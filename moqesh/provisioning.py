"""Generación server-side de scripts e instrucciones de instalación.

Todo lo que el usuario pega en su servidor sale de aquí, con la clave y la URL ya
embebidas. El onboarding es: crear sensor → copiar un comando → ✓ conectado.
"""

from __future__ import annotations

from .config import settings


def server_url() -> str:
    return (settings.public_url or f"http://localhost:{settings.dashboard_port}").rstrip("/")


def one_command(token: str) -> str:
    """Comando principal (curl | sh) para el asistente."""
    return f"curl -fsSL {server_url()}/s/{token} | sh"


def inspect_command(token: str) -> str:
    """Alternativa 'inspeccionar primero': descargar + ver checksum antes de ejecutar."""
    url = f"{server_url()}/s/{token}"
    return (
        f"curl -fsSL {url} -o moqesh-install.sh && sha256sum moqesh-install.sh "
        "&& less moqesh-install.sh && sh moqesh-install.sh"
    )


def agent_install_script(key_id: str, secret: str) -> str:
    """Script POSIX que instala el agente como binario autocontenido + servicio."""
    srv = server_url()
    return f"""#!/bin/sh
set -eu
# Instalador del agente Moqesh. Revisa este script antes de ejecutarlo.
SERVER="{srv}"
KEY_ID="{key_id}"
SECRET="{secret}"

OS=$(uname -s | tr '[:upper:]' '[:lower:]')
ARCH=$(uname -m)
case "$ARCH" in
  x86_64|amd64) ARCH=amd64 ;;
  aarch64|arm64) ARCH=arm64 ;;
  *) echo "arquitectura no soportada: $ARCH"; exit 1 ;;
esac

DIR="${{MOQESH_DIR:-/opt/moqesh}}"
mkdir -p "$DIR"
echo "[moqesh] preflight: probando conectividad a $SERVER ..."
if ! curl -fsS -o /dev/null "$SERVER/healthz"; then
  echo "[moqesh] ERROR: no se alcanza $SERVER. Abre egress HTTPS hacia ese host."; exit 1
fi
echo "[moqesh] descargando agente ($OS/$ARCH) ..."
curl -fsSL "$SERVER/download/agent/$OS-$ARCH" -o "$DIR/moqesh-agent"
chmod +x "$DIR/moqesh-agent"
cat > "$DIR/agent.env" <<EOF
MOQESH_SERVER=$SERVER
MOQESH_KEY_ID=$KEY_ID
MOQESH_SECRET=$SECRET
EOF
chmod 600 "$DIR/agent.env"

if command -v systemctl >/dev/null 2>&1; then
  cat > /etc/systemd/system/moqesh-agent.service <<EOF
[Unit]
Description=Moqesh Agent
After=network.target
[Service]
EnvironmentFile=$DIR/agent.env
ExecStart=$DIR/moqesh-agent
Restart=always
[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload && systemctl enable --now moqesh-agent
  echo "[moqesh] agente instalado y arrancado (servicio systemd)."
else
  echo "[moqesh] sin systemd; arranca manualmente: env \\$(cat $DIR/agent.env) $DIR/moqesh-agent &"
fi
"""


def agentless_steps(sensor_id: int, key_id: str, secret: str, base_path: str, bundle_count: int) -> dict:
    """Pasos y snippets para el modo sin instalación (ZIP + cron)."""
    srv = server_url()
    cron = (
        f"*/5 * * * * MOQESH_SERVER={srv} MOQESH_KEY_ID={key_id} MOQESH_SECRET={secret} "
        f"/opt/moqesh/moqesh-ship.sh >/dev/null 2>&1"
    )
    return {
        "steps": [
            f"Descarga el script de envío: curl -fsSL {srv}/download/shipper/{sensor_id} "
            "-o /opt/moqesh/moqesh-ship.sh && chmod +x /opt/moqesh/moqesh-ship.sh",
            f"Descarga y descomprime los {bundle_count} bundles donde quieras servir el cebo "
            f"(bajo {base_path}). Enlaces en la pestaña del sensor.",
            "Aplica la config de servido seguro (texto plano, sin ejecución) que te damos por tipo de web server.",
            "Añade la tarea programada (cron) de abajo para enviar los logs del cebo.",
        ],
        "cron": cron,
        "shipper_url": f"{srv}/download/shipper/{sensor_id}",
        "note": "El script solo envía líneas de log que casen el prefijo del cebo; haz un dry-run antes.",
    }
