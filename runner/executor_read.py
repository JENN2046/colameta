import json
import os
import subprocess
from datetime import datetime, timezone
from typing import Any

from runner.executor_confirmation_store import ExecutorConfirmationStore
from runner.executor_events import ExecutorEventStore
from runner.executor_run_claims import ExecutorRunClaimStore, parse_iso_datetime
from runner.executor_run_reports import ExecutorRunReportStore
from runner.executor_run_workflow import ExecutorRunOnceService
from runner.executor_session import ExecutorSessionStore
from runner.mcp_executor_workflow import (
    MCPExecutorWorkflowManager,
    PREVIEWS_DIR,
)


def _safe_str(value: Any, default: str = "") -> str:
    if isinstance(value, str):
        return value
    return default


def _safe_int(value: Any, default: int) -> int:
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except (ValueError, TypeError):
            return default
    return default


def _safe_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            result.append(text)
    return result


def _event_data(event: dict[str, Any]) -> dict[str, Any]:
    data = event.get("data") if isinstance(event, dict) else None
    return data if isinstance(data, dict) else {}


def _extract_run_scoped_diff_from_events(
    events: list[dict[str, Any]],
    preexisting_runner_files: set | None = None,
) -> dict[str, Any]:
    """Return changed files evidenced by this executor run's own events.

    Do not inspect the current Git worktree here: live status can outlive the run
    that created the worktree diff, so global diff would be wrongly attributed to
    stale/orphaned claims.
    """
    for event in reversed(events or []):
        if not isinstance(event, dict) or event.get("event_type") != "git_diff_changed":
            continue
        data = _event_data(event)
        changed_files = _safe_list(data.get("changed_files"))
        runner_metadata = _safe_list(data.get("runner_metadata_changed_files"))
        if preexisting_runner_files is not None:
            combined = changed_files + runner_metadata
            runner_metadata = [f for f in combined if f in preexisting_runner_files]
            changed_files = [f for f in combined if f not in preexisting_runner_files]
        return {
            "available": True,
            "changed_files": changed_files,
            "runner_metadata_changed_files": runner_metadata,
            "diff_summary": _safe_str(data.get("diff_summary"))[:2000],
        }
    return {
        "available": False,
        "changed_files": [],
        "runner_metadata_changed_files": [],
        "diff_summary": "",
    }


def _claim_latest_timestamp(claim: dict[str, Any] | None) -> datetime | None:
    if not isinstance(claim, dict):
        return None
    timestamps: list[datetime] = []
    for key in ("finished_at", "last_heartbeat_at", "worker_started_at", "thread_started_at", "claimed_at"):
        parsed = parse_iso_datetime(str(claim.get(key) or ""))
        if parsed:
            timestamps.append(parsed)
    return max(timestamps) if timestamps else None


def _report_finished_timestamp(report_summary: dict[str, Any] | None, report_detail: dict[str, Any] | None = None) -> datetime | None:
    candidates: list[str] = []
    if isinstance(report_summary, dict):
        candidates.append(str(report_summary.get("finished_at") or ""))
    if isinstance(report_detail, dict):
        candidates.append(str(report_detail.get("finished_at") or ""))
        candidates.append(str(report_detail.get("report", {}).get("finished_at") or "") if isinstance(report_detail.get("report"), dict) else "")
    for value in candidates:
        parsed = parse_iso_datetime(value)
        if parsed:
            return parsed
    return None


def _report_is_newer_than_claim(report_summary: dict[str, Any] | None, report_detail: dict[str, Any] | None, claim: dict[str, Any] | None) -> bool:
    report_at = _report_finished_timestamp(report_summary, report_detail)
    claim_at = _claim_latest_timestamp(claim)
    if report_at is None or claim_at is None:
        return False
    return report_at > claim_at


