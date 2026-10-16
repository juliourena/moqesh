"""Router de honeypots: CRUD, toggle y subida de contenido."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import HoneypotConfig, RequestLog, utcnow
from ..schemas import CreateHoneypotRequest, HoneypotDto, UpdateHoneypotRequest

router = APIRouter(prefix="/honeypots", tags=["honeypots"])


def _to_dto(db: Session, h: HoneypotConfig) -> HoneypotDto:
    count = db.scalar(select(func.count(RequestLog.id)).where(RequestLog.honeypot_id == h.id)) or 0
    return HoneypotDto(
        id=h.id,
        name=h.name,
        type=h.type,
        port=h.port,
        is_active=h.is_active,
        token_exhaust_enabled=h.token_exhaust_enabled,
        created_at=h.created_at,
        request_count=count,
    )


@router.get("", response_model=list[HoneypotDto])
def list_honeypots(db: Session = Depends(get_session)) -> list[HoneypotDto]:
    return [_to_dto(db, h) for h in db.scalars(select(HoneypotConfig).order_by(HoneypotConfig.id))]


@router.get("/{honeypot_id}", response_model=HoneypotDto)
def get_honeypot(honeypot_id: int, db: Session = Depends(get_session)) -> HoneypotDto:
    h = db.get(HoneypotConfig, honeypot_id)
    if h is None:
        raise HTTPException(status_code=404, detail="honeypot no encontrado")
    return _to_dto(db, h)


@router.post("", response_model=HoneypotDto, status_code=201)
def create_honeypot(body: CreateHoneypotRequest, db: Session = Depends(get_session)) -> HoneypotDto:
    h = HoneypotConfig(name=body.name, type=body.type, port=body.port, is_active=True, token_exhaust_enabled=True)
    db.add(h)
    db.commit()
    return _to_dto(db, h)


@router.put("/{honeypot_id}", status_code=204)
def update_honeypot(honeypot_id: int, patch: UpdateHoneypotRequest, db: Session = Depends(get_session)) -> Response:
    h = db.get(HoneypotConfig, honeypot_id)
    if h is None:
        raise HTTPException(status_code=404, detail="honeypot no encontrado")
    if patch.name is not None:
        h.name = patch.name
    if patch.port is not None:
        h.port = patch.port
    if patch.is_active is not None:
        h.is_active = patch.is_active
    if patch.token_exhaust_enabled is not None:
        h.token_exhaust_enabled = patch.token_exhaust_enabled
    h.updated_at = utcnow()
    db.commit()
    return Response(status_code=204)


@router.delete("/{honeypot_id}", status_code=204)
def delete_honeypot(honeypot_id: int, db: Session = Depends(get_session)) -> Response:
    h = db.get(HoneypotConfig, honeypot_id)
    if h is not None:
        db.delete(h)
        db.commit()
    return Response(status_code=204)


@router.post("/{honeypot_id}/toggle")
def toggle_honeypot(honeypot_id: int, db: Session = Depends(get_session)) -> dict:
    h = db.get(HoneypotConfig, honeypot_id)
    if h is None:
        raise HTTPException(status_code=404, detail="honeypot no encontrado")
    h.is_active = not h.is_active
    db.commit()
    return {"isActive": h.is_active}


@router.post("/{honeypot_id}/upload")
async def upload_content(honeypot_id: int, files: list[UploadFile]) -> dict:
    # El contenido procedural del laberinto hace innecesaria la subida manual;
    # se acepta por compatibilidad con el dashboard y se reporta el conteo.
    names = [f.filename for f in files]
    for f in files:
        await f.close()
    return {"uploaded": len(names), "files": names}
