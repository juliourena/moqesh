"""Generador del laberinto (Token Exhaust).

Produce contenido **finito, coherente y determinista** por (seed, path): un sitio
real, grande y autoconsistente (no uno "infinito" que un modelo detecta al instante).
La coherencia es el arma: un sitio incoherente deja al agente descartarlo barato;
uno autoconsistente le obliga a leer más para decidir, y eso quema tokens. El gasto
viene del volumen (muchos registros coherentes), de los rabbit-holes plausibles
(READMEs/logs que apuntan a rutas reales de bajo valor) y del tarpit adaptativo.

**Intensidad adaptativa**: a intensidad 0 (desconocido/humano) el sitio se comporta
como uno real finito. A intensidades 1..3 (agente confirmado) crece el volumen de
contenido (prosa/logs más largos, más migajas) — SIEMPRE coherente, nunca infinito
ni incoherente. La paginación de API SIEMPRE termina salvo el opt-in de quema bruta
(`allow_infinite`), que rompe el sigilo a propósito.

Modo Template: vocabulario genérico mutado por seed. Modo Mimic: además mezcla el
vocabulario/rutas del perfil de un sitio real (dict de `mimic.py`) para camuflarse.
"""

from __future__ import annotations

import base64
import html
import json
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from . import vocabulary as vocab
from .rng import SeededRandom

_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# Frases coherentes para READMEs/docs/notas (se rellenan con marca y recursos del tema).
# Sustituyen al "word-salad" anterior, que un modelo detectaba al instante como generado.
_SENTENCE_TEMPLATES = [
    "This runbook documents the {res} workflow for the {brand} platform.",
    "All changes to {res} go through the CI pipeline; do not edit production by hand.",
    "Rotate the service account credentials every 90 days and update the secrets store.",
    "The {res} service loads its configuration from the mounted config map on startup.",
    "Contact the platform team before scaling {res} workers past the documented limits.",
    "Staging mirrors the production topology with synthetic data and fewer replicas.",
    "Metrics are shipped to the internal Prometheus endpoint and retained for thirty days.",
    "Failover is automatic: the standby is promoted after three failed health checks.",
    "See the architecture decision records for the reasoning behind the {res} layout.",
    "Access is limited to the on-call rotation; request it through the access portal.",
    "Nightly backups run at 02:00 UTC and are copied to the offsite bucket.",
    "Requests are rate limited per tenant; exceeding the quota returns HTTP 429.",
    "Schema migrations are applied on deploy and must remain backward compatible.",
    "The legacy {res} endpoint is deprecated and will be removed in the next major release.",
]

# Componentes y plantillas de mensajes para logs de aplicación coherentes.
_LOG_COMPONENTS = ["api", "worker", "scheduler", "auth", "db", "cache", "ingest", "webhook"]
_LOG_LINES = [
    ("INFO", "worker {n} started (pid {pid})"),
    ("INFO", "processed {n} {res} records in {ms}ms"),
    ("INFO", "{res} sync complete: {n} created, {n2} updated"),
    ("INFO", "GET /api/v2/{res} 200 in {ms}ms"),
    ("INFO", "scheduled job {res}-sync enqueued"),
    ("INFO", "health check ok ({n} upstreams)"),
    ("WARN", "slow query on {res} ({ms}ms)"),
    ("WARN", "cache miss ratio high ({pct}%) for {res}"),
    ("WARN", "rate limit reached for tenant {tok}"),
    ("WARN", "retrying {res} request (attempt {n})"),
    ("ERROR", "connection to db-{n}.internal reset, retrying in {ms}ms"),
    ("ERROR", "upstream timeout calling {res} service"),
]

# User-Agents y verbos/estados realistas para el access.log.
_ACCESS_UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "curl/8.4.0",
    "python-requests/2.31.0",
    "Go-http-client/2.0",
    "kube-probe/1.28",
]
_ACCESS_METHODS = ["GET", "GET", "GET", "GET", "POST", "PUT", "DELETE"]
_ACCESS_STATUSES = [200, 200, 200, 200, 200, 304, 301, 404, 302, 401, 500]

# Directorios donde es plausible encontrar secretos; fuera de aquí, los cebos sensibles
# aparecen rara vez (un .env en cada carpeta es irreal y delata el honeypot).
_SENSITIVE_DIRS = {
    "config", "configs", "secrets", "deploy", "backup", "backups", "env", "ci",
    "infra", "terraform", "ansible", "helm", "credentials", ".ssh", "k8s", "vault",
}

# Títulos de sección realistas para docs (en vez de usar palabras-recurso como "Api-key").
_DOC_SECTIONS = [
    "Overview", "Architecture", "Configuration", "Deployment", "Operations",
    "Monitoring", "Security", "Troubleshooting", "Rollback", "Runbook", "FAQ",
]
# Entradas de changelog realistas.
_CHANGELOG_KINDS = ["feat", "fix", "chore", "refactor", "perf", "docs"]
_CHANGELOG_MSGS = [
    "add retry with backoff to {r} delivery", "handle null {r} on tenant sync",
    "bump runtime dependencies", "improve {r} pagination", "cache {r} lookups",
    "fix race condition in the {r} worker", "validate incoming {r} payloads",
    "reduce {r} query latency", "rotate signing keys for {r}",
    "drop deprecated {r} endpoint", "add structured logging to {r}",
]


@dataclass(frozen=True)
class GeneratedPage:
    body: bytes
    content_type: str
    status_code: int = 200
    node_kind: str = "dir"
    attachment_name: str | None = None
    links: list[str] = field(default_factory=list)


