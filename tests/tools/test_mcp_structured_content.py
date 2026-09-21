"""Tests for MCP tool structuredContent preservation."""
from agent.generated.ae_glyphs import HAT_AI_AGENT
from agent.generated.ae_glyphs import OPERATION_STEER
from agent.generated.ae_glyphs import IDENTITY_PENGUIN
from agent.generated.ae_glyphs import ROLE_BUTLER
from agent.generated.ae_glyphs import ROLE_EM

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.tool_result_channels import SCHEMA, split_tool_result_channels
from tools import mcp_tool


class _FakeContentBlock:
    """Minimal content block with .text and .type attributes."""

    def __init__(self, text: str, block_type: str = "text"):
        self.text = text
        self.type = block_type


class _FakeCallToolResult:
    """Minimal CallToolResult stand-in.

    Uses camelCase ``structuredContent`` / ``isError`` to match the real
    MCP SDK Pydantic model (``mcp.types.CallToolResult``).
    """

    def __init__(self, content, is_error=False, structuredContent=None):
        self.content = content
        self.isError = is_error
        self.structuredContent = structuredContent


def _fake_run_on_mcp_loop(coro_or_factory, timeout=30):
    coro = coro_or_factory() if callable(coro_or_factory) else coro_or_factory
    """Run an MCP coroutine directly in a fresh event loop."""
    loop = asyncio.new_event_loop()
    try:
        # `_rpc_lock` must be created inside the loop that awaits it, or asyncio
        # raises "attached to a different loop". Build it here and attach it to
        # whatever fake server is currently registered under _servers.
        async def _install_lock_and_run():
            for srv in list(mcp_tool._servers.values()):
                if getattr(srv, "_rpc_lock", None) is None:
                    srv._rpc_lock = asyncio.Lock()
            return await coro
        return loop.run_until_complete(_install_lock_and_run())
    finally:
        loop.close()


def _assert_structured_result(raw, text, structured):
    presentation = {
        "__hermes_model_visible_result": text,
        "result": text,
        "structuredContent": structured,
    }
    assert json.loads(raw) == {
        "schema": SCHEMA,
        "model": text,
        "presentation": presentation,
    }
    model, projected = split_tool_result_channels(raw)
    assert model == text
    assert json.loads(projected) == presentation


@pytest.fixture
def _patch_mcp_server():
    """Patch _servers and the MCP event loop so _make_tool_handler can run."""
    fake_session = MagicMock()
    # `_rpc_lock` is acquired by _make_tool_handler's call path (mcp_tool.py
    # ~L2008) to serialize JSON-RPC against the server — build it inside the
    # fresh loop that _fake_run_on_mcp_loop spins up, not at fixture import.
    fake_server = SimpleNamespace(session=fake_session, _rpc_lock=None)
    with patch.dict(mcp_tool._servers, {"test-server": fake_server}), \
         patch("tools.mcp_tool._run_on_mcp_loop", side_effect=_fake_run_on_mcp_loop):
        yield fake_session


