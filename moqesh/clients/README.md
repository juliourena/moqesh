# Moqesh - Shippers agentless

Scripts de envío (shipper) **sin instalación de software pesado**. Corren por
cron (POSIX) o Tarea Programada (Windows), leen el access log del web server, se
quedan **solo con las líneas que casan el prefijo del cebo** y las envían
firmadas (HMAC) al servidor Moqesh.

- `moqesh-ship.sh` — POSIX `sh`. Necesita solo `curl`, `openssl` y `awk`.
- `moqesh-ship.ps1` — PowerShell 5+ (Windows), sin dependencias externas.

Ambos son **idempotentes** (un byte-offset del log evita reenvíos; el servidor
además deduplica) y **nunca** modifican ni borran el log de origen.

## Privacidad

El script envía **únicamente** las líneas cuyo contenido incluye
`MOQESH_BASE_PATH` (el prefijo del cebo). El tráfico real de los usuarios nunca
sale del host. Por eso `MOQESH_BASE_PATH` es obligatorio: sin prefijo se enviaría
todo el log, y el script se niega a ejecutarse.

## Variables de entorno

| Variable           | Req. | Descripción                                                        |
|--------------------|:----:|--------------------------------------------------------------------|
| `MOQESH_SERVER`    |  sí  | URL base del servidor Moqesh (p.ej. `https://moqesh.example.com`). |
| `MOQESH_KEY_ID`    |  sí  | Identificador de clave del sensor.                                 |
| `MOQESH_SECRET`    |  sí  | Secreto HMAC del sensor (mantener privado).                        |
| `MOQESH_LOG`       |  sí  | Ruta del access log (p.ej. `/var/log/nginx/access.log`).           |
| `MOQESH_BASE_PATH` |  sí  | Prefijo del cebo (p.ej. `/lure`).                                  |
| `MOQESH_FORMAT`    |  no  | `nginx` \| `apache` \| `caddy` \| `json` \| `raw`. Def. `nginx`.   |
| `MOQESH_STATE`     |  no  | Fichero de offset. Def. junto al script, único por ruta de log.    |
| `MOQESH_DRY_RUN`   |  no  | `1` = imprime lo que enviaría y sale (no toca la red ni el offset). |

## Comportamiento

1. **Offset + rotación**: guarda el byte-offset leído. Si el tamaño actual del
   log es menor que el offset guardado (rotación/truncado), reinicia a `0`. Solo
   se leen las líneas nuevas desde el offset. La última línea sin `\n` (posible
   escritura a medias) se deja pendiente para la siguiente ejecución.
2. **Filtrado** por `MOQESH_BASE_PATH` (ver *Privacidad*).
3. **`GET /control`** firmado. Se **verifica la firma del servidor**
   (`X-Moqesh-Server-Signature`) antes de confiar en la respuesta; si no casa, se
   aborta sin enviar (protección anti-MITM).
4. Si `enabled=false`: **no se envía y NO se avanza el offset** (decisión de
   diseño), para no perder líneas del cebo al reactivar el sensor. Entretanto el
   script vuelve a leer esas mismas líneas en cada ejecución, pero **no salen del
   host** hasta que el sensor se reactiva.
5. **`POST /ingest/logs`** firmado, en lotes de hasta **20 000 líneas** por envío.
   El offset solo avanza tras el éxito de **todos** los lotes.
6. Las líneas que no casan el prefijo (tráfico real) sí hacen avanzar el offset
   para no reescanearlas, pero nunca se envían.

### Firma (idéntica a `moqesh/security.py`)

```
ts        = <epoch unix con decimales, como string>
message   = ts + "." + <cuerpo exacto>          # cuerpo vacío en GET /control
signature = "sha256=" + HMAC_SHA256_hex(MOQESH_SECRET, message)
```

Cabeceras: `X-Moqesh-Key-Id`, `X-Moqesh-Timestamp`, `X-Moqesh-Signature`.

## Ejemplo: cron (POSIX, cada 5 minutos)

Preferible poner los secretos en un fichero de entorno con permisos `600` en vez
de dejarlos en el crontab:

```sh
# /opt/moqesh/ship.env   (chmod 600)
export MOQESH_SERVER=https://moqesh.example.com
export MOQESH_KEY_ID=mq_xxxxxxxxxxxxxxxx
export MOQESH_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
export MOQESH_LOG=/var/log/nginx/access.log
export MOQESH_BASE_PATH=/lure
export MOQESH_FORMAT=nginx
```

