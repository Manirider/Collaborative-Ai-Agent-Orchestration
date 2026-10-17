import uuid
import pytest
from unittest.mock import patch

from src.services.task_service import create_task, update_task_status


def test_create_task_endpoint(client):
    with patch("src.api.routes.execute_graph.delay") as mock_delay:
        response = client.post(
            "/api/v1/tasks",
            json={"prompt": "Benchmark distributed state stores"},
        )
        assert response.status_code == 202
        data = response.json()
        assert "task_id" in data
        assert data["status"] == "PENDING"
        mock_delay.assert_called_once()


def test_create_task_celery_failure(client):
    with patch("src.api.routes.execute_graph.delay", side_effect=RuntimeError("Broker unavailable")):
        response = client.post(
            "/api/v1/tasks",
            json={"prompt": "This should fail gracefully"},
        )
        assert response.status_code == 500
        assert "Failed to queue task" in response.json()["detail"]


@pytest.mark.asyncio
async def test_get_task_endpoint(client, db_session):
    task = await create_task(db_session, "Inspection prompt")
    tid = task.id
    await update_task_status(
        db_session,
        tid,
        "RUNNING",
        logs=[{"agent": "ResearchAgent", "action": "completed"}],
    )
    await db_session.commit()

    response = client.get(f"/api/v1/tasks/{tid}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(tid)
    assert data["prompt"] == "Inspection prompt"
    assert data["status"] == "RUNNING"
    assert len(data["agent_logs"]) == 1
    assert data["agent_logs"][0]["agent"] == "ResearchAgent"
    assert "created_at" in data
    assert "updated_at" in data


def test_get_task_not_found(client):
    fake_id = uuid.uuid4()
    response = client.get(f"/api/v1/tasks/{fake_id}")
    assert response.status_code == 404
    assert response.json()["detail"] == "Task not found"


def test_get_task_invalid_uuid(client):
    response = client.get("/api/v1/tasks/bad-uuid")
    assert response.status_code == 400
    assert "Invalid UUID" in response.json()["detail"]
