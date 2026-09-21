"""Prompt preparation and a separate, non-model direct-operation journal."""

from __future__ import annotations

import http.client
import json
import os
import re
import socket
import shlex
import sqlite3
import time
import threading
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from agent.generated.ae_glyphs import SIGNAL_GREEN, SIGNAL_RED, SIGNAL_PENDING, SIGNAL_WARNING, IDENTITY_PENGUIN, DELIMITER_SEGMENT, RELATION_ACTION
from hermes_penguin import (
    PENGUIN_WIRE_MODEL_ID, PENGUIN_TOKEN_BASE, PENGUIN_TOKENS_PER_INPUT_BYTE,
    penguin_max_tokens,
)
from hermes_gestalt import canonical_stream
from tui_gateway.intent_admission import (
    MAX_INPUT_BYTES, SCHEMA, catalog_hash, evaluate_twitch, input_hash,
    invocation_tokens, operation_from_tokens,
)
from tui_gateway.lucid_traversal import Traversal, receipt_walkthroughs, receipt_selection_prompts
from tui_gateway import penguin_funnel

_ENDPOINT = os.environ.pop("AE_WITNESS_DIRECT_ENDPOINT", "")
_TOKEN = os.environ.pop("AE_WITNESS_DIRECT_TOKEN", "")
_MAX_RESPONSE = 524_288
_PENGUIN_TIMEOUT_SECONDS = 30
_CACHE_TTL = 3600
_ACTIVE_LOCK = threading.Lock()
_ACTIVE: dict[str, tuple[str, threading.Event, list]] = {}
_REQUEST = threading.local()
CLASSIFIER_CHANNELS = {"🧠": "semantic", "🤖": "cli"}


def lucid_vocabulary() -> dict:
    path = Path(__file__).resolve().parents[2] / "envelope/LUCID.json"
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 1_048_576:
        raise ValueError("lucid-vocabulary-source-bound")
    vocabulary = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(vocabulary.get("verbs"), dict) or len(vocabulary["verbs"]) != 7:
        raise ValueError("lucid-vocabulary-invalid")
    return vocabulary


def classifier_verbs() -> dict[str, str]:
    verbs = {}
    for verb, definition in lucid_vocabulary()["verbs"].items():
        label = definition.get("glyph")
        if not isinstance(label, str) or not label or label in CLASSIFIER_CHANNELS or label in verbs:
            raise ValueError("classifier-label-collision")
        verbs[label] = verb
    return verbs


def classifier_choices() -> dict[str, str]:
    return {**CLASSIFIER_CHANNELS, **{label: "lucid" for label in classifier_verbs()}}


def classification_instruction() -> str:
    classifier_verbs()
    return penguin_funnel.project("classification")["prompt"]


def decode_classification(text: str, response: str) -> dict:
    choices = classifier_choices()
    if not isinstance(response, str) or response.strip() not in choices:
        raise ValueError("penguin-classifier-glyph-invalid")
    selection = response.strip()
    channel = choices[selection]
    selected_verb = classifier_verbs().get(selection)
    try:
        tokens = shlex.split(text)
    except ValueError:
        tokens = []
    verb = tokens[1] if len(tokens) > 1 and tokens[0].lower() == "lucid" else tokens[0] if tokens else ""
    if selected_verb == "morph" or verb.lower() == "morph":
        return {"classification": "semantic", "classifier_response": response,
            "selected_verb": selected_verb, "routing_reason": "morph-requires-semantic"}
    if channel == "semantic":
        return {"classification": "semantic", "classifier_response": response}
    operation = operation_from_tokens(invocation_tokens(text),
        lucid_verbs=lucid_vocabulary()["verbs"] if channel == "lucid" else ())
    if operation["channel"] != channel:
        if channel == "lucid":
            return {"classification": "lucid", "selected_verb": selected_verb, "classifier_response": response}
        raise ValueError("classifier-invocation-mismatch")
    if channel == "lucid" and operation["verb"] != selected_verb:
        raise ValueError("classifier-verb-mismatch")
    return {"classification": "direct", "operation": operation, "classifier_response": response}


def cancel_intent(submission: str, session: str) -> bool:
    with _ACTIVE_LOCK:
        active = _ACTIVE.get(submission)
        if not active or active[0] != session:
            return False
        active[1].set()
        connections = list(active[2])
    for connection in connections:
        try:
            if isinstance(connection, socket.socket):
                connection.shutdown(socket.SHUT_RDWR)
            connection.close()
        except OSError:
            pass
    return True


def _track(connection) -> None:
    submission = getattr(_REQUEST, "submission", None)
    with _ACTIVE_LOCK:
        active = _ACTIVE.get(submission)
        if active:
            if active[1].is_set():
                connection.close()
                raise ValueError("submission-cancelled")
            active[2].append(connection)


def _check_cancelled() -> None:
    with _ACTIVE_LOCK:
        active = _ACTIVE.get(getattr(_REQUEST, "submission", None))
        if active and active[1].is_set():
            raise ValueError("submission-cancelled")


def _cache_identity() -> str:
    return input_hash(json.dumps({"catalog": catalog_hash(), "model": PENGUIN_WIRE_MODEL_ID,
        "instruction": input_hash(penguin_instruction(Path(__file__).resolve().parents[2])),
        "classifier_instruction": input_hash(classification_instruction()),
        "lucid_traversal": input_hash(Path(__file__).with_name("lucid_traversal.py").read_text()),
        "policy": input_hash(Path(__file__).read_text(encoding="utf-8"))}, sort_keys=True))


def cached_candidate(home: Path, text: str) -> dict | None:
    with _journal(home) as journal:
        row = journal.execute("SELECT identity,expires,candidate FROM route_cache WHERE input_hash=?", (input_hash(text),)).fetchone()
    if not row or row[0] != _cache_identity() or row[1] <= time.time():
        return None
    response = json.loads(row[2])
    if not isinstance(response, str):
        return None
    try:
        candidate = decode_classification(text, response)
    except ValueError:
        return None
    if candidate["classification"] != "direct":
        return None
    bound = {key: value for key, value in candidate.items() if key != "classifier_response"}
    bound.update(schema=SCHEMA, input_hash=input_hash(text), catalog_hash=catalog_hash())
    return candidate if evaluate_twitch(text, bound, lucid_verbs=lucid_vocabulary()["verbs"]
        if candidate["operation"]["channel"] == "lucid" else ()).operation else None


def retain_candidate(home: Path, text: str, candidate: dict) -> None:
    if not isinstance(candidate.get("classifier_response"), str):
        return
    decoded = decode_classification(text, candidate["classifier_response"])
    if decoded != candidate:
        return
    bound = {key: value for key, value in candidate.items() if key != "classifier_response"}
    bound.update(schema=SCHEMA, input_hash=input_hash(text), catalog_hash=catalog_hash())
    if not evaluate_twitch(text, bound, lucid_verbs=lucid_vocabulary()["verbs"]
        if candidate["operation"]["channel"] == "lucid" else ()).operation:
        return
    with _journal(home) as journal:
        journal.execute("DELETE FROM route_cache WHERE identity != ? OR expires <= ?", (_cache_identity(), time.time()))
        if journal.execute("SELECT count(*) FROM route_cache").fetchone()[0] >= 128:
            return
        journal.execute("INSERT OR REPLACE INTO route_cache VALUES (?,?,?,?)",
            (input_hash(text), _cache_identity(), time.time() + _CACHE_TTL, json.dumps(candidate["classifier_response"])))


