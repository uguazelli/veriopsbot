import httpx
import os

EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY", "")
EVOLUTION_URL = os.getenv("EVOLUTION_URL", "https://dev-evolution.veridatapro.com")

async def message_whatsapp(*, instance: str, phone: str, message: str, delay: int = 5000):
    url = f"{EVOLUTION_URL}/message/sendText/{instance}"

    payload = {
        "number": phone,
        "text": message,
        "options": {
            "delay": delay,
            "presence": "composing" # Shows "typing..." status
        }
    }

    headers = {
        "apikey": EVOLUTION_API_KEY,
        "Content-Type": "application/json"
    }

    # USE ASYNC CLIENT
    async with httpx.AsyncClient() as client:
        try:
            print(f"🤖 Sending to {phone}...")
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            # print(response.json()) # Optional: Keep logs clean in prod
        except httpx.HTTPStatusError as e:
            print(f"❌ Error {e.response.status_code}: {e.response.text}")
        except Exception as e:
            print(f"❌ Request Failed: {str(e)}")

async def process_webhook(payload: dict):
    # 1. Filter Event Type
    event_type = payload.get("event")
    if event_type != "messages.upsert":
        return {"status": "ignored", "reason": "not_upsert"}

    data = payload.get("data", {})
    key = data.get("key", {})

    # 2. CRITICAL: Ignore own messages (Prevent Loop)
    if key.get("fromMe"):
        return {"status": "ignored", "reason": "from_me"}

    remote_jid = key.get("remoteJid")
    if not remote_jid:
        return {"status": "error", "reason": "no_jid"}

    # 3. Robust Text Extraction
    message_content = data.get("message", {})

    # Prioritize conversation (Android/Web), fallback to extended (iOS/Formatted)
    user_text = (
        message_content.get("conversation") or
        message_content.get("extendedTextMessage", {}).get("text")
    )

    if not user_text:
        return {"status": "ignored", "reason": "no_text_found"}

    # 4. Process Logic
    phone_number = remote_jid.split("@")[0]
    instance = payload.get("instance")

    print(f"📩 Received from {phone_number}: {user_text}")

    # HERE: Call your AI/RAG logic.
    # For now, we just echo back.
    response_text = f"Received: {user_text}"

    await message_whatsapp(instance=instance, phone=phone_number, message=response_text)

    return {"status": "processed"}