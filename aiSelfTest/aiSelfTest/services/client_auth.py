"""客户端认证与鉴权请求服务。"""

from __future__ import annotations

from dataclasses import dataclass
from time import time
from typing import Any, Callable
from urllib.parse import urljoin

import requests
from loguru import logger
from requests import Response
from requests.exceptions import RequestException
from sqlmodel import Session

from aiSelfTest.config import get_settings
from aiSelfTest.exceptions import AppException
from aiSelfTest.models.client import Client
from aiSelfTest.schemas.client import ClientResponse
from aiSelfTest.services.client import _get_client_or_raise


TOKEN_ERROR_KEYWORDS = ("token", "令牌", "授权")
TOKEN_REUSE_BUFFER_SECONDS = 60
LOGIN_PATH = "/auth/login"
REFRESH_PATH = "/auth/refresh"
RequestFunc = Callable[..., Response]


@dataclass
class ClientAuthenticationResult:
    """客户端认证结果。"""

    client: Client
    used_strategy: str


def authenticate_client(
    session: Session,
    client_id: int,
    *,
    request_func: RequestFunc | None = None,
) -> ClientAuthenticationResult:
    """确保客户端持有可用的访问令牌。"""

    client = _get_client_or_raise(session, client_id)
    return _authenticate_client_model(session, client, request_func=request_func)


def perform_authenticated_request(
    session: Session,
    client_id: int,
    method: str,
    path: str,
    *,
    request_func: RequestFunc | None = None,
    retry_on_auth_failure: bool = True,
    **kwargs: Any,
) -> Response:
    """使用客户端认证信息调用上游业务接口。"""

    request_impl = request_func or requests.request
    client = _get_client_or_raise(session, client_id)
    auth_result = _authenticate_client_model(session, client, request_func=request_impl)
    response = _request_with_authorization_variants(
        request_impl=request_impl,
        method=method,
        url=_build_url(client.api_url, path),
        token=auth_result.client.access_token,
        **kwargs,
    )

    if response.status_code != 401 and not _response_contains_token_error(response):
        return response

    if not retry_on_auth_failure:
        return response

    logger.warning("检测到上游 token 失效，准备重新认证后重试请求")
    reauth_result = _authenticate_client_model(
        session,
        client,
        request_func=request_impl,
        force_reauthenticate=True,
    )
    return _request_with_authorization_variants(
        request_impl=request_impl,
        method=method,
        url=_build_url(client.api_url, path),
        token=reauth_result.client.access_token,
        **kwargs,
    )


def get_client_auth_status(client: Client) -> str:
    """推导客户端当前认证状态。"""

    if not client.access_token:
        return "未认证"
    if _will_expire_soon(client.expires_in):
        return "即将过期"
    return "已认证"


def _authenticate_client_model(
    session: Session,
    client: Client,
    *,
    request_func: RequestFunc | None = None,
    force_reauthenticate: bool = False,
) -> ClientAuthenticationResult:
    """对客户端模型执行认证。"""

    request_impl = request_func or requests.request

    if client.status != "启用":
        raise AppException(
            code=2002,
            message="客户端已停用，无法进行认证",
            status_code=400,
        )

    if not force_reauthenticate and _is_access_token_usable(client):
        return ClientAuthenticationResult(client=client, used_strategy="reuse")

    if client.refresh_token:
        try:
            refresh_result = _refresh_client_token(
                session,
                client,
                request_func=request_impl,
            )
        except AppException as exc:
            logger.warning("客户端刷新令牌发生异常，将回退完整登录: {}", exc.message)
            refresh_result = None
        if refresh_result is not None:
            return refresh_result

    return _login_client(session, client, request_func=request_impl)


def _refresh_client_token(
    session: Session,
    client: Client,
    *,
    request_func: RequestFunc,
) -> ClientAuthenticationResult | None:
    """尝试使用刷新令牌续期。"""

    response = _request_with_authorization_variants(
        request_impl=request_func,
        method="POST",
        url=_build_url(client.api_url, REFRESH_PATH),
        token=client.refresh_token,
    )
    if response.status_code == 200:
        _update_client_tokens(session, client, response.json())
        return ClientAuthenticationResult(client=client, used_strategy="refresh")

    logger.warning(
        "客户端刷新令牌失败: client_id={} status={} body={}",
        client.id,
        response.status_code,
        response.text,
    )
    return None


