from typing import TypedDict, List, Optional


class AgentState(TypedDict):
    task_id: str
    prompt: str
    research_findings: Optional[dict]
    draft: Optional[str]
    approval_granted: Optional[bool]
    human_feedback: Optional[str]
    final_result: Optional[str]
    agent_logs: List[dict]
    errors: Optional[str]
    retry_count: int
