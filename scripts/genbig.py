#!/usr/bin/env python3
"""Genera un árbol de ficheros de texto GRANDES con texto real (para el World de Moqesh).

Rellena directorios tipo `/data` o `/files/<subdir>` con ficheros voluminosos formados por
párrafos reales de libros de dominio público (Project Gutenberg, cacheados en ~/.cache/genbig)
o de tu propio corpus. Servidos por el World con `"autoindex": true`, forman un "directorio
abierto" finito pero pesado que quema los tokens de un agente SIN el delator del contenido
generado/templado (es texto real).

Uso típico con Moqesh (el World vive junto a la DB, p.ej. /app/data/world):
  # /data con 50 ficheros de 10 MiB
  python3 scripts/genbig.py /app/data/world/sites/data --files 50 --size 10M --lang es
  # /files/2023 /files/2024 /files/2025 (subdirs numéricos)
  python3 scripts/genbig.py /app/data/world/sites/files --files 60 --size 10M \
      --subdirs 3 --subdir-prefix "" --subdir-width 4 --subdir-start 2023
Luego añade el mount al manifest.json del World y reinicia:
  {"prefix": "/data", "dir": "sites/data", "autoindex": true}

Otros ejemplos:
  python3 scripts/genbig.py salida --files 20 --size 5G --lang en
  python3 scripts/genbig.py salida --files 10 --size 2G --corpus mis_textos.txt --unique
"""
import argparse
import os
import random
import re
import sys
import time
import urllib.request
from concurrent.futures import ProcessPoolExecutor, as_completed

BLOCK = 1 << 20  # 1 MiB por bloque
POOL_BLOCKS = 64  # bloques pregenerados por worker
CACHE = os.path.expanduser("~/.cache/genbig")

BOOKS = {
    # Crimen y castigo, Los miserables 2, Don Quijote, Cuentos de amor, Insolación y Morriña,
    # La Odisea, Los argonautas, La Divina Comedia, El paraíso perdido, José
    "es": [61851, 78068, 2000, 55514, 52597, 58221, 25640, 57303, 67092, 27738],
    # Pride and Prejudice, Moby Dick, Frankenstein, Alice, Sherlock Holmes, Dracula,
    # Crime and Punishment, Middlemarch, Little Women, Jane Eyre, Dorian Gray, Monte Cristo, Two Cities
    "en": [1342, 2701, 84, 11, 1661, 345, 2554, 145, 37106, 1260, 174, 1184, 98],
}


def parse_size(s):
    s = s.strip().upper().rstrip("B")
    mult = {"K": 1 << 10, "M": 1 << 20, "G": 1 << 30, "T": 1 << 40}
    if s and s[-1] in mult:
        return int(float(s[:-1]) * mult[s[-1]])
    return int(s)


def download_books(lang):
    """Descarga los libros (si no están en caché) y devuelve sus rutas."""
    os.makedirs(CACHE, exist_ok=True)
    langs = ["es", "en"] if lang == "mix" else [lang]
    paths = []
    for lng in langs:
        for bid in BOOKS[lng]:
            path = os.path.join(CACHE, f"pg{bid}.txt")
            if not os.path.exists(path):
                url = f"https://www.gutenberg.org/cache/epub/{bid}/pg{bid}.txt"
                print(f"Descargando {url}")
                try:
                    with urllib.request.urlopen(url, timeout=60) as r, open(path + ".part", "wb") as f:
                        f.write(r.read())
                    os.replace(path + ".part", path)
                except Exception as e:
                    print(f"  aviso: no se pudo descargar ({e}), se omite")
                    continue
            paths.append(path)
    if not paths:
        sys.exit("No se pudo descargar ningún libro.")
    return paths


