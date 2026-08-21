"""Closed execution compiler for canonical LUCID UGUI actions.

The renderer submits one previously projected document plus an action identity.
This module binds the action to its projection provenance and compiles only the
small set of intents that are already complete enough to invoke directly.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any, Mapping

_MAX_DOCUMENT_BYTES = 262_144
_MAX_ACTIONS = 32
_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}$")
_DISPATCH_ID = re.compile(r"^dispatch:[0-9a-f]{64}$")
_LUCID_VERBS = {"show", "get", "set", "morph", "dispatch", "steer", "cancel"}
_MUTATING_VERBS = {"set", "dispatch", "steer", "cancel"}
_MUTATING_MORPH_OPERATIONS = {"start", "customize", "write", "advance"}
_READ_MORPH_OPERATIONS = {"inspect", "shard", "vocabulary", "project"}
_FORBIDDEN_AUTHORITY_KEYS = {
    "capability",
    "signature",
    "localCapability",
    "exact_confirmation",
    "_meta",
    "callContext",
}


class UguiActionError(ValueError):
    """A UGUI action is malformed, stale, unconfirmed, or not executable."""

    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class CompiledLUCIDAction:
    server_name: str
    tool_name: str
    arguments: dict[str, Any]
    action_id: str
    provenance_hash: str


def _object(value: Any, code: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise UguiActionError(code, "expected an object")
    return value


def _bounded_document(document: Any) -> Mapping[str, Any]:
    root = _object(document, "document-invalid")
    try:
        encoded = json.dumps(root, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise UguiActionError("document-invalid", "document is not JSON-serializable") from exc
    if len(encoded) > _MAX_DOCUMENT_BYTES:
        raise UguiActionError("document-oversized", "document exceeds the action execution bound")
    if root.get("schema") not in {
        "lucid-ugui-response/1",
        "lucid-show-document/1",
        "lucid-help-document/1",
    }:
        raise UguiActionError("document-schema", "document is not a canonical LUCID UGUI response")
    return root


def _contains_authority(value: Any) -> bool:
    if isinstance(value, dict):
        return any(key in _FORBIDDEN_AUTHORITY_KEYS or _contains_authority(child) for key, child in value.items())
    if isinstance(value, list):
        return any(_contains_authority(child) for child in value)
    return False


def compile_lucid_ugui_action(
    document: Any,
    action_id: str,
    *,
    confirmed: bool = False,
    inputs: Mapping[str, Any] | None = None,
) -> CompiledLUCIDAction:
    """Compile one provenance-bound UGUI action into one exact LUCID tool call."""

    root = _bounded_document(document)
    if not isinstance(action_id, str) or _ID.fullmatch(action_id) is None:
        raise UguiActionError("action-id-invalid", "action id is not a bounded UGUI identity")
    if inputs:
        raise UguiActionError("action-input-unsupported", "this action has no admitted typed input")

    provenance = _object(root.get("provenance"), "provenance-missing")
    provenance_hash = provenance.get("parentHash")
    if not isinstance(provenance_hash, str) or _HASH.fullmatch(provenance_hash) is None:
        raise UguiActionError("provenance-invalid", "document provenance hash is invalid")

    actions = root.get("actions")
    if not isinstance(actions, list) or len(actions) > _MAX_ACTIONS:
        raise UguiActionError("actions-invalid", "document actions are absent or exceed their bound")
    matches = [action for action in actions if isinstance(action, dict) and action.get("id") == action_id]
    if len(matches) != 1:
        raise UguiActionError("action-unavailable", "action is absent or ambiguous")
    action = matches[0]

    receipt = _object(root.get("receipt"), "action-provenance-missing")
    receipts = receipt.get("action_provenance")
    if not isinstance(receipts, list) or len(receipts) > _MAX_ACTIONS:
        raise UguiActionError("action-provenance-invalid", "action provenance is absent or oversized")
    receipt_matches = [
        item
        for item in receipts
        if isinstance(item, dict)
        and item.get("id") == action_id
        and item.get("state") == "AVAILABLE"
        and item.get("provenance_hash") == provenance_hash
    ]
    if len(receipt_matches) != 1:
        raise UguiActionError("action-stale", "action is not available for this document provenance")

    handler = action.get("action")
    if not isinstance(handler, str):
        raise UguiActionError("action-handler-invalid", "action handler is missing")
    if action.get("disabled") is True:
        raise UguiActionError("action-not-executable", "the producer disabled this action")
    intent = _object(action.get("intent"), "action-intent-missing")
    arguments = dict(_object(intent.get("arguments"), "action-arguments-missing"))
    tool_name = intent.get("verb")
    if not isinstance(tool_name, str) or tool_name not in _LUCID_VERBS:
        raise UguiActionError("action-verb-mismatch", "action does not name a closed LUCID verb")
    if handler == "lucid.help.verb":
        if (
            arguments
            or action.get("value") != tool_name
        ):
            raise UguiActionError("action-intent-invalid", "help action is not exactly verb-bound")
        return CompiledLUCIDAction(
            server_name="LUCID",
            tool_name=tool_name,
            arguments={},
            action_id=action_id,
            provenance_hash=provenance_hash,
        )
    if not handler.startswith(f"lucid.{tool_name}."):
        raise UguiActionError("action-verb-mismatch", "action handler and LUCID verb differ")
    if _contains_authority(arguments):
        raise UguiActionError("action-authority-forbidden", "action carries authority material")
    morph_operation = arguments.get("operation")
    if tool_name == "morph" and morph_operation not in (
        _READ_MORPH_OPERATIONS | _MUTATING_MORPH_OPERATIONS
    ):
        raise UguiActionError("action-intent-invalid", "MORPH action does not name a closed operation")
    requires_confirmation = action.get("requiresConfirmation") == "exact"
    mutating = tool_name in _MUTATING_VERBS or (
        tool_name == "morph" and morph_operation in _MUTATING_MORPH_OPERATIONS
    )
    if mutating and not requires_confirmation:
        raise UguiActionError(
            "confirmation-policy-missing",
            "mutating LUCID actions require authored exact confirmation",
        )
    if requires_confirmation and not confirmed:
        raise UguiActionError("confirmation-required", "exact action confirmation is required")

    if handler in {"lucid.get.refresh", "lucid.show.refresh"}:
        content_id = action.get("value")
        if not isinstance(content_id, str) or not content_id or len(content_id.encode("utf-8")) > 512:
            raise UguiActionError("action-target-invalid", "refresh action target is not bounded")
        return CompiledLUCIDAction(
            server_name="LUCID",
            tool_name=tool_name,
            arguments=arguments,
            action_id=action_id,
            provenance_hash=provenance_hash,
        )

    if handler == "lucid.morph.choice":
        target = action.get("value")
        if not isinstance(target, str) or not target or arguments.get("codebook") != target:
            raise UguiActionError("action-target-invalid", "MORPH choice target differs from its exact request")
    elif handler == "lucid.set.host-role":
        target = action.get("value")
        expected = arguments.get("expected_hash")
        value = arguments.get("value")
        if not isinstance(target, str) or _HASH.fullmatch(target) is None or expected != target:
            raise UguiActionError("action-target-invalid", "host-role action hash is not exact")
        if set(arguments) != {"path", "scope", "op", "expected_hash", "value"}:
            raise UguiActionError("action-intent-invalid", "host-role action fields are not closed")
        if (
            arguments.get("path") != "host-role"
            or arguments.get("scope") != "this"
            or arguments.get("op") != "set"
            or not isinstance(value, dict)
            or set(value) != {"role"}
            or value.get("role") not in {"EM", "SIDEKICK"}
        ):
            raise UguiActionError("action-intent-invalid", "host-role action is not role-bound")
    elif handler == "lucid.dispatch.plan":
        target = action.get("value")
        request = arguments.get("request")
        if not isinstance(target, str) or _HASH.fullmatch(target) is None:
            raise UguiActionError("action-target-invalid", "action target is not an exact plan hash")
        if set(arguments) not in ({"task", "request"}, {"task", "request", "scope"}):
            raise UguiActionError("action-intent-invalid", "DISPATCH plan promotion fields are not closed")
        if arguments.get("task") != "engineer" or not isinstance(request, dict):
            raise UguiActionError("action-intent-invalid", "DISPATCH plan promotion is not request-bound")
        canonical = json.dumps(request, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        observed = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        if observed != target:
            raise UguiActionError("action-stale", "DISPATCH plan promotion request hash differs")
    elif handler == "lucid.show.execution":
        target = action.get("value")
        if not isinstance(target, str) or _DISPATCH_ID.fullmatch(target) is None:
            raise UguiActionError("action-target-invalid", "action target is not an exact dispatch id")
        if set(arguments) != {"view", "id"} or arguments != {"view": "execution", "id": target}:
            raise UguiActionError("action-intent-invalid", "SHOW execution intent is not exactly bound")
    elif handler == "lucid.cancel.dispatch":
        target = action.get("value")
        if not isinstance(target, str) or _DISPATCH_ID.fullmatch(target) is None:
            raise UguiActionError("action-target-invalid", "action target is not an exact dispatch id")
        if (
            set(arguments) != {"task", "dispatch_id"}
            or arguments != {"task": "fleet.dispatch", "dispatch_id": target}
        ):
            raise UguiActionError("action-intent-invalid", "CANCEL intent is not exactly bound")

    return CompiledLUCIDAction(
        server_name="LUCID",
        tool_name=tool_name,
        arguments=arguments,
        action_id=action_id,
        provenance_hash=provenance_hash,
    )


def execute_lucid_ugui_action(
    document: Any,
    action_id: str,
    *,
    confirmed: bool = False,
    inputs: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compile and invoke one action through Catalyst's existing MCP transport."""

    compiled = compile_lucid_ugui_action(
        document,
        action_id,
        confirmed=confirmed,
        inputs=inputs,
    )
    from tools.mcp_tool import invoke_registered_mcp_tool

    result = invoke_registered_mcp_tool(
        compiled.server_name,
        compiled.tool_name,
        compiled.arguments,
    )
    return {
        "ok": "error" not in result,
        "action_id": compiled.action_id,
        "provenance_hash": compiled.provenance_hash,
        "result": result,
    }
