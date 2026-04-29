"""旧 review 接口兼容层。"""

from __future__ import annotations

from aiSelfTest.database import get_session
from aiSelfTest.services.task import (
    confirm_review_items,
    delete_review_item,
    delete_review_items,
    list_completed_review_tasks,
    list_review_items,
)
from fastapi import APIRouter, Depends
from sqlmodel import Session

router = APIRouter(prefix="/reviews")


@router.get("/completed-tasks")
def list_completed_review_tasks_route(session: Session = Depends(get_session)) -> list[dict[str, int | str]]:
    """查询旧复核页面可展示的已完成任务。"""

    return list_completed_review_tasks(session)


@router.get("")
def list_reviews_route(task_id: int, session: Session = Depends(get_session)) -> list[dict[str, object]]:
    """查询旧复核页面的任务复核项。"""

    return list_review_items(session, task_id)


@router.post("/confirm")
def confirm_reviews_route(payload: dict[str, list[str]], session: Session = Depends(get_session)) -> dict[str, object]:
    """批量确认旧复核页面提交的复核项。"""

    ids = payload.get("ids", [])
    return confirm_review_items(session, ids)


@router.delete("/{review_id}")
def delete_review_route(review_id: int, session: Session = Depends(get_session)) -> dict[str, bool]:
    """删除旧复核页面中的单个复核项。"""

    delete_review_item(session, review_id)
    return {"ok": True}


@router.post("/delete")
def delete_reviews_route(payload: dict[str, list[str]], session: Session = Depends(get_session)) -> dict[str, bool]:
    """批量删除旧复核页面中的复核项。"""

    ids = payload.get("ids", [])
    delete_review_items(session, ids)
    return {"ok": True}
