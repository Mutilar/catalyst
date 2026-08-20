import importlib.util
import json
from pathlib import Path

import pytest


@pytest.fixture
def plugin():
    path = Path(__file__).parents[2] / "plugins" / "ae-tool-teaching" / "__init__.py"
    spec = importlib.util.spec_from_file_location("ae_tool_teaching_plugin", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module._reset_state_for_tests()
    return module


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / "run").mkdir()
    (tmp_path / "butler").mkdir()
    (tmp_path / "envelope").mkdir()
    (tmp_path / "quine").mkdir()
    (tmp_path / "run" / "STACK.json").write_text("{}", encoding="utf-8")
    canonical = json.loads(
        (Path(__file__).parents[3] / "envelope" / "LUCID.json").read_text(encoding="utf-8")
    )
    authored = canonical["tool_suggestion_registry"]
    (tmp_path / "envelope" / "LUCID.json").write_text(
        json.dumps({"tool_suggestion_registry": authored}), encoding="utf-8"
    )
    projection_path = Path(__file__).parents[3] / "envelope" / "LUCID-TOOL-TEACHING.json"
    (tmp_path / "envelope" / "LUCID-TOOL-TEACHING.json").write_text(
        projection_path.read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / "quine" / "areas.json").write_text(
        (Path(__file__).parents[3] / "quine" / "areas.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return tmp_path


def _receipt(result):
    assert result["action"] == "block"
    return json.loads(result["message"].splitlines()[-1])


def _schema():
    return json.loads(
        (Path(__file__).parents[3] / "envelope" / "PENGUIN-TOOL-SUGGESTION.schema.json").read_text(
            encoding="utf-8"
        )
    )


def _executable_refusal_schema():
    return json.loads(
        (
            Path(__file__).parents[3]
            / "envelope"
            / "TERMINAL-EXECUTABLE-REFUSAL.schema.json"
        ).read_text(encoding="utf-8")
    )


def test_generated_universe_joins_every_closed_verb(workspace):
    universe = json.loads(
        (workspace / "envelope" / "LUCID-TOOL-TEACHING.json").read_text(encoding="utf-8")
    )
    assert {join["verb"] for join in universe["target_registry"].values()} == {
        "show",
        "get",
        "set",
        "morph",
        "dispatch",
        "steer",
        "cancel",
    }
    assert universe["authority"] == "none"
    assert universe["policy_owner"] == "HARNESS"


def test_registered_area_binding_normalizes_focused_package_path(plugin, workspace):
    assert (
        plugin._resolve_binding(
            {"$intent": "area", "$transform": "registered-area"},
            {"area": "catalyst/apps/desktop"},
            {},
            workspace,
        )
        == "catalyst"
    )
    with pytest.raises(ValueError, match="unregistered-quality-area"):
        plugin._resolve_binding(
            {"$intent": "area", "$transform": "registered-area"},
            {"area": "unknown/package"},
            {},
            workspace,
        )


def test_bare_cargo_test_is_held_with_generated_candidate(plugin, workspace):
    suggestion = _receipt(
        plugin._on_pre_tool_call(
            tool_name="terminal",
            args={"command": "cargo test", "workdir": str(workspace / "butler")},
            session_id="cargo",
        )
    )
    assert suggestion["decision"] == "hold"
    assert suggestion["source"] == "generated"
    assert suggestion["mode"] == "generated"
    assert suggestion["authority"] == "none"
    assert suggestion["executed"] is False
    assert suggestion["auto_replay"] is False
    assert suggestion["candidate"]["tool"] == "mcp__LUCID__dispatch"
    assert suggestion["candidate"]["arguments"] == {"area": "butler", "operation": "test"}


def test_focused_diagnostic_executes_then_whispers(plugin, workspace):
    args = {
        "command": "pytest catalyst/tests/agent/test_ae_tool_teaching_plugin.py",
        "workdir": str(workspace / "butler"),
    }
    assert plugin._on_pre_tool_call(tool_name="terminal", args=args, session_id="whisper") is None
    transformed = plugin._on_transform_tool_result(
        tool_name="terminal", args=args, result="1 passed", session_id="whisper", status="ok"
    )
    assert transformed is not None and transformed.startswith("1 passed")
    suggestion = json.loads(transformed.splitlines()[-1])
    assert suggestion["decision"] == "whisper"
    assert suggestion["original_executed"] is True
    assert suggestion["trajectory"] == {"state": "whisper", "attempt": 1}


def test_search_files_maps_to_bounded_get_search_recursively(plugin, workspace, monkeypatch):
    monkeypatch.chdir(workspace)
    args = {
        "pattern": "target_registry",
        "target": "content",
        "path": ".",
        "limit": 17,
        "context": 2,
    }
    suggestion = _receipt(
        plugin._on_pre_tool_call(tool_name="search_files", args=args, session_id="search")
    )
    assert suggestion["candidate"]["tool"] == "mcp__LUCID__get"
    assert suggestion["candidate"]["target"] == {"registry": "get-target", "id": "search"}
    assert suggestion["candidate"]["arguments"] == {
        "path": "search",
        "query": {
            "terms": ["target_registry"],
            "paths": ["."],
            "mode": "content",
            "limit": 17,
            "context": 2,
        },
    }


def test_write_file_maps_to_set_repository_file_with_full_arguments(plugin, workspace, monkeypatch):
    monkeypatch.chdir(workspace)
    args = {"path": "catalyst/new.py", "content": "print('bounded')\n"}
    suggestion = _receipt(
        plugin._on_pre_tool_call(tool_name="write_file", args=args, session_id="write")
    )
    candidate = suggestion["candidate"]
    assert candidate["tool"] == "mcp__LUCID__set"
    assert candidate["target"] == {
        "registry": "set-target",
        "id": "repository-authored-file",
    }
    assert candidate["arguments"] == {
        "path": "repository/file",
        "value": {"path": "catalyst/new.py", "content": "print('bounded')\n"},
    }
    assert candidate["syntax"] == {
        "tool": candidate["tool"],
        "arguments": candidate["arguments"],
    }


def test_cross_profile_and_repository_escape_writes_are_inert(plugin, workspace, monkeypatch):
    monkeypatch.chdir(workspace)
    assert (
        plugin._on_pre_tool_call(
            tool_name="write_file",
            args={"path": "safe.py", "content": "x", "cross_profile": True},
        )
        is None
    )
    assert (
        plugin._on_pre_tool_call(
            tool_name="write_file", args={"path": "../outside.py", "content": "x"}
        )
        is None
    )


def test_closed_recursive_resolver_rejects_unknown_transform(plugin, workspace):
    with pytest.raises(ValueError, match="unknown-generated-transform"):
        plugin._resolve_binding(
            {"value": {"$arg": "path", "$transform": "shell"}},
            {},
            {"path": "safe"},
            workspace,
        )
    with pytest.raises(ValueError, match="unknown-generated-binding"):
        plugin._resolve_binding({"$eval": "args"}, {}, {}, workspace)


def test_harness_owns_all_four_policy_dispositions(plugin):
    intents = {
        "workspace": {"focused": False, "release": False},
        "focused": {"focused": True, "release": False},
        "release": {"focused": False, "release": True},
    }
    target = {
        "policy": {"workspace": "allow", "focused": "whisper", "release": "enforce"}
    }
    assert plugin._policy_disposition(intents["workspace"], target) == "allow"
    assert plugin._policy_disposition(intents["focused"], target) == "whisper"
    assert plugin._policy_disposition(intents["release"], target) == "enforce"
    target["policy"]["workspace"] = "hold"
    assert plugin._policy_disposition(intents["workspace"], target) == "hold"


def test_interpretation_environment_cannot_disable_harness(plugin, workspace, monkeypatch):
    monkeypatch.setenv("AE_PENGUIN_TOOL_INTERPRETATION", "off")
    receipt = _receipt(
        plugin._on_pre_tool_call(
            tool_name="terminal",
            args={"command": "cargo test", "workdir": str(workspace / "butler")},
            session_id="still-held",
        )
    )
    assert receipt["decision"] == "hold"
    assert not hasattr(plugin, "_penguin_candidate")


def test_repeating_a_held_call_once_is_explicit_override(plugin, workspace):
    args = {"command": "cargo test", "workdir": str(workspace / "butler")}
    first = plugin._on_pre_tool_call(tool_name="terminal", args=args, session_id="override")
    assert _receipt(first)["decision"] == "hold"
    assert plugin._on_pre_tool_call(tool_name="terminal", args=args, session_id="override") is None
    transformed = plugin._on_transform_tool_result(
        tool_name="terminal",
        args=args,
        result="diagnostic",
        session_id="override",
        status="ok",
    )
    assert transformed is not None
    receipt = json.loads(transformed.splitlines()[-1])
    assert receipt["decision"] == "override"
    assert receipt["trajectory"] == {"state": "override", "attempt": 2}


@pytest.mark.parametrize(
    ("status", "outcome", "succeeded"),
    [("ok", "success", True), ("blocked", "refusal", False), ("error", "failure", False)],
)
def test_exact_follow_up_records_all_terminal_outcomes(
    plugin, workspace, status, outcome, succeeded
):
    held = plugin._on_pre_tool_call(
        tool_name="terminal",
        args={"command": "cargo test", "workdir": str(workspace / "butler")},
        session_id=f"follow-{status}",
    )
    candidate = _receipt(held)["candidate"]
    transformed = plugin._on_transform_tool_result(
        tool_name=candidate["tool"],
        args=candidate["arguments"],
        result="bounded result",
        session_id=f"follow-{status}",
        status=status,
    )
    receipt = json.loads(transformed.splitlines()[-1])
    assert receipt["state"] == "followed"
    assert receipt["authority"] == "none"
    assert receipt["auto_replay"] is False
    assert receipt["candidate_executed"] is True
    assert receipt["outcome"] == outcome
    assert receipt["succeeded"] is succeeded
    assert receipt["candidate"] == candidate


def test_transport_success_with_typed_red_result_records_failure(plugin):
    result = json.dumps({"structuredContent": {"state": "🔴"}})
    assert plugin._tool_outcome("success", result) == "failure"


def test_follow_up_requires_exact_tool_full_args_and_session(plugin, workspace):
    held = plugin._on_pre_tool_call(
        tool_name="terminal",
        args={"command": "cargo test", "workdir": str(workspace / "butler")},
        session_id="exact",
    )
    candidate = _receipt(held)["candidate"]
    assert (
        plugin._on_transform_tool_result(
            tool_name=candidate["tool"],
            args={"area": "workspace"},
            result="wrong args",
            session_id="exact",
            status="ok",
        )
        is None
    )
    assert (
        plugin._on_transform_tool_result(
            tool_name=candidate["tool"],
            args=candidate["arguments"],
            result="wrong session",
            session_id="other",
            status="ok",
        )
        is None
    )
    assert (
        plugin._on_transform_tool_result(
            tool_name="mcp__LUCID__get",
            args=candidate["arguments"],
            result="wrong tool",
            session_id="exact",
            status="ok",
        )
        is None
    )
    assert plugin._on_transform_tool_result(
        tool_name=candidate["tool"],
        args=candidate["arguments"],
        result="exact",
        session_id="exact",
        status="ok",
    )


def test_terminal_command_and_result_privacy(plugin, workspace):
    secret = "DO_NOT_PROJECT_PRIVATE_TOKEN"
    held = plugin._on_pre_tool_call(
        tool_name="terminal",
        args={
            "command": f"cargo test --config password={secret}",
            "workdir": str(workspace / "butler"),
        },
        session_id="privacy",
    )
    suggestion = _receipt(held)
    encoded = json.dumps(suggestion)
    assert secret not in encoded
    assert "password=" not in encoded
    candidate = suggestion["candidate"]
    transformed = plugin._on_transform_tool_result(
        tool_name=candidate["tool"],
        args=candidate["arguments"],
        result=f"private result {secret}",
        session_id="privacy",
        status="error",
    )
    trajectory = json.loads(transformed.splitlines()[-1])
    assert secret not in json.dumps(trajectory)
    assert "result" not in trajectory


def test_followed_event_is_privacy_bounded_for_run_store_ingestion(
    plugin, workspace, capsys
):
    secret = "NEVER_PERSIST_THIS_VALUE"
    held = plugin._on_pre_tool_call(
        tool_name="terminal",
        args={"command": f"cargo test --config password={secret}", "workdir": str(workspace / "butler")},
        session_id="event-followed",
    )
    candidate = _receipt(held)["candidate"]
    plugin._on_transform_tool_result(
        tool_name=candidate["tool"],
        args=candidate["arguments"],
        result=f"private result {secret}",
        session_id="event-followed",
        status="ok",
    )
    events = [
        json.loads(line.removeprefix("PENGUIN_TEACHING_EVENT "))
        for line in capsys.readouterr().err.splitlines()
        if line.startswith("PENGUIN_TEACHING_EVENT ")
    ]
    event = next(event for event in events if event["schema"] == "penguin-suggestion-outcome/1")
    assert event["schema"] == "penguin-suggestion-outcome/1"
    assert event["outcome"] == "followed"
    assert event["matched_candidate"] is True
    assert event["succeeded"] is True
    assert event["authority"] == "none"
    assert event["auto_replay"] is False
    encoded = json.dumps(event)
    assert secret not in encoded
    assert "arguments" not in event
    assert "result" not in event
    assert "session_id" not in event


def test_session_end_emits_ignored_without_identity_or_candidate_arguments(
    plugin, workspace, capsys
):
    plugin._on_pre_tool_call(
        tool_name="terminal",
        args={"command": "cargo test", "workdir": str(workspace / "butler")},
        session_id="event-ignored",
    )
    plugin._on_session_end(session_id="event-ignored")
    events = [
        json.loads(line.removeprefix("PENGUIN_TEACHING_EVENT "))
        for line in capsys.readouterr().err.splitlines()
        if line.startswith("PENGUIN_TEACHING_EVENT ")
    ]
    event = next(event for event in events if event["schema"] == "penguin-suggestion-outcome/1")
    assert event["outcome"] == "ignored"
    assert event["matched_candidate"] is False
    assert event["succeeded"] is False
    assert "arguments" not in event
    assert "session_id" not in event


def test_unregistered_known_source_emits_coverage_gap_without_raw_values(
    plugin, workspace, capsys
):
    secret = "UNMAPPED_PRIVATE_VALUE"
    result = plugin._on_pre_tool_call(
        tool_name="terminal",
        args={"command": f"python unknown.py --token={secret}", "workdir": str(workspace / "butler")},
        session_id="coverage-gap",
    )
    assert result["action"] == "block"
    refusal = json.loads(result["message"].splitlines()[-1])
    assert refusal["schema"] == "ae-terminal-executable-refusal/1"
    assert refusal["reason"] == "unregistered-executable"
    assert refusal["executed"] is False
    assert refusal["executable"] == "python"
    assert secret not in json.dumps(refusal)
    events = [
        json.loads(line.removeprefix("PENGUIN_TEACHING_EVENT "))
        for line in capsys.readouterr().err.splitlines()
        if line.startswith("PENGUIN_TEACHING_EVENT ")
    ]
    event = next(event for event in events if event["schema"] == "penguin-tool-intent-observed/1")
    assert event["classification"] == "unregistered"
    assert event["target"] is None
    assert event["operation"] is None
    assert secret not in json.dumps(event)
    assert "arguments" not in event
    assert "session_id" not in event


@pytest.mark.parametrize(
    "command",
    [
        "git",
        "git status",
        "git commit -m nope",
        "/usr/bin/git status",
        "env git status",
        "GIT_OPTIONAL_LOCKS=0 git status",
        "command git status",
    ],
)
def test_git_family_is_categorically_refused(plugin, workspace, command):
    receipt = _receipt(
        plugin._on_pre_tool_call(
            tool_name="terminal",
            args={"command": command, "workdir": str(workspace / "butler")},
            session_id="git",
        )
    )
    assert receipt["schema"] == "penguin-tool-refusal/1"
    assert receipt["state"] == "refused"
    assert receipt["reason"] == "git-prohibited"
    assert receipt["policy_owner"] == "HARNESS"
    assert receipt["authority"] == "none"
    assert receipt["executed"] is False
    assert receipt["auto_replay"] is False
    assert receipt["alternative"]["tool"] == "mcp__LUCID__get"


def test_unregistered_or_compound_calls_are_refused(plugin, workspace):
    for command in ["cargo test && rm -rf nowhere", "make test"]:
        refusal = plugin._on_pre_tool_call(
            tool_name="terminal",
            args={"command": command, "workdir": str(workspace / "butler")},
            session_id="refused",
        )
        assert refusal["action"] == "block"
        receipt = json.loads(refusal["message"].splitlines()[-1])
        assert receipt["reason"] == "unregistered-executable"
        assert receipt["executed"] is False


@pytest.mark.parametrize("command", ["run status --json", "lucid get --help"])
def test_only_canonical_direct_executables_are_admitted(plugin, workspace, command):
    assert (
        plugin._on_pre_tool_call(
            tool_name="terminal",
            args={"command": command, "workdir": str(workspace / "butler")},
            session_id="direct",
        )
        is None
    )


@pytest.mark.parametrize(
    "command",
    [
        "butler --help",
        "ae status --json",
        "/usr/local/bin/lucid get --help",
        "run/target/debug/ae status --json",
        "butler/target/debug/lucid get --help",
        "build/run status",
        "dist/lucid get --help",
        "run status $(butler --help)",
        "lucid get --help > result.json",
        "cargo test; butler --help",
        "cargo test\nbutler --help",
    ],
)
def test_arbitrary_external_and_build_output_executables_are_refused(
    plugin, workspace, command
):
    refusal = plugin._on_pre_tool_call(
        tool_name="terminal",
        args={"command": command, "workdir": str(workspace / "butler")},
        session_id="binary",
    )
    assert refusal["action"] == "block"
    receipt = json.loads(refusal["message"].splitlines()[-1])
    assert receipt["schema"] == "ae-terminal-executable-refusal/1"
    assert receipt["executed"] is False
    assert receipt["original_executed"] is False


def test_generated_projection_is_mandatory(plugin, workspace):
    (workspace / "envelope" / "LUCID-TOOL-TEACHING.json").unlink()
    refusal = plugin._on_pre_tool_call(
        tool_name="terminal",
        args={"command": "cargo test", "workdir": str(workspace / "butler")},
    )
    assert refusal["action"] == "block"
    receipt = json.loads(refusal["message"].splitlines()[-1])
    assert receipt["reason"] == "executable-policy-unavailable"


def test_receipts_validate_against_canonical_schema(plugin, workspace):
    jsonschema = pytest.importorskip("jsonschema")
    held = plugin._on_pre_tool_call(
        tool_name="terminal",
        args={"command": "cargo test", "workdir": str(workspace / "butler")},
        session_id="schema",
    )
    suggestion = _receipt(held)
    jsonschema.validate(suggestion, _schema())
    candidate = suggestion["candidate"]
    transformed = plugin._on_transform_tool_result(
        tool_name=candidate["tool"],
        args=candidate["arguments"],
        result="ok",
        session_id="schema",
        status="ok",
    )
    jsonschema.validate(json.loads(transformed.splitlines()[-1]), _schema())
    refusal = _receipt(
        plugin._on_pre_tool_call(
            tool_name="terminal",
            args={"command": "git status", "workdir": str(workspace / "butler")},
            session_id="schema-refusal",
        )
    )
    jsonschema.validate(refusal, _schema())
    executable_refusal = plugin._on_pre_tool_call(
        tool_name="terminal",
        args={"command": "butler --help", "workdir": str(workspace / "butler")},
        session_id="schema-executable-refusal",
    )
    jsonschema.validate(
        json.loads(executable_refusal["message"].splitlines()[-1]),
        _executable_refusal_schema(),
    )


def test_trajectory_state_is_bounded(plugin, workspace):
    args = {"command": "cargo test", "workdir": str(workspace / "butler")}
    for index in range(plugin._MAX_TRAJECTORIES + 20):
        assert plugin._on_pre_tool_call(
            tool_name="terminal", args=args, session_id=f"session-{index}"
        )
    assert len(plugin._HELD_CALLS) == plugin._MAX_TRAJECTORIES
    assert len(plugin._PENDING_CANDIDATES) <= plugin._MAX_TRAJECTORIES


def test_registers_pre_tool_and_result_transform_hooks(plugin):
    registered = []

    class Context:
        def register_hook(self, name, callback):
            registered.append((name, callback))

    plugin.register(Context())
    assert registered == [
        ("pre_tool_call", plugin._on_pre_tool_call),
        ("transform_tool_result", plugin._on_transform_tool_result),
        ("on_session_end", plugin._on_session_end),
    ]
