from typing import Optional
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.orm import sessionmaker
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: Optional[str] = None
    ADMIN_USER: str = "admin"
    ADMIN_PASSWORD: str = "admin"

    # Optional components to build URL if DATABASE_URL is missing
    POSTGRES_USER: Optional[str] = None
    POSTGRES_PASSWORD: Optional[str] = None
    POSTGRES_HOST: Optional[str] = None
    POSTGRES_PORT: Optional[str] = None
    POSTGRES_DB: Optional[str] = None

    @property
    def database_url_resolved(self) -> str:
        if self.DATABASE_URL:
            return self.DATABASE_URL

        # Construct from components if available
        if all([self.POSTGRES_USER, self.POSTGRES_HOST, self.POSTGRES_DB]):
             return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT or 5432}/{self.POSTGRES_DB}"

        # Fallback/Error
        raise ValueError("DATABASE_URL or POSTGRES_* connection details required in environment.")

settings = Settings()

engine = create_async_engine(settings.database_url_resolved, echo=False, future=True)

async def get_session() -> AsyncSession:
    async_session = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session() as session:
        yield session
