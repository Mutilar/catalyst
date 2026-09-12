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
from hermes_penguin import PENGUIN_WIRE_MODEL_ID
from hermes_gestalt import canonical_stream
from tui_gateway.intent_admission import (
    MAX_INPUT_BYTES, SCHEMA, catalog_hash, evaluate_twitch, input_hash,
    invocation_tokens, operation_from_tokens,
)
from tui_gateway.lucid_traversal import Traversal, receipt_walkthroughs

_ENDPOINT = os.environ.pop("AE_WITNESS_DIRECT_ENDPOINT", "")
_TOKEN = os.environ.pop("AE_WITNESS_DIRECT_TOKEN", "")
_MAX_RESPONSE = 524_288
_CACHE_TTL = 3600
_ACTIVE_LOCK = threading.Lock()
_ACTIVE: dict[str, tuple[str, threading.Event, list]] = {}
_REQUEST = threading.local()
CLASSIFIER_CHANNELS = {"🧠": "lucid", "🔎": "semantic", "🤖": "cli"}
STAGE_TOKEN_LIMITS = {"classification": 8192, "semantic-preparation": 8192}


def lucid_vocabulary() -> dict:
    path = Path(__file__).resolve().parents[2] / "envelope/LUCID.json"
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 1_048_576:
        raise ValueError("lucid-vocabulary-source-bound")
    vocabulary = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(vocabulary.get("verbs"), dict) or len(vocabulary["verbs"]) != 7:
        raise ValueError("lucid-vocabulary-invalid")
    return vocabulary


def classification_instruction() -> str:
    path = Path(__file__).with_name("penguin-classification.md")
    if path.is_symlink() or not 0 < path.stat().st_size <= 8192:
        raise ValueError("classifier-instruction-source-bound")
    skill_path = Path(__file__).resolve().parents[2] / ".agents/skills/lucid/SKILL.md"
    if skill_path.is_symlink() or not skill_path.is_file() or not 0 < skill_path.stat().st_size <= 65_536:
        raise ValueError("classifier-protocol-source-bound")
    skill = skill_path.read_text(encoding="utf-8")
    header = "| **🧠 PROTOCOL** | **RULE** |"
    if skill.count(header) != 1:
        raise ValueError("classifier-protocol-table-missing")
    table = header + skill.split(header, 1)[1].split("\n\n", 1)[0]
    vocabulary = lucid_vocabulary()
    for verb, definition in vocabulary["verbs"].items():
        if table.count(f"| ↳ {definition['glyph']} | {verb.upper()} |") != 1:
            raise ValueError("classifier-protocol-vocabulary-mismatch")
    template = path.read_text(encoding="utf-8")
    if template.count("{{LUCID_PROTOCOL}}") != 1:
        raise ValueError("classifier-protocol-slot-invalid")
    return template.replace("{{LUCID_PROTOCOL}}", table)


