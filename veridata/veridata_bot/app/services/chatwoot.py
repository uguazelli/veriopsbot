import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models.integration import IntegrationConfig
import logging

logger = logging.getLogger(__name__)

async def get_client_config(db: AsyncSession, client_id: int, platform: str):
    result = await db.execute(select(IntegrationConfig).where(
        IntegrationConfig.client_id == client_id,
        IntegrationConfig.platform == platform
    ))
    config = result.scalar_one_or_none()
    return config.settings if config else {}

class ChatwootService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def send_message(self, client_id: int, conversation_id: str, message: str):
        config = await get_client_config(self.db, client_id, "chatwoot")
        base_url = config.get("url")
        api_token = config.get("api_token")
        account_id = config.get("account_id")

        if not all([base_url, api_token, account_id]):
            logger.error(f"Chatwoot configuration missing for client {client_id}")
            return False

        url = f"{base_url}/api/v1/accounts/{account_id}/conversations/{conversation_id}/messages"
        headers = {"api_access_token": api_token}

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, json={"content": message, "message_type": "outgoing"}, headers=headers)
                response.raise_for_status()
                return True
            except Exception as e:
                logger.error(f"Error sending message to Chatwoot: {e}")
                return False
