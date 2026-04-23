"""多模态模型管理、会话与聊天测试服务。"""

from __future__ import annotations

import binascii
from dataclasses import dataclass
from datetime import datetime
import json
import re
from typing import Any, Callable, Iterator

import requests
from loguru import logger
from requests import Response
from requests.exceptions import RequestException
from sqlmodel import Session, select

from aiSelfTest.config import get_settings
from aiSelfTest.exceptions import AppException
from aiSelfTest.models.multimodal_chat import (
    MultimodalChatMessage,
    MultimodalChatSession,
)
from aiSelfTest.models.multimodal_model import MultimodalModel
from aiSelfTest.schemas.multimodal_model import (
    MASK_PLACEHOLDER,
    MultimodalAttachmentPayload,
    MultimodalChatData,
    MultimodalChatMessagePayload,
    MultimodalChatMessageResponse,
    MultimodalChatRequest,
    MultimodalChatSessionDetailData,
    MultimodalChatSessionListData,
    MultimodalChatSessionResponse,
    MultimodalModelCreateRequest,
    MultimodalModelDetectData,
    MultimodalModelDetectRequest,
    MultimodalModelResponse,
    MultimodalModelUpdateRequest,
    parse_attachments,
    parse_detected_models,
    serialize_attachments,
    serialize_detected_models,
)


RequestFunc = Callable[..., Response]
DETECT_PATH_SUFFIXES = ("/v1/models", "/models")
CHAT_PATH_SUFFIXES = ("/v1/chat/completions", "/chat/completions")
KNOWN_ENDPOINT_SUFFIXES = DETECT_PATH_SUFFIXES + CHAT_PATH_SUFFIXES
AUTH_HEADER_VARIANTS = (
    ("Authorization", "Bearer {api_key}"),
    ("X-API-Key", "{api_key}"),
    ("api-key", "{api_key}"),
)
TEXT_ATTACHMENT_LIMIT = 4000
DATA_URL_PATTERN = re.compile(r"^data:(?P<mime>[^;]+);base64,(?P<data>.+)$", re.IGNORECASE)


@dataclass(frozen=True)
class GatewayCallResult:
    """模型网关调用结果。"""

    payload: dict[str, Any]
    used_url: str


@dataclass(frozen=True)
class StreamGatewayCallResult:
    """流式模型网关调用结果。"""

    used_url: str
    chunks: Iterator[str]


@dataclass(frozen=True)
class ChatPreparation:
    """聊天调用前的上下文准备结果。"""

    model: MultimodalModel
    existing_session: MultimodalChatSession | None
    context_messages: list[MultimodalChatMessagePayload]
    new_messages: list[MultimodalChatMessagePayload]


def list_multimodal_models(session: Session) -> list[MultimodalModelResponse]:
    """查询全部模型配置。"""

    models = session.exec(select(MultimodalModel).order_by(MultimodalModel.id.desc())).all()
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
    return MultimodalModelResponse.from_model(model)


def delete_multimodal_model(session: Session, model_id: int) -> int:
    """删除模型配置。"""

    model = _get_multimodal_model_or_raise(session, model_id)
    session.delete(model)
    session.commit()
    return model_id


def detect_multimodal_models(
    payload: MultimodalModelDetectRequest,
    *,
    request_func: RequestFunc | None = None,
) -> MultimodalModelDetectData:
    """探测远端可用模型。"""

    request_impl = request_func or requests.request
    result = _call_models_endpoint(
        endpoint_url=payload.endpoint_url,
        api_key=payload.api_key,
        request_func=request_impl,
    )
    models = _extract_model_names(result.payload)
    recommended_model = models[0] if models else ""
    return MultimodalModelDetectData(
        models=models,
        detected_url=result.used_url,
        recommended_model=recommended_model,
    )


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
    return MultimodalChatSessionListData(
        items=[
            MultimodalChatSessionResponse.from_model(item, model_name=model.model_name)
            for item in sessions
        ]
    )


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
    return session_id


