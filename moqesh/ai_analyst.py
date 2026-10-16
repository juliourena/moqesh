"""Modulo OPCIONAL de confirmacion de agentes IA en la zona gris.

El sistema de deteccion por reglas (`detection.py`) funciona de forma autonoma y
asigna a cada sesion un score 0..1. Las sesiones con score intermedio (zona gris)
son ambiguas: aqui las revisamos una vez mas, con un clasificador que puede ser
puramente heuristico (sin tokens, sin red) o apoyarse en un LLM compatible con la
API de OpenAI (OpenRouter, endpoint local, etc.). Si el LLM no esta disponible o
falla, se degrada de forma elegante al heuristico: el modulo NUNCA bloquea el
pipeline y es seguro ejecutarlo sin configurar ninguna clave.

Referencia de comportamiento: `Moqesh.AiAnalyst` (C#).

Variables de entorno equivalentes a `AiConfirmationOptions` (ver `from_env`):
    MOQESH_AI_ENABLED          -> enabled          ("1"/"true"/"yes" = True)
    MOQESH_AI_PROVIDER         -> provider         ("heuristic" | "openai")
    MOQESH_AI_BASE_URL         -> base_url         (p.ej. https://openrouter.ai/api/v1)
    MOQESH_AI_API_KEY          -> api_key          (nunca hardcodear secretos)
    MOQESH_AI_MODEL            -> model            (p.ej. anthropic/claude-3.5-haiku)
    MOQESH_AI_GRAY_ZONE_LOW    -> gray_zone_low    (default 0.35)
    MOQESH_AI_GRAY_ZONE_HIGH   -> gray_zone_high   (default 0.65)
    MOQESH_AI_CONFIRM_THRESHOLD-> confirm_threshold(default 0.70)
"""

from __future__ import annotations

import json
import logging
import math
import os
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AgentSession, RequestLog

log = logging.getLogger(__name__)

# Timeout de la llamada al LLM; si se agota caemos al heuristico.
_LLM_TIMEOUT_S = 30.0
# Cuantos requests incluir en el prompt para acotar el consumo de tokens.
_MAX_BEATS_IN_PROMPT = 30


def _as_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class AiConfirmationOptions:
    """Config del modulo de confirmacion. Valores seguros por defecto (heuristico)."""

    enabled: bool = False
    provider: str = "heuristic"  # "heuristic" | "openai"
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    gray_zone_low: float = 0.35  # solo se analizan sesiones en [low, high]
    gray_zone_high: float = 0.65
    confirm_threshold: float = 0.7  # confianza minima para fijar un veredicto

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> AiConfirmationOptions:
        """Construye las opciones desde variables de entorno (ver docstring del modulo)."""
        e = env if env is not None else os.environ
        o = cls()
        o.enabled = _as_bool(e.get("MOQESH_AI_ENABLED", ""))
        o.provider = e.get("MOQESH_AI_PROVIDER", o.provider)
        o.base_url = e.get("MOQESH_AI_BASE_URL", o.base_url)
        o.api_key = e.get("MOQESH_AI_API_KEY", o.api_key)
        o.model = e.get("MOQESH_AI_MODEL", o.model)
        o.gray_zone_low = float(e.get("MOQESH_AI_GRAY_ZONE_LOW", o.gray_zone_low))
        o.gray_zone_high = float(e.get("MOQESH_AI_GRAY_ZONE_HIGH", o.gray_zone_high))
        o.confirm_threshold = float(e.get("MOQESH_AI_CONFIRM_THRESHOLD", o.confirm_threshold))
        return o


@dataclass(slots=True)
class Verdict:
    """Juicio del clasificador sobre una sesion."""

    is_ai: bool
    confidence: float  # 0..1
    reasoning: str
    model_attribution: str | None = None  # None en heuristico; p.ej. "openai:<model>" con LLM


@runtime_checkable
class Classifier(Protocol):
    """Interfaz comun; permite intercambiar heuristico y LLM sin acoplar llamadas."""

    async def classify(self, features: dict) -> Verdict: ...


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


