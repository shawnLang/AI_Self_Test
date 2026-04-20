"""Multimodal model configuration and gateway helpers."""

from __future__ import annotations

import json
from typing import Any

import requests
from sqlmodel import Session, select

from aiSelfTest.config import get_settings
from aiSelfTest.db.models import MultimodalModel
from aiSelfTest.db.session import session_scope
from aiSelfTest.logging import log_event
from aiSelfTest.services.utils import normalize_endpoint_url, now_iso, trim_trailing_slash


def build_auth_headers(api_key: str) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "X-API-Key": api_key,
        "api-key": api_key,
    }


def build_model_list_candidates(endpoint_url: str) -> list[str]:
    normalized = (
        trim_trailing_slash(endpoint_url)
        .removesuffix("/chat/completions")
        .removesuffix("/responses")
        .removesuffix("/models")
    )
    if not normalized:
        return []
    if normalized.endswith("/v1"):
        return [f"{normalized}/models", f"{normalized.removesuffix('/v1')}/models"]
    return [f"{normalized}/v1/models", f"{normalized}/models"]


def build_chat_completion_candidates(endpoint_url: str) -> list[str]:
    normalized = trim_trailing_slash(endpoint_url)
    if not normalized:
        return []
    if normalized.lower().endswith("/chat/completions"):
        return [normalized]
    base = normalized.removesuffix("/models").removesuffix("/responses")
    candidates = []
    if base.endswith("/v1"):
        candidates.append(f"{base}/chat/completions")
    candidates.extend([f"{base}/v1/chat/completions", f"{base}/chat/completions"])
    return list(dict.fromkeys(candidates))


def extract_detected_models(result_data: Any) -> list[str]:
    source_lists = []
    if isinstance(result_data, dict):
        source_lists = [
            result_data.get("data"),
            result_data.get("models"),
            result_data.get("results"),
            result_data.get("items"),
        ]
    names: list[str] = []
    for source in source_lists:
        if isinstance(source, list):
            for item in source:
                if isinstance(item, dict):
                    names.append(str(item.get("id") or item.get("name") or item.get("model") or "").strip())
    if isinstance(result_data, dict) and isinstance(result_data.get("model"), str):
        names.append(result_data["model"].strip())
    return list(dict.fromkeys([name for name in names if name]))


def _safe_json(response: requests.Response) -> Any:
    try:
        return response.json()
    except Exception:
        return {"rawText": response.text}


def detect_remote_models(endpoint_url: str, api_key: str) -> dict[str, Any]:
    settings = get_settings()
    errors = []
    for url in build_model_list_candidates(endpoint_url):
        try:
            response = requests.get(url, headers=build_auth_headers(api_key), timeout=settings.request_timeout_seconds)
            data = _safe_json(response)
            if not response.ok:
                error = data.get("error", {}) if isinstance(data, dict) else {}
                fallback = data.get("message", f"HTTP {response.status_code}") if isinstance(data, dict) else f"HTTP {response.status_code}"
                errors.append(f"{url}: {error.get('message') if isinstance(error, dict) else fallback}")
                continue
            models = extract_detected_models(data)
            if models:
                return {"models": models, "detectedUrl": url}
            errors.append(f"{url}: 未识别到模型列表")
        except Exception as exc:
            errors.append(f"{url}: {exc}")
    raise RuntimeError(errors[0] if errors else "无法自动检索模型列表")


def parse_assistant_message(result_data: Any) -> str:
    if not isinstance(result_data, dict):
        return ""
    message_content = (((result_data.get("choices") or [{}])[0]).get("message") or {}).get("content")
    if isinstance(message_content, str):
        return message_content.strip()
    if isinstance(message_content, list):
        return "\n".join(str(part.get("text") or "") for part in message_content if isinstance(part, dict)).strip()
    if isinstance(result_data.get("output_text"), str):
        return result_data["output_text"].strip()
    output = result_data.get("output")
    if isinstance(output, list):
        parts = []
        for item in output:
            for part in item.get("content", []) if isinstance(item, dict) else []:
                if isinstance(part, dict):
                    parts.append(str(part.get("text") or ""))
        return "\n".join(parts).strip()
    return ""


def parse_data_url_base64(data_url: str) -> tuple[str, str] | None:
    if not data_url.startswith("data:") or ";base64," not in data_url:
        return None
    header, data = data_url.split(";base64,", 1)
    return header.removeprefix("data:"), data


