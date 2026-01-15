import logging

from fastapi import HTTPException
from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.graph import agent_app
from app.bot.actions import (
    check_subscription_quota,
    execute_crm_action,
    get_client_and_config,
    get_crm_integrations,
    handle_audio_message,
    handle_chatwoot_response,
    handle_conversation_resolution,
)
from app.core.logging import log_db, log_error, log_skip, log_start, log_success
from app.integrations.rag import RagClient
from app.models.session import BotSession
from app.schemas.events import ChatwootEvent, IntegrationEvent

logger = logging.getLogger(__name__)


async def process_integration_event(client_slug: str, payload_dict: dict, db: AsyncSession):
    log_start(logger, f"Processing Integration Event for {client_slug}")

    try:
        # ==================================================================================
        # STEP 1: VALIDATE PAYLOAD
        # Ensure the incoming webhook payload matches our expected schema (IntegrationEvent).
        # ==================================================================================
        try:
            event = IntegrationEvent(**payload_dict)
        except Exception as e:
            log_error(logger, f"Invalid Payload: {e}")
            return {"status": "invalid_payload"}

        # ==================================================================================
        # STEP 2: LOAD CLIENT & CRM CONFIGURATIONS
        # access the database to get client details and active CRM credentials (HubSpot, EspoCRM, etc.)
        # ==================================================================================
        client, configs = await get_client_and_config(client_slug, db)

        crms = get_crm_integrations(configs)

        # ==================================================================================
        # STEP 3: HANDLE "CONVERSATION CREATED" (New Lead)
        # When a new conversation starts, we treat the user as a potential Lead.
        # We sync their Name, Email, and Phone to all connected CRMs.
        # ==================================================================================
        if event.event == "conversation_created":
            if crms:
                sender = event.effective_sender
                if sender and (sender.email or sender.phone_number):
                    await execute_crm_action(
                        crms,
                        "lead",
                        lambda crm: crm.sync_lead(
                            name=sender.name, email=sender.email, phone_number=sender.phone_number
                        ),
                    )
                else:
                    log_skip(logger, "Skipping CRM sync: No email or phone provided")
            else:
                log_skip(logger, "Skipping CRM sync: No CRM configured")

            return {"status": "conversation_created_processed"}

        # ==================================================================================
        # STEP 4: HANDLE "CONTACT UPDATED"
        # If a contact's details change in Chatwoot, we mirror those changes to the CRM.
        # ==================================================================================
        elif event.event in ("contact_created", "contact_updated"):
            if crms:
                await execute_crm_action(crms, f"contact ({event.event})", lambda crm: crm.sync_contact(payload_dict))
            else:
                log_skip(logger, "Skipping CRM sync: No CRM configured")

            return {"status": "contact_event_processed"}

        # ==================================================================================
        # STEP 5: HANDLE "CONVERSATION RESOLVED"
        # This is critical for the RAG/Summarization loop.
        # When a ticket is marked "Resolved":
        # 1. We fetch the full chat history.
        # 2. We use an LLM to generate a summary (Issue, Resolution, Sentiment).
        # 3. We push this summary to the Client's CRM note/timeline.
        # ==================================================================================
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

    # ==================================================================================
    # STEP 1: VALIDATE PAYLOAD
    # Convert the raw JSON payload into a strict Pydantic model (ChatwootEvent).
    # If this fails, the payload is malformed, and we stop immediately.
    # ==================================================================================
    try:
        event = ChatwootEvent(**payload_dict)
    except Exception as e:
        log_error(logger, f"Invalid Bot Payload: {e}")
        return {"status": "invalid_payload"}

    # ==================================================================================
    # STEP 2: LOAD CLIENT & CONFIGURATION
    # Fetch the Client and its ServiceConfigs (RAG settings, Chatwoot credentials, etc.)
    # from the database based on the 'client_slug'.
    # ==================================================================================
    client, configs = await get_client_and_config(client_slug, db)

    # ==================================================================================
    # STEP 3: CHECK SUBSCRIPTION QUOTA
    # Ensure the client has not exceeded their monthly message limit.
    # If quota is exceeded, we return early and the bot stays silent.
    # ==================================================================================
    subscription = await check_subscription_quota(client.id, client_slug, db)
    if not subscription:
        return {"status": "quota_exceeded"}

    # Extract specific configs for easy access
    rag_config = configs.get("rag")
    chatwoot_config = configs.get("chatwoot")

    # Validate that essential configurations exist
    if not rag_config or not chatwoot_config:
        log_error(logger, f"Missing configs for {client_slug}. Found: {list(configs.keys())}")
        raise HTTPException(status_code=500, detail="Configuration missing")

    # ==================================================================================
    # STEP 4: FILTER EVENTS
    # We only care about:
    # 1. Incoming messages (from users, not bot)
    # 2. Private messages or public tweets depending on valid command logic
    # 3. Conversations that are NOT already 'snoozed' or 'open' (handled by humans)
    # ==================================================================================
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

    # Basic Message Data
    conversation_id = event.conversation_id
    user_query = event.content
    logger.info(f"Message from {event.message_type} in conversation {conversation_id}")

    # ==================================================================================
    # STEP 5: HANDLE AUDIO ATTACHMENTS (Voice Notes)
    # If the message has no text but has audio, we download and transcribe it locally.
    # ==================================================================================
    if not user_query and event.attachments:
        transcript = await handle_audio_message(event.attachments, rag_config)
        if transcript:
            user_query = transcript

    # If still empty (e.g. image only, or empty audio), skip.
    if not user_query:
        log_skip(logger, "Empty message content and no valid audio transcription")
        return {"status": "empty_message"}

    # ==================================================================================
    # STEP 6: SESSION MANAGEMENT
    # Find the existing BotSession map (External Chatwoot ID <-> Internal BotSession).
    # If none exists, create a new one.
    # ==================================================================================
    session_query = select(BotSession).where(
        BotSession.client_id == client.id, BotSession.external_session_id == conversation_id
    )

    sess_result = await db.execute(session_query)
    session = sess_result.scalars().first()

    if not session:
        log_start(logger, f"Creating new BotSession for conversation {conversation_id}")
        session = BotSession(client_id=client.id, external_session_id=conversation_id)
        db.add(session)
        await db.commit()
        await db.refresh(session)
    else:
        log_db(logger, f"Found existing BotSession: {session.id}, RAG ID: {session.rag_session_id}")

    # ==================================================================================
    # STEP 7: BUILD CONVERSATION HISTORY
    # If this session is linked to a RAG session, fetch previous messages from the RAG Service.
    # This gives the Agent "Long Term Memory".
    # ==================================================================================
    history_messages = []
    if session and session.rag_session_id:
        try:
            rag_client = RagClient(
                base_url=rag_config["base_url"],
                api_key=rag_config.get("api_key", ""),
                tenant_id=rag_config["tenant_id"],
            )
            history_data = await rag_client.get_history(session.rag_session_id)
            for msg in history_data:
                if msg["role"] == "user":
                    history_messages.append(HumanMessage(content=msg["content"]))
                elif msg["role"] == "ai":
                    history_messages.append(AIMessage(content=msg["content"]))
        except Exception as e:
            logger.warning(f"Failed to fetch chat history: {e}")

    # Combine History + Current Message
    full_messages = history_messages + [HumanMessage(content=user_query)]

    # ==================================================================================
    # STEP 8: EXECUTE AGENT (LangGraph)
    # 1. Router Node: Decides usage (RAG vs Human Handoff).
    # 2. Execution Node: Runs RAG query or generates Handoff message.
    # 3. Output: Returns final Answer and Metadata (requires_human).
    # ==================================================================================
    initial_state = {
        "messages": full_messages,
        "tenant_id": rag_config.get("tenant_id"),
        "session_id": str(session.rag_session_id) if session.rag_session_id else None,
        "google_sheets_url": rag_config.get("google_sheets_url"),
        "client_slug": client_slug,
    }

    logger.info(f"DEBUG: Graph Input Messages: {[m.content for m in full_messages]}")

    try:
        from langfuse.langchain import CallbackHandler

        # Prepare Langfuse Context (Session & User)
        lf_user_id = "unknown_user"
        if event.sender:
            # Priority: Email -> Phone -> ID -> Name
            if event.sender.email:
                lf_user_id = event.sender.email
            elif event.sender.phone_number:
                lf_user_id = event.sender.phone_number
            elif event.sender.id:
                lf_user_id = str(event.sender.id)
            elif event.sender.name:
                lf_user_id = event.sender.name

        # Use Chatwoot Conversation ID as the Trace Session
        lf_session_id = conversation_id or "unknown_session"

        langfuse_handler = CallbackHandler()

        # Pass context via metadata (Langfuse specific keys)
        result = await agent_app.ainvoke(
            initial_state,
            config={
                "callbacks": [langfuse_handler],
                "metadata": {
                    "langfuse_user_id": lf_user_id,
                    "langfuse_session_id": lf_session_id,
                },
            },
        )
        answer = result["messages"][-1].content
        logger.info(f"DEBUG: Agent Answer: {answer}")

        requires_human = result.get("requires_human", False)
        rag_session_id = result.get("session_id")

        # Persist RAG Session ID if newly created
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

    # ==================================================================================
    # STEP 9: SEND RESPONSE TO CHATWOOT
    # Send the agent's answer back to the user via Chatwoot API.
    # If 'requires_human' is True, also toggle conversation status to Open.
    # ==================================================================================
    await handle_chatwoot_response(conversation_id, answer, requires_human, chatwoot_config)

    # ==================================================================================
    # STEP 10: UPDATE USAGE QUOTA
    # Increment the usage count for this client's subscription.
    # ==================================================================================
    subscription.usage_count += 1
    db.add(subscription)
    db.add(session)
    await db.commit()

    log_success(logger, "Bot Event Processed Successfully")
    return {"status": "processed"}