@dataclass
class LabyrinthOptions:
    mode: str = "Template"  # Template | Mimic | Static
    seed: str = ""
    realism_level: int = 3
    vocabulary_theme: str = ""
    brand_name: str = ""
    profile: dict | None = None  # perfil Mimic (claves: vocabulary, paths, api_prefixes, server_banner...)
    # Opt-in de quema bruta: a intensidad máxima la API vuelve a paginar sin fin (rompe el sigilo).
    allow_infinite: bool = False


@dataclass(frozen=True)
class _Child:
    name: str
    is_dir: bool
    kind: str


@dataclass(frozen=True)
class _Global:
    theme: str
    brand: str
    slug: str
    style: str
    banner: str
    powered_by: str
    marker: str


# ----------------------------- helpers de rutas -----------------------------


def normalize(path: str) -> str:
    if not path:
        return "/"
    return path if path.startswith("/") else "/" + path


def _depth(path: str) -> int:
    t = path.strip("/")
    return 0 if not t else len(t.split("/"))


def _last_seg(path: str) -> str:
    p = path.rstrip("/")
    i = p.rfind("/")
    return p[i + 1 :] if i >= 0 else p


def _parent_dir(path: str) -> str:
    p = path.rstrip("/")
    i = p.rfind("/")
    return "/" if i <= 0 else p[: i + 1]


def _child_path(parent: str, name: str, is_dir: bool) -> str:
    base = parent if parent.endswith("/") else parent + "/"
    return base + name + ("/" if is_dir else "")


def _enc(s: str) -> str:
    return html.escape(s, quote=True)


def _pad(s: str) -> str:
    return (s[:39] + ">") if len(s) >= 40 else s.ljust(40)


# ----------------------------- clasificación --------------------------------


def _is_binary_name(seg: str) -> bool:
    return seg.endswith("-cli") or seg in ("core", "agent", "worker", "runner", "daemon") or seg.endswith("d")


def _is_api_path(path: str) -> bool:
    low = path.lower()
    return "/api/" in low or low.startswith("/api") or "/graphql" in low or "/v1/" in low or "/v2/" in low


def kind_of(path: str) -> str:
    path = normalize(path)
    if path == "/":
        return "landing"
    if path.endswith("/"):
        return "dir"
    seg = _last_seg(path).lower()
    if seg == ".env" or seg.startswith(".env.") or seg.endswith(".env"):
        return "env"
    if _is_api_path(path) and (seg.endswith(".json") or "." not in seg):
        return "api"
    if seg.endswith(".md"):
        return "readme" if "readme" in seg else "doc"
    if seg.endswith((".yaml", ".yml", ".conf", ".ini")):
        return "config"
    if seg.endswith(".json"):
        return "apiconfig"
    if seg.endswith(".js"):
        return "js"
    if seg.endswith(".sh"):
        return "script"
    if seg.endswith((".log", ".txt")):
        return "noise"
    if seg.endswith(".sql"):
        return "sqldump"
    if seg.endswith((".tar.gz", ".tgz", ".zip", ".bak")):
        return "archive"
    if "." not in seg:
        return "binary" if _is_binary_name(seg) else "resource"
    return "resource"


def _parse_api(path: str) -> tuple[str, int, int | None, bool]:
    """Descompone una ruta de API en (colección, página, id_de_registro, válida).

    - ``/api/v2/tenant``          -> ("/api/v2/tenant", 1, None, True)   # lista, página 1
    - ``/api/v2/tenant/page/3``   -> ("/api/v2/tenant", 3, None, True)   # lista, página 3
    - ``/api/v2/tenant/4172``     -> ("/api/v2/tenant", 1, 4172, True)   # un registro
    - ``/api/v2/tenant/page/x``   -> (..., 1, None, False)               # basura -> 404
    - ``/api/v2/tenant/9/page/2`` -> (..., 2, 9, False)                  # incoherente -> 404
    """
    p = normalize(path).rstrip("/")
    page = 1
    has_page = False
    i = p.find("/page/")
    if i >= 0:
        tail = p[i + 6 :]
        if not tail.isdigit():
            return (p, 1, None, False)
        page = int(tail)
        has_page = True
        p = p[:i]
    seg = _last_seg(p)
    record_id: int | None = None
    if seg.isdigit():
        record_id = int(seg)
        p = _parent_dir(p).rstrip("/") or "/"
        if has_page:  # un registro concreto no pagina
            return (p, page, record_id, False)
    return (p, page, record_id, True)


def _api_collection_path(collection: str, page: int) -> str:
    """Forma canónica de una página de colección (página 1 = la colección a secas)."""
    return collection if page <= 1 else f"{collection}/page/{page}"


def effective_api_path(path: str, query: str | None) -> str:
    """Mapea ``?page=N`` a la forma canónica ``/page/N`` para la paginación de API.

    Así ``/api/v2/x?page=2`` y ``/api/v2/x/page/2`` devuelven lo MISMO (una API real
    pagina por query; si cambiar ``?page=`` no cambiara la respuesta, sería un delator).
    """
    path = normalize(path)
    if not _is_api_path(path) or "/page/" in path or not query:
        return path
    for part in query.split("&"):
        if part.startswith("page="):
            val = part[5:]
            if val.isdigit():
                return path.rstrip("/") + f"/page/{val}"
    return path


# ----------------------------- valores falsos -------------------------------


def _fake_date(rng: SeededRandom) -> str:
    y, mon, day = rng.between(2023, 2026), rng.pick(_MONTHS), rng.between(1, 28)
    return f" {y}-{mon}-{day:02d} {rng.below(24):02d}:{rng.below(60):02d} "


def _clf_epoch(epoch: int) -> str:
    """Fecha en formato CLF (access log) desde un epoch. Independiente de locale (meses propios)."""
    dt = datetime.fromtimestamp(epoch, UTC)
    return f"{dt.day:02d}/{_MONTHS[dt.month - 1]}/{dt.year}:{dt.hour:02d}:{dt.minute:02d}:{dt.second:02d} +0000"


