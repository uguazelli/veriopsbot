from fastapi import FastAPI, Depends, Request, BackgroundTasks
from sqladmin import Admin, ModelView
from app.core.db import engine, get_session, async_session_maker
from app.models import Client, Subscription, ServiceConfig, BotSession
from app.api.endpoints import router as api_router
from app.bot.engine import process_bot_event, process_integration_event
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.base import Base
from sqladmin.authentication import AuthenticationBackend
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

# Admin Views
class ClientAdmin(ModelView, model=Client):
    column_list = [Client.id, Client.name, Client.slug, Client.is_active]

class SubscriptionAdmin(ModelView, model=Subscription):
    column_list = [Subscription.id, Subscription.client_id, Subscription.usage_count, Subscription.quota_limit]

class ServiceConfigAdmin(ModelView, model=ServiceConfig):
    column_list = [ServiceConfig.id, ServiceConfig.client_id, ServiceConfig.platform]

class BotSessionAdmin(ModelView, model=BotSession):
    column_list = [BotSession.id, BotSession.client_id, BotSession.external_session_id]

class AdminAuth(AuthenticationBackend):
    async def login(self, request: Request) -> bool:
        form = await request.form()
        username = form.get("username")
        password = form.get("password")

        if username == settings.admin_user and password == settings.admin_password:
            request.session.update({"token": "admin_token"})
            return True
        return False

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        token = request.session.get("token")
        if not token:
            return False
        return True

authentication_backend = AdminAuth(secret_key=settings.postgres_password or "secret") # Using db password as secret for now, or could use itsdangerous

# Startup - Create tables
@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


# Admin
admin = Admin(app, engine, authentication_backend=authentication_backend)
admin.add_view(ClientAdmin)
admin.add_view(SubscriptionAdmin)
admin.add_view(ServiceConfigAdmin)
admin.add_view(BotSessionAdmin)

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
