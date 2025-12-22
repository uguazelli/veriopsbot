from app.services.messaging import MessagingService
from app.models.clients import Client

class TelegramService:
    def __init__(self, messaging_service: MessagingService):
        self.messaging_service = messaging_service

    async def process_update(self, token: str, update: dict):
        client = await self.messaging_service.get_client_by_telegram_token(token)
        if not client:
            print(f"Warning: Received update for unknown Telegram token: {token}")
            return

        # Determine message type (message, edited_message, etc.)
        message = update.get("message") or update.get("edited_message")
        if not message:
            print("Ignored non-message update")
            return

        chat_id = message.get("chat", {}).get("id")
        text = message.get("text", "")

        print(f"Telegram [{client.name}]: Message from {chat_id}: {text}")

        # Pass chat_id as user_identifier.
        # MessagingService handles session lookups and persistence.
        user_identifier = str(chat_id)

        # Delegate to the main messaging hub
        response_text = await self.messaging_service.process_incoming_message(
            source="telegram",
            payload=update,
            client=client,
            user_identifier=user_identifier
        )

        if response_text:
            await self.send_message(token, chat_id, response_text)

    async def send_message(self, token: str, chat_id: int, text: str):
        import httpx
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        async with httpx.AsyncClient() as client:
            try:
                await client.post(url, json={"chat_id": chat_id, "text": text})
            except Exception as e:
                print(f"Failed to send Telegram message: {e}")
