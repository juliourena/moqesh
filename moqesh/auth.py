"""Autenticación del dashboard (admin único) — sin dependencias nuevas.

- Contraseñas: PBKDF2-HMAC-SHA256 (stdlib `hashlib`), salt por usuario, comparación
  en tiempo constante. Formato: ``pbkdf2_sha256$<iters>$<salt_b64>$<hash_b64>``.
- Sesión: cookie firmada con HMAC-SHA256 (stdlib), con expiración embebida y
  verificada. No hay estado de sesión en servidor (stateless, a prueba de reinicios).
- El secreto de firma es estable por despliegue: `MOQESH_SESSION_SECRET` o, si está
  vacío, uno generado y persistido junto a la DB (volumen Docker).

Separado del canal de sensores (`security.py`, HMAC simétrico): aquel protege
sensor↔servidor; este, operador↔dashboard.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import User, utcnow

logger = logging.getLogger("moqesh.auth")

_PBKDF2_ITERS = 600_000  # recomendación OWASP para PBKDF2-HMAC-SHA256
_COOKIE_NAME = "moqesh_session"


# ------------------------------- contraseñas --------------------------------


def hash_password(password: str, *, iters: int = _PBKDF2_ITERS) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iters)
    return f"pbkdf2_sha256${iters}${_b64e(salt)}${_b64e(dk)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters_s, salt_b64, hash_b64 = stored.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), _b64d(salt_b64), int(iters_s))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(dk, _b64d(hash_b64))


_dummy_hash: str | None = None


def dummy_hash() -> str:
    """Hash señuelo con las MISMAS iteraciones que uno real. El login lo verifica cuando el
    usuario no existe, para que el tiempo de respuesta no revele si existe o no."""
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = hash_password(secrets.token_hex(8))
    return _dummy_hash


# ------------------------------ cookie firmada ------------------------------


def make_token(payload: dict, *, max_age: int) -> str:
    data = {**payload, "exp": int(time.time()) + max_age}
    raw = _b64e(json.dumps(data, separators=(",", ":")).encode())
    sig = _sign(raw)
    return f"{raw}.{sig}"


def read_token(token: str | None) -> dict | None:
    if not token or "." not in token:
        return None
    raw, sig = token.rsplit(".", 1)
    if not hmac.compare_digest(_sign(raw), sig):
        return None
    try:
        data = json.loads(_b64d(raw))
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict) or int(data.get("exp", 0)) < int(time.time()):
        return None
    return data


def cookie_name() -> str:
    return _COOKIE_NAME


# ------------------------------- bootstrap ----------------------------------


def bootstrap_admin(session: Session) -> None:
    """Crea el usuario admin si aún no hay usuarios. La contraseña sale de
    `MOQESH_ADMIN_PASSWORD`; si está vacía, se genera una y se imprime UNA vez en el log."""
    if session.scalar(select(User).limit(1)) is not None:
        return
    username = settings.admin_user or "admin"
    password = settings.admin_password
    generated = False
    if not password:
        password = secrets.token_urlsafe(12)
        generated = True
    session.add(User(username=username, password_hash=hash_password(password), role="admin"))
    session.commit()
    if generated:
        logger.warning(
            "[auth] Usuario admin '%s' creado con contraseña GENERADA (una sola vez): %s\n"
            "       Cámbiala o fija MOQESH_ADMIN_PASSWORD y recrea el usuario.",
            username,
            password,
        )
    else:
        logger.info("[auth] Usuario admin '%s' creado desde MOQESH_ADMIN_PASSWORD.", username)


def touch_last_login(session: Session, user: User) -> None:
    user.last_login = utcnow()
    session.commit()


# ------------------------------- internos -----------------------------------


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _sign(raw: str) -> str:
    return hmac.new(_secret(), raw.encode(), hashlib.sha256).hexdigest()


_cached_secret: bytes | None = None


def _secret() -> bytes:
    """Secreto de firma estable por despliegue (env o fichero persistido junto a la DB)."""
    global _cached_secret
    if _cached_secret is not None:
        return _cached_secret
    if settings.session_secret:
        _cached_secret = settings.session_secret.encode()
        return _cached_secret
    path = os.path.join(os.path.dirname(os.path.abspath(settings.db_path)) or ".", ".moqesh_session_secret")
    try:
        if os.path.isfile(path):
            with open(path, "rb") as f:
                _cached_secret = f.read().strip()
                if _cached_secret:
                    return _cached_secret
        generated = secrets.token_hex(32).encode()
        with open(path, "wb") as f:
            f.write(generated)
        os.chmod(path, 0o600)
        _cached_secret = generated
    except OSError:
        # Último recurso: secreto efímero en memoria (las sesiones no sobreviven a un reinicio).
        logger.warning("[auth] No se pudo persistir el secreto de sesión; se usa uno efímero.")
        _cached_secret = secrets.token_hex(32).encode()
    return _cached_secret
