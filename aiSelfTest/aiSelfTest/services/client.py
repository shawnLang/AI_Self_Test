"""客户端管理服务。"""

from __future__ import annotations

from loguru import logger
from sqlmodel import Session, select

from aiSelfTest.exceptions import AppException, ErrorCode
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
    logger.debug("客户端列表查询完成: count={}", len(clients))
    return [ClientResponse.from_model(client) for client in clients]


def get_client_detail(session: Session, client_id: int) -> ClientResponse:
    """查询单个客户端。"""

    client = _get_client_or_raise(session, client_id)
    logger.debug("客户端详情查询完成: client_id={}", client_id)
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
    logger.info(
        "客户端创建完成: client_id={}, name={}, status={}",
        client.id,
        client.name,
        client.status,
    )
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
        credential_changed = True
    else:
        credential_changed = False

    session.add(client)
    session.commit()
    session.refresh(client)
    logger.info(
        "客户端更新完成: client_id={}, name={}, status={}, password_changed={}",
        client.id,
        client.name,
        client.status,
        payload.password not in (None, "", MASK_PLACEHOLDER),
    )
    return ClientResponse.from_model(client)


def delete_client(session: Session, client_id: int) -> int:
    """删除客户端及其关联任务数据。"""

    with session.begin():
        client = _get_client_or_raise(session, client_id)
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
                    select(TaskItemData).where(
                        TaskItemData.task_item_id.in_(task_item_ids)
                    )
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

    logger.info(
        "客户端删除完成: client_id={}, task_count={}, task_item_count={}, task_item_data_count={}",
        client_id,
        len(tasks),
        len(task_items),
        len(task_item_data_rows),
    )
    return client_id


def _get_client_or_raise(session: Session, client_id: int) -> Client:
    """按 ID 查询客户端，不存在时抛出统一异常。"""

    client = session.get(Client, client_id)
    if client is None:
        raise AppException(
            code=ErrorCode.NOT_FOUND,
            message="客户端不存在",
            status_code=404,
        )
    return client
