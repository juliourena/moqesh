# Worldsmith — constructor IA del World

El **worldsmith** es un agente de IA que **construye y evoluciona el contenido del
[World](#qué-es-el-world)**: un sitio realista de varios portales estáticos e inertes +
un **cebo** colocado en la ruta de caza del atacante. Se invoca **bajo demanda** (no por
petición): provisiona o refresca el contenido y para.

> No confundir con `moqesh/agent/`, que es el **sensor remoto** (edge). El worldsmith
> (`moqesh/worldsmith/`) **produce ficheros**; el sensor reporta hits.

## Principio de seguridad (no negociable)

Moqesh **solo sirve bytes estáticos y nunca ejecuta** el contenido de los portales. El
worldsmith, por tanto, produce **exclusivamente ficheros estáticos inertes** (HTML/CSS/JS/
JSON/SVG/…), y eso se **impone mecánicamente**, no se confía al prompt:

1. **Validación por escritura** (`validate.py`) — cada fichero pasa por: ruta segura (sin
   traversal/absolutas, allowlist de extensiones), **sin código de servidor** (`<?php`,
   `<% %>`, `{% %}`, shebangs), **sin cargas/callbacks externos** (todo *same-origin*: los
   “logins” postean al gate de Moqesh, no a un backend o dominio externo), y límites de tamaño.
2. **Gate final** — antes de publicar, se **re-valida el árbol completo** en disco. Si algo
   falla, **no se publica nada** y el World en vivo queda intacto.
3. **Publicación atómica** — el build se arma en un *staging* y se intercambia de golpe.

El contenido sí puede incluir secretos/credenciales **fabricados** (son el cebo); la
invariante de “una sola credencial viva” la impone `plant_bait`, no el validador de inertness.

## Qué es el World

Un árbol de ficheros reales + `manifest.json` que monta uno o varios **portales** bajo
distintos prefijos de URL (como un servidor que aloja varias webs):

```
world/
  manifest.json                 # {"mounts":[{"prefix":"/docs","dir":"sites/docs","spa":false}, ...]}
  sites/console/index.html      # portales: estáticos + mock data (api/*.json)
  sites/docs/index.html
  sites/status/summary.json
```

Los endpoints de salud/estado pueden usar tokens dinámicos que **rellena Moqesh al servir**
(para no quedar “congelados”): `{{moqesh.now_iso}}`, `{{moqesh.uptime_seconds}}`,
`{{moqesh.minutes_ago}}`. Ver [`MOQESH_WORLD_*`](CONFIGURATION.md#generación-de-contenido).

## Doctrina de ruta de caza (el cebo)

Un agente de pentest **con objetivo** (estilo Strix/PentAGI) enumera buscando siempre lo mismo:
un **backup de entorno con credenciales** (`/.env`, `/.env.bak`, `/env.bak`, `/api/env.bak`…),
una **consola admin/ops** (`/ops`, `/admin`, `/internal/ops`…) y un **login** donde postear
(`/api/login`, `/auth/login`…). El worldsmith planta el cebo **justo ahí** con `plant_bait`:

- **una sola credencial viva** (un honeytoken);
- el backup (leak) se filtra en esas rutas e incluye el placeholder `{{cred:KEY}}` y la URL del gate;
- la consola (gate) exige ese token (401 Bearer sin él; 200 con él);
- `robots.txt` revela las rutas como señuelo.

Cuando el atacante reusa el token contra el gate, Moqesh dispara **`credential_reuse`** y lo
**bloquea**. El cebo se importa como escenario activo (ver [escenarios](CONFIGURATION.md)).

## Proveedores

Configurable con `MOQESH_WORLDSMITH_PROVIDER` (o `--provider`):

| Proveedor | IA | Notas |
|-----------|----|-------|
| `stub` | no | Determinista, sin coste. Construye un World válido + cebo. Ideal para tests y como build por defecto sin IA. |
| `api` | Anthropic Messages API | Bucle *tool-use* con **nuestras herramientas** (`write_file`, `set_manifest`, `plant_bait`…). **No tiene shell**: el modelo solo puede llamar a esas herramientas sandboxeadas → no puede pivotar. Requiere `MOQESH_WORLDSMITH_API_KEY`. |
| `claude_cli` | CLI `claude` (suscripción) | Subproceso `claude -p` acotado (`Read,Write,Edit`, sin bash/red, `--add-dir` al staging). Construye por ficheros + un `_worldsmith_bait.json` que ingerimos por `plant_bait`. Requiere auth del CLI o `CLAUDE_CODE_OAUTH_TOKEN`. |

Las herramientas del proveedor `api` **nunca lanzan**: devuelven `{"ok": false, "reasons": [...]}`
para que el agente se **autocorrija**. Toda escritura se valida; el sandbox tiene topes de nº de
ficheros y bytes.

## Uso (CLI)

```bash
# Build nuevo (proveedor por config, o --provider)
python -m moqesh.worldsmith build --brand "Harborline" --profile saas

# Evolucionar el World actual (rota el cebo, refresca mock data, añade/varía un portal)
python -m moqesh.worldsmith evolve

# Opciones: --provider stub|api|claude_cli  --model  --brand  --profile
#           --goal  --portals N  --world-path PATH  --no-import-bait  --json
```

El build publica el World (si pasa la validación) e **importa el pack de cebo** como escenario
activo. **Reinicia/recarga el proceso del honeypot** para que sirva el World nuevo (el World se
carga al arrancar).

### Proveedor `api` (Anthropic)

```bash
export MOQESH_WORLDSMITH_PROVIDER=api
export MOQESH_WORLDSMITH_API_KEY=sk-ant-...
export MOQESH_WORLDSMITH_MODEL=claude-sonnet-4-5   # opcional
python -m moqesh.worldsmith build --brand "Harborline"
```

### Proveedor `claude_cli` (suscripción)

Genera un token de larga vida con tu suscripción y pásalo por entorno:

```bash
claude setup-token            # flujo interactivo (navegador); imprime un sk-ant-oat...
export CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat...
python -m moqesh.worldsmith build --provider claude_cli --brand "Harborline" --profile saas
```

El CLI escribe los ficheros del World + `manifest.json` + un `_worldsmith_bait.json` (artefacto
de build con la spec del cebo; **no** se publica: se ingiere por `plant_bait` y se borra).

> **Aislamiento (importante).** Ejecuta cualquier build de IA en un entorno **limpio** (sin claves
> SSH ni `.env` reales en el `$HOME`/cwd accesible). El proveedor `api` no tiene shell; el
> `claude_cli` va acotado a `Read,Write,Edit` sin bash/red, pero el aislamiento del entorno es la
> defensa principal.

## Verificación (lo que comprueba un build correcto)

- El árbol publicado pasa `validate_tree` (inertness limpia) y sirve bytes reales en cada portal;
  lo no presente → **404 real**.
- El cebo es funcional end-to-end: `GET /ops` sin token → **401**; `GET /.env` filtra el token →
  `GET /ops` con `Authorization: Bearer <token>` → **200** + `credential_reuse`.
- Cero referencias externas; endpoints de salud/estado con `{{moqesh.*}}`.

## Despliegue (VPS)

1. Corre el build en el servidor (o súbelo) apuntando `MOQESH_WORLD_PATH` al volumen persistente.
2. Reinicia el contenedor del honeypot para recargar el World.
3. El pack de cebo ya quedó importado y activo en la DB.

## Ficheros

```
moqesh/worldsmith/
  validate.py   red de seguridad de inertness (ruta + contenido + manifest + árbol)
  tools.py      BuildSandbox: herramientas bulletproof (write_file/set_manifest/plant_bait…)
  providers.py  stub | api (tool-use Anthropic) | claude_cli + dispatch seguro
  prompt.py     ingeniería de prompt (sistema + brief) con la doctrina de ruta de caza
  builder.py    orquesta, re-valida el árbol y publica atómicamente + importa el cebo
  main.py       CLI: python -m moqesh.worldsmith build|evolve
```
