"""Pure policy contracts for the legacy ``run_mcp_workflow`` surface.

The MCP server owns authentication and enforcement.  This module owns the
workflow/phase-to-scope matrix and the exact phases that reach a mutation
boundary.  Keeping those tables beside the P1 migration contract prevents the
transport composition root from becoming a second workflow implementation.
"""

from __future__ import annotations

from typing import Any

from runner.mcp_gate_review_workflow import GATE_REVIEW_WORKFLOW
from runner.mcp_current_facts import CURRENT_FACTS_WORKFLOW
from runner.mcp_stage_7_9_preview import STAGE_7_9_PREVIEW_WORKFLOW
from runner.mcp_workflow_migration import OPERATOR_BATCH_WORKFLOW, RESULT_ARTIFACT_WORKFLOW
from runner.review_manifest import REVIEW_MANIFEST_WORKFLOW


# Context binding belongs at the real side-effect boundary, not merely at a
# phase name that another workflow happens to reject.  In particular,
# git_commit/apply is intentionally unsupported by the core workflow; asking
# for a context binding before returning PHASE_NOT_SUPPORTED would obscure the
# actual contract violation.  Keep this table aligned with the core workflow
# phase handlers and the public policy matrix below.
WORKFLOW_CONTEXT_MUTATION_PHASES: dict[str, frozenset[str]] = {
    "plan_update": frozenset({"apply"}),
    "small_project_patch": frozenset({"apply"}),
    "docs_update": frozenset({"apply"}),
    "git_commit": frozenset({"commit"}),
    "git_restore_file": frozenset({"apply"}),
    "git_revert": frozenset({"apply"}),
    "git_undo_version": frozenset({"apply"}),
    "agent_dispatch": frozenset({"apply", "run"}),
    "prompt_to_plan": frozenset({"apply", "apply_all", "plan_apply", "run"}),
    CURRENT_FACTS_WORKFLOW: frozenset({"apply"}),
    OPERATOR_BATCH_WORKFLOW: frozenset({"execute"}),
    "github_delivery": frozenset({"pr_apply"}),
}


def policy_string_param(params: dict[str, Any], key: str) -> str:
    """Return one normalized policy selector without coercing arbitrary input."""

    value = params.get(key)
    return value.strip().lower() if isinstance(value, str) else ""


def run_mcp_workflow_policy_scope(params: dict[str, Any]) -> str | None:
    """Return the only permitted OAuth scope for one legacy workflow call.

    ``None`` deliberately means that the shape is unsupported and must be
    denied by the normal tool-policy layer.  This function performs no I/O and
    has no authority to dispatch a workflow.
    """

    workflow = policy_string_param(params, "workflow")
    phase = policy_string_param(params, "phase")
    docs_action = policy_string_param(params, "docs_action")
    if workflow == RESULT_ARTIFACT_WORKFLOW:
        return "mcp:read" if phase == "read" else None
    if workflow == CURRENT_FACTS_WORKFLOW:
        if phase in {"", "inspect"}:
            return "mcp:read"
        if phase == "preview":
            return "mcp:preview"
        if phase == "apply":
            return "mcp:commit"
        return None
    if workflow == STAGE_7_9_PREVIEW_WORKFLOW:
        # This workflow is intrinsically read-only.  Permit its declared
        # scope through the common policy layer even for an invalid phase so
        # the typed handler can return its precise
        # STAGE_7_9_PHASE_NOT_SUPPORTED contract rather than a generic policy
        # denial.  The handler has no mutation path and rejects every phase
        # other than inspect/preview.
        return "mcp:read"
    if workflow == GATE_REVIEW_WORKFLOW:
        if phase in {"inspect", "status"}:
            return "mcp:read"
        if phase == "preview":
            return "mcp:preview"
        if phase == "apply":
            return "mcp:commit"
        return None
    if workflow == OPERATOR_BATCH_WORKFLOW:
        if phase == "status":
            return "mcp:read"
        if phase == "preview":
            return "mcp:preview"
        if phase == "execute":
            return "mcp:commit"
        return None
    if workflow == "auto_preview":
        return "mcp:preview"
    if workflow == "project_status":
        return "mcp:read"
    if workflow == "source_onboarding":
        if phase in {"", "preview"}:
            return "mcp:preview"
        return None
    if workflow == "plan_update":
        if phase == "apply":
            return "mcp:plan"
        if phase in {"", "preview"}:
            return "mcp:preview"
        return None
    if workflow == "thin_governed_loop_preview":
        return "mcp:read"
    if workflow == "project_delivery_preview":
        return "mcp:read" if phase == "preview" else None
    if workflow == "github_delivery":
        if phase in {"pr_status", "merge_status"}:
            return "mcp:read"
        if phase == "pr_preview":
            return "mcp:preview"
        if phase == "pr_apply":
            return "mcp:commit"
        return None
    if workflow == REVIEW_MANIFEST_WORKFLOW:
        if phase in {"", "inspect", "read", "verify", "status"}:
            return "mcp:read"
        return None
    if workflow == "small_project_patch":
        if phase == "status":
            return "mcp:read"
        if phase == "preview":
            return "mcp:preview"
        if phase in {"apply", ""}:
            return "mcp:commit"
        return None
    if workflow == "docs_update":
        if docs_action in {"index", "search", "read_section"}:
            return "mcp:read" if phase in {"", "inspect"} else None
        if docs_action in {"update_section_preview", "append_section_preview", "sync_docs_preview"}:
            return "mcp:preview" if phase in {"", "preview"} else None
        if docs_action == "apply":
            return "mcp:commit"
        if phase in {"", "inspect"}:
            return "mcp:read"
        if phase == "preview":
            return "mcp:preview"
        if phase == "apply":
            return "mcp:commit"
        return None
    if workflow == "git_commit":
        if phase in {"inspect", "status"}:
            return "mcp:read"
        if phase == "preview":
            return "mcp:preview"
        if phase in {"apply", "commit", ""}:
            return "mcp:commit"
        return None
    if workflow in {"git_restore_file", "git_revert"}:
        if phase == "preview":
            return "mcp:preview"
        if phase in {"apply", ""}:
            return "mcp:commit"
        return None
    if workflow == "git_undo_version":
        if phase == "inspect":
            return "mcp:read"
        if phase == "preview":
            return "mcp:preview"
        if phase in {"apply", ""}:
            return "mcp:commit"
        return None
    if workflow == "agent_dispatch":
        if phase in {"inspect", "status"}:
            return "mcp:read"
        if phase in {"preview", "run_preview"}:
            return "mcp:preview"
        if phase in {"run", "apply", ""}:
            return "mcp:commit"
        return None
    if workflow == "prompt_to_plan":
        if phase in {"preview", "plan_preview", "run_preview"}:
            return "mcp:preview"
        if phase == "plan_apply":
            return "mcp:plan"
        if phase in {"apply", "apply_all", "run"}:
            return "mcp:commit"
        return None
    return None
