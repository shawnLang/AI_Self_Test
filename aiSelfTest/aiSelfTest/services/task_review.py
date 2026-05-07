"""TaskItem 复核状态判定服务。"""

from __future__ import annotations

from datetime import datetime

from aiSelfTest.models.task import (
    Task,
    TaskExecutionStatus,
    TaskItem,
    TaskItemConfirmState,
    TaskItemData,
    TaskItemDataStatus,
    TaskItemRemoteState,
    TaskItemStatus,
)
from sqlmodel import Session, select


def is_task_item_review_matched(data_rows: list[TaskItemData]) -> bool:
    """判断 TaskItemData 复核结果是否全部一致。"""

    return bool(data_rows) and all(row.status == TaskItemDataStatus.DEFAULT.value for row in data_rows)


def apply_task_item_review_state(task_item: TaskItem, data_rows: list[TaskItemData], now: datetime) -> None:
    """根据复核明细状态刷新 TaskItem 的人工复核状态。"""

    if task_item.status == TaskItemStatus.FINISHED.value:
        return

    task_item.updated_at = now
    task_item.remote_state = task_item.remote_state or TaskItemRemoteState.PENDING.value
    if is_task_item_review_matched(data_rows):
        task_item.status = TaskItemStatus.SKIPPED.value
        task_item.confirm_state = TaskItemConfirmState.SKIPPED.value
        return

    task_item.status = TaskItemStatus.VERIFY_PENDING.value
    task_item.confirm_state = TaskItemConfirmState.PENDING.value


def refresh_task_finish_state(session: Session, task_id: int, now: datetime | None = None) -> None:
    """所有 TaskItem 都完成或跳过后，把任务推进到结束态。"""

    task = session.get(Task, task_id)
    if task is None or task.execution_status != TaskExecutionStatus.VERIFY.value:
        return

    rows = session.exec(select(TaskItem).where(TaskItem.task_id == task_id)).all()
    if not rows:
        return

    finished_statuses = {
        TaskItemStatus.FINISHED.value,
        TaskItemStatus.SKIPPED.value,
    }
    if not all(row.status in finished_statuses for row in rows):
        return

    finished_at = now or datetime.now()
    task.execution_status = TaskExecutionStatus.FINISH.value
    task.finished_at = finished_at
    task.stage_started_at = None
    task.last_progress_at = None
    task.updated_at = finished_at
    task.processed_count = len(rows)
    task.total_count = len(rows)
    session.add(task)
    session.commit()
