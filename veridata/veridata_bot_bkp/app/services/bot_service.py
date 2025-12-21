import os
from typing import Callable, Awaitable
from app import database
from app.services import rag_service

# Load Magic Words from env or use defaults
PAUSE_ENV = os.getenv("PAUSE_COMMANDS", "#stop,#human,#humano,#parar,#pause")
RESUME_ENV = os.getenv("RESUME_COMMANDS", "#bot,#start,#iniciar,#resume,#auto")

PAUSE_COMMANDS = [cmd.strip().lower() for cmd in PAUSE_ENV.split(",") if cmd.strip()]
RESUME_COMMANDS = [cmd.strip().lower() for cmd in RESUME_ENV.split(",") if cmd.strip()]

async def process_message(
    instance_id: str,
    user_id: str,
    text: str,
    reply_callback: Callable[[str], Awaitable[None]],
    mark_read_callback: Callable[[], Awaitable[None]] = None,
    from_me: bool = False
) -> dict:
    """
    Core bot logic processing:
    1. Handles administrative commands (Magic Words)
    2. Checks session status (Active/Paused)
    3. Resolves Tenant ID
    4. Queries RAG
    5. Updates Session
    6. Sends response via callback
    """

    # 1. Magic Words Logic (Status Toggling)
    text_lower = text.strip().lower()

    # If message is FROM AGENT/ADMIN (e.g. from WA Business App)
    if from_me:
        print(f"nb [BotService] 📤 Sent by Agent to {user_id}: {text}")
        if text_lower in PAUSE_COMMANDS:
            await database.set_session_active(instance_id, user_id, False)
            await reply_callback("⏸️ Bot paused. Human agent can now take over.")
            return {"status": "processed", "action": "paused_by_agent"}

        if text_lower in RESUME_COMMANDS:
            await database.set_session_active(instance_id, user_id, True)
            await reply_callback("🤖 Bot active. I am back!")
            return {"status": "processed", "action": "resumed_by_agent"}

        # Ignore other agent messages to prevent loops
        return {"status": "ignored", "reason": "from_me"}

    # If message is FROM Client (User)
    print(f"nb [BotService] 📩 Received from {user_id} on {instance_id}: {text}")

    # OPTIONAL: Explicitly ignore magic commands from client if they shouldn't control the bot
    if text_lower in PAUSE_COMMANDS or text_lower in RESUME_COMMANDS:
        print(f"⚠️ [BotService] Ignoring magic command from client: {text}")
        return {"status": "ignored", "reason": "client_command_ignored"}

    # 2. Check Status (Global & Session)
    # A. Global Instance Check
    is_globally_active = await database.get_instance_status(instance_id)
    if not is_globally_active:
        print(f"🛑 [BotService] Instance {instance_id} is globally PAUSED. Ignoring message.")
        return {"status": "ignored", "reason": "global_paused"}

    # B. Session Check
    is_active = await database.get_session_status(instance_id, user_id)
    if not is_active:
        print(f"💤 [BotService] Bot paused for {user_id}. Ignoring message.")
        # Do NOT mark as read here, so notification triggers on phone
        return {"status": "ignored", "reason": "paused"}

    # C. Rate Limit Check
    quota = await database.check_rate_limit(instance_id)
    if not quota["allowed"]:
        print(f"🛑 [BotService] Quota exceeded for {instance_id}. Limit: {quota['limit']}, Used: {quota['used']}")
        # Optional: Notify user once? Or just silence?
        # Better to notify so they know why it stopped working.
        renewal_str = str(quota['renewal']) if quota['renewal'] else "soon"
        await reply_callback(f"⚠️ Monthly Message Limit Reached.\n\nYour bot has used {quota['used']}/{quota['limit']} messages.\nResets on: {renewal_str}")
        return {"status": "ignored", "reason": "quota_exceeded"}

    # Bot is ACTIVE -> Mark message as read to silence notification
    if mark_read_callback:
        try:
            await mark_read_callback()
        except Exception as e:
            print(f"⚠️ [BotService] Failed to mark read: {e}")

    # 3. DB Lookup: Get Tenant ID
    tenant_id = await database.get_tenant_id(instance_id)
    if not tenant_id:
        print(f"⚠️ [BotService] No tenant configured for instance {instance_id}. Ignoring.")
        return {"status": "ignored", "reason": "unknown_instance"}

    # 4. DB Lookup: Get Session ID (if exists)
    session_id = await database.get_session_id(instance_id, user_id)

    # 5. Call RAG Service
    rag_response = await rag_service.query_rag(
        tenant_id=tenant_id,
        query=text,
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

        # 6. Save/Update Session
        new_session_id = rag_response.get("session_id")
        if new_session_id:
            await database.update_session_id(instance_id, user_id, new_session_id)

        # 7. Check for Human Handoff
        if rag_response.get("requires_human"):
            print(f"👤 [BotService] Human intervention requested for {user_id}")
            await database.set_session_active(instance_id, user_id, False)
            # Response text essentially says "Transferring..."
            # We send it, then the bot is paused for next messages.

    # 8. Send Response via Callback
    await reply_callback(str(response_text))

    # 9. Increment Usage
    await database.increment_usage(instance_id)

    return {"status": "processed"}
