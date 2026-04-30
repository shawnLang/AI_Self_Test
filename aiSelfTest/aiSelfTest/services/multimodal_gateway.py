"""多模态模型网关 URL、认证头与响应解析工具。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterator

import requests
from aiSelfTest.config import get_settings
from aiSelfTest.exceptions import AppException, ErrorCode
from loguru import logger
from requests import Response
from requests.exceptions import RequestException

DETECT_PATH_SUFFIXES = ("/v1/models", "/models")
CHAT_PATH_SUFFIXES = ("/v1/chat/completions", "/chat/completions")
KNOWN_ENDPOINT_SUFFIXES = DETECT_PATH_SUFFIXES + CHAT_PATH_SUFFIXES
AUTH_HEADER_VARIANTS = (
    ("Authorization", "Bearer {api_key}"),
    ("X-API-Key", "{api_key}"),
    ("api-key", "{api_key}"),
)


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


def call_models_endpoint(endpoint_url: str, api_key: str) -> GatewayCallResult:
    """轮询模型列表接口，直到成功为止。"""

    errors: list[str] = []
    for candidate_url in _build_candidate_urls(endpoint_url, DETECT_PATH_SUFFIXES):
        for headers in _auth_header_variants(api_key):
            try:
                logger.info("开始探测模型列表: url={}", candidate_url)
                response = requests.get(
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
        code=ErrorCode.INTERNAL_ERROR,
        message=_join_gateway_errors("模型探测失败", errors),
        status_code=502,
    )


def call_chat_endpoint(endpoint_url: str, api_key: str, payload: dict[str, Any]) -> GatewayCallResult:
    """轮询非流式聊天接口，直到成功为止。"""

    errors: list[str] = []
    for candidate_url in _build_candidate_urls(endpoint_url, CHAT_PATH_SUFFIXES):
        for headers in _auth_header_variants(api_key):
            try:
                logger.info("开始调用多模态模型: url={}", candidate_url)
                response = requests.post(
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
        code=ErrorCode.INTERNAL_ERROR,
        message=_join_gateway_errors("模型调用失败", errors),
        status_code=502,
    )


def _call_chat_endpoint_stream(endpoint_url: str, api_key: str, payload: dict[str, Any]) -> StreamGatewayCallResult:
    """轮询流式聊天接口，直到成功为止。"""

    errors: list[str] = []
    for candidate_url in _build_candidate_urls(endpoint_url, CHAT_PATH_SUFFIXES):
        for headers in _auth_header_variants(api_key):
            try:
                logger.info("开始流式调用多模态模型: url={}", candidate_url)
                response = requests.post(
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
        code=ErrorCode.INTERNAL_ERROR,
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
            reply = extract_chat_reply(payload)
            if reply:
                yield reply
                return
            raise AppException(
                code=ErrorCode.INTERNAL_ERROR,
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
            code=ErrorCode.INTERNAL_ERROR,
            message=f"模型流式响应 JSON 解析失败: {payload_text}",
            status_code=502,
        ) from exc

    if not isinstance(payload, dict):
        return

    error_payload = payload.get("error")
    if isinstance(error_payload, dict):
        error_message = str(error_payload.get("message") or "模型流式调用失败").strip()
        raise AppException(code=ErrorCode.INTERNAL_ERROR, message=error_message, status_code=502)

    delta_text = _extract_stream_delta(payload)
    if delta_text:
        yield delta_text


def extract_model_names(payload: dict[str, Any]) -> list[str]:
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


def extract_chat_reply(payload: dict[str, Any]) -> str:
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
            code=ErrorCode.INTERNAL_ERROR,
            message=f"模型网关返回了非 JSON 响应: {response.text}",
            status_code=502,
        ) from exc

    if not isinstance(payload, dict):
        raise AppException(
            code=ErrorCode.INTERNAL_ERROR,
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
