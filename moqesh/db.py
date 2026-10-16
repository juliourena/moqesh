"""Capa de datos: engine SQLite + sesiones + inicialización/seed.

Síncrono a propósito (SQLite). Los endpoints `def` de FastAPI corren en su
threadpool, así que cada petición usa su propia `Session`. El HTTP saliente
(mimic, LLM, webhooks) sí es async y vive en otros módulos.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from .config import settings
from .models import Base, DetectionRule, HoneypotConfig, Sensor

_engine = create_engine(
    f"sqlite:///{os.path.abspath(settings.db_path)}",
    future=True,
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(bind=_engine, class_=Session, expire_on_commit=False, future=True)


def get_session() -> Iterator[Session]:
    """Dependencia FastAPI: cede una Session y la cierra al terminar."""
    with SessionLocal() as s:
        yield s


# 14 reglas conductuales/CTF (las 4 fuertes se alimentan del motor de escenarios).
_SEED_RULES = [
    (1, "Timing intermedio", "Inter-request intervals 2-30s; el LLM pausa mientras razona.", 0.15, "timing_analysis"),
    (2, "Secuencia predecible", "Acceso secuencial a todos los archivos (curl→file→exec).", 0.25, "sequence_pattern"),
    (3, "Descarga exhaustiva", "Descarga TODOS los archivos listados sin discriminar.", 0.15, "download_pattern"),
    (4, "README literal", "Ejecuta los comandos del README tal cual, en orden.", 0.20, "readme_following"),
    (5, "JS deobfuscation", "Accede a endpoints solo visibles desofuscando JS.", 0.10, "js_deobfuscation"),
    (6, "User-Agent / headers", "User-Agents conocidos de crawlers/clientes de IA.", 0.05, "user_agent"),
    (
        7,
        "Breadcrumb following",
        "Sigue la cadena de enlaces generados hacia más profundidad.",
        0.10,
        "breadcrumb_following",
    ),
    (8, "Descenso profundo", "Baja 5+ niveles siguiendo configs/.env (no humano).", 0.15, "depth_descent"),
    (
        9,
        "Fan-out exhaustivo",
        "Sigue casi todos los enlaces de cada página (cobertura ~total).",
        0.15,
        "exhaustive_fanout",
    ),
    (10, "Sin render de assets", "Nunca pide CSS/JS/img/favicon: no hay navegador.", 0.10, "no_asset_render"),
    (
        11,
        "Reuso de credenciales",
        "Presentó un honeytoken plantado en un gate: casi certeza.",
        0.35,
        "credential_reuse",
    ),
    (12, "Acceso a ruta oculta", "Accedió a una ruta no enlazada (pistas/fuzzing).", 0.20, "hidden_path_access"),
    (
        13,
        "Follow-up de decompilación",
        "Descargó un binario y siguió una ruta embebida en él.",
        0.20,
        "binary_decompile_followup",
    ),
    (14, "Fuerza bruta de auth", "Múltiples intentos fallidos contra un gate.", 0.10, "auth_bruteforce"),
]


def init_db() -> None:
    """Crea el esquema y siembra reglas, honeypot por defecto y escenario builtin."""
    Base.metadata.create_all(_engine)
    with SessionLocal() as s:
        if s.scalar(select(DetectionRule).limit(1)) is None:
            s.add_all(
                DetectionRule(id=i, name=n, description=d, weight=w, rule_type=rt, is_active=True)
                for (i, n, d, w, rt) in _SEED_RULES
            )
        seed = settings.seed or uuid.uuid4().hex
        if s.scalar(select(HoneypotConfig).limit(1)) is None:
            s.add(
                HoneypotConfig(
                    id=1,
                    name="Honeypot Web Server",
                    type="HTTP",
                    port=settings.honeypot_port,
                    is_active=True,
                    token_exhaust_enabled=settings.token_exhaust_enabled,
                    generation_mode=settings.generation_mode,
                    seed=seed,
                    target_url=settings.target_url,
                    realism_level=max(1, min(settings.realism_level, 5)),
                    tarpit_delay_ms=settings.tarpit_delay_ms,
                    server_banner=settings.server_banner,
                    vocabulary_theme=settings.vocabulary_theme,
                    brand_name=settings.brand_name,
                )
            )
        # Sensor `local`: el propio honeypot visto como sensor (mismo seed).
        if s.scalar(select(Sensor).where(Sensor.kind == "local").limit(1)) is None:
            s.add(
                Sensor(
                    name="local",
                    kind="local",
                    enabled=True,
                    status="online",
                    seed=seed,
                    generation_mode=settings.generation_mode,
                    realism_level=max(1, min(settings.realism_level, 5)),
                    vocabulary_theme=settings.vocabulary_theme,
                    brand_name=settings.brand_name,
                    covered_url=f"http://localhost:{settings.honeypot_port}",
                    covered_app="honeypot local",
                    base_path="/",
                )
            )
        s.commit()

    # Siembra el escenario CTF incorporado (import diferido: evita ciclo de importación).
    from .scenarios import seed_builtin

    with SessionLocal() as s:
        seed_builtin(s)