def build_attachment_parts(attachments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    for attachment in attachments:
        name = str(attachment.get("name") or "未命名附件").strip()
        mime_type = str(attachment.get("mimeType") or attachment.get("type") or "application/octet-stream").strip()
        text_content = str(attachment.get("textContent") or "").strip()
        data_url = str(attachment.get("dataUrl") or "").strip()
        if mime_type.startswith("image/") and data_url:
            parts.append({"type": "image_url", "image_url": {"url": data_url}})
            continue
        if mime_type.startswith("audio/") and data_url:
            parsed = parse_data_url_base64(data_url)
            if parsed:
                parsed_mime, base64_data = parsed
                parts.append({"type": "input_audio", "input_audio": {"data": base64_data, "format": parsed_mime.split("/")[-1] or "mp3"}})
                continue
        if text_content:
            parts.append({"type": "text", "text": f"附件《{name}》内容如下：\n{text_content[:12000]}"})
        else:
            parts.append({"type": "text", "text": f"用户上传了附件《{name}》，类型为 {mime_type}。当前接口按通用兼容模式发送，请结合附件信息回答。"})
    return parts


def normalize_chat_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = []
    for message in messages:
        if message.get("role") not in {"system", "user", "assistant"}:
            continue
        if message["role"] != "user":
            normalized.append({"role": message["role"], "content": str(message.get("content") or "")})
            continue
        text = str(message.get("content") or "").strip()
        content_parts = []
        if text:
            content_parts.append({"type": "text", "text": text})
        content_parts.extend(build_attachment_parts(message.get("attachments") if isinstance(message.get("attachments"), list) else []))
        normalized.append({"role": "user", "content": content_parts or [{"type": "text", "text": "请查看附件并回答。"}]})
    return normalized


def chat_with_multimodal_model(model: MultimodalModel, messages: list[dict[str, Any]]) -> dict[str, Any]:
    settings = get_settings()
    errors = []
    payload = {
        "model": model.model_name,
        "messages": normalize_chat_messages(messages),
        "temperature": 0.2,
        "max_tokens": 1200,
    }
    for url in build_chat_completion_candidates(model.endpoint_url):
        try:
            response = requests.post(url, headers=build_auth_headers(model.api_key), json=payload, timeout=settings.request_timeout_seconds)
            data = _safe_json(response)
            log_event("model_gateway", "chat completion attempted", model_id=model.id, url=url, status=response.status_code)
            if not response.ok:
                error = data.get("error", {}) if isinstance(data, dict) else {}
                fallback = data.get("message", f"HTTP {response.status_code}") if isinstance(data, dict) else f"HTTP {response.status_code}"
                errors.append(f"{url}: {error.get('message') if isinstance(error, dict) else fallback}")
                continue
            assistant_message = parse_assistant_message(data)
            if assistant_message:
                return {"assistantMessage": assistant_message, "requestUrl": url, "raw": data}
            errors.append(f"{url}: 模型已响应，但未返回可解析文本")
        except Exception as exc:
            errors.append(f"{url}: {exc}")
    raise RuntimeError(errors[0] if errors else "多模态模型调用失败")


def map_multimodal_model(row: MultimodalModel) -> dict[str, Any]:
    try:
        detected = json.loads(row.detected_models_json or "[]")
    except Exception:
        detected = []
    return {
        "id": row.id,
        "modelName": row.model_name,
        "endpointUrl": row.endpoint_url,
        "apiKey": row.api_key,
        "status": row.status or "active",
        "detectedModels": detected,
        "lastDetectedAt": row.last_detected_at,
        "createdAt": row.created_at,
        "updatedAt": row.updated_at,
    }


def ensure_default_model_registered() -> None:
    settings = get_settings()
    endpoint_url = normalize_endpoint_url(settings.omlx_api_url)
    api_key = settings.omlx_api_key.strip()
    model_name = settings.omlx_model.strip()
    if not endpoint_url or not api_key or not model_name:
        return
    with session_scope() as session:
        existing = session.exec(
            select(MultimodalModel).where(
                MultimodalModel.endpoint_url == endpoint_url,
                MultimodalModel.model_name == model_name,
            )
        ).first()
        now = now_iso()
        if existing:
            detected = json.loads(existing.detected_models_json or "[]")
            existing.api_key = api_key
            existing.status = "active"
            existing.detected_models_json = json.dumps(list(dict.fromkeys([*detected, model_name])), ensure_ascii=False)
            existing.last_detected_at = existing.last_detected_at or now
            existing.updated_at = now
            session.add(existing)
            return
        session.add(
            MultimodalModel(
                model_name=model_name,
                endpoint_url=endpoint_url,
                api_key=api_key,
                status="active",
                detected_models_json=json.dumps([model_name], ensure_ascii=False),
                last_detected_at=now,
                created_at=now,
                updated_at=now,
            )
        )
