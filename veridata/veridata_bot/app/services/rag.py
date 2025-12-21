import httpx
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models.integration import IntegrationConfig

logger = logging.getLogger(__name__)

async def get_client_config(db: AsyncSession, client_id: int, platform: str):
    result = await db.execute(select(IntegrationConfig).where(
        IntegrationConfig.client_id == client_id,
        IntegrationConfig.platform == platform
    ))
    config = result.scalar_one_or_none()
    return config.settings if config else {}

class RagService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def forward_message(self, client_id: int, message: str, conversation_id: str, sender_id: str):
        config = await get_client_config(self.db, client_id, "rag")
        rag_url = config.get("url")
        api_key = config.get("api_key")
        tenant_id = config.get("tenant_id")
        provider = config.get("provider", "gemini")

        if not rag_url:
            logger.error(f"RAG URL not configured for client {client_id}")
            return None

        if not tenant_id:
            logger.error(f"RAG Tenant ID not configured for client {client_id}")
            return None

        # Log configuration (masking api key)
        logger.info(f"Forwarding to RAG: URL={rag_url}, Tenant={tenant_id}, Provider={provider}, ConvID={conversation_id}")

        async with httpx.AsyncClient() as client:
            try:
                headers = {
                    "Content-Type": "application/json"
                }
                if api_key:
                    # Basic or Bearer? User curl showed "Basic YWRtaW46YWRtaW4=", which is admin:admin base64.
                    # If user enters "Basic ...", use it directly. If just key, maybe Bearer?
                    # User example: Authorization: Basic ...
                    # Let's assume user puts full token or handle "Basic" prefix logic.
                    if api_key.startswith("Basic ") or api_key.startswith("Bearer "):
                         headers["Authorization"] = api_key
                    else:
                         headers["Authorization"] = f"Bearer {api_key}"

                import uuid
                # Generate a deterministic UUID based on conversation_id
                # This ensures the same chatwoot conversation always gets the same RAG session UUID
                session_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"chatwoot_{conversation_id}"))

                payload = {
                    "query": message,
                    "session_id": session_uuid,
                    "tenant_id": tenant_id,
                    "provider": provider,
                    "use_hyde": True,
                    "use_rerank": True
                }

                logger.info(f"RAG Payload: {payload}")

                response = await client.post(rag_url, json=payload, headers=headers)
                response.raise_for_status()

                resp_json = response.json()
                logger.info(f"RAG Response: {resp_json}")

                # Map RAG response standard to what we need
                # User example response: { "answer": "...", "requires_human": true, ... }
                return {
                    "response": resp_json.get("answer", ""),
                    "human_needed": resp_json.get("requires_human", False)
                }

            except Exception as e:
                logger.error(f"Error forwarding to RAG: {e}")
                return None
