"""单进程 Task 调度器封装。"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from loguru import logger
from sqlmodel import Session, select

from aiSelfTest.database import engine
from aiSelfTest.models.task import Task, TaskExecutionStatus
from aiSelfTest.services.task_execution import is_task_running, run_task_execution

try:  # pragma: no cover - 缺依赖时走 NoopTaskScheduler
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
except ImportError:  # pragma: no cover
    AsyncIOScheduler = None  # type: ignore[assignment]


TASK_JOB_PREFIX = "task_"
ZOMBIE_TASK_ERROR = "启动时检测到僵尸状态"
_global_scheduler: "TaskScheduler | NoopTaskScheduler | None" = None


class NoopTaskScheduler:
    """APScheduler 不可用时的安全空实现。"""

    available = False

    def start(self) -> None:
        logger.warning("APScheduler 未安装，Task 自动调度不会启动")

    def shutdown(self) -> None:
        return None

    def sync_task(self, task_id: int) -> None:
        logger.debug("跳过 Task {} 调度同步：APScheduler 不可用", task_id)

    def restore_active_tasks(self, session: Session) -> None:
        return None

    def recover_zombie_tasks(
        self,
        session: Session,
        *,
        now: datetime | None = None,
        stale_after_hours: int = 6,
    ) -> int:
        return recover_zombie_tasks(session, now=now, stale_after_hours=stale_after_hours)


class TaskScheduler:
    """进程内 Task 调度器。

    APScheduler 实例可注入，便于单元测试验证 job 注册行为。
    """

    available = True

    def __init__(self, *, scheduler: Any | None = None) -> None:
        if scheduler is None and AsyncIOScheduler is None:
            raise RuntimeError("APScheduler 未安装")
        self.scheduler = scheduler or AsyncIOScheduler()

    def start(self) -> None:
        with Session(engine) as session:
            recover_zombie_tasks(session)
            self.restore_active_tasks(session)

        if not getattr(self.scheduler, "running", False):
            self.scheduler.start()

    def shutdown(self) -> None:
        if getattr(self.scheduler, "running", False):
            self.scheduler.shutdown(wait=False)

    def restore_active_tasks(self, session: Session) -> None:
        tasks = session.exec(select(Task).where(Task.active == True)).all()  # noqa: E712
        for task in tasks:
            self._schedule_task(task)

    def sync_task(self, task_id: int) -> None:
        with Session(engine) as session:
            task = session.get(Task, task_id)
            if task is None or not task.active:
                self._remove_task(task_id)
                return
            self._schedule_task(task)

    def run_task_job(self, task_id: int) -> None:
        with Session(engine) as session:
            task = session.get(Task, task_id)
            if task is None:
                self._remove_task(task_id)
                return
            if is_task_running(task):
                task.skipped_count += 1
                task.updated_at = datetime.now()
                session.add(task)
                session.commit()
                logger.warning("调度触发时任务 {} 仍在运行，已跳过", task_id)
                return
            run_task_execution(session, task_id)

    def _schedule_task(self, task: Task) -> None:
        if task.id is None:
            return
        self.scheduler.add_job(
            self.run_task_job,
            "interval",
            hours=task.interval,
            id=_job_id(task.id),
            args=[task.id],
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )

    def _remove_task(self, task_id: int) -> None:
        job_id = _job_id(task_id)
        if self.scheduler.get_job(job_id) is not None:
            self.scheduler.remove_job(job_id)


def create_task_scheduler() -> TaskScheduler | NoopTaskScheduler:
    """创建调度器；缺少 APScheduler 时返回安全空实现。"""

    if AsyncIOScheduler is None:
        return NoopTaskScheduler()
    return TaskScheduler()


def set_global_task_scheduler(scheduler: TaskScheduler | NoopTaskScheduler | None) -> None:
    """设置当前进程的全局调度器引用。"""

    global _global_scheduler
    _global_scheduler = scheduler


def sync_global_task_scheduler(task_id: int) -> None:
    """在 Task 变更后同步全局调度状态。"""

    if _global_scheduler is None:
        return
    _global_scheduler.sync_task(task_id)


def recover_zombie_tasks(
    session: Session,
    *,
    now: datetime | None = None,
    stale_after_hours: int = 6,
) -> int:
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
        task.execution_status = TaskExecutionStatus.FAIL.value
        task.last_error = ZOMBIE_TASK_ERROR
        task.updated_at = current
        session.add(task)
        recovered += 1
    if recovered:
        session.commit()
    return recovered


def _job_id(task_id: int) -> str:
    return f"{TASK_JOB_PREFIX}{task_id}"
