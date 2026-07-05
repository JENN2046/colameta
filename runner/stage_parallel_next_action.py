from __future__ import annotations

import os
import subprocess
from typing import Any

from runner.stage_parallel_executor_results import build_stage_parallel_executor_results_packet
from runner.stage_parallel_plan import build_stage_parallel_run_preview
from runner.stage_parallel_shard_input_overlay import load_valid_overlay


def build_stage_parallel_next_action_packet(
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
    call_args = _call_args(
        project_name=project_name,
        stage_id=stage_id or str(run_preview.get("stage_id") or ""),
        task_intents=task_intents,
        max_parallel_tasks=max_parallel_tasks,
        provider=provider,
        base_branch=base_branch,
    )

    if run_preview.get("status") != "preview_ready":
        return _packet(
            project_root=project_root_abs,
            project_name=project_name,
            run_preview=run_preview,
            phase="plan_not_ready",
            status="blocked" if run_preview.get("status") == "blocked" else "empty",
            next_tool="get_stage_parallel_plan_preview",
            next_args=call_args,
            reason="阶段并行计划还未 ready；先读取 plan preview 并修正 task boundary。",
            blockers=_dict_list(run_preview.get("blocking_reasons")),
            evidence={"run_preview_status": run_preview.get("status")},
        )

    worktrees = _worktree_evidence(run_preview)
    missing_worktrees = [item for item in worktrees if item.get("state") == "missing"]
    blocked_worktrees = [item for item in worktrees if item.get("state") == "blocked"]
    if missing_worktrees:
        return _packet(
            project_root=project_root_abs,
            project_name=project_name,
            run_preview=run_preview,
            phase="worktrees_missing",
            status="needs_worktrees",
            next_tool="manage_stage_parallel_worktrees",
            next_args={**call_args, "action": "preview"},
            reason="至少一个 isolated worktree 还不存在；下一步预览 worktree 创建 gate。",
            blockers=[],
            evidence={"worktrees": worktrees},
            requires_confirmation=True,
        )
    if blocked_worktrees:
        return _packet(
            project_root=project_root_abs,
            project_name=project_name,
            run_preview=run_preview,
            phase="worktrees_blocked",
            status="blocked",
            next_tool="get_stage_parallel_worktree_assignment_preview",
            next_args=call_args,
            reason="isolated worktree 存在但状态不符合预期；先读取 assignment/worktree blocker。",
            blockers=[blocker for item in blocked_worktrees for blocker in _dict_list(item.get("blockers"))],
            evidence={"worktrees": worktrees},
        )

    overlays = _overlay_evidence(worktrees)
    missing_overlays = [item for item in overlays if item.get("state") != "ready"]
    if missing_overlays:
        return _packet(
            project_root=project_root_abs,
            project_name=project_name,
            run_preview=run_preview,
            phase="shard_inputs_missing",
            status="needs_shard_inputs",
            next_tool="manage_stage_parallel_shard_inputs",
            next_args={**call_args, "action": "preview"},
            reason="worktrees 已就绪，但至少一个 shard runner input overlay 缺失；下一步预览 shard input materialization。",
            blockers=[],
            evidence={"worktrees": worktrees, "shard_inputs": overlays},
            requires_confirmation=True,
        )

    results_packet = build_stage_parallel_executor_results_packet(
        project_root=project_root_abs,
        project_name=project_name,
        stage_id=stage_id,
        task_intents=task_intents,
        max_parallel_tasks=max_parallel_tasks,
        provider=provider,
        base_branch=base_branch,
    )
    shard_results = _dict_list(results_packet.get("shard_results"))
    planned_without_preview = [
        item
        for item in shard_results
        if item.get("status") == "planned" and not item.get("executor_preview_id")
    ]
    planned_with_preview = [
        item
        for item in shard_results
        if item.get("status") == "planned" and item.get("executor_preview_id")
    ]
    running = [item for item in shard_results if item.get("status") == "running"]
    failed_or_blocked = [
        item
        for item in shard_results
        if item.get("status") in {"failed", "blocked", "unknown"}
    ]

    if planned_without_preview:
        return _packet(
            project_root=project_root_abs,
            project_name=project_name,
            run_preview=run_preview,
            phase="executor_previews_missing",
            status="needs_executor_previews",
            next_tool="manage_stage_parallel_executor_group",
            next_args={**call_args, "action": "preview"},
            reason="shard inputs 已就绪，但 executor run_once_preview artifacts 尚未创建；下一步预览 executor group gate。",
            blockers=[],
            evidence=_results_evidence(results_packet, worktrees, overlays),
            requires_confirmation=True,
        )
    if planned_with_preview:
        return _packet(
            project_root=project_root_abs,
            project_name=project_name,
            run_preview=run_preview,
            phase="executor_runs_not_started",
            status="needs_executor_runs",
            next_tool="manage_stage_parallel_executor_runs",
            next_args={**call_args, "action": "preview"},
            reason="executor previews 已存在但 runs 尚未启动；下一步预览 executor run group gate。",
            blockers=[],
            evidence=_results_evidence(results_packet, worktrees, overlays),
            requires_confirmation=True,
        )
    if running:
        return _packet(
            project_root=project_root_abs,
            project_name=project_name,
            run_preview=run_preview,
            phase="executor_runs_running",
            status="waiting_for_executor_results",
            next_tool="get_stage_parallel_executor_results_packet",
            next_args=call_args,
            reason="至少一个 executor run 仍在运行；稍后读取 structured results packet。",
            blockers=[],
            evidence=_results_evidence(results_packet, worktrees, overlays),
        )
    if bool(results_packet.get("result_summary", {}).get("ready_for_merge_preview")):
        return _packet(
            project_root=project_root_abs,
            project_name=project_name,
            run_preview=run_preview,
            phase="merge_preview_ready",
            status="ready_for_merge_preview",
            next_tool="get_stage_parallel_merge_preview",
            next_args={**call_args, "executor_results": "<executor_results from this packet>"},
            reason="所有 shard succeeded 且 validation passed；下一步读取 merge preview。",
            blockers=[],
            evidence=_results_evidence(results_packet, worktrees, overlays),
        )
    if failed_or_blocked:
        return _packet(
            project_root=project_root_abs,
            project_name=project_name,
            run_preview=run_preview,
            phase="executor_results_blocked",
            status="blocked",
            next_tool="inspect_executor_activity",
            next_args={"project_name": project_name} if project_name else {},
            reason="至少一个 shard failed/blocked/unknown；下一步读取 structured executor activity，不读 raw logs。",
            blockers=_dict_list(results_packet.get("blocking_reasons")),
            evidence=_results_evidence(results_packet, worktrees, overlays),
        )

    return _packet(
        project_root=project_root_abs,
        project_name=project_name,
        run_preview=run_preview,
        phase="no_action",
        status="no_action",
        next_tool="get_stage_parallel_group_status",
        next_args=call_args,
        reason="没有可自动判定的下一步；读取 group status 复核。",
        blockers=[],
        evidence=_results_evidence(results_packet, worktrees, overlays),
    )


def _worktree_evidence(run_preview: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    base_branch = str(run_preview.get("base_branch") or "main")
    for shard in _dict_list(run_preview.get("run_shards")):
        isolation = shard.get("isolation") if isinstance(shard.get("isolation"), dict) else {}
        worktree_path = os.path.abspath(os.path.expanduser(str(isolation.get("worktree_path") or "")))
        expected_branch = str(isolation.get("branch_name") or "")
        expected_head = _git_stdout(["rev-parse", "--verify", base_branch], cwd=str(run_preview.get("project_root") or ""))
        state, blockers = _worktree_state(worktree_path, expected_branch=expected_branch, expected_head=expected_head)
        result.append(
            {
                "task_id": shard.get("task_id"),
                "worktree_path": worktree_path,
                "branch_name": expected_branch,
                "state": state,
                "head": _git_stdout(["rev-parse", "HEAD"], cwd=worktree_path) if state != "missing" else "",
                "blockers": blockers,
            }
        )
    return result


def _worktree_state(worktree_path: str, *, expected_branch: str, expected_head: str) -> tuple[str, list[dict[str, Any]]]:
    if not os.path.isdir(worktree_path):
        return "missing", [{"code": "WORKTREE_PATH_NOT_FOUND"}]
    inside = _git_stdout(["rev-parse", "--is-inside-work-tree"], cwd=worktree_path)
    if inside.lower() != "true":
        return "blocked", [{"code": "NOT_A_GIT_WORKTREE"}]
    branch = _git_stdout(["rev-parse", "--abbrev-ref", "HEAD"], cwd=worktree_path)
    head = _git_stdout(["rev-parse", "HEAD"], cwd=worktree_path)
    status_lines = [
        line
        for line in _git_stdout(["status", "--short", "--untracked-files=all"], cwd=worktree_path).splitlines()
        if line.strip()
    ]
    blocking_status = [line for line in status_lines if not _is_ignored_runtime_status(line)]
    blockers: list[dict[str, Any]] = []
    if expected_branch and branch != expected_branch:
        blockers.append({"code": "WORKTREE_BRANCH_MISMATCH", "expected": expected_branch, "actual": branch})
    if expected_head and head != expected_head:
        blockers.append({"code": "WORKTREE_HEAD_MISMATCH", "expected": expected_head, "actual": head})
    if blocking_status:
        blockers.append({"code": "WORKTREE_NOT_CLEAN", "status_short": blocking_status[:20]})
    return ("blocked", blockers) if blockers else ("ready", [])


def _overlay_evidence(worktrees: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for item in worktrees:
        overlay = load_valid_overlay(str(item.get("worktree_path") or ""))
        result.append(
            {
                "task_id": item.get("task_id"),
                "worktree_path": item.get("worktree_path"),
                "state": "ready" if overlay else "missing",
                "version": overlay.get("version") if isinstance(overlay, dict) else "",
                "manifest_file": overlay.get("manifest_file") if isinstance(overlay, dict) else "",
            }
        )
    return result


def _packet(
    *,
    project_root: str,
    project_name: str | None,
    run_preview: dict[str, Any],
    phase: str,
    status: str,
    next_tool: str,
    next_args: dict[str, Any],
    reason: str,
    blockers: list[dict[str, Any]],
    evidence: dict[str, Any],
    requires_confirmation: bool = False,
) -> dict[str, Any]:
    return {
        "ok": True,
        "source": "stage_parallel_next_action_packet",
        "scope": "mcp:read",
        "read_only": True,
        "side_effects": False,
        "status": status,
        "phase": phase,
        "project_root": project_root,
        "project_name": project_name,
        "stage_id": run_preview.get("stage_id"),
        "parallel_group_id": run_preview.get("parallel_group_id"),
        "next_action": {
            "tool": next_tool,
            "arguments": next_args,
            "reason": reason,
            "requires_confirmation": requires_confirmation,
        },
        "copyable_tool_call": {
            "tool": next_tool,
            "arguments": next_args,
        },
        "blocking_reasons": blockers,
        "evidence_summary": evidence,
        "authority_boundary": _authority_boundary(),
    }


def _results_evidence(
    results_packet: dict[str, Any],
    worktrees: list[dict[str, Any]],
    overlays: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "worktrees": worktrees,
        "shard_inputs": overlays,
        "result_summary": results_packet.get("result_summary"),
        "group_status_preview": results_packet.get("group_status_preview"),
        "executor_results": results_packet.get("executor_results"),
    }


def _call_args(
    *,
    project_name: str | None,
    stage_id: str,
    task_intents: list[dict[str, Any]] | None,
    max_parallel_tasks: int | None,
    provider: str | None,
    base_branch: str | None,
) -> dict[str, Any]:
    args: dict[str, Any] = {}
    if project_name:
        args["project_name"] = project_name
    if stage_id:
        args["stage_id"] = stage_id
    if task_intents is not None:
        args["task_intents"] = task_intents
    if isinstance(max_parallel_tasks, int):
        args["max_parallel_tasks"] = max_parallel_tasks
    if provider:
        args["provider"] = provider
    if base_branch:
        args["base_branch"] = base_branch
    return args


def _git_stdout(args: list[str], *, cwd: str) -> str:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if proc.returncode != 0:
            return ""
        return proc.stdout.strip()
    except Exception:
        return ""


def _is_ignored_runtime_status(line: str) -> bool:
    path = line[3:].strip() if len(line) > 3 else line.strip()
    paths = [part.strip() for part in path.split(" -> ")]
    return bool(paths) and all(
        item == ".colameta/runtime"
        or item.startswith(".colameta/runtime/")
        for item in paths
    )


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _authority_boundary() -> dict[str, bool]:
    return {
        "does_not_read_raw_logs": True,
        "does_not_create_preview_artifact": True,
        "does_not_create_branch_or_worktree": True,
        "does_not_write_shard_input": True,
        "does_not_authorize_executor_run": True,
        "does_not_start_executor": True,
        "does_not_merge_parallel_results": True,
        "does_not_commit": True,
        "does_not_push": True,
        "does_not_replace_stable_service": True,
        "does_not_write_delivery_accepted": True,
        "does_not_create_review_decision": True,
        "does_not_emit_gate_event": True,
    }
