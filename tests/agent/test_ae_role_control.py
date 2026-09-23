from types import SimpleNamespace

import pytest

from agent.ae_role_control import RoleControlError, RoleControlReceiver

REVISION = "sha256:" + "a" * 64
CONTROL = "control:" + "b" * 64


def message(**changes):
    return {
        "id": CONTROL, "intent_delta": "Keep the original constraints.",
        "expected_revision": REVISION, "caller_role": "BUTLER",
        "expires_epoch": 9_000_000_000, **changes,
    }


class Host:
    def __init__(self, controls):
        self.controls = controls
        self.calls = []

    def __call__(self, params):
        self.calls.append(params)
        controls = self.controls if params["operation"] == "poll" else []
        if params["operation"] == "poll":
            self.controls = []
        return {"schema": "ae-role-control-host-result/1", "revision": REVISION, "controls": controls}


def agent(durable=True):
    def persist(messages, history):
        if durable:
            for item in messages:
                item["_db_persisted"] = True
    return SimpleNamespace(_interrupt_requested=False, _session_db=object(), _persist_session=persist)


def test_receipt_is_applied_only_after_context_persistence():
    host = Host([message()])
    receiver = RoleControlReceiver(agent(), host, "actual-session")
    messages = [{"role": "user", "content": "Original assignment"}]
    try:
        assert receiver.apply(messages)
        assert messages[-1]["_db_persisted"] is True
        assert "Keep the original constraints." in messages[-1]["content"]
        assert host.calls[-1]["status"] == "applied"
        assert host.calls[-1]["reason_code"] == "context-applied"
        assert not receiver.apply(messages)
    finally:
        receiver.close()
    assert host.calls[-1]["operation"] == "close"

def test_sidekick_can_deliver_broker_admitted_corrections():
    host = Host([message(caller_role="SIDEKICK")])
    receiver = RoleControlReceiver(agent(), host, "session")
    try:
        messages = []
        assert receiver.apply(messages)
        assert host.calls[-1]["status"] == "applied"
        assert len(messages) == 1
    finally:
        receiver.close()

def test_late_control_keeps_the_interim_answer_and_does_not_settle_it():
    host = Host([message()])
    target = agent()
    interim = []
    target._emit_interim_assistant_message = interim.append
    receiver = RoleControlReceiver(target, host, "session")
    messages = [{"role": "user", "content": "Original assignment"}]
    candidate = {"role": "assistant", "content": "Prior candidate", "finish_reason": "role_control_continue"}
    try:
        assert receiver.apply(messages, candidate=candidate)
        assert messages[-2] is candidate
        assert messages[-1]["role"] == "user"
        assert interim == [candidate]
        assert candidate["_db_persisted"]
        assert candidate["finish_reason"] == "role_control_continue"
    finally:
        receiver.close()


def test_durability_failure_is_unknown_and_never_claims_application():
    host = Host([message()])
    receiver = RoleControlReceiver(agent(False), host, "session")
    try:
        with pytest.raises(RoleControlError, match="durability-unconfirmed"):
            receiver.apply([])
        assert host.calls[-1]["status"] == "unknown"
        assert not any(call.get("status") == "applied" for call in host.calls)
    finally:
        receiver.close()


@pytest.mark.parametrize("change", [
    {"expected_revision": "sha256:" + "c" * 64},
    {"intent_delta": "x" * 4001},
    {"caller_role": "PENGUIN"},
    {"id": "arbitrary"},
])
def test_stale_malformed_or_unbounded_controls_never_enter_context(change):
    host = Host([message(**change)])
    receiver = RoleControlReceiver(agent(), host, "session")
    messages = []
    try:
        with pytest.raises(RoleControlError, match="delivery-invalid"):
            receiver.apply(messages)
        assert messages == []
        assert not any(call.get("status") == "applied" for call in host.calls)
    finally:
        receiver.close()


