"""模型提示词配置(Config)的数据库模型"""
from typing import Optional

from sqlmodel import Field, SQLModel


class Config(SQLModel, table=True):
    """模型提示词配置。"""

    __tablename__ = "config"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(max_length=200, description="提示词名称")
    remark: str = Field(max_length=1000, description="备注")
    text: str = Field(max_length=10000, description="提示词")
    format: int = Field(default=0, description="数据解析格式选项")
