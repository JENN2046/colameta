from __future__ import annotations

import inspect

from runner.mcp_resources import (
    MCPResourcesService,
    RESULT_ARTIFACT_RESOURCE_TEMPLATES,
    REVIEW_MANIFEST_RESOURCE_TEMPLATES,
)
from runner.mcp_server import (
    MCPPlanningBridgeServer,
    MCP_RESULT_ARTIFACT_RESOURCE_TEMPLATES,
    MCP_REVIEW_MANIFEST_RESOURCE_TEMPLATES,
)


def test_transport_reexports_resource_templates_from_the_resource_contract() -> None:
    assert MCP_RESULT_ARTIFACT_RESOURCE_TEMPLATES is RESULT_ARTIFACT_RESOURCE_TEMPLATES
    assert MCP_REVIEW_MANIFEST_RESOURCE_TEMPLATES is REVIEW_MANIFEST_RESOURCE_TEMPLATES


def test_transport_uses_the_resource_service_for_stateful_resource_operations() -> None:
    expected_handlers = {
        "_store_packaged_result_artifact": "store_packaged_result_artifact",
        "_result_artifact_manifest_fields": "result_artifact_manifest_fields",
        "_result_artifact_recommended_next_reads": "result_artifact_recommended_next_reads",
        "_result_artifact_recovery_manifest": "result_artifact_recovery_manifest",
        "_review_manifest_resources": "review_manifest_resources",
        "_review_manifest_resource_read_result": "review_manifest_resource_read_result",
        "_mcp_resources_list_result": "mcp_resources_list_result",
        "_mcp_resource_read_result": "mcp_resource_read_result",
    }

    for handler_name, service_handler_name in expected_handlers.items():
        source = inspect.getsource(getattr(MCPPlanningBridgeServer, handler_name))
        assert "_mcp_resources_service" in source
        assert service_handler_name in source
        assert hasattr(MCPResourcesService, service_handler_name)
