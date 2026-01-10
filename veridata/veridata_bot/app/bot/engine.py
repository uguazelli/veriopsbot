from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models import Subscription, BotSession
import logging
import uuid
from app.core.logging import log_start, log_skip, log_success, log_error, log_db

# Import Actions
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
from app.bot.schemas import IntegrationEvent, ChatwootEvent

logger = logging.getLogger(__name__)

async def process_integration_event(client_slug: str, payload_dict: dict, db: AsyncSession):
    log_start(logger, f"Processing Integration Event for {client_slug}")

    try:
        # Validate Payload
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
                 # Pass raw dict for compatibility if needed, or define strict schema later
                 await execute_crm_action(crms, f"contact ({event.event})",
                    lambda crm: crm.sync_contact(payload_dict)
                 )
            else:
                 log_skip(logger, "Skipping CRM sync: No CRM configured")

            return {"status": "contact_event_processed"}

        elif event.event == "conversation_status_changed":
            # Support both dict access (event.content) and raw payload fallback for status
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

    # 0. Validate Payload
    try:
        event = ChatwootEvent(**payload_dict)
    except Exception as e:
        log_error(logger, f"Invalid Bot Payload: {e}")
        return {"status": "invalid_payload"}

    # 1. Get Client & Config
    client, configs = await get_client_and_config(client_slug, db)

    # Check Subscription
    subscription = await check_subscription_quota(client.id, client_slug, db)
    if not subscription:
        return {"status": "quota_exceeded"}

    rag_config = configs.get("rag")
    chatwoot_config = configs.get("chatwoot")

    if not rag_config or not chatwoot_config:
        log_error(logger, f"Missing configs for {client_slug}. Found: {list(configs.keys())}")
        raise HTTPException(status_code=500, detail="Configuration missing")

    # 2. Validation Checks
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

    # 3. Handle Audio
    if not user_query and event.attachments:
        transcript = await handle_audio_message(event.attachments, rag_config)
        if transcript:
            user_query = transcript

    if not user_query:
         log_skip(logger, "Empty message content and no valid audio transcription")
         return {"status": "empty_message"}

    # 4. Session Management
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

    # 5. LangGraph Execution (Replaces direct RAG Call)
    # Import agent app here to avoid circular dependencies if any (or move to top if clean)
    from app.agent.graph import agent_app
    from langchain_core.messages import HumanMessage

    initial_state = {
        "messages": [HumanMessage(content=user_query)],
        "tenant_id": rag_config.get("tenant_id"),
        "session_id": str(session.rag_session_id) if session.rag_session_id else None,
        "google_sheets_url": rag_config.get("google_sheets_url")
    }

    try:
        # Invoke the graph
        result = await agent_app.ainvoke(initial_state)

        # Extract Results
        # The last message is the AI response
        answer = result["messages"][-1].content

        # Check flags in state
        requires_human = result.get("requires_human", False)

        # Note: For now, we don't get a "new_session_id" back from LangGraph explicitly unless RAG returned it
        # But RAG service interactions are stateless via the node unless we persist context there.
        # The session.rag_session_id we sent is what we expect to keep using.

    except Exception as e:
        logger.error(f"LangGraph execution failed: {e}", exc_info=True)
        return {"status": "agent_error"}

    # Update session if needed (Currently LangGraph implementation assumes stable session ID passed in)
    # Legacy logic checked for new session ID. We can probably skip this unless RAG creates one.
    # If rag_node creates one, it's not currently bubbling up unless we update rag_node to return it in state.
    # For now, we assume session ID persists.

    # 6. Send to Chatwoot
    await handle_chatwoot_response(conversation_id, answer, requires_human, chatwoot_config)

    # Increment Usage
    subscription.usage_count += 1
    db.add(subscription)
    await db.commit()

    log_success(logger, "Bot Event Processed Successfully")
    return {"status": "processed"}
