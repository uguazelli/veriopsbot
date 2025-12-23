import httpx
import uuid

class RagClient:
    def __init__(self, base_url: str, api_key: str, tenant_id: str):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.tenant_id = tenant_id

    async def query(self, message: str, session_id: uuid.UUID | None = None, **kwargs) -> dict:
        async with httpx.AsyncClient() as client:
            url = f"{self.base_url}/api/query"

            # Base payload
            payload = {
                "query": message,
                "tenant_id": self.tenant_id,
                **kwargs # provider, use_hyde, use_rerank etc.
            }

            if session_id:
                payload["session_id"] = str(session_id)

            headers = {}
            if self.api_key:
                # Determine if Basic or Bearer based on content or config?
                # For now assuming user provides the full token value or we prepend Bearer.
                # Given the curl example used Basic, the user might provide the base64 string or "Basic ..."
                # Let's assume the user config 'api_key' holds the value for the Authorization header
                # OR we treat it as Bearer if it looks like a key.
                # Actually, simplest is to just send it.
                # If the key is 'YWRtaW46YWRtaW4=' (admin:admin in base64), we might need to prepend Basic.
                if "Basic" in self.api_key or "Bearer" in self.api_key:
                     headers["Authorization"] = self.api_key
                else:
                     headers["Authorization"] = f"Bearer {self.api_key}"

            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            return resp.json()
            # Expected response: {"answer": "...", "requires_human": true, "session_id": "..."}
