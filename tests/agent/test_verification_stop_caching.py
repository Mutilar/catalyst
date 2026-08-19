"""Pre-final attestation correction scaffolding is never durable."""

import json
import sys
from datetime import datetime
from unittest.mock import MagicMock


def _fresh_run_agent(hermes_home):
    del hermes_home
    for mod in list(sys.modules):
        if mod == "run_agent" or mod.startswith("tools."):
            del sys.modules[mod]
    import run_agent  # noqa: F401

    return sys.modules["run_agent"]


def _make_agent(ra, session_id, tmp_path):
    agent = object.__new__(ra.AIAgent)
    agent.session_id = session_id
    agent.model = "test-model"
    agent.base_url = "http://127.0.0.1"
    agent.platform = "test"
    agent.session_start = datetime.now()
    agent._cached_system_prompt = ""
    agent.tools = []
    agent.verbose_logging = False
    agent._clean_session_content = lambda content: content
    agent._redact_message_content = lambda content: content
    agent._session_db = MagicMock()
    agent._session_db_created = True
    agent._session_json_enabled = True
    agent.logs_dir = tmp_path / "logs"
    agent.logs_dir.mkdir(parents=True, exist_ok=True)
    return agent


def _messages():
    return [
        {"role": "user", "content": "finish"},
        {
            "role": "assistant",
            "content": "candidate missing suffix",
            "_pre_final_synthetic": True,
        },
        {
            "role": "user",
            "content": "[System: correct the terminal token]",
            "_pre_final_synthetic": True,
        },
        {"role": "assistant", "content": "corrected 🎼🐧"},
    ]


def test_pre_final_flag_is_ephemeral(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    ra = _fresh_run_agent(tmp_path)
    assert "_pre_final_synthetic" in ra._EPHEMERAL_SCAFFOLDING_FLAGS
    assert "_verification_stop_synthetic" not in ra._EPHEMERAL_SCAFFOLDING_FLAGS
    assert ra._is_ephemeral_scaffolding(_messages()[1])
    assert ra._is_ephemeral_scaffolding(_messages()[2])


def test_db_flush_drops_candidate_and_nudge(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    ra = _fresh_run_agent(tmp_path)
    agent = _make_agent(ra, "sess_db", tmp_path)
    agent._flush_messages_to_session_db(_messages(), conversation_history=[])
    persisted = [kwargs.get("content") for _args, kwargs in agent._session_db.append_message.call_args_list]
    assert persisted == ["finish", "corrected 🎼🐧"]


def test_json_log_drops_candidate_and_nudge(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    ra = _fresh_run_agent(tmp_path)
    agent = _make_agent(ra, "sess_json", tmp_path)
    agent._save_session_log(_messages())
    data = json.loads((agent.logs_dir / "session_sess_json.json").read_text(encoding="utf-8"))
    assert [message.get("content") for message in data["messages"]] == [
        "finish",
        "corrected 🎼🐧",
    ]
