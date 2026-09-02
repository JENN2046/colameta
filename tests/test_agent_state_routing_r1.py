from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
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
from runner.canonical_project_state import build_canonical_project_state
from runner.continuation_snapshot import snapshot_from_fact_bundle
from runner.core_orchestrator import WorkflowOrchestrator
from runner.mcp_server import COMMANDER_EXPOSED_TOOLS, MCPPlanningBridgeServer
from runner.mcp_workflow_router import MCPWorkflowRouter
from runner.project_registry import ProjectRegistry
from tests.agent_ux_independent_verifier import (
    verify_agent_projection,
    verify_authority_expectation,
)


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "agent_routing_r1.json"


class _PlanPreviewManager:
    def handle(self, action: str, params: dict) -> dict:
        assert action == "plan_extend_preview"
        return {"ok": True, "patch_id": "patch_production_1"}


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
    assert [item["tool"] for item in registry["tools"] if item["domain"] == "unclassified"] == []
    assert tool_routing_metadata("get_runtime_version_status")["domain"] == "runtime"
    assert tool_routing_metadata("get_review_context")["domain"] == "review"
    assert tool_routing_metadata("manage_project_patch")["domain"] == "source"
    assert tool_routing_metadata("retry_delivery")["domain"] == "product_release"


@pytest.mark.parametrize(
    "tool_name",
    [
        "todo_add",
        "todo_update",
        "todo_delete",
        "decision_add",
        "decision_update",
        "decision_delete",
        "recover_outbox_event",
    ],
)
def test_commit_scoped_legacy_commands_are_never_advertised_read_only(
    tmp_path,
    tool_name: str,
) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="owner")

    assert tool_routing_metadata(tool_name)["side_effect_level"] == "WRITE_OR_TRANSITION"
    assert server.get_required_scope_for_tool(tool_name, {}) == "mcp:commit"


@pytest.mark.parametrize(
    ("tool_name", "action", "side_effect_level", "required_scope"),
    [
        ("manage_workflow_run", "list", "READ_ONLY", "mcp:read"),
        ("manage_plan_workflow", "plan_repair_preview", "PREVIEW", "mcp:preview"),
    ],
)
def test_fixed_scope_manage_tools_precede_the_name_based_fallback(
    tmp_path,
    tool_name: str,
    action: str,
    side_effect_level: str,
    required_scope: str,
) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="owner")

    assert tool_routing_metadata(tool_name)["side_effect_level"] == side_effect_level
    assert server.get_required_scope_for_tool(tool_name, {"action": action}) == required_scope


def test_read_scoped_preview_getters_precede_the_name_based_fallback(tmp_path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="owner")
    read_scoped_preview_getters = {
        "get_executor_continuation_preview",
        "get_executor_resume_invocation_preview",
        "get_stage_parallel_executor_group_preview",
        "get_stage_parallel_merge_preview",
        "get_stage_parallel_plan_preview",
        "get_stage_parallel_run_preview",
        "get_stage_parallel_worktree_assignment_preview",
        "get_submission_evidence_fill_preview",
    }

    for tool_name in read_scoped_preview_getters:
        assert tool_routing_metadata(tool_name)["side_effect_level"] == "READ_ONLY"
        assert server.get_required_scope_for_tool(tool_name, {}) == "mcp:read"


def test_profile_guidance_preserves_commander_physical_surface() -> None:
    guidance = profile_guidance("web_gpt_commander")

    assert {"analyze_project_state", "run_mcp_workflow", "manage_validation_run", "manage_git"} <= (
        set(guidance["primary_tools"]) & set(COMMANDER_EXPOSED_TOOLS)
    )
    assert guidance["does_not_grant_tool_authority"] is True
    assert "manage_executor_workflow" not in guidance["primary_tools"]
    recommended = set(guidance["primary_tools"]) | set(guidance["advanced_tools"])
    assert guidance["preferred_first_entrypoint"] in COMMANDER_EXPOSED_TOOLS
    assert recommended <= set(COMMANDER_EXPOSED_TOOLS)
    assert all(
        tool_routing_metadata(tool)["classification"] == TOOL_TIER_PRIMARY
        for tool in guidance["primary_tools"]
    )


