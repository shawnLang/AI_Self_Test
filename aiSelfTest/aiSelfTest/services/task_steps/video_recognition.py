"""视频任务项识别辅助逻辑。"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import cv2
from loguru import logger

from aiSelfTest.exceptions import AppException, ErrorCode
from aiSelfTest.models.task import TaskItemData
from aiSelfTest.schemas.multimodal_model import MultimodalAttachmentPayload

MAX_VIDEO_KEYFRAME_COUNT = 5
VIDEO_CROP_PADDING_RATIO = 0.15


@dataclass(frozen=True)
class TrackDetection:
    """datajson 中命中的单条追踪检测结果。"""

    frame_index: int
    track_id: str
    bbox: tuple[float, float, float, float]
    score: float

    @property
    def area(self) -> float:
        """返回 bbox 面积。"""

        xmin, ymin, xmax, ymax = self.bbox
        return max(0.0, xmax - xmin) * max(0.0, ymax - ymin)


class VideoFrameExtractor:
    """解析 datajson 并构造视频关键帧裁剪附件。"""

    def __init__(self, max_keyframes: int = MAX_VIDEO_KEYFRAME_COUNT,
                 padding_ratio: float = VIDEO_CROP_PADDING_RATIO) -> None:
        """初始化视频抽帧参数。"""

        self.max_keyframes = max_keyframes
        self.padding_ratio = padding_ratio

    def load_detections(self, datajson_path: Path) -> list[TrackDetection]:
        """读取二维数组格式 datajson。"""

        try:
            payload = json.loads(datajson_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AppException(
                code=ErrorCode.TASK_FAILED,
                message=f"视频结果文件读取失败: {datajson_path}",
                status_code=502,
            ) from exc
        if not isinstance(payload, list):
            raise AppException(code=ErrorCode.TASK_FAILED, message="视频结果文件格式必须是数组", status_code=502)

        detections: list[TrackDetection] = []
        for fallback_index, frame_payload in enumerate(payload):
            if not isinstance(frame_payload, list):
                continue
            for row in frame_payload:
                detection = self._parse_detection(row, fallback_index)
                if detection is not None:
                    detections.append(detection)
        return detections

    def find_row_detections(self, data_row: TaskItemData,
                            detections: Sequence[TrackDetection]) -> list[TrackDetection]:
        """按 TaskItemData.track_ids 提取命中的 detection。"""

        track_ids = {part.strip() for part in str(data_row.track_ids or "").split(",") if part.strip()}
        return [detection for detection in detections if detection.track_id in track_ids] if track_ids else []

    def select_key_detections(self, detections: Sequence[TrackDetection]) -> list[TrackDetection]:
        """选择首帧、末帧、最大面积、最高 score、时间中位帧。"""

        if not detections:
            return []
        sorted_detections = sorted(detections, key=lambda item: item.frame_index)
        candidates = [
            sorted_detections[0],
            sorted_detections[-1],
            max(sorted_detections, key=lambda item: item.area),
            max(sorted_detections, key=lambda item: item.score),
            sorted_detections[len(sorted_detections) // 2],
        ]

        by_frame: dict[int, TrackDetection] = {}
        for detection in candidates:
            existing = by_frame.get(detection.frame_index)
            if existing is None or detection.area > existing.area:
                by_frame[detection.frame_index] = detection
        return sorted(by_frame.values(), key=lambda item: item.frame_index)[:self.max_keyframes]

    def build_crop_attachments(self, video_path: Path,
                               detections: Sequence[TrackDetection]) -> list[MultimodalAttachmentPayload]:
        """按关键 detection 从视频抽帧并裁剪为图片附件。"""

        if not detections:
            return []
        capture = cv2.VideoCapture(video_path.as_posix())
        if not capture.isOpened():
            raise AppException(code=ErrorCode.TASK_FAILED, message=f"视频文件无法打开: {video_path}", status_code=502)

        attachments: list[MultimodalAttachmentPayload] = []
        try:
            for position, detection in enumerate(detections, start=1):
                capture.set(cv2.CAP_PROP_POS_FRAMES, detection.frame_index)
                success, frame = capture.read()
                if not success or frame is None:
                    raise AppException(
                        code=ErrorCode.TASK_FAILED,
                        message=f"视频帧读取失败: frame_index={detection.frame_index}",
                        status_code=502,
                    )
                crop = self._crop_frame(frame, detection.bbox)
                success, encoded = cv2.imencode(".jpg", crop)
                if not success:
                    raise AppException(code=ErrorCode.TASK_FAILED, message="视频关键帧裁剪图编码失败", status_code=502)
                data = base64.b64encode(encoded.tobytes()).decode("ascii")
                attachments.append(
                    MultimodalAttachmentPayload(
                        name=f"track_crop_{detection.track_id}_{position}.jpg",
                        mimeType="image/jpeg",
                        kind="image",
                        dataUrl=f"data:image/jpeg;base64,{data}",
                    )
                )
        finally:
            capture.release()
        return attachments

    @staticmethod
    def _parse_detection(payload: Any, fallback_index: int) -> TrackDetection | None:
        """从 datajson 单个对象解析 TrackDetection。"""

        if not isinstance(payload, Mapping):
            return None
        bbox_payload = payload.get("bbox")
        if not isinstance(bbox_payload, list) or len(bbox_payload) != 4:
            return None
        track_id = str(payload.get("trackId", "")).strip()
        if not track_id:
            return None
        try:
            frame_index = int(payload.get("index", fallback_index))
            bbox = tuple(float(value) for value in bbox_payload)
            score = float(payload.get("score") or 0)
        except (TypeError, ValueError):
            logger.warning("跳过非法视频 detection: {}", payload)
            return None
        return TrackDetection(frame_index=frame_index, track_id=track_id,
                              bbox=(bbox[0], bbox[1], bbox[2], bbox[3]), score=score)

    def _crop_frame(self, frame: Any, bbox: tuple[float, float, float, float]) -> Any:
        """按 bbox 加 padding 裁剪 OpenCV 帧。"""

        height, width = frame.shape[:2]
        xmin, ymin, xmax, ymax = bbox
        box_width = max(1.0, xmax - xmin)
        box_height = max(1.0, ymax - ymin)
        pad_x = box_width * self.padding_ratio
        pad_y = box_height * self.padding_ratio
        left = max(0, int(round(xmin - pad_x)))
        top = max(0, int(round(ymin - pad_y)))
        right = min(width, int(round(xmax + pad_x)))
        bottom = min(height, int(round(ymax + pad_y)))
        if right <= left or bottom <= top:
            raise AppException(code=ErrorCode.TASK_FAILED, message="视频关键帧 bbox 裁剪范围非法", status_code=502)
        return frame[top:bottom, left:right]
