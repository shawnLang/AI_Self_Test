"""多模态聊天附件归一化工具。"""

from __future__ import annotations

import binascii
import re
from typing import Any

from aiSelfTest.schemas.multimodal_model import (
    MultimodalAttachmentPayload,
    MultimodalChatMessagePayload,
)
from loguru import logger

TEXT_ATTACHMENT_LIMIT = 4000
DATA_URL_PATTERN = re.compile(r"^data:(?P<mime>[^;]+);base64,(?P<data>.+)$", re.IGNORECASE)


def build_gateway_chat_payload(model_name: str, messages: list[MultimodalChatMessagePayload],
                               stream: bool) -> dict[str, Any]:
    """构造发送给模型网关的聊天载荷。"""

    payload: dict[str, Any] = {
        "model": model_name,
        "messages": [
            _normalize_chat_message(message)
            for message in messages
        ],
    }
    if stream:
        payload["stream"] = True
    logger.debug(
        "多模态网关聊天载荷构建完成: model_name={}, message_count={}, stream={}",
        model_name,
        len(messages),
        stream,
    )
    return payload


def _normalize_chat_message(message: MultimodalChatMessagePayload) -> dict[str, Any]:
    """将聊天消息转换为兼容 chat/completions 的结构。"""

    parts: list[dict[str, Any]] = []
    content_text = message.content.strip()
    if content_text:
        parts.append({"type": "text", "text": content_text})

    for attachment in message.attachments:
        parts.extend(_normalize_attachment(attachment))

    if not parts:
        return {"role": message.role, "content": ""}

    if len(parts) == 1 and parts[0]["type"] == "text":
        return {"role": message.role, "content": parts[0]["text"]}

    return {"role": message.role, "content": parts}


def _normalize_attachment(attachment: MultimodalAttachmentPayload) -> list[dict[str, Any]]:
    """将附件归一化为模型可识别的消息片段。"""

    if attachment.kind == "image" and attachment.data_url:
        return [
            {
                "type": "image_url",
                "image_url": {"url": attachment.data_url},
            }
        ]

    if attachment.kind == "audio" and attachment.data_url:
        audio_content = _parse_audio_data_url(attachment.data_url)
        if audio_content is not None:
            return [
                {
                    "type": "input_audio",
                    "input_audio": audio_content,
                }
            ]
        logger.warning(
            "忽略无法解析的音频附件 data URL: attachment_name={}, mime_type={}",
            attachment.name,
            attachment.mime_type,
        )

    if attachment.text_content:
        preview_text = attachment.text_content.strip()[:TEXT_ATTACHMENT_LIMIT]
        return [
            {
                "type": "text",
                "text": f"附件《{attachment.name}》内容如下：\n{preview_text}",
            }
        ]

    return [
        {
            "type": "text",
            "text": (
                f"收到附件《{attachment.name}》，"
                f"类型为 {attachment.kind}，MIME 为 {attachment.mime_type}。"
                "当前接口仅提供说明性文本，请结合上下文回答。"
            ),
        }
    ]


def _parse_audio_data_url(data_url: str) -> dict[str, str] | None:
    """解析音频 data URL。"""

    match = DATA_URL_PATTERN.match(data_url)
    if match is None:
        return None

    mime_type = match.group("mime").lower()
    base64_data = match.group("data")
    try:
        binascii.a2b_base64(base64_data)
    except binascii.Error:
        return None

    audio_format = mime_type.split("/")[-1].split("+")[0]
    if audio_format == "mpeg":
        audio_format = "mp3"

    return {
        "data": base64_data,
        "format": audio_format,
    }
