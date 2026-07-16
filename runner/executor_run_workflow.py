from __future__ import annotations

import os
import hashlib
from typing import TYPE_CHECKING, Any

from runner._internal_utils import run_git as _run_git_base
from runner.execution_profile import resolve_version_execution_provider
from runner.executor_events import EVENT_TYPES, ExecutorEventStore
from runner.executor_inventory import load_executor_inventory
from runner.executor_registry import (
    DEFAULT_EXECUTION_PROVIDER,
    get_executor_provider_display,
    is_supported_execution_provider,
    normalize_execution_provider,
)
from runner.executor_run_reports import ExecutorRunReportStore
from runner.executor_session import ExecutorSessionStore
from runner.git_diff_helper import collect_git_diff_name_paths
from runner.path_glob import match_any as glob_match_any
from runner.plan_allowed_files import current_plan_allowed_patterns
from runner.runner_settings import RunnerSettingsStore
from runner.runner_data_layout import classify_runner_path
from runner.runner_paths import (
    is_project_runner_path,
    resolve_project_runner_dir,
    resolve_project_runner_plan_path,
)
from runner.stage_parallel_shard_input_overlay import load_valid_overlay
from runner.sensitive_redaction import redact_sensitive_text
from runner.source_review_bridge import SourceReviewBridge
from runner.state_machine import RunnerStateMachine
from runner.state_mutation import ExecutorRunLifecycleStatePersistMutation, RunnerStateMutationService
from runner.state_store import StateStore
from runner.plan_loader import PlanLoader
from runner.work_item_governance.references import (
    optional_plan_work_item_reference_rejections,
    resolve_execution_attempt_binding,
)
from runner.workspace import ProjectWorkspace
from runner.work_item_commands import WorkItemCommandGateway
from runner.work_item_governance.errors import WorkItemGovernanceError

if TYPE_CHECKING:
    from runner.development_target import ResolvedDevelopmentTarget


FLOW_SOURCE = "manage_executor_workflow"

_EXECUTION_MODES = {"run", "fix"}
_SCOPE_BLOCK_STATES = {"FAILED", "BLOCKED", "VIOLATION", "BLOCKED_BY_SCOPE_VIOLATION"}
_RUN_BLOCKED_STATUS_CODES = {
    "VERSION_PASSED": ("VERSION_PASSED", "当前版本已通过。"),
    "COMPLETED": ("COMPLETED", "所有版本已完成。"),
    "BLOCKED_BY_ACCEPTANCE_FAILURE": ("BLOCKED_BY_ACCEPTANCE_FAILURE", "当前版本被验收失败阻断。"),
    "BLOCKED_BY_MAX_FIX_ATTEMPTS": ("BLOCKED_BY_MAX_FIX_ATTEMPTS", "当前版本已达到最大修复次数。"),
}
_EXECUTOR_ERROR_CODES = {
    "PI_NOT_FOUND",
    "PI_UNAUTHORIZED",
    "CODEX_NOT_FOUND",
    "CODEX_UNAUTHORIZED",
    "OPENCODE_NOT_FOUND",
    "OPENCODE_UNAUTHORIZED",
    "OPENCODE_RUN_UNSUPPORTED",
    "FIX_PROMPT_MISSING",
    "EXECUTOR_FAILED",
    "EXECUTOR_MODEL_QUOTA_EXHAUSTED",
    "REQUIRED_CHANGED_FILES_MISSING",
}
_RESOURCE_EXHAUSTION_MARKERS = (
    "rate limit",
    "quota",
    "resource exhausted",
    "resources exhausted",
    "insufficient credits",
    "insufficient credit",
    "out of credits",
    "usage limit",
    "quota exceeded",
    "too many requests",
)
_INFRA_INTERRUPTION_TEXT_MARKERS = (
    "unknown certificate verification error",
    "certificate verification",
    "certificate verify failed",
    "ssl certificate",
    "tls certificate",
    "x509",
    "network failure",
    "network error",
    "connection refused",
    "connection reset",
    "timed out",
    "timeout",
    "authentication failed",
    "unauthorized",
    "not authenticated",
    "invalid api key",
    "login required",
)
_FAILED_PROVIDER_STATUSES = {
    "failed",
    "error",
    "timed_out",
    "timeout",
    "cancelled",
    "canceled",
    "interrupted",
    "crashed",
    "aborted",
}
_COMPLETED_PROVIDER_STATUSES = {
    "completed",
    "succeeded",
    "success",
    "passed",
}
_PROVIDER_COMPLETION_TEXT_MARKERS = (
    "已完成",
    "validation_results",
    "passed:",
    " passed",
    "compileall 通过",
    "git diff --check 通过",
    "executor_report_available",
)