def load_paragraphs(paths):
    """Lee los textos, quita la cabecera/licencia de Gutenberg y une las líneas de cada párrafo."""
    paras = []
    for p in paths:
        with open(p, encoding="utf-8", errors="ignore") as f:
            text = f.read().replace("\r\n", "\n")
        start = re.search(r"\*\*\* ?START OF.*?\*\*\*", text)
        end = re.search(r"\*\*\* ?END OF", text)
        if start:
            text = text[start.end() : end.start() if end else None]
        for para in re.split(r"\n\s*\n", text):
            para = " ".join(para.split())
            # descartar títulos, números de capítulo, líneas cortas y notas del transcriptor
            low = para.lower()
            if len(para) >= 80 and not any(k in low for k in ("gutenberg", "http", "e-text", "ebook")):
                paras.append(para)
    return paras


def make_block(rng, paras):
    out, size = [], 0
    while size < BLOCK:
        p = rng.choice(paras) + "\n\n"
        out.append(p)
        size += len(p.encode())
    return "".join(out).encode()


def write_file(path, size, sources, seed, unique):
    rng = random.Random(seed)
    paras = load_paragraphs(sources)
    pool = None if unique else [make_block(rng, paras) for _ in range(POOL_BLOCKS)]
    written = 0
    with open(path, "wb", buffering=8 * BLOCK) as f:
        while written < size:
            blk = make_block(rng, paras) if unique else rng.choice(pool)
            blk = blk[: size - written]
            f.write(blk)
            written += len(blk)
    return path, written


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("outdir")
    ap.add_argument("--files", type=int, default=10, help="número de archivos")
    ap.add_argument("--size", default="100M", help="tamaño por archivo (K/M/G/T)")
    ap.add_argument("--lang", choices=["es", "en", "mix"], default="es", help="idioma del texto")
    ap.add_argument("--corpus", nargs="+", help="usar tus propios archivos .txt en vez de Gutenberg")
    ap.add_argument("--unique", action="store_true", help="generar cada bloque nuevo (menos repetición, más lento)")
    ap.add_argument("--subdirs", type=int, default=0, help="repartir en N subdirectorios")
    ap.add_argument("--subdir-prefix", default="dir_", help="prefijo de subdirectorio ('' para /0023, /2023…)")
    ap.add_argument("--subdir-width", type=int, default=4, help="dígitos del índice de subdirectorio")
    ap.add_argument("--subdir-start", type=int, default=0, help="índice inicial de subdirectorio (p.ej. 2023)")
    ap.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 1))
    ap.add_argument("--seed", type=int, default=None)
    a = ap.parse_args()

    size = parse_size(a.size)
    total = size * a.files
    os.makedirs(a.outdir, exist_ok=True)
    st = os.statvfs(a.outdir)
    free = st.f_bavail * st.f_frsize
    if total > free:
        sys.exit(f"Espacio insuficiente: se necesitan {total / 2**30:.1f} GiB, hay {free / 2**30:.1f} GiB")

    sources = [os.path.abspath(c) for c in a.corpus] if a.corpus else download_books(a.lang)
    if not load_paragraphs(sources):
        sys.exit("Los textos fuente no tienen párrafos utilizables.")

    base_seed = a.seed if a.seed is not None else random.randrange(2**32)
    jobs = []
    for i in range(a.files):
        if a.subdirs:
            n = a.subdir_start + (i % a.subdirs)
            d = os.path.join(a.outdir, f"{a.subdir_prefix}{n:0{a.subdir_width}d}")
        else:
            d = a.outdir
        os.makedirs(d, exist_ok=True)
        jobs.append((os.path.join(d, f"file_{i:06d}.txt"), size, sources, base_seed + i, a.unique))

    print(f"Generando {a.files} archivos x {a.size} = {total / 2**30:.2f} GiB con {a.workers} workers...")
    t0, done_bytes = time.time(), 0
    with ProcessPoolExecutor(a.workers) as ex:
        futs = [ex.submit(write_file, *j) for j in jobs]
        for n, fut in enumerate(as_completed(futs), 1):
            _, w = fut.result()
            done_bytes += w
            el = time.time() - t0
            print(
                f"\r[{n}/{a.files}] {done_bytes / 2**30:.2f} GiB  "
                f"{done_bytes / 2**20 / max(el, 1e-9):.0f} MiB/s",
                end="",
                flush=True,
            )
    print(f"\nListo en {time.time() - t0:.1f}s -> {a.outdir}")


if __name__ == "__main__":
    main()
