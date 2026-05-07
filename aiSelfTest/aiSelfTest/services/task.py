"""任务与任务项服务。"""

from __future__ import annotations

import json
from datetime import datetime

from aiSelfTest.exceptions import AppException, ErrorCode
from aiSelfTest.models.task import (
    Task,
    TaskItem,
    TaskItemConfirmState,
    TaskItemData,
    TaskItemDataStatus,
    TaskItemRemoteState,
    TaskItemStatus,
)
from aiSelfTest.schemas.task import (
    TaskActionData,
    TaskCreateRequest,
    TaskDeleteData,
    TaskFiltersPayload,
    TaskItemActionData,
    TaskItemBatchActionData,
    TaskItemBatchActionRow,
    TaskItemDetailData,
    TaskItemListData,
    TaskItemListRow,
    TaskItemRejectRequest,
    TaskItemReviewRow,
    TaskItemReviewRowUpdateRequest,
    TaskItemActionRequest,
    TaskItemSubmitTaskRequest,
    TaskListData,
    TaskResponse,
    TaskUpdateRequest,
    resolve_task_item_source_size,
)
from aiSelfTest.services.task_execution import run_task_execution
from aiSelfTest.services.task_review import apply_task_item_review_state, refresh_task_finish_state
from aiSelfTest.services.task_scheduler import sync_global_task_scheduler
from aiSelfTest.services.task_submission import submit_task_item_outputs
from loguru import logger
from sqlmodel import Session, select


def list_tasks(session: Session) -> TaskListData:
    """查询任务列表。"""

    rows = session.exec(select(Task).order_by(Task.id.desc())).all()
    items = [
        TaskResponse.from_model(task, filters=_deserialize_filters(task.filters_json))
        for task in rows
    ]
    return TaskListData(items=items)


def create_task(session: Session, payload: TaskCreateRequest) -> TaskResponse:
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
    if task.auto_execute:
        run_task_execution(session, task.id or 0)
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
    return TaskResponse.from_model(task, filters=payload.filters)


def get_task_detail(session: Session, task_id: int) -> TaskResponse:
    """查询任务详情。"""

    task = _get_task_or_raise(session, task_id)
    return TaskResponse.from_model(task, filters=_deserialize_filters(task.filters_json))


def update_task(session: Session, task_id: int, payload: TaskUpdateRequest) -> TaskResponse:
    """更新任务。"""

    task = _get_task_or_raise(session, task_id)
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
    _sync_scheduler(task.id)
    return TaskResponse.from_model(task, filters=payload.filters)


def delete_task(session: Session, task_id: int) -> TaskDeleteData:
    """删除任务及关联任务项。"""

    with session.begin():
        task = _get_task_or_raise(session, task_id)
        task_items = session.exec(select(TaskItem).where(TaskItem.task_id == task_id)).all()
        task_item_ids = [row.id for row in task_items if row.id is not None]

        if task_item_ids:
            task_item_data_rows = session.exec(
                select(TaskItemData).where(TaskItemData.task_item_id.in_(task_item_ids))
            ).all()
            for row in task_item_data_rows:
                session.delete(row)
            session.flush()

        for row in task_items:
            session.delete(row)
        session.flush()

        session.delete(task)

    _sync_scheduler(task_id)
    logger.info(
        "任务删除完成 task_id={} task_item_count={} detail_count={}",
        task_id,
        len(task_items),
        len(task_item_data_rows) if task_item_ids else 0,
    )
    return TaskDeleteData(id=task_id)


def start_task(session: Session, task_id: int) -> TaskActionData:
    """启动任务。"""

    task = _get_task_or_raise(session, task_id)
    task.active = True
    task.updated_at = datetime.now()
    session.add(task)
    session.commit()
    session.refresh(task)
    _sync_scheduler(task.id)
    logger.info("任务已启动 task_id={} execution_status={}", task.id, task.execution_status)
    return TaskActionData(id=task.id or 0, active=task.active, execution_status=task.execution_status)


def stop_task(session: Session, task_id: int) -> TaskActionData:
    """停止任务。"""

    task = _get_task_or_raise(session, task_id)
    task.active = False
    task.updated_at = datetime.now()
    session.add(task)
    session.commit()
    session.refresh(task)
    _sync_scheduler(task.id)
    logger.info("任务已停止 task_id={} execution_status={}", task.id, task.execution_status)
    return TaskActionData(id=task.id or 0, active=task.active, execution_status=task.execution_status)


def run_task_once(session: Session, task_id: int) -> TaskActionData:
    """立即执行一次任务。"""

    run_task_execution(session, task_id)
    task = _get_task_or_raise(session, task_id)
    logger.info("任务手动执行完成 task_id={} execution_status={}", task.id, task.execution_status)
    return TaskActionData(id=task.id or 0, active=task.active, execution_status=task.execution_status)


def list_task_items(
        session: Session,
        task_id: int,
        media_type: str | None = None,
        status: str | None = None,
        confirm_state: str | None = None,
        page: int = 1,
        page_size: int = 20,
) -> TaskItemListData:
    """查询 TaskItem 列表。"""

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
    paged_items = items[start:end]
    return TaskItemListData(items=paged_items, total=len(items), page=page, page_size=page_size)


