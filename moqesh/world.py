"""World: contenido estático INERTE servido por el honeypot (multi-sitio).

Sustituye al laberinto generado como fuente primaria de contenido. Un "World" es un
árbol de ficheros reales en disco (volumen de datos) + un `manifest.json` que monta
uno o varios **portales** bajo distintos prefijos de ruta (como un servidor que aloja
varias webs/vhosts). El honeypot SOLO sirve bytes: nunca ejecuta nada (sin intérprete,
sin backend, sin auth real) — así se añade realismo sin introducir superficie de ataque.

Estructura en disco (`MOQESH_WORLD_PATH`, p.ej. /app/data/world):
    world/
      manifest.json            # {"mounts": [{"prefix": "/docs", "dir": "sites/docs", "spa": false}, ...]}
      sites/<portal>/index.html, assets/..., api/*.json   # estáticos + mock data

Seguridad: la resolución de rutas está acotada a cada directorio de portal (sin escape
por `..`), y resolver una ruta nunca lee fuera del World.
"""

from __future__ import annotations

import html
import json
import logging
import mimetypes
import os
import re
import shutil
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger("moqesh.world")

# Ficheros estáticos por encima de este umbral se sirven en STREAMING (FileResponse) en vez de
# leerse enteros en memoria: permite servir árboles voluminosos (p.ej. generados con genbig) sin
# agotar la RAM del honeypot. Los pequeños (y los dinámicos con tokens) siguen yendo en memoria.
STREAM_THRESHOLD = 1 << 20  # 1 MiB

# Capa fina de valores dinámicos que calcula MOQESH (no los portales): evita el delator de
# endpoints de salud/estado "congelados". Un fichero del World puede incluir estos tokens y
# Moqesh los sustituye al servir. No ejecuta código de los portales; solo rellena unos valores.
_DYN_RE = re.compile(r"\{\{moqesh\.(now_iso|uptime_seconds|minutes_ago)\}\}")
_DEPLOY_BASE = 1_748_000_000  # ~2025-05; uptime = ahora - base (crece en cada petición)