def _login_client(
    session: Session,
    client: Client,
    *,
    request_func: RequestFunc,
) -> ClientAuthenticationResult:
    """执行完整登录。"""

    login_payload = {
        "userName": client.account,
        "password": client.password,
        "clientType": "WEB",
    }
    try:
        response = request_func(
            "POST",
            _build_url(client.api_url, LOGIN_PATH),
            json=login_payload,
            timeout=get_settings().request_timeout_seconds,
        )
    except RequestException as exc:
        raise AppException(
            code=5001,
            message=f"客户端登录请求失败: {exc}",
            status_code=502,
        ) from exc

    if response.status_code != 200:
        raise AppException(
            code=2001,
            message=f"客户端登录失败: {response.text}",
            status_code=401,
        )

    _update_client_tokens(session, client, response.json())
    return ClientAuthenticationResult(client=client, used_strategy="login")


def _request_with_authorization_variants(
    *,
    request_impl: RequestFunc,
    method: str,
    url: str,
    token: str | None,
    **kwargs: Any,
) -> Response:
    """按两种 Authorization 形式依次请求。"""

    if not token:
        raise AppException(
            code=2001,
            message="缺少可用的认证令牌",
            status_code=401,
        )

    response: Response | None = None
    errors: list[str] = []
    base_headers = dict(kwargs.get("headers", {}) or {})
    request_kwargs = dict(kwargs)
    request_kwargs.pop("headers", None)
    timeout = request_kwargs.pop("timeout", get_settings().request_timeout_seconds)
    for authorization in _authorization_variants(token):
        headers = dict(base_headers)
        headers["Authorization"] = authorization
        try:
            response = request_impl(
                method,
                url,
                headers=headers,
                timeout=timeout,
                **request_kwargs,
            )
        except RequestException as exc:
            errors.append(str(exc))
            continue

        if response.status_code == 200:
            return response

        if response.status_code != 401 and not _response_contains_token_error(response):
            return response

    if response is not None:
        return response

    raise AppException(
        code=5001,
        message=f"上游请求失败: {'; '.join(errors)}",
        status_code=502,
    )


def _update_client_tokens(
    session: Session,
    client: Client,
    payload: dict[str, Any],
) -> None:
    """将上游 token 信息写回数据库。"""

    access_token = payload.get("accessToken")
    refresh_token = payload.get("refreshToken")
    expires_in = payload.get("expiresIn")

    if not access_token:
        raise AppException(
            code=2001,
            message="上游认证返回缺少 accessToken",
            status_code=502,
        )

    client.access_token = str(access_token)
    client.refresh_token = str(refresh_token or client.refresh_token or "")
    client.expires_in = int(expires_in) if expires_in is not None else None
    session.add(client)
    session.commit()
    session.refresh(client)


def _authorization_variants(token: str) -> list[str]:
    """生成 Authorization 值候选列表。"""

    variants = [token]
    bearer_token = f"Bearer {token}"
    if bearer_token not in variants:
        variants.append(bearer_token)
    return variants


def _is_access_token_usable(client: Client) -> bool:
    """判断 access token 是否可直接复用。"""

    return bool(client.access_token) and not _will_expire_soon(client.expires_in)


def _will_expire_soon(expires_in: int | None) -> bool:
    """判断 token 是否已过期或即将过期。"""

    if expires_in is None:
        return True

    expires_at_seconds = expires_in / 1000 if expires_in > 10**11 else expires_in
    return expires_at_seconds - time() <= TOKEN_REUSE_BUFFER_SECONDS


def _response_contains_token_error(response: Response) -> bool:
    """判断响应是否包含 token 相关错误。"""

    response_text = (response.text or "").lower()
    if any(keyword in response_text for keyword in TOKEN_ERROR_KEYWORDS):
        return True

    try:
        payload = response.json()
    except Exception:  # noqa: BLE001
        return False

    messages = [
        str(payload.get("message", "")),
        str(payload.get("error", "")),
        str(payload.get("msg", "")),
    ]
    return any(
        keyword in message.lower()
        for message in messages
        for keyword in TOKEN_ERROR_KEYWORDS
    )


def _build_url(base_url: str, path: str) -> str:
    """拼接上游请求 URL。"""

    normalized_base_url = base_url.rstrip("/") + "/"
    return urljoin(normalized_base_url, path.lstrip("/"))
