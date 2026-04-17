"""Review mapping and confirmation services."""

from __future__ import annotations

from typing import Any

from sqlmodel import Session, select

from ..db.models import Client, Review, Task
from .client_api import assert_client_api_ok, request_client_api
from .utils import (
    get_record_name,
    is_same_species,
    is_submittable_species,
    normalize_species_label,
    safe_json_loads,
    now_iso,
)


def normalize_confirm_state(row: Review) -> str:
    value = str(row.confirm_state or "").strip()
    if value:
        return value
    return "confirmed" if row.status == "confirmed" else "pending"


def build_legacy_review_rows(row: Review) -> list[dict[str, Any]]:
    original_name = str(row.sp_name_list or "").strip() or str(row.original_result or "").strip()
    ai_name = str(row.ai_result or "").strip()
    is_error = ai_name.startswith("识别失败:")
    return [
        {
            "recordId": row.file_id,
            "recordIndex": 0,
            "originalName": original_name,
            "aiName": ai_name,
            "decision": "error" if is_error else ("keep" if is_submittable_species(ai_name) and is_same_species(original_name, ai_name) else "rename"),
            "willSubmit": is_submittable_species(ai_name) and not is_error,
            "groundingStatus": "legacy",
            "errorMessage": ai_name if is_error else "",
            "legacy": True,
        }
    ]


def get_review_rows_for_row(row: Review) -> list[dict[str, Any]]:
    parsed = safe_json_loads(row.review_rows_json, None)
    return parsed if isinstance(parsed, list) else build_legacy_review_rows(row)


def map_review(row: Review) -> dict[str, Any]:
    review_rows = get_review_rows_for_row(row)
    submit_count = len([item for item in review_rows if item.get("willSubmit")])
    excluded_count = max(0, len(review_rows) - submit_count)
    has_any_mismatch = True if not review_rows else any(item.get("decision") != "keep" or not item.get("willSubmit") for item in review_rows)
    confirm_state = normalize_confirm_state(row)
    return {
        "id": row.id,
        "imageUrl": row.image_url,
        "originalResult": str(row.sp_name_list or "").strip() or row.original_result,
        "aiResult": row.ai_result,
        "status": row.status,
        "confirmState": confirm_state,
        "remoteError": row.remote_error or "",
        "requiresRetry": confirm_state in {"failed", "submitting"},
        "taskId": row.task_id,
        "taskName": row.task_name,
        "fileId": row.file_id,
        "mediaType": row.media_type or "image",
        "mediaUrl": row.media_url or row.image_url,
        "fileTime": row.file_time,
        "reviewRows": review_rows,
        "submitCount": submit_count,
        "excludedCount": excluded_count,
        "hasAnyMismatch": has_any_mismatch,
        "willSubmitEmptyArray": len(review_rows) == 0 or submit_count == 0,
    }


def find_source_record(records: list[dict[str, Any]], review_row: dict[str, Any]) -> dict[str, Any] | None:
    index = review_row.get("recordIndex")
    if isinstance(index, int) and 0 <= index < len(records):
        return records[index]
    return next((record for record in records if str(record.get("id")) == str(review_row.get("recordId"))), None)


def derive_submit_record_data(detail_snapshot: dict[str, Any], review_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records = detail_snapshot.get("recordData") if isinstance(detail_snapshot, dict) else []
    if not isinstance(records, list):
        return []
    submitted = []
    for row in review_rows:
        if not row.get("willSubmit") or not is_submittable_species(row.get("aiName")):
            continue
        source_record = find_source_record(records, row)
        if source_record:
            submitted.append({**source_record, "name": normalize_species_label(row.get("aiName"))})
    return submitted


def update_ai_polling_result(session: Session, client: Client, file_id: int, record_data: list[dict[str, Any]]) -> None:
    response, result = request_client_api(
        session,
        client,
        "/openApi/icFile/aiPollingResult",
        method="POST",
        body={"id": int(file_id), "recordData": record_data},
    )
    assert_client_api_ok(response, result, "更新 AI 巡检结果")
    if result is not True:
        raise RuntimeError("更新 AI 巡检结果失败: 服务端未返回成功状态")


def confirm_reviews(session: Session, ids: list[Any]) -> dict[str, Any]:
    results = []
    for raw_id in ids:
        review_id = str(raw_id)
        attempted_at = now_iso()
        review = session.get(Review, review_id)
        if not review:
            results.append({"reviewId": review_id, "status": "failed", "message": "未找到复核记录"})
            continue
        file_id = int(review.file_id) if review.file_id is not None else None
        if normalize_confirm_state(review) == "confirmed":
            results.append({"reviewId": review_id, "fileId": file_id, "status": "confirmed", "alreadyConfirmed": True})
            continue
        try:
            task = session.get(Task, review.task_id) if review.task_id else None
            if not task:
                raise RuntimeError("未找到复核记录对应的任务")
            client = session.get(Client, task.client_id)
            if not client:
                raise RuntimeError("未找到任务对应的客户端")
            detail_snapshot = safe_json_loads(review.detail_snapshot_json, None)
            if not isinstance(detail_snapshot, dict) or file_id is None:
                raise RuntimeError("缺少可提交的详情快照，无法回写服务端")
            review_rows = get_review_rows_for_row(review)
            record_data = derive_submit_record_data(detail_snapshot, review_rows)
            review.confirm_state = "submitting"
            review.status = "pending"
            review.confirm_attempted_at = attempted_at
            review.remote_error = None
            review.updated_at = attempted_at
            session.add(review)
            session.commit()

            update_ai_polling_result(session, client, file_id, record_data)

            confirmed_at = now_iso()
            review.confirm_state = "confirmed"
            review.status = "confirmed"
            review.confirmed_at = confirmed_at
            review.remote_error = None
            review.updated_at = confirmed_at
            session.add(review)
            session.commit()
            results.append(
                {
                    "reviewId": review_id,
                    "fileId": file_id,
                    "status": "confirmed",
                    "submittedCount": len(record_data),
                    "submittedEmptyArray": len(record_data) == 0,
                }
            )
        except Exception as exc:
            failed_at = now_iso()
            review.confirm_state = "failed"
            review.status = "pending"
            review.remote_error = str(exc)
            review.updated_at = failed_at
            session.add(review)
            session.commit()
            results.append({"reviewId": review_id, "fileId": file_id, "status": "failed", "message": str(exc)})

    return {
        "successCount": len([item for item in results if item["status"] == "confirmed"]),
        "failureCount": len([item for item in results if item["status"] == "failed"]),
        "results": results,
    }


def completed_tasks(session: Session) -> list[dict[str, Any]]:
    tasks = session.exec(
        select(Task)
        .where(Task.execution_status == "completed", Task.total_count > 0, Task.processed_count >= Task.total_count)
        .order_by(Task.finished_at.desc(), Task.id.desc())
    ).all()
    return [
        {
            "id": task.id,
            "name": task.name,
            "totalCount": task.total_count,
            "processedCount": task.processed_count,
            "progress": 100,
            "finishedAt": task.finished_at,
        }
        for task in tasks
    ]