def test_source_observer_guidance_contains_only_read_only_tools() -> None:
    guidance = profile_guidance("source_observer")
    recommended = guidance["primary_tools"] + guidance["advanced_tools"]

    assert "manage_files" not in recommended
    assert {
        "get_repo_overview",
        "get_source_file",
        "search_source",
        "get_runtime_version_status",
    } <= set(recommended)
    assert all(
        tool_routing_metadata(tool)["side_effect_level"] == "READ_ONLY"
        for tool in recommended
    )


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
    ("error_code", "expected_class", "should_stop", "retryable"),
    [
        ("PREVIEW_EXPIRED", "new_preview_required", False, True),
        ("CONTEXT_BINDING_MISMATCH", "context_changed", False, True),
        ("EXECUTOR_ALREADY_RUNNING", "wait_for_running_operation", False, True),
        ("VALIDATION_FAILED", "operator_action_required", False, True),
        ("INSUFFICIENT_SCOPE", "authorization_required", True, True),
        ("SCOPE_VIOLATION", "authorization_required", True, True),
        ("CONFIRMATION_REQUIRED", "operator_action_required", True, True),
        ("UNSUPPORTED_TRANSITION", "unsupported_by_current_surface", False, False),
        ("AUTHORITY_MISMATCH", "hard_stop", True, False),
        ("PREREQUISITE_NOT_READY", "refresh_state_then_retry", False, True),
    ],
)
def test_recovery_classes_are_machine_readable(
    error_code: str,
    expected_class: str,
    should_stop: bool,
    retryable: bool,
) -> None:
    recovery = recovery_projection(error_code)

    assert recovery is not None
    assert recovery["recovery_class"] == expected_class
    assert recovery["agent_should_stop"] is should_stop
    assert recovery["retryable"] is retryable
    assert recovery["does_not_grant_authority"] is True


def test_external_connector_failure_does_not_claim_automatic_recovery() -> None:
    recovery = recovery_projection("CONNECTOR_PRINCIPAL_REJECTED")

    assert recovery is not None
    assert recovery["error_origin"] == "connector"
    assert recovery["recovery_class"] == "operator_action_required"
    assert recovery["agent_should_stop"] is True


@pytest.mark.parametrize(
    "error_code",
    ["CONNECTOR_PRINCIPAL_REJECTED", "CONNECTOR_OAUTH_SCOPE_REJECTED"],
)
def test_connector_origin_precedes_oauth_markers(error_code: str) -> None:
    recovery = recovery_projection(error_code)

    assert recovery is not None
    assert recovery["error_origin"] == "connector"
    assert recovery["recovery_class"] == "operator_action_required"


def test_unknown_colameta_error_stops_instead_of_retrying() -> None:
    recovery = recovery_projection("SOME_NEW_INTEGRITY_PRECONDITION")

    assert recovery is not None
    assert recovery["error_origin"] == "colameta_application"
    assert recovery["recovery_class"] == "operator_action_required"
    assert recovery["agent_should_stop"] is True
    assert recovery["retryable"] is False


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


def test_patch_handle_precedes_generic_core_preview_ids() -> None:
    continuation = typed_continuation_projection(
        {
            "preview_ids": ["patch_1"],
            "next_actions": [
                {
                    "tool": "manage_plan_version",
                    "params": {"action": "apply", "patch_id": "patch_1"},
                }
            ],
            "result": {"patch_id": "patch_1"},
        },
        source_tool="run_mcp_workflow",
    )

    assert continuation is not None
    assert continuation["kind"] == "plan_patch"
    assert continuation["field_name"] == "patch_id"
    assert continuation["id"] == "patch_1"


