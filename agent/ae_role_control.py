"""Authenticated role corrections consumed only at model-decision boundaries."""

from __future__ import annotations

import logging
import re
import threading
import time
import uuid
from contextlib import contextmanager
from typing import Callable

logger = logging.getLogger(__name__)
_ID = re.compile(r"control:[0-9a-f]{64}\Z")
_REVISION = re.compile(r"sha256:[0-9a-f]{64}\Z")
_SESSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,191}\Z")


class RoleControlError(RuntimeError):
    pass


class RoleControlReceiver:
    def __init__(self, agent, request: Callable[[dict], dict], session_id: str):
        if not _SESSION.fullmatch(session_id):
            raise RoleControlError("role-control-runtime-session-invalid")
        self.agent = agent
        self.request = request
        self.base = {
            "harness": "catalyst",
            "runtime_session_id": session_id,
            "execution_id": f"turn-{uuid.uuid4().hex}",
            "revision": time.time_ns() // 1000,
        }
        self.revision: str | None = None
        self.seen: dict[str, str] = {}
        self.closed = False
        self.unavailable: str | None = None
        self.stop = threading.Event()
        self.heartbeat: threading.Thread | None = None
        self.heartbeat_error: str | None = None

    def _call(self, operation: str, **fields) -> dict:
        try:
            result = self.request({**self.base, "operation": operation, **fields})
        except (RuntimeError, ValueError, OSError):
            raise RoleControlError(f"role-control-{operation}-unconfirmed") from None
        if not isinstance(result, dict):
            raise RoleControlError("role-control-response-invalid")
        revision = result.get("revision")
        if (
            result.get("schema") != "ae-role-control-host-result/1"
            or not isinstance(revision, str)
            or not _REVISION.fullmatch(revision)
            or self.revision is not None and revision != self.revision
        ):
            raise RoleControlError("role-control-receiver-revision-mismatch")
        self.revision = revision
        return result

    def _ack(self, control_id: str, status: str, reason: str) -> None:
        self._call("settle", control_id=control_id, status=status, reason_code=reason)

    def _heartbeat(self) -> None:
        while not self.stop.wait(30):
            try:
                self._call("observe")
            except (RuntimeError, ValueError, OSError) as error:
                self.heartbeat_error = type(error).__name__
                logger.warning("role-control heartbeat unavailable; no automatic redelivery")
                return

    def apply(self, messages: list[dict], history=None, native_delivery=None, candidate=None) -> bool:
        if self.closed or getattr(self.agent, "_interrupt_requested", False):
            return False
        if self.heartbeat_error is not None:
            raise RoleControlError("role-control-heartbeat-unavailable")
        try:
            result = self._call("poll")
        except (RuntimeError, ValueError, OSError):
            if self.revision is not None:
                raise RoleControlError("role-control-active-delivery-unavailable") from None
            if self.unavailable is None:
                self.unavailable = "role-control-receiver-unavailable"
                logger.warning("role-control receiver unavailable; no steering capability assumed")
            return False
        if self.heartbeat is None:
            self.heartbeat = threading.Thread(target=self._heartbeat, name="role-control-heartbeat", daemon=True)
            self.heartbeat.start()
        self.unavailable = None
        controls = result.get("controls")
        if not isinstance(controls, list) or len(controls) > 8:
            raise RoleControlError("role-control-delivery-bound")
        applied = False
        for control in controls:
            if (
                not isinstance(control, dict)
                or set(control) != {"id", "intent_delta", "expected_revision", "caller_role", "expires_epoch"}
                or not isinstance(control["id"], str)
                or not _ID.fullmatch(control["id"])
                or not isinstance(control["intent_delta"], str)
                or not control["intent_delta"].strip()
                or len(control["intent_delta"].encode("utf-8")) > 4000
                or "\0" in control["intent_delta"]
                or control["expected_revision"] != self.revision
                or control["caller_role"] not in {"BUTLER", "EM", "SIDEKICK", "WITNESS"}
                or type(control["expires_epoch"]) is not int
            ):
                raise RoleControlError("role-control-delivery-invalid")
            control_id = control["id"]
            text = control["intent_delta"]
            if control_id in self.seen:
                status = "applied" if self.seen[control_id] == text else "rejected"
                self._ack(control_id, status, "context-applied" if status == "applied" else "identity-conflict")
                if status == "rejected":
                    raise RoleControlError("role-control-identity-conflict")
                continue
            if getattr(self.agent, "_interrupt_requested", False) or control["expires_epoch"] <= time.time():
                self._ack(control_id, "rejected", "cancelled-or-expired")
                continue
            if len(self.seen) >= 32 or getattr(self.agent, "_session_db", None) is None:
                self._ack(control_id, "rejected", "context-storage-unavailable")
                raise RoleControlError("role-control-context-storage-unavailable")
            message = {
                "role": "user",
                "content": (
                    "[Authenticated in-flight correction; preserve the original assignment and authority.]\n"
                    + text
                ),
            }
            if candidate is not None:
                messages.append(candidate)
            messages.append(message)
            self.agent._persist_session(messages, history)
            if not message.get("_db_persisted"):
                self._ack(control_id, "unknown", "context-durability-unconfirmed")
                raise RoleControlError("role-control-context-durability-unconfirmed")
            if native_delivery is not None:
                try:
                    native_delivery(text)
                except (RuntimeError, ValueError, OSError):
                    self._ack(control_id, "unknown", "native-context-unconfirmed")
                    raise RoleControlError("role-control-native-context-unconfirmed") from None
            self.seen[control_id] = text
            self._ack(control_id, "applied", "context-applied")
            if candidate is not None:
                self.agent._emit_interim_assistant_message(candidate)
                candidate = None
            applied = True
        return applied

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.stop.set()
        if self.heartbeat is not None:
            self.heartbeat.join(timeout=7)
            if self.heartbeat.is_alive():
                raise RoleControlError("role-control-heartbeat-close-unconfirmed")
        if self.revision is not None:
            self._call("close")


