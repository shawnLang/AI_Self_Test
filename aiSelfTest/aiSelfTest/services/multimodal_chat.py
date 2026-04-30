"""多模态聊天会话与消息持久化服务。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterator

from aiSelfTest.exceptions import AppException, ErrorCode
from aiSelfTest.models.multimodal_chat import (
    MultimodalChatMessage,
    MultimodalChatSession,
)
from aiSelfTest.models.multimodal_model import MultimodalModel
from aiSelfTest.schemas.multimodal_model import (
    MultimodalChatMessagePayload,
    MultimodalChatRequest,
    parse_attachments,
    serialize_attachments,
)
from aiSelfTest.services.multimodal_attachment import build_gateway_chat_payload
from aiSelfTest.services.multimodal_gateway import (
    _call_chat_endpoint_stream,
)
from aiSelfTest.services.multimodal_model_crud import get_multimodal_model_or_raise
from loguru import logger
from sqlmodel import Session, select, asc


@dataclass(frozen=True)
class ChatPreparation:
    """聊天调用前的上下文准备结果。"""

    model: MultimodalModel
    existing_session: MultimodalChatSession | None
    context_messages: list[MultimodalChatMessagePayload]
    new_messages: list[MultimodalChatMessagePayload]


def stream_chat_with_multimodal_model(session: Session, model_id: int, payload: MultimodalChatRequest) -> Iterator[str]:
    """对指定模型配置发起流式聊天测试。"""

    prepared = prepare_chat_request(session, model_id, payload)
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
            result = _call_chat_endpoint_stream(
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

            persisted_session = persist_chat_turn(
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


def prepare_chat_request(session: Session, model_id: int, payload: MultimodalChatRequest) -> ChatPreparation:
    """准备聊天上下文。"""

    model = get_multimodal_model_or_raise(session, model_id)
    if model.status != "启用":
        raise AppException(
            code=ErrorCode.PARAM_INVALID,
            message="模型已停用，无法进行测试",
            status_code=400,
        )

    existing_session: MultimodalChatSession | None = None
    context_messages: list[MultimodalChatMessagePayload] = []
    if payload.session_id is not None:
        existing_session = get_chat_session_or_raise(session, payload.session_id)
        if existing_session.model_id != model_id:
            raise AppException(
                code=ErrorCode.PARAM_INVALID,
                message="会话与当前模型不匹配，无法继续对话",
                status_code=400,
            )
        stored_rows = list_chat_message_rows(session, existing_session.id or 0)
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


def persist_chat_turn(session: Session, prepared: ChatPreparation, reply: str,
                      used_url: str) -> MultimodalChatSession:
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


def _message_row_to_payload(message_row: MultimodalChatMessage) -> MultimodalChatMessagePayload:
    """将数据库消息恢复为请求消息对象。"""

    return MultimodalChatMessagePayload(
        role=message_row.role,
        content=message_row.content,
        attachments=parse_attachments(message_row.attachments_json),
    )


def list_chat_message_rows(session: Session, session_id: int) -> list[MultimodalChatMessage]:
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


def get_chat_session_or_raise(session: Session, session_id: int) -> MultimodalChatSession:
    """按 ID 查询聊天会话，不存在时抛出统一异常。"""

    chat_session = session.get(MultimodalChatSession, session_id)
    if chat_session is None:
        raise AppException(
            code=ErrorCode.NOT_FOUND,
            message="聊天会话不存在",
            status_code=404,
        )
    return chat_session
