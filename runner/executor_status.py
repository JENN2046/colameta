from datetime import datetime, timezone
import re
from typing import Any

from runner.executor_run_claims import parse_iso_datetime
from runner.executor_events import (
    ExecutorEventIntegrityError,
    ExecutorEventStore,
    public_executor_projection,
)


HEARTBEAT_ONLY_STALE_SECONDS = 120
_HEARTBEAT_ONLY_IGNORED_EVENTS = {"heartbeat"}
DEFAULT_POLLING_PROFILE_ID = "web_gpt_commander"
_POLLING_PROFILE_CONFIGS: dict[str, dict[str, Any]] = {
    "web_gpt_commander": {
        "next_poll_after_seconds": 3,
        "max_poll_attempts": 3,
        "policy": "non_blocking_polling",
        "on_exhausted": "stop_and_ask_user_to_check_later",
        "reason": "External Web GPT connectors should not stay in long tool loops.",
    },
    "planner_agent": {
        "next_poll_after_seconds": 3,
        "max_poll_attempts": 3,
        "policy": "non_blocking_polling",
        "on_exhausted": "stop_and_ask_user_to_check_later",
        "reason": "Planner agents should hand off long-running executor observation.",
    },
    "reviewer_agent": {
        "next_poll_after_seconds": 3,
        "max_poll_attempts": 3,
        "policy": "non_blocking_polling",
        "on_exhausted": "stop_and_ask_user_to_check_later",
        "reason": "Reviewer agents should avoid long executor polling loops.",
    },
    "source_observer": {
        "next_poll_after_seconds": 3,
        "max_poll_attempts": 3,
        "policy": "non_blocking_polling",
        "on_exhausted": "stop_and_ask_user_to_check_later",
        "reason": "Source observers are read-only and should not follow long executor runs.",
    },
    "local_codex_commander": {
        "next_poll_after_seconds": 5,
        "max_poll_attempts": 24,
        "policy": "bounded_local_polling",
        "on_exhausted": "stop_and_report_background_run_still_active",
        "reason": "Local Codex can safely follow a bounded long-running executor task.",
    },
}
_PUBLIC_EXECUTOR_CLAIM_FIELDS = frozenset({
    "status",
    "run_id",
    "preview_id",
    "model",
    "model_source",
    "claimed_at",
    "finished_at",
    "report_id",
    "worker_pid",
    "thread_started_at",
    "worker_started_at",
    "last_heartbeat_at",
    "heartbeat_interval_seconds",
    "heartbeat_timeout_seconds",
    "error_code",
    "error_message",
    "exception_type",
    "blockers",
    "warnings",
})


def _collect_private_claim_values(value: Any) -> set[str]:
    private_values: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).strip().lower() in {
                "executor_authority_id", "admission_sha256", "authority_id",
                "authority_alias", "executor_authority", "fresh_executor_authority_id",
                "expected_executor_authority_id", "expected_admission_sha256",
                "admission_hash", "admission_digest", "admission_alias",
            } and isinstance(child, str) and child:
                private_values.add(child)
            private_values.update(_collect_private_claim_values(child))
    elif isinstance(value, (list, tuple)):
        for child in value:
            private_values.update(_collect_private_claim_values(child))
    return private_values


def _redact_private_claim_aliases(value: Any, private_values: set[str]) -> Any:
    def redact(text: str) -> str:
        redacted = text
        for private_value in private_values:
            redacted = re.sub(
                re.escape(private_value),
                "[private-lineage-redacted]",
                redacted,
                flags=re.IGNORECASE,
            )
        return redacted

    if isinstance(value, dict):
        return {
            redact(str(key)): _redact_private_claim_aliases(child, private_values)
            for key, child in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact_private_claim_aliases(child, private_values) for child in value]
    if isinstance(value, str):
        return redact(value)
    return value


def polling_guidance_for_profile(profile_id: str | None = None) -> dict[str, Any]:
    requested_profile_id = str(profile_id or "").strip() or DEFAULT_POLLING_PROFILE_ID
    selected_profile_id = requested_profile_id
    fallback_profile_id = ""
    if requested_profile_id not in _POLLING_PROFILE_CONFIGS:
        selected_profile_id = DEFAULT_POLLING_PROFILE_ID
        fallback_profile_id = DEFAULT_POLLING_PROFILE_ID
    config = _POLLING_PROFILE_CONFIGS[selected_profile_id]
    interval = int(config["next_poll_after_seconds"])
    attempts = int(config["max_poll_attempts"])
    guidance = {
        "profile_id": selected_profile_id,
        "requested_profile_id": requested_profile_id,
        "policy": str(config["policy"]),
        "next_poll_after_seconds": interval,
        "max_poll_attempts": attempts,
        "max_total_poll_seconds": interval * attempts,
        "on_exhausted": str(config["on_exhausted"]),
        "reason": str(config["reason"]),
    }
    if fallback_profile_id:
        guidance["fallback_profile_id"] = fallback_profile_id
        guidance["warning"] = "UNKNOWN_POLLING_PROFILE_USED_DEFAULT"
    return guidance


