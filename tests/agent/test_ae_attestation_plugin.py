import importlib.util
import json
from pathlib import Path

import pytest


@pytest.fixture
def plugin():
    path = Path(__file__).parents[2] / "plugins" / "ae-attestation" / "__init__.py"
    spec = importlib.util.spec_from_file_location("ae_attestation_plugin", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _workspace(root: Path, role: str = "EM", glyph: str = "🎼🐧") -> Path:
    repository = Path(__file__).parents[3]
    (root / "quine" / "canon").mkdir(parents=True)
    (root / "quine" / "mcp" / "onboarding").mkdir(parents=True)
    (root / "run" / "state" / "runtime").mkdir(parents=True)
    (root / "envelope").mkdir(parents=True)
    (root / "quine" / "canon" / "roles.json").write_text(
        json.dumps({"$schema": "ae-roles/1", "roles": {role: {"glyph": glyph}}}),
        encoding="utf-8",
    )
    (root / "run" / "state" / "runtime" / "lucid-host-role.json").write_text(
        json.dumps({"schema": "lucid-host-role-decision/1", "role": role}),
        encoding="utf-8",
    )
    (root / "envelope" / "HARNESS.json").write_text(
        (repository / "envelope" / "HARNESS.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    for name in ["index.json", "universal.md", f"{role.lower()}.md"]:
        (root / "quine" / "mcp" / "onboarding" / name).write_text(
            (repository / "quine" / "mcp" / "onboarding" / name).read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    return root


def test_exact_canonical_suffix_passes_without_synthetic_turn(plugin, tmp_path):
    root = _workspace(tmp_path)
    assert plugin.required_terminal_suffix(root) == "🎼🐧"
    assert plugin._pre_final(final_response="Done.\n\n🎼🐧", workspace_root=str(root)) is None


def test_attested_final_submits_once_to_current_role_effigy(plugin, tmp_path, monkeypatch):
    root = _workspace(tmp_path)
    observed = []

    def submit(arguments):
        observed.append(arguments)
        return {"structuredContent": {"status": "accepted"}}

    monkeypatch.setattr(plugin, "_submit_effigy_speech", submit)
    response = "The exact final statement.\n\n🎼🐧"
    receipt = plugin._post_final(
        final_response=response,
        workspace_root=str(root),
        session_id="session-1",
    )

    assert receipt == {
        "state": "submitted",
        "code": "effigy-response-final-submitted",
    }
    assert observed == [
        {
            "kind": "text",
            "data": {"text": response},
            "from": "response-final",
            "presentation": "audio-only",
            "scope": "this",
        }
    ]
    assert plugin._post_final(
        final_response=response,
        workspace_root=str(root),
        session_id="session-1",
    ) is None


def test_unattested_final_is_never_submitted_to_effigy(plugin, tmp_path, monkeypatch):
    root = _workspace(tmp_path)
    observed = []
    monkeypatch.setattr(
        plugin,
        "_submit_effigy_speech",
        lambda arguments: observed.append(arguments),
    )

    assert plugin._post_final(
        final_response="Missing glyph.",
        workspace_root=str(root),
        session_id="session-2",
    ) is None
    assert observed == []


def test_missing_suffix_reinjects_canonical_onboarding_then_requires_signout(plugin, tmp_path):
    root = _workspace(tmp_path)
    result = plugin._pre_final(
        final_response="Done.", workspace_root=str(root), attempt=0, session_id="drift"
    )
    assert result["action"] == "continue"
    message = result["message"]
    assert message.startswith("⚠️ LUCID · role-attestation · protocol-drift")
    assert "AE/PENGUIN PROTOCOL · UNIVERSAL" in message
    assert "AE/PENGUIN PROTOCOL · EM" in message
    assert "lucid://onboarding/em" in message
    assert "terminate with exactly 🎼🐧" in message

    signout = plugin._pre_final(
        final_response="Still drifted.", workspace_root=str(root), attempt=1, session_id="drift"
    )
    assert signout["action"] == "continue"
    assert signout["message"].startswith("🔴 LUCID · role-session · signout-required")
    assert "NEXT Sign out immediately:" in signout["message"]
    assert '"action":"signout"' in signout["message"]
    assert "mcp__LUCID__set" in signout["message"]

    repeated = plugin._pre_final(
        final_response="Ignored signout.", workspace_root=str(root), attempt=2, session_id="drift"
    )
    assert repeated["action"] == "continue"
    assert "signout-required" in repeated["message"]

    plugin._transform_tool_result(
        tool_name="mcp__LUCID__set",
        args={"path": "role-session", "scope": "this", "value": {"action": "signout"}},
        result=json.dumps({"structuredContent": {"state": "signout"}}),
        session_id="drift",
        status="success",
    )
    offline = plugin._pre_final(
        final_response="Signed out.", workspace_root=str(root), attempt=2, session_id="drift"
    )
    assert offline["action"] == "block"
    assert offline["message"].startswith("🔴 LUCID · role-session · offline")
    assert "OWNER WITNESS" in offline["message"]


def test_role_and_suffix_come_from_canon_not_prompt_or_model_claim(plugin, tmp_path):
    root = _workspace(tmp_path, role="SIDEKICK", glyph="🧭🐧")
    result = plugin._pre_final(
        final_response="I claim I am EM. 🎼🐧",
        workspace_root=str(root),
    )
    assert "terminate with exactly 🧭🐧" in result["message"]


def test_missing_malformed_or_symlinked_canon_is_inert(plugin, tmp_path):
    assert plugin._pre_final(final_response="Done.", workspace_root=str(tmp_path)) is None
    root = _workspace(tmp_path)
    decision = root / "run" / "state" / "runtime" / "lucid-host-role.json"
    decision.unlink()
    decision.symlink_to(root / "quine" / "canon" / "roles.json")
    assert plugin.required_terminal_suffix(root) is None
    assert plugin._pre_final(final_response="Done.", workspace_root=str(root)) is None


def test_registers_attestation_lifecycle_hooks(plugin):
    registered = []

    class Context:
        def register_hook(self, name, callback):
            registered.append((name, callback))

    plugin.register(Context())
    assert registered == [
        ("pre_final", plugin._pre_final),
        ("post_final", plugin._post_final),
        ("transform_tool_result", plugin._transform_tool_result),
        ("on_session_end", plugin._on_session_end),
    ]


def test_conversation_loop_uses_attestation_hook_not_verify_on_stop():
    source = (Path(__file__).parents[2] / "agent" / "conversation_loop.py").read_text(
        encoding="utf-8"
    )
    assert "get_pre_final_decision" in source
    assert 'invoke_hook(\n                            "post_final"' in source
    assert "_attestation_attempt < 1" not in source
    assert '"attestation_offline"' in source
    assert "build_verify_on_stop_nudge" not in source
    assert "_verification_stop_synthetic" not in source


def test_bundled_plugin_discovers_the_pre_final_hook(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    from hermes_cli.plugins import PluginManager

    manager = PluginManager()
    manager.discover_and_load()
    callbacks = manager._hooks.get("pre_final", [])
    assert any(getattr(callback, "__name__", "") == "_pre_final" for callback in callbacks)
