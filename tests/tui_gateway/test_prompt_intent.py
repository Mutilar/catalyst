import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from tui_gateway import prompt_intent
from hermes_gestalt import canonical_stream, parse_stream
from agent.generated.ae_glyphs import SIGNAL_GREEN, SIGNAL_PENDING
from tui_gateway.lucid_traversal import Traversal, MAX_STEPS


SUBMISSION = "submission-000000000001"
ROOT = Path(__file__).resolve().parents[3]


def gestalt(channel, text, *labels, signal=SIGNAL_GREEN):
    if channel in {"CLI", "LUCID"}:
        return canonical_stream(ROOT, signal, data=("Requested invocation",)) + f"\n\n➡️ `{text}`"
    return canonical_stream(ROOT, signal, data=(text,))


CLI_OPERATION = {"channel": "cli", "executable": "git", "argv": ["status"]}
CLI_RESPONSE = "🤖"
CLI_PROPOSAL = {"classification": "direct", "operation": CLI_OPERATION, "classifier_response": CLI_RESPONSE}


@pytest.mark.parametrize("signal", ["🟢", "⏳", "⚠️", "🔴"])
def test_byte_zero_canonical_signal_skips_all_penguin_work(tmp_path, monkeypatch, signal):
    text = signal + ' · ◆ Preserve this\n\n| Value | Literal |\n|---|---|\n| 1 | [200~ |\n'
    forbidden = Mock(side_effect=AssertionError("preprocessing must be bypassed"))
    for name in ("classify", "format_semantic", "format_lucid", "cached_candidate", "_journal", "execute_direct"):
        monkeypatch.setattr(prompt_intent, name, forbidden)
    progress = Mock()
    result = prompt_intent.admit_prompt(text, SUBMISSION, "session", "/workspace", tmp_path, on_preparation=progress)
    assert result["prepared_text"] == text
    assert result["admission"]["penguin_bypassed"] is True
    assert result["admission"]["stages"] == []
    forbidden.assert_not_called()
    progress.assert_not_called()


@pytest.mark.parametrize("text", [" 🟢 request", "\n🔴 request", "\ufeff🟢 request", "text 🟢", "🧠", "🤖", "🔎", "⚠", "\x1b[200~🟢 request"])
def test_nonzero_or_noncanonical_signals_do_not_shortcut(tmp_path, monkeypatch, text):
    assert not prompt_intent.has_canonical_signal_prefix(text)
    classifier = Mock(return_value="invalid")
    monkeypatch.setattr(prompt_intent, "classify", classifier)
    result = prompt_intent.admit_prompt(text, SUBMISSION, "session", "/workspace", tmp_path)
    classifier.assert_called_once()
    assert "prepared_text" not in result


def test_canonical_bypass_retains_the_existing_input_bound(tmp_path):
    result = prompt_intent.admit_prompt("🟢" + "x" * prompt_intent.MAX_INPUT_BYTES,
        SUBMISSION, "session", "/workspace", tmp_path)
    assert result["direct_operation"]["diagnostic"]["receipt"]["refusal"] == "input-bound"


@pytest.mark.parametrize("bypass", [False, True])
def test_rpc_passes_untransformed_input_unchanged_to_agent_dispatch(tmp_path, monkeypatch, bypass):
    import threading
    from tui_gateway import server

    text = '  Keep literal [200~ content\n' if bypass else '🟢 · ◆ Keep literal [200~ content\n'
    if bypass:
        monkeypatch.setattr(prompt_intent, "classify", Mock(side_effect=ValueError("penguin-response-incomplete")))
        prompt_intent.admit_prompt(text, SUBMISSION, "session", "/workspace", tmp_path)
    session = {"session_key": "session", "running": False, "history": [], "history_lock": threading.Lock()}
    monkeypatch.setattr(server, "_sessions", {"runtime": session})
    monkeypatch.setattr(server, "get_hermes_home", lambda: tmp_path)
    monkeypatch.setattr(server, "_session_cwd", lambda current: "/workspace")
    monkeypatch.setattr(server, "_load_dashboard_process_isolation_config", lambda: {})
    monkeypatch.setattr(server, "_session_uses_compute_host", lambda *args: True)
    monkeypatch.setattr(server, "current_transport", lambda: None)
    inflight = Mock()
    dispatch = Mock(return_value={"result": {"status": "streaming"}})
    monkeypatch.setattr(server, "_start_inflight_turn", inflight)
    monkeypatch.setattr(server, "_submit_prompt_to_compute_host", dispatch)
    classifier = Mock(side_effect=AssertionError("unexpected classification"))
    monkeypatch.setattr(prompt_intent, "classify", classifier)
    result = server._methods["prompt.submit"]("request", {
        "session_id": "runtime", "submission_id": SUBMISSION + "-recovery" if bypass else SUBMISSION, "text": text,
        **({"penguin_recovery": {"submission_id": SUBMISSION, "action": "bypass"}} if bypass else {})})
    assert result == dispatch.return_value
    dispatch.assert_called_once_with("request", "runtime", session, text)
    inflight.assert_called_once_with(session, text)
    classifier.assert_not_called()


@pytest.mark.parametrize("text,operation", [
    ("git diff --stat", {"channel": "cli", "executable": "git", "argv": ["diff", "--stat"]}),
    ("rg -n TODO src", {"channel": "cli", "executable": "rg", "argv": ["-n", "TODO", "src"]}),
    ("custom-cli inspect --format=json", {"channel": "cli", "executable": "custom-cli", "argv": ["inspect", "--format=json"]}),
    ("lucid show --args '{\"view\":\"pulse\"}'", {"channel": "lucid", "verb": "show", "argv": ["--args", '{"view":"pulse"}']}),
])
def test_new_invocations_share_classification_execution_and_inline_results(tmp_path, monkeypatch, text, operation):
    response = "🧠" if operation["channel"] == "lucid" else "🤖"
    candidate = {"classification": "direct", "operation": operation, "classifier_response": response}
    monkeypatch.setattr(prompt_intent, "classify", Mock(return_value=response))
    formatter = Mock(side_effect=AssertionError("direct routes must not format"))
    monkeypatch.setattr(prompt_intent, "format_semantic", formatter)
    execute = Mock(return_value={"operation": operation, "ran": True, "exit_code": 0, "stdout": "result"})
    monkeypatch.setattr(prompt_intent, "execute_direct", execute)
    result = prompt_intent.admit_prompt(text, SUBMISSION, "session", "/workspace", tmp_path)
    execute.assert_called_once_with(SUBMISSION, "/workspace", operation)
    assert "prepared_text" not in result
    assert result["direct_operation"]["diagnostic"]["proposal"] == candidate
    assert prompt_intent.cached_candidate(tmp_path, text) == candidate
    formatter.assert_not_called()


