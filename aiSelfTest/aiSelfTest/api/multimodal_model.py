"""多模态模型管理路由。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterator

from aiSelfTest.database import get_session
from aiSelfTest.exceptions import AppException, ErrorCode
from aiSelfTest.models.multimodal_chat import MultimodalChatMessage, MultimodalChatSession
from aiSelfTest.models.multimodal_model import MultimodalModel
from aiSelfTest.schemas.client import MASK_PLACEHOLDER
from aiSelfTest.schemas.common import ApiResponse, success_res
from aiSelfTest.schemas.multimodal_model import (
    MultimodalChatData,
    MultimodalChatMessagePayload,
    MultimodalChatMessageResponse,
    MultimodalChatRequest,
    MultimodalChatSessionDeleteData,
    MultimodalChatSessionDetailData,
    MultimodalChatSessionListData,
    MultimodalChatSessionResponse,
    MultimodalModelCreateRequest,
    MultimodalModelDeleteData,
    MultimodalModelDetectData,
    MultimodalModelDetectRequest,
    MultimodalModelListData,
    MultimodalModelResponse,
    MultimodalModelUpdateRequest,
    parse_attachments,
    serialize_attachments,
    serialize_detected_models,
)
from aiSelfTest.services.multimodal_attachment import build_gateway_chat_payload
from aiSelfTest.services.multimodal_gateway import GatewayResponseParser, MultimodalGatewayClient
from fastapi import APIRouter, Depends, status
from fastapi.responses import StreamingResponse
from loguru import logger
from sqlmodel import Session, asc, desc, select

router = APIRouter(prefix="/multimodal-models")


@dataclass(frozen=True)
class ChatPreparation:
    """聊天调用前的上下文准备结果。"""

    model: MultimodalModel
    existing_session: MultimodalChatSession | None
    context_messages: list[MultimodalChatMessagePayload]
    new_messages: list[MultimodalChatMessagePayload]


@router.get("/list", response_model=ApiResponse[MultimodalModelListData])
def list_multimodal_models_route(session: Session = Depends(get_session)) -> ApiResponse[MultimodalModelListData]:
    """查询模型配置列表。"""

    models = session.exec(select(MultimodalModel).order_by(desc(MultimodalModel.id))).all()
    logger.info("API 请求多模态模型配置列表完成: count={}", len(models))
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
        last_detected_at=_resolve_detected_at(
            detected_models=payload.detected_models,
            detected_models_updated=payload.detected_models_updated,
        ),
    )
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

    model = _get_multimodal_model_or_raise(session, model_id)
    session.delete(model)
    session.commit()
    logger.info("API 请求删除多模态模型配置完成: model_id={}", model_id)
    return success_res(data=MultimodalModelDeleteData(id=model_id))


@router.post("/detect", response_model=ApiResponse[MultimodalModelDetectData])
def detect_multimodal_models_route(
        payload: MultimodalModelDetectRequest,
        session: Session = Depends(get_session),
) -> ApiResponse[MultimodalModelDetectData]:
    """探测远端可用模型。"""

    result = MultimodalGatewayClient().call_models_endpoint(
        endpoint_url=payload.endpoint_url,
        api_key=payload.api_key,
    )
    models = GatewayResponseParser.extract_model_names(result.payload)
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

    prepared = _prepare_chat_request(session, model_id, payload)
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
    result = MultimodalGatewayClient().call_chat_endpoint(
        endpoint_url=prepared.model.endpoint_url,
        api_key=prepared.model.api_key,
        payload=normalized_payload,
    )
    reply = GatewayResponseParser.extract_chat_reply(result.payload)
    if not reply:
        raise AppException(
            code=ErrorCode.INTERNAL_ERROR,
            message="模型调用成功，但未解析到回复内容",
            status_code=502,
        )

    persisted_session = _persist_chat_turn(
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
        sessionId=persisted_session.id or 0,
    ))


@router.post("/chat-stream/{model_id}")
def stream_chat_with_multimodal_model_route(model_id: int, payload: MultimodalChatRequest,
                                            session: Session = Depends(get_session)) -> StreamingResponse:
    """对指定模型配置发起流式聊天测试。"""

    event_stream = _stream_chat_with_multimodal_model(session, model_id, payload)
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

    model = _get_multimodal_model_or_raise(session, model_id)
    sessions = session.exec(
        select(MultimodalChatSession)
        .where(MultimodalChatSession.model_id == model_id)
        .where(MultimodalChatSession.message_count > 0)
        .order_by(desc(MultimodalChatSession.updated_at), desc(MultimodalChatSession.id))
    ).all()
    logger.info("API 请求多模态聊天会话列表查询完成: model_id={}, count={}", model_id, len(sessions))
    return success_res(data=MultimodalChatSessionListData(
        items=[
            MultimodalChatSessionResponse.from_model(item, model_name=model.model_name)
            for item in sessions
        ]
    ))


@router.get("/session-detail/{session_id}", response_model=ApiResponse[MultimodalChatSessionDetailData])
def get_multimodal_chat_session_detail_route(session_id: int, session: Session = Depends(get_session)) -> ApiResponse[
    MultimodalChatSessionDetailData]:
    """查询聊天会话详情。"""

    chat_session = _get_chat_session_or_raise(session, session_id)
    model = _get_multimodal_model_or_raise(session, chat_session.model_id)
    message_rows = _list_chat_message_rows(session, chat_session.id or 0)
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

    chat_session = _get_chat_session_or_raise(session, session_id)
    message_rows = _list_chat_message_rows(session, chat_session.id or 0)
    for message_row in message_rows:
        session.delete(message_row)

    session.delete(chat_session)
    session.commit()
    logger.info(
        "多模态聊天会话删除完成: session_id={}, message_count={}",
        session_id,
        len(message_rows),
    )
    return success_res(data=MultimodalChatSessionDeleteData(id=session_id))


def _resolve_detected_at(
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


def _get_chat_session_or_raise(session: Session, session_id: int) -> MultimodalChatSession:
    """按 ID 查询聊天会话，不存在时抛出统一异常。"""

    chat_session = session.get(MultimodalChatSession, session_id)
    if chat_session is None:
        raise AppException(
            code=ErrorCode.NOT_FOUND,
            message="聊天会话不存在",
            status_code=404,
        )
    return chat_session


def _prepare_chat_request(session: Session, model_id: int, payload: MultimodalChatRequest) -> ChatPreparation:
    """准备聊天上下文。"""

    model = _get_multimodal_model_or_raise(session, model_id)
    if model.status != "启用":
        raise AppException(
            code=ErrorCode.PARAM_INVALID,
            message="模型已停用，无法进行测试",
            status_code=400,
        )

    existing_session: MultimodalChatSession | None = None
    context_messages: list[MultimodalChatMessagePayload] = []
    if payload.session_id is not None:
        existing_session = _get_chat_session_or_raise(session, payload.session_id)
        if existing_session.model_id != model_id:
            raise AppException(
                code=ErrorCode.PARAM_INVALID,
                message="会话与当前模型不匹配，无法继续对话",
                status_code=400,
            )
        stored_rows = _list_chat_message_rows(session, existing_session.id or 0)
        context_messages.extend(_message_row_to_payload(item) for item in stored_rows)

    context_messages.extend(payload.messages)
    logger.debug(
        "多模态聊天上下文准备完成: model_id={}, session_id={}, stored_message_count={}, new_message_count={}",
        model_id,
        existing_session.id if existing_session else None,
        len(context_messages) - len(payload.messages),
        len(payload.messages),
    )
    return ChatPreparation(
        model=model,
        existing_session=existing_session,
        context_messages=context_messages,
        new_messages=list(payload.messages),
    )


def _persist_chat_turn(
    session: Session,
    prepared: ChatPreparation,
    reply: str,
    used_url: str,
) -> MultimodalChatSession:
    """持久化一轮问答。"""

    chat_session = prepared.existing_session
    if chat_session is None:
        chat_session = MultimodalChatSession(
            model_id=prepared.model.id or 0,
            title=_build_session_title(prepared.new_messages),
        )
        session.add(chat_session)
        session.commit()
        session.refresh(chat_session)
        logger.info(
            "多模态聊天会话创建完成: session_id={}, model_id={}, title_length={}",
            chat_session.id,
            prepared.model.id,
            len(chat_session.title),
        )

    current_count = chat_session.message_count
    now = datetime.now()
    new_rows: list[MultimodalChatMessage] = []
    for offset, message in enumerate(prepared.new_messages, start=1):
        new_rows.append(
            MultimodalChatMessage(
                session_id=chat_session.id or 0,
                sequence_no=current_count + offset,
                role=message.role,
                content=message.content,
                attachments_json=serialize_attachments(message.attachments),
            )
        )

    assistant_row = MultimodalChatMessage(
        session_id=chat_session.id or 0,
        sequence_no=current_count + len(prepared.new_messages) + 1,
        role="assistant",
        content=reply,
        used_url=used_url,
    )
    new_rows.append(assistant_row)

    for row in new_rows:
        session.add(row)

    chat_session.message_count = current_count + len(new_rows)
    chat_session.last_message_at = now
    chat_session.updated_at = now
    session.add(chat_session)
    session.commit()
    session.refresh(chat_session)
    logger.info(
        "多模态聊天轮次持久化完成: session_id={}, new_row_count={}, total_message_count={}, used_url={}",
        chat_session.id,
        len(new_rows),
        chat_session.message_count,
        used_url,
    )
    return chat_session


def _stream_chat_with_multimodal_model(
    session: Session,
    model_id: int,
    payload: MultimodalChatRequest,
) -> Iterator[str]:
    """对指定模型配置发起流式聊天测试。"""

    prepared = _prepare_chat_request(session, model_id, payload)
    logger.info(
        "多模态流式聊天准备完成: model_id={}, existing_session_id={}, new_message_count={}, context_message_count={}",
        model_id,
        prepared.existing_session.id if prepared.existing_session else None,
        len(prepared.new_messages),
        len(prepared.context_messages),
    )
    normalized_payload = build_gateway_chat_payload(
        model_name=prepared.model.model_name,
        messages=prepared.context_messages,
        stream=True,
    )

    def event_stream() -> Iterator[str]:
        """生成 SSE 事件并在成功结束后持久化本轮聊天。"""

        yield _format_sse_event(
            "session",
            {
                "sessionId": prepared.existing_session.id if prepared.existing_session else None,
                "modelName": prepared.model.model_name,
                "isNewSession": prepared.existing_session is None,
            },
        )

        try:
            result = MultimodalGatewayClient().call_chat_endpoint_stream(
                endpoint_url=prepared.model.endpoint_url,
                api_key=prepared.model.api_key,
                payload=normalized_payload,
            )
            reply_parts: list[str] = []
            for delta_text in result.chunks:
                if not delta_text:
                    continue
                reply_parts.append(delta_text)
                yield _format_sse_event("delta", {"delta": delta_text})

            reply = "".join(reply_parts).strip()
            if not reply:
                raise AppException(
                    code=ErrorCode.INTERNAL_ERROR,
                    message="模型流式调用成功，但未解析到回复内容",
                    status_code=502,
                )

            persisted_session = _persist_chat_turn(
                session=session,
                prepared=prepared,
                reply=reply,
                used_url=result.used_url,
            )
            yield _format_sse_event(
                "done",
                {
                    "reply": reply,
                    "modelName": prepared.model.model_name,
                    "usedUrl": result.used_url,
                    "sessionId": persisted_session.id or 0,
                },
            )
            logger.info(
                "多模态流式聊天完成: model_id={}, session_id={}, used_url={}, chunk_count={}",
                model_id,
                persisted_session.id,
                result.used_url,
                len(reply_parts),
            )
        except AppException as exc:
            logger.warning("流式模型调用失败: {}", exc.message)
            yield _format_sse_event("error", {"message": exc.message})
        except Exception as exc:  # pragma: no cover - 兜底保护
            logger.exception("流式模型调用发生未预期异常")
            yield _format_sse_event(
                "error",
                {"message": str(exc) or "流式模型调用失败"},
            )

    return event_stream()


def _list_chat_message_rows(session: Session, session_id: int) -> list[MultimodalChatMessage]:
    """按顺序查询会话消息。"""

    statement = (
        select(MultimodalChatMessage)
        .where(MultimodalChatMessage.session_id == session_id)
        .order_by(
            asc(MultimodalChatMessage.sequence_no),
            asc(MultimodalChatMessage.id),
        )
    )
    return session.exec(statement).all()


def _format_sse_event(event: str, data: dict[str, Any]) -> str:
    """构造 SSE 文本片段。"""

    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _build_session_title(messages: list[MultimodalChatMessagePayload]) -> str:
    """根据首轮消息构建会话标题。"""

    for message in messages:
        if message.role != "user":
            continue
        title = message.content.strip()
        if title:
            return title[:80]
        if message.attachments:
            return f"附件测试会话（{len(message.attachments)} 个附件）"

    for message in messages:
        title = message.content.strip()
        if title:
            return title[:80]

    return "新的模型测试会话"


def _message_row_to_payload(message_row: MultimodalChatMessage) -> MultimodalChatMessagePayload:
    """将数据库消息恢复为请求消息对象。"""

    return MultimodalChatMessagePayload(
        role=message_row.role,
        content=message_row.content,
        attachments=parse_attachments(message_row.attachments_json),
    )
