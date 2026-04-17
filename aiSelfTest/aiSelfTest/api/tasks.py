"""Task API routes."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel import Session, select

from ..db.models import Client, Review, Task
from ..db.session import get_session
from ..services.tasks import (
    fetch_task_query_results_scoped,
    map_task,
    request_stop,
    sanitize_task_filters,
    start_background_execution,
)

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("")
def list_tasks(session: Session = Depends(get_session)):
    rows = session.exec(select(Task, Client.name).join(Client, Task.client_id == Client.id, isouter=True)).all()
    return [map_task(task, client_name) for task, client_name in rows]


@router.get("/{task_id}")
def get_task(task_id: int, session: Session = Depends(get_session)):
    row = session.exec(select(Task, Client.name).join(Client, Task.client_id == Client.id, isouter=True).where(Task.id == task_id)).first()
    if not row:
        raise HTTPException(status_code=404, detail={"error": "Task not found"})
    task, client_name = row
    return map_task(task, client_name)


@router.post("")
async def create_task(request: Request, session: Session = Depends(get_session)):
    body = await request.json()
    normalized_filters = sanitize_task_filters(body.get("filters") if isinstance(body.get("filters"), dict) else {})
    threshold = body.get("threshold")
    try:
        threshold_value = int(threshold)
    except (TypeError, ValueError):
        threshold_value = 0
    task = Task(
        name=body.get("name"),
        client_id=int(body.get("clientId")),
        interval=body.get("interval"),
        threshold=threshold_value,
        filters_json=json.dumps(normalized_filters, ensure_ascii=False),
        execution_mode="auto" if body.get("executionMode") == "auto" else "manual",
        auto_confirm=bool(body.get("autoConfirm")),
        active=bool(body.get("active")),
    )
    session.add(task)
    session.commit()
    session.refresh(task)
    return {"id": task.id}


@router.delete("/{task_id}")
def delete_task(task_id: int, session: Session = Depends(get_session)):
    for review in session.exec(select(Review).where(Review.task_id == task_id)).all():
        session.delete(review)
    task = session.get(Task, task_id)
    if task:
        session.delete(task)
    session.commit()
    return {"success": True}


@router.put("/{task_id}/status")
async def update_task_status(task_id: int, request: Request, session: Session = Depends(get_session)):
    body = await request.json()
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail={"error": "Task not found"})
    if body.get("active"):
        task.active = True
        task.execution_status = "running"
    else:
        request_stop(task_id)
        task.active = False
        if task.execution_status == "running":
            task.execution_status = "paused"
    session.add(task)
    session.commit()
    return {"success": True}


@router.post("/{task_id}/query-data")
async def query_data(task_id: int, request: Request, session: Session = Depends(get_session)):
    body = await request.json()
    try:
        result = await asyncio.to_thread(fetch_task_query_results_scoped, task_id, body if isinstance(body, dict) else {})
        result_data = result["resultData"]
        if isinstance(result_data, dict) and isinstance(result_data.get("results"), list):
            return {**result_data, "results": result["results"]}
        if isinstance(result_data, dict) and isinstance(result_data.get("data"), dict) and isinstance(result_data["data"].get("results"), list):
            data = {**result_data["data"], "results": result["results"]}
            return {**result_data, "data": data}
        return result_data
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"error": str(exc)}) from exc


def _execution_items_from_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": item.get("id"),
            "name": item.get("name"),
            "spNameList": item.get("spNameList"),
            "classify": item.get("classify"),
            "fileTime": item.get("fileTime"),
            "fileUrl": item.get("fileUrl"),
            "coverUrl": item.get("coverUrl"),
            "mediaType": item.get("mediaType"),
            "mediaUrl": item.get("mediaUrl"),
        }
        for item in results
    ]


@router.post("/{task_id}/run-now")
async def run_now(task_id: int, request: Request, session: Session = Depends(get_session)):
    body = await request.json()
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail={"error": "Task not found"})
    if task.execution_status == "running":
        raise HTTPException(status_code=409, detail={"error": "当前任务正在执行，请稍后再试"})
    try:
        result = await asyncio.to_thread(fetch_task_query_results_scoped, task_id, body if isinstance(body, dict) else {})
        execution_items = _execution_items_from_results(result["results"])
        if not execution_items:
            raise HTTPException(status_code=400, detail={"error": "当前任务按筛选条件未查询到可执行的数据"})
        await start_background_execution(task_id, execution_items)
        return {"success": True, "message": "任务已开始立即执行", "total": len(execution_items)}
    except HTTPException:
        raise
    except RuntimeError as exc:
        if "正在执行" in str(exc):
            raise HTTPException(status_code=409, detail={"error": str(exc)}) from exc
        raise HTTPException(status_code=500, detail={"error": str(exc)}) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"error": str(exc)}) from exc


@router.post("/{task_id}/execute")
async def execute_task(task_id: int, request: Request, session: Session = Depends(get_session)):
    body = await request.json()
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail={"error": "Task not found"})
    if task.execution_status == "running":
        raise HTTPException(status_code=409, detail={"error": "当前任务正在执行，请稍后再试"})
    execution_items = body.get("selectedItems") if isinstance(body.get("selectedItems"), list) else []
    if not execution_items and isinstance(body.get("fileIds"), list):
        execution_items = [{"id": item} for item in body["fileIds"]]
    if not execution_items:
        raise HTTPException(status_code=400, detail={"error": "未收到可执行的文件数据"})
    try:
        await start_background_execution(task_id, execution_items)
        return {"success": True, "message": "任务已开始执行", "total": len(execution_items)}
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail={"error": str(exc)}) from exc
