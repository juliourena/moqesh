"""Motor de escenarios CTF: gates de credenciales, rutas ocultas, forge."""

from moqesh.scenarios import (
    BUILTIN_PACKS,
    ScCred,
    ScenarioContext,
    ScenarioData,
    ScenarioEngine,
    ScenarioRequest,
    ScNode,
)


def _corp_data() -> ScenarioData:
    pack = BUILTIN_PACKS["corp-breach"]()
    nodes = [
        ScNode(
            id=i,
            path=n["path"],
            visibility=n.get("visibility", "linked"),
            kind=n.get("kind", "file"),
            content_type=n.get("contentType", "text/plain"),
            body_template=n.get("bodyTemplate", ""),
            requires_credential_key=n.get("requiresCredentialKey"),
            grants_credential_keys=n.get("grantsCredentialKeys"),
            hinted_by_paths=n.get("hintedByPaths"),
            stage=n.get("stage", 0),
            binary_kind=n.get("binaryKind", "none"),
            binary_secret=n.get("binarySecret", ""),
        )
        for i, n in enumerate(pack["nodes"], 1)
    ]
    creds = [
        ScCred(
            key=c["key"],
            username=c.get("username"),
            secret=c.get("secret", ""),
            kind=c.get("kind", "bearer"),
            found_in_path=c.get("foundInPath"),
            usable_at_path=c.get("usableAtPath"),
        )
        for c in pack["credentials"]
    ]
    return ScenarioData(scenario_id=1, name=pack["name"], nodes=nodes, credentials=creds)


def test_gate_denies_without_credential():
    data, engine = _corp_data(), ScenarioEngine()
    ctx = ScenarioContext(seed="seed-x", brand="Acme Labs")
    res = engine.resolve(data, ctx, ScenarioRequest(path="/api/internal/vault"))
    assert res is not None and res.status == 401 and res.failed_auth


def test_gate_allows_with_valid_credential_and_flags_reuse():
    data, engine = _corp_data(), ScenarioEngine()
    ctx = ScenarioContext(seed="seed-x", brand="Acme Labs")
    bearer = ctx.secret_of(data.cred("svc_bearer"))
    res = engine.resolve(
        data, ctx, ScenarioRequest(path="/api/internal/vault", headers={"Authorization": f"Bearer {bearer}"})
    )
    assert res is not None and res.status == 200
    assert res.used_planted_cred_key == "svc_bearer"  # señal de credential_reuse
    assert b"portal-secrets" in res.body


def test_hidden_node_not_resolved_as_none_but_hinted():
    data, engine = _corp_data(), ScenarioEngine()
    # /backup/ es oculto pero existe como nodo: se sirve; la pista viene de /robots.txt.
    assert "/backup/" in engine.hints_from(data, "/robots.txt")


def test_forge_dll_served_as_binary():
    data, engine = _corp_data(), ScenarioEngine()
    ctx = ScenarioContext(seed="seed-x", brand="Acme Labs")
    res = engine.resolve(data, ctx, ScenarioRequest(path="/backup/Portal.dll"))
    assert res is not None and res.node_kind == "binary"
    assert res.attachment_name == "Portal.dll"
    assert res.content_type == "application/octet-stream" and len(res.body) > 1024


def test_unknown_path_returns_none():
    data, engine = _corp_data(), ScenarioEngine()
    ctx = ScenarioContext(seed="seed-x", brand="Acme Labs")
    assert engine.resolve(data, ctx, ScenarioRequest(path="/nope/nothing")) is None
