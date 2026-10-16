"""Proveedores del worldsmith: ejecutan el bucle de agente sobre un `BuildSandbox`.

- `StubProvider`: determinista, sin LLM (tests sin coste y build offline reproducible).
- `ApiProvider`: bucle tool-use de la Messages API de Anthropic (httpx crudo, como `ai_analyst`).
- `ClaudeCliProvider`: subproceso `claude -p` acotado al sandbox; la red de seguridad es la
  re-validación del árbol completo antes de publicar (`builder.validate_tree`).

Todos comparten `TOOL_SPECS` (contrato de herramientas) y `dispatch()` (ejecución segura).
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from typing import Any, Protocol

from .prompt import CLI_SYSTEM_PROMPT
from .tools import BuildSandbox

logger = logging.getLogger("moqesh.worldsmith")

# Contrato de herramientas (esquema estilo Anthropic tools). El prompt lo refleja en prosa.
TOOL_SPECS: list[dict] = [
    {
        "name": "write_file",
        "description": "Escribe un fichero ESTÁTICO e inerte en el build (HTML/CSS/JS/JSON/SVG/txt...). "
        "El servidor solo sirve bytes; nada se ejecuta. Nada de PHP/ASP/JSP ni cargas externas "
        "(todo same-origin). Devuelve {ok} o {ok:false, reasons:[...]} para corregir.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "ruta relativa en el build, p.ej. sites/console/index.html"},
                "content": {"type": "string", "description": "contenido (texto; base64 si encoding=base64)"},
                "encoding": {"type": "string", "enum": ["utf-8", "base64"], "default": "utf-8"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "delete_file",
        "description": "Borra un fichero del build.",
        "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    },
    {
        "name": "list_files",
        "description": "Lista los ficheros ya escritos en el build.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "read_file",
        "description": "Lee un fichero de texto del build.",
        "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    },
    {
        "name": "list_seed",
        "description": "Lista los ficheros de la semilla curada (plantillas de portal de referencia).",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "read_seed",
        "description": "Lee un fichero de la semilla curada para imitar su estilo.",
        "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    },
    {
        "name": "set_manifest",
        "description": "Registra los portales: cada mount monta un directorio del build bajo un prefijo de URL. "
        "Llamar al final, cuando los directorios ya existen.",
        "input_schema": {
            "type": "object",
            "properties": {
                "mounts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "prefix": {"type": "string", "description": "prefijo de URL, '/' para la raíz"},
                            "dir": {"type": "string", "description": "directorio del build, p.ej. sites/console"},
                            "spa": {"type": "boolean", "default": False},
                        },
                        "required": ["prefix", "dir"],
                    },
                }
            },
            "required": ["mounts"],
        },
    },
    {
        "name": "plant_bait",
        "description": "Planta UN honeytoken vivo en la ruta de caza del atacante: un backup de entorno "
        "filtrado (leak_paths, con el placeholder {{cred:KEY}}) que lleva a una consola protegida "
        "(gate_paths) que exige ese token. robots_disallow revela las rutas como cebo. "
        "EXACTAMENTE una credencial viva.",
        "input_schema": {
            "type": "object",
            "properties": {
                "credential_key": {"type": "string"},
                "credential_kind": {"type": "string", "enum": ["bearer", "apikey", "basic"], "default": "bearer"},
                "leak_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "rutas donde se filtra el backup, p.ej. /.env, /env.bak",
                },
                "leak_body": {
                    "type": "string",
                    "description": "contenido del backup; debe incluir {{cred:KEY}} una vez",
                },
                "gate_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "rutas de la consola gated, p.ej. /internal/ops, /ops",
                },
                "gate_body": {"type": "string", "description": "HTML de la consola al presentar el token"},
                "robots_disallow": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["credential_key", "leak_paths", "leak_body", "gate_paths", "gate_body"],
        },
    },
    {
        "name": "finish",
        "description": "Termina el build. Llamar cuando el World esté completo, el manifest puesto y el cebo plantado.",
        "input_schema": {"type": "object", "properties": {"summary": {"type": "string"}}},
    },
]

_DISPATCH = {
    "write_file": lambda s, a: s.write_file(a.get("path", ""), a.get("content", ""), a.get("encoding", "utf-8")),
    "delete_file": lambda s, a: s.delete_file(a.get("path", "")),
    "list_files": lambda s, a: s.list_files(),
    "read_file": lambda s, a: s.read_file(a.get("path", "")),
    "list_seed": lambda s, a: s.list_seed(),
    "read_seed": lambda s, a: s.read_seed(a.get("path", "")),
    "set_manifest": lambda s, a: s.set_manifest(a.get("mounts", [])),
    "plant_bait": lambda s, a: s.plant_bait(
        a.get("credential_key", ""),
        a.get("leak_paths", []),
        a.get("leak_body", ""),
        a.get("gate_paths", []),
        a.get("gate_body", ""),
        a.get("credential_kind", "bearer"),
        a.get("robots_disallow"),
    ),
    "finish": lambda s, a: s.finish(a.get("summary", "")),
}


def dispatch(sandbox: BuildSandbox, name: str, args: dict[str, Any]) -> dict:
    """Ejecuta una herramienta de forma segura. Nunca lanza: devuelve {ok:false,...} ante cualquier fallo."""
    fn = _DISPATCH.get(name)
    if fn is None:
        return {"ok": False, "error": f"herramienta desconocida: {name}"}
    if not isinstance(args, dict):
        return {"ok": False, "error": "argumentos no son un objeto"}
    try:
        return fn(sandbox, args)
    except Exception as e:  # red de seguridad dura: una herramienta jamás tumba el bucle
        logger.warning("[worldsmith] herramienta %s falló: %s", name, e)
        return {"ok": False, "error": f"excepción en {name}: {e}"}


class Provider(Protocol):
    def build(self, sandbox: BuildSandbox, system_prompt: str, brief: str) -> dict: ...


# ---------------------------------------------------------------- stub (tests/offline)


class StubProvider:
    """Construye un World multi-portal válido + cebo SIN LLM. Determinista y reproducible.

    Sirve para: (a) tests sin coste de la capa de herramientas/validación/publicación de extremo
    a extremo; (b) un build offline por defecto cuando no hay proveedor de IA configurado.
    """

    name = "stub"

    def build(self, sandbox: BuildSandbox, system_prompt: str, brief: str) -> dict:
        brand = _brand_from_brief(brief)
        calls: list[dict] = []

        def call(tool: str, **args: Any) -> dict:
            out = dispatch(sandbox, tool, args)
            calls.append({"tool": tool, "ok": out.get("ok")})
            return out

        css = (
            "body{margin:0;font:14px/1.5 -apple-system,Segoe UI,Roboto,Arial,sans-serif;"
            "background:#f6f7f9;color:#1f2430}header{background:#0f1115;color:#fff;padding:14px 22px;"
            "font-weight:600}main{max-width:960px;margin:26px auto;padding:0 22px}a{color:#2563eb}"
            ".card{background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:16px;margin:10px 0}"
        )
        call("write_file", path="sites/console/assets/app.css", content=css)
        call(
            "write_file",
            path="sites/console/index.html",
            content=(
                '<!doctype html><html lang="en"><head><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width,initial-scale=1">'
                f"<title>{brand} — Operations</title>"
                '<link rel="stylesheet" href="/assets/app.css"></head><body>'
                f"<header>{brand} · Operations</header><main>"
                "<div class=\"card\"><h2>Service status</h2><p>All systems "
                "operational. Uptime {{moqesh.uptime_seconds}}s.</p>"
                '<p>See <a href="/docs/">docs</a> and <a href="/status/">status</a>.</p></div>'
                "</main></body></html>"
            ),
        )
        call(
            "write_file",
            path="sites/console/api/health.json",
            content='{\n  "status": "ok",\n  "version": "2026.9.3",\n  "timestamp": "{{moqesh.now_iso}}",\n'
            '  "uptime_seconds": {{moqesh.uptime_seconds}}\n}\n',
        )
        call(
            "write_file",
            path="sites/docs/index.html",
            content=(
                '<!doctype html><html lang="en"><head><meta charset="utf-8">'
                f"<title>{brand} Docs</title>"
                '<link rel="stylesheet" href="/assets/app.css"></head><body>'
                f"<header>{brand} · Docs</header><main><div class=\"card\"><h1>Getting started</h1>"
                "<p>Authenticate against the gateway for a short-lived service token.</p>"
                '<p><a href="/">← console</a></p></div></main></body></html>'
            ),
        )
        call(
            "write_file",
            path="sites/status/api/summary.json",
            content='{\n  "updated_at": "{{moqesh.now_iso}}",\n  "overall": "operational"\n}\n',
        )
        call(
            "write_file",
            path="sites/status/index.html",
            content=(
                '<!doctype html><html lang="en"><head><meta charset="utf-8">'
                f"<title>{brand} Status</title>"
                '<link rel="stylesheet" href="/assets/app.css"></head><body>'
                f"<header>{brand} · Status</header><main><div class=\"card\">All core systems "
                'operational. Machine-readable: <a href="/status/api/summary.json">summary.json</a>.'
                "</div></main></body></html>"
            ),
        )
        call(
            "set_manifest",
            mounts=[
                {"prefix": "/docs", "dir": "sites/docs", "spa": False},
                {"prefix": "/status", "dir": "sites/status", "spa": False},
                {"prefix": "/", "dir": "sites/console", "spa": False},
            ],
        )
        gate_html = (
            '<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f"<title>{brand} — Ops Console</title></head><body>"
            f"<h1>{brand} Ops Console</h1><p>Signed in with a service token. Environment: production.</p>"
            "<table><tr><th>User</th><th>Role</th></tr><tr><td>m.alvarez</td><td>admin</td></tr>"
            "<tr><td>t.okafor</td><td>operator</td></tr></table></body></html>"
        )
        leak = (
            f"# {brand} — production environment (backup)\nNODE_ENV=production\n"
            "APP_URL=https://console.internal\nSESSION_SECRET=***REDACTED***\n"
            "# ops dashboard service token — rotate after the Q3 migration\n"
            "OPS_API_TOKEN={{cred:ops_token}}\nOPS_DASHBOARD_URL=/internal/ops\n"
        )
        call(
            "plant_bait",
            credential_key="ops_token",
            leak_paths=["/.env.bak", "/.env", "/env.bak", "/api/env.bak"],
            leak_body=leak,
            gate_paths=["/internal/ops", "/ops", "/admin", "/api/login"],
            gate_body=gate_html,
            robots_disallow=["/api/", "/internal/", "/internal/ops", "/ops/"],
        )
        call("finish", summary=f"World stub de {brand}: 3 portales + cebo ops_token.")
        return {"ok": True, "provider": "stub", "calls": calls, "summary": sandbox.summary}


def _brand_from_brief(brief: str) -> str:
    for line in (brief or "").splitlines():
        low = line.lower()
        if "brand" in low or "marca" in low:
            parts = line.split(":", 1)
            if len(parts) == 2 and parts[1].strip():
                return parts[1].strip()[:40]
    return "Harborline"


# ---------------------------------------------------------------- Anthropic API


class ApiProvider:
    """Bucle tool-use contra la Messages API de Anthropic (httpx síncrono, degradación limpia)."""

    name = "api"

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "https://api.anthropic.com",
        max_steps: int = 60,
        max_tokens: int = 4096,
        timeout: float = 120.0,
        transport: object | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model or "claude-sonnet-4-5"
        self.base_url = base_url.rstrip("/")
        self.max_steps = max_steps
        self.max_tokens = max_tokens
        self.timeout = timeout
        self._transport = transport  # para tests (httpx.MockTransport); None = red real

    def build(self, sandbox: BuildSandbox, system_prompt: str, brief: str) -> dict:
        import httpx

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        messages: list[dict] = [{"role": "user", "content": brief}]
        steps = 0
        client_kwargs = {"timeout": self.timeout}
        if self._transport is not None:
            client_kwargs["transport"] = self._transport
        try:
            with httpx.Client(**client_kwargs) as client:
                while steps < self.max_steps and not sandbox.done:
                    steps += 1
                    payload = {
                        "model": self.model,
                        "max_tokens": self.max_tokens,
                        "system": system_prompt,
                        "tools": TOOL_SPECS,
                        "messages": messages,
                    }
                    resp = client.post(self.base_url + "/v1/messages", json=payload, headers=headers)
                    if resp.status_code != 200:
                        return {
                            "ok": False,
                            "provider": "api",
                            "error": f"HTTP {resp.status_code}: {resp.text[:300]}",
                            "steps": steps,
                        }
                    data = resp.json()
                    content = data.get("content", [])
                    messages.append({"role": "assistant", "content": content})
                    tool_uses = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_use"]
                    if not tool_uses:
                        break  # el modelo paró sin más herramientas
                    results = []
                    for tu in tool_uses:
                        out = dispatch(sandbox, tu.get("name", ""), tu.get("input", {}))
                        results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": tu.get("id"),
                                "content": json.dumps(out, ensure_ascii=False),
                                "is_error": not out.get("ok", False),
                            }
                        )
                    messages.append({"role": "user", "content": results})
        except Exception as e:  # red de seguridad: nunca propaga
            logger.warning("[worldsmith] ApiProvider falló: %s", e)
            return {"ok": False, "provider": "api", "error": str(e), "steps": steps}
        return {"ok": sandbox.done, "provider": "api", "steps": steps, "summary": sandbox.summary}


# ---------------------------------------------------------------- claude CLI


class ClaudeCliProvider:
    """Usa el CLI `claude -p` acotado al sandbox (Read/Write/Edit, sin bash/red). El CLI escribe
    los ficheros del World + manifest.json + un `_worldsmith_bait.json` (convención) que luego
    INGERIMOS por nuestro `plant_bait` validado. La inertness la garantiza la re-validación
    completa del árbol antes de publicar (`builder.validate_tree`).

    Autenticación: usa las credenciales del CLI (o `CLAUDE_CODE_OAUTH_TOKEN` del entorno, p.ej. un
    token de `claude setup-token`), heredadas por el subproceso.
    """

    name = "claude_cli"
    BAIT_FILE = "_worldsmith_bait.json"

    def __init__(self, model: str = "", binary: str = "claude", timeout: float = 900.0) -> None:
        self.model = model
        self.binary = binary
        self.timeout = timeout

    def build(self, sandbox: BuildSandbox, system_prompt: str, brief: str) -> dict:
        if shutil.which(self.binary) is None:
            return {"ok": False, "provider": "claude_cli", "error": f"binario '{self.binary}' no encontrado"}
        prompt = f"{CLI_SYSTEM_PROMPT}\n\n--- BRIEF ---\n{brief}\n"
        cmd = [
            self.binary, "-p", prompt,
            "--output-format", "json",
            "--allowedTools", "Read,Write,Edit",
            "--permission-mode", "acceptEdits",
            "--add-dir", sandbox.root,
        ]
        if self.model:
            cmd += ["--model", self.model]
        try:
            proc = subprocess.run(
                cmd, cwd=sandbox.root, capture_output=True, text=True, timeout=self.timeout, check=False,
                env={**os.environ, "CLAUDE_NO_UPDATE": "1"},
            )
        except (subprocess.TimeoutExpired, OSError) as e:
            return {"ok": False, "provider": "claude_cli", "error": str(e)}
        bait = self.ingest(sandbox)
        return {
            "ok": proc.returncode == 0,
            "provider": "claude_cli",
            "returncode": proc.returncode,
            "stderr": proc.stderr[-500:],
            "bait": bait,
        }

    def ingest(self, sandbox: BuildSandbox) -> dict:
        """Reindexa los ficheros que escribió el CLI y planta el cebo desde `_worldsmith_bait.json`.

        El fichero de cebo se borra tras leerlo (no debe publicarse como parte del World). Expuesto
        aparte de `build` para poder testearlo sin invocar el binario real.
        """
        sandbox.files = {}
        for dp, _dn, fn in os.walk(sandbox.root):
            for n in fn:
                ap = os.path.join(dp, n)
                rel = os.path.relpath(ap, sandbox.root).replace(os.sep, "/")
                if rel in ("manifest.json", self.BAIT_FILE):
                    continue
                try:
                    sandbox.files[rel] = os.path.getsize(ap)
                except OSError:
                    pass
        bait_path = os.path.join(sandbox.root, self.BAIT_FILE)
        if not os.path.isfile(bait_path):
            return {"ok": False, "error": f"el CLI no escribió {self.BAIT_FILE} (sin cebo)"}
        try:
            spec = json.loads(open(bait_path, "rb").read().decode("utf-8"))
        except (OSError, ValueError, UnicodeDecodeError) as e:
            os.remove(bait_path)
            return {"ok": False, "error": f"{self.BAIT_FILE} ilegible: {e}"}
        os.remove(bait_path)  # artefacto de build; NO se sirve
        if not isinstance(spec, dict):
            return {"ok": False, "error": f"{self.BAIT_FILE} no es un objeto"}
        return sandbox.plant_bait(
            spec.get("credential_key", ""),
            spec.get("leak_paths", []),
            spec.get("leak_body", ""),
            spec.get("gate_paths", []),
            spec.get("gate_body", ""),
            spec.get("credential_kind", "bearer"),
            spec.get("robots_disallow"),
        )


def make_provider(name: str, *, api_key: str = "", model: str = "", base_url: str = "") -> Provider:
    name = (name or "stub").lower()
    if name == "api":
        return ApiProvider(api_key=api_key, model=model, base_url=base_url or "https://api.anthropic.com")
    if name == "claude_cli":
        return ClaudeCliProvider(model=model)
    return StubProvider()
