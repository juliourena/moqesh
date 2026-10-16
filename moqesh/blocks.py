"""Cierre del loop de respuesta: cuando un atacante se confirma (reuso de
credencial plantada o score sobre umbral) se registra su IP como bloqueada y
se notifica a un sistema externo (firewall/Caddy/Slack) vía webhook.

Referencia de comportamiento: `Moqesh.Alerts.BlockService` (C#). Aquí se
implementa en Python idiomático: capa de datos síncrona (SQLAlchemy `Session`,
igual que el resto del proyecto) y webhook asíncrono con `httpx.AsyncClient`.

El bloqueo a nivel SO (iptables) es OPCIONAL y está DESACTIVADO por defecto:
corremos en contenedor sin privilegios, así que el bloqueo real es a nivel
aplicación (el honeypot responde 403 a las IP activas) + webhook.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import logging
import os
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import BlockedIp

log = logging.getLogger("moqesh.blocks")


@dataclass(slots=True)
class NotificationOptions:
    """Configuración de notificación/bloqueo.

    Variables de entorno equivalentes (ver `from_env`):
      - MOQESH_WEBHOOK_URL      -> webhook_url   (vacío = no notifica)
      - MOQESH_WEBHOOK_SECRET   -> secret        (firma HMAC-SHA256 opcional)
      - MOQESH_ENFORCE_BLOCK    -> enforce_block (honeypot responde 403)
      - MOQESH_AUTO_BLOCK_SCORE -> auto_block_score (0 = desactivado)
      - MOQESH_ENABLE_IPTABLES  -> enable_iptables (DROP a nivel SO; peligroso)
    """

    # URL del webhook (Slack/Discord/genérico). Vacío = no se notifica.
    webhook_url: str = ""
    # Secreto opcional: añade header X-Moqesh-Signature con HMAC-SHA256 del body.
    secret: str = ""
    # Si True, el honeypot aplica el bloqueo (403) a las IP activas.
    enforce_block: bool = True
    # Auto-bloqueo por score (0.0 = desactivado; p.ej. 0.8 = bloquear sobre umbral).
    auto_block_score: float = 0.0
    # Bloqueo OS-level vía iptables. DESACTIVADO por defecto (requiere privilegios).
    enable_iptables: bool = False

    @classmethod
    def from_env(cls) -> NotificationOptions:
        """Construye las opciones desde variables de entorno."""
        return cls(
            webhook_url=os.environ.get("MOQESH_WEBHOOK_URL", ""),
            secret=os.environ.get("MOQESH_WEBHOOK_SECRET", ""),
            enforce_block=_env_bool("MOQESH_ENFORCE_BLOCK", True),
            auto_block_score=_env_float("MOQESH_AUTO_BLOCK_SCORE", 0.0),
            enable_iptables=_env_bool("MOQESH_ENABLE_IPTABLES", False),
        )


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


class BlockService:
    """Registra IP bloqueadas y dispara notificaciones. Idempotente por IP."""

    def __init__(self, options: NotificationOptions, http: httpx.AsyncClient | None = None) -> None:
        self.options = options
        # Si no recibimos un cliente lo creamos nosotros (y lo cerramos en aclose).
        self._http = http or httpx.AsyncClient(timeout=5.0)
        self._owns_http = http is None

    async def aclose(self) -> None:
        """Cierra el cliente httpx solo si lo creamos nosotros."""
        if self._owns_http:
            await self._http.aclose()

    # --- API pública -----------------------------------------------------

    async def block(
        self,
        db: Session,
        ip: str,
        reason: str,
        session_id: int | None = None,
        source: str = "auto",
        meta: dict | None = None,
    ) -> None:
        """Crea (si no existe) un bloqueo activo para `ip` y notifica.

        Idempotente: si ya hay un bloqueo activo para la IP, no duplica.
        El fallo del webhook degrada con elegancia (log, no rompe el bloqueo).
        """
        ip = (ip or "").strip()
        if not ip or ip == "unknown":
            return  # nada que bloquear

        if self._active_block(db, ip) is not None:
            return  # ya bloqueada -> idempotente

        db.add(BlockedIp(ip=ip, reason=reason, source=source, session_id=session_id, active=True))
        db.commit()
        log.warning("[block] IP %s bloqueada (%s): %s", ip, source, reason)

        # Bloqueo OS-level opcional (no-op salvo que enable_iptables=True).
        self._iptables_drop(ip)

        await self._notify(
            {
                "event": "attacker_blocked",
                "ip": ip,
                "reason": reason,
                "source": source,
                "session_id": session_id,
                "meta": meta,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )

    def is_blocked(self, db: Session, ip: str) -> bool:
        """True si la IP tiene un bloqueo activo."""
        ip = (ip or "").strip()
        if not ip:
            return False
        return self._active_block(db, ip) is not None

    def unblock(self, db: Session, block_id: int) -> None:
        """Marca el bloqueo como inactivo (active=False)."""
        row = db.get(BlockedIp, block_id)
        if row is None or not row.active:
            return
        row.active = False
        db.commit()
        log.info("[block] bloqueo #%s (%s) levantado", block_id, row.ip)

    # --- Internos --------------------------------------------------------

    def _active_block(self, db: Session, ip: str) -> BlockedIp | None:
        """Devuelve el bloqueo activo para la IP, o None."""
        return db.scalar(
            select(BlockedIp).where(BlockedIp.ip == ip, BlockedIp.active == True).limit(1)  # noqa: E712
        )

    async def _notify(self, payload: dict) -> None:
        """Envía el webhook; cualquier fallo se registra pero no propaga."""
        if not self.options.webhook_url.strip():
            return
        try:
            # Serializamos nosotros para firmar exactamente el body enviado.
            body = json.dumps(payload).encode("utf-8")
            headers = {"Content-Type": "application/json"}
            if self.options.secret:
                sig = hmac.new(self.options.secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
                headers["X-Moqesh-Signature"] = f"sha256={sig}"
            resp = await self._http.post(self.options.webhook_url, content=body, headers=headers)
            log.info("[block] webhook -> %s", resp.status_code)
        except Exception as ex:  # degradación elegante: nunca rompe el bloqueo
            log.warning("[block] webhook falló: %s", ex)

    def _iptables_drop(self, ip: str) -> None:
        """Bloqueo OS-level opcional. No-op (+ log) salvo enable_iptables=True.

        Valida que `ip` sea una dirección IP real antes de invocar subprocess
        (defensa en profundidad; además usamos args en lista, sin shell).
        """
        if not self.options.enable_iptables:
            log.debug("[block] iptables desactivado; omito DROP para %s", ip)
            return
        try:
            ipaddress.ip_address(ip)  # ValueError si no es IPv4/IPv6 válida
        except ValueError:
            log.warning("[block] IP inválida, no aplico iptables: %r", ip)
            return
        try:
            subprocess.run(
                ["iptables", "-A", "INPUT", "-s", ip, "-j", "DROP"],
                check=True,
                capture_output=True,
                timeout=5,
            )
            log.warning("[block] iptables DROP aplicado a %s", ip)
        except Exception as ex:  # sin privilegios/binario: degrada, no rompe
            log.warning("[block] iptables falló para %s: %s", ip, ex)
