import importlib.util
import json
from pathlib import Path

import pytest


@pytest.fixture
def module():
    path = Path(__file__).parents[2] / "agent" / "harness_capsule.py"
    spec = importlib.util.spec_from_file_location("ae_harness_capsule", path)
    assert spec is not None
    loaded = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(loaded)
    return loaded


def tool(name: str, description: str = "safe") -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": {}},
        },
    }


def test_observation_hashes_actual_schema_without_persisting_content(module):
    secret = "DO_NOT_PERSIST_SCHEMA_DESCRIPTION"
    tools = [tool("mcp__LUCID__get"), tool("write_file", secret)]
    first = module.observe_tool_schema(tools, observed_epoch=1000)
    second = module.observe_tool_schema(tools, observed_epoch=1000)
    assert first == second
    assert first["actual_tool_schema_hash"].startswith("sha256:")
    assert first["tool_count"] == 2
    assert first["lucid_tool_count"] == 1
    assert first["generic_equivalent_count"] == 1
    assert first["dual_surface"] is True
    assert first["content_included"] is False
    assert secret not in json.dumps(first)
    assert "tools" not in first


def test_agent_observation_emits_content_free_transport_without_writing_run_state(
    module, tmp_path, monkeypatch, capsys
):
    (tmp_path / "envelope").mkdir()
    (tmp_path / "envelope" / "HARNESS.json").write_text("{}", encoding="utf-8")
    (tmp_path / "envelope" / "LUCID.json").write_text("{}", encoding="utf-8")

    class Agent:
        tools = [tool("mcp__LUCID__show")]

    monkeypatch.chdir(tmp_path)
    module.observe_agent_tool_schema(Agent())
    line = capsys.readouterr().err.strip()
    assert line.startswith("CATALYST_TOOL_OBSERVATION ")
    observation = json.loads(line.removeprefix("CATALYST_TOOL_OBSERVATION "))
    assert observation["schema"] == "ae-catalyst-harness-tool-observation/1"
    assert observation["content_included"] is False
    assert not (tmp_path / "run").exists()


def test_agent_observation_is_inert_outside_ae(module, tmp_path, monkeypatch):
    class Agent:
        tools = [tool("terminal")]

    monkeypatch.chdir(tmp_path)
    module.observe_agent_tool_schema(Agent())
    assert not (tmp_path / "run").exists()


def test_invalid_clock_is_refused(module):
    with pytest.raises(ValueError, match="observed_epoch"):
        module.observe_tool_schema([], observed_epoch=0)
