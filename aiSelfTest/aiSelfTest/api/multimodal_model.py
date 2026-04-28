"""多模态模型管理路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from fastapi.responses import StreamingResponse
from loguru import logger
from sqlmodel import Session

from aiSelfTest.database import get_session
from aiSelfTest.schemas.common import ApiResponse
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
    MultimodalModelUpdateRequest,
)
from aiSelfTest.services.multimodal_chat import (
    chat_with_multimodal_model,
    delete_multimodal_chat_session,
    get_multimodal_chat_session_detail,
    list_multimodal_chat_sessions,
    stream_chat_with_multimodal_model,
)
from aiSelfTest.services.multimodal_model_crud import (
    create_multimodal_model,
    delete_multimodal_model,
    detect_multimodal_models,
    list_multimodal_models,
    update_multimodal_model,
)


router = APIRouter(prefix="/multimodal-models")


@router.get("/list", response_model=ApiResponse[MultimodalModelListData])
def list_multimodal_models_route(
    session: Session = Depends(get_session),
) -> ApiResponse[MultimodalModelListData]:
    """查询模型配置列表。"""

    logger.info("API 请求多模态模型配置列表")
    items = list_multimodal_models(session)
    return ApiResponse(
        code=0,
        message="success",
        data=MultimodalModelListData(items=items),
    )


@router.post(
    "/create",
    response_model=ApiResponse[MultimodalModelResponse],
    status_code=status.HTTP_201_CREATED,
)
def create_multimodal_model_route(
    payload: MultimodalModelCreateRequest,
    session: Session = Depends(get_session),
) -> ApiResponse[MultimodalModelResponse]:
    """创建模型配置。"""

    logger.info(
        "API 请求创建多模态模型配置: model_name={}, status={}",
        payload.model_name,
        payload.status,
    )
    return ApiResponse(
        code=0,
        message="success",
        data=create_multimodal_model(session, payload),
    )


@router.put("/update/{model_id}", response_model=ApiResponse[MultimodalModelResponse])
def update_multimodal_model_route(
    model_id: int,
    payload: MultimodalModelUpdateRequest,
    session: Session = Depends(get_session),
) -> ApiResponse[MultimodalModelResponse]:
    """更新模型配置。"""

    logger.info(
        "API 请求更新多模态模型配置: model_id={}, model_name={}, status={}",
        model_id,
        payload.model_name,
        payload.status,
    )
    return ApiResponse(
        code=0,
        message="success",
        data=update_multimodal_model(session, model_id, payload),
    )


@router.delete("/delete/{model_id}", response_model=ApiResponse[MultimodalModelDeleteData])
def delete_multimodal_model_route(
    model_id: int,
    session: Session = Depends(get_session),
) -> ApiResponse[MultimodalModelDeleteData]:
    """删除模型配置。"""

    logger.info("API 请求删除多模态模型配置: model_id={}", model_id)
    deleted_model_id = delete_multimodal_model(session, model_id)
    return ApiResponse(
        code=0,
        message="success",
        data=MultimodalModelDeleteData(id=deleted_model_id),
    )


@router.post("/detect", response_model=ApiResponse[MultimodalModelDetectData])
def detect_multimodal_models_route(
    payload: MultimodalModelDetectRequest,
) -> ApiResponse[MultimodalModelDetectData]:
    """探测远端可用模型。"""

    logger.info("API 请求探测多模态模型: endpoint_url={}", payload.endpoint_url)
    return ApiResponse(
        code=0,
        message="success",
        data=detect_multimodal_models(payload),
    )


@router.post("/chat/{model_id}", response_model=ApiResponse[MultimodalChatData])
def chat_with_multimodal_model_route(
    model_id: int,
    payload: MultimodalChatRequest,
    session: Session = Depends(get_session),
) -> ApiResponse[MultimodalChatData]:
    """对指定模型配置发起聊天测试。"""

    logger.info(
        "API 请求多模态聊天: model_id={}, session_id={}, message_count={}",
        model_id,
        payload.session_id,
        len(payload.messages),
    )
    return ApiResponse(
        code=0,
        message="success",
        data=chat_with_multimodal_model(session, model_id, payload),
    )


@router.post("/chat-stream/{model_id}")
def stream_chat_with_multimodal_model_route(
    model_id: int,
    payload: MultimodalChatRequest,
    session: Session = Depends(get_session),
) -> StreamingResponse:
    """对指定模型配置发起流式聊天测试。"""

    logger.info(
        "API 请求多模态流式聊天: model_id={}, session_id={}, message_count={}",
        model_id,
        payload.session_id,
        len(payload.messages),
    )
    event_stream = stream_chat_with_multimodal_model(session, model_id, payload)
    return StreamingResponse(
        event_stream,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/session-list/{model_id}",
    response_model=ApiResponse[MultimodalChatSessionListData],
)
def list_multimodal_chat_sessions_route(
    model_id: int,
    session: Session = Depends(get_session),
) -> ApiResponse[MultimodalChatSessionListData]:
    """查询指定模型下的聊天会话列表。"""

    logger.info("API 请求多模态聊天会话列表: model_id={}", model_id)
    return ApiResponse(
        code=0,
        message="success",
        data=list_multimodal_chat_sessions(session, model_id),
    )


@router.get(
    "/session-detail/{session_id}",
    response_model=ApiResponse[MultimodalChatSessionDetailData],
)
def get_multimodal_chat_session_detail_route(
    session_id: int,
    session: Session = Depends(get_session),
) -> ApiResponse[MultimodalChatSessionDetailData]:
    """查询聊天会话详情。"""

    logger.info("API 请求多模态聊天会话详情: session_id={}", session_id)
    return ApiResponse(
        code=0,
        message="success",
        data=get_multimodal_chat_session_detail(session, session_id),
    )


@router.delete(
    "/delete-session/{session_id}",
    response_model=ApiResponse[MultimodalChatSessionDeleteData],
)
def delete_multimodal_chat_session_route(
    session_id: int,
    session: Session = Depends(get_session),
) -> ApiResponse[MultimodalChatSessionDeleteData]:
    """删除聊天会话。"""

    logger.info("API 请求删除多模态聊天会话: session_id={}", session_id)
    deleted_session_id = delete_multimodal_chat_session(session, session_id)
    return ApiResponse(
        code=0,
        message="success",
        data=MultimodalChatSessionDeleteData(id=deleted_session_id),
    )
