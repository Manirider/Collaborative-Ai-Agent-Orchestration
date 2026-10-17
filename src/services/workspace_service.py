import json
import redis
from src.config.settings import settings

redis_client = redis.from_url(
    settings.redis_url,
    decode_responses=True,
    socket_connect_timeout=0.2,
    socket_timeout=0.2,
)

# In-memory fallback for isolated unit testing when Redis is offline
_local_workspaces: dict[str, dict] = {}


def workspace_key(task_id: str) -> str:
    return f"task:{task_id}:workspace"


def reset_local_workspaces():
    """Clear in-memory workspaces (used in test teardown)."""
    _local_workspaces.clear()


def save_workspace(task_id: str, data: dict, ttl: int | None = None):
    key = workspace_key(task_id)
    try:
        redis_client.set(key, json.dumps(data))
        if ttl:
            redis_client.expire(key, ttl)
    except (redis.ConnectionError, redis.TimeoutError, Exception):
        _local_workspaces[key] = data


def load_workspace(task_id: str) -> dict | None:
    key = workspace_key(task_id)
    try:
        raw = redis_client.get(key)
        if not raw:
            return None
        return json.loads(raw)
    except (redis.ConnectionError, redis.TimeoutError, Exception):
        return _local_workspaces.get(key)
