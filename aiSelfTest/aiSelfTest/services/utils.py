from datetime import datetime
from typing import Any, Optional


def optional_float(value: Any) -> Optional[float]:
    """把可选数值转换为浮点数，无法转换时返回 None。"""

    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def truncate(value: str, max_length: int) -> str:
    """按数据库字段长度截断字符串。"""

    return value[:max_length]


def format_dt(value: datetime) -> str:
    """统一格式化任务执行窗口时间。"""

    return value.strftime("%Y-%m-%d %H:%M:%S")


def clip_end_at(end_at: str, now: datetime) -> str:
    """把结束时间裁剪到当前时间，避免自动任务拉取未来窗口。"""

    if not end_at:
        return format_dt(now)
    parsed = parse_window_end(end_at)
    if parsed and parsed < now:
        return format_dt(parsed)
    return format_dt(now)


def parse_window_end(value: str) -> Optional[datetime]:
    """兼容解析日期或 ISO 时间格式的窗口结束时间。"""

    if not value:
        return None
    normalized = value.strip().replace("Z", "+00:00")
    if len(normalized) == 10:
        normalized = f"{normalized} 23:59:59"
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None
