<#
  moqesh-ship.ps1 - Shipper agentless de Moqesh (PowerShell 5+).

  Corre por Tarea Programada en el servidor del cliente. Lee el access log del
  web server, se queda SOLO con las lineas que casan el prefijo del cebo
  (privacidad: el trafico real de usuarios nunca sale del host) y las envia
  firmadas con HMAC al servidor Moqesh. No instala software pesado.

  Idempotente: guarda un byte-offset del log; el servidor ademas deduplica.
  NUNCA modifica ni borra el log de origen.

  Variables de entorno (ver moqesh/clients/README.md):
    MOQESH_SERVER     URL base del servidor Moqesh         (requerida)
    MOQESH_KEY_ID     identificador de clave del sensor    (requerida)
    MOQESH_SECRET     secreto HMAC del sensor              (requerida)
    MOQESH_LOG        ruta del access log                  (requerida)
    MOQESH_BASE_PATH  prefijo del cebo, p.ej. /lure         (requerida)
    MOQESH_FORMAT     nginx|apache|caddy|json|raw          (def. nginx)
    MOQESH_STATE      fichero de offset                    (def. junto al script)
    MOQESH_DRY_RUN    1 = imprime lo que enviaria y sale   (def. vacio)

  Decision documentada: si /control devuelve enabled=false, NO se envia y NO se
  avanza el offset, para no perder lineas del cebo al reactivar el sensor.
#>

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

