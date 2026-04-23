"""多模态模型测试会话与消息的数据库模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class MultimodalChatSession(SQLModel, table=True):
    """多模态模型测试会话。"""

    __tablename__ = "multimodal_chat_session"

    id: Optional[int] = Field(default=None, primary_key=True)
    model_id: int = Field(
        foreign_key="multimodal_model.id",
        index=True,
        description="关联的多模态模型配置",
    )
    title: str = Field(max_length=200, description="会话标题")
    message_count: int = Field(default=0, description="消息数量")
    last_message_at: Optional[datetime] = Field(default=None, description="最后消息时间")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    updated_at: datetime = Field(default_factory=datetime.now, description="更新时间")


class MultimodalChatMessage(SQLModel, table=True):
    """多模态模型测试消息。"""

    __tablename__ = "multimodal_chat_message"

    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: int = Field(
        foreign_key="multimodal_chat_session.id",
        index=True,
        description="关联的测试会话",
    )
    sequence_no: int = Field(index=True, description="消息顺序号")
    role: str = Field(max_length=20, description="消息角色")
    content: str = Field(default="", description="文本内容")
    attachments_json: Optional[str] = Field(default=None, description="附件 JSON")
    used_url: Optional[str] = Field(default=None, max_length=1000, description="实际调用地址")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
