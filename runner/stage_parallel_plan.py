from __future__ import annotations

import os
import re
from typing import Any


DEFAULT_MAX_PARALLEL_TASKS = 3
MAX_PARALLEL_TASKS_LIMIT = 8
_SAFE_ID_RE = re.compile(r"[^a-z0-9_]+")


def build_stage_parallel_plan_preview(
    *,
    project_root: str,
    project_name: str | None = None,
    stage_id: str | None = None,
    task_intents: list[dict[str, Any]] | None = None,
    max_parallel_tasks: int | None = None,
) -> dict[str, Any]:
    """Build a read-only preview for future stage-level parallel execution.

    This function only classifies candidate task shards and their overlap risk.
    It does not create executor previews, write runner state, create branches or
    worktrees, start executors, merge results, commit, push, or promote stable.
    """
    limit = _bounded_parallel_limit(max_parallel_tasks)
    tasks = _normalize_task_intents(task_intents)
    source = "provided_task_intents"
    if not tasks:
        tasks = _default_automation_task_intents()
        source = "default_automation_roadmap"

    shards = [_build_task_shard(task, index + 1) for index, task in enumerate(tasks[:limit])]
    skipped_count = max(0, len(tasks) - len(shards))
    file_overlaps = _file_overlaps(shards)
    surface_summary = _surface_summary(shards)
    plan_risk = _plan_risk(file_overlaps=file_overlaps, shards=shards, skipped_count=skipped_count)
    suggested_next_action = (
        "refine_task_boundaries"
        if file_overlaps
        else "ready_for_parallel_run_preview"
        if shards
        else "keep_planning"
    )

    return {
        "ok": True,
        "source": "stage_parallel_plan_preview",
        "scope": "mcp:read",
        "read_only": True,
        "side_effects": False,
        "status": "preview_ready" if shards else "empty",
        "project_root": os.path.abspath(os.path.expanduser(project_root or "")),
        "project_name": project_name,
        "stage_id": _clean_text(stage_id) or "stage_parallel_automation",
        "task_source": source,
        "parallelism": {
            "requested_max_parallel_tasks": max_parallel_tasks,
            "effective_max_parallel_tasks": limit,
            "candidate_task_count": len(tasks),
            "planned_task_count": len(shards),
            "skipped_task_count": skipped_count,
        },
        "task_shards": shards,
        "file_overlap_risks": file_overlaps,
        "surface_summary": surface_summary,
        "risk_level": plan_risk,
        "suggested_next_action": suggested_next_action,
        "blocking_reasons": _blocking_reasons(file_overlaps),
        "automation_stage": "parallel_plan_preview_only",
        "next_capability_steps": [
            "stage_parallel_run_preview",
            "isolated_worktree_assignment",
            "parallel_group_status",
            "stage_parallel_merge_preview",
            "stage_closeout_packet",
        ],
        "authority_boundary": {
            "does_not_authorize_executor_run": True,
            "does_not_create_executor_preview": True,
            "does_not_create_branch_or_worktree": True,
            "does_not_merge_parallel_results": True,
            "does_not_commit": True,
            "does_not_push": True,
            "does_not_replace_stable_service": True,
            "does_not_write_delivery_accepted": True,
            "does_not_create_review_decision": True,
            "does_not_emit_gate_event": True,
        },
        "safe_next_actions": _safe_next_actions(suggested_next_action),
    }


def _bounded_parallel_limit(value: int | None) -> int:
    try:
        candidate = int(value) if value is not None else DEFAULT_MAX_PARALLEL_TASKS
    except (TypeError, ValueError):
        candidate = DEFAULT_MAX_PARALLEL_TASKS
    return min(MAX_PARALLEL_TASKS_LIMIT, max(1, candidate))