def test_formatter_prompt_selects_only_protocol_and_gestalt_behavior(monkeypatch):
    response = gestalt("SEMANTIC", "Explain the program.")
    connection = Mock()
    connection.getresponse.return_value.status = 200
    connection.getresponse.return_value.read.return_value = json.dumps({"choices": [
        {"finish_reason": "stop", "message": {"content": response}}]}).encode()
    monkeypatch.setattr(prompt_intent.http.client, "HTTPConnection", Mock(return_value=connection))
    assert prompt_intent.format_semantic("custom-cli") == response
    body = json.loads(connection.request.call_args.args[2])
    instruction = body["messages"][0]["content"]
    assert "response_format" not in body
    canon = json.loads((ROOT / "quine/canon/AGENT_INSTRUCTIONS.json").read_text())
    delta = Path(prompt_intent.__file__).with_name("penguin-preparation.md").read_text()
    assert instruction.endswith(delta)
    for row in canon["rlhf_behavior"]:
        assert (row["definition"] in instruction) == (row["directive"] == "GESTALT")
    assert "SYS" not in instruction and "HATS" not in instruction
    assert "LUCID SHOW/GET ONLY" not in instruction
    assert "json" not in instruction.lower()
    assert "permission" not in instruction.lower()
    assert "CLI, LUCID, SEMANTIC" not in instruction
    assert '` · `' in instruction
    assert '| **GESTALT** |' in instruction
    assert "git status" not in instruction and "lucid get role" not in instruction
    assert body["messages"][1]["content"] == "custom-cli"
    connection.close.assert_called_once()


def test_direct_execution_is_retained_once_outside_model_history(tmp_path, monkeypatch):
    classify = Mock(return_value=CLI_RESPONSE)
    execute = Mock(return_value={"operation": CLI_OPERATION, "ran": True, "exit_code": 0,
        "stdout": "working tree clean", "stderr": "", "refusal": None})
    monkeypatch.setattr(prompt_intent, "classify", classify)
    monkeypatch.setattr(prompt_intent, "execute_direct", execute)
    first = prompt_intent.admit_prompt("git status", SUBMISSION, "session", "/workspace", tmp_path)
    second = prompt_intent.admit_prompt("git status", SUBMISSION, "session", "/workspace", tmp_path)
    assert first == second
    classify.assert_called_once()
    execute.assert_called_once_with(SUBMISSION, "/workspace", CLI_OPERATION)
    assert "prepared_text" not in first
    diagnostic = first["direct_operation"]["diagnostic"]
    assert diagnostic["context_admission"] == "excluded"
    assert set(diagnostic["envelope"]) == {"intent", "capability", "escalation", "fidelity", "refusal", "receipt"}
    assert set(diagnostic["envelope"]["receipt"]) == {"id", "ts", "trust", "content_hash", "ran", "effect"}
    assert diagnostic["envelope"]["fidelity"]["level"] == "lossless"
    history = prompt_intent.operation_history(tmp_path, "session")
    assert len(history) == 1 and history[0]["role"] == "system"
    assert json.loads(history[0]["text"][len("twitch:"):]) == first["direct_operation"]
    assert prompt_intent.operation_history(tmp_path, "other") == []


def test_offline_penguin_is_inline_refusal_not_reasoning(tmp_path, monkeypatch):
    monkeypatch.setattr(prompt_intent, "classify", Mock(side_effect=ConnectionError("offline")))
    execute = Mock()
    monkeypatch.setattr(prompt_intent, "execute_direct", execute)
    result = prompt_intent.admit_prompt("git status", SUBMISSION, "session", "/workspace", tmp_path)
    assert "prepared_text" not in result
    assert result["direct_operation"]["diagnostic"]["receipt"]["ran"] is False
    execute.assert_not_called()


def test_semantic_question_cannot_be_classified_into_execution(tmp_path, monkeypatch):
    monkeypatch.setattr(prompt_intent, "classify", Mock(return_value="🔎"))
    monkeypatch.setattr(prompt_intent, "format_semantic", Mock(return_value=gestalt("SEMANTIC", "Explain what git status means.")))
    execute = Mock()
    monkeypatch.setattr(prompt_intent, "execute_direct", execute)
    result = prompt_intent.admit_prompt("What does git status mean?", SUBMISSION, "session", "/workspace", tmp_path)
    assert "prepared_text" in result
    execute.assert_not_called()


def test_ambiguous_input_cannot_fall_through_to_reasoning(tmp_path, monkeypatch):
    monkeypatch.setattr(prompt_intent, "classify", Mock(return_value=gestalt("CLARIFICATION", "Which scope?", signal=SIGNAL_PENDING)))
    result = prompt_intent.admit_prompt("git status", SUBMISSION, "session", "/workspace", tmp_path)
    assert "prepared_text" not in result
    assert result["direct_operation"]["diagnostic"]["receipt"]["refusal"] == "penguin-classifier-glyph-invalid"


def test_semantic_preparation_preserves_returned_gestalt_and_has_display_only_history(tmp_path, monkeypatch):
    text = "Compare options; do not edit files."
    response = gestalt("SEMANTIC", "Compare the available options.", "OBJECTIVE") + "\n" + gestalt("SEMANTIC", "Do not modify files.", "PROHIBITION")
    monkeypatch.setattr(prompt_intent, "classify", Mock(return_value="🔎"))
    monkeypatch.setattr(prompt_intent, "format_semantic", Mock(return_value=response))
    result = prompt_intent.admit_prompt(text, SUBMISSION, "session", "/workspace", tmp_path)
    assert result["prepared_text"] == response
    assert "Original WITNESS input" not in result["prepared_text"]
    assert parse_stream(ROOT, response.splitlines()[1])["data"] == ["Do not modify files."]
    history = prompt_intent.operation_history(tmp_path, "session")
    assert len(history) == 1 and history[0]["role"] == "system"
    retained = json.loads(history[0]["text"][len("twitch:"):])
    assert retained["diagnostic"]["context_admission"] == "excluded"
    assert retained["diagnostic"]["original_input"] == text
    assert retained["diagnostic"]["transformed_input"] == result["prepared_text"]
    replay = prompt_intent.admit_prompt(text, SUBMISSION, "session", "/workspace", tmp_path)
    assert "prepared_text" not in replay


