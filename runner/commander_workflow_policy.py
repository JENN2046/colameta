"""Deterministic journey and next-action policy for Commander responses.

This module classifies already-produced tool results.  It does not execute a
tool, grant authority, or alter a workflow result.
"""

from __future__ import annotations

import copy
import re
from typing import Any, Iterable

from runner.commander_contract import commander_public_error_code_for_result


COMMANDER_JOURNEY_STAGES = frozenset(
    {"connect", "observe", "plan", "execute", "review", "validate", "close", "recover"}
)

_TOOL_JOURNEY_STAGES = {
    "list_registered_projects": "connect",
    "get_apps_connector_smoke_packet": "connect",
    "render_commander_app": "connect",
    "analyze_project_state": "observe",
    "review_manifest": "review",
    "read_result_artifact": "review",
    "manage_validation_run": "validate",
    "manage_git": "close",
}
_WORKFLOW_JOURNEY_STAGES = {
    "project_status": "observe",
    "current_facts": "observe",
    "source_onboarding": "plan",
    "plan_update": "plan",
    "prompt_to_plan": "plan",
    "thin_governed_loop_preview": "plan",
    "project_delivery_preview": "close",
    "github_delivery": "close",
    "stage_7_9_preview": "plan",
    "auto_preview": "plan",
    "small_project_patch": "execute",
    "docs_update": "execute",
    "agent_dispatch": "execute",
    "operator_batch": "execute",
    "review_manifest": "review",
    "result_artifact": "review",
    "gate_review_request": "review",
    "git_commit": "close",
    "git_restore_file": "recover",
    "git_revert": "recover",
    "git_undo_version": "recover",
}
_RECOVERY_WORKFLOWS = frozenset({"git_restore_file", "git_revert", "git_undo_version"})
_COMPATIBILITY_ONLY_WORKFLOWS = frozenset({"auto_preview"})
_RECOVERY_GIT_ACTIONS = frozenset(
    {"restore_file_preview", "restore_file_apply", "revert_preview", "revert_apply"}
)
_PROJECT_SELECTION_PUBLIC_ERROR_CODES = frozenset(
    {"PROJECT_REQUIRED", "PROJECT_NOT_REGISTERED"}
)
_ACTION_CONTAINER_KEYS = frozenset(
    {
        "next_action",
        "next_actions",
        "recommended_next_action",
        "recommended_next_actions",
        "recommended_next_read",
        "recommended_next_reads",
        "copyable_apply_call",
        "copyable_tool_call",
        "recovery",
        "alternatives",
        "copy_paste_next_request",
    }
)
_RESOURCE_ARTIFACT_RE = re.compile(
    r"^colameta://result-artifact/(?P<artifact_id>[A-Za-z0-9_-]{16,128})"
    r"(?:/pages/(?P<page>[1-9][0-9]*))?$"
)
_RESOURCE_MANIFEST_RE = re.compile(
    r"^colameta://review-manifest/(?P<manifest_id>[A-Za-z0-9_-]{16,128})"
    r"(?:/subjects/(?P<subject>[1-9][0-9]*)"
    r"(?:/pages/(?P<page>[1-9][0-9]*))?)?$"
)


def _string(value: Any) -> str:
    return value.strip().lower() if isinstance(value, str) else ""


def _commander_tools() -> frozenset[str]:
    # Keep the public inventory in one place.  The import is intentionally
    # lazy so mcp_commander_public can use this policy without a module cycle.
    from runner.mcp_commander_public import COMMANDER_EXPOSED_TOOLS

    return frozenset(COMMANDER_EXPOSED_TOOLS)


def _result_data(result: dict[str, Any]) -> dict[str, Any]:
    data = result.get("data")
    return data if isinstance(data, dict) else result


def _find_first_stage(value: Any) -> str | None:
    if isinstance(value, dict):
        for key in ("journey_stage", "current_stage", "stage"):
            candidate = _string(value.get(key))
            if candidate in COMMANDER_JOURNEY_STAGES:
                return candidate
        for nested in value.values():
            candidate = _find_first_stage(nested)
            if candidate is not None:
                return candidate
    elif isinstance(value, list):
        for nested in value:
            candidate = _find_first_stage(nested)
            if candidate is not None:
                return candidate
    return None


