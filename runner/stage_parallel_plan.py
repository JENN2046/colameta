from __future__ import annotations

import os
import re
import hashlib
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


def build_stage_parallel_run_preview(
    *,
    project_root: str,
    project_name: str | None = None,
    stage_id: str | None = None,
    task_intents: list[dict[str, Any]] | None = None,
    max_parallel_tasks: int | None = None,
    provider: str | None = None,
    base_branch: str | None = None,
) -> dict[str, Any]:
    """Build a read-only run orchestration preview for parallel task shards.

    The returned packet describes the isolated worktrees, branches, and future
    executor preview requests that would be needed. It deliberately does not
    create those worktrees, create executor preview artifacts, or start runs.
    """
    plan = build_stage_parallel_plan_preview(
        project_root=project_root,
        project_name=project_name,
        stage_id=stage_id,
        task_intents=task_intents,
        max_parallel_tasks=max_parallel_tasks,
    )
    stage = _clean_text(stage_id) or str(plan.get("stage_id") or "stage_parallel_automation")
    executor_provider = _clean_provider(provider)
    base = _clean_branch(base_branch) or "main"
    shards = plan.get("task_shards") if isinstance(plan.get("task_shards"), list) else []
    group_id = _parallel_group_id(project_name=project_name, stage_id=stage, shards=shards)
    blocking_reasons = list(plan.get("blocking_reasons", [])) if isinstance(plan.get("blocking_reasons"), list) else []
    preview_ready = bool(shards) and not blocking_reasons
    run_shards = [
        _build_run_shard(
            shard=shard,
            project_root=project_root,
            project_name=project_name,
            stage_id=stage,
            group_id=group_id,
            provider=executor_provider,
            base_branch=base,
        )
        for shard in shards
        if isinstance(shard, dict)
    ]
    status = "preview_ready" if preview_ready else "blocked" if blocking_reasons else "empty"

    return {
        "ok": True,
        "source": "stage_parallel_run_preview",
        "scope": "mcp:read",
        "read_only": True,
        "side_effects": False,
        "status": status,
        "project_root": os.path.abspath(os.path.expanduser(project_root or "")),
        "project_name": project_name,
        "stage_id": stage,
        "parallel_group_id": group_id,
        "base_branch": base,
        "provider": executor_provider,
        "plan_preview": {
            "status": plan.get("status"),
            "risk_level": plan.get("risk_level"),
            "suggested_next_action": plan.get("suggested_next_action"),
            "planned_task_count": plan.get("parallelism", {}).get("planned_task_count")
            if isinstance(plan.get("parallelism"), dict)
            else None,
        },
        "parallelism": {
            "planned_task_count": len(run_shards),
            "max_concurrency": len(run_shards) if preview_ready else 0,
            "requires_isolated_worktrees": True,
            "requires_start_new_executor_sessions": True,
            "requires_merge_preview_before_main": True,
        },
        "run_shards": run_shards,
        "blocking_reasons": blocking_reasons,
        "risk_level": "blocked" if blocking_reasons else _run_preview_risk(plan, run_shards),
        "suggested_next_action": (
            "create_isolated_worktree_preview"
            if preview_ready
            else "refine_task_boundaries"
            if blocking_reasons
            else "keep_planning"
        ),
        "next_capability_steps": [
            "isolated_worktree_assignment_apply",
            "executor_preview_group_apply",
            "parallel_group_status",
            "stage_parallel_merge_preview",
            "stage_closeout_packet",
        ],
        "authority_boundary": {
            "does_not_authorize_executor_run": True,
            "does_not_create_executor_preview": True,
            "does_not_create_branch_or_worktree": True,
            "does_not_start_background_worker": True,
            "does_not_merge_parallel_results": True,
            "does_not_commit": True,
            "does_not_push": True,
            "does_not_replace_stable_service": True,
            "does_not_write_delivery_accepted": True,
            "does_not_create_review_decision": True,
            "does_not_emit_gate_event": True,
        },
        "safe_next_actions": _run_preview_safe_next_actions(preview_ready, blocking_reasons),
    }


def _build_run_shard(
    *,
    shard: dict[str, Any],
    project_root: str,
    project_name: str | None,
    stage_id: str,
    group_id: str,
    provider: str,
    base_branch: str,
) -> dict[str, Any]:
    task_id = _clean_text(shard.get("task_id")) or "parallel_task"
    branch_name = _parallel_branch_name(stage_id, task_id)
    worktree_path = os.path.join(
        os.path.abspath(os.path.expanduser(project_root or "")),
        ".colameta",
        "runtime",
        "parallel-worktrees",
        group_id,
        task_id,
    )
    return {
        "task_id": task_id,
        "title": _clean_text(shard.get("title")) or task_id,
        "allowed_files": _clean_string_list(shard.get("allowed_files")),
        "surfaces": _clean_surface_list(shard.get("surfaces")),
        "risk_level": _clean_risk_level(shard.get("risk_level")) or "low",
        "isolation": {
            "strategy": "git_worktree_required",
            "worktree_path": worktree_path,
            "base_branch": base_branch,
            "branch_name": branch_name,
            "created": False,
        },
        "executor_preview_request": {
            "status": "not_created",
            "tool": "manage_executor_workflow",
            "arguments": {
                "action": "run_once_preview",
                "project_name": project_name or "<registered project_name>",
                "provider": provider,
                "executor_session_mode": "start_new",
                "execution_mode": "run",
                "reason": f"{group_id}/{task_id}: {_clean_text(shard.get('title')) or task_id}",
            },
        },
        "merge_policy": {
            "merge_into_main_allowed": False,
            "requires_stage_parallel_merge_preview": True,
            "requires_validation_after_merge": True,
        },
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


def _parallel_group_id(*, project_name: str | None, stage_id: str, shards: list[Any]) -> str:
    task_ids = [
        str(item.get("task_id") or "")
        for item in shards
        if isinstance(item, dict) and item.get("task_id")
    ]
    raw = "|".join([project_name or "", stage_id, *task_ids])
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:10]
    return f"parallel_group_{_slugify(stage_id)}_{digest}"


def _parallel_branch_name(stage_id: str, task_id: str) -> str:
    return f"colameta/{_slugify(stage_id)}/{_slugify(task_id)}"


def _clean_provider(value: str | None) -> str:
    cleaned = _clean_text(value)
    if cleaned in {"codex", "opencode", "pi"}:
        return cleaned
    return "codex"


def _clean_branch(value: str | None) -> str | None:
    cleaned = _clean_text(value)
    if not cleaned:
        return None
    if re.fullmatch(r"[A-Za-z0-9._/-]{1,120}", cleaned):
        return cleaned
    return None


def _run_preview_risk(plan: dict[str, Any], run_shards: list[dict[str, Any]]) -> str:
    plan_risk = _clean_risk_level(plan.get("risk_level")) or "unknown"
    if plan_risk in {"high", "moderate"}:
        return plan_risk
    if len(run_shards) > 4:
        return "moderate"
    return "low" if run_shards else "none"


def _run_preview_safe_next_actions(
    preview_ready: bool,
    blocking_reasons: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if blocking_reasons:
        return [
            {
                "action_id": "refine_parallel_task_boundaries",
                "label": "Resolve overlap blockers before any parallel run preview can be applied.",
            }
        ]
    if preview_ready:
        return [
            {
                "action_id": "create_isolated_worktree_preview",
                "label": "Preview isolated worktree creation for each shard before executor previews are created.",
            }
        ]
    return [{"action_id": "keep_planning", "label": "Add task_intents before building a run preview."}]
