"""客户端认证能力测试。"""

from __future__ import annotations

import importlib
import time
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from requests.exceptions import ConnectTimeout
from sqlmodel import Session, select


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
        return self._json_data


def _future_timestamp(seconds: int = 3600) -> int:
    return int(time.time() + seconds)


def _expired_timestamp(seconds: int = 3600) -> int:
    return int(time.time() - seconds)


def _create_client(
    db_session: Session,
    *,
    access_token: str | None = None,
    refresh_token: str | None = None,
    expires_at: int | None = None,
) -> Any:
    client_model = import_client_model()
    client = client_model(
        name="树蛙项目",
        api_url="https://example.com",
        account="frog-admin",
        password="secret-123",
        status="启用",
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=expires_at,
    )
    db_session.add(client)
    db_session.commit()
    db_session.refresh(client)
    return client


def test_authenticate_client_route_reuses_valid_access_token(
    app_client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    client = _create_client(
        db_session,
        access_token="cached-token",
        refresh_token="refresh-token",
        expires_at=_future_timestamp(),
    )

    client_auth_module = importlib.import_module("aiSelfTest.services.client_auth")

    def fail_request(*args, **kwargs):
        raise AssertionError("存在有效 access token 时不应发起远端请求")

    monkeypatch.setattr(client_auth_module, "requests", type("Req", (), {"request": fail_request}))

    response = app_client.post(f"/api/clients/authenticate/{client.id}")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["usedStrategy"] == "reuse"
    assert payload["client"]["authStatus"] == "已认证"


def test_authenticate_client_route_logs_in_when_tokens_missing(
    app_client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    client = _create_client(db_session)
    client_auth_module = importlib.import_module("aiSelfTest.services.client_auth")
    calls: list[tuple[str, dict[str, Any] | None, dict[str, str] | None]] = []

    def fake_post(url: str, **kwargs):
        calls.append((url, kwargs.get("json"), kwargs.get("headers")))
        if url.endswith("/auth/login"):
            return FakeResponse(
                200,
                {
                    "accessToken": "login-access-token",
                    "refreshToken": "login-refresh-token",
                    "expiresIn": 3600,
                },
            )
        raise AssertionError(f"未预期的请求: {url}")

    monkeypatch.setattr(client_auth_module.requests, "post", fake_post)

    response = app_client.post(f"/api/clients/authenticate/{client.id}")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["usedStrategy"] == "login"

    db_session.expire_all()
    refreshed_client = db_session.exec(
        select(import_client_model()).where(import_client_model().id == client.id)
    ).one()
    assert refreshed_client.access_token == "login-access-token"
    assert refreshed_client.refresh_token == "login-refresh-token"
    assert refreshed_client.expires_at is not None
    assert refreshed_client.expires_at > int(time.time())
    assert len(calls) == 1
    assert calls[0][0].endswith("/auth/login")
    assert calls[0][1] == {
        "userName": "frog-admin",
        "password": "secret-123",
        "clientType": "WEB",
    }


def test_authenticate_client_route_accepts_millisecond_epoch_expires_in(
    app_client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    """上游返回毫秒级绝对过期时间戳时，入库前应转换为秒级时间戳。"""

    client = _create_client(db_session)
    client_auth_module = importlib.import_module("aiSelfTest.services.client_auth")

    def fake_post(url: str, **kwargs):
        if url.endswith("/auth/login"):
            return FakeResponse(
                200,
                {
                    "accessToken": "login-access-token",
                    "refreshToken": "login-refresh-token",
                    "expiresIn": 1779991525810,
                },
            )
        raise AssertionError(f"未预期的请求: {url}")

    monkeypatch.setattr(client_auth_module.requests, "post", fake_post)

    response = app_client.post(f"/api/clients/authenticate/{client.id}")

    assert response.status_code == 200
    assert response.json()["data"]["usedStrategy"] == "login"

    db_session.expire_all()
    refreshed_client = db_session.exec(
        select(import_client_model()).where(import_client_model().id == client.id)
    ).one()
    assert refreshed_client.expires_at == 1779991525


def test_resolve_expires_at_accepts_second_epoch_expires_in() -> None:
    """上游返回秒级绝对时间戳时，不应再次叠加当前时间。"""

    client_auth_module = importlib.import_module("aiSelfTest.services.client_auth")

    assert client_auth_module.ClientUtils.resolve_expires_at(1779991525) == 1779991525


def test_authenticate_client_route_refreshes_expired_token(
    app_client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    client = _create_client(
        db_session,
        access_token="expired-access-token",
        refresh_token="refresh-token",
        expires_at=_expired_timestamp(),
    )
    client_auth_module = importlib.import_module("aiSelfTest.services.client_auth")
    calls: list[tuple[str, dict[str, str] | None]] = []

    def fake_post(url: str, **kwargs):
        calls.append((url, kwargs.get("headers")))
        if url.endswith("/auth/refresh"):
            assert kwargs["headers"]["Authorization"] == "refresh-token"
            return FakeResponse(
                200,
                {
                    "accessToken": "refresh-access-token",
                    "refreshToken": "refresh-token-2",
                    "expiresIn": 3600,
                },
            )
        raise AssertionError(f"未预期的请求: {url}")

    monkeypatch.setattr(client_auth_module.requests, "post", fake_post)

    response = app_client.post(f"/api/clients/authenticate/{client.id}")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["usedStrategy"] == "refresh"
    assert len(calls) == 1


def test_authenticate_client_route_falls_back_to_login_when_refresh_fails(
    app_client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    client = _create_client(
        db_session,
        access_token="expired-access-token",
        refresh_token="refresh-token",
        expires_at=_expired_timestamp(),
    )
    client_auth_module = importlib.import_module("aiSelfTest.services.client_auth")
    calls: list[str] = []

    def fake_post(url: str, **kwargs):
        calls.append(url)
        if url.endswith("/auth/refresh"):
            return FakeResponse(401, {"message": "token expired"}, "token expired")
        if url.endswith("/auth/login"):
            return FakeResponse(
                200,
                {
                    "accessToken": "login-access-token",
                    "refreshToken": "login-refresh-token",
                    "expiresIn": 3600,
                },
            )
        raise AssertionError(f"未预期的请求: {url}")

    monkeypatch.setattr(client_auth_module.requests, "post", fake_post)

    response = app_client.post(f"/api/clients/authenticate/{client.id}")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["usedStrategy"] == "login"
    assert calls == [
        "https://example.com/auth/refresh",
        "https://example.com/auth/login",
    ]


def test_client_api_retries_find_file_page_on_retryable_status(
    monkeypatch,
) -> None:
    client = SimpleNamespace(
        id=1,
        api_url="https://example.com",
        status="启用",
        access_token="cached-token",
        refresh_token="refresh-token",
        expires_at=_future_timestamp(),
    )
    client_auth_module = importlib.import_module("aiSelfTest.services.client_auth")
    api = client_auth_module.ClientApi(object(), client.id)
    api.client = client
    calls: list[str] = []

    def fake_post(url: str, **kwargs):
        calls.append(url)
        assert kwargs["headers"]["Authorization"] == "cached-token"
        if len(calls) == 1:
            return FakeResponse(503, {"message": "service unavailable"})
        return FakeResponse(200, {"records": []})

    monkeypatch.setattr(client_auth_module.requests, "post", fake_post)

    response = api.find_file_page({"size": 10, "current": 1})

    assert response.status_code == 200
    assert len(calls) == 2
    assert calls[0].endswith("/openApi/icFile/findFilePage")


def test_client_api_reauthenticates_find_file_page_when_token_expired(
    monkeypatch,
) -> None:
    class FakeSession:
        """记录 ClientApi 写回 token 时需要的最小 session 行为。"""

        def add(self, obj: Any) -> None:
            return None

        def commit(self) -> None:
            return None

        def refresh(self, obj: Any) -> None:
            return None

    client = SimpleNamespace(
        id=1,
        api_url="https://example.com",
        account="frog-admin",
        password="secret-123",
        status="启用",
        tenant_code="",
        tenant_name="",
        access_token="stale-token",
        refresh_token="",
        expires_at=_future_timestamp(),
    )
    client_auth_module = importlib.import_module("aiSelfTest.services.client_auth")
    api = client_auth_module.ClientApi(FakeSession(), client.id)
    api.client = client
    calls: list[tuple[str, str | None]] = []

    def fake_post(url: str, **kwargs):
        authorization = (kwargs.get("headers") or {}).get("Authorization")
        calls.append((url, authorization))

        if url.endswith("/openApi/icFile/findFilePage"):
            if authorization == "stale-token":
                return FakeResponse(401, {"message": "登录失效"}, "登录失效")
            if authorization == "fresh-token":
                return FakeResponse(200, {"records": []})
            raise AssertionError(f"未预期的业务请求 Authorization: {authorization}")

        if url.endswith("/auth/login"):
            assert kwargs["json"] == {
                "userName": "frog-admin",
                "password": "secret-123",
                "clientType": "WEB",
            }
            return FakeResponse(
                200,
                {
                    "accessToken": "fresh-token",
                    "refreshToken": "fresh-refresh-token",
                    "expiresIn": 3600,
                },
            )

        raise AssertionError(f"未预期的请求: {url}")

    monkeypatch.setattr(client_auth_module.requests, "post", fake_post)

    response = api.find_file_page({"size": 10, "current": 1})

    assert response.status_code == 200
    assert calls == [
        ("https://example.com/openApi/icFile/findFilePage", "stale-token"),
        ("https://example.com/auth/login", None),
        ("https://example.com/openApi/icFile/findFilePage", "fresh-token"),
    ]
    assert client.access_token == "fresh-token"
    assert client.refresh_token == "fresh-refresh-token"


def test_client_api_retries_get_result_by_fileId_on_request_exception(
    monkeypatch,
) -> None:
    client = SimpleNamespace(
        id=1,
        api_url="https://example.com",
        status="启用",
        access_token="cached-token",
        refresh_token="refresh-token",
        expires_at=_future_timestamp(),
    )
    client_auth_module = importlib.import_module("aiSelfTest.services.client_auth")
    api = client_auth_module.ClientApi(object(), client.id)
    api.client = client
    calls: list[str] = []

    def fake_get(url: str, **kwargs):
        calls.append(url)
        assert kwargs["params"] == {"fileId": "file-001"}
        if len(calls) == 1:
            raise ConnectTimeout("临时连接超时")
        return FakeResponse(200, {"fileId": "file-001"})

    monkeypatch.setattr(client_auth_module.requests, "get", fake_get)

    response = api.get_result_by_fileId({"fileId": "file-001"})

    assert response.status_code == 200
    assert len(calls) == 2
    assert calls[0].endswith("/openApi/icFile/getResultDetByFileId")


def test_client_api_updates_ai_polling_result(monkeypatch) -> None:
    """客户端 API 应调用更新 ai 巡检结果接口。"""

    client = SimpleNamespace(
        id=1,
        api_url="https://example.com",
        status="启用",
        access_token="cached-token",
        refresh_token="refresh-token",
        expires_at=_future_timestamp(),
    )
    client_auth_module = importlib.import_module("aiSelfTest.services.client_auth")
    api = client_auth_module.ClientApi(object(), client.id)
    api.client = client
    calls: list[str] = []
    payload = {"id": 101, "recordData": [{"name": "白鹭"}]}

    def fake_post(url: str, **kwargs):
        calls.append(url)
        assert kwargs["headers"] == {"Authorization": "cached-token"}
        assert kwargs["json"] == payload
        return FakeResponse(200, True)

    monkeypatch.setattr(client_auth_module.requests, "post", fake_post)

    response = api.update_ai_polling_result(payload)

    assert response.status_code == 200
    assert response.json() is True
    assert calls == ["https://example.com/openApi/icFile/aiPollingResult"]


def test_client_api_retries_raise_app_exception_after_request_failures(
    monkeypatch,
) -> None:
    client = SimpleNamespace(
        id=1,
        api_url="https://example.com",
        status="启用",
        access_token="cached-token",
        refresh_token="refresh-token",
        expires_at=_future_timestamp(),
    )
    client_auth_module = importlib.import_module("aiSelfTest.services.client_auth")
    api = client_auth_module.ClientApi(object(), client.id)
    api.client = client
    calls: list[str] = []

    def fake_get(url: str, **kwargs):
        calls.append(url)
        raise ConnectTimeout("持续连接超时")

    monkeypatch.setattr(client_auth_module.requests, "get", fake_get)

    with pytest.raises(client_auth_module.AppException):
        api.get_result_by_fileId({"fileId": "file-001"})

    assert len(calls) == client_auth_module.UPSTREAM_REQUEST_RETRY_ATTEMPTS


def import_client_model():
    from aiSelfTest.models.client import Client

    return Client