def get_multimodal_chat_session_detail(
    session: Session,
    session_id: int,
) -> MultimodalChatSessionDetailData:
    """查询聊天会话详情。"""

    chat_session = _get_chat_session_or_raise(session, session_id)
    model = _get_multimodal_model_or_raise(session, chat_session.model_id)
    message_rows = _list_chat_message_rows(session, chat_session.id or 0)
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
            code=5001,
            message="模型调用成功，但未解析到回复内容",
            status_code=502,
        )

    persisted_session = _persist_chat_turn(
        session=session,
        prepared=prepared,
        reply=reply,
        used_url=result.used_url,
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
    normalized_payload = _build_gateway_chat_payload(
        model_name=prepared.model.model_name,
        messages=prepared.context_messages,
        stream=True,
    )

    def event_stream() -> Iterator[str]:
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
                    code=5001,
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
            code=1001,
            message="模型已停用，无法进行测试",
            status_code=400,
        )

    existing_session: MultimodalChatSession | None = None
    context_messages: list[MultimodalChatMessagePayload] = []
    if payload.session_id is not None:
        existing_session = _get_chat_session_or_raise(session, payload.session_id)
        if existing_session.model_id != model_id:
            raise AppException(
                code=1001,
                message="会话与当前模型不匹配，无法继续对话",
                status_code=400,
            )
        stored_rows = _list_chat_message_rows(session, existing_session.id or 0)
        context_messages.extend(_message_row_to_payload(item) for item in stored_rows)

    context_messages.extend(payload.messages)
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
    return chat_session


def _call_models_endpoint(
    *,
    endpoint_url: str,
    api_key: str,
    request_func: RequestFunc,
) -> GatewayCallResult:
    """轮询模型列表接口，直到成功为止。"""

    errors: list[str] = []
    for candidate_url in _build_candidate_urls(endpoint_url, DETECT_PATH_SUFFIXES):
        for headers in _auth_header_variants(api_key):
            try:
                logger.info("开始探测模型列表: url={}", candidate_url)
                response = request_func(
                    "GET",
                    candidate_url,
                    headers=headers,
                    timeout=get_settings().request_timeout_seconds,
                )
            except RequestException as exc:
                errors.append(f"{candidate_url}: {exc}")
                continue

            if response.status_code == 200:
                payload = _safe_json(response)
                return GatewayCallResult(payload=payload, used_url=candidate_url)

            errors.append(_build_response_error(candidate_url, response))

    raise AppException(
        code=5001,
        message=_join_gateway_errors("模型探测失败", errors),
        status_code=502,
    )


def _call_chat_endpoint(
    *,
    endpoint_url: str,
    api_key: str,
    payload: dict[str, Any],
    request_func: RequestFunc,
) -> GatewayCallResult:
    """轮询非流式聊天接口，直到成功为止。"""

    errors: list[str] = []
    for candidate_url in _build_candidate_urls(endpoint_url, CHAT_PATH_SUFFIXES):
        for headers in _auth_header_variants(api_key):
            try:
                logger.info("开始调用多模态模型: url={}", candidate_url)
                response = request_func(
                    "POST",
                    candidate_url,
                    headers=headers,
                    json=payload,
                    timeout=get_settings().request_timeout_seconds,
                )
            except RequestException as exc:
                errors.append(f"{candidate_url}: {exc}")
                continue

            if response.status_code == 200:
                return GatewayCallResult(
                    payload=_safe_json(response),
                    used_url=candidate_url,
                )

            errors.append(_build_response_error(candidate_url, response))

    raise AppException(
        code=5001,
        message=_join_gateway_errors("模型调用失败", errors),
        status_code=502,
    )


