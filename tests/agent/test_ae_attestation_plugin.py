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
    (root / "quine" / "canon").mkdir(parents=True)
    (root / "run" / "state" / "runtime").mkdir(parents=True)
    (root / "quine" / "canon" / "roles.json").write_text(
        json.dumps({"$schema": "ae-roles/1", "roles": {role: {"glyph": glyph}}}),
        encoding="utf-8",
    )
    (root / "run" / "state" / "runtime" / "lucid-host-role.json").write_text(
        json.dumps({"schema": "lucid-host-role-decision/1", "role": role}),
        encoding="utf-8",
    )
    return root


def test_exact_canonical_suffix_passes_without_synthetic_turn(plugin, tmp_path):
    root = _workspace(tmp_path)
    assert plugin.required_terminal_suffix(root) == "🎼🐧"
    assert plugin._pre_final(final_response="Done.\n\n🎼🐧", workspace_root=str(root)) is None


def test_missing_suffix_requests_one_content_free_correction(plugin, tmp_path):
    root = _workspace(tmp_path)
    result = plugin._pre_final(final_response="Done.", workspace_root=str(root), attempt=0)
    assert result["action"] == "continue"
    message = result["message"]
    assert "exactly `🎼🐧`" in message
    assert "Do not call tools" in message
    assert "grants no authority" in message
    assert "attests no repository state" in message
    assert plugin._pre_final(final_response="Done.", workspace_root=str(root), attempt=1) is None


def test_role_and_suffix_come_from_canon_not_prompt_or_model_claim(plugin, tmp_path):
    root = _workspace(tmp_path, role="SIDEKICK", glyph="🧭🐧")
    result = plugin._pre_final(
        final_response="I claim I am EM. 🎼🐧",
        workspace_root=str(root),
    )
    assert "exactly `🧭🐧`" in result["message"]


def test_missing_malformed_or_symlinked_canon_is_inert(plugin, tmp_path):
    assert plugin._pre_final(final_response="Done.", workspace_root=str(tmp_path)) is None
    root = _workspace(tmp_path)
    decision = root / "run" / "state" / "runtime" / "lucid-host-role.json"
    decision.unlink()
    decision.symlink_to(root / "quine" / "canon" / "roles.json")
    assert plugin.required_terminal_suffix(root) is None
    assert plugin._pre_final(final_response="Done.", workspace_root=str(root)) is None


def test_registers_only_the_pre_final_hook(plugin):
    registered = []

    class Context:
        def register_hook(self, name, callback):
            registered.append((name, callback))

    plugin.register(Context())
    assert registered == [("pre_final", plugin._pre_final)]


def test_conversation_loop_uses_attestation_hook_not_verify_on_stop():
    source = (Path(__file__).parents[2] / "agent" / "conversation_loop.py").read_text(
        encoding="utf-8"
    )
    assert "get_pre_final_continue_message" in source
    assert "_attestation_attempt < 1" in source
    assert "build_verify_on_stop_nudge" not in source
    assert "_verification_stop_synthetic" not in source


def test_bundled_plugin_discovers_the_pre_final_hook(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    from hermes_cli.plugins import PluginManager

    manager = PluginManager()
    manager.discover_and_load()
    callbacks = manager._hooks.get("pre_final", [])
    assert any(getattr(callback, "__name__", "") == "_pre_final" for callback in callbacks)
