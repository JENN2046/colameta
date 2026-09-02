from __future__ import annotations

import json
from pathlib import Path

import pytest

from runner.agent_routing_registry import (
    TOOL_TIER_ADVANCED,
    TOOL_TIER_LEGACY_OR_INTERNAL,
    TOOL_TIER_PRIMARY,
    build_capability_routing_registry,
    profile_guidance,
    tool_routing_metadata,
)
from runner.agent_state_projection import (
    add_agent_state_projection,
    recovery_projection,
    select_primary_action_from_state,
    typed_continuation_projection,
)
from runner.core_orchestrator import WorkflowOrchestrator
from runner.mcp_server import COMMANDER_EXPOSED_TOOLS, MCPPlanningBridgeServer
from runner.mcp_workflow_router import MCPWorkflowRouter
from tests.agent_ux_independent_verifier import verify_agent_projection


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "agent_routing_r1.json"


def test_registry_classifies_the_complete_runtime_catalog(tmp_path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="owner")
    registry = build_capability_routing_registry(tool.name for tool in server.tool_defs)

    assert registry["tool_count"] == 123
    assert {item["classification"] for item in registry["tools"]} == {
        TOOL_TIER_PRIMARY,
        TOOL_TIER_ADVANCED,
        TOOL_TIER_LEGACY_OR_INTERNAL,
    }
    assert registry["registry_does_not_grant_authority"] is True
    assert tool_routing_metadata("manage_git")["canonical_primary_tool"] == "manage_git"
    assert tool_routing_metadata("get_git_status")["classification"] == TOOL_TIER_LEGACY_OR_INTERNAL


def test_profile_guidance_preserves_commander_physical_surface() -> None:
    guidance = profile_guidance("web_gpt_commander")

    assert {"analyze_project_state", "run_mcp_workflow", "manage_validation_run", "manage_git"} <= (
        set(guidance["primary_tools"]) & set(COMMANDER_EXPOSED_TOOLS)
    )
    assert guidance["does_not_grant_tool_authority"] is True
    assert "manage_executor_workflow" not in guidance["primary_tools"]


@pytest.mark.parametrize(
    "profile_id",
    [
        "web_gpt_commander",
        "local_codex_commander",
        "planner_agent",
        "reviewer_agent",
        "source_observer",
    ],
)
def test_all_supported_profiles_have_bounded_guidance(profile_id: str) -> None:
    guidance = profile_guidance(profile_id)

    assert guidance["profile_id"] == profile_id
    assert guidance["primary_tools"]
    assert guidance["preferred_first_entrypoint"]
    assert guidance["guidance_is_navigation_only"] is True
    assert guidance["does_not_grant_tool_authority"] is True


@pytest.mark.parametrize(
    ("error_code", "expected_class", "should_stop"),
    [
        ("PREVIEW_EXPIRED", "new_preview_required", False),
        ("CONTEXT_BINDING_MISMATCH", "context_changed", False),
        ("EXECUTOR_ALREADY_RUNNING", "wait_for_running_operation", False),
        ("VALIDATION_FAILED", "operator_action_required", False),
        ("INSUFFICIENT_SCOPE", "authorization_required", True),
        ("SCOPE_VIOLATION", "authorization_required", True),
        ("CONFIRMATION_REQUIRED", "operator_action_required", True),
        ("UNSUPPORTED_TRANSITION", "unsupported_by_current_surface", False),
        ("AUTHORITY_MISMATCH", "hard_stop", True),
        ("PREREQUISITE_NOT_READY", "refresh_state_then_retry", False),
    ],
)
def test_recovery_classes_are_machine_readable(
    error_code: str,
    expected_class: str,
    should_stop: bool,
) -> None:
    recovery = recovery_projection(error_code)

    assert recovery is not None
    assert recovery["recovery_class"] == expected_class
    assert recovery["agent_should_stop"] is should_stop
    assert recovery["does_not_grant_authority"] is True


def test_external_connector_failure_does_not_claim_automatic_recovery() -> None:
    recovery = recovery_projection(
        "CONNECTOR_PRINCIPAL_REJECTED",
        error_origin="connector",
    )

    assert recovery is not None
    assert recovery["error_origin"] == "connector"
    assert recovery["recovery_class"] == "operator_action_required"
    assert recovery["agent_should_stop"] is True


def test_independent_verifier_rejects_cross_typed_continuation() -> None:
    packet = add_agent_state_projection(
        {"ok": True, "review_manifest_id": "rm_1"},
        source_tool="review_manifest",
    )
    packet["continuation"]["field_name"] = "run_id"

    assert "continuation kind does not match its typed field" in verify_agent_projection(packet)


@pytest.mark.parametrize(
    ("payload", "kind", "field_name"),
    [
        ({"review_manifest_id": "rm_1"}, "review_manifest", "review_manifest_id"),
        ({"run_id": "run_1"}, "executor_run", "run_id"),
        ({"patch_id": "patch_1"}, "plan_patch", "patch_id"),
        ({"artifact_id": "artifact_1"}, "result_artifact", "artifact_id"),
    ],
)
def test_typed_continuations_remain_distinct(
    payload: dict[str, str],
    kind: str,
    field_name: str,
) -> None:
    continuation = typed_continuation_projection({"result": payload}, source_tool="run_mcp_workflow")

    assert continuation is not None
    assert continuation["kind"] == kind
    assert continuation["field_name"] == field_name
    assert "continuation_id" not in continuation


