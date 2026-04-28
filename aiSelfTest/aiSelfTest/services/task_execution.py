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
from aiSelfTest.services.client_auth import perform_authenticated_request


RUNNING_TASK_STATUSES = {
    TaskExecutionStatus.DOWN.value,
    TaskExecutionStatus.LLM.value,
    TaskExecutionStatus.VERIFY.value,
    TaskExecutionStatus.SUBMIT.value,
}
UPSTREAM_FILE_PAGE_PATH = "/openApi/icFile/findFilePage"
UPSTREAM_FILE_DETAIL_PATH = "/openApi/icFile/getResultByFileId1"
UPSTREAM_PAGE_SIZE = 100
MAX_UPSTREAM_PAGE_COUNT = 500


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
    file_id: str = ""
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
    """测试或显式本地空跑使用的数据源。"""

    def fetch_task_items(
        self,
        *,
        session: Session,
        task: Task,
        filters: TaskFiltersPayload,
        window: TaskExecutionWindow,
    ) -> Sequence[SourceTaskItemRecord]:
        """返回空文件列表，作为未接入真实上游时的安全默认。"""

        return []

    def fetch_task_item_detail(
        self,
        *,
        session: Session,
        task: Task,
        task_item: TaskItem,
        source_record: SourceTaskItemRecord,
    ) -> Sequence[SourceTaskItemDataRecord]:
        """返回空详情列表，避免默认实现访问外部详情服务。"""

        return []


class AuthenticatedTaskExecutionSource:
    """通过已配置客户端认证信息调用真实上游接口。"""

    def fetch_task_items(
        self,
        *,
        session: Session,
        task: Task,
        filters: TaskFiltersPayload,
        window: TaskExecutionWindow,
    ) -> Sequence[Mapping[str, Any]]:
        """分页拉取符合任务筛选条件的真实上游文件。"""

        all_records: list[Mapping[str, Any]] = []
        current = 1
        for _ in range(MAX_UPSTREAM_PAGE_COUNT):
            payload = _build_upstream_page_payload(
                filters,
                window,
                current=current,
                size=UPSTREAM_PAGE_SIZE,
            )
            response = perform_authenticated_request(
                session,
                task.client_id,
                "POST",
                UPSTREAM_FILE_PAGE_PATH,
                json=payload,
            )
            page_payload = _extract_response_payload(
                response,
                path=UPSTREAM_FILE_PAGE_PATH,
            )
            page_records = _extract_page_records(page_payload)
            all_records.extend(page_records)
            logger.info(
                "上游分页查询完成: task_id={}, current={}, page_count={}, total_loaded={}",
                task.id,
                current,
                len(page_records),
                len(all_records),
            )
            if not _has_next_page(page_payload, current, len(page_records), len(all_records)):
                return all_records
            current += 1

        logger.warning(
            "上游分页达到安全上限: task_id={}, max_page_count={}, loaded_count={}",
            task.id,
            MAX_UPSTREAM_PAGE_COUNT,
            len(all_records),
        )
        return all_records

    def fetch_task_item_detail(
        self,
        *,
        session: Session,
        task: Task,
        task_item: TaskItem,
        source_record: SourceTaskItemRecord,
    ) -> Sequence[Mapping[str, Any]]:
        """按文件 ID 拉取单个上游文件的识别结果详情。"""

        file_id = source_record.file_id or source_record.file_fid
        response = perform_authenticated_request(
            session,
            task.client_id,
            "GET",
            UPSTREAM_FILE_DETAIL_PATH,
            params={"fileId": file_id},
        )
        detail_payload = _extract_response_payload(
            response,
            path=UPSTREAM_FILE_DETAIL_PATH,
        )
        detail_records = _extract_detail_records(detail_payload)
        logger.info(
            "上游详情查询完成: task_id={}, task_item_id={}, file_id={}, detail_count={}",
            task.id,
            task_item.id,
            file_id,
            len(detail_records),
        )
        return detail_records


