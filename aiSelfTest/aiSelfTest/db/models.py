"""SQLModel table definitions for the new SQLite schema."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Column, String, Text
from sqlmodel import Field, SQLModel


class Client(SQLModel, table=True):
    __tablename__ = "clients"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    api_url: str = Field(sa_column=Column("apiUrl", String, nullable=False))
    account: str
    password: str
    status: str = Field(default="活跃")
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    expires_in: Optional[int] = None


class Task(SQLModel, table=True):
    __tablename__ = "tasks"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    client_id: int = Field(foreign_key="clients.id")
    interval: str
    threshold: int = 0
    filters_json: Optional[str] = Field(default=None, sa_column=Column(Text))
    execution_mode: str = Field(default="manual")
    auto_confirm: bool = Field(default=False)
    active: bool = Field(default=False)
    execution_status: str = Field(default="idle")
    total_count: int = Field(default=0)
    processed_count: int = Field(default=0)
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    last_error: Optional[str] = None


class Review(SQLModel, table=True):
    __tablename__ = "reviews"

    id: str = Field(primary_key=True)
    image_url: str
    original_result: str
    sp_name_list: Optional[str] = None
    ai_result: str
    status: str
    schema_version: int = Field(default=2)
    detail_snapshot_json: Optional[str] = Field(default=None, sa_column=Column(Text))
    review_rows_json: Optional[str] = Field(default=None, sa_column=Column(Text))
    confirm_state: str = Field(default="pending")
    confirm_attempted_at: Optional[str] = None
    confirmed_at: Optional[str] = None
    remote_error: Optional[str] = None
    updated_at: Optional[str] = None
    task_id: Optional[int] = Field(default=None, foreign_key="tasks.id")
    task_name: Optional[str] = None
    file_id: Optional[int] = None
    media_type: Optional[str] = None
    media_url: Optional[str] = None
    file_time: Optional[str] = None
    created_at: Optional[str] = None


class MultimodalModel(SQLModel, table=True):
    __tablename__ = "multimodal_models"

    id: Optional[int] = Field(default=None, primary_key=True)
    model_name: str
    endpoint_url: str
    api_key: str
    status: str = Field(default="active")
    detected_models_json: Optional[str] = Field(default=None, sa_column=Column(Text))
    last_detected_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
