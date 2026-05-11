"""前端静态资源服务测试。"""

from __future__ import annotations

import importlib
from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient


def test_root_serves_frontend_index_and_assets(monkeypatch, tmp_path: Path) -> None:
    """根路径应返回前端入口页面，assets 路径应返回静态资源。"""

    from aiSelfTest.config import get_settings

    settings = get_settings()
    static_dir = tmp_path / "static"
    assets_dir = static_dir / "assets"
    assets_dir.mkdir(parents=True)
    (static_dir / "index.html").write_text(
        '<!doctype html><html><head><script src="/assets/app.js"></script></head><body></body></html>',
        encoding="utf-8",
    )
    (assets_dir / "app.js").write_text("console.log('ok');", encoding="utf-8")

    main_module = importlib.import_module("aiSelfTest.main")
    monkeypatch.setattr(main_module, "get_settings", lambda: replace(settings, static_dir=static_dir))

    with TestClient(main_module.create_app()) as client:
        index_response = client.get("/")
        asset_response = client.get("/assets/app.js")

    assert index_response.status_code == 200
    assert "text/html" in index_response.headers["content-type"]
    assert "/assets/app.js" in index_response.text
    assert asset_response.status_code == 200
    assert "console.log('ok');" in asset_response.text
