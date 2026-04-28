"""仪表盘路由。"""

from __future__ import annotations

from aiSelfTest.schemas.common import ApiResponse
from aiSelfTest.schemas.dashboard import DashboardStatsData
from fastapi import APIRouter

router = APIRouter(prefix="/dashboard")


@router.get("/stats", response_model=ApiResponse[DashboardStatsData])
def get_dashboard_stats_route() -> ApiResponse[DashboardStatsData]:
    """返回最小可用仪表盘统计。"""

    return ApiResponse(
        code=0,
        message="success",
        data=DashboardStatsData(
            active_tasks=0,
            processed_today=0,
            pending_reviews=0,
            anomalies=0,
            recent_activities=[],
        ),
    )
