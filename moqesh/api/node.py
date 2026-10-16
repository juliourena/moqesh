"""Endpoints de cara a los sensores (agente y agentless).

Autenticación HMAC simétrica por sensor (`security.verify`), rate-limit, dedup y
validación hostil de todo lo recibido. Montado SIN prefijo /api: los sensores
hablan con /ingest/* y /control.
"""

from __future__ import annotations

import json
import logging
import time

from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import select

from .. import logparse, pipeline, security
from ..db import SessionLocal
from ..labyrinth import LabyrinthOptions, kind_of
from ..models import Sensor, SessionProgress
from ..realtime import manager

logger = logging.getLogger("moqesh.node")
router = APIRouter(tags=["node"])

_MAX_BODY = 2 * 1024 * 1024  # 2 MB por request
_STRONG_KEYS = ("credential_reuse", "hidden_path_access", "binary_decompile_followup", "auth_bruteforce")


async def _authed(request: Request) -> tuple[Sensor, bytes]:
    """Devuelve (sensor, body) tras verificar HMAC + estado. Lanza HTTP si falla."""
    body = await request.body()
    if len(body) > _MAX_BODY:
        raise HTTPException(status_code=413, detail="payload demasiado grande")
    key_id = request.headers.get("x-moqesh-key-id", "")
    ts = request.headers.get("x-moqesh-timestamp", "")
    sig = request.headers.get("x-moqesh-signature", "")
    if not key_id or not security.ingest_limiter.allow(key_id):
        raise HTTPException(status_code=429, detail="rate limit")
    with SessionLocal() as db:
        sensor = db.scalar(select(Sensor).where(Sensor.key_id == key_id).limit(1))
        if sensor is None or sensor.retired or not security.verify(sensor.api_secret, ts, sig, body):
            raise HTTPException(status_code=401, detail="no autorizado")
        # Copia desacoplada de la sesión para usar fuera del with.
        snapshot = Sensor(
            id=sensor.id,
            name=sensor.name,
            kind=sensor.kind,
            enabled=sensor.enabled,
            seed=sensor.seed,
            scenario_id=sensor.scenario_id,
            generation_mode=sensor.generation_mode,
            realism_level=sensor.realism_level,
            vocabulary_theme=sensor.vocabulary_theme,
            brand_name=sensor.brand_name,
            base_path=sensor.base_path,
            api_secret=sensor.api_secret,
            config_version=sensor.config_version,
            key_id=sensor.key_id,
        )
    return snapshot, body


def _opts(sensor: Sensor) -> LabyrinthOptions:
    return LabyrinthOptions(
        mode=sensor.generation_mode or "Template",
        seed=sensor.seed or "default-seed",
        realism_level=max(1, min(sensor.realism_level, 5)),
        vocabulary_theme=sensor.vocabulary_theme or "",
        brand_name=sensor.brand_name or "",
    )


def _touch(sensor_id: int, *, ingest: bool, agent_version: str | None = None) -> None:
    from ..models import utcnow

    with SessionLocal() as db:
        s = db.get(Sensor, sensor_id)
        if s is None:
            return
        now = utcnow()
        s.last_seen = now
        s.status = "online"
        if ingest:
            s.last_ingest_at = now
        if agent_version:
            s.agent_version = agent_version
        db.commit()


@router.post("/ingest/events")
async def ingest_events(request: Request) -> dict:
    """Agente: eventos estructurados con señales fuertes ya resueltas localmente."""
    sensor, body = await _authed(request)
    try:
        payload = json.loads(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="JSON inválido") from exc
    events = payload.get("events", [])
    if not isinstance(events, list):
        raise HTTPException(status_code=400, detail="'events' debe ser lista")

    opts = _opts(sensor)
    accepted = 0
    with SessionLocal() as db:
        for ev in events[:5000]:
            if not isinstance(ev, dict) or not ev.get("path"):
                continue
            h = security.event_hash(sensor.id, json.dumps(ev, sort_keys=True))
            if security.dedup.seen(h):
                continue
            result = pipeline.score_and_record(
                db,
                sensor_id=sensor.id,
                opts=opts,
                source_ip=str(ev.get("source_ip", "unknown")),
                user_agent=str(ev.get("user_agent", "")),
                method=str(ev.get("method", "GET")),
                path=str(ev["path"]),
                status=int(ev.get("status", 200)),
                response_size=int(ev.get("size", 0)),
                processing_ms=float(ev.get("processing_ms", 0.0)),
                node_kind=str(ev.get("node_kind", "static")),
                query=ev.get("query"),
                model_attribution=ev.get("model_attribution"),
                signals_fn=_agent_signals(ev),
            )
            accepted += 1
            manager.publish("request", result.request_dto)
            if result.alert:
                manager.publish("alert", result.alert)
        db.commit()
    _touch(sensor.id, ingest=True, agent_version=payload.get("agent_version"))
    return {"accepted": accepted}


