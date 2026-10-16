"""Perfilador de sitios reales para el modo Mimic (read-only).

Inspirado en `Moqesh.TokenExhaust.SiteProfiler` (C#) pero reescrito idiomatico:
hace un crawl superficial y ACOTADO del mismo origen (httpx async + html.parser
de la stdlib, sin dependencias nuevas) y extrae un perfil JSON-serializable que
se guarda en `SiteProfile.profile_json`. Genérico: funciona contra cualquier
dominio objetivo.

Perfil devuelto (todas las claves siempre presentes):
    {
      "paths":          [...],  # directorios observados ("/app/", "/account/")
      "api_prefixes":   [...],  # prefijos de API ("/api/v2", "/graphql")
      "resource_names": [...],  # nombres de recursos hoja ("login", "app.js")
      "tech_stack":     {...},  # tech detectada -> evidencia ("react": "html")
      "vocabulary":     [...],  # segmentos/palabras del dominio (vocabulario)
      "server_banner":  "...",  # cabecera Server real (o "nginx" por defecto)
      "title":          "...",  # <title> de la primera pagina HTML
    }
"""

from __future__ import annotations

import asyncio
import re
from collections import deque
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse, urlunparse

import httpx

# --------------------------- limites y constantes ---------------------------

_USER_AGENT = "Mozilla/5.0 (compatible; MoqeshProfiler/1.0)"
_MAX_BYTES = 2_000_000  # tope de cuerpo leido por pagina (anti-OOM)
_MAX_PATHS = 40
_MAX_API = 10
_MAX_RESOURCES = 40
_MAX_VOCAB = 60
_MAX_TECH = 12
_SEG_MIN, _SEG_MAX = 3, 24  # longitud de segmento valido para vocabulario
_LEAF_MAX = 48  # longitud maxima de un nombre de recurso

# Esquemas de enlace que se ignoran (no son paginas navegables).
_SKIP_SCHEMES = ("mailto:", "tel:", "javascript:", "data:", "blob:", "about:")

# Pistas de stack: aguja (en HTML, minusculas) -> nombre normalizado.
_TECH_NEEDLES: tuple[tuple[str, str], ...] = (
    ("__next_data__", "next.js"),
    ("data-reactroot", "react"),
    ("ng-version", "angular"),
    ("wp-content", "wordpress"),
    ("csrfmiddlewaretoken", "django"),
    ("laravel_session", "laravel"),
    ("_nuxt", "nuxt"),
    ("data-v-app", "vue"),
    ("__sveltekit", "svelte"),
    ("gatsby", "gatsby"),
    ("/cdn-cgi/", "cloudflare"),
    ("shopify", "shopify"),
    ("vite", "vite"),
)

_API_RE = re.compile(r"/(?:api|graphql|rest|v\d+)(?:/|$)", re.IGNORECASE)
_API_PREFIX_RE = re.compile(r"^(/[^/]*(?:api|graphql|rest|v\d)[^/]*(?:/v\d+)?)", re.IGNORECASE)
_SEG_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]*$")
_LEAF_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")


# ------------------------------- parser HTML --------------------------------


