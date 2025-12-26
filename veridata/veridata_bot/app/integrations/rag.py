import httpx
import uuid
import logging

logger = logging.getLogger(__name__)

import base64

class RagClient:
    def __init__(self, base_url: str, api_key: str, tenant_id: str):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.tenant_id = tenant_id

    def _get_headers(self):
        headers = {}
        if self.api_key:
            # If the key contains a colon, assume it's username:password and use Basic Auth
            if ":" in self.api_key and "Basic" not in self.api_key and "Bearer" not in self.api_key:
                encoded = base64.b64encode(self.api_key.encode()).decode()
                headers["Authorization"] = f"Basic {encoded}"
            elif "Basic" in self.api_key or "Bearer" in self.api_key:
                 headers["Authorization"] = self.api_key
            else:
                 # Default to Bearer if single string
                 headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def query(self, message: str, session_id: uuid.UUID | None = None, **kwargs) -> dict:
        async with httpx.AsyncClient(timeout=60.0) as client:
            url = f"{self.base_url}/api/query"

            # Base payload
            payload = {
                "query": message,
                "tenant_id": self.tenant_id,
                **kwargs # provider, use_hyde, use_rerank etc.
            }

            logger.info(f"RAG Request to {url}. Payload keys: {list(payload.keys())}")

            if session_id:
                payload["session_id"] = str(session_id)

            headers = self._get_headers()

            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            return resp.json()
            # Expected response: {"answer": "...", "requires_human": true, "session_id": "..."}

    async def transcribe(self, file_bytes: bytes, filename: str, provider: str = "gemini") -> str:
        async with httpx.AsyncClient(timeout=60.0) as client:
            url = f"{self.base_url}/api/transcribe"

            headers = self._get_headers()

            files = {"file": (filename, file_bytes)}
            data = {"provider": provider}

            resp = await client.post(url, data=data, files=files, headers=headers)
            resp.raise_for_status()
            return resp.json().get("text", "")

    async def summarize(self, session_id: uuid.UUID, provider: str = "gemini") -> dict:
        async with httpx.AsyncClient(timeout=60.0) as client:
            url = f"{self.base_url}/api/summarize"

            payload = {
                "tenant_id": self.tenant_id,
                "session_id": str(session_id),
                "provider": provider
            }

            logger.info(f"Requesting summary for session {session_id}")
            headers = self._get_headers()

            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            return resp.json()

    async def delete_session(self, session_id: uuid.UUID) -> dict:
        async with httpx.AsyncClient(timeout=10.0) as client:
            url = f"{self.base_url}/api/session/{session_id}"

            headers = self._get_headers()

            logger.info(f"Deleting RAG session {session_id}")
            resp = await client.delete(url, headers=headers)
            # If 404, it's fine (already deleted)
            if resp.status_code == 404:
                return {"status": "already_deleted"}
            resp.raise_for_status()
            return resp.json()
