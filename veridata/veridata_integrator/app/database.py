from sqlmodel import SQLModel, create_engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_async_engine(DATABASE_URL, echo=True, future=True)

async def init_db():
    async with engine.begin() as conn:
        # await conn.run_sync(SQLModel.metadata.drop_all)
        # Custom migration for dev: Add columns safely
        from sqlalchemy import text
        # We use IF NOT EXISTS to avoid transaction abortion if the column is already there.
        # Note: We need to execute these as separate statements or ensure syntax is valid.
        await conn.execute(text("ALTER TABLE client ADD COLUMN IF NOT EXISTS rag_tenant_id UUID"))
        await conn.execute(text("ALTER TABLE client ADD COLUMN IF NOT EXISTS bot_instance_alias VARCHAR"))

        await conn.run_sync(SQLModel.metadata.create_all)

async def get_session() -> AsyncSession:
    async_session = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session() as session:
        yield session
