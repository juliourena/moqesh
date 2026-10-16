"""Simula un agente IA recorriendo el laberinto (sigue enlaces, baja en profundidad,
lee README y luego el .env, descarga binarios). Usa un UA de bot para disparar
reglas conductuales. No es parte del producto: es el arnes de la prueba e2e.
"""
import os
import re
import time

import httpx

BASE = os.environ.get("MOQESH_BASE", "http://localhost:8080")
UA = "python-requests/2.31 (langchain; AutoGPT)"

LINK_RE = re.compile(r'href="([^"]+)"')


def links(html: str, base_path: str) -> list[str]:
    out = []
    for href in LINK_RE.findall(html):
        if href.startswith("../") or href.startswith("http"):
            continue
        out.append(base_path.rstrip("/") + "/" + href if base_path != "/" else "/" + href)
    return out


def main() -> None:
    client = httpx.Client(headers={"User-Agent": UA, "X-Agent-Model": "openrouter/anthropic/claude-haiku"},
                          timeout=10)
    frontier = ["/"]
    seen = set()
    hits = 0
    # BFS/DFS mezclado: sigue casi todos los enlaces (fan-out exhaustivo) y baja hondo.
    while frontier and hits < 40:
        path = frontier.pop(0)
        if path in seen:
            continue
        seen.add(path)
        r = client.get(BASE + path)
        hits += 1
        time.sleep(0.4)  # intervalo regular -> dispara timing_analysis
        ct = r.headers.get("content-type", "")
        if "html" in ct:
            found = links(r.text, path)
            # Sigue TODO lo listado (comportamiento de agente, no de humano).
            frontier.extend(found)
        print(f"{r.status_code}  {path:45.45}  {len(r.content):>7}b  {ct.split(';')[0]}")
    print(f"\nTotal requests del agente simulado: {hits}")


if __name__ == "__main__":
    main()