def penguin_instruction(root: Path) -> str:
    return penguin_funnel.load_projection(root, "semantic-preparation")["prompt"]


def preparation_blocks(response: str) -> tuple[list[str], bool]:
    from markdown import Markdown
    from markdown.treeprocessors import Treeprocessor
    from markdown.util import HTML_PLACEHOLDER_RE

    paragraphs = []
    structured = False

    class CaptureProse(Treeprocessor):
        def run(self, root):
            def visit(element, depth=0):
                nonlocal structured
                if depth > 32:
                    raise ValueError("penguin-document-depth")
                if element.tag in {"table", "pre", "code"}:
                    structured = True
                    return
                if element.tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
                    structured = True
                if element.tag == "p":
                    content = "".join(element.itertext()).strip()
                    if HTML_PLACEHOLDER_RE.fullmatch(content):
                        structured = True
                        return
                    paragraphs.append(content)
                    return
                for child in element:
                    visit(child, depth + 1)
            visit(root)

    markdown = Markdown(extensions=["tables", "fenced_code"], tab_length=4)
    markdown.treeprocessors.register(CaptureProse(markdown), "penguin-prose", 1)
    markdown.convert(response)
    return paragraphs, structured


def decode_preparation(text: str, response: str, root: Path) -> dict:
    if not isinstance(response, str) or not response.strip() or len(response.encode("utf-8")) > _MAX_RESPONSE:
        raise ValueError("penguin-gestalt-bound")
    if len(response.splitlines()) > 512:
        raise ValueError("penguin-gestalt-line-bound")
    paragraphs, structured = preparation_blocks(response)
    if not paragraphs and not structured:
        raise ValueError("penguin-document-empty")
    grammar_path = root / "envelope/GESTALT.json"
    if grammar_path.is_symlink() or grammar_path.stat().st_size > 65_536:
        raise ValueError("gestalt-contract-bound")
    grammar = json.loads(grammar_path.read_text(encoding="utf-8"))["segments"]
    action = grammar["glyphs"]["action"]
    states = tuple(signal + grammar["separator"] for signal in grammar["signals"])
    verbs = lucid_vocabulary()["verbs"]
    for paragraph in paragraphs:
        for line in paragraph.splitlines():
            action_start = line.find(action + " " + grammar["glyphs"]["service"])
            if action_start >= 0:
                from hermes_gestalt import parse_stream
                stream = parse_stream(root, SIGNAL_GREEN + grammar["separator"] + line[action_start:].strip())
                if not stream["actions"] or any(item["verb"].lower() not in verbs for item in stream["actions"]):
                    raise ValueError("penguin-unsupported-lucid-verb")
        if paragraph and all(character == "🐧" for character in paragraph):
            continue
        if paragraph.startswith(action + " "):
            continue
        if paragraph.startswith("$$"):
            continue
        if not paragraph.startswith(states):
            raise ValueError("penguin-unframed-prose")
    return {"classification": "semantic", "gestalt": response}


def classify(text: str) -> str:
    return penguin_inference(text, classification_instruction(), "classification", penguin_max_tokens(text))


def format_semantic(text: str) -> str:
    return penguin_inference(text, penguin_instruction(Path(__file__).resolve().parents[2]), "semantic-preparation", penguin_max_tokens(text))


def format_lucid(text: str, selected_verb: str) -> str:
    vocabulary = lucid_vocabulary()
    tokens = invocation_tokens(text)
    explicit = operation_from_tokens(tokens, lucid_verbs=vocabulary["verbs"])
    if explicit["channel"] != "lucid":
        explicit = None

    def infer(original: str, instruction: str, stage: str, max_tokens: int) -> str:
        _check_cancelled()
        callback = getattr(_REQUEST, "progress", None)
        if callback is not None:
            callback(stage)
        response = penguin_inference(original, instruction, stage, max_tokens)
        _check_cancelled()
        return response

    traversal = Traversal(text, vocabulary, infer)
    try:
        result = traversal.run(Path(__file__).resolve().parents[2], explicit, classified_verb=selected_verb)
        _REQUEST.lucid_traversal = result
        return result.get("gestalt", "")
    except (ValueError, KeyError, TypeError) as error:
        _REQUEST.lucid_traversal = {"steps": traversal.records, "refusal": str(error), "executed": False}
        raise


def penguin_request(text: str, instruction: str, max_tokens: int, *, stage: str,
                    history: list[dict] | None = None) -> dict:
    if max_tokens != penguin_max_tokens(text):
        raise ValueError("penguin-input-budget-mismatch")
    selection = stage in {"classification", "lucid-noun", "lucid-optional", "lucid-noun:retry", "lucid-optional:retry"} or stage.startswith("lucid-argument:")
    if not selection and stage != "semantic-preparation":
        raise ValueError("penguin-request-stage-invalid")
    request = {
        "model": PENGUIN_WIRE_MODEL_ID, "temperature": 0, "max_tokens": max_tokens,
        "tools": [], "tool_choice": "none",
        "chat_template_kwargs": {"enable_thinking": False},
        "messages": [{"role": "system", "content": instruction}, {"role": "user", "content": text}],
    }
    if selection:
        previous = history or []
        if len(previous) >= 64 or len(previous) % 2:
            raise ValueError("penguin-context-turn-bound")
        for index, message in enumerate(previous):
            if (not isinstance(message, dict) or set(message) != {"role", "content"} or not isinstance(message["content"], str)
                or message["role"] != ("user", "assistant")[index % 2]):
                raise ValueError("penguin-context-message-invalid")
            if index % 2 == 0 and message["content"] != text:
                raise ValueError("penguin-context-input-mismatch")
        request["messages"] = [request["messages"][0], *(dict(message) for message in previous), request["messages"][1]]
        if len(json.dumps(request["messages"], ensure_ascii=False).encode("utf-8")) > 262_144:
            raise ValueError("penguin-context-byte-bound")
    elif history:
        raise ValueError("penguin-semantic-context-forbidden")
    return request


def semantic_thinking_comparison(root: Path) -> dict:
    projection = penguin_funnel.load_projection(root, "semantic-preparation")
    corpus = penguin_funnel.strict_json(penguin_funnel.read(root, penguin_funnel.CORPUS))
    cases = {case["id"]: case for case in corpus["cases"]}
    pairs = []
    for index, identity in enumerate(projection["case_ids"]):
        case = cases[identity]
        base = penguin_request(case["input"], projection["prompt"], penguin_max_tokens(case["input"]), stage="semantic-preparation")
        variants = []
        for thinking in (False, True):
            request = {**base, "chat_template_kwargs": {"enable_thinking": thinking}}
            variants.append({"enable_thinking": thinking, "request": request,
                "request_hash": input_hash(json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":"))),
                "response": None, "finish_reason": None, "usage": None, "elapsed_ms": None, "witness": None})
        pairs.append({"case_id": identity, "input": case["input"], "input_hash": input_hash(case["input"]),
            "expected_output": case["semantic"], "expected_is_observed": False,
            "suggested_order": [False, True] if index % 2 == 0 else [True, False], "variants": variants})
    return {"schema": "penguin-thinking-comparison/1", "inference_ran": False,
        "few_shots": penguin_funnel.receipt(projection), "pairs": pairs,
        "live_semantic_policy": "enable_thinking=false",
        "comparison": "Only enable_thinking varies; identical model, messages, temperature, budget and tools",
        "measurements": ["response", "finish_reason", "completion_tokens", "reasoning_tokens when reported",
            "cached_tokens when reported", "elapsed_ms", "witness fidelity: negation, conditions, uncertainty, quotes and literals"],
        "qualification": "Corpus examples are in-prompt checks, not held-out generalization evidence; measure warm/cold cache separately and witness fidelity before changing live semantic policy"}


