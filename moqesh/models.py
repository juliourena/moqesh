"""Modelos SQLAlchemy 2.0 — port completo de `Moqesh.Core.Models`.

Equivale a EF Core (`MoqeshDbContext`). Atributos en snake_case; la serializacion
camelCase para el frontend se hace en los controllers (dashboard/api).
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    """UTC naive (consistente con las columnas DateTime de SQLite)."""
    return datetime.now(UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class HoneypotConfig(Base):
    __tablename__ = "honeypots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    type: Mapped[str] = mapped_column(String(50), default="HTTP")
    port: Mapped[int] = mapped_column(Integer, default=8080)
    is_active: Mapped[bool] = mapped_column(default=True)
    content_path: Mapped[str] = mapped_column(String(512), default="")
    token_exhaust_enabled: Mapped[bool] = mapped_column(default=False)
    generation_mode: Mapped[str] = mapped_column(String(20), default="Template")
    seed: Mapped[str] = mapped_column(String(64), default="")
    target_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    realism_level: Mapped[int] = mapped_column(Integer, default=3)
    tarpit_delay_ms: Mapped[int] = mapped_column(Integer, default=0)
    server_banner: Mapped[str] = mapped_column(String(128), default="nginx")
    vocabulary_theme: Mapped[str] = mapped_column(String(20), default="")
    brand_name: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    requests: Mapped[list[RequestLog]] = relationship(back_populates="honeypot")


class AgentSession(Base):
    __tablename__ = "sessions"
    __table_args__ = (Index("ix_sessions_source_ip", "source_ip"), Index("ix_sessions_score", "ai_probability_score"))

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_ip: Mapped[str] = mapped_column(String(64), default="")
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    request_count: Mapped[int] = mapped_column(Integer, default=0)
    ai_probability_score: Mapped[float] = mapped_column(Float, default=0.0)
    matched_rules: Mapped[str | None] = mapped_column(Text, nullable=True)
    tokens_estimated: Mapped[int] = mapped_column(Integer, default=0)
    max_depth_reached: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="Active")
    nodes_served: Mapped[int] = mapped_column(Integer, default=0)
    time_wasted_ms: Mapped[int] = mapped_column(Integer, default=0)
    verdict: Mapped[str] = mapped_column(String(20), default="Unknown")
    verdict_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    verdict_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_attribution: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sensor_id: Mapped[int | None] = mapped_column(ForeignKey("sensors.id"), nullable=True, index=True)

    requests: Mapped[list[RequestLog]] = relationship(back_populates="session")
    alerts: Mapped[list[Alert]] = relationship(back_populates="session")


class RequestLog(Base):
    __tablename__ = "request_logs"
    __table_args__ = (
        Index("ix_req_ts", "timestamp"),
        Index("ix_req_ip", "source_ip"),
        Index("ix_req_session", "session_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    honeypot_id: Mapped[int] = mapped_column(ForeignKey("honeypots.id"))
    session_id: Mapped[int | None] = mapped_column(ForeignKey("sessions.id"), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    source_ip: Mapped[str] = mapped_column(String(64), default="")
    method: Mapped[str] = mapped_column(String(10), default="")
    path: Mapped[str] = mapped_column(Text, default="")
    query_string: Mapped[str | None] = mapped_column(Text, nullable=True)
    headers: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_code: Mapped[int] = mapped_column(Integer, default=200)
    response_size: Mapped[int] = mapped_column(Integer, default=0)
    processing_time_ms: Mapped[float] = mapped_column(Float, default=0.0)
    sensor_id: Mapped[int | None] = mapped_column(ForeignKey("sensors.id"), nullable=True, index=True)

    honeypot: Mapped[HoneypotConfig] = relationship(back_populates="requests")
    session: Mapped[AgentSession] = relationship(back_populates="requests")


class DetectionRule(Base):
    __tablename__ = "detection_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    weight: Mapped[float] = mapped_column(Float, default=0.0)
    rule_type: Mapped[str] = mapped_column(String(64), default="")
    parameters: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    mitre_attack_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    mitre_atlas_id: Mapped[str | None] = mapped_column(String(32), nullable=True)


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (Index("ix_alert_created", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"))
    sensor_id: Mapped[int | None] = mapped_column(ForeignKey("sensors.id"), nullable=True, index=True)
    severity: Mapped[str] = mapped_column(String(20), default="Medium")
    title: Mapped[str] = mapped_column(String(256), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    triggered_rules: Mapped[str | None] = mapped_column(Text, nullable=True)
    notified_via: Mapped[str | None] = mapped_column(String(128), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    session: Mapped[AgentSession] = relationship(back_populates="alerts")


class Honeytoken(Base):
    __tablename__ = "honeytokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String(32), default="")
    value: Mapped[str] = mapped_column(Text, default="")
    deployed_in: Mapped[str | None] = mapped_column(Text, nullable=True)
    triggered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    triggered_by_session_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_metadata: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SiteProfile(Base):
    __tablename__ = "site_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    target_url: Mapped[str] = mapped_column(String(512), default="")
    profile_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Scenario(Base):
    __tablename__ = "scenarios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    nodes: Mapped[list[ScenarioNode]] = relationship(back_populates="scenario", cascade="all, delete-orphan")
    credentials: Mapped[list[ScenarioCredential]] = relationship(
        back_populates="scenario", cascade="all, delete-orphan"
    )


class ScenarioNode(Base):
    __tablename__ = "scenario_nodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scenario_id: Mapped[int] = mapped_column(ForeignKey("scenarios.id"))
    path: Mapped[str] = mapped_column(Text, default="")
    visibility: Mapped[str] = mapped_column(String(16), default="linked")
    kind: Mapped[str] = mapped_column(String(16), default="file")
    content_type: Mapped[str] = mapped_column(String(128), default="text/plain; charset=utf-8")
    body_template: Mapped[str] = mapped_column(Text, default="")
    requires_credential_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    grants_credential_keys: Mapped[str | None] = mapped_column(Text, nullable=True)
    hinted_by_paths: Mapped[str | None] = mapped_column(Text, nullable=True)
    stage: Mapped[int] = mapped_column(Integer, default=0)
    binary_kind: Mapped[str] = mapped_column(String(16), default="none")
    binary_secret: Mapped[str] = mapped_column(Text, default="")

    scenario: Mapped[Scenario] = relationship(back_populates="nodes")


class ScenarioCredential(Base):
    __tablename__ = "scenario_credentials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scenario_id: Mapped[int] = mapped_column(ForeignKey("scenarios.id"))
    key: Mapped[str] = mapped_column(String(64), default="")
    username: Mapped[str | None] = mapped_column(String(128), nullable=True)
    secret: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(16), default="bearer")
    found_in_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    usable_at_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    scenario: Mapped[Scenario] = relationship(back_populates="credentials")


class SessionProgress(Base):
    __tablename__ = "session_progress"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(Integer)
    scenario_id: Mapped[int] = mapped_column(Integer)
    sensor_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stage_reached: Mapped[int] = mapped_column(Integer, default=0)
    credentials_obtained: Mapped[str] = mapped_column(Text, default="")
    credentials_used: Mapped[str] = mapped_column(Text, default="")
    hidden_hits: Mapped[int] = mapped_column(Integer, default=0)
    decompile_follow: Mapped[bool] = mapped_column(default=False)
    failed_auth_attempts: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class BlockedIp(Base):
    __tablename__ = "blocked_ips"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ip: Mapped[str] = mapped_column(String(64), default="")
    reason: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(16), default="auto")
    session_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sensor_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Sensor(Base):
    """Punto de despliegue: honeypot local, agente remoto o endpoint agentless.

    `api_secret` es la clave simétrica compartida (HMAC en ambos sentidos); de
    mínimo privilegio y revocable. Si la DB se filtra, se rota la clave.
    """

    __tablename__ = "sensors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    kind: Mapped[str] = mapped_column(String(16), default="agent")  # local | agent | agentless
    enabled: Mapped[bool] = mapped_column(default=True)
    status: Mapped[str] = mapped_column(String(16), default="unknown")  # online | offline | unknown
    last_seen: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_ingest_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Generación de contenido del sensor (su propio seed → anti-fingerprint).
    seed: Mapped[str] = mapped_column(String(64), default="")
    scenario_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    generation_mode: Mapped[str] = mapped_column(String(20), default="Template")
    realism_level: Mapped[int] = mapped_column(Integer, default=3)
    vocabulary_theme: Mapped[str] = mapped_column(String(20), default="")
    brand_name: Mapped[str] = mapped_column(String(128), default="")

    # Qué cubre / dónde vive el cebo (agentless: prefijo para filtrar logs).
    covered_url: Mapped[str] = mapped_column(String(512), default="")
    covered_app: Mapped[str] = mapped_column(String(200), default="")
    base_path: Mapped[str] = mapped_column(String(512), default="/")

    # Credenciales simétricas + control de versión.
    key_id: Mapped[str] = mapped_column(String(32), unique=True, index=True, default="")
    api_secret: Mapped[str] = mapped_column(String(128), default="")
    install_token: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)  # un solo uso
    agent_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    config_version: Mapped[int] = mapped_column(Integer, default=1)

    retired: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class User(Base):
    """Usuario del dashboard. v1: un admin único (bootstrap por env). La contraseña se
    guarda hasheada con PBKDF2-HMAC-SHA256 (stdlib); nunca en claro."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(128), unique=True, index=True, default="")
    password_hash: Mapped[str] = mapped_column(String(256), default="")
    role: Mapped[str] = mapped_column(String(16), default="admin")  # admin | viewer (v1: solo admin)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_login: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class SensorBundle(Base):
    """Registro de auditoría de los ZIP generados para un sensor agentless."""

    __tablename__ = "sensor_bundles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sensor_id: Mapped[int] = mapped_column(ForeignKey("sensors.id"), index=True)
    filename: Mapped[str] = mapped_column(String(200), default="")
    seed: Mapped[str] = mapped_column(String(64), default="")
    archive_format: Mapped[str] = mapped_column(String(8), default="zip")  # zip | tgz
    structure_summary: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
