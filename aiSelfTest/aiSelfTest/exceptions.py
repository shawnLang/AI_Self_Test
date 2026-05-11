"""全局异常处理器。"""
from enum import IntEnum
from functools import lru_cache
import importlib
import inspect
from typing import Any, Union

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from loguru import logger
from pydantic import BaseModel, ValidationError
from pydantic_core import ErrorDetails


class ErrorCode(IntEnum):
    """统一业务错误码。"""

    SUCCESS = 0
    PARAM_INVALID = 1001
    NOT_FOUND = 1002
    EXISTS = 1003
    AUTH_FAILED = 2001
    PERMISSION_DENIED = 2002
    TOKEN_EXPIRED = 2003
    TASK_FAILED = 3001
    RESOURCE_BUSY = 3002
    INTERNAL_ERROR = 5001


class AppException(Exception):
    """统一业务异常。"""

    def __init__(self, code: Union[ErrorCode, int], message: str, status_code: int, data: Any = None) -> None:
        """保存业务错误码、用户可读消息和 HTTP 状态码。"""

        self.code = int(code)
        self.message = message
        self.status_code = status_code
        self.data = data
        super().__init__(message)


def get_field_display_name(field: str) -> str:
    """获取字段的中文显示名称。"""
    schema_description = _get_schema_field_descriptions().get(field)
    if schema_description:
        return schema_description

    field_map = {
        "username": "用户名",
        "password": "密码",
        "email": "邮箱",
        "role_ids": "角色",
        "is_active": "状态",
        "old_password": "原密码",
        "new_password": "新密码",
        "confirm_password": "确认密码",
        "remember_me": "记住我",
        "action": "操作类型",
        "resource": "资源类型",
        "detail": "详情",
        "name": "名称",
        "description": "描述",
        "apiUrl": "API 地址",
        "endpointUrl": "模型地址",
        "account": "账号",
        "modelName": "模型名称",
        "apiKey": "API Key",
        "detectedModels": "已探测模型",
        "messages": "消息列表",
        "status": "状态",
        "remark": "备注",
        "text": "提示词",
        "format": "解析格式",
    }
    return field_map.get(field, field)


@lru_cache(maxsize=1)
def _get_schema_field_descriptions() -> dict[str, str]:
    """从 Pydantic schema 字段描述中收集中文字段名。"""

    descriptions: dict[str, str] = {}
    schema_modules = (
        "aiSelfTest.schemas.client",
        "aiSelfTest.schemas.config",
        "aiSelfTest.schemas.multimodal_model",
        "aiSelfTest.schemas.task",
        "aiSelfTest.schemas.dashboard",
    )
    for module_name in schema_modules:
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue

        for _, model_class in inspect.getmembers(module, inspect.isclass):
            if not issubclass(model_class, BaseModel):
                continue
            for field_name, field_info in model_class.model_fields.items():
                description = field_info.description
                if not description:
                    continue
                descriptions.setdefault(field_name, description)
                if field_info.alias:
                    descriptions.setdefault(str(field_info.alias), description)

    return descriptions


def parse_validation_error(error: ErrorDetails) -> str:
    """解析单个验证错误，返回人性化的错误消息。"""
    error_type = error.get("type", "")
    loc = error.get("loc", [])
    ctx = error.get("ctx", {})

    # 获取字段名（最后一个 loc）
    field = str(loc[-1]) if loc else "字段"
    field_name = get_field_display_name(field)

    # 根据错误类型返回中文提示
    if error_type == "string_too_short":
        min_length = ctx.get("min_length", 0)
        return f"{field_name}长度不能少于 {min_length} 个字符"
    elif error_type == "string_too_long":
        max_length = ctx.get("max_length", 0)
        return f"{field_name}长度不能超过 {max_length} 个字符"
    elif error_type == "missing":
        return f"{field_name}不能为空"
    elif error_type == "value_error":
        return f"{field_name}格式不正确"
    elif error_type == "type_error":
        return f"{field_name}类型错误"
    elif error_type.startswith("int_"):
        return f"{field_name}必须是整数"
    elif error_type.startswith("bool_"):
        return f"{field_name}必须是布尔值"
    elif error_type.startswith("list_"):
        return f"{field_name}必须是列表"
    elif error_type == "string_pattern_mismatch":
        return f"{field_name}格式不符合要求"
    elif error_type == "greater_than":
        gt = ctx.get("gt", 0)
        return f"{field_name}必须大于 {gt}"
    elif error_type == "greater_than_equal":
        ge = ctx.get("ge", 0)
        return f"{field_name}必须大于等于 {ge}"
    elif error_type == "less_than":
        lt = ctx.get("lt", 0)
        return f"{field_name}必须小于 {lt}"
    elif error_type == "less_than_equal":
        le = ctx.get("le", 0)
        return f"{field_name}必须小于等于 {le}"
    else:
        # 使用原始错误消息
        msg = error.get("msg", "验证失败")
        return f"{field_name}: {msg}"


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """处理请求验证错误，返回人性化的中文提示。"""
    errors = exc.errors()
    error_messages = []

    for error in errors:
        error_messages.append(parse_validation_error(error))

    # 合并所有错误消息
    detail = "；".join(error_messages)

    logger.warning(f"请求验证失败: {detail}, path={request.url.path}")

    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "code": ErrorCode.PARAM_INVALID,
            "message": detail,
            "data": None
        }
    )


async def pydantic_validation_exception_handler(
    request: Request, exc: ValidationError
) -> JSONResponse:
    """处理 Pydantic 验证错误。"""
    errors = exc.errors()
    error_messages = []

    for error in errors:
        error_messages.append(parse_validation_error(error))

    detail = "；".join(error_messages)

    logger.warning(f"数据验证失败: {detail}, path={request.url.path}")

    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "code": ErrorCode.PARAM_INVALID,
            "message": detail,
            "data": None
        }
    )


async def app_exception_handler(
    request: Request,
    exc: AppException,
) -> JSONResponse:
    """处理统一业务异常。"""

    logger.warning(f"业务处理失败: {exc.message}, path={request.url.path}")
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": exc.code,
            "message": exc.message,
            "data": exc.data,
        },
    )
