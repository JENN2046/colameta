from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from runner.core_result_facts import (
    NextAction,
    ResultFacts,
    normalize_fact_snapshot_facts,
    normalize_next_actions,
    normalize_result_facts,
)


class RunnerPhase(str, Enum):
    IDLE = "idle"
    PLANNING = "planning"
    EXECUTING = "executing"
    REVIEWING = "reviewing"
    COMMITTING = "committing"


class RunnerState(str, Enum):
    READY = "ready"
    BLOCKED = "blocked"
    FAILED = "failed"
    RUNNING = "running"
    COMPLETED = "completed"
    PREVIEW_NEEDED = "preview_needed"
    HAS_PREVIEW = "has_preview"
    CLEAN = "clean"


@dataclass
class RunnerStatus:
    phase: str = RunnerPhase.IDLE.value
    state: str = RunnerState.READY.value

    blocked: bool = False
    failed: bool = False
    can_continue: bool = False
    needs_user_confirmation: bool = False

    can_preview: bool = False
    can_apply: bool = False
    can_run: bool = False
    can_commit: bool = False
    can_fix: bool = False

    preview_id: str | None = None
    patch_id: str | None = None
    report_id: str | None = None
    run_id: str | None = None

    working_tree_clean: bool = True

    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    error_code: str | None = None

    source: str | None = None
    action: str | None = None

    summary: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "state": self.state,
            "blocked": self.blocked,
            "failed": self.failed,
            "can_continue": self.can_continue,
            "needs_user_confirmation": self.needs_user_confirmation,
            "can_preview": self.can_preview,
            "can_apply": self.can_apply,
            "can_run": self.can_run,
            "can_commit": self.can_commit,
            "can_fix": self.can_fix,
            "working_tree_clean": self.working_tree_clean,
            "preview_id": self.preview_id,
            "patch_id": self.patch_id,
            "report_id": self.report_id,
            "run_id": self.run_id,
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "error": self.error,
            "error_code": self.error_code,
            "source": self.source,
            "action": self.action,
            "summary": self.summary,
        }


def create_status_from_manager_output(
    output: dict[str, Any],
    source: str | None = None,
    action: str | None = None,
) -> RunnerStatus:
    s = RunnerStatus()
    s.source = source
    s.action = action

    if not isinstance(output, dict):
        return s

    _apply_common_fields(s, output)
    _apply_git_commit_fields(s, output)
    _apply_executor_fields(s, output)
    _apply_workflow_router_fields(s, output)

    return s


def create_status_from_normalized_result(
    workflow: str,
    status: str,
    risk_level: str,
    requires_confirmation: bool,
    blockers: list[str] | None = None,
    warnings: list[str] | None = None,
    preview_ids: list[str] | None = None,
    result: dict[str, Any] | None = None,
) -> RunnerStatus:
    s = RunnerStatus()
    s.source = workflow
    s.needs_user_confirmation = requires_confirmation

    if isinstance(blockers, list) and blockers:
        s.blockers = list(blockers)
        s.blocked = True

    if isinstance(warnings, list) and warnings:
        s.warnings = list(warnings)

    if isinstance(preview_ids, list) and preview_ids:
        pid = preview_ids[0]
        if isinstance(pid, str) and pid:
            s.preview_id = pid
            s.state = RunnerState.HAS_PREVIEW.value
            s.can_apply = True

    if status == "blocked":
        s.state = RunnerState.BLOCKED.value
        s.blocked = True
    elif status == "failed":
        s.state = RunnerState.FAILED.value
        s.failed = True
    elif status == "preview_ready":
        s.state = RunnerState.HAS_PREVIEW.value
    elif status == "succeeded":
        s.state = RunnerState.COMPLETED.value
    elif status == "started":
        s.state = RunnerState.RUNNING.value
        s.can_continue = True

    if isinstance(result, dict):
        if result.get("ok") and "working_tree_clean" in result:
            s.working_tree_clean = bool(result.get("working_tree_clean", True))
        if result.get("run_id"):
            s.run_id = str(result.get("run_id"))
        if result.get("report_id"):
            s.report_id = str(result.get("report_id"))
        if result.get("error"):
            s.error = str(result.get("error"))
        if result.get("error_code"):
            s.error_code = str(result.get("error_code"))
        s_summary = result.get("message") or result.get("summary")
        if isinstance(s_summary, str) and s_summary:
            s.summary = s_summary

    return s