def generate_prompt_receipt(root: Path) -> Path:
    root = root.resolve()
    sources = [Path(__file__).resolve(), Path(__file__).with_name("penguin_funnel.py"),
        *(root / name for name in penguin_funnel.SOURCES), root / penguin_funnel.ARTIFACT,
        root / "quine/canon/AGENT_INSTRUCTIONS.json",
        root / "catalyst/hermes_penguin.py", root / "catalyst/agent/generated/ae_glyphs.py",
        root / "envelope/LUCID.json", root / "envelope/GESTALT.json", root / ".agents/skills/lucid/SKILL.md",
        Path(__file__).with_name("lucid_traversal.py"),
        root / "butler/src/penguin_host/funnel.rs", root / "butler/tests/unit/penguin_host/funnel.rs",
        root / "catalyst/tests/tui_gateway/test_prompt_intent.py",
        root / "catalyst/apps/desktop/src/components/assistant-ui/direct-operation.tsx",
        root / "catalyst/apps/desktop/src/components/assistant-ui/direct-operation.test.tsx"]

    def source_hashes() -> dict:
        hashes = {}
        for path in sources:
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 524_288:
                raise ValueError("prompt-receipt-source-bound")
            hashes[path.relative_to(root).as_posix()] = input_hash(path.read_text(encoding="utf-8"))
        return hashes

    before = source_hashes()
    instructions = {"classification": classification_instruction(), "semantic-preparation": penguin_instruction(root)}
    walkthroughs = receipt_walkthroughs(root, lucid_vocabulary())
    selection_prompts = receipt_selection_prompts(lucid_vocabulary())
    input_cases = {}
    for record in selection_prompts:
        request = penguin_request(record["input"], record["system_prompt"], penguin_max_tokens(record["input"]), stage=record["stage"])
        record["request"] = request
        record["context_basis"] = "Standalone request with no prior turns; live follow-ups append completed selection attempts from this submission"
        record["request_hash"] = input_hash(json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        identity = record["input_hash"]
        if identity not in input_cases:
            input_cases[identity] = {"original_input": record["input"], "input_hash": identity,
                "inference_ran": False, "stage_requests": {stage:
                    penguin_request(record["input"], instruction, penguin_max_tokens(record["input"]), stage=stage)
                    for stage, instruction in instructions.items()},
                "routing_note": "Same original user message in every request. Semantic and verb traversal are alternative routes, not a rewrite chain."}
    stages = []
    for stage, instruction in instructions.items():
        request = penguin_request("", instruction, penguin_max_tokens(""), stage=stage)
        stages.append({"stage": stage, "system_message": request["messages"][0],
            "request_messages": request["messages"], "stage_prompt": instruction,
            "stage_prompt_hash": input_hash(instruction),
            "few_shots": penguin_funnel.receipt(penguin_funnel.project(stage)),
            "system_prompt_hash": input_hash(request["messages"][0]["content"]),
            "prompt_size": {"utf8_bytes": len(instruction.encode("utf-8")), "characters": len(instruction),
                "token_count": None, "token_count_basis": "No runtime tokenizer invoked"},
            "request_settings": {key: value for key, value in request.items() if key != "messages"},
            "token_budget": {"base_tokens": PENGUIN_TOKEN_BASE,
                "tokens_per_user_input_byte": PENGUIN_TOKENS_PER_INPUT_BYTE,
                "encoding": "utf-8", "user_input_bytes": 0,
                "binding": "Recomputed from the actual inference user message; empty-input settings shown here"},
            "user_message_binding": "The submitted input is supplied verbatim at inference time; no user input was supplied for this generation."})
    thinking_comparison = semantic_thinking_comparison(root)
    selection = next(record for record in selection_prompts if record["stage"] == "lucid-noun")
    initial_request = penguin_request(selection["input"], instructions["classification"],
        penguin_max_tokens(selection["input"]), stage="classification")
    expected_label = next(label for label, verb in classifier_verbs().items() if verb == selection["resolved_before"]["verb"])
    followup_request = penguin_request(selection["input"], selection["system_prompt"],
        penguin_max_tokens(selection["input"]), stage=selection["stage"],
        history=[initial_request["messages"][-1], {"role": "assistant", "content": expected_label}])
    context_example = {"input_case_id": selection["input_case_id"], "inference_ran": False,
        "expected_classifier_reply": expected_label, "expected_is_observed": False,
        "initial_request": initial_request, "followup_request": followup_request,
        "followup_request_hash": input_hash(json.dumps(followup_request, ensure_ascii=False, sort_keys=True, separators=(",", ":")))}
    if source_hashes() != before:
        raise ValueError("prompt-receipt-source-changed")
    payload = {"schema": "penguin-prompt-generation/1", "generator": "tui_gateway.prompt_intent.generate_prompt_receipt",
        "sources": before, "stages": stages, "inference_ran": False,
        "classification_contract": {"choices": classifier_choices(),
            "verb_labels": classifier_verbs(),
            "verb_binding": "Classifier-selected verb is carried into traversal without a second verb inference",
            "semantic_verb_routes": ["morph"],
            "noun_arguments": "Resolved by verb-scoped traversal; inferred operations still require confirmation"},
        "lucid_traversal": walkthroughs,
        "selection_prompts": selection_prompts,
        "selection_input_cases": list(input_cases.values()),
        "semantic_thinking_comparison": thinking_comparison,
        "selection_context_example": context_example,
        "audit": {
            "selection_context": {"policy": "submission-local-selection",
                "instruction_binding": "Exact authored stage prompt as system message; unchanged original input as user message; no wrapper instruction",
                "lifetime": "Created per admission and cleared in finally; no cross-submission conversation history",
                "history": "Completed selection attempts only, including invalid selections before retry; no reasoning or tool outputs",
                "semantic": "Isolated, unchanged messages; enable_thinking=false",
                "bounds": {"requests": 32, "serialized_message_utf8_bytes": 262144, "overflow": "refuse; never silently truncate"},
                "cache": "Stage system prompts change; conversational context retained, full-prefix KV reuse not guaranteed"},
            "thinking_policy": {"classification_and_selection": "enable_thinking=false",
                "semantic_preparation": "enable_thinking=false", "semantic_comparison": "prepared only; no inference",
                "adapter": "Catalyst MLX chat_template_kwargs; not a portable OpenAI or Ollama setting"},
            "generation": "Executed actual prompt assembly and pinned traversal projection; no model or command execution",
            "token_budget": {"formula": "max_tokens = base_tokens + tokens_per_user_input_byte * UTF8(inference_user_message).bytes",
                "base_tokens": PENGUIN_TOKEN_BASE, "tokens_per_user_input_byte": PENGUIN_TOKENS_PER_INPUT_BYTE,
                "scope": "classification, semantic preparation and LUCID traversal inference",
                "system_prompt_bytes_included": False,
                "generation_settings": "Top-level prompts use empty input; selection prompt examples bind their declared illustrative input; actual requests recompute the budget"},
            "design_obligations": ["Original input is supplied to every inference", "Current-stage choices are scoped; history retains earlier user inputs and selection replies, not earlier system prompts",
                "Host request supplies tools=[] and tool_choice=none; no tool catalog or cross-submission conversation history is injected",
                "Host rejects tool/function-call outputs; preprocessing has no model tool-dispatch loop",
                "Preparation preserves speech acts and does not answer the user or invent continuations",
                "State glyphs describe the input; non-green restatements are not preparation failures",
                "Few-shots cover CLI/LUCID contrasts, evidence, timing, all states and conditional/alternative CYOA",
                "Semantic rewrites remain display-only proposals; original input is forwarded unchanged",
                "Active LUCID continuations must use canonical syntax and registered verbs",
                "Explicit choices skip inference", "MORPH returns to semantic evaluation",
                "Classification selects CLI, semantic or a declared verb; traversal never reselects the verb",
                "Noun, optional-field, enum and literal prompts use bold headers, segmented rows and scoped delimited few-shots",
                "Butler owns one canonical corpus and filtering projector; both hosts consume the same context-keyed artifact",
                "Corpus expectations are not inference observations; uncovered contexts refuse without unrelated fallback examples",
                "Each selection attempt retains its exact prompt/hash and input-sized budget; retry feedback is bounded",
                "Literal selection returns one JSON string sourced from the input; uncertainty refuses without guessing",
                "Inferred requests require confirmation; no execution from a model selection alone"],
            "bounds": {"steps": 16, "selection_attempts": 2, "choices": 128, "prompt_bytes": 16384},
            "observations": [{"input": example["input"], "recorded_steps": len(example["result"]["steps"]),
                "inference_calls": sum(len(step.get("attempts", [])) for step in example["result"]["steps"] if step.get("selection_source") == "penguin"),
                "semantic_required": example["result"].get("semantic_required", False),
                "projected_action": example["result"].get("gestalt")} for example in walkthroughs],
            "qualification": "Tests, compilation, and live model/UI checks not run; QUINE-owned",
            "open_contracts": ["DISPATCH/STEER/CANCEL noun-specific adapters", "Complex object argument preparation",
                "Runtime model selection accuracy"]},
        "generation_only": True}
    digest = input_hash(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    directory = root / "run/state/runtime/penguin-prompts"
    directory.mkdir(parents=True, exist_ok=True)
    stem = digest.removeprefix("sha256:")
    readable = "# Generated PENGUIN Prompts\n\nGeneration only; not an inference or delivery attestation.\n\n"
    readable += "## Selection Context Example\n\nExpected classifier reply, not an inference observation.\n\n"
    readable += "```json\n" + json.dumps(context_example, ensure_ascii=False, indent=2) + "\n```\n\n"
    readable += "\n\n".join("## " + stage + "\n\n" + instruction for stage, instruction in instructions.items())
    readable += "\n\n## Selection Prompts\n\nGeneration-only standalone requests with no prior turns. Live selection requests retain completed user/reply turns from the same submission beneath the current stage's exact authored system prompt. The original input remains the latest user message, without wrapper prose. Semantic preparation remains isolated.\n"
    for record in selection_prompts:
        readable += "\n### " + record["stage"] + " / " + record["resolved_before"]["verb"] + "\n\n"
        readable += "**USER MESSAGE (UNCHANGED)**\n" + json.dumps(record["input"], ensure_ascii=False) + "\n\n"
        readable += record["system_prompt"] + "\n\n"
        readable += "Input hash: " + record["input_hash"] + "\n\n"
        readable += "System prompt hash: " + record["system_prompt_hash"] + "\n"
    readable += "\n\n## LUCID Traversal Receipt\n\nGeneration-only walkthroughs; no inference or execution.\n"
    for walkthrough in walkthroughs:
        readable += "\n### " + walkthrough["input"] + "\n\n"
        for step in walkthrough["result"]["steps"]:
            readable += "#### " + step["stage"] + "\n\n"
            readable += step.get("system_prompt", "Decision bound without additional inference.") + "\n\n"
            readable += "Selection: `" + str(step.get("selected", "")) + "`\n\n"
        readable += walkthrough["result"].get("gestalt", "Semantic evaluation required.") + "\n"
    readable += "\n## Classification Contract\n\n" + json.dumps(payload["classification_contract"], ensure_ascii=False, indent=2) + "\n"
    readable += "\n## Semantic Thinking Comparison\n\nGeneration only; neither variant has been run. Exact paired requests are in the JSON receipt.\n\n"
    readable += "**CASE** · **THINKING OFF REQUEST HASH** · **THINKING ON REQUEST HASH**\n"
    for pair in thinking_comparison["pairs"]:
        readable += pair["case_id"] + " · " + " · ".join(variant["request_hash"] for variant in pair["variants"]) + "\n"
    readable += "\n## Audit\n\n" + json.dumps(payload["audit"], indent=2) + "\n"
    readable += "\n"
    envelope = {"intent": {"verb": "get", "args": {"path": "penguin-prompts", "result": payload}},
        "capability": None, "escalation": None,
        "fidelity": {"surface": "prompt-generation", "level": "lossless",
            "preserved": ["exact system messages", "request settings", "source hashes"], "lost": []},
        "refusal": None, "receipt": {"id": digest, "ts": datetime.now(timezone.utc).isoformat(),
            "trust": "untrusted", "content_hash": digest, "ran": True,
            "effect": "Generated prompt receipt and readable projection; no model invoked."}}
    for suffix, content in ((".md", readable), (".json", json.dumps(envelope, ensure_ascii=False, indent=2) + "\n")):
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory, delete=False) as output:
            temporary = Path(output.name)
            try:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            except BaseException:
                temporary.unlink(missing_ok=True)
                raise
        try:
            os.replace(temporary, directory / (stem + suffix))
        finally:
            temporary.unlink(missing_ok=True)
    return directory / (stem + ".json")


def penguin_inference(text: str, instruction: str, stage: str, max_tokens: int) -> str:
    from hermes_penguin import PENGUIN_BASE_URL
    from urllib.parse import urlsplit

    endpoint = urlsplit(PENGUIN_BASE_URL)
    if endpoint.hostname != "127.0.0.1" or endpoint.scheme != "http":
        raise ValueError("penguin-endpoint-not-local")
    stages = getattr(_REQUEST, "stages", None)
    context = getattr(_REQUEST, "selection_context", None) if stage != "semantic-preparation" else None
    if context is not None and context["input"] != text:
        raise ValueError("penguin-context-input-mismatch")
    request = penguin_request(text, instruction, max_tokens, stage=stage,
        history=context["messages"] if context is not None else None)
    record = {"stage": stage, "system_prompt_hash": input_hash(instruction),
        "system_prompt_message_index": 0,
        "max_tokens": max_tokens, "input": text, "response": None,
        "request_messages": request["messages"],
        "context": {"policy": "submission-local-selection" if stage != "semantic-preparation" else "isolated-semantic",
            "prior_turns": len(context["messages"]) // 2 if context is not None else 0,
            "stage_instruction_binding": "system message"},
        "token_budget": {"base_tokens": PENGUIN_TOKEN_BASE,
            "tokens_per_user_input_byte": PENGUIN_TOKENS_PER_INPUT_BYTE,
            "encoding": "utf-8", "user_input_bytes": len(text.encode("utf-8"))},
        "request_settings": {key: value for key, value in request.items() if key != "messages"},
        "request_hash": input_hash(json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":")))}
    if stages is not None:
        stages.append(record)
    if stage in {"classification", "semantic-preparation"}:
        projection = penguin_funnel.project(stage)
        if instruction != projection["prompt"]:
            raise ValueError("funnel-request-prompt-drift")
        record["few_shots"] = penguin_funnel.receipt(projection)
    started = time.monotonic()
    body = json.dumps(request).encode()
    transport = {"timeout_ms": _PENGUIN_TIMEOUT_SECONDS * 1000, "phase": "request",
        "http_status": None, "inference_state": "unknown", "error": None}
    record["transport"] = transport
    connection = http.client.HTTPConnection(endpoint.hostname, endpoint.port, timeout=_PENGUIN_TIMEOUT_SECONDS)
    try:
        _track(connection)
        connection.request("POST", "/v1/chat/completions", body, {"Content-Type": "application/json"})
        transport["phase"] = "response-headers"
        response = connection.getresponse()
        transport["http_status"] = response.status
        transport["phase"] = "response-body"
        raw = response.read(_MAX_RESPONSE + 1)
        transport["phase"] = "complete"
        transport["inference_state"] = "response-received"
        if response.status != 200 or len(raw) > _MAX_RESPONSE:
            raise ValueError("penguin-response-unavailable")
        result = json.loads(raw)
        choice = result["choices"][0]
        message = choice.get("message")
        if not isinstance(message, dict):
            raise ValueError("penguin-response-message-invalid")
        record["response"] = message.get("content")
        record["finish_reason"] = choice.get("finish_reason")
        tool_calls = message.get("tool_calls")
        record["tool_calls_present"] = tool_calls not in (None, [])
        record["function_call_present"] = message.get("function_call") is not None
        if (record["tool_calls_present"] or record["function_call_present"]
            or choice.get("finish_reason") in {"tool_calls", "function_call"}):
            record["refusal"] = "penguin-tool-output-forbidden"
            raise ValueError("penguin-tool-output-forbidden")
        usage = result.get("usage")
        if isinstance(usage, dict):
            record["usage"] = {key: usage[key] for key in ("prompt_tokens", "completion_tokens", "total_tokens")
                if type(usage.get(key)) is int and usage[key] >= 0}
            for field, key in (("prompt_tokens_details", "cached_tokens"), ("completion_tokens_details", "reasoning_tokens")):
                details = usage.get(field)
                if isinstance(details, dict) and type(details.get(key)) is int and details[key] >= 0:
                    record["usage"][field] = {key: details[key]}
        reasoning = message.get("reasoning_content")
        if isinstance(reasoning, str):
            record["reasoning_chars"] = len(reasoning)
        if choice.get("finish_reason") != "stop":
            raise ValueError("penguin-response-incomplete")
        response_text = choice["message"]["content"]
        if not isinstance(response_text, str):
            raise ValueError("penguin-gestalt-string-required")
        if context is not None:
            context["messages"].extend([dict(request["messages"][-1]),
                {"role": "assistant", "content": response_text}])
        return response_text
    except TimeoutError as error:
        transport["error"] = type(error).__name__
        _check_cancelled()
        record["refusal"] = "penguin-inference-timeout"
        raise ValueError("penguin-inference-timeout") from error
    finally:
        record["elapsed_ms"] = round((time.monotonic() - started) * 1000)
        connection.close()


