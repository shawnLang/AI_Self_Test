"""客户端管理路由。"""

from __future__ import annotations

from aiSelfTest.database import get_session
from aiSelfTest.models import Client, Task, TaskItem, TaskItemData
from aiSelfTest.schemas.client import (
    ClientAuthenticateData,
    ClientCreateRequest,
    ClientDeleteData,
    ClientListData,
    ClientResponse,
    ClientUpdateRequest,
)
from aiSelfTest.schemas.common import ApiResponse, success_res
from aiSelfTest.schemas.multimodal_model import MASK_PLACEHOLDER
from aiSelfTest.services.client import (
    get_client_or_raise,
)
from aiSelfTest.services.client_auth import authenticate_client
from fastapi import APIRouter, Depends, status
from loguru import logger
from sqlmodel import Session, select, desc

router = APIRouter(prefix="/clients")


@router.get("/list", response_model=ApiResponse[ClientListData])
def list_client_route(session: Session = Depends(get_session)) -> ApiResponse[ClientListData]:
    """查询客户端列表。"""

    clients = session.exec(select(Client).order_by(desc(Client.id))).all()
    items = [ClientResponse.from_model(client) for client in clients]
    logger.info(f"api 客户端列表查询完成: count={len(clients)}")
    return success_res(data=ClientListData(items=items))


@router.get("/detail/{client_id}", response_model=ApiResponse[ClientResponse])
def get_client_detail_route(client_id: int, session: Session = Depends(get_session)) -> ApiResponse[ClientResponse]:
    """查询客户端详情。"""
    client = get_client_or_raise(session, client_id)
    return success_res(data=ClientResponse.from_model(client))


@router.post("/create", response_model=ApiResponse[ClientResponse], status_code=status.HTTP_201_CREATED)
def create_client_route(payload: ClientCreateRequest, session: Session = Depends(get_session)) -> ApiResponse[
    ClientResponse]:
    """创建客户端。"""

    client = Client(
        name=payload.name,
        api_url=payload.api_url,
        account=payload.account,
        password=payload.password,
        status=payload.status,
    )
    session.add(client)
    session.commit()
    session.refresh(client)
    logger.info(f"API 请求创建客户端创建完成: client_id={client.id}, name={client.name}, status={client.status}")
    return success_res(data=ClientResponse.from_model(client))


@router.put("/update/{client_id}", response_model=ApiResponse[ClientResponse])
def update_client_route(client_id: int, payload: ClientUpdateRequest, session: Session = Depends(get_session)) -> \
        ApiResponse[ClientResponse]:
    """更新客户端。"""

    client = get_client_or_raise(session, client_id)
    client.name = payload.name
    client.api_url = payload.api_url
    client.account = payload.account
    client.status = payload.status

    if payload.password not in (None, "", MASK_PLACEHOLDER):
        client.password = payload.password
        credential_changed = True
    else:
        credential_changed = False

    session.add(client)
    session.commit()
    session.refresh(client)
    logger.info(f"API 请求更新客户端完成: client_id={client.id}, name={client.name}, "
                f"status={client.status}, password_changed={credential_changed}")
    return success_res(data=ClientResponse.from_model(client))


@router.delete("/delete/{client_id}", response_model=ApiResponse[ClientDeleteData])
def delete_client_route(client_id: int, session: Session = Depends(get_session), ) -> ApiResponse[ClientDeleteData]:
    """删除客户端。"""

    with session.begin():
        client = get_client_or_raise(session, client_id)
        tasks = session.exec(select(Task).where(Task.client_id == client_id)).all()
        task_ids = [task.id for task in tasks if task.id is not None]

        task_items = []
        task_item_data_rows = []
        if task_ids:
            task_items = session.exec(
                select(TaskItem).where(TaskItem.task_id.in_(task_ids))
            ).all()
            task_item_ids = [
                task_item.id for task_item in task_items if task_item.id is not None
            ]
            if task_item_ids:
                task_item_data_rows = session.exec(
                    select(TaskItemData).where(TaskItemData.task_item_id.in_(task_item_ids))
                ).all()

        for task_item_data in task_item_data_rows:
            session.delete(task_item_data)
        session.flush()

        for task_item in task_items:
            session.delete(task_item)
        session.flush()

        for task in tasks:
            session.delete(task)
        session.flush()

        session.delete(client)

    logger.info(f"API 请求删除客户端完成: client_id={client_id}, task_count={len(tasks)}, "
                f"task_item_count={len(task_items)}, task_item_data_count={len(task_item_data_rows)}")

    return success_res(data=ClientDeleteData(id=client_id))


@router.post("/authenticate/{client_id}", response_model=ApiResponse[ClientAuthenticateData])
def authenticate_client_route(client_id: int, session: Session = Depends(get_session), ) -> ApiResponse[
    ClientAuthenticateData]:
    """手动触发客户端认证。"""

    auth_result = authenticate_client(session, client_id)
    auth_data = ClientAuthenticateData(
        client=ClientResponse.from_model(auth_result.client),
        usedStrategy=auth_result.used_strategy,
    )
    return success_res(data=auth_data)
