import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from tui_gateway import prompt_intent
from hermes_gestalt import canonical_stream, parse_stream
from agent.generated.ae_glyphs import SIGNAL_GREEN, SIGNAL_PENDING


SUBMISSION = "submission-000000000001"
ROOT = Path(__file__).resolve().parents[3]


def gestalt(channel, text, *labels, signal=SIGNAL_GREEN):
    if channel in {"CLI", "LUCID"}:
        return canonical_stream(ROOT, signal, data=("Requested invocation",)) + f"\n\n➡️ `{text}`"
    return canonical_stream(ROOT, signal, data=(text,))


CLI_OPERATION = {"channel": "cli", "executable": "git", "argv": ["status"]}
CLI_RESPONSE = "🤖"
CLI_PROPOSAL = {"classification": "direct", "operation": CLI_OPERATION, "classifier_response": CLI_RESPONSE}


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
    monkeypatch.setattr(prompt_intent, "format_lucid", Mock(return_value='➡️ 🧠 · ⚡ SHOW · 🎯 PULSE · 🔎 Show pulse'))
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
    assert events[-1]["document"]["sections"][0]["heading"] == "From user / PENGUIN"


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


def test_copied_diagnostics_include_the_actual_canonical_system_instruction(tmp_path, monkeypatch):
    response = gestalt("SEMANTIC", "Compare the approaches.", "OBJECTIVE") + '\n\n➡️ "Explain tradeoffs"\n\n🐧🐧'
    connection = Mock()
    connection.getresponse.return_value.status = 200
    connection.getresponse.return_value.read.side_effect = [json.dumps({"choices": [
        {"finish_reason": "stop", "message": {"content": content}}]}).encode() for content in ["🔎", response]]
    monkeypatch.setattr(prompt_intent.http.client, "HTTPConnection", Mock(return_value=connection))
    result = prompt_intent.admit_prompt("Compare approaches", SUBMISSION, "session", "/workspace", tmp_path)
    actual_prompt = json.loads(connection.request.call_args.args[2])["messages"][0]["content"]
    diagnostic = result["preparation"]["diagnostic"]
    assert diagnostic["penguin_system_prompt"] == actual_prompt
    assert diagnostic["penguin_system_prompt_hash"] == prompt_intent.input_hash(actual_prompt)
    assert diagnostic["penguin_response"] == response
    assert result["prepared_text"] == response
    calls = [json.loads(call.args[2]) for call in connection.request.call_args_list]
    assert len(calls) == 2
    assert calls[0]["messages"][0]["content"] == prompt_intent.classification_instruction()
    assert calls[0]["max_tokens"] == 8 and calls[1]["max_tokens"] == 8192
    assert calls[1]["messages"][0]["content"] == prompt_intent.penguin_instruction(ROOT)
    assert [stage["stage"] for stage in diagnostic["stages"]] == ["classification", "semantic-preparation"]
    assert [stage["response"] for stage in diagnostic["stages"]] == ["🔎", response]
    assert all(stage["input"] == "Compare approaches" for stage in diagnostic["stages"])


def test_lucid_uses_its_declared_route_and_retains_original_projection(tmp_path, monkeypatch):
    projected = {"schema": "lucid-ugui-response/1", "id": "role", "type": "document", "header": [], "sections": [], "actions": []}
    operation = {"channel": "lucid", "verb": "get", "argv": ["role"]}
    monkeypatch.setattr(prompt_intent, "classify", Mock(return_value="🧠"))
    execute = Mock(return_value={"ran": True, "exit_code": 0, "operation": operation, "ugui_source": json.dumps(projected)})
    monkeypatch.setattr(prompt_intent, "format_lucid", Mock(return_value='➡️ 🧠 · ⚡ GET · 🎯 ROLE · 🔎 Inspect role'))
    monkeypatch.setattr(prompt_intent, "execute_direct", execute)
    result = prompt_intent.admit_prompt("lucid get role", SUBMISSION, "session", "/workspace", tmp_path)
    execute.assert_called_once_with(SUBMISSION, "/workspace", operation)
    assert result["direct_operation"]["document"] == projected


def test_missing_handoff_never_executes(monkeypatch):
    monkeypatch.setattr(prompt_intent, "_TOKEN", "")
    assert prompt_intent.execute_direct(SUBMISSION, "/workspace", CLI_OPERATION) == {
        "operation": CLI_OPERATION, "refusal": "witness-handoff-unavailable", "ran": False}


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
    formatter = Mock()
    execute = Mock()
    monkeypatch.setattr(prompt_intent, "format_semantic", formatter)
    monkeypatch.setattr(prompt_intent, "execute_direct", execute)
    result = prompt_intent.admit_prompt("Sign in as EM", SUBMISSION, "session", "/workspace", tmp_path)
    assert result["direct_operation"]["diagnostic"]["classifier_response"] == "🧠"
    assert result["direct_operation"]["diagnostic"]["receipt"]["refusal"] == "lucid-lowering-required"
    formatter.assert_not_called()
    execute.assert_not_called()


def test_classifier_teaches_only_verbs_and_agent_role_distinction():
    instruction = prompt_intent.classification_instruction()
    vocabulary = prompt_intent.lucid_vocabulary()
    for verb, definition in vocabulary["verbs"].items():
        assert f"| {verb.upper()} | {definition['glyph']} |" in instruction
    for noun in ("pulse", "effigy", "plan.dispatch", "speech", "dispatch:", "sha256", "64-lowercase"):
        assert noun not in instruction
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
    lucid = Mock(return_value=formatted)
    semantic = Mock()
    execute = Mock(return_value={"ran": True, "exit_code": 0})
    monkeypatch.setattr(prompt_intent, "format_lucid", lucid)
    monkeypatch.setattr(prompt_intent, "format_semantic", semantic)
    monkeypatch.setattr(prompt_intent, "execute_direct", execute)
    result = prompt_intent.admit_prompt(text, SUBMISSION, "session", "/workspace", tmp_path)
    execute.assert_called_once_with(SUBMISSION, "/workspace", {"channel": "lucid", "verb": "show", "argv": argv})
    lucid.assert_called_once_with(text)
    semantic.assert_not_called()
    assert result["direct_operation"]["diagnostic"]["penguin_response"] == formatted


@pytest.mark.parametrize("formatted", [
    '➡️ 🧠 · ⚡ SET · 🎯 PULSE · 🔎 Change operation',
    '➡️ 🧠 · ⚡ SHOW · 🎯 URL · ⚙️ "https://other.example/" · 🔎 Open URL',
    'SHOW URL https://example.com/',
])
def test_lucid_formatter_cannot_change_operation_or_arguments(formatted):
    with pytest.raises(ValueError):
        prompt_intent.validate_lucid_preparation(formatted, {"channel": "lucid", "verb": "show", "argv": ["URL", "https://example.com/"]})


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