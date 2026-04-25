"""任务接口测试规格。

当前 `aiSelfTest.api.task` 仍为空实现，本文件用于提前锁定
后续 task 模块需要满足的最小接口验收面。
"""

from __future__ import annotations

import pytest


pytestmark = pytest.mark.skip(reason="task API 尚未实现，当前测试文件用于固定接口验收范围")


def test_task_list_endpoint_returns_items() -> None:
    """应提供任务列表接口。"""


def test_task_create_endpoint_persists_filters_and_schedule() -> None:
    """应支持创建任务并保存筛选条件、调度方式与提示词关联。"""


def test_task_detail_endpoint_returns_task_configuration() -> None:
    """应支持查询任务详情。"""


def test_task_update_endpoint_updates_schedule_and_filters() -> None:
    """应支持更新任务配置。"""


def test_task_delete_endpoint_removes_related_runtime_state() -> None:
    """应支持删除任务并清理关联运行状态。"""


def test_task_run_endpoint_executes_manual_run() -> None:
    """应支持手动触发一次任务执行。"""
