"""Router de escenarios CTF: packs, nodos y credenciales (CRUD + import/export)."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import Scenario, ScenarioCredential, ScenarioNode
from ..scenarios import BUILTIN_PACKS, export_pack, import_pack
from ..schemas import CamelModel, ScenarioCredentialDto, ScenarioDetail, ScenarioInfo, ScenarioNodeDto, ScenarioSummary

router = APIRouter(prefix="/scenarios", tags=["scenarios"])


class ScenarioNodeInput(CamelModel):
    path: str = ""
    visibility: str = "linked"
    kind: str = "file"
    content_type: str = "text/plain; charset=utf-8"
    body_template: str = ""
    requires_credential_key: str | None = None
    grants_credential_keys: str | None = None
    hinted_by_paths: str | None = None
    stage: int = 0
    binary_kind: str = "none"
    binary_secret: str = ""


class ScenarioCredentialInput(CamelModel):
    key: str = ""
    username: str | None = None
    secret: str = ""
    kind: str = "bearer"
    found_in_path: str | None = None
    usable_at_path: str | None = None


# ---- listados / detalle (rutas específicas antes de /{id}) ----


@router.get("", response_model=list[ScenarioSummary])
def list_scenarios(db: Session = Depends(get_session)) -> list[ScenarioSummary]:
    scenarios = db.scalars(select(Scenario).order_by(Scenario.is_active.desc(), Scenario.name)).all()
    out = []
    for s in scenarios:
        nc = db.scalar(select(func.count(ScenarioNode.id)).where(ScenarioNode.scenario_id == s.id)) or 0
        cc = db.scalar(select(func.count(ScenarioCredential.id)).where(ScenarioCredential.scenario_id == s.id)) or 0
        out.append(
            ScenarioSummary(
                id=s.id,
                name=s.name,
                description=s.description,
                is_active=s.is_active,
                created_at=s.created_at,
                node_count=nc,
                cred_count=cc,
            )
        )
    return out


@router.get("/builtins", response_model=list[str])
def builtins() -> list[str]:
    return list(BUILTIN_PACKS.keys())


@router.post("/builtins/{name}")
def import_builtin(name: str, activate: bool = Query(False), db: Session = Depends(get_session)) -> dict:
    factory = BUILTIN_PACKS.get(name)
    if factory is None:
        raise HTTPException(status_code=404, detail="pack no encontrado")
    s = import_pack(db, factory(), activate)
    return {"id": s.id, "name": s.name, "isActive": s.is_active}


@router.post("/import")
def import_scenario(activate: bool = Query(False), pack: dict = Body(...), db: Session = Depends(get_session)) -> dict:
    if not pack.get("name"):
        raise HTTPException(status_code=400, detail="pack JSON inválido: falta 'name'")
    s = import_pack(db, pack, activate)
    return {"id": s.id, "name": s.name, "isActive": s.is_active}


@router.get("/{scenario_id}/export")
def export_scenario(scenario_id: int, db: Session = Depends(get_session)) -> dict:
    pack = export_pack(db, scenario_id)
    if pack is None:
        raise HTTPException(status_code=404, detail="escenario no encontrado")
    return pack


@router.get("/{scenario_id}", response_model=ScenarioDetail)
def get_scenario(scenario_id: int, db: Session = Depends(get_session)) -> ScenarioDetail:
    s = db.get(Scenario, scenario_id)
    if s is None:
        raise HTTPException(status_code=404, detail="escenario no encontrado")
    nodes = db.scalars(
        select(ScenarioNode)
        .where(ScenarioNode.scenario_id == scenario_id)
        .order_by(ScenarioNode.stage, ScenarioNode.path)
    ).all()
    creds = db.scalars(select(ScenarioCredential).where(ScenarioCredential.scenario_id == scenario_id)).all()
    return ScenarioDetail(
        scenario=ScenarioInfo(
            id=s.id, name=s.name, description=s.description, is_active=s.is_active, created_at=s.created_at
        ),
        nodes=[ScenarioNodeDto.model_validate(n) for n in nodes],
        credentials=[ScenarioCredentialDto.model_validate(c) for c in creds],
    )


@router.post("/{scenario_id}/activate")
def activate(scenario_id: int, db: Session = Depends(get_session)) -> dict:
    s = db.get(Scenario, scenario_id)
    if s is None:
        raise HTTPException(status_code=404, detail="escenario no encontrado")
    for other in db.scalars(select(Scenario).where(Scenario.is_active.is_(True))):
        other.is_active = False
    s.is_active = True
    db.commit()
    return {"id": s.id, "isActive": s.is_active}


@router.post("/{scenario_id}/deactivate")
def deactivate(scenario_id: int, db: Session = Depends(get_session)) -> dict:
    s = db.get(Scenario, scenario_id)
    if s is None:
        raise HTTPException(status_code=404, detail="escenario no encontrado")
    s.is_active = False
    db.commit()
    return {"id": s.id, "isActive": s.is_active}


@router.delete("/{scenario_id}", status_code=204)
def delete_scenario(scenario_id: int, db: Session = Depends(get_session)) -> Response:
    s = db.get(Scenario, scenario_id)
    if s is not None:
        db.delete(s)  # cascade borra nodos y credenciales
        db.commit()
    return Response(status_code=204)


# ---- nodos ----


@router.post("/{scenario_id}/nodes", response_model=ScenarioNodeDto)
def add_node(scenario_id: int, body: ScenarioNodeInput, db: Session = Depends(get_session)) -> ScenarioNodeDto:
    if db.get(Scenario, scenario_id) is None:
        raise HTTPException(status_code=404, detail="escenario no encontrado")
    n = ScenarioNode(scenario_id=scenario_id, **body.model_dump())
    db.add(n)
    db.commit()
    return ScenarioNodeDto.model_validate(n)


@router.put("/nodes/{node_id}", response_model=ScenarioNodeDto)
def update_node(node_id: int, body: ScenarioNodeInput, db: Session = Depends(get_session)) -> ScenarioNodeDto:
    n = db.get(ScenarioNode, node_id)
    if n is None:
        raise HTTPException(status_code=404, detail="nodo no encontrado")
    for k, v in body.model_dump().items():
        setattr(n, k, v)
    db.commit()
    return ScenarioNodeDto.model_validate(n)


@router.delete("/nodes/{node_id}", status_code=204)
def delete_node(node_id: int, db: Session = Depends(get_session)) -> Response:
    n = db.get(ScenarioNode, node_id)
    if n is not None:
        db.delete(n)
        db.commit()
    return Response(status_code=204)


# ---- credenciales ----


@router.post("/{scenario_id}/credentials", response_model=ScenarioCredentialDto)
def add_cred(
    scenario_id: int, body: ScenarioCredentialInput, db: Session = Depends(get_session)
) -> ScenarioCredentialDto:
    if db.get(Scenario, scenario_id) is None:
        raise HTTPException(status_code=404, detail="escenario no encontrado")
    c = ScenarioCredential(scenario_id=scenario_id, **body.model_dump())
    db.add(c)
    db.commit()
    return ScenarioCredentialDto.model_validate(c)


@router.put("/credentials/{cred_id}", response_model=ScenarioCredentialDto)
def update_cred(
    cred_id: int, body: ScenarioCredentialInput, db: Session = Depends(get_session)
) -> ScenarioCredentialDto:
    c = db.get(ScenarioCredential, cred_id)
    if c is None:
        raise HTTPException(status_code=404, detail="credencial no encontrada")
    for k, v in body.model_dump().items():
        setattr(c, k, v)
    db.commit()
    return ScenarioCredentialDto.model_validate(c)


@router.delete("/credentials/{cred_id}", status_code=204)
def delete_cred(cred_id: int, db: Session = Depends(get_session)) -> Response:
    c = db.get(ScenarioCredential, cred_id)
    if c is not None:
        db.delete(c)
        db.commit()
    return Response(status_code=204)
