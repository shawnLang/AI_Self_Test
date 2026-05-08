"""任务执行派发服务。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from fastapi import status
from loguru import logger
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from aiSelfTest.config import get_settings
from aiSelfTest.exceptions import AppException, ErrorCode
from aiSelfTest.models.task import (
    Task,
    TaskExecution,
    TaskExecutionRecordStatus,
    TaskExecutionStatus,
    TaskExecutionTriggerType,
)


ACTIVE_EXECUTION_STATUSES = {
    TaskExecutionRecordStatus.QUEUED.value,
    TaskExecutionRecordStatus.RUNNING.value,
}

TERMINAL_EXECUTION_STATUSES = {
    TaskExecutionRecordStatus.SUCCESS.value,
    TaskExecutionRecordStatus.FAILED.value,
    TaskExecutionRecordStatus.SKIPPED.value,
    TaskExecutionRecordStatus.CANCELLED.value,
}


@dataclass(frozen=True)
class DispatchResult:
    """任务派发结果。"""

    task: Task
    execution: TaskExecution
    enqueued: bool = True


class TaskDispatchService:
    """统一处理任务执行记录创建和 Celery 投递。"""

    def __init__(self, session: Session) -> None:
        """保存数据库会话。"""

        self.session = session

    def submit(self, task_id: int, trigger_type: str) -> DispatchResult:
        """创建执行记录并投递 Celery 任务。"""

        self._validate_trigger_type(trigger_type)
        now = datetime.now()
        task = self._get_task_or_raise(task_id)
        existing_execution = self.get_active_execution(task_id)
        if existing_execution is not None:
            if trigger_type == TaskExecutionTriggerType.SCHEDULE.value:
                task.skipped_count += 1
                task.updated_at = now
                self.session.add(task)
                self.session.commit()
                logger.info("定时触发跳过，任务已有执行实例: task_id={}, execution_id={}", task_id,
                            existing_execution.id)
                return DispatchResult(task=task, execution=existing_execution, enqueued=False)
            raise AppException(
                code=ErrorCode.RESOURCE_BUSY,
                message="任务正在执行或排队中",
                status_code=status.HTTP_409_CONFLICT,
            )

        execution = TaskExecution(
            task_id=task_id,
            trigger_type=trigger_type,
            status=TaskExecutionRecordStatus.QUEUED.value,
            created_at=now,
            updated_at=now,
        )
        try:
            self.session.add(execution)
            self.session.flush()
            task.current_execution_id = execution.id
            task.updated_at = now
            self.session.add(task)
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise AppException(
                code=ErrorCode.RESOURCE_BUSY,
                message="任务正在执行或排队中",
                status_code=status.HTTP_409_CONFLICT,
            ) from exc

        self.session.refresh(task)
        self.session.refresh(execution)
        celery_task_id = self._build_celery_task_id(execution.id or 0)
        try:
            self._enqueue_task(task_id, execution.id or 0, celery_task_id)
        except Exception as exc:
            logger.exception("任务投递 Celery 失败: task_id={}, execution_id={}", task_id, execution.id)
            self._mark_dispatch_failed(task, execution, str(exc))
            raise AppException(
                code=ErrorCode.TASK_FAILED,
                message="任务入队失败，请稍后重试",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            ) from exc

        execution.celery_task_id = celery_task_id
        execution.updated_at = datetime.now()
        self.session.add(execution)
        self.session.commit()
        self.session.refresh(task)
        self.session.refresh(execution)
        logger.info("任务已提交后台执行: task_id={}, execution_id={}, trigger_type={}", task_id, execution.id,
                    trigger_type)
        return DispatchResult(task=task, execution=execution, enqueued=True)

    def get_active_execution(self, task_id: int) -> TaskExecution | None:
        """返回任务当前排队或运行中的执行实例。"""

        return self.session.exec(
            select(TaskExecution)
            .where(TaskExecution.task_id == task_id)
            .where(TaskExecution.status.in_(ACTIVE_EXECUTION_STATUSES))
            .order_by(TaskExecution.created_at.desc())
        ).first()

    def recover_stale_queued(self, now: datetime | None = None, max_retries: int = 3) -> int:
        """补偿长时间未被 Worker 接收的 queued 执行记录。"""

        current = now or datetime.now()
        threshold = current - timedelta(seconds=get_settings().task_queue_stale_seconds)
        executions = self.session.exec(
            select(TaskExecution)
            .where(TaskExecution.status == TaskExecutionRecordStatus.QUEUED.value)
            .where(TaskExecution.updated_at < threshold)
        ).all()
        recovered = 0
        for execution in executions:
            if execution.retry_count >= max_retries:
                self._finish_execution_as_failed(execution, "排队超时未被 Worker 接收", current)
                recovered += 1
                continue

            celery_task_id = self._build_celery_task_id(execution.id or 0)
            self._enqueue_task(execution.task_id, execution.id or 0, celery_task_id)
            execution.celery_task_id = celery_task_id
            execution.retry_count += 1
            execution.updated_at = current
            self.session.add(execution)
            recovered += 1
        if recovered:
            self.session.commit()
        return recovered

    def recover_stale_running(self, now: datetime | None = None) -> int:
        """恢复心跳超时的 running 执行记录。"""

        current = now or datetime.now()
        threshold = current - timedelta(seconds=get_settings().task_running_stale_seconds)
        executions = self.session.exec(
            select(TaskExecution)
            .where(TaskExecution.status == TaskExecutionRecordStatus.RUNNING.value)
            .where(TaskExecution.last_heartbeat_at < threshold)
        ).all()
        for execution in executions:
            self._finish_execution_as_failed(execution, "Worker 心跳超时，任务已恢复为失败", current)
        if executions:
            self.session.commit()
        return len(executions)

    @staticmethod
    def _validate_trigger_type(trigger_type: str) -> None:
        """校验触发来源。"""

        allowed = {item.value for item in TaskExecutionTriggerType}
        if trigger_type not in allowed:
            raise AppException(code=ErrorCode.PARAM_INVALID, message="任务执行触发来源无效", status_code=400)

    def _get_task_or_raise(self, task_id: int) -> Task:
        """查询任务，不存在时抛出业务异常。"""

        task = self.session.get(Task, task_id)
        if task is None:
            raise AppException(code=ErrorCode.NOT_FOUND, message="任务不存在", status_code=404)
        return task

    def _mark_dispatch_failed(self, task: Task, execution: TaskExecution, error: str) -> None:
        """Celery 投递失败时回写执行记录。"""

        now = datetime.now()
        execution.status = TaskExecutionRecordStatus.CANCELLED.value
        execution.error = error
        execution.finished_at = now
        execution.updated_at = now
        task.current_execution_id = None
        task.last_error = "任务入队失败"
        task.updated_at = now
        self.session.add(execution)
        self.session.add(task)
        self.session.commit()

    def _finish_execution_as_failed(self, execution: TaskExecution, error: str, now: datetime) -> None:
        """将执行记录和任务聚合状态标记为失败。"""

        execution.status = TaskExecutionRecordStatus.FAILED.value
        execution.error = error
        execution.finished_at = now
        execution.updated_at = now
        task = self.session.get(Task, execution.task_id)
        if task is not None:
            task.current_execution_id = None
            task.execution_status = TaskExecutionStatus.FAIL.value
            task.last_error = error
            task.updated_at = now
            self.session.add(task)
        self.session.add(execution)

    @staticmethod
    def _build_celery_task_id(execution_id: int) -> str:
        """构造确定性 Celery task id。"""

        return f"task-execution-{execution_id}"

    @staticmethod
    def _enqueue_task(task_id: int, execution_id: int, celery_task_id: str) -> None:
        """投递 Celery 任务。"""

        from aiSelfTest.worker import execute_task

        execute_task.apply_async(args=[task_id, execution_id], task_id=celery_task_id)
