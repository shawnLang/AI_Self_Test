"""任务模型与迁移契约测试。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select


def _unwrap_success(response_json: dict):
    assert response_json["code"] == 0
    assert response_json["message"] == "success"
    return response_json["data"]


def _create_task_fixture(app_client: TestClient) -> int:
    client_id = _unwrap_success(app_client.post("/api/clients/create", json={
        "name": "任务项目",
        "apiUrl": "https://example.com",
        "account": "task-admin",
        "password": "secret-123",
        "status": "启用",
    }).json())["id"]
    config_id = _unwrap_success(app_client.post("/api/configs/create", json={
        "name": "任务提示词",
        "remark": "任务测试用提示词",
        "text": "请返回识别结果。",
        "format": 0,
    }).json())["id"]
    task_id = _unwrap_success(app_client.post("/api/tasks/create", json={
        "name": "迁移任务-001",
        "client_id": client_id,
        "config_id": config_id,
        "interval_hours": 1,
        "execution_mode": "manual",
        "auto_confirm": False,
        "filters": {
          "classify_list": [1],
          "keyword": "",
          "sp_name": "",
          "start_at": "",
          "end_at": "",
          "media_types": ["image"],
          "upload_types": [],
          "identify_source": []
        }
    }).json())["id"]
    return task_id


def test_task_create_initializes_runtime_cursor_fields(
    app_client: TestClient,
    db_session: Session,
) -> None:
    task_id = _create_task_fixture(app_client)
    task_model, _, _ = import_task_models()

    task = db_session.exec(select(task_model).where(task_model.id == task_id)).one()

    assert task.last_pull_end_at is None
    assert task.last_run_started_at is None
    assert task.skipped_count == 0


def test_task_item_same_task_same_file_id_must_be_unique(
    app_client: TestClient,
    db_session: Session,
) -> None:
    task_id = _create_task_fixture(app_client)
    _, task_item_model, _ = import_task_models()

    first = task_item_model(
        task_id=task_id,
        name="image-1.jpg",
        device_name="device-1",
        file_num="file-001",
        file_extension="jpg",
        file_url="https://example.com/file.jpg",
        file_id="file-001",
        file_fid="fid-001",
        sp_name_list="白鹭",
        classify=1,
        file_bmp=1,
        result_file_data="",
        id_type=0,
        status="创建",
    )
    second = task_item_model(
        task_id=task_id,
        name="image-2.jpg",
        device_name="device-2",
        file_num="file-002",
        file_extension="jpg",
        file_url="https://example.com/file-2.jpg",
        file_id="file-001",
        file_fid="fid-002",
        sp_name_list="苍鹭",
        classify=1,
        file_bmp=1,
        result_file_data="",
        id_type=0,
        status="创建",
    )

    db_session.add(first)
    db_session.commit()

    db_session.add(second)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def import_task_models():
    from aiSelfTest.models.task import Task, TaskItem, TaskItemData

    return Task, TaskItem, TaskItemData