def test_penguin_progress_precedes_inference_and_exposes_exact_outgoing_wrapper(tmp_path, monkeypatch):
    text = "Explain the EM role"
    response = gestalt("SEMANTIC", "Explain the responsibilities of EM.", "OBJECTIVE")
    events = []

    def classify(source):
        assert source == text
        assert events[0]["diagnostic"]["phase"] == "classification"
        assert events[0]["diagnostic"]["pending"] is True
        return "🔎"

    monkeypatch.setattr(prompt_intent, "classify", classify)
    formatter = Mock(return_value=response)
    monkeypatch.setattr(prompt_intent, "format_semantic", formatter)
    result = prompt_intent.admit_prompt(text, SUBMISSION, "session", "/workspace", tmp_path, on_preparation=events.append)
    assert [event["diagnostic"]["phase"] for event in events] == ["classification", "semantic-preparation", "prepared"]
    formatter.assert_called_once_with(text)
    assert events[-1]["diagnostic"]["classifier_response"] == "🔎"
    diagnostic = events[-1]["diagnostic"]
    assert diagnostic["pending"] is False
    assert diagnostic["original_input"] == text
    assert diagnostic["transformed_input"] == result["prepared_text"]
    assert result["prepared_text"] == response
    assert diagnostic["penguin_response"] == response
    assert diagnostic["proposal"]["gestalt"] == response
    assert diagnostic["authority"] == "none"
    assert diagnostic["origin"] == {"author": "user", "processor": "PENGUIN", "kind": "intent-preparation"}
    assert "document" not in events[-1]
    assert parse_stream(ROOT, events[-1]["source"].split("\n\n", 1)[0])["service"] == "🐧"


def test_semantic_agent_input_contains_only_canonical_streams():
    text = "Compare options; do not edit files."
    response = gestalt("SEMANTIC", "Compare options.", "OBJECTIVE") + "\n" + gestalt("SEMANTIC", "Do not edit files.", "PROHIBITION")
    candidate = prompt_intent.decode_preparation(text, response, ROOT)
    prepared = prompt_intent.prepare_semantic(text, candidate, ROOT)
    streams = [parse_stream(ROOT, line) for line in prepared.splitlines()]
    assert len(streams) == 2
    assert streams[0]["data"] == ["Compare options."]
    assert streams[1]["data"] == ["Do not edit files."]
    assert "Original WITNESS input" not in prepared


def test_penguin_failure_settles_processing_indicator(tmp_path, monkeypatch):
    events = []
    monkeypatch.setattr(prompt_intent, "classify", Mock(side_effect=ConnectionError("offline")))
    prompt_intent.admit_prompt("hello", SUBMISSION, "session", "/workspace", tmp_path, on_preparation=events.append)
    assert events[-1]["diagnostic"]["phase"] == "refused"
    assert events[-1]["diagnostic"]["pending"] is False


@pytest.mark.parametrize("response", ['{"classification":"semantic"}', "Sign in as EM", ""])
def test_non_gestalt_model_responses_refuse(response):
    with pytest.raises(ValueError):
        prompt_intent.decode_preparation("Sign in as EM", response, ROOT)


def test_represented_command_does_not_execute_for_semantic_input():
    mixed = gestalt("SEMANTIC", "Explain the result.", "OBJECTIVE") + "\n\n➡️ `git status`"
    assert prompt_intent.decode_preparation("Explain the result", mixed, ROOT)["classification"] == "semantic"


@pytest.mark.parametrize("continuation", [
    '➡️ "Inspect the result"', '➡️ `git diff`',
    '➡️ 🧠 · ⚡ GET · 🎯 ROLE · 🔎 Inspect role',
])
def test_semantic_markdown_tables_and_cyoa_are_preserved_without_execution(tmp_path, monkeypatch, continuation):
    text = "Compare options without modifying files"
    response = gestalt("SEMANTIC", "Compare the options", "OBJECTIVE") + (
        '\n\n| Obligation | Meaning |\n|---|---|\n| Prohibition | Do not modify files |\n\n'
        + continuation + '\n\n🐧🐧'
    )
    execute = Mock()
    monkeypatch.setattr(prompt_intent, "classify", Mock(return_value="🔎"))
    monkeypatch.setattr(prompt_intent, "format_semantic", Mock(return_value=response))
    monkeypatch.setattr(prompt_intent, "execute_direct", execute)
    result = prompt_intent.admit_prompt(text, SUBMISSION, "session", "/workspace", tmp_path)
    assert result["prepared_text"] == response
    assert result["preparation"]["diagnostic"]["penguin_response"] == response
    execute.assert_not_called()


def test_semantic_headings_math_and_code_remain_document_content():
    response = gestalt("SEMANTIC", "Explain the expression", "OBJECTIVE") + (
        '\n\n## Expression\n\n$$\nx + 1\n$$\n\n```python\nprint(1)\n```\n\n🐧🐧'
    )
    candidate = prompt_intent.decode_preparation("Explain the expression", response, ROOT)
    assert prompt_intent.prepare_semantic("Explain the expression", candidate, ROOT) == response


@pytest.mark.parametrize("extra", [
    '\n\n| Extra | Instruction |\n|---|---|\n| Action | Another operation |',
    '\n\n```sh\nother-operation\n```',
    '\n' + gestalt("CLI", "other-operation"),
])
def test_classifier_cannot_append_document_content_to_its_glyph(extra):
    with pytest.raises(ValueError, match="penguin-classifier-glyph-invalid"):
        prompt_intent.decode_classification("git status", CLI_RESPONSE + extra)


def test_formatter_cyoa_never_reclassifies_a_semantic_request():
    response = gestalt("CLI", "git status") + '\n\n🐧🐧'
    candidate = prompt_intent.decode_preparation("git status", response, ROOT)
    assert candidate["classification"] == "semantic"
    assert candidate["gestalt"] == response