def prepare_semantic(text: str, candidate: dict, root: Path) -> str:
    if set(candidate) != {"classification", "gestalt"}:
        raise ValueError("semantic-schema")
    if decode_preparation(text, candidate["gestalt"], root)["classification"] != "semantic":
        raise ValueError("semantic-channel-mismatch")
    return text


def presentation_source(signal: str, evidence: str, *, data: tuple[str, ...] = (), timing: tuple[str, ...] = (),
    blocks: tuple[tuple[str, str], ...] = (), continuations: tuple[str, ...] = ()) -> str:
    root = Path(__file__).resolve().parents[2]
    source = canonical_stream(root, signal, service=IDENTITY_PENGUIN,
        evidence=(evidence,), data=data, timing=timing)
    source += "".join(DELIMITER_SEGMENT + RELATION_ACTION + " " + json.dumps(label) for label in continuations)
    for label, value in blocks:
        if value:
            source += "\n\n" + canonical_stream(root, signal, service=IDENTITY_PENGUIN, evidence=(label,))
            fence = "`" * max(3, 1 + max((len(run) for run in re.findall(r"`+", value)), default=0))
            source += "\n\n" + fence + "text\n" + value + "\n" + fence
    return source


def preparation_document(submission: str, text: str, phase: str, *, transformed: str = "",
    proposal: dict | None = None, source: str | None = None, elapsed_ms: int = 0) -> dict:
    pending = phase not in {"prepared", "refused"}
    signal = SIGNAL_PENDING if pending else SIGNAL_RED if phase == "refused" else SIGNAL_GREEN
    return {
        "source": presentation_source(signal, phase.upper(),
            blocks=(("INPUT", text), ("PREPARED INPUT", transformed))),
        "diagnostic": {"schema": "catalyst-intent-preparation/1", "submission_id": submission,
            "phase": phase, "pending": pending, "original_input": text, "input_hash": input_hash(text),
            "transformed_input": transformed, "proposal": proposal, "interpretation_source": source,
            "origin": {"author": "user", "processor": "PENGUIN", "kind": "intent-preparation"},
            "elapsed_ms": elapsed_ms, "authority": "none", "context_admission": "excluded"},
    }


