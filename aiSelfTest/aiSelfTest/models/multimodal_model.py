"""多模态模型网关配置(MultimodalModel)的数据库模型"""
from datetime import datetime
from enum import Enum
from typing import Optional

from sqlmodel import Field, SQLModel


class ModelStatusType(str, Enum):
    """客户端类型。"""

    Enable = "启用"
    Disable = "停用"


class MultimodalModel(SQLModel, table=True):
    """多模态模型网关配置。"""

    __tablename__ = "multimodal_model"

    id: Optional[int] = Field(default=None, primary_key=True)
    model_name: str = Field(max_length=200, description="模型名称")
    endpoint_url: str = Field(max_length=1000, description="地址")
    api_key: str = Field(max_length=1000, description="key")
    status: str = Field(default=ModelStatusType.Enable.value, max_length=10, description="状态")
    detected_models_json: Optional[str] = Field(default=None, description="检测到的模型 JSON 格式文件")
    last_detected_at: Optional[datetime] = Field(default=None, description="最后检测时间")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    updated_at: datetime = Field(default_factory=datetime.now, description="更新时间")
