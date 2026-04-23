"""模型提示词配置接口请求与响应模型。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from aiSelfTest.models.config import Config as ConfigModel


ConfigFormatValue = Literal[0, 1, 2]


class ConfigPayloadBase(BaseModel):
    """模型提示词配置写入请求基础模型。"""

    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=200)
    remark: str = Field(default="", max_length=1000)
    text: str = Field(min_length=1, max_length=10000)
    format: ConfigFormatValue = 0


class ConfigCreateRequest(ConfigPayloadBase):
    """创建模型提示词配置请求。"""


class ConfigUpdateRequest(ConfigPayloadBase):
    """更新模型提示词配置请求。"""


class ConfigResponse(BaseModel):
    """模型提示词配置对外返回模型。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    remark: str
    text: str
    format: ConfigFormatValue

    @classmethod
    def from_model(cls, config: ConfigModel) -> "ConfigResponse":
        """将数据库模型转换为响应模型。"""

        return cls(
            id=config.id or 0,
            name=config.name,
            remark=config.remark,
            text=config.text,
            format=config.format,  # type: ignore[arg-type]
        )


class ConfigListData(BaseModel):
    """模型提示词配置列表响应体。"""

    items: list[ConfigResponse]


class ConfigDeleteData(BaseModel):
    """模型提示词配置删除响应体。"""

    id: int
