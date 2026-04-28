"""多模态模型配置 CRUD 与模型探测服务。"""

from __future__ import annotations

from datetime import datetime
from typing import Callable

import requests
from loguru import logger
from requests import Response
from sqlmodel import Session, select

from aiSelfTest.exceptions import AppException, ErrorCode
from aiSelfTest.models.multimodal_model import MultimodalModel
from aiSelfTest.schemas.multimodal_model import (
    MASK_PLACEHOLDER,
    MultimodalModelCreateRequest,
    MultimodalModelDetectData,
    MultimodalModelDetectRequest,
    MultimodalModelResponse,
    MultimodalModelUpdateRequest,
    serialize_detected_models,
)
from aiSelfTest.services.multimodal_gateway import (
    _call_models_endpoint,
    _extract_model_names,
)

RequestFunc = Callable[..., Response]


def list_multimodal_models(session: Session) -> list[MultimodalModelResponse]:
    """查询全部模型配置。"""

    models = session.exec(select(MultimodalModel).order_by(MultimodalModel.id.desc())).all()
    logger.debug("多模态模型配置列表查询完成 count={}", len(models))
    return [MultimodalModelResponse.from_model(model) for model in models]


def create_multimodal_model(
    session: Session,
    payload: MultimodalModelCreateRequest,
) -> MultimodalModelResponse:
    """创建模型配置。"""

    model = MultimodalModel(
        model_name=payload.model_name,
        endpoint_url=payload.endpoint_url,
        api_key=payload.api_key,
        status=payload.status,
        detected_models_json=serialize_detected_models(payload.detected_models),
        last_detected_at=_resolve_detected_at(
            detected_models=payload.detected_models,
            detected_models_updated=payload.detected_models_updated,
        ),
    )
    session.add(model)
    session.commit()
    session.refresh(model)
    logger.info(
        "多模态模型配置创建完成 model_id={} model_name={} detected_count={}",
        model.id,
        model.model_name,
        len(payload.detected_models),
    )
    return MultimodalModelResponse.from_model(model)


def update_multimodal_model(
    session: Session,
    model_id: int,
    payload: MultimodalModelUpdateRequest,
) -> MultimodalModelResponse:
    """更新模型配置。"""

    model = _get_multimodal_model_or_raise(session, model_id)

    model.model_name = payload.model_name
    model.endpoint_url = payload.endpoint_url
    model.status = payload.status

    if payload.api_key not in (None, "", MASK_PLACEHOLDER):
        model.api_key = payload.api_key
        credential_changed = True
    else:
        credential_changed = False

    model.detected_models_json = serialize_detected_models(payload.detected_models)
    model.last_detected_at = _resolve_detected_at(
        detected_models=payload.detected_models,
        detected_models_updated=payload.detected_models_updated,
        current_detected_at=model.last_detected_at,
    )
    model.updated_at = datetime.now()

    session.add(model)
    session.commit()
    session.refresh(model)
    logger.info(
        "多模态模型配置更新完成 model_id={} model_name={} api_key_updated={} detected_count={}",
        model.id,
        model.model_name,
        credential_changed,
        len(payload.detected_models),
    )
    return MultimodalModelResponse.from_model(model)


def delete_multimodal_model(session: Session, model_id: int) -> int:
    """删除模型配置。"""

    model = _get_multimodal_model_or_raise(session, model_id)
    session.delete(model)
    session.commit()
    logger.info("多模态模型配置删除完成 model_id={} model_name={}", model_id, model.model_name)
    return model_id


def detect_multimodal_models(
    payload: MultimodalModelDetectRequest,
    *,
    request_func: RequestFunc | None = None,
) -> MultimodalModelDetectData:
    """探测远端可用模型。"""

    request_impl = request_func or requests.request
    logger.info("开始探测多模态模型 endpoint_url={}", payload.endpoint_url)
    result = _call_models_endpoint(
        endpoint_url=payload.endpoint_url,
        api_key=payload.api_key,
        request_func=request_impl,
    )
    models = _extract_model_names(result.payload)
    recommended_model = models[0] if models else ""
    logger.info(
        "多模态模型探测完成 detected_url={} model_count={} recommended_model={}",
        result.used_url,
        len(models),
        recommended_model,
    )
    return MultimodalModelDetectData(
        models=models,
        detected_url=result.used_url,
        recommended_model=recommended_model,
    )


def _resolve_detected_at(
    *,
    detected_models: list[str],
    detected_models_updated: bool,
    current_detected_at: datetime | None = None,
) -> datetime | None:
    """根据探测模型是否刷新决定更新时间。"""

    if detected_models_updated:
        return datetime.now() if detected_models else None
    return current_detected_at


def _get_multimodal_model_or_raise(session: Session, model_id: int) -> MultimodalModel:
    """按 ID 查询模型配置，不存在时抛出统一异常。"""

    model = session.get(MultimodalModel, model_id)
    if model is None:
        raise AppException(
            code=ErrorCode.NOT_FOUND,
            message="模型配置不存在",
            status_code=404,
        )
    return model