def _call_chat_endpoint_stream(
    *,
    endpoint_url: str,
    api_key: str,
    payload: dict[str, Any],
    request_func: RequestFunc,
) -> StreamGatewayCallResult:
    """轮询流式聊天接口，直到成功为止。"""

    errors: list[str] = []
    for candidate_url in _build_candidate_urls(endpoint_url, CHAT_PATH_SUFFIXES):
        for headers in _auth_header_variants(api_key):
            try:
                logger.info("开始流式调用多模态模型: url={}", candidate_url)
                response = request_func(
                    "POST",
                    candidate_url,
                    headers=headers,
                    json=payload,
                    timeout=get_settings().request_timeout_seconds,
                    stream=True,
                )
            except RequestException as exc:
                errors.append(f"{candidate_url}: {exc}")
                continue

            if response.status_code == 200:
                return StreamGatewayCallResult(
                    used_url=candidate_url,
                    chunks=_iter_gateway_stream_chunks(response),
                )

            errors.append(_build_response_error(candidate_url, response))

    raise AppException(
        code=5001,
        message=_join_gateway_errors("模型流式调用失败", errors),
        status_code=502,
    )


def _iter_gateway_stream_chunks(response: Response) -> Iterator[str]:
    """遍历上游流式响应并提取文本增量。"""

    headers = getattr(response, "headers", {}) or {}
    content_type = str(headers.get("Content-Type") or headers.get("content-type") or "")
    close_func = getattr(response, "close", None)

    try:
        if "text/event-stream" not in content_type.lower():
            payload = _safe_json(response)
            reply = _extract_chat_reply(payload)
            if reply:
                yield reply
                return
            raise AppException(
                code=5001,
                message="模型网关未返回可解析的流式内容",
                status_code=502,
            )

        data_lines: list[str] = []
        for raw_line in response.iter_lines(decode_unicode=True):
            if raw_line is None:
                continue
            line = str(raw_line).strip()
            if not line:
                yield from _flush_sse_data_lines(data_lines)
                data_lines.clear()
                continue
            if line.startswith(":"):
                continue
            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip())

        if data_lines:
            yield from _flush_sse_data_lines(data_lines)
    finally:
        if callable(close_func):
            close_func()


def _flush_sse_data_lines(data_lines: list[str]) -> Iterator[str]:
    """解析一次 SSE 事件中的数据行。"""

    payload_text = "\n".join(data_lines).strip()
    if not payload_text or payload_text == "[DONE]":
        return

    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError as exc:
        raise AppException(
            code=5001,
            message=f"模型流式响应 JSON 解析失败: {payload_text}",
            status_code=502,
        ) from exc

    if not isinstance(payload, dict):
        return

    error_payload = payload.get("error")
    if isinstance(error_payload, dict):
        error_message = str(error_payload.get("message") or "模型流式调用失败").strip()
        raise AppException(code=5001, message=error_message, status_code=502)

    delta_text = _extract_stream_delta(payload)
    if delta_text:
        yield delta_text


def _build_gateway_chat_payload(
    *,
    model_name: str,
    messages: list[MultimodalChatMessagePayload],
    stream: bool,
) -> dict[str, Any]:
    """构造发送给模型网关的聊天载荷。"""

    payload: dict[str, Any] = {
        "model": model_name,
        "messages": [
            _normalize_chat_message(message)
            for message in messages
        ],
    }
    if stream:
        payload["stream"] = True
    return payload


def _normalize_chat_message(message: MultimodalChatMessagePayload) -> dict[str, Any]:
    """将聊天消息转换为兼容 chat/completions 的结构。"""

    parts: list[dict[str, Any]] = []
    content_text = message.content.strip()
    if content_text:
        parts.append({"type": "text", "text": content_text})

    for attachment in message.attachments:
        parts.extend(_normalize_attachment(attachment))

    if not parts:
        return {"role": message.role, "content": ""}

    if len(parts) == 1 and parts[0]["type"] == "text":
        return {"role": message.role, "content": parts[0]["text"]}

    return {"role": message.role, "content": parts}


