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


def _workspace(
    root: Path,
    role: str = "EM",
    hat: str = "🎼",
    witness_alias: str = "brianhu",
    witness_glyph: str = "🐧",
) -> Path:
    repository = Path(__file__).parents[3]
    (root / "quine" / "canon").mkdir(parents=True)
    (root / "quine" / "mcp" / "onboarding").mkdir(parents=True)
    (root / "run" / "state" / "runtime").mkdir(parents=True)
    (root / "envelope").mkdir(parents=True)
    (root / "quine" / "canon" / "roles.json").write_text(
        json.dumps(
            {
                "$schema": "ae-roles/1",
                "roles": {
                    role: {"glyph": f"{hat}{witness_glyph}", "hat": hat},
                },
            }
        ),
        encoding="utf-8",
    )
    (root / "quine" / "author-glyphs.json").write_text(
        json.dumps({"schema": "ae-author-glyphs/1", "authors": {witness_alias: witness_glyph}}),
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


def _accepted_submission() -> dict:
    return {
        "model": "\n".join(
            [
                "🟢 LUCID · show · text · fresh",
                "Presentation Audio Accepted=true",
                "Presentation Audio Code=speech-queued",
                "Presentation Audio Status=accepted",
            ]
        )
    }


def test_exact_canonical_suffix_passes_without_synthetic_turn(plugin, tmp_path):
    root = _workspace(tmp_path)
    assert plugin.required_terminal_suffix(root) == "🎼🐧"
    assert plugin._pre_final(final_response="🟢 Done.\n\n🎼🐧", workspace_root=str(root)) is None


def test_final_requires_one_canonical_gestalt_signal(plugin, tmp_path):
    root = _workspace(tmp_path)
    result = plugin._pre_final(
        final_response="Done without semantic signal.\n\n🎼🐧",
        workspace_root=str(root),
    )

    assert result["action"] == "continue"
    assert "CAUSE canonical-gestalt-signal-missing" in result["message"]
    assert "include at least one canonical GESTALT signal" in result["message"]


def test_wrong_permanent_role_hat_is_diagnosed(plugin, tmp_path):
    root = _workspace(tmp_path)
    result = plugin._pre_final(
        final_response="🟢 Done.\n\n🧭🐧",
        workspace_root=str(root),
    )

    assert "CAUSE role-hat-mismatch" in result["message"]
    assert "terminate with exactly 🎼🐧" in result["message"]


def test_wrong_witness_glyph_is_diagnosed_from_active_witness_binding(plugin, tmp_path):
    root = _workspace(tmp_path, witness_alias="brian", witness_glyph="🐧")
    authors = root / "quine" / "author-glyphs.json"
    authors.write_text(
        json.dumps({"schema": "ae-author-glyphs/1", "authors": {"brian": "🐧", "alex": "🦊"}}),
        encoding="utf-8",
    )
    decision = root / "run" / "state" / "runtime" / "lucid-host-role.json"
    decision.write_text(
        json.dumps(
            {
                "schema": "lucid-host-role-decision/1",
                "role": "EM",
                "witness_alias": "brian",
                "witness_glyph": "🐧",
            }
        ),
        encoding="utf-8",
    )

    result = plugin._pre_final(
        final_response="🟢 Done.\n\n🎼🦊",
        workspace_root=str(root),
    )

    assert "CAUSE witness-glyph-mismatch" in result["message"]
    assert plugin.required_terminal_suffix(root) == "🎼🐧"


def test_multiple_witnesses_require_an_explicit_host_binding(plugin, tmp_path):
    root = _workspace(tmp_path)
    (root / "quine" / "author-glyphs.json").write_text(
        json.dumps({"schema": "ae-author-glyphs/1", "authors": {"brian": "🐧", "alex": "🦊"}}),
        encoding="utf-8",
    )

    assert plugin.required_terminal_suffix(root) is None


def test_missing_live_role_binding_allows_one_bounded_recovery_turn(plugin, tmp_path):
    root = _workspace(tmp_path)
    (root / "run" / "state" / "runtime" / "lucid-host-role.json").unlink()

    result = plugin._pre_final(
        final_response="hello",
        workspace_root=str(root),
        attempt=0,
        session_id="offline-bootstrap",
    )

    assert result["action"] == "continue"
    assert result["message"].startswith(
        "⚠️ LUCID · role-session · bootstrap-decision-required"
    )
    assert "blocks finalization only" in result["message"]
    assert "run/state/runtime/lucid-host-role.json" in result["message"]
    assert "OWNER WITNESS" in result["message"]
    assert "mcp__LUCID__get" in result["message"]
    assert '"action":"recover"' in result["message"]
    assert "RUN WITNESS sign-in" in result["message"]

    repeated = plugin._pre_final(
        final_response="ignored recovery",
        workspace_root=str(root),
        attempt=1,
        session_id="offline-bootstrap",
    )
    assert repeated["action"] == "block"
    assert repeated["message"].startswith("🔴 LUCID · role-attestation · offline")


def test_pre_final_remains_inert_outside_ae_workspace(plugin, tmp_path):
    assert plugin._pre_final(final_response="hello", workspace_root=str(tmp_path)) is None


def test_explicit_non_penguin_witness_changes_the_exact_terminal_identity(plugin, tmp_path):
    root = _workspace(tmp_path)
    (root / "quine" / "author-glyphs.json").write_text(
        json.dumps({"schema": "ae-author-glyphs/1", "authors": {"brianhu": "🐧", "alex": "🦊"}}),
        encoding="utf-8",
    )
    (root / "run" / "state" / "runtime" / "lucid-host-role.json").write_text(
        json.dumps(
            {
                "schema": "lucid-host-role-decision/1",
                "role": "EM",
                "witness_alias": "alex",
                "witness_glyph": "🦊",
            }
        ),
        encoding="utf-8",
    )

    assert plugin.required_terminal_suffix(root) == "🎼🦊"
    assert (
        plugin._pre_final(
            final_response="◆ Exact non-penguin witness.\n\n🎼🦊",
            workspace_root=str(root),
        )
        is None
    )


def test_attested_final_submits_once_to_current_role_effigy(plugin, tmp_path, monkeypatch):
    root = _workspace(tmp_path)
    observed = []

    def submit(arguments):
        observed.append(arguments)
        return _accepted_submission()

    monkeypatch.setattr(plugin, "_submit_effigy_speech", submit)
    response = "🟢 The exact final statement.\n\n🎼🐧"
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
            "data": {"schema": "response-final/1", "text": response},
            "presentation": "audio-only",
            "scope": "this",
        }
    ]
    assert plugin._post_final(
        final_response=response,
        workspace_root=str(root),
        session_id="session-1",
    ) is None