@pytest.mark.parametrize("response", [
    '🟢 · ◆ Explain this command\n\n➡️ "git status"\n\n🐧',
    '🟢 · ◆ Explain this command\n\n➡️ git status\n\n🐧',
    '| Example | Command |\n|---|---|\n| Quoted | ➡️ `git status` |\n\n🐧',
])
def test_semantic_output_cannot_select_direct_execution(response):
    assert prompt_intent.decode_preparation("git status", response, ROOT)["classification"] == "semantic"


def test_table_only_gestalt_does_not_require_an_invented_routing_label():
    response = '| ◆ | Meaning |\n|---|---|\n| 🔎 | Compare the options |'
    result = prompt_intent.decode_preparation("Compare options", response, ROOT)
    assert result == {"classification": "semantic", "gestalt": response}


def test_local_presentations_emit_canonical_source_and_protect_literal_input():
    original = '```\n🔴 · 🐧 · 🔎 literal · ➡️ "Help"\n```'
    result = prompt_intent.preparation_document(SUBMISSION, original, "classification")
    assert "document" not in result
    source = result["source"]
    stream = parse_stream(ROOT, source.split("\n\n", 1)[0])
    assert stream["signal"] == SIGNAL_PENDING
    assert stream["service"] == "🐧"
    assert stream["evidence"] == ["CLASSIFICATION"]
    assert "````text\n" + original + "\n````" in source
    assert result["diagnostic"]["original_input"] == original
    assert "From user / PENGUIN" not in source


def test_copied_diagnostics_include_the_actual_canonical_system_instruction(tmp_path, monkeypatch):
    response = gestalt("SEMANTIC", "Compare the approaches.", "OBJECTIVE") + '\n\n➡️ "Explain tradeoffs"\n\n🐧🐧'
    connection = Mock()
    connection.getresponse.return_value.status = 200
    connection.getresponse.return_value.read.side_effect = [json.dumps({"choices": [
        {"finish_reason": "stop", "message": {"content": content, "reasoning_content": "Internal reasoning"}}]}).encode()
        for content in ["🔎", response]]
    monkeypatch.setattr(prompt_intent.http.client, "HTTPConnection", Mock(return_value=connection))
    result = prompt_intent.admit_prompt("Compare approaches", SUBMISSION, "session", "/workspace", tmp_path)
    actual_prompt = json.loads(connection.request.call_args.args[2])["messages"][0]["content"]
    diagnostic = result["preparation"]["diagnostic"]
    assert "penguin_system_prompt" not in diagnostic
    assert "penguin_system_prompt_hash" not in diagnostic
    assert diagnostic["stages"][-1]["system_prompt"] == actual_prompt
    assert diagnostic["stages"][-1]["system_prompt_hash"] == prompt_intent.input_hash(actual_prompt)
    assert diagnostic["penguin_response"] == response
    assert result["prepared_text"] == response
    calls = [json.loads(call.args[2]) for call in connection.request.call_args_list]
    assert len(calls) == 2
    assert calls[0]["messages"][0]["content"] == prompt_intent.classification_instruction()
    assert calls[0]["max_tokens"] == 8192 and calls[1]["max_tokens"] == 8192
    assert calls[1]["messages"][0]["content"] == prompt_intent.penguin_instruction(ROOT)
    assert [stage["stage"] for stage in diagnostic["stages"]] == ["classification", "semantic-preparation"]
    assert [stage["response"] for stage in diagnostic["stages"]] == ["🔎", response]
    assert all(stage["finish_reason"] == "stop" for stage in diagnostic["stages"])
    assert all(stage["reasoning_chars"] == len("Internal reasoning") for stage in diagnostic["stages"])
    assert "Internal reasoning" not in json.dumps(diagnostic)
    assert all(stage["input"] == "Compare approaches" for stage in diagnostic["stages"])


def test_incomplete_reasoning_response_retains_budget_evidence_without_duplicate_prompt(tmp_path, monkeypatch):
    connection = Mock()
    connection.getresponse.return_value.status = 200
    connection.getresponse.return_value.read.return_value = json.dumps({
        "choices": [{"finish_reason": "length", "message": {"content": None, "reasoning_content": "Still reasoning"}}],
        "usage": {"prompt_tokens": 300, "completion_tokens": 8192, "total_tokens": 8492},
    }).encode()
    monkeypatch.setattr(prompt_intent.http.client, "HTTPConnection", Mock(return_value=connection))
    execute = Mock()
    monkeypatch.setattr(prompt_intent, "execute_direct", execute)
    events = []
    result = prompt_intent.admit_prompt("How's your day going", SUBMISSION, "session", "/workspace", tmp_path,
        on_preparation=events.append)
    diagnostic = result["direct_operation"]["diagnostic"]
    assert diagnostic["receipt"]["refusal"] == "penguin-response-incomplete"
    stage = diagnostic["stages"][0]
    assert stage["finish_reason"] == "length"
    assert stage["max_tokens"] == stage["usage"]["completion_tokens"] == 8192
    assert stage["reasoning_chars"] == len("Still reasoning")
    assert stage["response"] is None
    assert "Still reasoning" not in json.dumps(diagnostic)
    assert "penguin_system_prompt" not in diagnostic
    assert all("penguin_system_prompt" not in event["diagnostic"] for event in events)
    source = result["direct_operation"]["source"]
    assert "document" not in result["direct_operation"]
    assert '🔎 INTENT ADMISSION REFUSED' in source
    assert '◆ FINISH REASON "length"' in source
    assert ' · ➡️ "Retry" · ➡️ "Bypass" · ➡️ "Help"' in source.split("\n\n", 1)[0]
    assert "```text\nHow's your day going\n```" in source
    assert '🔎 OUTPUT' not in source and '🔎 DIAGNOSTICS' not in source
    execute.assert_not_called()


@pytest.mark.parametrize("action", ["retry", "bypass", "help"])
def test_penguin_recovery_uses_retained_original_and_explicit_action(tmp_path, monkeypatch, action):
    original = "  checking testing\n\n"
    classifier = Mock(side_effect=ValueError("penguin-response-incomplete"))
    monkeypatch.setattr(prompt_intent, "classify", classifier)
    prompt_intent.admit_prompt(original, SUBMISSION, "session", "/workspace", tmp_path)
    classifier.reset_mock()
    execute = Mock(return_value={"ran": True, "exit_code": 0})
    monkeypatch.setattr(prompt_intent, "execute_direct", execute)
    result = prompt_intent.admit_prompt("not the retained input", SUBMISSION + "-recovery", "session", "/workspace", tmp_path,
        recovery={"submission_id": SUBMISSION, "action": action})
    if action == "bypass":
        assert result["prepared_text"] == original
        assert result["admission"]["source"] == "witness-penguin-bypass"
        classifier.assert_not_called()
        execute.assert_not_called()
    elif action == "retry":
        classifier.assert_called_once()
        assert result["direct_operation"]["diagnostic"]["original_input"] == original
        assert result["direct_operation"]["diagnostic"]["submission_id"] == SUBMISSION + "-recovery"
        execute.assert_not_called()
    else:
        classifier.assert_not_called()
        execute.assert_called_once_with(SUBMISSION + "-recovery", "/workspace",
            {"channel": "lucid", "verb": "--help", "argv": []})
        assert "direct_operation" in result


