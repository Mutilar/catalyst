"""Project RUN-owned MCP outage state through generated LUCID offline facades."""

from __future__ import annotations

import json
from pathlib import Path
import shlex
from typing import Any

_REPO = Path(__file__).resolve().parents[2]
_OFFLINE = _REPO / "envelope/LUCID-OFFLINE.json"
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
    try:
        encoded = json.dumps(arguments, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError):
        return None
    if len(encoded.encode("utf-8")) > _MAX_ARGUMENTS:
        return None
    return f"{adapter} --args {shlex.quote(encoded)}"


def project_lucid_transport_outage(tool: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Return a bounded UGUI-shaped fallback only for RUN-attested active outage."""

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
    text = f"⚠️ LUCID · {tool} · mcp-unavailable\n{eta}\nOFFLINE {command}\nRETIRE port:mcp fresh 🟢"
    return {
        "error": text,
        "structuredContent": {
            "schema": "lucid-ugui-response/1",
            "id": "lucid.mcp-unavailable",
            "type": "lucid",
            "verb": tool,
            "state": "mcp-unavailable",
            "header": [{"id": "lucid.outage.title", "type": "text", "body": "LUCID unavailable", "style": "heading", "width": 12}],
            "sections": [
                {"id": "lucid.outage.status", "type": "status", "signal": "warning", "body": eta, "width": 12},
                {"id": "lucid.outage.fallback", "type": "text", "body": f"OFFLINE {command}", "width": 12},
            ],
            "actions": [],
            "provenance": {
                "schema": "ugui-provenance/1",
                "sourceSchema": "run-mcp-revival/1",
                "parentHash": registry.get("source_hash"),
                "observedEpoch": revival.get("observed_epoch_ms", 0) // 1000,
                "sourceField": "offline_facades",
            },
            "fidelity": {
                "schema": "lucid-ugui-projection-fidelity/1",
                "lossless": True,
                "sourceFields": ["node", "eta", "offline_facades_active"],
                "projectedFields": ["state", "sections"],
                "omittedFields": [],
                "generator": "catalyst.tools.lucid_outage@1",
            },
            "receipt": {"schema": "lucid-ugui-action-receipt/1", "action_provenance": []},
        },
    }


def project_lucid_failure(
    tool: str,
    arguments: dict[str, Any],
    detail: str,
    structured: dict[str, Any] | None = None,
    code: str = "mcp-unavailable",
) -> dict[str, Any]:
    """Project every LUCID failure without inventing RUN-owned outage evidence."""

    if isinstance(structured, dict):
        return {"error": detail, "structuredContent": structured}
    outage = project_lucid_transport_outage(tool, arguments)
    if outage is not None:
        return outage
    code = code if code in {"mcp-unavailable", "outcome-envelope-invalid"} else "outcome-envelope-invalid"
    bounded = " ".join(detail.split())[:1024] or "isError response omitted content and structuredContent"
    next_action = f"lucid {tool} --help"
    return {
        "error": f"🔴 LUCID · {tool} · {code}\nCAUSE {bounded}\nNEXT {next_action}",
        "structuredContent": {
            "schema": "lucid-ugui-response/1",
            "id": f"lucid.{code}",
            "type": "lucid",
            "verb": tool,
            "state": code,
            "header": [
                {
                    "id": "lucid.error.title",
                    "type": "text",
                    "body": f"LUCID {tool} failed",
                    "style": "heading",
                    "width": 12,
                }
            ],
            "sections": [
                {
                    "id": "lucid.error.status",
                    "type": "status",
                    "signal": "error",
                    "body": bounded,
                    "width": 12,
                },
                {
                    "id": "lucid.error.next",
                    "type": "text",
                    "body": f"NEXT {next_action}",
                    "width": 12,
                },
            ],
            "actions": [],
            "provenance": {
                "schema": "ugui-provenance/1",
                "sourceSchema": "mcp-call-tool-result",
                "parentHash": None,
                "observedEpoch": 0,
                "sourceField": "isError",
            },
            "fidelity": {
                "schema": "lucid-ugui-projection-fidelity/1",
                "lossless": False,
                "sourceFields": ["isError", "content", "structuredContent"],
                "projectedFields": ["state", "sections"],
                "omittedFields": ["transport"],
                "generator": "catalyst.tools.lucid_outage@1",
            },
            "receipt": {"schema": "lucid-ugui-action-receipt/1", "action_provenance": []},
        },
    }
