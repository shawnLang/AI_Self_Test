"""客户端管理服务。"""

from __future__ import annotations

from sqlalchemy import delete
from sqlmodel import Session, select

from aiSelfTest.exceptions import AppException
from aiSelfTest.models.client import Client
from aiSelfTest.models.task import Task, TaskItem, TaskItemData
from aiSelfTest.schemas.client import (
    MASK_PLACEHOLDER,
    ClientCreateRequest,
    ClientResponse,
    ClientUpdateRequest,
)


def list_clients(session: Session) -> list[ClientResponse]:
    """查询全部客户端。"""

    clients = session.exec(select(Client).order_by(Client.id.desc())).all()
    return [ClientResponse.from_model(client) for client in clients]


def get_client_detail(session: Session, client_id: int) -> ClientResponse:
    """查询单个客户端。"""

    client = _get_client_or_raise(session, client_id)
    return ClientResponse.from_model(client)


def create_client(session: Session, payload: ClientCreateRequest) -> ClientResponse:
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
    return ClientResponse.from_model(client)


def update_client(
    session: Session,
    client_id: int,
    payload: ClientUpdateRequest,
) -> ClientResponse:
    """更新客户端。"""

    client = _get_client_or_raise(session, client_id)
    client.name = payload.name
    client.api_url = payload.api_url
    client.account = payload.account
    client.status = payload.status

    if payload.password not in (None, "", MASK_PLACEHOLDER):
        client.password = payload.password

    session.add(client)
    session.commit()
    session.refresh(client)
    return ClientResponse.from_model(client)


def delete_client(session: Session, client_id: int) -> int:
    """删除客户端及其关联任务数据。"""

    client = _get_client_or_raise(session, client_id)
    task_ids = session.exec(select(Task.id).where(Task.client_id == client_id)).all()

    if task_ids:
        task_item_ids = session.exec(
            select(TaskItem.id).where(TaskItem.task_id.in_(task_ids))
        ).all()
        if task_item_ids:
            session.exec(
                delete(TaskItemData).where(TaskItemData.task_item_id.in_(task_item_ids))
            )
        session.exec(delete(TaskItem).where(TaskItem.task_id.in_(task_ids)))
        session.exec(delete(Task).where(Task.id.in_(task_ids)))

    session.delete(client)
    session.commit()
    return client_id


def _get_client_or_raise(session: Session, client_id: int) -> Client:
    """按 ID 查询客户端，不存在时抛出统一异常。"""

    client = session.get(Client, client_id)
    if client is None:
        raise AppException(
            code=1002,
            message="客户端不存在",
            status_code=404,
        )
    return client
