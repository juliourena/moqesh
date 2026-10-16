"""Entrypoint: levanta honeypot (:8080) y dashboard+API (:5000) en un proceso.

Ambas apps ASGI corren sobre el mismo event loop asyncio (una por `uvicorn.Server`).
"""

from __future__ import annotations

import asyncio

import uvicorn

from .api import app as api_app
from .config import settings
from .honeypot import app as honeypot_app


async def _serve() -> None:
    # server_header=False: uvicorn NO añade su propia cabecera `Server: uvicorn`. El honeypot
    # emite exactamente UNA cabecera `Server` (su banner), como un web server real; dos cabeceras
    # Server (una del framework, otra del banner) delatarían el montaje.
    # server_header/date_header=False: uvicorn NO añade sus cabeceras `Server`/`Date`. El
    # honeypot las emite él mismo, en Title-Case y con un único banner coherente, igual que un
    # web server real (nginx/IIS); si no, delataría el stack ASGI (minúsculas, doble Server).
    honeypot = uvicorn.Server(
        uvicorn.Config(
            honeypot_app, host="0.0.0.0", port=settings.honeypot_port,
            log_level="warning", server_header=False, date_header=False,
        )
    )
    dashboard = uvicorn.Server(
        uvicorn.Config(
            api_app, host="0.0.0.0", port=settings.dashboard_port,
            log_level="info", server_header=False, date_header=False,
        )
    )
    print(f"Honeypot  -> http://localhost:{settings.honeypot_port}")
    print(f"Dashboard -> http://localhost:{settings.dashboard_port}  (API en /api, WS en /hubs/stream)")
    await asyncio.gather(honeypot.serve(), dashboard.serve())


def main() -> None:
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
