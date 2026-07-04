from __future__ import annotations

import json
import os
from typing import Any

from runner.executor_run_reports import ExecutorRunReportStore
from runner.mcp_executor_workflow import MCPExecutorWorkflowManager
from runner.mcp_stage_parallel_executor_group import MCPStageParallelExecutorGroupManager
from runner.mcp_stage_parallel_executor_runs import CLAIMS_DIR, EXECUTOR_PREVIEWS_RELATIVE_DIR
from runner.stage_parallel_plan import build_stage_parallel_group_status, build_stage_parallel_run_preview


RESULT_METADATA_DIR_PREFIXES = (
    ".colameta/runtime/",
    ".colameta/reports/",
    ".colameta/audits/",
)


def build_stage_parallel_executor_results_packet(
    *,
    project_root: str,
    project_name: str | None = None,
    stage_id: str | None = None,
    task_intents: list[dict[str, Any]] | None = None,
    max_parallel_tasks: int | None = None,
    provider: str | None = None,
    base_branch: str | None = None,
) -> dict[str, Any]:
    project_root_abs = os.path.abspath(os.path.expanduser(project_root or ""))
    run_preview = build_stage_parallel_run_preview(
        project_root=project_root_abs,
        project_name=project_name,
        stage_id=stage_id,
        task_intents=task_intents,
        max_parallel_tasks=max_parallel_tasks,
        provider=provider,
        base_branch=base_branch,
    )
    validations = MCPStageParallelExecutorGroupManager(project_root_abs)._validate_plan(run_preview)
    shard_results = [
        _build_shard_result(validation, provider=str(run_preview.get("provider") or provider or "codex"))
        for validation in validations
    ]
    executor_results = [_executor_result_for_group_status(item) for item in shard_results]
    group_status = build_stage_parallel_group_status(
        project_root=project_root_abs,
        project_name=project_name,
        stage_id=stage_id,
        task_intents=task_intents,
        max_parallel_tasks=max_parallel_tasks,
        provider=provider,
        base_branch=base_branch,
        executor_results=executor_results,
    )
    counts = _status_counts(shard_results)
    blockers = _packet_blockers(run_preview, shard_results)

    return {
        "ok": True,
        "source": "stage_parallel_executor_results_packet",
        "scope": "mcp:read",
        "read_only": True,
        "side_effects": False,
        "status": group_status.get("status") if not blockers else "blocked",
        "project_root": project_root_abs,
        "project_name": project_name,
        "stage_id": run_preview.get("stage_id"),
        "parallel_group_id": run_preview.get("parallel_group_id"),
        "result_summary": {
            "total": counts["total"],
            "planned": counts["planned"],
            "running": counts["running"],
            "succeeded": counts["succeeded"],
            "failed": counts["failed"],
            "blocked": counts["blocked"],
            "unknown": counts["unknown"],
            "executor_results_count": len(executor_results),
            "ready_for_merge_preview": bool(group_status.get("merge_readiness", {}).get("ready"))
            if isinstance(group_status.get("merge_readiness"), dict)
            else False,
        },
        "executor_results": executor_results,
        "shard_results": shard_results,
        "group_status_preview": {
            "status": group_status.get("status"),
            "status_counts": group_status.get("status_counts"),
            "merge_readiness": group_status.get("merge_readiness"),
            "blocking_reasons": group_status.get("blocking_reasons", []),
            "suggested_next_action": group_status.get("suggested_next_action"),
        },
        "blocking_reasons": blockers,
        "risk_level": "blocked" if blockers else group_status.get("risk_level", "info"),
        "suggested_next_action": (
            "build_stage_parallel_merge_preview"
            if isinstance(group_status.get("merge_readiness"), dict)
            and group_status.get("merge_readiness", {}).get("ready") is True
            else "wait_for_executor_results"
            if counts["running"] or counts["planned"]
            else "resolve_parallel_group_blockers"
            if blockers or counts["failed"] or counts["blocked"] or counts["unknown"]
            else "keep_planning"
        ),
        "authority_boundary": _authority_boundary(),
        "safe_next_actions": _safe_next_actions(group_status, counts, blockers),
    }


