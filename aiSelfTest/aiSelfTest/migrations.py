"""Alembic upgrade helpers for package-managed migrations."""

from __future__ import annotations

from alembic import command
from alembic.config import Config

from aiSelfTest.config import Settings
from aiSelfTest.logging import log_event


def run_migrations(settings: Settings) -> None:
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    config = Config(str(settings.package_dir / "alembic.ini"))
    config.set_main_option("script_location", str(settings.package_dir / "alembic"))
    config.set_main_option("sqlalchemy.url", settings.database_url)
    log_event("db_migration", "running alembic upgrade head", database=str(settings.database_path))
    command.upgrade(config, "head")
    log_event("db_migration", "alembic upgrade head completed", database=str(settings.database_path))
