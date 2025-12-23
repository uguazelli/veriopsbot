from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models import Client, Subscription, ServiceConfig, BotSession
from app.integrations.rag import RagClient
from app.integrations.chatwoot import ChatwootClient
from app.integrations.espocrm import EspoClient
import uuid
import logging

logger = logging.getLogger(__name__)

async def process_webhook(client_slug: str, payload: dict, db: AsyncSession):
    # 1. Validate Client & Subscription
    query = select(Client).where(Client.slug == client_slug, Client.is_active == True)
    result = await db.execute(query)
    client = result.scalars().first()

    if not client:
        raise HTTPException(status_code=404, detail="Client not found or inactive")

    # Check Subscription
    sub_query = select(Subscription).where(
        Subscription.client_id == client.id,
        Subscription.usage_count < Subscription.quota_limit
    )
    # Also check dates if needed, skipping for brevity but recommended
    sub_result = await db.execute(sub_query)
    subscription = sub_result.scalars().first()

    if not subscription:
        logger.warning(f"Subscription limit reached for {client_slug}")
        # Optionally send a message saying "quota exceeded"
        return {"status": "quota_exceeded"}

    # 2. Get Configs
    cfg_query = select(ServiceConfig).where(ServiceConfig.client_id == client.id)
    cfg_result = await db.execute(cfg_query)
    configs = {c.platform: c.config for c in cfg_result.scalars().all()}

    rag_config = configs.get("rag")
    chatwoot_config = configs.get("chatwoot")
    espo_config = configs.get("espocrm")

    if not rag_config or not chatwoot_config:
        logger.error(f"Missing configs for {client_slug}")
        raise HTTPException(status_code=500, detail="Configuration missing")

    # Extract info from payload
    # Assuming Chatwoot webhook payload structure
    # event_type = widget_triggered, message_created etc.
    event_type = payload.get("event")
    if event_type != "message_created":
        return {"status": "ignored_event"}

    message_data = payload.get("content", "")
    conversation_id = str(payload.get("conversation", {}).get("id"))
    sender = payload.get("sender", {})
    sender_type = payload.get("message_type") # incoming / outgoing

    if sender_type != "incoming":
        return {"status": "ignored_outgoing"}

    user_query = payload.get("content")

    if not user_query:
         return {"status": "empty_message"}

    # 3. Session Management
    session_query = select(BotSession).where(
        BotSession.client_id == client.id,
        BotSession.external_session_id == conversation_id
    )
    sess_result = await db.execute(session_query)
    session = sess_result.scalars().first()

    if not session:
        session = BotSession(
            client_id=client.id,
            external_session_id=conversation_id
        )
        db.add(session)
        await db.commit()
        await db.refresh(session)

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

        rag_response = await rag_client.query(
            message=user_query,
            session_id=session.rag_session_id,
            **query_params
        )
    except Exception as e:
        logger.error(f"RAG Error: {e}")
        return {"status": "rag_error"}

    answer = rag_response.get("answer")
    requires_human = rag_response.get("requires_human", False)
    new_rag_session_id = rag_response.get("session_id")

    # Update session if needed
    if new_rag_session_id and str(new_rag_session_id) != str(session.rag_session_id):
        session.rag_session_id = uuid.UUID(new_rag_session_id)
        db.add(session) # Mark for update

    # 5. Send to Chatwoot
    cw_client = ChatwootClient(
        base_url=chatwoot_config["base_url"],
        api_token=chatwoot_config["api_key"]
    )

    if answer:
        await cw_client.send_message(
            conversation_id=conversation_id,
            message=answer
        )

    # Handle Handover
    if requires_human:
         # Optionally toggle status in Chatwoot
         # await cw_client.toggle_status(conversation_id, "open")
         logger.info(f"Handover requested for session {conversation_id}")
         # TODO: Implement toggle_status in ChatwootClient if needed
         pass

    # Increment Usage
    subscription.usage_count += 1
    db.add(subscription)
    await db.commit()

    # 6. CRM Sync (Best effort)
    if espo_config:
        try:
            espo = EspoClient(
                base_url=espo_config["base_url"],
                api_key=espo_config["api_key"]
            )
            email = sender.get("email")
            name = sender.get("name", "Unknown")
            if email:
                await espo.sync_lead(name=name, email=email)
        except Exception as e:
            logger.error(f"CRM Sync failed: {e}")

    return {"status": "processed"}
