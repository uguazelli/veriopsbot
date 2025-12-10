import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from src.db import init_db, close_pool
from src.controllers import web, api

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield
    close_pool()

app = FastAPI(title="VeriRag Core", lifespan=lifespan)

# Include Routers
# Web (HTML) Router - Mounts at root
app.include_router(web.router)

# API (JSON) Router - Mounts at /api
app.include_router(api.router, prefix="/api")

# Static files (if needed in future)
# app.mount("/static", StaticFiles(directory="static"), name="static")