@pytest.mark.parametrize("session,workspace", [("other", "/workspace"), ("session", "/other")])
def test_penguin_recovery_cannot_cross_session_or_workspace(tmp_path, monkeypatch, session, workspace):
    monkeypatch.setattr(prompt_intent, "classify", Mock(side_effect=ValueError("penguin-response-incomplete")))
    prompt_intent.admit_prompt("hello", SUBMISSION, "session", "/workspace", tmp_path)
    with pytest.raises(ValueError, match="penguin-recovery-not-found"):
        prompt_intent.admit_prompt("hello", SUBMISSION + "-recovery", session, workspace, tmp_path,
            recovery={"submission_id": SUBMISSION, "action": "bypass"})


def test_penguin_recovery_refuses_an_execution_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(prompt_intent, "classify", Mock(return_value=CLI_RESPONSE))
    monkeypatch.setattr(prompt_intent, "execute_direct", Mock(side_effect=ValueError("executor-response-bound")))
    prompt_intent.admit_prompt("git status", SUBMISSION, "session", "/workspace", tmp_path)
    with pytest.raises(ValueError, match="penguin-recovery-not-eligible"):
        prompt_intent.admit_prompt("git status", SUBMISSION + "-recovery", "session", "/workspace", tmp_path,
            recovery={"submission_id": SUBMISSION, "action": "bypass"})


def test_lucid_uses_its_declared_route_and_retains_original_projection(tmp_path, monkeypatch):
    projected = {"schema": "lucid-ugui-response/1", "id": "role", "type": "document", "header": [], "sections": [], "actions": []}
    operation = {"channel": "lucid", "verb": "get", "argv": ["role"]}
    monkeypatch.setattr(prompt_intent, "classify", Mock(return_value="🧠"))
    execute = Mock(return_value={"ran": True, "exit_code": 0, "operation": operation, "ugui_source": json.dumps(projected)})
    monkeypatch.setattr(prompt_intent, "execute_direct", execute)
    result = prompt_intent.admit_prompt("lucid get role", SUBMISSION, "session", "/workspace", tmp_path)
    execute.assert_called_once_with(SUBMISSION, "/workspace", operation)
    assert result["direct_operation"]["document"] == projected


def test_missing_handoff_never_executes(monkeypatch):
    monkeypatch.setattr(prompt_intent, "_TOKEN", "")
    assert prompt_intent.execute_direct(SUBMISSION, "/workspace", CLI_OPERATION) == {
        "operation": CLI_OPERATION, "refusal": "witness-handoff-unavailable", "ran": False}


def test_direct_wire_request_has_exact_five_field_contract(monkeypatch):
    monkeypatch.setattr(prompt_intent, "_ENDPOINT", "127.0.0.1:12345")
    monkeypatch.setattr(prompt_intent, "_TOKEN", "fixture-token")
    receipt = {"schema": "run-witness-direct/2", "submission_id": SUBMISSION,
        "workspace": "/workspace", "operation": CLI_OPERATION, "ran": True, "exit_code": 0}
    stream = Mock()
    connection = Mock()
    connection.__enter__ = Mock(return_value=stream)
    connection.__exit__ = Mock(return_value=False)
    reader = Mock()
    reader.readline.return_value = (json.dumps(receipt) + "\n").encode()
    file = Mock()
    file.__enter__ = Mock(return_value=reader)
    file.__exit__ = Mock(return_value=False)
    stream.makefile.return_value = file
    monkeypatch.setattr(prompt_intent.socket, "create_connection", Mock(return_value=connection))
    assert prompt_intent.execute_direct(SUBMISSION, "/workspace", CLI_OPERATION) == receipt
    wire = stream.sendall.call_args.args[0]
    assert wire.endswith(b"\n")
    assert json.loads(wire) == {"schema": "run-witness-direct/2", "submission_id": SUBMISSION,
        "workspace": "/workspace", "operation": CLI_OPERATION, "token": "fixture-token"}


@pytest.mark.parametrize("receipt,state,execution", [
    ({"ran": True, "exit_code": 0, "stdout": "On branch main\nworking tree clean\n"}, "COMPLETED", "Ran"),
    ({"ran": False, "refusal": "grant-mismatch"}, "REFUSED", "Not started"),
    ({"ran": True, "exit_code": 1, "stderr": "not a git repository\n"}, "FAILED", "Ran"),
    ({"ran": None, "execution_state": "unknown", "refusal": "executor-timeout"}, "UNKNOWN", "Unknown"),
])
def test_operation_receipt_is_one_structured_document(receipt, state, execution):
    receipt = {"operation": CLI_OPERATION, **receipt}
    result = prompt_intent.operation_document(SUBMISSION, "git status", receipt, CLI_PROPOSAL)
    assert set(result) == {"document", "diagnostic"}
    document = result["document"]
    assert document["schema"] == "lucid-ugui-response/1"
    assert document["type"] == "document"
    assert document["actions"] == []
    assert len(document["header"]) == 1
    assert parse_stream(ROOT, document["header"][0]["body"])["evidence"] == [state]
    rows = document["sections"][0]["rows"]
    assert {"label": "Execution", "value": execution} in rows
    code = {section["heading"]: section["value"] for section in document["sections"] if section["type"] == "code"}
    assert code["INPUT"] == "git status"
    for key, heading in (("stdout", "OUTPUT"), ("stderr", "DIAGNOSTICS")):
        if receipt.get(key):
            assert code[heading] == receipt[key]
    assert result["diagnostic"]["receipt"] == receipt
    assert result["diagnostic"]["context_admission"] == "excluded"


