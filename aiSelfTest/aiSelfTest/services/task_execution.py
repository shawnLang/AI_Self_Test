"""Task 执行主干。

本模块先提供媒体无关的 V1 执行骨架：

1. 拉取上游文件记录并落库为 TaskItem。
2. 对新增 TaskItem 执行最小下载占位、详情落库、LLM 占位识别。
3. 根据 auto_confirm 推进确认、提交与训练目录状态。

真实上游、下载器和 LLM 分支都通过协议注入，避免在测试或本地手动
执行时产生不可控外部请求。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence
from urllib.parse import urlparse

from loguru import logger
from sqlmodel import Session, select

from aiSelfTest.config import get_settings
from aiSelfTest.exceptions import AppException, ErrorCode
from aiSelfTest.models.task import (
    Task,
    TaskExecutionMode,
    TaskExecutionStatus,
    TaskItem,
    TaskItemData,
    TaskItemDataStatus,
)
from aiSelfTest.schemas.task import TaskFiltersPayload


RUNNING_TASK_STATUSES = {
    TaskExecutionStatus.DOWN.value,
    TaskExecutionStatus.LLM.value,
    TaskExecutionStatus.VERIFY.value,
    TaskExecutionStatus.SUBMIT.value,
}


@dataclass(frozen=True)
class TaskExecutionWindow:
    """本次任务执行使用的时间窗口。"""

    start_at: str
    end_at: str
    should_fetch: bool = True


@dataclass(frozen=True)
class SourceTaskItemRecord:
    """上游文件记录的规范化形状。"""

    name: str
    file_fid: str
    file_url: str
    file_bmp: int
    device_name: str = ""
    file_num: str = ""
    file_extension: str = ""
    sp_name_list: str = ""
    classify: int = 1
    result_file_data: str = ""
    id_type: int = 0
    record_data: list[Mapping[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class SourceTaskItemDataRecord:
    """上游详情记录的规范化形状。"""

    name: str
    score: float = 0
    track_ids: str = ""
    sp_amount: int = 1
    minx: float | None = None
    miny: float | None = None
    maxx: float | None = None
    maxy: float | None = None


@dataclass(frozen=True)
class TaskExecutionResult:
    """任务执行结果摘要。"""

    task_id: int
    inserted_count: int
    skipped_count: int
    detail_row_count: int
    processed_count: int
    execution_status: str


class TaskExecutionSource(Protocol):
    """执行主干的数据源协议。"""

    def fetch_task_items(
        self,
        *,
        session: Session,
        task: Task,
        filters: TaskFiltersPayload,
        window: TaskExecutionWindow,
    ) -> Sequence[SourceTaskItemRecord | Mapping[str, Any]]:
        """拉取本次需要处理的上游文件。"""

    def fetch_task_item_detail(
        self,
        *,
        session: Session,
        task: Task,
        task_item: TaskItem,
        source_record: SourceTaskItemRecord,
    ) -> Sequence[SourceTaskItemDataRecord | Mapping[str, Any]]:
        """拉取单个文件的识别详情。"""


class EmptyTaskExecutionSource:
    """默认空数据源，避免本地手动执行时误触发外部请求。"""

    def fetch_task_items(
        self,
        *,
        session: Session,
        task: Task,
        filters: TaskFiltersPayload,
        window: TaskExecutionWindow,
    ) -> Sequence[SourceTaskItemRecord]:
        """返回空文件列表，作为未接入上游时的安全默认值。"""

        return []

    def fetch_task_item_detail(
        self,
        *,
        session: Session,
        task: Task,
        task_item: TaskItem,
        source_record: SourceTaskItemRecord,
    ) -> Sequence[SourceTaskItemDataRecord]:
        """返回空详情列表，避免默认执行产生额外外部请求。"""

        return []


def run_task_execution(
    session: Session,
    task_id: int,
    *,
    source: TaskExecutionSource | None = None,
    now: datetime | None = None,
) -> TaskExecutionResult:
    """执行一次 Task V1 共享主干。

    source 缺省为空数据源，生产接入真实上游时只需要替换协议实现。
    """

    execution_now = now or datetime.now()
    task = _get_task_or_raise(session, task_id)
    logger.info(
        "任务执行开始: task_id={}, execution_mode={}, auto_confirm={}, active={}",
        task_id,
        task.execution_mode,
        task.auto_confirm,
        task.active,
    )
    if is_task_running(task):
        task.skipped_count += 1
        task.updated_at = execution_now
        session.add(task)
        session.commit()
        logger.warning("任务 {} 正在运行，跳过本次重复触发", task_id)
        return TaskExecutionResult(
            task_id=task_id,
            inserted_count=0,
            skipped_count=1,
            detail_row_count=0,
            processed_count=task.processed_count,
            execution_status=task.execution_status,
        )

    execution_source = source or EmptyTaskExecutionSource()
    filters = _deserialize_filters(task.filters_json)
    window = _build_execution_window(task, filters, execution_now)
    logger.debug(
        "任务执行窗口已计算: task_id={}, start_at={}, end_at={}, should_fetch={}",
        task_id,
        window.start_at,
        window.end_at,
        window.should_fetch,
    )

    task.started_at = execution_now
    task.last_run_started_at = execution_now
    task.finished_at = None
    task.last_error = None
    task.execution_status = TaskExecutionStatus.DOWN.value
    task.updated_at = execution_now
    session.add(task)
    session.commit()
    session.refresh(task)
    logger.info("任务状态切换: task_id={}, execution_status={}", task_id, task.execution_status)

    try:
        inserted_items: list[tuple[TaskItem, SourceTaskItemRecord]] = []
        skipped_count = 0
        detail_row_count = 0

        if window.should_fetch:
            source_records = [
                _coerce_source_record(row)
                for row in execution_source.fetch_task_items(
                    session=session,
                    task=task,
                    filters=filters,
                    window=window,
                )
            ]
            logger.info("任务上游记录拉取完成: task_id={}, source_count={}", task_id, len(source_records))
            inserted_items, skipped_count = _insert_new_task_items(
                session,
                task=task,
                source_records=source_records,
                now=execution_now,
            )
            logger.info(
                "任务上游记录入库完成: task_id={}, inserted_count={}, skipped_count={}",
                task_id,
                len(inserted_items),
                skipped_count,
            )
            if _is_auto_task(task):
                task.last_pull_end_at = _parse_window_end(window.end_at) or execution_now
        else:
            source_records = []
            logger.info("任务执行跳过上游拉取: task_id={}, reason=empty_window", task_id)

        task.skipped_count += skipped_count
        task.execution_status = TaskExecutionStatus.LLM.value
        task.updated_at = execution_now
        session.add(task)
        session.commit()
        logger.info("任务状态切换: task_id={}, execution_status={}", task_id, task.execution_status)

        for task_item, source_record in inserted_items:
            _mark_task_item_downloaded(task_item, now=execution_now)
            detail_row_count += _insert_task_item_data_rows(
                session,
                task=task,
                task_item=task_item,
                source_record=source_record,
                execution_source=execution_source,
            )
            _advance_task_item_recognition(
                session,
                task=task,
                task_item=task_item,
                now=execution_now,
            )
            logger.debug(
                "任务项处理完成: task_id={}, task_item_id={}, detail_row_count={}",
                task_id,
                task_item.id,
                detail_row_count,
            )

        task.execution_status = TaskExecutionStatus.FINISH.value
        task.finished_at = datetime.now()
        task.updated_at = task.finished_at
        task.total_count = _count_task_items(session, task_id)
        task.processed_count += len(inserted_items)
        session.add(task)
        session.commit()
        session.refresh(task)
        logger.info(
            "任务执行完成: task_id={}, inserted_count={}, skipped_count={}, detail_row_count={}, processed_count={}, execution_status={}",
            task_id,
            len(inserted_items),
            skipped_count,
            detail_row_count,
            task.processed_count,
            task.execution_status,
        )

        return TaskExecutionResult(
            task_id=task_id,
            inserted_count=len(inserted_items),
            skipped_count=skipped_count,
            detail_row_count=detail_row_count,
            processed_count=task.processed_count,
            execution_status=task.execution_status,
        )
    except Exception as exc:
        task = _get_task_or_raise(session, task_id)
        task.execution_status = TaskExecutionStatus.FAIL.value
        task.last_error = str(exc)
        task.updated_at = datetime.now()
        session.add(task)
        session.commit()
        logger.exception("任务 {} 执行失败", task_id)
        raise


def is_task_running(task: Task) -> bool:
    """判断任务是否处于运行中状态。"""

    return task.execution_status in RUNNING_TASK_STATUSES


def _insert_new_task_items(
    session: Session,
    *,
    task: Task,
    source_records: Sequence[SourceTaskItemRecord],
    now: datetime,
) -> tuple[list[tuple[TaskItem, SourceTaskItemRecord]], int]:
    """按 file_fid 去重插入新的任务项，并统计重复跳过数量。"""

    if not source_records:
        return [], 0

    incoming_fids = [record.file_fid for record in source_records]
    existing_fids = set(
        session.exec(
            select(TaskItem.file_fid).where(
                TaskItem.task_id == task.id,
                TaskItem.file_fid.in_(incoming_fids),
            )
        ).all()
    )

    inserted: list[tuple[TaskItem, SourceTaskItemRecord]] = []
    skipped_count = 0
    for record in source_records:
        if record.file_fid in existing_fids:
            skipped_count += 1
            continue

        task_item = TaskItem(
            task_id=task.id or 0,
            name=_truncate(record.name, 200),
            device_name=_truncate(record.device_name or "--", 100),
            file_num=_truncate(record.file_num or record.file_fid, 50),
            file_extension=_truncate(record.file_extension or _infer_extension(record), 10),
            file_url=_truncate(record.file_url, 200),
            file_fid=_truncate(record.file_fid, 50),
            sp_name_list=_truncate(record.sp_name_list, 100),
            classify=record.classify,
            file_bmp=record.file_bmp,
            result_file_data=_truncate(record.result_file_data, 100),
            id_type=record.id_type,
            status="created",
            created_at=now,
            updated_at=now,
            down_state=False,
            llm_state="pending",
            confirm_state="pending",
            remote_state="pending",
            train_state="pending",
        )
        session.add(task_item)
        session.commit()
        session.refresh(task_item)
        inserted.append((task_item, record))
        existing_fids.add(record.file_fid)
        logger.debug(
            "任务项入库完成: task_id={}, task_item_id={}, file_fid={}",
            task.id,
            task_item.id,
            record.file_fid,
        )

    return inserted, skipped_count


def _insert_task_item_data_rows(
    session: Session,
    *,
    task: Task,
    task_item: TaskItem,
    source_record: SourceTaskItemRecord,
    execution_source: TaskExecutionSource,
) -> int:
    """拉取并写入单个任务项的识别详情行。"""

    raw_rows = execution_source.fetch_task_item_detail(
        session=session,
        task=task,
        task_item=task_item,
        source_record=source_record,
    )
    detail_rows = [
        _coerce_detail_record(row)
        for row in (raw_rows or source_record.record_data)
    ]
    for row in detail_rows:
        task_item_data = TaskItemData(
            task_item_id=task_item.id or 0,
            name=_truncate(row.name, 100),
            score=row.score,
            track_ids=_truncate(row.track_ids, 100),
            sp_amount=row.sp_amount,
            minx=row.minx,
            miny=row.miny,
            maxx=row.maxx,
            maxy=row.maxy,
            llm_name=None,
            status=TaskItemDataStatus.DEFAULT.value,
        )
        session.add(task_item_data)
    if detail_rows:
        session.commit()
    logger.debug(
        "任务项详情行入库完成: task_id={}, task_item_id={}, detail_row_count={}",
        task.id,
        task_item.id,
        len(detail_rows),
    )
    return len(detail_rows)


def _mark_task_item_downloaded(task_item: TaskItem, *, now: datetime) -> None:
    """将任务项推进到已下载占位状态，并记录预期元数据路径。"""

    task_item.down_state = True
    task_item.down_error = None
    task_item.file_path = _build_metadata_file_path(task_item)
    task_item.status = "downloaded"
    task_item.updated_at = now


def _advance_task_item_recognition(
    session: Session,
    *,
    task: Task,
    task_item: TaskItem,
    now: datetime,
) -> None:
    """推进任务项识别、确认、提交和训练目录状态。"""

    data_rows = session.exec(
        select(TaskItemData).where(TaskItemData.task_item_id == task_item.id)
    ).all()
    if _is_auto_task(task):
        for row in data_rows:
            row.llm_name = row.llm_name or row.name
            session.add(row)
        task_item.llm_state = "success"
        task_item.llm_error = None
        task_item.llm_at = now
        task_item.status = "verified"
    else:
        task_item.llm_state = "pending"
        task_item.status = "created"

    if task.auto_confirm:
        task_item.confirm_state = "auto_confirmed"
        task_item.confirmed_at = now
        task_item.remote_state = "success"
        task_item.remote_error = None
        task_item.remote_at = now
        task_item.train_state = "saved"
        task_item.train_at = now
        task_item.status = "done"

    task_item.updated_at = now
    session.add(task_item)
    session.commit()
    logger.debug(
        "任务项状态推进完成: task_id={}, task_item_id={}, status={}, llm_state={}, confirm_state={}, remote_state={}",
        task.id,
        task_item.id,
        task_item.status,
        task_item.llm_state,
        task_item.confirm_state,
        task_item.remote_state,
    )


def _build_execution_window(
    task: Task,
    filters: TaskFiltersPayload,
    now: datetime,
) -> TaskExecutionWindow:
    """根据任务模式和筛选条件计算本次拉取时间窗口。"""

    end_at = _clip_end_at(filters.end_at, now)
    if _is_auto_task(task):
        start_at = _format_dt(task.last_pull_end_at) if task.last_pull_end_at else filters.start_at
        should_fetch = not (start_at and end_at and start_at >= end_at)
        return TaskExecutionWindow(start_at=start_at, end_at=end_at, should_fetch=should_fetch)
    return TaskExecutionWindow(start_at=filters.start_at, end_at=filters.end_at or end_at)


def _deserialize_filters(raw: str | None) -> TaskFiltersPayload:
    """将数据库中的筛选 JSON 还原为任务筛选对象。"""

    if not raw:
        return TaskFiltersPayload()
    return TaskFiltersPayload.model_validate(json.loads(raw))


def _coerce_source_record(row: SourceTaskItemRecord | Mapping[str, Any]) -> SourceTaskItemRecord:
    """将上游不同命名风格的文件记录规范化为内部结构。"""

    if isinstance(row, SourceTaskItemRecord):
        return row

    file_fid = _first_text(row, "file_fid", "fileFid", "fileId", "file_id", "fid", "id")
    file_url = _first_text(row, "file_url", "fileUrl", "mediaUrl", "url")
    name = _first_text(row, "name", "fileName", "file_name", default=file_fid)
    if not file_fid or not file_url:
        logger.warning("上游文件记录缺少必要字段: has_file_fid={}, has_file_url={}", bool(file_fid), bool(file_url))
        raise AppException(
            code=ErrorCode.PARAMS_ERROR,
            message="上游文件记录缺少 file_fid 或 file_url",
            status_code=400,
        )

    media_type = _first_text(row, "media_type", "mediaType", "fileBmp", "file_bmp", default="image")
    return SourceTaskItemRecord(
        name=name,
        file_fid=file_fid,
        file_url=file_url,
        file_bmp=_coerce_file_bmp(media_type),
        device_name=_first_text(row, "device_name", "deviceName", "deName", default=""),
        file_num=_first_text(row, "file_num", "fileNum", "fileNo", default=""),
        file_extension=_first_text(row, "file_extension", "fileExtension", "extension", default=""),
        sp_name_list=_first_text(row, "sp_name_list", "spNameList", "spName", default=""),
        classify=_first_int(row, "classify", default=1),
        result_file_data=_first_text(row, "result_file_data", "resultFileData", "resultFileUrl", default=""),
        id_type=_first_int(row, "id_type", "idType", default=0),
        record_data=list(row.get("record_data") or row.get("recordData") or []),
    )


def _coerce_detail_record(
    row: SourceTaskItemDataRecord | Mapping[str, Any],
) -> SourceTaskItemDataRecord:
    """将上游识别详情规范化为内部详情结构。"""

    if isinstance(row, SourceTaskItemDataRecord):
        return row

    bbox = row.get("bbox") or row.get("box") or []
    minx = row.get("minx")
    miny = row.get("miny")
    maxx = row.get("maxx")
    maxy = row.get("maxy")
    if len(bbox) == 4:
        minx, miny, maxx, maxy = bbox

    return SourceTaskItemDataRecord(
        name=_first_text(row, "name", "spName", "originalName", default=""),
        score=_first_float(row, "score", "confidence", default=0),
        track_ids=_first_text(row, "track_ids", "trackIds", "track_id", "trackId", default=""),
        sp_amount=_first_int(row, "sp_amount", "spAmount", default=1),
        minx=_optional_float(minx),
        miny=_optional_float(miny),
        maxx=_optional_float(maxx),
        maxy=_optional_float(maxy),
    )


def _is_auto_task(task: Task) -> bool:
    """判断任务是否使用自动执行模式。"""

    return task.execution_mode in {TaskExecutionMode.AUTO.value, "auto"}


def _count_task_items(session: Session, task_id: int) -> int:
    """统计指定任务下的任务项数量。"""

    return len(session.exec(select(TaskItem.id).where(TaskItem.task_id == task_id)).all())


def _get_task_or_raise(session: Session, task_id: int) -> Task:
    """按 ID 查询任务，不存在时抛出统一异常。"""

    task = session.get(Task, task_id)
    if task is None:
        raise AppException(code=ErrorCode.NOT_FOUND, message="任务不存在", status_code=404)
    return task


def _build_metadata_file_path(task_item: TaskItem) -> str:
    """构建任务项原始文件在本地数据目录中的预期路径。"""

    extension = task_item.file_extension or _infer_extension_from_name(task_item.name)
    filename = f"original.{extension}" if extension else "original"
    return (
        get_settings().data_dir
        / "task_files"
        / str(task_item.task_id)
        / str(task_item.id or 0)
        / filename
    ).as_posix()


def _clip_end_at(end_at: str, now: datetime) -> str:
    """将结束时间裁剪到不晚于当前执行时间。"""

    if not end_at:
        return _format_dt(now)
    parsed = _parse_window_end(end_at)
    if parsed and parsed < now:
        return _format_dt(parsed)
    return _format_dt(now)


def _parse_window_end(value: str) -> datetime | None:
    """解析筛选结束时间，解析失败时返回 None 以保持兼容。"""

    if not value:
        return None
    normalized = value.strip().replace("Z", "+00:00")
    if len(normalized) == 10:
        normalized = f"{normalized} 23:59:59"
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _format_dt(value: datetime) -> str:
    """按旧接口兼容格式输出日期时间。"""

    return value.strftime("%Y-%m-%d %H:%M:%S")


def _first_text(row: Mapping[str, Any], *keys: str, default: str = "") -> str:
    """按候选键顺序读取第一个非空文本值。"""

    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    return default


def _first_int(row: Mapping[str, Any], *keys: str, default: int) -> int:
    """按候选键顺序读取第一个可转换整数值。"""

    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            try:
                return int(value)
            except (TypeError, ValueError):
                return default
    return default


def _first_float(row: Mapping[str, Any], *keys: str, default: float) -> float:
    """按候选键顺序读取第一个可转换浮点值。"""

    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            converted = _optional_float(value)
            return default if converted is None else converted
    return default


def _optional_float(value: Any) -> float | None:
    """将可选输入转换为浮点数，空值或非法值返回 None。"""

    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_file_bmp(value: object) -> int:
    """将媒体类型转换为旧模型使用的 file_bmp 数值。"""

    if isinstance(value, int):
        return 2 if value == 2 else 1
    text = str(value).lower()
    return 2 if text in {"2", "video", "mp4", "视频"} else 1


def _infer_extension(record: SourceTaskItemRecord) -> str:
    """从记录名称或 URL 推断文件扩展名。"""

    return _infer_extension_from_name(record.name) or _infer_extension_from_name(record.file_url)


def _infer_extension_from_name(value: str) -> str:
    """从路径或 URL 文本中提取扩展名。"""

    path = Path(urlparse(value).path)
    suffix = path.suffix.lstrip(".")
    return suffix or ""


def _truncate(value: str, max_length: int) -> str:
    """按数据库字段长度截断文本。"""

    return value[:max_length]