def test_cancel_and_expiry_do_not_apply_pending_control():
    host = Host([message(expires_epoch=1)])
    target = agent()
    receiver = RoleControlReceiver(target, host, "session")
    try:
        assert not receiver.apply([])
        assert host.calls[-1]["status"] == "rejected"
        target._interrupt_requested = True
        count = len(host.calls)
        assert not receiver.apply([])
        assert len(host.calls) == count
    finally:
        receiver.close()


def test_duplicate_delivery_is_idempotent_and_conflicts_are_rejected():
    host = Host([message(), message()])
    receiver = RoleControlReceiver(agent(), host, "session")
    messages = []
    try:
        assert receiver.apply(messages)
        assert len(messages) == 1
        host.controls = [message(intent_delta="Different correction")]
        with pytest.raises(RoleControlError, match="identity-conflict"):
            receiver.apply(messages)
        assert host.calls[-1]["status"] == "rejected"
        assert len(messages) == 1
    finally:
        receiver.close()


def test_applied_duplicate_remains_applied_after_its_deadline():
    host = Host([message()])
    receiver = RoleControlReceiver(agent(), host, "session")
    messages = []
    try:
        assert receiver.apply(messages)
        host.controls = [message(expires_epoch=1)]
        assert not receiver.apply(messages)
        assert len(messages) == 1
        assert host.calls[-1]["status"] == "applied"
    finally:
        receiver.close()


def test_offline_receiver_never_registers_or_reports_applied(caplog):
    def unavailable(_params):
        raise RuntimeError("offline")
    receiver = RoleControlReceiver(agent(), unavailable, "session")
    assert not receiver.apply([])
    assert receiver.revision is None
    assert receiver.unavailable == "role-control-receiver-unavailable"
    receiver.close()
    assert "no steering capability assumed" in caplog.text


def test_metadata_binds_only_after_a_valid_host_context_is_available(monkeypatch):
    from tools import mcp_tool
    from agent.ae_role_control import role_control_turn

    server = SimpleNamespace(session=object())
    monkeypatch.setitem(mcp_tool._servers, "LUCID", server)
    bound = {"com.asg.lucid/host-context": {"session_id": "host-session", "authority": "none"}}
    metadata = iter([{"modality": "text"}, bound])
    captured = []
    host = Host([])
    monkeypatch.setattr(mcp_tool, "_preferred_tool_call_meta", lambda _server: next(metadata))

    def request(params, context):
        captured.append(context)
        if context != bound:
            raise RuntimeError("role-control-host-context-unavailable")
        return host(params)

    monkeypatch.setattr(mcp_tool, "role_control_host_request", request)
    target = agent()
    target.session_id = "session"
    with role_control_turn(target) as receiver:
        assert not receiver.apply([])
        assert receiver.revision is None
        assert not receiver.apply([])
        assert receiver.revision == REVISION
        assert not receiver.apply([])
    assert captured == [{"modality": "text"}, bound, bound, bound]
    assert target._ae_role_control is None


def test_settlement_disconnect_is_a_control_error_not_a_model_retry():
    host = Host([message()])

    def request(params):
        if params["operation"] == "settle":
            raise OSError("transport closed")
        return host(params)

    receiver = RoleControlReceiver(agent(), request, "session")
    try:
        with pytest.raises(RoleControlError, match="settle-unconfirmed"):
            receiver.apply([])
        assert receiver.seen == {CONTROL: "Keep the original constraints."}
    finally:
        receiver.close()


def test_native_close_failure_does_not_cancel_or_replay_the_existing_turn(caplog):
    from agent.ae_role_control import native_role_control_callback

    host = Host([message()])
    target = agent()

    def request(params):
        if params["operation"] == "close":
            raise OSError("transport closed")
        return host(params)

    receiver = RoleControlReceiver(target, request, "session")
    target._ae_role_control = receiver
    attempts = []

    def deliver(text):
        attempts.append(text)
        raise RuntimeError("delivery unknown")

    callback = native_role_control_callback(target, [])
    assert callback(SimpleNamespace(request_steer_bound=deliver)) is False
    assert attempts == ["Keep the original constraints."]
    assert receiver.closed
    assert not target._interrupt_requested
    assert "close unconfirmed" in caplog.text


