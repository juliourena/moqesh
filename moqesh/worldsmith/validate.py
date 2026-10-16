"""Red de seguridad de inertness del worldsmith (defensa en profundidad).

TODO byte que el agente quiera escribir pasa por aquí ANTES de tocar disco, y el
árbol completo se re-valida ANTES de publicarse al World en vivo. El principio no
negociable: Moqesh solo sirve **bytes estáticos** y jamás ejecuta contenido de los
portales. Este módulo hace cumplir eso de forma mecánica (no confía en el prompt):

  1. Rutas seguras: relativas, sin `..`, sin absolutas/NUL, extensión en allowlist.
  2. Sin marcadores de ejecución del lado servidor (`<?php`, `<% %>`, shebangs…).
  3. Sin cargas/callbacks ACTIVOS a orígenes externos (script/link/img/iframe/form,
     fetch/import/XHR/WebSocket, CSS url()/@import). Todo queda same-origin: los
     "logins" postean al gate de Moqesh, nunca a un backend real ni a un beacon.
  4. Límites de tamaño.

El contenido SÍ puede incluir secretos/credenciales *fabricados* (son el cebo); la
invariante de "una sola credencial viva" la impone el lado del pack de escenario,
no este validador, cuyo trabajo es exclusivamente la INERTNESS.
"""

from __future__ import annotations

import os
import posixpath
import re

# Extensiones permitidas -> si es texto se escanea su contenido; binarias solo por tamaño/tipo.
_TEXT_EXTS = {
    ".html", ".htm", ".css", ".js", ".mjs", ".json", ".txt", ".md",
    ".csv", ".xml", ".svg", ".yaml", ".yml", ".webmanifest", ".map",
}
_BINARY_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".avif",
    ".woff", ".woff2", ".ttf", ".otf", ".eot", ".pdf",
}
ALLOWED_EXTS = _TEXT_EXTS | _BINARY_EXTS

MAX_TEXT_BYTES = 512 * 1024          # 512 KiB por fichero de texto
MAX_BINARY_BYTES = 4 * 1024 * 1024   # 4 MiB por binario (fuentes/imágenes)
MAX_REL_DEPTH = 10
MAX_REL_LEN = 240

# Único patrón de plantilla permitido en ficheros del World: tokens dinámicos de Moqesh.
_ALLOWED_DYNAMIC = re.compile(r"\{\{\s*moqesh\.(?:now_iso|uptime_seconds|minutes_ago)\s*\}\}")
# Placeholders del motor de escenario (SOLO válidos en cuerpos de cebo, no en ficheros del World):
# los sustituye el ScenarioEngine al servir, nunca se ejecutan.
_SCENARIO_PLACEHOLDER = re.compile(r"\{\{\s*(?:brand|slug|token|cred:[\w-]+|user:[\w-]+)\s*\}\}")

# Marcadores de ejecución del lado servidor: prohibidos en cualquier parte.
_SERVER_EXEC = [
    (re.compile(r"<\?php", re.I), "PHP abierto (<?php)"),
    (re.compile(r"<\?=", re.I), "PHP short-echo (<?=)"),
    (re.compile(r"<\?(?![x])", re.I), "etiqueta de proceso <? ...?>"),  # permite <?xml
    (re.compile(r"<%[-=@!]?"), "scriptlet ASP/JSP/EJS (<% %>)"),
    (re.compile(r"#!\s*/"), "shebang de script (#!/...)"),
    (re.compile(r"\{%[-\s]"), "bloque de plantilla de servidor ({% %})"),
    (re.compile(r"<jsp:", re.I), "etiqueta JSP"),
]

