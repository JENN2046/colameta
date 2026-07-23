from __future__ import annotations

import pytest

from runner.mcp_workflow_policy import (
    WORKFLOW_CONTEXT_MUTATION_PHASES,
    run_mcp_workflow_policy_scope,
)


@pytest.mark.parametrize(
    ("params", "expected_scope"),
    [
        ({"workflow": "auto_preview"}, "mcp:preview"),
        ({"workflow": "project_status", "phase": "inspect"}, "mcp:read"),
        ({"workflow": "source_onboarding", "phase": "preview"}, "mcp:preview"),
        ({"workflow": "plan_update", "phase": "apply"}, "mcp:plan"),
        ({"workflow": "small_project_patch", "phase": "status"}, "mcp:read"),
        ({"workflow": "docs_update", "phase": "preview", "docs_action": "sync_docs_preview"}, "mcp:preview"),
        ({"workflow": "git_commit", "phase": "commit"}, "mcp:commit"),
        ({"workflow": "git_restore_file", "phase": "preview"}, "mcp:preview"),
        ({"workflow": "git_revert", "phase": "apply"}, "mcp:commit"),
        ({"workflow": "git_undo_version", "phase": "inspect"}, "mcp:read"),
        ({"workflow": "agent_dispatch", "phase": "run_preview"}, "mcp:preview"),
        ({"workflow": "prompt_to_plan", "phase": "plan_apply"}, "mcp:plan"),
        ({"workflow": "thin_governed_loop_preview", "phase": "preview"}, "mcp:read"),
        ({"workflow": "review_manifest", "phase": "verify"}, "mcp:read"),
        ({"workflow": "result_artifact", "phase": "read"}, "mcp:read"),
        ({"workflow": "gate_review_request", "phase": "preview"}, "mcp:preview"),
        ({"workflow": "operator_batch", "phase": "execute"}, "mcp:commit"),
    ],
)
def test_run_mcp_workflow_policy_covers_each_migration_workflow(
    params: dict[str, object],
    expected_scope: str,
) -> None:
    assert run_mcp_workflow_policy_scope(params) == expected_scope


@pytest.mark.parametrize(
    "params",
    [
        {"workflow": "result_artifact", "phase": "verify"},
        {"workflow": "review_manifest", "phase": "apply"},
        {"workflow": "operator_batch", "phase": "run"},
        {"workflow": "plan_update", "phase": "run"},
        {"workflow": "unknown", "phase": "inspect"},
    ],
)
def test_run_mcp_workflow_policy_fails_closed_for_invalid_phase_or_workflow(
    params: dict[str, object],
) -> None:
    assert run_mcp_workflow_policy_scope(params) is None


def test_context_binding_tracks_only_real_mutation_boundaries() -> None:
    assert WORKFLOW_CONTEXT_MUTATION_PHASES == {
        "plan_update": frozenset({"apply"}),
        "small_project_patch": frozenset({"apply"}),
        "docs_update": frozenset({"apply"}),
        "git_commit": frozenset({"commit"}),
        "git_restore_file": frozenset({"apply"}),
        "git_revert": frozenset({"apply"}),
        "git_undo_version": frozenset({"apply"}),
        "agent_dispatch": frozenset({"apply", "run"}),
        "prompt_to_plan": frozenset({"apply", "apply_all", "plan_apply", "run"}),
        "operator_batch": frozenset({"execute"}),
    }
