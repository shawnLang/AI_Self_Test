"""TaskItem 提交与训练目录保存服务。"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from aiSelfTest.config import get_settings
from aiSelfTest.models.task import (
    TaskItem,
    TaskItemData,
    TaskItemRemoteState,
    TaskItemStatus,
    TaskItemTrainState,
)
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
    """推进 TaskItem 提交状态，并保存训练目录标注文件。"""

    submitted_at = now or datetime.now()
    data_rows = session.exec(
        select(TaskItemData).where(TaskItemData.task_item_id == task_item.id)
    ).all()
    annotation_path = _save_training_artifacts(task_item, data_rows)

    task_item.remote_state = TaskItemRemoteState.SUCCESS.value
    task_item.remote_error = None
    task_item.remote_at = submitted_at
    task_item.train_state = TaskItemTrainState.SAVED.value
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
