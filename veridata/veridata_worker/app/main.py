import asyncio
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqladmin import Admin
from sqlalchemy import select
from app.database import engine, get_session
from app.admin import authentication_backend, ClientAdmin, SyncConfigAdmin, ServiceConfigAdmin, SubscriptionAdmin, BotSessionAdmin
from app.models import SyncConfig, Client
import logging
from app.core.logging import setup_logging, log_job, log_error

# Configure logging
setup_logging(log_filename="veridata_worker.log")
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

                    log_job(logger, f"Checking job for [{client_name}] on [{config.platform}]")

                    # Smart Scheduler Logic
                    should_run = False
                    now = datetime.now(timezone.utc).replace(tzinfo=None) # Ensure naive/aware consistency based on DB config
                    # OR just standard datetime.now() if using naive. SQLModel usually uses naive by default for SQLite/PG unless configured.
                    # Safety: Use naive UTC for simplicity if DB is naive
                    now = datetime.utcnow()

                    if not config.last_run_at:
                        should_run = True
                        log_job(logger, f"Job [{config.id}] never ran. Triggering NOW.")
                    else:
                        delta = now - config.last_run_at
                        if delta.total_seconds() / 60 >= config.frequency_minutes:
                            should_run = True
                            log_job(logger, f"Job [{config.id}] due (Last run: {config.last_run_at}, Delta: {delta}). Triggering NOW.")
                        else:
                            log_job(logger, f"Job [{config.id}] SKIP. (Last run: {config.last_run_at}, Freq: {config.frequency_minutes}m, Wait: {config.frequency_minutes - (delta.total_seconds()/60):.1f}m)")

                    if should_run:
                        if config.platform == "chatwoot" or config.platform == "chatwoot-auto-resolve":
                            await run_auto_resolve_job(session, config)
                        else:
                            log_job(logger, f"Simulating generic sync for [{client_name}] (Frequency: {config.frequency_minutes}m)")

                        # Update last_run_at
                        config.last_run_at = now
                        session.add(config)
                        await session.commit()

        except Exception as e:
            log_error(logger, f"Worker loop error: {e}")

        # Determine sleep interval (simplification: fixed sleep for simulation)
        # Real world would calculate next run time based on frequency.
        await asyncio.sleep(60) # Check every minute

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables
    async with engine.begin() as conn:
        from app.models import SQLModel
        await conn.run_sync(SQLModel.metadata.create_all)

        # MIGRATION: Ensure last_run_at exists (create_all doesn't alter existing tables)
        from sqlalchemy import text
        try:
            await conn.execute(text("ALTER TABLE sync_configs ADD COLUMN IF NOT EXISTS last_run_at TIMESTAMP WITHOUT TIME ZONE"))
            await conn.execute(text("ALTER TABLE sync_configs ADD COLUMN IF NOT EXISTS inactivity_threshold_minutes INTEGER"))
        except Exception as e:
            logger.warning(f"Migration check failed (safe to ignore if column exists): {e}")

    # Startup
    admin = Admin(
        app,
        engine,
        authentication_backend=authentication_backend,
        title="Veri Data",
        logo_url="/static/logo.png"
    )
    admin.add_view(ClientAdmin)
    admin.add_view(SyncConfigAdmin)
    admin.add_view(ServiceConfigAdmin)
    admin.add_view(SubscriptionAdmin)
    admin.add_view(BotSessionAdmin)

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
app.mount("/static", StaticFiles(directory="app/static"), name="static")

@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "veridata-worker"}