@router.post("/ingest/logs")
async def ingest_logs(request: Request) -> dict:
    """Agentless: líneas de log crudas; el parser central reconstruye y puntúa (conductual)."""
    sensor, body = await _authed(request)
    try:
        payload = json.loads(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="JSON inválido") from exc
    fmt = str(payload.get("format", "raw"))
    base = str(payload.get("base_path", sensor.base_path or "/"))
    lines = payload.get("lines", [])
    if not isinstance(lines, list):
        raise HTTPException(status_code=400, detail="'lines' debe ser lista")

    reqs = logparse.parse(fmt, [str(x) for x in lines[:20000]], base_path=base)
    opts = _opts(sensor)
    accepted = 0
    with SessionLocal() as db:
        for r in reqs:
            h = security.event_hash(sensor.id, f"{r.timestamp}|{r.source_ip}|{r.path}|{r.status}")
            if security.dedup.seen(h):
                continue
            result = pipeline.score_and_record(
                db,
                sensor_id=sensor.id,
                opts=opts,
                source_ip=r.source_ip,
                user_agent=r.user_agent,
                method=r.method,
                path=r.path,
                status=r.status,
                response_size=r.size,
                processing_ms=0.0,
                node_kind=kind_of(r.path),
                timestamp=r.timestamp,
            )
            accepted += 1
            manager.publish("request", result.request_dto)
            if result.alert:
                manager.publish("alert", result.alert)
        db.commit()
    _touch(sensor.id, ingest=True)
    return {"accepted": accepted, "parsed": len(reqs)}


@router.get("/control")
async def control(request: Request) -> Response:
    """Estado deseado del sensor, con RESPUESTA FIRMADA (integridad del control)."""
    sensor, _ = await _authed(request)
    _touch(sensor.id, ingest=False)
    scenario_pack = None
    if sensor.scenario_id:
        from ..scenarios import export_pack

        with SessionLocal() as db:
            scenario_pack = export_pack(db, sensor.scenario_id)
    payload = {
        "enabled": sensor.enabled,
        "seed": sensor.seed,
        "scenario_id": sensor.scenario_id,
        "scenario": scenario_pack,  # pack firmado → el agente corre gates/CTF reales
        "generation_mode": sensor.generation_mode,
        "realism_level": sensor.realism_level,
        "config_version": sensor.config_version,
        "server_time": time.time(),
    }
    body = json.dumps(payload).encode()
    ts = str(int(time.time()))
    sig = security.sign(sensor.api_secret, ts, body)
    return Response(
        content=body,
        media_type="application/json",
        headers={"X-Moqesh-Timestamp": ts, "X-Moqesh-Server-Signature": sig},
    )


def _agent_signals(ev: dict):
    """signals_fn para eventos de agente: persiste progreso y devuelve señales fuertes."""
    strong = ev.get("strong") or {}
    prog_facts = ev.get("progress") or {}

    def fn(db, session_id, ordered):
        if prog_facts:
            prog = db.scalar(select(SessionProgress).where(SessionProgress.session_id == session_id).limit(1))
            if prog is None:
                prog = SessionProgress(session_id=session_id, scenario_id=int(prog_facts.get("scenario_id", 0)))
                db.add(prog)
                db.flush()
            prog.stage_reached = max(prog.stage_reached, int(prog_facts.get("stage_reached", 0)))
            for key in ("credentials_obtained", "credentials_used"):
                if prog_facts.get(key):
                    setattr(prog, key, str(prog_facts[key]))
            prog.hidden_hits = max(prog.hidden_hits, int(prog_facts.get("hidden_hits", 0)))
            prog.decompile_follow = prog.decompile_follow or bool(prog_facts.get("decompile_follow"))
            prog.failed_auth_attempts = max(prog.failed_auth_attempts, int(prog_facts.get("failed_auth_attempts", 0)))
        return {k: bool(strong.get(k, False)) for k in _STRONG_KEYS}

    return fn
