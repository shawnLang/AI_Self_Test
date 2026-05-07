"""任务(Task)的数据库模型"""
from datetime import datetime
from enum import Enum, IntEnum
from typing import Optional

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


class TaskIntervalType(IntEnum):
    """任务执行间隔。"""

    EVERY_HOUR = 1  # 每小时
    EVERY_6_HOURS = 6  # 每6小时
    EVERY_12_HOURS = 12  # 每12小时
    DAILY = 24  # 每天
    WEEKLY = 168  # 每周


class TaskExecutionMode(str, Enum):
    """任务执行方式"""
    AUTO = "自动"
    MANUAL = "手动"


class TaskItemDataStatus(str, Enum):
    """任务项明细在复核流程中的状态。"""

    ADD = "新增"
    UPDATE = "修改"
    DELETE = "删除"
    DEFAULT = "默认"


class TaskExecutionStatus(str, Enum):
    """任务执行状态"""

    CREATE = "创建"
    DATA_LOAD = "数据加载"
    DOWN = "下载"
    LLM = "模型识别"
    VERIFY = "核查"
    FINISH = "结束"
    FAIL = "失败"


class TaskItemStatus(str, Enum):
    """任务项执行与复核状态。"""

    CREATED = "已创建"
    DATA_LOADED = "详情已加载"
    DOWNLOADING = "下载中"
    DOWNLOADED = "已下载"
    LLM_RUNNING = "识别中"
    LLM_SUCCESS = "识别完成"
    VERIFY_PENDING = "待复核"
    CONFIRMED = "已确认"
    SKIPPED = "已跳过"
    FINISHED = "已完成"
    FAILED = "失败"


class TaskItemLlmState(str, Enum):
    """任务项大模型识别状态。"""

    PENDING = "待识别"
    RUNNING = "识别中"
    SUCCESS = "识别完成"
    FAIL = "识别失败"


class TaskItemConfirmState(str, Enum):
    """任务项人工确认状态。"""

    PENDING = "待确认"
    CONFIRMED = "已确认"
    SKIPPED = "已跳过"


class TaskItemRemoteState(str, Enum):
    """任务项远端提交状态。"""

    PENDING = "待提交"
    SUCCESS = "已提交"
    FAIL = "提交失败"


class TaskItemTrainState(str, Enum):
    """任务项训练数据保存状态。"""

    PENDING = "待保存"
    SAVED = "已保存"
    FAIL = "保存失败"


class Task(SQLModel, table=True):
    """任务。"""

    __tablename__ = "task"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(max_length=200, description="任务名称")
    client_id: int = Field(
        foreign_key="client.id",
        index=True,
        description="关联的客户端"
    )
    config_id: int = Field(
        foreign_key="config.id",
        index=True,
        description="关联的提示词"
    )
    interval: int = Field(default=TaskIntervalType.DAILY.value, description="执行间隔")
    filters_json: Optional[str] = Field(default=None, description="筛选条件json")
    execution_mode: str = Field(default=TaskExecutionMode.MANUAL.value,
                                max_length=10, description="执行方式")
    auto_execute: bool = Field(default=False, description="自动执行前置流程")
    active: bool = Field(default=False, description="活跃")
    execution_status: str = Field(default=TaskExecutionStatus.CREATE.value,
                                  max_length=10, description="执行状态")
    total_count: int = Field(default=0, description="总数")
    processed_count: int = Field(default=0, description="处理次数")
    started_at: Optional[datetime] = Field(default=None, description="开始时间")
    finished_at: Optional[datetime] = Field(default=None, description="完成时间")
    stage_started_at: Optional[datetime] = Field(default=None, description="当前阶段开始时间")
    last_progress_at: Optional[datetime] = Field(default=None, description="最近进度更新时间")
    last_pull_end_at: Optional[datetime] = Field(default=None, description="上次拉取结束时间")
    last_run_started_at: Optional[datetime] = Field(default=None, description="上次执行发起时间")
    skipped_count: int = Field(default=0, description="累计跳过重复条数")
    last_error: Optional[str] = Field(default=None, description="最后错误")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    updated_at: datetime = Field(default_factory=datetime.now, description="更新时间")


class TaskItem(SQLModel, table=True):
    """任务文件列表"""

    __tablename__ = "task_item"
    __table_args__ = (
        UniqueConstraint("task_id", "file_id", name="uq_task_item_task_id_file_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    task_id: int = Field(
        foreign_key="task.id",
        index=True,
        description="关联的任务"
    )
    name: str = Field(max_length=200, description="文件名称")
    device_name: str = Field(max_length=100, description="设备名称")
    file_num: str = Field(max_length=50, description="文件编号")
    file_extension: str = Field(max_length=10, description="文件扩展后缀名")
    file_url: str = Field(max_length=200, description="文件url")
    file_id: Optional[int] = Field(default=None, description="上游文件ID")
    file_fid: str = Field(max_length=50, description="文件fid")
    sp_name_list: str = Field(max_length=100, description="识别名称结果")
    classify: int = Field(default=1, description="识别类型")
    file_bmp: int = Field(default=1, description="文件格式")
    result_file_data: str = Field(max_length=100, description="视频识别结果数据文件url")
    id_type: int = Field(default=0, description="识别类型")
    status: str = Field(max_length=10, description="流程状态")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    updated_at: datetime = Field(default_factory=datetime.now, description="更新时间")
    down_state: bool = Field(default=False, description="是否下载")
    down_error: Optional[str] = Field(default=None, description="下载错误")
    file_path: Optional[str] = Field(default=None, description="文件保存路径")
    llm_state: str = Field(
        default=TaskItemLlmState.PENDING.value,
        max_length=20,
        description="大模型状态",
    )
    llm_error: Optional[str] = Field(default=None, description="大模型错误")
    llm_at: Optional[datetime] = Field(default=None, description="大模型识别时间")
    confirm_state: str = Field(
        default=TaskItemConfirmState.PENDING.value,
        max_length=20,
        description="确认状态",
    )
    confirmed_at: Optional[datetime] = Field(default=None, description="确认时间")
    remote_state: str = Field(
        default=TaskItemRemoteState.PENDING.value,
        max_length=20,
        description="远端提交状态",
    )
    remote_error: Optional[str] = Field(default=None, description="远端提交错误")
    remote_at: Optional[datetime] = Field(default=None, description="远端提交时间")
    train_state: str = Field(
        default=TaskItemTrainState.PENDING.value,
        max_length=20,
        description="提交训练状态",
    )
    train_at: Optional[datetime] = Field(default=None, description="提交训练时间")


class TaskItemData(SQLModel, table=True):
    """任务文件列表结果详情"""

    __tablename__ = "task_item_data"

    id: Optional[int] = Field(default=None, primary_key=True)
    task_item_id: int = Field(
        foreign_key="task_item.id",
        index=True,
        description="关联的任务item"
    )
    name: str = Field(max_length=100, description="原始识别名称")
    score: float = Field(default=0, description="原始识别率")
    track_ids: str = Field(max_length=100, description="个体轨迹ids")
    sp_amount: int = Field(default=1, description="识别物种个体数")
    minx: Optional[float] = Field(default=None, description="左上角x")
    miny: Optional[float] = Field(default=None, description="左上角y")
    maxx: Optional[float] = Field(default=None, description="右下角x")
    maxy: Optional[float] = Field(default=None, description="右下角y")
    llm_name: Optional[str] = Field(default=None, description="大模型识别名称")
    status: str = Field(default=TaskItemDataStatus.DEFAULT.value, description="状态")
