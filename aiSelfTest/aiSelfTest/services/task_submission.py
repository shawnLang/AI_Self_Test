"""TaskItem 提交与训练目录保存服务。"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from aiSelfTest.config import get_settings
from aiSelfTest.exceptions import AppException, ErrorCode
from aiSelfTest.models.task import (
    Task,
    TaskItem,
    TaskItemData,
    TaskItemDataStatus,
    TaskItemRemoteState,
    TaskItemStatus,
    TaskItemTrainState,
)
from aiSelfTest.services.client_auth import ClientApi
from loguru import logger
from sqlmodel import Session, select


@dataclass(frozen=True)
class TaskSubmissionResult:
    """TaskItem 提交结果。"""

    remote_state: str
    train_state: str
    annotation_path: str


def submit_task_item_outputs(
    session: Session,
    task_item: TaskItem,
    now: datetime | None = None,
) -> TaskSubmissionResult:
    """提交远端 AI 巡检结果，并保存训练目录标注文件。"""

    submitted_at = now or datetime.now()
    data_rows = session.exec(
        select(TaskItemData).where(TaskItemData.task_item_id == task_item.id)
    ).all()
    payload = _build_ai_polling_payload(task_item, data_rows, submitted_at)

    try:
        response = ClientApi(session, task_item_client_id(session, task_item)).update_ai_polling_result(payload)
        _ensure_remote_submit_success(response)
    except Exception as exc:
        _mark_remote_failed(session, task_item, submitted_at, str(exc))
        raise AppException(
            code=ErrorCode.TASK_FAILED,
            message=f"远端提交失败: {exc}",
            status_code=502,
        ) from exc

    try:
        annotation_path = _save_training_artifacts(task_item, data_rows)
        train_state = TaskItemTrainState.SAVED.value
    except Exception as exc:  # noqa: BLE001
        task_item.train_state = TaskItemTrainState.FAIL.value
        task_item.train_at = submitted_at
        task_item.updated_at = submitted_at
        session.add(task_item)
        session.commit()
        logger.exception("训练目录保存失败 task_item_id={}", task_item.id)
        raise AppException(
            code=ErrorCode.TASK_FAILED,
            message=f"训练目录保存失败: {exc}",
            status_code=502,
        ) from exc

    task_item.remote_state = TaskItemRemoteState.SUCCESS.value
    task_item.remote_error = None
    task_item.remote_at = submitted_at
    task_item.train_state = train_state
    task_item.train_at = submitted_at
    task_item.status = TaskItemStatus.FINISHED.value
    task_item.updated_at = submitted_at
    session.add(task_item)
    session.commit()
    session.refresh(task_item)
    logger.info(
        "任务项提交与训练保存完成 task_item_id={} annotation_path={}",
        task_item.id,
        annotation_path,
    )
    return TaskSubmissionResult(
        remote_state=task_item.remote_state or TaskItemRemoteState.SUCCESS.value,
        train_state=task_item.train_state or TaskItemTrainState.SAVED.value,
        annotation_path=annotation_path.as_posix(),
    )


def _save_training_artifacts(task_item: TaskItem, data_rows: list[TaskItemData]) -> Path:
    """保存训练目录中的媒体文件副本与标注 JSON。"""

    target_dir = (
        get_settings().data_dir
        / "training"
        / str(task_item.task_id)
        / str(task_item.id or 0)
    )
    target_dir.mkdir(parents=True, exist_ok=True)

    _copy_if_exists(task_item.file_path, target_dir)
    if task_item.file_path:
        result_path = Path(task_item.file_path).parent / "result.json"
        _copy_if_exists(result_path.as_posix(), target_dir)

    annotation_path = target_dir / "annotation.json"
    payload = {
        "taskItemId": task_item.id or 0,
        "taskId": task_item.task_id,
        "fileFid": task_item.file_fid,
        "fileName": task_item.name,
        "mediaType": "video" if task_item.file_bmp == 2 else "image",
        "recordData": [_build_annotation_row(row) for row in data_rows],
    }
    annotation_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return annotation_path


def task_item_client_id(session: Session, task_item: TaskItem) -> int:
    """返回 TaskItem 所属任务的客户端 ID。"""

    task = session.get(Task, task_item.task_id)
    if task is None:
        raise AppException(code=ErrorCode.NOT_FOUND, message="任务不存在", status_code=404)
    return task.client_id


def _build_ai_polling_payload(
    task_item: TaskItem,
    data_rows: list[TaskItemData],
    submitted_at: datetime,
) -> dict[str, object]:
    """构造更新 AI 巡检结果接口载荷。"""

    if task_item.file_id is None:
        raise AppException(code=ErrorCode.PARAM_INVALID, message="任务项缺少上游 file_id", status_code=400)
    return {
        "id": task_item.file_id,
        "recordData": [
            row_payload
            for row in data_rows
            if (row_payload := _build_ai_polling_record(row, submitted_at)) is not None
        ],
    }


def _build_ai_polling_record(row: TaskItemData, submitted_at: datetime) -> dict[str, object] | None:
    """构造单条最终识别结果记录，删除行不提交。"""

    if row.status == TaskItemDataStatus.DELETE.value:
        return None

    name = row.name if row.status == TaskItemDataStatus.DEFAULT.value else row.llm_name
    return {
        "name": name or "",
        "speciesName": "",
        "score": row.score,
        "trackIds": row.track_ids,
        "spAmount": row.sp_amount,
        "lastUpdatedTime": submitted_at.isoformat(timespec="seconds"),
        "minx": row.minx,
        "miny": row.miny,
        "maxx": row.maxx,
        "maxy": row.maxy,
    }


def _ensure_remote_submit_success(response: object) -> None:
    """校验上游提交响应。"""

    status_code = getattr(response, "status_code", None)
    if status_code != 200:
        raise AppException(
            code=ErrorCode.TASK_FAILED,
            message=f"远端提交接口失败 HTTP {status_code}: {getattr(response, 'text', '')}",
            status_code=502,
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise AppException(code=ErrorCode.TASK_FAILED, message="远端提交接口返回非 JSON", status_code=502) from exc
    if payload is not True:
        raise AppException(code=ErrorCode.TASK_FAILED, message=f"远端提交接口返回失败: {payload}", status_code=502)


def _mark_remote_failed(session: Session, task_item: TaskItem, submitted_at: datetime, error: str) -> None:
    """记录远端提交失败状态。"""

    task_item.remote_state = TaskItemRemoteState.FAIL.value
    task_item.remote_error = error[:1000]
    task_item.remote_at = submitted_at
    task_item.status = TaskItemStatus.CONFIRMED.value
    task_item.updated_at = submitted_at
    session.add(task_item)
    session.commit()


def _copy_if_exists(source_path: str | None, target_dir: Path) -> None:
    """存在本地源文件时复制到训练目录。"""

    if not source_path:
        return
    source = Path(source_path)
    if not source.exists() or not source.is_file():
        return
    shutil.copy2(source, target_dir / source.name)


def _build_annotation_row(row: TaskItemData) -> dict[str, object]:
    """构造训练标注中的单条识别结果。"""

    return {
        "id": row.id or 0,
        "name": row.name,
        "score": row.score,
        "trackIds": row.track_ids,
        "spAmount": row.sp_amount,
        "bbox": [row.minx, row.miny, row.maxx, row.maxy],
        "llmName": row.llm_name,
        "status": row.status,
    }
