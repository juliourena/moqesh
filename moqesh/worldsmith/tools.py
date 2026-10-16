"""Capa de herramientas del worldsmith: un sandbox de build donde el agente SOLO puede
hacer operaciones seguras. Cada herramienta:

  * valida TODO (ruta + inertness) antes de tocar disco (reusa `validate.py`);
  * está acotada a un directorio de staging (sin escape, con topes de nº de ficheros y bytes);
  * NUNCA lanza al bucle del modelo: devuelve `{"ok": False, "error", "reasons"}` para que el
    agente se autocorrija (p.ej. "extensión .php no permitida" -> reintenta con .html).

Es el contrato que ejecuta cualquier proveedor (stub / API / CLI). El agente nunca toca el
World en vivo: produce un staging que `builder.py` re-valida entero y publica de forma atómica.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import posixpath
import re
from dataclasses import dataclass, field
from pathlib import Path

from .validate import InertnessError, validate_file, validate_manifest

MAX_FILES = 400
MAX_TOTAL_BYTES = 24 * 1024 * 1024  # 24 MiB en todo el build
MAX_SEED_READ_BYTES = 256 * 1024

# Un path de URL (para el cebo): debe ser absoluto del sitio, sin esquema ni traversal.
_URL_PATH_RE = re.compile(r"^/[A-Za-z0-9._~!$&'()*+,;=:@/%-]*$")


def _safe_url_path(p: str) -> str | None:
    p = (p or "").strip()
    if not p.startswith("/") or "://" in p or ".." in p or "\n" in p or len(p) > 200:
        return None
    if not _URL_PATH_RE.match(p):
        return None
    return "/" + p.strip("/") if p != "/" else "/"


@dataclass
class BuildSandbox:
    """Staging aislado donde el agente construye el World. Todo escribe aquí dentro."""

    root: str
    seed_dir: str
    files: dict[str, int] = field(default_factory=dict)  # relpath -> bytes
    bait_pack: dict | None = None
    done: bool = False
    summary: str = ""

    def __post_init__(self) -> None:
        self.root = os.path.abspath(self.root)
        self.seed_dir = os.path.abspath(self.seed_dir)
        os.makedirs(self.root, exist_ok=True)

    # ---------------------------------------------------------------- escritura
    def write_file(self, path: str, content: str, encoding: str = "utf-8") -> dict:
        """Escribe un fichero estático en el build. `encoding`: 'utf-8' (texto) o 'base64' (binario)."""
        if encoding == "base64":
            try:
                body = base64.b64decode(content, validate=True)
            except (binascii.Error, ValueError):
                return {"ok": False, "error": "base64 inválido", "path": path}
        else:
            body = content.encode("utf-8")
        try:
            rel = validate_file(path, body)
        except InertnessError as e:
            return {"ok": False, "error": "viola inertness", "reasons": e.reasons, "path": path}
        if rel not in self.files and len(self.files) >= MAX_FILES:
            return {"ok": False, "error": f"límite de {MAX_FILES} ficheros alcanzado", "path": path}
        projected = sum(v for k, v in self.files.items() if k != rel) + len(body)
        if projected > MAX_TOTAL_BYTES:
            return {"ok": False, "error": f"límite total de {MAX_TOTAL_BYTES} bytes superado", "path": path}
        abs_path = os.path.join(self.root, rel)
        # Contención defensiva extra (el rel ya es seguro, pero re-verificamos el abspath).
        if abs_path != self.root and not os.path.abspath(abs_path).startswith(self.root + os.sep):
            return {"ok": False, "error": "ruta fuera del sandbox", "path": path}
        os.makedirs(os.path.dirname(abs_path) or self.root, exist_ok=True)
        with open(abs_path, "wb") as f:
            f.write(body)
        self.files[rel] = len(body)
        return {"ok": True, "path": rel, "bytes": len(body), "total_files": len(self.files)}

    def delete_file(self, path: str) -> dict:
        try:
            rel = validate_file(path, b"")  # solo valida la ruta/extensión
        except InertnessError as e:
            return {"ok": False, "error": "ruta inválida", "reasons": e.reasons, "path": path}
        if rel not in self.files:
            return {"ok": False, "error": "no existe", "path": rel}
        try:
            os.remove(os.path.join(self.root, rel))
        except OSError:
            pass
        self.files.pop(rel, None)
        return {"ok": True, "path": rel, "total_files": len(self.files)}

    # ---------------------------------------------------------------- lectura
    def list_files(self) -> dict:
        return {"ok": True, "files": sorted(self.files), "total_files": len(self.files)}

    def read_file(self, path: str) -> dict:
        try:
            rel = validate_file(path, b"")
        except InertnessError as e:
            return {"ok": False, "error": "ruta inválida", "reasons": e.reasons, "path": path}
        abs_path = os.path.join(self.root, rel)
        if not os.path.isfile(abs_path):
            return {"ok": False, "error": "no existe", "path": rel}
        try:
            return {"ok": True, "path": rel, "content": Path(abs_path).read_text("utf-8")}
        except (OSError, UnicodeDecodeError):
            return {"ok": False, "error": "no legible como texto", "path": rel}

    def list_seed(self) -> dict:
        out: list[str] = []
        for dp, _dn, fn in os.walk(self.seed_dir):
            for n in fn:
                out.append(os.path.relpath(os.path.join(dp, n), self.seed_dir).replace(os.sep, "/"))
        return {"ok": True, "files": sorted(out)}

    def read_seed(self, path: str) -> dict:
        rel = posixpath.normpath((path or "").replace("\\", "/").lstrip("/"))
        if rel.startswith("..") or rel in (".", ""):
            return {"ok": False, "error": "ruta de semilla inválida", "path": path}
        abs_path = os.path.abspath(os.path.join(self.seed_dir, rel))
        if not abs_path.startswith(self.seed_dir + os.sep) and abs_path != self.seed_dir:
            return {"ok": False, "error": "fuera de la semilla", "path": path}
        if not os.path.isfile(abs_path) or os.path.getsize(abs_path) > MAX_SEED_READ_BYTES:
            return {"ok": False, "error": "no existe o demasiado grande", "path": rel}
        try:
            return {"ok": True, "path": rel, "content": Path(abs_path).read_text("utf-8")}
        except (OSError, UnicodeDecodeError):
            return {"ok": False, "error": "no legible", "path": rel}

    # ---------------------------------------------------------------- manifest
    def set_manifest(self, mounts: list[dict]) -> dict:
        """Registra los portales (prefijo de URL -> directorio del build). Valida antes de escribir."""
        if not isinstance(mounts, list) or not mounts:
            return {"ok": False, "error": "mounts debe ser una lista no vacía"}
        present = set()
        for dp, _dn, _fn in os.walk(self.root):
            rel = posixpath.normpath(os.path.relpath(dp, self.root).replace(os.sep, "/"))
            if rel != ".":
                present.add(rel)
        manifest = {"mounts": mounts}
        problems = validate_manifest(manifest, present)
        if problems:
            return {"ok": False, "error": "manifest inválido", "reasons": problems}
        with open(os.path.join(self.root, "manifest.json"), "wb") as f:
            f.write(json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"))
        return {"ok": True, "mounts": len(mounts)}

    # ---------------------------------------------------------------- cebo
    def plant_bait(
        self,
        credential_key: str,
        leak_paths: list[str],
        leak_body: str,
        gate_paths: list[str],
        gate_body: str,
        credential_kind: str = "bearer",
        robots_disallow: list[str] | None = None,
    ) -> dict:
        """Planta UN honeytoken vivo: un backup filtrado (leak_paths) -> consola con gate (gate_paths).

        Invariante de cebo ESCASO (impuesta aquí, no por el prompt): exactamente UNA credencial viva,
        contenidos inertes, rutas de URL seguras, y el `{{cred:KEY}}` presente en el leak para que al
        reusarse dispare `credential_reuse`. Produce el pack camelCase que importará `builder.py`.
        """
        key = (credential_key or "").strip()
        if not re.fullmatch(r"[a-zA-Z0-9_]{2,40}", key):
            return {"ok": False, "error": "credential_key inválida (usa [a-zA-Z0-9_]{2,40})"}
        leaks = [_safe_url_path(p) for p in (leak_paths or [])]
        gates = [_safe_url_path(p) for p in (gate_paths or [])]
        if not leaks or any(p is None for p in leaks):
            return {"ok": False, "error": "leak_paths vacío o con rutas inválidas"}
        if not gates or any(p is None for p in gates):
            return {"ok": False, "error": "gate_paths vacío o con rutas inválidas"}
        if f"{{{{cred:{key}}}}}" not in leak_body:
            return {"ok": False, "error": f"leak_body debe incluir el placeholder {{{{cred:{key}}}}}"}
        # Inertness de los cuerpos (como .txt y .html respectivamente).
        for _p, body, ext in ((leaks[0], leak_body, ".txt"), (gates[0], gate_body, ".html")):
            try:
                validate_file("bait" + ext, body.encode("utf-8"), allow_scenario_placeholders=True)
            except InertnessError as e:
                return {"ok": False, "error": f"cuerpo del cebo ({ext}) viola inertness", "reasons": e.reasons}
        nodes: list[dict] = []
        for p in leaks:
            nodes.append(
                {
                    "path": p,
                    "visibility": "hidden",
                    "kind": "file",
                    "stage": 1,
                    "grantsCredentialKeys": key,
                    "contentType": "text/plain; charset=utf-8",
                    "bodyTemplate": leak_body,
                }
            )
        hint = ",".join(leaks[:3])
        for p in gates:
            nodes.append(
                {
                    "path": p,
                    "visibility": "hidden",
                    "kind": "page",
                    "stage": 2,
                    "hintedByPaths": hint,
                    "requiresCredentialKey": key,
                    "contentType": "text/html; charset=utf-8",
                    "bodyTemplate": gate_body,
                }
            )
        disallow = [p for p in (_safe_url_path(x) for x in (robots_disallow or [])) if p]
        if disallow:
            lines = "User-agent: *\n" + "".join(f"Disallow: {d}\n" for d in disallow)
            nodes.append(
                {
                    "path": "/robots.txt",
                    "visibility": "linked",
                    "kind": "file",
                    "stage": 0,
                    "contentType": "text/plain; charset=utf-8",
                    "bodyTemplate": lines,
                }
            )
        self.bait_pack = {
            "name": "worldsmith-bait",
            "description": "Cebo generado por el worldsmith: un honeytoken en la ruta de caza -> consola gated.",
            "credentials": [
                {"key": key, "kind": credential_kind, "foundInPath": leaks[0], "usableAtPath": gates[0]}
            ],
            "nodes": nodes,
        }
        return {"ok": True, "credential_key": key, "leak_paths": leaks, "gate_paths": gates, "nodes": len(nodes)}

    # ---------------------------------------------------------------- fin
    def finish(self, summary: str = "") -> dict:
        self.done = True
        self.summary = (summary or "")[:2000]
        return {"ok": True, "files": len(self.files), "has_bait": self.bait_pack is not None}
