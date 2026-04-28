"""模型提示词配置管理路由。"""

from __future__ import annotations

from aiSelfTest.database import get_session
from aiSelfTest.exceptions import AppException, ErrorCode
from aiSelfTest.models import Config
from aiSelfTest.schemas.common import ApiResponse, success_res
from aiSelfTest.schemas.config import (
    ConfigCreateRequest,
    ConfigDeleteData,
    ConfigListData,
    ConfigResponse,
    ConfigUpdateRequest,
)
from fastapi import APIRouter, Depends, status
from loguru import logger
from sqlmodel import Session, select, desc

router = APIRouter(prefix="/configs")


def get_config_or_raise(session: Session, config_id: int) -> Config:
    """按 ID 查询模型提示词配置，不存在时抛出统一异常。"""
    config = session.get(Config, config_id)
    if config is None:
        raise AppException(
            code=ErrorCode.NOT_FOUND,
            message="模型提示词配置不存在",
            status_code=404,
        )
    return config


@router.get("/list", response_model=ApiResponse[ConfigListData])
def list_configs_route(session: Session = Depends(get_session)) -> ApiResponse[ConfigListData]:
    """查询模型提示词配置列表。"""

    configs = session.exec(select(Config).order_by(desc(Config.id))).all()
    logger.info(f"API 请求模型提示词配置列表查询完成: count={len(configs)}")
    items = [ConfigResponse.from_model(config) for config in configs]
    return success_res(data=ConfigListData(items=items))


@router.get("/detail/{config_id}", response_model=ApiResponse[ConfigResponse])
def get_config_detail_route(config_id: int, session: Session = Depends(get_session)) -> ApiResponse[ConfigResponse]:
    """查询模型提示词配置详情。"""

    config = get_config_or_raise(session, config_id)
    return success_res(data=ConfigResponse.from_model(config))


@router.post("/create", response_model=ApiResponse[ConfigResponse], status_code=status.HTTP_201_CREATED)
def create_config_route(payload: ConfigCreateRequest, session: Session = Depends(get_session)) -> ApiResponse[
    ConfigResponse]:
    """创建模型提示词配置。"""

    config = Config(
        name=payload.name,
        remark=payload.remark,
        text=payload.text,
        format=payload.format,
    )
    session.add(config)
    session.commit()
    session.refresh(config)
    logger.info(f"API 请求创建模型提示词配置: config_id={config.id}, name={config.name}, format={config.format}")
    return success_res(data=ConfigResponse.from_model(config))


@router.put("/update/{config_id}", response_model=ApiResponse[ConfigResponse])
def update_config_route(config_id: int, payload: ConfigUpdateRequest, session: Session = Depends(get_session)) -> \
        ApiResponse[ConfigResponse]:
    """更新模型提示词配置。"""

    config = get_config_or_raise(session, config_id)
    config.name = payload.name
    config.remark = payload.remark
    config.text = payload.text
    config.format = payload.format

    session.add(config)
    session.commit()
    session.refresh(config)
    logger.info(f"API 请求更新模型提示词配置完成: config_id={config.id}, name={config.name}, format={config.format}")
    return success_res(data=ConfigResponse.from_model(config))


@router.delete("/delete/{config_id}", response_model=ApiResponse[ConfigDeleteData])
def delete_config_route(config_id: int, session: Session = Depends(get_session)) -> ApiResponse[ConfigDeleteData]:
    """删除模型提示词配置。"""

    config = get_config_or_raise(session, config_id)
    session.delete(config)
    session.commit()
    logger.info(f"API 请求删除模型提示词配置完成: config_id={config_id}")
    return success_res(data=ConfigDeleteData(id=config_id))