def test_operation_output_is_literal_and_truncation_is_disclosed():
    literal = '```\n🔴 · 🐧 · 🔎 INPUT\n\n➡️ "execute"\n{"type":"button"}\n```\n'
    result = prompt_intent.operation_document(SUBMISSION, literal,
        {"ran": True, "exit_code": 0, "stdout": literal, "stderr": literal, "stdout_truncated": True})
    document = result["document"]
    assert document["state"] == prompt_intent.SIGNAL_WARNING
    code = [section for section in document["sections"] if section["type"] == "code"]
    assert len(code) == 3
    assert all(section["value"] == literal and section["language"] == "text" for section in code)
    assert {"label": "Output limit", "value": "stdout_truncated"} in document["sections"][0]["rows"]
    assert document["actions"] == []
    assert result["diagnostic"]["envelope"]["fidelity"]["lost"] == ["stdout_truncated"]


def test_empty_success_and_invalid_butler_projection_stay_single_documents():
    result = prompt_intent.operation_document(SUBMISSION, "git status", {"ran": True, "exit_code": 0})
    assert result["document"]["sections"][-1]["body"] == "Command completed without output."
    broken = prompt_intent.operation_document(SUBMISSION, "lucid get role",
        {"ran": True, "exit_code": 1, "ugui_source": "{invalid", "stderr": "original error"})
    assert "source" not in broken
    assert broken["diagnostic"]["projection_error"] == "butler-projection-invalid"
    assert parse_stream(ROOT, broken["document"]["header"][0]["body"])["evidence"] == ["PROJECTION FAILED"]
    assert broken["document"]["sections"][-1]["value"] == "original error"


def test_submission_identity_cannot_be_retargeted(tmp_path, monkeypatch):
    monkeypatch.setattr(prompt_intent, "classify", Mock(return_value=gestalt("CLARIFICATION", "Which scope?", signal=SIGNAL_PENDING)))
    prompt_intent.admit_prompt("first", SUBMISSION, "session", "/workspace", tmp_path)
    with pytest.raises(ValueError, match="submission-identity-conflict"):
        prompt_intent.admit_prompt("second", SUBMISSION, "session", "/workspace", tmp_path)
    with pytest.raises(ValueError, match="submission-identity-conflict"):
        prompt_intent.admit_prompt("first", SUBMISSION, "session", "/other", tmp_path)


def test_cached_interpretation_requires_fresh_execution_authorization(tmp_path, monkeypatch):
    candidate = CLI_PROPOSAL
    prompt_intent.retain_candidate(tmp_path, "git status", candidate)
    classify = Mock(side_effect=ConnectionError("offline"))
    execute = Mock(return_value={"refusal": "grant-revoked", "ran": False})
    monkeypatch.setattr(prompt_intent, "classify", classify)
    monkeypatch.setattr(prompt_intent, "execute_direct", execute)
    result = prompt_intent.admit_prompt("git status", SUBMISSION, "session", "/workspace", tmp_path)
    classify.assert_not_called()
    execute.assert_called_once()
    receipt = result["direct_operation"]["diagnostic"]["receipt"]
    assert receipt["refusal"] == "grant-revoked"
    assert receipt["interpretation_source"] == "qualified_cache"


def test_cache_rejects_near_matches_and_policy_changes(tmp_path, monkeypatch):
    prompt_intent.retain_candidate(tmp_path, "git status", CLI_PROPOSAL)
    assert prompt_intent.cached_candidate(tmp_path, "git status ") is None
    monkeypatch.setattr(prompt_intent, "_cache_identity", lambda: "changed")
    assert prompt_intent.cached_candidate(tmp_path, "git status") is None


@pytest.mark.parametrize("text,glyph,channel", [("git status", "🤖", "cli"), ("lucid get role", "🧠", "lucid")])
def test_classifier_glyph_selects_the_explicit_host_adapter(text, glyph, channel):
    assert prompt_intent.decode_classification(text, glyph)["operation"]["channel"] == channel


@pytest.mark.parametrize("response", ["CLI", "🤖 🔎", "🟢 · ◆ 🤖", "", '{"route":"cli"}'])
def test_classifier_rejects_anything_except_one_declared_glyph(response):
    with pytest.raises(ValueError, match="penguin-classifier-glyph-invalid"):
        prompt_intent.decode_classification("git status", response)


def test_misclassified_agent_role_instruction_never_mutates_witness_identity(tmp_path, monkeypatch):
    monkeypatch.setattr(prompt_intent, "classify", Mock(return_value="🧠"))
    monkeypatch.setattr(prompt_intent, "penguin_inference", Mock(return_value="not-a-choice"))
    formatter = Mock()
    execute = Mock()
    monkeypatch.setattr(prompt_intent, "format_semantic", formatter)
    monkeypatch.setattr(prompt_intent, "execute_direct", execute)
    result = prompt_intent.admit_prompt("Sign in as EM", SUBMISSION, "session", "/workspace", tmp_path)
    assert result["direct_operation"]["diagnostic"]["classifier_response"] == "🧠"
    assert result["direct_operation"]["diagnostic"]["receipt"]["refusal"] == "lucid-help-selection-invalid:lucid-verb"
    formatter.assert_not_called()
    execute.assert_not_called()


def test_classifier_teaches_only_verbs_and_agent_role_distinction():
    instruction = prompt_intent.classification_instruction()
    vocabulary = prompt_intent.lucid_vocabulary()
    for verb, definition in vocabulary["verbs"].items():
        assert f"| ↳ {definition['glyph']} | {verb.upper()} |" in instruction
    protocol_start = instruction.index("| **🧠 PROTOCOL** | **RULE** |")
    examples_start = instruction.index("| Input | Output |")
    assert protocol_start < examples_start
    skill = (ROOT / ".agents/skills/lucid/SKILL.md").read_text()
    protocol = "| **🧠 PROTOCOL** | **RULE** |" + skill.split("| **🧠 PROTOCOL** | **RULE** |", 1)[1].split("\n\n", 1)[0]
    assert protocol in instruction
    assert "{{LUCID_PROTOCOL}}" not in instruction
    for noun in ("plan.dispatch", "speech", "dispatch:", "sha256", "64-lowercase"):
        assert noun not in instruction
    assert '| SHOW PULSE | 🧠 |' in instruction[examples_start:]
    assert '| SHOW URL "https://example.com/" | 🧠 |' in instruction[examples_start:]
    assert '| SHOW APP "macos-shell" | 🧠 |' in instruction[examples_start:]
    assert "MORPH's verb glyph is 🧬; classify every MORPH request as 🔎" in instruction
    assert "| Sign in as EM | 🔎 |" in instruction
    assert "| MORPH | 🔎 |" in instruction
    assert "with or without the lucid prefix" in instruction