def _build_shard_result(validation: dict[str, Any], *, provider: str) -> dict[str, Any]:
    task_id = str(validation.get("task_id") or "")
    worktree_path = str(validation.get("worktree_path") or "")
    branch_name = str(validation.get("branch_name") or "")
    blockers = _result_stage_validation_blockers(validation)
    if blockers:
        return {
            "task_id": task_id,
            "title": validation.get("title"),
            "status": "blocked",
            "validation_status": "blocked",
            "worktree_path": worktree_path,
            "branch_name": branch_name,
            "changed_files": [],
            "summary": _summary_from_blockers("worktree validation blocked", blockers),
            "blockers": blockers,
        }

    located = _latest_preview_and_claim(worktree_path, validation, provider=provider)
    artifact = located.get("artifact") if isinstance(located.get("artifact"), dict) else None
    claim = located.get("claim") if isinstance(located.get("claim"), dict) else None
    if artifact is None:
        return {
            "task_id": task_id,
            "title": validation.get("title"),
            "status": "planned",
            "validation_status": "not_run",
            "worktree_path": worktree_path,
            "branch_name": branch_name,
            "changed_files": [],
            "summary": "executor preview artifact not created",
            "blockers": [],
        }

    preview_id = str(artifact.get("preview_id") or "")
    base = {
        "task_id": task_id,
        "title": validation.get("title"),
        "worktree_path": worktree_path,
        "branch_name": branch_name,
        "executor_preview_id": preview_id,
        "provider": str(artifact.get("provider") or provider),
        "current_head": str(artifact.get("current_head") or ""),
        "current_version": str(artifact.get("current_version") or ""),
    }
    if claim is None:
        return {
            **base,
            "status": "planned",
            "validation_status": "not_run",
            "changed_files": [],
            "summary": "executor preview ready; run not started",
            "blockers": [],
        }

    status_payload = MCPExecutorWorkflowManager(worktree_path).handle(
        "status",
        {
            "preview_id": preview_id,
            "profile_id": "local_codex_commander",
        },
    )
    mapped = _map_status_payload(status_payload)
    report_summary = _report_summary(worktree_path, claim, fallback_head=str(artifact.get("current_head") or ""))
    if report_summary.get("available"):
        mapped.update(_map_report_summary(report_summary))

    return {
        **base,
        "status": mapped["status"],
        "validation_status": mapped["validation_status"],
        "head": mapped.get("head") or str(artifact.get("current_head") or ""),
        "changed_files": mapped.get("changed_files", []),
        "summary": mapped.get("summary") or "",
        "run_id": str(claim.get("run_id") or status_payload.get("run_id") or ""),
        "preview_claim_status": str(status_payload.get("preview_claim_status") or claim.get("status") or ""),
        "executor_run_status": str(status_payload.get("executor_run_status") or ""),
        "terminal": bool(status_payload.get("terminal") is True),
        "report_id": str(claim.get("report_id") or ""),
        "claimed_at": str(claim.get("claimed_at") or ""),
        "finished_at": str(claim.get("finished_at") or ""),
        "blockers": _status_blockers(status_payload),
    }


def _latest_preview_and_claim(worktree_path: str, validation: dict[str, Any], *, provider: str) -> dict[str, Any]:
    preview_dir = os.path.join(worktree_path, EXECUTOR_PREVIEWS_RELATIVE_DIR)
    if not os.path.isdir(preview_dir):
        return {}
    candidates: list[tuple[str, dict[str, Any], dict[str, Any] | None]] = []
    for filename in sorted(os.listdir(preview_dir)):
        if not filename.endswith(".json"):
            continue
        path = os.path.join(preview_dir, filename)
        if not os.path.isfile(path):
            continue
        artifact = _read_json(path)
        if not _artifact_matches(artifact, validation, provider=provider, worktree_path=worktree_path):
            continue
        preview_id = str(artifact.get("preview_id") or filename[:-5])
        claim = _read_json(os.path.join(preview_dir, CLAIMS_DIR, f"{preview_id}.json"))
        sort_value = str((claim or {}).get("claimed_at") or artifact.get("created_at") or preview_id)
        candidates.append((sort_value, artifact, claim))
    if not candidates:
        return {}
    candidates.sort(key=lambda item: item[0], reverse=True)
    _, artifact, claim = candidates[0]
    return {"artifact": artifact, "claim": claim}