class ExecutorRunOnceService:
    def __init__(self, project_root: str, target: ResolvedDevelopmentTarget | None = None):
        self.project_root = os.path.abspath(os.path.expanduser(project_root))
        self._target = target if target is not None else self._resolve_default_target()
        self._source_review = SourceReviewBridge()
        self._event_store = ExecutorEventStore(project_root)

    def _resolve_default_target(self) -> ResolvedDevelopmentTarget | None:
        try:
            from runner.development_target import resolve_development_target

            target = resolve_development_target(self.project_root)
            if os.path.exists(target.plan_file) or os.path.exists(target.state_file):
                return target
        except Exception:
            return None
        return None

    _EVENT_PHASE_MESSAGE: dict[str, tuple[str, str]] = {
        "run_claimed": ("claim", "Executor run claimed"),
        "worker_started": ("worker", "Executor worker started"),
        "executor_preparing": ("preparation", "Executor preparing"),
        "executor_started": ("executor", "Executor started"),
        "executor_finished": ("executor", "Executor finished"),
        "executor_failed": ("executor", "Executor failed"),
        "validation_started": ("validation", "Validation started"),
        "validation_finished": ("validation", "Validation finished"),
        "report_written": ("report", "Executor report written"),
        "run_completed": ("finalize", "Executor run completed"),
        "run_failed": ("finalize", "Executor run failed"),
        "git_diff_changed": ("diff", "Git working tree changed"),
        "heartbeat": ("heartbeat", "Executor heartbeat"),
    }

    def _maybe_write_event(self, run_id: str, event_type: str, data: dict[str, Any] | None = None, event_context: dict[str, Any] | None = None) -> None:
        if not run_id:
            return
        d = data or {}
        if event_context is None:
            event_context = {
                "run_id": d.get("run_id", run_id),
                "preview_id": d.get("preview_id", ""),
                "version": d.get("version") or d.get("current_version", ""),
                "provider": d.get("provider", ""),
                "execution_mode": d.get("execution_mode", ""),
            }
        phase, msg = self._EVENT_PHASE_MESSAGE.get(event_type, ("", ""))
        event_context["phase"] = event_context.get("phase") or phase
        event_context["message"] = event_context.get("message") or msg
        if "level" not in event_context:
            event_context["level"] = d.get("level", "info")
        self._event_store.append(run_id, event_type, data=d, event_context=event_context)

    def preflight(self, provider: str, execution_mode: str = "run") -> dict[str, Any]:
        project_root = self.project_root
        target = self._target
        if target is not None:
            runner_dir = target.runner_dir
            plan_file = target.plan_file
            state_file = target.state_file
        else:
            runner_dir = resolve_project_runner_dir(project_root)
            plan_file = os.path.join(runner_dir, "plan.json")
            state_file = os.path.join(runner_dir, "state.json")
        overlay = load_valid_overlay(project_root)
        runner_input_source = (
            "stage_parallel_shard_overlay"
            if overlay is not None and os.path.abspath(str(overlay.get("plan_file") or "")) == os.path.abspath(plan_file)
            else "project_runner"
        )
        blocks: list[dict[str, str]] = []
        warnings: list[str] = []

        mode = self._normalize_execution_mode(execution_mode)
        if mode is None:
            blocks.append({"code": "EXECUTION_MODE_INVALID", "message": "execution_mode 仅支持 run 或 fix。"})
            mode = "run"

        provider_norm = self._normalize_provider(provider)
        if not provider_norm:
            blocks.append({"code": "PROVIDER_REQUIRED", "message": "provider 不能为空。"})
            provider_norm = DEFAULT_EXECUTION_PROVIDER
        elif not is_supported_execution_provider(provider_norm):
            blocks.append({"code": "PROVIDER_INVALID", "message": f"不支持的执行器：{provider_norm}，仅支持 pi、codex、opencode。"})
            provider_norm = normalize_execution_provider(provider_norm, default=DEFAULT_EXECUTION_PROVIDER)

        git_context = self._collect_git_context()
        dirty_context = self._classify_git_changed_files(git_context["git_status_short"])
        if git_context["git_status_error"]:
            blocks.append({"code": "GIT_STATUS_UNAVAILABLE", "message": f"读取 git status 失败：{git_context['git_status_error']}"})
        if git_context.get("no_git_head"):
            blocks.append({
                "code": "NO_GIT_HEAD",
                "message": "当前 Git 仓库还没有初始提交。请先提交 Runner 共享项目记忆文件和项目初始文件，创建初始 HEAD，再运行执行器。",
            })
        elif git_context["head_error"]:
            warnings.append(f"读取 HEAD 失败：{git_context['head_error']}")
        if git_context["branch_error"] and not git_context.get("no_git_head"):
            warnings.append(f"读取分支失败：{git_context['branch_error']}")
        if dirty_context["ignored_runner_local_files"]:
            warnings.append("检测到 Runner 本机状态文件改动；这些文件不属于 Git baseline 提交建议。")
        if dirty_context["ignored_runner_runtime_files"]:
            warnings.append("检测到 Runner 运行态文件改动；这些文件不属于 Git baseline 提交建议。")
        if dirty_context["ignored_runner_archive_files"]:
            warnings.append("检测到 Runner 报告/审计归档文件改动；这些文件不属于默认 Git baseline。")
        if dirty_context["preexisting_runner_files"]:
            warnings.append("检测到 Runner 元数据文件改动，不影响执行器启动。")

        current_version: str | None = None
        current_version_index = -1
        runner_status = ""
        execution_branch_status = "NOT_EVALUATED"
        execution_branch_required = False
        execution_branch_ready = False

        plan_data: dict[str, Any] | None = None
        state_data: dict[str, Any] | None = None

        if not os.path.isdir(runner_dir):
            blocks.append({"code": "NO_RUNNER_DIR", "message": "项目缺少 ColaMeta Runner 元数据目录。"})
        if not os.path.isfile(plan_file):
            blocks.append({"code": "NO_PLAN_FILE", "message": "缺少 plan.json，项目可能尚未纳管。"})
        if not os.path.isfile(state_file):
            blocks.append({"code": "NO_STATE_FILE", "message": "缺少 state.json。"})

        if os.path.isfile(plan_file):
            plan_data = self._load_plan(plan_file)
            if not isinstance(plan_data, dict):
                blocks.append({"code": "PLAN_INVALID", "message": "plan.json 格式无效。"})

        if os.path.isfile(state_file):
            state_data = self._load_state(state_file)
            if not isinstance(state_data, dict):
                blocks.append({"code": "STATE_INVALID", "message": "state.json 格式无效。"})

        if isinstance(state_data, dict):
            raw_version = state_data.get("current_version")
            current_version = raw_version if isinstance(raw_version, str) and raw_version.strip() else None
            current_version_index = self._safe_int(state_data.get("current_version_index"), default=-1)
            status_raw = state_data.get("status")
            runner_status = status_raw.strip() if isinstance(status_raw, str) else ""

        if isinstance(plan_data, dict) and isinstance(state_data, dict):
            normalized_status = self._normalized_runner_status_from_state(plan_file, state_file)
            if normalized_status:
                runner_status = normalized_status

        if not current_version:
            blocks.append({"code": "NO_CURRENT_VERSION", "message": "当前没有可执行版本。"})

        plan_versions = plan_data.get("versions", []) if isinstance(plan_data, dict) else []
        version_spec: dict[str, Any] | None = None
        if isinstance(plan_versions, list) and 0 <= current_version_index < len(plan_versions):
            candidate = plan_versions[current_version_index]
            if isinstance(candidate, dict):
                version_spec = candidate
        else:
            if current_version_index < 0:
                blocks.append({"code": "INVALID_VERSION_INDEX", "message": "current_version_index 无效。"})

        if current_version and version_spec is None:
            blocks.append({"code": "VERSION_NOT_FOUND", "message": "plan.versions 找不到当前版本。"})

        if isinstance(plan_data, dict):
            binding_rejections = optional_plan_work_item_reference_rejections(plan_data)
            if isinstance(version_spec, dict):
                binding_rejections.extend(optional_plan_work_item_reference_rejections(version_spec))
            if binding_rejections:
                blocks.append({
                    "code": "WORK_ITEM_BINDING_INVALID",
                    "message": f"plan Work Item binding 无效：{binding_rejections}",
                })

        if mode == "run":
            status_block = _RUN_BLOCKED_STATUS_CODES.get(runner_status)
            if status_block:
                blocks.append({"code": status_block[0], "message": status_block[1]})
        if mode == "fix" and runner_status != "FIX_PROMPT_READY":
            blocks.append({"code": "FIX_PROMPT_NOT_READY", "message": "fix 模式要求 state.status=FIX_PROMPT_READY。"})

        if dirty_context["blocking_files"] and not git_context.get("no_git_head"):
            blocks.append(self._build_dirty_git_block(git_context["git_status_short"]))

        mainline_provider = self._load_settings_provider(project_root)
        resolved_provider = provider_norm
        if isinstance(plan_data, dict) and isinstance(version_spec, dict):
            resolved_provider = self._resolve_provider_from_dict(
                plan_data=plan_data,
                version_spec=version_spec,
                fallback_provider=mainline_provider,
            )

        execution_branch_required = False
        execution_branch_status = "NOT_REQUIRED"
        execution_branch_ready = True

        inventory_raw: dict[str, Any]
        try:
            inventory_raw = load_executor_inventory(project_root)
        except Exception:
            inventory_raw = {"available": False}

        if self._provider_unavailable(inventory_raw, resolved_provider):
            blocks.append({"code": "PROVIDER_UNAVAILABLE", "message": "执行器 provider 当前不可用。"})

        attempt_binding = (
            resolve_execution_attempt_binding(plan_data, version_spec)
            if isinstance(plan_data, dict)
            else {}
        )
        if attempt_binding:
            try:
                gateway = WorkItemCommandGateway(project_root)
                governance_status = gateway.execute("get_work_item_governance_status", {})
                if governance_status.get("enabled") is not True:
                    blocks.append({
                        "code": "WORK_ITEM_ATTEMPT_GOVERNANCE_DISABLED",
                        "message": "plan 已绑定 Work Item Attempt，但 Work Item governance 未启用。",
                    })
                elif not isinstance(governance_status.get("ledger_schema_version"), int):
                    blocks.append({
                        "code": "WORK_ITEM_ATTEMPT_LEDGER_MISSING",
                        "message": "plan 已绑定 Work Item Attempt，但 Work Item governance ledger 不存在。",
                    })
                else:
                    dispatch = gateway.execute(
                        "get_execution_attempt_dispatch_authority",
                        {
                            "work_item_id": attempt_binding["work_item_id"],
                            "task_version": attempt_binding["task_version"],
                            "attempt_id": attempt_binding["attempt_id"],
                        },
                    )
                    if dispatch.get("dispatch_authorized") is not True:
                        blocks.append({
                            "code": "WORK_ITEM_ATTEMPT_DISPATCH_DENIED",
                            "message": f"Work Item Attempt 不允许 runtime dispatch：{dispatch.get('reason_codes', [])}",
                        })
            except WorkItemGovernanceError as exc:
                blocks.append({
                    "code": "WORK_ITEM_ATTEMPT_DISPATCH_INVALID",
                    "message": f"Work Item Attempt dispatch 校验失败：{exc.code}",
                })

        result = {
            "ok": True,
            "preflight_blocked": len(blocks) > 0,
            "blocks": blocks,
            "warnings": warnings,
            "current_version": current_version,
            "current_version_index": current_version_index,
            "current_head": git_context["current_head"],
            "current_branch": git_context["current_branch"],
            "runner_status": runner_status,
            "provider": provider_norm,
            "resolved_provider": resolved_provider,
            "mainline_provider": mainline_provider,
            "git_status_short": git_context["git_status_short"],
            "git_dirty": git_context["git_dirty"],
            "blocking_git_status_short": dirty_context["blocking_status_short"],
            "blocking_git_changed_files": dirty_context["blocking_files"],
            "runner_memory_files": dirty_context["runner_memory_files"],
            "preexisting_runner_files": dirty_context["preexisting_runner_files"],
            "ignored_runner_local_files": dirty_context["ignored_runner_local_files"],
            "ignored_runner_runtime_files": dirty_context["ignored_runner_runtime_files"],
            "ignored_runner_archive_files": dirty_context["ignored_runner_archive_files"],
            "execution_branch_status": execution_branch_status,
            "execution_branch_required": execution_branch_required,
            "execution_branch_ready": execution_branch_ready,
            "execution_mode": mode,
            "executor_inventory": inventory_raw,
            "runner_input_source": runner_input_source,
            "runner_input_overlay": self._compact_runner_input_overlay(overlay) if runner_input_source == "stage_parallel_shard_overlay" else None,
        }
        result.update(attempt_binding)
        return result

    def _compact_runner_input_overlay(self, overlay: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(overlay, dict):
            return None
        return {
            "stage_id": overlay.get("stage_id"),
            "parallel_group_id": overlay.get("parallel_group_id"),
            "task_id": overlay.get("task_id"),
            "version": overlay.get("version"),
            "allowed_files": overlay.get("allowed_files", []),
        }

    def _normalized_runner_status_from_state(self, plan_file: str, state_file: str) -> str:
        try:
            loader = PlanLoader()
            plan = loader.load_plan(plan_file)
            state = StateStore().load_state(state_file)
            RunnerStateMachine(plan, state).normalize_passed_current_version_status()
            return str(state.status or "")
        except Exception:
            return ""

    def run_once(
        self,
        provider: str,
        execution_mode: str = "run",
        include_diff_summary: bool = True,
        include_report_markdown: bool = False,
        max_report_chars: int = 30000,
        reason: str = "",
        executor_session_mode: str = "auto",
        model: str | None = None,
        model_source: str | None = None,
        reasoning_effort: str | None = None,
        reasoning_effort_source: str | None = None,
        run_id: str = "",
        preview_id: str = "",
        preview_claimed_at: str = "",
        preview_claim_status: str = "",
    ) -> dict[str, Any]:
        provider_norm = self._normalize_provider(provider) or DEFAULT_EXECUTION_PROVIDER
        mode = self._normalize_execution_mode(execution_mode)
        if mode is None:
            return self._executor_error(
                provider_norm,
                "EXECUTION_MODE_INVALID",
                "execution_mode 仅支持 run 或 fix。",
                self._get_git_head(),
                execution_mode,
            )

        preflight_result = self.preflight(provider=provider_norm, execution_mode=mode)
        if preflight_result.get("preflight_blocked"):
            message = "preflight 未通过，run_once 未执行。"
            return {
                "ok": False,
                "action": "run_once",
                "status": "blocked",
                "error_code": "PREFLIGHT_BLOCKED",
                "message": message,
                "provider": provider_norm,
                "execution_mode": mode,
                "classification": "blocked_preflight",
                "next_actions": self._build_next_actions("blocked_preflight", provider_norm, mode),
                "blocks": preflight_result.get("blocks", []),
                "warnings": preflight_result.get("warnings", []),
                "current_version": preflight_result.get("current_version"),
                "current_version_index": preflight_result.get("current_version_index"),
                "runner_status": preflight_result.get("runner_status"),
                "git_head_before": preflight_result.get("current_head"),
                "git_head_after": preflight_result.get("current_head"),
                "git_status_after": preflight_result.get("git_status_short", ""),
                "reason": reason,
            }

        preexisting_runner_files_set = set(preflight_result.get("preexisting_runner_files", []))

        project_root = self.project_root
        workspace = ProjectWorkspace.from_project_path(project_root)
        workspace.ensure_directories()

        try:
            loader = PlanLoader()
            plan = loader.load_plan(workspace.plan_file)
            plan.project_root = workspace.workspace_root
            plan.logs_dir = workspace.logs_dir
            plan.runtime_dir = workspace.runtime_dir
            plan.state_file = workspace.state_file
            if not os.path.isabs(plan.rules_file):
                plan.rules_file = workspace.rules_file
            loader.validate_plan(plan)
            store = StateStore()
            state = store.load_state(workspace.state_file)
            baseline_updated_at = state.updated_at
            state_mutations = RunnerStateMutationService()
        except Exception as exc:
            return self._executor_error(
                provider_norm,
                "PLAN_OR_STATE_LOAD_FAILED",
                f"加载 plan/state 失败：{exc}",
                preflight_result.get("current_head"),
                mode,
            )

        current_version_str = str(state.current_version or "")

        base_ctx: dict[str, Any] = {
            "run_id": run_id,
            "preview_id": preview_id,
            "version": current_version_str,
            "provider": provider_norm,
            "execution_mode": mode,
        }
        base_ctx.update(resolve_execution_attempt_binding(plan, current_version_str))

        self._maybe_write_event(run_id, "run_claimed", {
            "run_id": run_id,
            "preview_id": preview_id,
            "provider": provider_norm,
            "execution_mode": mode,
        }, event_context=base_ctx)

        machine = RunnerStateMachine(plan, state)
        is_fix = mode == "fix"
        head_before = preflight_result.get("current_head")
        continuation_decision_before = self._safe_get_continuation_decision(provider_norm)
        resume_invocation_before = self._safe_get_resume_invocation_preview(provider_norm)

        allow_no_changes = False
        required_changed_files: list[str] = []
        for v in plan.versions:
            if str(v.version) == current_version_str:
                allow_no_changes = bool(getattr(v, "allow_no_changes", False))
                required_changed_files = list(getattr(v, "required_changed_files", []) or [])
                break

        self._maybe_write_event(run_id, "worker_started", {
            "run_id": run_id,
            "provider": provider_norm,
            "execution_mode": mode,
        }, event_context=base_ctx)

        self._maybe_write_event(run_id, "heartbeat", {
            "lifecycle_point": "worker_started",
        }, event_context={**base_ctx, "phase": "heartbeat", "message": "Executor heartbeat"})

        self._maybe_write_event(run_id, "executor_preparing", {
            "provider": provider_norm,
            "execution_mode": mode,
            "is_fix": is_fix,
            "current_version": str(state.current_version or ""),
        }, event_context=base_ctx)

        execution_result = self._execute_provider(
            provider=provider_norm,
            plan=plan,
            state=state,
            workspace=workspace,
            is_fix=is_fix,
            execution_mode=mode,
            head_before=head_before,
            executor_session_mode=executor_session_mode,
            model_override=model,
            reasoning_effort_override=reasoning_effort,
            run_id=run_id,
            event_context=base_ctx,
        )

        state_mutations.persist_executor_run_post_provider_state(
            state=state,
            state_file=workspace.state_file,
            mutation=ExecutorRunLifecycleStatePersistMutation(
                lifecycle_point="post_provider_execution",
            ),
            baseline_updated_at=baseline_updated_at,
        )
        head_after = self._get_git_head()

        if not execution_result.get("ok"):
            error_code = str(execution_result.get("error_code", ""))
            error_message = str(execution_result.get("message", ""))
            git_status_after = self._get_git_status_short()
            changed_files_after_all = self._get_changed_files_from_git()
            changed_files_after = [f for f in changed_files_after_all if f not in preexisting_runner_files_set]
            raw_execution_result = execution_result.pop("_execution_result", None)
            execution_result.pop("_report", None)
            interruption_kind = str(execution_result.get("interruption_kind", "") or "")
            classification = str(
                execution_result.get("classification")
                or self.classify_result(
                    run_status="",
                    scope_status="",
                    changed_files=[],
                    git_status_after=git_status_after,
                    diff_summary="",
                    preflight_blocked=False,
                    executor_error_code=error_code,
                )
            )
            recovery_options = execution_result.get("recovery_options")
            if not isinstance(recovery_options, list) or interruption_kind:
                recovery_options = self._build_recovery_options(
                    classification=classification,
                    provider=provider_norm,
                    execution_mode=mode,
                    has_partial_worktree=bool(changed_files_after),
                )
            execution_result["classification"] = classification
            execution_result["interruption_kind"] = interruption_kind
            execution_result["recovery_options"] = recovery_options
            report_id = ""
            if classification in {"executor_resource_exhausted", "executor_infrastructure_failed"}:
                interruption_report = self._record_executor_interruption_report(
                    state=state,
                    plan=plan,
                    provider=provider_norm,
                    execution_mode=mode,
                    commit_head_before=head_before,
                    commit_head_after=head_after,
                    raw_execution_result=raw_execution_result,
                    execution_result=execution_result,
                    continuation_decision_before=continuation_decision_before,
                    resume_invocation_before=resume_invocation_before,
                    execution_lineage_extra=self._build_preview_lineage_extra(
                        run_id=run_id,
                        preview_id=preview_id,
                        preview_claimed_at=preview_claimed_at,
                        preview_claim_status=preview_claim_status,
                        model=model,
                        model_source=model_source or str(execution_result.get("model_source") or ("request" if model else "")) or None,
                        reasoning_effort=reasoning_effort,
                        reasoning_effort_source=reasoning_effort_source,
                    ),
                    changed_files=changed_files_after,
                    preexisting_runner_files=preexisting_runner_files_set,
                    include_report_markdown=include_report_markdown,
                    max_report_chars=max_report_chars,
                )
                report_id = str(interruption_report.get("latest_report_id") or "")
                if report_id:
                    execution_result["latest_report_id"] = report_id
                report_summary = interruption_report.get("report_summary")
                if isinstance(report_summary, dict) and report_summary:
                    execution_result["report_summary"] = report_summary
                if include_report_markdown and "report" in interruption_report:
                    execution_result["report"] = interruption_report.get("report")
            self._maybe_write_event(run_id, "executor_failed", {
                "error_code": error_code,
                "message": error_message,
                "classification": classification,
                "interruption_kind": interruption_kind,
                "report_id": report_id,
                "recovery_options": [
                    item.get("option")
                    for item in recovery_options
                    if isinstance(item, dict) and item.get("option")
                ],
            }, event_context=base_ctx)
            execution_result["next_actions"] = self._build_next_actions(
                classification,
                provider_norm,
                mode,
                has_partial_worktree=bool(changed_files_after),
            )
            execution_result["git_head_after"] = head_after
            execution_result["git_status_after"] = git_status_after
            execution_result["changed_files"] = changed_files_after
            execution_result["reason"] = reason
            self._maybe_write_event(run_id, "run_failed", {
                "error_code": error_code,
                "message": error_message,
                "classification": classification,
                "interruption_kind": interruption_kind,
                "report_id": report_id,
            }, event_context=base_ctx)
            return execution_result

        post_provider_written_at = state.updated_at

        self._maybe_write_event(run_id, "validation_started", {
            "is_fix": is_fix,
        }, event_context=base_ctx)

        run_result = (
            machine.mark_fix_model_done_and_run_acceptance()
            if is_fix
            else machine.mark_model_done_and_run_acceptance()
        )
        state_mutations.persist_executor_run_post_acceptance_state(
            state=state,
            state_file=workspace.state_file,
            mutation=ExecutorRunLifecycleStatePersistMutation(
                lifecycle_point="post_acceptance_state_machine",
            ),
            baseline_updated_at=post_provider_written_at,
        )

        failed_indexes, command_results = self._build_acceptance_command_results(run_result)
        run_status = run_result.status

        self._maybe_write_event(run_id, "validation_finished", {
            "run_status": str(run_status or ""),
            "failed_count": len(failed_indexes),
            "total_commands": len(command_results),
        }, event_context=base_ctx)

        changed_files_early_all = self._collect_executor_report_changed_files(run_result)
        changed_files_early = [f for f in changed_files_early_all if f not in preexisting_runner_files_set]
        runner_metadata_changed = [f for f in changed_files_early_all if f in preexisting_runner_files_set]
        if changed_files_early_all:
            self._maybe_write_event(run_id, "git_diff_changed", {
                "changed_file_count": len(changed_files_early),
                "changed_files": changed_files_early[:50],
                "runner_metadata_changed_files": runner_metadata_changed[:50],
                "runner_metadata_changed_file_count": len(runner_metadata_changed),
            }, event_context=base_ctx)

        completion_evidence = self._compute_completion_evidence(
            project_root=project_root,
            plan=plan,
            state=state,
            run_status=run_status,
            provider=provider_norm,
            changed_files=changed_files_early,
            command_results=command_results,
            allow_no_changes=allow_no_changes,
        )
        no_changes_blocked = (
            completion_evidence.get("mode") == "validation_only_no_diff"
            and completion_evidence.get("allowed_files_present") is True
        )
        if no_changes_blocked:
            post_acceptance_written_at = state.updated_at
            state = machine.mark_blocked_by_no_changes(
                state.current_version_index,
                completion_evidence,
                recorded_at=getattr(run_result, "completed_at", None) or state.updated_at,
            )
            state_mutations.persist_executor_run_post_acceptance_state(
                state=state,
                state_file=workspace.state_file,
                mutation=ExecutorRunLifecycleStatePersistMutation(
                    lifecycle_point="post_acceptance_no_changes_block",
                ),
                baseline_updated_at=post_acceptance_written_at,
            )
        report_status = "failed" if no_changes_blocked else ("completed" if run_status == "PASSED" else "failed")

        self._record_executor_run_report(
            state=state,
            plan=plan,
            provider=provider_norm,
            execution_mode=mode,
            status=report_status,
            commit_head_before=head_before,
            commit_head_after=head_after,
            execution_result=execution_result.get("_execution_result"),
            run_result=run_result,
            continuation_decision_before=continuation_decision_before,
            resume_invocation_before=resume_invocation_before,
            execution_lineage_extra=self._build_preview_lineage_extra(
                run_id=run_id,
                preview_id=preview_id,
                preview_claimed_at=preview_claimed_at,
                preview_claim_status=preview_claim_status,
                model=model,
                model_source=model_source or str(execution_result.get("model_source") or ("request" if model else "")) or None,
                reasoning_effort=reasoning_effort,
                reasoning_effort_source=reasoning_effort_source,
            ),
            completion_evidence=completion_evidence,
            preexisting_runner_files=preexisting_runner_files_set,
        )

        self._maybe_write_event(run_id, "heartbeat", {
            "lifecycle_point": "before_report",
        }, event_context={**base_ctx, "phase": "heartbeat", "message": "Executor heartbeat"})

        self._maybe_write_event(run_id, "report_written", {
            "report_status": report_status,
            "run_status": str(run_status or ""),
        }, event_context=base_ctx)

        post_data = self.collect_post_run_data(
            project_root=project_root,
            include_diff_summary=include_diff_summary,
            include_report_markdown=include_report_markdown,
            max_report_chars=max_report_chars,
            preexisting_runner_files=preexisting_runner_files_set,
        )

        scope_status = "NOT_CHECKED"
        if getattr(run_result, "scope_check", None) is not None:
            scope_status = str(getattr(run_result.scope_check, "status", "NOT_CHECKED") or "NOT_CHECKED")

        changed_files = post_data.get("changed_files", [])
        required_changed_files_missing: list[str] = []
        if required_changed_files and run_status == "PASSED":
            changed_set = set(changed_files)
            required_changed_files_missing = [f for f in required_changed_files if f not in changed_set]

        classification = (
            "required_changed_files_missing" if required_changed_files_missing else
            "executor_no_changes" if no_changes_blocked else self.classify_result(
                run_status=run_status,
                scope_status=scope_status,
                changed_files=changed_files,
                git_status_after=post_data.get("git_status_short", ""),
                diff_summary=post_data.get("diff_summary", ""),
                preflight_blocked=False,
                executor_error_code="",
            )
        )
        no_changes_message = "执行器退出且验收命令通过，但没有产生 allowed_files 内的业务改动。"
        blockers = list(post_data.get("blockers", []))
        if no_changes_blocked:
            blockers.append(no_changes_message)

        had_error = bool(no_changes_blocked or required_changed_files_missing)
        if required_changed_files_missing:
            missing_msg = f"执行器未修改以下必需文件：{', '.join(required_changed_files_missing)}"
            blockers.append(missing_msg)
            completion_evidence["missing_required_files"] = required_changed_files_missing
            completion_evidence["required_changed_files"] = required_changed_files

        final_ok = not had_error
        terminal_event_data = {
            "run_status": str(run_status or ""),
            "classification": classification,
            "changed_file_count": len(changed_files),
            "report_status": report_status,
            "changed_files": changed_files[:50],
            "completion_evidence_mode": str(completion_evidence.get("mode") or ""),
            "executor_changed_files": list(completion_evidence.get("executor_changed_files") or [])[:50],
            "latest_report_id": post_data.get("latest_report_id"),
        }
        if not final_ok:
            terminal_event_data["error_code"] = "REQUIRED_CHANGED_FILES_MISSING" if required_changed_files_missing else (
                "EXECUTOR_NO_CHANGES" if no_changes_blocked else ""
            )
        self._maybe_write_event(
            run_id,
            "run_completed" if final_ok else "run_failed",
            terminal_event_data,
            event_context=base_ctx,
        )

        return {
            "ok": final_ok,
            "action": "run_once",
            "status": "failed" if had_error else "completed",
            "error_code": "REQUIRED_CHANGED_FILES_MISSING" if required_changed_files_missing else (
                "EXECUTOR_NO_CHANGES" if no_changes_blocked else None
            ),
            "message": missing_msg if required_changed_files_missing else (
                no_changes_message if no_changes_blocked else ""
            ),
            "risk_level": "blocked" if had_error else "commit",
            "provider": provider_norm,
            "execution_mode": mode,
            "version": state.current_version,
            "runner_status": state.status,
            "run_status": run_status,
            "scope_status": scope_status,
            "audit_file": run_result.audit_file or "",
            "log_path": execution_result.get("log_path", ""),
            "summary_path": execution_result.get("summary_path", ""),
            "command_results": command_results,
            "failed_command_indexes": failed_indexes,
            "git_head_before": head_before,
            "git_head_after": head_after,
            "git_status_after": post_data.get("git_status_short", ""),
            "changed_files": changed_files,
            "diff_summary": post_data.get("diff_summary", ""),
            "report_summary": post_data.get("report_summary", {}),
            "latest_report_id": post_data.get("latest_report_id"),
            "classification": classification,
            "completion_evidence": completion_evidence,
            "next_actions": self._build_next_actions(classification, provider_norm, mode),
            "blockers": blockers,
            "warnings": post_data.get("warnings", []),
            "workflow_id": None,
            "reason": reason,
            "report": post_data.get("report") if include_report_markdown else None,
        }

    def _execute_provider(
        self,
        *,
        provider: str,
        plan: Any,
        state: Any,
        workspace: ProjectWorkspace,
        is_fix: bool,
        execution_mode: str,
        head_before: str | None,
        executor_session_mode: str = "auto",
        model_override: str | None = None,
        reasoning_effort_override: str | None = None,
        run_id: str = "",
        event_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        not_found_error: type[BaseException] | tuple[type[BaseException], ...] = tuple()
        unauthorized_error: type[BaseException] | tuple[type[BaseException], ...] = tuple()
        unsupported_error: type[BaseException] | tuple[type[BaseException], ...] = tuple()
        model_quota_error: type[BaseException] | tuple[type[BaseException], ...] = tuple()
        provider_terminal_error: type[BaseException] | tuple[type[BaseException], ...] = tuple()
        try:
            if provider == "codex":
                from adapters.codex_cli_adapter import (
                    CodexModelQuotaExhaustedError,
                    CodexNotFoundError,
                    CodexUnauthorizedError,
                )
                from runner.codex_executor import CodexExecutor

                executor = CodexExecutor(
                    workspace,
                    model_override=model_override,
                    reasoning_effort_override=reasoning_effort_override,
                )
                not_found_error = CodexNotFoundError
                unauthorized_error = CodexUnauthorizedError
                unsupported_error = tuple()
                model_quota_error = CodexModelQuotaExhaustedError
            elif provider == "opencode":
                from adapters.opencode_server_adapter import (
                    OpenCodeModelQuotaExhaustedError,
                    OpenCodeProviderTerminalError,
                    OpenCodeServerNotFoundError,
                    OpenCodeServerUnauthorizedError,
                )
                from runner.opencode_executor import OpenCodeExecutor

                executor = OpenCodeExecutor(workspace, model_override=model_override)
                not_found_error = OpenCodeServerNotFoundError
                unsupported_error = tuple()
                unauthorized_error = OpenCodeServerUnauthorizedError
                model_quota_error = OpenCodeModelQuotaExhaustedError
                provider_terminal_error = OpenCodeProviderTerminalError
            else:
                from adapters.pi_rpc_adapter import PiNotFoundError, PiUnauthorizedError
                from runner.pi_executor import PiExecutor

                executor = PiExecutor(workspace, model_override=model_override)
                not_found_error = PiNotFoundError
                unauthorized_error = PiUnauthorizedError
                unsupported_error = tuple()
                model_quota_error = tuple()

            self._maybe_write_event(run_id, "executor_started", {
                "provider": provider,
                "is_fix": is_fix,
            }, event_context=event_context)

            execution_result = (
                executor.run_current_fix(plan, state, executor_session_mode=executor_session_mode, run_id=run_id, event_context=event_context)
                if is_fix
                else executor.run_current_version(plan, state, executor_session_mode=executor_session_mode, run_id=run_id, event_context=event_context)
            )

            self._maybe_write_event(run_id, "executor_finished", {
                "provider": provider,
                "is_fix": is_fix,
            }, event_context=event_context)
        except FileNotFoundError:
            return self._executor_error(provider, "FIX_PROMPT_MISSING", "当前修复提示词不存在。", head_before, execution_mode)
        except not_found_error as exc:  # type: ignore[misc]
            return self._executor_error(
                provider,
                f"{provider.upper()}_NOT_FOUND",
                str(exc) or f"{get_executor_provider_display(provider)} 执行器未安装。",
                head_before,
                execution_mode,
            )
        except unauthorized_error as exc:  # type: ignore[misc]
            return self._executor_error(
                provider,
                f"{provider.upper()}_UNAUTHORIZED",
                str(exc) or f"{get_executor_provider_display(provider)} 鉴权失败。",
                head_before,
                execution_mode,
            )
        except unsupported_error as exc:  # type: ignore[misc]
            return self._executor_error(
                provider,
                f"{provider.upper()}_RUN_UNSUPPORTED",
                str(exc) or f"{get_executor_provider_display(provider)} 当前环境不支持 run。",
                head_before,
                execution_mode,
            )
        except model_quota_error as exc:  # type: ignore[misc]
            safe_message = self._model_quota_exhausted_message(get_executor_provider_display(provider))
            return {
                **self._executor_interruption_error(
                    provider=provider,
                    head_before=head_before,
                    execution_mode=execution_mode,
                    report={
                        "status": "failed",
                        "log_path": getattr(exc, "log_path", "") or "",
                        "summary_path": "",
                    },
                    interruption={
                        "classification": "executor_resource_exhausted",
                        "error_code": "EXECUTOR_MODEL_QUOTA_EXHAUSTED",
                        "interruption_kind": "executor_model_quota_exhausted",
                        "message": safe_message,
                        "provider_status": "failed",
                        "summary_excerpt": safe_message,
                    },
                ),
                "terminal_reason": "executor_model_quota_exhausted",
                "model": model_override or "",
                "model_source": "preview" if model_override else "",
            }
        except provider_terminal_error as exc:  # type: ignore[misc]
            provider_display = get_executor_provider_display(provider)
            error_code = str(getattr(exc, "error_code", "") or "EXECUTOR_PROVIDER_ERROR")
            terminal_reason = str(getattr(exc, "terminal_reason", "") or "executor_provider_error")
            provider_status = str(getattr(exc, "provider_status", "") or "")
            safe_message = str(exc) or f"{provider_display} provider/server 返回 terminal error。"
            if error_code == "EXECUTOR_STALLED":
                classification = "executor_infrastructure_failed"
                interruption_kind = "executor_stalled"
            elif error_code == "EXECUTOR_PROVIDER_RETRY":
                classification = "executor_infrastructure_failed"
                interruption_kind = "provider_retry"
            else:
                classification = "executor_infrastructure_failed"
                interruption_kind = "provider_error"
            return {
                **self._executor_interruption_error(
                    provider=provider,
                    head_before=head_before,
                    execution_mode=execution_mode,
                    report={
                        "status": "failed",
                        "log_path": getattr(exc, "log_path", "") or "",
                        "summary_path": "",
                    },
                    interruption={
                        "classification": classification,
                        "error_code": error_code,
                        "interruption_kind": interruption_kind,
                        "message": safe_message,
                        "provider_status": provider_status or "failed",
                        "summary_excerpt": safe_message[:240],
                        "terminal_reason": terminal_reason,
                    },
                ),
                "terminal_reason": terminal_reason,
                "provider_error_code": error_code,
            }
        except Exception as exc:
            provider_display = get_executor_provider_display(provider)
            return self._executor_error(
                provider,
                "EXECUTOR_FAILED",
                f"{provider_display} 执行失败：{exc}",
                head_before,
                execution_mode,
            )

        report = self._extract_report(execution_result)
        interruption = self._classify_provider_interruption(
            provider=provider,
            execution_result=execution_result,
            report=report,
        )
        if interruption is not None:
            ret = self._executor_interruption_error(
                provider=provider,
                head_before=head_before,
                execution_mode=execution_mode,
                report=report,
                interruption=interruption,
            )
            ret["_execution_result"] = execution_result
            ret["_report"] = report
            return ret
        return {
            "ok": True,
            "_execution_result": execution_result,
            "_report": report,
            "log_path": report.get("log_path", ""),
            "summary_path": report.get("summary_path", ""),
        }

    def _extract_report(self, execution_result: Any) -> dict[str, Any]:
        rs = getattr(execution_result, "result_summary", None)
        if rs is None:
            return {}
        return {
            "provider": getattr(rs, "provider", ""),
            "execution_mode": getattr(rs, "execution_mode", ""),
            "status": getattr(rs, "process_status", None) or getattr(rs, "status", ""),
            "log_path": getattr(rs, "log_path", ""),
            "summary_path": getattr(rs, "summary_path", ""),
            "summary": getattr(rs, "summary", ""),
            "attempted_resume": getattr(rs, "attempted_resume", False),
            "used_resume": getattr(rs, "used_resume", False),
            "fallback_to_new_session": getattr(rs, "fallback_to_new_session", False),
            "resume_failed_reason": getattr(rs, "resume_failed_reason", None),
            "command_shape": getattr(rs, "command_shape", None),
            "provider_status": getattr(rs, "provider_status", None),
            "provider_error_code": getattr(rs, "provider_error_code", None),
            "provider_error_summary": getattr(rs, "provider_error_summary", None),
        }

    def _collect_provider_interruption_text(self, execution_result: Any, report: dict[str, Any]) -> str:
        texts: list[str] = []

        def _append_text(value: Any) -> None:
            if isinstance(value, str) and value.strip():
                texts.append(value.strip())

        for key in ("summary", "status", "provider", "execution_mode", "resume_failed_reason", "command_shape", "provider_status", "provider_error_code", "provider_error_summary"):
            _append_text(report.get(key))

        result_summary = getattr(execution_result, "result_summary", None)
        if result_summary is not None:
            for key in ("summary", "status", "process_status", "resume_failed_reason", "command_shape", "provider_status", "provider_error_code", "provider_error_summary"):
                _append_text(getattr(result_summary, key, None))

        for attr_name in ("codex_run", "opencode_run", "pi_run"):
            run_obj = getattr(execution_result, attr_name, None)
            if run_obj is None:
                continue
            for key in ("summary", "final_message_preview", "stderr", "stdout"):
                _append_text(getattr(run_obj, key, None))
            stdout_lines = getattr(run_obj, "stdout_lines", None)
            if isinstance(stdout_lines, list):
                for line in stdout_lines[-20:]:
                    _append_text(line)
            exit_code = getattr(run_obj, "exit_code", None)
            if exit_code not in (None, ""):
                texts.append(f"exit_code={exit_code}")

        return redact_sensitive_text("\n".join(texts), replacement_token="<redacted>", preserve_token_prefix=True)[:8000]

    def _provider_completed_with_completion_evidence(self, report_status: str, combined_text_lower: str) -> bool:
        if report_status not in _COMPLETED_PROVIDER_STATUSES:
            return False
        return any(marker.lower() in combined_text_lower for marker in _PROVIDER_COMPLETION_TEXT_MARKERS)

    def _classify_provider_interruption(
        self,
        *,
        provider: str,
        execution_result: Any,
        report: dict[str, Any],
    ) -> dict[str, Any] | None:
        provider_display = get_executor_provider_display(provider)
        report_status = str(report.get("status") or "").strip().lower()
        combined_text = self._collect_provider_interruption_text(execution_result, report)
        combined_text_lower = combined_text.lower()
        summary_excerpt = combined_text[:240] if combined_text else ""

        if self._provider_completed_with_completion_evidence(report_status, combined_text_lower):
            return None

        if any(marker in combined_text_lower for marker in _RESOURCE_EXHAUSTION_MARKERS):
            is_model_quota = self._looks_model_quota_exhausted(combined_text_lower)
            message = (
                self._model_quota_exhausted_message(provider_display)
                if is_model_quota
                else f"{provider_display} 资源中断，已在 acceptance 前停止。"
            )
            if summary_excerpt and not is_model_quota:
                message = f"{message} 原因摘要：{summary_excerpt}"
            return {
                "classification": "executor_resource_exhausted",
                "error_code": "EXECUTOR_MODEL_QUOTA_EXHAUSTED" if is_model_quota else "EXECUTOR_RESOURCE_EXHAUSTED",
                "interruption_kind": "executor_model_quota_exhausted" if is_model_quota else "resource_exhausted",
                "message": message,
                "provider_status": report_status,
                "summary_excerpt": message if is_model_quota else summary_excerpt,
                "terminal_reason": "executor_model_quota_exhausted" if is_model_quota else "",
            }

        if any(marker in combined_text_lower for marker in _INFRA_INTERRUPTION_TEXT_MARKERS):
            message = f"{provider_display} 基础设施中断，已在 acceptance 前停止。"
            if summary_excerpt:
                message = f"{message} 原因摘要：{summary_excerpt}"
            return {
                "classification": "executor_infrastructure_failed",
                "error_code": "EXECUTOR_INFRASTRUCTURE_FAILED",
                "interruption_kind": "infrastructure_failed",
                "message": message,
                "provider_status": report_status,
                "summary_excerpt": summary_excerpt,
            }

        if report_status in _FAILED_PROVIDER_STATUSES:
            message = f"{provider_display} 基础设施中断，provider 返回状态 {report_status}，已在 acceptance 前停止。"
            if summary_excerpt:
                message = f"{message} 原因摘要：{summary_excerpt}"
            return {
                "classification": "executor_infrastructure_failed",
                "error_code": "EXECUTOR_INFRASTRUCTURE_FAILED",
                "interruption_kind": "infrastructure_failed",
                "message": message,
                "provider_status": report_status,
                "summary_excerpt": summary_excerpt,
            }

        return None

    def _executor_interruption_error(
        self,
        *,
        provider: str,
        head_before: str | None,
        execution_mode: str,
        report: dict[str, Any],
        interruption: dict[str, Any],
    ) -> dict[str, Any]:
        classification = str(interruption.get("classification") or "executor_infrastructure_failed")
        return {
            "ok": False,
            "action": "run_once",
            "status": "failed",
            "error_code": str(interruption.get("error_code") or "EXECUTOR_INFRASTRUCTURE_FAILED"),
            "message": str(interruption.get("message") or "执行器基础设施中断。"),
            "provider": provider,
            "execution_mode": execution_mode,
            "git_head_before": head_before,
            "git_head_after": head_before,
            "runner_status": None,
            "version": None,
            "blockers": [str(interruption.get("message") or "执行器基础设施中断。")],
            "warnings": [],
            "classification": classification,
            "interruption_kind": str(interruption.get("interruption_kind") or "infrastructure_failed"),
            "provider_status": str(interruption.get("provider_status") or ""),
            "provider_summary_excerpt": str(interruption.get("summary_excerpt") or ""),
            "terminal_reason": str(interruption.get("terminal_reason") or ""),
            "recovery_options": self._build_recovery_options(
                classification=classification,
                provider=provider,
                execution_mode=execution_mode,
                has_partial_worktree=False,
            ),
            "log_path": report.get("log_path", ""),
            "summary_path": report.get("summary_path", ""),
        }

    def _record_executor_interruption_report(
        self,
        *,
        state: Any,
        plan: Any,
        provider: str,
        execution_mode: str,
        commit_head_before: str | None,
        commit_head_after: str | None,
        raw_execution_result: Any | None,
        execution_result: dict[str, Any],
        continuation_decision_before: dict[str, Any] | None,
        resume_invocation_before: dict[str, Any] | None,
        execution_lineage_extra: dict[str, Any] | None,
        changed_files: list[str],
        preexisting_runner_files: set[str],
        include_report_markdown: bool,
        max_report_chars: int,
    ) -> dict[str, Any]:
        recovery_options = execution_result.get("recovery_options")
        recovery_option_names = [
            str(item.get("option")).strip()
            for item in recovery_options
            if isinstance(item, dict) and str(item.get("option") or "").strip()
        ] if isinstance(recovery_options, list) else []
        completion_evidence = {
            "mode": "executor_interrupted",
            "provider": provider,
            "version": str(state.current_version or ""),
            "classification": str(execution_result.get("classification") or ""),
            "error_code": str(execution_result.get("error_code") or ""),
            "interruption_kind": str(execution_result.get("interruption_kind") or ""),
            "provider_status": str(execution_result.get("provider_status") or ""),
            "terminal_reason": str(execution_result.get("terminal_reason") or ""),
            "recovery_options": recovery_option_names,
            "executor_changed_files": list(changed_files),
            "has_partial_worktree": bool(changed_files),
            "notes": [
                str(execution_result.get("message") or "执行器中断，业务验收尚未开始。"),
            ],
        }
        self._record_executor_run_report(
            state=state,
            plan=plan,
            provider=provider,
            execution_mode=execution_mode,
            status="failed",
            commit_head_before=commit_head_before,
            commit_head_after=commit_head_after,
            execution_result=raw_execution_result,
            run_result=None,
            continuation_decision_before=continuation_decision_before,
            resume_invocation_before=resume_invocation_before,
            execution_lineage_extra=execution_lineage_extra,
            completion_evidence=completion_evidence,
            preexisting_runner_files=preexisting_runner_files,
        )
        return self._get_latest_report_summary(
            self.project_root,
            include_report_markdown=include_report_markdown,
            max_report_chars=max_report_chars,
        )

    def _executor_error(
        self,
        provider: str,
        error_code: str,
        message: str,
        head_before: str | None,
        execution_mode: str,
    ) -> dict[str, Any]:
        return {
            "ok": False,
            "action": "run_once",
            "status": "failed",
            "error_code": error_code,
            "message": message,
            "provider": provider,
            "execution_mode": execution_mode,
            "git_head_before": head_before,
            "git_head_after": head_before,
            "runner_status": None,
            "version": None,
            "blockers": [message],
            "warnings": [],
        }

    def classify_result(
        self,
        run_status: str,
        scope_status: str = "",
        changed_files: list[str] | None = None,
        git_status_after: str = "",
        diff_summary: str = "",
        preflight_blocked: bool = False,
        executor_error_code: str = "",
    ) -> str:
        if preflight_blocked:
            return "blocked_preflight"

        scope_norm = str(scope_status or "").strip().upper()
        if scope_norm in _SCOPE_BLOCK_STATES:
            return "blocked_scope_violation"

        run_status_norm = str(run_status or "").strip().upper()
        if run_status_norm in {"FAILED", "FAILED_BLOCKED"}:
            return "failed_acceptance"

        if run_status_norm == "PASSED":
            has_changes = bool(changed_files) or bool((git_status_after or "").strip()) or bool((diff_summary or "").strip())
            return "passed_with_changes" if has_changes else "passed_clean"

        error_norm = str(executor_error_code or "").strip().upper()
        if error_norm == "EXECUTOR_RESOURCE_EXHAUSTED":
            return "executor_resource_exhausted"
        if error_norm == "EXECUTOR_MODEL_QUOTA_EXHAUSTED":
            return "executor_resource_exhausted"
        if error_norm == "EXECUTOR_INFRASTRUCTURE_FAILED":
            return "executor_infrastructure_failed"
        if error_norm in _EXECUTOR_ERROR_CODES or not run_status_norm:
            return "executor_failed"

        return "executor_failed"

    def collect_post_run_data(
        self,
        project_root: str,
        include_diff_summary: bool,
        include_report_markdown: bool,
        max_report_chars: int,
        preexisting_runner_files: set | None = None,
    ) -> dict[str, Any]:
        git_status_raw = self._get_git_status_short()
        diff_summary = self._get_diff_summary(project_root) if include_diff_summary else ""
        report_data = self._get_latest_report_summary(
            project_root,
            include_report_markdown=include_report_markdown,
            max_report_chars=max_report_chars,
        )
        report_summary = report_data.get("report_summary", {})
        report_changed_files = report_summary.get("changed_files", []) if isinstance(report_summary, dict) else []
        changed_files_raw = self._collect_changed_files_for_evidence(extra_changed_files=report_changed_files)
        if preexisting_runner_files:
            changed_files = [f for f in changed_files_raw if f not in preexisting_runner_files]
            git_status = "\n".join(
                line for line in (git_status_raw or "").splitlines()
                if line.strip() and self._status_line_path(line) not in preexisting_runner_files
            )
        else:
            changed_files = changed_files_raw
            git_status = git_status_raw
        return {
            "git_status_short": git_status,
            "git_status_short_all": git_status_raw,
            "changed_files": changed_files,
            "changed_files_all": changed_files_raw,
            "diff_summary": diff_summary,
            "report_summary": report_summary if isinstance(report_summary, dict) else {},
            "latest_report_id": report_data.get("latest_report_id"),
            "scope_status": report_data.get("scope_status", ""),
            "report": report_data.get("report") if include_report_markdown else None,
            "blockers": [],
            "warnings": [],
        }

    def _get_diff_summary(self, project_root: str) -> str:
        try:
            diff_result = self._source_review.get_filtered_diff(project_root, max_chars=60000)
            if isinstance(diff_result, dict):
                return str(diff_result.get("diff", ""))[:40000]
        except Exception:
            pass
        return ""

    def _get_latest_report_summary(
        self,
        project_root: str,
        *,
        include_report_markdown: bool,
        max_report_chars: int,
    ) -> dict[str, Any]:
        try:
            store = ExecutorRunReportStore(project_root)
            report = store.get_report(
                latest=True,
                include_markdown=include_report_markdown,
                max_markdown_chars=max_report_chars,
            )
            if isinstance(report, dict) and report.get("ok") and isinstance(report.get("report"), dict):
                r = report["report"]
                ret: dict[str, Any] = {
                    "latest_report_id": r.get("report_id"),
                    "scope_status": "",
                    "report_summary": {
                        "status": r.get("status"),
                        "provider": r.get("provider"),
                        "version": r.get("version"),
                        "execution_mode": r.get("execution_mode"),
                        "finished_at": r.get("finished_at"),
                        "changed_files": r.get("changed_files", []),
                        "commit_head_before": r.get("commit_head_before"),
                        "commit_head_after": r.get("commit_head_after"),
                        "execution_lineage": r.get("execution_lineage", {}),
                    },
                }
                if include_report_markdown:
                    ret["report"] = report.get("report_markdown", "")
                return ret
        except Exception:
            pass
        return {}

    def _compute_completion_evidence(
        self,
        project_root: str,
        plan: Any,
        state: Any,
        run_status: str,
        provider: str,
        changed_files: list[str],
        command_results: list[dict[str, Any]],
        allow_no_changes: bool = False,
    ) -> dict[str, Any]:
        version = str(state.current_version or "") if state else ""
        provider_val = str(provider or "").strip().lower()
        validation_commands = [str(cmd.get("original_command", cmd.get("command", ""))) for cmd in command_results]
        allowed_patterns = current_plan_allowed_patterns(project_root) if plan else []
        executor_changed_files: list[str] = []
        for f in changed_files:
            norm = f.replace("\\", "/")
            if self._is_runner_local_private_file(norm):
                continue
            if self._is_runner_runtime_file(norm):
                continue
            if self._is_runner_archive_file(norm):
                continue
            if allowed_patterns and glob_match_any(norm, allowed_patterns):
                if norm not in executor_changed_files:
                    executor_changed_files.append(norm)
        if run_status in ("PASSED",):
            if executor_changed_files:
                mode = "executor_changed"
            elif allow_no_changes:
                mode = "validation_only_no_diff_allowed"
            else:
                mode = "validation_only_no_diff"
        else:
            mode = "failed_or_unknown"
        notes: list[str] = []
        if mode == "validation_only_no_diff":
            notes.append("executor report PASSED but no allowed_files diff detected")
        if mode == "validation_only_no_diff_allowed":
            notes.append("executor report PASSED with allow_no_changes=true")
        allowed_files_present = bool(allowed_patterns)
        if not allowed_patterns:
            notes.append("allowed_files patterns unavailable or empty")
        if not version:
            notes.append("current_version unavailable")
        return {
            "mode": mode,
            "provider": provider_val,
            "version": version,
            "allowed_files_present": allowed_files_present,
            "allow_no_changes": allow_no_changes,
            "executor_changed_files": sorted(executor_changed_files),
            "validation_commands": validation_commands,
            "notes": notes,
        }

    def _build_acceptance_command_results(self, run_result: Any) -> tuple[list[int], list[dict[str, Any]]]:
        failed_indexes: list[int] = []
        command_results: list[dict[str, Any]] = []
        if not run_result or not run_result.acceptance_run:
            return failed_indexes, command_results
        for idx, item in enumerate(run_result.acceptance_run.commands, start=1):
            command_results.append({
                "index": idx,
                "status": item.status,
                "exit_code": item.exit_code,
                "original_command": getattr(item, "original_command", None) or getattr(item, "command", ""),
                "executed_command": getattr(item, "executed_command", None) or getattr(item, "command", ""),
                "cwd": getattr(item, "cwd", None),
            })
            if item.status != "PASSED":
                failed_indexes.append(idx)
        return failed_indexes, command_results

    def _record_executor_run_report(
        self,
        *,
        state: Any,
        plan: Any,
        provider: str,
        execution_mode: str,
        status: str,
        commit_head_before: str | None = None,
        commit_head_after: str | None = None,
        execution_result: Any | None = None,
        run_result: Any | None = None,
        continuation_decision_before: dict[str, Any] | None = None,
        resume_invocation_before: dict[str, Any] | None = None,
        execution_lineage_extra: dict[str, Any] | None = None,
        completion_evidence: dict[str, Any] | None = None,
        preexisting_runner_files: set | None = None,
    ) -> None:
        try:
            store = ExecutorRunReportStore(self.project_root)
            version = str(state.current_version or "")
            version_name = ""
            version_plan = None
            if version and plan:
                for v in plan.versions:
                    if str(v.version) == version:
                        version_name = str(v.name or "")
                        version_plan = v
                        break
            report_text = None
            log_path = None
            if execution_result is not None:
                rs = getattr(execution_result, "result_summary", None)
                if rs is not None:
                    report_text = getattr(rs, "full_report_text", None) or getattr(rs, "summary", None)
                    log_path = getattr(rs, "log_path", None)
                if not report_text:
                    for attr_name in ("codex_run", "opencode_run", "pi_run"):
                        cr = getattr(execution_result, attr_name, None)
                        if cr is not None:
                            report_text = (
                                getattr(cr, "full_report_text", None)
                                or getattr(cr, "summary", None)
                                or getattr(cr, "final_message_preview", None)
                            )
                            if not log_path:
                                log_path = getattr(cr, "log_path", None)
                            break
            report_text = report_text or "No executor final report was captured."
            changed_files = self._collect_executor_report_changed_files(run_result, preexisting_runner_files=preexisting_runner_files)
            audit_file = getattr(run_result, "audit_file", None) if run_result else None
            summary_changed = []
            summary_validation = []
            summary_validation_command_records: list[dict[str, Any]] = []
            summary_risks = []
            if run_result is not None:
                rc = getattr(run_result, "changed_files", None)
                if rc:
                    summary_changed = [
                        str(item).strip()
                        for item in rc
                        if str(item).strip()
                    ]
                acceptance = getattr(run_result, "acceptance_run", None)
                if acceptance is not None and hasattr(acceptance, "commands"):
                    for idx, cmd in enumerate(acceptance.commands, start=1):
                        cmd_status = getattr(cmd, "status", "UNKNOWN")
                        cmd_text = getattr(cmd, "command", "") or getattr(cmd, "executed_command", "") or ""
                        summary_validation.append(f"{cmd_status}: {cmd_text}")
                        summary_validation_command_records.append({
                            "command_index": idx,
                            "command": getattr(cmd, "command", "") or "",
                            "original_command": getattr(cmd, "original_command", None) or getattr(cmd, "command", "") or "",
                            "executed_command": getattr(cmd, "executed_command", None) or "",
                            "status": cmd_status,
                            "exit_code": getattr(cmd, "exit_code", None),
                            "stdout": getattr(cmd, "stdout", "") or "",
                            "stderr": getattr(cmd, "stderr", "") or "",
                        })
                scope = getattr(run_result, "scope_check", None)
                if scope is not None:
                    scope_status = getattr(scope, "status", "NOT_CHECKED")
                    summary_validation.append(f"Scope check: {scope_status}")
            if not summary_changed and changed_files:
                summary_changed = list(changed_files)
            token_usage: dict[str, Any] | None = None
            if execution_result is not None:
                for attr_name in ("codex_run", "opencode_run", "pi_run"):
                    cr = getattr(execution_result, attr_name, None)
                    if cr is not None:
                        tu = getattr(cr, "token_usage", None)
                        if isinstance(tu, dict):
                            token_usage = tu
                        break
            execution_lineage = self._build_execution_lineage(
                provider=provider,
                execution_result=execution_result,
                continuation_decision_before=continuation_decision_before,
                resume_invocation_before=resume_invocation_before,
                execution_lineage_extra={
                    **self._build_prompt_lineage_extra(
                        execution_result=execution_result,
                        plan=plan,
                        execution_mode=execution_mode,
                    ),
                    **(execution_lineage_extra or {}),
                },
            )
            ce = dict(completion_evidence) if isinstance(completion_evidence, dict) else None
            attempt_binding = resolve_execution_attempt_binding(plan, version_plan or version)
            store.record_report(
                version=version,
                version_name=version_name,
                provider=provider,
                execution_mode=execution_mode,
                status=status,
                commit_head_before=commit_head_before,
                commit_head_after=commit_head_after,
                changed_files=changed_files,
                log_file=log_path,
                audit_file=audit_file,
                summary_changed_files=summary_changed,
                summary_validation_results=summary_validation,
                summary_validation_command_records=summary_validation_command_records,
                summary_risk_followups=summary_risks,
                executor_report_text=report_text,
                execution_lineage=execution_lineage,
                completion_evidence=ce,
                token_usage=token_usage,
                **attempt_binding,
            )
        except Exception:
            import logging

            logging.getLogger(__name__).warning("Failed to record executor run report", exc_info=True)

    def _collect_changed_files_for_evidence(
        self,
        run_result: Any | None = None,
        *,
        extra_changed_files: list[str] | None = None,
        preexisting_runner_files: set | None = None,
    ) -> list[str]:
        files: list[str] = []
        files.extend(self._get_git_diff_names())
        git_status_short = self._get_git_status_short()
        status_files = self._get_git_changed_files_from_status(git_status_short)
        files.extend(self._expand_status_changed_paths(status_files))
        if run_result is not None:
            rc = getattr(run_result, "changed_files", None)
            if rc:
                files.extend(str(item) for item in rc if str(item).strip())
        if isinstance(extra_changed_files, list):
            files.extend(str(item) for item in extra_changed_files if str(item).strip())
        result = sorted(set(str(item).strip() for item in files if str(item).strip()))
        if preexisting_runner_files:
            result = [f for f in result if f not in preexisting_runner_files]
        return [f for f in result if self._is_reportable_changed_file(f)]

    def _is_reportable_changed_file(self, path: str) -> bool:
        if not is_project_runner_path(path):
            return True
        classification = classify_runner_path(path)
        return classification.get("track_policy") == "track"

    def _collect_executor_report_changed_files(self, run_result: Any | None, preexisting_runner_files: set | None = None) -> list[str]:
        return self._collect_changed_files_for_evidence(
            run_result,
            preexisting_runner_files=preexisting_runner_files,
        )

    def _build_execution_lineage(
        self,
        *,
        provider: str,
        execution_result: Any | None,
        continuation_decision_before: dict[str, Any] | None,
        resume_invocation_before: dict[str, Any] | None,
        execution_lineage_extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        rs = getattr(execution_result, "result_summary", None) if execution_result is not None else None
        attempted_resume = bool(getattr(rs, "attempted_resume", False))
        used_resume = bool(getattr(rs, "used_resume", False))
        fallback_to_new_session = bool(getattr(rs, "fallback_to_new_session", False))
        resume_failed_reason = self._sanitize_text(getattr(rs, "resume_failed_reason", None), max_chars=600)
        command_shape = self._sanitize_text(getattr(rs, "command_shape", None), max_chars=120)

        decision = continuation_decision_before or self._safe_get_continuation_decision(provider)
        invocation = resume_invocation_before or self._safe_get_resume_invocation_preview(provider)
        if not isinstance(decision, dict):
            decision = {}
        if not isinstance(invocation, dict):
            invocation = {}

        lineage = {
            "attempted_resume": attempted_resume,
            "actual_executor_resume_attempted": attempted_resume,
            "used_resume": used_resume,
            "fallback_to_new_session": fallback_to_new_session,
            "resume_failed_reason": resume_failed_reason or "",
            "command_shape": command_shape or "",
            "continuation_decision": str(decision.get("decision", "") or ""),
            "continuation_decision_reason": str(decision.get("decision_reason", "") or ""),
            "continuation_available_before_run": bool(decision.get("continuation_available") is True),
            "identity_kind": str(decision.get("identity_kind", "") or ""),
            "identity_present": bool(decision.get("identity_present") is True),
            "resume_identity_present": bool(
                decision.get("resume_identity_present", decision.get("identity_present")) is True
            ),
            "conversation_identity_present": bool(decision.get("conversation_identity_present") is True),
            "provider_matches": bool(decision.get("provider_matches") is True),
            "provider_resume_supported": bool(decision.get("provider_resume_supported") is True),
            "session_resume_available": bool(decision.get("session_resume_available") is True),
            "resume_invocation_verified": bool(invocation.get("resume_invocation_verified") is True),
            "risk_warnings": [str(item) for item in (decision.get("risk_warnings") or []) if str(item)],
            "resume_warnings": [str(item) for item in (decision.get("resume_warnings") or decision.get("risk_warnings") or []) if str(item)],
            "hard_blockers": [str(item) for item in (decision.get("hard_blockers") or []) if str(item)],
            "resume_blockers": [str(item) for item in (decision.get("resume_blockers") or decision.get("hard_blockers") or []) if str(item)],
        }
        if isinstance(execution_lineage_extra, dict):
            for key, value in execution_lineage_extra.items():
                if key in {
                    "run_id",
                    "preview_id",
                    "preview_claimed_at",
                    "preview_claim_status",
                    "model",
                    "model_source",
                    "reasoning_effort",
                    "reasoning_effort_source",
                    "prompt_file",
                    "prompt_sha256",
                    "prompt_sha256_status",
                } and isinstance(value, str):
                    trimmed = value.strip()
                    if trimmed:
                        lineage[key] = trimmed[:200]
        return lineage

    def _build_preview_lineage_extra(
        self,
        *,
        run_id: str,
        preview_id: str,
        preview_claimed_at: str,
        preview_claim_status: str,
        model: str | None = None,
        model_source: str | None = None,
        reasoning_effort: str | None = None,
        reasoning_effort_source: str | None = None,
    ) -> dict[str, Any]:
        extra: dict[str, Any] = {}
        if isinstance(run_id, str) and run_id.strip():
            extra["run_id"] = run_id.strip()
        if isinstance(preview_id, str) and preview_id.strip():
            extra["preview_id"] = preview_id.strip()
        if isinstance(preview_claimed_at, str) and preview_claimed_at.strip():
            extra["preview_claimed_at"] = preview_claimed_at.strip()
        if isinstance(preview_claim_status, str) and preview_claim_status.strip():
            extra["preview_claim_status"] = preview_claim_status.strip()
        if isinstance(model, str) and model.strip():
            extra["model"] = model.strip()
        if isinstance(model_source, str) and model_source.strip():
            extra["model_source"] = model_source.strip()
        if isinstance(reasoning_effort, str) and reasoning_effort.strip():
            extra["reasoning_effort"] = reasoning_effort.strip()
        if isinstance(reasoning_effort_source, str) and reasoning_effort_source.strip():
            extra["reasoning_effort_source"] = reasoning_effort_source.strip()
        return extra

    def _build_prompt_lineage_extra(
        self,
        *,
        execution_result: Any | None,
        plan: Any | None,
        execution_mode: str,
    ) -> dict[str, Any]:
        prompt_path = self._detect_prompt_file_path(execution_result=execution_result, plan=plan, execution_mode=execution_mode)
        if not prompt_path:
            return {"prompt_sha256_status": "unavailable"}

        rel_path = self._to_project_relative_path(prompt_path)
        if not rel_path:
            return {"prompt_sha256_status": "unavailable"}

        extra: dict[str, Any] = {"prompt_file": rel_path}
        if not os.path.isfile(prompt_path):
            extra["prompt_sha256_status"] = "missing"
            return extra
        try:
            with open(prompt_path, "rb") as handle:
                data = handle.read()
            extra["prompt_sha256"] = hashlib.sha256(data).hexdigest()
            extra["prompt_sha256_status"] = "ok"
            return extra
        except Exception:
            extra["prompt_sha256_status"] = "unavailable"
            return extra

    def _detect_prompt_file_path(self, *, execution_result: Any | None, plan: Any | None, execution_mode: str) -> str:
        candidate: str = ""
        if execution_result is not None:
            raw = getattr(execution_result, "prompt_file", None)
            if isinstance(raw, str) and raw.strip():
                candidate = raw.strip()
        if not candidate and plan is not None:
            runtime_dir = getattr(plan, "runtime_dir", None)
            if isinstance(runtime_dir, str) and runtime_dir.strip():
                filename = "current-fix-prompt.md" if execution_mode == "fix" else "current-prompt.md"
                candidate = os.path.join(runtime_dir, filename)
        if not candidate:
            return ""
        try:
            return os.path.realpath(candidate)
        except Exception:
            return ""

    def _to_project_relative_path(self, abs_path: str) -> str:
        if not abs_path:
            return ""
        try:
            root = os.path.realpath(self.project_root)
            target = os.path.realpath(abs_path)
            if target == root or target.startswith(root + os.sep):
                return os.path.relpath(target, root).replace("\\", "/")
            return ""
        except Exception:
            return ""

    def _safe_get_continuation_decision(self, provider: str) -> dict[str, Any]:
        try:
            return ExecutorSessionStore(self.project_root, target=self._target).get_continuation_decision(requested_provider=provider)
        except Exception as exc:
            return {
                "ok": False,
                "decision": "unavailable",
                "decision_reason": "continuation_decision_error",
                "continuation_available": False,
                "identity_kind": "",
                "identity_present": False,
                "resume_identity_present": False,
                "conversation_identity_present": False,
                "provider_matches": False,
                "provider_resume_supported": False,
                "session_resume_available": False,
                "risk_warnings": [],
                "resume_warnings": [],
                "hard_blockers": [f"continuation_decision_error:{exc.__class__.__name__}"],
                "resume_blockers": [f"continuation_decision_error:{exc.__class__.__name__}"],
                "decision_owner": "gpts",
                "optimization_goal": "maximize_cache_hit",
                "recommended_default": "start_new",
                "cache_hit_preference": "start_new_avoids_cache_stale",
                "context_facts": {},
            }

    def _safe_get_resume_invocation_preview(self, provider: str) -> dict[str, Any]:
        try:
            return ExecutorSessionStore(self.project_root, target=self._target).get_resume_invocation_preview(requested_provider=provider)
        except Exception as exc:
            return {
                "ok": False,
                "resume_invocation_supported": False,
                "resume_invocation_verified": False,
                "hard_blockers": [f"resume_invocation_preview_error:{exc.__class__.__name__}"],
            }

    def _sanitize_text(self, value: Any, max_chars: int) -> str:
        if not isinstance(value, str):
            return ""
        cleaned = redact_sensitive_text(value.strip(), replacement_token="<redacted>", preserve_token_prefix=True)
        if len(cleaned) > max_chars:
            cleaned = cleaned[:max_chars]
        return cleaned

    def _looks_model_quota_exhausted(self, lowered_text: str) -> bool:
        markers = (
            "model quota",
            "token quota",
            "quota exceeded",
            "insufficient quota",
            "insufficient credits",
            "insufficient credit",
            "out of credits",
            "usage limit",
            "rate limit",
            "too many requests",
            "resource exhausted",
            "resources exhausted",
            "429",
        )
        return any(marker in lowered_text for marker in markers)

    def _model_quota_exhausted_message(self, provider_display: str) -> str:
        return (
            f"{provider_display} 模型额度或 token 配额已耗尽，Runner 已将本次执行标记为终止失败。"
            "请更换模型、等待额度恢复，或检查执行器账号和配置。"
        )

    def _expand_status_changed_paths(self, status_paths: list[str]) -> list[str]:
        expanded: list[str] = []
        for raw in status_paths:
            path = str(raw or "").strip().replace("\\", "/")
            if not path:
                continue
            abs_path = os.path.join(self.project_root, path.rstrip("/"))
            if os.path.isdir(abs_path):
                for current_dir, _, file_names in os.walk(abs_path):
                    for file_name in sorted(file_names):
                        full_path = os.path.join(current_dir, file_name)
                        rel_path = os.path.relpath(full_path, self.project_root).replace("\\", "/")
                        if rel_path not in expanded:
                            expanded.append(rel_path)
                continue
            if path not in expanded:
                expanded.append(path)
        return expanded

    def _load_plan(self, plan_file: str) -> dict[str, Any] | None:
        try:
            import json

            with open(plan_file, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    def _load_state(self, state_file: str) -> dict[str, Any] | None:
        try:
            import json

            with open(state_file, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    def _load_settings_provider(self, project_root: str) -> str:
        target = self._target
        plan_file = target.plan_file if target is not None else resolve_project_runner_plan_path(project_root)
        settings = RunnerSettingsStore().load_for_project(project_root, plan_file)
        return normalize_execution_provider(settings.execution_provider, default=DEFAULT_EXECUTION_PROVIDER)

    def _resolve_provider_from_dict(
        self,
        *,
        plan_data: dict[str, Any],
        version_spec: dict[str, Any],
        fallback_provider: str,
    ) -> str:
        try:
            from schemas.plan import BuildRunnerPlan

            plan_obj = BuildRunnerPlan.from_dict(plan_data)
            version_obj = None
            version_id = version_spec.get("version")
            for v in plan_obj.versions:
                if str(v.version) == str(version_id):
                    version_obj = v
                    break
            return resolve_version_execution_provider(
                plan=plan_obj,
                version=version_obj,
                fallback_provider=fallback_provider,
            )
        except Exception:
            version_exec = version_spec.get("execution")
            if isinstance(version_exec, dict):
                candidate = version_exec.get("provider")
                if is_supported_execution_provider(candidate):
                    return str(candidate).strip().lower()
            model_exec = plan_data.get("model_execution")
            if isinstance(model_exec, dict):
                candidate = model_exec.get("provider") or model_exec.get("execution_provider")
                if is_supported_execution_provider(candidate):
                    return str(candidate).strip().lower()
            return normalize_execution_provider(fallback_provider, default=DEFAULT_EXECUTION_PROVIDER)

    def _normalize_provider(self, provider: Any) -> str:
        if not isinstance(provider, str):
            return ""
        return provider.strip().lower()

    def _normalize_execution_mode(self, execution_mode: Any) -> str | None:
        if not isinstance(execution_mode, str):
            return None
        mode = execution_mode.strip().lower()
        if mode not in _EXECUTION_MODES:
            return None
        return mode

    def _safe_int(self, value: Any, default: int = -1) -> int:
        try:
            return int(value)
        except Exception:
            return default

    def _collect_git_context(self) -> dict[str, Any]:
        head_ok, head_out, head_err = self._run_git_cmd(["rev-parse", "--verify", "HEAD"])
        branch_ok, branch_out, branch_err = self._run_git_cmd(["rev-parse", "--abbrev-ref", "HEAD"])
        status_ok, status_out, status_err = self._run_git_cmd(["status", "--short", "--untracked-files=all"])
        git_status_short = "\n".join(line for line in (status_out or "").splitlines() if line.strip()) if status_ok else ""
        head_value = head_out.strip() if head_ok else ""
        head_valid = head_ok and self._looks_like_git_object_id(head_value)
        no_git_head = self._is_no_git_head(
            head_ok=head_ok,
            head_err=head_err,
            status_ok=status_ok,
            status_err=status_err,
        )
        if head_ok and not head_valid:
            head_error = "git rev-parse --verify HEAD returned an invalid object id."
        else:
            head_error = None if head_valid or no_git_head else head_err
        return {
            "current_head": head_value if head_valid else None,
            "current_branch": branch_out.strip() if branch_ok else None,
            "git_status_short": git_status_short,
            "git_dirty": bool(git_status_short),
            "head_error": head_error,
            "branch_error": None if branch_ok else branch_err,
            "git_status_error": None if status_ok else status_err,
            "no_git_head": no_git_head,
        }

    def _is_no_git_head(self, *, head_ok: bool, head_err: str, status_ok: bool, status_err: str) -> bool:
        if head_ok or not status_ok:
            return False
        if self._is_no_git_head_error(head_err):
            return True
        return not self._is_git_unavailable_or_not_repo_error(head_err or status_err)

    def _is_no_git_head_error(self, error: str) -> bool:
        normalized = (error or "").lower()
        return (
            "ambiguous argument 'head'" in normalized
            or "fatal: ambiguous argument" in normalized
            or "unknown revision or path not in the working tree" in normalized
            or "needed a single revision" in normalized
            or "bad revision" in normalized
        )

    def _is_git_unavailable_or_not_repo_error(self, error: str) -> bool:
        normalized = (error or "").lower()
        return (
            "not a git repository" in normalized
            or "no such file or directory" in normalized
            or "timed out" in normalized
            or "permission denied" in normalized
        )

    def _looks_like_git_object_id(self, value: str) -> bool:
        candidate = (value or "").strip()
        if len(candidate) not in (40, 64):
            return False
        return all(char in "0123456789abcdefABCDEF" for char in candidate)

    def _build_dirty_git_block(self, git_status_short: str) -> dict[str, Any]:
        dirty_context = self._classify_git_changed_files(git_status_short)
        memory_files = dirty_context["runner_memory_files"]
        blocking_files = dirty_context["blocking_files"]
        preexisting_files = dirty_context["preexisting_runner_files"]

        if memory_files:
            message = "Git 工作区不干净。Runner 共享项目记忆文件存在未提交改动；请先提交这些文件并处理其他改动，建立 Git baseline，再运行执行器。"
            return {
                "code": "DIRTY_GIT_STATUS",
                "message": message,
                "hints": [
                    "请先提交 Runner 共享项目记忆文件和需要纳入 baseline 的项目文件，再运行执行器。",
                    "Runner 本机状态文件和运行态文件不属于 baseline 提交建议。",
                ],
                "runner_memory_files": memory_files,
                "blocking_files": blocking_files,
                "preexisting_runner_files": preexisting_files,
                "ignored_runner_local_files": dirty_context["ignored_runner_local_files"],
                "ignored_runner_runtime_files": dirty_context["ignored_runner_runtime_files"],
                "ignored_runner_archive_files": dirty_context["ignored_runner_archive_files"],
            }
        return {
            "code": "DIRTY_GIT_STATUS",
            "message": "Git 工作区不干净，请先提交或清理。",
            "blocking_files": blocking_files,
            "preexisting_runner_files": preexisting_files,
            "ignored_runner_local_files": dirty_context["ignored_runner_local_files"],
            "ignored_runner_runtime_files": dirty_context["ignored_runner_runtime_files"],
            "ignored_runner_archive_files": dirty_context["ignored_runner_archive_files"],
        }

    def _classify_git_changed_files(self, git_status_short: str) -> dict[str, Any]:
        status_lines = [line for line in (git_status_short or "").splitlines() if line.strip()]
        changed_files = self._get_git_changed_files_from_status(git_status_short)
        runner_memory_files = [path for path in changed_files if self._is_runner_project_tracked_file(path)]
        ignored_runner_local_files = [path for path in changed_files if self._is_runner_local_private_file(path)]
        ignored_runner_runtime_files = [path for path in changed_files if self._is_runner_runtime_file(path)]
        ignored_runner_archive_files = [path for path in changed_files if self._is_runner_archive_file(path)]
        preexisting_runner_files = [path for path in changed_files if is_project_runner_path(path)]
        ignored_files = set(ignored_runner_local_files + ignored_runner_runtime_files + ignored_runner_archive_files)
        blocking_files = sorted(
            path for path in changed_files
            if path not in ignored_files and path not in preexisting_runner_files
        )
        blocking_status_short = "\n".join(
            line for line in status_lines
            if self._status_line_path(line) in blocking_files
        )
        return {
            "changed_files": changed_files,
            "blocking_files": blocking_files,
            "blocking_status_short": blocking_status_short,
            "runner_memory_files": runner_memory_files,
            "preexisting_runner_files": preexisting_runner_files,
            "ignored_runner_local_files": ignored_runner_local_files,
            "ignored_runner_runtime_files": ignored_runner_runtime_files,
            "ignored_runner_archive_files": ignored_runner_archive_files,
        }

    def _get_blocking_git_changed_files(self, git_status_short: str) -> list[str]:
        return list(self._classify_git_changed_files(git_status_short)["blocking_files"])

    def _is_runner_project_tracked_file(self, path: str) -> bool:
        return classify_runner_path(path).get("category") == "project_tracked"

    def _is_runner_local_private_file(self, path: str) -> bool:
        return classify_runner_path(path).get("category") == "project_local"

    def _is_runner_runtime_file(self, path: str) -> bool:
        return classify_runner_path(path).get("category") == "runtime_ephemeral"

    def _is_runner_archive_file(self, path: str) -> bool:
        return classify_runner_path(path).get("category") == "archive_private_or_exportable"

    def _status_line_path(self, line: str) -> str:
        if len(line) <= 3:
            return ""
        return line[3:].strip()

    def _run_git_cmd(self, args: list[str]) -> tuple[bool, str, str]:
        rc, stdout, stderr = _run_git_base(args, self.project_root, timeout=10)
        if rc == 0:
            return True, stdout or "", ""
        return False, "", (stderr or stdout or "git command failed").strip()

    def _get_git_head(self) -> str | None:
        ok, out, _ = self._run_git_cmd(["rev-parse", "HEAD"])
        return out.strip() if ok else None

    def _get_git_branch(self) -> str | None:
        ok, out, _ = self._run_git_cmd(["rev-parse", "--abbrev-ref", "HEAD"])
        return out.strip() if ok else None

    def _get_git_status_short(self) -> str:
        ok, out, _ = self._run_git_cmd(["status", "--short", "--untracked-files=all"])
        return "\n".join(line for line in (out or "").splitlines() if line.strip()) if ok else ""

    def _get_git_diff_names(self) -> list[str]:
        return collect_git_diff_name_paths(self.project_root, timeout_seconds=10)

    def _get_changed_files_from_git(self) -> list[str]:
        return self._collect_changed_files_for_evidence()

    def _provider_unavailable(self, inventory: Any, provider: str) -> bool:
        if not isinstance(inventory, dict) or not inventory.get("ok"):
            return False
        provider_name = str(provider or "").strip().lower()
        providers = inventory.get("providers")
        if isinstance(providers, list):
            for item in providers:
                if isinstance(item, dict) and str(item.get("provider") or "").strip().lower() == provider_name:
                    return not bool(item.get("available", False))
        current_provider = str(inventory.get("current_provider") or "").strip().lower()
        current_available = inventory.get("current_provider_available")
        if current_provider == provider_name and isinstance(current_available, bool):
            return not current_available
        return False

    def _get_git_changed_files_from_status(self, git_status_short: str) -> list[str]:
        files: list[str] = []
        for line in (git_status_short or "").splitlines():
            if not line.strip():
                continue
            if len(line) > 3:
                files.append(line[3:].strip())
        return sorted(set(f for f in files if f))

    def _build_recovery_options(
        self,
        *,
        classification: str,
        provider: str,
        execution_mode: str,
        has_partial_worktree: bool,
    ) -> list[dict[str, Any]]:
        if classification == "executor_resource_exhausted":
            options = [
                {
                    "option": "wait_and_retry_current_provider",
                    "provider": provider,
                    "execution_mode": execution_mode,
                    "recommended": True,
                    "reason": "等待额度或限流恢复后重试当前执行器。",
                },
                {
                    "option": "switch_model",
                    "provider": provider,
                    "execution_mode": execution_mode,
                    "recommended": False,
                    "reason": "切换到同 provider 的其他模型，避开当前限额。",
                },
                {
                    "option": "switch_provider",
                    "provider": provider,
                    "execution_mode": execution_mode,
                    "recommended": False,
                    "reason": "切换到其他执行器 provider 继续当前版本。",
                },
                {
                    "option": "resume_existing",
                    "provider": provider,
                    "execution_mode": execution_mode,
                    "recommended": False,
                    "reason": "沿用当前执行器会话继续尝试。",
                },
                {
                    "option": "start_new",
                    "provider": provider,
                    "execution_mode": execution_mode,
                    "recommended": False,
                    "reason": "创建新执行器会话重新发起当前版本。",
                },
            ]
        else:
            options = [
                {
                    "option": "retry_current_provider",
                    "provider": provider,
                    "execution_mode": execution_mode,
                    "recommended": True,
                    "reason": "修复网络、证书或基础设施问题后重试当前执行器。",
                },
                {
                    "option": "switch_model",
                    "provider": provider,
                    "execution_mode": execution_mode,
                    "recommended": False,
                    "reason": "切换到当前 provider 的其他模型后继续。",
                },
                {
                    "option": "switch_provider",
                    "provider": provider,
                    "execution_mode": execution_mode,
                    "recommended": False,
                    "reason": "切换到其他执行器 provider 继续当前版本。",
                },
                {
                    "option": "resume_existing",
                    "provider": provider,
                    "execution_mode": execution_mode,
                    "recommended": False,
                    "reason": "沿用当前执行器会话继续尝试。",
                },
                {
                    "option": "start_new",
                    "provider": provider,
                    "execution_mode": execution_mode,
                    "recommended": False,
                    "reason": "创建新执行器会话重新发起当前版本。",
                },
            ]
        if has_partial_worktree:
            options.append(
                {
                    "option": "continue_from_partial_worktree",
                    "provider": provider,
                    "execution_mode": execution_mode,
                    "recommended": True,
                    "reason": "保留当前工作区半成品，修复执行器问题后继续完成剩余任务。",
                }
            )
        return options

    def _build_next_actions(
        self,
        classification: str,
        provider: str,
        execution_mode: str,
        *,
        has_partial_worktree: bool = False,
    ) -> list[dict[str, Any]]:
        if classification == "passed_with_changes":
            return [
                {
                    "tool": "manage_git_commit",
                    "action": "readiness",
                    "params": {"action": "readiness", "include_diff_summary": True},
                    "reason": "审查当前改动并准备提交。",
                    "requires_confirmation": False,
                },
                {
                    "tool": "run_mcp_workflow",
                    "action": "git_commit.preview",
                    "params": {"workflow": "git_commit", "phase": "preview"},
                    "reason": "生成受控提交预览。",
                    "requires_confirmation": True,
                },
            ]
        if classification == "passed_clean":
            return [
                {
                    "tool": "run_mcp_workflow",
                    "action": "project_status.inspect",
                    "params": {"workflow": "project_status", "phase": "inspect"},
                    "reason": "读取当前状态并决定是否推进下一版本。",
                    "requires_confirmation": False,
                }
            ]
        if classification in ("failed_acceptance", "executor_no_changes", "required_changed_files_missing"):
            return [
                {
                    "tool": "get_executor_run_report",
                    "action": "latest",
                    "params": {"latest": True, "include_markdown": True},
                    "reason": "读取执行报告并人工准备修复提示词。",
                    "requires_confirmation": False,
                }
            ]
        if classification == "blocked_scope_violation":
            return [
                {
                    "tool": "get_review_context",
                    "action": "inspect_scope",
                    "params": {"include_log": True, "include_repo_overview": False},
                    "reason": "复核 scope violation 后再继续。",
                    "requires_confirmation": False,
                }
            ]
        if classification == "blocked_preflight":
            return [
                {
                    "tool": "manage_executor_workflow",
                    "action": "preflight",
                    "params": {"action": "preflight", "provider": provider, "execution_mode": execution_mode},
                    "reason": "修复阻断项后重新执行 preflight。",
                    "requires_confirmation": False,
                }
            ]
        if classification in ("executor_resource_exhausted", "executor_infrastructure_failed"):
            actions = [
                {
                    "tool": "manage_executor_workflow",
                    "action": "preflight",
                    "params": {"action": "preflight", "provider": provider, "execution_mode": execution_mode},
                    "reason": "先确认执行器环境、凭证、网络或额度状态，再决定下一步恢复路径。",
                    "requires_confirmation": False,
                },
                {
                    "tool": "manage_executor_workflow",
                    "action": "run_once_preview",
                    "params": {"action": "run_once_preview", "provider": provider, "execution_mode": execution_mode},
                    "reason": "生成新的执行预览，再选择重试、切换模型或切换 provider。",
                    "requires_confirmation": False,
                },
            ]
            if has_partial_worktree:
                actions.append(
                    {
                        "tool": "get_review_context",
                        "action": "inspect_partial_worktree",
                        "params": {"include_log": True, "include_repo_overview": False},
                        "reason": "检查当前工作区半成品，决定继续跑还是先整理恢复方案。",
                        "requires_confirmation": False,
                    }
                )
            return actions
        return [
            {
                "tool": "manage_executor_workflow",
                "action": "preflight",
                "params": {"action": "preflight", "provider": provider, "execution_mode": execution_mode},
                "reason": "修复执行器配置后重新预检。",
                "requires_confirmation": False,
            }
        ]
