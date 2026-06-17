import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from runner.confirmation_store import ConfirmationStore


class ExecutorConfirmationStore:
    """Storage adapter for executor workflow preview artifacts."""

    def __init__(self, project_root: str, relative_dir: str, ttl_seconds: int):
        self.project_root = project_root
        self.ttl_seconds = ttl_seconds
        self._store = ConfirmationStore(project_root, relative_dir, ttl_seconds)

    def create_id(self, prefix: str) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        return f"{prefix}_{ts}_{uuid.uuid4().hex[:8]}"

    def now_iso(self) -> str:
        return datetime.now(timezone.utc).astimezone().isoformat()

    def expires_at(self, add_seconds: int | None = None) -> str:
        seconds = self.ttl_seconds if add_seconds is None else int(add_seconds)
        return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).astimezone().isoformat()

    def write_artifact(self, preview_id: str, payload: dict[str, Any]) -> None:
        self._store.write(preview_id, payload)

    def read_artifact(self, preview_id: str) -> dict[str, Any] | None:
        data = self._store.read(preview_id)
        return data if isinstance(data, dict) else None

    def delete_artifact(self, preview_id: str) -> None:
        self._store.delete(preview_id)

    def is_expired(self, payload: dict[str, Any]) -> bool:
        return self._store.is_expired(payload)

    def validate_project(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._store.validate_project(payload)

    def validate_not_expired(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._store.validate_not_expired(payload)

    def validate_artifact_kind(self, payload: dict[str, Any], expected: str) -> dict[str, Any]:
        actual = str(payload.get("artifact_kind") or "")
        if actual != expected:
            return {
                "ok": False,
                "error_code": "PREVIEW_KIND_MISMATCH",
                "message": "preview_id 类型不匹配。",
            }
        return {"ok": True}

    def validate_provider(self, payload: dict[str, Any], provider: str) -> dict[str, Any]:
        actual = str(payload.get("provider") or "")
        if actual != provider:
            return {
                "ok": False,
                "error_code": "PROVIDER_MISMATCH",
                "message": f"provider 不匹配。preview 中记录的是 {actual}，但请求的是 {provider}。",
            }
        return {"ok": True}

    def validate_execution_mode(self, payload: dict[str, Any], execution_mode: str) -> dict[str, Any]:
        actual = str(payload.get("execution_mode") or "run")
        if actual != execution_mode:
            return {
                "ok": False,
                "error_code": "EXECUTION_MODE_MISMATCH",
                "message": f"execution_mode 不匹配。preview 中记录的是 {actual}，但请求的是 {execution_mode}。",
            }
        return {"ok": True}


def run_once_preview_artifact(
    *,
    preview_id: str,
    project_root: str,
    preflight_result: dict[str, Any],
    provider: str,
    execution_mode: str,
    created_at: str,
    expires_at: str,
) -> dict[str, Any]:
    return {
        "preview_id": preview_id,
        "artifact_kind": "run_once",
        "project_root": project_root,
        "current_head": preflight_result.get("current_head"),
        "current_branch": preflight_result.get("current_branch"),
        "current_version": preflight_result.get("current_version"),
        "current_version_index": preflight_result.get("current_version_index"),
        "runner_status": preflight_result.get("runner_status"),
        "provider": preflight_result.get("provider", provider),
        "execution_mode": preflight_result.get("execution_mode", execution_mode),
        "execution_branch_required": preflight_result.get("execution_branch_required", False),
        "execution_branch_status": preflight_result.get("execution_branch_status", "NOT_REQUIRED"),
        "git_status_short": preflight_result.get("git_status_short", ""),
        "blocking_git_status_short": preflight_result.get("blocking_git_status_short", ""),
        "ignored_runner_archive_files": preflight_result.get("ignored_runner_archive_files", []),
        "created_at": created_at,
        "expires_at": expires_at,
        "risk_level": "commit",
        "preflight_summary": {
            "blocks_count": len(preflight_result.get("blocks", [])),
            "warnings_count": len(preflight_result.get("warnings", [])),
            "execution_branch_ready": preflight_result.get("execution_branch_ready", False),
        },
    }


def run_bounded_preview_artifact(
    *,
    preview_id: str,
    project_root: str,
    preflight: dict[str, Any],
    provider: str,
    max_iterations: int,
    trusted_mode: bool,
    allow_fix: bool,
    allow_commit: bool,
    stop_on_acceptance_failure: bool,
    stop_on_scope_violation: bool,
    stop_on_diff_too_large: bool,
    max_total_diff_chars: int,
    continuation_decision: dict[str, Any],
    resume_invocation_preview: dict[str, Any],
    created_at: str,
    expires_at: str,
) -> dict[str, Any]:
    return {
        "preview_id": preview_id,
        "artifact_kind": "run_bounded",
        "project_root": project_root,
        "current_head": preflight.get("current_head"),
        "current_branch": preflight.get("current_branch"),
        "current_version": preflight.get("current_version"),
        "current_version_index": preflight.get("current_version_index"),
        "runner_status": preflight.get("runner_status"),
        "provider": preflight.get("provider", provider),
        "execution_mode": "run",
        "max_iterations": max_iterations,
        "trusted_mode": trusted_mode,
        "allow_fix": allow_fix,
        "allow_commit": allow_commit,
        "stop_on_acceptance_failure": stop_on_acceptance_failure,
        "stop_on_scope_violation": stop_on_scope_violation,
        "stop_on_diff_too_large": stop_on_diff_too_large,
        "max_total_diff_chars": max_total_diff_chars,
        "git_status_short": preflight.get("git_status_short", ""),
        "blocking_git_status_short": preflight.get("blocking_git_status_short", ""),
        "ignored_runner_archive_files": preflight.get("ignored_runner_archive_files", []),
        "execution_branch_status": preflight.get("execution_branch_status", "NOT_REQUIRED"),
        "execution_branch_required": preflight.get("execution_branch_required", False),
        "continuation_decision": continuation_decision,
        "resume_invocation_preview": resume_invocation_preview,
        "created_at": created_at,
        "expires_at": expires_at,
        "risk_level": "commit",
        "preflight_summary": {
            "blocks_count": len(preflight.get("blocks", [])),
            "warnings_count": len(preflight.get("warnings", [])),
            "execution_branch_ready": preflight.get("execution_branch_ready", False),
        },
    }


def recheck_report_preview_artifact(
    *,
    preview_id: str,
    project_root: str,
    target_version: str,
    report_id: str,
    old_runner_status: str,
    old_version_status: str,
    current_head: str,
    report_head_after: str,
    proposed_state_update: dict[str, Any],
    old_scope_result: dict[str, Any],
    new_scope_result: dict[str, Any],
    created_at: str,
    expires_at: str,
) -> dict[str, Any]:
    return {
        "preview_id": preview_id,
        "artifact_kind": "recheck_report_state_refresh",
        "project_root": project_root,
        "target_version": target_version,
        "report_id": report_id,
        "old_runner_status": old_runner_status,
        "old_version_status": old_version_status,
        "current_head": current_head,
        "report_head_after": report_head_after,
        "can_refresh_state": True,
        "proposed_state_update": proposed_state_update,
        "old_scope_result": old_scope_result,
        "new_scope_result": new_scope_result,
        "created_at": created_at,
        "expires_at": expires_at,
    }


def manual_fix_prompt_preview_artifact(
    *,
    preview_id: str,
    project_root: str,
    target_version: str,
    current_version_index: int,
    old_runner_status: str,
    old_version_status: str,
    current_head: str,
    attempt_before: int,
    attempt_after: int,
    max_fix_attempts_per_version: int,
    reason: str,
    manual_fix_prompt: str,
    evidence_kind: str,
    evidence_path: str,
    evidence_markdown: str,
    report_id: str,
    audit_package_id: str,
    allow_max_attempt_recovery: bool,
    created_at: str,
    expires_at: str,
) -> dict[str, Any]:
    return {
        "preview_id": preview_id,
        "artifact_kind": "manual_fix_prompt_prepare",
        "project_root": project_root,
        "target_version": target_version,
        "current_version_index": current_version_index,
        "old_runner_status": old_runner_status,
        "old_version_status": old_version_status,
        "current_head": current_head,
        "attempt_before": attempt_before,
        "attempt_after": attempt_after,
        "max_fix_attempts_per_version": max_fix_attempts_per_version,
        "reason": reason,
        "manual_fix_prompt": manual_fix_prompt,
        "evidence_kind": evidence_kind,
        "evidence_path": evidence_path,
        "evidence_markdown": evidence_markdown,
        "report_id": report_id,
        "audit_package_id": audit_package_id,
        "allow_max_attempt_recovery": allow_max_attempt_recovery,
        "created_at": created_at,
        "expires_at": expires_at,
        "risk_level": "commit",
        "can_apply": True,
    }


def scope_mismatch_preview_artifact(**fields: Any) -> dict[str, Any]:
    artifact = dict(fields)
    artifact["artifact_kind"] = "scope_mismatch_resolution"
    return artifact
