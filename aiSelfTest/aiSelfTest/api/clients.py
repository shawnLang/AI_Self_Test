"""Client project API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel import Session, select

from aiSelfTest.db.models import Client, Task
from aiSelfTest.db.session import get_session

router = APIRouter(prefix="/api/clients", tags=["clients"])


def map_client(client: Client, *, include_tokens: bool = True) -> dict[str, Any]:
    data = {
        "id": client.id,
        "name": client.name,
        "apiUrl": client.api_url,
        "account": client.account,
        "password": client.password,
        "status": client.status,
    }
    if include_tokens:
        data.update(
            {
                "access_token": client.access_token,
                "refresh_token": client.refresh_token,
                "expires_in": client.expires_in,
            }
        )
    return data


@router.get("")
def list_clients(session: Session = Depends(get_session)):
    return [map_client(client) for client in session.exec(select(Client)).all()]


@router.post("")
async def create_client(request: Request, session: Session = Depends(get_session)):
    body = await request.json()
    client = Client(
        name=body.get("name"),
        api_url=body.get("apiUrl"),
        account=body.get("account"),
        password=body.get("password") or "",
        status=body.get("status") or "活跃",
    )
    session.add(client)
    session.commit()
    session.refresh(client)
    return map_client(client, include_tokens=False)


@router.put("/{client_id}")
async def update_client(client_id: int, request: Request, session: Session = Depends(get_session)):
    body = await request.json()
    client = session.get(Client, client_id)
    if not client:
        raise HTTPException(status_code=404, detail={"error": "Client not found"})
    client.name = body.get("name")
    client.api_url = body.get("apiUrl")
    client.account = body.get("account")
    client.password = body.get("password") or ""
    client.status = body.get("status") or "活跃"
    session.add(client)
    session.commit()
    return {"success": True}


@router.delete("/{client_id}")
def delete_client(client_id: int, session: Session = Depends(get_session)):
    for task in session.exec(select(Task).where(Task.client_id == client_id)).all():
        session.delete(task)
    client = session.get(Client, client_id)
    if client:
        session.delete(client)
    session.commit()
    return {"success": True}
