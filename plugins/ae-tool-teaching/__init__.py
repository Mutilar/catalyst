"""AE PENGUIN authority-none tool-call teaching.

The generated LUCID KX universe classifies source calls and binds one exact
canonical candidate. HARNESS alone owns allow/whisper/hold/enforce policy;
this plugin never executes or replays either call.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import sys
import threading
import time

from collections import OrderedDict
from pathlib import Path
from typing import Any, Optional

SUGGESTION_SCHEMA = "penguin-tool-suggestion/1"
CANDIDATE_SCHEMA = "penguin-tool-suggestion-candidate/1"
_MAX_COMMAND_BYTES = 16_384
_MAX_TRAJECTORIES = 256
_AREA_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")
_SHELL_CONTROL_RE = re.compile(r"[\r\n;&|<>`$()]")
_STATE_LOCK = threading.Lock()
_MISSING = object()
_TRANSFORMS = {
    "identity",
    "singleton-list",
    "repo-relative",
    "repo-relative-list",
    "path-parent",
    "focused-path",
    "registered-area",
    "search-mode",
}
_HELD_CALLS: OrderedDict[tuple[str, str], int] = OrderedDict()
_OVERRIDDEN_CALLS: OrderedDict[tuple[str, str], int] = OrderedDict()
_PENDING_CANDIDATES: OrderedDict[tuple[str, str], dict[str, Any]] = OrderedDict()


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
    value = value or "workspace"
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
        registry = json.loads(
            (root / "envelope/LUCID-TOOL-TEACHING.json").read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, ValueError, TypeError):
        return None
    if (
        not isinstance(registry, dict)
        or registry.get("schema") != "lucid-kx-tool-teaching/1"
        or registry.get("authority") != "none"
        or registry.get("policy_owner") != "HARNESS"
        or registry.get("verbs") != ["show", "get", "set", "morph", "dispatch", "steer", "cancel"]
    ):
        return None
    target_registry = registry.get("target_registry")
    targets = registry.get("targets")
    if (
        not isinstance(target_registry, dict)
        or len(target_registry) != 7
        or not isinstance(targets, list)
        or not targets
        or len(targets) > 128
    ):
        return None
    return registry


def _terminal_executable_policy(registry: dict[str, Any]) -> Optional[dict[str, Any]]:
    policy = registry.get("terminal_executable_policy")
    if not isinstance(policy, dict) or set(policy) != {
        "schema",
        "direct_allow",
        "forbidden_path_segments",
        "unregistered",
    }:
        return None
    direct = policy.get("direct_allow")
    forbidden = policy.get("forbidden_path_segments")
    if (
        policy.get("schema") != "lucid-terminal-executable-policy/1"
        or policy.get("unregistered") != "enforce"
        or direct != ["lucid", "run"]
        or forbidden != [".build", "build", "dist", "out", "target"]
    ):
        return None
    return policy


def _terminal_invocation(args: dict[str, Any]) -> Optional[list[str]]:
    command = args.get("command")
    if (
        not isinstance(command, str)
        or not command
        or len(command.encode("utf-8")) > _MAX_COMMAND_BYTES
        or _SHELL_CONTROL_RE.search(command) is not None
    ):
        return None
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        return None
    invocation = _unwrap_invocation(tokens)
    return invocation or None


def _direct_terminal_executable_allowed(
    args: dict[str, Any], policy: dict[str, Any]
) -> bool:
    invocation = _terminal_invocation(args)
    if invocation is None or any(token in {"&&", "||", ";", "|"} for token in invocation):
        return False
    executable = invocation[0]
    path = Path(executable)
    if path.name != executable or path.is_absolute():
        return False
    if any(part in policy["forbidden_path_segments"] for part in path.parts):
        return False
    return executable in policy["direct_allow"]


def _unregistered_executable_refusal(
    args: dict[str, Any], policy: Optional[dict[str, Any]]
) -> dict[str, Any]:
    invocation = _terminal_invocation(args)
    executable = Path(invocation[0]).name if invocation else "unavailable"
    receipt = {
        "schema": "ae-terminal-executable-refusal/1",
        "state": "refused",
        "reason": "unregistered-executable" if policy is not None else "executable-policy-unavailable",
        "authority": "none",
        "policy_owner": "HARNESS",
        "executed": False,
        "original_executed": False,
        "executable": executable[:96],
        "direct_allow": list(policy["direct_allow"]) if policy is not None else [],
        "policy_hash": _canonical_hash(policy) if policy is not None else None,
    }
    encoded = json.dumps(receipt, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return {
        "action": "block",
        "message": (
            "HARNESS refused an unregistered terminal executable before execution. "
            "Use a registered source command or one canonical direct executable (run or lucid).\n"
            + encoded
        ),
    }


def _canonical_hash(value: Any) -> str:
    canonical = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _argument_shape(value: Any, depth: int = 0) -> Any:
    if depth >= 12:
        return "value"
    if isinstance(value, dict):
        return {
            str(key): _argument_shape(child, depth + 1)
            for key, child in sorted(value.items(), key=lambda item: str(item[0]))[:64]
        }
    if isinstance(value, list):
        return [_argument_shape(child, depth + 1) for child in value[:32]]
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return 1
    if value is None:
        return None
    return "value"


def _call_hash(tool_name: str, args: dict[str, Any], target_id: Any, operation: Any) -> str:
    return _canonical_hash(
        {
            "tool": tool_name,
            "target": target_id,
            "operation": operation,
            "argument_shape": _argument_shape(args),
        }
    )


def _base_intent(
    tool_name: str,
    args: dict[str, Any],
    target: dict[str, Any],
    source: dict[str, Any],
    *,
    area: str,
    focused: bool,
    release: bool,
) -> dict[str, Any]:
    return {
        "tool": tool_name,
        "executable": source.get("executable", tool_name),
        "operation": source.get("operation"),
        "target": target.get("id"),
        "area": area,
        "focused": focused,
        "release": release,
        "call_hash": _call_hash(tool_name, args, target.get("id"), source.get("operation")),
    }


def _argv_intent(
    tool_name: str,
    args: dict[str, Any],
    target: dict[str, Any],
    source: dict[str, Any],
    root: Path,
) -> Optional[dict[str, Any]]:
    if tool_name != "terminal":
        return None
    invocation_tokens = _terminal_invocation(args)
    if not invocation_tokens:
        return None
    prefixes = source.get("argv_prefixes")
    if not isinstance(prefixes, list):
        return None
    prefix = next((prefix for prefix in prefixes if _prefix_matches(invocation_tokens, prefix)), None)
    if prefix is None:
        return None
    invocation = invocation_tokens[len(prefix) :]
    action = source.get("action_token")
    if isinstance(action, str) and action not in invocation:
        return None
    focus_flags = source.get("focus_flags")
    release_flags = source.get("release_flags")
    area_flags = source.get("area_flags")
    if (
        not isinstance(focus_flags, list)
        or not isinstance(release_flags, list)
        or not isinstance(area_flags, list)
    ):
        return None
    focused = any(_flag_present(invocation, flag) for flag in focus_flags)
    area = _workspace_area(root, args)
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
    intent = _base_intent(
        tool_name,
        args,
        target,
        source,
        area=area,
        focused=focused,
        release=any(_flag_present(invocation, flag) for flag in release_flags),
    )
    return intent if _intent_valid(intent) else None


def _typed_intent(
    tool_name: str,
    args: dict[str, Any],
    target: dict[str, Any],
    source: dict[str, Any],
    root: Path,
) -> Optional[dict[str, Any]]:
    if source.get("tool") != tool_name:
        return None
    allowed = source.get("allowed_args")
    required = source.get("required_args")
    if (
        not isinstance(allowed, list)
        or not isinstance(required, list)
        or any(key not in allowed for key in args)
        or any(key not in args for key in required)
        or any(bool(args.get(key)) for key in source.get("reject_truthy", []))
    ):
        return None
    declaration = source.get("intent")
    if not isinstance(declaration, dict):
        return None
    try:
        resolved = _resolve_binding(declaration, {}, args, root)
    except (KeyError, TypeError, ValueError):
        return None
    if (
        not isinstance(resolved, dict)
        or not isinstance(resolved.get("area"), str)
        or not isinstance(resolved.get("focused"), bool)
        or not isinstance(resolved.get("release"), bool)
    ):
        return None
    intent = _base_intent(
        tool_name,
        args,
        target,
        source,
        area=resolved["area"],
        focused=resolved["focused"],
        release=resolved["release"],
    )
    return intent if _intent_valid(intent) else None


def _intent_valid(intent: dict[str, Any]) -> bool:
    return (
        all(
            isinstance(intent.get(key), str) and bool(intent[key])
            for key in ("tool", "executable", "operation", "target", "area", "call_hash")
        )
        and isinstance(intent.get("focused"), bool)
        and isinstance(intent.get("release"), bool)
        and _AREA_RE.fullmatch(intent["area"]) is not None
    )


def _source_intent(
    tool_name: str,
    args: dict[str, Any],
    registry: dict[str, Any],
    root: Path,
) -> Optional[tuple[dict[str, Any], dict[str, Any]]]:
    classifiers = {"argv": _argv_intent, "typed": _typed_intent}
    for target in registry["targets"]:
        if not isinstance(target, dict):
            continue
        source = target.get("source")
        if not isinstance(source, dict) or source.get("tool") != tool_name:
            continue
        kind = source.get("kind")
        classifier = classifiers.get(kind) if isinstance(kind, str) else None
        if classifier is None:
            continue
        intent = classifier(tool_name, args, target, source, root)
        if intent is not None:
            return intent, target
    return None


def _registry_hash(registry: dict[str, Any]) -> str:
    return _canonical_hash(registry)


def _argument_value(args: dict[str, Any], path: str) -> Any:
    value: Any = args
    for segment in path.split("."):
        if not isinstance(value, dict) or segment not in value:
            return _MISSING
        value = value[segment]
    return value


def _repository_relative(value: Any, root: Path) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError("invalid-repository-path")
    path = Path(value).expanduser()
    try:
        if path.is_absolute():
            relative = path.resolve(strict=False).relative_to(root.resolve(strict=True))
        else:
            if ".." in path.parts:
                raise ValueError("repository-path-escape")
            relative = path
    except (OSError, RuntimeError, ValueError) as error:
        raise ValueError("repository-path-escape") from error
    normalized = relative.as_posix()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized or "."


def _transform_value(name: str, value: Any, root: Path) -> Any:
    if name not in _TRANSFORMS:
        raise ValueError("unknown-generated-transform")
    if name == "identity":
        return value
    if name == "singleton-list":
        return [value]
    if name == "repo-relative":
        return _repository_relative(value, root)
    if name == "repo-relative-list":
        return [_repository_relative(value, root)]
    if name == "path-parent":
        relative = _repository_relative(value, root)
        return _area_from(relative, "path-parent") or "workspace"
    if name == "focused-path":
        return _repository_relative(value, root) != "."
    if name == "search-mode":
        modes = {"content": "content", "files": "names"}
        if value not in modes:
            raise ValueError("unregistered-search-mode")
        return modes[value]
    if name == "registered-area":
        if not isinstance(value, str) or not value:
            raise ValueError("unregistered-quality-area")
        path = root / "quine" / "areas.json"
        try:
            if path.is_symlink() or path.stat().st_size > 128 * 1024:
                raise ValueError("unregistered-quality-area")
            areas = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, TypeError, ValueError):
            raise ValueError("unregistered-quality-area") from None
        rows = areas.get("areas") if isinstance(areas, dict) else None
        registered = (
            {
                row["name"]
                for row in rows
                if isinstance(row, dict) and isinstance(row.get("name"), str)
            }
            if isinstance(rows, list)
            else set()
        )
        candidate = value.replace("\\", "/").strip("/").split("/", 1)[0]
        if candidate not in registered:
            raise ValueError("unregistered-quality-area")
        return candidate
    raise ValueError("unknown-generated-transform")


def _resolve_binding(
    binding: Any,
    intent: dict[str, Any],
    args: dict[str, Any],
    root: Path,
) -> Any:
    if isinstance(binding, list):
        resolved = [_resolve_binding(value, intent, args, root) for value in binding]
        return [value for value in resolved if value is not _MISSING]
    if not isinstance(binding, dict):
        raise ValueError("unbound-generated-value")
    keys = set(binding)
    if keys == {"$const"}:
        return binding["$const"]
    if "$intent" in binding and keys <= {"$intent", "$transform"}:
        name = binding["$intent"]
        if not isinstance(name, str) or name not in intent:
            raise KeyError(name)
        value = intent[name]
    elif "$arg" in binding and keys <= {"$arg", "$default", "$transform"}:
        name = binding["$arg"]
        if not isinstance(name, str):
            raise ValueError("invalid-generated-argument")
        value = _argument_value(args, name)
        if value is _MISSING:
            value = binding.get("$default", _MISSING)
        if value is _MISSING:
            return _MISSING
    elif not any(key.startswith("$") for key in binding):
        resolved = {
            key: _resolve_binding(value, intent, args, root)
            for key, value in binding.items()
        }
        return {key: value for key, value in resolved.items() if value is not _MISSING}
    else:
        raise ValueError("unknown-generated-binding")
    transform = binding.get("$transform", "identity")
    if not isinstance(transform, str):
        raise ValueError("invalid-generated-transform")
    return _transform_value(transform, value, root)


def _heuristic_candidate(
    intent: dict[str, Any],
    args: dict[str, Any],
    target: dict[str, Any],
    root: Path,
) -> dict[str, Any]:
    declaration = target.get("compiled")
    if not isinstance(declaration, dict) or declaration.get("kind") != "call":
        raise ValueError("unregistered-candidate-kind")
    arguments = _resolve_binding(declaration.get("arguments"), intent, args, root)
    if not isinstance(arguments, dict) or not arguments:
        raise ValueError("empty-generated-arguments")
    target_identity = declaration.get("target")
    explanation = declaration.get("explanation")
    if isinstance(target_identity, dict) and target_identity.get("id") == "run-qualification":
        area = arguments.get("area")
        if not isinstance(area, str) or not area:
            raise ValueError("quality-area-missing")
        operation = arguments.get("operation")
        if operation not in {"test", "lint", "line_coverage", "branch_coverage"}:
            operation = "test"
        arguments = {"area": area, "operation": operation}
        explanation = f"Use LUCID DISPATCH {operation.upper()} {area.upper()}."
    return {
        "schema": CANDIDATE_SCHEMA,
        "tool": declaration.get("tool"),
        "verb": declaration.get("verb"),
        "target": declaration.get("target"),
        "arguments": arguments,
        "explanation": explanation,
        "syntax": {"tool": declaration.get("tool"), "arguments": arguments},
    }


def _candidate_valid(candidate: Any, registry: dict[str, Any]) -> bool:
    if not isinstance(candidate, dict) or set(candidate) != {
        "schema",
        "tool",
        "verb",
        "target",
        "arguments",
        "explanation",
        "syntax",
    }:
        return False
    verb = candidate.get("verb")
    target = candidate.get("target")
    arguments = candidate.get("arguments")
    explanation = candidate.get("explanation")
    if (
        candidate.get("schema") != CANDIDATE_SCHEMA
        or candidate.get("tool") != f"mcp__LUCID__{verb}"
        or not isinstance(target, dict)
        or set(target) != {"registry", "id"}
        or not isinstance(arguments, dict)
        or not arguments
        or len(arguments) > 32
        or not isinstance(explanation, str)
        or not explanation
        or len(explanation) > 512
        or candidate.get("syntax") != {"tool": candidate["tool"], "arguments": arguments}
    ):
        return False
    join = registry["target_registry"].get(target.get("registry"))
    return isinstance(join, dict) and join.get("verb") == verb


def _suggestion(
    intent: dict[str, Any],
    source_args: dict[str, Any],
    target: dict[str, Any],
    registry: dict[str, Any],
    root: Path,
    *,
    decision: str,
    original_executed: bool,
    attempt: int,
) -> dict[str, Any]:
    candidate = _heuristic_candidate(intent, source_args, target, root)
    valid = _candidate_valid(candidate, registry)
    if not valid:
        raise ValueError("generated-candidate-invalid")
    return {
        "schema": SUGGESTION_SCHEMA,
        "state": "validated",
        "decision": decision,
        "source": "generated",
        "authority": "none",
        "executed": False,
        "auto_replay": False,
        "original_executed": original_executed,
        "mode": "generated",
        "registry_hash": _registry_hash(registry),
        "intent": intent,
        "candidate": candidate,
        "preflight": {"valid": True, "validator": "AE deterministic tool suggestion preflight"},
        "trajectory": {"state": decision, "attempt": attempt},
        "fallback": None,
    }


def _refusal(
    intent: dict[str, Any],
    source_args: dict[str, Any],
    target: dict[str, Any],
    registry: dict[str, Any],
    root: Path,
) -> dict[str, Any]:
    declaration = target.get("compiled")
    if not isinstance(declaration, dict) or declaration.get("kind") != "refusal":
        raise ValueError("unregistered-refusal-shape")
    alternative = declaration["alternative"]
    arguments = _resolve_binding(alternative["arguments"], intent, source_args, root)
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
            "kind": "lucid-search",
            "tool": alternative["tool"],
            "verb": alternative["verb"],
            "target": alternative["target"],
            "arguments": arguments,
            "constraint": "explicit search terms are required; Git repository/history access remains prohibited",
        },
    }


def _policy_disposition(intent: dict[str, Any], target: dict[str, Any]) -> Optional[str]:
    policy = target.get("policy")
    if not isinstance(policy, dict):
        return None
    disposition = (
        policy.get("release")
        if intent["release"]
        else policy.get("focused")
        if intent["focused"]
        else policy.get("workspace")
    )
    return disposition if disposition in {"allow", "whisper", "hold", "enforce"} else None


def _bounded_put(mapping: OrderedDict, key: Any, value: Any) -> None:
    mapping[key] = value
    mapping.move_to_end(key)
    while len(mapping) > _MAX_TRAJECTORIES:
        mapping.popitem(last=False)


def _hold_once(intent: dict[str, Any], session_id: str) -> bool:
    key = (session_id or "session-unknown", intent["call_hash"])
    with _STATE_LOCK:
        if key in _HELD_CALLS:
            attempt = _HELD_CALLS.pop(key) + 1
            _bounded_put(_OVERRIDDEN_CALLS, key, attempt)
            return False
        _bounded_put(_HELD_CALLS, key, 1)
        return True


def _consume_override(call_hash: str, session_id: str) -> Optional[int]:
    key = (session_id or "session-unknown", call_hash)
    with _STATE_LOCK:
        return _OVERRIDDEN_CALLS.pop(key, None)


def _remember_candidate(session_id: str, suggestion: dict[str, Any]) -> None:
    candidate = suggestion["candidate"]
    key = (session_id or "session-unknown", _canonical_hash(candidate))
    with _STATE_LOCK:
        _bounded_put(
            _PENDING_CANDIDATES,
            key,
            {
                "candidate": candidate,
                "source_call_hash": suggestion["intent"]["call_hash"],
                "registry_hash": suggestion["registry_hash"],
            },
        )


def _consume_followed(session_id: str, tool_name: str, args: Any) -> Optional[dict[str, Any]]:
    normalized = tool_name.lower().replace(".", "_").replace("-", "_")
    if not isinstance(args, dict):
        return None
    session = session_id or "session-unknown"
    with _STATE_LOCK:
        for key, pending in list(_PENDING_CANDIDATES.items()):
            candidate = pending["candidate"]
            expected_tool = candidate["tool"].lower().replace(".", "_").replace("-", "_")
            if key[0] == session and normalized == expected_tool and args == candidate["arguments"]:
                _PENDING_CANDIDATES.pop(key)
                return pending
    return None


def _emit_teaching_event(pending: dict[str, Any], outcome: str, succeeded: bool) -> None:
    candidate = pending.get("candidate")
    if not isinstance(candidate, dict):
        return
    target = candidate.get("target")
    verb = candidate.get("verb")
    candidate_hash = _canonical_hash(candidate)
    request_identity = pending.get("source_call_hash")
    registry_hash = pending.get("registry_hash")
    if (
        not isinstance(target, dict)
        or not isinstance(target.get("id"), str)
        or not isinstance(verb, str)
        or not isinstance(request_identity, str)
        or not isinstance(registry_hash, str)
    ):
        return
    event = {
        "schema": "penguin-suggestion-outcome/1",
        "reasoning_retained": False,
        "source_class": "local-observation",
        "observed_epoch_bucket": max(1, int(time.time()) // 60 * 60),
        "teaching_episode": _canonical_hash(
            {
                "candidate_hash": candidate_hash,
                "request_identity": request_identity,
                "registry_hash": registry_hash,
            }
        ),
        "candidate_hash": candidate_hash,
        "request_identity": request_identity,
        "verb": verb,
        "target": target["id"],
        "matched_candidate": outcome in {"followed", "rejected"},
        "outcome": outcome,
        "succeeded": succeeded,
        "authority": "none",
        "auto_replay": False,
    }
    sys.stderr.write(
        "PENGUIN_TEACHING_EVENT "
        + json.dumps(event, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    )
    sys.stderr.flush()


def _emit_intent_event(
    tool_name: str,
    args: dict[str, Any],
    classified: Optional[tuple],
) -> None:
    intent = classified[0] if classified is not None else None
    target = classified[1] if classified is not None else None
    operation = intent.get("operation") if isinstance(intent, dict) else None
    target_id = target.get("id") if isinstance(target, dict) else None
    event = {
        "schema": "penguin-tool-intent-observed/1",
        "source_class": "local-observation",
        "observed_epoch_bucket": max(1, int(time.time()) // 60 * 60),
        "request_identity": (
            intent["call_hash"]
            if isinstance(intent, dict)
            else _call_hash(tool_name, args, target_id, operation)
        ),
        "tool_family": tool_name.lower().replace(".", "_").replace("-", "_")[:64],
        "classification": "registered" if classified is not None else "unregistered",
        "target": target_id,
        "operation": operation,
        "result_body_stored": False,
        "authority": "none",
    }
    sys.stderr.write(
        "PENGUIN_TEACHING_EVENT "
        + json.dumps(event, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    )
    sys.stderr.flush()


def _on_session_end(session_id: str = "", **_: Any) -> None:
    session = session_id or "session-unknown"
    pending = []
    with _STATE_LOCK:
        for key, value in list(_PENDING_CANDIDATES.items()):
            if key[0] == session:
                pending.append(_PENDING_CANDIDATES.pop(key))
    for value in pending:
        _emit_teaching_event(value, "ignored", False)


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
    classified = _source_intent(tool_name, args, registry, root)
    if classified is None:
        return None
    intent, target = classified
    disposition = _policy_disposition(intent, target)
    if disposition is None:
        return None
    return intent, target, registry, disposition, root


def _on_pre_tool_call(
    *,
    tool_name: str = "",
    args: Optional[dict[str, Any]] = None,
    session_id: str = "",
    **_: Any,
):
    classified = _classify(tool_name, args)
    root = _ae_root(args) if isinstance(args, dict) else None
    registry = _registry(root) if root is not None else None
    if isinstance(args, dict):
        known_source = isinstance(registry, dict) and any(
            isinstance(target, dict)
            and isinstance(target.get("source"), dict)
            and target["source"].get("tool") == tool_name
            for target in registry.get("targets", [])
        )
        if known_source:
            _emit_intent_event(tool_name, args, classified)
    if tool_name == "terminal" and isinstance(args, dict) and root is not None:
        policy = _terminal_executable_policy(registry) if isinstance(registry, dict) else None
        if classified is None:
            if policy is not None and _direct_terminal_executable_allowed(args, policy):
                return None
            return _unregistered_executable_refusal(args, policy)
    if classified is None or not isinstance(args, dict):
        return None
    intent, target, registry, disposition, root = classified
    if disposition in {"allow", "whisper"}:
        return None
    declaration = target.get("compiled")
    if disposition == "enforce" and isinstance(declaration, dict) and declaration.get("kind") == "refusal":
        receipt = _refusal(intent, args, target, registry, root)
        encoded = json.dumps(receipt, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        return {
            "action": "block",
            "message": "HARNESS refused this prohibited source call before execution.\n" + encoded,
        }
    if disposition == "hold" and not _hold_once(intent, session_id):
        return None
    decision = "enforce" if disposition == "enforce" else "hold"
    try:
        suggestion = _suggestion(
            intent,
            args,
            target,
            registry,
            root,
            decision=decision,
            original_executed=False,
            attempt=1,
        )
    except (KeyError, TypeError, ValueError):
        return None
    _remember_candidate(session_id, suggestion)
    encoded = json.dumps(suggestion, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return {
        "action": "block",
        "message": (
            "HARNESS held this noncanonical tool call before execution. "
            "The generated PENGUIN suggestion is authority-none and has not executed or replayed either call. "
            "Issue the exact suggested LUCID tool and complete arguments only if they match the intent.\n"
            + encoded
        ),
    }


def _tool_outcome(status: str, result: str) -> str:
    if status in {"blocked", "refused"}:
        return "refusal"
    if status not in {"ok", "success"}:
        return "failure"
    try:
        value = json.loads(result)
    except (TypeError, ValueError):
        return "success"
    if not isinstance(value, dict):
        return "success"
    if value.get("refusal") or value.get("error"):
        return "refusal" if value.get("refusal") else "failure"
    structured = value.get("structuredContent")
    if not isinstance(structured, dict):
        structured = value
    if structured.get("refusal"):
        return "refusal"
    state = structured.get("state")
    if state in {"refused", "blocked"}:
        return "refusal"
    if state in {"🔴", "⚠️", "failed", "failure", "error", "degraded", "stale", "unavailable"}:
        return "failure"
    return "success"


def _on_transform_tool_result(
    tool_name: str = "",
    args: Any = None,
    result: Any = None,
    session_id: str = "",
    status: str = "",
    **_: Any,
) -> Optional[str]:
    if not isinstance(result, str):
        return None
    followed = _consume_followed(session_id, tool_name, args)
    if followed is not None:
        outcome = _tool_outcome(status, result)
        receipt = {
            "schema": "penguin-tool-suggestion-trajectory/1",
            "state": "followed",
            "authority": "none",
            "auto_replay": False,
            "candidate_executed": True,
            "outcome": outcome,
            "succeeded": outcome == "success",
            "source_call_hash": followed["source_call_hash"],
            "registry_hash": followed["registry_hash"],
            "candidate": followed["candidate"],
        }
        _emit_teaching_event(
            followed,
            "followed" if outcome == "success" else "rejected",
            outcome == "success",
        )
        encoded = json.dumps(receipt, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        return result + "\n\nPENGUIN teaching trajectory:\n" + encoded
    classified = _classify(tool_name, args)
    if classified is None:
        return None
    intent, target, registry, disposition, root = classified
    attempt = _consume_override(intent["call_hash"], session_id)
    if attempt is not None:
        decision = "override"
    elif disposition == "whisper":
        decision = "whisper"
        attempt = 1
    else:
        return None
    try:
        suggestion = _suggestion(
            intent,
            args,
            target,
            registry,
            root,
            decision=decision,
            original_executed=True,
            attempt=attempt,
        )
    except (KeyError, TypeError, ValueError):
        return None
    _remember_candidate(session_id, suggestion)
    encoded = json.dumps(suggestion, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return result + "\n\nPENGUIN teaching receipt (authority-none; no replay):\n" + encoded


def register(ctx) -> None:
    ctx.register_hook("pre_tool_call", _on_pre_tool_call)
    ctx.register_hook("transform_tool_result", _on_transform_tool_result)
    ctx.register_hook("on_session_end", _on_session_end)
