# Configuración

Toda la configuración se lee del entorno con prefijo `MOQESH_` (o de un fichero
`.env` en el directorio de trabajo). Plantilla: [`.env.example`](../.env.example).

## Almacenamiento

| Variable | Default | Descripción |
|----------|---------|-------------|
| `MOQESH_DB_PATH` | `moqesh.db` | Ruta del SQLite. En Docker: `/app/data/moqesh.db`. |
| `MOQESH_WEB_DIST` | *(auto)* | Ruta al build del frontend. Auto si está junto al paquete (`web/dist`). |

## Red

| Variable | Default | Descripción |
|----------|---------|-------------|
| `MOQESH_HONEYPOT_PORT` | `8080` | Puerto del honeypot (el laberinto servido a los agentes). |
| `MOQESH_DASHBOARD_PORT` | `5000` | Puerto del dashboard + API + WebSocket + ingestión. |
| `MOQESH_PUBLIC_URL` | *(vacío)* | URL pública del servidor a la que se conectan los sensores remotos. Imprescindible para el onboarding de sensores. |

## Generación de contenido

| Variable | Default | Descripción |
|----------|---------|-------------|
| `MOQESH_SEED` | *(auto)* | Semilla del deployment. Vacío = se genera una (anti-fingerprint). |
| `MOQESH_GENERATION_MODE` | `Template` | `Template` \| `Mimic` \| `Static`. |
| `MOQESH_TARGET_URL` | *(vacío)* | Sitio real a imitar (solo `Mimic`). |
| `MOQESH_SITE_PROFILE` | *(vacío)* | Perfil built-in (`saas`\|`corp`\|`ecommerce`\|`nonprofit`): rutas, vocabulario y colecciones de API realistas sin crawlear. Vacío = genérico por seed. En `Mimic` manda el crawl de `TARGET_URL`. Genera más con `scripts/build_profile.py`. |
| `MOQESH_REALISM_LEVEL` | `3` | 1 (poco cebo) .. 5 (cebo denso). |
| `MOQESH_VOCABULARY_THEME` | *(auto)* | `corporate` \| `devops` \| `saas` \| `ecommerce`. Vacío = por seed. |
| `MOQESH_BRAND_NAME` | *(auto)* | Marca ficticia. Vacío = derivada del seed. |
| `MOQESH_TARPIT_DELAY_MS` | `0` | Retardo fijo base por respuesta (ms). Se suma al tarpit adaptativo. |
| `MOQESH_ADAPTIVE_TARPIT` | `true` | Retardo que crece con la intensidad de la sesión (coherente→cebo). 0 a intensidad 0 (humano/desconocido); sube solo con agente confirmado. |
| `MOQESH_TARPIT_MAX_MS` | `6000` | Retardo máximo por respuesta a intensidad 3 (agente confirmado). |
| `MOQESH_ALLOW_INFINITE_ON_CONFIRMED` | `false` | Opt-in de quema bruta: a intensidad máxima la API vuelve a paginar sin fin. Rompe el invariante de coherencia (vuelve a ser fingerprinteable), por eso OFF por defecto. |
| `MOQESH_SERVER_BANNER` | `nginx` | Banner `Server`. `nginx` = se deriva del seed. |
| `MOQESH_TOKEN_EXHAUST_ENABLED` | `true` | Activa el laberinto Token Exhaust (finito y coherente; **legacy**: OFF de facto cuando hay World activo). |
| `MOQESH_WORLD_ENABLED` | `true` | Sirve el **World**: contenido estático INERTE multi-sitio (ficheros reales en disco; solo bytes, nunca ejecuta). Fuente primaria; sustituye al laberinto generado. |
| `MOQESH_WORLD_PATH` | *(auto)* | Ruta del World. Vacío = `<dir de la DB>/world` (volumen persistente). |
| `MOQESH_WORLD_AUTOSEED` | `true` | Si el World está vacío, copia la semilla curada de portales empaquetada. |
| `MOQESH_SCENARIOS_ENABLED` | `false` | Sirve el escenario activo (gate de reuso de credencial, se resuelve ANTES del World). `false` = sin cebo activo (solo el World/laberinto). `true` = cebo activo. Packs builtin: `realistic-ops` (recomendado con World: **un** `.env.bak` filtrado → consola ops oculta con mock data, sin pinta de CTF), `corp-breach`/`git-leak` (cadenas tipo CTF). Actívalo con `POST /api/scenarios/builtins/realistic-ops?activate=true`. |

