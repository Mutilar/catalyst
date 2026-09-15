"""AE final-response attestation guard.

The plugin is inert outside an AgentExperiments checkout. It derives the exact
terminal suffix from the live host-owned LUCID role decision and QUINE's
canonical role registry; prompt prose and model claims are never authority.
"""

from __future__ import annotations
from agent.generated.ae_glyphs import (
    DELIMITER_SEGMENT,
    IDENTITY_CATALYST,
    IDENTITY_QUINE,
    RELATION_DATUM,
    RELATION_EVIDENCE,
    SIGNAL_GREEN,
    SIGNAL_PENDING,
    SIGNAL_RED,
    SIGNAL_WARNING,
)

import hashlib
import json
import logging
import os
import re
import sys
import threading
from pathlib import Path
from typing import Any, Optional

from hermes_gestalt import canonical_stream, parse_stream, semantic_action

_ROLE_DECISION = Path("run/state/runtime/lucid-host-role.json")
_ROLE_REGISTRY = Path("quine/canon/roles.json")
_WITNESS_REGISTRY = Path("quine/author-glyphs.json")
_HARNESS = Path("envelope/HARNESS.json")
_ONBOARDING_INDEX = Path("quine/mcp/onboarding/index.json")
_ONBOARDING_DIRECTORY = Path("quine/mcp/onboarding")
_GESTALT_ROOT = Path(__file__).resolve().parents[3]
_MAX_DECISION_BYTES = 4096
_MAX_REGISTRY_BYTES = 64 * 1024
_MAX_HARNESS_BYTES = 128 * 1024
_MAX_INDEX_BYTES = 64 * 1024
_MAX_ONBOARDING_BYTES = 512 * 1024
_STATE_LOCK = threading.Lock()
_SIGNED_OUT_SESSIONS: set[str] = set()
_LIVE_LIFECYCLE_SESSIONS: set[str] = set()
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
    return root, role, role_hat, witness_alias, witness_glyph, suffix


def required_terminal_suffix(workspace_root: str | os.PathLike[str]) -> Optional[str]:
    attestation = _role_attestation(workspace_root)
    return attestation[5] if attestation is not None else None


def _effective_attestation(
    workspace_root: str | os.PathLike[str],
    agent_role: str,
) -> Optional[tuple[Path, str, str, str, str, str]]:
    if agent_role != "PENGUIN":
        return _role_attestation(workspace_root)
    root = _ae_workspace_root(workspace_root)
    if root is None:
        return None
    registry = _read_regular_json(root / _ROLE_REGISTRY, _MAX_REGISTRY_BYTES)
    if not registry or registry.get("$schema") != "ae-roles/1":
        return None
    roles = registry.get("roles") if isinstance(registry, dict) else None
    definition = roles.get("PENGUIN") if isinstance(roles, dict) else None
    role_hat = definition.get("hat") if isinstance(definition, dict) else None
    role_hats = [
        candidate.get("hat")
        for candidate in (roles or {}).values()
        if isinstance(candidate, dict)
    ]
    if (
        not isinstance(role_hat, str)
        or not role_hat
        or len(role_hat) > 16
        or any(character.isspace() or character.isascii() for character in role_hat)
        or role_hats.count(role_hat) != 1
        or definition.get("automation") != "host"
        or definition.get("behavior_tag") != "penguin_only"
        or definition.get("lease") != "PENGUIN.md"
    ):
        return None
    suffix = f"{role_hat}{role_hat}"
    return root, "PENGUIN", role_hat, "PENGUIN", role_hat, suffix


def _witness_lifecycle_binding(root: Path) -> bool:
    decision = _read_regular_json(root / _ROLE_DECISION, _MAX_DECISION_BYTES)
    witnesses = _read_regular_json(root / _WITNESS_REGISTRY, _MAX_REGISTRY_BYTES)
    if (
        not decision
        or decision.get("schema") != "lucid-host-role-decision/1"
        or decision.get("role") != "WITNESS"
        or not witnesses
        or witnesses.get("schema") != "ae-author-glyphs/1"
    ):
        return False
    authors = witnesses.get("authors")
    alias = decision.get("witness_alias")
    glyph = authors.get(alias) if isinstance(authors, dict) and isinstance(alias, str) else None
    return (
        isinstance(glyph, str)
        and bool(glyph)
        and len(glyph) <= 16
        and not any(character.isspace() or character.isascii() for character in glyph)
        and decision.get("witness_glyph") == glyph
    )


