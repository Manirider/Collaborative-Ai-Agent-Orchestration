"""WebSocket endpoint for real-time task lifecycle events.

Design notes:
- On connect, validates the task_id format and sends the current persisted state as
  the initial snapshot so the client immediately knows task status/logs.
- Then subscribes to Redis Pub/Sub for subsequent lifecycle events.
- The subscription is created *before* the initial snapshot is read to avoid
  a race where an event fires between reading the snapshot and subscribing.
  Any events received during the snapshot read are delivered immediately after.

Limitation:
  Redis Pub/Sub is fire-and-forget. If the client disconnects and
  reconnects, events published during the gap are lost. For durable
  event replay, a persistent event log (e.g. Redis Streams or a DB
  table) would be required. This is documented but not implemented.
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import json
import asyncio
import uuid
import logging

from src.services.event_service import subscribe_task_events
from src.db.session import get_session
from src.services.task_service import get_task

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws/tasks/{task_id}")
async def websocket_task_events(websocket: WebSocket, task_id: str):
    # Validate task_id format before accepting
    try:
        task_uuid = uuid.UUID(task_id)
    except ValueError:
        await websocket.close(code=4400, reason="Invalid task ID format")
        return

    await websocket.accept()

    # Subscribe FIRST to avoid missing events between snapshot and subscribe
    pubsub = subscribe_task_events(task_id)

    try:
        # Read persisted task state for initial snapshot
        snapshot = await _build_snapshot(task_uuid, task_id)
        await websocket.send_text(json.dumps(snapshot))

        # Drain any events that arrived between subscribe and now
        while True:
            message = pubsub.get_message(timeout=0)
            if message and message["type"] == "message":
                await websocket.send_text(message["data"])
            else:
                break

        # Stream subsequent events
        while True:
            message = pubsub.get_message(timeout=1.0)
            if message and message["type"] == "message":
                await websocket.send_text(message["data"])
            await asyncio.sleep(0.1)

    except WebSocketDisconnect:
        logger.debug("WebSocket client disconnected for task %s", task_id)
    except Exception:
        logger.exception("WebSocket error for task %s", task_id)
    finally:
        try:
            pubsub.unsubscribe()
            pubsub.close()
        except Exception:
            pass


async def _build_snapshot(task_uuid: uuid.UUID, task_id: str) -> dict:
    """Build the initial snapshot from persisted DB state."""
    try:
        async with get_session() as session:
            task = await get_task(session, task_uuid)
            if task is None:
                return {
                    "task_id": task_id,
                    "status": "NOT_FOUND",
                    "result": None,
                    "agent_logs": [],
                }
            return {
                "task_id": task_id,
                "status": task.status,
                "result": task.result,
                "agent_logs": task.agent_logs or [],
                "created_at": task.created_at.isoformat() if task.created_at else None,
                "updated_at": task.updated_at.isoformat() if task.updated_at else None,
            }
    except Exception:
        logger.exception("Failed to read task snapshot for %s", task_id)
        return {
            "task_id": task_id,
            "status": "SNAPSHOT_ERROR",
            "result": None,
            "agent_logs": [],
        }