def _artifact_matches(artifact: Any, validation: dict[str, Any], *, provider: str, worktree_path: str) -> bool:
    if not isinstance(artifact, dict):
        return False
    if str(artifact.get("artifact_kind") or "") != "run_once":
        return False
    if os.path.abspath(str(artifact.get("project_root") or "")) != os.path.abspath(worktree_path):
        return False
    if str(artifact.get("provider") or "") != provider:
        return False
    state = validation.get("worktree_state") if isinstance(validation.get("worktree_state"), dict) else {}
    expected_head = str(state.get("head") or "")
    expected_branch = str(validation.get("branch_name") or "")
    if expected_head and str(artifact.get("current_head") or "") != expected_head:
        return False
    if expected_branch and str(artifact.get("current_branch") or "") != expected_branch:
        return False
    return True


def _map_status_payload(status_payload: dict[str, Any]) -> dict[str, Any]:
    executor_status = str(status_payload.get("executor_run_status") or "unknown")
    if executor_status in {"running", "stalled"}:
        return {
            "status": "running",
            "validation_status": "running",
            "changed_files": [],
            "summary": f"executor_run_status={executor_status}",
        }
    if executor_status == "completed":
        return {
            "status": "succeeded",
            "validation_status": "unknown",
            "changed_files": [],
            "summary": "executor completed; report validation pending",
        }
    if executor_status == "failed":
        return {
            "status": "failed",
            "validation_status": "failed",
            "changed_files": [],
            "summary": str(status_payload.get("message") or "executor failed"),
        }
    if executor_status == "orphaned":
        return {
            "status": "blocked",
            "validation_status": "blocked",
            "changed_files": [],
            "summary": str(status_payload.get("message") or "executor run orphaned"),
        }
    return {
        "status": "unknown",
        "validation_status": "unknown",
        "changed_files": [],
        "summary": f"executor_run_status={executor_status}",
    }


def _report_summary(worktree_path: str, claim: dict[str, Any], *, fallback_head: str) -> dict[str, Any]:
    report_id = str(claim.get("report_id") or "")
    if not report_id:
        return {"available": False}
    report_result = ExecutorRunReportStore(worktree_path).get_report(
        report_id=report_id,
        latest=False,
        include_markdown=False,
    )
    if not report_result.get("ok"):
        return {"available": False, "error_code": report_result.get("error_code")}
    report = report_result.get("report") if isinstance(report_result.get("report"), dict) else {}
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    changed_files = _string_list(report.get("changed_files")) or _string_list(summary.get("changed_files"))
    validation_status = str(summary.get("validation_status_summary") or "unknown").lower()
    return {
        "available": True,
        "report_id": report_id,
        "report_status": str(report.get("status") or "").lower(),
        "validation_status_summary": validation_status,
        "head": str(report.get("commit_head_after") or fallback_head),
        "changed_files": changed_files,
        "validation_inconsistent": bool(summary.get("validation_inconsistent") is True),
        "validation_failed_command_count": int(summary.get("validation_failed_command_count") or 0),
    }


def _map_report_summary(report: dict[str, Any]) -> dict[str, Any]:
    report_status = str(report.get("report_status") or "")
    validation_summary = str(report.get("validation_status_summary") or "unknown")
    validation_status = "passed" if validation_summary == "passed" else "failed" if validation_summary in {"failed", "inconsistent"} else "unknown"
    status = "succeeded" if report_status == "completed" else "failed" if report_status == "failed" else "unknown"
    changed_files = _string_list(report.get("changed_files"))
    return {
        "status": status,
        "validation_status": validation_status,
        "head": str(report.get("head") or ""),
        "changed_files": changed_files,
        "summary": (
            f"report_status={report_status or 'unknown'}; "
            f"validation={validation_summary}; changed_files={len(changed_files)}"
        ),
    }


def _executor_result_for_group_status(shard: dict[str, Any]) -> dict[str, Any]:
    return {
        "task_id": str(shard.get("task_id") or ""),
        "status": str(shard.get("status") or "unknown"),
        "validation_status": str(shard.get("validation_status") or "unknown"),
        "head": str(shard.get("head") or shard.get("current_head") or ""),
        "changed_files": _string_list(shard.get("changed_files")),
        "summary": str(shard.get("summary") or "")[:500],
    }


