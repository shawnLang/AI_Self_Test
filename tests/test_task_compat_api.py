"""旧 task 页面兼容接口测试。"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sqlmodel import Session


def _unwrap_success(response_json: dict[str, Any]) -> Any:
    assert response_json["code"] == 0
    assert response_json["message"] == "success"
    return response_json["data"]


def _seed_task_fixture(app_client: TestClient, db_session: Session) -> tuple[int, int]:
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
        "name": "兼容任务-001",
        "client_id": client_id,
        "config_id": config_id,
        "interval_hours": 1,
        "execution_mode": "manual",
        "auto_confirm": False,
        "filters": {
            "classify_list": [1, 2],
            "keyword": "白鹭",
            "sp_name": "白鹭",
            "start_at": "2026-04-20",
            "end_at": "2026-04-25",
            "media_types": ["image"],
            "upload_types": [],
            "identify_source": [],
        },
    }).json())["id"]

    _, task_item_model, _ = import_task_models()
    task_item = task_item_model(
        task_id=task_id,
        name="image-1.jpg",
        device_name="device-1",
        file_num="file-001",
        file_extension="jpg",
        file_url="https://example.com/image.jpg",
        file_fid="fid-001",
        sp_name_list="白鹭",
        classify=1,
        file_bmp=1,
        result_file_data="",
        id_type=0,
        status="创建",
        down_state=True,
    )
    db_session.add(task_item)
    db_session.commit()
    db_session.refresh(task_item)
    return task_id, task_item.id or 0


def test_legacy_task_detail_route_returns_form_compatible_filters(
    app_client: TestClient,
    db_session: Session,
) -> None:
    task_id, _ = _seed_task_fixture(app_client, db_session)

    response = app_client.get(f"/api/tasks/{task_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == task_id
    assert data["filters"]["classifyList"] == [1, 2]
    assert data["filters"]["fileBmp"] == "image"


def test_legacy_query_data_route_returns_results(
    app_client: TestClient,
    db_session: Session,
) -> None:
    task_id, task_item_id = _seed_task_fixture(app_client, db_session)

    response = app_client.post(
        f"/api/tasks/{task_id}/query-data",
        json={"current": 1, "size": 20},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["results"][0]["id"] == task_item_id
    assert data["results"][0]["mediaType"] == "image"
    assert data["results"][0]["spNameList"] == "白鹭"


def test_legacy_execute_route_triggers_task_run(
    app_client: TestClient,
    db_session: Session,
) -> None:
    task_id, _ = _seed_task_fixture(app_client, db_session)
    task_model, _, _ = import_task_models()

    response = app_client.post(
        f"/api/tasks/{task_id}/execute",
        json={"fileIds": [], "selectedItems": []},
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    task = db_session.get(task_model, task_id)
    assert task is not None
    assert task.started_at is not None


def import_task_models():
    from aiSelfTest.models.task import Task, TaskItem, TaskItemData

    return Task, TaskItem, TaskItemData
