"""TaskItemData 匹配判定。"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Sequence

from sqlmodel import Session

from aiSelfTest.models.task import TaskItemData, TaskItemDataStatus
from aiSelfTest.services.task_steps.llm_result import BoundingBox, LlmDetectedObject


IMAGE_IOU_THRESHOLD = 0.5


@dataclass(frozen=True)
class VideoRecognitionChoice:
    """单条视频业务结果的大模型候选名称。"""

    name: str
    score: float = 0.0


class TaskItemDataMatcher:
    """TaskItemData 匹配判定器。"""

    def __init__(self, image_iou_threshold: float = IMAGE_IOU_THRESHOLD) -> None:
        """初始化匹配参数。"""

        self.image_iou_threshold = image_iou_threshold

    def apply_image_results(self, session: Session, task_item_id: int, data_rows: Sequence[TaskItemData],
                            detected_objects: Sequence[LlmDetectedObject]) -> None:
        """按 bbox IoU 把图片大模型结果写回 TaskItemData。"""

        matched_row_ids: set[int] = set()
        for detected in detected_objects:
            best_row: TaskItemData | None = None
            best_iou = 0.0
            for row in data_rows:
                row_id = row.id or 0
                if row_id in matched_row_ids:
                    continue
                row_bbox = self._row_bbox(row)
                if row_bbox is None:
                    continue
                current_iou = self.calculate_iou(row_bbox, detected.bbox)
                if current_iou > best_iou:
                    best_iou = current_iou
                    best_row = row

            if best_row is not None and best_iou >= self.image_iou_threshold:
                best_row.llm_name = detected.name
                best_row.status = (
                    TaskItemDataStatus.DEFAULT.value
                    if detected.name.strip() == best_row.name.strip()
                    else TaskItemDataStatus.UPDATE.value
                )
                matched_row_ids.add(best_row.id or 0)
                session.add(best_row)
            else:
                session.add(
                    TaskItemData(
                        task_item_id=task_item_id,
                        name="",
                        score=0,
                        track_ids="",
                        sp_amount=1,
                        minx=detected.bbox.xmin,
                        miny=detected.bbox.ymin,
                        maxx=detected.bbox.xmax,
                        maxy=detected.bbox.ymax,
                        llm_name=detected.name,
                        status=TaskItemDataStatus.ADD.value,
                    )
                )

        for row in data_rows:
            if (row.id or 0) not in matched_row_ids:
                row.status = TaskItemDataStatus.DELETE.value
                session.add(row)
        session.commit()

    def apply_video_choice(self, row: TaskItemData, choices: Sequence[VideoRecognitionChoice]) -> None:
        """按单条 TaskItemData 的视频识别候选名称写回状态。"""

        if not choices:
            row.llm_name = None
            row.status = TaskItemDataStatus.DELETE.value
            return

        name_counts = Counter(choice.name for choice in choices if choice.name.strip())
        if not name_counts:
            row.llm_name = None
            row.status = TaskItemDataStatus.DELETE.value
            return

        max_count = max(name_counts.values())
        top_names = {name for name, count in name_counts.items() if count == max_count}
        best_choice = max((choice for choice in choices if choice.name in top_names), key=lambda choice: choice.score)
        row.llm_name = best_choice.name
        row.status = (
            TaskItemDataStatus.DEFAULT.value
            if best_choice.name.strip() == row.name.strip()
            else TaskItemDataStatus.UPDATE.value
        )

    @staticmethod
    def calculate_iou(first: BoundingBox, second: BoundingBox) -> float:
        """计算两个 bbox 的 IoU。"""

        inter_xmin = max(first.xmin, second.xmin)
        inter_ymin = max(first.ymin, second.ymin)
        inter_xmax = min(first.xmax, second.xmax)
        inter_ymax = min(first.ymax, second.ymax)
        inter_area = BoundingBox(inter_xmin, inter_ymin, inter_xmax, inter_ymax).area
        union_area = first.area + second.area - inter_area
        return 0.0 if union_area <= 0 else inter_area / union_area

    @staticmethod
    def _row_bbox(row: TaskItemData) -> BoundingBox | None:
        """从 TaskItemData 提取 bbox。"""

        if row.minx is None or row.miny is None or row.maxx is None or row.maxy is None:
            return None
        return BoundingBox(row.minx, row.miny, row.maxx, row.maxy)
