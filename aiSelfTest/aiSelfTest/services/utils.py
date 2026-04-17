"""Shared compatibility helpers."""

from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import Any
from urllib.parse import urlparse


IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "bmp", "webp", "svg"}
VIDEO_EXTENSIONS = {"mp4", "mov", "avi", "mkv", "webm", "flv", "m4v"}
REVIEW_SCHEMA_VERSION = 2


def now_iso() -> str:
    return datetime.now().isoformat()


def safe_json_loads(value: Any, fallback: Any = None) -> Any:
    if value is None or value == "":
        return fallback
    try:
        return json.loads(value)
    except Exception:
        return fallback


def safe_json_dumps(value: Any) -> str:
    return json.dumps(value if value is not None else None, ensure_ascii=False)


def trim_trailing_slash(value: str = "") -> str:
    return str(value or "").strip().rstrip("/")


def normalize_endpoint_url(value: str = "") -> str:
    return trim_trailing_slash(value)


def to_data_url(mime_type: str, data: bytes) -> str:
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def resolve_media_url(client_api_url: str, raw_url: Any) -> str | None:
    value = str(raw_url or "").strip()
    if not value:
        return None
    if value.lower().startswith(("http://", "https://")):
        return value
    normalized = value.lstrip("/")
    parsed = urlparse(client_api_url)
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}/weed/{normalized}"


def resolve_media_info(client_api_url: str, item: dict[str, Any]) -> dict[str, Any]:
    raw_file_url = str(item.get("fileUrl") or "").strip()
    normalized_file_url = raw_file_url.lstrip("/")
    raw_name = str(item.get("name") or "").strip()
    explicit_ext = str(item.get("fileExtension") or "").lower()
    inferred_from_url = normalized_file_url.split(".")[-1].lower() if "." in normalized_file_url else ""
    inferred_from_name = raw_name.split(".")[-1].lower() if "." in raw_name else ""
    extension = explicit_ext or inferred_from_url or inferred_from_name

    media_type = "unknown"
    if extension in IMAGE_EXTENSIONS:
        media_type = "image"
    if extension in VIDEO_EXTENSIONS:
        media_type = "video"
    return {"mediaType": media_type, "mediaUrl": resolve_media_url(client_api_url, normalized_file_url)}


def normalize_species_label(raw_species: Any) -> str:
    text = str(raw_species or "").strip()
    if not text:
        return "无"
    lowered = text.lower()
    if lowered in {"none", "null", "no", "empty", "unknown", "无法判断", "未识别", "无", "没有"}:
        return "无"
    if lowered in {"person", "human", "people", "man", "woman"}:
        return "人"
    return text[:60]


def is_submittable_species(value: Any) -> bool:
    normalized = normalize_species_label(value)
    return bool(normalized) and normalized != "无" and not normalized.startswith("识别失败:")


def normalize_compare_value(value: Any) -> str:
    return "".join(str(value or "").strip().lower().split())


def is_same_species(left: Any, right: Any) -> bool:
    a = normalize_compare_value(left)
    b = normalize_compare_value(right)
    if not a or not b:
        return False
    return a == b or a in b or b in a


def get_record_name(record: dict[str, Any]) -> str:
    return str(record.get("name") or record.get("speciesName") or "").strip()


def build_original_result(item: dict[str, Any]) -> str:
    species = str(item.get("spNameList") or "").strip()
    return species or "未识别物种"
