import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any

from runner.workflow_records import WorkflowRecordStore


SENSITIVE_FIELD_KEYS = {
    "old_text", "new_text", "patch_text", "spec_json", "plan_json",
    "prompt", "first_version_prompt", "markdown", "content", "report",
    "new_content", "section_content",
}

SAFE_OUTPUT_FIELDS = {
    "ok", "action", "error_code", "mode", "status", "risk_level",
    "preview_id", "patch_id", "diff_hash", "can_commit", "can_apply",
    "recommended_next_action", "changed_files", "files_to_commit",
    "committed_files", "blockers", "warnings", "version",
    "workflow_action", "confidence", "assumptions",
    "manual_review_required", "can_preview", "plan_summary",
    "generated_spec_summary", "generated_version_spec_summary",
    "lint_summary", "repair_candidates",
    "workflow", "preview_ids", "next_actions", "requires_confirmation",
    "selected_workflow", "selection_reason", "stop_reason",
    "preflight_blocked", "blocks", "current_version", "current_version_index",
    "current_head", "current_branch", "runner_status", "git_status_short",
    "git_dirty", "git_head_before", "git_head_after", "git_status_after",
    "execution_branch_status", "execution_mode", "provider",
    "preflight_summary", "run_status", "scope_status", "audit_file",
    "log_path", "summary_path", "command_results", "failed_command_indexes",
    "executor_inventory", "report_summary",
    "latest_report_id", "classification", "diff_summary",
    "session_status", "run_summary", "gate_details",
    "execution_branch_required", "execution_branch_ready",
    "require_execution_branch",
    "max_iterations", "iterations_requested", "iterations_completed",
    "stopped", "stop_conditions_triggered", "iteration_results",
    "loop_summary", "total_changed_files", "total_diff_chars",
    "trusted_mode", "allow_fix", "allow_commit", "workflow_steps",
    "expires_at", "resolution", "next_action", "note",
    "resolution_options", "resolution_metadata",
    "synced_version_count", "state_file",
    "current_inventory_summary", "command_summary",
    "inventory_exists", "default_provider", "models_summary",
    "missing_providers", "providers_to_probe",
    "output_summary", "inventory_exists",
    "completion_evidence", "post_executor_patch_evidence",
    "manual_acceptance_evidence", "evidence_mismatch_warning",
    "scope", "target_files", "strategy", "command_count", "can_run",
    "validation_groups", "run_id", "run_file", "passed", "failed_command_index",
}


def _sha256_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _truncate(text: str, max_len: int = 300) -> str:
    if not text:
        return text
    return text[:max_len]


def _safe_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    return ""


def _safe_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value if isinstance(v, str)]
    return []


def summarize_inputs(tool_name: str, action: str, params: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "tool_name": tool_name,
        "action": action,
    }
    for key, val in params.items():
        if key in SENSITIVE_FIELD_KEYS:
            if isinstance(val, str) and val:
                summary[key] = {
                    "present": True,
                    "length": len(val),
                    "sha256": _sha256_of(val),
                    "kind": key,
                }
            else:
                summary[key] = {"present": False}
        elif key == "reason":
            summary[key] = _truncate(_safe_str(val), 300)
        elif key == "message":
            summary[key] = _truncate(_safe_str(val), 200)
        elif key == "preview_id":
            summary[key] = _safe_str(val)
        elif key == "version":
            summary[key] = _safe_str(val)
        elif isinstance(val, (str, int, float, bool)):
            summary[key] = val
        elif isinstance(val, list):
            summary[key] = [str(v) for v in val if isinstance(v, (str, int, float, bool))]
        elif val is None:
            summary[key] = None
    return summary


def _safe_assumptions(val: Any) -> list[str]:
    if not isinstance(val, list):
        return []
    result: list[str] = []
    for item in val[:10]:
        if isinstance(item, str):
            result.append(item[:300])
        elif isinstance(item, (int, float, bool)):
            result.append(str(item))
    return result


