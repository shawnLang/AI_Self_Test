"""模型提示词配置接口测试。"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient


def _create_config_payload(**overrides: Any) -> dict[str, Any]:
    """构造创建或更新提示词配置的请求体。"""

    payload = {
        "name": "默认物种复核提示词",
        "remark": "用于任务执行时识别物种",
        "text": "请根据图片裁剪区域判断物种，并只返回目标物种名称。",
        "format": 0,
    }
    payload.update(overrides)
    return payload


def _unwrap_success(response_json: dict[str, Any]) -> Any:
    """取出统一响应中的 data 字段。"""

    assert response_json["code"] == 0
    assert response_json["message"] == "success"
    return response_json["data"]


def test_list_configs_returns_empty_items(app_client: TestClient) -> None:
    """空库时提示词配置列表为空。"""

    response = app_client.get("/api/configs/list")

    assert response.status_code == 200
    data = _unwrap_success(response.json())
    assert data["items"] == []


def test_create_config_and_get_detail(app_client: TestClient) -> None:
    """创建提示词配置后可查询详情。"""

    create_response = app_client.post(
        "/api/configs/create",
        json=_create_config_payload(),
    )

    assert create_response.status_code == 201
    created = _unwrap_success(create_response.json())
    assert created["name"] == "默认物种复核提示词"
    assert created["remark"] == "用于任务执行时识别物种"
    assert created["text"] == "请根据图片裁剪区域判断物种，并只返回目标物种名称。"
    assert created["format"] == 0

    detail_response = app_client.get(f"/api/configs/detail/{created['id']}")

    assert detail_response.status_code == 200
    detail = _unwrap_success(detail_response.json())
    assert detail == created


def test_list_configs_returns_created_items_desc(app_client: TestClient) -> None:
    """提示词配置列表按 ID 倒序返回。"""

    first_response = app_client.post(
        "/api/configs/create",
        json=_create_config_payload(name="提示词 A"),
    )
    second_response = app_client.post(
        "/api/configs/create",
        json=_create_config_payload(name="提示词 B", format=1),
    )
    first = _unwrap_success(first_response.json())
    second = _unwrap_success(second_response.json())

    response = app_client.get("/api/configs/list")

    assert response.status_code == 200
    data = _unwrap_success(response.json())
    assert [item["id"] for item in data["items"]] == [second["id"], first["id"]]
    assert [item["name"] for item in data["items"]] == ["提示词 B", "提示词 A"]


def test_update_config_persists_new_values(app_client: TestClient) -> None:
    """更新提示词配置后可回读最新值。"""

    create_response = app_client.post(
        "/api/configs/create",
        json=_create_config_payload(),
    )
    config_id = _unwrap_success(create_response.json())["id"]

    response = app_client.put(
        f"/api/configs/update/{config_id}",
        json=_create_config_payload(
            name="更新后的提示词",
            remark="更新后的备注",
            text="请返回 JSON 格式的识别结果。",
            format=2,
        ),
    )

    assert response.status_code == 200
    updated = _unwrap_success(response.json())
    assert updated["id"] == config_id
    assert updated["name"] == "更新后的提示词"
    assert updated["remark"] == "更新后的备注"
    assert updated["text"] == "请返回 JSON 格式的识别结果。"
    assert updated["format"] == 2

    detail_response = app_client.get(f"/api/configs/detail/{config_id}")
    detail = _unwrap_success(detail_response.json())
    assert detail == updated


def test_delete_config_removes_row(app_client: TestClient) -> None:
    """删除提示词配置后详情不可再访问。"""

    create_response = app_client.post(
        "/api/configs/create",
        json=_create_config_payload(),
    )
    config_id = _unwrap_success(create_response.json())["id"]

    response = app_client.delete(f"/api/configs/delete/{config_id}")

    assert response.status_code == 200
    data = _unwrap_success(response.json())
    assert data["id"] == config_id

    detail_response = app_client.get(f"/api/configs/detail/{config_id}")
    assert detail_response.status_code == 404
    assert detail_response.json()["code"] == 1002


def test_missing_config_operations_return_not_found(app_client: TestClient) -> None:
    """查询、更新、删除不存在的提示词配置时返回资源不存在。"""

    detail_response = app_client.get("/api/configs/detail/99999")
    update_response = app_client.put(
        "/api/configs/update/99999",
        json=_create_config_payload(),
    )
    delete_response = app_client.delete("/api/configs/delete/99999")

    assert detail_response.status_code == 404
    assert update_response.status_code == 404
    assert delete_response.status_code == 404
    assert detail_response.json()["code"] == 1002
    assert update_response.json()["code"] == 1002
    assert delete_response.json()["code"] == 1002


def test_create_config_validates_required_text_fields(app_client: TestClient) -> None:
    """提示词名称和正文禁止为空或纯空白。"""

    response = app_client.post(
        "/api/configs/create",
        json=_create_config_payload(name="   ", text="   "),
    )

    assert response.status_code == 400
    body = response.json()
    assert body["code"] == 1001


def test_create_config_rejects_unknown_format(app_client: TestClient) -> None:
    """提示词解析格式必须是受控值。"""

    response = app_client.post(
        "/api/configs/create",
        json=_create_config_payload(format=99),
    )

    assert response.status_code == 400
    body = response.json()
    assert body["code"] == 1001
