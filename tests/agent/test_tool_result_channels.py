import json

from agent.tool_result_channels import (
    SCHEMA,
    encode_tool_result_channels,
    split_tool_result_channels,
)


def test_dual_channel_keeps_full_ugui_out_of_model_content():
    gestalt = "🟢 LUCID · get · onboarding · ready\n# The Penguin Protocol"
    ugui = {
        "schema": "lucid-ugui-response/1",
        "projectionForm": "detailed",
        "sections": [{"type": "text", "body": "# The Penguin Protocol"}],
    }

    encoded = encode_tool_result_channels(
        gestalt,
        {
            "__hermes_model_visible_result": gestalt,
            "result": gestalt,
            "structuredContent": ugui,
        },
    )
    assert json.loads(encoded)["schema"] == SCHEMA

    model, presentation = split_tool_result_channels(encoded)

    assert model == gestalt
    assert "structuredContent" not in model
    assert "lucid-ugui-response/1" not in model
    projected = json.loads(presentation)
    assert projected["__hermes_model_visible_result"] == gestalt
    assert projected["structuredContent"] == ugui
    assert projected["structuredContent"]["projectionForm"] == "detailed"


def test_ordinary_tool_results_pass_through_unchanged():
    ordinary = '{"result":"plain"}'
    assert split_tool_result_channels(ordinary) == (ordinary, ordinary)


def test_error_channel_remains_classifiable_without_leaking_presentation():
    gestalt = "🔴 · 🧠 · 🔎 ROLE-SESSION-REFUSED"
    encoded = encode_tool_result_channels(
        gestalt,
        {
            "__hermes_model_visible_result": gestalt,
            "error": gestalt,
            "structuredContent": {"schema": "lucid-ugui-response/1"},
        },
        is_error=True,
    )

    assert json.loads(encoded)["error"] == gestalt
    model, presentation = split_tool_result_channels(encoded)
    assert model == gestalt
    assert "structuredContent" not in model
    assert json.loads(presentation)["structuredContent"]["schema"] == "lucid-ugui-response/1"
