from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from runner.mcp_server import (
    WORK_ITEM_APPLY_TOOLS,
    WORK_ITEM_MCP_TOOLS,
    WORK_ITEM_PREVIEW_TOOLS,
    MCPPlanningBridgeServer,
)
from runner.project_registry import ProjectRegistry
from runner.work_item_governance.ids import new_stable_id
from runner.work_item_governance.repository import SQLiteWorkItemLedger
from runner.work_item_principal_adapter import principal_from_auth_context


def test_work_item_tools_are_registered_with_fail_closed_scopes(tmp_path: Path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path))
    names = {definition.name for definition in server.tool_defs}
    assert set(WORK_ITEM_MCP_TOOLS).issubset(names)
    assert set(WORK_ITEM_MCP_TOOLS).issubset(server.tools)
    assert server.get_required_scope_for_tool("get_work_item", {}) == "mcp:read"
    assert server.get_required_scope_for_tool("preview_work_item_create", {}) == "mcp:preview"
    assert server.get_required_scope_for_tool("apply_work_item_transition", {}) == "mcp:commit"


def test_service_mode_work_item_writes_require_managed_project_routing(tmp_path: Path) -> None:
    source_only = tmp_path / "source-only"
    (source_only / ".git").mkdir(parents=True)
    registry = ProjectRegistry(
        registry_path=str(tmp_path / "project-registry.json"),
        user_settings_path=str(tmp_path / "settings.json"),
    )
    registered = registry.register_project(
        str(source_only),
        project_name="source-only-project",
        project_mode="source-only",
    )
    assert registered["ok"] is True

    server = MCPPlanningBridgeServer(str(tmp_path), service_mode=True)
    server.project_registry = registry
    status = server.call_tool_for_agent(
        "get_work_item_governance_status",
        {"project_name": "source-only-project"},
    )
    assert status["ok"] is True

    for tool_name in (*WORK_ITEM_PREVIEW_TOOLS, *WORK_ITEM_APPLY_TOOLS):
        denied = server.call_tool_for_agent(
            tool_name,
            {"project_name": "source-only-project"},
        )
        assert denied["ok"] is False, tool_name
        assert denied["error_code"] == "PROJECT_MODE_UNSUPPORTED", tool_name
    assert not (source_only / ".colameta").exists()


def test_mcp_feature_is_default_off_and_explicit_preview_apply_works_when_enabled(tmp_path: Path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path))
    status = server.call_tool_for_agent("get_work_item_governance_status", {})
    assert status["ok"] is True
    assert status["data"]["enabled"] is False
    blocked = server.call_tool_for_agent(
        "preview_work_item_create",
        {
            "command": {
                "origin": {
                    "kind": "manual",
                    "ref": "mcp",
                    "snapshot_digest": hashlib.sha256(b"mcp").hexdigest(),
                }
            }
        },
    )
    assert blocked["ok"] is False
    assert blocked["error_code"] == "WORK_ITEM_GOVERNANCE_DISABLED"

    settings_dir = tmp_path / ".colameta"
    settings_dir.mkdir()
    (settings_dir / "settings.json").write_text(
        json.dumps({"work_item_governance": {"shadow_ledger_enabled": True, "gate_mode": "shadow"}}),
        encoding="utf-8",
    )
    enabled_server = MCPPlanningBridgeServer(str(tmp_path))
    preview_result = enabled_server.call_tool_for_agent(
        "preview_work_item_create",
        {
            "command": {
                "origin": {
                    "kind": "manual",
                    "ref": "mcp",
                    "snapshot_digest": hashlib.sha256(b"mcp").hexdigest(),
                }
            }
        },
    )
    assert preview_result["ok"] is True
    assert preview_result["data"]["creates_work_item"] is False
    applied = enabled_server.call_tool_for_agent(
        "apply_work_item_create",
        {"preview": preview_result["data"]["preview"]},
    )
    assert applied["ok"] is True
    assert applied["data"]["created"] is True
    assert applied["data"]["work_item"]["state"] == "proposed"

    release = enabled_server.call_tool_for_agent(
        "get_release_submission_readiness",
        {"work_item_id": applied["data"]["work_item"]["work_item_id"]},
    )
    assert release["ok"] is True
    assert release["data"]["work_item_reference"]["state"] == "proposed"
    assert release["data"]["work_item_command_boundary"] == {
        "create_path": ["preview_work_item_create", "apply_work_item_create"],
        "reference_path": "get_work_item",
        "direct_ledger_write": False,
        "automatic_work_item_creation": False,
    }


def test_mcp_read_tools_do_not_create_a_missing_ledger(tmp_path: Path) -> None:
    settings_dir = tmp_path / ".colameta"
    settings_dir.mkdir()
    (settings_dir / "settings.json").write_text(
        json.dumps({"work_item_governance": {"shadow_ledger_enabled": True, "gate_mode": "shadow"}}),
        encoding="utf-8",
    )
    server = MCPPlanningBridgeServer(str(tmp_path))
    work_item_id = new_stable_id("work_item")
    attempt_id = new_stable_id("attempt")

    status = server.call_tool_for_agent("get_work_item_governance_status", {})
    assert status["ok"] is True
    assert "ledger_schema_version" not in status["data"]

    read_calls = {
        "get_work_item": {"work_item_id": work_item_id},
        "list_work_items": {},
        "get_work_item_timeline": {"work_item_id": work_item_id},
        "list_outbox_events": {},
        "get_execution_attempt_dispatch_authority": {
            "attempt_id": attempt_id,
            "work_item_id": work_item_id,
            "task_version": 1,
        },
    }
    for tool_name, arguments in read_calls.items():
        result = server.call_tool_for_agent(tool_name, arguments)
        assert result["ok"] is False, tool_name
        assert result["error_code"] == "LEDGER_FILE_MISSING", tool_name

    assert not (settings_dir / "ledger").exists()


