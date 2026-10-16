"""Router de bloqueos: listar, bloquear (manual) y desbloquear IPs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import BlockedIp
from ..schemas import BlockedIpDto, BlockRequest

router = APIRouter(prefix="/blocks", tags=["blocks"])


@router.get("", response_model=list[BlockedIpDto])
def list_blocks(db: Session = Depends(get_session)) -> list[BlockedIpDto]:
    rows = db.scalars(select(BlockedIp).order_by(BlockedIp.created_at.desc())).all()
    return [BlockedIpDto.model_validate(b) for b in rows]


@router.post("", status_code=204)
def block_ip(body: BlockRequest, db: Session = Depends(get_session)) -> Response:
    existing = db.scalar(select(BlockedIp).where(BlockedIp.ip == body.ip, BlockedIp.active.is_(True)).limit(1))
    if existing is None:
        db.add(BlockedIp(ip=body.ip, reason=body.reason or "manual", source="manual", active=True))
        db.commit()
    return Response(status_code=204)


@router.delete("/{block_id}", status_code=204)
def unblock(block_id: int, db: Session = Depends(get_session)) -> Response:
    b = db.get(BlockedIp, block_id)
    if b is not None:
        b.active = False
        db.commit()
    return Response(status_code=204)
