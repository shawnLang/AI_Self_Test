"""客户端认证与鉴权请求服务。"""

from __future__ import annotations

from dataclasses import dataclass
from time import time
from typing import Any, Optional
from urllib.parse import urljoin

import requests
from loguru import logger
from requests import Response
from requests.exceptions import RequestException
from sqlmodel import Session

from aiSelfTest.config import get_settings
from aiSelfTest.exceptions import AppException, ErrorCode
from aiSelfTest.models.client import Client
from aiSelfTest.services.client import get_client_or_raise

TOKEN_ERROR_KEYWORDS = ("token", "令牌", "授权")
TOKEN_REUSE_BUFFER_SECONDS = 60
SECONDS_EPOCH_THRESHOLD = 1_000_000_000
MILLISECONDS_EPOCH_THRESHOLD = 1_000_000_000_000
UPSTREAM_REQUEST_RETRY_ATTEMPTS = 3
UPSTREAM_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
LOGIN_PATH = "/auth/login"
REFRESH_PATH = "/auth/refresh"
TENANT_CONFIG_PATH_TEMPLATE = "/sys/sysTenantConfig/getByCode/{code}"
UPSTREAM_FILE_PAGE_PATH = "/openApi/icFile/findFilePage"
UPSTREAM_FILE_DETAIL_PATH = "/openApi/icFile/getResultDetByFileId"
UPSTREAM_FILE_AI_POLLING_RESULT_PATH = "/openApi/icFile/aiPollingResult"


@dataclass
class ClientAuthenticationResult:
    """客户端认证结果。"""

    client: Client
    used_strategy: str


class ClientUtils:
    @staticmethod
    def resolve_expires_at(expires_in: Any) -> int | None:
        """将上游过期字段统一转换为绝对秒级时间戳。"""

        if expires_in is None:
            return None

        expires_value = int(expires_in)
        if expires_value >= MILLISECONDS_EPOCH_THRESHOLD:
            return expires_value // 1000
        if expires_value >= SECONDS_EPOCH_THRESHOLD:
            return expires_value
        return int(time() + expires_value)

    @staticmethod
    def will_expire_soon(expires_at: int | None) -> bool:
        """判断 token 是否已过期或即将过期。"""

        if expires_at is None:
            return True

        return expires_at - time() <= TOKEN_REUSE_BUFFER_SECONDS

    @staticmethod
    def is_access_token_usable(client: Client) -> bool:
        """判断 access token 是否可直接复用。"""

        return bool(client.access_token) and not ClientUtils.will_expire_soon(client.expires_at)

    @staticmethod
    def response_contains_token_error(response: Response) -> bool:
        """判断响应是否包含 token 相关错误。"""

        response_text = (response.text or "").lower()
        if any(keyword in response_text for keyword in TOKEN_ERROR_KEYWORDS):
            return True

        try:
            payload = response.json()
        except Exception:  # noqa: BLE001
            return False
        if not isinstance(payload, dict):
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

    @staticmethod
    def build_url(base_url: str, path: str) -> str:
        """拼接上游请求 URL。"""

        normalized_base_url = base_url.rstrip("/") + "/"
        return urljoin(normalized_base_url, path.lstrip("/"))

    @staticmethod
    def is_same_logical_path(cached_path: str | None, path: str) -> bool:
        """判断缓存路径是否属于同一个逻辑接口。"""

        if not cached_path:
            return False
        return cached_path.strip("/") == path.strip("/")

    @staticmethod
    def toggle_leading_slash(path: str) -> str:
        """切换路径前导斜杠形式。"""

        return path.lstrip("/") if path.startswith("/") else f"/{path}"

    @staticmethod
    def get_client_auth_status(client: Client) -> str:
        """推导客户端当前认证状态。"""

        if not client.access_token:
            return "未认证"
        if ClientUtils.will_expire_soon(client.expires_at):
            return "即将过期"
        return "已认证"


