import uuid
import pytest
from unittest.mock import patch

from src.services.task_service import create_task, update_task_status
from src.worker.tasks import resume_graph


@pytest.mark.asyncio
async def test_first_valid_approval(client, db_session):
    # Setup task in AWAITING_APPROVAL
    task = await create_task(db_session, "Approval test")
    tid = task.id
    await update_task_status(db_session, tid, "RUNNING")
    await update_task_status(db_session, tid, "AWAITING_APPROVAL")
    await db_session.commit()

    with patch("src.api.routes.resume_graph.delay") as mock_resume:
        response = client.post(
            f"/api/v1/tasks/{tid}/approve",
            json={"approved": True, "feedback": "Approved for release"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["task_id"] == str(tid)
        assert data["status"] == "RESUMED"

        mock_resume.assert_called_once_with(str(tid), True, "Approved for release")


@pytest.mark.asyncio
async def test_duplicate_approval_returns_409(client, db_session):
    task = await create_task(db_session, "Duplicate approval test")
    tid = task.id
    await update_task_status(db_session, tid, "RUNNING")
    await update_task_status(db_session, tid, "AWAITING_APPROVAL")
    await db_session.commit()

    with patch("src.api.routes.resume_graph.delay"):
        # First approval succeeds
        resp1 = client.post(f"/api/v1/tasks/{tid}/approve", json={"approved": True})
        assert resp1.status_code == 200

        # Duplicate approval request returns 409 Conflict
        resp2 = client.post(f"/api/v1/tasks/{tid}/approve", json={"approved": True})
        assert resp2.status_code == 409
        assert "already" in resp2.json()["detail"].lower()


@pytest.mark.asyncio
async def test_approval_for_nonexistent_task(client):
    fake_id = uuid.uuid4()
    response = client.post(
        f"/api/v1/tasks/{fake_id}/approve",
        json={"approved": True},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Task not found"


def test_approval_for_invalid_uuid(client):
    response = client.post(
        "/api/v1/tasks/not-a-valid-uuid/approve",
        json={"approved": True},
    )
    assert response.status_code == 400
    assert "Invalid UUID" in response.json()["detail"]


@pytest.mark.asyncio
async def test_approval_before_reaching_gate(client, db_session):
    # Task is still in PENDING status
    task = await create_task(db_session, "Early approval")
    await db_session.commit()

    response = client.post(
        f"/api/v1/tasks/{task.id}/approve",
        json={"approved": True},
    )
    assert response.status_code == 409
    assert "not awaiting approval" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_approval_after_completion(client, db_session):
    task = await create_task(db_session, "Completed task")
    tid = task.id
    await update_task_status(db_session, tid, "RUNNING")
    await update_task_status(db_session, tid, "COMPLETED", result_text="All done")
    await db_session.commit()

    response = client.post(
        f"/api/v1/tasks/{tid}/approve",
        json={"approved": True},
    )
    assert response.status_code == 409
    assert "terminal state" in response.json()["detail"].lower()
