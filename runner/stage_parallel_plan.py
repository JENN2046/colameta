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
            "stage_parallel_worktree_assignment_preview",
            "stage_parallel_executor_group_preview",
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
            "stage_parallel_worktree_assignment_preview",
            "stage_parallel_executor_group_preview",
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


def build_stage_parallel_worktree_assignment_preview(
    *,
    project_root: str,
    project_name: str | None = None,
    stage_id: str | None = None,
    task_intents: list[dict[str, Any]] | None = None,
    max_parallel_tasks: int | None = None,
    provider: str | None = None,
    base_branch: str | None = None,
) -> dict[str, Any]:
    """Preview deterministic isolated worktree assignments for a parallel group.

    This is still read-only. It checks whether the suggested paths and branch
    names are assignable, but does not create directories, branches, worktrees,
    executor previews, runs, commits, pushes, or stable replacements.
    """
    run_preview = build_stage_parallel_run_preview(
        project_root=project_root,
        project_name=project_name,
        stage_id=stage_id,
        task_intents=task_intents,
        max_parallel_tasks=max_parallel_tasks,
        provider=provider,
        base_branch=base_branch,
    )
    project_root_abs = os.path.abspath(os.path.expanduser(project_root or ""))
    runtime_root = os.path.join(project_root_abs, ".colameta", "runtime", "parallel-worktrees")
    run_shards = run_preview.get("run_shards") if isinstance(run_preview.get("run_shards"), list) else []
    assignments = [
        _build_worktree_assignment(
            run_shard=run_shard,
            project_root=project_root_abs,
            runtime_root=runtime_root,
        )
        for run_shard in run_shards
        if isinstance(run_shard, dict)
    ]
    blocking_reasons = _worktree_assignment_blockers(run_preview, assignments)
    assignable_count = sum(1 for item in assignments if item.get("assignment_status") == "assignable")
    status = (
        "preview_ready"
        if assignments and not blocking_reasons
        else "blocked"
        if blocking_reasons
        else "empty"
    )

    return {
        "ok": True,
        "source": "stage_parallel_worktree_assignment_preview",
        "scope": "mcp:read",
        "read_only": True,
        "side_effects": False,
        "status": status,
        "project_root": project_root_abs,
        "project_name": project_name,
        "stage_id": run_preview.get("stage_id"),
        "parallel_group_id": run_preview.get("parallel_group_id"),
        "base_branch": run_preview.get("base_branch"),
        "provider": run_preview.get("provider"),
        "worktree_root": runtime_root,
        "run_preview": {
            "status": run_preview.get("status"),
            "risk_level": run_preview.get("risk_level"),
            "suggested_next_action": run_preview.get("suggested_next_action"),
        },
        "assignment_summary": {
            "planned_assignment_count": len(assignments),
            "assignable_count": assignable_count,
            "blocked_count": max(0, len(assignments) - assignable_count),
            "creates_worktrees": False,
            "creates_branches": False,
        },
        "worktree_assignments": assignments,
        "blocking_reasons": blocking_reasons,
        "risk_level": "blocked" if blocking_reasons else _worktree_assignment_risk(assignments),
        "suggested_next_action": (
            "build_executor_preview_group"
            if status == "preview_ready"
            else "resolve_worktree_assignment_blockers"
            if status == "blocked"
            else "keep_planning"
        ),
        "next_capability_steps": [
            "executor_preview_group",
            "parallel_group_status",
            "stage_parallel_merge_preview",
            "stage_closeout_packet",
        ],
        "authority_boundary": _parallel_read_only_authority_boundary(),
        "safe_next_actions": _worktree_assignment_safe_next_actions(status),
    }


