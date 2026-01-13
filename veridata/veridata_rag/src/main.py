import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from src.controllers import web, api, ops
from src.storage.engine import dispose_engine
from src.config.config import load_config_from_db
from src.config.logging import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    await load_config_from_db()
    yield
    await dispose_engine()

app = FastAPI(title="VeriRag Core", lifespan=lifespan)

app.include_router(web.router)
app.include_router(api.router, prefix="/api")
app.include_router(ops.router, prefix="/ops", tags=["ops"])
app.mount("/static", StaticFiles(directory="src/static"), name="static")
