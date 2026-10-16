"""Autenticación del dashboard: login/logout/me + dependencia `require_user`.

Protege los routers del dashboard (`/api/*`) con una sesión por cookie firmada.
NO toca el canal de sensores (`/ingest/*`, `/control`, `/s/*`, `/download/*`,
`/healthz`), que conserva su propia autenticación HMAC.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import auth
from ..config import settings
from ..db import get_session
from ..models import User
from ..security import RateLimiter

router = APIRouter(prefix="/auth", tags=["auth"])

# Rate-limit del login por IP (anti fuerza bruta): ~20/min, ráfaga 10.
_login_limiter = RateLimiter(per_minute=20, burst=10)


class LoginBody(BaseModel):
    username: str
    password: str


def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def require_user(request: Request) -> dict:
    """Dependencia de guarda: exige una sesión válida o devuelve 401."""
    data = auth.read_token(request.cookies.get(auth.cookie_name()))
    if data is None:
        raise HTTPException(status_code=401, detail="no autenticado")
    return data


@router.post("/login")
def login(body: LoginBody, request: Request, response: Response, db: Session = Depends(get_session)) -> dict:
    if not _login_limiter.allow(_client_ip(request)):
        raise HTTPException(status_code=429, detail="demasiados intentos; espera un momento")
    user = db.scalar(select(User).where(User.username == body.username).limit(1))
    # Verifica SIEMPRE (incluso sin usuario, contra un hash señuelo de iteraciones reales)
    # para no filtrar por tiempo si el usuario existe o no.
    stored = user.password_hash if user else auth.dummy_hash()
    if not auth.verify_password(body.password, stored) or user is None:
        raise HTTPException(status_code=401, detail="credenciales inválidas")
    auth.touch_last_login(db, user)
    token = auth.make_token({"uid": user.id, "username": user.username, "role": user.role},
                            max_age=settings.session_max_age)
    response.set_cookie(
        auth.cookie_name(),
        token,
        max_age=settings.session_max_age,
        httponly=True,
        samesite="strict",
        secure=settings.cookie_secure,
        path="/",
    )
    return {"username": user.username, "role": user.role}


@router.post("/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(auth.cookie_name(), path="/")
    return {"ok": True}


@router.get("/me")
def me(user: dict = Depends(require_user)) -> dict:
    return {"username": user.get("username"), "role": user.get("role")}
