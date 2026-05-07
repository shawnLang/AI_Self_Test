"""仪表盘统计服务。"""

from __future__ import annotations

from datetime import datetime, time, timedelta

from loguru import logger
from sqlalchemy import or_
from sqlmodel import Session, select

from aiSelfTest.models.task import (
    Task,
    TaskExecutionStatus,
    TaskItem,
    TaskItemConfirmState,
    TaskItemStatus,
)
from aiSelfTest.schemas.dashboard import DashboardActivity, DashboardStatsData
from aiSelfTest.services.task_execution import RUNNING_TASK_STATUSES
from aiSelfTest.services.utils import format_dt


RECENT_ACTIVITY_LIMIT = 5


def get_dashboard_stats(session: Session, now: datetime | None = None) -> DashboardStatsData:
    """基于任务与任务项实时计算总览统计。"""

    current_time = now or datetime.now()
    start_at = datetime.combine(current_time.date(), time.min)
    end_at = start_at + timedelta(days=1)

    active_tasks = _count_active_tasks(session)
    processed_today = _count_processed_reviews_today(session, start_at=start_at, end_at=end_at)
    pending_reviews = _count_pending_reviews(session)
    anomalies = _count_failed_tasks(session)
    recent_activities = _list_recent_finished_tasks(session)

    logger.debug(
        "仪表盘统计完成 active_tasks={} processed_today={} pending_reviews={} anomalies={}",
        active_tasks,
        processed_today,
        pending_reviews,
        anomalies,
    )
    return DashboardStatsData(
        active_tasks=active_tasks,
        processed_today=processed_today,
        pending_reviews=pending_reviews,
        anomalies=anomalies,
        recent_activities=recent_activities,
    )


def _count_active_tasks(session: Session) -> int:
    """统计处于任务执行主流程中的任务数。"""

    running_statuses = set(RUNNING_TASK_STATUSES)
    running_statuses.discard(TaskExecutionStatus.CREATE.value)
    rows = session.exec(
        select(Task).where(
            or_(
                Task.execution_status.in_(running_statuses),
                (Task.execution_status == TaskExecutionStatus.CREATE.value)
                & (Task.last_run_started_at.is_not(None)),
            )
        )
    ).all()
    return len(rows)


def _count_processed_reviews_today(
    session: Session,
    *,
    start_at: datetime,
    end_at: datetime,
) -> int:
    """统计当天已处理的复核项数量。"""

    rows = session.exec(
        select(TaskItem).where(
            or_(
                (
                    TaskItem.confirm_state.in_(
                        [
                            TaskItemConfirmState.CONFIRMED.value,
                            TaskItemConfirmState.SKIPPED.value,
                        ]
                    )
                    & (TaskItem.confirmed_at >= start_at)
                    & (TaskItem.confirmed_at < end_at)
                ),
                (
                    (TaskItem.status == TaskItemStatus.FINISHED.value)
                    & (TaskItem.remote_at >= start_at)
                    & (TaskItem.remote_at < end_at)
                ),
            )
        )
    ).all()
    return len(rows)


def _count_pending_reviews(session: Session) -> int:
    """统计等待人工确认的复核项数量。"""

    rows = session.exec(
        select(TaskItem).where(
            TaskItem.status == TaskItemStatus.VERIFY_PENDING.value,
            TaskItem.confirm_state == TaskItemConfirmState.PENDING.value,
        )
    ).all()
    return len(rows)


def _count_failed_tasks(session: Session) -> int:
    """统计执行失败任务数量。"""

    rows = session.exec(
        select(Task).where(Task.execution_status == TaskExecutionStatus.FAIL.value)
    ).all()
    return len(rows)


def _list_recent_finished_tasks(session: Session) -> list[DashboardActivity]:
    """返回最近完成任务摘要。"""

    rows = session.exec(
        select(Task)
        .where(
            Task.execution_status == TaskExecutionStatus.FINISH.value,
            Task.finished_at.is_not(None),
        )
        .order_by(Task.finished_at.desc(), Task.id.desc())
        .limit(RECENT_ACTIVITY_LIMIT)
    ).all()
    return [
        DashboardActivity(
            id=row.id or 0,
            name=row.name,
            status=row.execution_status,
            processed_count=row.processed_count,
            total_count=row.total_count,
            finished_at=format_dt(row.finished_at),
        )
        for row in rows
    ]
