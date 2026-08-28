import json

from tools import lucid_outage


def write(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def registry():
    return {
        "source_hash": f"sha256:{'a' * 64}",
        "facades": [
            {
                "id": "search",
                "verb": "get",
                "adapter": "lucid get",
                "outage_tier": "mcp-offline",
                "canonical": {"path": "search"},
            },
            {
                "id": "json-get",
                "verb": "get",
                "adapter": "json get",
                "outage_tier": "mcp-offline",
                "canonical": {"path": "json", "operations": ["get", "keys"]},
            },
            {
                "id": "morph",
                "verb": "morph",
                "adapter": "morph",
                "outage_tier": "mcp-online",
                "canonical": {"codebook": "lucid"},
            },
        ],
    }


def revival(active=True):
    return {
        "schema": "run-mcp-revival/1",
        "node": "butler:port:mcp",
        "owner": "RUN",
        "eta": "⏳ ETA T-10s" if active else None,
        "offline_facades_active": active,
        "observed_epoch_ms": 1_000,
    }


def test_active_outage_projects_exact_search_fallback(monkeypatch, tmp_path):
    offline = tmp_path / "offline.json"
    state = tmp_path / "revival.json"
    write(offline, registry())
    write(state, revival())
    monkeypatch.setattr(lucid_outage, "_OFFLINE", offline)
    monkeypatch.setattr(lucid_outage, "_REVIVAL", state)

    arguments = {
        "path": "search",
        "query": {"terms": ["needle"]},
        "scope": "this",
    }
    result = lucid_outage.project_lucid_transport_outage("get", arguments)

    assert result is not None
    assert set(result) == {"error"}
    assert result["error"].splitlines() == [
        "⚠️ LUCID · get · transport · offline-fallback",
        "🔎 mcp-unavailable · ⏳ ETA T-10s",
        "➡️ lucid get search --query '{\"terms\":[\"needle\"]}'",
    ]
    assert "--args" not in result["error"]
    assert "--scope" not in result["error"]
    assert "RETIRE" not in result["error"]


def test_green_or_unregistered_noun_never_suggests_fallback(monkeypatch, tmp_path):
    offline = tmp_path / "offline.json"
    state = tmp_path / "revival.json"
    write(offline, registry())
    write(state, revival(active=False))
    monkeypatch.setattr(lucid_outage, "_OFFLINE", offline)
    monkeypatch.setattr(lucid_outage, "_REVIVAL", state)

    assert lucid_outage.project_lucid_transport_outage("get", {"path": "search"}) is None

    write(state, revival(active=True))
    assert lucid_outage.project_lucid_transport_outage("steer", {"action": "pause"}) is None
    assert lucid_outage.project_lucid_transport_outage("morph", {"codebook": "lucid"}) is None


def test_empty_error_uses_run_attested_eta_and_offline_facade(monkeypatch, tmp_path):
    offline = tmp_path / "offline.json"
    state = tmp_path / "revival.json"
    write(offline, registry())
    write(state, revival())
    monkeypatch.setattr(lucid_outage, "_OFFLINE", offline)
    monkeypatch.setattr(lucid_outage, "_REVIVAL", state)

    result = lucid_outage.project_lucid_failure(
        "get",
        {"path": "search", "query": {"terms": ["needle"]}, "scope": "this"},
        "isError response omitted content and structuredContent",
        code="outcome-envelope-invalid",
    )

    assert set(result) == {"error"}
    assert "⏳ ETA T-10s" in result["error"]
    assert "➡️ lucid get search --query" in result["error"]
    assert "--args" not in result["error"]
    assert "--scope" not in result["error"]


def test_unattested_empty_error_uses_canonical_outcome_code(monkeypatch, tmp_path):
    monkeypatch.setattr(lucid_outage, "_OFFLINE", tmp_path / "absent-offline.json")
    monkeypatch.setattr(lucid_outage, "_REVIVAL", tmp_path / "absent-revival.json")

    result = lucid_outage.project_lucid_failure(
        "dispatch",
        {"operation": "test", "area": "butler"},
        "isError response omitted content and structuredContent",
        code="outcome-envelope-invalid",
    )

    assert set(result) == {"error"}
    assert result["error"].startswith(
        "🔴 🧠 · ⚡ DISPATCH · 🎛️ OUTCOME-ENVELOPE-INVALID"
    )
    assert "MCP tool returned an error" not in result["error"]
    assert "➡️" not in result["error"]
    assert "?" not in result["error"]


def test_failure_gestalt_is_stable_for_the_same_evidence(monkeypatch, tmp_path):
    monkeypatch.setattr(lucid_outage, "_OFFLINE", tmp_path / "absent-offline.json")
    monkeypatch.setattr(lucid_outage, "_REVIVAL", tmp_path / "absent-revival.json")

    first = lucid_outage.project_lucid_failure("get", {"path": "search"}, "deadline expired")
    second = lucid_outage.project_lucid_failure("get", {"path": "search"}, "deadline expired")

    assert first == second
    assert "structuredContent" not in first


def test_canonical_semantic_refusal_is_transparent_passthrough(monkeypatch, tmp_path):
    monkeypatch.setattr(lucid_outage, "_OFFLINE", tmp_path / "absent-offline.json")
    monkeypatch.setattr(lucid_outage, "_REVIVAL", tmp_path / "absent-revival.json")
    refusal = (
        "🔴 🧠 · ⚡ SET · 🎯 ROLE-SESSION · 🎛️ RECOVER · "
        "🔎 ROLE-SUPERSEDED: role binding settlement outcome unknown · "
        "➡️ 🧠 · ⚡ GET · 🎯 ROLE-SESSION · 🔎 Inspect settlement before retrying"
    )

    result = lucid_outage.project_lucid_failure(
        "set",
        {"path": "role-session", "value": {"action": "recover"}},
        refusal,
        code="outcome-envelope-invalid",
    )

    assert result == {"error": refusal}


def test_server_supplied_ugui_error_is_not_forwarded_through_model_context():
    structured = {"schema": "lucid-ugui-response/1", "state": "malformed-args"}
    result = lucid_outage.project_lucid_failure(
        "dispatch",
        {},
        "typed refusal",
        structured=structured,
        code="outcome-envelope-invalid",
    )
    assert set(result) == {"error"}
    assert "structuredContent" not in result
    assert result["error"].startswith(
        "🔴 🧠 · ⚡ DISPATCH · 🎛️ OUTCOME-ENVELOPE-INVALID"
    )
