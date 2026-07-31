from __future__ import annotations

import pytest

from runner.commander_workflow_policy import (
    COMMANDER_JOURNEY_STAGES,
    journey_stage_for,
    select_commander_next_action,
)
from runner.mcp_commander_public import COMMANDER_EXPOSED_TOOLS


ARTIFACT_ID = "artifact_handle_1234567890"
MANIFEST_ID = "manifest_handle_1234567890"
PREVIEW_ID = "preview_handle_1234567890"


@pytest.mark.parametrize(
    ("tool_name", "expected"),
    [
        ("list_registered_projects", "connect"),
        ("get_apps_connector_smoke_packet", "connect"),
        ("render_commander_app", "connect"),
        ("analyze_project_state", "observe"),
        ("review_manifest", "review"),
        ("read_result_artifact", "review"),
        ("manage_validation_run", "validate"),
        ("manage_git", "close"),
    ],
)
def test_public_tools_have_deterministic_journey_stages(
    tool_name: str,
    expected: str,
) -> None:
    assert journey_stage_for(tool_name, {}, {}) == expected


@pytest.mark.parametrize(
    ("workflow", "expected"),
    [
        ("project_status", "observe"),
        ("source_onboarding", "plan"),
        ("plan_update", "plan"),
        ("prompt_to_plan", "plan"),
        ("small_project_patch", "execute"),
        ("docs_update", "execute"),
        ("agent_dispatch", "execute"),
        ("git_restore_file", "recover"),
        ("git_revert", "recover"),
        ("git_undo_version", "recover"),
        ("auto_preview", "plan"),
        ("git_commit", "close"),
    ],
)
def test_workflows_have_frozen_journey_stages(
    workflow: str,
    expected: str,
) -> None:
    assert (
        journey_stage_for(
            "run_mcp_workflow",
            {"workflow": workflow},
            {},
        )
        == expected
    )


def test_thin_governed_loop_uses_observed_stage_or_plan_default() -> None:
    assert (
        journey_stage_for(
            "run_mcp_workflow",
            {"workflow": "thin_governed_loop_preview"},
            {"data": {"current_stage": "review"}},
        )
        == "review"
    )
    assert (
        journey_stage_for(
            "run_mcp_workflow",
            {"workflow": "thin_governed_loop_preview"},
            {"data": {}},
        )
        == "plan"
    )


@pytest.mark.parametrize(
    ("action", "expected"),
    [
        ("status", "close"),
        ("commit_preview", "close"),
        ("restore_file_preview", "recover"),
        ("restore_file_apply", "recover"),
        ("revert_preview", "recover"),
        ("revert_apply", "recover"),
    ],
)
def test_manage_git_recovery_actions_use_recover_stage(
    action: str,
    expected: str,
) -> None:
    assert journey_stage_for("manage_git", {"action": action}, {}) == expected


def test_journey_stage_inventory_is_closed() -> None:
    assert COMMANDER_JOURNEY_STAGES == {
        "connect",
        "observe",
        "plan",
        "execute",
        "review",
        "validate",
        "close",
        "recover",
    }
    assert journey_stage_for("unknown_tool", {}, {}) == "recover"


def test_confirmation_selects_apply_action_even_when_legacy_uses_params() -> None:
    action = select_commander_next_action(
        tool_name="manage_git",
        params={"action": "commit_preview"},
        raw_result={
            "data": {
                "next_actions": [
                    {
                        "tool": "manage_git",
                        "params": {
                            "action": "commit_apply",
                            "preview_id": PREVIEW_ID,
                        },
                        "reason": "确认并提交。",
                    }
                ]
            }
        },
        outcome="confirmation_required",
    )

    assert action == {
        "tool": "manage_git",
        "arguments": {
            "action": "commit_apply",
            "preview_id": PREVIEW_ID,
        },
        "reason": "确认并提交。",
    }


def test_git_commit_workflow_is_mapped_to_manage_git() -> None:
    action = select_commander_next_action(
        tool_name="run_mcp_workflow",
        params={"workflow": "docs_update"},
        raw_result={
            "next_action": {
                "tool": "run_mcp_workflow",
                "arguments": {
                    "workflow": "git_commit",
                    "phase": "preview",
                    "message": "docs: update guide",
                    "project_name": "colameta",
                },
                "reason": "准备提交。",
            }
        },
        outcome="completed",
    )

    assert action == {
        "tool": "manage_git",
        "arguments": {
            "action": "commit_preview",
            "message": "docs: update guide",
            "project_name": "colameta",
        },
        "reason": "准备提交。",
    }


