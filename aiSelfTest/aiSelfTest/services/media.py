"""Media loading, image cropping, and model grounding helpers."""

from __future__ import annotations

from io import BytesIO
from typing import Any

import requests
from PIL import Image

from ..config import get_settings
from ..logging import summarize_attachment
from .utils import resolve_media_url, to_data_url


def normalize_bounding_box(record: dict[str, Any]) -> dict[str, int] | None:
    try:
        minx = float(record.get("minx"))
        miny = float(record.get("miny"))
        maxx = float(record.get("maxx"))
        maxy = float(record.get("maxy"))
    except (TypeError, ValueError):
        return None
    if maxx <= minx or maxy <= miny:
        return None
    return {
        "minx": int(minx),
        "miny": int(miny),
        "maxx": int(maxx),
        "maxy": int(maxy),
        "width": int(maxx - minx),
        "height": int(maxy - miny),
    }


def resolve_grounding_media_url(client_api_url: str, detail: dict[str, Any], media_info: dict[str, Any]) -> str | None:
    if media_info.get("mediaType") == "image":
        return media_info.get("mediaUrl")
    if media_info.get("mediaType") == "video":
        return resolve_media_url(client_api_url, detail.get("coverUrl"))
    return None


def load_grounding_source(client_api_url: str, detail: dict[str, Any], media_info: dict[str, Any]) -> dict[str, Any]:
    media_url = resolve_grounding_media_url(client_api_url, detail, media_info)
    if not media_url:
        raise RuntimeError("视频缺少可用封面帧" if media_info.get("mediaType") == "video" else "缺少可裁剪图片地址")
    settings = get_settings()
    response = requests.get(media_url, timeout=settings.media_timeout_seconds)
    if not response.ok:
        raise RuntimeError(f"媒体获取失败: HTTP {response.status_code}")
    data = response.content
    try:
        image = Image.open(BytesIO(data)).convert("RGB")
    except Exception as exc:
        raise RuntimeError(f"无法解析图片尺寸: {response.headers.get('content-type', 'unknown')}") from exc
    return {
        "buffer": data,
        "image": image,
        "mimeType": response.headers.get("content-type", "image/jpeg").split(";")[0].strip(),
        "width": image.width,
        "height": image.height,
        "summary": summarize_attachment(data, response.headers.get("content-type", ""), ""),
    }


def normalize_crop_box(source: dict[str, Any], box: dict[str, int]) -> dict[str, int]:
    safe_box = {
        "minx": max(0, int(box["minx"])),
        "miny": max(0, int(box["miny"])),
        "maxx": min(int(source["width"]), int(box["maxx"])),
        "maxy": min(int(source["height"]), int(box["maxy"])),
    }
    safe_box["width"] = safe_box["maxx"] - safe_box["minx"]
    safe_box["height"] = safe_box["maxy"] - safe_box["miny"]
    if safe_box["width"] <= 0 or safe_box["height"] <= 0:
        raise RuntimeError("bbox 超出图片范围")
    return safe_box


def build_record_grounding(record: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    box = normalize_bounding_box(record)
    if not box:
        return {
            "ok": False,
            "groundingStatus": "invalid-bbox",
            "errorMessage": "recordData 缺少有效 bbox 坐标",
        }
    try:
        safe_box = normalize_crop_box(source, box)
        image: Image.Image = source["image"]
        cropped = image.crop((safe_box["minx"], safe_box["miny"], safe_box["maxx"], safe_box["maxy"]))
        output = BytesIO()
        cropped.save(output, format="PNG")
        return {
            "ok": True,
            "groundingStatus": "bbox-crop",
            "imageUrl": to_data_url("image/png", output.getvalue()),
            "imageMimeType": "image/png",
            "groundingMethod": "pillow-png",
            "bbox": safe_box,
            "sourceSize": {"width": source["width"], "height": source["height"]},
            "cropSize": {"width": safe_box["width"], "height": safe_box["height"]},
        }
    except Exception as exc:
        return {"ok": False, "groundingStatus": "invalid-bbox", "errorMessage": str(exc)}
