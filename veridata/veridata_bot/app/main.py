from fastapi import FastAPI, Depends, Request, BackgroundTasks
from app.core.db import engine, get_session, async_session_maker
from app.models import Client, Subscription, ServiceConfig, BotSession
from app.api.endpoints import router as api_router
from app.bot.engine import process_bot_event, process_integration_event
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.base import Base
from app.core.config import settings

import logging
import sys

from app.core.logging import setup_logging

from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

# Configure logging
setup_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="Veridata Bot")

# Fix for Mixed Content / HTTPS behind Proxy
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=["*"])

# Background Task Wrapper
async def run_bot_bg(client_slug: str, payload: dict):
    async with async_session_maker() as db:
        await process_bot_event(client_slug, payload, db)

async def run_integration_bg(client_slug: str, payload: dict):
    async with async_session_maker() as db:
        await process_integration_event(client_slug, payload, db)

# Admin UI removed (moved to veridata_worker)

# API
app.include_router(api_router, prefix="/api/v1")

# Webhooks
@app.post("/bot/chatwoot/{client_slug}")
async def chatwoot_bot_handler(
    client_slug: str,
    request: Request,
    background_tasks: BackgroundTasks
):
    payload = await request.json()
    background_tasks.add_task(run_bot_bg, client_slug, payload)
    return {"status": "processing_started"}

@app.post("/integrations/chatwoot/{client_slug}")
async def chatwoot_integration_handler(
    client_slug: str,
    request: Request,
    background_tasks: BackgroundTasks
):
    payload = await request.json()
    background_tasks.add_task(run_integration_bg, client_slug, payload)
    return {"status": "processing_started"}

@app.get("/health")
def health():
    return {"status": "ok"}
