"""Review API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel import Session, select

from ..db.models import Review
from ..db.session import get_session
from ..services.reviews import completed_tasks, confirm_reviews, map_review

router = APIRouter(prefix="/api/reviews", tags=["reviews"])


@router.get("")
def list_reviews(taskId: int | None = None, status: str = "pending", session: Session = Depends(get_session)):
    statement = select(Review).where(Review.status == status)
    if taskId and taskId > 0:
        statement = statement.where(Review.task_id == taskId)
    statement = statement.order_by(Review.created_at.desc(), Review.id.desc())
    return [map_review(row) for row in session.exec(statement).all()]


@router.get("/completed-tasks")
def get_completed_tasks(session: Session = Depends(get_session)):
    return completed_tasks(session)


@router.delete("/{review_id}")
def delete_review(review_id: str, session: Session = Depends(get_session)):
    row = session.get(Review, review_id)
    if row:
        session.delete(row)
        session.commit()
    return {"success": True}


@router.post("/confirm")
async def confirm(request: Request, session: Session = Depends(get_session)):
    body = await request.json()
    ids = body.get("ids")
    if not isinstance(ids, list) or not ids:
        raise HTTPException(status_code=400, detail={"error": "请选择需要确认的复核数据。"})
    return confirm_reviews(session, ids)


@router.post("/delete")
async def delete_many(request: Request, session: Session = Depends(get_session)):
    body = await request.json()
    ids = body.get("ids")
    if isinstance(ids, list):
        for review_id in ids:
            row = session.get(Review, str(review_id))
            if row:
                session.delete(row)
        session.commit()
    return {"success": True}
