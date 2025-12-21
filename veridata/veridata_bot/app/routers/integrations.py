from fastapi import APIRouter, Depends, BackgroundTasks, Request
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db, SessionLocal
from app.services.rag import RagService
from app.services.chatwoot import ChatwootService
from app.services.espocrm import EspoCRMService
import logging

router = APIRouter(prefix="/integrations", tags=["integrations"])
logger = logging.getLogger(__name__)

from app.models.integration import IntegrationConfig
from sqlalchemy import select, func

async def process_chatwoot_message_bg(payload: dict, client_id: int | None):
    """
    Background task to process Chatwoot message.
    Creates its own DB session to avoid detached instances.
    Resolves client_id from account_id if not provided.
    """
    async with SessionLocal() as db:
        # Resolve client_id if missing
        if client_id is None:
            account_data = payload.get("account", {})
            account_id = account_data.get("id")
            if account_id:
                # Find client_id by checking which integration has this account_id in settings
                # Note: settings is JSONB. We look for platform='chatwoot' and settings->>'account_id' == str(account_id)
                # Cast to text for comparison
                stmt = select(IntegrationConfig).where(
                    IntegrationConfig.platform == 'chatwoot',
                    func.jsonb_extract_path_text(IntegrationConfig.settings, 'account_id') == str(account_id)
                )
                result = await db.execute(stmt)
                config = result.scalars().first()
                if config:
                    client_id = config.client_id
                    logger.info(f"Resolved client_id={client_id} from account_id={account_id}")
                else:
                    logger.warning(f"No client found for Chatwoot account_id={account_id}")
                    return
            else:
                logger.warning("No client_id provided and no account_id in payload")
                return

        event = payload.get("event")
        msg_type = payload.get("message_type") # incoming, outgoing

        # We only care about incoming messages from users
        if event == "message_created" and msg_type == "incoming":
            conversation_id = payload.get("conversation", {}).get("id")
            message_content = payload.get("content")
            sender_id = payload.get("sender", {}).get("id")

            if not conversation_id or not message_content:
                logger.warning(f"Missing conv_id or content: {payload}")
                return

            logger.info(f"Processing message in background: {message_content} for conv {conversation_id}")

            rag_service = RagService(db)
            chatwoot_service = ChatwootService(db)

            try:
                # 1. Forward to RAG (pass client_id)
                rag_response = await rag_service.forward_message(client_id, message_content, str(conversation_id), str(sender_id))

                if rag_response and "response" in rag_response:
                    bot_reply = rag_response["response"]
                    logger.info(f"Bot reply: {bot_reply}")

                    # 2. Respond back to Chatwoot (pass client_id)
                    await chatwoot_service.send_message(client_id, str(conversation_id), bot_reply)
            except Exception as e:
                logger.error(f"Error in background task: {e}")

@router.post("/chatwoot/webhook")
async def chatwoot_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    client_id: int | None = None,
):
    try:
        payload = await request.json()
    except Exception:
        logger.warning("Received invalid JSON payload in webhook")
        return {"status": "error", "message": "Invalid JSON payload"}

    # Offload processing to background task
    background_tasks.add_task(process_chatwoot_message_bg, payload, client_id)

    # Return immediately to avoid Chatwoot timeout
    return {"status": "processing_started"}


@router.post("/sync/contact")
async def sync_contact(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    data = await request.json()
    return {"status": "not implemented yet"}
