"""任务接口契约测试。"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sqlmodel import Session, select


def _unwrap_success(response_json: dict[str, Any]) -> Any:
    assert response_json["code"] == 0
    assert response_json["message"] == "success"
    return response_json["data"]


def _create_client_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "name": "任务项目",
        "apiUrl": "https://example.com",
        "account": "task-admin",
        "password": "secret-123",
        "status": "启用",
    }
    payload.update(overrides)
    return payload


def _create_config_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "name": "任务提示词",
        "remark": "任务测试用提示词",
        "text": "请返回识别结果。",
        "format": 0,
    }
    payload.update(overrides)
    return payload


def _create_task_payload(client_id: int, config_id: int, **overrides: Any) -> dict[str, Any]:
    payload = {
        "name": "鸟类任务-001",
        "client_id": client_id,
        "config_id": config_id,
        "interval_hours": 1,
        "execution_mode": "manual",
        "auto_confirm": False,
        "filters": {
            "classify_list": [1, 2],
            "keyword": "鸟类",
            "sp_name": "白鹭",
            "start_at": "2026-04-20",
            "end_at": "2026-04-25",
            "media_types": ["image", "video"],
            "upload_types": [],
            "identify_source": [],
        },
    }
    payload.update(overrides)
    return payload


def _create_client_and_config(app_client: TestClient) -> tuple[int, int]:
    client_response = app_client.post("/api/clients/create", json=_create_client_payload())
    config_response = app_client.post("/api/configs/create", json=_create_config_payload())

    assert client_response.status_code == 201
    assert config_response.status_code == 201

    client_id = _unwrap_success(client_response.json())["id"]
    config_id = _unwrap_success(config_response.json())["id"]
    return client_id, config_id


def test_task_list_returns_empty_items(app_client: TestClient) -> None:
    response = app_client.get("/api/tasks/list")

    assert response.status_code == 200
    data = _unwrap_success(response.json())
    assert data["items"] == []


def test_create_task_and_get_detail(app_client: TestClient) -> None:
    client_id, config_id = _create_client_and_config(app_client)

    create_response = app_client.post(
        "/api/tasks/create",
        json=_create_task_payload(client_id, config_id),
    )

    assert create_response.status_code == 201
    created = _unwrap_success(create_response.json())
    assert created["name"] == "鸟类任务-001"
    assert created["client_id"] == client_id
    assert created["config_id"] == config_id
    assert created["interval_hours"] == 1
    assert created["execution_mode"] == "manual"
    assert created["auto_confirm"] is False

    detail_response = app_client.get(f"/api/tasks/detail/{created['id']}")

    assert detail_response.status_code == 200
    detail = _unwrap_success(detail_response.json())
    assert detail["id"] == created["id"]
    assert detail["filters"]["classify_list"] == [1, 2]
    assert detail["filters"]["media_types"] == ["image", "video"]


def test_create_task_requires_config_id(app_client: TestClient) -> None:
    client_id, config_id = _create_client_and_config(app_client)
    payload = _create_task_payload(client_id, config_id)
    payload.pop("config_id")

    response = app_client.post("/api/tasks/create", json=payload)

    assert response.status_code == 400
    body = response.json()
    assert body["code"] == 1001


def test_create_task_validates_interval_hours(app_client: TestClient) -> None:
    client_id, config_id = _create_client_and_config(app_client)

    response = app_client.post(
        "/api/tasks/create",
        json=_create_task_payload(client_id, config_id, interval_hours=0),
    )

    assert response.status_code == 400
    body = response.json()
    assert body["code"] == 1001


def test_create_task_rejects_non_canonical_execution_mode(app_client: TestClient) -> None:
    client_id, config_id = _create_client_and_config(app_client)

    response = app_client.post(
        "/api/tasks/create",
        json=_create_task_payload(client_id, config_id, execution_mode="自动"),
    )

    assert response.status_code == 400
    body = response.json()
    assert body["code"] == 1001


def test_update_task_persists_schedule_and_filters(app_client: TestClient) -> None:
    client_id, config_id = _create_client_and_config(app_client)
    create_response = app_client.post(
        "/api/tasks/create",
        json=_create_task_payload(client_id, config_id),
    )
    task_id = _unwrap_success(create_response.json())["id"]

    update_response = app_client.post(
        f"/api/tasks/update/{task_id}",
        json=_create_task_payload(
            client_id,
            config_id,
            name="鸟类任务-002",
            interval_hours=6,
            execution_mode="auto",
            auto_confirm=True,
            filters={
                "classify_list": [2],
                "keyword": "夜拍",
                "sp_name": "苍鹭",
                "start_at": "2026-04-01",
                "end_at": "2026-04-25",
                "media_types": ["video"],
                "upload_types": [1],
                "identify_source": [0],
            },
        ),
    )

    assert update_response.status_code == 200
    updated = _unwrap_success(update_response.json())
    assert updated["name"] == "鸟类任务-002"
    assert updated["interval_hours"] == 6
    assert updated["execution_mode"] == "auto"
    assert updated["auto_confirm"] is True
    assert updated["filters"]["media_types"] == ["video"]


def test_delete_task_cascades_task_items(
    app_client: TestClient,
    db_session: Session,
) -> None:
    client_id, config_id = _create_client_and_config(app_client)
    task_response = app_client.post(
        "/api/tasks/create",
        json=_create_task_payload(client_id, config_id),
    )
    task_id = _unwrap_success(task_response.json())["id"]

    _, task_item_model, task_item_data_model = import_task_models()

    task_item = task_item_model(
        task_id=task_id,
        name="image-1.jpg",
        device_name="device-1",
        file_num="file-001",
        file_extension="jpg",
        file_url="https://example.com/file.jpg",
        file_fid="fid-001",
        sp_name_list="白鹭",
        classify=1,
        file_bmp=1,
        result_file_data="",
        id_type=0,
        status="创建",
    )
    db_session.add(task_item)
    db_session.commit()
    db_session.refresh(task_item)

    task_item_data = task_item_data_model(
        task_item_id=task_item.id,
        name="白鹭",
        score=0.91,
        track_ids="1",
        sp_amount=1,
    )
    db_session.add(task_item_data)
    db_session.commit()

    delete_response = app_client.delete(f"/api/tasks/delete/{task_id}")

    assert delete_response.status_code == 200
    data = _unwrap_success(delete_response.json())
    assert data["id"] == task_id
    assert db_session.exec(select(task_item_model)).all() == []
    assert db_session.exec(select(task_item_data_model)).all() == []


def test_task_action_start_stop_and_run(app_client: TestClient) -> None:
    client_id, config_id = _create_client_and_config(app_client)
    create_response = app_client.post(
        "/api/tasks/create",
        json=_create_task_payload(client_id, config_id),
    )
    task_id = _unwrap_success(create_response.json())["id"]

    start_response = app_client.post(f"/api/tasks/action-start/{task_id}")
    stop_response = app_client.post(f"/api/tasks/action-stop/{task_id}")
    run_response = app_client.post(f"/api/tasks/action-run/{task_id}")

    assert start_response.status_code == 200
    assert stop_response.status_code == 200
    assert run_response.status_code == 200
    assert start_response.json()["code"] == 0
    assert stop_response.json()["code"] == 0
    assert run_response.json()["code"] == 0


def import_task_models():
    from aiSelfTest.models.task import Task, TaskItem, TaskItemData

    return Task, TaskItem, TaskItemData
