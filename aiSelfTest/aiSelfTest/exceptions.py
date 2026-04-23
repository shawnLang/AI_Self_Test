"""全局异常处理器。"""
from typing import Any

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from loguru import logger
from pydantic import ValidationError


def get_field_display_name(field: str) -> str:
    """获取字段的中文显示名称。"""
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
    }
    return field_map.get(field, field)


def parse_validation_error(error: dict[str, Any]) -> str:
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
            "code": 1001,  # 参数错误
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
            "code": 1001,
            "message": detail,
            "data": None
        }
    )
