from agent.generated.ae_glyphs import OPERATION_STEER
from agent.generated.ae_glyphs import SIGNAL_WARNING
from agent.generated.ae_glyphs import SIGNAL_RED
from agent.generated.ae_glyphs import SIGNAL_GREEN
from agent.generated.ae_glyphs import IDENTITY_PENGUIN
from agent.generated.ae_glyphs import DELIMITER_SEGMENT
from agent.generated.ae_glyphs import IDENTITY_CATALYST
from agent.generated.ae_glyphs import IDENTITY_QUINE
from agent.generated.ae_glyphs import ROLE_EM
import importlib.util
import json
from pathlib import Path

import pytest

from hermes_gestalt import canonical_stream, parse_stream


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
    hat: str = ROLE_EM,
    witness_alias: str = "brianhu",
    witness_glyph: str = f"{IDENTITY_PENGUIN}",
) -> Path:
    repository = Path(__file__).parents[3]
    (root / "quine" / "canon").mkdir(parents=True)
    (root / "quine" / "mcp" / "onboarding").mkdir(parents=True)
    (root / "run" / "state" / "runtime").mkdir(parents=True)
    (root / "envelope").mkdir(parents=True)
    (root / "quine" / "canon" / "GLYPH.json").write_bytes(
        (repository / "quine" / "canon" / "GLYPH.json").read_bytes()
    )
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
    (root / "envelope" / "GESTALT.json").write_text(
        (repository / "envelope" / "GESTALT.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    for name in ["index.json", "universal.md", f"{role.lower()}.md"]:
        (root / "quine" / "mcp" / "onboarding" / name).write_text(
            (repository / "quine" / "mcp" / "onboarding" / name).read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    return root


def _accepted_submission() -> dict:
    root = Path(__file__).parents[3]
    return {
        "model": canonical_stream(
            root,
            f"{SIGNAL_GREEN}",
            "show",
            "text",
            "fresh",
            data=(
                "Presentation Audio Accepted=true",
                "Presentation Audio Code=speech-queued",
                "Presentation Audio Status=accepted",
            ),
        )
    }


def test_exact_canonical_suffix_passes_without_synthetic_turn(plugin, tmp_path):
    root = _workspace(tmp_path)
    assert plugin.required_terminal_suffix(root) == f"{ROLE_EM}{IDENTITY_PENGUIN}"
    assert plugin._pre_final(final_response=f"{SIGNAL_GREEN} Done.\n\n{ROLE_EM}{IDENTITY_PENGUIN}", workspace_root=str(root)) is None


def test_penguin_session_uses_canonical_double_penguin_not_host_role(plugin, tmp_path):
    root = _workspace(tmp_path, role="EM", hat=ROLE_EM)
    registry_path = root / "quine" / "canon" / "roles.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["roles"]["PENGUIN"] = {
        "automation": "host",
        "behavior_tag": "penguin_only",
        "hat": f"{IDENTITY_PENGUIN}",
        "lease": "PENGUIN.md",
    }
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    repository = Path(__file__).parents[3]
    (root / "quine" / "mcp" / "onboarding" / "penguin.md").write_text(
        (repository / "quine" / "mcp" / "onboarding" / "penguin.md").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )

    assert (
        plugin._pre_final(
            final_response=f"{SIGNAL_GREEN} Local observation.\n\n{IDENTITY_PENGUIN}{IDENTITY_PENGUIN}",
            workspace_root=str(root),
            agent_role="PENGUIN",
        )
        is None
    )
    result = plugin._pre_final(
        final_response=f"{SIGNAL_GREEN} Local observation.\n\n{IDENTITY_PENGUIN}{IDENTITY_PENGUIN} COMPLETE",
        workspace_root=str(root),
        agent_role="PENGUIN",
    )
    assert result["action"] == "continue"
    stream = parse_stream(root, result["message"].splitlines()[0])
    assert stream["service"] == IDENTITY_CATALYST
    assert stream["data"] == [IDENTITY_QUINE]
    assert stream["continuations"] == [f"{IDENTITY_PENGUIN}"]
    assert DELIMITER_SEGMENT.join(("ROLE PROTOCOL", "PENGUIN")) in result["message"]

    terminal = plugin._pre_final(
        final_response="Still missing the terminal glyphs.",
        workspace_root=str(root),
        agent_role="PENGUIN",
        attempt=1,
        session_id="penguin-offline",
    )
    assert terminal["action"] == "block"
    assert terminal["message"].endswith(
        f"{IDENTITY_PENGUIN}{IDENTITY_PENGUIN}"
    )
    terminal_stream = parse_stream(root, terminal["message"].splitlines()[0])
    assert terminal_stream["evidence"] == [
        "ROLE-ATTESTATION-PROTOCOL-DRIFT",
        "repeated-role-protocol-drift",
    ]
    assert terminal_stream["actions"] == []


def test_final_requires_one_canonical_gestalt_signal(plugin, tmp_path):
    root = _workspace(tmp_path)
    result = plugin._pre_final(
        final_response=f"Done without semantic signal.\n\n{ROLE_EM}{IDENTITY_PENGUIN}",
        workspace_root=str(root),
    )

    assert result["action"] == "continue"
    stream = parse_stream(root, result["message"].splitlines()[0])
    assert "canonical-gestalt-signal-missing" in stream["evidence"]
    assert stream["continuations"] == [ROLE_EM]


def test_wrong_permanent_role_hat_is_diagnosed(plugin, tmp_path):
    root = _workspace(tmp_path)
    result = plugin._pre_final(
        final_response=f"{SIGNAL_GREEN} Done.\n\n{OPERATION_STEER}{IDENTITY_PENGUIN}",
        workspace_root=str(root),
    )

    stream = parse_stream(root, result["message"].splitlines()[0])
    assert "role-hat-mismatch" in stream["evidence"]
    assert stream["continuations"] == [ROLE_EM]


def test_wrong_witness_glyph_is_diagnosed_from_active_witness_binding(plugin, tmp_path):
    root = _workspace(tmp_path, witness_alias="brian", witness_glyph=f"{IDENTITY_PENGUIN}")
    authors = root / "quine" / "author-glyphs.json"
    authors.write_text(
        json.dumps({"schema": "ae-author-glyphs/1", "authors": {"brian": f"{IDENTITY_PENGUIN}", "alex": "🦊"}}),
        encoding="utf-8",
    )
    decision = root / "run" / "state" / "runtime" / "lucid-host-role.json"
    decision.write_text(
        json.dumps(
            {
                "schema": "lucid-host-role-decision/1",
                "role": "EM",
                "witness_alias": "brian",
                "witness_glyph": f"{IDENTITY_PENGUIN}",
            }
        ),
        encoding="utf-8",
    )

    result = plugin._pre_final(
        final_response=f"{SIGNAL_GREEN} Done.\n\n{ROLE_EM}🦊",
        workspace_root=str(root),
    )

    stream = parse_stream(root, result["message"].splitlines()[0])
    assert "witness-glyph-mismatch" in stream["evidence"]
    assert plugin.required_terminal_suffix(root) == f"{ROLE_EM}{IDENTITY_PENGUIN}"


def test_multiple_witnesses_require_an_explicit_host_binding(plugin, tmp_path):
    root = _workspace(tmp_path)
    (root / "quine" / "author-glyphs.json").write_text(
        json.dumps({"schema": "ae-author-glyphs/1", "authors": {"brian": f"{IDENTITY_PENGUIN}", "alex": "🦊"}}),
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
    stream = parse_stream(root, result["message"])
    assert stream["signal"] == f"{SIGNAL_WARNING}"
    assert stream["service"] == IDENTITY_CATALYST
    assert stream["verb"] is None
    assert stream["evidence"][0] == "BOOTSTRAP-DECISION-REQUIRED"
    assert stream["data"] == [IDENTITY_QUINE]
    assert "\n" not in result["message"]
    assert any(
        action["verb"] == "get" and action["noun"] == "role"
        for action in stream["actions"]
    )
    recover = next(action for action in stream["actions"] if action["verb"] == "set")
    assert recover["noun"] == "role"
    assert recover["arguments"] == ["RECOVER"]
    for leaked in ["lucid://", "envelope/", "QUINE", "WITNESS", "mcp__"]:
        assert leaked not in result["message"]

    repeated = plugin._pre_final(
        final_response="ignored recovery",
        workspace_root=str(root),
        attempt=1,
        session_id="offline-bootstrap",
    )
    assert repeated is None


def test_pre_final_remains_inert_outside_ae_workspace(plugin, tmp_path):
    assert plugin._pre_final(final_response="hello", workspace_root=str(tmp_path)) is None


def test_explicit_non_penguin_witness_changes_the_exact_terminal_identity(plugin, tmp_path):
    root = _workspace(tmp_path)
    (root / "quine" / "author-glyphs.json").write_text(
        json.dumps({"schema": "ae-author-glyphs/1", "authors": {"brianhu": f"{IDENTITY_PENGUIN}", "alex": "🦊"}}),
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

    assert plugin.required_terminal_suffix(root) == f"{ROLE_EM}🦊"
    assert (
        plugin._pre_final(
            final_response=f"{SIGNAL_GREEN} Exact non-penguin witness.\n\n{ROLE_EM}🦊",
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
    response = f"{SIGNAL_GREEN} The exact final statement.\n\n{ROLE_EM}{IDENTITY_PENGUIN}"
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
        final_response=f"{SIGNAL_GREEN} Desktop final without an agent session id.\n\n{ROLE_EM}{IDENTITY_PENGUIN}",
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
    final = f"{SIGNAL_WARNING} Retry this final after transient speech failure.\n\n{ROLE_EM}{IDENTITY_PENGUIN}"

    assert plugin._post_final(
        final_response=final, workspace_root=str(root), session_id="session-retry"
    ) == {"state": "degraded", "code": "effigy-submission-failed"}
    assert plugin._post_final(
        final_response=final, workspace_root=str(root), session_id="session-retry"
    ) == {"state": "submitted", "code": "effigy-response-final-submitted"}


def test_typed_lucid_speech_refusal_is_visible_with_code_and_reason(plugin, capsys):
    root = Path(__file__).parents[3]
    refusal = {
        "model": "\n".join(
            [
                canonical_stream(root, f"{SIGNAL_RED}", "show", "text", "refused"),
                "Presentation Audio Accepted=false",
                "Presentation Audio Code=effigy-transfer-protected-identity-refused",
                "Presentation Audio Effigy Transfer Code=effigy-transfer-protected-identity-refused",
                "Presentation Audio Status=refused",
                "Presentation Audio Detail=protected identity was present in transfer input",
            ]
        )
    }

    assert plugin._effigy_submission_accepted(refusal) is False
    plugin._emit_effigy_warning("EM", f"{ROLE_EM}{IDENTITY_PENGUIN}", refusal)
    warning = parse_stream(root, capsys.readouterr().err.strip())
    assert warning["signal"] == f"{SIGNAL_WARNING}"
    assert warning["evidence"] == [
        "EFFIGY-TRANSFER-PROTECTED-IDENTITY-REFUSED: protected identity was present in transfer input"
    ]
    assert warning["data"] == [f"{ROLE_EM}{IDENTITY_PENGUIN}"]


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

    plugin._emit_effigy_warning("EM", f"{ROLE_EM}{IDENTITY_PENGUIN}", refusal)
    warning = parse_stream(Path(__file__).parents[3], capsys.readouterr().err.strip())
    assert warning["evidence"] == ["PENGUIN-MODEL-CONNECT-FAILED"]
    assert warning["data"] == [f"{ROLE_EM}{IDENTITY_PENGUIN}"]


def test_distinct_effigy_failure_detail_is_not_deduplicated(plugin, capsys):
    refusal = {
        "structuredContent": {
            "refusal": {
                "code": "penguin-transfer-timeout",
                "reason": "registered model exceeded its 2000ms response deadline",
            }
        }
    }

    plugin._emit_effigy_warning("EM", f"{ROLE_EM}{IDENTITY_PENGUIN}", refusal)
    warning = parse_stream(Path(__file__).parents[3], capsys.readouterr().err.strip())
    assert warning["evidence"] == [
        "PENGUIN-TRANSFER-TIMEOUT: registered model exceeded its 2000ms response deadline"
    ]


def test_canonical_mcp_gestalt_refusal_supplies_typed_effigy_detail(plugin, capsys):
    root = Path(__file__).parents[3]
    refusal = {
        "isError": True,
        "content": [
            {
                "type": "text",
                "text": canonical_stream(
                    root,
                    f"{SIGNAL_RED}",
                    evidence=("PENGUIN-MODEL-CONNECT-FAILED",),
                    data=("loopback model endpoint refused the connection",),
                ),
            }
        ],
    }

    plugin._emit_effigy_warning("PENGUIN", f"{IDENTITY_PENGUIN}{IDENTITY_PENGUIN}", refusal)
    warning = parse_stream(root, capsys.readouterr().err.strip())
    assert warning["evidence"] == [
        "PENGUIN-MODEL-CONNECT-FAILED: loopback model endpoint refused the connection"
    ]
    assert warning["data"] == [f"{IDENTITY_PENGUIN}{IDENTITY_PENGUIN}"]


def test_effigy_exception_warning_preserves_cause_and_redacts_secrets(plugin, capsys):
    plugin._emit_effigy_warning(
        "EM",
        f"{ROLE_EM}{IDENTITY_PENGUIN}",
        None,
        RuntimeError("speech worker refused token=private-value after queue closure"),
    )

    warning = parse_stream(Path(__file__).parents[3], capsys.readouterr().err.strip())
    assert warning["evidence"] == [
        "EFFIGY-SUBMISSION-FAILED: RuntimeError: speech worker refused token=[redacted] after queue closure"
    ]


def test_effigy_compound_detail_uses_separate_semantic_atoms(plugin, capsys):
    root = Path(__file__).parents[3]
    plugin._emit_effigy_warning(
        "EM", f"{ROLE_EM}{IDENTITY_PENGUIN}", None,
        RuntimeError(f"connection refused{DELIMITER_SEGMENT}token=private-value"),
    )
    rendered = capsys.readouterr().err.strip()
    warning = parse_stream(root, rendered)
    assert warning["evidence"] == ["EFFIGY-SUBMISSION-FAILED: RuntimeError: connection refused"]
    assert warning["data"] == ["token=[redacted]", f"{ROLE_EM}{IDENTITY_PENGUIN}"]
    assert " / " not in rendered
    assert "private-value" not in rendered


def test_shared_serializer_refuses_nested_separator_instead_of_rewriting_it():
    root = Path(__file__).parents[3]
    with pytest.raises(ValueError, match="canonical separator"):
        canonical_stream(root, SIGNAL_WARNING, evidence=(f"first{DELIMITER_SEGMENT}second",))


def test_canonical_refusal_in_error_field_is_not_flattened_into_slash_prose(plugin, capsys):
    root = Path(__file__).parents[3]
    refusal = {
        "error": canonical_stream(
            root,
            f"{SIGNAL_RED}",
            "show",
            "text",
            "no-capability",
            evidence=("capability is required", "no-capability"),
        )
    }

    plugin._emit_effigy_warning("PENGUIN", f"{IDENTITY_PENGUIN}{IDENTITY_PENGUIN}", refusal)
    rendered = capsys.readouterr().err.strip()
    warning = parse_stream(root, rendered)
    assert warning["evidence"] == ["NO-CAPABILITY: capability is required"]
    assert " / " not in rendered


def test_post_final_returns_the_exact_typed_effigy_failure(plugin, tmp_path, monkeypatch, capsys):
    root = _workspace(tmp_path)
    refusal = {
        "model": "\n".join(
            [
                canonical_stream(root, f"{SIGNAL_RED}", "show", "text", "refused"),
                "Presentation Audio Effigy Transfer Code=effigy-transfer-timeout",
                "Presentation Audio Stage=effigy-transfer",
                "Presentation Audio Detail=local transfer exceeded its 2000ms deadline",
            ]
        )
    }
    monkeypatch.setattr(plugin, "_submit_effigy_speech", lambda _arguments: refusal)

    receipt = plugin._post_final(
        final_response=f"{SIGNAL_GREEN} Bounded final.\n\n{ROLE_EM}{IDENTITY_PENGUIN}",
        workspace_root=str(root),
        session_id="typed-effigy-failure",
    )

    assert receipt == {"state": "degraded", "code": "effigy-transfer-timeout"}
    warning = parse_stream(root, capsys.readouterr().err.strip())
    assert warning["evidence"] == [
        "EFFIGY-TRANSFER-TIMEOUT: local transfer exceeded its 2000ms deadline"
    ]
    assert warning["data"] == [f"{ROLE_EM}{IDENTITY_PENGUIN}"]


@pytest.mark.parametrize("container", ["error", "model", "content", "exception"])
def test_transport_coordinate_refusal_is_preserved_without_slash_rewriting(plugin, capsys, container):
    root = Path(__file__).parents[3]
    text = canonical_stream(
        root, SIGNAL_RED, "show", "transport", "MCP-UNAVAILABLE",
        evidence=("MCP server 'LUCID' is unreachable after 3 connection attempts",),
    )
    result = {container: text}
    cause = None
    if container == "content":
        result = {"content": [{"type": "text", "text": text}]}
    elif container == "exception":
        result, cause = None, RuntimeError(text)
    fields = plugin._emit_effigy_warning("EM", f"{ROLE_EM}{IDENTITY_PENGUIN}", result, cause)
    rendered = capsys.readouterr().err.strip()
    warning = parse_stream(root, rendered)
    assert fields[1] == "mcp-unavailable"
    assert warning["evidence"] == ["MCP-UNAVAILABLE: MCP server 'LUCID' is unreachable after 3 connection attempts"]
    assert " / " not in rendered
    assert "EFFIGY-SUBMISSION-FAILED" not in rendered


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
    stream = parse_stream(root, message.splitlines()[0])
    assert stream["signal"] == f"{SIGNAL_WARNING}"
    assert "ROLE-ATTESTATION-PROTOCOL-DRIFT" in stream["evidence"]
    assert stream["service"] == IDENTITY_CATALYST
    assert stream["data"] == [IDENTITY_QUINE]
    assert stream["continuations"] == [ROLE_EM]
    assert DELIMITER_SEGMENT.join(("ROLE PROTOCOL", "UNIVERSAL")) in message
    assert DELIMITER_SEGMENT.join(("ROLE PROTOCOL", "EM")) in message
    assert "lucid://" not in message

    signout = plugin._pre_final(
        final_response="Still drifted.", workspace_root=str(root), attempt=1, session_id="drift"
    )
    assert signout["action"] == "continue"
    signout_stream = parse_stream(root, signout["message"])
    assert signout_stream["service"] == IDENTITY_CATALYST
    assert signout_stream["evidence"] == [
        "ROLE-ATTESTATION-PROTOCOL-DRIFT",
        "terminal-attestation-missing",
    ]
    assert signout_stream["data"] == [IDENTITY_QUINE]
    assert signout_stream["actions"][0]["verb"] == "set"
    assert signout_stream["actions"][0]["noun"] == "role"
    assert signout_stream["actions"][0]["arguments"] == ["SIGNOUT"]
    for leaked in ["lucid://", "envelope/", "QUINE", "WITNESS", "mcp__"]:
        assert leaked not in signout["message"]

    repeated = plugin._pre_final(
        final_response="Ignored signout.", workspace_root=str(root), attempt=2, session_id="drift"
    )
    assert repeated["action"] == "block"
    assert repeated["message"].endswith(f"{ROLE_EM}{IDENTITY_PENGUIN}")
    repeated_stream = parse_stream(root, repeated["message"].splitlines()[0])
    assert repeated_stream["evidence"] == [
        "ROLE-ATTESTATION-PROTOCOL-DRIFT",
        "repeated-role-protocol-drift",
    ]
    assert repeated_stream["data"] == [IDENTITY_QUINE, "OFFLINE", "RESUME WITNESS"]
    assert repeated_stream["actions"] == []

    terminal = plugin._pre_final(
        final_response="Still offline.", workspace_root=str(root), attempt=3, session_id="drift"
    )
    assert terminal == repeated

    plugin._transform_tool_result(
        tool_name="mcp__LUCID__set",
        args={"path": "role-session", "scope": "this", "value": {"action": "signout"}},
        result=json.dumps({"structuredContent": {"state": "signout"}}),
        session_id="drift",
        status="success",
    )
    released = plugin._pre_final(
        final_response="Signed out.", workspace_root=str(root), attempt=2, session_id="drift"
    )
    assert released is None


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
    assert "recovered-session" in plugin._LIVE_LIFECYCLE_SESSIONS


def test_canonical_penguin_role_signin_tracks_live_session(plugin):
    plugin._transform_tool_result(
        tool_name="mcp__LUCID__set",
        args={"path": "role", "value": {"action": "signin"}},
        result=json.dumps(
            {"structuredContent": {"state": "signed-in", "role": "PENGUIN"}}
        ),
        session_id="penguin-session",
        status="success",
    )

    assert "penguin-session" in plugin._LIVE_LIFECYCLE_SESSIONS


def test_confirmed_capability_bound_witness_preserves_substantive_final(plugin, tmp_path):
    root = _workspace(tmp_path)
    (root / "run" / "state" / "runtime" / "lucid-host-role.json").write_text(
        json.dumps(
            {
                "schema": "lucid-host-role-decision/1",
                "role": "WITNESS",
                "witness_alias": "brianhu",
                "witness_glyph": f"{IDENTITY_PENGUIN}",
            }
        ),
        encoding="utf-8",
    )
    plugin._transform_tool_result(
        tool_name="mcp__LUCID__set",
        args={"path": "role-session", "scope": "this", "value": {"action": "recover"}},
        result=json.dumps(
            {"structuredContent": {"state": "bound", "role": "WITNESS"}}
        ),
        session_id="capability-bound-witness",
        status="success",
    )

    assert (
        plugin._pre_final(
            final_response="Substantive EM result without an injected replacement.",
            workspace_root=str(root),
            attempt=1,
            session_id="capability-bound-witness",
        )
        is None
    )


def test_unconfirmed_or_noncanonical_witness_preserves_finalization(plugin, tmp_path):
    root = _workspace(tmp_path)
    decision = root / "run" / "state" / "runtime" / "lucid-host-role.json"
    decision.write_text(
        json.dumps(
            {
                "schema": "lucid-host-role-decision/1",
                "role": "WITNESS",
                "witness_alias": "brianhu",
                "witness_glyph": f"{IDENTITY_PENGUIN}",
            }
        ),
        encoding="utf-8",
    )
    unconfirmed = plugin._pre_final(
        final_response="Unconfirmed.",
        workspace_root=str(root),
        attempt=1,
        session_id="unconfirmed-witness",
    )
    assert unconfirmed is None

    plugin._LIVE_LIFECYCLE_SESSIONS.add("noncanonical-witness")
    decision.write_text(
        json.dumps(
            {
                "schema": "lucid-host-role-decision/1",
                "role": "WITNESS",
                "witness_alias": "brianhu",
                "witness_glyph": "🦊",
            }
        ),
        encoding="utf-8",
    )
    noncanonical = plugin._pre_final(
        final_response="Noncanonical.",
        workspace_root=str(root),
        attempt=1,
        session_id="noncanonical-witness",
    )
    assert noncanonical is None


def test_role_lifecycle_terminal_states_are_action_specific(plugin):
    assert plugin._role_action_settled({"state": "signed-in"}, "recover")
    assert plugin._role_action_settled({"state": "bound"}, "signin")
    assert plugin._role_action_settled({"state": "unbound"}, "signout")
    assert not plugin._role_action_settled({"state": "unbound"}, "recover")
    assert not plugin._role_action_settled({"state": "signed-in"}, "signout")


def test_role_and_suffix_come_from_canon_not_prompt_or_model_claim(plugin, tmp_path):
    root = _workspace(tmp_path, role="SIDEKICK", hat=f"{OPERATION_STEER}")
    result = plugin._pre_final(
        final_response=f"I claim I am EM. {ROLE_EM}{IDENTITY_PENGUIN}",
        workspace_root=str(root),
    )
    stream = parse_stream(root, result["message"].splitlines()[0])
    assert stream["continuations"] == [f"{OPERATION_STEER}"]


def test_missing_or_symlinked_binding_never_replaces_the_final(plugin, tmp_path):
    assert plugin._pre_final(final_response="Done.", workspace_root=str(tmp_path)) is None
    root = _workspace(tmp_path)
    decision = root / "run" / "state" / "runtime" / "lucid-host-role.json"
    decision.unlink()
    decision.symlink_to(root / "quine" / "canon" / "roles.json")
    assert plugin.required_terminal_suffix(root) is None
    result = plugin._pre_final(final_response="Done.", workspace_root=str(root))
    assert result is None


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
