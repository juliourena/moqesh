"""Generador de bundles estáticos para el modo agentless.

Materializa snapshots FINITOS y ALEATORIOS del laberinto y los empaqueta en un
ZIP o un tar.gz que el usuario descomprime en su servidor como cebo. A diferencia
del honeypot vivo (infinito y determinista por petición), aquí se congela un árbol
acotado: profundidad, ramas y cantidad de archivos se eligen al azar por bundle,
de modo que dos descargas nunca comparten estructura, cantidad ni patrones (clave
anti-fingerprint).

Seguridad de colocación: el contenido se escribe con extensiones INERTES para que
el web server del cliente lo sirva como DATOS y jamás lo ejecute (ver `_ruta_segura`
y los snippets de `serve-config/`). Solo se usa stdlib para empaquetar.
"""

from __future__ import annotations

import io
import json
import random
import tarfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import uuid4

from sqlalchemy.orm import Session

from .config import settings
from .labyrinth import LabyrinthGenerator, LabyrinthOptions
from .models import Sensor, SensorBundle

# Extensiones que un web server podría EJECUTAR en el host del cliente: nunca se
# colocan tal cual; se neutralizan a una extensión inerte (`.txt`).
_EJECUTABLES = (".php", ".sh", ".cgi", ".aspx", ".jsp", ".pl", ".py", ".phtml")

# Nombres plausibles para la carpeta raíz del cebo (se les añade un sufijo hex).
_POOL_RAIZ = ["assets", "static", "public", "data", "files", "shared", "content", "docs", "cdn", "media"]


def bundles_dir() -> Path:
    """Directorio donde se escriben los bundles (junto a la DB). Lo crea si falta."""
    directorio = Path(settings.db_path).resolve().parent / "bundles"
    directorio.mkdir(parents=True, exist_ok=True)
    return directorio


# ----------------------------- rutas / seguridad ----------------------------


def _profundidad(ruta: str) -> int:
    """Niveles del path (la raíz '/' es 0)."""
    t = ruta.strip("/")
    return 0 if not t else len(t.split("/"))


def _seguro(rel: str) -> bool:
    """Evita traversal: ningún segmento vacío, '.', '..' ni backslash."""
    return all(p not in ("", ".", "..") and "\\" not in p for p in rel.split("/"))


def _ruta_segura(ruta: str, node_kind: str) -> str:
    """Convierte un path del laberinto en una ruta relativa de archivo INERTE.

    - Directorios (`/ops/` o `/`) -> `ops/index.html` / `index.html`.
    - Binarios (`node_kind == "binary"`) -> `.bin`.
    - Extensiones ejecutables -> se les añade `.txt` (conserva el nombre cebo).
    """
    rel = ruta.strip("/")
    if ruta.endswith("/") or rel == "":
        base = (rel + "/") if rel else ""
        return base + "index.html"
    if node_kind == "binary":
        return str(PurePosixPath(rel).with_suffix(".bin"))
    if PurePosixPath(rel).suffix.lower() in _EJECUTABLES:
        return rel + ".txt"
    return rel


def _nombre_raiz(rng: random.Random) -> str:
    """Nombre de carpeta raíz aleatorio (distinto por bundle gracias al sufijo hex)."""
    return rng.choice(_POOL_RAIZ) + "-" + "".join(rng.choices("0123456789abcdef", k=6))


# ----------------------------- materialización ------------------------------


