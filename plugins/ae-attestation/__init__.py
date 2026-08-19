"""AE final-response attestation guard.

The plugin is inert outside an AgentExperiments checkout. It derives the exact
terminal suffix from the live host-owned LUCID role decision and QUINE's
canonical role registry; prompt prose and model claims are never authority.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

_ROLE_DECISION = Path("run/state/runtime/lucid-host-role.json")
_ROLE_REGISTRY = Path("quine/canon/roles.json")
_MAX_DECISION_BYTES = 4096
_MAX_REGISTRY_BYTES = 64 * 1024


def _read_regular_json(path: Path, maximum_bytes: int) -> Optional[dict[str, Any]]:
    try:
        metadata = path.lstat()
        if path.is_symlink() or not path.is_file() or metadata.st_size > maximum_bytes:
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def required_terminal_suffix(workspace_root: str | os.PathLike[str]) -> Optional[str]:
    try:
        root = Path(workspace_root).expanduser().resolve(strict=True)
    except (OSError, RuntimeError, TypeError, ValueError):
        return None
    decision = _read_regular_json(root / _ROLE_DECISION, _MAX_DECISION_BYTES)
    registry = _read_regular_json(root / _ROLE_REGISTRY, _MAX_REGISTRY_BYTES)
    if not decision or not registry:
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
    if not isinstance(definition, dict):
        return None
    glyph = definition.get("glyph")
    if (
        not isinstance(glyph, str)
        or not glyph
        or len(glyph) > 16
        or not glyph.endswith("🐧")
        or any(character.isspace() for character in glyph)
    ):
        return None
    return glyph


def _pre_final(
    *,
    final_response: str = "",
    workspace_root: str = "",
    attempt: int = 0,
    **_: Any,
) -> Optional[dict[str, str]]:
    if attempt >= 1 or not isinstance(final_response, str) or not final_response.strip():
        return None
    suffix = required_terminal_suffix(workspace_root)
    if suffix is None or final_response.rstrip().endswith(suffix):
        return None
    return {
        "action": "continue",
        "message": (
            "[System: The proposed final response is missing the exact terminal token "
            f"required by the active canonical role attestation. Reply again with the same "
            f"substantive answer, corrected so its final characters are exactly `{suffix}`. "
            "Do not call tools, perform work, add claims, or reinterpret completion. This "
            "correction grants no authority and attests no repository state.]"
        ),
    }


def register(ctx) -> None:
    ctx.register_hook("pre_final", _pre_final)
