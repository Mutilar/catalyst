"""Closed local PENGUIN model identity for Catalyst and LUCID host binding."""

from __future__ import annotations
from agent.generated.ae_glyphs import DELIMITER_SEGMENT, IDENTITY_PENGUIN

import json
from pathlib import Path
from typing import Any

PENGUIN_PROVIDER_ID = "penguin"
PENGUIN_MODEL_ID = "PENGUIN"
PENGUIN_WIRE_MODEL_ID = "mlx-community/Ornith-1.0-35B-4bit"
PENGUIN_BASE_URL = "http://127.0.0.1:8080/v1"
PENGUIN_API_MODE = "chat_completions"
PENGUIN_ROLE = "PENGUIN"
_MAX_ROLE_BYTES = 8 * 1024
_MAX_LUCID_BYTES = 512 * 1024
_PENGUIN_TOOL_NAMES = frozenset({
    "mcp__lucid__get",
    "mcp__lucid__show",
    "mcp__lucid__set",
})


def is_penguin_selection(provider: object, model: object) -> bool:
    """Return true only for the exact authored picker identity."""

    return provider == PENGUIN_PROVIDER_ID and model == PENGUIN_MODEL_ID


def is_penguin_runtime(model: object, base_url: object) -> bool:
    """Recognize only the exact admitted model at its exact loopback route."""

    return model == PENGUIN_MODEL_ID and base_url == PENGUIN_BASE_URL


def penguin_picker_row(*, current_provider: str, current_model: str) -> dict[str, Any]:
    """Return the sole picker row for RUN's supervised loopback SLM."""

    return {
        "slug": PENGUIN_PROVIDER_ID,
        "name": "Microsoft Applied Sciences",
        "model_labels": {PENGUIN_MODEL_ID: f"{IDENTITY_PENGUIN}"},
        "model_annotations": {
            PENGUIN_MODEL_ID: [
                {"label": "Role", "value": PENGUIN_ROLE},
                {"label": "Runtime", "value": "Local MLX"},
                {"label": "Grants", "value": DELIMITER_SEGMENT.join(("GET", "SHOW"))},
            ]
        },
        "is_current": is_penguin_selection(current_provider, current_model),
        "is_user_defined": False,
        "models": [PENGUIN_MODEL_ID],
        "total_models": 1,
        "source": "run-supervised-local-model",
        "authenticated": True,
        "auth_type": "local-supervised",
        "capabilities": {
            PENGUIN_MODEL_ID: {"fast": False, "reasoning": False},
        },
    }


def penguin_model_override(provider: object, model: object) -> dict[str, Any] | None:
    """Translate the exact picker identity into a bounded local runtime route."""

    if is_penguin_selection(provider, model):
        return {
            "model": PENGUIN_MODEL_ID,
            "provider": PENGUIN_PROVIDER_ID,
            "base_url": PENGUIN_BASE_URL,
            "api_key": "local-penguin",
            "api_mode": PENGUIN_API_MODE,
        }
    if provider == PENGUIN_PROVIDER_ID or model == PENGUIN_MODEL_ID:
        raise ValueError("PENGUIN requires the exact provider/model pair")
    return None


def penguin_runtime() -> dict[str, Any]:
    """Return the OpenAI-compatible runtime used only after exact admission."""

    return {
        "provider": "custom",
        "model": PENGUIN_WIRE_MODEL_ID,
        "base_url": PENGUIN_BASE_URL,
        "api_key": "local-penguin",
        "api_mode": PENGUIN_API_MODE,
    }


