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

    arguments = {"path": "search", "query": {"terms": ["needle"]}}
    result = lucid_outage.project_lucid_transport_outage("get", arguments)

    assert result is not None
    assert result["structuredContent"]["state"] == "mcp-unavailable"
    assert "⏳ ETA T-10s" in result["error"]
    assert "OFFLINE lucid get --args" in result["error"]
    assert "RETIRE port:mcp fresh 🟢" in result["error"]


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
        {"path": "search", "query": {"terms": ["needle"]}},
        "isError response omitted content and structuredContent",
        code="outcome-envelope-invalid",
    )

    assert result["structuredContent"]["state"] == "mcp-unavailable"
    assert "⏳ ETA T-10s" in result["error"]
    assert "OFFLINE lucid get --args" in result["error"]


def test_unattested_empty_error_uses_canonical_outcome_code(monkeypatch, tmp_path):
    monkeypatch.setattr(lucid_outage, "_OFFLINE", tmp_path / "absent-offline.json")
    monkeypatch.setattr(lucid_outage, "_REVIVAL", tmp_path / "absent-revival.json")

    result = lucid_outage.project_lucid_failure(
        "dispatch",
        {"operation": "test", "area": "butler"},
        "isError response omitted content and structuredContent",
        code="outcome-envelope-invalid",
    )

    assert result["structuredContent"]["state"] == "outcome-envelope-invalid"
    assert result["structuredContent"]["schema"] == "lucid-ugui-response/1"
    assert "MCP tool returned an error" not in result["error"]
    assert "NEXT lucid dispatch --help" in result["error"]
    document = result["structuredContent"]
    assert [section["id"] for section in document["sections"]] == ["lucid.error.status"]
    assert document["provenance"]["parentHash"].startswith("sha256:")
    assert document["provenance"]["observedEpoch"] > 0
    assert document["actions"] == [
        {
            "id": "lucid.error.help.dispatch",
            "type": "button",
            "label": "dispatch --help",
            "action": "lucid.help.verb",
            "value": "dispatch",
            "intent": {"verb": "dispatch", "arguments": {}},
            "handlers": [{"gesture": "tap", "handler": "lucid.help.verb"}],
            "width": 12,
        }
    ]
    receipt = document["receipt"]["action_provenance"]
    assert len(receipt) == 1
    assert receipt[0]["id"] == "lucid.error.help.dispatch"
    assert receipt[0]["state"] == "AVAILABLE"
    assert receipt[0]["provenance_hash"] == document["provenance"]["parentHash"]
    assert receipt[0]["content_id"] == document["provenance"]["parentHash"]


def test_failure_help_action_provenance_is_stable_for_the_same_evidence(monkeypatch, tmp_path):
    monkeypatch.setattr(lucid_outage, "_OFFLINE", tmp_path / "absent-offline.json")
    monkeypatch.setattr(lucid_outage, "_REVIVAL", tmp_path / "absent-revival.json")
    monkeypatch.setattr(lucid_outage.time, "time", lambda: 1234)

    first = lucid_outage.project_lucid_failure("get", {"path": "search"}, "deadline expired")
    second = lucid_outage.project_lucid_failure("get", {"path": "search"}, "deadline expired")

    first_document = first["structuredContent"]
    second_document = second["structuredContent"]
    assert first_document["provenance"] == second_document["provenance"]
    assert first_document["provenance"]["observedEpoch"] == 1234
    assert first_document["receipt"]["action_provenance"][0]["provenance_hash"] == first_document["provenance"]["parentHash"]


def test_server_supplied_ugui_error_is_preserved():
    structured = {"schema": "lucid-ugui-response/1", "state": "malformed-args"}
    result = lucid_outage.project_lucid_failure(
        "dispatch",
        {},
        "typed refusal",
        structured=structured,
        code="outcome-envelope-invalid",
    )
    assert result == {"error": "typed refusal", "structuredContent": structured}
