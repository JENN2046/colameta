import os
import re
import uuid
import json
from typing import Any, Callable

from runner.planning_bridge import PlanningBridge, PlanningBridgeError
from runner.mcp_plan_workflow import MCPPlanWorkflowManager
from runner.mcp_project_patch import MCPProjectPatchManager
from runner.mcp_project_docs import MCPProjectDocsManager
from runner.mcp_git_history import MCPGitHistoryManager
from runner.mcp_git_commit import MCPGitCommitManager
from runner.mcp_executor_workflow import MCPExecutorWorkflowManager
from runner.plan_patch_workflow import PlanPatchAutoApplyService
from runner.source_review_bridge import SourceReviewBridge
from runner.executor_session import ExecutorSessionStore
from runner.continuation_snapshot import (
    ContinuationSnapshot,
    collect_continuation_snapshot,
    get_or_collect_continuation_snapshot,
    snapshot_from_fact_bundle,
)
from runner.executor_run_reports import ExecutorRunReportStore
from runner.mcp_runner_plan import MCPRunnerPlanManager
from runner.project_identity import build_project_identity
from runner.core_fact_snapshot import CoreFactSnapshot
from runner.project_snapshot import ProjectSnapshotBuilder
from runner.core_output import CoreOutput
from runner.core_request import CoreRequest
from runner.core_result import CoreResult
from runner.core_result_facts import (
    normalize_fact_snapshot_facts,
    normalize_result_facts,
)
from runner.core_workflow_registry import SUPPORTED_CORE_WORKFLOWS
from runner.runner_status import create_status_from_normalized_result
from runner.runner_data_layout import classify_runner_path
from runner.runner_paths import resolve_project_runner_path

_GOAL_CLASSIFIERS: list[tuple[set[str], str]] = [
    ({"docs", "文档", "readme", "agents", "markdown", "section", "heading",
      "同步", "sync", "追加", "append"}, "docs"),
    ({"plan", "repair", "extend", "修复", "扩展", "版本", "version"}, "plan"),
    ({"commit", "提交", "stage"}, "git_commit"),
    ({"executor", "codex", "opencode", "pi", "continuation",
      "resume", "执行器", "exec"}, "executor"),
    ({"patch", "edit", "修改"}, "small_project_patch"),
]

_STOP_NEEDS_PLAN_APPLY_CONFIRMATION = "needs_plan_apply_confirmation"
_STOP_NEEDS_COMMIT_CONFIRMATION = "needs_commit_confirmation"
_STOP_NEEDS_DOCS_APPLY_CONFIRMATION = "needs_docs_apply_confirmation"
_STOP_NEEDS_PATCH_APPLY_CONFIRMATION = "needs_patch_apply_confirmation"
_STOP_NEEDS_MORE_INPUT = "needs_more_input"
_STOP_STATUS_ONLY_NO_GOAL = "status_only_no_goal"
_STOP_EXECUTOR_PREFLIGHT = "executor_preflight"
_STOP_GOAL_UNCLASSIFIED = "goal_unclassified"


STEP_RISK_INFO = "info"
STEP_RISK_PREVIEW = "preview"
STEP_RISK_WRITE = "write"
STEP_RISK_COMMIT = "commit"
STEP_RISK_BLOCKED = "blocked"




