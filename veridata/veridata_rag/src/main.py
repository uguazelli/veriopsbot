import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from src.controllers import web, api, ops
from src.config.logging import setup_logging
from src.storage.db import close_pool

setup_logging()
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    close_pool()

app = FastAPI(title="VeriRag Core", lifespan=lifespan)

app.include_router(web.router)
app.include_router(api.router, prefix="/api")
app.include_router(ops.router, prefix="/ops", tags=["ops"])
app.mount("/static", StaticFiles(directory="src/static"), name="static")
