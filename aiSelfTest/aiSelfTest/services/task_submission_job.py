"""任务级提交远端与训练保存后台任务服务。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from fastapi import status
from loguru import logger
from sqlmodel import Session, select

from aiSelfTest.exceptions import AppException, ErrorCode
from aiSelfTest.models.task import (
    Task,
    TaskItem,
    TaskItemConfirmState,
    TaskItemRemoteState,
    TaskSubmission,
    TaskSubmissionStatus,
)
from aiSelfTest.services.task_review import refresh_task_finish_state
from aiSelfTest.services.task_submission import TaskSubmissionService


ACTIVE_SUBMISSION_STATUSES = {
    TaskSubmissionStatus.QUEUED.value,
    TaskSubmissionStatus.RUNNING.value,
}
TERMINAL_SUBMISSION_STATUSES = {
    TaskSubmissionStatus.SUCCESS.value,
    TaskSubmissionStatus.PARTIAL_FAILED.value,
    TaskSubmissionStatus.FAILED.value,
}
MAX_ERROR_SUMMARY_LENGTH = 2000


@dataclass(frozen=True)
class TaskSubmissionDispatchResult:
    """任务级提交保存派发结果。"""

    submission: TaskSubmission
    enqueued: bool = True


class TaskSubmissionJobService:
    """任务级提交远端与训练保存后台任务服务。"""

    def __init__(self, session: Session) -> None:
        """保存数据库会话。"""

        self.session = session

    def submit(self, task_id: int) -> TaskSubmissionDispatchResult:
        """创建任务级提交记录并投递 Celery。"""

        self._get_task_or_raise(task_id)
        active_submission = self.get_active_submission(task_id)
        if active_submission is not None:
            raise AppException(
                code=ErrorCode.RESOURCE_BUSY,
                message="任务正在提交保存中",
                status_code=status.HTTP_409_CONFLICT,
                data=self._build_exception_data(active_submission),
            )

        now = datetime.now()
        total_count = self._count_submittable_items(task_id)
        submission = TaskSubmission(
            task_id=task_id,
            status=TaskSubmissionStatus.QUEUED.value,
            total_count=total_count,
            success_count=0,
            failed_count=0,
            skipped_count=0,
            created_at=now,
            updated_at=now,
        )
        self.session.add(submission)
        self.session.commit()
        self.session.refresh(submission)

        celery_task_id = self._build_celery_task_id(submission.id or 0)
        try:
            self._enqueue_submission(submission.id or 0, celery_task_id)
        except Exception as exc:
            logger.exception("任务提交保存投递 Celery 失败 task_id={} submission_id={}", task_id, submission.id)
            submission.status = TaskSubmissionStatus.FAILED.value
            submission.error_summary = "任务提交保存入队失败"
            submission.finished_at = datetime.now()
            submission.updated_at = submission.finished_at
            self.session.add(submission)
            self.session.commit()
            raise AppException(
                code=ErrorCode.TASK_FAILED,
                message="任务提交保存入队失败，请稍后重试",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            ) from exc

        submission.celery_task_id = celery_task_id
        submission.updated_at = datetime.now()
        self.session.add(submission)
        self.session.commit()
        self.session.refresh(submission)
        logger.info(
            "任务提交保存已提交后台执行 task_id={} submission_id={} total_count={}",
            task_id,
            submission.id,
            total_count,
        )
        return TaskSubmissionDispatchResult(submission=submission)

    def execute(self, submission_id: int) -> None:
        """执行任务级提交远端与训练保存。"""

        submission = self.session.get(TaskSubmission, submission_id)
        if submission is None:
            logger.warning("任务提交保存记录不存在 submission_id={}", submission_id)
            return
        if submission.status in TERMINAL_SUBMISSION_STATUSES:
            logger.info("任务提交保存记录已结束，跳过 submission_id={} status={}", submission_id, submission.status)
            return

        now = datetime.now()
        submission.status = TaskSubmissionStatus.RUNNING.value
        submission.started_at = submission.started_at or now
        submission.updated_at = now
        self.session.add(submission)
        self.session.commit()

        task_items = self._get_task_items_for_submission(submission.task_id)
        submission.total_count = len(task_items)
        submission.updated_at = datetime.now()
        self.session.add(submission)
        self.session.commit()

        error_messages: list[str] = []
        for task_item in task_items:
            task_item_id = task_item.id or 0
            self._refresh_submission_progress(submission, task_item_id)
            if not self._can_submit_task_item(task_item):
                submission.skipped_count += 1
                self._save_submission_progress(submission)
                continue

            try:
                TaskSubmissionService(self.session).submit_task_item_outputs(task_item)
                submission.success_count += 1
            except Exception as exc:  # noqa: BLE001
                self.session.rollback()
                submission = self.session.get(TaskSubmission, submission_id)
                if submission is None:
                    logger.warning("任务提交保存记录执行中被删除 submission_id={}", submission_id)
                    return
                submission.failed_count += 1
                error_messages.append(f"TaskItem {task_item_id}: {exc}")
                logger.warning(
                    "任务项提交保存失败 task_id={} submission_id={} task_item_id={} error={}",
                    submission.task_id,
                    submission_id,
                    task_item_id,
                    exc,
                )
            self._save_submission_progress(submission, error_messages)

        self._finish_submission(submission, error_messages)
        refresh_task_finish_state(self.session, submission.task_id)

    def get_active_submission(self, task_id: int) -> TaskSubmission | None:
        """返回任务当前排队或运行中的提交保存记录。"""

        return self.session.exec(
            select(TaskSubmission)
            .where(TaskSubmission.task_id == task_id)
            .where(TaskSubmission.status.in_(ACTIVE_SUBMISSION_STATUSES))
            .order_by(TaskSubmission.created_at.desc())
        ).first()

    def _get_task_or_raise(self, task_id: int) -> Task:
        """查询任务，不存在时抛出业务异常。"""

        task = self.session.get(Task, task_id)
        if task is None:
            raise AppException(code=ErrorCode.NOT_FOUND, message="任务不存在", status_code=404)
        return task

    def _count_submittable_items(self, task_id: int) -> int:
        """统计当前任务下可提交保存的任务项数量。"""

        return len(self._get_task_items_for_submission(task_id))

    def _get_task_items_for_submission(self, task_id: int) -> list[TaskItem]:
        """查询当前任务下可提交或可重试提交的任务项。"""

        return self.session.exec(
            select(TaskItem)
            .where(TaskItem.task_id == task_id)
            .where(TaskItem.confirm_state == TaskItemConfirmState.CONFIRMED.value)
            .where(TaskItem.remote_state.in_({
                TaskItemRemoteState.PENDING.value,
                TaskItemRemoteState.FAIL.value,
            }))
            .order_by(TaskItem.id.asc())
        ).all()

    @staticmethod
    def _can_submit_task_item(task_item: TaskItem) -> bool:
        """再次确认任务项仍处于可提交状态。"""

        return (
            task_item.confirm_state == TaskItemConfirmState.CONFIRMED.value
            and task_item.remote_state in {
                TaskItemRemoteState.PENDING.value,
                TaskItemRemoteState.FAIL.value,
            }
        )

    def _refresh_submission_progress(self, submission: TaskSubmission, task_item_id: int | None) -> None:
        """更新当前处理项。"""

        submission.current_task_item_id = task_item_id
        submission.updated_at = datetime.now()
        self.session.add(submission)
        self.session.commit()

    def _save_submission_progress(
        self,
        submission: TaskSubmission,
        error_messages: list[str] | None = None,
    ) -> None:
        """保存任务级提交进度。"""

        submission.error_summary = self._join_error_summary(error_messages or [])
        submission.updated_at = datetime.now()
        self.session.add(submission)
        self.session.commit()

    def _finish_submission(self, submission: TaskSubmission, error_messages: list[str]) -> None:
        """根据统计结果结束提交保存记录。"""

        finished_at = datetime.now()
        if submission.failed_count == 0:
            submission.status = TaskSubmissionStatus.SUCCESS.value
        elif submission.success_count > 0 or submission.skipped_count > 0:
            submission.status = TaskSubmissionStatus.PARTIAL_FAILED.value
        else:
            submission.status = TaskSubmissionStatus.FAILED.value
        submission.current_task_item_id = None
        submission.error_summary = self._join_error_summary(error_messages)
        submission.finished_at = finished_at
        submission.updated_at = finished_at
        self.session.add(submission)
        self.session.commit()
        logger.info(
            "任务提交保存完成 task_id={} submission_id={} status={} success={} failed={} skipped={}",
            submission.task_id,
            submission.id,
            submission.status,
            submission.success_count,
            submission.failed_count,
            submission.skipped_count,
        )

    @staticmethod
    def _join_error_summary(error_messages: list[str]) -> str | None:
        """拼接并截断错误摘要。"""

        if not error_messages:
            return None
        return "\n".join(error_messages)[:MAX_ERROR_SUMMARY_LENGTH]

    @staticmethod
    def _build_exception_data(submission: TaskSubmission) -> dict[str, object]:
        """构造并发冲突时返回的当前提交记录。"""

        return {
            "submission_id": submission.id or 0,
            "task_id": submission.task_id,
            "status": submission.status,
            "total_count": submission.total_count,
            "success_count": submission.success_count,
            "failed_count": submission.failed_count,
            "skipped_count": submission.skipped_count,
            "current_task_item_id": submission.current_task_item_id,
            "error_summary": submission.error_summary,
            "celery_task_id": submission.celery_task_id,
        }

    @staticmethod
    def _build_celery_task_id(submission_id: int) -> str:
        """构造确定性 Celery task id。"""

        return f"task-submission-{submission_id}"

    @staticmethod
    def _enqueue_submission(submission_id: int, celery_task_id: str) -> None:
        """投递 Celery 任务。"""

        from aiSelfTest.worker import execute_task_submission

        execute_task_submission.apply_async(args=[submission_id], task_id=celery_task_id)
