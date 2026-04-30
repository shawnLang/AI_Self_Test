"""旧 review 接口兼容层测试。"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sqlmodel import Session, select


def _create_client_payload() -> dict[str, Any]:
    return {
        "name": "任务项目",
        "apiUrl": "https://example.com",
        "account": "task-admin",
        "password": "secret-123",
        "status": "启用",
    }


def _create_config_payload() -> dict[str, Any]:
    return {
        "name": "任务提示词",
        "remark": "任务测试用提示词",
        "text": "请返回识别结果。",
        "format": 0,
    }


def _unwrap_success(response_json: dict[str, Any]) -> Any:
    assert response_json["code"] == 0
    assert response_json["message"] == "success"
    return response_json["data"]


def _seed_review_fixture(app_client: TestClient, db_session: Session) -> tuple[int, int]:
    client_id = _unwrap_success(
        app_client.post("/api/clients/create", json=_create_client_payload()).json()
    )["id"]
    config_id = _unwrap_success(
        app_client.post("/api/configs/create", json=_create_config_payload()).json()
    )["id"]
    task_id = _unwrap_success(
        app_client.post(
            "/api/tasks/create",
            json={
                "name": "复核任务-001",
                "client_id": client_id,
                "config_id": config_id,
                "interval_hours": 1,
                "execution_mode": "manual",
                "auto_confirm": False,
                "filters": {
                    "classify_list": [1],
                    "keyword": "",
                    "sp_name": "",
                    "start_at": "",
                    "end_at": "",
                    "media_types": ["image"],
                    "upload_types": [],
                    "identify_source": [],
                },
            },
        ).json()
    )["id"]

    task_model, task_item_model, task_item_data_model = import_task_models()
    task = db_session.get(task_model, task_id)
    task.execution_status = "结束"
    db_session.add(task)
    db_session.commit()

    task_item = task_item_model(
        task_id=task_id,
        name="image-1.jpg",
        device_name="device-1",
        file_num="file-001",
        file_extension="jpg",
        file_url="https://example.com/image.jpg",
        file_id="file-001",
        file_fid="fid-001",
        sp_name_list="白鹭",
        classify=1,
        file_bmp=1,
        result_file_data="",
        id_type=0,
        status="核查",
        down_state=True,
        llm_state="success",
        confirm_state="pending",
        remote_state="pending",
    )
    db_session.add(task_item)
    db_session.commit()
    db_session.refresh(task_item)

    task_item_data = task_item_data_model(
        task_item_id=task_item.id,
        name="白鹭",
        llm_name="苍鹭",
        score=0.91,
        track_ids="1001",
        sp_amount=1,
        status="修改",
    )
    db_session.add(task_item_data)
    db_session.commit()
    return task_id, task_item.id or 0


def test_list_completed_review_tasks_returns_task_options(
    app_client: TestClient,
    db_session: Session,
) -> None:
    task_id, _ = _seed_review_fixture(app_client, db_session)

    response = app_client.get("/api/reviews/completed-tasks")

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert data[0]["id"] == task_id
    assert data[0]["name"] == "复核任务-001"


def test_list_reviews_returns_review_items(
    app_client: TestClient,
    db_session: Session,
) -> None:
    task_id, task_item_id = _seed_review_fixture(app_client, db_session)

    response = app_client.get(f"/api/reviews?taskId={task_id}")

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert data[0]["id"] == task_item_id
    assert data[0]["taskName"] == "复核任务-001"
    assert data[0]["mediaType"] == "image"
    assert data[0]["reviewRows"][0]["aiName"] == "苍鹭"
    assert data[0]["reviewRows"][0]["groundingStatus"] == "structured"
    assert data[0]["reviewRows"][0]["willSubmit"] is True


def test_confirm_reviews_updates_task_item_confirm_state_without_submitting(
    app_client: TestClient,
    db_session: Session,
) -> None:
    _, task_item_id = _seed_review_fixture(app_client, db_session)
    _, task_item_model, _ = import_task_models()

    response = app_client.post("/api/reviews/confirm", json={"ids": [str(task_item_id)]})

    assert response.status_code == 200
    data = response.json()
    assert data["successCount"] == 1
    assert data["failureCount"] == 0
    task_item = db_session.exec(select(task_item_model).where(task_item_model.id == task_item_id)).one()
    assert task_item.confirm_state == "manual_confirmed"
    assert task_item.remote_state == "pending"
    assert task_item.remote_at is None


def test_delete_review_marks_rows_deleted_but_keeps_source_entities(
    app_client: TestClient,
    db_session: Session,
) -> None:
    _, task_item_id = _seed_review_fixture(app_client, db_session)
    _, task_item_model, task_item_data_model = import_task_models()

    response = app_client.delete(f"/api/reviews/{task_item_id}")

    assert response.status_code == 200
    task_item = db_session.exec(select(task_item_model).where(task_item_model.id == task_item_id)).one_or_none()
    task_item_data = db_session.exec(select(task_item_data_model)).all()
    assert task_item is not None
    assert task_item_data != []
    assert all(row.status == "删除" for row in task_item_data)


def test_batch_delete_reviews_marks_rows_deleted_but_keeps_source_entities(
    app_client: TestClient,
    db_session: Session,
) -> None:
    _, task_item_id = _seed_review_fixture(app_client, db_session)
    _, task_item_model, task_item_data_model = import_task_models()

    response = app_client.post("/api/reviews/delete", json={"ids": [str(task_item_id)]})

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    task_item = db_session.exec(select(task_item_model).where(task_item_model.id == task_item_id)).one_or_none()
    task_item_data = db_session.exec(select(task_item_data_model)).all()
    assert task_item is not None
    assert task_item_data != []
    assert all(row.status == "删除" for row in task_item_data)


def import_task_models():
    from aiSelfTest.models.task import Task, TaskItem, TaskItemData

    return Task, TaskItem, TaskItemData
