from app.models.clients import Client, IntegrationConfig
from app.services.mattermost import MattermostService
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

            # --- Mirroring Logic ---
            # Check if this client has a mattermost integration for mirroring
            mm_config = await self.get_integration_config(client.id, "mattermost")
            if mm_config:
                mm_service = MattermostService()
                server_url = mm_config.settings.get("server_url")
                bot_token = mm_config.settings.get("bot_token")
                channel_id = mm_config.settings.get("channel_id")

                if server_url and bot_token and channel_id:
                    # 1. Mirror User Message (Standard Text with Override)
                    # We rely on username override for ID, plain text for look
                    await mm_service.send_message(
                        server_url,
                        bot_token,
                        channel_id,
                        text=message_text,
                        username=f"{client.name} - {user_identifier}"
                    )

                    # 2. Mirror Bot Response (As Attachment)
                    if answer:
                        bot_attachment = {
                            "color": "#00C853", # Greenish for success/response
                            "text": answer,
                            # Optional: "author_name" could be "Veridata Bot", or leave blank to use bot's name
                        }
                        await mm_service.send_message(
                            server_url,
                            bot_token,
                            channel_id,
                            text="", # Empty text, only attachment
                            attachments=[bot_attachment]
                        )
            # -----------------------

            return answer

        # 3. Forward to Mattermost (Pending)

        return None