def journey_stage_for(
    tool_name: str,
    params: dict[str, Any] | None,
    result: dict[str, Any],
) -> str:
    """Return the public journey position without granting workflow authority."""

    safe_params = params if isinstance(params, dict) else {}
    if tool_name == "manage_git":
        action = _string(safe_params.get("action"))
        return "recover" if action in _RECOVERY_GIT_ACTIONS else "close"
    if tool_name == "run_mcp_workflow":
        workflow = _string(safe_params.get("workflow"))
        if workflow == "thin_governed_loop_preview":
            observed = _find_first_stage(_result_data(result))
            if observed is not None:
                return observed
        return _WORKFLOW_JOURNEY_STAGES.get(workflow, "execute")
    return _TOOL_JOURNEY_STAGES.get(tool_name, "recover")


def _walk_action_candidates(value: Any, *, selected: bool = False) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        if selected and isinstance(value.get("tool"), str):
            yield value
        for key, nested in value.items():
            if key in _ACTION_CONTAINER_KEYS:
                yield from _walk_action_candidates(nested, selected=True)
            elif isinstance(nested, (dict, list)):
                yield from _walk_action_candidates(nested, selected=False)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk_action_candidates(nested, selected=selected)


def _resource_candidate(candidate: dict[str, Any]) -> dict[str, Any] | None:
    if candidate.get("tool") != "resources/read":
        return None
    arguments = candidate.get("arguments")
    if not isinstance(arguments, dict):
        arguments = candidate.get("params")
    uri = arguments.get("uri") if isinstance(arguments, dict) else None
    if not isinstance(uri, str):
        return None
    artifact_match = _RESOURCE_ARTIFACT_RE.fullmatch(uri)
    if artifact_match:
        action_arguments: dict[str, Any] = {
            "artifact_id": artifact_match.group("artifact_id"),
        }
        page = artifact_match.group("page")
        if page is not None:
            action_arguments["artifact_page"] = int(page)
        return {
            "tool": "read_result_artifact",
            "arguments": action_arguments,
            "reason": candidate.get("reason") or "读取受控结果证据。",
        }
    manifest_match = _RESOURCE_MANIFEST_RE.fullmatch(uri)
    if manifest_match:
        action_arguments: dict[str, Any] = {
            "phase": "status",
            "review_manifest_id": manifest_match.group("manifest_id"),
        }
        subject = manifest_match.group("subject")
        page = manifest_match.group("page")
        if subject is not None:
            action_arguments["phase"] = "read"
            action_arguments["review_manifest_subject_index"] = int(subject)
        if page is not None:
            action_arguments["review_manifest_page"] = int(page)
        return {
            "tool": "review_manifest",
            "arguments": action_arguments,
            "reason": candidate.get("reason") or "读取受控审查证据。",
        }
    return None


def _normalized_candidate(candidate: dict[str, Any]) -> dict[str, Any] | None:
    tool = candidate.get("tool")
    if not isinstance(tool, str):
        return None
    if tool == "resources/read":
        return _resource_candidate(candidate)
    arguments = candidate.get("arguments")
    if not isinstance(arguments, dict):
        arguments = candidate.get("params")
    clean_arguments = copy.deepcopy(arguments) if isinstance(arguments, dict) else {}
    workflow = _string(clean_arguments.get("workflow"))
    if tool == "run_mcp_workflow" and workflow in _COMPATIBILITY_ONLY_WORKFLOWS:
        return None
    if tool == "run_mcp_workflow" and workflow == "git_commit":
        tool = "manage_git"
        phase = _string(clean_arguments.get("phase"))
        clean_arguments = {
            "action": "commit_apply" if phase in {"apply", "commit"} else "commit_preview",
            **{
                key: copy.deepcopy(clean_arguments[key])
                for key in ("preview_id", "message", "project_name", "context_binding")
                if key in clean_arguments
            },
        }
    elif tool == "manage_git_commit":
        tool = "manage_git"
        action = _string(clean_arguments.get("action"))
        action_map = {
            "status": "commit_readiness",
            "readiness": "commit_readiness",
            "suggest_commit_message": "commit_message",
            "commit_workflow_preview": "commit_preview",
            "preview": "commit_preview",
            "commit": "commit_apply",
        }
        mapped = action_map.get(action)
        if mapped is None:
            return None
        clean_arguments["action"] = mapped
    elif tool in {"get_git_status", "get_git_diff"}:
        legacy_tool = tool
        tool = "manage_git"
        clean_arguments = {
            "action": "status" if legacy_tool == "get_git_status" else "diff",
            **{
                key: copy.deepcopy(clean_arguments[key])
                for key in ("project_name",)
                if key in clean_arguments
            },
        }
    if tool not in _commander_tools():
        return None
    reason = candidate.get("reason")
    return {
        "tool": tool,
        "arguments": clean_arguments,
        "reason": reason.strip() if isinstance(reason, str) and reason.strip() else "继续当前受控流程。",
    }