# TLS 1.2 para HTTPS en Windows antiguos.
try {
  [System.Net.ServicePointManager]::SecurityProtocol = `
    [System.Net.ServicePointManager]::SecurityProtocol -bor [System.Net.SecurityProtocolType]::Tls12
} catch { }

$CAP = 20000  # tope de lineas por envio (el servidor tambien capa a 20000)

function Die([string]$msg) { [Console]::Error.WriteLine("moqesh-ship: $msg"); exit 1 }
function Info([string]$msg) { Write-Host "moqesh-ship: $msg" }

# ---------------------------------------------------------------------------
# 1. Entorno y validacion
# ---------------------------------------------------------------------------
$server   = $env:MOQESH_SERVER
$keyId    = $env:MOQESH_KEY_ID
$secret   = $env:MOQESH_SECRET
$log      = $env:MOQESH_LOG
$basePath = $env:MOQESH_BASE_PATH
$fmt      = $env:MOQESH_FORMAT; if ([string]::IsNullOrEmpty($fmt)) { $fmt = 'nginx' }
$dryRun   = ($env:MOQESH_DRY_RUN -eq '1')

if ([string]::IsNullOrEmpty($server))   { Die 'falta MOQESH_SERVER' }
if ([string]::IsNullOrEmpty($keyId))    { Die 'falta MOQESH_KEY_ID' }
if ([string]::IsNullOrEmpty($secret))   { Die 'falta MOQESH_SECRET' }
if ([string]::IsNullOrEmpty($log))      { Die 'falta MOQESH_LOG' }
# Prefijo vacio = se enviaria TODO el trafico -> prohibido por privacidad.
if ([string]::IsNullOrEmpty($basePath)) { Die 'falta MOQESH_BASE_PATH (sin prefijo se enviaria trafico real)' }

$server = $server.TrimEnd('/')  # sin barra final -> evita //control

# Estado por defecto: unico por ruta de log.
$state = $env:MOQESH_STATE
if ([string]::IsNullOrEmpty($state)) {
  $selfDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
  if ([string]::IsNullOrEmpty($selfDir)) { $selfDir = '.' }
  $md5 = [System.Security.Cryptography.MD5]::Create()
  $h = ($md5.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($log)) | ForEach-Object { $_.ToString('x2') }) -join ''
  $state = Join-Path $selfDir (".moqesh-ship-" + $h.Substring(0, 8) + ".state")
}

$secretBytes = [System.Text.Encoding]::UTF8.GetBytes($secret)

# ---------------------------------------------------------------------------
# Helpers de firma
# ---------------------------------------------------------------------------

# Timestamp unix con decimales, cultura invariante (siempre punto).
function Get-MoqeshTs {
  $ms = [System.DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
  return ($ms / 1000.0).ToString('F3', [System.Globalization.CultureInfo]::InvariantCulture)
}

# "sha256=<hex>" sobre  ts + "." + body   (identico a moqesh.security.sign).
function Get-MoqeshSignature([string]$ts, [byte[]]$bodyBytes) {
  $prefix = [System.Text.Encoding]::UTF8.GetBytes($ts + '.')
  $msg = New-Object byte[] ($prefix.Length + $bodyBytes.Length)
  [System.Array]::Copy($prefix, 0, $msg, 0, $prefix.Length)
  if ($bodyBytes.Length -gt 0) {
    [System.Array]::Copy($bodyBytes, 0, $msg, $prefix.Length, $bodyBytes.Length)
  }
  $hmac = New-Object System.Security.Cryptography.HMACSHA256
  $hmac.Key = $secretBytes
  $hash = $hmac.ComputeHash($msg)
  $hex = ($hash | ForEach-Object { $_.ToString('x2') }) -join ''
  return 'sha256=' + $hex
}

# Escapa una cadena como literal JSON (comillas incluidas).
function ConvertTo-JsonLiteral([string]$s) {
  $sb = New-Object System.Text.StringBuilder
  [void]$sb.Append([char]34)
  foreach ($ch in $s.ToCharArray()) {
    $code = [int][char]$ch
    if     ($ch -eq [char]34) { [void]$sb.Append('\"') }
    elseif ($ch -eq [char]92) { [void]$sb.Append('\\') }
    elseif ($code -eq 8)      { [void]$sb.Append('\b') }
    elseif ($code -eq 9)      { [void]$sb.Append('\t') }
    elseif ($code -eq 10)     { [void]$sb.Append('\n') }
    elseif ($code -eq 12)     { [void]$sb.Append('\f') }
    elseif ($code -eq 13)     { [void]$sb.Append('\r') }
    elseif ($code -lt 32)     { [void]$sb.Append(('\u{0:x4}' -f $code)) }
    else                      { [void]$sb.Append($ch) }
  }
  [void]$sb.Append([char]34)
  return $sb.ToString()
}

function Write-Offset([long]$value) {
  $tmp = $state + '.tmp'
  try {
    [System.IO.File]::WriteAllText($tmp, [string]$value, [System.Text.Encoding]::ASCII)
    Move-Item -LiteralPath $tmp -Destination $state -Force
  } catch {
    Die "no se pudo escribir el estado en $state (permisos del directorio?)"
  }
}

# ---------------------------------------------------------------------------
# 2. Offset + rotacion
# ---------------------------------------------------------------------------
if (-not (Test-Path -LiteralPath $log)) { Die "el log no existe: $log" }

$curSize = (Get-Item -LiteralPath $log).Length

$offset = 0L
if (Test-Path -LiteralPath $state) {
  try {
    $raw = (Get-Content -LiteralPath $state -Raw -ErrorAction Stop).Trim()
    [void][long]::TryParse($raw, [ref]$offset)
  } catch { $offset = 0L }
}

# Rotacion / truncado: el log encogio -> empezar desde cero.
if ($curSize -lt $offset) {
  Info "rotacion detectada ($curSize < $offset); reiniciando offset a 0"
  $offset = 0L
}

if ($curSize -eq $offset) {
  Info "sin lineas nuevas (offset $offset)"
  exit 0
}

# Lee solo lo nuevo desde el offset, con sharing ReadWrite (no bloquea al web server).
$count = [int]($curSize - $offset)
$buf = New-Object byte[] $count
$fs = $null
try {
  $fs = New-Object System.IO.FileStream($log, [System.IO.FileMode]::Open,
        [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
  [void]$fs.Seek($offset, [System.IO.SeekOrigin]::Begin)
  $readTotal = 0
  while ($readTotal -lt $count) {
    $n = $fs.Read($buf, $readTotal, $count - $readTotal)
    if ($n -le 0) { break }
    $readTotal += $n
  }
} catch {
  Die "no se pudo leer $log (permisos?): $($_.Exception.Message)"
} finally {
  if ($fs) { $fs.Close() }
}

# ---------------------------------------------------------------------------
# 3. Lineas completas (ultima sin '\n' queda pendiente) + filtrado por prefijo.
#    consumed = bytes de TODAS las lineas completas; solo las del cebo se envian.
# ---------------------------------------------------------------------------
$lastNl = -1
for ($i = $readTotal - 1; $i -ge 0; $i--) { if ($buf[$i] -eq 10) { $lastNl = $i; break } }

$consumed = 0L
$matched = New-Object System.Collections.Generic.List[string]
if ($lastNl -ge 0) {
  $consumed = [long]($lastNl + 1)
  $text = [System.Text.Encoding]::UTF8.GetString($buf, 0, $lastNl + 1)
  foreach ($line in ($text -split "`n")) {
    $clean = $line.TrimEnd("`r")
    if ($clean.Length -eq 0) { continue }
    if ($clean.Contains($basePath)) { $matched.Add($clean) }  # solo lineas del cebo
  }
}
$newoffset = $offset + $consumed
$cnt = $matched.Count