def _normalize_attachment(attachment: MultimodalAttachmentPayload) -> list[dict[str, Any]]:
    """将附件归一化为模型可识别的消息片段。"""

    if attachment.kind == "image" and attachment.data_url:
        return [
            {
                "type": "image_url",
                "image_url": {"url": attachment.data_url},
            }
        ]

    if attachment.kind == "audio" and attachment.data_url:
        audio_content = _parse_audio_data_url(attachment.data_url)
        if audio_content is not None:
            return [
                {
                    "type": "input_audio",
                    "input_audio": audio_content,
                }
            ]

    if attachment.text_content:
        preview_text = attachment.text_content.strip()[:TEXT_ATTACHMENT_LIMIT]
        return [
            {
                "type": "text",
                "text": f"附件《{attachment.name}》内容如下：\n{preview_text}",
            }
        ]

    return [
        {
            "type": "text",
            "text": (
                f"收到附件《{attachment.name}》，"
                f"类型为 {attachment.kind}，MIME 为 {attachment.mime_type}。"
                "当前接口仅提供说明性文本，请结合上下文回答。"
            ),
        }
    ]


def _parse_audio_data_url(data_url: str) -> dict[str, str] | None:
    """解析音频 data URL。"""

    match = DATA_URL_PATTERN.match(data_url)
    if match is None:
        return None

    mime_type = match.group("mime").lower()
    base64_data = match.group("data")
    try:
        binascii.a2b_base64(base64_data)
    except binascii.Error:
        return None

    audio_format = mime_type.split("/")[-1].split("+")[0]
    if audio_format == "mpeg":
        audio_format = "mp3"

    return {
        "data": base64_data,
        "format": audio_format,
    }


def _extract_model_names(payload: dict[str, Any]) -> list[str]:
    """从探测响应中提取模型名列表。"""

    candidates = payload.get("data")
    if not isinstance(candidates, list):
        candidates = payload.get("models")

    if not isinstance(candidates, list):
        return []

    models: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        model_name = _extract_model_name(item)
        if not model_name or model_name in seen:
            continue
        seen.add(model_name)
        models.append(model_name)
    return models