@contextmanager
def role_control_turn(agent):
    from tools.mcp_tool import _preferred_tool_call_meta, _servers, _lock, role_control_host_request

    with _lock:
        server = _servers.get("LUCID")
    metadata = None
    session_id = str(getattr(agent, "session_id", "") or "")
    receiver = None
    if server is not None and _SESSION.fullmatch(session_id):
        def request(params):
            nonlocal metadata
            if metadata is None:
                candidate = _preferred_tool_call_meta(server)
                context = candidate.get("com.asg.lucid/host-context") if isinstance(candidate, dict) else None
                if isinstance(context, dict) and context.get("authority") == "none" and context.get("session_id"):
                    metadata = candidate
                return role_control_host_request(params, candidate)
            return role_control_host_request(params, metadata)
        receiver = RoleControlReceiver(
            agent, request, session_id
        )
    previous = getattr(agent, "_ae_role_control", None)
    agent._ae_role_control = receiver
    try:
        yield receiver
    finally:
        agent._ae_role_control = previous
        if receiver is not None:
            try:
                receiver.close()
            except (RuntimeError, ValueError, OSError):
                logger.warning("role-control close unconfirmed; inspect the exact receipt before any replay")


def apply_role_controls(agent, messages: list[dict], history=None, candidate=None) -> bool:
    receiver = getattr(agent, "_ae_role_control", None)
    return receiver.apply(messages, history, candidate=candidate) if receiver is not None else False


def native_role_control_callback(agent, messages: list[dict]):
    receiver = getattr(agent, "_ae_role_control", None)
    if receiver is None:
        return None

    def apply(session):
        try:
            receiver.apply(messages, native_delivery=session.request_steer_bound)
        except RoleControlError:
            logger.warning("native role control unconfirmed; the existing turn is not cancelled or replayed")
            try:
                receiver.close()
            except RoleControlError:
                logger.warning("native role control close unconfirmed; inspect the exact receipt before any replay")
            return False
        return True

    return apply
