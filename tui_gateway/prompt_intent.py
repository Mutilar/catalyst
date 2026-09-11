"""Prompt preparation and a separate, non-model direct-operation journal."""

from __future__ import annotations

import http.client
import json
import os
import socket
import shlex
from hermes_gestalt import parse_stream, semantic_action
import sqlite3
import time
import threading
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from agent.generated.ae_glyphs import SIGNAL_GREEN, SIGNAL_RED, SIGNAL_PENDING, IDENTITY_PENGUIN
from hermes_penguin import PENGUIN_WIRE_MODEL_ID
from tui_gateway.intent_admission import (
    MAX_INPUT_BYTES, SCHEMA, catalog_hash, evaluate_twitch, input_hash,
    invocation_tokens, operation_from_tokens,
)

_ENDPOINT = os.environ.pop("AE_WITNESS_DIRECT_ENDPOINT", "")
_TOKEN = os.environ.pop("AE_WITNESS_DIRECT_TOKEN", "")
_MAX_RESPONSE = 524_288
_CACHE_TTL = 3600
_ACTIVE_LOCK = threading.Lock()
_ACTIVE: dict[str, tuple[str, threading.Event, list]] = {}
_REQUEST = threading.local()
CLASSIFIER_CHANNELS = {"🧠": "lucid", "🔎": "semantic", "🤖": "cli"}
STAGE_TOKEN_LIMITS = {"classification": 8, "semantic-preparation": 8192, "lucid-preparation": 1024}


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
    vocabulary = lucid_vocabulary()
    rows = ["| Verb | Glyph |", "|---|---|"]
    for verb, definition in vocabulary["verbs"].items():
        cells = [verb.upper(), definition["glyph"]]
        rows.append("| " + " | ".join(cell.replace("|", "\\|").replace("\n", " ") for cell in cells) + " |")
    return path.read_text(encoding="utf-8") + "\n\n" + "\n".join(rows)


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
        raise ValueError("lucid-lowering-required" if channel == "lucid" else "classifier-invocation-mismatch")
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
        "lucid_instruction": input_hash(lucid_instruction()),
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


def lucid_instruction() -> str:
    path = Path(__file__).with_name("penguin-lucid.md")
    if path.is_symlink() or not 0 < path.stat().st_size <= 8192:
        raise ValueError("lucid-instruction-source-bound")
    return path.read_text(encoding="utf-8")


def format_lucid(text: str) -> str:
    return penguin_inference(text, lucid_instruction(), "lucid-preparation", STAGE_TOKEN_LIMITS["lucid-preparation"])


