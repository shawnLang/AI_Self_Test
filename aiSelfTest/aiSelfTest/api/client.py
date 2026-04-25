"""客户端管理路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlmodel import Session

from aiSelfTest.database import get_session
from aiSelfTest.schemas.client import (
    ClientAuthenticateData,
    ClientCreateRequest,
    ClientDeleteData,
    ClientListData,
    ClientResponse,
    ClientUpdateRequest,
)
from aiSelfTest.schemas.common import ApiResponse
from aiSelfTest.services.client_auth import authenticate_client
from aiSelfTest.services.client import (
    create_client,
    delete_client,
    get_client_detail,
    list_clients,
    update_client,
)


router = APIRouter(prefix="/clients")


@router.get("/list", response_model=ApiResponse[ClientListData])
def list_client_route(
    session: Session = Depends(get_session),
) -> ApiResponse[ClientListData]:
    """查询客户端列表。"""

    items = list_clients(session)
    return ApiResponse(
        code=0,
        message="success",
        data=ClientListData(items=items),
    )


@router.get("/detail/{client_id}", response_model=ApiResponse[ClientResponse])
def get_client_detail_route(
    client_id: int,
    session: Session = Depends(get_session),
) -> ApiResponse[ClientResponse]:
    """查询客户端详情。"""

    return ApiResponse(
        code=0,
        message="success",
        data=get_client_detail(session, client_id),
    )


@router.post(
    "/create",
    response_model=ApiResponse[ClientResponse],
    status_code=status.HTTP_201_CREATED,
)
def create_client_route(
    payload: ClientCreateRequest,
    session: Session = Depends(get_session),
) -> ApiResponse[ClientResponse]:
    """创建客户端。"""

    return ApiResponse(
        code=0,
        message="success",
        data=create_client(session, payload),
    )


@router.put("/update/{client_id}", response_model=ApiResponse[ClientResponse])
def update_client_route(
    client_id: int,
    payload: ClientUpdateRequest,
    session: Session = Depends(get_session),
) -> ApiResponse[ClientResponse]:
    """更新客户端。"""

    return ApiResponse(
        code=0,
        message="success",
        data=update_client(session, client_id, payload),
    )


@router.delete("/delete/{client_id}", response_model=ApiResponse[ClientDeleteData])
def delete_client_route(
    client_id: int,
    session: Session = Depends(get_session),
) -> ApiResponse[ClientDeleteData]:
    """删除客户端。"""

    deleted_client_id = delete_client(session, client_id)
    return ApiResponse(
        code=0,
        message="success",
        data=ClientDeleteData(id=deleted_client_id),
    )


@router.post("/authenticate/{client_id}", response_model=ApiResponse[ClientAuthenticateData])
def authenticate_client_route(
    client_id: int,
    session: Session = Depends(get_session),
) -> ApiResponse[ClientAuthenticateData]:
    """手动触发客户端认证。"""

    auth_result = authenticate_client(session, client_id)
    return ApiResponse(
        code=0,
        message="success",
        data=ClientAuthenticateData(
            client=ClientResponse.from_model(auth_result.client),
            used_strategy=auth_result.used_strategy,
        ),
    )
