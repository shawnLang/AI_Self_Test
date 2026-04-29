"""多模态模型管理路由。"""

from __future__ import annotations

from datetime import datetime

import requests
from aiSelfTest.database import get_session
from aiSelfTest.exceptions import AppException, ErrorCode
from aiSelfTest.models import MultimodalModel, MultimodalChatSession
from aiSelfTest.schemas.client import MASK_PLACEHOLDER
from aiSelfTest.schemas.common import ApiResponse, success_res
from aiSelfTest.schemas.multimodal_model import (
    MultimodalChatData,
    MultimodalChatRequest,
    MultimodalChatSessionDeleteData,
    MultimodalChatSessionDetailData,
    MultimodalChatSessionListData,
    MultimodalModelCreateRequest,
    MultimodalModelDeleteData,
    MultimodalModelDetectData,
    MultimodalModelDetectRequest,
    MultimodalModelListData,
    MultimodalModelResponse,
    MultimodalModelUpdateRequest, serialize_detected_models, MultimodalChatSessionResponse,
    MultimodalChatMessageResponse,
)
from aiSelfTest.services.multimodal_attachment import build_gateway_chat_payload
from aiSelfTest.services.multimodal_chat import stream_chat_with_multimodal_model, persist_chat_turn, \
    get_chat_session_or_raise, list_chat_message_rows, prepare_chat_request
from aiSelfTest.services.multimodal_gateway import call_models_endpoint, extract_model_names, call_chat_endpoint, \
    extract_chat_reply
from aiSelfTest.services.multimodal_model_crud import (
    resolve_detected_at, get_multimodal_model_or_raise,
)
from fastapi import APIRouter, Depends, status
from fastapi.responses import StreamingResponse
from loguru import logger
from sqlmodel import Session, select, desc

router = APIRouter(prefix="/multimodal-models")


@router.get("/list", response_model=ApiResponse[MultimodalModelListData])
def list_multimodal_models_route(session: Session = Depends(get_session)) -> ApiResponse[MultimodalModelListData]:
    """查询模型配置列表。"""

    models = session.exec(select(MultimodalModel).order_by(desc(MultimodalModel.id))).all()
    logger.info(f"API 请求多模态模型配置列表完成: count={len(models)}")
    items = [MultimodalModelResponse.from_model(model) for model in models]
    return success_res(data=MultimodalModelListData(items=items))


@router.post("/create", response_model=ApiResponse[MultimodalModelResponse], status_code=status.HTTP_201_CREATED)
def create_multimodal_model_route(payload: MultimodalModelCreateRequest, session: Session = Depends(get_session)) -> \
        ApiResponse[MultimodalModelResponse]:
    """创建模型配置。"""

    model = MultimodalModel(
        model_name=payload.model_name,
        endpoint_url=payload.endpoint_url,
        api_key=payload.api_key,
        status=payload.status,
        detected_models_json=serialize_detected_models(payload.detected_models),
        last_detected_at=resolve_detected_at(
            detected_models=payload.detected_models,
            detected_models_updated=payload.detected_models_updated,
        ))
    session.add(model)
    session.commit()
    session.refresh(model)
    logger.info(
        "多模态模型配置创建完成: model_id={}, model_name={}, status={}, detected_model_count={}",
        model.id,
        model.model_name,
        model.status,
        len(payload.detected_models),
    )
    return success_res(data=MultimodalModelResponse.from_model(model))


@router.put("/update/{model_id}", response_model=ApiResponse[MultimodalModelResponse])
def update_multimodal_model_route(model_id: int, payload: MultimodalModelUpdateRequest,
                                  session: Session = Depends(get_session)) -> ApiResponse[MultimodalModelResponse]:
    """更新模型配置。"""

    model = get_multimodal_model_or_raise(session, model_id)

    model.model_name = payload.model_name
    model.endpoint_url = payload.endpoint_url
    model.status = payload.status

    if payload.api_key not in (None, "", MASK_PLACEHOLDER):
        model.api_key = payload.api_key
        credential_changed = True
    else:
        credential_changed = False

    model.detected_models_json = serialize_detected_models(payload.detected_models)
    model.last_detected_at = resolve_detected_at(
        detected_models=payload.detected_models,
        detected_models_updated=payload.detected_models_updated,
        current_detected_at=model.last_detected_at,
    )
    model.updated_at = datetime.now()

    session.add(model)
    session.commit()
    session.refresh(model)
    logger.info(
        "多模态模型配置更新完成: model_id={}, model_name={}, status={}, api_key_changed={}, detected_model_count={}",
        model.id,
        model.model_name,
        model.status,
        credential_changed,
        len(payload.detected_models),
    )
    return success_res(data=MultimodalModelResponse.from_model(model))


@router.delete("/delete/{model_id}", response_model=ApiResponse[MultimodalModelDeleteData])
def delete_multimodal_model_route(model_id: int, session: Session = Depends(get_session)) -> ApiResponse[
    MultimodalModelDeleteData]:
    """删除模型配置。"""
    model = get_multimodal_model_or_raise(session, model_id)
    session.delete(model)
    session.commit()
    logger.info("API 请求删除多模态模型配置完成: model_id={}", model_id)
    return success_res(data=MultimodalModelDeleteData(id=model_id))


