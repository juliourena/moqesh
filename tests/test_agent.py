"""Tests del agente remoto: señales fuertes (puro) + firmado HMAC (sin red real)."""

import json
import time

import httpx

from moqesh import security
from moqesh.agent.main import (
    AgentConfig,
    EventSender,
    IpProgress,
    ServerClient,
    build_scenario,
    update_progress,
)
from moqesh.labyrinth import LabyrinthGenerator, LabyrinthOptions
from moqesh.scenarios import BUILTIN_PACKS, ScenarioContext, ScenarioEngine, ScenarioRequest

SEED = "test-seed"


def _scenario():
    pack = BUILTIN_PACKS["corp-breach"]()
    return pack, build_scenario(pack, scenario_id=7)


def _ctx():
    opts = LabyrinthOptions(mode="Template", seed=SEED, realism_level=3)
    return ScenarioContext(seed=SEED, brand=LabyrinthGenerator.brand_for(opts))


def _bearer_for(scenario, ctx, key):
    return ctx.secret_of(scenario.cred(key))


# ----------------------------- mapeo del pack --------------------------------


def test_build_scenario_maps_camel_to_snake():
    _, sc = _scenario()
    assert sc.scenario_id == 7 and sc.name == "corp-breach"
    dll = sc.node_at("/backup/Portal.dll")
    assert dll is not None and dll.kind == "binary" and dll.binary_kind == "dotnetdll"
    assert dll.grants_credential_keys == "db,svc_bearer"
    vault = sc.node_at("/api/internal/vault")
    assert vault.visibility == "hidden" and vault.requires_credential_key == "svc_bearer"
    assert vault.hinted_by_paths == "/backup/Portal.dll"
    assert sc.cred("admin").username == "admin" and sc.cred("admin").kind == "basic"


# ----------------------------- señales fuertes acumulativas ------------------


def test_strong_signals_follow_ctf_chain():
    _, sc = _scenario()
    engine = ScenarioEngine()
    ctx = _ctx()
    prog = IpProgress(scenario_id=sc.scenario_id)

    def visit(path, headers=None):
        hit = engine.resolve(sc, ctx, ScenarioRequest(path=path, headers=headers or {}))
        assert hit is not None, path
        return update_progress(prog, sc, hit, path)

    # robots.txt (linked, stage 0): nada se dispara.
    sig = visit("/robots.txt")
    assert sig == dict.fromkeys(sig, False)

    # Descarga del binario (linked): otorga credenciales pero aún no hay reuso ni oculto.
    sig = visit("/backup/Portal.dll")
    assert sig["credential_reuse"] is False and sig["hidden_path_access"] is False
    assert "svc_bearer" in prog.credentials_obtained

    # Acceso a ruta oculta hinteada por el binario, sin credencial -> hidden + decompile + fallo.
    sig = visit("/api/internal/vault")
    assert sig["hidden_path_access"] is True  # visibility hidden
    assert sig["binary_decompile_followup"] is True  # vault hinteado por Portal.dll (binario ya visitado)
    assert sig["credential_reuse"] is False
    assert prog.failed_auth_attempts == 1

    # Presentar la credencial plantada correcta -> reuso confirmado.
    bearer = _bearer_for(sc, ctx, "svc_bearer")
    sig = visit("/api/internal/vault", headers={"Authorization": f"Bearer {bearer}"})
    assert sig["credential_reuse"] is True
    assert "svc_bearer" in prog.credentials_used
    assert prog.stage_reached >= 3


def test_auth_bruteforce_after_three_failures():
    _, sc = _scenario()
    engine = ScenarioEngine()
    ctx = _ctx()
    prog = IpProgress(scenario_id=sc.scenario_id)
    last = {}
    for _ in range(3):
        hit = engine.resolve(sc, ctx, ScenarioRequest(path="/api/internal/vault"))
        last = update_progress(prog, sc, hit, "/api/internal/vault")
    assert prog.failed_auth_attempts == 3 and last["auth_bruteforce"] is True


