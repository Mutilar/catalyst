from agent.generated.ae_glyphs import IDENTITY_LUCID
from agent.generated.ae_glyphs import IDENTITY_RUN
from agent.generated.ae_glyphs import DELIMITER_SEGMENT
from agent.generated.ae_glyphs import RELATION_ACTION
from agent.generated.ae_glyphs import RELATION_DATUM
from agent.generated.ae_glyphs import SIGNAL_WARNING
from agent.generated.ae_glyphs import SIGNAL_RED
from agent.generated.ae_glyphs import SIGNAL_GREEN
from agent.generated.ae_glyphs import SIGNAL_PENDING
import json
from pathlib import Path

import pytest

from tools import lucid_outage

from hermes_gestalt import canonical_stream, parse_stream, semantic_action


_GESTALT_ROOT = Path(__file__).parents[3]
_GESTALT_CONFORMANCE = json.loads(
    (_GESTALT_ROOT / "quine/tests/fixtures/gestalt-conformance.json").read_text(encoding="utf-8")
)


def _render_conformance_stream(stream):
    fields = dict(stream)
    if fields.get("service", "default") is None:
        fields.pop("service")
        fields["without_identity"] = True
    return canonical_stream(_GESTALT_ROOT, **fields)


def _conformance_fields(stream):
    fields = {key: value for key, value in stream.items() if key not in {"intents", "cli", "without_identity"}}
    fields["continuations"] = [
        {"kind": "service", "value": value} if isinstance(value, str) else value
        for value in fields["continuations"]
    ]
    for field, kind in (("intents", "intent"), ("cli", "cli")):
        assert stream[field] == [entry["value"] for entry in fields["continuations"] if entry["kind"] == kind]
    return fields


@pytest.mark.parametrize("case", _GESTALT_CONFORMANCE["positive"], ids=lambda case: case["id"])
def test_gestalt_conformance_round_trip(case):
    rendered = _render_conformance_stream(case.get("render", case["stream"]))
    assert rendered == case["canonical"]
    parsed = parse_stream(_GESTALT_ROOT, case.get("source", case["canonical"]))
    assert _conformance_fields(parsed) == case["stream"]
    assert _render_conformance_stream(parsed) == case["canonical"]


@pytest.mark.parametrize("case", _GESTALT_CONFORMANCE["negative"], ids=lambda case: case["id"])
def test_gestalt_conformance_refusals(case):
    if "source" in case:
        with pytest.raises(ValueError):
            parse_stream(_GESTALT_ROOT, case["source"])
    if "stream" in case:
        with pytest.raises(ValueError):
            _render_conformance_stream(case["stream"])


def test_gestalt_legacy_argument_and_continuation_aliases_round_trip_without_conflicts():
    intent = f"Inspect MiXeD{DELIMITER_SEGMENT}bytes"
    command = f"printf 'MiXeD{DELIMITER_SEGMENT}bytes'"
    argument = f"TERM `MiXeD{DELIMITER_SEGMENT}bytes`"
    rendered = canonical_stream(
        _GESTALT_ROOT,
        SIGNAL_GREEN,
        "get",
        "search",
        "first",
        without_identity=True,
        intents=(intent,),
        cli=(command,),
        actions=({"verb": "get", "noun": "search", "argument": argument},),
    )
    parsed = parse_stream(_GESTALT_ROOT, rendered)
    assert parsed["arguments"] == ["FIRST"]
    assert parsed["intents"] == [intent]
    assert parsed["cli"] == [command]
    assert parsed["actions"][0]["arguments"] == [argument]
    assert canonical_stream(_GESTALT_ROOT, **parsed) == rendered
    assert canonical_stream(_GESTALT_ROOT, argument="FIRST", **parsed) == rendered
    for arguments in (("SECOND",), ("FIRST", "SECOND")):
        with pytest.raises(ValueError, match="argument sources conflict"):
            canonical_stream(_GESTALT_ROOT, SIGNAL_GREEN, "get", "search", "FIRST", arguments=arguments)
        with pytest.raises(ValueError, match="argument sources conflict"):
            canonical_stream(_GESTALT_ROOT, SIGNAL_GREEN, actions=({"verb": "get", "noun": "search", "argument": "FIRST", "arguments": arguments},))
    for field in ("intents", "cli"):
        with pytest.raises(ValueError, match="continuation sources conflict"):
            canonical_stream(_GESTALT_ROOT, **{**parsed, field: ["Changed"]})
    with pytest.raises(ValueError, match="service conflicts"):
        canonical_stream(_GESTALT_ROOT, SIGNAL_GREEN, service=IDENTITY_RUN, without_identity=True)


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
                "eta": f"{SIGNAL_PENDING} ETA T-10s" if active else None,
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
    assert "\n" not in result["error"]
    stream = parse_stream(Path(__file__).parents[3], result["error"])
    assert stream["signal"] == f"{SIGNAL_WARNING}"
    assert (stream["verb"], stream["noun"], stream["arguments"]) == (
        "get",
        "transport",
        ["OFFLINE-FALLBACK"],
    )
    assert stream["evidence"] == ["mcp-unavailable"]
    assert stream["timing"] == ["ETA T-10s"]
    action = stream["actions"][0]
    assert (action["verb"], action["noun"]) == ("get", "search")
    assert action["arguments"] == ["TERM `needle`"]
    assert "{" not in result["error"]
    assert "--args" not in result["error"]
    assert "--scope" not in result["error"]
    assert "RETIRE" not in result["error"]