def _ae_workspace_root(workspace_root: str | os.PathLike[str]) -> Optional[Path]:
    """Return one recognizable AE root without treating prompt prose as authority."""
    try:
        root = Path(workspace_root).expanduser().resolve(strict=True)
    except (OSError, RuntimeError, TypeError, ValueError):
        return None
    required = (root / _HARNESS, root / _ROLE_REGISTRY, root / _WITNESS_REGISTRY)
    try:
        if all(path.is_file() and not path.is_symlink() for path in required):
            return root
    except OSError:
        return None
    return None


def _role_binding_is_absent(root: Path) -> bool:
    path = root / _ROLE_DECISION
    try:
        path.lstat()
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return False


def _offline_recovery_message(root: Path, projection: dict[str, Any], cause: str) -> str:
    inspect = projection["inspect"]
    recover = projection["recover"]
    return canonical_stream(
        root,
        projection["signal"],
        service=IDENTITY_CATALYST,
        evidence=(projection["state"].upper(), f"{cause}."),
        data=(projection["owner"],),
        actions=(
            semantic_action(root, "get", inspect["arguments"], "Inspect"),
            semantic_action(root, "set", recover["arguments"], "Recover"),
        ),
    )


def _finalization_contract(root: Path) -> Optional[dict[str, Any]]:
    harness = _read_regular_json(root / _HARNESS, _MAX_HARNESS_BYTES)
    finalization = harness.get("finalization") if isinstance(harness, dict) else None
    if (
        not isinstance(harness, dict)
        or harness.get("$schema") != "ae-harness-contract/1"
        or harness.get("version") != 1
        or not isinstance(finalization, dict)
        or finalization.get("schema") != "ae-harness-finalization/1"
        or finalization.get("policy_owner") != "CATALYST"
        or finalization.get("modality") != "gestalt"
        or finalization.get("grammar") != "lucid-gestalt/1"
    ):
        return None
    attestation = finalization.get("attestation")
    signals = attestation.get("signals") if isinstance(attestation, dict) else None
    if (
        not isinstance(attestation, dict)
        or attestation.get("schema") != "ae-final-attestation/1"
        or attestation.get("persistent_role_hats") != "quine/canon/roles.json#/roles/*/hat"
        or attestation.get("engineer_hats") != "quine/canon/hats.json#/hats"
        or attestation.get("engineer_max_hats") != 10
        or attestation.get("witness_registry") != "quine/author-glyphs.json"
        or attestation.get("minimum_signals") != 1
        or not isinstance(signals, list)
        or signals != [SIGNAL_GREEN, SIGNAL_PENDING, SIGNAL_WARNING, SIGNAL_RED]
    ):
        return None
    attempts = finalization.get("attempts")
    terminal = finalization.get("terminal")
    refusals = finalization.get("refusals")
    bootstrap = refusals.get("bootstrap-decision-required") if isinstance(refusals, dict) else None
    expected_inspect = {
        "verb": "get",
        "arguments": {"path": "role", "scope": "this"},
    }
    expected_recover = {
        "verb": "set",
        "arguments": {
            "path": "role",
            "scope": "this",
            "value": {"action": "recover"},
        },
    }
    reinject_projection = attempts[0].get("projection") if isinstance(attempts, list) and attempts else None
    signout_projection = attempts[1].get("projection") if isinstance(attempts, list) and len(attempts) > 1 else None
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
        or not isinstance(bootstrap, dict)
        or bootstrap.get("schema") != "ae-harness-refusal-projection/1"
        or bootstrap.get("signal") != f"{SIGNAL_WARNING}"
        or bootstrap.get("subject") != "role"
        or bootstrap.get("state") != "bootstrap-decision-required"
        or bootstrap.get("owner") != IDENTITY_QUINE
        or bootstrap.get("settles") != "exact-local-bootstrap-decision"
        or bootstrap.get("inspect") != expected_inspect
        or bootstrap.get("recover") != expected_recover
        or bootstrap.get("constraints")
        != [
            "finalization-reminder-only",
            "one-recovery-turn",
            "no-automatic-signin",
            "retain-candidate-final",
        ]
        or not _valid_projection(
            reinject_projection,
            signal=f"{SIGNAL_WARNING}",
            evidence="ROLE-ATTESTATION-PROTOCOL-DRIFT",
            continuation="{role_hat}",
        )
        or not _valid_projection(
            signout_projection,
            signal=f"{SIGNAL_RED}",
            evidence="ROLE-ATTESTATION-PROTOCOL-DRIFT",
        )
    ):
        return None
    return finalization


