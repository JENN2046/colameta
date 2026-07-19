from __future__ import annotations

from runner.mcp_server import (
    COMMANDER_EXPOSED_TOOLS,
    COMMANDER_PUBLIC_RESPONSE_MINIMIZATION_VERSION,
    NORMAL_EXPOSED_TOOLS,
    MCPPlanningBridgeServer,
)


def _nested_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        keys = set(value)
        for nested in value.values():
            keys.update(_nested_keys(nested))
        return keys
    if isinstance(value, list):
        keys = set()
        for nested in value:
            keys.update(_nested_keys(nested))
        return keys
    return set()


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


def test_commander_profile_denies_hidden_tools_even_if_client_cached_them(tmp_path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="commander")

    result = server._call_tool("manage_files", {"action": "read", "path": "README.md"})

    assert result["ok"] is False
    assert result["error_code"] == "TOOL_NOT_EXPOSED"

    shaped = server._as_mcp_call_result(result, {"action": "read", "path": "README.md"})
    assert shaped["structuredContent"]["tool"] == "manage_files"
    assert shaped["structuredContent"]["error_code"] == "TOOL_NOT_EXPOSED"


def test_normal_profile_preserves_complete_advanced_catalog(tmp_path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="normal")

    assert set(server._visible_tool_names()) == set(NORMAL_EXPOSED_TOOLS)
    assert len(server._visible_tool_names()) == 82
    assert "manage_files" in server._visible_tool_names()


