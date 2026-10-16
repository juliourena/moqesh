"""Router de sesiones: listado, detalle (con progreso CTF) y requests."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import AgentSession, Alert, RequestLog, SessionProgress
from ..schemas import AlertSummary, RequestLogDto, ScenarioProgressDto, SessionDetailDto, SessionDto

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.get("", response_model=list[SessionDto])
def list_sessions(
    db: Session = Depends(get_session),
    min_score: float = Query(0.0, alias="minScore"),
    status: str | None = None,
    limit: int = Query(100, le=500),
) -> list[SessionDto]:
    stmt = select(AgentSession).where(AgentSession.ai_probability_score >= min_score)
    if status:
        stmt = stmt.where(AgentSession.status == status)
    stmt = stmt.order_by(AgentSession.last_seen.desc()).limit(limit)
    return [SessionDto.model_validate(s) for s in db.scalars(stmt)]


@router.get("/{session_id}", response_model=SessionDetailDto)
def get_session_detail(session_id: int, db: Session = Depends(get_session)) -> SessionDetailDto:
    s = db.get(AgentSession, session_id)
    if s is None:
        raise HTTPException(status_code=404, detail="sesión no encontrada")
    reqs = db.scalars(
        select(RequestLog).where(RequestLog.session_id == session_id).order_by(RequestLog.timestamp)
    ).all()
    alerts = db.scalars(select(Alert).where(Alert.session_id == session_id).order_by(Alert.created_at.desc())).all()
    prog = db.scalar(select(SessionProgress).where(SessionProgress.session_id == session_id).limit(1))
    return SessionDetailDto(
        session=SessionDto.model_validate(s),
        requests=[RequestLogDto.model_validate(r) for r in reqs],
        alerts=[
            AlertSummary(
                id=a.id,
                severity=a.severity,
                title=a.title,
                created_at=a.created_at,
                acknowledged=a.acknowledged_at is not None,
            )
            for a in alerts
        ],
        progress=ScenarioProgressDto.model_validate(prog) if prog else None,
    )


@router.get("/{session_id}/requests", response_model=list[RequestLogDto])
def session_requests(session_id: int, db: Session = Depends(get_session)) -> list[RequestLogDto]:
    reqs = db.scalars(
        select(RequestLog).where(RequestLog.session_id == session_id).order_by(RequestLog.timestamp)
    ).all()
    return [RequestLogDto.model_validate(r) for r in reqs]
