from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models import Client, Subscription, ServiceConfig, BotSession
from app.integrations.rag import RagClient
from app.integrations.chatwoot import ChatwootClient
from app.integrations.espocrm import EspoClient
import uuid
import logging
import httpx
from app.core.logging import log_start, log_payload, log_skip, log_success, log_error, log_external_call, log_db

logger = logging.getLogger(__name__)

async def _get_client_and_config(client_slug: str, db: AsyncSession):
    # 1. Validate Client
    query = select(Client).where(Client.slug == client_slug, Client.is_active == True)
    result = await db.execute(query)
    client = result.scalars().first()

    if not client:
        log_error(logger, f"Client not found or inactive: {client_slug}")
        raise HTTPException(status_code=404, detail="Client not found or inactive")

    # 2. Get Configs
    cfg_query = select(ServiceConfig).where(ServiceConfig.client_id == client.id)
    cfg_result = await db.execute(cfg_query)
    configs = {c.platform: c.config for c in cfg_result.scalars().all()}

    return client, configs

async def process_integration_event(client_slug: str, payload: dict, db: AsyncSession):
    log_start(logger, f"Processing Integration Event for {client_slug}")

    try:
        client, configs = await _get_client_and_config(client_slug, db)
        espo_config = configs.get("espocrm")

        event_type = payload.get("event")
        # log_payload(logger, payload, f"Integration Event: {event_type}")

        if event_type == "conversation_created":
            if espo_config:
                sender = payload.get("meta", {}).get("sender", {}) or payload.get("sender", {})
                email = sender.get("email")
                phone = sender.get("phone_number")
                name = sender.get("name", "Unknown")

                if email or phone:
                    try:
                        log_external_call(logger, "EspoCRM", "Syncing lead for new conversation")
                        espo = EspoClient(
                            base_url=espo_config["base_url"],
                            api_key=espo_config["api_key"]
                        )
                        await espo.sync_lead(name=name, email=email, phone_number=phone)
                        log_success(logger, f"Lead synced: {email or phone}")
                    except Exception as e:
                        log_error(logger, f"CRM Sync failed for conversation_created: {e}")
                else:
                    log_skip(logger, "Skipping CRM sync: No email or phone provided")
            else:
                log_skip(logger, "Skipping CRM sync: EspoCRM not configured")

            return {"status": "conversation_created_processed"}

        return {"status": "ignored_event"}
    except Exception as e:
        log_error(logger, f"Integration event processing failed: {e}", exc_info=True)
        return {"status": "error"}