@pytest.mark.parametrize(
    ("action", "expected_action"),
    [
        (
            {
                "tool": "run_mcp_workflow",
                "params": {
                    "workflow": "git_commit",
                    "phase": "commit",
                    "preview_id": "preview_git",
                },
            },
            "commit",
        ),
        (
            {
                "tool": "manage_git_commit",
                "params": {"action": "commit", "preview_id": "preview_git"},
            },
            "commit",
        ),
        (
            {
                "tool": "manage_executor_workflow",
                "params": {"action": "run_once", "preview_id": "preview_once"},
            },
            "run_once",
        ),
        (
            {
                "tool": "manage_executor_workflow",
                "params": {"action": "run_bounded", "preview_id": "preview_bounded"},
            },
            "run_bounded",
        ),
    ],
)
def test_preview_continuation_derives_the_workflow_specific_consuming_action(
    action: dict,
    expected_action: str,
) -> None:
    preview_id = action["params"]["preview_id"]
    continuation = typed_continuation_projection(
        {"preview_ids": [preview_id], "next_actions": [action]},
        source_tool="run_mcp_workflow",
    )

    assert continuation is not None
    assert continuation["field_name"] == "preview_id"
    assert continuation["id"] == preview_id
    assert continuation["allowed_next_actions"] == [expected_action]


def test_context_free_preview_handle_does_not_invent_a_consuming_action() -> None:
    continuation = typed_continuation_projection(
        {"preview_id": "preview_unknown"},
        source_tool="run_mcp_workflow",
    )

    assert continuation is not None
    assert continuation["allowed_next_actions"] == []
    assert continuation["why_no_allowed_next_action"]


def test_auto_preview_plan_route_preserves_production_patch_handle(tmp_path) -> None:
    result = MCPWorkflowRouter(
        str(tmp_path),
        plan_workflow_manager=_PlanPreviewManager(),  # type: ignore[arg-type]
    ).handle(
        "auto_preview",
        {
            "goal": "Update the implementation plan",
            "name": "R2",
            "description": "Bounded follow-up",
        },
    )

    assert result["selected_workflow"] == "plan_update"
    assert result["preview_ids"] == ["patch_production_1"]
    assert result["continuation"]["kind"] == "plan_patch"
    assert result["continuation"]["field_name"] == "patch_id"
    assert result["continuation"]["id"] == "patch_production_1"
    assert result["continuation"]["allowed_next_actions"] == [
        "apply_preview_status",
        "apply_preview",
    ]


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


def test_same_source_refresh_fallback_is_not_promoted_to_primary_action() -> None:
    fallback = {
        "tool": "analyze_project_state",
        "action": "refresh_project_state",
        "params": {},
        "reason": "Refresh project state.",
    }
    projected = add_agent_state_projection(
        {"ok": True, "recommended_next_actions": [fallback]},
        source_tool="analyze_project_state",
    )

    assert projected["primary_next_action"] is None
    assert projected["why_no_unique_action"]


def test_same_source_refresh_fallback_yields_to_next_usable_action() -> None:
    projected = add_agent_state_projection(
        {
            "ok": True,
            "recommended_next_actions": [
                {
                    "tool": "analyze_project_state",
                    "action": "refresh_project_state",
                    "params": {},
                },
                {
                    "tool": "manage_validation_run",
                    "action": "preview",
                    "params": {"action": "preview"},
                },
            ],
        },
        source_tool="analyze_project_state",
    )

    assert projected["primary_next_action"]["tool"] == "manage_validation_run"
    assert projected["primary_next_action"]["action"] == "preview"


def test_analyze_project_state_exposes_the_canonical_projection(tmp_path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="commander")

    result = server._tool_analyze_project_state({"include_reports": False})

    assert result["agent_projection_schema_version"] == "colameta.agent_state_projection.v1"
    assert result["agent_state"]["profile_id"] == "web_gpt_commander"
    assert result["blocked_next_actions"]["exhaustive"] is False
    assert verify_agent_projection(result) == []


