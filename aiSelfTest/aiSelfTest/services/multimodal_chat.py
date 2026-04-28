"""多模态聊天会话与消息持久化服务。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from typing import Any, Callable, Iterator

import requests
from loguru import logger
from requests import Response
from sqlmodel import Session, select

from aiSelfTest.exceptions import AppException, ErrorCode
from aiSelfTest.models.multimodal_chat import (
    MultimodalChatMessage,
    MultimodalChatSession,
)
from aiSelfTest.models.multimodal_model import MultimodalModel
from aiSelfTest.schemas.multimodal_model import (
    MultimodalChatData,
    MultimodalChatMessagePayload,
    MultimodalChatMessageResponse,
    MultimodalChatRequest,
    MultimodalChatSessionDetailData,
    MultimodalChatSessionListData,
    MultimodalChatSessionResponse,
    parse_attachments,
    serialize_attachments,
)
from aiSelfTest.services.multimodal_attachment import _build_gateway_chat_payload
from aiSelfTest.services.multimodal_gateway import (
    _call_chat_endpoint,
    _call_chat_endpoint_stream,
    _extract_chat_reply,
)
from aiSelfTest.services.multimodal_model_crud import _get_multimodal_model_or_raise

RequestFunc = Callable[..., Response]


@dataclass(frozen=True)
class ChatPreparation:
    """聊天调用前的上下文准备结果。"""

    model: MultimodalModel
    existing_session: MultimodalChatSession | None
    context_messages: list[MultimodalChatMessagePayload]
    new_messages: list[MultimodalChatMessagePayload]


def list_multimodal_chat_sessions(
    session: Session,
    model_id: int,
) -> MultimodalChatSessionListData:
    """查询指定模型下的聊天会话列表。"""

    model = _get_multimodal_model_or_raise(session, model_id)
    sessions = session.exec(
        select(MultimodalChatSession)
        .where(MultimodalChatSession.model_id == model_id)
        .where(MultimodalChatSession.message_count > 0)
        .order_by(MultimodalChatSession.updated_at.desc(), MultimodalChatSession.id.desc())
    ).all()
    result = MultimodalChatSessionListData(
        items=[
            MultimodalChatSessionResponse.from_model(item, model_name=model.model_name)
            for item in sessions
        ]
    )
    logger.debug("多模态聊天会话列表查询完成: model_id={}, count={}", model_id, len(sessions))
    return result


def delete_multimodal_chat_session(
    session: Session,
    session_id: int,
) -> int:
    """删除聊天会话及其下全部消息。"""

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
    return session_id


def get_multimodal_chat_session_detail(
    session: Session,
    session_id: int,
) -> MultimodalChatSessionDetailData:
    """查询聊天会话详情。"""

    chat_session = _get_chat_session_or_raise(session, session_id)
    model = _get_multimodal_model_or_raise(session, chat_session.model_id)
    message_rows = _list_chat_message_rows(session, chat_session.id or 0)
    logger.debug(
        "多模态聊天会话详情查询完成: session_id={}, model_id={}, message_count={}",
        session_id,
        chat_session.model_id,
        len(message_rows),
    )
    return MultimodalChatSessionDetailData(
        session=MultimodalChatSessionResponse.from_model(
            chat_session,
            model_name=model.model_name,
        ),
        messages=[
            MultimodalChatMessageResponse.from_model(item)
            for item in message_rows
        ],
    )


def chat_with_multimodal_model(
    session: Session,
    model_id: int,
    payload: MultimodalChatRequest,
    *,
    request_func: RequestFunc | None = None,
) -> MultimodalChatData:
    """对指定模型配置发起非流式聊天测试。"""

    request_impl = request_func or requests.request
    prepared = _prepare_chat_request(session, model_id, payload)
    logger.info(
        "多模态非流式聊天开始: model_id={}, existing_session_id={}, new_message_count={}, context_message_count={}",
        model_id,
        prepared.existing_session.id if prepared.existing_session else None,
        len(prepared.new_messages),
        len(prepared.context_messages),
    )
    normalized_payload = _build_gateway_chat_payload(
        model_name=prepared.model.model_name,
        messages=prepared.context_messages,
        stream=False,
    )
    result = _call_chat_endpoint(
        endpoint_url=prepared.model.endpoint_url,
        api_key=prepared.model.api_key,
        payload=normalized_payload,
        request_func=request_impl,
    )
    reply = _extract_chat_reply(result.payload)
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
    return MultimodalChatData(
        reply=reply,
        model_name=prepared.model.model_name,
        used_url=result.used_url,
        session_id=persisted_session.id or 0,
    )


def stream_chat_with_multimodal_model(
    session: Session,
    model_id: int,
    payload: MultimodalChatRequest,
    *,
    request_func: RequestFunc | None = None,
) -> Iterator[str]:
    """对指定模型配置发起流式聊天测试。"""

    request_impl = request_func or requests.request
    prepared = _prepare_chat_request(session, model_id, payload)
    logger.info(
        "多模态流式聊天准备完成: model_id={}, existing_session_id={}, new_message_count={}, context_message_count={}",
        model_id,
        prepared.existing_session.id if prepared.existing_session else None,
        len(prepared.new_messages),
        len(prepared.context_messages),
    )
    normalized_payload = _build_gateway_chat_payload(
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
            result = _call_chat_endpoint_stream(
                endpoint_url=prepared.model.endpoint_url,
                api_key=prepared.model.api_key,
                payload=normalized_payload,
                request_func=request_impl,
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


def _prepare_chat_request(
    session: Session,
    model_id: int,
    payload: MultimodalChatRequest,
) -> ChatPreparation:
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
    *,
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


def _message_row_to_payload(
    message_row: MultimodalChatMessage,
) -> MultimodalChatMessagePayload:
    """将数据库消息恢复为请求消息对象。"""

    return MultimodalChatMessagePayload(
        role=message_row.role,
        content=message_row.content,
        attachments=parse_attachments(message_row.attachments_json),
    )


def _list_chat_message_rows(
    session: Session,
    session_id: int,
) -> list[MultimodalChatMessage]:
    """按顺序查询会话消息。"""

    return session.exec(
        select(MultimodalChatMessage)
        .where(MultimodalChatMessage.session_id == session_id)
        .order_by(
            MultimodalChatMessage.sequence_no.asc(),
            MultimodalChatMessage.id.asc(),
        )
    ).all()


def _format_sse_event(event: str, data: dict[str, Any]) -> str:
    """构造 SSE 文本片段。"""

    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _get_chat_session_or_raise(
    session: Session,
    session_id: int,
) -> MultimodalChatSession:
    """按 ID 查询聊天会话，不存在时抛出统一异常。"""

    chat_session = session.get(MultimodalChatSession, session_id)
    if chat_session is None:
        raise AppException(
            code=ErrorCode.NOT_FOUND,
            message="聊天会话不存在",
            status_code=404,
        )
    return chat_session
