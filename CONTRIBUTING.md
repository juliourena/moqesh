# Contribuir a Moqesh AI

Gracias por tu interés. Esta guía cubre el entorno de desarrollo, las pruebas y
las convenciones del proyecto.

## Requisitos

- Python 3.12+ y [uv](https://docs.astral.sh/uv/)
- Node 20+ (para el dashboard React)

## Puesta en marcha

```bash
# Backend
uv venv .venv
uv pip install --python .venv -e . pytest ruff
.venv/bin/moqesh                 # honeypot :8080 + dashboard/API :5000

# Frontend (hot reload, proxy a :5000)
cd web && npm install && npm run dev
```

Configuración por entorno (prefijo `MOQESH_`): ver [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md)
y [`.env.example`](.env.example).

## Pruebas y lint

```bash
.venv/bin/python -m pytest -q      # suite completa
.venv/bin/ruff check moqesh tests  # lint
.venv/bin/ruff format moqesh tests # formato
cd web && npm run build            # type-check + build del SPA
```

El CI (`.github/workflows/ci.yml`) corre exactamente esto en cada push/PR.

## Binarios del agente

El agente remoto se distribuye como binario autocontenido (PyInstaller). La receta
por plataforma está en [`moqesh/agent/BUILD.md`](moqesh/agent/BUILD.md); el workflow
`release.yml` los compila (linux amd64/arm64 + windows) al publicar un tag `vX.Y.Z`.

## Estructura

Ver el árbol en el [README](README.md#arquitectura). En corto: `moqesh/` es el
backend (motor + API + ingestión de sensores), `web/` el dashboard, `docs/` las guías.

- El **motor** (`labyrinth`, `scenarios`, `detection`, `rng`) es puro y determinista.
- La **detección es central**: `pipeline.py` la comparten el honeypot local y la
  ingestión remota — añade reglas ahí, no en dos sitios.
- El **contrato del frontend** sale de `schemas.py` (Pydantic, camelCase); no armes
  JSON a mano en los routers.

## Convenciones

- Código y comentarios en español (coherente con el repo); `ruff` debe pasar limpio.
- SQLAlchemy **síncrono** (threadpool de FastAPI); `httpx` **async** solo para HTTP saliente.
- Añade pruebas para lógica nueva; los tests aíslan la DB vía `tests/conftest.py`.
- Convención de commits: una línea de resumen + cuerpo explicando el porqué.

## Seguridad

¿Encontraste una vulnerabilidad? No abras un issue público: ver [`SECURITY.md`](SECURITY.md).