def build_stage_parallel_executor_group_preview(
    *,
    project_root: str,
    project_name: str | None = None,
    stage_id: str | None = None,
    task_intents: list[dict[str, Any]] | None = None,
    max_parallel_tasks: int | None = None,
    provider: str | None = None,
    base_branch: str | None = None,
) -> dict[str, Any]:
    """Preview the executor preview group that would follow worktree assignment."""
    assignment_preview = build_stage_parallel_worktree_assignment_preview(
        project_root=project_root,
        project_name=project_name,
        stage_id=stage_id,
        task_intents=task_intents,
        max_parallel_tasks=max_parallel_tasks,
        provider=provider,
        base_branch=base_branch,
    )
    run_preview = build_stage_parallel_run_preview(
        project_root=project_root,
        project_name=project_name,
        stage_id=stage_id,
        task_intents=task_intents,
        max_parallel_tasks=max_parallel_tasks,
        provider=provider,
        base_branch=base_branch,
    )
    run_by_task = _items_by_task_id(run_preview.get("run_shards"))
    executor_previews = []
    for assignment in assignment_preview.get("worktree_assignments", []):
        if not isinstance(assignment, dict):
            continue
        task_id = str(assignment.get("task_id") or "")
        run_shard = run_by_task.get(task_id, {})
        request = run_shard.get("executor_preview_request") if isinstance(run_shard, dict) else None
        executor_previews.append(
            {
                "task_id": task_id,
                "title": run_shard.get("title") if isinstance(run_shard, dict) else task_id,
                "preview_status": "not_created",
                "executor_provider": run_preview.get("provider"),
                "assigned_worktree_path": assignment.get("worktree_path"),
                "assigned_branch_name": assignment.get("branch_name"),
                "requires_assignment_status": "assignable",
                "assignment_status": assignment.get("assignment_status"),
                "future_preview_request": request if isinstance(request, dict) else {},
            }
        )
    assignment_status = str(assignment_preview.get("status") or "empty")
    status = "preview_ready" if assignment_status == "preview_ready" else assignment_status

    return {
        "ok": True,
        "source": "stage_parallel_executor_group_preview",
        "scope": "mcp:read",
        "read_only": True,
        "side_effects": False,
        "status": status,
        "project_root": assignment_preview.get("project_root"),
        "project_name": project_name,
        "stage_id": assignment_preview.get("stage_id"),
        "parallel_group_id": assignment_preview.get("parallel_group_id"),
        "assignment_preview": {
            "status": assignment_status,
            "risk_level": assignment_preview.get("risk_level"),
            "planned_assignment_count": assignment_preview.get("assignment_summary", {}).get("planned_assignment_count")
            if isinstance(assignment_preview.get("assignment_summary"), dict)
            else None,
        },
        "executor_preview_summary": {
            "planned_preview_count": len(executor_previews),
            "created_preview_count": 0,
            "starts_executor_runs": False,
            "requires_explicit_apply_before_creation": True,
        },
        "executor_previews": executor_previews,
        "blocking_reasons": list(assignment_preview.get("blocking_reasons", []))
        if isinstance(assignment_preview.get("blocking_reasons"), list)
        else [],
        "risk_level": assignment_preview.get("risk_level"),
        "suggested_next_action": (
            "preview_executor_run_group"
            if status == "preview_ready"
            else assignment_preview.get("suggested_next_action")
        ),
        "next_capability_steps": [
            "executor_run_group_preview",
            "parallel_group_status",
            "stage_parallel_merge_preview",
            "stage_closeout_packet",
        ],
        "authority_boundary": _parallel_read_only_authority_boundary(),
        "safe_next_actions": _executor_group_safe_next_actions(status),
    }


