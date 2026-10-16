#!/bin/sh
# moqesh-ship.sh - Shipper agentless de Moqesh (POSIX sh).
#
# Corre por cron en el servidor del cliente. Lee el access log del web server,
# se queda SOLO con las lineas que casan el prefijo del cebo (privacidad: el
# trafico real de usuarios nunca sale del host), y las envia firmadas con HMAC
# al servidor Moqesh. No instala nada: solo necesita sh, curl, openssl y awk.
#
# Idempotente: guarda un byte-offset del log; el servidor ademas deduplica.
# NUNCA modifica ni borra el log de origen.
#
# Variables de entorno (ver moqesh/clients/README.md):
#   MOQESH_SERVER     URL base del servidor Moqesh         (requerida)
#   MOQESH_KEY_ID     identificador de clave del sensor    (requerida)
#   MOQESH_SECRET     secreto HMAC del sensor              (requerida)
#   MOQESH_LOG        ruta del access log                  (requerida)
#   MOQESH_BASE_PATH  prefijo del cebo, p.ej. /lure         (requerida)
#   MOQESH_FORMAT     nginx|apache|caddy|json|raw          (def. nginx)
#   MOQESH_STATE      fichero de offset                    (def. junto al script)
#   MOQESH_DRY_RUN    1 = imprime lo que enviaria y sale   (def. vacio)
#
# Decision documentada: si /control devuelve enabled=false, NO se envia y NO se
# avanza el offset, para no perder lineas del cebo al reactivar el sensor.

LC_ALL=C
export LC_ALL

CAP=20000  # tope de lineas por envio (el servidor tambien capa a 20000)

die() { printf 'moqesh-ship: %s\n' "$*" >&2; exit 1; }
info() { printf 'moqesh-ship: %s\n' "$*" >&2; }

# ---------------------------------------------------------------------------
# 1. Entorno y validacion
# ---------------------------------------------------------------------------
MOQESH_SERVER=${MOQESH_SERVER:-}
MOQESH_KEY_ID=${MOQESH_KEY_ID:-}
MOQESH_SECRET=${MOQESH_SECRET:-}
MOQESH_LOG=${MOQESH_LOG:-}
MOQESH_BASE_PATH=${MOQESH_BASE_PATH:-}
MOQESH_FORMAT=${MOQESH_FORMAT:-nginx}
MOQESH_DRY_RUN=${MOQESH_DRY_RUN:-}

[ -n "$MOQESH_SERVER" ]    || die "falta MOQESH_SERVER"
[ -n "$MOQESH_KEY_ID" ]    || die "falta MOQESH_KEY_ID"
[ -n "$MOQESH_SECRET" ]    || die "falta MOQESH_SECRET"
[ -n "$MOQESH_LOG" ]       || die "falta MOQESH_LOG"
# Prefijo vacio = se enviaria TODO el trafico -> prohibido por privacidad.
[ -n "$MOQESH_BASE_PATH" ] || die "falta MOQESH_BASE_PATH (sin prefijo se enviaria trafico real)"

MOQESH_SERVER=${MOQESH_SERVER%/}  # sin barra final -> evita //control

command -v curl    >/dev/null 2>&1 || die "curl no esta disponible"
command -v openssl >/dev/null 2>&1 || die "openssl no esta disponible"
command -v awk     >/dev/null 2>&1 || die "awk no esta disponible"

# Directorio del propio script (para el estado por defecto).
SELF_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" 2>/dev/null && pwd) || SELF_DIR=.

# Estado por defecto: unico por ruta de log (varios logs -> varios offsets).
if [ -n "${MOQESH_STATE:-}" ]; then
  STATE=$MOQESH_STATE
else
  _h=$(printf '%s' "$MOQESH_LOG" | cksum 2>/dev/null | cut -d' ' -f1)
  [ -n "$_h" ] || _h=default
  STATE="$SELF_DIR/.moqesh-ship-$_h.state"
fi

# ---------------------------------------------------------------------------
# Helpers de firma
# ---------------------------------------------------------------------------