@router.post("/detect", response_model=ApiResponse[MultimodalModelDetectData])
def detect_multimodal_models_route(payload: MultimodalModelDetectRequest) -> ApiResponse[MultimodalModelDetectData]:
    """探测远端可用模型。"""
    result = call_models_endpoint(
        endpoint_url=payload.endpoint_url,
        api_key=payload.api_key,
        request_func=requests,
    )
    models = extract_model_names(result.payload)
    recommended_model = models[0] if models else ""
    logger.info(
        "多模态模型探测完成: endpoint_url={}, detected_url={}, model_count={}",
        payload.endpoint_url,
        result.used_url,
        len(models),
    )
    return success_res(data=MultimodalModelDetectData(
        models=models,
        detectedUrl=result.used_url,
        recommendedModel=recommended_model,
    ))


@router.post("/chat/{model_id}", response_model=ApiResponse[MultimodalChatData])
def chat_with_multimodal_model_route(model_id: int, payload: MultimodalChatRequest,
                                     session: Session = Depends(get_session)) -> ApiResponse[MultimodalChatData]:
    """对指定模型配置发起聊天测试。"""

    prepared = prepare_chat_request(session, model_id, payload)
    logger.info(
        "API 请求多模态非流式聊天开始: model_id={}, existing_session_id={}, new_message_count={}, context_message_count={}",
        model_id,
        prepared.existing_session.id if prepared.existing_session else None,
        len(prepared.new_messages),
        len(prepared.context_messages),
    )
    normalized_payload = build_gateway_chat_payload(
        model_name=prepared.model.model_name,
        messages=prepared.context_messages,
        stream=False,
    )
    result = call_chat_endpoint(
        endpoint_url=prepared.model.endpoint_url,
        api_key=prepared.model.api_key,
        payload=normalized_payload,
        request_func=requests.request,
    )
    reply = extract_chat_reply(result.payload)
    if not reply:
        raise AppException(
            code=ErrorCode.INTERNAL_ERROR,
            message="模型调用成功，但未解析到回复内容",
            status_code=502,
        )

    persisted_session = persist_chat_turn(
        session=session,
        prepared=prepared,
        reply=reply,
        used_url=result.used_url,
    )
    logger.info(
        "多模态非流式聊天完成: model_id={}, session_id={}, used_url={}",
        model_id,
        persisted_session.id,
        result.used_url,
    )
    return success_res(data=MultimodalChatData(
        reply=reply,
        modelName=prepared.model.model_name,
        usedUrl=result.used_url,
        sessionId=persisted_session.id or 0))


@router.post("/chat-stream/{model_id}")
def stream_chat_with_multimodal_model_route(model_id: int, payload: MultimodalChatRequest,
                                            session: Session = Depends(get_session)) -> StreamingResponse:
    """对指定模型配置发起流式聊天测试。"""

    event_stream = stream_chat_with_multimodal_model(session, model_id, payload)
    return StreamingResponse(
        event_stream,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/session-list/{model_id}", response_model=ApiResponse[MultimodalChatSessionListData])
def list_multimodal_chat_sessions_route(model_id: int, session: Session = Depends(get_session)) -> ApiResponse[
    MultimodalChatSessionListData]:
    """查询指定模型下的聊天会话列表。"""

    model = get_multimodal_model_or_raise(session, model_id)
    sessions = session.exec(
        select(MultimodalChatSession)
        .where(MultimodalChatSession.model_id == model_id)
        .where(MultimodalChatSession.message_count > 0)
        .order_by(desc(MultimodalChatSession.updated_at), desc(MultimodalChatSession.id))
    ).all()
    result = MultimodalChatSessionListData(
        items=[
            MultimodalChatSessionResponse.from_model(item, model_name=model.model_name)
            for item in sessions
        ]
    )
    logger.info("API 请求多模态聊天会话列表查询完成: model_id={}, count={}", model_id, len(sessions))
    return success_res(data=result)


@router.get("/session-detail/{session_id}", response_model=ApiResponse[MultimodalChatSessionDetailData])
def get_multimodal_chat_session_detail_route(session_id: int, session: Session = Depends(get_session)) -> ApiResponse[
    MultimodalChatSessionDetailData]:
    """查询聊天会话详情。"""

    chat_session = get_chat_session_or_raise(session, session_id)
    model = get_multimodal_model_or_raise(session, chat_session.model_id)
    message_rows = list_chat_message_rows(session, chat_session.id or 0)
    logger.debug(
        "api 请求多模态聊天会话详情查询完成: session_id={}, model_id={}, message_count={}",
        session_id,
        chat_session.model_id,
        len(message_rows),
    )
    return success_res(data=MultimodalChatSessionDetailData(
        session=MultimodalChatSessionResponse.from_model(
            chat_session,
            model_name=model.model_name,
        ),
        messages=[
            MultimodalChatMessageResponse.from_model(item)
            for item in message_rows
        ],
    ))


@router.delete("/delete-session/{session_id}", response_model=ApiResponse[MultimodalChatSessionDeleteData])
def delete_multimodal_chat_session_route(session_id: int, session: Session = Depends(get_session)) -> ApiResponse[
    MultimodalChatSessionDeleteData]:
    """删除聊天会话。"""

    chat_session = get_chat_session_or_raise(session, session_id)
    message_rows = list_chat_message_rows(session, chat_session.id or 0)
    for message_row in message_rows:
        session.delete(message_row)

    session.delete(chat_session)
    session.commit()
    logger.info(
        "API 请求多模态聊天会话删除完成: session_id={}, message_count={}",
        session_id,
        len(message_rows),
    )
    return success_res(data=session_id)
