"""Perfiles de sitio seleccionables (Fase 2)."""

from moqesh.labyrinth import LabyrinthGenerator, LabyrinthOptions
from moqesh.profiles import available, load_builtin


def test_builtins_available_and_loadable():
    names = set(available())
    assert {"saas", "corp", "ecommerce", "nonprofit"} <= names
    for n in names:
        p = load_builtin(n)
        assert isinstance(p, dict)
        assert p.get("api_resources"), f"{n} sin api_resources"


def test_load_builtin_rejects_bad_names():
    assert load_builtin("") is None
    assert load_builtin("../config") is None
    assert load_builtin("a/b") is None
    assert load_builtin(".hidden") is None
    assert load_builtin("nope-not-real") is None


def test_profile_api_collections_reachable_others_404():
    gen = LabyrinthGenerator()
    opts = LabyrinthOptions(seed="deploy-1", profile=load_builtin("saas"))
    assert gen.is_reachable(opts, "/api/v2/tenant")  # recurso del perfil
    assert gen.is_reachable(opts, "/api/v2/invoice")
    assert not gen.is_reachable(opts, "/api/v2/handbook")  # recurso de OTRO tema -> 404
    assert not gen.is_reachable(opts, "/api/v2/zzz")


def test_profile_drives_directory_vocabulary():
    gen = LabyrinthGenerator()
    prof = load_builtin("corp")
    opts = LabyrinthOptions(seed="deploy-1", profile=prof)
    g = gen.global_ctx(opts)
    pool = LabyrinthGenerator._dir_pool(opts, g)
    assert any(w in pool for w in prof["vocabulary"])


def test_profile_theme_and_banner():
    gen = LabyrinthGenerator()
    opts = LabyrinthOptions(seed="deploy-1", profile=load_builtin("ecommerce"))
    g = gen.global_ctx(opts)
    assert g.theme == "ecommerce"
    assert g.banner == "nginx/1.25.3"


def test_profile_record_name_matches_collection():
    # El nombre del registro deriva de la colección del perfil (coherencia visible).
    import json

    gen = LabyrinthGenerator()
    opts = LabyrinthOptions(seed="deploy-1", profile=load_builtin("nonprofit"))
    body = json.loads(gen.generate(opts, "/api/v1/member").body)
    assert body["data"][0]["name"].startswith("member-")