def test_attested_final_without_session_id_still_submits(plugin, tmp_path, monkeypatch):
    root = _workspace(tmp_path)
    observed = []
    monkeypatch.setattr(
        plugin,
        "_submit_effigy_speech",
        lambda arguments: observed.append(arguments)
        or _accepted_submission(),
    )

    receipt = plugin._post_final(
        final_response="🟢 Desktop final without an agent session id.\n\n🎼🐧",
        workspace_root=str(root),
        session_id="",
    )

    assert receipt == {"state": "submitted", "code": "effigy-response-final-submitted"}
    assert len(observed) == 1


def test_failed_effigy_submission_releases_exact_once_claim(plugin, tmp_path, monkeypatch):
    root = _workspace(tmp_path)
    responses = iter(
        [{"error": "speech unavailable"}, _accepted_submission()]
    )
    monkeypatch.setattr(plugin, "_submit_effigy_speech", lambda _arguments: next(responses))
    final = "⚠️ Retry this final after transient speech failure.\n\n🎼🐧"

    assert plugin._post_final(
        final_response=final, workspace_root=str(root), session_id="session-retry"
    ) == {"state": "degraded", "code": "effigy-submission-failed"}
    assert plugin._post_final(
        final_response=final, workspace_root=str(root), session_id="session-retry"
    ) == {"state": "submitted", "code": "effigy-response-final-submitted"}


def test_typed_lucid_speech_refusal_is_visible_with_code_and_reason(plugin, capsys):
    refusal = {
        "model": "\n".join(
            [
                "🔴 LUCID · show · text · refused",
                "Presentation Audio Accepted=false",
                "Presentation Audio Code=effigy-transfer-protected-identity-refused",
                "Presentation Audio Effigy Transfer Code=effigy-transfer-protected-identity-refused",
                "Presentation Audio Status=refused",
                "Presentation Audio Detail=protected identity was present in transfer input",
            ]
        )
    }

    assert plugin._effigy_submission_accepted(refusal) is False
    plugin._emit_effigy_warning("EM", "🎼🐧", refusal)
    assert capsys.readouterr().err == (
        "⚠️ 🎼🐧 · 🔎 effigy-transfer-protected-identity-refused: "
        "protected identity was present in transfer input\n"
    )


