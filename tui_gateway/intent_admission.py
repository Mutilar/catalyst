"""Bounded typed-channel admission; interpretation never grants execution."""

from __future__ import annotations

import hashlib
import json
import shlex
from dataclasses import dataclass
from typing import Any

MAX_INPUT_BYTES = 16_384
MAX_ARGUMENTS = 128
SCHEMA = "catalyst-intent-admission/2"

CHANNEL_ADAPTERS = {
    "cli": {
        "description": "An explicit single executable invocation, without shell expansion or operators.",
        "fields": {"executable": "string", "argv": "string[]"},
    },
    "lucid": {
        "description": "A LUCID CLI invocation. Butler owns verb and argument validation and lowering.",
        "fields": {"verb": "string", "argv": "string[]"},
    },
}


@dataclass(frozen=True)
class Admission:
    input_hash: str
    catalog_hash: str
    operation: dict[str, Any] | None
    refusal: str | None
    offender: str | None

    def diagnostic(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "predicate": "PREDICATE.TWITCHY",
            "input_hash": self.input_hash,
            "catalog_hash": self.catalog_hash,
            "decision": "REFUSE" if self.refusal else "PASS",
            "operation": self.operation,
            "refusal": self.refusal,
            "offender": self.offender,
            "execution_authorized": False,
            "context_admission": "excluded",
            "evidence_scope": "Explicit invocation token preservation; not arbitrary semantic equivalence or global cost optimality",
        }


def input_hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def catalog_hash() -> str:
    return input_hash(json.dumps(CHANNEL_ADAPTERS, sort_keys=True, separators=(",", ":")))


def invocation_tokens(text: str) -> list[str]:
    if not isinstance(text, str) or not text or len(text) > MAX_INPUT_BYTES:
        raise ValueError("input-out-of-bounds")
    if len(text.encode("utf-8")) > MAX_INPUT_BYTES or "\0" in text:
        raise ValueError("input-out-of-bounds")
    lexer = shlex.shlex(text, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    tokens = list(lexer)
    if not tokens or not tokens[0] or len(tokens) > MAX_ARGUMENTS + 1:
        raise ValueError("invocation-out-of-bounds")
    if "\n" in text or any(
        (token and all(character in "();<>|&" for character in token))
        or any(character in token for character in "`$") or token.startswith("~")
        for token in tokens
    ):
        raise ValueError("shell-syntax-requires-explicit-channel")
    return tokens


def operation_from_tokens(tokens: list[str], *, lucid_verbs=()) -> dict[str, Any]:
    if tokens[0] == "lucid":
        if len(tokens) < 2:
            raise ValueError("lucid-verb-missing")
        return {"channel": "lucid", "verb": tokens[1].lower(), "argv": tokens[2:]}
    if tokens[0].lower() in lucid_verbs:
        return {"channel": "lucid", "verb": tokens[0].lower(), "argv": tokens[1:]}
    return {"channel": "cli", "executable": tokens[0], "argv": tokens[1:]}


def evaluate_twitch(
    text: str,
    proposal: object,
    *, lucid_verbs=(),
) -> Admission:
    """Check bounded invocation syntax independently of model confidence."""
    source_hash = ""
    declared_hash = catalog_hash()

    def refuse(reason: str, offender: str) -> Admission:
        return Admission(source_hash, declared_hash, None, reason, offender)

    try:
        tokens = invocation_tokens(text)
        source_hash = input_hash(text)
        expected_operation = operation_from_tokens(tokens, lucid_verbs=lucid_verbs)
    except ValueError as error:
        return refuse(str(error), "input")
    if not isinstance(proposal, dict) or set(proposal) != {
        "schema", "input_hash", "catalog_hash", "classification", "operation"
    }:
        return refuse("proposal-schema", "proposal")
    for field, expected_binding in (
        ("schema", SCHEMA), ("input_hash", source_hash), ("catalog_hash", declared_hash)
    ):
        if proposal[field] != expected_binding:
            return refuse("proposal-binding", f"proposal.{field}")
    if proposal["classification"] != "direct":
        return refuse("not-direct", "proposal.classification")
    if proposal["operation"] != expected_operation:
        return refuse("intent-not-preserved", "proposal.operation")
    return Admission(source_hash, declared_hash, expected_operation, None, None)