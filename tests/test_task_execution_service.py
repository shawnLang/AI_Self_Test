"""Task 执行主干服务测试。"""

from __future__ import annotations

import importlib
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlmodel import Session, select


class FakeResponse:
    """简化 requests 响应对象。"""

    def __init__(self, status_code: int, json_data: dict[str, Any]) -> None:
        self.status_code = status_code
        self._json_data = json_data
        self.text = str(json_data)

    def json(self) -> dict[str, Any]:
        """返回 JSON 响应体。"""

        return self._json_data


class FakeTaskFileDownloader:
    """测试用文件下载器，写入可断言的本地文件。"""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.calls: list[str] = []

    def download(self, **kwargs: Any) -> Any:
        """模拟原始文件与视频结果文件下载。"""

        task_item = kwargs["task_item"]
        source_record = kwargs["source_record"]
        from aiSelfTest.services.client import get_client_or_raise
        from aiSelfTest.services.task_execution import TaskDownloadResult, build_task_item_save_name

        item_dir = self.root / "task_files" / str(task_item.task_id) / str(task_item.id)
        item_dir.mkdir(parents=True, exist_ok=True)
        client = get_client_or_raise(kwargs["session"], kwargs["task"].client_id)
        file_path = item_dir / build_task_item_save_name(client, source_record, task_item.file_extension)
        if task_item.file_bmp == 2:
            self._write_test_video(file_path)
        else:
            Image.new("RGB", (100, 100), color=(255, 255, 255)).save(file_path)
        result_file_path = None
        if task_item.result_file_data:
            result_file_path = item_dir / build_task_item_save_name(client, source_record, "videojson")
            result_file_path.write_text(
                """
                [
                  [{"index": 0, "score": 0.5, "bbox": [10, 10, 30, 30], "trackId": "track-1"}],
                  [{"index": 1, "score": 0.9, "bbox": [12, 12, 35, 35], "trackId": "track-1"}],
                  [{"index": 2, "score": 0.7, "bbox": [11, 11, 32, 32], "trackId": "track-1"}]
                ]
                """,
                encoding="utf-8",
            )
        self.calls.append(source_record.file_fid)
        return TaskDownloadResult(
            file_path=file_path.as_posix(),
            result_file_path=result_file_path.as_posix() if result_file_path else None,
        )

    @staticmethod
    def _write_test_video(file_path: Path) -> None:
        """写入可供 OpenCV 读取的测试视频。"""

        writer = cv2.VideoWriter(file_path.as_posix(), cv2.VideoWriter_fourcc(*"mp4v"), 1, (80, 80))
        for value in (0, 80, 160):
            frame = np.full((80, 80, 3), value, dtype=np.uint8)
            writer.write(frame)
        writer.release()


class FakeTaskItemRecognizer:
    """测试用大模型识别器。"""

    def __init__(self) -> None:
        self.calls: list[int] = []

    def recognize(self, **kwargs: Any) -> Any:
        """返回与原始名称不同的识别结果，避免复制原始名称的占位逻辑。"""

        task_item = kwargs["task_item"]
        data_rows = kwargs["data_rows"]
        from aiSelfTest.services.task_execution import TaskItemRecognitionResult
        from aiSelfTest.services.task_steps.llm_result import BoundingBox, LlmDetectedObject, LlmDetectionResult
        from aiSelfTest.services.task_steps.matcher import VideoRecognitionChoice

        self.calls.append(task_item.id)
        if task_item.file_bmp == 2:
            return TaskItemRecognitionResult(
                video_results={row.id: [VideoRecognitionChoice(name=f"AI-{row.name}", score=0.9)] for row in data_rows}
            )
        return TaskItemRecognitionResult(
            image_result=LlmDetectionResult(
                width=100,
                height=100,
                data=[LlmDetectedObject(name=f"AI-{row.name}", bbox=BoundingBox(row.minx, row.miny, row.maxx, row.maxy))
                      for row in data_rows],
            )
        )


