import json
import logging
import redis
from src.config.settings import settings

logger = logging.getLogger(__name__)
redis_client = redis.from_url(
    settings.redis_url,
    decode_responses=True,
    socket_connect_timeout=0.2,
    socket_timeout=0.2,
)


class DummyPubSub:
    """Mock pubsub object for when Redis is unavailable in unit tests."""
    def get_message(self, timeout=0.0):
        return None

    def unsubscribe(self):
        pass

    def close(self):
        pass


def publish_task_event(task_id: str, status: str):
    channel = f"task:{task_id}:events"
    payload = json.dumps({"task_id": task_id, "status": status})
    try:
        redis_client.publish(channel, payload)
    except (redis.ConnectionError, redis.TimeoutError, Exception):
        logger.debug("Redis unavailable; skipping event publish for task %s", task_id)


def subscribe_task_events(task_id: str):
    channel = f"task:{task_id}:events"
    try:
        pubsub = redis_client.pubsub()
        pubsub.subscribe(channel)
        return pubsub
    except (redis.ConnectionError, redis.TimeoutError, Exception):
        logger.debug("Redis unavailable; returning DummyPubSub for task %s", task_id)
        return DummyPubSub()