def build_stage_parallel_group_status(
    *,
    project_root: str,
    project_name: str | None = None,
    stage_id: str | None = None,
    task_intents: list[dict[str, Any]] | None = None,
    max_parallel_tasks: int | None = None,
    provider: str | None = None,
    base_branch: str | None = None,
    executor_results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Aggregate expected or caller-provided executor result summaries."""
    executor_group = build_stage_parallel_executor_group_preview(
        project_root=project_root,
        project_name=project_name,
        stage_id=stage_id,
        task_intents=task_intents,
        max_parallel_tasks=max_parallel_tasks,
        provider=provider,
        base_branch=base_branch,
    )
    result_by_task = _normalize_executor_results(executor_results)
    shard_statuses = []
    for preview in executor_group.get("executor_previews", []):
        if not isinstance(preview, dict):
            continue
        task_id = str(preview.get("task_id") or "")
        result = result_by_task.get(task_id)
        shard_statuses.append(_build_parallel_shard_status(preview, result))
    counts = _parallel_status_counts(shard_statuses)
    has_results = bool(result_by_task)
    all_succeeded = bool(shard_statuses) and all(item.get("status") == "succeeded" for item in shard_statuses)
    all_validated = bool(shard_statuses) and all(item.get("validation_status") == "passed" for item in shard_statuses)
    has_incomplete_results = any(item.get("status") in {"planned", "running"} for item in shard_statuses)
    raw_group_blockers = list(executor_group.get("blocking_reasons", [])) if isinstance(executor_group.get("blocking_reasons"), list) else []
    blockers = _parallel_group_blockers_for_results(raw_group_blockers, has_results=has_results)
    if has_results:
        blockers.extend(_parallel_result_blockers(shard_statuses))
    status = (
        "merge_ready"
        if has_results and all_succeeded and all_validated and not blockers
        else "waiting_for_executor_results"
        if (
            (has_results and has_incomplete_results and not blockers)
            or (executor_group.get("status") == "preview_ready" and not has_results)
        )
        else "blocked"
        if blockers
        else str(executor_group.get("status") or "empty")
    )

    return {
        "ok": True,
        "source": "stage_parallel_group_status",
        "scope": "mcp:read",
        "read_only": True,
        "side_effects": False,
        "status": status,
        "project_root": executor_group.get("project_root"),
        "project_name": project_name,
        "stage_id": executor_group.get("stage_id"),
        "parallel_group_id": executor_group.get("parallel_group_id"),
        "executor_group_preview": {
            "status": executor_group.get("status"),
            "planned_preview_count": executor_group.get("executor_preview_summary", {}).get("planned_preview_count")
            if isinstance(executor_group.get("executor_preview_summary"), dict)
            else None,
        },
        "result_source": "provided_executor_results" if has_results else "planned_no_executor_results",
        "status_counts": counts,
        "shard_statuses": shard_statuses,
        "merge_readiness": {
            "ready": status == "merge_ready",
            "all_shards_succeeded": all_succeeded,
            "all_validations_passed": all_validated,
            "requires_stage_parallel_merge_preview": True,
        },
        "blocking_reasons": blockers,
        "risk_level": _parallel_group_status_risk(status, blockers),
        "suggested_next_action": (
            "build_stage_parallel_merge_preview"
            if status == "merge_ready"
            else "wait_for_executor_results"
            if status == "waiting_for_executor_results"
            else "resolve_parallel_group_blockers"
            if status == "blocked"
            else "keep_planning"
        ),
        "next_capability_steps": [
            "stage_parallel_merge_preview",
            "stage_closeout_packet",
        ],
        "authority_boundary": _parallel_read_only_authority_boundary(),
        "safe_next_actions": _parallel_group_status_safe_next_actions(status),
    }


def build_stage_parallel_merge_preview(
    *,
    project_root: str,
    project_name: str | None = None,
    stage_id: str | None = None,
    task_intents: list[dict[str, Any]] | None = None,
    max_parallel_tasks: int | None = None,
    provider: str | None = None,
    base_branch: str | None = None,
    executor_results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Preview a safe merge plan for a completed parallel group."""
    group_status = build_stage_parallel_group_status(
        project_root=project_root,
        project_name=project_name,
        stage_id=stage_id,
        task_intents=task_intents,
        max_parallel_tasks=max_parallel_tasks,
        provider=provider,
        base_branch=base_branch,
        executor_results=executor_results,
    )
    merge_ready = group_status.get("status") == "merge_ready"
    merge_sequence = _build_merge_sequence(group_status.get("shard_statuses")) if merge_ready else []
    blockers = [] if merge_ready else _merge_preview_blockers(group_status)

    return {
        "ok": True,
        "source": "stage_parallel_merge_preview",
        "scope": "mcp:read",
        "read_only": True,
        "side_effects": False,
        "status": "preview_ready" if merge_ready else "blocked",
        "project_root": group_status.get("project_root"),
        "project_name": project_name,
        "stage_id": group_status.get("stage_id"),
        "parallel_group_id": group_status.get("parallel_group_id"),
        "group_status": {
            "status": group_status.get("status"),
            "result_source": group_status.get("result_source"),
            "merge_ready": group_status.get("merge_readiness", {}).get("ready")
            if isinstance(group_status.get("merge_readiness"), dict)
            else False,
        },
        "merge_plan": {
            "strategy": "sequential_worktree_merge_after_explicit_authorization",
            "target_branch": _clean_branch(base_branch) or "main",
            "merge_sequence": merge_sequence,
            "merge_allowed_now": False,
            "requires_clean_target_worktree": True,
            "requires_post_merge_validation": True,
            "validation_commands": _default_parallel_validation_commands(),
        },
        "blocking_reasons": blockers,
        "risk_level": "moderate" if merge_ready else "blocked",
        "suggested_next_action": (
            "prepare_stage_closeout_packet"
            if merge_ready
            else "complete_parallel_group_before_merge_preview"
        ),
        "next_capability_steps": ["stage_closeout_packet"],
        "authority_boundary": _parallel_read_only_authority_boundary(),
        "safe_next_actions": _merge_preview_safe_next_actions(merge_ready),
    }


def build_stage_parallel_closeout_packet(
    *,
    project_root: str,
    project_name: str | None = None,
    stage_id: str | None = None,
    task_intents: list[dict[str, Any]] | None = None,
    max_parallel_tasks: int | None = None,
    provider: str | None = None,
    base_branch: str | None = None,
    executor_results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the read-only closeout packet for a parallel stage."""
    merge_preview = build_stage_parallel_merge_preview(
        project_root=project_root,
        project_name=project_name,
        stage_id=stage_id,
        task_intents=task_intents,
        max_parallel_tasks=max_parallel_tasks,
        provider=provider,
        base_branch=base_branch,
        executor_results=executor_results,
    )
    ready_for_review = merge_preview.get("status") == "preview_ready"
    return {
        "ok": True,
        "source": "stage_parallel_closeout_packet",
        "scope": "mcp:read",
        "read_only": True,
        "side_effects": False,
        "status": "ready_for_human_review" if ready_for_review else "not_ready",
        "project_root": merge_preview.get("project_root"),
        "project_name": project_name,
        "stage_id": merge_preview.get("stage_id"),
        "parallel_group_id": merge_preview.get("parallel_group_id"),
        "closeout_summary": {
            "parallel_orchestration_packet_ready": True,
            "merge_preview_ready": ready_for_review,
            "requires_human_review_before_apply": True,
            "stable_replacement_in_scope": False,
        },
        "review_packet": {
            "worktree_assignment": "reviewed_by_stage_parallel_worktree_assignment_preview",
            "executor_group": "reviewed_by_stage_parallel_executor_group_preview",
            "group_status": merge_preview.get("group_status"),
            "merge_plan": merge_preview.get("merge_plan"),
            "required_validation": _default_parallel_validation_commands(),
        },
        "blocking_reasons": list(merge_preview.get("blocking_reasons", []))
        if isinstance(merge_preview.get("blocking_reasons"), list)
        else [],
        "risk_level": "moderate" if ready_for_review else "blocked",
        "suggested_next_action": (
            "human_review_parallel_closeout"
            if ready_for_review
            else "continue_parallel_group_execution_or_review_blockers"
        ),
        "authority_boundary": _parallel_read_only_authority_boundary(),
        "safe_next_actions": _closeout_safe_next_actions(ready_for_review),
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


def _build_worktree_assignment(
    *,
    run_shard: dict[str, Any],
    project_root: str,
    runtime_root: str,
) -> dict[str, Any]:
    task_id = _clean_text(run_shard.get("task_id")) or "parallel_task"
    isolation = run_shard.get("isolation") if isinstance(run_shard.get("isolation"), dict) else {}
    worktree_path = str(isolation.get("worktree_path") or "")
    branch_name = str(isolation.get("branch_name") or "")
    worktree_abs = os.path.abspath(os.path.expanduser(worktree_path))
    parent_path = os.path.dirname(worktree_abs)
    branch_name_valid = _clean_branch(branch_name) == branch_name
    path_within_runtime = _path_is_within(worktree_abs, runtime_root)
    path_exists = os.path.exists(worktree_abs)
    blockers = []
    if not path_within_runtime:
        blockers.append(
            {
                "code": "WORKTREE_PATH_OUTSIDE_PROJECT_RUNTIME",
                "message": "The suggested worktree path is outside the project runtime worktree root.",
            }
        )
    if path_exists:
        blockers.append(
            {
                "code": "WORKTREE_PATH_ALREADY_EXISTS",
                "message": "The suggested worktree path already exists and must be inspected before reuse.",
            }
        )
    if not branch_name_valid:
        blockers.append(
            {
                "code": "INVALID_PARALLEL_BRANCH_NAME",
                "message": "The suggested branch name is not a safe Git branch name.",
            }
        )
    return {
        "task_id": task_id,
        "title": _clean_text(run_shard.get("title")) or task_id,
        "worktree_path": worktree_abs,
        "worktree_parent_path": parent_path,
        "worktree_root": runtime_root,
        "branch_name": branch_name,
        "base_branch": isolation.get("base_branch"),
        "path_exists": path_exists,
        "parent_exists": os.path.isdir(parent_path),
        "path_within_project_runtime": path_within_runtime,
        "branch_name_valid": branch_name_valid,
        "assignment_status": "blocked" if blockers else "assignable",
        "blocking_reasons": blockers,
        "creates_worktree": False,
        "creates_branch": False,
    }


def _worktree_assignment_blockers(
    run_preview: dict[str, Any],
    assignments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    run_blockers = run_preview.get("blocking_reasons")
    if isinstance(run_blockers, list):
        blockers.extend(item for item in run_blockers if isinstance(item, dict))
    for assignment in assignments:
        for item in assignment.get("blocking_reasons", []):
            if isinstance(item, dict):
                blocker = dict(item)
                blocker["task_id"] = assignment.get("task_id")
                blockers.append(blocker)
    return blockers


def _worktree_assignment_risk(assignments: list[dict[str, Any]]) -> str:
    if not assignments:
        return "none"
    if len(assignments) > 4:
        return "moderate"
    return "low"


def _worktree_assignment_safe_next_actions(status: str) -> list[dict[str, Any]]:
    if status == "preview_ready":
        return [
            {
                "action_id": "build_executor_preview_group",
                "label": "Preview executor preview requests for each assignable worktree.",
            }
        ]
    if status == "blocked":
        return [
            {
                "action_id": "resolve_worktree_assignment_blockers",
                "label": "Inspect path or branch blockers before any worktree is created.",
            }
        ]
    return [{"action_id": "keep_planning", "label": "Add task_intents before assigning worktrees."}]


def _executor_group_safe_next_actions(status: str) -> list[dict[str, Any]]:
    if status == "preview_ready":
        return [
            {
                "action_id": "preview_executor_run_group",
                "label": "Preview the executor run group after run_once_preview artifacts exist.",
            }
        ]
    return _worktree_assignment_safe_next_actions(status)


def _parallel_group_status_safe_next_actions(status: str) -> list[dict[str, Any]]:
    if status == "merge_ready":
        return [
            {
                "action_id": "build_stage_parallel_merge_preview",
                "label": "Preview merge order and validation before applying parallel results.",
            }
        ]
    if status == "waiting_for_executor_results":
        return [
            {
                "action_id": "wait_for_executor_results",
                "label": "Collect executor result summaries before merge preview.",
            }
        ]
    if status == "blocked":
        return [
            {
                "action_id": "resolve_parallel_group_blockers",
                "label": "Fix failed, blocked, or unvalidated shard results before merge preview.",
            }
        ]
    return [{"action_id": "keep_planning", "label": "Add task_intents before tracking a parallel group."}]


def _merge_preview_safe_next_actions(merge_ready: bool) -> list[dict[str, Any]]:
    if merge_ready:
        return [
            {
                "action_id": "prepare_stage_closeout_packet",
                "label": "Prepare a closeout packet for human review before any merge apply.",
            }
        ]
    return [
        {
            "action_id": "complete_parallel_group_before_merge_preview",
            "label": "Provide succeeded and validated executor results before merge preview.",
        }
    ]


def _closeout_safe_next_actions(ready_for_review: bool) -> list[dict[str, Any]]:
    if ready_for_review:
        return [
            {
                "action_id": "human_review_parallel_closeout",
                "label": "Review the closeout packet; it still does not authorize merge, commit, push, or stable replacement.",
            }
        ]
    return [
        {
            "action_id": "continue_parallel_group_execution_or_review_blockers",
            "label": "Complete executor results and merge preview evidence before closeout review.",
        }
    ]


def _items_by_task_id(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for item in value:
        if not isinstance(item, dict):
            continue
        task_id = _clean_text(item.get("task_id"))
        if task_id:
            result[task_id] = item
    return result


def _normalize_executor_results(value: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for item in value:
        if not isinstance(item, dict):
            continue
        task_id = _clean_text(item.get("task_id"))
        if not task_id:
            continue
        result[task_id] = {
            "task_id": task_id,
            "status": _clean_executor_status(item.get("status")),
            "validation_status": _clean_validation_status(item.get("validation_status")),
            "head": _clean_text(item.get("head")),
            "changed_files": _clean_string_list(item.get("changed_files")),
            "summary": _clean_text(item.get("summary")) or "",
        }
    return result


def _build_parallel_shard_status(
    preview: dict[str, Any],
    result: dict[str, Any] | None,
) -> dict[str, Any]:
    task_id = str(preview.get("task_id") or "")
    if not result:
        return {
            "task_id": task_id,
            "title": preview.get("title") or task_id,
            "status": "planned",
            "validation_status": "not_run",
            "worktree_path": preview.get("assigned_worktree_path"),
            "branch_name": preview.get("assigned_branch_name"),
            "changed_files": [],
            "merge_candidate": False,
        }
    status = str(result.get("status") or "unknown")
    validation_status = str(result.get("validation_status") or "unknown")
    return {
        "task_id": task_id,
        "title": preview.get("title") or task_id,
        "status": status,
        "validation_status": validation_status,
        "worktree_path": preview.get("assigned_worktree_path"),
        "branch_name": preview.get("assigned_branch_name"),
        "head": result.get("head"),
        "changed_files": _clean_string_list(result.get("changed_files")),
        "summary": result.get("summary") or "",
        "merge_candidate": status == "succeeded" and validation_status == "passed",
    }


def _parallel_status_counts(shard_statuses: list[dict[str, Any]]) -> dict[str, int]:
    counts = {
        "planned": 0,
        "running": 0,
        "succeeded": 0,
        "failed": 0,
        "blocked": 0,
        "unknown": 0,
    }
    for item in shard_statuses:
        status = str(item.get("status") or "unknown")
        if status not in counts:
            status = "unknown"
        counts[status] += 1
    counts["total"] = len(shard_statuses)
    return counts


def _parallel_result_blockers(shard_statuses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for item in shard_statuses:
        task_id = item.get("task_id")
        status = item.get("status")
        validation_status = item.get("validation_status")
        if status in {"failed", "blocked"}:
            blockers.append(
                {
                    "code": "PARALLEL_SHARD_NOT_SUCCESSFUL",
                    "message": "A parallel shard did not finish successfully.",
                    "task_id": task_id,
                    "status": status,
                }
            )
        elif status == "succeeded" and validation_status != "passed":
            blockers.append(
                {
                    "code": "PARALLEL_SHARD_VALIDATION_NOT_PASSED",
                    "message": "A parallel shard succeeded without passed validation evidence.",
                    "task_id": task_id,
                    "validation_status": validation_status,
                }
            )
        elif status not in {"succeeded", "planned", "running"}:
            blockers.append(
                {
                    "code": "PARALLEL_SHARD_STATUS_UNKNOWN",
                    "message": "A parallel shard has an unknown status.",
                    "task_id": task_id,
                    "status": status,
                }
            )
    return blockers


def _parallel_group_blockers_for_results(blockers: list[dict[str, Any]], *, has_results: bool) -> list[dict[str, Any]]:
    if not has_results:
        return blockers
    pre_creation_only = {"WORKTREE_PATH_ALREADY_EXISTS"}
    return [
        item
        for item in blockers
        if str(item.get("code") or "") not in pre_creation_only
    ]


def _parallel_group_status_risk(status: str, blockers: list[dict[str, Any]]) -> str:
    if blockers or status == "blocked":
        return "blocked"
    if status in {"merge_ready", "waiting_for_executor_results"}:
        return "moderate"
    return "low" if status == "preview_ready" else "none"


def _build_merge_sequence(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    sequence = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            continue
        sequence.append(
            {
                "order": index,
                "task_id": item.get("task_id"),
                "source_branch": item.get("branch_name"),
                "source_worktree_path": item.get("worktree_path"),
                "head": item.get("head"),
                "changed_files": _clean_string_list(item.get("changed_files")),
                "merge_command_preview": "git merge --no-ff <source_branch>",
            }
        )
    return sequence


def _merge_preview_blockers(group_status: dict[str, Any]) -> list[dict[str, Any]]:
    blockers = group_status.get("blocking_reasons")
    if isinstance(blockers, list) and blockers:
        return [item for item in blockers if isinstance(item, dict)]
    return [
        {
            "code": "PARALLEL_GROUP_NOT_MERGE_READY",
            "message": "The parallel group is not merge-ready yet.",
            "group_status": group_status.get("status"),
        }
    ]


def _default_parallel_validation_commands() -> list[str]:
    return [
        "python3 -m py_compile runner/stage_parallel_plan.py runner/mcp_server.py runner/web_console.py",
        ".venv/bin/python -m pytest tests/test_stage_parallel_plan.py tests/test_mcp_runtime_observability.py tests/test_web_console_security.py -q",
        ".venv/bin/python -m pytest -q",
    ]


def _parallel_read_only_authority_boundary() -> dict[str, bool]:
    return {
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
    }


def _path_is_within(path: str, parent: str) -> bool:
    try:
        return os.path.commonpath([path, parent]) == os.path.abspath(parent)
    except ValueError:
        return False


def _clean_executor_status(value: Any) -> str:
    cleaned = _clean_text(value)
    if cleaned in {"planned", "running", "succeeded", "failed", "blocked"}:
        return cleaned
    return "unknown"


def _clean_validation_status(value: Any) -> str:
    cleaned = _clean_text(value)
    if cleaned in {"not_run", "running", "passed", "failed", "blocked"}:
        return cleaned
    return "unknown"


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