def test_nested_lucid_refusal_preserves_typed_code_and_reason(plugin, capsys):
    refusal = {
        "presentation": {
            "structuredContent": {
                "schema": "lucid-domain-result/1",
                "refusal": {
                    "code": "penguin-model-connect-failed",
                    "reason": "local effigy transfer worker is unavailable",
                },
            }
        }
    }

    plugin._emit_effigy_warning("EM", "🎼🐧", refusal)
    assert capsys.readouterr().err == "⚠️ 🎼🐧 · 🔎 penguin-model-connect-failed\n"


def test_distinct_effigy_failure_detail_is_not_deduplicated(plugin, capsys):
    refusal = {
        "structuredContent": {
            "refusal": {
                "code": "penguin-transfer-timeout",
                "reason": "registered model exceeded its 2000ms response deadline",
            }
        }
    }

    plugin._emit_effigy_warning("EM", "🎼🐧", refusal)
    assert capsys.readouterr().err == (
        "⚠️ 🎼🐧 · 🔎 penguin-transfer-timeout: "
        "registered model exceeded its 2000ms response deadline\n"
    )


def test_effigy_exception_warning_preserves_cause_and_redacts_secrets(plugin, capsys):
    plugin._emit_effigy_warning(
        "EM",
        "🎼🐧",
        None,
        RuntimeError("speech worker refused token=private-value after queue closure"),
    )

    assert capsys.readouterr().err == (
        "⚠️ 🎼🐧 · 🔎 effigy-submission-failed: "
        "RuntimeError: speech worker refused token=[redacted] after queue closure\n"
    )


def test_post_final_returns_the_exact_typed_effigy_failure(plugin, tmp_path, monkeypatch, capsys):
    root = _workspace(tmp_path)
    refusal = {
        "model": "\n".join(
            [
                "🔴 LUCID · show · text · refused",
                "Presentation Audio Effigy Transfer Code=effigy-transfer-timeout",
                "Presentation Audio Stage=effigy-transfer",
                "Presentation Audio Detail=local transfer exceeded its 2000ms deadline",
            ]
        )
    }
    monkeypatch.setattr(plugin, "_submit_effigy_speech", lambda _arguments: refusal)

    receipt = plugin._post_final(
        final_response="🟢 Bounded final.\n\n🎼🐧",
        workspace_root=str(root),
        session_id="typed-effigy-failure",
    )

    assert receipt == {"state": "degraded", "code": "effigy-transfer-timeout"}
    assert capsys.readouterr().err == (
        "⚠️ 🎼🐧 · 🔎 effigy-transfer-timeout: "
        "local transfer exceeded its 2000ms deadline\n"
    )


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


def test_successful_role_session_recovery_clears_signed_out_state(plugin):
    plugin._SIGNED_OUT_SESSIONS.add("recovered-session")
    plugin._transform_tool_result(
        tool_name="mcp__LUCID__set",
        args={"path": "role-session", "scope": "this", "value": {"action": "recover"}},
        result=json.dumps(
            {
                "structuredContent": {
                    "state": "recovered",
                    "action": "recover",
                    "role": "EM",
                }
            }
        ),
        session_id="recovered-session",
        status="success",
    )

    assert "recovered-session" not in plugin._SIGNED_OUT_SESSIONS


def test_role_and_suffix_come_from_canon_not_prompt_or_model_claim(plugin, tmp_path):
    root = _workspace(tmp_path, role="SIDEKICK", hat="🧭")
    result = plugin._pre_final(
        final_response="I claim I am EM. 🎼🐧",
        workspace_root=str(root),
    )
    assert "terminate with exactly 🧭🐧" in result["message"]


def test_missing_or_symlinked_binding_is_inert_outside_ae_and_blocked_inside(plugin, tmp_path):
    assert plugin._pre_final(final_response="Done.", workspace_root=str(tmp_path)) is None
    root = _workspace(tmp_path)
    decision = root / "run" / "state" / "runtime" / "lucid-host-role.json"
    decision.unlink()
    decision.symlink_to(root / "quine" / "canon" / "roles.json")
    assert plugin.required_terminal_suffix(root) is None
    result = plugin._pre_final(final_response="Done.", workspace_root=str(root))
    assert result["action"] == "block"
    assert "exact live role/witness binding is unavailable" in result["message"]


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
    callbacks = manager._hooks.get("post_final", [])
    assert any(getattr(callback, "__name__", "") == "_post_final" for callback in callbacks)