# Timestamp unix con decimales (fallback a enteros si date no soporta %N).
mq_ts() {
  _t=$(date +%s.%N 2>/dev/null)
  case "$_t" in
    *N*|'') _t=$(date +%s) ;;
  esac
  printf '%s' "$_t"
}

# sign_file TS FILE -> "sha256=<hex>" sobre  TS + "." + <bytes de FILE>
# (identico a moqesh.security.sign: HMAC_SHA256(secret, ts.encode()+b"."+body)).
sign_file() {
  _ts=$1; _f=$2
  _hex=$({ printf '%s.' "$_ts"; cat "$_f"; } \
    | openssl dgst -sha256 -hmac "$MOQESH_SECRET" 2>/dev/null \
    | awk '{print $NF}')
  [ -n "$_hex" ] || die "openssl fallo al calcular HMAC"
  printf 'sha256=%s' "$_hex"
}

# Escapa un escalar corto (format / base_path) para JSON.
json_scalar() {
  printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'
}

# ---------------------------------------------------------------------------
# Temporales
# ---------------------------------------------------------------------------
TMPD=$(mktemp -d 2>/dev/null) || die "no se pudo crear directorio temporal"
trap 'rm -rf "$TMPD"' EXIT INT TERM HUP

RAW="$TMPD/raw"            # bytes nuevos del log
ESC="$TMPD/esc"            # lineas del cebo ya escapadas (una por linea)
CNTF="$TMPD/cnt"           # numero de lineas del cebo
HDR="$TMPD/hdr"            # cabeceras de /control
CBODY="$TMPD/cbody"        # cuerpo de /control
EMPTY="$TMPD/empty"        # cuerpo vacio (firma del GET)
: > "$EMPTY"

# ---------------------------------------------------------------------------
# 2. Offset + rotacion
# ---------------------------------------------------------------------------
[ -e "$MOQESH_LOG" ] || die "el log no existe: $MOQESH_LOG"
[ -r "$MOQESH_LOG" ] || die "sin permiso de lectura sobre: $MOQESH_LOG"

cur_size=$(wc -c < "$MOQESH_LOG" 2>/dev/null | tr -d ' ')
case "$cur_size" in ''|*[!0-9]*) die "no se pudo medir el tamano de $MOQESH_LOG" ;; esac

offset=0
if [ -f "$STATE" ]; then
  offset=$(cat "$STATE" 2>/dev/null)
  case "$offset" in ''|*[!0-9]*) offset=0 ;; esac
fi

# Rotacion / truncado: el log encogio -> empezar desde cero.
if [ "$cur_size" -lt "$offset" ]; then
  info "rotacion detectada ($cur_size < $offset); reiniciando offset a 0"
  offset=0
fi

if [ "$cur_size" -eq "$offset" ]; then
  info "sin lineas nuevas (offset $offset)"
  exit 0
fi

# Lee solo lo nuevo desde el offset (tail -c +N es 1-based).
tail -c "+$((offset + 1))" "$MOQESH_LOG" > "$RAW" 2>/dev/null \
  || die "no se pudo leer $MOQESH_LOG desde el offset (permisos?)"

# ¿Termina en salto de linea? La ultima linea puede estar a medio escribir.
NL='
'
ends_nl=0
if [ -s "$RAW" ]; then
  _lc=$(tail -c 1 "$RAW" 2>/dev/null; printf x)
  case "$_lc" in "${NL}x") ends_nl=1 ;; esac
fi

