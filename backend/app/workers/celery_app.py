"""Celery application configured with Redis as broker and result backend."""

from typing import Any

from celery import Celery  # type: ignore[import-untyped]
from celery.signals import worker_init  # type: ignore[import-untyped]

from app.core.settings import settings

celery_app = Celery(
    "rfp_response_intelligence",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True,
    result_expires=86400,
    task_default_queue="default",
    task_routes={
        "app.workers.tasks.ping_task": {"queue": "default"},
    },
)


@worker_init.connect
def configure_worker_logging(**kwargs: Any) -> None:
    """Configure structured logging for Celery workers."""
    from app.core.logging import configure_logging

    configure_logging()