"""大模型检测结果解析。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from aiSelfTest.exceptions import AppException, ErrorCode


@dataclass(frozen=True)
class BoundingBox:
    """检测框坐标。"""

    xmin: float
    ymin: float
    xmax: float
    ymax: float

    @classmethod
    def from_sequence(cls, value: Sequence[Any]) -> "BoundingBox":
        """从列表解析 bbox。"""

        if len(value) != 4:
            raise AppException(
                code=ErrorCode.TASK_FAILED,
                message="大模型 bbox 长度必须为 4",
                status_code=502,
            )
        try:
            xmin, ymin, xmax, ymax = [float(item) for item in value]
        except (TypeError, ValueError) as exc:
            raise AppException(
                code=ErrorCode.TASK_FAILED,
                message="大模型 bbox 必须为数字",
                status_code=502,
            ) from exc
        return cls(xmin=xmin, ymin=ymin, xmax=xmax, ymax=ymax)

    @property
    def area(self) -> float:
        """返回 bbox 面积。"""

        return max(0.0, self.xmax - self.xmin) * max(0.0, self.ymax - self.ymin)


@dataclass(frozen=True)
class LlmDetectedObject:
    """大模型返回的单个目标。"""

    name: str
    det_name: str
    bbox: BoundingBox


@dataclass(frozen=True)
class LlmDetectionResult:
    """大模型检测结果。"""

    width: int
    height: int
    data: list[LlmDetectedObject]


class LlmDetectionParser:
    """解析大模型 `{width,height,data}` 回复。"""

    def parse(self, reply: str) -> LlmDetectionResult:
        """解析大模型回复。"""

        try:
            payload = json.loads(self._extract_json_text(reply.strip()))
        except json.JSONDecodeError as exc:
            raise AppException(
                code=ErrorCode.TASK_FAILED,
                message="大模型识别结果不是可解析 JSON",
                status_code=502,
            ) from exc
        if not isinstance(payload, Mapping):
            raise AppException(
                code=ErrorCode.TASK_FAILED,
                message="大模型识别结果必须是 JSON 对象",
                status_code=502,
            )

        try:
            width = int(payload.get("width", 0))
            height = int(payload.get("height", 0))
        except (TypeError, ValueError) as exc:
            raise AppException(
                code=ErrorCode.TASK_FAILED,
                message="大模型 width/height 必须为整数",
                status_code=502,
            ) from exc

        data_payload = payload.get("data", [])
        if not isinstance(data_payload, list):
            raise AppException(
                code=ErrorCode.TASK_FAILED,
                message="大模型 data 必须为数组",
                status_code=502,
            )

        objects: list[LlmDetectedObject] = []
        for item in data_payload:
            if not isinstance(item, Mapping):
                continue
            name = str(item.get("name", "")).strip()
            det_name = str(item.get("detName", "")).strip()
            bbox_payload = item.get("bbox")
            if not name or not isinstance(bbox_payload, Sequence) or isinstance(bbox_payload, (str, bytes)):
                continue
            objects.append(
                LlmDetectedObject(
                    name=name,
                    det_name=det_name,
                    bbox=BoundingBox.from_sequence(bbox_payload),
                )
            )

        return LlmDetectionResult(width=width, height=height, data=objects)

    @staticmethod
    def _extract_json_text(text: str) -> str:
        """从 Markdown 代码块或说明文本中提取 JSON。"""

        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()

        starts = [position for position in (text.find("{"), text.find("[")) if position >= 0]
        if not starts:
            return text
        start = min(starts)
        end = max(text.rfind("}"), text.rfind("]"))
        return text[start:end + 1] if end >= start else text
