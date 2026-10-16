"""Perfiles de sitio built-in, seleccionables por despliegue.

Un perfil es un dict JSON (mismo contrato que el perfil Mimic de `mimic.py`, más
`theme` y `api_resources`) que da al laberinto una taxonomía de rutas, vocabulario y
colecciones de API realistas SIN crawlear nada. Lo consume el generador vía
`LabyrinthOptions.profile`. Elegible con `MOQESH_SITE_PROFILE=<nombre>`.

Contrato (todas opcionales; el generador degrada con elegancia si faltan):
    {
      "theme":          "saas|corporate|devops|ecommerce",  # tema de vocabulario base
      "server_banner":  "cloudflare",                       # cabecera Server
      "vocabulary":     [...],   # palabras de dominio -> nombres de directorio
      "paths":          [...],   # rutas observadas ("/console/", "/billing/")
      "api_prefixes":   [...],   # prefijos de API ("/api/v2")
      "api_resources":  [...],   # colecciones de API que EXISTEN ("tenant", "invoice")
    }
"""

from __future__ import annotations

import json
from pathlib import Path

_DIR = Path(__file__).parent


def available() -> list[str]:
    """Nombres de perfiles built-in disponibles (p.ej. ['corp', 'ecommerce', 'nonprofit', 'saas'])."""
    return sorted(p.stem for p in _DIR.glob("*.json"))


def load_builtin(name: str) -> dict | None:
    """Carga un perfil built-in por nombre; None si no existe o está corrupto.

    Solo acepta nombres de fichero simples (sin separadores de ruta): el nombre viene de
    configuración del operador, pero validarlo evita cualquier escape de directorio.
    """
    if not name or "/" in name or "\\" in name or name.startswith("."):
        return None
    path = _DIR / f"{name}.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None
