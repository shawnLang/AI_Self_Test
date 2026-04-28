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
        """提示调度器不可用，保持应用启动流程不中断。"""

        logger.warning("APScheduler 未安装，Task 自动调度不会启动")

    def shutdown(self) -> None:
        """APScheduler 缺失时无需释放任何资源。"""

        return None

    def sync_task(self, task_id: int) -> None:
        """APScheduler 缺失时跳过单任务同步。"""

        logger.debug("跳过 Task {} 调度同步：APScheduler 不可用", task_id)

    def restore_active_tasks(self, session: Session) -> None:
        """APScheduler 缺失时跳过启用任务恢复。"""

        logger.debug("跳过启用任务恢复：APScheduler 不可用")
        return None

    def recover_zombie_tasks(
        self,
        session: Session,
        *,
        now: datetime | None = None,
        stale_after_hours: int = 6,
    ) -> int:
        """复用通用僵尸任务恢复逻辑，便于测试空调度器行为。"""

        return recover_zombie_tasks(session, now=now, stale_after_hours=stale_after_hours)


class TaskScheduler:
    """进程内 Task 调度器。

    APScheduler 实例可注入，便于单元测试验证 job 注册行为。
    """

    available = True

    def __init__(self, *, scheduler: Any | None = None) -> None:
        """创建单进程 Task 调度器包装器。"""

        if scheduler is None and AsyncIOScheduler is None:
            raise RuntimeError("APScheduler 未安装")
        self.scheduler = scheduler or AsyncIOScheduler()

    def start(self) -> None:
        """启动调度器前恢复数据库中可继续调度的任务。"""

        with Session(engine) as session:
            recovered = recover_zombie_tasks(session)
            logger.info("Task 调度器启动前恢复僵尸任务完成: recovered_count={}", recovered)
            self.restore_active_tasks(session)

        if not getattr(self.scheduler, "running", False):
            self.scheduler.start()
            logger.info("Task 调度器已启动")

    def shutdown(self) -> None:
        """关闭底层 APScheduler 实例。"""

        if getattr(self.scheduler, "running", False):
            self.scheduler.shutdown(wait=False)
            logger.info("Task 调度器已关闭")

    def restore_active_tasks(self, session: Session) -> None:
        """把数据库中启用的任务恢复到调度器。"""

        tasks = session.exec(select(Task).where(Task.active == True)).all()  # noqa: E712
        logger.info("开始恢复启用任务调度: count={}", len(tasks))
        for task in tasks:
            self._schedule_task(task)

    def sync_task(self, task_id: int) -> None:
        """根据数据库状态同步单个任务的调度 job。"""

        with Session(engine) as session:
            task = session.get(Task, task_id)
            if task is None or not task.active:
                self._remove_task(task_id)
                logger.info("任务调度已移除: task_id={}, reason=missing_or_inactive", task_id)
                return
            self._schedule_task(task)
            logger.info("任务调度已同步: task_id={}, interval_hours={}", task_id, task.interval)

    def run_task_job(self, task_id: int) -> None:
        """执行 APScheduler 触发的单个任务 job。"""

        with Session(engine) as session:
            task = session.get(Task, task_id)
            if task is None:
                self._remove_task(task_id)
                logger.info("调度触发跳过任务: task_id={}, reason=missing", task_id)
                return
            if is_task_running(task):
                task.skipped_count += 1
                task.updated_at = datetime.now()
                session.add(task)
                session.commit()
                logger.warning("调度触发时任务 {} 仍在运行，已跳过", task_id)
                return
            logger.info("调度触发任务执行: task_id={}", task_id)
            run_task_execution(session, task_id)

    def _schedule_task(self, task: Task) -> None:
        """注册或替换单个任务的 APScheduler job。"""

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
        logger.info(
            "任务调度注册完成: task_id={}, interval_hours={}",
            task.id,
            task.interval,
        )

    def _remove_task(self, task_id: int) -> None:
        """从调度器中移除单个任务 job。"""

        job_id = _job_id(task_id)
        if self.scheduler.get_job(job_id) is not None:
            self.scheduler.remove_job(job_id)
            logger.debug("任务调度 job 已移除: task_id={}, job_id={}", task_id, job_id)


def create_task_scheduler() -> TaskScheduler | NoopTaskScheduler:
    """创建调度器；缺少 APScheduler 时返回安全空实现。"""

    if AsyncIOScheduler is None:
        logger.warning("创建 NoopTaskScheduler：APScheduler 不可用")
        return NoopTaskScheduler()
    logger.debug("创建 TaskScheduler：APScheduler 可用")
    return TaskScheduler()


def set_global_task_scheduler(scheduler: TaskScheduler | NoopTaskScheduler | None) -> None:
    """设置当前进程的全局调度器引用。"""

    global _global_scheduler
    _global_scheduler = scheduler
    logger.debug("全局 Task 调度器已设置: scheduler_type={}", type(scheduler).__name__)


def sync_global_task_scheduler(task_id: int) -> None:
    """在 Task 变更后同步全局调度状态。"""

    if _global_scheduler is None:
        logger.debug("跳过全局任务调度同步：调度器未初始化, task_id={}", task_id)
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
        logger.warning(
            "恢复僵尸任务状态: task_id={}, marker={}, stale_after_hours={}",
            task.id,
            marker,
            stale_after_hours,
        )
    if recovered:
        session.commit()
        logger.info("僵尸任务恢复完成: recovered_count={}", recovered)
    return recovered


def _job_id(task_id: int) -> str:
    """生成 APScheduler job id。"""

    return f"{TASK_JOB_PREFIX}{task_id}"
