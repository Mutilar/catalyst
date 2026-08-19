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
    return module


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / "run").mkdir()
    (tmp_path / "envelope").mkdir()
    (tmp_path / "run" / "STACK.json").write_text("{}", encoding="utf-8")
    canonical = json.loads(
        (Path(__file__).parents[3] / "envelope" / "LUCID.json").read_text(encoding="utf-8")
    )
    (tmp_path / "envelope" / "LUCID.json").write_text(
        json.dumps({"tool_suggestion_registry": canonical["tool_suggestion_registry"]}),
        encoding="utf-8",
    )
    return tmp_path


def _suggestion(result):
    assert result["action"] == "block"
    return json.loads(result["message"].splitlines()[-1])


def test_bare_cargo_test_is_held_with_validated_heuristic(plugin, workspace, monkeypatch):
    monkeypatch.setenv("AE_PENGUIN_TOOL_INTERPRETATION", "heuristic")
    result = plugin._on_pre_tool_call(
        tool_name="terminal",
        args={"command": "cargo test", "workdir": str(workspace)},
    )
    suggestion = _suggestion(result)
    assert suggestion["schema"] == plugin.SUGGESTION_SCHEMA
    assert suggestion["source"] == "heuristic"
    assert suggestion["authority"] == "none"
    assert suggestion["executed"] is False
    assert suggestion["auto_replay"] is False
    assert suggestion["original_executed"] is False
    assert suggestion["candidate"]["arguments"] == {"area": "workspace", "operation": "test"}
    assert suggestion["preflight"]["valid"] is True
    assert suggestion["registry_hash"].startswith("sha256:")


def test_focused_cargo_test_is_allowed_unless_hold_focused_is_enabled(
    plugin, workspace, monkeypatch
):
    args = {
        "command": "cargo test --manifest-path butler/Cargo.toml --test skin_census",
        "workdir": str(workspace),
    }
    assert plugin._on_pre_tool_call(tool_name="terminal", args=args) is None
    monkeypatch.setenv("AE_PENGUIN_TOOL_HOLD_FOCUSED", "1")
    suggestion = _suggestion(plugin._on_pre_tool_call(tool_name="terminal", args=args))
    assert suggestion["intent"]["area"] == "butler"
    assert suggestion["intent"]["focused"] is True


def test_off_mode_is_inert(plugin, workspace, monkeypatch):
    monkeypatch.setenv("AE_PENGUIN_TOOL_INTERPRETATION", "off")
    assert (
        plugin._on_pre_tool_call(
            tool_name="terminal",
            args={"command": "cargo test", "workdir": str(workspace)},
        )
        is None
    )