@pytest.mark.parametrize("text,verb,argv", [
    ("SHOW SNAKE", "show", ["SNAKE"]),
    ("GET coverage", "get", ["coverage"]),
    ("lucid GET role", "get", ["role"]),
])
def test_bare_canonical_verbs_share_lucid_classification_and_admission(text, verb, argv):
    from tui_gateway.intent_admission import SCHEMA, catalog_hash, evaluate_twitch, input_hash

    candidate = prompt_intent.decode_classification(text, "🧠")
    assert candidate["operation"] == {"channel": "lucid", "verb": verb, "argv": argv}
    bound = {key: value for key, value in candidate.items() if key != "classifier_response"}
    bound.update(schema=SCHEMA, input_hash=input_hash(text), catalog_hash=catalog_hash())
    assert evaluate_twitch(text, bound, lucid_verbs=prompt_intent.lucid_vocabulary()["verbs"]).operation == candidate["operation"]


@pytest.mark.parametrize("text,argv,formatted", [
    ("SHOW PULSE", ["PULSE"], '➡️ 🧠 · ⚡ SHOW · 🎯 PULSE · 🔎 Show pulse'),
    ('SHOW URL "https://example.com/"', ["URL", "https://example.com/"], '➡️ 🧠 · ⚡ SHOW · 🎯 URL · ⚙️ "https://example.com/" · 🔎 Open URL'),
    ('SHOW APP "macos-shell"', ["APP", "macos-shell"], '➡️ 🧠 · ⚡ SHOW · 🎯 APP · ⚙️ "macos-shell" · 🔎 Open macOS Shell'),
])
def test_lucid_second_pass_preserves_skill_coordinates(tmp_path, monkeypatch, text, argv, formatted):
    monkeypatch.setattr(prompt_intent, "classify", Mock(return_value="🧠"))
    lucid = Mock(wraps=prompt_intent.format_lucid)
    semantic = Mock()
    execute = Mock(return_value={"ran": True, "exit_code": 0})
    monkeypatch.setattr(prompt_intent, "format_lucid", lucid)
    monkeypatch.setattr(prompt_intent, "format_semantic", semantic)
    monkeypatch.setattr(prompt_intent, "execute_direct", execute)
    result = prompt_intent.admit_prompt(text, SUBMISSION, "session", "/workspace", tmp_path)
    execute.assert_called_once_with(SUBMISSION, "/workspace", {"channel": "lucid", "verb": "show", "argv": argv})
    lucid.assert_called_once_with(text)
    semantic.assert_not_called()
    action = result["direct_operation"]["diagnostic"]["penguin_response"]
    parsed = parse_stream(ROOT, SIGNAL_GREEN + " · " + action)["actions"][0]
    expected = parse_stream(ROOT, SIGNAL_GREEN + " · " + formatted)["actions"][0]
    assert {key: value for key, value in parsed.items() if key != "label"} == {key: value for key, value in expected.items() if key != "label"}
    assert all(step.get("selection_source") != "penguin" for step in result["direct_operation"]["diagnostic"]["lucid_traversal"]["steps"])


def test_help_traversal_focuses_each_step_and_preserves_original():
    original = "Open https://example.com/"
    infer = Mock(side_effect=["🖼️", "url", "omit", '"https://example.com/"'])
    traversal = Traversal(original, prompt_intent.lucid_vocabulary(), infer)
    result = traversal.run(ROOT)
    assert result["resolved_arguments"] == {"view": "url", "url": "https://example.com/"}
    calls = infer.call_args_list
    assert all(call.args[0] == original for call in calls)
    assert [call.args[2] for call in calls] == ["lucid-verb", "lucid-noun", "lucid-optional", "lucid-argument:url"]
    assert "PULSE" not in calls[0].args[1] and "url" not in calls[0].args[1]
    assert "dispatch" not in calls[1].args[1].lower()
    assert "macos-shell" not in calls[-1].args[1]
    assert all(step.get("help_hash") for step in result["steps"])
    assert all(step.get("help_source", "").startswith("envelope/LUCID.json#/") for step in result["steps"])


def test_invalid_selection_retries_only_current_decision_then_refuses():
    infer = Mock(side_effect=["invalid", "still-invalid"])
    traversal = Traversal("Open the app", prompt_intent.lucid_vocabulary(), infer)
    with pytest.raises(ValueError, match="lucid-help-selection-invalid:lucid-verb"):
        traversal.run(ROOT)
    assert infer.call_count == 2
    assert len(traversal.records) == 1
    assert traversal.records[0]["validation"] == "refused"
    assert len(traversal.records[0]["attempts"]) == 2


def test_missing_free_argument_cannot_be_invented():
    infer = Mock(side_effect=["🖼️", "url", "omit", '"https://invented.example/"'])
    traversal = Traversal("Open the URL", prompt_intent.lucid_vocabulary(), infer)
    with pytest.raises(ValueError, match="lucid-argument-needs-clarification:url"):
        traversal.run(ROOT)
    assert traversal.records[-1]["validation"] == "refused"


def test_explicit_steps_skip_inference_and_keep_optional_scope():
    infer = Mock(side_effect=AssertionError("no model needed"))
    operation = {"channel": "lucid", "verb": "show", "argv": ["--args", '{"view":"pulse","scope":"this"}']}
    traversal = Traversal("lucid show --args", prompt_intent.lucid_vocabulary(), infer)
    result = traversal.run(ROOT, operation)
    assert result["operation"] == operation
    assert result["resolved_arguments"] == {"view": "pulse", "scope": "this"}
    infer.assert_not_called()


def test_missing_noun_help_is_not_replaced_by_an_invented_option_list():
    traversal = Traversal("DISPATCH work", prompt_intent.lucid_vocabulary(), Mock())
    with pytest.raises(ValueError, match="lucid-noun-help-unavailable:dispatch"):
        traversal.run(ROOT, {"channel": "lucid", "verb": "dispatch", "argv": ["work"]})