def _normalize_task_intents(value: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    tasks: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        title = _clean_text(item.get("title")) or _clean_text(item.get("task_id"))
        if not title:
            continue
        tasks.append(
            {
                "task_id": _clean_text(item.get("task_id")),
                "title": title,
                "description": _clean_text(item.get("description")),
                "allowed_files": _clean_string_list(item.get("allowed_files")),
                "surfaces": _clean_surface_list(item.get("surfaces")),
                "risk_level": _clean_risk_level(item.get("risk_level")),
            }
        )
    return tasks


def _default_automation_task_intents() -> list[dict[str, Any]]:
    return [
        {
            "task_id": "parallel_plan_preview",
            "title": "Define stage parallel plan preview",
            "description": "Expose read-only task sharding, file-boundary, and risk evidence.",
            "allowed_files": ["runner/stage_parallel_plan.py", "runner/mcp_server.py", "tests/test_stage_parallel_plan.py"],
            "surfaces": ["MCP", "tests"],
            "risk_level": "low",
        },
        {
            "task_id": "parallel_status_packet",
            "title": "Design parallel group status packet",
            "description": "Prepare aggregation shape for future executor run groups.",
            "allowed_files": ["runner/stage_parallel_status.py", "tests/test_stage_parallel_status.py"],
            "surfaces": ["MCP", "tests"],
            "risk_level": "low",
        },
        {
            "task_id": "parallel_docs",
            "title": "Document stage parallel automation path",
            "description": "Clarify preview-first boundaries and stable replacement separation.",
            "allowed_files": ["docs/USAGE.md", "docs/USAGE.zh-CN.md"],
            "surfaces": ["docs"],
            "risk_level": "low",
        },
    ]


def _build_task_shard(task: dict[str, Any], index: int) -> dict[str, Any]:
    task_id = _clean_text(task.get("task_id")) or _slugify(_clean_text(task.get("title")) or f"task_{index}")
    allowed_files = _clean_string_list(task.get("allowed_files"))
    surfaces = _clean_surface_list(task.get("surfaces")) or _infer_surfaces_from_files(allowed_files)
    return {
        "task_id": task_id,
        "title": _clean_text(task.get("title")) or task_id,
        "description": _clean_text(task.get("description")) or "",
        "allowed_files": allowed_files,
        "surfaces": surfaces,
        "risk_level": _clean_risk_level(task.get("risk_level")) or _infer_task_risk(allowed_files, surfaces),
        "executor_assignment": {
            "strategy": "isolated_worktree_required",
            "provider_preference": "codex",
            "session_mode": "start_new",
        },
        "status": "candidate",
        "read_only": True,
    }


def _file_overlaps(shards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    owners: dict[str, list[str]] = {}
    for shard in shards:
        task_id = str(shard.get("task_id") or "")
        for path in _clean_string_list(shard.get("allowed_files")):
            owners.setdefault(path, []).append(task_id)
    overlaps = []
    for path, task_ids in sorted(owners.items()):
        unique_ids = list(dict.fromkeys(task_ids))
        if len(unique_ids) > 1:
            overlaps.append({"path": path, "task_ids": unique_ids, "risk": "write_conflict"})
    return overlaps


def _surface_summary(shards: list[dict[str, Any]]) -> dict[str, list[str]]:
    summary: dict[str, list[str]] = {}
    for shard in shards:
        task_id = str(shard.get("task_id") or "")
        for surface in _clean_surface_list(shard.get("surfaces")):
            summary.setdefault(surface, []).append(task_id)
    return {surface: task_ids for surface, task_ids in sorted(summary.items())}


def _plan_risk(*, file_overlaps: list[dict[str, Any]], shards: list[dict[str, Any]], skipped_count: int) -> str:
    if file_overlaps:
        return "blocked"
    if skipped_count > 0:
        return "moderate"
    if any(shard.get("risk_level") == "high" for shard in shards):
        return "high"
    if any(shard.get("risk_level") == "moderate" for shard in shards):
        return "moderate"
    return "low" if shards else "none"


def _blocking_reasons(file_overlaps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not file_overlaps:
        return []
    return [
        {
            "code": "PARALLEL_FILE_BOUNDARY_OVERLAP",
            "message": "One or more candidate tasks share writable file paths.",
            "overlap_count": len(file_overlaps),
        }
    ]


def _safe_next_actions(suggested_next_action: str) -> list[dict[str, Any]]:
    if suggested_next_action == "refine_task_boundaries":
        return [
            {
                "action_id": "refine_parallel_task_boundaries",
                "label": "Refine task allowed_files until overlap risks are empty.",
            }
        ]
    if suggested_next_action == "ready_for_parallel_run_preview":
        return [
            {
                "action_id": "build_stage_parallel_run_preview",
                "label": "Generate a future run preview with isolated worktree assignments before any executor starts.",
            }
        ]
    return [{"action_id": "keep_planning", "label": "Add task_intents before parallel execution planning."}]


def _infer_surfaces_from_files(paths: list[str]) -> list[str]:
    surfaces: list[str] = []
    for path in paths:
        lowered = path.lower().replace("\\", "/")
        if lowered.startswith("runner/mcp_") or lowered == "runner/mcp_server.py":
            _append_unique(surfaces, "MCP")
        if lowered.startswith("runner/web_") or lowered.startswith("runner/web_console"):
            _append_unique(surfaces, "Web")
        if lowered.startswith("scripts/") or lowered.startswith("bin/"):
            _append_unique(surfaces, "CLI")
        if lowered.startswith("docs/"):
            _append_unique(surfaces, "docs")
        if lowered.startswith("tests/"):
            _append_unique(surfaces, "tests")
    return surfaces


def _infer_task_risk(paths: list[str], surfaces: list[str]) -> str:
    if any(path.startswith(".github/") for path in paths):
        return "moderate"
    if len(surfaces) >= 4:
        return "moderate"
    return "low"


def _clean_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    return candidate or None


def _clean_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        cleaned = _clean_text(item)
        if cleaned and cleaned not in result:
            result.append(cleaned)
    return result


def _clean_surface_list(value: Any) -> list[str]:
    allowed = {"MCP", "Web", "CLI", "docs", "tests", "Git", "CI", "runtime"}
    result: list[str] = []
    for item in _clean_string_list(value):
        normalized = item if item in allowed else item.strip().lower()
        mapped = {
            "mcp": "MCP",
            "web": "Web",
            "cli": "CLI",
            "doc": "docs",
            "docs": "docs",
            "test": "tests",
            "tests": "tests",
            "git": "Git",
            "ci": "CI",
            "runtime": "runtime",
        }.get(normalized)
        if mapped:
            _append_unique(result, mapped)
    return result


def _clean_risk_level(value: Any) -> str | None:
    cleaned = _clean_text(value)
    if cleaned in {"none", "low", "moderate", "high", "blocked"}:
        return cleaned
    return None


def _slugify(value: str) -> str:
    lowered = value.strip().lower()
    slug = _SAFE_ID_RE.sub("_", lowered).strip("_")
    return slug or "parallel_task"


def _append_unique(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)
