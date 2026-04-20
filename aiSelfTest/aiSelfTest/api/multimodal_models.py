"""Multimodal model configuration API routes."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel import Session, select

from aiSelfTest.db.models import MultimodalModel
from aiSelfTest.db.session import get_session
from aiSelfTest.services.multimodal import (
    chat_with_multimodal_model,
    detect_remote_models,
    map_multimodal_model,
)
from aiSelfTest.services.utils import normalize_endpoint_url, now_iso

router = APIRouter(prefix="/api/multimodal-models", tags=["multimodal-models"])


@router.get("")
def list_models(session: Session = Depends(get_session)):
    rows = session.exec(select(MultimodalModel).order_by(MultimodalModel.updated_at.desc(), MultimodalModel.id.desc())).all()
    return [map_multimodal_model(row) for row in rows]


@router.post("/detect")
async def detect_models(request: Request):
    body = await request.json()
    endpoint_url = str(body.get("endpointUrl") or "").strip()
    api_key = str(body.get("apiKey") or "").strip()
    if not endpoint_url or not api_key:
        raise HTTPException(status_code=400, detail={"error": "请先输入地址和密码。"})
    try:
        result = await asyncio.to_thread(detect_remote_models, endpoint_url, api_key)
        return {
            "models": result["models"],
            "detectedUrl": result["detectedUrl"],
            "recommendedModel": result["models"][0] if result["models"] else "",
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc


@router.post("")
async def create_model(request: Request, session: Session = Depends(get_session)):
    body = await request.json()
    model_name = str(body.get("modelName") or "").strip()
    endpoint_url = str(body.get("endpointUrl") or "").strip()
    api_key = str(body.get("apiKey") or "").strip()
    if not model_name or not endpoint_url or not api_key:
        raise HTTPException(status_code=400, detail={"error": "模型名称、地址、密码不能为空。"})
    now = now_iso()
    detected = body.get("detectedModels") if isinstance(body.get("detectedModels"), list) else []
    row = MultimodalModel(
        model_name=model_name,
        endpoint_url=normalize_endpoint_url(endpoint_url),
        api_key=api_key,
        status=body.get("status") or "active",
        detected_models_json=json.dumps(detected, ensure_ascii=False),
        last_detected_at=now if detected else None,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return map_multimodal_model(row)


@router.put("/{model_id}")
async def update_model(model_id: int, request: Request, session: Session = Depends(get_session)):
    body = await request.json()
    model_name = str(body.get("modelName") or "").strip()
    endpoint_url = str(body.get("endpointUrl") or "").strip()
    api_key = str(body.get("apiKey") or "").strip()
    if not model_name or not endpoint_url or not api_key:
        raise HTTPException(status_code=400, detail={"error": "模型名称、地址、密码不能为空。"})
    row = session.get(MultimodalModel, model_id)
    if not row:
        raise HTTPException(status_code=404, detail={"error": "未找到对应的多模态模型配置。"})
    detected = body.get("detectedModels") if isinstance(body.get("detectedModels"), list) else []
    row.model_name = model_name
    row.endpoint_url = normalize_endpoint_url(endpoint_url)
    row.api_key = api_key
    row.status = body.get("status") or "active"
    row.detected_models_json = json.dumps(detected, ensure_ascii=False)
    row.last_detected_at = now_iso() if detected else None
    row.updated_at = now_iso()
    session.add(row)
    session.commit()
    session.refresh(row)
    return map_multimodal_model(row)


@router.delete("/{model_id}")
def delete_model(model_id: int, session: Session = Depends(get_session)):
    row = session.get(MultimodalModel, model_id)
    if row:
        session.delete(row)
        session.commit()
    return {"success": True}


@router.post("/{model_id}/chat")
async def chat(model_id: int, request: Request, session: Session = Depends(get_session)):
    body = await request.json()
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        raise HTTPException(status_code=400, detail={"error": "请至少输入一条对话消息。"})
    row = session.get(MultimodalModel, model_id)
    if not row:
        raise HTTPException(status_code=404, detail={"error": "未找到对应的多模态模型配置。"})
    try:
        result = await asyncio.to_thread(chat_with_multimodal_model, row, messages)
        return {"reply": result["assistantMessage"], "modelName": row.model_name, "usedUrl": result["requestUrl"]}
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"error": str(exc)}) from exc