def execute_direct(submission: str, workspace: str, operation: dict) -> dict:
    if not _ENDPOINT or not _TOKEN:
        return {"operation": operation, "refusal": "witness-handoff-unavailable", "ran": False}
    host, separator, port = _ENDPOINT.rpartition(":")
    if host != "127.0.0.1" or not separator or not port.isdecimal():
        return {"operation": operation, "refusal": "witness-handoff-invalid", "ran": False}
    request = {"schema": "run-witness-direct/2", "submission_id": submission,
        "operation": operation, "workspace": workspace, "token": _TOKEN}
    with socket.create_connection((host, int(port)), timeout=35) as stream:
        _track(stream)
        stream.sendall(json.dumps(request).encode() + b"\n")
        with stream.makefile("rb") as reader:
            raw = reader.readline(_MAX_RESPONSE + 1)
    if len(raw) > _MAX_RESPONSE or not raw.endswith(b"\n"):
        raise ValueError("executor-response-bound")
    receipt = json.loads(raw)
    if not isinstance(receipt, dict) or receipt.get("schema") != "run-witness-direct/2":
        raise ValueError("executor-receipt-invalid")
    if receipt.get("ran") and (receipt.get("submission_id") != submission
        or receipt.get("workspace") != workspace or receipt.get("operation") != operation):
        raise ValueError("executor-receipt-binding")
    if "operation" in receipt and receipt["operation"] != operation:
        raise ValueError("executor-receipt-binding")
    receipt.setdefault("operation", operation)
    return receipt


