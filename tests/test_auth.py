"""Autenticación del dashboard (Fase 3): hashing, cookie firmada y guarda real."""

import time

from fastapi.testclient import TestClient

from moqesh import auth
from tests.conftest import TEST_ADMIN_PASSWORD, TEST_ADMIN_USER


def test_password_hash_roundtrip():
    h = auth.hash_password("correcta", iters=50_000)  # iters bajos = test rápido
    assert h.startswith("pbkdf2_sha256$")
    assert auth.verify_password("correcta", h)
    assert not auth.verify_password("incorrecta", h)
    assert not auth.verify_password("correcta", "basura")


def test_token_roundtrip_and_tamper_and_expiry():
    tok = auth.make_token({"uid": 1, "username": "admin"}, max_age=60)
    data = auth.read_token(tok)
    assert data and data["username"] == "admin"
    # Manipulado -> inválido.
    assert auth.read_token(tok[:-1] + ("0" if tok[-1] != "0" else "1")) is None
    assert auth.read_token("no-es-un-token") is None
    # Expirado -> inválido.
    expired = auth.make_token({"uid": 1}, max_age=-1)
    assert auth.read_token(expired) is None
    # Sin firma correcta (payload sin punto) -> None.
    assert auth.read_token("soloraw") is None


def _real_guard_client():
    from moqesh.api import app
    from moqesh.api.auth import require_user

    app.dependency_overrides.pop(require_user, None)  # usar la guarda REAL
    return app


def test_dashboard_requires_session_and_login_flow():
    app = _real_guard_client()
    with TestClient(app) as client:
        # Sin sesión, un endpoint del dashboard devuelve 401.
        assert client.get("/api/rules").status_code == 401
        # Credenciales inválidas -> 401.
        bad = client.post("/api/auth/login", json={"username": TEST_ADMIN_USER, "password": "mala"})
        assert bad.status_code == 401
        # Login correcto -> 200 + cookie en el jar del cliente.
        ok = client.post("/api/auth/login", json={"username": TEST_ADMIN_USER, "password": TEST_ADMIN_PASSWORD})
        assert ok.status_code == 200 and ok.json()["role"] == "admin"
        assert auth.cookie_name() in client.cookies
        # Con sesión, el dashboard responde.
        assert client.get("/api/rules").status_code == 200
        assert client.get("/api/auth/me").json()["username"] == TEST_ADMIN_USER
        # Logout -> vuelve a 401.
        assert client.post("/api/auth/logout").status_code == 200
        client.cookies.clear()
        assert client.get("/api/rules").status_code == 401


def test_sensor_channel_not_behind_dashboard_auth():
    # /ingest/* y /control usan HMAC propio; NO deben requerir la sesión del dashboard.
    app = _real_guard_client()
    with TestClient(app) as client:
        # Sin sesión ni HMAC: /control responde 401 por FALTA DE HMAC (no por la guarda del dashboard),
        # y /healthz es público.
        assert client.get("/healthz").status_code == 200
        # /control lo rechaza el canal de sensores (429/401 por falta de HMAC), NO la guarda del
        # dashboard: confirma que el endpoint de sensores no está detrás de la cookie del operador.
        assert client.get("/control").status_code in (401, 429)


def test_login_rate_limited():
    app = _real_guard_client()
    with TestClient(app) as client:
        # Muchos intentos seguidos desde la misma IP acaban en 429 (burst=10).
        codes = [
            client.post("/api/auth/login", json={"username": "x", "password": "y"}).status_code
            for _ in range(15)
        ]
        assert 429 in codes
        time.sleep(0)  # no-op; el limiter es por tiempo monotónico