def decode_classification(text: str, response: str) -> dict:
    if not isinstance(response, str) or response.strip() not in CLASSIFIER_CHANNELS:
        raise ValueError("penguin-classifier-glyph-invalid")
    glyph = response.strip()
    channel = CLASSIFIER_CHANNELS[glyph]
    try:
        tokens = shlex.split(text)
    except ValueError:
        tokens = []
    verb = tokens[1] if len(tokens) > 1 and tokens[0].lower() == "lucid" else tokens[0] if tokens else ""
    if verb.lower() == "morph":
        return {"classification": "semantic", "classifier_response": response}
    if channel == "semantic":
        return {"classification": "semantic", "classifier_response": response}
    operation = operation_from_tokens(invocation_tokens(text),
        lucid_verbs=lucid_vocabulary()["verbs"] if channel == "lucid" else ())
    if operation["channel"] != channel:
        if channel == "lucid":
            return {"classification": "lucid", "classifier_response": response}
        raise ValueError("classifier-invocation-mismatch")
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
        "policy": input_hash(Path(__file__).read_text())}, sort_keys=True))


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
    def read_source(path: Path) -> str:
        metadata = path.lstat()
        if path.is_symlink() or not path.is_file() or not 0 < metadata.st_size <= 65_536:
            raise ValueError("penguin-instruction-source-bound")
        return path.read_text(encoding="utf-8")

    canon = json.loads(read_source(root / "quine/canon/AGENT_INSTRUCTIONS.json"))
    gestalt = [row for row in canon["rlhf_behavior"] if row["directive"] == "GESTALT"]
    if len(gestalt) != 1:
        raise ValueError("gestalt-behavior-unavailable")
    protocol = [f"| **{IDENTITY_PENGUIN}** | **PROTOCOL** |", "|---|---|"]
    for row in canon["protocol"]["rows"]:
        signal = row["signal"].replace("<WITNESS>", IDENTITY_PENGUIN)
        definition = row["definition"].replace("<WITNESS>", IDENTITY_PENGUIN)
        protocol.append(f"| {signal} | {definition} |")
    protocol.extend(["", "| **BEHAVIOR** | **RULE** |", "|---|---|",
        f"| **GESTALT** | {gestalt[0]['definition']} |"])
    return "\n".join(protocol) + "\n\n" + read_source(Path(__file__).with_name("penguin-preparation.md"))


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
    unresolved = False
    for paragraph in paragraphs:
        if paragraph and all(character == "🐧" for character in paragraph):
            continue
        if paragraph.startswith(action + " "):
            continue
        if paragraph.startswith("$$"):
            continue
        if not paragraph.startswith(states):
            raise ValueError("penguin-unframed-prose")
        for line in paragraph.splitlines():
            if line.startswith(states):
                state = line.partition(grammar["separator"])[0]
                unresolved |= state != SIGNAL_GREEN
    if unresolved:
        return {"classification": "ambiguous", "gestalt": response}
    return {"classification": "semantic", "gestalt": response}


def classify(text: str) -> str:
    return penguin_inference(text, classification_instruction(), "classification", STAGE_TOKEN_LIMITS["classification"])


def format_semantic(text: str) -> str:
    return penguin_inference(text, penguin_instruction(Path(__file__).resolve().parents[2]), "semantic-preparation", STAGE_TOKEN_LIMITS["semantic-preparation"])


def format_lucid(text: str) -> str:
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
        result = traversal.run(Path(__file__).resolve().parents[2], explicit)
        _REQUEST.lucid_traversal = result
        return result.get("gestalt", "")
    except (ValueError, KeyError, TypeError) as error:
        _REQUEST.lucid_traversal = {"steps": traversal.records, "refusal": str(error), "executed": False}
        raise


def penguin_request(text: str, instruction: str, max_tokens: int) -> dict:
    return {
        "model": PENGUIN_WIRE_MODEL_ID, "temperature": 0, "max_tokens": max_tokens,
        "messages": [{"role": "system", "content": instruction}, {"role": "user", "content": text}],
    }


