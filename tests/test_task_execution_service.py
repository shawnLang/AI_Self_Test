"""Task 执行主干服务测试。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlmodel import Session, select


class FakeTaskExecutionSource:
    """测试用上游数据源。"""

    def __init__(self) -> None:
        self.records = [
            {
                "name": "image-1.jpg",
                "deviceName": "camera-1",
                "fileNum": "IMG-001",
                "fileExtension": "jpg",
                "fileUrl": "https://example.com/image-1.jpg",
                "fileFid": "fid-image-1",
                "spNameList": "白鹭",
                "classify": 1,
                "fileBmp": 1,
                "idType": 0,
                "recordData": [
                    {
                        "name": "白鹭",
                        "score": 0.91,
                        "trackIds": "1",
                        "spAmount": 1,
                        "bbox": [1, 2, 10, 12],
                    }
                ],
            },
            {
                "name": "video-1.mp4",
                "deviceName": "camera-2",
                "fileNum": "VID-001",
                "fileExtension": "mp4",
                "fileUrl": "https://example.com/video-1.mp4",
                "fileFid": "fid-video-1",
                "spNameList": "苍鹭",
                "classify": 2,
                "fileBmp": 2,
                "resultFileData": "https://example.com/result.json",
                "idType": 0,
                "recordData": [
                    {
                        "name": "苍鹭",
                        "score": 0.88,
                        "trackIds": "track-1",
                        "spAmount": 1,
                    }
                ],
            },
        ]

    def fetch_task_items(self, **_: Any) -> list[dict[str, Any]]:
        return self.records

    def fetch_task_item_detail(self, **_: Any) -> list[dict[str, Any]]:
        return []


class FakeTaskFileDownloader:
    """测试用文件下载器，写入可断言的本地文件。"""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.calls: list[str] = []

    def download(self, **kwargs: Any) -> Any:
        """模拟原始文件与视频结果文件下载。"""

        task_item = kwargs["task_item"]
        source_record = kwargs["source_record"]
        from aiSelfTest.services.task_execution import TaskDownloadResult

        item_dir = self.root / "task_files" / str(task_item.task_id) / str(task_item.id)
        item_dir.mkdir(parents=True, exist_ok=True)
        extension = task_item.file_extension or "bin"
        file_path = item_dir / f"original.{extension}"
        file_path.write_bytes(f"downloaded:{source_record.file_fid}".encode())
        result_file_path = None
        if source_record.result_file_data:
            result_file_path = item_dir / "result.json"
            result_file_path.write_text('{"tracks":[]}', encoding="utf-8")
        self.calls.append(source_record.file_fid)
        return TaskDownloadResult(
            file_path=file_path.as_posix(),
            result_file_path=result_file_path.as_posix() if result_file_path else None,
        )


class FakeTaskItemRecognizer:
    """测试用大模型识别器。"""

    def __init__(self) -> None:
        self.calls: list[int] = []

    def recognize(self, **kwargs: Any) -> dict[int, str]:
        """返回与原始名称不同的识别结果，避免复制原始名称的占位逻辑。"""

        task_item = kwargs["task_item"]
        data_rows = kwargs["data_rows"]
        self.calls.append(task_item.id)
        return {row.id: f"AI-{row.name}" for row in data_rows}


def test_task_execution_ingests_records_and_advances_shared_trunk(
    app_client: TestClient,
    db_session: Session,
) -> None:
    task_id = _create_task(app_client, execution_mode="auto")
    run_task_execution = _import_run_task_execution()
    task_model, task_item_model, task_item_data_model = _import_task_models()
    downloader = FakeTaskFileDownloader(_get_data_dir())
    recognizer = FakeTaskItemRecognizer()

    result = run_task_execution(
        db_session,
        task_id,
        source=FakeTaskExecutionSource(),
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
    assert result.execution_status == "结束"
    assert task.execution_status == "结束"
    assert task.total_count == 2
    assert task.processed_count == 2
    assert task.last_run_started_at is not None
    assert task.last_pull_end_at is not None
    assert {item.file_fid for item in items} == {"fid-image-1", "fid-video-1"}
    assert {item.file_bmp for item in items} == {1, 2}
    assert all(item.down_state is True for item in items)
    assert all(item.llm_state == "success" for item in items)
    assert all(item.confirm_state == "pending" for item in items)
    assert {row.llm_name for row in rows} == {"AI-白鹭", "AI-苍鹭"}
    assert {row.status for row in rows} == {"修改"}
    assert set(downloader.calls) == {"fid-image-1", "fid-video-1"}
    assert len(recognizer.calls) == 2
    assert all(Path(item.file_path).exists() for item in items)
    video_item = next(item for item in items if item.file_bmp == 2)
    assert (Path(video_item.file_path).parent / "result.json").exists()


def test_manual_task_execution_downloads_without_llm_recognition(
    app_client: TestClient,
    db_session: Session,
) -> None:
    task_id = _create_task(app_client, execution_mode="manual")
    run_task_execution = _import_run_task_execution()
    _, task_item_model, task_item_data_model = _import_task_models()
    downloader = FakeTaskFileDownloader(_get_data_dir())
    recognizer = FakeTaskItemRecognizer()

    result = run_task_execution(
        db_session,
        task_id,
        source=FakeTaskExecutionSource(),
        downloader=downloader,
        recognizer=recognizer,
        now=datetime(2026, 4, 25, 10, 0, 0),
    )

    items = db_session.exec(
        select(task_item_model).where(task_item_model.task_id == task_id)
    ).all()
    rows = db_session.exec(select(task_item_data_model)).all()

    assert result.inserted_count == 2
    assert all(item.down_state is True for item in items)
    assert all(item.llm_state == "pending" for item in items)
    assert all(item.status == "downloaded" for item in items)
    assert {row.llm_name for row in rows} == {None}
    assert set(downloader.calls) == {"fid-image-1", "fid-video-1"}
    assert recognizer.calls == []


def test_auto_confirm_submits_and_saves_training_payload(
    app_client: TestClient,
    db_session: Session,
) -> None:
    task_id = _create_task(app_client, execution_mode="auto", auto_confirm=True)
    run_task_execution = _import_run_task_execution()
    _, task_item_model, _ = _import_task_models()

    result = run_task_execution(
        db_session,
        task_id,
        source=FakeTaskExecutionSource(),
        downloader=FakeTaskFileDownloader(_get_data_dir()),
        recognizer=FakeTaskItemRecognizer(),
        now=datetime(2026, 4, 25, 10, 0, 0),
    )

    items = db_session.exec(
        select(task_item_model).where(task_item_model.task_id == task_id)
    ).all()

    assert result.inserted_count == 2
    assert all(item.remote_state == "success" for item in items)
    assert all(item.train_state == "saved" for item in items)
    assert all(item.status == "done" for item in items)
    assert all(
        (_get_data_dir() / "training" / str(task_id) / str(item.id) / "annotation.json").exists()
        for item in items
    )


def test_task_execution_deduplicates_without_overwriting_existing_items(
    app_client: TestClient,
    db_session: Session,
) -> None:
    task_id = _create_task(app_client, execution_mode="auto")
    run_task_execution = _import_run_task_execution()
    task_model, task_item_model, _ = _import_task_models()
    source = FakeTaskExecutionSource()
    downloader = FakeTaskFileDownloader(_get_data_dir())
    recognizer = FakeTaskItemRecognizer()

    first = run_task_execution(
        db_session,
        task_id,
        source=source,
        downloader=downloader,
        recognizer=recognizer,
        now=datetime(2026, 4, 25, 10, 0, 0),
    )
    second = run_task_execution(
        db_session,
        task_id,
        source=source,
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
    assert task.total_count == 2
    assert task.processed_count == 2
    assert task.skipped_count == 2


def test_task_execution_skips_reentrant_running_task(
    app_client: TestClient,
    db_session: Session,
) -> None:
    task_id = _create_task(app_client, execution_mode="auto")
    run_task_execution = _import_run_task_execution()
    task_model, task_item_model, _ = _import_task_models()

    task = db_session.get(task_model, task_id)
    task.execution_status = "下载"
    db_session.add(task)
    db_session.commit()

    result = run_task_execution(
        db_session,
        task_id,
        source=FakeTaskExecutionSource(),
        now=datetime(2026, 4, 25, 10, 0, 0),
    )

    stored_task = db_session.get(task_model, task_id)
    items = db_session.exec(
        select(task_item_model).where(task_item_model.task_id == task_id)
    ).all()
    assert result.inserted_count == 0
    assert result.skipped_count == 1
    assert stored_task.execution_status == "下载"
    assert stored_task.skipped_count == 1
    assert items == []


def _create_task(app_client: TestClient, *, execution_mode: str, auto_confirm: bool = False) -> int:
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
                "auto_confirm": auto_confirm,
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
