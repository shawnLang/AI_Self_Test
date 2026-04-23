"""模型提示词配置管理服务。"""

from __future__ import annotations

from sqlmodel import Session, select

from aiSelfTest.exceptions import AppException
from aiSelfTest.models.config import Config
from aiSelfTest.schemas.config import (
    ConfigCreateRequest,
    ConfigResponse,
    ConfigUpdateRequest,
)


def list_configs(session: Session) -> list[ConfigResponse]:
    """查询全部模型提示词配置。"""

    configs = session.exec(select(Config).order_by(Config.id.desc())).all()
    return [ConfigResponse.from_model(config) for config in configs]


def get_config_detail(session: Session, config_id: int) -> ConfigResponse:
    """查询单个模型提示词配置。"""

    config = _get_config_or_raise(session, config_id)
    return ConfigResponse.from_model(config)


def create_config(
    session: Session,
    payload: ConfigCreateRequest,
) -> ConfigResponse:
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
    return ConfigResponse.from_model(config)


def update_config(
    session: Session,
    config_id: int,
    payload: ConfigUpdateRequest,
) -> ConfigResponse:
    """更新模型提示词配置。"""

    config = _get_config_or_raise(session, config_id)
    config.name = payload.name
    config.remark = payload.remark
    config.text = payload.text
    config.format = payload.format

    session.add(config)
    session.commit()
    session.refresh(config)
    return ConfigResponse.from_model(config)


def delete_config(session: Session, config_id: int) -> int:
    """删除模型提示词配置。"""

    config = _get_config_or_raise(session, config_id)
    session.delete(config)
    session.commit()
    return config_id


def _get_config_or_raise(session: Session, config_id: int) -> Config:
    """按 ID 查询模型提示词配置，不存在时抛出统一异常。"""

    config = session.get(Config, config_id)
    if config is None:
        raise AppException(
            code=1002,
            message="模型提示词配置不存在",
            status_code=404,
        )
    return config
