"""Celery Worker 与 Beat 任务入口。"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from celery.exceptions import SoftTimeLimitExceeded
from loguru import logger
from sqlmodel import Session, select

from aiSelfTest.celery_app import celery_app
from aiSelfTest.config import get_settings
from aiSelfTest.database import engine
from aiSelfTest.models.task import (
    Task,
    TaskExecution,
    TaskExecutionRecordStatus,
    TaskExecutionStatus,
    TaskExecutionTriggerType,
)
from aiSelfTest.services.task_dispatch import TaskDispatchService
from aiSelfTest.services.task_execution import run_task_execution
from aiSelfTest.services.task_re_recognition import TaskItemReRecognitionService


def main_worker() -> None:
    """启动 Celery Worker，便于 IDE 以 Python 脚本方式调试。"""

    settings = get_settings()
    celery_app.worker_main(
        [
            "worker",
            "--loglevel=info",
            f"--concurrency={settings.task_worker_concurrency}",
            "--pool=solo",
        ]
    )


def main_beat() -> None:
    """启动 Celery Beat，便于 IDE 以 Python 脚本方式调试。"""

    celery_app.start(
        [
            "beat",
            "--loglevel=info",
        ]
    )


@celery_app.task(name="aiSelfTest.execute_task", bind=True)
def execute_task(self: Any, task_id: int, execution_id: int) -> None:
    """执行单个任务执行实例。"""

    with Session(engine) as session:
        execution = session.get(TaskExecution, execution_id)
        if execution is None:
            logger.warning("执行记录不存在，跳过 Celery 任务: execution_id={}", execution_id)
            return
        if execution.status != TaskExecutionRecordStatus.QUEUED.value:
            logger.info("执行记录状态不是 queued，跳过: execution_id={}, status={}", execution_id, execution.status)
            return

        now = datetime.now()
        execution.status = TaskExecutionRecordStatus.RUNNING.value
        execution.started_at = now
        execution.last_heartbeat_at = now
        execution.updated_at = now
        session.add(execution)
        session.commit()

        try:
            run_task_execution(session, task_id)
            _mark_execution_success(session, task_id, execution_id)
            logger.info("Celery 任务执行成功: task_id={}, execution_id={}", task_id, execution_id)
        except SoftTimeLimitExceeded as exc:
            _mark_execution_failed(session, task_id, execution_id, "任务执行软超时")
            raise exc
        except Exception as exc:
            _mark_execution_failed(session, task_id, execution_id, str(exc))
            raise


@celery_app.task(name="aiSelfTest.scan_scheduled_tasks")
def scan_scheduled_tasks() -> int:
    """扫描到期的启用任务并提交定时执行。"""

    now = datetime.now()
    submitted = 0
    with Session(engine) as session:
        tasks = session.exec(
            select(Task)
            .where(Task.active == True)  # noqa: E712
            .where((Task.next_run_at == None) | (Task.next_run_at <= now))  # noqa: E711
        ).all()
        for task in tasks:
            if task.id is None:
                continue
            try:
                dispatch_result = TaskDispatchService(session).submit(task.id, TaskExecutionTriggerType.SCHEDULE.value)
                if dispatch_result.enqueued:
                    task.next_run_at = now + timedelta(hours=task.interval)
                    task.updated_at = now
                    session.add(task)
                    session.commit()
                    submitted += 1
            except Exception:
                session.rollback()
                logger.exception("定时任务派发失败: task_id={}", task.id)
    return submitted


@celery_app.task(name="aiSelfTest.recover_stale_task_executions")
def recover_stale_task_executions() -> dict[str, int]:
    """恢复异常停滞的执行记录。"""

    with Session(engine) as session:
        service = TaskDispatchService(session)
        queued = service.recover_stale_queued()
        running = service.recover_stale_running()
        return {"queued": queued, "running": running}


@celery_app.task(name="aiSelfTest.execute_task_item_re_recognition_batch", bind=True)
def execute_task_item_re_recognition_batch(self: Any, batch_id: int) -> None:
    """执行任务项批量重新识别。"""

    with Session(engine) as session:
        TaskItemReRecognitionService(session).execute_batch(batch_id)


celery_app.conf.beat_schedule = {
    "scan-scheduled-tasks": {
        "task": "aiSelfTest.scan_scheduled_tasks",
        "schedule": get_settings().task_beat_scan_seconds,
    },
    "recover-stale-task-executions": {
        "task": "aiSelfTest.recover_stale_task_executions",
        "schedule": max(60, get_settings().task_beat_scan_seconds),
    },
}


def _mark_execution_success(session: Session, task_id: int, execution_id: int) -> None:
    """将执行实例标记为成功，并释放任务当前执行指针。"""

    finished_at = datetime.now()
    execution = session.get(TaskExecution, execution_id)
    if execution is not None:
        execution.status = TaskExecutionRecordStatus.SUCCESS.value
        execution.finished_at = finished_at
        execution.last_heartbeat_at = finished_at
        execution.updated_at = finished_at
        session.add(execution)

    task = session.get(Task, task_id)
    if task is not None:
        task.current_execution_id = None
        task.updated_at = finished_at
        session.add(task)

    session.commit()


def _mark_execution_failed(session: Session, task_id: int, execution_id: int, error: str) -> None:
    """将执行实例和任务聚合状态标记为失败。"""

    failed_at = datetime.now()
    execution = session.get(TaskExecution, execution_id)
    if execution is not None:
        execution.status = TaskExecutionRecordStatus.FAILED.value
        execution.error = error
        execution.finished_at = failed_at
        execution.last_heartbeat_at = failed_at
        execution.updated_at = failed_at
        session.add(execution)

    task = session.get(Task, task_id)
    if task is not None:
        task.current_execution_id = None
        task.execution_status = TaskExecutionStatus.FAIL.value
        task.last_error = error
        task.updated_at = failed_at
        session.add(task)

    session.commit()
    logger.exception("Celery 任务执行失败: task_id={}, execution_id={}", task_id, execution_id)