# Cargas/callbacks ACTIVOS a orígenes externos (absolutos o protocol-relative).
_EXT = r"(?:https?:)?//"  # http://, https:// o //host
_ACTIVE_EXTERNAL = [
    (re.compile(r"<script\b[^>]*\bsrc\s*=\s*['\"]?\s*" + _EXT, re.I), "<script src> externo"),
    (re.compile(r"<link\b[^>]*\bhref\s*=\s*['\"]?\s*" + _EXT, re.I), "<link href> externo"),
    (re.compile(r"<iframe\b[^>]*\bsrc\s*=\s*['\"]?\s*" + _EXT, re.I), "<iframe src> externo"),
    (re.compile(r"<img\b[^>]*\bsrc\s*=\s*['\"]?\s*" + _EXT, re.I), "<img src> externo"),
    (
        re.compile(r"<(?:audio|video|source|track|embed|object)\b[^>]*\b(?:src|data)\s*=\s*['\"]?\s*" + _EXT, re.I),
        "media externo",
    ),
    (re.compile(r"<form\b[^>]*\baction\s*=\s*['\"]?\s*" + _EXT, re.I), "<form action> externo"),
    (re.compile(r"\bfetch\s*\(\s*['\"]\s*" + _EXT, re.I), "fetch() externo"),
    (re.compile(r"\bimport\s*\(\s*['\"]\s*" + _EXT, re.I), "import() dinámico externo"),
    (re.compile(r"\bimport\b[^;\n]*\bfrom\s*['\"]\s*" + _EXT, re.I), "import ... from externo"),
    (re.compile(r"\bnew\s+WebSocket\s*\(\s*['\"]\s*wss?://", re.I), "WebSocket externo"),
    (re.compile(r"\bnew\s+EventSource\s*\(\s*['\"]\s*" + _EXT, re.I), "EventSource externo"),
    (re.compile(r"\.open\s*\(\s*['\"][A-Z]+['\"]\s*,\s*['\"]\s*" + _EXT, re.I), "XMLHttpRequest externo"),
    (re.compile(r"@import\s+(?:url\()?\s*['\"]?\s*" + _EXT, re.I), "CSS @import externo"),
    (re.compile(r"\burl\(\s*['\"]?\s*" + _EXT, re.I), "CSS url() externo"),
    (re.compile(r"\bnavigator\.sendBeacon\s*\(\s*['\"]\s*" + _EXT, re.I), "sendBeacon externo"),
    (re.compile(r"<(?:image|use|feimage)\b[^>]*\b(?:xlink:)?href\s*=\s*['\"]?\s*" + _EXT, re.I), "ref SVG externa"),
    (re.compile(r"\bxlink:href\s*=\s*['\"]?\s*" + _EXT, re.I), "xlink:href externo"),
]


class InertnessError(ValueError):
    """La ruta o el contenido viola la inertness; incluye las razones concretas."""

    def __init__(self, path: str, reasons: list[str]) -> None:
        self.path = path
        self.reasons = reasons
        super().__init__(f"{path}: " + "; ".join(reasons))


def safe_relpath(path: str) -> str:
    """Normaliza a una ruta relativa POSIX segura o lanza InertnessError.

    Rechaza absolutas, traversal (`..`), NUL, backslashes, profundidad/longitud excesivas.
    """
    reasons: list[str] = []
    raw = path or ""
    if "\x00" in raw:
        reasons.append("NUL en la ruta")
    if "\\" in raw:
        reasons.append("backslash en la ruta (usa '/')")
    norm = raw.replace("\\", "/").lstrip("/")
    norm = posixpath.normpath(norm)
    if norm.startswith("..") or "/../" in f"/{norm}/" or norm == "." or norm == "":
        reasons.append("traversal o ruta vacía")
    if os.path.isabs(raw) or raw.startswith("/"):
        reasons.append("ruta absoluta")
    if len(norm) > MAX_REL_LEN:
        reasons.append(f"ruta demasiado larga (>{MAX_REL_LEN})")
    if norm.count("/") + 1 > MAX_REL_DEPTH:
        reasons.append(f"profundidad excesiva (>{MAX_REL_DEPTH})")
    ext = posixpath.splitext(norm)[1].lower()
    if ext not in ALLOWED_EXTS:
        reasons.append(f"extensión no permitida: {ext or '(ninguna)'}")
    if reasons:
        raise InertnessError(path, reasons)
    return norm


def _scan_text(body: bytes, allow_scenario: bool = False) -> list[str]:
    """Escanea contenido de texto en busca de ejecución de servidor y callbacks externos.

    `allow_scenario`: True solo para cuerpos de cebo (permite `{{cred:...}}`, `{{brand}}`, etc.).
    """
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return ["texto no-UTF-8 (debería ser binario o UTF-8 válido)"]
    reasons: list[str] = []
    for rx, label in _SERVER_EXEC:
        if rx.search(text):
            reasons.append(f"marcador de ejecución de servidor: {label}")
    # Oculta los tokens permitidos para que no disparen el chequeo de `{{ ... }}` desconocido.
    scrubbed = _ALLOWED_DYNAMIC.sub("", text)
    if allow_scenario:
        scrubbed = _SCENARIO_PLACEHOLDER.sub("", scrubbed)
    if re.search(r"\{\{", scrubbed):
        allowed = "{{moqesh.*}} (+ placeholders de escenario)" if allow_scenario else "{{moqesh.*}}"
        reasons.append(f"expresión de plantilla desconocida ({{{{ ... }}}}) — solo se permite {allowed}")
    for rx, label in _ACTIVE_EXTERNAL:
        if rx.search(text):
            reasons.append(f"carga/callback externo: {label}")
    return reasons


