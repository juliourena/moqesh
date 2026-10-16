# Sensores: desplegar Moqesh en servidores remotos

Un **sensor** es un punto donde se sirve el cebo de Moqesh. Hay tres tipos:

| Tipo | Qué es | Capacidades | Huella en el host |
|------|--------|-------------|-------------------|
| `local` | El propio honeypot de Moqesh (:8080) | Todo | — |
| `agent` | Binario autocontenido en el servidor remoto | Laberinto infinito + tar-pit + **gates de credenciales/CTF** + telemetría | Proceso + puerto + beacon saliente |
| `agentless` | ZIP estático + cron que envía logs | **Detección conductual** (sin gates en vivo) | Solo archivos + un cron esporádico (máximo sigilo) |

Regla práctica: usa **agent** cuando necesites CTF/reuso de credencial; usa **agentless** cuando no puedas (o no quieras) instalar nada o cuando el sigilo mande.

## Alta de un sensor (1 comando)

1. Dashboard → **Sensores → Añadir sensor**. El asistente recomienda el modo con 3 preguntas y crea el sensor.
2. Copia el **comando único** que aparece (se muestra **una sola vez**, lleva la clave embebida):

   ```sh
   curl -fsSL https://TU-MOQESH/s/<token> | sh
   ```

   ¿Prefieres revisar antes de ejecutar? Usa la opción **inspeccionar**: descarga el script, verifica su `sha256` y léelo antes de correrlo.
3. El asistente queda en *"esperando primer check-in…"* y cambia a **✓ conectado** en cuanto el sensor late (por WebSocket).

### Modo agent

El instalador hace **preflight** (conectividad a Moqesh y reloj), descarga el binario para tu `os/arch`, escribe la config con la clave (permisos `600`) e instala un servicio (`systemd` en Linux, servicio en Windows). A partir de ahí el agente sirve el cebo y envía telemetría firmada.

> Los binarios del agente los produce el CI (`release.yml`, PyInstaller) y se adjuntan al
> GitHub Release; la imagen Docker de GHCR ya los trae embebidos (linux amd64/arm64), así que
> `GET /download/agent/{os-arch}` funciona sin pasos extra. Build manual: [`moqesh/agent/BUILD.md`](../moqesh/agent/BUILD.md).

### Modo agentless

1. Descarga el **script de envío** y los **bundles** (varios ZIP, cada uno con estructura/cantidad distintas — sin patrones).
2. Descomprime los bundles donde quieras servir el cebo (p.ej. bajo `/lure`).
3. Aplica el snippet de **servido seguro** (incluido en cada bundle, para nginx/apache/caddy) que sirve el contenido como **texto plano, sin ejecución**.
4. Añade la **tarea programada** que te da el asistente (lee solo las líneas del prefijo del cebo y las envía firmadas):

   ```
   */5 * * * * MOQESH_SERVER=... MOQESH_KEY_ID=... MOQESH_SECRET=... /opt/moqesh/moqesh-ship.sh
   ```

   Haz un **dry-run** (`MOQESH_DRY_RUN=1`) para ver qué se enviaría antes de activarlo.

## Seguridad

- Cada sensor tiene su **clave simétrica**; firma HMAC en ambos sentidos (envíos del sensor **y** respuestas de control), así un MITM no puede forjar ni un envío ni un "disable". Ventana anti-replay por timestamp.
- Clave de **mínimo privilegio** (solo ingestión + control de su sensor) y **revocable/rotable** en un clic desde el dashboard. La clave vive en un host que puede ser atacado: por diseño es de bajo valor.
- Toda ingestión se trata como **hostil**: validación, rate-limit, dedup y filtrado por prefijo. El agentless solo envía líneas del cebo (no tráfico real de usuarios).

## Operación

- **Estado**: la página Sensores muestra online/offline (por último check-in), sesiones y alertas por sensor, versión y último envío. Un sensor que queda en silencio puede significar que lo encontraron: Moqesh lo marca.
- **Encender/apagar y rotar seed**: en caliente; el agente y el cron consultan `/control` y lo aplican.
- **Dar de baja**: revoca la clave y retira el sensor. En agentless, borra el cebo con el `uninstall.sh` incluido en el bundle (usa el `MANIFEST.json`).

## Límites de esta entrega

- El modo agentless detecta **comportamiento**, no reuso de credencial en gates en vivo (eso requiere agent).
- Los servidores remotos deben **alcanzar** el servidor Moqesh (HTTPS saliente). El instalador valida la conectividad; para entornos con egress cerrado, el relay store-and-forward llegará en una entrega futura.