def _safe_generated_spec_summary(val: Any) -> dict[str, Any] | None:
    if not isinstance(val, dict):
        return None
    safe: dict[str, Any] = {}
    for key in val:
        if key in ("prompt", "first_version_prompt"):
            if isinstance(val[key], str):
                safe[key] = {"present": True, "length": len(val[key]), "sha256": _sha256_of(val[key]), "kind": key}
            else:
                safe[key] = {"present": False}
        elif key == "acceptance_commands" and isinstance(val[key], list):
            safe_cmds: list[dict[str, Any]] = []
            for cmd in val[key]:
                if isinstance(cmd, dict):
                    entry: dict[str, Any] = {}
                    if "command" in cmd and isinstance(cmd["command"], str):
                        entry["command"] = cmd["command"][:80]
                    if "timeout_seconds" in cmd:
                        entry["timeout_seconds"] = cmd["timeout_seconds"]
                    if "continue_on_failure" in cmd:
                        entry["continue_on_failure"] = cmd["continue_on_failure"]
                    safe_cmds.append(entry)
            safe[key] = safe_cmds
        elif key in ("allowed_files", "context_files", "manual_acceptance"):
            safe[key] = list(val[key]) if isinstance(val[key], list) else val[key]
        else:
            safe[key] = val[key]
    return safe


