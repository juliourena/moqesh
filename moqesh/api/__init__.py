"""App del dashboard (puerto 5000): API REST + WebSocket + SPA React.

Monta los routers por recurso bajo `/api`, un WebSocket nativo en `/hubs/stream`
(reemplazo de SignalR) y sirve el build de React (`web/dist`) si existe.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from .. import provisioning
from ..auth import bootstrap_admin
from ..config import settings
from ..db import SessionLocal, init_db
from ..models import Sensor
from ..realtime import manager
from . import auth, blocks, dashboard, honeypots, monitoring, node, scenarios, sensors, sessions
from .auth import require_user

_CLIENTS = Path(__file__).resolve().parents[1] / "clients"  # scripts del shipper (entrega aparte)
_AGENT_DIST = Path(__file__).resolve().parents[1] / "agent" / "dist"  # binarios del agente (build aparte)
_BUNDLES = Path(settings.db_path).resolve().parent / "bundles"  # ZIPs generados

_DIST = Path(settings.web_dist) if settings.web_dist else Path(__file__).resolve().parents[2] / "web" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    with SessionLocal() as db:
        bootstrap_admin(db)
    manager.bind_loop(asyncio.get_running_loop())
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Moqesh Dashboard API", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=True,
    )

    # Login/logout/me: público (la guarda vive dentro de /me). El resto del dashboard
    # queda protegido por sesión (require_user).
    app.include_router(auth.router, prefix="/api")
    for router in (
        dashboard.router,
        sessions.router,
        monitoring.router,
        honeypots.router,
        scenarios.router,
        blocks.router,
        sensors.router,
    ):
        app.include_router(router, prefix="/api", dependencies=[Depends(require_user)])

    # Endpoints de cara a los sensores (sin prefijo /api): /ingest/*, /control.
    # Conservan su autenticación HMAC propia; NO llevan la sesión del dashboard.
    app.include_router(node.router)

    @app.get("/s/{token}", response_class=PlainTextResponse)
    def install_script(token: str) -> str:
        """Instalador de un comando (curl | sh). La install_token es de un solo uso."""
        with SessionLocal() as db:
            s = db.scalar(select(Sensor).where(Sensor.install_token == token, Sensor.retired.is_(False)).limit(1))
            if s is None:
                raise HTTPException(status_code=404, detail="token inválido o ya usado")
            key_id, secret, kind, sid, base = s.key_id, s.api_secret, s.kind, s.id, s.base_path
            s.install_token = None  # consumir
            db.commit()
        if kind == "agentless":
            steps = provisioning.agentless_steps(sid, key_id, secret, base, bundle_count=3)
            body = "#!/bin/sh\n# Configuración agentless de Moqesh (revisa antes de ejecutar)\n"
            body += f"mkdir -p /opt/moqesh\n{steps['steps'][0]}\n"
            body += f"echo \"Cron a añadir:\"\necho '{steps['cron']}'\n"
            return body
        return provisioning.agent_install_script(key_id, secret)

    @app.get("/download/agent/{target}")
    def download_agent(target: str) -> FileResponse:
        safe = target.replace("/", "_").replace("..", "")
        path = _AGENT_DIST / f"moqesh-agent-{safe}"
        if not path.is_file():
            raise HTTPException(status_code=404, detail="binario del agente no disponible (build pendiente)")
        return FileResponse(path, filename="moqesh-agent")

    @app.get("/download/shipper/{sensor_id}")
    def download_shipper(sensor_id: int) -> FileResponse:
        path = _CLIENTS / "moqesh-ship.sh"
        if not path.is_file():
            raise HTTPException(status_code=404, detail="script de envío no disponible")
        return FileResponse(path, filename="moqesh-ship.sh", media_type="text/x-shellscript")

    @app.get("/download/bundle/{bundle_id}")
    def download_bundle(bundle_id: str) -> FileResponse:
        safe = bundle_id.replace("/", "_").replace("..", "")
        for ext in (".zip", ".tar.gz"):
            path = _BUNDLES / f"{safe}{ext}"
            if path.is_file():
                return FileResponse(path, filename=path.name)
        raise HTTPException(status_code=404, detail="bundle no encontrado")

    @app.websocket("/hubs/stream")
    async def stream(ws: WebSocket) -> None:
        await manager.connect(ws)
        try:
            while True:
                await ws.receive_text()  # mantiene viva la conexión (ignora el contenido)
        except WebSocketDisconnect:
            manager.disconnect(ws)
        except Exception:
            manager.disconnect(ws)

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    if _DIST.exists():
        app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")

        @app.get("/{full_path:path}")
        def spa(full_path: str):
            candidate = _DIST / full_path
            if full_path and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(_DIST / "index.html")

    return app


app = create_app()
