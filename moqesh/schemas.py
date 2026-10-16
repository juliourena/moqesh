"""Schemas Pydantic (contrato del frontend).

Campos en snake_case; el alias camelCase se genera solo (`to_camel`), de modo
que el JSON que consume el React sale en camelCase sin construir dicts a mano.
Las fechas se emiten en ISO-8601 UTC con sufijo `Z`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, PlainSerializer
from pydantic.alias_generators import to_camel


def _iso_z(dt: datetime) -> str:
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC).replace(tzinfo=None)
    return dt.isoformat() + "Z"


# datetime que siempre serializa como UTC con 'Z' (el navegador lo interpreta bien).
UtcDateTime = Annotated[datetime, PlainSerializer(_iso_z, return_type=str)]


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)


# ---------------- Dashboard ----------------


class AlertSummary(CamelModel):
    id: int
    severity: str
    title: str
    created_at: UtcDateTime
    acknowledged: bool


class TimeSeriesPoint(CamelModel):
    timestamp: UtcDateTime
    count: int


class ScoreDistributionPoint(CamelModel):
    range: str
    count: int


class TopSourceEntry(CamelModel):
    ip: str
    request_count: int
    max_score: float


class DashboardOverview(CamelModel):
    total_requests: int
    active_sessions: int
    ai_agents_detected: int
    unresolved_alerts: int
    requests_over_time: list[TimeSeriesPoint]
    score_distribution: list[ScoreDistributionPoint]
    top_sources: list[TopSourceEntry]
    recent_alerts: list[AlertSummary]


# ---------------- Sesiones / requests ----------------


class SessionDto(CamelModel):
    id: int
    source_ip: str
    user_agent: str | None
    first_seen: UtcDateTime
    last_seen: UtcDateTime
    request_count: int
    ai_probability_score: float
    status: str
    tokens_estimated: int
    nodes_served: int
    time_wasted_ms: int
    max_depth_reached: int
    matched_rules: str | None
    verdict: str
    verdict_confidence: float
    verdict_reasoning: str | None
    model_attribution: str | None


class RequestLogDto(CamelModel):
    id: int
    honeypot_id: int
    session_id: int | None
    timestamp: UtcDateTime
    source_ip: str
    method: str
    path: str
    user_agent: str | None
    response_code: int
    processing_time_ms: float


class ScenarioProgressDto(CamelModel):
    stage_reached: int
    credentials_obtained: str
    credentials_used: str
    hidden_hits: int
    decompile_follow: bool
    failed_auth_attempts: int


class SessionDetailDto(CamelModel):
    session: SessionDto
    requests: list[RequestLogDto]
    alerts: list[AlertSummary]
    progress: ScenarioProgressDto | None


# ---------------- Token Exhaust ----------------


class TokenBySourceEntry(CamelModel):
    ip: str
    tokens: int
    time_wasted_ms: int
    nodes: int
    max_depth: int
    score: float
    verdict: str


class ModelAttributionEntry(CamelModel):
    model: str
    sessions: int
    tokens: int
    avg_score: float


class TokenExhaustOverview(CamelModel):
    total_tokens_burned: int
    total_time_wasted_ms: int
    total_nodes_served: int
    sessions_engaged: int
    top_burners: list[TokenBySourceEntry]
    by_model: list[ModelAttributionEntry]


# ---------------- Honeypots / reglas / blocks ----------------


class HoneypotDto(CamelModel):
    id: int
    name: str
    type: str
    port: int
    is_active: bool
    token_exhaust_enabled: bool
    created_at: UtcDateTime
    request_count: int


class DetectionRuleDto(CamelModel):
    id: int
    name: str
    description: str
    weight: float
    rule_type: str
    is_active: bool
    mitre_attack_id: str | None = None
    mitre_atlas_id: str | None = None


class BlockedIpDto(CamelModel):
    id: int
    ip: str
    reason: str
    source: str
    session_id: int | None
    active: bool
    created_at: UtcDateTime


# ---------------- Escenarios ----------------


class ScenarioSummary(CamelModel):
    id: int
    name: str
    description: str
    is_active: bool
    created_at: UtcDateTime
    node_count: int
    cred_count: int


class ScenarioNodeDto(CamelModel):
    id: int
    scenario_id: int
    path: str
    visibility: str
    kind: str
    content_type: str
    body_template: str
    requires_credential_key: str | None
    grants_credential_keys: str | None
    hinted_by_paths: str | None
    stage: int
    binary_kind: str
    binary_secret: str


class ScenarioCredentialDto(CamelModel):
    id: int
    scenario_id: int
    key: str
    username: str | None
    secret: str
    kind: str
    found_in_path: str | None
    usable_at_path: str | None


class ScenarioInfo(CamelModel):
    id: int
    name: str
    description: str
    is_active: bool
    created_at: UtcDateTime


class ScenarioDetail(CamelModel):
    scenario: ScenarioInfo
    nodes: list[ScenarioNodeDto]
    credentials: list[ScenarioCredentialDto]


# ---------------- Request bodies ----------------


class CreateHoneypotRequest(CamelModel):
    name: str
    type: str = "HTTP"
    port: int = 8080


class UpdateHoneypotRequest(CamelModel):
    name: str | None = None
    port: int | None = None
    is_active: bool | None = None
    token_exhaust_enabled: bool | None = None


class UpdateRuleRequest(CamelModel):
    weight: float | None = None
    is_active: bool | None = None


class BlockRequest(CamelModel):
    ip: str
    reason: str | None = None


# ---------------- Sensores ----------------


class SensorDto(CamelModel):
    id: int
    name: str
    kind: str
    enabled: bool
    status: str
    last_seen: UtcDateTime | None
    last_ingest_at: UtcDateTime | None
    seed: str
    scenario_id: int | None
    generation_mode: str
    realism_level: int
    covered_url: str
    covered_app: str
    base_path: str
    agent_version: str | None
    config_version: int
    created_at: UtcDateTime
    session_count: int = 0
    alert_count: int = 0


class CreateSensorRequest(CamelModel):
    name: str
    kind: str = "agent"  # agent | agentless
    covered_url: str = ""
    covered_app: str = ""
    base_path: str = "/"
    generation_mode: str = "Template"
    realism_level: int = 3
    vocabulary_theme: str = ""
    scenario_id: int | None = None


class SensorCreated(CamelModel):
    """Respuesta de alta: el secreto y el comando se muestran UNA sola vez."""

    id: int
    name: str
    kind: str
    key_id: str
    api_secret: str
    install_token: str
    install_command: str


class SensorBundleDto(CamelModel):
    id: int
    sensor_id: int
    filename: str
    seed: str
    archive_format: str
    created_at: UtcDateTime
