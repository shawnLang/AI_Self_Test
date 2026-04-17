"""Third-party client API authentication and request helpers."""

from __future__ import annotations

import time
from typing import Any

import requests
from sqlmodel import Session

from ..config import get_settings
from ..db.models import Client
from ..logging import log_event
from .utils import trim_trailing_slash


def _safe_json(response: requests.Response) -> Any:
    try:
        return response.json()
    except Exception:
        return {"rawText": response.text}


def _persist_client_auth(session: Session, client: Client, auth_data: dict[str, Any], now_ms: int | None = None) -> str:
    if not auth_data.get("accessToken"):
        raise RuntimeError("Login failed to client API")
    now_ms = now_ms or int(time.time() * 1000)
    client.access_token = auth_data["accessToken"]
    client.refresh_token = auth_data.get("refreshToken")
    client.expires_in = int(auth_data.get("expiresIn") or now_ms + 86400000)
    session.add(client)
    session.commit()
    session.refresh(client)
    return client.access_token or ""


def login_client(session: Session, client: Client) -> str:
    settings = get_settings()
    url = f"{trim_trailing_slash(client.api_url)}/auth/login"
    response = requests.post(
        url,
        json={"userName": client.account, "password": client.password, "clientType": "WEB"},
        timeout=settings.request_timeout_seconds,
    )
    data = _safe_json(response)
    log_event("external_client_auth", "client login attempted", client_id=client.id, status=response.status_code)
    return _persist_client_auth(session, client, data)


def refresh_client_token(session: Session, client: Client) -> str | None:
    if not client.refresh_token:
        return None
    settings = get_settings()
    url = f"{trim_trailing_slash(client.api_url)}/auth/refresh"
    try:
        response = requests.post(
            url,
            headers={"Authorization": client.refresh_token, "Content-Type": "application/json"},
            timeout=settings.request_timeout_seconds,
        )
        data = _safe_json(response)
        if not data.get("accessToken"):
            return None
        log_event("external_client_auth", "client token refreshed", client_id=client.id, status=response.status_code)
        return _persist_client_auth(session, client, data)
    except Exception:
        return None


def ensure_client_access_token(session: Session, client: Client) -> str:
    now_ms = int(time.time() * 1000)
    current_token = str(client.access_token or "").strip()
    if current_token and client.expires_in and now_ms <= int(client.expires_in) - 3600 * 1000:
        return current_token
    refreshed = refresh_client_token(session, client)
    if refreshed:
        return refreshed
    return login_client(session, client)


def is_client_token_error(response: requests.Response, result_data: Any) -> bool:
    message = str(result_data.get("message") if isinstance(result_data, dict) else "").lower()
    return response.status_code == 401 or "token" in message


def request_client_api(
    session: Session,
    client: Client,
    path: str,
    *,
    method: str = "GET",
    body: Any = None,
    query: dict[str, Any] | None = None,
) -> tuple[requests.Response, Any]:
    settings = get_settings()
    access_token = ensure_client_access_token(session, client)
    base_url = trim_trailing_slash(client.api_url)
    url = f"{base_url}{path}"
    method = method.upper()

    def make_request(with_bearer: bool = False) -> tuple[requests.Response, Any]:
        headers = {"Authorization": f"Bearer {access_token}" if with_bearer else access_token}
        if body is not None:
            headers["Content-Type"] = "application/json"
        response = requests.request(
            method,
            url,
            params=query,
            json=body if body is not None else None,
            headers=headers,
            timeout=settings.request_timeout_seconds,
        )
        result = _safe_json(response)
        log_event(
            "external_client_api",
            "client api request completed",
            client_id=client.id,
            path=path,
            status=response.status_code,
        )
        return response, result

    response, result = make_request(False)
    if is_client_token_error(response, result):
        access_token = login_client(session, client)
        response, result = make_request(False)
    if response.status_code == 401:
        response, result = make_request(True)
    return response, result


def assert_client_api_ok(response: requests.Response, result_data: Any, action_name: str) -> None:
    if not response.ok:
        message = ""
        if isinstance(result_data, dict):
            error = result_data.get("error")
            message = (
                (error.get("message") if isinstance(error, dict) else error)
                or result_data.get("message")
                or f"HTTP {response.status_code}"
            )
        raise RuntimeError(f"{action_name}失败: {message or f'HTTP {response.status_code}'}")
