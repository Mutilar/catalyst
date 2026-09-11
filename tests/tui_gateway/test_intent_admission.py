import pytest

from tui_gateway.intent_admission import (
    MAX_INPUT_BYTES,
    SCHEMA,
    catalog_hash,
    evaluate_twitch,
    input_hash,
)


OPERATION = {"channel": "cli", "executable": "git", "argv": ["status"]}


def proposal(text="git status", operation=None):
    return {
        "schema": SCHEMA,
        "input_hash": input_hash(text),
        "catalog_hash": catalog_hash(),
        "classification": "direct",
        "operation": OPERATION if operation is None else operation,
    }


def test_exact_candidate_passes_without_granting_execution():
    result = evaluate_twitch("git status", proposal())
    assert result.operation == OPERATION
    assert result.refusal is None
    assert result.diagnostic()["decision"] == "PASS"
    assert result.diagnostic()["execution_authorized"] is False
    assert result.diagnostic()["context_admission"] == "excluded"


@pytest.mark.parametrize("text", [
    "What does git status mean?", "Run git status, then explain it", "git Status",
])
def test_classifier_cannot_rewrite_input_into_a_direct_command(text):
    result = evaluate_twitch(text, proposal(text))
    assert result.refusal == "intent-not-preserved"
    assert result.operation is None


@pytest.mark.parametrize("field,value", [
    ("schema", "other/1"), ("input_hash", "stale"), ("catalog_hash", "stale"),
    ("classification", "semantic"), ("operation", {"channel": "unknown"}),
])
def test_proposal_bindings_and_route_are_checked(field, value):
    candidate = {**proposal(), field: value}
    result = evaluate_twitch("git status", candidate)
    assert result.refusal is not None
    assert result.operation is None
    assert result.offender == f"proposal.{field}"


@pytest.mark.parametrize("text,operation", [
    ("git diff --stat", {"channel": "cli", "executable": "git", "argv": ["diff", "--stat"]}),
    ("git log -3", {"channel": "cli", "executable": "git", "argv": ["log", "-3"]}),
    ("rg --fixed-strings 'two words' src", {"channel": "cli", "executable": "rg", "argv": ["--fixed-strings", "two words", "src"]}),
    ("custom-tool '' --Mode=Exact", {"channel": "cli", "executable": "custom-tool", "argv": ["", "--Mode=Exact"]}),
    ("./local-tool input", {"channel": "cli", "executable": "./local-tool", "argv": ["input"]}),
    ("python -c 'print(123)'", {"channel": "cli", "executable": "python", "argv": ["-c", "print(123)"]}),
    (" git  status ", OPERATION),
    ("lucid get role", {"channel": "lucid", "verb": "get", "argv": ["role"]}),
    ("lucid show --args '{\"view\":\"pulse\"}'", {"channel": "lucid", "verb": "show", "argv": ["--args", '{"view":"pulse"}']}),
    ("lucid set --args '{\"path\":\"theme\"}'", {"channel": "lucid", "verb": "set", "argv": ["--args", '{"path":"theme"}']}),
    ("./lucid get role", {"channel": "cli", "executable": "./lucid", "argv": ["get", "role"]}),
])
def test_generic_invocations_need_no_command_registration(text, operation):
    result = evaluate_twitch(text, proposal(text, operation))
    assert result.refusal is None
    assert result.operation == operation


@pytest.mark.parametrize("text", ["git status; pwd", "git status\nwhoami", "cat file | sort", "echo $(whoami)", "echo $HOME"])
def test_shell_syntax_is_not_silently_lowered_to_literal_argv(text):
    assert evaluate_twitch(text, proposal(text)).refusal is not None


@pytest.mark.parametrize("candidate", [None, {}, {"confidence": 1.0}])
def test_missing_or_model_confidence_only_proposals_refuse(candidate):
    assert evaluate_twitch("git status", candidate).refusal == "proposal-schema"


def test_bounds_and_invalid_tokenization_refuse():
    assert evaluate_twitch("x" * (MAX_INPUT_BYTES + 1), {}).refusal == "input-out-of-bounds"
    assert evaluate_twitch("tool\0name", {}).refusal == "input-out-of-bounds"
    assert evaluate_twitch("tool 'unterminated", {}).refusal is not None
    assert evaluate_twitch("tool " + "arg " * 129, {}).refusal == "invocation-out-of-bounds"


def test_evaluation_does_not_mutate_proposal():
    candidate = proposal()
    original = dict(candidate)
    evaluate_twitch("git status", candidate)
    assert candidate == original