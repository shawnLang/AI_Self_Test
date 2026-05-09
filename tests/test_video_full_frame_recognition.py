"""视频整帧识别策略测试。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, Sequence


def test_load_detections_uses_outer_frame_index_for_videojson_arrays(tmp_path: Path) -> None:
    """二维 videojson 应使用外层数组下标作为真实帧号。"""

    from aiSelfTest.services.task_steps.video_recognition import VideoFrameExtractor

    videojson_path = tmp_path / "video.videojson"
    videojson_path.write_text(
        """
        [
          [{"index": 142, "trackId": 1, "bbox": [0, 0, 10, 10], "score": 0.9}],
          [{"index": 142, "trackId": 1, "bbox": [1, 0, 11, 10], "score": 0.9}],
          [{"index": 208, "trackId": 1, "bbox": [2, 0, 12, 10], "score": 0.9}]
        ]
        """,
        encoding="utf-8",
    )

    detections = VideoFrameExtractor().load_detections(videojson_path)

    assert [detection.frame_index for detection in detections] == [0, 1, 2]


def test_select_full_frame_detections_prioritizes_coverage_count_and_area() -> None:
    """整帧选帧应优先覆盖未达标 track、同帧目标数量和目标面积。"""

    from aiSelfTest.services.task_steps.video_recognition import VideoFrameExtractor

    extractor = VideoFrameExtractor(max_full_frames=3, target_frames_per_track=2)
    rows = [
        _row(row_id=1, name="白鹭", track_ids="1"),
        _row(row_id=2, name="苍鹭", track_ids="2"),
    ]
    detections = [
        _detection(frame=1, track_id="1", bbox=(0, 0, 10, 10)),
        _detection(frame=2, track_id="1", bbox=(0, 0, 80, 80)),
        _detection(frame=2, track_id="2", bbox=(100, 100, 160, 160)),
        _detection(frame=3, track_id="2", bbox=(100, 100, 110, 110)),
    ]

    selected = extractor.select_full_frame_detections(rows, detections)

    assert [frame.frame_index for frame in selected] == [2, 1, 3]
    assert len(selected) <= 3
    assert [len(frame.detections) for frame in selected] == [2, 1, 1]


def test_full_frame_video_recognition_calls_model_once_per_selected_frame(monkeypatch, tmp_path: Path) -> None:
    """整帧模式下，每个选中帧应单独调用一次大模型。"""

    from aiSelfTest.services.task_execution import MultimodalTaskItemRecognizer

    recognizer = MultimodalTaskItemRecognizer()
    rows = [
        _row(row_id=1, name="白鹭", track_ids="1"),
        _row(row_id=2, name="苍鹭", track_ids="2"),
    ]
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"fake-video")
    (tmp_path / "video.videojson").write_text("[]", encoding="utf-8")
    task_item = _task_item(video_path)
    detections = [
        _detection(frame=10, track_id="1", bbox=(0, 0, 100, 100)),
        _detection(frame=10, track_id="2", bbox=(120, 0, 220, 100)),
        _detection(frame=20, track_id="1", bbox=(0, 0, 90, 90)),
        _detection(frame=20, track_id="2", bbox=(120, 0, 210, 90)),
    ]
    extractor = FakeFullFrameExtractor(detections=detections)
    recognizer.video_extractor = extractor
    calls: list[list[str]] = []

    monkeypatch.setattr(recognizer, "_get_default_multimodal_model", lambda session: object())
    monkeypatch.setattr(recognizer, "_get_task_prompt", lambda session, config_id: "配置提示词")

    def fake_call_model(model, prompt, item, data_rows, attachments):
        calls.append([attachment.name for attachment in attachments])
        assert prompt == "配置提示词"
        frame_name = attachments[0].name
        if frame_name == "frame_10.jpg":
            return _result("白鹭", (0, 0, 100, 100))
        return _result("苍鹭", (120, 0, 210, 90))

    monkeypatch.setattr(recognizer, "_call_model", fake_call_model)

    result = recognizer._recognize_video_full_frame(object(), "配置提示词", task_item, rows)

    assert calls == [["frame_10.jpg"], ["frame_20.jpg"]]
    assert [choice.name for choice in result.video_results[1]] == ["白鹭"]
    assert [choice.name for choice in result.video_results[2]] == ["苍鹭"]


def test_video_recognition_mode_switches_between_full_frame_and_crop(monkeypatch) -> None:
    """视频识别模式配置应在整帧和旧裁剪逻辑之间切换。"""

    from aiSelfTest.services import task_execution
    from aiSelfTest.services.task_execution import MultimodalTaskItemRecognizer, TaskItemRecognitionResult

    recognizer = MultimodalTaskItemRecognizer()
    calls: list[str] = []

    def fake_full_frame(model, prompt, task_item, data_rows):
        calls.append("full_frame")
        return TaskItemRecognitionResult(video_results={})

    def fake_crop_per_row(model, prompt, task_item, data_rows):
        calls.append("crop_per_row")
        return TaskItemRecognitionResult(video_results={})

    monkeypatch.setattr(recognizer, "_recognize_video_full_frame", fake_full_frame)
    monkeypatch.setattr(recognizer, "_recognize_video_crop_per_row", fake_crop_per_row)

    monkeypatch.setattr(task_execution, "get_settings", lambda: SimpleNamespace(video_recognition_mode="full_frame"))
    recognizer._recognize_video(object(), "提示词", _task_item_for_switch(), [])

    monkeypatch.setattr(task_execution, "get_settings", lambda: SimpleNamespace(video_recognition_mode="crop_per_row"))
    recognizer._recognize_video(object(), "提示词", _task_item_for_switch(), [])

    assert calls == ["full_frame", "crop_per_row"]


def test_apply_video_choices_uses_vote_and_larger_bbox_tie_breaker() -> None:
    """视频整帧多次命中同一行时，应按票数和 bbox 面积写回最终名称。"""

    row = _row(row_id=1, name="白鹭", track_ids="1")
    row.det_name = "鸟"
    choices = [
        _choice("苍鹭", det_name="鸟", score=100),
        _choice("白鹭", det_name="兽", score=20),
        _choice("白鹭", det_name="鸟", score=30),
    ]

    from aiSelfTest.services.task_steps.matcher import TaskItemDataMatcher

    TaskItemDataMatcher().apply_video_choice(row, choices)

    assert row.llm_name == "白鹭"
    assert row.det_name == "鸟"
    assert row.llm_det_name == "鸟"
    assert row.status == "默认"


def test_llm_detection_parser_reads_det_name() -> None:
    """大模型新结构中的 detName 应解析为 llm 检测分类。"""

    from aiSelfTest.services.task_steps.llm_result import LlmDetectionParser

    result = LlmDetectionParser().parse(
        '{"width": 320, "height": 240, '
        '"data": [{"name": "白鹭", "detName": "鸟", "bbox": [1, 2, 3, 4]}]}'
    )

    assert result.width == 320
    assert result.height == 240
    assert result.data[0].name == "白鹭"
    assert result.data[0].det_name == "鸟"
    assert result.data[0].bbox.xmin == 1


def test_image_matcher_writes_llm_det_name_without_overwriting_source_det_name() -> None:
    """图片匹配只写模型检测分类，不覆盖上游原始检测分类。"""

    from aiSelfTest.services.task_steps.llm_result import BoundingBox, LlmDetectedObject
    from aiSelfTest.services.task_steps.matcher import TaskItemDataMatcher

    class FakeSession:
        def __init__(self) -> None:
            self.added: list[Any] = []
            self.committed = False

        def add(self, row: Any) -> None:
            self.added.append(row)

        def commit(self) -> None:
            self.committed = True

    row = _row(row_id=1, name="白鹭", track_ids="1")
    row.det_name = "鸟"
    session = FakeSession()
    detected = LlmDetectedObject(name="白鹭", det_name="兽", bbox=BoundingBox(0, 0, 100, 100))

    TaskItemDataMatcher().apply_image_results(session, 10, [row], [detected])

    assert row.det_name == "鸟"
    assert row.llm_det_name == "兽"
    assert row.llm_name == "白鹭"
    assert row.status == "默认"
    assert session.committed is True


def test_task_recognition_prompt_uses_config_prompt_without_duplicate_format_rules(tmp_path: Path) -> None:
    """配置提示词已含返回结构时，后端只追加上下文，不重复追加格式示例。"""

    from aiSelfTest.services.task_execution import MultimodalTaskItemRecognizer

    image_path = tmp_path / "image.jpg"
    from PIL import Image

    Image.new("RGB", (16, 9), color=(255, 255, 255)).save(image_path)
    configured_prompt = (
        "你是一个动物专家，如果没有就返回：{width:图片宽度,height:图片高度,data:[]}，"
        "如果有动物,人,车返回{width:图片宽度,height:图片高度,"
        "data:[{name:动物名称/人/车,detName:鸟/兽/人/车,bbox:[xmin,ymin,xmax,ymax]}]}"
    )

    prompt = MultimodalTaskItemRecognizer._build_task_recognition_prompt(
        configured_prompt,
        _image_task_item(image_path),
        [_row(row_id=1, name="白鹭", track_ids="1")],
    )

    assert prompt.startswith(configured_prompt)
    assert "只返回 JSON 对象，不要返回 Markdown" in prompt
    assert "文件名：image.jpg" in prompt
    assert "图片尺寸：width=16, height=9" in prompt
    assert "原始识别结果：" in prompt
    assert prompt.count("data:[{name:动物名称/人/车,detName:鸟/兽/人/车") == 1
    assert "没有动物、人、车时返回" not in prompt
    assert "有目标时返回" not in prompt


class FakeFullFrameExtractor:
    """只覆盖整帧识别需要的抽帧接口。"""

    def __init__(self, detections: Sequence[Any]) -> None:
        self.detections = list(detections)

    def load_detections(self, videojson_path: Path) -> list[Any]:
        return self.detections

    def select_full_frame_detections(
        self,
        data_rows: Sequence[Any],
        detections: Sequence[Any],
    ):
        from aiSelfTest.services.task_steps.video_recognition import VideoFrameExtractor

        return VideoFrameExtractor(max_full_frames=2, target_frames_per_track=2).select_full_frame_detections(
            data_rows,
            detections,
        )

    def build_full_frame_attachment(
        self,
        video_path: Path,
        frame_index: int,
    ) -> Any:
        from aiSelfTest.schemas.multimodal_model import MultimodalAttachmentPayload

        return MultimodalAttachmentPayload(
            name=f"frame_{frame_index}.jpg",
            mimeType="image/jpeg",
            kind="image",
            dataUrl="data:image/jpeg;base64,ZmFrZQ==",
        )


def _task_item(video_path: Path) -> Any:
    from aiSelfTest.models.task import TaskItem

    return TaskItem(
        id=10,
        task_id=1,
        name="video.mp4",
        file_bmp=2,
        file_path=video_path.as_posix(),
    )


def _task_item_for_switch() -> Any:
    from aiSelfTest.models.task import TaskItem

    return TaskItem(id=10, task_id=1, name="video.mp4", file_bmp=2)


def _image_task_item(image_path: Path) -> Any:
    from aiSelfTest.models.task import TaskItem

    return TaskItem(id=11, task_id=1, name=image_path.name, file_bmp=1, file_path=image_path.as_posix())


def _row(row_id: int, name: str, track_ids: str) -> Any:
    from aiSelfTest.models.task import TaskItemData

    return TaskItemData(
        id=row_id,
        task_item_id=10,
        name=name,
        track_ids=track_ids,
        score=0,
        sp_amount=1,
        minx=0,
        miny=0,
        maxx=100,
        maxy=100,
    )


def _detection(frame: int, track_id: str, bbox: tuple[float, float, float, float]) -> Any:
    from aiSelfTest.services.task_steps.video_recognition import TrackDetection

    return TrackDetection(frame_index=frame, track_id=track_id, bbox=bbox, score=0.9)


def _result(name: str, bbox: tuple[float, float, float, float]) -> Any:
    from aiSelfTest.services.task_steps.llm_result import BoundingBox, LlmDetectedObject, LlmDetectionResult

    detected = LlmDetectedObject(name=name, det_name="鸟", bbox=BoundingBox(*bbox))
    return LlmDetectionResult(width=320, height=240, data=[detected])


def _choice(name: str, det_name: str = "", score: float = 0.0):
    from aiSelfTest.services.task_steps.matcher import VideoRecognitionChoice

    return VideoRecognitionChoice(name=name, det_name=det_name, score=score)
