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
DEFAULT_FULL_FRAME_TARGET_PER_TRACK = 3
DEFAULT_MAX_FULL_FRAME_COUNT = 30
VIDEO_CROP_PADDING_RATIO = 0.15


@dataclass(frozen=True)
class TrackDetection:
    """videojson 中命中的单条追踪检测结果。"""

    frame_index: int
    track_id: str
    bbox: tuple[float, float, float, float]
    score: float

    @property
    def area(self) -> float:
        """返回 bbox 面积。"""

        xmin, ymin, xmax, ymax = self.bbox
        return max(0.0, xmax - xmin) * max(0.0, ymax - ymin)


@dataclass(frozen=True)
class FullFrameDetectionGroup:
    """整帧识别选中的一帧及其相关 detection。"""

    frame_index: int
    detections: tuple[TrackDetection, ...]

    @property
    def track_ids(self) -> set[str]:
        """返回该帧覆盖的追踪 ID。"""

        return {detection.track_id for detection in self.detections}

    @property
    def detection_count(self) -> int:
        """返回该帧目标数量。"""

        return len(self.detections)

    @property
    def area_sum(self) -> float:
        """返回该帧目标 bbox 面积总和。"""

        return sum(detection.area for detection in self.detections)

    @property
    def max_area(self) -> float:
        """返回该帧最大目标 bbox 面积。"""

        return max((detection.area for detection in self.detections), default=0.0)


