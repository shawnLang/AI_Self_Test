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
from aiSelfTest.exceptions import AppException, ErrorCode
from aiSelfTest.models.client import Client
from aiSelfTest.schemas.client import ClientResponse
from aiSelfTest.services.client import get_client_or_raise


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

    client = get_client_or_raise(session, client_id)
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
    client = get_client_or_raise(session, client_id)
    logger.debug(
        "准备发起认证上游请求: client_id={}, method={}, path={}, retry_on_auth_failure={}",
        client_id,
        method,
        path,
        retry_on_auth_failure,
    )
    auth_result = _authenticate_client_model(session, client, request_func=request_impl)
    response = _request_with_cached_paths(
        session=session,
        client=auth_result.client,
        request_impl=request_impl,
        method=method,
        token=auth_result.client.access_token,
        path=path,
        **kwargs,
    )

    if response.status_code != 401 and not _response_contains_token_error(response):
        logger.debug(
            "认证上游请求完成: client_id={}, method={}, path={}, status={}",
            client_id,
            method,
            path,
            response.status_code,
        )
        return response

    if not retry_on_auth_failure:
        logger.warning(
            "认证上游请求疑似 token 失效但未重试: client_id={}, method={}, path={}, status={}",
            client_id,
            method,
            path,
            response.status_code,
        )
        return response

    logger.warning("检测到上游 token 失效，准备重新认证后重试请求: client_id={}, path={}", client_id, path)
    reauth_result = _authenticate_client_model(
        session,
        client,
        request_func=request_impl,
        force_reauthenticate=True,
    )
    return _request_with_cached_paths(
        session=session,
        client=reauth_result.client,
        request_impl=request_impl,
        method=method,
        token=reauth_result.client.access_token,
        path=path,
        **kwargs,
    )


def get_client_auth_status(client: Client) -> str:
    """推导客户端当前认证状态。"""

    if not client.access_token:
        return "未认证"
    if _will_expire_soon(client.expires_at):
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
            code=ErrorCode.PERMISSION_DENIED,
            message="客户端已停用，无法进行认证",
            status_code=400,
        )

    if not force_reauthenticate and _is_access_token_usable(client):
        logger.debug("复用客户端 access token: client_id={}", client.id)
        return ClientAuthenticationResult(client=client, used_strategy="reuse")

    if client.refresh_token:
        try:
            logger.info("尝试刷新客户端 token: client_id={}", client.id)
            refresh_result = _refresh_client_token(
                session,
                client,
                request_func=request_impl,
            )
        except AppException as exc:
            logger.warning("客户端刷新令牌发生异常，将回退完整登录: {}", exc.message)
            refresh_result = None
        if refresh_result is not None:
            logger.info("客户端 token 刷新成功: client_id={}", client.id)
            return refresh_result

    logger.info("执行客户端完整登录: client_id={}", client.id)
    return _login_client(session, client, request_func=request_impl)


def _refresh_client_token(
    session: Session,
    client: Client,
    *,
    request_func: RequestFunc,
) -> ClientAuthenticationResult | None:
    """尝试使用刷新令牌续期。"""

    response = _request_with_authorization_variants(
        session=session,
        client=client,
        request_impl=request_func,
        method="POST",
        url=_build_url(client.api_url, REFRESH_PATH),
        token=client.refresh_token,
        path=REFRESH_PATH,
    )
    if response.status_code == 200:
        _update_client_tokens(session, client, response.json())
        logger.info("客户端刷新令牌成功: client_id={}, status={}", client.id, response.status_code)
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
        logger.warning("客户端登录请求异常: client_id={}, error={}", client.id, exc)
        raise AppException(
            code=ErrorCode.INTERNAL_ERROR,
            message=f"客户端登录请求失败: {exc}",
            status_code=502,
        ) from exc

    if response.status_code != 200:
        logger.warning("客户端登录失败: client_id={}, status={}", client.id, response.status_code)
        raise AppException(
            code=ErrorCode.AUTH_FAILED,
            message=f"客户端登录失败: {response.text}",
            status_code=401,
        )

    _update_client_tokens(session, client, response.json())
    logger.info("客户端登录成功: client_id={}", client.id)
    return ClientAuthenticationResult(client=client, used_strategy="login")