def generate_prompt_receipt(root: Path) -> Path:
    root = root.resolve()
    sources = [Path(__file__).resolve(), Path(__file__).with_name("penguin-classification.md"),
        Path(__file__).with_name("penguin-preparation.md"), root / "quine/canon/AGENT_INSTRUCTIONS.json",
        root / "catalyst/hermes_penguin.py", root / "catalyst/agent/generated/ae_glyphs.py",
        root / "envelope/LUCID.json", root / "envelope/GESTALT.json", root / ".agents/skills/lucid/SKILL.md",
        Path(__file__).with_name("lucid_traversal.py"),
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
    stages = []
    for stage, instruction in instructions.items():
        request = penguin_request("", instruction, STAGE_TOKEN_LIMITS[stage])
        stages.append({"stage": stage, "system_message": request["messages"][0],
            "system_prompt_hash": input_hash(instruction),
            "request_settings": {key: value for key, value in request.items() if key != "messages"},
            "user_message_binding": "The submitted input is supplied verbatim at inference time; no user input was supplied for this generation."})
    if source_hashes() != before:
        raise ValueError("prompt-receipt-source-changed")
    payload = {"schema": "penguin-prompt-generation/1", "generator": "tui_gateway.prompt_intent.generate_prompt_receipt",
        "sources": before, "stages": stages, "inference_ran": False,
        "lucid_traversal": walkthroughs,
        "audit": {
            "generation": "Executed actual prompt assembly and pinned traversal projection; no model or command execution",
            "design_obligations": ["Original input is supplied to every inference", "Only current-stage choices are shown",
                "Explicit choices skip inference", "MORPH returns to semantic evaluation",
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
    readable += "\n\n".join("## " + stage + "\n\n" + instruction for stage, instruction in instructions.items())
    readable += "\n\n## LUCID Traversal Receipt\n\nGeneration-only walkthroughs; no inference or execution.\n"
    for walkthrough in walkthroughs:
        readable += "\n### " + walkthrough["input"] + "\n\n"
        for step in walkthrough["result"]["steps"]:
            readable += "#### " + step["stage"] + "\n\n"
            readable += step.get("system_prompt", "Argument contract resolved without inference.") + "\n\n"
            readable += "Selection: `" + str(step.get("selected", "")) + "`\n\n"
        readable += walkthrough["result"].get("gestalt", "Semantic evaluation required.") + "\n"
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
    record = {"stage": stage, "system_prompt": instruction, "system_prompt_hash": input_hash(instruction),
        "max_tokens": max_tokens, "input": text, "response": None}
    if stages is not None:
        stages.append(record)
    started = time.monotonic()
    body = json.dumps(penguin_request(text, instruction, max_tokens)).encode()
    connection = http.client.HTTPConnection(endpoint.hostname, endpoint.port, timeout=30)
    try:
        connection.request("POST", "/v1/chat/completions", body, {"Content-Type": "application/json"})
        _track(connection)
        response = connection.getresponse()
        raw = response.read(_MAX_RESPONSE + 1)
        if response.status != 200 or len(raw) > _MAX_RESPONSE:
            raise ValueError("penguin-response-unavailable")
        result = json.loads(raw)
        choice = result["choices"][0]
        record["response"] = choice.get("message", {}).get("content")
        record["finish_reason"] = choice.get("finish_reason")
        usage = result.get("usage")
        if isinstance(usage, dict):
            record["usage"] = {key: usage[key] for key in ("prompt_tokens", "completion_tokens", "total_tokens")
                if type(usage.get(key)) is int and usage[key] >= 0}
        reasoning = choice.get("message", {}).get("reasoning_content")
        if isinstance(reasoning, str):
            record["reasoning_chars"] = len(reasoning)
        if choice.get("finish_reason") != "stop":
            raise ValueError("penguin-response-incomplete")
        response_text = choice["message"]["content"]
        if not isinstance(response_text, str):
            raise ValueError("penguin-gestalt-string-required")
        return response_text
    finally:
        record["elapsed_ms"] = round((time.monotonic() - started) * 1000)
        connection.close()


def prepare_semantic(text: str, candidate: dict, root: Path) -> str:
    if set(candidate) != {"classification", "gestalt"}:
        raise ValueError("semantic-schema")
    if decode_preparation(text, candidate["gestalt"], root)["classification"] != "semantic":
        raise ValueError("semantic-channel-mismatch")
    return candidate["gestalt"]


def presentation_source(signal: str, evidence: str, *, data: tuple[str, ...] = (),
    blocks: tuple[tuple[str, str], ...] = (), continuations: tuple[str, ...] = ()) -> str:
    root = Path(__file__).resolve().parents[2]
    source = canonical_stream(root, signal, service=IDENTITY_PENGUIN,
        evidence=(evidence,), data=data)
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
    diagnostic["recovery"] = {"submission_id": diagnostic["submission_id"]}
    evidence.pop("document", None)
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
    classifier_response = None

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
            publish(phase)
            response_text = format_lucid(text)
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
            publish(phase)
            response_text = format_semantic(text)
            _check_cancelled()
            candidate = decode_preparation(text, response_text, Path(__file__).resolve().parents[2])
            if candidate["classification"] != "semantic":
                raise ValueError("semantic-preparation-unresolved")
            result = {"prepared_text": prepare_semantic(text, candidate, Path(__file__).resolve().parents[2])}
            prepared = preparation_document(submission, text, "prepared", transformed=result["prepared_text"],
                proposal=candidate, source=candidate_source, elapsed_ms=round((time.monotonic() - started) * 1000))
            prepared["diagnostic"]["penguin_response"] = response_text
            prepared["diagnostic"]["effective_channel"] = "semantic"
            prepared["diagnostic"]["validation_scope"] = "Canonical GESTALT syntax and channel; semantic fidelity is not mechanically proven"
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
        if result is not None:
            evidence = result.get("preparation") or result.get("direct_operation")
            if evidence is not None:
                evidence["diagnostic"]["classifier_response"] = classifier_response
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