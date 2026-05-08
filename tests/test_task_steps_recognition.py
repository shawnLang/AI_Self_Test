"""Task 识别步骤单元测试。"""

from __future__ import annotations

from pathlib import Path

from sqlmodel import SQLModel, Session, create_engine, select

from aiSelfTest.models.task import TaskItemData
from aiSelfTest.services.task_steps.llm_result import BoundingBox, LlmDetectedObject, LlmDetectionParser
from aiSelfTest.services.task_steps.matcher import TaskItemDataMatcher
from aiSelfTest.services.task_steps.video_recognition import VideoFrameExtractor


def test_llm_detection_parser_accepts_empty_and_detected_data() -> None:
    parser = LlmDetectionParser()

    empty_result = parser.parse('{"width": 100, "height": 80, "data": []}')
    detected_result = parser.parse('{"width": 100, "height": 80, "data": [{"name": "人", "bbox": [1, 2, 3, 4]}]}')

    assert empty_result.width == 100
    assert empty_result.data == []
    assert detected_result.data[0].name == "人"
    assert detected_result.data[0].bbox.xmax == 3


def test_image_matcher_updates_adds_and_deletes_rows() -> None:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        matched = TaskItemData(task_item_id=1, name="白鹭", score=0.9, track_ids="", sp_amount=1,
                               minx=0, miny=0, maxx=10, maxy=10)
        missed = TaskItemData(task_item_id=1, name="苍鹭", score=0.8, track_ids="", sp_amount=1,
                              minx=50, miny=50, maxx=70, maxy=70)
        session.add(matched)
        session.add(missed)
        session.commit()
        session.refresh(matched)
        session.refresh(missed)

        TaskItemDataMatcher().apply_image_results(
            session,
            1,
            [matched, missed],
            [
                LlmDetectedObject(name="夜鹭", bbox=BoundingBox(0, 0, 10, 10)),
                LlmDetectedObject(name="人", bbox=BoundingBox(80, 80, 90, 90)),
            ],
        )

        rows = session.exec(select(TaskItemData).where(TaskItemData.task_item_id == 1)).all()
        assert {row.status for row in rows} == {"修改", "删除", "新增"}
        assert any(row.llm_name == "夜鹭" and row.status == "修改" for row in rows)
        assert any(row.llm_name == "人" and row.status == "新增" for row in rows)


def test_video_extractor_parses_videojson_and_selects_five_keyframes(tmp_path: Path) -> None:
    videojson_path = tmp_path / "result.videojson"
    videojson_path.write_text(
        """
        [
          [{"index": 0, "name": "错名", "score": 0.10, "detName": "鸟", "bbox": [0, 0, 10, 10], "trackId": 1}],
          [{"index": 1, "score": 0.20, "bbox": [0, 0, 12, 12], "trackId": 2}],
          [{"index": 2, "score": 0.30, "bbox": [0, 0, 30, 30], "trackId": 1}],
          [{"index": 3, "score": 0.30, "bbox": [0, 0, 8, 8], "trackId": 2}],
          [{"index": 4, "score": 0.99, "bbox": [0, 0, 9, 9], "trackId": 1}],
          [{"index": 5, "score": 0.50, "bbox": [0, 0, 11, 11], "trackId": 2}],
          [{"index": 6, "score": 0.60, "bbox": [0, 0, 13, 13], "trackId": 1}]
        ]
        """,
        encoding="utf-8",
    )
    row = TaskItemData(task_item_id=1, name="鹌鹑", score=0.9, track_ids="1,2", sp_amount=1)
    extractor = VideoFrameExtractor()

    detections = extractor.find_row_detections(row, extractor.load_detections(videojson_path))
    key_detections = extractor.select_key_detections(detections)

    assert len(detections) == 7
    assert len(key_detections) == 5
    assert {item.frame_index for item in key_detections} == {0, 2, 3, 4, 6}
