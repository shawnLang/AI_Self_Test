"""模型提示词配置管理路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from loguru import logger
from sqlmodel import Session

from aiSelfTest.database import get_session
from aiSelfTest.schemas.common import ApiResponse
from aiSelfTest.schemas.config import (
    ConfigCreateRequest,
    ConfigDeleteData,
    ConfigListData,
    ConfigResponse,
    ConfigUpdateRequest,
)
from aiSelfTest.services.config import (
    create_config,
    delete_config,
    get_config_detail,
    list_configs,
    update_config,
)


router = APIRouter(prefix="/configs")


@router.get("/list", response_model=ApiResponse[ConfigListData])
def list_configs_route(
    session: Session = Depends(get_session),
) -> ApiResponse[ConfigListData]:
    """查询模型提示词配置列表。"""

    logger.info("API 请求：查询提示词配置列表")
    items = list_configs(session)
    return ApiResponse(
        code=0,
        message="success",
        data=ConfigListData(items=items),
    )


@router.get("/detail/{config_id}", response_model=ApiResponse[ConfigResponse])
def get_config_detail_route(
    config_id: int,
    session: Session = Depends(get_session),
) -> ApiResponse[ConfigResponse]:
    """查询模型提示词配置详情。"""

    logger.info("API 请求：查询提示词配置详情 config_id={}", config_id)
    return ApiResponse(
        code=0,
        message="success",
        data=get_config_detail(session, config_id),
    )


@router.post(
    "/create",
    response_model=ApiResponse[ConfigResponse],
    status_code=status.HTTP_201_CREATED,
)
def create_config_route(
    payload: ConfigCreateRequest,
    session: Session = Depends(get_session),
) -> ApiResponse[ConfigResponse]:
    """创建模型提示词配置。"""

    logger.info("API 请求：创建提示词配置 name={} format={}", payload.name, payload.format)
    return ApiResponse(
        code=0,
        message="success",
        data=create_config(session, payload),
    )


@router.put("/update/{config_id}", response_model=ApiResponse[ConfigResponse])
def update_config_route(
    config_id: int,
    payload: ConfigUpdateRequest,
    session: Session = Depends(get_session),
) -> ApiResponse[ConfigResponse]:
    """更新模型提示词配置。"""

    logger.info("API 请求：更新提示词配置 config_id={} name={}", config_id, payload.name)
    return ApiResponse(
        code=0,
        message="success",
        data=update_config(session, config_id, payload),
    )


@router.delete("/delete/{config_id}", response_model=ApiResponse[ConfigDeleteData])
def delete_config_route(
    config_id: int,
    session: Session = Depends(get_session),
) -> ApiResponse[ConfigDeleteData]:
    """删除模型提示词配置。"""

    logger.info("API 请求：删除提示词配置 config_id={}", config_id)
    deleted_config_id = delete_config(session, config_id)
    return ApiResponse(
        code=0,
        message="success",
        data=ConfigDeleteData(id=deleted_config_id),
    )