def get_task_item_detail(session: Session, task_item_id: int) -> TaskItemDetailData:
    """查询 TaskItem 详情。"""

    task_item = _get_task_item_or_raise(session, task_item_id)
    data_rows = session.exec(
        select(TaskItemData).where(TaskItemData.task_item_id == task_item_id).order_by(TaskItemData.id.desc())
    ).all()
    source_size = resolve_task_item_source_size(task_item, data_rows)
    review_rows = [TaskItemReviewRow.from_model(row, source_size=source_size) for row in data_rows]
    return TaskItemDetailData.from_model(task_item, review_rows=review_rows)


def confirm_task_item(session: Session, payload: TaskItemActionRequest) -> TaskItemActionData:
    """确认 TaskItem。"""

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
    return TaskItemActionData(id=task_item.id or 0, confirm_state=task_item.confirm_state)


def reject_task_item(session: Session, payload: TaskItemRejectRequest) -> TaskItemActionData:
    """跳过 TaskItem，不提交客户端但计为已处理。"""

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
    return TaskItemActionData(id=task_item.id or 0, confirm_state=task_item.confirm_state)


def update_task_item_review_row(session: Session, payload: TaskItemReviewRowUpdateRequest) -> TaskItemActionData:
    """更新 TaskItemData 复核状态与识别名称。"""

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
    return TaskItemActionData(id=task_item.id or 0, confirm_state=task_item.confirm_state)


def submit_task_item(session: Session, payload: TaskItemActionRequest) -> TaskItemActionData:
    """提交 TaskItem。"""

    task_item = _get_task_item_or_raise(session, payload.task_item_id)
    if task_item.confirm_state != TaskItemConfirmState.CONFIRMED.value:
        raise AppException(
            code=ErrorCode.PARAM_INVALID,
            message="任务项必须人工确认后才能提交",
            status_code=400,
        )
    if task_item.remote_state not in {
        TaskItemRemoteState.PENDING.value,
        TaskItemRemoteState.FAIL.value,
    }:
        raise AppException(
            code=ErrorCode.PARAM_INVALID,
            message="任务项当前远端状态不能提交",
            status_code=400,
        )

    result = submit_task_item_outputs(session, task_item)
    refresh_task_finish_state(session, task_item.task_id)
    logger.info(
        "任务项提交完成 task_item_id={} remote_state={} train_state={}",
        task_item.id,
        result.remote_state,
        result.train_state,
    )
    return TaskItemActionData(
        id=task_item.id or 0,
        remote_state=result.remote_state,
        train_state=result.train_state,
    )


def submit_task_items_by_task(
        session: Session,
        payload: TaskItemSubmitTaskRequest,
) -> TaskItemBatchActionData:
    """按任务提交所有已确认且待提交或提交失败的 TaskItem。"""

    _get_task_or_raise(session, payload.task_id)
    task_items = session.exec(
        select(TaskItem).where(
            TaskItem.task_id == payload.task_id,
            TaskItem.confirm_state == TaskItemConfirmState.CONFIRMED.value,
            TaskItem.remote_state.in_({
                TaskItemRemoteState.PENDING.value,
                TaskItemRemoteState.FAIL.value,
            }),
        ).order_by(TaskItem.id.asc())
    ).all()

    results: list[TaskItemBatchActionRow] = []
    for task_item in task_items:
        try:
            submit_task_item(session, TaskItemActionRequest(task_item_id=task_item.id or 0))
            results.append(
                TaskItemBatchActionRow(
                    id=task_item.id or 0,
                    status="success",
                    message=f"任务项 {task_item.id} 已提交远端",
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("任务级提交远端失败 task_id={} task_item_id={} error={}", payload.task_id, task_item.id, exc)
            results.append(
                TaskItemBatchActionRow(
                    id=task_item.id or 0,
                    status="failed",
                    message=str(exc),
                )
            )

    success_count = len([row for row in results if row.status == "success"])
    failure_count = len(results) - success_count
    logger.info(
        "任务级提交远端完成 task_id={} submit_count={} success_count={} failure_count={}",
        payload.task_id,
        len(task_items),
        success_count,
        failure_count,
    )
    return TaskItemBatchActionData(
        success_count=success_count,
        failure_count=failure_count,
        results=results,
    )


def _serialize_filters(filters: TaskFiltersPayload) -> str:
    """把任务筛选条件序列化为数据库中的 JSON 字符串。"""

    return filters.model_dump_json()


def _deserialize_filters(raw: str | None) -> TaskFiltersPayload:
    """从数据库 JSON 字符串恢复筛选条件，空值兼容为默认筛选。"""

    if not raw:
        return TaskFiltersPayload()
    return TaskFiltersPayload.model_validate(json.loads(raw))


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


def _sync_scheduler(task_id: int | None) -> None:
    """同步单进程调度器；缺全局调度器时安全跳过。"""

    if task_id is None:
        return

    sync_global_task_scheduler(task_id)
