"""AE final-response attestation guard.

The plugin is inert outside an AgentExperiments checkout. It derives the exact
terminal suffix from the live host-owned LUCID role decision and QUINE's
canonical role registry; prompt prose and model claims are never authority.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sys
import threading
from pathlib import Path
from typing import Any, Optional

_ROLE_DECISION = Path("run/state/runtime/lucid-host-role.json")
_ROLE_REGISTRY = Path("quine/canon/roles.json")
_WITNESS_REGISTRY = Path("quine/author-glyphs.json")
_HARNESS = Path("envelope/HARNESS.json")
_ONBOARDING_INDEX = Path("quine/mcp/onboarding/index.json")
_ONBOARDING_DIRECTORY = Path("quine/mcp/onboarding")
_MAX_DECISION_BYTES = 4096
_MAX_REGISTRY_BYTES = 64 * 1024
_MAX_HARNESS_BYTES = 128 * 1024
_MAX_INDEX_BYTES = 64 * 1024
_MAX_ONBOARDING_BYTES = 512 * 1024
_STATE_LOCK = threading.Lock()
_SIGNED_OUT_SESSIONS: set[str] = set()
_SPOKEN_FINALS: set[tuple[str, str]] = set()
_MAX_FINAL_SPEECH_BYTES = 65_536
logger = logging.getLogger(__name__)


def _read_regular_json(path: Path, maximum_bytes: int) -> Optional[dict[str, Any]]:
    try:
        metadata = path.lstat()
        if path.is_symlink() or not path.is_file() or metadata.st_size > maximum_bytes:
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def _role_attestation(
    workspace_root: str | os.PathLike[str],
) -> Optional[tuple[Path, str, str, str, str, str]]:
    try:
        root = Path(workspace_root).expanduser().resolve(strict=True)
    except (OSError, RuntimeError, TypeError, ValueError):
        return None
    decision = _read_regular_json(root / _ROLE_DECISION, _MAX_DECISION_BYTES)
    registry = _read_regular_json(root / _ROLE_REGISTRY, _MAX_REGISTRY_BYTES)
    witnesses = _read_regular_json(root / _WITNESS_REGISTRY, _MAX_REGISTRY_BYTES)
    if not decision or not registry or not witnesses:
        return None
    if decision.get("schema") != "lucid-host-role-decision/1":
        return None
    if registry.get("$schema") != "ae-roles/1":
        return None
    role = decision.get("role")
    roles = registry.get("roles")
    if not isinstance(role, str) or not isinstance(roles, dict):
        return None
    definition = roles.get(role)
    authors = witnesses.get("authors")
    if (
        not isinstance(definition, dict)
        or witnesses.get("schema") != "ae-author-glyphs/1"
        or not isinstance(authors, dict)
        or not authors
    ):
        return None
    role_hat = definition.get("hat")
    role_hats = [candidate.get("hat") for candidate in roles.values() if isinstance(candidate, dict)]
    if (
        not isinstance(role_hat, str)
        or not role_hat
        or len(role_hat) > 16
        or any(character.isspace() or character.isascii() for character in role_hat)
        or role_hats.count(role_hat) != 1
    ):
        return None
    witness_alias = decision.get("witness_alias")
    if witness_alias is None and len(authors) == 1:
        witness_alias = next(iter(authors))
    witness_glyph = authors.get(witness_alias) if isinstance(witness_alias, str) else None
    if (
        not isinstance(witness_alias, str)
        or not isinstance(witness_glyph, str)
        or not witness_glyph
        or len(witness_glyph) > 16
        or any(character.isspace() or character.isascii() for character in witness_glyph)
        or decision.get("witness_glyph") not in (None, witness_glyph)
    ):
        return None
    suffix = f"{role_hat}{witness_glyph}"
    # The committed glyph is a convenience/default projection. Runtime attestation composes the
    # permanent role hat with the active WITNESS, which may differ from that default.
    if not any(definition.get("glyph") == f"{role_hat}{glyph}" for glyph in authors.values()):
        return None
    return root, role, role_hat, witness_alias, witness_glyph, suffix


def required_terminal_suffix(workspace_root: str | os.PathLike[str]) -> Optional[str]:
    attestation = _role_attestation(workspace_root)
    return attestation[5] if attestation is not None else None


def _finalization_contract(root: Path) -> Optional[dict[str, Any]]:
    harness = _read_regular_json(root / _HARNESS, _MAX_HARNESS_BYTES)
    finalization = harness.get("finalization") if isinstance(harness, dict) else None
    if (
        not isinstance(finalization, dict)
        or finalization.get("schema") != "ae-harness-finalization/1"
        or finalization.get("policy_owner") != "CATALYST"
        or finalization.get("modality") != "gestalt"
        or finalization.get("grammar") != "lucid-gestalt/1"
    ):
        return None
    attestation = finalization.get("attestation")
    signals = attestation.get("canonical_signals") if isinstance(attestation, dict) else None
    if (
        not isinstance(attestation, dict)
        or attestation.get("schema") != "ae-final-attestation/1"
        or attestation.get("persistent_role_hats") != "quine/canon/roles.json#/roles/*/hat"
        or attestation.get("engineer_hats") != "quine/canon/hats.json#/hats"
        or attestation.get("engineer_max_hats") != 10
        or attestation.get("witness_registry") != "quine/author-glyphs.json"
        or attestation.get("minimum_signals") != 1
        or not isinstance(signals, list)
        or signals != ["🟢", "⏳", "⚠️", "🔴", "🔎", "◆", "➡️"]
    ):
        return None
    attempts = finalization.get("attempts")
    terminal = finalization.get("terminal")
    if (
        not isinstance(attempts, list)
        or len(attempts) != 2
        or [attempt.get("attempt") for attempt in attempts if isinstance(attempt, dict)] != [0, 1]
        or [attempt.get("action") for attempt in attempts if isinstance(attempt, dict)]
        != ["reinject-onboarding", "signout"]
        or not isinstance(terminal, dict)
        or terminal.get("state") != "offline"
        or terminal.get("resume_authority") != "WITNESS"
        or terminal.get("automatic_signin") is not False
        or terminal.get("automatic_recover") is not False
    ):
        return None
    return finalization


def _onboarding_resources(root: Path, role: str, attempt: dict[str, Any]) -> Optional[str]:
    index = _read_regular_json(root / _ONBOARDING_INDEX, _MAX_INDEX_BYTES)
    rows = index.get("resources") if isinstance(index, dict) else None
    requested = attempt.get("resources")
    labels = attempt.get("section_labels")
    if not isinstance(rows, list) or not isinstance(requested, list) or not isinstance(labels, dict):
        return None
    by_uri = {
        row.get("uri"): row
        for row in rows
        if isinstance(row, dict)
        and isinstance(row.get("uri"), str)
        and isinstance(row.get("path"), str)
    }
    role_lower = role.lower()
    sections = []
    for index, template in enumerate(requested):
        if not isinstance(template, str):
            return None
        uri = template.format(role_lower=role_lower)
        row = by_uri.get(uri)
        if not isinstance(row, dict):
            return None
        relative = Path(row["path"])
        if relative.is_absolute() or len(relative.parts) != 1:
            return None
        path = root / _ONBOARDING_DIRECTORY / relative
        try:
            metadata = path.lstat()
            if path.is_symlink() or not path.is_file() or metadata.st_size > _MAX_ONBOARDING_BYTES:
                return None
            content = path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            return None
        label_key = "universal" if index == 0 else "role"
        label = labels.get(label_key)
        if not isinstance(label, str) or not label:
            return None
        sections.append(f"{label.format(role=role)}\n{content}")
    return "\n\n".join(sections)


def _render_attempt(
    root: Path,
    role: str,
    suffix: str,
    cause: str,
    attempt: dict[str, Any],
) -> Optional[str]:
    gestalt = attempt.get("gestalt")
    if not isinstance(gestalt, str) or not gestalt:
        return None
    signout_arguments = json.dumps(
        attempt.get("arguments"), ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    rendered = gestalt.format(
        role=role,
        role_lower=role.lower(),
        suffix=suffix,
        cause=cause,
        signout_arguments=signout_arguments,
    )
    if attempt.get("action") == "reinject-onboarding":
        onboarding = _onboarding_resources(root, role, attempt)
        if onboarding is None:
            return None
        rendered = f"{rendered}\n\n{onboarding}"
    return rendered


def _attestation_failure(
    final_response: str,
    identity: tuple[Path, str, str, str, str, str],
    finalization: dict[str, Any],
) -> Optional[str]:
    _, _, role_hat, _, witness_glyph, suffix = identity
    terminal = final_response.rstrip("\r\n")
    terminal_line = terminal.rsplit("\n", 1)[-1]
    if terminal_line != suffix:
        witness_registry = _read_regular_json(identity[0] / _WITNESS_REGISTRY, _MAX_REGISTRY_BYTES)
        authors = witness_registry.get("authors") if isinstance(witness_registry, dict) else None
        witness_glyphs = tuple(
            glyph for glyph in (authors or {}).values() if isinstance(glyph, str) and glyph
        )
        if witness_glyphs and terminal_line.endswith(witness_glyphs) and not terminal_line.endswith(witness_glyph):
            return "witness-glyph-mismatch"
        if terminal_line.endswith(witness_glyph) and terminal_line != f"{role_hat}{witness_glyph}":
            return "role-hat-mismatch"
        return "terminal-attestation-missing"
    body = terminal[: -len(suffix)]
    policy = finalization["attestation"]
    signals = policy["canonical_signals"]
    if sum(body.count(signal) for signal in signals) < policy["minimum_signals"]:
        return "canonical-gestalt-signal-missing"
    return None


def _pre_final(
    *,
    final_response: str = "",
    workspace_root: str = "",
    attempt: int = 0,
    session_id: str = "",
    **_: Any,
) -> Optional[dict[str, str]]:
    if attempt < 0 or not isinstance(final_response, str) or not final_response.strip():
        return None
    attestation = _role_attestation(workspace_root)
    if attestation is None:
        return None
    root, role, _, _, _, suffix = attestation
    finalization = _finalization_contract(root)
    if finalization is None:
        return None
    cause = _attestation_failure(final_response, attestation, finalization)
    attempts = finalization["attempts"]
    if attempt >= len(attempts):
        with _STATE_LOCK:
            signed_out = bool(session_id) and session_id in _SIGNED_OUT_SESSIONS
        if not signed_out:
            selected = attempts[1]
            message = _render_attempt(root, role, suffix, "repeated-role-protocol-drift", selected)
            return {"action": "continue", "message": message} if message is not None else None
        terminal = finalization["terminal"]
        message = terminal.get("gestalt")
        if not isinstance(message, str) or not message:
            return None
        return {"action": "block", "message": message}
    if cause is None:
        return None
    selected = attempts[attempt]
    if not isinstance(selected, dict):
        return None
    message = _render_attempt(root, role, suffix, cause, selected)
    if message is None:
        return None
    return {
        "action": "continue",
        "message": message,
    }


def _submit_effigy_speech(arguments: dict[str, Any]) -> dict[str, Any]:
    from tools.mcp_tool import invoke_registered_mcp_tool

    return invoke_registered_mcp_tool("LUCID", "show", arguments, timeout=10.0)


def _effigy_submission_accepted(result: Any) -> bool:
    if not isinstance(result, dict) or result.get("error") or result.get("isError") is True:
        return False
    candidates = [result.get("model"), result.get("result")]
    presentation = result.get("presentation")
    if isinstance(presentation, dict):
        candidates.extend(
            [
                presentation.get("__hermes_model_visible_result"),
                presentation.get("result"),
            ]
        )
    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        if (
            candidate.startswith("🟢 LUCID · show · text · fresh")
            and "Presentation Audio Accepted=true" in candidate
            and "Presentation Audio Status=accepted" in candidate
            and "Presentation Audio Code=speech-queued" in candidate
        ):
            return True
    structured = result.get("structuredContent")
    return (
        isinstance(structured, dict)
        and structured.get("accepted") is True
        and structured.get("status") == "accepted"
        and structured.get("code") == "speech-queued"
    )


def _bounded_effigy_detail(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    detail = " ".join(value.replace("\0", " ").split()).strip()
    if not detail:
        return None
    detail = re.sub(
        r"(?i)(bearer|token|secret|password)(\s*[:=]\s*)\S+",
        r"\1\2[redacted]",
        detail,
    )
    return detail[:256]


def _effigy_failure_fields(
    result: Any,
    cause: Optional[BaseException] = None,
) -> tuple[str, str, str]:
    stage = "submission"
    code = "effigy-submission-failed"
    if cause is not None:
        detail = _bounded_effigy_detail(str(cause)) or "submission raised without an error message"
        return stage, code, f"{type(cause).__name__}: {detail}"
    if not isinstance(result, dict):
        return stage, code, "LUCID returned no typed submission result"
    candidates = [result.get("model"), result.get("result")]
    presentation = result.get("presentation")
    containers = [result]
    if isinstance(presentation, dict):
        containers.append(presentation)
        candidates.extend(
            [
                presentation.get("__hermes_model_visible_result"),
                presentation.get("result"),
            ]
        )
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        containers.append(structured)
    detail = next(
        (
            bounded
            for container in containers
            for key in ("detail", "error", "reason", "message")
            if (bounded := _bounded_effigy_detail(container.get(key))) is not None
        ),
        None,
    )
    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        for line in candidate.splitlines():
            if line.startswith("Presentation Audio Effigy Transfer Code="):
                code = line.split("=", 1)[1].strip()[:96] or code
                stage = "effigy-transfer"
            elif line.startswith("Presentation Audio Code=") and stage == "submission":
                code = line.split("=", 1)[1].strip()[:96] or code
            elif line.startswith("Presentation Audio Stage="):
                stage = line.split("=", 1)[1].strip()[:64] or stage
            elif "Detail=" in line and detail is None:
                detail = _bounded_effigy_detail(line.split("Detail=", 1)[1])
            elif "Error=" in line and detail is None:
                detail = _bounded_effigy_detail(line.split("Error=", 1)[1])
    return stage, code, detail or "LUCID returned a refusal without a typed failure detail"


def _emit_effigy_warning(
    _role: str,
    role_glyph: str,
    result: Any,
    cause: Optional[BaseException] = None,
) -> tuple[str, str, str]:
    stage, code, detail = _effigy_failure_fields(result, cause)
    print(
        f"⚠️ {role_glyph} · 🔎 {code} · {stage}: {detail}",
        file=sys.stderr,
        flush=True,
    )
    return stage, code, detail


def _post_final(
    *,
    final_response: str = "",
    workspace_root: str = "",
    session_id: str = "",
    **_: Any,
) -> Optional[dict[str, str]]:
    """Submit one attested final through the current role's EFFIGY speech profile."""

    if not isinstance(final_response, str) or not final_response.strip():
        return None
    attestation = _role_attestation(workspace_root)
    if attestation is None:
        return None
    root, role, _, _, _, suffix = attestation
    finalization = _finalization_contract(root)
    if finalization is None or _attestation_failure(final_response, attestation, finalization) is not None:
        return None
    encoded = final_response.encode("utf-8")
    if len(encoded) > _MAX_FINAL_SPEECH_BYTES:
        return {"state": "omitted", "code": "response-final-oversized"}
    digest = hashlib.sha256(encoded).hexdigest()
    identity_scope = session_id or f"workspace:{root}:{role}"
    identity = (identity_scope, digest)
    with _STATE_LOCK:
        if session_id in _SIGNED_OUT_SESSIONS or identity in _SPOKEN_FINALS:
            return None
        _SPOKEN_FINALS.add(identity)
    arguments = {
        "kind": "text",
        "data": {"schema": "response-final/1", "text": final_response},
        "presentation": "audio-only",
        "scope": "this",
    }
    try:
        result = _submit_effigy_speech(arguments)
    except Exception as exc:
        with _STATE_LOCK:
            _SPOKEN_FINALS.discard(identity)
        stage, code, detail = _emit_effigy_warning(role, suffix, None, exc)
        logger.warning(
            "Attested %s final EFFIGY submission raised stage=%s code=%s detail=%s",
            role,
            stage,
            code,
            detail,
            exc_info=True,
        )
        return {"state": "degraded", "code": code}
    if not _effigy_submission_accepted(result):
        with _STATE_LOCK:
            _SPOKEN_FINALS.discard(identity)
        stage, code, detail = _emit_effigy_warning(role, suffix, result)
        logger.warning(
            "Attested %s final EFFIGY submission failed stage=%s code=%s detail=%s",
            role,
            stage,
            code,
            detail,
        )
        return {"state": "degraded", "code": code}
    return {"state": "submitted", "code": "effigy-response-final-submitted"}


