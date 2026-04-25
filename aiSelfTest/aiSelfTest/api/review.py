"""旧 review 接口兼容层。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session

from aiSelfTest.database import get_session
from aiSelfTest.services.task import (
    confirm_review_items,
    delete_review_item,
    delete_review_items,
    list_completed_review_tasks,
    list_review_items,
)


router = APIRouter(prefix="/reviews")


@router.get("/completed-tasks")
def list_completed_review_tasks_route(
    session: Session = Depends(get_session),
) -> list[dict[str, int | str]]:
    return list_completed_review_tasks(session)


@router.get("")
def list_reviews_route(
    taskId: int,
    session: Session = Depends(get_session),
) -> list[dict[str, object]]:
    return list_review_items(session, taskId)


@router.post("/confirm")
def confirm_reviews_route(
    payload: dict[str, list[str]],
    session: Session = Depends(get_session),
) -> dict[str, object]:
    return confirm_review_items(session, payload.get("ids", []))


@router.delete("/{review_id}")
def delete_review_route(
    review_id: int,
    session: Session = Depends(get_session),
) -> dict[str, bool]:
    delete_review_item(session, review_id)
    return {"ok": True}


@router.post("/delete")
def delete_reviews_route(
    payload: dict[str, list[str]],
    session: Session = Depends(get_session),
) -> dict[str, bool]:
    delete_review_items(session, payload.get("ids", []))
    return {"ok": True}