def test_native_transport_requires_matching_turn_ack_without_interrupting():
    from agent.transports.codex_app_server_session import CodexAppServerSession
    import threading

    requests = []
    session = object.__new__(CodexAppServerSession)
    session._active_turn_lock = threading.Lock()
    session._active_turn_id = "native-turn"
    session._thread_id = "native-thread"
    session._interrupt_event = threading.Event()
    class Client:
        response = {"turnId": "native-turn"}
        def request(self, method, params, timeout):
            requests.append((method, params))
            return self.response
    client = Client()
    session._client = client
    session.request_steer_bound("Continue with the correction")
    assert requests[0][0] == "turn/steer"
    assert requests[0][1]["expectedTurnId"] == "native-turn"
    client.response = {}
    with pytest.raises(RuntimeError, match="acknowledgement-unknown"):
        session.request_steer_bound("No assumed acceptance")
    assert not session._interrupt_event.is_set()
    assert all(method == "turn/steer" for method, _ in requests)


def test_native_delivery_failure_retains_an_unknown_receipt():
    host = Host([message()])
    receiver = RoleControlReceiver(agent(), host, "session")
    def failed(_text):
        raise RuntimeError("native delivery unknown")
    try:
        with pytest.raises(RoleControlError, match="native-context-unconfirmed"):
            receiver.apply([], native_delivery=failed)
        assert host.calls[-1]["status"] == "unknown"
    finally:
        receiver.close()


def test_negotiated_host_transport_uses_private_method_and_exact_context(monkeypatch):
    import asyncio
    from tools import mcp_tool
    from mcp.types import Result

    requests = []
    class Session:
        async def send_request(self, request, result_type, **kwargs):
            requests.append(request.model_dump(by_alias=True, exclude_none=True))
            return Result.model_validate({
                "schema": "ae-role-control-host-result/1", "revision": REVISION, "controls": [],
            })
    server = SimpleNamespace(session=Session(), initialize_result=SimpleNamespace(
        capabilities={"experimental": {"com.asg.lucid/role-control-host": {"schema": "ae-role-control-host/1"}}}
    ))
    monkeypatch.setitem(mcp_tool._servers, "LUCID", server)
    monkeypatch.setattr(mcp_tool, "_run_on_mcp_loop", lambda factory, timeout: asyncio.run(factory()))
    metadata = {"com.asg.lucid/host-context": {"session_id": "host-session", "authority": "none"}}
    params = {"operation": "poll", "harness": "catalyst", "runtime_session_id": "runtime", "execution_id": "turn", "revision": 1}
    response = mcp_tool.role_control_host_request(params, metadata)
    assert response["revision"] == REVISION
    assert requests[0]["method"] == "role/control"
    assert requests[0]["params"]["_meta"] == metadata
    assert "name" not in requests[0]["params"]
    assert "bootstrap" not in str(requests[0])
    with pytest.raises(ValueError, match="authority-injection"):
        mcp_tool.role_control_host_request({**params, "localCapability": {}}, metadata)


@pytest.mark.parametrize("error_name", ["BrokenResourceError", "ClosedResourceError", "EndOfStream"])
def test_private_transport_resource_errors_are_explicit(monkeypatch, error_name):
    import anyio
    from tools import mcp_tool

    server = SimpleNamespace(session=object(), initialize_result=SimpleNamespace(
        capabilities={"experimental": {"com.asg.lucid/role-control-host": {"schema": "ae-role-control-host/1"}}}
    ))
    monkeypatch.setitem(mcp_tool._servers, "LUCID", server)

    def unavailable(_factory, timeout):
        raise getattr(anyio, error_name)()

    monkeypatch.setattr(mcp_tool, "_run_on_mcp_loop", unavailable)
    metadata = {"com.asg.lucid/host-context": {"session_id": "host-session", "authority": "none"}}
    with pytest.raises(RuntimeError, match="transport-unavailable"):
        mcp_tool.role_control_host_request({"operation": "poll"}, metadata)


