# Empaquetado del agente remoto de Moqesh

El agente (`moqesh.agent`) se distribuye como **binario autocontenido** (PyInstaller
`--onefile`) para que un cliente lo ejecute sin instalar Python ni dependencias. No
necesita la DB, FastAPI ni pydantic-settings: sólo stdlib + `httpx` + los módulos puros
`moqesh.labyrinth`, `moqesh.scenarios` y `moqesh.security`.

## Entrada / ejecución

```bash
python -m moqesh.agent        # desde el repo (desarrollo)
./moqesh-agent-linux-amd64    # binario empaquetado
```

Variables de entorno:

| Variable                  | Default | Descripción                                              |
|---------------------------|---------|----------------------------------------------------------|
| `MOQESH_SERVER`           | —       | URL del servidor central (obligatoria)                   |
| `MOQESH_KEY_ID`           | —       | Key id del sensor (obligatoria)                          |
| `MOQESH_SECRET`           | —       | Secreto HMAC del sensor (obligatoria)                    |
| `MOQESH_AGENT_PORT`       | `8080`  | Puerto del honeypot local                                |
| `MOQESH_CONTROL_INTERVAL` | `30`    | Segundos entre beacons de control / envío de eventos     |
| `MOQESH_BEACON_JITTER`    | `0.3`   | Jitter simétrico (±fracción) sobre el intervalo          |

## Dependencia de build

```bash
.venv/bin/pip install pyinstaller
```

> Nota: `moqesh.scenarios` importa SQLAlchemy a nivel de módulo (comparte dataclasses con
> el ORM del servidor). PyInstaller lo detecta y lo incluye; el agente **no** lo usa en
> runtime. Para adelgazar el binario se puede excluir lo que no se toca (ver `--exclude-module`).

## Construcción por plataforma

PyInstaller **no hace cross-compile**: hay que construir en (o emulando) cada SO/arch.
El nombre de salida debe ser `moqesh-agent-<os>-<arch>` y copiarse a
`moqesh/agent/dist/` — de ahí el servidor los sirve en `GET /download/agent/{os-arch}`
(ver `moqesh/api/__init__.py::download_agent`).

Opciones comunes (incluir el template DLL del forge y recortar peso):

```
COMMON="--onefile --name moqesh-agent \
  --add-data moqesh/assets/portal_template.dll:moqesh/assets \
  --hidden-import httpx \
  --exclude-module fastapi --exclude-module uvicorn \
  --exclude-module pydantic --exclude-module pydantic_settings \
  moqesh/agent/__main__.py"
```

(En Windows, el separador de `--add-data` es `;` en lugar de `:`. Si el template DLL no
existe, el forge degrada a un PE señuelo y el build sigue funcionando — omite el `--add-data`.)

### linux/amd64

```bash
# En una máquina/container linux x86_64:
pyinstaller $COMMON
mv dist/moqesh-agent moqesh/agent/dist/moqesh-agent-linux-amd64
```

### linux/arm64

```bash
# En una máquina/container linux aarch64 (o QEMU: docker run --platform linux/arm64 ...):
pyinstaller $COMMON
mv dist/moqesh-agent moqesh/agent/dist/moqesh-agent-linux-arm64
```

Ejemplo con Docker + buildx para arm64:

```bash
docker run --rm --platform linux/arm64 -v "$PWD":/src -w /src python:3.11-slim bash -c "
  pip install -e . pyinstaller &&
  pyinstaller $COMMON &&
  cp dist/moqesh-agent /src/moqesh/agent/dist/moqesh-agent-linux-arm64"
```

### windows/amd64

```powershell
# En Windows x64 (PowerShell). Nota el `;` en --add-data:
pyinstaller --onefile --name moqesh-agent `
  --add-data "moqesh/assets/portal_template.dll;moqesh/assets" `
  --hidden-import httpx `
  --exclude-module fastapi --exclude-module uvicorn `
  --exclude-module pydantic --exclude-module pydantic_settings `
  moqesh/agent/__main__.py
move dist\moqesh-agent.exe moqesh\agent\dist\moqesh-agent-windows-amd64
```

## Salida esperada

```
moqesh/agent/dist/
  moqesh-agent-linux-amd64
  moqesh-agent-linux-arm64
  moqesh-agent-windows-amd64     # (el .exe se renombra sin extensión)
```

El servidor mapea `GET /download/agent/{os-arch}` → `moqesh/agent/dist/moqesh-agent-<os-arch>`
y lo entrega con `filename="moqesh-agent"`. Si el binario no está, responde 404
("build pendiente"), por lo que estos artefactos deben generarse y commitearse (o subirse
al artifact store del CI) antes de publicar descargas.

## Verificación rápida

```bash
MOQESH_SERVER=http://localhost:5000 MOQESH_KEY_ID=mq_x MOQESH_SECRET=s \
  ./moqesh-agent-linux-amd64   # debe hacer preflight a /healthz y abrir el puerto 8080
```
