import asyncio
import logging
from urllib.parse import urlparse

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from tenacity import retry, stop_after_attempt, wait_fixed
from app.database import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

max_tries = 60 * 5
wait_seconds = 1


async def ensure_database_exists() -> None:
    """Checks if the configured database exists and creates it if not."""
    target_url = settings.database_url_resolved
    if not target_url:
        logger.error("No DATABASE_URL configured.")
        return

    # Parse the target database name
    # Expected format: postgresql+asyncpg://user:pass@host:port/dbname
    try:
        # We need to parse a standard URL, so we might need to strip the driver text for parsing if standard urlparse fails,
        # but urlparse handles schemes effectively.
        parsed = urlparse(target_url)
        db_name = parsed.path.lstrip("/")

        if not db_name:
            logger.warning("No database name found in DATABASE_URL. Skipping creation check.")
            return

        # Create a URL for the default 'postgres' database to connect for administration
        postgres_url = target_url.replace(f"/{db_name}", "/postgres")

        logger.info(f"Checking database '{db_name}' existence using '{postgres_url}'...")

        # Connect to 'postgres' db with autocommit to allow CREATE DATABASE
        engine = create_async_engine(postgres_url, isolation_level="AUTOCOMMIT")

        try:
            async with engine.connect() as conn:
                # Check if database exists
                # Parameter binding is safer, though dealing with database identifiers often requires safe formatting or text()
                result = await conn.execute(
                    text("SELECT 1 FROM pg_database WHERE datname = :dbname"),
                    {"dbname": db_name}
                )
                exists = result.scalar() is not None

                if not exists:
                    logger.info(f"Database '{db_name}' does not exist. Creating...")
                    # CREATE DATABASE cannot run in a transaction block, which is why isolation_level="AUTOCOMMIT" is crucial
                    # We cannot bind the database name in CREATE DATABASE statement directly
                    await conn.execute(text(f'CREATE DATABASE "{db_name}"'))
                    logger.info(f"Database '{db_name}' created successfully.")
                else:
                    logger.info(f"Database '{db_name}' already exists.")

        finally:
            await engine.dispose()

    except Exception as e:
        logger.error(f"Error checking/creating database: {e}")
        # We generally don't check for failure here because the main init loop will retry connection
        # and if the DB doesn't exist, the content connection will fail appropriately.
        # But raising let's us retry this specific logic if needed.
        raise e


@retry(
    stop=stop_after_attempt(max_tries),
    wait=wait_fixed(wait_seconds),
)
async def init() -> None:
    try:
        await ensure_database_exists()

        logger.info(f"Attempting connection to: {settings.database_url_resolved}")
        engine = create_async_engine(settings.database_url_resolved)
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