class HeuristicClassifier:
    """Clasificador sin LLM: explica el veredicto a partir de senales de timing,
    profundidad y patron. Funciona sin consumir tokens y sirve de fallback.

    `features` esperadas (todas opcionales, con defaults tolerantes):
        score (float), request_count (int), max_depth (int),
        matched_rules (list[str]), intervals (list[float] en segundos).
    """

    async def classify(self, features: dict) -> Verdict:
        reasons: list[str] = []
        conf = float(features.get("score", 0.0))  # ancla en el score de reglas

        intervals = [x for x in features.get("intervals", []) if x and x > 0]
        if len(intervals) >= 3:
            avg = sum(intervals) / len(intervals)
            std = math.sqrt(sum((x - avg) ** 2 for x in intervals) / len(intervals))
            if avg > 0 and std / avg < 0.35:
                conf += 0.15
                reasons.append(f"ritmo muy regular (cv={std / avg:.2f})")

        max_depth = int(features.get("max_depth", 0))
        if max_depth >= 6:
            conf += 0.15
            reasons.append(f"descenso a profundidad {max_depth}")

        request_count = int(features.get("request_count", 0))
        if request_count >= 20:
            conf += 0.1
            reasons.append(f"{request_count} requests sostenidos")

        matched = features.get("matched_rules", []) or []
        if "exhaustive_fanout" in matched:
            conf += 0.1
            reasons.append("fan-out exhaustivo")
        if "no_asset_render" in matched:
            reasons.append("sin render de assets")

        conf = _clamp01(conf)
        text = "; ".join(reasons) if reasons else "senales debiles"
        return Verdict(is_ai=conf >= 0.6, confidence=conf, reasoning=text)


class LlmClassifier:
    """Clasificador basado en LLM via API OpenAI-compatible.

    Envia un resumen compacto de la sesion y pide un veredicto JSON. Ante
    cualquier error (red, status != 2xx, JSON invalido) cae al heuristico.
    """

    def __init__(self, options: AiConfirmationOptions) -> None:
        self._opt = options
        self._fallback = HeuristicClassifier()

    async def classify(self, features: dict) -> Verdict:
        try:
            return await self._classify_llm(features)
        except Exception as exc:  # degradacion elegante: nunca propagamos
            log.warning("[ai_analyst] LLM no disponible (%s); uso heuristico", exc)
            return await self._fallback.classify(features)

    async def _classify_llm(self, features: dict) -> Verdict:
        url = self._opt.base_url.rstrip("/") + "/chat/completions"
        payload = {
            "model": self._opt.model,
            "temperature": 0,
            "max_tokens": 200,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Eres un analista de seguridad. Determinas si una sesion HTTP contra "
                        "un honeypot fue generada por un agente de IA/bot automatizado o por un "
                        "humano. Responde SOLO con JSON: "
                        '{"is_ai_agent":bool,"confidence":0..1,"reasoning":"breve"}.'
                    ),
                },
                {"role": "user", "content": self._build_prompt(features)},
            ],
        }
        headers = {
            "Authorization": f"Bearer {self._opt.api_key}",
            "HTTP-Referer": "https://github.com/moqesh-ai",
            "X-Title": "Moqesh AI",
        }
        async with httpx.AsyncClient(timeout=_LLM_TIMEOUT_S) as client:
            resp = await client.post(url, json=payload, headers=headers)

        if resp.status_code // 100 != 2:
            log.warning("[ai_analyst] LLM status %s; uso heuristico", resp.status_code)
            return await self._fallback.classify(features)

        content = resp.json()["choices"][0]["message"]["content"] or ""
        parsed = _extract_json(content)
        raw_ai = parsed.get("is_ai_agent", False)
        is_ai = raw_ai is True or (isinstance(raw_ai, str) and raw_ai.lower() == "true")
        conf = parsed.get("confidence", 0.5)
        conf = _clamp01(float(conf)) if isinstance(conf, (int, float, str)) else 0.5
        reasoning = str(parsed.get("reasoning", ""))
        return Verdict(is_ai, conf, reasoning, model_attribution=f"openai:{self._opt.model}")

    @staticmethod
    def _build_prompt(features: dict) -> str:
        lines = [
            f"UA: {features.get('user_agent') or '(ninguno)'}",
            "requests={rc} profundidad_max={md} score_reglas={sc:.2f} reglas={rules}".format(
                rc=features.get("request_count", 0),
                md=features.get("max_depth", 0),
                sc=float(features.get("score", 0.0)),
                rules=",".join(features.get("matched_rules", []) or []),
            ),
            f"tokens_estimados={features.get('tokens_estimated', 0)}",
            "paths (muestra):",
        ]
        paths = features.get("paths", []) or []
        intervals = features.get("intervals", []) or []
        for i, path in enumerate(paths[:_MAX_BEATS_IN_PROMPT]):
            # intervals[i] es el gap previo a paths[i]; el primero no tiene antecesor.
            iv = intervals[i - 1] if 0 < i <= len(intervals) else 0.0
            lines.append(f"  {path} | {iv:.1f}s")
        return "\n".join(lines)