def test_registered_project_analysis_publishes_copyable_project_bound_action(tmp_path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    subprocess.run(["git", "-C", str(project), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(project), "config", "user.name", "Test"], check=True)
    (project / "README.md").write_text("fixture\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(project), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(project), "commit", "-qm", "fixture"], check=True)

    server = MCPPlanningBridgeServer(
        str(project),
        service_mode=True,
        exposure_profile="commander",
    )
    server.project_registry = ProjectRegistry(
        registry_path=str(tmp_path / "registry.json"),
        user_settings_path=str(tmp_path / "settings.json"),
    )
    registered = server.project_registry.register_project(
        str(project),
        project_name="demo-project",
        last_selected=False,
    )
    assert registered["ok"] is True

    response = server.call_tool_for_agent(
        "analyze_project_state",
        {"project_name": "demo-project", "include_reports": False},
    )

    assert response["ok"] is True
    public_action = response["data"]["next_action"]
    assert public_action["arguments"]["project_name"] == "demo-project"
    projected_action = response["data"]["facts"]["primary_next_action"]
    assert projected_action["params"]["project_name"] == "demo-project"
    assert projected_action["required_arguments"]["project_name"] == "demo-project"

    followup = server.call_tool_for_agent(
        public_action["tool"],
        public_action["arguments"],
    )
    assert followup.get("error_code") != "PROJECT_NAME_REQUIRED"


def test_project_binding_preserves_copyable_action_arguments() -> None:
    projected = add_agent_state_projection(
        {
            "recommended_next_actions": [
                {
                    "tool": "run_mcp_workflow",
                    "copyable_tool_call": {
                        "tool": "run_mcp_workflow",
                        "arguments": {"workflow": "source_onboarding", "phase": "preview"},
                    }
                }
            ]
        },
        source_tool="analyze_project_state",
        project_name="demo-project",
    )

    primary = projected["primary_next_action"]
    assert primary["required_arguments"] == {
        "workflow": "source_onboarding",
        "phase": "preview",
        "project_name": "demo-project",
    }


def test_auto_preview_exposes_selected_workflow_and_projection(tmp_path) -> None:
    router = MCPWorkflowRouter(str(tmp_path), analyze_state_fn=lambda _params: {"ok": True})

    result = router.handle("auto_preview", {"goal": "Inspect project state; do not start executor."})

    assert result["selected_workflow"] == "project_status"
    assert result["classified_intent"]["selected_workflow"] == "project_status"
    assert result["classified_intent"]["does_not_grant_authority"] is True
    assert result["agent_state"]["goal"].startswith("Inspect project state")
    assert result["routing"]["selected_workflow"] == "project_status"
    assert verify_agent_projection(result) == []


def test_auto_preview_commander_never_projects_an_unreachable_executor_tool(tmp_path) -> None:
    result = MCPWorkflowRouter(
        str(tmp_path),
        agent_profile_id="web_gpt_commander",
    ).handle("auto_preview", {"goal": "Run the executor for this task"})

    guidance = result["routing"]["profile"]
    reachable = set(guidance["primary_tools"]) | set(guidance["advanced_tools"])
    primary = result["primary_next_action"]
    assert result["selected_workflow"] == "executor_preflight"
    assert primary is None or primary["tool"] in reachable
    assert primary is None
    assert result["why_no_unique_action"]

    local_result = MCPWorkflowRouter(
        str(tmp_path),
        agent_profile_id="local_codex_commander",
    ).handle("auto_preview", {"goal": "Run the executor for this task"})
    assert local_result["primary_next_action"]["tool"] == "manage_executor_workflow"


def test_registered_project_auto_preview_preserves_serving_commander_profile(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    subprocess.run(
        ["git", "-C", str(project), "config", "user.email", "test@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(project), "config", "user.name", "Test"],
        check=True,
    )
    (project / "README.md").write_text("fixture\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(project), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(project), "commit", "-qm", "fixture"], check=True)

    snapshot = snapshot_from_fact_bundle(
        str(project),
        {
            "executor_session_status": {"ok": True, "active": False},
            "continuation_preview": {"ok": True},
            "requested_provider": "codex",
            "selected_provider": None,
            "identity_present": False,
            "provider_resume_supported": True,
            "resume_invocation_verified": True,
            "operation_running": False,
            "job_status": "idle",
            "latest_run_status": "completed",
            "runner_status": "VERSION_PASSED",
            "current_version_status": "PASSED",
            "worktree_clean": True,
            "hard_blockers": [],
            "risk_warnings": [],
        },
    )
    monkeypatch.setattr(
        "runner.core_orchestrator.get_or_collect_continuation_snapshot",
        lambda *_args, **_kwargs: snapshot,
    )
    monkeypatch.setattr(
        "runner.executor_inventory.load_executor_inventory",
        lambda _project_root: {"ok": True, "available": True, "providers": ["codex"]},
    )

    server = MCPPlanningBridgeServer(
        str(tmp_path),
        service_mode=True,
        exposure_profile="commander",
    )
    server.project_registry = ProjectRegistry(
        registry_path=str(tmp_path / "registry.json"),
        user_settings_path=str(tmp_path / "settings.json"),
    )
    registered = server.project_registry.register_project(
        str(project),
        project_name="demo-project",
        project_mode="managed",
        last_selected=False,
    )
    assert registered["ok"] is True

    response = server.call_tool_for_agent(
        "run_mcp_workflow",
        {
            "workflow": "auto_preview",
            "goal": "Run the executor for this task",
            "project_name": "demo-project",
        },
    )

    assert response["ok"] is True
    assert response["data"]["outcome"] == "completed"
    facts = response["data"]["facts"]
    assert facts["selected_workflow"] == "executor_preflight"
    assert facts["agent_state"]["profile_id"] == "web_gpt_commander"
    assert facts["agent_state"]["project"] == "demo-project"
    assert facts.get("primary_next_action") is None
    assert "manage_executor_workflow" not in json.dumps(response, sort_keys=True)


@pytest.mark.parametrize(
    ("goal", "expected_workflow"),
    [
        ("Editing a source file", "small_project_patch"),
        ("Patching the code", "small_project_patch"),
        ("Committing the current changes", "git_commit"),
        ("Commiting the current changes", "git_commit"),
        ("Execute the bounded task", "executor_preflight"),
        ("The agent executes this task", "executor_preflight"),
        ("The task executed through Codex", "executor_preflight"),
        ("Executing the bounded task", "executor_preflight"),
        ("Start execution for this task", "executor_preflight"),
    ],
)
def test_auto_preview_preserves_common_inflected_routing_keywords(
    tmp_path,
    goal: str,
    expected_workflow: str,
) -> None:
    result = MCPWorkflowRouter(str(tmp_path)).handle("auto_preview", {"goal": goal})

    assert result["selected_workflow"] == expected_workflow


@pytest.mark.parametrize(
    ("goal", "expected_workflow"),
    [
        ("plan_update", "plan_update"),
        ("git_commit", "git_commit"),
        ("small_project_patch", "small_project_patch"),
        ("executor_preflight", "executor_preflight"),
    ],
)
def test_auto_preview_treats_underscores_as_canonical_name_separators(
    tmp_path,
    goal: str,
    expected_workflow: str,
) -> None:
    result = MCPWorkflowRouter(str(tmp_path)).handle("auto_preview", {"goal": goal})

    assert result["selected_workflow"] == expected_workflow


def test_auto_preview_projects_nested_production_state_instead_of_workflow_envelope(tmp_path) -> None:
    state = {
        "ok": True,
        "status": "EXECUTOR_RUNNING",
        "current_version": "R9",
        "phase": "implementation",
        "recommended_next_actions": [],
    }
    result = MCPWorkflowRouter(str(tmp_path), analyze_state_fn=lambda _params: state).handle(
        "auto_preview", {"goal": ""}
    )

    assert result["status"] == "succeeded"
    assert result["agent_state"]["status"] == "EXECUTOR_RUNNING"
    assert result["agent_state"]["operation_status"] == "succeeded"
    assert result["agent_state"]["current_version"] == "R9"
    assert result["agent_state"]["current_phase"] == "implementation"
    assert result["primary_next_action"]["tool"] == "manage_executor_workflow"
    assert result["primary_next_action"]["action"] == "status"


def test_auto_preview_production_path_wraps_nested_connector_error_conservatively(tmp_path) -> None:
    state = {
        "ok": False,
        "error_code": "CONNECTOR_PRINCIPAL_REJECTED",
        "message": "Connector rejected the current principal.",
        "recommended_next_actions": [],
    }
    result = MCPWorkflowRouter(str(tmp_path), analyze_state_fn=lambda _params: state).handle(
        "auto_preview", {"goal": ""}
    )

    assert result["status"] == "failed"
    assert result["error_code"] == "CONNECTOR_PRINCIPAL_REJECTED"
    assert result["error_origin"] == "connector"
    assert result["recovery"]["recovery_class"] == "operator_action_required"
    assert result["recovery"]["agent_should_stop"] is True


def test_auto_preview_production_path_stops_on_unknown_application_error(tmp_path) -> None:
    state = {
        "ok": False,
        "error_code": "SOME_NEW_INTEGRITY_PRECONDITION",
        "message": "No reviewed recovery classification exists.",
        "recommended_next_actions": [],
    }
    result = MCPWorkflowRouter(str(tmp_path), analyze_state_fn=lambda _params: state).handle(
        "auto_preview", {"goal": ""}
    )

    assert result["error_origin"] == "colameta_application"
    assert result["recovery"]["recovery_class"] == "operator_action_required"
    assert result["recovery"]["agent_should_stop"] is True
    assert result["recovery"]["retryable"] is False


def _build_fixture_canonical_state(tmp_path: Path, fixture: dict) -> dict:
    inputs = fixture["canonical_inputs"]
    mode = inputs.get("mode", "runner_managed")
    pending_count = inputs.get("pending_count", 0)
    observed_at = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)
    observation = {"status": "current", "observed_at": "2026-09-02T12:00:00Z"}
    return build_canonical_project_state(
        project_root=str(tmp_path),
        project_identity={"project_name": "routing-fixture"},
        mode=mode,
        git={
            "ok": True,
            "branch": "fixture",
            "head": "a" * 40,
            "working_tree_clean": inputs.get("delivery_clean", True),
            "blocking_working_tree_clean": inputs.get("delivery_clean", True),
            "ignored_runner_runtime_files": [],
        },
        runner={
            "has_runner_state": mode == "runner_managed",
            "runner_status": "READY",
            "current_version": "R1",
            "current_version_status": "NOT_STARTED" if pending_count else "PASSED",
            "pending_count": pending_count,
            "has_pending_versions": pending_count > 0,
        },
        plan={"has_plan": mode == "runner_managed"},
        executor={
            "has_session": inputs.get("executor_has_session", False),
            "continuation_available": False,
        },
        reports={},
        blockers=inputs.get("blockers", []),
        warnings=[],
        partial_errors=[],
        observed_at=observed_at,
        runtime_observation=observation,
        connector_observation=observation,
    )


def test_canonical_routing_fixtures(tmp_path) -> None:
    fixtures = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    assert len(fixtures) >= 20
    for fixture in fixtures:
        expected = fixture["expected"]
        classified = WorkflowOrchestrator._classify_goal(fixture["intent"])
        assert classified["selected_workflow"] == expected["selected_workflow"], fixture["name"]

        canonical_state = _build_fixture_canonical_state(tmp_path, fixture)
        initial_state = {
            "ok": True,
            "canonical_state": canonical_state,
            "recommended_next_actions": fixture.get("recommended_next_actions", []),
            **({"result": fixture["result"]} if "result" in fixture else {}),
            **({"error_code": fixture["error_code"]} if "error_code" in fixture else {}),
        }
        assert canonical_state["schema_version"] == "colameta.canonical_project_state.v1"
        assert canonical_state["current_conclusion"]["authorization"] == "observation_only"

        packet = add_agent_state_projection(
            initial_state,
            source_tool="analyze_project_state",
            goal=fixture["intent"],
        )
        action = packet["primary_next_action"]
        assert action is not None, fixture["name"]
        assert {"tool": action["tool"], "action": action["action"]} == expected["primary_next_action"]
        actual_recovery = packet["recovery"]["recovery_class"] if packet["recovery"] else None
        assert actual_recovery == expected["recovery_class"], fixture["name"]
        assert packet["blocked_next_actions"]["exhaustive"] is False
        assert verify_agent_projection(packet) == [], fixture["name"]
        assert verify_authority_expectation(packet, expected["authority_expectation"]) == [], fixture["name"]
        assert tool_routing_metadata(action["tool"])["classification"] != TOOL_TIER_LEGACY_OR_INTERNAL
