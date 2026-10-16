"""Integración de la API y el honeypot (TestClient, sin arrancar uvicorn)."""

from fastapi.testclient import TestClient


def test_dashboard_and_rules():
    from moqesh.api import app

    with TestClient(app) as client:
        assert client.get("/healthz").json() == {"status": "ok"}
        rules = client.get("/api/rules").json()
        assert len(rules) == 14 and rules[0]["ruleType"] == "timing_analysis"
        ov = client.get("/api/dashboard/overview").json()
        assert "totalRequests" in ov and "scoreDistribution" in ov


def test_scenarios_builtins_and_import():
    from moqesh.api import app

    with TestClient(app) as client:
        assert set(client.get("/api/scenarios/builtins").json()) >= {"corp-breach", "git-leak"}
        scn = client.get("/api/scenarios").json()
        assert any(s["name"] == "corp-breach" for s in scn)  # sembrado por defecto


def test_honeypot_crawl_detects_agent():
    from moqesh.honeypot import app

    with TestClient(app) as client:
        headers = {"User-Agent": "python-requests/2.31 (langchain)"}
        # Sigue enlaces del landing en profundidad para disparar varias reglas.
        seen, frontier, hits = set(), ["/"], 0
        import re

        link_re = re.compile(r'href="([^"]+)"')
        while frontier and hits < 20:
            path = frontier.pop(0)
            if path in seen:
                continue
            seen.add(path)
            r = client.get(path, headers=headers)
            hits += 1
            if "html" in r.headers.get("content-type", ""):
                for href in link_re.findall(r.text):
                    if href.startswith(("../", "http")):
                        continue
                    frontier.append((path.rstrip("/") + "/" + href) if path != "/" else "/" + href)
    # Consulta directa a la DB (el honeypot y la API comparten SQLite).
    from sqlalchemy import select

    from moqesh.db import SessionLocal
    from moqesh.models import AgentSession

    with SessionLocal() as db:
        s = db.scalar(select(AgentSession).order_by(AgentSession.request_count.desc()).limit(1))
    assert s is not None and s.request_count >= 5
    assert s.ai_probability_score > 0 and "user_agent" in (s.matched_rules or "")
