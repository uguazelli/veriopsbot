from fastapi import FastAPI, Request
from app.routers import admin, user_settings, telegram, evolution, chatwoot
from app.services import telegram_service
from app import database
from contextlib import asynccontextmanager
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
import os

@asynccontextmanager
async def lifespan(app: FastAPI):
    await database.init_db()

    # --- Auto-Register Telegram Webhooks on Startup ---
    await telegram_service.register_webhooks()
    # --------------------------------------------------

    yield
    await database.close_db()

app = FastAPI(lifespan=lifespan)
app.include_router(admin.router)
app.include_router(user_settings.router)
app.include_router(telegram.router)
app.include_router(evolution.router)
app.include_router(chatwoot.router)


static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")



@app.get("/")
async def root():
    return RedirectResponse(url="/login")