def summarize_outputs(tool_name: str, action: str, result: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {
        "ok": result.get("ok", False),
    }
    for key in SAFE_OUTPUT_FIELDS:
        if key in result:
            val = result[key]
            if key == "message":
                safe[key] = _truncate(_safe_str(val), 300)
            elif key in ("blockers", "warnings", "changed_files", "files_to_commit", "committed_files"):
                safe[key] = _safe_list(val)
            elif key == "assumptions":
                safe[key] = _safe_assumptions(val)
            elif key in ("generated_spec_summary", "generated_version_spec_summary"):
                safe_val = _safe_generated_spec_summary(val)
                if safe_val is not None:
                    safe[key] = safe_val
            elif key in ("plan_summary", "lint_summary", "repair_candidates", "confidence", "can_preview",
                         "manual_review_required", "workflow_action", "can_apply"):
                safe[key] = val
            else:
                safe[key] = val
    return safe


def infer_risk_level(tool_name: str, action: str) -> str:
    tool_action_map: dict[str, dict[str, str]] = {
        "analyze_project_state": {"analyze": "info"},
        "manage_plan_version": {
            "insert_preview": "preview",
            "update_preview": "preview",
            "repair_preview": "preview",
            "reload_plan": "commit",
            "continue_next_version": "commit",
        },
        "manage_project_patch": {
            "preview": "preview",
            "apply": "write",
        },
        "manage_git": {
            "status": "info",
            "diff": "info",
            "review_context": "info",
            "commit_readiness": "info",
            "commit_message": "info",
            "commit_preview": "preview",
            "commit_apply": "commit",
            "push_status": "info",
            "push_preview": "preview",
            "push_apply": "commit",
            "pull_status": "info",
            "pull_preview": "preview",
            "pull_apply": "commit",
            "history_log": "info",
            "history_show": "info",
            "diff_commits": "info",
            "restore_file_preview": "preview",
            "restore_file_apply": "write",
            "revert_preview": "preview",
            "revert_apply": "write",
        },
        "manage_git_history": {
            "restore_file_preview": "preview",
            "restore_file_apply": "write",
            "revert_preview": "preview",
            "revert_apply": "write",
        },
        "manage_git_commit": {
            "suggest_commit_message": "info",
            "preview": "preview",
            "commit_workflow_preview": "preview",
            "commit": "commit",
        },
        "manage_git_remote": {
            "push_status": "info",
            "push_preview": "preview",
            "push_apply": "commit",
            "fetch_preview": "preview",
            "fetch_apply": "commit",
            "pull_status": "info",
            "pull_preview": "preview",
            "pull_apply": "commit",
        },
        "manage_plan_workflow": {
            "source_onboarding_preview": "preview",
            "plan_repair_preview": "preview",
            "plan_extend_preview": "preview",
        },
        "manage_project_docs": {
            "update_section_preview": "preview",
            "append_section_preview": "preview",
            "sync_docs_preview": "preview",
            "apply": "write",
        },
        "manage_executor_config": {
            "inspect_inventory": "info",
            "probe_models_preview": "preview",
            "probe_models_apply": "commit",
        },
        "manage_executor_workflow": {
            "preflight": "info",
            "run_once_preview": "preview",
            "run_once": "commit",
            "run_bounded_preview": "preview",
            "run_bounded": "commit",
            "recheck_report_preview": "preview",
            "recheck_report_apply": "commit",
            "scope_mismatch_preview": "preview",
            "scope_mismatch_apply": "commit",
            "status": "info",
        },
        "manage_validation_run": {
            "inspect": "info",
            "preview": "preview",
            "run": "commit",
            "status": "info",
        },
        "run_mcp_workflow": {
            "auto_preview": "preview",
            "project_status": "info",
            "source_onboarding": "preview",
            "plan_update": "preview",
            "small_project_patch": "preview",
            "docs_update": "preview",
            "git_commit": "preview",
            "git_restore_file": "preview",
            "git_revert": "preview",
        },
        "manage_runner_record": {
            "read": "info",
            "add": "write",
            "update": "write",
            "delete": "write",
        },
        "manage_project_memory": {
            "read": "info",
            "add": "write",
            "update": "write",
            "delete": "write",
        },
        "inspect_executor_activity": {
            "run_status": "info",
            "latest_run_status": "info",
            "list_reports": "info",
            "get_report": "info",
            "get_audit_summary": "info",
        },
        "todo_read": {
            "todo_read": "info",
        },
        "todo_add": {
            "todo_add": "write",
        },
        "todo_update": {
            "update": "write",
        },
        "todo_delete": {
            "todo_delete": "write",
        },
    }
    action_map = tool_action_map.get(tool_name, {})
    return action_map.get(action, "info")


def infer_status(result: dict[str, Any]) -> str:
    if not isinstance(result, dict):
        return "failed"
    ok = result.get("ok", False)
    if not ok:
        error_code = result.get("error_code", "")
        if error_code == "NOT_SUPPORTED_IN_THIS_VERSION":
            return "unsupported"
        return "failed"
    return "succeeded"


def extract_preview_ids(result: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for key in ("preview_id", "patch_id"):
        val = result.get(key)
        if isinstance(val, str) and val.strip():
            if val.strip() not in ids:
                ids.append(val.strip())
    pids = result.get("preview_ids")
    if isinstance(pids, list):
        for pid in pids:
            if isinstance(pid, str) and pid.strip() and pid.strip() not in ids:
                ids.append(pid.strip())
    return ids


def extract_changed_files(result: dict[str, Any]) -> list[str]:
    files: list[str] = []
    for key in ("changed_files", "files_to_commit", "committed_files"):
        val = result.get(key)
        if isinstance(val, list):
            for f in val:
                if isinstance(f, str) and f.strip():
                    if f.strip() not in files:
                        files.append(f.strip())
    return files


def extract_diff_hash(result: dict[str, Any]) -> str | None:
    val = result.get("diff_hash")
    if isinstance(val, str) and val.strip():
        return val.strip()
    return None


def should_record_tool(tool_name: str, action: str) -> bool:
    record_actions: dict[str, set[str]] = {
        "analyze_project_state": {"analyze"},
        "manage_plan_version": {"insert_preview", "update_preview", "repair_preview", "reload_plan", "continue_next_version"},
        "manage_project_patch": {"preview", "apply"},
        "manage_git": {
            "status", "diff", "review_context",
            "commit_readiness", "commit_message", "commit_preview", "commit_apply",
            "push_status", "push_preview", "push_apply",
            "pull_status", "pull_preview", "pull_apply",
            "history_log", "history_show", "diff_commits",
            "restore_file_preview", "restore_file_apply",
            "revert_preview", "revert_apply",
        },
        "manage_git_history": {"restore_file_preview", "restore_file_apply", "revert_preview", "revert_apply"},
        "manage_git_commit": {"suggest_commit_message", "commit_workflow_preview", "preview", "commit"},
        "manage_git_remote": {
            "push_status",
            "push_preview",
            "push_apply",
            "fetch_preview",
            "fetch_apply",
            "pull_status",
            "pull_preview",
            "pull_apply",
        },
        "manage_plan_workflow": {
            "source_onboarding_preview", "plan_repair_preview", "plan_extend_preview",
        },
        "manage_project_docs": {
            "update_section_preview", "append_section_preview", "sync_docs_preview", "apply",
        },
        "manage_executor_config": {
            "inspect_inventory", "probe_models_preview", "probe_models_apply",
        },
        "manage_executor_workflow": {
            "preflight", "run_once_preview", "run_once", "run_bounded_preview", "run_bounded", "recheck_report_preview", "recheck_report_apply", "scope_mismatch_preview", "scope_mismatch_apply", "status",
        },
        "manage_validation_run": {"inspect", "preview", "run", "status"},
        "run_mcp_workflow": {
            "auto_preview", "project_status", "source_onboarding", "plan_update",
            "small_project_patch", "docs_update", "git_commit",
            "git_restore_file", "git_revert",
            "prompt_to_plan",
        },
        "manage_runner_record": {"read", "add", "update", "delete"},
        "manage_project_memory": {"read", "add", "update", "delete"},
        "init_submission_evidence": {"apply"},
        "fill_submission_evidence_files": {"apply"},
        "todo_read": {"todo_read"},
        "todo_add": {"todo_add"},
        "todo_update": {"update"},
        "todo_delete": {"todo_delete"},
    }
    actions = record_actions.get(tool_name, set())
    return action in actions


def record_tool_call(
    project_root: str,
    tool_name: str,
    action: str,
    params: dict[str, Any],
    result: dict[str, Any],
    error: str | None = None,
) -> dict[str, Any]:
    store = WorkflowRecordStore(project_root)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    step_id = uuid.uuid4().hex[:12]

    inputs_summary = summarize_inputs(tool_name, action, params)
    outputs_summary = summarize_outputs(tool_name, action, result)
    risk_level = infer_risk_level(tool_name, action)
    status = infer_status(result)
    preview_ids = extract_preview_ids(result)
    preview_id_from_params = params.get("preview_id", params.get("patch_id"))
    if isinstance(preview_id_from_params, str) and preview_id_from_params.strip():
        pid = preview_id_from_params.strip()
        if pid not in preview_ids:
            preview_ids.append(pid)

    extract_result = {
        "changed_files": extract_changed_files(result),
        "diff_hash": extract_diff_hash(result),
        "preview_ids": preview_ids,
    }

    step: dict[str, Any] = {
        "step_id": step_id,
        "started_at": now,
        "finished_at": now,
        "tool_name": tool_name,
        "action": action,
        "status": status,
        "risk_level": risk_level,
        "inputs_summary": inputs_summary,
        "outputs_summary": outputs_summary,
        "changed_files": extract_result["changed_files"],
        "diff_hash": extract_result["diff_hash"],
        "preview_ids": preview_ids,
        "warnings": _safe_list(result.get("warnings")),
        "blockers": _safe_list(result.get("blockers")),
        "error_code": result.get("error_code") if not result.get("ok") else None,
        "stop_reason": None,
        "message_error": error,
    }
    raw_sub_steps = result.get("workflow_steps")
    appended_sub_steps = _sanitize_workflow_sub_steps(raw_sub_steps)

    preview_id = preview_ids[0] if preview_ids else None
    if preview_id:
        existing = store.find_run_by_preview_id(preview_id)
        if existing is not None:
            wf_id = existing.get("workflow_id", "")
            for sub_step in appended_sub_steps:
                append_sub_ret = store.append_step(wf_id, sub_step)
                if not append_sub_ret.get("ok"):
                    return {"workflow_id": wf_id, "warning": f"failed to append workflow sub-step: {append_sub_ret.get('error')}"}
            append_ret = store.append_step(wf_id, step)
            if not append_ret.get("ok"):
                return {"workflow_id": None, "warning": f"failed to append step: {append_ret.get('error')}"}
            stop_reason = _infer_stop_reason(tool_name, action, result, is_append=True)
            finish_ret = store.finish_run(
                wf_id,
                status=status,
                outputs_summary=outputs_summary,
                stop_reason=stop_reason,
                warnings=_safe_list(result.get("warnings")),
                blockers=_safe_list(result.get("blockers")),
                step_outputs_summary=outputs_summary,
                step_changed_files=extract_result["changed_files"],
                step_diff_hash=extract_result["diff_hash"],
                step_preview_ids=preview_ids,
            )
            if not finish_ret.get("ok"):
                return {"workflow_id": wf_id, "warning": f"failed to finish run: {finish_ret.get('error')}"}
            return {"workflow_id": wf_id}

    workflow_name = tool_name
    create_ret = store.create_run(
        workflow_name=workflow_name,
        tool_name=tool_name,
        action=action,
        inputs_summary=inputs_summary,
        risk_level=risk_level,
    )
    if not create_ret.get("ok"):
        return {"workflow_id": None, "warning": f"failed to create workflow: {create_ret.get('error')}"}

    wf_id = create_ret["workflow_id"]
    for sub_step in appended_sub_steps:
        append_sub_ret = store.append_step(wf_id, sub_step)
        if not append_sub_ret.get("ok"):
            return {"workflow_id": wf_id, "warning": f"failed to append workflow sub-step: {append_sub_ret.get('error')}"}

    stop_reason = _infer_stop_reason(tool_name, action, result, is_append=False)
    finish_ret = store.finish_run(
        wf_id,
        status=status,
        outputs_summary=outputs_summary,
        stop_reason=stop_reason,
        warnings=_safe_list(result.get("warnings")),
        blockers=_safe_list(result.get("blockers")),
        step_outputs_summary=outputs_summary,
        step_changed_files=extract_result["changed_files"],
        step_diff_hash=extract_result["diff_hash"],
        step_preview_ids=preview_ids,
    )
    if not finish_ret.get("ok"):
        return {"workflow_id": wf_id, "warning": f"failed to finish run: {finish_ret.get('error')}"}

    return {"workflow_id": wf_id}


def _infer_stop_reason(tool_name: str, action: str, result: dict[str, Any], is_append: bool) -> str:
    stop_reason = result.get("stop_reason")
    if isinstance(stop_reason, str) and stop_reason.strip():
        return stop_reason.strip()
    if action == "analyze":
        return "analysis_completed"
    if action in ("restore_file_preview", "revert_preview"):
        can_apply = result.get("can_apply", True)
        if not can_apply:
            return "preview_only_not_apply_supported"
        return "preview_created"
    if action == "preview":
        return "preview_created"
    if action in ("apply", "commit", "restore_file_apply"):
        return "completed"
    return "completed"


def _sanitize_workflow_sub_steps(raw_steps: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_steps, list):
        return []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    safe_steps: list[dict[str, Any]] = []
    for item in raw_steps:
        if not isinstance(item, dict):
            continue
        action_val = item.get("action")
        if not isinstance(action_val, str) or not action_val.strip():
            continue
        status_val = item.get("status")
        status = str(status_val).strip() if isinstance(status_val, str) and status_val.strip() else "completed"
        safe_steps.append({
            "step_id": uuid.uuid4().hex[:12],
            "started_at": now,
            "finished_at": now,
            "tool_name": "manage_executor_workflow",
            "action": action_val.strip(),
            "status": status,
            "risk_level": "info",
            "inputs_summary": {},
            "outputs_summary": {},
            "changed_files": [],
            "diff_hash": None,
            "preview_ids": [],
            "warnings": [],
            "blockers": [],
            "error_code": None,
            "stop_reason": None,
            "message_error": None,
        })
    return safe_steps