# Sin lineas del cebo: avanza el offset (era trafico real) y termina.
if ($cnt -eq 0) {
  if ($dryRun) {
    Info "[dry-run] $consumed bytes nuevos, 0 lineas del cebo; nada que enviar (offset $offset -> $newoffset)"
    exit 0
  }
  Write-Offset $newoffset
  Info "0 lineas del cebo; offset $offset -> $newoffset"
  exit 0
}

$fmtLit  = ConvertTo-JsonLiteral $fmt
$baseLit = ConvertTo-JsonLiteral $basePath

# Divide en lotes de hasta CAP lineas y arma cada cuerpo JSON.
function Build-Body([System.Collections.Generic.List[string]]$lines, [int]$start, [int]$len) {
  $parts = New-Object System.Collections.Generic.List[string]
  for ($j = $start; $j -lt ($start + $len); $j++) { $parts.Add((ConvertTo-JsonLiteral $lines[$j])) }
  $arr = [string]::Join(',', $parts)
  return '{"format":' + $fmtLit + ',"base_path":' + $baseLit + ',"lines":[' + $arr + ']}'
}

$batches = New-Object System.Collections.Generic.List[string]
$pos = 0
while ($pos -lt $cnt) {
  $len = [Math]::Min($CAP, $cnt - $pos)
  $batches.Add((Build-Body $matched $pos $len))
  $pos += $len
}

# ---------------------------------------------------------------------------
# 6. DRY-RUN: imprime lo que enviaria y sale (sin red, sin avanzar offset).
# ---------------------------------------------------------------------------
if ($dryRun) {
  Info "[dry-run] servidor=$server formato=$fmt prefijo=$basePath"
  Info "[dry-run] offset $offset -> $newoffset ; $cnt lineas del cebo (NO se avanza el offset)"
  Info "[dry-run] se omite /control; a continuacion los cuerpos que se enviarian:"
  for ($b = 0; $b -lt $batches.Count; $b++) {
    $body = $batches[$b]
    $bodyBytes = [System.Text.Encoding]::UTF8.GetBytes($body)
    $ts = Get-MoqeshTs
    $sig = Get-MoqeshSignature $ts $bodyBytes
    Write-Host ("--- lote {0} -> POST {1}/ingest/logs ---" -f ($b + 1), $server)
    Write-Host ("X-Moqesh-Key-Id: {0}" -f $keyId)
    Write-Host ("X-Moqesh-Timestamp: {0}" -f $ts)
    Write-Host ("X-Moqesh-Signature: {0}" -f $sig)
    Write-Host $body
  }
  exit 0
}