def _iso_epoch(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _prose(rng: SeededRandom, g, sentences: int) -> str:
    """Prosa coherente a partir de plantillas (marca + recursos del tema). Determinista por rng."""
    res_pool = vocab.resources(g.theme)
    return " ".join(
        rng.pick(_SENTENCE_TEMPLATES).format(res=rng.pick(res_pool), brand=g.brand)
        for _ in range(max(1, sentences))
    )


# mtime determinista de un "fichero" (época reciente, 2025-05 .. 2026-08). Compartido entre el
# contenido (p.ej. fechas del CHANGELOG) y las cabeceras Last-Modified/ETag, para que NUNCA la
# fecha de modificación quede antes que lo que el fichero documenta (contradicción imposible).
_MTIME_BASE = 1_748_000_000
_MTIME_SPAN = 40_000_000


def file_mtime_epoch(seed: str, path: str) -> int:
    return _MTIME_BASE + SeededRandom(seed, path + "\x03mtime").below(_MTIME_SPAN)


class LabyrinthGenerator:
    """Generador determinista. Métodos puros; toda la salida deriva de (seed, path)."""

    # ---- contexto global por deployment (estable para un seed) ----

    @staticmethod
    def _global(o: LabyrinthOptions) -> _Global:
        rng = SeededRandom(o.seed, "\u0001global")
        if o.vocabulary_theme:
            theme = vocab.theme_for(rng, o.vocabulary_theme)
        elif o.profile and o.profile.get("theme"):
            theme = vocab.theme_for(rng, str(o.profile["theme"]))
        elif o.profile and o.profile.get("vocabulary"):
            theme = "saas"
        else:
            theme = vocab.theme_for(rng, "")
        brand = o.brand_name or vocab.brand(rng)
        slug = "".join(c for c in brand if c.isalnum()).lower()
        style = rng.pick(["nginx", "apache", "portal"])
        banner = (o.profile or {}).get("server_banner") or vocab.server_banner(rng)
        powered = vocab.powered_by_header(rng)
        marker = rng.alnum(4).upper()
        return _Global(theme, brand, slug, style, banner, powered, marker)

    def global_ctx(self, o: LabyrinthOptions) -> _Global:
        return self._global(o)

    @staticmethod
    def brand_for(o: LabyrinthOptions) -> str:
        return LabyrinthGenerator._global(o).brand

    # ---- vocabulario (mezcla el perfil Mimic si existe) ----

    # Directorios web neutrales, coherentes con cualquier sitio (no son términos de negocio).
    _NEUTRAL_DIRS = ["static", "assets", "media", "uploads", "public", "docs", "api", "images", "files"]

    @staticmethod
    def _dir_pool(o: LabyrinthOptions, g: _Global) -> list[str]:
        prof = o.profile
        if not prof:
            return list(vocab.dirs(g.theme))
        extra = list(prof.get("vocabulary", []))
        extra += [p.strip("/").split("/")[0] for p in prof.get("paths", [])]
        seen: set[str] = set()
        clean: list[str] = []
        for v in extra:
            if v and 2 <= len(v) <= 24 and not v.startswith("_") and v.lower() not in seen:
                seen.add(v.lower())
                clean.append(v)
        if not clean:
            return list(vocab.dirs(g.theme))
        # En Mimic el árbol usa el vocabulario REAL del sitio objetivo + directorios web neutrales,
        # SIN mezclar términos de negocio genéricos (tenants/webhooks/invoices) que no encajan con
        # el sitio imitado y delataban el surtido artificial de cebos.
        return clean + [d for d in LabyrinthGenerator._NEUTRAL_DIRS if d.lower() not in seen]

    # ---- derivación de hijos (pura; compartida por generate y links_for) ----

    @staticmethod
    def _children(o: LabyrinthOptions, g: _Global, path: str) -> list[_Child]:
        # Normaliza la barra final: '/docs' y '/docs/' deben dar EL MISMO listado (un dir real
        # no cambia de contenido por la barra; nginx redirige). Semilla por la ruta sin barra.
        key = path.rstrip("/") or "/"
        rng = SeededRandom(o.seed, key + "\u0002children")
        depth = _depth(path)
        dir_pool = LabyrinthGenerator._dir_pool(o, g)
        res_pool = vocab.resources(g.theme)
        # No repetir el nombre de un ancestro: evita /exports/exports/ (delator de recursión).
        ancestors = {s.lower() for s in key.strip("/").split("/") if s}
        used: set[str] = set()
        children: list[_Child] = []

        def claim(name: str) -> bool:
            key = name.lower()
            if key in used or key in ancestors:
                return False
            used.add(key)
            return True

        # Subdirectorios: el número decrece con la profundidad, así el árbol "termina" como
        # uno real en vez de ramificar siempre 2-6 en cada nivel (ramificación uniforme
        # infinita = delator). El token-exhaust infinito lo aporta la paginación de /api.
        n_dirs = max(0, rng.between(2, 6) - max(0, depth - 1))
        for _ in range(n_dirs):
            name = LabyrinthGenerator._dir_name(rng, dir_pool, res_pool)
            if claim(name):
                children.append(_Child(name, True, "dir"))

        # Rama de API en niveles superiores.
        if depth <= 2 and rng.chance(0.6):
            api_seg = "api"
            if o.profile and o.profile.get("api_prefixes"):
                api_seg = o.profile["api_prefixes"][0].strip("/").split("/")[0] or "api"
            if claim(api_seg):
                children.append(_Child(api_seg, True, "dir"))

        # Archivos: los secretos se concentran en directorios plausibles (config/backup/…),
        # no esparcidos por todas partes (densidad irreal de secretos era un delator).
        parent = _last_seg(path).lower()
        juicy_chance = 0.05 + 0.03 * o.realism_level + (0.30 if parent in _SENSITIVE_DIRS else 0.0)
        for _ in range(rng.between(1, 4)):
            c = LabyrinthGenerator._pick_file(rng, g, depth, juicy_chance)
            if claim(c.name):
                children.append(c)

        # README como breadcrumb (no en todos los directorios).
        if depth >= 1 and rng.chance(0.45) and claim("README.md"):
            children.append(_Child("README.md", False, "readme"))

        return children

    @staticmethod
    def _dir_name(rng: SeededRandom, dir_pool: list[str], res_pool: list[str]) -> str:
        """Nombre de directorio realista: semántico, versión, año o recurso en plural.

        Sin sufijos hex ('session-11ac'/'plan-67c5'), que delataban la generación automática.
        """
        r = rng.below(100)
        if r < 60:
            return rng.pick(dir_pool)
        if r < 72:
            return "v" + str(rng.between(1, 4))
        if r < 84:
            return str(rng.between(2022, 2027))
        if r < 94:
            return rng.pick(res_pool) + "s"
        return rng.pick(["archive", "legacy", "backup", "shared"])

    @staticmethod
    def _pick_file(rng: SeededRandom, g: _Global, depth: int, juicy_chance: float) -> _Child:
        if rng.chance(juicy_chance) and depth >= 1:
            return rng.pick(
                [
                    _Child(".env", False, "env"),
                    _Child("credentials.json", False, "apiconfig"),
                    _Child("config.yaml", False, "config"),
                    _Child("secrets.yml", False, "config"),
                    _Child("backup.sql", False, "archive"),
                    _Child(g.slug + "-cli", False, "binary"),
                ]
            )
        return rng.pick(
            [
                _Child("README.md", False, "readme"),
                _Child("settings.json", False, "apiconfig"),
                _Child("deploy.sh", False, "script"),
                _Child("CHANGELOG.md", False, "doc"),
                _Child("notes.txt", False, "noise"),
                _Child("access.log", False, "noise"),
                _Child("app.js", False, "js"),
                _Child("ARCHITECTURE.md", False, "doc"),
            ]
        )

    # ---- API coherente (finita por colección) ----

    # Recursos cuyos registros llevan un token/secreto (plausible solo en colecciones de
    # credenciales; un `token` en cada registro de "invoice" sería irreal).
    _CRED_RESOURCES = {"api-key", "apikey", "secret", "token", "webhook", "session", "connector", "credential"}

    @staticmethod
    def _api_valid_resources(o: LabyrinthOptions, g: _Global) -> set[str]:
        """Colecciones de API que EXISTEN en el deployment. Un sondeo a /api/v2/<inexistente>
        da 404, como en un sitio real finito (antes TODA ruta de API devolvía 200: delator).

        Con perfil (built-in o Mimic) manda su lista de recursos de API; si el perfil no la
        aporta, se cae al vocabulario genérico del tema del deployment."""
        prof = o.profile or {}
        res = {str(v).lower() for v in prof.get("api_resources", []) if v}
        for v in prof.get("resource_names", []):  # recursos hoja de un crawl Mimic (login, app.js…)
            s = str(v).lower()
            if s and "." not in s and s.isalpha() and 3 <= len(s) <= 20:
                res.add(s)
        return res or {r.lower() for r in vocab.resources(g.theme)}

    def _api_collection_exists(self, o: LabyrinthOptions, g: _Global, collection: str) -> bool:
        return _last_seg(collection).lower() in self._api_valid_resources(o, g)

    @staticmethod
    def _api_shape(o: LabyrinthOptions, collection: str) -> tuple[int, int]:
        """(total, per_page) ESTABLES por colección: no cambian entre páginas ni peticiones.
        Antes el total se re-sorteaba por página (variaba en cada request): el delator principal."""
        r = SeededRandom(o.seed, collection + "\u0004apishape")
        per_page = r.pick([20, 25, 50, 100])
        total = r.between(12, 400) if r.chance(0.6) else r.between(400, 9000)
        return total, per_page

    @staticmethod
    def _api_record(o: LabyrinthOptions, g: _Global, collection: str, rid: int) -> dict:
        """Registro ESTABLE por (colección, id): el mismo id da los mismos campos en la lista y
        en /colección/<id>. Un agente puede cruzar respuestas y la coherencia se sostiene."""
        r = SeededRandom(o.seed, f"{collection}\u0004rec\u0004{rid}")
        res = _last_seg(collection).lower()
        rec: dict = {
            "id": rid,
            "name": f"{res}-{r.between(1000, 9999)}",
            "status": r.pick(["active", "active", "active", "disabled", "pending"]),
            "owner": f"user_{r.hex(6)}",
            "created": _iso_epoch(_MTIME_BASE + r.below(_MTIME_SPAN)),
        }
        if res in LabyrinthGenerator._CRED_RESOURCES:
            rec["token"] = r.alnum(20)
        return rec

    # ---- API pública ----

    def generate(self, o: LabyrinthOptions, path: str, intensity: int = 0) -> GeneratedPage:
        path = normalize(path)
        g = self._global(o)
        rng = SeededRandom(o.seed, path)
        kind = kind_of(path)

        renderers = {
            "env": (self._render_env, "text/plain; charset=utf-8"),
            "config": (self._render_config, "text/yaml; charset=utf-8"),
            "apiconfig": (self._render_json_config, "application/json; charset=utf-8"),
            "readme": (self._render_readme, "text/markdown; charset=utf-8"),
            "doc": (self._render_doc, "text/markdown; charset=utf-8"),
            "api": (self._render_api, "application/json; charset=utf-8"),
            "js": (self._render_js, "application/javascript; charset=utf-8"),
            "script": (self._render_script, "text/x-shellscript; charset=utf-8"),
            "noise": (self._render_noise, "text/plain; charset=utf-8"),
            "sqldump": (self._render_sql, "application/sql; charset=utf-8"),
        }
        if kind in ("landing", "dir"):
            return self._html(self._render_listing(o, g, path, kind == "landing"), kind)
        if kind in ("archive", "binary"):
            return self._binary(g, rng, path)
        if kind in renderers:
            fn, ct = renderers[kind]
            node_kind = "noise" if kind == "doc" else ("config" if kind == "apiconfig" else kind)
            return self._text(fn(o, g, rng, path, intensity), ct, node_kind)
        return self._html(self._render_listing(o, g, path, False), "resource")

    def is_reachable(self, o: LabyrinthOptions, path: str, intensity: int = 0) -> bool:
        """Un path del árbol de ficheros es alcanzable SOLO si su último segmento es un hijo
        que el directorio padre generaría. Así el honeypot se comporta como un sitio real
        finito: lo enlazado responde 200, lo que no (p.ej. /favicon.ico, /index.php, rutas al
        azar que sondea un fingerprinter) responde 404 — no 'todo 200', que era el delator.

        Las rutas de API también son finitas: una colección existe si está en el vocabulario
        del deployment; una página, si está en rango [1, última]; un registro, si su id ∈
        [1, total]. Fuera de eso -> 404 (antes CUALQUIER /api/... daba 200, delator inmediato).
        """
        path = normalize(path)
        if path == "/":
            return True
        g = self._global(o)
        if _is_api_path(path):
            collection, page, rid, valid = _parse_api(path)
            if not valid or not self._api_collection_exists(o, g, collection):
                return False
            if o.allow_infinite and intensity >= 3:
                return True  # opt-in de quema bruta: la API vuelve a ser infinita
            total, per_page = self._api_shape(o, collection)
            if rid is not None:
                return 1 <= rid <= total
            return 1 <= page <= max(1, math.ceil(total / per_page))
        parent = _parent_dir(path)
        seg = _last_seg(path)
        names = {c.name.lower() for c in self._children(o, g, parent)}
        return seg.lower() in names

    def links_for(self, o: LabyrinthOptions, path: str, intensity: int = 0) -> list[str]:
        path = normalize(path)
        g = self._global(o)
        kind = kind_of(path)
        if kind in ("landing", "dir", "resource"):
            return [_child_path(path, c.name, c.is_dir) for c in self._children(o, g, path)]
        if kind == "api":
            collection, page, rid, valid = _parse_api(path)
            if not valid or rid is not None or not self._api_collection_exists(o, g, collection):
                return []
            if o.allow_infinite and intensity >= 3:
                return [_api_collection_path(collection, page + 1)]
            total, per_page = self._api_shape(o, collection)
            last_page = max(1, math.ceil(total / per_page))
            return [_api_collection_path(collection, page + 1)] if page < last_page else []
        if kind == "readme":
            return self._readme_breadcrumbs(o, g, path, intensity)
        return []

    # ---- renderers de directorios ----

    def _render_listing(self, o: LabyrinthOptions, g: _Global, path: str, is_landing: bool) -> str:
        children = self._children(o, g, path)
        if g.style == "apache":
            return self._apache_index(path, children)
        if g.style == "portal":
            return self._portal_index(g, path, children, is_landing)
        return self._nginx_index(path, children)

    @staticmethod
    def _nginx_index(path: str, children: list[_Child]) -> str:
        out = [
            f"<html>\n<head><title>Index of {_enc(path)}</title></head>\n<body>\n"
            f"<h1>Index of {_enc(path)}</h1><hr><pre>\n"
        ]
        if path != "/":
            out.append('<a href="../">../</a>\n')
        rng = SeededRandom("listing", path)
        for c in children:
            name = c.name + ("/" if c.is_dir else "")
            size = "-" if c.is_dir else str(rng.between(312, 98000))
            out.append(f'<a href="{_enc(name)}">{_enc(_pad(name))}</a>{_fake_date(rng)}    {size.rjust(10)}\n')
        out.append("</pre><hr></body>\n</html>\n")
        return "".join(out)

    @staticmethod
    def _apache_index(path: str, children: list[_Child]) -> str:
        out = [
            '<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 3.2 Final//EN">\n<html>\n<head><title>Index of ',
            _enc(path),
            f"</title></head>\n<body>\n<h1>Index of {_enc(path)}</h1>\n",
            '<table><tr><th>Name</th><th>Last modified</th><th>Size</th></tr><tr><th colspan="3"><hr></th></tr>\n',
        ]
        if path != "/":
            out.append('<tr><td><a href="../">Parent Directory</a></td><td>&nbsp;</td><td>-</td></tr>\n')
        rng = SeededRandom("apache", path)
        for c in children:
            name = c.name + ("/" if c.is_dir else "")
            size = "-" if c.is_dir else f"{rng.between(1, 420)}K"
            out.append(
                f'<tr><td><a href="{_enc(name)}">{_enc(name)}</a></td><td>{_fake_date(rng)}</td><td>{size}</td></tr>\n'
            )
        out.append("</table></body></html>\n")
        return "".join(out)

    @staticmethod
    def _portal_index(g: _Global, path: str, children: list[_Child], is_landing: bool) -> str:
        title = (g.brand + " — Internal") if is_landing else (g.brand + " · " + _enc(path))
        out = [
            '<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8"><title>',
            _enc(title),
            "</title><style>body{font-family:system-ui,Segoe UI,Arial,sans-serif;margin:0;"
            "background:#0f1115;color:#e6e6e6}header{padding:18px 28px;border-bottom:1px solid #222;"
            "background:#151821}main{padding:24px 28px}.badge{font-size:11px;color:#f5a623;"
            "border:1px solid #f5a623;border-radius:4px;padding:1px 6px;margin-left:8px}"
            ".grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px}"
            "a.card{display:block;padding:14px 16px;background:#1b1f2a;border:1px solid #262c3a;"
            "border-radius:8px;color:#cfe3ff;text-decoration:none}a.card:hover{border-color:#3b82f6}"
            "small{color:#8a93a6}</style></head><body>\n",
            f'<header><strong>{_enc(g.brand)}</strong><span class="badge">STAGING</span>',
            f"<div><small>{_enc(path)}</small></div></header><main>\n",
        ]
        if is_landing:
            out.append("<p>Internal resource index. Authenticated mirror of the production control plane.</p>\n")
        out.append('<div class="grid">\n')
        if path != "/":
            out.append('<a class="card" href="../">../ <small>parent</small></a>\n')
        for c in children:
            name = c.name + ("/" if c.is_dir else "")
            # Mostrar "folder" o la extensión del fichero, NO la taxonomía interna del generador
            # (antes se filtraba literal "noise"/"archive"/"readme", delator inmediato).
            meta = "folder" if c.is_dir else (c.name.rsplit(".", 1)[-1] if "." in c.name else "file")
            out.append(f'<a class="card" href="{_enc(name)}">{_enc(name)} <small>{_enc(meta)}</small></a>\n')
        out.append("</div></main></body></html>\n")
        return "".join(out)

    # ---- renderers de archivos ----

    @staticmethod
    def _render_env(o: LabyrinthOptions, g: _Global, rng: SeededRandom, path: str, intensity: int = 0) -> str:
        env_name = "staging" if "stag" in path.lower() else "production"
        out = [
            f"# {g.brand} — environment ({path})\n",
            f"NODE_ENV={env_name}\n",
            f"APP_NAME={g.slug}\n",
            f"DATABASE_URL=postgres://svc_{g.slug}:{rng.alnum(16)}@db-{rng.between(1, 9)}"
            f".internal:5432/{g.slug}_{'stg' if env_name == 'staging' else 'prod'}\n",
            f"REDIS_URL=redis://cache-{rng.between(1, 6)}.internal:6379/0\n",
        ]
        if o.realism_level >= 2:
            out.append(f"AWS_ACCESS_KEY_ID=AKIA{rng.alnum(16).upper()}\n")
            out.append(f"AWS_SECRET_ACCESS_KEY={rng.alnum(40)}\n")
        out.append(f"JWT_SECRET={rng.alnum(32)}\n")
        if o.realism_level >= 3:
            out.append(f"VAULT_TOKEN=hvs.{rng.alnum(24)}\n")
            out.append(f"STRIPE_SECRET_KEY=sk_live_{rng.alnum(24)}\n")
        out.append("SMTP_HOST=smtp.internal\nLOG_LEVEL=info\n")
        return "".join(out)

    @staticmethod
    def _render_config(o: LabyrinthOptions, g: _Global, rng: SeededRandom, path: str, intensity: int = 0) -> str:
        res = vocab.resources(g.theme)
        out = [
            f"# {g.brand} service config\n",
            f"service: {g.slug}\n",
            f"version: {rng.between(1, 4)}.{rng.below(20)}.{rng.below(40)}\n",
            f"replicas: {rng.between(2, 9)}\n",
            "endpoints:\n",
        ]
        for _ in range(3):
            out.append(f"  - /{rng.pick(res)}/v{rng.between(1, 3)}\n")
        out += [
            "credentials:\n",
            f"  api_key: {rng.alnum(22)}\n",
            f"  signing_secret: {rng.alnum(32)}\n",
            "features:\n  beta_console: true\n  audit_log: true\n",
        ]
        return "".join(out)

    @staticmethod
    def _render_json_config(o: LabyrinthOptions, g: _Global, rng: SeededRandom, path: str, intensity: int = 0) -> str:
        return (
            "{\n"
            f'  "service": "{g.slug}",\n'
            f'  "api_key": "{rng.alnum(24)}",\n'
            f'  "issued_at": "{_iso_epoch(file_mtime_epoch(o.seed, path))}",\n'
            '  "scopes": ["read", "write", "admin"],\n'
            f'  "endpoint": "https://api.{g.slug}.internal",\n'
            f'  "webhook_secret": "whsec_{rng.alnum(24)}"\n'
            "}\n"
        )

    def _render_readme(self, o: LabyrinthOptions, g: _Global, rng: SeededRandom, path: str, intensity: int = 0) -> str:
        crumbs = self._readme_breadcrumbs(o, g, path, intensity)
        out = [
            f"# {g.brand} — Operations\n\n",
            f"Internal runbook for `{path}`. Do not share outside the org.\n\n",
            "## Setup\n\n```bash\n",
            "cp .env.example .env    # set the values for your environment\n",
            f"./{g.slug}-cli --config config.yaml migrate\n",
            f"./{g.slug}-cli --config config.yaml deploy --env staging\n```\n\n",
            "## Resources\n\n",
        ]
        out += [f"- [`{c}`]({c})\n" for c in crumbs]
        # A mayor intensidad, más prosa coherente (más que leer = más tokens), nunca incoherencia.
        out.append("\n## Notes\n\n" + _prose(rng, g, 3 + 2 * intensity) + "\n")
        return "".join(out)

    def _readme_breadcrumbs(self, o: LabyrinthOptions, g: _Global, path: str, intensity: int = 0) -> list[str]:
        d = _parent_dir(path)
        siblings = self._children(o, g, d)
        # Las migajas son SIEMPRE hermanos reales (alcanzables): a mayor intensidad se muestran más,
        # pero nunca se inventan rutas que darían 404. La alcanzabilidad no depende de la intensidad.
        crumbs = [_child_path(d, c.name, False) for c in siblings if not c.is_dir and "README" not in c.name]
        return crumbs[: 5 + 3 * intensity]

    @staticmethod
    def _render_doc(o: LabyrinthOptions, g: _Global, rng: SeededRandom, path: str, intensity: int = 0) -> str:
        if "changelog" in _last_seg(path).lower():
            return LabyrinthGenerator._render_changelog(o, g, rng, path, intensity)
        title = _last_seg(path).rsplit(".", 1)[0].replace("-", " ").replace("_", " ").title()
        out = [f"# {g.brand} — {title}\n\n"]
        used: set[str] = set()
        for _ in range(rng.between(3, 6) + intensity):
            sec = rng.pick(_DOC_SECTIONS)
            if sec in used:
                continue
            used.add(sec)
            out.append(f"## {sec}\n\n" + _prose(rng, g, rng.between(2, 4) + intensity) + "\n\n")
        return "".join(out)

    @staticmethod
    def _render_changelog(o: LabyrinthOptions, g: _Global, rng: SeededRandom, path: str, intensity: int = 0) -> str:
        res = vocab.resources(g.theme)
        out = [f"# Changelog\n\nAll notable changes to {g.brand} are documented in this file.\n\n"]
        # La entrada más reciente coincide con el mtime del fichero (= última vez que se tocó);
        # las versiones y fechas DECRECEN de forma monótona hacia abajo, como un changelog real.
        cur = datetime.fromtimestamp(file_mtime_epoch(o.seed, path), UTC)
        major, minor, patch = rng.between(2, 6), rng.between(0, 12), rng.between(0, 9)
        for _ in range(rng.between(5, 9) + 2 * intensity):
            out.append(f"## [{major}.{minor}.{patch}] - {cur:%Y-%m-%d}\n")
            for _ in range(rng.between(2, 5)):
                out.append(f"- {rng.pick(_CHANGELOG_KINDS)}: {rng.pick(_CHANGELOG_MSGS).format(r=rng.pick(res))}\n")
            out.append("\n")
            cur -= timedelta(days=rng.between(6, 55))  # entrada anterior = más vieja
            if patch > 0:
                patch -= 1
            elif minor > 0:
                minor -= 1
                patch = rng.between(0, 9)
            else:
                major = max(1, major - 1)
                minor = rng.between(2, 12)
        return "".join(out)

    def _render_api(self, o: LabyrinthOptions, g: _Global, rng: SeededRandom, path: str, intensity: int = 0) -> str:
        collection, page, rid, _valid = _parse_api(path)
        total, per_page = self._api_shape(o, collection)
        if rid is not None:  # GET de un registro concreto -> el MISMO que aparece en la lista
            return json.dumps(self._api_record(o, g, collection, rid), indent=2) + "\n"
        last_page = max(1, math.ceil(total / per_page))
        start = (page - 1) * per_page + 1
        end = min(page * per_page, total)
        data = [self._api_record(o, g, collection, i) for i in range(start, end + 1)] if start <= total else []
        # Paginación FINITA: `next` es null en la última página (antes era siempre page+1 ->
        # infinito -> delator). El opt-in de quema bruta se maneja fuera, en links_for/is_reachable.
        body = {
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": last_page,
            "data": data,
            "links": {
                "self": _api_collection_path(collection, page),
                "next": _api_collection_path(collection, page + 1) if page < last_page else None,
                "prev": _api_collection_path(collection, page - 1) if page > 1 else None,
            },
        }
        return json.dumps(body, indent=2) + "\n"

    @staticmethod
    def _render_js(o: LabyrinthOptions, g: _Global, rng: SeededRandom, path: str, intensity: int = 0) -> str:
        res = vocab.resources(g.theme)
        hidden = "/" + rng.pick(res) + "/internal/" + rng.hex(6)
        b64 = base64.b64encode(hidden.encode()).decode("ascii")
        return (
            f"/*! {g.slug} bundle */\n"
            f'(function(){{var _0x="{b64}";\n'
            "var api=atob(_0x);\n"
            f"fetch(api,{{headers:{{'x-{g.slug}-key':'{rng.alnum(18)}'}}}});\n"
            "})();\n"
        )

    @staticmethod
    def _render_script(o: LabyrinthOptions, g: _Global, rng: SeededRandom, path: str, intensity: int = 0) -> str:
        # Script de deploy realista: NO hace curl a rutas del propio sitio (eso dejaba migajas
        # colgantes que daban 404 y delataban el montaje). Referencia ficheros locales.
        return (
            "#!/usr/bin/env bash\n"
            f"# {g.brand} deploy helper\n"
            "set -euo pipefail\n"
            'ENV="${1:-staging}"\n'
            'cd "$(dirname "$0")"\n'
            f'echo "Deploying {g.slug} to ${{ENV}}..."\n'
            'docker compose -f "docker-compose.${ENV}.yml" pull\n'
            'docker compose -f "docker-compose.${ENV}.yml" up -d --remove-orphans\n'
            f'./{g.slug}-cli migrate --env "${{ENV}}"\n'
            'echo "done."\n'
        )

    @staticmethod
    def _render_sql(o: LabyrinthOptions, g: _Global, rng: SeededRandom, path: str, intensity: int = 0) -> str:
        """Volcado SQL realista (TEXTO, no un binario ELF). Fechas <= mtime del fichero."""
        res = vocab.resources(g.theme)
        tbl = rng.pick(res).replace("-", "_") + "s"
        end = file_mtime_epoch(o.seed, path)
        out = [
            f"-- {g.brand} database dump\n",
            f"-- Host: db-{rng.between(1, 9)}.internal    Database: {g.slug}_prod\n",
            "-- ------------------------------------------------------\n",
            "SET NAMES utf8mb4;\nSET FOREIGN_KEY_CHECKS=0;\n\n",
            f"DROP TABLE IF EXISTS `{tbl}`;\n",
            f"CREATE TABLE `{tbl}` (\n"
            "  `id` bigint NOT NULL AUTO_INCREMENT,\n"
            "  `name` varchar(255) NOT NULL,\n"
            "  `status` varchar(32) NOT NULL DEFAULT 'active',\n"
            "  `created_at` datetime NOT NULL,\n"
            "  PRIMARY KEY (`id`)\n"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;\n\n",
            f"LOCK TABLES `{tbl}` WRITE;\n",
            f"INSERT INTO `{tbl}` VALUES\n",
        ]
        rows = []
        for i in range(rng.between(8, 20)):
            created = datetime.fromtimestamp(end - rng.between(0, 9_000_000), UTC).strftime("%Y-%m-%d %H:%M:%S")
            rows.append(f"  ({i + 1},'{rng.pick(res)}-{rng.between(1000, 9999)}','active','{created}')")
        out.append(",\n".join(rows) + ";\n")
        out.append(f"UNLOCK TABLES;\nSET FOREIGN_KEY_CHECKS=1;\n-- Dump completed on {_iso_epoch(end)}\n")
        return "".join(out)

    @staticmethod
    def _render_noise(o: LabyrinthOptions, g: _Global, rng: SeededRandom, path: str, intensity: int = 0) -> str:
        name = _last_seg(path).lower()
        end = file_mtime_epoch(o.seed, path)  # el log "termina" cuando se tocó el fichero
        extra = 120 * intensity  # a mayor intensidad, más historial (coherente, append-only)
        if "access" in name and name.endswith(".log"):
            return LabyrinthGenerator._access_log(g, rng, end, extra)
        return LabyrinthGenerator._app_log(g, rng, end, extra)

    @staticmethod
    def _ascending_times(rng: SeededRandom, end_epoch: int, n: int, max_gap: int) -> list[int]:
        """n timestamps MONÓTONOS ascendentes que terminan en end_epoch (append-only real):
        nunca hay entradas en el futuro ni posteriores al Last-Modified del fichero."""
        times: list[int] = []
        t = end_epoch
        for _ in range(n):
            times.append(t)
            t -= rng.between(1, max_gap)
        times.reverse()
        return times

    @staticmethod
    def _access_log(g: _Global, rng: SeededRandom, end_epoch: int, extra: int = 0) -> str:
        """Access log tipo nginx 'combined', cronológico (ascendente), terminando en el mtime."""
        res = vocab.resources(g.theme)
        out: list[str] = []
        for ts in LabyrinthGenerator._ascending_times(rng, end_epoch, rng.between(80, 220) + extra, 90):
            ip = f"10.{rng.below(256)}.{rng.below(256)}.{rng.between(1, 254)}"
            r = rng.below(100)
            if r < 45:
                req = f"/api/v2/{rng.pick(res)}/{rng.between(1, 99999)}"
            elif r < 65:
                req = f"/api/v2/{rng.pick(res)}?page={rng.between(1, 40)}"
            elif r < 80:
                req = f"/static/{rng.pick(res)}.{rng.hex(8)}.js"
            elif r < 90:
                req = f"/{rng.pick(res)}/{rng.pick(['index', 'edit', 'new', 'show'])}"
            else:
                req = rng.pick(["/health", "/favicon.ico", "/robots.txt", "/metrics"])
            status = rng.pick(_ACCESS_STATUSES)
            size = 0 if status in (301, 302, 304) else rng.between(120, 48000)
            out.append(
                f'{ip} - - [{_clf_epoch(ts)}] "{rng.pick(_ACCESS_METHODS)} {req} HTTP/1.1" '
                f'{status} {size} "-" "{rng.pick(_ACCESS_UAS)}"'
            )
        return "\n".join(out) + "\n"

    @staticmethod
    def _app_log(g: _Global, rng: SeededRandom, end_epoch: int, extra: int = 0) -> str:
        """Log de aplicación cronológico (ascendente), terminando en el mtime del fichero."""
        res = vocab.resources(g.theme)
        out: list[str] = []
        for ts in LabyrinthGenerator._ascending_times(rng, end_epoch, rng.between(60, 180) + extra, 120):
            lvl, tmpl = rng.pick(_LOG_LINES)
            msg = tmpl.format(
                n=rng.between(1, 64),
                n2=rng.between(1, 64),
                pid=rng.between(1000, 32000),
                ms=rng.between(2, 900),
                pct=rng.between(70, 99),
                res=rng.pick(res),
                tok=rng.hex(8),
            )
            out.append(f"{_iso_epoch(ts)} [{lvl}] {rng.pick(_LOG_COMPONENTS)}: {msg}")
        return "\n".join(out) + "\n"

    @staticmethod
    def _binary(g: _Global, rng: SeededRandom, path: str) -> GeneratedPage:
        name = _last_seg(path)
        size = rng.between(4096, 24576)
        buf = bytearray(size)
        elf = bytes([0x7F, ord("E"), ord("L"), ord("F"), 2, 1, 1, 0])
        buf[: len(elf)] = elf
        for i in range(len(elf), size):
            if buf[i] == 0:
                buf[i] = rng.below(256)
        marker = (g.slug + rng.hex(12)).encode("ascii")
        buf[len(elf) + 16 : len(elf) + 16 + len(marker)] = marker
        return GeneratedPage(
            body=bytes(buf), content_type="application/octet-stream", node_kind="binary", attachment_name=name
        )

    # ---- envoltura ----

    @staticmethod
    def _html(body: str, kind: str) -> GeneratedPage:
        return GeneratedPage(body=body.encode(), content_type="text/html; charset=utf-8", node_kind=kind)

    @staticmethod
    def _text(body: str, ct: str, kind: str) -> GeneratedPage:
        return GeneratedPage(body=body.encode(), content_type=ct, node_kind=kind)
