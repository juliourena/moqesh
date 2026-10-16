"""Router de monitoreo: requests, alertas y reglas de detección."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import Alert, DetectionRule, RequestLog
from ..schemas import AlertSummary, DetectionRuleDto, RequestLogDto, UpdateRuleRequest

router = APIRouter(tags=["monitoring"])


# ---- Requests ----


@router.get("/requests", response_model=list[RequestLogDto])
def list_requests(
    db: Session = Depends(get_session),
    honeypot_id: int | None = Query(None, alias="honeypotId"),
    limit: int = Query(50, le=500),
    offset: int = 0,
) -> list[RequestLogDto]:
    stmt = select(RequestLog)
    if honeypot_id is not None:
        stmt = stmt.where(RequestLog.honeypot_id == honeypot_id)
    stmt = stmt.order_by(RequestLog.timestamp.desc()).offset(offset).limit(limit)
    return [RequestLogDto.model_validate(r) for r in db.scalars(stmt)]


@router.get("/requests/{request_id}", response_model=RequestLogDto)
def get_request(request_id: int, db: Session = Depends(get_session)) -> RequestLogDto:
    r = db.get(RequestLog, request_id)
    if r is None:
        raise HTTPException(status_code=404, detail="request no encontrada")
    return RequestLogDto.model_validate(r)


# ---- Alertas ----


@router.get("/alerts", response_model=list[AlertSummary])
def list_alerts(
    db: Session = Depends(get_session),
    severity: str | None = None,
    acknowledged: bool | None = None,
    limit: int = Query(50, le=500),
) -> list[AlertSummary]:
    stmt = select(Alert)
    if severity:
        stmt = stmt.where(Alert.severity == severity)
    if acknowledged is not None:
        stmt = stmt.where(Alert.acknowledged_at.isnot(None) if acknowledged else Alert.acknowledged_at.is_(None))
    stmt = stmt.order_by(Alert.created_at.desc()).limit(limit)
    return [
        AlertSummary(
            id=a.id,
            severity=a.severity,
            title=a.title,
            created_at=a.created_at,
            acknowledged=a.acknowledged_at is not None,
        )
        for a in db.scalars(stmt)
    ]


@router.put("/alerts/{alert_id}/acknowledge", status_code=204)
def acknowledge_alert(alert_id: int, db: Session = Depends(get_session)) -> Response:
    from ..models import utcnow

    a = db.get(Alert, alert_id)
    if a is None:
        raise HTTPException(status_code=404, detail="alerta no encontrada")
    if a.acknowledged_at is None:
        a.acknowledged_at = utcnow()
        db.commit()
    return Response(status_code=204)


# ---- Reglas ----


@router.get("/rules", response_model=list[DetectionRuleDto])
def list_rules(db: Session = Depends(get_session)) -> list[DetectionRuleDto]:
    rules = db.scalars(select(DetectionRule).order_by(DetectionRule.id)).all()
    return [DetectionRuleDto.model_validate(r) for r in rules]


@router.put("/rules/{rule_id}", status_code=204)
def update_rule(rule_id: int, patch: UpdateRuleRequest, db: Session = Depends(get_session)) -> Response:
    r = db.get(DetectionRule, rule_id)
    if r is None:
        raise HTTPException(status_code=404, detail="regla no encontrada")
    if patch.weight is not None:
        r.weight = patch.weight
    if patch.is_active is not None:
        r.is_active = patch.is_active
    db.commit()
    return Response(status_code=204)
