"""Motor coherente + adaptativo (Fase 1).

Verifica el giro de diseño: la API es FINITA y COHERENTE (ya no infinita ni con un
`total` que cambia por página), y la intensidad adaptativa solo añade VOLUMEN de cebo
coherente — nunca incoherencia, nunca infinito (salvo el opt-in de quema bruta).
"""

import json
import math

from moqesh import vocabulary as vocab
from moqesh.detection import intensity_for
from moqesh.labyrinth import LabyrinthGenerator, LabyrinthOptions, effective_api_path


def _collection(gen: LabyrinthGenerator, opts: LabyrinthOptions) -> str:
    """Una colección de API que EXISTE en este deployment (recurso real del tema)."""
    return f"/api/v2/{vocab.resources(gen.global_ctx(opts).theme)[0]}"


def _body(gen: LabyrinthGenerator, opts: LabyrinthOptions, path: str, intensity: int = 0) -> dict:
    return json.loads(gen.generate(opts, path, intensity).body)


def test_api_total_stable_per_collection():
    # El delator principal era que `total` se re-sorteaba por página: aquí es estable.
    opts = LabyrinthOptions(seed="deploy-123")
    gen = LabyrinthGenerator()
    coll = _collection(gen, opts)
    t1 = _body(gen, opts, coll)["total"]
    t2 = _body(gen, opts, f"{coll}/page/2")["total"]
    t3 = _body(gen, opts, f"{coll}/page/7")["total"]
    assert t1 == t2 == t3


def test_api_pagination_terminates():
    # Un sitio real es finito: la paginación TERMINA (next=null en la última página).
    opts = LabyrinthOptions(seed="deploy-123")
    gen = LabyrinthGenerator()
    coll = _collection(gen, opts)
    last_page = _body(gen, opts, coll)["total_pages"]
    path, pages = coll, 1
    while True:
        nxt = gen.links_for(opts, path)
        if not nxt:
            break
        path = nxt[0]
        pages += 1
        assert pages <= last_page, "la API paginó más allá de la última página"
    assert pages == last_page
    assert _body(gen, opts, path)["links"]["next"] is None


def test_api_page_out_of_range_is_404():
    opts = LabyrinthOptions(seed="deploy-123")
    gen = LabyrinthGenerator()
    coll = _collection(gen, opts)
    assert gen.is_reachable(opts, coll)  # página 1 existe
    assert not gen.is_reachable(opts, f"{coll}/page/999999")  # muy fuera de rango -> 404
    assert not gen.is_reachable(opts, "/api/v2/nonexistent-xyz")  # colección inexistente -> 404


def test_record_coherent_across_pages_and_endpoints():
    # El mismo id da los mismos campos en la lista y en /colección/<id> (coherencia verificable).
    opts = LabyrinthOptions(seed="deploy-123")
    gen = LabyrinthGenerator()
    coll = _collection(gen, opts)
    rec = _body(gen, opts, coll)["data"][0]
    rid = rec["id"]
    single = _body(gen, opts, f"{coll}/{rid}")
    assert single == rec
    assert gen.is_reachable(opts, f"{coll}/{rid}")


def test_record_out_of_range_is_404():
    opts = LabyrinthOptions(seed="deploy-123")
    gen = LabyrinthGenerator()
    coll = _collection(gen, opts)
    total = _body(gen, opts, coll)["total"]
    assert gen.is_reachable(opts, f"{coll}/{total}")
    assert not gen.is_reachable(opts, f"{coll}/{total + 1}")


def test_query_pagination_is_canonicalized():
    # ?page=N y /page/N devuelven lo MISMO (si cambiar ?page= no cambiara nada, sería delator).
    coll = "/api/v2/tenant"
    assert effective_api_path(coll, "page=2") == f"{coll}/page/2"
    assert effective_api_path(coll, "sort=x&page=3") == f"{coll}/page/3"
    assert effective_api_path(coll, None) == coll
    assert effective_api_path("/docs/README.md", "page=2") == "/docs/README.md"  # no-API intacto


def test_intensity_grows_coherent_bait_but_not_api():
    opts = LabyrinthOptions(seed="deploy-123")
    gen = LabyrinthGenerator()
    coll = _collection(gen, opts)
    # El contenido de la API NO cambia con la intensidad (coherencia: un registro es un registro).
    assert gen.generate(opts, coll, 0).body == gen.generate(opts, coll, 3).body
    # Pero la prosa/historial coherente SÍ crece (más que leer = más tokens del agente).
    doc0 = len(gen.generate(opts, "/ops/CHANGELOG.md", 0).body)
    doc3 = len(gen.generate(opts, "/ops/CHANGELOG.md", 3).body)
    assert doc3 > doc0
    readme0 = len(gen.generate(opts, "/ops/README.md", 0).body)
    readme3 = len(gen.generate(opts, "/ops/README.md", 3).body)
    assert readme3 > readme0


def test_intensity_for_thresholds():
    class _S:
        def __init__(self, score):
            self.ai_probability_score = score

    assert intensity_for(None) == 0
    assert intensity_for(_S(0.0)) == 0
    assert intensity_for(_S(0.39)) == 0
    assert intensity_for(_S(0.4)) == 1
    assert intensity_for(_S(0.6)) == 2
    assert intensity_for(_S(0.85)) == 3


def test_allow_infinite_opt_in_reopens_pagination():
    # Opt-in de quema bruta: a intensidad máxima la API vuelve a ser infinita (rompe el sigilo).
    opts = LabyrinthOptions(seed="deploy-123", allow_infinite=True)
    gen = LabyrinthGenerator()
    coll = _collection(gen, opts)
    far = f"{coll}/page/999999"
    assert gen.is_reachable(opts, far, intensity=3)  # cualquier página es alcanzable
    assert gen.links_for(opts, far, intensity=3)  # y siempre hay 'next'
    # Sin el opt-in, la misma página lejana da 404.
    plain = LabyrinthOptions(seed="deploy-123")
    assert not gen.is_reachable(plain, far, intensity=3)


def test_api_response_is_valid_json():
    opts = LabyrinthOptions(seed="deploy-A", realism_level=4)
    gen = LabyrinthGenerator()
    coll = _collection(gen, opts)
    body = _body(gen, opts, coll)
    assert body["page"] == 1
    assert isinstance(body["data"], list)
    assert body["links"]["prev"] is None
    assert set(body) >= {"page", "per_page", "total", "total_pages", "data", "links"}
    # Coherencia interna: el nº de registros de la página cuadra con total/per_page.
    expected = min(body["per_page"], body["total"])
    assert len(body["data"]) == expected
    assert body["total_pages"] == max(1, math.ceil(body["total"] / body["per_page"]))
