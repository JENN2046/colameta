from __future__ import annotations

import json
from pathlib import Path

from runner.mcp_server import (
    COMMANDER_EXPOSED_TOOLS,
    NORMAL_EXPOSED_TOOLS,
    MCPPlanningBridgeServer,
)


def test_commander_profile_exposes_exact_seven_high_level_tools(tmp_path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="commander")

    assert tuple(server._visible_tool_names()) == COMMANDER_EXPOSED_TOOLS
    assert len(server._visible_tool_names()) == 7
    assert "list_registered_projects" in server._visible_tool_names()
    assert "get_apps_connector_smoke_packet" in server._visible_tool_names()
    assert all(
        tool.output_schema and tool.annotations
        for tool in server._filter_tools_by_exposure_profile(server.tool_defs)
    )


def test_commander_profile_allows_cached_read_only_smoke_tool(tmp_path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="commander")

    result = server._call_tool("get_apps_connector_smoke_packet", {})

    assert result["ok"] is True
    assert server.get_required_scope_for_tool("get_apps_connector_smoke_packet", {}) == "mcp:read"


def test_submission_artifact_matches_exact_commander_surface(tmp_path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="commander")
    visible_defs = server._filter_tools_by_exposure_profile(server.tool_defs)
    artifact_path = Path(__file__).resolve().parents[1] / "chatgpt-app-submission.json"
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))

    assert tuple(artifact["tools"]) == COMMANDER_EXPOSED_TOOLS
    assert len(artifact["test_cases"]) == 5
    assert len(artifact["negative_test_cases"]) == 3
    for tool in visible_defs:
        assert tool.output_schema
        submission_annotations = artifact["tools"][tool.name]["annotations"]
        for hint in ("readOnlyHint", "openWorldHint", "destructiveHint"):
            assert submission_annotations[hint] is tool.annotations[hint]
        assert set(artifact["tools"][tool.name]["justifications"]) == {
            "read_only_justification",
            "open_world_justification",
            "destructive_justification",
        }


def test_commander_profile_denies_hidden_tools_even_if_client_cached_them(tmp_path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="commander")

    result = server._call_tool("manage_files", {"action": "read", "path": "README.md"})

    assert result["ok"] is False
    assert result["error_code"] == "TOOL_NOT_EXPOSED"


def test_normal_profile_preserves_complete_advanced_catalog(tmp_path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="normal")

    assert set(server._visible_tool_names()) == set(NORMAL_EXPOSED_TOOLS)
    assert len(server._visible_tool_names()) == 82
    assert "manage_files" in server._visible_tool_names()


def test_commander_profile_can_be_selected_from_environment(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("MCP_EXPOSURE_PROFILE", "commander")

    server = MCPPlanningBridgeServer(str(tmp_path))

    assert server.mcp_exposure_profile == "commander"
