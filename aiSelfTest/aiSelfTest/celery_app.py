"""Celery 应用初始化。"""

from __future__ import annotations

from celery import Celery

from aiSelfTest.config import get_settings


settings = get_settings()

celery_app = Celery("aiSelfTest")
celery_app.conf.update(
    broker_url=settings.redis_url,
    result_backend=settings.redis_url,
    task_time_limit=settings.task_time_limit_seconds,
    task_soft_time_limit=settings.task_soft_time_limit_seconds,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    worker_hijack_root_logger=False,
    worker_redirect_stdouts=True,
    worker_redirect_stdouts_level="INFO",
    task_track_started=True,
    timezone="Asia/Shanghai",
)

celery_app.autodiscover_tasks(["aiSelfTest"])
