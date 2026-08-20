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
                "adapter": "search",
                "canonical": {"path": "search"},
            },
            {
                "id": "json-get",
                "verb": "get",
                "adapter": "json get",
                "canonical": {"path": "json", "operations": ["get", "keys"]},
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
    assert "OFFLINE search --args" in result["error"]
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
