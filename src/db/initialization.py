from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy import text
from src.db.models import Base
from src.db.session import engine


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def ensure_tasks_table():
    # Idempotent check/create using SQL for required schema
    async with engine.begin() as conn:
        await conn.execute(text("""
            CREATE EXTENSION IF NOT EXISTS "pgcrypto";
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS tasks (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                prompt TEXT NOT NULL,
                status VARCHAR(50) NOT NULL,
                result TEXT NULL,
                agent_logs JSONB NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """))
