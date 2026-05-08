"""多模态模型管理与模型测试接口测试。"""

from __future__ import annotations

import importlib
import json
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
        *,
        headers: dict[str, str] | None = None,
        stream_lines: list[str] | None = None,
    ) -> None:
        self.status_code = status_code
        self._json_data = json_data or {}
        self.text = text or str(self._json_data)
        self.headers = headers or {"Content-Type": "application/json"}
        self._stream_lines = stream_lines or []

    def json(self) -> dict[str, Any]:
        """返回 JSON 响应体。"""

        return self._json_data

    def iter_lines(self, decode_unicode: bool = False):
        """模拟 requests 的流式逐行迭代。"""

        for line in self._stream_lines:
            yield line if decode_unicode else line.encode("utf-8")

    def close(self) -> None:
        """关闭响应对象。"""


def _create_model_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "modelName": "gpt-4.1-mini",
        "endpointUrl": "https://gateway.example.com/v1/chat/completions",
        "apiKey": "model-secret-key",
        "status": "启用",
        "detectedModels": [],
        "detectedModelsUpdated": False,
    }
    payload.update(overrides)
    return payload


def _unwrap_success(response_json: dict[str, Any]) -> Any:
    assert response_json["code"] == 0
    assert response_json["message"] == "success"
    return response_json["data"]


def test_list_multimodal_models_returns_empty_items(app_client: TestClient) -> None:
    response = app_client.get("/api/multimodal-models/list")

    assert response.status_code == 200
    data = _unwrap_success(response.json())
    assert data["items"] == []


def test_create_multimodal_model_returns_masked_api_key(app_client: TestClient) -> None:
    response = app_client.post(
        "/api/multimodal-models/create",
        json=_create_model_payload(),
    )

    assert response.status_code == 201
    data = _unwrap_success(response.json())
    assert data["modelName"] == "gpt-4.1-mini"
    assert data["apiKey"] == "********"
    assert data["apiKeyConfigured"] is True
    assert data["detectedModels"] == []


def test_update_multimodal_model_with_blank_api_key_keeps_original_value(
    app_client: TestClient,
    db_session: Session,
) -> None:
    create_response = app_client.post(
        "/api/multimodal-models/create",
        json=_create_model_payload(),
    )
    model_id = _unwrap_success(create_response.json())["id"]

    response = app_client.put(
        f"/api/multimodal-models/update/{model_id}",
        json=_create_model_payload(modelName="gpt-4.1", apiKey=""),
    )

    assert response.status_code == 200

    model_class = import_multimodal_model_class()
    model = db_session.exec(select(model_class).where(model_class.id == model_id)).one()
    assert model.api_key == "model-secret-key"
    assert model.model_name == "gpt-4.1"


def test_update_multimodal_model_with_mask_placeholder_keeps_original_value(
    app_client: TestClient,
    db_session: Session,
) -> None:
    create_response = app_client.post(
        "/api/multimodal-models/create",
        json=_create_model_payload(),
    )
    model_id = _unwrap_success(create_response.json())["id"]

    response = app_client.put(
        f"/api/multimodal-models/update/{model_id}",
        json=_create_model_payload(apiKey="********"),
    )

    assert response.status_code == 200

    model_class = import_multimodal_model_class()
    model = db_session.exec(select(model_class).where(model_class.id == model_id)).one()
    assert model.api_key == "model-secret-key"


def test_update_multimodal_model_with_new_api_key_updates_database(
    app_client: TestClient,
    db_session: Session,
) -> None:
    create_response = app_client.post(
        "/api/multimodal-models/create",
        json=_create_model_payload(),
    )
    model_id = _unwrap_success(create_response.json())["id"]

    response = app_client.put(
        f"/api/multimodal-models/update/{model_id}",
        json=_create_model_payload(apiKey="new-secret-key"),
    )

    assert response.status_code == 200

    model_class = import_multimodal_model_class()
    model = db_session.exec(select(model_class).where(model_class.id == model_id)).one()
    assert model.api_key == "new-secret-key"


def test_delete_missing_multimodal_model_returns_not_found(
    app_client: TestClient,
) -> None:
    response = app_client.delete("/api/multimodal-models/delete/99999")

    assert response.status_code == 404
    body = response.json()
    assert body["code"] == 1002