def validate_file(path: str, body: bytes, *, allow_scenario_placeholders: bool = False) -> str:
    """Valida ruta + contenido de UN fichero. Devuelve la ruta relativa segura o lanza.

    Es el único camino por el que un byte llega al build del World. `allow_scenario_placeholders`
    se usa solo al validar cuerpos del pack de cebo (no ficheros del World, que se sirven crudos).
    """
    rel = safe_relpath(path)  # puede lanzar
    ext = posixpath.splitext(rel)[1].lower()
    reasons: list[str] = []
    is_text = ext in _TEXT_EXTS
    limit = MAX_TEXT_BYTES if is_text else MAX_BINARY_BYTES
    if len(body) > limit:
        reasons.append(f"tamaño {len(body)}B excede el límite {limit}B")
    if is_text:
        reasons.extend(_scan_text(body, allow_scenario=allow_scenario_placeholders))
    if reasons:
        raise InertnessError(path, reasons)
    return rel


def validate_manifest(manifest: dict, present_dirs: set[str]) -> list[str]:
    """Valida el manifest del World: mounts bien formados, dirs dentro del build y presentes.

    `present_dirs` = conjunto de rutas de directorio relativas POSIX que existen en el build.
    Devuelve una lista de problemas (vacía = ok).
    """
    problems: list[str] = []
    if not isinstance(manifest, dict):
        return ["manifest no es un objeto"]
    mounts = manifest.get("mounts")
    if not isinstance(mounts, list) or not mounts:
        return ["manifest.mounts vacío o ausente"]
    seen_prefixes: set[str] = set()
    for i, m in enumerate(mounts):
        if not isinstance(m, dict):
            problems.append(f"mount[{i}] no es un objeto")
            continue
        prefix = "/" + str(m.get("prefix", "/")).strip("/")
        if prefix in seen_prefixes:
            problems.append(f"mount[{i}] prefix duplicado: {prefix}")
        seen_prefixes.add(prefix)
        d = str(m.get("dir", ""))
        try:
            rel_dir = posixpath.normpath(d.replace("\\", "/").lstrip("/"))
        except Exception:
            problems.append(f"mount[{i}] dir inválido: {d!r}")
            continue
        if rel_dir.startswith("..") or os.path.isabs(d):
            problems.append(f"mount[{i}] dir escapa del build: {d!r}")
        elif rel_dir not in present_dirs:
            problems.append(f"mount[{i}] dir no existe en el build: {rel_dir}")
    return problems


def validate_tree(root: str) -> list[str]:
    """Re-valida TODO el build (gate final antes de publicar). Devuelve problemas (vacía = ok).

    Recorre cada fichero por `validate_file` y valida `manifest.json`. Cualquier fichero no
    permitido o con contenido ejecutable/externo invalida la publicación entera.
    """
    problems: list[str] = []
    present_dirs: set[str] = set()
    manifest_obj: dict | None = None
    for dirpath, _dirnames, filenames in os.walk(root):
        rel_dir = posixpath.normpath(os.path.relpath(dirpath, root).replace(os.sep, "/"))
        if rel_dir != ".":
            present_dirs.add(rel_dir)
        for name in filenames:
            abs_path = os.path.join(dirpath, name)
            rel = posixpath.normpath(os.path.relpath(abs_path, root).replace(os.sep, "/"))
            if rel == "manifest.json":
                try:
                    import json

                    manifest_obj = json.loads(open(abs_path, "rb").read().decode("utf-8"))
                except (OSError, ValueError, UnicodeDecodeError) as e:
                    problems.append(f"manifest.json ilegible: {e}")
                continue
            try:
                with open(abs_path, "rb") as f:
                    body = f.read()
                validate_file(rel, body)
            except InertnessError as e:
                problems.append(str(e))
            except OSError as e:
                problems.append(f"{rel}: no se pudo leer ({e})")
    if manifest_obj is None:
        problems.append("falta manifest.json en el build")
    else:
        problems.extend(validate_manifest(manifest_obj, present_dirs))
    return problems
