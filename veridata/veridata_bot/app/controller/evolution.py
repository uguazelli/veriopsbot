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

from app import database
from app.services import rag_service

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

    if not user_text:
        return {"status": "ignored", "reason": "no_text_found"}

    phone_number = remote_jid.split("@")[0]
    instance = payload.get("instance")
    from_me = key.get("fromMe", False)


    # Magic Words Logic (Status Toggling)
    text_lower = user_text.strip().lower()

    # Load from env or use defaults
    pause_env = os.getenv("PAUSE_COMMANDS", "#stop,#human,#humano,#parar,#pause")
    resume_env = os.getenv("RESUME_COMMANDS", "#bot,#start,#iniciar,#resume,#auto")

    PAUSE_COMMANDS = [cmd.strip().lower() for cmd in pause_env.split(",") if cmd.strip()]
    RESUME_COMMANDS = [cmd.strip().lower() for cmd in resume_env.split(",") if cmd.strip()]

    # If message is FROM ME (Agent/Admin)
    if from_me:
        print(f"📤 Sent by Agent to {phone_number}: {user_text}")
        if text_lower in PAUSE_COMMANDS:
            await database.set_session_active(instance, phone_number, False)
            await message_whatsapp(instance=instance, phone=phone_number, message="⏸️ Bot paused. Human agent can now take over.")
            return {"status": "processed", "action": "paused_by_agent"}

        if text_lower in RESUME_COMMANDS:
            await database.set_session_active(instance, phone_number, True)
            await message_whatsapp(instance=instance, phone=phone_number, message="🤖 Bot active. I am back!")
            return {"status": "processed", "action": "resumed_by_agent"}

        # Ignore other agent messages to prevent loops
        return {"status": "ignored", "reason": "from_me"}

    # If message is FROM Client (Not me)
    print(f"📩 Received from {phone_number} on {instance}: {user_text}")

    # OPTIONAL: Explicitly ignore magic commands from client if they shouldn't control the bot
    if text_lower in PAUSE_COMMANDS or text_lower in RESUME_COMMANDS:
        print(f"⚠️ Ignoring magic command from client: {user_text}")
        # Return processed but do nothing (or ignored)
        return {"status": "ignored", "reason": "client_command_ignored"}

    # 4. Check Status
    is_active = await database.get_session_status(instance, phone_number)
    if not is_active:
        print(f"💤 Bot paused for {phone_number}. Ignoring message.")
        return {"status": "ignored", "reason": "paused"}

    # 5. DB Lookup: Get Tenant ID
    tenant_id = await database.get_tenant_id(instance)
    if not tenant_id:
        print(f"⚠️ No tenant configured for instance {instance}. Ignoring.")
        return {"status": "ignored", "reason": "unknown_instance"}

    # 6. DB Lookup: Get Session ID (if exists)
    session_id = await database.get_session_id(instance, phone_number)

    # 7. Call RAG Service
    rag_response = await rag_service.query_rag(
        tenant_id=tenant_id,
        query=user_text,
        session_id=session_id
    )

    # Error handling for RAG
    if "error" in rag_response:
        response_text = "I'm having trouble connecting to my brain right now. Please try again later."
    else:
        # Extract answer from RAG response - adjusting based on expected format
        response_text = rag_response.get("text") or rag_response.get("answer") or rag_response.get("response")
        if not response_text:
             response_text = str(rag_response)

        # 8. Save/Update Session
        new_session_id = rag_response.get("session_id")
        if new_session_id:
            await database.update_session_id(instance, phone_number, new_session_id)

    # 9. Send Response
    await message_whatsapp(instance=instance, phone=phone_number, message=str(response_text))

    return {"status": "processed"}