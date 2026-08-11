"""P1-A0 migration contract for the legacy ``run_mcp_workflow`` surface.

The public MCP schema still contains legacy workflow values while the Commander
surface converges on nine compact tools.  This module is the single, checked-in
map from each legacy value to its current owner, target owner, authority shape,
and compatibility destination.  It intentionally performs no routing; P1-A
extractors must update this map and its tests before moving a workflow.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from runner.core_workflow_registry import SUPPORTED_CORE_WORKFLOWS
from runner.mcp_current_facts import CURRENT_FACTS_WORKFLOW
from runner.mcp_gate_review_workflow import GATE_REVIEW_WORKFLOW
from runner.mcp_stage_7_9_preview import STAGE_7_9_PREVIEW_WORKFLOW
from runner.review_manifest import REVIEW_MANIFEST_WORKFLOW


RESULT_ARTIFACT_WORKFLOW = "result_artifact"
OPERATOR_BATCH_WORKFLOW = "operator_batch"
PROJECT_DELIVERY_PREVIEW_WORKFLOW = "project_delivery_preview"
GITHUB_DELIVERY_WORKFLOW = "github_delivery"

MigrationClassification = Literal[
    "public_typed",
    "public_compatibility",
    "local_advanced",
    "retired_with_handoff",
]

_VALID_CLASSIFICATIONS = frozenset(
    {
        "public_typed",
        "public_compatibility",
        "local_advanced",
        "retired_with_handoff",
    }
)


@dataclass(frozen=True)
class WorkflowMigrationEntry:
    """One authoritative P1-A0 disposition for a legacy workflow value."""

    workflow: str
    classification: MigrationClassification
    current_owner_module: str
    current_owner_symbol: str
    target_owner_module: str
    target_owner_symbol: str
    target_owner_status: Literal["existing", "extract"]
    public_typed_entrypoint: str | None
    local_handoff_entrypoint: str | None
    supported_phases: tuple[str, ...]
    required_fields: tuple[str, ...]
    scope_contract: tuple[str, ...]
    input_contract_id: str
    output_contract_id: str
    compatibility_status: Literal["typed_preferred", "compatibility_only", "local_only", "retired"]
    regression_tests: tuple[str, ...]


def _entry(
    workflow: str,
    classification: MigrationClassification,
    *,
    current_owner_module: str,
    current_owner_symbol: str,
    target_owner_module: str,
    target_owner_symbol: str,
    target_owner_status: Literal["existing", "extract"],
    public_typed_entrypoint: str | None,
    local_handoff_entrypoint: str | None,
    supported_phases: tuple[str, ...],
    required_fields: tuple[str, ...],
    scope_contract: tuple[str, ...],
    output_contract_id: str = "core_output_legacy_envelope.v1",
    compatibility_status: Literal["typed_preferred", "compatibility_only", "local_only", "retired"],
    regression_tests: tuple[str, ...],
) -> WorkflowMigrationEntry:
    return WorkflowMigrationEntry(
        workflow=workflow,
        classification=classification,
        current_owner_module=current_owner_module,
        current_owner_symbol=current_owner_symbol,
        target_owner_module=target_owner_module,
        target_owner_symbol=target_owner_symbol,
        target_owner_status=target_owner_status,
        public_typed_entrypoint=public_typed_entrypoint,
        local_handoff_entrypoint=local_handoff_entrypoint,
        supported_phases=supported_phases,
        required_fields=required_fields,
        scope_contract=scope_contract,
        input_contract_id=f"run_mcp_workflow/{workflow}/v1",
        output_contract_id=output_contract_id,
        compatibility_status=compatibility_status,
        regression_tests=regression_tests,
    )


WORKFLOW_MIGRATION_MAP: dict[str, WorkflowMigrationEntry] = {
    "auto_preview": _entry(
        "auto_preview",
        "public_compatibility",
        current_owner_module="runner.core_orchestrator",
        current_owner_symbol="WorkflowOrchestrator._workflow_auto_preview",
        target_owner_module="runner.mcp_auto_preview",
        target_owner_symbol="MCPAutoPreviewWorkflow",
        target_owner_status="extract",
        public_typed_entrypoint=None,
        local_handoff_entrypoint=None,
        supported_phases=("preview",),
        required_fields=("workflow",),
        scope_contract=("default:mcp:preview",),
        compatibility_status="compatibility_only",
        regression_tests=("tests/test_core_orchestrator_auto_preview_intent.py",),
    ),
    "project_status": _entry(
        "project_status",
        "public_typed",
        current_owner_module="runner.core_orchestrator",
        current_owner_symbol="WorkflowOrchestrator._workflow_project_status",
        target_owner_module="runner.mcp_project_state",
        target_owner_symbol="MCPProjectStateWorkflow",
        target_owner_status="extract",
        public_typed_entrypoint="analyze_project_state",
        local_handoff_entrypoint=None,
        supported_phases=("inspect", "status"),
        required_fields=("workflow",),
        scope_contract=("inspect:mcp:read", "status:mcp:read"),
        compatibility_status="typed_preferred",
        regression_tests=("tests/test_canonical_project_state.py", "tests/test_mcp_operation_context_binding.py"),
    ),
    "source_onboarding": _entry(
        "source_onboarding",
        "local_advanced",
        current_owner_module="runner.core_orchestrator",
        current_owner_symbol="WorkflowOrchestrator._workflow_source_onboarding",
        target_owner_module="runner.mcp_runner_plan",
        target_owner_symbol="MCPRunnerPlanManager",
        target_owner_status="existing",
        public_typed_entrypoint=None,
        local_handoff_entrypoint="manage_runner_plan",
        supported_phases=("preview",),
        required_fields=("workflow", "goal"),
        scope_contract=("preview:mcp:preview",),
        compatibility_status="local_only",
        regression_tests=("tests/test_runner_cli.py", "tests/test_mcp_runtime_observability.py"),
    ),
    "plan_update": _entry(
        "plan_update",
        "local_advanced",
        current_owner_module="runner.core_orchestrator",
        current_owner_symbol="WorkflowOrchestrator._workflow_plan_update",
        target_owner_module="runner.mcp_plan_workflow",
        target_owner_symbol="MCPPlanWorkflowManager",
        target_owner_status="existing",
        public_typed_entrypoint=None,
        local_handoff_entrypoint="manage_plan_version",
        supported_phases=("preview", "apply"),
        required_fields=("workflow", "mode"),
        scope_contract=("preview:mcp:preview", "apply:mcp:plan"),
        compatibility_status="local_only",
        regression_tests=("tests/test_mcp_operation_context_binding.py", "tests/test_runner_cli.py"),
    ),
    "small_project_patch": _entry(
        "small_project_patch",
        "local_advanced",
        current_owner_module="runner.core_orchestrator",
        current_owner_symbol="WorkflowOrchestrator._workflow_small_project_patch",
        target_owner_module="runner.mcp_project_patch",
        target_owner_symbol="MCPProjectPatchManager",
        target_owner_status="existing",
        public_typed_entrypoint=None,
        local_handoff_entrypoint="manage_project_patch",
        supported_phases=("status", "preview", "apply"),
        required_fields=("workflow", "file"),
        scope_contract=("status:mcp:read", "preview:mcp:preview", "apply:mcp:commit"),
        compatibility_status="local_only",
        regression_tests=("tests/test_mcp_operation_context_binding.py", "tests/test_mcp_project_patch_transaction.py"),
    ),
    "docs_update": _entry(
        "docs_update",
        "public_compatibility",
        current_owner_module="runner.core_orchestrator",
        current_owner_symbol="WorkflowOrchestrator._workflow_docs_update",
        target_owner_module="runner.mcp_project_docs",
        target_owner_symbol="MCPProjectDocsManager",
        target_owner_status="existing",
        public_typed_entrypoint=None,
        local_handoff_entrypoint="manage_project_docs",
        supported_phases=("inspect", "preview", "apply"),
        required_fields=("workflow", "docs_action"),
        scope_contract=("inspect:mcp:read", "preview:mcp:preview", "apply:mcp:commit"),
        compatibility_status="compatibility_only",
        regression_tests=("tests/test_mcp_operation_context_binding.py",),
    ),
    "git_commit": _entry(
        "git_commit",
        "public_typed",
        current_owner_module="runner.core_orchestrator",
        current_owner_symbol="WorkflowOrchestrator._workflow_git_commit",
        target_owner_module="runner.mcp_git_commit",
        target_owner_symbol="MCPGitCommitManager",
        target_owner_status="existing",
        public_typed_entrypoint="manage_git",
        local_handoff_entrypoint="manage_git",
        supported_phases=("inspect", "status", "preview", "commit"),
        required_fields=("workflow",),
        scope_contract=("inspect:mcp:read", "status:mcp:read", "preview:mcp:preview", "commit:mcp:commit"),
        compatibility_status="typed_preferred",
        regression_tests=("tests/test_mcp_operation_context_binding.py", "tests/test_mcp_git_commit_infrastructure_paths.py"),
    ),
    "git_restore_file": _entry(
        "git_restore_file",
        "public_typed",
        current_owner_module="runner.core_orchestrator",
        current_owner_symbol="WorkflowOrchestrator._workflow_git_restore_file",
        target_owner_module="runner.mcp_git_history",
        target_owner_symbol="MCPGitHistoryManager",
        target_owner_status="existing",
        public_typed_entrypoint="manage_git",
        local_handoff_entrypoint="manage_git",
        supported_phases=("preview", "apply"),
        required_fields=("workflow", "commit", "file"),
        scope_contract=("preview:mcp:preview", "apply:mcp:commit"),
        compatibility_status="typed_preferred",
        regression_tests=("tests/test_mcp_operation_context_binding.py", "tests/test_mcp_runtime_observability.py"),
    ),
    "git_revert": _entry(
        "git_revert",
        "public_typed",
        current_owner_module="runner.core_orchestrator",
        current_owner_symbol="WorkflowOrchestrator._workflow_git_revert",
        target_owner_module="runner.mcp_git_history",
        target_owner_symbol="MCPGitHistoryManager",
        target_owner_status="existing",
        public_typed_entrypoint="manage_git",
        local_handoff_entrypoint="manage_git",
        supported_phases=("preview", "apply"),
        required_fields=("workflow", "commit"),
        scope_contract=("preview:mcp:preview", "apply:mcp:commit"),
        compatibility_status="typed_preferred",
        regression_tests=("tests/test_mcp_operation_context_binding.py", "tests/test_mcp_runtime_observability.py"),
    ),
    "git_undo_version": _entry(
        "git_undo_version",
        "local_advanced",
        current_owner_module="runner.core_orchestrator",
        current_owner_symbol="WorkflowOrchestrator._workflow_git_undo_version",
        target_owner_module="runner.mcp_git_history",
        target_owner_symbol="MCPGitHistoryManager",
        target_owner_status="existing",
        public_typed_entrypoint=None,
        local_handoff_entrypoint="manage_git",
        supported_phases=("inspect", "preview", "apply"),
        required_fields=("workflow",),
        scope_contract=("inspect:mcp:read", "preview:mcp:preview", "apply:mcp:commit"),
        compatibility_status="local_only",
        regression_tests=("tests/test_mcp_operation_context_binding.py", "tests/test_mcp_runtime_observability.py"),
    ),
    "agent_dispatch": _entry(
        "agent_dispatch",
        "local_advanced",
        current_owner_module="runner.core_orchestrator",
        current_owner_symbol="WorkflowOrchestrator._workflow_agent_dispatch",
        target_owner_module="runner.mcp_executor_workflow",
        target_owner_symbol="MCPExecutorWorkflowManager",
        target_owner_status="existing",
        public_typed_entrypoint=None,
        local_handoff_entrypoint="manage_executor_workflow",
        supported_phases=("inspect", "status", "preview", "apply", "run_preview", "run"),
        required_fields=("workflow",),
        scope_contract=("inspect:mcp:read", "status:mcp:read", "preview:mcp:preview", "run_preview:mcp:preview", "apply:mcp:commit", "run:mcp:commit"),
        compatibility_status="local_only",
        regression_tests=("tests/test_mcp_operation_context_binding.py", "tests/test_executor_session_head_mismatch.py"),
    ),
    "prompt_to_plan": _entry(
        "prompt_to_plan",
        "local_advanced",
        current_owner_module="runner.core_orchestrator",
        current_owner_symbol="WorkflowOrchestrator._workflow_prompt_to_plan",
        target_owner_module="runner.mcp_prompt_to_plan",
        target_owner_symbol="MCPPromptToPlanWorkflow",
        target_owner_status="extract",
        public_typed_entrypoint=None,
        local_handoff_entrypoint="manage_prompt_file",
        supported_phases=("preview", "apply", "plan_preview", "plan_apply", "apply_all", "run_preview", "run"),
        required_fields=("workflow",),
        scope_contract=("preview:mcp:preview", "plan_preview:mcp:preview", "run_preview:mcp:preview", "plan_apply:mcp:plan", "apply:mcp:commit", "apply_all:mcp:commit", "run:mcp:commit"),
        compatibility_status="local_only",
        regression_tests=("tests/test_mcp_operation_context_binding.py", "tests/test_mcp_runtime_observability.py"),
    ),
    "thin_governed_loop_preview": _entry(
        "thin_governed_loop_preview",
        "public_compatibility",
        current_owner_module="runner.core_orchestrator",
        current_owner_symbol="WorkflowOrchestrator._workflow_thin_governed_loop_preview",
        target_owner_module="runner.mcp_thin_governed_loop",
        target_owner_symbol="MCPThinGovernedLoopPreview",
        target_owner_status="extract",
        public_typed_entrypoint=None,
        local_handoff_entrypoint=None,
        supported_phases=("inspect", "status", "preview"),
        required_fields=("workflow",),
        scope_contract=("inspect:mcp:read", "status:mcp:read", "preview:mcp:read"),
        compatibility_status="compatibility_only",
        regression_tests=("tests/test_thin_governed_loop.py", "tests/test_mcp_operation_context_binding.py"),
    ),
    PROJECT_DELIVERY_PREVIEW_WORKFLOW: _entry(
        PROJECT_DELIVERY_PREVIEW_WORKFLOW,
        "public_compatibility",
        current_owner_module="runner.mcp_server",
        current_owner_symbol="MCPPlanningBridgeServer._project_delivery_preview",
        target_owner_module="runner.mcp_server",
        target_owner_symbol="MCPPlanningBridgeServer._project_delivery_preview",
        target_owner_status="existing",
        public_typed_entrypoint=None,
        local_handoff_entrypoint=None,
        supported_phases=("preview",),
        required_fields=("workflow", "phase", "project_name", "thin_loop_id"),
        scope_contract=("preview:mcp:read",),
        compatibility_status="compatibility_only",
        regression_tests=("tests/test_commander_public_contract_integration.py",),
    ),
    GITHUB_DELIVERY_WORKFLOW: _entry(
        GITHUB_DELIVERY_WORKFLOW,
        "public_compatibility",
        current_owner_module="runner.mcp_server",
        current_owner_symbol="MCPPlanningBridgeServer._github_delivery",
        target_owner_module="runner.mcp_github_delivery",
        target_owner_symbol="MCPGitHubDeliveryManager",
        target_owner_status="existing",
        public_typed_entrypoint=None,
        local_handoff_entrypoint=None,
        supported_phases=(
            "pr_status",
            "pr_preview",
            "pr_apply",
            "merge_status",
        ),
        required_fields=("workflow", "phase", "project_name"),
        scope_contract=(
            "pr_status:mcp:read",
            "pr_preview:mcp:preview",
            "pr_apply:mcp:commit",
            "merge_status:mcp:read",
        ),
        compatibility_status="compatibility_only",
        regression_tests=(
            "tests/test_mcp_github_delivery.py",
            "tests/test_commander_public_contract_integration.py",
        ),
    ),
    CURRENT_FACTS_WORKFLOW: _entry(
        CURRENT_FACTS_WORKFLOW,
        "public_compatibility",
        current_owner_module="runner.mcp_workflow_compatibility",
        current_owner_symbol="MCPWorkflowCompatibilityService.handle_current_facts",
        target_owner_module="runner.mcp_current_facts",
        target_owner_symbol="MCPCurrentFactsWorkflow",
        target_owner_status="existing",
        public_typed_entrypoint=None,
        local_handoff_entrypoint=None,
        supported_phases=("inspect", "preview", "apply"),
        required_fields=("workflow", "phase"),
        scope_contract=("inspect:mcp:read", "preview:mcp:preview", "apply:mcp:commit"),
        output_contract_id="current_facts_artifact.v1",
        compatibility_status="compatibility_only",
        regression_tests=("tests/test_current_facts_artifact.py", "tests/test_mcp_current_facts.py"),
    ),
    STAGE_7_9_PREVIEW_WORKFLOW: _entry(
        STAGE_7_9_PREVIEW_WORKFLOW,
        "public_compatibility",
        current_owner_module="runner.mcp_workflow_compatibility",
        current_owner_symbol="MCPWorkflowCompatibilityService.handle_stage_7_9_preview",
        target_owner_module="runner.mcp_stage_7_9_preview",
        target_owner_symbol="MCPStage79PreviewWorkflow",
        target_owner_status="existing",
        public_typed_entrypoint=None,
        local_handoff_entrypoint=None,
        supported_phases=("inspect", "preview"),
        required_fields=("workflow", "phase"),
        scope_contract=("inspect:mcp:read", "preview:mcp:read"),
        output_contract_id="stage_7_9_preview.v1",
        compatibility_status="compatibility_only",
        regression_tests=("tests/test_mcp_stage_7_9_preview.py",),
    ),
    REVIEW_MANIFEST_WORKFLOW: _entry(
        REVIEW_MANIFEST_WORKFLOW,
        "public_typed",
        current_owner_module="runner.mcp_workflow_compatibility",
        current_owner_symbol="MCPWorkflowCompatibilityService.handle_review_manifest",
        target_owner_module="runner.mcp_review_manifest",
        target_owner_symbol="MCPReviewManifestWorkflow",
        target_owner_status="existing",
        public_typed_entrypoint="review_manifest",
        local_handoff_entrypoint="review_manifest",
        supported_phases=("inspect", "read", "verify", "status"),
        required_fields=("workflow", "phase"),
        scope_contract=("inspect:mcp:read", "read:mcp:read", "verify:mcp:read", "status:mcp:read"),
        output_contract_id="review_manifest_read_contract.v1",
        compatibility_status="typed_preferred",
        regression_tests=("tests/test_mcp_review_manifest.py",),
    ),
    RESULT_ARTIFACT_WORKFLOW: _entry(
        RESULT_ARTIFACT_WORKFLOW,
        "public_typed",
        current_owner_module="runner.mcp_workflow_compatibility",
        current_owner_symbol="MCPWorkflowCompatibilityService.handle_result_artifact",
        target_owner_module="runner.mcp_resources",
        target_owner_symbol="MCPResourcesService",
        target_owner_status="existing",
        public_typed_entrypoint="read_result_artifact",
        local_handoff_entrypoint="read_result_artifact",
        supported_phases=("read",),
        required_fields=("workflow", "phase", "artifact_id"),
        scope_contract=("read:mcp:read",),
        output_contract_id="result_artifact_page.v1",
        compatibility_status="typed_preferred",
        regression_tests=("tests/test_mcp_result_artifacts.py", "tests/test_mcp_resources.py"),
    ),
    GATE_REVIEW_WORKFLOW: _entry(
        GATE_REVIEW_WORKFLOW,
        "local_advanced",
        current_owner_module="runner.mcp_workflow_compatibility",
        current_owner_symbol="MCPWorkflowCompatibilityService.handle_gate_review",
        target_owner_module="runner.mcp_gate_review_workflow",
        target_owner_symbol="MCPGateReviewWorkflow",
        target_owner_status="existing",
        public_typed_entrypoint=None,
        local_handoff_entrypoint="manage_work_item",
        supported_phases=("inspect", "status", "preview", "apply"),
        required_fields=("workflow", "phase"),
        scope_contract=("inspect:mcp:read", "status:mcp:read", "preview:mcp:preview", "apply:mcp:commit"),
        compatibility_status="local_only",
        regression_tests=("tests/test_mcp_gate_review_workflow.py",),
    ),
    OPERATOR_BATCH_WORKFLOW: _entry(
        OPERATOR_BATCH_WORKFLOW,
        "local_advanced",
        current_owner_module="runner.mcp_workflow_compatibility",
        current_owner_symbol="MCPWorkflowCompatibilityService.handle_operator_batch",
        target_owner_module="runner.mcp_private_operator",
        target_owner_symbol="OperatorBatchService",
        target_owner_status="existing",
        public_typed_entrypoint=None,
        local_handoff_entrypoint="private_operator_ipc",
        supported_phases=("status", "preview", "execute"),
        required_fields=("workflow", "phase", "project_name"),
        scope_contract=("status:mcp:read", "preview:mcp:preview", "execute:mcp:commit"),
        compatibility_status="local_only",
        regression_tests=("tests/test_mcp_private_operator.py",),
    ),
}


def declared_run_mcp_workflows() -> frozenset[str]:
    """Return the complete workflow set that P1-A0 must classify."""

    return frozenset(
        {
            *SUPPORTED_CORE_WORKFLOWS,
            CURRENT_FACTS_WORKFLOW,
            STAGE_7_9_PREVIEW_WORKFLOW,
            REVIEW_MANIFEST_WORKFLOW,
            RESULT_ARTIFACT_WORKFLOW,
            GATE_REVIEW_WORKFLOW,
            OPERATOR_BATCH_WORKFLOW,
            PROJECT_DELIVERY_PREVIEW_WORKFLOW,
            GITHUB_DELIVERY_WORKFLOW,
        }
    )


def validate_workflow_migration_map() -> tuple[str, ...]:
    """Return deterministic P1-A0 contract errors without mutating state."""

    errors: list[str] = []
    declared = declared_run_mcp_workflows()
    mapped = frozenset(WORKFLOW_MIGRATION_MAP)
    missing = sorted(declared - mapped)
    unexpected = sorted(mapped - declared)
    if missing:
        errors.append(f"missing workflows: {', '.join(missing)}")
    if unexpected:
        errors.append(f"unexpected workflows: {', '.join(unexpected)}")

    for workflow in sorted(mapped):
        entry = WORKFLOW_MIGRATION_MAP[workflow]
        if entry.workflow != workflow:
            errors.append(f"{workflow}: entry workflow mismatch")
        if entry.classification not in _VALID_CLASSIFICATIONS:
            errors.append(f"{workflow}: invalid classification")
        if not entry.current_owner_module or not entry.current_owner_symbol:
            errors.append(f"{workflow}: current owner is required")
        if not entry.target_owner_module or not entry.target_owner_symbol:
            errors.append(f"{workflow}: target owner is required")
        if entry.target_owner_status not in {"existing", "extract"}:
            errors.append(f"{workflow}: invalid target owner status")
        if not entry.supported_phases or not entry.scope_contract:
            errors.append(f"{workflow}: phase and scope contracts are required")
        if not entry.input_contract_id or not entry.output_contract_id:
            errors.append(f"{workflow}: input/output contracts are required")
        if not entry.regression_tests:
            errors.append(f"{workflow}: regression test entry is required")
        if entry.classification == "public_typed" and not entry.public_typed_entrypoint:
            errors.append(f"{workflow}: public typed entrypoint is required")
        if entry.classification in {"local_advanced", "retired_with_handoff"} and not entry.local_handoff_entrypoint:
            errors.append(f"{workflow}: local handoff is required")
    return tuple(errors)
