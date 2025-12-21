import httpx
import asyncio
from app.services import bot_service
from app import database
import os


TELEGRAM_API_BASE = "https://api.telegram.org/bot"

async def send_message(token: str, chat_id: str, text: str):
    url = f"{TELEGRAM_API_BASE}{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown" # Optional, but good for formmating
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, json=payload)
            response.raise_for_status()
        except Exception as e:
            print(f"❌ Telegram Send Failed: {e}")

async def sync_lead(*, instance: str, user_id: str, first_name: str, last_name: str, username: str):
    """
    Fire-and-forget sync to Veridata Integrator.
    """
    try:
        # New API Endpoint
        # instance is the 'token' alias in Telegram case
        url = f"http://veridata.sync:8001/api/v1/{instance}/lead"

        payload = {
            "firstName": first_name or "Unknown",
            "lastName": last_name or username or "TelegramUser",
            "status": "New",
            "source": "Call",
            "opportunityAmount": 0,
            "opportunityAmountCurrency": "USD",
            "emailAddress": "unknown@telegram.org",
            "phoneNumber": "00000000" # Logic needed if we want phone
        }

        async with httpx.AsyncClient() as client:
            print(f"🔄 Syncing lead for Telegram:{user_id} to Integrator...")
            # We set a short timeout because we don't want to hang background tasks too long
            resp = await client.post(url, json=payload, timeout=5.0)
            if resp.status_code >= 400:
                print(f"⚠️ Integrator Sync Failed: {resp.status_code} - {resp.text}")
            else:
                print(f"✅ Lead Synced: {resp.json()}")

    except Exception as e:
        print(f"❌ Lead Sync Error: {str(e)}")

async def process_webhook(token: str, payload: dict):

    """
    Process Telegram Webhook Update.
    The 'token' identifies the bot instance (and thus the tenant).
    """
    # 1. Extract Message Data
    # We only care about text messages for now
    message = payload.get("message")
    if not message:
        return {"status": "ignored", "reason": "no_message"}

    chat_id = str(message.get("chat", {}).get("id"))
    user_text = message.get("text")

    # Extract identity info for sync
    chat_info = message.get("chat", {})
    first_name = chat_info.get("first_name", "")
    last_name = chat_info.get("last_name", "")
    username = chat_info.get("username", "")

    if not chat_id or not user_text:
         return {"status": "ignored", "reason": "no_chat_id_or_text"}

    # Telegram doesn't usually send "from_me" via webhook updates unless we listen to 'channel_post' or 'edited_message'
    # For standard user interactions, it's always from the user.
    # Whatever, we can default from_me=False.
    # Note: If we want to support "Commanding the bot" via admin account on Telegram, we'd need to identify the admin ID.
    # For now, treat all inputs as user inputs.
    from_me = False

    # Sync Lead (async)
    asyncio.create_task(sync_lead(
        instance=token, # Token is the alias here
        user_id=chat_id,
        first_name=first_name,
        last_name=last_name,
        username=username
    ))

    # 2. Look up Platform Token (if Alias is used)
    platform_token = await database.get_platform_token(token)
    api_token = platform_token if platform_token else token

    # 3. Define Reply Callback
    async def reply_to_telegram(text: str):
        await send_message(api_token, chat_id, text)

    # 4. Delegate to Bot Service
    # Note: We use the 'token' (Alias) as the instance_id for lookup in the mappings table.
    return await bot_service.process_message(
        instance_id=token,
        user_id=chat_id,
        text=user_text,
        reply_callback=reply_to_telegram,
        from_me=from_me
    )


async def register_webhooks():
    try:
        mappings = await database.get_all_mappings()
        base_url = os.getenv("PUBLIC_URL") or os.getenv("VERIDATA_BOT_URL")

        if base_url:
            base_url = base_url.rstrip("/")
            print(f"🔄 Checking Telegram Webhooks for base URL: {base_url}")

            async with httpx.AsyncClient() as client:
                for mapping in mappings:
                    instance_name = mapping.get("instance_name")
                    # Check if it looks like a Token (123:ABC...)
                    if instance_name and ":" in instance_name and len(instance_name) > 20:
                        webhook_url = f"{base_url}/telegram/webhook/{instance_name}"
                        tg_url = f"https://api.telegram.org/bot{instance_name}/setWebhook"

                        try:
                            resp = await client.post(tg_url, json={"url": webhook_url})
                            if resp.status_code == 200:
                                print(f"✅ Webhook refreshed for {instance_name[:10]}... -> {webhook_url}")
                            else:
                                print(f"⚠️ Webhook refresh failed for {instance_name[:10]}...: {resp.text}")
                        except Exception as e:
                            print(f"❌ Webhook connection error for {instance_name}: {e}")
        else:
            print("ℹ️ PUBLIC_URL not set. Skipping auto-webhook registration on startup.")

    except Exception as e:
        print(f"❌ Startup webhook check failed: {e}")
