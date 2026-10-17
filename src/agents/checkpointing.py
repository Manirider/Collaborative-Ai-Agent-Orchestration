"""LangGraph checkpoint saver factory.

Production (APP_ENV != 'development' or CHECKPOINT_MODE == 'postgres'):
    Uses PostgresSaver backed by a psycopg connection pool.
    Fails loudly if the dependency or database is unreachable.

Development fallback (CHECKPOINT_MODE == 'memory'):
    Uses in-process MemorySaver singleton. Data is lost on restart.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator

from langgraph.checkpoint.memory import MemorySaver

from src.config.settings import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy singletons
# ---------------------------------------------------------------------------
_pool = None
_pool_creation_attempted = False
_tables_initialized = False
_memory_saver = None


def _postgres_conn_string() -> str:
    """Derive a *psycopg3* DSN from the SQLAlchemy-style DATABASE_URL."""
    url = settings.database_url
    for prefix in ("postgresql+asyncpg://", "postgresql+psycopg2://", "postgresql+psycopg://"):
        if url.startswith(prefix):
            return "postgresql://" + url[len(prefix):]
    return url


def _get_pool():
    """Return the global psycopg connection pool, creating it on first call."""
    global _pool, _pool_creation_attempted
    if _pool is not None:
        return _pool
    if _pool_creation_attempted:
        raise RuntimeError(
            "PostgreSQL checkpoint pool creation already failed in this process. "
            "Fix the database connection and restart."
        )
    _pool_creation_attempted = True
    try:
        from psycopg_pool import ConnectionPool
        from psycopg.rows import dict_row

        dsn = _postgres_conn_string()
        _pool = ConnectionPool(
            conninfo=dsn,
            min_size=1,
            max_size=10,
            timeout=5.0,
            kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row, "connect_timeout": 3},
            open=True,
        )
        logger.info("PostgreSQL checkpoint connection pool created")
        return _pool
    except Exception as exc:
        _pool = None
        raise RuntimeError(
            f"Failed to create PostgreSQL checkpoint pool: {exc}"
        ) from exc


def _is_postgres_mode() -> bool:
    mode = settings.checkpoint_mode.lower()
    if mode == "postgres":
        return True
    if mode == "memory":
        return False
    # "auto" – use postgres unless APP_ENV is development
    return settings.app_env.lower() != "development"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def init_checkpoint_tables():
    """Ensure PostgreSQL checkpoint tables are initialized.

    Called during application startup. In production mode, raises
    RuntimeError if database or required packages are unreachable.
    """
    global _tables_initialized
    if _is_postgres_mode():
        saver = get_checkpointer()
        try:
            saver.setup()
            _tables_initialized = True
            logger.info("PostgreSQL checkpoint tables initialized successfully.")
        except Exception as exc:
            raise RuntimeError(
                f"Failed to initialize PostgreSQL checkpoint tables: {exc}"
            ) from exc


def get_checkpointer():
    """Return a checkpointer instance according to active configuration.

    In production/postgres mode:
        Returns a PostgresSaver backed by the shared ConnectionPool.
        Ensures tables exist. Raises RuntimeError on any failure.

    In memory/development mode:
        Returns a process-shared MemorySaver singleton.
    """
    global _memory_saver, _tables_initialized
    if _is_postgres_mode():
        try:
            from langgraph.checkpoint.postgres import PostgresSaver
        except ImportError as exc:
            raise RuntimeError(
                "langgraph-checkpoint-postgres is required for PostgreSQL "
                "checkpointing but is not installed. Install it with: "
                "pip install 'langgraph-checkpoint-postgres>=2.0.0'"
            ) from exc

        pool = _get_pool()
        saver = PostgresSaver(pool)
        if not _tables_initialized:
            try:
                saver.setup()
                _tables_initialized = True
            except Exception as exc:
                raise RuntimeError(
                    f"Failed to setup PostgreSQL checkpoint tables: {exc}"
                ) from exc
        return saver
    else:
        if _memory_saver is None:
            logger.warning(
                "Using in-memory MemorySaver (checkpoint_mode=%s, app_env=%s). "
                "Checkpoints will NOT survive process restarts.",
                settings.checkpoint_mode,
                settings.app_env,
            )
            _memory_saver = MemorySaver()
        return _memory_saver


@contextmanager
def get_checkpointer_cm() -> Iterator:
    """Context manager yielding a checkpointer."""
    yield get_checkpointer()


def reset_pool():
    """Close the pool and reset state. Used in tests to reset module state."""
    global _pool, _pool_creation_attempted, _tables_initialized, _memory_saver
    if _pool is not None:
        try:
            _pool.close()
        except Exception:
            pass
    _pool = None
    _pool_creation_attempted = False
    _tables_initialized = False
    _memory_saver = None
