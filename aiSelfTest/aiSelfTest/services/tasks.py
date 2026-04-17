"""Task compatibility mapping, query, and background execution services."""

from __future__ import annotations

import asyncio
import json
import random
import re
import threading
import time
from typing import Any

import requests
from sqlmodel import Session, select

from ..config import get_settings
from ..db.models import Client, Review, Task
from ..db.session import session_scope
from ..logging import log_error, log_event
from .client_api import request_client_api
from .media import build_record_grounding, load_grounding_source
from .utils import (
    REVIEW_SCHEMA_VERSION,
    build_original_result,
    get_record_name,
    is_same_species,
    is_submittable_species,
    normalize_species_label,
    now_iso,
    resolve_media_info,
    resolve_media_url,
    safe_json_dumps,
    safe_json_loads,
)


_running_tasks: dict[int, asyncio.Task] = {}
_stop_flags: dict[int, threading.Event] = {}


def normalize_date_filter_value(value: Any) -> str:
    trimmed = str(value or "").strip()
    if not trimmed:
        return ""
    match = re.match(r"^(\d{4}-\d{2}-\d{2})", trimmed)
    return match.group(1) if match else trimmed


def normalize_date_time_boundary(value: Any, boundary_time: str) -> str:
    trimmed = str(value or "").strip()
    if not trimmed:
        return ""
    if re.search(r"[T\s]\d{2}:\d{2}:\d{2}", trimmed):
        return trimmed
    date_value = normalize_date_filter_value(trimmed)
    return f"{date_value} {boundary_time}" if date_value else ""


def normalize_number_list(value: Any) -> list[int]:
    if value is None or value == "" or value == "all":
        return []
    values = value if isinstance(value, list) else [value]
    normalized = []
    for item in values:
        try:
            number = int(item)
        except (TypeError, ValueError):
            continue
        if number not in normalized:
            normalized.append(number)
    return normalized


def normalize_single_number_value(value: Any) -> int | None:
    if value is None or value == "" or value == "all":
        return None
    raw = value[0] if isinstance(value, list) and value else value
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value or default)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def normalize_task_file_bmp_value(value: Any) -> str:
    if value is None or value == "" or value == "all":
        return "all"
    raw = value[0] if isinstance(value, list) and value else value
    trimmed = str(raw or "").strip().lower()
    if not trimmed or trimmed == "all":
        return "all"
    if trimmed in {"image", "video", "audio"}:
        return trimmed
    if trimmed in {"0", "1"}:
        return "image"
    if trimmed == "2":
        return "video"
    if trimmed == "3":
        return "audio"
    return "all"


def normalize_legacy_saved_task_filters(raw_filters: dict[str, Any]) -> dict[str, Any]:
    filters = dict(raw_filters or {})
    file_bmp_value = filters.get("fileBmp")
    if isinstance(file_bmp_value, list):
        file_bmp_value = file_bmp_value[0] if file_bmp_value else None
    normalized = str(file_bmp_value if file_bmp_value is not None else "").strip()
    if normalized == "0":
        filters["fileBmp"] = "image"
    if normalized == "1":
        filters["fileBmp"] = "video"
    if normalized == "2":
        filters["fileBmp"] = "audio"
    return filters


def normalize_task_search_file_bmp_values(value: Any) -> list[int]:
    if value is None or value == "" or value == "all":
        return []
    values = value if isinstance(value, list) else [value]
    mapped = []
    for item in values:
        normalized = normalize_task_file_bmp_value(item)
        if normalized != "all":
            mapped.append({"image": 1, "video": 2, "audio": 3}[normalized])
    return list(dict.fromkeys(mapped))


def sanitize_task_filters(raw_filters: dict[str, Any] | None) -> dict[str, Any]:
    filters = raw_filters or {}
    upload_type = normalize_single_number_value(filters.get("uploadType"))
    id_type = normalize_single_number_value(filters.get("idType"))
    return {
        "classifyList": normalize_number_list(filters.get("classifyList")),
        "keyword": str(filters.get("keyword") or "").strip(),
        "spName": str(filters.get("spName") or "").strip(),
        "startTime": normalize_date_filter_value(filters.get("startTime")),
        "endTime": normalize_date_filter_value(filters.get("endTime")),
        "fileBmp": normalize_task_file_bmp_value(filters.get("fileBmp")),
        "uploadType": "all" if upload_type is None else str(upload_type),
        "idType": "all" if id_type is None else str(id_type),
        "size": positive_int(filters.get("size"), 50),
        "current": positive_int(filters.get("current"), 1),
    }


