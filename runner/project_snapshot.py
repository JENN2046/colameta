from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable

from runner.development_target import resolve_development_target
from runner.executor_run_reports import ExecutorRunReportStore
from runner.executor_session import ExecutorSessionStore
from runner.mcp_runner_plan import MCPRunnerPlanManager
from runner.planning_bridge import PlanningBridge
from runner.project_identity import build_project_identity
from runner.source_review_bridge import SourceReviewBridge
from runner.runner_data_layout import classify_runner_path
from runner.runner_paths import resolve_project_runner_path


@dataclass
class ProjectSnapshot:
    project_identity: dict[str, Any]
    mode: str
    has_plan: bool
    has_state: bool
    git: dict[str, Any]
    working_tree_clean: bool | None
    plan_status: dict[str, Any]
    runner: dict[str, Any]
    executor: dict[str, Any]
    reports: dict[str, Any]
    partial_errors: list[dict[str, str]] = field(default_factory=list)


class ProjectSnapshotBuilder:
    def __init__(
        self,
        project_root: str,
        *,
        target: Any = None,
        source_review: SourceReviewBridge | None = None,
        planning_bridge: PlanningBridge | None = None,
        runner_plan_manager: MCPRunnerPlanManager | None = None,
        executor_run_report_store: ExecutorRunReportStore | None = None,
        project_identity_builder: Callable[[str], dict[str, Any]] | None = None,
    ) -> None:
        self.project_root = os.path.abspath(os.path.expanduser(project_root))
        if target is not None:
            self._target = target
        else:
            try:
                self._target = resolve_development_target(project_root)
            except Exception:
                self._target = None
        self.source_review = source_review or SourceReviewBridge()
        self.planning_bridge = planning_bridge or PlanningBridge()
        self.runner_plan_manager = runner_plan_manager or MCPRunnerPlanManager(self.project_root)
        self.executor_run_report_store = executor_run_report_store or ExecutorRunReportStore(self.project_root, target=self._target)
        self.project_identity_builder = project_identity_builder or build_project_identity

    def build(
        self,
        *,
        provider: str | None = None,
        include_reports: bool = True,
    ) -> ProjectSnapshot:
        partial_errors: list[dict[str, str]] = []
        project_identity = self._build_project_identity()

        target = self._target
        if target is not None:
            plan_path = target.plan_file
            state_path = target.state_file
        else:
            plan_path = resolve_project_runner_path(self.project_root, "plan.json")
            state_path = resolve_project_runner_path(self.project_root, "state.json")
        has_plan = os.path.isfile(plan_path)
        has_state = os.path.isfile(state_path)
        mode = self._determine_mode(has_plan=has_plan, has_state=has_state)

        git = self._build_git_status(project_identity=project_identity)
        working_tree_clean = git.get("working_tree_clean") if isinstance(git, dict) else None

        plan_status = self._build_plan_status(
            has_plan=has_plan,
            has_state=has_state,
            partial_errors=partial_errors,
        )
        runner = self._build_runner_status(
            mode=mode,
            partial_errors=partial_errors,
        )
        executor = self._build_executor_status(
            provider=provider,
            partial_errors=partial_errors,
        )
        reports = self._build_reports(
            include_reports=include_reports,
            partial_errors=partial_errors,
        )

        return ProjectSnapshot(
            project_identity=project_identity,
            mode=mode,
            has_plan=has_plan,
            has_state=has_state,
            git=git,
            working_tree_clean=working_tree_clean,
            plan_status=plan_status,
            runner=runner,
            executor=executor,
            reports=reports,
            partial_errors=partial_errors,
        )

    def _build_project_identity(self) -> dict[str, Any]:
        try:
            result = self.project_identity_builder(self.project_root)
            return result if isinstance(result, dict) else {"project_root": self.project_root}
        except Exception:
            return {"project_root": self.project_root}

    @staticmethod
    def _determine_mode(*, has_plan: bool, has_state: bool) -> str:
        if has_plan and has_state:
            return "runner_managed"
        if has_plan and not has_state:
            return "plan_without_state"
        if not has_plan and has_state:
            return "state_without_plan"
        return "source_only"

    def _build_git_status(self, *, project_identity: dict[str, Any]) -> dict[str, Any]:
        git_raw: dict[str, Any] = {"ok": False}
        try:
            result = self.source_review.get_git_status(self.project_root)
            if isinstance(result, dict):
                git_raw = result
        except Exception:
            git_raw = {"ok": False}

        git: dict[str, Any] = {"ok": False}
        if isinstance(git_raw, dict) and git_raw.get("ok"):
            changed = [str(f) for f in git_raw.get("changed_files", []) if isinstance(f, str)]
            untracked = [str(f) for f in git_raw.get("untracked_files", []) if isinstance(f, str)]
            dirty = bool(changed or untracked)
            blocking_changed = [f for f in changed if not self._is_ignored_runner_runtime_dirty_path(f)]
            blocking_untracked = [f for f in untracked if not self._is_ignored_runner_runtime_dirty_path(f)]
            ignored_runner_runtime = [f for f in [*changed, *untracked] if self._is_ignored_runner_runtime_dirty_path(f)]
            blocking_dirty = bool(blocking_changed or blocking_untracked)
            git = {
                "ok": True,
                "branch": git_raw.get("branch") or project_identity.get("git_branch"),
                "head": project_identity.get("git_head"),
                "head_short": project_identity.get("git_head_short"),
                "dirty": dirty,
                "changed_files": changed,
                "untracked_files": untracked,
                "working_tree_clean": not dirty,
                "blocking_working_tree_clean": not blocking_dirty,
                "blocking_changed_files": blocking_changed,
                "blocking_untracked_files": blocking_untracked,
                "ignored_runner_runtime_files": ignored_runner_runtime,
                "status_short": git_raw.get("status_short"),
            }
        return git

    def _build_plan_status(
        self,
        *,
        has_plan: bool,
        has_state: bool,
        partial_errors: list[dict[str, str]],
    ) -> dict[str, Any]:
        plan_blockers: list[str] = []
        plan_warnings: list[str] = []
        plan_summary: dict[str, Any] | None = None
        lint_status: dict[str, Any] | None = None
        lint_blocking_issue_count = 0
        lint_warning_count = 0
        try:
            plan_inspect = self.runner_plan_manager.inspect()
            if isinstance(plan_inspect, dict):
                plan_summary = plan_inspect.get("plan_summary")
                plan_blockers = list(plan_inspect.get("blockers", []))
                plan_warnings = list(plan_inspect.get("warnings", []))
                if isinstance(plan_summary, dict):
                    lint_status_val = plan_summary.get("lint_status")
                    lint_status = (
                        {
                            "has_lint": True,
                            "blocking_issue_count": int(plan_summary.get("lint_blocking_issue_count", 0)),
                            "warning_count": int(plan_summary.get("lint_warning_count", 0)),
                        }
                        if lint_status_val else {
                            "has_lint": False,
                            "blocking_issue_count": 0,
                            "warning_count": 0,
                        }
                    )
                    lint_blocking_issue_count = int(plan_summary.get("lint_blocking_issue_count", 0))
                    lint_warning_count = int(plan_summary.get("lint_warning_count", 0))
        except Exception as exc:
            partial_errors.append({"name": "plan_inspect", "error_code": "CONTEXT_ERROR", "message": str(exc)})

        return {
            "has_plan": has_plan,
            "has_state": has_state,
            "source_only": not has_plan,
            "can_bootstrap": True,
            "can_import": True,
            "plan_summary": plan_summary,
            "lint_status": lint_status,
            "lint_blocking_issue_count": lint_blocking_issue_count,
            "lint_warning_count": lint_warning_count,
            "blockers": plan_blockers,
            "warnings": plan_warnings,
        }

    def _build_runner_status(
        self,
        *,
        mode: str,
        partial_errors: list[dict[str, str]],
    ) -> dict[str, Any]:
        runner: dict[str, Any] = {
            "has_runner_state": False,
            "runner_status": None,
            "current_version": None,
            "current_version_status": None,
            "next_version": None,
            "next_version_status": None,
            "has_pending_versions": False,
            "pending_versions": [],
            "next_not_started_version": None,
            "pending_count": 0,
            "unreconciled_direct_version_count": 0,
            "unreconciled_direct_versions": [],
            "unreconciled_direct_scan_limit": 20,
        }
        try:
            runner_raw = self.planning_bridge.get_runner_status(self.project_root)
            runner["runner_status"] = runner_raw
            if isinstance(runner_raw, dict) and runner_raw.get("ok"):
                if mode != "source_only":
                    runner["has_runner_state"] = True
                    runner["current_version"] = runner_raw.get("current_version")
                    runner["current_version_status"] = runner_raw.get("current_version_status")
                    runner["next_version"] = runner_raw.get("next_version")
                    runner["next_version_status"] = runner_raw.get("next_version_status")
                    runner["has_pending_versions"] = bool(runner_raw.get("has_pending_versions"))
                    pending_versions = runner_raw.get("pending_versions")
                    runner["pending_versions"] = pending_versions if isinstance(pending_versions, list) else []
                    runner["next_not_started_version"] = runner_raw.get("next_not_started_version")
                    try:
                        runner["pending_count"] = int(runner_raw.get("pending_count", 0))
                    except Exception:
                        runner["pending_count"] = len(runner["pending_versions"])
                try:
                    runner["unreconciled_direct_version_count"] = int(runner_raw.get("unreconciled_direct_version_count", 0))
                except Exception:
                    runner["unreconciled_direct_version_count"] = 0
                direct_versions = runner_raw.get("unreconciled_direct_versions")
                runner["unreconciled_direct_versions"] = direct_versions if isinstance(direct_versions, list) else []
                try:
                    runner["unreconciled_direct_scan_limit"] = int(runner_raw.get("unreconciled_direct_scan_limit", 20))
                except Exception:
                    runner["unreconciled_direct_scan_limit"] = 20
        except Exception as exc:
            partial_errors.append({"name": "runner_status", "error_code": "CONTEXT_ERROR", "message": str(exc)})
        return runner

    def _build_executor_status(
        self,
        *,
        provider: str | None,
        partial_errors: list[dict[str, str]],
    ) -> dict[str, Any]:
        try:
            session_store = ExecutorSessionStore(self.project_root, target=self._target)
            session_status = session_store.get_status()
            continuation_preview = session_store.get_continuation_preview()
            has_session = bool(session_status.get("active", False)) if isinstance(session_status, dict) else False
            continuation_available = bool(continuation_preview.get("continuation_available")) if isinstance(continuation_preview, dict) else False

            decision_result = None
            if provider is not None:
                try:
                    decision_result = session_store.get_continuation_decision(requested_provider=provider)
                except Exception as exc:
                    partial_errors.append({"name": "executor_continuation_decision", "error_code": "CONTEXT_ERROR", "message": str(exc)})

            exec_risk = "none"
            exec_blockers: list[str] = []
            exec_warnings: list[str] = []
            should_start_new = True
            should_resume = False
            manual_confirmation = False

            if isinstance(continuation_preview, dict):
                exec_risk = continuation_preview.get("risk_level", "none")
                exec_blockers = list(continuation_preview.get("blockers", []))
                exec_warnings = list(continuation_preview.get("warnings", []))

            if isinstance(decision_result, dict):
                should_start_new = bool(decision_result.get("should_start_new", True))
                should_resume = bool(decision_result.get("should_resume", False))
                manual_confirmation = bool(decision_result.get("manual_confirmation_required", False))

            decision_owner = None
            optimization_goal = None
            recommended_default = None
            cache_hit_preference = None
            context_facts = None
            if isinstance(continuation_preview, dict):
                decision_owner = continuation_preview.get("decision_owner")
                optimization_goal = continuation_preview.get("optimization_goal")
                recommended_default = continuation_preview.get("recommended_default")
                cache_hit_preference = continuation_preview.get("cache_hit_preference")
                context_facts = continuation_preview.get("context_facts")
            return {
                "has_session": has_session,
                "continuation_available": continuation_available,
                "decision": decision_result.get("decision") if isinstance(decision_result, dict) else None,
                "should_resume": should_resume,
                "should_start_new": should_start_new,
                "manual_confirmation_required": manual_confirmation,
                "risk_level": exec_risk,
                "blockers": exec_blockers,
                "warnings": exec_warnings,
                "decision_owner": decision_owner,
                "optimization_goal": optimization_goal,
                "recommended_default": recommended_default,
                "cache_hit_preference": cache_hit_preference,
                "context_facts": context_facts,
            }
        except Exception as exc:
            partial_errors.append({"name": "executor", "error_code": "CONTEXT_ERROR", "message": str(exc)})
            return {
                "has_session": False,
                "continuation_available": False,
                "risk_level": "info",
                "blockers": [],
                "warnings": [],
                "error": True,
            }

    def _build_reports(
        self,
        *,
        include_reports: bool,
        partial_errors: list[dict[str, str]],
    ) -> dict[str, Any]:
        reports: dict[str, Any] = {"available": False, "count": 0, "latest": None, "message": "没有执行器运行报告。"}
        if not include_reports:
            return reports
        try:
            report_list = self.executor_run_report_store.list_reports(limit=5)
            latest_report = self.executor_run_report_store.get_report(latest=True, include_markdown=False)
            latest_entry = None
            if isinstance(latest_report, dict) and latest_report.get("ok") and isinstance(latest_report.get("report"), dict):
                latest_raw = latest_report.get("report") or {}
                raw_token_usage = latest_raw.get("token_usage")
                token_usage = dict(raw_token_usage) if isinstance(raw_token_usage, dict) else None
                latest_entry = {
                    "version": str(latest_raw.get("version", "")),
                    "provider": str(latest_raw.get("provider", "")),
                    "status": str(latest_raw.get("status", "")),
                    "finished_at": str(latest_raw.get("finished_at", "")),
                    "report_id": str(latest_raw.get("report_id", "")),
                    "json_file": str(latest_raw.get("json_file", "")),
                    "markdown_file": str(latest_raw.get("markdown_file", "")),
                    "token_usage": token_usage,
                }
            if report_list:
                reports = {
                    "available": True,
                    "count": len(report_list),
                    "latest": latest_entry,
                    "message": f"找到 {len(report_list)} 份执行器运行报告。",
                }
        except Exception as exc:
            partial_errors.append({"name": "reports", "error_code": "CONTEXT_ERROR", "message": str(exc)})
        return reports

    @staticmethod
    def _is_ignored_runner_runtime_dirty_path(path: str) -> bool:
        return classify_runner_path(path).get("category") in {
            "project_local",
            "runtime_ephemeral",
            "archive_private_or_exportable",
        }