def test_mcp_reads_do_not_migrate_an_older_ledger(tmp_path: Path) -> None:
    ledger = SQLiteWorkItemLedger(tmp_path)
    ledger.initialize()
    settings = tmp_path / ".colameta" / "settings.json"
    settings.write_text(
        json.dumps({"work_item_governance": {"shadow_ledger_enabled": True, "gate_mode": "shadow"}}),
        encoding="utf-8",
    )
    with sqlite3.connect(ledger.path) as connection:
        connection.execute("PRAGMA user_version=4")
    ledger_dir = ledger.path.parent
    before_paths = {
        path.relative_to(ledger_dir).as_posix()
        for path in ledger_dir.rglob("*")
        if path.is_file()
    }
    before_database = ledger.path.read_bytes()

    server = MCPPlanningBridgeServer(str(tmp_path))
    for tool_name in ("get_work_item_governance_status", "list_work_items"):
        result = server.call_tool_for_agent(tool_name, {})
        assert result["ok"] is False, tool_name
        assert result["error_code"] == "LEDGER_SCHEMA_MIGRATION_REQUIRED", tool_name

    after_paths = {
        path.relative_to(ledger_dir).as_posix()
        for path in ledger_dir.rglob("*")
        if path.is_file()
    }
    assert after_paths == before_paths
    assert ledger.path.read_bytes() == before_database
    with sqlite3.connect(ledger.path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 4


def test_mcp_commit_scope_does_not_self_grant_work_item_authority() -> None:
    assert principal_from_auth_context(
        {
            "mode": "oauth",
            "token": {
                "sub": "caller-claimed-jenn",
                "scope": "mcp:read mcp:preview mcp:commit",
            },
        }
    ) is None

    principal = principal_from_auth_context(
        {
            "mode": "cloud-relay",
            "principal_id": "authenticated-reviewer",
            "principal_kind": "human",
            "work_item_permissions": ["work_item.accept"],
            "session_ref": "commander:verified-session",
        }
    )
    assert principal is not None
    assert principal.trusted is True
    assert principal.principal_id == "authenticated-reviewer"


def test_local_control_plane_injects_explicit_environment_principal(
    monkeypatch,
) -> None:
    monkeypatch.setenv("COLAMETA_WORK_ITEM_PRINCIPAL_ID", "local-reviewer")
    monkeypatch.setenv(
        "COLAMETA_WORK_ITEM_PERMISSIONS",
        "work_item.submit work_item.accept",
    )
    monkeypatch.setenv("COLAMETA_WORK_ITEM_SESSION_REF", "local-session:test")
    principal = principal_from_auth_context({"mode": "token"})
    assert principal is not None
    assert principal.authenticated_by == "local_session"
    assert principal.granted_permissions == frozenset(
        {"work_item.submit", "work_item.accept"}
    )


def test_local_mcp_principal_authorizes_gate_without_body_authority(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings_dir = tmp_path / ".colameta"
    settings_dir.mkdir()
    (settings_dir / "settings.json").write_text(
        json.dumps(
            {
                "work_item_governance": {
                    "shadow_ledger_enabled": True,
                    "gate_mode": "authoritative",
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("COLAMETA_WORK_ITEM_PRINCIPAL_ID", "local-gate-reviewer")
    monkeypatch.setenv("COLAMETA_WORK_ITEM_PERMISSIONS", "work_item.ready")
    monkeypatch.setenv("COLAMETA_WORK_ITEM_SESSION_REF", "local-session:gate-test")
    server = MCPPlanningBridgeServer(str(tmp_path))
    create_preview = server.call_tool_for_agent(
        "preview_work_item_create",
        {
            "command": {
                "origin": {
                    "kind": "manual",
                    "ref": "local-mcp-gate",
                    "snapshot_digest": hashlib.sha256(b"local-mcp-gate").hexdigest(),
                }
            }
        },
    )
    created = server.call_tool_for_agent(
        "apply_work_item_create",
        {"preview": create_preview["data"]["preview"]},
    )["data"]["work_item"]
    transition_preview = server.call_tool_for_agent(
        "preview_work_item_transition",
        {
            "command": {
                "work_item_id": created["work_item_id"],
                "task_version": 1,
                "target_state": "ready",
                "expected_state_version": 0,
                "decision_ids": [],
                "evidence_artifact_ids": [],
            }
        },
    )
    assert transition_preview["ok"] is True
    assert (
        transition_preview["data"]["preview"]["command"]["principal_context"]["principal_id"]
        == "local-gate-reviewer"
    )
    applied = server.call_tool_for_agent(
        "apply_work_item_transition",
        {"preview": transition_preview["data"]["preview"]},
    )
    assert applied["ok"] is True
    assert applied["data"]["work_item"]["state"] == "ready"


def test_commander_runtime_uses_three_owned_projections(tmp_path: Path) -> None:
    result = MCPPlanningBridgeServer(str(tmp_path)).call_tool_for_agent(
        "get_commander_app_manifest",
        {},
    )
    assert result["ok"] is True
    sections = result["data"]["domain_projections"]
    assert set(sections) == {"core", "service_operations", "app_submission"}
    assert sections["core"]["owner"] == "work_item_governance"
    assert sections["core"]["write_path"] == "application_commands_only"
    assert sections["service_operations"]["owner"] == "service_operations"
    assert sections["app_submission"]["owner"] == "app_productization"
    assert sections["service_operations"]["can_write_work_item_state"] is False
    assert sections["app_submission"]["can_write_work_item_state"] is False
