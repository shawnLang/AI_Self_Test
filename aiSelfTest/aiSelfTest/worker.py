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
from aiSelfTest.logging import configure_deploy_logging
from aiSelfTest.models.task import (
    Task,
    TaskExecution,
    TaskExecutionRecordStatus,
    TaskExecutionStatus,
    TaskExecutionTriggerType,
)
from aiSelfTest.services.task_dispatch import TaskDispatchService
from aiSelfTest.services.task_execution import run_task_execution
from aiSelfTest.services.task_item_compensation import TaskItemCompensationService
from aiSelfTest.services.task_re_recognition import TaskItemReRecognitionService
from aiSelfTest.services.task_submission_job import TaskSubmissionJobService


def main_worker() -> None:
    """启动 Celery Worker，便于 IDE 以 Python 脚本方式调试。"""

    _start_worker(configure_logging=True)


def start_worker_without_logging_config() -> None:
    """启动 Celery Worker，供已完成日志配置的部署入口调用。"""

    _start_worker(configure_logging=False)


def _start_worker(*, configure_logging: bool) -> None:
    """按需配置日志后启动 Celery Worker。"""

    if configure_logging:
        configure_deploy_logging("worker")
    settings = get_settings()
    logger.info(
        "准备启动 Celery Worker: broker_url={} result_backend={} concurrency={} "
        "time_limit={} soft_time_limit={}",
        settings.redis_url,
        settings.redis_url,
        settings.task_worker_concurrency,
        settings.task_time_limit_seconds,
        settings.task_soft_time_limit_seconds,
    )
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

    _start_beat(configure_logging=True)


def start_beat_without_logging_config() -> None:
    """启动 Celery Beat，供已完成日志配置的部署入口调用。"""

    _start_beat(configure_logging=False)


def _start_beat(*, configure_logging: bool) -> None:
    """按需配置日志后启动 Celery Beat。"""

    if configure_logging:
        configure_deploy_logging("beat")
    settings = get_settings()
    logger.info(
        "准备启动 Celery Beat: broker_url={} scan_seconds={} running_stale_seconds={} queue_stale_seconds={}",
        settings.redis_url,
        settings.task_beat_scan_seconds,
        settings.task_running_stale_seconds,
        settings.task_queue_stale_seconds,
    )
    celery_app.start(
        [
            "beat",
            "--loglevel=info",
        ]
    )


@celery_app.task(name="aiSelfTest.execute_task", bind=True)
def execute_task(self: Any, task_id: int, execution_id: int) -> None:
    """执行单个任务执行实例。"""

    logger.info("Celery 任务执行入口: task_id={} execution_id={}", task_id, execution_id)
    with Session(engine) as session:
        execution = session.get(TaskExecution, execution_id)
        if execution is None:
            logger.warning("执行记录不存在，跳过 Celery 任务: task_id={} execution_id={}", task_id, execution_id)
            return
        if execution.status != TaskExecutionRecordStatus.QUEUED.value:
            logger.info(
                "执行记录状态不是 queued，跳过: task_id={} execution_id={} status={} trigger_type={} celery_task_id={}",
                task_id,
                execution_id,
                execution.status,
                execution.trigger_type,
                execution.celery_task_id,
            )
            return

        now = datetime.now()
        execution.status = TaskExecutionRecordStatus.RUNNING.value
        execution.started_at = now
        execution.last_heartbeat_at = now
        execution.updated_at = now
        session.add(execution)
        session.commit()
        logger.info(
            "Celery 任务执行记录进入 running: task_id={} execution_id={} trigger_type={} celery_task_id={} started_at={}",
            task_id,
            execution_id,
            execution.trigger_type,
            execution.celery_task_id,
            now,
        )

        try:
            result = run_task_execution(session, task_id)
            if getattr(result, "execution_status", None) == TaskExecutionStatus.FAIL.value:
                task = session.get(Task, task_id)
                error = task.last_error if task is not None and task.last_error else "任务执行失败"
                _mark_execution_failed(session, task_id, execution_id, error)
                logger.error(
                    "Celery 任务执行完成但任务状态为失败: task_id={} execution_id={} error={}",
                    task_id,
                    execution_id,
                    error,
                )
                return
            _mark_execution_success(session, task_id, execution_id)
            logger.info("Celery 任务执行成功: task_id={}, execution_id={}", task_id, execution_id)
        except SoftTimeLimitExceeded as exc:
            logger.exception("Celery 任务执行软超时: task_id={} execution_id={}", task_id, execution_id)
            _mark_execution_failed(session, task_id, execution_id, "任务执行软超时")
            raise exc
        except Exception as exc:
            logger.exception("Celery 任务执行异常: task_id={} execution_id={} error={}", task_id, execution_id, exc)
            _mark_execution_failed(session, task_id, execution_id, str(exc))
            raise


