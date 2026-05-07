"""任务(Task)接口请求与响应模型。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator
from PIL import Image

from aiSelfTest.config import get_settings
from aiSelfTest.models.task import (
    Task,
    TaskExecutionStatus,
    TaskItem,
    TaskItemConfirmState,
    TaskItemData,
    TaskItemDataStatus,
    TaskItemLlmState,
    TaskItemRemoteState,
    TaskItemTrainState,
)


ExecutionModeValue = Literal["auto", "manual"]
MediaTypeValue = Literal["image", "video"]
ModuleValue = Literal["camera", "lure", "video"]
TASK_FILE_STATIC_PREFIX = "/api/task-files"
ESTIMATABLE_TASK_STATUSES = {
    TaskExecutionStatus.DATA_LOAD.value,
    TaskExecutionStatus.DOWN.value,
    TaskExecutionStatus.LLM.value,
}


def resolve_task_item_media_url(row: TaskItem) -> str:
    """返回已下载文件的本地静态访问地址，未下载或文件缺失时返回空字符串。"""

    if row.down_state and row.file_path:
        file_path = Path(row.file_path).expanduser().resolve()
        if not file_path.is_file():
            return ""

        task_files_dir = (get_settings().data_dir / "task_files").resolve()
        try:
            relative_path = file_path.relative_to(task_files_dir)
        except ValueError:
            return ""

        quoted_path = quote(relative_path.as_posix(), safe="/")
        return f"{TASK_FILE_STATIC_PREFIX}/{quoted_path}"

    return ""


def estimate_task_remaining_seconds(task: Task) -> int | None:
    """估算任务当前执行阶段的剩余秒数。"""

    if task.execution_status not in ESTIMATABLE_TASK_STATUSES:
        return None
    if task.total_count <= 0 or task.processed_count <= 0:
        return None
    if task.stage_started_at is None or task.last_progress_at is None:
        return None

    remaining_count = task.total_count - task.processed_count
    if remaining_count <= 0:
        return 0

    elapsed_seconds = (task.last_progress_at - task.stage_started_at).total_seconds()
    if elapsed_seconds <= 0:
        return None

    average_seconds = elapsed_seconds / task.processed_count
    return max(0, round(average_seconds * remaining_count))


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
    module: ModuleValue = Field(default="camera", description="设备所属模块(camera,lure,video)")

    @field_validator("module", mode="before")
    @classmethod
    def normalize_module(cls, value: str | None) -> str:
        """空模块按历史默认值红外相机处理。"""

        text = str(value or "").strip()
        return text or "camera"


class TaskPayloadBase(BaseModel):
    """任务写入请求基础模型。"""

    model_config = ConfigDict(str_strip_whitespace=True, validate_by_name=True)

    name: str = Field(min_length=1, max_length=200, description="任务名称")
    client_id: int = Field(gt=0, description="项目ID")
    config_id: int = Field(gt=0, description="提示词配置ID")
    interval_hours: int = Field(description="执行间隔小时数")
    execution_mode: ExecutionModeValue = Field(description="执行方式")
    auto_execute: bool = Field(
        default=False,
        validation_alias=AliasChoices("auto_execute", "auto_confirm"),
        description="自动执行前置流程",
    )
    filters: TaskFiltersPayload = Field(description="筛选条件")

    @field_validator("interval_hours")
    @classmethod
    def validate_interval_hours(cls, value: int) -> int:
        """校验任务执行间隔只能使用前端支持的固定档位。"""

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
    auto_execute: bool
    active: bool
    execution_status: str
    total_count: int
    processed_count: int
    skipped_count: int
    last_error: str | None
    estimated_remaining_seconds: int | None = None
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
        """将任务数据库模型转换为 API 响应模型。"""

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
            auto_execute=task.auto_execute,
            active=task.active,
            execution_status=task.execution_status,
            total_count=task.total_count,
            processed_count=task.processed_count,
            skipped_count=task.skipped_count,
            last_error=task.last_error,
            estimated_remaining_seconds=estimate_task_remaining_seconds(task),
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


class TaskItemSubmitTaskRequest(BaseModel):
    """按任务提交所有可提交 TaskItem 请求。"""

    task_id: int = Field(gt=0, description="任务ID")


class TaskItemRejectRequest(TaskItemActionRequest):
    """TaskItem 拒绝动作请求。"""

    reason: str = Field(min_length=1, max_length=200, description="拒绝原因")


class TaskItemReviewRowUpdateRequest(TaskItemActionRequest):
    """TaskItemData 复核行更新请求。"""

    task_item_data_id: int = Field(gt=0, description="任务项明细ID")
    status: str = Field(description="复核状态")
    llm_name: str | None = Field(default=None, max_length=100, description="识别名称")

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        """校验复核状态只能使用 TaskItemDataStatus 定义值。"""

        allowed_statuses = {item.value for item in TaskItemDataStatus}
        if value not in allowed_statuses:
            raise ValueError("复核状态必须是 默认/新增/修改/删除")
        return value


class TaskItemBBox(BaseModel):
    """TaskItemData 识别框。"""

    minx: float
    miny: float
    maxx: float
    maxy: float

    @classmethod
    def from_model(cls, row: TaskItemData) -> "TaskItemBBox | None":
        """从任务项明细提取有效识别框。"""

        if row.minx is None or row.miny is None or row.maxx is None or row.maxy is None:
            return None
        if row.maxx <= row.minx or row.maxy <= row.miny:
            return None
        return cls(minx=row.minx, miny=row.miny, maxx=row.maxx, maxy=row.maxy)


class TaskItemSourceSize(BaseModel):
    """TaskItem 原始图片尺寸。"""

    width: float
    height: float


class TaskItemReviewRow(BaseModel):
    """TaskItem 复核行。"""

    task_item_data_id: int
    source_name: str | None
    llm_name: str | None
    status: str
    bbox: TaskItemBBox | None = None
    source_size: TaskItemSourceSize | None = None

    @classmethod
    def from_model(
        cls,
        row: TaskItemData,
        *,
        source_size: TaskItemSourceSize | None = None,
    ) -> "TaskItemReviewRow":
        """将任务项明细转换为复核行响应。"""

        return cls(
            task_item_data_id=row.id or 0,
            source_name=row.name,
            llm_name=row.llm_name,
            status=row.status,
            bbox=TaskItemBBox.from_model(row),
            source_size=source_size,
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
        """将任务项数据库模型转换为列表行响应。"""

        media_type: MediaTypeValue = "video" if row.file_bmp == 2 else "image"
        return cls(
            id=row.id or 0,
            task_id=row.task_id,
            media_type=media_type,
            name=row.name,
            file_url=resolve_task_item_media_url(row),
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
        """将任务项及其复核行转换为详情响应。"""

        media_type: MediaTypeValue = "video" if row.file_bmp == 2 else "image"
        submit_statuses = {
            TaskItemDataStatus.DEFAULT.value,
            TaskItemDataStatus.ADD.value,
            TaskItemDataStatus.UPDATE.value,
        }
        submit_count = len([item for item in review_rows if item.status in submit_statuses])
        exclude_count = len(
            [item for item in review_rows if item.status == TaskItemDataStatus.DELETE.value]
        )
        return cls(
            id=row.id or 0,
            task_id=row.task_id,
            media_type=media_type,
            media=TaskItemMedia(
                url=resolve_task_item_media_url(row),
                result_file_url=None,
            ),
            step_state=TaskItemStepState(
                download="success" if row.down_state else "pending",
                llm=row.llm_state or TaskItemLlmState.PENDING.value,
                confirm=row.confirm_state or TaskItemConfirmState.PENDING.value,
                remote=row.remote_state or TaskItemRemoteState.PENDING.value,
                train=row.train_state or TaskItemTrainState.PENDING.value,
            ),
            review_summary=TaskItemReviewSummary(
                submit_count=submit_count,
                exclude_count=exclude_count,
                submit_empty=submit_count == 0,
            ),
            review_rows=review_rows,
        )


def resolve_task_item_source_size(row: TaskItem, data_rows: list[TaskItemData]) -> TaskItemSourceSize | None:
    """返回图片复核绘框需要的源尺寸，无法读取原图时用 bbox 推导兜底尺寸。"""

    if row.file_bmp != 1:
        return None

    file_path = Path(row.file_path).expanduser() if row.file_path else None
    if file_path and file_path.is_file():
        try:
            with Image.open(file_path) as image:
                return TaskItemSourceSize(width=float(image.width), height=float(image.height))
        except OSError:
            pass

    maxx_values = [data_row.maxx for data_row in data_rows if data_row.maxx is not None]
    maxy_values = [data_row.maxy for data_row in data_rows if data_row.maxy is not None]
    if not maxx_values or not maxy_values:
        return None

    width = max(maxx_values)
    height = max(maxy_values)
    if width <= 0 or height <= 0:
        return None
    return TaskItemSourceSize(width=width, height=height)


class TaskItemActionData(BaseModel):
    """TaskItem 动作响应体。"""

    id: int
    confirm_state: str | None = None
    remote_state: str | None = None
    train_state: str | None = None


class TaskItemBatchActionRow(BaseModel):
    """TaskItem 批量动作单项结果。"""

    id: int
    status: str
    message: str


class TaskItemBatchActionData(BaseModel):
    """TaskItem 批量动作响应体。"""

    success_count: int
    failure_count: int
    results: list[TaskItemBatchActionRow]
