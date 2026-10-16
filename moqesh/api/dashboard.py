"""Router del dashboard: overview, timeline y métricas de Token Exhaust."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import AgentSession, Alert, RequestLog, utcnow
from ..schemas import (
    AlertSummary,
    DashboardOverview,
    ModelAttributionEntry,
    ScoreDistributionPoint,
    TimeSeriesPoint,
    TokenBySourceEntry,
    TokenExhaustOverview,
    TopSourceEntry,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _bucket_hourly(timestamps: list[datetime]) -> list[TimeSeriesPoint]:
    counts: Counter[datetime] = Counter(t.replace(minute=0, second=0, microsecond=0) for t in timestamps)
    return [TimeSeriesPoint(timestamp=k, count=counts[k]) for k in sorted(counts)]


@router.get("/overview", response_model=DashboardOverview)
def overview(db: Session = Depends(get_session)) -> DashboardOverview:
    now = utcnow()
    total_requests = db.scalar(select(func.count(RequestLog.id))) or 0
    active_sessions = db.scalar(select(func.count(AgentSession.id)).where(AgentSession.status == "Active")) or 0
    ai_detected = (
        db.scalar(
            select(func.count(AgentSession.id)).where(
                (AgentSession.ai_probability_score >= 0.5) | (AgentSession.verdict == "AiConfirmed")
            )
        )
        or 0
    )
    unresolved = db.scalar(select(func.count(Alert.id)).where(Alert.acknowledged_at.is_(None))) or 0

    recent_ts = db.scalars(select(RequestLog.timestamp).where(RequestLog.timestamp >= now - timedelta(hours=24))).all()

    scores = db.scalars(select(AgentSession.ai_probability_score)).all()
    buckets = [
        ("0.0-0.2", 0.0, 0.2),
        ("0.2-0.4", 0.2, 0.4),
        ("0.4-0.6", 0.4, 0.6),
        ("0.6-0.8", 0.6, 0.8),
        ("0.8-1.0", 0.8, 1.01),
    ]
    dist = [
        ScoreDistributionPoint(range=label, count=sum(1 for s in scores if lo <= s < hi)) for label, lo, hi in buckets
    ]

    top = db.scalars(select(AgentSession).order_by(AgentSession.request_count.desc()).limit(10)).all()
    top_sources = [
        TopSourceEntry(ip=s.source_ip, request_count=s.request_count, max_score=s.ai_probability_score) for s in top
    ]

    recent = db.scalars(select(Alert).order_by(Alert.created_at.desc()).limit(10)).all()
    recent_alerts = [
        AlertSummary(
            id=a.id,
            severity=a.severity,
            title=a.title,
            created_at=a.created_at,
            acknowledged=a.acknowledged_at is not None,
        )
        for a in recent
    ]

    return DashboardOverview(
        total_requests=total_requests,
        active_sessions=active_sessions,
        ai_agents_detected=ai_detected,
        unresolved_alerts=unresolved,
        requests_over_time=_bucket_hourly(list(recent_ts)),
        score_distribution=dist,
        top_sources=top_sources,
        recent_alerts=recent_alerts,
    )


@router.get("/timeline", response_model=list[TimeSeriesPoint])
def timeline(
    db: Session = Depends(get_session), from_: datetime | None = Query(None, alias="from"), to: datetime | None = None
) -> list[TimeSeriesPoint]:
    start = from_ or utcnow() - timedelta(days=7)
    end = to or utcnow()
    ts = db.scalars(
        select(RequestLog.timestamp).where(RequestLog.timestamp >= start, RequestLog.timestamp <= end)
    ).all()
    return _bucket_hourly(list(ts))


@router.get("/token-exhaust", response_model=TokenExhaustOverview)
def token_exhaust(db: Session = Depends(get_session)) -> TokenExhaustOverview:
    engaged = db.scalars(select(AgentSession).where(AgentSession.nodes_served > 0)).all()

    top = sorted(engaged, key=lambda s: s.tokens_estimated, reverse=True)[:15]
    top_burners = [
        TokenBySourceEntry(
            ip=s.source_ip,
            tokens=s.tokens_estimated,
            time_wasted_ms=s.time_wasted_ms,
            nodes=s.nodes_served,
            max_depth=s.max_depth_reached,
            score=s.ai_probability_score,
            verdict=s.verdict,
        )
        for s in top
    ]

    by_model: dict[str, list[AgentSession]] = {}
    for s in engaged:
        if s.model_attribution:
            by_model.setdefault(s.model_attribution, []).append(s)
    models = [
        ModelAttributionEntry(
            model=k,
            sessions=len(v),
            tokens=sum(x.tokens_estimated for x in v),
            avg_score=sum(x.ai_probability_score for x in v) / len(v),
        )
        for k, v in by_model.items()
    ]
    models.sort(key=lambda m: m.tokens, reverse=True)

    return TokenExhaustOverview(
        total_tokens_burned=sum(s.tokens_estimated for s in engaged),
        total_time_wasted_ms=sum(s.time_wasted_ms for s in engaged),
        total_nodes_served=sum(s.nodes_served for s in engaged),
        sessions_engaged=len(engaged),
        top_burners=top_burners,
        by_model=models,
    )