@pytest.mark.parametrize(
    ("legacy_tool", "expected_action"),
    [
        ("get_git_status", "status"),
        ("get_git_diff", "diff"),
    ],
)
def test_legacy_git_reads_map_to_the_correct_public_action(
    legacy_tool: str,
    expected_action: str,
) -> None:
    action = select_commander_next_action(
        tool_name="analyze_project_state",
        params={"project_name": "colameta"},
        raw_result={
            "recommended_next_action": {
                "tool": legacy_tool,
                "params": {"project_name": "colameta"},
                "reason": "读取 Git。",
            }
        },
        outcome="completed",
    )

    assert action == {
        "tool": "manage_git",
        "arguments": {
            "action": expected_action,
            "project_name": "colameta",
        },
        "reason": "读取 Git。",
    }


def test_auto_preview_is_callable_but_never_recommended() -> None:
    action = select_commander_next_action(
        tool_name="analyze_project_state",
        params={},
        raw_result={
            "recommended_next_actions": [
                {
                    "tool": "run_mcp_workflow",
                    "arguments": {
                        "workflow": "auto_preview",
                        "goal": "update docs",
                    },
                    "reason": "legacy recommendation",
                },
                {
                    "tool": "run_mcp_workflow",
                    "arguments": {"workflow": "plan_update"},
                    "reason": "prepare plan",
                },
            ]
        },
        outcome="completed",
    )

    assert action is not None
    assert action["arguments"]["workflow"] == "plan_update"


def test_non_commander_tool_is_filtered_without_guessing() -> None:
    action = select_commander_next_action(
        tool_name="analyze_project_state",
        params={},
        raw_result={
            "recommended_next_action": {
                "tool": "manage_files",
                "arguments": {"action": "write"},
                "reason": "internal-only",
            }
        },
        outcome="completed",
    )

    assert action is None


def test_copy_paste_next_request_is_also_filtered() -> None:
    action = select_commander_next_action(
        tool_name="analyze_project_state",
        params={},
        raw_result={
            "copy_paste_next_request": {
                "tool": "manage_executor_workflow",
                "arguments": {"action": "run_once"},
                "reason": "internal-only",
            }
        },
        outcome="completed",
    )

    assert action is None


def test_result_artifact_resource_read_maps_to_typed_tool() -> None:
    action = select_commander_next_action(
        tool_name="run_mcp_workflow",
        params={"workflow": "docs_update"},
        raw_result={
            "recommended_next_read": {
                "tool": "resources/read",
                "arguments": {
                    "uri": (
                        f"colameta://result-artifact/{ARTIFACT_ID}/pages/2"
                    )
                },
                "reason": "读取下一页。",
            }
        },
        outcome="completed",
    )

    assert action == {
        "tool": "read_result_artifact",
        "arguments": {
            "artifact_id": ARTIFACT_ID,
            "artifact_page": 2,
        },
        "reason": "读取下一页。",
    }


@pytest.mark.parametrize(
    ("uri", "expected_arguments"),
    [
        (
            f"colameta://review-manifest/{MANIFEST_ID}",
            {
                "phase": "status",
                "review_manifest_id": MANIFEST_ID,
            },
        ),
        (
            (
                f"colameta://review-manifest/{MANIFEST_ID}"
                "/subjects/3/pages/2"
            ),
            {
                "phase": "read",
                "review_manifest_id": MANIFEST_ID,
                "review_manifest_subject_index": 3,
                "review_manifest_page": 2,
            },
        ),
    ],
)
def test_review_manifest_resource_maps_to_public_input_schema(
    uri: str,
    expected_arguments: dict,
) -> None:
    action = select_commander_next_action(
        tool_name="review_manifest",
        params={"phase": "inspect"},
        raw_result={
            "recommended_next_read": {
                "tool": "resources/read",
                "params": {"uri": uri},
                "reason": "读取审查证据。",
            }
        },
        outcome="completed",
    )

    assert action == {
        "tool": "review_manifest",
        "arguments": expected_arguments,
        "reason": "读取审查证据。",
    }


def test_confirmation_priority_is_deterministic() -> None:
    action = select_commander_next_action(
        tool_name="manage_git",
        params={"action": "commit_preview"},
        raw_result={
            "next_actions": [
                {
                    "tool": "analyze_project_state",
                    "arguments": {},
                    "reason": "poll",
                },
                {
                    "tool": "manage_git",
                    "arguments": {
                        "action": "commit_apply",
                        "preview_id": PREVIEW_ID,
                    },
                    "reason": "confirm",
                },
                {
                    "tool": "review_manifest",
                    "arguments": {"phase": "status"},
                    "reason": "review",
                },
            ]
        },
        outcome="confirmation_required",
    )

    assert action is not None
    assert action["tool"] == "manage_git"
    assert action["arguments"]["action"] == "commit_apply"


def test_blocked_prefers_recovery_over_polling() -> None:
    action = select_commander_next_action(
        tool_name="manage_git",
        params={"action": "restore_file_preview"},
        raw_result={
            "next_actions": [
                {
                    "tool": "analyze_project_state",
                    "arguments": {},
                    "reason": "poll",
                },
                {
                    "tool": "run_mcp_workflow",
                    "arguments": {"workflow": "git_restore_file"},
                    "reason": "recover",
                },
            ]
        },
        outcome="blocked",
    )

    assert action is not None
    assert action["tool"] == "run_mcp_workflow"
    assert action["arguments"]["workflow"] == "git_restore_file"


