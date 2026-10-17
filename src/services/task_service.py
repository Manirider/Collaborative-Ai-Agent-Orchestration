from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.db.models import Task
import uuid
from typing import Optional


ALLOWED_TRANSITIONS = {
    "PENDING": {"RUNNING"},
    "RUNNING": {"AWAITING_APPROVAL", "FAILED", "COMPLETED"},
    "AWAITING_APPROVAL": {"RESUMED", "FAILED"},
    "RESUMED": {"COMPLETED", "FAILED"},
}

TERMINAL_STATUSES = {"COMPLETED", "FAILED"}


async def create_task(session: AsyncSession, prompt: str) -> Task:
    task = Task(prompt=prompt, status="PENDING", agent_logs=[])
    session.add(task)
    await session.flush()
    return task


async def get_task(session: AsyncSession, task_id: uuid.UUID) -> Optional[Task]:
    result = await session.execute(select(Task).where(Task.id == task_id))
    return result.scalar_one_or_none()


async def update_task_status(
    session: AsyncSession,
    task_id: uuid.UUID,
    new_status: str,
    result_text: str | None = None,
    logs: list | None = None,
):
    """Update task status with transition validation.

    Appends new log entries rather than overwriting existing logs.
    """
    task = await get_task(session, task_id)
    if not task:
        return None
    current = task.status
    if current != new_status:
        if current in TERMINAL_STATUSES:
            raise ValueError(f"Task {task_id} is in terminal status {current}")
        allowed = ALLOWED_TRANSITIONS.get(current, set())
        if new_status not in allowed:
            raise ValueError(f"Invalid status transition from {current} to {new_status}")
    task.status = new_status
    if result_text is not None:
        task.result = result_text
    if logs is not None:
        existing = list(task.agent_logs or [])
        for entry in logs:
            if entry not in existing:
                existing.append(entry)
        task.agent_logs = existing
    await session.flush()
    return task


async def try_claim_for_approval(
    session: AsyncSession,
    task_id: uuid.UUID,
) -> tuple[bool, str]:
    """Atomically transition a task from AWAITING_APPROVAL to RESUMED.

    Uses row-level locking (with_for_update) on supported databases (PostgreSQL)
    to prevent concurrent approval race conditions.

    Returns:
        (success: bool, current_status: str)
    """
    stmt = select(Task).where(Task.id == task_id)
    if session.bind and session.bind.dialect.name != "sqlite":
        stmt = stmt.with_for_update()
    result = await session.execute(stmt)
    task = result.scalar_one_or_none()
    if task is None:
        return False, "NOT_FOUND"
    if task.status != "AWAITING_APPROVAL":
        return False, task.status
    task.status = "RESUMED"
    await session.flush()
    return True, "RESUMED"


async def append_agent_logs(session: AsyncSession, task_id: uuid.UUID, entry: dict):
    task = await get_task(session, task_id)
    if not task:
        return
    logs = list(task.agent_logs or [])
    logs.append(entry)
    task.agent_logs = logs
    await session.flush()
