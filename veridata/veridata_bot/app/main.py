from fastapi import FastAPI, Request
from app.controller import evolution, admin

from app import database
from contextlib import asynccontextmanager

import os
import httpx

@asynccontextmanager
async def lifespan(app: FastAPI):
    await database.init_db()

    # --- Auto-Register Telegram Webhooks on Startup ---
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
    # --------------------------------------------------

    yield
    await database.close_db()

app = FastAPI(lifespan=lifespan)
app.include_router(admin.router)
from app.routers import telegram
app.include_router(telegram.router)

@app.get("/")
async def root():
    return {"message": "VeriOps Bot is running"}

@app.post("/evolution/webhook")
async def evolution_webhook_post(request: Request):
    payload = await request.json()
    return await evolution.process_webhook(payload)

@app.get("/evolution/webhook")
async def evolution_webhook_get():
    return {"message": "The webhook is working"}
