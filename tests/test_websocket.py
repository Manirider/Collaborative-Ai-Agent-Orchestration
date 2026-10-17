import uuid
import pytest
from starlette.websockets import WebSocketDisconnect

from src.services.task_service import create_task, update_task_status


@pytest.mark.asyncio
async def test_websocket_initial_snapshot_pending(client, db_session):
    task = await create_task(db_session, "WS test prompt")
    await db_session.commit()

    with client.websocket_connect(f"/ws/tasks/{task.id}") as websocket:
        data = websocket.receive_json()
        assert data["task_id"] == str(task.id)
        assert data["status"] == "PENDING"
        assert data["result"] is None
        assert data["agent_logs"] == []
        assert "created_at" in data


@pytest.mark.asyncio
async def test_websocket_snapshot_awaiting_approval(client, db_session):
    task = await create_task(db_session, "WS approval prompt")
    tid = task.id
    logs = [
        {"agent": "ResearchAgent", "action": "completed"},
        {"agent": "WritingAgent", "action": "completed"},
        {"agent": "HumanApprovalGate", "action": "awaiting_approval"},
    ]
    await update_task_status(db_session, tid, "RUNNING")
    await update_task_status(db_session, tid, "AWAITING_APPROVAL", logs=logs)
    await db_session.commit()

    with client.websocket_connect(f"/ws/tasks/{tid}") as websocket:
        data = websocket.receive_json()
        assert data["task_id"] == str(tid)
        assert data["status"] == "AWAITING_APPROVAL"
        assert len(data["agent_logs"]) == 3
        agent_names = [l["agent"] for l in data["agent_logs"]]
        assert agent_names == ["ResearchAgent", "WritingAgent", "HumanApprovalGate"]


@pytest.mark.asyncio
async def test_websocket_snapshot_completed(client, db_session):
    task = await create_task(db_session, "WS completed prompt")
    tid = task.id
    await update_task_status(db_session, tid, "RUNNING")
    await update_task_status(
        db_session,
        tid,
        "COMPLETED",
        result_text="Final research report",
        logs=[{"agent": "FinalizationAgent", "action": "completed"}],
    )
    await db_session.commit()

    with client.websocket_connect(f"/ws/tasks/{tid}") as websocket:
        data = websocket.receive_json()
        assert data["task_id"] == str(tid)
        assert data["status"] == "COMPLETED"
        assert data["result"] == "Final research report"
        assert len(data["agent_logs"]) >= 1


def test_websocket_invalid_uuid(client):
    try:
        with client.websocket_connect("/ws/tasks/invalid-id") as websocket:
            websocket.receive_json()
    except WebSocketDisconnect as e:
        assert e.code == 4400


def test_websocket_nonexistent_task(client):
    fake_id = uuid.uuid4()
    with client.websocket_connect(f"/ws/tasks/{fake_id}") as websocket:
        data = websocket.receive_json()
        assert data["task_id"] == str(fake_id)
        assert data["status"] == "NOT_FOUND"
