from __future__ import annotations

import inspect

import pytest

from runner.mcp_commander_public import COMMANDER_EXPOSED_TOOLS, CommanderPublicProjector
from runner.mcp_server import MCPPlanningBridgeServer
from runner.executor_events import public_executor_projection
from runner.executor_status import apply_claim_to_status, status_base_result
from runner.web_console import public_executor_web_projection


def test_transport_reexports_the_exact_nine_tool_public_contract() -> None:
    from runner.mcp_server import COMMANDER_EXPOSED_TOOLS as transport_tools

    assert transport_tools is COMMANDER_EXPOSED_TOOLS
    assert len(COMMANDER_EXPOSED_TOOLS) == 9


def test_transport_uses_a_dedicated_commander_public_projector() -> None:
    for handler_name, projector_method in {
        "_commander_public_sanitize": "sanitize",
        "_commander_public_project_tool_result": "project_tool_result",
    }.items():
        source = inspect.getsource(getattr(MCPPlanningBridgeServer, handler_name))
        assert "_commander_public_projector" in source
        assert projector_method in source
        assert hasattr(CommanderPublicProjector, projector_method)


def test_artifact_sanitizer_omits_structured_oauth_callback() -> None:
    authorization_code = "synthetic-artifact-oauth-callback-code"
    projector = CommanderPublicProjector(None)

    sanitized = projector.sanitize_for_artifact(
        {
            "status": "clean",
            "oauth_callback": {
                "code": authorization_code,
                "state": "synthetic-artifact-oauth-callback-state",
            },
        }
    )

    assert sanitized == {"status": "clean"}
    assert authorization_code not in repr(sanitized)


def test_artifact_sanitizer_preserves_non_oauth_code_state_mapping() -> None:
    projector = CommanderPublicProjector(None)
    payload = {
        "workflow_result": {
            "code": "SUCCESS",
            "state": "completed",
        }
    }

    assert projector.sanitize_for_artifact(payload) == payload


def test_public_executor_status_redacts_claim_aliases_and_uses_claim_allowlist() -> None:
    authority_id = "a" * 32
    admission_sha256 = "b" * 64
    claim = {
        "status": "FAILED",
        "run_id": "run-public-1",
        "preview_id": "preview-public-1",
        "executor_authority_id": authority_id,
        "admission_sha256": admission_sha256,
        "error_code": "SYNTHETIC_FAILURE",
        "error_message": f"message copied {authority_id}",
        "exception_type": f"Synthetic{admission_sha256}",
        "blockers": [
            f"blocker copied {authority_id}",
            {"nested": [admission_sha256], authority_id: "private key"},
        ],
        "warnings": [
            {"deep": {"alias": authority_id, admission_sha256: "private key"}},
            f"warning copied {admission_sha256}",
        ],
        "fresh_authority_bound": True,
        "fresh_authority_proof": {"digest": admission_sha256},
        "attacker_controlled_extra": f"must not project {authority_id}",
    }
    events = [{
        "event_type": "executor_tool_event",
        "timestamp": "2026-08-24T00:00:00Z",
        "data": {"stage": f"stage-{authority_id}-{admission_sha256}"},
    }]
    result = status_base_result(1)

    apply_claim_to_status(result, claim, {}, events=events)

    serialized = repr(result)
    assert authority_id not in serialized
    assert admission_sha256 not in serialized
    assert "[private-lineage-redacted]" in serialized
    assert "executor_authority_id" not in result
    assert "admission_sha256" not in result
    assert "fresh_authority_bound" not in result
    assert "fresh_authority_proof" not in result
    assert "attacker_controlled_extra" not in result
    assert result["executor_run_status"] == "failed"
    assert result["error_code"] == "SYNTHETIC_FAILURE"
    assert result["message"] == "message copied [private-lineage-redacted]"


def test_recursive_projection_redacts_real_dictionary_key_aliases() -> None:
    authority_id = "a" * 32
    admission_sha256 = "b" * 64
    payload = {
        "executor_authority_id": authority_id,
        "admission_sha256": admission_sha256,
        authority_id: {
            f"prefix-{admission_sha256}": f"value-{authority_id}",
        },
    }

    projected = public_executor_projection(payload)
    serialized = repr(projected)

    assert authority_id not in serialized
    assert admission_sha256 not in serialized
    assert "[private-lineage-redacted]" in serialized


def test_web_executor_projection_drops_unknown_attacker_fields() -> None:
    authority_id = "a" * 32
    result = public_executor_web_projection({
        "ok": False,
        "error_code": "SYNTHETIC_FAILURE",
        "message": f"copied={authority_id}",
        "executor_authority_id": authority_id,
        "attacker_controlled_extra": {authority_id: "must not survive"},
    })

    assert result == {
        "ok": False,
        "error_code": "SYNTHETIC_FAILURE",
        "message": "copied=[private-lineage-redacted]",
    }


