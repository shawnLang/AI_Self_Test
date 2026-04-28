"""任务与任务项路由。"""

from __future__ import annotations

from aiSelfTest.database import get_session
from aiSelfTest.schemas.common import ApiResponse
from aiSelfTest.schemas.task import (
    TaskActionData,
    TaskCreateRequest,
    TaskDeleteData,
    TaskItemActionData,
    TaskItemActionRequest,
    TaskItemDeleteRequest,
    TaskItemDetailData,
    TaskItemListData,
    TaskItemRejectRequest,
    TaskListData,
    TaskResponse,
    TaskUpdateRequest,
)
from aiSelfTest.services.task import (
    confirm_task_item,
    create_task,
    delete_task,
    delete_task_item_rows,
    get_task_detail,
    get_legacy_task_detail,
    get_task_item_detail,
    list_task_items,
    list_tasks,
    query_legacy_task_data,
    reject_task_item,
    run_legacy_task_execute,
    run_task_once,
    start_task,
    stop_task,
    submit_task_item,
    update_task,
)
from fastapi import APIRouter, Depends, Query, status
from loguru import logger
from sqlmodel import Session

task_router = APIRouter(prefix="/tasks")
task_item_router = APIRouter(prefix="/task-items")


@task_router.get("/list", response_model=ApiResponse[TaskListData])
def list_tasks_route(session: Session = Depends(get_session)) -> ApiResponse[TaskListData]:
    """查询任务列表。"""

    logger.info("API 请求任务列表")
    return ApiResponse(code=0, message="success", data=list_tasks(session))


@task_router.post("/create", response_model=ApiResponse[TaskResponse], status_code=status.HTTP_201_CREATED)
def create_task_route(payload: TaskCreateRequest, session: Session = Depends(get_session)) -> ApiResponse[TaskResponse]:
    """创建任务。"""

    logger.info(
        "API 请求创建任务: name={}, client_id={}, config_id={}, execution_mode={}",
        payload.name,
        payload.client_id,
        payload.config_id,
        payload.execution_mode,
    )
    return ApiResponse(code=0, message="success", data=create_task(session, payload))


@task_router.get("/detail/{task_id}", response_model=ApiResponse[TaskResponse])
def get_task_detail_route(task_id: int, session: Session = Depends(get_session)) -> ApiResponse[TaskResponse]:
    """查询任务详情。"""

    logger.info("API 请求任务详情: task_id={}", task_id)
    return ApiResponse(code=0, message="success", data=get_task_detail(session, task_id))


@task_router.post("/update/{task_id}", response_model=ApiResponse[TaskResponse])
def update_task_route(task_id: int, payload: TaskUpdateRequest, session: Session = Depends(get_session)) -> ApiResponse[
    TaskResponse]:
    """更新任务。"""

    logger.info(
        "API 请求更新任务: task_id={}, name={}, execution_mode={}",
        task_id,
        payload.name,
        payload.execution_mode,
    )
    return ApiResponse(code=0, message="success", data=update_task(session, task_id, payload))


@task_router.delete("/delete/{task_id}", response_model=ApiResponse[TaskDeleteData])
def delete_task_route(task_id: int, session: Session = Depends(get_session)) -> ApiResponse[TaskDeleteData]:
    """删除任务及关联任务项。"""

    logger.info("API 请求删除任务: task_id={}", task_id)
    return ApiResponse(code=0, message="success", data=delete_task(session, task_id))


@task_router.post("/action-start/{task_id}", response_model=ApiResponse[TaskActionData])
def start_task_route(task_id: int, session: Session = Depends(get_session)) -> ApiResponse[TaskActionData]:
    """启动任务自动调度。"""

    logger.info("API 请求启动任务: task_id={}", task_id)
    return ApiResponse(code=0, message="success", data=start_task(session, task_id))


@task_router.post("/action-stop/{task_id}", response_model=ApiResponse[TaskActionData])
def stop_task_route(task_id: int, session: Session = Depends(get_session)) -> ApiResponse[TaskActionData]:
    """停止任务自动调度。"""

    logger.info("API 请求停止任务: task_id={}", task_id)
    return ApiResponse(code=0, message="success", data=stop_task(session, task_id))


@task_router.post("/action-run/{task_id}", response_model=ApiResponse[TaskActionData])
def run_task_route(task_id: int, session: Session = Depends(get_session)) -> ApiResponse[TaskActionData]:
    """立即执行一次任务。"""

    logger.info("API 请求立即执行任务: task_id={}", task_id)
    return ApiResponse(code=0, message="success", data=run_task_once(session, task_id))