def _valid_projection(
    projection: Any,
    *,
    signal: str,
    evidence: str,
    continuation: Optional[str] = None,
) -> bool:
    if not isinstance(projection, dict):
        return False
    expected_keys = {"data", "evidence", "service", "signal"}
    if continuation is not None:
        expected_keys.add("continuations")
    return (
        set(projection) == expected_keys
        and projection.get("signal") == signal
        and projection.get("service") == IDENTITY_CATALYST
        and projection.get("evidence") == [evidence, "{cause}"]
        and projection.get("data") == [IDENTITY_QUINE]
        and (
            continuation is None
            or projection.get("continuations") == [continuation]
        )
    )


def _onboarding_resources(root: Path, role: str, attempt: dict[str, Any]) -> Optional[str]:
    index = _read_regular_json(root / _ONBOARDING_INDEX, _MAX_INDEX_BYTES)
    rows = index.get("resources") if isinstance(index, dict) else None
    requested = attempt.get("resources")
    labels = attempt.get("section_labels")
    if not isinstance(rows, list) or not isinstance(requested, list) or not isinstance(labels, dict):
        return None
    by_role = {
        row.get("role"): row
        for row in rows
        if isinstance(row, dict) and isinstance(row.get("role"), str) and isinstance(row.get("path"), str)
    }
    role_lower = role.lower()
    sections = []
    for index, template in enumerate(requested):
        if not isinstance(template, str):
            return None
        resource_role = template.format(role_lower=role_lower)
        row = by_role.get(resource_role)
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
    role_hat: str,
    witness_glyph: str,
    suffix: str,
    cause: str,
    attempt: dict[str, Any],
) -> Optional[str]:
    projection = attempt.get("projection")
    if not isinstance(projection, dict):
        return None
    values = {
        "cause": cause,
        "role": role,
        "role_hat": role_hat,
        "role_lower": role.lower(),
        "suffix": suffix,
        "witness_glyph": witness_glyph,
    }
    try:
        evidence = tuple(value.format(**values) for value in projection["evidence"])
        data = tuple(value.format(**values) for value in projection["data"])
        continuations = tuple(
            value.format(**values) for value in projection.get("continuations", [])
        )
        actions = ()
        if attempt.get("action") == "signout":
            arguments = attempt.get("arguments")
            label = attempt.get("label")
            if not isinstance(arguments, dict) or not isinstance(label, str):
                return None
            actions = (semantic_action(root, "set", arguments, label),)
        rendered = canonical_stream(
            root,
            projection["signal"],
            service=projection["service"],
            evidence=evidence,
            data=data,
            continuations=continuations,
            actions=actions,
        )
    except (KeyError, TypeError, ValueError):
        return None
    if attempt.get("action") == "reinject-onboarding":
        onboarding = _onboarding_resources(root, role, attempt)
        if onboarding is None:
            return None
        rendered = f"{rendered}\n\n{onboarding}"
    return rendered