def _extract_model_name(item: Any) -> str:
    """从单个模型项中提取模型名。"""

    if isinstance(item, str):
        return item.strip()

    if not isinstance(item, dict):
        return ""

    for key in ("id", "model", "name"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _extract_chat_reply(payload: dict[str, Any]) -> str:
    """从模型响应中提取文本回复。"""

    direct_output_text = payload.get("output_text")
    if isinstance(direct_output_text, str) and direct_output_text.strip():
        return direct_output_text.strip()

    choices = payload.get("choices")
    if isinstance(choices, list):
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            message = choice.get("message")
            extracted_text = _extract_text_from_content(message)
            if extracted_text:
                return extracted_text
            extracted_text = _extract_text_from_content(choice.get("text"))
            if extracted_text:
                return extracted_text

    output_items = payload.get("output")
    if isinstance(output_items, list):
        collected_texts: list[str] = []
        for item in output_items:
            extracted_text = _extract_text_from_content(item)
            if extracted_text:
                collected_texts.append(extracted_text)
        if collected_texts:
            return "\n".join(collected_texts)

    return ""


def _extract_stream_delta(payload: dict[str, Any]) -> str:
    """从流式 chunk 中提取文本增量。"""

    direct_output_text = payload.get("output_text")
    if isinstance(direct_output_text, str) and direct_output_text:
        return direct_output_text

    choices = payload.get("choices")
    if isinstance(choices, list):
        parts: list[str] = []
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            for candidate in (
                choice.get("delta"),
                choice.get("message"),
                choice.get("text"),
                choice.get("content"),
            ):
                extracted_text = _extract_stream_text(candidate)
                if extracted_text:
                    parts.append(extracted_text)
        if parts:
            return "".join(parts)

    output_items = payload.get("output")
    if isinstance(output_items, list):
        parts = [
            _extract_stream_text(item)
            for item in output_items
        ]
        return "".join(part for part in parts if part)

    return ""


def _extract_stream_text(content: Any) -> str:
    """递归提取流式响应中的文本片段。"""

    if isinstance(content, str):
        return content

    if isinstance(content, dict):
        text_value = content.get("text")
        if isinstance(text_value, str):
            return text_value

        delta_value = content.get("delta")
        extracted_delta = _extract_stream_text(delta_value)
        if extracted_delta:
            return extracted_delta

        content_value = content.get("content")
        if isinstance(content_value, list):
            return "".join(_extract_stream_text(item) for item in content_value)
        return _extract_stream_text(content_value)

    if isinstance(content, list):
        return "".join(_extract_stream_text(item) for item in content)

    return ""


def _extract_text_from_content(content: Any) -> str:
    """从不同结构的 content 中递归提取文本。"""

    if isinstance(content, str):
        return content.strip()

    if isinstance(content, dict):
        for key in ("text", "content", "output_text"):
            extracted_text = _extract_text_from_content(content.get(key))
            if extracted_text:
                return extracted_text
        return ""

    if isinstance(content, list):
        texts: list[str] = []
        for item in content:
            extracted_text = _extract_text_from_content(item)
            if extracted_text:
                texts.append(extracted_text)
        return "\n".join(texts).strip()

    return ""


def _auth_header_variants(api_key: str) -> list[dict[str, str]]:
    """生成认证头候选列表。"""

    return [
        {header_name: value_template.format(api_key=api_key)}
        for header_name, value_template in AUTH_HEADER_VARIANTS
    ]


def _build_candidate_urls(endpoint_url: str, suffixes: tuple[str, ...]) -> list[str]:
    """根据输入地址生成候选 URL 列表。"""

    normalized_url = endpoint_url.rstrip("/")
    direct_url = normalized_url if any(
        normalized_url.endswith(suffix) for suffix in suffixes
    ) else None
    root_url = _strip_known_suffix(normalized_url)

    candidates: list[str] = []
    if direct_url:
        candidates.append(direct_url)

    for suffix in suffixes:
        candidate_url = _append_suffix(root_url, suffix)
        if candidate_url not in candidates:
            candidates.append(candidate_url)
    return candidates


def _strip_known_suffix(endpoint_url: str) -> str:
    """剥离已知的模型网关后缀，得到根地址。"""

    normalized_url = endpoint_url.rstrip("/")
    for suffix in sorted(KNOWN_ENDPOINT_SUFFIXES, key=len, reverse=True):
        if normalized_url.endswith(suffix):
            return normalized_url[: -len(suffix)] or normalized_url
    return normalized_url


def _append_suffix(root_url: str, suffix: str) -> str:
    """将后缀追加到根地址。"""

    normalized_root = root_url.rstrip("/")
    normalized_suffix = suffix
    if normalized_root.endswith("/v1") and suffix.startswith("/v1/"):
        normalized_suffix = suffix[3:]
    return f"{normalized_root}{normalized_suffix}"


def _safe_json(response: Response) -> dict[str, Any]:
    """安全解析响应 JSON。"""

    try:
        payload = response.json()
    except ValueError as exc:
        raise AppException(
            code=5001,
            message=f"模型网关返回了非 JSON 响应: {response.text}",
            status_code=502,
        ) from exc

    if not isinstance(payload, dict):
        raise AppException(
            code=5001,
            message="模型网关返回 JSON 结构异常",
            status_code=502,
        )
    return payload


def _build_response_error(candidate_url: str, response: Response) -> str:
    """构造网关错误描述。"""

    response_text = str(getattr(response, "text", "")).strip()
    if len(response_text) > 200:
        response_text = response_text[:200]
    return f"{candidate_url}: HTTP {response.status_code} {response_text}"


def _join_gateway_errors(prefix: str, errors: list[str]) -> str:
    """拼接模型网关错误列表。"""

    if not errors:
        return prefix
    return f"{prefix}: {'; '.join(errors)}"


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


def _get_multimodal_model_or_raise(session: Session, model_id: int) -> MultimodalModel:
    """按 ID 查询模型配置，不存在时抛出统一异常。"""

    model = session.get(MultimodalModel, model_id)
    if model is None:
        raise AppException(
            code=1002,
            message="模型配置不存在",
            status_code=404,
        )
    return model


def _get_chat_session_or_raise(
    session: Session,
    session_id: int,
) -> MultimodalChatSession:
    """按 ID 查询聊天会话，不存在时抛出统一异常。"""

    chat_session = session.get(MultimodalChatSession, session_id)
    if chat_session is None:
        raise AppException(
            code=1002,
            message="聊天会话不存在",
            status_code=404,
        )
    return chat_session
