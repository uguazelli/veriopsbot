import logging

import httpx

logger = logging.getLogger(__name__)


class ChatwootClient:
    """Client for Chatwoot API (v1).
    Used to send messages back to the user and manage conversation status.
    """

    def __init__(self, base_url: str, api_token: str, account_id: int = 1):
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token
        self.account_id = account_id
        self.headers = {"api_access_token": api_token}

    # ==================================================================================
    # METHOD: SEND MESSAGE
    # Appends a new message to the conversation.
    # message_type='outgoing' means the bot (agent) is speaking.
    # ==================================================================================
    async def send_message(self, conversation_id: str, message: str, message_type: str = "outgoing"):
        async with httpx.AsyncClient() as client:
            url = f"{self.base_url}/api/v1/accounts/{self.account_id}/conversations/{conversation_id}/messages"
            logger.info(f"Sending message to Chatwoot conversation {conversation_id} (Account {self.account_id})")
            payload = {"content": message, "message_type": message_type, "private": False}
            resp = await client.post(url, json=payload, headers=self.headers)
            resp.raise_for_status()
            return resp.json()

    # ==================================================================================
    # METHOD: TOGGLE STATUS
    # Changes conversation status:
    # 'open'    -> Visible to human agents (Handover)
    # 'pending' -> In progress (Bot active)
    # 'snoozed' -> Temporary hold
    # 'resolved'-> Done
    # ==================================================================================
    async def toggle_status(self, conversation_id: str, status: str):
        async with httpx.AsyncClient() as client:
            url = f"{self.base_url}/api/v1/accounts/{self.account_id}/conversations/{conversation_id}/toggle_status"
            payload = {"status": status}
            resp = await client.post(url, json=payload, headers=self.headers)
            resp.raise_for_status()
            return resp.json()
