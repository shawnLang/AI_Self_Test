"""任务与任务项路由。"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Annotated

from aiSelfTest.config import get_settings
from aiSelfTest.database import get_session
from aiSelfTest.exceptions import AppException, ErrorCode
from aiSelfTest.models.task import (
    Task,
    TaskExecution,
    TaskExecutionTriggerType,
    TaskItem,
    TaskItemConfirmState,
    TaskItemData,
    TaskItemDataStatus,
    TaskItemLlmState,
    TaskItemRecognitionBatch,
    TaskItemRemoteState,
    TaskItemStatus,
    TaskSubmission,
)
from aiSelfTest.schemas.common import ApiResponse
from aiSelfTest.schemas.task import (
    TaskActionData,
    TaskCompensationResetData,
    TaskCreateRequest,
    TaskDeleteData,
    TaskFiltersPayload,
    TaskItemActionData,
    TaskItemActionRequest,
    TaskItemDetailData,
    TaskItemListData,
    TaskItemListRow,
    TaskItemReRecognitionBatchData,
    TaskItemReRecognitionBatchRequest,
    TaskItemRejectRequest,
    TaskItemReviewRow,
    TaskItemReviewRowUpdateRequest,
    TaskListData,
    TaskResponse,
    TaskSubmissionData,
    TaskUpdateRequest,
    resolve_task_item_source_size,
)
from aiSelfTest.services.task_dispatch import ACTIVE_EXECUTION_STATUSES, TaskDispatchService
from aiSelfTest.services.task_item_compensation import (
    TASK_ITEM_COMPENSATION_MAX_ATTEMPTS,
    TaskItemCompensationService,
)
from aiSelfTest.services.task_re_recognition import TaskItemReRecognitionService
from aiSelfTest.services.task_review import apply_task_item_review_state, refresh_task_finish_state
from aiSelfTest.services.task_submission_job import TaskSubmissionJobService
from fastapi import APIRouter, Depends, Query, status
from loguru import logger
from sqlalchemy import or_
from sqlmodel import Session, select

task_router = APIRouter(prefix="/tasks")
task_item_router = APIRouter(prefix="/task-items")


@task_router.get("/list", response_model=ApiResponse[TaskListData])
def list_tasks_route(session: Session = Depends(get_session)) -> ApiResponse[TaskListData]:
    """查询任务列表。"""

    rows = session.exec(select(Task).order_by(Task.id.desc())).all()
    limited_counts = _count_compensation_limited_items(session, [task.id or 0 for task in rows])
    items = [
        TaskResponse.from_model(
            task,
            filters=_deserialize_filters(task.filters_json),
            current_execution=_get_active_execution(session, task.id or 0),
            compensation_limited_count=limited_counts.get(task.id or 0, 0),
        )
        for task in rows
    ]
    return ApiResponse(code=0, message="success", data=TaskListData(items=items))


@task_router.post("/create", response_model=ApiResponse[TaskResponse], status_code=status.HTTP_201_CREATED)
def create_task_route(payload: TaskCreateRequest, session: Session = Depends(get_session)) -> ApiResponse[TaskResponse]:
    """创建任务。"""

    task = Task(
        name=payload.name,
        client_id=payload.client_id,
        config_id=payload.config_id,
        interval=payload.interval_hours,
        filters_json=_serialize_filters(payload.filters),
        execution_mode=payload.execution_mode,
        auto_execute=payload.auto_execute,
        active=False,
    )
    session.add(task)
    session.commit()
    session.refresh(task)
    current_execution = None
    if task.auto_execute:
        dispatch_result = TaskDispatchService(session).submit(
            task_id=task.id or 0,
            trigger_type=TaskExecutionTriggerType.CREATE_AUTO.value,
        )
        task = dispatch_result.task
        current_execution = dispatch_result.execution
        session.refresh(task)
    logger.info(
        "任务创建完成 task_id={} name={} client_id={} config_id={} interval={} execution_mode={}",
        task.id,
        task.name,
        task.client_id,
        task.config_id,
        task.interval,
        task.execution_mode,
    )
    data = TaskResponse.from_model(task, filters=payload.filters, current_execution=current_execution)
    return ApiResponse(code=0, message="success", data=data)


@task_router.get("/detail/{task_id}", response_model=ApiResponse[TaskResponse])
def get_task_detail_route(task_id: int, session: Session = Depends(get_session)) -> ApiResponse[TaskResponse]:
    """查询任务详情。"""

    task = _get_task_or_raise(session, task_id)
    limited_counts = _count_compensation_limited_items(session, [task_id])
    data = TaskResponse.from_model(
        task,
        filters=_deserialize_filters(task.filters_json),
        current_execution=_get_active_execution(session, task_id),
        compensation_limited_count=limited_counts.get(task_id, 0),
    )
    return ApiResponse(code=0, message="success", data=data)


@task_router.post("/update/{task_id}", response_model=ApiResponse[TaskResponse])
def update_task_route(task_id: int, payload: TaskUpdateRequest, session: Session = Depends(get_session)) -> ApiResponse[
    TaskResponse]:
    """更新任务。"""

    task = _get_task_or_raise(session, task_id)
    _ensure_task_can_be_modified(session, task_id)
    task.name = payload.name
    task.client_id = payload.client_id
    task.config_id = payload.config_id
    task.interval = payload.interval_hours
    task.execution_mode = payload.execution_mode
    task.auto_execute = payload.auto_execute
    task.filters_json = _serialize_filters(payload.filters)
    task.updated_at = datetime.now()

    session.add(task)
    session.commit()
    session.refresh(task)
    logger.info(
        "更新任务成功: task_id={}, client_id={}, config_id={}, execution_mode={}, auto_execute={}",
        task.id,
        task.client_id,
        task.config_id,
        task.execution_mode,
        task.auto_execute,
    )
    return ApiResponse(
        code=0,
        message="success",
        data=TaskResponse.from_model(
            task,
            filters=payload.filters,
            current_execution=_get_active_execution(session, task.id or 0),
        ),
    )


@task_router.delete("/delete/{task_id}", response_model=ApiResponse[TaskDeleteData])
def delete_task_route(task_id: int, session: Session = Depends(get_session)) -> ApiResponse[TaskDeleteData]:
    """删除任务及关联任务项。"""

    download_dirs: set[Path] = set()
    with session.begin():
        task = _get_task_or_raise(session, task_id)
        _ensure_task_can_be_deleted(session, task_id, task)
        task_items = session.exec(select(TaskItem).where(TaskItem.task_id == task_id)).all()
        task_item_ids = [row.id for row in task_items if row.id is not None]
        download_dirs = _resolve_task_download_dirs(task_items)
        batches = session.exec(
            select(TaskItemRecognitionBatch).where(TaskItemRecognitionBatch.task_id == task_id)
        ).all()
        for batch in batches:
            session.delete(batch)
        submissions = session.exec(select(TaskSubmission).where(TaskSubmission.task_id == task_id)).all()
        for submission in submissions:
            session.delete(submission)
        session.flush()

        if task_item_ids:
            task_item_data_rows = session.exec(
                select(TaskItemData).where(TaskItemData.task_item_id.in_(task_item_ids))
            ).all()
            for row in task_item_data_rows:
                session.delete(row)
            session.flush()
        else:
            task_item_data_rows = []

        for row in task_items:
            session.delete(row)
        session.flush()

        task_executions = session.exec(select(TaskExecution).where(TaskExecution.task_id == task_id)).all()
        for row in task_executions:
            session.delete(row)
        session.flush()

        session.delete(task)

    deleted_download_dir_count = _delete_task_download_dirs(task_id, download_dirs)
    logger.info(
        "任务删除完成 task_id={} task_item_count={} detail_count={} execution_count={} download_dir_count={}",
        task_id,
        len(task_items),
        len(task_item_data_rows),
        len(task_executions),
        deleted_download_dir_count,
    )
    return ApiResponse(code=0, message="success", data=TaskDeleteData(id=task_id))


@task_router.post("/action-start/{task_id}", response_model=ApiResponse[TaskActionData])
def start_task_route(task_id: int, session: Session = Depends(get_session)) -> ApiResponse[TaskActionData]:
    """启动任务自动调度。"""

    task = _get_task_or_raise(session, task_id)
    task.active = True
    task.next_run_at = datetime.now()
    task.updated_at = datetime.now()
    session.add(task)
    session.commit()
    session.refresh(task)
    logger.info("任务已启动 task_id={} execution_status={}", task.id, task.execution_status)
    data = TaskActionData.from_model(task, _get_active_execution(session, task.id or 0))
    return ApiResponse(code=0, message="success", data=data)


@task_router.post("/action-stop/{task_id}", response_model=ApiResponse[TaskActionData])
def stop_task_route(task_id: int, session: Session = Depends(get_session)) -> ApiResponse[TaskActionData]:
    """停止任务自动调度。"""

    task = _get_task_or_raise(session, task_id)
    task.active = False
    task.updated_at = datetime.now()
    session.add(task)
    session.commit()
    session.refresh(task)
    logger.info("任务已停止 task_id={} execution_status={}", task.id, task.execution_status)
    data = TaskActionData.from_model(task, _get_active_execution(session, task.id or 0))
    return ApiResponse(code=0, message="success", data=data)


@task_router.post("/action-run/{task_id}", response_model=ApiResponse[TaskActionData])
def run_task_route(task_id: int, session: Session = Depends(get_session)) -> ApiResponse[TaskActionData]:
    """立即执行一次任务。"""

    dispatch_result = TaskDispatchService(session).submit(
        task_id=task_id,
        trigger_type=TaskExecutionTriggerType.MANUAL.value,
    )
    logger.info("任务手动执行已入队 task_id={} execution_id={}", task_id, dispatch_result.execution.id)
    data = TaskActionData.from_model(dispatch_result.task, dispatch_result.execution)
    return ApiResponse(code=0, message="success", data=data)


@task_router.post("/action-submit/{task_id}", response_model=ApiResponse[TaskSubmissionData])
def submit_task_outputs_route(task_id: int, session: Session = Depends(get_session)) -> ApiResponse[TaskSubmissionData]:
    """提交任务下已确认结果到远端并后台保存训练数据。"""

    result = TaskSubmissionJobService(session).submit(task_id)
    logger.info("任务提交保存已入队 task_id={} submission_id={}", task_id, result.submission.id)
    return ApiResponse(code=0, message="success", data=TaskSubmissionData.from_model(result.submission))


@task_router.post("/action-reset-compensation/{task_id}", response_model=ApiResponse[TaskCompensationResetData])
def reset_task_compensation_route(
    task_id: int,
    session: Session = Depends(get_session),
) -> ApiResponse[TaskCompensationResetData]:
    """恢复已达到补偿上限的任务项，并立即投递补偿。"""

    result = TaskItemCompensationService(session).reset_task_limited_items(task_id)
    logger.info(
        "任务补偿恢复已入队 task_id={} execution_id={} reset_count={}",
        task_id,
        result.execution.id,
        result.reset_count,
    )
    data = TaskCompensationResetData.from_models(
        result.task,
        result.execution,
        result.reset_count,
    )
    return ApiResponse(code=0, message="success", data=data)


@task_router.get("/submission-detail/{submission_id}", response_model=ApiResponse[TaskSubmissionData])
def get_task_submission_detail_route(
    submission_id: int,
    session: Session = Depends(get_session),
) -> ApiResponse[TaskSubmissionData]:
    """查询任务级提交保存进度。"""

    submission = session.get(TaskSubmission, submission_id)
    if submission is None:
        raise AppException(code=ErrorCode.NOT_FOUND, message="任务提交保存记录不存在", status_code=404)
    return ApiResponse(code=0, message="success", data=TaskSubmissionData.from_model(submission))


@task_router.get("/submission-current/{task_id}", response_model=ApiResponse[TaskSubmissionData | None])
def get_current_task_submission_route(
    task_id: int,
    session: Session = Depends(get_session),
) -> ApiResponse[TaskSubmissionData | None]:
    """查询任务当前排队或运行中的提交保存进度。"""

    _get_task_or_raise(session, task_id)
    submission = TaskSubmissionJobService(session).get_active_submission(task_id)
    data = TaskSubmissionData.from_model(submission) if submission else None
    return ApiResponse(code=0, message="success", data=data)


@task_item_router.get("/list", response_model=ApiResponse[TaskItemListData])
def list_task_items_route(
        task_id: Annotated[int, Query(gt=0)],
        media_type: Annotated[str | None, Query()] = None,
        status: Annotated[str | None, Query()] = None,
        confirm_state: Annotated[str | None, Query()] = None,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=200)] = 20,
        session: Session = Depends(get_session),
) -> ApiResponse[TaskItemListData]:
    """分页查询任务项列表。"""

    _get_task_or_raise(session, task_id)
    query = select(TaskItem).where(TaskItem.task_id == task_id)

    if media_type == "image":
        query = query.where(TaskItem.file_bmp == 1)
    elif media_type == "video":
        query = query.where(TaskItem.file_bmp == 2)

    if status:
        query = query.where(TaskItem.status == status)
    if confirm_state:
        query = query.where(TaskItem.confirm_state == confirm_state)

    rows = session.exec(query.order_by(TaskItem.id.desc())).all()
    items = [TaskItemListRow.from_model(row) for row in rows]
    start = (page - 1) * page_size
    end = start + page_size
    data = TaskItemListData(items=items[start:end], total=len(items), page=page, page_size=page_size)
    return ApiResponse(code=0, message="success", data=data)


@task_item_router.get("/detail/{task_item_id}", response_model=ApiResponse[TaskItemDetailData])
def get_task_item_detail_route(task_item_id: int, session: Session = Depends(get_session)) -> ApiResponse[
    TaskItemDetailData]:
    """查询任务项详情。"""

    task_item = _get_task_item_or_raise(session, task_item_id)
    data_rows = session.exec(
        select(TaskItemData).where(TaskItemData.task_item_id == task_item_id).order_by(TaskItemData.id.desc())
    ).all()
    source_size = resolve_task_item_source_size(task_item, data_rows)
    review_rows = [TaskItemReviewRow.from_model(row, source_size=source_size) for row in data_rows]
    data = TaskItemDetailData.from_model(task_item, review_rows=review_rows)
    return ApiResponse(code=0, message="success", data=data)


@task_item_router.post("/action-confirm", response_model=ApiResponse[TaskItemActionData])
def confirm_task_item_route(payload: TaskItemActionRequest, session: Session = Depends(get_session)) -> ApiResponse[
    TaskItemActionData]:
    """确认任务项。"""

    task_item = _get_task_item_or_raise(session, payload.task_item_id)
    _ensure_task_item_can_be_manually_reviewed(session, task_item, "确认")
    now = datetime.now()
    task_item.confirm_state = TaskItemConfirmState.CONFIRMED.value
    task_item.confirmed_at = now
    task_item.status = TaskItemStatus.CONFIRMED.value
    task_item.updated_at = now
    session.add(task_item)
    session.commit()
    session.refresh(task_item)
    refresh_task_finish_state(session, task_item.task_id, now=now)
    logger.info("任务项确认完成 task_item_id={} confirm_state={}", task_item.id, task_item.confirm_state)
    data = TaskItemActionData(id=task_item.id or 0, confirm_state=task_item.confirm_state)
    return ApiResponse(code=0, message="success", data=data)


@task_item_router.post("/action-reject", response_model=ApiResponse[TaskItemActionData])
def reject_task_item_route(payload: TaskItemRejectRequest, session: Session = Depends(get_session)) -> ApiResponse[
    TaskItemActionData]:
    """拒绝任务项。"""

    task_item = _get_task_item_or_raise(session, payload.task_item_id)
    _ensure_task_item_can_be_manually_reviewed(session, task_item, "跳过")
    now = datetime.now()
    task_item.confirm_state = TaskItemConfirmState.SKIPPED.value
    task_item.status = TaskItemStatus.SKIPPED.value
    task_item.updated_at = now
    session.add(task_item)
    session.commit()
    session.refresh(task_item)
    refresh_task_finish_state(session, task_item.task_id, now=now)
    logger.info("任务项跳过完成 task_item_id={} reason_length={}", task_item.id, len(payload.reason))
    data = TaskItemActionData(id=task_item.id or 0, confirm_state=task_item.confirm_state)
    return ApiResponse(code=0, message="success", data=data)


@task_item_router.post("/action-update-row", response_model=ApiResponse[TaskItemActionData])
def update_task_item_review_row_route(
        payload: TaskItemReviewRowUpdateRequest,
        session: Session = Depends(get_session),
) -> ApiResponse[
    TaskItemActionData]:
    """更新任务项复核明细。"""

    task_item = _get_task_item_or_raise(session, payload.task_item_id)
    if task_item.status == TaskItemStatus.FINISHED.value:
        raise AppException(
            code=ErrorCode.PARAM_INVALID,
            message="已完成提交的任务项不能修改复核明细",
            status_code=400,
        )

    data_row = session.get(TaskItemData, payload.task_item_data_id)
    if data_row is None or data_row.task_item_id != task_item.id:
        raise AppException(
            code=ErrorCode.NOT_FOUND,
            message="任务项复核明细不存在",
            status_code=404,
        )

    now = datetime.now()
    data_row.status = payload.status
    data_row.llm_name = payload.llm_name.strip() if payload.llm_name else None
    session.add(data_row)
    session.flush()

    data_rows = session.exec(
        select(TaskItemData).where(TaskItemData.task_item_id == task_item.id)
    ).all()
    apply_task_item_review_state(task_item, data_rows, now)
    if task_item.confirm_state == TaskItemConfirmState.PENDING.value:
        task_item.confirmed_at = None
    session.add(task_item)
    session.commit()
    session.refresh(task_item)
    refresh_task_finish_state(session, task_item.task_id, now=now)
    logger.info(
        "任务项复核明细更新完成 task_item_id={} task_item_data_id={} status={}",
        task_item.id,
        data_row.id,
        data_row.status,
    )
    data = TaskItemActionData(id=task_item.id or 0, confirm_state=task_item.confirm_state)
    return ApiResponse(code=0, message="success", data=data)


@task_item_router.post("/action-re-recognize-batch", response_model=ApiResponse[TaskItemReRecognitionBatchData])
def re_recognize_task_items_batch_route(
        payload: TaskItemReRecognitionBatchRequest,
        session: Session = Depends(get_session),
) -> ApiResponse[TaskItemReRecognitionBatchData]:
    """批量重新识别任务项。"""

    service = TaskItemReRecognitionService(session)
    batch = service.create_batch(
        scope=payload.scope,
        task_id=payload.task_id,
        task_item_ids=payload.task_item_ids,
    )
    batch = service.enqueue_batch(batch)
    logger.info(
        "批量重新识别已入队 batch_id={} task_id={} scope={} total_count={}",
        batch.id,
        batch.task_id,
        batch.scope,
        batch.total_count,
    )
    return ApiResponse(code=0, message="success", data=TaskItemReRecognitionBatchData.from_model(batch))


@task_item_router.get(
    "/re-recognize-batch-detail/{batch_id}",
    response_model=ApiResponse[TaskItemReRecognitionBatchData],
)
def get_re_recognition_batch_detail_route(
        batch_id: int,
        session: Session = Depends(get_session),
) -> ApiResponse[TaskItemReRecognitionBatchData]:
    """查询批量重新识别进度。"""

    batch = session.get(TaskItemRecognitionBatch, batch_id)
    if batch is None:
        raise AppException(code=ErrorCode.NOT_FOUND, message="批量重新识别记录不存在", status_code=404)
    return ApiResponse(code=0, message="success", data=TaskItemReRecognitionBatchData.from_model(batch))


def _serialize_filters(filters: TaskFiltersPayload) -> str:
    """把任务筛选条件序列化为数据库中的 JSON 字符串。"""

    return filters.model_dump_json()


def _deserialize_filters(raw: str | None) -> TaskFiltersPayload:
    """从数据库 JSON 字符串恢复筛选条件，空值兼容为默认筛选。"""

    if not raw:
        return TaskFiltersPayload()

    return TaskFiltersPayload.model_validate(json.loads(raw))


def _resolve_task_download_dirs(task_items: list[TaskItem]) -> set[Path]:
    """从 TaskItem 文件路径中提取可安全删除的任务下载目录。"""

    task_files_dir = (get_settings().data_dir / "task_files").resolve()
    download_dirs: set[Path] = set()

    for task_item in task_items:
        if not task_item.file_path:
            continue

        file_path = Path(task_item.file_path).expanduser().resolve()
        if not file_path.is_relative_to(task_files_dir):
            logger.warning(
                "跳过任务文件目录删除，路径不在任务文件目录内 task_id={} task_item_id={} file_path={}",
                task_item.task_id,
                task_item.id,
                task_item.file_path,
            )
            continue

        parent_dir = file_path.parent
        if parent_dir != task_files_dir:
            download_dirs.add(parent_dir)

    return download_dirs


def _delete_task_download_dirs(task_id: int, download_dirs: set[Path]) -> int:
    """删除任务下载目录，失败时记录日志并继续。"""

    deleted_count = 0
    for download_dir in sorted(download_dirs):
        if not download_dir.exists():
            continue
        if not download_dir.is_dir():
            logger.warning(
                "跳过任务文件目录删除，目标不是目录 task_id={} path={}",
                task_id,
                download_dir,
            )
            continue

        try:
            shutil.rmtree(download_dir)
            deleted_count += 1
            logger.info("任务下载目录已删除 task_id={} path={}", task_id, download_dir)
        except OSError:
            logger.exception("任务下载目录删除失败 task_id={} path={}", task_id, download_dir)

    return deleted_count


def _get_task_or_raise(session: Session, task_id: int) -> Task:
    """按 ID 查询任务，不存在时抛出统一异常。"""

    task = session.get(Task, task_id)
    if task is None:
        raise AppException(
            code=ErrorCode.NOT_FOUND,
            message="任务不存在",
            status_code=404,
        )
    return task


def _get_task_item_or_raise(session: Session, task_item_id: int) -> TaskItem:
    """按 ID 查询任务项，不存在时抛出统一异常。"""

    task_item = session.get(TaskItem, task_item_id)
    if task_item is None:
        raise AppException(
            code=ErrorCode.NOT_FOUND,
            message="任务项不存在",
            status_code=404,
        )
    return task_item


def _count_compensation_limited_items(session: Session, task_ids: list[int]) -> dict[int, int]:
    """按任务统计达到补偿上限且仍失败的任务项数量。"""

    if not task_ids:
        return {}

    rows = session.exec(
        select(TaskItem)
        .where(TaskItem.task_id.in_(task_ids))
        .where(TaskItem.compensation_count >= TASK_ITEM_COMPENSATION_MAX_ATTEMPTS)
        .where(
            or_(
                (TaskItem.down_state == False)  # noqa: E712
                & (TaskItem.down_error != None),  # noqa: E711
                TaskItem.llm_state == TaskItemLlmState.FAIL.value,
            )
        )
        .where(TaskItem.remote_state != TaskItemRemoteState.SUCCESS.value)
        .where(TaskItem.confirm_state != TaskItemConfirmState.SKIPPED.value)
        .where(TaskItem.status.notin_({TaskItemStatus.SKIPPED.value, TaskItemStatus.FINISHED.value}))
    ).all()
    counts: dict[int, int] = {}
    for row in rows:
        counts[row.task_id] = counts.get(row.task_id, 0) + 1
    return counts


def _get_active_execution(session: Session, task_id: int) -> TaskExecution | None:
    """查询任务当前排队或运行中的执行实例。"""

    return session.exec(
        select(TaskExecution)
        .where(TaskExecution.task_id == task_id)
        .where(TaskExecution.status.in_(ACTIVE_EXECUTION_STATUSES))
        .order_by(TaskExecution.created_at.desc())
    ).first()


def _ensure_task_can_be_deleted(session: Session, task_id: int, task: Task) -> None:
    """校验任务当前是否允许删除。"""

    if _get_active_execution(session, task_id) is not None or _is_task_in_execution_stage(task):
        raise AppException(
            code=ErrorCode.RESOURCE_BUSY,
            message="任务正在执行，不能删除",
            status_code=409,
        )


def _ensure_task_can_be_modified(session: Session, task_id: int) -> None:
    """校验任务当前是否允许修改关键配置。"""

    task = _get_task_or_raise(session, task_id)
    if _get_active_execution(session, task_id) is not None or _is_task_in_execution_stage(task):
        raise AppException(
            code=ErrorCode.RESOURCE_BUSY,
            message="任务正在执行，不能修改关键配置",
            status_code=409,
        )


def _is_task_in_execution_stage(task: Task) -> bool:
    """判断任务聚合状态是否处于执行阶段。"""

    if task.execution_status == "创建":
        return task.last_run_started_at is not None
    return task.execution_status in {"数据加载", "下载", "模型识别"}


def _ensure_task_item_can_be_manually_reviewed(
        session: Session,
        task_item: TaskItem,
        action_name: str,
) -> None:
    """校验 TaskItem 是否仍需要人工确认或跳过。"""

    if task_item.confirm_state != TaskItemConfirmState.PENDING.value:
        raise AppException(
            code=ErrorCode.PARAM_INVALID,
            message=f"任务项当前状态不能{action_name}",
            status_code=400,
        )

    data_rows = session.exec(
        select(TaskItemData).where(TaskItemData.task_item_id == task_item.id)
    ).all()
    if data_rows and all(row.status == TaskItemDataStatus.DEFAULT.value for row in data_rows):
        raise AppException(
            code=ErrorCode.PARAM_INVALID,
            message=f"结果一致的任务项已自动跳过，不能人工{action_name}",
            status_code=400,
        )
