"""Dashboard statistics API route."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlmodel import Session, select

from aiSelfTest.db.models import Review, Task
from aiSelfTest.db.session import get_session

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/stats")
def stats(session: Session = Depends(get_session)):
    active_tasks = session.exec(select(func.count()).select_from(Task).where(Task.execution_status == "running")).one()
    pending_reviews = session.exec(select(func.count()).select_from(Review).where(Review.status == "pending")).one()
    processed_today = session.exec(
        select(func.count()).select_from(Review).where(
            Review.created_at.is_not(None),
            func.date(Review.created_at, "localtime") == func.date("now", "localtime"),
        )
    ).one()
    anomalies = session.exec(select(func.count()).select_from(Task).where(Task.execution_status == "failed")).one()
    recent_tasks = session.exec(
        select(Task)
        .where(Task.finished_at.is_not(None))
        .order_by(Task.finished_at.desc())
        .limit(8)
    ).all()
    return {
        "activeTasks": active_tasks,
        "processedToday": processed_today,
        "pendingReviews": pending_reviews,
        "anomalies": anomalies,
        "recentActivities": [
            {
                "id": task.id,
                "name": task.name,
                "status": task.execution_status,
                "processedCount": task.processed_count,
                "totalCount": task.total_count,
                "finishedAt": task.finished_at,
            }
            for task in recent_tasks
        ],
    }
