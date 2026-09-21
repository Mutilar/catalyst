import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from tui_gateway import prompt_intent
from hermes_gestalt import canonical_stream, parse_stream
from agent.generated import ae_glyphs as glyph
from agent.generated.ae_glyphs import SIGNAL_GREEN, SIGNAL_PENDING
from tui_gateway.lucid_traversal import Traversal, MAX_STEPS
from agent.generated.ae_glyphs import RELATION_DATUM


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
    text = signal + f'{glyph.DELIMITER_SEGMENT}{glyph.RELATION_DATUM} Preserve this\n\n| Value | Literal |\n|---|---|\n| 1 | [200~ |\n'
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

    text = '  Keep literal [200~ content\n' if bypass else f'{glyph.SIGNAL_GREEN}{glyph.DELIMITER_SEGMENT}{glyph.RELATION_DATUM} Keep literal [200~ content\n'
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
    response = prompt_intent.lucid_vocabulary()["verbs"][operation["verb"]]["glyph"] if operation["channel"] == "lucid" else "🤖"
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
    from tui_gateway import penguin_funnel
    delta = (ROOT / "butler/canon/penguin/semantic.md").read_text()
    prefix, suffix = delta.split("{{FEW_SHOTS}}")
    assert instruction.startswith(prefix) and instruction.endswith(suffix)
    assert instruction == prompt_intent.penguin_instruction(ROOT)
    segments = json.loads((ROOT / "envelope/GESTALT.json").read_text())["segments"]
    assert "{{FEW_SHOTS}}" not in instruction
    assert instruction == penguin_funnel.project("semantic-preparation")["prompt"]
    for token in segments["signals"]:
        assert token in instruction
    assert "SYS" not in instruction and "HATS" not in instruction
    assert "LUCID SHOW/GET ONLY" not in instruction
    assert "json" not in instruction.lower()
    assert "permission" not in instruction.lower()
    assert "CLI, LUCID, SEMANTIC" not in instruction
    for heading in ("**SEMANTIC PROTOCOL**", "**PREFIX GLYPH**", "**SEGMENT GLYPH**"):
        assert glyph.DELIMITER_SEGMENT.join((heading, "**RULE**")) in prefix
    assert "RESTATE · REFORMAT THE ENTIRE INPUT; DO NOT ANSWER IT" in prefix
    assert "git status" in instruction
    assert "lucid get role" not in instruction
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


@pytest.mark.parametrize("transport_phase", ["request", "response-headers", "response-body"])
def test_penguin_timeout_retains_transport_evidence_without_retry_or_execution(tmp_path, monkeypatch, transport_phase):
    connection = Mock()
    response = connection.getresponse.return_value
    response.status = 200
    failure = {"request": connection.request, "response-headers": connection.getresponse,
        "response-body": response.read}[transport_phase]

    def time_out(*args, **kwargs):
        assert connection in prompt_intent._ACTIVE[SUBMISSION][2]
        raise TimeoutError("timed out")

    failure.side_effect = time_out
    transport = Mock(return_value=connection)
    monkeypatch.setattr(prompt_intent.http.client, "HTTPConnection", transport)
    execute = Mock(side_effect=AssertionError("timed out classification must not execute"))
    monkeypatch.setattr(prompt_intent, "execute_direct", execute)
    result = prompt_intent.admit_prompt("KX is KOLMOGOROV", SUBMISSION, "session", "/workspace", tmp_path)
    assert "prepared_text" not in result
    evidence = result["direct_operation"]
    diagnostic = evidence["diagnostic"]
    assert diagnostic["receipt"]["refusal"] == "penguin-inference-timeout"
    assert diagnostic["receipt"]["execution_state"] == "not-started"
    assert diagnostic["receipt"]["ran"] is False
    assert diagnostic["classifier_response"] is None
    assert diagnostic["classifier_selection"] is None
    assert len(diagnostic["stages"]) == 1
    stage = diagnostic["stages"][0]
    assert stage["response"] is None
    assert stage["transport"] == {
        "timeout_ms": 30_000, "phase": transport_phase,
        "http_status": 200 if transport_phase == "response-body" else None,
        "inference_state": "unknown", "error": "TimeoutError",
    }
    projected = parse_stream(ROOT, evidence["source"].split("\n\n", 1)[0])
    assert projected["evidence"] == ["PENGUIN INFERENCE TIMEOUT"]
    assert "CLASSIFICATION" in projected["data"]
    assert "30s transport timeout" in projected["data"]
    assert "No complete response received" in projected["data"]
    assert "Provider completion unknown" in projected["data"]
    assert "Execution not started" in projected["data"]
    assert transport.call_args.kwargs["timeout"] == 30
    assert connection.request.call_count == 1
    connection.close.assert_called_once()
    execute.assert_not_called()
    assert prompt_intent.admit_prompt("KX is KOLMOGOROV", SUBMISSION, "session", "/workspace", tmp_path) == result
    transport.assert_called_once()


def test_semantic_question_cannot_be_classified_into_execution(tmp_path, monkeypatch):
    monkeypatch.setattr(prompt_intent, "classify", Mock(return_value="🧠"))
    monkeypatch.setattr(prompt_intent, "format_semantic", Mock(return_value=gestalt("SEMANTIC", "Explain what git status means.")))
    execute = Mock()
    monkeypatch.setattr(prompt_intent, "execute_direct", execute)
    result = prompt_intent.admit_prompt("What does git status mean?", SUBMISSION, "session", "/workspace", tmp_path)
    assert "prepared_text" in result
    execute.assert_not_called()


@pytest.mark.parametrize("text", ["this is a test", "KX is KOLMOGOROV"])
def test_valid_semantic_preparation_preserves_input_and_separates_notice_datums(tmp_path, monkeypatch, text):
    response = canonical_stream(ROOT, SIGNAL_GREEN, without_identity=True, data=(text,))
    monkeypatch.setattr(prompt_intent, "classify", Mock(return_value=glyph.IDENTITY_LUCID))
    monkeypatch.setattr(prompt_intent, "format_semantic", Mock(return_value=response))
    execute = Mock(side_effect=AssertionError("semantic preparation must not execute"))
    monkeypatch.setattr(prompt_intent, "execute_direct", execute)
    events = []
    result = prompt_intent.admit_prompt(text, SUBMISSION, "session", "/workspace", tmp_path,
        on_preparation=events.append)
    assert result.get("prepared_text") == text, result
    assert "direct_operation" not in result
    prepared = result["preparation"]
    assert prepared["diagnostic"]["transformed_input"] == response
    assert prepared["diagnostic"]["semantic_admission"]["proposal_admitted"] is False
    notice = parse_stream(ROOT, prepared["source"].split("\n\n", 1)[0])
    assert notice["evidence"] == ["PROPOSAL ONLY"]
    assert notice["data"] == ["Original input forwarded unchanged", "rewrite not admitted"]
    assert events[-1] == prepared
    execute.assert_not_called()


def test_ambiguous_input_cannot_fall_through_to_reasoning(tmp_path, monkeypatch):
    monkeypatch.setattr(prompt_intent, "classify", Mock(return_value=gestalt("CLARIFICATION", "Which scope?", signal=SIGNAL_PENDING)))
    result = prompt_intent.admit_prompt("git status", SUBMISSION, "session", "/workspace", tmp_path)
    assert "prepared_text" not in result
    assert result["direct_operation"]["diagnostic"]["receipt"]["refusal"] == "penguin-classifier-glyph-invalid"


def test_semantic_preparation_preserves_returned_gestalt_and_has_display_only_history(tmp_path, monkeypatch):
    text = "Compare options; do not edit files."
    response = gestalt("SEMANTIC", "Compare the available options.", "OBJECTIVE") + "\n" + gestalt("SEMANTIC", "Do not modify files.", "PROHIBITION")
    monkeypatch.setattr(prompt_intent, "classify", Mock(return_value="🧠"))
    monkeypatch.setattr(prompt_intent, "format_semantic", Mock(return_value=response))
    result = prompt_intent.admit_prompt(text, SUBMISSION, "session", "/workspace", tmp_path)
    assert result["prepared_text"] == text
    assert "Original WITNESS input" not in result["prepared_text"]
    assert parse_stream(ROOT, response.splitlines()[1])["data"] == ["Do not modify files."]
    history = prompt_intent.operation_history(tmp_path, "session")
    assert len(history) == 1 and history[0]["role"] == "system"
    retained = json.loads(history[0]["text"][len("twitch:"):])
    assert retained["diagnostic"]["context_admission"] == "excluded"
    assert retained["diagnostic"]["original_input"] == text
    assert retained["diagnostic"]["transformed_input"] == response
    assert retained["diagnostic"]["semantic_admission"]["proposal_admitted"] is False
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
        return "🧠"

    monkeypatch.setattr(prompt_intent, "classify", classify)
    formatter = Mock(return_value=response)
    monkeypatch.setattr(prompt_intent, "format_semantic", formatter)
    result = prompt_intent.admit_prompt(text, SUBMISSION, "session", "/workspace", tmp_path, on_preparation=events.append)
    assert [event["diagnostic"]["phase"] for event in events] == ["classification", "semantic-preparation", "prepared"]
    formatter.assert_called_once_with(text)
    assert events[-1]["diagnostic"]["classifier_response"] == "🧠"
    diagnostic = events[-1]["diagnostic"]
    assert diagnostic["pending"] is False
    assert diagnostic["original_input"] == text
    assert diagnostic["transformed_input"] == response
    assert result["prepared_text"] == text
    assert diagnostic["penguin_response"] == response
    assert diagnostic["proposal"]["gestalt"] == response
    assert diagnostic["authority"] == "none"
    assert diagnostic["origin"] == {"author": "user", "processor": "PENGUIN", "kind": "intent-preparation"}
    assert "document" not in events[-1]
    assert parse_stream(ROOT, events[-1]["source"].split("\n\n", 1)[0])["service"] == "🐧"