def _event_timestamp(event: dict[str, Any]) -> datetime | None:
    if not isinstance(event, dict):
        return None
    return parse_iso_datetime(str(event.get("timestamp") or event.get("ts") or ""))


def _is_meaningful_event(event: dict[str, Any]) -> bool:
    if not isinstance(event, dict):
        return False
    event_type = str(event.get("event_type") or event.get("event") or "").strip()
    if not event_type or event_type in _HEARTBEAT_ONLY_IGNORED_EVENTS:
        return False
    data = event.get("data")
    if event_type == "executor_tool_event" and isinstance(data, dict):
        stage = str(data.get("stage") or "").strip()
        return bool(stage)
    return True


def analyze_meaningful_progress(
    events: list[dict[str, Any]] | None,
    *,
    stale_after_seconds: int = HEARTBEAT_ONLY_STALE_SECONDS,
) -> dict[str, Any]:
    meaningful_events = [event for event in (events or []) if _is_meaningful_event(event)]
    if not meaningful_events:
        return {
            "available": False,
            "stale": False,
            "age_seconds": None,
            "event_type": "",
            "stage": "",
            "timestamp": "",
        }
    latest = meaningful_events[-1]
    ts = _event_timestamp(latest)
    age_seconds = None
    stale = False
    if ts is not None:
        age_seconds = (datetime.now(timezone.utc) - ts).total_seconds()
        stale = age_seconds > max(1, int(stale_after_seconds))
    data = latest.get("data") if isinstance(latest.get("data"), dict) else {}
    return {
        "available": True,
        "stale": stale,
        "age_seconds": age_seconds,
        "stale_after_seconds": max(1, int(stale_after_seconds)),
        "event_type": str(latest.get("event_type") or latest.get("event") or ""),
        "stage": str(data.get("stage") or ""),
        "timestamp": str(latest.get("timestamp") or latest.get("ts") or ""),
    }


def read_executor_events_for_status(project_root: str, run_id: str, limit: int = 50) -> list[dict[str, Any]]:
    result = read_executor_events_for_status_result(project_root, run_id, limit=limit)
    events = result.get("events")
    if not result.get("ok"):
        raise ExecutorEventIntegrityError(
            str(result.get("error_code") or "EVENT_INTEGRITY_FAILED")
        )
    return events if isinstance(events, list) else []


def read_executor_events_for_status_result(
    project_root: str, run_id: str, limit: int = 50
) -> dict[str, Any]:
    if not run_id:
        return {"ok": False, "error_code": "EVENT_RUN_ID_INVALID", "events": []}
    store = ExecutorEventStore(project_root)
    result = store.read_with_integrity(run_id, limit=limit)
    if result.get("error_code") == "EVENT_STORE_NOT_FOUND":
        return {"ok": True, "error_code": None, "events": []}
    return result