### World: manifest y contenido voluminoso (genbig)

El `manifest.json` del World monta portales: `{"mounts": [{"prefix", "dir", "spa", "autoindex"}]}`.
- **`autoindex: true`** → un directorio **sin `index.html`** sirve un **listado estilo servidor**
  (señuelo de "directorio abierto") en vez de 404. Por defecto `false` (un dir sin index = 404).
- Los ficheros estáticos **> 1 MiB se sirven en streaming** (Content-Length/Range reales, sin
  leerlos en memoria): puedes servir árboles pesados sin agotar la RAM del honeypot.

Para rellenar un árbol voluminoso de **texto REAL** (quema de tokens finita, sin el delator del
contenido generado/templado) usa [`scripts/genbig.py`](../scripts/genbig.py):

```bash
# /data con 50 ficheros de 10 MiB (texto de dominio público, cacheado en ~/.cache/genbig)
python3 scripts/genbig.py <world>/sites/data --files 50 --size 10M --lang es
# subdirs numéricos: /files/2023 /files/2024 /files/2025
python3 scripts/genbig.py <world>/sites/files --files 60 --size 10M \
    --subdirs 3 --subdir-prefix "" --subdir-width 4 --subdir-start 2023
```

Luego añade el mount con `autoindex` al `manifest.json` del World y reinicia el honeypot:

```json
{ "prefix": "/data", "dir": "sites/data", "autoindex": true }
```

La salida de genbig NO se commitea: vive en el volumen del World (`<dir de la DB>/world`).

## Detección y alertas

| Variable | Default | Descripción |
|----------|---------|-------------|
| `MOQESH_ALERT_SCORE_THRESHOLD` | `0.5` | Score mínimo para alertar. |
| `MOQESH_ALERT_MIN_REQUESTS` | `5` | Requests mínimos en la sesión para alertar. |

## Bloqueo y notificaciones

| Variable | Default | Descripción |
|----------|---------|-------------|
| `MOQESH_ENFORCE_BLOCK` | `true` | El honeypot responde 403 a IPs bloqueadas. |
| `MOQESH_AUTO_BLOCK_SCORE` | `0.0` | Auto-bloqueo por score (0 = desactivado; `credential_reuse` siempre bloquea). |
| `MOQESH_WEBHOOK_URL` | *(vacío)* | Webhook de notificación (firmado HMAC `X-Moqesh-Signature`). |
| `MOQESH_WEBHOOK_SECRET` | *(vacío)* | Secreto para firmar el webhook. |
| `MOQESH_ENABLE_IPTABLES` | `false` | Bloqueo OS-level opcional (OFF por defecto). |

## Autenticación del dashboard (admin único)

El dashboard/API (`/api/*`) queda detrás de una sesión por cookie firmada. El canal de
sensores (`/ingest/*`, `/control`, `/s/*`, `/download/*`, `/healthz`) NO se ve afectado:
conserva su autenticación HMAC propia.

| Variable | Default | Descripción |
|----------|---------|-------------|
| `MOQESH_ADMIN_USER` | `admin` | Usuario admin creado en el primer arranque. |
| `MOQESH_ADMIN_PASSWORD` | *(vacío)* | Contraseña del admin. Vacío = se genera una y se imprime en el log **una vez**. |
| `MOQESH_SESSION_SECRET` | *(vacío)* | Secreto de firma de la cookie. Vacío = se genera y persiste junto a la DB (estable por despliegue). |
| `MOQESH_SESSION_MAX_AGE` | `86400` | Vida de la sesión en segundos. |
| `MOQESH_COOKIE_SECURE` | `false` | `true` tras TLS (subdominio admin); `false` en local/túnel http. |

