import uuid
import pytest
from unittest.mock import patch

from src.db.models import Task
from src.services.task_service import (
    create_task,
    get_task,
    update_task_status,
    try_claim_for_approval,
    append_agent_logs,
)
from src.agents.checkpointing import (
    get_checkpointer,
    _is_postgres_mode,
    reset_pool,
)
from src.config.settings import settings
from langgraph.checkpoint.memory import MemorySaver


@pytest.mark.asyncio
async def test_task_creation_and_retrieval(db_session):
    task = await create_task(db_session, "Research quantum computing")
    assert task.id is not None
    assert task.status == "PENDING"
    assert task.prompt == "Research quantum computing"

    retrieved = await get_task(db_session, task.id)
    assert retrieved is not None
    assert retrieved.id == task.id
    assert retrieved.status == "PENDING"


@pytest.mark.asyncio
async def test_allowed_status_transitions(db_session):
    task = await create_task(db_session, "Lifecycle test")
    tid = task.id

    # PENDING -> RUNNING
    task = await update_task_status(db_session, tid, "RUNNING")
    assert task.status == "RUNNING"

    # RUNNING -> AWAITING_APPROVAL
    task = await update_task_status(db_session, tid, "AWAITING_APPROVAL")
    assert task.status == "AWAITING_APPROVAL"

    # AWAITING_APPROVAL -> RESUMED
    task = await update_task_status(db_session, tid, "RESUMED")
    assert task.status == "RESUMED"

    # RESUMED -> COMPLETED
    task = await update_task_status(
        db_session, tid, "COMPLETED", result_text="Final summary"
    )
    assert task.status == "COMPLETED"
    assert task.result == "Final summary"


@pytest.mark.asyncio
async def test_invalid_status_transitions(db_session):
    task = await create_task(db_session, "Invalid transition test")
    tid = task.id

    # PENDING -> COMPLETED is not allowed
    with pytest.raises(ValueError, match="Invalid status transition"):
        await update_task_status(db_session, tid, "COMPLETED")

    # Move to COMPLETED properly
    await update_task_status(db_session, tid, "RUNNING")
    await update_task_status(db_session, tid, "COMPLETED")

    # COMPLETED is terminal; cannot transition to RUNNING
    with pytest.raises(ValueError, match="terminal status"):
        await update_task_status(db_session, tid, "RUNNING")


@pytest.mark.asyncio
async def test_log_preservation_and_deduplication(db_session):
    task = await create_task(db_session, "Log test")
    tid = task.id

    # Append first log
    log1 = [{"agent": "ResearchAgent", "action": "completed"}]
    task = await update_task_status(db_session, tid, "RUNNING", logs=log1)
    assert len(task.agent_logs) == 1

    # Append second log, ensuring log1 is preserved
    log2 = [{"agent": "WritingAgent", "action": "completed"}]
    task = await update_task_status(db_session, tid, "AWAITING_APPROVAL", logs=log2)
    assert len(task.agent_logs) == 2
    assert task.agent_logs[0]["agent"] == "ResearchAgent"
    assert task.agent_logs[1]["agent"] == "WritingAgent"

    # Passing existing logs along with new logs does not duplicate
    task = await update_task_status(db_session, tid, "RESUMED")
    merged = log1 + log2 + [{"agent": "FinalizationAgent", "action": "completed"}]
    task = await update_task_status(db_session, tid, "COMPLETED", logs=merged)
    assert len(task.agent_logs) == 3


@pytest.mark.asyncio
async def test_atomic_claim_for_approval(db_session):
    task = await create_task(db_session, "Claim test")
    tid = task.id

    # Not yet awaiting approval
    claimed, status = await try_claim_for_approval(db_session, tid)
    assert not claimed
    assert status == "PENDING"

    # Transition to AWAITING_APPROVAL
    await update_task_status(db_session, tid, "RUNNING")
    await update_task_status(db_session, tid, "AWAITING_APPROVAL")

    # First claim succeeds
    claimed, status = await try_claim_for_approval(db_session, tid)
    assert claimed is True
    assert status == "RESUMED"

    # Duplicate claim fails immediately
    claimed, status = await try_claim_for_approval(db_session, tid)
    assert claimed is False
    assert status == "RESUMED"


def test_checkpoint_mode_selection():
    """Verify checkpointer selection logic under different configuration settings."""
    # Memory mode explicitly selected
    settings.checkpoint_mode = "memory"
    settings.app_env = "production"
    assert not _is_postgres_mode()
    saver = get_checkpointer()
    assert isinstance(saver, MemorySaver)

    # Postgres mode explicitly selected
    settings.checkpoint_mode = "postgres"
    assert _is_postgres_mode()

    # Auto mode in development -> memory
    settings.checkpoint_mode = "auto"
    settings.app_env = "development"
    assert not _is_postgres_mode()

    # Auto mode in production -> postgres
    settings.app_env = "production"
    assert _is_postgres_mode()


def test_missing_postgres_dependency_raises_error():
    """Missing PostgreSQL checkpointer dependency must fail loudly in production."""
    settings.checkpoint_mode = "postgres"
    reset_pool()

    with patch.dict("sys.modules", {"langgraph.checkpoint.postgres": None}):
        with pytest.raises(RuntimeError, match="langgraph-checkpoint-postgres is required"):
            get_checkpointer()