@pytest.mark.parametrize("boundary", ["after-tool", "candidate-final"])
def test_real_conversation_loop_applies_controls_and_durably_delivers_only_the_final_answer(
    monkeypatch, tmp_path, boundary
):
    from copy import deepcopy
    from unittest.mock import MagicMock, patch
    from hermes_state import SessionDB
    from run_agent import AIAgent
    from tools import mcp_tool

    tool = {"type": "function", "function": {
        "name": "web_search", "description": "Fixture tool",
        "parameters": {"type": "object", "properties": {}},
    }}
    db = SessionDB(tmp_path / "controls.db")
    with (
        patch("run_agent.get_tool_definitions", return_value=[tool]),
        patch("run_agent.check_toolset_requirements", return_value={}),
        patch("run_agent.OpenAI"),
    ):
        target = AIAgent(
            api_key="fixture", base_url="http://127.0.0.1:9/v1",
            provider="openai", api_mode="chat_completions",
            model="fixture", quiet_mode=True, skip_context_files=True,
            skip_memory=True, max_iterations=3, session_db=db,
        )
    target.client = MagicMock()
    target._cached_system_prompt = "Fixture system."
    target._use_prompt_caching = False
    target._disable_streaming = True
    target.tool_delay = 0
    target.save_trajectories = False
    target.compression_enabled = False
    host = Host([])
    monkeypatch.setitem(mcp_tool._servers, "LUCID", SimpleNamespace(session=object()))
    monkeypatch.setattr(mcp_tool, "_preferred_tool_call_meta", lambda _server: {
        "com.asg.lucid/host-context": {"session_id": "host-session", "authority": "none"},
    })
    monkeypatch.setattr(mcp_tool, "role_control_host_request", lambda params, _meta: host(params))
    requests = []
    effects = []

    def execute(name, arguments, task_id=None, **_kwargs):
        effects.append(name)
        host.controls = [message()]
        return '{"observed":true}'

    def respond(**params):
        requests.append(deepcopy(params["messages"]))
        first = len(requests) == 1
        tool_calls = None
        if first and boundary == "after-tool":
            tool_calls = [SimpleNamespace(
                id="fixture-call", type="function",
                function=SimpleNamespace(name="web_search", arguments="{}"),
            )]
        elif first:
            host.controls = [message()]
        content = "prior candidate" if first else "corrected final"
        response = SimpleNamespace(content=content, reasoning_content=None, reasoning=None, tool_calls=tool_calls)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=response, finish_reason="tool_calls" if tool_calls else "stop")],
            model="fixture", usage=None,
        )

    target.client.chat.completions.create.side_effect = respond
    try:
        with (
            patch("run_agent.handle_function_call", execute),
            patch.object(target, "_spawn_background_review", return_value=None),
            patch.object(target, "_cleanup_task_resources"),
        ):
            result = target.run_conversation("Original assignment")
        assert result["completed"] is True
        assert result["final_response"] == "corrected final"
        assert len(requests) == 2
        correction = requests[1][-1]
        assert correction["role"] == "user"
        assert "Keep the original constraints." in correction["content"]
        assert effects == (["web_search"] if boundary == "after-tool" else [])
        assert requests[1][-2]["role"] == ("tool" if boundary == "after-tool" else "assistant")
        assert not target._interrupt_requested
        assert host.calls[-1]["operation"] == "close"
        assert [call["status"] for call in host.calls if call["operation"] == "settle"] == ["applied"]
        stored = db.get_messages(target.session_id)
        assert stored[-1]["content"] == "corrected final"
        assert len([row for row in stored if "Keep the original constraints." in (row["content"] or "")]) == 1
    finally:
        db.close()
