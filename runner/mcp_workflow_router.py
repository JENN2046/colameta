import os
from typing import Any, Callable

from runner.planning_bridge import PlanningBridge
from runner.mcp_plan_workflow import MCPPlanWorkflowManager
from runner.mcp_project_patch import MCPProjectPatchManager
from runner.mcp_project_docs import MCPProjectDocsManager
from runner.mcp_git_history import MCPGitHistoryManager
from runner.mcp_git_commit import MCPGitCommitManager
from runner.mcp_executor_workflow import MCPExecutorWorkflowManager
from runner.source_review_bridge import SourceReviewBridge
from runner.core_orchestrator import WorkflowOrchestrator, _GOAL_CLASSIFIERS
from runner.core_request import CoreRequest
from runner.core_output import CoreOutput


class MCPWorkflowRouter:
    def __init__(
        self,
        project_root: str,
        source_review: SourceReviewBridge | None = None,
        analyze_state_fn: Callable[[dict], dict] | None = None,
        plan_workflow_manager: MCPPlanWorkflowManager | None = None,
        project_patch_manager: MCPProjectPatchManager | None = None,
        project_docs_manager: MCPProjectDocsManager | None = None,
        git_history_manager: MCPGitHistoryManager | None = None,
        git_commit_manager: MCPGitCommitManager | None = None,
        planning_bridge: PlanningBridge | None = None,
        executor_workflow_factory: Callable[[str], MCPExecutorWorkflowManager] | None = None,
    ):
        self.project_root = os.path.abspath(os.path.expanduser(project_root))
        self._source_review = source_review or SourceReviewBridge()
        self._analyze_state_fn = analyze_state_fn
        self._plan_workflow_manager = plan_workflow_manager
        self._project_patch_manager = project_patch_manager
        self._project_docs_manager = project_docs_manager
        self._git_history_manager = git_history_manager
        self._git_commit_manager = git_commit_manager
        self._planning_bridge = planning_bridge or PlanningBridge()
        self._executor_workflow_factory = executor_workflow_factory or (
            lambda project_root: MCPExecutorWorkflowManager(project_root)
        )

    # ---- Lazy managers ----

    @property
    def plan_workflow(self) -> MCPPlanWorkflowManager:
        if self._plan_workflow_manager is None:
            self._plan_workflow_manager = MCPPlanWorkflowManager(self.project_root, self._source_review)
        return self._plan_workflow_manager

    @property
    def project_patch(self) -> MCPProjectPatchManager:
        if self._project_patch_manager is None:
            self._project_patch_manager = MCPProjectPatchManager(self.project_root, self._source_review)
        return self._project_patch_manager

    @property
    def project_docs(self) -> MCPProjectDocsManager:
        if self._project_docs_manager is None:
            from runner.mcp_project_docs import MCPProjectDocsManager
            self._project_docs_manager = MCPProjectDocsManager(self.project_root, self._source_review)
        return self._project_docs_manager

    @property
    def git_history(self) -> MCPGitHistoryManager:
        if self._git_history_manager is None:
            self._git_history_manager = MCPGitHistoryManager(self.project_root, self._source_review)
        return self._git_history_manager

    @property
    def git_commit(self) -> MCPGitCommitManager:
        if self._git_commit_manager is None:
            self._git_commit_manager = MCPGitCommitManager(self.project_root)
        return self._git_commit_manager

    # ---- Public API ----

    def handle(self, workflow: str, params: dict[str, Any]) -> dict[str, Any]:
        orchestrator = WorkflowOrchestrator(
            project_root=self.project_root,
            source_review=self._source_review,
            analyze_state_fn=self._analyze_state_fn,
            plan_workflow_manager=self._plan_workflow_manager,
            project_patch_manager=self._project_patch_manager,
            project_docs_manager=self._project_docs_manager,
            git_history_manager=self._git_history_manager,
            git_commit_manager=self._git_commit_manager,
            planning_bridge=self._planning_bridge,
            executor_workflow_factory=self._executor_workflow_factory,
        )
        payload: dict[str, Any] = {
            "intent_type": "workflow",
            "workflow": workflow,
            "params": params,
        }
        phase = params.get("phase")
        if phase:
            payload["phase"] = phase
        core_request = CoreRequest.from_tool_payload(
            payload=payload,
            entrypoint="mcp_workflow",
        )
        core_output = orchestrator.handle_request(core_request)
        return self._core_output_to_legacy_response(core_output)

    def _core_output_to_legacy_response(self, output: CoreOutput) -> dict[str, Any]:
        out: dict[str, Any] = {
            "ok": output.ok,
            "workflow": output.workflow,
            "status": output.status,
            "risk_level": output.risk_level,
            "steps": output.steps,
            "changed_files": output.changed_files,
            "preview_ids": output.preview_ids,
            "next_actions": output.next_actions,
            "requires_confirmation": output.requires_confirmation,
            "blockers": output.blockers,
            "warnings": output.warnings,
            "result": output.result,
        }
        if output.phase is not None:
            out["phase"] = output.phase
        if output.action_outcome and output.action_outcome.get("error_code"):
            out["error_code"] = output.action_outcome["error_code"]
        if output.action_outcome and output.action_outcome.get("message"):
            out["message"] = output.action_outcome["message"]
        if output.partial is not None:
            out["partial"] = output.partial
        if output.selected_workflow is not None:
            out["selected_workflow"] = output.selected_workflow
        if output.selection_reason is not None:
            out["selection_reason"] = output.selection_reason
        if output.confidence is not None:
            out["confidence"] = output.confidence
        if output.stop_reason is not None:
            out["stop_reason"] = output.stop_reason
        if output.unified_status is not None:
            out["unified_status"] = output.unified_status
        return out
