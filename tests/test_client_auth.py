"""客户端认证能力测试。"""

from __future__ import annotations

import importlib
import time
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
    auth_header_style: str | None = None,
    working_url_path: str | None = None,
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
        auth_header_style=auth_header_style,
        working_url_path=working_url_path,
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
    calls: list[tuple[str, str, dict[str, Any] | None, dict[str, str] | None]] = []

    def fake_request(method: str, url: str, **kwargs):
        calls.append((method, url, kwargs.get("json"), kwargs.get("headers")))
        if url.endswith("/auth/login"):
            return FakeResponse(
                200,
                {
                    "accessToken": "login-access-token",
                    "refreshToken": "login-refresh-token",
                    "expiresIn": 3600,
                },
            )
        raise AssertionError(f"未预期的请求: {method} {url}")

    monkeypatch.setattr(client_auth_module.requests, "request", fake_request)

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
    assert calls[0][0] == "POST"
    assert calls[0][1].endswith("/auth/login")
    assert calls[0][2] == {
        "userName": "frog-admin",
        "password": "secret-123",
        "clientType": "WEB",
    }


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
    calls: list[tuple[str, str, dict[str, str] | None]] = []

    def fake_request(method: str, url: str, **kwargs):
        calls.append((method, url, kwargs.get("headers")))
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
        raise AssertionError(f"未预期的请求: {method} {url}")

    monkeypatch.setattr(client_auth_module.requests, "request", fake_request)

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
    calls: list[tuple[str, str]] = []

    def fake_request(method: str, url: str, **kwargs):
        calls.append((method, url))
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
        raise AssertionError(f"未预期的请求: {method} {url}")

    monkeypatch.setattr(client_auth_module.requests, "request", fake_request)

    response = app_client.post(f"/api/clients/authenticate/{client.id}")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["usedStrategy"] == "login"
    assert [url for _, url in calls] == [
        "https://example.com/auth/refresh",
        "https://example.com/auth/refresh",
        "https://example.com/auth/login",
    ]


def test_perform_authenticated_request_supports_bearer_fallback(
    db_session: Session,
    monkeypatch,
) -> None:
    client = _create_client(
        db_session,
        access_token="plain-token",
        refresh_token="refresh-token",
        expires_at=_future_timestamp(),
    )
    client_auth_module = importlib.import_module("aiSelfTest.services.client_auth")
    calls: list[str] = []

    def fake_request(method: str, url: str, **kwargs):
        authorization = kwargs["headers"]["Authorization"]
        calls.append(authorization)
        if authorization == "plain-token":
            return FakeResponse(401, {"message": "token invalid"}, "token invalid")
        if authorization == "Bearer plain-token":
            return FakeResponse(200, {"results": []})
        raise AssertionError(f"未预期的 Authorization: {authorization}")

    monkeypatch.setattr(client_auth_module.requests, "request", fake_request)

    response = client_auth_module.perform_authenticated_request(
        db_session,
        client.id,
        "POST",
        "/openApi/icFile/findFilePage",
        json={"size": 10, "current": 1},
    )

    assert response.status_code == 200
    assert calls == ["plain-token", "Bearer plain-token"]
    db_session.expire_all()
    refreshed_client = db_session.exec(
        select(import_client_model()).where(import_client_model().id == client.id)
    ).one()
    assert refreshed_client.auth_header_style == "bearer"
    assert refreshed_client.working_url_path == "/openApi/icFile/findFilePage"


def test_perform_authenticated_request_uses_cached_authorization_style(
    db_session: Session,
    monkeypatch,
) -> None:
    client = _create_client(
        db_session,
        access_token="cached-token",
        refresh_token="refresh-token",
        expires_at=_future_timestamp(),
        auth_header_style="bearer",
        working_url_path="/openApi/icFile/findFilePage",
    )
    client_auth_module = importlib.import_module("aiSelfTest.services.client_auth")
    calls: list[str] = []

    def fake_request(method: str, url: str, **kwargs):
        authorization = kwargs["headers"]["Authorization"]
        calls.append(authorization)
        return FakeResponse(200, {"results": []})

    monkeypatch.setattr(client_auth_module.requests, "request", fake_request)

    response = client_auth_module.perform_authenticated_request(
        db_session,
        client.id,
        "POST",
        "/openApi/icFile/findFilePage",
        json={"size": 10, "current": 1},
    )

    assert response.status_code == 200
    assert calls == ["Bearer cached-token"]


def test_perform_authenticated_request_reauthenticates_when_token_invalid(
    db_session: Session,
    monkeypatch,
) -> None:
    client = _create_client(
        db_session,
        access_token="stale-token",
        refresh_token="refresh-token",
        expires_at=_future_timestamp(),
    )
    client_auth_module = importlib.import_module("aiSelfTest.services.client_auth")
    calls: list[tuple[str, str, str | None]] = []

    def fake_request(method: str, url: str, **kwargs):
        authorization = (kwargs.get("headers") or {}).get("Authorization")
        calls.append((method, url, authorization))

        if url.endswith("/openApi/icFile/findFilePage"):
            if authorization in ("stale-token", "Bearer stale-token"):
                return FakeResponse(401, {"message": "token invalid"}, "token invalid")
            if authorization == "fresh-token":
                return FakeResponse(200, {"results": []})
            raise AssertionError(f"未预期的业务请求 Authorization: {authorization}")

        if url.endswith("/auth/refresh"):
            return FakeResponse(401, {"message": "refresh token invalid"}, "refresh token invalid")

        if url.endswith("/auth/login"):
            return FakeResponse(
                200,
                {
                    "accessToken": "fresh-token",
                    "refreshToken": "fresh-refresh-token",
                    "expiresIn": 3600,
                },
            )

        raise AssertionError(f"未预期的请求: {method} {url}")

    monkeypatch.setattr(client_auth_module.requests, "request", fake_request)

    response = client_auth_module.perform_authenticated_request(
        db_session,
        client.id,
        "POST",
        "/openApi/icFile/findFilePage",
        json={"size": 10, "current": 1},
    )

    assert response.status_code == 200
    refreshed_client = db_session.exec(
        select(import_client_model()).where(import_client_model().id == client.id)
    ).one()
    assert refreshed_client.access_token == "fresh-token"
    assert any(url.endswith("/auth/login") for _, url, _ in calls)


def import_client_model():
    from aiSelfTest.models.client import Client

    return Client
