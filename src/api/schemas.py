from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import uuid


class TaskCreate(BaseModel):
    prompt: str


class TaskResponse(BaseModel):
    id: uuid.UUID
    prompt: str
    status: str
    result: Optional[str]
    agent_logs: Optional[list]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ApprovalRequest(BaseModel):
    approved: bool
    feedback: Optional[str] = ""


class TaskStatusResponse(BaseModel):
    task_id: uuid.UUID
    status: str
