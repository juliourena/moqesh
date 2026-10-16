"""Agente remoto de Moqesh.

Honeypot autónomo que corre en el borde (servidores de clientes). Se empaqueta como
binario autocontenido con PyInstaller (ver BUILD.md): NO depende de la DB, FastAPI,
SQLAlchemy ni pydantic-settings; sólo stdlib + httpx + los módulos puros del laberinto,
escenarios y seguridad.
"""

from __future__ import annotations

from .main import AgentConfig, build_event, build_scenario, progress_facts, update_progress

AGENT_VERSION = "0.1.0"

__all__ = [
    "AGENT_VERSION",
    "AgentConfig",
    "build_event",
    "build_scenario",
    "progress_facts",
    "update_progress",
]
