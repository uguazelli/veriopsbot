import logging
from typing import Any, Dict, List

import httpx

logger = logging.getLogger(__name__)


class ChatwootClient:
    def __init__(self, base_url: str, account_id: str, access_token: str):
        self.base_url = base_url.rstrip("/")
        self.account_id = account_id
        self.headers = {"api_access_token": access_token}

    async def get_conversations(self, status: str = "open") -> List[Dict[str, Any]]:
        """Fetch conversations by status.

        Args:
            status: 'open', 'resolved', 'pending', or 'all'
        """
        url = f"{self.base_url}/api/v1/accounts/{self.account_id}/conversations"
        params = {"status": status, "sort_by": "last_activity_at", "sort_order": "desc"}

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, headers=self.headers, params=params)
                resp.raise_for_status()
                data = resp.json()
                return data.get("data", {}).get("payload", [])
        except Exception as e:
            logger.error(f"Failed to fetch conversations from Chatwoot: {e}")
            return []

    async def toggle_status(self, conversation_id: int, status: str):
        """Update conversation status (e.g., to 'resolved').
        """
        url = f"{self.base_url}/api/v1/accounts/{self.account_id}/conversations/{conversation_id}/toggle_status"
        payload = {"status": status}

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, headers=self.headers, json=payload)
                resp.raise_for_status()
                logger.info(f"Successfully changed status of conversation {conversation_id} to {status}")
                return resp.json()
        except Exception as e:
            logger.error(f"Failed to toggle status for conversation {conversation_id}: {e}")
            raise e