@celery_app.task(name="aiSelfTest.scan_scheduled_tasks")
def scan_scheduled_tasks() -> int:
    """扫描到期的启用任务并提交定时执行。"""

    now = datetime.now()
    submitted = 0
    with Session(engine) as session:
        logger.info("定时任务扫描开始: now={}", now)
        tasks = session.exec(
            select(Task)
            .where(Task.active == True)  # noqa: E712
            .where((Task.next_run_at == None) | (Task.next_run_at <= now))  # noqa: E711
        ).all()
        logger.info("定时任务扫描命中: count={} now={}", len(tasks), now)
        for task in tasks:
            if task.id is None:
                continue
            try:
                logger.info(
                    "定时任务准备派发: task_id={} name={} interval={} next_run_at={} status={} current_execution_id={}",
                    task.id,
                    task.name,
                    task.interval,
                    task.next_run_at,
                    task.execution_status,
                    task.current_execution_id,
                )
                dispatch_result = TaskDispatchService(session).submit(task.id, TaskExecutionTriggerType.SCHEDULE.value)
                if dispatch_result.enqueued:
                    task.next_run_at = now + timedelta(hours=task.interval)
                    task.updated_at = now
                    session.add(task)
                    session.commit()
                    submitted += 1
                    logger.info(
                        "定时任务派发成功: task_id={} execution_id={} next_run_at={}",
                        task.id,
                        dispatch_result.execution.id,
                        task.next_run_at,
                    )
                else:
                    logger.info(
                        "定时任务派发跳过: task_id={} execution_id={} active_status={}",
                        task.id,
                        dispatch_result.execution.id,
                        dispatch_result.execution.status,
                    )
            except Exception:
                session.rollback()
                logger.exception(
                    "定时任务派发失败: task_id={} name={} interval={} next_run_at={} status={} current_execution_id={}",
                    task.id,
                    task.name,
                    task.interval,
                    task.next_run_at,
                    task.execution_status,
                    task.current_execution_id,
                )
    logger.info("定时任务扫描结束: submitted={} scanned_at={}", submitted, now)
    return submitted


@celery_app.task(name="aiSelfTest.recover_stale_task_executions")
def recover_stale_task_executions() -> dict[str, int]:
    """恢复异常停滞的执行记录。"""

    with Session(engine) as session:
        logger.info("异常停滞执行记录恢复开始")
        service = TaskDispatchService(session)
        queued = service.recover_stale_queued()
        running = service.recover_stale_running()
        logger.info("异常停滞执行记录恢复完成: queued={} running={}", queued, running)
        return {"queued": queued, "running": running}


@celery_app.task(name="aiSelfTest.scan_failed_task_items_for_compensation")
def scan_failed_task_items_for_compensation() -> int:
    """扫描下载或识别失败的任务项并提交补偿。"""

    with Session(engine) as session:
        logger.info("任务项失败补偿扫描 Celery 入口")
        submitted = TaskItemCompensationService(session).scan_and_enqueue()
        logger.info("任务项失败补偿扫描 Celery 完成: submitted={}", submitted)
        return submitted


@celery_app.task(name="aiSelfTest.execute_task_item_compensation", bind=True)
def execute_task_item_compensation(self: Any, task_id: int, execution_id: int) -> dict[str, int | str | None]:
    """执行单个任务的失败任务项补偿。"""

    logger.info("Celery 任务项补偿入口: task_id={} execution_id={}", task_id, execution_id)
    with Session(engine) as session:
        try:
            result = TaskItemCompensationService(session).execute(task_id, execution_id)
            logger.info(
                "Celery 任务项补偿完成: task_id={} execution_id={} total={} success={} failed={} skipped={}",
                task_id,
                execution_id,
                result.total_count,
                result.success_count,
                result.failed_count,
                result.skipped_count,
            )
            return result.as_dict()
        except Exception:
            logger.exception("Celery 任务项补偿失败: task_id={} execution_id={}", task_id, execution_id)
            raise


@celery_app.task(name="aiSelfTest.execute_task_item_re_recognition_batch", bind=True)
def execute_task_item_re_recognition_batch(self: Any, batch_id: int) -> None:
    """执行任务项批量重新识别。"""

    logger.info("Celery 批量重新识别入口: batch_id={}", batch_id)
    with Session(engine) as session:
        try:
            TaskItemReRecognitionService(session).execute_batch(batch_id)
            logger.info("Celery 批量重新识别完成: batch_id={}", batch_id)
        except Exception:
            logger.exception("Celery 批量重新识别失败: batch_id={}", batch_id)
            raise


@celery_app.task(name="aiSelfTest.execute_task_submission", bind=True)
def execute_task_submission(self: Any, submission_id: int) -> None:
    """执行任务级提交远端与训练保存。"""

    logger.info("Celery 任务提交保存入口: submission_id={}", submission_id)
    with Session(engine) as session:
        try:
            TaskSubmissionJobService(session).execute(submission_id)
            logger.info("Celery 任务提交保存完成: submission_id={}", submission_id)
        except Exception:
            logger.exception("Celery 任务提交保存失败: submission_id={}", submission_id)
            raise


celery_app.conf.beat_schedule = {
    "scan-scheduled-tasks": {
        "task": "aiSelfTest.scan_scheduled_tasks",
        "schedule": get_settings().task_beat_scan_seconds,
    },
    "recover-stale-task-executions": {
        "task": "aiSelfTest.recover_stale_task_executions",
        "schedule": max(60, get_settings().task_beat_scan_seconds),
    },
    "scan-failed-task-items-for-compensation": {
        "task": "aiSelfTest.scan_failed_task_items_for_compensation",
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
    logger.info("执行记录已标记成功: task_id={} execution_id={} finished_at={}", task_id, execution_id, finished_at)


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
    logger.error("执行记录已标记失败: task_id={} execution_id={} error={} failed_at={}", task_id, execution_id, error, failed_at)
