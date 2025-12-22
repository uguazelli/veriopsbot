from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.core.config import get_settings
from typing import AsyncGenerator

settings = get_settings()

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,  # Set to True for debugging SQL queries
    future=True
)

AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
