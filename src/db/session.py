from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from src.config.settings import settings

engine = create_async_engine(settings.database_url, echo=False, future=True)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def reset_session_engine(url: str | None = None):
    """Reconfigure the global engine and session maker (used by tests)."""
    global engine, AsyncSessionLocal
    target_url = url or settings.database_url
    if "sqlite" in target_url:
        engine = create_async_engine(
            target_url,
            echo=False,
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    else:
        engine = create_async_engine(target_url, echo=False, future=True)
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, AsyncSessionLocal


def get_session() -> AsyncSession:
    """Return a fresh AsyncSession instance from the active sessionmaker."""
    return AsyncSessionLocal()


async def get_db():
    async with get_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
