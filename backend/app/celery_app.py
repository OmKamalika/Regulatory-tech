"""
Celery application instance.
"""
from celery import Celery
from app.config import settings

celery_app = Celery(
    "regtech",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["app.tasks.video_pipeline"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    task_acks_late=False,
    worker_prefetch_multiplier=1,  # One task at a time per worker (heavy ML jobs)
)