def test_step_budget_is_enforced():
    traversal = Traversal("input", prompt_intent.lucid_vocabulary(), Mock())
    traversal.records = [{} for _ in range(MAX_STEPS)]
    with pytest.raises(ValueError, match="lucid-traversal-step-bound"):
        traversal.record({"stage": "extra"})


def test_decision_receipts_do_not_change_when_later_choices_are_made():
    traversal = Traversal("input", prompt_intent.lucid_vocabulary(), Mock())
    traversal.decisions["optional_arguments"] = ["scope"]
    traversal.choose("snapshot", {"omit": "Done"}, "envelope/LUCID.json#/verbs/show/args", "omit")
    traversal.decisions["optional_arguments"].append("speak")
    assert traversal.records[0]["resolved_before"]["optional_arguments"] == ["scope"]


def test_inferred_operation_requires_explicit_submission(tmp_path, monkeypatch):
    monkeypatch.setattr(prompt_intent, "classify", Mock(return_value="🧠"))
    monkeypatch.setattr(prompt_intent, "penguin_inference", Mock(side_effect=["🖼️", "url", "omit", '"https://example.com/"']))
    execute = Mock()
    monkeypatch.setattr(prompt_intent, "execute_direct", execute)
    result = prompt_intent.admit_prompt("Open https://example.com/", SUBMISSION, "session", "/workspace", tmp_path)
    execute.assert_not_called()
    diagnostic = result["direct_operation"]["diagnostic"]
    assert diagnostic["receipt"]["refusal"] == "lucid-proposal-needs-confirmation"
    assert diagnostic["lucid_traversal"]["resolved_arguments"] == {"view": "url", "url": "https://example.com/"}
    source = result["direct_operation"]["source"]
    assert "document" not in result["direct_operation"]
    assert ' · ➡️ "lucid ' in source.split("\n\n", 1)[0]
    assert "https://example.com/" in source


@pytest.mark.parametrize("text", ["MORPH effigy", "lucid morph print", "morph a story"])
def test_morph_requires_semantic_evaluation_even_if_classifier_selects_lucid(tmp_path, monkeypatch, text):
    monkeypatch.setattr(prompt_intent, "classify", Mock(return_value="🧠"))
    semantic = Mock(return_value=gestalt("SEMANTIC", "Evaluate the requested morph."))
    lucid = Mock()
    execute = Mock()
    monkeypatch.setattr(prompt_intent, "format_semantic", semantic)
    monkeypatch.setattr(prompt_intent, "format_lucid", lucid)
    monkeypatch.setattr(prompt_intent, "execute_direct", execute)
    result = prompt_intent.admit_prompt(text, SUBMISSION, "session", "/workspace", tmp_path)
    semantic.assert_called_once_with(text)
    assert result["prepared_text"] == semantic.return_value
    lucid.assert_not_called()
    execute.assert_not_called()


def test_role_assumption_instruction_reaches_agent_as_gestalt_not_witness_execution(tmp_path, monkeypatch):
    text = "Sign in as EM"
    response = gestalt("SEMANTIC", "Establish your agent session as EM.")
    monkeypatch.setattr(prompt_intent, "classify", Mock(return_value="🔎"))
    formatter = Mock(return_value=response)
    execute = Mock()
    monkeypatch.setattr(prompt_intent, "format_semantic", formatter)
    monkeypatch.setattr(prompt_intent, "execute_direct", execute)
    result = prompt_intent.admit_prompt(text, SUBMISSION, "session", "/workspace", tmp_path)
    assert result["prepared_text"] == response
    assert result["preparation"]["diagnostic"]["classifier_response"] == "🔎"
    formatter.assert_called_once_with(text)
    execute.assert_not_called()


def test_cancellation_is_session_scoped_and_prevents_dispatch(tmp_path, monkeypatch):
    def classify(text):
        assert not prompt_intent.cancel_intent(SUBMISSION, "other")
        assert prompt_intent.cancel_intent(SUBMISSION, "session")
        return CLI_RESPONSE

    monkeypatch.setattr(prompt_intent, "classify", classify)
    execute = Mock()
    monkeypatch.setattr(prompt_intent, "execute_direct", execute)
    result = prompt_intent.admit_prompt("git status", SUBMISSION, "session", "/workspace", tmp_path)
    assert result["direct_operation"]["diagnostic"]["receipt"]["refusal"] == "submission-cancelled"
    execute.assert_not_called()


def test_lost_execution_reply_is_unknown_not_claimed_unexecuted(tmp_path, monkeypatch):
    monkeypatch.setattr(prompt_intent, "classify", Mock(return_value=CLI_RESPONSE))
    monkeypatch.setattr(prompt_intent, "execute_direct", Mock(side_effect=TimeoutError()))
    result = prompt_intent.admit_prompt("git status", SUBMISSION, "session", "/workspace", tmp_path)
    receipt = result["direct_operation"]["diagnostic"]["receipt"]
    assert receipt["execution_state"] == "unknown"
    assert receipt["ran"] is None


def test_rpc_admits_direct_input_before_agent_side_effects(tmp_path, monkeypatch):
    from tui_gateway import server

    history = [{"role": "user", "content": "existing agent turn"}]
    session = {"session_key": "session", "running": True, "history": history}
    monkeypatch.setattr(server, "_sessions", {"runtime": session})
    monkeypatch.setattr(server, "get_hermes_home", lambda: tmp_path)
    monkeypatch.setattr(server, "_session_cwd", lambda current: "/workspace")
    persist = Mock()
    monkeypatch.setattr(server, "_ensure_session_db_row", persist)
    emit = Mock()
    monkeypatch.setattr(server, "_emit", emit)
    agent_path = Mock(side_effect=AssertionError("agent path entered"))
    monkeypatch.setattr(server, "_load_dashboard_process_isolation_config", agent_path)
    monkeypatch.setattr(prompt_intent, "classify", Mock(return_value=CLI_RESPONSE))
    monkeypatch.setattr(prompt_intent, "execute_direct", Mock(return_value={"ran": True, "exit_code": 0, "stdout": "clean"}))
    result = server._methods["prompt.submit"]("request", {
        "session_id": "runtime", "submission_id": SUBMISSION, "text": "git status", "interrupted": True})
    assert "direct_operation" in result["result"]
    assert result["result"]["agent_running"] is True
    assert session["history"] == history and session["running"] is True
    persist.assert_called_once_with(session)
    agent_path.assert_not_called()
    assert emit.call_args.args[0] == "intent.operation"