class _HtmlScan(HTMLParser):
    """Extrae enlaces (href/src/action) y el <title>. Tolerante a HTML roto."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self.title: str = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self._in_title = True
        for name, value in attrs:
            if value and name in ("href", "src", "action"):
                self.links.append(value)

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        # Solo el primer <title>; puede llegar en varios trozos.
        if self._in_title and not self.title:
            text = data.strip()
            if text:
                self.title = text


# ------------------------------- helpers URL --------------------------------


def _is_http(url: str) -> bool:
    return url.startswith(("http://", "https://"))


def _normalize(url: str) -> str:
    """Canonicaliza para dedupe: baja esquema/host y descarta query y fragmento."""
    p = urlparse(url)
    return urlunparse((p.scheme.lower(), p.netloc.lower(), p.path or "/", "", "", ""))


def _dir_of(path: str) -> str:
    """Directorio contenedor de una ruta ("/a/b/c" -> "/a/b/"); "/" si es raiz."""
    p = path.rstrip("/")
    idx = p.rfind("/")
    return "/" if idx <= 0 else p[: idx + 1]


def _leaf_of(path: str) -> str:
    """Ultimo segmento (nombre de recurso); "" si la ruta es un directorio."""
    if path.endswith("/"):
        return ""
    idx = path.rfind("/")
    return path[idx + 1 :] if idx >= 0 else path


def _api_prefix(path: str) -> str:
    m = _API_PREFIX_RE.match(path)
    return m.group(1) if m else "/api"


# ------------------------------- acumulador ---------------------------------


class _OrderedSet:
    """Conjunto ordenado por insercion con tope; ignora extras una vez lleno."""

    def __init__(self, limit: int) -> None:
        self._data: dict[str, None] = {}
        self._limit = limit

    def add(self, key: str) -> None:
        if key and key not in self._data and len(self._data) < self._limit:
            self._data[key] = None

    def sorted(self) -> list[str]:
        return sorted(self._data)


# ------------------------------- descarga -----------------------------------


async def _fetch_html(client: httpx.AsyncClient, url: str) -> tuple[httpx.Response, str | None]:
    """Descarga una pagina. Devuelve (respuesta, html) o (respuesta, None) si no
    es HTML. Lee como mucho `_MAX_BYTES` para acotar memoria."""
    async with client.stream("GET", url) as resp:
        ctype = resp.headers.get("content-type", "").lower()
        if "html" not in ctype:
            return resp, None
        chunks: list[bytes] = []
        total = 0
        async for chunk in resp.aiter_bytes():
            chunks.append(chunk)
            total += len(chunk)
            if total >= _MAX_BYTES:
                break
        enc = resp.charset_encoding or "utf-8"
        try:
            html = b"".join(chunks).decode(enc, errors="replace")
        except (LookupError, UnicodeError):
            html = b"".join(chunks).decode("utf-8", errors="replace")
        return resp, html


# ------------------------------- API publica --------------------------------


async def profile_site(
    target_url: str, *, max_pages: int = 40, timeout: float = 10.0, same_origin: bool = True
) -> dict:
    """Perfila (read-only) un sitio real para el modo Mimic.

    Hace un crawl BFS acotado desde `target_url`: como mucho `max_pages` paginas,
    `timeout` segundos por peticion, sin salir del host salvo que `same_origin`
    sea False. Nunca lanza por errores de red/HTML: en el peor caso devuelve un
    perfil parcial (o vacio con banner "nginx").
    """
    base = urlparse(target_url)
    paths = _OrderedSet(_MAX_PATHS)
    api = _OrderedSet(_MAX_API)
    resources = _OrderedSet(_MAX_RESOURCES)
    vocab = _OrderedSet(_MAX_VOCAB)
    tech: dict[str, str] = {}
    server_banner = ""
    title = ""

    # URL objetivo invalida: perfil vacio pero bien formado.
    if base.scheme not in ("http", "https") or not base.netloc:
        return _build(paths, api, resources, vocab, tech, server_banner, title)

    base_host = base.netloc.lower()
    seen: set[str] = set()
    queue: deque[str] = deque([_normalize(target_url)])
    pages = 0
    headers_done = False
    html_done = False

    limits = httpx.Timeout(timeout)
    headers = {"User-Agent": _USER_AGENT, "Accept": "text/html,application/xhtml+xml,*/*"}
    try:
        async with httpx.AsyncClient(timeout=limits, follow_redirects=True, headers=headers, max_redirects=5) as client:
            while queue and pages < max_pages:
                url = queue.popleft()
                if url in seen:
                    continue
                seen.add(url)

                try:
                    resp, html = await _fetch_html(client, url)
                except (httpx.HTTPError, OSError):
                    pages += 1  # cuenta el intento para no colgarse en un host muerto
                    continue

                # Cabeceras: solo de la primera respuesta exitosa.
                if not headers_done:
                    headers_done = True
                    sv = resp.headers.get("server", "").strip()
                    if sv:
                        server_banner = sv
                    xpb = resp.headers.get("x-powered-by", "").strip()
                    if xpb and len(tech) < _MAX_TECH:
                        tech[xpb.lower()] = "x-powered-by"

                pages += 1
                if html is None:
                    continue

                # Primera pagina HTML: titulo y deteccion de stack.
                if not html_done:
                    html_done = True
                    scan_title, lower = _scan_meta(html)
                    if scan_title:
                        title = scan_title
                        _harvest_words(title, vocab)
                    for needle, name in _TECH_NEEDLES:
                        if needle in lower and len(tech) < _MAX_TECH:
                            tech.setdefault(name, "html")

                # Extraccion de enlaces y vocabulario.
                for raw in _links(html):
                    abs_url = _resolve(url, raw)
                    if abs_url is None:
                        continue
                    pu = urlparse(abs_url)
                    on_host = pu.netloc.lower() == base_host
                    if not on_host and same_origin:
                        continue  # fuera del origen: no seguir ni registrar

                    path = pu.path or "/"
                    d = _dir_of(path)
                    if d != "/":
                        paths.add(d)
                    leaf = _leaf_of(path)
                    if leaf and len(leaf) <= _LEAF_MAX and _LEAF_RE.match(leaf):
                        resources.add(leaf.lower())
                    for seg in path.strip("/").split("/"):
                        if _SEG_MIN <= len(seg) <= _SEG_MAX and _SEG_RE.match(seg):
                            vocab.add(seg.lower())
                    if _API_RE.search(path):
                        api.add(_api_prefix(path))

                    # Encolar nuevas paginas navegables (sin extension de archivo).
                    if (on_host or not same_origin) and "." not in leaf and len(queue) < max_pages * 4:
                        norm = _normalize(abs_url)
                        if norm not in seen:
                            queue.append(norm)
    except Exception:
        # Ultima red de seguridad: devolvemos lo acumulado hasta el fallo.
        pass

    return _build(paths, api, resources, vocab, tech, server_banner, title)


def profile_site_sync(target_url: str, *, max_pages: int = 40, timeout: float = 10.0, same_origin: bool = True) -> dict:
    """Envoltura sincrona de `profile_site` para contextos no-async (CLI, tests).

    No usar dentro de un event loop ya en marcha (usar `profile_site` directamente).
    """
    return asyncio.run(profile_site(target_url, max_pages=max_pages, timeout=timeout, same_origin=same_origin))


# ------------------------------- internos -----------------------------------


def _links(html: str) -> list[str]:
    """Devuelve los enlaces del HTML; tolera documentos malformados."""
    parser = _HtmlScan()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        pass  # html.parser rara vez lanza, pero no debe tumbar el crawl
    return parser.links


def _scan_meta(html: str) -> tuple[str, str]:
    """Extrae el <title> y devuelve tambien el HTML en minusculas (para stack)."""
    parser = _HtmlScan()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        pass
    return parser.title, html.lower()


def _resolve(current: str, raw: str) -> str | None:
    """Resuelve un enlace a URL absoluta http(s); None si no es navegable."""
    raw = raw.strip()
    if not raw or raw.startswith("#"):
        return None
    if raw.lower().startswith(_SKIP_SCHEMES):
        return None
    try:
        abs_url = urljoin(current, raw)
    except ValueError:
        return None
    return abs_url if _is_http(abs_url) else None


def _harvest_words(text: str, vocab: _OrderedSet) -> None:
    """Añade al vocabulario las palabras utiles de un texto (p.ej. el titulo)."""
    for w in _WORD_RE.findall(text):
        if _SEG_MIN <= len(w) <= _SEG_MAX:
            vocab.add(w.lower())


def _build(
    paths: _OrderedSet,
    api: _OrderedSet,
    resources: _OrderedSet,
    vocab: _OrderedSet,
    tech: dict[str, str],
    server_banner: str,
    title: str,
) -> dict:
    """Ensambla el perfil JSON-serializable con todas las claves presentes."""
    return {
        "paths": paths.sorted(),
        "api_prefixes": api.sorted(),
        "resource_names": resources.sorted(),
        "tech_stack": dict(tech),
        "vocabulary": vocab.sorted(),
        "server_banner": server_banner or "nginx",
        "title": title,
    }