```cron
# crontab -e
*/5 * * * * . /opt/moqesh/ship.env && /opt/moqesh/moqesh-ship.sh >> /var/log/moqesh-ship.log 2>&1
```

O todo en una línea (como lo genera el asistente de provisioning):

```cron
*/5 * * * * MOQESH_SERVER=https://moqesh.example.com MOQESH_KEY_ID=mq_... MOQESH_SECRET=... MOQESH_LOG=/var/log/nginx/access.log MOQESH_BASE_PATH=/lure /opt/moqesh/moqesh-ship.sh >/dev/null 2>&1
```

## Ejemplo: Tarea Programada (Windows, cada 5 minutos)

```powershell
# Ejecutar una vez como administrador para registrar la tarea.
$envBlock = @'
$env:MOQESH_SERVER   = "https://moqesh.example.com"
$env:MOQESH_KEY_ID   = "mq_xxxxxxxxxxxxxxxx"
$env:MOQESH_SECRET   = "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
$env:MOQESH_LOG      = "C:\logs\access.log"
$env:MOQESH_BASE_PATH= "/lure"
$env:MOQESH_FORMAT   = "nginx"
& "C:\moqesh\moqesh-ship.ps1"
'@
Set-Content -Path C:\moqesh\run-ship.ps1 -Value $envBlock -Encoding UTF8

$action  = New-ScheduledTaskAction -Execute "powershell.exe" `
           -Argument '-NoProfile -ExecutionPolicy Bypass -File C:\moqesh\run-ship.ps1'
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
           -RepetitionInterval (New-TimeSpan -Minutes 5)
Register-ScheduledTask -TaskName "Moqesh Shipper" -Action $action -Trigger $trigger `
           -RunLevel Highest -Description "Envío agentless de logs del cebo a Moqesh"
```

> Protege `run-ship.ps1` con ACL restrictiva: contiene el secreto.

## Dry-run

Siempre haz una prueba en seco antes de programar la tarea:

```sh
MOQESH_SERVER=https://moqesh.example.com MOQESH_KEY_ID=mq_... MOQESH_SECRET=... \
MOQESH_LOG=/var/log/nginx/access.log MOQESH_BASE_PATH=/lure MOQESH_DRY_RUN=1 \
  sh /opt/moqesh/moqesh-ship.sh
```

Imprime el/los cuerpo(s) JSON exactos y las cabeceras firmadas que se enviarían,
**sin** contactar el servidor y **sin** avanzar el offset. Verifica que:

- solo aparecen líneas del cebo (ninguna de tráfico real),
- el formato (`MOQESH_FORMAT`) casa con tu web server.

## Verificación de paridad de firma (hecha)

Se comprobó que la firma HMAC de los scripts coincide **byte a byte** con
`moqesh.security.sign`:

```sh
# POSIX / openssl  (lo que hace sign_file en moqesh-ship.sh)
SECRET=...; TS=1760000000.123; BODY='{"format":"nginx",...}'
{ printf '%s.' "$TS"; printf '%s' "$BODY"; } | openssl dgst -sha256 -hmac "$SECRET" | awk '{print $NF}'

# Referencia Python
python -c "from moqesh import security; print(security.sign('$SECRET','$TS', b'...'))"
```

Resultado: idénticos para cuerpo lleno y para cuerpo vacío (GET `/control`),
incluso con secretos que empiezan por `-` (p.ej. de `token_urlsafe`). La versión
PowerShell (`HMACSHA256` sobre `UTF8(ts + "." + body)`) produce el mismo hash.
Además, el cuerpo JSON generado por ambos scripts se parseó con
`moqesh.logparse.parse` y la verificación de `X-Moqesh-Server-Signature` se probó
contra una respuesta firmada con `moqesh.security.sign` (incluida una prueba de
manipulación que, correctamente, se rechaza).

## Nota de seguridad

En POSIX el secreto se pasa a `openssl dgst -hmac` como argumento; es visible de
forma fugaz en la lista de procesos del propio host. Es el mismo secreto que ya
vive en el entorno del cron; mantén el host y el fichero de entorno con permisos
restrictivos.
