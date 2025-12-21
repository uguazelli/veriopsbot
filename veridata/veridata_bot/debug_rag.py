import httpx
import asyncio

async def test_rag():
    url = "http://localhost:8000/api/query" # RAG port usually 4017 locally or 8000 inside docker. User said 4017 in previous curl example but config has 8000.
    # Wait, user curl was http://localhost:4017/api/query.
    # But bot says http://veridata.rag:8000/api/query which is internal.

    # Let's try to verify what the RAG service expects.
    # The payload sent was:
    payload = {
        'query': 'hi',
        'session_id': 'cw_conv_1',
        'tenant_id': '3a0771e9-e3f9-48ed-813e-c388ecc9c2a1',
        'provider': 'gemini',
        'use_hyde': True,
        'use_rerank': True
    }

    print(f"Testing URL: {url}")
    print(f"Payload: {payload}")

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, headers={"Content-Type": "application/json"})
            print(f"Status: {resp.status_code}")
            print(f"Response: {resp.text}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_rag())
