"""上游客户端(Client)的数据库模型"""
from enum import Enum
from typing import Optional

from sqlmodel import Field, SQLModel


class ClientStatusType(str, Enum):
    """客户端类型。"""

    Enable = "启用"
    Disable = "停用"


class Client(SQLModel, table=True):
    """第三方客户端连接配置与令牌缓存。"""

    __tablename__ = "client"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(max_length=200, description="项目名称")
    api_url: str = Field(max_length=1000, description="api地址")
    account: str = Field(max_length=50, description="账号")
    password: str = Field(max_length=200, description="密码")
    status: str = Field(default=ClientStatusType.Enable.value, max_length=10, description="状态")
    access_token: Optional[str] = Field(default=None, max_length=4000, description="token")
    refresh_token: Optional[str] = Field(default=None, max_length=4000, description="刷新token")
    expires_at: Optional[int] = Field(default=None, description="token过期绝对时间戳")
    auth_header_style: Optional[str] = Field(default=None, max_length=20, description="认证头格式")
    working_url_path: Optional[str] = Field(default=None, max_length=200, description="可用请求路径")
