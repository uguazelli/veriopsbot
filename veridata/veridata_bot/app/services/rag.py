import httpx
import logging
import base64

logger = logging.getLogger(__name__)

class RAGService:
    def __init__(self):
        pass

    async def query(self, message: str, session_id: str, config: dict) -> dict:
        """
        Sends a query to the RAG service based on the provided configuration.
        """
        api_url = config.get("api_url")
        tenant_id = config.get("tenant_id")

        # Auth options
        auth_header = config.get("auth_header")
        username = config.get("username")
        password = config.get("password")

        provider = config.get("provider", "gemini")
        use_hyde = config.get("use_hyde", True)
        use_rerank = config.get("use_rerank", True)

        if not api_url or not tenant_id:
            logger.error("RAG Configuration missing api_url or tenant_id")
            return "Configuration error: Missing RAG parameters."

        headers = {
            "Content-Type": "application/json"
        }

        if auth_header:
            headers["Authorization"] = auth_header
        elif username and password:
            credentials = f"{username}:{password}"
            encoded_credentials = base64.b64encode(credentials.encode()).decode()
            headers["Authorization"] = f"Basic {encoded_credentials}"

        payload = {
            "tenant_id": tenant_id,
            "query": message,
            "provider": provider,
            "use_hyde": use_hyde,
            "use_rerank": use_rerank,
            "session_id": session_id
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.post(api_url, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()

                # Default return structure
                result = {
                    "answer": "",
                    "session_id": None
                }

                if isinstance(data, dict):
                     # Extract answer
                     result["answer"] = data.get("answer") or data.get("response") or data.get("text") or str(data)
                     # Extract session_id
                     result["session_id"] = data.get("session_id")
                else:
                    result["answer"] = str(data)

                return result

            except httpx.HTTPStatusError as e:
                logger.error(f"RAG Service Error: {e.response.text}")
                return {"answer": "I'm having trouble connecting to my brain right now.", "session_id": None}
            except Exception as e:
                logger.error(f"RAG Service Exception: {e}")
                return {"answer": "An unexpected error occurred.", "session_id": None}
