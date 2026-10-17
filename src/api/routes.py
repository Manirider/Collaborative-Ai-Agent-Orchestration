from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.session import get_db
from src.services.task_service import (
    create_task,
    get_task,
    try_claim_for_approval,
    TERMINAL_STATUSES,
)
from src.api.schemas import TaskCreate, TaskResponse, ApprovalRequest, TaskStatusResponse
from src.worker.tasks import execute_graph, resume_graph
import uuid

router = APIRouter(prefix="/api/v1")


@router.post("/tasks", status_code=status.HTTP_202_ACCEPTED)
async def create_task_endpoint(payload: TaskCreate, session: AsyncSession = Depends(get_db)):
    task = await create_task(session, payload.prompt)
    # Dispatch celery job
    try:
        execute_graph.delay(str(task.id))
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to queue task")
    return {"task_id": str(task.id), "status": "PENDING"}


@router.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task_endpoint(task_id: str, session: AsyncSession = Depends(get_db)):
    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID")
    task = await get_task(session, tid)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.post("/tasks/{task_id}/approve", response_model=TaskStatusResponse)
async def approve_task(task_id: str, payload: ApprovalRequest, session: AsyncSession = Depends(get_db)):
    """Submit an approval decision for a task awaiting human review.

    Idempotency semantics:
        - First valid approval (task in AWAITING_APPROVAL): transitions to RESUMED,
          dispatches the resume worker, returns 200 with status RESUMED.
        - Duplicate approval (task already RESUMED or in a later state):
          returns 409 Conflict.  The original resume is unaffected.
        - Task not found: 404.
        - Task never reached approval (PENDING/RUNNING): 409 Conflict.
        - Task in terminal state (COMPLETED/FAILED): 409 Conflict.
    """
    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID")

    # Atomic claim – uses SELECT … FOR UPDATE inside the transaction.
    claimed, current_status = await try_claim_for_approval(session, tid)

    if not claimed:
        if current_status == "NOT_FOUND":
            raise HTTPException(status_code=404, detail="Task not found")
        if current_status == "RESUMED":
            raise HTTPException(
                status_code=409,
                detail="Approval already accepted; task is being resumed",
            )
        if current_status in TERMINAL_STATUSES:
            raise HTTPException(
                status_code=409,
                detail=f"Task already in terminal state: {current_status}",
            )
        # e.g. PENDING, RUNNING – not yet at approval gate
        raise HTTPException(
            status_code=409,
            detail=f"Task not awaiting approval (current status: {current_status})",
        )

    # Dispatch Celery job only after the DB transaction commits (via get_db).
    # If Celery dispatch fails the task stays RESUMED; the worker can be
    # retried manually.  This is safer than reverting the DB claim.
    resume_graph.delay(task_id, payload.approved, payload.feedback or "")
    return {"task_id": tid, "status": "RESUMED"}
