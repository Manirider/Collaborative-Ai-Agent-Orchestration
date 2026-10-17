import uuid
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from langgraph.errors import GraphInterrupt
from src.agents.graph import build_graph


def test_graph_pauses_at_human_approval():
    """Graph must execute research and writing nodes then pause at approval interrupt."""
    checkpointer = MemorySaver()
    graph = build_graph(checkpointer=checkpointer)
    task_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": task_id}}

    initial_state = {
        "task_id": task_id,
        "prompt": "Compare LangGraph and CrewAI features",
        "retry_count": 0,
        "agent_logs": [],
        "research_findings": None,
        "draft": None,
        "approval_granted": None,
        "human_feedback": None,
        "final_result": None,
        "errors": None,
    }

    # Execute graph - should interrupt at human_approval_node
    res = None
    try:
        res = graph.invoke(initial_state, config=config)
    except GraphInterrupt:
        pass

    # Verify pause: in LangGraph v1.2+, interrupt returns a state dict with '__interrupt__'
    checkpoint_state = graph.get_state(config)
    assert (res and "__interrupt__" in res) or bool(checkpoint_state.next), "Graph did not interrupt for human approval"

    # Verify state saved at checkpoint
    assert checkpoint_state is not None
    assert checkpoint_state.values.get("draft") is not None
    assert "LangGraph features:" in checkpoint_state.values["draft"]
    assert "CrewAI features:" in checkpoint_state.values["draft"]

    # Check agent logs saved up to the interrupt
    logs = checkpoint_state.values.get("agent_logs", [])
    agent_names = [entry["agent"] for entry in logs]
    assert "ResearchAgent" in agent_names
    assert "WritingAgent" in agent_names
    assert "HumanApprovalGate" in agent_names


def test_graph_resumes_from_existing_checkpoint():
    """Graph must resume from its paused checkpoint without restarting research/writing."""
    checkpointer = MemorySaver()
    graph = build_graph(checkpointer=checkpointer)
    task_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": task_id}}

    initial_state = {
        "task_id": task_id,
        "prompt": "Explain stateful graph workflows",
        "retry_count": 0,
        "agent_logs": [],
        "research_findings": None,
        "draft": None,
        "approval_granted": None,
        "human_feedback": None,
        "final_result": None,
        "errors": None,
    }

    try:
        graph.invoke(initial_state, config=config)
    except GraphInterrupt:
        pass

    # Resume graph with approval
    resume_command = Command(resume={"approved": True, "feedback": "Looks great!"})
    result_state = graph.invoke(resume_command, config=config)

    assert result_state["approval_granted"] is True
    assert result_state["human_feedback"] == "Looks great!"
    assert result_state["final_result"] is not None
    assert "Looks great!" in result_state["final_result"]

    # Verify final logs
    agent_names = [entry["agent"] for entry in result_state["agent_logs"]]
    assert "FinalizationAgent" in agent_names


def test_graph_rejection_path():
    """When human rejects approval, graph terminates without calling finalization node."""
    checkpointer = MemorySaver()
    graph = build_graph(checkpointer=checkpointer)
    task_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": task_id}}

    initial_state = {
        "task_id": task_id,
        "prompt": "Evaluate agent architectures",
        "retry_count": 0,
        "agent_logs": [],
        "research_findings": None,
        "draft": None,
        "approval_granted": None,
        "human_feedback": None,
        "final_result": None,
        "errors": None,
    }

    try:
        graph.invoke(initial_state, config=config)
    except GraphInterrupt:
        pass

    # Reject
    resume_command = Command(resume={"approved": False, "feedback": "Needs rework"})
    result_state = graph.invoke(resume_command, config=config)

    assert result_state["approval_granted"] is False
    assert result_state.get("final_result") is None
    agent_names = [entry["agent"] for entry in result_state["agent_logs"]]
    assert "FinalizationAgent" not in agent_names


def test_thread_id_isolation():
    """Different tasks using different thread_ids must maintain isolated checkpoints."""
    checkpointer = MemorySaver()
    graph = build_graph(checkpointer=checkpointer)

    task_1 = str(uuid.uuid4())
    task_2 = str(uuid.uuid4())
    config_1 = {"configurable": {"thread_id": task_1}}
    config_2 = {"configurable": {"thread_id": task_2}}

    state_1 = {
        "task_id": task_1,
        "prompt": "Topic One",
        "retry_count": 0,
        "agent_logs": [],
        "research_findings": None,
        "draft": None,
        "approval_granted": None,
        "human_feedback": None,
        "final_result": None,
        "errors": None,
    }
    state_2 = {
        "task_id": task_2,
        "prompt": "Topic Two",
        "retry_count": 0,
        "agent_logs": [],
        "research_findings": None,
        "draft": None,
        "approval_granted": None,
        "human_feedback": None,
        "final_result": None,
        "errors": None,
    }

    try:
        graph.invoke(state_1, config=config_1)
    except GraphInterrupt:
        pass

    try:
        graph.invoke(state_2, config=config_2)
    except GraphInterrupt:
        pass

    chk_1 = graph.get_state(config_1)
    chk_2 = graph.get_state(config_2)

    assert chk_1.values["prompt"] == "Topic One"
    assert chk_2.values["prompt"] == "Topic Two"
    assert chk_1.values["task_id"] == task_1
    assert chk_2.values["task_id"] == task_2
