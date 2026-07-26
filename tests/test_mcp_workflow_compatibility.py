from __future__ import annotations

import inspect

from runner.mcp_server import MCPPlanningBridgeServer
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
