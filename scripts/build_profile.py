#!/usr/bin/env python3
"""Construye un perfil de sitio para Moqesh crawleando un sitio real AUTORIZADO.

Herramienta de desarrollo (NO corre dentro del honeypot). Hace un crawl read-only y
acotado del objetivo (reutiliza `moqesh.mimic.profile_site_sync`: httpx + html.parser,
mismo origen, tope de páginas) y escribe un perfil JSON que un despliegue puede
seleccionar con `MOQESH_SITE_PROFILE=<nombre>`.

Datos no confiables: el contenido crawleado es DATO, nunca instrucción. El script solo
extrae estructura (rutas, vocabulario, prefijos de API, banner) y la escribe como JSON;
no ejecuta nada del sitio ni sigue enlaces fuera del origen.

Uso:
    python scripts/build_profile.py --url https://tu-sitio-autorizado.example --name misitio
    python scripts/build_profile.py --url https://... --name x --max-pages 60 --out /tmp/x.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from moqesh.mimic import profile_site_sync  # noqa: E402

_PROFILES_DIR = _REPO / "moqesh" / "profiles"
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,30}$")
# Recursos hoja que parecen colecciones de API (sustantivos limpios, sin extensión).
_RESOURCE_OK = re.compile(r"^[a-z][a-z-]{2,19}$")


def _api_resources_from(profile: dict) -> list[str]:
    """Deriva colecciones de API plausibles de los nombres de recurso del crawl."""
    out: list[str] = []
    for leaf in profile.get("resource_names", []):
        s = str(leaf).lower()
        if _RESOURCE_OK.match(s) and s not in out:
            out.append(s)
    return out[:16]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Construye un perfil de sitio Moqesh desde un sitio real.")
    ap.add_argument("--url", required=True, help="URL del sitio AUTORIZADO a perfilar")
    ap.add_argument("--name", required=True, help="nombre del perfil (a-z0-9_-, 2..31)")
    ap.add_argument("--max-pages", type=int, default=40, help="tope de páginas a crawlear (default 40)")
    ap.add_argument("--timeout", type=float, default=10.0, help="timeout por petición en segundos")
    ap.add_argument("--out", default="", help="ruta de salida (default: moqesh/profiles/<name>.json)")
    args = ap.parse_args(argv)

    if not _NAME_RE.match(args.name):
        ap.error("--name debe casar [a-z0-9][a-z0-9_-]{1,30}")

    print(f"[build_profile] crawleando {args.url} (máx {args.max_pages} páginas)…", file=sys.stderr)
    crawled = profile_site_sync(args.url, max_pages=args.max_pages, timeout=args.timeout)

    profile = {
        "theme": "saas",  # ajústalo a mano si el sitio encaja mejor en corporate/devops/ecommerce
        "server_banner": crawled.get("server_banner") or "nginx",
        "vocabulary": crawled.get("vocabulary", []),
        "paths": crawled.get("paths", []),
        "api_prefixes": crawled.get("api_prefixes", []),
        "api_resources": _api_resources_from(crawled),
        "resource_names": crawled.get("resource_names", []),
    }

    out_path = Path(args.out) if args.out else (_PROFILES_DIR / f"{args.name}.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(profile, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(
        f"[build_profile] perfil '{args.name}' escrito en {out_path} "
        f"({len(profile['vocabulary'])} vocab, {len(profile['api_resources'])} recursos de API). "
        "Revisa 'theme' y 'api_resources' antes de usarlo.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