async def process_bot_event(client_slug: str, payload: dict, db: AsyncSession):
    log_start(logger, f"Processing Bot Event for {client_slug}")
    # log_payload(logger, payload, "Bot Event Payload")

    # 1. Get Client & Config
    client, configs = await _get_client_and_config(client_slug, db)

    # Check Subscription
    sub_query = select(Subscription).where(
        Subscription.client_id == client.id,
        Subscription.usage_count < Subscription.quota_limit
    )
    # Also check dates if needed, skipping for brevity but recommended
    sub_result = await db.execute(sub_query)
    subscription = sub_result.scalars().first()

    if not subscription:
        log_error(logger, f"Subscription limit reached for {client_slug}")
        # Optionally send a message saying "quota exceeded"
        return {"status": "quota_exceeded"}

    rag_config = configs.get("rag")
    chatwoot_config = configs.get("chatwoot")
    # espo_config logic removed from bot flow (kept only for syncing via integration webhook if needed separately, but primary sync is now in integration handler)
    espo_config = configs.get("espocrm")

    if not rag_config or not chatwoot_config:
        log_error(logger, f"Missing configs for {client_slug}. Found: {list(configs.keys())}")
        raise HTTPException(status_code=500, detail="Configuration missing")

    # Extract info from payload
    # Assuming Chatwoot webhook payload structure
    # event_type = widget_triggered, message_created etc.
    event_type = payload.get("event")

    if event_type != "message_created":
        log_skip(logger, f"Ignored event type: {event_type}")
        return {"status": "ignored_event"}

    message_data = payload.get("content", "")
    conversation_id = str(payload.get("conversation", {}).get("id"))
    sender = payload.get("sender", {})
    sender_type = payload.get("message_type") # incoming / outgoing

    logger.info(f"Message from {sender_type} in conversation {conversation_id}")

    if sender_type != "incoming":
        log_skip(logger, "Ignored outgoing message")
        return {"status": "ignored_outgoing"}

    conversation_status = payload.get("conversation", {}).get("status")
    if conversation_status == "open" or conversation_status == "snoozed":
        log_skip(logger, f"Ignored conversation with status: {conversation_status}")
        return {"status": "ignored_open_conversation"}

    user_query = payload.get("content")
    attachments = payload.get("attachments", [])
    logger.info(f"Received {len(attachments)} attachments")

    if not user_query and attachments:
        # Try to find audio attachment
        for att in attachments:
             file_type = att.get("file_type")
             data_url = att.get("data_url")
             logger.info(f"Processing attachment: type={file_type}, url={data_url}")

             if file_type == "audio":
                 filename = f"audio.{att.get('extension', 'mp3')}"
                 logger.info(f"Found audio attachment. Downloading from: {data_url}")

                 try:
                     async with httpx.AsyncClient(follow_redirects=True) as http_client:
                         # Download audio
                         log_external_call(logger, "Internal/Web", f"Downloading audio from {data_url}")
                         resp = await http_client.get(data_url)
                         resp.raise_for_status()
                         audio_bytes = resp.content
                         logger.info(f"Download complete. Size: {len(audio_bytes)} bytes")

                         # Transcribe
                         rag_client = RagClient(
                            base_url=rag_config["base_url"],
                            api_key=rag_config.get("api_key", ""),
                            tenant_id=rag_config["tenant_id"]
                         )

                         log_external_call(logger, "RAG Transcribe", "Sending audio for transcription")
                         transcript = await rag_client.transcribe(audio_bytes, filename)
                         log_success(logger, f"Transcription result: '{transcript}'")

                         if transcript:
                             user_query = transcript
                             break # One audio per message supported for now
                 except Exception as e:
                     log_error(logger, f"Failed to process audio attachment: {e}", exc_info=True)

    if not user_query:
         log_skip(logger, "Empty message content and no valid audio transcription")
         return {"status": "empty_message"}

    # 3. Session Management
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

    # 4. RAG Call
    # Extract optional params from config
    rag_provider = rag_config.get("provider")
    rag_use_hyde = rag_config.get("use_hyde")
    rag_use_rerank = rag_config.get("use_rerank")

    rag_client = RagClient(
        base_url=rag_config["base_url"],
        api_key=rag_config.get("api_key", ""), # Safe get
        tenant_id=rag_config["tenant_id"]
    )

    try:
        # Prepare kwargs
        query_params = {}
        if rag_provider: query_params["provider"] = rag_provider
        if rag_use_hyde is not None: query_params["use_hyde"] = rag_use_hyde
        if rag_use_rerank is not None: query_params["use_rerank"] = rag_use_rerank

        log_external_call(logger, "Veridata RAG", f"Query: '{user_query}' | Params: {query_params}")
        rag_response = await rag_client.query(
            message=user_query,
            session_id=session.rag_session_id,
            **query_params
        )
        log_success(logger, "RAG response received successfully")
    except Exception as e:
        log_error(logger, f"RAG Error: {e}", exc_info=True)
        return {"status": "rag_error"}

    answer = rag_response.get("answer")
    requires_human = rag_response.get("requires_human", False)
    new_rag_session_id = rag_response.get("session_id")

    # Update session if needed
    if new_rag_session_id and str(new_rag_session_id) != str(session.rag_session_id):
        log_db(logger, f"Updating RAG session ID to {new_rag_session_id}")
        session.rag_session_id = uuid.UUID(new_rag_session_id)
        db.add(session) # Mark for update

    # 5. Send to Chatwoot
    cw_client = ChatwootClient(
        base_url=chatwoot_config["base_url"],
        api_token=chatwoot_config["api_key"],
        account_id=chatwoot_config.get("account_id", 1)
    )

    if answer:
        # If conversation was resolved, reopen it as pending
        if conversation_status == "resolved":
            try:
                log_external_call(logger, "Chatwoot", f"Reopening resolved conversation {conversation_id}")
                await cw_client.toggle_status(conversation_id, "pending")
            except Exception as e:
                log_error(logger, f"Failed to set status to pending for {conversation_id}: {e}")

        log_external_call(logger, "Chatwoot", f"Sending response to conversation {conversation_id}")
        await cw_client.send_message(
            conversation_id=conversation_id,
            message=answer
        )
        log_success(logger, "Response sent to Chatwoot")
    else:
        log_skip(logger, "RAG returned no answer (empty response)")

    # Handle Handover
    if requires_human:
         log_start(logger, f"Handover requested for session {conversation_id}")
         try:
             await cw_client.toggle_status(conversation_id, "open")
             log_success(logger, "Conversation opened for human agent")
         except Exception as e:
             log_error(logger, f"Failed to toggle status for {conversation_id}: {e}")

    # Increment Usage
    subscription.usage_count += 1
    db.add(subscription)
    await db.commit()

    # 6. CRM Sync
    # Removed from Bot Flow - moved to Integration Flow

    log_success(logger, "Bot Event Processed Successfully")
    return {"status": "processed"}
