from src.agents.tools import research_tool, TransientError
from src.services.workspace_service import save_workspace
from src.observability.logging_config import log_agent_activity
from src.services.event_service import publish_task_event
from src.config.settings import settings


def research_node(state):
    task_id = state["task_id"]
    prompt = state["prompt"]
    log_agent_activity(task_id, "ResearchAgent", "Starting research operation")
    try:
        findings = research_tool(prompt, task_id)
        save_workspace(task_id, findings, ttl=settings.workspace_ttl_seconds)
        log_agent_activity(task_id, "ResearchAgent", "Research completed and workspace persisted")
        publish_task_event(task_id, "RUNNING")
        state["research_findings"] = findings
        state.setdefault("agent_logs", []).append({"agent": "ResearchAgent", "action": "completed"})
        return state
    except TransientError as e:
        log_agent_activity(task_id, "ResearchAgent", f"Transient error: {e}")
        state["errors"] = str(e)
        raise