def _action_kind(action: dict[str, Any]) -> str:
    tool = action["tool"]
    arguments = action.get("arguments")
    safe_arguments = arguments if isinstance(arguments, dict) else {}
    action_name = _string(safe_arguments.get("action"))
    phase = _string(safe_arguments.get("phase"))
    workflow = _string(safe_arguments.get("workflow"))
    if tool == "manage_git" and (
        action_name.endswith("_apply") or action_name in {"commit_apply", "push_apply", "pull_apply"}
    ):
        return "confirmation"
    if tool == "run_mcp_workflow" and phase in {
        "apply",
        "apply_all",
        "plan_apply",
        "run",
        "commit",
        "execute",
        "pr_apply",
    }:
        return "confirmation"
    if tool == "manage_validation_run" and action_name == "run":
        return "confirmation"
    if (
        workflow in _RECOVERY_WORKFLOWS
        or (tool == "manage_git" and action_name in _RECOVERY_GIT_ACTIONS)
    ):
        return "recovery"
    if tool in {"read_result_artifact", "review_manifest"}:
        return "evidence"
    if (
        action_name in {"status", "push_status", "pull_status"}
        or phase in {"status", "pr_status"}
        or tool == "analyze_project_state"
    ):
        return "poll"
    if tool == "manage_validation_run":
        return "validation"
    if tool == "manage_git":
        return "commit"
    if tool == "run_mcp_workflow":
        return "plan"
    return "plan"


def _candidate_priority(kind: str) -> int:
    return {
        "confirmation": 0,
        "recovery": 1,
        "poll": 2,
        "evidence": 3,
        "validation": 4,
        "commit": 5,
        "plan": 6,
    }.get(kind, 99)


def _allowed_kind_for_outcome(outcome: str, kind: str) -> bool:
    if outcome == "confirmation_required":
        return kind == "confirmation"
    if outcome == "blocked":
        return kind == "recovery" or kind == "poll"
    if outcome == "in_progress":
        return kind == "poll"
    if outcome == "failed":
        return kind in {"recovery", "poll", "evidence"}
    return kind not in {"confirmation", "recovery"}


def _first_string(value: Any, keys: tuple[str, ...]) -> str | None:
    if isinstance(value, dict):
        for key in keys:
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        for nested in value.values():
            candidate = _first_string(nested, keys)
            if candidate is not None:
                return candidate
    elif isinstance(value, list):
        for nested in value:
            candidate = _first_string(nested, keys)
            if candidate is not None:
                return candidate
    return None


def _synthetic_confirmation_action(
    tool_name: str,
    params: dict[str, Any],
    raw_result: dict[str, Any],
) -> dict[str, Any] | None:
    data = _result_data(raw_result)
    preview_id = _first_string(
        data,
        ("gate_preview_id", "batch_preview_id", "preview_id"),
    )
    if preview_id is None:
        return None
    project_name = params.get("project_name")
    context_binding = data.get("context_binding")
    if not isinstance(context_binding, dict):
        confirmation = data.get("confirmation")
        if isinstance(confirmation, dict):
            context_binding = confirmation.get("context_binding")
    continuation: dict[str, Any] = {"preview_id": preview_id}
    if isinstance(project_name, str) and project_name.strip():
        continuation["project_name"] = project_name.strip()
    if isinstance(context_binding, dict):
        continuation["context_binding"] = copy.deepcopy(context_binding)
    if tool_name == "manage_git":
        action = _string(params.get("action"))
        apply_action = {
            "commit_preview": "commit_apply",
            "push_preview": "push_apply",
            "pull_preview": "pull_apply",
            "restore_file_preview": "restore_file_apply",
            "revert_preview": "revert_apply",
        }.get(action)
        if apply_action is None:
            return None
        continuation["action"] = apply_action
        if apply_action == "commit_apply" and isinstance(params.get("message"), str):
            continuation["message"] = params["message"]
        return {
            "tool": "manage_git",
            "arguments": continuation,
            "reason": "确认后执行与当前预览精确绑定的 Git 操作。",
        }
    if tool_name == "manage_validation_run":
        continuation["action"] = "run"
        return {
            "tool": "manage_validation_run",
            "arguments": continuation,
            "reason": "确认后运行当前预览固定的验证命令。",
        }
    if tool_name == "run_mcp_workflow":
        workflow = _string(params.get("workflow"))
        phase = _string(params.get("phase"))
        if workflow == "git_commit":
            continuation["action"] = "commit_apply"
            return {
                "tool": "manage_git",
                "arguments": continuation,
                "reason": "确认后创建与当前预览绑定的本地提交。",
            }
        continuation["workflow"] = workflow
        continuation["phase"] = {
            "plan_preview": "plan_apply",
            "run_preview": "run",
            "preview": "apply",
        }.get(phase, "apply")
        return {
            "tool": "run_mcp_workflow",
            "arguments": continuation,
            "reason": "确认后继续当前受控工作流。",
        }
    return None


