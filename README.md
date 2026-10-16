# Moqesh AI

<!-- Ajusta `juliourena/moqesh` al slug real del repo en GitHub (badge + GHCR, más abajo). -->
![CI](https://github.com/juliourena/moqesh/actions/workflows/ci.yml/badge.svg)

Honeypot open-source contra **agentes de IA autónomos** que escanean tu
infraestructura. Moqesh sirve un **laberinto Token Exhaust** —un maze infinito y
coherente de contenido creíble— que atrapa a los agentes automatizados, **agota
los tokens de su LLM**, perfila su comportamiento y permite detectarlos y
bloquearlos. Proyecto nativo en **Python** (FastAPI + SQLAlchemy).

**Documentación:** [configuración](docs/CONFIGURATION.md) · [worldsmith (constructor IA)](docs/WORLDSMITH.md)
· [sensores remotos](docs/SENSORS.md) · [contribuir](CONTRIBUTING.md) · [seguridad](SECURITY.md)

## Cómo funciona

1. **Cebo (Lure)** — sirve un portal interno falso: listados de directorios,
   `.env`, configs, READMEs, APIs y binarios señuelo.
2. **Trampa (Trap)** — cada página enlaza más hondo: los listados nunca terminan,
   las APIs paginan sin fin, los READMEs apuntan a archivos "jugosos" y los
   bundles JS esconden endpoints. Un agente que *sigue todo* navega indefinidamente.
3. **Detección (Detect)** — cada request se puntúa con un motor de **reglas
   conductuales** (regularidad temporal, descenso en profundidad, fan-out
   exhaustivo, seguimiento de breadcrumbs/README, deobfuscación de JS, UAs de
   crawlers de IA…). Al cruzar el umbral se levanta una alerta.
4. **Confirmación (opcional)** — un módulo LLM revisa sesiones en zona gris y
   confirma si el visitante es un agente. El sistema funciona **sin** este módulo.
5. **Bloqueo (Block)** — el reuso de una credencial plantada (honeytoken) o un
   score sobre umbral bloquea la IP de forma activa (403) y puede notificar por webhook.

Todo el contenido es **determinista por `(seed, path)`**: la misma URL devuelve
siempre la misma página dentro de un deployment (no hay ruido aleatorio delator),
pero dos deployments con seeds distintos no comparten firma estática (anti-fingerprint).

## Modos de generación

- **Template** — vocabulario genérico mutado por seed (zero-config, sirve contra cualquier objetivo).
- **Mimic** — perfila un sitio real (`TargetUrl`, crawl read-only) y genera contenido que se mimetiza con él.
- **Static** — desactiva el laberinto procedural.

## Escenarios CTF

Sobre el laberinto se puede activar un **escenario** autorable: una cadena de
ataque con rutas ocultas, gates de credenciales reales, binarios decompilables y
vaults. Incluye dos packs: `corp-breach` (DLL → vault → reuso de credencial →
flag) y `git-leak` (fuga de `.git` → token → secretos de CI). Editables e
importables/exportables como JSON desde el dashboard.

## World y Worldsmith (contenido inerte + IA)

La fuente primaria de contenido es el **World**: un árbol de ficheros reales e **inertes**
(varios portales bajo distintos prefijos, con mock data) que el honeypot sirve **solo como
bytes — nunca ejecuta nada**. Sustituye al laberinto generado (que queda como *legacy*,
OFF cuando hay World) y elimina los artefactos estructurales que delataban al honeypot.

Para **quema de tokens a gran escala sin el delator del contenido generado**, un directorio del
World puede marcarse `"autoindex": true` (sirve un listado de "directorio abierto") y rellenarse
con árboles voluminosos de **texto real** mediante [`scripts/genbig.py`](scripts/genbig.py);
los ficheros grandes se sirven en streaming. Detalle en [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md).

El **worldsmith** es un agente de IA que **construye y evoluciona** ese World + un **cebo**
colocado en la ruta de caza del atacante (un `.env` filtrado con un único honeytoken → una
consola ops protegida; reusar el token dispara `credential_reuse` y bloquea). La inertness se
**impone mecánicamente** (validación por escritura + re-validación del árbol antes de publicar),
no se confía al prompt. Proveedores: `stub` (sin IA), `api` (Anthropic tool-use) y `claude_cli`
(suscripción). Uso:

```bash
python -m moqesh.worldsmith build --provider claude_cli --brand "Harborline" --profile saas
```

Guía completa: [`docs/WORLDSMITH.md`](docs/WORLDSMITH.md).

## Quick start

### Docker

```bash
docker compose up --build
```

Dashboard: http://localhost:5000 · Honeypot: http://localhost:8080

### Desarrollo

```bash
# Backend (honeypot + dashboard/API en un proceso)
uv venv .venv && uv pip install --python .venv -e .
.venv/bin/moqesh            # o: .venv/bin/python -m moqesh.main

# Frontend (hot reload, proxy a :5000)
cd web && npm install && npm run dev
```

Configuración por entorno (prefijo `MOQESH_`): ver [`.env.example`](.env.example).

## Sensores (despliegue remoto)

Moqesh puede proteger servidores donde **no** vive, mediante *sensores*:

- **Agente** — binario autocontenido que corre el motor completo en el servidor
  remoto (laberinto infinito, gates de credenciales/CTF) y envía telemetría firmada.
- **Agentless** — ZIP estáticos (aleatorios, sin patrón) que descomprimes donde
  quieras + una tarea programada que envía los logs; sin instalar software.

Alta en un comando desde el dashboard (con verificación de conexión en vivo),
control y rotación de clave en caliente, auth HMAC firmada en ambos sentidos.
Guía completa: [`docs/SENSORS.md`](docs/SENSORS.md).

## Arquitectura

```
moqesh/
  rng.py          RNG determinista por (seed,path) — primitivo anti-fingerprint
  vocabulary.py   pools de vocabulario por tema
  labyrinth.py    generador Token Exhaust (legacy: OFF cuando hay World activo)
  world.py        World inerte: sirve SOLO bytes de ficheros reales multi-portal (fuente primaria)
  worlds/         semilla curada de portales inertes + manifest
  worldsmith/     agente IA que construye/evoluciona el World + el cebo (inertness validada)
  detection.py    motor de scoring conductual (10 reglas + señales de escenario)
  scenarios.py    motor CTF + packs incorporados (import/export)
  forge.py        binarios señuelo (plantilla DLL parcheada; fallback PE)
  mimic.py        perfilador de sitios reales (modo Mimic)
  ai_analyst.py   confirmación opcional (heurística o LLM OpenAI-compatible)
  blocks.py       bloqueo activo de IPs + webhooks
  models.py       modelos SQLAlchemy (SQLite)
  schemas.py      contrato Pydantic (camelCase) para el frontend
  realtime.py     WebSocket nativo (tiempo real al dashboard)
  pipeline.py     scoring central (comparten honeypot local e ingestión remota)
  security.py     HMAC bidireccional, anti-replay, rate-limit, dedup
  provisioning.py scripts/instrucciones de instalación (onboarding de 1 comando)
  logparse.py     parser de logs agentless (nginx/apache/caddy/json)
  bundles.py      generador de ZIP estáticos aleatorios (modo agentless)
  honeypot.py     servidor trampa local (:8080) — sensor `local`
  agent/          agente remoto autocontenido (binario PyInstaller)
  clients/        script de envío agentless (sh + PowerShell)
  api/            dashboard + API REST + ingestión/control de sensores (:5000)
web/              dashboard React + TypeScript (Vite, Tailwind)
```

**Decisiones**: SQLAlchemy síncrono (threadpool de FastAPI) para SQLite; `httpx`
async solo para HTTP saliente (mimic, LLM, webhooks); tiempo real con WebSocket
nativo. El forge usa una plantilla DLL generada offline (ver
[`tools/build_template_dll.md`](tools/build_template_dll.md)); sin ella degrada a
un binario con credenciales embebidas.

## Tests y CI

```bash
.venv/bin/python -m pytest -q         # determinismo, escenarios, sensores e integración
.venv/bin/ruff check moqesh tests     # lint
```

El CI (`.github/workflows/ci.yml`) corre lint + tests + build del SPA en cada push/PR.

## Builds y releases

Al publicar un tag `vX.Y.Z`, `.github/workflows/release.yml`:

- Compila los **binarios del agente** (PyInstaller) para `linux/amd64`, `linux/arm64` y
  `windows/amd64` y los adjunta al **GitHub Release**. El servidor los sirve en
  `GET /download/agent/{os-arch}`. Receta de build: [`moqesh/agent/BUILD.md`](moqesh/agent/BUILD.md).
- Publica la **imagen Docker multi-arch** (amd64/arm64) en **GHCR**
  (`ghcr.io/juliourena/moqesh:<tag>` y `:latest`), con los binarios linux del agente embebidos.

```bash
# Ejecutar la imagen publicada:
docker run -p 5000:5000 -p 8080:8080 -v moqesh-data:/app/data ghcr.io/juliourena/moqesh:latest
```

Contribuir: ver [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Licencia

**AGPL-3.0-or-later** — ver [`LICENSE`](LICENSE) y [`NOTICE`](NOTICE). © 2026 Julio Ureña.

Copyleft fuerte con cláusula de red: puedes usar, modificar y ofrecer Moqesh (incluso
comercialmente), pero si distribuyes una versión modificada **o la ofreces como servicio en
red**, debes publicar su código fuente bajo AGPL-3.0 y conservar la atribución. Para uso
propietario/cerrado sin esas obligaciones, contacta para una licencia comercial (doble licencia).
