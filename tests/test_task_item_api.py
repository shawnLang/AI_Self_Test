"""TaskItem 与动作层契约测试。"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sqlmodel import Session, select


def _unwrap_success(response_json: dict[str, Any]) -> Any:
    assert response_json["code"] == 0
    assert response_json["message"] == "success"
    return response_json["data"]


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


def _create_task_payload(client_id: int, config_id: int) -> dict[str, Any]:
    return {
        "name": "任务工作区-001",
        "client_id": client_id,
        "config_id": config_id,
        "interval_hours": 1,
        "execution_mode": "manual",
        "auto_confirm": False,
        "filters": {
            "classify_list": [1, 2],
            "keyword": "",
            "sp_name": "",
            "start_at": "2026-04-20",
            "end_at": "2026-04-25",
            "media_types": ["image", "video"],
            "upload_types": [],
            "identify_source": [],
        },
    }


def _create_base_entities(app_client: TestClient) -> tuple[int, int, int]:
    client_response = app_client.post("/api/clients/create", json=_create_client_payload())
    config_response = app_client.post("/api/configs/create", json=_create_config_payload())

    client_id = _unwrap_success(client_response.json())["id"]
    config_id = _unwrap_success(config_response.json())["id"]

    task_response = app_client.post(
        "/api/tasks/create",
        json=_create_task_payload(client_id, config_id),
    )
    task_id = _unwrap_success(task_response.json())["id"]
    return client_id, config_id, task_id


def _seed_task_item(
    db_session: Session,
    task_id: int,
    **overrides: Any,
) -> tuple[Any, Any]:
    task_item_model, task_item_data_model = import_task_item_models()

    task_item_payload = {
        "task_id": task_id,
        "name": "video-1.mp4",
        "device_name": "device-1",
        "file_num": "file-001",
        "file_extension": "mp4",
        "file_url": "https://example.com/video.mp4",
        "file_fid": "fid-001",
        "sp_name_list": "白鹭",
        "classify": 1,
        "file_bmp": 2,
        "result_file_data": "https://example.com/result.json",
        "id_type": 0,
        "status": "核查",
        "down_state": True,
        "llm_state": "success",
        "confirm_state": "pending",
        "remote_state": "pending",
    }
    task_item_payload.update(overrides)
    task_item = task_item_model(**task_item_payload)
    db_session.add(task_item)
    db_session.commit()
    db_session.refresh(task_item)

    task_item_data = task_item_data_model(
        task_item_id=task_item.id,
        name="白鹭",
        score=0.91,
        track_ids="1001",
        sp_amount=1,
        llm_name="白鹭",
        status="修改",
    )
    db_session.add(task_item_data)
    db_session.commit()
    db_session.refresh(task_item_data)
    return task_item, task_item_data


def test_task_item_list_returns_items_for_task(
    app_client: TestClient,
    db_session: Session,
) -> None:
    _, _, task_id = _create_base_entities(app_client)
    task_item, _ = _seed_task_item(db_session, task_id)

    response = app_client.get(f"/api/task-items/list?task_id={task_id}")

    assert response.status_code == 200
    data = _unwrap_success(response.json())
    assert data["total"] == 1
    assert data["items"][0]["id"] == task_item.id
    assert data["items"][0]["media_type"] == "video"


def test_task_item_list_filters_by_media_status_and_confirm_state(
    app_client: TestClient,
    db_session: Session,
) -> None:
    _, _, task_id = _create_base_entities(app_client)
    _seed_task_item(
        db_session,
        task_id,
        name="image-confirmed.jpg",
        file_extension="jpg",
        file_url="https://example.com/image.jpg",
        file_fid="fid-image-confirmed",
        file_bmp=1,
        result_file_data="",
        status="核查",
        confirm_state="manual_confirmed",
    )
    _seed_task_item(
        db_session,
        task_id,
        name="video-pending.mp4",
        file_fid="fid-video-pending",
        status="核查",
        confirm_state="pending",
    )

    response = app_client.get(
        "/api/task-items/list",
        params={
            "task_id": task_id,
            "media_type": "image",
            "status": "核查",
            "confirm_state": "manual_confirmed",
        },
    )

    assert response.status_code == 200
    data = _unwrap_success(response.json())
    assert data["total"] == 1
    assert data["items"][0]["name"] == "image-confirmed.jpg"
    assert data["items"][0]["media_type"] == "image"


def test_task_item_detail_returns_review_rows(
    app_client: TestClient,
    db_session: Session,
) -> None:
    _, _, task_id = _create_base_entities(app_client)
    task_item, task_item_data = _seed_task_item(db_session, task_id)

    response = app_client.get(f"/api/task-items/detail/{task_item.id}")

    assert response.status_code == 200
    data = _unwrap_success(response.json())
    assert data["id"] == task_item.id
    assert data["review_rows"][0]["task_item_data_id"] == task_item_data.id
    assert data["review_rows"][0]["status"] == "修改"


def test_task_item_confirm_action_updates_confirm_state(
    app_client: TestClient,
    db_session: Session,
) -> None:
    _, _, task_id = _create_base_entities(app_client)
    task_item, _ = _seed_task_item(db_session, task_id)
    task_item_model, _ = import_task_item_models()

    response = app_client.post("/api/task-items/action-confirm", json={"task_item_id": task_item.id})

    assert response.status_code == 200
    db_session.refresh(task_item)
    stored = db_session.exec(select(task_item_model).where(task_item_model.id == task_item.id)).one()
    assert stored.confirm_state in {"manual_confirmed", "confirmed", "auto_confirmed"}
    assert stored.remote_state == "pending"


def test_task_item_reject_action_does_not_delete_source_item(
    app_client: TestClient,
    db_session: Session,
) -> None:
    _, _, task_id = _create_base_entities(app_client)
    task_item, _ = _seed_task_item(db_session, task_id)
    task_item_model, _ = import_task_item_models()

    response = app_client.post(
        "/api/task-items/action-reject",
        json={"task_item_id": task_item.id, "reason": "manual_review_required"},
    )

    assert response.status_code == 200
    stored = db_session.exec(select(task_item_model).where(task_item_model.id == task_item.id)).one_or_none()
    assert stored is not None


def test_task_item_delete_action_does_not_delete_source_task_item(
    app_client: TestClient,
    db_session: Session,
) -> None:
    _, _, task_id = _create_base_entities(app_client)
    task_item, task_item_data = _seed_task_item(db_session, task_id)
    task_item_model, task_item_data_model = import_task_item_models()
    retained_data = task_item_data_model(
        task_item_id=task_item.id,
        name="苍鹭",
        score=0.88,
        track_ids="1002",
        sp_amount=1,
        llm_name="苍鹭",
        status="修改",
    )
    db_session.add(retained_data)
    db_session.commit()
    db_session.refresh(retained_data)

    response = app_client.post(
        "/api/task-items/action-delete",
        json={"task_item_id": task_item.id, "task_item_data_ids": [task_item_data.id]},
    )

    assert response.status_code == 200
    db_session.expire_all()
    assert db_session.exec(
        select(task_item_model).where(task_item_model.id == task_item.id)
    ).one_or_none() is not None
    assert db_session.exec(
        select(task_item_data_model).where(task_item_data_model.id == task_item_data.id)
    ).one_or_none() is not None
    deleted_row = db_session.exec(
        select(task_item_data_model).where(task_item_data_model.id == task_item_data.id)
    ).one()
    retained_row = db_session.exec(
        select(task_item_data_model).where(task_item_data_model.id == retained_data.id)
    ).one()
    assert deleted_row.status == "删除"
    assert retained_row.status == "修改"


def test_task_item_submit_action_returns_success(
    app_client: TestClient,
    db_session: Session,
) -> None:
    _, _, task_id = _create_base_entities(app_client)
    task_item, _ = _seed_task_item(db_session, task_id)

    response = app_client.post("/api/task-items/action-submit", json={"task_item_id": task_item.id})

    assert response.status_code == 200
    assert response.json()["code"] == 0


def test_task_item_submit_rejected_item_is_blocked(
    app_client: TestClient,
    db_session: Session,
) -> None:
    _, _, task_id = _create_base_entities(app_client)
    task_item, _ = _seed_task_item(db_session, task_id, confirm_state="rejected")

    response = app_client.post("/api/task-items/action-submit", json={"task_item_id": task_item.id})

    assert response.status_code == 400
    assert response.json()["code"] == 1001
    db_session.refresh(task_item)
    assert task_item.remote_state == "pending"


def import_task_item_models():
    from aiSelfTest.models.task import TaskItem, TaskItemData

    return TaskItem, TaskItemData