def operation_document(submission: str, text: str, receipt: dict, proposal: dict | None = None) -> dict:
    success = receipt.get("ran") is True and receipt.get("exit_code") == 0 and not receipt.get("refusal")
    diagnostic = {"schema": "catalyst-direct-operation/1", "submission_id": submission,
        "original_input": text, "input_hash": input_hash(text), "actor": "WITNESS",
        "context_admission": "excluded", "proposal": proposal, "receipt": receipt}
    intent = {"verb": "dispatch", "args": {"path": "witness-direct", "submission_id": submission,
        "operation": receipt.get("operation"), "result": receipt}}
    lost = [key for key in ("stdout_truncated", "stderr_truncated") if receipt.get(key)]
    refusal = receipt.get("refusal")
    refusal_code = {
        "witness-handoff-unavailable": "no-capability", "grant-missing": "no-capability",
        "grant-revoked": "no-capability", "grant-mismatch": "bad-signature",
        "workspace-not-granted": "scope-violation", "operation-not-granted": "scope-violation",
        "intent-not-preserved": "fidelity-floor", "semantic-source-not-preserved": "fidelity-floor",
    }.get(refusal, "internal-error")
    diagnostic["envelope"] = {
        "intent": intent,
        "capability": None, "escalation": None,
        "fidelity": {"surface": "inline-ugui", "level": "lossy" if lost else "lossless",
            "preserved": ["operation identity", "bounded executor receipt", "domain refusal"], "lost": lost},
        "refusal": {"code": refusal_code, "reason": refusal} if refusal else None,
        "receipt": {"id": submission, "ts": datetime.now(timezone.utc).isoformat(),
            "ran": receipt.get("ran") is True, "trust": "untrusted",
            "content_hash": input_hash(json.dumps(intent, sort_keys=True, separators=(",", ":"))),
            "effect": "Observed direct operation result" if receipt.get("ran") is True else
                "No direct execution confirmed; consult the domain execution state"},
    }
    body = receipt.get("stdout", "")
    stderr = receipt.get("stderr", "")
    unknown = receipt.get("execution_state") == "unknown" or receipt.get("ran") is None
    state = "UNKNOWN" if unknown else "COMPLETED" if success else "FAILED" if receipt.get("ran") is True else "REFUSED"
    signal = SIGNAL_WARNING if unknown or (success and lost) else SIGNAL_GREEN if success else SIGNAL_RED
    rows = [{"label": "Execution", "value": "Unknown" if unknown else "Ran" if receipt.get("ran") is True else "Not started"}]
    if receipt.get("exit_code") is not None:
        rows.append({"label": "Exit code", "value": str(receipt["exit_code"])})
    if refusal:
        rows.append({"label": "Refusal", "value": str(refusal)})
    for field in lost:
        rows.append({"label": "Output limit", "value": field})
    document = {"schema": "lucid-ugui-response/1", "type": "document",
        "id": "direct-" + input_hash(submission).removeprefix("sha256:"), "state": signal,
        "header": [{"type": "text", "body": presentation_source(signal, state)}],
        "sections": [{"type": "key_value", "heading": "Execution", "rows": rows}], "actions": []}
    for label, value in (("INPUT", text), ("OUTPUT", body), ("DIAGNOSTICS", stderr)):
        if value:
            document["sections"].append({"type": "code", "heading": label, "language": "text", "value": value})
    if success and not body and not stderr:
        document["sections"].append({"type": "text", "body": "Command completed without output."})
    if receipt.get("ugui_source"):
        try:
            projected = json.loads(receipt["ugui_source"])
            if not isinstance(projected, dict) or projected.get("schema") != "lucid-ugui-response/1":
                raise ValueError("butler-projection-invalid")
            return {"document": projected, "diagnostic": diagnostic}
        except (ValueError, TypeError):
            diagnostic["projection_error"] = "butler-projection-invalid"
            document["state"] = SIGNAL_RED
            document["header"] = [{"type": "text", "body": presentation_source(SIGNAL_RED, "PROJECTION FAILED")}]
            rows.append({"label": "Projection", "value": "butler-projection-invalid"})
    return {"document": document, "diagnostic": diagnostic}


def project_penguin_failure(evidence: dict) -> None:
    diagnostic = evidence["diagnostic"]
    receipt = diagnostic["receipt"]
    if not receipt.get("refusal") or receipt.get("phase") not in {
        "classification", "semantic-preparation", "lucid-preparation"
    } or receipt.get("execution_state") != "not-started":
        return
    diagnostic["recovery"] = {"submission_id": diagnostic["submission_id"]}
    evidence.pop("document", None)
    stages = diagnostic.get("stages", [])
    stage = stages[-1] if stages else {}
    if receipt["refusal"] == "penguin-inference-timeout":
        transport = stage.get("transport", {})
        facts = [receipt["phase"].replace("-", " ").upper()]
        timeout_ms = transport.get("timeout_ms")
        if type(timeout_ms) is int and timeout_ms > 0:
            facts.append(f"{timeout_ms / 1000:g}s transport timeout")
        if transport.get("phase"):
            facts.append("HTTP " + transport["phase"].replace("-", " ").upper())
        facts.extend(("No complete response received", "Provider completion unknown", "Execution not started"))
        elapsed = stage.get("elapsed_ms")
        timing = (f"Elapsed {elapsed / 1000:.1f}s",) if type(elapsed) is int and elapsed >= 0 else ()
        evidence["source"] = presentation_source(SIGNAL_RED, "PENGUIN INFERENCE TIMEOUT", data=tuple(facts), timing=timing,
            blocks=(("INPUT", diagnostic["original_input"]),), continuations=("Retry", "Bypass", "Help"))
        return
    if receipt["refusal"] == "penguin-response-incomplete" and stage.get("finish_reason") == "length":
        facts = [receipt["phase"].replace("-", " ").upper()]
        usage = stage.get("usage", {})
        completed, maximum = usage.get("completion_tokens"), stage.get("max_tokens")
        if type(maximum) is int and maximum > 0:
            facts.append(f"{completed}/{maximum} completion tokens" if type(completed) is int and completed >= 0
                else f"{maximum}-token response limit")
        facts.append("Incomplete response withheld" if isinstance(stage.get("response"), str) and stage["response"]
            else "No response text returned")
        thinking = stage.get("request_settings", {}).get("chat_template_kwargs", {}).get("enable_thinking")
        facts.append("Thinking disabled requested" if thinking is False else "Thinking enabled requested" if thinking is True
            else "Thinking mode unspecified")
        reasoning_tokens = usage.get("completion_tokens_details", {}).get("reasoning_tokens")
        if type(reasoning_tokens) is int and reasoning_tokens > 0:
            facts.append(f"{reasoning_tokens} reasoning tokens reported")
        elif type(stage.get("reasoning_chars")) is int and stage["reasoning_chars"] > 0:
            facts.append(f"{stage['reasoning_chars']} reasoning characters reported")
        facts.append("Execution not started")
        elapsed = stage.get("elapsed_ms")
        timing = (f"Elapsed {elapsed / 1000:.1f}s",) if type(elapsed) is int and elapsed >= 0 else ()
        evidence["source"] = presentation_source(SIGNAL_RED, "RESPONSE TOKEN LIMIT", data=tuple(facts), timing=timing,
            blocks=(("INPUT", diagnostic["original_input"]),), continuations=("Retry", "Bypass", "Help"))
        return
    rows = [{"key": "Refusal", "value": receipt["refusal"]},
        {"key": "Phase", "value": receipt["phase"]},
        {"key": "Execution", "value": "Not started"},
        {"key": "Submission", "value": diagnostic["submission_id"]}]
    for stage in diagnostic.get("stages", [])[-1:]:
        for field in ("stage", "finish_reason", "max_tokens", "elapsed_ms", "reasoning_chars"):
            if stage.get(field) is not None:
                rows.append({"key": field.replace("_", " ").title(), "value": str(stage[field])})
        for field, value in stage.get("usage", {}).items():
            rows.append({"key": field.replace("_", " ").title(), "value": str(value)})
    evidence["source"] = presentation_source(SIGNAL_RED, "INTENT ADMISSION REFUSED",
        data=tuple(row["key"].upper() + " " + json.dumps(row["value"]) for row in rows),
        blocks=(("INPUT", diagnostic["original_input"]),), continuations=("Retry", "Bypass", "Help"))


