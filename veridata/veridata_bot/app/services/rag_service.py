import os
import httpx
import base64

# Configuration
RAG_API_URL = os.getenv("RAG_API_URL", "http://localhost:4017/api/query")
# Default basic auth admin:admin -> YWRtaW46YWRtaW4=
RAG_API_AUTH = os.getenv("RAG_API_AUTH", "Basic YWRtaW46YWRtaW4=")

async def query_rag(tenant_id: str, query: str, session_id: str = None, provider: str = "gemini") -> dict:
    """
    Queries the RAG service.
    Returns the JSON response from the service.
    """
    headers = {
        'Content-Type': 'application/json',
        'Authorization': RAG_API_AUTH
    }

    payload = {
        "tenant_id": tenant_id,
        "query": query,
        "provider": provider,
        "use_hyde": True,
        "use_rerank": True
    }

    if session_id:
        payload["session_id"] = session_id

    async with httpx.AsyncClient() as client:
        try:
            print(f"🧠 Querying RAG for tenant {tenant_id}...")
            print(f"📦 RAG Payload: {payload}")
            response = await client.post(RAG_API_URL, json=payload, headers=headers, timeout=60.0) # Longer timeout for AI

            print(f"📥 RAG Response Status: {response.status_code}")
            try:
                print(f"📥 RAG Response Body: {response.json()}")
            except:
                print(f"📥 RAG Response Text: {response.text}")

            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            print(f"❌ RAG Error {e.response.status_code}: {e.response.text}")
            return {"error": f"RAG Error: {e.response.status_code}"}
        except Exception as e:
            print(f"❌ RAG Request Failed: {str(e)}")
            return {"error": "RAG Service Unavailable"}
