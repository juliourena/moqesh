"""Tiempo real con WebSocket nativo (reemplazo de SignalR).

Un único `ConnectionManager` compartido en el proceso: el dashboard registra los
WebSocket de los navegadores y el honeypot publica eventos (`request`, `alert`).
Como el honeypot corre en el threadpool (endpoints sync), publica de forma
thread-safe agendando el envío en el event loop ya capturado.
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import WebSocket

logger = logging.getLogger("moqesh.realtime")


class ConnectionManager:
    def __init__(self) -> None:
        self._active: set[WebSocket] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._active.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._active.discard(ws)

    async def _send_all(self, msg: str) -> None:
        for ws in list(self._active):
            try:
                await ws.send_text(msg)
            except Exception:
                self._active.discard(ws)

    async def apublish(self, event: str, data: dict) -> None:
        """Publica desde un contexto async (p.ej. el propio dashboard)."""
        if self._active:
            await self._send_all(json.dumps({"event": event, "data": data}, default=str))

    def publish(self, event: str, data: dict) -> None:
        """Publica desde un contexto sync/otro hilo (el honeypot). Fire-and-forget."""
        if not self._active or self._loop is None:
            return
        msg = json.dumps({"event": event, "data": data}, default=str)
        try:
            asyncio.run_coroutine_threadsafe(self._send_all(msg), self._loop)
        except Exception:
            pass

    def schedule(self, coro) -> None:
        """Agenda una corrutina (webhook, confirmación IA) en el event loop, sin esperar."""
        if self._loop is not None:
            try:
                asyncio.run_coroutine_threadsafe(coro, self._loop)
                return
            except Exception:
                pass
        try:
            asyncio.run(coro)
        except Exception:
            logger.debug("No se pudo agendar la corrutina en background", exc_info=True)


manager = ConnectionManager()