# ---------------------------------------------------------------------------
# 3. Filtrado por prefijo + escape JSON + conteo de bytes consumidos
#
# consumed = bytes de TODAS las lineas completas (casen o no el prefijo), para
# avanzar el offset sin reprocesar trafico real. Solo las lineas que CONTIENEN
# el prefijo se acumulan para enviar. La ultima linea sin '\n' se deja pendiente.
# ---------------------------------------------------------------------------
: > "$ESC"
consumed=$(awk \
  -v base="$MOQESH_BASE_PATH" -v ends_nl="$ends_nl" \
  -v linesfile="$ESC" -v countfile="$CNTF" '
function esc(s,   out, i, c, b, n) {
  out = "\"";
  n = length(s);
  for (i = 1; i <= n; i++) {
    c = substr(s, i, 1); b = ordv[c];
    if (c == "\\")      out = out "\\\\";
    else if (c == "\"") out = out "\\\"";
    else if (b == 8)    out = out "\\b";
    else if (b == 9)    out = out "\\t";
    else if (b == 10)   out = out "\\n";
    else if (b == 12)   out = out "\\f";
    else if (b == 13)   out = out "\\r";
    else if (b < 32)    out = out sprintf("\\u%04x", b);
    else                out = out c;
  }
  return out "\"";
}
function flush(line) {
  consumed += length(line) + 1;           # +1 por el \n que la terminaba
  if (index(line, base) > 0) {            # solo lineas del cebo
    print esc(line) > linesfile;
    cnt++;
  }
}
BEGIN { for (i = 0; i < 256; i++) ordv[sprintf("%c", i)] = i; consumed = 0; cnt = 0; }
NR > 1 { flush(prev) }                     # prev siempre esta completa
{ prev = $0 }
END {
  if (ends_nl == 1 && NR >= 1) flush(prev);  # ultima linea completa
  print cnt + 0 > countfile;
  print consumed + 0;                        # -> stdout
}
' "$RAW") || die "fallo procesando el log"

case "$consumed" in ''|*[!0-9]*) consumed=0 ;; esac
cnt=0
if [ -f "$CNTF" ]; then cnt=$(cat "$CNTF" 2>/dev/null); fi
case "$cnt" in ''|*[!0-9]*) cnt=0 ;; esac
newoffset=$((offset + consumed))

# ---------------------------------------------------------------------------
# write_offset: escritura atomica del estado.
# ---------------------------------------------------------------------------
write_offset() {
  _o=$1
  if ( set -C; printf '%s\n' "$_o" > "$STATE.tmp" ) 2>/dev/null; then
    :
  elif printf '%s\n' "$_o" > "$STATE.tmp" 2>/dev/null; then
    :
  else
    die "no se pudo escribir el estado en $STATE (permisos del directorio?)"
  fi
  mv -f "$STATE.tmp" "$STATE" 2>/dev/null || die "no se pudo actualizar $STATE"
}

# Sin lineas del cebo en lo nuevo: avanza el offset (era trafico real) y termina.
if [ "$cnt" -eq 0 ]; then
  if [ "$MOQESH_DRY_RUN" = "1" ]; then
    info "[dry-run] $consumed bytes nuevos, 0 lineas del cebo; nada que enviar (offset $offset -> $newoffset)"
    exit 0
  fi
  write_offset "$newoffset"
  info "0 lineas del cebo; offset $offset -> $newoffset"
  exit 0
fi

fmt_esc=$(json_scalar "$MOQESH_FORMAT")
base_esc=$(json_scalar "$MOQESH_BASE_PATH")

# Divide en lotes de hasta CAP lineas.
CHUNKD="$TMPD/chunks"
mkdir -p "$CHUNKD"
if ! split -l "$CAP" "$ESC" "$CHUNKD/c." 2>/dev/null; then
  cp "$ESC" "$CHUNKD/c.aa"  # fallback: un solo lote
fi

# ---------------------------------------------------------------------------
# build_body CHUNK BODYFILE : arma el JSON exacto a firmar/enviar.
# ---------------------------------------------------------------------------
build_body() {
  _chunk=$1; _bf=$2
  _arr=$(paste -sd, "$_chunk")
  printf '%s%s%s' \
    '{"format":"'"$fmt_esc"'","base_path":"'"$base_esc"'","lines":[' \
    "$_arr" \
    ']}' > "$_bf"
}

