"""Celery Beat 任务调度兼容入口。"""

from __future__ import annotations

from datetime import datetime, timedelta

from loguru import logger
from sqlmodel import Session, select

from aiSelfTest.models.task import Task, TaskExecutionStatus
from aiSelfTest.services.task_execution import is_task_running


ZOMBIE_TASK_ERROR = "启动时检测到僵尸状态"


class NoopTaskScheduler:
    """保留旧调用方兼容的空调度器。"""

    available = False

    def start(self) -> None:
        """提示任务调度已迁移到 Celery Beat。"""

        logger.info("Task 定时调度由 Celery Beat 负责，API 进程不启动本地调度器")

    def shutdown(self) -> None:
        """空调度器无需释放资源。"""

        return None

    def sync_task(self, task_id: int) -> None:
        """任务调度状态由数据库字段和 Celery Beat 扫描决定。"""

        logger.debug("跳过本地任务调度同步: task_id={}", task_id)

    def restore_active_tasks(self, session: Session) -> None:
        """Celery Beat 会扫描 active 任务，无需恢复本地 job。"""

        return None

    def recover_zombie_tasks(self, session: Session, now: datetime | None = None, stale_after_hours: int = 6) -> int:
        """复用僵尸任务恢复逻辑。"""

        return recover_zombie_tasks(session, now=now, stale_after_hours=stale_after_hours)


TaskScheduler = NoopTaskScheduler


def create_task_scheduler() -> NoopTaskScheduler:
    """创建兼容空调度器。"""

    return NoopTaskScheduler()


def set_global_task_scheduler(scheduler: NoopTaskScheduler | None) -> None:
    """保留旧接口，避免历史调用失败。"""

    logger.debug("忽略全局本地调度器设置: scheduler_type={}", type(scheduler).__name__)


def sync_global_task_scheduler(task_id: int) -> None:
    """保留旧接口，调度同步由 Celery Beat 负责。"""

    logger.debug("跳过全局本地任务调度同步: task_id={}", task_id)


def recover_zombie_tasks(session: Session, now: datetime | None = None, stale_after_hours: int = 6) -> int:
    """把启动时遗留的运行中僵尸任务转为失败态。"""

    current = now or datetime.now()
    threshold = current - timedelta(hours=stale_after_hours)
    running_tasks = session.exec(select(Task)).all()
    recovered = 0
    for task in running_tasks:
        if not is_task_running(task):
            continue
        marker = task.last_run_started_at or task.started_at or task.updated_at
        if marker and marker > threshold:
            continue
        previous_status = task.execution_status
        task.execution_status = TaskExecutionStatus.FAIL.value
        task.current_execution_id = None
        task.last_error = ZOMBIE_TASK_ERROR
        task.updated_at = current
        session.add(task)
        recovered += 1
        logger.warning(
            "恢复僵尸任务为失败态: task_id={}, previous_status={}, marker={}",
            task.id,
            previous_status,
            marker,
        )
    if recovered:
        session.commit()
        logger.info("僵尸任务恢复完成: recovered_count={}", recovered)
    return recovered
