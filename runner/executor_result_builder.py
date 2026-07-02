from typing import Any

from runner.executor_status import classify_claim_status, polling_guidance_for_profile


def _status_next_action_params(*, run_id: str = "", preview_id: str = "", profile_id: str | None = None) -> dict[str, str]:
    params = {"action": "status"}
    if run_id:
        params["run_id"] = run_id
    if preview_id:
        params["preview_id"] = preview_id
    selected_profile_id = polling_guidance_for_profile(profile_id)["profile_id"]
    if selected_profile_id:
        params["profile_id"] = selected_profile_id
    return params


def preflight_result(preflight: dict[str, Any], *, provider: str, execution_mode: str) -> dict[str, Any]:
    return {
        "ok": True,
        "action": "preflight",
        "status": "succeeded",
        "risk_level": "info",
        "provider": preflight.get("provider", provider),
        "execution_mode": preflight.get("execution_mode", execution_mode),
        "preflight_blocked": preflight.get("preflight_blocked", True),
        "blocks": preflight.get("blocks", []),
        "warnings": preflight.get("warnings", []),
        "current_version": preflight.get("current_version"),
        "current_version_index": preflight.get("current_version_index"),
        "current_head": preflight.get("current_head"),
        "current_branch": preflight.get("current_branch"),
        "runner_status": preflight.get("runner_status"),
        "git_status_short": preflight.get("git_status_short", ""),
        "git_dirty": preflight.get("git_dirty", False),
        "blocking_git_status_short": preflight.get("blocking_git_status_short", ""),
        "blocking_git_changed_files": preflight.get("blocking_git_changed_files", []),
        "runner_memory_files": preflight.get("runner_memory_files", []),
        "ignored_runner_local_files": preflight.get("ignored_runner_local_files", []),
        "ignored_runner_runtime_files": preflight.get("ignored_runner_runtime_files", []),
        "ignored_runner_archive_files": preflight.get("ignored_runner_archive_files", []),
        "execution_branch_status": preflight.get("execution_branch_status", "NOT_REQUIRED"),
        "execution_branch_required": preflight.get("execution_branch_required", False),
        "execution_branch_ready": preflight.get("execution_branch_ready", False),
        "executor_inventory": preflight.get("executor_inventory", {}),
    }


def run_once_started_result(*, run_id: str, preview_id: str, preview_claimed_at: str, profile_id: str | None = None) -> dict[str, Any]:
    return {
        "ok": True,
        "action": "run_once",
        "status": "started",
        "risk_level": "commit",
        "run_id": run_id,
        "preview_id": preview_id,
        "preview_claimed_at": preview_claimed_at,
        "preview_claim_status": "RUNNING",
        "polling_guidance": polling_guidance_for_profile(profile_id),
        "message": f"执行器已启动（run_id={run_id}）。使用 manage_executor_workflow action=status run_id={run_id} 或 preview_id={preview_id} 查询执行进度。",
        "next_actions": [
            {
                "tool": "manage_executor_workflow",
                "action": "status",
                "params": _status_next_action_params(run_id=run_id, preview_id=preview_id, profile_id=profile_id),
                "reason": "使用 status 轮询执行进度。",
                "requires_confirmation": False,
            },
        ],
    }


def already_claimed_error(
    *,
    action: str,
    preview_id: str,
    claim: dict[str, Any],
    orphan_info: dict[str, Any],
    possible_report_id: str = "",
    profile_id: str | None = None,
) -> dict[str, Any]:
    run_id = str(claim.get("run_id") or "")
    claimed_at = str(claim.get("claimed_at") or "")
    classification = classify_claim_status(claim, orphan_info)
    preview_claim_status = classification["preview_claim_status"]
    message = "preview_id 已被消费。"
    if orphan_info.get("orphaned"):
        message = str(orphan_info.get("message") or message)
    polling_guidance = polling_guidance_for_profile(profile_id)
    payload: dict[str, Any] = {
        "ok": False,
        "action": action,
        "status": "blocked",
        "risk_level": "blocked",
        "error_code": "PREVIEW_ALREADY_CLAIMED",
        "message": message,
        "preview_id": preview_id,
        "run_id": run_id,
        "claimed_at": claimed_at,
        "preview_claim_status": preview_claim_status,
        "terminal": classification["terminal"],
        "executor_run_status": classification["executor_run_status"],
        "polling_profile_id": polling_guidance["profile_id"],
        "next_poll_after_seconds": polling_guidance["next_poll_after_seconds"],
        "max_poll_attempts": polling_guidance["max_poll_attempts"],
        "max_total_poll_seconds": polling_guidance["max_total_poll_seconds"],
        "polling_guidance": polling_guidance,
        "next_actions": [
            {
                "tool": "manage_executor_workflow",
                "action": "status",
                "params": _status_next_action_params(run_id=run_id, preview_id=preview_id, profile_id=profile_id),
                "reason": "使用 status 轮询执行进度，不使用 start/run。",
                "requires_confirmation": False,
            },
            {
                "tool": "manage_executor_workflow",
                "action": "preflight",
                "params": {"action": "preflight"},
                "reason": "先检查当前状态，再生成新的 preview。",
                "requires_confirmation": False,
            },
        ],
    }
    if orphan_info.get("orphaned"):
        payload["terminal"] = True
        payload["executor_run_status"] = "orphaned"
        payload["orphan_error_code"] = str(orphan_info.get("error_code") or "EXECUTOR_RUN_ORPHANED")
        if possible_report_id:
            payload["possible_report_id"] = possible_report_id
    for key in ("worker_pid", "worker_started_at", "thread_started_at", "last_heartbeat_at", "heartbeat_interval_seconds"):
        value = claim.get(key)
        if value is not None and value != "":
            payload[key] = value
    if claim.get("report_id"):
        payload["report_id"] = str(claim.get("report_id"))
    return payload
