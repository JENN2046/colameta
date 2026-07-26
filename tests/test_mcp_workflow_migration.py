from __future__ import annotations

import importlib
from pathlib import Path

from runner.mcp_server import COMMANDER_EXPOSED_TOOLS, MCPPlanningBridgeServer
from runner.mcp_workflow_migration import (
    WORKFLOW_MIGRATION_MAP,
    declared_run_mcp_workflows,
    validate_workflow_migration_map,
)


def _run_mcp_workflow_schema_workflows(server: MCPPlanningBridgeServer) -> set[str]:
    tool = next(tool for tool in server.tool_defs if tool.name == "run_mcp_workflow")
    workflows = tool.input_schema["properties"]["workflow"]["enum"]
    return {str(workflow) for workflow in workflows}


def test_p1_a0_migration_map_covers_the_exact_public_legacy_schema(tmp_path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="commander")

    assert validate_workflow_migration_map() == ()
    assert set(WORKFLOW_MIGRATION_MAP) == set(declared_run_mcp_workflows())
    assert _run_mcp_workflow_schema_workflows(server) == set(WORKFLOW_MIGRATION_MAP)


def test_p1_a0_migration_map_keeps_current_owners_importable() -> None:
    for entry in WORKFLOW_MIGRATION_MAP.values():
        module = importlib.import_module(entry.current_owner_module)
        current_owner = module
        for symbol_part in entry.current_owner_symbol.split("."):
            current_owner = getattr(current_owner, symbol_part)
        assert current_owner is not None
        if entry.target_owner_status == "existing":
            target_module = importlib.import_module(entry.target_owner_module)
            target_owner = target_module
            for symbol_part in entry.target_owner_symbol.split("."):
                target_owner = getattr(target_owner, symbol_part)
            assert target_owner is not None
        assert entry.required_fields
        assert entry.supported_phases
        assert entry.scope_contract
        assert entry.input_contract_id.endswith("/v1")
        assert entry.output_contract_id.endswith(".v1")
        for regression_test in entry.regression_tests:
            assert Path(regression_test).is_file()


def test_p1_a0_public_typed_targets_are_in_the_nine_tool_contract() -> None:
    typed_entries = [
        entry
        for entry in WORKFLOW_MIGRATION_MAP.values()
        if entry.classification == "public_typed"
    ]

    assert typed_entries
    assert len(COMMANDER_EXPOSED_TOOLS) == 9
    assert all(entry.public_typed_entrypoint in COMMANDER_EXPOSED_TOOLS for entry in typed_entries)


def test_p1_a0_local_advanced_entries_have_a_safe_handoff() -> None:
    local_entries = [
        entry
        for entry in WORKFLOW_MIGRATION_MAP.values()
        if entry.classification in {"local_advanced", "retired_with_handoff"}
    ]

    assert local_entries
    assert all(entry.local_handoff_entrypoint for entry in local_entries)
    assert all(entry.compatibility_status in {"local_only", "retired"} for entry in local_entries)
