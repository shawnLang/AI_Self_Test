"""Loguru logging setup and structured event helpers."""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path
from typing import Any

from loguru import logger

from aiSelfTest.config import Settings


def setup_logging(settings: Settings) -> None:
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(settings.log_dir, 0o700)
    except OSError:
        pass

    logger.remove()
    log_format = (
        "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level} | "
        "{extra[event]} | {extra[request_id]} | {message}"
    )
    logger.configure(extra={"event": "app", "request_id": "-"})
    logger.add(sys.stderr, level="INFO", format=log_format)
    logger.add(
        settings.log_dir / "app.log",
        level="INFO",
        rotation="100 MB",
        retention="14 days",
        compression="zip",
        encoding="utf-8",
        format=log_format,
    )
    logger.add(
        settings.log_dir / "error.log",
        level="ERROR",
        rotation="100 MB",
        retention="14 days",
        compression="zip",
        encoding="utf-8",
        backtrace=True,
        diagnose=True,
        format=log_format,
    )


def summarize_attachment(data: bytes, mime_type: str = "", filename: str = "") -> dict[str, Any]:
    return {
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "mimeType": mime_type,
        "filename": filename,
    }


def log_event(event: str, message: str, *, request_id: str = "-", **payload: Any) -> None:
    logger.bind(event=event, request_id=request_id).info(message, payload=payload)


def log_error(event: str, message: str, *, request_id: str = "-", **payload: Any) -> None:
    logger.bind(event=event, request_id=request_id).exception(message, payload=payload)