class VideoFrameExtractor:
    """解析 videojson 并构造视频关键帧裁剪附件。"""

    def __init__(self, max_keyframes: int = MAX_VIDEO_KEYFRAME_COUNT,
                 padding_ratio: float = VIDEO_CROP_PADDING_RATIO,
                 max_full_frames: int = DEFAULT_MAX_FULL_FRAME_COUNT,
                 target_frames_per_track: int = DEFAULT_FULL_FRAME_TARGET_PER_TRACK) -> None:
        """初始化视频抽帧参数。"""

        self.max_keyframes = max_keyframes
        self.padding_ratio = padding_ratio
        self.max_full_frames = max_full_frames
        self.target_frames_per_track = target_frames_per_track

    def load_detections(self, videojson_path: Path) -> list[TrackDetection]:
        """读取二维数组格式 videojson。"""

        logger.info("开始读取视频结果文件: path={}", videojson_path)
        try:
            payload = json.loads(videojson_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.exception("视频结果文件读取失败: path={}", videojson_path)
            raise AppException(
                code=ErrorCode.TASK_FAILED,
                message=f"视频结果文件读取失败: {videojson_path}",
                status_code=502,
            ) from exc
        if not isinstance(payload, list):
            logger.warning("视频结果文件格式错误: path={} payload_type={}", videojson_path, type(payload).__name__)
            raise AppException(code=ErrorCode.TASK_FAILED, message="视频结果文件格式必须是数组", status_code=502)

        detections: list[TrackDetection] = []
        frame_count = len(payload)
        for frame_index, frame_payload in enumerate(payload):
            if not isinstance(frame_payload, list):
                logger.warning(
                    "跳过非法视频帧结果: path={} frame_index={} frame_payload_type={}",
                    videojson_path,
                    frame_index,
                    type(frame_payload).__name__,
                )
                continue
            for row in frame_payload:
                detection = self._parse_detection(row, frame_index)
                if detection is not None:
                    detections.append(detection)
        logger.info("视频结果文件读取完成: path={} frame_count={} detection_count={}", videojson_path, frame_count, len(detections))
        return detections

    def find_row_detections(self, data_row: TaskItemData,
                            detections: Sequence[TrackDetection]) -> list[TrackDetection]:
        """按 TaskItemData.track_ids 提取命中的 detection。"""

        track_ids = {part.strip() for part in str(data_row.track_ids or "").split(",") if part.strip()}
        matched = [detection for detection in detections if detection.track_id in track_ids] if track_ids else []
        logger.info(
            "视频明细匹配 track detections: row_id={} track_ids={} matched_count={}",
            data_row.id,
            sorted(track_ids),
            len(matched),
        )
        return matched

    def select_key_detections(self, detections: Sequence[TrackDetection]) -> list[TrackDetection]:
        """选择首帧、末帧、最大面积、最高 score、时间中位帧。"""

        if not detections:
            logger.info("视频关键帧选择跳过: detection_count=0")
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
        selected = sorted(by_frame.values(), key=lambda item: item.frame_index)[:self.max_keyframes]
        logger.info(
            "视频关键帧选择完成: source_detection_count={} selected_count={} selected_frames={} track_ids={}",
            len(detections),
            len(selected),
            [item.frame_index for item in selected],
            [item.track_id for item in selected],
        )
        return selected

    def build_crop_attachments(self, video_path: Path,
                               detections: Sequence[TrackDetection]) -> list[MultimodalAttachmentPayload]:
        """按关键 detection 从视频抽帧并裁剪为图片附件。"""

        if not detections:
            logger.info("视频裁剪附件构建跳过: video_path={} detection_count=0", video_path)
            return []
        logger.info(
            "开始构建视频裁剪附件: video_path={} detection_count={} frames={}",
            video_path,
            len(detections),
            [detection.frame_index for detection in detections],
        )
        capture = cv2.VideoCapture(video_path.as_posix())
        if not capture.isOpened():
            logger.warning("视频文件无法打开: video_path={}", video_path)
            raise AppException(code=ErrorCode.TASK_FAILED, message=f"视频文件无法打开: {video_path}", status_code=502)

        attachments: list[MultimodalAttachmentPayload] = []
        try:
            for position, detection in enumerate(detections, start=1):
                logger.info(
                    "读取并裁剪视频关键帧: video_path={} frame_index={} track_id={} bbox={} score={} position={}",
                    video_path,
                    detection.frame_index,
                    detection.track_id,
                    detection.bbox,
                    detection.score,
                    position,
                )
                capture.set(cv2.CAP_PROP_POS_FRAMES, detection.frame_index)
                success, frame = capture.read()
                if not success or frame is None:
                    logger.warning(
                        "视频帧读取失败: video_path={} frame_index={} track_id={}",
                        video_path,
                        detection.frame_index,
                        detection.track_id,
                    )
                    raise AppException(
                        code=ErrorCode.TASK_FAILED,
                        message=f"视频帧读取失败: frame_index={detection.frame_index}",
                        status_code=502,
                    )
                crop = self._crop_frame(frame, detection.bbox)
                success, encoded = cv2.imencode(".jpg", crop)
                if not success:
                    logger.warning(
                        "视频关键帧裁剪图编码失败: video_path={} frame_index={} track_id={} bbox={}",
                        video_path,
                        detection.frame_index,
                        detection.track_id,
                        detection.bbox,
                    )
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
        logger.info("视频裁剪附件构建完成: video_path={} attachment_count={}", video_path, len(attachments))
        return attachments

    def select_full_frame_detections(
        self,
        data_rows: Sequence[TaskItemData],
        detections: Sequence[TrackDetection],
    ) -> list[FullFrameDetectionGroup]:
        """全局选择整帧识别候选帧。"""

        target_track_ids = self._collect_row_track_ids(data_rows)
        if not target_track_ids:
            logger.info("视频整帧候选选择跳过: data_row_count={} target_track_ids=empty", len(data_rows))
            return []

        frame_groups = self._group_full_frame_detections(detections, target_track_ids)
        if not frame_groups:
            logger.warning(
                "视频整帧候选选择无匹配帧: data_row_count={} detection_count={} target_track_ids={}",
                len(data_rows),
                len(detections),
                sorted(target_track_ids),
            )
            return []

        selected: list[FullFrameDetectionGroup] = []
        selected_indexes: set[int] = set()
        coverage = {track_id: 0 for track_id in target_track_ids}
        max_count = max(0, self.max_full_frames)
        target_count = max(1, self.target_frames_per_track)

        while len(selected) < max_count and any(count < target_count for count in coverage.values()):
            candidate = self._select_next_full_frame(frame_groups, selected_indexes, coverage, target_count)
            if candidate is None:
                break
            selected.append(candidate)
            selected_indexes.add(candidate.frame_index)
            for track_id in candidate.track_ids:
                if track_id in coverage:
                    coverage[track_id] += 1

        missing = {track_id: count for track_id, count in coverage.items() if count < target_count}
        if missing:
            logger.warning("视频整帧识别 track 覆盖不足: {}", missing)
        logger.info(
            "视频整帧候选选择完成: data_row_count={} detection_count={} frame_group_count={} selected_count={} "
            "selected_frames={} coverage={}",
            len(data_rows),
            len(detections),
            len(frame_groups),
            len(selected),
            [group.frame_index for group in selected],
            coverage,
        )
        return selected

    def build_full_frame_attachment(self, video_path: Path, frame_index: int) -> MultimodalAttachmentPayload:
        """从视频抽取原始整帧并构造图片附件。"""

        capture = cv2.VideoCapture(video_path.as_posix())
        if not capture.isOpened():
            logger.warning("视频文件无法打开: video_path={}", video_path)
            raise AppException(code=ErrorCode.TASK_FAILED, message=f"视频文件无法打开: {video_path}", status_code=502)
        try:
            logger.info("开始抽取视频整帧: video_path={} frame_index={}", video_path, frame_index)
            capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            success, frame = capture.read()
            if not success or frame is None:
                logger.warning("视频帧读取失败: video_path={} frame_index={}", video_path, frame_index)
                raise AppException(
                    code=ErrorCode.TASK_FAILED,
                    message=f"视频帧读取失败: frame_index={frame_index}",
                    status_code=502,
                )
            success, encoded = cv2.imencode(".jpg", frame)
            if not success:
                logger.warning("视频整帧图片编码失败: video_path={} frame_index={}", video_path, frame_index)
                raise AppException(code=ErrorCode.TASK_FAILED, message="视频整帧图片编码失败", status_code=502)
            data = base64.b64encode(encoded.tobytes()).decode("ascii")
            logger.info("视频整帧附件构建完成: video_path={} frame_index={} encoded_size={}", video_path, frame_index, len(data))
            return MultimodalAttachmentPayload(
                name=f"frame_{frame_index}.jpg",
                mimeType="image/jpeg",
                kind="image",
                dataUrl=f"data:image/jpeg;base64,{data}",
            )
        finally:
            capture.release()

    @staticmethod
    def _parse_detection(payload: Any, frame_index: int) -> TrackDetection | None:
        """从 videojson 单个对象解析 TrackDetection。"""

        if not isinstance(payload, Mapping):
            return None
        bbox_payload = payload.get("bbox")
        if not isinstance(bbox_payload, list) or len(bbox_payload) != 4:
            return None
        track_id = str(payload.get("trackId", "")).strip()
        if not track_id:
            return None
        try:
            bbox = tuple(float(value) for value in bbox_payload)
            score = float(payload.get("score") or 0)
        except (TypeError, ValueError):
            logger.warning("跳过非法视频 detection: {}", payload)
            return None
        return TrackDetection(frame_index=frame_index, track_id=track_id,
                              bbox=(bbox[0], bbox[1], bbox[2], bbox[3]), score=score)

    @staticmethod
    def _collect_row_track_ids(data_rows: Sequence[TaskItemData]) -> set[str]:
        """收集当前任务明细需要复核的 track_id。"""

        track_ids: set[str] = set()
        for row in data_rows:
            track_ids.update(part.strip() for part in str(row.track_ids or "").split(",") if part.strip())
        return track_ids

    @staticmethod
    def _group_full_frame_detections(
        detections: Sequence[TrackDetection],
        target_track_ids: set[str],
    ) -> list[FullFrameDetectionGroup]:
        """按帧聚合目标 track 的 detection。"""

        by_frame: dict[int, list[TrackDetection]] = {}
        for detection in detections:
            if detection.track_id not in target_track_ids:
                continue
            by_frame.setdefault(detection.frame_index, []).append(detection)
        return [
            FullFrameDetectionGroup(frame_index=frame_index, detections=tuple(frame_detections))
            for frame_index, frame_detections in sorted(by_frame.items())
            if frame_detections
        ]

    @staticmethod
    def _select_next_full_frame(
        frame_groups: Sequence[FullFrameDetectionGroup],
        selected_indexes: set[int],
        coverage: dict[str, int],
        target_count: int,
    ) -> FullFrameDetectionGroup | None:
        """从剩余候选帧中选择下一帧。"""

        best_group: FullFrameDetectionGroup | None = None
        best_score: tuple[int, int, float, float, int] | None = None
        for group in frame_groups:
            if group.frame_index in selected_indexes:
                continue
            undercovered_tracks = {
                track_id
                for track_id in group.track_ids
                if track_id in coverage and coverage[track_id] < target_count
            }
            if not undercovered_tracks:
                continue
            score = (
                len(undercovered_tracks),
                group.detection_count,
                group.area_sum,
                group.max_area,
                -group.frame_index,
            )
            if best_score is None or score > best_score:
                best_score = score
                best_group = group
        return best_group

    def _crop_frame(self, frame: Any, bbox: Sequence[float]) -> Any:
        """按 bbox 加 padding 裁剪 OpenCV 帧。"""

        height, width = frame.shape[:2]
        bbox_values = list(bbox)
        if len(bbox_values) != 4:
            raise AppException(code=ErrorCode.TASK_FAILED, message="视频关键帧 bbox 坐标数量非法", status_code=502)

        xmin = float(bbox_values[0])
        ymin = float(bbox_values[1])
        xmax = float(bbox_values[2])
        ymax = float(bbox_values[3])
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