def _extract_executor_interruption_from_report(report: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(report, dict):
        return None
    completion_evidence = report.get("completion_evidence")
    if not isinstance(completion_evidence, dict):
        return None
    if _safe_str(completion_evidence.get("mode")) != "executor_interrupted":
        return None

    changed_files_raw = completion_evidence.get("executor_changed_files")
    changed_files = [
        str(item).strip()
        for item in changed_files_raw
        if str(item).strip()
    ] if isinstance(changed_files_raw, list) else []
    if not changed_files:
        report_changed_files = report.get("changed_files")
        if isinstance(report_changed_files, list):
            changed_files = [
                str(item).strip()
                for item in report_changed_files
                if str(item).strip()
            ]

    recovery_options_raw = completion_evidence.get("recovery_options")
    recovery_options = [
        str(item).strip()
        for item in recovery_options_raw
        if str(item).strip()
    ] if isinstance(recovery_options_raw, list) else []

    return {
        "present": True,
        "classification": _safe_str(completion_evidence.get("classification")),
        "error_code": _safe_str(completion_evidence.get("error_code")),
        "interruption_kind": _safe_str(completion_evidence.get("interruption_kind")),
        "provider_status": _safe_str(completion_evidence.get("provider_status")),
        "recovery_options": recovery_options,
        "changed_files": changed_files,
        "executor_changed_files": changed_files,
        "has_partial_worktree": bool(completion_evidence.get("has_partial_worktree")) or bool(changed_files),
        "report_id": _safe_str(report.get("report_id")),
    }


def _load_executor_interruption(project_root: str, report_id: str) -> dict[str, Any] | None:
    if not report_id:
        return None
    try:
        store = ExecutorRunReportStore(project_root)
        detail = store.get_report(report_id=report_id, include_markdown=False)
    except Exception:
        return None
    if not isinstance(detail, dict) or not detail.get("ok"):
        return None
    report = detail.get("report")
    return _extract_executor_interruption_from_report(report if isinstance(report, dict) else None)


def _read_preview_artifact(project_root: str, preview_id: str) -> dict[str, Any] | None:
    if not preview_id:
        return None
    try:
        store = ExecutorConfirmationStore(project_root, PREVIEWS_DIR, 3600)
        artifact = store.read_artifact(preview_id)
    except Exception:
        return None
    return artifact if isinstance(artifact, dict) else None


def _extract_session_id_from_record(record: dict[str, Any] | None) -> str:
    if not isinstance(record, dict):
        return ""
    for key in ("session_id", "conversation_id"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _session_mode_from_source(source: Any) -> str:
    source_text = _safe_str(source).strip().lower()
    if source_text in {"codex_exec_resume", "opencode_run_resume"}:
        return "resume"
    if source_text:
        return "new"
    return ""


def _session_mode_from_preview_artifact(project_root: str, preview_id: str) -> str:
    artifact = _read_preview_artifact(project_root, preview_id)
    if not isinstance(artifact, dict):
        return ""
    continuation = artifact.get("executor_session_continuation_facts")
    default_behavior = continuation.get("default_behavior") if isinstance(continuation, dict) else None
    if isinstance(default_behavior, dict):
        if default_behavior.get("will_resume_session") is True:
            return "resume"
        if default_behavior.get("will_start_new_session") is True:
            return "new"
    decision = artifact.get("continuation_decision")
    if isinstance(decision, dict):
        if decision.get("should_resume") is True:
            return "resume"
        if decision.get("should_start_new") is True:
            return "new"
    return ""


def _extract_session_snapshot(
    project_root: str,
    *,
    claim: dict[str, Any] | None,
    preview_id: str,
    report_lineage: dict[str, Any] | None,
) -> dict[str, Any]:
    record: dict[str, Any] = {}
    try:
        status = ExecutorSessionStore(project_root).get_status()
        loaded = status.get("record") if isinstance(status, dict) else None
        if isinstance(loaded, dict):
            record = loaded
    except Exception:
        record = {}

    claim_status = _safe_str(claim.get("status")) if isinstance(claim, dict) else ""
    claim_provider = _safe_str(claim.get("provider")) if isinstance(claim, dict) else ""
    claim_version = _safe_str(claim.get("current_version")) if isinstance(claim, dict) else ""
    record_provider = _safe_str(record.get("provider"))
    record_version = _safe_str(record.get("version"))
    record_matches_claim = (
        bool(record)
        and (not claim_provider or not record_provider or claim_provider == record_provider)
        and (not claim_version or not record_version or claim_version == record_version)
    )

    session_mode = ""
    if isinstance(report_lineage, dict):
        if bool(report_lineage.get("used_resume")):
            session_mode = "resume"
        elif report_lineage:
            session_mode = "new"
    if not session_mode and preview_id:
        session_mode = _session_mode_from_preview_artifact(project_root, preview_id)
    if not session_mode:
        session_mode = _session_mode_from_source(record.get("source"))
    if not session_mode:
        session_mode = "new"

    session_id_full = ""
    if claim_status.upper() == "RUNNING" and not isinstance(report_lineage, dict):
        if session_mode == "resume" and record_matches_claim:
            session_id_full = _extract_session_id_from_record(record)
    elif record_matches_claim:
        session_id_full = _extract_session_id_from_record(record)

    return {
        "session_id_full": session_id_full,
        "session_mode": session_mode,
        "session_mode_label": "续接" if session_mode == "resume" else "新开",
    }


def build_live_snapshot(
    project_root: str,
    run_id: str,
    preview_id: str = "",
    max_events: int = 50,
    preexisting_runner_files: set | None = None,
) -> dict[str, Any]:
    if not run_id:
        return {"available": False}
    project_root = os.path.abspath(os.path.expanduser(project_root))
    event_store = ExecutorEventStore(project_root)
    events = event_store.read(run_id, limit=max_events) if event_store.has_events(run_id) else []

    heartbeat_age: float | None = None
    heartbeat_stale: bool = False
    claim_status: str = ""
    claim_found: bool = False

    claims_store = ExecutorRunClaimStore(
        project_root,
        os.path.join(resolve_project_runner_rel_dir(project_root), "runtime", "executor-workflow-previews"),
        "claims",
        5, 3, 20,
    )
    if preview_id:
        claim = claims_store.read_claim(preview_id)
    else:
        claim = claims_store.find_claim_by_run_id(run_id)

    if isinstance(claim, dict):
        claim_found = True
        claim_status = str(claim.get("status") or "")
        orphan_info = claims_store.evaluate_orphaned_claim(claim)
        if orphan_info.get("orphaned"):
            heartbeat_stale = True
        last_hb_raw = str(claim.get("last_heartbeat_at") or "")
        if last_hb_raw:
            hb_dt = parse_iso_datetime(last_hb_raw)
            if hb_dt:
                heartbeat_age = (datetime.now(timezone.utc) - hb_dt).total_seconds()

    run_diff = _extract_run_scoped_diff_from_events(events, preexisting_runner_files)
    changed_files = run_diff["changed_files"]
    runner_metadata_changed_files = run_diff["runner_metadata_changed_files"]
    diff_summary = run_diff["diff_summary"]
    if not run_diff["available"] and not claim_found:
        # Compatibility path for ad-hoc snapshots without a run claim. Diagnostics
        # that require a claim still use run-scoped evidence only.
        changed_files_raw: list[str] = []
        try:
            changed_files_raw = ExecutorRunOnceService(project_root)._get_changed_files_from_git()
            proc_stat = subprocess.run(
                ["git", "diff", "--stat"],
                cwd=project_root,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if proc_stat.returncode == 0:
                diff_summary = proc_stat.stdout.strip()[:2000]
        except Exception:
            changed_files_raw = []
        if preexisting_runner_files is not None:
            runner_metadata_changed_files = [f for f in changed_files_raw if f in preexisting_runner_files]
            changed_files = [f for f in changed_files_raw if f not in preexisting_runner_files]
        else:
            runner_metadata_changed_files = [f for f in changed_files_raw if is_project_runner_path(f)]
            changed_files = [f for f in changed_files_raw if not is_project_runner_path(f)]

    report_available = False
    report_id = ""
    report_lineage: dict[str, Any] = {}
    try:
        report_store = ExecutorRunReportStore(project_root)
        report = report_store.get_report(latest=True, include_markdown=False)
        if isinstance(report, dict) and report.get("ok"):
            r = report.get("report", {})
            if isinstance(r, dict):
                lineage = r.get("execution_lineage", {})
                lineage_run_id = str(lineage.get("run_id", "")) if isinstance(lineage, dict) else ""
                if lineage_run_id == run_id:
                    report_available = True
                    report_id = str(r.get("report_id") or "")
                    report_lineage = dict(lineage) if isinstance(lineage, dict) else {}
    except Exception:
        pass

    diagnostics: list[str] = []
    if claim_found and claim_status == "RUNNING" and heartbeat_stale:
        diagnostics.append("EXECUTOR_RUN_ORPHANED")
    if claim_found and claim_status == "RUNNING" and changed_files and not report_available:
        diagnostics.append("RUN_CHANGED_WITHOUT_REPORT")

    session_snapshot = _extract_session_snapshot(
        project_root,
        claim=claim if isinstance(claim, dict) else None,
        preview_id=preview_id,
        report_lineage=report_lineage if report_lineage else None,
    )

    snapshot: dict[str, Any] = {
        "available": True,
        "run_id": run_id,
        "preview_id": preview_id,
        "claim_status": claim_status,
        "claim_found": claim_found,
        "events": events,
        "event_count": len(events),
        "heartbeat": {
            "age_seconds": heartbeat_age,
            "stale": heartbeat_stale,
            "stale_threshold_seconds": _safe_int(claim.get("heartbeat_timeout_seconds"), 20) if isinstance(claim, dict) else 20,
        },
        "changed_files": changed_files,
        "changed_file_count": len(changed_files),
        "runner_metadata_changed_files": runner_metadata_changed_files,
        "runner_metadata_changed_file_count": len(runner_metadata_changed_files),
        "diff_summary": diff_summary[:2000],
        "report_available": report_available,
        "report_id": report_id,
        "diagnostics": diagnostics,
        "session_id_full": session_snapshot["session_id_full"],
        "session_mode": session_snapshot["session_mode"],
        "session_mode_label": session_snapshot["session_mode_label"],
    }
    if isinstance(claim, dict):
        snapshot["claim"] = {
            "status": str(claim.get("status") or ""),
            "last_heartbeat_at": str(claim.get("last_heartbeat_at") or ""),
            "provider": str(claim.get("provider") or ""),
            "current_version": str(claim.get("current_version") or ""),
            "model": claim.get("model") or "",
            "model_source": claim.get("model_source") or "",
        }
    return snapshot


def handle_inspect_executor_activity(
    project_root: str,
    action: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    if action == "run_status":
        return _run_status(project_root, params)
    elif action == "latest_run_status":
        return _latest_run_status(project_root, params)
    elif action == "list_reports":
        return _list_reports(project_root, params)
    elif action == "get_report":
        return _get_report(project_root, params)
    elif action == "get_audit_summary":
        return _get_audit_summary(project_root, params)
    else:
        return {
            "ok": False,
            "error_code": "UNKNOWN_ACTION",
            "message": "不支持的 action。支持：run_status、latest_run_status、list_reports、get_report、get_audit_summary。",
        }


def _run_status(project_root: str, params: dict[str, Any]) -> dict[str, Any]:
    run_id = _safe_str(params.get("run_id"))
    preview_id = _safe_str(params.get("preview_id"))
    if not run_id and not preview_id:
        return {
            "ok": True,
            "action": "run_status",
            "status": "not_found",
            "message": "请提供 run_id 或 preview_id。",
        }
    manager = MCPExecutorWorkflowManager(project_root)
    result = manager.handle("status", {
        "run_id": run_id,
        "preview_id": preview_id,
        "poll_attempt": 1,
    })
    result["action"] = "run_status"
    resolved_run_id = _safe_str(result.get("run_id")) or run_id
    resolved_preview_id = _safe_str(result.get("preview_id")) or preview_id
    if resolved_run_id:
        live = build_live_snapshot(project_root, resolved_run_id, preview_id=resolved_preview_id)
        result["live"] = live
    report_id = _safe_str(result.get("report_id"))
    if not report_id and isinstance(result.get("live"), dict):
        report_id = _safe_str(result["live"].get("report_id"))
    interruption = _load_executor_interruption(project_root, report_id)
    if interruption:
        result["executor_interruption"] = interruption
    return result


def _latest_run_status(project_root: str, params: dict[str, Any]) -> dict[str, Any]:
    try:
        return _latest_run_status_impl(project_root, params)
    except Exception as exc:
        return {
            "ok": True,
            "action": "latest_run_status",
            "status": "not_found",
            "found": False,
            "warning": "LATEST_RUN_STATUS_UNAVAILABLE",
            "message": f"无法读取最近执行器状态：{exc}",
        }


def _latest_run_status_impl(project_root: str, params: dict[str, Any]) -> dict[str, Any]:
    store = ExecutorRunReportStore(project_root)
    claims_store = ExecutorRunClaimStore(
        project_root,
        os.path.join(resolve_project_runner_rel_dir(project_root), "runtime", "executor-workflow-previews"),
        "claims",
        5, 3, 20,
    )

    active_claim: dict[str, Any] | None = None
    try:
        active_claim = claims_store.find_active_claim(status="RUNNING")
    except Exception:
        pass

    active_run_id = str(active_claim.get("run_id", "")) if active_claim else ""
    active_preview_id = str(active_claim.get("preview_id", "")) if active_claim else ""

    reports = store.list_reports(limit=1)
    report = reports[0] if reports else None
    report_id = report.get("report_id", "") if report else ""

    if active_run_id:
        live = build_live_snapshot(project_root, active_run_id, preview_id=active_preview_id, max_events=8)
        diagnostics = live.get("diagnostics") if isinstance(live, dict) else None
        is_orphaned = isinstance(diagnostics, list) and "EXECUTOR_RUN_ORPHANED" in diagnostics
        report_run_id = ""
        detail: dict[str, Any] | None = None
        full_report: dict[str, Any] | None = None
        interruption: dict[str, Any] | None = None
        if report and report_id:
            loaded_detail = store.get_report(report_id=report_id, include_markdown=False)
            if isinstance(loaded_detail, dict):
                detail = loaded_detail
            if isinstance(detail, dict) and detail.get("ok"):
                loaded_report = detail.get("report", {})
                if isinstance(loaded_report, dict):
                    full_report = loaded_report
                    lineage = full_report.get("execution_lineage", {})
                    if isinstance(lineage, dict):
                        report_run_id = str(lineage.get("run_id") or "")
                    interruption = _extract_executor_interruption_from_report(full_report)

        if is_orphaned and report and _report_is_newer_than_claim(report, detail, active_claim):
            result = {
                "ok": True,
                "action": "latest_run_status",
                "status": _safe_str(full_report.get("status"), "unknown") if isinstance(full_report, dict) else "unknown",
                "found": True,
                "live": {"available": False},
                "latest_report": dict(report) if isinstance(report, dict) else {},
                "stale_orphan_claim": live,
                "message": "已忽略旧 orphan RUNNING claim；最新报告比该 claim 更新。",
            }
            if interruption and report_run_id == active_run_id:
                result["executor_interruption"] = interruption
            return result

        result: dict[str, Any] = {
            "ok": True,
            "action": "latest_run_status",
            "status": "orphaned" if is_orphaned else "running",
            "found": True,
            "live": live,
        }
        if report and report_id:
            if interruption and report_run_id == active_run_id:
                result["executor_interruption"] = interruption
            if report_run_id and report_run_id != active_run_id:
                result["stale_report"] = dict(report) if isinstance(report, dict) else {}
            else:
                result["latest_report"] = dict(report) if isinstance(report, dict) else {}
        return result

    if not reports:
        return {
            "ok": True,
            "action": "latest_run_status",
            "status": "not_found",
            "found": False,
            "message": "没有执行器运行记录。",
        }

    report_detail = store.get_report(report_id=report_id, include_markdown=False)
    status = report_detail.get("report", {}).get("status", "unknown") if report_detail.get("ok") else "unknown"

    result = {
        "ok": True,
        "action": "latest_run_status",
        "status": status,
        "found": True,
        "latest_report": report,
        "message": None,
    }
    if isinstance(report_detail, dict) and report_detail.get("ok"):
        full_report = report_detail.get("report")
        interruption = _extract_executor_interruption_from_report(full_report if isinstance(full_report, dict) else None)
        if interruption:
            result["executor_interruption"] = interruption

    any_claim: dict[str, Any] | None = None
    try:
        any_claim = claims_store.find_active_claim(status="RUNNING")
        if not any_claim:
            any_claim = claims_store.find_active_claim(status="COMPLETED")
        if not any_claim:
            any_claim = claims_store.find_active_claim(status="FAILED")
    except Exception:
        pass
    if any_claim:
        c_run_id = str(any_claim.get("run_id", ""))
        c_preview_id = str(any_claim.get("preview_id", ""))
        if c_run_id:
            live = build_live_snapshot(project_root, c_run_id, preview_id=c_preview_id, max_events=8)
            if live.get("available"):
                result["live"] = live

    return result


def _list_reports(project_root: str, params: dict[str, Any]) -> dict[str, Any]:
    version_raw = params.get("version")
    version: str | None = None
    if version_raw is not None:
        if not isinstance(version_raw, str) or not version_raw.strip():
            return {
                "ok": False,
                "error_code": "INVALID_VERSION",
                "message": "version 必须是字符串。",
            }
        version = version_raw.strip()
    limit = _safe_int(params.get("limit"), 10)
    limit = max(1, min(limit, 50))
    store = ExecutorRunReportStore(project_root)
    reports = store.list_reports(version=version, limit=limit)
    result: dict[str, Any] = {
        "ok": True,
        "action": "list_reports",
        "reports": reports,
    }
    if not reports:
        result["message"] = "没有找到执行器运行报告。"
    return result


def _get_report(project_root: str, params: dict[str, Any]) -> dict[str, Any]:
    version_raw = params.get("version")
    report_id_raw = params.get("report_id")
    latest = True
    if isinstance(params.get("latest"), bool):
        latest = params["latest"]
    include_markdown = True
    if isinstance(params.get("include_markdown"), bool):
        include_markdown = params["include_markdown"]
    max_report_chars = _safe_int(params.get("max_report_chars"), 30000)
    max_report_chars = max(1, min(max_report_chars, 60000))
    version: str | None = None
    if version_raw is not None:
        if not isinstance(version_raw, str) or not version_raw.strip():
            return {
                "ok": False,
                "error_code": "INVALID_VERSION",
                "message": "version 必须是字符串。",
            }
        version = version_raw.strip()
    report_id: str | None = None
    if report_id_raw is not None:
        if not isinstance(report_id_raw, str) or not report_id_raw.strip():
            return {
                "ok": False,
                "error_code": "INVALID_REPORT_ID",
                "message": "report_id 必须是字符串。",
            }
        report_id = report_id_raw.strip()
    store = ExecutorRunReportStore(project_root)
    result = store.get_report(
        version=version,
        report_id=report_id,
        latest=latest,
        include_markdown=include_markdown,
        max_markdown_chars=max_report_chars,
    )
    if not result.get("ok"):
        return result
    report = result.get("report", {})
    if isinstance(report, dict):
        lineage = report.get("execution_lineage")
        run_id = str(lineage.get("run_id") or "") if isinstance(lineage, dict) else ""
        if run_id and not isinstance(report.get("events"), list):
            events = ExecutorEventStore(project_root).read(run_id, limit=10)
            if events:
                report = dict(report)
                report["events"] = events
    return {
        "ok": True,
        "action": "get_report",
        "report": report if isinstance(report, dict) else {},
        "report_markdown": result.get("report_markdown"),
        "truncated": result.get("truncated", False),
    }


def _get_audit_summary(project_root: str, params: dict[str, Any]) -> dict[str, Any]:
    version_raw = params.get("version")
    section = _safe_str(params.get("section"), "summary")
    if section not in ("summary", "lineage", "scope", "report_excerpt"):
        section = "summary"
    manager = MCPExecutorWorkflowManager(project_root)
    result = manager.handle("get_audit_package", {
        "version": version_raw or "",
        "section": section,
    })
    if not result.get("ok"):
        return result
    return {
        "ok": True,
        "action": "get_audit_summary",
        "section": result.get("section", section),
        "source": result.get("source"),
        "summary": result.get("summary"),
        "lineage": result.get("lineage"),
        "validation": result.get("validation"),
        "scope": result.get("scope"),
        "report_excerpt": result.get("report_excerpt"),
    }
from runner.runner_paths import (
    is_project_runner_path,
    resolve_project_runner_rel_dir,
)
