"""任务项批量重新识别服务。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Sequence

from loguru import logger
from sqlmodel import Session, select

from aiSelfTest.exceptions import AppException, ErrorCode
from aiSelfTest.models.task import (
    Task,
    TaskItem,
    TaskItemConfirmState,
    TaskItemData,
    TaskItemDataStatus,
    TaskItemLlmState,
    TaskItemRecognitionBatch,
    TaskItemRecognitionBatchStatus,
    TaskItemRemoteState,
    TaskItemStatus,
)
from aiSelfTest.services.task_execution import TaskExecutionRunner


class TaskItemReRecognitionService:
    """批量重新识别 TaskItem。"""

    def __init__(self, session: Session) -> None:
        """初始化服务依赖。"""

        self.session = session

    def create_batch(
        self,
        *,
        scope: str,
        task_id: int | None = None,
        task_item_ids: Sequence[int] | None = None,
    ) -> TaskItemRecognitionBatch:
        """创建批量重新识别记录。"""

        resolved_item_ids = self._resolve_task_item_ids(scope, task_id, task_item_ids or [])
        if not resolved_item_ids:
            raise AppException(
                code=ErrorCode.PARAM_INVALID,
                message="没有可重新识别的任务项",
                status_code=400,
            )

        first_item = self.session.get(TaskItem, resolved_item_ids[0])
        if first_item is None:
            raise AppException(code=ErrorCode.NOT_FOUND, message="任务项不存在", status_code=404)
        resolved_task_id = task_id or first_item.task_id
        task = self.session.get(Task, resolved_task_id)
        if task is None:
            raise AppException(code=ErrorCode.NOT_FOUND, message="任务不存在", status_code=404)

        batch = TaskItemRecognitionBatch(
            task_id=resolved_task_id,
            scope=scope,
            task_item_ids=",".join(str(item_id) for item_id in resolved_item_ids),
            status=TaskItemRecognitionBatchStatus.QUEUED.value,
            total_count=len(resolved_item_ids),
            success_count=0,
            failed_count=0,
            skipped_count=0,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        self.session.add(batch)
        self.session.commit()
        self.session.refresh(batch)
        logger.info(
            "批量重新识别记录已创建 batch_id={} task_id={} scope={} total_count={}",
            batch.id,
            batch.task_id,
            batch.scope,
            batch.total_count,
        )
        return batch

    def enqueue_batch(self, batch: TaskItemRecognitionBatch) -> TaskItemRecognitionBatch:
        """投递批量重新识别 Celery 任务。"""

        from aiSelfTest.worker import execute_task_item_re_recognition_batch

        batch.celery_task_id = f"task-item-re-recognition-{batch.id}"
        batch.updated_at = datetime.now()
        self.session.add(batch)
        self.session.commit()
        execute_task_item_re_recognition_batch.delay(batch.id or 0)
        self.session.refresh(batch)
        return batch

    def execute_batch(self, batch_id: int) -> TaskItemRecognitionBatch:
        """执行批量重新识别记录。"""

        batch = self.session.get(TaskItemRecognitionBatch, batch_id)
        if batch is None:
            logger.warning("批量重新识别记录不存在 batch_id={}", batch_id)
            raise AppException(code=ErrorCode.NOT_FOUND, message="批量重新识别记录不存在", status_code=404)
        if batch.status != TaskItemRecognitionBatchStatus.QUEUED.value:
            logger.info("批量重新识别状态不是 queued，跳过 batch_id={} status={}", batch.id, batch.status)
            return batch

        now = datetime.now()
        batch.status = TaskItemRecognitionBatchStatus.RUNNING.value
        batch.started_at = now
        batch.updated_at = now
        self.session.add(batch)
        self.session.commit()
        self.session.refresh(batch)

        task_item_ids = self._parse_task_item_ids(batch.task_item_ids)
        errors: list[str] = []
        for task_item_id in task_item_ids:
            batch.current_task_item_id = task_item_id
            batch.updated_at = datetime.now()
            self.session.add(batch)
            self.session.commit()

            result = self._execute_one(batch, task_item_id)
            if result == "success":
                batch.success_count += 1
            elif result == "skipped":
                batch.skipped_count += 1
            else:
                batch.failed_count += 1
                errors.append(f"{task_item_id}: {result}")
            batch.updated_at = datetime.now()
            self.session.add(batch)
            self.session.commit()

        finished_at = datetime.now()
        batch.current_task_item_id = None
        batch.finished_at = finished_at
        batch.updated_at = finished_at
        batch.error_summary = "\n".join(errors[:20]) or None
        if batch.failed_count > 0 and batch.success_count > 0:
            batch.status = TaskItemRecognitionBatchStatus.PARTIAL_FAILED.value
        elif batch.failed_count > 0 and batch.success_count == 0 and batch.skipped_count == 0:
            batch.status = TaskItemRecognitionBatchStatus.FAILED.value
        else:
            batch.status = TaskItemRecognitionBatchStatus.SUCCESS.value
        self.session.add(batch)
        self.session.commit()
        self.session.refresh(batch)
        logger.info(
            "批量重新识别完成 batch_id={} status={} success={} failed={} skipped={}",
            batch.id,
            batch.status,
            batch.success_count,
            batch.failed_count,
            batch.skipped_count,
        )
        return batch

    def _execute_one(self, batch: TaskItemRecognitionBatch, task_item_id: int) -> str:
        """执行单个 TaskItem 重新识别。"""

        task_item = self.session.get(TaskItem, task_item_id)
        if task_item is None or task_item.task_id != batch.task_id:
            return "任务项不存在或不属于当前任务"
        if self._should_skip_task_item(task_item):
            logger.info("批量重新识别跳过任务项 task_item_id={}", task_item.id)
            return "skipped"

        try:
            self._ensure_task_item_file_ready(task_item)
            self._reset_task_item_model_results(task_item)
            runner = TaskExecutionRunner(self.session, batch.task_id, now=datetime.now())
            if not runner._advance_task_item_recognition(task_item):
                return task_item.llm_error or "重新识别失败"
            return "success"
        except Exception as exc:  # noqa: BLE001
            self.session.rollback()
            self._mark_task_item_failed(task_item_id, str(exc))
            logger.warning("批量重新识别单项失败 task_item_id={} error={}", task_item_id, exc)
            return str(exc)

    def _resolve_task_item_ids(
        self,
        scope: str,
        task_id: int | None,
        task_item_ids: Sequence[int],
    ) -> list[int]:
        """根据请求范围解析任务项 ID。"""

        if scope == "selected":
            ids = list(dict.fromkeys(task_item_ids))
            if not ids:
                raise AppException(
                    code=ErrorCode.PARAM_INVALID,
                    message="请选择需要重新识别的任务项",
                    status_code=400,
                )
            rows = self.session.exec(select(TaskItem).where(TaskItem.id.in_(ids))).all()
            if len(rows) != len(ids):
                raise AppException(code=ErrorCode.NOT_FOUND, message="部分任务项不存在", status_code=404)
            task_ids = {row.task_id for row in rows}
            if len(task_ids) != 1:
                raise AppException(
                    code=ErrorCode.PARAM_INVALID,
                    message="批量重新识别只能选择同一任务下的任务项",
                    status_code=400,
                )
            return ids

        if scope == "failed":
            if task_id is None:
                raise AppException(code=ErrorCode.PARAM_INVALID, message="缺少任务ID", status_code=400)
            task = self.session.get(Task, task_id)
            if task is None:
                raise AppException(code=ErrorCode.NOT_FOUND, message="任务不存在", status_code=404)
            return list(
                self.session.exec(
                    select(TaskItem.id)
                    .where(TaskItem.task_id == task_id)
                    .where(TaskItem.llm_state == TaskItemLlmState.FAIL.value)
                    .order_by(TaskItem.id.asc())
                ).all()
            )

        raise AppException(code=ErrorCode.PARAM_INVALID, message="不支持的重新识别范围", status_code=400)

    @staticmethod
    def _parse_task_item_ids(raw: str) -> list[int]:
        """解析逗号分隔的任务项 ID。"""

        ids: list[int] = []
        for part in raw.split(","):
            text = part.strip()
            if not text:
                continue
            ids.append(int(text))
        return ids

    @staticmethod
    def _should_skip_task_item(task_item: TaskItem) -> bool:
        """判断任务项是否应跳过重新识别。"""

        return (
            task_item.remote_state == TaskItemRemoteState.SUCCESS.value
            or task_item.llm_state == TaskItemLlmState.RUNNING.value
            or task_item.confirm_state == TaskItemConfirmState.SKIPPED.value
            or task_item.status == TaskItemStatus.SKIPPED.value
        )

    @staticmethod
    def _ensure_task_item_file_ready(task_item: TaskItem) -> None:
        """确认任务项本地文件可用于识别。"""

        file_path = Path(task_item.file_path) if task_item.file_path else None
        if not task_item.down_state or file_path is None or not file_path.is_file():
            raise AppException(
                code=ErrorCode.TASK_FAILED,
                message=f"任务项文件未下载或不存在: task_item_id={task_item.id}",
                status_code=502,
            )
        if task_item.file_bmp == 2 and not list(file_path.parent.glob("*.videojson")):
            raise AppException(
                code=ErrorCode.TASK_FAILED,
                message=f"视频任务项缺少 videojson: task_item_id={task_item.id}",
                status_code=502,
            )

    def _reset_task_item_model_results(self, task_item: TaskItem) -> None:
        """清理旧模型结果并恢复原始行到待匹配状态。"""

        rows = self.session.exec(
            select(TaskItemData).where(TaskItemData.task_item_id == task_item.id).order_by(TaskItemData.id.asc())
        ).all()
        for row in rows:
            if row.status == TaskItemDataStatus.ADD.value:
                self.session.delete(row)
                continue
            row.llm_name = None
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

    def _mark_task_item_failed(self, task_item_id: int, error: str) -> None:
        """标记任务项重新识别失败。"""

        task_item = self.session.get(TaskItem, task_item_id)
        if task_item is None:
            return
        now = datetime.now()
        task_item.llm_state = TaskItemLlmState.FAIL.value
        task_item.llm_error = error
        task_item.llm_at = now
        task_item.status = TaskItemStatus.FAILED.value
        task_item.updated_at = now
        self.session.add(task_item)
        self.session.commit()
