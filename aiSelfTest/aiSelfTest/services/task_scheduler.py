"""单进程 Task 调度器封装。"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from aiSelfTest.database import engine
from aiSelfTest.models.task import Task, TaskExecutionStatus
from aiSelfTest.services.task_execution import is_task_running, run_task_execution
from loguru import logger
from sqlmodel import Session, select

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
        """记录调度器不可用状态，并保持调用方启动流程可继续。"""

        logger.warning("APScheduler 未安装，Task 自动调度不会启动")

    def shutdown(self) -> None:
        """空调度器无需释放资源。"""

        return None

    def sync_task(self, task_id: int) -> None:
        """记录被跳过的单任务同步请求。"""

        logger.debug("跳过 Task {} 调度同步：APScheduler 不可用", task_id)

    def restore_active_tasks(self, session: Session) -> None:
        """空调度器不恢复任务，保持接口与真实调度器一致。"""

        return None

    def recover_zombie_tasks(self, session: Session, now: datetime | None = None, stale_after_hours: int = 6) -> int:
        """复用公共僵尸任务恢复逻辑，保证缺依赖时仍能修正状态。"""

        return recover_zombie_tasks(session, now=now, stale_after_hours=stale_after_hours)


class TaskScheduler:
    """进程内 Task 调度器。

    APScheduler 实例可注入，便于单元测试验证 job 注册行为。
    """

    available = True

    def __init__(self, scheduler: Any | None = None) -> None:
        """初始化调度器，允许测试传入伪 scheduler。"""

        if scheduler is None and AsyncIOScheduler is None:
            raise RuntimeError("APScheduler 未安装")
        self.scheduler = scheduler or AsyncIOScheduler()

    def start(self) -> None:
        """启动 APScheduler，并在启动前恢复任务状态和已启用任务。"""

        logger.info("启动 Task 调度器")
        with Session(engine) as session:
            recovered = recover_zombie_tasks(session)
            if recovered:
                logger.warning("启动时恢复僵尸任务: recovered_count={}", recovered)
            self.restore_active_tasks(session)

        if not getattr(self.scheduler, "running", False):
            self.scheduler.start()
            logger.info("Task 调度器已启动")

    def shutdown(self) -> None:
        """停止 APScheduler，避免应用关闭后继续触发后台任务。"""

        if getattr(self.scheduler, "running", False):
            self.scheduler.shutdown(wait=False)
            logger.info("Task 调度器已关闭")

    def restore_active_tasks(self, session: Session) -> None:
        """从数据库恢复 active=True 的任务并重新注册周期 job。"""

        tasks = session.exec(select(Task).where(Task.active == True)).all()  # noqa: E712
        logger.info("恢复活跃任务调度: count={}", len(tasks))
        for task in tasks:
            self._schedule_task(task)

    def sync_task(self, task_id: int) -> None:
        """在任务启停或配置变更后，同步单个任务的调度 job。"""

        with Session(engine) as session:
            task = session.get(Task, task_id)
            if task is None or not task.active:
                self._remove_task(task_id)
                logger.debug("任务未启用或不存在，已移除调度: task_id={}", task_id)
                return
            self._schedule_task(task)
            logger.info("任务调度已同步: task_id={}, interval_hours={}", task_id, task.interval)

    def run_task_job(self, task_id: int) -> None:
        """APScheduler 触发的任务执行入口。"""

        logger.info("调度触发任务执行: task_id={}", task_id)
        with Session(engine) as session:
            task = session.get(Task, task_id)
            if task is None:
                self._remove_task(task_id)
                logger.warning("调度任务不存在，已移除 job: task_id={}", task_id)
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
        """注册或替换单个任务的周期执行 job。"""

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
        logger.info("任务调度已同步: task_id={}, interval_hours={}", task.id, task.interval)

    def _remove_task(self, task_id: int) -> None:
        """移除单个任务对应的周期执行 job。"""

        job_id = _job_id(task_id)
        if self.scheduler.get_job(job_id) is not None:
            self.scheduler.remove_job(job_id)
            logger.info("任务调度已移除: task_id={}", task_id)


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


def _job_id(task_id: int) -> str:
    """生成 APScheduler job ID，确保任务与调度记录一一对应。"""

    return f"{TASK_JOB_PREFIX}{task_id}"
