"""Celery tasks for graph execution and resumption.

Key design decisions:
- Each task uses the *task_id* as the LangGraph thread_id for checkpoint
  continuity across execute → pause → resume.
- Logs and status are persisted to the database at every lifecycle transition:
  start, complete agent, retry attempt, pause for approval, resume after approval,
  complete successfully, or fail on retry exhaustion.
- A thread-pool bridge is used to safely execute async DB coroutines from
  either synchronous Celery workers or async test environments.
- Dynamic get_session() is used for all database sessions so test environments
  can swap the underlying engine cleanly.
- The checkpointer is obtained via the factory; in production this uses
  PostgreSQL, ensuring all workers share the same durable checkpoint store.
- Duplicate resume calls check task status and gracefully exit if already COMPLETED.
"""

import asyncio
import concurrent.futures
import logging
import uuid

from celery.exceptions import MaxRetriesExceededError
from langgraph.errors import GraphInterrupt
from langgraph.types import Command
from sqlalchemy import select

from src.agents.checkpointing import get_checkpointer
from src.agents.graph import build_graph
from src.config.settings import settings
from src.db.models import Task
from src.db.session import get_session
from src.observability.logging_config import log_agent_activity, setup_logging
from src.services.event_service import publish_task_event
from src.services.task_service import update_task_status, append_agent_logs, get_task
from src.worker.celery_app import celery_app

logger = logging.getLogger(__name__)
setup_logging(settings.log_file, settings.log_level)


