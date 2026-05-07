"""旧 review 兼容接口禁用测试。"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_review_compat_routes_are_not_registered(app_client: TestClient) -> None:
    """结果复核不再暴露旧 /api/reviews/* 兼容接口。"""

    responses = [
        app_client.get("/api/reviews/completed-tasks"),
        app_client.get("/api/reviews?taskId=1"),
        app_client.post("/api/reviews/confirm", json={"ids": ["1"]}),
        app_client.delete("/api/reviews/1"),
        app_client.post("/api/reviews/delete", json={"ids": ["1"]}),
    ]

    assert [response.status_code for response in responses] == [404, 404, 404, 404, 404]
