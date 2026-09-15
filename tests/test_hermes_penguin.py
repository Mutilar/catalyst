from __future__ import annotations
from agent.generated.ae_glyphs import DELIMITER_SEGMENT, IDENTITY_PENGUIN

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

import hermes_penguin
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


@pytest.fixture
def penguin_vocabulary_source(tmp_path, monkeypatch):
    monkeypatch.setattr(hermes_penguin, "__file__", str(tmp_path / "catalyst/hermes_penguin.py"))
    (tmp_path / "PENGUIN.md").write_text(
        "<!-- GENERATED -->\n"
        f"| **{IDENTITY_PENGUIN}{IDENTITY_PENGUIN} PROTOCOL** | **RULE** |\n",
        encoding="utf-8",
    )
    (tmp_path / "envelope").mkdir()
    source = tmp_path / "envelope/LUCID.json"
    source.write_text(json.dumps({
        "verbs": {verb: {} for verb in ["show", "get", "set", "morph", "dispatch", "steer", "cancel"]},
        "get_registry": {"targets": [{"id": "role"}, {"id": "pulse"}]},
    }), encoding="utf-8")
    return source


def test_penguin_vocabulary_formatting_above_old_cap_preserves_prompt(penguin_vocabulary_source) -> None:
    expected = penguin_role_document()
    source = penguin_vocabulary_source.read_bytes()
    penguin_vocabulary_source.write_bytes(b" " * (512 * 1024) + source)

    assert penguin_role_document() == expected


def test_penguin_vocabulary_accepts_exact_source_limit(penguin_vocabulary_source) -> None:
    expected = penguin_role_document()
    source = penguin_vocabulary_source.read_bytes()
    penguin_vocabulary_source.write_bytes(
        source + b" " * (hermes_penguin._MAX_LUCID_BYTES - len(source))
    )

    assert penguin_role_document() == expected


@pytest.mark.parametrize("size", [0, hermes_penguin._MAX_LUCID_BYTES + 1])
def test_penguin_vocabulary_rejects_empty_and_oversized_sources(penguin_vocabulary_source, size) -> None:
    penguin_vocabulary_source.write_bytes(b" " * size)

    with pytest.raises(ValueError, match=rf"outside its byte bound.*{hermes_penguin._MAX_LUCID_BYTES}"):
        penguin_role_document()


def test_picker_row_is_one_authenticated_closed_penguin_model() -> None:
    row = penguin_picker_row(
        current_provider=PENGUIN_PROVIDER_ID,
        current_model=PENGUIN_MODEL_ID,
    )

    assert row["slug"] == "penguin"
    assert row["name"] == "Microsoft Applied Sciences"
    assert row["model_labels"] == {"PENGUIN": f"{IDENTITY_PENGUIN}"}
    assert row["model_annotations"]["PENGUIN"] == [
        {"label": "Role", "value": "PENGUIN"},
        {"label": "Runtime", "value": "Local MLX"},
            {"label": "Grants", "value": DELIMITER_SEGMENT.join(("GET", "SHOW"))},
    ]
    assert row["models"] == ["PENGUIN"]
    assert row["authenticated"] is True
    assert row["is_current"] is True
    assert row["capabilities"] == {"PENGUIN": {"fast": False, "reasoning": True}}


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


@pytest.mark.parametrize("configured_thinking", [None, False, True])
def test_penguin_agent_requests_thinking_with_tools_without_changing_other_modes(configured_thinking, monkeypatch) -> None:
    from agent.chat_completion_helpers import build_api_kwargs
    from agent.transports.chat_completions import ChatCompletionsTransport
    from tui_gateway.prompt_intent import penguin_request

    template = {"preserve_other_option": True}
    if configured_thinking is not None:
        template["enable_thinking"] = configured_thinking
    overrides = {"extra_body": {"chat_template_kwargs": template, "repetition_penalty": 1.05}}
    original_overrides = deepcopy(overrides)
    tools = [{"type": "function", "function": {"name": name,
        "description": "fixture", "parameters": {"type": "object", "properties": {}}}}
        for name in ("mcp__LUCID__get", "mcp__LUCID__show", "mcp__LUCID__set", "terminal")]
    transport = ChatCompletionsTransport()
    agent = SimpleNamespace(
        provider="custom", model=PENGUIN_MODEL_ID, _wire_model=PENGUIN_WIRE_MODEL_ID,
        base_url=PENGUIN_BASE_URL, _base_url_lower=PENGUIN_BASE_URL.lower(),
        api_mode="chat_completions", tools=tools, request_overrides=overrides,
        reasoning_config={"enabled": False}, max_tokens=4096, _ollama_num_ctx=None,
        providers_allowed=None, providers_ignored=None, providers_order=None, provider_sort=None,
        provider_require_parameters=False, provider_data_collection=None, openrouter_min_coding_score=None,
        _get_transport=lambda: transport, _is_qwen_portal=lambda: False, _is_openrouter_url=lambda: False,
        _resolved_api_call_timeout=lambda: 120, _max_tokens_param=lambda maximum: {"max_tokens": maximum},
        _prepare_messages_for_non_vision_model=lambda messages: messages,
        _supports_reasoning_extra_body=lambda: False,
    )
    messages = [{"role": "user", "content": "Read current role using the registered tool"}]
    baseline = build_api_kwargs(agent, messages)
    configure_penguin_agent(agent)
    request = build_api_kwargs(agent, messages)
    assert request["model"] == PENGUIN_WIRE_MODEL_ID
    assert request["messages"] == messages
    assert request["extra_body"]["chat_template_kwargs"] == {
        "preserve_other_option": True, "enable_thinking": True,
    }
    assert request["extra_body"]["repetition_penalty"] == 1.05
    assert request["tools"] == agent.tools
    assert len(request["tools"]) == 3
    assert request.get("tool_choice") != "none"
    assert request["max_tokens"] == 4096
    assert overrides == original_overrides
    assert agent.request_overrides == original_overrides
    followup_messages = messages + [
        {"role": "assistant", "content": None, "reasoning_content": "fixture reasoning",
            "tool_calls": [{"id": "call-1", "type": "function", "function": {
                "name": "mcp__LUCID__get", "arguments": '{"path":"role"}'}}]},
        {"role": "tool", "tool_call_id": "call-1", "content": "fixture role observed"},
    ]
    followup = build_api_kwargs(agent, followup_messages)
    assert followup["extra_body"] == request["extra_body"]
    assert followup["messages"] == followup_messages
    assert followup["tools"] == request["tools"]
    for field, value in [("model", "other-model"), ("_wire_model", "other-model"),
        ("base_url", "https://provider.example/v1")]:
        with monkeypatch.context() as context:
            context.setattr(agent, field, value)
            other = build_api_kwargs(agent, messages)
            assert other["extra_body"]["chat_template_kwargs"] == template
    for stage in ("classification", "semantic-preparation"):
        preprocessing = penguin_request("Hi", "stage instruction", 1028, stage=stage)
        assert preprocessing["chat_template_kwargs"] == {"enable_thinking": False}
        assert preprocessing["tools"] == [] and preprocessing["tool_choice"] == "none"
    clear_penguin_agent(agent)
    assert build_api_kwargs(agent, messages) == baseline
