import hashlib
import json

import pytest

from hermes_cli.ugui_actions import (
    UguiActionError,
    compile_lucid_ugui_action,
    execute_lucid_ugui_action,
)


DISPATCH_ID = f"dispatch:{'b' * 64}"
PARENT_HASH = f"sha256:{'a' * 64}"


def document(action):
    return {
        "schema": "lucid-ugui-response/1",
        "id": "lucid.dispatch.response",
        "type": "lucid",
        "header": [],
        "sections": [],
        "actions": [action],
        "provenance": {"parentHash": PARENT_HASH},
        "receipt": {
            "action_provenance": [
                {
                    "id": action["id"],
                    "state": "AVAILABLE",
                    "provenance_hash": PARENT_HASH,
                }
            ]
        },
    }


def show_action():
    return {
        "id": "lucid.response.execution",
        "action": "lucid.show.execution",
        "value": DISPATCH_ID,
        "intent": {
            "verb": "show",
            "arguments": {"view": "execution", "id": DISPATCH_ID},
        },
    }


def cancel_action():
    return {
        "id": "lucid.response.cancel",
        "action": "lucid.cancel.dispatch",
        "value": DISPATCH_ID,
        "requiresConfirmation": "exact",
        "intent": {
            "verb": "cancel",
            "arguments": {"task": "fleet.dispatch", "dispatch_id": DISPATCH_ID},
        },
    }


def dispatch_plan_action():
    request = {"$schema": "ae-dispatch/1", "intent": "bounded fixture"}
    canonical = json.dumps(request, ensure_ascii=False, separators=(",", ":"))
    request_hash = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return {
        "id": "lucid.response.dispatch-plan",
        "action": "lucid.dispatch.plan",
        "value": request_hash,
        "requiresConfirmation": "exact",
        "intent": {
            "verb": "dispatch",
            "arguments": {"task": "engineer", "request": request, "scope": "this"},
        },
    }


def host_role_action():
    return {
        "id": "lucid.response.switch-to-sidekick",
        "action": "lucid.set.host-role",
        "value": PARENT_HASH,
        "requiresConfirmation": "exact",
        "intent": {
            "verb": "set",
            "arguments": {
                "path": "host-role",
                "scope": "this",
                "op": "set",
                "expected_hash": PARENT_HASH,
                "value": {"role": "SIDEKICK"},
            },
        },
    }


def refresh_action(verb="get"):
    return {
        "id": "lucid.response.refresh",
        "action": f"lucid.{verb}.refresh",
        "value": "logs/quine" if verb == "get" else "attention/pulse",
        "intent": {
            "verb": verb,
            "arguments": {"path": "logs/quine"} if verb == "get" else {"view": "pulse"},
        },
    }


def test_show_execution_compiles_to_one_exact_lucid_call():
    compiled = compile_lucid_ugui_action(document(show_action()), "lucid.response.execution")

    assert compiled.server_name == "LUCID"
    assert compiled.tool_name == "show"
    assert compiled.arguments == {"view": "execution", "id": DISPATCH_ID}


def test_cancel_requires_exact_confirmation_before_compiling():
    with pytest.raises(UguiActionError, match="confirmation") as refusal:
        compile_lucid_ugui_action(document(cancel_action()), "lucid.response.cancel")
    assert refusal.value.code == "confirmation-required"

    compiled = compile_lucid_ugui_action(
        document(cancel_action()),
        "lucid.response.cancel",
        confirmed=True,
    )
    assert compiled.tool_name == "cancel"
    assert compiled.arguments == {"task": "fleet.dispatch", "dispatch_id": DISPATCH_ID}


def test_dispatch_plan_promotion_requires_confirmation_and_exact_candidate_hash():
    action = dispatch_plan_action()
    with pytest.raises(UguiActionError) as unconfirmed:
        compile_lucid_ugui_action(document(action), action["id"])
    assert unconfirmed.value.code == "confirmation-required"

    compiled = compile_lucid_ugui_action(document(action), action["id"], confirmed=True)
    assert compiled.tool_name == "dispatch"
    assert compiled.arguments == action["intent"]["arguments"]

    action["intent"]["arguments"]["request"]["intent"] = "different candidate"
    with pytest.raises(UguiActionError) as stale:
        compile_lucid_ugui_action(document(action), action["id"], confirmed=True)
    assert stale.value.code == "action-stale"


def test_host_role_switch_requires_confirmation_and_exact_hash_binding():
    action = host_role_action()
    with pytest.raises(UguiActionError) as unconfirmed:
        compile_lucid_ugui_action(document(action), action["id"])
    assert unconfirmed.value.code == "confirmation-required"

    compiled = compile_lucid_ugui_action(document(action), action["id"], confirmed=True)
    assert compiled.tool_name == "set"
    assert compiled.arguments["value"] == {"role": "SIDEKICK"}

    action["intent"]["arguments"]["expected_hash"] = f"sha256:{'c' * 64}"
    with pytest.raises(UguiActionError) as stale:
        compile_lucid_ugui_action(document(action), action["id"], confirmed=True)
    assert stale.value.code == "action-target-invalid"