def validate_lucid_preparation(response: str, operation: dict) -> None:
    if not isinstance(response, str) or len(response.encode()) > 16_384 or "\n" in response.strip():
        raise ValueError("lucid-preparation-bound")
    root = Path(__file__).resolve().parents[2]
    stream = parse_stream(root, SIGNAL_GREEN + " · " + response.strip())
    if len(stream["actions"]) != 1 or stream["data"] or stream["verb"] or stream["evidence"] or stream["continuations"] or stream["timing"]:
        raise ValueError("lucid-preparation-action-required")
    action = stream["actions"][0]
    argv = operation["argv"]
    if argv and argv[0] == "--args" and len(argv) == 2:
        expected = semantic_action(root, operation["verb"], json.loads(argv[1]), "")
        expected_noun = expected.get("noun")
        expected_arguments = shlex.split(expected["argument"]) if expected.get("argument") is not None else []
    else:
        expected_noun = argv[0].lower() if argv else None
        expected_arguments = argv[1:]
    if not expected_noun or action["verb"] != operation["verb"] or action["noun"] != expected_noun.lower():
        raise ValueError("lucid-preparation-intent-mismatch")
    arguments = shlex.split(action["argument"]) if action["argument"] is not None else []
    if arguments != expected_arguments or not action["label"]:
        raise ValueError("lucid-preparation-arguments-mismatch")


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
        root / "envelope/LUCID.json", Path(__file__).with_name("penguin-lucid.md")]

    def source_hashes() -> dict:
        hashes = {}
        for path in sources:
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 524_288:
                raise ValueError("prompt-receipt-source-bound")
            hashes[path.relative_to(root).as_posix()] = input_hash(path.read_text(encoding="utf-8"))
        return hashes

    before = source_hashes()
    instructions = {"classification": classification_instruction(), "lucid-preparation": lucid_instruction(), "semantic-preparation": penguin_instruction(root)}
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
        "generation_only": True}
    digest = input_hash(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    directory = root / "run/state/runtime/penguin-prompts"
    directory.mkdir(parents=True, exist_ok=True)
    stem = digest.removeprefix("sha256:")
    readable = "# Generated PENGUIN Prompts\n\nGeneration only; not an inference or delivery attestation.\n\n"
    readable += "\n\n".join("## " + stage + "\n\n" + instruction for stage, instruction in instructions.items())
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
    _REQUEST.instruction = instruction
    stages = getattr(_REQUEST, "stages", None)
    record = {"stage": stage, "system_prompt": instruction, "input": text, "response": None}
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


def preparation_document(submission: str, text: str, phase: str, *, transformed: str = "",
    proposal: dict | None = None, source: str | None = None, elapsed_ms: int = 0) -> dict:
    pending = phase not in {"prepared", "refused"}
    signal = SIGNAL_PENDING if pending else SIGNAL_RED if phase == "refused" else SIGNAL_GREEN
    return {
        "document": {"schema": "lucid-ugui-response/1", "id": submission + "-preparation",
            "type": "document", "header": [], "actions": [], "sections": [
                {"id": "phase", "type": "status", "signal": signal,
                 "heading": "From user / PENGUIN", "body": phase},
                {"id": "original", "type": "code", "heading": "Original input", "body": text},
                {"id": "transformed", "type": "code", "heading": "Prepared input", "body": transformed},
            ]},
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
    document = {"schema": "lucid-ugui-response/1", "id": submission, "type": "document",
        "header": [], "actions": [], "sections": [
            {"id": "operation", "type": "status", "signal": SIGNAL_GREEN if success else SIGNAL_RED,
             "heading": "WITNESS / " + str((receipt.get("operation") or {}).get("channel", "intent admission")),
             "body": receipt.get("refusal") or ("Completed" if success else "Not completed")},
            {"id": "request", "type": "code", "heading": "Input", "body": text},
            {"id": "stdout", "type": "code", "heading": "Output", "body": body},
            {"id": "stderr", "type": "code", "heading": "Diagnostics", "body": stderr},
        ]}
    if receipt.get("ugui_source"):
        try:
            projected = json.loads(receipt["ugui_source"])
            if not isinstance(projected, dict) or projected.get("schema") != "lucid-ugui-response/1":
                raise ValueError("butler-projection-invalid")
            document = projected
        except (ValueError, TypeError):
            diagnostic["projection_error"] = "butler-projection-invalid"
            document["sections"].insert(0, {"id": "projection", "type": "status", "signal": SIGNAL_RED,
                "heading": "Projection failed", "body": "butler-projection-invalid"})
    return {"document": document, "diagnostic": diagnostic}


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


def admit_prompt(text: str, submission: str, session: str, workspace: str, home: Path, *, on_preparation=None) -> dict:
    started = time.monotonic()
    if not text or len(text.encode()) > MAX_INPUT_BYTES:
        return {"direct_operation": operation_document(submission, "", {"refusal": "input-bound", "ran": False})}
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
    _REQUEST.instruction = None
    _REQUEST.stages = []
    classifier_response = None

    def publish(phase: str, transformed: str = "") -> dict:
        document = preparation_document(submission, text, phase, transformed=transformed,
            proposal=candidate, source=candidate_source, elapsed_ms=round((time.monotonic() - started) * 1000))
        document["diagnostic"]["penguin_response"] = response_text
        document["diagnostic"]["classifier_response"] = classifier_response
        document["diagnostic"]["stages"] = [dict(stage) for stage in _REQUEST.stages]
        instruction = getattr(_REQUEST, "instruction", None)
        if instruction is not None:
            document["diagnostic"]["penguin_system_prompt"] = instruction
            document["diagnostic"]["penguin_system_prompt_hash"] = input_hash(instruction)
        if on_preparation is not None:
            on_preparation(document)
        return document

    with _ACTIVE_LOCK:
        _ACTIVE[submission] = (session, threading.Event(), [])
    _REQUEST.submission = submission
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
            if candidate["operation"]["channel"] == "lucid":
                phase = "lucid-preparation"
                publish(phase)
                response_text = format_lucid(text)
                _check_cancelled()
                validate_lucid_preparation(response_text, candidate["operation"])
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
        else:
            reason = "intent-clarification-required"
            result = {"direct_operation": operation_document(submission, text, {"refusal": reason, "ran": False}, candidate)}
    except (OSError, ValueError, KeyError, TypeError, IndexError, http.client.HTTPException) as error:
        reason = str(error) if isinstance(error, ValueError) else type(error).__name__
        result = {"direct_operation": operation_document(submission, text,
            {"refusal": reason[:256], "ran": None if phase == "execution" else False,
             "execution_state": "unknown" if phase == "execution" else "not-started", "phase": phase}, candidate)}
    finally:
        instruction = getattr(_REQUEST, "instruction", None)
        if result is not None:
            evidence = result.get("preparation") or result.get("direct_operation")
            if evidence is not None:
                evidence["diagnostic"]["classifier_response"] = classifier_response
                evidence["diagnostic"]["stages"] = [dict(stage) for stage in _REQUEST.stages]
                if instruction is not None:
                    evidence["diagnostic"]["penguin_system_prompt"] = instruction
                    evidence["diagnostic"]["penguin_system_prompt_hash"] = input_hash(instruction)
        with _ACTIVE_LOCK:
            _ACTIVE.pop(submission, None)
        _REQUEST.submission = None
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
    _REQUEST.instruction = None
    _REQUEST.stages = None
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