class TestStructuredContentPreservation:
    """Ensure structuredContent from CallToolResult is forwarded."""

    def test_text_only_result(self, _patch_mcp_server):
        """When no structuredContent, result is text-only (existing behaviour)."""
        session = _patch_mcp_server
        session.call_tool = AsyncMock(
            return_value=_FakeCallToolResult(
                content=[_FakeContentBlock("hello")],
            )
        )
        handler = mcp_tool._make_tool_handler("test-server", "my-tool", 30.0)
        raw = handler({})
        data = json.loads(raw)
        assert data == {"result": "hello"}

    def test_both_content_and_structured(self, _patch_mcp_server):
        """Preserve both channels without exposing structuredContent to the model."""
        session = _patch_mcp_server
        payload = {"value": "secret-123", "revealed": True}
        session.call_tool = AsyncMock(
            return_value=_FakeCallToolResult(
                content=[_FakeContentBlock("OK")],
                structuredContent=payload,
            )
        )
        handler = mcp_tool._make_tool_handler("test-server", "my-tool", 30.0)
        raw = handler({})
        _assert_structured_result(raw, "OK", payload)

    def test_both_content_and_structured_desktop_commander(self, _patch_mcp_server):
        """Real-world case: Desktop Commander returns file text in content,
        metadata in structuredContent.  Agent must see file contents."""
        session = _patch_mcp_server
        file_text = "import os\nprint('hello')\n"
        metadata = {"fileName": "main.py", "filePath": "/tmp/main.py", "fileType": "python"}
        session.call_tool = AsyncMock(
            return_value=_FakeCallToolResult(
                content=[_FakeContentBlock(file_text)],
                structuredContent=metadata,
            )
        )
        handler = mcp_tool._make_tool_handler("test-server", "my-tool", 30.0)
        raw = handler({})
        _assert_structured_result(raw, file_text, metadata)

    def test_structured_content_none_falls_back_to_text(self, _patch_mcp_server):
        """When structuredContent is explicitly None, fall back to text."""
        session = _patch_mcp_server
        session.call_tool = AsyncMock(
            return_value=_FakeCallToolResult(
                content=[_FakeContentBlock("done")],
                structuredContent=None,
            )
        )
        handler = mcp_tool._make_tool_handler("test-server", "my-tool", 30.0)
        raw = handler({})
        data = json.loads(raw)
        assert data == {"result": "done"}

    def test_empty_text_with_structured_content(self, _patch_mcp_server):
        """When content blocks are empty but structuredContent exists."""
        session = _patch_mcp_server
        payload = {"status": "ok", "data": [1, 2, 3]}
        session.call_tool = AsyncMock(
            return_value=_FakeCallToolResult(
                content=[],
                structuredContent=payload,
            )
        )
        handler = mcp_tool._make_tool_handler("test-server", "my-tool", 30.0)
        raw = handler({})
        _assert_structured_result(raw, "", payload)

    def test_application_refusal_does_not_trip_transport_breaker(self, _patch_mcp_server):
        session = _patch_mcp_server
        session.call_tool = AsyncMock(
            return_value=_FakeCallToolResult(
                content=[_FakeContentBlock("malformed-args")],
                is_error=True,
            )
        )
        mcp_tool._reset_server_error("test-server")
        handler = mcp_tool._make_tool_handler("test-server", "morph", 30.0)

        for _ in range(mcp_tool._CIRCUIT_BREAKER_THRESHOLD + 1):
            assert json.loads(handler({})) == {"error": "malformed-args"}

        assert session.call_tool.await_count == mcp_tool._CIRCUIT_BREAKER_THRESHOLD + 1
        assert mcp_tool._server_error_counts.get("test-server", 0) == 0
        assert "test-server" not in mcp_tool._server_breaker_opened_at

    def test_advertised_ugui_is_negotiated_and_preserved(self, _patch_mcp_server):
        session = _patch_mcp_server
        document = {
            "schema": "lucid-ugui-response/1",
            "id": "lucid.response",
            "type": "lucid",
            "header": [],
            "sections": [],
            "actions": [],
        }
        session.call_tool = AsyncMock(
            return_value=_FakeCallToolResult(content=[], structuredContent=document)
        )
        mcp_tool._servers["test-server"].initialize_result = SimpleNamespace(
            capabilities=SimpleNamespace(
                experimental={
                    "com.asg.lucid/response-modality": {
                        "revision": 1,
                        "default": "gestalt",
                        "modes": ["gestalt", "envelope", "ugui"],
                    }
                }
            )
        )

        handler = mcp_tool._make_tool_handler("test-server", "morph", 30.0)
        _assert_structured_result(handler({}), "", document)
        call = session.call_tool.await_args
        assert call is not None
        assert call.kwargs["meta"] == {
            "com.asg.lucid/response-modality": {"mode": "ugui"}
        }

    def test_advertised_host_context_binds_exact_agent_session_role(self, _patch_mcp_server):
        from gateway.session_context import bind_agent_role_from_system_prompt, set_session_vars

        session = _patch_mcp_server
        session.call_tool = AsyncMock(
            return_value=_FakeCallToolResult(content=[_FakeContentBlock("ok")])
        )
        mcp_tool._servers["test-server"].initialize_result = SimpleNamespace(
            capabilities=SimpleNamespace(
                experimental={
                    "com.asg.lucid/response-modality": {
                        "revision": 1,
                        "default": "gestalt",
                        "modes": ["gestalt", "envelope", "ugui"],
                    },
                    "com.asg.lucid/host-context": {
                        "revision": 3,
                        "identity_authority": "none",
                    }
                }
            )
        )
        set_session_vars(session_id="hermes-session-42")
        bind_agent_role_from_system_prompt(
            f"| **{ROLE_EM}{IDENTITY_PENGUIN} PROTOCOL** | **RULE** |"
        )

        handler = mcp_tool._make_tool_handler("test-server", "set", 30.0)
        assert json.loads(handler({"path": "role", "value": {"action": "signin"}})) == {
            "result": "ok"
        }
        call = session.call_tool.await_args
        assert call.kwargs["meta"] == {
            "com.asg.lucid/response-modality": {"mode": "ugui"},
            "com.asg.lucid/host-context": {
                "session_id": "hermes-session-42",
                "authority": "none",
                "bootstrap": {
                    "schema": "hermes-lucid-bootstrap-decision/1",
                    "action": "signin",
                    "role": "EM",
                    "role_session_id": "hermes-session-42",
                },
            }
        }

        session.call_tool.reset_mock()
        assert json.loads(mcp_tool._make_tool_handler("test-server", "get", 30.0)({
            "path": "role"
        })) == {"result": "ok"}
        ordinary = session.call_tool.await_args.kwargs["meta"][
            "com.asg.lucid/host-context"
        ]
        assert ordinary == {
            "session_id": "hermes-session-42",
            "authority": "none",
        }

    @pytest.mark.parametrize(
        ("header", "role"),
        [
            (f"| **{ROLE_EM}{IDENTITY_PENGUIN} PROTOCOL** | **RULE** |", "EM"),
            (f"| **{OPERATION_STEER}{IDENTITY_PENGUIN} PROTOCOL** | **RULE** |", "SIDEKICK"),
            (f"| **{ROLE_BUTLER}{IDENTITY_PENGUIN} PROTOCOL** | **RULE** |", "BUTLER"),
            (f"| **{HAT_AI_AGENT}{IDENTITY_PENGUIN} PROTOCOL** | **RULE** |", "ENGINEER"),
        ],
    )
    def test_host_context_bootstrap_preserves_each_closed_agent_role(
        self, _patch_mcp_server, header, role
    ):
        from gateway.session_context import bind_agent_role_from_system_prompt, set_session_vars

        server = mcp_tool._servers["test-server"]
        server.initialize_result = SimpleNamespace(
            capabilities=SimpleNamespace(
                experimental={
                    "com.asg.lucid/host-context": {
                        "revision": 3,
                        "identity_authority": "none",
                    }
                }
            )
        )
        set_session_vars(session_id="hermes-role-session")
        bind_agent_role_from_system_prompt(header)

        meta = mcp_tool._preferred_tool_call_meta(
            server,
            "set",
            {"path": "role", "value": {"action": "signin"}},
        )

        assert meta["com.asg.lucid/host-context"]["bootstrap"]["role"] == role

    def test_penguin_model_session_derives_read_only_lucid_bootstrap(
        self, _patch_mcp_server
    ):
        from gateway.session_context import (
            bind_agent_role_from_system_prompt,
            get_agent_role,
            set_session_vars,
        )

        server = mcp_tool._servers["test-server"]
        server.initialize_result = SimpleNamespace(
            capabilities=SimpleNamespace(
                experimental={
                    "com.asg.lucid/host-context": {
                        "revision": 3,
                        "identity_authority": "none",
                    }
                }
            )
        )
        set_session_vars(
            session_id="penguin-session",
            model="PENGUIN",
            provider="penguin",
        )
        bind_agent_role_from_system_prompt(
            f"| **{ROLE_EM}{IDENTITY_PENGUIN} PROTOCOL** | **RULE** |"
        )

        assert get_agent_role() == "PENGUIN"
        meta = mcp_tool._preferred_tool_call_meta(
            server,
            "set",
            {"path": "role", "value": {"action": "signin"}},
        )

        assert meta["com.asg.lucid/host-context"] == {
            "session_id": "penguin-session",
            "authority": "none",
            "bootstrap": {
                "schema": "hermes-lucid-bootstrap-decision/1",
                "action": "signin",
                "role": "PENGUIN",
                "role_session_id": "penguin-session",
            },
        }

    def test_legacy_server_receives_no_unadvertised_metadata(self, _patch_mcp_server):
        session = _patch_mcp_server
        session.call_tool = AsyncMock(
            return_value=_FakeCallToolResult(content=[_FakeContentBlock("ok")])
        )

        handler = mcp_tool._make_tool_handler("test-server", "tool", 30.0)
        assert json.loads(handler({})) == {"result": "ok"}
        call = session.call_tool.await_args
        assert call is not None
        assert "meta" not in call.kwargs