def _materializar(gen: LabyrinthGenerator, opts: LabyrinthOptions, rng: random.Random) -> tuple[dict[str, bytes], dict]:
    """Recorre el laberinto desde '/' y devuelve `(decoy, resumen)`.

    `decoy` mapea ruta relativa (sin la carpeta raíz) -> bytes, e incluye el
    `index.html` de cada directorio visitado y los archivos hoja. El recorrido es
    FINITO y su tamaño VARÍA por bundle: profundidad (2–5), ramas por nivel y un
    objetivo de archivos se sortean con el `rng` propio del bundle.
    """
    max_depth = rng.randint(2, 5)
    objetivo_archivos = rng.randint(4, 28)
    max_dirs = rng.randint(3, 10)

    decoy: dict[str, bytes] = {}
    n_archivos = 0
    n_dirs = 0
    prof_max = 0

    cola: list[tuple[str, int]] = [("/", 0)]
    vistos: set[str] = {"/"}

    while cola:
        ruta, prof = cola.pop(0)
        prof_max = max(prof_max, prof)

        # Materializa el index.html del directorio actual.
        rel_dir = _ruta_segura(ruta, "dir")
        if _seguro(rel_dir) and rel_dir not in decoy:
            decoy[rel_dir] = gen.generate(opts, ruta).body
            n_dirs += 1

        enlaces = gen.links_for(opts, ruta)
        hijos_dir = [e for e in enlaces if e.endswith("/")]
        hijos_file = [e for e in enlaces if not e.endswith("/")]
        rng.shuffle(hijos_dir)
        rng.shuffle(hijos_file)

        # Subconjunto aleatorio de archivos de este nivel (densidad variable).
        for enlace in hijos_file[: rng.randint(0, len(hijos_file))]:
            if n_archivos >= objetivo_archivos:
                break
            pagina = gen.generate(opts, enlace)
            rel = _ruta_segura(enlace, pagina.node_kind)
            if not _seguro(rel) or rel in decoy:
                continue
            decoy[rel] = pagina.body
            n_archivos += 1
            prof_max = max(prof_max, _profundidad(enlace))

        # Desciende a un subconjunto aleatorio de subdirectorios (árbol acotado).
        if prof < max_depth and hijos_dir and len(vistos) < max_dirs:
            cuantos = rng.randint(1, min(3, len(hijos_dir)))
            for enlace in hijos_dir[:cuantos]:
                if enlace in vistos or len(vistos) >= max_dirs:
                    continue
                vistos.add(enlace)
                cola.append((enlace, prof + 1))

        if n_archivos >= objetivo_archivos:
            break

    resumen = {"files": n_archivos, "dirs": n_dirs, "depth": prof_max}
    return decoy, resumen


# ----------------------------- empaquetado ----------------------------------


def _escribir_zip(destino: Path, miembros: dict[str, bytes]) -> None:
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as zf:
        for nombre, datos in miembros.items():
            zf.writestr(nombre, datos)


def _escribir_tgz(destino: Path, miembros: dict[str, bytes]) -> None:
    with tarfile.open(destino, "w:gz") as tf:
        for nombre, datos in miembros.items():
            info = tarfile.TarInfo(nombre)
            info.size = len(datos)
            tf.addfile(info, io.BytesIO(datos))


# ----------------------------- meta del bundle ------------------------------


def _uninstall_sh(lista: list[str], root: str) -> str:
    """Script POSIX que borra EXACTAMENTE lo listado en MANIFEST.json."""
    cuerpo = [
        "#!/bin/sh",
        "# Moqesh — desinstalador del bundle.",
        "# Borra EXACTAMENTE los archivos colocados (los del MANIFEST.json).",
        "set -eu",
        'cd "$(dirname "$0")"',
        "for f in \\",
    ]
    cuerpo += [f'  "{ruta}" \\' for ruta in lista]
    cuerpo += [
        "  ; do",
        '  rm -f -- "./$f"',
        "done",
        f'find "./{root}" -type d -empty -delete 2>/dev/null || true',
        'echo "[moqesh] cebo eliminado."',
        "",
    ]
    return "\n".join(cuerpo)


def _snippet_nginx(root: str) -> str:
    return (
        "# Moqesh — sirve el cebo como TEXTO PLANO y SIN ejecución (nginx).\n"
        "# Pega este bloque dentro del server { } de tu sitio y ajusta la ruta.\n"
        "location /lure/ {\n"
        f"    alias /var/www/{root}/;\n"
        "    autoindex off;\n"
        "    default_type text/plain;\n"
        "    types { }                       # anula el mapeo de tipos: todo es texto\n"
        "    add_header X-Content-Type-Options nosniff;\n"
        "    # No añadas fastcgi_pass/proxy_pass aquí: nada debe ejecutarse.\n"
        "    location ~* \\.(php|cgi|pl|py|sh|jsp|aspx)$ { return 403; }\n"
        "}\n"
    )


