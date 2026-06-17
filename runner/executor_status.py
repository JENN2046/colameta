from typing import Any


def status_base_result(poll_attempt: int) -> dict[str, Any]:
    max_poll_attempts = 3
    polling_exhausted = poll_attempt > max_poll_attempts
    result: dict[str, Any] = {
        "ok": True,
        "action": "status",
        "status": "succeeded",
        "risk_level": "info",
        "next_poll_after_seconds": 3,
        "max_poll_attempts": max_poll_attempts,
        "poll_attempt": poll_attempt,
        "remaining_poll_attempts": max(0, max_poll_attempts - poll_attempt),
        "polling_exhausted": polling_exhausted,
        "terminal": False,
        "executor_run_status": "unknown",
        "polling_guidance": {
            "policy": "non_blocking_polling",
            "next_poll_after_seconds": 3,
            "max_poll_attempts": max_poll_attempts,
            "on_exhausted": "stop_and_ask_user_to_check_later",
        },
    }
    if polling_exhausted:
        result["message"] = (
            "已达到最大轮询次数。请停止工具调用，告知用户："
            "Runner 仍在工作，请稍后再发消息继续检查。"
        )
    return result


def classify_claim_status(claim: dict[str, Any], orphan_info: dict[str, Any]) -> dict[str, Any]:
    claim_status = str(claim.get("status") or "RUNNING")
    terminal = False
    executor_run_status = "unknown"
    message = ""
    error_code = ""
    if claim_status == "RUNNING":
        if orphan_info.get("orphaned"):
            executor_run_status = "orphaned"
            terminal = True
            error_code = str(orphan_info.get("error_code") or "EXECUTOR_RUN_ORPHANED")
            message = str(orphan_info.get("message") or "执行器运行已失联。")
        else:
            executor_run_status = "running"
    elif claim_status == "COMPLETED":
        executor_run_status = "completed"
        terminal = True
    elif claim_status == "FAILED":
        executor_run_status = "failed"
        terminal = True
    return {
        "preview_claim_status": claim_status,
        "executor_run_status": executor_run_status,
        "terminal": terminal,
        "error_code": error_code,
        "message": message,
    }


def apply_claim_to_status(
    result: dict[str, Any],
    claim: dict[str, Any],
    orphan_info: dict[str, Any],
    possible_report_id: str = "",
) -> None:
    classification = classify_claim_status(claim, orphan_info)
    claim_status = classification["preview_claim_status"]
    result["executor_run_status"] = classification["executor_run_status"]
    result["terminal"] = classification["terminal"]
    if classification.get("error_code"):
        result["error_code"] = classification["error_code"]
    if classification.get("message"):
        result["message"] = classification["message"]
    if possible_report_id and claim_status == "RUNNING" and orphan_info.get("orphaned") and not str(claim.get("report_id") or ""):
        result["possible_report_id"] = possible_report_id

    result["run_id"] = str(claim.get("run_id") or "")
    result["preview_id"] = str(claim.get("preview_id") or "")
    claim_model = claim.get("model")
    if claim_model:
        result["model"] = str(claim_model)
        result["model_source"] = str(claim.get("model_source") or "")
    result["preview_claim_status"] = claim_status
    result["claimed_at"] = str(claim.get("claimed_at") or "")
    result["finished_at"] = str(claim.get("finished_at") or "")
    result["report_id"] = str(claim.get("report_id") or "")
    if claim.get("worker_pid") is not None:
        result["worker_pid"] = claim.get("worker_pid")
    thread_started_at = claim.get("thread_started_at")
    if thread_started_at:
        result["thread_started_at"] = str(thread_started_at)
    worker_started_at = claim.get("worker_started_at")
    if worker_started_at:
        result["worker_started_at"] = str(worker_started_at)
    last_heartbeat_at = claim.get("last_heartbeat_at")
    if last_heartbeat_at:
        result["last_heartbeat_at"] = str(last_heartbeat_at)
    heartbeat_interval_seconds = claim.get("heartbeat_interval_seconds")
    if heartbeat_interval_seconds is not None:
        try:
            result["heartbeat_interval_seconds"] = int(heartbeat_interval_seconds)
        except Exception:
            pass
    heartbeat_timeout_seconds = claim.get("heartbeat_timeout_seconds")
    if heartbeat_timeout_seconds is not None:
        try:
            result["heartbeat_timeout_seconds"] = int(heartbeat_timeout_seconds)
        except Exception:
            pass
    error_code = claim.get("error_code")
    if error_code and "error_code" not in result:
        result["error_code"] = str(error_code)
    error_message = claim.get("error_message")
    if error_message and "message" not in result:
        result["message"] = str(error_message)
    exc_type = claim.get("exception_type")
    if exc_type:
        result["exception_type"] = str(exc_type)
    blockers = claim.get("blockers")
    if blockers and isinstance(blockers, list):
        result["blockers"] = [str(b) for b in blockers]
    warnings = claim.get("warnings")
    if warnings and isinstance(warnings, list):
        result["warnings"] = [str(w) for w in warnings]
