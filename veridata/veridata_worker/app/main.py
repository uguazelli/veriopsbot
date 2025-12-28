import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from sqladmin import Admin
from sqlalchemy import select
from app.database import engine, get_session
from app.admin import authentication_backend, ClientAdmin, SyncConfigAdmin
from app.models import SyncConfig, Client
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from app.jobs.auto_resolve import run_auto_resolve_job

async def sync_worker_loop():
    """Background loop to check for active sync configs and simulate work."""
    while True:
        try:
            async for session in get_session():
                query = select(SyncConfig).where(SyncConfig.is_active == True)
                result = await session.execute(query)
                configs = result.scalars().all()

                for config in configs:
                    # Fetch client name for logging
                    client = await session.get(Client, config.client_id)
                    client_name = client.name if client else f"ID {config.client_id}"

                    logger.info(f"Checking job for [{client_name}] on [{config.platform}]")

                    if config.platform == "chatwoot-auto-resolve":
                        await run_auto_resolve_job(config)
                    else:
                        logger.info(f"Simulating generic sync for [{client_name}] (Frequency: {config.frequency_minutes}m)")

        except Exception as e:
            logger.error(f"Worker loop error: {e}")

        # Determine sleep interval (simplification: fixed sleep for simulation)
        # Real world would calculate next run time based on frequency.
        await asyncio.sleep(60) # Check every minute

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables
    async with engine.begin() as conn:
        from app.models import SQLModel
        await conn.run_sync(SQLModel.metadata.create_all)

    # Startup
    admin = Admin(app, engine, authentication_backend=authentication_backend)
    admin.add_view(ClientAdmin)
    admin.add_view(SyncConfigAdmin)

    # Start worker
    task = asyncio.create_task(sync_worker_loop())

    yield

    # Shutdown
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

app = FastAPI(title="Veridata Worker", lifespan=lifespan)

@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "veridata-worker"}
