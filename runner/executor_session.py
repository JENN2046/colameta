from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from runner._internal_utils import now_iso as _now_iso, run_git as _run_git_base

if TYPE_CHECKING:
    from runner.development_target import ResolvedDevelopmentTarget


def _normalize_executor_identity_str(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    return ""


def _executor_identity_label(identity_kind: str) -> str:
    if identity_kind in {"conversation_id", "session_id", "session_file"}:
        return identity_kind
    return "会话标识"


def _infer_executor_identity_kind(provider: str) -> str:
    normalized = _normalize_executor_identity_str(provider).lower()
    if normalized == "codex":
        return "conversation_id"
    if normalized == "pi":
        return "session_id"
    return "executor_identity"


def select_executor_identity_for_display(
    *,
    run_identity: dict[str, Any] | None = None,
    session_record: dict[str, Any] | None = None,
    provider: str | None = None,
    fallback_value: str | None = None,
) -> dict[str, Any]:
    run = run_identity if isinstance(run_identity, dict) else {}
    record = session_record if isinstance(session_record, dict) else {}
    claim = run.get("claim") if isinstance(run.get("claim"), dict) else {}
    report = run.get("report") if isinstance(run.get("report"), dict) else {}
    lineage = report.get("execution_lineage") if isinstance(report.get("execution_lineage"), dict) else {}

    candidates: list[tuple[str, str, str]] = []

    def push(value: Any, identity_kind: str, source: str) -> None:
        normalized = _normalize_executor_identity_str(value)
        if normalized:
            candidates.append((normalized, identity_kind, source))

    push(run.get("conversation_id"), "conversation_id", "current_run")
    push(claim.get("conversation_id"), "conversation_id", "current_run")
    push(lineage.get("conversation_id"), "conversation_id", "current_run")
    push(record.get("conversation_id"), "conversation_id", "executor_session")
    push(run.get("session_id"), "session_id", "current_run")
    push(claim.get("session_id"), "session_id", "current_run")
    push(lineage.get("session_id"), "session_id", "current_run")
    push(record.get("session_id"), "session_id", "executor_session")
    push(run.get("session_file"), "session_file", "current_run")
    push(claim.get("session_file"), "session_file", "current_run")
    push(lineage.get("session_file"), "session_file", "current_run")
    push(record.get("session_file"), "session_file", "executor_session")

    if candidates:
        value, identity_kind, source = candidates[0]
        return {
            "identity_present": True,
            "identity_value": value,
            "identity_kind": identity_kind,
            "identity_label": _executor_identity_label(identity_kind),
            "identity_source": source,
        }

    normalized_fallback = _normalize_executor_identity_str(fallback_value)
    if normalized_fallback:
        inferred_kind = _infer_executor_identity_kind(
            _normalize_executor_identity_str(provider)
            or _normalize_executor_identity_str(record.get("provider"))
            or _normalize_executor_identity_str(claim.get("provider"))
        )
        return {
            "identity_present": True,
            "identity_value": normalized_fallback,
            "identity_kind": inferred_kind,
            "identity_label": _executor_identity_label(inferred_kind),
            "identity_source": "live_snapshot",
        }

    return {
        "identity_present": False,
        "identity_value": "",
        "identity_kind": "",
        "identity_label": "会话标识",
        "identity_source": "absent",
    }


@dataclass
class ExecutorSessionRecord:
    active: bool
    provider: str
    project_root: str
    project_name: str | None
    git_branch: str | None
    base_head: str | None
    current_head: str | None
    version: str
    execution_mode: str
    attempt: int
    session_id: str | None
    session_file: str | None
    conversation_id: str | None
    resume_supported: bool
    resume_enabled: bool
    log_path: str | None
    summary_path: str | None
    created_at: str
    updated_at: str
    source: str


class ExecutorSessionStore:
    def __init__(self, project_root: str, target: "ResolvedDevelopmentTarget | None" = None):
        self.project_root = os.path.abspath(os.path.expanduser(project_root))
        if target is None:
            target = self._resolve_default_target()
        if target is not None:
            self.runner_dir = target.runner_dir
            self.runtime_dir = target.runtime_dir
            self.manifest_file = target.executor_session_manifest_path
        else:
            self.runner_dir = resolve_project_runner_dir(self.project_root)
            self.runtime_dir = os.path.join(self.runner_dir, "runtime")
            self.manifest_file = os.path.join(self.runtime_dir, "executor-session.json")

    def _resolve_default_target(self) -> "ResolvedDevelopmentTarget | None":
        try:
            from runner.development_target import resolve_development_target

            target = resolve_development_target(self.project_root)
            if os.path.exists(target.plan_file) or os.path.exists(target.state_file):
                return target
        except Exception:
            return None
        return None

    def get_status(self) -> dict[str, Any]:
        git_branch, current_head, warnings = self._get_current_git_context()
        git_context_available = git_branch is not None and current_head is not None
        if not os.path.exists(self.manifest_file):
            eligibility = self.evaluate_resume_eligibility(
                record=None,
                git_branch=git_branch,
                current_head=current_head,
            )
            result = {
                "ok": True,
                "active": False,
                "manifest_file": self.manifest_file,
                "message": "当前没有执行器会话记录。",
                "eligibility": eligibility,
            }
            if warnings:
                result["warnings"] = warnings
            return result

        record = self._load_manifest()
        if not isinstance(record, dict):
            eligibility = self._new_eligibility()
            eligibility["resume_blockers"].append("session_manifest_invalid")
            if not git_context_available:
                if git_branch is None:
                    eligibility["resume_warnings"].append("current_branch_unavailable")
                    eligibility["risk_warnings"].append("current_branch_unavailable")
                if current_head is None:
                    eligibility["resume_warnings"].append("current_head_unavailable")
                    eligibility["risk_warnings"].append("current_head_unavailable")
            eligibility = self._finalize_continuation_decision(eligibility)
            return {
                "ok": True,
                "active": False,
                "manifest_file": self.manifest_file,
                "error_code": "MANIFEST_INVALID",
                "message": "执行器会话记录格式无效。",
                "eligibility": eligibility,
            }

        recorded_project = record.get("project_root")
        recorded_branch = record.get("git_branch")
        recorded_head = record.get("current_head")
        matches_current_project = (
            isinstance(recorded_project, str)
            and os.path.abspath(recorded_project) == self.project_root
        )
        matches_current_branch = (
            isinstance(recorded_branch, str)
            and isinstance(git_branch, str)
            and recorded_branch == git_branch
        )
        matches_current_head = (
            isinstance(recorded_head, str)
            and isinstance(current_head, str)
            and recorded_head == current_head
        )
        eligibility = self.evaluate_resume_eligibility(
            record=record,
            git_branch=git_branch,
            current_head=current_head,
        )

        result = {
            "ok": True,
            "active": bool(record.get("active", False)),
            "manifest_file": self.manifest_file,
            "record": record,
            "current_project_root": self.project_root,
            "current_git_branch": git_branch,
            "current_head": current_head,
            "matches_current_project": matches_current_project,
            "matches_current_branch": matches_current_branch,
            "matches_current_head": matches_current_head,
            "eligibility": eligibility,
        }
        if warnings:
            result["warnings"] = warnings
        return result

    def evaluate_resume_eligibility(
        self,
        record: dict[str, Any] | None,
        git_branch: str | None,
        current_head: str | None,
    ) -> dict[str, Any]:
        eligibility = self._new_eligibility()
        if git_branch is None:
            eligibility["resume_warnings"].append("current_branch_unavailable")
            eligibility["risk_warnings"].append("current_branch_unavailable")
        if current_head is None:
            eligibility["resume_warnings"].append("current_head_unavailable")
            eligibility["risk_warnings"].append("current_head_unavailable")

        if record is None:
            eligibility["resume_blockers"].append("no_session_manifest")
            return self._finalize_continuation_decision(eligibility)

        provider = self._normalize_optional_str(record.get("provider"))
        if provider:
            provider = provider.lower()
        version = self._normalize_optional_str(record.get("version"))
        execution_mode = self._normalize_optional_str(record.get("execution_mode"))
        session_id = self._normalize_optional_str(record.get("session_id"))
        session_file = self._normalize_optional_str(record.get("session_file"))
        conversation_id = self._normalize_optional_str(record.get("conversation_id"))
        resume_enabled = bool(record.get("resume_enabled", False))
        active = bool(record.get("active", False))
        recorded_project = self._normalize_optional_str(record.get("project_root"))
        recorded_branch = self._normalize_optional_str(record.get("git_branch"))
        recorded_head = self._normalize_optional_str(record.get("current_head"))

        eligibility["resume_candidate_provider"] = provider
        eligibility["resume_candidate_version"] = version
        eligibility["resume_candidate_execution_mode"] = execution_mode
        eligibility["resume_candidate_session_id_present"] = bool(session_id)
        eligibility["resume_candidate_session_file_present"] = bool(session_file)
        eligibility["resume_candidate_conversation_id_present"] = bool(conversation_id)

        if not active:
            eligibility["resume_blockers"].append("session_manifest_inactive")
        if recorded_project and os.path.abspath(recorded_project) != self.project_root:
            eligibility["resume_blockers"].append("project_mismatch")
        if (
            recorded_branch is not None
            and git_branch is not None
            and recorded_branch != git_branch
        ):
            eligibility["resume_blockers"].append("branch_mismatch")
            eligibility["resume_warnings"].append("branch_mismatch")
            eligibility["risk_warnings"].append("branch_mismatch")
        if (
            recorded_head is not None
            and current_head is not None
            and recorded_head != current_head
        ):
            eligibility["resume_blockers"].append("head_mismatch")
            eligibility["resume_warnings"].append("head_mismatch")
            eligibility["risk_warnings"].append("head_mismatch")
        diagnostics = self._build_resume_diagnostics(
            provider=provider,
            active=active,
            session_id=session_id,
            session_file=session_file,
            conversation_id=conversation_id,
        )
        eligibility["resume_blockers"].extend(diagnostics.get("resume_blockers", []))
        eligibility["provider_resume_supported"] = bool(diagnostics.get("provider_resume_supported") is True)
        eligibility["session_resume_available"] = bool(diagnostics.get("session_resume_available") is True)
        eligibility["resume_identity_kind"] = diagnostics.get("resume_identity_kind")
        eligibility["resume_identity_present"] = bool(diagnostics.get("resume_identity_present") is True)
        eligibility["conversation_identity_present"] = bool(diagnostics.get("conversation_identity_present") is True)
        if not resume_enabled:
            eligibility["resume_warnings"].append("resume_enabled_false_currently_expected")

        if (
            not eligibility["resume_blockers"]
            and eligibility.get("session_resume_available") is True
        ):
            eligibility["resume_eligible"] = True
        return self._finalize_continuation_decision(eligibility)

    def get_continuation_preview(self) -> dict[str, Any]:
        status = self.get_status()
        if not isinstance(status, dict):
            return {
                "ok": False,
                "error_code": "STATUS_UNAVAILABLE",
                "message": "无法读取执行器会话状态。",
            }

        eligibility = status.get("eligibility", {})
        if not isinstance(eligibility, dict):
            eligibility = self._new_eligibility()
            eligibility["resume_blockers"].append("session_manifest_invalid")
            eligibility = self._finalize_continuation_decision(eligibility)

        record = status.get("record", {})
        if not isinstance(record, dict):
            record = {}

        continuation_available = bool(eligibility.get("preferred_continuation_available") is True)
        selected_provider = self._normalize_optional_str(eligibility.get("preferred_continuation_provider"))
        if not selected_provider:
            selected_provider = self._normalize_optional_str(eligibility.get("resume_candidate_provider"))
        if not selected_provider:
            selected_provider = self._normalize_optional_str(record.get("provider"))

        selected_version = self._normalize_optional_str(eligibility.get("resume_candidate_version"))
        if not selected_version:
            selected_version = self._normalize_optional_str(record.get("version"))

        selected_execution_mode = self._normalize_optional_str(eligibility.get("resume_candidate_execution_mode"))
        if not selected_execution_mode:
            selected_execution_mode = self._normalize_optional_str(record.get("execution_mode"))

        identity_kind = self._normalize_optional_str(eligibility.get("resume_identity_kind"))
        identity_present = bool(eligibility.get("resume_identity_present") is True)
        blockers = list(eligibility.get("continuation_blockers") or [])
        warnings = list(eligibility.get("resume_warnings") or [])
        hard_blockers = list(eligibility.get("hard_blockers") or blockers)
        risk_warnings = list(eligibility.get("risk_warnings") or [])
        risk_level = str(eligibility.get("risk_level") or "none")
        continuation_mode = "resume_candidate" if continuation_available else "new_conversation"
        next_action_hint = self._build_continuation_hint(
            continuation_available=continuation_available,
            blockers=hard_blockers,
            risk_level=risk_level,
        )

        return {
            "ok": True,
            "project_root": self.project_root,
            "manifest_file": self.manifest_file,
            "active": bool(status.get("active", False)),
            "selected_provider": selected_provider,
            "selected_version": selected_version,
            "selected_execution_mode": selected_execution_mode,
            "identity_kind": identity_kind,
            "identity_present": identity_present,
            "continuation_available": continuation_available,
            "continuation_mode": continuation_mode,
            "would_resume": False,
            "would_start_new": not continuation_available,
            "blockers": hard_blockers,
            "hard_blockers": hard_blockers,
            "resume_blockers": hard_blockers,
            "risk_warnings": risk_warnings,
            "resume_warnings": warnings,
            "risk_level": risk_level,
            "warnings": warnings,
            "provider_resume_supported": bool(eligibility.get("provider_resume_supported") is True),
            "session_resume_available": bool(eligibility.get("session_resume_available") is True),
            "conversation_identity_present": bool(eligibility.get("conversation_identity_present") is True),
            "resume_identity_present": identity_present,
            "next_action_hint": next_action_hint,
        }

    def get_continuation_decision(self, requested_provider: str | None = None) -> dict[str, Any]:
        preview = self.get_continuation_preview()
        if not isinstance(preview, dict) or not preview.get("ok"):
            return {
                "ok": False,
                "error_code": "PREVIEW_UNAVAILABLE",
                "message": "无法生成续接预览。",
            }

        policy = "auto_resume_when_verified"
        allowed_providers = {"pi", "codex", "opencode"}
        selected_provider = self._normalize_optional_str(preview.get("selected_provider"))
        normalized_requested = self._normalize_optional_str(requested_provider)
        if normalized_requested:
            normalized_requested = normalized_requested.lower()
        if not normalized_requested:
            normalized_requested = selected_provider

        hard_blockers = list(preview.get("hard_blockers") or preview.get("blockers") or [])
        risk_warnings = list(preview.get("risk_warnings") or [])
        risk_level = str(preview.get("risk_level") or "none")
        identity_kind = self._normalize_optional_str(preview.get("identity_kind"))
        identity_present = bool(preview.get("identity_present") is True)
        conversation_identity_present = bool(preview.get("conversation_identity_present") is True)
        provider_matches = bool(
            normalized_requested
            and selected_provider
            and normalized_requested == selected_provider
        )

        decision = "start_new_blocked"
        decision_reason = "hard_blocked"
        continuation_available = False
        should_start_new = True
        manual_confirmation_required = False
        should_resume = False
        provider_resume_supported, resume_invocation_verified, _ = self._provider_resume_policy(normalized_requested)

        if not normalized_requested:
            decision = "start_new_no_provider"
            decision_reason = "no_selected_provider"
            hard_blockers.append("no_selected_provider")
        elif normalized_requested not in allowed_providers:
            decision = "start_new_invalid_provider"
            decision_reason = "invalid_provider"
            hard_blockers.append("provider_unknown")
        elif selected_provider and not provider_matches:
            decision = "start_new_provider_mismatch"
            decision_reason = "provider_mismatch"
            hard_blockers.append("provider_mismatch")
        else:
            continuation_available = bool(preview.get("continuation_available") is True)
            if continuation_available:
                if (
                    provider_matches
                    and identity_present
                    and provider_resume_supported
                    and resume_invocation_verified
                    and not hard_blockers
                ):
                    decision = "resume_auto_eligible"
                    decision_reason = "same_project_provider_identity_available"
                    should_start_new = False
                    should_resume = True
                    manual_confirmation_required = False
                    hard_blockers = []
                else:
                    decision = "start_new_resume_invocation_unverified"
                    decision_reason = "resume_invocation_unverified"
                    should_start_new = True
                    should_resume = False
                    manual_confirmation_required = False
                    if not provider_resume_supported:
                        hard_blockers.append("provider_resume_not_supported")
                    if not resume_invocation_verified:
                        hard_blockers.append("resume_invocation_unverified")
                    if normalized_requested == "pi":
                        hard_blockers.append("pi_resume_invocation_unverified")
            else:
                if "no_session_manifest" in hard_blockers:
                    decision = "start_new_no_session"
                    decision_reason = "no_session_manifest"
                else:
                    decision = "start_new_blocked"
                    decision_reason = "hard_blocked"

        if normalized_requested in allowed_providers and not provider_resume_supported:
            hard_blockers.append("provider_resume_not_supported")

        hard_blockers = self._unique_items(hard_blockers)
        risk_warnings = self._unique_items(risk_warnings)
        session_resume_available = bool(
            continuation_available
            and provider_matches
            and provider_resume_supported
            and identity_present
            and not hard_blockers
        )
        if decision == "resume_auto_eligible":
            if risk_level == "warning":
                next_action_hint = "当前存在同项目、同执行器的可续接候选，分支或 HEAD 变化会记录为风险告警，下一次执行将自动 resume。"
            else:
                next_action_hint = "当前存在同项目、同执行器的可续接候选，下一次执行将自动 resume。"
        elif decision == "start_new_provider_mismatch":
            next_action_hint = "当前记录的会话来自其他执行器，本次应启动新会话。"
        elif decision == "start_new_invalid_provider":
            next_action_hint = "请求的执行器无效，本次不能使用 continuation。"
        elif decision == "start_new_no_session":
            next_action_hint = "当前没有可续接会话，本次应启动新会话。"
        else:
            next_action_hint = "当前存在硬阻断，本次应启动新会话。"

        return {
            "ok": True,
            "project_root": self.project_root,
            "manifest_file": self.manifest_file,
            "requested_provider": normalized_requested,
            "selected_provider": selected_provider,
            "provider_matches": provider_matches,
            "identity_kind": identity_kind,
            "identity_present": identity_present,
            "continuation_available": continuation_available,
            "policy": policy,
            "decision": decision,
            "decision_reason": decision_reason,
            "should_resume": should_resume,
            "should_start_new": should_start_new,
            "manual_confirmation_required": manual_confirmation_required,
            "risk_level": risk_level,
            "risk_warnings": risk_warnings,
            "resume_warnings": risk_warnings,
            "hard_blockers": hard_blockers,
            "resume_blockers": hard_blockers,
            "provider_resume_supported": provider_resume_supported,
            "session_resume_available": session_resume_available,
            "conversation_identity_present": conversation_identity_present,
            "resume_identity_present": identity_present,
            "actual_executor_resume_attempted": False,
            "resume_invocation_verified": resume_invocation_verified,
            "next_action_hint": next_action_hint,
            "preview": preview,
        }

    def get_resume_invocation_preview(self, requested_provider: str | None = None) -> dict[str, Any]:
        decision = self.get_continuation_decision(requested_provider=requested_provider)
        if not isinstance(decision, dict) or not decision.get("ok"):
            return {
                "ok": False,
                "error_code": "DECISION_UNAVAILABLE",
                "message": "无法生成续接决策。",
            }

        provider = self._normalize_optional_str(decision.get("requested_provider"))
        if provider:
            provider = provider.lower()
        selected_provider = self._normalize_optional_str(decision.get("selected_provider"))
        if selected_provider:
            selected_provider = selected_provider.lower()

        continuation_available = bool(decision.get("continuation_available") is True)
        identity_kind = self._normalize_optional_str(decision.get("identity_kind"))
        identity_present = bool(decision.get("identity_present") is True)
        provider_matches = bool(decision.get("provider_matches") is True)
        risk_level = str(decision.get("risk_level") or "none")
        risk_warnings = list(decision.get("risk_warnings") or [])
        hard_blockers = self._unique_items(list(decision.get("hard_blockers") or []))
        decision_name = str(decision.get("decision") or "start_new_blocked")
        (
            provider_resume_supported,
            resume_invocation_verified_flag,
            resume_invocation_kind,
        ) = self._provider_resume_policy(provider)
        should_resume = bool(
            decision_name == "resume_auto_eligible"
            and continuation_available
            and provider_matches
            and provider_resume_supported
            and resume_invocation_verified_flag
            and identity_present
            and not hard_blockers
        )
        requires_manual_confirmation = False

        resume_invocation_supported = provider_resume_supported
        resume_invocation_verified = resume_invocation_verified_flag
        command_preview: list[str] = []
        alternate_command_preview: list[str] = []
        command_mode = "unsupported"
        evidence = {
            "source": "internal_policy",
            "summary": "当前执行器没有可用的调用形态证据。",
        }
        next_action_hint = "当前没有可用的 resume 调用预览。"

        if provider == "codex":
            command_preview = ["codex", "exec", "resume", "<SESSION_ID>", "-"]
            alternate_command_preview = ["codex", "exec", "resume", "<SESSION_ID>", "<FOLLOW_UP_PROMPT>"]
            command_mode = "non_interactive_exec"
            evidence = {
                "source": "official_docs",
                "summary": "Codex CLI supports codex exec resume [SESSION_ID] with optional follow-up prompt.",
            }
            if should_resume:
                next_action_hint = "Codex resume invocation shape is verified. 下一次执行会自动 resume 同一会话。"
            else:
                next_action_hint = "Codex resume invocation shape is verified. 当前状态会在下一次执行使用新会话。"
        elif provider == "opencode":
            command_preview = []
            alternate_command_preview = []
            command_mode = "server_api"
            evidence = {
                "source": "runner_code_evidence",
                "summary": "OpenCode server adapter resumes sessions via HTTP API, not CLI commands.",
            }
            if should_resume:
                next_action_hint = "OpenCode server resume is supported. 下一次执行会自动 resume 同一会话。"
            else:
                next_action_hint = "OpenCode server resume is supported. 当前状态会在下一次执行使用新会话。"
        elif provider == "pi":
            command_preview = []
            alternate_command_preview = []
            command_mode = "unsupported"
            hard_blockers.append("pi_resume_invocation_unverified")
            hard_blockers = self._unique_items(hard_blockers)
            evidence = {
                "source": "runner_code_evidence",
                "summary": "Pi RPC currently proves sessionId/sessionFile capture, and resume command injection evidence is pending verification.",
            }
            next_action_hint = "当前只能证明 Pi 会返回 sessionId/sessionFile，Pi CLI/RPC 的安全 resume 调用证据仍在验证中。"
        else:
            hard_blockers.append("provider_unknown")
            hard_blockers = self._unique_items(hard_blockers)
            resume_invocation_kind = "provider_unknown"
            next_action_hint = "请求的执行器无效，当前无法提供 resume 调用预览。"

        return {
            "ok": True,
            "project_root": self.project_root,
            "manifest_file": self.manifest_file,
            "requested_provider": provider,
            "selected_provider": selected_provider,
            "provider_matches": provider_matches,
            "identity_kind": identity_kind,
            "identity_present": identity_present,
            "continuation_available": continuation_available,
            "decision": decision_name,
            "resume_invocation_supported": resume_invocation_supported,
            "resume_invocation_verified": resume_invocation_verified,
            "resume_invocation_kind": resume_invocation_kind,
            "command_preview": command_preview,
            "alternate_command_preview": alternate_command_preview,
            "command_mode": command_mode,
            "will_execute": should_resume,
            "requires_manual_confirmation": requires_manual_confirmation,
            "should_resume": should_resume,
            "risk_level": risk_level,
            "risk_warnings": risk_warnings,
            "hard_blockers": hard_blockers,
            "evidence": evidence,
            "next_action_hint": next_action_hint,
            "continuation_decision": decision,
        }

    def _provider_resume_policy(self, provider: str | None) -> tuple[bool, bool, str]:
        if provider == "codex":
            return True, True, "codex_exec_resume_session"
        if provider == "opencode":
            return True, True, "opencode_run_session"
        if provider == "pi":
            return False, False, "pi_resume_unsupported_pending_verification"
        return False, False, "provider_unknown"

    def record_execution(
        self,
        *,
        provider: str,
        version: str,
        execution_mode: str,
        attempt: int,
        session_id: str | None = None,
        session_file: str | None = None,
        conversation_id: str | None = None,
        resume_supported: bool = False,
        resume_enabled: bool = False,
        log_path: str | None = None,
        summary_path: str | None = None,
        source: str = "executor_result",
    ) -> dict[str, Any]:
        os.makedirs(self.runtime_dir, exist_ok=True)
        now = _now_iso()
        warnings: list[str] = []
        created_at = now
        if os.path.exists(self.manifest_file):
            previous = self._load_manifest()
            if isinstance(previous, dict):
                previous_created_at = previous.get("created_at")
                if isinstance(previous_created_at, str) and previous_created_at.strip():
                    created_at = previous_created_at.strip()

        git_branch, current_head, git_warnings = self._get_current_git_context()
        warnings.extend(git_warnings)
        record = ExecutorSessionRecord(
            active=True,
            provider=provider.strip(),
            project_root=self.project_root,
            project_name=os.path.basename(self.project_root.rstrip(os.sep)) or None,
            git_branch=git_branch,
            base_head=current_head,
            current_head=current_head,
            version=version.strip(),
            execution_mode=execution_mode.strip(),
            attempt=max(0, int(attempt)),
            session_id=self._normalize_optional_str(session_id),
            session_file=self._normalize_optional_str(session_file),
            conversation_id=self._normalize_optional_str(conversation_id),
            resume_supported=bool(resume_supported),
            resume_enabled=bool(resume_enabled),
            log_path=self._normalize_optional_str(log_path),
            summary_path=self._normalize_optional_str(summary_path),
            created_at=created_at,
            updated_at=now,
            source=source.strip() or "executor_result",
        )
        payload = asdict(record)
        self._write_manifest(payload)
        result = {
            "ok": True,
            "active": True,
            "manifest_file": self.manifest_file,
            "record": payload,
        }
        if warnings:
            result["warnings"] = warnings
        return result

    def reset(self, reason: str | None = None) -> dict[str, Any]:
        if not os.path.exists(self.manifest_file):
            return {
                "ok": True,
                "active": False,
                "manifest_file": self.manifest_file,
                "message": "当前没有执行器会话记录。",
            }

        payload = self._load_manifest()
        if not isinstance(payload, dict):
            return {
                "ok": False,
                "error_code": "MANIFEST_INVALID",
                "message": "执行器会话记录格式无效，无法重置。",
                "manifest_file": self.manifest_file,
            }

        now = _now_iso()
        payload["active"] = False
        payload["updated_at"] = now
        payload["reset_at"] = now
        payload["reset_reason"] = (reason or "").strip() or None
        self._write_manifest(payload)
        return {
            "ok": True,
            "active": False,
            "manifest_file": self.manifest_file,
            "record": payload,
            "message": "执行器会话记录已重置为非活动状态。",
        }

    def _load_manifest(self) -> dict[str, Any] | None:
        try:
            with open(self.manifest_file, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            return payload if isinstance(payload, dict) else None
        except Exception:
            return None

    def _write_manifest(self, payload: dict[str, Any]) -> None:
        os.makedirs(self.runtime_dir, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(prefix=".executor-session-", suffix=".json", dir=self.runtime_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            os.replace(temp_path, self.manifest_file)
        except Exception:
            try:
                os.unlink(temp_path)
            except Exception:
                pass
            raise

    def _get_current_git_context(self) -> tuple[str | None, str | None, list[str]]:
        warnings: list[str] = []
        git_branch, err_branch = self._run_git_value(["rev-parse", "--abbrev-ref", "HEAD"])
        current_head, err_head = self._run_git_value(["rev-parse", "HEAD"])
        if err_branch:
            warnings.append(f"读取 git_branch 失败：{err_branch}")
        if err_head:
            warnings.append(f"读取 current_head 失败：{err_head}")
        return git_branch, current_head, warnings

    def _run_git_value(self, args: list[str]) -> tuple[str | None, str | None]:
        rc, stdout, stderr = _run_git_base(args, self.project_root, timeout=5)
        if rc != 0:
            return None, (stderr or stdout or "git command failed").strip()
        value = (stdout or "").strip()
        return (value or None), None

    def _normalize_optional_str(self, value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        cleaned = value.strip()
        return cleaned or None

    def _new_eligibility(self) -> dict[str, Any]:
        return {
            "resume_eligible": False,
            "resume_blockers": [],
            "resume_warnings": [],
            "resume_candidate_provider": None,
            "resume_candidate_version": None,
            "resume_candidate_execution_mode": None,
            "resume_candidate_session_id_present": False,
            "resume_candidate_session_file_present": False,
            "resume_candidate_conversation_id_present": False,
            "resume_identity_kind": None,
            "resume_identity_present": False,
            "conversation_identity_present": False,
            "provider_resume_supported": False,
            "session_resume_available": False,
            "preferred_continuation_provider": None,
            "preferred_continuation_available": False,
            "preferred_continuation_reason": None,
            "continuation_blockers": [],
            "hard_blockers": [],
            "risk_warnings": [],
            "risk_level": "none",
        }

    def _finalize_continuation_decision(self, eligibility: dict[str, Any]) -> dict[str, Any]:
        provider = eligibility.get("resume_candidate_provider")
        blockers = self._unique_items(list(eligibility.get("resume_blockers") or []))
        risk_warnings = list(eligibility.get("risk_warnings") or [])
        resume_warnings = self._unique_items(list(eligibility.get("resume_warnings") or []))
        unique_risks: list[str] = []
        for risk in risk_warnings:
            if isinstance(risk, str) and risk and risk not in unique_risks:
                unique_risks.append(risk)
        eligibility["resume_blockers"] = blockers
        eligibility["resume_warnings"] = resume_warnings
        eligibility["risk_warnings"] = unique_risks
        eligibility["hard_blockers"] = blockers
        eligibility["continuation_blockers"] = blockers
        eligibility["provider_resume_supported"] = bool(eligibility.get("provider_resume_supported") is True)
        eligibility["session_resume_available"] = bool(
            eligibility.get("session_resume_available") is True
            and not blockers
        )
        eligibility["resume_identity_present"] = bool(eligibility.get("resume_identity_present") is True)
        eligibility["conversation_identity_present"] = bool(eligibility.get("conversation_identity_present") is True)
        if blockers:
            eligibility["risk_level"] = "blocked"
        elif unique_risks:
            eligibility["risk_level"] = "warning"
        else:
            eligibility["risk_level"] = "none"
        if eligibility.get("resume_eligible") is True:
            eligibility["preferred_continuation_provider"] = provider
            eligibility["preferred_continuation_available"] = True
            eligibility["preferred_continuation_reason"] = "eligible_same_project_provider_identity"
            eligibility["hard_blockers"] = []
            eligibility["continuation_blockers"] = []
        else:
            eligibility["preferred_continuation_provider"] = provider if isinstance(provider, str) and provider else None
            eligibility["preferred_continuation_available"] = False
            eligibility["preferred_continuation_reason"] = "blocked"
        return eligibility

    def _build_continuation_hint(self, *, continuation_available: bool, blockers: list[str], risk_level: str) -> str:
        blocker_set = set(blockers)
        if continuation_available:
            if risk_level == "warning":
                return "当前存在同项目、同执行器的可续接候选，但分支或 HEAD 已变化；本轮仅预览，不会执行 resume。"
            return "当前存在同项目、同执行器的可续接候选；本轮仅预览，不会执行 resume。"
        if "no_session_manifest" in blocker_set:
            return "当前没有可续接会话，下次执行将启动新会话。"
        if "provider_resume_not_supported" in blocker_set:
            return "当前执行器静态策略不支持 resume，下次执行将启动新会话。"
        if "project_mismatch" in blocker_set:
            return "当前会话来自不同项目，下次执行应启动新会话。"
        return "当前没有可用续接候选。"

    def _build_resume_diagnostics(
        self,
        *,
        provider: str | None,
        active: bool,
        session_id: str | None,
        session_file: str | None,
        conversation_id: str | None,
    ) -> dict[str, Any]:
        provider_norm = self._normalize_optional_str(provider)
        if provider_norm:
            provider_norm = provider_norm.lower()
        provider_resume_supported, _, _ = self._provider_resume_policy(provider_norm)

        blockers: list[str] = []
        identity_kind = None
        identity_present = False
        conversation_identity_present = bool(conversation_id)

        if not provider_norm:
            blockers.append("provider_missing")
        elif provider_norm not in {"pi", "codex", "opencode"}:
            blockers.append("provider_unknown")
        elif provider_norm == "pi":
            identity_kind = "pi_session"
            identity_present = bool(session_id or session_file)
            if not identity_present:
                blockers.append("session_identity_missing")
        elif provider_norm == "codex":
            identity_kind = "codex_conversation"
            identity_present = bool(conversation_id)
            if not identity_present:
                blockers.append("conversation_identity_missing")
        elif provider_norm == "opencode":
            if conversation_id:
                identity_kind = "opencode_conversation"
                identity_present = True
            elif session_id or session_file:
                identity_kind = "opencode_session"
                identity_present = True
            else:
                identity_kind = "opencode_unknown"
                identity_present = False
                blockers.append("opencode_identity_missing")

        if provider_norm in {"pi", "codex", "opencode"} and not provider_resume_supported:
            blockers.append("provider_resume_not_supported")

        session_resume_available = bool(
            provider_resume_supported
            and active
            and identity_present
            and not blockers
        )
        return {
            "provider_resume_supported": provider_resume_supported,
            "session_resume_available": session_resume_available,
            "resume_identity_kind": identity_kind,
            "resume_identity_present": identity_present,
            "conversation_identity_present": conversation_identity_present,
            "resume_blockers": self._unique_items(blockers),
        }

    def _unique_items(self, items: list[str]) -> list[str]:
        unique: list[str] = []
        for item in items:
            if isinstance(item, str) and item and item not in unique:
                unique.append(item)
        return unique

from runner.runner_paths import resolve_project_runner_dir