def _apply_common_fields(s: RunnerStatus, output: dict[str, Any]) -> None:
    if output.get("ok") is False:
        raw_status = str(output.get("status", ""))
        has_commit_blockers = (
            isinstance(output.get("commit_blockers"), list)
            and len(output.get("commit_blockers")) > 0
        )
        is_blocked = bool(output.get("preflight_blocked")) or raw_status == "blocked" or has_commit_blockers
        if is_blocked:
            s.blocked = True
            s.state = RunnerState.BLOCKED.value
        else:
            s.failed = True
            s.state = RunnerState.FAILED.value
    if "working_tree_clean" in output:
        s.working_tree_clean = bool(output.get("working_tree_clean"))
    if "blocked" in output:
        s.blocked = bool(output.get("blocked"))
    if "failed" in output:
        s.failed = bool(output.get("failed"))
    if "can_continue" in output:
        s.can_continue = bool(output.get("can_continue"))
    if "needs_user_confirmation" in output:
        s.needs_user_confirmation = bool(output.get("needs_user_confirmation"))
    if "requires_confirmation" in output:
        s.needs_user_confirmation = bool(output.get("requires_confirmation"))
    if "can_preview" in output:
        s.can_preview = bool(output.get("can_preview"))
    if "can_apply" in output:
        s.can_apply = bool(output.get("can_apply"))
    if "can_run" in output:
        s.can_run = bool(output.get("can_run"))
    if "can_commit" in output:
        s.can_commit = bool(output.get("can_commit"))
    if "can_fix" in output:
        s.can_fix = bool(output.get("can_fix"))

    if "blockers" in output:
        raw = output.get("blockers", [])
        if isinstance(raw, list):
            for b in raw:
                if isinstance(b, str) and b not in s.blockers:
                    s.blockers.append(b)
        s.blocked = len(s.blockers) > 0
    if "warnings" in output:
        raw = output.get("warnings", [])
        if isinstance(raw, list):
            for w in raw:
                if isinstance(w, str) and w not in s.warnings:
                    s.warnings.append(w)

    if "error" in output:
        s.error = str(output.get("error", "")) or None
    if "error_code" in output:
        s.error_code = str(output.get("error_code", "")) or None

    pid = output.get("preview_id")
    if isinstance(pid, str) and pid:
        s.preview_id = pid
        s.state = RunnerState.HAS_PREVIEW.value
        s.can_apply = True
    pids = output.get("preview_ids")
    if isinstance(pids, list) and pids and not s.preview_id:
        first = pids[0]
        if isinstance(first, str) and first:
            s.preview_id = first
            s.state = RunnerState.HAS_PREVIEW.value
            s.can_apply = True
    pid2 = output.get("patch_id")
    if isinstance(pid2, str) and pid2:
        s.patch_id = pid2
    rid = output.get("run_id")
    if isinstance(rid, str) and rid:
        s.run_id = rid
    rid2 = output.get("report_id")
    if isinstance(rid2, str) and rid2:
        s.report_id = rid2

    s_summary = output.get("summary") or output.get("message")
    if isinstance(s_summary, str) and s_summary:
        s.summary = s_summary


def _apply_git_commit_fields(s: RunnerStatus, output: dict[str, Any]) -> None:
    if "commit_blockers" in output:
        raw = output.get("commit_blockers", [])
        if isinstance(raw, list):
            for b in raw:
                if isinstance(b, str) and b not in s.blockers:
                    s.blockers.append(b)
        s.blocked = len(s.blockers) > 0
    if "commit_warnings" in output:
        raw = output.get("commit_warnings", [])
        if isinstance(raw, list):
            for w in raw:
                if isinstance(w, str) and w not in s.warnings:
                    s.warnings.append(w)

    if output.get("working_tree_clean") and not s.blockers:
        s.state = RunnerState.CLEAN.value
    elif not s.blocked:
        if output.get("can_preview") and not output.get("working_tree_clean"):
            s.state = RunnerState.PREVIEW_NEEDED.value
        else:
            s.state = RunnerState.READY.value


def _apply_executor_fields(s: RunnerStatus, output: dict[str, Any]) -> None:
    if "preflight_blocked" in output:
        blocked = bool(output.get("preflight_blocked"))
        if blocked:
            s.blocked = True
            s.state = RunnerState.BLOCKED.value
    if "runner_status" in output:
        rs = str(output.get("runner_status", ""))
        if rs in ("running", "pending"):
            s.state = RunnerState.RUNNING.value
            s.can_continue = True
        elif rs in ("failed", "error"):
            s.failed = True
            s.state = RunnerState.FAILED.value
        elif rs == "completed":
            s.state = RunnerState.COMPLETED.value
    if "executor_run_status" in output:
        ers = str(output.get("executor_run_status", ""))
        if ers == "running":
            s.state = RunnerState.RUNNING.value
            s.can_continue = True
        elif ers == "completed":
            s.state = RunnerState.COMPLETED.value
        elif ers in ("failed", "orphaned"):
            s.failed = True
            s.state = RunnerState.FAILED.value


def _apply_workflow_router_fields(s: RunnerStatus, output: dict[str, Any]) -> None:
    raw_status = str(output.get("status", ""))
    if raw_status == "blocked":
        s.blocked = True
        s.state = RunnerState.BLOCKED.value
    elif raw_status == "failed":
        s.failed = True
        s.state = RunnerState.FAILED.value
    elif raw_status == "preview_ready":
        s.state = RunnerState.HAS_PREVIEW.value
        s.needs_user_confirmation = True
    elif raw_status == "started":
        s.state = RunnerState.RUNNING.value
        s.can_continue = True
    elif raw_status == "succeeded":
        s.state = RunnerState.COMPLETED.value

    if "requires_confirmation" in output:
        s.needs_user_confirmation = bool(output.get("requires_confirmation"))
    if "actionable" in output:
        pass
    if "dispatch_ready" in output:
        s.can_run = bool(output.get("dispatch_ready"))
