from fastapi import FastAPI, Depends, Request
from sqladmin import Admin, ModelView
from app.core.db import engine, get_session
from app.models import Client, Subscription, ServiceConfig, BotSession
from app.api.endpoints import router as api_router
from app.bot.engine import process_webhook
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.base import Base

app = FastAPI(title="Veridata Bot")

# Admin Views
class ClientAdmin(ModelView, model=Client):
    column_list = [Client.id, Client.name, Client.slug, Client.is_active]

class SubscriptionAdmin(ModelView, model=Subscription):
    column_list = [Subscription.id, Subscription.client_id, Subscription.usage_count, Subscription.quota_limit]

class ServiceConfigAdmin(ModelView, model=ServiceConfig):
    column_list = [ServiceConfig.id, ServiceConfig.client_id, ServiceConfig.platform]

class BotSessionAdmin(ModelView, model=BotSession):
    column_list = [BotSession.id, BotSession.client_id, BotSession.external_session_id]

# Startup - Create tables
@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

# Admin
admin = Admin(app, engine)
admin.add_view(ClientAdmin)
admin.add_view(SubscriptionAdmin)
admin.add_view(ServiceConfigAdmin)
admin.add_view(BotSessionAdmin)

# API
app.include_router(api_router, prefix="/api/v1")

# Webhooks
@app.post("/webhooks/chatwoot/{client_slug}")
async def chatwoot_webhook(
    client_slug: str,
    request: Request,
    db: AsyncSession = Depends(get_session)
):
    payload = await request.json()
    return await process_webhook(client_slug, payload, db)

@app.get("/health")
def health():
    return {"status": "ok"}