def test_semantic_agent_input_retains_original_while_proposal_remains_inspectable():
    text = "Compare options; do not edit files."
    response = gestalt("SEMANTIC", "Compare options.", "OBJECTIVE") + "\n" + gestalt("SEMANTIC", "Do not edit files.", "PROHIBITION")
    candidate = prompt_intent.decode_preparation(text, response, ROOT)
    prepared = prompt_intent.prepare_semantic(text, candidate, ROOT)
    assert prepared == text
    streams = [parse_stream(ROOT, line) for line in candidate["gestalt"].splitlines()]
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


@pytest.mark.parametrize("verb", ["DEPLOY", "QUERY", "CONFIGURE"])
@pytest.mark.parametrize("separator", ["\n", f"{glyph.DELIMITER_SEGMENT}"])
def test_semantic_preparation_rejects_invented_active_lucid_verbs(verb, separator):
    response = gestalt("SEMANTIC", "Greeting acknowledged") + separator + (
        f"{glyph.RELATION_ACTION} {glyph.IDENTITY_LUCID}{glyph.DELIMITER_SEGMENT}{glyph.RELATION_VERB} {verb}{glyph.DELIMITER_SEGMENT}{glyph.RELATION_NOUN} TASK{glyph.DELIMITER_SEGMENT}{glyph.RELATION_ARGUMENT} <SPECIFICATION>{glyph.DELIMITER_SEGMENT}{glyph.RELATION_EVIDENCE} Request"
    )
    with pytest.raises(ValueError, match="GESTALT verb is not canonical"):
        prompt_intent.decode_preparation("Hi", response, ROOT)


def test_quoted_invalid_protocol_example_stays_non_executable_content():
    response = gestalt("SEMANTIC", "Explain this quoted example") + (
        f"\n\n```text\n{glyph.RELATION_ACTION} {glyph.IDENTITY_LUCID}{glyph.DELIMITER_SEGMENT}{glyph.RELATION_VERB} DEPLOY{glyph.DELIMITER_SEGMENT}{glyph.RELATION_NOUN} TASK\n```"
    )
    candidate = prompt_intent.decode_preparation("Explain the quoted DEPLOY example", response, ROOT)
    assert prompt_intent.prepare_semantic("Explain the quoted DEPLOY example", candidate, ROOT) == "Explain the quoted DEPLOY example"


def test_fabricated_greeting_reply_is_not_admitted_as_user_input(tmp_path, monkeypatch):
    response = canonical_stream(ROOT, SIGNAL_GREEN,
        data=("Greeting acknowledged", "system ready for execution"))
    monkeypatch.setattr(prompt_intent, "classify", Mock(return_value="🧠"))
    monkeypatch.setattr(prompt_intent, "format_semantic", Mock(return_value=response))
    execute = Mock()
    monkeypatch.setattr(prompt_intent, "execute_direct", execute)
    result = prompt_intent.admit_prompt("Hi", SUBMISSION, "session", "/workspace", tmp_path)
    assert result["prepared_text"] == "Hi"
    diagnostic = result["preparation"]["diagnostic"]
    assert diagnostic["penguin_response"] == response
    assert diagnostic["transformed_input"] == response
    assert diagnostic["semantic_admission"] == {
        "forwarded": "original-input", "forwarded_input_hash": prompt_intent.input_hash("Hi"),
        "proposal_input_hash": prompt_intent.input_hash(response), "proposal_admitted": False,
        "reason": "semantic-fidelity-unverified",
    }
    execute.assert_not_called()


def test_reported_greeting_failure_retains_actual_prompt_and_raw_response(tmp_path, monkeypatch):
    response = (
        f"\n\n{glyph.SIGNAL_GREEN}{glyph.DELIMITER_SEGMENT}GREETING ACKNOWLEDGED{glyph.DELIMITER_SEGMENT}SYSTEM STANDBY{glyph.DELIMITER_SEGMENT}AWAITING TASK SPECIFICATION{glyph.DELIMITER_SEGMENT}READY FOR EXECUTION\n"
        f"{glyph.RELATION_ACTION} {glyph.IDENTITY_LUCID}{glyph.DELIMITER_SEGMENT}{glyph.RELATION_VERB} DEPLOY{glyph.DELIMITER_SEGMENT}{glyph.RELATION_NOUN} TASK{glyph.DELIMITER_SEGMENT}{glyph.RELATION_ARGUMENT} <SPECIFICATION>{glyph.DELIMITER_SEGMENT}{glyph.RELATION_EVIDENCE} REQUEST\n"
        f"{glyph.RELATION_ACTION} {glyph.IDENTITY_LUCID}{glyph.DELIMITER_SEGMENT}{glyph.RELATION_VERB} QUERY{glyph.DELIMITER_SEGMENT}{glyph.RELATION_NOUN} CONTEXT{glyph.DELIMITER_SEGMENT}{glyph.RELATION_ARGUMENT} <DOMAIN>{glyph.DELIMITER_SEGMENT}{glyph.RELATION_EVIDENCE} INQUIRY\n"
        f"{glyph.RELATION_ACTION} {glyph.IDENTITY_LUCID}{glyph.DELIMITER_SEGMENT}{glyph.RELATION_VERB} CONFIGURE{glyph.DELIMITER_SEGMENT}{glyph.RELATION_NOUN} PROTOCOL{glyph.DELIMITER_SEGMENT}{glyph.RELATION_ARGUMENT} <PARAMETERS>{glyph.DELIMITER_SEGMENT}{glyph.RELATION_EVIDENCE} ADJUSTMENT"
    )
    connection = Mock()
    connection.getresponse.return_value.status = 200
    connection.getresponse.return_value.read.side_effect = [json.dumps({"choices": [
        {"finish_reason": "stop", "message": {"content": content}}]}).encode()
        for content in ["\n\n🧠", response]]
    monkeypatch.setattr(prompt_intent.http.client, "HTTPConnection", Mock(return_value=connection))
    execute = Mock()
    monkeypatch.setattr(prompt_intent, "execute_direct", execute)
    result = prompt_intent.admit_prompt("Hi", SUBMISSION, "session", "/workspace", tmp_path)
    assert "prepared_text" not in result
    diagnostic = result["direct_operation"]["diagnostic"]
    assert diagnostic["receipt"]["refusal"] == "GESTALT verb is not canonical"
    assert diagnostic["stages"][-1]["response"] == response
    actual = json.loads(connection.request.call_args.args[2])
    assert diagnostic["stages"][-1]["request_messages"] == actual["messages"]
    assert diagnostic["input_normalization"]["submitted_input"] == "Hi"
    assert diagnostic["input_normalization"]["changed"] is False
    execute.assert_not_called()


def test_preparation_prompt_preserves_speech_acts_without_lucid_teaching():
    instruction = prompt_intent.penguin_instruction(ROOT)
    assert "RESTATE · REFORMAT THE ENTIRE INPUT; DO NOT ANSWER IT" in instruction
    assert "EXPLICIT NEXT STEPS ARE CONTINUATIONS, NOT DATA" in instruction
    assert "OMIT ONLY WHEN NONE REQUESTED; KEEP CONDITIONS" in instruction
    for excluded in ("LUCID", "GESTALT", "signature", "whitespace", "wrapper",
        glyph.IDENTITY_LUCID, glyph.RELATION_VERB, glyph.RELATION_NOUN, glyph.RELATION_ARGUMENT):
        assert excluded not in instruction
    assert "{{GESTALT_LEGEND}}" not in instruction
    assert "=>" not in instruction
    rows = instruction.split("**PROMPT** · **EXPECTED OUTPUT**\n", 1)[1].strip().splitlines()
    from tui_gateway import penguin_funnel
    selected = [case for case in penguin_funnel.corpus()["cases"] if case["classification"] in {"semantic", "morph"}]
    assert len(rows) == len(selected)
    states = set()
    for row in rows:
        original, end = json.JSONDecoder().raw_decode(row)
        assert row[end:].startswith(glyph.DELIMITER_SEGMENT)
        encoded = row[end + len(glyph.DELIMITER_SEGMENT):]
        fence = encoded[:len(encoded) - len(encoded.lstrip("`"))]
        assert fence and encoded.endswith(fence)
        response = encoded[len(fence):-len(fence)].strip()
        states.add(response.split(glyph.DELIMITER_SEGMENT, 1)[0])
        candidate = prompt_intent.decode_preparation(original, response, ROOT)
        assert candidate["classification"] == "semantic"
        assert prompt_intent.prepare_semantic(original, candidate, ROOT) == original
    assert states == {glyph.SIGNAL_GREEN, glyph.SIGNAL_PENDING, glyph.SIGNAL_WARNING, glyph.SIGNAL_RED}
    assert "· ⏳ Elapsed 3s" in instruction
    assert "· ⏳ ETA 2m" in instruction
    assert "· ⏳ Age 5m" in instruction
    assert "· 🔎 Log: exit 0" in instruction
    assert f'{glyph.RELATION_ACTION} "Then run git status"' in instruction
    assert f'{glyph.RELATION_ACTION} `git diff --stat`' in instruction
    for header in ("**SEMANTIC PROTOCOL** · **RULE**", "**PREFIX GLYPH** · **RULE**",
        "**SEGMENT GLYPH** · **RULE**"):
        assert header in instruction
    assert f"{glyph.RELATION_EVIDENCE} · EVIDENCE FROM INPUT" in instruction
    assert f"{glyph.SIGNAL_PENDING} · TIMING: ELAPSED, ETA, AGE (OPTIONAL)" in instruction
    assert "EVIDENCE FIRST, DATA FOLLOWS, THEN TIMING AND CYOA LAST" in instruction


