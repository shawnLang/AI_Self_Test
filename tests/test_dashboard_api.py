"""仪表盘统计接口测试。"""

from __future__ import annotations

import importlib
from datetime import datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlmodel import Session


def _unwrap_success(response_json: dict[str, Any]) -> Any:
    """提取统一成功响应中的 data 字段。"""

    assert response_json["code"] == 0
    assert response_json["message"] == "success"
    return response_json["data"]


def test_dashboard_stats_returns_zero_values_when_empty(app_client: TestClient) -> None:
    """无任务数据时，总览统计返回空态。"""

    response = app_client.get("/api/dashboard/stats")

    assert response.status_code == 200
    data = _unwrap_success(response.json())
    assert data == {
        "activeTasks": 0,
        "processedToday": 0,
        "pendingReviews": 0,
        "anomalies": 0,
        "recentActivities": [],
    }


def test_dashboard_stats_uses_real_task_and_review_counts(
    app_client: TestClient,
    db_session: Session,
) -> None:
    """总览统计基于任务与任务项真实状态计算。"""

    task_model, task_item_model = _import_task_models()
    client_id, config_id = _create_client_and_config(app_client)
    now = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)

    running_task = task_model(
        name="运行中任务",
        client_id=client_id,
        config_id=config_id,
        execution_status="数据加载",
        total_count=5,
        processed_count=2,
    )
    finished_task = task_model(
        name="最近完成任务",
        client_id=client_id,
        config_id=config_id,
        execution_status="结束",
        total_count=3,
        processed_count=3,
        finished_at=now - timedelta(hours=1),
    )
    older_finished_task = task_model(
        name="较早完成任务",
        client_id=client_id,
        config_id=config_id,
        execution_status="结束",
        total_count=2,
        processed_count=2,
        finished_at=now - timedelta(days=1),
    )
    failed_task = task_model(
        name="失败任务",
        client_id=client_id,
        config_id=config_id,
        execution_status="失败",
        total_count=4,
        processed_count=1,
    )
    db_session.add_all([running_task, finished_task, older_finished_task, failed_task])
    db_session.commit()

    for task in [running_task, finished_task, older_finished_task, failed_task]:
        db_session.refresh(task)

    today_confirmed_item = _build_task_item(
        task_item_model,
        task_id=finished_task.id,
        name="今日已确认.jpg",
        file_id="file-001",
        status="已确认",
        confirm_state="已确认",
        confirmed_at=now - timedelta(minutes=5),
    )
    today_skipped_item = _build_task_item(
        task_item_model,
        task_id=finished_task.id,
        name="今日已跳过.jpg",
        file_id="file-002",
        status="已跳过",
        confirm_state="已跳过",
        confirmed_at=now - timedelta(minutes=4),
    )
    today_finished_item = _build_task_item(
        task_item_model,
        task_id=finished_task.id,
        name="今日已完成.jpg",
        file_id="file-003",
        status="已完成",
        confirm_state="已确认",
        remote_at=now - timedelta(minutes=3),
    )
    pending_item = _build_task_item(
        task_item_model,
        task_id=running_task.id,
        name="待确认.jpg",
        file_id="file-004",
        status="待复核",
        confirm_state="待确认",
    )
    yesterday_confirmed_item = _build_task_item(
        task_item_model,
        task_id=older_finished_task.id,
        name="昨日已确认.jpg",
        file_id="file-005",
        status="已确认",
        confirm_state="已确认",
        confirmed_at=now - timedelta(days=1),
    )
    db_session.add_all(
        [
            today_confirmed_item,
            today_skipped_item,
            today_finished_item,
            pending_item,
            yesterday_confirmed_item,
        ]
    )
    db_session.commit()

    response = app_client.get("/api/dashboard/stats")

    assert response.status_code == 200
    data = _unwrap_success(response.json())
    assert data["activeTasks"] == 1
    assert data["processedToday"] == 3
    assert data["pendingReviews"] == 1
    assert data["anomalies"] == 1
    assert data["recentActivities"][0]["id"] == finished_task.id
    assert data["recentActivities"][0]["name"] == "最近完成任务"
    assert data["recentActivities"][0]["status"] == "结束"
    assert data["recentActivities"][0]["processedCount"] == 3
    assert data["recentActivities"][0]["totalCount"] == 3
    assert data["recentActivities"][1]["id"] == older_finished_task.id


def _import_task_models() -> tuple[type[Any], type[Any]]:
    """导入当前测试环境重新加载后的任务模型。"""

    task_module = importlib.import_module("aiSelfTest.models.task")
    return task_module.Task, task_module.TaskItem


def _create_client_and_config(app_client: TestClient) -> tuple[int, int]:
    """创建满足任务外键约束的客户端与提示词配置。"""

    client_response = app_client.post(
        "/api/clients/create",
        json={
            "name": "总览项目",
            "apiUrl": "https://example.com",
            "account": "dashboard-admin",
            "password": "secret-123",
            "status": "启用",
        },
    )
    config_response = app_client.post(
        "/api/configs/create",
        json={
            "name": "总览提示词",
            "remark": "总览测试用提示词",
            "text": "请返回识别结果。",
            "format": 0,
        },
    )

    assert client_response.status_code == 201
    assert config_response.status_code == 201
    return (
        _unwrap_success(client_response.json())["id"],
        _unwrap_success(config_response.json())["id"],
    )


def _build_task_item(task_item_model: type[Any], **overrides: Any) -> Any:
    """构造满足数据库约束的 TaskItem。"""

    values: dict[str, Any] = {
        "task_id": 1,
        "name": "image.jpg",
        "device_name": "device-1",
        "file_num": "file-num-1",
        "file_extension": "jpg",
        "file_url": "https://example.com/image.jpg",
        "file_id": "file-id-1",
        "file_fid": "fid-1",
        "sp_name_list": "白鹭",
        "classify": 1,
        "file_bmp": 1,
        "result_file_data": "",
        "id_type": 0,
        "status": "已创建",
    }
    values.update(overrides)
    return task_item_model(**values)