@contextmanager
def _journal(home: Path):
    path = home / "direct-operations.sqlite"
    if path.is_symlink():
        raise ValueError("operation-journal-symlink")
    connection = sqlite3.connect(path, timeout=2)
    os.chmod(path, 0o600)
    connection.execute("CREATE TABLE IF NOT EXISTS operations (id TEXT PRIMARY KEY, session TEXT NOT NULL, input_hash TEXT NOT NULL, workspace TEXT NOT NULL, created REAL NOT NULL, result TEXT)")
    connection.execute("CREATE TABLE IF NOT EXISTS route_cache (input_hash TEXT PRIMARY KEY, identity TEXT NOT NULL, expires REAL NOT NULL, candidate TEXT NOT NULL)")
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def has_canonical_signal_prefix(text: object) -> bool:
    return isinstance(text, str) and text.startswith((SIGNAL_GREEN, SIGNAL_PENDING, SIGNAL_WARNING, SIGNAL_RED))


def recover_prompt(recovery: dict, submission: str, session: str, workspace: str, home: Path, on_preparation=None) -> dict:
    if not isinstance(recovery, dict) or set(recovery) != {"submission_id", "action"}:
        raise ValueError("penguin-recovery-invalid")
    previous_id, action = recovery["submission_id"], recovery["action"]
    if not isinstance(previous_id, str) or previous_id == submission or action not in ("retry", "bypass", "help"):
        raise ValueError("penguin-recovery-invalid")
    with _journal(home) as journal:
        previous = journal.execute("SELECT session,workspace,result FROM operations WHERE id=?", (previous_id,)).fetchone()
    if not previous or previous[:2] != (session, workspace) or not previous[2]:
        raise ValueError("penguin-recovery-not-found")
    diagnostic = json.loads(previous[2]).get("direct_operation", {}).get("diagnostic", {})
    receipt = diagnostic.get("receipt", {})
    if not receipt.get("refusal") or receipt.get("execution_state") != "not-started" or receipt.get("phase") not in {
        "classification", "semantic-preparation", "lucid-preparation"
    }:
        raise ValueError("penguin-recovery-not-eligible")
    original = diagnostic.get("original_input")
    if not isinstance(original, str) or not original or len(original.encode()) > MAX_INPUT_BYTES:
        raise ValueError("penguin-recovery-input-invalid")
    if action == "retry":
        return admit_prompt(original, submission, session, workspace, home, on_preparation=on_preparation)
    if action == "help":
        operation = {"channel": "lucid", "verb": "--help", "argv": []}
        return {"direct_operation": operation_document(submission, "lucid --help --modality ugui",
            execute_direct(submission, workspace, operation))}
    return {"prepared_text": original, "admission": {
        "source": "witness-penguin-bypass", "failed_submission_id": previous_id,
        "input_hash": input_hash(original), "penguin_bypassed": True, "inference_ran": False, "stages": [],
    }}


