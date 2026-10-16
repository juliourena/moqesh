"""CLI del worldsmith: `python -m moqesh.worldsmith build|evolve`.

Construye (o evoluciona) el World y publica si pasa la validación de inertness; importa el
pack de cebo como escenario activo. El proveedor y los parámetros salen de la config (prefijo
MOQESH_) y se pueden sobreescribir por flags.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from ..config import settings
from ..world import default_world_path
from .builder import build_world
from .providers import make_provider


def _provider(name_override: str | None, model_override: str | None):
    name = name_override or settings.worldsmith_provider
    api_key = settings.worldsmith_api_key or settings.ai_api_key
    model = model_override or settings.worldsmith_model
    return make_provider(name, api_key=api_key, model=model, base_url=settings.worldsmith_base_url)


def _add_common(sp: argparse.ArgumentParser) -> None:
    sp.add_argument("--provider", help="stub | api | claude_cli (default: config)")
    sp.add_argument("--model", help="modelo del proveedor (api/claude_cli)")
    sp.add_argument("--brand", default="", help="marca/identidad del sitio")
    sp.add_argument("--profile", default="", help="perfil de sitio (saas/corp/ecommerce/...)")
    sp.add_argument("--goal", default="", help="objetivo específico del build")
    sp.add_argument("--portals", type=int, default=0, help="nº aproximado de portales (default: config)")
    sp.add_argument("--world-path", default="", help="ruta del World (default: config/junto a la DB)")
    sp.add_argument("--no-import-bait", action="store_true", help="no importar el pack de cebo")
    sp.add_argument("--json", action="store_true", help="salida JSON")


def _format(report: dict) -> str:
    lines = []
    ok = report.get("ok")
    lines.append(("✓ " if ok else "✗ ") + ("publicado" if report.get("published") else "NO publicado"))
    if report.get("error"):
        lines.append(f"  error: {report['error']}")
    for pr in report.get("problems", [])[:20]:
        lines.append(f"  - {pr}")
    if report.get("world_path"):
        lines.append(f"  world: {report['world_path']}  ({report.get('files')} ficheros)")
    if report.get("bait"):
        b = report["bait"]
        lines.append(f"  cebo: {'ok' if b.get('ok') else b.get('error')} "
                     f"(escenario #{b.get('scenario_id')}, {b.get('nodes')} nodos, activo={b.get('active')})")
    pres = report.get("provider_result", {})
    lines.append(f"  proveedor: {pres.get('provider')} steps={pres.get('steps', '-')} ok={pres.get('ok')}")
    if report.get("note"):
        lines.append(f"  nota: {report['note']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    p = argparse.ArgumentParser(prog="moqesh-worldsmith", description="Constructor IA del World de Moqesh")
    sub = p.add_subparsers(dest="cmd", required=True)
    _add_common(sub.add_parser("build", help="construir un World nuevo"))
    _add_common(sub.add_parser("evolve", help="evolucionar el World actual (rotar cebo, añadir portal)"))
    args = p.parse_args(argv)

    world_path = args.world_path or settings.world_path or default_world_path(settings.db_path)
    import_bait = not args.no_import_bait
    if import_bait:
        from ..db import init_db

        init_db()  # idempotente: asegura el esquema antes de importar el pack

    report = build_world(
        provider=_provider(args.provider, args.model),
        world_path=world_path,
        brand=args.brand or settings.worldsmith_brand,
        profile=args.profile,
        goal=args.goal,
        portals=args.portals or settings.worldsmith_portals,
        import_bait=import_bait,
        seed_from_current=(args.cmd == "evolve"),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else _format(report))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
