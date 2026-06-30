from __future__ import annotations

import hashlib
import json
import os
import subprocess
from typing import Any

from runner.runtime_observability import get_runtime_version_status, git_checkout_metadata


DEFAULT_STABLE_RUNTIME_DIR = "/home/jenn/tools/colameta"
REQUIRED_VISIBLE_TOOLS = (
    "get_web_gpt_service_entrypoint",
    "get_stable_promotion_readiness",
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
) -> dict[str, Any]:
    """Return a read-only stable-promotion preflight card.

    The result is deliberately evidence-only. It never claims deployment
    authority, and it does not modify service lifecycle, Git, or runner state.
    """
    root = os.path.abspath(os.path.expanduser(project_root))
    runtime = runtime_status if isinstance(runtime_status, dict) else get_runtime_version_status(root)
    git_state = _git_repo_state(root)
    candidate_manifest = _candidate_artifact_manifest(root, git_state)
    stable_state = _stable_runtime_state(stable_runtime_dir or _default_stable_runtime_dir())
    tool_support = _tool_support(visible_tool_names or (), supported_workflows or ())
    registry_state = _registry_state(registered_projects)

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

    external_required = [
        _blocker("PROMOTION_ARTIFACT_MANIFEST_NOT_PERSISTED", "需要把候选 artifact manifest 摘要与 sha256 写入晋升材料。"),
        _blocker("ROLLBACK_REHEARSAL_NOT_PROVEN", "需要在不替换稳定服务的前提下完成 rollback/rehearsal 证明。"),
        _blocker("COMMANDER_STABLE_REPLACEMENT_AUTHORIZATION_ABSENT", "替换稳定服务必须由 Commander 给出精确、当前有效授权。"),
    ]
    stable_promotion_review_candidate = not local_blockers

    if stable_promotion_review_candidate:
        readiness_status = "stable_promotion_review_candidate"
        one_line = "本地服务候选可进入稳定晋升审查；正式替换仍被 artifact、rollback 和 Commander 授权阻断。"
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
        "registry": registry_state,
        "tool_support": tool_support,
        "local_blockers": local_blockers,
        "warnings": warnings,
        "external_required_before_stable_replacement": external_required,
        "recommended_next_steps": _recommended_next_steps(stable_promotion_review_candidate),
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
        },
    }


def _git_repo_state(project_root: str) -> dict[str, Any]:
    metadata = git_checkout_metadata(project_root)
    status = _run_git(project_root, ["status", "--porcelain=v1", "-z"])
    dirty_entries = _count_porcelain_z_entries(status.get("stdout_bytes", b"")) if status["ok"] else None
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


def _candidate_artifact_manifest(project_root: str, git_state: dict[str, Any]) -> dict[str, Any]:
    head = git_state.get("head")
    if not isinstance(head, str) or not head.strip():
        return {
            "available": False,
            "unavailable_reason": "project_head_unknown",
            "read_only": True,
        }

    listed = _run_git(project_root, ["ls-files", "-z"])
    if not listed["ok"]:
        return {
            "available": False,
            "unavailable_reason": "git_ls_files_failed",
            "read_only": True,
        }

    root = os.path.abspath(os.path.expanduser(project_root))
    entries: list[dict[str, Any]] = []
    total_size_bytes = 0
    for raw_path in _split_nul_paths(listed.get("stdout_bytes", b"")):
        relative_path = raw_path.decode("utf-8", errors="replace")
        if not relative_path:
            continue
        fingerprint = _fingerprint_tracked_path(root, relative_path)
        if not fingerprint.get("available"):
            return {
                "available": False,
                "unavailable_reason": str(fingerprint.get("unavailable_reason") or "tracked_file_fingerprint_failed"),
                "failed_path": relative_path,
                "read_only": True,
            }
        size_bytes = int(fingerprint.get("size_bytes") or 0)
        total_size_bytes += size_bytes
        entries.append(
            {
                "path": relative_path,
                "file_type": fingerprint.get("file_type"),
                "sha256": fingerprint.get("sha256"),
                "size_bytes": size_bytes,
            }
        )

    entries.sort(key=lambda item: str(item.get("path") or ""))
    payload = {
        "manifest_version": 1,
        "manifest_kind": "tracked_worktree_sha256_manifest",
        "project_head": head,
        "file_count": len(entries),
        "total_size_bytes": total_size_bytes,
        "files": entries,
    }
    manifest_json = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    manifest_sha256 = hashlib.sha256(manifest_json.encode("utf-8")).hexdigest()
    path_list_sha256 = hashlib.sha256(
        "\n".join(str(item.get("path") or "") for item in entries).encode("utf-8")
    ).hexdigest()

    return {
        "available": True,
        "manifest_version": 1,
        "manifest_kind": "tracked_worktree_sha256_manifest",
        "algorithm": "sha256",
        "project_head": head,
        "file_count": len(entries),
        "total_size_bytes": total_size_bytes,
        "manifest_sha256": manifest_sha256,
        "tracked_path_list_sha256": path_list_sha256,
        "file_entries_omitted_from_response": True,
        "included_paths_preview": [str(item.get("path") or "") for item in entries[:20]],
        "excluded_scope": "untracked_files_ignored_runtime_private_state_git_directory_virtualenv_build_artifacts",
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
        "stable_readiness_tool_visible": "get_stable_promotion_readiness" in visible,
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


def _recommended_next_steps(local_ready: bool) -> list[dict[str, str]]:
    if not local_ready:
        return [
            {"step": "clear_local_blockers", "description": "先修复 local_blockers，再重新调用本工具。"},
            {"step": "rerun_readiness", "description": "确认运行中服务加载的是当前 checkout 代码，且 worktree clean。"},
        ]
    return [
        {"step": "generate_artifact_manifest", "description": "为候选 HEAD 生成 artifact manifest 与 sha256。"},
        {"step": "run_stable_promotion_rehearsal", "description": "在不替换稳定服务的前提下演练启动、健康检查与 rollback。"},
        {"step": "request_commander_authorization", "description": "拿到精确 hash-specific Commander 授权后，才可进入稳定服务替换。"},
    ]


def _blocker(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def _warning(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def _count_porcelain_z_entries(raw: bytes) -> int:
    if not raw:
        return 0
    return len([part for part in raw.split(b"\0") if part])


def _split_nul_paths(raw: bytes) -> list[bytes]:
    if not raw:
        return []
    return [part for part in raw.split(b"\0") if part]


def _fingerprint_tracked_path(project_root: str, relative_path: str) -> dict[str, Any]:
    candidate = os.path.abspath(os.path.join(project_root, relative_path))
    try:
        common = os.path.commonpath([project_root, candidate])
    except ValueError:
        return {"available": False, "unavailable_reason": "path_outside_project_root"}
    if common != project_root:
        return {"available": False, "unavailable_reason": "path_outside_project_root"}
    try:
        if os.path.islink(candidate):
            data = os.readlink(candidate).encode("utf-8", errors="surrogateescape")
            return {
                "available": True,
                "file_type": "symlink",
                "sha256": hashlib.sha256(data).hexdigest(),
                "size_bytes": len(data),
            }
        digest = hashlib.sha256()
        size = 0
        with open(candidate, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                size += len(chunk)
                digest.update(chunk)
        return {
            "available": True,
            "file_type": "file",
            "sha256": digest.hexdigest(),
            "size_bytes": size,
        }
    except OSError as exc:
        return {"available": False, "unavailable_reason": exc.__class__.__name__}


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