def _request_with_authorization_variants(
    *,
    session: Session,
    client: Client,
    request_impl: RequestFunc,
    method: str,
    url: str,
    token: str | None,
    path: str,
    **kwargs: Any,
) -> Response:
    """按两种 Authorization 形式依次请求。"""

    if not token:
        raise AppException(
            code=ErrorCode.AUTH_FAILED,
            message="缺少可用的认证令牌",
            status_code=401,
        )

    response: Response | None = None
    errors: list[str] = []
    base_headers = dict(kwargs.get("headers", {}) or {})
    request_kwargs = dict(kwargs)
    request_kwargs.pop("headers", None)
    timeout = request_kwargs.pop("timeout", get_settings().request_timeout_seconds)
    for style, authorization in _authorization_variants(token, client.auth_header_style):
        headers = dict(base_headers)
        headers["Authorization"] = authorization
        try:
            logger.debug(
                "发起上游认证请求: client_id={}, method={}, path={}, auth_style={}",
                client.id,
                method,
                path,
                style,
            )
            response = request_impl(
                method,
                url,
                headers=headers,
                timeout=timeout,
                **request_kwargs,
            )
        except RequestException as exc:
            logger.warning(
                "上游认证请求异常: client_id={}, method={}, path={}, auth_style={}, error={}",
                client.id,
                method,
                path,
                style,
                exc,
            )
            errors.append(str(exc))
            continue

        if response.status_code == 200:
            _cache_successful_request(session, client, style, path)
            logger.debug(
                "上游认证请求成功: client_id={}, method={}, path={}, auth_style={}, status={}",
                client.id,
                method,
                path,
                style,
                response.status_code,
            )
            return response

        if response.status_code != 401 and not _response_contains_token_error(response):
            logger.debug(
                "上游请求返回非认证错误状态: client_id={}, method={}, path={}, status={}",
                client.id,
                method,
                path,
                response.status_code,
            )
            return response

    if response is not None:
        return response

    raise AppException(
        code=ErrorCode.INTERNAL_ERROR,
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
            code=ErrorCode.AUTH_FAILED,
            message="上游认证返回缺少 accessToken",
            status_code=502,
        )

    client.access_token = str(access_token)
    client.refresh_token = str(refresh_token or client.refresh_token or "")
    client.expires_at = _resolve_expires_at(expires_in)
    session.add(client)
    session.commit()
    session.refresh(client)
    logger.info("客户端 token 已更新: client_id={}, expires_at={}", client.id, client.expires_at)


def _request_with_cached_paths(
    *,
    session: Session,
    client: Client,
    request_impl: RequestFunc,
    method: str,
    path: str,
    token: str | None,
    **kwargs: Any,
) -> Response:
    """按缓存路径优先请求，失败时回退路径候选。"""

    response: Response | None = None
    for candidate_path in _request_path_candidates(client, path):
        logger.debug("尝试上游请求路径: client_id={}, requested_path={}, candidate_path={}", client.id, path, candidate_path)
        response = _request_with_authorization_variants(
            session=session,
            client=client,
            request_impl=request_impl,
            method=method,
            url=_build_url(client.api_url, candidate_path),
            token=token,
            path=candidate_path,
            **kwargs,
        )
        if response.status_code != 404:
            return response

    if response is not None:
        logger.warning(
            "上游请求所有候选路径均返回 404: client_id={}, requested_path={}, status={}",
            client.id,
            path,
            response.status_code,
        )
        return response

    raise AppException(
        code=ErrorCode.INTERNAL_ERROR,
        message="上游请求失败: 未生成可用路径",
        status_code=502,
    )


def _authorization_variants(
    token: str,
    preferred_style: str | None = None,
) -> list[tuple[str, str]]:
    """生成 Authorization 值候选列表。"""

    styles = ["plain", "bearer"]
    if preferred_style in styles:
        styles.remove(preferred_style)
        styles.insert(0, preferred_style)

    values = {
        "plain": token,
        "bearer": f"Bearer {token}",
    }
    return [(style, values[style]) for style in styles]


def _request_path_candidates(client: Client, path: str) -> list[str]:
    """生成上游请求路径候选，缓存路径优先。"""

    candidates: list[str] = []
    cached_path = (
        client.working_url_path
        if _is_same_logical_path(client.working_url_path, path)
        else None
    )
    for candidate in (cached_path, path, _toggle_leading_slash(path)):
        if not candidate or candidate in candidates:
            continue
        candidates.append(candidate)
    return candidates


def _is_same_logical_path(cached_path: str | None, path: str) -> bool:
    """判断缓存路径是否属于同一个逻辑接口。"""

    if not cached_path:
        return False
    return cached_path.strip("/") == path.strip("/")


def _toggle_leading_slash(path: str) -> str:
    """切换路径前导斜杠形式。"""

    return path.lstrip("/") if path.startswith("/") else f"/{path}"


def _cache_successful_request(
    session: Session,
    client: Client,
    auth_header_style: str,
    path: str,
) -> None:
    """缓存成功的认证头格式与请求路径。"""

    cache_path = path not in (LOGIN_PATH, REFRESH_PATH)
    if client.auth_header_style == auth_header_style and (
        not cache_path or client.working_url_path == path
    ):
        return

    client.auth_header_style = auth_header_style
    if cache_path:
        client.working_url_path = path
    session.add(client)
    session.commit()
    session.refresh(client)
    logger.debug(
        "缓存客户端认证请求参数: client_id={}, auth_header_style={}, cache_path={}",
        client.id,
        auth_header_style,
        path if cache_path else "",
    )


def _resolve_expires_at(expires_in: Any) -> int | None:
    """将上游过期时长转换为绝对秒级时间戳。"""

    if expires_in is None:
        return None
    return int(time() + int(expires_in))


def _is_access_token_usable(client: Client) -> bool:
    """判断 access token 是否可直接复用。"""

    return bool(client.access_token) and not _will_expire_soon(client.expires_at)


def _will_expire_soon(expires_at: int | None) -> bool:
    """判断 token 是否已过期或即将过期。"""

    if expires_at is None:
        return True

    return expires_at - time() <= TOKEN_REUSE_BUFFER_SECONDS


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
