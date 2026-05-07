"""仪表盘路由。"""

from __future__ import annotations

from aiSelfTest.database import get_session
from aiSelfTest.schemas.common import ApiResponse
from aiSelfTest.schemas.dashboard import DashboardStatsData
from aiSelfTest.services.dashboard import get_dashboard_stats
from fastapi import APIRouter, Depends
from sqlmodel import Session

router = APIRouter(prefix="/dashboard")


@router.get("/stats", response_model=ApiResponse[DashboardStatsData])
def get_dashboard_stats_route(session: Session = Depends(get_session)) -> ApiResponse[DashboardStatsData]:
    """返回仪表盘真实统计。"""

    return ApiResponse(
        code=0,
        message="success",
        data=get_dashboard_stats(session),
    )