def run_task_execution(
    session: Session,
    task_id: int,
    *,
    source: TaskExecutionSource | None = None,
    now: datetime | None = None,
) -> TaskExecutionResult:
    """执行一次 Task V1 共享主干。

    source 缺省为认证上游数据源；测试可显式注入 fake source 隔离外部请求。
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

    execution_source = source or AuthenticatedTaskExecutionSource()
    filters = _deserialize_filters(task.filters_json)
    window = _build_execution_window(task, filters, execution_now)
    logger.info(
        "任务执行开始 task_id={} execution_mode={} window_start={} window_end={} should_fetch={}",
        task_id,
        task.execution_mode,
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
    logger.debug("任务状态已切换 task_id={} execution_status={}", task_id, task.execution_status)

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
            logger.info("上游任务项拉取完成 task_id={} source_count={}", task_id, len(source_records))
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
        logger.info(
            "任务进入识别阶段 task_id={} inserted_count={} skipped_count={}",
            task_id,
            len(inserted_items),
            skipped_count,
        )

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
            "任务执行完成 task_id={} inserted_count={} skipped_count={} detail_row_count={} processed_count={}",
            task_id,
            len(inserted_items),
            skipped_count,
            detail_row_count,
            task.processed_count,
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
    """插入本次新发现的任务项，并跳过已存在的上游文件。"""

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
            "新增任务项: task_id={}, task_item_id={}, file_fid={}, media_type={}",
            task.id,
            task_item.id,
            record.file_fid,
            record.file_bmp,
        )

    logger.debug(
        "任务项落库完成 task_id={} inserted_count={} skipped_count={}",
        task.id,
        len(inserted),
        skipped_count,
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
    """拉取并插入单个任务项的识别明细行。"""

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
        "任务项识别明细落库完成 task_id={} task_item_id={} detail_count={}",
        task.id,
        task_item.id,
        len(detail_rows),
    )
    return len(detail_rows)


def _mark_task_item_downloaded(task_item: TaskItem, *, now: datetime) -> None:
    """把任务项推进到下载完成占位状态。"""

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
    """根据任务模式推进识别、确认、远端提交和训练占位状态。"""

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
        "任务项状态推进完成 task_id={} task_item_id={} status={} confirm_state={} remote_state={}",
        task.id,
        task_item.id,
        task_item.status,
        task_item.confirm_state,
        task_item.remote_state,
    )


def _build_execution_window(
    task: Task,
    filters: TaskFiltersPayload,
    now: datetime,
) -> TaskExecutionWindow:
    """按任务模式和筛选条件计算本次执行窗口。"""

    end_at = _clip_end_at(filters.end_at, now)
    if _is_auto_task(task):
        start_at = _format_dt(task.last_pull_end_at) if task.last_pull_end_at else filters.start_at
        should_fetch = not (start_at and end_at and start_at >= end_at)
        return TaskExecutionWindow(start_at=start_at, end_at=end_at, should_fetch=should_fetch)
    return TaskExecutionWindow(start_at=filters.start_at, end_at=filters.end_at or end_at)


def _deserialize_filters(raw: str | None) -> TaskFiltersPayload:
    """从任务表 JSON 字段恢复筛选条件。"""

    if not raw:
        return TaskFiltersPayload()
    return TaskFiltersPayload.model_validate(json.loads(raw))


def _coerce_source_record(row: SourceTaskItemRecord | Mapping[str, Any]) -> SourceTaskItemRecord:
    """把上游文件记录兼容转换为执行主干内部结构。"""

    if isinstance(row, SourceTaskItemRecord):
        return row

    file_id = _first_text(row, "file_id", "fileId", "id", default="")
    file_fid = _first_text(
        row,
        "file_fid",
        "fileFid",
        "fileId",
        "file_id",
        "fid",
        "id",
        default=file_id,
    )
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
        file_id=file_id,
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
    """把上游识别详情记录兼容转换为内部结构。"""

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
    """判断任务是否采用自动执行模式。"""

    return task.execution_mode in {TaskExecutionMode.AUTO.value, "auto"}


def _build_upstream_page_payload(
    filters: TaskFiltersPayload,
    window: TaskExecutionWindow,
    *,
    current: int,
    size: int,
) -> dict[str, Any]:
    """把本地任务筛选条件转换为上游分页查询请求体。"""

    payload: dict[str, Any] = {
        "size": size,
        "current": current,
        "keyword": filters.keyword,
        "spName": filters.sp_name,
        "startTime": _normalize_window_boundary(window.start_at, end_of_day=False),
        "endTime": _normalize_window_boundary(window.end_at, end_of_day=True),
        "sortColumn": "fe.file_time",
        "sortOrder": "ASC",
        "module": "camera",
    }
    if filters.classify_list:
        payload["classifyList"] = filters.classify_list
        if len(filters.classify_list) == 1:
            payload["classify"] = filters.classify_list[0]
    if filters.media_types:
        payload["fileBmp"] = _media_types_to_file_bmp(filters.media_types)
    if filters.upload_types:
        payload["uploadType"] = filters.upload_types
    if filters.identify_source:
        payload["idWayList"] = filters.identify_source
        if len(filters.identify_source) == 1:
            payload["idType"] = filters.identify_source[0]
    return payload


def _extract_response_payload(response: Any, *, path: str) -> Any:
    """校验上游响应状态并兼容提取业务数据。"""

    if response.status_code != 200:
        logger.warning(
            "上游接口返回非成功状态: path={}, status={}, body={}",
            path,
            response.status_code,
            getattr(response, "text", ""),
        )
        raise AppException(
            code=ErrorCode.TASK_FAILED,
            message=f"上游接口请求失败: {path}",
            status_code=502,
        )

    try:
        payload = response.json()
    except ValueError as exc:
        logger.warning("上游接口返回非 JSON 数据: path={}, body={}", path, getattr(response, "text", ""))
        raise AppException(
            code=ErrorCode.TASK_FAILED,
            message=f"上游接口返回格式错误: {path}",
            status_code=502,
        ) from exc

    if isinstance(payload, Mapping):
        response_code = payload.get("code")
        if response_code not in (None, 0, "0", 200, "200"):
            message = _first_text(payload, "message", "msg", "error", default="上游接口业务失败")
            logger.warning("上游接口返回业务错误: path={}, code={}, message={}", path, response_code, message)
            raise AppException(
                code=ErrorCode.TASK_FAILED,
                message=message,
                status_code=502,
            )
        data = payload.get("data")
        if isinstance(data, (Mapping, list)):
            return data
    return payload


def _extract_page_records(payload: Any) -> list[Mapping[str, Any]]:
    """从上游分页响应中提取文件列表。"""

    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, Mapping)]
    if not isinstance(payload, Mapping):
        logger.warning("上游分页响应不是对象或列表: payload_type={}", type(payload).__name__)
        return []

    for key in ("results", "records", "items", "list"):
        value = payload.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, Mapping)]
    logger.warning("上游分页响应缺少结果列表字段: keys={}", list(payload.keys()))
    return []


def _extract_detail_records(payload: Any) -> list[Mapping[str, Any]]:
    """从上游详情响应中提取识别结果记录。"""

    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, Mapping)]
    if not isinstance(payload, Mapping):
        logger.warning("上游详情响应不是对象或列表: payload_type={}", type(payload).__name__)
        return []

    record_data = payload.get("recordData") or payload.get("record_data") or []
    if isinstance(record_data, list):
        return [row for row in record_data if isinstance(row, Mapping)]
    logger.warning(
        "上游详情 recordData 字段不是列表: payload_keys={}, record_data_type={}",
        list(payload.keys()),
        type(record_data).__name__,
    )
    return []


def _has_next_page(
    payload: Any,
    current: int,
    page_count: int,
    loaded_count: int,
) -> bool:
    """根据上游分页元数据判断是否继续拉取下一页。"""

    if not isinstance(payload, Mapping):
        return False

    total_pages = _first_int(payload, "totalCurrent", "totalPages", "pages", default=0)
    if total_pages > 0:
        return current < total_pages

    total_count = _first_int(payload, "total", "totalCount", default=0)
    if total_count > 0:
        return page_count > 0 and loaded_count < total_count

    page_size = _first_int(payload, "size", "pageSize", default=UPSTREAM_PAGE_SIZE)
    return page_count >= page_size


def _media_types_to_file_bmp(media_types: Sequence[str]) -> list[int]:
    """把前端媒体类型转换为上游 fileBmp 枚举。"""

    values: list[int] = []
    mapping = {"image": 1, "video": 2}
    for media_type in media_types:
        value = mapping.get(media_type)
        if value is not None and value not in values:
            values.append(value)
    return values


def _normalize_window_boundary(value: str, *, end_of_day: bool) -> str:
    """把日期或日期时间规整为上游需要的标准时间字符串。"""

    text = (value or "").strip()
    if not text:
        return ""
    if len(text) == 10:
        suffix = "23:59:59" if end_of_day else "00:00:00"
        return f"{text} {suffix}"

    normalized = text.replace("Z", "+00:00")
    try:
        return _format_dt(datetime.fromisoformat(normalized))
    except ValueError:
        return text


def _count_task_items(session: Session, task_id: int) -> int:
    """统计任务当前关联的任务项数量。"""

    return len(session.exec(select(TaskItem.id).where(TaskItem.task_id == task_id)).all())


def _get_task_or_raise(session: Session, task_id: int) -> Task:
    """按 ID 查询任务，不存在时抛出统一异常。"""

    task = session.get(Task, task_id)
    if task is None:
        raise AppException(code=ErrorCode.NOT_FOUND, message="任务不存在", status_code=404)
    return task


def _build_metadata_file_path(task_item: TaskItem) -> str:
    """构造任务项原始文件在本地数据目录中的元数据路径。"""

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
    """把结束时间裁剪到当前时间，避免自动任务拉取未来窗口。"""

    if not end_at:
        return _format_dt(now)
    parsed = _parse_window_end(end_at)
    if parsed and parsed < now:
        return _format_dt(parsed)
    return _format_dt(now)


def _parse_window_end(value: str) -> datetime | None:
    """兼容解析日期或 ISO 时间格式的窗口结束时间。"""

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
    """统一格式化任务执行窗口时间。"""

    return value.strftime("%Y-%m-%d %H:%M:%S")


def _first_text(row: Mapping[str, Any], *keys: str, default: str = "") -> str:
    """从多个候选字段中取第一个非空文本。"""

    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    return default


def _first_int(row: Mapping[str, Any], *keys: str, default: int) -> int:
    """从多个候选字段中取第一个可解析整数。"""

    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            try:
                return int(value)
            except (TypeError, ValueError):
                return default
    return default


def _first_float(row: Mapping[str, Any], *keys: str, default: float) -> float:
    """从多个候选字段中取第一个可解析浮点数。"""

    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            converted = _optional_float(value)
            return default if converted is None else converted
    return default


def _optional_float(value: Any) -> float | None:
    """把可选数值转换为浮点数，无法转换时返回 None。"""

    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_file_bmp(value: object) -> int:
    """把上游媒体类型兼容转换为数据库中的 file_bmp 枚举值。"""

    if isinstance(value, int):
        return 2 if value == 2 else 1
    text = str(value).lower()
    return 2 if text in {"2", "video", "mp4", "视频"} else 1


def _infer_extension(record: SourceTaskItemRecord) -> str:
    """从上游记录名称或 URL 推断文件扩展名。"""

    return _infer_extension_from_name(record.name) or _infer_extension_from_name(record.file_url)


def _infer_extension_from_name(value: str) -> str:
    """从文件名或 URL 路径中提取扩展名。"""

    path = Path(urlparse(value).path)
    suffix = path.suffix.lstrip(".")
    return suffix or ""


def _truncate(value: str, max_length: int) -> str:
    """按数据库字段长度截断字符串。"""

    return value[:max_length]
