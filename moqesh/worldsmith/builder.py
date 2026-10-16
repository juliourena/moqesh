"""Orquestación del worldsmith: corre un proveedor en un staging, re-valida TODO el árbol
(gate final de inertness) y, solo si está limpio, publica atómicamente al World e importa el
pack de cebo. El World en vivo nunca se toca hasta que el build pasa la validación completa.
"""

from __future__ import annotations

import logging
import os
import shutil

from ..world import SEED_DIR
from .prompt import SYSTEM_PROMPT, build_brief
from .providers import Provider
from .tools import BuildSandbox
from .validate import validate_tree

logger = logging.getLogger("moqesh.worldsmith")


def _publish(staging: str, world_path: str) -> None:
    """Swap atómico: staging (hermano del world_path) pasa a ser el World; el anterior va a .prev."""
    world_path = os.path.abspath(world_path)
    prev = world_path + ".prev"
    if os.path.exists(prev):
        shutil.rmtree(prev, ignore_errors=True)
    if os.path.exists(world_path):
        os.replace(world_path, prev)  # atómico en el mismo FS
    os.replace(staging, world_path)


def build_world(
    *,
    provider: Provider,
    world_path: str,
    brand: str = "",
    profile: str = "",
    goal: str = "",
    portals: int = 4,
    import_bait: bool = True,
    activate: bool = True,
    seed_from_current: bool = False,
) -> dict:
    """Construye (o evoluciona) el World con el proveedor dado y lo publica si valida.

    Devuelve un reporte. Si la validación final falla, NO publica y deja el World en vivo intacto.
    """
    world_path = os.path.abspath(world_path)
    os.makedirs(os.path.dirname(world_path) or ".", exist_ok=True)
    staging = world_path + ".building"
    if os.path.exists(staging):
        shutil.rmtree(staging, ignore_errors=True)
    os.makedirs(staging, exist_ok=True)

    # Evolución: parte de una copia del World actual para que el agente lo modifique.
    if seed_from_current and os.path.isfile(os.path.join(world_path, "manifest.json")):
        for item in os.listdir(world_path):
            src = os.path.join(world_path, item)
            dst = os.path.join(staging, item)
            if os.path.isdir(src):
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dst)

    sandbox = BuildSandbox(root=staging, seed_dir=str(SEED_DIR))
    brief = build_brief(
        brand=brand,
        profile=profile,
        goal=goal,
        portals=portals,
        extra="Estás EVOLUCIONANDO un World existente: rota el cebo, refresca mock data y añade/varía un portal."
        if seed_from_current
        else "",
    )
    prov_result = provider.build(sandbox, SYSTEM_PROMPT, brief)

    # Gate final de inertness: re-valida TODO el árbol en disco (no confía en las herramientas).
    problems = validate_tree(staging)
    if problems:
        shutil.rmtree(staging, ignore_errors=True)
        return {
            "ok": False,
            "published": False,
            "error": "la validación final de inertness falló; World en vivo intacto",
            "problems": problems[:50],
            "provider_result": prov_result,
        }

    _publish(staging, world_path)
    report = {
        "ok": True,
        "published": True,
        "world_path": world_path,
        "files": sandbox_file_count(world_path),
        "bait": None,
        "provider_result": prov_result,
        "note": "Reinicia/recarga el proceso del honeypot para que sirva el World nuevo "
        "(World se carga al arrancar).",
    }

    if import_bait and sandbox.bait_pack is not None:
        report["bait"] = import_bait_pack(sandbox.bait_pack, activate=activate)
    return report


def import_bait_pack(pack: dict, *, activate: bool = True) -> dict:
    """Importa el pack de cebo producido por el agente como escenario activo."""
    try:
        from ..db import SessionLocal
        from ..scenarios import import_pack

        with SessionLocal() as db:
            s = import_pack(db, pack, activate)
            return {
                "ok": True,
                "scenario_id": s.id,
                "name": s.name,
                "active": s.is_active,
                "nodes": len(pack.get("nodes", [])),
            }
    except Exception as e:  # no tumbar el build publicado por un fallo de import
        logger.warning("[worldsmith] import del pack de cebo falló: %s", e)
        return {"ok": False, "error": str(e)}


def sandbox_file_count(root: str) -> int:
    n = 0
    for _dp, _dn, fn in os.walk(root):
        n += len(fn)
    return n
