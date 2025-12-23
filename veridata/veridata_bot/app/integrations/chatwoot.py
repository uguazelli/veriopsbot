import httpx

class ChatwootClient:
    def __init__(self, base_url: str, api_token: str):
        self.base_url = base_url.rstrip('/')
        self.api_token = api_token
        self.headers = {"api_access_token": api_token}

    async def send_message(self, conversation_id: str, message: str, message_type: str = "outgoing"):
        async with httpx.AsyncClient() as client:
            url = f"{self.base_url}/api/v1/accounts/1/conversations/{conversation_id}/messages"
            payload = {
                "content": message,
                "message_type": message_type,
                "private": False
            }
            # Note: Authentication might vary (header vs param). Assuming header based on standard practices
            # or it might be passed differently. Adjusting for standard Chatwoot API.
            # Usually: api_access_token in header or query.
            # Using header here.
            resp = await client.post(url, json=payload, headers=self.headers)
            resp.raise_for_status()
            return resp.json()
