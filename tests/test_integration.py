import uuid
import pytest

from src.services.task_service import create_task, get_task
from src.worker.tasks import execute_graph, resume_graph
from src.db.session import get_session
from src.config.settings import settings


@pytest.mark.asyncio
async def test_end_to_end_worker_workflow(db_session):
    """Test full task lifecycle through Celery worker functions with in-memory checkpointer."""
    # Step 1: Create task
    task = await create_task(db_session, "Full lifecycle comparison: LangGraph vs CrewAI")
    tid_str = str(task.id)
    task_uuid = task.id
    await db_session.commit()

    # Step 2: Execute graph worker task (should run research, writing, then pause at approval)
    execute_graph(tid_str)

    # Step 3: Verify task state is paused and logs are persisted before approval is submitted
    async with get_session() as session:
        t = await get_task(session, task_uuid)
        assert t is not None
        assert t.status == "AWAITING_APPROVAL"
        logs = t.agent_logs or []
        agent_names = [entry["agent"] for entry in logs]
        assert "ResearchAgent" in agent_names
        assert "WritingAgent" in agent_names
        assert "HumanApprovalGate" in agent_names
        # Not yet finalized
        assert t.result is None

    # Step 4: Resume graph worker task with human approval
    resume_graph(tid_str, approved=True, feedback="Well formatted research")

    # Step 5: Verify task is COMPLETED with final result and final logs
    async with get_session() as session:
        t = await get_task(session, task_uuid)
        assert t is not None
        assert t.status == "COMPLETED"
        assert t.result is not None
        assert "LangGraph features:" in t.result
        assert "CrewAI features:" in t.result
        assert "Well formatted research" in t.result

        final_logs = t.agent_logs or []
        agent_names = [entry["agent"] for entry in final_logs]
        assert "FinalizationAgent" in agent_names

    # Step 6: Verify duplicate resume call is ignored without re-running or error
    resume_graph(tid_str, approved=True, feedback="Duplicate call")
    async with get_session() as session:
        t = await get_task(session, task_uuid)
        assert t.status == "COMPLETED"


@pytest.mark.integration
def test_postgres_saver_real_integration():
    """Integration test requiring a live PostgreSQL instance with CHECKPOINT_MODE=postgres."""
    from src.agents.checkpointing import get_checkpointer
    try:
        settings.checkpoint_mode = "postgres"
        saver = get_checkpointer()
        assert saver is not None
        saver.setup()
        saver.setup()
    except Exception as exc:
        pytest.skip(f"PostgreSQL integration unavailable in this environment: {exc}")