# ---------------------------------------------------------------------------
# 6. DRY-RUN: imprime lo que enviaria y sale (sin red, sin avanzar offset).
# ---------------------------------------------------------------------------
if [ "$MOQESH_DRY_RUN" = "1" ]; then
  info "[dry-run] servidor=$MOQESH_SERVER formato=$MOQESH_FORMAT prefijo=$MOQESH_BASE_PATH"
  info "[dry-run] offset $offset -> $newoffset ; $cnt lineas del cebo (NO se avanza el offset)"
  info "[dry-run] se omite /control; a continuacion los cuerpos que se enviarian:"
  _i=0
  for _chunk in "$CHUNKD"/c.*; do
    [ -f "$_chunk" ] || continue
    _i=$((_i + 1))
    _bf="$TMPD/body.$_i"
    build_body "$_chunk" "$_bf"
    _ts=$(mq_ts)
    _sig=$(sign_file "$_ts" "$_bf")
    printf -- '--- lote %s -> POST %s/ingest/logs ---\n' "$_i" "$MOQESH_SERVER"
    printf 'X-Moqesh-Key-Id: %s\n' "$MOQESH_KEY_ID"
    printf 'X-Moqesh-Timestamp: %s\n' "$_ts"
    printf 'X-Moqesh-Signature: %s\n' "$_sig"
    cat "$_bf"
    printf '\n'
  done
  exit 0
fi

# ---------------------------------------------------------------------------
# 4. GET /control (firmado) + verificacion de la firma del servidor.
# ---------------------------------------------------------------------------
ts=$(mq_ts)
sig=$(sign_file "$ts" "$EMPTY")  # cuerpo vacio
code=$(curl -sS -o "$CBODY" -D "$HDR" -w '%{http_code}' \
  -H "X-Moqesh-Key-Id: $MOQESH_KEY_ID" \
  -H "X-Moqesh-Timestamp: $ts" \
  -H "X-Moqesh-Signature: $sig" \
  "$MOQESH_SERVER/control" 2>/dev/null) \
  || die "no se pudo conectar a $MOQESH_SERVER/control"
[ "$code" = "200" ] || die "/control devolvio HTTP $code"

srv_ts=$(awk -F': *' 'tolower($1)=="x-moqesh-timestamp"{v=$2} END{printf "%s", v}' "$HDR" | tr -d '\r\n')
srv_sig=$(awk -F': *' 'tolower($1)=="x-moqesh-server-signature"{v=$2} END{printf "%s", v}' "$HDR" | tr -d '\r\n')
[ -n "$srv_sig" ] || die "/control sin X-Moqesh-Server-Signature"

calc=$(sign_file "$srv_ts" "$CBODY")
[ "$calc" = "$srv_sig" ] || die "firma del servidor INVALIDA (posible MITM); no se envia"

enabled=$(sed -n 's/.*"enabled"[[:space:]]*:[[:space:]]*\(true\|false\).*/\1/p' "$CBODY" | head -n1)
if [ "$enabled" != "true" ]; then
  # DECISION: disabled -> no enviar y NO avanzar offset (no perder lineas del cebo).
  info "sensor deshabilitado (enabled=$enabled); no se envia ni se avanza el offset ($cnt lineas en espera)"
  exit 0
fi

# ---------------------------------------------------------------------------
# 5. POST /ingest/logs por lotes (firmado). Offset solo tras exito total.
# ---------------------------------------------------------------------------
sent=0
_i=0
for _chunk in "$CHUNKD"/c.*; do
  [ -f "$_chunk" ] || continue
  _i=$((_i + 1))
  _bf="$TMPD/body.$_i"
  build_body "$_chunk" "$_bf"
  _ts=$(mq_ts)
  _sig=$(sign_file "$_ts" "$_bf")
  _resp="$TMPD/resp.$_i"
  code=$(curl -sS -o "$_resp" -w '%{http_code}' -X POST \
    -H "Content-Type: application/json" \
    -H "X-Moqesh-Key-Id: $MOQESH_KEY_ID" \
    -H "X-Moqesh-Timestamp: $_ts" \
    -H "X-Moqesh-Signature: $_sig" \
    --data-binary @"$_bf" \
    "$MOQESH_SERVER/ingest/logs" 2>/dev/null) \
    || die "fallo de red enviando el lote $_i (offset sin avanzar)"
  case "$code" in
    2*) sent=$((sent + 1)) ;;
    *)  die "ingest devolvio HTTP $code en el lote $_i (offset sin avanzar)" ;;
  esac
done

# Todos los lotes OK -> ahora si avanzamos el offset.
write_offset "$newoffset"
info "enviados $cnt lineas del cebo en $sent lote(s); offset $offset -> $newoffset"
exit 0