def test_detect_multimodal_models_tries_candidate_urls_and_returns_models(
    app_client: TestClient,
    monkeypatch,
) -> None:
    service_module = importlib.import_module("aiSelfTest.services.multimodal_gateway")
    calls: list[tuple[str, str, dict[str, str] | None]] = []

    def fake_get(url: str, **kwargs: Any) -> FakeResponse:
        calls.append(("GET", url, kwargs.get("headers")))
        if url.endswith("/v1/models"):
            return FakeResponse(
                200,
                {
                    "data": [
                        {"id": "gpt-4.1-mini"},
                        {"id": "qwen-vl-max"},
                    ]
                },
            )
        raise AssertionError(f"未预期的请求: GET {url}")

    monkeypatch.setattr(service_module.requests, "get", fake_get)

    response = app_client.post(
        "/api/multimodal-models/detect",
        json={
            "endpointUrl": "https://gateway.example.com/v1/chat/completions",
            "apiKey": "model-secret-key",
        },
    )

    assert response.status_code == 200
    data = _unwrap_success(response.json())
    assert data["models"] == ["gpt-4.1-mini", "qwen-vl-max"]
    assert data["recommendedModel"] == "gpt-4.1-mini"
    assert data["detectedUrl"] == "https://gateway.example.com/v1/models"
    assert calls[0][0] == "GET"
    assert calls[0][1] == "https://gateway.example.com/v1/models"


def test_detect_multimodal_models_uses_bearer_authorization_only(
    app_client: TestClient,
    monkeypatch,
) -> None:
    service_module = importlib.import_module("aiSelfTest.services.multimodal_gateway")
    urls_seen: list[str] = []
    headers_seen: list[dict[str, str] | None] = []

    def fake_get(url: str, **kwargs: Any) -> FakeResponse:
        urls_seen.append(url)
        assert url == "https://gateway.example.com/v1/models"
        headers = kwargs.get("headers")
        headers_seen.append(headers)
        if headers == {"Authorization": "Bearer model-secret-key"}:
            return FakeResponse(200, {"models": ["gpt-4.1-mini"]})
        raise AssertionError(f"未预期的认证头: {headers}")

    monkeypatch.setattr(service_module.requests, "get", fake_get)

    response = app_client.post(
        "/api/multimodal-models/detect",
        json={
            "endpointUrl": "https://gateway.example.com",
            "apiKey": "model-secret-key",
        },
    )

    assert response.status_code == 200
    data = _unwrap_success(response.json())
    assert data["models"] == ["gpt-4.1-mini"]
    assert urls_seen == ["https://gateway.example.com/v1/models"]
    assert headers_seen == [
        {"Authorization": "Bearer model-secret-key"},
    ]


