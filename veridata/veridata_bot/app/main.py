from fastapi import FastAPI, Depends, Request, BackgroundTasks
from fastapi.responses import RedirectResponse
from app.api.endpoints import router as api_router
from app.bot.engine import process_bot_event, process_integration_event
from app.core.db import async_session_maker
import logging
from app.core.logging import setup_logging
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
from app.ops import router as ops_router

# Configure logging
setup_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="Veridata Bot")

@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/ops/logs/view")

# Fix for Mixed Content / HTTPS behind Proxy
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=["*"])

# Background Task Wrapper
async def run_bot_bg(client_slug: str, payload: dict):
    async with async_session_maker() as db:
        await process_bot_event(client_slug, payload, db)

async def run_integration_bg(client_slug: str, payload: dict):
    async with async_session_maker() as db:
        await process_integration_event(client_slug, payload, db)


# API
app.include_router(api_router, prefix="/api/v1")
# from app.api.agent import router as agent_router
# app.include_router(agent_router, prefix="/api/v1/agent", tags=["Agent Shadow"])
app.include_router(ops_router, prefix="/ops", tags=["ops"])

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
