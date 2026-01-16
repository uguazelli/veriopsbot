import asyncio
from typing import AsyncGenerator, Generator
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.db import get_session
from app.main import app as fastapi_app
import app.main  # Import for patching
import app.core.db # Import for patching

# Override host for local testing
settings.postgres_host = "127.0.0.1"
settings.rag_service_url = "http://127.0.0.1:8000"

# Hardcode URL to ensure no settings magic interference
test_db_url = "postgresql+asyncpg://veridata_user:veridata_pass@127.0.0.1:5432/veridata_bot"

test_engine = create_async_engine(test_db_url, echo=False, future=True)
TestingSessionLocal = async_sessionmaker(expire_on_commit=False, bind=test_engine)


@pytest_asyncio.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="function")
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with TestingSessionLocal() as session:
        yield session

@pytest.fixture(autouse=True)
def patch_db_maker(mocker):
    """
    Patch the async_session_maker used by background tasks (app.main.run_bot_bg)
    to use our test engine.
    """
    mocker.patch("app.main.async_session_maker", TestingSessionLocal)
    mocker.patch("app.core.db.async_session_maker", TestingSessionLocal)


@pytest_asyncio.fixture(scope="function")
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    # Override the dependency to use the test session
    async def override_get_session():
        yield db_session

    fastapi_app.dependency_overrides[get_session] = override_get_session

    async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as ac:
        yield ac

    fastapi_app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def mock_chatwoot_response(mocker):
    """
    Mock the handle_chatwoot_response function to prevent actual API calls
    and allow verification of what would have been sent.
    """
    mock = mocker.patch("app.bot.engine.handle_chatwoot_response", new_callable=AsyncMock)
    return mock

@pytest.fixture(autouse=True)
def mock_llm_router(mocker):
    """
    Mock the LLM used in the router node to avoid external API calls.
    Returns a JSON that forces 'rag' intent.
    """
    mock_llm_class = mocker.patch("app.agent.nodes.ChatGoogleGenerativeAI")
    mock_llm_instance = mock_llm_class.return_value

    # Mock ainvoke to return a valid JSON string for the router
    # Router expects: {"requires_rag": true, "requires_human": false, ...}
    mock_response = MagicMock()
    mock_response.content = '{"requires_rag": true, "requires_human": false, "complexity_score": 5, "pricing_intent": false, "reason": "Test"}'

    mock_llm_instance.ainvoke = AsyncMock(return_value=mock_response)
    return mock_llm_instance
