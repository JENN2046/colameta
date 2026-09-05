from __future__ import annotations

import inspect

import pytest

from runner.executor_status import polling_guidance_for_profile
from runner.mcp_server import MCPPlanningBridgeServer
import runner.mcp_workflow_compatibility as workflow_compatibility
from runner.mcp_workflow_compatibility import MCPWorkflowCompatibilityService


def test_transport_handlers_are_thin_compatibility_adapters() -> None:
    expected_handlers = {
        "_tool_operator_batch": "handle_operator_batch",
        "_tool_review_manifest": "handle_review_manifest",
        "_tool_review_manifest_entry": "handle_review_manifest_entry",
        "_tool_read_result_artifact": "handle_read_result_artifact",
        "_tool_result_artifact": "handle_result_artifact",
        "_tool_run_mcp_workflow": "handle_run_mcp_workflow",
    }

    for handler_name, service_handler_name in expected_handlers.items():
        source = inspect.getsource(getattr(MCPPlanningBridgeServer, handler_name))
        assert "_workflow_compatibility_result" in source
        assert service_handler_name in source
        assert hasattr(MCPWorkflowCompatibilityService, service_handler_name)


def test_workflow_compatibility_service_keeps_result_reads_narrow() -> None:
    boundary = MCPWorkflowCompatibilityService._result_artifact_authority_boundary()

    assert boundary == {
        "does_not_read_project_files": True,
        "does_not_authorize_executor_run": True,
        "does_not_authorize_validation_run": True,
        "does_not_authorize_commit_or_push": True,
        "does_not_authorize_review_decision": True,
        "does_not_authorize_delivery_acceptance": True,
    }


def _capture_core_workflow_params(
    server: MCPPlanningBridgeServer,
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[str, dict[str, object]]]:
    calls: list[tuple[str, dict[str, object]]] = []

    class RecordingRouter:
        def handle(self, workflow: str, params: dict[str, object]) -> dict[str, object]:
            calls.append((workflow, dict(params)))
            guidance = polling_guidance_for_profile(params.get("profile_id"))
            return {
                "ok": True,
                "workflow": workflow,
                "polling_profile_id": guidance["profile_id"],
                "polling_guidance": guidance,
            }

    monkeypatch.setattr(server, "_create_mcp_workflow_router", RecordingRouter)
    monkeypatch.setattr(
        server,
        "_require_operation_context_binding",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        server,
        "_attach_operation_context_binding",
        lambda result, **kwargs: result,
    )
    monkeypatch.setattr(
        server,
        "_record_workflow_if_needed",
        lambda *args, **kwargs: None,
    )
    return calls


@pytest.mark.parametrize(
    ("workflow", "phase"),
    [
        ("agent_dispatch", "run"),
        ("project_status", "status"),
        ("git_commit", "commit"),
        ("prompt_to_plan", "preview"),
    ],
)
def test_omitted_profile_does_not_leak_exposure_fallback_into_core_workflows(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    workflow: str,
    phase: str,
) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="normal")
    calls = _capture_core_workflow_params(server, monkeypatch)

    server._workflow_compatibility_service().handle_run_mcp_workflow(
        {"workflow": workflow, "phase": phase}
    )

    assert calls == [(workflow, {"workflow": workflow, "phase": phase})]


def test_omitted_agent_dispatch_profile_keeps_legacy_web_polling_guidance(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="normal")
    calls = _capture_core_workflow_params(server, monkeypatch)

    result = server._workflow_compatibility_service().handle_run_mcp_workflow(
        {"workflow": "agent_dispatch", "phase": "run"}
    )

    assert "profile_id" not in calls[0][1]
    assert result["polling_profile_id"] == "web_gpt_commander"
    assert result["polling_guidance"]["max_poll_attempts"] == 3
    assert result["polling_guidance"]["next_poll_after_seconds"] == 3


def test_explicit_agent_dispatch_profile_keeps_local_codex_polling_guidance(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="normal")
    calls = _capture_core_workflow_params(server, monkeypatch)

    result = server._workflow_compatibility_service().handle_run_mcp_workflow(
        {
            "workflow": "agent_dispatch",
            "phase": "run",
            "profile_id": "local_codex_commander",
        }
    )

    assert calls[0][1]["profile_id"] == "local_codex_commander"
    assert result["polling_profile_id"] == "local_codex_commander"
    assert result["polling_guidance"]["max_poll_attempts"] == 24
    assert result["polling_guidance"]["next_poll_after_seconds"] == 5


def test_functional_mvp_omitted_profile_remains_omitted(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict[str, object]] = []

    class RecordingFunctionalMVPWorkflow:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def handle(self, params: dict[str, object]) -> dict[str, object]:
            captured.append(dict(params))
            return {"ok": True, "workflow": "functional_mvp"}

    monkeypatch.setattr(
        workflow_compatibility,
        "MCPFunctionalMVPWorkflow",
        RecordingFunctionalMVPWorkflow,
    )
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="normal")
    monkeypatch.setattr(
        server,
        "_record_workflow_if_needed",
        lambda *args, **kwargs: None,
    )

    server._workflow_compatibility_service().handle_run_mcp_workflow(
        {"workflow": "functional_mvp"}
    )

    assert captured == [{"workflow": "functional_mvp"}]
