from agent.verification_stop import (
    build_verify_on_stop_nudge,
    verify_on_stop_enabled,
)


def test_verify_on_stop_is_retired_even_when_legacy_config_requests_it(monkeypatch):
    monkeypatch.setenv("HERMES_VERIFY_ON_STOP", "1")
    assert verify_on_stop_enabled({"agent": {"verify_on_stop": True}}) is False


def test_verify_on_stop_never_synthesizes_repository_work():
    assert (
        build_verify_on_stop_nudge(
            session_id="session:test",
            changed_paths=["src/app.py"],
            attempts=0,
        )
        is None
    )