def normalize_task_search_filters(raw_filters: dict[str, Any] | None) -> dict[str, Any]:
    filters = raw_filters or {}
    return {
        "classifyList": normalize_number_list(filters.get("classifyList")),
        "keyword": str(filters.get("keyword") or "").strip(),
        "spName": str(filters.get("spName") or "").strip(),
        "startTime": str(filters.get("startTime") or "").strip(),
        "endTime": str(filters.get("endTime") or "").strip(),
        "fileBmp": normalize_task_search_file_bmp_values(filters.get("fileBmp")),
        "uploadType": normalize_number_list(filters.get("uploadType")),
        "idType": normalize_single_number_value(filters.get("idType")),
        "size": positive_int(filters.get("size"), 50),
        "current": positive_int(filters.get("current"), 1),
    }


def build_task_search_body(filters: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_task_search_filters(filters)
    body: dict[str, Any] = {"size": normalized["size"], "current": normalized["current"]}
    if normalized["keyword"]:
        body["keyword"] = normalized["keyword"]
    if normalized["spName"]:
        body["spName"] = normalized["spName"]
    if normalized["classifyList"]:
        body["classifyList"] = normalized["classifyList"]
    if normalized["startTime"]:
        body["startTime"] = normalize_date_time_boundary(normalized["startTime"], "00:00:00")
    if normalized["endTime"]:
        body["endTime"] = normalize_date_time_boundary(normalized["endTime"], "23:59:59")
    if normalized["fileBmp"]:
        body["fileBmp"] = normalized["fileBmp"]
    if normalized["uploadType"]:
        body["uploadType"] = normalized["uploadType"]
    if normalized["idType"] is not None:
        body["idType"] = normalized["idType"]
    return body


def map_task(task: Task, client_name: str | None = None) -> dict[str, Any]:
    total = int(task.total_count or 0)
    processed = int(task.processed_count or 0)
    progress = min(100, round((processed / total) * 100)) if total > 0 else (100 if task.execution_status == "completed" else 0)
    parsed_filters = safe_json_loads(task.filters_json, None)
    filters = sanitize_task_filters(normalize_legacy_saved_task_filters(parsed_filters)) if isinstance(parsed_filters, dict) else None
    return {
        "id": task.id,
        "name": task.name,
        "client_id": task.client_id,
        "clientName": client_name,
        "interval": task.interval,
        "threshold": task.threshold,
        "filters_json": task.filters_json,
        "execution_mode": task.execution_mode,
        "auto_confirm": task.auto_confirm,
        "active": bool(task.active),
        "execution_status": task.execution_status,
        "total_count": total,
        "processed_count": processed,
        "started_at": task.started_at,
        "finished_at": task.finished_at,
        "last_error": task.last_error,
        "clientId": task.client_id,
        "autoConfirm": bool(task.auto_confirm),
        "executionMode": task.execution_mode or "manual",
        "filters": filters,
        "totalCount": total,
        "processedCount": processed,
        "executionStatus": task.execution_status or "idle",
        "progress": progress,
    }


def fetch_task_query_results(session: Session, task_id: int, raw_filters: dict[str, Any] | None = None) -> dict[str, Any]:
    task = session.get(Task, task_id)
    if not task:
        raise RuntimeError("Task not found")
    client = session.get(Client, task.client_id)
    if not client:
        raise RuntimeError("Client not found")
    saved_filters = safe_json_loads(task.filters_json, {})
    saved_filters = sanitize_task_filters(normalize_legacy_saved_task_filters(saved_filters if isinstance(saved_filters, dict) else {}))
    search_body = build_task_search_body({**saved_filters, **(raw_filters or {})})
    response, result = request_client_api(session, client, "/openApi/icFile/findFilePage", method="POST", body=search_body)
    result_dict = result if isinstance(result, dict) else {}
    source_results = result_dict.get("results")
    if not isinstance(source_results, list) and isinstance(result_dict.get("data"), dict):
        source_results = result_dict["data"].get("results")
    mapped_results = []
    if isinstance(source_results, list):
        for item in source_results:
            if not isinstance(item, dict):
                continue
            media_info = resolve_media_info(client.api_url, item)
            mapped_results.append({**item, "mediaType": media_info["mediaType"], "mediaUrl": media_info["mediaUrl"]})
    return {"task": task, "client": client, "status_code": response.status_code, "resultData": result, "results": mapped_results}


def fetch_task_query_results_scoped(task_id: int, raw_filters: dict[str, Any] | None = None) -> dict[str, Any]:
    with session_scope() as session:
        result = fetch_task_query_results(session, task_id, raw_filters)
        return {"status_code": result["status_code"], "resultData": result["resultData"], "results": result["results"]}


def create_detail_fetch_error(status_code: int, result: Any, file_id: Any) -> RuntimeError:
    endpoint = "/openApi/icFile/getResultByFileId1"
    message = ""
    if isinstance(result, dict):
        error = result.get("error")
        message = (error.get("message") if isinstance(error, dict) else error) or result.get("message") or f"HTTP {status_code}"
    if status_code == 404:
        exc = RuntimeError(f"获取文件详情失败: 接口 {endpoint} 返回 404 Not Found，请检查目标环境是否已部署该 1.0 接口（fileId={file_id}）")
        setattr(exc, "grounding_status", "detail-endpoint-missing")
        return exc
    exc = RuntimeError(f"获取文件详情失败: {message or f'HTTP {status_code}'}")
    setattr(exc, "grounding_status", "detail-fetch-error")
    return exc


def fetch_file_detail(session: Session, client: Client, file_id: Any) -> dict[str, Any]:
    try:
        response, result = request_client_api(session, client, "/openApi/icFile/getResultByFileId1", method="GET", query={"fileId": file_id})
        if not response.ok:
            raise create_detail_fetch_error(response.status_code, result, file_id)
        return result if isinstance(result, dict) else {}
    except Exception as exc:
        if hasattr(exc, "grounding_status"):
            raise
        wrapped = RuntimeError(f"获取文件详情失败: {exc}")
        setattr(wrapped, "grounding_status", "detail-fetch-error")
        raise wrapped from exc


def parse_model_content(result_data: Any) -> str:
    if not isinstance(result_data, dict):
        return ""
    choices = result_data.get("choices")
    content = (((choices or [{}])[0]).get("message") or {}).get("content") if isinstance(choices, list) else ""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return "\n".join(str(part.get("text") or "") for part in content if isinstance(part, dict)).strip()
    return ""


def normalize_ai_result(raw_text: str) -> str:
    text = str(raw_text or "").strip()
    if not text:
        return "无"
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            parsed = json.loads(match.group(0))
            return normalize_species_label(parsed.get("species") or parsed.get("result") or parsed.get("name") or "")
        except Exception:
            pass
    cleaned = re.sub(r"^(最可能物种|species)[:：]\s*", "", text, flags=re.I).split("\n")[0].strip()
    return normalize_species_label(cleaned)


def build_record_model_message_content(detail: dict[str, Any], record: dict[str, Any], grounding: dict[str, Any]) -> list[dict[str, Any]]:
    original_name = get_record_name(record) or "未命名"
    text = "\n".join(
        [
            "你是一个动物分类专家，请只判断当前裁剪区域中的目标。",
            "如果裁剪区域中没有可识别物种，请返回“无”。",
            '只返回一行 JSON，不要返回其他文字：{"species":"物种名或无"}',
            f"文件ID: {detail.get('id', '未知')}",
            f"原识别名称: {original_name}",
            f"拉丁名: {record.get('speciesName') or '无'}",
            f"识别率: {record.get('score', '无')}",
            f"个体数: {record.get('spAmount', '无')}",
            f"bbox: {record.get('minx', '-')},{record.get('miny', '-')},{record.get('maxx', '-')},{record.get('maxy', '-')}",
        ]
    )
    return [{"type": "text", "text": text}, {"type": "image_url", "image_url": {"url": grounding["imageUrl"]}}]


def call_omlx_with_content(content: list[dict[str, Any]], max_tokens: int = 180) -> str:
    settings = get_settings()
    response = requests.post(
        settings.omlx_api_url,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {settings.omlx_api_key}"},
        json={
            "model": settings.omlx_model,
            "messages": [{"role": "user", "content": content}],
            "temperature": 0.1,
            "max_tokens": max_tokens,
        },
        timeout=settings.request_timeout_seconds,
    )
    try:
        result = response.json()
    except Exception:
        result = {"rawText": response.text}
    log_event("model_gateway", "omlx recognition completed", status=response.status_code)
    if not response.ok:
        message = result.get("error", {}).get("message") if isinstance(result.get("error"), dict) else result.get("message", f"HTTP {response.status_code}")
        raise RuntimeError(f"oMLX 调用失败: {message}")
    return normalize_ai_result(parse_model_content(result))


def create_review_row_from_result(
    *,
    record: dict[str, Any],
    record_index: int,
    ai_name: str,
    decision: str,
    will_submit: bool,
    grounding_status: str,
    error_message: str = "",
    grounding_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "recordId": record.get("id"),
        "recordIndex": record_index,
        "originalName": get_record_name(record),
        "speciesName": str(record.get("speciesName") or "").strip(),
        "aiName": ai_name or "",
        "decision": decision,
        "willSubmit": bool(will_submit),
        "groundingStatus": grounding_status,
        "errorMessage": error_message,
        "groundingMeta": grounding_meta,
        "bbox": {
            "minx": record.get("minx"),
            "miny": record.get("miny"),
            "maxx": record.get("maxx"),
            "maxy": record.get("maxy"),
        },
    }


def create_error_review_row(record: dict[str, Any], record_index: int, grounding_status: str, error_message: str) -> dict[str, Any]:
    return create_review_row_from_result(
        record=record,
        record_index=record_index,
        ai_name="",
        decision="error",
        will_submit=False,
        grounding_status=grounding_status,
        error_message=error_message,
    )


def judge_record_data(client: Client, detail: dict[str, Any], media_info: dict[str, Any]) -> list[dict[str, Any]]:
    records = detail.get("recordData") if isinstance(detail.get("recordData"), list) else []
    if not records:
        return []
    source = None
    source_error = ""
    try:
        source = load_grounding_source(client.api_url, detail, media_info)
    except Exception as exc:
        source_error = str(exc)
    rows = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            continue
        if source is None:
            rows.append(create_error_review_row(record, index, "media-error", source_error or "无法加载裁剪媒体"))
            continue
        grounding = build_record_grounding(record, source)
        if not grounding["ok"]:
            rows.append(create_error_review_row(record, index, grounding["groundingStatus"], grounding["errorMessage"]))
            continue
        try:
            ai_name = call_omlx_with_content(build_record_model_message_content(detail, record, grounding))
            will_submit = is_submittable_species(ai_name)
            rows.append(
                create_review_row_from_result(
                    record=record,
                    record_index=index,
                    ai_name=ai_name,
                    decision="keep" if will_submit and is_same_species(get_record_name(record), ai_name) else ("rename" if will_submit else "exclude"),
                    will_submit=will_submit,
                    grounding_status=grounding["groundingStatus"],
                    grounding_meta={
                        "method": grounding["groundingMethod"],
                        "imageMimeType": grounding["imageMimeType"],
                        "sourceSize": grounding["sourceSize"],
                        "cropSize": grounding["cropSize"],
                        "cropBox": grounding["bbox"],
                    },
                )
            )
        except Exception as exc:
            rows.append(create_error_review_row(record, index, grounding["groundingStatus"], str(exc)))
    return rows


def summarize_review_rows(review_rows: list[dict[str, Any]], fallback_original: str = "") -> dict[str, Any]:
    original_names = [row.get("originalName") for row in review_rows if row.get("originalName")]
    ai_names = [row.get("aiName") or (f"识别失败: {row.get('errorMessage')}" if row.get("errorMessage") else "无") for row in review_rows]
    return {
        "originalResult": "、".join(original_names) if original_names else (fallback_original or "未识别物种"),
        "spNameList": "、".join(original_names) if original_names else None,
        "aiResult": "、".join([name for name in ai_names if name]) or "无",
    }


def build_file_execution_item(client: Client, list_item: dict[str, Any], detail: dict[str, Any] | None) -> dict[str, Any]:
    merged = {**list_item, **(detail or {})}
    media_info = resolve_media_info(client.api_url, merged)
    return {
        **merged,
        "mediaType": media_info["mediaType"],
        "mediaUrl": media_info["mediaUrl"],
        "coverUrl": resolve_media_url(client.api_url, (detail or list_item).get("coverUrl")),
    }


def process_task_execution(task_id: int, selected_items: list[dict[str, Any]], stop_flag: threading.Event) -> None:
    with session_scope() as session:
        task = session.get(Task, task_id)
        if not task:
            return
        client = session.get(Client, task.client_id)
        if not client:
            return
        task.active = True
        task.execution_status = "running"
        task.total_count = len(selected_items)
        task.processed_count = 0
        task.started_at = now_iso()
        task.finished_at = None
        task.last_error = None
        session.add(task)
        session.commit()

        processed = 0
        try:
            for item in selected_items:
                if stop_flag.is_set():
                    task.active = False
                    task.execution_status = "paused"
                    task.finished_at = now_iso()
                    session.add(task)
                    session.commit()
                    return
                file_id = item.get("id")
                detail = None
                executable_item = item
                processing_error = ""
                try:
                    detail = fetch_file_detail(session, client, file_id)
                    executable_item = build_file_execution_item(client, item, detail)
                    media_info = {"mediaType": executable_item.get("mediaType"), "mediaUrl": executable_item.get("mediaUrl")}
                    review_rows = judge_record_data(client, executable_item, media_info)
                except Exception as exc:
                    processing_error = str(exc)
                    media_info = resolve_media_info(client.api_url, item)
                    executable_item = {
                        **item,
                        "mediaType": media_info["mediaType"],
                        "mediaUrl": media_info["mediaUrl"],
                        "coverUrl": resolve_media_url(client.api_url, item.get("coverUrl")),
                    }
                    grounding_status = getattr(exc, "grounding_status", "media-error")
                    error_message = str(exc) if str(grounding_status).startswith("detail-") else f"详情或识别处理失败: {exc}"
                    review_rows = [create_error_review_row(item, 0, grounding_status, error_message)]

                summary = summarize_review_rows(review_rows, build_original_result(executable_item))
                timestamp = int(time.time() * 1000)
                review_id = f"T{task_id}-F{file_id or 'NA'}-{timestamp}-{random.choice(range(100000, 999999))}"
                created_at = now_iso()
                review = Review(
                    id=review_id,
                    image_url=executable_item.get("mediaUrl") or executable_item.get("coverUrl") or "about:blank",
                    original_result=summary["originalResult"],
                    sp_name_list=summary["spNameList"],
                    ai_result=summary["aiResult"],
                    status="pending",
                    schema_version=REVIEW_SCHEMA_VERSION,
                    detail_snapshot_json=safe_json_dumps(executable_item) if detail else None,
                    review_rows_json=safe_json_dumps(review_rows),
                    confirm_state="failed" if processing_error else "pending",
                    remote_error=processing_error or None,
                    task_id=task_id,
                    task_name=task.name,
                    file_id=int(file_id) if str(file_id or "").isdigit() else None,
                    media_type=executable_item.get("mediaType"),
                    media_url=executable_item.get("mediaUrl"),
                    file_time=executable_item.get("fileTime"),
                    created_at=created_at,
                    updated_at=created_at,
                )
                session.add(review)
                processed += 1
                task.processed_count = processed
                session.add(task)
                session.commit()

            task.active = False
            task.execution_status = "completed"
            task.processed_count = processed
            task.finished_at = now_iso()
            session.add(task)
            session.commit()
        except Exception as exc:
            task.active = False
            task.execution_status = "failed"
            task.last_error = str(exc)
            task.finished_at = now_iso()
            session.add(task)
            session.commit()
            log_error("task_lifecycle", "task execution failed", task_id=task_id, error=str(exc))
        finally:
            _running_tasks.pop(task_id, None)
            _stop_flags.pop(task_id, None)


async def start_background_execution(task_id: int, selected_items: list[dict[str, Any]]) -> None:
    if task_id in _running_tasks and not _running_tasks[task_id].done():
        raise RuntimeError("当前任务正在执行，请稍后再试")
    stop_flag = threading.Event()
    _stop_flags[task_id] = stop_flag
    task = asyncio.create_task(asyncio.to_thread(process_task_execution, task_id, selected_items, stop_flag))
    _running_tasks[task_id] = task
    log_event("task_lifecycle", "task scheduled", task_id=task_id, total=len(selected_items))


def request_stop(task_id: int) -> None:
    flag = _stop_flags.get(task_id)
    if flag:
        flag.set()


def cancel_running_tasks() -> None:
    for flag in _stop_flags.values():
        flag.set()


def restore_interrupted_tasks() -> None:
    with session_scope() as session:
        tasks = session.exec(select(Task).where(Task.execution_status == "running")).all()
        if not tasks:
            return
        finished_at = now_iso()
        for task in tasks:
            task.active = False
            task.execution_status = "failed"
            task.finished_at = finished_at
            task.last_error = "process interrupted before completion"
            session.add(task)
        log_event("task_lifecycle", "restored interrupted tasks", count=len(tasks))
