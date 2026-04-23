"""多模态模型接口请求与响应模型。"""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from aiSelfTest.models.multimodal_chat import (
    MultimodalChatMessage,
    MultimodalChatSession,
)
from aiSelfTest.models.multimodal_model import MultimodalModel


MASK_PLACEHOLDER = "********"
ModelStatusValue = Literal["启用", "停用"]
ChatMessageRole = Literal["system", "user", "assistant"]
AttachmentKind = Literal["image", "video", "audio", "document"]


def _masked_value(value: str | None) -> str:
    """将敏感值转换为脱敏字符串。"""

    return MASK_PLACEHOLDER if value else ""


def _normalize_detected_models(models: list[str] | None) -> list[str]:
    """清洗探测出的模型列表。"""

    if not models:
        return []

    normalized_models: list[str] = []
    seen: set[str] = set()
    for item in models:
        model_name = str(item).strip()
        if not model_name or model_name in seen:
            continue
        seen.add(model_name)
        normalized_models.append(model_name)
    return normalized_models


class MultimodalModelPayloadBase(BaseModel):
    """多模态模型写入请求基础模型。"""

    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True)

    model_name: str = Field(alias="modelName", min_length=1, max_length=200)
    endpoint_url: str = Field(alias="endpointUrl", min_length=1, max_length=1000)
    status: ModelStatusValue = "启用"
    detected_models: list[str] = Field(
        default_factory=list,
        alias="detectedModels",
    )
    detected_models_updated: bool = Field(
        default=False,
        alias="detectedModelsUpdated",
    )

    @field_validator("endpoint_url")
    @classmethod
    def validate_endpoint_url(cls, value: str) -> str:
        """校验模型地址。"""

        if not value.startswith(("http://", "https://")):
            raise ValueError("模型地址必须以 http:// 或 https:// 开头")
        return value.rstrip("/")

    @field_validator("detected_models")
    @classmethod
    def normalize_detected_models(cls, value: list[str]) -> list[str]:
        """清洗探测出的模型列表。"""

        return _normalize_detected_models(value)


class MultimodalModelCreateRequest(MultimodalModelPayloadBase):
    """创建模型配置请求。"""

    api_key: str = Field(alias="apiKey", min_length=1, max_length=1000)


class MultimodalModelUpdateRequest(MultimodalModelPayloadBase):
    """更新模型配置请求。"""

    api_key: str | None = Field(default=None, alias="apiKey", max_length=1000)


class MultimodalModelResponse(BaseModel):
    """模型配置对外返回模型。"""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    model_name: str = Field(alias="modelName")
    endpoint_url: str = Field(alias="endpointUrl")
    api_key: str = Field(alias="apiKey")
    api_key_configured: bool = Field(alias="apiKeyConfigured")
    status: ModelStatusValue
    detected_models: list[str] = Field(alias="detectedModels")
    last_detected_at: str | None = Field(alias="lastDetectedAt")

    @classmethod
    def from_model(cls, model: MultimodalModel) -> "MultimodalModelResponse":
        """将数据库模型转换为对外响应模型。"""

        return cls(
            id=model.id or 0,
            model_name=model.model_name,
            endpoint_url=model.endpoint_url,
            api_key=_masked_value(model.api_key),
            api_key_configured=bool(model.api_key),
            status=model.status,
            detected_models=parse_detected_models(model.detected_models_json),
            last_detected_at=(
                model.last_detected_at.isoformat() if model.last_detected_at else None
            ),
        )


class MultimodalModelListData(BaseModel):
    """模型配置列表响应体。"""

    items: list[MultimodalModelResponse]


class MultimodalModelDeleteData(BaseModel):
    """模型配置删除响应体。"""

    id: int


class MultimodalModelDetectRequest(BaseModel):
    """探测模型请求。"""

    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True)

    endpoint_url: str = Field(alias="endpointUrl", min_length=1, max_length=1000)
    api_key: str = Field(alias="apiKey", min_length=1, max_length=1000)

    @field_validator("endpoint_url")
    @classmethod
    def validate_endpoint_url(cls, value: str) -> str:
        """校验模型地址。"""

        if not value.startswith(("http://", "https://")):
            raise ValueError("模型地址必须以 http:// 或 https:// 开头")
        return value.rstrip("/")


class MultimodalModelDetectData(BaseModel):
    """探测模型响应体。"""

    model_config = ConfigDict(populate_by_name=True)

    models: list[str]
    detected_url: str = Field(alias="detectedUrl")
    recommended_model: str = Field(alias="recommendedModel")


class MultimodalAttachmentPayload(BaseModel):
    """聊天附件载荷。"""

    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(alias="mimeType", min_length=1, max_length=255)
    kind: AttachmentKind
    data_url: str | None = Field(default=None, alias="dataUrl")
    text_content: str | None = Field(default=None, alias="textContent")


