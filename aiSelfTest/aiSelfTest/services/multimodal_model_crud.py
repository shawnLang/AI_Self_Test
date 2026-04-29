"""多模态模型配置 CRUD 与模型探测服务。"""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from aiSelfTest.exceptions import AppException, ErrorCode
from aiSelfTest.models.multimodal_model import MultimodalModel
from requests import Response
from sqlmodel import Session

RequestFunc = Callable[..., Response]


def resolve_detected_at(detected_models: list[str], detected_models_updated: bool,
                        current_detected_at: datetime | None = None) -> datetime | None:
    """根据探测模型是否刷新决定更新时间。"""

    if detected_models_updated:
        return datetime.now() if detected_models else None
    return current_detected_at


def get_multimodal_model_or_raise(session: Session, model_id: int) -> MultimodalModel:
    """按 ID 查询模型配置，不存在时抛出统一异常。"""

    model = session.get(MultimodalModel, model_id)
    if model is None:
        raise AppException(
            code=ErrorCode.NOT_FOUND,
            message="模型配置不存在",
            status_code=404,
        )
    return model
