"""任务与任务项服务。"""

from __future__ import annotations

import json
from datetime import datetime

from loguru import logger
from sqlmodel import Session, select

from aiSelfTest.exceptions import AppException, ErrorCode
from aiSelfTest.models.task import Task, TaskItem, TaskItemData, TaskItemDataStatus
from aiSelfTest.schemas.task import (
    TaskActionData,
    TaskCreateRequest,
    TaskDeleteData,
    TaskFiltersPayload,
    TaskItemActionData,
    TaskItemDeleteRequest,
    TaskItemDetailData,
    TaskItemListData,
    TaskItemListRow,
    TaskItemRejectRequest,
    TaskItemReviewRow,
    TaskItemActionRequest,
    TaskListData,
    TaskResponse,
    TaskUpdateRequest,
)


def list_tasks(session: Session) -> TaskListData:
    """查询任务列表。"""

    rows = session.exec(select(Task).order_by(Task.id.desc())).all()
    logger.debug("任务列表查询完成 count={}", len(rows))
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
        auto_confirm=payload.auto_confirm,
        active=False,
    )
    session.add(task)
    session.commit()
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
    logger.debug("任务详情查询完成: task_id={}, execution_status={}", task_id, task.execution_status)
    return TaskResponse.from_model(task, filters=_deserialize_filters(task.filters_json))


def update_task(
    session: Session,
    task_id: int,
    payload: TaskUpdateRequest,
) -> TaskResponse:
    """更新任务。"""

    task = _get_task_or_raise(session, task_id)
    task.name = payload.name
    task.client_id = payload.client_id
    task.config_id = payload.config_id
    task.interval = payload.interval_hours
    task.execution_mode = payload.execution_mode
    task.auto_confirm = payload.auto_confirm
    task.filters_json = _serialize_filters(payload.filters)
    task.updated_at = datetime.now()

    session.add(task)
    session.commit()
    session.refresh(task)
    logger.info(
        "更新任务成功: task_id={}, client_id={}, config_id={}, execution_mode={}, auto_confirm={}",
        task.id,
        task.client_id,
        task.config_id,
        task.execution_mode,
        task.auto_confirm,
    )
    _sync_scheduler(task.id)
    logger.info(
        "任务更新完成 task_id={} name={} active={} interval={} execution_mode={}",
        task.id,
        task.name,
        task.active,
        task.interval,
        task.execution_mode,
    )
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

    logger.info("删除任务成功: task_id={}, task_item_count={}", task_id, len(task_item_ids))
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
    logger.info("任务已启动: task_id={}, execution_status={}", task.id, task.execution_status)
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
    logger.info("任务已停止: task_id={}, execution_status={}", task.id, task.execution_status)
    _sync_scheduler(task.id)
    logger.info("任务已停止 task_id={} execution_status={}", task.id, task.execution_status)
    return TaskActionData(id=task.id or 0, active=task.active, execution_status=task.execution_status)


def run_task_once(session: Session, task_id: int) -> TaskActionData:
    """立即执行一次任务。"""

    from aiSelfTest.services.task_execution import run_task_execution

    run_task_execution(session, task_id)
    task = _get_task_or_raise(session, task_id)
    logger.info("任务手动执行完成 task_id={} execution_status={}", task.id, task.execution_status)
    return TaskActionData(id=task.id or 0, active=task.active, execution_status=task.execution_status)


