import asyncio
import logging
import os
from urllib.parse import urlparse

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from tenacity import retry, stop_after_attempt, wait_fixed

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

max_tries = 60 * 5
wait_seconds = 1


def get_database_url() -> str:
    url = os.getenv("DATABASE_URL")
    if not url:
        return ""
    # Ensure using async driver for psycopg
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


async def ensure_database_exists() -> None:
    """Checks if the configured database exists and creates it if not."""
    target_url = get_database_url()
    if not target_url:
        logger.error("No DATABASE_URL configured.")
        return

    try:
        parsed = urlparse(target_url)
        db_name = parsed.path.lstrip("/")

        if not db_name:
            logger.warning("No database name found in DATABASE_URL. Skipping creation check.")
            return

        # Connect to 'postgres' db
        # We need to preserve the driver scheme (postgresql+psycopg://)
        postgres_url = target_url.replace(f"/{db_name}", "/postgres")

        logger.info(f"Checking database '{db_name}' existence...")

        engine = create_async_engine(postgres_url, isolation_level="AUTOCOMMIT")

        try:
            async with engine.connect() as conn:
                result = await conn.execute(
                    text("SELECT 1 FROM pg_database WHERE datname = :dbname"),
                    {"dbname": db_name}
                )
                exists = result.scalar() is not None

                if not exists:
                    logger.info(f"Database '{db_name}' does not exist. Creating...")
                    await conn.execute(text(f'CREATE DATABASE "{db_name}"'))
                    logger.info(f"Database '{db_name}' created successfully.")
                else:
                    logger.info(f"Database '{db_name}' already exists.")

        finally:
            await engine.dispose()

    except Exception as e:
        logger.error(f"Error checking/creating database: {e}")
        raise e


@retry(
    stop=stop_after_attempt(max_tries),
    wait=wait_fixed(wait_seconds),
)
async def init() -> None:
    try:
        await ensure_database_exists()

        url = get_database_url()
        logger.info(f"Attempting connection to DB...")
        engine = create_async_engine(url)
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("Database connection established.")
    except Exception as e:
        logger.error(f"Database unavailable: {e}")
        raise e


def main() -> None:
    logger.info("Initializing service")
    asyncio.run(init())
    logger.info("Service finished initializing")


if __name__ == "__main__":
    main()
