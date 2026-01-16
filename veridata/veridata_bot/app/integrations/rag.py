import base64
import logging
import uuid

import httpx

logger = logging.getLogger(__name__)


class RagClient:
    """Client for communicating with the internal Veridata RAG Service.
    Handles Auth (Bearer/Basic) and JSON serialization.
    """

    def __init__(self, base_url: str, api_key: str, tenant_id: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.tenant_id = tenant_id

    async def create_session(self) -> str | None:
        """Explicitly create a new details session."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            url = f"{self.base_url}/api/session"
            headers = self._get_headers()
            payload = {"tenant_id": self.tenant_id}

            try:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                return str(data.get("session_id"))
            except Exception as e:
                logger.error(f"Failed to create RAG session: {e}")
                return None

    async def append_message(self, session_id: uuid.UUID, role: str, content: str):
        """Manually append a message to the RAG history."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            url = f"{self.base_url}/api/session/{session_id}/messages"
            headers = self._get_headers()
            payload = {"role": role, "content": content}

            try:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
            except Exception as e:
                logger.error(f"Failed to append message to RAG session {session_id}: {e}")

    def _get_headers(self):
        """Helper to construct Authorization headers."""
        headers = {}
        if self.api_key:
            if ":" in self.api_key and "Basic" not in self.api_key and "Bearer" not in self.api_key:
                encoded = base64.b64encode(self.api_key.encode()).decode()
                headers["Authorization"] = f"Basic {encoded}"
            elif "Basic" in self.api_key or "Bearer" in self.api_key:
                headers["Authorization"] = self.api_key
            else:
                headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    # ==================================================================================
    # METHOD: QUERY
    # Main entry point. Sends user text + context to RAG for an answer.
    # ==================================================================================
    async def query(
        self,
        message: str,
        session_id: uuid.UUID | None = None,
        complexity_score: int = 5,
        pricing_intent: bool = False,
        external_context: str | None = None,
        **kwargs,
    ) -> dict:
        async with httpx.AsyncClient(timeout=60.0) as client:
            url = f"{self.base_url}/api/query"

            payload = {
                "query": message,
                "tenant_id": self.tenant_id,
                "complexity_score": complexity_score,
                "pricing_intent": pricing_intent,
                "external_context": external_context,
                **kwargs,
            }

            logger.info(f"RAG Request to {url}. Payload: {payload}")

            if session_id:
                payload["session_id"] = str(session_id)

            headers = self._get_headers()

            resp = await client.post(url, json=payload, headers=headers)

            if resp.status_code != 200:
                logger.error(f"RAG Error {resp.status_code}: {resp.text}")

            resp.raise_for_status()
            return resp.json()

    # ==================================================================================
    # METHOD: SUMMARIZE
    # Asks RAG to summarize a session (unused? logic moved to Bot/Summarizer?)
    # ==================================================================================
    async def summarize(self, session_id: uuid.UUID, provider: str = "gemini") -> dict:
        async with httpx.AsyncClient(timeout=60.0) as client:
            url = f"{self.base_url}/api/summarize"

            payload = {"tenant_id": self.tenant_id, "session_id": str(session_id), "provider": provider}

            logger.info(f"Requesting summary for session {session_id}")
            headers = self._get_headers()

            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            return resp.json()

    # ==================================================================================
    # METHOD: DELETE SESSION
    # Cleans up memory references in RAG service.
    # ==================================================================================
    async def delete_session(self, session_id: uuid.UUID) -> dict:
        async with httpx.AsyncClient(timeout=10.0) as client:
            url = f"{self.base_url}/api/session/{session_id}"

            headers = self._get_headers()

            logger.info(f"Deleting RAG session {session_id}")
            resp = await client.delete(url, headers=headers)
            if resp.status_code == 404:
                return {"status": "already_deleted"}
            resp.raise_for_status()
            return resp.json()

    # ==================================================================================
    # METHOD: GET HISTORY
    # Retrieves chat transcript for LangGraph context or Summarization.
    # ==================================================================================
    async def get_history(self, session_id: uuid.UUID) -> list[dict]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            url = f"{self.base_url}/api/session/{session_id}/history"
            headers = self._get_headers()

            resp = await client.get(url, headers=headers)
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            return resp.json().get("messages", [])
