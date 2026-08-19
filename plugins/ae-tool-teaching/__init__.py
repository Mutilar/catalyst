"""AE PENGUIN tool-call teaching.

HARNESS policy decides whether a call is held. PENGUIN may only suggest one
existing LUCID call; deterministic validation is authoritative and no suggestion
executes or replays either the original or candidate call.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import threading
import urllib.request
from collections import OrderedDict
from pathlib import Path
from typing import Any, Optional

SUGGESTION_SCHEMA = "penguin-tool-suggestion/1"
CANDIDATE_SCHEMA = "penguin-tool-suggestion-candidate/1"
_MODE_ENV = "AE_PENGUIN_TOOL_INTERPRETATION"
_HOLD_FOCUSED_ENV = "AE_PENGUIN_TOOL_HOLD_FOCUSED"
_MAX_COMMAND_BYTES = 16_384
_MAX_RESPONSE_BYTES = 16_384
_MAX_TRAJECTORIES = 256
_AREA_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")
_STATE_LOCK = threading.Lock()
_HELD_CALLS: OrderedDict[tuple[str, str], int] = OrderedDict()
_OVERRIDDEN_CALLS: OrderedDict[tuple[str, str], int] = OrderedDict()
_PENDING_CANDIDATES: OrderedDict[tuple[str, str], dict[str, Any]] = OrderedDict()


def _mode() -> str:
    value = os.environ.get(_MODE_ENV, "heuristic").strip().lower()
    return value if value in {"off", "heuristic", "intelligent"} else "heuristic"


def _truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _ae_root(args: dict[str, Any]) -> Optional[Path]:
    candidates = [args.get("workdir"), args.get("cwd"), os.environ.get("TERMINAL_CWD"), os.getcwd()]
    for raw in candidates:
        if not isinstance(raw, (str, os.PathLike)) or not str(raw):
            continue
        try:
            current = Path(raw).expanduser().resolve(strict=True)
        except (OSError, RuntimeError, TypeError, ValueError):
            continue
        for root in (current, *current.parents):
            if (root / "run/STACK.json").is_file() and (root / "envelope/LUCID.json").is_file():
                return root
    return None


def _flag_value(tokens: list[str], flag: str) -> Optional[str]:
    for index, token in enumerate(tokens):
        if token == flag and index + 1 < len(tokens):
            return tokens[index + 1]
        if token.startswith(flag + "="):
            return token.split("=", 1)[1]
    return None


def _flag_present(tokens: list[str], flag: str) -> bool:
    return flag in tokens or any(token.startswith(flag + "=") for token in tokens)


def _area_from(value: str, kind: str) -> Optional[str]:
    if kind == "atom":
        return value if _AREA_RE.fullmatch(value) else None
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        return None
    if kind == "path-parent":
        parent = path.parent.as_posix().strip("./")
        value = parent or path.stem
    elif kind == "path":
        value = path.as_posix().strip("./")
    else:
        return None
    return value if _AREA_RE.fullmatch(value) else None


def _prefix_matches(tokens: list[str], prefix: Any) -> bool:
    if not isinstance(prefix, list) or not prefix or len(tokens) < len(prefix):
        return False
    return Path(tokens[0]).name == prefix[0] and tokens[1 : len(prefix)] == prefix[1:]


def _unwrap_invocation(tokens: list[str]) -> list[str]:
    unwrapped = list(tokens)
    if unwrapped and Path(unwrapped[0]).name in {"env", "command"}:
        unwrapped.pop(0)
    while unwrapped and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", unwrapped[0]):
        unwrapped.pop(0)
    return unwrapped


def _workspace_area(root: Path, args: dict[str, Any]) -> str:
    raw = args.get("workdir") or args.get("cwd") or os.environ.get("TERMINAL_CWD")
    if not isinstance(raw, str) or not raw:
        return "workspace"
    try:
        relative = Path(raw).expanduser().resolve(strict=True).relative_to(root)
    except (OSError, RuntimeError, TypeError, ValueError):
        return "workspace"
    value = relative.as_posix().strip("./") or "workspace"
    return value if _AREA_RE.fullmatch(value) else "workspace"



def _registry(root: Path) -> Optional[dict[str, Any]]:
    try:
        lucid = json.loads((root / "envelope/LUCID.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, TypeError):
        return None
    registry = lucid.get("tool_suggestion_registry")
    if not isinstance(registry, dict) or registry.get("schema") != "lucid-tool-suggestion-registry/1":
        return None
    targets = registry.get("targets")
    if not isinstance(targets, list) or not targets or len(targets) > 64:
        return None
    return registry


def _command_intent(
    tool_name: str,
    args: dict[str, Any],
    registry: dict[str, Any],
    root: Path,
) -> Optional[tuple[dict[str, Any], dict[str, Any]]]:
    if tool_name != "terminal":
        return None
    command = args.get("command")
    if not isinstance(command, str) or not command or len(command.encode("utf-8")) > _MAX_COMMAND_BYTES:
        return None
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        return None
    if not tokens or any(token in {"&&", "||", ";", "|"} for token in tokens):
        return None
    invocation_tokens = _unwrap_invocation(tokens)
    if not invocation_tokens:
        return None
    for target in registry["targets"]:
        if not isinstance(target, dict):
            continue
        source = target.get("source")
        if not isinstance(source, dict) or source.get("tool") != tool_name:
            continue
        prefixes = source.get("argv_prefixes")
        if not isinstance(prefixes, list):
            continue
        prefix = next(
            (prefix for prefix in prefixes if _prefix_matches(invocation_tokens, prefix)), None
        )
        if prefix is None:
            continue
        invocation = invocation_tokens[len(prefix) :]
        action = source.get("action_token")
        if isinstance(action, str) and action not in invocation:
            continue
        focus_flags = source.get("focus_flags")
        if not isinstance(focus_flags, list) or not all(isinstance(flag, str) for flag in focus_flags):
            continue
        release_flags = source.get("release_flags")
        if not isinstance(release_flags, list) or not all(isinstance(flag, str) for flag in release_flags):
            continue
        focused = any(_flag_present(invocation, flag) for flag in focus_flags)
        area = _workspace_area(root, args)
        area_flags = source.get("area_flags")
        if not isinstance(area_flags, list):
            continue
        for rule in area_flags:
            if not isinstance(rule, dict):
                continue
            flag = rule.get("flag")
            kind = rule.get("kind")
            if not isinstance(flag, str) or not isinstance(kind, str):
                continue
            value = _flag_value(invocation, flag)
            if value is not None:
                derived = _area_from(value, kind)
                if derived is None:
                    return None
                area = derived
                focused = True
                break
        if source.get("positional_focus") is True:
            positional = next(
                (
                    token
                    for token in invocation
                    if not token.startswith("-")
                    and token != action
                    and ("/" in token or token.endswith((".py", ".rs", ".ts", ".tsx")))
                ),
                None,
            )
            if positional is not None:
                focused = True
                derived = _area_from(positional, "path-parent")
                if derived is not None:
                    area = derived
        intent = {
            "tool": "terminal",
            "executable": source.get("executable"),
            "operation": source.get("operation"),
            "target": target.get("id"),
            "area": area,
            "focused": focused,
            "release": any(_flag_present(invocation, flag) for flag in release_flags),
            "command_hash": "sha256:" + hashlib.sha256(command.encode("utf-8")).hexdigest(),
        }
        if not all(isinstance(intent[key], str) and intent[key] for key in ("executable", "operation", "target")):
            continue
        return intent, target
    return None


def _registry_hash(registry: dict[str, Any]) -> str:
    canonical = json.dumps(registry, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _heuristic_candidate(intent: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    candidate = target.get("candidate", {})
    if candidate.get("shape") == "quality-operation":
        arguments = {"area": intent["area"], "operation": candidate.get("operation")}
        explanation = (
            f"Use the registered {candidate.get('operation')} quality owner when this command is intended "
            "as completion evidence."
        )
    elif candidate.get("shape") == "run-qualification":
        arguments = {"task": candidate.get("task"), "area": intent["area"]}
        explanation = "Use RUN qualification when this build is intended to produce or promote a runtime artifact."
    else:
        raise ValueError("unregistered-candidate-shape")
    return {
        "schema": CANDIDATE_SCHEMA,
        "verb": candidate.get("verb"),
        "arguments": arguments,
        "explanation": explanation,
    }


def _candidate_valid(candidate: Any, intent: dict[str, Any]) -> bool:
    if not isinstance(candidate, dict) or set(candidate) != {"schema", "verb", "arguments", "explanation"}:
        return False
    if candidate.get("schema") != CANDIDATE_SCHEMA or candidate.get("verb") != "dispatch":
        return False
    explanation = candidate.get("explanation")
    arguments = candidate.get("arguments")
    if not isinstance(explanation, str) or not explanation or len(explanation) > 512:
        return False
    if not isinstance(arguments, dict) or arguments.get("area") != intent["area"]:
        return False
    if intent["operation"] in {"test", "lint", "line_coverage", "branch_coverage"}:
        return (
            set(arguments) == {"area", "operation"}
            and arguments.get("operation") == intent["operation"]
        )
    return set(arguments) == {"task", "area"} and arguments.get("task") == "run.qualify"


def _penguin_candidate(intent: dict[str, Any], heuristic: dict[str, Any]) -> dict[str, Any]:
    endpoint = os.environ.get("AE_SLM_ENDPOINT", "").rstrip("/")
    model = os.environ.get("AE_SLM_MODEL", "")
    if not endpoint or not model:
        raise RuntimeError("penguin-unavailable")
    prompt = {
        "schema": "penguin-tool-suggestion-request/1",
        "authority": "none",
        "instruction": (
            "Return exactly one raw penguin-tool-suggestion-candidate/1 JSON object. "
            "Preserve verb=dispatch and the exact area. Do not execute, replay, add capability, or emit prose."
        ),
        "intent": intent,
        "heuristic_candidate": heuristic,
    }
    body = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": json.dumps(prompt, separators=(",", ":"))}],
            "temperature": 0,
            "max_tokens": 256,
        },
        separators=(",", ":"),
    ).encode("utf-8")
    request = urllib.request.Request(
        endpoint + "/v1/chat/completions",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        payload = response.read(_MAX_RESPONSE_BYTES + 1)
    if len(payload) > _MAX_RESPONSE_BYTES:
        raise RuntimeError("penguin-response-too-large")
    decoded = json.loads(payload)
    content = decoded["choices"][0]["message"]["content"]
    candidate = json.loads(content)
    if not _candidate_valid(candidate, intent):
        raise RuntimeError("penguin-candidate-invalid")
    return candidate


def _suggestion(
    intent: dict[str, Any],
    mode: str,
    target: dict[str, Any],
    registry: dict[str, Any],
    *,
    decision: str,
    original_executed: bool,
    attempt: int,
) -> dict[str, Any]:
    heuristic = _heuristic_candidate(intent, target)
    candidate = heuristic
    source = "heuristic"
    fallback = None
    if mode == "intelligent":
        try:
            candidate = _penguin_candidate(intent, heuristic)
            source = "PENGUIN"
        except Exception as error:  # graceful, content-free fallback
            fallback = type(error).__name__
    valid = _candidate_valid(candidate, intent)
    if not valid:
        candidate = heuristic
        source = "heuristic"
        fallback = "candidate-invalid"
        valid = True
    return {
        "schema": SUGGESTION_SCHEMA,
        "state": "validated",
        "decision": decision,
        "source": source,
        "authority": "none",
        "executed": False,
        "auto_replay": False,
        "original_executed": original_executed,
        "mode": mode,
        "registry_hash": _registry_hash(registry),
        "intent": intent,
        "candidate": candidate,
        "preflight": {"valid": valid, "validator": "AE deterministic tool suggestion preflight"},
        "trajectory": {"state": decision, "attempt": attempt},
        "fallback": fallback,
    }


def _refusal(intent: dict[str, Any], target: dict[str, Any], registry: dict[str, Any]) -> dict[str, Any]:
    declaration = target.get("candidate")
    if not isinstance(declaration, dict) or declaration.get("shape") != "refusal":
        raise ValueError("unregistered-refusal-shape")
    return {
        "schema": "penguin-tool-refusal/1",
        "state": "refused",
        "reason": declaration.get("reason"),
        "authority": "none",
        "policy_owner": "HARNESS",
        "executed": False,
        "auto_replay": False,
        "original_executed": False,
        "registry_hash": _registry_hash(registry),
        "intent": intent,
        "alternative": {
            "kind": declaration.get("alternative"),
            "verb": "get",
            "path": "search",
            "constraint": "explicit search terms are required; Git repository/history access remains prohibited",
        },
    }


def _policy_disposition(intent: dict[str, Any], target: dict[str, Any]) -> Optional[str]:
    raw_policy = target.get("policy")
    policy = raw_policy if isinstance(raw_policy, dict) else {}
    disposition = (
        policy.get("release")
        if intent["release"]
        else policy.get("focused")
        if intent["focused"]
        else policy.get("workspace")
    )
    if intent["focused"] and _truthy(_HOLD_FOCUSED_ENV):
        return "hold"
    return disposition if disposition in {"whisper", "hold", "enforce"} else None


def _bounded_put(mapping: OrderedDict, key: Any, value: Any) -> None:
    mapping[key] = value
    mapping.move_to_end(key)
    while len(mapping) > _MAX_TRAJECTORIES:
        mapping.popitem(last=False)


def _hold_once(intent: dict[str, Any], session_id: str) -> bool:
    key = (session_id or "session-unknown", intent["command_hash"])
    with _STATE_LOCK:
        if key in _HELD_CALLS:
            attempt = _HELD_CALLS.pop(key) + 1
            _bounded_put(_OVERRIDDEN_CALLS, key, attempt)
            return False
        _bounded_put(_HELD_CALLS, key, 1)
        return True


def _consume_override(command_hash: str, session_id: str) -> Optional[int]:
    key = (session_id or "session-unknown", command_hash)
    with _STATE_LOCK:
        return _OVERRIDDEN_CALLS.pop(key, None)


def _remember_candidate(session_id: str, suggestion: dict[str, Any]) -> None:
    candidate = suggestion["candidate"]
    canonical = json.dumps(candidate, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    fingerprint = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    key = (session_id or "session-unknown", fingerprint)
    with _STATE_LOCK:
        _bounded_put(
            _PENDING_CANDIDATES,
            key,
            {
                "candidate": candidate,
                "source_call_hash": suggestion["intent"]["command_hash"],
                "registry_hash": suggestion["registry_hash"],
            },
        )


def _consume_followed(session_id: str, tool_name: str, args: Any) -> Optional[dict[str, Any]]:
    normalized = tool_name.lower().replace(".", "_").replace("-", "_")
    if "lucid" not in normalized or not normalized.endswith("dispatch") or not isinstance(args, dict):
        return None
    session = session_id or "session-unknown"
    with _STATE_LOCK:
        for key, pending in list(_PENDING_CANDIDATES.items()):
            candidate_args = pending["candidate"]["arguments"]
            if key[0] == session and all(args.get(name) == value for name, value in candidate_args.items()):
                _PENDING_CANDIDATES.pop(key)
                return pending
    return None


def _reset_state_for_tests() -> None:
    with _STATE_LOCK:
        _HELD_CALLS.clear()
        _OVERRIDDEN_CALLS.clear()
        _PENDING_CANDIDATES.clear()


def _classify(tool_name: str, args: Any):
    root = _ae_root(args) if isinstance(args, dict) else None
    if not isinstance(args, dict) or root is None:
        return None
    registry = _registry(root)
    if registry is None:
        return None
    classified = _command_intent(tool_name, args, registry, root)
    if classified is None:
        return None
    intent, target = classified
    disposition = _policy_disposition(intent, target)
    if disposition is None:
        return None
    return intent, target, registry, disposition


def _on_pre_tool_call(
    *,
    tool_name: str = "",
    args: Optional[dict[str, Any]] = None,
    session_id: str = "",
    **_: Any,
):
    mode = _mode()
    classified = _classify(tool_name, args)
    if classified is None:
        return None
    intent, target, registry, disposition = classified
    if disposition == "whisper":
        return None
    declaration = target.get("candidate")
    if (
        disposition == "enforce"
        and isinstance(declaration, dict)
        and declaration.get("shape") == "refusal"
    ):
        receipt = _refusal(intent, target, registry)
        encoded = json.dumps(receipt, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        return {
            "action": "block",
            "message": (
                "HARNESS refused Git before execution. QUINE owns repository mutation and history; "
                "Git inspection is also prohibited. Use only bounded LUCID repository search.\n"
                + encoded
            ),
        }
    if mode == "off":
        return None
    if disposition == "hold" and not _hold_once(intent, session_id):
        return None
    decision = "enforce" if disposition == "enforce" else "hold"
    suggestion = _suggestion(
        intent,
        mode,
        target,
        registry,
        decision=decision,
        original_executed=False,
        attempt=1,
    )
    if decision == "hold":
        _remember_candidate(session_id, suggestion)
    encoded = json.dumps(suggestion, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return {
        "action": "block",
        "message": (
            "HARNESS held this noncanonical tool call before execution. "
            "PENGUIN suggestion is authority-none and was deterministically validated; "
            "issue the suggested LUCID call if it matches your intent. Repeating the exact held call once "
            "is treated as an explicit diagnostic override. Disable teaching with "
            f"{_MODE_ENV}=off.\n{encoded}"
        ),
    }


def _on_transform_tool_result(
    tool_name: str = "",
    args: Any = None,
    result: Any = None,
    session_id: str = "",
    **_: Any,
) -> Optional[str]:
    mode = _mode()
    if mode == "off" or not isinstance(result, str):
        return None
    followed = _consume_followed(session_id, tool_name, args)
    if followed is not None:
        receipt = {
            "schema": "penguin-tool-suggestion-trajectory/1",
            "state": "followed",
            "authority": "none",
            "auto_replay": False,
            "candidate_executed": True,
            "source_call_hash": followed["source_call_hash"],
            "registry_hash": followed["registry_hash"],
            "candidate": followed["candidate"],
        }
        encoded = json.dumps(receipt, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        return result + "\n\nPENGUIN teaching trajectory:\n" + encoded
    classified = _classify(tool_name, args)
    if classified is None:
        return None
    intent, target, registry, disposition = classified
    attempt = _consume_override(intent["command_hash"], session_id)
    if attempt is not None:
        decision = "override"
    elif disposition == "whisper":
        decision = "whisper"
        attempt = 1
    else:
        return None
    suggestion = _suggestion(
        intent,
        mode,
        target,
        registry,
        decision=decision,
        original_executed=True,
        attempt=attempt,
    )
    encoded = json.dumps(suggestion, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return result + "\n\nPENGUIN teaching receipt (authority-none; no replay):\n" + encoded


def register(ctx) -> None:
    ctx.register_hook("pre_tool_call", _on_pre_tool_call)
    ctx.register_hook("transform_tool_result", _on_transform_tool_result)
