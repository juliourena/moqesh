"""Motor de scoring conductual.

Cada regla observa la secuencia de paths/timestamps de una sesión y suma su peso
si dispara. Las reglas fuertes (credential_reuse, hidden_path_access,
binary_decompile_followup, auth_bruteforce) se alimentan del motor de escenarios
y llegan como señales externas (`extra_signals`).
"""

from __future__ import annotations

import math
from datetime import datetime

from .labyrinth import LabyrinthGenerator, LabyrinthOptions, kind_of

_AI_UAS = [
    "gpt",
    "claude",
    "anthropic",
    "openai",
    "langchain",
    "autogpt",
    "agentgpt",
    "babyagi",
    "crewai",
    "python-requests",
    "axios",
    "node-fetch",
    "go-http-client",
    "aiohttp",
    "httpx",
    "curl",
    "wget",
    "scrapy",
]
_ASSET_EXT = (".css", ".png", ".jpg", ".jpeg", ".svg", ".ico", ".woff", ".woff2", ".gif")


def _parent_of(path: str) -> str:
    p = path.rstrip("/")
    i = p.rfind("/")
    return "/" if i <= 0 else p[: i + 1]


def check_timing(ts: list[datetime]) -> bool:
    if len(ts) < 3:
        return False
    intervals = [(ts[i] - ts[i - 1]).total_seconds() for i in range(1, len(ts))]
    avg = sum(intervals) / len(intervals)
    variance = sum((x - avg) ** 2 for x in intervals) / len(intervals)
    regular = avg > 0 and math.sqrt(variance) / avg < 0.6
    return (0.3 <= avg <= 30) and (regular or len(intervals) >= 4)


def check_sequence(paths: list[str]) -> bool:
    if len(paths) < 4:
        return False
    dirs = sum(1 for p in paths if p.endswith("/"))
    files = sum(1 for p in paths if not p.endswith("/"))
    if dirs < 2 or files < 2:
        return False
    first_dir = next((i for i, p in enumerate(paths) if p.endswith("/")), -1)
    first_file = next((i for i, p in enumerate(paths) if not p.endswith("/")), -1)
    return first_dir >= 0 and first_file >= 0 and first_dir < first_file


def check_downloads(paths: list[str]) -> bool:
    return sum(1 for p in paths if kind_of(p) in ("binary", "archive")) >= 2


def check_readme_following(paths: list[str]) -> bool:
    idx = next((i for i, p in enumerate(paths) if kind_of(p) == "readme"), -1)
    if idx < 0:
        return False
    return any(kind_of(p) in ("env", "config", "apiconfig", "binary") for p in paths[idx + 1 :])


def check_js_deobfuscation(paths: list[str]) -> bool:
    idx = next((i for i, p in enumerate(paths) if kind_of(p) == "js"), -1)
    if idx < 0:
        return False
    return any("/internal/" in p for p in paths[idx + 1 :])


def check_user_agent(ua: str) -> bool:
    low = (ua or "").lower()
    return any(x in low for x in _AI_UAS)


def check_breadcrumb(gen: LabyrinthGenerator, opts: LabyrinthOptions | None, paths: list[str]) -> bool:
    if opts is None or len(paths) < 4:
        return False
    visited: set[str] = set()
    followed = 0
    for p in paths:
        parent = _parent_of(p)
        if parent in visited and p in gen.links_for(opts, parent):
            followed += 1
        visited.add(p)
    return followed >= 3


def check_fanout(gen: LabyrinthGenerator, opts: LabyrinthOptions | None, paths: list[str]) -> bool:
    if opts is None:
        return False
    visited = set(paths)
    seen: set[str] = set()
    dirs: list[str] = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            if kind_of(p) in ("landing", "dir", "resource"):
                dirs.append(p)
    if len(dirs) < 2:
        return False
    total, counted = 0.0, 0
    for d in dirs:
        links = gen.links_for(opts, d)
        if not links:
            continue
        total += sum(1 for link in links if link in visited) / len(links)
        counted += 1
    return counted >= 2 and (total / counted) >= 0.55


def check_depth_descent(paths: list[str]) -> bool:
    return any(len(p.strip("/").split("/")) >= 5 for p in paths)


def check_no_assets(paths: list[str]) -> bool:
    if len(paths) < 5:
        return False
    return not any(p.lower().endswith(_ASSET_EXT) for p in paths)


def estimate_tokens(response_size: int) -> int:
    return response_size // 4


def intensity_for(session) -> int:
    """Nivel de intensidad adaptativa (0..3) de una sesión, según su score acumulado.

    0 = desconocido/humano: el sitio se comporta como uno real finito (máximo sigilo).
    1..3 = sospecha creciente -> más volumen de cebo COHERENTE (prosa/logs/migajas) + tarpit
    mayor. Alineado con los umbrales de severidad de alerta (Low/Medium/High/Critical). La
    intensidad nunca vuelve al laberinto incoherente ni infinito: solo "más sitio real".
    """
    if session is None:
        return 0
    score = getattr(session, "ai_probability_score", 0.0) or 0.0
    if score >= 0.8:
        return 3
    if score >= 0.6:
        return 2
    if score >= 0.4:
        return 1
    return 0


def score_session(
    gen: LabyrinthGenerator,
    opts: LabyrinthOptions | None,
    rules: list,
    ordered_paths: list[str],
    timestamps: list[datetime],
    user_agent: str,
    extra_signals: dict[str, bool] | None = None,
) -> tuple[float, list[str]]:
    """Evalúa reglas activas; devuelve (score acotado a 1.0, reglas disparadas)."""
    extra = extra_signals or {}
    checks = {
        "timing_analysis": lambda: check_timing(timestamps),
        "sequence_pattern": lambda: check_sequence(ordered_paths),
        "download_pattern": lambda: check_downloads(ordered_paths),
        "readme_following": lambda: check_readme_following(ordered_paths),
        "js_deobfuscation": lambda: check_js_deobfuscation(ordered_paths),
        "user_agent": lambda: check_user_agent(user_agent),
        "breadcrumb_following": lambda: check_breadcrumb(gen, opts, ordered_paths),
        "depth_descent": lambda: check_depth_descent(ordered_paths),
        "exhaustive_fanout": lambda: check_fanout(gen, opts, ordered_paths),
        "no_asset_render": lambda: check_no_assets(ordered_paths),
    }
    score, matched = 0.0, []
    for rule in rules:
        fn = checks.get(rule.rule_type)
        triggered = fn() if fn is not None else extra.get(rule.rule_type, False)
        if triggered:
            score += rule.weight
            matched.append(rule.rule_type)
    return min(score, 1.0), matched