class MatchingTaskItemRecognizer(FakeTaskItemRecognizer):
    """测试用大模型识别器，返回与原始识别名称一致的结果。"""

    def recognize(self, **kwargs: Any) -> Any:
        """返回和原始名称一致的识别结果。"""

        task_item = kwargs["task_item"]
        data_rows = kwargs["data_rows"]
        from aiSelfTest.services.task_execution import TaskItemRecognitionResult
        from aiSelfTest.services.task_steps.llm_result import BoundingBox, LlmDetectedObject, LlmDetectionResult
        from aiSelfTest.services.task_steps.matcher import VideoRecognitionChoice

        self.calls.append(task_item.id)
        if task_item.file_bmp == 2:
            return TaskItemRecognitionResult(
                video_results={row.id: [VideoRecognitionChoice(name=row.name, score=0.9)] for row in data_rows}
            )
        return TaskItemRecognitionResult(
            image_result=LlmDetectionResult(
                width=100,
                height=100,
                data=[
                    LlmDetectedObject(name=row.name, bbox=BoundingBox(row.minx, row.miny, row.maxx, row.maxy))
                    for row in data_rows
                ],
            )
        )


class FlakyTaskItemRecognizer(FakeTaskItemRecognizer):
    """首次识别失败、后续成功的测试识别器。"""

    def __init__(self) -> None:
        """初始化失败记录。"""

        super().__init__()
        self.failed_item_ids: set[int] = set()

    def recognize(self, **kwargs: Any) -> Any:
        """模拟模型网关临时失败后恢复。"""

        task_item = kwargs["task_item"]
        task_item_id = task_item.id or 0
        if task_item_id not in self.failed_item_ids:
            self.failed_item_ids.add(task_item_id)
            from aiSelfTest.exceptions import AppException, ErrorCode

            raise AppException(
                code=ErrorCode.INTERNAL_ERROR,
                message="模型网关返回了非 JSON 响应",
                status_code=502,
            )
        return super().recognize(**kwargs)


def test_build_upstream_page_payload_skips_empty_filter_values() -> None:
    """空筛选参数不应写入上游分页请求体。"""

    from aiSelfTest.schemas.task import TaskFiltersPayload
    from aiSelfTest.services.task_execution import AuthenticatedTaskExecutionSource, TaskExecutionWindow

    source = AuthenticatedTaskExecutionSource()
    payload = source.build_upstream_page_payload(
        filters=TaskFiltersPayload(
            keyword="",
            sp_name="",
            start_at="",
            end_at="",
            classify_list=[],
            media_types=[],
            upload_types=[],
            identify_source=[],
            module="",
        ),
        window=TaskExecutionWindow(start_at="", end_at=""),
        current=1,
        size=100,
    )

    assert payload == {
        "size": 100,
        "current": 1,
        "sortColumn": "fe.created_time",
        "sortOrder": "ASC",
        "module": "camera",
    }


def test_build_upstream_page_payload_keeps_non_empty_filter_values() -> None:
    """非空筛选参数应继续按上游字段名写入请求体。"""

    from aiSelfTest.schemas.task import TaskFiltersPayload
    from aiSelfTest.services.task_execution import AuthenticatedTaskExecutionSource, TaskExecutionWindow

    source = AuthenticatedTaskExecutionSource()
    payload = source.build_upstream_page_payload(
        filters=TaskFiltersPayload(
            keyword="鸟类",
            sp_name="白鹭",
            classify_list=[1, 2],
            media_types=["image", "video"],
            upload_types=[3],
            identify_source=[0],
            module="lure",
        ),
        window=TaskExecutionWindow(start_at="2026-04-20", end_at="2026-04-25"),
        current=2,
        size=50,
    )

    assert payload == {
        "size": 50,
        "current": 2,
        "keyword": "鸟类",
        "spName": "白鹭",
        "startTime": "2026-04-20 00:00:00",
        "endTime": "2026-04-25 23:59:59",
        "sortColumn": "fe.created_time",
        "sortOrder": "ASC",
        "classifyList": [1, 2],
        "fileBmp": [1, 2],
        "uploadType": [3],
        "idWayList": [0],
        "module": "lure",
    }