def status_base_result(poll_attempt: int, *, profile_id: str | None = None) -> dict[str, Any]:
    polling_guidance = polling_guidance_for_profile(profile_id)
    max_poll_attempts = int(polling_guidance["max_poll_attempts"])
    polling_exhausted = poll_attempt > max_poll_attempts
    result: dict[str, Any] = {
        "ok": True,
        "action": "status",
        "status": "succeeded",
        "risk_level": "info",
        "polling_profile_id": polling_guidance["profile_id"],
        "next_poll_after_seconds": int(polling_guidance["next_poll_after_seconds"]),
        "max_poll_attempts": max_poll_attempts,
        "max_total_poll_seconds": int(polling_guidance["max_total_poll_seconds"]),
        "poll_attempt": poll_attempt,
        "remaining_poll_attempts": max(0, max_poll_attempts - poll_attempt),
        "polling_exhausted": polling_exhausted,
        "terminal": False,
        "executor_run_status": "unknown",
        "polling_guidance": polling_guidance,
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
        error_code = str(claim.get("error_code") or "")
        message = str(claim.get("error_message") or "")
        if error_code == "EXECUTOR_MODEL_QUOTA_EXHAUSTED":
            message = message or "执行器模型额度或 token 配额已耗尽。请更换模型、等待额度恢复，或检查执行器账号和配置。"
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
    events: list[dict[str, Any]] | None = None,
) -> None:
    private_values = _collect_private_claim_values(claim)
    projected_sources = _redact_private_claim_aliases(public_executor_projection({
        "claim": claim,
        "orphan_info": orphan_info,
        "events": events or [],
    }), private_values)
    projected_claim = projected_sources.get("claim", {})
    public_claim = (
        {
            key: value
            for key, value in projected_claim.items()
            if key in _PUBLIC_EXECUTOR_CLAIM_FIELDS
        }
        if isinstance(projected_claim, dict)
        else {}
    )
    public_orphan_info = projected_sources.get("orphan_info", {})
    if not isinstance(public_orphan_info, dict):
        public_orphan_info = {}
    public_events = projected_sources.get("events", [])
    if not isinstance(public_events, list):
        public_events = []

    classification = classify_claim_status(public_claim, public_orphan_info)
    claim_status = classification["preview_claim_status"]
    result["executor_run_status"] = classification["executor_run_status"]
    result["terminal"] = classification["terminal"]
    if classification.get("error_code"):
        result["error_code"] = classification["error_code"]
    if classification.get("message"):
        result["message"] = classification["message"]
    if possible_report_id and claim_status == "RUNNING" and public_orphan_info.get("orphaned") and not str(public_claim.get("report_id") or ""):
        result["possible_report_id"] = possible_report_id
    meaningful = analyze_meaningful_progress(public_events)
    result["last_meaningful_progress"] = meaningful
    if (
        claim_status == "RUNNING"
        and classification["executor_run_status"] == "running"
        and meaningful.get("available")
        and meaningful.get("stale")
    ):
        result["executor_run_status"] = "stalled"
        result["provider_status"] = "stalled_without_provider_error"
        result["terminal_reason"] = "executor_stalled_without_provider_error"
        result["message"] = "执行器 heartbeat 仍在刷新，但最近业务进展已过期；当前运行疑似停在 provider/server 等待阶段。"
        result["diagnostics"] = ["HEARTBEAT_ONLY_WITH_STALE_PROGRESS"]

    result["run_id"] = str(public_claim.get("run_id") or "")
    result["preview_id"] = str(public_claim.get("preview_id") or "")
    claim_model = public_claim.get("model")
    if claim_model:
        result["model"] = str(claim_model)
        result["model_source"] = str(public_claim.get("model_source") or "")
    result["preview_claim_status"] = claim_status
    result["claimed_at"] = str(public_claim.get("claimed_at") or "")
    result["finished_at"] = str(public_claim.get("finished_at") or "")
    result["report_id"] = str(public_claim.get("report_id") or "")
    if public_claim.get("worker_pid") is not None:
        result["worker_pid"] = public_claim.get("worker_pid")
    thread_started_at = public_claim.get("thread_started_at")
    if thread_started_at:
        result["thread_started_at"] = str(thread_started_at)
    worker_started_at = public_claim.get("worker_started_at")
    if worker_started_at:
        result["worker_started_at"] = str(worker_started_at)
    last_heartbeat_at = public_claim.get("last_heartbeat_at")
    if last_heartbeat_at:
        result["last_heartbeat_at"] = str(last_heartbeat_at)
    heartbeat_interval_seconds = public_claim.get("heartbeat_interval_seconds")
    if heartbeat_interval_seconds is not None:
        try:
            result["heartbeat_interval_seconds"] = int(heartbeat_interval_seconds)
        except Exception:
            pass
    heartbeat_timeout_seconds = public_claim.get("heartbeat_timeout_seconds")
    if heartbeat_timeout_seconds is not None:
        try:
            result["heartbeat_timeout_seconds"] = int(heartbeat_timeout_seconds)
        except Exception:
            pass
    error_code = public_claim.get("error_code")
    if error_code and "error_code" not in result:
        result["error_code"] = str(error_code)
    error_message = public_claim.get("error_message")
    if error_message and "message" not in result:
        result["message"] = str(error_message)
    exc_type = public_claim.get("exception_type")
    if exc_type:
        result["exception_type"] = str(exc_type)
    blockers = public_claim.get("blockers")
    if blockers and isinstance(blockers, list):
        result["blockers"] = [str(b) for b in blockers]
    warnings = public_claim.get("warnings")
    if warnings and isinstance(warnings, list):
        result["warnings"] = [str(w) for w in warnings]
    if result.get("error_code") == "EXECUTOR_MODEL_QUOTA_EXHAUSTED":
        result["terminal_reason"] = "executor_model_quota_exhausted"
        result["next_actions"] = [
            {
                "tool": "manage_executor_workflow",
                "action": "run_once_preview",
                "params": {"action": "run_once_preview"},
                "reason": "更换模型、等待额度恢复，或检查执行器账号和配置后重新生成执行预览。",
                "requires_confirmation": False,
            },
            {
                "tool": "manage_executor_workflow",
                "action": "preflight",
                "params": {"action": "preflight"},
                "reason": "检查当前执行器账号、配置和项目状态。",
                "requires_confirmation": False,
            },
        ]

    final_projection = _redact_private_claim_aliases(
        public_executor_projection({"claim": claim, "status": result}),
        private_values,
    )
    safe_result = final_projection.get("status") if isinstance(final_projection, dict) else None
    if isinstance(safe_result, dict):
        result.clear()
        result.update(safe_result)
