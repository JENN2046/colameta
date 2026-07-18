from __future__ import annotations

from runner.mcp_server import (
    COMMANDER_EXPOSED_TOOLS,
    NORMAL_EXPOSED_TOOLS,
    MCPPlanningBridgeServer,
)


def test_commander_profile_exposes_exact_six_high_level_tools(tmp_path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="commander")

    assert tuple(server._visible_tool_names()) == COMMANDER_EXPOSED_TOOLS
    assert len(server._visible_tool_names()) == 6
    assert all(
        tool.output_schema and tool.annotations
        for tool in server._filter_tools_by_exposure_profile(server.tool_defs)
    )


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