def _run_async(coro):
    """Run an async coroutine from sync Celery worker or async test contexts."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(lambda: asyncio.run(coro)).result()
    else:
        return asyncio.run(coro)


async def _get_task_record(task_id: uuid.UUID) -> Task | None:
    async with get_session() as session:
        return await get_task(session, task_id)


async def _persist_status(task_uuid: uuid.UUID, status: str,
                          result_text: str | None = None,
                          logs: list | None = None):
    """Persist status + logs in a dedicated session with explicit commit."""
    async with get_session() as session:
        try:
            await update_task_status(
                session, task_uuid, status,
                result_text=result_text, logs=logs,
            )
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("Failed to persist status=%s for task=%s", status, task_uuid)
            raise


@celery_app.task(bind=True, name="tasks.execute_graph", max_retries=3)
def execute_graph(self, task_id: str):
    """Execute the LangGraph workflow for a new task.

    The graph will run research → writing → approval (interrupt) → finalize.
    On interrupt the task is set to AWAITING_APPROVAL and the Celery
    task returns cleanly; the graph will be resumed by resume_graph().
    """
    task_uuid = uuid.UUID(task_id)
    log_agent_activity(task_id, "Worker", "Starting graph execution")

    task = _run_async(_get_task_record(task_uuid))
    if not task:
        log_agent_activity(task_id, "Worker", "Task not found")
        return

    # Check for duplicate execution: if already past PENDING/RUNNING, do not re-run
    if task.status in ("AWAITING_APPROVAL", "RESUMED", "COMPLETED"):
        log_agent_activity(task_id, "Worker", f"Task already in status {task.status}, skipping execute")
        return

    prompt = task.prompt or ""

    # Transition to RUNNING
    try:
        start_logs = [{"agent": "Worker", "action": "execution_started"}]
        _run_async(_persist_status(task_uuid, "RUNNING", logs=start_logs))
        publish_task_event(task_id, "RUNNING")
    except Exception:
        logger.exception("Failed to set RUNNING for task=%s", task_id)
        raise

    try:
        checkpointer = get_checkpointer()
        graph = build_graph(checkpointer=checkpointer)
        initial_state = {
            "task_id": task_id,
            "prompt": prompt,
            "retry_count": getattr(self.request, "retries", 0),
            "agent_logs": [],
            "research_findings": None,
            "draft": None,
            "approval_granted": None,
            "human_feedback": None,
            "final_result": None,
            "errors": None,
        }
        # Use task_id as thread_id so resume picks up the same checkpoint
        config = {"configurable": {"thread_id": task_id}}
        result_state = graph.invoke(initial_state, config=config)

        # In LangGraph v1.2+, interrupt returns a state dict containing '__interrupt__'
        if isinstance(result_state, dict) and "__interrupt__" in result_state:
            log_agent_activity(task_id, "Worker", "Graph paused for human approval")
            try:
                checkpoint_state = graph.get_state(config)
                partial_logs = []
                if checkpoint_state and checkpoint_state.values:
                    partial_logs = list(checkpoint_state.values.get("agent_logs", []))
                if not any(entry.get("agent") == "HumanApprovalGate" for entry in partial_logs):
                    partial_logs.append({"agent": "HumanApprovalGate", "action": "awaiting_approval"})
                _run_async(_persist_status(
                    task_uuid, "AWAITING_APPROVAL",
                    logs=partial_logs,
                ))
            except Exception:
                logger.exception("Could not read checkpoint state for partial logs")
                _run_async(_persist_status(
                    task_uuid, "AWAITING_APPROVAL",
                    logs=[{"agent": "HumanApprovalGate", "action": "awaiting_approval"}],
                ))
            publish_task_event(task_id, "AWAITING_APPROVAL")
            return

        # Graph completed without interruption
        agent_logs = result_state.get("agent_logs", []) if isinstance(result_state, dict) else []
        final_result = result_state.get("final_result") if isinstance(result_state, dict) else None
        _run_async(_persist_status(
            task_uuid, "COMPLETED",
            result_text=final_result,
            logs=agent_logs,
        ))
        publish_task_event(task_id, "COMPLETED")
        log_agent_activity(task_id, "Worker", "Graph execution completed")

    except GraphInterrupt:
        log_agent_activity(task_id, "Worker", "Graph paused for human approval")
        try:
            checkpoint_state = graph.get_state(config)
            partial_logs = []
            if checkpoint_state and checkpoint_state.values:
                partial_logs = list(checkpoint_state.values.get("agent_logs", []))
            if not any(entry.get("agent") == "HumanApprovalGate" for entry in partial_logs):
                partial_logs.append({"agent": "HumanApprovalGate", "action": "awaiting_approval"})
            _run_async(_persist_status(
                task_uuid, "AWAITING_APPROVAL",
                logs=partial_logs,
            ))
        except Exception:
            logger.exception("Could not read checkpoint state for partial logs")
            _run_async(_persist_status(
                task_uuid, "AWAITING_APPROVAL",
                logs=[{"agent": "HumanApprovalGate", "action": "awaiting_approval"}],
            ))
        publish_task_event(task_id, "AWAITING_APPROVAL")

    except Exception as e:
        log_agent_activity(task_id, "Worker", f"Graph execution failed: {e}")
        retries = getattr(self.request, "retries", 0)
        max_retries = getattr(self, "max_retries", 3)
        if retries < max_retries:
            retry_log = [{"agent": "Worker", "action": f"retry_scheduled: attempt {retries + 1}/{max_retries} ({e})"}]
            try:
                _run_async(_persist_status(task_uuid, "RUNNING", logs=retry_log))
            except Exception:
                pass
            raise self.retry(exc=e, countdown=settings.task_retry_backoff_seconds)
        else:
            exhausted_log = [{"agent": "Worker", "action": f"retries_exhausted: {e}"}]
            try:
                _run_async(_persist_status(task_uuid, "FAILED", logs=exhausted_log))
                publish_task_event(task_id, "FAILED")
            except Exception:
                logger.exception("Failed to persist FAILED status for task=%s", task_id)
            raise


@celery_app.task(bind=True, name="tasks.resume_graph", max_retries=2)
def resume_graph(self, task_id: str, approved: bool, feedback: str):
    """Resume a graph that was paused at the human approval gate.

    Uses the same thread_id (task_id) to load the existing checkpoint,
    then injects the approval decision via Command(resume=...).
    """
    task_uuid = uuid.UUID(task_id)
    log_agent_activity(task_id, "Worker", f"Resuming graph (approved={approved})")

    # Guard against duplicate Celery job execution
    task = _run_async(_get_task_record(task_uuid))
    if not task:
        log_agent_activity(task_id, "Worker", "Task not found on resume")
        return
    if task.status == "COMPLETED":
        log_agent_activity(task_id, "Worker", "Task already COMPLETED; skipping duplicate resume")
        return

    # Persist resumption log
    try:
        resume_log = [{"agent": "Worker", "action": f"resumed (approved={approved})"}]
        _run_async(_persist_status(task_uuid, "RESUMED", logs=resume_log))
        publish_task_event(task_id, "RESUMED")
    except Exception:
        pass

    try:
        checkpointer = get_checkpointer()
        graph = build_graph(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": task_id}}

        # Resume with approval data injected into the interrupt
        command = Command(resume={"approved": approved, "feedback": feedback})
        result_state = graph.invoke(command, config=config)

        # Completed
        agent_logs = result_state.get("agent_logs", []) if isinstance(result_state, dict) else []
        final_result = result_state.get("final_result") if isinstance(result_state, dict) else None
        _run_async(_persist_status(
            task_uuid, "COMPLETED",
            result_text=final_result,
            logs=agent_logs,
        ))
        publish_task_event(task_id, "COMPLETED")
        log_agent_activity(task_id, "Worker", "Graph resumed and completed successfully")

    except Exception as e:
        log_agent_activity(task_id, "Worker", f"Resume failed: {e}")
        retries = getattr(self.request, "retries", 0)
        max_retries = getattr(self, "max_retries", 2)
        if retries < max_retries:
            retry_log = [{"agent": "Worker", "action": f"resume_retry_scheduled: attempt {retries + 1}/{max_retries} ({e})"}]
            try:
                _run_async(_persist_status(task_uuid, "RESUMED", logs=retry_log))
            except Exception:
                pass
            raise self.retry(exc=e, countdown=settings.task_retry_backoff_seconds)
        else:
            exhausted_log = [{"agent": "Worker", "action": f"resume_retries_exhausted: {e}"}]
            try:
                _run_async(_persist_status(task_uuid, "FAILED", logs=exhausted_log))
                publish_task_event(task_id, "FAILED")
            except Exception:
                logger.exception("Failed to persist FAILED status on resume for task=%s", task_id)
            raise