def test_chat_with_multimodal_model_normalizes_attachments_and_returns_reply(
    app_client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    create_response = app_client.post(
        "/api/multimodal-models/create",
        json=_create_model_payload(),
    )
    model_id = _unwrap_success(create_response.json())["id"]

    service_module = importlib.import_module("aiSelfTest.services.multimodal_gateway")
    captured_payloads: list[dict[str, Any]] = []

    def fake_post(url: str, **kwargs: Any) -> FakeResponse:
        assert url == "https://gateway.example.com/v1/chat/completions"
        captured_payloads.append(kwargs["json"])
        assert kwargs["headers"] == {"Authorization": "Bearer model-secret-key"}
        return FakeResponse(
            200,
            {"choices": [{"message": {"content": "这是模型回复"}}]},
        )

    monkeypatch.setattr(service_module.requests, "post", fake_post)

    response = app_client.post(
        f"/api/multimodal-models/chat/{model_id}",
        json={
            "messages": [
                {
                    "role": "user",
                    "content": "请识别这张图里的物种",
                    "attachments": [
                        {
                            "name": "frog.jpg",
                            "mimeType": "image/jpeg",
                            "kind": "image",
                            "dataUrl": "data:image/jpeg;base64,ZmFrZS1pbWFnZQ==",
                        },
                        {
                            "name": "sound.wav",
                            "mimeType": "audio/wav",
                            "kind": "audio",
                            "dataUrl": "data:audio/wav;base64,UklGRg==",
                        },
                        {
                            "name": "note.txt",
                            "mimeType": "text/plain",
                            "kind": "document",
                            "textContent": "这是一段补充说明",
                        },
                        {
                            "name": "clip.mp4",
                            "mimeType": "video/mp4",
                            "kind": "video",
                            "dataUrl": "data:video/mp4;base64,AAAA",
                        },
                    ],
                }
            ]
        },
    )

    assert response.status_code == 200
    data = _unwrap_success(response.json())
    assert data["reply"] == "这是模型回复"
    assert data["modelName"] == "gpt-4.1-mini"
    assert data["usedUrl"] == "https://gateway.example.com/v1/chat/completions"

    normalized_message = captured_payloads[0]["messages"][0]
    assert normalized_message["role"] == "user"
    assert normalized_message["content"][0] == {
        "type": "text",
        "text": "请识别这张图里的物种",
    }
    assert normalized_message["content"][1]["type"] == "image_url"
    assert normalized_message["content"][1]["image_url"]["url"].startswith(
        "data:image/jpeg;base64,"
    )
    assert normalized_message["content"][2] == {
        "type": "input_audio",
        "input_audio": {
            "data": "UklGRg==",
            "format": "wav",
        },
    }
    assert "附件《note.txt》内容如下" in normalized_message["content"][3]["text"]
    assert "clip.mp4" in normalized_message["content"][4]["text"]


def test_chat_with_multimodal_model_supports_output_text_response_shape(
    app_client: TestClient,
    monkeypatch,
) -> None:
    create_response = app_client.post(
        "/api/multimodal-models/create",
        json=_create_model_payload(modelName="qwen-vl-max"),
    )
    model_id = _unwrap_success(create_response.json())["id"]

    service_module = importlib.import_module("aiSelfTest.services.multimodal_gateway")

    def fake_post(url: str, **kwargs: Any) -> FakeResponse:
        return FakeResponse(200, {"output_text": "这是 output_text 回复"})

    monkeypatch.setattr(service_module.requests, "post", fake_post)

    response = app_client.post(
        f"/api/multimodal-models/chat/{model_id}",
        json={"messages": [{"role": "user", "content": "hello", "attachments": []}]},
    )

    assert response.status_code == 200
    data = _unwrap_success(response.json())
    assert data["reply"] == "这是 output_text 回复"


def test_chat_with_multimodal_model_supports_output_content_response_shape(
    app_client: TestClient,
    monkeypatch,
) -> None:
    create_response = app_client.post(
        "/api/multimodal-models/create",
        json=_create_model_payload(modelName="glm-4.1v"),
    )
    model_id = _unwrap_success(create_response.json())["id"]

    service_module = importlib.import_module("aiSelfTest.services.multimodal_gateway")

    def fake_post(url: str, **kwargs: Any) -> FakeResponse:
        return FakeResponse(
            200,
            {
                "output": [
                    {
                        "content": [
                            {"text": "这是 output[].content 回复"},
                        ]
                    }
                ]
            },
        )

    monkeypatch.setattr(service_module.requests, "post", fake_post)

    response = app_client.post(
        f"/api/multimodal-models/chat/{model_id}",
        json={"messages": [{"role": "user", "content": "hello", "attachments": []}]},
    )

    assert response.status_code == 200
    data = _unwrap_success(response.json())
    assert data["reply"] == "这是 output[].content 回复"


def test_chat_with_multimodal_model_creates_session_and_persists_messages(
    app_client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    create_response = app_client.post(
        "/api/multimodal-models/create",
        json=_create_model_payload(modelName="gemma-4"),
    )
    model_id = _unwrap_success(create_response.json())["id"]

    service_module = importlib.import_module("aiSelfTest.services.multimodal_gateway")

    def fake_post(url: str, **kwargs: Any) -> FakeResponse:
        assert kwargs["json"]["messages"][0]["content"] == "第一轮问题"
        return FakeResponse(
            200,
            {"choices": [{"message": {"content": "第一轮回答"}}]},
        )

    monkeypatch.setattr(service_module.requests, "post", fake_post)

    response = app_client.post(
        f"/api/multimodal-models/chat/{model_id}",
        json={"messages": [{"role": "user", "content": "第一轮问题", "attachments": []}]},
    )

    assert response.status_code == 200
    data = _unwrap_success(response.json())
    assert data["reply"] == "第一轮回答"
    assert data["sessionId"] > 0

    session_class = import_multimodal_chat_session_class()
    message_class = import_multimodal_chat_message_class()
    chat_session = db_session.get(session_class, data["sessionId"])
    assert chat_session is not None
    assert chat_session.message_count == 2

    message_rows = db_session.exec(
        select(message_class)
        .where(message_class.session_id == data["sessionId"])
        .order_by(message_class.sequence_no.asc())
    ).all()
    assert [item.role for item in message_rows] == ["user", "assistant"]
    assert message_rows[0].content == "第一轮问题"
    assert message_rows[1].content == "第一轮回答"


def test_chat_with_multimodal_model_uses_stored_session_context(
    app_client: TestClient,
    monkeypatch,
) -> None:
    create_response = app_client.post(
        "/api/multimodal-models/create",
        json=_create_model_payload(modelName="gemma-4"),
    )
    model_id = _unwrap_success(create_response.json())["id"]

    service_module = importlib.import_module("aiSelfTest.services.multimodal_gateway")
    captured_payloads: list[dict[str, Any]] = []
    replies = iter(["第一轮回答", "第二轮回答"])

    def fake_post(url: str, **kwargs: Any) -> FakeResponse:
        captured_payloads.append(kwargs["json"])
        return FakeResponse(
            200,
            {"choices": [{"message": {"content": next(replies)}}]},
        )

    monkeypatch.setattr(service_module.requests, "post", fake_post)

    first_response = app_client.post(
        f"/api/multimodal-models/chat/{model_id}",
        json={"messages": [{"role": "user", "content": "第一轮问题", "attachments": []}]},
    )
    first_session_id = _unwrap_success(first_response.json())["sessionId"]

    second_response = app_client.post(
        f"/api/multimodal-models/chat/{model_id}",
        json={
            "sessionId": first_session_id,
            "messages": [{"role": "user", "content": "第二轮问题", "attachments": []}],
        },
    )

    assert second_response.status_code == 200
    second_payload_messages = captured_payloads[1]["messages"]
    assert len(second_payload_messages) == 3
    assert second_payload_messages[0]["content"] == "第一轮问题"
    assert second_payload_messages[1]["content"] == "第一轮回答"
    assert second_payload_messages[2]["content"] == "第二轮问题"


def test_list_and_detail_multimodal_chat_sessions(
    app_client: TestClient,
    monkeypatch,
) -> None:
    create_response = app_client.post(
        "/api/multimodal-models/create",
        json=_create_model_payload(modelName="gemma-4"),
    )
    model_id = _unwrap_success(create_response.json())["id"]

    service_module = importlib.import_module("aiSelfTest.services.multimodal_gateway")

    def fake_post(url: str, **kwargs: Any) -> FakeResponse:
        return FakeResponse(
            200,
            {"choices": [{"message": {"content": "列表详情测试回复"}}]},
        )

    monkeypatch.setattr(service_module.requests, "post", fake_post)

    chat_response = app_client.post(
        f"/api/multimodal-models/chat/{model_id}",
        json={"messages": [{"role": "user", "content": "请记录这轮会话", "attachments": []}]},
    )
    session_id = _unwrap_success(chat_response.json())["sessionId"]

    list_response = app_client.get(f"/api/multimodal-models/session-list/{model_id}")
    assert list_response.status_code == 200
    list_data = _unwrap_success(list_response.json())
    assert len(list_data["items"]) == 1
    assert list_data["items"][0]["id"] == session_id
    assert list_data["items"][0]["messageCount"] == 2

    detail_response = app_client.get(f"/api/multimodal-models/session-detail/{session_id}")
    assert detail_response.status_code == 200
    detail_data = _unwrap_success(detail_response.json())
    assert detail_data["session"]["id"] == session_id
    assert [item["role"] for item in detail_data["messages"]] == ["user", "assistant"]
    assert detail_data["messages"][0]["content"] == "请记录这轮会话"
    assert detail_data["messages"][1]["content"] == "列表详情测试回复"


def test_delete_multimodal_chat_session_removes_session_and_messages(
    app_client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    create_response = app_client.post(
        "/api/multimodal-models/create",
        json=_create_model_payload(modelName="gemma-4"),
    )
    model_id = _unwrap_success(create_response.json())["id"]

    service_module = importlib.import_module("aiSelfTest.services.multimodal_gateway")

    def fake_post(url: str, **kwargs: Any) -> FakeResponse:
        return FakeResponse(
            200,
            {"choices": [{"message": {"content": "待删除的回复"}}]},
        )

    monkeypatch.setattr(service_module.requests, "post", fake_post)

    chat_response = app_client.post(
        f"/api/multimodal-models/chat/{model_id}",
        json={"messages": [{"role": "user", "content": "待删除会话", "attachments": []}]},
    )
    session_id = _unwrap_success(chat_response.json())["sessionId"]

    delete_response = app_client.delete(f"/api/multimodal-models/delete-session/{session_id}")
    assert delete_response.status_code == 200
    delete_data = _unwrap_success(delete_response.json())
    assert delete_data["id"] == session_id

    session_class = import_multimodal_chat_session_class()
    message_class = import_multimodal_chat_message_class()
    assert db_session.get(session_class, session_id) is None
    message_rows = db_session.exec(
        select(message_class).where(message_class.session_id == session_id)
    ).all()
    assert message_rows == []

    detail_response = app_client.get(f"/api/multimodal-models/session-detail/{session_id}")
    assert detail_response.status_code == 404
    assert detail_response.json()["code"] == 1002

    duplicate_delete_response = app_client.delete(
        f"/api/multimodal-models/delete-session/{session_id}"
    )
    assert duplicate_delete_response.status_code == 404
    assert duplicate_delete_response.json()["code"] == 1002


def test_stream_chat_with_multimodal_model_returns_sse_and_persists_messages(
    app_client: TestClient,
    monkeypatch,
) -> None:
    create_response = app_client.post(
        "/api/multimodal-models/create",
        json=_create_model_payload(modelName="gemma-4"),
    )
    model_id = _unwrap_success(create_response.json())["id"]

    service_module = importlib.import_module("aiSelfTest.services.multimodal_gateway")

    def fake_post(url: str, **kwargs: Any) -> FakeResponse:
        assert kwargs["json"]["stream"] is True
        return FakeResponse(
            200,
            headers={"Content-Type": "text/event-stream"},
            stream_lines=[
                f"data: {json.dumps({'choices': [{'delta': {'content': '流式'}}]}, ensure_ascii=False)}",
                "",
                f"data: {json.dumps({'choices': [{'delta': {'content': '回复'}}]}, ensure_ascii=False)}",
                "",
                "data: [DONE]",
                "",
            ],
        )

    monkeypatch.setattr(service_module.requests, "post", fake_post)

    with app_client.stream(
        "POST",
        f"/api/multimodal-models/chat-stream/{model_id}",
        json={"messages": [{"role": "user", "content": "请流式回答", "attachments": []}]},
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = "".join(chunk for chunk in response.iter_text())

    assert "event: session" in body
    assert "event: delta" in body
    assert "event: done" in body
    assert "流式回复" in body

    list_response = app_client.get(f"/api/multimodal-models/session-list/{model_id}")
    list_data = _unwrap_success(list_response.json())
    assert len(list_data["items"]) == 1
    session_id = list_data["items"][0]["id"]

    detail_response = app_client.get(f"/api/multimodal-models/session-detail/{session_id}")
    detail_data = _unwrap_success(detail_response.json())
    assert detail_data["messages"][1]["content"] == "流式回复"


def test_chat_with_multimodal_model_rejects_disabled_model(
    app_client: TestClient,
) -> None:
    create_response = app_client.post(
        "/api/multimodal-models/create",
        json=_create_model_payload(status="停用"),
    )
    model_id = _unwrap_success(create_response.json())["id"]

    response = app_client.post(
        f"/api/multimodal-models/chat/{model_id}",
        json={"messages": [{"role": "user", "content": "hello", "attachments": []}]},
    )

    assert response.status_code == 400
    body = response.json()
    assert body["code"] == 1001


def import_multimodal_model_class():
    from aiSelfTest.models.multimodal_model import MultimodalModel

    return MultimodalModel


def import_multimodal_chat_session_class():
    from aiSelfTest.models.multimodal_chat import MultimodalChatSession

    return MultimodalChatSession


def import_multimodal_chat_message_class():
    from aiSelfTest.models.multimodal_chat import MultimodalChatMessage

    return MultimodalChatMessage