def _synthetic_poll_action(
    tool_name: str,
    params: dict[str, Any],
    raw_result: dict[str, Any],
) -> dict[str, Any] | None:
    data = _result_data(raw_result)
    project_name = params.get("project_name")
    if tool_name == "manage_validation_run":
        run_id = _first_string(data, ("run_id", "validation_run_id"))
        if run_id is not None:
            arguments: dict[str, Any] = {"action": "status", "run_id": run_id}
            if isinstance(project_name, str) and project_name.strip():
                arguments["project_name"] = project_name.strip()
            return {
                "tool": "manage_validation_run",
                "arguments": arguments,
                "reason": "查询当前验证运行状态。",
            }
    if tool_name == "run_mcp_workflow":
        workflow = _string(params.get("workflow"))
        if workflow:
            arguments = {"workflow": workflow, "phase": "status"}
            for key in ("batch_preview_id", "project_name"):
                value = data.get(key) if key != "project_name" else project_name
                if isinstance(value, str) and value.strip():
                    arguments[key] = value.strip()
            return {
                "tool": "run_mcp_workflow",
                "arguments": arguments,
                "reason": "查询当前工作流运行状态。",
            }
    return {
        "tool": "analyze_project_state",
        "arguments": (
            {"project_name": project_name.strip()}
            if isinstance(project_name, str) and project_name.strip()
            else {}
        ),
        "reason": "重新读取项目状态。",
    }


def _synthetic_recovery_action(
    params: dict[str, Any],
    raw_result: dict[str, Any],
) -> dict[str, Any]:
    if (
        commander_public_error_code_for_result(raw_result)
        in _PROJECT_SELECTION_PUBLIC_ERROR_CODES
    ):
        return {
            "tool": "list_registered_projects",
            "arguments": {},
            "reason": "列出可用项目后，使用有效 project_name 重试原调用。",
        }
    project_name = params.get("project_name")
    return {
        "tool": "analyze_project_state",
        "arguments": (
            {"project_name": project_name.strip()}
            if isinstance(project_name, str) and project_name.strip()
            else {}
        ),
        "reason": "重新读取项目事实后再决定如何解除阻断。",
    }


def select_commander_next_action(
    *,
    tool_name: str,
    params: dict[str, Any] | None,
    raw_result: dict[str, Any],
    outcome: str,
) -> dict[str, Any] | None:
    """Select at most one public action using the frozen priority order."""

    safe_params = params if isinstance(params, dict) else {}
    if (
        outcome == "blocked"
        and commander_public_error_code_for_result(raw_result)
        in _PROJECT_SELECTION_PUBLIC_ERROR_CODES
    ):
        return _synthetic_recovery_action(safe_params, raw_result)
    candidates: list[tuple[int, int, dict[str, Any]]] = []
    for index, candidate in enumerate(_walk_action_candidates(raw_result)):
        normalized = _normalized_candidate(candidate)
        if normalized is None:
            continue
        kind = _action_kind(normalized)
        if _allowed_kind_for_outcome(outcome, kind):
            candidates.append((_candidate_priority(kind), index, normalized))
    if candidates:
        candidates.sort(key=lambda item: (item[0], item[1]))
        return candidates[0][2]
    if outcome == "confirmation_required":
        return _synthetic_confirmation_action(tool_name, safe_params, raw_result)
    if outcome == "in_progress":
        return _synthetic_poll_action(tool_name, safe_params, raw_result)
    if outcome == "blocked":
        return _synthetic_recovery_action(safe_params, raw_result)
    return None
