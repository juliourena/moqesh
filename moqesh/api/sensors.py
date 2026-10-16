"""Router de gestión de sensores (dashboard): alta, estado, control y onboarding."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import provisioning, security
from ..db import get_session
from ..models import AgentSession, Alert, Sensor, SensorBundle, utcnow
from ..schemas import CreateSensorRequest, SensorBundleDto, SensorCreated, SensorDto

router = APIRouter(prefix="/sensors", tags=["sensors"])

# Un sensor se considera online si latió hace menos de esto.
_ONLINE_WINDOW_S = 180


def _status(s: Sensor) -> str:
    if s.kind == "local":
        return "online"
    if s.last_seen is None:
        return "unknown"
    return "online" if (utcnow() - s.last_seen).total_seconds() <= _ONLINE_WINDOW_S else "offline"


def _to_dto(db: Session, s: Sensor) -> SensorDto:
    sessions = db.scalar(select(func.count(AgentSession.id)).where(AgentSession.sensor_id == s.id)) or 0
    alerts = (
        db.scalar(select(func.count(Alert.id)).where(Alert.sensor_id == s.id, Alert.acknowledged_at.is_(None))) or 0
    )
    return SensorDto(
        id=s.id,
        name=s.name,
        kind=s.kind,
        enabled=s.enabled,
        status=_status(s),
        last_seen=s.last_seen,
        last_ingest_at=s.last_ingest_at,
        seed=s.seed,
        scenario_id=s.scenario_id,
        generation_mode=s.generation_mode,
        realism_level=s.realism_level,
        covered_url=s.covered_url,
        covered_app=s.covered_app,
        base_path=s.base_path,
        agent_version=s.agent_version,
        config_version=s.config_version,
        created_at=s.created_at,
        session_count=sessions,
        alert_count=alerts,
    )


@router.get("", response_model=list[SensorDto])
def list_sensors(db: Session = Depends(get_session)) -> list[SensorDto]:
    rows = db.scalars(select(Sensor).where(Sensor.retired.is_(False)).order_by(Sensor.id)).all()
    return [_to_dto(db, s) for s in rows]


@router.post("", response_model=SensorCreated, status_code=201)
def create_sensor(body: CreateSensorRequest, db: Session = Depends(get_session)) -> SensorCreated:
    if body.kind not in ("agent", "agentless"):
        raise HTTPException(status_code=400, detail="kind debe ser 'agent' o 'agentless'")
    key_id, secret = security.new_credentials()
    token = uuid.uuid4().hex
    s = Sensor(
        name=body.name,
        kind=body.kind,
        enabled=True,
        status="unknown",
        seed=uuid.uuid4().hex,
        scenario_id=body.scenario_id,
        generation_mode=body.generation_mode,
        realism_level=max(1, min(body.realism_level, 5)),
        vocabulary_theme=body.vocabulary_theme,
        covered_url=body.covered_url,
        covered_app=body.covered_app,
        base_path=body.base_path or "/",
        key_id=key_id,
        api_secret=secret,
        install_token=token,
    )
    db.add(s)
    db.commit()
    return SensorCreated(
        id=s.id,
        name=s.name,
        kind=s.kind,
        key_id=key_id,
        api_secret=secret,
        install_token=token,
        install_command=provisioning.one_command(token),
    )


@router.get("/{sensor_id}", response_model=SensorDto)
def get_sensor(sensor_id: int, db: Session = Depends(get_session)) -> SensorDto:
    s = db.get(Sensor, sensor_id)
    if s is None or s.retired:
        raise HTTPException(status_code=404, detail="sensor no encontrado")
    return _to_dto(db, s)


def _bump(s: Sensor) -> None:
    s.config_version += 1


@router.post("/{sensor_id}/enable")
def enable_sensor(sensor_id: int, db: Session = Depends(get_session)) -> dict:
    s = _require(db, sensor_id)
    s.enabled = True
    _bump(s)
    db.commit()
    return {"id": s.id, "enabled": True}


@router.post("/{sensor_id}/disable")
def disable_sensor(sensor_id: int, db: Session = Depends(get_session)) -> dict:
    s = _require(db, sensor_id)
    s.enabled = False
    _bump(s)
    db.commit()
    return {"id": s.id, "enabled": False}


@router.post("/{sensor_id}/rotate-seed")
def rotate_seed(sensor_id: int, db: Session = Depends(get_session)) -> dict:
    s = _require(db, sensor_id)
    s.seed = uuid.uuid4().hex
    _bump(s)
    db.commit()
    return {"id": s.id, "seed": s.seed}


@router.post("/{sensor_id}/rotate-key", response_model=SensorCreated)
def rotate_key(sensor_id: int, db: Session = Depends(get_session)) -> SensorCreated:
    s = _require(db, sensor_id)
    key_id, secret = security.new_credentials()
    token = uuid.uuid4().hex
    s.key_id, s.api_secret, s.install_token = key_id, secret, token
    _bump(s)
    db.commit()
    return SensorCreated(
        id=s.id,
        name=s.name,
        kind=s.kind,
        key_id=key_id,
        api_secret=secret,
        install_token=token,
        install_command=provisioning.one_command(token),
    )


@router.delete("/{sensor_id}", status_code=204)
def decommission(sensor_id: int, db: Session = Depends(get_session)) -> Response:
    s = db.get(Sensor, sensor_id)
    if s is not None and s.kind != "local":
        s.retired = True
        s.enabled = False
        s.api_secret = ""  # revoca credenciales
        s.install_token = None
        db.commit()
    return Response(status_code=204)


@router.get("/{sensor_id}/install")
def install_info(sensor_id: int, db: Session = Depends(get_session)) -> dict:
    s = _require(db, sensor_id)
    if not s.install_token:
        s.install_token = uuid.uuid4().hex
        db.commit()
    data = {
        "kind": s.kind,
        "oneCommand": provisioning.one_command(s.install_token),
        "inspectCommand": provisioning.inspect_command(s.install_token),
    }
    if s.kind == "agentless":
        data["agentless"] = provisioning.agentless_steps(s.id, s.key_id, s.api_secret, s.base_path, bundle_count=3)
    return data


@router.get("/{sensor_id}/bundles", response_model=list[SensorBundleDto])
def list_bundles(sensor_id: int, db: Session = Depends(get_session)) -> list[SensorBundleDto]:
    rows = db.scalars(select(SensorBundle).where(SensorBundle.sensor_id == sensor_id)).all()
    return [SensorBundleDto.model_validate(b) for b in rows]


@router.post("/{sensor_id}/bundles", response_model=list[SensorBundleDto])
def generate_bundles(sensor_id: int, count: int = 3, db: Session = Depends(get_session)) -> list[SensorBundleDto]:
    s = _require(db, sensor_id)
    try:
        from .. import bundles  # módulo del generador (entrega aparte)
    except ImportError as exc:
        raise HTTPException(status_code=501, detail="generador de bundles no disponible") from exc
    created = bundles.generate_for_sensor(db, s, count=count)
    return [SensorBundleDto.model_validate(b) for b in created]


def _require(db: Session, sensor_id: int) -> Sensor:
    s = db.get(Sensor, sensor_id)
    if s is None or s.retired:
        raise HTTPException(status_code=404, detail="sensor no encontrado")
    return s
