"""客户端接口请求与响应模型。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from aiSelfTest.models.client import Client


MASK_PLACEHOLDER = "********"
ClientStatusValue = Literal["启用", "停用"]
ClientAuthStatusValue = Literal["未认证", "已认证", "即将过期"]


def _masked_value(value: str | None) -> str:
    """将敏感值转换为脱敏字符串。"""

    return MASK_PLACEHOLDER if value else ""


class ClientPayloadBase(BaseModel):
    """客户端写入请求基础模型。"""

    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=200)
    api_url: str = Field(alias="apiUrl", min_length=1, max_length=1000)
    account: str = Field(min_length=1, max_length=50)
    status: ClientStatusValue = "启用"

    @field_validator("api_url")
    @classmethod
    def validate_api_url(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            raise ValueError("API 地址必须以 http:// 或 https:// 开头")
        return value


class ClientCreateRequest(ClientPayloadBase):
    """创建客户端请求。"""

    password: str = Field(min_length=1, max_length=50)


class ClientUpdateRequest(ClientPayloadBase):
    """更新客户端请求。"""

    password: str | None = Field(default=None, max_length=50)


class ClientResponse(BaseModel):
    """客户端对外返回模型。"""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    name: str
    api_url: str = Field(alias="apiUrl")
    account: str
    status: ClientStatusValue
    auth_status: ClientAuthStatusValue = Field(alias="authStatus")
    password: str
    access_token: str = Field(alias="accessToken")
    refresh_token: str = Field(alias="refreshToken")
    expires_in: int | None = Field(alias="expiresIn")

    @classmethod
    def from_model(cls, client: Client) -> "ClientResponse":
        """将数据库模型转换为对外响应模型。"""

        return cls(
            id=client.id or 0,
            name=client.name,
            api_url=client.api_url,
            account=client.account,
            status=client.status,
            auth_status=_client_auth_status(client),
            password=_masked_value(client.password),
            access_token=_masked_value(client.access_token),
            refresh_token=_masked_value(client.refresh_token),
            expires_in=client.expires_in,
        )


class ClientListData(BaseModel):
    """客户端列表响应体。"""

    items: list[ClientResponse]


class ClientDeleteData(BaseModel):
    """客户端删除响应体。"""

    id: int


class ClientAuthenticateData(BaseModel):
    """客户端认证响应体。"""

    model_config = ConfigDict(populate_by_name=True)

    client: ClientResponse
    used_strategy: Literal["reuse", "refresh", "login"] = Field(alias="usedStrategy")


def _client_auth_status(client: Client) -> ClientAuthStatusValue:
    """根据缓存 token 推导认证状态。"""

    if not client.access_token:
        return "未认证"
    if _will_expire_soon(client.expires_in):
        return "即将过期"
    return "已认证"


def _will_expire_soon(expires_in: int | None) -> bool:
    """判断 token 是否已过期或即将过期。"""

    from time import time

    if expires_in is None:
        return True

    expires_at_seconds = expires_in / 1000 if expires_in > 10**11 else expires_in
    return expires_at_seconds - time() <= 60
