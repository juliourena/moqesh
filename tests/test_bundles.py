"""Tests del generador de bundles estáticos (modo agentless).

Verifica que `generate_for_sensor` crea los bundles pedidos, que los archivos
existen, que la estructura VARÍA entre bundles, que nada colocado es ejecutable y
que el MANIFEST viaja dentro del archivo. La DB la aísla el conftest.
"""

import json
import tarfile
import zipfile
from uuid import uuid4

from moqesh.bundles import bundles_dir, generate_for_sensor
from moqesh.db import SessionLocal, init_db
from moqesh.models import Sensor

# Extensiones que un web server podría ejecutar: ninguna debe aparecer en el cebo.
_EJECUTABLES = (".php", ".sh", ".cgi", ".aspx", ".jsp", ".pl", ".py", ".phtml")


def _leer_manifest(ruta) -> tuple[dict, list[str]]:
    """Abre el bundle (zip o tar.gz) y devuelve (manifest, nombres de miembros)."""
    if ruta.name.endswith(".zip"):
        with zipfile.ZipFile(ruta) as zf:
            nombres = zf.namelist()
            assert "MANIFEST.json" in nombres
            return json.loads(zf.read("MANIFEST.json")), nombres
    with tarfile.open(ruta, "r:gz") as tf:
        nombres = tf.getnames()
        assert "MANIFEST.json" in nombres
        extraido = tf.extractfile("MANIFEST.json")
        assert extraido is not None
        return json.loads(extraido.read()), nombres


def test_generate_for_sensor_crea_bundles_variados_e_inertes():
    init_db()
    with SessionLocal() as db:
        sensor = Sensor(
            name="agentless-edge",
            kind="agentless",
            realism_level=4,
            vocabulary_theme="devops",
            base_path="/lure",
            key_id=uuid4().hex[:16],  # único: evita chocar con el sensor 'local' sembrado
        )
        db.add(sensor)
        db.commit()
        db.refresh(sensor)

        filas = generate_for_sensor(db, sensor, count=3)

        # Se crean exactamente 3 filas persistidas.
        assert len(filas) == 3
        assert all(f.id is not None and f.sensor_id == sensor.id for f in filas)

        manifests: list[dict] = []
        for fila in filas:
            ruta = bundles_dir() / fila.filename
            # El archivo existe en disco y no está vacío.
            assert ruta.exists() and ruta.stat().st_size > 0
            assert fila.archive_format in ("zip", "tgz")

            manifest, _nombres = _leer_manifest(ruta)
            manifests.append(manifest)

            # El MANIFEST lleva seed y fecha (auditoría/uninstall).
            assert manifest["seed"] == fila.seed
            assert manifest["created_at"]
            assert manifest["files"], "el bundle debería colocar archivos"

            # Ningún archivo colocado tiene extensión ejecutable.
            for archivo in manifest["files"]:
                assert not archivo.lower().endswith(_EJECUTABLES), archivo

        # Al menos dos bundles difieren en estructura (rutas relativas a la raíz).
        relativos = [frozenset(p.split("/", 1)[1] for p in m["files"]) for m in manifests]
        assert len(set(relativos)) >= 2, "los bundles no deberían compartir estructura"
