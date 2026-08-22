"""Project RUN-owned MCP outage state through generated LUCID offline facades."""

from __future__ import annotations

import json
from pathlib import Path
import shlex

from typing import Any

_REPO = Path(__file__).resolve().parents[2]
_OFFLINE = _REPO / "envelope/LUCID-OFFLINE.json"
_GESTALT = _REPO / "envelope/GESTALT.json"
_REVIVAL = _REPO / "run/state/runtime/mcp-revival.json"
_MAX_REGISTRY = 64 * 1024
_MAX_REVIVAL = 4 * 1024
_MAX_ARGUMENTS = 65_536


def _read_json(path: Path, maximum: int) -> dict[str, Any] | None:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > maximum:
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _facade_matches(facade: dict[str, Any], tool: str, arguments: dict[str, Any]) -> bool:
    if facade.get("outage_tier") != "mcp-offline" or facade.get("verb") != tool:
        return False
    canonical = facade.get("canonical")
    if not isinstance(canonical, dict):
        return False
    if "path" in canonical and arguments.get("path") != canonical["path"]:
        return False
    if "view" in canonical and arguments.get("view") != canonical["view"]:
        return False
    if "task" in canonical and arguments.get("task") != canonical["task"]:
        return False
    operations = canonical.get("operations")
    if isinstance(operations, list):
        operation = arguments.get("query", {}).get("operation") if tool == "get" else arguments.get("value", {}).get("operation")
        if operation not in operations:
            return False
    return True


def _command(facade: dict[str, Any], arguments: dict[str, Any]) -> str | None:
    adapter = facade.get("adapter")
    if not isinstance(adapter, str) or not adapter:
        return None
    if adapter == "plan":
        return "plan < ae-dispatch.json"
    if adapter == "receipt":
        return "receipt < envelope.json"
    if adapter.startswith("lucid "):
        verb = adapter.removeprefix("lucid ")
        noun_key = {
            "show": "view",
            "get": "path",
            "set": "path",
            "morph": "codebook",
            "dispatch": "task",
            "steer": "action",
            "cancel": "action",
        }.get(verb)
        noun = arguments.get(noun_key) if noun_key else None
        if not isinstance(noun, str) or not noun:
            return None
        tokens = ["lucid", verb, noun]
        for key, value in arguments.items():
            if key == noun_key:
                continue
            if key == "scope" and value == "this":
                continue
            encoded = (
                value
                if isinstance(value, str)
                else json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            )
            tokens.extend([f"--{key.replace('_', '-')}", shlex.quote(encoded)])
        return " ".join(tokens)
    try:
        encoded = json.dumps(arguments, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError):
        return None
    if len(encoded.encode("utf-8")) > _MAX_ARGUMENTS:
        return None
    return f"{adapter} --args {shlex.quote(encoded)}"


def project_lucid_transport_outage(tool: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Return bounded Gestalt only for a RUN-attested active outage."""

    revival = _read_json(_REVIVAL, _MAX_REVIVAL)
    registry = _read_json(_OFFLINE, _MAX_REGISTRY)
    if (
        revival is None
        or registry is None
        or revival.get("schema") != "run-mcp-revival/1"
        or revival.get("node") != "butler:port:mcp"
        or revival.get("owner") != "RUN"
        or revival.get("offline_facades_active") is not True
    ):
        return None
    eta = revival.get("eta")
    if not isinstance(eta, str) or not (eta == "⏳ ETA UNKNOWN" or eta.startswith("⏳ ETA T-")):
        return None
    facades = registry.get("facades")
    if not isinstance(facades, list):
        return None
    facade = next(
        (row for row in facades if isinstance(row, dict) and _facade_matches(row, tool, arguments)),
        None,
    )
    if facade is None:
        return None
    command = _command(facade, arguments)
    if command is None:
        return None
    text = (
        f"⚠️ LUCID · {tool} · transport · offline-fallback\n"
        f"🔎 mcp-unavailable · {eta}\n"
        f"➡️ {command}"
    )
    return {"error": text}


def project_lucid_failure(
    tool: str,
    arguments: dict[str, Any],
    detail: str,
    structured: dict[str, Any] | None = None,
    code: str = "mcp-unavailable",
) -> dict[str, Any]:
    """Project every LUCID failure without inventing RUN-owned outage evidence."""

    outage = project_lucid_transport_outage(tool, arguments)
    if outage is not None:
        return outage
    code = code if code in {"mcp-unavailable", "outcome-envelope-invalid"} else "outcome-envelope-invalid"
    gestalt = _read_json(_GESTALT, _MAX_REGISTRY) or {}
    line_bytes = gestalt.get("bounds", {}).get("lineBytes", 1024)
    if not isinstance(line_bytes, int) or not 1 <= line_bytes <= 4096:
        line_bytes = 1024
    bounded = " ".join(detail.split())[:line_bytes] or "isError response omitted content and structuredContent"
    action = json.dumps(
        {"label": "?", "verb": tool, "arguments": {}},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return {
        "error": (
            f"🔴 LUCID · {tool} · transport · {code}\n"
            f"🔎 Code={code} · Detail={bounded}\n➡️ {action}"
        )
    }
