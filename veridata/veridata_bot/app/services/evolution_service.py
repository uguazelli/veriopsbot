import httpx
import os
import base64
import asyncio
from app.services import rag_service, bot_service


EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY", "")
EVOLUTION_URL = os.getenv("EVOLUTION_URL", "https://dev-evolution.veridatapro.com")


async def mark_message_read(*, instance: str, message_id: str, phone: str):
    url = f"{EVOLUTION_URL}/chat/markMessageAsRead/{instance}"

    payload = {
        "readMessages": [
            {
                "remoteJid": phone,
                "fromMe": False,
                "id": message_id
            }
        ]
    }

    headers = {
        "apikey": EVOLUTION_API_KEY,
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient() as client:
        try:
            await client.post(url, json=payload, headers=headers)
        except Exception as e:
            print(f"❌ Failed to mark message as read: {str(e)}")

async def get_audio_bytes(*, instance: str, message_data: dict, phone: str):
    """
    Fetches the audio base64 from Evolution API and decodes it.
    """
    url = f"{EVOLUTION_URL}/chat/getBase64FromMediaMessage/{instance}"

    payload = {
        "message": message_data,
        "convertToMp4": False
    }

    headers = {
        "apikey": EVOLUTION_API_KEY,
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient() as client:
        try:
            print(f"🎧 Fetching audio for {phone}...")
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            result = response.json()
            b64_str = result.get("base64")
            if b64_str:
                return base64.b64decode(b64_str)
        except Exception as e:
            print(f"❌ Failed to fetch audio: {str(e)}")
    return None

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

async def sync_lead(*, instance: str, phone: str, push_name: str):
    """
    Fire-and-forget sync to Veridata Integrator.
    """
    try:
        # Simple name splitting logic
        parts = push_name.strip().split(" ", 1)
        first_name = parts[0] if parts else "Unknown"
        last_name = parts[1] if len(parts) > 1 else first_name

        # New API Endpoint
        url = f"http://veridata.sync:8001/api/v1/{instance}/lead"

        payload = {
            "firstName": first_name,
            "lastName": last_name,
            "status": "New",
            "source": "Call",
            "opportunityAmount": 0,
            "opportunityAmountCurrency": "USD",
            "emailAddress": "", # Not available in webhook usually, but required by API
            "phoneNumber": f"+{phone}" # Ensure E.164-ish format
        }

        async with httpx.AsyncClient() as client:
            print(f"🔄 Syncing lead for {phone} to Integrator...")
            resp = await client.post(url, json=payload)
            if resp.status_code >= 400:
                print(f"⚠️ Integrator Sync Failed: {resp.status_code} - {resp.text}")
            else:
                print(f"✅ Lead Synced: {resp.json()}")

    except Exception as e:
        print(f"❌ Lead Sync Error: {str(e)}")

async def process_webhook(payload: dict):

    # 1. Filter Event Type
    event_type = payload.get("event")
    if event_type != "messages.upsert":
        return {"status": "ignored", "reason": "not_upsert"}

    data = payload.get("data", {})
    key = data.get("key", {})

    remote_jid = key.get("remoteJid")
    if not remote_jid:
        return {"status": "error", "reason": "no_jid"}

    # Ignore Groups
    if remote_jid.endswith("@g.us"):
        return {"status": "ignored", "reason": "group_message"}

    # 2. Extract Data
    message_content = data.get("message", {})
    user_text = (
        message_content.get("conversation") or
        message_content.get("extendedTextMessage", {}).get("text")
    )

    phone_number = remote_jid.split("@")[0]
    instance = payload.get("instance")
    push_name = data.get("pushName") or "Unknown User"
    from_me = key.get("fromMe", False)


    # Handle Audio
    if not user_text and message_content.get("audioMessage"):
        print(f"🎤 [Evolution] Audio message received from {remote_jid}")
        audio_bytes = await get_audio_bytes(
            instance=instance,
            message_data=data, # Pass full data object (includes key)
            phone=phone_number
        )
        if audio_bytes:
            print(f"📝 Transcribing audio...")
            transcript = await rag_service.transcribe_audio(audio_bytes)
            if transcript:
                print(f"🗣️ Transcription: {transcript}")
                user_text = transcript
            else:
                user_text = "[Audio unintelligible]"
        else:
             print("❌ Could not retrieve audio bytes.")

    if not user_text:
        return {"status": "ignored", "reason": "no_text_found"}

    # 2.5 Fire Async Sync (Do not await)
    if not from_me:
        asyncio.create_task(sync_lead(instance=instance, phone=phone_number, push_name=push_name))



    # 3. Define Callback for Replying
    async def reply_to_whatsapp(text: str):
        await message_whatsapp(
            instance=instance,
            phone=phone_number,
            message=text
        )

    # 3b. Define Callback for Marking Read (Silence)
    message_id = key.get("id")
    async def mark_read_callback():
        if message_id:
            await mark_message_read(
                instance=instance,
                message_id=message_id,
                phone=remote_jid  # remoteJid includes @s.whatsapp.net
            )

    # 4. Delegate to Bot Service
    return await bot_service.process_message(
        instance_id=instance,
        user_id=phone_number,
        text=user_text,
        reply_callback=reply_to_whatsapp,
        mark_read_callback=mark_read_callback,
        from_me=from_me
    )
