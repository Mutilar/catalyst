"""Typed internal split between model context and presentation-only tool data."""

from __future__ import annotations

import json
from typing import Any

SCHEMA = "hermes-tool-result-channels/1"
_MAX_PRESENTATION_BYTES = 1_048_576


def encode_tool_result_channels(
    model: str,
    presentation: dict[str, Any],
    *,
    is_error: bool = False,
) -> str:
    """Encode one process-local dual-channel result for the agent executor."""
    if not isinstance(model, str) or not isinstance(presentation, dict):
        raise TypeError("tool result channels require text model content and object presentation")
    encoded_presentation = json.dumps(presentation, ensure_ascii=False, separators=(",", ":"))
    if len(encoded_presentation.encode("utf-8")) > _MAX_PRESENTATION_BYTES:
        raise ValueError("presentation tool result exceeds its byte bound")
    envelope = {"schema": SCHEMA, "model": model, "presentation": presentation}
    if is_error:
        envelope["error"] = model
    return json.dumps(
        envelope,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def split_tool_result_channels(value: Any) -> tuple[Any, Any]:
    """Return ``(model, presentation)``; ordinary tool results pass through twice."""
    if not isinstance(value, str):
        return value, value
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return value, value
    if not isinstance(parsed, dict) or parsed.get("schema") != SCHEMA:
        return value, value
    keys = set(parsed)
    if keys not in (
        {"schema", "model", "presentation"},
        {"schema", "model", "presentation", "error"},
    ):
        return value, value
    model = parsed.get("model")
    presentation = parsed.get("presentation")
    if not isinstance(model, str) or not isinstance(presentation, dict):
        return value, value
    if "error" in parsed and parsed.get("error") != model:
        return value, value
    encoded_presentation = json.dumps(presentation, ensure_ascii=False, separators=(",", ":"))
    if len(encoded_presentation.encode("utf-8")) > _MAX_PRESENTATION_BYTES:
        return value, value
    return model, encoded_presentation