class ClientApi:
    def __init__(self, session: Session, client_id: int):
        self.session: Session = session
        self.client_id = client_id
        self.client: Optional[Client] = None

    def client_login(self):
        if self.client is None:
            raise AppException(code=ErrorCode.INTERNAL_ERROR, message=f"客户端登录为空", status_code=502)
        login_payload = {
            "userName": self.client.account,
            "password": self.client.password,
            "clientType": "WEB",
        }
        login_url = ClientUtils.build_url(self.client.api_url, LOGIN_PATH)
        try:
            logger.info("开始调用客户端登录接口: client_id={} url={} payload={}", self.client_id, login_url, login_payload)
            response = requests.post(login_url, json=login_payload, timeout=get_settings().request_timeout_seconds)
        except RequestException as exc:
            logger.warning(
                "客户端登录请求异常: client_id={} url={} payload={} error={}",
                self.client_id,
                login_url,
                login_payload,
                exc,
            )
            raise AppException(code=ErrorCode.INTERNAL_ERROR, message=f"客户端登录请求失败: {exc}",
                               status_code=502) from exc

        if response.status_code != 200:
            logger.warning(
                "客户端登录失败: client_id={} url={} payload={} status={} body={}",
                self.client_id,
                login_url,
                login_payload,
                response.status_code,
                response.text,
            )
            raise AppException(code=ErrorCode.AUTH_FAILED, message=f"客户端登录失败: {response.text}", status_code=401)
        self.update_client_tokens(response.json())
        return ClientAuthenticationResult(client=self.client, used_strategy="login")

    def refresh_client_token(self) -> ClientAuthenticationResult | None:
        """尝试使用刷新令牌续期。"""
        if self.client is None or not self.client.refresh_token:
            raise AppException(code=ErrorCode.AUTH_FAILED, message="缺少可用的认证令牌", status_code=401)
        headers = {
            "Authorization": self.client.refresh_token
        }
        timeout = get_settings().request_timeout_seconds
        refresh_url = ClientUtils.build_url(self.client.api_url, REFRESH_PATH)
        try:
            logger.info("开始调用客户端刷新token接口: client_id={} url={} headers={}", self.client_id, refresh_url, headers)
            response = requests.post(refresh_url, headers=headers, timeout=timeout)
            if response is not None and response.status_code == 200:
                self.update_client_tokens(response.json())
                return ClientAuthenticationResult(client=self.client, used_strategy="refresh")
        except RequestException as exc:
            msg = f"客户端刷新token异常: client_id={self.client_id} url={refresh_url} headers={headers} error={exc}"
            logger.warning(msg)
            raise AppException(code=ErrorCode.INTERNAL_ERROR, message=msg, status_code=502)
        if response is not None:
            logger.warning(
                "客户端刷新token失败: client_id={} url={} headers={} status={} body={}",
                self.client_id,
                refresh_url,
                headers,
                response.status_code,
                response.text,
            )
        return None

    def authenticate_client_model(self, force_reauthenticate: bool = False) -> ClientAuthenticationResult:
        """对客户端模型执行认证。"""

        if self.client is None:
            self.client = get_client_or_raise(self.session, self.client_id)

        if self.client is None or self.client.status != "启用":
            raise AppException(code=ErrorCode.PERMISSION_DENIED, message="客户端已停用，无法进行认证", status_code=400)

        if not force_reauthenticate and ClientUtils.is_access_token_usable(self.client):
            if self._fill_tenant_name_once():
                self.session.add(self.client)
                self.session.commit()
                self.session.refresh(self.client)
            return ClientAuthenticationResult(client=self.client, used_strategy="reuse")

        if self.client.refresh_token:
            try:
                logger.info(f"尝试刷新客户端 token: client_id={self.client_id}")
                refresh_result = self.refresh_client_token()
            except AppException as exc:
                logger.warning("客户端刷新令牌发生异常，将回退完整登录: {}", exc.message)
                refresh_result = None
            if refresh_result is not None:
                return refresh_result

        logger.info(f"执行客户端完整登录: client_id={self.client_id}")
        return self.client_login()

    def update_client_tokens(self, payload: dict[str, Any]) -> None:
        """将上游 token 信息写回数据库。"""

        access_token = payload.get("accessToken")
        refresh_token = payload.get("refreshToken")
        expires_in = payload.get("expiresIn")
        tenant_code = str(payload.get("tenantCode") or "").strip()

        if not access_token:
            raise AppException(code=ErrorCode.AUTH_FAILED, message="上游认证返回缺少 accessToken", status_code=502)

        self.client.access_token = str(access_token)
        self.client.refresh_token = str(refresh_token or self.client.refresh_token or "")
        self.client.expires_at = ClientUtils.resolve_expires_at(expires_in)
        if tenant_code and not self.client.tenant_code:
            self.client.tenant_code = tenant_code
        self._fill_tenant_name_once()
        self.session.add(self.client)
        self.session.commit()
        self.session.refresh(self.client)

    def _fill_tenant_name_once(self) -> bool:
        """租户名称只在未写入时按 tenantCode 获取一次。"""

        if (
                self.client is None
                or getattr(self.client, "tenant_name", "")
                or not getattr(self.client, "tenant_code", "")
        ):
            return False

        path = TENANT_CONFIG_PATH_TEMPLATE.format(code=self.client.tenant_code)
        url = ClientUtils.build_url(self.client.api_url, path)
        try:
            response = requests.get(
                url,
                headers={"Authorization": self.client.access_token},
                timeout=get_settings().request_timeout_seconds,
            )
        except RequestException as exc:
            logger.warning("租户信息请求异常: client_id={}, tenant_code={}, error={}",
                           self.client_id, self.client.tenant_code, exc)
            return False

        if response.status_code != 200:
            logger.warning(
                "租户信息请求失败: client_id={}, tenant_code={}, status={}, body={}",
                self.client_id,
                self.client.tenant_code,
                response.status_code,
                response.text,
            )
            return False

        try:
            payload = response.json()
        except ValueError:
            logger.warning("租户信息接口返回非 JSON: client_id={}, body={}", self.client_id, response.text)
            return False

        tenant_name = str(payload.get("name") or "").strip()
        if tenant_name:
            self.client.tenant_name = tenant_name
            return True
        return False

    def clear_client_tokens(self):
        """
        清除登录token
        :return:
        """
        logger.warning("客户端清除登录token")
        self.client.access_token = ""
        self.client.refresh_token = ""
        self.client.expires_at = None
        self.session.add(self.client)
        self.session.commit()
        self.session.refresh(self.client)

    def post_with_retry(self, path: str, headers: dict[str, str], params: dict[str, Any],
                        method: str = "POST") -> Response:
        """调用上游接口，并对临时失败执行有限重试。"""

        timeout = get_settings().request_timeout_seconds
        last_exception: RequestException | None = None

        for attempt in range(1, UPSTREAM_REQUEST_RETRY_ATTEMPTS + 1):
            try:
                logger.info(
                    "开始调用上游接口: client_id={} method={} path={} params={} attempt={}/{}",
                    self.client_id,
                    method.upper(),
                    path,
                    params,
                    attempt,
                    UPSTREAM_REQUEST_RETRY_ATTEMPTS,
                )
                if method.upper() == "GET":
                    response = requests.get(path, headers=headers, timeout=timeout, params=params)
                else:
                    response = requests.post(path, headers=headers, timeout=timeout, json=params)
                if response.status_code == 401 or ClientUtils.response_contains_token_error(response):
                    last_exception = RequestException("登录失效")
                    logger.warning(
                        "客户端 token 已失效，准备重新登录后重试: client_id={}, method={}, path={}, "
                        "params={}, attempt={}/{}, status={}, body={}",
                        self.client_id,
                        method.upper(),
                        path,
                        params,
                        attempt,
                        UPSTREAM_REQUEST_RETRY_ATTEMPTS,
                        response.status_code,
                        response.text,
                    )
                    self.clear_client_tokens()
                    auth_result = self.authenticate_client_model(force_reauthenticate=True)
                    headers["Authorization"] = auth_result.client.access_token
                    continue
            except RequestException as exc:
                last_exception = exc
                logger.warning(
                    "客户端请求异常，将按需重试: client_id={}, method={}, path={}, params={}, "
                    "attempt={}/{}, error={}",
                    self.client_id,
                    method.upper(),
                    path,
                    params,
                    attempt,
                    UPSTREAM_REQUEST_RETRY_ATTEMPTS,
                    exc,
                )
                continue

            if response.status_code not in UPSTREAM_RETRYABLE_STATUS_CODES:
                if response.status_code != 200:
                    logger.warning(
                        "客户端接口返回非成功状态: client_id={}, method={}, path={}, params={}, status={}, body={}",
                        self.client_id,
                        method.upper(),
                        path,
                        params,
                        response.status_code,
                        response.text,
                    )
                return response

            logger.warning(
                "客户端返回临时失败，将按需重试: client_id={}, method={}, path={}, "
                "params={}, attempt={}/{}, status={}, body={}",
                self.client_id,
                method.upper(),
                path,
                params,
                attempt,
                UPSTREAM_REQUEST_RETRY_ATTEMPTS,
                response.status_code,
                response.text,
            )

            if attempt == UPSTREAM_REQUEST_RETRY_ATTEMPTS:
                return response

        msg = f"客户端请求失败: client_id={self.client_id}, path={path}, error={last_exception}"
        raise AppException(code=ErrorCode.INTERNAL_ERROR, message=msg, status_code=502) from last_exception

    def find_file_page(self, params: dict[str, Any]) -> Response:
        """
        查询分页数据
        :param params:
        :return:
        """
        auth_result = self.authenticate_client_model()
        headers = {
            "Authorization": auth_result.client.access_token
        }
        path = ClientUtils.build_url(auth_result.client.api_url, UPSTREAM_FILE_PAGE_PATH)
        response = self.post_with_retry(path, headers, params)
        return response

    def get_result_by_fileId(self, params: dict[str, Any]) -> Response:
        auth_result = self.authenticate_client_model()
        headers = {
            "Authorization": auth_result.client.access_token
        }
        path = ClientUtils.build_url(auth_result.client.api_url, UPSTREAM_FILE_DETAIL_PATH)
        response = self.post_with_retry(path, headers, params, method="GET")
        return response

    def update_ai_polling_result(self, params: dict[str, Any]) -> Response:
        """更新上游 AI 巡检结果。"""

        auth_result = self.authenticate_client_model()
        headers = {
            "Authorization": auth_result.client.access_token
        }
        path = ClientUtils.build_url(auth_result.client.api_url, UPSTREAM_FILE_AI_POLLING_RESULT_PATH)
        response = self.post_with_retry(path, headers, params)
        return response


def authenticate_client(session: Session, client_id: int) -> ClientAuthenticationResult:
    """确保客户端持有可用的访问令牌。"""
    client_auth = ClientApi(session, client_id)
    return client_auth.authenticate_client_model()
