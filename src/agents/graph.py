from langgraph.graph import StateGraph, END
from langgraph.types import interrupt
from src.agents.state import AgentState
from src.agents.research_agent import research_node
from src.agents.writing_agent import writing_node
from src.observability.logging_config import log_agent_activity
from src.services.event_service import publish_task_event


def human_approval_node(state: AgentState):
    task_id = state["task_id"]
    draft = state.get("draft")
    log_agent_activity(task_id, "HumanApprovalGate", "Pausing for human approval")

    # Record pause in state agent_logs before interrupt so checkpoint contains it
    logs = state.setdefault("agent_logs", [])
    logs.append({"agent": "HumanApprovalGate", "action": "awaiting_approval"})

    # Interrupt execution and wait for human decision
    approval_data = interrupt({"draft": draft, "prompt": state["prompt"]})

    # approval_data is injected on resume
    if isinstance(approval_data, dict):
        state["approval_granted"] = bool(approval_data.get("approved", False))
        state["human_feedback"] = approval_data.get("feedback", "")
    else:
        state["approval_granted"] = False

    decision = "approved" if state["approval_granted"] else "rejected"
    log_agent_activity(task_id, "HumanApprovalGate", f"Approval received: {decision}")
    state.setdefault("agent_logs", []).append({
        "agent": "HumanApprovalGate",
        "action": f"decision_{decision}",
    })
    return state


def finalization_node(state: AgentState):
    task_id = state["task_id"]
    log_agent_activity(task_id, "FinalizationAgent", "Finalizing result")
    final = state.get("draft", "")
    if state.get("human_feedback"):
        final = f"{final}\n\nFeedback: {state['human_feedback']}"
    state["final_result"] = final
    state.setdefault("agent_logs", []).append({
        "agent": "FinalizationAgent",
        "action": "completed",
    })
    try:
        publish_task_event(task_id, "COMPLETED")
    except Exception:
        pass
    return state


def build_graph(checkpointer=None):
    graph = StateGraph(AgentState)
    graph.add_node("research", research_node)
    graph.add_node("writing", writing_node)
    graph.add_node("approval", human_approval_node)
    graph.add_node("finalize", finalization_node)

    graph.set_entry_point("research")
    graph.add_edge("research", "writing")
    graph.add_edge("writing", "approval")
    graph.add_conditional_edges(
        "approval",
        lambda s: "finalize" if s.get("approval_granted") else END,
        {"finalize": "finalize", END: END}
    )
    graph.add_edge("finalize", END)
    return graph.compile(checkpointer=checkpointer)
