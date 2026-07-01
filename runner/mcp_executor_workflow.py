import json
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from runner._internal_utils import now_iso as _shared_now_iso
from runner.executor_confirmation import (
    manual_fix_prompt_preview_artifact,
    recheck_report_preview_artifact,
    run_bounded_preview_artifact,
    run_once_preview_artifact,
    scope_mismatch_preview_artifact,
)
from runner.executor_confirmation_store import ExecutorConfirmationStore
from runner.executor_result_builder import (
    already_claimed_error,
    preflight_result,
    run_once_started_result,
)
from runner.executor_run_claims import ExecutorRunClaimStore, parse_iso_datetime
from runner.executor_run_reports import ExecutorRunReportStore
from runner.executor_run_workflow import ExecutorRunOnceService
from runner.executor_session import ExecutorSessionStore
from runner.executor_status import apply_claim_to_status, read_executor_events_for_status, status_base_result
from runner.executor_registry import is_supported_execution_provider
from runner.final_version_closeout import (
    ARTIFACT_KIND as FINAL_VERSION_CLOSEOUT_ARTIFACT_KIND,
    apply_final_version_closeout_artifact,
    build_final_version_closeout_preview,
)
from runner.param_utils import bounded_int
from runner.path_glob import match as glob_match, match_any as glob_match_any, normalize as glob_normalize
from runner.plan_allowed_files import current_plan_allowed_patterns
from runner.plan_loader import PlanLoader
from runner.planning_bridge import PlanningBridge, PlanningBridgeError
from runner.runner_settings import RunnerSettingsStore, _sanitize_optional_str
from runner.runner_paths import (
    is_project_runner_path,
    resolve_project_runner_path,
    resolve_project_runner_rel_dir,
)
from runner.state_machine import RunnerStateMachine
from runner.state_lineage_reconciliation import (
    ARTIFACT_KIND as STATE_LINEAGE_ARTIFACT_KIND,
    apply_state_lineage_reconciliation_artifact,
    build_state_lineage_reconciliation_preview,
)
from runner.state_mutation import (
    ManualValidationPassMutation,
    RecheckReportStateRefreshMutation,
    RunnerStateMutationService,
    ScopeMismatchResolutionMutation,
)
from runner.state_mutation_gateway import StateMutationGateway
from runner.state_store import StateStore
from runner.executor_validation_truth import (
    bounded_validation_command_records,
    summarize_legacy_validation_results,
    validation_truth_from_summary,
)


PREVIEWS_DIR = os.path.join("runtime", "executor-workflow-previews")
PREVIEW_TTL_SECONDS = 3600
CLAIMS_DIR = "claims"
CLAIM_HEARTBEAT_INTERVAL_SECONDS = 5
CLAIM_HEARTBEAT_STALE_MULTIPLIER = 3
CLAIM_HEARTBEAT_STALE_MIN_SECONDS = 20
_MANUAL_FIX_PROMPT_ALLOWED_RUNNER_STATUSES = {
    "BLOCKED_BY_ACCEPTANCE_FAILURE",
    "BLOCKED_BY_SCOPE_VIOLATION",
    "BLOCKED_BY_MODEL_FAILURE",
    "BLOCKED_BY_MAX_FIX_ATTEMPTS",
    "FAILED",
    "CANCELLED",
    "BLOCKED",
}
_MANUAL_FIX_PROMPT_REJECTED_RUNNER_STATUSES = {
    "VERSION_PASSED",
    "COMPLETED",
    "READY",
    "PROMPT_READY",
    "FIX_PROMPT_READY",
}


