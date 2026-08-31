"""End-to-end coverage for bounded pre-final attestation correction."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from run_agent import AIAgent


def _response(content):
    message = SimpleNamespace(content=content, tool_calls=None)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason="stop")],
        model="test/model",
        usage=None,
    )


@pytest.fixture
def agent(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    with (
        patch("run_agent.get_tool_definitions", return_value=[]),
        patch("run_agent.check_toolset_requirements", return_value={}),
        patch("run_agent.OpenAI"),
    ):
        instance = AIAgent(
            session_id="attestation-test",
            api_key="test-key",
            base_url="https://example.invalid/v1",
            provider="openai-compat",
            model="test/model",
            max_iterations=2,
            quiet_mode=True,
            skip_context_files=True,
            skip_memory=True,
        )
    instance._cached_system_prompt = "stable test prompt"
    instance._session_db = None
    instance._session_json_enabled = False
    instance.save_trajectories = False
    instance.compression_enabled = False
    instance._cleanup_task_resources = lambda *_a, **_kw: None
    instance._save_trajectory = lambda *_a, **_kw: None
    return instance


def test_missing_attestation_retains_candidate_and_control_lineage(agent):
    answers = iter([_response("substantive answer"), _response("substantive answer 🎼🐧")])
    agent._interruptible_api_call = lambda _kwargs: next(answers)
    agent._handle_max_iterations = MagicMock(return_value="replacement summary")

    with (
        patch("agent.coding_context.project_facts_for", return_value={"root": "/repo"}),
        patch("hermes_cli.plugins.has_hook", side_effect=lambda name: name == "pre_final"),
        patch(
            "hermes_cli.plugins.get_pre_final_decision",
            side_effect=[
                {"action": "continue", "message": "correct terminal attestation"},
                None,
            ],
        ) as correction,
        patch("hermes_cli.plugins.invoke_hook", return_value=[]),
    ):
        result = agent.run_conversation("finish")

    assert result["final_response"] == "substantive answer 🎼🐧"
    assert result["completed"] is True
    assert correction.call_count == 2
    assert [message["role"] for message in result["messages"]] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert result["messages"][1]["_finalization_lineage"] == "candidate"
    assert result["messages"][2]["_finalization_lineage"] == "control"
    assert result["messages"][2]["name"] == "HARNESS"


def test_attested_final_does_not_add_a_turn(agent):
    agent._interruptible_api_call = lambda _kwargs: _response("done 🎼🐧")
    with (
        patch("agent.coding_context.project_facts_for", return_value={"root": "/repo"}),
        patch("hermes_cli.plugins.has_hook", side_effect=lambda name: name == "pre_final"),
        patch(
            "hermes_cli.plugins.get_pre_final_decision",
            return_value=None,
        ) as correction,
        patch("hermes_cli.plugins.invoke_hook", return_value=[]),
    ):
        result = agent.run_conversation("finish")
    assert result["final_response"] == "done 🎼🐧"
    correction.assert_called_once()


def test_unattested_candidate_is_not_budget_fallback(agent):
    agent.max_iterations = 1
    agent.iteration_budget.max_total = 1
    agent._interruptible_api_call = lambda _kwargs: _response("missing suffix")
    agent._handle_max_iterations = MagicMock(return_value="bounded failure summary")
    with (
        patch("agent.coding_context.project_facts_for", return_value={"root": "/repo"}),
        patch("hermes_cli.plugins.has_hook", side_effect=lambda name: name == "pre_final"),
        patch(
            "hermes_cli.plugins.get_pre_final_decision",
            return_value={"action": "continue", "message": "correct terminal attestation"},
        ),
        patch("hermes_cli.plugins.invoke_hook", return_value=[]),
    ):
        result = agent.run_conversation("finish")
    assert result["final_response"] != "missing suffix"
    assert result["completed"] is False


def test_terminal_attestation_block_replaces_candidate_without_another_model_turn(agent):
    agent._interruptible_api_call = MagicMock(return_value=_response("drifted candidate"))
    with (
        patch("agent.coding_context.project_facts_for", return_value={"root": "/repo"}),
        patch("hermes_cli.plugins.has_hook", side_effect=lambda name: name == "pre_final"),
        patch(
            "hermes_cli.plugins.get_pre_final_decision",
            return_value={"action": "block", "message": "🔴 · 🧠 · 🔎 ROLE-SESSION-OFFLINE"},
        ),
        patch("hermes_cli.plugins.invoke_hook", return_value=[]),
    ):
        result = agent.run_conversation("finish")
    assert result["final_response"] == "🔴 · 🧠 · 🔎 ROLE-SESSION-OFFLINE"
    assert agent._interruptible_api_call.call_count == 1
    with pytest.raises(RuntimeError, match="ROLE-SESSION-OFFLINE"):
        agent.run_conversation("try to continue")
    assert agent._interruptible_api_call.call_count == 1