def test_intelligent_mode_falls_back_gracefully_to_heuristic(
    plugin, workspace, monkeypatch
):
    monkeypatch.setenv("AE_PENGUIN_TOOL_INTERPRETATION", "intelligent")
    monkeypatch.setattr(
        plugin,
        "_penguin_candidate",
        lambda _intent, _heuristic: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    suggestion = _suggestion(
        plugin._on_pre_tool_call(
            tool_name="terminal",
            args={"command": "cargo test", "workdir": str(workspace)},
        )
    )
    assert suggestion["source"] == "heuristic"
    assert suggestion["fallback"] == "RuntimeError"
    assert suggestion["preflight"]["valid"] is True


def test_intelligent_candidate_is_used_only_after_deterministic_validation(
    plugin, workspace, monkeypatch
):
    monkeypatch.setenv("AE_PENGUIN_TOOL_INTERPRETATION", "intelligent")

    def candidate(intent, _heuristic):
        return {
            "schema": plugin.CANDIDATE_SCHEMA,
            "verb": "dispatch",
            "arguments": {"area": intent["area"], "operation": "test"},
            "explanation": "Use the exact registered quality owner.",
        }

    monkeypatch.setattr(plugin, "_penguin_candidate", candidate)
    suggestion = _suggestion(
        plugin._on_pre_tool_call(
            tool_name="terminal",
            args={"command": "cargo test", "workdir": str(workspace)},
        )
    )
    assert suggestion["source"] == "PENGUIN"
    assert suggestion["fallback"] is None


def test_invalid_intelligent_candidate_falls_back_and_raw_command_is_not_projected(
    plugin, workspace, monkeypatch
):
    monkeypatch.setenv("AE_PENGUIN_TOOL_INTERPRETATION", "intelligent")
    monkeypatch.setattr(
        plugin,
        "_penguin_candidate",
        lambda _intent, _heuristic: {
            "schema": plugin.CANDIDATE_SCHEMA,
            "verb": "dispatch",
            "arguments": {"task": "dangerous", "area": "workspace"},
            "explanation": "bad",
        },
    )
    raw = "cargo test --config password=DO_NOT_PROJECT"
    suggestion = _suggestion(
        plugin._on_pre_tool_call(
            tool_name="terminal",
            args={"command": raw, "workdir": str(workspace)},
        )
    )
    assert suggestion["source"] == "heuristic"
    assert raw not in json.dumps(suggestion)
    assert "DO_NOT_PROJECT" not in json.dumps(suggestion)


def test_release_build_maps_to_run_qualification(plugin, workspace):
    suggestion = _suggestion(
        plugin._on_pre_tool_call(
            tool_name="terminal",
            args={"command": "cargo build --release", "workdir": str(workspace)},
        )
    )
    assert suggestion["candidate"]["arguments"] == {
        "task": "run.qualify",
        "area": "workspace",
    }


def test_registers_pre_tool_and_result_transform_hooks(plugin):
    registered = []

    class Context:
        def register_hook(self, name, callback):
            registered.append((name, callback))

    plugin.register(Context())
    assert registered == [
        ("pre_tool_call", plugin._on_pre_tool_call),
        ("transform_tool_result", plugin._on_transform_tool_result),
    ]


@pytest.mark.parametrize(
    ("command", "target", "operation"),
    [
        ("pytest", "pytest", "test"),
        ("python -m pytest", "pytest", "test"),
        ("npm test", "node-test", "test"),
        ("pnpm run build", "node-build", "build"),
        ("xcodebuild test", "xcode-test", "test"),
        ("xcodebuild build", "xcode-build", "build"),
        ("cargo clippy", "cargo-clippy", "lint"),
        ("ruff check", "ruff-check", "lint"),
        ("npm run lint", "node-lint", "lint"),
        ("cargo llvm-cov", "cargo-line-coverage", "line_coverage"),
    ],
)
def test_registry_classifies_cross_ecosystem_workspace_calls(
    plugin, workspace, command, target, operation
):
    result = plugin._on_pre_tool_call(
        tool_name="terminal",
        args={"command": command, "workdir": str(workspace)},
        session_id="cross-ecosystem",
    )
    suggestion = _suggestion(result)
    assert suggestion["decision"] == "hold"
    assert suggestion["intent"]["target"] == target
    assert suggestion["intent"]["operation"] == operation


def test_focused_diagnostic_executes_then_receives_whisper(plugin, workspace):
    args = {
        "command": "pytest catalyst/tests/agent/test_ae_tool_teaching_plugin.py",
        "workdir": str(workspace),
    }
    assert plugin._on_pre_tool_call(tool_name="terminal", args=args, session_id="whisper") is None
    transformed = plugin._on_transform_tool_result(
        tool_name="terminal", args=args, result="1 passed"
    )
    assert transformed is not None and transformed.startswith("1 passed")
    receipt = json.loads(transformed.splitlines()[-1])
    assert receipt["decision"] == "whisper"
    assert receipt["original_executed"] is True
    assert receipt["trajectory"] == {"state": "whisper", "attempt": 1}


def test_repeating_a_held_call_once_is_an_explicit_override(plugin, workspace):
    plugin._reset_state_for_tests()
    args = {"command": "cargo test", "workdir": str(workspace)}
    first = plugin._on_pre_tool_call(tool_name="terminal", args=args, session_id="loop-safe")
    assert _suggestion(first)["decision"] == "hold"
    assert (
        plugin._on_pre_tool_call(tool_name="terminal", args=args, session_id="loop-safe")
        is None
    )
    transformed = plugin._on_transform_tool_result(
        tool_name="terminal", args=args, result="diagnostic result", session_id="loop-safe"
    )
    assert transformed is not None
    receipt = json.loads(transformed.splitlines()[-1])
    assert receipt["decision"] == "override"
    assert receipt["original_executed"] is True
    assert receipt["trajectory"] == {"state": "override", "attempt": 2}


def test_override_trajectory_is_session_scoped(plugin, workspace):
    plugin._reset_state_for_tests()
    args = {"command": "cargo test", "workdir": str(workspace)}
    assert plugin._on_pre_tool_call(tool_name="terminal", args=args, session_id="one")
    assert plugin._on_pre_tool_call(tool_name="terminal", args=args, session_id="one") is None
    assert (
        plugin._on_transform_tool_result(
            tool_name="terminal", args=args, result="other", session_id="two"
        )
        is None
    )
    transformed = plugin._on_transform_tool_result(
        tool_name="terminal", args=args, result="mine", session_id="one"
    )
    assert transformed is not None
    assert json.loads(transformed.splitlines()[-1])["decision"] == "override"


def test_emitted_receipt_validates_against_canonical_schema(plugin, workspace):
    jsonschema = pytest.importorskip("jsonschema")
    result = plugin._on_pre_tool_call(
        tool_name="terminal",
        args={"command": "npm test", "workdir": str(workspace)},
        session_id="schema",
    )
    receipt = _suggestion(result)
    schema = json.loads(
        (Path(__file__).parents[3] / "envelope" / "PENGUIN-TOOL-SUGGESTION.schema.json").read_text(
            encoding="utf-8"
        )
    )
    jsonschema.validate(receipt, schema)


def test_matching_lucid_dispatch_settles_followed_trajectory(plugin, workspace):
    plugin._reset_state_for_tests()
    held = plugin._on_pre_tool_call(
        tool_name="terminal",
        args={"command": "cargo test", "workdir": str(workspace)},
        session_id="follow",
    )
    suggestion = _suggestion(held)
    transformed = plugin._on_transform_tool_result(
        tool_name="mcp__LUCID__dispatch",
        args=suggestion["candidate"]["arguments"],
        result="dispatch accepted",
        session_id="follow",
    )
    assert transformed is not None and transformed.startswith("dispatch accepted")
    receipt = json.loads(transformed.splitlines()[-1])
    assert receipt["schema"] == "penguin-tool-suggestion-trajectory/1"
    assert receipt["state"] == "followed"
    assert receipt["authority"] == "none"
    assert receipt["auto_replay"] is False
    assert receipt["candidate_executed"] is True
    assert receipt["candidate"] == suggestion["candidate"]
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(
        (Path(__file__).parents[3] / "envelope" / "PENGUIN-TOOL-SUGGESTION.schema.json").read_text(
            encoding="utf-8"
        )
    )
    jsonschema.validate(receipt, schema)


def test_followed_trajectory_cannot_cross_sessions(plugin, workspace):
    plugin._reset_state_for_tests()
    held = plugin._on_pre_tool_call(
        tool_name="terminal",
        args={"command": "cargo test", "workdir": str(workspace)},
        session_id="owner",
    )
    candidate = _suggestion(held)["candidate"]
    assert (
        plugin._on_transform_tool_result(
            tool_name="mcp__LUCID__dispatch",
            args=candidate["arguments"],
            result="other",
            session_id="other",
        )
        is None
    )


@pytest.mark.parametrize(
    "command",
    [
        "cargo test && rm -rf nowhere",
        "cargo test --manifest-path ../outside/Cargo.toml",
        "make test",
    ],
)
def test_unbounded_or_unregistered_commands_are_inert(plugin, workspace, command):
    assert (
        plugin._on_pre_tool_call(
            tool_name="terminal",
            args={"command": command, "workdir": str(workspace)},
            session_id="adversarial",
        )
        is None
    )


def test_trajectory_state_is_bounded(plugin, workspace):
    plugin._reset_state_for_tests()
    args = {"command": "cargo test", "workdir": str(workspace)}
    for index in range(plugin._MAX_TRAJECTORIES + 20):
        assert plugin._on_pre_tool_call(
            tool_name="terminal", args=args, session_id=f"session-{index}"
        )
    assert len(plugin._HELD_CALLS) == plugin._MAX_TRAJECTORIES
    assert len(plugin._PENDING_CANDIDATES) <= plugin._MAX_TRAJECTORIES


@pytest.mark.parametrize(
    "command",
    [
        "git",
        "git status",
        "git diff",
        "git log --oneline",
        "git rev-parse HEAD",
        "git branch --show-current",
        "git commit -m nope",
        "git reset --hard HEAD",
        "/usr/bin/git status",
        "env git status",
        "GIT_OPTIONAL_LOCKS=0 git status",
        "command git status",
    ],
)
def test_every_git_family_is_categorically_refused(plugin, workspace, command):
    result = plugin._on_pre_tool_call(
        tool_name="terminal",
        args={"command": command, "workdir": str(workspace)},
        session_id="git-refusal",
    )
    receipt = _suggestion(result)
    assert receipt["schema"] == "penguin-tool-refusal/1"
    assert receipt["state"] == "refused"
    assert receipt["reason"] == "git-prohibited"
    assert receipt["policy_owner"] == "HARNESS"
    assert receipt["executed"] is False
    assert receipt["original_executed"] is False
    assert receipt["auto_replay"] is False
    assert receipt["alternative"]["kind"] == "lucid-search"
    assert "candidate" not in receipt


def test_git_refusal_cannot_be_disabled_overridden_or_model_reinterpreted(
    plugin, workspace, monkeypatch
):
    monkeypatch.setenv("AE_PENGUIN_TOOL_INTERPRETATION", "off")
    monkeypatch.setattr(
        plugin,
        "_penguin_candidate",
        lambda *_args: (_ for _ in ()).throw(AssertionError("PENGUIN must not arbitrate Git")),
    )
    args = {"command": "git status", "workdir": str(workspace)}
    first = plugin._on_pre_tool_call(tool_name="terminal", args=args, session_id="git-enforced")
    second = plugin._on_pre_tool_call(tool_name="terminal", args=args, session_id="git-enforced")
    assert _suggestion(first)["schema"] == "penguin-tool-refusal/1"
    assert _suggestion(second)["schema"] == "penguin-tool-refusal/1"


def test_git_refusal_validates_against_canonical_schema(plugin, workspace):
    jsonschema = pytest.importorskip("jsonschema")
    receipt = _suggestion(
        plugin._on_pre_tool_call(
            tool_name="terminal",
            args={"command": "git log", "workdir": str(workspace)},
            session_id="git-schema",
        )
    )
    schema = json.loads(
        (Path(__file__).parents[3] / "envelope" / "PENGUIN-TOOL-SUGGESTION.schema.json").read_text(
            encoding="utf-8"
        )
    )
    jsonschema.validate(receipt, schema)


def test_bundled_plugin_discovers_pre_tool_hook(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    from hermes_cli.plugins import PluginManager

    manager = PluginManager()
    manager.discover_and_load()
    callbacks = manager._hooks.get("pre_tool_call", [])
    assert any(
        getattr(callback, "__name__", "") == "_on_pre_tool_call"
        and "ae_tool_teaching" in getattr(callback, "__module__", "").replace("-", "_")
        for callback in callbacks
    )
    transforms = manager._hooks.get("transform_tool_result", [])
    assert any(
        getattr(callback, "__name__", "") == "_on_transform_tool_result"
        and "ae_tool_teaching" in getattr(callback, "__module__", "").replace("-", "_")
        for callback in transforms
    )
