"""Configuración central por entorno (pydantic-settings).

Fuente única de verdad: reemplaza el binding de appsettings.json del proyecto
original. Todas las variables se leen de entorno con prefijo `MOQESH_`
(p.ej. `MOQESH_SEED`, `MOQESH_AI_ENABLED`) o de un fichero `.env`.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MOQESH_", env_file=".env", extra="ignore")

    # --- Almacenamiento ---
    db_path: str = "moqesh.db"

    # Ruta al build del frontend (vacío = junto al paquete: ../web/dist).
    web_dist: str = ""

    # --- Puertos ---
    honeypot_port: int = 8080
    dashboard_port: int = 5000

    # URL pública del servidor Moqesh (a la que se conectan los sensores remotos).
    public_url: str = ""

    # --- Generación de contenido ---
    seed: str = ""  # vacío = se genera uno por deployment
    generation_mode: str = "Template"  # Template | Mimic | Static
    target_url: str | None = None  # solo Mimic
    # Perfil de sitio built-in seleccionable por despliegue (saas|corp|ecommerce|nonprofit...).
    # Da taxonomía de rutas, vocabulario y colecciones de API realistas sin crawlear nada.
    # Vacío = laberinto genérico por seed. En modo Mimic manda el crawl de target_url.
    site_profile: str = ""
    realism_level: int = 3  # 1..5
    vocabulary_theme: str = ""  # corporate|devops|saas|ecommerce ("" = por seed)
    brand_name: str = ""
    tarpit_delay_ms: int = 0
    server_banner: str = "nginx"
    token_exhaust_enabled: bool = True

    # --- World: contenido estático INERTE multi-sitio (fuente primaria; sustituye al laberinto) ---
    # El honeypot sirve ficheros reales de un árbol en disco (varios portales). Solo bytes, nunca
    # ejecuta nada. Con un World activo, el laberinto determinista queda OFF (era la fuente de los
    # delatores) salvo que no haya World. El agente "worldsmith" monta/expande este World.
    world_enabled: bool = True
    world_path: str = ""  # vacío = junto a la DB (<dir de la DB>/world)
    world_autoseed: bool = True  # si el World está vacío, copia la semilla curada empaquetada

    # --- Tarpit adaptativo (motor coherente -> cebo) ---
    # El laberinto es coherente y finito por defecto (indetectable). Solo cuando una sesión se
    # confirma como agente hostil (score alto) sube la "intensidad": prosa/logs más largos y, sobre
    # todo, un retardo creciente por respuesta que quema wall-clock y tokens del agente. Invisible
    # para tráfico humano/desconocido (intensidad 0 = sin retardo extra).
    adaptive_tarpit: bool = True
    tarpit_max_ms: int = 6000  # retardo máximo por respuesta a intensidad 3 (agente confirmado)
    # Opt-in de "quema bruta": a intensidad máxima la API vuelve a paginar sin fin. Rompe el
    # invariante de coherencia (vuelve a ser fingerprinteable), por eso está OFF por defecto.
    allow_infinite_on_confirmed: bool = False

    # Escenario CTF (corp-breach/git-leak): cadena de migajas con gates de credenciales reales.
    # Atrapa activamente a quien la siga (reuso de credencial -> bloqueo), PERO el patrón de la
    # cadena es reconocible por un modelo de IA escéptico. Off por defecto = máximo sigilo (solo
    # el laberinto realista); on = cebo activo. Decisión por despliegue.
    scenarios_enabled: bool = False

    # --- Detección / alertas ---
    alert_score_threshold: float = 0.5
    alert_min_requests: int = 5

    # --- Bloqueo / notificaciones ---
    webhook_url: str = ""
    webhook_secret: str = ""
    enforce_block: bool = True
    auto_block_score: float = 0.0  # 0 = auto-bloqueo por score desactivado
    enable_iptables: bool = False

    # --- Confirmación con IA (opcional) ---
    ai_enabled: bool = False
    ai_provider: str = "heuristic"  # heuristic | openai
    ai_base_url: str = ""
    ai_api_key: str = ""
    ai_model: str = ""
    ai_gray_zone_low: float = 0.35
    ai_gray_zone_high: float = 0.65
    ai_confirm_threshold: float = 0.7

    # --- Worldsmith (agente IA que CONSTRUYE/evoluciona el World + el cebo) ---
    # Produce SOLO ficheros estáticos inertes (validados mecánicamente) y un pack de cebo. No
    # corre por petición: se invoca bajo demanda (CLI `python -m moqesh.worldsmith` / dashboard).
    worldsmith_provider: str = "stub"  # stub (sin IA, determinista) | api (Anthropic) | claude_cli
    worldsmith_model: str = ""  # p.ej. claude-sonnet-4-5 (api) o alias del CLI
    worldsmith_api_key: str = ""  # provider=api; si vacío, cae a ai_api_key
    worldsmith_base_url: str = "https://api.anthropic.com"
    worldsmith_portals: int = 4
    worldsmith_brand: str = ""  # marca a usar; vacío = la deriva el agente desde el brief

    # --- Autenticación del dashboard (admin único) ---
    admin_user: str = "admin"
    admin_password: str = ""  # vacío = se genera una y se imprime en el log (una vez)
    session_secret: str = ""  # vacío = se genera y persiste junto a la DB (estable por despliegue)
    session_max_age: int = 86400  # vida de la sesión en segundos (1 día)
    cookie_secure: bool = False  # True tras TLS (subdominio admin); False en local/túnel http

    # --- CORS (dev del frontend) ---
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]


settings = Settings()
