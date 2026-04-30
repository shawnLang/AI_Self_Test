"""旧 task 页面兼容接口测试。"""

from __future__ import annotations

import importlib
from typing import Any

from fastapi.testclient import TestClient
from sqlmodel import Session


class FakeResponse:
    """简化的 requests 响应对象。"""

    def __init__(
        self,
        status_code: int,
        json_data: dict[str, Any] | None = None,
        text: str = "",
    ) -> None:
        self.status_code = status_code
        self._json_data = json_data or {}
        self.text = text or str(self._json_data)

    def json(self) -> dict[str, Any]:
        """返回预设 JSON 响应体。"""

        return self._json_data


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
        file_id="file-001",
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
    monkeypatch,
) -> None:
    task_id, _ = _seed_task_fixture(app_client, db_session)
    task_model, _, _ = import_task_models()
    _install_empty_upstream_mock(monkeypatch)

    response = app_client.post(
        f"/api/tasks/{task_id}/execute",
        json={"fileIds": [], "selectedItems": []},
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    task = db_session.get(task_model, task_id)
    assert task is not None
    assert task.started_at is not None


def _install_empty_upstream_mock(monkeypatch) -> None:
    """安装空分页结果上游桩，避免兼容接口测试访问真实网络。"""

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