def test_canonical_stream_builds_service_free_intent_and_cli_without_changing_defaults():
    assert canonical_stream(ROOT, SIGNAL_GREEN) == glyph.DELIMITER_SEGMENT.join((SIGNAL_GREEN, glyph.IDENTITY_LUCID))
    assert canonical_stream(ROOT, SIGNAL_GREEN, without_identity=True, data=("ok",), intents=("try",)) == glyph.DELIMITER_SEGMENT.join((
        SIGNAL_GREEN, f"{glyph.RELATION_DATUM} ok", f'{glyph.RELATION_ACTION} "try"',
    ))
    assert canonical_stream(ROOT, SIGNAL_GREEN, without_identity=True, data=("check",), cli=("git status",)) == glyph.DELIMITER_SEGMENT.join((
        SIGNAL_GREEN, f"{glyph.RELATION_DATUM} check", f"{glyph.RELATION_ACTION} `git status`",
    ))
    for field, invalid in [("intents", 'nested " quote'), ("cli", "nested ` quote"), ("intents", ""),
        ("cli", "new\nline"), ("intents", "\x7f"), ("cli", "é" * 513)]:
        with pytest.raises(ValueError, match="CYOA continuation is invalid"):
            canonical_stream(ROOT, SIGNAL_GREEN, **{field: (invalid,)})
    with pytest.raises(ValueError, match="conflicts"):
        canonical_stream(ROOT, SIGNAL_GREEN, without_identity=True, service=glyph.IDENTITY_LUCID)


def test_canonical_quoted_continuations_round_trip_without_promoting_literal_actions():
    intent = f"inspect{glyph.DELIMITER_SEGMENT}{glyph.RELATION_ACTION} literally; A=B"
    command = f"printf 'a{glyph.DELIMITER_SEGMENT}b' | head"
    text = canonical_stream(ROOT, SIGNAL_GREEN, without_identity=True,
        data=("check",), intents=(intent, "try"), cli=(command, "git status"))
    parsed = parse_stream(ROOT, text)
    assert parsed["service"] is None
    assert parsed["data"] == ["check"]
    assert parsed["intents"] == [intent, "try"]
    assert parsed["cli"] == [command, "git status"]
    assert parsed["actions"] == []
    assert parsed["continuations"] == [
        {"kind": "intent", "value": intent}, {"kind": "intent", "value": "try"},
        {"kind": "cli", "value": command}, {"kind": "cli", "value": "git status"},
    ]
    for malformed in ['"unclosed', '`unclosed', '"nested " quote"', '"try" unsegmented', '""', '`\x00`']:
        with pytest.raises(ValueError):
            parse_stream(ROOT, glyph.DELIMITER_SEGMENT.join((SIGNAL_GREEN, f"{glyph.RELATION_ACTION} {malformed}")))
    service = parse_stream(ROOT, canonical_stream(ROOT, SIGNAL_GREEN, continuations=(glyph.IDENTITY_PENGUIN,)))
    assert service["continuations"] == [glyph.IDENTITY_PENGUIN]
    assert service["intents"] == [] and service["cli"] == []


def test_witnessed_greeting_status_and_next_step_are_preserved_in_canonical_semantic_case():
    from tui_gateway import penguin_funnel

    cases = {case["id"]: case for case in penguin_funnel.corpus()["cases"]}
    case = cases["greeting-status-continuation"]
    assert case["input"] == "Hello, how are we doing today, this is a status and protocol check. Next steps: Sign in as EM"
    assert case["classification"] == "semantic"
    assert case["semantic"] == canonical_stream(ROOT, SIGNAL_GREEN, without_identity=True,
        data=("Hello", "How are we doing today?", "This is a status and protocol check"), intents=("Sign in as EM",))
    projection = penguin_funnel.project("semantic-preparation")
    assert case["id"] in projection["case_ids"]
    assert case["semantic"] in projection["prompt"]
    assert "EXPLICIT NEXT STEPS ARE CONTINUATIONS, NOT DATA" in projection["prompt"]
    assert cases["agent-role"]["semantic"] == canonical_stream(ROOT, SIGNAL_GREEN, without_identity=True, data=("Sign in as EM",))
    candidate = prompt_intent.decode_preparation(case["input"], case["semantic"], ROOT)
    assert prompt_intent.prepare_semantic(case["input"], candidate, ROOT) == case["input"]


@pytest.mark.parametrize("stage", ["classification", "semantic-preparation"])
def test_preprocessing_request_has_no_tool_surface_or_prior_submission_history(stage):
    instruction = (prompt_intent.classification_instruction() if stage == "classification"
        else prompt_intent.penguin_instruction(ROOT))
    request = prompt_intent.penguin_request("Hi", instruction, prompt_intent.penguin_max_tokens("Hi"), stage=stage)
    assert request["tools"] == []
    assert request["tool_choice"] == "none"
    assert "functions" not in request
    assert request["messages"] == [
        {"role": "system", "content": instruction}, {"role": "user", "content": "Hi"},
    ]


@pytest.mark.parametrize("text,expected", [
    ("", 1024), ("Hi", 1028), ("Welcome to AE", 1050),
    ("🐧", 1032), ("é", 1028), ("a\n", 1028),
    ("a" * prompt_intent.MAX_INPUT_BYTES, 1024 + 2 * prompt_intent.MAX_INPUT_BYTES),
])
def test_budget_is_base_plus_twice_utf8_user_bytes(text, expected):
    assert prompt_intent.penguin_max_tokens(text) == expected
    for instruction in ["Short", "Long system instruction " * 100]:
        request = prompt_intent.penguin_request(text, instruction, expected, stage="classification")
        assert request["max_tokens"] == expected
    with pytest.raises(ValueError, match="penguin-input-budget-mismatch"):
        prompt_intent.penguin_request(text, "instruction", expected - 1, stage="classification")


@pytest.mark.parametrize("stage", ["classification", "semantic-preparation", "lucid-noun", "lucid-optional",
    "lucid-noun:retry", "lucid-optional:retry", "lucid-argument:url", "lucid-argument:app:retry"])
def test_bounded_preprocessing_disables_thinking_without_prompt_instructions(stage):
    request = prompt_intent.penguin_request("Hi", "unchanged instructions", 1028, stage=stage)
    assert request["chat_template_kwargs"] == {"enable_thinking": False}
    assert request["messages"] == [
        {"role": "system", "content": "unchanged instructions"}, {"role": "user", "content": "Hi"}]
    assert request["max_tokens"] == 1028
    assert request["tools"] == [] and request["tool_choice"] == "none"


def test_selection_context_uses_current_authored_prompt_and_preserves_original_input_without_mutating_history():
    initial = prompt_intent.penguin_request("Hi", "classify", 1028, stage="classification")
    history = [initial["messages"][-1], {"role": "assistant", "content": "SHOW"}]
    followup = prompt_intent.penguin_request("Hi", "select noun", 1028, stage="lucid-noun", history=history)
    assert followup["messages"][0] == {"role": "system", "content": "select noun"}
    assert followup["messages"][1:3] == history
    assert followup["messages"][2] == history[-1]
    assert followup["messages"][3:] == [{"role": "user", "content": "Hi"}]
    assert len(history) == 2
    assert followup["messages"][1] is not history[0]
    assert followup["max_tokens"] == initial["max_tokens"] == 1028
    assert followup["tools"] == [] and followup["tool_choice"] == "none"
    with pytest.raises(ValueError, match="penguin-context-input-mismatch"):
        prompt_intent.penguin_request("Other", "select noun", 1034, stage="lucid-noun", history=history)
    with pytest.raises(ValueError, match="penguin-semantic-context-forbidden"):
        prompt_intent.penguin_request("Hi", "semantic", 1028, stage="semantic-preparation", history=history)
    with pytest.raises(ValueError, match="penguin-context-turn-bound"):
        prompt_intent.penguin_request("Hi", "select noun", 1028, stage="lucid-noun", history=history * 32)
    history[-1]["content"] = "x" * 262144
    with pytest.raises(ValueError, match="penguin-context-byte-bound"):
        prompt_intent.penguin_request("Hi", "select noun", 1028, stage="lucid-noun", history=history)


@pytest.mark.parametrize("finish,extra", [("stop", {}), ("length", {}),
    ("stop", {"tool_calls": [{"id": "forbidden"}]})])
