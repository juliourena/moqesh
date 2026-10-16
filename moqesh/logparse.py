"""Parser central de logs de acceso para el modo agentless.

El remoto envía líneas crudas (ya filtradas por el prefijo del cebo) y un hint de
formato; aquí se extrae `(timestamp, source_ip, method, path, status, size, user_agent)`.
Soporta combined de nginx/apache, Caddy (JSON) y JSON genérico. Lo que no casa se
descarta silenciosamente (nunca lanza).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime

# nginx/apache "combined":
# 1.2.3.4 - - [10/Oct/2026:13:55:36 +0000] "GET /p HTTP/1.1" 200 1234 "ref" "ua"
_COMBINED = re.compile(
    r"(?P<ip>\S+)\s+\S+\s+\S+\s+\[(?P<ts>[^\]]+)\]\s+"
    r'"(?P<method>\S+)\s+(?P<path>\S+)\s+[^"]*"\s+(?P<status>\d{3})\s+(?P<size>\S+)'
    r'(?:\s+"[^"]*"\s+"(?P<ua>[^"]*)")?'
)
_CLF_TS = "%d/%b/%Y:%H:%M:%S %z"


@dataclass
class ParsedRequest:
    timestamp: datetime
    source_ip: str
    method: str
    path: str
    status: int
    size: int
    user_agent: str


def _to_naive_utc(dt: datetime) -> datetime:
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC).replace(tzinfo=None)
    return dt


def _int(v, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _parse_combined(line: str) -> ParsedRequest | None:
    m = _COMBINED.search(line)
    if not m:
        return None
    try:
        ts = _to_naive_utc(datetime.strptime(m.group("ts"), _CLF_TS))
    except ValueError:
        ts = datetime.utcnow()
    return ParsedRequest(
        ts,
        m.group("ip"),
        m.group("method"),
        m.group("path"),
        _int(m.group("status")),
        _int(m.group("size")),
        m.group("ua") or "",
    )


def _parse_json(line: str) -> ParsedRequest | None:
    try:
        d = json.loads(line)
    except (ValueError, TypeError):
        return None
    # Soporta esquemas de Caddy y JSON genéricos (claves alternativas).
    req = d.get("request", d)
    ip = req.get("remote_ip") or req.get("client_ip") or d.get("remote_addr") or d.get("ip") or ""
    method = req.get("method") or d.get("method") or "GET"
    path = req.get("uri") or req.get("path") or d.get("path") or d.get("url") or ""
    status = _int(
        d.get("status") or d.get("response", {}).get("status")
        if isinstance(d.get("response"), dict)
        else d.get("status")
    )
    size = _int(d.get("size") or d.get("bytes") or d.get("resp_size"))
    headers = req.get("headers") or {}
    ua = ""
    if isinstance(headers, dict):
        ua_val = headers.get("User-Agent") or headers.get("user-agent")
        ua = ua_val[0] if isinstance(ua_val, list) and ua_val else (ua_val or "")
    ua = ua or d.get("user_agent") or ""
    ts_raw = d.get("ts") or d.get("time") or d.get("timestamp")
    ts = datetime.utcnow()
    if isinstance(ts_raw, (int, float)):
        ts = datetime.utcfromtimestamp(ts_raw)
    elif isinstance(ts_raw, str):
        try:
            ts = _to_naive_utc(datetime.fromisoformat(ts_raw.replace("Z", "+00:00")))
        except ValueError:
            pass
    if not path:
        return None
    return ParsedRequest(ts, ip, method, path, status, size, ua)


def parse(fmt: str, lines: list[str], base_path: str = "/") -> list[ParsedRequest]:
    """Parsea `lines` según `fmt` (nginx|apache|combined|caddy|json|raw) y filtra por prefijo."""
    fmt = (fmt or "raw").lower()
    out: list[ParsedRequest] = []
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        if fmt in ("json", "caddy"):
            pr = _parse_json(raw)
        elif fmt in ("nginx", "apache", "combined"):
            pr = _parse_combined(raw)
        else:  # raw / autodetección: intenta JSON y luego combined
            pr = _parse_json(raw) if raw.startswith("{") else _parse_combined(raw)
        if pr is not None and pr.path.startswith(base_path):
            out.append(pr)
    out.sort(key=lambda r: r.timestamp)
    return out