def test_exceptional_dispatcher_outcome_is_projected_before_return(
    tmp_path, monkeypatch
) -> None:
    authority_id = "a" * 32
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="commander")

    def raise_private_exception(*args, **kwargs):
        raise RuntimeError(f"private={authority_id}")

    monkeypatch.setattr(server, "_dispatch_tool_result", raise_private_exception)
    result = server._call_tool("list_registered_projects", {})
    serialized = repr(result)

    assert authority_id not in serialized
    assert result["ok"] is False
    assert result["tool"] == "list_registered_projects"
    assert result["data"]["schema_version"]
    assert "attacker_controlled_extra" not in serialized


@pytest.mark.parametrize(
    "exposure_profile",
    ["normal", "maintainer", "legacy", "commander"],
)
def test_executor_workflow_final_boundary_redacts_every_profile(
    tmp_path, exposure_profile
) -> None:
    authority_id = "a" * 32
    admission_sha256 = "b" * 64
    server = MCPPlanningBridgeServer(
        str(tmp_path),
        exposure_profile=exposure_profile,
    )

    def synthetic_status(_params):
        return {
            "ok": True,
            "action": "status",
            "status": "succeeded",
            "risk_level": "info",
            "message": f"aliases={authority_id}:{admission_sha256.upper()}",
            "Authority_Alias": authority_id,
            "EXPECTED_ADMISSION_SHA256": admission_sha256,
            "project_identity": {"internal": authority_id},
            "session_status": {
                "status": "ready",
                "AUTHORITY_ID": authority_id,
                "attacker_controlled_extra": {
                    "nested": admission_sha256,
                },
            },
            "attacker_controlled_extra": {
                "nested": [authority_id, admission_sha256],
            },
        }

    server.tools["manage_executor_workflow"] = synthetic_status
    response = server._handle_jsonrpc_request({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "manage_executor_workflow",
            "arguments": {"action": "status"},
        },
    })

    assert response is not None
    serialized = repr(response)
    assert authority_id not in serialized
    assert admission_sha256 not in serialized.lower()
    assert "authority_alias" not in serialized.lower()
    assert "expected_admission_sha256" not in serialized.lower()
    assert "project_identity" not in serialized
    assert "attacker_controlled_extra" not in serialized
    if exposure_profile == "normal":
        structured = response["result"]["structuredContent"]
        assert set(structured) == {"ok", "tool", "data"}
        assert set(structured["data"]) == {
            "ok",
            "action",
            "status",
            "risk_level",
            "message",
            "session_status",
        }
        assert structured["data"]["session_status"] == {"status": "ready"}


@pytest.mark.parametrize(
    "exposure_profile",
    ["normal", "maintainer", "legacy", "commander"],
)
def test_executor_workflow_inner_error_and_exception_fail_closed(
    tmp_path, exposure_profile
) -> None:
    authority_id = "c" * 32
    admission_sha256 = "d" * 64
    server = MCPPlanningBridgeServer(
        str(tmp_path),
        exposure_profile=exposure_profile,
    )

    def normal_private_error(_params):
        return {
            "ok": False,
            "error_code": "SYNTHETIC_INNER_ERROR",
            "message": "Synthetic executor error.",
            "details": {"message": f"private={authority_id}:{admission_sha256}"},
            "arbitrary": {"nested": authority_id},
        }

    server.tools["manage_executor_workflow"] = normal_private_error
    inner_response = server._handle_jsonrpc_request({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "manage_executor_workflow",
            "arguments": {
                "action": "run_once_preview",
                "executor_session_mode": "start_new",
                "executor_authority_id": authority_id,
                "admission_sha256": admission_sha256,
            },
        },
    })
    assert inner_response is not None
    assert inner_response["result"]["isError"] is True
    inner_serialized = repr(inner_response)
    assert authority_id not in inner_serialized
    assert admission_sha256 not in inner_serialized
    assert "details" not in inner_serialized
    assert "arbitrary" not in inner_serialized

    def raise_private_exception(_params):
        raise RuntimeError(f"private={authority_id}:{admission_sha256}")

    server.tools["manage_executor_workflow"] = raise_private_exception
    exception_response = server._handle_jsonrpc_request({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "manage_executor_workflow",
            "arguments": {
                "action": "run_once_preview",
                "executor_session_mode": "start_new",
                "executor_authority_id": authority_id,
                "admission_sha256": admission_sha256,
            },
        },
    })
    assert exception_response is not None
    assert exception_response["result"]["isError"] is True
    exception_serialized = repr(exception_response)
    assert authority_id not in exception_serialized
    assert admission_sha256 not in exception_serialized
    assert "private=" not in exception_serialized


def test_executor_workflow_rejects_parameters_not_allowlisted_for_action(
    tmp_path,
) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path))
    called = False

    def should_not_run(_params):
        nonlocal called
        called = True
        return {"ok": True, "action": "status", "status": "succeeded"}

    server.tools["manage_executor_workflow"] = should_not_run
    response = server._handle_jsonrpc_request({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "manage_executor_workflow",
            "arguments": {"action": "status", "reason": "not valid for status"},
        },
    })

    assert response is not None
    assert called is False
    structured = response["result"]["structuredContent"]
    assert structured == {
        "ok": False,
        "tool": "manage_executor_workflow",
        "error_code": "INVALID_TOOL_INPUT_SCHEMA",
        "message": "Tool arguments do not match the exact action input schema.",
        "details": {"unexpected_fields": ["reason"]},
    }
