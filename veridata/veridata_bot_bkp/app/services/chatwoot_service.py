import httpx
import os
from app import database
from app.services import bot_service
import asyncio


# Default Chatwoot URL if not provided elsewhere.
CHATWOOT_BASE_URL = os.getenv("CHATWOOT_URL", "https://dev-chat.veridatapro.com")

async def send_message(account_id: str, conversation_id: str, text: str, api_token: str):
    """
    Sends a message back to Chatwoot conversation.
    """
    # Endpoint: /api/v1/accounts/{account_id}/conversations/{conversation_id}/messages
    url = f"{CHATWOOT_BASE_URL}/api/v1/accounts/{account_id}/conversations/{conversation_id}/messages"

    payload = {
        "content": text,
        "message_type": "outgoing",
        "private": False
    }

    headers = {
        "api_access_token": api_token, # Bot Access Token
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
        except Exception as e:
            print(f"❌ Chatwoot Send Failed (Acc: {account_id}, Conv: {conversation_id}): {e}")

async def sync_lead(*, instance: str, user_id: str, name: str, email: str, phone: str):
    """
    Fire-and-forget sync to Veridata Integrator.
    """
    try:
        # Chatwoot usually gives a full name
        parts = name.strip().split(" ", 1)
        first_name = parts[0] if parts else "Unknown"
        last_name = parts[1] if len(parts) > 1 else first_name

        # New API Endpoint
        url = f"http://veridata.sync:8001/api/v1/{instance}/lead"

        payload = {
            "firstName": first_name,
            "lastName": last_name,
            "status": "New",
            "source": "Call",
            "emailAddress": email or "", # API expects string
            "phoneNumber": phone or "",
            "opportunityAmount": 0,
            "opportunityAmountCurrency": "USD"
        }

        async with httpx.AsyncClient() as client:
            print(f"🔄 Syncing lead for Chatwoot:{user_id} to Integrator...")
            resp = await client.post(url, json=payload, timeout=5.0)
            if resp.status_code >= 400:
                print(f"⚠️ Integrator Sync Failed: {resp.status_code} - {resp.text}")
            else:
                print(f"✅ Lead Synced: {resp.json()}")

    except Exception as e:
        print(f"❌ Lead Sync Error: {str(e)}")

    except Exception as e:
        print(f"❌ Lead Sync Error: {str(e)}")

async def process_webhook(payload: dict):

    """
    Process Chatwoot Webhook Event.
    """
    event_type = payload.get("event")

    # We only care about new messages created by 'users' (incoming)
    if event_type != "message_created":
        return {"status": "ignored", "reason": "not_message_created"}

    message_type = payload.get("message_type") # incoming, outgoing, template
    if message_type != "incoming":
        return {"status": "ignored", "reason": "not_incoming_message"}

    # Extract Data
    account_info = payload.get("account", {})
    conversation_info = payload.get("conversation", {})
    message_content = payload.get("content")
    sender_info = payload.get("sender", {})

    account_id = str(account_info.get("id"))
    conversation_id = str(conversation_info.get("id"))

    # Identifier for the Session:
    # Use conversation_id as the 'user_id' equivalent.
    # Why? specific chat session context is tied to conversation in Chatwoot.
    chat_session_id = conversation_id

    # The 'Instance Name' in our DB needs to match something we can derive.
    # We can use "chatwoot_{account_id}" or just the account_id string if unique enough.
    # Let's use "chatwoot_{account_id}" to avoid collision with evolution instance names.
    instance_name = f"chatwoot_{account_id}"

    user_text = message_content

    if not user_text or not conversation_id or not account_id:
        return {"status": "ignored", "reason": "missing_data"}

    # Sync Lead (async)
    # Extract extra sender info
    sender_name = sender_info.get("name", "Unknown")
    sender_email = sender_info.get("email")
    sender_phone = sender_info.get("phone_number")

    asyncio.create_task(sync_lead(
        instance=instance_name,
        user_id=sender_info.get("id", "unknown"),
        name=sender_name,
        email=sender_email,
        phone=sender_phone
    ))

    # 1. Get Token for replying
    # We expect the admin to have saved the Chatwoot Bot Access Token in the mappings table
    # under this instance_name ("chatwoot_{account_id}").
    platform_token = await database.get_platform_token(instance_name)

    if not platform_token:
        print(f"⚠️ No platform_token found for {instance_name}. Cannot reply to Chatwoot.")
        # We can still process (maybe for RAG testing) but can't reply.
        # Let's return, as it's pointless.
        return {"status": "error", "reason": "no_token_configured"}

    # 2. Define Reply Callback
    async def reply_to_chatwoot(text: str):
        await send_message(account_id, conversation_id, text, platform_token)

    # 3. Delegate to Bot Service
    # Note: `from_me` is handled by the `message_type != incoming` check above.
    return await bot_service.process_message(
        instance_id=instance_name,
        user_id=chat_session_id,
        text=user_text,
        reply_callback=reply_to_chatwoot,
        from_me=False
    )