def test_selection_context_retains_only_completed_text_and_receipts_exact_messages(monkeypatch, finish, extra):
    context = {"input": "Hi", "messages": []}
    records = []
    monkeypatch.setattr(prompt_intent._REQUEST, "selection_context", context, raising=False)
    monkeypatch.setattr(prompt_intent._REQUEST, "stages", records, raising=False)
    monkeypatch.setattr(prompt_intent._REQUEST, "submission", None, raising=False)
    connection = Mock()
    connection.getresponse.return_value.status = 200
    connection.getresponse.return_value.read.return_value = json.dumps({"choices": [{
        "finish_reason": finish, "message": {"content": "INVALID", "reasoning_content": "private", **extra}}]}).encode()
    monkeypatch.setattr(prompt_intent.http.client, "HTTPConnection", Mock(return_value=connection))
    if finish == "stop" and not extra:
        prompt_intent.penguin_inference("Hi", "select noun", "lucid-noun", 1028)
        prompt_intent.penguin_inference("Hi", "retry noun", "lucid-noun", 1028)
        outgoing = [json.loads(call.args[2]) for call in connection.request.call_args_list]
        assert outgoing[1]["messages"][0] == {"role": "system", "content": "retry noun"}
        assert outgoing[1]["messages"][1] == outgoing[0]["messages"][1]
        assert outgoing[1]["messages"][2] == {"role": "assistant", "content": "INVALID"}
        assert [record["context"]["prior_turns"] for record in records] == [0, 1]
        assert len(context["messages"]) == 4
        assert "private" not in json.dumps(context)
        for record, request in zip(records, outgoing):
            assert record["request_messages"] == request["messages"]
            assert "system_prompt" not in record and "stage_prompt" not in record
            assert record["system_prompt_message_index"] == 0
            instruction = record["request_messages"][record["system_prompt_message_index"]]["content"]
            assert record["system_prompt_hash"] == prompt_intent.input_hash(instruction)
            assert sum(message["content"] == instruction for message in record["request_messages"]) == 1
            assert record["request_hash"] == prompt_intent.input_hash(json.dumps(
                request, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    else:
        with pytest.raises(ValueError, match="penguin-tool-output-forbidden" if extra else "penguin-response-incomplete"):
            prompt_intent.penguin_inference("Hi", "select noun", "lucid-noun", 1028)
        assert context["messages"] == []


@pytest.mark.parametrize("fail", [False, True])
def test_admissions_clear_selection_context_on_success_and_failure(tmp_path, monkeypatch, fail):
    contexts = []

    def classify(text):
        context = prompt_intent._REQUEST.selection_context
        assert context == {"input": text, "messages": []}
        contexts.append(context)
        context["messages"].append({"role": "assistant", "content": "previous submission marker"})
        if fail:
            raise ValueError("context-cleanup-probe")
        return "🧠"

    monkeypatch.setattr(prompt_intent, "classify", classify)
    monkeypatch.setattr(prompt_intent, "format_semantic", Mock(return_value=gestalt("SEMANTIC", "Hello")))
    for suffix in ("-first", "-second"):
        prompt_intent.admit_prompt("Hello", SUBMISSION + suffix, "session", "/workspace", tmp_path)
        assert prompt_intent._REQUEST.selection_context is None
    assert contexts[0] is not contexts[1]


def test_live_semantic_thinking_is_disabled_and_unknown_stage_refuses():
    request = prompt_intent.penguin_request("Hi", "instruction", 1028, stage="semantic-preparation")
    assert request["chat_template_kwargs"] == {"enable_thinking": False}
    assert request["messages"] == [{"role": "system", "content": "instruction"}, {"role": "user", "content": "Hi"}]
    assert request["max_tokens"] == 1028
    assert request["tools"] == [] and request["tool_choice"] == "none"
    with pytest.raises(ValueError, match="penguin-request-stage-invalid"):
        prompt_intent.penguin_request("Hi", "instruction", 1028, stage="unregistered")


def test_semantic_comparison_pairs_change_only_thinking_and_keep_results_unobserved():
    from tui_gateway import penguin_funnel

    comparison = prompt_intent.semantic_thinking_comparison(ROOT)
    projection = penguin_funnel.project("semantic-preparation")
    cases = {case["id"]: case for case in penguin_funnel.corpus()["cases"]}
    assert comparison["inference_ran"] is False
    assert comparison["live_semantic_policy"] == "enable_thinking=false"
    assert [pair["case_id"] for pair in comparison["pairs"]] == projection["case_ids"]
    for pair in comparison["pairs"]:
        assert pair["input"] == cases[pair["case_id"]]["input"]
        assert pair["expected_output"] == cases[pair["case_id"]]["semantic"]
        assert pair["expected_is_observed"] is False
        off, on = pair["variants"]
        assert off["request"]["chat_template_kwargs"] == {"enable_thinking": False}
        assert on["request"]["chat_template_kwargs"] == {"enable_thinking": True}
        assert {key: value for key, value in off["request"].items() if key != "chat_template_kwargs"} == {
            key: value for key, value in on["request"].items() if key != "chat_template_kwargs"}
        for variant in pair["variants"]:
            request = variant["request"]
            assert request["messages"][1] == {"role": "user", "content": pair["input"]}
            assert request["messages"][0]["content"] == projection["prompt"]
            assert variant["request_hash"] == prompt_intent.input_hash(json.dumps(
                request, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
            assert all(variant[field] is None for field in ("response", "usage", "elapsed_ms", "witness"))


@pytest.mark.parametrize("details", [None, {"cached_tokens": 12}, {"cached_tokens": -1}, {"cached_tokens": True}])
def test_cached_usage_is_retained_only_when_reported_as_nonnegative_integer(monkeypatch, details):
    connection = Mock()
    connection.getresponse.return_value.status = 200
    usage = {"prompt_tokens": 20, "completion_tokens": 3, "total_tokens": 23}
    if details is not None:
        usage["prompt_tokens_details"] = details
    connection.getresponse.return_value.read.return_value = json.dumps({"choices": [{
        "finish_reason": "stop", "message": {"content": "🧠"}}], "usage": usage}).encode()
    monkeypatch.setattr(prompt_intent.http.client, "HTTPConnection", Mock(return_value=connection))
    records = []
    monkeypatch.setattr(prompt_intent._REQUEST, "stages", records, raising=False)
    prompt_intent.penguin_inference("Hi", prompt_intent.classification_instruction(), "classification", 1028)
    assert records[0]["request_settings"]["chat_template_kwargs"] == {"enable_thinking": False}
    if details == {"cached_tokens": 12}:
        assert records[0]["usage"]["prompt_tokens_details"] == details
    else:
        assert "prompt_tokens_details" not in records[0]["usage"]


def test_classification_and_rewrite_use_the_same_input_sized_budget(monkeypatch):
    infer = Mock(return_value="🧠")
    monkeypatch.setattr(prompt_intent, "penguin_inference", infer)
    for text in ["Hi", "Welcome to AE", "🐧"]:
        prompt_intent.classify(text)
        prompt_intent.format_semantic(text)
        for call in infer.call_args_list[-2:]:
            assert call.args[0] == text
            assert call.args[3] == 1024 + 2 * len(text.encode("utf-8"))


@pytest.mark.parametrize("stage", ["classification", "semantic-preparation"])
@pytest.mark.parametrize("extra,finish", [
    ({"tool_calls": [{"id": "call-1", "type": "function", "function": {
        "name": "mcp__lucid__get", "arguments": "{}"}}]}, "stop"),
    ({"function_call": {"name": "get", "arguments": "{}"}}, "stop"),
    ({}, "tool_calls"),
    ({}, "function_call"),
])
def test_preprocessing_rejects_tool_outputs_even_with_valid_text(stage, extra, finish, monkeypatch):
    connection = Mock()
    connection.getresponse.return_value.status = 200
    connection.getresponse.return_value.read.return_value = json.dumps({"choices": [{
        "finish_reason": finish, "message": {"content": "🧠", **extra},
    }]}).encode()
    monkeypatch.setattr(prompt_intent.http.client, "HTTPConnection", Mock(return_value=connection))
    execute = Mock()
    monkeypatch.setattr(prompt_intent, "execute_direct", execute)
    instruction = (prompt_intent.classification_instruction() if stage == "classification"
        else prompt_intent.penguin_instruction(ROOT))
    with pytest.raises(ValueError, match="penguin-tool-output-forbidden"):
        prompt_intent.penguin_inference("Hi", instruction, stage, prompt_intent.penguin_max_tokens("Hi"))
    outgoing = json.loads(connection.request.call_args.args[2])
    assert outgoing["tools"] == [] and outgoing["tool_choice"] == "none"
    connection.close.assert_called_once()
    execute.assert_not_called()


@pytest.mark.parametrize("signal", ["🟢", "⏳", "⚠️", "🔴"])
def test_restatement_state_describes_input_not_preparation_failure(signal):
    response = f"{signal}{glyph.DELIMITER_SEGMENT}{glyph.RELATION_EVIDENCE} User-reported state{glyph.DELIMITER_SEGMENT}{glyph.RELATION_DATUM} Do not retry{glyph.DELIMITER_SEGMENT}{glyph.SIGNAL_PENDING} Age 5m"
    assert prompt_intent.decode_preparation("Report state; do not retry", response, ROOT) == {
        "classification": "semantic", "gestalt": response,
    }


def test_represented_command_does_not_execute_for_semantic_input():
    mixed = gestalt("SEMANTIC", "Explain the result.", "OBJECTIVE") + f"\n\n{glyph.RELATION_ACTION} `git status`"
    assert prompt_intent.decode_preparation("Explain the result", mixed, ROOT)["classification"] == "semantic"


@pytest.mark.parametrize("continuation", [
    f'{glyph.RELATION_ACTION} "Inspect the result"', f'{glyph.RELATION_ACTION} `git diff`',
    f'{glyph.RELATION_ACTION} {glyph.IDENTITY_LUCID}{glyph.DELIMITER_SEGMENT}{glyph.RELATION_VERB} GET{glyph.DELIMITER_SEGMENT}{glyph.RELATION_NOUN} ROLE{glyph.DELIMITER_SEGMENT}{glyph.RELATION_EVIDENCE} Inspect role',
])
def test_semantic_markdown_tables_and_cyoa_are_preserved_without_execution(tmp_path, monkeypatch, continuation):
    text = "Compare options without modifying files"
    response = gestalt("SEMANTIC", "Compare the options", "OBJECTIVE") + (
        '\n\n| Obligation | Meaning |\n|---|---|\n| Prohibition | Do not modify files |\n\n'
        + continuation + '\n\n🐧🐧'
    )
    execute = Mock()
    monkeypatch.setattr(prompt_intent, "classify", Mock(return_value="🧠"))
    monkeypatch.setattr(prompt_intent, "format_semantic", Mock(return_value=response))
    monkeypatch.setattr(prompt_intent, "execute_direct", execute)
    result = prompt_intent.admit_prompt(text, SUBMISSION, "session", "/workspace", tmp_path)
    assert result["prepared_text"] == text
    assert result["preparation"]["diagnostic"]["transformed_input"] == response
    assert result["preparation"]["diagnostic"]["penguin_response"] == response
    execute.assert_not_called()


def test_semantic_headings_math_and_code_remain_document_content():
    response = gestalt("SEMANTIC", "Explain the expression", "OBJECTIVE") + (
        '\n\n## Expression\n\n$$\nx + 1\n$$\n\n```python\nprint(1)\n```\n\n🐧🐧'
    )
    candidate = prompt_intent.decode_preparation("Explain the expression", response, ROOT)
    assert prompt_intent.prepare_semantic("Explain the expression", candidate, ROOT) == "Explain the expression"


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
    f'{glyph.SIGNAL_GREEN}{glyph.DELIMITER_SEGMENT}{glyph.RELATION_DATUM} Explain this command\n\n{glyph.RELATION_ACTION} "git status"\n\n{glyph.IDENTITY_PENGUIN}',
    f'{glyph.SIGNAL_GREEN}{glyph.DELIMITER_SEGMENT}{glyph.RELATION_DATUM} Explain this command\n\n{glyph.RELATION_ACTION} git status\n\n{glyph.IDENTITY_PENGUIN}',
    f'| Example | Command |\n|---|---|\n| Quoted | {glyph.RELATION_ACTION} `git status` |\n\n{glyph.IDENTITY_PENGUIN}',
])
def test_semantic_output_cannot_select_direct_execution(response):
    assert prompt_intent.decode_preparation("git status", response, ROOT)["classification"] == "semantic"


def test_table_only_gestalt_does_not_require_an_invented_routing_label():
    response = f'| {RELATION_DATUM} | Meaning |\n|---|---|\n| 🔎 | Compare the options |'
    result = prompt_intent.decode_preparation("Compare options", response, ROOT)
    assert result == {"classification": "semantic", "gestalt": response}


def test_local_presentations_emit_canonical_source_and_protect_literal_input():
    original = f'```\n{glyph.SIGNAL_RED}{glyph.DELIMITER_SEGMENT}{glyph.IDENTITY_PENGUIN}{glyph.DELIMITER_SEGMENT}{glyph.RELATION_EVIDENCE} literal{glyph.DELIMITER_SEGMENT}{glyph.RELATION_ACTION} "Help"\n```'
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
    response = gestalt("SEMANTIC", "Compare the approaches.", "OBJECTIVE") + f'\n\n{glyph.RELATION_ACTION} "Explain tradeoffs"\n\n{glyph.IDENTITY_PENGUIN}{glyph.IDENTITY_PENGUIN}'
    connection = Mock()
    connection.getresponse.return_value.status = 200
    connection.getresponse.return_value.read.side_effect = [json.dumps({"choices": [
        {"finish_reason": "stop", "message": {"content": content, "reasoning_content": "Internal reasoning"}}]}).encode()
        for content in ["🧠", response]]
    monkeypatch.setattr(prompt_intent.http.client, "HTTPConnection", Mock(return_value=connection))
    result = prompt_intent.admit_prompt("Compare approaches", SUBMISSION, "session", "/workspace", tmp_path)
    actual_prompt = json.loads(connection.request.call_args.args[2])["messages"][0]["content"]
    diagnostic = result["preparation"]["diagnostic"]
    assert "penguin_system_prompt" not in diagnostic
    assert "penguin_system_prompt_hash" not in diagnostic
    assert diagnostic["stages"][-1]["request_messages"][0]["content"] == actual_prompt
    assert all("system_prompt" not in stage and "stage_prompt" not in stage for stage in diagnostic["stages"])
    assert diagnostic["stages"][-1]["system_prompt_hash"] == prompt_intent.input_hash(actual_prompt)
    assert diagnostic["penguin_response"] == response
    assert result["prepared_text"] == "Compare approaches"
    calls = [json.loads(call.args[2]) for call in connection.request.call_args_list]
    assert len(calls) == 2
    assert calls[0]["messages"][0]["content"] == prompt_intent.classification_instruction()
    assert calls[0]["messages"][1]["content"] == "Compare approaches"
    assert calls[0]["max_tokens"] == calls[1]["max_tokens"] == 1024 + 2 * len("Compare approaches".encode("utf-8"))
    assert calls[1]["messages"][0]["content"] == prompt_intent.penguin_instruction(ROOT)
    assert [stage["stage"] for stage in diagnostic["stages"]] == ["classification", "semantic-preparation"]
    assert [stage["response"] for stage in diagnostic["stages"]] == ["🧠", response]
    assert all(stage["finish_reason"] == "stop" for stage in diagnostic["stages"])
    assert all(stage["reasoning_chars"] == len("Internal reasoning") for stage in diagnostic["stages"])
    assert "Internal reasoning" not in json.dumps(diagnostic)
    assert all(stage["input"] == "Compare approaches" for stage in diagnostic["stages"])
    for stage, request in zip(diagnostic["stages"], calls):
        assert stage["token_budget"] == {"base_tokens": 1024, "tokens_per_user_input_byte": 2,
            "encoding": "utf-8", "user_input_bytes": len("Compare approaches".encode("utf-8"))}
        assert stage["request_settings"] == {key: value for key, value in request.items() if key != "messages"}
        assert stage["request_messages"] == request["messages"]
        assert stage["request_hash"] == prompt_intent.input_hash(
            json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


@pytest.mark.parametrize("partial", [None, "unfinished response"])
def test_rewrite_exhaustion_does_not_report_classifier_output_as_rewrite(tmp_path, monkeypatch, partial):
    text = 'This is an introduction into the LUCID system.\n\nLUCID has been alive for 5 minutes.\n\nThe system is awaiting your sign in, use value "EM"'
    budget = prompt_intent.penguin_max_tokens(text)
    assert budget == 1296
    monkeypatch.setattr(prompt_intent.time, "monotonic", lambda: 0)
    connection = Mock()
    connection.getresponse.return_value.status = 200
    connection.getresponse.return_value.read.side_effect = [
        json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": "\n\n🧠"}}]}).encode(),
        json.dumps({"choices": [{"finish_reason": "length", "message": {"content": partial}}],
            "usage": {"completion_tokens": budget}}).encode(),
    ]
    monkeypatch.setattr(prompt_intent.http.client, "HTTPConnection", Mock(return_value=connection))
    execute = Mock()
    monkeypatch.setattr(prompt_intent, "execute_direct", execute)
    events = []
    result = prompt_intent.admit_prompt(text, SUBMISSION, "session", "/workspace", tmp_path,
        on_preparation=events.append)
    diagnostic = result["direct_operation"]["diagnostic"]
    assert diagnostic["classifier_response"] == "\n\n🧠"
    assert diagnostic["penguin_response"] is None
    assert diagnostic["receipt"]["phase"] == "semantic-preparation"
    assert diagnostic["receipt"]["refusal"] == "penguin-response-incomplete"
    assert diagnostic["stages"][-1]["response"] == partial
    assert diagnostic["stages"][-1]["usage"]["completion_tokens"] == budget
    assert diagnostic["receipt"]["ran"] is False
    assert "prepared_text" not in result
    semantic_event = next(event for event in events if event["diagnostic"]["phase"] == "semantic-preparation")
    assert semantic_event["diagnostic"]["penguin_response"] is None
    request = json.loads(connection.request.call_args.args[2])
    assert request["messages"] == [
        {"role": "system", "content": prompt_intent.penguin_instruction(ROOT)},
        {"role": "user", "content": text},
    ]
    assert request["chat_template_kwargs"] == {"enable_thinking": False}
    assert request["max_tokens"] == budget
    assert connection.request.call_count == 2
    source = result["direct_operation"]["source"]
    projected = parse_stream(ROOT, source.split("\n\n", 1)[0])
    assert projected["evidence"] == ["RESPONSE TOKEN LIMIT"]
    assert projected["data"] == [
        "SEMANTIC PREPARATION", "1296/1296 completion tokens",
        "No response text returned" if partial is None else "Incomplete response withheld",
        "Thinking disabled requested", "Execution not started",
    ]
    assert projected["timing"] == ["Elapsed 0.0s"]
    assert source.endswith("```text\n" + text + "\n```")
    if partial is not None:
        assert partial not in source
    execute.assert_not_called()


@pytest.mark.parametrize("usage,expected", [
    ({}, ["1028-token response limit"]),
    ({"completion_tokens": 1028, "completion_tokens_details": {"reasoning_tokens": 1028},
        "prompt_tokens_details": {"cached_tokens": 0}}, ["1028/1028 completion tokens", "1028 reasoning tokens reported"]),
])
def test_token_limit_projection_does_not_invent_usage_or_backend_reasoning(usage, expected):
    evidence = {"diagnostic": {
        "submission_id": SUBMISSION, "original_input": "Hi",
        "receipt": {"refusal": "penguin-response-incomplete", "phase": "semantic-preparation",
            "ran": False, "execution_state": "not-started"},
        "stages": [{"stage": "semantic-preparation", "finish_reason": "length", "max_tokens": 1028,
            "response": None, "usage": usage, "request_settings": {}}],
    }}
    original = json.dumps(evidence["diagnostic"], sort_keys=True)
    prompt_intent.project_penguin_failure(evidence)
    projected = parse_stream(ROOT, evidence["source"].split("\n\n", 1)[0])
    assert projected["evidence"] == ["RESPONSE TOKEN LIMIT"]
    assert projected["data"] == ["SEMANTIC PREPARATION", expected[0], "No response text returned",
        "Thinking mode unspecified", *expected[1:], "Execution not started"]
    assert projected["timing"] == []
    assert "cached_tokens" not in evidence["source"]
    assert "response" not in evidence["diagnostic"]["receipt"]
    assert json.dumps({key: value for key, value in evidence["diagnostic"].items() if key != "recovery"}, sort_keys=True) == original


def test_incomplete_reasoning_response_retains_budget_evidence_without_duplicate_prompt(tmp_path, monkeypatch):
    text = "How's your day going"
    budget = 1024 + 2 * len(text.encode("utf-8"))
    connection = Mock()
    connection.getresponse.return_value.status = 200
    connection.getresponse.return_value.read.return_value = json.dumps({
        "choices": [{"finish_reason": "length", "message": {"content": None, "reasoning_content": "Still reasoning"}}],
        "usage": {"prompt_tokens": 300, "completion_tokens": budget, "total_tokens": 300 + budget},
    }).encode()
    monkeypatch.setattr(prompt_intent.http.client, "HTTPConnection", Mock(return_value=connection))
    execute = Mock()
    monkeypatch.setattr(prompt_intent, "execute_direct", execute)
    events = []
    result = prompt_intent.admit_prompt(text, SUBMISSION, "session", "/workspace", tmp_path,
        on_preparation=events.append)
    diagnostic = result["direct_operation"]["diagnostic"]
    assert diagnostic["receipt"]["refusal"] == "penguin-response-incomplete"
    stage = diagnostic["stages"][0]
    assert stage["finish_reason"] == "length"
    assert stage["max_tokens"] == stage["usage"]["completion_tokens"] == budget
    assert stage["reasoning_chars"] == len("Still reasoning")
    assert stage["response"] is None
    assert "Still reasoning" not in json.dumps(diagnostic)
    assert "penguin_system_prompt" not in diagnostic
    assert all("penguin_system_prompt" not in event["diagnostic"] for event in events)
    source = result["direct_operation"]["source"]
    assert "document" not in result["direct_operation"]
    projected = parse_stream(ROOT, source.split("\n\n", 1)[0])
    assert projected["evidence"] == ["RESPONSE TOKEN LIMIT"]
    assert projected["data"][0] == "CLASSIFICATION"
    assert f"{budget}/{budget} completion tokens" in projected["data"]
    assert "Thinking disabled requested" in projected["data"]
    assert f"{len('Still reasoning')} reasoning characters reported" in projected["data"]
    assert f'{glyph.DELIMITER_SEGMENT}{glyph.RELATION_ACTION} "Retry"{glyph.DELIMITER_SEGMENT}{glyph.RELATION_ACTION} "Bypass"{glyph.DELIMITER_SEGMENT}{glyph.RELATION_ACTION} "Help"' in source.split("\n\n", 1)[0]
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
    monkeypatch.setattr(prompt_intent, "classify", Mock(return_value="🔎"))
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
    literal = f'```\n{glyph.SIGNAL_RED}{glyph.DELIMITER_SEGMENT}{glyph.IDENTITY_PENGUIN}{glyph.DELIMITER_SEGMENT}{glyph.RELATION_EVIDENCE} INPUT\n\n{glyph.RELATION_ACTION} "execute"\n{{"type":"button"}}\n```\n'
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


@pytest.mark.parametrize("text,label,channel", [("git status", "🤖", "cli"), ("lucid get role", "🔎", "lucid")])
def test_classifier_label_selects_the_explicit_host_adapter(text, label, channel):
    assert prompt_intent.decode_classification(text, label)["operation"]["channel"] == channel


def test_get_and_semantic_glyphs_are_distinct_routes():
    choices = prompt_intent.classifier_choices()
    assert len(choices) == 9
    assert choices[glyph.IDENTITY_LUCID] == "semantic"
    assert choices[glyph.RELATION_EVIDENCE] == "lucid"
    assert prompt_intent.classifier_verbs()[glyph.RELATION_EVIDENCE] == "get"
    assert prompt_intent.decode_classification("Hi", glyph.IDENTITY_LUCID) == {
        "classification": "semantic", "classifier_response": glyph.IDENTITY_LUCID,
    }
    candidate = prompt_intent.decode_classification("Retrieve current status", glyph.RELATION_EVIDENCE)
    assert candidate["classification"] == "lucid" and candidate["selected_verb"] == "get"
    assert "operation" not in candidate


@pytest.mark.parametrize("collision", ["semantic", "cli", "verb"])
def test_classifier_rejects_registry_glyph_collisions(monkeypatch, collision):
    vocabulary = json.loads(json.dumps(prompt_intent.lucid_vocabulary()))
    vocabulary["verbs"]["get"]["glyph"] = {
        "semantic": glyph.IDENTITY_LUCID, "cli": "🤖",
        "verb": vocabulary["verbs"]["show"]["glyph"],
    }[collision]
    monkeypatch.setattr(prompt_intent, "lucid_vocabulary", lambda: vocabulary)
    with pytest.raises(ValueError, match="classifier-label-collision"):
        prompt_intent.classifier_choices()
    with pytest.raises(ValueError, match="classifier-label-collision"):
        prompt_intent.classification_instruction()


@pytest.mark.parametrize("verb", list(prompt_intent.lucid_vocabulary()["verbs"]))
def test_each_classifier_verb_is_retained_and_morph_is_system_routed(verb):
    label = prompt_intent.lucid_vocabulary()["verbs"][verb]["glyph"]
    result = prompt_intent.decode_classification("Please handle this request", label)
    assert result["selected_verb"] == verb
    assert result["classification"] == ("semantic" if verb == "morph" else "lucid")
    assert "operation" not in result
    if verb == "morph":
        assert result["routing_reason"] == "morph-requires-semantic"


def test_classifier_cannot_rebind_an_explicit_verb():
    with pytest.raises(ValueError, match="classifier-verb-mismatch"):
        prompt_intent.decode_classification("GET role", "✏️")
    infer = Mock()
    traversal = Traversal("GET role", prompt_intent.lucid_vocabulary(), infer)
    with pytest.raises(ValueError, match="classifier-verb-mismatch"):
        traversal.run(ROOT, {"channel": "lucid", "verb": "get", "argv": ["role"]}, classified_verb="set")
    infer.assert_not_called()


def test_undeclared_classified_verb_never_enters_noun_selection():
    infer = Mock()
    traversal = Traversal("request", prompt_intent.lucid_vocabulary(), infer)
    with pytest.raises(ValueError, match="lucid-verb-not-declared"):
        traversal.run(ROOT, classified_verb="deploy")
    infer.assert_not_called()


@pytest.mark.parametrize("response", ["CLI", "GET", "SHOW", "MORPH", "SHOW GET", "DEPLOY", "🤖 🔎", f"{glyph.SIGNAL_GREEN}{glyph.DELIMITER_SEGMENT}{glyph.RELATION_DATUM} 🤖", "", '{"route":"cli"}'])
def test_classifier_rejects_anything_except_one_declared_label(response):
    with pytest.raises(ValueError, match="penguin-classifier-glyph-invalid"):
        prompt_intent.decode_classification("git status", response)


def test_misclassified_agent_role_instruction_never_mutates_witness_identity(tmp_path, monkeypatch):
    monkeypatch.setattr(prompt_intent, "classify", Mock(return_value="✏️"))
    monkeypatch.setattr(prompt_intent, "penguin_inference", Mock(return_value="not-a-choice"))
    formatter = Mock()
    execute = Mock()
    monkeypatch.setattr(prompt_intent, "format_semantic", formatter)
    monkeypatch.setattr(prompt_intent, "execute_direct", execute)
    result = prompt_intent.admit_prompt("Sign in as EM", SUBMISSION, "session", "/workspace", tmp_path)
    assert result["direct_operation"]["diagnostic"]["classifier_response"] == "✏️"
    assert result["direct_operation"]["diagnostic"]["receipt"]["refusal"] == "lucid-help-selection-invalid:lucid-noun"
    formatter.assert_not_called()
    execute.assert_not_called()


def test_classifier_teaches_glyph_intents_without_protocol_routing_details():
    instruction = prompt_intent.classification_instruction()
    vocabulary = prompt_intent.lucid_vocabulary()
    assert "lucid" not in instruction.lower()
    header = f"**PROMPT**{glyph.DELIMITER_SEGMENT}**EXPECTED OUTPUT**"
    assert "{{" not in instruction
    for noun in ("plan.dispatch", "speech", "dispatch:", "sha256", "64-lowercase"):
        assert noun not in instruction
    assert "ALWAYS" not in instruction and "EXCEPT MORPH" not in instruction
    assert "CLI TERMINAL INPUT: PROGRAM + ARGS/FLAGS" in instruction
    for definition in vocabulary["verbs"].values():
        assert f"\n{definition['glyph']} · " in instruction
    assert "**CLASSIFICATION PROTOCOL** · **RULE**" in instruction
    assert "**OUTPUT LABEL** · **RULE**" in instruction
    assert "=>" not in instruction
    rows = instruction.split(header + "\n", 1)[1].strip().splitlines()
    from tui_gateway import penguin_funnel
    cases = penguin_funnel.corpus()["cases"]
    assert len(rows) == len(cases)
    examples = {}
    for row in rows:
        original, end = json.JSONDecoder().raw_decode(row)
        assert row[end:].startswith(glyph.DELIMITER_SEGMENT)
        encoded = row[end + len(glyph.DELIMITER_SEGMENT):]
        assert encoded.startswith("`") and encoded.endswith("`")
        output = encoded[1:-1]
        assert output in prompt_intent.classifier_choices()
        assert original not in examples
        examples[original] = output
    assert sum(output == "🤖" for output in examples.values()) == 10
    assert examples['SHOW PULSE'] == vocabulary["verbs"]["show"]["glyph"]
    assert examples['Open https://example.com/Path?q=Case%20A'] == vocabulary["verbs"]["show"]["glyph"]
    assert examples['GET role'] == vocabulary["verbs"]["get"]["glyph"]
    assert examples['echo "SHOW PULSE"'] == "🤖"
    assert examples["MORPH"] == examples["Turn this idea into a comic"] == vocabulary["verbs"]["morph"]["glyph"]
    assert set(examples.values()) == set(prompt_intent.classifier_choices())
    for original in ("Sign in as EM", "--offline", "Run git status and explain the changes"):
        assert examples[original] == glyph.IDENTITY_LUCID


@pytest.mark.parametrize("text,verb,argv", [
    ("SHOW SNAKE", "show", ["SNAKE"]),
    ("GET coverage", "get", ["coverage"]),
    ("lucid GET role", "get", ["role"]),
])
def test_bare_canonical_verbs_share_lucid_classification_and_admission(text, verb, argv):
    from tui_gateway.intent_admission import SCHEMA, catalog_hash, evaluate_twitch, input_hash

    candidate = prompt_intent.decode_classification(text, prompt_intent.lucid_vocabulary()["verbs"][verb]["glyph"])
    assert candidate["operation"] == {"channel": "lucid", "verb": verb, "argv": argv}
    bound = {key: value for key, value in candidate.items() if key != "classifier_response"}
    bound.update(schema=SCHEMA, input_hash=input_hash(text), catalog_hash=catalog_hash())
    assert evaluate_twitch(text, bound, lucid_verbs=prompt_intent.lucid_vocabulary()["verbs"]).operation == candidate["operation"]


@pytest.mark.parametrize("text,argv,formatted", [
    ("SHOW PULSE", ["PULSE"], f'{glyph.RELATION_ACTION} {glyph.IDENTITY_LUCID}{glyph.DELIMITER_SEGMENT}{glyph.RELATION_VERB} SHOW{glyph.DELIMITER_SEGMENT}{glyph.RELATION_NOUN} PULSE{glyph.DELIMITER_SEGMENT}{glyph.RELATION_EVIDENCE} Show pulse'),
    ('SHOW URL "https://example.com/"', ["URL", "https://example.com/"], f'{glyph.RELATION_ACTION} {glyph.IDENTITY_LUCID}{glyph.DELIMITER_SEGMENT}{glyph.RELATION_VERB} SHOW{glyph.DELIMITER_SEGMENT}{glyph.RELATION_NOUN} URL{glyph.DELIMITER_SEGMENT}{glyph.RELATION_ARGUMENT} `https://example.com/`{glyph.DELIMITER_SEGMENT}{glyph.RELATION_EVIDENCE} Open URL'),
    ('SHOW APP "macos-shell"', ["APP", "macos-shell"], f'{glyph.RELATION_ACTION} {glyph.IDENTITY_LUCID}{glyph.DELIMITER_SEGMENT}{glyph.RELATION_VERB} SHOW{glyph.DELIMITER_SEGMENT}{glyph.RELATION_NOUN} APP{glyph.DELIMITER_SEGMENT}{glyph.RELATION_ARGUMENT} `macos-shell`{glyph.DELIMITER_SEGMENT}{glyph.RELATION_EVIDENCE} Open macOS Shell'),
])
def test_lucid_second_pass_preserves_skill_coordinates(tmp_path, monkeypatch, text, argv, formatted):
    monkeypatch.setattr(prompt_intent, "classify", Mock(return_value="🖼️"))
    lucid = Mock(wraps=prompt_intent.format_lucid)
    semantic = Mock()
    execute = Mock(return_value={"ran": True, "exit_code": 0})
    monkeypatch.setattr(prompt_intent, "format_lucid", lucid)
    monkeypatch.setattr(prompt_intent, "format_semantic", semantic)
    monkeypatch.setattr(prompt_intent, "execute_direct", execute)
    result = prompt_intent.admit_prompt(text, SUBMISSION, "session", "/workspace", tmp_path)
    execute.assert_called_once_with(SUBMISSION, "/workspace", {"channel": "lucid", "verb": "show", "argv": argv})
    lucid.assert_called_once_with(text, "show")
    semantic.assert_not_called()
    action = result["direct_operation"]["diagnostic"]["penguin_response"]
    parsed = parse_stream(ROOT, SIGNAL_GREEN + f"{glyph.DELIMITER_SEGMENT}" + action)["actions"][0]
    expected = parse_stream(ROOT, SIGNAL_GREEN + f"{glyph.DELIMITER_SEGMENT}" + formatted)["actions"][0]
    assert {key: value for key, value in parsed.items() if key != "label"} == {key: value for key, value in expected.items() if key != "label"}
    assert all(step.get("selection_source") != "penguin" for step in result["direct_operation"]["diagnostic"]["lucid_traversal"]["steps"])


def test_help_traversal_focuses_each_step_and_preserves_original():
    original = "Open https://example.com/"
    infer = Mock(side_effect=["url", "omit", '"https://example.com/"'])
    traversal = Traversal(original, prompt_intent.lucid_vocabulary(), infer)
    result = traversal.run(ROOT, classified_verb="show")
    assert result["resolved_arguments"] == {"view": "url", "url": "https://example.com/"}
    calls = infer.call_args_list
    assert all(call.args[0] == original for call in calls)
    assert [call.args[2] for call in calls] == ["lucid-noun", "lucid-optional", "lucid-argument:url"]
    assert result["steps"][0]["selection_source"] == "classifier"
    assert result["steps"][0]["selected"] == "show"
    assert result["steps"][0]["classification_selection"] == prompt_intent.lucid_vocabulary()["verbs"]["show"]["glyph"]
    assert result["steps"][0]["inference_ran"] is False
    assert "system_prompt" not in result["steps"][0]
    assert "dispatch" not in calls[0].args[1].lower()
    assert "macos-shell" not in calls[-1].args[1]
    assert all(step.get("help_hash") for step in result["steps"])
    assert all(step.get("help_source", "").startswith("envelope/LUCID.json#/") for step in result["steps"])


def test_invalid_selection_retries_only_current_decision_then_refuses():
    infer = Mock(side_effect=["invalid", "still-invalid"])
    traversal = Traversal("Open the app", prompt_intent.lucid_vocabulary(), infer)
    with pytest.raises(ValueError, match="lucid-help-selection-invalid:lucid-noun"):
        traversal.run(ROOT, classified_verb="show")
    assert infer.call_count == 2
    assert len(traversal.records) == 2
    assert traversal.records[-1]["validation"] == "refused"
    assert len(traversal.records[-1]["attempts"]) == 2
    attempts = traversal.records[-1]["attempts"]
    for attempt, call in zip(attempts, infer.call_args_list):
        assert attempt["system_prompt"] == call.args[1]
        assert attempt["system_prompt_hash"] == prompt_intent.input_hash(call.args[1])
        assert attempt["input"] == "Open the app"
        assert attempt["max_tokens"] == prompt_intent.penguin_max_tokens("Open the app")
    assert "**FEEDBACK** · **RULE**" not in attempts[0]["system_prompt"]
    assert "**FEEDBACK** · **RULE**" in attempts[1]["system_prompt"]


def test_selection_prompt_receipts_use_production_builders_and_canonical_rows():
    from tui_gateway.lucid_traversal import receipt_selection_prompts, MAX_PROMPT_BYTES

    records = receipt_selection_prompts(prompt_intent.lucid_vocabulary())
    assert {record["stage"] for record in records} >= {
        "lucid-noun", "lucid-optional", "lucid-optional:retry", "lucid-argument:url", "lucid-argument:app",
    }
    for record in records:
        instruction = record["system_prompt"]
        assert len(instruction.encode("utf-8")) <= MAX_PROMPT_BYTES
        assert record["system_prompt_hash"] == prompt_intent.input_hash(instruction)
        assert record["inference_ran"] is False and record["execution_ran"] is False
        assert "|---" not in instruction and "=>" not in instruction
        assert "**RESOLVED** · **VALUE**" in instruction
        rows = instruction.split("**EXAMPLE PROMPT** · **EXPECTED OUTPUT**\n", 1)[1].split("\n\n", 1)[0].splitlines()
        assert rows
        for row in rows:
            original, end = json.JSONDecoder().raw_decode(row)
            assert row[end:].startswith(glyph.DELIMITER_SEGMENT)
            encoded = row[end + len(glyph.DELIMITER_SEGMENT):]
            fence = encoded[:len(encoded) - len(encoded.lstrip("`"))]
            assert fence and encoded.endswith(fence)
            expected = encoded[len(fence):-len(fence)].strip()
            if "**OUTPUT LABEL**" in instruction and expected != glyph.SIGNAL_PENDING:
                choices = instruction.split("**OUTPUT LABEL** · **MEANING**\n", 1)[1].split("\n\n", 1)[0]
                assert any(line.split(glyph.DELIMITER_SEGMENT, 1)[0] == expected
                    for line in choices.splitlines())
                assert all(line == line.upper() and not line.startswith('"') for line in choices.splitlines())
            elif "**LITERAL PROTOCOL**" in instruction and expected != glyph.SIGNAL_PENDING:
                value = json.loads(expected)
                assert isinstance(value, str)
                assert value in original or json.dumps(value, ensure_ascii=False) in original
        request = prompt_intent.penguin_request(record["input"], instruction, prompt_intent.penguin_max_tokens(record["input"]), stage=record["stage"])
        assert request["tools"] == [] and request["tool_choice"] == "none"


def test_uncertain_choice_refuses_without_retry_or_guess():
    infer = Mock(return_value=glyph.SIGNAL_PENDING)
    traversal = Traversal("Which target?", prompt_intent.lucid_vocabulary(), infer)
    with pytest.raises(ValueError, match="lucid-help-selection-unresolved:lucid-noun"):
        traversal.run(ROOT, classified_verb="show")
    assert infer.call_count == 1
    assert traversal.records[-1]["validation"] == "missing-or-ambiguous"


def test_optional_prompt_excludes_already_selected_fields_without_mutating_contract():
    from tui_gateway.lucid_traversal import choice_instruction, optional_choices

    target = {"optional": ["scope", "speak"]}
    choices = optional_choices(target, ["scope"])
    assert choices == {"omit": "NO FURTHER REQUESTED OPTIONAL FIELDS", "speak": "SPEAK"}
    with pytest.raises(ValueError, match="funnel-coverage-gap"):
        choice_instruction("lucid-optional", choices,
            {"verb": "show", "noun": "pulse", "optional_arguments": ["scope"]})
    assert target["optional"] == ["scope", "speak"]


def test_uncertainty_label_cannot_be_a_registered_choice():
    infer = Mock()
    traversal = Traversal("request", prompt_intent.lucid_vocabulary(), infer)
    with pytest.raises(ValueError, match="lucid-help-choice-collision"):
        traversal.choose("lucid-noun", {glyph.SIGNAL_PENDING: "target"}, "fixture")
    infer.assert_not_called()


def test_uppercase_label_collision_refuses_before_inference():
    infer = Mock()
    traversal = Traversal("request", prompt_intent.lucid_vocabulary(), infer)
    with pytest.raises(ValueError, match="lucid-help-choice-collision"):
        traversal.choose("lucid-noun", {"app": "one", "APP": "two"}, "fixture")
    infer.assert_not_called()


def test_same_original_message_reaches_classification_rewrite_and_selection(monkeypatch):
    original = "Open https://example.com/Path with scope this."
    infer = Mock(side_effect=["🖼️", "proposed restatement", "URL", "SCOPE", '"https://example.com/Path"', '"this"'])
    monkeypatch.setattr(prompt_intent, "penguin_inference", infer)
    prompt_intent.classify(original)
    prompt_intent.format_semantic(original)
    prompt_intent.format_lucid(original, "show")
    assert all(call.args[0] == original for call in infer.call_args_list)
    assert [call.args[2] for call in infer.call_args_list] == [
        "classification", "semantic-preparation", "lucid-noun", "lucid-optional",
        "lucid-argument:url", "lucid-argument:scope",
    ]
    receipt = prompt_intent._REQUEST.lucid_traversal
    assert receipt["resolved_arguments"] == {"view": "url", "url": "https://example.com/Path", "scope": "this"}
    noun = receipt["steps"][1]
    assert noun["output_labels"]["URL"] == "url"
    assert noun["attempts"][0]["selection"] == "URL"
    assert noun["attempts"][0]["wire_value"] == "url"
    assert "VERB · 🖼️ SHOW" in noun["system_prompt"]
    assert "APP · OPEN AN APPLICATION" in noun["system_prompt"]


def test_generated_selection_cases_keep_the_original_request_across_stages():
    from tui_gateway.lucid_traversal import receipt_selection_prompts

    records = receipt_selection_prompts(prompt_intent.lucid_vocabulary())
    from tui_gateway import penguin_funnel
    cases = {case["id"]: case for case in penguin_funnel.corpus()["cases"]}
    stages = records
    assert {record["stage"] for record in stages} >= {
        "lucid-noun", "lucid-optional", "lucid-argument:url", "lucid-argument:scope",
    }
    assert all(record["input"] == cases[record["input_case_id"]]["input"] for record in stages)
    assert all(record["input_hash"] == prompt_intent.input_hash(record["input"]) for record in stages)
    assert all('Target: ' not in record["input"] for record in records)


def test_retry_prompt_is_bounded_before_another_inference(monkeypatch):
    from tui_gateway import lucid_traversal

    traversal = Traversal("Open URL", prompt_intent.lucid_vocabulary(), Mock(return_value="invalid"))
    choices = lucid_traversal.noun_choices(traversal.targets("show"))
    traversal.decisions = {"verb": "show"}
    instruction = lucid_traversal.choice_instruction("lucid-noun", choices, traversal.decisions)
    monkeypatch.setattr(lucid_traversal, "MAX_PROMPT_BYTES", len(instruction.encode("utf-8")))
    infer = traversal.infer
    with pytest.raises(ValueError, match="lucid-help-prompt-bound"):
        traversal.choose("lucid-noun", choices, "fixture")
    assert infer.call_count == 1


@pytest.mark.parametrize("value", ['Case A', 'a"b', 'C:\\Temp\\A', 'é🐧'])
def test_json_literal_selection_preserves_exact_source_value(value):
    encoded = json.dumps(value, ensure_ascii=False)
    infer = Mock(return_value=encoded)
    traversal = Traversal("url: " + encoded, prompt_intent.lucid_vocabulary(), infer)
    traversal.decisions = {"verb": "show", "noun": "url"}
    result = traversal.arguments("show", "url", traversal.targets("show")["url"], {"view": "url"})
    assert result["url"] == value
    record = next(record for record in traversal.records if record["stage"] == "lucid-argument:url")
    assert record["system_prompt"] == infer.call_args.args[1]
    assert record["system_prompt_hash"] == prompt_intent.input_hash(record["system_prompt"])


@pytest.mark.parametrize("response", ['unquoted', "'single quoted'", '[]', '42', 'null', '""', '"invented"', '"first" "second"'])
def test_literal_selection_rejects_non_json_strings_and_unsourced_values(response):
    traversal = Traversal("url missing", prompt_intent.lucid_vocabulary(), Mock(return_value=response))
    traversal.decisions = {"verb": "show", "noun": "url"}
    with pytest.raises(ValueError, match="lucid-argument-needs-clarification:url"):
        traversal.arguments("show", "url", traversal.targets("show")["url"], {"view": "url"})


def test_missing_free_argument_cannot_be_invented():
    infer = Mock(side_effect=["url", "omit", '"https://invented.example/"'])
    traversal = Traversal("Open the URL", prompt_intent.lucid_vocabulary(), infer)
    with pytest.raises(ValueError, match="lucid-argument-needs-clarification:url"):
        traversal.run(ROOT, classified_verb="show")
    assert traversal.records[-1]["validation"] == "refused"


def test_explicit_steps_skip_inference_and_keep_optional_scope():
    infer = Mock(side_effect=AssertionError("no model needed"))
    operation = {"channel": "lucid", "verb": "show", "argv": ["--args", '{"view":"pulse","scope":"this"}']}
    traversal = Traversal("lucid show --args", prompt_intent.lucid_vocabulary(), infer)
    result = traversal.run(ROOT, operation, classified_verb="show")
    assert result["operation"] == operation
    assert result["resolved_arguments"] == {"view": "pulse", "scope": "this"}
    infer.assert_not_called()


def test_missing_noun_help_is_not_replaced_by_an_invented_option_list():
    traversal = Traversal("DISPATCH work", prompt_intent.lucid_vocabulary(), Mock())
    with pytest.raises(ValueError, match="lucid-noun-help-unavailable:dispatch"):
        traversal.run(ROOT, {"channel": "lucid", "verb": "dispatch", "argv": ["work"]}, classified_verb="dispatch")


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
    monkeypatch.setattr(prompt_intent, "classify", Mock(return_value="🖼️"))
    infer = Mock(side_effect=["url", "omit", '"https://example.com/"'])
    monkeypatch.setattr(prompt_intent, "penguin_inference", infer)
    execute = Mock()
    monkeypatch.setattr(prompt_intent, "execute_direct", execute)
    result = prompt_intent.admit_prompt("Open https://example.com/", SUBMISSION, "session", "/workspace", tmp_path)
    execute.assert_not_called()
    diagnostic = result["direct_operation"]["diagnostic"]
    assert diagnostic["receipt"]["refusal"] == "lucid-proposal-needs-confirmation"
    assert diagnostic["lucid_traversal"]["resolved_arguments"] == {"view": "url", "url": "https://example.com/"}
    assert all(call.args[2] != "lucid-verb" for call in infer.call_args_list)
    assert diagnostic["classifier_selection"]["selected_verb"] == "show"
    assert diagnostic["classifier_selection"]["label"] == prompt_intent.lucid_vocabulary()["verbs"]["show"]["glyph"]
    source = result["direct_operation"]["source"]
    assert "document" not in result["direct_operation"]
    assert f'{glyph.DELIMITER_SEGMENT}{glyph.RELATION_ACTION} "lucid ' in source.split("\n\n", 1)[0]
    assert "https://example.com/" in source


@pytest.mark.parametrize("text", ["MORPH effigy", "lucid morph print", "morph a story", "Turn this idea into a comic"])
def test_selected_morph_routes_to_semantic_without_traversal(tmp_path, monkeypatch, text):
    monkeypatch.setattr(prompt_intent, "classify", Mock(return_value="🧬"))
    semantic = Mock(return_value=gestalt("SEMANTIC", "Evaluate the requested morph."))
    lucid = Mock()
    execute = Mock()
    monkeypatch.setattr(prompt_intent, "format_semantic", semantic)
    monkeypatch.setattr(prompt_intent, "format_lucid", lucid)
    monkeypatch.setattr(prompt_intent, "execute_direct", execute)
    result = prompt_intent.admit_prompt(text, SUBMISSION, "session", "/workspace", tmp_path)
    semantic.assert_called_once_with(text)
    assert result["prepared_text"] == text
    diagnostic = result["preparation"]["diagnostic"]
    assert diagnostic["classifier_selection"] == {
        "label": "🧬", "channel": "lucid", "effective_channel": "semantic", "selected_verb": "morph",
    }
    assert diagnostic["lucid_traversal"] is None
    lucid.assert_not_called()
    execute.assert_not_called()


def test_role_assumption_instruction_reaches_agent_unchanged_not_witness_execution(tmp_path, monkeypatch):
    text = "Sign in as EM"
    response = gestalt("SEMANTIC", "Establish your agent session as EM.")
    monkeypatch.setattr(prompt_intent, "classify", Mock(return_value="🧠"))
    formatter = Mock(return_value=response)
    execute = Mock()
    monkeypatch.setattr(prompt_intent, "format_semantic", formatter)
    monkeypatch.setattr(prompt_intent, "execute_direct", execute)
    result = prompt_intent.admit_prompt(text, SUBMISSION, "session", "/workspace", tmp_path)
    assert result["prepared_text"] == text
    assert result["preparation"]["diagnostic"]["classifier_response"] == "🧠"
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