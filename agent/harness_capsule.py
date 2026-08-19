"""Content-free observation of the actual Catalyst model tool schema.

The observation contains hashes and counts only. Tool declarations, descriptions,
arguments, session identity, prompts, and provider credentials are never persisted.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Iterable, Optional

_SCHEMA = "ae-catalyst-harness-tool-observation/1"
_LUCID_PREFIX = "mcp__lucid__"
_GENERIC_EQUIVALENTS = frozenset(
    {
        "execute_code",
        "patch",
        "process",
        "read_file",
        "search_files",
        "terminal",
        "workflow",
        "write_file",
    }
)


def _canonical_hash(value: Any) -> str:
    canonical = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _tool_name(tool: Any) -> Optional[str]:
    if not isinstance(tool, dict):
        return None
    function = tool.get("function")
    name = function.get("name") if isinstance(function, dict) else tool.get("name")
    return name if isinstance(name, str) and name else None


def _normalized_tool_projection(tools: list[Any]) -> list[dict[str, Any]]:
    projected = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        candidate = tool.get("function")
        function = candidate if isinstance(candidate, dict) else tool
        name = function.get("name")
        arguments = function.get("parameters", function.get("inputSchema"))
        if isinstance(name, str) and name and isinstance(arguments, dict):
            projected.append({"name": name, "arguments": arguments})
    return sorted(projected, key=lambda tool: tool["name"])


def observe_tool_schema(tools: Iterable[Any], observed_epoch: Optional[int] = None) -> dict[str, Any]:
    snapshot = list(tools)
    names = [name for name in (_tool_name(tool) for tool in snapshot) if name is not None]
    normalized = [name.lower().replace(".", "__").replace("-", "_") for name in names]
    lucid_count = sum(name.startswith(_LUCID_PREFIX) for name in normalized)
    generic_count = sum(name in _GENERIC_EQUIVALENTS for name in normalized)
    epoch = int(time.time()) if observed_epoch is None else observed_epoch
    if epoch <= 0:
        raise ValueError("observed_epoch must be positive")
    return {
        "schema": _SCHEMA,
        "observed_epoch": epoch,
        "actual_tool_schema_hash": _canonical_hash(_normalized_tool_projection(snapshot)),
        "request_tool_schema_hash": _canonical_hash(snapshot),
        "tool_count": len(snapshot),
        "lucid_tool_count": lucid_count,
        "generic_equivalent_count": generic_count,
        "dual_surface": lucid_count > 0 and generic_count > 0,
        "content_included": False,
    }


def _ae_root(start: Path) -> Optional[Path]:
    try:
        current = start.expanduser().resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        return None
    for candidate in (current, *current.parents):
        if (candidate / "envelope/HARNESS.json").is_file() and (
            candidate / "envelope/LUCID.json"
        ).is_file():
            return candidate
    return None


def observe_agent_tool_schema(agent: Any, workspace: Optional[str | os.PathLike[str]] = None) -> None:
    tools = getattr(agent, "tools", None)
    if not isinstance(tools, list):
        return
    start = Path(workspace) if workspace is not None else Path.cwd()
    root = _ae_root(start)
    if root is None:
        return
    try:
        observation = observe_tool_schema(tools)
        sys.stderr.write(
            "HARNESS_TOOL_OBSERVATION "
            + json.dumps(observation, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
            + "\n"
        )
        sys.stderr.flush()
    except (OSError, TypeError, ValueError):
        return