def _packet_blockers(run_preview: dict[str, Any], shard_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    run_blockers = run_preview.get("blocking_reasons")
    if isinstance(run_blockers, list):
        blockers.extend(item for item in run_blockers if isinstance(item, dict))
    for shard in shard_results:
        if str(shard.get("status") or "") in {"failed", "blocked", "unknown"}:
            blockers.append(
                {
                    "code": "PARALLEL_EXECUTOR_RESULT_NOT_READY",
                    "task_id": shard.get("task_id"),
                    "status": shard.get("status"),
                    "summary": shard.get("summary"),
                }
            )
    return blockers


def _result_stage_validation_blockers(validation: dict[str, Any]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for item in validation.get("blocking_reasons", []):
        if not isinstance(item, dict):
            continue
        if str(item.get("code") or "") == "WORKTREE_NOT_CLEAN" and _status_lines_are_result_metadata(item.get("status_short")):
            continue
        blockers.append(item)
    return blockers


def _status_lines_are_result_metadata(value: Any) -> bool:
    if not isinstance(value, list) or not value:
        return False
    for line in value:
        path = _status_line_path(str(line))
        if not any(path == prefix.rstrip("/") or path.startswith(prefix) for prefix in RESULT_METADATA_DIR_PREFIXES):
            return False
    return True


def _status_line_path(line: str) -> str:
    text = str(line or "").strip()
    path = text[3:].strip() if len(text) > 3 else text
    if " -> " in path:
        path = path.split(" -> ")[-1].strip()
    return path


def _status_blockers(status_payload: dict[str, Any]) -> list[dict[str, Any]]:
    blockers = status_payload.get("blockers")
    if not isinstance(blockers, list):
        return []
    return [{"code": str(item)} for item in blockers[:20]]


def _status_counts(shards: list[dict[str, Any]]) -> dict[str, int]:
    counts = {key: 0 for key in ("planned", "running", "succeeded", "failed", "blocked", "unknown")}
    for shard in shards:
        status = str(shard.get("status") or "unknown")
        if status not in counts:
            status = "unknown"
        counts[status] += 1
    counts["total"] = len(shards)
    return counts


def _safe_next_actions(group_status: dict[str, Any], counts: dict[str, int], blockers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(group_status.get("merge_readiness"), dict) and group_status.get("merge_readiness", {}).get("ready") is True:
        return [
            {
                "tool": "get_stage_parallel_merge_preview",
                "arguments": {"executor_results": "<executor_results from this packet>"},
                "reason": "所有 shard succeeded 且 validation passed；下一步只读预览 merge。",
                "requires_confirmation": False,
            }
        ]
    if counts["running"] or counts["planned"]:
        return [
            {
                "tool": "get_stage_parallel_executor_results_packet",
                "arguments": {},
                "reason": "稍后重新读取 structured executor result metadata；不读 raw logs。",
                "requires_confirmation": False,
            }
        ]
    if blockers:
        return [
            {
                "tool": "inspect_executor_activity",
                "arguments": {},
                "reason": "读取 structured executor activity，定位失败或阻断 shard；不要读取 raw logs。",
                "requires_confirmation": False,
            }
        ]
    return []


def _authority_boundary() -> dict[str, bool]:
    return {
        "does_not_read_raw_logs": True,
        "does_not_start_executor": True,
        "does_not_create_executor_preview": True,
        "does_not_create_branch_or_worktree": True,
        "does_not_merge_parallel_results": True,
        "does_not_commit": True,
        "does_not_push": True,
        "does_not_replace_stable_service": True,
        "does_not_write_delivery_accepted": True,
        "does_not_create_review_decision": True,
        "does_not_emit_gate_event": True,
    }


def _summary_from_blockers(prefix: str, blockers: list[dict[str, Any]]) -> str:
    codes = [str(item.get("code") or "") for item in blockers if isinstance(item, dict)]
    return f"{prefix}: {', '.join(code for code in codes if code)[:400]}"


def _read_json(path: str) -> dict[str, Any] | None:
    try:
        if not os.path.isfile(path):
            return None
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item.strip()][:200]