def list_task_items(
    session: Session,
    *,
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
    logger.debug(
        "任务项列表查询完成 task_id={} total={} page={} page_size={}",
        task_id,
        len(items),
        page,
        page_size,
    )
    return TaskItemListData(items=paged_items, total=len(items), page=page, page_size=page_size)


def get_task_item_detail(session: Session, task_item_id: int) -> TaskItemDetailData:
    """查询 TaskItem 详情。"""

    task_item = _get_task_item_or_raise(session, task_item_id)
    data_rows = session.exec(
        select(TaskItemData).where(TaskItemData.task_item_id == task_item_id).order_by(TaskItemData.id.desc())
    ).all()
    review_rows = [TaskItemReviewRow.from_model(row) for row in data_rows]
    logger.debug(
        "任务项详情查询完成: task_item_id={}, review_row_count={}",
        task_item_id,
        len(review_rows),
    )
    return TaskItemDetailData.from_model(task_item, review_rows=review_rows)


def confirm_task_item(
    session: Session,
    payload: TaskItemActionRequest,
) -> TaskItemActionData:
    """确认 TaskItem。"""

    task_item = _get_task_item_or_raise(session, payload.task_item_id)
    task_item.confirm_state = "manual_confirmed"
    task_item.confirmed_at = datetime.now()
    task_item.updated_at = datetime.now()
    session.add(task_item)
    session.commit()
    session.refresh(task_item)
    logger.info("任务项确认完成 task_item_id={} confirm_state={}", task_item.id, task_item.confirm_state)
    return TaskItemActionData(id=task_item.id or 0, confirm_state=task_item.confirm_state)


def reject_task_item(
    session: Session,
    payload: TaskItemRejectRequest,
) -> TaskItemActionData:
    """拒绝 TaskItem。"""

    task_item = _get_task_item_or_raise(session, payload.task_item_id)
    task_item.confirm_state = "rejected"
    task_item.updated_at = datetime.now()
    session.add(task_item)
    session.commit()
    session.refresh(task_item)
    logger.info("任务项拒绝完成 task_item_id={} reason_length={}", task_item.id, len(payload.reason))
    return TaskItemActionData(id=task_item.id or 0, confirm_state=task_item.confirm_state)


def delete_task_item_rows(
    session: Session,
    payload: TaskItemDeleteRequest,
) -> TaskItemActionData:
    """删除复核层对象，但不删除源 TaskItem。"""

    task_item = _get_task_item_or_raise(session, payload.task_item_id)
    if payload.task_item_data_ids:
        rows = session.exec(
            select(TaskItemData).where(TaskItemData.id.in_(payload.task_item_data_ids))
        ).all()
        for row in rows:
            row.status = TaskItemDataStatus.DELETE.value
            session.add(row)
    task_item.updated_at = datetime.now()
    session.add(task_item)
    session.commit()
    session.refresh(task_item)
    logger.info(
        "任务项复核明细删除完成 task_item_id={} requested_detail_count={}",
        task_item.id,
        len(payload.task_item_data_ids),
    )
    return TaskItemActionData(id=task_item.id or 0, confirm_state=task_item.confirm_state)


def submit_task_item(
    session: Session,
    payload: TaskItemActionRequest,
) -> TaskItemActionData:
    """提交 TaskItem。"""

    task_item = _get_task_item_or_raise(session, payload.task_item_id)
    if task_item.confirm_state == "rejected":
        raise AppException(
            code=ErrorCode.PARAM_INVALID,
            message="已拒绝的任务项不能提交",
            status_code=400,
        )

    task_item.remote_state = "success"
    task_item.remote_at = datetime.now()
    task_item.updated_at = datetime.now()
    session.add(task_item)
    session.commit()
    session.refresh(task_item)
    logger.info("任务项提交完成 task_item_id={} remote_state={}", task_item.id, task_item.remote_state)
    return TaskItemActionData(id=task_item.id or 0, remote_state=task_item.remote_state)


def get_legacy_task_detail(session: Session, task_id: int) -> dict[str, object]:
    """旧 DataQuery 页面兼容详情。"""

    task = _get_task_or_raise(session, task_id)
    filters = _deserialize_filters(task.filters_json)
    logger.debug("构建旧任务详情 task_id={}", task_id)
    media_types = filters.media_types
    if media_types == ["image"]:
        file_bmp = "image"
    elif media_types == ["video"]:
        file_bmp = "video"
    else:
        file_bmp = "all"
    upload_type = str(filters.upload_types[0]) if filters.upload_types else "all"
    id_type = str(filters.identify_source[0]) if filters.identify_source else "all"

    return {
        "id": task.id or 0,
        "name": task.name,
        "filters": {
            "classifyList": filters.classify_list,
            "keyword": filters.keyword,
            "spName": filters.sp_name,
            "startTime": filters.start_at,
            "endTime": filters.end_at,
            "fileBmp": file_bmp,
            "uploadType": upload_type,
            "idType": id_type,
            "size": 50,
            "current": 1,
        },
    }


def query_legacy_task_data(session: Session, task_id: int) -> dict[str, object]:
    """旧 DataQuery 查询结果兼容层。"""

    _get_task_or_raise(session, task_id)
    rows = session.exec(select(TaskItem).where(TaskItem.task_id == task_id).order_by(TaskItem.id.desc())).all()
    logger.debug("旧任务数据查询完成 task_id={} count={}", task_id, len(rows))
    results = [
        {
            "id": row.id or 0,
            "name": row.name,
            "spNameList": row.sp_name_list,
            "classify": row.classify,
            "fileTime": row.created_at.strftime("%Y-%m-%d %H:%M:%S") if row.created_at else "--",
            "fileUrl": row.file_url,
            "coverUrl": row.file_url,
            "mediaType": "video" if row.file_bmp == 2 else "image",
            "mediaUrl": row.file_url,
            "deName": row.device_name,
        }
        for row in rows
    ]
    return {"results": results}


def run_legacy_task_execute(session: Session, task_id: int) -> dict[str, bool]:
    """旧 execute 兼容入口。"""

    run_task_once(session, task_id)
    logger.info("旧任务执行入口完成 task_id={}", task_id)
    return {"ok": True}


def list_completed_review_tasks(session: Session) -> list[dict[str, int | str]]:
    """查询可复核任务列表（兼容层）。"""

    tasks = session.exec(select(Task).where(Task.execution_status == "结束").order_by(Task.id.desc())).all()
    logger.debug("已完成复核任务查询完成 count={}", len(tasks))
    return [
        {"id": task.id or 0, "name": task.name}
        for task in tasks
        if session.exec(select(TaskItem).where(TaskItem.task_id == task.id)).first() is not None
    ]
    logger.debug("兼容复核任务列表查询完成: count={}", len(results))
    return results


def list_review_items(session: Session, task_id: int) -> list[dict[str, object]]:
    """查询复核项列表（兼容层）。"""

    task = _get_task_or_raise(session, task_id)
    items = session.exec(select(TaskItem).where(TaskItem.task_id == task_id).order_by(TaskItem.id.desc())).all()
    logger.debug("复核项列表查询完成 task_id={} count={}", task_id, len(items))
    return [_build_review_item(task, item, session) for item in items]


def confirm_review_items(session: Session, ids: list[str]) -> dict[str, object]:
    """批量确认复核项（兼容层）。"""

    success_count = 0
    failure_count = 0
    results: list[dict[str, str]] = []

    for raw_id in ids:
        try:
            task_item_id = int(raw_id)
            confirm_task_item(session, TaskItemActionRequest(task_item_id=task_item_id))
            success_count += 1
            results.append({"status": "success", "message": f"复核项 {task_item_id} 确认成功"})
        except Exception as exc:  # noqa: BLE001
            failure_count += 1
            logger.warning("复核项确认失败 raw_id={} error={}", raw_id, exc)
            results.append({"status": "failed", "message": str(exc)})

    logger.info(
        "兼容复核项批量确认完成: success_count={}, failure_count={}",
        success_count,
        failure_count,
    )
    return {
        "successCount": success_count,
        "failureCount": failure_count,
        "results": results,
    }


def delete_review_item(session: Session, task_item_id: int) -> None:
    """删除复核层对象（兼容层）。"""

    task_item = _get_task_item_or_raise(session, task_item_id)
    data_rows = session.exec(
        select(TaskItemData).where(TaskItemData.task_item_id == task_item_id)
    ).all()
    delete_task_item_rows(
        session,
        TaskItemDeleteRequest(
            task_item_id=task_item.id or 0,
            task_item_data_ids=[row.id or 0 for row in data_rows if row.id is not None],
        ),
    )
    logger.info("复核项删除完成 task_item_id={} detail_count={}", task_item_id, len(data_rows))


def delete_review_items(session: Session, ids: list[str]) -> None:
    """批量删除复核层对象（兼容层）。"""

    for raw_id in ids:
        delete_review_item(session, int(raw_id))
    logger.info("复核项批量删除完成 count={}", len(ids))


def _serialize_filters(filters: TaskFiltersPayload) -> str:
    """把任务筛选条件序列化为数据库中的 JSON 字符串。"""

    return filters.model_dump_json()


def _deserialize_filters(raw: str | None) -> TaskFiltersPayload:
    """从数据库 JSON 字符串恢复筛选条件，空值兼容为默认筛选。"""

    if not raw:
        return TaskFiltersPayload()
    return TaskFiltersPayload.model_validate(json.loads(raw))


def _build_review_item(task: Task, task_item: TaskItem, session: Session) -> dict[str, object]:
    """构造旧复核页面消费的一行任务项数据。"""

    data_rows = session.exec(
        select(TaskItemData).where(TaskItemData.task_item_id == task_item.id).order_by(TaskItemData.id.desc())
    ).all()
    review_rows = [_build_compat_review_row(row) for row in data_rows]
    submit_count = len([row for row in review_rows if bool(row["willSubmit"])])
    excluded_count = len([row for row in review_rows if row["decision"] == "exclude"])
    media_type = "video" if task_item.file_bmp == 2 else "image"
    ai_values = [str(row["aiName"]) for row in review_rows if row["aiName"]]
    original_values = [str(row["originalName"]) for row in review_rows if row["originalName"]]
    return {
        "id": task_item.id or 0,
        "taskName": task.name,
        "mediaType": media_type,
        "imageUrl": task_item.file_url,
        "mediaUrl": task_item.file_url,
        "originalResult": "、".join(original_values),
        "aiResult": "、".join(ai_values),
        "reviewRows": review_rows,
        "submitCount": submit_count,
        "excludedCount": excluded_count,
        "willSubmitEmptyArray": submit_count == 0,
        "remoteError": task_item.remote_error,
    }


def _build_compat_review_row(row: TaskItemData) -> dict[str, object]:
    """把 TaskItemData 转换为旧复核页兼容行。"""

    if row.status == TaskItemDataStatus.DELETE.value:
        decision = "exclude"
    elif row.llm_name and row.name and row.llm_name.strip() == row.name.strip():
        decision = "keep"
    elif row.llm_name:
        decision = "rename"
    else:
        decision = "exclude"

    return {
        "recordId": row.id or 0,
        "originalName": row.name,
        "aiName": row.llm_name,
        "decision": decision,
        "willSubmit": decision != "exclude" and bool(row.llm_name),
        "groundingStatus": "structured",
    }


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


def _sync_scheduler(task_id: int | None) -> None:
    """同步单进程调度器；缺全局调度器时安全跳过。"""

    if task_id is None:
        return
    from aiSelfTest.services.task_scheduler import sync_global_task_scheduler

    sync_global_task_scheduler(task_id)