def _extract_json(content: str) -> dict:
    """Extrae el primer objeto JSON del texto del LLM (tolera ```json ... ``` y prosa)."""
    i, j = content.find("{"), content.rfind("}")
    if i < 0 or j <= i:
        return {}
    try:
        return json.loads(content[i : j + 1])
    except (ValueError, TypeError):
        return {}


def build_classifier(options: AiConfirmationOptions) -> Classifier:
    """Fabrica el clasificador segun provider/enabled.

    Devuelve el heuristico salvo que el modulo este habilitado con provider
    "openai" y credenciales (base_url + api_key) presentes.
    """
    if options.enabled and options.provider.lower() == "openai" and options.base_url and options.api_key:
        return LlmClassifier(options)
    return HeuristicClassifier()


def _parse_rules(matched_rules: str | None) -> list[str]:
    if not matched_rules:
        return []
    return [r.strip() for r in matched_rules.split(",") if r.strip()]


def _build_features(db: Session, session: AgentSession) -> dict:
    """Arma el dict de features a partir de la sesion y sus request logs."""
    rows = db.execute(
        select(RequestLog.timestamp, RequestLog.path)
        .where(RequestLog.session_id == session.id)
        .order_by(RequestLog.timestamp)
    ).all()
    paths = [r.path for r in rows]
    intervals = [(rows[i].timestamp - rows[i - 1].timestamp).total_seconds() for i in range(1, len(rows))]
    return {
        "session_id": session.id,
        "source_ip": session.source_ip,
        "user_agent": session.user_agent,
        "score": session.ai_probability_score,
        "request_count": session.request_count,
        "max_depth": session.max_depth_reached,
        "tokens_estimated": session.tokens_estimated,
        "matched_rules": _parse_rules(session.matched_rules),
        "paths": paths,
        "intervals": intervals,
    }


async def confirm_session(
    db: Session,
    session: AgentSession,
    classifier: Classifier,
    options: AiConfirmationOptions,
) -> None:
    """Confirma una sesion en zona gris y escribe el veredicto en `session`.

    Si el score NO cae en [gray_zone_low, gray_zone_high] no hace nada (la sesion
    ya es suficientemente clara para el motor de reglas). En caso contrario pide
    un veredicto al clasificador y actualiza `verdict`, `verdict_confidence`,
    `verdict_reasoning` y `model_attribution`; luego hace commit via `db`.

    Veredicto (igual que el C#): solo se fija cuando la confianza alcanza el
    umbral; con baja confianza la sesion queda en "Unknown" para reintentar con
    mas datos.
    """
    score = session.ai_probability_score
    if not (options.gray_zone_low <= score <= options.gray_zone_high):
        return  # fuera de la zona gris: no se consume clasificador

    features = _build_features(db, session)
    verdict = await classifier.classify(features)

    session.verdict_confidence = verdict.confidence
    session.verdict_reasoning = verdict.reasoning
    if verdict.model_attribution:
        session.model_attribution = verdict.model_attribution

    if verdict.confidence >= options.confirm_threshold:
        session.verdict = "AiConfirmed" if verdict.is_ai else "HumanLikely"
    else:
        session.verdict = "Unknown"

    db.commit()
