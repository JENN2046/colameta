from pathlib import Path

from runner.mcp_server import COMMANDER_APP_WIDGET_URI, MCPPlanningBridgeServer, MCPToolDef
from runner.mcp_tool_catalog import (
    MCPToolDef as CatalogMCPToolDef,
    apply_chatgpt_submission_tool_annotations,
    build_mcp_tool_definitions,
)


ROOT = Path(__file__).resolve().parents[1]


def test_server_composes_the_tool_definitions_from_the_standalone_catalog() -> None:
    server = MCPPlanningBridgeServer(str(ROOT))

    catalog = build_mcp_tool_definitions(
        server,
        server._build_common_output_schema(),
        commander_widget_uri=COMMANDER_APP_WIDGET_URI,
    )
    apply_chatgpt_submission_tool_annotations(catalog)

    assert MCPToolDef is CatalogMCPToolDef
    assert catalog == server.tool_defs[: len(catalog)]
    assert {"review_manifest", "read_result_artifact", "run_mcp_workflow"} <= {
        tool.name for tool in catalog
    }

    executor_tool = next(tool for tool in catalog if tool.name == "manage_executor_workflow")
    profile_description = executor_tool.input_schema["properties"]["profile_id"]["description"]
    assert "run_once_preview/run_bounded_preview/run_once/run_bounded/status" in profile_description
    assert "绑定到 artifact" in profile_description