class MultimodalChatMessagePayload(BaseModel):
    """聊天消息载荷。"""

    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True)

    role: ChatMessageRole
    content: str = Field(default="", max_length=20000)
    attachments: list[MultimodalAttachmentPayload] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_has_content(self) -> "MultimodalChatMessagePayload":
        """校验消息至少包含文本或附件。"""

        if self.content.strip() or self.attachments:
            return self
        raise ValueError("消息内容和附件不能同时为空")


class MultimodalChatRequest(BaseModel):
    """聊天测试请求。"""

    model_config = ConfigDict(populate_by_name=True)

    session_id: int | None = Field(default=None, alias="sessionId", gt=0)
    messages: list[MultimodalChatMessagePayload] = Field(min_length=1)


class MultimodalChatData(BaseModel):
    """聊天测试响应体。"""

    model_config = ConfigDict(populate_by_name=True)

    reply: str
    model_name: str = Field(alias="modelName")
    used_url: str = Field(alias="usedUrl")
    session_id: int = Field(alias="sessionId")


class MultimodalChatSessionResponse(BaseModel):
    """聊天会话摘要响应。"""

    model_config = ConfigDict(populate_by_name=True)

    id: int
    model_id: int = Field(alias="modelId")
    model_name: str = Field(alias="modelName")
    title: str
    message_count: int = Field(alias="messageCount")
    created_at: str = Field(alias="createdAt")
    updated_at: str = Field(alias="updatedAt")
    last_message_at: str | None = Field(alias="lastMessageAt")

    @classmethod
    def from_model(
        cls,
        chat_session: MultimodalChatSession,
        *,
        model_name: str,
    ) -> "MultimodalChatSessionResponse":
        """将数据库会话转换为对外响应模型。"""

        return cls(
            id=chat_session.id or 0,
            model_id=chat_session.model_id,
            model_name=model_name,
            title=chat_session.title,
            message_count=chat_session.message_count,
            created_at=chat_session.created_at.isoformat(),
            updated_at=chat_session.updated_at.isoformat(),
            last_message_at=(
                chat_session.last_message_at.isoformat()
                if chat_session.last_message_at
                else None
            ),
        )


class MultimodalChatMessageResponse(BaseModel):
    """聊天消息响应。"""

    model_config = ConfigDict(populate_by_name=True)

    id: int
    role: ChatMessageRole
    content: str
    attachments: list[MultimodalAttachmentPayload]
    used_url: str | None = Field(alias="usedUrl")
    created_at: str = Field(alias="createdAt")

    @classmethod
    def from_model(
        cls,
        chat_message: MultimodalChatMessage,
    ) -> "MultimodalChatMessageResponse":
        """将数据库消息转换为对外响应模型。"""

        return cls(
            id=chat_message.id or 0,
            role=chat_message.role,
            content=chat_message.content,
            attachments=parse_attachments(chat_message.attachments_json),
            used_url=chat_message.used_url,
            created_at=chat_message.created_at.isoformat(),
        )


class MultimodalChatSessionListData(BaseModel):
    """聊天会话列表响应体。"""

    items: list[MultimodalChatSessionResponse]


class MultimodalChatSessionDetailData(BaseModel):
    """聊天会话详情响应体。"""

    session: MultimodalChatSessionResponse
    messages: list[MultimodalChatMessageResponse]


class MultimodalChatSessionDeleteData(BaseModel):
    """聊天会话删除响应体。"""

    id: int


def parse_detected_models(detected_models_json: str | None) -> list[str]:
    """解析数据库中的探测模型缓存。"""

    if not detected_models_json:
        return []

    try:
        raw_models = json.loads(detected_models_json)
    except json.JSONDecodeError:
        return []

    if not isinstance(raw_models, list):
        return []
    return _normalize_detected_models([str(item) for item in raw_models])


def serialize_detected_models(models: list[str] | None) -> str | None:
    """序列化探测模型缓存。"""

    normalized_models = _normalize_detected_models(models)
    if not normalized_models:
        return None
    return json.dumps(normalized_models, ensure_ascii=False)


def parse_attachments(attachments_json: str | None) -> list[MultimodalAttachmentPayload]:
    """解析数据库中的附件 JSON。"""

    if not attachments_json:
        return []

    try:
        raw_attachments = json.loads(attachments_json)
    except json.JSONDecodeError:
        return []

    if not isinstance(raw_attachments, list):
        return []

    attachments: list[MultimodalAttachmentPayload] = []
    for item in raw_attachments:
        if not isinstance(item, dict):
            continue
        try:
            attachments.append(MultimodalAttachmentPayload.model_validate(item))
        except ValueError:
            continue
    return attachments


def serialize_attachments(
    attachments: list[MultimodalAttachmentPayload] | None,
) -> str | None:
    """序列化附件列表。"""

    if not attachments:
        return None
    return json.dumps(
        [attachment.model_dump(by_alias=True, exclude_none=True) for attachment in attachments],
        ensure_ascii=False,
    )
