from contextlib import asynccontextmanager
from fastapi import FastAPI
from sqladmin import Admin
from app.core.database import engine
from app.models.base import Base
from app.models.clients import Client, IntegrationConfig
from app.models.sessions import ConversationSession
from app.admin.views import ClientAdmin, IntegrationConfigAdmin
from app.core.config import get_settings

settings = get_settings()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Setup database (create tables if not exists for quick dev, though migrations are better)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    # Shutdown logic if needed

from app.routers import webhooks, api

app = FastAPI(title=settings.PROJECT_NAME, version=settings.VERSION, lifespan=lifespan)

app.include_router(webhooks.router)
app.include_router(api.router)

# Admin Interface
admin = Admin(app, engine)
admin.add_view(ClientAdmin)
admin.add_view(IntegrationConfigAdmin)

@app.get("/")
async def root():
    return {"message": "Veridata Bot is running"}
