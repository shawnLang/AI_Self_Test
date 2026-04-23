"""仪表盘响应模型。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class DashboardActivity(BaseModel):
    """近期活动条目。"""

    model_config = ConfigDict(populate_by_name=True)

    id: int
    name: str
    status: str
    processed_count: int = Field(alias="processedCount")
    total_count: int = Field(alias="totalCount")
    finished_at: str = Field(default="", alias="finishedAt")


class DashboardStatsData(BaseModel):
    """仪表盘统计响应。"""

    model_config = ConfigDict(populate_by_name=True)

    active_tasks: int = Field(alias="activeTasks")
    processed_today: int = Field(alias="processedToday")
    pending_reviews: int = Field(alias="pendingReviews")
    anomalies: int
    recent_activities: list[DashboardActivity] = Field(alias="recentActivities")
