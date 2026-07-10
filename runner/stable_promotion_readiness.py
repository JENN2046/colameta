from __future__ import annotations

import os
import subprocess
from typing import Any, Callable

from runner.runtime_observability import get_runtime_version_status, git_checkout_metadata
from runner.stable_promotion_evidence import (
    build_candidate_artifact_manifest,
    count_promotion_relevant_porcelain_entries,
    get_stable_promotion_evidence_status,
)


DEFAULT_STABLE_RUNTIME_DIR = "/home/jenn/tools/colameta"
REQUIRED_VISIBLE_TOOLS = (
    "get_web_gpt_service_entrypoint",
    "get_commander_app_manifest",
    "render_commander_app",
    "get_agent_consumer_contract",
    "get_service_entry_profile",
    "get_stable_promotion_readiness",
    "manage_stable_promotion_evidence",
    "get_runtime_version_status",
    "list_registered_projects",
    "analyze_project_state",
    "run_mcp_workflow",
    "manage_validation_run",
    "manage_workflow_run",
)
REQUIRED_WORKFLOWS = ("thin_governed_loop_preview",)


def get_stable_promotion_readiness(
    project_root: str,
    *,
    visible_tool_names: list[str] | tuple[str, ...] | None = None,
    supported_workflows: list[str] | tuple[str, ...] | None = None,
    service_mode: bool = False,
    mcp_exposure_profile: str | None = None,
    runtime_status: dict[str, Any] | None = None,
    registered_projects: list[dict[str, Any]] | None = None,
    stable_runtime_dir: str | None = None,
    backup_dir: str | None = None,
    rollback_rehearsal_evidence: dict[str, Any] | None = None,
    rollback_rehearsal_builder: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return a read-only stable-promotion preflight card.

    The result is deliberately evidence-only. It never claims deployment
    authority, and it does not modify service lifecycle, Git, or runner state.
    """
    root = os.path.abspath(os.path.expanduser(project_root))
    runtime = runtime_status if isinstance(runtime_status, dict) else get_runtime_version_status(root)
    git_state = _git_repo_state(root)
    candidate_manifest = build_candidate_artifact_manifest(root, git_state.get("head"))
    promotion_evidence = get_stable_promotion_evidence_status(root, candidate_head=git_state.get("head"))
    stable_state = _stable_runtime_state(stable_runtime_dir or _default_stable_runtime_dir())
    tool_support = _tool_support(visible_tool_names or (), supported_workflows or ())
    registry_state = _registry_state(registered_projects)
    built_rehearsal_evidence = (
        rollback_rehearsal_evidence
        if isinstance(rollback_rehearsal_evidence, dict)
        else (rollback_rehearsal_builder or _build_rollback_rehearsal_evidence)(
            project_root=root,
            backup_dir=backup_dir or _default_backup_dir(),
            target_head=_clean_text(git_state.get("head")),
        )
    )
    rehearsal_evidence = (
        dict(built_rehearsal_evidence) if isinstance(built_rehearsal_evidence, dict) else {}
    )
    rehearsal_binding = _rollback_rehearsal_binding(
        rehearsal_evidence,
        candidate_head=_clean_text(git_state.get("head")),
    )

    local_blockers: list[dict[str, str]] = []
    if not runtime.get("project_checkout_head"):
        local_blockers.append(_blocker("PROJECT_HEAD_UNKNOWN", "无法确认目标项目当前 Git HEAD。"))
    if runtime.get("reload_needed_for_verification") is not False:
        local_blockers.append(
            _blocker(
                "RUNTIME_RELOAD_NEEDED_FOR_VERIFICATION",
                "运行中服务无法证明已加载当前 checkout 代码；需要先重启或重新验证测试服务。",
            )
        )
    if git_state.get("worktree_clean") is not True:
        local_blockers.append(_blocker("WORKTREE_NOT_CLEAN", "目标项目 worktree 不是 clean，不能作为稳定晋升候选。"))
    missing_tools = tool_support["missing_visible_tools"]
    if missing_tools:
        local_blockers.append(
            _blocker("REQUIRED_MCP_TOOLS_MISSING", f"MCP 入口缺少生产级检查所需工具：{', '.join(missing_tools)}。")
        )
    missing_workflows = tool_support["missing_workflows"]
    if missing_workflows:
        local_blockers.append(
            _blocker("REQUIRED_WORKFLOWS_MISSING", f"MCP workflow 缺少：{', '.join(missing_workflows)}。")
        )

    warnings: list[dict[str, str]] = []
    if git_state.get("ahead_behind_available") is not True:
        warnings.append(_warning("ORIGIN_MAIN_COMPARISON_UNKNOWN", "无法确认本地与 origin/main 的 ahead/behind 状态。"))
    elif int(git_state.get("ahead") or 0) > 0:
        warnings.append(
            _warning(
                "LOCAL_COMMITS_NOT_PUSHED_TO_ORIGIN",
                "本地存在尚未 push 到 origin/main 的提交；可进入本地晋升审查，但不应宣称远端可追溯。",
            )
        )
    if stable_state.get("git_head_available") is not True:
        warnings.append(
            _warning(
                "STABLE_RUNTIME_GIT_PROVENANCE_UNKNOWN",
                "稳定运行目录不是可证明 Git HEAD 的 checkout；晋升前需要 artifact manifest 和 rollback receipt 补足来源证明。",
            )
        )
    if service_mode and registry_state["registered_project_count"] == 0:
        warnings.append(_warning("NO_REGISTERED_PROJECTS_VISIBLE", "服务模式下当前未看到已登记项目。"))

    external_required: list[dict[str, str]] = []
    if promotion_evidence.get("status") != "verified_current":
        external_required.append(
            _blocker("PROMOTION_ARTIFACT_MANIFEST_NOT_PERSISTED", "需要持久化并验证精确候选 HEAD 的 artifact manifest。"),
        )
    if rehearsal_binding.get("status") != "verified_current":
        external_required.append(
            _blocker("ROLLBACK_REHEARSAL_NOT_PROVEN", "需要为精确候选 HEAD 完成只读 rollback/rehearsal 证明。")
        )
    external_required.append(
        _blocker("COMMANDER_STABLE_REPLACEMENT_AUTHORIZATION_ABSENT", "替换稳定服务必须由 Commander 给出精确、当前有效授权。")
    )
    stable_promotion_review_candidate = not local_blockers
    worktree_isolation = _worktree_isolation(git_state, candidate_manifest)

    if stable_promotion_review_candidate:
        readiness_status = "stable_promotion_review_candidate"
        one_line = "本地服务候选可进入稳定晋升审查；正式替换仍需完成 external_required_before_stable_replacement。"
    else:
        readiness_status = "not_ready_for_stable_promotion_review"
        one_line = "当前服务候选还不能进入稳定晋升审查；先清掉 local_blockers。"

    return {
        "ok": True,
        "source": "stable_promotion_readiness",
        "scope": "mcp:read",
        "read_only": True,
        "side_effects": False,
        "readiness_status": readiness_status,
        "one_line": one_line,
        "stable_promotion_review_candidate": stable_promotion_review_candidate,
        "stable_production_ready": False,
        "stable_production_ready_reason": "deployment_authority_and_artifact_receipts_are_external_to_this_read_only_tool",
        "service": {
            "service_mode": bool(service_mode),
            "mcp_exposure_profile": mcp_exposure_profile,
        },
        "project": {
            "project_root": root,
            "head": runtime.get("project_checkout_head"),
            "branch": (runtime.get("project_checkout") or {}).get("branch"),
        },
        "runtime": {
            "loaded_source_root": (runtime.get("loaded_runtime") or {}).get("source_root"),
            "loaded_runtime_head": runtime.get("loaded_runtime_head"),
            "project_checkout_head": runtime.get("project_checkout_head"),
            "runtime_loaded_code_stale": runtime.get("runtime_loaded_code_stale"),
            "reload_needed_for_verification": runtime.get("reload_needed_for_verification"),
            "reload_awareness_reason": runtime.get("reload_awareness_reason"),
        },
        "git": git_state,
        "stable_runtime": stable_state,
        "candidate_artifact_manifest": candidate_manifest,
        "worktree_isolation": worktree_isolation,
        "promotion_artifact_evidence": promotion_evidence,
        "rollback_rehearsal_evidence": rehearsal_evidence,
        "rollback_rehearsal_binding": rehearsal_binding,
        "registry": registry_state,
        "tool_support": tool_support,
        "local_blockers": local_blockers,
        "warnings": warnings,
        "external_required_before_stable_replacement": external_required,
        "recommended_next_steps": _recommended_next_steps(
            stable_promotion_review_candidate,
            artifact_evidence_ready=promotion_evidence.get("status") == "verified_current",
            artifact_evidence_tool_visible=tool_support.get("stable_promotion_evidence_tool_visible") is True,
            rollback_rehearsal_ready=rehearsal_binding.get("status") == "verified_current",
            candidate_head=_clean_text(git_state.get("head")),
        ),
        "safety_boundary": {
            "does_not_authorize_stable_replacement": True,
            "does_not_authorize_service_restart": True,
            "does_not_authorize_push": True,
            "does_not_authorize_executor_run": True,
            "does_not_authorize_route_transition": True,
            "does_not_authorize_release_or_deploy": True,
            "does_not_create_review_decision": True,
            "does_not_emit_gate_event": True,
            "does_not_write_delivery_state": True,
            "worktree_changes_excluded_from_candidate_manifest": True,
        },
    }


def _git_repo_state(project_root: str) -> dict[str, Any]:
    metadata = git_checkout_metadata(project_root)
    status = _run_git(project_root, ["status", "--porcelain=v1", "-z", "--untracked-files=all"])
    dirty_entries = count_promotion_relevant_porcelain_entries(status.get("stdout_bytes", b"")) if status["ok"] else None
    origin_head = _run_git(project_root, ["rev-parse", "--verify", "origin/main"])
    ahead = behind = None
    ahead_behind_available = False
    if origin_head["ok"]:
        counts = _run_git(project_root, ["rev-list", "--left-right", "--count", "origin/main...HEAD"])
        if counts["ok"]:
            parts = str(counts.get("stdout") or "").strip().split()
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                behind = int(parts[0])
                ahead = int(parts[1])
                ahead_behind_available = True

    return {
        "head": metadata.get("head"),
        "branch": metadata.get("branch"),
        "git_dir_available": bool(metadata.get("git_dir_available")),
        "head_available": bool(metadata.get("head_available")),
        "head_source": metadata.get("head_source"),
        "worktree_clean": (dirty_entries == 0) if dirty_entries is not None else None,
        "dirty_entry_count": dirty_entries,
        "origin_main_head": _clean_text(origin_head.get("stdout")) if origin_head["ok"] else None,
        "origin_main_available": bool(origin_head["ok"]),
        "ahead_behind_available": ahead_behind_available,
        "ahead": ahead,
        "behind": behind,
        "read_only": True,
    }


def _stable_runtime_state(stable_runtime_dir: str) -> dict[str, Any]:
    root = os.path.abspath(os.path.expanduser(stable_runtime_dir))
    metadata = git_checkout_metadata(root)
    return {
        "stable_runtime_dir": root,
        "exists": os.path.isdir(root),
        "git_dir_available": bool(metadata.get("git_dir_available")),
        "git_head_available": bool(metadata.get("head_available")),
        "git_head": metadata.get("head"),
        "git_branch": metadata.get("branch"),
        "head_source": metadata.get("head_source"),
        "read_only": True,
    }


def _tool_support(
    visible_tool_names: list[str] | tuple[str, ...],
    supported_workflows: list[str] | tuple[str, ...],
) -> dict[str, Any]:
    visible = {item for item in visible_tool_names if isinstance(item, str)}
    workflows = {item for item in supported_workflows if isinstance(item, str)}
    missing_tools = [tool for tool in REQUIRED_VISIBLE_TOOLS if tool not in visible]
    missing_workflows = [workflow for workflow in REQUIRED_WORKFLOWS if workflow not in workflows]
    return {
        "required_visible_tools": list(REQUIRED_VISIBLE_TOOLS),
        "visible_tool_count": len(visible),
        "missing_visible_tools": missing_tools,
        "required_workflows": list(REQUIRED_WORKFLOWS),
        "missing_workflows": missing_workflows,
        "web_gpt_entrypoint_visible": "get_web_gpt_service_entrypoint" in visible,
        "agent_consumer_contract_visible": "get_agent_consumer_contract" in visible,
        "service_entry_profile_visible": "get_service_entry_profile" in visible,
        "stable_readiness_tool_visible": "get_stable_promotion_readiness" in visible,
        "stable_promotion_evidence_tool_visible": "manage_stable_promotion_evidence" in visible,
        "thin_governed_loop_preview_supported": "thin_governed_loop_preview" in workflows,
    }


def _registry_state(registered_projects: list[dict[str, Any]] | None) -> dict[str, Any]:
    projects = registered_projects if isinstance(registered_projects, list) else []
    managed_count = 0
    for project in projects:
        if isinstance(project, dict) and project.get("runner_managed") is True:
            managed_count += 1
    return {
        "registered_project_count": len(projects),
        "registered_managed_project_count": managed_count,
    }


def _default_stable_runtime_dir() -> str:
    env_value = os.environ.get("COLAMETA_STABLE_RUNTIME_DIR")
    if isinstance(env_value, str) and env_value.strip():
        return env_value.strip()
    return DEFAULT_STABLE_RUNTIME_DIR


def _default_backup_dir() -> str:
    from runner.production_ops import DEFAULT_BACKUP_DIR

    return DEFAULT_BACKUP_DIR


def _build_rollback_rehearsal_evidence(
    *,
    project_root: str,
    backup_dir: str,
    target_head: str | None,
) -> dict[str, Any]:
    from runner.production_ops import build_rollback_rehearsal_check

    return build_rollback_rehearsal_check(project_root, backup_dir, target_head)


def _recommended_next_steps(
    local_ready: bool,
    *,
    artifact_evidence_ready: bool,
    artifact_evidence_tool_visible: bool,
    rollback_rehearsal_ready: bool,
    candidate_head: str | None,
) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    if not artifact_evidence_ready and artifact_evidence_tool_visible:
        steps.append(
            {
                "step": "persist_artifact_manifest",
                "description": (
                    "先 preview，再持久化精确候选 HEAD 的 artifact manifest 与 sha256；"
                    "该证据只读 Git object database，不包含当前 worktree 改动。"
                ),
                "tool": "manage_stable_promotion_evidence",
                "arguments": {
                    "action": "preview",
                    **({"candidate_head": candidate_head} if candidate_head else {}),
                },
                "required_scope": "mcp:preview",
            }
        )
    if not local_ready:
        steps.extend(
            [
                {"step": "clear_local_blockers", "description": "清理 local_blockers；worktree 改动仍阻断正式晋升审查。"},
                {"step": "rerun_readiness", "description": "确认运行中服务加载的是当前 checkout 代码，且 worktree clean。"},
            ]
        )
        return steps
    if not rollback_rehearsal_ready:
        steps.append(
            {"step": "run_stable_promotion_rehearsal", "description": "在不替换稳定服务的前提下演练启动、健康检查与 rollback。"}
        )
    steps.append(
        {"step": "request_commander_authorization", "description": "拿到精确 hash-specific Commander 授权后，才可进入稳定服务替换。"}
    )
    return steps


def _rollback_rehearsal_binding(
    evidence: dict[str, Any],
    *,
    candidate_head: str | None,
) -> dict[str, Any]:
    target_head = _clean_text(evidence.get("target_head"))
    backup_file = _clean_text(evidence.get("backup_file"))
    backup_sha256 = _clean_text(evidence.get("backup_sha256"))
    backup_member_count = evidence.get("backup_member_count")
    evidence_reason_codes = {
        str(code) for code in evidence.get("reason_codes", []) if isinstance(code, str) and code
    }
    reason_codes: list[str] = []
    if evidence.get("status") != "ready":
        reason_codes.extend(evidence_reason_codes)
        if not reason_codes:
            reason_codes.append("ROLLBACK_REHEARSAL_EVIDENCE_NOT_READY")
    if evidence.get("evidence_source") != "local_read_only_status":
        reason_codes.append("ROLLBACK_REHEARSAL_SOURCE_INVALID")
    if "ROLLBACK_REHEARSAL_READY" not in evidence_reason_codes:
        reason_codes.append("ROLLBACK_REHEARSAL_READY_CODE_MISSING")
    if not candidate_head or target_head != candidate_head:
        reason_codes.append("ROLLBACK_REHEARSAL_TARGET_MISMATCH")
    if not backup_file:
        reason_codes.append("ROLLBACK_REHEARSAL_BACKUP_UNAVAILABLE")
    if not backup_sha256 or len(backup_sha256) != 64 or any(char not in "0123456789abcdef" for char in backup_sha256.lower()):
        reason_codes.append("ROLLBACK_REHEARSAL_BACKUP_SHA256_INVALID")
    if not isinstance(backup_member_count, int) or isinstance(backup_member_count, bool) or backup_member_count < 1:
        reason_codes.append("ROLLBACK_REHEARSAL_BACKUP_ARCHIVE_EMPTY")
    if evidence.get("rehearsal_executed_restore") is not False:
        reason_codes.append("ROLLBACK_REHEARSAL_RESTORE_BOUNDARY_INVALID")
    verified = not reason_codes
    return {
        "source": "stable_promotion_rollback_rehearsal_binding",
        "schema_version": "stable_promotion_rollback_rehearsal_binding.v1",
        "read_only": True,
        "side_effects": False,
        "status": "verified_current" if verified else "not_proven",
        "verified": verified,
        "candidate_head": candidate_head,
        "evidence_target_head": target_head,
        "backup_file": backup_file,
        "backup_sha256": backup_sha256,
        "backup_member_count": backup_member_count,
        "rehearsal_executed_restore": evidence.get("rehearsal_executed_restore"),
        "reason_codes": ["ROLLBACK_REHEARSAL_VERIFIED_CURRENT"] if verified else sorted(set(reason_codes)),
        "authority_boundary": {
            "does_not_execute_restore": True,
            "does_not_modify_stable_runtime": True,
            "does_not_authorize_stable_replacement": True,
        },
    }


def _worktree_isolation(git_state: dict[str, Any], candidate_manifest: dict[str, Any]) -> dict[str, Any]:
    clean_state = git_state.get("worktree_clean")
    status = (
        "clean"
        if clean_state is True
        else "changes_excluded_from_exact_commit_evidence"
        if clean_state is False
        else "worktree_state_unavailable_but_content_not_used"
    )
    return {
        "status": status,
        "worktree_clean": clean_state,
        "dirty_entry_count": git_state.get("dirty_entry_count"),
        "candidate_source": candidate_manifest.get("source_kind"),
        "worktree_content_used": candidate_manifest.get("worktree_content_used"),
        "worktree_changes_block_artifact_receipt": False,
        "worktree_changes_still_block_promotion_review": clean_state is not True,
    }


def _blocker(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def _warning(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def _run_git(project_root: str, args: list[str]) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            ["git", "-C", project_root, *args],
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": exc.__class__.__name__, "stdout": "", "stdout_bytes": b""}
    stdout_bytes = completed.stdout or b""
    return {
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "stdout": stdout_bytes.decode("utf-8", errors="replace"),
        "stdout_bytes": stdout_bytes,
    }


def _clean_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    return candidate or None
