"""任务接口契约测试。"""

from __future__ import annotations

import importlib
from typing import Any

from fastapi.testclient import TestClient
from sqlmodel import Session, select


class FakeResponse:
    """简化的 requests 响应对象。"""

    def __init__(
        self,
        status_code: int,
        json_data: dict[str, Any] | None = None,
        text: str = "",
        content: bytes = b"",
    ) -> None:
        self.status_code = status_code
        self._json_data = json_data or {}
        self.text = text or str(self._json_data)
        self.content = content or self.text.encode()

    def json(self) -> dict[str, Any]:
        """返回预设 JSON 响应体。"""

        return self._json_data

    def iter_content(self, chunk_size: int) -> list[bytes]:
        """返回预设二进制响应体。"""

        return [self.content]

    def close(self) -> None:
        """兼容 requests.Response.close。"""

        return None


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
        "auto_execute": False,
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
    assert created["auto_execute"] is False

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
            auto_execute=True,
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
    assert updated["auto_execute"] is True
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
        file_id="file-001",
        file_fid="fid-001",
        sp_name_list="白鹭",
        classify=1,
        file_bmp=1,
        result_file_data="",
        id_type=0,
        status="已创建",
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


def test_task_action_start_stop_and_run(
    app_client: TestClient,
    monkeypatch,
) -> None:
    client_id, config_id = _create_client_and_config(app_client)
    create_response = app_client.post(
        "/api/tasks/create",
        json=_create_task_payload(client_id, config_id),
    )
    task_id = _unwrap_success(create_response.json())["id"]
    _install_empty_upstream_mock(monkeypatch)

    start_response = app_client.post(f"/api/tasks/action-start/{task_id}")
    stop_response = app_client.post(f"/api/tasks/action-stop/{task_id}")
    run_response = app_client.post(f"/api/tasks/action-run/{task_id}")

    assert start_response.status_code == 200
    assert stop_response.status_code == 200
    assert run_response.status_code == 200
    assert start_response.json()["code"] == 0
    assert stop_response.json()["code"] == 0
    assert run_response.json()["code"] == 0


def test_task_action_run_fetches_real_upstream_and_persists_task_items(
    app_client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    """立即执行应调用真实上游分页和详情接口，而不是默认空数据源。"""

    client_id, config_id = _create_client_and_config(app_client)
    create_response = app_client.post(
        "/api/tasks/create",
        json=_create_task_payload(client_id, config_id),
    )
    task_id = _unwrap_success(create_response.json())["id"]
    calls: list[tuple[str, str, dict[str, Any]]] = []
    client_auth_module = importlib.import_module("aiSelfTest.services.client_auth")
    task_execution_module = importlib.import_module("aiSelfTest.services.task_execution")

    def fake_post(url: str, **kwargs: Any) -> FakeResponse:
        calls.append(("POST", url, kwargs))
        if url.endswith("/auth/login"):
            return FakeResponse(
                200,
                {
                    "accessToken": "task-access-token",
                    "refreshToken": "task-refresh-token",
                    "expiresIn": 3600,
                },
            )
        if url.endswith("/openApi/icFile/findFilePage"):
            assert kwargs["json"]["classifyList"] == [1, 2]
            assert kwargs["json"]["keyword"] == "鸟类"
            assert kwargs["json"]["spName"] == "白鹭"
            assert kwargs["json"]["fileBmp"] == [1, 2]
            assert kwargs["json"]["startTime"] == "2026-04-20 00:00:00"
            assert kwargs["json"]["endTime"] == "2026-04-25 23:59:59"
            return FakeResponse(
                200,
                {
                    "results": [
                        {
                            "id": 101,
                            "name": "real-image.jpg",
                            "deName": "camera-real",
                            "fileNum": "IMG-REAL-001",
                            "fileExtension": "jpg",
                            "fileUrl": "https://cdn.example.com/real-image.jpg",
                            "fileFid": "fid-real-image-101",
                            "spNameList": "白鹭",
                            "classify": 1,
                            "fileBmp": 1,
                            "idType": 0,
                        }
                    ],
                    "total": 1,
                    "size": 100,
                    "current": 1,
                    "totalCurrent": 1,
                },
            )
        raise AssertionError(f"未预期的 POST 请求: {url}")

    def fake_upstream_get(url: str, **kwargs: Any) -> FakeResponse:
        calls.append(("GET", url, kwargs))
        if url.endswith("/openApi/icFile/getResultByFileId1"):
            assert kwargs["params"] == {"fileId": "101"}
            return FakeResponse(
                200,
                {
                    "id": 101,
                    "recordData": [
                        {
                            "name": "白鹭",
                            "score": 0.93,
                            "trackIds": "track-real-1",
                            "spAmount": 1,
                            "minx": 1,
                            "miny": 2,
                            "maxx": 30,
                            "maxy": 40,
                        }
                    ],
                },
            )
        if url == "https://cdn.example.com/real-image.jpg":
            return FakeResponse(200, text="fake image", content=b"fake image")
        raise AssertionError(f"未预期的 GET 请求: {url}")

    monkeypatch.setattr(client_auth_module.requests, "post", fake_post)
    monkeypatch.setattr(task_execution_module.requests, "post", fake_post)
    monkeypatch.setattr(task_execution_module.requests, "get", fake_upstream_get)

    response = app_client.post(f"/api/tasks/action-run/{task_id}")

    assert response.status_code == 200
    assert response.json()["code"] == 0
    assert any(url.endswith("/openApi/icFile/findFilePage") for _, url, _ in calls)
    assert any(url.endswith("/openApi/icFile/getResultByFileId1") for _, url, _ in calls)

    _, task_item_model, task_item_data_model = import_task_models()
    items = db_session.exec(
        select(task_item_model).where(task_item_model.task_id == task_id)
    ).all()
    rows = db_session.exec(select(task_item_data_model)).all()

    assert len(items) == 1
    assert items[0].file_fid == "fid-real-image-101"
    assert items[0].down_state is True
    assert len(rows) == 1
    assert rows[0].name == "白鹭"
    assert rows[0].llm_name is None


def _install_empty_upstream_mock(monkeypatch) -> None:
    """安装空分页结果上游桩，避免动作契约测试访问真实网络。"""

    client_auth_module = importlib.import_module("aiSelfTest.services.client_auth")
    task_execution_module = importlib.import_module("aiSelfTest.services.task_execution")

    def fake_post(url: str, **_: Any) -> FakeResponse:
        if url.endswith("/auth/login"):
            return FakeResponse(
                200,
                {
                    "accessToken": "task-access-token",
                    "refreshToken": "task-refresh-token",
                    "expiresIn": 3600,
                },
            )
        if url.endswith("/openApi/icFile/findFilePage"):
            return FakeResponse(
                200,
                {
                    "results": [],
                    "total": 0,
                    "size": 100,
                    "current": 1,
                    "totalCurrent": 1,
                },
            )
        raise AssertionError(f"未预期的 POST 请求: {url}")

    monkeypatch.setattr(client_auth_module.requests, "post", fake_post)
    monkeypatch.setattr(task_execution_module.requests, "post", fake_post)


def import_task_models():
    from aiSelfTest.models.task import Task, TaskItem, TaskItemData

    return Task, TaskItem, TaskItemData
