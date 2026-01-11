from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from app.models.session import BotSession
from app.models.subscription import Subscription
from app.agent.graph import agent_app
from langchain_core.messages import HumanMessage, AIMessage
import logging
import uuid
from app.core.logging import log_start, log_skip, log_success, log_error, log_db

from app.bot.actions import (
    get_client_and_config,
    get_crm_integrations,
    check_subscription_quota,
    execute_crm_action,
    handle_audio_message,
    query_rag_system,
    handle_chatwoot_response,
    handle_conversation_resolution
)
from app.integrations.rag import RagClient
from app.schemas.events import IntegrationEvent, ChatwootEvent

logger = logging.getLogger(__name__)

async def process_integration_event(client_slug: str, payload_dict: dict, db: AsyncSession):
    log_start(logger, f"Processing Integration Event for {client_slug}")

    try:
        try:
            event = IntegrationEvent(**payload_dict)
        except Exception as e:
            log_error(logger, f"Invalid Payload: {e}")
            return {"status": "invalid_payload"}

        client, configs = await get_client_and_config(client_slug, db)

        crms = get_crm_integrations(configs)

        if event.event == "conversation_created":
            if crms:
                sender = event.effective_sender
                if sender and (sender.email or sender.phone_number):
                     await execute_crm_action(crms, "lead",
                        lambda crm: crm.sync_lead(name=sender.name, email=sender.email, phone_number=sender.phone_number)
                     )
                else:
                    log_skip(logger, "Skipping CRM sync: No email or phone provided")
            else:
                log_skip(logger, "Skipping CRM sync: No CRM configured")

            return {"status": "conversation_created_processed"}

        elif event.event in ("contact_created", "contact_updated"):
            if crms:
                 await execute_crm_action(crms, f"contact ({event.event})",
                    lambda crm: crm.sync_contact(payload_dict)
                 )
            else:
                 log_skip(logger, "Skipping CRM sync: No CRM configured")

            return {"status": "contact_event_processed"}

        elif event.event == "conversation_status_changed":
            status = payload_dict.get("status")
            if isinstance(event.content, dict):
                 status = event.content.get("status", status)
                 conversation_data = event.content
            else:
                 conversation_data = payload_dict.get("content", payload_dict)

            if status == "resolved":
                log_start(logger, "Conversation resolved. Initiating Summarization & Sync.")

                sender = event.effective_sender
                await handle_conversation_resolution(client, configs, conversation_data, sender, db)
                return {"status": "conversation_status_processed"}

        return {"status": "ignored_event"}
    except Exception as e:
        log_error(logger, f"Integration event processing failed: {e}", exc_info=True)
        return {"status": "error"}


async def process_bot_event(client_slug: str, payload_dict: dict, db: AsyncSession):
    log_start(logger, f"Processing Bot Event for {client_slug}")

    try:
        event = ChatwootEvent(**payload_dict)
    except Exception as e:
        log_error(logger, f"Invalid Bot Payload: {e}")
        return {"status": "invalid_payload"}

    client, configs = await get_client_and_config(client_slug, db)

    subscription = await check_subscription_quota(client.id, client_slug, db)
    if not subscription:
        return {"status": "quota_exceeded"}

    rag_config = configs.get("rag")
    chatwoot_config = configs.get("chatwoot")

    if not rag_config or not chatwoot_config:
        log_error(logger, f"Missing configs for {client_slug}. Found: {list(configs.keys())}")
        raise HTTPException(status_code=500, detail="Configuration missing")

    if not event.is_valid_bot_command:
         if event.event != "message_created":
             log_skip(logger, f"Ignored event type: {event.event}")
             return {"status": "ignored_event"}
         if not event.is_incoming:
             log_skip(logger, "Ignored outgoing message")
             return {"status": "ignored_outgoing"}
         if event.conversation and event.conversation.status in ("snoozed", "open"):
             log_skip(logger, f"Ignored conversation with status: {event.conversation.status}")
             return {"status": f"ignored_{event.conversation.status}"}

         return {"status": "ignored_generic"}

    conversation_id = event.conversation_id
    user_query = event.content
    logger.info(f"Message from {event.message_type} in conversation {conversation_id}")

    if not user_query and event.attachments:
        transcript = await handle_audio_message(event.attachments, rag_config)
        if transcript:
            user_query = transcript

    if not user_query:
         log_skip(logger, "Empty message content and no valid audio transcription")
         return {"status": "empty_message"}

    session_query = select(BotSession).where(
        BotSession.client_id == client.id,
        BotSession.external_session_id == conversation_id
    )
    sess_result = await db.execute(session_query)
    session = sess_result.scalars().first()

    if not session:
        log_start(logger, f"Creating new BotSession for conversation {conversation_id}")
        session = BotSession(
            client_id=client.id,
            external_session_id=conversation_id
        )
        db.add(session)
        await db.commit()
        await db.refresh(session)
    else:
        log_db(logger, f"Found existing BotSession: {session.id}, RAG ID: {session.rag_session_id}")

    history_messages = []
    if session and session.rag_session_id:
        try:
             rag_client = RagClient(
                base_url=rag_config["base_url"],
                api_key=rag_config.get("api_key", ""),
                tenant_id=rag_config["tenant_id"]
             )
             history_data = await rag_client.get_history(session.rag_session_id)
             for msg in history_data:
                 if msg["role"] == "user":
                     history_messages.append(HumanMessage(content=msg["content"]))
                 elif msg["role"] == "ai":
                     history_messages.append(AIMessage(content=msg["content"]))
        except Exception as e:
             logger.warning(f"Failed to fetch chat history: {e}")

    full_messages = history_messages + [HumanMessage(content=user_query)]

    initial_state = {
        "messages": full_messages,
        "tenant_id": rag_config.get("tenant_id"),
        "session_id": str(session.rag_session_id) if session.rag_session_id else None,
        "google_sheets_url": rag_config.get("google_sheets_url")
    }

    logger.info(f"DEBUG: Graph Input Messages: {[m.content for m in full_messages]}")

    try:
        result = await agent_app.ainvoke(initial_state)
        answer = result["messages"][-1].content
        logger.info(f"DEBUG: Agent Answer: {answer}")
        requires_human = result.get("requires_human", False)
        rag_session_id = result.get("session_id")
        if rag_session_id:
            try:
                import uuid
                rag_uuid = uuid.UUID(str(rag_session_id))
                stmt = update(BotSession).where(BotSession.id == session.id).values(rag_session_id=rag_uuid)
                await db.execute(stmt)
                await db.commit()
                session.rag_session_id = rag_uuid
                logger.info(f"💾 Persisted RAG Session ID via SQL: {rag_session_id}")
            except Exception as e:
                logger.warning(f"Failed to persist RAG Session ID: {e}")

    except Exception as e:
        logger.error(f"LangGraph execution failed: {e}", exc_info=True)
        return {"status": "agent_error"}

    await handle_chatwoot_response(conversation_id, answer, requires_human, chatwoot_config)

    subscription.usage_count += 1
    db.add(subscription)
    db.add(session)
    await db.commit()

    log_success(logger, "Bot Event Processed Successfully")
    return {"status": "processed"}
