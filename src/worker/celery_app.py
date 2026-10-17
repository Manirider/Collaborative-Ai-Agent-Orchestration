from celery import Celery
from src.config.settings import settings

celery_app = Celery(
    "agent_worker",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_time_limit=settings.task_timeout_seconds,
    task_soft_time_limit=settings.task_timeout_seconds,
    worker_prefetch_multiplier=1,
)
