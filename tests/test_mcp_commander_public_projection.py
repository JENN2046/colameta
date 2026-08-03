from __future__ import annotations

import inspect

from runner.mcp_commander_public import COMMANDER_EXPOSED_TOOLS, CommanderPublicProjector
from runner.mcp_server import MCPPlanningBridgeServer


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
