"""任务(Task)接口请求与响应模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from aiSelfTest.models.task import Task, TaskItem, TaskItemData


ExecutionModeValue = Literal["auto", "manual"]
MediaTypeValue = Literal["image", "video"]


class TaskFiltersPayload(BaseModel):
    """任务筛选条件。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    classify_list: list[int] = Field(default_factory=list, description="识别分类")
    keyword: str = Field(default="", max_length=200, description="关键词")
    sp_name: str = Field(default="", max_length=200, description="物种名称")
    start_at: str = Field(default="", max_length=50, description="开始时间")
    end_at: str = Field(default="", max_length=50, description="结束时间")
    media_types: list[MediaTypeValue] = Field(default_factory=list, description="媒体类型")
    upload_types: list[int] = Field(default_factory=list, description="上传类型")
    identify_source: list[int] = Field(default_factory=list, description="识别来源")


class TaskPayloadBase(BaseModel):
    """任务写入请求基础模型。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=200, description="任务名称")
    client_id: int = Field(gt=0, description="项目ID")
    config_id: int = Field(gt=0, description="提示词配置ID")
    interval_hours: int = Field(description="执行间隔小时数")
    execution_mode: ExecutionModeValue = Field(description="执行方式")
    auto_confirm: bool = Field(default=False, description="自动确认")
    filters: TaskFiltersPayload = Field(description="筛选条件")

    @field_validator("interval_hours")
    @classmethod
    def validate_interval_hours(cls, value: int) -> int:
        if value not in {1, 6, 12, 24, 168}:
            raise ValueError("执行间隔必须是 1/6/12/24/168 小时")
        return value


class TaskCreateRequest(TaskPayloadBase):
    """创建任务请求。"""


class TaskUpdateRequest(TaskPayloadBase):
    """更新任务请求。"""


class TaskResponse(BaseModel):
    """任务响应体。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    client_id: int
    config_id: int
    interval_hours: int
    execution_mode: ExecutionModeValue
    auto_confirm: bool
    active: bool
    execution_status: str
    total_count: int
    processed_count: int
    last_error: str | None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    filters: TaskFiltersPayload

    @classmethod
    def from_model(
        cls,
        task: Task,
        *,
        filters: TaskFiltersPayload,
    ) -> "TaskResponse":
        execution_mode: ExecutionModeValue = (
            "auto" if task.execution_mode in {"自动", "auto"} else "manual"
        )
        return cls(
            id=task.id or 0,
            name=task.name,
            client_id=task.client_id,
            config_id=task.config_id,
            interval_hours=task.interval,
            execution_mode=execution_mode,
            auto_confirm=task.auto_confirm,
            active=task.active,
            execution_status=task.execution_status,
            total_count=task.total_count,
            processed_count=task.processed_count,
            last_error=task.last_error,
            started_at=task.started_at,
            finished_at=task.finished_at,
            filters=filters,
        )


class TaskListData(BaseModel):
    """任务列表响应体。"""

    items: list[TaskResponse]


class TaskDeleteData(BaseModel):
    """任务删除响应体。"""

    id: int


class TaskActionData(BaseModel):
    """任务动作响应体。"""

    id: int
    active: bool
    execution_status: str


class TaskItemActionRequest(BaseModel):
    """TaskItem 基础动作请求。"""

    task_item_id: int = Field(gt=0, description="任务项ID")


class TaskItemRejectRequest(TaskItemActionRequest):
    """TaskItem 拒绝动作请求。"""

    reason: str = Field(min_length=1, max_length=200, description="拒绝原因")


class TaskItemDeleteRequest(TaskItemActionRequest):
    """TaskItem 删除动作请求。"""

    task_item_data_ids: list[int] = Field(default_factory=list, description="待删除明细ID")


class TaskItemReviewRow(BaseModel):
    """TaskItem 复核行。"""

    task_item_data_id: int
    source_name: str | None
    llm_name: str | None
    status: str

    @classmethod
    def from_model(cls, row: TaskItemData) -> "TaskItemReviewRow":
        return cls(
            task_item_data_id=row.id or 0,
            source_name=row.name,
            llm_name=row.llm_name,
            status=row.status,
        )


class TaskItemReviewSummary(BaseModel):
    """TaskItem 复核摘要。"""

    submit_count: int
    exclude_count: int
    submit_empty: bool


class TaskItemMedia(BaseModel):
    """TaskItem 媒体信息。"""

    url: str
    result_file_url: str | None = None


class TaskItemStepState(BaseModel):
    """TaskItem 分步骤状态。"""

    download: str
    llm: str
    confirm: str
    remote: str
    train: str


class TaskItemListRow(BaseModel):
    """TaskItem 列表项。"""

    id: int
    task_id: int
    media_type: MediaTypeValue
    name: str
    file_url: str
    status: str
    down_state: bool
    llm_state: str | None
    confirm_state: str | None
    remote_state: str | None

    @classmethod
    def from_model(cls, row: TaskItem) -> "TaskItemListRow":
        media_type: MediaTypeValue = "video" if row.file_bmp == 2 else "image"
        return cls(
            id=row.id or 0,
            task_id=row.task_id,
            media_type=media_type,
            name=row.name,
            file_url=row.file_url,
            status=row.status,
            down_state=row.down_state,
            llm_state=row.llm_state,
            confirm_state=row.confirm_state,
            remote_state=row.remote_state,
        )


class TaskItemListData(BaseModel):
    """TaskItem 列表响应体。"""

    items: list[TaskItemListRow]
    total: int
    page: int
    page_size: int


class TaskItemDetailData(BaseModel):
    """TaskItem 详情响应体。"""

    id: int
    task_id: int
    media_type: MediaTypeValue
    media: TaskItemMedia
    step_state: TaskItemStepState
    review_summary: TaskItemReviewSummary
    review_rows: list[TaskItemReviewRow]

    @classmethod
    def from_model(
        cls,
        row: TaskItem,
        *,
        review_rows: list[TaskItemReviewRow],
    ) -> "TaskItemDetailData":
        media_type: MediaTypeValue = "video" if row.file_bmp == 2 else "image"
        submit_count = len([item for item in review_rows if item.status in {"新增", "修改", "删除"}])
        exclude_count = len([item for item in review_rows if item.status == "删除"])
        return cls(
            id=row.id or 0,
            task_id=row.task_id,
            media_type=media_type,
            media=TaskItemMedia(
                url=row.file_url,
                result_file_url=row.result_file_data or None,
            ),
            step_state=TaskItemStepState(
                download="success" if row.down_state else "pending",
                llm=row.llm_state or "pending",
                confirm=row.confirm_state or "pending",
                remote=row.remote_state or "pending",
                train=row.train_state or "pending",
            ),
            review_summary=TaskItemReviewSummary(
                submit_count=submit_count,
                exclude_count=exclude_count,
                submit_empty=submit_count == 0,
            ),
            review_rows=review_rows,
        )


class TaskItemActionData(BaseModel):
    """TaskItem 动作响应体。"""

    id: int
    confirm_state: str | None = None
    remote_state: str | None = None
