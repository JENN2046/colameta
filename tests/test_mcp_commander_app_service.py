from unittest.mock import patch

import runner.mcp_server as mcp_server
from runner.mcp_commander_app import MCPCommanderAppMixin
from runner.mcp_server import MCPPlanningBridgeServer


def test_server_inherits_commander_product_domain_from_its_dedicated_mixin() -> None:
    assert issubclass(MCPPlanningBridgeServer, MCPCommanderAppMixin)
    assert MCPPlanningBridgeServer._commander_app_manifest is MCPCommanderAppMixin._commander_app_manifest
    assert MCPPlanningBridgeServer._tool_get_web_gpt_service_entrypoint is (
        MCPCommanderAppMixin._tool_get_web_gpt_service_entrypoint
    )
    assert "_commander_app_manifest" not in MCPPlanningBridgeServer.__dict__
    assert "_tool_get_web_gpt_service_entrypoint" not in MCPPlanningBridgeServer.__dict__


def test_commander_product_domain_preserves_the_server_dependency_injection_seam() -> None:
    server = object.__new__(MCPPlanningBridgeServer)
    fallback = object()
    override = object()

    with patch.object(mcp_server, "build_product_console_map", override):
        assert server._commander_app_dependency("build_product_console_map", fallback) is override

    assert server._commander_app_dependency("missing_commander_dependency", fallback) is fallback
