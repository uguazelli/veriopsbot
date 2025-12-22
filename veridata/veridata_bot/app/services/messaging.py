from app.models.clients import Client, IntegrationConfig
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

class MessagingService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_client_by_telegram_token(self, token: str) -> Client | None:
        # JSONB query to match the token inside the settings dict
        stmt = (
            select(Client)
            .join(IntegrationConfig)
            .where(IntegrationConfig.platform_name == "telegram")
            .where(IntegrationConfig.settings["bot_token"].astext == token)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_integration_config(self, client_id: int, platform: str) -> IntegrationConfig | None:
        result = await self.db.execute(
            select(IntegrationConfig)
            .where(IntegrationConfig.client_id == client_id)
            .where(IntegrationConfig.platform_name == platform)
        )
        return result.scalar_one_or_none()

    async def process_incoming_message(self, source: str, payload: dict, client: Client = None, user_identifier: str = "default") -> str | None:
        # 1. Identify Client (if not provided)
        if not client:
             # Logic to find client if not already found (e.g. for generic webhooks)
             pass

        print(f"Processing message from {source} for client {client.name if client else 'Unknown'} user {user_identifier}: {payload}")

        # Extract message text (simplistic extraction, ideally standardized by caller)
        message_text = ""
        if source == "telegram":
            message_text = payload.get("message", {}).get("text", "")

        if not message_text:
            return None

        # 2. Forward to RAG
        rag_config = await self.get_integration_config(client.id, "rag")
        if rag_config:
            from app.services.rag import RAGService
            from app.models.sessions import ConversationSession

            # Lookup existing session using the (client_id, user_identifier)
            stmt = select(ConversationSession).where(
                ConversationSession.client_id == client.id,
                ConversationSession.platform == source,
                ConversationSession.user_identifier == user_identifier
            )
            result = await self.db.execute(stmt)
            session = result.scalar_one_or_none()

            # Use stored RAG session ID if we have one
            # If no session, default to None (starts new convo)
            rag_session_id = session.rag_session_id if session else None

            rag_service = RAGService()
            # Call RAG (MessagingService now knows rag_service.query returns a dict)
            rag_result = await rag_service.query(message_text, rag_session_id, rag_config.settings)

            answer = rag_result.get("answer", "")
            new_rag_session_id = rag_result.get("session_id")

            # Persist the new session_id if provided
            if new_rag_session_id:
                if session:
                    session.rag_session_id = new_rag_session_id
                else:
                    new_session = ConversationSession(
                        client_id=client.id,
                        platform=source,
                        user_identifier=user_identifier,
                        rag_session_id=new_rag_session_id
                    )
                    self.db.add(new_session)
                await self.db.commit()

            return answer

        # 3. Forward to Mattermost (Pending)

        return None
