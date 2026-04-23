"""通用响应模型。"""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel


DataT = TypeVar("DataT")


class ApiResponse(BaseModel, Generic[DataT]):
    """统一 API 响应结构。"""

    code: int
    message: str
    data: DataT | None = None


class EmptyData(BaseModel):
    """空数据响应占位。"""

    pass
