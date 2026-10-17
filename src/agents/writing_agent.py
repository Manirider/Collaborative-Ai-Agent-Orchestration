from src.services.workspace_service import load_workspace
from src.observability.logging_config import log_agent_activity


def writing_node(state):
    task_id = state["task_id"]
    log_agent_activity(task_id, "WritingAgent", "Reading workspace")
    workspace = load_workspace(task_id)
    if not workspace or "langgraph" not in workspace:
        raise ValueError("Research findings missing or malformed in workspace")
    prompt = state["prompt"]
    draft = (
        f"Comparison based on prompt: {prompt}\n\n"
        f"LangGraph features: {', '.join(workspace['langgraph']['features'])}\n"
        f"CrewAI features: {', '.join(workspace['crewai']['features'])}"
    )
    log_agent_activity(task_id, "WritingAgent", "Draft generated")
    state["draft"] = draft
    state.setdefault("agent_logs", []).append({"agent": "WritingAgent", "action": "completed"})
    return state