@task_router.get("/{task_id}")
def get_legacy_task_detail_route(task_id: int, session: Session = Depends(get_session)) -> dict[str, object]:
    """查询旧 DataQuery 页面兼容任务详情。"""

    logger.info("API 请求兼容任务详情: task_id={}", task_id)
    return get_legacy_task_detail(session, task_id)


@task_router.post("/{task_id}/query-data")
def query_legacy_task_data_route(task_id: int, session: Session = Depends(get_session)) -> dict[str, object]:
    """查询旧 DataQuery 页面兼容数据。"""

    logger.info("API 请求兼容任务数据查询: task_id={}", task_id)
    return query_legacy_task_data(session, task_id)


@task_router.post("/{task_id}/execute")
def run_legacy_task_execute_route(task_id: int, session: Session = Depends(get_session)) -> dict[str, bool]:
    """执行旧 DataQuery 页面兼容任务。"""

    logger.info("API 请求兼容任务执行: task_id={}", task_id)
    return run_legacy_task_execute(session, task_id)


@task_item_router.get("/list", response_model=ApiResponse[TaskItemListData])
def list_task_items_route(
        task_id: int = Query(gt=0),
        media_type: str | None = Query(default=None),
        status: str | None = Query(default=None),
        confirm_state: str | None = Query(default=None),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=20, ge=1, le=200),
        session: Session = Depends(get_session),
) -> ApiResponse[TaskItemListData]:
    """分页查询任务项列表。"""

    logger.info(
        "API 请求任务项列表: task_id={}, media_type={}, status={}, confirm_state={}, page={}, page_size={}",
        task_id,
        media_type,
        status,
        confirm_state,
        page,
        page_size,
    )
    data = list_task_items(
        session,
        task_id=task_id,
        media_type=media_type,
        status=status,
        confirm_state=confirm_state,
        page=page,
        page_size=page_size,
    )
    return ApiResponse(code=0, message="success", data=data)


@task_item_router.get("/detail/{task_item_id}", response_model=ApiResponse[TaskItemDetailData])
def get_task_item_detail_route(task_item_id: int, session: Session = Depends(get_session)) -> ApiResponse[
    TaskItemDetailData]:
    """查询任务项详情。"""

    logger.info("API 请求任务项详情: task_item_id={}", task_item_id)
    return ApiResponse(code=0, message="success", data=get_task_item_detail(session, task_item_id))


@task_item_router.post("/action-confirm", response_model=ApiResponse[TaskItemActionData])
def confirm_task_item_route(payload: TaskItemActionRequest, session: Session = Depends(get_session)) -> ApiResponse[
    TaskItemActionData]:
    """确认任务项。"""

    logger.info("API 请求确认任务项: task_item_id={}", payload.task_item_id)
    return ApiResponse(code=0, message="success", data=confirm_task_item(session, payload))


@task_item_router.post("/action-reject", response_model=ApiResponse[TaskItemActionData])
def reject_task_item_route(payload: TaskItemRejectRequest, session: Session = Depends(get_session)) -> ApiResponse[
    TaskItemActionData]:
    """拒绝任务项。"""

    logger.info("API 请求拒绝任务项: task_item_id={}", payload.task_item_id)
    return ApiResponse(code=0, message="success", data=reject_task_item(session, payload))


@task_item_router.post("/action-delete", response_model=ApiResponse[TaskItemActionData])
def delete_task_item_route(payload: TaskItemDeleteRequest, session: Session = Depends(get_session)) -> ApiResponse[
    TaskItemActionData]:
    """删除任务项复核数据。"""

    logger.info(
        "API 请求删除任务项复核数据: task_item_id={}, row_count={}",
        payload.task_item_id,
        len(payload.task_item_data_ids),
    )
    return ApiResponse(code=0, message="success", data=delete_task_item_rows(session, payload))


@task_item_router.post("/action-submit", response_model=ApiResponse[TaskItemActionData])
def submit_task_item_route(payload: TaskItemActionRequest, session: Session = Depends(get_session)) -> ApiResponse[
    TaskItemActionData]:
    """提交任务项到远端。"""

    logger.info("API 请求提交任务项: task_item_id={}", payload.task_item_id)
    return ApiResponse(code=0, message="success", data=submit_task_item(session, payload))
