import asyncio
import logging
from sqlalchemy.future import select
from app.core.database import SessionLocal
from app.models.integration import IntegrationConfig

logger = logging.getLogger(__name__)

async def summary_scheduler():
    logger.info("Starting summary scheduler")
    while True:
        try:
            async with SessionLocal() as db:
                # Get frequency from config, default to 60 minutes
                # using platform='scheduler' and client_id=None (global) or generic
                result = await db.execute(select(IntegrationConfig).where(IntegrationConfig.platform == "scheduler"))
                config = result.first() # Use first() as scalar_one_or_none might fail if duplicates

                minutes = 60
                if config:
                    # config is a Row, config[0] is the object
                    settings = config[0].settings
                    if settings:
                        minutes = int(settings.get("frequency_minutes", 60))

            logger.info(f"Scheduler sleeping for {minutes} minutes")
            await asyncio.sleep(minutes * 60)

            # Logic to find open conversations and summarize would go here.
            # logger.info("Running summarization task...")

        except Exception as e:
            logger.error(f"Error in scheduler: {e}")
            await asyncio.sleep(60) # Wait a bit before retrying
