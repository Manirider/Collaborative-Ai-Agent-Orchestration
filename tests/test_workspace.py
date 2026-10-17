import uuid
from src.services.workspace_service import (
    save_workspace,
    load_workspace,
    workspace_key,
)


def test_workspace_save_and_load():
    task_id = str(uuid.uuid4())
    data = {
        "langgraph": {"features": ["checkpoints", "human-in-the-loop"]},
        "crewai": {"features": ["role-based agents"]},
    }

    save_workspace(task_id, data)
    loaded = load_workspace(task_id)

    assert loaded is not None
    assert loaded == data
    assert "langgraph" in loaded
    assert "crewai" in loaded


def test_workspace_load_nonexistent():
    task_id = str(uuid.uuid4())
    assert load_workspace(task_id) is None


def test_workspace_key_format():
    task_id = "test-uuid"
    assert workspace_key(task_id) == "task:test-uuid:workspace"