def _render_terminal_offline(
    root: Path,
    role_hat: str,
    witness_glyph: str,
    finalization: dict[str, Any],
) -> Optional[str]:
    terminal = finalization.get("terminal")
    if not isinstance(terminal, dict):
        return None
    state = terminal.get("state")
    resume_authority = terminal.get("resume_authority")
    if not isinstance(state, str) or not isinstance(resume_authority, str):
        return None
    try:
        rendered = canonical_stream(
            root,
            SIGNAL_RED,
            service=IDENTITY_CATALYST,
            evidence=(
                "ROLE-ATTESTATION-PROTOCOL-DRIFT",
                "repeated-role-protocol-drift",
            ),
            data=(IDENTITY_QUINE, state.upper(), f"RESUME {resume_authority}"),
        )
    except (OSError, TypeError, ValueError):
        return None
    return f"{rendered}\n\n{role_hat}{witness_glyph}"


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
    signals = policy["signals"]
    if sum(body.count(signal) for signal in signals) < policy["minimum_signals"]:
        return "canonical-gestalt-signal-missing"
    return None


def _pre_final(
    *,
    final_response: str = "",
    workspace_root: str = "",
    attempt: int = 0,
    session_id: str = "",
    agent_role: str = "",
    **_: Any,
) -> Optional[dict[str, str]]:
    if attempt < 0 or not isinstance(final_response, str) or not final_response.strip():
        return None
    ae_root = _ae_workspace_root(workspace_root)
    if ae_root is None:
        return None
    attestation = _effective_attestation(workspace_root, agent_role)
    if attestation is None:
        with _STATE_LOCK:
            lifecycle_confirmed = (
                bool(session_id)
                and session_id in _LIVE_LIFECYCLE_SESSIONS
                and session_id not in _SIGNED_OUT_SESSIONS
            )
        if lifecycle_confirmed and _witness_lifecycle_binding(ae_root):
            logger.warning(
                "preserving final for session-confirmed WITNESS lifecycle binding; "
                "canonical finalization role is unavailable"
            )
            return None
        cause = "the exact live role/witness binding is unavailable"
        finalization = _finalization_contract(ae_root)
        if finalization is None:
            logger.warning(
                "preserving final because the CATALYST finalization contract is unavailable or malformed"
            )
            return None
        if attempt == 0 and _role_binding_is_absent(ae_root):
            return {
                "action": "continue",
                "message": _offline_recovery_message(
                    ae_root,
                    finalization["refusals"]["bootstrap-decision-required"],
                    cause,
                ),
            }
        logger.warning("preserving final without exact live role/witness attestation")
        return None
    root, role, role_hat, _, witness_glyph, suffix = attestation
    finalization = _finalization_contract(root)
    if finalization is None:
        logger.warning(
            "preserving final because the CATALYST finalization contract is unavailable or malformed"
        )
        return None
    cause = _attestation_failure(final_response, attestation, finalization)
    attempts = finalization["attempts"]
    terminal_attempt = 1 if role == "PENGUIN" else len(attempts)
    if attempt >= terminal_attempt:
        with _STATE_LOCK:
            signed_out = bool(session_id) and session_id in _SIGNED_OUT_SESSIONS
        if signed_out:
            return None
        message = _render_terminal_offline(
            root,
            role_hat,
            witness_glyph,
            finalization,
        )
        return {"action": "block", "message": message} if message is not None else None
    if cause is None:
        return None
    selected = attempts[attempt]
    if not isinstance(selected, dict):
        return None
    message = _render_attempt(
        root,
        role,
        role_hat,
        witness_glyph,
        suffix,
        cause,
        selected,
    )
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
        try:
            stream = parse_stream(_GESTALT_ROOT, candidate)
        except (OSError, ValueError):
            continue
        semantics = set(stream["data"]) | set(stream["evidence"])
        if (
            stream["signal"] == f"{SIGNAL_GREEN}"
            and stream["verb"] == "show"
            and stream["noun"] == "text"
            and stream["arguments"] == ["FRESH"]
            and {
                "Presentation Audio Accepted=true",
                "Presentation Audio Status=accepted",
                "Presentation Audio Code=speech-queued",
            }.issubset(semantics)
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


def _effigy_display_detail(code: str, detail: str) -> Optional[str]:
    ignored = {
        "a",
        "an",
        "effigy",
        "is",
        "local",
        "model",
        "penguin",
        "the",
        "transfer",
        "was",
        "worker",
    }
    words = {word for word in re.split(r"[^a-z0-9]+", detail.lower()) if word not in ignored}
    generic = {"failed", "failure", "refused", "unavailable"}
    if words and words <= generic:
        return None
    code_words = set(re.split(r"[^a-z0-9]+", code.lower())) - ignored
    return None if words and words <= code_words else detail


def _canonical_effigy_refusal(value: Any) -> Optional[tuple[str, str]]:
    if not isinstance(value, str):
        return None
    try:
        stream = parse_stream(_GESTALT_ROOT, value)
    except (OSError, ValueError):
        return None
    evidence = stream.get("evidence")
    data = stream.get("data")
    if stream.get("signal") != SIGNAL_RED or not isinstance(evidence, list) or not isinstance(data, list):
        return None
    machine = next(
        (
            item.lower()
            for item in [*stream.get("arguments", []), *reversed(evidence)]
            if isinstance(item, str)
            and "-" in item
            and re.fullmatch(r"[a-z0-9][a-z0-9-]{0,95}", item, re.IGNORECASE)
        ),
        None,
    )
    if machine is None:
        return None
    detail = next(
        (
            bounded
            for item in [*evidence, *data]
            if isinstance(item, str) and item.lower() != machine
            and (bounded := _bounded_effigy_detail(item)) is not None
        ),
        "LUCID returned a refusal without a typed failure detail",
    )
    return machine, detail


def _effigy_failure_fields(
    result: Any,
    cause: Optional[BaseException] = None,
) -> tuple[str, str, str]:
    stage = "submission"
    code = "effigy-submission-failed"
    if cause is not None:
        parsed = _canonical_effigy_refusal(str(cause))
        if parsed is not None:
            return stage, *parsed
        detail = _bounded_effigy_detail(str(cause)) or "submission raised without an error message"
        return stage, code, f"{type(cause).__name__}: {detail}"
    if not isinstance(result, dict):
        return stage, code, "LUCID returned no typed submission result"
    containers = []
    pending = [result]
    while pending and len(containers) < 8:
        container = pending.pop(0)
        if not isinstance(container, dict) or any(container is seen for seen in containers):
            continue
        containers.append(container)
        for key in ("presentation", "structuredContent", "result"):
            nested = container.get(key)
            if isinstance(nested, dict):
                pending.append(nested)
    candidates = [
        candidate
        for container in containers
        for key in ("model", "result", "__hermes_model_visible_result")
        if isinstance((candidate := container.get(key)), str)
    ]
    candidates.extend(
        item["text"]
        for container in containers
        for item in container.get("content", [])
        if isinstance(item, dict)
        and item.get("type") == "text"
        and isinstance(item.get("text"), str)
    )
    for candidate in candidates:
        parsed = _canonical_effigy_refusal(candidate)
        if parsed is not None:
            return stage, *parsed
    for container in containers:
        for key in ("detail", "error", "reason", "message"):
            parsed = _canonical_effigy_refusal(container.get(key))
            if parsed is not None:
                return stage, *parsed
    for container in containers:
        refusal = container.get("refusal")
        if not isinstance(refusal, dict):
            continue
        typed_code = refusal.get("code")
        if isinstance(typed_code, str) and re.fullmatch(r"[a-z0-9][a-z0-9-]{0,95}", typed_code):
            code = typed_code
            if code.startswith("effigy-transfer-"):
                stage = "effigy-transfer"
        for key in ("reason", "detail", "message"):
            typed_detail = _bounded_effigy_detail(refusal.get(key))
            if typed_detail is not None:
                return stage, code, typed_detail
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
            canonical = [segment.strip() for segment in line.split(DELIMITER_SEGMENT)]
            refusal_code = next(
                (
                    segment.removeprefix(f"{RELATION_EVIDENCE} ")
                    for segment in canonical
                    if segment.startswith(f"{RELATION_EVIDENCE} ")
                ),
                None,
            )
            if refusal_code is not None:
                normalized_code = refusal_code.strip().lower().replace("_", "-")
                if re.fullmatch(r"[a-z0-9][a-z0-9-]{0,95}", normalized_code):
                    code = normalized_code
                typed_detail = next(
                    (
                        _bounded_effigy_detail(segment.removeprefix(f"{RELATION_DATUM} "))
                        for segment in canonical
                        if segment.startswith(f"{RELATION_DATUM} ")
                    ),
                    None,
                )
                if typed_detail is not None:
                    detail = typed_detail
            elif line.startswith("Presentation Audio Effigy Transfer Code="):
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
    display_detail = _effigy_display_detail(code, detail)
    display_code = code.upper()
    rca = display_code if display_detail is None else f"{display_code}: {display_detail}"
    atoms = tuple(atom.strip() for atom in rca.split(DELIMITER_SEGMENT) if atom.strip())
    print(
        canonical_stream(_GESTALT_ROOT, f"{SIGNAL_WARNING}", evidence=atoms[:1], data=(*atoms[1:], role_glyph)),
        file=sys.stderr,
        flush=True,
    )
    return stage, code, detail


def _post_final(
    *,
    final_response: str = "",
    workspace_root: str = "",
    session_id: str = "",
    agent_role: str = "",
    **_: Any,
) -> Optional[dict[str, str]]:
    """Submit one attested final through the current role's EFFIGY speech profile."""

    if not isinstance(final_response, str) or not final_response.strip():
        return None
    attestation = _effective_attestation(workspace_root, agent_role)
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


def _contains_role_action(value: Any, actions: set[str], depth: int = 0) -> bool:
    if depth > 10:
        return False
    if isinstance(value, dict):
        if value.get("state") in actions or value.get("action") in actions:
            return True
        return any(_contains_role_action(child, actions, depth + 1) for child in value.values())
    if isinstance(value, list):
        return any(_contains_role_action(child, actions, depth + 1) for child in value)
    return False


def _role_action_settled(value: Any, action: str) -> bool:
    terminal_states = {
        "signin": {"signin", "signed-in", "bound"},
        "register-signin": {"register-signin", "signed-in", "bound"},
        "recover": {"recover", "recovered", "signed-in", "bound"},
        "signout": {"signout", "signed-out", "unbound"},
    }
    return _contains_role_action(value, terminal_states.get(action, {action}))


def _transform_tool_result(
    *,
    tool_name: str = "",
    args: Any = None,
    result: Any = None,
    session_id: str = "",
    status: str = "",
    **_: Any,
) -> None:
    value_args = args.get("value") if isinstance(args, dict) else None
    requested_action = value_args.get("action") if isinstance(value_args, dict) else None
    if (
        tool_name != "mcp__LUCID__set"
        or not isinstance(args, dict)
        or args.get("path") not in {"role", "role-session"}
        or args.get("scope") not in {None, "this"}
        or requested_action not in {"signin", "register-signin", "recover", "signout"}
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
        if _role_action_settled(value, requested_action):
            with _STATE_LOCK:
                if requested_action == "signout":
                    _SIGNED_OUT_SESSIONS.add(session_id)
                    _LIVE_LIFECYCLE_SESSIONS.discard(session_id)
                else:
                    _SIGNED_OUT_SESSIONS.discard(session_id)
                    _LIVE_LIFECYCLE_SESSIONS.add(session_id)
    return None


def _on_session_end(*, session_id: str = "", **_: Any) -> None:
    if session_id:
        with _STATE_LOCK:
            _SIGNED_OUT_SESSIONS.discard(session_id)
            _LIVE_LIFECYCLE_SESSIONS.discard(session_id)
            stale = {
                identity for identity in _SPOKEN_FINALS if identity[0] == session_id
            }
            _SPOKEN_FINALS.difference_update(stale)


def register(ctx) -> None:
    ctx.register_hook("pre_final", _pre_final)
    ctx.register_hook("post_final", _post_final)
    ctx.register_hook("transform_tool_result", _transform_tool_result)
    ctx.register_hook("on_session_end", _on_session_end)
