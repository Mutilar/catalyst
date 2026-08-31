from __future__ import annotations

import pytest

from hermes_penguin import (
    PENGUIN_BASE_URL,
    PENGUIN_MODEL_ID,
    PENGUIN_PROVIDER_ID,
    PENGUIN_WIRE_MODEL_ID,
    clear_penguin_agent,
    configure_penguin_agent,
    is_penguin_selection,
    penguin_model_override,
    penguin_picker_row,
    penguin_role_document,
    penguin_runtime,
)
from hermes_cli.inventory import ConfigContext, build_models_payload


def test_picker_row_is_one_authenticated_closed_penguin_model() -> None:
    row = penguin_picker_row(
        current_provider=PENGUIN_PROVIDER_ID,
        current_model=PENGUIN_MODEL_ID,
    )

    assert row["slug"] == "penguin"
    assert row["name"] == "Microsoft Applied Sciences"
    assert row["model_labels"] == {"PENGUIN": "🐧"}
    assert row["model_annotations"]["PENGUIN"] == [
        {"label": "Role", "value": "PENGUIN"},
        {"label": "Runtime", "value": "Local MLX"},
        {"label": "Grants", "value": "GET · SHOW"},
    ]
    assert row["models"] == ["PENGUIN"]
    assert row["authenticated"] is True
    assert row["is_current"] is True
    assert row["capabilities"] == {"PENGUIN": {"fast": False, "reasoning": False}}


def test_shared_inventory_always_exposes_one_penguin_picker_row(monkeypatch) -> None:
    monkeypatch.setattr(
        "hermes_cli.model_switch.list_authenticated_providers",
        lambda **_kwargs: [],
    )
    payload = build_models_payload(
        ConfigContext(
            current_provider="",
            current_model="",
            current_base_url="",
            user_providers={},
            custom_providers=[],
            excluded_providers=[],
        ),
        explicit_only=True,
        picker_hints=True,
        capabilities=True,
    )

    assert [row for row in payload["providers"] if row["slug"] == "penguin"] == [
        penguin_picker_row(current_provider="", current_model="")
    ]


def test_exact_penguin_selection_maps_to_loopback_chat_completions() -> None:
    override = penguin_model_override("penguin", "PENGUIN")

    assert override is not None
    assert override["base_url"] == PENGUIN_BASE_URL
    assert override["api_mode"] == "chat_completions"
    assert penguin_runtime()["provider"] == "custom"
    assert penguin_runtime()["model"] == PENGUIN_WIRE_MODEL_ID
    assert is_penguin_selection("penguin", "PENGUIN")
    doctrine = penguin_role_document()
    assert "LUCID SHOW/GET ONLY" in doctrine
    assert "LUCID has exactly 7 verbs:" in doctrine
    assert "MCP prompts and resources are discovery surfaces, not verbs." in doctrine
    assert "GET role verifies the binding" in doctrine
    assert "GET pulse reads current state" in doctrine
    assert "GET identity is not registered" in doctrine


@pytest.mark.parametrize(
    ("provider", "model"),
    [("penguin", "other"), ("other", "PENGUIN"), ("PENGUIN", "PENGUIN")],
)
def test_penguin_lookalikes_refuse(provider: str, model: str) -> None:
    with pytest.raises(ValueError, match="exact provider/model pair"):
        penguin_model_override(provider, model)


def test_penguin_model_role_is_cleared_with_session_context() -> None:
    from gateway.session_context import (
        clear_session_vars,
        get_agent_role,
        set_session_vars,
    )

    tokens = set_session_vars(model="PENGUIN", provider="penguin")
    assert get_agent_role() == "PENGUIN"
    clear_session_vars(tokens)
    assert get_agent_role() == ""


def test_penguin_agent_hides_hermes_skills_and_narrows_set_to_signin() -> None:
    def tool(name: str) -> dict:
        return {"type": "function", "function": {"name": name}}

    full_tools = [
        tool("terminal"),
        tool("skill_view"),
        tool("mcp__LUCID__get"),
        tool("mcp__LUCID__show"),
        tool("mcp__LUCID__set"),
        tool("mcp__LUCID__morph"),
        tool("mcp__LUCID__list_resources"),
        tool("mcp__LUCID__list_prompts"),
    ]
    agent = type("Agent", (), {"tools": full_tools, "_cached_system_prompt": "old"})()

    configure_penguin_agent(agent)

    assert agent._prompt_profile == "penguin"
    assert agent.valid_tool_names == {
        "mcp__LUCID__get",
        "mcp__LUCID__show",
        "mcp__LUCID__set",
    }
    assert [item["function"]["name"] for item in agent.tools] == [
        "mcp__LUCID__get",
        "mcp__LUCID__show",
        "mcp__LUCID__set",
    ]
    signin = agent.tools[2]["function"]
    assert signin["parameters"]["properties"]["path"] == {"const": "role"}
    assert signin["parameters"]["properties"]["value"]["properties"]["action"] == {
        "const": "signin"
    }

    clear_penguin_agent(agent)
    assert agent._prompt_profile == ""
    assert agent.tools == full_tools