def test_refresh_compiles_the_exact_get_and_show_arguments():
    for verb in ("get", "show"):
        action = refresh_action(verb)
        compiled = compile_lucid_ugui_action(document(action), action["id"])
        assert compiled.tool_name == verb
        assert compiled.arguments == action["intent"]["arguments"]


def test_refresh_rejects_embedded_authority_material():
    action = refresh_action()
    action["intent"]["arguments"]["capability"] = "forbidden"

    with pytest.raises(UguiActionError) as refusal:
        compile_lucid_ugui_action(document(action), action["id"])
    assert refusal.value.code == "action-authority-forbidden"


def test_help_action_invokes_the_selected_bare_lucid_verb():
    action = {
        "id": "lucid.help.morph",
        "action": "lucid.help.verb",
        "value": "morph",
        "intent": {"verb": "morph", "arguments": {}},
    }
    value = document(action)
    value["schema"] = "lucid-help-document/1"

    compiled = compile_lucid_ugui_action(value, action["id"])
    assert compiled.tool_name == "morph"
    assert compiled.arguments == {}


def test_action_provenance_must_match_the_document():
    value = document(show_action())
    value["receipt"]["action_provenance"][0]["provenance_hash"] = f"sha256:{'c' * 64}"

    with pytest.raises(UguiActionError) as refusal:
        compile_lucid_ugui_action(value, "lucid.response.execution")
    assert refusal.value.code == "action-stale"


def test_incomplete_steer_compose_is_not_presented_as_executable():
    action = {
        "id": "lucid.response.steer",
        "action": "lucid.steer.compose",
        "value": DISPATCH_ID,
        "disabled": True,
    }

    with pytest.raises(UguiActionError) as refusal:
        compile_lucid_ugui_action(document(action), "lucid.response.steer")
    assert refusal.value.code == "action-not-executable"


def test_complete_read_intents_do_not_require_a_renderer_handler_allowlist():
    action = {
        "id": "lucid.response.inspect",
        "action": "lucid.get.inspect",
        "value": "fleet",
        "intent": {"verb": "get", "arguments": {"path": "fleet"}},
    }

    compiled = compile_lucid_ugui_action(document(action), action["id"])
    assert compiled.tool_name == "get"
    assert compiled.arguments == {"path": "fleet"}


def test_generic_mutating_intents_require_authored_exact_confirmation():
    action = {
        "id": "lucid.response.restore",
        "action": "lucid.set.restore",
        "value": "setting",
        "intent": {"verb": "set", "arguments": {"path": "setting", "value": "prior"}},
    }

    with pytest.raises(UguiActionError) as missing_policy:
        compile_lucid_ugui_action(document(action), action["id"])
    assert missing_policy.value.code == "confirmation-policy-missing"

    action["requiresConfirmation"] = "exact"
    with pytest.raises(UguiActionError) as unconfirmed:
        compile_lucid_ugui_action(document(action), action["id"])
    assert unconfirmed.value.code == "confirmation-required"

    compiled = compile_lucid_ugui_action(document(action), action["id"], confirmed=True)
    assert compiled.tool_name == "set"


def test_execution_uses_the_registered_mcp_transport(monkeypatch):
    observed = {}

    def invoke(server_name, tool_name, arguments):
        observed.update(server=server_name, tool=tool_name, arguments=arguments)
        return {"structuredContent": {"schema": "lucid-show-document/1"}}

    monkeypatch.setattr("tools.mcp_tool.invoke_registered_mcp_tool", invoke)
    result = execute_lucid_ugui_action(document(show_action()), "lucid.response.execution")

    assert result["ok"] is True
    assert observed == {
        "server": "LUCID",
        "tool": "show",
        "arguments": {"view": "execution", "id": DISPATCH_ID},
    }


def test_web_route_executes_the_compiled_action(monkeypatch, tmp_path):
    pytest.importorskip("starlette.testclient")
    from starlette.testclient import TestClient
    from hermes_cli import ugui_actions, web_server

    observed = {}

    def execute(value, action_id, *, confirmed, inputs):
        observed.update(
            document=value,
            action_id=action_id,
            confirmed=confirmed,
            inputs=inputs,
        )
        return {"ok": True, "result": {"structuredContent": document(show_action())}}

    monkeypatch.setattr(ugui_actions, "execute_lucid_ugui_action", execute)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    previous_auth_required = getattr(web_server.app.state, "auth_required", None)
    web_server.app.state.auth_required = False
    try:
        client = TestClient(web_server.app)
        client.headers[web_server._SESSION_HEADER_NAME] = web_server._SESSION_TOKEN
        response = client.post(
            "/api/ugui/actions/invoke",
            json={
                "document": document(show_action()),
                "action_id": "lucid.response.execution",
                "confirmed": False,
                "inputs": {},
            },
        )
    finally:
        web_server.app.state.auth_required = previous_auth_required

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert observed["action_id"] == "lucid.response.execution"
    assert observed["confirmed"] is False
