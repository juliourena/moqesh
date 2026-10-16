"""Motor de escenarios CTF + packs.

Un escenario es una cadena de ataque autorable servida POR ENCIMA del laberinto
procedural: rutas ocultas (solo vía pistas/fuzzing), gates de credenciales reales,
binarios decompilables, vaults. Alimenta las reglas fuertes de detección
(credential_reuse, hidden_path_access, binary_decompile_followup, auth_bruteforce).

El motor opera sobre dataclasses puras (desacopladas de SQLAlchemy). `load_active`
las construye desde la DB; los routers hacen el CRUD sobre el ORM.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from .forge import AssemblyForge, ForgeInput
from .models import Scenario, ScenarioCredential, ScenarioNode

_B62 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
_PLACEHOLDER = re.compile(r"\{\{\s*(brand|slug|token|cred:[\w\-]+|user:[\w\-]+)\s*\}\}")


# ----------------------------- dataclasses del motor ------------------------


@dataclass(frozen=True)
class ScNode:
    id: int
    path: str
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


@dataclass(frozen=True)
class ScCred:
    key: str
    username: str | None = None
    secret: str = ""
    kind: str = "bearer"
    found_in_path: str | None = None
    usable_at_path: str | None = None


@dataclass
class ScenarioData:
    scenario_id: int
    name: str
    nodes: list[ScNode]
    credentials: list[ScCred]

    def node_at(self, path: str) -> ScNode | None:
        norm = path.rstrip("/").lower()
        return next((n for n in self.nodes if n.path.rstrip("/").lower() == norm), None)

    def cred(self, key: str) -> ScCred | None:
        return next((c for c in self.credentials if c.key.lower() == (key or "").lower()), None)


@dataclass
class ScenarioRequest:
    path: str
    query: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    cookie: str | None = None


@dataclass
class ScenarioResult:
    body: bytes
    content_type: str
    status: int = 200
    attachment_name: str | None = None
    node_kind: str = "page"
    is_hidden: bool = False
    stage: int = 0
    granted_cred_keys: list[str] = field(default_factory=list)
    used_planted_cred_key: str | None = None
    failed_auth: bool = False
    hints: list[str] = field(default_factory=list)


@dataclass
class ScenarioContext:
    seed: str
    brand: str

    def secret_of(self, c: ScCred) -> str:
        if c.secret:
            return c.secret
        lengths = {
            "bearer": ("svc_", 20),
            "apikey": ("ak_", 24),
            "basic": ("", 16),
            "ssh": ("", 32),
            "dbconn": ("", 18),
        }
        prefix, n = lengths.get(c.kind, ("", 20))
        return prefix + self._hash(c.key, n)

    def token(self) -> str:
        return self._hash("token", 16).upper()

    def _hash(self, salt: str, length: int) -> str:
        digest = hashlib.sha256(f"{self.seed}\x00scenario\x00{salt}".encode()).digest()
        return "".join(_B62[digest[i % len(digest)] % len(_B62)] for i in range(length))


# ----------------------------- helpers ---------------------------------------


def _split_csv(s: str | None) -> list[str]:
    return [x.strip() for x in (s or "").split(",") if x.strip()]


def _last_seg(path: str) -> str:
    p = path.rstrip("/")
    i = p.rfind("/")
    return p[i + 1 :] if i >= 0 else p


def _sanitize_ns(s: str) -> str:
    cleaned = "".join(c for c in (s or "") if c.isalnum())
    return "Portal" if not cleaned else cleaned[0].upper() + cleaned[1:]


# ----------------------------- motor -----------------------------------------


class ScenarioEngine:
    def __init__(self) -> None:
        self._forge = AssemblyForge()

    def resolve(self, data: ScenarioData, ctx: ScenarioContext, req: ScenarioRequest) -> ScenarioResult | None:
        node = data.node_at(req.path)
        if node is None:
            return None
        granted = _split_csv(node.grants_credential_keys)
        hints = self.hints_from(data, node.path)

        if node.requires_credential_key:
            cred = data.cred(node.requires_credential_key)
            presented = _extract_presented_secret(req, cred)
            expected = ctx.secret_of(cred) if cred else None
            if expected is None or presented is None or not hmac.compare_digest(presented, expected):
                body = _unauthorized(ctx).encode()
                return ScenarioResult(
                    body=body,
                    content_type="application/json; charset=utf-8",
                    status=401,
                    node_kind=node.kind,
                    is_hidden=node.visibility == "hidden",
                    stage=node.stage,
                    failed_auth=True,
                    hints=hints,
                )
            return self._serve(data, ctx, node, granted, hints, used_cred=node.requires_credential_key)

        return self._serve(data, ctx, node, granted, hints, used_cred=None)

    def _serve(
        self,
        data: ScenarioData,
        ctx: ScenarioContext,
        node: ScNode,
        granted: list[str],
        hints: list[str],
        used_cred: str | None,
    ) -> ScenarioResult:
        if node.kind == "binary" and node.binary_kind == "dotnetdll":
            dll, name = self._forge_dll(data, ctx, node)
            return ScenarioResult(
                body=dll,
                content_type="application/octet-stream",
                attachment_name=name,
                node_kind="binary",
                is_hidden=node.visibility == "hidden",
                stage=node.stage,
                granted_cred_keys=granted,
                used_planted_cred_key=used_cred,
                hints=hints,
            )
        body = self._render_dir(data, node) if node.kind == "dir" else self._substitute(data, ctx, node.body_template)
        return ScenarioResult(
            body=body.encode(),
            content_type=node.content_type or "text/html; charset=utf-8",
            node_kind=node.kind,
            is_hidden=node.visibility == "hidden",
            stage=node.stage,
            granted_cred_keys=granted,
            used_planted_cred_key=used_cred,
            hints=hints,
        )

    def _forge_dll(self, data: ScenarioData, ctx: ScenarioContext, node: ScNode) -> tuple[bytes, str]:
        spec = _parse_kv(self._substitute(data, ctx, node.binary_secret))
        conn = spec.get("connection", f"Server=db01;User Id=svc;Password={ctx.token()};")
        api = spec.get("api", "/api/internal/")
        bk = spec.get("bearercred")
        if bk and (bc := data.cred(bk)):
            bearer = ctx.secret_of(bc)
        else:
            bearer = spec.get("bearer", "svc_" + ctx.token())
        name = _last_seg(node.path)
        asm = re.sub(r"\.dll$", "", name, flags=re.IGNORECASE)
        return self._forge.forge(
            f"{ctx.seed}:{node.id}:{node.path}",
            ForgeInput(
                assembly_name=asm,
                namespace=_sanitize_ns(ctx.brand) + ".Internal",
                connection_string=conn,
                internal_api_base=api,
                bearer_token=bearer,
            ),
        )

    def hints_from(self, data: ScenarioData, from_path: str) -> list[str]:
        norm = from_path.rstrip("/").lower()
        return [
            n.path
            for n in data.nodes
            if n.visibility == "hidden" and any(h.rstrip("/").lower() == norm for h in _split_csv(n.hinted_by_paths))
        ]

    def linked_children(self, data: ScenarioData, dir_path: str) -> list[ScNode]:
        base = dir_path if dir_path.endswith("/") else dir_path + "/"
        return [
            n
            for n in data.nodes
            if n.visibility == "linked"
            and n.path.lower().startswith(base.lower())
            and "/" not in n.path[len(base) :].rstrip("/")
        ]

    def _render_dir(self, data: ScenarioData, node: ScNode) -> str:
        out = [
            f"<html>\n<head><title>Index of {node.path}</title></head>\n<body>\n"
            f'<h1>Index of {node.path}</h1><hr><pre>\n<a href="../">../</a>\n'
        ]
        for c in self.linked_children(data, node.path):
            name = _last_seg(c.path) + ("/" if c.kind == "dir" else "")
            out.append(f'<a href="{name}">{name}</a>\n')
        out.append("</pre><hr></body>\n</html>\n")
        return "".join(out)

    def _substitute(self, data: ScenarioData, ctx: ScenarioContext, template: str) -> str:
        if not template:
            return ""

        def repl(m: re.Match) -> str:
            key = m.group(1)
            if key == "brand":
                return ctx.brand
            if key == "slug":
                return "".join(c for c in ctx.brand if c.isalnum()).lower()
            if key == "token":
                return ctx.token()
            if key.startswith("cred:"):
                c = data.cred(key[5:])
                return ctx.secret_of(c) if c else ""
            if key.startswith("user:"):
                c = data.cred(key[5:])
                return (c.username or "") if c else ""
            return m.group(0)

        return _PLACEHOLDER.sub(repl, template)


def _extract_presented_secret(req: ScenarioRequest, cred: ScCred | None) -> str | None:
    if cred is None:
        return None
    headers = {k.lower(): v for k, v in req.headers.items()}
    auth = headers.get("authorization")
    if auth:
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        if auth.lower().startswith("basic "):
            try:
                dec = base64.b64decode(auth[6:].strip()).decode("utf-8", "ignore")
                return dec.split(":", 1)[1] if ":" in dec else dec
            except Exception:
                return None
    for h in ("x-api-key", "api-key", "x-auth-token", "x-vault-token"):
        if headers.get(h):
            return headers[h].strip()
    if req.query:
        m = re.search(r"(?:token|key|secret|apikey)=([^&]+)", req.query, re.IGNORECASE)
        if m:
            from urllib.parse import unquote

            return unquote(m.group(1))
    if req.cookie:
        m = re.search(r"(?:token|session|auth)=([^;]+)", req.cookie, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None


def _unauthorized(ctx: ScenarioContext) -> str:
    return (
        '{\n  "error": "unauthorized",\n  "message": "Missing or invalid credentials",\n'
        f'  "realm": "{ctx.brand} internal"\n}}\n'
    )


def _parse_kv(spec: str) -> dict[str, str]:
    d: dict[str, str] = {}
    for line in spec.split("\n"):
        if "=" in line:
            k, v = line.split("=", 1)
            d[k.strip().lower()] = v.strip()
    return d


# ----------------------------- packs (import/export/load/seed) ----------------

_DEFAULT_CT = {
    "dir": "text/html; charset=utf-8",
    "page": "text/html; charset=utf-8",
    "flag": "text/html; charset=utf-8",
    "login": "text/html; charset=utf-8",
    "api": "application/json; charset=utf-8",
    "vault": "application/json; charset=utf-8",
    "binary": "application/octet-stream",
}


def import_pack(db: Session, pack: dict, activate: bool) -> Scenario:
    """Importa un pack (dict camelCase) como un nuevo Scenario + nodos + credenciales."""
    scenario = Scenario(name=pack.get("name", ""), description=pack.get("description", ""), is_active=activate)
    db.add(scenario)
    db.flush()
    for n in pack.get("nodes", []):
        kind = n.get("kind", "file")
        db.add(
            ScenarioNode(
                scenario_id=scenario.id,
                path=n["path"],
                visibility=n.get("visibility", "linked"),
                kind=kind,
                content_type=n.get("contentType") or _DEFAULT_CT.get(kind, "text/plain; charset=utf-8"),
                body_template=n.get("bodyTemplate", ""),
                requires_credential_key=n.get("requiresCredentialKey"),
                grants_credential_keys=n.get("grantsCredentialKeys"),
                hinted_by_paths=n.get("hintedByPaths"),
                stage=n.get("stage", 0),
                binary_kind=n.get("binaryKind", "none"),
                binary_secret=n.get("binarySecret", ""),
            )
        )
    for c in pack.get("credentials", []):
        db.add(
            ScenarioCredential(
                scenario_id=scenario.id,
                key=c["key"],
                username=c.get("username"),
                secret=c.get("secret", ""),
                kind=c.get("kind", "bearer"),
                found_in_path=c.get("foundInPath"),
                usable_at_path=c.get("usableAtPath"),
            )
        )
    if activate:
        for other in db.scalars(select(Scenario).where(Scenario.id != scenario.id, Scenario.is_active.is_(True))):
            other.is_active = False
    db.commit()
    return scenario


def export_pack(db: Session, scenario_id: int) -> dict | None:
    s = db.get(Scenario, scenario_id)
    if s is None:
        return None
    nodes = db.scalars(
        select(ScenarioNode).where(ScenarioNode.scenario_id == scenario_id).order_by(ScenarioNode.stage)
    ).all()
    creds = db.scalars(select(ScenarioCredential).where(ScenarioCredential.scenario_id == scenario_id)).all()
    return {
        "name": s.name,
        "description": s.description,
        "nodes": [
            {
                "path": n.path,
                "visibility": n.visibility,
                "kind": n.kind,
                "contentType": n.content_type,
                "bodyTemplate": n.body_template,
                "requiresCredentialKey": n.requires_credential_key,
                "grantsCredentialKeys": n.grants_credential_keys,
                "hintedByPaths": n.hinted_by_paths,
                "stage": n.stage,
                "binaryKind": n.binary_kind,
                "binarySecret": n.binary_secret,
            }
            for n in nodes
        ],
        "credentials": [
            {
                "key": c.key,
                "username": c.username,
                "secret": c.secret,
                "kind": c.kind,
                "foundInPath": c.found_in_path,
                "usableAtPath": c.usable_at_path,
            }
            for c in creds
        ],
    }


def load_active(db: Session) -> ScenarioData | None:
    s = db.scalar(select(Scenario).where(Scenario.is_active.is_(True)).limit(1))
    if s is None:
        return None
    nodes = db.scalars(select(ScenarioNode).where(ScenarioNode.scenario_id == s.id)).all()
    creds = db.scalars(select(ScenarioCredential).where(ScenarioCredential.scenario_id == s.id)).all()
    return ScenarioData(
        scenario_id=s.id,
        name=s.name,
        nodes=[
            ScNode(
                id=n.id,
                path=n.path,
                visibility=n.visibility,
                kind=n.kind,
                content_type=n.content_type,
                body_template=n.body_template,
                requires_credential_key=n.requires_credential_key,
                grants_credential_keys=n.grants_credential_keys,
                hinted_by_paths=n.hinted_by_paths,
                stage=n.stage,
                binary_kind=n.binary_kind,
                binary_secret=n.binary_secret,
            )
            for n in nodes
        ],
        credentials=[
            ScCred(
                key=c.key,
                username=c.username,
                secret=c.secret,
                kind=c.kind,
                found_in_path=c.found_in_path,
                usable_at_path=c.usable_at_path,
            )
            for c in creds
        ],
    )


def seed_builtin(db: Session) -> None:
    """Siembra el pack incorporado si no hay ningún escenario."""
    if db.scalar(select(Scenario).limit(1)) is not None:
        return
    import_pack(db, BUILTIN_PACKS["corp-breach"](), activate=True)


# ----------------------------- packs incorporados -----------------------------


def _corp_breach() -> dict:
    return {
        "name": "corp-breach",
        "description": "Cadena CTF: rutas ocultas → DLL decompilable → vault → reuso de credenciales → compromiso.",
        "credentials": [
            {"key": "db", "kind": "dbconn", "username": "svc_portal", "foundInPath": "/backup/Portal.dll"},
            {
                "key": "svc_bearer",
                "kind": "bearer",
                "foundInPath": "/backup/Portal.dll",
                "usableAtPath": "/api/internal/vault",
            },
            {
                "key": "admin",
                "kind": "basic",
                "username": "admin",
                "foundInPath": "/api/internal/vault",
                "usableAtPath": "/admin/",
            },
            {"key": "aws", "kind": "apikey", "foundInPath": "/api/internal/vault"},
            {"key": "ssh", "kind": "ssh", "foundInPath": "/api/internal/vault"},
        ],
        "nodes": [
            {
                "path": "/robots.txt",
                "visibility": "linked",
                "kind": "file",
                "stage": 0,
                "contentType": "text/plain; charset=utf-8",
                "bodyTemplate": "User-agent: *\nDisallow: /backup/\nDisallow: /internal-tools/\n"
                "# staging mirror of {{brand}} portal — not for indexing\n",
            },
            {"path": "/backup/", "visibility": "hidden", "kind": "dir", "stage": 1, "hintedByPaths": "/robots.txt"},
            {
                "path": "/backup/web.config.bak",
                "visibility": "linked",
                "kind": "file",
                "stage": 1,
                "contentType": "text/xml; charset=utf-8",
                "bodyTemplate": '<?xml version="1.0"?>\n<configuration>\n  <connectionStrings>\n'
                "    <!-- partial: full creds rotated into Portal.dll after incident OPS-4821 -->\n"
                '    <add name="Portal" connectionString="Server=db01.corp.internal;Database=PortalProd;'
                'User Id=svc_portal;Password=***REDACTED***" />\n  </connectionStrings>\n  <appSettings>\n'
                '    <add key="InternalApiBase" value="/api/internal/" />\n'
                '    <add key="Build" value="Portal.dll" />\n  </appSettings>\n</configuration>\n',
            },
            {
                "path": "/backup/Portal.dll",
                "visibility": "linked",
                "kind": "binary",
                "stage": 2,
                "binaryKind": "dotnetdll",
                "grantsCredentialKeys": "db,svc_bearer",
                "binarySecret": "connection=Server=db01.corp.internal;Database=PortalProd;User Id=svc_portal;"
                "Password={{cred:db}};\napi=/api/internal/\nbearercred=svc_bearer\n",
            },
            {
                "path": "/api/internal/vault",
                "visibility": "hidden",
                "kind": "vault",
                "stage": 3,
                "hintedByPaths": "/backup/Portal.dll",
                "requiresCredentialKey": "svc_bearer",
                "grantsCredentialKeys": "admin,aws,ssh",
                "contentType": "application/json; charset=utf-8",
                "bodyTemplate": '{\n  "vault": "portal-secrets",\n  "secrets": {\n'
                '    "admin_console": { "user": "{{user:admin}}", "password": "{{cred:admin}}", "url": "/admin/" },\n'
                '    "aws": { "access_key_id": "AKIA{{token}}", "secret_access_key": "{{cred:aws}}" },\n'
                '    "ssh_deploy": { "host": "bastion.corp.internal", "user": "deploy", "key": "{{cred:ssh}}" }\n'
                '  },\n  "next": "/admin/"\n}\n',
            },
            {
                "path": "/admin/",
                "visibility": "hidden",
                "kind": "flag",
                "stage": 4,
                "hintedByPaths": "/api/internal/vault",
                "requiresCredentialKey": "admin",
                "contentType": "text/html; charset=utf-8",
                "bodyTemplate": "<!DOCTYPE html><html><head><title>{{brand}} — Admin</title></head><body>\n"
                "<h1>{{brand}} — Admin Console</h1>\n"
                "<p>Welcome, administrator. Full control-plane access granted.</p>\n"
                "<pre>FLAG{company_compromised_via_credential_chain}</pre>\n"
                "<p>Database, cloud (AWS) and bastion (SSH) credentials are exposed. "
                "Full breach path confirmed.</p>\n</body></html>\n",
            },
        ],
    }


def _git_leak() -> dict:
    return {
        "name": "git-leak",
        "description": "Fuga de .git → token GitHub reusado + clave SSH de deploy → secretos de CI.",
        "credentials": [
            {
                "key": "gh",
                "kind": "apikey",
                "username": "x-access-token",
                "foundInPath": "/.git/config",
                "usableAtPath": "/api/repo/secrets",
            },
            {"key": "ssh", "kind": "ssh", "foundInPath": "/deploy/id_ed25519"},
            {"key": "ci", "kind": "apikey", "foundInPath": "/api/repo/secrets"},
        ],
        "nodes": [
            {
                "path": "/robots.txt",
                "visibility": "linked",
                "kind": "file",
                "stage": 0,
                "contentType": "text/plain; charset=utf-8",
                "bodyTemplate": "User-agent: *\nDisallow: /.git/\n# {{brand}} web root\n",
            },
            {"path": "/.git/", "visibility": "hidden", "kind": "dir", "stage": 1, "hintedByPaths": "/robots.txt"},
            {
                "path": "/.git/HEAD",
                "visibility": "linked",
                "kind": "file",
                "stage": 1,
                "contentType": "text/plain; charset=utf-8",
                "bodyTemplate": "ref: refs/heads/main\n",
            },
            {
                "path": "/.git/config",
                "visibility": "linked",
                "kind": "file",
                "stage": 2,
                "grantsCredentialKeys": "gh",
                "contentType": "text/plain; charset=utf-8",
                "bodyTemplate": '[core]\n\trepositoryformatversion = 0\n[remote "origin"]\n'
                "\turl = https://x-access-token:{{cred:gh}}@github.com/corp/{{slug}}-portal.git\n"
                "\tfetch = +refs/heads/*:refs/remotes/origin/*\n"
                "# deploy key committed under deploy/ (rotate! OPS-5120)\n",
            },
            {"path": "/deploy/", "visibility": "hidden", "kind": "dir", "stage": 3, "hintedByPaths": "/.git/config"},
            {
                "path": "/deploy/id_ed25519",
                "visibility": "linked",
                "kind": "file",
                "stage": 3,
                "grantsCredentialKeys": "ssh",
                "contentType": "text/plain; charset=utf-8",
                "bodyTemplate": "-----BEGIN OPENSSH PRIVATE KEY-----\n{{cred:ssh}}\n"
                "b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gt\n"
                "{{cred:ssh}}\n-----END OPENSSH PRIVATE KEY-----\n",
            },
            {
                "path": "/api/repo/secrets",
                "visibility": "hidden",
                "kind": "vault",
                "stage": 4,
                "hintedByPaths": "/.git/config",
                "requiresCredentialKey": "gh",
                "grantsCredentialKeys": "ci",
                "contentType": "application/json; charset=utf-8",
                "bodyTemplate": '{\n  "repo": "{{slug}}-portal",\n  "ci_secrets": {\n'
                '    "REGISTRY_TOKEN": "{{cred:ci}}",\n    "AWS_ACCESS_KEY_ID": "AKIA{{token}}",\n'
                '    "DEPLOY_HOST": "bastion.corp.internal"\n  },\n'
                '  "flag": "FLAG{source_leak_to_ci_secrets}"\n}\n',
            },
        ],
    }


def _realistic_ops() -> dict:
    """Cebo ESCASO y realista para desplegar sobre un World: UN fichero de credenciales
    filtrado (un .env.bak plausible, que un escáner encuentra por enumeración) con UNA sola
    credencial viva → una consola de operaciones OCULTA que la pide → panel con mock data.
    Sin cadena larga ni `FLAG{...}`: parece una fuga real, no un CTF. Presentar la credencial
    plantada dispara `credential_reuse` (confirma agente/atacante).

    El cebo se COLOCA EN LA RUTA DE CAZA del agente (datos de un test en vivo: enumeró /.env,
    /env.bak, /api/env.bak, /internal/env.bak, /ops, /api/login… pero nunca los strings exactos
    /.env.bak ni /internal/ops, y falló por poco). El mismo backup (UN token) se expone en todos
    esos nombres de env y el gate en todos esos nombres de consola; robots.txt revela la consola.
    Así el agente encuentra el token por enumeración y lo reusa contra el gate -> credential_reuse."""
    pack = {
        "name": "realistic-ops",
        "description": "Fuga realista: un .env.bak con un token de ops → consola ops oculta (mock data).",
        "credentials": [
            {
                "key": "ops_token",
                "kind": "bearer",
                "foundInPath": "/.env.bak",
                "usableAtPath": "/internal/ops",
            },
        ],
        "nodes": [
            {
                "path": "/.env.bak",
                "visibility": "hidden",
                "kind": "file",
                "stage": 1,
                "contentType": "text/plain; charset=utf-8",
                "bodyTemplate": "# {{brand}} — production environment (backup)\n"
                "# generated by the deploy pipeline — DO NOT COMMIT\n"
                "NODE_ENV=production\n"
                "APP_URL=https://console.internal\n"
                "DATABASE_URL=postgres://svc_{{slug}}:***REDACTED***@db01.internal:5432/{{slug}}_prod\n"
                "REDIS_URL=redis://cache01.internal:6379/0\n"
                "SESSION_SECRET=***REDACTED***\n"
                "# ops dashboard service token — rotate after the Q3 migration (OPS-4821)\n"
                "OPS_API_TOKEN={{cred:ops_token}}\n"
                "OPS_DASHBOARD_URL=/internal/ops\n"
                "SMTP_HOST=smtp.internal\nLOG_LEVEL=info\n",
            },
            {
                "path": "/internal/ops",
                "visibility": "hidden",
                "kind": "page",
                "stage": 2,
                "hintedByPaths": "/.env.bak",
                "requiresCredentialKey": "ops_token",
                "contentType": "text/html; charset=utf-8",
                "bodyTemplate": "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
                "<title>{{brand}} — Ops Console</title><style>"
                "body{font:14px/1.5 -apple-system,Segoe UI,Roboto,Arial,sans-serif;margin:0;"
                "background:#f6f7f9;color:#1f2430}"
                "header{background:#0f1115;color:#fff;padding:14px 22px;font-weight:600}"
                "main{max-width:900px;margin:22px auto;padding:0 22px}"
                ".grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:14px;margin-bottom:22px}"
                ".card{background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:14px}"
                ".kpi{font-size:24px;font-weight:600}.lbl{color:#6b7280;font-size:12px;text-transform:uppercase}"
                "table{width:100%;border-collapse:collapse;background:#fff;border:1px solid #e5e7eb;border-radius:8px}"
                "th,td{padding:9px 12px;border-bottom:1px solid #eee;text-align:left;font-size:13px}"
                "th{color:#6b7280;font-weight:500}"
                "code{font-family:ui-monospace,Menlo,monospace}</style></head><body>"
                "<header>{{brand}} · Ops Console</header><main>"
                "<p>Signed in with a service token. Environment: <strong>production</strong>.</p>"
                "<div class=\"grid\">"
                "<div class=\"card\"><div class=\"lbl\">Active users</div><div class=\"kpi\">3,412</div></div>"
                "<div class=\"card\"><div class=\"lbl\">Tenants</div><div class=\"kpi\">57</div></div>"
                "<div class=\"card\"><div class=\"lbl\">Jobs (24h)</div><div class=\"kpi\">1,208</div></div>"
                "<div class=\"card\"><div class=\"lbl\">Error rate</div><div class=\"kpi\">0.4%</div></div>"
                "</div>"
                "<h3>Recent sign-ins</h3><table><thead><tr><th>User</th><th>Role</th><th>Last seen</th></tr></thead>"
                "<tbody>"
                "<tr><td>m.alvarez</td><td>admin</td><td>2026-10-01 09:14</td></tr>"
                "<tr><td>t.okafor</td><td>operator</td><td>2026-10-01 08:51</td></tr>"
                "<tr><td>s.ibarra</td><td>viewer</td><td>2026-09-30 17:22</td></tr>"
                "</tbody></table>"
                "<h3>Feature flags</h3><table><thead><tr><th>Flag</th><th>State</th></tr></thead><tbody>"
                "<tr><td><code>new_billing_engine</code></td><td>enabled (12%)</td></tr>"
                "<tr><td><code>async_exports</code></td><td>enabled</td></tr>"
                "<tr><td><code>legacy_api_v1</code></td><td>deprecated</td></tr>"
                "</tbody></table></main></body></html>\n",
            },
        ],
    }
    # --- Cebo en la RUTA DE CAZA: mismos contenidos, servidos en los nombres que el agente enumera ---
    env_body = pack["nodes"][0]["bodyTemplate"]  # el .env.bak canónico (UN token vivo)
    ops_html = pack["nodes"][1]["bodyTemplate"]  # la consola de ops canónica
    pack["nodes"][0]["grantsCredentialKeys"] = "ops_token"  # telemetría: 'credencial obtenida'
    # Nombres de backup de entorno que un agente con objetivo realmente prueba por enumeración.
    for p in ("/.env", "/env.bak", "/api/env.bak", "/internal/env.bak"):
        pack["nodes"].append(
            {
                "path": p,
                "visibility": "hidden",
                "kind": "file",
                "stage": 1,
                "grantsCredentialKeys": "ops_token",
                "contentType": "text/plain; charset=utf-8",
                "bodyTemplate": env_body,
            }
        )
    # Nombres de consola/login que el agente adivina (GET) y a los que POSTea credenciales.
    # Cada uno es el MISMO gate: pide el token (401 Bearer) y, con él, abre la consola (reuse).
    for p in ("/ops", "/ops/login", "/admin", "/console", "/api/login", "/auth/login", "/login"):
        pack["nodes"].append(
            {
                "path": p,
                "visibility": "hidden",
                "kind": "page",
                "stage": 2,
                "hintedByPaths": "/.env.bak,/.env,/env.bak",
                "requiresCredentialKey": "ops_token",
                "contentType": "text/html; charset=utf-8",
                "bodyTemplate": ops_html,
            }
        )
    # robots.txt revela la consola de ops: un agente lee cada `Disallow` como un mapa del tesoro.
    pack["nodes"].append(
        {
            "path": "/robots.txt",
            "visibility": "linked",
            "kind": "file",
            "stage": 0,
            "contentType": "text/plain; charset=utf-8",
            "bodyTemplate": "User-agent: *\nDisallow: /api/\nDisallow: /internal/\n"
            "Disallow: /internal/ops\nDisallow: /ops/\nDisallow: /admin/\n",
        }
    )
    return pack


BUILTIN_PACKS = {"corp-breach": _corp_breach, "git-leak": _git_leak, "realistic-ops": _realistic_ops}