class MCPExecutorWorkflowManager:
    def __init__(self, project_root: str):
        self.project_root = os.path.abspath(os.path.expanduser(project_root))
        self._service = ExecutorRunOnceService(project_root)
        preview_rel_dir = os.path.join(resolve_project_runner_rel_dir(self.project_root), PREVIEWS_DIR)
        self._previews_root = resolve_project_runner_path(self.project_root, PREVIEWS_DIR)
        self._claims_root = os.path.join(self._previews_root, CLAIMS_DIR)
        self._confirmation = ExecutorConfirmationStore(self.project_root, preview_rel_dir, PREVIEW_TTL_SECONDS)
        self._claims = ExecutorRunClaimStore(
            self.project_root,
            preview_rel_dir,
            CLAIMS_DIR,
            CLAIM_HEARTBEAT_INTERVAL_SECONDS,
            CLAIM_HEARTBEAT_STALE_MULTIPLIER,
            CLAIM_HEARTBEAT_STALE_MIN_SECONDS,
        )
        self._state_mutations = RunnerStateMutationService()

    def handle(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        action_map: dict[str, Any] = {
            "preflight": self._preflight,
            "run_once_preview": self._run_once_preview,
            "run_once": self._run_once,
            "run_bounded_preview": self._run_bounded_preview,
            "run_bounded": self._run_bounded,
            "get_audit_package": self._get_audit_package,
            "refresh_audit_package": self._refresh_audit_package,
            "recheck_report_preview": self._recheck_report_preview,
            "recheck_report_apply": self._recheck_report_apply,
            "manual_fix_prompt_preview": self._manual_fix_prompt_preview,
            "manual_fix_prompt_apply": self._manual_fix_prompt_apply,
            "manual_validation_preview": self._manual_validation_preview,
            "manual_validation_apply": self._manual_validation_apply,
            "scope_mismatch_preview": self._scope_mismatch_preview,
            "scope_mismatch_apply": self._scope_mismatch_apply,
            "state_lineage_reconciliation_preview": self._state_lineage_reconciliation_preview,
            "state_lineage_reconciliation_apply": self._state_lineage_reconciliation_apply,
            "final_version_closeout_preview": self._final_version_closeout_preview,
            "final_version_closeout_apply": self._final_version_closeout_apply,
            "reconcile_orphaned_claims_preview": self._reconcile_orphaned_claims_preview,
            "reconcile_orphaned_claims_apply": self._reconcile_orphaned_claims_apply,
            "status": self._status,
        }
        handler = action_map.get(action)
        if handler is None:
            return {
                "ok": False,
                "error_code": "UNKNOWN_ACTION",
                "message": "不支持的操作。支持：preflight、run_once_preview、run_once、run_bounded_preview、run_bounded、get_audit_package、refresh_audit_package、recheck_report_preview、recheck_report_apply、manual_fix_prompt_preview、manual_fix_prompt_apply、manual_validation_preview、manual_validation_apply、scope_mismatch_preview、scope_mismatch_apply、state_lineage_reconciliation_preview、state_lineage_reconciliation_apply、final_version_closeout_preview、final_version_closeout_apply、reconcile_orphaned_claims_preview、reconcile_orphaned_claims_apply、status。",
            }
        return handler(params)

    def _preflight(self, params: dict[str, Any]) -> dict[str, Any]:
        provider = self._str_param(params.get("provider"), default="codex", lower=True)
        execution_mode = self._str_param(params.get("execution_mode"), default="run", lower=True)
        result = self._service.preflight(provider=provider, execution_mode=execution_mode)
        return preflight_result(result, provider=provider, execution_mode=execution_mode)

    def _run_once_preview(self, params: dict[str, Any]) -> dict[str, Any]:
        params_provider_raw = _sanitize_optional_str(params.get("provider"))
        params_model_raw = _sanitize_optional_str(params.get("model"))
        provider = self._str_param(params.get("provider"), default="codex", lower=True)
        execution_mode = self._str_param(params.get("execution_mode"), default="run", lower=True)
        executor_session_mode = _sanitize_optional_str(params.get("executor_session_mode"))
        if executor_session_mode is not None and executor_session_mode not in ("auto", "resume_existing", "start_new"):
            return self._error(
                "run_once_preview",
                "INVALID_EXECUTOR_SESSION_MODE",
                f"executor_session_mode 必须是 auto、resume_existing 或 start_new，收到：{executor_session_mode}",
            )
        executor_session_mode = executor_session_mode or "auto"
        selected_executor_profile = self._build_selected_executor_profile(
            provider=provider,
            params_provider=params_provider_raw,
            params_model=params_model_raw,
        )
        provider = str(selected_executor_profile["provider"])

        preflight_result = self._service.preflight(provider=provider, execution_mode=execution_mode)
        if preflight_result.get("preflight_blocked"):
            return {
                "ok": False,
                "action": "run_once_preview",
                "status": "blocked",
                "risk_level": "blocked",
                "provider": preflight_result.get("provider", provider),
                "execution_mode": preflight_result.get("execution_mode", execution_mode),
                "message": "preflight 未通过，无法生成 run_once_preview。",
                "blocks": preflight_result.get("blocks", []),
                "warnings": preflight_result.get("warnings", []),
            }

        preview_key = self._generate_preview_key(prefix="exec_preview")
        artifact = run_once_preview_artifact(
            preview_id=preview_key,
            project_root=self.project_root,
            preflight_result=preflight_result,
            provider=provider,
            execution_mode=execution_mode,
            created_at=self._now_iso(),
            expires_at=self._now_iso_ts(PREVIEW_TTL_SECONDS),
        )
        artifact["model"] = selected_executor_profile.get("model")
        artifact["model_source"] = selected_executor_profile.get("model_source")
        artifact["reasoning_effort"] = selected_executor_profile.get("reasoning_effort")
        artifact["reasoning_effort_source"] = selected_executor_profile.get("reasoning_effort_source")
        self._write_preview_artifact(preview_key, artifact)
        pending_alignment = self._build_pending_alignment_summary(
            current_version=str(artifact.get("current_version") or "").strip()
        )
        warnings = list(pending_alignment.get("warnings", []))
        warning_codes = list(pending_alignment.get("warning_codes", []))
        pending_versions = pending_alignment.get("pending_versions", [])
        next_not_started_version = pending_alignment.get("next_not_started_version")
        pending_count = int(pending_alignment.get("pending_count", 0))
        session_store = ExecutorSessionStore(self.project_root)
        session_status = session_store.get_status()
        session_record = session_status.get("record") if isinstance(session_status, dict) else None
        if not isinstance(session_record, dict):
            session_record = {}
        continuation_decision = session_store.get_continuation_decision(requested_provider=provider)
        compact_continuation = self._compact_continuation_decision(continuation_decision)
        effective_continuation = dict(compact_continuation)
        if executor_session_mode == "start_new":
            effective_continuation.update({
                "decision": "start_new_requested",
                "decision_reason": "requested_start_new",
                "should_start_new": True,
                "should_resume": False,
                "next_action_hint": "executor_session_mode=start_new 已显式请求新会话；run_once 不应续接已有会话。",
                "risk_level": "info",
                "resume_blockers": [],
                "resume_warnings": [],
                "risk_warnings": [],
                "continuation_available": False,
            })
        session_manifest_missing = "no_session_manifest" in effective_continuation.get("hard_blockers", [])

        executor_session_affinity = self._build_executor_session_affinity(
            provider=selected_executor_profile["provider"],
            session_record=session_record,
            continuation_decision=effective_continuation,
        )
        executor_session_readiness = {
            "session_manifest_present": not session_manifest_missing,
            "missing_session_manifest": session_manifest_missing,
            "requested_session_mode": executor_session_mode,
            "decision": effective_continuation.get("decision"),
            "decision_reason": effective_continuation.get("decision_reason"),
            "should_start_new": effective_continuation.get("should_start_new"),
            "should_resume": effective_continuation.get("should_resume"),
            "message": "未发现可续接执行器会话；run_once 将启动新会话并生成 session manifest。" if session_manifest_missing else effective_continuation.get("next_action_hint"),
        }

        # Add profile_provider_matches_session_provider to affinity
        session_provider = _sanitize_optional_str(session_record.get("provider"))
        profile_provider = selected_executor_profile["provider"]
        base_affinity = executor_session_affinity.copy()
        base_affinity["selected_provider_matches_session_provider"] = (
            bool(profile_provider and session_provider and profile_provider == session_provider)
        )
        base_affinity["session_provider"] = session_provider
        base_affinity["requested_session_mode"] = executor_session_mode
        continuation_facts = self._build_executor_session_continuation_facts(
            provider=provider,
            preflight_result=preflight_result,
            session_store=session_store,
            session_record=session_record,
            continuation_decision=continuation_decision,
            requested_session_mode=executor_session_mode,
        )
        artifact["executor_session_continuation_facts"] = continuation_facts
        self._write_preview_artifact(preview_key, artifact)

        return {
            "ok": True,
            "action": "run_once_preview",
            "status": "preview_ready",
            "risk_level": "preview",
            "preview_id": preview_key,
            "provider": preflight_result.get("provider", provider),
            "execution_mode": preflight_result.get("execution_mode", execution_mode),
            "current_version": artifact.get("current_version"),
            "pending_count": pending_count,
            "has_pending_versions": pending_count > 0,
            "pending_versions": pending_versions,
            "next_not_started_version": next_not_started_version,
            "ignored_runner_archive_files": artifact.get("ignored_runner_archive_files", []),
            "created_at": artifact.get("created_at"),
            "expires_at": artifact.get("expires_at"),
            "executor_session_readiness": executor_session_readiness,
            "executor_session_affinity": base_affinity,
            "continuation_decision": effective_continuation,
            "selected_executor_profile": selected_executor_profile,
            "executor_session_continuation_facts": continuation_facts,
            "preflight_summary": {
                "blocked": False,
                "current_version": artifact.get("current_version"),
                "current_head": artifact.get("current_head"),
                "current_branch": artifact.get("current_branch"),
                "runner_status": artifact.get("runner_status"),
                "git_clean": not bool(artifact.get("blocking_git_status_short")),
                "execution_branch_status": artifact.get("execution_branch_status"),
                "provider": artifact.get("provider"),
            },
            "warnings": warnings,
            "warning_codes": warning_codes,
            "message": (
                f"run_once_preview 已生成。使用 preview_id={preview_key} 调用 "
                "manage_executor_workflow action=run_once 执行。"
            ),
        }

    def _build_selected_executor_profile(
        self,
        *,
        provider: str,
        params_provider: str | None,
        params_model: str | None = None,
    ) -> dict[str, Any]:
        """
        Build the selected_executor_profile dict for run_once_preview.
        Resolves effective executor settings and merges them with the request params.
        """
        resolved_settings = RunnerSettingsStore().resolve_for_project(self.project_root)
        settings = resolved_settings.settings
        profile = settings.executor_profile
        settings_profile_present = profile is not None

        warnings: list[str] = []

        def _public_source(value: str | None) -> str:
            if value in {"user_settings_project", "user_settings_global", "project_settings", "plan"}:
                return str(value)
            return "default"

        # Determine provider source
        if params_provider:
            selected_provider = params_provider
            provider_source = "request"
        elif profile is not None and profile.provider and is_supported_execution_provider(profile.provider):
            selected_provider = profile.provider
            provider_source = _public_source(resolved_settings.profile_source)
        elif is_supported_execution_provider(settings.execution_provider):
            selected_provider = settings.execution_provider
            provider_source = _public_source(resolved_settings.provider_source)
        else:
            selected_provider = provider  # fallback from preflight/codex default
            provider_source = "default"

        if profile is not None and profile.provider and not is_supported_execution_provider(profile.provider):
            warnings.append(f"executor_profile 中的 provider '{profile.provider}' 无效，已回退默认。")

        # Detect explicit provider override that differs from profile provider
        profile_has_valid_provider = (
            profile is not None
            and profile.provider is not None
            and is_supported_execution_provider(profile.provider)
        )
        provider_mismatch = (
            params_provider is not None
            and profile_has_valid_provider
            and params_provider != profile.provider
        )

        # Determine model source
        if params_model:
            selected_model = params_model
            model_source = "request"
        elif provider_mismatch:
            selected_model = None
            model_source = "unavailable"
        elif profile is not None and profile.model:
            selected_model = profile.model
            model_source = _public_source(resolved_settings.profile_source)
        else:
            selected_model = None
            model_source = "unavailable"

        # Determine reasoning_effort source
        if provider_mismatch:
            selected_effort = None
            effort_source = "unavailable"
        elif profile is not None and profile.reasoning_effort:
            selected_effort = profile.reasoning_effort
            effort_source = _public_source(resolved_settings.profile_source)
        else:
            selected_effort = None
            effort_source = "unavailable"

        if provider_mismatch:
            warnings.append(
                f"executor_profile provider={profile.provider} 与请求 provider={params_provider} "
                f"不兼容，profile model/reasoning_effort 已忽略。"
            )

        notes: list[str] = []
        if selected_model and selected_provider in {"opencode", "codex", "pi"}:
            notes.append(f"model={selected_model} 将在 run_once 中传递给 {selected_provider} 执行器。")
        elif selected_model:
            warnings.append(f"model={selected_model} 已选中；当前执行器尚未接入 project-local profile model 的真实传递。")

        result: dict[str, Any] = {
            "provider": selected_provider,
            "model": selected_model,
            "reasoning_effort": selected_effort,
            "source": provider_source,
            "settings_profile_present": settings_profile_present,
            "provider_source": provider_source,
            "model_source": model_source,
            "reasoning_effort_source": effort_source,
            "warnings": warnings,
            "notes": notes,
        }
        return result

    def _build_executor_session_continuation_facts(
        self,
        *,
        provider: str,
        preflight_result: dict[str, Any],
        session_store: ExecutorSessionStore,
        session_record: dict[str, Any],
        continuation_decision: dict[str, Any],
        requested_session_mode: str = "auto",
    ) -> dict[str, Any]:
        current_version = preflight_result.get("current_version")
        session_provider = session_record.get("provider") if isinstance(session_record, dict) else None
        session_version = session_record.get("version") if isinstance(session_record, dict) else None

        # Default behavior from current auto logic
        will_resume = bool(continuation_decision.get("should_resume") is True)
        will_start_new = bool(continuation_decision.get("should_start_new") is True)
        default_reason = str(continuation_decision.get("decision_reason") or "no_session_manifest")

        # Session facts
        has_session_manifest = bool(session_record)
        identity_kind = continuation_decision.get("resume_identity_kind") or continuation_decision.get("identity_kind")
        identity_present = bool(continuation_decision.get("resume_identity_present") is True)

        # Current request facts
        prompt_file = None
        try:
            state_file = resolve_project_runner_path(self.project_root, "state.json")
            if os.path.isfile(state_file):
                with open(state_file, "r", encoding="utf-8") as f:
                    state_data = json.load(f)
                if isinstance(state_data, dict):
                    prompt_file = state_data.get("last_generated_prompt_file") or state_data.get("last_prompt_file")
        except Exception:
            pass

        allowed_files_count = 0
        acceptance_commands_count = 0
        try:
            patterns = current_plan_allowed_patterns(self.project_root)
            allowed_files_count = len(patterns)
            plan_file = resolve_project_runner_path(self.project_root, "plan.json")
            if os.path.isfile(plan_file):
                with open(plan_file, "r", encoding="utf-8") as f:
                    plan_data = json.load(f)
                if isinstance(plan_data, dict):
                    versions = plan_data.get("versions", [])
                    if isinstance(versions, list) and current_version:
                        for vs in versions:
                            if isinstance(vs, dict) and vs.get("version") == current_version:
                                cmds = vs.get("acceptance_commands") or vs.get("manual_acceptance") or []
                                if isinstance(cmds, list):
                                    acceptance_commands_count = len(cmds)
                                break
        except Exception:
            pass

        # Deltas
        version_changed = None
        if current_version is not None and session_version is not None:
            version_changed = current_version != session_version
        provider_changed = None
        if provider is not None and session_provider is not None:
            provider_changed = provider != session_provider

        # Recent activity from report store
        latest_run_status = None
        recent_failed_run_count = 0
        latest_report_id = None
        try:
            report_store = ExecutorRunReportStore(self.project_root)
            version_filter = str(current_version).strip() if isinstance(current_version, str) and current_version.strip() else None
            recent_reports = report_store.list_reports(version=version_filter, limit=5)
            if recent_reports:
                latest_report_id = recent_reports[0].get("report_id")
                latest_run_status = recent_reports[0].get("status")
                for r in recent_reports:
                    status = str(r.get("status") or "").upper()
                    if status in ("FAILED", "FAILED_BLOCKED"):
                        recent_failed_run_count += 1
        except Exception:
            pass

        latest_executor_interruption = self._load_latest_executor_interruption_facts(
            version=str(current_version).strip() if isinstance(current_version, str) and current_version.strip() else None,
        )

        return {
            "decision_owner": "gpts",
            "runner_policy": "facts_only",
            "runner_behavior_changed": False,
            "default_session_mode": "auto",
            "requested_session_mode": requested_session_mode,
            "default_behavior": {
                "will_resume_session": will_resume,
                "will_start_new_session": will_start_new,
                "reason": default_reason,
            },
            "allowed_session_modes": ["auto", "resume_existing", "start_new"],
            "session": {
                "has_session_manifest": has_session_manifest,
                "provider": session_provider,
                "resume_source_version": session_version,
                "session_identity_kind": identity_kind,
                "session_identity_present": identity_present,
            },
            "current_request": {
                "provider": provider,
                "current_version": current_version,
                "prompt_file": prompt_file,
                "allowed_files_count": allowed_files_count,
                "acceptance_commands_count": acceptance_commands_count,
            },
            "deltas": {
                "version_changed_since_session_start": version_changed,
                "provider_changed": provider_changed,
                "prompt_file_changed": None,
                "allowed_files_changed": None,
                "acceptance_commands_changed": None,
            },
            "recent_activity": {
                "latest_run_status": latest_run_status,
                "recent_failed_run_count": recent_failed_run_count,
                "latest_report_id": latest_report_id,
            },
            **({"latest_executor_interruption": latest_executor_interruption} if latest_executor_interruption else {}),
        }

    def _load_latest_executor_interruption_facts(self, version: str | None = None) -> dict[str, Any] | None:
        try:
            store = ExecutorRunReportStore(self.project_root)
            reports = store.list_reports(version=version, limit=1)
            if not reports:
                return None
            report_id = self._str_param(reports[0].get("report_id"), default="")
            if not report_id:
                return None
            report_ret = store.get_report(report_id=report_id, include_markdown=False)
            if not isinstance(report_ret, dict) or not report_ret.get("ok"):
                return None
            report = report_ret.get("report")
            if not isinstance(report, dict):
                return None
            completion_evidence = report.get("completion_evidence")
            if not isinstance(completion_evidence, dict):
                return None
            if self._str_param(completion_evidence.get("mode"), default="") != "executor_interrupted":
                return None
            changed_files_raw = completion_evidence.get("executor_changed_files")
            executor_changed_files = [
                str(item).strip()
                for item in changed_files_raw
                if str(item).strip()
            ] if isinstance(changed_files_raw, list) else []
            recovery_options_raw = completion_evidence.get("recovery_options")
            recovery_options = [
                str(item).strip()
                for item in recovery_options_raw
                if str(item).strip()
            ] if isinstance(recovery_options_raw, list) else []
            return {
                "present": True,
                "report_id": report_id,
                "classification": self._str_param(completion_evidence.get("classification"), default=""),
                "error_code": self._str_param(completion_evidence.get("error_code"), default=""),
                "interruption_kind": self._str_param(completion_evidence.get("interruption_kind"), default=""),
                "recovery_options": recovery_options,
                "executor_changed_files": executor_changed_files,
                "has_partial_worktree": bool(completion_evidence.get("has_partial_worktree")) or bool(executor_changed_files),
            }
        except Exception:
            return None

    def _build_pending_alignment_summary(self, current_version: str) -> dict[str, Any]:
        try:
            status = PlanningBridge().get_runner_status(self.project_root)
        except PlanningBridgeError:
            return {
                "pending_count": 0,
                "pending_versions": [],
                "next_not_started_version": None,
                "warnings": [],
                "warning_codes": [],
            }
        except Exception:
            return {
                "pending_count": 0,
                "pending_versions": [],
                "next_not_started_version": None,
                "warnings": [],
                "warning_codes": [],
            }

        pending_versions = status.get("pending_versions")
        if not isinstance(pending_versions, list):
            pending_versions = []
        next_not_started_version = status.get("next_not_started_version")
        try:
            pending_count = int(status.get("pending_count", len(pending_versions)))
        except Exception:
            pending_count = len(pending_versions)

        warnings: list[str] = []
        warning_codes: list[str] = []
        expected = str(next_not_started_version or "").strip()
        if expected and current_version and expected != current_version:
            warnings.append(
                f"当前将执行版本为 {current_version}，待执行队列首项为 {expected}。建议先确认运行目标版本。"
            )
            warning_codes.append("CURRENT_VERSION_PENDING_MISMATCH")
        return {
            "pending_count": pending_count,
            "pending_versions": pending_versions,
            "next_not_started_version": next_not_started_version,
            "warnings": warnings,
            "warning_codes": warning_codes,
        }

    def _run_once(self, params: dict[str, Any]) -> dict[str, Any]:
        preview_id = self._str_param(params.get("preview_id", params.get("preview_key", "")), default="")
        provider = self._str_param(params.get("provider"), default="codex", lower=True)
        model = _sanitize_optional_str(params.get("model"))
        execution_mode = self._str_param(params.get("execution_mode"), default="run", lower=True)
        include_diff_summary = self._bool_param(params.get("include_diff_summary"), default=True)
        include_report_markdown = self._bool_param(params.get("include_report_markdown"), default=False)
        max_report_chars = self._bounded_int_param(params.get("max_report_chars"), default=30000, minimum=1, maximum=60000)
        reason = self._str_param(params.get("reason"), default="")
        executor_session_mode = _sanitize_optional_str(params.get("executor_session_mode"))
        if executor_session_mode is not None and executor_session_mode not in ("auto", "resume_existing", "start_new"):
            return self._error(
                "run_once",
                "INVALID_EXECUTOR_SESSION_MODE",
                f"executor_session_mode 必须是 auto、resume_existing 或 start_new，收到：{executor_session_mode}",
            )
        executor_session_mode = executor_session_mode or "auto"

        if not preview_id:
            return self._error("run_once", "PREVIEW_ID_REQUIRED", "run_once 需要 preview_id。请先调用 run_once_preview 获取。")

        existing_claim = self._read_preview_claim_record(preview_id)
        if isinstance(existing_claim, dict):
            return self._already_claimed_error("run_once", preview_id, existing_claim)

        artifact = self._read_preview_artifact(preview_id)
        if artifact is None:
            return self._error(
                "run_once",
                "PREVIEW_NOT_FOUND",
                f"preview_id={preview_id} 不存在或已过期。请重新调用 run_once_preview。",
            )
        if artifact.get("artifact_kind") not in (None, "run_once"):
            return self._error("run_once", "PREVIEW_KIND_MISMATCH", "preview_id 类型不匹配，当前不是 run_once_preview。")

        artifact_model = _sanitize_optional_str(artifact.get("model"))
        artifact_model_source = _sanitize_optional_str(artifact.get("model_source"))
        artifact_reasoning_effort = _sanitize_optional_str(artifact.get("reasoning_effort"))
        artifact_reasoning_effort_source = _sanitize_optional_str(artifact.get("reasoning_effort_source"))
        if model is not None and model != artifact_model:
            return self._error(
                "run_once",
                "MODEL_MISMATCH",
                f"model 不匹配。preview 中记录的是 {artifact_model or '默认模型'}，但请求的是 {model or '默认模型'}。",
            )
        effective_model = artifact_model
        effective_model_source = artifact_model_source
        effective_reasoning_effort = artifact_reasoning_effort
        effective_reasoning_effort_source = artifact_reasoning_effort_source

        validation = self._validate_preview_artifact(preview_id, artifact, provider, execution_mode)
        if not validation.get("ok"):
            return validation

        continuation_facts = artifact.get("executor_session_continuation_facts")
        allowed_session_modes = None
        if isinstance(continuation_facts, dict):
            allowed_session_modes = continuation_facts.get("allowed_session_modes")
        if isinstance(allowed_session_modes, list):
            allowed_modes = {str(item) for item in allowed_session_modes if isinstance(item, str)}
            if executor_session_mode not in allowed_modes:
                return self._error(
                    "run_once",
                    "EXECUTOR_SESSION_MODE_NOT_ALLOWED_BY_PREVIEW",
                    f"executor_session_mode={executor_session_mode} 不在 run_once_preview 允许的会话模式内。",
                )
        elif executor_session_mode != "auto":
            return self._error(
                "run_once",
                "EXECUTOR_SESSION_MODE_PREVIEW_FACTS_MISSING",
                "当前 preview 未包含 executor_session_continuation_facts，不能使用显式会话模式。请重新调用 run_once_preview。",
            )

        re_preflight = self._service.preflight(provider=provider, execution_mode=execution_mode)
        if re_preflight.get("preflight_blocked"):
            return {
                "ok": False,
                "action": "run_once",
                "status": "blocked",
                "risk_level": "blocked",
                "error_code": "PREFLIGHT_BLOCKED",
                "message": "run_once 前置 preflight 未通过。",
                "provider": re_preflight.get("provider", provider),
                "execution_mode": re_preflight.get("execution_mode", execution_mode),
                "classification": "blocked_preflight",
                "blocks": re_preflight.get("blocks", []),
                "warnings": re_preflight.get("warnings", []),
                "preview_id": preview_id,
                "next_actions": self._service._build_next_actions(
                    "blocked_preflight",
                    re_preflight.get("provider", provider),
                    re_preflight.get("execution_mode", execution_mode),
                ),
            }

        compare_result = self._compare_artifact_with_preflight(artifact, re_preflight)
        if not compare_result.get("ok"):
            return compare_result

        if re_preflight.get("blocking_git_status_short"):
            return self._error(
                "run_once",
                "GIT_STATUS_MISMATCH",
                "run_once 前置校验要求 blocking_git_status_short 为空，当前工作区存在阻断执行器的改动。",
            )

        # Validate explicit session mode before proceeding
        if executor_session_mode == "resume_existing":
            session_store = ExecutorSessionStore(self.project_root)
            session_decision = session_store.get_continuation_decision(requested_provider=provider)
            cd = session_decision if isinstance(session_decision, dict) else {}
            can_resume = bool(
                cd.get("decision") == "resume_auto_eligible"
                and cd.get("should_resume") is True
            )
            if not can_resume:
                return {
                    "ok": False,
                    "action": "run_once",
                    "status": "blocked",
                    "error_code": "RESUME_EXISTING_NOT_AVAILABLE",
                    "message": "executor_session_mode=resume_existing 但当前没有兼容的可续接执行器会话。",
                    "provider": provider,
                    "execution_mode": execution_mode,
                    "preview_id": preview_id,
                }

        claim_result = self._claim_preview_artifact(
            action="run_once",
            preview_id=preview_id,
            artifact=artifact,
            provider=provider,
            execution_mode=execution_mode,
        )
        if not claim_result.get("ok"):
            return claim_result
        run_id = str(claim_result.get("run_id", ""))
        preview_claimed_at = str(claim_result.get("claimed_at", ""))
        preview_claim_status = str(claim_result.get("preview_claim_status", ""))

        self._start_run_once_background_worker(
            provider=provider,
            execution_mode=execution_mode,
            include_diff_summary=include_diff_summary,
            include_report_markdown=include_report_markdown,
            max_report_chars=max_report_chars,
            reason=reason,
            executor_session_mode=executor_session_mode,
            model=effective_model,
            model_source=effective_model_source,
            reasoning_effort=effective_reasoning_effort,
            reasoning_effort_source=effective_reasoning_effort_source,
            run_id=run_id,
            preview_id=preview_id,
            preview_claimed_at=preview_claimed_at,
            preview_claim_status=preview_claim_status,
        )

        return run_once_started_result(
            run_id=run_id,
            preview_id=preview_id,
            preview_claimed_at=preview_claimed_at,
        )

    def _start_run_once_background_worker(
        self,
        provider: str, execution_mode: str,
        include_diff_summary: bool, include_report_markdown: bool,
        max_report_chars: int, reason: str,
        executor_session_mode: str = "auto",
        model: str | None = None,
        model_source: str | None = None,
        reasoning_effort: str | None = None,
        reasoning_effort_source: str | None = None,
        run_id: str = "", preview_id: str = "",
        preview_claimed_at: str = "", preview_claim_status: str = "",
    ) -> None:
        started_at = self._now_iso()
        self._mark_claim_worker_started(
            preview_id=preview_id,
            run_id=run_id,
            thread_started_at=started_at,
            worker_pid=os.getpid(),
            heartbeat_interval_seconds=CLAIM_HEARTBEAT_INTERVAL_SECONDS,
        )
        run_once_callable = self._service.run_once
        threading.Thread(
            target=self._run_once_background_worker,
            args=(
                provider, execution_mode,
                include_diff_summary, include_report_markdown,
                max_report_chars, reason,
                executor_session_mode, model, model_source,
                reasoning_effort, reasoning_effort_source,
                run_id, preview_id,
                preview_claimed_at, preview_claim_status,
                run_once_callable,
            ),
            daemon=True,
        ).start()

    def _run_once_background_worker(
        self,
        provider: str, execution_mode: str,
        include_diff_summary: bool, include_report_markdown: bool,
        max_report_chars: int, reason: str,
        executor_session_mode: str = "auto",
        model: str | None = None,
        model_source: str | None = None,
        reasoning_effort: str | None = None,
        reasoning_effort_source: str | None = None,
        run_id: str = "", preview_id: str = "",
        preview_claimed_at: str = "", preview_claim_status: str = "",
        run_once_callable: Callable[..., dict[str, Any]] | None = None,
    ) -> None:
        heartbeat_stop_event = threading.Event()
        heartbeat_state: dict[str, Any] = {"errors": 0, "last_error": ""}

        heartbeat_thread = threading.Thread(
            target=self._run_once_heartbeat_worker,
            args=(
                preview_id,
                run_id,
                heartbeat_stop_event,
                CLAIM_HEARTBEAT_INTERVAL_SECONDS,
                heartbeat_state,
            ),
            daemon=True,
        )
        heartbeat_thread.start()
        self._refresh_claim_heartbeat(preview_id=preview_id, run_id=run_id, error_state=heartbeat_state)
        try:
            service_run_once = run_once_callable or self._service.run_once
            result = service_run_once(
                provider=provider,
                execution_mode=execution_mode,
                include_diff_summary=include_diff_summary,
                include_report_markdown=include_report_markdown,
                max_report_chars=max_report_chars,
                reason=reason,
                executor_session_mode=executor_session_mode,
                model=model,
                model_source=model_source,
                reasoning_effort=reasoning_effort,
                reasoning_effort_source=reasoning_effort_source,
                run_id=run_id,
                preview_id=preview_id,
                preview_claimed_at=preview_claimed_at,
                preview_claim_status=preview_claim_status,
            )
            final_status = "COMPLETED" if bool(result.get("ok")) else "FAILED"
            report_id = str(result.get("latest_report_id") or "")
            error_code = ""
            error_message = ""
            exception_type = ""
            blockers: list[str] = []
            warnings: list[str] = []
            if not result.get("ok"):
                error_code = str(result.get("error_code") or "EXECUTOR_FAILED")
                error_message = str(result.get("message") or "执行器返回失败状态")
                blockers = self._str_list(result.get("blockers", []))
                warnings = self._str_list(result.get("warnings", []))
        except Exception as exc:
            final_status = "FAILED"
            report_id = ""
            error_code = "BACKGROUND_WORKER_CRASHED"
            error_message = f"后台执行器 worker 异常：{exc}"
            exception_type = type(exc).__name__
            logging.exception("run_once 后台 worker 异常")
            blockers = []
            warnings = []
        finally:
            heartbeat_stop_event.set()
            heartbeat_thread.join(timeout=max(1.0, float(CLAIM_HEARTBEAT_INTERVAL_SECONDS)))
            self._refresh_claim_heartbeat(preview_id=preview_id, run_id=run_id, error_state=heartbeat_state)
            heartbeat_error_count = int(heartbeat_state.get("errors", 0) or 0)
            if heartbeat_error_count > 0:
                warnings = list(warnings)
                warnings.append("HEARTBEAT_UPDATE_FAILED")
                if not error_code and final_status == "FAILED":
                    error_code = "CLAIM_HEARTBEAT_UPDATE_FAILED"
                if not error_message and final_status == "FAILED":
                    error_message = "执行器 heartbeat 写入失败，请检查服务日志。"
            self._delete_preview_artifact(preview_id)
            self._finalize_preview_claim(
                preview_id=preview_id,
                run_id=run_id,
                final_status=final_status,
                report_id=report_id,
                error_code=error_code,
                message=error_message,
                exception_type=exception_type,
                blockers=blockers,
                warnings=warnings,
            )

    def _run_once_heartbeat_worker(
        self,
        preview_id: str,
        run_id: str,
        stop_event: threading.Event,
        heartbeat_interval_seconds: int,
        error_state: dict[str, Any],
    ) -> None:
        interval = max(1, int(heartbeat_interval_seconds))
        while not stop_event.wait(interval):
            self._refresh_claim_heartbeat(
                preview_id=preview_id,
                run_id=run_id,
                error_state=error_state,
            )

    def _run_bounded_preview(self, params: dict[str, Any]) -> dict[str, Any]:
        provider = self._str_param(params.get("provider"), default="codex", lower=True)
        max_iterations = self._bounded_int_param(params.get("max_iterations"), default=1, minimum=1, maximum=3)
        trusted_mode = self._bool_param(params.get("trusted_mode"), default=False)
        allow_fix = self._bool_param(params.get("allow_fix"), default=False)
        allow_commit = self._bool_param(params.get("allow_commit"), default=False)
        stop_on_acceptance_failure = self._bool_param(params.get("stop_on_acceptance_failure"), default=True)
        stop_on_scope_violation = self._bool_param(params.get("stop_on_scope_violation"), default=True)
        stop_on_diff_too_large = self._bool_param(params.get("stop_on_diff_too_large"), default=True)
        max_total_diff_chars = self._bounded_int_param(params.get("max_total_diff_chars"), default=80000, minimum=1, maximum=200000)

        if max_iterations > 1 and not trusted_mode:
            return {
                "ok": False,
                "action": "run_bounded_preview",
                "status": "blocked",
                "risk_level": "blocked",
                "error_code": "TRUSTED_MODE_REQUIRED",
                "message": "max_iterations > 1 需要 trusted_mode=true。",
                "provider": provider,
                "max_iterations": max_iterations,
                "trusted_mode": trusted_mode,
                "allow_fix": allow_fix,
                "allow_commit": allow_commit,
                "blocks": [{"code": "TRUSTED_MODE_REQUIRED", "message": "max_iterations > 1 requires trusted_mode=true"}],
                "warnings": [],
            }

        preflight = self._service.preflight(provider=provider, execution_mode="run")
        if preflight.get("preflight_blocked"):
            return {
                "ok": False,
                "action": "run_bounded_preview",
                "status": "blocked",
                "risk_level": "blocked",
                "error_code": "PREFLIGHT_BLOCKED",
                "message": "preflight 未通过，无法生成 run_bounded_preview。",
                "provider": provider,
                "max_iterations": max_iterations,
                "trusted_mode": trusted_mode,
                "allow_fix": allow_fix,
                "allow_commit": allow_commit,
                "blocks": preflight.get("blocks", []),
                "warnings": preflight.get("warnings", []),
            }

        session_store = ExecutorSessionStore(self.project_root)
        continuation_decision = session_store.get_continuation_decision(requested_provider=provider)
        resume_preview = session_store.get_resume_invocation_preview(requested_provider=provider)

        preview_id = self._generate_preview_key(prefix="bounded_preview")
        artifact = run_bounded_preview_artifact(
            preview_id=preview_id,
            project_root=self.project_root,
            preflight=preflight,
            provider=provider,
            max_iterations=max_iterations,
            trusted_mode=trusted_mode,
            allow_fix=allow_fix,
            allow_commit=allow_commit,
            stop_on_acceptance_failure=stop_on_acceptance_failure,
            stop_on_scope_violation=stop_on_scope_violation,
            stop_on_diff_too_large=stop_on_diff_too_large,
            max_total_diff_chars=max_total_diff_chars,
            continuation_decision=self._compact_continuation_decision(continuation_decision),
            resume_invocation_preview=self._compact_resume_preview(resume_preview),
            created_at=self._now_iso(),
            expires_at=self._now_iso_ts(PREVIEW_TTL_SECONDS),
        )
        self._write_preview_artifact(preview_id, artifact)

        stop_conditions = [
            "max_iterations_reached",
            "acceptance_failed",
            "scope_violation",
            "executor_failed",
            "provider_unavailable",
            "dirty_worktree_unexpected",
            "diff_too_large",
            "missing_fix_prompt",
            "max_fix_attempts",
            "continuation_risk_warning",
            "report_missing",
            "preview_invalidated",
        ]

        return {
            "ok": True,
            "action": "run_bounded_preview",
            "status": "preview_ready",
            "risk_level": "preview",
            "preview_id": preview_id,
            "provider": provider,
            "execution_mode": "run",
            "current_version": artifact.get("current_version"),
            "created_at": artifact.get("created_at"),
            "expires_at": artifact.get("expires_at"),
            "ignored_runner_archive_files": artifact.get("ignored_runner_archive_files", []),
            "max_iterations": max_iterations,
            "trusted_mode": trusted_mode,
            "allow_fix": allow_fix,
            "allow_commit": allow_commit,
            "stop_conditions": stop_conditions,
            "gates": {
                "preflight_blocked": False,
                "git_clean_required": True,
                "trusted_mode_required_for_multi_iteration": max_iterations > 1,
            },
            "loop_plan": {
                "iterations_requested": max_iterations,
                "initial_execution_mode": "run",
                "allow_fix": allow_fix,
                "allow_commit": allow_commit,
                "stop_on_acceptance_failure": stop_on_acceptance_failure,
                "stop_on_scope_violation": stop_on_scope_violation,
                "stop_on_diff_too_large": stop_on_diff_too_large,
                "max_total_diff_chars": max_total_diff_chars,
            },
            "next_actions": [
                {
                    "action": "manage_executor_workflow.run_bounded",
                    "label": "执行 bounded loop",
                    "reason": "使用 run_bounded_preview 的 preview_id 执行 bounded loop。",
                    "tool": "manage_executor_workflow",
                    "params": {
                        "action": "run_bounded",
                        "preview_id": preview_id,
                        "provider": provider,
                    },
                    "risk_level": "commit",
                    "requires_confirmation": True,
                }
            ],
            "warnings": preflight.get("warnings", []),
            "blocks": [],
        }

    def _run_bounded(self, params: dict[str, Any]) -> dict[str, Any]:
        preview_id = self._str_param(params.get("preview_id", params.get("preview_key", "")), default="")
        provider = self._str_param(params.get("provider"), default="codex", lower=True)
        include_diff_summary = self._bool_param(params.get("include_diff_summary"), default=True)
        include_report_markdown = self._bool_param(params.get("include_report_markdown"), default=False)
        max_report_chars = self._bounded_int_param(params.get("max_report_chars"), default=30000, minimum=1, maximum=60000)
        reason = self._str_param(params.get("reason"), default="")

        if not preview_id:
            return self._error("run_bounded", "PREVIEW_ID_REQUIRED", "run_bounded 需要 preview_id。请先调用 run_bounded_preview。")

        existing_claim = self._read_preview_claim_record(preview_id)
        if isinstance(existing_claim, dict):
            return self._already_claimed_error("run_bounded", preview_id, existing_claim)

        artifact = self._read_preview_artifact(preview_id)
        if artifact is None:
            return self._error("run_bounded", "PREVIEW_NOT_FOUND", f"preview_id={preview_id} 不存在或已过期。")
        if artifact.get("artifact_kind") != "run_bounded":
            return self._error("run_bounded", "PREVIEW_KIND_MISMATCH", "preview_id 不是 run_bounded_preview 生成的 artifact。")

        guard_error = self._preview_guard_error(
            "run_bounded",
            preview_id,
            artifact,
            expired_message="preview_id 已过期，请重新生成 run_bounded_preview。",
        )
        if guard_error is not None:
            return guard_error

        max_iterations = self._bounded_int_param(artifact.get("max_iterations"), default=1, minimum=1, maximum=3)
        trusted_mode = bool(artifact.get("trusted_mode", False))
        allow_fix = bool(artifact.get("allow_fix", False))
        allow_commit = bool(artifact.get("allow_commit", False))
        stop_on_acceptance_failure = bool(artifact.get("stop_on_acceptance_failure", True))
        stop_on_scope_violation = bool(artifact.get("stop_on_scope_violation", True))
        stop_on_diff_too_large = bool(artifact.get("stop_on_diff_too_large", True))
        max_total_diff_chars = self._bounded_int_param(artifact.get("max_total_diff_chars"), default=80000, minimum=1, maximum=200000)

        requested_max_iterations = params.get("max_iterations")
        if requested_max_iterations is not None:
            requested_value = self._bounded_int_param(requested_max_iterations, default=max_iterations, minimum=1, maximum=3)
            if requested_value != max_iterations:
                return self._error("run_bounded", "MAX_ITERATIONS_MISMATCH", "当前请求 max_iterations 与 preview artifact 不一致。")

        requested_trusted_mode = params.get("trusted_mode")
        if requested_trusted_mode is not None and bool(requested_trusted_mode) != trusted_mode:
            return self._error("run_bounded", "TRUSTED_MODE_MISMATCH", "当前请求 trusted_mode 与 preview artifact 不一致。")

        if max_iterations > 1 and not trusted_mode:
            return self._error("run_bounded", "TRUSTED_MODE_REQUIRED", "max_iterations > 1 需要 trusted_mode=true。")

        preflight = self._service.preflight(provider=provider, execution_mode="run")
        if preflight.get("preflight_blocked"):
            preflight_blocks = preflight.get("blocks", [])
            codes = {
                str(item.get("code", ""))
                for item in preflight_blocks
                if isinstance(item, dict)
            }
            stop_reason = "dirty_worktree_unexpected" if "DIRTY_GIT_STATUS" in codes else "blocked_preflight"
            return self._bounded_blocked_result(
                preview_id=preview_id,
                provider=provider,
                max_iterations=max_iterations,
                trusted_mode=trusted_mode,
                allow_fix=allow_fix,
                allow_commit=allow_commit,
                reason=stop_reason,
                message="run_bounded 前置 preflight 未通过。",
                blocks=preflight_blocks,
                warnings=preflight.get("warnings", []),
            )

        compare_result = self._compare_bounded_artifact_with_preflight(artifact, preflight)
        if not compare_result.get("ok"):
            return compare_result

        if preflight.get("blocking_git_status_short"):
            return self._bounded_blocked_result(
                preview_id=preview_id,
                provider=provider,
                max_iterations=max_iterations,
                trusted_mode=trusted_mode,
                allow_fix=allow_fix,
                allow_commit=allow_commit,
                reason="dirty_worktree_unexpected",
                message="run_bounded 执行前存在阻断执行器的工作区改动。",
                blocks=[{"code": "DIRTY_GIT_STATUS", "message": "blocking_git_status_short 不能为空。"}],
                warnings=[],
            )

        session_store = ExecutorSessionStore(self.project_root)
        continuation_decision = session_store.get_continuation_decision(requested_provider=provider)
        hard_blockers = continuation_decision.get("hard_blockers", []) if isinstance(continuation_decision, dict) else []
        risk_level = continuation_decision.get("risk_level") if isinstance(continuation_decision, dict) else "none"
        decision = str(continuation_decision.get("decision") or "") if isinstance(continuation_decision, dict) else ""
        hard_blockers_list = [str(item) for item in hard_blockers if isinstance(item, str)]
        hard_blockers_effective = [item for item in hard_blockers_list if item != "no_session_manifest"]
        if hard_blockers_effective or (str(risk_level) == "blocked" and decision != "start_new_no_session"):
            return self._bounded_blocked_result(
                preview_id=preview_id,
                provider=provider,
                max_iterations=max_iterations,
                trusted_mode=trusted_mode,
                allow_fix=allow_fix,
                allow_commit=allow_commit,
                reason="continuation_risk_warning",
                message="continuation 决策存在 hard_blockers 或 blocked 风险。",
                blocks=[{"code": "CONTINUATION_RISK_WARNING", "message": "续接风险过高，停止执行。"}],
                warnings=hard_blockers_effective,
            )

        inventory = preflight.get("executor_inventory")
        if not self._provider_available(inventory, provider):
            return self._bounded_blocked_result(
                preview_id=preview_id,
                provider=provider,
                max_iterations=max_iterations,
                trusted_mode=trusted_mode,
                allow_fix=allow_fix,
                allow_commit=allow_commit,
                reason="provider_unavailable",
                message="执行器 provider 当前不可用。",
                blocks=[{"code": "PROVIDER_UNAVAILABLE", "message": "provider unavailable"}],
                warnings=[],
            )

        claim_result = self._claim_preview_artifact(
            action="run_bounded",
            preview_id=preview_id,
            artifact=artifact,
            provider=provider,
            execution_mode="run",
        )
        if not claim_result.get("ok"):
            return claim_result
        run_id = str(claim_result.get("run_id", ""))
        preview_claimed_at = str(claim_result.get("claimed_at", ""))
        preview_claim_status = str(claim_result.get("preview_claim_status", ""))

        iteration_results: list[dict[str, Any]] = []
        workflow_steps: list[dict[str, Any]] = [
            {"action": "bounded_preflight", "status": "completed"},
            {"action": "loop_preview_validation", "status": "completed"},
        ]

        all_changed_files: list[str] = []
        total_diff_chars = 0
        latest_report_id = None
        latest_report_summary: dict[str, Any] = {}
        final_classification = "blocked_preflight"
        stop_reason = "max_iterations_reached"
        stop_conditions_triggered: list[str] = []
        warnings: list[str] = []
        blockers: list[str] = []

        next_mode = "run"
        iterations_completed = 0

        for idx in range(1, max_iterations + 1):
            step_prefix = f"iteration_{idx}"
            iter_preflight = self._service.preflight(provider=provider, execution_mode=next_mode)
            workflow_steps.append({"action": f"{step_prefix}_preflight", "status": "completed"})
            if iter_preflight.get("preflight_blocked"):
                stop_reason = "blocked_preflight"
                stop_conditions_triggered.append("blocked_preflight")
                blockers.extend([b.get("code", "") for b in iter_preflight.get("blocks", []) if isinstance(b, dict)])
                break
            if iter_preflight.get("blocking_git_status_short"):
                stop_reason = "dirty_worktree_unexpected"
                stop_conditions_triggered.append("dirty_worktree_unexpected")
                blockers.append("DIRTY_GIT_STATUS")
                break

            run_result = self._service.run_once(
                provider=provider,
                execution_mode=next_mode,
                include_diff_summary=include_diff_summary,
                include_report_markdown=include_report_markdown,
                max_report_chars=max_report_chars,
                reason=reason,
                run_id=run_id,
                preview_id=preview_id,
                preview_claimed_at=preview_claimed_at,
                preview_claim_status=preview_claim_status,
            )
            workflow_steps.append({"action": f"{step_prefix}_run_once", "status": "completed" if run_result.get("ok") else "failed"})

            classification = str(run_result.get("classification") or "executor_failed")
            final_classification = classification
            changed_files = self._str_list(run_result.get("changed_files"))
            diff_summary = str(run_result.get("diff_summary") or "")
            total_diff_chars += len(diff_summary)
            for changed in changed_files:
                if changed not in all_changed_files:
                    all_changed_files.append(changed)

            latest_report_id = run_result.get("latest_report_id")
            report_summary = run_result.get("report_summary")
            latest_report_summary = report_summary if isinstance(report_summary, dict) else {}

            iteration_result = {
                "iteration": idx,
                "execution_mode": next_mode,
                "provider": provider,
                "status": run_result.get("status", "failed"),
                "run_status": run_result.get("run_status"),
                "runner_status": run_result.get("runner_status"),
                "classification": classification,
                "changed_files": changed_files,
                "latest_report_id": latest_report_id,
                "stop_reason": "",
                "git_head_before": run_result.get("git_head_before"),
                "git_head_after": run_result.get("git_head_after"),
                "git_status_after": run_result.get("git_status_after", ""),
            }
            iteration_results.append(iteration_result)
            iterations_completed = idx

            workflow_steps.append({"action": f"{step_prefix}_report_read", "status": "completed"})
            workflow_steps.append({"action": f"{step_prefix}_diff_read", "status": "completed"})
            workflow_steps.append({"action": f"{step_prefix}_classification", "status": "completed"})

            stop_check = self._evaluate_loop_stop(
                classification=classification,
                run_result=run_result,
                allow_fix=allow_fix,
                allow_commit=allow_commit,
                stop_on_acceptance_failure=stop_on_acceptance_failure,
                stop_on_scope_violation=stop_on_scope_violation,
                stop_on_diff_too_large=stop_on_diff_too_large,
                total_diff_chars=total_diff_chars,
                max_total_diff_chars=max_total_diff_chars,
            )
            workflow_steps.append({"action": "stop_condition_evaluation", "status": "completed"})

            if stop_check["stop"]:
                stop_reason = stop_check["reason"]
                stop_conditions_triggered.append(stop_check["reason"])
                warnings.extend(stop_check.get("warnings", []))
                blockers.extend(stop_check.get("blockers", []))
                iteration_result["stop_reason"] = stop_reason
                break

            if classification == "failed_acceptance" and allow_fix:
                if self._can_run_fix_next():
                    next_mode = "fix"
                else:
                    stop_reason = "missing_fix_prompt"
                    stop_conditions_triggered.append("missing_fix_prompt")
                    blockers.append("FIX_PROMPT_NOT_READY")
                    iteration_result["stop_reason"] = stop_reason
                    break
            else:
                next_mode = "run"

        if not stop_conditions_triggered and iterations_completed >= max_iterations:
            stop_reason = "max_iterations_reached"
            stop_conditions_triggered.append("max_iterations_reached")

        self._delete_preview_artifact(preview_id)
        self._finalize_preview_claim(
            preview_id=preview_id,
            run_id=run_id,
            final_status="COMPLETED",
            report_id=str(latest_report_id or ""),
        )

        next_actions = self._build_bounded_next_actions(
            classification=final_classification,
            provider=provider,
            allow_commit=allow_commit,
        )

        return {
            "ok": True,
            "action": "run_bounded",
            "status": "completed" if iterations_completed > 0 else "blocked",
            "risk_level": "commit",
            "preview_id": preview_id,
            "provider": provider,
            "max_iterations": max_iterations,
            "iterations_requested": max_iterations,
            "iterations_completed": iterations_completed,
            "stopped": True,
            "stop_reason": stop_reason,
            "stop_conditions_triggered": stop_conditions_triggered,
            "loop_summary": {
                "trusted_mode": trusted_mode,
                "allow_fix": allow_fix,
                "allow_commit": allow_commit,
                "stop_on_acceptance_failure": stop_on_acceptance_failure,
                "stop_on_scope_violation": stop_on_scope_violation,
                "stop_on_diff_too_large": stop_on_diff_too_large,
                "max_total_diff_chars": max_total_diff_chars,
            },
            "iteration_results": iteration_results,
            "changed_files": all_changed_files,
            "total_changed_files": len(all_changed_files),
            "diff_summary": "" if not include_diff_summary else "\n".join([str(it.get("classification", "")) for it in iteration_results])[:4000],
            "total_diff_chars": total_diff_chars,
            "latest_report_id": latest_report_id,
            "report_summary": latest_report_summary,
            "classification": final_classification,
            "next_actions": next_actions,
            "blockers": list(dict.fromkeys(blockers)),
            "warnings": list(dict.fromkeys(warnings)),
            "workflow_id": None,
            "run_id": run_id,
            "trusted_mode": trusted_mode,
            "allow_fix": allow_fix,
            "allow_commit": allow_commit,
            "workflow_steps": workflow_steps,
            "execution_mode": "run",
            "preview_claimed_at": preview_claimed_at,
            "preview_claim_status": preview_claim_status,
        }

    def _reconcile_orphaned_claims_preview(self, params: dict[str, Any]) -> dict[str, Any]:
        running_claims = self._claims.list_claims(status="RUNNING")
        candidates: list[dict[str, Any]] = []
        for claim in running_claims:
            orphan = self._claims.evaluate_orphaned_claim(claim)
            if not orphan.get("orphaned"):
                continue
            candidates.append({
                "preview_id": str(claim.get("preview_id") or ""),
                "run_id": str(claim.get("run_id") or ""),
                "current_version": str(claim.get("current_version") or ""),
                "provider": str(claim.get("provider") or ""),
                "last_heartbeat_at": str(claim.get("last_heartbeat_at") or ""),
                "heartbeat_timeout_seconds": int(claim.get("heartbeat_timeout_seconds") or 0),
                "claimed_at": str(claim.get("claimed_at") or ""),
                "error_code": str(orphan.get("error_code") or ""),
                "message": str(orphan.get("message") or ""),
            })
        if not candidates:
            return {
                "ok": True,
                "action": "reconcile_orphaned_claims_preview",
                "status": "ok",
                "candidates": [],
                "message": "没有失联的执行器运行记录需要处理。",
            }
        preview_id = self._generate_preview_key(prefix="reconcile_orphaned")
        artifact = {
            "preview_id": preview_id,
            "artifact_kind": "reconcile_orphaned_claims",
            "created_at": self._now_iso(),
            "expires_at": self._now_iso_ts(PREVIEW_TTL_SECONDS),
            "project_root": self.project_root,
            "action": "reconcile_orphaned_claims",
            "candidates": candidates,
        }
        self._write_preview_artifact(preview_id, artifact)
        return {
            "ok": True,
            "action": "reconcile_orphaned_claims_preview",
            "status": "preview_ready",
            "preview_id": preview_id,
            "candidate_count": len(candidates),
            "candidates": candidates,
            "message": f"发现 {len(candidates)} 个失联执行器运行记录。",
        }

    def _reconcile_orphaned_claims_apply(self, params: dict[str, Any]) -> dict[str, Any]:
        preview_id = self._str_param(params.get("preview_id"), default="")
        if not preview_id:
            return self._error("reconcile_orphaned_claims_apply", "PREVIEW_ID_REQUIRED", "reconcile_orphaned_claims_apply 需要 preview_id。")
        artifact = self._read_preview_artifact(preview_id)
        if artifact is None:
            return self._error("reconcile_orphaned_claims_apply", "PREVIEW_NOT_FOUND", "preview_id 不存在或已过期。")
        if str(artifact.get("artifact_kind") or "") != "reconcile_orphaned_claims":
            return self._error("reconcile_orphaned_claims_apply", "PREVIEW_KIND_MISMATCH", "preview_id 类型不匹配。")
        guard_error = self._preview_guard_error(
            "reconcile_orphaned_claims_apply",
            preview_id,
            artifact,
            expired_message="preview_id 已过期，请重新执行 reconcile_orphaned_claims_preview。",
        )
        if guard_error is not None:
            return guard_error

        candidates = artifact.get("candidates")
        if not isinstance(candidates, list):
            return self._error("reconcile_orphaned_claims_apply", "INVALID_PREVIEW", "preview 数据格式无效。")

        applied: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        for candidate in candidates:
            c_preview_id = str(candidate.get("preview_id") or "")
            c_run_id = str(candidate.get("run_id") or "")
            c_heartbeat = str(candidate.get("last_heartbeat_at") or "")
            if not c_preview_id:
                skipped.append({"preview_id": c_preview_id, "run_id": c_run_id, "reason": "missing preview_id"})
                continue
            claim = self._claims.read_claim(c_preview_id)
            if not isinstance(claim, dict):
                skipped.append({"preview_id": c_preview_id, "run_id": c_run_id, "reason": "claim_not_found"})
                continue
            if str(claim.get("status") or "") != "RUNNING":
                skipped.append({"preview_id": c_preview_id, "run_id": str(claim.get("run_id") or ""), "reason": "status_changed", "current_status": str(claim.get("status") or "")})
                continue
            if c_run_id and str(claim.get("run_id") or "") != c_run_id:
                skipped.append({"preview_id": c_preview_id, "run_id": str(claim.get("run_id") or ""), "reason": "run_id_changed"})
                continue
            orphan = self._claims.evaluate_orphaned_claim(claim)
            if not orphan.get("orphaned"):
                skipped.append({"preview_id": c_preview_id, "run_id": str(claim.get("run_id") or ""), "reason": "heartbeat_refreshed"})
                continue
            self._claims.finalize_claim(
                preview_id=c_preview_id,
                run_id=c_run_id,
                final_status="FAILED",
                error_code="ORPHANED_CLAIM_RECONCILED",
                message="Claim 被显式 reconcile 操作判定为失联，已终止。",
            )
            applied.append({"preview_id": c_preview_id, "run_id": c_run_id})

        final_status = "ok" if applied or not candidates else "skipped"
        return {
            "ok": True,
            "action": "reconcile_orphaned_claims_apply",
            "status": "succeeded",
            "final_status": final_status,
            "risk_level": "commit",
            "preview_id": preview_id,
            "applied_count": len(applied),
            "skipped_count": len(skipped),
            "candidates": candidates,
            "applied": applied,
            "skipped": skipped,
            "message": f"已终结 {len(applied)} 个失联执行器运行，跳过 {len(skipped)} 个。" if applied else "没有需要终结的失联执行器运行。",
        }

    def _status(self, params: dict[str, Any]) -> dict[str, Any]:
        preview_id = self._str_param(params.get("preview_id"), default="")
        run_id = self._str_param(params.get("run_id"), default="")
        poll_attempt_raw = params.get("poll_attempt", 1)
        poll_attempt = bounded_int(poll_attempt_raw, default=1, minimum=1, maximum=9_223_372_036_854_775_807)
        result = status_base_result(poll_attempt)

        store = ExecutorSessionStore(self.project_root)
        session_status = store.get_status()
        result["session_status"] = session_status

        if preview_id:
            claim = self._read_preview_claim_record(preview_id)
            result["preview_id"] = preview_id
            self._apply_preview_artifact_context(result, preview_id)
            if isinstance(claim, dict):
                self._apply_claim_to_status(result, claim)
            else:
                result["executor_run_status"] = "unknown"
                result["terminal"] = False
        elif run_id:
            result["run_id"] = run_id
            claim = self._find_claim_by_run_id(run_id)
            if isinstance(claim, dict):
                self._apply_claim_to_status(result, claim)
                claim_preview_id = str(claim.get("preview_id") or "")
                if claim_preview_id:
                    self._apply_preview_artifact_context(result, claim_preview_id)
            else:
                result["executor_run_status"] = "unknown"
                result["terminal"] = False

        return result

    def _apply_preview_artifact_context(self, result: dict[str, Any], preview_id: str) -> None:
        artifact = self._read_preview_artifact(preview_id)
        if not isinstance(artifact, dict):
            return
        archive_files = artifact.get("ignored_runner_archive_files")
        if isinstance(archive_files, list):
            result["ignored_runner_archive_files"] = [str(item) for item in archive_files if isinstance(item, str)]

    def _apply_claim_to_status(self, result: dict[str, Any], claim: dict[str, Any]) -> None:
        orphan_info = self._evaluate_orphaned_claim(claim)
        possible_report_id = self._resolve_possible_report_id(claim) if orphan_info.get("orphaned") else ""
        run_id = str(claim.get("run_id") or "")
        events = read_executor_events_for_status(self.project_root, run_id, limit=50)
        apply_claim_to_status(result, claim, orphan_info, possible_report_id=possible_report_id, events=events)

    def _find_claim_by_run_id(self, run_id: str) -> dict[str, Any] | None:
        return self._claims.find_claim_by_run_id(run_id)

    def _refresh_audit_package(self, params: dict[str, Any]) -> dict[str, Any]:
        version = self._str_param(params.get("version"), default="")
        reason = self._str_param(params.get("reason"), default="")
        if not version:
            return self._error("refresh_audit_package", "VERSION_REQUIRED", "version 不能为空。")
        store = ExecutorRunReportStore(self.project_root)
        try:
            result = store.refresh_version_audit_package(version=version, reason=reason)
        except ValueError:
            return self._error("refresh_audit_package", "INVALID_VERSION", "version 格式无效。")
        except Exception:
            return self._error("refresh_audit_package", "REFRESH_FAILED", "刷新 version 审计包失败。")
        if not result.get("ok"):
            code = str(result.get("error_code") or "REFRESH_FAILED")
            if code == "REPORT_NOT_FOUND":
                return self._error("refresh_audit_package", "REPORT_NOT_FOUND", "未找到该版本 report。")
            return self._error("refresh_audit_package", code, "刷新 version 审计包失败。")
        listing = store.list_version_audit_packages(version)
        return {
            "ok": True,
            "action": "refresh_audit_package",
            "status": "succeeded",
            "risk_level": "commit",
            "version": version,
            "audit_package_id": result.get("audit_package_id", ""),
            "json_file": result.get("json_file", ""),
            "source": "version_refresh",
            "base_package_file": listing.get("base_package_file", "") if isinstance(listing, dict) else "",
            "refresh_package_files": listing.get("refresh_package_files", []) if isinstance(listing, dict) else [],
            "latest_package_file": listing.get("latest_package_file", "") if isinstance(listing, dict) else "",
        }

    def _recheck_report_preview(self, params: dict[str, Any]) -> dict[str, Any]:
        version = self._str_param(params.get("version"), default="")
        report_id = self._str_param(params.get("report_id"), default="")
        context = self._load_recheck_plan_state_context(version)
        if not context.get("ok"):
            return {
                "ok": False,
                "action": "recheck_report_preview",
                "status": "failed",
                "risk_level": "preview",
                "error_code": str(context.get("error_code") or "PLAN_OR_STATE_LOAD_FAILED"),
                "message": str(context.get("message") or "加载 plan/state 失败。"),
                "blockers": self._str_list(context.get("blockers")),
                "warnings": self._str_list(context.get("warnings")),
            }

        target_version = str(context.get("target_version") or "")
        state = context["state"]
        target_runtime = context["target_runtime"]
        target_plan_version = context["target_plan_version"]
        old_runner_status = str(getattr(state, "status", "") or "")
        old_version_status = str(getattr(target_runtime, "status", "") or "")
        current_state_version = str(getattr(state, "current_version", "") or "")

        store = ExecutorRunReportStore(self.project_root)
        try:
            report_ret = store.get_report(
                version=target_version,
                report_id=report_id or None,
                latest=not bool(report_id),
                include_markdown=False,
            )
        except ValueError:
            return {
                "ok": False,
                "action": "recheck_report_preview",
                "status": "failed",
                "risk_level": "preview",
                "error_code": "INVALID_REPORT_QUERY",
                "message": "report_id 或 version 参数格式无效。",
                "blockers": ["INVALID_REPORT_QUERY"],
                "warnings": [],
            }
        except Exception:
            return {
                "ok": False,
                "action": "recheck_report_preview",
                "status": "failed",
                "risk_level": "preview",
                "error_code": "REPORT_LOAD_FAILED",
                "message": "读取目标 report 失败。",
                "blockers": ["REPORT_LOAD_FAILED"],
                "warnings": [],
            }

        if not report_ret.get("ok") or not isinstance(report_ret.get("report"), dict):
            return {
                "ok": False,
                "action": "recheck_report_preview",
                "status": "failed",
                "risk_level": "preview",
                "error_code": str(report_ret.get("error_code") or "REPORT_NOT_FOUND"),
                "message": "未找到目标 report。",
                "blockers": ["REPORT_NOT_FOUND"],
                "warnings": [],
            }

        report = report_ret["report"]
        resolved_report_id = self._str_param(report.get("report_id"), default="")
        report_version = self._str_param(report.get("version"), default="")
        old_report_status = self._str_param(report.get("status"), default="")
        old_scope_result = self._extract_scope_from_report(report)

        blockers: list[dict[str, str]] = []
        warnings: list[str] = []

        if report_version != target_version:
            blockers.append({
                "code": "REPORT_VERSION_MISMATCH",
                "message": f"report.version={report_version} 与目标 version={target_version} 不一致。",
            })
        if current_state_version and current_state_version != target_version:
            blockers.append({
                "code": "CURRENT_VERSION_MISMATCH",
                "message": f"state.current_version={current_state_version} 与目标 version={target_version} 不一致。",
            })

        current_head = self._str_param(self._service._get_git_head(), default="")
        report_head_after = self._str_param(report.get("commit_head_after"), default="")
        if report_head_after and current_head and report_head_after != current_head:
            blockers.append({
                "code": "HEAD_MISMATCH",
                "message": f"当前 HEAD={current_head} 与 report HEAD={report_head_after} 不一致。",
            })
        elif not report_head_after:
            warnings.append("REPORT_HEAD_MISSING")

        changed_files_eval = self._collect_recheck_changed_files(report)
        new_scope_result = self._evaluate_recheck_scope(
            version_spec=target_plan_version,
            changed_files=changed_files_eval.get("files", []),
            source=str(changed_files_eval.get("source") or "unknown"),
        )
        if not changed_files_eval.get("has_trustable_source"):
            blockers.append({
                "code": "CHANGED_FILES_SOURCE_UNAVAILABLE",
                "message": "无法从当前 Git diff 或 report.changed_files 获取可用 changed_files。",
            })
        elif str(changed_files_eval.get("source")) == "report_changed_files":
            warnings.append("USING_REPORT_CHANGED_FILES_FALLBACK")

        if new_scope_result.get("blocked"):
            blockers.append({
                "code": "NEW_SCOPE_CHECK_BLOCKED",
                "message": "基于当前规则重算后 scope check 仍未通过。",
            })

        if not self._is_state_recheck_candidate(old_runner_status, old_version_status):
            blockers.append({
                "code": "STATE_NOT_BLOCKED",
                "message": f"当前状态 runner={old_runner_status} version={old_version_status}，无需执行状态刷新。",
            })

        proposed_state_update = {
            "version": target_version,
            "runner_status_from": old_runner_status,
            "runner_status_to": "VERSION_PASSED",
            "version_status_from": old_version_status,
            "version_status_to": "PASSED",
            "state_file": str(context.get("state_file") or ""),
            "apply_note": "基于 recheck_report_apply 的受控重审刷新。",
            "report_id": resolved_report_id,
            "report_head_after": report_head_after,
            "current_head": current_head,
        }
        can_refresh_state = len(blockers) == 0
        preview_id = ""
        expires_at = ""
        if can_refresh_state:
            preview_id = self._generate_preview_key(prefix="recheck_report")
            expires_at = self._now_iso_ts(PREVIEW_TTL_SECONDS)
            artifact = recheck_report_preview_artifact(
                preview_id=preview_id,
                project_root=self.project_root,
                target_version=target_version,
                report_id=resolved_report_id,
                old_runner_status=old_runner_status,
                old_version_status=old_version_status,
                current_head=current_head,
                report_head_after=report_head_after,
                proposed_state_update=proposed_state_update,
                old_scope_result=old_scope_result,
                new_scope_result=new_scope_result,
                created_at=self._now_iso(),
                expires_at=expires_at,
            )
            self._write_preview_artifact(preview_id, artifact)

        payload: dict[str, Any] = {
            "ok": True,
            "action": "recheck_report_preview",
            "status": "preview_ready" if can_refresh_state else "blocked",
            "risk_level": "preview",
            "target_version": target_version,
            "report_id": resolved_report_id,
            "old_report_status": old_report_status,
            "old_runner_status": old_runner_status,
            "old_version_status": old_version_status,
            "old_scope_result": old_scope_result,
            "new_scope_result": new_scope_result,
            "can_refresh_state": can_refresh_state,
            "proposed_state_update": proposed_state_update,
            "blockers": blockers,
            "warnings": warnings,
            "facts_source": {
                "changed_files_source": changed_files_eval.get("source"),
                "changed_files_count": len(changed_files_eval.get("files", [])),
                "report_json_file": self._str_param(report.get("json_file"), default=""),
                "report_markdown_file": self._str_param(report.get("markdown_file"), default=""),
                "current_head": current_head,
                "report_head_after": report_head_after,
            },
        }
        if can_refresh_state:
            payload["preview_id"] = preview_id
            payload["expires_at"] = expires_at
            payload["why_safe_to_refresh"] = "重算 scope check 通过，且 report/version/HEAD 与当前状态一致。"
        else:
            payload["why_blocked"] = "当前重审结果存在阻断项，apply 不可用。"
        return payload

    def _manual_validation_preview(self, params: dict[str, Any]) -> dict[str, Any]:
        version = self._str_param(params.get("version"), default="")
        validation_run_id = self._str_param(params.get("validation_run_id"), default="")
        reason = self._str_param(params.get("reason"), default="")
        if not validation_run_id:
            return self._error("manual_validation_preview", "VALIDATION_RUN_ID_REQUIRED", "manual_validation_preview 需要 validation_run_id。")
        context = self._load_recheck_plan_state_context(version)
        if not context.get("ok"):
            return {
                "ok": False,
                "action": "manual_validation_preview",
                "status": "failed",
                "risk_level": "preview",
                "error_code": str(context.get("error_code") or "PLAN_OR_STATE_LOAD_FAILED"),
                "message": str(context.get("message") or "加载 plan/state 失败。"),
                "blockers": self._str_list(context.get("blockers")),
                "warnings": self._str_list(context.get("warnings")),
            }

        target_version = str(context.get("target_version") or "")
        state = context["state"]
        target_runtime = context["target_runtime"]
        old_runner_status = self._str_param(getattr(state, "status", None), default="")
        old_version_status = self._str_param(getattr(target_runtime, "status", None), default="")
        current_state_version = self._str_param(getattr(state, "current_version", None), default="")
        current_head = self._str_param(self._service._get_git_head(), default="")

        validation_record = self._load_validation_run_record(validation_run_id)
        blockers: list[dict[str, str]] = []
        warnings: list[str] = []
        if not validation_record.get("ok"):
            blockers.append({
                "code": str(validation_record.get("error_code") or "VALIDATION_RUN_LOAD_FAILED"),
                "message": str(validation_record.get("message") or "读取 validation run 失败。"),
            })
            validation_data: dict[str, Any] = {}
        else:
            validation_data = validation_record.get("record") if isinstance(validation_record.get("record"), dict) else {}

        if current_state_version and current_state_version != target_version:
            blockers.append({
                "code": "CURRENT_VERSION_MISMATCH",
                "message": f"state.current_version={current_state_version} 与目标 version={target_version} 不一致。",
            })
        allowed_state_pairs = {
            ("BLOCKED_BY_ACCEPTANCE_FAILURE", "FAILED_BLOCKED"),
            ("FIX_PROMPT_READY", "FIX_PROMPT_READY"),
        }
        if (old_runner_status, old_version_status) not in allowed_state_pairs:
            blockers.append({
                "code": "STATE_NOT_ACCEPTANCE_BLOCKED",
                "message": f"当前状态 runner={old_runner_status} version={old_version_status}，不适用手动验收通过登记。",
            })

        git_status = self._service._get_git_status_short()
        if git_status.strip():
            blockers.append({
                "code": "WORKTREE_NOT_CLEAN",
                "message": "手动验收通过登记要求工作区干净，避免把未提交改动登记为已通过。",
            })

        validation_passed = bool(validation_data.get("passed") is True and validation_data.get("status") == "passed")
        if validation_data and not validation_passed:
            blockers.append({
                "code": "VALIDATION_RUN_NOT_PASSED",
                "message": f"validation_run_id={validation_run_id} 未通过，不能登记版本通过。",
            })

        command_results = validation_data.get("command_results") if isinstance(validation_data.get("command_results"), list) else []
        commands = [self._str_param(item.get("command"), default="") for item in command_results if isinstance(item, dict)]
        failed_commands = [cmd for cmd, item in zip(commands, command_results) if isinstance(item, dict) and not bool(item.get("ok"))]
        if validation_data and (not command_results or failed_commands):
            blockers.append({
                "code": "VALIDATION_COMMAND_RESULTS_INVALID",
                "message": "validation run 缺少有效 command_results 或存在失败命令。",
            })

        proposed_state_update = {
            "version": target_version,
            "runner_status_from": old_runner_status,
            "runner_status_to": "VERSION_PASSED",
            "version_status_from": old_version_status,
            "version_status_to": "PASSED",
            "state_file": str(context.get("state_file") or ""),
            "apply_note": "基于 manual_validation_apply 的手动/等价验收通过登记。",
            "validation_run_id": validation_run_id,
            "current_head": current_head,
        }
        can_apply = len(blockers) == 0
        preview_id = ""
        expires_at = ""
        if can_apply:
            preview_id = self._generate_preview_key(prefix="manual_validation")
            expires_at = self._now_iso_ts(PREVIEW_TTL_SECONDS)
            artifact = {
                "preview_id": preview_id,
                "artifact_kind": "manual_validation_state_refresh",
                "project_root": self.project_root,
                "target_version": target_version,
                "validation_run_id": validation_run_id,
                "old_runner_status": old_runner_status,
                "old_version_status": old_version_status,
                "current_head": current_head,
                "commands": commands,
                "validation_completed_at": self._str_param(validation_data.get("completed_at"), default=""),
                "reason": reason,
                "can_refresh_state": True,
                "proposed_state_update": proposed_state_update,
                "created_at": self._now_iso(),
                "expires_at": expires_at,
            }
            self._write_preview_artifact(preview_id, artifact)

        payload: dict[str, Any] = {
            "ok": True,
            "action": "manual_validation_preview",
            "status": "preview_ready" if can_apply else "blocked",
            "risk_level": "preview",
            "target_version": target_version,
            "validation_run_id": validation_run_id,
            "old_runner_status": old_runner_status,
            "old_version_status": old_version_status,
            "validation_status": self._str_param(validation_data.get("status"), default="") if isinstance(validation_data, dict) else "",
            "validation_passed": validation_passed,
            "commands": commands,
            "can_refresh_state": can_apply,
            "proposed_state_update": proposed_state_update,
            "blockers": blockers,
            "warnings": warnings,
            "facts_source": {
                "validation_run_file": self._validation_run_record_path(validation_run_id),
                "current_head": current_head,
                "git_status_short": git_status,
            },
        }
        if can_apply:
            payload["preview_id"] = preview_id
            payload["expires_at"] = expires_at
            payload["why_safe_to_refresh"] = "validation run 已通过、工作区干净，且 state 仍处于验收失败或修复待确认状态。"
        else:
            payload["why_blocked"] = "当前手动验收登记存在阻断项，apply 不可用。"
        return payload

    def _state_lineage_reconciliation_preview(self, params: dict[str, Any]) -> dict[str, Any]:
        context = self._load_state_lineage_context()
        if not context.get("ok"):
            return {
                "ok": False,
                "action": "state_lineage_reconciliation_preview",
                "status": "failed",
                "risk_level": "blocked",
                "error_code": str(context.get("error_code") or "PLAN_OR_STATE_LOAD_FAILED"),
                "message": str(context.get("message") or "加载 plan/state 失败。"),
                "blockers": self._str_list(context.get("blockers")),
                "warnings": self._str_list(context.get("warnings")),
            }

        bindings = params.get("bindings") if isinstance(params.get("bindings"), list) else []
        commit_facts = self._state_lineage_commit_facts(bindings)
        current_head = self._str_param(self._service._get_git_head(), default="")
        current_branch = self._str_param(self._service._get_git_branch(), default="")
        git_status_short = self._service._get_git_status_short()
        preview_result = build_state_lineage_reconciliation_preview(
            plan=context["plan"],
            state=context["state"],
            bindings=bindings,
            expected_head=self._str_param(params.get("expected_head"), default=""),
            current_head=current_head,
            git_status_short=git_status_short,
            target_next_version=self._str_param(params.get("target_next_version"), default=""),
            now=self._now_iso(),
            state_file=str(context.get("state_file") or ""),
            project_root=self.project_root,
            expected_branch=self._str_param(params.get("expected_branch"), default=""),
            current_branch=current_branch,
            commit_exists=commit_facts["exists"],
            commit_subjects=commit_facts["subjects"],
        )
        response = dict(preview_result)
        response.pop("proposed_state", None)
        if preview_result.get("can_apply"):
            preview_id = self._generate_preview_key(prefix="state_lineage")
            expires_at = self._now_iso_ts(PREVIEW_TTL_SECONDS)
            artifact = dict(preview_result)
            artifact["preview_id"] = preview_id
            artifact["expires_at"] = expires_at
            self._write_preview_artifact(preview_id, artifact)
            response["preview_id"] = preview_id
            response["expires_at"] = expires_at
            response["next_actions"] = [{
                "tool": "manage_executor_workflow",
                "action": "state_lineage_reconciliation_apply",
                "params": {"action": "state_lineage_reconciliation_apply", "preview_id": preview_id},
                "reason": "使用 preview_id 受控写入 Runner state lineage 对账结果。",
                "requires_confirmation": True,
                "risk_level": "commit",
            }]
        else:
            response["why_blocked"] = "state lineage reconciliation preview 存在阻断项，apply 不可用。"
        return response

    def _state_lineage_reconciliation_apply(self, params: dict[str, Any]) -> dict[str, Any]:
        preview_id = self._str_param(params.get("preview_id"), default="")
        if not preview_id:
            return self._error("state_lineage_reconciliation_apply", "PREVIEW_ID_REQUIRED", "state_lineage_reconciliation_apply 需要 preview_id。")
        artifact = self._read_preview_artifact(preview_id)
        if artifact is None:
            return self._error("state_lineage_reconciliation_apply", "PREVIEW_NOT_FOUND", "preview_id 不存在或已过期。")
        if str(artifact.get("artifact_kind") or "") != STATE_LINEAGE_ARTIFACT_KIND:
            return self._error("state_lineage_reconciliation_apply", "PREVIEW_KIND_MISMATCH", "preview_id 类型不匹配。")
        guard_error = self._preview_guard_error(
            "state_lineage_reconciliation_apply",
            preview_id,
            artifact,
            expired_message="preview_id 已过期，请重新生成 preview。",
        )
        if guard_error is not None:
            return guard_error

        context = self._load_state_lineage_context()
        if not context.get("ok"):
            return self._error(
                "state_lineage_reconciliation_apply",
                str(context.get("error_code") or "PLAN_OR_STATE_LOAD_FAILED"),
                str(context.get("message") or "加载 plan/state 失败。"),
            )
        bindings = artifact.get("bindings") if isinstance(artifact.get("bindings"), list) else []
        commit_facts = self._state_lineage_commit_facts(bindings)
        apply_result = apply_state_lineage_reconciliation_artifact(
            artifact=artifact,
            current_state=context["state"],
            preview_id=preview_id,
            current_head=self._str_param(self._service._get_git_head(), default=""),
            git_status_short=self._service._get_git_status_short(),
            current_branch=self._str_param(self._service._get_git_branch(), default=""),
            commit_exists=commit_facts["exists"],
            commit_subjects=commit_facts["subjects"],
        )
        if not apply_result.get("ok"):
            return apply_result
        try:
            StateMutationGateway().save_raw(
                apply_result["updated_state"],
                str(context.get("state_file") or ""),
                expected_hash=self._str_param(artifact.get("state_hash"), default=""),
            )
        except Exception:
            return self._error("state_lineage_reconciliation_apply", "STATE_SAVE_FAILED", "写入 state 失败。")
        self._delete_preview_artifact(preview_id)
        return {
            "ok": True,
            "action": "state_lineage_reconciliation_apply",
            "status": "succeeded",
            "risk_level": "commit",
            "preview_id": preview_id,
            "state_file": str(context.get("state_file") or ""),
            "before_state_summary": apply_result.get("before_state_summary", {}),
            "after_state_summary": apply_result.get("after_state_summary", {}),
            "versions_updated": apply_result.get("versions_updated", []),
            "files_touched": [
                str(item).replace("<preview_id>", preview_id)
                for item in apply_result.get("files_touched", [])
            ],
            "forbidden_side_effects": apply_result.get("forbidden_side_effects", []),
            "message": "Runner state lineage reconciliation 已受控写入 state.json；未运行 executor、未执行 Git 远端操作。",
        }

    def _final_version_closeout_preview(self, params: dict[str, Any]) -> dict[str, Any]:
        context = self._load_state_lineage_context()
        if not context.get("ok"):
            return {
                "ok": False,
                "action": "final_version_closeout_preview",
                "status": "failed",
                "risk_level": "blocked",
                "error_code": str(context.get("error_code") or "PLAN_OR_STATE_LOAD_FAILED"),
                "message": str(context.get("message") or "加载 plan/state 失败。"),
                "blockers": self._str_list(context.get("blockers")),
                "warnings": self._str_list(context.get("warnings")),
            }

        accepted_commit = self._str_param(params.get("accepted_commit") or params.get("commit_hash"), default="")
        commit_fact = self._final_version_commit_fact(accepted_commit)
        current_head = self._str_param(self._service._get_git_head(), default="")
        current_branch = self._str_param(self._service._get_git_branch(), default="")
        git_status_short = self._service._get_git_status_short()
        preview_result = build_final_version_closeout_preview(
            plan=context["plan"],
            state=context["state"],
            target_version=self._str_param(params.get("target_version") or params.get("version"), default=""),
            accepted_commit=accepted_commit,
            accepted_commit_subject=self._str_param(
                params.get("accepted_commit_subject")
                or params.get("commit_subject")
                or params.get("commit_message"),
                default="",
            ),
            expected_head=self._str_param(params.get("expected_head"), default=""),
            current_head=current_head,
            git_status_short=git_status_short,
            now=self._now_iso(),
            state_file=str(context.get("state_file") or ""),
            project_root=self.project_root,
            expected_branch=self._str_param(params.get("expected_branch"), default=""),
            current_branch=current_branch,
            commit_exists=bool(commit_fact.get("exists")),
            commit_subject=self._str_param(commit_fact.get("subject"), default=""),
            commit_files=self._str_list(params.get("commit_files")),
            evidence_refs=self._str_list(params.get("evidence_refs")),
            evidence_summary=self._str_param(params.get("evidence_summary"), default=""),
            reason=self._str_param(params.get("reason"), default=""),
        )
        response = dict(preview_result)
        response.pop("proposed_state", None)
        if preview_result.get("can_apply"):
            preview_id = self._generate_preview_key(prefix="final_closeout")
            expires_at = self._now_iso_ts(PREVIEW_TTL_SECONDS)
            artifact = dict(preview_result)
            artifact["preview_id"] = preview_id
            artifact["expires_at"] = expires_at
            self._write_preview_artifact(preview_id, artifact)
            response["preview_id"] = preview_id
            response["expires_at"] = expires_at
            response["next_actions"] = [{
                "tool": "manage_executor_workflow",
                "action": "final_version_closeout_apply",
                "params": {"action": "final_version_closeout_apply", "preview_id": preview_id},
                "reason": "使用 preview_id 受控写入最后一个版本 closeout 结果。",
                "requires_confirmation": True,
                "risk_level": "commit",
            }]
        else:
            response["why_blocked"] = "final version closeout preview 存在阻断项，apply 不可用。"
        return response

    def _final_version_closeout_apply(self, params: dict[str, Any]) -> dict[str, Any]:
        preview_id = self._str_param(params.get("preview_id"), default="")
        if not preview_id:
            return self._error("final_version_closeout_apply", "PREVIEW_ID_REQUIRED", "final_version_closeout_apply 需要 preview_id。")
        artifact = self._read_preview_artifact(preview_id)
        if artifact is None:
            return self._error("final_version_closeout_apply", "PREVIEW_NOT_FOUND", "preview_id 不存在或已过期。")
        if str(artifact.get("artifact_kind") or "") != FINAL_VERSION_CLOSEOUT_ARTIFACT_KIND:
            return self._error("final_version_closeout_apply", "PREVIEW_KIND_MISMATCH", "preview_id 类型不匹配。")
        guard_error = self._preview_guard_error(
            "final_version_closeout_apply",
            preview_id,
            artifact,
            expired_message="preview_id 已过期，请重新生成 preview。",
        )
        if guard_error is not None:
            return guard_error

        context = self._load_state_lineage_context()
        if not context.get("ok"):
            return self._error(
                "final_version_closeout_apply",
                str(context.get("error_code") or "PLAN_OR_STATE_LOAD_FAILED"),
                str(context.get("message") or "加载 plan/state 失败。"),
            )
        commit_fact = self._final_version_commit_fact(self._str_param(artifact.get("accepted_commit"), default=""))
        apply_result = apply_final_version_closeout_artifact(
            artifact=artifact,
            current_state=context["state"],
            preview_id=preview_id,
            current_head=self._str_param(self._service._get_git_head(), default=""),
            git_status_short=self._service._get_git_status_short(),
            current_branch=self._str_param(self._service._get_git_branch(), default=""),
            commit_exists=bool(commit_fact.get("exists")),
            commit_subject=self._str_param(commit_fact.get("subject"), default=""),
        )
        if not apply_result.get("ok"):
            return apply_result
        try:
            StateMutationGateway().save_raw(
                apply_result["updated_state"],
                str(context.get("state_file") or ""),
                expected_hash=self._str_param(artifact.get("state_hash"), default=""),
            )
        except Exception:
            return self._error("final_version_closeout_apply", "STATE_SAVE_FAILED", "写入 state 失败。")
        self._delete_preview_artifact(preview_id)
        return {
            "ok": True,
            "action": "final_version_closeout_apply",
            "status": "succeeded",
            "risk_level": "commit",
            "preview_id": preview_id,
            "state_file": str(context.get("state_file") or ""),
            "before_state_summary": apply_result.get("before_state_summary", {}),
            "after_state_summary": apply_result.get("after_state_summary", {}),
            "versions_updated": apply_result.get("versions_updated", []),
            "files_touched": [
                str(item).replace("<preview_id>", preview_id)
                for item in apply_result.get("files_touched", [])
            ],
            "forbidden_side_effects": apply_result.get("forbidden_side_effects", []),
            "message": "最后一个版本 closeout 已受控写入 state.json；未运行 executor、未写 ReviewDecision/GateEvent/Delivery accepted、未执行 Git 远端操作。",
        }

    def _manual_validation_apply(self, params: dict[str, Any]) -> dict[str, Any]:
        preview_id = self._str_param(params.get("preview_id"), default="")
        if not preview_id:
            return self._error("manual_validation_apply", "PREVIEW_ID_REQUIRED", "manual_validation_apply 需要 preview_id。")
        artifact = self._read_preview_artifact(preview_id)
        if artifact is None:
            return self._error("manual_validation_apply", "PREVIEW_NOT_FOUND", "preview_id 不存在或已过期。")
        if str(artifact.get("artifact_kind") or "") != "manual_validation_state_refresh":
            return self._error("manual_validation_apply", "PREVIEW_KIND_MISMATCH", "preview_id 类型不匹配。")
        guard_error = self._preview_guard_error(
            "manual_validation_apply",
            preview_id,
            artifact,
            expired_message="preview_id 已过期，请重新生成 preview。",
        )
        if guard_error is not None:
            return guard_error
        if not bool(artifact.get("can_refresh_state")):
            return self._error("manual_validation_apply", "PREVIEW_BLOCKED", "该 preview 不可用于状态刷新。")

        target_version = self._str_param(artifact.get("target_version"), default="")
        context = self._load_recheck_plan_state_context(target_version)
        if not context.get("ok"):
            return self._error("manual_validation_apply", str(context.get("error_code") or "PLAN_OR_STATE_LOAD_FAILED"), str(context.get("message") or "加载 plan/state 失败。"))
        state = context["state"]
        target_runtime = context["target_runtime"]
        state_file = str(context.get("state_file") or "")
        old_runner_status = self._str_param(getattr(state, "status", None), default="")
        old_version_status = self._str_param(getattr(target_runtime, "status", None), default="")
        if old_runner_status != self._str_param(artifact.get("old_runner_status"), default="") or old_version_status != self._str_param(artifact.get("old_version_status"), default=""):
            return self._error("manual_validation_apply", "STATE_CHANGED_SINCE_PREVIEW", "state 在 preview 之后发生变化，已阻断 apply。")
        current_head = self._str_param(self._service._get_git_head(), default="")
        if current_head and self._str_param(artifact.get("current_head"), default="") and current_head != self._str_param(artifact.get("current_head"), default=""):
            return self._error("manual_validation_apply", "HEAD_CHANGED_SINCE_PREVIEW", "HEAD 在 preview 之后发生变化，已阻断 apply。")
        if self._service._get_git_status_short().strip():
            return self._error("manual_validation_apply", "WORKTREE_NOT_CLEAN", "工作区不干净，已阻断 apply。")

        proposed = artifact.get("proposed_state_update") if isinstance(artifact.get("proposed_state_update"), dict) else {}
        now_iso = self._now_iso()
        try:
            mutation_result = self._state_mutations.apply_manual_validation_pass(
                state=state,
                target_runtime=target_runtime,
                state_file=state_file,
                mutation=ManualValidationPassMutation(
                    version=target_version,
                    runner_status_to=self._str_param(proposed.get("runner_status_to"), default="VERSION_PASSED"),
                    version_status_to=self._str_param(proposed.get("version_status_to"), default="PASSED"),
                    validation_run_id=self._str_param(artifact.get("validation_run_id"), default=""),
                    commands=self._str_list(artifact.get("commands")),
                    current_head=current_head,
                    reason=self._str_param(artifact.get("reason"), default=""),
                    recorded_at=now_iso,
                ),
            )
        except Exception:
            return self._error("manual_validation_apply", "STATE_SAVE_FAILED", "写入 state 失败。")
        self._delete_preview_artifact(preview_id)
        return {
            "ok": True,
            "action": "manual_validation_apply",
            "status": "succeeded",
            "risk_level": "commit",
            "preview_id": preview_id,
            "target_version": target_version,
            "validation_run_id": self._str_param(artifact.get("validation_run_id"), default=""),
            "old_runner_status": old_runner_status,
            "new_runner_status": mutation_result.runner_status,
            "old_version_status": old_version_status,
            "new_version_status": mutation_result.version_status,
            "state_file": mutation_result.state_file,
            "message": "手动/等价验收通过已登记到 state。原始 executor report 未改写。",
        }

    def _scope_mismatch_preview(self, params: dict[str, Any]) -> dict[str, Any]:
        version = self._str_param(params.get("version"), default="")
        report_id = self._str_param(params.get("report_id"), default="")
        if not version:
            return {
                "ok": False,
                "action": "scope_mismatch_preview",
                "status": "failed",
                "risk_level": "preview",
                "error_code": "VERSION_REQUIRED",
                "message": "version 不能为空。",
                "blockers": ["VERSION_REQUIRED"],
                "warnings": [],
            }

        context = self._load_scope_mismatch_plan_context(version)
        if not context.get("ok"):
            return {
                "ok": False,
                "action": "scope_mismatch_preview",
                "status": "failed",
                "risk_level": "preview",
                "error_code": str(context.get("error_code") or "PLAN_LOAD_FAILED"),
                "message": str(context.get("message") or "读取 plan 失败。"),
                "blockers": self._str_list(context.get("blockers")),
                "warnings": self._str_list(context.get("warnings")),
            }

        target_version = str(context.get("target_version") or "")
        target_plan_version = context["target_plan_version"]
        store = ExecutorRunReportStore(self.project_root)
        try:
            report_ret = store.get_report(
                version=target_version,
                report_id=report_id or None,
                latest=not bool(report_id),
                include_markdown=False,
            )
        except ValueError:
            return {
                "ok": False,
                "action": "scope_mismatch_preview",
                "status": "failed",
                "risk_level": "preview",
                "error_code": "INVALID_REPORT_QUERY",
                "message": "report_id 或 version 参数格式无效。",
                "blockers": ["INVALID_REPORT_QUERY"],
                "warnings": [],
            }
        except Exception:
            return {
                "ok": False,
                "action": "scope_mismatch_preview",
                "status": "failed",
                "risk_level": "preview",
                "error_code": "REPORT_LOAD_FAILED",
                "message": "读取目标 report 失败。",
                "blockers": ["REPORT_LOAD_FAILED"],
                "warnings": [],
            }

        if not report_ret.get("ok") or not isinstance(report_ret.get("report"), dict):
            return {
                "ok": False,
                "action": "scope_mismatch_preview",
                "status": "failed",
                "risk_level": "preview",
                "error_code": str(report_ret.get("error_code") or "REPORT_NOT_FOUND"),
                "message": "未找到目标 report。",
                "blockers": ["REPORT_NOT_FOUND"],
                "warnings": [],
            }

        report = report_ret["report"]
        resolved_report_id = self._str_param(report.get("report_id"), default="")
        report_version = self._str_param(report.get("version"), default="")
        current_head = self._str_param(self._service._get_git_head(), default="")
        report_head_after = self._str_param(report.get("commit_head_after"), default="")

        changed_files_eval = self._collect_scope_mismatch_changed_files(report)
        scope_eval = self._evaluate_recheck_scope(
            version_spec=target_plan_version,
            changed_files=changed_files_eval.get("files", []),
            source=str(changed_files_eval.get("source") or "unknown"),
        )
        allowed_files = self._str_list(scope_eval.get("allowed_files"))
        forbidden_files = self._str_list(scope_eval.get("forbidden_files"))
        changed_files = self._str_list(scope_eval.get("scope_checked_files"))
        outside_allowed_files = self._str_list(scope_eval.get("changed_outside_allowed_files"))
        forbidden_files_hit = self._str_list(scope_eval.get("changed_forbidden_files"))
        inside_allowed_files = [path for path in changed_files if path not in outside_allowed_files]

        blockers: list[dict[str, str]] = []
        warnings: list[str] = []

        if report_version and report_version != target_version:
            blockers.append({
                "code": "REPORT_VERSION_MISMATCH",
                "message": f"report.version={report_version} 与目标 version={target_version} 不一致。",
            })

        head_match = bool(report_head_after and current_head and report_head_after == current_head)
        head_mismatch: dict[str, Any] | None = None
        if report_head_after and current_head and report_head_after != current_head:
            head_mismatch = {
                "code": "HEAD_MISMATCH",
                "current_head": current_head,
                "report_head_after": report_head_after,
                "message": "当前 HEAD 与报告记录 HEAD 不一致。",
            }
            warnings.append("HEAD_MISMATCH")
        elif not report_head_after:
            head_mismatch = {
                "code": "REPORT_HEAD_MISSING",
                "current_head": current_head,
                "report_head_after": report_head_after,
                "message": "报告缺少 commit_head_after，无法完成 HEAD 一致性比对。",
            }
            warnings.append("REPORT_HEAD_MISSING")
        elif not current_head:
            head_mismatch = {
                "code": "CURRENT_HEAD_MISSING",
                "current_head": current_head,
                "report_head_after": report_head_after,
                "message": "当前仓库无法读取 HEAD，无法完成 HEAD 一致性比对。",
            }
            warnings.append("CURRENT_HEAD_MISSING")

        if not changed_files_eval.get("has_trustable_source"):
            blockers.append({
                "code": "CHANGED_FILES_SOURCE_UNAVAILABLE",
                "message": "无法从当前 Git 改动或 report changed_files 获取可用 changed_files。",
            })
        elif str(changed_files_eval.get("source") or "") in {"report_summary_changed_files", "report_changed_files"}:
            warnings.append("USING_REPORT_CHANGED_FILES_FALLBACK")

        if forbidden_files_hit:
            blockers.append({
                "code": "FORBIDDEN_FILES_HIT",
                "message": "检测到 forbidden_files 命中，需强阻断处理。",
            })

        if outside_allowed_files and not forbidden_files_hit:
            warnings.append("SCOPE_MISMATCH_OUTSIDE_ALLOWED_FILES")

        if forbidden_files_hit:
            scope_status = "forbidden_violation"
            risk_level = "high"
        elif outside_allowed_files:
            scope_status = "scope_mismatch"
            risk_level = "preview"
        else:
            scope_status = "in_scope"
            risk_level = "info"

        resolution_options = self._build_scope_mismatch_resolution_options(
            scope_status=scope_status,
            has_outside=bool(outside_allowed_files),
            has_forbidden=bool(forbidden_files_hit),
        )
        if forbidden_files_hit:
            warnings.append("DIRECT_MANUAL_REVIEW_COMMIT_NOT_RECOMMENDED")

        can_apply = bool(not blockers and not forbidden_files_hit)
        preview_id = self._generate_preview_key(prefix="scope_mismatch_preview")
        expires_at = self._now_iso_ts(PREVIEW_TTL_SECONDS)
        preview_artifact = scope_mismatch_preview_artifact(
            preview_id=preview_id,
            project_root=self.project_root,
            target_version=target_version,
            report_id=resolved_report_id,
            report_version=report_version,
            scope_status=scope_status,
            risk_level=risk_level,
            allowed_files=allowed_files,
            forbidden_files=forbidden_files,
            changed_files=changed_files,
            inside_allowed_files=inside_allowed_files,
            outside_allowed_files=outside_allowed_files,
            forbidden_files_hit=forbidden_files_hit,
            resolution_options=resolution_options,
            changed_files_source=str(changed_files_eval.get("source") or "unknown"),
            head_match=head_match,
            head_mismatch=head_mismatch,
            warnings=warnings,
            blockers=blockers,
            current_head=current_head,
            report_head_after=report_head_after,
            can_apply=can_apply,
            old_runner_status="",
            old_version_status="",
            created_at=self._now_iso(),
            expires_at=expires_at,
        )
        context = self._load_recheck_plan_state_context(target_version)
        if context.get("ok"):
            state = context.get("state")
            target_runtime = context.get("target_runtime")
            preview_artifact["state_file"] = str(context.get("state_file") or "")
            preview_artifact["old_runner_status"] = self._str_param(getattr(state, "status", None), default="")
            preview_artifact["old_version_status"] = self._str_param(getattr(target_runtime, "status", None), default="")
        self._write_preview_artifact(preview_id, preview_artifact)

        return {
            "ok": True,
            "action": "scope_mismatch_preview",
            "status": "preview_ready",
            "risk_level": risk_level,
            "version": target_version,
            "report_id": resolved_report_id,
            "allowed_files": allowed_files,
            "forbidden_files": forbidden_files,
            "changed_files": changed_files,
            "inside_allowed_files": inside_allowed_files,
            "outside_allowed_files": outside_allowed_files,
            "forbidden_files_hit": forbidden_files_hit,
            "scope_status": scope_status,
            "changed_files_source": str(changed_files_eval.get("source") or "unknown"),
            "head_match": head_match,
            "head_mismatch": head_mismatch,
            "can_apply": can_apply,
            "preview_id": preview_id,
            "expires_at": expires_at,
            "resolution_options": resolution_options,
            "blockers": blockers,
            "warnings": warnings,
            "message": "返回 scope mismatch 事实、风险与受控处理选项。",
        }

    def _scope_mismatch_apply(self, params: dict[str, Any]) -> dict[str, Any]:
        preview_id = self._str_param(params.get("preview_id"), default="")
        resolution = self._str_param(params.get("resolution"), default="", lower=True)
        if not preview_id:
            return self._error("scope_mismatch_apply", "PREVIEW_ID_REQUIRED", "scope_mismatch_apply 需要 preview_id。")
        if not resolution:
            return self._error("scope_mismatch_apply", "RESOLUTION_REQUIRED", "scope_mismatch_apply 需要 resolution。")

        artifact = self._read_preview_artifact(preview_id)
        if artifact is None:
            return self._error("scope_mismatch_apply", "PREVIEW_NOT_FOUND", "preview_id 不存在或已过期。")
        if str(artifact.get("artifact_kind") or "") != "scope_mismatch_resolution":
            return self._error("scope_mismatch_apply", "PREVIEW_KIND_MISMATCH", "preview_id 类型不匹配。")
        guard_error = self._preview_guard_error(
            "scope_mismatch_apply",
            preview_id,
            artifact,
            expired_message="preview_id 已过期，请重新生成 preview。",
        )
        if guard_error is not None:
            return guard_error

        target_version = self._str_param(artifact.get("target_version"), default="")
        scope_status = self._str_param(artifact.get("scope_status"), default="")
        outside_allowed_files = self._str_list(artifact.get("outside_allowed_files"))
        forbidden_files_hit = self._str_list(artifact.get("forbidden_files_hit"))
        head_mismatch = artifact.get("head_mismatch") if isinstance(artifact.get("head_mismatch"), dict) else None
        can_apply = bool(artifact.get("can_apply"))

        if forbidden_files_hit:
            return {
                "ok": False,
                "action": "scope_mismatch_apply",
                "status": "blocked",
                "risk_level": "blocked",
                "error_code": "FORBIDDEN_FILES_HIT",
                "message": "检测到 forbidden_files 命中，scope_mismatch_apply 已阻断。",
                "preview_id": preview_id,
                "version": target_version,
                "resolution": resolution,
                "scope_status": scope_status,
                "forbidden_files_hit": forbidden_files_hit,
                "blockers": ["FORBIDDEN_FILES_HIT"],
                "warnings": self._scope_apply_head_warnings(head_mismatch),
            }
        if not can_apply:
            return self._error("scope_mismatch_apply", "PREVIEW_BLOCKED", "该 preview 当前不可 apply。")

        context = self._load_recheck_plan_state_context(target_version)
        if not context.get("ok"):
            return {
                "ok": False,
                "action": "scope_mismatch_apply",
                "status": "failed",
                "risk_level": "commit",
                "error_code": str(context.get("error_code") or "PLAN_OR_STATE_LOAD_FAILED"),
                "message": str(context.get("message") or "加载 plan/state 失败。"),
                "blockers": self._str_list(context.get("blockers")),
                "warnings": self._str_list(context.get("warnings")),
                "preview_id": preview_id,
                "version": target_version,
                "resolution": resolution,
            }

        state = context["state"]
        target_runtime = context["target_runtime"]
        state_file = str(context.get("state_file") or "")
        old_runner_status = self._str_param(getattr(state, "status", None), default="")
        old_version_status = self._str_param(getattr(target_runtime, "status", None), default="")
        expected_runner_status = self._str_param(artifact.get("old_runner_status"), default="")
        expected_version_status = self._str_param(artifact.get("old_version_status"), default="")
        if expected_runner_status and old_runner_status != expected_runner_status:
            return {
                "ok": False,
                "action": "scope_mismatch_apply",
                "status": "blocked",
                "risk_level": "blocked",
                "error_code": "STATE_CHANGED_SINCE_PREVIEW",
                "message": "state 在 preview 之后发生变化，已阻断 apply。",
                "preview_id": preview_id,
                "version": target_version,
                "resolution": resolution,
                "old_runner_status": old_runner_status,
                "old_version_status": old_version_status,
                "blockers": ["STATE_CHANGED_SINCE_PREVIEW"],
                "warnings": self._scope_apply_head_warnings(head_mismatch),
            }
        if expected_version_status and old_version_status != expected_version_status:
            return {
                "ok": False,
                "action": "scope_mismatch_apply",
                "status": "blocked",
                "risk_level": "blocked",
                "error_code": "STATE_CHANGED_SINCE_PREVIEW",
                "message": "state 在 preview 之后发生变化，已阻断 apply。",
                "preview_id": preview_id,
                "version": target_version,
                "resolution": resolution,
                "old_runner_status": old_runner_status,
                "old_version_status": old_version_status,
                "blockers": ["STATE_CHANGED_SINCE_PREVIEW"],
                "warnings": self._scope_apply_head_warnings(head_mismatch),
            }

        expected_head = self._str_param(artifact.get("current_head"), default="")
        current_head = self._str_param(self._service._get_git_head(), default="")
        if expected_head and current_head and expected_head != current_head:
            return {
                "ok": False,
                "action": "scope_mismatch_apply",
                "status": "blocked",
                "risk_level": "blocked",
                "error_code": "HEAD_CHANGED_SINCE_PREVIEW",
                "message": "HEAD 在 preview 之后发生变化，已阻断 apply。",
                "preview_id": preview_id,
                "version": target_version,
                "resolution": resolution,
                "blockers": ["HEAD_CHANGED_SINCE_PREVIEW"],
                "warnings": self._scope_apply_head_warnings(head_mismatch),
            }

        allowed_resolutions = self._allowed_scope_apply_resolutions(
            scope_status=scope_status,
            has_outside=bool(outside_allowed_files),
            has_forbidden=bool(forbidden_files_hit),
        )
        if resolution not in allowed_resolutions:
            return {
                "ok": False,
                "action": "scope_mismatch_apply",
                "status": "blocked",
                "risk_level": "blocked",
                "error_code": "RESOLUTION_NOT_ALLOWED",
                "message": f"resolution={resolution} 与当前 scope 状态不匹配。",
                "preview_id": preview_id,
                "version": target_version,
                "scope_status": scope_status,
                "resolution": resolution,
                "allowed_resolutions": sorted(allowed_resolutions),
                "blockers": ["RESOLUTION_NOT_ALLOWED"],
                "warnings": self._scope_apply_head_warnings(head_mismatch),
            }

        note, metadata, next_runner_status, next_version_status = self._build_scope_apply_update(
            resolution=resolution,
            scope_status=scope_status,
            outside_allowed_files=outside_allowed_files,
            old_runner_status=old_runner_status,
            old_version_status=old_version_status,
            head_mismatch=head_mismatch,
            preview_id=preview_id,
            report_id=self._str_param(artifact.get("report_id"), default=""),
        )

        now_iso = self._now_iso()

        try:
            mutation_result = self._state_mutations.apply_scope_mismatch_resolution(
                state=state,
                target_runtime=target_runtime,
                state_file=state_file,
                mutation=ScopeMismatchResolutionMutation(
                    runner_status_to=next_runner_status,
                    version_status_to=next_version_status,
                    note=note,
                    resolution_metadata=metadata,
                    recorded_at=now_iso,
                ),
            )
        except Exception:
            return self._error("scope_mismatch_apply", "STATE_SAVE_FAILED", "写入 state 失败。")

        self._delete_preview_artifact(preview_id)
        warnings = self._scope_apply_head_warnings(head_mismatch)
        return {
            "ok": True,
            "action": "scope_mismatch_apply",
            "status": "succeeded",
            "risk_level": "commit",
            "preview_id": preview_id,
            "version": target_version,
            "resolution": resolution,
            "scope_status": scope_status,
            "outside_allowed_files": outside_allowed_files,
            "forbidden_files_hit": forbidden_files_hit,
            "old_runner_status": old_runner_status,
            "new_runner_status": mutation_result.runner_status,
            "old_version_status": old_version_status,
            "new_version_status": mutation_result.version_status,
            "state_file": mutation_result.state_file,
            "note": mutation_result.note,
            "resolution_metadata": mutation_result.resolution_metadata,
            "next_action": str(metadata.get("next_action") or ""),
            "warnings": warnings,
            "message": "scope mismatch resolution 已写入 state。原始 executor report 未改写。",
        }

    def _recheck_report_apply(self, params: dict[str, Any]) -> dict[str, Any]:
        preview_id = self._str_param(params.get("preview_id"), default="")
        if not preview_id:
            return self._error("recheck_report_apply", "PREVIEW_ID_REQUIRED", "recheck_report_apply 需要 preview_id。")

        artifact = self._read_preview_artifact(preview_id)
        if artifact is None:
            return self._error("recheck_report_apply", "PREVIEW_NOT_FOUND", "preview_id 不存在或已过期。")
        if str(artifact.get("artifact_kind") or "") != "recheck_report_state_refresh":
            return self._error("recheck_report_apply", "PREVIEW_KIND_MISMATCH", "preview_id 类型不匹配。")
        guard_error = self._preview_guard_error(
            "recheck_report_apply",
            preview_id,
            artifact,
            expired_message="preview_id 已过期，请重新生成 preview。",
        )
        if guard_error is not None:
            return guard_error
        if not bool(artifact.get("can_refresh_state")):
            return self._error("recheck_report_apply", "PREVIEW_BLOCKED", "该 preview 不可用于状态刷新。")

        target_version = self._str_param(artifact.get("target_version"), default="")
        context = self._load_recheck_plan_state_context(target_version)
        if not context.get("ok"):
            return {
                "ok": False,
                "action": "recheck_report_apply",
                "status": "failed",
                "risk_level": "commit",
                "error_code": str(context.get("error_code") or "PLAN_OR_STATE_LOAD_FAILED"),
                "message": str(context.get("message") or "加载 plan/state 失败。"),
                "blockers": self._str_list(context.get("blockers")),
                "warnings": self._str_list(context.get("warnings")),
            }

        state = context["state"]
        target_runtime = context["target_runtime"]
        state_file = str(context.get("state_file") or "")
        old_runner_status = str(getattr(state, "status", "") or "")
        old_version_status = str(getattr(target_runtime, "status", "") or "")
        expected_runner_status = self._str_param(artifact.get("old_runner_status"), default="")
        expected_version_status = self._str_param(artifact.get("old_version_status"), default="")
        if old_runner_status != expected_runner_status or old_version_status != expected_version_status:
            return {
                "ok": False,
                "action": "recheck_report_apply",
                "status": "blocked",
                "risk_level": "blocked",
                "error_code": "STATE_CHANGED_SINCE_PREVIEW",
                "message": "state 在 preview 之后发生变化，已阻断 apply。",
                "blockers": ["STATE_CHANGED_SINCE_PREVIEW"],
                "warnings": [],
                "preview_id": preview_id,
                "target_version": target_version,
                "old_runner_status": old_runner_status,
                "old_version_status": old_version_status,
            }

        current_head = self._str_param(self._service._get_git_head(), default="")
        expected_head = self._str_param(artifact.get("current_head"), default="")
        if expected_head and current_head and expected_head != current_head:
            return {
                "ok": False,
                "action": "recheck_report_apply",
                "status": "blocked",
                "risk_level": "blocked",
                "error_code": "HEAD_CHANGED_SINCE_PREVIEW",
                "message": "HEAD 在 preview 之后发生变化，已阻断 apply。",
                "blockers": ["HEAD_CHANGED_SINCE_PREVIEW"],
                "warnings": [],
                "preview_id": preview_id,
                "target_version": target_version,
            }

        proposed = artifact.get("proposed_state_update")
        if not isinstance(proposed, dict):
            return self._error("recheck_report_apply", "PREVIEW_CORRUPTED", "preview 缺少 proposed_state_update。")
        next_runner_status = self._str_param(proposed.get("runner_status_to"), default="")
        next_version_status = self._str_param(proposed.get("version_status_to"), default="")
        if not next_runner_status or not next_version_status:
            return self._error("recheck_report_apply", "PREVIEW_CORRUPTED", "preview 状态更新字段无效。")

        now_iso = self._now_iso()
        try:
            mutation_result = self._state_mutations.apply_recheck_report_state_refresh(
                state=state,
                target_runtime=target_runtime,
                state_file=state_file,
                mutation=RecheckReportStateRefreshMutation(
                    runner_status_to=next_runner_status,
                    version_status_to=next_version_status,
                    recorded_at=now_iso,
                ),
            )
        except Exception:
            return self._error("recheck_report_apply", "STATE_SAVE_FAILED", "写入 state 失败。")

        warnings: list[str] = []
        audit_refresh_result: dict[str, Any] = {}
        try:
            reason = (
                f"recheck_report_apply preview_id={preview_id} "
                f"report_id={self._str_param(artifact.get('report_id'), default='')}"
            )
            audit_refresh_result = ExecutorRunReportStore(self.project_root).refresh_version_audit_package(
                version=target_version,
                reason=reason,
            )
            if not audit_refresh_result.get("ok"):
                warnings.append(str(audit_refresh_result.get("error_code") or "AUDIT_REFRESH_FAILED"))
        except Exception:
            warnings.append("AUDIT_REFRESH_FAILED")

        self._delete_preview_artifact(preview_id)
        return {
            "ok": True,
            "action": "recheck_report_apply",
            "status": "succeeded",
            "risk_level": "commit",
            "preview_id": preview_id,
            "target_version": target_version,
            "old_runner_status": old_runner_status,
            "new_runner_status": mutation_result.runner_status,
            "old_version_status": old_version_status,
            "new_version_status": mutation_result.version_status,
            "proposed_state_update": proposed,
            "state_file": mutation_result.state_file,
            "report_id": self._str_param(artifact.get("report_id"), default=""),
            "audit_refresh_result": audit_refresh_result if isinstance(audit_refresh_result, dict) else {},
            "warnings": warnings,
            "message": "状态刷新完成。原始 executor report 未改写。",
        }

    def _manual_fix_prompt_preview(self, params: dict[str, Any]) -> dict[str, Any]:
        version = self._str_param(params.get("version"), default="")
        manual_fix_prompt = self._str_param(params.get("manual_fix_prompt"), default="")
        reason = self._str_param(params.get("reason"), default="")
        if not manual_fix_prompt:
            return {
                "ok": False,
                "action": "manual_fix_prompt_preview",
                "status": "failed",
                "risk_level": "preview",
                "error_code": "MANUAL_FIX_PROMPT_REQUIRED",
                "message": "manual_fix_prompt 不能为空。",
                "blockers": ["MANUAL_FIX_PROMPT_REQUIRED"],
                "warnings": [],
            }

        context = self._load_recheck_plan_state_context(version)
        if not context.get("ok"):
            return {
                "ok": False,
                "action": "manual_fix_prompt_preview",
                "status": "failed",
                "risk_level": "preview",
                "error_code": str(context.get("error_code") or "PLAN_OR_STATE_LOAD_FAILED"),
                "message": str(context.get("message") or "加载 plan/state 失败。"),
                "blockers": self._str_list(context.get("blockers")),
                "warnings": self._str_list(context.get("warnings")),
            }

        state = context["state"]
        target_runtime = context["target_runtime"]
        target_version = self._str_param(context.get("target_version"), default="")
        current_version = self._str_param(getattr(state, "current_version", None), default="")
        old_runner_status = self._str_param(getattr(state, "status", None), default="")
        old_version_status = self._str_param(getattr(target_runtime, "status", None), default="")
        current_head = self._str_param(self._service._get_git_head(), default="")
        blockers: list[dict[str, str]] = []
        warnings: list[str] = []

        if current_version != target_version:
            blockers.append({
                "code": "CURRENT_VERSION_MISMATCH",
                "message": f"state.current_version={current_version or '<empty>'} 与目标 version={target_version} 不一致。",
            })

        allow_max_attempt_recovery, max_attempt_message = self._manual_fix_prompt_max_attempt_gate(state)
        state_gate = self._manual_fix_prompt_state_gate(
            runner_status=old_runner_status,
            version_status=old_version_status,
            allow_max_attempt_recovery=allow_max_attempt_recovery,
            max_attempt_message=max_attempt_message,
        )
        blockers.extend(state_gate["blockers"])
        warnings.extend(state_gate["warnings"])

        evidence = self._resolve_manual_fix_prompt_evidence(
            version=target_version,
            state=state,
            target_runtime=target_runtime,
        )
        if not evidence.get("ok"):
            blockers.append({
                "code": str(evidence.get("error_code") or "EVIDENCE_UNAVAILABLE"),
                "message": str(evidence.get("message") or "缺少可用审计/报告证据。"),
            })
        elif evidence.get("used_report_fallback"):
            warnings.append("USING_REPORT_EVIDENCE_FALLBACK")

        can_apply = len(blockers) == 0
        preview_id = ""
        expires_at = ""
        if can_apply:
            preview_id = self._generate_preview_key(prefix="manual_fix_prompt")
            expires_at = self._now_iso_ts(PREVIEW_TTL_SECONDS)
            artifact = manual_fix_prompt_preview_artifact(
                preview_id=preview_id,
                project_root=self.project_root,
                target_version=target_version,
                current_version_index=self._coerce_int(getattr(state, "current_version_index", 0), 0),
                old_runner_status=old_runner_status,
                old_version_status=old_version_status,
                current_head=current_head,
                attempt_before=self._coerce_int(getattr(state, "attempt", 0), 0),
                attempt_after=self._coerce_int(getattr(state, "attempt", 0), 0) + 1,
                max_fix_attempts_per_version=self._coerce_int(getattr(state, "max_fix_attempts_per_version", 0), 0),
                reason=reason,
                manual_fix_prompt=manual_fix_prompt,
                evidence_kind=self._str_param(evidence.get("evidence_kind"), default=""),
                evidence_path=self._str_param(evidence.get("evidence_path"), default=""),
                evidence_markdown=self._str_param(evidence.get("evidence_markdown"), default=""),
                report_id=self._str_param(evidence.get("report_id"), default=""),
                audit_package_id=self._str_param(evidence.get("audit_package_id"), default=""),
                allow_max_attempt_recovery=allow_max_attempt_recovery,
                created_at=self._now_iso(),
                expires_at=expires_at,
            )
            self._write_preview_artifact(preview_id, artifact)

        payload: dict[str, Any] = {
            "ok": True,
            "action": "manual_fix_prompt_preview",
            "status": "preview_ready" if can_apply else "blocked",
            "risk_level": "preview",
            "target_version": target_version,
            "current_version": current_version,
            "old_runner_status": old_runner_status,
            "old_version_status": old_version_status,
            "attempt_before": self._coerce_int(getattr(state, "attempt", 0), 0),
            "attempt_after": self._coerce_int(getattr(state, "attempt", 0), 0) + 1,
            "max_fix_attempts_per_version": self._coerce_int(getattr(state, "max_fix_attempts_per_version", 0), 0),
            "can_apply": can_apply,
            "blockers": blockers,
            "warnings": warnings,
            "facts_source": {
                "current_head": current_head,
                "evidence_kind": self._str_param(evidence.get("evidence_kind"), default=""),
                "evidence_path": self._str_param(evidence.get("evidence_path"), default=""),
                "report_id": self._str_param(evidence.get("report_id"), default=""),
                "audit_package_id": self._str_param(evidence.get("audit_package_id"), default=""),
            },
        }
        if can_apply:
            payload["preview_id"] = preview_id
            payload["expires_at"] = expires_at
            payload["why_safe_to_apply"] = "目标版本仍是当前版本，状态可进入修复准备，且证据与当前 HEAD 已固化到 preview。"
        else:
            payload["why_blocked"] = "当前版本不满足手动修复提示词准备条件。"
        return payload

    def _manual_fix_prompt_apply(self, params: dict[str, Any]) -> dict[str, Any]:
        preview_id = self._str_param(params.get("preview_id"), default="")
        if not preview_id:
            return self._error("manual_fix_prompt_apply", "PREVIEW_ID_REQUIRED", "manual_fix_prompt_apply 需要 preview_id。")

        artifact = self._read_preview_artifact(preview_id)
        if artifact is None:
            return self._error("manual_fix_prompt_apply", "PREVIEW_NOT_FOUND", "preview_id 不存在或已过期。")
        if str(artifact.get("artifact_kind") or "") != "manual_fix_prompt_prepare":
            return self._error("manual_fix_prompt_apply", "PREVIEW_KIND_MISMATCH", "preview_id 类型不匹配。")
        guard_error = self._preview_guard_error(
            "manual_fix_prompt_apply",
            preview_id,
            artifact,
            expired_message="preview_id 已过期，请重新生成 preview。",
        )
        if guard_error is not None:
            return guard_error
        if not bool(artifact.get("can_apply")):
            return self._error("manual_fix_prompt_apply", "PREVIEW_BLOCKED", "该 preview 当前不可 apply。")

        target_version = self._str_param(artifact.get("target_version"), default="")
        context = self._load_recheck_plan_state_context(target_version)
        if not context.get("ok"):
            return self._error("manual_fix_prompt_apply", str(context.get("error_code") or "PLAN_OR_STATE_LOAD_FAILED"), str(context.get("message") or "加载 plan/state 失败。"))

        plan = context["plan"]
        state = context["state"]
        target_runtime = context["target_runtime"]
        state_file = str(context.get("state_file") or "")
        baseline_updated_at = state.updated_at
        current_version = self._str_param(getattr(state, "current_version", None), default="")
        current_version_index = self._coerce_int(getattr(state, "current_version_index", 0), 0)
        old_runner_status = self._str_param(getattr(state, "status", None), default="")
        old_version_status = self._str_param(getattr(target_runtime, "status", None), default="")

        if current_version != target_version or current_version_index != self._coerce_int(artifact.get("current_version_index"), -1):
            return self._error("manual_fix_prompt_apply", "CURRENT_VERSION_MISMATCH", "当前版本已变化，已阻断 apply。")
        if old_runner_status != self._str_param(artifact.get("old_runner_status"), default="") or old_version_status != self._str_param(artifact.get("old_version_status"), default=""):
            return self._error("manual_fix_prompt_apply", "STATE_CHANGED_SINCE_PREVIEW", "state 在 preview 之后发生变化，已阻断 apply。")
        if self._coerce_int(getattr(state, "attempt", 0), 0) != self._coerce_int(artifact.get("attempt_before"), -1):
            return self._error("manual_fix_prompt_apply", "STATE_CHANGED_SINCE_PREVIEW", "state.attempt 在 preview 之后发生变化，已阻断 apply。")

        current_head = self._str_param(self._service._get_git_head(), default="")
        preview_head = self._str_param(artifact.get("current_head"), default="")
        if current_head and preview_head and current_head != preview_head:
            return self._error("manual_fix_prompt_apply", "HEAD_CHANGED_SINCE_PREVIEW", "HEAD 在 preview 之后发生变化，已阻断 apply。")

        manual_fix_prompt = self._str_param(artifact.get("manual_fix_prompt"), default="")
        evidence_markdown = self._str_param(artifact.get("evidence_markdown"), default="")
        evidence_path = self._str_param(artifact.get("evidence_path"), default="")
        state_machine = RunnerStateMachine(plan, state)
        try:
            state_machine.paste_manual_fix_prompt(
                manual_fix_prompt,
                audit_file_override=evidence_path or None,
                audit_markdown_override=evidence_markdown or None,
                allow_max_attempt_recovery=bool(artifact.get("allow_max_attempt_recovery")),
            )
        except ValueError as exc:
            return self._error("manual_fix_prompt_apply", "FIX_PROMPT_PREPARE_BLOCKED", str(exc))

        try:
            StateMutationGateway().save(state, state_file, expected_updated_at=baseline_updated_at)
        except Exception:
            return self._error("manual_fix_prompt_apply", "STATE_SAVE_FAILED", "写入 state 失败。")

        self._delete_preview_artifact(preview_id)
        runtime_dir = resolve_project_runner_path(self.project_root, "runtime")
        return {
            "ok": True,
            "action": "manual_fix_prompt_apply",
            "status": "succeeded",
            "risk_level": "commit",
            "preview_id": preview_id,
            "target_version": target_version,
            "old_runner_status": self._str_param(artifact.get("old_runner_status"), default=""),
            "new_runner_status": self._str_param(getattr(state, "status", None), default=""),
            "old_version_status": self._str_param(artifact.get("old_version_status"), default=""),
            "new_version_status": self._str_param(getattr(target_runtime, "status", None), default=""),
            "attempt_before": self._coerce_int(artifact.get("attempt_before"), 0),
            "attempt_after": self._coerce_int(getattr(state, "attempt", 0), 0),
            "state_file": state_file,
            "manual_fix_prompt_file": os.path.join(runtime_dir, f"manual-fix-{target_version}-attempt-{self._coerce_int(getattr(state, 'attempt', 0), 0)}.md"),
            "fix_prompt_file": os.path.join(runtime_dir, "current-fix-prompt.md"),
            "evidence_kind": self._str_param(artifact.get("evidence_kind"), default=""),
            "evidence_path": evidence_path,
            "report_id": self._str_param(artifact.get("report_id"), default=""),
            "audit_package_id": self._str_param(artifact.get("audit_package_id"), default=""),
            "message": "手动修复提示词已准备完成。当前版本进入 FIX_PROMPT_READY，未标记为通过，也未推进下一版本。",
        }

    def _validation_run_record_path(self, validation_run_id: str) -> str:
        safe_id = "".join(ch for ch in str(validation_run_id or "") if ch.isalnum() or ch in {"_", "-"})
        if safe_id != str(validation_run_id or "") or not safe_id:
            return ""
        return resolve_project_runner_path(
            self.project_root, "runtime", "validation-runs", f"{safe_id}.json"
        )

    def _load_validation_run_record(self, validation_run_id: str) -> dict[str, Any]:
        path = self._validation_run_record_path(validation_run_id)
        if not path:
            return {
                "ok": False,
                "error_code": "INVALID_VALIDATION_RUN_ID",
                "message": "validation_run_id 格式无效。",
            }
        root = os.path.realpath(resolve_project_runner_path(self.project_root, "runtime", "validation-runs"))
        target = os.path.realpath(path)
        if not (target == root or target.startswith(root + os.sep)):
            return {
                "ok": False,
                "error_code": "VALIDATION_RUN_PATH_OUTSIDE_ROOT",
                "message": "validation_run_id 指向非法路径。",
            }
        if not os.path.isfile(target):
            return {
                "ok": False,
                "error_code": "VALIDATION_RUN_NOT_FOUND",
                "message": "未找到 validation run 记录。",
            }
        try:
            with open(target, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception:
            return {
                "ok": False,
                "error_code": "VALIDATION_RUN_INVALID",
                "message": "validation run 记录无法读取。",
            }
        if not isinstance(data, dict):
            return {
                "ok": False,
                "error_code": "VALIDATION_RUN_INVALID",
                "message": "validation run 记录格式无效。",
            }
        return {"ok": True, "record": data, "path": target}

    def _load_state_lineage_context(self) -> dict[str, Any]:
        plan_file = resolve_project_runner_path(self.project_root, "plan.json")
        state_file = resolve_project_runner_path(self.project_root, "state.json")
        if not os.path.isfile(plan_file):
            return {
                "ok": False,
                "error_code": "PLAN_NOT_FOUND",
                "message": "缺少 plan.json，无法执行 state lineage reconciliation。",
                "blockers": ["PLAN_NOT_FOUND"],
                "warnings": [],
            }
        if not os.path.isfile(state_file):
            return {
                "ok": False,
                "error_code": "STATE_NOT_FOUND",
                "message": "缺少 state.json，无法执行 state lineage reconciliation。",
                "blockers": ["STATE_NOT_FOUND"],
                "warnings": [],
            }
        try:
            with open(plan_file, "r", encoding="utf-8") as handle:
                plan = json.load(handle)
            with open(state_file, "r", encoding="utf-8") as handle:
                state = json.load(handle)
        except Exception as exc:
            return {
                "ok": False,
                "error_code": "PLAN_OR_STATE_LOAD_FAILED",
                "message": f"加载 plan/state 失败：{exc}",
                "blockers": ["PLAN_OR_STATE_LOAD_FAILED"],
                "warnings": [],
            }
        if not isinstance(plan, dict) or not isinstance(state, dict):
            return {
                "ok": False,
                "error_code": "PLAN_OR_STATE_INVALID",
                "message": "plan/state 格式无效。",
                "blockers": ["PLAN_OR_STATE_INVALID"],
                "warnings": [],
            }
        return {
            "ok": True,
            "plan": plan,
            "state": state,
            "plan_file": plan_file,
            "state_file": state_file,
            "blockers": [],
            "warnings": [],
        }

    def _state_lineage_commit_facts(self, bindings: list[Any]) -> dict[str, dict[str, Any]]:
        exists: dict[str, bool] = {}
        subjects: dict[str, str] = {}
        for item in bindings:
            if not isinstance(item, dict):
                continue
            commit_hash = self._str_param(item.get("accepted_commit") or item.get("commit_hash"), default="")
            if not commit_hash or commit_hash in exists:
                continue
            ok, _, _ = self._service._run_git_cmd(["cat-file", "-e", f"{commit_hash}^{{commit}}"])
            exists[commit_hash] = bool(ok)
            if ok:
                subject_ok, subject_out, _ = self._service._run_git_cmd(["show", "-s", "--format=%s", commit_hash])
                subjects[commit_hash] = subject_out.strip() if subject_ok else ""
            else:
                subjects[commit_hash] = ""
        return {"exists": exists, "subjects": subjects}

    def _final_version_commit_fact(self, commit_hash: str) -> dict[str, Any]:
        commit_hash = self._str_param(commit_hash, default="")
        if not commit_hash:
            return {"exists": False, "subject": ""}
        ok, _, _ = self._service._run_git_cmd(["cat-file", "-e", f"{commit_hash}^{{commit}}"])
        if not ok:
            return {"exists": False, "subject": ""}
        subject_ok, subject_out, _ = self._service._run_git_cmd(["show", "-s", "--format=%s", commit_hash])
        return {
            "exists": True,
            "subject": subject_out.strip() if subject_ok else "",
        }

    def _load_recheck_plan_state_context(self, requested_version: str) -> dict[str, Any]:
        workspace_root = self.project_root
        plan_file = resolve_project_runner_path(workspace_root, "plan.json")
        state_file = resolve_project_runner_path(workspace_root, "state.json")
        if not os.path.isfile(plan_file):
            return {
                "ok": False,
                "error_code": "PLAN_NOT_FOUND",
                "message": "缺少 plan.json，无法执行 report 重审。",
                "blockers": ["PLAN_NOT_FOUND"],
                "warnings": [],
            }
        if not os.path.isfile(state_file):
            return {
                "ok": False,
                "error_code": "STATE_NOT_FOUND",
                "message": "缺少 state.json，无法执行 report 重审。",
                "blockers": ["STATE_NOT_FOUND"],
                "warnings": [],
            }

        try:
            plan = PlanLoader().load_plan(plan_file)
            state = StateStore().load_state(state_file)
        except Exception as exc:
            return {
                "ok": False,
                "error_code": "PLAN_OR_STATE_LOAD_FAILED",
                "message": f"加载 plan/state 失败：{exc}",
                "blockers": ["PLAN_OR_STATE_LOAD_FAILED"],
                "warnings": [],
            }

        def _resolve_plan_path(value: Any, default_relative: str) -> str:
            text = self._str_param(value, default="")
            if not text:
                text = default_relative
            if os.path.isabs(text):
                return text
            return os.path.join(workspace_root, text)

        plan.project_root = workspace_root
        runner_rel_dir = resolve_project_runner_rel_dir(workspace_root)
        plan.logs_dir = _resolve_plan_path(getattr(plan, "logs_dir", ""), os.path.join(runner_rel_dir, "logs"))
        plan.runtime_dir = _resolve_plan_path(getattr(plan, "runtime_dir", ""), os.path.join(runner_rel_dir, "runtime"))
        plan.state_file = _resolve_plan_path(getattr(plan, "state_file", ""), os.path.join(runner_rel_dir, "state.json"))
        plan.rules_file = _resolve_plan_path(getattr(plan, "rules_file", ""), os.path.join(runner_rel_dir, "rules.md"))

        target_version = requested_version.strip() if requested_version.strip() else str(getattr(state, "current_version", "") or "")
        if not target_version:
            return {
                "ok": False,
                "error_code": "VERSION_REQUIRED",
                "message": "version 不能为空，且 state.current_version 为空。",
                "blockers": ["VERSION_REQUIRED"],
                "warnings": [],
            }

        target_runtime = None
        for runtime in getattr(state, "versions", []):
            if str(getattr(runtime, "version", "") or "") == target_version:
                target_runtime = runtime
                break
        if target_runtime is None:
            return {
                "ok": False,
                "error_code": "STATE_VERSION_NOT_FOUND",
                "message": f"state.versions 中不存在 version={target_version}。",
                "blockers": ["STATE_VERSION_NOT_FOUND"],
                "warnings": [],
            }

        target_plan_version = None
        for version_spec in getattr(plan, "versions", []):
            if str(getattr(version_spec, "version", "") or "") == target_version:
                target_plan_version = version_spec
                break
        if target_plan_version is None:
            return {
                "ok": False,
                "error_code": "PLAN_VERSION_NOT_FOUND",
                "message": f"plan.versions 中不存在 version={target_version}。",
                "blockers": ["PLAN_VERSION_NOT_FOUND"],
                "warnings": [],
            }

        return {
            "ok": True,
            "target_version": target_version,
            "plan": plan,
            "state": state,
            "target_runtime": target_runtime,
            "target_plan_version": target_plan_version,
            "state_file": state_file,
            "plan_file": plan_file,
            "warnings": [],
            "blockers": [],
        }

    def _manual_fix_prompt_max_attempt_gate(self, state: Any) -> tuple[bool, str]:
        attempt = self._coerce_int(getattr(state, "attempt", 0), 0)
        max_attempts = self._coerce_int(getattr(state, "max_fix_attempts_per_version", 0), 0)
        if max_attempts <= 0:
            return False, "当前 max_fix_attempts_per_version 无效。"
        if attempt < max_attempts:
            return True, ""
        return False, f"当前 attempt={attempt}，max_fix_attempts_per_version={max_attempts}，没有剩余修复次数。"

    def _manual_fix_prompt_state_gate(
        self,
        *,
        runner_status: str,
        version_status: str,
        allow_max_attempt_recovery: bool,
        max_attempt_message: str,
    ) -> dict[str, Any]:
        normalized_runner = str(runner_status or "").strip().upper()
        normalized_version = str(version_status or "").strip().upper()
        blockers: list[dict[str, str]] = []
        warnings: list[str] = []
        if normalized_runner in _MANUAL_FIX_PROMPT_REJECTED_RUNNER_STATUSES:
            blockers.append({
                "code": "RUNNER_STATUS_NOT_FIX_CANDIDATE",
                "message": f"当前状态 runner={runner_status} 不适合准备修复提示词。",
            })
            return {"blockers": blockers, "warnings": warnings}
        if normalized_runner.startswith("RUNNING_"):
            blockers.append({
                "code": "RUNNER_STATUS_RUNNING",
                "message": f"当前状态 runner={runner_status} 正在运行，不能准备修复提示词。",
            })
            return {"blockers": blockers, "warnings": warnings}
        if normalized_runner == "BLOCKED_BY_MAX_FIX_ATTEMPTS" and not allow_max_attempt_recovery:
            blockers.append({
                "code": "MAX_FIX_ATTEMPTS_REACHED",
                "message": max_attempt_message or "当前版本已达到最大修复次数。",
            })
            return {"blockers": blockers, "warnings": warnings}
        if normalized_runner not in _MANUAL_FIX_PROMPT_ALLOWED_RUNNER_STATUSES:
            blockers.append({
                "code": "RUNNER_STATUS_NOT_FIX_CANDIDATE",
                "message": f"当前状态 runner={runner_status} version={version_status} 不适合准备修复提示词。",
            })
            return {"blockers": blockers, "warnings": warnings}
        if normalized_runner == "BLOCKED_BY_MAX_FIX_ATTEMPTS" and allow_max_attempt_recovery:
            warnings.append("RECOVERING_BLOCKED_BY_MAX_FIX_ATTEMPTS")
        if normalized_version in {"PASSED", "PROMPT_READY", "FIX_PROMPT_READY", "ACCEPTANCE_RUNNING", "FIX_ACCEPTANCE_RUNNING", "WAITING_MODEL_DONE", "FIX_WAITING_MODEL_DONE", "NOT_STARTED"}:
            blockers.append({
                "code": "VERSION_STATUS_NOT_FIX_CANDIDATE",
                "message": f"当前版本状态 version={version_status} 不适合准备修复提示词。",
            })
        return {"blockers": blockers, "warnings": warnings}

    def _resolve_manual_fix_prompt_evidence(
        self,
        *,
        version: str,
        state: Any,
        target_runtime: Any,
    ) -> dict[str, Any]:
        candidates: list[tuple[str, str]] = []
        current_version = self._str_param(getattr(state, "current_version", None), default="")
        state_last_audit = self._str_param(getattr(state, "last_audit_file", None), default="")
        runtime_last_audit = self._str_param(getattr(target_runtime, "last_audit_file", None), default="")
        if state_last_audit:
            candidates.append(("state.last_audit_file", state_last_audit))
        if runtime_last_audit and runtime_last_audit not in {path for _, path in candidates}:
            candidates.append(("runtime.last_audit_file", runtime_last_audit))
        if current_version:
            candidates.append((
                "logs.current_version_audit",
                resolve_project_runner_path(self.project_root, "logs", f"{current_version}-audit.md"),
            ))

        for evidence_kind, path in candidates:
            content = self._safe_read_project_text(path)
            if content:
                return {
                    "ok": True,
                    "evidence_kind": evidence_kind,
                    "evidence_path": path,
                    "evidence_markdown": content,
                    "report_id": "",
                    "audit_package_id": "",
                    "used_report_fallback": False,
                }

        store = ExecutorRunReportStore(self.project_root)
        try:
            version_pkg_ret = store.get_latest_materialized_version_audit_package(version)
        except Exception:
            version_pkg_ret = {"ok": False}
        if version_pkg_ret.get("ok") and isinstance(version_pkg_ret.get("audit_package"), dict):
            version_pkg = version_pkg_ret["audit_package"]
            evidence_paths = version_pkg.get("evidence_paths") if isinstance(version_pkg.get("evidence_paths"), dict) else {}
            report_md_path = self._str_param(evidence_paths.get("selected_report_markdown_file"), default="")
            report_md = self._safe_read_project_text(report_md_path)
            if report_md:
                return {
                    "ok": True,
                    "evidence_kind": "version_audit.selected_report_markdown_file",
                    "evidence_path": report_md_path,
                    "evidence_markdown": report_md,
                    "report_id": self._str_param(version_pkg.get("selected_report_id"), default=""),
                    "audit_package_id": self._str_param(version_pkg.get("audit_package_id"), default=""),
                    "used_report_fallback": True,
                }

        try:
            latest_report_ret = store.get_report(version=version, latest=True, include_markdown=True)
        except Exception:
            latest_report_ret = {"ok": False}
        report = latest_report_ret.get("report") if isinstance(latest_report_ret.get("report"), dict) else {}
        if latest_report_ret.get("ok") and report:
            audit_path = self._str_param(report.get("audit_file"), default="")
            audit_md = self._safe_read_project_text(audit_path)
            if audit_md:
                return {
                    "ok": True,
                    "evidence_kind": "latest_report.audit_file",
                    "evidence_path": audit_path,
                    "evidence_markdown": audit_md,
                    "report_id": self._str_param(report.get("report_id"), default=""),
                    "audit_package_id": "",
                    "used_report_fallback": True,
                }
            report_md_path = self._str_param(report.get("markdown_file"), default="")
            report_md = self._safe_read_project_text(report_md_path)
            if report_md:
                return {
                    "ok": True,
                    "evidence_kind": "latest_report.markdown_file",
                    "evidence_path": report_md_path,
                    "evidence_markdown": report_md,
                    "report_id": self._str_param(report.get("report_id"), default=""),
                    "audit_package_id": "",
                    "used_report_fallback": True,
                }
            inline_md = self._str_param(latest_report_ret.get("report_markdown"), default="")
            if inline_md:
                return {
                    "ok": True,
                    "evidence_kind": "latest_report.report_markdown",
                    "evidence_path": "",
                    "evidence_markdown": inline_md,
                    "report_id": self._str_param(report.get("report_id"), default=""),
                    "audit_package_id": "",
                    "used_report_fallback": True,
                }

        return {
            "ok": False,
            "error_code": "EVIDENCE_UNAVAILABLE",
            "message": "未找到当前版本可用的审计文件、报告 Markdown 或版本审计包证据。",
        }

    def _load_scope_mismatch_plan_context(self, requested_version: str) -> dict[str, Any]:
        workspace_root = self.project_root
        plan_file = resolve_project_runner_path(workspace_root, "plan.json")
        if not os.path.isfile(plan_file):
            return {
                "ok": False,
                "error_code": "PLAN_NOT_FOUND",
                "message": "缺少 plan.json，无法执行 scope mismatch 诊断。",
                "blockers": ["PLAN_NOT_FOUND"],
                "warnings": [],
            }

        try:
            plan = PlanLoader().load_plan(plan_file)
        except Exception as exc:
            return {
                "ok": False,
                "error_code": "PLAN_LOAD_FAILED",
                "message": f"加载 plan 失败：{exc}",
                "blockers": ["PLAN_LOAD_FAILED"],
                "warnings": [],
            }

        target_version = requested_version.strip()
        target_plan_version = None
        for version_spec in getattr(plan, "versions", []):
            if str(getattr(version_spec, "version", "") or "") == target_version:
                target_plan_version = version_spec
                break
        if target_plan_version is None:
            return {
                "ok": False,
                "error_code": "PLAN_VERSION_NOT_FOUND",
                "message": f"plan.versions 中不存在 version={target_version}。",
                "blockers": ["PLAN_VERSION_NOT_FOUND"],
                "warnings": [],
            }

        return {
            "ok": True,
            "target_version": target_version,
            "plan": plan,
            "target_plan_version": target_plan_version,
            "plan_file": plan_file,
            "warnings": [],
            "blockers": [],
        }

    def _extract_scope_from_report(self, report: dict[str, Any]) -> dict[str, Any]:
        summary_raw = report.get("summary")
        summary = summary_raw if isinstance(summary_raw, dict) else {}
        validation_results = self._str_list(summary.get("validation_results"))
        scope_line = ""
        for item in validation_results:
            if item.startswith("Scope check:"):
                scope_line = item
        scope_status = "UNKNOWN"
        if scope_line:
            scope_status = scope_line.split(":", 1)[-1].strip().upper() or "UNKNOWN"
        blocked = scope_status in {"FAILED", "BLOCKED", "VIOLATION", "BLOCKED_BY_SCOPE_VIOLATION"}
        return {
            "status": scope_status,
            "blocked": blocked,
            "validation_count": len(validation_results),
            "source": "report.summary.validation_results",
        }

    def _collect_recheck_changed_files(self, report: dict[str, Any]) -> dict[str, Any]:
        live_files = self._service._collect_executor_report_changed_files(None)
        if live_files:
            return {
                "source": "git_live_diff_and_status",
                "files": live_files,
                "has_trustable_source": True,
            }
        summary_raw = report.get("summary")
        summary = summary_raw if isinstance(summary_raw, dict) else {}
        summary_changed = self._str_list(summary.get("changed_files"))
        if summary_changed:
            return {
                "source": "report_summary_changed_files",
                "files": sorted(set(summary_changed)),
                "has_trustable_source": True,
            }
        report_changed = self._str_list(report.get("changed_files"))
        if report_changed:
            return {
                "source": "report_changed_files",
                "files": sorted(set(report_changed)),
                "has_trustable_source": True,
            }
        return {
            "source": "none",
            "files": [],
            "has_trustable_source": False,
        }

    def _collect_scope_mismatch_changed_files(self, report: dict[str, Any]) -> dict[str, Any]:
        return self._collect_recheck_changed_files(report)

    def _build_scope_mismatch_resolution_options(
        self,
        *,
        scope_status: str,
        has_outside: bool,
        has_forbidden: bool,
    ) -> list[dict[str, Any]]:
        refresh_recommended = bool(scope_status == "in_scope" and not has_forbidden)
        manual_recommended = bool(has_outside and not has_forbidden)
        abort_recommended = bool(has_outside or has_forbidden)
        return [
            {
                "option": "refresh_in_scope_state",
                "description": "scope 已回到 in_scope，刷新当前 version 的 Runner state 为通过。",
                "recommended": refresh_recommended,
                "can_apply": bool(scope_status == "in_scope" and not has_forbidden),
            },
            {
                "option": "record_direct_manual_review",
                "description": "记录 direct/manual resolution，保持或标记当前版本 blocked，并交由人工后续处理。",
                "recommended": manual_recommended,
                "can_apply": bool(has_outside and not has_forbidden),
            },
            {
                "option": "abort_version",
                "description": "终止当前版本推进，保留 scope mismatch 诊断记录。",
                "recommended": abort_recommended,
                "can_apply": bool(not has_forbidden),
            },
            {
                "option": "update_allowed_files_and_rerun",
                "description": "调整 plan allowed_files 后重新运行执行器。",
                "recommended": False,
                "can_apply": False,
            },
            {
                "option": "revert_out_of_scope_changes",
                "description": "回退越界改动后重新执行验收。",
                "recommended": False,
                "can_apply": False,
            },
            {
                "option": "direct_manual_review_commit",
                "description": "人工直接处理代码改动，Runner 仅记录该决议。",
                "recommended": False,
                "can_apply": False,
            },
        ]

    def _allowed_scope_apply_resolutions(
        self,
        *,
        scope_status: str,
        has_outside: bool,
        has_forbidden: bool,
    ) -> set[str]:
        if has_forbidden:
            return set()
        allowed: set[str] = {"abort_version"}
        if scope_status == "in_scope" and not has_outside:
            allowed.add("refresh_in_scope_state")
            return allowed
        if has_outside:
            allowed.add("record_direct_manual_review")
        return allowed

    def _scope_apply_head_warnings(self, head_mismatch: dict[str, Any] | None) -> list[str]:
        if not isinstance(head_mismatch, dict):
            return []
        code = self._str_param(head_mismatch.get("code"), default="")
        if code == "HEAD_MISMATCH":
            return ["HEAD_MISMATCH"]
        if code:
            return [code]
        return []

    def _build_scope_apply_update(
        self,
        *,
        resolution: str,
        scope_status: str,
        outside_allowed_files: list[str],
        old_runner_status: str,
        old_version_status: str,
        head_mismatch: dict[str, Any] | None,
        preview_id: str,
        report_id: str,
    ) -> tuple[str, dict[str, Any], str, str]:
        now_iso = self._now_iso()
        mismatch_code = self._str_param(head_mismatch.get("code"), default="") if isinstance(head_mismatch, dict) else ""
        base_metadata: dict[str, Any] = {
            "resolution": resolution,
            "scope_status": scope_status,
            "outside_allowed_files_count": len(outside_allowed_files),
            "outside_allowed_files": outside_allowed_files,
            "preview_id": preview_id,
            "report_id": report_id,
            "recorded_at": now_iso,
            "record_type": "scope_mismatch_resolution",
            "head_mismatch_code": mismatch_code,
            "head_mismatch": head_mismatch if isinstance(head_mismatch, dict) else {},
        }
        if resolution == "refresh_in_scope_state":
            note = "scope_mismatch_apply: refresh_in_scope_state，当前版本恢复为 PASSED。"
            base_metadata["manual_review_required"] = False
            base_metadata["next_action"] = "continue_normal_runner_flow"
            return note, base_metadata, "VERSION_PASSED", "PASSED"
        if resolution == "record_direct_manual_review":
            next_runner_status = old_runner_status if old_runner_status in {"BLOCKED_BY_SCOPE_VIOLATION", "BLOCKED"} else "BLOCKED_BY_SCOPE_VIOLATION"
            next_version_status = old_version_status if old_version_status == "BLOCKED" else "BLOCKED"
            note = "scope_mismatch_apply: record_direct_manual_review，版本保持 blocked，等待人工处理。"
            base_metadata["manual_review_required"] = True
            base_metadata["direct_resolution"] = True
            base_metadata["next_action"] = "manual_review_then_choose_abort_or_plan_update"
            return note, base_metadata, next_runner_status, next_version_status
        next_runner_status = old_runner_status if old_runner_status in {"BLOCKED_BY_SCOPE_VIOLATION", "BLOCKED"} else "BLOCKED_BY_SCOPE_VIOLATION"
        next_version_status = old_version_status if old_version_status == "BLOCKED" else "BLOCKED"
        note = "scope_mismatch_apply: abort_version，当前版本已终止并保持 blocked。"
        base_metadata["manual_review_required"] = True
        base_metadata["next_action"] = "version_aborted_waiting_user_plan"
        return note, base_metadata, next_runner_status, next_version_status

    def _evaluate_recheck_scope(
        self,
        *,
        version_spec: Any,
        changed_files: list[str],
        source: str,
    ) -> dict[str, Any]:
        allowed_patterns = [glob_normalize(pattern) for pattern in getattr(version_spec, "allowed_files", [])]
        forbidden_patterns = [glob_normalize(pattern) for pattern in getattr(version_spec, "forbidden_files", [])]
        raw_changed_files = [glob_normalize(item) for item in changed_files if isinstance(item, str) and item.strip()]
        ignored_runtime_files, scope_checked_files = self._split_runtime_scope_files(raw_changed_files)
        changed_outside_allowed = [
            path for path in scope_checked_files
            if not glob_match_any(path, allowed_patterns)
        ]
        changed_forbidden = [
            path for path in scope_checked_files
            if glob_match_any(path, forbidden_patterns)
        ]
        blocked = bool(changed_outside_allowed or changed_forbidden)
        return {
            "status": "FAILED" if blocked else "PASSED",
            "blocked": blocked,
            "source": source,
            "allowed_files": allowed_patterns,
            "forbidden_files": forbidden_patterns,
            "raw_changed_files": raw_changed_files,
            "ignored_runtime_files": ignored_runtime_files,
            "scope_checked_files": scope_checked_files,
            "changed_outside_allowed_files": changed_outside_allowed,
            "changed_forbidden_files": changed_forbidden,
        }

    def _is_state_recheck_candidate(self, runner_status: str, version_status: str) -> bool:
        runner_status_norm = str(runner_status or "").strip().upper()
        version_status_norm = str(version_status or "").strip().upper()
        if runner_status_norm in {"BLOCKED_BY_SCOPE_VIOLATION", "BLOCKED"}:
            return True
        return version_status_norm == "BLOCKED"

    def _split_runtime_scope_files(self, paths: list[str]) -> tuple[list[str], list[str]]:
        ignored_runtime_files: list[str] = []
        scope_checked_files: list[str] = []
        for path in paths:
            normalized = glob_normalize(path)
            if is_project_runner_path(normalized):
                ignored_runtime_files.append(normalized)
            else:
                scope_checked_files.append(normalized)
        return ignored_runtime_files, scope_checked_files

    def _get_audit_package(self, params: dict[str, Any]) -> dict[str, Any]:
        latest = self._bool_param(params.get("latest"), default=True)
        report_id = self._str_param(params.get("report_id"), default="")
        version = self._str_param(params.get("version"), default="")
        section = self._str_param(params.get("section"), default="summary", lower=True)
        include_markdown = self._bool_param(params.get("include_markdown"), default=False)
        max_chars = self._bounded_int_param(params.get("max_chars"), default=20000, minimum=1, maximum=60000)

        allowed_sections = {"summary", "lineage", "validation", "scope", "report_excerpt"}
        if section not in allowed_sections:
            return self._error("get_audit_package", "INVALID_SECTION", "section 不支持。")
        include_md = bool((section == "report_excerpt" and include_markdown) or section == "validation")
        if report_id:
            version = ""

        store = ExecutorRunReportStore(self.project_root)
        version_package: dict[str, Any] | None = None
        version_package_source = ""
        if version:
            try:
                version_ret = store.get_latest_materialized_version_audit_package(version)
                if version_ret.get("ok") and isinstance(version_ret.get("audit_package"), dict):
                    version_package = version_ret["audit_package"]
                    version_package_source = self._str_param(version_ret.get("source"), default="")
            except ValueError:
                return self._error("get_audit_package", "INVALID_VERSION", "version 格式无效。")
            except Exception:
                version_package = None

        try:
            latest_for_report = True if (version and not report_id) else (latest if not report_id else False)
            report_result = store.get_report(
                version=version or None,
                report_id=report_id or None,
                latest=latest_for_report,
                include_markdown=include_md,
                max_markdown_chars=max_chars,
            )
        except ValueError:
            if report_id:
                return self._error("get_audit_package", "INVALID_REPORT_ID", "report_id 格式无效。")
            return self._error("get_audit_package", "INVALID_VERSION", "version 格式无效。")
        except Exception:
            return self._error("get_audit_package", "REPORT_LOAD_FAILED", "读取 report 失败。")

        if not report_result.get("ok"):
            code = str(report_result.get("error_code") or "REPORT_NOT_FOUND")
            if code == "REPORT_NOT_FOUND" and isinstance(version_package, dict):
                report_result = {"ok": True, "report": {}}
            elif code == "REPORT_NOT_FOUND":
                return self._error("get_audit_package", "REPORT_NOT_FOUND", "未找到可用 report。")
            else:
                return self._error("get_audit_package", code, "读取 report 失败。")

        report = report_result.get("report")
        if not isinstance(report, dict):
            report = {}
        report_markdown_text = self._str_param(report_result.get("report_markdown"), default="")

        selected_lineage: dict[str, str] = {}
        changed_files: list[str] = []
        validation_status_summary = "unknown"
        scope_status_summary = "unknown"
        has_markdown = False
        truncated = False
        audit_package_id = "auditpkg_unknown"
        evidence_paths = {"json_file": "", "markdown_file": "", "log_file": "", "audit_file": ""}
        version_value = self._str_param(report.get("version"), default=version)
        version_name = self._str_param(report.get("version_name"), default="")
        provider_value = self._str_param(report.get("provider"), default="")
        execution_mode_value = self._str_param(report.get("execution_mode"), default="")
        status_value = self._str_param(report.get("status"), default="")
        started_at_value = self._str_param(report.get("started_at"), default="")
        finished_at_value = self._str_param(report.get("finished_at"), default="")
        validation_sample: list[str] = []
        validation_for_section: list[str] = []
        validation_command_records: list[dict[str, Any]] = []
        validation_inconsistent = False
        validation_inconsistency_reasons: list[str] = []
        validation_truth_source = ""
        validation_command_count = 0
        validation_failed_command_count = 0
        source_kind = "dynamic_report"
        report_id_value = self._str_param(report.get("report_id"), default="")
        package_role = ""
        commit_data: dict[str, Any] = {
            "commit_hash": "",
            "commit_hash_short": "",
            "commit_message": "",
            "committed_at": "",
            "committed_files": [],
            "commit_head_before": "",
            "commit_head_after": "",
            "commit_metadata_status": "unknown",
        }

        if isinstance(version_package, dict):
            report_id_value = self._str_param(
                version_package.get("selected_report_id"),
                default=self._str_param(version_package.get("latest_report_id"), default=report_id_value),
            )
            for key in (
                "run_id",
                "preview_id",
                "preview_claimed_at",
                "preview_claim_status",
                "prompt_file",
                "prompt_sha256",
                "prompt_sha256_status",
            ):
                val = version_package.get(key)
                if isinstance(val, str) and val.strip():
                    selected_lineage[key] = val.strip()[:200]
            report_ids = self._str_list(version_package.get("report_ids"))
            if report_id_value:
                selected_lineage["selected_report_id"] = report_id_value
            if report_ids:
                selected_lineage["report_ids"] = ",".join(report_ids[:20])
            changed_files = self._str_list(version_package.get("changed_files"))
            report_summary_obj = report.get("summary")
            report_summary_data = report_summary_obj if isinstance(report_summary_obj, dict) else {}
            validation_truth = self._extract_validation_truth(
                version_package,
                fallback_summary=report_summary_data,
                executor_report_text=report_markdown_text,
            )
            validation_status_summary = self._str_param(validation_truth.get("validation_status_summary"), default="unknown", lower=True)
            validation_inconsistent = bool(validation_truth.get("validation_inconsistent") is True)
            validation_inconsistency_reasons = self._str_list(validation_truth.get("validation_inconsistency_reasons"))[:20]
            validation_truth_source = self._str_param(validation_truth.get("validation_truth_source"), default="")
            validation_command_count = self._coerce_int(validation_truth.get("validation_command_count"), 0)
            validation_failed_command_count = self._coerce_int(validation_truth.get("validation_failed_command_count"), 0)
            validation_command_records = bounded_validation_command_records(
                validation_truth.get("validation_command_records"),
                limit=50,
            )
            scope_status_summary = self._str_param(version_package.get("scope_status_summary"), default="unknown", lower=True)
            validation_sample = self._str_list(validation_truth.get("validation_sample"))[:5]
            validation_for_section = self._str_list(validation_truth.get("validation_results")) or validation_sample
            audit_package_id = self._str_param(version_package.get("audit_package_id"), default=f"version_auditpkg_{version}")
            evidence_obj = version_package.get("evidence_paths")
            evidence_paths_raw = evidence_obj if isinstance(evidence_obj, dict) else {}
            evidence_paths = {
                "json_file": self._str_param(evidence_paths_raw.get("selected_report_json_file"), default=""),
                "markdown_file": self._str_param(evidence_paths_raw.get("selected_report_markdown_file"), default=""),
                "log_file": "",
                "audit_file": self._str_param(evidence_paths_raw.get("version_audit_file"), default=""),
            }
            version_value = self._str_param(version_package.get("version"), default=version_value)
            version_name = self._str_param(version_package.get("version_name"), default=version_name)
            status_value = self._str_param(version_package.get("status"), default=status_value)
            package_role = self._str_param(version_package.get("package_role"), default="")
            commit_data = {
                "commit_hash": self._str_param(version_package.get("commit_hash"), default=""),
                "commit_hash_short": self._str_param(version_package.get("commit_hash_short"), default=""),
                "commit_message": self._str_param(version_package.get("commit_message"), default=""),
                "committed_at": self._str_param(version_package.get("committed_at"), default=""),
                "committed_files": self._str_list(version_package.get("committed_files"))[:200],
                "commit_head_before": self._str_param(version_package.get("commit_head_before"), default=""),
                "commit_head_after": self._str_param(version_package.get("commit_head_after"), default=""),
                "commit_metadata_status": self._str_param(version_package.get("commit_metadata_status"), default="unknown"),
            }
            source_kind = "version_refresh" if version_package_source == "version_refresh" else "version_materialized"
        else:
            materialized = None
            if report_id_value and not version:
                try:
                    materialized_ret = store.get_materialized_audit_package(report_id_value)
                    if materialized_ret.get("ok") and isinstance(materialized_ret.get("audit_package"), dict):
                        materialized = materialized_ret["audit_package"]
                except Exception:
                    materialized = None

            if isinstance(materialized, dict):
                for key in (
                    "run_id",
                    "preview_id",
                    "preview_claimed_at",
                    "preview_claim_status",
                    "prompt_file",
                    "prompt_sha256",
                    "prompt_sha256_status",
                ):
                    val = materialized.get(key)
                    if isinstance(val, str) and val.strip():
                        selected_lineage[key] = val.strip()[:200]
                changed_files = self._str_list(materialized.get("changed_files"))
                report_summary_obj = report.get("summary")
                report_summary_data = report_summary_obj if isinstance(report_summary_obj, dict) else {}
                validation_truth = self._extract_validation_truth(
                    materialized,
                    fallback_summary=report_summary_data,
                    executor_report_text=report_markdown_text,
                )
                validation_status_summary = self._str_param(validation_truth.get("validation_status_summary"), default="unknown", lower=True)
                validation_inconsistent = bool(validation_truth.get("validation_inconsistent") is True)
                validation_inconsistency_reasons = self._str_list(validation_truth.get("validation_inconsistency_reasons"))[:20]
                validation_truth_source = self._str_param(validation_truth.get("validation_truth_source"), default="")
                validation_command_count = self._coerce_int(validation_truth.get("validation_command_count"), 0)
                validation_failed_command_count = self._coerce_int(validation_truth.get("validation_failed_command_count"), 0)
                validation_command_records = bounded_validation_command_records(
                    validation_truth.get("validation_command_records"),
                    limit=50,
                )
                scope_status_summary = self._str_param(materialized.get("scope_status_summary"), default="unknown", lower=True)
                validation_sample = self._str_list(validation_truth.get("validation_sample"))[:5]
                validation_for_section = self._str_list(validation_truth.get("validation_results")) or validation_sample
                has_markdown = bool(self._str_param(report.get("markdown_file"), default=""))
                truncated = False
                audit_package_id = self._str_param(materialized.get("audit_package_id"), default=f"auditpkg_{report_id_value}")
                evidence_obj = materialized.get("evidence_paths")
                evidence_paths_raw = evidence_obj if isinstance(evidence_obj, dict) else {}
                evidence_paths = {
                    "json_file": self._str_param(evidence_paths_raw.get("json_file"), default=self._str_param(report.get("json_file"), default="")),
                    "markdown_file": self._str_param(evidence_paths_raw.get("markdown_file"), default=self._str_param(report.get("markdown_file"), default="")),
                    "log_file": self._str_param(evidence_paths_raw.get("log_file"), default=self._str_param(report.get("log_file"), default="")),
                    "audit_file": self._str_param(evidence_paths_raw.get("audit_file"), default=self._str_param(report.get("audit_file"), default="")),
                }
                version_value = self._str_param(materialized.get("version"), default=version_value)
                version_name = self._str_param(materialized.get("version_name"), default=version_name)
                provider_value = self._str_param(materialized.get("provider"), default=provider_value)
                execution_mode_value = self._str_param(materialized.get("execution_mode"), default=execution_mode_value)
                status_value = self._str_param(materialized.get("status"), default=status_value)
                started_at_value = self._str_param(materialized.get("started_at"), default=started_at_value)
                finished_at_value = self._str_param(materialized.get("finished_at"), default=finished_at_value)
                source_kind = "materialized"
            else:
                lineage_raw = report.get("execution_lineage")
                lineage_data = lineage_raw if isinstance(lineage_raw, dict) else {}
                for key in (
                    "run_id",
                    "preview_id",
                    "preview_claimed_at",
                    "preview_claim_status",
                    "prompt_file",
                    "prompt_sha256",
                    "prompt_sha256_status",
                ):
                    val = lineage_data.get(key)
                    if isinstance(val, str) and val.strip():
                        selected_lineage[key] = val.strip()[:200]
                changed_files = self._str_list(report.get("changed_files"))
                summary_obj = report.get("summary")
                summary_data = summary_obj if isinstance(summary_obj, dict) else {}
                validation_results = self._str_list(summary_data.get("validation_results"))
                validation_results_trimmed = [item[:500] for item in validation_results[:100]]
                validation_truth = self._extract_validation_truth(
                    summary_data,
                    fallback_summary=summary_data,
                    executor_report_text=report_markdown_text,
                )
                validation_status_summary = self._str_param(validation_truth.get("validation_status_summary"), default="unknown", lower=True)
                validation_inconsistent = bool(validation_truth.get("validation_inconsistent") is True)
                validation_inconsistency_reasons = self._str_list(validation_truth.get("validation_inconsistency_reasons"))[:20]
                validation_truth_source = self._str_param(validation_truth.get("validation_truth_source"), default="")
                validation_command_count = self._coerce_int(validation_truth.get("validation_command_count"), 0)
                validation_failed_command_count = self._coerce_int(validation_truth.get("validation_failed_command_count"), 0)
                validation_command_records = bounded_validation_command_records(
                    validation_truth.get("validation_command_records"),
                    limit=50,
                )
                scope_status_summary = self._summarize_scope(validation_results_trimmed)
                validation_sample = self._str_list(validation_truth.get("validation_sample"))[:5] or validation_results_trimmed[:5]
                validation_for_section = validation_results_trimmed
                has_markdown = bool(summary_data.get("executor_report_available"))
                truncated = bool(report_result.get("truncated", False))
                audit_package_id = f"auditpkg_{report_id_value}" if report_id_value else "auditpkg_unknown"
                evidence_paths = {
                    "json_file": self._str_param(report.get("json_file"), default=""),
                    "markdown_file": self._str_param(report.get("markdown_file"), default=""),
                    "log_file": self._str_param(report.get("log_file"), default=""),
                    "audit_file": self._str_param(report.get("audit_file"), default=""),
                }
                source_kind = "version_dynamic_report" if version else "dynamic_report"
            commit_hash = self._str_param(report.get("commit_head_after"), default="")
            commit_data = {
                "commit_hash": commit_hash,
                "commit_hash_short": commit_hash[:12] if commit_hash else "",
                "commit_message": "",
                "committed_at": "",
                "committed_files": changed_files[:200],
                "commit_head_before": self._str_param(report.get("commit_head_before"), default=""),
                "commit_head_after": commit_hash,
                "commit_metadata_status": "confirmed" if commit_hash else "unknown",
            }

        committed_files = self._str_list(commit_data.get("committed_files"))[:200]
        completion_evidence_summary = self._summarize_completion_evidence(report.get("completion_evidence"))

        package_summary = {
            "report_id": report_id_value,
            "version": version_value,
            "version_name": version_name,
            "provider": provider_value,
            "execution_mode": execution_mode_value,
            "status": status_value,
            "started_at": started_at_value,
            "finished_at": finished_at_value,
            "changed_files_count": len(changed_files),
            "validation_status_summary": validation_status_summary,
            "validation_inconsistent": validation_inconsistent,
            "validation_truth_source": validation_truth_source,
            "validation_command_count": validation_command_count,
            "validation_failed_command_count": validation_failed_command_count,
            "scope_status_summary": scope_status_summary,
            "completion_evidence_mode": completion_evidence_summary.get("mode", ""),
            "lineage_keys": sorted(selected_lineage.keys()),
            "has_report_markdown": has_markdown,
            "truncated": truncated,
            "package_role": package_role,
            "commit_hash_short": self._str_param(commit_data.get("commit_hash_short"), default=""),
            "commit_metadata_status": self._str_param(commit_data.get("commit_metadata_status"), default="unknown"),
            "committed_files_count": len(committed_files),
        }

        acceptance_summary = {
            "validation_results_count": len(validation_sample),
            "validation_status_summary": validation_status_summary,
            "validation_inconsistent": validation_inconsistent,
            "validation_inconsistency_reasons": validation_inconsistency_reasons,
            "validation_truth_source": validation_truth_source,
            "validation_command_count": validation_command_count,
            "validation_failed_command_count": validation_failed_command_count,
            "validation_command_records_sample": validation_command_records[:10],
            "sample_validation_results": validation_sample,
        }
        scope_available = scope_status_summary not in {"unknown", ""}
        scope_summary = {
            "available": scope_available,
            "scope_status_summary": scope_status_summary,
            "changed_files_count": len(changed_files),
            "changed_files_sample": changed_files[:20],
        }

        payload: dict[str, Any] = {
            "ok": True,
            "action": "get_audit_package",
            "audit_package_id": audit_package_id,
            "report_id": report_id_value,
            "version": version_value,
            "provider": provider_value,
            "execution_mode": execution_mode_value,
            "status": status_value,
            "summary": package_summary,
            "lineage": selected_lineage,
            "evidence_paths": evidence_paths,
            "changed_files": changed_files[:50],
            "acceptance_summary": acceptance_summary,
            "scope_summary": scope_summary,
            "completion_evidence": completion_evidence_summary,
            "recommended_next_reads": self._build_audit_recommended_next_reads(
                report_id_value,
                max_chars,
                version=version_value,
                selected_report_id=selected_lineage.get("selected_report_id", report_id_value),
            ),
            "source": source_kind,
            "section": section,
        }

        if section == "lineage":
            payload["lineage"] = selected_lineage
            payload["commit"] = {
                "commit_hash": self._str_param(commit_data.get("commit_hash"), default=""),
                "commit_hash_short": self._str_param(commit_data.get("commit_hash_short"), default=""),
                "commit_message": self._str_param(commit_data.get("commit_message"), default=""),
                "committed_at": self._str_param(commit_data.get("committed_at"), default=""),
                "committed_files": committed_files,
                "commit_head_before": self._str_param(commit_data.get("commit_head_before"), default=""),
                "commit_head_after": self._str_param(commit_data.get("commit_head_after"), default=""),
                "commit_metadata_status": self._str_param(commit_data.get("commit_metadata_status"), default="unknown"),
            }
            payload["changed_files"] = changed_files[:20]
        elif section == "validation":
            payload["validation"] = {
                "status": status_value,
                "validation_status_summary": validation_status_summary,
                "validation_inconsistent": validation_inconsistent,
                "validation_inconsistency_reasons": validation_inconsistency_reasons,
                "validation_truth_source": validation_truth_source,
                "validation_command_count": validation_command_count,
                "validation_failed_command_count": validation_failed_command_count,
                "validation_command_records": validation_command_records,
                "validation_command_records_truncated": validation_command_count > len(validation_command_records),
                "validation_results": validation_for_section[:50],
                "changed_files": changed_files[:20],
            }
        elif section == "scope":
            payload["scope"] = scope_summary
        elif section == "report_excerpt":
            if include_markdown:
                excerpt = ""
                excerpt_truncated = False
                if report_id_value:
                    refresh = store.get_report(
                        report_id=report_id_value,
                        latest=False,
                        include_markdown=True,
                        max_markdown_chars=max_chars,
                    )
                    if refresh.get("ok"):
                        excerpt = str(refresh.get("report_markdown") or "")
                        excerpt_truncated = bool(refresh.get("truncated", False))
                payload["report_excerpt"] = excerpt[:max_chars]
                payload["truncated"] = excerpt_truncated or len(excerpt) > max_chars
            else:
                payload["report_excerpt"] = ""
                payload["truncated"] = False
        return payload

    def _evaluate_loop_stop(
        self,
        *,
        classification: str,
        run_result: dict[str, Any],
        allow_fix: bool,
        allow_commit: bool,
        stop_on_acceptance_failure: bool,
        stop_on_scope_violation: bool,
        stop_on_diff_too_large: bool,
        total_diff_chars: int,
        max_total_diff_chars: int,
    ) -> dict[str, Any]:
        if classification == "executor_failed":
            return {"stop": True, "reason": "executor_failed", "blockers": ["EXECUTOR_FAILED"], "warnings": []}

        if classification == "blocked_scope_violation" and stop_on_scope_violation:
            return {"stop": True, "reason": "scope_violation", "blockers": ["SCOPE_VIOLATION"], "warnings": []}

        if classification == "failed_acceptance":
            if stop_on_acceptance_failure:
                return {"stop": True, "reason": "acceptance_failed", "blockers": ["FAILED_ACCEPTANCE"], "warnings": []}
            if not allow_fix:
                return {"stop": True, "reason": "acceptance_failed", "blockers": ["FAILED_ACCEPTANCE"], "warnings": []}

        if classification == "passed_with_changes":
            return {"stop": True, "reason": "passed_with_changes", "blockers": [], "warnings": []}

        changed_files = self._str_list(run_result.get("changed_files"))
        if changed_files and classification != "passed_with_changes":
            return {"stop": True, "reason": "dirty_worktree_unexpected", "blockers": ["UNEXPECTED_CHANGED_FILES"], "warnings": []}

        if stop_on_diff_too_large and total_diff_chars > max_total_diff_chars:
            return {"stop": True, "reason": "diff_too_large", "blockers": ["DIFF_TOO_LARGE"], "warnings": []}

        latest_report_id = run_result.get("latest_report_id")
        report_summary = run_result.get("report_summary")
        if not latest_report_id or not isinstance(report_summary, dict) or not report_summary:
            return {"stop": True, "reason": "report_missing", "blockers": ["REPORT_MISSING"], "warnings": []}

        if run_result.get("runner_status") == "BLOCKED_BY_MAX_FIX_ATTEMPTS":
            return {"stop": True, "reason": "max_fix_attempts", "blockers": ["MAX_FIX_ATTEMPTS"], "warnings": []}

        if allow_commit and classification == "passed_with_changes":
            return {"stop": True, "reason": "passed_with_changes", "blockers": [], "warnings": ["allow_commit_only_preview"]}

        return {"stop": False, "reason": "continue", "blockers": [], "warnings": []}

    def _build_bounded_next_actions(self, *, classification: str, provider: str, allow_commit: bool) -> list[dict[str, Any]]:
        if classification == "passed_with_changes":
            actions = [
                {
                    "tool": "manage_git_commit",
                    "action": "readiness",
                    "params": {"action": "readiness", "include_diff_summary": True},
                    "reason": "先审查 diff 和提交阻断项。",
                    "requires_confirmation": False,
                }
            ]
            if allow_commit:
                actions.append({
                    "tool": "manage_git_commit",
                    "action": "commit_workflow_preview",
                    "params": {"action": "commit_workflow_preview", "scope_hint": "bounded_loop"},
                    "reason": "允许生成 commit preview，但不执行 commit。",
                    "requires_confirmation": True,
                })
            else:
                actions.append({
                    "tool": "run_mcp_workflow",
                    "action": "git_commit.preview",
                    "params": {"workflow": "git_commit", "phase": "preview"},
                    "reason": "生成受控提交预览。",
                    "requires_confirmation": True,
                })
            return actions
        if classification == "failed_acceptance":
            return [{
                "tool": "get_executor_run_report",
                "action": "latest",
                "params": {"latest": True, "include_markdown": True},
                "reason": "读取报告并手动准备 fix 流程。",
                "requires_confirmation": False,
            }]
        if classification == "blocked_scope_violation":
            return [{
                "tool": "get_review_context",
                "action": "inspect_scope",
                "params": {"include_log": True, "include_repo_overview": False},
                "reason": "审查 scope violation 后再继续。",
                "requires_confirmation": False,
            }]
        if classification == "executor_failed":
            return [{
                "tool": "manage_executor_workflow",
                "action": "preflight",
                "params": {"action": "preflight", "provider": provider},
                "reason": "修复执行器安装/鉴权/配置后再重试。",
                "requires_confirmation": False,
            }]
        return [{
            "tool": "run_mcp_workflow",
            "action": "project_status.inspect",
            "params": {"workflow": "project_status", "phase": "inspect"},
            "reason": "查看当前 Runner 状态。",
            "requires_confirmation": False,
        }]

    def _can_run_fix_next(self) -> bool:
        state_file = resolve_project_runner_path(self.project_root, "state.json")
        fix_prompt_file = resolve_project_runner_path(self.project_root, "runtime", "current-fix-prompt.md")
        if not os.path.isfile(state_file):
            return False
        try:
            with open(state_file, "r", encoding="utf-8") as handle:
                state = json.load(handle)
        except Exception:
            return False
        status = state.get("status") if isinstance(state, dict) else ""
        return status == "FIX_PROMPT_READY" and os.path.isfile(fix_prompt_file)

    def _provider_available(self, inventory: Any, provider: str) -> bool:
        if not isinstance(inventory, dict):
            return True
        if not inventory.get("ok"):
            return True
        providers = inventory.get("providers")
        if isinstance(providers, list):
            for p in providers:
                if isinstance(p, dict) and p.get("provider") == provider:
                    return bool(p.get("available", False))
        current_provider_available = inventory.get("current_provider_available")
        if isinstance(current_provider_available, bool):
            return current_provider_available
        return True

    def _build_executor_session_affinity(
        self,
        *,
        provider: str,
        session_record: dict[str, Any],
        continuation_decision: dict[str, Any],
    ) -> dict[str, Any]:
        will_resume = bool(continuation_decision.get("decision") == "resume_auto_eligible" and continuation_decision.get("should_resume") is True)
        resume_identity_present = bool(continuation_decision.get("resume_identity_present") is True)
        resume_identity_kind = continuation_decision.get("resume_identity_kind")
        resume_source_version = session_record.get("version") if isinstance(session_record.get("version"), str) else None
        resume_source_provider = session_record.get("provider") if isinstance(session_record.get("provider"), str) else None
        start_new_reason = None if will_resume else str(continuation_decision.get("decision_reason") or "not_resume_auto_eligible")
        resume_reason = str(continuation_decision.get("decision_reason") or "resume_auto_eligible") if will_resume else None
        return {
            "will_resume_session": will_resume,
            "will_start_new_session": not will_resume,
            "resume_provider": resume_source_provider if will_resume else provider,
            "resume_identity_kind": resume_identity_kind,
            "resume_identity_present": resume_identity_present,
            "resume_source_version": resume_source_version,
            "resume_reason": resume_reason,
            "start_new_reason": start_new_reason,
            "cache_affinity_expected": will_resume and resume_identity_present,
            "message": "下一次 run_once 预计会续接上一轮执行器会话，有利于连续任务缓存命中（GPTs 可最终决策）。" if will_resume else "下一次 run_once 预计会开启新执行器会话；不会命中上一轮对话缓存（可手动指定 resume_existing 以优先缓存命中）。",
        }

    def _compact_continuation_decision(self, decision: Any) -> dict[str, Any]:
        if not isinstance(decision, dict):
            return {}
        return {
            "ok": decision.get("ok"),
            "decision": decision.get("decision"),
            "decision_reason": decision.get("decision_reason"),
            "should_start_new": decision.get("should_start_new"),
            "should_resume": decision.get("should_resume"),
            "next_action_hint": decision.get("next_action_hint"),
            "risk_level": decision.get("risk_level"),
            "hard_blockers": self._str_list(decision.get("hard_blockers")),
            "resume_blockers": self._str_list(decision.get("resume_blockers")),
            "risk_warnings": self._str_list(decision.get("risk_warnings")),
            "resume_warnings": self._str_list(decision.get("resume_warnings")),
            "continuation_available": decision.get("continuation_available"),
            "provider_resume_supported": decision.get("provider_resume_supported"),
            "session_resume_available": decision.get("session_resume_available"),
            "resume_identity_kind": decision.get("resume_identity_kind", decision.get("identity_kind")),
            "resume_identity_present": decision.get("resume_identity_present"),
            "conversation_identity_present": decision.get("conversation_identity_present"),
            "decision_owner": decision.get("decision_owner"),
            "optimization_goal": decision.get("optimization_goal"),
            "recommended_default": decision.get("recommended_default"),
            "cache_hit_preference": decision.get("cache_hit_preference"),
            "context_facts": decision.get("context_facts"),
        }

    def _compact_resume_preview(self, preview: Any) -> dict[str, Any]:
        if not isinstance(preview, dict):
            return {}
        return {
            "ok": preview.get("ok"),
            "command_name": preview.get("command_name"),
            "resume_invocation_supported": preview.get("resume_invocation_supported"),
            "resume_invocation_verified": preview.get("resume_invocation_verified"),
            "hard_blockers": self._str_list(preview.get("hard_blockers")),
            "risk_level": preview.get("risk_level"),
        }

    def _validate_preview_artifact(
        self,
        preview_id: str,
        artifact: dict[str, Any],
        provider: str,
        execution_mode: str,
    ) -> dict[str, Any]:
        guard_error = self._preview_guard_error(
            "run_once",
            preview_id,
            artifact,
            expired_message="preview_id 已过期。请重新调用 run_once_preview。",
        )
        if guard_error is not None:
            return guard_error

        provider_validation = self._confirmation.validate_provider(artifact, provider)
        if not provider_validation.get("ok"):
            artifact_provider = artifact.get("provider", "")
            return self._error(
                "run_once",
                "PROVIDER_MISMATCH",
                f"provider 不匹配。preview 中记录的是 {artifact_provider}，但请求的是 {provider}。",
            )

        mode_validation = self._confirmation.validate_execution_mode(artifact, execution_mode)
        if not mode_validation.get("ok"):
            artifact_execution_mode = artifact.get("execution_mode", "run")
            return self._error(
                "run_once",
                "EXECUTION_MODE_MISMATCH",
                f"execution_mode 不匹配。preview 中记录的是 {artifact_execution_mode}，但请求的是 {execution_mode}。",
            )

        return {"ok": True}

    def _preview_guard_error(
        self,
        action: str,
        preview_id: str,
        artifact: dict[str, Any],
        *,
        expired_message: str,
    ) -> dict[str, Any] | None:
        guard = self._confirmation.guard(preview_id, payload=artifact)
        if guard.get("ok"):
            return None
        error_code = str(guard.get("error_code") or "PREVIEW_NOT_FOUND")
        if error_code == "PREVIEW_EXPIRED":
            self._delete_preview_artifact(preview_id)
            return self._error(action, "PREVIEW_EXPIRED", expired_message)
        if error_code == "PROJECT_MISMATCH":
            return self._error(action, "PROJECT_MISMATCH", "preview 与当前项目不匹配。")
        return self._error(action, error_code, "preview_id 不存在或已过期。")

    def _compare_artifact_with_preflight(self, artifact: dict[str, Any], preflight: dict[str, Any]) -> dict[str, Any]:
        checks: list[tuple[str, str, str]] = [
            ("current_head", "HEAD_MISMATCH", "HEAD 已变化。"),
            ("current_branch", "BRANCH_MISMATCH", "分支已变化。"),
            ("current_version", "CURRENT_VERSION_MISMATCH", "current_version 已变化。"),
            ("current_version_index", "CURRENT_VERSION_INDEX_MISMATCH", "current_version_index 已变化。"),
            ("runner_status", "RUNNER_STATUS_MISMATCH", "runner_status 已变化。"),
            ("provider", "PROVIDER_MISMATCH", "provider 已变化。"),
            ("execution_mode", "EXECUTION_MODE_MISMATCH", "execution_mode 已变化。"),
            ("execution_branch_status", "EXECUTION_BRANCH_STATUS_MISMATCH", "execution branch 状态已变化。"),
        ]
        for field, code, message in checks:
            preview_val = artifact.get(field)
            current_val = preflight.get(field)
            if preview_val != current_val:
                return self._error("run_once", code, f"{message} preview={preview_val!r} current={current_val!r}")
        return {"ok": True}

    def _compare_bounded_artifact_with_preflight(self, artifact: dict[str, Any], preflight: dict[str, Any]) -> dict[str, Any]:
        checks: list[tuple[str, str, str]] = [
            ("current_head", "HEAD_MISMATCH", "HEAD 已变化。"),
            ("current_branch", "BRANCH_MISMATCH", "分支已变化。"),
            ("current_version", "CURRENT_VERSION_MISMATCH", "current_version 已变化。"),
            ("current_version_index", "CURRENT_VERSION_INDEX_MISMATCH", "current_version_index 已变化。"),
            ("runner_status", "RUNNER_STATUS_MISMATCH", "runner_status 已变化。"),
            ("provider", "PROVIDER_MISMATCH", "provider 已变化。"),
            ("execution_branch_status", "EXECUTION_BRANCH_STATUS_MISMATCH", "execution branch 状态已变化。"),
            ("blocking_git_status_short", "GIT_STATUS_MISMATCH", "blocking_git_status_short 已变化。"),
        ]
        for field, code, message in checks:
            preview_val = artifact.get(field)
            current_val = preflight.get(field)
            if preview_val != current_val:
                return self._error("run_bounded", code, f"{message} preview={preview_val!r} current={current_val!r}")
        return {"ok": True}

    def _bounded_blocked_result(
        self,
        *,
        preview_id: str,
        provider: str,
        max_iterations: int,
        trusted_mode: bool,
        allow_fix: bool,
        allow_commit: bool,
        reason: str,
        message: str,
        blocks: list[dict[str, Any]],
        warnings: list[str],
    ) -> dict[str, Any]:
        return {
            "ok": False,
            "action": "run_bounded",
            "status": "blocked",
            "risk_level": "blocked",
            "preview_id": preview_id,
            "provider": provider,
            "max_iterations": max_iterations,
            "iterations_requested": max_iterations,
            "iterations_completed": 0,
            "stopped": True,
            "stop_reason": reason,
            "stop_conditions_triggered": [reason],
            "loop_summary": {
                "trusted_mode": trusted_mode,
                "allow_fix": allow_fix,
                "allow_commit": allow_commit,
            },
            "iteration_results": [],
            "classification": "blocked_preflight",
            "next_actions": [{
                "tool": "manage_executor_workflow",
                "action": "preflight",
                "params": {"action": "preflight", "provider": provider},
                "reason": "先修复阻断项再重试。",
                "requires_confirmation": False,
            }],
            "blockers": [b.get("code", "") for b in blocks if isinstance(b, dict)],
            "warnings": warnings,
            "message": message,
            "error_code": "PREFLIGHT_BLOCKED",
        }

    def _generate_preview_key(self, prefix: str) -> str:
        return self._confirmation.create_id(prefix)

    def _generate_run_id(self) -> str:
        return self._claims.create_run_id()

    def _claim_preview_artifact(
        self,
        *,
        action: str,
        preview_id: str,
        artifact: dict[str, Any],
        provider: str,
        execution_mode: str,
    ) -> dict[str, Any]:
        claim_result = self._claims.acquire_claim(
            preview_id=preview_id,
            artifact=artifact,
            provider=provider,
            execution_mode=execution_mode,
        )
        if claim_result.get("ok"):
            return {
                "ok": True,
                "run_id": claim_result.get("run_id", ""),
                "claimed_at": claim_result.get("claimed_at", ""),
                "preview_claim_status": "RUNNING",
            }
        if claim_result.get("error_code") == "CLAIM_EXISTS":
            return self._already_claimed_error(action, preview_id, claim_result.get("claim") or {})
        return self._error(action, "PREVIEW_CLAIM_FAILED", "preview claim 失败。")

    def _finalize_preview_claim(
        self,
        *,
        preview_id: str,
        run_id: str,
        final_status: str,
        report_id: str = "",
        error_code: str = "",
        message: str = "",
        exception_type: str = "",
        blockers: list[str] | None = None,
        warnings: list[str] | None = None,
    ) -> None:
        self._claims.finalize_claim(
            preview_id=preview_id,
            run_id=run_id,
            final_status=final_status,
            report_id=report_id,
            error_code=error_code,
            message=message,
            exception_type=exception_type,
            blockers=blockers,
            warnings=warnings,
        )

    def _mark_claim_worker_started(
        self,
        *,
        preview_id: str,
        run_id: str,
        thread_started_at: str,
        worker_pid: int,
        heartbeat_interval_seconds: int,
    ) -> None:
        self._claims.mark_worker_started(
            preview_id=preview_id,
            run_id=run_id,
            thread_started_at=thread_started_at,
            worker_pid=worker_pid,
            heartbeat_interval_seconds=heartbeat_interval_seconds,
        )

    def _refresh_claim_heartbeat(
        self,
        *,
        preview_id: str,
        run_id: str,
        error_state: dict[str, Any] | None = None,
    ) -> bool:
        return self._claims.refresh_heartbeat(
            preview_id=preview_id,
            run_id=run_id,
            error_state=error_state,
        )

    def _evaluate_orphaned_claim(self, claim: dict[str, Any]) -> dict[str, Any]:
        return self._claims.evaluate_orphaned_claim(claim)

    def _resolve_possible_report_id(self, claim: dict[str, Any]) -> str:
        report_id = str(claim.get("report_id") or "").strip()
        if report_id:
            return report_id
        version = str(claim.get("current_version") or "").strip()
        store = ExecutorRunReportStore(self.project_root)
        try:
            version_reports = store.list_reports(version=version, limit=1) if version else []
            if version_reports:
                candidate = str(version_reports[0].get("report_id") or "").strip()
                if candidate:
                    return candidate
            reports = store.list_reports(limit=1)
            if reports:
                candidate = str(reports[0].get("report_id") or "").strip()
                if candidate:
                    return candidate
        except Exception:
            return ""
        return ""

    def _heartbeat_timeout_seconds(self, interval_seconds: int) -> int:
        return self._claims.heartbeat_timeout_seconds(interval_seconds)

    def _claim_record_path(self, preview_id: str) -> str:
        return self._claims.claim_record_path(preview_id)

    def _read_preview_claim_record(self, preview_id: str) -> dict[str, Any] | None:
        return self._claims.read_claim(preview_id)

    def _already_claimed_error(self, action: str, preview_id: str, claim: dict[str, Any]) -> dict[str, Any]:
        orphan_info = self._evaluate_orphaned_claim(claim)
        possible_report_id = self._resolve_possible_report_id(claim) if orphan_info.get("orphaned") else ""
        return already_claimed_error(
            action=action,
            preview_id=preview_id,
            claim=claim,
            orphan_info=orphan_info,
            possible_report_id=possible_report_id,
        )

    def _write_preview_artifact(self, preview_key: str, artifact: dict[str, Any]) -> None:
        self._confirmation.write_artifact(preview_key, artifact)

    def _read_preview_artifact(self, preview_key: str) -> dict[str, Any] | None:
        return self._confirmation.read_artifact(preview_key)

    def _delete_preview_artifact(self, preview_key: str) -> None:
        self._confirmation.delete_artifact(preview_key)

    def _now_iso(self) -> str:
        return _shared_now_iso()

    def _now_iso_ts(self, add_seconds: int = 0) -> str:
        return (datetime.now(timezone.utc) + timedelta(seconds=add_seconds)).astimezone().isoformat()

    def _str_param(self, value: Any, default: str, lower: bool = False) -> str:
        if isinstance(value, str) and value.strip():
            normalized = value.strip()
            return normalized.lower() if lower else normalized
        return default

    def _bool_param(self, value: Any, default: bool) -> bool:
        if isinstance(value, bool):
            return value
        return default

    def _bounded_int_param(self, value: Any, *, default: int, minimum: int, maximum: int) -> int:
        return bounded_int(value, default=default, minimum=minimum, maximum=maximum)

    def _coerce_int(self, value: Any, default: int) -> int:
        try:
            return int(value)
        except Exception:
            return default

    def _str_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item) for item in value if isinstance(item, str) and item]

    def _safe_read_project_text(self, path: str) -> str:
        candidate = str(path or "").strip()
        if not candidate:
            return ""
        try:
            root = os.path.realpath(self.project_root)
            target = os.path.realpath(candidate)
            if not (target == root or target.startswith(root + os.sep)):
                return ""
            if not os.path.isfile(target):
                return ""
            with open(target, "r", encoding="utf-8") as handle:
                return handle.read()
        except Exception:
            return ""

    def _parse_iso_datetime(self, value: str) -> datetime | None:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            return parse_iso_datetime(text)
        except Exception:
            return None

    def _summarize_completion_evidence(self, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        result: dict[str, Any] = {
            "mode": self._str_param(value.get("mode"), default=""),
            "provider": self._str_param(value.get("provider"), default=""),
            "version": self._str_param(value.get("version"), default=""),
            "executor_changed_files": self._str_list(value.get("executor_changed_files"))[:50],
        }
        notes = self._str_list(value.get("notes"))[:20]
        if notes:
            result["notes"] = notes
        validation_commands = value.get("validation_commands")
        if isinstance(validation_commands, list):
            result["validation_command_count"] = len(validation_commands)
        return {k: v for k, v in result.items() if v not in ("", [], None)}

    def _extract_validation_truth(
        self,
        source: dict[str, Any] | None,
        *,
        fallback_summary: dict[str, Any] | None = None,
        executor_report_text: str | None = None,
    ) -> dict[str, Any]:
        source_obj = source if isinstance(source, dict) else {}
        fallback_obj = fallback_summary if isinstance(fallback_summary, dict) else {}
        source_records = bounded_validation_command_records(source_obj.get("validation_command_records"), limit=100)
        fallback_records = bounded_validation_command_records(fallback_obj.get("validation_command_records"), limit=100)
        records = source_records or fallback_records
        validation_results = self._str_list(fallback_obj.get("validation_results"))
        if not validation_results:
            validation_results = self._str_list(source_obj.get("validation_sample"))
        truth = validation_truth_from_summary({
            "validation_results": validation_results,
            "validation_command_records": records,
        }, executor_report_text=executor_report_text or "")
        source_status = self._str_param(source_obj.get("validation_status_summary"), default="", lower=True)
        status = source_status or self._str_param(truth.get("validation_status_summary"), default="unknown", lower=True)
        truth_status = self._str_param(truth.get("validation_status_summary"), default="unknown", lower=True)
        if truth_status in {"failed", "inconsistent"}:
            status = truth_status
        source_inconsistent = bool(source_obj.get("validation_inconsistent") is True)
        validation_inconsistent = source_inconsistent or bool(truth.get("validation_inconsistent") is True)
        if validation_inconsistent and status == "passed":
            status = "inconsistent"
        reasons = self._str_list(source_obj.get("validation_inconsistency_reasons"))
        if not reasons:
            reasons = self._str_list(truth.get("validation_inconsistency_reasons"))
        validation_sample = self._str_list(source_obj.get("validation_sample"))
        if not validation_sample:
            validation_sample = self._str_list(truth.get("validation_sample"))
        truth_records = bounded_validation_command_records(
            truth.get("validation_command_records"),
            limit=100,
        )
        truth_command_count = int(truth.get("validation_command_count", len(records)) or len(records))
        truth_failed_count = int(truth.get("validation_failed_command_count", 0) or 0)
        source_command_count = self._coerce_int(source_obj.get("validation_command_count"), truth_command_count)
        source_failed_count = self._coerce_int(source_obj.get("validation_failed_command_count"), truth_failed_count)
        return {
            "validation_status_summary": status or "unknown",
            "validation_inconsistent": validation_inconsistent,
            "validation_inconsistency_reasons": reasons[:20],
            "validation_truth_source": self._str_param(
                source_obj.get("validation_truth_source"),
                default=self._str_param(truth.get("validation_truth_source"), default=""),
            ),
            "validation_command_count": max(source_command_count, truth_command_count, len(records)),
            "validation_failed_command_count": max(source_failed_count, truth_failed_count),
            "validation_command_records": truth_records,
            "validation_sample": validation_sample[:5],
            "validation_results": validation_results[:100],
        }

    def _summarize_validation(self, results: list[str]) -> str:
        return summarize_legacy_validation_results(results)

    def _summarize_scope(self, results: list[str]) -> str:
        scope_lines = [item for item in results if item.startswith("Scope check:")]
        if not scope_lines:
            return "unknown"
        last = scope_lines[-1].split(":", 1)[-1].strip().upper()
        if last in {"PASSED", "NOT_CHECKED"}:
            return "ok"
        if last in {"FAILED", "BLOCKED", "VIOLATION"}:
            return "blocked"
        return last.lower() if last else "unknown"

    def _build_audit_recommended_next_reads(
        self,
        report_id: str,
        max_chars: int,
        *,
        version: str = "",
        selected_report_id: str = "",
    ) -> list[dict[str, Any]]:
        bounded_chars = min(max_chars, 20000)
        report_params_small: dict[str, Any] = {"latest": True, "include_markdown": False}
        report_params_md: dict[str, Any] = {"latest": True, "include_markdown": True, "max_markdown_chars": min(5000, bounded_chars)}
        if report_id:
            report_params_small = {"report_id": report_id, "include_markdown": False}
            report_params_md = {"report_id": report_id, "include_markdown": True, "max_markdown_chars": min(5000, bounded_chars)}
        elif version:
            report_params_small = {"version": version, "latest": True, "include_markdown": False}
            report_params_md = {"version": version, "latest": True, "include_markdown": True, "max_markdown_chars": min(5000, bounded_chars)}
        lineage_params: dict[str, Any] = {"action": "get_audit_package", "section": "lineage", "latest": not bool(report_id or version)}
        if report_id:
            lineage_params["report_id"] = report_id
        if version:
            lineage_params["version"] = version
        target_report_id = selected_report_id or report_id
        selected_report_params = {"report_id": target_report_id, "include_markdown": False} if target_report_id else report_params_small
        items = [
            {"tool": "manage_executor_workflow", "params": lineage_params},
            {"tool": "get_executor_run_report", "params": selected_report_params},
            {"tool": "get_executor_run_report", "params": report_params_small},
            {"tool": "get_git_diff", "params": {"mode": "summary"}},
            {"tool": "get_git_diff", "params": {"mode": "page", "offset": 0, "max_chars": min(30000, bounded_chars)}},
            {"tool": "get_executor_run_report", "params": report_params_md},
        ]
        if version:
            items.insert(1, {"tool": "manage_executor_workflow", "params": {"action": "refresh_audit_package", "version": version}})
        return items

    def _error(self, action: str, error_code: str, message: str) -> dict[str, Any]:
        return {
            "ok": False,
            "action": action,
            "status": "failed",
            "risk_level": "commit",
            "error_code": error_code,
            "message": message,
        }
