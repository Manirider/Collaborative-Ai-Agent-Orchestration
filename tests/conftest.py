import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.testclient import TestClient

from src.main import app
from src.db.models import Base
from src.db.session import get_db, get_session, reset_session_engine
from src.agents.tools import reset_flaky_attempts
from src.services.workspace_service import reset_local_workspaces
from src.agents.checkpointing import reset_pool
from src.config.settings import settings

# Test in-memory database engine with SQLite
TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture(scope="function")
async def test_engine():
    # Configure global session maker to point to test SQLite database
    engine, _ = reset_session_engine(TEST_DB_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
    # Reset back to default URL
    reset_session_engine(settings.database_url)


@pytest_asyncio.fixture(scope="function")
async def db_session(test_engine):
    async with get_session() as session:
        yield session


@pytest_asyncio.fixture(scope="function")
async def client(test_engine):
    """FastAPI TestClient with overridden get_db dependency."""
    async def _override_get_db():
        async with get_session() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def clean_environment():
    """Reset shared in-memory state before and after each test."""
    reset_flaky_attempts()
    reset_local_workspaces()
    reset_pool()
    settings.checkpoint_mode = "memory"
    settings.app_env = "development"
    yield
    reset_flaky_attempts()
    reset_local_workspaces()
    reset_pool()
    settings.checkpoint_mode = "memory"
    settings.app_env = "development"
