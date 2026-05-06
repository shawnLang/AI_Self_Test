"""客户端管理接口测试。"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sqlmodel import Session, select


def _create_client_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "name": "树蛙项目",
        "apiUrl": "https://example.com",
        "account": "frog-admin",
        "password": "secret-123",
        "status": "启用",
    }
    payload.update(overrides)
    return payload


def _unwrap_success(response_json: dict[str, Any]) -> Any:
    assert response_json["code"] == 0
    assert response_json["message"] == "success"
    return response_json["data"]


def test_health_endpoint_returns_ok(app_client: TestClient) -> None:
    response = app_client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_request_id_header_is_returned(app_client: TestClient) -> None:
    request_id = "test-request-id-001"

    response = app_client.get("/health", headers={"X-Request-ID": request_id})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == request_id


def test_openapi_uses_chinese_router_tags(app_client: TestClient) -> None:
    response = app_client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert paths["/api/clients/list"]["get"]["tags"] == ["客户端"]
    assert paths["/api/configs/list"]["get"]["tags"] == ["提示词"]
    assert paths["/api/dashboard/stats"]["get"]["tags"] == ["首页统计"]
    assert paths["/api/multimodal-models/list"]["get"]["tags"] == ["多模态模型"]


def test_dashboard_stats_returns_frontend_compatible_shape(app_client: TestClient) -> None:
    response = app_client.get("/api/dashboard/stats")

    assert response.status_code == 200
    data = _unwrap_success(response.json())
    assert data["activeTasks"] == 0
    assert data["processedToday"] == 0
    assert data["pendingReviews"] == 0
    assert data["recentActivities"] == []


def test_create_client_returns_masked_sensitive_fields(app_client: TestClient) -> None:
    response = app_client.post("/api/clients/create", json=_create_client_payload())

    assert response.status_code == 201
    data = _unwrap_success(response.json())
    assert data["name"] == "树蛙项目"
    assert data["password"] == "********"
    assert data["accessToken"] == ""
    assert data["refreshToken"] == ""


def test_list_clients_returns_masked_sensitive_fields(app_client: TestClient) -> None:
    app_client.post("/api/clients/create", json=_create_client_payload())

    response = app_client.get("/api/clients/list")

    assert response.status_code == 200
    data = _unwrap_success(response.json())
    assert len(data["items"]) == 1
    item = data["items"][0]
    assert item["password"] == "********"
    assert item["accessToken"] == ""
    assert item["refreshToken"] == ""


def test_create_client_validates_required_fields(app_client: TestClient) -> None:
    response = app_client.post(
        "/api/clients/create",
        json={"name": "", "apiUrl": "", "account": "", "password": "", "status": "启用"},
    )

    assert response.status_code == 400
    body = response.json()
    assert body["code"] == 1001


def test_update_client_with_blank_password_keeps_original_password(
    app_client: TestClient,
    db_session: Session,
) -> None:
    create_response = app_client.post("/api/clients/create", json=_create_client_payload())
    client_id = _unwrap_success(create_response.json())["id"]

    response = app_client.put(
        f"/api/clients/update/{client_id}",
        json=_create_client_payload(name="新项目名", password=""),
    )

    assert response.status_code == 200

    client_model = import_client_model()
    client = db_session.exec(select(client_model).where(client_model.id == client_id)).one()
    assert client.password == "secret-123"
    assert client.name == "新项目名"


def test_update_client_with_mask_placeholder_keeps_original_password(
    app_client: TestClient,
    db_session: Session,
) -> None:
    create_response = app_client.post("/api/clients/create", json=_create_client_payload())
    client_id = _unwrap_success(create_response.json())["id"]

    response = app_client.put(
        f"/api/clients/update/{client_id}",
        json=_create_client_payload(password="********"),
    )

    assert response.status_code == 200

    client_model = import_client_model()
    client = db_session.exec(select(client_model).where(client_model.id == client_id)).one()
    assert client.password == "secret-123"


def test_update_client_with_new_password_updates_database(
    app_client: TestClient,
    db_session: Session,
) -> None:
    create_response = app_client.post("/api/clients/create", json=_create_client_payload())
    client_id = _unwrap_success(create_response.json())["id"]

    response = app_client.put(
        f"/api/clients/update/{client_id}",
        json=_create_client_payload(password="new-secret-456"),
    )

    assert response.status_code == 200

    client_model = import_client_model()
    client = db_session.exec(select(client_model).where(client_model.id == client_id)).one()
    assert client.password == "new-secret-456"


def test_delete_client_cascades_related_task_data(
    app_client: TestClient,
    db_session: Session,
) -> None:
    create_response = app_client.post("/api/clients/create", json=_create_client_payload())
    client_id = _unwrap_success(create_response.json())["id"]

    config_model, task_model, task_item_model, task_item_data_model = import_task_models()

    config = config_model(name="默认提示词", remark="测试", text="提示词", format=0)
    db_session.add(config)
    db_session.commit()
    db_session.refresh(config)

    task = task_model(
        name="测试任务",
        client_id=client_id,
        config_id=config.id,
    )
    db_session.add(task)
    db_session.commit()
    db_session.refresh(task)

    task_item = task_item_model(
        task_id=task.id,
        name="image-1.jpg",
        device_name="device-1",
        file_num="file-001",
        file_extension="jpg",
        file_url="https://example.com/file.jpg",
        file_id="file-001",
        file_fid="fid-001",
        sp_name_list="树蛙",
        classify=1,
        file_bmp=1,
        result_file_data="{}",
        id_type=0,
        status="已创建",
    )
    db_session.add(task_item)
    db_session.commit()
    db_session.refresh(task_item)

    task_item_data = task_item_data_model(
        task_item_id=task_item.id,
        name="树蛙",
        score=0.88,
        track_ids="1,2",
        sp_amount=1,
    )
    db_session.add(task_item_data)
    db_session.commit()

    response = app_client.delete(f"/api/clients/delete/{client_id}")

    assert response.status_code == 200
    assert db_session.exec(select(task_model)).all() == []
    assert db_session.exec(select(task_item_model)).all() == []
    assert db_session.exec(select(task_item_data_model)).all() == []


def test_delete_missing_client_returns_not_found(app_client: TestClient) -> None:
    response = app_client.delete("/api/clients/delete/99999")

    assert response.status_code == 404
    body = response.json()
    assert body["code"] == 1002


def import_client_model():
    from aiSelfTest.models.client import Client

    return Client


def import_task_models():
    from aiSelfTest.models.config import Config
    from aiSelfTest.models.task import Task, TaskItem, TaskItemData

    return Config, Task, TaskItem, TaskItemData