def test_projection_preserves_old_fields_and_grants_no_authority() -> None:
    original = {
        "ok": True,
        "status": "preview_ready",
        "selected_workflow": "small_project_patch",
        "preview_ids": ["preview_1"],
        "next_actions": [
            {"tool": "manage_files", "action": "apply", "params": {"preview_id": "preview_1"}}
        ],
    }

    projected = add_agent_state_projection(original, source_tool="run_mcp_workflow", goal="edit one file")

    for key, value in original.items():
        assert projected[key] == value
    assert projected["continuation"]["field_name"] == "preview_id"
    assert projected["blocked_next_actions"]["exhaustive"] is False
    assert all(
        item.get("granted_by_projection") is False
        for item in projected["authority"].values()
        if isinstance(item, dict)
    )
    assert verify_agent_projection(projected) == []


def test_navigation_metadata_does_not_widen_existing_tool_scopes(tmp_path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="owner")
    navigation_metadata = {
        "primary_next_action": {"tool": "manage_git", "action": "commit_apply"},
        "authority": {"commit": {"recommended": True}},
    }

    assert server.get_required_scope_for_tool(
        "manage_executor_workflow",
        {"action": "run_once", **navigation_metadata},
    ) == "mcp:commit"
    assert server.get_required_scope_for_tool(
        "manage_git",
        {"action": "commit_apply", **navigation_metadata},
    ) == "mcp:commit"
    assert server.get_required_scope_for_tool(
        "manage_git",
        {"action": "push_apply", **navigation_metadata},
    ) == "mcp:commit"
    assert server.get_required_scope_for_tool(
        "manage_stable_promotion_evidence",
        {"action": "apply", **navigation_metadata},
    ) == "mcp:commit"


def test_unknown_state_does_not_invent_a_primary_action() -> None:
    projected = add_agent_state_projection(
        {"ok": True, "status": "SOMETHING_UNRECOGNIZED"},
        source_tool="analyze_project_state",
    )

    assert projected["primary_next_action"] is None
    assert projected["why_no_unique_action"]


def test_analyze_project_state_exposes_the_canonical_projection(tmp_path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="commander")

    result = server._tool_analyze_project_state({"include_reports": False})

    assert result["agent_projection_schema_version"] == "colameta.agent_state_projection.v1"
    assert result["agent_state"]["profile_id"] == "web_gpt_commander"
    assert result["blocked_next_actions"]["exhaustive"] is False
    assert verify_agent_projection(result) == []


def test_auto_preview_exposes_selected_workflow_and_projection(tmp_path) -> None:
    router = MCPWorkflowRouter(str(tmp_path), analyze_state_fn=lambda _params: {"ok": True})

    result = router.handle("auto_preview", {"goal": "Inspect project state; do not start executor."})

    assert result["selected_workflow"] == "project_status"
    assert result["classified_intent"]["selected_workflow"] == "project_status"
    assert result["classified_intent"]["does_not_grant_authority"] is True
    assert result["agent_state"]["goal"].startswith("Inspect project state")
    assert result["routing"]["selected_workflow"] == "project_status"
    assert verify_agent_projection(result) == []


def _fixture_error_code(name: str) -> str | None:
    return {
        "executor_currently_running": "EXECUTOR_ALREADY_RUNNING",
        "validation_failed": "VALIDATION_FAILED",
        "context_changed": "CONTEXT_BINDING_MISMATCH",
        "preview_expired": "PREVIEW_EXPIRED",
        "scope_violation": "SCOPE_VIOLATION",
        "blocked_work_item": "PREREQUISITE_NOT_READY",
        "stable_promotion_not_ready": "PREREQUISITE_NOT_READY",
    }.get(name)


def test_canonical_routing_fixtures() -> None:
    fixtures = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    assert len(fixtures) >= 20
    for fixture in fixtures:
        expected = fixture["expected"]
        classified = WorkflowOrchestrator._classify_goal(fixture["intent"])
        assert classified["selected_workflow"] == expected["selected_workflow"], fixture["name"]

        action = select_primary_action_from_state(
            fixture["initial_state"],
            intent=fixture["intent"],
        )
        assert action is not None, fixture["name"]
        assert {"tool": action["tool"], "action": action["action"]} == expected["primary_next_action"]

        packet = add_agent_state_projection(
            {
                **fixture["initial_state"],
                **({"error_code": _fixture_error_code(fixture["name"])} if _fixture_error_code(fixture["name"]) else {}),
            },
            source_tool="analyze_project_state",
            goal=fixture["intent"],
        )
        actual_recovery = packet["recovery"]["recovery_class"] if packet["recovery"] else None
        assert actual_recovery == expected["recovery_class"], fixture["name"]
        blocked_actions = [
            (
                "stable_apply"
                if item["tool"] == "manage_stable_promotion_evidence"
                else item["action"]
            )
            for item in packet["blocked_next_actions"]["items"]
        ]
        assert blocked_actions == expected["blocked_actions"], fixture["name"]
        assert verify_agent_projection(packet) == [], fixture["name"]