def test_task_execution_ingests_records_and_advances_shared_trunk(
    app_client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    task_id = _create_task(app_client, execution_mode="auto")
    _install_task_upstream_mock(monkeypatch)
    run_task_execution = _import_run_task_execution()
    task_model, task_item_model, task_item_data_model = _import_task_models()
    task_status, item_status, llm_state, confirm_state, remote_state, train_state = _import_task_status_enums()
    downloader = FakeTaskFileDownloader(_get_data_dir())
    recognizer = FakeTaskItemRecognizer()

    result = run_task_execution(
        db_session,
        task_id,
        downloader=downloader,
        recognizer=recognizer,
        now=datetime(2026, 4, 25, 10, 0, 0),
    )

    task = db_session.get(task_model, task_id)
    items = db_session.exec(
        select(task_item_model).where(task_item_model.task_id == task_id)
    ).all()
    rows = db_session.exec(select(task_item_data_model)).all()

    assert result.inserted_count == 2
    assert result.skipped_count == 0
    assert result.detail_row_count == 2
    assert result.execution_status == task_status.VERIFY.value
    assert task.execution_status == task_status.VERIFY.value
    assert task.total_count == 2
    assert task.processed_count == 2
    assert task.stage_started_at is None
    assert task.last_progress_at is None
    assert task.last_run_started_at is not None
    assert task.last_pull_end_at is not None
    assert {item.file_id for item in items} == {101, 102}
    assert {item.file_fid for item in items} == {"fid-image-1", "fid-video-1"}
    assert {item.file_url for item in items} == {"image-1.jpg", "video-1.mp4"}
    assert {item.file_bmp for item in items} == {1, 2}
    assert all(item.down_state is True for item in items)
    assert all(item.llm_state == llm_state.SUCCESS.value for item in items)
    assert all(item.confirm_state == confirm_state.PENDING.value for item in items)
    assert all(item.remote_state == remote_state.PENDING.value for item in items)
    assert all(item.train_state == train_state.PENDING.value for item in items)
    assert all(item.status == item_status.VERIFY_PENDING.value for item in items)
    assert {row.llm_name for row in rows} == {"AI-白鹭", "AI-苍鹭"}
    assert {row.status for row in rows} == {"修改"}
    assert set(downloader.calls) == {"fid-image-1", "fid-video-1"}
    assert len(recognizer.calls) == 2
    assert all(Path(item.file_path).exists() for item in items)
    assert {Path(item.file_path).name for item in items} == {
        "树蛙保护区_tenant-001_camera-1_camera_101_IMG-001_ai_确种.jpg",
        "树蛙保护区_tenant-001_camera-2_camera_102_VID-001_ai_有效.mp4",
    }
    video_item = next(item for item in items if item.file_bmp == 2)
    assert video_item.result_file_data == "video-result.json"
    assert (
        Path(video_item.file_path).parent
        / "树蛙保护区_tenant-001_camera-2_camera_102_VID-001_ai_有效.videojson"
    ).exists()


def test_manual_task_execution_runs_full_pre_review_flow_after_click(
    app_client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    task_id = _create_task(app_client, execution_mode="manual")
    _install_task_upstream_mock(monkeypatch)
    run_task_execution = _import_run_task_execution()
    task_model, task_item_model, task_item_data_model = _import_task_models()
    task_status, item_status, llm_state, confirm_state, remote_state, _ = _import_task_status_enums()
    downloader = FakeTaskFileDownloader(_get_data_dir())
    recognizer = FakeTaskItemRecognizer()

    result = run_task_execution(
        db_session,
        task_id,
        downloader=downloader,
        recognizer=recognizer,
        now=datetime(2026, 4, 25, 10, 0, 0),
    )

    items = db_session.exec(
        select(task_item_model).where(task_item_model.task_id == task_id)
    ).all()
    rows = db_session.exec(select(task_item_data_model)).all()
    task = db_session.get(task_model, task_id)

    assert result.inserted_count == 2
    assert result.execution_status == task_status.VERIFY.value
    assert task.execution_status == task_status.VERIFY.value
    assert all(item.down_state is True for item in items)
    assert all(item.llm_state == llm_state.SUCCESS.value for item in items)
    assert all(item.confirm_state == confirm_state.PENDING.value for item in items)
    assert all(item.remote_state == remote_state.PENDING.value for item in items)
    assert all(item.status == item_status.VERIFY_PENDING.value for item in items)
    assert {row.llm_name for row in rows} == {"AI-白鹭", "AI-苍鹭"}
    assert set(downloader.calls) == {"fid-image-1", "fid-video-1"}
    assert len(recognizer.calls) == 2


def test_task_execution_recognizes_all_images_before_videos(
    app_client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    """大模型识别阶段应先处理全部图片，再处理视频。"""

    task_id = _create_task(app_client, execution_mode="auto")
    source_records = _source_records()
    _install_task_upstream_mock(monkeypatch, records=[source_records[1], source_records[0]])
    run_task_execution = _import_run_task_execution()
    _, task_item_model, _ = _import_task_models()
    downloader = FakeTaskFileDownloader(_get_data_dir())
    recognizer = FakeTaskItemRecognizer()

    run_task_execution(
        db_session,
        task_id,
        downloader=downloader,
        recognizer=recognizer,
        now=datetime(2026, 4, 25, 10, 0, 0),
    )

    items = db_session.exec(
        select(task_item_model).where(task_item_model.task_id == task_id).order_by(task_item_model.id)
    ).all()
    media_type_by_item_id = {item.id: item.file_bmp for item in items}

    assert [item.file_bmp for item in items] == [2, 1]
    assert [media_type_by_item_id[item_id] for item_id in recognizer.calls] == [1, 2]


def test_task_execution_retries_transient_llm_recognition_error(
    app_client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    task_id = _create_task(app_client, execution_mode="auto")
    _install_task_upstream_mock(monkeypatch, records=_source_records()[:1])
    run_task_execution = _import_run_task_execution()
    task_model, task_item_model, _ = _import_task_models()
    task_status, item_status, llm_state, *_ = _import_task_status_enums()
    downloader = FakeTaskFileDownloader(_get_data_dir())
    recognizer = FlakyTaskItemRecognizer()

    from aiSelfTest.services import task_execution

    monkeypatch.setattr(task_execution, "TASK_ITEM_RECOGNITION_RETRY_DELAY_SECONDS", 0)

    result = run_task_execution(
        db_session,
        task_id,
        downloader=downloader,
        recognizer=recognizer,
        now=datetime(2026, 4, 25, 10, 0, 0),
    )

    task = db_session.get(task_model, task_id)
    item = db_session.exec(
        select(task_item_model).where(task_item_model.task_id == task_id)
    ).one()

    assert result.execution_status == task_status.VERIFY.value
    assert task.execution_status == task_status.VERIFY.value
    assert task.processed_count == 1
    assert item.llm_state == llm_state.SUCCESS.value
    assert item.llm_error is None
    assert item.status == item_status.VERIFY_PENDING.value
    assert recognizer.failed_item_ids == {item.id}
    assert recognizer.calls == [item.id]


def test_task_execution_auto_skips_matched_items_but_keeps_verify_page_visibility(
    app_client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    task_id = _create_task(app_client, execution_mode="manual")
    _install_task_upstream_mock(monkeypatch, records=_source_records()[:1])
    run_task_execution = _import_run_task_execution()
    task_model, task_item_model, task_item_data_model = _import_task_models()
    task_status, item_status, llm_state, confirm_state, remote_state, train_state = _import_task_status_enums()
    downloader = FakeTaskFileDownloader(_get_data_dir())
    recognizer = MatchingTaskItemRecognizer()

    result = run_task_execution(
        db_session,
        task_id,
        downloader=downloader,
        recognizer=recognizer,
        now=datetime(2026, 4, 25, 10, 0, 0),
    )

    task = db_session.get(task_model, task_id)
    item = db_session.exec(select(task_item_model).where(task_item_model.task_id == task_id)).one()
    rows = db_session.exec(select(task_item_data_model).where(task_item_data_model.task_item_id == item.id)).all()

    assert result.execution_status == task_status.FINISH.value
    assert task.execution_status == task_status.FINISH.value
    assert item.llm_state == llm_state.SUCCESS.value
    assert item.status == item_status.SKIPPED.value
    assert item.confirm_state == confirm_state.SKIPPED.value
    assert item.remote_state == remote_state.PENDING.value
    assert item.train_state == train_state.PENDING.value
    assert rows != []
    assert {row.status for row in rows} == {"默认"}


def test_auto_execute_stops_at_verify_without_submitting(
    app_client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    _install_task_upstream_mock(monkeypatch)
    downloader = FakeTaskFileDownloader(_get_data_dir())
    recognizer = FakeTaskItemRecognizer()
    _install_default_task_workers(monkeypatch, downloader=downloader, recognizer=recognizer)
    task_id = _create_task(app_client, execution_mode="auto", auto_execute=True)
    task_model, task_item_model, _ = _import_task_models()
    task_status, item_status, _, confirm_state, remote_state, train_state = _import_task_status_enums()

    items = db_session.exec(
        select(task_item_model).where(task_item_model.task_id == task_id)
    ).all()
    task = db_session.get(task_model, task_id)

    assert task.execution_status == task_status.VERIFY.value
    assert task.total_count == 2
    assert task.processed_count == 2
    assert all(item.confirm_state == confirm_state.PENDING.value for item in items)
    assert all(item.remote_state == remote_state.PENDING.value for item in items)
    assert all(item.train_state == train_state.PENDING.value for item in items)
    assert all(item.status == item_status.VERIFY_PENDING.value for item in items)
    assert not (_get_data_dir() / "training" / str(task_id)).exists()


def test_task_execution_deduplicates_without_overwriting_existing_items(
    app_client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    task_id = _create_task(app_client, execution_mode="auto")
    records = _source_records()
    _install_task_upstream_mock(monkeypatch, records)
    run_task_execution = _import_run_task_execution()
    task_model, task_item_model, _ = _import_task_models()
    downloader = FakeTaskFileDownloader(_get_data_dir())
    recognizer = FakeTaskItemRecognizer()

    first = run_task_execution(
        db_session,
        task_id,
        downloader=downloader,
        recognizer=recognizer,
        now=datetime(2026, 4, 25, 10, 0, 0),
    )
    second = run_task_execution(
        db_session,
        task_id,
        downloader=downloader,
        recognizer=recognizer,
        now=datetime(2026, 4, 25, 11, 0, 0),
    )

    task = db_session.get(task_model, task_id)
    items = db_session.exec(
        select(task_item_model).where(task_item_model.task_id == task_id)
    ).all()

    assert first.inserted_count == 2
    assert second.inserted_count == 0
    assert second.skipped_count == 2
    assert len(items) == 2
    assert task.execution_status == "核查"
    assert task.total_count == 2
    assert task.processed_count == 2
    assert task.skipped_count == 2


def test_task_execution_uses_file_id_instead_of_file_fid_for_deduplication(
    app_client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    task_id = _create_task(app_client, execution_mode="auto")
    records = _source_records()
    _install_task_upstream_mock(monkeypatch, records)
    run_task_execution = _import_run_task_execution()
    _, task_item_model, _ = _import_task_models()
    downloader = FakeTaskFileDownloader(_get_data_dir())
    recognizer = FakeTaskItemRecognizer()

    first = run_task_execution(
        db_session,
        task_id,
        downloader=downloader,
        recognizer=recognizer,
        now=datetime(2026, 4, 25, 10, 0, 0),
    )
    records[0]["fileFid"] = "fid-image-1-changed"
    records[1]["id"] = 103
    records[1]["fileFid"] = "fid-image-1"

    second = run_task_execution(
        db_session,
        task_id,
        downloader=downloader,
        recognizer=recognizer,
        now=datetime(2026, 4, 25, 11, 0, 0),
    )

    items = db_session.exec(
        select(task_item_model).where(task_item_model.task_id == task_id)
    ).all()

    assert first.inserted_count == 2
    assert second.inserted_count == 1
    assert second.skipped_count == 1
    assert {item.file_id for item in items} == {101, 102, 103}
    assert len([item for item in items if item.file_fid == "fid-image-1"]) == 2


def test_task_execution_rejects_non_integer_upstream_file_id(
    app_client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    """上游分页 id 必须是整数，才能用于远端提交。"""

    task_id = _create_task(app_client, execution_mode="auto")
    records = _source_records()
    records[0]["id"] = "file-001"
    _install_task_upstream_mock(monkeypatch, records)
    run_task_execution = _import_run_task_execution()

    with pytest.raises(Exception, match="上游分页数据 id 不是整数"):
        run_task_execution(
            db_session,
            task_id,
            downloader=FakeTaskFileDownloader(_get_data_dir()),
            recognizer=FakeTaskItemRecognizer(),
            now=datetime(2026, 4, 25, 10, 0, 0),
        )


def test_task_execution_skips_reentrant_running_task(
    app_client: TestClient,
    db_session: Session,
) -> None:
    task_id = _create_task(app_client, execution_mode="auto")
    run_task_execution = _import_run_task_execution()
    task_model, task_item_model, _ = _import_task_models()

    task = db_session.get(task_model, task_id)
    task.execution_status = "数据加载"
    db_session.add(task)
    db_session.commit()

    result = run_task_execution(
        db_session,
        task_id,
        now=datetime(2026, 4, 25, 10, 0, 0),
    )

    stored_task = db_session.get(task_model, task_id)
    items = db_session.exec(
        select(task_item_model).where(task_item_model.task_id == task_id)
    ).all()
    assert result.inserted_count == 0
    assert result.skipped_count == 1
    assert stored_task.execution_status == "数据加载"
    assert stored_task.skipped_count == 1
    assert items == []


def test_task_execution_records_stage_progress_timestamps(
    app_client: TestClient,
    db_session: Session,
) -> None:
    task_id = _create_task(app_client, execution_mode="manual")
    task_model, _, _ = _import_task_models()
    task_status, *_ = _import_task_status_enums()

    task_execution_module = importlib.import_module("aiSelfTest.services.task_execution")
    runner = task_execution_module.TaskExecutionRunner(
        db_session,
        task_id,
        now=datetime(2026, 4, 25, 10, 0, 0),
    )

    runner._set_task_stage(task_status.DOWN, reset_processed=True)
    task = db_session.get(task_model, task_id)
    assert task.stage_started_at is not None
    assert task.last_progress_at is None

    runner._increment_processed_count()
    task = db_session.get(task_model, task_id)
    assert task.processed_count == 1
    assert task.last_progress_at is not None
    assert task.last_progress_at >= task.stage_started_at

    runner._enter_verify_stage()
    task = db_session.get(task_model, task_id)
    assert task.execution_status == task_status.VERIFY.value
    assert task.stage_started_at is None
    assert task.last_progress_at is None


def _create_task(app_client: TestClient, *, execution_mode: str, auto_execute: bool = False) -> int:
    client_id = _unwrap_success(
        app_client.post(
            "/api/clients/create",
            json={
                "name": "任务项目",
                "apiUrl": "https://example.com",
                "account": "task-admin",
                "password": "secret-123",
                "status": "启用",
            },
        ).json()
    )["id"]
    config_id = _unwrap_success(
        app_client.post(
            "/api/configs/create",
            json={
                "name": "任务提示词",
                "remark": "任务测试用提示词",
                "text": "请返回识别结果。",
                "format": 0,
            },
        ).json()
    )["id"]
    task_id = _unwrap_success(
        app_client.post(
            "/api/tasks/create",
            json={
                "name": "执行主干任务",
                "client_id": client_id,
                "config_id": config_id,
                "interval_hours": 1,
                "execution_mode": execution_mode,
                "auto_execute": auto_execute,
                "filters": {
                    "classify_list": [1, 2],
                    "keyword": "",
                    "sp_name": "",
                    "start_at": "2026-04-25 00:00:00",
                    "end_at": "2026-04-25 23:59:59",
                    "media_types": ["image", "video"],
                    "upload_types": [],
                    "identify_source": [],
                },
            },
        ).json()
    )["id"]
    return task_id


def _get_data_dir() -> Path:
    from aiSelfTest.config import get_settings

    return get_settings().data_dir


def _source_records() -> list[dict[str, Any]]:
    return [
        {
            "id": 101,
            "name": "image-1.jpg",
            "deName": "camera-1",
            "fileNum": "IMG-001",
            "fileExtension": "jpg",
            "fileUrl": "image-1.jpg",
            "fileFid": "fid-image-1",
            "spNameList": "白鹭",
            "classify": 1,
            "fileBmp": 1,
            "module": "camera",
            "idType": 0,
        },
        {
            "id": 102,
            "name": "video-1.mp4",
            "deName": "camera-2",
            "fileNum": "VID-001",
            "fileExtension": "mp4",
            "fileUrl": "video-1.mp4",
            "fileFid": "fid-video-1",
            "spNameList": "苍鹭",
            "classify": 2,
            "fileBmp": 2,
            "module": "camera",
            "idType": 0,
        },
    ]


def _detail_records(file_id: str) -> list[dict[str, Any]]:
    rows_by_file_id = {
        "101": [
            {
                "name": "白鹭",
                "score": 0.91,
                "trackIds": "1",
                "spAmount": 1,
                "minx": 1,
                "miny": 2,
                "maxx": 10,
                "maxy": 12,
            }
        ],
        "102": [
            {
                "name": "苍鹭",
                "score": 0.88,
                "trackIds": "track-1",
                "spAmount": 1,
            }
        ],
        "103": [
            {
                "name": "苍鹭",
                "score": 0.77,
                "trackIds": "track-2",
                "spAmount": 1,
            }
        ],
    }
    return rows_by_file_id[file_id]


def _install_task_upstream_mock(monkeypatch, records: list[dict[str, Any]] | None = None) -> list[str]:
    from aiSelfTest.services import task_execution

    page_records = records if records is not None else _source_records()
    calls: list[str] = []

    def fake_post(url: str, **kwargs: Any) -> FakeResponse:
        calls.append(url)
        if url.endswith("/auth/login"):
            return FakeResponse(
                200,
                {
                    "accessToken": "task-access-token",
                    "refreshToken": "task-refresh-token",
                    "expiresIn": 3600,
                    "tenantCode": "tenant-001",
                },
            )
        if url.endswith("/openApi/icFile/findFilePage"):
            assert kwargs["headers"] == {"Authorization": "task-access-token"}
            return FakeResponse(
                200,
                {
                    "results": page_records,
                    "total": len(page_records),
                    "size": 100,
                    "current": 1,
                    "totalCurrent": 1,
                },
            )
        raise AssertionError(f"未预期的 POST 请求: {url}")

    def fake_get(url: str, **kwargs: Any) -> FakeResponse:
        calls.append(url)
        if url.endswith("/sys/sysTenantConfig/getByCode/tenant-001"):
            assert kwargs["headers"] == {"Authorization": "task-access-token"}
            return FakeResponse(200, {"tenantCode": "tenant-001", "name": "树蛙保护区"})
        if url.endswith("/openApi/icFile/getResultByFileId1"):
            file_id = str(kwargs["params"]["fileId"])
            payload: dict[str, Any] = {"recordData": _detail_records(file_id)}
            if file_id == "102":
                payload["resultFileData"] = "video-result.json"
            return FakeResponse(200, payload)
        raise AssertionError(f"未预期的 GET 请求: {url}")

    monkeypatch.setattr(task_execution.requests, "post", fake_post)
    monkeypatch.setattr(task_execution.requests, "get", fake_get)
    return calls


def _install_default_task_workers(
    monkeypatch,
    *,
    downloader: FakeTaskFileDownloader,
    recognizer: FakeTaskItemRecognizer,
) -> None:
    from aiSelfTest.services import task_execution

    monkeypatch.setattr(task_execution, "RequestsTaskFileDownloader", lambda: downloader)
    monkeypatch.setattr(task_execution, "MultimodalTaskItemRecognizer", lambda: recognizer)


def _unwrap_success(response_json: dict[str, Any]) -> Any:
    assert response_json["code"] == 0
    assert response_json["message"] == "success"
    return response_json["data"]


def _import_run_task_execution():
    from aiSelfTest.services.task_execution import run_task_execution

    return run_task_execution


def _import_task_models():
    from aiSelfTest.models.task import Task, TaskItem, TaskItemData

    return Task, TaskItem, TaskItemData


def _import_task_status_enums():
    from aiSelfTest.models.task import (
        TaskExecutionStatus,
        TaskItemConfirmState,
        TaskItemLlmState,
        TaskItemRemoteState,
        TaskItemStatus,
        TaskItemTrainState,
    )

    return (
        TaskExecutionStatus,
        TaskItemStatus,
        TaskItemLlmState,
        TaskItemConfirmState,
        TaskItemRemoteState,
        TaskItemTrainState,
    )