def _dyn_value(key: str) -> str:
    now = int(time.time())
    if key == "now_iso":
        return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if key == "uptime_seconds":
        return str(max(0, now - _DEPLOY_BASE))
    if key == "minutes_ago":
        return str(now // 60 % 7 + 1)
    return ""

# Directorio de la semilla curada empaquetada (plantillas de portal inertes).
SEED_DIR = Path(__file__).parent / "worlds" / "seed"

# Tipos de contenido explícitos (el resto cae a mimetypes). Texto lleva charset.
_CT_TEXT = {
    ".html": "text/html",
    ".htm": "text/html",
    ".css": "text/css",
    ".js": "application/javascript",
    ".mjs": "application/javascript",
    ".json": "application/json",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".csv": "text/csv",
    ".xml": "application/xml",
    ".svg": "image/svg+xml",
    ".yaml": "text/yaml",
    ".yml": "text/yaml",
}


def content_type_for(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext in _CT_TEXT:
        base = _CT_TEXT[ext]
        return base if base.startswith("image/") else f"{base}; charset=utf-8"
    guessed, _ = mimetypes.guess_type(path)
    return guessed or "application/octet-stream"


def default_world_path(db_path: str) -> str:
    """World junto a la DB (mismo volumen persistente)."""
    return os.path.join(os.path.dirname(os.path.abspath(db_path)) or ".", "world")


@dataclass(frozen=True)
class WorldFile:
    body: bytes
    content_type: str
    dynamic: bool = False  # True si Moqesh rellenó tokens dinámicos (sirve sin ETag/Last-Modified)
    path: str | None = None  # ruta en disco del fichero (presente cuando stream=True)
    size: int = 0  # tamaño en bytes (para streaming)
    stream: bool = False  # True = servir en streaming desde `path` (fichero grande), no desde `body`


@dataclass(frozen=True)
class _Mount:
    prefix: str  # sin barra final, "/" para la raíz
    dir: str  # ruta absoluta del portal
    spa: bool  # si True, rutas no encontradas bajo el mount sirven index.html (app SPA)
    autoindex: bool = False  # si True, un directorio sin index.html sirve un listado (estilo servidor)


class World:
    """Carga un manifest y resuelve rutas a ficheros estáticos (solo lectura)."""

    def __init__(self, root: str) -> None:
        self.root = os.path.abspath(root)
        self.mounts: list[_Mount] = []
        self.active = False
        self._load()

    def _load(self) -> None:
        manifest = os.path.join(self.root, "manifest.json")
        if not os.path.isfile(manifest):
            return
        try:
            data = json.loads(Path(manifest).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.warning("[world] manifest.json ilegible en %s", self.root)
            return
        mounts: list[_Mount] = []
        for m in data.get("mounts", []):
            if not isinstance(m, dict):
                continue
            prefix = "/" + str(m.get("prefix", "/")).strip("/")
            d = os.path.abspath(os.path.join(self.root, str(m.get("dir", ""))))
            # El dir del portal debe quedar DENTRO del World (anti-escape).
            if d != self.root and not d.startswith(self.root + os.sep):
                continue
            if not os.path.isdir(d):
                continue
            mounts.append(
                _Mount(
                    prefix=prefix if prefix != "/" else "/",
                    dir=d,
                    spa=bool(m.get("spa")),
                    autoindex=bool(m.get("autoindex")),
                )
            )
        # Más específico primero (longest-prefix match).
        mounts.sort(key=lambda mt: len(mt.prefix), reverse=True)
        self.mounts = mounts
        self.active = bool(mounts)

    def resolve(self, path: str) -> WorldFile | None:
        """Devuelve el fichero a servir, o None si no hay nada (el llamador hace 404).

        El PRIMER mount que casa la ruta "posee" ese espacio: si no encuentra el fichero
        dentro, es 404 (no cae a otro mount), como un vhost/app real.
        """
        if not self.active:
            return None
        path = "/" + path.lstrip("/") if path else "/"
        for mt in self.mounts:
            if mt.prefix == "/":
                rel = path.lstrip("/")
            elif path == mt.prefix or path.startswith(mt.prefix + "/"):
                rel = path[len(mt.prefix) :].lstrip("/")
            else:
                continue
            return self._serve_within(mt, rel)
        return None

    def _serve_within(self, mt: _Mount, rel: str) -> WorldFile | None:
        target = os.path.abspath(os.path.join(mt.dir, rel))
        # Anti-traversal: el objetivo debe quedar dentro del directorio del portal.
        if target != mt.dir and not target.startswith(mt.dir + os.sep):
            return None
        if os.path.isdir(target):
            index = os.path.join(target, "index.html")
            if os.path.isfile(index):
                return self._read(index)
            if mt.autoindex:
                return self._autoindex(mt, target, rel)
            return self._spa_fallback(mt)
        if os.path.isfile(target):
            try:
                size = os.path.getsize(target)
            except OSError:
                return None
            # Fichero grande -> streaming (no se lee en memoria; sin substitución de tokens).
            if size > STREAM_THRESHOLD:
                return WorldFile(body=b"", content_type=content_type_for(target), path=target, size=size, stream=True)
            return self._read(target)
        return self._spa_fallback(mt)

    def _autoindex(self, mt: _Mount, target: str, rel: str) -> WorldFile | None:
        """Genera un listado de directorio (estilo autoindex de nginx) para un dir sin index.html.

        Solo lista los hijos directos de `target` (ya validado dentro del mount); los enlaces son
        rutas absolutas del propio sitio. Es el señuelo de 'directorio abierto' que invita a un
        agente a descargar un árbol voluminoso de ficheros reales (quema de tokens finita)."""
        prefix = "" if mt.prefix == "/" else mt.prefix
        url = (prefix + "/" + rel) if rel else (prefix + "/")
        if not url.startswith("/"):
            url = "/" + url
        if not url.endswith("/"):
            url += "/"
        try:
            names = sorted(os.listdir(target))
        except OSError:
            return None
        dirs = [n for n in names if os.path.isdir(os.path.join(target, n))]
        files = [n for n in names if os.path.isfile(os.path.join(target, n))]
        rows = ['<a href="../">../</a>']
        for n in dirs:
            mtime = self._fmt_time(os.path.getmtime(os.path.join(target, n)))
            rows.append(self._index_row(html.escape(url + n + "/"), html.escape(n + "/"), mtime, "-"))
        for n in files:
            st = os.stat(os.path.join(target, n))
            rows.append(
                self._index_row(html.escape(url + n), html.escape(n), self._fmt_time(st.st_mtime), str(st.st_size))
            )
        title = html.escape(url)
        body = (
            f"<html>\n<head><title>Index of {title}</title></head>\n<body>\n"
            f"<h1>Index of {title}</h1><hr><pre>\n" + "\n".join(rows) + "\n</pre><hr></body>\n</html>\n"
        )
        return WorldFile(body=body.encode(), content_type="text/html; charset=utf-8")

    @staticmethod
    def _fmt_time(ts: float) -> str:
        return datetime.fromtimestamp(ts, UTC).strftime("%d-%b-%Y %H:%M")

    @staticmethod
    def _index_row(href: str, disp: str, mtime: str, size: str) -> str:
        name_cell = disp if len(disp) <= 50 else disp[:47] + "..&gt;"
        pad = " " * max(1, 51 - len(name_cell))
        return f'<a href="{href}">{name_cell}</a>{pad}{mtime}{size:>20}'

    def _spa_fallback(self, mt: _Mount) -> WorldFile | None:
        if not mt.spa:
            return None
        index = os.path.join(mt.dir, "index.html")
        return self._read(index) if os.path.isfile(index) else None

    @staticmethod
    def _read(abs_path: str) -> WorldFile | None:
        try:
            body = Path(abs_path).read_bytes()
        except OSError:
            return None
        ct = content_type_for(abs_path)
        # Sustitución de tokens dinámicos (solo si el fichero los declara).
        if b"{{moqesh." in body:
            try:
                text = body.decode("utf-8")
            except UnicodeDecodeError:
                return WorldFile(body=body, content_type=ct)
            new = _DYN_RE.sub(lambda m: _dyn_value(m.group(1)), text)
            if new != text:
                return WorldFile(body=new.encode(), content_type=ct, dynamic=True)
        return WorldFile(body=body, content_type=ct)


def ensure_seeded(world_path: str) -> bool:
    """Si el World está vacío (sin manifest) y existe la semilla empaquetada, la copia.

    Idempotente: no toca un World ya provisionado (p.ej. por el agente). Devuelve True
    si tras la llamada hay un World con manifest."""
    manifest = os.path.join(world_path, "manifest.json")
    if os.path.isfile(manifest):
        return True
    seed_manifest = SEED_DIR / "manifest.json"
    if not seed_manifest.is_file():
        return False
    try:
        os.makedirs(world_path, exist_ok=True)
        for item in SEED_DIR.iterdir():
            dest = os.path.join(world_path, item.name)
            if item.is_dir():
                shutil.copytree(item, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dest)
        logger.info("[world] semilla copiada a %s", world_path)
        return True
    except OSError:
        logger.warning("[world] no se pudo sembrar el World en %s", world_path, exc_info=True)
        return False