Exposición: el dashboard se publica en un subdominio TLS propio (p.ej.
`moqesh-admin.…`) tras el Caddy compartido — ver [`deploy/caddy-admin.snippet`](../deploy/caddy-admin.snippet) —
y además sigue accesible por túnel SSH. Superficie separada del honeypot público.

## Confirmación con IA (opcional)

El sistema funciona sin este módulo (modo heurístico).

| Variable | Default | Descripción |
|----------|---------|-------------|
| `MOQESH_AI_ENABLED` | `false` | Activa la confirmación en zona gris. |
| `MOQESH_AI_PROVIDER` | `heuristic` | `heuristic` \| `openai` (endpoint OpenAI-compatible). |
| `MOQESH_AI_BASE_URL` | *(vacío)* | Ej. `https://openrouter.ai/api/v1`. |
| `MOQESH_AI_API_KEY` | *(vacío)* | Clave del proveedor. |
| `MOQESH_AI_MODEL` | *(vacío)* | Ej. `anthropic/claude-haiku-5.5`. |
| `MOQESH_AI_GRAY_ZONE_LOW` / `_HIGH` | `0.35` / `0.65` | Rango de score que dispara la confirmación. |
| `MOQESH_AI_CONFIRM_THRESHOLD` | `0.7` | Confianza mínima para fijar veredicto. |

## Worldsmith (constructor IA del World)

Agente de IA que construye/evoluciona el contenido inerte del World + el cebo. Se invoca bajo
demanda (`python -m moqesh.worldsmith build|evolve`), no por petición. Guía:
[`docs/WORLDSMITH.md`](WORLDSMITH.md).

| Variable | Default | Descripción |
|----------|---------|-------------|
| `MOQESH_WORLDSMITH_PROVIDER` | `stub` | `stub` (determinista, sin IA) \| `api` (Anthropic tool-use) \| `claude_cli` (CLI por suscripción). |
| `MOQESH_WORLDSMITH_MODEL` | *(vacío)* | Modelo del proveedor (p.ej. `claude-sonnet-4-5` para `api`; alias del CLI). |
| `MOQESH_WORLDSMITH_API_KEY` | *(vacío)* | Clave para `provider=api`. Si vacío, cae a `MOQESH_AI_API_KEY`. |
| `MOQESH_WORLDSMITH_BASE_URL` | `https://api.anthropic.com` | Endpoint de la Messages API (`api`). |
| `MOQESH_WORLDSMITH_PORTALS` | `4` | Nº aproximado de portales a generar. |
| `MOQESH_WORLDSMITH_BRAND` | *(vacío)* | Marca/identidad del sitio. Vacío = la deriva el agente desde el brief. |

Para `claude_cli`, la autenticación sale del CLI o de `CLAUDE_CODE_OAUTH_TOKEN` (de
`claude setup-token`), heredado por el subproceso. El proveedor va acotado a `Read,Write,Edit`
sin bash ni red.

## Sensores remotos (en el servidor del cliente)

Estas variables las consume el **agente** o el **shipper agentless**, no el servidor central:
`MOQESH_SERVER`, `MOQESH_KEY_ID`, `MOQESH_SECRET`, y (agente) `MOQESH_AGENT_PORT`,
`MOQESH_CONTROL_INTERVAL`, `MOQESH_BEACON_JITTER`; (shipper) `MOQESH_LOG`, `MOQESH_BASE_PATH`,
`MOQESH_FORMAT`, `MOQESH_STATE`, `MOQESH_DRY_RUN`. Detalle en
[`moqesh/agent/BUILD.md`](../moqesh/agent/BUILD.md) y [`moqesh/clients/README.md`](../moqesh/clients/README.md).