# ----------------------------- firmado HMAC (MockTransport) ------------------


def _agent_signed(secret, request: httpx.Request) -> bool:
    ts = request.headers.get("X-Moqesh-Timestamp", "")
    sig = request.headers.get("X-Moqesh-Signature", "")
    return security.verify(secret, ts, sig, request.content)


def _mock_client(secret, captured, *, forge_bad_server_sig=False):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/healthz":
            return httpx.Response(200, json={"status": "ok"})  # público, sin firma
        assert _agent_signed(secret, request), "petición del agente mal firmada"
        if path == "/control":
            payload = json.dumps(
                {
                    "enabled": True,
                    "seed": "s",
                    "scenario_id": 0,
                    "scenario": None,
                    "generation_mode": "Template",
                    "realism_level": 3,
                    "config_version": 1,
                    "server_time": time.time(),
                }
            ).encode()
            ts = str(time.time())
            sig = "sha256=bad" if forge_bad_server_sig else security.sign(secret, ts, payload)
            return httpx.Response(
                200,
                content=payload,
                headers={
                    "X-Moqesh-Timestamp": ts,
                    "X-Moqesh-Server-Signature": sig,
                    "Content-Type": "application/json",
                },
            )
        if path == "/ingest/events":
            data = json.loads(request.content)
            captured.append(data)
            return httpx.Response(200, json={"accepted": len(data["events"])})
        return httpx.Response(404)

    client = ServerClient("http://server.test", "mq_key", secret)
    client._client = httpx.Client(transport=httpx.MockTransport(handler))
    return client


def test_signing_and_server_signature_roundtrip():
    secret = "super-secret"
    captured: list[dict] = []
    client = _mock_client(secret, captured)

    assert client.healthz() is True

    ctrl = client.get_control()  # exige firma del servidor válida
    assert ctrl is not None and ctrl["enabled"] is True and ctrl["config_version"] == 1

    assert client.post_events([{"path": "/x", "strong": {}}]) is True
    assert captured[-1]["agent_version"] and captured[-1]["events"][0]["path"] == "/x"


def test_control_rejects_bad_server_signature():
    captured: list[dict] = []
    client = _mock_client("super-secret", captured, forge_bad_server_sig=True)
    assert client.get_control() is None  # firma del servidor inválida -> se descarta


# ----------------------------- buffer de reintento ---------------------------


class _FlakyClient:
    def __init__(self):
        self.calls: list[list[dict]] = []
        self.ok = False

    def post_events(self, events):
        self.calls.append(list(events))
        return self.ok


def test_event_buffer_retries_without_loss():
    fake = _FlakyClient()
    sender = EventSender(fake, interval=0.0, jitter=0.0)
    sender.enqueue({"path": "/1"})
    sender._flush()  # falla la red: el evento queda en buffer
    assert sender._pending == [{"path": "/1"}]

    fake.ok = True
    sender.enqueue({"path": "/2"})
    sender._flush()  # reintenta el retenido + el nuevo, en orden
    assert fake.calls[-1] == [{"path": "/1"}, {"path": "/2"}]
    assert sender._pending == []


# ----------------------------- config desde entorno --------------------------


def test_config_from_env_and_defaults():
    cfg = AgentConfig.from_env({"MOQESH_SERVER": "http://s:5000/", "MOQESH_KEY_ID": "mq_1", "MOQESH_SECRET": "x"})
    assert cfg.server == "http://s:5000" and cfg.port == 8080
    assert cfg.control_interval == 30.0 and cfg.beacon_jitter == 0.3

    try:
        AgentConfig.from_env({"MOQESH_SERVER": "http://s"})
    except ValueError as exc:
        assert "MOQESH_KEY_ID" in str(exc) and "MOQESH_SECRET" in str(exc)
    else:
        raise AssertionError("debió exigir key_id/secret")
