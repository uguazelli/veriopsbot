from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.core.config import settings
from app.core.database import engine, Base
from app.models import * # Import models to register them
import logging
from contextlib import asynccontextmanager
from app.services.scheduler import summary_scheduler
import asyncio

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Start scheduler
    task = asyncio.create_task(summary_scheduler())

    yield

    # Cancel scheduler on shutdown
    task.cancel()

from app.routers import auth, admin, integrations

app = FastAPI(title=settings.PROJECT_NAME, version=settings.VERSION, lifespan=lifespan)

# Mount static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(integrations.router, prefix=settings.API_V1_STR)

from fastapi import Request
from fastapi.responses import RedirectResponse

@app.get("/")
async def root(request: Request):
    token = request.cookies.get("access_token")
    if token:
        return RedirectResponse(url="/admin/clients")
    return RedirectResponse(url="/auth/login")

@app.get("/health")
async def health_check():
    return {"status": "ok"}