class WorkflowOrchestrator:
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
        continuation_snapshot: ContinuationSnapshot | None = None,
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
        self._continuation_snapshot = continuation_snapshot

        self._runner_plan_manager: MCPRunnerPlanManager | None = None
        self._executor_run_report_store: ExecutorRunReportStore | None = None

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

    @property
    def runner_plan_manager(self) -> MCPRunnerPlanManager:
        if self._runner_plan_manager is None:
            self._runner_plan_manager = MCPRunnerPlanManager(self.project_root)
        return self._runner_plan_manager

    @property
    def executor_run_report_store(self) -> ExecutorRunReportStore:
        if self._executor_run_report_store is None:
            self._executor_run_report_store = ExecutorRunReportStore(self.project_root)
        return self._executor_run_report_store

    # ---- Public API ----

    def handle(self, workflow: str, params: dict[str, Any]) -> 'CoreOutput':
        workflow_map: dict[str, Callable[[dict[str, Any]], Any]] = {
            "auto_preview": self._workflow_auto_preview,
            "project_status": self._workflow_project_status,
            "source_onboarding": self._workflow_source_onboarding,
            "plan_update": self._workflow_plan_update,
            "small_project_patch": self._workflow_small_project_patch,
            "docs_update": self._workflow_docs_update,
            "git_commit": self._workflow_git_commit,
            "git_restore_file": self._workflow_git_restore_file,
            "git_revert": self._workflow_git_revert,
            "git_undo_version": self._workflow_git_undo_version,
            "agent_dispatch": self._workflow_agent_dispatch,
            "prompt_to_plan": self._workflow_prompt_to_plan,
            "thin_governed_loop_preview": self._workflow_thin_governed_loop_preview,
        }
        handler = workflow_map.get(workflow)
        if handler is None:
            return self._build_error_output(
                workflow, "UNKNOWN_WORKFLOW",
                f"未知 workflow：{workflow}。支持：{', '.join(sorted(SUPPORTED_CORE_WORKFLOWS))}",
            )
        core_result = handler(params)
        return self._build_core_output(core_result, fact_snapshot=core_result.fact_snapshot)

    def handle_request(self, core_request: CoreRequest) -> CoreOutput:
        intent = core_request.intent_type
        target = core_request.target_scope or {}
        params: dict[str, Any] = dict(target.get("params") or {})

        if intent in ("query", "inspect"):
            return self.handle("project_status", {"include_reports": True})

        if intent == "workflow":
            workflow = target.get("workflow") or params.get("workflow") or "project_status"
            phase = target.get("phase") or params.get("phase")
            if phase:
                params["phase"] = phase
            return self.handle(workflow, params)

        if intent == "preview":
            if "workflow" in target:
                workflow = target["workflow"]
                if "phase" not in params:
                    params["phase"] = "preview"
                return self.handle(workflow, params)
            workflow = target.get("params", {}).get("workflow") or "auto_preview"
            if "phase" not in params:
                params["phase"] = "preview"
            return self.handle(workflow, params)

        return self._build_request_error_output(
            f"不支持的 intent_type：{intent}。支持：query、inspect、preview、workflow。",
            error_code="INTENT_NOT_SUPPORTED",
        )

    def _build_request_error_output(
        self,
        message: str,
        error_code: str = "REQUEST_REJECTED",
    ) -> CoreOutput:
        return CoreOutput(
            ok=False,
            source="core",
            action="handle_request",
            status="blocked",
            risk_level="blocked",
            action_outcome={
                "code": "FAILED",
                "message": message,
                "error_code": error_code,
            },
            blockers=[message],
            display_summary={
                "title": "请求被拒绝",
                "status_text": "blocked",
                "primary_message": message,
                "next_step_text": "",
                "detail_refs": [],
            },
            audit={
                "source": "core",
                "workflow": "handle_request",
                "phase": None,
            },
        )

    def _build_core_output(
        self,
        core_result: CoreResult,
        fact_snapshot: CoreFactSnapshot | None = None,
        source: str = "workflow",
        action: str = "run_workflow",
    ) -> CoreOutput:
        result_facts = normalize_result_facts(core_result)
        unified_status = create_status_from_normalized_result(
            workflow=core_result.workflow,
            status=core_result.status,
            risk_level=core_result.risk_level,
            requires_confirmation=result_facts.requires_confirmation,
            blockers=result_facts.blockers,
            warnings=result_facts.warnings,
            preview_ids=core_result.preview_ids,
            result=core_result.result,
        ).to_dict()

        out = CoreOutput(
            ok=core_result.ok,
            source=source,
            action=action,
            workflow=core_result.workflow,
            phase=core_result.phase,
            status=core_result.status,
            risk_level=core_result.risk_level,
            fact_snapshot=fact_snapshot,
            action_outcome={
                "code": "SUCCESS" if core_result.ok else "FAILED",
                "message": core_result.message or "",
            },
            result=core_result.result,
            steps=list(core_result.steps),
            changed_files=list(core_result.changed_files),
            preview_ids=list(core_result.preview_ids),
            next_actions=list(result_facts.recommended_next_actions),
            requires_confirmation=result_facts.requires_confirmation,
            confirmation=result_facts.confirmation,
            blockers=list(result_facts.blockers),
            warnings=list(result_facts.warnings),
            partial=core_result.partial,
            selected_workflow=core_result.selected_workflow,
            selection_reason=core_result.selection_reason,
            confidence=core_result.confidence,
            stop_reason=core_result.stop_reason,
            unified_status=unified_status,
            display_summary=self._build_display_summary(core_result),
            audit={
                "source": source,
                "workflow": core_result.workflow,
                "phase": core_result.phase,
            },
        )
        if core_result.error_code is not None:
            out.action_outcome["error_code"] = core_result.error_code
        return out

    def _build_display_summary(self, core_result: CoreResult) -> dict[str, Any]:
        status_text = core_result.status
        if status_text == "failed":
            title = "操作失败"
            primary = core_result.message or "操作执行失败。"
        elif status_text == "preview_ready":
            title = "预览就绪"
            primary = "预览已生成，请确认后继续。"
        elif status_text == "succeeded":
            title = "操作成功"
            primary = "操作执行成功。"
        else:
            title = status_text
            primary = ""

        next_step = ""
        if core_result.next_actions:
            next_step = core_result.next_actions[0].get("label", "")

        return {
            "title": title,
            "status_text": status_text,
            "primary_message": primary,
            "next_step_text": next_step,
            "detail_refs": [],
        }

    def _build_error_output(
        self,
        workflow: str,
        error_code: str,
        message: str,
    ) -> CoreOutput:
        core_result = self._error_result(workflow, error_code, message)
        return self._build_core_output(core_result)

    def _build_analyze_core_output(
        self,
        fact_snapshot: CoreFactSnapshot,
    ) -> CoreOutput:
        legacy_result = self._fact_snapshot_to_analyze_legacy(fact_snapshot)
        result_facts = normalize_fact_snapshot_facts(fact_snapshot)
        unified_status = create_status_from_normalized_result(
            workflow="analyze_project_state",
            status="succeeded",
            risk_level=fact_snapshot.risk_level or "info",
            requires_confirmation=result_facts.requires_confirmation,
            blockers=result_facts.blockers,
            warnings=result_facts.warnings,
            preview_ids=[],
            result=legacy_result,
        ).to_dict()

        next_actions = list(result_facts.recommended_next_actions)

        return CoreOutput(
            ok=True,
            source="mcp",
            action="analyze_project_state",
            workflow="analyze_project_state",
            status="succeeded",
            risk_level=fact_snapshot.risk_level or "info",
            fact_snapshot=fact_snapshot,
            action_outcome={
                "code": "SUCCESS",
                "message": "项目状态分析完成。",
            },
            result=legacy_result,
            next_actions=next_actions,
            requires_confirmation=result_facts.requires_confirmation,
            confirmation=result_facts.confirmation,
            blockers=list(result_facts.blockers),
            warnings=list(result_facts.warnings),
            unified_status=unified_status,
            display_summary=self._build_analyze_display_summary(legacy_result, next_actions),
            audit={
                "source": "mcp",
                "workflow": "analyze_project_state",
                "phase": "analyze",
            },
        )

    def _build_analyze_display_summary(
        self,
        legacy_result: dict[str, Any],
        next_actions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        next_text = (legacy_result.get("summary") or {}).get("recommended_primary_action", "")
        if not next_text and next_actions:
            next_text = next_actions[0].get("label", "")
        return {
            "title": "分析完成",
            "status_text": "succeeded",
            "primary_message": "项目状态分析完成。",
            "next_step_text": next_text,
            "detail_refs": [],
        }

    # ================================================================
    # project_status
    # ================================================================

    def _workflow_project_status(self, params: dict[str, Any]) -> dict[str, Any]:
        phase = params.get("phase", "inspect")
        if phase != "inspect":
            return self._error_result("project_status", "PHASE_NOT_SUPPORTED",
                                      "project_status 只支持 phase=inspect。")

        provider_raw = params.get("provider")
        provider: str | None = None
        if provider_raw is not None:
            if isinstance(provider_raw, str) and provider_raw.strip().lower() in {"pi", "codex", "opencode"}:
                provider = provider_raw.strip().lower()

        include_reports = self._bool_param(params.get("include_reports"), default=True)

        fact_snapshot = self.build_fact_snapshot(provider=provider, include_reports=include_reports)

        legacy_result = self._fact_snapshot_to_analyze_legacy(fact_snapshot)
        steps = [self._step("project_status", "analyze_project_state", "analyze", legacy_result, STEP_RISK_INFO)]

        next_actions = list(fact_snapshot.recommended_next_actions)

        result = self._build_core_result(
            workflow="project_status",
            steps=steps,
            risk_level=STEP_RISK_INFO,
            status="succeeded" if legacy_result.get("ok") else "failed",
            requires_confirmation=False,
            next_actions=next_actions,
            result=legacy_result,
        )
        result.fact_snapshot = fact_snapshot
        return result

    # ================================================================
    # Core fact snapshot
    # ================================================================

    def build_fact_snapshot(
        self,
        provider: str | None = None,
        include_reports: bool = True,
        continuation_fact_bundle: dict[str, Any] | None = None,
        continuation_snapshot: ContinuationSnapshot | None = None,
    ) -> CoreFactSnapshot:
        captured = continuation_snapshot or self._continuation_snapshot
        if captured is None and continuation_fact_bundle is not None:
            captured = snapshot_from_fact_bundle(self.project_root, continuation_fact_bundle)
        if captured is None:
            captured = collect_continuation_snapshot(
                self.project_root,
                requested_provider=provider,
                planning_bridge=self._planning_bridge,
                source_review=self._source_review,
            )
        if self._continuation_snapshot is None:
            self._continuation_snapshot = captured
        snapshot = ProjectSnapshotBuilder(
            self.project_root,
            source_review=self._source_review,
            planning_bridge=self._planning_bridge,
            runner_plan_manager=self.runner_plan_manager,
            executor_run_report_store=self.executor_run_report_store,
        ).build(
            provider=provider,
            include_reports=include_reports,
            continuation_snapshot=captured,
        )
        project_identity = snapshot.project_identity
        mode = snapshot.mode
        git = dict(snapshot.git)
        working_tree_clean = snapshot.working_tree_clean
        plan_status = dict(snapshot.plan_status)
        runner = dict(snapshot.runner)
        executor = dict(snapshot.executor)
        reports = dict(snapshot.reports)
        partial_errors = list(snapshot.partial_errors)

        # ProjectSnapshotBuilder owns the single canonical decision read for
        # this snapshot.  Analyze only projects that exact object.
        canonical_continuation_decision = executor.get("canonical_continuation_decision")
        if isinstance(canonical_continuation_decision, dict):
            executor["canonical_continuation_decision"] = canonical_continuation_decision
            executor["continuation_available"] = bool(
                canonical_continuation_decision.get("resume_allowed") is True
            )
            executor["decision"] = canonical_continuation_decision.get("decision")
            executor["should_resume"] = bool(
                canonical_continuation_decision.get("resume_allowed") is True
            )
            executor["should_start_new"] = bool(
                canonical_continuation_decision.get("start_new_allowed") is True
                and canonical_continuation_decision.get("recommended_action") == "start_new"
            )
            executor["manual_confirmation_required"] = bool(
                canonical_continuation_decision.get("recommended_action") == "human_review"
            )

        plan_blockers = list(plan_status.get("blockers", []))
        plan_warnings = list(plan_status.get("warnings", []))
        lint_blocking_issue_count = int(plan_status.get("lint_blocking_issue_count", 0) or 0)
        risk_level = self._determine_risk_level(mode, plan_blockers, executor)
        summary = self._summarize_analyzed_state(
            mode,
            snapshot.has_plan,
            snapshot.has_state,
            working_tree_clean,
            runner,
            executor,
            plan=plan_status,
        )

        pending_warnings = self._build_pending_queue_warnings(
            pending_versions=runner.get("pending_versions", []),
            pending_count=int(runner.get("pending_count", 0) or 0),
            next_not_started_version=runner.get("next_not_started_version"),
        )
        direct_version_warnings = self._build_unreconciled_direct_warnings(
            direct_versions=runner.get("unreconciled_direct_versions", []),
            count=int(runner.get("unreconciled_direct_version_count", 0) or 0),
        )
        recommended_next_actions = self._recommend_next_actions(mode, git, plan_status, runner, executor, working_tree_clean, reports)

        core_can_commit = (
            working_tree_clean is False
            and not plan_blockers
            and lint_blocking_issue_count == 0
        )

        return CoreFactSnapshot(
            project_identity=project_identity,
            current_version=str(runner.get("current_version") or "") if runner.get("current_version") else None,
            next_version=str(runner.get("next_version") or "") if runner.get("next_version") else None,
            plan_status=plan_status,
            git_status=git,
            active_preview=None,
            active_run={
                "has_session": executor.get("has_session", False),
                "continuation_available": executor.get("continuation_available", False),
                "decision": executor.get("decision"),
                "should_resume": executor.get("should_resume", False),
                "should_start_new": executor.get("should_start_new", True),
                "canonical_continuation_decision": executor.get(
                    "canonical_continuation_decision"
                ),
            },
            latest_report=reports,
            can_continue=bool(runner.get("has_pending_versions") or executor.get("continuation_available")),
            can_commit=core_can_commit,
            requires_confirmation=bool(executor.get("manual_confirmation_required", False)),
            recommended_next_actions=recommended_next_actions,
            blockers=plan_blockers,
            warnings=(plan_warnings + pending_warnings + direct_version_warnings)[:20],
            risk_level=risk_level,
            mode=mode,
            summary=summary,
            unreconciled_direct_version_count=int(runner.get("unreconciled_direct_version_count", 0) or 0),
            unreconciled_direct_versions=runner.get("unreconciled_direct_versions", []),
            has_pending_versions=bool(runner.get("has_pending_versions")),
            pending_versions=runner.get("pending_versions", []),
            pending_count=int(runner.get("pending_count", 0) or 0),
            next_not_started_version=str(runner.get("next_not_started_version") or "") if runner.get("next_not_started_version") else None,
            partial_errors=partial_errors,
            _runner_raw=runner,
            _executor_raw=executor,
            _plan_raw=plan_status,
            _git_raw=git,
            _reports_raw=reports,
        )

    def _fact_snapshot_to_analyze_legacy(self, snapshot: CoreFactSnapshot) -> dict[str, Any]:
        runner = dict(snapshot._runner_raw) if snapshot._runner_raw else {}
        plan = dict(snapshot._plan_raw) if snapshot._plan_raw else dict(snapshot.plan_status)
        executor = dict(snapshot._executor_raw) if snapshot._executor_raw else {}
        git = dict(snapshot._git_raw) if snapshot._git_raw else dict(snapshot.git_status)
        reports = dict(snapshot._reports_raw) if snapshot._reports_raw else dict(snapshot.latest_report)

        plan_blockers = list(plan.get("blockers", []))

        return {
            "ok": True,
            "project_identity": snapshot.project_identity,
            "mode": snapshot.mode,
            "risk_level": snapshot.risk_level,
            "git": git,
            "runner": runner,
            "plan": plan,
            "executor": executor,
            "reports": reports,
            "summary": snapshot.summary,
            "recommended_next_actions": list(snapshot.recommended_next_actions),
            "blockers": plan_blockers,
            "warnings": snapshot.warnings,
            "unreconciled_direct_version_count": snapshot.unreconciled_direct_version_count,
            "unreconciled_direct_versions": snapshot.unreconciled_direct_versions,
            "partial_errors": list(snapshot.partial_errors),
        }

    def _build_project_identity(self) -> dict[str, Any]:
        try:
            result = build_project_identity(self.project_root)
            return result if isinstance(result, dict) else {"project_root": self.project_root}
        except Exception:
            return {"project_root": self.project_root}

    def _collect_git_status(self) -> dict[str, Any]:
        try:
            result = self._source_review.get_git_status(self.project_root)
            return {"result": result}
        except Exception as exc:
            return {"result": {"ok": False}, "error": str(exc)}

    @staticmethod
    def _is_ignored_runner_runtime_dirty_path(path: str) -> bool:
        return classify_runner_path(path).get("category") in {
            "project_local",
            "runtime_ephemeral",
            "archive_private_or_exportable",
        }

    def _determine_risk_level(
        self, mode: str, plan_blockers: list[str], executor: dict[str, Any],
    ) -> str:
        if plan_blockers:
            return "blocked"
        if mode == "source_only":
            return "info"
        if executor.get("risk_level") == "blocked":
            return "blocked"
        if executor.get("risk_level") == "warning":
            return "warning"
        return "none"

    def _summarize_analyzed_state(
        self, mode: str, has_plan: bool, has_state: bool,
        working_tree_clean: bool | None, runner: dict[str, Any],
        executor: dict[str, Any], plan: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        has_runner_state = runner.get("has_runner_state", False)
        has_executor_session = executor.get("has_session", False)
        can_use_web_console = mode == "runner_managed"
        can_use_mcp_plan_onboarding = mode == "source_only"
        can_commit = working_tree_clean is False
        direct_count = int(runner.get("unreconciled_direct_version_count", 0) or 0)
        plan_summary = plan.get("plan_summary") if isinstance(plan, dict) else None
        if not isinstance(plan_summary, dict):
            plan_summary = {}
        try:
            plan_version_count = int(plan_summary.get("version_count", 0) or 0)
        except Exception:
            plan_version_count = 0
        try:
            enabled_plan_version_count = int(
                plan_summary.get("enabled_version_count", plan_version_count) or 0
            )
        except Exception:
            enabled_plan_version_count = plan_version_count
        has_plan_versions = plan_version_count > 0 or enabled_plan_version_count > 0

        if mode == "source_only":
            one_line = "项目处于 source-only 模式，尚未纳入 Runner 管理。推荐使用 run_mcp_workflow workflow=source_onboarding phase=preview 生成纳管预览（仅创建 .colameta 基础结构，不创建开发版本）。"
        elif mode == "runner_managed":
            pending_count = int(runner.get("pending_count", 0) or 0)
            if pending_count <= 0 and not has_plan_versions:
                one_line = "项目已纳入 Runner 管理，尚无开发版本。推荐先保存 prompt 文件，再通过 manage_plan_version insert_from_prompt_file_preview 插入第一个开发版本。"
            elif pending_count <= 0:
                current_version = str(runner.get("current_version") or "").strip()
                current_status = str(runner.get("current_version_status") or "").strip()
                current_text = (
                    f"当前版本 {current_version} 状态为 {current_status or 'unknown'}"
                    if current_version
                    else "当前没有 active 版本"
                )
                one_line = (
                    f"项目已纳入 Runner 管理，计划中有 {plan_version_count} 个版本，"
                    f"{current_text}，暂无待执行版本。推荐使用 run_mcp_workflow workflow=project_status "
                    "phase=inspect 查看完整状态，或为下一轮优化保存 prompt 并插入新版本。"
                )
            else:
                one_line = "项目已纳入 Runner 管理。推荐使用 run_mcp_workflow workflow=project_status phase=inspect 查看完整状态。"
        elif mode == "plan_without_state":
            one_line = "项目存在 plan.json 但缺少 state.json，状态不完整。"
        elif mode == "state_without_plan":
            one_line = "项目存在 state.json 但缺少 plan.json，状态不完整。"
        else:
            one_line = "项目状态异常。"

        recommended_primary_action = "no_action_needed"
        if direct_count > 0:
            recommended_primary_action = "manual_git_history_review_required"
        elif mode == "source_only":
            recommended_primary_action = "run_mcp_workflow source_onboarding preview"
        elif mode == "runner_managed" and int(runner.get("pending_count", 0) or 0) <= 0:
            recommended_primary_action = "manage_prompt_file preview"
        elif working_tree_clean is False:
            recommended_primary_action = "run_mcp_workflow git_commit inspect"

        return {
            "one_line": one_line,
            "has_plan": has_plan,
            "has_runner_state": has_runner_state,
            "working_tree_clean": working_tree_clean,
            "has_executor_session": has_executor_session,
            "can_use_web_console": can_use_web_console,
            "can_use_mcp_plan_onboarding": can_use_mcp_plan_onboarding,
            "can_commit": can_commit,
            "recommended_primary_action": recommended_primary_action,
            "plan_version_count": plan_version_count,
            "enabled_plan_version_count": enabled_plan_version_count,
            "has_plan_versions": has_plan_versions,
        }

    def _build_pending_queue_warnings(
        self,
        *,
        pending_versions: list,
        pending_count: int,
        next_not_started_version,
    ) -> list[str]:
        warnings: list[str] = []
        if pending_count <= 0:
            return warnings
        if pending_count == 1:
            return warnings
        warnings.append(f"pending 队列中有 {pending_count} 个版本待执行，先检查队列状态确认队列顺序。")
        if next_not_started_version:
            warnings.append(f"下一个待执行版本为 {next_not_started_version}。")
        return warnings

    def _build_unreconciled_direct_warnings(
        self,
        *,
        direct_versions: list,
        count: int,
    ) -> list[str]:
        if count <= 0:
            return []
        summary = f"Git 历史中发现 {count} 个未纳入 Runner lineage 的 direct version 提交。"
        if direct_versions:
            formatted = []
            for v in direct_versions[:5]:
                if isinstance(v, dict):
                    ver = v.get("version", str(v))
                    commit = v.get("commit_hash_short", "")
                    formatted.append(f"{ver}@{commit}" if commit else str(ver))
                else:
                    formatted.append(str(v))
            details = f"涉及版本：{', '.join(formatted)}"
            if count > 5:
                details = f"{details}\n还有 {count - 5} 个未显示。"
            return [f"{summary}\n{details}"]
        return [summary]

    def _recommend_next_actions(
        self, mode: str, git: dict[str, Any], plan: dict[str, Any],
        runner: dict[str, Any], executor: dict[str, Any], working_tree_clean: bool | None,
        reports: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        actions: list[dict[str, Any]] = []
        direct_count = int(runner.get("unreconciled_direct_version_count", 0) or 0)
        if direct_count > 0:
            actions.append({
                "action": "manual_git_history_review_required",
                "label": "需要 direct version 对账",
                "reason": "Git 历史发现未纳入 Runner lineage 的版本提交；旧 manage_git_history 不再作为 normal public 入口暴露。",
                "tool": "run_mcp_workflow",
                "params": {"workflow": "project_status", "phase": "inspect"},
                "risk_level": "info",
                "requires_confirmation": False,
            })

        if mode == "source_only":
            actions.append({
                "action": "source_onboarding",
                "label": "生成纳管预览（推荐）",
                "reason": "项目尚未纳入 Runner 管理。使用高层 workflow 入口。",
                "tool": "run_mcp_workflow",
                "params": {"workflow": "source_onboarding", "phase": "preview"},
                "risk_level": "info",
                "requires_confirmation": True,
            })
            actions.append({
                "action": "inspect_source_only",
                "label": "检查项目现状（底层）",
                "reason": "使用底层 manage_runner_plan 检查。",
                "tool": "manage_runner_plan",
                "params": {"action": "inspect"},
                "risk_level": "none",
                "requires_confirmation": False,
            })
            actions.append({
                "action": "bootstrap_plan_preview",
                "label": "生成纳管预览（底层）",
                "reason": "使用底层 manage_runner_plan bootstrap_preview。",
                "tool": "manage_runner_plan",
                "params": {"action": "bootstrap_preview"},
                "risk_level": "info",
                "requires_confirmation": True,
            })

        if working_tree_clean is False:
            actions.append({
                "action": "review_diff",
                "label": "审查改动",
                "reason": "工作区有未提交改动。",
                "tool": "manage_git",
                "params": {"action": "review_context"},
                "risk_level": "none",
                "requires_confirmation": False,
            })
            actions.append({
                "action": "git_commit_inspect",
                "label": "审查并提交改动（推荐）",
                "reason": "使用高层 workflow 入口审查并提交。",
                "tool": "run_mcp_workflow",
                "params": {"workflow": "git_commit", "phase": "inspect"},
                "risk_level": "info",
                "requires_confirmation": False,
            })
            actions.append({
                "action": "commit_readiness",
                "label": "预览提交（底层）",
                "reason": "使用底层 commit_readiness 预览。",
                "tool": "manage_git",
                "params": {"action": "commit_readiness"},
                "risk_level": "warning",
                "requires_confirmation": True,
            })

        if mode == "runner_managed" and plan.get("has_plan"):
            actions.append({
                "action": "open_web_console",
                "label": "打开 Web Console",
                "reason": "Web Console 是主工作台。",
                "tool": "none",
                "params": {},
                "risk_level": "none",
                "requires_confirmation": False,
            })
            pending_count = int(runner.get("pending_count", 0) or 0)
            next_not_started_version = str(runner.get("next_not_started_version") or "").strip()
            if pending_count <= 0:
                actions.append({
                    "action": "save_prompt_file",
                    "label": "保存 prompt 文件",
                    "reason": "先保存开发 prompt 到 .colameta/prompts/，再插入为计划版本。",
                    "tool": "manage_prompt_file",
                    "params": {"action": "preview"},
                    "risk_level": "preview",
                    "requires_confirmation": True,
                })
                actions.append({
                    "action": "insert_from_prompt_file_preview",
                    "label": "从 prompt 文件插入版本",
                    "reason": "从已有的 prompt 文件生成 plan patch 并预览。",
                    "tool": "manage_plan_version",
                    "params": {"action": "insert_from_prompt_file_preview"},
                    "risk_level": "preview",
                    "requires_confirmation": True,
                })
                actions.append({
                    "action": "plan_insert_preview",
                    "label": "直接新增版本（底层）",
                    "reason": "当前没有待执行版本，可直接追加新版本。",
                    "tool": "manage_plan_version",
                    "params": {"action": "insert_preview"},
                    "risk_level": "preview",
                    "requires_confirmation": True,
                })
            elif pending_count == 1:
                update_params: dict[str, Any] = {"action": "update_preview"}
                append_params: dict[str, Any] = {"action": "insert_preview"}
                if next_not_started_version:
                    update_params["version"] = next_not_started_version
                    append_params["insert_after"] = next_not_started_version
                actions.append({
                    "action": "review_pending_queue",
                    "label": "检查待执行版本",
                    "reason": "当前存在 1 个待执行版本，先确认是更新现有任务还是在其后追加。",
                    "tool": "manage_plan_version",
                    "params": {"action": "inspect"},
                    "risk_level": "info",
                    "requires_confirmation": False,
                })
                actions.append({
                    "action": "update_existing_pending",
                    "label": "更新待执行版本",
                    "reason": "保持队列顺序，更新已有 NOT_STARTED 版本。",
                    "tool": "manage_plan_version",
                    "params": update_params,
                    "risk_level": "preview",
                    "requires_confirmation": True,
                })
                actions.append({
                    "action": "append_after_pending",
                    "label": "在待执行版本后追加",
                    "reason": "确认保留现有待执行版本后再追加新任务。",
                    "tool": "manage_plan_version",
                    "params": append_params,
                    "risk_level": "preview",
                    "requires_confirmation": True,
                })
            else:
                actions.append({
                    "action": "review_pending_queue_required",
                    "label": "确认待执行队列",
                    "reason": "当前存在多个待执行版本，先确认队列顺序后再新增任务。",
                    "tool": "manage_plan_version",
                    "params": {"action": "inspect"},
                    "risk_level": "warning",
                    "requires_confirmation": False,
                })

        if isinstance(reports, dict) and (bool(reports.get("available")) or int(reports.get("count", 0)) > 0):
            actions.append({
                "action": "read_executor_report",
                "label": "读取执行器报告",
                "reason": "有可用的执行器运行报告。",
                "tool": "list_executor_run_reports",
                "params": {},
                "risk_level": "none",
                "requires_confirmation": False,
            })

        if plan.get("lint_blocking_issue_count", 0) > 0:
            actions.append({
                "action": "fix_plan",
                "label": "修复计划问题",
                "reason": f"计划存在 {plan['lint_blocking_issue_count']} 个阻断问题。",
                "tool": "get_plan_standards_report",
                "params": {},
                "risk_level": "blocked",
                "requires_confirmation": False,
            })

        if not actions:
            actions.append({
                "action": "no_action_needed",
                "label": "无需操作",
                "reason": "当前项目状态正常。",
                "tool": "none",
                "params": {},
                "risk_level": "none",
                "requires_confirmation": False,
            })

        return actions

    def _bool_param(self, value: Any, default: bool = True) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in ("true", "1", "yes")
        if isinstance(value, (int, float)):
            return bool(value)
        return default

    # ================================================================
    # agent_dispatch
    # ================================================================

    def _workflow_agent_dispatch(self, params: dict[str, Any]) -> dict[str, Any]:
        phase = str(params.get("phase", "inspect")).strip().lower() or "inspect"
        if phase == "inspect":
            return self._agent_dispatch_inspect(params)
        if phase == "preview":
            return self._agent_dispatch_preview(params)
        if phase == "apply":
            return self._agent_dispatch_apply(params)
        if phase == "run_preview":
            return self._agent_dispatch_run_preview(params)
        if phase == "run":
            return self._agent_dispatch_run(params)
        if phase == "status":
            return self._agent_dispatch_status(params)
        return self._error_result(
            "agent_dispatch",
            "PHASE_NOT_SUPPORTED",
            f"不支持 phase={phase}。支持：inspect、preview、apply、run_preview、run、status。",
        )

    def _agent_dispatch_precheck(
        self,
        params: dict[str, Any],
        *,
        require_runner_managed: bool,
        require_git_clean: bool,
        require_lint_clean: bool,
        require_provider: bool,
        require_executor_session_clear: bool,
    ) -> dict[str, Any]:
        if self._analyze_state_fn is None:
            return {
                "ok": False,
                "error": self._error_result("agent_dispatch", "ANALYZE_FN_MISSING", "analyze_state_fn 未提供。"),
            }
        provider_result = self._resolve_agent_dispatch_provider(params.get("provider"), require_provider=require_provider)
        if provider_result.get("error") is not None:
            return {"ok": False, "error": provider_result["error"]}
        provider = provider_result["provider"]

        analyze = self._analyze_state_fn({"include_reports": True, "provider": provider})
        steps = [self._step("agent_dispatch", "analyze_project_state", "analyze", analyze, STEP_RISK_INFO)]
        if not analyze.get("ok"):
            return {
                "ok": False,
                "error": self._build_core_result(
                    workflow="agent_dispatch",
                    steps=steps,
                    risk_level=STEP_RISK_BLOCKED,
                    status="failed",
                    requires_confirmation=False,
                    blockers=["analyze_project_state 失败。"],
                    result=analyze,
                ),
            }

        plan_info = analyze.get("plan", {}) if isinstance(analyze, dict) else {}
        git_info = analyze.get("git", {}) if isinstance(analyze, dict) else {}
        source_only = bool(plan_info.get("source_only")) if isinstance(plan_info, dict) else True
        lint_blockers = int(plan_info.get("lint_blocking_issue_count", 0)) if isinstance(plan_info, dict) else 0
        if isinstance(git_info, dict):
            git_clean = bool(git_info.get("blocking_working_tree_clean", git_info.get("working_tree_clean")))
        else:
            git_clean = False

        continuation_snapshot = self._continuation_snapshot or get_or_collect_continuation_snapshot(
            self.project_root,
            requested_provider=provider,
            planning_bridge=self._planning_bridge,
            source_review=self._source_review,
        )
        if self._continuation_snapshot is None:
            self._continuation_snapshot = continuation_snapshot
        continuation_projection = continuation_snapshot.project(provider)
        session_status = continuation_snapshot.session_status
        continuation_preview = continuation_snapshot.continuation_preview
        continuation_decision = continuation_projection["canonical_continuation_decision"]
        session_step_result = {
            "ok": True,
            "session_status": session_status,
            "continuation_preview": continuation_preview,
            "canonical_continuation_decision": continuation_decision,
            "continuation_snapshot": continuation_snapshot.public_view(provider),
            "warnings": continuation_decision.get("risk_warnings", []),
            "blockers": (
                continuation_decision.get("hard_blockers", [])
                if require_executor_session_clear
                else []
            ),
        }
        steps.append(self._step("agent_dispatch", "executor_session", "status", session_step_result, STEP_RISK_INFO))

        blockers: list[str] = []
        warnings: list[str] = []
        if source_only:
            blockers.append("项目处于 source-only 模式，先完成 Runner 纳管。")
        if lint_blockers > 0:
            blockers.append("plan lint 存在 blocker，先修复后再派发执行。")
        if not git_clean:
            blockers.append("Git 工作区存在改动，先清理后再派发执行。")

        hard_blockers: list[str] = []
        if isinstance(continuation_decision, dict):
            for item in continuation_decision.get("risk_warnings", []) or []:
                if isinstance(item, str) and item not in warnings:
                    warnings.append(item)
            for item in continuation_decision.get("hard_blockers", []) or []:
                if isinstance(item, str) and item not in hard_blockers:
                    hard_blockers.append(item)
        if isinstance(continuation_preview, dict):
            for item in continuation_preview.get("warnings", []) or []:
                if isinstance(item, str) and item not in warnings:
                    warnings.append(item)

        if require_executor_session_clear:
            for item in hard_blockers:
                if item not in blockers:
                    blockers.append(item)

        if require_runner_managed and source_only:
            return {"ok": False, "error": self._error_result("agent_dispatch", "RUNNER_MANAGED_REQUIRED", "agent_dispatch 仅支持 Runner-managed 项目。")}
        if require_git_clean and (not git_clean):
            return {"ok": False, "error": self._error_result("agent_dispatch", "DIRTY_GIT_STATUS", "当前工作区存在改动，agent_dispatch 需要干净工作区。")}
        if require_lint_clean and lint_blockers > 0:
            return {"ok": False, "error": self._error_result("agent_dispatch", "PLAN_LINT_BLOCKED", "plan lint 存在 blocker，无法继续。")}
        if require_executor_session_clear and blockers:
            return {
                "ok": False,
                "error": self._build_core_result(
                    workflow="agent_dispatch",
                    steps=steps,
                    risk_level=STEP_RISK_BLOCKED,
                    status="blocked",
                    requires_confirmation=False,
                    blockers=blockers,
                    warnings=warnings,
                    result={
                        "ok": False,
                        "error_code": "EXECUTOR_SESSION_BLOCKED",
                        "message": "executor session 前置状态阻断了当前操作。",
                        "hard_blockers": hard_blockers,
                        "warnings": warnings,
                    },
                ),
            }

        inspect_result = {
            "ok": True,
            "dispatch_ready": len(blockers) == 0,
            "runner_managed": not source_only,
            "git_clean": git_clean,
            "lint_blocking_issue_count": lint_blockers,
            "current_version": (analyze.get("runner") or {}).get("current_version") if isinstance(analyze.get("runner"), dict) else None,
            "next_version": (analyze.get("runner") or {}).get("next_version") if isinstance(analyze.get("runner"), dict) else None,
            "executor_session_status": session_status,
            "executor_continuation_preview": continuation_preview,
            "hard_blockers": hard_blockers,
            "provider": provider,
        }
        return {
            "ok": True,
            "provider": provider,
            "analyze": analyze,
            "steps": steps,
            "blockers": blockers,
            "warnings": warnings,
            "inspect_result": inspect_result,
        }

    def _agent_dispatch_inspect(self, params: dict[str, Any]) -> dict[str, Any]:
        precheck = self._agent_dispatch_precheck(
            params,
            require_runner_managed=False,
            require_git_clean=False,
            require_lint_clean=False,
            require_provider=False,
            require_executor_session_clear=False,
        )
        if not precheck.get("ok"):
            return precheck["error"]
        steps = precheck["steps"]
        blockers = precheck["blockers"]
        warnings = precheck["warnings"]
        inspect_result = precheck["inspect_result"]
        can_dispatch = bool(inspect_result.get("dispatch_ready"))
        next_actions = []
        if can_dispatch:
            next_actions.append({
                "action": "agent_dispatch.preview",
                "label": "生成派发预览",
                "tool": "run_mcp_workflow",
                "params": {"workflow": "agent_dispatch", "phase": "preview"},
                "risk_level": "preview",
                "requires_confirmation": True,
            })
        else:
            next_actions.append({
                "action": "project_status.inspect",
                "label": "查看当前状态",
                "tool": "run_mcp_workflow",
                "params": {"workflow": "project_status", "phase": "inspect"},
                "risk_level": "info",
                "requires_confirmation": False,
            })

        return self._build_core_result(
            workflow="agent_dispatch",
            steps=steps,
            risk_level=STEP_RISK_INFO if can_dispatch else STEP_RISK_BLOCKED,
            status="succeeded" if can_dispatch else "blocked",
            requires_confirmation=False,
            next_actions=next_actions,
            blockers=blockers,
            warnings=warnings,
            result=inspect_result,
        )

    def _agent_dispatch_preview(self, params: dict[str, Any]) -> dict[str, Any]:
        disallowed_raw_inputs = ("plan_json", "raw_plan", "patch_body", "raw_patch_body", "raw_patch", "spec_json")
        for key in disallowed_raw_inputs:
            if key in params and params.get(key) is not None:
                return self._error_result("agent_dispatch", "RAW_INPUT_NOT_SUPPORTED", f"agent_dispatch preview 不接受 {key}。")
        user_request = params.get("user_request")
        if not isinstance(user_request, str) or not user_request.strip():
            return self._error_result("agent_dispatch", "USER_REQUEST_REQUIRED", "preview 需要非空 user_request。")

        precheck = self._agent_dispatch_precheck(
            params,
            require_runner_managed=True,
            require_git_clean=True,
            require_lint_clean=True,
            require_provider=True,
            require_executor_session_clear=False,
        )
        if not precheck.get("ok"):
            return precheck["error"]
        steps = list(precheck["steps"])
        inspect_result = precheck["inspect_result"]
        analyze = precheck.get("analyze", {})
        provider = precheck["provider"]

        version = self._agent_dispatch_resolve_version(params, inspect_result)
        name = self._agent_dispatch_resolve_name(params, user_request, version)
        description = self._agent_dispatch_resolve_description(params, user_request, version)
        insert_after_result = self._agent_dispatch_resolve_insert_after(params, inspect_result, analyze)
        if not insert_after_result.get("ok"):
            return self._error_result(
                "agent_dispatch",
                insert_after_result.get("error_code", "INSERT_AFTER_UNRESOLVED"),
                insert_after_result.get("message", "无法推断 insert_after。"),
            )
        insert_after = insert_after_result["insert_after"]
        allowed_files = self._agent_dispatch_resolve_allowed_files(params, user_request)
        if not allowed_files:
            return self._error_result(
                "agent_dispatch",
                "ALLOWED_FILES_REQUIRED",
                "无法从 user_request 推断 allowed_files，请显式提供 allowed_files。",
            )
        acceptance_commands = self._agent_dispatch_resolve_acceptance_commands(params, allowed_files)
        if not acceptance_commands:
            return self._error_result(
                "agent_dispatch",
                "ACCEPTANCE_COMMANDS_REQUIRED",
                "无法推断 acceptance_commands，请显式提供 acceptance_commands。",
            )
        manual_acceptance = self._normalize_string_list(params.get("manual_acceptance"))
        if not manual_acceptance:
            manual_acceptance = ["确认核心行为与当前基线兼容。"]
        out_of_scope = self._normalize_string_list(params.get("out_of_scope"))
        if not out_of_scope:
            out_of_scope = [
                "不执行自动提交",
                "不执行破坏性 git 命令",
                "不修改未列入 allowed_files 的文件",
            ]
        context_files = self._normalize_string_list(params.get("context_files"))
        forbidden_files = self._normalize_string_list(params.get("forbidden_files"))
        prompt = self._agent_dispatch_build_prompt(
            user_request=user_request.strip(),
            version=version,
            name=name,
            allowed_files=allowed_files,
            acceptance_commands=acceptance_commands,
            out_of_scope=out_of_scope,
        )

        spec: dict[str, Any] = {
            "insert_after": insert_after,
            "version": version,
            "name": name,
            "description": description,
            "prompt": prompt,
            "allowed_files": allowed_files,
            "acceptance_commands": acceptance_commands,
            "manual_acceptance": manual_acceptance,
            "out_of_scope": out_of_scope,
            "agent_dispatch_context": {
                "workflow": "agent_dispatch",
                "phase": "preview",
                "purpose": "agent_dispatch_plan_patch",
                "project_root": self.project_root,
            },
        }
        if context_files:
            spec["context_files"] = context_files
        if forbidden_files:
            spec["forbidden_files"] = forbidden_files
        try:
            result = self._planning_bridge.preview_insert_version(self.project_root, spec)
        except PlanningBridgeError as exc:
            return self._error_result("agent_dispatch", "INSERT_PREVIEW_FAILED", str(exc))
        except Exception as exc:  # pragma: no cover - defensive
            return self._error_result("agent_dispatch", "INSERT_PREVIEW_FAILED", f"生成版本预览失败：{exc}")

        result["proposal"] = {
            "version": version,
            "name": name,
            "description": description,
            "insert_after": insert_after,
            "provider": provider,
            "allowed_files": allowed_files,
            "acceptance_commands": acceptance_commands,
            "manual_acceptance": manual_acceptance,
            "out_of_scope": out_of_scope,
            "context_files": context_files,
            "forbidden_files": forbidden_files,
            "prompt": prompt,
        }
        steps.append(self._step("agent_dispatch", "manage_plan_version", "insert_preview", result, STEP_RISK_PREVIEW))
        preview_ids = self._extract_preview_ids(result)
        next_actions = []
        if preview_ids:
            next_actions.append({
                "action": "agent_dispatch.apply",
                "label": "应用版本预览",
                "tool": "run_mcp_workflow",
                "params": {"workflow": "agent_dispatch", "phase": "apply", "preview_id": preview_ids[0]},
                "risk_level": "commit",
                "requires_confirmation": True,
            })
        return self._build_core_result(
            workflow="agent_dispatch",
            steps=steps,
            risk_level=STEP_RISK_PREVIEW,
            status="preview_ready" if preview_ids else ("succeeded" if result.get("ok") else "failed"),
            requires_confirmation=bool(preview_ids),
            next_actions=next_actions,
            preview_ids=preview_ids,
            result=result,
        )

    def _agent_dispatch_apply(self, params: dict[str, Any]) -> dict[str, Any]:
        preview_id = params.get("preview_id")
        patch_id = params.get("patch_id")
        resolved_patch_id = patch_id if isinstance(patch_id, str) and patch_id.strip() else preview_id
        if not isinstance(resolved_patch_id, str) or not resolved_patch_id.strip():
            return self._error_result("agent_dispatch", "PREVIEW_ID_REQUIRED", "apply 需要 preview_id 或 patch_id。")
        precheck = self._agent_dispatch_precheck(
            params,
            require_runner_managed=True,
            require_git_clean=True,
            require_lint_clean=True,
            require_provider=False,
            require_executor_session_clear=False,
        )
        if not precheck.get("ok"):
            return precheck["error"]
        marker_error = self._validate_agent_dispatch_plan_patch_source(resolved_patch_id.strip())
        if marker_error is not None:
            return marker_error
        try:
            result = self._planning_bridge.apply_plan_patch(self.project_root, resolved_patch_id.strip())
        except PlanningBridgeError as exc:
            return self._error_result("agent_dispatch", "APPLY_PLAN_PATCH_FAILED", str(exc))
        except Exception as exc:  # pragma: no cover - defensive
            return self._error_result("agent_dispatch", "APPLY_PLAN_PATCH_FAILED", f"应用版本补丁失败：{exc}")

        steps = list(precheck["steps"])
        steps.append(self._step("agent_dispatch", "manage_plan_version", "apply", result, STEP_RISK_WRITE))
        recommended_version = result.get("inserted_version") or result.get("updated_version")
        next_actions = []
        if result.get("ok"):
            action_params: dict[str, Any] = {"workflow": "agent_dispatch", "phase": "run_preview"}
            if isinstance(recommended_version, str) and recommended_version.strip():
                action_params["version"] = recommended_version.strip()
            next_actions.append({
                "action": "agent_dispatch.run_preview",
                "label": "生成执行器运行预览",
                "tool": "run_mcp_workflow",
                "params": action_params,
                "risk_level": "preview",
                "requires_confirmation": True,
            })
        result["recommended_next_action"] = "run_preview"
        if isinstance(recommended_version, str) and recommended_version.strip():
            result["version"] = recommended_version.strip()
        return self._build_core_result(
            workflow="agent_dispatch",
            steps=steps,
            risk_level=STEP_RISK_WRITE,
            status="succeeded" if result.get("ok") else "failed",
            requires_confirmation=False,
            next_actions=next_actions,
            changed_files=self._extract_changed_files(result),
            result=result,
        )

    def _agent_dispatch_run_preview(self, params: dict[str, Any]) -> dict[str, Any]:
        execution_mode = str(params.get("execution_mode", "run")).strip().lower() or "run"
        if execution_mode != "run":
            return self._error_result("agent_dispatch", "EXECUTION_MODE_NOT_SUPPORTED", "run_preview 仅支持 execution_mode=run。")
        precheck = self._agent_dispatch_precheck(
            params,
            require_runner_managed=True,
            require_git_clean=True,
            require_lint_clean=True,
            require_provider=True,
            require_executor_session_clear=True,
        )
        if not precheck.get("ok"):
            return precheck["error"]
        provider = precheck["provider"]
        steps = list(precheck["steps"])
        inspect_result = precheck["inspect_result"]

        manager = self._executor_workflow_factory(self.project_root)
        preflight = manager.handle("preflight", {"provider": provider, "execution_mode": "run"})
        steps.append(self._step("agent_dispatch", "manage_executor_workflow", "preflight", preflight, STEP_RISK_INFO))
        if not preflight.get("ok") or preflight.get("preflight_blocked"):
            return self._build_core_result(
                workflow="agent_dispatch",
                steps=steps,
                risk_level=STEP_RISK_BLOCKED,
                status="blocked",
                requires_confirmation=False,
                result=preflight,
            )

        requested_version = params.get("version")
        if isinstance(requested_version, str) and requested_version.strip():
            current_version = str(preflight.get("current_version") or "").strip()
            if current_version and requested_version.strip() != current_version:
                return self._error_result(
                    "agent_dispatch",
                    "VERSION_MISMATCH",
                    f"requested version={requested_version.strip()} 与当前可运行版本={current_version} 不一致。",
                )

        preview = manager.handle("run_once_preview", {"provider": provider, "execution_mode": "run"})
        steps.append(self._step("agent_dispatch", "manage_executor_workflow", "run_once_preview", preview, STEP_RISK_PREVIEW))
        preview_id_value = preview.get("preview_id")
        if isinstance(preview_id_value, str) and preview_id_value.strip():
            self._tag_agent_dispatch_executor_preview(preview_id_value.strip(), provider)
        preview_ids = self._extract_preview_ids(preview)
        next_actions = []
        if preview_ids:
            next_actions.append({
                "action": "agent_dispatch.run",
                "label": "确认启动执行器",
                "tool": "run_mcp_workflow",
                "params": {"workflow": "agent_dispatch", "phase": "run", "preview_id": preview_ids[0], "provider": provider},
                "risk_level": "commit",
                "requires_confirmation": True,
            })
        return self._build_core_result(
            workflow="agent_dispatch",
            steps=steps,
            risk_level=STEP_RISK_PREVIEW,
            status="preview_ready" if preview_ids else ("succeeded" if preview.get("ok") else "failed"),
            requires_confirmation=bool(preview_ids),
            preview_ids=preview_ids,
            next_actions=next_actions,
            blockers=self._extract_blockers(preview),
            warnings=self._extract_warnings(preview),
            result=preview,
        )

    def _agent_dispatch_run(self, params: dict[str, Any]) -> dict[str, Any]:
        preview_id = params.get("preview_id")
        if not isinstance(preview_id, str) or not preview_id.strip():
            return self._error_result("agent_dispatch", "PREVIEW_ID_REQUIRED", "run 需要 preview_id。")
        precheck = self._agent_dispatch_precheck(
            params,
            require_runner_managed=True,
            require_git_clean=True,
            require_lint_clean=True,
            require_provider=True,
            require_executor_session_clear=True,
        )
        if not precheck.get("ok"):
            return precheck["error"]
        provider = precheck["provider"]
        source_error = self._validate_agent_dispatch_executor_preview_source(preview_id.strip(), provider)
        if source_error is not None:
            return source_error
        run_result = {
            "ok": False,
            "error_code": "EXECUTOR_ASYNC_START_UNAVAILABLE",
            "message": "当前 executor workflow 缺少启动后立即返回入口，agent_dispatch run 保持 fail-closed。",
            "recommended_next_action": "请在 Web Console 或受控 workflow 中手动确认运行。",
        }
        steps = list(precheck["steps"])
        steps.append(self._step("agent_dispatch", "manage_executor_workflow", "run", run_result, STEP_RISK_BLOCKED))
        return self._build_core_result(
            workflow="agent_dispatch",
            steps=steps,
            risk_level=STEP_RISK_BLOCKED,
            status="failed",
            requires_confirmation=False,
            blockers=self._extract_blockers(run_result),
            warnings=self._extract_warnings(run_result),
            result=run_result,
        )

    def _agent_dispatch_status(self, params: dict[str, Any]) -> dict[str, Any]:
        precheck = self._agent_dispatch_precheck(
            params,
            require_runner_managed=False,
            require_git_clean=False,
            require_lint_clean=False,
            require_provider=False,
            require_executor_session_clear=False,
        )
        if not precheck.get("ok"):
            return precheck["error"]
        analyze = precheck["analyze"]
        steps = list(precheck["steps"])
        manager = self._executor_workflow_factory(self.project_root)
        executor_status = manager.handle("status", {})
        git_status = self._source_review.get_git_status(self.project_root)
        steps.append(self._step("agent_dispatch", "manage_executor_workflow", "status", executor_status, STEP_RISK_INFO))
        steps.append(self._step("agent_dispatch", "get_git_status", "read", git_status, STEP_RISK_INFO))
        result = {
            "ok": bool(analyze.get("ok")) and bool(executor_status.get("ok")) and bool(git_status.get("ok")),
            "analyze_project_state": analyze,
            "executor_status": executor_status,
            "git_status": git_status,
            "next_action": "run_mcp_workflow workflow=agent_dispatch phase=inspect",
        }
        return self._build_core_result(
            workflow="agent_dispatch",
            steps=steps,
            risk_level=STEP_RISK_INFO,
            status="succeeded" if result.get("ok") else "failed",
            requires_confirmation=False,
            result=result,
        )

    def _agent_dispatch_resolve_version(self, params: dict[str, Any], inspect_result: dict[str, Any]) -> str:
        version = params.get("version")
        if isinstance(version, str) and version.strip():
            return version.strip()
        suggested = inspect_result.get("next_version")
        if isinstance(suggested, str) and suggested.strip():
            return suggested.strip()
        return self._infer_next_version_from_plan()

    def _agent_dispatch_resolve_name(self, params: dict[str, Any], user_request: str, version: str) -> str:
        name = params.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
        compact = re.sub(r"\s+", " ", user_request).strip()
        compact = compact[:32]
        return f"{version} {compact}" if compact else version

    def _agent_dispatch_resolve_description(self, params: dict[str, Any], user_request: str, version: str) -> str:
        description = params.get("description")
        if isinstance(description, str) and description.strip():
            return description.strip()
        compact = re.sub(r"\s+", " ", user_request).strip()
        if len(compact) > 96:
            compact = compact[:96].rstrip() + "..."
        return f"{version}：{compact}"

    def _agent_dispatch_resolve_insert_after(self, params: dict[str, Any], inspect_result: dict[str, Any], analyze: dict[str, Any]) -> dict[str, Any]:
        insert_after = params.get("insert_after")
        if isinstance(insert_after, str) and insert_after.strip():
            return {"ok": True, "insert_after": insert_after.strip()}
        current_version = inspect_result.get("current_version")
        if isinstance(current_version, str) and current_version.strip():
            return {"ok": True, "insert_after": current_version.strip()}
        plan_info = analyze.get("plan", {}) if isinstance(analyze, dict) else {}
        plan_summary = plan_info.get("plan_summary") if isinstance(plan_info, dict) else None
        version_count = int(plan_summary.get("version_count", 0)) if isinstance(plan_summary, dict) else 0
        if version_count <= 0:
            return {"ok": True, "insert_after": "__first__"}
        versions = plan_summary.get("versions") if isinstance(plan_summary, dict) else None
        if isinstance(versions, list) and versions and all(isinstance(v, str) for v in versions):
            return {"ok": True, "insert_after": versions[-1]}
        return {
            "ok": False,
            "error_code": "INSERT_AFTER_UNRESOLVED",
            "message": "非空 plan 且无 current_version 时无法推断 insert_after，请显式提供 insert_after。",
        }

    def _agent_dispatch_resolve_allowed_files(self, params: dict[str, Any], user_request: str) -> list[str]:
        explicit = self._normalize_string_list(params.get("allowed_files"))
        if explicit:
            return explicit
        text = user_request.lower()
        inferred: list[str] = []
        if any(token in text for token in ["readme", "docs", "文档"]):
            inferred.extend(["README.md", "docs/**/*.md"])
        if any(token in text for token in ["workflow", "mcp", "actions", "openapi"]):
            inferred.extend([
                "runner/mcp_workflow_router.py",
                "runner/mcp_server.py",
                "tests/test_mcp_workflow_router.py",
                "tests/test_mcp_actions_api.py",
                "tests/test_mcp_http_auth.py",
            ])
        if any(token in text for token in ["cli", "runner_cli"]):
            inferred.extend(["scripts/runner_cli.py", "tests/test_runner_cli.py"])
        if any(token in text for token in ["web", "console"]):
            inferred.extend(["runner/web_console.py"])
        unique: list[str] = []
        for item in inferred:
            if item not in unique:
                unique.append(item)
        return unique

    def _agent_dispatch_resolve_acceptance_commands(self, params: dict[str, Any], allowed_files: list[str]) -> list[Any]:
        raw = params.get("acceptance_commands")
        if isinstance(raw, list) and raw:
            normalized: list[Any] = []
            for item in raw:
                text = self._acceptance_command_to_text(item).strip()
                if text:
                    normalized.append(item)
            return normalized
        test_files = [f for f in allowed_files if f.startswith("tests/test_") and f.endswith(".py")]
        commands: list[str] = []
        for file_path in test_files[:4]:
            module = file_path[:-3].replace("/", ".")
            commands.append(f"python -m unittest {module}")
        return commands

    def _agent_dispatch_build_prompt(
        self,
        *,
        user_request: str,
        version: str,
        name: str,
        allowed_files: list[str],
        acceptance_commands: list[Any],
        out_of_scope: list[str],
    ) -> str:
        # 限制用户需求长度，避免 preview 响应返回过大 prompt 正文。
        request_text = user_request.strip()
        if len(request_text) > 2000:
            request_text = request_text[:2000] + "\n[TRUNCATED]"
        allowed_text = "\n".join(f"- {item}" for item in allowed_files)
        acceptance_text = "\n".join(f"- {self._acceptance_command_to_text(item)}" for item in acceptance_commands)
        out_scope_text = "\n".join(f"- {item}" for item in out_of_scope)
        return (
            f"版本：{version} {name}\n\n"
            f"用户需求：\n{request_text}\n\n"
            f"允许修改文件：\n{allowed_text}\n\n"
            "禁止修改范围：\n"
            "- 未列入 allowed_files 的文件\n"
            "- runtime/log/token/OAuth/session/state 文件\n\n"
            f"Out of scope：\n{out_scope_text}\n\n"
            f"验收命令：\n{acceptance_text}\n\n"
            "执行要求：\n"
            "- 所有写操作先 preview 再 apply/run\n"
            "- 输出修改文件列表、实现摘要、测试结果、风险和后续工作\n"
            "- 禁止自行提交 git commit\n"
            "- 禁止破坏性 git 命令（reset/clean/push/merge/rebase/checkout/switch/stash）\n"
            "- 禁止创建、打印或保存 secrets\n"
        )

    def _resolve_agent_dispatch_provider(self, value: Any, *, require_provider: bool) -> dict[str, Any]:
        provider = "codex"
        if value is None:
            return {"provider": provider, "error": None}
        if not isinstance(value, str) or not value.strip():
            if require_provider:
                return {
                    "provider": provider,
                    "error": self._error_result("agent_dispatch", "PROVIDER_NOT_SUPPORTED", "provider 仅支持 pi、codex、opencode。"),
                }
            return {"provider": provider, "error": None}
        provider_normalized = value.strip().lower()
        if provider_normalized not in {"pi", "codex", "opencode"}:
            return {
                "provider": provider,
                "error": self._error_result("agent_dispatch", "PROVIDER_NOT_SUPPORTED", "provider 仅支持 pi、codex、opencode。"),
            }
        return {"provider": provider_normalized, "error": None}

    def _agent_dispatch_plan_patch_path(self, patch_id: str) -> str:
        return resolve_project_runner_path(self.project_root, "plan-patches", f"{patch_id}.json")

    def _validate_agent_dispatch_plan_patch_source(self, patch_id: str) -> dict[str, Any] | None:
        patch_path = self._agent_dispatch_plan_patch_path(patch_id)
        if not os.path.isfile(patch_path):
            return self._error_result("agent_dispatch", "PREVIEW_SOURCE_MISMATCH", "patch 预览来源无效或不存在。")
        try:
            with open(patch_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception:
            return self._error_result("agent_dispatch", "PREVIEW_SOURCE_MISMATCH", "patch 预览元数据读取失败。")
        spec = payload.get("spec") if isinstance(payload, dict) else None
        marker = spec.get("agent_dispatch_context") if isinstance(spec, dict) else None
        if not isinstance(marker, dict):
            return self._error_result("agent_dispatch", "PREVIEW_SOURCE_MISMATCH", "patch 预览缺少 agent_dispatch 来源标记。")
        if marker.get("workflow") != "agent_dispatch" or marker.get("phase") != "preview":
            return self._error_result("agent_dispatch", "PREVIEW_SOURCE_MISMATCH", "patch 预览来源与 agent_dispatch preview 不匹配。")
        if marker.get("purpose") != "agent_dispatch_plan_patch":
            return self._error_result("agent_dispatch", "PREVIEW_SOURCE_MISMATCH", "patch 预览用途标记无效。")
        marker_root = marker.get("project_root")
        if not isinstance(marker_root, str) or os.path.abspath(marker_root) != self.project_root:
            return self._error_result("agent_dispatch", "PREVIEW_SOURCE_MISMATCH", "patch 预览项目来源不匹配。")
        return None

    def _executor_preview_artifact_path(self, preview_id: str) -> str:
        return resolve_project_runner_path(
            self.project_root, "runtime", "executor-workflow-previews", f"{preview_id}.json"
        )

    def _tag_agent_dispatch_executor_preview(self, preview_id: str, provider: str) -> None:
        artifact_path = self._executor_preview_artifact_path(preview_id)
        if not os.path.isfile(artifact_path):
            return
        try:
            with open(artifact_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            if not isinstance(payload, dict):
                return
            payload["agent_dispatch_context"] = {
                "workflow": "agent_dispatch",
                "phase": "run_preview",
                "purpose": "agent_dispatch_executor_run",
                "project_root": self.project_root,
                "provider": provider,
            }
            with open(artifact_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception:
            return

    def _validate_agent_dispatch_executor_preview_source(self, preview_id: str, provider: str) -> dict[str, Any] | None:
        artifact_path = self._executor_preview_artifact_path(preview_id)
        if not os.path.isfile(artifact_path):
            return self._error_result("agent_dispatch", "PREVIEW_SOURCE_MISMATCH", "run preview 来源无效或不存在。")
        try:
            with open(artifact_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception:
            return self._error_result("agent_dispatch", "PREVIEW_SOURCE_MISMATCH", "run preview 元数据读取失败。")
        if not isinstance(payload, dict):
            return self._error_result("agent_dispatch", "PREVIEW_SOURCE_MISMATCH", "run preview 元数据结构无效。")
        marker = payload.get("agent_dispatch_context")
        if not isinstance(marker, dict):
            return self._error_result("agent_dispatch", "PREVIEW_SOURCE_MISMATCH", "run preview 缺少 agent_dispatch 来源标记。")
        if marker.get("workflow") != "agent_dispatch" or marker.get("phase") != "run_preview":
            return self._error_result("agent_dispatch", "PREVIEW_SOURCE_MISMATCH", "run preview 来源与 agent_dispatch run_preview 不匹配。")
        if marker.get("purpose") != "agent_dispatch_executor_run":
            return self._error_result("agent_dispatch", "PREVIEW_SOURCE_MISMATCH", "run preview 用途标记无效。")
        marker_root = marker.get("project_root")
        if not isinstance(marker_root, str) or os.path.abspath(marker_root) != self.project_root:
            return self._error_result("agent_dispatch", "PREVIEW_SOURCE_MISMATCH", "run preview 项目来源不匹配。")
        marker_provider = marker.get("provider")
        if isinstance(marker_provider, str) and marker_provider.strip() and marker_provider.strip() != provider:
            return self._error_result("agent_dispatch", "PREVIEW_SOURCE_MISMATCH", "run preview provider 与当前请求不匹配。")
        return None

    def _infer_next_version_from_plan(self) -> str:
        plan_path = resolve_project_runner_path(self.project_root, "plan.json")
        if not os.path.isfile(plan_path):
            return "v1.0"
        try:
            import json
            with open(plan_path, "r", encoding="utf-8") as f:
                plan_data = json.load(f)
        except Exception:
            return "v1.0"
        versions = plan_data.get("versions", []) if isinstance(plan_data, dict) else []
        if not isinstance(versions, list) or not versions:
            return "v1.0"
        last_version = ""
        for item in versions:
            if isinstance(item, dict):
                candidate = item.get("version")
                if isinstance(candidate, str) and candidate.strip():
                    last_version = candidate.strip()
        if not last_version:
            return "v1.0"
        match = re.match(r"^v(\d+(?:\.\d+)*)$", last_version)
        if not match:
            return f"{last_version}.1"
        parts = [int(p) for p in match.group(1).split(".")]
        parts[-1] += 1
        return "v" + ".".join(str(p) for p in parts)

    def _normalize_string_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        out: list[str] = []
        for item in value:
            if isinstance(item, str):
                text = item.strip()
                if text and text not in out:
                    out.append(text)
        return out

    def _normalize_provider(self, value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        provider = value.strip().lower()
        if provider in {"pi", "codex", "opencode"}:
            return provider
        return None

    def _acceptance_command_to_text(self, item: Any) -> str:
        if isinstance(item, str):
            return item
        if isinstance(item, dict):
            command = item.get("command")
            if isinstance(command, str) and command.strip():
                return command.strip()
        return str(item)

    # ================================================================
    # source_onboarding
    # ================================================================

    def _workflow_source_onboarding(self, params: dict[str, Any]) -> dict[str, Any]:
        phase = params.get("phase", "preview")
        if phase == "apply":
            return self._error_result(
                "source_onboarding",
                "APPLY_NOT_SUPPORTED_IN_RUN_MCP_WORKFLOW",
                "run_mcp_workflow source_onboarding 不支持 phase=apply。请使用 manage_runner_plan apply 显式执行。",
            )
        if phase != "preview":
            return self._error_result("source_onboarding", "PHASE_NOT_SUPPORTED",
                                      "source_onboarding 只支持 phase=preview（v1.74）。")

        plan_params = {
            "action": "source_onboarding_preview",
            "project_name": params.get("project_name"),
            "goal": params.get("goal"),
            "first_version": params.get("first_version"),
            "first_version_name": params.get("first_version_name"),
            "dry_run": params.get("dry_run", False),
            "max_files": params.get("max_files"),
            "reason": params.get("reason"),
        }
        result = self.plan_workflow.handle("source_onboarding_preview", plan_params)
        steps = [self._step("source_onboarding", "manage_plan_workflow", "source_onboarding_preview", result, STEP_RISK_PREVIEW)]

        preview_ids = self._extract_preview_ids(result)
        requires_confirmation = result.get("ok", False) and bool(preview_ids)

        next_actions = []
        if preview_ids:
            next_actions.append({
                "action": "manage_runner_plan.apply",
                "label": "应用纳管计划",
                "tool": "manage_runner_plan",
                "params": {"action": "apply", "preview_id": preview_ids[0]},
                "risk_level": "commit",
                "requires_confirmation": True,
            })
        next_actions.append({
            "action": "list_workflow_runs",
            "label": "查看 workflow 记录",
            "tool": "list_workflow_runs",
            "params": {},
            "risk_level": "none",
            "requires_confirmation": False,
        })

        return self._build_core_result(
            workflow="source_onboarding",
            steps=steps,
            risk_level=STEP_RISK_PREVIEW,
            status="preview_ready" if preview_ids else ("failed" if not result.get("ok") else "succeeded"),
            requires_confirmation=requires_confirmation,
            next_actions=next_actions,
            preview_ids=preview_ids,
            blockers=self._extract_blockers(result),
            warnings=self._extract_warnings(result) + [
                "run_mcp_workflow source_onboarding 使用底层 manage_plan_workflow。新流程请直接使用 manage_runner_plan（inspect / bootstrap_preview / import_preview / apply）。"
            ],
            result=result,
        )

    # ================================================================
    # plan_update
    # ================================================================

    def _workflow_plan_update(self, params: dict[str, Any]) -> dict[str, Any]:
        phase = str(params.get("phase", "preview")).strip().lower() or "preview"
        if phase == "apply":
            disallowed_raw_inputs = ("plan_json", "raw_plan", "patch_body", "raw_patch_body", "raw_patch", "spec_json")
            for key in disallowed_raw_inputs:
                if key in params and params.get(key) is not None:
                    return self._error_result("plan_update", "RAW_INPUT_NOT_SUPPORTED",
                                              f"plan_update apply 不接受 {key}。")
            try:
                auto_apply_service = PlanPatchAutoApplyService(self.project_root)
                auto_apply_result = auto_apply_service.auto_apply()
            except Exception as exc:  # pragma: no cover - defensive
                return self._error_result("plan_update", "AUTO_APPLY_FAILED", f"应用 pending plan patch 失败：{exc}")

            result_ok = bool(auto_apply_result.get("ok"))
            applied_count = int(auto_apply_result.get("applied_count", 0) or 0)
            failed_count = int(auto_apply_result.get("failed_count", 0) or 0)
            skipped_count = int(auto_apply_result.get("skipped_count", 0) or 0)
            results = auto_apply_result.get("results")
            if not isinstance(results, list):
                results = []
            auto_apply_result["results"] = results
            auto_apply_result["applied_count"] = applied_count
            auto_apply_result["failed_count"] = failed_count
            auto_apply_result["skipped_count"] = skipped_count
            if applied_count == 0 and failed_count == 0 and not auto_apply_result.get("message"):
                auto_apply_result["message"] = "没有可应用的 eligible pending plan patch。"
            auto_apply_result["phase"] = "apply"
            auto_apply_result["workflow"] = "plan_update"

            step_result = dict(auto_apply_result)
            if failed_count > 0:
                step_result["ok"] = False
            steps = [self._step("plan_update", "plan_patch_auto_apply", "apply", step_result, STEP_RISK_WRITE)]

            blockers = self._extract_blockers(auto_apply_result)
            warnings = self._extract_warnings(auto_apply_result)
            if failed_count > 0:
                for item in results:
                    if isinstance(item, dict) and item.get("ok") is False:
                        msg = item.get("message")
                        if isinstance(msg, str) and msg and msg not in blockers:
                            blockers.append(msg)
                        code = item.get("error_code")
                        if isinstance(code, str) and code and code not in blockers:
                            blockers.append(code)
            if skipped_count > 0 and "存在已跳过的 pending patch。" not in warnings:
                warnings.append("存在已跳过的 pending patch。")

            next_actions = [
                {
                    "action": "project_status.inspect",
                    "label": "查看项目状态",
                    "tool": "run_mcp_workflow",
                    "params": {"workflow": "project_status", "phase": "inspect"},
                    "risk_level": "info",
                    "requires_confirmation": False,
                },
                {
                    "action": "executor_preview.later",
                    "label": "后续可生成执行器预览",
                    "tool": "manage_executor_workflow",
                    "params": {"action": "run_once_preview", "provider": "codex"},
                    "risk_level": "preview",
                    "requires_confirmation": True,
                },
            ]
            status = "failed"
            if result_ok and failed_count == 0 and applied_count > 0:
                status = "succeeded"
            elif result_ok and failed_count == 0 and applied_count == 0:
                status = "succeeded"
            elif result_ok and failed_count > 0:
                status = "blocked"

            return self._build_core_result(
                workflow="plan_update",
                steps=steps,
                risk_level=STEP_RISK_WRITE if status == "succeeded" else STEP_RISK_BLOCKED,
                status=status,
                requires_confirmation=False,
                next_actions=next_actions,
                changed_files=self._extract_changed_files(auto_apply_result),
                blockers=blockers,
                warnings=warnings,
                result=auto_apply_result,
            )

        if phase != "preview":
            return self._error_result("plan_update", "PHASE_NOT_SUPPORTED",
                                      "plan_update 支持 phase=preview 或 phase=apply。")

        mode = params.get("mode", "")
        has_repair_hints = bool(params.get("target_version") or params.get("version") or params.get("repair_kinds"))
        has_extend_hints = bool(params.get("name") or params.get("description") or params.get("prompt") or params.get("insert_after"))

        resolved_mode = ""
        if mode == "repair" or (not mode and has_repair_hints and not has_extend_hints):
            resolved_mode = "repair"
            plan_params = {
                "action": "plan_repair_preview",
                "version": params.get("version") or params.get("target_version"),
                "repair_kinds": params.get("repair_kinds"),
                "reason": params.get("reason"),
            }
            result = self.plan_workflow.handle("plan_repair_preview", plan_params)
            steps = [self._step("plan_update", "manage_plan_workflow", "plan_repair_preview", result, STEP_RISK_PREVIEW)]
        elif mode == "extend" or (not mode and has_extend_hints and not has_repair_hints):
            resolved_mode = "extend"
            plan_params = {
                "action": "plan_extend_preview",
                "version": params.get("version"),
                "insert_after": params.get("insert_after"),
                "name": params.get("name"),
                "description": params.get("description"),
                "prompt": params.get("prompt"),
                "user_request": params.get("user_request"),
                "allowed_files": params.get("allowed_files"),
                "forbidden_files": params.get("forbidden_files"),
                "acceptance_commands": params.get("acceptance_commands"),
                "manual_acceptance": params.get("manual_acceptance"),
                "out_of_scope": params.get("out_of_scope"),
                "context_files": params.get("context_files"),
                "provider": params.get("provider"),
                "reason": params.get("reason"),
            }
            result = self.plan_workflow.handle("plan_extend_preview", plan_params)
            steps = [self._step("plan_update", "manage_plan_workflow", "plan_extend_preview", result, STEP_RISK_PREVIEW)]
        else:
            return self._error_result(
                "plan_update", "MODE_REQUIRED",
                "plan_update 需要指定 mode=repair 或 mode=extend，或提供对应参数字段。",
            )

        preview_ids = self._extract_preview_ids(result)
        requires_confirmation = result.get("ok", False) and bool(preview_ids)

        next_actions = []
        if preview_ids:
            if resolved_mode == "repair":
                next_actions.append({
                    "action": "manage_plan_version.apply_preview",
                    "label": "应用 plan repair patch",
                    "tool": "manage_plan_version",
                    "params": {"action": "apply_preview", "patch_id": preview_ids[0]},
                    "risk_level": "commit",
                    "requires_confirmation": True,
                })
            elif resolved_mode == "extend":
                next_actions.append({
                    "action": "manage_plan_version.apply_preview",
                    "label": "应用 plan extend patch",
                    "tool": "manage_plan_version",
                    "params": {"action": "apply_preview", "patch_id": preview_ids[0]},
                    "risk_level": "commit",
                    "requires_confirmation": True,
                })
            next_actions.append({
                "action": "apply_preview_status",
                "label": "查看 patch 状态",
                "tool": "manage_plan_version",
                "params": {"action": "apply_preview_status", "patch_id": preview_ids[0]},
                "risk_level": "none",
                "requires_confirmation": False,
            })
        else:
            mainline_tool_hint = "manage_plan_version.repair_preview" if resolved_mode == "repair" else "manage_plan_version.insert_preview"
            next_actions.append({
                "action": "use_mainline_tool",
                "label": f"下次请直接使用 {mainline_tool_hint}",
                "tool": "manage_plan_version",
                "params": {},
                "risk_level": "none",
                "requires_confirmation": False,
            })

        return self._build_core_result(
            workflow="plan_update",
            steps=steps,
            risk_level=STEP_RISK_PREVIEW,
            status="preview_ready" if preview_ids else ("failed" if not result.get("ok") else "succeeded"),
            requires_confirmation=requires_confirmation,
            next_actions=next_actions,
            preview_ids=preview_ids,
            blockers=self._extract_blockers(result),
            warnings=self._extract_warnings(result) + [
                "run_mcp_workflow plan_update 使用底层 manage_plan_workflow。新流程请直接使用 manage_plan_version（repair_preview / insert_preview / apply_preview）。"
            ],
            result=result,
        )

    # ================================================================
    # small_project_patch
    # ================================================================

    def _workflow_small_project_patch(self, params: dict[str, Any]) -> dict[str, Any]:
        phase = params.get("phase", "preview")

        if phase == "status":
            patch_params = {
                "action": "status",
                "preview_id": params.get("preview_id"),
            }
            result = self.project_patch.status(patch_params)
            steps = [self._step("small_project_patch", "manage_project_patch", "status", result, STEP_RISK_INFO)]
            return self._build_core_result(
                workflow="small_project_patch",
                steps=steps,
                risk_level=STEP_RISK_INFO,
                status="succeeded" if result.get("ok") else "failed",
                requires_confirmation=False,
                result=result,
            )

        if phase == "preview":
            patch_params = {
                "action": "preview",
                "file": params.get("file"),
                "old_text": params.get("old_text"),
                "new_text": params.get("new_text"),
                "patch_text": params.get("patch_text"),
                "reason": params.get("reason"),
                "max_files": params.get("max_files"),
                "max_diff_chars": params.get("max_diff_chars"),
            }
            result = self.project_patch.preview(patch_params)
            steps = [self._step("small_project_patch", "manage_project_patch", "preview", result, STEP_RISK_PREVIEW)]

            preview_ids = self._extract_preview_ids(result)
            requires_confirmation = result.get("ok", False) and bool(preview_ids)

            next_actions = []
            if preview_ids:
                next_actions.append({
                    "action": "small_project_patch.apply",
                    "label": "应用 patch",
                    "tool": "run_mcp_workflow",
                    "params": {"workflow": "small_project_patch", "phase": "apply", "preview_id": preview_ids[0]},
                    "risk_level": "write",
                    "requires_confirmation": True,
                })
                next_actions.append({
                    "action": "manage_git_commit.suggest_commit_message",
                    "label": "建议 commit message",
                    "tool": "manage_git_commit",
                    "params": {"action": "suggest_commit_message"},
                    "risk_level": "info",
                    "requires_confirmation": False,
                })

            return self._build_core_result(
                workflow="small_project_patch",
                steps=steps,
                risk_level=STEP_RISK_PREVIEW,
                status="preview_ready" if preview_ids else ("failed" if not result.get("ok") else "succeeded"),
                requires_confirmation=requires_confirmation,
                next_actions=next_actions,
                preview_ids=preview_ids,
                result=result,
            )

        if phase == "apply":
            preview_id = params.get("preview_id")
            if not preview_id:
                return self._error_result("small_project_patch", "PREVIEW_ID_REQUIRED",
                                          "apply 需要 preview_id。")
            patch_params = {
                "action": "apply",
                "preview_id": preview_id,
            }
            result = self.project_patch.apply(patch_params)
            steps = [self._step("small_project_patch", "manage_project_patch", "apply", result, STEP_RISK_WRITE)]

            changed_files = self._extract_changed_files(result)
            next_actions = []
            if result.get("ok"):
                next_actions.append({
                    "action": "manage_git_commit.suggest_commit_message",
                    "label": "建议 commit message",
                    "tool": "manage_git_commit",
                    "params": {"action": "suggest_commit_message"},
                    "risk_level": "info",
                    "requires_confirmation": False,
                })
                next_actions.append({
                    "action": "manage_git_commit.commit_workflow_preview",
                    "label": "提交预览",
                    "tool": "manage_git_commit",
                    "params": {"action": "commit_workflow_preview"},
                    "risk_level": "preview",
                    "requires_confirmation": True,
                })

            return self._build_core_result(
                workflow="small_project_patch",
                steps=steps,
                risk_level=STEP_RISK_WRITE,
                status="succeeded" if result.get("ok") else "failed",
                requires_confirmation=False,
                next_actions=next_actions,
                changed_files=changed_files,
                result=result,
            )

        return self._error_result("small_project_patch", "PHASE_NOT_SUPPORTED",
                                  f"不支持 phase={phase}。支持：preview、apply、status。")

    # ================================================================
    # docs_update
    # ================================================================

    def _workflow_docs_update(self, params: dict[str, Any]) -> dict[str, Any]:
        phase = params.get("phase", "")
        docs_action = params.get("docs_action", "")

        resolved_action = docs_action
        if not resolved_action:
            if phase == "inspect" or not phase:
                resolved_action = "index"
            elif phase == "apply":
                resolved_action = "apply"
            elif phase == "preview":
                resolved_action = ""

        doc_params = {
            "action": resolved_action,
            "file": params.get("file"),
            "heading": params.get("heading"),
            "query": params.get("query"),
            "new_content": params.get("new_content"),
            "section_heading": params.get("section_heading"),
            "section_content": params.get("section_content"),
            "after_heading": params.get("after_heading"),
            "stale_terms": params.get("stale_terms"),
            "preview_id": params.get("preview_id"),
            "max_chars": params.get("max_chars"),
            "max_files": params.get("max_files"),
            "reason": params.get("reason"),
        }

        if resolved_action in ("index", "search", "read_section"):
            result = self.project_docs.handle(resolved_action, doc_params)
            steps = [self._step("docs_update", "manage_project_docs", resolved_action, result, STEP_RISK_INFO)]
            return self._build_core_result(
                workflow="docs_update",
                steps=steps,
                risk_level=STEP_RISK_INFO,
                status="succeeded" if result.get("ok") else "failed",
                requires_confirmation=False,
                result=result,
            )

        if resolved_action in ("update_section_preview", "append_section_preview", "sync_docs_preview"):
            result = self.project_docs.handle(resolved_action, doc_params)
            steps = [self._step("docs_update", "manage_project_docs", resolved_action, result, STEP_RISK_PREVIEW)]

            preview_ids = self._extract_preview_ids(result)
            requires_confirmation = result.get("ok", False) and bool(preview_ids)

            next_actions = []
            if preview_ids:
                next_actions.append({
                    "action": "docs_update.apply",
                    "label": "应用文档更新",
                    "tool": "run_mcp_workflow",
                    "params": {"workflow": "docs_update", "phase": "apply", "preview_id": preview_ids[0]},
                    "risk_level": "write",
                    "requires_confirmation": True,
                })

            return self._build_core_result(
                workflow="docs_update",
                steps=steps,
                risk_level=STEP_RISK_PREVIEW,
                status="preview_ready" if preview_ids else ("failed" if not result.get("ok") else "succeeded"),
                requires_confirmation=requires_confirmation,
                next_actions=next_actions,
                preview_ids=preview_ids,
                result=result,
            )

        if resolved_action == "apply":
            preview_id = params.get("preview_id")
            if not preview_id:
                return self._error_result("docs_update", "PREVIEW_ID_REQUIRED",
                                          "docs_update apply 需要 preview_id。")
            doc_params["preview_id"] = preview_id
            result = self.project_docs.handle("apply", doc_params)
            steps = [self._step("docs_update", "manage_project_docs", "apply", result, STEP_RISK_WRITE)]

            changed_files = self._extract_changed_files(result)
            next_actions = []
            if result.get("ok"):
                next_actions.append({
                    "action": "manage_git_commit.suggest_commit_message",
                    "label": "建议 commit message",
                    "tool": "manage_git_commit",
                    "params": {"action": "suggest_commit_message"},
                    "risk_level": "info",
                    "requires_confirmation": False,
                })
                next_actions.append({
                    "action": "manage_git_commit.commit_workflow_preview",
                    "label": "提交预览",
                    "tool": "manage_git_commit",
                    "params": {"action": "commit_workflow_preview"},
                    "risk_level": "preview",
                    "requires_confirmation": True,
                })

            return self._build_core_result(
                workflow="docs_update",
                steps=steps,
                risk_level=STEP_RISK_WRITE,
                status="succeeded" if result.get("ok") else "failed",
                requires_confirmation=False,
                next_actions=next_actions,
                changed_files=changed_files,
                result=result,
            )

        return self._error_result("docs_update", "ACTION_NOT_SUPPORTED",
                                  f"不支持 docs_action={resolved_action}。")

    # ================================================================
    # git_commit
    # ================================================================

    def _workflow_git_commit(self, params: dict[str, Any]) -> dict[str, Any]:
        phase = params.get("phase", "preview")

        style = params.get("style", "runner_version")
        scope_hint = params.get("scope_hint")
        message = params.get("message")
        preview_id = params.get("preview_id")

        if phase in ("inspect", "status"):
            readiness = self.git_commit.readiness(include_diff_summary=True, max_diff_chars=40000)
            suggest = self.git_commit.suggest_commit_message(
                include_diff_summary=True,
                max_diff_chars=40000,
                style=style,
                scope_hint=scope_hint,
            )
            result = {
                "ok": readiness.get("ok", False) and suggest.get("ok", False),
                "readiness": readiness,
                "suggestions": suggest,
            }
            steps = [
                self._step("git_commit", "manage_git_commit", "readiness", readiness, STEP_RISK_INFO),
                self._step("git_commit", "manage_git_commit", "suggest_commit_message", suggest, STEP_RISK_INFO),
            ]
            return self._build_core_result(
                workflow="git_commit",
                steps=steps,
                risk_level=STEP_RISK_INFO,
                status="succeeded" if result.get("ok") else "failed",
                requires_confirmation=False,
                result=result,
            )

        if phase == "preview":
            result = self.git_commit.commit_workflow_preview(
                message=message.strip() if isinstance(message, str) else None,
                include_diff_summary=True,
                max_diff_chars=40000,
                style=style,
                scope_hint=scope_hint,
            )
            steps = [self._step("git_commit", "manage_git_commit", "commit_workflow_preview", result, STEP_RISK_PREVIEW)]

            preview_ids = self._extract_preview_ids(result)
            requires_confirmation = result.get("ok", False) and bool(preview_ids)

            next_actions = []
            if preview_ids:
                next_actions.append({
                    "action": "confirm_controlled_commit_preview",
                    "label": "确认受控提交预览",
                    "reason": "使用 manage_git_commit action=commit 应用已生成的 commit preview，不执行任意 shell，不 git add .",
                    "tool": "manage_git_commit",
                    "params": {"action": "commit", "preview_id": preview_ids[0]},
                    "risk_level": "commit",
                    "requires_confirmation": True,
                })

            return self._build_core_result(
                workflow="git_commit",
                steps=steps,
                risk_level=STEP_RISK_PREVIEW,
                status="preview_ready" if preview_ids else ("failed" if not result.get("ok") else "succeeded"),
                requires_confirmation=requires_confirmation,
                next_actions=next_actions,
                preview_ids=preview_ids,
                result=result,
            )

        if phase == "commit":
            if not preview_id:
                return self._error_result("git_commit", "PREVIEW_ID_REQUIRED",
                                          "commit 需要 preview_id。")
            result = self.git_commit.commit(
                preview_id=preview_id,
                message=message.strip() if isinstance(message, str) else None,
            )
            steps = [self._step("git_commit", "manage_git_commit", "commit", result, STEP_RISK_COMMIT)]

            changed_files = self._extract_changed_files(result)

            return self._build_core_result(
                workflow="git_commit",
                steps=steps,
                risk_level=STEP_RISK_COMMIT,
                status="succeeded" if result.get("ok") else "failed",
                requires_confirmation=False,
                next_actions=[],
                changed_files=changed_files,
                result=result,
            )

        return self._error_result("git_commit", "PHASE_NOT_SUPPORTED",
                                  f"不支持 phase={phase}。支持：inspect、status、preview、commit。")

    # ================================================================
    # git_restore_file
    # ================================================================

    def _workflow_git_restore_file(self, params: dict[str, Any]) -> dict[str, Any]:
        phase = params.get("phase", "preview")

        if phase == "preview":
            commit = params.get("commit")
            file = params.get("file")
            if not commit or not file:
                return self._error_result("git_restore_file", "COMMIT_AND_FILE_REQUIRED",
                                          "preview 需要 commit 和 file 参数。")

            hist_params = {
                "action": "restore_file_preview",
                "commit": commit,
                "file": file,
                "reason": params.get("reason"),
            }
            result = self.git_history.handle("restore_file_preview", hist_params)
            steps = [self._step("git_restore_file", "manage_git_history", "restore_file_preview", result, STEP_RISK_PREVIEW)]

            preview_ids = self._extract_preview_ids(result)
            requires_confirmation = result.get("ok", False) and bool(preview_ids)

            next_actions = []
            if preview_ids:
                next_actions.append({
                    "action": "git_restore_file.apply",
                    "label": "应用文件恢复",
                    "tool": "run_mcp_workflow",
                    "params": {"workflow": "git_restore_file", "phase": "apply", "preview_id": preview_ids[0]},
                    "risk_level": "write",
                    "requires_confirmation": True,
                })

            return self._build_core_result(
                workflow="git_restore_file",
                steps=steps,
                risk_level=STEP_RISK_PREVIEW,
                status="preview_ready" if preview_ids else ("failed" if not result.get("ok") else "succeeded"),
                requires_confirmation=requires_confirmation,
                next_actions=next_actions,
                preview_ids=preview_ids,
                result=result,
            )

        if phase == "apply":
            preview_id = params.get("preview_id")
            if not preview_id:
                return self._error_result("git_restore_file", "PREVIEW_ID_REQUIRED",
                                          "apply 需要 preview_id。")
            hist_params = {
                "action": "restore_file_apply",
                "preview_id": preview_id,
            }
            result = self.git_history.handle("restore_file_apply", hist_params)
            steps = [self._step("git_restore_file", "manage_git_history", "restore_file_apply", result, STEP_RISK_WRITE)]

            changed_files = self._extract_changed_files(result)
            next_actions = []
            if result.get("ok"):
                next_actions.append({
                    "action": "manage_git_commit.suggest_commit_message",
                    "label": "建议 commit message",
                    "tool": "manage_git_commit",
                    "params": {"action": "suggest_commit_message"},
                    "risk_level": "info",
                    "requires_confirmation": False,
                })
                next_actions.append({
                    "action": "manage_git_commit.commit_workflow_preview",
                    "label": "提交预览",
                    "tool": "manage_git_commit",
                    "params": {"action": "commit_workflow_preview"},
                    "risk_level": "preview",
                    "requires_confirmation": True,
                })

            return self._build_core_result(
                workflow="git_restore_file",
                steps=steps,
                risk_level=STEP_RISK_WRITE,
                status="succeeded" if result.get("ok") else "failed",
                requires_confirmation=False,
                next_actions=next_actions,
                changed_files=changed_files,
                result=result,
            )

        return self._error_result("git_restore_file", "PHASE_NOT_SUPPORTED",
                                  f"不支持 phase={phase}。支持：preview、apply。")

    # ================================================================
    # git_revert
    # ================================================================

    def _workflow_git_revert(self, params: dict[str, Any]) -> dict[str, Any]:
        phase = params.get("phase", "preview")

        if phase == "preview":
            commit = params.get("commit")
            if not commit:
                return self._error_result("git_revert", "COMMIT_REQUIRED",
                                          "preview 需要 commit 参数。")

            hist_params = {
                "action": "revert_preview",
                "commit": commit,
                "max_chars": params.get("max_chars"),
                "reason": params.get("reason"),
            }
            result = self.git_history.handle("revert_preview", hist_params)
            steps = [self._step("git_revert", "manage_git_history", "revert_preview", result, STEP_RISK_PREVIEW)]

            preview_ids = self._extract_preview_ids(result)
            requires_confirmation = result.get("ok", False) and bool(preview_ids) and result.get("can_apply", False)

            next_actions = []
            if preview_ids and result.get("can_apply"):
                next_actions.append({
                    "action": "git_revert.apply",
                    "label": "应用撤销",
                    "tool": "run_mcp_workflow",
                    "params": {"workflow": "git_revert", "phase": "apply", "preview_id": preview_ids[0]},
                    "risk_level": "write",
                    "requires_confirmation": True,
                })

            return self._build_core_result(
                workflow="git_revert",
                steps=steps,
                risk_level=STEP_RISK_PREVIEW,
                status="preview_ready" if preview_ids else ("failed" if not result.get("ok") else "succeeded"),
                requires_confirmation=requires_confirmation,
                next_actions=next_actions,
                preview_ids=preview_ids,
                blockers=self._extract_blockers(result),
                warnings=self._extract_warnings(result),
                result=result,
            )

        if phase == "apply":
            preview_id = params.get("preview_id")
            if not preview_id:
                return self._error_result("git_revert", "PREVIEW_ID_REQUIRED",
                                          "apply 需要 preview_id。")
            hist_params = {
                "action": "revert_apply",
                "preview_id": preview_id,
            }
            result = self.git_history.handle("revert_apply", hist_params)
            steps = [self._step("git_revert", "manage_git_history", "revert_apply", result, STEP_RISK_WRITE)]

            changed_files = self._extract_changed_files(result)

            next_actions = []
            if result.get("ok"):
                next_actions.append({
                    "action": "manage_git_commit.suggest_commit_message",
                    "label": "建议 commit message",
                    "tool": "manage_git_commit",
                    "params": {"action": "suggest_commit_message"},
                    "risk_level": "info",
                    "requires_confirmation": False,
                })

            return self._build_core_result(
                workflow="git_revert",
                steps=steps,
                risk_level=STEP_RISK_WRITE,
                status="succeeded" if result.get("ok") or result.get("error_code") == "REVERT_CONFLICT" else "failed",
                requires_confirmation=False,
                next_actions=next_actions,
                changed_files=changed_files,
                blockers=self._extract_blockers(result),
                warnings=self._extract_warnings(result),
                result=result,
            )

        return self._error_result("git_revert", "PHASE_NOT_SUPPORTED",
                                  f"不支持 phase={phase}。支持：preview、apply。")

    # ================================================================
    # git_undo_version
    # ================================================================

    def _workflow_git_undo_version(self, params: dict[str, Any]) -> dict[str, Any]:
        for dangerous in ("reset", "checkout", "rebase", "stash", "branch", "merge", "switch", "push", "pull", "force"):
            if dangerous in params and params[dangerous] is not None and params[dangerous] is not False:
                return self._error_result(
                    "git_undo_version", "UNSUPPORTED_UNDO_MODE",
                    f"撤销版本向导不支持 {dangerous} 操作。"
                    "该向导只支持受控 revert（撤销整个版本）和受控 restore（恢复文件）。"
                    "如需执行危险 Git 操作，请使用终端直接操作。",
                )

        phase = params.get("phase", "inspect")

        if phase == "inspect":
            return self._git_undo_version_inspect(params)

        if phase == "preview":
            return self._git_undo_version_preview(params)

        if phase == "apply":
            return self._git_undo_version_apply(params)

        return self._error_result("git_undo_version", "INVALID_PHASE",
                                  f"不支持 phase={phase}。支持：inspect、preview、apply。")

    def _git_undo_version_inspect(self, params: dict[str, Any]) -> dict[str, Any]:
        commit = params.get("commit")
        file = params.get("file")
        max_chars = params.get("max_chars")

        if commit and file:
            return self._error_result("git_undo_version", "INVALID_PARAMS",
                                      "commit 和 file 不能同时传入。请选择撤销整个版本（commit）或恢复单个文件（commit + file）。")

        if commit:
            show_params = {"action": "show", "commit": commit, "max_chars": max_chars}
            show_result = self.git_history.handle("show", show_params)
            if not show_result.get("ok"):
                return self._error_result("git_undo_version", "INVALID_COMMIT",
                                          f"无法读取提交 {commit}。")
            steps = [self._step("git_undo_version", "manage_git_history", "show", show_result, STEP_RISK_INFO)]
            return self._build_core_result(
                workflow="git_undo_version",
                steps=steps,
                risk_level=STEP_RISK_INFO,
                status="succeeded" if show_result.get("ok") else "failed",
                requires_confirmation=False,
                result={
                    "mode": "revert_commit",
                    "selected_commit": show_result,
                    "message": f"已定位到提交 {commit}。可生成撤销预览来撤销此版本的影响。",
                    "recommended_next_action": f"run_mcp_workflow workflow=git_undo_version phase=preview commit={commit}",
                },
            )

        log_params = {"action": "log", "limit": params.get("limit", 12)}
        log_result = self.git_history.handle("log", log_params)
        if not log_result.get("ok"):
            return self._error_result("git_undo_version", "GIT_UNDO_PREVIEW_FAILED",
                                      "读取提交历史失败。")
        candidates = log_result.get("commits", log_result.get("data", {}).get("commits", []))
        mode = "restore_file" if file else "select_commit"
        msg = (
            "请选择要撤销的版本。每个候选版本都包含影响文件列表，确认后生成撤销预览。"
            if not file else
            "已指定要恢复的文件。请选择目标版本，确认后将生成文件恢复预览。"
        )
        steps = [self._step("git_undo_version", "manage_git_history", "log", log_result, STEP_RISK_INFO)]
        return self._build_core_result(
            workflow="git_undo_version",
            steps=steps,
            risk_level=STEP_RISK_INFO,
            status="succeeded",
            requires_confirmation=False,
            result={
                "mode": mode,
                "candidates": candidates,
                "selected_file": file or None,
                "message": msg,
                "recommended_next_action": "再次调用 git_undo_version，传入 commit 和可选的 file 参数。",
            },
        )

    def _git_undo_version_preview(self, params: dict[str, Any]) -> dict[str, Any]:
        commit = params.get("commit")
        if not commit:
            return self._error_result("git_undo_version", "INVALID_COMMIT",
                                      "preview 阶段需要 commit 参数。")

        file = params.get("file")
        reason = params.get("reason")

        if file:
            hist_params = {
                "action": "restore_file_preview",
                "commit": commit,
                "file": file,
                "reason": reason,
            }
            result = self.git_history.handle("restore_file_preview", hist_params)
            steps = [self._step("git_undo_version", "manage_git_history", "restore_file_preview", result, STEP_RISK_PREVIEW)]
            preview_ids = self._extract_preview_ids(result)
            requires_confirmation = bool(result.get("ok")) and bool(preview_ids)
            next_actions = []
            if preview_ids:
                next_actions.append({
                    "action": "git_undo_version.apply",
                    "label": "确认恢复文件",
                    "tool": "run_mcp_workflow",
                    "params": {"workflow": "git_undo_version", "phase": "apply", "preview_id": preview_ids[0], "mode": "restore_file"},
                    "risk_level": "write",
                    "requires_confirmation": True,
                })
            return self._build_core_result(
                workflow="git_undo_version",
                steps=steps,
                risk_level=STEP_RISK_PREVIEW,
                status="preview_ready" if preview_ids else ("failed" if not result.get("ok") else "succeeded"),
                requires_confirmation=requires_confirmation,
                next_actions=next_actions,
                preview_ids=preview_ids,
                result={
                    "mode": "restore_file",
                    "commit": commit,
                    "file": file,
                    "message": "文件恢复预览已生成，确认后才会应用。",
                    "recommended_next_action": f"run_mcp_workflow workflow=git_undo_version phase=apply preview_id={preview_ids[0]} mode=restore_file" if preview_ids else "",
                },
            )

        hist_params = {
            "action": "revert_preview",
            "commit": commit,
            "max_chars": params.get("max_chars"),
            "reason": reason,
        }
        result = self.git_history.handle("revert_preview", hist_params)
        steps = [self._step("git_undo_version", "manage_git_history", "revert_preview", result, STEP_RISK_PREVIEW)]
        preview_ids = self._extract_preview_ids(result)
        requires_confirmation = bool(result.get("ok")) and bool(preview_ids) and bool(result.get("can_apply", False))
        next_actions = []
        if preview_ids and result.get("can_apply"):
            next_actions.append({
                "action": "git_undo_version.apply",
                "label": "确认撤销版本",
                "tool": "run_mcp_workflow",
                "params": {"workflow": "git_undo_version", "phase": "apply", "preview_id": preview_ids[0]},
                "risk_level": "write",
                "requires_confirmation": True,
            })
        affected_files = self._extract_changed_files(result)
        return self._build_core_result(
            workflow="git_undo_version",
            steps=steps,
            risk_level=STEP_RISK_PREVIEW,
            status="preview_ready" if preview_ids else ("failed" if not result.get("ok") else "succeeded"),
            requires_confirmation=requires_confirmation,
            next_actions=next_actions,
            preview_ids=preview_ids,
            result={
                "mode": "revert_commit",
                "commit": commit,
                "affected_files": affected_files,
                "message": "已生成撤销预览，确认后才会应用。",
                "recommended_next_action": f"run_mcp_workflow workflow=git_undo_version phase=apply preview_id={preview_ids[0]}" if preview_ids else "",
            },
        )

    def _git_undo_version_apply(self, params: dict[str, Any]) -> dict[str, Any]:
        preview_id = params.get("preview_id")
        if not preview_id:
            return self._error_result("git_undo_version", "INVALID_PREVIEW_ID",
                                      "apply 阶段需要 preview_id 参数。不允许直接根据 commit 执行。")

        mode = params.get("mode", "")
        if mode == "restore_file":
            hist_params = {"action": "restore_file_apply", "preview_id": preview_id}
        else:
            hist_params = {"action": "revert_apply", "preview_id": preview_id}
        result = self.git_history.handle(hist_params["action"], hist_params)
        tool_action = hist_params["action"]
        steps = [self._step("git_undo_version", "manage_git_history", tool_action, result, STEP_RISK_WRITE)]
        changed_files = self._extract_changed_files(result)
        next_actions = []
        if result.get("ok"):
            commit_hash = result.get("commit_hash") or result.get("data", {}).get("commit_hash")
            undo_msg = ("文件已恢复到预览指定版本。" if mode == "restore_file"
                        else "撤销已应用。")
            if commit_hash:
                undo_msg += f" 已生成 revert commit：{commit_hash}。"
            else:
                undo_msg += " 工作区已更新，请审查并提交。"
            next_actions.append({
                "action": "manage_git_commit.suggest_commit_message",
                "label": "建议 commit message",
                "tool": "manage_git_commit",
                "params": {"action": "suggest_commit_message"},
                "risk_level": "info",
                "requires_confirmation": False,
            })
            return self._build_core_result(
                workflow="git_undo_version",
                steps=steps,
                risk_level=STEP_RISK_WRITE,
                status="succeeded",
                requires_confirmation=False,
                next_actions=next_actions,
                changed_files=changed_files,
                result={
                    "mode": mode or "revert_commit",
                    "commit_hash": commit_hash,
                    "message": undo_msg,
                },
            )

        return self._build_core_result(
            workflow="git_undo_version",
            steps=steps,
            risk_level=STEP_RISK_WRITE,
            status="failed",
            requires_confirmation=False,
            changed_files=changed_files,
            blockers=self._extract_blockers(result),
            warnings=self._extract_warnings(result),
            result={
                "mode": mode or "revert_commit",
                "error_code": "GIT_UNDO_APPLY_FAILED",
                "message": "撤销应用失败。",
            },
        )

    # ================================================================
    # prompt_to_plan
    # ================================================================

    def _workflow_prompt_to_plan(self, params: dict[str, Any]) -> dict[str, Any]:
        phase = str(params.get("phase", "")).strip().lower()

        if phase == "preview":
            return self._prompt_to_plan_preview(params)
        if phase == "apply":
            return self._prompt_to_plan_apply(params)
        if phase == "plan_preview":
            return self._prompt_to_plan_plan_preview(params)
        if phase == "plan_apply":
            return self._prompt_to_plan_plan_apply(params)
        if phase == "apply_all":
            return self._prompt_to_plan_apply_all(params)
        if phase == "run_preview":
            return self._prompt_to_plan_run_preview(params)
        if phase == "run":
            return self._prompt_to_plan_run(params)
        return self._error_result(
            "prompt_to_plan", "PHASE_NOT_SUPPORTED",
            f"不支持 phase={phase}。支持：preview、apply、plan_preview、plan_apply、apply_all、run_preview、run。",
        )

    def _prompt_to_plan_plan_metadata(self, params: dict[str, Any]) -> dict[str, Any]:
        metadata: dict[str, Any] = {}
        for field in (
            "insert_after",
            "version",
            "name",
            "description",
            "allowed_files",
            "forbidden_files",
            "acceptance_commands",
            "manual_acceptance",
            "out_of_scope",
            "context_files",
            "execution",
        ):
            if field in params and params.get(field) is not None:
                metadata[field] = params.get(field)
        return metadata

    def _prompt_to_plan_missing_required_plan_metadata(self, metadata: dict[str, Any]) -> list[str]:
        missing: list[str] = []
        for field in ("name", "description"):
            value = metadata.get(field)
            if not isinstance(value, str) or not value.strip():
                missing.append(field)
        if not metadata.get("allowed_files"):
            missing.append("allowed_files")
        if not metadata.get("acceptance_commands"):
            missing.append("acceptance_commands")
        return missing

    def _prompt_to_plan_preview(self, params: dict[str, Any]) -> dict[str, Any]:
        version = params.get("version")
        content = params.get("content")
        if not isinstance(version, str) or not version.strip():
            return self._error_result("prompt_to_plan", "VERSION_REQUIRED", "preview 需要非空 version。")
        if not isinstance(content, str) or not content.strip():
            return self._error_result("prompt_to_plan", "CONTENT_REQUIRED", "preview 需要非空 content。")
        pending_info = self._get_pending_queue_info()
        pending_warnings = self._build_prompt_pending_warnings(pending_info)
        plan_metadata = self._prompt_to_plan_plan_metadata(params)
        from runner.mcp_prompt_file import MCPPromptFileManager
        mgr = MCPPromptFileManager(self.project_root)
        result = mgr.handle("preview", {
            "version": version.strip(),
            "content": content,
            "overwrite": params.get("overwrite", False),
            "reason": params.get("reason"),
            "write_front_matter": False,
            "plan_metadata": plan_metadata,
        })
        steps = [self._step("prompt_to_plan", "manage_prompt_file", "preview", result, STEP_RISK_PREVIEW)]
        preview_ids = self._extract_preview_ids(result)
        requires_confirmation = result.get("ok", False) and bool(preview_ids)
        next_actions = []
        if preview_ids:
            next_actions.append({
                "action": "prompt_to_plan.apply_all",
                "label": "保存 prompt 并登记到 plan（一键完成）",
                "tool": "run_mcp_workflow",
                "params": {"workflow": "prompt_to_plan", "phase": "apply_all", "preview_id": preview_ids[0]},
                "risk_level": "write",
                "requires_confirmation": True,
            })
        if pending_info.get("pending_count", 0) > 0:
            next_actions.append({
                "action": "project_status.inspect",
                "label": "检查待执行版本队列",
                "tool": "run_mcp_workflow",
                "params": {"workflow": "project_status", "phase": "inspect"},
                "risk_level": "info",
                "requires_confirmation": False,
            })
        return self._build_core_result(
            workflow="prompt_to_plan",
            steps=steps,
            risk_level=STEP_RISK_PREVIEW,
            status="preview_ready" if preview_ids else ("failed" if not result.get("ok") else "succeeded"),
            requires_confirmation=requires_confirmation,
            next_actions=next_actions,
            preview_ids=preview_ids,
            warnings=pending_warnings,
            result={
                **(result if isinstance(result, dict) else {}),
                "pending_queue": pending_info,
            },
        )

    def _get_pending_queue_info(self) -> dict[str, Any]:
        try:
            status = self._planning_bridge.get_runner_status(self.project_root)
        except Exception:
            return {
                "pending_count": 0,
                "pending_versions": [],
                "next_not_started_version": None,
                "has_pending_versions": False,
            }
        pending_versions = status.get("pending_versions")
        if not isinstance(pending_versions, list):
            pending_versions = []
        try:
            pending_count = int(status.get("pending_count", len(pending_versions)))
        except Exception:
            pending_count = len(pending_versions)
        next_not_started_version = status.get("next_not_started_version")
        return {
            "pending_count": pending_count,
            "pending_versions": pending_versions,
            "next_not_started_version": next_not_started_version,
            "has_pending_versions": pending_count > 0,
        }

    def _build_prompt_pending_warnings(self, pending_info: dict[str, Any]) -> list[str]:
        pending_count = int(pending_info.get("pending_count", 0) or 0)
        if pending_count <= 0:
            return []
        next_not_started = str(pending_info.get("next_not_started_version") or "").strip()
        pending_versions = pending_info.get("pending_versions")
        if not isinstance(pending_versions, list):
            pending_versions = []
        if pending_count == 1:
            if next_not_started:
                return [f"当前存在 1 个待执行版本：{next_not_started}。建议先更新该版本，或确认在该版本后追加新任务。"]
            return ["当前存在 1 个待执行版本。建议先更新该版本，或确认在该版本后追加新任务。"]
        queue_versions: list[str] = []
        for item in pending_versions:
            if isinstance(item, dict):
                version = str(item.get("version") or "").strip()
                if version:
                    queue_versions.append(version)
        if queue_versions:
            return [f"当前存在 {pending_count} 个待执行版本队列：{', '.join(queue_versions[:6])}。先确认顺序后再新增任务。"]
        return [f"当前存在 {pending_count} 个待执行版本队列。先确认顺序后再新增任务。"]

    def _prompt_to_plan_apply(self, params: dict[str, Any]) -> dict[str, Any]:
        preview_id = params.get("preview_id")
        if not isinstance(preview_id, str) or not preview_id.strip():
            return self._error_result("prompt_to_plan", "PREVIEW_ID_REQUIRED", "apply 需要非空 preview_id。")
        from runner.mcp_prompt_file import MCPPromptFileManager
        mgr = MCPPromptFileManager(self.project_root)
        result = mgr.handle("apply", {"preview_id": preview_id.strip()})
        steps = [self._step("prompt_to_plan", "manage_prompt_file", "apply", result, STEP_RISK_WRITE)]
        changed_files = self._extract_changed_files(result)
        next_actions = []
        if result.get("ok"):
            prompt_file = os.path.basename(result.get("target_file", "")) if result.get("target_file") else ""
            if prompt_file:
                next_actions.append({
                    "action": "prompt_to_plan.plan_preview",
                    "label": "从 prompt 文件生成 plan patch preview",
                    "tool": "run_mcp_workflow",
                    "params": {"workflow": "prompt_to_plan", "phase": "plan_preview", "prompt_file": prompt_file},
                    "risk_level": "preview",
                    "requires_confirmation": True,
                })
        return self._build_core_result(
            workflow="prompt_to_plan",
            steps=steps,
            risk_level=STEP_RISK_WRITE,
            status="succeeded" if result.get("ok") else "failed",
            requires_confirmation=False,
            next_actions=next_actions,
            changed_files=changed_files,
            result=result,
        )

    def _prompt_to_plan_plan_preview(self, params: dict[str, Any]) -> dict[str, Any]:
        prompt_file = params.get("prompt_file")
        if not isinstance(prompt_file, str) or not prompt_file.strip():
            return self._error_result("prompt_to_plan", "PROMPT_FILE_REQUIRED", "plan_preview 需要非空 prompt_file。")
        prompt_file = prompt_file.strip()
        if "/" in prompt_file or "\\" in prompt_file:
            return self._error_result("prompt_to_plan", "PROMPT_FILE_UNSAFE",
                                      "prompt_file 只接受文件名，不接受路径。")
        insert_params = {"prompt_file": prompt_file}
        insert_params.update(self._prompt_to_plan_plan_metadata(params))
        result = self._run_plan_version_action("insert_from_prompt_file_preview", insert_params)
        steps = [self._step("prompt_to_plan", "manage_plan_version", "insert_from_prompt_file_preview", result, STEP_RISK_PREVIEW)]
        preview_ids = self._extract_preview_ids(result)
        requires_confirmation = result.get("ok", False) and bool(preview_ids)
        next_actions = []
        if preview_ids:
            next_actions.append({
                "action": "prompt_to_plan.plan_apply",
                "label": "应用 plan patch",
                "tool": "run_mcp_workflow",
                "params": {"workflow": "prompt_to_plan", "phase": "plan_apply", "patch_id": preview_ids[0]},
                "risk_level": "commit",
                "requires_confirmation": True,
            })
        return self._build_core_result(
            workflow="prompt_to_plan",
            steps=steps,
            risk_level=STEP_RISK_PREVIEW,
            status="preview_ready" if preview_ids else ("failed" if not result.get("ok") else "succeeded"),
            requires_confirmation=requires_confirmation,
            next_actions=next_actions,
            preview_ids=preview_ids,
            result=result,
        )

    def _prompt_to_plan_plan_apply(self, params: dict[str, Any]) -> dict[str, Any]:
        patch_id = params.get("patch_id")
        if not isinstance(patch_id, str) or not patch_id.strip():
            return self._error_result("prompt_to_plan", "PATCH_ID_REQUIRED", "plan_apply 需要非空 patch_id。")
        result = self._run_plan_version_action("apply_preview", {"patch_id": patch_id.strip()})
        steps = [self._step("prompt_to_plan", "manage_plan_version", "apply_preview", result, STEP_RISK_COMMIT)]
        changed_files = self._extract_changed_files(result)
        next_actions = []
        if result.get("ok"):
            next_actions.append({
                "action": "prompt_to_plan.run_preview",
                "label": "生成执行器运行预览（推荐）",
                "tool": "run_mcp_workflow",
                "params": {"workflow": "prompt_to_plan", "phase": "run_preview"},
                "risk_level": "preview",
                "requires_confirmation": False,
            })
        return self._build_core_result(
            workflow="prompt_to_plan",
            steps=steps,
            risk_level=STEP_RISK_COMMIT,
            status="succeeded" if result.get("ok") else "failed",
            requires_confirmation=False,
            next_actions=next_actions,
            changed_files=changed_files,
            result=result,
        )

    # ── prompt_to_plan apply_all ──

    def _prompt_to_plan_apply_all(self, params: dict[str, Any]) -> dict[str, Any]:
        preview_id = params.get("preview_id")
        if not isinstance(preview_id, str) or not preview_id.strip():
            return self._error_result("prompt_to_plan", "PREVIEW_ID_REQUIRED", "apply_all 需要非空 preview_id。")
        steps: list[dict[str, Any]] = []
        # Step 1: manage_prompt_file apply
        from runner.mcp_prompt_file import MCPPromptFileManager
        mgr = MCPPromptFileManager(self.project_root)
        apply_result = mgr.handle("apply", {"preview_id": preview_id.strip()})
        steps.append(self._step("prompt_to_plan", "manage_prompt_file", "apply", apply_result, STEP_RISK_WRITE))
        if not apply_result.get("ok"):
            return self._apply_all_partial(steps, "PROMPT_FILE_APPLY_FAILED",
                                           f"prompt_file apply 失败：{apply_result.get('message', '未知错误')}")
        prompt_file = None
        target_file = apply_result.get("target_file")
        if isinstance(target_file, str) and target_file.strip():
            prompt_file = os.path.basename(target_file)
        if not prompt_file:
            return self._apply_all_partial(steps, "PROMPT_FILE_MISSING",
                                           "prompt_file apply 返回中缺少 prompt_file。")
        # Step 2: manage_plan_version insert_from_prompt_file_preview
        plan_metadata = apply_result.get("plan_metadata")
        if not isinstance(plan_metadata, dict):
            plan_metadata = {}
        missing_metadata = self._prompt_to_plan_missing_required_plan_metadata(plan_metadata)
        if missing_metadata:
            return self._apply_all_partial(
                steps,
                "PLAN_METADATA_REQUIRED",
                f"apply_all 需要 GPTs 显式提供版本元数据：{', '.join(missing_metadata)}。",
                partial=True,
            )
        insert_params = {"prompt_file": prompt_file}
        insert_params.update(plan_metadata)
        insert_result = self._run_plan_version_action("insert_from_prompt_file_preview", insert_params)
        steps.append(self._step("prompt_to_plan", "manage_plan_version", "insert_from_prompt_file_preview",
                                insert_result, STEP_RISK_PREVIEW))
        if not insert_result.get("ok"):
            return self._apply_all_partial(steps, "PLAN_INSERT_PREVIEW_FAILED",
                                           f"plan insert preview 失败：{insert_result.get('message', '未知错误')}",
                                           partial=True)
        patch_id = insert_result.get("patch_id") or insert_result.get("preview_id")
        if not isinstance(patch_id, str) or not patch_id.strip():
            return self._apply_all_partial(steps, "PATCH_ID_MISSING",
                                           "plan insert preview 未返回 patch_id。", partial=True)
        # Step 3: manage_plan_version apply_preview
        apply_patch_result = self._run_plan_version_action("apply_preview", {"patch_id": patch_id.strip()})
        steps.append(self._step("prompt_to_plan", "manage_plan_version", "apply_preview",
                                apply_patch_result, STEP_RISK_COMMIT))
        if not apply_patch_result.get("ok"):
            return self._apply_all_partial(steps, "PLAN_APPLY_FAILED",
                                           f"plan apply 失败：{apply_patch_result.get('message', '未知错误')}",
                                           partial=True)
        changed_files = self._extract_changed_files(apply_patch_result)
        inserted_version = apply_patch_result.get("inserted_version") or apply_patch_result.get("updated_version")
        return self._build_core_result(
            workflow="prompt_to_plan",
            steps=steps,
            risk_level=STEP_RISK_WRITE,
            status="succeeded",
            requires_confirmation=False,
            next_actions=[{
                "action": "prompt_to_plan.run_preview",
                "label": "生成执行器运行预览（推荐）",
                "tool": "run_mcp_workflow",
                "params": {"workflow": "prompt_to_plan", "phase": "run_preview"},
                "risk_level": "preview",
                "requires_confirmation": False,
            }],
            changed_files=changed_files,
            result={
                "prompt_file": prompt_file,
                "patch_id": patch_id,
                "inserted_version": inserted_version,
            },
            phase="apply_all",
        )

    def _apply_all_partial(
        self, steps: list[dict[str, Any]],
        error_code: str, message: str,
        partial: bool = False,
    ) -> 'CoreResult':
        return CoreResult(
            ok=False,
            workflow="prompt_to_plan",
            risk_level=STEP_RISK_BLOCKED,
            phase="apply_all",
            status="partial" if partial else "failed",
            partial=partial,
            error_code=error_code,
            message=message,
            steps=steps,
            changed_files=[],
            preview_ids=[],
            next_actions=[],
            requires_confirmation=False,
            blockers=[message],
            warnings=[],
            result=None,
        )
    def _prompt_to_plan_run_preview(self, params: dict[str, Any]) -> dict[str, Any]:
        provider = self._normalize_provider(params.get("provider")) or "codex"
        manager = self._executor_workflow_factory(self.project_root)
        steps: list[dict[str, Any]] = []
        preflight = manager.handle("preflight", {"provider": provider, "execution_mode": "run"})
        steps.append(self._step("prompt_to_plan", "manage_executor_workflow", "preflight",
                                preflight, STEP_RISK_INFO))
        if not preflight.get("ok") or preflight.get("preflight_blocked"):
            return self._build_core_result(
                workflow="prompt_to_plan",
                steps=steps,
                risk_level=STEP_RISK_BLOCKED,
                status="blocked",
                requires_confirmation=False,
                result=preflight,
                phase="run_preview",
            )
        preview = manager.handle("run_once_preview", {"provider": provider, "execution_mode": "run"})
        steps.append(self._step("prompt_to_plan", "manage_executor_workflow", "run_once_preview",
                                preview, STEP_RISK_PREVIEW))
        preview_id_value = preview.get("preview_id")
        preview_ids = self._extract_preview_ids(preview)
        next_actions = []
        if preview_ids:
            next_actions.append({
                "action": "prompt_to_plan.run",
                "label": "确认运行执行器",
                "tool": "run_mcp_workflow",
                "params": {"workflow": "prompt_to_plan", "phase": "run", "preview_id": preview_ids[0], "provider": provider},
                "risk_level": "write",
                "requires_confirmation": True,
            })
        return self._build_core_result(
            workflow="prompt_to_plan",
            steps=steps,
            risk_level=STEP_RISK_PREVIEW,
            status="preview_ready" if preview_ids else ("failed" if not preview.get("ok") else "succeeded"),
            requires_confirmation=False,
            next_actions=next_actions,
            preview_ids=preview_ids,
            blockers=self._extract_blockers(preview),
            warnings=self._extract_warnings(preview),
            result={
                "provider": provider,
                "preview_id": preview_id_value,
                **(preview if isinstance(preview, dict) else {}),
            },
            phase="run_preview",
        )

    # ── prompt_to_plan run ──

    def _prompt_to_plan_run(self, params: dict[str, Any]) -> dict[str, Any]:
        preview_id = params.get("preview_id")
        if not isinstance(preview_id, str) or not preview_id.strip():
            return self._error_result("prompt_to_plan", "PREVIEW_ID_REQUIRED", "run 需要非空 preview_id。")
        provider = self._normalize_provider(params.get("provider")) or "codex"
        manager = self._executor_workflow_factory(self.project_root)
        run_result = manager.handle("run_once", {
            "provider": provider,
            "preview_id": preview_id.strip(),
            "execution_mode": "run",
        })
        steps = [self._step("prompt_to_plan", "manage_executor_workflow", "run_once",
                            run_result, STEP_RISK_WRITE)]
        run_ok = bool(run_result.get("ok"))
        run_status = str(run_result.get("status") or "")
        run_id = str(run_result.get("run_id") or "")
        next_actions = []
        if run_ok and run_status == "started":
            next_actions.append({
                "action": "manage_executor_workflow.status",
                "label": "查看执行器运行进度",
                "tool": "manage_executor_workflow",
                "params": {"action": "status", "run_id": run_id},
                "risk_level": "info",
                "requires_confirmation": False,
            })
        return self._build_core_result(
            workflow="prompt_to_plan",
            steps=steps,
            risk_level=STEP_RISK_WRITE,
            status="started" if (run_ok and run_status == "started") else ("succeeded" if run_ok else "failed"),
            requires_confirmation=False,
            next_actions=next_actions,
            blockers=self._extract_blockers(run_result),
            warnings=self._extract_warnings(run_result),
            result={
                "provider": provider,
                "run_id": run_id,
                **(run_result if isinstance(run_result, dict) else {}),
            },
            phase="run",
        )

    def _run_plan_version_action(self, action: str, action_params: dict[str, Any]) -> dict[str, Any]:
        from runner.mcp_server import MCPPlanningBridgeServer
        server = MCPPlanningBridgeServer(self.project_root)
        full_params = {"action": action, **action_params}
        # We avoid _record_workflow_if_needed here because the workflow router
        # is the orchestrator; the underlying tool record is secondary.
        return server._tool_manage_plan_version(full_params)

    def _workflow_thin_governed_loop_preview(self, params: dict[str, Any]) -> 'CoreResult':
        from runner.thin_governed_loop import (
            THIN_LOOP_FAILED_CLOSED,
            THIN_LOOP_PASSED,
            run_stage_0_6_thin_governed_loop,
        )

        phase = str(params.get("phase") or "preview").strip().lower()
        if phase not in ("preview", "inspect", "status"):
            return self._error_result(
                "thin_governed_loop_preview",
                "PHASE_NOT_SUPPORTED",
                "thin_governed_loop_preview 只支持 preview / inspect / status；它不执行 apply、run、commit。",
            )

        requested_input_mode = self._thin_loop_requested_input_mode(params)
        warning = (
            "thin_governed_loop_preview is read-only evidence; it does not authorize "
            "executor dispatch, ReviewDecision, GateEvent, Delivery State transition, commit, or push."
        )
        if requested_input_mode == "template":
            return self._thin_loop_template_result(phase=phase, warnings=[warning])
        if requested_input_mode == "draft":
            return self._thin_loop_draft_result(params=params, phase=phase, warnings=[warning])

        inputs, input_mode, input_blockers = self._thin_loop_inputs_from_params(params)
        if input_blockers:
            invalid_input_mode = input_blockers == ["input_mode"]
            if invalid_input_mode:
                blocker_items = [{
                    "code": "thin_loop_invalid_input_mode",
                    "field": "input_mode",
                    "allowed_values": ["example", "template", "draft", "provided"],
                }]
                blocker_messages = ["input_mode 必须是 example、template、draft 或 provided。"]
            else:
                blocker_items = [
                    {"code": "thin_loop_input_missing", "field": field}
                    for field in input_blockers
                ]
                blocker_messages = [f"缺少真实输入对象：{field}" for field in input_blockers]
            thin_loop = {
                "thin_loop_status": THIN_LOOP_FAILED_CLOSED,
                "thin_loop_path": [
                    "repository_runtime_baseline",
                    "master_taskbook_anchor",
                    "stage_taskbook_registry",
                    "external_taskbook_import",
                    "execution_envelope",
                    "local_execution_receipt",
                    "reviewer_handoff_package",
                    "review_feedback_intake",
                ],
                "stage_results": {},
                "blockers": blocker_items,
                "authority_boundary": self._thin_loop_authority_boundary(),
                "delivery_state_accepted": False,
                "review_decision_created": False,
                "gate_event_emitted": False,
                "executor_dispatch_authorized": False,
            }
            return self._thin_loop_core_result(
                phase=phase,
                input_mode=input_mode,
                thin_loop=thin_loop,
                passed=False,
                blocker_messages=blocker_messages,
                warnings=[warning],
            )

        thin_loop = run_stage_0_6_thin_governed_loop(inputs)
        passed = thin_loop.get("thin_loop_status") == THIN_LOOP_PASSED
        blocker_messages = [
            self._thin_loop_blocker_text(blocker)
            for blocker in thin_loop.get("blockers", [])
        ]
        return self._thin_loop_core_result(
            phase=phase,
            input_mode=input_mode,
            thin_loop=thin_loop,
            passed=passed,
            blocker_messages=blocker_messages,
            warnings=[warning],
        )

    def _thin_loop_template_result(self, *, phase: str, warnings: list[str]) -> 'CoreResult':
        thin_loop = {
            "thin_loop_status": "thin_governed_loop_input_template_ready",
            "thin_loop_path": [
                "repository_runtime_baseline",
                "master_taskbook_anchor",
                "stage_taskbook_registry",
                "external_taskbook_import",
                "execution_envelope",
                "local_execution_receipt",
                "reviewer_handoff_package",
                "review_feedback_intake",
            ],
            "stage_results": {},
            "blockers": [],
            "authority_boundary": self._thin_loop_authority_boundary(),
            "delivery_state_accepted": False,
            "review_decision_created": False,
            "gate_event_emitted": False,
            "executor_dispatch_authorized": False,
        }
        return self._thin_loop_core_result(
            phase=phase,
            input_mode="template",
            thin_loop=thin_loop,
            passed=True,
            blocker_messages=[],
            warnings=warnings,
        )

    def _thin_loop_draft_result(self, *, params: dict[str, Any], phase: str, warnings: list[str]) -> 'CoreResult':
        generated_input_bundle = self._thin_loop_generated_input_bundle(params)
        codex_execution_packet = self._thin_loop_codex_execution_packet(generated_input_bundle, params)
        next_request_payload = {
            "workflow": "thin_governed_loop_preview",
            "phase": "preview",
            "project_name": params.get("project_name") or "<same managed project_name or route used for this draft call>",
            "input_mode": "provided",
            "thin_loop_inputs": generated_input_bundle,
        }
        thin_loop = {
            "thin_loop_status": "thin_governed_loop_input_draft_ready",
            "thin_loop_path": [
                "repository_runtime_baseline",
                "master_taskbook_anchor",
                "stage_taskbook_registry",
                "external_taskbook_import",
                "execution_envelope",
                "local_execution_receipt",
                "reviewer_handoff_package",
                "review_feedback_intake",
            ],
            "stage_results": {},
            "blockers": [],
            "evidence_provenance": {
                "schema_version": generated_input_bundle["evidence_provenance"]["schema_version"],
                "provenance_status": "draft_non_acceptable",
                "eligible_for_acceptance": False,
            },
            "authority_boundary": self._thin_loop_authority_boundary(),
            "delivery_state_accepted": False,
            "review_decision_created": False,
            "gate_event_emitted": False,
            "executor_dispatch_authorized": False,
        }
        return self._thin_loop_core_result(
            phase=phase,
            input_mode="draft",
            thin_loop=thin_loop,
            passed=True,
            blocker_messages=[],
            warnings=warnings,
            extra_result={
                "generated_input_bundle": generated_input_bundle,
                "next_request_payload": next_request_payload,
                "copy_paste_next_request": next_request_payload,
                "codex_execution_packet": codex_execution_packet,
                "copy_paste_codex_prompt": codex_execution_packet.get("copy_paste_codex_prompt"),
                "generated_input_bundle_summary": {
                    "bundle_kind": "draft_input_bundle",
                    "reusable_as": "thin_loop_inputs",
                    "submit_with_input_mode": "provided",
                    "copy_paste_field": "next_request_payload",
                    "direct_execution_packet_field": "codex_execution_packet",
                    "copy_paste_codex_prompt_field": "copy_paste_codex_prompt",
                    "provided_preview_is_optional_for_m0_m2": True,
                    "current_head": generated_input_bundle.get("current_head"),
                    "seed_fields_applied": generated_input_bundle.get("draft_seed_applied", []),
                    "seed_fields_ignored": generated_input_bundle.get("draft_seed_ignored", []),
                    "seed_fields_unknown": generated_input_bundle.get("draft_seed_unknown", []),
                    "object_fields": list(self._thin_loop_object_fields()),
                    "editable_before_submit": [
                        "external_taskbook_claim",
                        "execution_envelope",
                        "local_execution_receipt",
                        "review_feedback",
                        "evidence_provenance",
                    ],
                    "next_request_shape": {
                        "workflow": "thin_governed_loop_preview",
                        "phase": "preview",
                        "project_name": params.get("project_name") or "<same managed project_name or route used for this draft call>",
                        "input_mode": "provided",
                        "thin_loop_inputs": "<generated_input_bundle>",
                    },
                    "copy_paste_next_request_shape": {
                        "field": "next_request_payload",
                        "description": (
                            "Use result.next_request_payload directly as the next run_mcp_workflow "
                            "arguments after reviewing and editing generated_input_bundle when formal evidence "
                            "preview is needed. For M0-M2 low-risk tasks, use result.codex_execution_packet "
                            "as the direct local Codex task packet."
                        ),
                    },
                    "authority_note": (
                        "Draft generation is read-only input preparation; it does not run the "
                        "thin loop, authorize execution, create ReviewDecision, emit GateEvent, "
                        "or change Delivery State."
                    ),
                },
            },
        )

    def _thin_loop_codex_execution_packet(self, generated_input_bundle: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
        external_claim = generated_input_bundle.get("external_taskbook_claim")
        if not isinstance(external_claim, dict):
            external_claim = {}
        envelope = generated_input_bundle.get("execution_envelope")
        if not isinstance(envelope, dict):
            envelope = {}
        draft_seed = self._thin_loop_draft_seed(params, generated_input_bundle)

        objective = self._thin_loop_packet_objective(draft_seed, external_claim)
        allowed_files = self._thin_loop_packet_string_list(envelope.get("allowed_files")) or self._thin_loop_packet_string_list(
            external_claim.get("allowed_files")
        )
        forbidden_files = self._thin_loop_packet_string_list(envelope.get("forbidden_files")) or self._thin_loop_packet_string_list(
            external_claim.get("forbidden_files")
        )
        validation_commands = self._thin_loop_packet_string_list(envelope.get("validation_commands")) or self._thin_loop_packet_string_list(
            external_claim.get("acceptance_commands")
        )
        allowed_commands = self._thin_loop_packet_string_list(envelope.get("allowed_commands")) or list(validation_commands)
        context_files = self._thin_loop_seed_string_list(draft_seed, "context_files")
        task_tier_info = self._thin_loop_task_tier_info(draft_seed)
        task_tier = task_tier_info["task_tier"]
        packet_blockers = self._thin_loop_codex_packet_blockers(
            task_tier_info=task_tier_info,
            allowed_files=allowed_files,
            validation_commands=validation_commands,
        )
        direct_execution_ready = not packet_blockers
        session_guidance = self._thin_loop_executor_session_guidance(
            provider="codex",
            continuation_snapshot=self._continuation_snapshot,
        )
        closeout_template = self._thin_loop_closeout_summary_template(validation_commands)
        prompt = self._thin_loop_codex_prompt(
            objective=objective,
            task_tier=task_tier,
            allowed_files=allowed_files,
            forbidden_files=forbidden_files,
            context_files=context_files,
            validation_commands=validation_commands,
            session_guidance=session_guidance,
            direct_execution_ready=direct_execution_ready,
            blockers=packet_blockers,
        )

        return {
            "packet_kind": "thin_governed_loop_codex_execution_packet",
            "packet_version": "v1",
            "packet_status": "ready" if direct_execution_ready else "blocked",
            "direct_execution_ready": direct_execution_ready,
            "blockers": packet_blockers,
            "task_tier": task_tier,
            "task_tier_status": task_tier_info,
            "project_root": self.project_root,
            "current_head": generated_input_bundle.get("current_head"),
            "objective": objective,
            "scope": {
                "allowed_files": allowed_files,
                "forbidden_files": forbidden_files,
                "context_files": context_files,
            },
            "validation": {
                "commands": validation_commands,
                "allowed_commands": allowed_commands,
                "run_validation_after_changes": direct_execution_ready,
            },
            "execution_boundary": {
                "local_codex_direct_execution_packet": True,
                "local_codex_direct_execution_ready": direct_execution_ready,
                "colameta_executor_dispatch_authorized": False,
                "delivery_state_accepted_authorized": False,
                "review_decision_authorized": False,
                "gate_event_authorized": False,
                "commit_or_push_authorized": False,
                "may_edit_only_allowed_files": bool(allowed_files) and direct_execution_ready,
                "must_not_read_secrets_or_private_state": True,
            },
            "executor_session_recovery": session_guidance,
            "closeout_summary_template": closeout_template,
            "copy_paste_codex_prompt": prompt,
            "next_optional_evidence_step": {
                "needed_for_m0_m2_direct_work": False,
                "direct_work_ready": direct_execution_ready,
                "tool": "run_mcp_workflow",
                "payload_field": "next_request_payload",
                "when_to_use": "Use only when a formal thin_loop evidence preview is needed after reviewing generated_input_bundle.",
            },
        }

    def _thin_loop_packet_objective(self, draft_seed: dict[str, Any], external_claim: dict[str, Any]) -> str:
        _, seeded_goal = self._thin_loop_seed_goal(draft_seed)
        if seeded_goal:
            return seeded_goal
        provenance = external_claim.get("provenance") if isinstance(external_claim.get("provenance"), dict) else {}
        note = provenance.get("provenance_note")
        if isinstance(note, str) and note.strip():
            return note.strip().removeprefix("Draft goal: ").strip()
        return "Complete the bounded low-risk task described by this thin governed loop packet."

    @staticmethod
    def _thin_loop_packet_string_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        result: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                result.append(item.strip())
            elif isinstance(item, dict):
                command = item.get("command")
                if isinstance(command, str) and command.strip():
                    result.append(command.strip())
        return result

    def _thin_loop_task_tier(self, draft_seed: dict[str, Any]) -> str:
        return self._thin_loop_task_tier_info(draft_seed)["task_tier"]

    def _thin_loop_task_tier_info(self, draft_seed: dict[str, Any]) -> dict[str, Any]:
        raw_value = self._thin_loop_seed_string(draft_seed, "task_tier")
        normalized = raw_value.upper().replace("_", "-") if raw_value else "M0-M2"
        valid_tiers = {"M0", "M1", "M2", "M0-M1", "M1-M2", "M0-M2"}
        if normalized in valid_tiers:
            return {
                "task_tier": normalized,
                "raw_task_tier": raw_value,
                "valid": True,
                "defaulted": not bool(raw_value),
                "valid_tiers": sorted(valid_tiers),
            }
        return {
            "task_tier": normalized,
            "raw_task_tier": raw_value,
            "valid": False,
            "defaulted": False,
            "valid_tiers": sorted(valid_tiers),
        }

    @staticmethod
    def _thin_loop_codex_packet_blockers(
        *,
        task_tier_info: dict[str, Any],
        allowed_files: list[str],
        validation_commands: list[str],
    ) -> list[dict[str, Any]]:
        blockers: list[dict[str, Any]] = []
        if task_tier_info.get("valid") is not True:
            blockers.append(
                {
                    "code": "invalid_task_tier",
                    "message": "task_tier must be one of the M0-M2 low-risk tiers before direct local Codex execution.",
                    "actual": task_tier_info.get("raw_task_tier") or task_tier_info.get("task_tier"),
                    "valid_tiers": task_tier_info.get("valid_tiers", []),
                }
            )
        if not allowed_files:
            blockers.append(
                {
                    "code": "allowed_files_required",
                    "message": "allowed_files must be supplied before direct local Codex execution.",
                }
            )
        if not validation_commands:
            blockers.append(
                {
                    "code": "validation_commands_required",
                    "message": "validation_commands must be supplied before direct local Codex execution.",
                }
            )
        return blockers

    def _thin_loop_executor_session_guidance(
        self,
        *,
        provider: str,
        continuation_snapshot: ContinuationSnapshot | None = None,
    ) -> dict[str, Any]:
        fallback = {
            "status": "session_guidance_unavailable",
            "provider": provider,
            "recommended_action": "inspect_evidence",
            "recommended_session_mode": "blocked",
            "resume_existing_allowed_by_packet": False,
            "start_new_allowed_by_packet": False,
            "local_codex_direct_session": "blocked",
            "managed_executor_mode_hint": None,
            "reason": "executor_session_status_unavailable",
            "head_mismatch": None,
            "hard_blockers": [],
            "warnings": [],
            "canonical_continuation_decision": None,
            "does_not_reset_or_modify_session_metadata": True,
        }
        try:
            captured = continuation_snapshot or self._continuation_snapshot
            if captured is None:
                captured = collect_continuation_snapshot(
                    self.project_root,
                    requested_provider=provider,
                    planning_bridge=self._planning_bridge,
                    source_review=self._source_review,
                )
                self._continuation_snapshot = captured
            projection = captured.project(provider)
            status = captured.session_status
            decision = projection["canonical_continuation_decision"]
            invocation = projection["resume_invocation_preview"]
        except Exception as exc:
            out = dict(fallback)
            out["error"] = str(exc)
            return out

        if not isinstance(status, dict):
            status = {}
        if not isinstance(decision, dict):
            decision = {}
        if not isinstance(invocation, dict):
            invocation = {}

        hard_blockers = [str(item) for item in decision.get("hard_blockers", []) if isinstance(item, str)]
        warnings = [str(item) for item in decision.get("risk_warnings", []) if isinstance(item, str)]
        classification = decision.get("head_mismatch_classification")
        classification = classification if isinstance(classification, dict) else {}
        classification_evidence = classification.get("evidence")
        classification_evidence = (
            classification_evidence if isinstance(classification_evidence, dict) else {}
        )
        recommended_action = str(decision.get("recommended_action") or "inspect_evidence")
        resume_allowed = bool(decision.get("resume_allowed") is True)
        start_new_allowed = bool(decision.get("start_new_allowed") is True)
        session_mode = {
            "resume": "auto",
            "start_new": "start_new",
            "inspect_evidence": "blocked",
            "human_review": "blocked",
        }.get(recommended_action, "blocked")
        guidance_status = {
            "resume": "resume_available",
            "start_new": "start_new_recommended",
            "inspect_evidence": "continuation_evidence_inspection_required",
            "human_review": "continuation_human_review_required",
        }.get(recommended_action, "continuation_evidence_inspection_required")
        managed_hint = {
            "resume": "executor_session_mode=auto",
            "start_new": "executor_session_mode=start_new",
        }.get(recommended_action)
        safe_recovery_steps = {
            "resume": [
                "Use the canonical resume path only while the bound facts remain current.",
            ],
            "start_new": [
                "Do not resume the prior executor session.",
                "Start a fresh local Codex conversation with copy_paste_codex_prompt.",
                "Do not reset session metadata unless Jenn explicitly asks for reset.",
            ],
            "inspect_evidence": [
                "Inspect the missing continuation evidence before selecting a session mode.",
                "Do not resume or start a managed executor session from this packet.",
            ],
            "human_review": [
                "Review the possibly active HEAD mismatch before selecting a session mode.",
                "Do not resume or start a managed executor session from this packet.",
            ],
        }.get(recommended_action, ["Inspect continuation evidence before selecting a session mode."])
        return {
            "status": guidance_status,
            "provider": provider,
            "recommended_action": recommended_action,
            "recommended_session_mode": session_mode,
            "resume_existing_allowed_by_packet": resume_allowed,
            "start_new_allowed_by_packet": start_new_allowed,
            "local_codex_direct_session": (
                "fresh_or_resume_at_codex_discretion"
                if recommended_action == "resume"
                else ("start_new" if recommended_action == "start_new" else "blocked")
            ),
            "managed_executor_mode_hint": managed_hint,
            "reason": str(decision.get("reason") or "continuation_evidence_incomplete"),
            "head_mismatch": classification_evidence.get("head_mismatch"),
            "session_head": (
                status.get("record", {}).get("current_head")
                if isinstance(status.get("record"), dict)
                else None
            ),
            "current_head": status.get("current_head"),
            "hard_blockers": hard_blockers,
            "warnings": warnings,
            "safe_recovery_steps": safe_recovery_steps,
            "canonical_continuation_decision": decision,
            "continuation_snapshot": captured.public_view(provider),
            "invocation_uses_canonical_decision": (
                invocation.get("canonical_continuation_decision") is decision
            ),
            "does_not_reset_or_modify_session_metadata": True,
        }

    def _thin_loop_closeout_summary_template(self, validation_commands: list[str]) -> dict[str, Any]:
        return {
            "progress": "<what changed, with file paths>",
            "validation": [
                {"command": command, "result": "<passed|failed|not_run>", "notes": ""}
                for command in validation_commands
            ],
            "risk": "<remaining risk or none>",
            "continuation": "COMPLETED | CONTINUING_AUTOMATICALLY | BLOCKED_NEEDS_USER",
            "forbidden_claims": {
                "delivery_accepted": False,
                "review_decision_written": False,
                "gate_event_written": False,
                "commit_or_push_done": False,
            },
        }

    def _thin_loop_codex_prompt(
        self,
        *,
        objective: str,
        task_tier: str,
        allowed_files: list[str],
        forbidden_files: list[str],
        context_files: list[str],
        validation_commands: list[str],
        session_guidance: dict[str, Any],
        direct_execution_ready: bool,
        blockers: list[dict[str, Any]],
    ) -> str:
        def lines(items: list[str]) -> str:
            return "\n".join(f"- {item}" for item in items) if items else "- <none specified>"

        def blocker_lines(items: list[dict[str, Any]]) -> str:
            if not items:
                return "- <none>"
            return "\n".join(
                f"- {item.get('code')}: {item.get('message')}"
                for item in items
            )

        validation_lines = lines(validation_commands) if validation_commands else "- <missing: provide validation_commands>"

        return "\n".join(
            [
                f"Goal: {objective}",
                "",
                f"Task tier: {task_tier} low-risk thin governed loop.",
                f"Packet status: {'ready' if direct_execution_ready else 'blocked'}",
                "Direct local Codex execution ready: " + ("yes" if direct_execution_ready else "no"),
                "Blockers:",
                blocker_lines(blockers),
                "",
                "Scope:",
                "Allowed files:",
                lines(allowed_files),
                "Forbidden files:",
                lines(forbidden_files),
                "Context files to read first:",
                lines(context_files),
                "",
                "Execution rules:",
                "- Work directly in the local repo; do not use ColaMeta insert/apply/continue/closeout tools for this low-risk task.",
                "- If this packet status is blocked, do not edit files from this packet until blockers are resolved.",
                "- Edit only allowed files unless the user explicitly expands scope.",
                "- Do not read token/cookie/credential/browser login state, tunnel config, proxy config, raw logs, or private memory.",
                "- Do not write Delivery accepted, ReviewDecision, GateEvent, commit, push, or stable replacement.",
                "- Follow only the canonical session guidance below; when it is blocked, do not resume or start a managed executor session.",
                f"- Session guidance: {session_guidance.get('status')} / {session_guidance.get('managed_executor_mode_hint')}.",
                "",
                "Validation commands:",
                validation_lines,
                "",
                "Closeout summary format:",
                "[Progress] changed files and behavior",
                "[Validation] commands run and results",
                "[Risk] remaining risk",
                "[Continuation] COMPLETED, CONTINUING_AUTOMATICALLY, or BLOCKED_NEEDS_USER",
            ]
        )

    def _thin_loop_core_result(
        self,
        *,
        phase: str,
        input_mode: str,
        thin_loop: dict[str, Any],
        passed: bool,
        blocker_messages: list[str],
        warnings: list[str],
        extra_result: dict[str, Any] | None = None,
    ) -> 'CoreResult':
        requested_action = str(thin_loop.get("requested_commander_action") or "")
        result = {
            "ok": passed,
            "read_only": True,
            "side_effects": False,
            "input_mode": input_mode,
            "thin_loop": thin_loop,
            "summary": {
                "thin_loop_status": thin_loop.get("thin_loop_status"),
                "stage_count": len(thin_loop.get("stage_results", {}) or {}),
                "blocker_count": len(thin_loop.get("blockers", []) or []),
                "requested_commander_action": requested_action,
            },
            "authority_boundary": thin_loop.get("authority_boundary") or self._thin_loop_authority_boundary(),
            "requested_commander_action": requested_action,
            "forbidden_authority_outputs": {
                "delivery_state_accepted": False,
                "review_decision_created": False,
                "gate_event_emitted": False,
                "executor_dispatch_authorized": False,
            },
            "input_contract": self._thin_loop_input_contract(),
        }
        if extra_result:
            result.update(extra_result)
        next_actions: list[dict[str, Any]] = []
        if passed and requested_action == "ask_whether_to_request_delivery_state_gate_review":
            gate_review_action = {
                "tool": "run_mcp_workflow",
                "arguments": {
                    "workflow": "gate_review_request",
                    "phase": "inspect",
                },
                "risk_level": STEP_RISK_INFO,
                "requires_confirmation": False,
                "authority": "read_only",
            }
            next_actions.append(gate_review_action)
            result["gate_review_request_entry"] = gate_review_action
        step = {
            "name": "thin_governed_loop_preview",
            "tool": "run_mcp_workflow",
            "action": "thin_governed_loop_preview",
            "ok": passed,
            "risk_level": STEP_RISK_INFO,
            "preview_id": None,
            "changed_files": [],
            "blockers": blocker_messages,
            "warnings": warnings,
        }
        return self._build_core_result(
            workflow="thin_governed_loop_preview",
            steps=[step],
            risk_level=STEP_RISK_INFO,
            status="succeeded" if passed else "blocked",
            requires_confirmation=False,
            next_actions=next_actions,
            blockers=blocker_messages,
            warnings=warnings,
            result=result,
            phase=phase,
        )

    def _thin_loop_generated_input_bundle(self, params: dict[str, Any]) -> dict[str, Any]:
        from runner.thin_governed_loop import build_draft_evidence_provenance, example_stage_3_6_inputs

        bundle_param = params.get("thin_loop_inputs")
        if not isinstance(bundle_param, dict):
            bundle_param = {}
        draft_seed = self._thin_loop_draft_seed(params, bundle_param)
        inputs = example_stage_3_6_inputs()
        self._thin_loop_reset_draft_task_evidence(inputs)
        current_head = self._thin_loop_current_head(params, bundle_param)
        inputs["project_root"] = self.project_root
        inputs["current_head"] = current_head
        applied_seed_fields = self._thin_loop_apply_draft_seed(inputs, draft_seed)
        ignored_seed_fields = self._thin_loop_ignored_seed_fields(draft_seed, applied_seed_fields)
        generated = {
            "input_mode": "provided",
            "current_head": current_head,
            "draft_seed_applied": applied_seed_fields,
            "draft_seed_ignored": ignored_seed_fields,
            "draft_seed_unknown": self._thin_loop_unknown_seed_fields(draft_seed),
        }
        for field in self._thin_loop_object_fields():
            generated[field] = inputs[field]
        generated["evidence_provenance"] = build_draft_evidence_provenance(generated)
        return generated

    @staticmethod
    def _thin_loop_draft_seed(params: dict[str, Any], bundle_param: dict[str, Any]) -> dict[str, Any]:
        for candidate in (params.get("draft_seed"), bundle_param.get("draft_seed")):
            if isinstance(candidate, dict):
                return candidate
        return {}

    @staticmethod
    def _thin_loop_reset_draft_task_evidence(inputs: dict[str, Any]) -> None:
        external_claim = inputs.get("external_taskbook_claim")
        if isinstance(external_claim, dict):
            source = external_claim.get("source")
            if isinstance(source, dict):
                source["source_id"] = "thin-governed-loop-draft"
            provenance = external_claim.get("provenance")
            if isinstance(provenance, dict):
                provenance["provenance_note"] = "Thin loop draft input placeholder; provide goal/objective before use."
            manual_acceptance = external_claim.get("manual_acceptance")
            if isinstance(manual_acceptance, dict):
                manual_acceptance["acceptance_note"] = "Manual review required before adoption. Draft input has not been executed."
            external_claim["allowed_files"] = []
            external_claim["forbidden_files"] = []
            external_claim["acceptance_commands"] = []

        envelope = inputs.get("execution_envelope")
        if isinstance(envelope, dict):
            envelope["allowed_files"] = []
            envelope["forbidden_files"] = []
            envelope["allowed_commands"] = []
            envelope["validation_commands"] = []

        local_receipt = inputs.get("local_execution_receipt")
        if isinstance(local_receipt, dict):
            local_receipt["execution_result"] = "blocked_before_execution"
            local_receipt["command_attempts"] = []
            local_receipt["touched_files"] = []
            local_receipt["observed_mutations"] = []
            local_receipt["validation_commands"] = []
            local_receipt["validation_results"] = []
            local_receipt["validation_summary"] = "not_run"
            local_receipt["scope_check_result"] = "not_run"
            local_receipt["blocked_or_failed_reasons"] = ["draft_input_not_executed"]
            local_receipt["known_gaps"] = [
                {"gap_id": "draft_input_not_executed", "description": "Draft input bundle has not been executed."},
                {"gap_id": "touched_files_unknown", "description": "Touched files are unknown until a real local run."},
            ]
            local_receipt["remaining_risks"] = [
                {"risk_id": "draft_not_executed", "risk": "Draft input bundle is not proof of execution."}
            ]

    @staticmethod
    def _thin_loop_known_draft_seed_fields() -> frozenset[str]:
        return frozenset(
            {
                "allowed_files",
                "forbidden_files",
                "validation_commands",
                "allowed_commands",
                "goal",
                "objective",
                "source_id",
                "review_decision_value",
                "pass_alias_policy_id_when_used",
                "reviewer_notes",
                "task_tier",
                "context_files",
            }
        )

    def _thin_loop_ignored_seed_fields(self, seed: dict[str, Any], applied_seed_fields: list[str]) -> list[str]:
        applied = set(applied_seed_fields)
        return sorted(str(key) for key in seed.keys() if str(key) not in applied)

    def _thin_loop_unknown_seed_fields(self, seed: dict[str, Any]) -> list[str]:
        known = self._thin_loop_known_draft_seed_fields()
        return sorted(str(key) for key in seed.keys() if str(key) not in known)

    def _thin_loop_apply_draft_seed(self, inputs: dict[str, Any], draft_seed: dict[str, Any]) -> list[str]:
        if not draft_seed:
            return []
        external_claim = inputs.get("external_taskbook_claim")
        envelope = inputs.get("execution_envelope")
        local_receipt = inputs.get("local_execution_receipt")
        review_feedback = inputs.get("review_feedback")
        if not all(isinstance(item, dict) for item in (external_claim, envelope, local_receipt, review_feedback)):
            return []

        applied: set[str] = set()
        goal_field, goal = self._thin_loop_seed_goal(draft_seed)
        if goal:
            applied.add(goal_field)
            external_claim.setdefault("provenance", {})["provenance_note"] = f"Draft goal: {goal}"
            external_claim.setdefault("manual_acceptance", {})["acceptance_note"] = (
                f"Manual review required before adoption. Draft goal: {goal}"
            )
            if not self._thin_loop_seed_string(draft_seed, "reviewer_notes"):
                review_feedback["reviewer_notes"] = f"Draft goal: {goal}"

        allowed_files = self._thin_loop_seed_string_list(draft_seed, "allowed_files")
        if allowed_files:
            applied.add("allowed_files")
            external_claim["allowed_files"] = allowed_files
            envelope["allowed_files"] = allowed_files

        forbidden_files = self._thin_loop_seed_string_list(draft_seed, "forbidden_files")
        if forbidden_files:
            applied.add("forbidden_files")
            external_claim["forbidden_files"] = forbidden_files
            envelope["forbidden_files"] = forbidden_files

        validation_commands = self._thin_loop_seed_string_list(draft_seed, "validation_commands")
        if validation_commands:
            applied.add("validation_commands")
            external_claim["acceptance_commands"] = validation_commands
            envelope["validation_commands"] = validation_commands
            local_receipt["validation_commands"] = validation_commands

        allowed_commands = self._thin_loop_seed_string_list(draft_seed, "allowed_commands")
        if allowed_commands:
            applied.add("allowed_commands")
            envelope["allowed_commands"] = allowed_commands
        elif validation_commands:
            envelope["allowed_commands"] = validation_commands

        source_id = self._thin_loop_seed_string(draft_seed, "source_id")
        if source_id:
            applied.add("source_id")
            external_claim.setdefault("source", {})["source_id"] = source_id
        task_tier_info = self._thin_loop_task_tier_info(draft_seed)
        if self._thin_loop_seed_string(draft_seed, "task_tier") and task_tier_info.get("valid") is True:
            applied.add("task_tier")
        if self._thin_loop_seed_string_list(draft_seed, "context_files"):
            applied.add("context_files")
        reviewer_notes = self._thin_loop_seed_string(draft_seed, "reviewer_notes")
        if reviewer_notes:
            applied.add("reviewer_notes")
            review_feedback["reviewer_notes"] = reviewer_notes
        pass_alias_policy_id = self._thin_loop_seed_string(draft_seed, "pass_alias_policy_id_when_used")
        review_decision_value = self._thin_loop_seed_review_decision(draft_seed)
        if review_decision_value == "PASS" and not pass_alias_policy_id:
            review_decision_value = ""
        if review_decision_value:
            applied.add("review_decision_value")
            review_feedback["review_decision_value"] = review_decision_value
            if review_decision_value != "PASS":
                review_feedback["pass_alias_policy_id_when_used"] = None
        if review_feedback.get("review_decision_value") == "PASS" and pass_alias_policy_id:
            applied.add("pass_alias_policy_id_when_used")
            review_feedback["pass_alias_policy_id_when_used"] = pass_alias_policy_id
        return sorted(applied)

    def _thin_loop_seed_goal(self, seed: dict[str, Any]) -> tuple[str, str]:
        for key in ("goal", "objective"):
            value = self._thin_loop_seed_string(seed, key)
            if value:
                return key, value
        return "", ""

    @staticmethod
    def _thin_loop_seed_string_list(seed: dict[str, Any], key: str) -> list[str]:
        value = seed.get(key)
        if not isinstance(value, list):
            return []
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]

    @staticmethod
    def _thin_loop_seed_string(seed: dict[str, Any], key: str) -> str:
        value = seed.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        return ""

    def _thin_loop_seed_review_decision(self, seed: dict[str, Any]) -> str:
        value = self._thin_loop_seed_string(seed, "review_decision_value").upper()
        allowed = {"ACCEPT", "NEEDS_FIX", "PLAN_ADJUST", "ABORT", "PASS"}
        return value if value in allowed else ""

    def _thin_loop_inputs_from_params(self, params: dict[str, Any]) -> tuple[dict[str, Any] | None, str, list[str]]:
        from runner.thin_governed_loop import example_stage_3_6_inputs

        object_fields = self._thin_loop_object_fields()
        bundle = params.get("thin_loop_inputs")
        if not isinstance(bundle, dict):
            bundle = {}

        input_mode = self._thin_loop_requested_input_mode(params)
        if input_mode not in ("", "example", "provided"):
            return None, input_mode or "unknown", ["input_mode"]

        provided: dict[str, Any] = {}
        for field in object_fields:
            if field in params:
                provided[field] = params.get(field)
            elif field in bundle:
                provided[field] = bundle.get(field)

        if input_mode == "example" or (input_mode == "" and not provided):
            inputs = example_stage_3_6_inputs()
            inputs["project_root"] = self.project_root
            inputs["current_head"] = self._thin_loop_current_head(params, bundle)
            return inputs, "example", []

        missing = [field for field in object_fields if not isinstance(provided.get(field), dict)]
        if missing:
            return None, "provided", missing

        inputs = {
            "project_root": self.project_root,
            "current_head": self._thin_loop_current_head(params, bundle),
        }
        for field in object_fields:
            inputs[field] = provided[field]
        provenance = params.get("evidence_provenance", bundle.get("evidence_provenance"))
        if provenance is not None:
            inputs["evidence_provenance"] = provenance
        return inputs, "provided", []

    def _thin_loop_requested_input_mode(self, params: dict[str, Any]) -> str:
        bundle = params.get("thin_loop_inputs")
        if not isinstance(bundle, dict):
            bundle = {}
        input_mode_raw = params.get("input_mode", bundle.get("input_mode", ""))
        return str(input_mode_raw or "").strip().lower()

    @staticmethod
    def _thin_loop_object_fields() -> tuple[str, str, str, str]:
        return (
            "external_taskbook_claim",
            "execution_envelope",
            "local_execution_receipt",
            "review_feedback",
        )

    def _thin_loop_input_contract(self) -> dict[str, Any]:
        return {
            "input_contract_version": "thin_governed_loop_inputs.v1",
            "accepted_input_modes": ["example", "template", "draft", "provided"],
            "provided_mode_required_objects": [
                {
                    "field": "external_taskbook_claim",
                    "stage": "stage_03_import",
                    "purpose": "外部任务书声明对象；作为 bounded claim 验证，不直接采信。",
                },
                {
                    "field": "execution_envelope",
                    "stage": "stage_04_execution_evidence",
                    "purpose": "受控执行 envelope；声明可执行边界、命令、文件范围和停止条件。",
                },
                {
                    "field": "local_execution_receipt",
                    "stage": "stage_04_execution_evidence",
                    "purpose": "本地执行 receipt；记录实际执行结果、文件触达和验证结果。",
                },
                {
                    "field": "review_feedback",
                    "stage": "stage_06_feedback_intake",
                    "purpose": "审查反馈对象；只生成反馈分类和 Commander 下一步请求。",
                },
            ],
            "transport": {
                "direct_fields": [*self._thin_loop_object_fields(), "evidence_provenance"],
                "bundle_field": "thin_loop_inputs",
                "bundle_allowed_fields": [
                    "input_mode",
                    "current_head",
                    "draft_seed",
                    *self._thin_loop_object_fields(),
                    "evidence_provenance",
                ],
            },
            "minimal_request_shape": {
                "workflow": "thin_governed_loop_preview",
                "phase": "preview",
                "input_mode": "provided",
                "project_name": "<managed project_name when using service mode>",
                "current_head": "<optional git head>",
                "external_taskbook_claim": "<object>",
                "execution_envelope": "<object>",
                "local_execution_receipt": "<object>",
                "review_feedback": "<object>",
                "evidence_provenance": "<optional versioned sibling envelope; omission is legacy_unclassified>",
            },
            "draft_request_shape": {
                "workflow": "thin_governed_loop_preview",
                "phase": "preview",
                "input_mode": "draft",
                "project_name": "<managed project_name when using service mode>",
                "draft_seed": {
                    "allowed_files": ["<project-relative path>"],
                    "goal": "<optional natural-language objective>",
                    "validation_commands": ["<validation command>"],
                    "review_decision_value": "NEEDS_FIX",
                    "reviewer_notes": "<optional reviewer note>",
                },
            },
            "draft_mode_output": {
                "field": "generated_input_bundle",
                "submit_as": "thin_loop_inputs",
                "submit_with_input_mode": "provided",
                "ignored_seed_fields": "generated_input_bundle.draft_seed_ignored",
                "unknown_seed_fields": "generated_input_bundle.draft_seed_unknown",
                "authority": "draft_input_only_not_execution_or_acceptance_authority",
            },
            "draft_seed_fields": {
                "allowed_files": "同步写入 external_taskbook_claim、execution_envelope；不伪造 receipt.touched_files/observed_mutations。",
                "forbidden_files": "同步写入 external_taskbook_claim、execution_envelope。",
                "validation_commands": "同步写入计划/边界字段；receipt 仍为 blocked_before_execution，且不伪造 passed/exit_code。",
                "allowed_commands": "可选覆盖 execution_envelope.allowed_commands；不传时沿用 validation_commands。",
                "goal": "写入 external_taskbook_claim provenance/manual_acceptance；无 reviewer_notes 时也写入 review_feedback.reviewer_notes。",
                "objective": "goal 的同义字段；用于自然语言目标。",
                "source_id": "写入 external_taskbook_claim.source.source_id。",
                "review_decision_value": "写入 review_feedback.review_decision_value；支持 ACCEPT、NEEDS_FIX、PLAN_ADJUST、ABORT；PASS 必须同时提供 pass_alias_policy_id_when_used。",
                "pass_alias_policy_id_when_used": "仅在 review_decision_value 为 PASS 时写入；没有该字段时 PASS seed 会被忽略。",
                "reviewer_notes": "写入 review_feedback.reviewer_notes。",
            },
            "read_only_boundary": {
                "authorizes_executor_dispatch": False,
                "creates_review_decision": False,
                "emits_gate_event": False,
                "writes_delivery_state": False,
                "commits_or_pushes": False,
            },
        }

    def _thin_loop_current_head(self, params: dict[str, Any], bundle: dict[str, Any]) -> str:
        for value in (params.get("current_head"), bundle.get("current_head")):
            if isinstance(value, str) and value.strip():
                return value.strip()
        try:
            project_identity = build_project_identity(self.project_root)
            head = project_identity.get("git_head")
            if isinstance(head, str) and head.strip():
                return head.strip()
        except Exception:
            pass
        return "unknown"

    @staticmethod
    def _thin_loop_authority_boundary() -> dict[str, bool]:
        return {
            "thin_loop_result_is_authority": False,
            "thin_loop_authorizes_executor_dispatch": False,
            "thin_loop_creates_review_decision": False,
            "thin_loop_emits_gate_event": False,
            "thin_loop_writes_delivery_state": False,
        }

    @staticmethod
    def _thin_loop_blocker_text(blocker: Any) -> str:
        if isinstance(blocker, dict):
            code = blocker.get("code") or "thin_loop_blocker"
            stage = blocker.get("stage")
            field = blocker.get("field")
            expected = blocker.get("expected")
            actual = blocker.get("actual")
            location = ".".join(str(part) for part in (stage, field) if part)
            if location:
                return f"{code}: {location} expected {expected!r}, actual {actual!r}"
            return f"{code}: {json.dumps(blocker, ensure_ascii=False, sort_keys=True)}"
        return str(blocker)

    # ================================================================
    # auto_preview
    # ================================================================

    def _workflow_auto_preview(self, params: dict[str, Any]) -> dict[str, Any]:
        goal_raw = params.get("goal", "")
        goal = goal_raw.strip().lower() if isinstance(goal_raw, str) else ""
        provider = params.get("provider")
        max_files = params.get("max_files")
        max_chars = params.get("max_chars")
        max_diff_chars = params.get("max_diff_chars")
        include_diff_summary = params.get("include_diff_summary", True)
        dry_run = params.get("dry_run", False)
        reason = params.get("reason")

        classify_params: dict[str, Any] = {
            "goal": goal_raw,
            "provider": provider,
        }
        if max_files is not None:
            classify_params["max_files"] = max_files
        if max_chars is not None:
            classify_params["max_chars"] = max_chars
        if max_diff_chars is not None:
            classify_params["max_diff_chars"] = max_diff_chars
        classify_params["include_diff_summary"] = include_diff_summary
        classify_params["dry_run"] = dry_run
        if reason is not None:
            classify_params["reason"] = reason

        if not goal:
            return self._auto_preview_project_status(classify_params)

        classified = self._classify_goal(goal)
        confidence = classified["confidence"]
        selected_workflow = classified["selected_workflow"]
        selection_reason = classified.get("reason", "goal keywords matched")

        auto_preview_params = self._copy_auto_preview_params(params)
        auto_preview_params["_selected_workflow"] = selected_workflow
        auto_preview_params["_selection_reason"] = selection_reason
        auto_preview_params["_confidence"] = confidence

        if selected_workflow == "docs":
            return self._auto_preview_docs(auto_preview_params)
        if selected_workflow == "plan":
            return self._auto_preview_plan(auto_preview_params)
        if selected_workflow == "git_commit":
            return self._auto_preview_git_commit(auto_preview_params)
        if selected_workflow == "executor":
            return self._auto_preview_executor(auto_preview_params)
        if selected_workflow == "small_project_patch":
            return self._auto_preview_small_project_patch(auto_preview_params)

        return self._auto_preview_source_or_status(auto_preview_params)

    # ----------------------------------------------------------------
    # auto_preview sub-routes
    # ----------------------------------------------------------------

    def _auto_preview_project_status(self, params: dict[str, Any]) -> dict[str, Any]:
        if self._analyze_state_fn is None:
            return self._auto_preview_result(
                selected_workflow="project_status",
                selection_reason="no goal provided, no analyze_state_fn available",
                confidence=0.0,
                stop_reason=_STOP_STATUS_ONLY_NO_GOAL,
                steps=[self._step("auto_preview", "analyze_project_state", "skip", {}, STEP_RISK_INFO)],
                status="needs_input",
                requires_confirmation=False,
                blockers=["analyze_state_fn 未提供"],
                result=None,
            )
        state = self._analyze_state_fn(params)
        steps = [self._step("auto_preview", "analyze_project_state", "analyze", state, STEP_RISK_INFO)]

        next_actions = []
        if isinstance(state, dict):
            raw = state.get("recommended_next_actions", [])
            if isinstance(raw, list):
                next_actions = raw

        return self._auto_preview_result(
            selected_workflow="project_status",
            selection_reason="goal was empty or None",
            confidence=1.0,
            stop_reason=_STOP_STATUS_ONLY_NO_GOAL,
            steps=steps,
            next_actions=next_actions,
            status="succeeded" if state.get("ok") else "failed",
            requires_confirmation=False,
            result=state,
        )

    def _auto_preview_source_or_status(self, params: dict[str, Any]) -> dict[str, Any]:
        if self._analyze_state_fn is None:
            return self._auto_preview_result(
                selected_workflow="project_status",
                selection_reason="no analyze_state_fn available",
                confidence=0.0,
                stop_reason=_STOP_STATUS_ONLY_NO_GOAL,
                steps=[],
                status="succeeded",
                requires_confirmation=False,
                blockers=["analyze_state_fn 未提供"],
            )
        state = self._analyze_state_fn(params)
        steps = [self._step("auto_preview", "analyze_project_state", "analyze", state, STEP_RISK_INFO)]

        is_source_only = False
        if isinstance(state, dict):
            plan_info = state.get("plan", {})
            if isinstance(plan_info, dict):
                if plan_info.get("source_only"):
                    is_source_only = True

        if is_source_only:
            onboarding_params = {
                "phase": "preview",
                "goal": params.get("goal"),
                "project_name": params.get("project_name"),
                "first_version": params.get("first_version"),
                "first_version_name": params.get("first_version_name"),
                "dry_run": params.get("dry_run", False),
                "max_files": params.get("max_files"),
                "reason": params.get("reason"),
            }
            onboarding_result = self._workflow_source_onboarding(onboarding_params)
            onboarding_step = self._step(
                "auto_preview", "run_mcp_workflow", "source_onboarding",
                onboarding_result, STEP_RISK_PREVIEW,
            )
            steps.append(onboarding_step)

            onboarding_preview_ids = self._extract_preview_ids(onboarding_result)
            next_actions = []
            if onboarding_preview_ids:
                next_actions.append({
                    "action": "manage_runner_plan.apply",
                    "label": "应用纳管计划",
                    "tool": "manage_runner_plan",
                    "params": {"action": "apply", "preview_id": onboarding_preview_ids[0]},
                    "risk_level": "commit",
                    "requires_confirmation": True,
                })

            return self._auto_preview_result(
                selected_workflow="source_onboarding",
                selection_reason=(
                    f"project is source-only; auto-ran source_onboarding preview for goal "
                    f"({params.get('goal', 'none')})"
                ),
                confidence=0.9,
                stop_reason=_STOP_NEEDS_PLAN_APPLY_CONFIRMATION,
                steps=steps,
                preview_ids=onboarding_preview_ids,
                next_actions=next_actions,
                status="preview_ready" if onboarding_preview_ids else "succeeded",
                requires_confirmation=bool(onboarding_preview_ids),
                result=onboarding_result,
            )

        next_actions = []
        if isinstance(state, dict):
            raw = state.get("recommended_next_actions", [])
            if isinstance(raw, list):
                next_actions = raw

        return self._auto_preview_result(
            selected_workflow="project_status",
            selection_reason=f"goal ({params.get('goal', 'none')}) did not match a specific workflow; fell back to project_status",
            confidence=0.5,
            stop_reason=_STOP_GOAL_UNCLASSIFIED,
            steps=steps,
            next_actions=next_actions,
            status="succeeded" if state.get("ok") else "failed",
            requires_confirmation=False,
            result=state,
        )

    def _auto_preview_docs(self, params: dict[str, Any]) -> dict[str, Any]:
        steps: list[dict[str, Any]] = []

        index_result = self.project_docs.handle("index", {"max_files": params.get("max_files", 50)})
        steps.append(self._step(
            "auto_preview", "manage_project_docs", "index", index_result, STEP_RISK_INFO,
        ))

        goal_raw = params.get("goal", "")
        sync_keywords = {"sync", "同步", "过时", "stale", "scan"}
        if any(kw in goal_raw.lower() for kw in sync_keywords):
            sync_params = {
                "stale_terms": params.get("stale_terms"),
                "max_files": params.get("max_files", 50),
                "reason": params.get("reason"),
            }
            sync_result = self.project_docs.handle("sync_docs_preview", sync_params)
            steps.append(self._step(
                "auto_preview", "manage_project_docs", "sync_docs_preview",
                sync_result, STEP_RISK_PREVIEW,
            ))

            preview_ids = self._extract_preview_ids(sync_result)
            next_actions = []
            if preview_ids:
                next_actions.append({
                    "action": "docs_update.apply",
                    "label": "应用文档同步更新",
                    "tool": "run_mcp_workflow",
                    "params": {"workflow": "docs_update", "phase": "apply", "preview_id": preview_ids[0]},
                    "risk_level": "write",
                    "requires_confirmation": True,
                })

            return self._auto_preview_result(
                selected_workflow="docs_update",
                selection_reason="goal mentions docs sync/stale terms",
                confidence=0.8,
                stop_reason=_STOP_NEEDS_DOCS_APPLY_CONFIRMATION,
                steps=steps,
                preview_ids=preview_ids,
                next_actions=next_actions,
                status="preview_ready" if preview_ids else ("failed" if not sync_result.get("ok") else "succeeded"),
                requires_confirmation=bool(preview_ids),
                result=sync_result,
            )

        has_file = bool(params.get("file"))
        has_heading = bool(params.get("heading"))
        has_new_content = bool(params.get("new_content"))
        has_section_heading = bool(params.get("section_heading"))
        has_section_content = bool(params.get("section_content"))

        if has_file and has_section_heading and has_section_content:
            preview_params = {
                "file": params.get("file"),
                "section_heading": params.get("section_heading"),
                "section_content": params.get("section_content"),
                "after_heading": params.get("after_heading"),
                "reason": params.get("reason"),
            }
            preview_result = self.project_docs.handle(
                "append_section_preview", preview_params
            )
            steps.append(self._step(
                "auto_preview", "manage_project_docs", "append_section_preview",
                preview_result, STEP_RISK_PREVIEW,
            ))
            preview_ids = self._extract_preview_ids(preview_result)
            next_actions = []
            if preview_ids:
                next_actions.append({
                    "action": "docs_update.apply",
                    "label": "应用文档更新",
                    "tool": "run_mcp_workflow",
                    "params": {
                        "workflow": "docs_update",
                        "phase": "apply",
                        "preview_id": preview_ids[0],
                    },
                    "risk_level": "write",
                    "requires_confirmation": True,
                })
            return self._auto_preview_result(
                selected_workflow="docs_update",
                selection_reason=(
                    "goal mentions docs; has file+section_heading+section_content "
                    "for append_section_preview"
                ),
                confidence=0.9,
                stop_reason=_STOP_NEEDS_DOCS_APPLY_CONFIRMATION,
                steps=steps,
                preview_ids=preview_ids,
                next_actions=next_actions,
                status=(
                    "preview_ready"
                    if preview_ids
                    else ("failed" if not preview_result.get("ok") else "succeeded")
                ),
                requires_confirmation=bool(preview_ids),
                result=preview_result,
            )

        if has_file and has_heading and has_new_content:
            preview_params = {
                "file": params.get("file"),
                "heading": params.get("heading"),
                "new_content": params.get("new_content"),
                "reason": params.get("reason"),
            }
            preview_result = self.project_docs.handle("update_section_preview", preview_params)
            steps.append(self._step(
                "auto_preview", "manage_project_docs", "update_section_preview",
                preview_result, STEP_RISK_PREVIEW,
            ))
            preview_ids = self._extract_preview_ids(preview_result)
            next_actions = []
            if preview_ids:
                next_actions.append({
                    "action": "docs_update.apply",
                    "label": "应用文档更新",
                    "tool": "run_mcp_workflow",
                    "params": {"workflow": "docs_update", "phase": "apply", "preview_id": preview_ids[0]},
                    "risk_level": "write",
                    "requires_confirmation": True,
                })
            return self._auto_preview_result(
                selected_workflow="docs_update",
                selection_reason="goal mentions docs; has file+heading+new_content for update_section_preview",
                confidence=0.9,
                stop_reason=_STOP_NEEDS_DOCS_APPLY_CONFIRMATION,
                steps=steps,
                preview_ids=preview_ids,
                next_actions=next_actions,
                status="preview_ready" if preview_ids else ("failed" if not preview_result.get("ok") else "succeeded"),
                requires_confirmation=bool(preview_ids),
                result=preview_result,
            )

        return self._auto_preview_result(
            selected_workflow="docs_update",
            selection_reason=(
                "goal mentions docs but lacks file plus either "
                "heading/new_content or section_heading/section_content"
            ),
            confidence=0.6,
            stop_reason=_STOP_NEEDS_MORE_INPUT,
            steps=steps,
            status="needs_input",
            requires_confirmation=False,
            blockers=[
                "goal 涉及文档操作，但缺少 file 与对应的 section 更新或追加参数"
            ],
            result={"index": index_result.get("doc_index") if isinstance(index_result, dict) else None},
        )

    def _auto_preview_plan(self, params: dict[str, Any]) -> dict[str, Any]:
        has_repair_hints = bool(params.get("target_version") or params.get("version") or params.get("repair_kinds"))
        has_extend_hints = bool(params.get("name") or params.get("description") or params.get("insert_after"))

        if not has_repair_hints and not has_extend_hints:
            return self._auto_preview_result(
                selected_workflow="plan_update",
                selection_reason="goal mentions plan but lacks version/name/description/insert_after",
                confidence=0.5,
                stop_reason=_STOP_NEEDS_MORE_INPUT,
                steps=[],
                status="needs_input",
                requires_confirmation=False,
                blockers=["goal 涉及 plan 操作, 但缺少足够版本信息（version/name/description/insert_after）"],
            )

        mode = "repair" if has_repair_hints else "extend"
        plan_params = {
            "phase": "preview",
            "mode": mode,
            "version": params.get("version"),
            "target_version": params.get("target_version"),
            "repair_kinds": params.get("repair_kinds"),
            "name": params.get("name"),
            "description": params.get("description"),
            "insert_after": params.get("insert_after"),
            "prompt": params.get("prompt"),
            "reason": params.get("reason"),
        }
        plan_result = self._workflow_plan_update(plan_params)
        steps = [self._step(
            "auto_preview", "run_mcp_workflow", "plan_update", plan_result, STEP_RISK_PREVIEW,
        )]

        preview_ids = self._extract_preview_ids(plan_result)
        next_actions = []
        if preview_ids:
            next_actions.append({
                "action": "apply_preview_status",
                "label": "查看 patch 状态",
                "tool": "manage_plan_version",
                "params": {"action": "apply_preview_status", "patch_id": preview_ids[0]},
                "risk_level": "none",
                "requires_confirmation": False,
            })

        return self._auto_preview_result(
            selected_workflow="plan_update",
            selection_reason=f"goal mentions plan; auto-ran {mode} preview",
            confidence=0.8,
            stop_reason=_STOP_NEEDS_MORE_INPUT,
            steps=steps,
            preview_ids=preview_ids,
            next_actions=next_actions,
            status="preview_ready" if preview_ids else ("failed" if not plan_result.get("ok") else "succeeded"),
            requires_confirmation=bool(preview_ids),
            result=plan_result,
        )

    def _auto_preview_git_commit(self, params: dict[str, Any]) -> dict[str, Any]:
        readiness = self.git_commit.readiness(
            include_diff_summary=params.get("include_diff_summary", True),
            max_diff_chars=params.get("max_diff_chars", 40000),
        )
        steps = [self._step(
            "auto_preview", "manage_git_commit", "readiness", readiness, STEP_RISK_INFO,
        )]

        if readiness.get("ok") is not True:
            return self._auto_preview_result(
                selected_workflow="git_commit",
                selection_reason="goal mentions commit; readiness failed",
                confidence=0.0,
                stop_reason=_STOP_NEEDS_MORE_INPUT,
                steps=steps,
                status="failed",
                requires_confirmation=False,
                result=readiness,
            )

        working_tree_clean = bool(readiness.get("working_tree_clean", True))
        if working_tree_clean:
            return self._auto_preview_result(
                selected_workflow="git_commit",
                selection_reason="goal mentions commit; working tree clean",
                confidence=0.5,
                stop_reason=_STOP_STATUS_ONLY_NO_GOAL,
                steps=steps,
                status="succeeded",
                requires_confirmation=False,
                result=readiness,
            )

        commit_params = {
            "phase": "preview",
            "style": params.get("style", "runner_version"),
            "scope_hint": params.get("scope_hint"),
            "message": params.get("message"),
            "include_diff_summary": params.get("include_diff_summary", True),
            "max_diff_chars": params.get("max_diff_chars", 40000),
        }
        preview_result = self._workflow_git_commit(commit_params)
        steps.append(self._step(
            "auto_preview", "run_mcp_workflow", "git_commit", preview_result, STEP_RISK_PREVIEW,
        ))

        preview_ids = self._extract_preview_ids(preview_result)
        next_actions = []
        if preview_ids:
            next_actions.append({
                "action": "confirm_controlled_commit_preview",
                "label": "确认受控提交预览",
                "reason": "使用 manage_git_commit action=commit 应用已生成的 commit preview，不执行任意 shell，不 git add .",
                "tool": "manage_git_commit",
                "params": {"action": "commit", "preview_id": preview_ids[0]},
                "risk_level": "commit",
                "requires_confirmation": True,
            })

        return self._auto_preview_result(
            selected_workflow="git_commit",
            selection_reason="goal mentions commit; auto-ran commit_workflow_preview",
            confidence=0.9,
            stop_reason=_STOP_NEEDS_COMMIT_CONFIRMATION,
            steps=steps,
            preview_ids=preview_ids,
            next_actions=next_actions,
            status="preview_ready" if preview_ids else ("failed" if not preview_result.get("ok") else "succeeded"),
            requires_confirmation=bool(preview_ids),
            result=preview_result,
        )

    def _auto_preview_small_project_patch(self, params: dict[str, Any]) -> dict[str, Any]:
        has_file = bool(params.get("file"))
        has_patch_text = bool(params.get("patch_text"))
        has_old_text = bool(params.get("old_text"))

        if not has_file or not (has_patch_text or has_old_text):
            return self._auto_preview_result(
                selected_workflow="small_project_patch",
                selection_reason="goal mentions patch but lacks file + old_text/new_text or patch_text",
                confidence=0.4,
                stop_reason=_STOP_NEEDS_MORE_INPUT,
                steps=[],
                status="needs_input",
                requires_confirmation=False,
                blockers=["goal 涉及 patch 操作, 但缺少 file + old_text/new_text 或 patch_text"],
            )

        patch_params = {
            "phase": "preview",
            "file": params.get("file"),
            "old_text": params.get("old_text"),
            "new_text": params.get("new_text"),
            "patch_text": params.get("patch_text"),
            "reason": params.get("reason"),
            "max_files": params.get("max_files"),
            "max_diff_chars": params.get("max_diff_chars"),
        }
        patch_result = self._workflow_small_project_patch(patch_params)
        steps = [self._step(
            "auto_preview", "run_mcp_workflow", "small_project_patch",
            patch_result, STEP_RISK_PREVIEW,
        )]

        preview_ids = self._extract_preview_ids(patch_result)
        next_actions = []
        if preview_ids:
            next_actions.append({
                "action": "small_project_patch.apply",
                "label": "应用 patch",
                "tool": "run_mcp_workflow",
                "params": {"workflow": "small_project_patch", "phase": "apply", "preview_id": preview_ids[0]},
                "risk_level": "write",
                "requires_confirmation": True,
            })

        return self._auto_preview_result(
            selected_workflow="small_project_patch",
            selection_reason="goal mentions patch; auto-ran small_project_patch preview",
            confidence=0.9,
            stop_reason=_STOP_NEEDS_PATCH_APPLY_CONFIRMATION,
            steps=steps,
            preview_ids=preview_ids,
            next_actions=next_actions,
            status="preview_ready" if preview_ids else ("failed" if not patch_result.get("ok") else "succeeded"),
            requires_confirmation=bool(preview_ids),
            result=patch_result,
        )

    def _auto_preview_executor(self, params: dict[str, Any]) -> dict[str, Any]:
        steps: list[dict[str, Any]] = []

        provider = params.get("provider", "codex")
        snapshot = self._continuation_snapshot or get_or_collect_continuation_snapshot(
            self.project_root,
            requested_provider=provider,
            planning_bridge=self._planning_bridge,
            source_review=self._source_review,
        )
        if self._continuation_snapshot is None:
            self._continuation_snapshot = snapshot
        projection = snapshot.project(provider)
        session_status = snapshot.session_status
        steps.append(self._step(
            "auto_preview", "executor_session", "status", session_status, STEP_RISK_INFO,
        ))

        continuation_decision = projection["canonical_continuation_decision"]
        steps.append(self._step(
            "auto_preview", "executor_session", "continuation_decision",
            continuation_decision, STEP_RISK_INFO,
        ))

        resume_preview = projection["resume_invocation_preview"]
        steps.append(self._step(
            "auto_preview", "executor_session", "resume_invocation_preview",
            resume_preview, STEP_RISK_INFO,
        ))

        executor_inventory_raw = {}
        try:
            from runner.executor_inventory import load_executor_inventory
            executor_inventory_raw = load_executor_inventory(self.project_root)
        except Exception:
            executor_inventory_raw = {"available": False}

        result_payload: dict[str, Any] = {
            "session_status": session_status,
            "continuation_decision": continuation_decision,
            "resume_invocation_preview": resume_preview,
            "continuation_snapshot": snapshot.public_view(provider),
            "executor_inventory": executor_inventory_raw,
        }
        goal_text = str(params.get("goal") or "").lower()
        bounded_keywords = ("bounded", "loop", "循环", "多轮", "trusted")
        use_bounded_preview = any(keyword in goal_text for keyword in bounded_keywords)
        if use_bounded_preview:
            next_action = {
                "action": "manage_executor_workflow.run_bounded_preview",
                "label": "生成 bounded loop 预览",
                "reason": "使用 manage_executor_workflow action=run_bounded_preview 生成 bounded loop 预览，不直接运行。",
                "tool": "manage_executor_workflow",
                "params": {"action": "run_bounded_preview", "provider": provider},
                "risk_level": "preview",
                "requires_confirmation": True,
            }
        else:
            next_action = {
                "action": "manage_executor_workflow.run_once_preview",
                "label": "生成执行器运行预览",
                "reason": "使用 manage_executor_workflow action=run_once_preview 生成执行器运行预览，不直接运行。",
                "tool": "manage_executor_workflow",
                "params": {"action": "run_once_preview", "provider": provider, "execution_mode": "run"},
                "risk_level": "preview",
                "requires_confirmation": True,
            }

        return self._auto_preview_result(
            selected_workflow="executor_preflight",
            selection_reason=f"goal mentions executor; provider={provider}; read-only preflight completed",
            confidence=0.9,
            stop_reason=_STOP_EXECUTOR_PREFLIGHT,
            steps=steps,
            status="succeeded",
            requires_confirmation=False,
            next_actions=[next_action],
            result=result_payload,
        )

    # ----------------------------------------------------------------
    # Goal classification
    # ----------------------------------------------------------------

    @staticmethod
    def _classify_goal(goal: str) -> dict[str, Any]:
        goal_lower = goal.lower().strip()
        if not goal_lower:
            return {"selected_workflow": "project_status", "confidence": 1.0, "reason": "empty goal"}

        best_workflow = "project_status"
        best_confidence = 0.0
        best_reason = ""

        for keywords, workflow in _GOAL_CLASSIFIERS:
            matches = sum(1 for kw in keywords if kw in goal_lower)
            if matches > 0:
                confidence = min(0.5 + matches * 0.15, 1.0)
                if confidence > best_confidence:
                    best_confidence = confidence
                    best_workflow = workflow
                    best_reason = f"matched {matches} keyword(s) in {workflow} classifier"

        if best_workflow == "project_status":
            return {
                "selected_workflow": best_workflow,
                "confidence": 0.3,
                "reason": f"goal ({goal}) did not match a specific classifier; default to project_status",
            }

        return {
            "selected_workflow": best_workflow,
            "confidence": best_confidence,
            "reason": best_reason,
        }

    # ----------------------------------------------------------------
    # auto_preview result builder
    # ----------------------------------------------------------------

    @staticmethod
    def _copy_auto_preview_params(params: dict[str, Any]) -> dict[str, Any]:
        _PASSTHROUGH_FIELDS = [
            "goal", "provider", "reason", "max_files", "max_chars",
            "max_diff_chars", "include_diff_summary", "dry_run",
            "project_name", "first_version", "first_version_name",
            "file", "heading", "query", "new_content",
            "section_heading", "section_content", "after_heading",
            "stale_terms", "version", "target_version", "insert_after",
            "name", "description", "prompt", "repair_kinds",
            "old_text", "new_text", "patch_text",
            "message", "style", "scope_hint", "commit",
        ]
        out: dict[str, Any] = {}
        for field in _PASSTHROUGH_FIELDS:
            if field in params:
                out[field] = params[field]
        return out

    def _auto_preview_result(
        self,
        selected_workflow: str,
        selection_reason: str,
        confidence: float,
        stop_reason: str,
        steps: list[dict[str, Any]],
        status: str = "succeeded",
        requires_confirmation: bool = False,
        next_actions: list[dict[str, Any]] | None = None,
        preview_ids: list[str] | None = None,
        changed_files: list[str] | None = None,
        blockers: list[str] | None = None,
        warnings: list[str] | None = None,
        result: dict[str, Any] | None = None,
    ) -> 'CoreResult':
        all_blockers: list[str] = list(blockers or [])
        all_warnings: list[str] = list(warnings or [])
        all_changed_files: list[str] = list(changed_files or [])
        all_preview_ids: list[str] = list(preview_ids or [])
        for step in steps:
            for b in step.get("blockers", []):
                if isinstance(b, str) and b not in all_blockers:
                    all_blockers.append(b)
            for w in step.get("warnings", []):
                if isinstance(w, str) and w not in all_warnings:
                    all_warnings.append(w)
            for f in step.get("changed_files", []):
                if isinstance(f, str) and f not in all_changed_files:
                    all_changed_files.append(f)
            pid = step.get("preview_id")
            if isinstance(pid, str) and pid and pid not in all_preview_ids:
                all_preview_ids.append(pid)
    
        ok = all(s.get("ok") for s in steps) if steps else True
        if status == "failed":
            ok = False
    
        max_risk = STEP_RISK_INFO
        for step in steps:
            r = step.get("risk_level", STEP_RISK_INFO)
            if r == STEP_RISK_COMMIT:
                max_risk = STEP_RISK_COMMIT
            elif r == STEP_RISK_WRITE and max_risk != STEP_RISK_COMMIT:
                max_risk = STEP_RISK_WRITE
            elif r == STEP_RISK_PREVIEW and max_risk not in (STEP_RISK_COMMIT, STEP_RISK_WRITE):
                max_risk = STEP_RISK_PREVIEW
    
        return CoreResult(
            ok=ok,
            workflow="auto_preview",
            status=status,
            risk_level=max_risk,
            selected_workflow=selected_workflow,
            selection_reason=selection_reason,
            confidence=confidence,
            stop_reason=stop_reason,
            steps=steps,
            changed_files=all_changed_files,
            preview_ids=all_preview_ids,
            next_actions=next_actions or [],
            requires_confirmation=requires_confirmation,
            blockers=all_blockers,
            warnings=all_warnings,
            result=result,
        )
    def _step(
        self, name: str, tool: str, action: str, result: dict[str, Any] | CoreResult,
        risk_level: str,
    ) -> dict[str, Any]:
        result_dict = self._result_as_dict(result)
        return {
            "name": name,
            "tool": tool,
            "action": action,
            "ok": bool(result_dict.get("ok", False)),
            "risk_level": risk_level,
            "preview_id": result_dict.get("preview_id"),
            "changed_files": self._extract_changed_files(result_dict),
            "blockers": self._extract_blockers(result_dict),
            "warnings": self._extract_warnings(result_dict),
        }

    @staticmethod
    def _result_as_dict(result: dict | CoreResult) -> dict:
        if isinstance(result, CoreResult):
            return {
                "ok": result.ok,
                "workflow": result.workflow,
                "status": result.status,
                "risk_level": result.risk_level,
                "steps": result.steps,
                "changed_files": result.changed_files,
                "preview_ids": result.preview_ids,
                "next_actions": result.next_actions,
                "requires_confirmation": result.requires_confirmation,
                "blockers": result.blockers,
                "warnings": result.warnings,
                "result": result.result,
                "error_code": result.error_code,
                "message": result.message,
                "phase": result.phase,
                "selected_workflow": result.selected_workflow,
                "selection_reason": result.selection_reason,
                "confidence": result.confidence,
                "stop_reason": result.stop_reason,
                "partial": result.partial,
            }
        return result

    def _build_core_result(
        self,
        workflow: str,
        steps: list[dict[str, Any]],
        risk_level: str,
        status: str,
        requires_confirmation: bool,
        next_actions: list[dict[str, Any]] | None = None,
        preview_ids: list[str] | None = None,
        changed_files: list[str] | None = None,
        blockers: list[str] | None = None,
        warnings: list[str] | None = None,
        result: dict[str, Any] | None = None,
        phase: str | None = None,
    ) -> 'CoreResult':
        all_blockers: list[str] = []
        all_warnings: list[str] = []
        all_changed_files: list[str] = []
        all_preview_ids: list[str] = []
    
        for step in steps:
            for b in step.get("blockers", []):
                if isinstance(b, str) and b not in all_blockers:
                    all_blockers.append(b)
            for w in step.get("warnings", []):
                if isinstance(w, str) and w not in all_warnings:
                    all_warnings.append(w)
            for f in step.get("changed_files", []):
                if isinstance(f, str) and f not in all_changed_files:
                    all_changed_files.append(f)
            pid = step.get("preview_id")
            if isinstance(pid, str) and pid and pid not in all_preview_ids:
                all_preview_ids.append(pid)
    
        if blockers:
            for b in blockers:
                if b not in all_blockers:
                    all_blockers.append(b)
        if warnings:
            for w in warnings:
                if w not in all_warnings:
                    all_warnings.append(w)
        if changed_files:
            for f in changed_files:
                if f not in all_changed_files:
                    all_changed_files.append(f)
        if preview_ids:
            for p in preview_ids:
                if p not in all_preview_ids:
                    all_preview_ids.append(p)
    
        ok = all(s.get("ok") for s in steps) if steps else True
    
        return CoreResult(
            ok=ok,
            workflow=workflow,
            status=status,
            risk_level=risk_level,
            steps=steps,
            changed_files=all_changed_files,
            preview_ids=all_preview_ids,
            next_actions=next_actions or [],
            requires_confirmation=requires_confirmation,
            blockers=all_blockers,
            warnings=all_warnings,
            result=result,
            phase=phase,
        )
    def _error_result(
        self, workflow: str, error_code: str, message: str,
    ) -> 'CoreResult':
        return CoreResult(
            ok=False,
            workflow=workflow,
            error_code=error_code,
            message=message,
            status="failed",
            risk_level=STEP_RISK_BLOCKED,
            steps=[],
            changed_files=[],
            preview_ids=[],
            next_actions=[],
            requires_confirmation=False,
            blockers=[message],
            warnings=[],
            result=None,
        )
    def _extract_preview_ids(self, result: dict[str, Any] | CoreResult) -> list[str]:
        result_dict = self._result_as_dict(result)
        ids: list[str] = []
        for key in ("preview_id", "patch_id"):
            val = result_dict.get(key)
            if isinstance(val, str) and val.strip():
                if val.strip() not in ids:
                    ids.append(val.strip())
        patch_preview_ids = result_dict.get("patch_preview_ids")
        if isinstance(patch_preview_ids, list):
            for pid in patch_preview_ids:
                if isinstance(pid, str) and pid.strip() and pid.strip() not in ids:
                    ids.append(pid.strip())
        preview_ids_list = result_dict.get("preview_ids")
        if isinstance(preview_ids_list, list):
            for pid in preview_ids_list:
                if isinstance(pid, str) and pid.strip() and pid.strip() not in ids:
                    ids.append(pid.strip())
        return ids
    def _extract_changed_files(self, result: dict[str, Any] | CoreResult) -> list[str]:
        result_dict = self._result_as_dict(result)
        files: list[str] = []
        for key in ("changed_files", "files_to_commit", "committed_files"):
            val = result_dict.get(key)
            if isinstance(val, list):
                for f in val:
                    if isinstance(f, str) and f.strip():
                        if f.strip() not in files:
                            files.append(f.strip())
        return files
    def _extract_blockers(self, result: dict[str, Any] | CoreResult) -> list[str]:
        result_dict = self._result_as_dict(result)
        blockers: list[str] = []
        val = result_dict.get("blockers")
        if isinstance(val, list):
            for b in val:
                if isinstance(b, str) and b not in blockers:
                    blockers.append(b)
        commit_blockers = result_dict.get("commit_blockers")
        if isinstance(commit_blockers, list):
            for b in commit_blockers:
                if isinstance(b, str) and b not in blockers:
                    blockers.append(b)
        return blockers
    def _extract_warnings(self, result: dict[str, Any] | CoreResult) -> list[str]:
        result_dict = self._result_as_dict(result)
        warnings: list[str] = []
        val = result_dict.get("warnings")
        if isinstance(val, list):
            for w in val:
                if isinstance(w, str) and w not in warnings:
                    warnings.append(w)
        commit_warnings = result_dict.get("commit_warnings")
        if isinstance(commit_warnings, list):
            for w in commit_warnings:
                if isinstance(w, str) and w not in warnings:
                    warnings.append(w)
        return warnings
    def _source_only_next_actions(self) -> list[dict[str, Any]]:
        return [
            {
                "action": "source_onboarding",
                "label": "纳入 Runner 管理（推荐）",
                "reason": "项目尚未纳入 Runner 管理。onboarding 只创建 .colameta 基础结构，不创建开发版本。",
                "tool": "run_mcp_workflow",
                "params": {"workflow": "source_onboarding", "phase": "preview"},
                "risk_level": "info",
                "requires_confirmation": True,
            },
            {
                "action": "inspect_source_only",
                "label": "检查项目现状（底层）",
                "reason": "使用底层工具检查。",
                "tool": "manage_runner_plan",
                "params": {"action": "inspect"},
                "risk_level": "none",
                "requires_confirmation": False,
            },
            {
                "action": "bootstrap_plan_preview",
                "label": "生成纳管预览（底层）",
                "reason": "使用底层 manage_runner_plan。",
                "tool": "manage_runner_plan",
                "params": {"action": "bootstrap_preview"},
                "risk_level": "info",
                "requires_confirmation": True,
            },
        ]