def admit_prompt(text: str, submission: str, session: str, workspace: str, home: Path, *, on_preparation=None, recovery=None) -> dict:
    started = time.monotonic()
    if recovery is not None:
        return recover_prompt(recovery, submission, session, workspace, home, on_preparation)
    if not text or len(text.encode()) > MAX_INPUT_BYTES:
        return {"direct_operation": operation_document(submission, "", {"refusal": "input-bound", "ran": False})}
    if has_canonical_signal_prefix(text):
        return {"prepared_text": text, "admission": {
            "source": "canonical-signal-prefix", "input_hash": input_hash(text),
            "penguin_bypassed": True, "inference_ran": False, "stages": [],
        }}
    from hermes_cli.input_sanitize import sanitize_user_prompt_text

    original_input = text
    text = sanitize_user_prompt_text(text)
    with _journal(home) as journal:
        journal.execute("BEGIN IMMEDIATE")
        previous = journal.execute("SELECT session,input_hash,workspace,result FROM operations WHERE id=?", (submission,)).fetchone()
        if previous:
            if previous[:3] != (session, input_hash(text), workspace):
                raise ValueError("submission-identity-conflict")
            retained = json.loads(previous[3]) if previous[3] else None
            if retained and "direct_operation" in retained:
                return retained
            return {"direct_operation": operation_document(
                submission, text, {"refusal": "submission-unresolved", "ran": False})}
        count = journal.execute("SELECT count(*) FROM operations").fetchone()[0]
        if count >= 10_000:
            return {"direct_operation": operation_document(submission, text, {"refusal": "operation-journal-bound", "ran": False})}
        journal.execute("INSERT INTO operations VALUES (?,?,?,?,?,NULL)", (submission, session, input_hash(text), workspace, time.time()))
    candidate = None
    result = None
    response_text = None
    phase = "classification"
    candidate_source = None
    prepared = None
    _REQUEST.stages = []
    _REQUEST.lucid_traversal = None
    _REQUEST.selection_context = {"input": text, "messages": []}
    classifier_response = None
    classification = None

    def publish(phase: str, transformed: str = "") -> dict:
        document = preparation_document(submission, text, phase, transformed=transformed,
            proposal=candidate, source=candidate_source, elapsed_ms=round((time.monotonic() - started) * 1000))
        document["diagnostic"]["penguin_response"] = response_text
        document["diagnostic"]["classifier_response"] = classifier_response
        document["diagnostic"]["stages"] = [dict(stage) for stage in _REQUEST.stages]
        document["diagnostic"]["lucid_traversal"] = getattr(_REQUEST, "lucid_traversal", None)
        if on_preparation is not None:
            on_preparation(document)
        return document

    with _ACTIVE_LOCK:
        _ACTIVE[submission] = (session, threading.Event(), [])
    _REQUEST.submission = submission
    _REQUEST.progress = publish
    try:
        publish("classification")
        candidate = cached_candidate(home, text)
        candidate_source = "qualified_cache" if candidate else "penguin"
        if candidate is None:
            classifier_response = classify(text)
            response_text = classifier_response
            candidate = decode_classification(text, classifier_response)
        else:
            classifier_response = candidate["classifier_response"]
            response_text = classifier_response
            _REQUEST.stages.append({"stage": "classification", "source": "qualified_cache",
                "input": text, "response": classifier_response, "elapsed_ms": 0})
        _check_cancelled()
        classification = candidate.get("classification")
        lucid_result = None
        if classification == "lucid" or (classification == "direct" and candidate["operation"]["channel"] == "lucid"):
            phase = "lucid-preparation"
            response_text = None
            publish(phase)
            response_text = format_lucid(text, candidate.get("selected_verb") or candidate["operation"]["verb"])
            lucid_result = getattr(_REQUEST, "lucid_traversal", None)
            _check_cancelled()
            if lucid_result is None:
                raise ValueError("lucid-traversal-receipt-missing")
            if lucid_result.get("semantic_required"):
                classification = "semantic"
            elif classification == "lucid":
                result = {"direct_operation": operation_document(submission, text,
                    {"ran": False, "refusal": "lucid-proposal-needs-confirmation", "ugui_source": None},
                    {"classification": "lucid", "gestalt": response_text})}
                invocation = shlex.join(["lucid", lucid_result["operation"]["verb"], *lucid_result["operation"]["argv"]])
                result["direct_operation"].pop("document", None)
                result["direct_operation"]["source"] = presentation_source(SIGNAL_PENDING, "CONFIRMATION REQUIRED",
                    blocks=(("INPUT", text), ("PROPOSED ACTION", response_text)), continuations=(invocation,))
                classification = "proposal"
        if classification == "semantic":
            phase = "semantic-preparation"
            response_text = None
            publish(phase)
            response_text = format_semantic(text)
            _check_cancelled()
            candidate = decode_preparation(text, response_text, Path(__file__).resolve().parents[2])
            if candidate["classification"] != "semantic":
                raise ValueError("semantic-preparation-unresolved")
            result = {"prepared_text": prepare_semantic(text, candidate, Path(__file__).resolve().parents[2])}
            prepared = preparation_document(submission, text, "prepared", transformed=candidate["gestalt"],
                proposal=candidate, source=candidate_source, elapsed_ms=round((time.monotonic() - started) * 1000))
            prepared["diagnostic"]["penguin_response"] = response_text
            prepared["diagnostic"]["effective_channel"] = "semantic"
            prepared["diagnostic"]["validation_scope"] = "Prose framing, semantic channel and active LUCID verb vocabulary checked; semantic fidelity unverified"
            prepared["diagnostic"]["semantic_admission"] = {
                "forwarded": "original-input", "forwarded_input_hash": input_hash(text),
                "proposal_input_hash": input_hash(candidate["gestalt"]),
                "proposal_admitted": False, "reason": "semantic-fidelity-unverified",
            }
            prepared["source"] = presentation_source(SIGNAL_WARNING, "PROPOSAL ONLY",
                data=("Original input forwarded unchanged", "rewrite not admitted"),
                blocks=(("INPUT", text), ("PROPOSED RESTATEMENT", candidate["gestalt"])))
            result["preparation"] = prepared
        elif classification == "direct":
            phase = "twitch-admission"
            if set(candidate) != {"classification", "operation", "classifier_response"}:
                raise ValueError("direct-proposal-schema")
            bound = {key: value for key, value in candidate.items() if key != "classifier_response"}
            bound.update(schema=SCHEMA, input_hash=input_hash(text), catalog_hash=catalog_hash())
            admission = evaluate_twitch(text, bound, lucid_verbs=lucid_vocabulary()["verbs"]
                if candidate["operation"]["channel"] == "lucid" else ())
            if admission.operation and candidate_source == "penguin":
                retain_candidate(home, text, candidate)
            phase = "execution" if admission.operation else "twitch-admission"
            publish(phase, response_text)
            _check_cancelled()
            receipt = execute_direct(submission, workspace, admission.operation) if admission.operation else {"refusal": admission.refusal, "ran": False}
            receipt["admission"] = admission.diagnostic()
            receipt["interpretation_source"] = candidate_source
            result = {"direct_operation": operation_document(submission, text, receipt, candidate)}
        elif classification != "proposal":
            reason = "intent-clarification-required"
            result = {"direct_operation": operation_document(submission, text, {"refusal": reason, "ran": False}, candidate)}
    except (OSError, ValueError, KeyError, TypeError, IndexError, http.client.HTTPException) as error:
        reason = str(error) if isinstance(error, ValueError) else type(error).__name__
        result = {"direct_operation": operation_document(submission, text,
            {"refusal": reason[:256], "ran": None if phase == "execution" else False,
             "execution_state": "unknown" if phase == "execution" else "not-started", "phase": phase}, candidate)}
    finally:
        _REQUEST.selection_context = None
        if result is not None:
            evidence = result.get("preparation") or result.get("direct_operation")
            if evidence is not None:
                evidence["diagnostic"]["input_normalization"] = {
                    "submitted_input": original_input, "submitted_input_hash": input_hash(original_input),
                    "inference_input_hash": input_hash(text), "changed": original_input != text,
                    "owner": "hermes_cli.input_sanitize.sanitize_user_prompt_text",
                }
                evidence["diagnostic"]["classifier_response"] = classifier_response
                evidence["diagnostic"]["classifier_selection"] = (
                    {"label": classifier_response.strip(),
                     "channel": classifier_choices()[classifier_response.strip()],
                     "effective_channel": classification,
                            "selected_verb": classifier_verbs().get(classifier_response.strip())}
                    if isinstance(classifier_response, str) and classifier_response.strip() in classifier_choices()
                    else None)
                evidence["diagnostic"]["stages"] = [dict(stage) for stage in _REQUEST.stages]
                evidence["diagnostic"]["lucid_traversal"] = getattr(_REQUEST, "lucid_traversal", None)
                if "direct_operation" in result and evidence["diagnostic"]["receipt"].get("execution_state") == "not-started":
                    evidence["diagnostic"]["original_input"] = original_input
                    evidence["diagnostic"]["input_hash"] = input_hash(original_input)
                    project_penguin_failure(evidence)
        with _ACTIVE_LOCK:
            _ACTIVE.pop(submission, None)
        _REQUEST.submission = None
        _REQUEST.progress = None
    if "direct_operation" in result:
        result["direct_operation"]["diagnostic"]["admission_elapsed_ms"] = round((time.monotonic() - started) * 1000)
        result["direct_operation"]["diagnostic"]["phase"] = phase
        result["direct_operation"]["diagnostic"]["penguin_response"] = response_text
    with _journal(home) as journal:
        journal.execute("UPDATE operations SET result=? WHERE id=?", (json.dumps(result), submission))
    if on_preparation is not None:
        if prepared is not None:
            on_preparation(prepared)
        else:
            publish("refused" if result["direct_operation"]["diagnostic"]["receipt"].get("refusal") else "prepared",
                response_text or "")
    _REQUEST.stages = None
    _REQUEST.lucid_traversal = None
    return result


def operation_history(home: Path, session: str) -> list[dict]:
    with _journal(home) as journal:
        rows = journal.execute("SELECT id,created,result FROM operations WHERE session=? AND result IS NOT NULL ORDER BY created LIMIT 256", (session,)).fetchall()
    messages = []
    for identity, created, serialized in rows:
        result = json.loads(serialized)
        for key, suffix in (("preparation", "-preparation"), ("direct_operation", "")):
            if key in result:
                messages.append({"id": identity + suffix, "role": "system",
                    "text": "twitch:" + json.dumps(result[key]), "timestamp": created})
    return messages


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt-receipt", action="store_true", required=True)
    parser.parse_args()
    print(generate_prompt_receipt(Path(__file__).resolve().parents[2]))