def test_canonical_stream_is_projected_from_the_root_gestalt_contract():
    root = Path(__file__).parents[3]
    complete = parse_stream(root, canonical_stream(root, f"{SIGNAL_GREEN}", "show", "app", "macos-shell"))
    assert (complete["signal"], complete["verb"], complete["noun"], complete["arguments"]) == (
        f"{SIGNAL_GREEN}",
        "show",
        "app",
        ["MACOS-SHELL"],
    )
    root_stream = parse_stream(root, canonical_stream(root, f"{SIGNAL_WARNING}"))
    assert root_stream["signal"] == f"{SIGNAL_WARNING}"
    assert root_stream["service"] == f"{IDENTITY_LUCID}"
    verb_stream = parse_stream(root, canonical_stream(root, f"{SIGNAL_GREEN}", "show"))
    assert verb_stream["verb"] == "show"
    assert verb_stream["noun"] is None
    with pytest.raises(ValueError, match="coordinate dependencies"):
        canonical_stream(root, f"{SIGNAL_GREEN}", "show", argument="view")
    stream = canonical_stream(
        root,
        SIGNAL_PENDING,
        "show",
        "app",
        '"macos-shell"',
        evidence=("RUNNING",),
        data=("Progress=98%",),
        timing=("ETA 2s",),
        actions=({"verb": "show", "noun": "pulse", "label": "Show pulse"},),
    )
    assert "\n" not in stream
    parsed = parse_stream(root, stream)
    assert parsed["evidence"] == ["RUNNING"]
    assert parsed["data"] == ["Progress=98%"]
    assert parsed["timing"] == ["ETA 2s"]
    assert parsed["actions"] == [
        {"verb": "show", "noun": "pulse", "arguments": [], "label": "Show pulse"}
    ]
    timing = canonical_stream(
        root,
        SIGNAL_PENDING,
        service=f"{IDENTITY_RUN}",
        timing=(f"{SIGNAL_RED} RTT [################] 200% T+5.0",),
    )
    assert parse_stream(root, timing)["timing"] == [f"{SIGNAL_RED} RTT [################] 200% T+5.0"]
    assert "SERVICE" not in timing
    assert "TIMING" not in timing


def test_repeated_arguments_and_json_refusal_follow_the_canonical_contract():
    root = Path(__file__).parents[3]
    action = semantic_action(root, "get", {"path": "search", "query": {"terms": ["first", "second"]}}, "Inspect")
    stream = canonical_stream(root, SIGNAL_GREEN, "get", "search", arguments=("FIRST", "SECOND"), actions=(action,))
    parsed = parse_stream(root, stream)
    assert parsed["arguments"] == ["FIRST", "SECOND"]
    assert parsed["actions"][0]["arguments"] == ["TERM `first`", "TERM `second`"]
    for value in ['{"ready":false}', '["first","second"]', 'Schema {"type":"object"}', 'Schema["first","second"]', 'Values[1,2]', 'Values[]']:
        with pytest.raises(ValueError, match="JSON"):
            canonical_stream(root, SIGNAL_GREEN, data=(value,))
        with pytest.raises(ValueError, match="JSON"):
            parse_stream(root, f"{SIGNAL_GREEN}{DELIMITER_SEGMENT}{RELATION_DATUM} {value}")
    for coordinate in ["$[0]", "$.rows[1]", "values[2][3]"]:
        assert parse_stream(root, canonical_stream(root, SIGNAL_GREEN, data=(coordinate,)))["data"] == [coordinate]
    profile = semantic_action(root, "set", {"path": "effigy-profiles", "value": {"role": "EM", "speech_style": "BUTLER"}}, "Inspect")
    assert profile["arguments"] == ["ROLE `EM`", "VOICE `BUTLER`"]


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
    stream = parse_stream(Path(__file__).parents[3], result["error"])
    assert stream["timing"] == ["ETA T-10s"]
    assert any(
        action["verb"] == "get" and action["noun"] == "search"
        for action in stream["actions"]
    )
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
    stream = parse_stream(Path(__file__).parents[3], result["error"])
    assert (stream["signal"], stream["verb"], stream["noun"], next(iter(stream["arguments"]), None)) == (
        f"{SIGNAL_RED}",
        "dispatch",
        "transport",
        "OUTCOME-ENVELOPE-INVALID",
    )
    assert "MCP tool returned an error" not in result["error"]
    assert f"{RELATION_ACTION}" not in result["error"]
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
    root = Path(__file__).parents[3]
    refusal = canonical_stream(
        root,
        f"{SIGNAL_RED}",
        "set",
        "role",
        "recover",
        evidence=("ROLE-SUPERSEDED: role binding settlement outcome unknown",),
        actions=(
            semantic_action(
                root,
                "get",
                {"path": "role"},
                "Inspect settlement before retrying",
            ),
        ),
    )

    result = lucid_outage.project_lucid_failure(
        "set",
        {"path": "role", "value": {"action": "recover"}},
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
    stream = parse_stream(Path(__file__).parents[3], result["error"])
    assert (stream["signal"], stream["verb"], stream["noun"], next(iter(stream["arguments"]), None)) == (
        f"{SIGNAL_RED}",
        "dispatch",
        "transport",
        "OUTCOME-ENVELOPE-INVALID",
    )
