"""TaskItem 批量重新识别测试。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from aiSelfTest.models.task import (
    TaskItemConfirmState,
    TaskItemDataStatus,
    TaskItemLlmState,
    TaskItemRecognitionBatchStatus,
    TaskItemRemoteState,
    TaskItemStatus,
)


def _unwrap_success(response_json: dict[str, Any]) -> Any:
    assert response_json["code"] == 0
    assert response_json["message"] == "success"
    return response_json["data"]


@pytest.fixture(autouse=True)
def fake_re_recognition_enqueue(app_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """拦截批量重新识别 Celery 投递。"""

    calls: list[int] = []

    def fake_delay(batch_id: int) -> None:
        calls.append(batch_id)

    from aiSelfTest import worker

    monkeypatch.setattr(worker.execute_task_item_re_recognition_batch, "delay", fake_delay)
    return calls


def test_create_selected_re_recognition_batch_returns_queued_progress(
    app_client: TestClient,
    db_session: Session,
    fake_re_recognition_enqueue: list[int],
) -> None:
    """selected 范围应创建批量记录并异步投递。"""

    task_id = _create_task(app_client)
    first, _ = _seed_task_item(db_session, task_id, file_id=1001, file_fid="fid-1001")
    second, _ = _seed_task_item(db_session, task_id, file_id=1002, file_fid="fid-1002")

    response = app_client.post(
        "/api/task-items/action-re-recognize-batch",
        json={"scope": "selected", "task_item_ids": [first.id, second.id]},
    )

    assert response.status_code == 200
    data = _unwrap_success(response.json())
    assert data["status"] == TaskItemRecognitionBatchStatus.QUEUED.value
    assert data["total_count"] == 2
    assert data["success_count"] == 0
    assert data["failed_count"] == 0
    assert data["skipped_count"] == 0
    assert len(fake_re_recognition_enqueue) == 1
    assert fake_re_recognition_enqueue[0] == data["batch_id"]

    batch_model = _import_batch_model()
    batch = db_session.get(batch_model, data["batch_id"])
    assert batch is not None
    assert batch.task_item_ids == f"{first.id},{second.id}"


def test_create_failed_re_recognition_batch_selects_failed_items(
    app_client: TestClient,
    db_session: Session,
) -> None:
    """failed 范围只选择识别失败的任务项。"""

    task_id = _create_task(app_client)
    failed_item, _ = _seed_task_item(
        db_session,
        task_id,
        file_id=1101,
        file_fid="fid-1101",
        llm_state=TaskItemLlmState.FAIL.value,
        status=TaskItemStatus.FAILED.value,
    )
    _seed_task_item(db_session, task_id, file_id=1102, file_fid="fid-1102")

    response = app_client.post(
        "/api/task-items/action-re-recognize-batch",
        json={"scope": "failed", "task_id": task_id},
    )

    assert response.status_code == 200
    data = _unwrap_success(response.json())
    assert data["total_count"] == 1

    batch_model = _import_batch_model()
    batch = db_session.get(batch_model, data["batch_id"])
    assert batch.task_item_ids == str(failed_item.id)


def test_selected_re_recognition_requires_task_item_ids(app_client: TestClient) -> None:
    """selected 范围必须传入至少一个任务项 ID。"""

    response = app_client.post(
        "/api/task-items/action-re-recognize-batch",
        json={"scope": "selected", "task_item_ids": []},
    )

    assert response.status_code == 400
    assert response.json()["code"] == 1001


def test_re_recognition_batch_detail_returns_progress(
    app_client: TestClient,
    db_session: Session,
) -> None:
    """批量进度详情接口应返回当前计数。"""

    task_id = _create_task(app_client)
    item, _ = _seed_task_item(db_session, task_id, file_id=1201, file_fid="fid-1201")
    batch_model = _import_batch_model()
    batch = batch_model(
        task_id=task_id,
        scope="selected",
        task_item_ids=str(item.id),
        status=TaskItemRecognitionBatchStatus.RUNNING.value,
        total_count=1,
        success_count=0,
        failed_count=0,
        skipped_count=0,
        current_task_item_id=item.id,
    )
    db_session.add(batch)
    db_session.commit()
    db_session.refresh(batch)

    response = app_client.get(f"/api/task-items/re-recognize-batch-detail/{batch.id}")

    assert response.status_code == 200
    data = _unwrap_success(response.json())
    assert data["batch_id"] == batch.id
    assert data["status"] == TaskItemRecognitionBatchStatus.RUNNING.value
    assert data["current_task_item_id"] == item.id


def test_worker_skips_submitted_and_running_items(
    app_client: TestClient,
    db_session: Session,
) -> None:
    """已提交和识别中的任务项应跳过，不进入识别。"""

    task_id = _create_task(app_client)
    submitted, _ = _seed_task_item(
        db_session,
        task_id,
        file_id=1301,
        file_fid="fid-1301",
        remote_state=TaskItemRemoteState.SUCCESS.value,
    )
    running, _ = _seed_task_item(
        db_session,
        task_id,
        file_id=1302,
        file_fid="fid-1302",
        llm_state=TaskItemLlmState.RUNNING.value,
        status=TaskItemStatus.LLM_RUNNING.value,
    )
    batch = _seed_batch(db_session, task_id, [submitted.id, running.id])

    from aiSelfTest.worker import execute_task_item_re_recognition_batch

    execute_task_item_re_recognition_batch.run(batch.id)

    db_session.refresh(batch)
    assert batch.status == TaskItemRecognitionBatchStatus.SUCCESS.value
    assert batch.success_count == 0
    assert batch.failed_count == 0
    assert batch.skipped_count == 2


def test_worker_cleans_old_added_rows_before_re_recognition(
    app_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """重新识别前应删除旧新增行并重置原始行。"""

    task_id = _create_task(app_client)
    image_path = tmp_path / "image.jpg"
    image_path.write_bytes(b"fake-image")
    task_item, source_row = _seed_task_item(
        db_session,
        task_id,
        file_id=1401,
        file_fid="fid-1401",
        file_bmp=1,
        file_extension="jpg",
        file_path=image_path.as_posix(),
        status=TaskItemStatus.CONFIRMED.value,
        confirm_state=TaskItemConfirmState.CONFIRMED.value,
    )
    data_model = _import_task_item_data_model()
    added_row = data_model(
        task_item_id=task_item.id,
        name="",
        score=0,
        track_ids="",
        sp_amount=1,
        minx=10,
        miny=10,
        maxx=20,
        maxy=20,
        llm_name="旧新增",
        status=TaskItemDataStatus.ADD.value,
    )
    db_session.add(added_row)
    db_session.commit()
    batch = _seed_batch(db_session, task_id, [task_item.id])

    from aiSelfTest.services import task_execution
    from aiSelfTest.services.task_execution import TaskItemRecognitionResult
    from aiSelfTest.services.task_steps.llm_result import BoundingBox, LlmDetectedObject, LlmDetectionResult

    def fake_recognize(self, session: Session, task, task_item, data_rows):
        assert [row.id for row in data_rows] == [source_row.id]
        detected = LlmDetectedObject(name="新名称", bbox=BoundingBox(0, 0, 100, 100))
        return TaskItemRecognitionResult(image_result=LlmDetectionResult(width=100, height=100, data=[detected]))

    monkeypatch.setattr(task_execution.MultimodalTaskItemRecognizer, "recognize", fake_recognize)

    from aiSelfTest.worker import execute_task_item_re_recognition_batch

    execute_task_item_re_recognition_batch.run(batch.id)

    db_session.refresh(batch)
    db_session.refresh(task_item)
    db_session.refresh(source_row)
    remaining_rows = db_session.exec(
        select(data_model).where(data_model.task_item_id == task_item.id).order_by(data_model.id)
    ).all()
    assert batch.status == TaskItemRecognitionBatchStatus.SUCCESS.value
    assert batch.success_count == 1
    assert batch.failed_count == 0
    assert len(remaining_rows) == 1
    assert remaining_rows[0].id == source_row.id
    assert source_row.llm_name == "新名称"
    assert source_row.status == TaskItemDataStatus.UPDATE.value
    assert task_item.llm_state == TaskItemLlmState.SUCCESS.value
    assert task_item.confirm_state == TaskItemConfirmState.PENDING.value


def test_worker_continues_after_single_item_failure(
    app_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """单个任务项失败时批量任务继续处理后续项。"""

    task_id = _create_task(app_client)
    missing, _ = _seed_task_item(
        db_session,
        task_id,
        file_id=1501,
        file_fid="fid-1501",
        file_bmp=1,
        file_path=(tmp_path / "missing.jpg").as_posix(),
    )
    image_path = tmp_path / "image.jpg"
    image_path.write_bytes(b"fake-image")
    success, _ = _seed_task_item(
        db_session,
        task_id,
        file_id=1502,
        file_fid="fid-1502",
        file_bmp=1,
        file_path=image_path.as_posix(),
    )
    batch = _seed_batch(db_session, task_id, [missing.id, success.id])

    from aiSelfTest.services import task_execution
    from aiSelfTest.services.task_execution import TaskItemRecognitionResult
    from aiSelfTest.services.task_steps.llm_result import BoundingBox, LlmDetectedObject, LlmDetectionResult

    def fake_recognize(self, session: Session, task, task_item, data_rows):
        detected = LlmDetectedObject(name="白鹭", bbox=BoundingBox(0, 0, 100, 100))
        return TaskItemRecognitionResult(image_result=LlmDetectionResult(width=100, height=100, data=[detected]))

    monkeypatch.setattr(task_execution.MultimodalTaskItemRecognizer, "recognize", fake_recognize)

    from aiSelfTest.worker import execute_task_item_re_recognition_batch

    execute_task_item_re_recognition_batch.run(batch.id)

    db_session.refresh(batch)
    db_session.refresh(missing)
    db_session.refresh(success)
    assert batch.status == TaskItemRecognitionBatchStatus.PARTIAL_FAILED.value
    assert batch.success_count == 1
    assert batch.failed_count == 1
    assert batch.skipped_count == 0
    assert missing.llm_state == TaskItemLlmState.FAIL.value
    assert success.llm_state == TaskItemLlmState.SUCCESS.value


def _create_task(app_client: TestClient) -> int:
    client_id = _unwrap_success(
        app_client.post(
            "/api/clients/create",
            json={
                "name": "批量重识别项目",
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
                "name": "批量重识别提示词",
                "remark": "测试用提示词",
                "text": "请返回识别结果。",
                "format": 0,
            },
        ).json()
    )["id"]
    return _unwrap_success(
        app_client.post(
            "/api/tasks/create",
            json={
                "name": "批量重识别任务",
                "client_id": client_id,
                "config_id": config_id,
                "interval_hours": 1,
                "execution_mode": "manual",
                "auto_execute": False,
                "filters": {
                    "classify_list": [1],
                    "keyword": "",
                    "sp_name": "",
                    "start_at": "",
                    "end_at": "",
                    "media_types": ["image", "video"],
                    "upload_types": [],
                    "identify_source": [],
                    "module": "camera",
                },
            },
        ).json()
    )["id"]


def _seed_task_item(db_session: Session, task_id: int, **overrides: Any) -> tuple[Any, Any]:
    task_item_model, task_item_data_model = _import_task_item_models()
    payload = {
        "task_id": task_id,
        "name": "image-1.jpg",
        "device_name": "device-1",
        "file_num": "file-001",
        "file_extension": "jpg",
        "file_url": "https://example.com/image.jpg",
        "file_id": 101,
        "file_fid": "fid-001",
        "sp_name_list": "白鹭",
        "classify": 1,
        "file_bmp": 1,
        "result_file_data": "",
        "id_type": 0,
        "status": TaskItemStatus.VERIFY_PENDING.value,
        "down_state": True,
        "file_path": __file__,
        "llm_state": TaskItemLlmState.SUCCESS.value,
        "confirm_state": TaskItemConfirmState.PENDING.value,
        "remote_state": TaskItemRemoteState.PENDING.value,
    }
    payload.update(overrides)
    task_item = task_item_model(**payload)
    db_session.add(task_item)
    db_session.commit()
    db_session.refresh(task_item)

    task_item_data = task_item_data_model(
        task_item_id=task_item.id,
        name="白鹭",
        score=0.91,
        track_ids="1001",
        sp_amount=1,
        minx=0,
        miny=0,
        maxx=100,
        maxy=100,
        llm_name="白鹭",
        status=TaskItemDataStatus.DEFAULT.value,
    )
    db_session.add(task_item_data)
    db_session.commit()
    db_session.refresh(task_item_data)
    return task_item, task_item_data


def _seed_batch(db_session: Session, task_id: int, task_item_ids: list[int]) -> Any:
    batch_model = _import_batch_model()
    batch = batch_model(
        task_id=task_id,
        scope="selected",
        task_item_ids=",".join(str(item_id) for item_id in task_item_ids),
        status=TaskItemRecognitionBatchStatus.QUEUED.value,
        total_count=len(task_item_ids),
        success_count=0,
        failed_count=0,
        skipped_count=0,
    )
    db_session.add(batch)
    db_session.commit()
    db_session.refresh(batch)
    return batch


def _import_task_item_models():
    from aiSelfTest.models.task import TaskItem, TaskItemData

    return TaskItem, TaskItemData


def _import_task_item_data_model():
    from aiSelfTest.models.task import TaskItemData

    return TaskItemData


def _import_batch_model():
    from aiSelfTest.models.task import TaskItemRecognitionBatch

    return TaskItemRecognitionBatch