def test_blocked_without_explicit_recovery_rereads_project_facts() -> None:
    action = select_commander_next_action(
        tool_name="run_mcp_workflow",
        params={
            "workflow": "small_project_patch",
            "project_name": "colameta",
        },
        raw_result={
            "data": {
                "error_code": "SCOPE_VIOLATION",
                "code": "PROJECT_NOT_REGISTERED",
                "steps": [
                    {
                        "error_code": "PROJECT_UNAVAILABLE",
                    }
                ],
            }
        },
        outcome="blocked",
    )

    assert action == {
        "tool": "analyze_project_state",
        "arguments": {"project_name": "colameta"},
        "reason": "重新读取项目事实后再决定如何解除阻断。",
    }


@pytest.mark.parametrize(
    ("raw_result", "params"),
    [
        (
            {"error_code": "PROJECT_NAME_REQUIRED"},
            {"workflow": "project_status"},
        ),
        (
            {"error_code": "PROJECT_REQUIRED"},
            {"workflow": "project_status"},
        ),
        (
            {"error_code": "INVALID_PROJECT_NAME"},
            {"workflow": "project_status"},
        ),
        (
            {"error": {"code": "PROJECT_NOT_REGISTERED"}},
            {
                "workflow": "project_status",
                "project_name": "stale-project",
            },
        ),
        (
            {"error_code": "PROJECT_UNAVAILABLE"},
            {
                "workflow": "project_status",
                "project_name": "unavailable-project",
            },
        ),
        (
            {"error_code": "PROJECT_ROOT_UNAVAILABLE"},
            {
                "workflow": "project_status",
                "project_name": "missing-root-project",
            },
        ),
        (
            {
                "result": {
                    "diagnostics": {
                        "error_code": "PROJECT_UNAVAILABLE",
                    }
                }
            },
            {
                "workflow": "project_status",
                "project_name": "unavailable-project",
            },
        ),
    ],
)
def test_project_selection_blockers_recover_through_registered_project_list(
    raw_result: dict,
    params: dict,
) -> None:
    action = select_commander_next_action(
        tool_name="run_mcp_workflow",
        params=params,
        raw_result=raw_result,
        outcome="blocked",
    )

    assert action == {
        "tool": "list_registered_projects",
        "arguments": {},
        "reason": "列出可用项目后，使用有效 project_name 重试原调用。",
    }


def test_in_progress_ignores_review_and_returns_polling() -> None:
    action = select_commander_next_action(
        tool_name="manage_validation_run",
        params={"action": "status", "project_name": "colameta"},
        raw_result={
            "data": {
                "run_id": "validation_run_1234567890",
                "next_actions": [
                    {
                        "tool": "review_manifest",
                        "arguments": {"phase": "status"},
                        "reason": "review",
                    }
                ],
            }
        },
        outcome="in_progress",
    )

    assert action == {
        "tool": "manage_validation_run",
        "arguments": {
            "action": "status",
            "run_id": "validation_run_1234567890",
            "project_name": "colameta",
        },
        "reason": "查询当前验证运行状态。",
    }


def test_synthetic_confirmation_is_bound_to_preview_and_context() -> None:
    context_binding = {
        "project_name": "colameta",
        "branch": "codex/test",
        "head": "a" * 40,
        "runner_plan": {"mode": "managed", "plan_sha256": "b" * 64},
        "current_version": "N1",
        "review_unit": "git-commit-preview",
        "workflow_intent": "create-local-commit",
    }
    action = select_commander_next_action(
        tool_name="manage_git",
        params={
            "action": "commit_preview",
            "project_name": "colameta",
            "message": "feat: contract",
        },
        raw_result={
            "data": {
                "preview_id": PREVIEW_ID,
                "context_binding": context_binding,
            }
        },
        outcome="confirmation_required",
    )

    assert action is not None
    assert action["tool"] == "manage_git"
    assert action["arguments"] == {
        "preview_id": PREVIEW_ID,
        "project_name": "colameta",
        "context_binding": context_binding,
        "action": "commit_apply",
        "message": "feat: contract",
    }


def test_every_selected_action_references_the_nine_tool_inventory() -> None:
    action = select_commander_next_action(
        tool_name="analyze_project_state",
        params={},
        raw_result={
            "recommended_next_actions": [
                {
                    "tool": "manage_validation_run",
                    "arguments": {"action": "inspect"},
                    "reason": "validate",
                },
                {
                    "tool": "manage_git",
                    "arguments": {"action": "commit_preview"},
                    "reason": "commit",
                },
            ]
        },
        outcome="completed",
    )

    assert action is not None
    assert action["tool"] in COMMANDER_EXPOSED_TOOLS
    assert isinstance(action, dict)