def penguin_role_document() -> str:
    """Read the generated parent role lease through one bounded local path."""

    path = Path(__file__).resolve().parent.parent / "PENGUIN.md"
    if path.is_symlink() or not path.is_file():
        raise ValueError("PENGUIN role document is unavailable")
    content = path.read_bytes()
    if not content or len(content) > _MAX_ROLE_BYTES:
        raise ValueError("PENGUIN role document is outside its byte bound")
    text = content.decode("utf-8")
    if (
        not text.startswith("<!-- GENERATED")
        or f"| **{IDENTITY_PENGUIN}{IDENTITY_PENGUIN} PROTOCOL** | **RULE** |" not in text
    ):
        raise ValueError("PENGUIN role document is not canonical")
    lucid_path = path.parent / "envelope" / "LUCID.json"
    if lucid_path.is_symlink() or not lucid_path.is_file():
        raise ValueError("LUCID vocabulary is unavailable")
    lucid_content = lucid_path.read_bytes()
    if not lucid_content or len(lucid_content) > _MAX_LUCID_BYTES:
        raise ValueError("LUCID vocabulary is outside its byte bound")
    lucid = json.loads(lucid_content)
    verbs = lucid.get("verbs")
    if not isinstance(verbs, dict) or len(verbs) != 7:
        raise ValueError("LUCID vocabulary is not the closed seven-verb codebook")
    verb_names = sorted(
        name.upper() for name in verbs if isinstance(name, str) and name
    )
    if len(verb_names) != 7:
        raise ValueError("LUCID vocabulary contains an invalid verb identity")
    get_targets = lucid.get("get_registry", {}).get("targets")
    if not isinstance(get_targets, list):
        raise ValueError("LUCID GET registry is unavailable")
    get_ids = {
        target.get("id")
        for target in get_targets
        if isinstance(target, dict) and isinstance(target.get("id"), str)
    }
    if not {"role", "pulse"}.issubset(get_ids) or "identity" in get_ids:
        raise ValueError("LUCID role/pulse GET vocabulary is invalid")
    vocabulary = (
        f"LUCID has exactly {len(verb_names)} verbs: {DELIMITER_SEGMENT.join(verb_names)}. "
        "MCP prompts and resources are discovery surfaces, not verbs. "
        "After sign-in, GET role verifies the binding and GET pulse reads current state; "
        "GET identity is not registered."
    )
    return f"{text.rstrip()}\n\n{vocabulary}\n"


def penguin_tool_definitions(tools: object) -> list[dict[str, Any]]:
    """Project the model-visible tool catalog to PENGUIN's exact grants."""

    if not isinstance(tools, list):
        return []
    projected = []
    for tool in tools:
        if not isinstance(tool, dict) or not isinstance(tool.get("function"), dict):
            continue
        name = str(tool["function"].get("name", "")).lower()
        if name not in _PENGUIN_TOOL_NAMES:
            continue
        if name == "mcp__lucid__set":
            tool = {
                **tool,
                "function": {
                    **tool["function"],
                    "description": (
                        "Bootstrap this PENGUIN session through LUCID role sign-in. "
                        "This is not a mutating role grant."
                    ),
                    "parameters": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "path": {"const": "role"},
                            "value": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {"action": {"const": "signin"}},
                                "required": ["action"],
                            },
                        },
                        "required": ["path", "value"],
                    },
                },
            }
        projected.append(tool)
    return projected


def configure_penguin_agent(agent: object) -> None:
    """Apply PENGUIN prompt and tool exposure without changing public identity."""

    if not hasattr(agent, "_penguin_full_tools"):
        agent._penguin_full_tools = list(getattr(agent, "tools", None) or [])
    agent._prompt_profile = "penguin"
    agent.tools = penguin_tool_definitions(agent._penguin_full_tools)
    agent.valid_tool_names = {tool["function"]["name"] for tool in agent.tools}
    agent._cached_system_prompt = None


def clear_penguin_agent(agent: object) -> None:
    """Restore the pre-PENGUIN prompt profile and complete tool snapshot."""

    agent._prompt_profile = ""
    full_tools = getattr(agent, "_penguin_full_tools", None)
    if isinstance(full_tools, list):
        agent.tools = full_tools
        agent.valid_tool_names = {
            tool["function"]["name"]
            for tool in full_tools
            if isinstance(tool, dict) and isinstance(tool.get("function"), dict)
        }
        del agent._penguin_full_tools
    agent._cached_system_prompt = None
