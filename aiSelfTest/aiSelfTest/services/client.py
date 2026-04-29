"""客户端管理服务。"""

from __future__ import annotations

from typing import cast, Optional

from aiSelfTest.exceptions import AppException, ErrorCode
from aiSelfTest.models.client import Client
from sqlmodel import Session


def get_client_or_raise(session: Session, client_id: int) -> Client:
    """按 ID 查询客户端，不存在时抛出统一异常。"""

    client = cast(Optional[Client], session.get(Client, client_id))
    if client is None:
        raise AppException(
            code=ErrorCode.NOT_FOUND,
            message="客户端不存在",
            status_code=404,
        )
    return client