def test_commander_profile_can_be_selected_from_environment(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("MCP_EXPOSURE_PROFILE", "commander")

    server = MCPPlanningBridgeServer(str(tmp_path))

    assert server.mcp_exposure_profile == "commander"


def test_commander_public_project_list_returns_only_selection_fields(tmp_path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="commander")
    server.tools["list_registered_projects"] = lambda _: {
        "ok": True,
        "registry_path": "/home/example/.config/colameta/projects.json",
        "project_count": 1,
        "projects": [
            {
                "project_id": "prj_internal",
                "project_name": "colameta-self-dev",
                "display_name": "ColaMeta",
                "project_root": "/home/example/src/colameta-dev",
                "project_mode": "managed",
                "available": True,
                "runner_managed": True,
                "updated_at": "2026-07-19T00:00:00Z",
                "last_selected_at": "2026-07-19T00:00:00Z",
            }
        ],
    }

    result = server._call_tool("list_registered_projects", {})

    assert COMMANDER_PUBLIC_RESPONSE_MINIMIZATION_VERSION == "commander_public_minimal.v1"
    assert result["data"] == {
        "ok": True,
        "project_count": 1,
        "projects": [
            {
                "project_name": "colameta-self-dev",
                "display_name": "ColaMeta",
                "project_mode": "managed",
                "available": True,
                "runner_managed": True,
            }
        ],
    }


def test_commander_public_compact_tools_omit_local_diagnostics_and_hidden_actions(tmp_path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="commander")
    forbidden_keys = {
        "project_id",
        "project_root",
        "project_identity",
        "pid",
        "updated_at",
        "last_observed_at",
        "recent_commits",
        "project_checkout_head",
        "loaded_runtime_head",
        "evidence_path",
        "ignored_files",
    }
    fixture = {
        "ok": True,
        "project_id": "prj_internal",
        "project_root": "/home/example/src/project",
        "project_identity": {"project_root": "/home/example/src/project"},
        "pid": 321,
        "updated_at": "2026-07-19T00:00:00Z",
        "last_observed_at": "2026-07-19T00:00:00Z",
        "recent_commits": [{"commit": "abc123", "subject": "internal subject"}],
        "project_checkout_head": "abc123",
        "loaded_runtime_head": "abc123",
        "evidence_path": "/home/example/src/project/.colameta/evidence.json",
        "ignored_files": [".colameta/runtime/private.json"],
        "safe_action": {"tool": "manage_git", "arguments": {"action": "status"}},
        "hidden_action": {"tool": "manage_files", "arguments": {"action": "read"}},
    }

    for tool_name in (
        "get_apps_connector_smoke_packet",
        "render_commander_app",
        "analyze_project_state",
    ):
        projected = server._commander_public_project_tool_result(
            {"ok": True, "tool": tool_name, "data": fixture},
            {"project_name": "colameta-self-dev"},
        )
        assert not (_nested_keys(projected) & forbidden_keys)
        assert projected["data"]["safe_action"]["tool"] == "manage_git"
        assert "hidden_action" not in projected["data"]


def test_commander_public_smoke_replaces_runtime_heads_with_alignment_fact(tmp_path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="commander")
    projected = server._commander_public_project_tool_result(
        {
            "ok": True,
            "tool": "get_apps_connector_smoke_packet",
            "data": {
                "ok": True,
                "runtime": {
                    "project_checkout_head": "abc123",
                    "loaded_runtime_head": "abc123",
                    "runtime_loaded_code_stale": False,
                    "reload_needed_for_verification": False,
                    "reload_awareness_reason": "installed_package_matches_project_checkout",
                },
            },
        },
        {"project_name": "colameta-self-dev"},
    )

    assert projected["data"]["runtime"] == {
        "runtime_aligned": True,
        "runtime_loaded_code_stale": False,
        "reload_needed_for_verification": False,
        "reload_awareness_reason": "installed_package_matches_project_checkout",
    }


def test_commander_public_operational_tools_keep_required_continuation_fields(tmp_path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="commander")
    fixture = {
        "ok": True,
        "preview_id": "preview_required_for_followup",
        "run_id": "run_required_for_status",
        "validation_run_id": "validation_required_for_status",
        "workflow_id": "internal_record_id",
        "updated_at": "2026-07-19T00:00:00Z",
        "project_root": "/home/example/src/project",
        "changed_files": ["runner/mcp_server.py"],
        "message": "Prepared from /home/example/src/project without applying changes.",
        "next_action": {"tool": "manage_git", "arguments": {"action": "status"}},
        "hidden_action": {"tool": "manage_files", "arguments": {"action": "read"}},
    }

    for tool_name in ("run_mcp_workflow", "manage_validation_run", "manage_git"):
        projected = server._commander_public_project_tool_result(
            {"ok": True, "tool": tool_name, "data": fixture},
            {"project_name": "colameta-self-dev"},
        )
        data = projected["data"]
        assert data["preview_id"] == "preview_required_for_followup"
        assert data["run_id"] == "run_required_for_status"
        assert data["validation_run_id"] == "validation_required_for_status"
        assert data["changed_files"] == ["runner/mcp_server.py"]
        assert data["project_name"] == "colameta-self-dev"
        assert "workflow_id" not in data
        assert "updated_at" not in data
        assert "project_root" not in data
        assert "hidden_action" not in data
        assert "/home/example" not in data["message"]


def test_commander_projection_applies_to_mcp_and_actions_envelopes(tmp_path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="commander")
    result = {
        "ok": True,
        "tool": "render_commander_app",
        "data": {
            "ok": True,
            "app_manifest_version": "colameta_commander_app.v1",
            "project_name": "colameta-self-dev",
            "project_root": "/home/example/src/project",
            "pid": 321,
            "safe_action": {"tool": "manage_git", "arguments": {"action": "status"}},
        },
        "_meta": {
            "ui": {"resourceUri": "ui://colameta/commander/v1.html"},
            "commander_app": {"project_name": "colameta-self-dev"},
        },
    }

    shaped = server._as_mcp_call_result(result, {"project_name": "colameta-self-dev"})
    assert shaped["structuredContent"]["data"]["project_name"] == "colameta-self-dev"
    assert "project_root" not in shaped["structuredContent"]["data"]
    assert "pid" not in shaped["structuredContent"]["data"]
    assert shaped["_meta"]["ui"]["resourceUri"] == "ui://colameta/commander/v1.html"

    actions = server._package_actions_rest_response(
        "render_commander_app",
        {"project_name": "colameta-self-dev"},
        result,
    )
    assert "project_root" not in actions["data"]
    assert "pid" not in actions["data"]
    assert actions["data"]["safe_action"]["tool"] == "manage_git"


def test_normal_profile_keeps_full_result_without_public_projection(tmp_path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="normal")
    result = {
        "ok": True,
        "tool": "analyze_project_state",
        "data": {
            "project_root": "/home/example/src/project",
            "pid": 321,
            "updated_at": "2026-07-19T00:00:00Z",
        },
    }

    assert server._commander_public_project_tool_result(result) is result
