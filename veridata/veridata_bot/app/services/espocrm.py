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

class EspoCRMService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_contact(self, client_id: int, contact_data: dict):
        config = await get_client_config(self.db, client_id, "espocrm")
        base_url = config.get("url")
        api_key = config.get("api_key")

        if not base_url or not api_key:
            logger.error(f"EspoCRM configuration missing for client {client_id}")
            return None

        url = f"{base_url}/api/v1/Contact"
        headers = {"X-Api-Key": api_key}

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, json=contact_data, headers=headers)
                response.raise_for_status()
                return response.json()
            except Exception as e:
                logger.error(f"Error creating contact in EspoCRM: {e}")
                return None
