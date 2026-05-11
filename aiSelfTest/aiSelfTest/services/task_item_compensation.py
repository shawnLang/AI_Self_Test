"""任务项下载与识别失败补偿服务。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from fastapi import status
from loguru import logger
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from aiSelfTest.exceptions import AppException, ErrorCode
from aiSelfTest.models.task import (
    Task,
    TaskExecution,
    TaskExecutionRecordStatus,
    TaskExecutionStatus,
    TaskExecutionTriggerType,
    TaskItem,
    TaskItemConfirmState,
    TaskItemData,
    TaskItemDataStatus,
    TaskItemLlmState,
    TaskItemRemoteState,
    TaskItemStatus,
)
from aiSelfTest.services.task_execution import TaskExecutionRunner
from aiSelfTest.services.task_review import refresh_task_finish_state


TASK_ITEM_COMPENSATION_COOLDOWN_SECONDS = 300
TASK_ITEM_COMPENSATION_MAX_ATTEMPTS = 3
TASK_ITEM_COMPENSATION_SCAN_LIMIT = 20

ACTIVE_EXECUTION_STATUSES = {
    TaskExecutionRecordStatus.QUEUED.value,
    TaskExecutionRecordStatus.RUNNING.value,
}


@dataclass(frozen=True)
class TaskItemCompensationResult:
    """任务项补偿执行结果。"""

    total_count: int = 0
    success_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    error_summary: str | None = None

    def as_dict(self) -> dict[str, int | str | None]:
        """转换为 Celery 可序列化的字典。"""

        return {
            "total_count": self.total_count,
            "success_count": self.success_count,
            "failed_count": self.failed_count,
            "skipped_count": self.skipped_count,
            "error_summary": self.error_summary,
        }


@dataclass(frozen=True)
class TaskCompensationResetResult:
    """任务补偿恢复结果。"""

    task: Task
    execution: TaskExecution
    reset_count: int


class TaskItemCompensationService:
    """扫描并执行 TaskItem 失败补偿。"""

    def __init__(self, session: Session) -> None:
        """保存数据库会话。"""

        self.session = session

    def scan_and_enqueue(self, now: datetime | None = None) -> int:
        """扫描存在失败任务项的任务，并提交补偿执行。"""

        current = now or datetime.now()
        threshold = current - timedelta(seconds=TASK_ITEM_COMPENSATION_COOLDOWN_SECONDS)
        task_ids = self._list_task_ids_needing_compensation(threshold)
        logger.info(
            "任务项补偿扫描开始: threshold={} task_count={} cooldown_seconds={} max_attempts={}",
            threshold,
            len(task_ids),
            TASK_ITEM_COMPENSATION_COOLDOWN_SECONDS,
            TASK_ITEM_COMPENSATION_MAX_ATTEMPTS,
        )

        submitted = 0
        for task_id in task_ids:
            try:
                execution = self.enqueue_task(task_id, now=current)
                if execution is not None:
                    submitted += 1
            except Exception:
                self.session.rollback()
                logger.exception("任务项补偿投递失败: task_id={}", task_id)

        logger.info("任务项补偿扫描结束: task_count={} submitted={}", len(task_ids), submitted)
        return submitted

    def enqueue_task(self, task_id: int, now: datetime | None = None) -> TaskExecution | None:
        """为单个任务创建补偿执行记录并投递 Celery。"""

        current = now or datetime.now()
        task = self.session.get(Task, task_id)
        if task is None:
            logger.warning("任务项补偿跳过，任务不存在: task_id={}", task_id)
            return None

        existing_execution = self._get_active_execution(task_id)
        if existing_execution is not None:
            logger.info(
                "任务项补偿跳过，任务已有执行实例: task_id={} execution_id={} status={}",
                task_id,
                existing_execution.id,
                existing_execution.status,
            )
            return None

        if not self._has_compensable_task_items(task_id):
            logger.info("任务项补偿跳过，任务没有可补偿失败项: task_id={}", task_id)
            return None

        execution = TaskExecution(
            task_id=task_id,
            trigger_type=TaskExecutionTriggerType.REPAIR.value,
            status=TaskExecutionRecordStatus.QUEUED.value,
            created_at=current,
            updated_at=current,
        )
        try:
            self.session.add(execution)
            self.session.flush()
            task.current_execution_id = execution.id
            task.updated_at = current
            self.session.add(task)
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            logger.warning("任务项补偿执行记录创建冲突: task_id={} error={}", task_id, exc)
            raise AppException(
                code=ErrorCode.RESOURCE_BUSY,
                message="任务正在执行或排队中",
                status_code=status.HTTP_409_CONFLICT,
            ) from exc

        self.session.refresh(execution)
        celery_task_id = self._build_celery_task_id(execution.id or 0)
        logger.info(
            "任务项补偿执行记录创建完成，准备投递 Celery: task_id={} execution_id={} celery_task_id={}",
            task_id,
            execution.id,
            celery_task_id,
        )
        try:
            self._enqueue_compensation(task_id, execution.id or 0, celery_task_id)
        except Exception as exc:
            logger.exception(
                "任务项补偿投递 Celery 失败: task_id={} execution_id={} celery_task_id={} error={}",
                task_id,
                execution.id,
                celery_task_id,
                exc,
            )
            self._mark_execution_failed(execution.id or 0, f"任务项补偿入队失败: {exc}")
            raise AppException(
                code=ErrorCode.TASK_FAILED,
                message="任务项补偿入队失败，请稍后重试",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            ) from exc

        execution.celery_task_id = celery_task_id
        execution.updated_at = datetime.now()
        self.session.add(execution)
        self.session.commit()
        self.session.refresh(execution)
        logger.info("任务项补偿已提交后台执行: task_id={} execution_id={}", task_id, execution.id)
        return execution

    def reset_task_limited_items(self, task_id: int) -> TaskCompensationResetResult:
        """重置任务下达到补偿上限的失败项，并立即投递补偿。"""

        current = datetime.now()
        task = self.session.get(Task, task_id)
        if task is None:
            raise AppException(code=ErrorCode.NOT_FOUND, message="任务不存在", status_code=404)

        existing_execution = self._get_active_execution(task_id)
        if existing_execution is not None:
            raise AppException(
                code=ErrorCode.RESOURCE_BUSY,
                message="任务正在执行或排队中",
                status_code=status.HTTP_409_CONFLICT,
            )

        task_items = self._list_limited_failed_task_items(task_id)
        if not task_items:
            raise AppException(
                code=ErrorCode.PARAM_INVALID,
                message="任务下没有达到补偿上限的失败任务项",
                status_code=400,
            )

        for task_item in task_items:
            task_item.compensation_count = 0
            task_item.updated_at = current
            self.session.add(task_item)
        self.session.commit()
        logger.info(
            "任务补偿次数已人工重置: task_id={} task_item_ids={} reset_count={}",
            task_id,
            [item.id for item in task_items],
            len(task_items),
        )

        execution = self.enqueue_task(task_id, now=current)
        if execution is None:
            raise AppException(
                code=ErrorCode.TASK_FAILED,
                message="补偿恢复后未能创建补偿执行记录",
                status_code=500,
            )
        self.session.refresh(task)
        return TaskCompensationResetResult(task=task, execution=execution, reset_count=len(task_items))

    def execute(self, task_id: int, execution_id: int) -> TaskItemCompensationResult:
        """执行单个任务的失败任务项补偿。"""

        execution = self.session.get(TaskExecution, execution_id)
        if execution is None:
            logger.warning("任务项补偿执行记录不存在: task_id={} execution_id={}", task_id, execution_id)
            return TaskItemCompensationResult(error_summary="执行记录不存在")
        if execution.status != TaskExecutionRecordStatus.QUEUED.value:
            logger.info(
                "任务项补偿执行记录状态不是 queued，跳过: task_id={} execution_id={} status={}",
                task_id,
                execution_id,
                execution.status,
            )
            return TaskItemCompensationResult(error_summary=f"执行记录状态不是 queued: {execution.status}")

        task = self.session.get(Task, task_id)
        if task is None:
            self._mark_execution_failed(execution_id, "任务不存在")
            return TaskItemCompensationResult(error_summary="任务不存在")
        if task.current_execution_id not in {None, execution_id}:
            execution.status = TaskExecutionRecordStatus.SKIPPED.value
            execution.error = f"任务已有其他执行实例: {task.current_execution_id}"
            execution.finished_at = datetime.now()
            execution.updated_at = execution.finished_at
            self.session.add(execution)
            self.session.commit()
            logger.warning(
                "任务项补偿跳过，任务已有其他执行实例: task_id={} execution_id={} current_execution_id={}",
                task_id,
                execution_id,
                task.current_execution_id,
            )
            return TaskItemCompensationResult(error_summary=execution.error)

        started_at = datetime.now()
        execution.status = TaskExecutionRecordStatus.RUNNING.value
        execution.started_at = started_at
        execution.last_heartbeat_at = started_at
        execution.updated_at = started_at
        task.current_execution_id = execution_id
        task.updated_at = started_at
        self.session.add(execution)
        self.session.add(task)
        self.session.commit()
        logger.info("任务项补偿开始: task_id={} execution_id={}", task_id, execution_id)

        try:
            result = self._run_compensation(task_id)
            self._mark_execution_finished(execution_id, result)
            logger.info(
                "任务项补偿完成: task_id={} execution_id={} total={} success={} failed={} skipped={} error_summary={}",
                task_id,
                execution_id,
                result.total_count,
                result.success_count,
                result.failed_count,
                result.skipped_count,
                result.error_summary,
            )
            return result
        except Exception as exc:
            self.session.rollback()
            self._mark_execution_failed(execution_id, str(exc))
            logger.exception("任务项补偿异常: task_id={} execution_id={} error={}", task_id, execution_id, exc)
            raise

    def _run_compensation(self, task_id: int) -> TaskItemCompensationResult:
        """逐个补偿下载或识别失败的任务项。"""

        task_items = self._list_compensable_task_items(task_id)
        runner = TaskExecutionRunner(self.session, task_id, now=datetime.now())
        success_count = 0
        failed_count = 0
        skipped_count = 0
        errors: list[str] = []

        logger.info("任务项补偿待处理列表: task_id={} count={}", task_id, len(task_items))
        for task_item in task_items:
            try:
                result = self._execute_one(runner, task_item)
                if result == "success":
                    success_count += 1
                elif result == "skipped":
                    skipped_count += 1
                else:
                    failed_count += 1
                    errors.append(f"{task_item.id}: {result}")
            except Exception as exc:  # noqa: BLE001
                self.session.rollback()
                failed_count += 1
                errors.append(f"{task_item.id}: {exc}")
                logger.exception(
                    "任务项补偿单项异常: task_id={} task_item_id={} error={}",
                    task_id,
                    task_item.id,
                    exc,
                )

        error_summary = "\n".join(errors[:20]) or None
        self._refresh_task_state_after_compensation(task_id)
        return TaskItemCompensationResult(
            total_count=len(task_items),
            success_count=success_count,
            failed_count=failed_count,
            skipped_count=skipped_count,
            error_summary=error_summary,
        )

    def _execute_one(self, runner: TaskExecutionRunner, task_item: TaskItem) -> str:
        """补偿单个任务项。"""

        if self._should_skip_task_item(task_item):
            logger.info("任务项补偿跳过不可处理项: task_id={} task_item_id={}", task_item.task_id, task_item.id)
            return "skipped"

        logger.info(
            "任务项补偿开始处理: task_id={} task_item_id={} status={} down_state={} "
            "down_error={} llm_state={} llm_error={} compensation_count={}/{}",
            task_item.task_id,
            task_item.id,
            task_item.status,
            task_item.down_state,
            task_item.down_error,
            task_item.llm_state,
            task_item.llm_error,
            task_item.compensation_count,
            TASK_ITEM_COMPENSATION_MAX_ATTEMPTS,
        )
        if task_item.compensation_count >= TASK_ITEM_COMPENSATION_MAX_ATTEMPTS:
            logger.warning(
                "任务项补偿跳过，已达到最大补偿次数: task_id={} task_item_id={} compensation_count={} max_attempts={}",
                task_item.task_id,
                task_item.id,
                task_item.compensation_count,
                TASK_ITEM_COMPENSATION_MAX_ATTEMPTS,
            )
            return "skipped"

        self._increment_task_item_compensation_count(task_item)

        if not task_item.down_state:
            source_record = TaskExecutionRunner._source_record_from_task_item(task_item)
            if not runner._download_task_item_file(task_item, source_record):
                error = task_item.down_error or "下载补偿失败"
                logger.warning(
                    "任务项补偿下载失败: task_id={} task_item_id={} error={}",
                    task_item.task_id,
                    task_item.id,
                    error,
                )
                self._log_if_reached_max_attempts(task_item, error)
                return error
            self.session.refresh(task_item)

        if task_item.llm_state == TaskItemLlmState.SUCCESS.value:
            logger.info("任务项补偿下载后已是识别成功，跳过识别: task_id={} task_item_id={}", task_item.task_id, task_item.id)
            return "success"

        self._reset_task_item_model_results(task_item)
        if runner._advance_task_item_recognition(task_item):
            logger.info("任务项补偿识别成功: task_id={} task_item_id={}", task_item.task_id, task_item.id)
            return "success"

        error = task_item.llm_error or "识别补偿失败"
        logger.warning(
            "任务项补偿识别失败: task_id={} task_item_id={} error={}",
            task_item.task_id,
            task_item.id,
            error,
        )
        self._log_if_reached_max_attempts(task_item, error)
        return error

    def _refresh_task_state_after_compensation(self, task_id: int) -> None:
        """根据补偿后的任务项状态刷新任务聚合状态。"""

        task = self.session.get(Task, task_id)
        if task is None:
            return

        reviewable_count = self._count_reviewable_task_items(task_id)
        failure_summary = self._build_failure_summary(task_id)
        now = datetime.now()
        if reviewable_count > 0:
            task.execution_status = TaskExecutionStatus.VERIFY.value
            task.finished_at = None
            task.stage_started_at = None
            task.last_progress_at = None
            task.last_error = failure_summary
            task.updated_at = now
            self.session.add(task)
            self.session.commit()
            refresh_task_finish_state(self.session, task_id, now=now)
            logger.info(
                "任务项补偿后任务进入核查: task_id={} reviewable_count={} failure_summary={}",
                task_id,
                reviewable_count,
                failure_summary,
            )
            return

        task.execution_status = TaskExecutionStatus.FAIL.value
        task.finished_at = now
        task.stage_started_at = None
        task.last_progress_at = None
        task.last_error = failure_summary or "补偿后仍没有可复核的任务项"
        task.updated_at = now
        self.session.add(task)
        self.session.commit()
        logger.warning(
            "任务项补偿后任务仍失败: task_id={} failure_summary={}",
            task_id,
            task.last_error,
        )

    def _mark_execution_finished(self, execution_id: int, result: TaskItemCompensationResult) -> None:
        """标记补偿执行记录结束，并释放任务当前执行指针。"""

        finished_at = datetime.now()
        execution = self.session.get(TaskExecution, execution_id)
        if execution is None:
            return

        execution.status = (
            TaskExecutionRecordStatus.FAILED.value
            if result.failed_count > 0 and result.success_count == 0
            else TaskExecutionRecordStatus.SUCCESS.value
        )
        execution.finished_at = finished_at
        execution.last_heartbeat_at = finished_at
        execution.error = result.error_summary
        execution.updated_at = finished_at
        self.session.add(execution)

        task = self.session.get(Task, execution.task_id)
        if task is not None:
            task.current_execution_id = None
            task.updated_at = finished_at
            self.session.add(task)

        self.session.commit()

    def _mark_execution_failed(self, execution_id: int, error: str) -> None:
        """标记补偿执行记录失败，并释放任务当前执行指针。"""

        failed_at = datetime.now()
        execution = self.session.get(TaskExecution, execution_id)
        if execution is None:
            return

        execution.status = TaskExecutionRecordStatus.FAILED.value
        execution.error = error
        execution.finished_at = failed_at
        execution.last_heartbeat_at = failed_at
        execution.updated_at = failed_at
        self.session.add(execution)

        task = self.session.get(Task, execution.task_id)
        if task is not None:
            task.current_execution_id = None
            task.execution_status = TaskExecutionStatus.FAIL.value
            task.last_error = error
            task.updated_at = failed_at
            self.session.add(task)

        self.session.commit()
        logger.error("任务项补偿执行失败状态已回写: execution_id={} error={}", execution_id, error)

    def _list_task_ids_needing_compensation(self, threshold: datetime) -> list[int]:
        """列出存在失败任务项且不处于执行中的任务 ID。"""

        rows = self.session.exec(
            select(TaskItem.task_id)
            .where(self._compensable_condition())
            .where(TaskItem.updated_at < threshold)
            .order_by(TaskItem.updated_at.asc())
            .limit(TASK_ITEM_COMPENSATION_SCAN_LIMIT * 5)
        ).all()
        task_ids: list[int] = []
        for task_id in rows:
            if task_id in task_ids:
                continue
            if self._get_active_execution(task_id) is None:
                task_ids.append(task_id)
            if len(task_ids) >= TASK_ITEM_COMPENSATION_SCAN_LIMIT:
                break
        return task_ids

    def _list_compensable_task_items(self, task_id: int) -> list[TaskItem]:
        """列出单个任务下可补偿的失败任务项。"""

        return list(
            self.session.exec(
                select(TaskItem)
                .where(TaskItem.task_id == task_id)
                .where(self._compensable_condition())
                .order_by(TaskItem.updated_at.asc(), TaskItem.id.asc())
            ).all()
        )

    def _list_limited_failed_task_items(self, task_id: int) -> list[TaskItem]:
        """列出达到补偿上限且仍失败的任务项。"""

        return list(
            self.session.exec(
                select(TaskItem)
                .where(TaskItem.task_id == task_id)
                .where(TaskItem.compensation_count >= TASK_ITEM_COMPENSATION_MAX_ATTEMPTS)
                .where(
                    or_(
                        (TaskItem.down_state == False) & (TaskItem.down_error != None),  # noqa: E711,E712
                        (TaskItem.llm_state == TaskItemLlmState.FAIL.value),
                    )
                )
                .where(TaskItem.remote_state != TaskItemRemoteState.SUCCESS.value)
                .where(TaskItem.confirm_state != TaskItemConfirmState.SKIPPED.value)
                .where(TaskItem.status.notin_({TaskItemStatus.SKIPPED.value, TaskItemStatus.FINISHED.value}))
                .order_by(TaskItem.id.asc())
            ).all()
        )

    def _has_compensable_task_items(self, task_id: int) -> bool:
        """判断任务是否还有可补偿失败项。"""

        return self.session.exec(
            select(TaskItem.id)
            .where(TaskItem.task_id == task_id)
            .where(self._compensable_condition())
        ).first() is not None

    def _get_active_execution(self, task_id: int) -> TaskExecution | None:
        """返回任务当前排队或运行中的执行记录。"""

        return self.session.exec(
            select(TaskExecution)
            .where(TaskExecution.task_id == task_id)
            .where(TaskExecution.status.in_(ACTIVE_EXECUTION_STATUSES))
            .order_by(TaskExecution.created_at.desc())
        ).first()

    @staticmethod
    def _compensable_condition() -> object:
        """构造可补偿失败项查询条件。"""

        return (
            or_(
                (TaskItem.down_state == False) & (TaskItem.down_error != None),  # noqa: E711,E712
                (TaskItem.down_state == True)  # noqa: E712
                & (TaskItem.llm_state == TaskItemLlmState.FAIL.value),
            )
            & (TaskItem.compensation_count < TASK_ITEM_COMPENSATION_MAX_ATTEMPTS)
            & (TaskItem.remote_state != TaskItemRemoteState.SUCCESS.value)
            & (TaskItem.confirm_state != TaskItemConfirmState.SKIPPED.value)
            & (TaskItem.status.notin_({TaskItemStatus.SKIPPED.value, TaskItemStatus.FINISHED.value}))
        )

    @staticmethod
    def _should_skip_task_item(task_item: TaskItem) -> bool:
        """判断任务项是否不应自动补偿。"""

        return (
            task_item.remote_state == TaskItemRemoteState.SUCCESS.value
            or task_item.confirm_state == TaskItemConfirmState.SKIPPED.value
            or task_item.status in {TaskItemStatus.SKIPPED.value, TaskItemStatus.FINISHED.value}
            or task_item.llm_state == TaskItemLlmState.RUNNING.value
            or task_item.compensation_count >= TASK_ITEM_COMPENSATION_MAX_ATTEMPTS
        )

    def _increment_task_item_compensation_count(self, task_item: TaskItem) -> None:
        """递增单个任务项补偿次数。"""

        task_item.compensation_count += 1
        task_item.updated_at = datetime.now()
        self.session.add(task_item)
        self.session.commit()
        self.session.refresh(task_item)
        logger.info(
            "任务项补偿次数已递增: task_id={} task_item_id={} compensation_count={}/{}",
            task_item.task_id,
            task_item.id,
            task_item.compensation_count,
            TASK_ITEM_COMPENSATION_MAX_ATTEMPTS,
        )

    @staticmethod
    def _log_if_reached_max_attempts(task_item: TaskItem, error: str) -> None:
        """任务项达到最大补偿次数时记录明确日志。"""

        if task_item.compensation_count < TASK_ITEM_COMPENSATION_MAX_ATTEMPTS:
            return
        logger.error(
            "任务项已达到最大补偿次数，后续不再自动补偿: task_id={} task_item_id={} compensation_count={} "
            "max_attempts={} error={}",
            task_item.task_id,
            task_item.id,
            task_item.compensation_count,
            TASK_ITEM_COMPENSATION_MAX_ATTEMPTS,
            error,
        )

    def _reset_task_item_model_results(self, task_item: TaskItem) -> None:
        """清理失败项旧模型结果并恢复到待识别状态。"""

        rows = self.session.exec(
            select(TaskItemData).where(TaskItemData.task_item_id == task_item.id).order_by(TaskItemData.id.asc())
        ).all()
        for row in rows:
            if row.status == TaskItemDataStatus.ADD.value:
                self.session.delete(row)
                continue
            row.llm_name = None
            row.llm_det_name = None
            row.status = TaskItemDataStatus.DEFAULT.value
            self.session.add(row)

        now = datetime.now()
        task_item.status = TaskItemStatus.DOWNLOADED.value
        task_item.llm_state = TaskItemLlmState.PENDING.value
        task_item.llm_error = None
        task_item.llm_at = None
        task_item.confirm_state = TaskItemConfirmState.PENDING.value
        task_item.confirmed_at = None
        task_item.updated_at = now
        self.session.add(task_item)
        self.session.commit()
        self.session.refresh(task_item)

    def _count_reviewable_task_items(self, task_id: int) -> int:
        """统计已经识别成功的任务项数量。"""

        return len(
            self.session.exec(
                select(TaskItem.id)
                .where(TaskItem.task_id == task_id)
                .where(TaskItem.llm_state == TaskItemLlmState.SUCCESS.value)
            ).all()
        )

    def _build_failure_summary(self, task_id: int) -> str | None:
        """构造任务当前失败摘要。"""

        download_failed_count = len(
            self.session.exec(
                select(TaskItem.id)
                .where(TaskItem.task_id == task_id)
                .where(TaskItem.down_state == False)  # noqa: E712
                .where(TaskItem.down_error != None)  # noqa: E711
            ).all()
        )
        llm_failed_count = len(
            self.session.exec(
                select(TaskItem.id)
                .where(TaskItem.task_id == task_id)
                .where(TaskItem.llm_state == TaskItemLlmState.FAIL.value)
            ).all()
        )
        max_attempts_count = len(
            self.session.exec(
                select(TaskItem.id)
                .where(TaskItem.task_id == task_id)
                .where(TaskItem.compensation_count >= TASK_ITEM_COMPENSATION_MAX_ATTEMPTS)
                .where(
                    or_(
                        (TaskItem.down_state == False) & (TaskItem.down_error != None),  # noqa: E711,E712
                        (TaskItem.llm_state == TaskItemLlmState.FAIL.value),
                    )
                )
            ).all()
        )
        parts: list[str] = []
        if download_failed_count:
            parts.append(f"下载失败任务项数量={download_failed_count}")
        if llm_failed_count:
            parts.append(f"识别失败任务项数量={llm_failed_count}")
        if max_attempts_count:
            parts.append(f"达到补偿上限任务项数量={max_attempts_count}")
        return "；".join(parts) if parts else None

    @staticmethod
    def _build_celery_task_id(execution_id: int) -> str:
        """构造补偿任务的 Celery task id。"""

        return f"task-item-compensation-{execution_id}"

    @staticmethod
    def _enqueue_compensation(task_id: int, execution_id: int, celery_task_id: str) -> None:
        """投递补偿 Celery 任务。"""

        from aiSelfTest.worker import execute_task_item_compensation

        logger.info(
            "调用 Celery apply_async 投递任务项补偿: task_id={} execution_id={} celery_task_id={}",
            task_id,
            execution_id,
            celery_task_id,
        )
        execute_task_item_compensation.apply_async(args=[task_id, execution_id], task_id=celery_task_id)