def _contains_signout(value: Any, depth: int = 0) -> bool:
    if depth > 10:
        return False
    if isinstance(value, dict):
        if value.get("state") == "signout" or value.get("action") == "signout":
            return True
        return any(_contains_signout(child, depth + 1) for child in value.values())
    if isinstance(value, list):
        return any(_contains_signout(child, depth + 1) for child in value)
    return False


def _transform_tool_result(
    *,
    tool_name: str = "",
    args: Any = None,
    result: Any = None,
    session_id: str = "",
    status: str = "",
    **_: Any,
) -> None:
    if (
        tool_name != "mcp__LUCID__set"
        or args
        != {
            "path": "role-session",
            "scope": "this",
            "value": {"action": "signout"},
        }
        or status not in {"ok", "success"}
        or not isinstance(result, str)
        or not session_id
    ):
        return None
    try:
        value = json.loads(result)
    except (TypeError, ValueError):
        return None
    if isinstance(value, dict) and not value.get("error") and not value.get("refusal"):
        if _contains_signout(value):
            with _STATE_LOCK:
                _SIGNED_OUT_SESSIONS.add(session_id)
    return None


def _on_session_end(*, session_id: str = "", **_: Any) -> None:
    if session_id:
        with _STATE_LOCK:
            _SIGNED_OUT_SESSIONS.discard(session_id)
            stale = {
                identity for identity in _SPOKEN_FINALS if identity[0] == session_id
            }
            _SPOKEN_FINALS.difference_update(stale)


def register(ctx) -> None:
    ctx.register_hook("pre_final", _pre_final)
    ctx.register_hook("post_final", _post_final)
    ctx.register_hook("transform_tool_result", _transform_tool_result)
    ctx.register_hook("on_session_end", _on_session_end)
