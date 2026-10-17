import redis
from src.config.settings import settings

redis_client = redis.from_url(
    settings.redis_url,
    decode_responses=True,
    socket_connect_timeout=0.2,
    socket_timeout=0.2,
)

# In-memory fallback for unit testing when Redis is unreachable
_local_attempts: dict[str, int] = {}


def _attempt_key(task_id: str) -> str:
    return f"task:{task_id}:flaky_attempt"


class TransientError(RuntimeError):
    pass


def reset_flaky_attempts():
    """Reset attempt counters (used in test fixtures)."""
    _local_attempts.clear()


def research_tool(prompt: str, task_id: str) -> dict:
    """Mock research tool with simulated transient failure for flaky testing.

    If prompt contains __FLAKY_TEST__, the first attempt raises TransientError.
    Subsequent attempts succeed. Uses Redis if connected; otherwise in-memory dict.
    """
    if "__FLAKY_TEST__" in prompt:
        key = _attempt_key(task_id)
        try:
            attempts = int(redis_client.get(key) or "0")
            if attempts < 1:
                redis_client.set(key, str(attempts + 1))
                raise TransientError("Simulated transient network error")
            redis_client.delete(key)
        except (redis.ConnectionError, redis.TimeoutError, Exception):
            attempts = _local_attempts.get(key, 0)
            if attempts < 1:
                _local_attempts[key] = attempts + 1
                raise TransientError("Simulated transient network error")
            _local_attempts.pop(key, None)

    # Deterministic mock facts
    findings = {
        "langgraph": {
            "features": ["stateful multi-step workflows", "checkpointing", "human-in-the-loop", "conditional routing"]
        },
        "crewai": {
            "features": ["role-based agents", "task delegation", "collaborative workflows"]
        },
        "prompt": prompt
    }
    return findings
