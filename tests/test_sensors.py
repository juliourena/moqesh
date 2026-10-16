"""Plano de sensores: alta, ingestión firmada, control firmado y agentless."""

import json
import time

from fastapi.testclient import TestClient

from moqesh import security


def _signed(secret, body: bytes) -> dict:
    ts = str(time.time())
    return {"X-Moqesh-Timestamp": ts, "X-Moqesh-Signature": security.sign(secret, ts, body)}


def _create(client, kind="agent"):
    r = client.post("/api/sensors", json={"name": f"edge-{kind}", "kind": kind, "basePath": "/lure"})
    assert r.status_code == 201, r.text
    return r.json()


def test_create_and_agent_ingest_detects():
    from moqesh.api import app

    with TestClient(app) as client:
        s = _create(client, "agent")
        key_id, secret = s["keyId"], s["apiSecret"]
        assert f"/s/{s['installToken']}" in s["installCommand"]

        # Un evento con señal fuerte de reuso de credencial → debe puntuar alto.
        events = {
            "events": [
                {
                    "source_ip": "9.9.9.9",
                    "method": "GET",
                    "path": "/lure/api/internal/vault",
                    "status": 200,
                    "size": 400,
                    "user_agent": "python-requests",
                    "node_kind": "scenario:vault",
                    "strong": {"credential_reuse": True, "hidden_path_access": True},
                    "progress": {"stage_reached": 3, "credentials_used": "svc_bearer", "hidden_hits": 2},
                }
            ]
        }
        body = json.dumps(events).encode()
        headers = {"X-Moqesh-Key-Id": key_id, **_signed(secret, body)}
        r = client.post("/ingest/events", content=body, headers=headers)
        assert r.status_code == 200 and r.json()["accepted"] == 1

        # El sensor aparece online y con telemetría.
        sensors = client.get("/api/sensors").json()
        edge = next(x for x in sensors if x["id"] == s["id"])
        assert edge["status"] == "online" and edge["sessionCount"] >= 1


def test_bad_signature_rejected():
    from moqesh.api import app

    with TestClient(app) as client:
        s = _create(client, "agent")
        body = json.dumps({"events": []}).encode()
        headers = {
            "X-Moqesh-Key-Id": s["keyId"],
            "X-Moqesh-Timestamp": str(time.time()),
            "X-Moqesh-Signature": "sha256=deadbeef",
        }
        assert client.post("/ingest/events", content=body, headers=headers).status_code == 401


def test_control_is_signed_by_server():
    from moqesh.api import app

    with TestClient(app) as client:
        s = _create(client, "agent")
        headers = {"X-Moqesh-Key-Id": s["keyId"], **_signed(s["apiSecret"], b"")}
        r = client.get("/control", headers=headers)
        assert r.status_code == 200
        ts = r.headers["X-Moqesh-Timestamp"]
        sig = r.headers["X-Moqesh-Server-Signature"]
        assert security.verify(s["apiSecret"], ts, sig, r.content)  # integridad del control
        assert r.json()["enabled"] is True


def test_agentless_log_ingest():
    from moqesh.api import app

    with TestClient(app) as client:
        s = _create(client, "agentless")
        line = '9.9.9.9 - - [10/Oct/2026:13:55:36 +0000] "GET /lure/ops/.env HTTP/1.1" 200 320 "-" "curl/8"'
        payload = {"format": "nginx", "base_path": "/lure", "lines": [line]}
        body = json.dumps(payload).encode()
        headers = {"X-Moqesh-Key-Id": s["keyId"], **_signed(s["apiSecret"], body)}
        r = client.post("/ingest/logs", content=body, headers=headers)
        assert r.status_code == 200 and r.json()["parsed"] == 1 and r.json()["accepted"] == 1


def test_disable_and_decommission():
    from moqesh.api import app

    with TestClient(app) as client:
        s = _create(client, "agent")
        assert client.post(f"/api/sensors/{s['id']}/disable").json()["enabled"] is False
        assert client.delete(f"/api/sensors/{s['id']}").status_code == 204
        # Tras la baja, ya no aparece en el listado activo.
        assert all(x["id"] != s["id"] for x in client.get("/api/sensors").json())