def _snippet_htaccess() -> str:
    return (
        "# Moqesh — sirve el cebo como TEXTO PLANO y SIN ejecución (Apache).\n"
        "# Copia este archivo como .htaccess dentro de la carpeta del cebo.\n"
        "Options -ExecCGI -Indexes +FollowSymLinks\n"
        "RemoveHandler .php .cgi .pl .py .sh .jsp .aspx .phtml\n"
        "RemoveType .php .cgi .pl .py\n"
        "php_flag engine off\n"
        "SetHandler none\n"
        "ForceType text/plain\n"
        "<IfModule mod_headers.c>\n"
        "    Header set X-Content-Type-Options nosniff\n"
        "</IfModule>\n"
    )


def _snippet_caddy(root: str) -> str:
    return (
        "# Moqesh — sirve el cebo como TEXTO PLANO y SIN ejecución (Caddy).\n"
        "cebo.example.com {\n"
        f"    root * /var/www/{root}\n"
        "    header Content-Type text/plain\n"
        "    header X-Content-Type-Options nosniff\n"
        "    file_server\n"
        "    # Sin php_fastcgi ni reverse_proxy: el contenido solo se sirve, nunca se ejecuta.\n"
        "}\n"
    )


# ----------------------------- API pública ----------------------------------


def generate_for_sensor(db: Session, sensor: Sensor, count: int = 3) -> list[SensorBundle]:
    """Genera `count` bundles para `sensor`, los escribe a disco y los registra.

    Cada bundle tiene seed propio (`uuid4`), estructura y tamaño distintos, nombre
    de carpeta raíz distinto y formato de archivo aleatorio (zip o tar.gz). Devuelve
    las filas `SensorBundle` creadas.
    """
    destino_dir = bundles_dir()
    gen = LabyrinthGenerator()
    filas: list[SensorBundle] = []

    for _ in range(count):
        seed = uuid4().hex
        rng = random.Random(seed)
        opts = LabyrinthOptions(
            seed=seed,
            mode="Template",
            realism_level=sensor.realism_level,
            vocabulary_theme=sensor.vocabulary_theme,
        )

        decoy, resumen = _materializar(gen, opts, rng)

        # Carpeta raíz aleatoria: el contenido del cebo cuelga de ella.
        root = _nombre_raiz(rng)
        miembros: dict[str, bytes] = {}
        lista_manifest: list[str] = []
        for rel, datos in decoy.items():
            arch = f"{root}/{rel}"
            miembros[arch] = datos
            lista_manifest.append(arch)
        lista_manifest.sort()

        # Formato de archivo aleatorio.
        fmt = rng.choice(["zip", "tgz"])
        ext = ".zip" if fmt == "zip" else ".tar.gz"
        filename = f"{sensor.id}-{seed[:8]}{ext}"

        manifest = {
            "sensor_id": sensor.id,
            "seed": seed,
            "created_at": datetime.now(UTC).isoformat(),
            "root": root,
            "archive_format": fmt,
            "summary": resumen,
            "files": lista_manifest,
        }
        miembros["MANIFEST.json"] = json.dumps(manifest, indent=2).encode()
        miembros["uninstall.sh"] = _uninstall_sh(lista_manifest, root).encode()
        miembros["serve-config/nginx.conf"] = _snippet_nginx(root).encode()
        miembros["serve-config/.htaccess"] = _snippet_htaccess().encode()
        miembros["serve-config/Caddyfile"] = _snippet_caddy(root).encode()

        destino = destino_dir / filename
        if fmt == "zip":
            _escribir_zip(destino, miembros)
        else:
            _escribir_tgz(destino, miembros)

        fila = SensorBundle(
            sensor_id=sensor.id,
            filename=filename,
            seed=seed,
            archive_format=fmt,
            structure_summary=json.dumps(resumen),
        )
        db.add(fila)
        filas.append(fila)

    db.commit()
    return filas