# ---------------------------------------------------------------------------
# 4. GET /control (firmado) + verificacion de la firma del servidor.
# ---------------------------------------------------------------------------
$ts = Get-MoqeshTs
$sig = Get-MoqeshSignature $ts (New-Object byte[] 0)  # cuerpo vacio
$ctrlHeaders = @{
  'X-Moqesh-Key-Id'    = $keyId
  'X-Moqesh-Timestamp' = $ts
  'X-Moqesh-Signature' = $sig
}
try {
  $resp = Invoke-WebRequest -Uri "$server/control" -Method Get -Headers $ctrlHeaders -UseBasicParsing
} catch {
  Die "no se pudo conectar a $server/control: $($_.Exception.Message)"
}
if ([int]$resp.StatusCode -ne 200) { Die "/control devolvio HTTP $($resp.StatusCode)" }

# Bytes exactos del cuerpo para re-firmar.
$respBytes = $null
try {
  $ms = New-Object System.IO.MemoryStream
  $resp.RawContentStream.CopyTo($ms)
  $respBytes = $ms.ToArray()
} catch {
  $respBytes = [System.Text.Encoding]::UTF8.GetBytes([string]$resp.Content)
}

$srvTs  = @($resp.Headers['X-Moqesh-Timestamp'])[0]
$srvSig = @($resp.Headers['X-Moqesh-Server-Signature'])[0]
if ([string]::IsNullOrEmpty($srvSig)) { Die '/control sin X-Moqesh-Server-Signature' }

$calc = Get-MoqeshSignature $srvTs $respBytes
if ($calc -ne $srvSig) { Die 'firma del servidor INVALIDA (posible MITM); no se envia' }

$respText = [System.Text.Encoding]::UTF8.GetString($respBytes)
$enabled = $false
if ($respText -match '"enabled"\s*:\s*(true|false)') { $enabled = ($matches[1] -eq 'true') }
if (-not $enabled) {
  # DECISION: disabled -> no enviar y NO avanzar offset (no perder lineas del cebo).
  Info "sensor deshabilitado (enabled=false); no se envia ni se avanza el offset ($cnt lineas en espera)"
  exit 0
}

# ---------------------------------------------------------------------------
# 5. POST /ingest/logs por lotes (firmado). Offset solo tras exito total.
# ---------------------------------------------------------------------------
$sent = 0
for ($b = 0; $b -lt $batches.Count; $b++) {
  $body = $batches[$b]
  $bodyBytes = [System.Text.Encoding]::UTF8.GetBytes($body)
  $ts = Get-MoqeshTs
  $sig = Get-MoqeshSignature $ts $bodyBytes
  $headers = @{
    'X-Moqesh-Key-Id'    = $keyId
    'X-Moqesh-Timestamp' = $ts
    'X-Moqesh-Signature' = $sig
  }
  try {
    $r = Invoke-WebRequest -Uri "$server/ingest/logs" -Method Post -Headers $headers `
         -ContentType 'application/json' -Body $bodyBytes -UseBasicParsing
  } catch {
    Die "fallo enviando el lote $($b + 1) (offset sin avanzar): $($_.Exception.Message)"
  }
  if ([int]$r.StatusCode -lt 200 -or [int]$r.StatusCode -ge 300) {
    Die "ingest devolvio HTTP $($r.StatusCode) en el lote $($b + 1) (offset sin avanzar)"
  }
  $sent++
}

# Todos los lotes OK -> ahora si avanzamos el offset.
Write-Offset $newoffset
Info "enviados $cnt lineas del cebo en $sent lote(s); offset $offset -> $newoffset"
exit 0
