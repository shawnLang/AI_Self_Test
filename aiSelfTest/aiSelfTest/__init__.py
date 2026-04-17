"""aiSelfTest application entry point."""

from __future__ import annotations

import sys

import uvicorn

from .app import create_app
from .config import get_settings
from .version import __version__


def main() -> None:
    """Run the bundled FastAPI application as the production entry point."""
    settings = get_settings()
    app = create_app(settings)
    try:
        uvicorn.run(
            app,
            host=settings.host,
            port=settings.port,
            log_config=None,
            workers=1,
        )
    except Exception as exc:  # pragma: no cover - uvicorn owns most failures.
        print(f"aiSelfTest failed to start: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


__all__ = ["__version__", "create_app", "main"]
