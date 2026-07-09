from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runner._internal_utils import write_json_atomic
from runner.full_loop_authority import build_full_loop_authority_status
from runner.product_readiness import build_product_readiness_packet
from runner.release_submission_readiness import build_release_submission_readiness
from runner.sensitive_redaction import redact_sensitive_text


PRODUCT_CONSOLE_SOURCE = "product_console_map"
PRODUCT_CONSOLE_VERSION = "product_console.v1"
PRODUCT_CONSOLE_ACTION_RESULTS_SOURCE = "product_console_action_results"
PRODUCT_CONSOLE_ACTION_RESULTS_VERSION = "product_console_action_results.v1"
SUBMISSION_EVIDENCE_FILL_PREVIEW_SOURCE = "submission_evidence_fill_preview"
SUBMISSION_EVIDENCE_FILL_PREVIEW_VERSION = "submission_evidence_fill_preview.v1"
SUBMISSION_EVIDENCE_ACTIVITY_ACTION_ID = "submission_evidence_activity"
SUBMISSION_EVIDENCE_ACTIVITY_TOOL = "submission_evidence_activity_summary"
ACTION_RESULT_STATUSES = frozenset({"not_recorded", "pending", "updated", "requested", "blocked", "failed", "stale"})
RECORDABLE_ACTION_RESULT_STATUSES = ACTION_RESULT_STATUSES - {"not_recorded", "stale"}
REFRESH_RECOMMENDED_RESULT_STATUSES = frozenset({"updated", "requested"})
MAX_ACTION_RESULT_MESSAGE_CHARS = 240
MAX_STORED_ACTION_RESULTS = 50


def build_product_console_map(
    project_root: str,
    *,
    project_name: str | None = None,
    include_readiness: bool = True,
    include_full_loop_authority: bool = True,
    include_release_submission: bool = True,
    readiness_packet: dict[str, Any] | None = None,
    full_loop_authority: dict[str, Any] | None = None,
    release_submission_readiness: dict[str, Any] | None = None,
    action_results: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    readiness = readiness_packet if isinstance(readiness_packet, dict) else None
    if readiness is None and include_readiness:
        readiness = build_product_readiness_packet(project_root, now=now)
    full_loop = full_loop_authority if isinstance(full_loop_authority, dict) else None
    if full_loop is None and include_full_loop_authority:
        full_loop = build_full_loop_authority_status(project_root, now=now)
    release = release_submission_readiness if isinstance(release_submission_readiness, dict) else None
    if release is None and include_release_submission:
        release = build_release_submission_readiness(project_root, project_name=project_name, readiness_packet=readiness, now=now)
    status = _console_status(readiness, full_loop)
    entries = _console_entries(project_name=project_name, readiness=readiness, full_loop=full_loop, release_submission=release)
    result_state = action_results if isinstance(action_results, dict) else load_product_console_action_results(project_root)
    recommended_actions = _attach_action_results(
        _recommended_first_actions(
            project_name=project_name,
            status=status,
            readiness=readiness,
            release_submission=release,
        ),
        result_state,
    )
    action_result_state = _action_result_state_summary(result_state, recommended_actions)
    release_evidence_bundle = _release_submission_evidence_bundle(
        project_args={"project_name": project_name} if project_name else {},
        release_submission=release,
    )
    return {
        "ok": True,
        "source": PRODUCT_CONSOLE_SOURCE,
        "schema_version": PRODUCT_CONSOLE_VERSION,
        "read_only": True,
        "side_effects": False,
        "project_root": os.path.abspath(os.path.expanduser(project_root)),
        "project_name": project_name,
        "observed_at": _iso_now(now),
        "status": status,
        "summary": _summary_for(status),
        "default_mode": "public_beta_read_preview",
        "console_sections": [
            {
                "section_id": "connect_and_readiness",
                "title": "Connect And Readiness",
                "entry_ids": ["connect_chatgpt", "product_readiness", "apps_connector_smoke"],
            },
            {
                "section_id": "plan_and_review",
                "title": "Plan And Review",
                "entry_ids": ["operator_flow", "review_context", "stage_parallel_preview"],
            },
            {
                "section_id": "controlled_full_loop",
                "title": "Controlled Full Loop",
                "entry_ids": ["full_loop_authority", "executor_workflow", "validation_run", "git_commit", "git_remote_push"],
            },
            {
                "section_id": "stable_and_release",
                "title": "Stable And Release",
                "entry_ids": ["stable_promotion_readiness", "release_submission_readiness"],
            },
        ],
        "entries": entries,
        "recommended_first_actions": recommended_actions,
        "action_result_state": action_result_state,
        "completion_surface": _completion_surface(
            status=status,
            readiness=readiness,
            release_submission=release,
            action_result_state=action_result_state,
            release_evidence_bundle=release_evidence_bundle,
            recommended_actions=recommended_actions,
        ),
        "readiness_snapshot": _readiness_snapshot(readiness),
        "full_loop_authority_snapshot": _full_loop_snapshot(full_loop),
        "release_submission_snapshot": _release_submission_snapshot(release),
        "release_submission_evidence_bundle": release_evidence_bundle,
        "authority_boundary": _authority_boundary(),
        "not_authorized_actions": [
            "executor_run",
            "validation_run",
            "commit_or_push",
            "stable_replacement",
            "release_or_deploy",
            "read_tokens_or_cookies",
            "read_provider_config",
        ],
    }


def product_console_action_results_path(project_root: str) -> str:
    return str(Path(os.path.abspath(os.path.expanduser(project_root))) / ".colameta" / "runtime" / "product-console-action-results.json")


def load_product_console_action_results(project_root: str) -> dict[str, Any]:
    path = product_console_action_results_path(project_root)
    if not os.path.isfile(path):
        return _empty_action_results(project_root, status="empty")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception as exc:
        return {
            **_empty_action_results(project_root, status="unreadable"),
            "ok": False,
            "error_code": "ACTION_RESULTS_UNREADABLE",
            "message": _safe_action_result_message(str(exc)),
        }
    if not isinstance(payload, dict):
        return _empty_action_results(project_root, status="invalid")
    return _normalize_action_results_packet(project_root, payload)


def record_product_console_action_result(
    project_root: str,
    *,
    action_id: str | None = None,
    tool: str | None = None,
    mode: str | None = None,
    status: str,
    message: str | None = None,
    project_name: str | None = None,
    result_ok: bool | None = None,
    action_fingerprint: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    normalized_mode = mode if mode in {"read", "preview", "commit"} else "read"
    normalized_status = status if status in RECORDABLE_ACTION_RESULT_STATUSES else "failed"
    observed_at = _iso_now(now)
    entry = {
        "action_key": _action_key_from_fields(action_id=action_id, tool=tool, mode=normalized_mode),
        "action_id": _clean_optional_text(action_id),
        "tool": _clean_optional_text(tool),
        "mode": normalized_mode,
        "status": normalized_status,
        "message": _safe_action_result_message(message or normalized_status),
        "observed_at": observed_at,
    }
    clean_project_name = _clean_optional_text(project_name)
    if clean_project_name:
        entry["project_name"] = clean_project_name
    if result_ok is not None:
        entry["result_ok"] = bool(result_ok)
    clean_action_fingerprint = _clean_optional_text(action_fingerprint)
    if clean_action_fingerprint:
        entry["action_fingerprint"] = clean_action_fingerprint

    existing = load_product_console_action_results(project_root)
    entries = [item for item in _action_result_entries(existing) if item.get("action_key") != entry["action_key"]]
    entries.insert(0, entry)
    entries = entries[:MAX_STORED_ACTION_RESULTS]
    packet = {
        "ok": True,
        "source": PRODUCT_CONSOLE_ACTION_RESULTS_SOURCE,
        "schema_version": PRODUCT_CONSOLE_ACTION_RESULTS_VERSION,
        "read_only": False,
        "side_effects": True,
        "project_root": os.path.abspath(os.path.expanduser(project_root)),
        "project_name": clean_project_name,
        "status": "recorded",
        "updated_at": observed_at,
        "results": entries,
        "authority_boundary": {
            "writes_runtime_state_only": True,
            "does_not_store_raw_tool_output": True,
            "does_not_execute_action": True,
            "does_not_authorize_stable_replacement": True,
            "does_not_submit_app_for_review": True,
            "does_not_publish_app": True,
        },
    }
    write_json_atomic(product_console_action_results_path(project_root), packet)
    return {
        "ok": True,
        "source": PRODUCT_CONSOLE_ACTION_RESULTS_SOURCE,
        "schema_version": PRODUCT_CONSOLE_ACTION_RESULTS_VERSION,
        "read_only": False,
        "side_effects": True,
        "status": "recorded",
        "updated_at": observed_at,
        "recorded_result": entry,
        "stored_result_count": len(entries),
        "authority_boundary": packet["authority_boundary"],
    }


def build_submission_evidence_activity_result(
    project_root: str,
) -> dict[str, Any]:
    """Return the latest recorded submission evidence activity summary."""
    return _submission_evidence_activity_result(
        _action_result_entries(load_product_console_action_results(project_root)),
    )


def build_submission_evidence_fill_preview(
    project_root: str,
    *,
    project_name: str | None = None,
    selected_keys: list[str] | None = None,
    release_submission_readiness: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    release = release_submission_readiness if isinstance(release_submission_readiness, dict) else None
    if release is None:
        release = build_release_submission_readiness(
            project_root,
            project_name=project_name,
            no_network=True,
            now=now,
        )
    project_args = {"project_name": project_name} if project_name else {}
    bundle = _release_submission_evidence_bundle(project_args=project_args, release_submission=release)
    selected = _normalized_selected_evidence_keys(selected_keys)
    fill_plan = bundle.get("fill_plan") if isinstance(bundle.get("fill_plan"), dict) else {}
    draft_entries = fill_plan.get("draft_entries") if isinstance(fill_plan, dict) else []
    if not isinstance(draft_entries, list):
        draft_entries = []
    review_entries = fill_plan.get("review_entries") if isinstance(fill_plan, dict) else []
    if not isinstance(review_entries, list):
        review_entries = []
    filtered_entries = _filter_draft_entries(draft_entries, selected)
    filtered_review_entries = _filter_review_entries(review_entries, selected)
    fill_entries = [
        dict(entry.get("copyable_entry_shape") or {})
        for entry in filtered_entries
        if isinstance(entry, dict) and isinstance(entry.get("copyable_entry_shape"), dict)
    ]
    fill_entries = [
        {
            "key": str(entry.get("key") or ""),
            "filename": str(entry.get("filename") or ""),
            "content": str(entry.get("content") or "<operator-confirmed evidence text>"),
        }
        for entry in fill_entries
        if entry.get("key")
    ]
    available_keys = {
        str(entry.get("key"))
        for entry in [*filtered_entries, *filtered_review_entries]
        if isinstance(entry, dict) and entry.get("key")
    }
    ignored_selected_keys = sorted(selected - available_keys)
    status = _submission_evidence_fill_preview_status(
        bundle,
        fill_plan,
        fill_entries,
        filtered_review_entries,
        selected,
    )
    if status == "review_ready":
        copyable_tool = "mark_submission_evidence_ready_fields"
        review_keys = [str(entry.get("key")) for entry in filtered_review_entries if isinstance(entry, dict) and entry.get("key")]
        copyable_arguments = {**dict(fill_plan.get("next_arguments") or project_args), "keys": review_keys}
    else:
        copyable_tool = "fill_submission_evidence_files"
        copyable_arguments = {**project_args, "entries": fill_entries, "mark_ready": False}
    operator_instructions = _submission_evidence_preview_operator_instructions(status)
    return {
        "ok": True,
        "source": SUBMISSION_EVIDENCE_FILL_PREVIEW_SOURCE,
        "schema_version": SUBMISSION_EVIDENCE_FILL_PREVIEW_VERSION,
        "read_only": True,
        "side_effects": False,
        "project_root": os.path.abspath(os.path.expanduser(project_root)),
        "project_name": project_name,
        "observed_at": _iso_now(now),
        "status": status,
        "summary": _submission_evidence_fill_preview_summary(status, fill_entries),
        "selected_keys": sorted(selected),
        "ignored_selected_keys": ignored_selected_keys,
        "release_submission_status": _status_value(release),
        "evidence_bundle_status": bundle.get("status"),
        "fill_plan_status": fill_plan.get("status"),
        "draft_entry_count": len(filtered_entries),
        "review_entry_count": len(filtered_review_entries),
        "copyable_tool_call": {
            "tool": copyable_tool,
            "arguments": copyable_arguments,
            "required_scope": "mcp:commit",
            "requires_explicit_operator_review": True,
            "result_contract": _result_contract_for_action("commit", copyable_tool),
        },
        "operator_instructions": operator_instructions,
        "evidence_bundle": bundle,
        "authority_boundary": {
            "read_only": True,
            "side_effects": False,
            "does_not_write_files": True,
            "does_not_mark_ready_fields": True,
            "does_not_create_openai_app_draft": True,
            "does_not_submit_app_for_review": True,
            "does_not_publish_app": True,
            "does_not_read_tokens_or_cookies": True,
        },
    }


def _console_entries(
    *,
    project_name: str | None,
    readiness: dict[str, Any] | None,
    full_loop: dict[str, Any] | None,
    release_submission: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    project_args = {"project_name": project_name} if project_name else {}
    readiness_status = _status_value(readiness)
    full_loop_status = _status_value(full_loop)
    full_loop_ready = bool(isinstance(full_loop, dict) and full_loop.get("full_loop_ready") is True)
    return [
        _entry(
            "connect_chatgpt",
            label="Connect ChatGPT",
            mode="read",
            status="available",
            tool="get_chatgpt_app_readiness",
            arguments=project_args,
            why="Connect or reconnect the ChatGPT App and get the external connector sequence.",
        ),
        _entry(
            "product_readiness",
            label="Product Readiness",
            mode="read",
            status=readiness_status,
            tool="get_product_readiness_status",
            arguments=project_args,
            why="Check whether the public beta product surface is usable and what blocks it.",
        ),
        _entry(
            "apps_connector_smoke",
            label="Apps Connector Smoke",
            mode="read",
            status=_remote_connector_status(readiness),
            tool="get_apps_connector_smoke_packet",
            arguments=project_args,
            why="Collect external ChatGPT Apps connector smoke evidence.",
        ),
        _entry(
            "operator_flow",
            label="Operator Flow",
            mode="read",
            status="available",
            tool="get_agent_operator_flow_packet",
            arguments=project_args,
            why="Choose the profile-aware next read or preview action for the current task.",
        ),
        _entry(
            "review_context",
            label="Review Context",
            mode="read",
            status="available",
            tool="manage_git",
            arguments={**project_args, "action": "review_context", "include_repo_overview": False},
            why="Read the current review context without mutating the repository.",
        ),
        _entry(
            "stage_parallel_preview",
            label="Stage Parallel Preview",
            mode="preview",
            status="available",
            tool="get_stage_parallel_plan_preview",
            arguments=project_args,
            why="Inspect stage-parallel planning before any worktree or executor operation.",
        ),
        _entry(
            "full_loop_authority",
            label="Full Loop Authority",
            mode="read",
            status=full_loop_status,
            tool="get_full_loop_authority_status",
            arguments=project_args,
            why="Check whether complete executor/validation/commit/push controls are explicitly present.",
        ),
        _entry(
            "executor_workflow",
            label="Executor Workflow",
            mode="commit",
            status="blocked" if not full_loop_ready else "preview_required",
            tool="manage_executor_workflow",
            arguments={**project_args, "action": "preflight"},
            why="Executor run remains blocked until full-loop controls are ready; then it still starts with preflight/preview.",
        ),
        _entry(
            "validation_run",
            label="Validation Run",
            mode="commit",
            status="blocked" if not full_loop_ready else "preview_required",
            tool="manage_validation_run",
            arguments={**project_args, "action": "preview"},
            why="Validation run remains behind full-loop controls and preview-confirm.",
        ),
        _entry(
            "git_commit",
            label="Git Commit",
            mode="commit",
            status="blocked" if not full_loop_ready else "preview_required",
            tool="manage_git_commit",
            arguments={**project_args, "action": "readiness"},
            why="Commit remains behind full-loop controls and dedicated commit readiness.",
        ),
        _entry(
            "git_remote_push",
            label="Git Remote Push",
            mode="commit",
            status="blocked" if not full_loop_ready else "preview_required",
            tool="manage_git_remote",
            arguments={**project_args, "action": "push_status"},
            why="Remote push remains behind full-loop controls and dedicated remote push status.",
        ),
        _entry(
            "stable_promotion_readiness",
            label="Stable Promotion Readiness",
            mode="read",
            status="available",
            tool="get_stable_promotion_readiness",
            arguments=project_args,
            why="Read stable promotion evidence. This does not authorize replacement.",
        ),
        _entry(
            "release_submission_readiness",
            label="Release Submission Readiness",
            mode="read",
            status=_status_value(release_submission),
            tool="get_release_submission_readiness",
            arguments=project_args,
            why="Read local evidence for ChatGPT App release/submission readiness. This does not submit the app.",
        ),
    ]


def _entry(
    entry_id: str,
    *,
    label: str,
    mode: str,
    status: str,
    tool: str | None,
    arguments: dict[str, Any],
    why: str,
) -> dict[str, Any]:
    required_scope = "mcp:read" if mode == "read" else "mcp:preview" if mode == "preview" else "mcp:commit"
    return {
        "entry_id": entry_id,
        "label": label,
        "mode": mode,
        "status": status,
        "tool": tool,
        "arguments": arguments,
        "required_scope": required_scope,
        "requires_preview_confirm": mode != "read",
        "side_effects": False,
        "why": why,
    }


def _recommended_first_actions(
    *,
    project_name: str | None,
    status: str,
    readiness: dict[str, Any] | None,
    release_submission: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    project_args = {"project_name": project_name} if project_name else {}
    readiness_actions = _readiness_recommended_actions(project_args, readiness)
    release_actions = _release_submission_recommended_actions(project_args, release_submission)
    if status == "blocked":
        return readiness_actions + release_actions + [
            _recommended_action(
                "full_loop_authority",
                label="Full Loop Authority",
                mode="read",
                source="console_default",
                tool="get_full_loop_authority_status",
                arguments=project_args,
                why="Read whether controlled full-loop authority is enabled; this does not grant new authority.",
            ),
        ]
    if status == "needs_attention":
        return readiness_actions + release_actions + [
            _recommended_action(
                "operator_flow",
                label="Operator Flow",
                mode="read",
                source="console_default",
                tool="get_agent_operator_flow_packet",
                arguments=project_args,
                why="Read the profile-aware operator flow before choosing lower-level tools.",
            ),
            _recommended_action(
                "full_loop_authority",
                label="Full Loop Authority",
                mode="read",
                source="console_default",
                tool="get_full_loop_authority_status",
                arguments=project_args,
                why="Read whether controlled full-loop authority is enabled; this does not grant new authority.",
            ),
        ]
    return release_actions + [
        *readiness_actions,
        _recommended_action(
            "operator_flow",
            label="Operator Flow",
            mode="read",
            source="console_default",
            tool="get_agent_operator_flow_packet",
            arguments=project_args,
            why="Read the profile-aware operator flow before choosing lower-level tools.",
        ),
        _recommended_action(
            "full_loop_authority",
            label="Full Loop Authority",
            mode="read",
            source="console_default",
            tool="get_full_loop_authority_status",
            arguments=project_args,
            why="Read whether controlled full-loop authority is enabled; this does not grant new authority.",
        ),
    ]


def _readiness_recommended_actions(
    project_args: dict[str, Any],
    readiness: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    fallback = _recommended_action(
        "inspect_product_readiness",
        label="Product Readiness",
        mode="read",
        source="console_fallback",
        tool="get_product_readiness_status",
        arguments=project_args,
        why="Read product readiness and inspect the primary blocker.",
    )
    if not isinstance(readiness, dict):
        return [fallback]
    safe_next = readiness.get("safe_next_action")
    if not isinstance(safe_next, dict):
        return [fallback]
    tool = safe_next.get("tool")
    action = safe_next.get("action")
    runbook = safe_next.get("runbook")
    why = safe_next.get("why")
    arguments = safe_next.get("arguments") if isinstance(safe_next.get("arguments"), dict) else {}
    if isinstance(tool, str) and tool:
        return [
            _recommended_action(
                _action_id_from(action, tool, "readiness_safe_next_action"),
                label=_label_from_action(action, tool),
                mode="read",
                source="readiness_safe_next_action",
                tool=tool,
                action=action if isinstance(action, str) else None,
                arguments={**project_args, **arguments},
                why=why if isinstance(why, str) else "",
            )
        ]
    if isinstance(runbook, str) and runbook:
        return [
            _recommended_action(
                _action_id_from(action, None, "readiness_runbook"),
                label=_label_from_action(action, None),
                mode="read",
                source="readiness_safe_next_action",
                action=action if isinstance(action, str) else None,
                arguments={**project_args, **arguments},
                runbook=runbook,
                why=why if isinstance(why, str) else "",
            )
        ]
    return [fallback]


def _recommended_action(
    action_id: str,
    *,
    label: str,
    mode: str,
    source: str,
    tool: str | None = None,
    arguments: dict[str, Any] | None = None,
    action: str | None = None,
    runbook: str | None = None,
    why: str = "",
    evidence_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_mode = mode if mode in {"read", "preview", "commit"} else "read"
    requires_confirmation = normalized_mode != "read"
    side_effects = normalized_mode == "commit"
    item: dict[str, Any] = {
        "action_id": action_id,
        "label": label,
        "mode": normalized_mode,
        "status": "available",
        "arguments": dict(arguments or {}),
        "source": source,
        "required_scope": _required_scope_for_mode(normalized_mode),
        "requires_preview_confirm": normalized_mode != "read",
        "requires_explicit_confirmation": requires_confirmation,
        "side_effects": side_effects,
        "authority_boundary": {
            "does_not_execute_now": True,
            "read_only": normalized_mode == "read",
            "side_effects_if_invoked": side_effects,
            "requires_explicit_operator_action": True,
            "requires_explicit_confirmation": requires_confirmation,
            "does_not_authorize_stable_replacement": True,
            "does_not_submit_app_for_review": True,
            "does_not_publish_app": True,
        },
        "result_contract": _result_contract_for_action(normalized_mode, tool),
    }
    if isinstance(tool, str) and tool:
        item["tool"] = tool
    if isinstance(action, str) and action:
        item["action"] = action
    if isinstance(runbook, str) and runbook:
        item["runbook"] = runbook
    if why:
        item["why"] = why
    if isinstance(evidence_context, dict):
        item["evidence_context"] = evidence_context
    return item


def _result_contract_for_action(mode: str, tool: str | None) -> dict[str, Any]:
    refresh_after = _refresh_after_for_tool(tool)
    return {
        "schema_version": "recommended_action_result_contract.v1",
        "expected_result_kind": (
            "read_packet"
            if mode == "read"
            else "preview_packet"
            if mode == "preview"
            else "commit_scoped_result"
        ),
        "success_indicators": ["tool call returned without transport error", "result.ok is not false"],
        "failure_summary_source": "transport error, tool error, or result.error.message",
        "last_action_result_shape": {
            "status": "not_recorded|pending|updated|requested|blocked|failed|stale",
            "message": "<short operator-readable summary>",
            "observed_at": "<ISO-8601 timestamp>",
        },
        "refresh_after": refresh_after,
    }


def _refresh_after_for_tool(tool: str | None) -> list[dict[str, Any]]:
    if tool in {
        "fill_submission_evidence_files",
        "mark_submission_evidence_ready_fields",
        "init_submission_evidence",
    }:
        return [
            {"tool": "get_release_submission_readiness", "why": "Refresh submission evidence and manifest status."},
            {"tool": "get_product_console_map", "why": "Refresh recommended actions after local submission evidence changes."},
        ]
    if tool == "get_product_readiness_status":
        return [{"tool": "get_product_console_map", "why": "Refresh console actions after product readiness changes."}]
    if tool == "get_apps_connector_smoke_packet":
        return [{"tool": "get_product_readiness_status", "why": "Refresh product readiness after connector smoke evidence."}]
    if tool == "get_stable_replacement_cadence":
        return [{"tool": "get_product_console_map", "why": "Refresh console guidance after stable cadence review."}]
    if tool == "render_commander_app":
        return [{"tool": "get_product_console_map", "why": "Refresh console action cards after entering Commander."}]
    return []


def _attach_action_results(actions: list[dict[str, Any]], result_state: dict[str, Any]) -> list[dict[str, Any]]:
    index = _action_result_index(result_state)
    attached: list[dict[str, Any]] = []
    for action in actions:
        item = dict(action)
        action_key = _action_key_for_model(item)
        action_fingerprint = _action_fingerprint_for_model(item)
        item["action_key"] = action_key
        item["action_fingerprint"] = action_fingerprint
        item["last_action_result"] = _action_result_for_current_action(index.get(action_key), action_fingerprint)
        item["next_refresh_actions"] = _next_refresh_actions_for_action(item)
        attached.append(item)
    return attached


def _action_result_state_summary(result_state: dict[str, Any], actions: list[dict[str, Any]]) -> dict[str, Any]:
    entries = _action_result_entries(result_state)
    latest = entries[0] if entries else None
    pending_refreshes = _pending_refresh_actions(actions)
    submission_activity = _submission_evidence_activity_result(entries)
    return {
        "source": PRODUCT_CONSOLE_ACTION_RESULTS_SOURCE,
        "schema_version": PRODUCT_CONSOLE_ACTION_RESULTS_VERSION,
        "status": str(result_state.get("status") or "empty") if isinstance(result_state, dict) else "empty",
        "available": bool(entries),
        "stored_result_count": len(entries),
        "stale_result_count": sum(
            1
            for action in actions
            if isinstance(action.get("last_action_result"), dict)
            and action["last_action_result"].get("status") == "stale"
        ),
        "latest": latest,
        "submission_evidence_activity": submission_activity,
        "pending_refresh_count": len(pending_refreshes),
        "pending_refreshes": pending_refreshes,
        "authority_boundary": {
            "read_only": True,
            "does_not_write_runtime_state": True,
            "does_not_store_raw_tool_output": True,
        },
    }


def _completion_surface(
    *,
    status: str,
    readiness: dict[str, Any] | None,
    release_submission: dict[str, Any] | None,
    action_result_state: dict[str, Any],
    release_evidence_bundle: dict[str, Any],
    recommended_actions: list[dict[str, Any]],
) -> dict[str, Any]:
    readiness_status = _status_value(readiness)
    release_status = _status_value(release_submission)
    fill_plan = release_evidence_bundle.get("fill_plan") if isinstance(release_evidence_bundle, dict) else None
    fill_plan_status = str(fill_plan.get("status") or "unknown") if isinstance(fill_plan, dict) else "unknown"
    submission_activity = (
        action_result_state.get("submission_evidence_activity")
        if isinstance(action_result_state.get("submission_evidence_activity"), dict)
        else {}
    )
    pending_refreshes = (
        action_result_state.get("pending_refreshes")
        if isinstance(action_result_state.get("pending_refreshes"), list)
        else []
    )
    components = {
        "product_readiness": {
            "status": readiness_status,
            "ready": isinstance(readiness, dict) and readiness.get("ready") is True,
        },
        "release_submission": {
            "status": release_status,
            "ready": isinstance(release_submission, dict) and release_submission.get("ready") is True,
        },
        "submission_evidence": {
            "status": fill_plan_status,
            "ready": release_evidence_bundle.get("ready") is True and fill_plan_status == "ready",
        },
        "submission_evidence_activity": {
            "status": submission_activity.get("status") or "not_recorded",
            "ready": submission_activity.get("available") is True and submission_activity.get("result_ok") is not False,
            "available": submission_activity.get("available") is True,
        },
        "action_refresh": {
            "status": "pending" if pending_refreshes else "current",
            "ready": not pending_refreshes,
            "pending_refresh_count": len(pending_refreshes),
        },
    }
    gaps = _completion_gaps(components)
    blocker_codes = [gap["code"] for gap in gaps if gap.get("severity") == "blocker"]
    needs_attention_codes = [gap["code"] for gap in gaps if gap.get("severity") == "needs_attention"]
    completion_status = "ready" if not gaps else "blocked" if blocker_codes else "needs_attention"
    safe_next_action = _completion_safe_next_action(
        readiness=readiness,
        release_evidence_bundle=release_evidence_bundle,
        action_result_state=action_result_state,
        recommended_actions=recommended_actions,
        gaps=gaps,
    )
    return {
        "source": "product_console_completion_surface",
        "schema_version": "product_console_completion_surface.v1",
        "read_only": True,
        "side_effects": False,
        "status": completion_status,
        "console_status": status,
        "ready": completion_status == "ready",
        "summary": _completion_summary(completion_status, gaps),
        "components": components,
        "gap_count": len(gaps),
        "gaps": gaps,
        "blocker_codes": blocker_codes,
        "needs_attention_codes": needs_attention_codes,
        "safe_next_action": safe_next_action,
        "action_groups": _completion_action_groups(
            status=completion_status,
            gaps=gaps,
            recommended_actions=recommended_actions,
            safe_next_action=safe_next_action,
        ),
        "authority_boundary": {
            "read_only": True,
            "side_effects": False,
            "does_not_execute_actions": True,
            "does_not_write_runtime_state": True,
            "does_not_submit_app_for_review": True,
            "does_not_authorize_stable_replacement": True,
        },
    }


def _completion_gaps(components: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    if not components["product_readiness"]["ready"]:
        gaps.append(
            {
                "code": "PRODUCT_READINESS_NOT_READY",
                "component": "product_readiness",
                "severity": "blocker" if components["product_readiness"]["status"] == "blocked" else "needs_attention",
                "status": components["product_readiness"]["status"],
            }
        )
    if not components["release_submission"]["ready"]:
        gaps.append(
            {
                "code": "RELEASE_SUBMISSION_NOT_READY",
                "component": "release_submission",
                "severity": "blocker" if components["release_submission"]["status"] == "blocked" else "needs_attention",
                "status": components["release_submission"]["status"],
            }
        )
    if not components["submission_evidence"]["ready"]:
        gaps.append(
            {
                "code": "SUBMISSION_EVIDENCE_NOT_READY",
                "component": "submission_evidence",
                "severity": "needs_attention",
                "status": components["submission_evidence"]["status"],
            }
        )
    if not components["submission_evidence_activity"]["ready"]:
        gaps.append(
            {
                "code": "SUBMISSION_EVIDENCE_ACTIVITY_NOT_RECORDED",
                "component": "submission_evidence_activity",
                "severity": "needs_attention",
                "status": components["submission_evidence_activity"]["status"],
            }
        )
    if not components["action_refresh"]["ready"]:
        gaps.append(
            {
                "code": "ACTION_REFRESH_PENDING",
                "component": "action_refresh",
                "severity": "needs_attention",
                "status": components["action_refresh"]["status"],
            }
        )
    return gaps


def _completion_summary(status: str, gaps: list[dict[str, Any]]) -> str:
    if status == "ready":
        return "Product console closeout is ready: readiness, release evidence, recorded activity, and refresh state are current."
    return f"Product console closeout needs attention: {len(gaps)} gap(s) remain."


def _completion_safe_next_action(
    *,
    readiness: dict[str, Any] | None,
    release_evidence_bundle: dict[str, Any],
    action_result_state: dict[str, Any],
    recommended_actions: list[dict[str, Any]],
    gaps: list[dict[str, Any]],
) -> dict[str, Any]:
    first_gap = gaps[0] if gaps else None
    if not first_gap:
        return {
            "action": "continue_with_public_beta_workflow",
            "tool": "render_commander_app",
            "authority": "read_only",
            "why": "Closeout surface is ready; continue through Commander without granting write authority.",
        }
    component = first_gap.get("component")
    if component == "product_readiness" and isinstance(readiness, dict) and isinstance(readiness.get("safe_next_action"), dict):
        return {
            **readiness["safe_next_action"],
            "authority": "read_only",
            "why": readiness["safe_next_action"].get("why") or "Resolve product readiness before claiming closeout ready.",
        }
    if component in {"release_submission", "submission_evidence"}:
        fill_plan = release_evidence_bundle.get("fill_plan") if isinstance(release_evidence_bundle, dict) else None
        if isinstance(fill_plan, dict) and isinstance(fill_plan.get("next_tool"), str):
            return {
                "action": fill_plan.get("status"),
                "tool": fill_plan.get("next_tool"),
                "arguments": dict(fill_plan.get("next_arguments") or {}),
                "authority": "commit" if fill_plan.get("next_tool") in {"fill_submission_evidence_files", "mark_submission_evidence_ready_fields", "init_submission_evidence"} else "read_only",
                "why": fill_plan.get("why") or "Complete release submission evidence before claiming closeout ready.",
            }
    if component == "submission_evidence_activity":
        return {
            "action": "record_submission_evidence_activity",
            "tool": "record_product_console_action_result",
            "authority": "commit",
            "why": "Record the latest submission evidence activity summary after review/refresh actions complete.",
        }
    if component == "action_refresh":
        pending = action_result_state.get("pending_refreshes") if isinstance(action_result_state.get("pending_refreshes"), list) else []
        first = pending[0] if pending and isinstance(pending[0], dict) else {}
        return {
            "action": "refresh_after_recorded_action",
            "tool": first.get("tool") or "get_product_console_map",
            "arguments": dict(first.get("arguments") or {}),
            "authority": "read_only",
            "why": first.get("why") or "Refresh the read surface after a recorded action result.",
        }
    first_action = recommended_actions[0] if recommended_actions else {}
    return {
        "action": first_action.get("action_id") or "inspect_product_console",
        "tool": first_action.get("tool") or "get_product_console_map",
        "arguments": dict(first_action.get("arguments") or {}),
        "authority": first_action.get("required_scope") or "mcp:read",
        "why": first_action.get("why") or "Inspect the next recommended product console action.",
    }


def _completion_action_groups(
    *,
    status: str,
    gaps: list[dict[str, Any]],
    recommended_actions: list[dict[str, Any]],
    safe_next_action: dict[str, Any],
) -> list[dict[str, Any]]:
    if not gaps:
        return [
            {
                "group_id": "closeout_ready",
                "label": "Closeout Ready",
                "status": "ready",
                "gap_codes": [],
                "primary_action": dict(safe_next_action),
                "action_refs": _completion_action_refs_for_component("closeout_ready", recommended_actions),
                "empty_state": "Closeout is ready; continue through the read-only Commander flow.",
            }
        ]
    groups: list[dict[str, Any]] = []
    seen_components: set[str] = set()
    for gap in gaps:
        component = str(gap.get("component") or "unknown")
        if component in seen_components:
            continue
        seen_components.add(component)
        component_gaps = [item for item in gaps if item.get("component") == component]
        action_refs = _completion_action_refs_for_component(component, recommended_actions)
        primary_action = (
            dict(safe_next_action)
            if gap is gaps[0]
            else _completion_primary_action_from_refs(action_refs, component)
        )
        groups.append(
            {
                "group_id": component,
                "label": _completion_group_label(component),
                "status": "blocked" if any(item.get("severity") == "blocker" for item in component_gaps) else "needs_attention",
                "component": component,
                "gap_codes": [str(item.get("code")) for item in component_gaps if item.get("code")],
                "primary_action": primary_action,
                "action_refs": action_refs,
                "empty_state": _completion_group_empty_state(component),
            }
        )
    return groups


def _completion_action_refs_for_component(
    component: str,
    recommended_actions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for action in recommended_actions:
        if not _completion_action_matches_component(component, action):
            continue
        refs.append(_completion_action_ref(action))
    return refs


def _completion_action_matches_component(component: str, action: dict[str, Any]) -> bool:
    tool = str(action.get("tool") or "")
    action_id = str(action.get("action_id") or "")
    source = str(action.get("source") or "")
    if component == "product_readiness":
        return tool in {"get_product_readiness_status", "get_apps_connector_smoke_packet", "get_stable_replacement_cadence"} or source == "readiness_safe_next_action"
    if component in {"release_submission", "submission_evidence"}:
        return tool in {
            "get_release_submission_readiness",
            "init_submission_evidence",
            "fill_submission_evidence_files",
            "mark_submission_evidence_ready_fields",
            "get_submission_evidence_fill_preview",
        }
    if component == "submission_evidence_activity":
        return action_id == SUBMISSION_EVIDENCE_ACTIVITY_ACTION_ID or tool == SUBMISSION_EVIDENCE_ACTIVITY_TOOL
    if component == "action_refresh":
        return bool(action.get("next_refresh_actions"))
    if component == "closeout_ready":
        return tool == "render_commander_app" or action_id == "operator_flow"
    return False


def _completion_action_ref(action: dict[str, Any]) -> dict[str, Any]:
    ref = {
        "action_id": action.get("action_id"),
        "label": action.get("label"),
        "tool": action.get("tool"),
        "action": action.get("action"),
        "runbook": action.get("runbook"),
        "mode": action.get("mode"),
        "required_scope": action.get("required_scope"),
        "arguments": action.get("arguments"),
        "status": action.get("status"),
    }
    return {key: value for key, value in ref.items() if value not in (None, "", {})}


def _completion_primary_action_from_refs(action_refs: list[dict[str, Any]], component: str) -> dict[str, Any]:
    if action_refs:
        first = dict(action_refs[0])
        first["authority"] = first.get("required_scope") or first.get("mode") or "mcp:read"
        return first
    return {
        "action": f"inspect_{component}",
        "tool": "get_product_console_map",
        "authority": "read_only",
        "why": _completion_group_empty_state(component),
    }


def _completion_group_label(component: str) -> str:
    labels = {
        "product_readiness": "Product Readiness",
        "release_submission": "Release Submission",
        "submission_evidence": "Submission Evidence",
        "submission_evidence_activity": "Evidence Activity",
        "action_refresh": "Action Refresh",
        "closeout_ready": "Closeout Ready",
    }
    return labels.get(component, component.replace("_", " ").title())


def _completion_group_empty_state(component: str) -> str:
    messages = {
        "product_readiness": "Read product readiness or run the connector smoke packet before continuing.",
        "release_submission": "Read release submission readiness and complete the remaining local submission material.",
        "submission_evidence": "Fill or review the local submission evidence before claiming closeout ready.",
        "submission_evidence_activity": "Record the latest submission evidence activity after refresh/recovery actions.",
        "action_refresh": "Run the pending read-only refresh actions before trusting the console state.",
        "closeout_ready": "Closeout is ready; continue through the read-only Commander flow.",
    }
    return messages.get(component, "Inspect Product Console recommendations for the next safe action.")


def _submission_evidence_activity_result(entries: list[dict[str, Any]]) -> dict[str, Any]:
    expected_key = _action_key_from_fields(
        action_id=SUBMISSION_EVIDENCE_ACTIVITY_ACTION_ID,
        tool=SUBMISSION_EVIDENCE_ACTIVITY_TOOL,
        mode="read",
    )
    for entry in entries:
        if entry.get("action_key") != expected_key:
            continue
        result = {
            "available": True,
            "action_key": entry.get("action_key"),
            "action_id": entry.get("action_id"),
            "tool": entry.get("tool"),
            "mode": entry.get("mode"),
            "status": entry.get("status"),
            "message": entry.get("message"),
            "observed_at": entry.get("observed_at"),
            "result_ok": entry.get("result_ok"),
            "project_name": entry.get("project_name"),
            "read_only_summary": True,
            "authority_boundary": {
                "read_only": True,
                "does_not_write_runtime_state": True,
                "does_not_store_raw_tool_output": True,
            },
        }
        return {key: value for key, value in result.items() if value is not None}
    return {
        "available": False,
        "status": "not_recorded",
        "message": "No submission evidence activity result recorded yet.",
        "read_only_summary": True,
    }


def _empty_action_results(project_root: str, *, status: str) -> dict[str, Any]:
    return {
        "ok": True,
        "source": PRODUCT_CONSOLE_ACTION_RESULTS_SOURCE,
        "schema_version": PRODUCT_CONSOLE_ACTION_RESULTS_VERSION,
        "read_only": True,
        "side_effects": False,
        "project_root": os.path.abspath(os.path.expanduser(project_root)),
        "status": status,
        "results": [],
    }


def _normalize_action_results_packet(project_root: str, packet: dict[str, Any]) -> dict[str, Any]:
    entries = _action_result_entries(packet)
    return {
        "ok": bool(packet.get("ok", True)),
        "source": PRODUCT_CONSOLE_ACTION_RESULTS_SOURCE,
        "schema_version": PRODUCT_CONSOLE_ACTION_RESULTS_VERSION,
        "read_only": bool(packet.get("read_only", True)),
        "side_effects": bool(packet.get("side_effects", False)),
        "project_root": os.path.abspath(os.path.expanduser(project_root)),
        "project_name": _clean_optional_text(packet.get("project_name")),
        "status": _clean_optional_text(packet.get("status")) or ("loaded" if entries else "empty"),
        "updated_at": _clean_optional_text(packet.get("updated_at")),
        "results": entries[:MAX_STORED_ACTION_RESULTS],
    }


def _action_result_entries(packet: dict[str, Any]) -> list[dict[str, Any]]:
    raw = packet.get("results") if isinstance(packet, dict) else []
    values = raw.values() if isinstance(raw, dict) else raw
    if not isinstance(values, list) and not hasattr(values, "__iter__"):
        return []
    entries: list[dict[str, Any]] = []
    for value in values:
        if not isinstance(value, dict):
            continue
        entry = _normalize_action_result_entry(value)
        if entry is not None:
            entries.append(entry)
    entries.sort(key=lambda item: item.get("observed_at") or "", reverse=True)
    return entries


def _normalize_action_result_entry(value: dict[str, Any]) -> dict[str, Any] | None:
    action_id = _clean_optional_text(value.get("action_id"))
    tool = _clean_optional_text(value.get("tool"))
    mode = _clean_optional_text(value.get("mode")) or "read"
    if mode not in {"read", "preview", "commit"}:
        mode = "read"
    action_key = _clean_optional_text(value.get("action_key")) or _action_key_from_fields(
        action_id=action_id,
        tool=tool,
        mode=mode,
    )
    if not action_key:
        return None
    status = _clean_optional_text(value.get("status")) or "failed"
    if status not in ACTION_RESULT_STATUSES:
        status = "failed"
    entry = {
        "action_key": action_key,
        "action_id": action_id,
        "tool": tool,
        "mode": mode,
        "status": status,
        "message": _safe_action_result_message(value.get("message") or status),
        "observed_at": _clean_optional_text(value.get("observed_at")),
    }
    project_name = _clean_optional_text(value.get("project_name"))
    if project_name:
        entry["project_name"] = project_name
    if isinstance(value.get("result_ok"), bool):
        entry["result_ok"] = value["result_ok"]
    action_fingerprint = _clean_optional_text(value.get("action_fingerprint"))
    if action_fingerprint:
        entry["action_fingerprint"] = action_fingerprint
    return entry


def _action_result_index(result_state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for entry in _action_result_entries(result_state):
        key = entry.get("action_key")
        if isinstance(key, str) and key and key not in index:
            index[key] = entry
    return index


def _not_recorded_action_result() -> dict[str, Any]:
    return {
        "status": "not_recorded",
        "message": "No action result recorded yet.",
        "observed_at": None,
        "stale": False,
        "refresh_recommended": False,
    }


def _action_result_for_current_action(entry: dict[str, Any] | None, current_fingerprint: str) -> dict[str, Any]:
    if not isinstance(entry, dict):
        return _not_recorded_action_result()
    result = dict(entry)
    recorded_fingerprint = _clean_optional_text(result.get("action_fingerprint"))
    if recorded_fingerprint and recorded_fingerprint != current_fingerprint:
        previous_status = _clean_optional_text(result.get("status")) or "failed"
        result["previous_status"] = previous_status
        result["status"] = "stale"
        result["message"] = "Recorded result is stale because the recommended action changed."
        result["stale"] = True
        result["stale_reason"] = "action_fingerprint_changed"
        result["current_action_fingerprint"] = current_fingerprint
        result["refresh_recommended"] = False
        return result
    result["stale"] = False
    if recorded_fingerprint:
        result["fingerprint_verified"] = True
    return result


def _next_refresh_actions_for_action(action: dict[str, Any]) -> list[dict[str, Any]]:
    result = action.get("last_action_result") if isinstance(action.get("last_action_result"), dict) else {}
    if not _result_should_offer_refresh(result):
        return []
    contract = action.get("result_contract") if isinstance(action.get("result_contract"), dict) else {}
    refresh_after = contract.get("refresh_after") if isinstance(contract.get("refresh_after"), list) else []
    if not refresh_after:
        return []
    action_key = _clean_optional_text(action.get("action_key")) or _action_key_for_model(action)
    arguments = _refresh_arguments_for_action(action)
    status = _clean_optional_text(result.get("status")) or "updated"
    observed_at = _clean_optional_text(result.get("observed_at"))
    refreshes: list[dict[str, Any]] = []
    for item in refresh_after:
        if not isinstance(item, dict):
            continue
        tool = _clean_optional_text(item.get("tool"))
        if not tool:
            continue
        refreshes.append(
            {
                "tool": tool,
                "arguments": arguments,
                "why": _clean_optional_text(item.get("why")) or "Refresh after the recorded action result.",
                "source_action_key": action_key,
                "after_result_status": status,
                "after_observed_at": observed_at,
                "requires_operator_or_agent_refresh": True,
            }
        )
    if refreshes:
        result["refresh_recommended"] = True
    return refreshes


def _result_should_offer_refresh(result: dict[str, Any]) -> bool:
    status = _clean_optional_text(result.get("status"))
    if status not in REFRESH_RECOMMENDED_RESULT_STATUSES:
        return False
    if result.get("result_ok") is False:
        return False
    return True


def _refresh_arguments_for_action(action: dict[str, Any]) -> dict[str, Any]:
    arguments = action.get("arguments") if isinstance(action.get("arguments"), dict) else {}
    project_name = _clean_optional_text(arguments.get("project_name"))
    return {"project_name": project_name} if project_name else {}


def _pending_refresh_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pending: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for action in actions:
        refreshes = action.get("next_refresh_actions") if isinstance(action.get("next_refresh_actions"), list) else []
        for refresh in refreshes:
            if not isinstance(refresh, dict):
                continue
            tool = _clean_optional_text(refresh.get("tool"))
            if not tool:
                continue
            args_key = json.dumps(refresh.get("arguments") or {}, sort_keys=True, ensure_ascii=True)
            key = (tool, args_key)
            if key in seen:
                continue
            seen.add(key)
            pending.append(refresh)
    return pending


def _action_key_for_model(action: dict[str, Any]) -> str:
    return _action_key_from_fields(
        action_id=_clean_optional_text(action.get("action_id")),
        tool=_clean_optional_text(action.get("tool")),
        mode=_clean_optional_text(action.get("mode")) or "read",
    )


def _action_fingerprint_for_model(action: dict[str, Any]) -> str:
    surface = {
        "action": _clean_optional_text(action.get("action")),
        "action_id": _clean_optional_text(action.get("action_id")),
        "arguments": action.get("arguments") if isinstance(action.get("arguments"), dict) else {},
        "mode": _clean_optional_text(action.get("mode")) or "read",
        "required_scope": _clean_optional_text(action.get("required_scope")),
        "requires_explicit_confirmation": bool(action.get("requires_explicit_confirmation")),
        "result_contract": action.get("result_contract") if isinstance(action.get("result_contract"), dict) else {},
        "runbook": _clean_optional_text(action.get("runbook")),
        "side_effects": bool(action.get("side_effects")),
        "tool": _clean_optional_text(action.get("tool")),
    }
    encoded = json.dumps(surface, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def _action_key_from_fields(*, action_id: str | None, tool: str | None, mode: str | None) -> str:
    parts = [_clean_optional_text(action_id), _clean_optional_text(tool), _clean_optional_text(mode) or "read"]
    return "|".join(part for part in parts if part)


def _clean_optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.strip().split())
    return cleaned or None


def _safe_action_result_message(value: Any) -> str:
    redacted = redact_sensitive_text(str(value), replacement_token="<redacted>", preserve_token_prefix=True)
    cleaned = " ".join(redacted.strip().split())
    if len(cleaned) > MAX_ACTION_RESULT_MESSAGE_CHARS:
        return cleaned[: MAX_ACTION_RESULT_MESSAGE_CHARS - 3] + "..."
    return cleaned


def _required_scope_for_mode(mode: str) -> str:
    if mode == "preview":
        return "mcp:preview"
    if mode == "commit":
        return "mcp:commit"
    return "mcp:read"


def _action_id_from(action: Any, tool: Any, fallback: str) -> str:
    raw = action if isinstance(action, str) and action else tool if isinstance(tool, str) and tool else fallback
    normalized = "".join(char.lower() if char.isalnum() else "_" for char in raw)
    return "_".join(part for part in normalized.split("_") if part) or fallback


def _label_from_action(action: Any, tool: Any) -> str:
    raw = action if isinstance(action, str) and action else tool if isinstance(tool, str) and tool else "Recommended Action"
    return " ".join(part.capitalize() for part in raw.replace("-", "_").split("_") if part) or "Recommended Action"


def _release_submission_recommended_actions(
    project_args: dict[str, Any],
    release_submission: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not isinstance(release_submission, dict) or release_submission.get("ready") is True:
        return []
    materials = release_submission.get("submission_materials")
    source = materials.get("source") if isinstance(materials, dict) else "unknown"
    checks = release_submission.get("checks")
    evidence_check = checks.get("submission_evidence_references") if isinstance(checks, dict) else None
    manifest_check = checks.get("submission_materials_manifest") if isinstance(checks, dict) else None
    progress = release_submission.get("submission_evidence_progress")
    review_keys = _filled_not_marked_ready_keys(progress)
    if source in {"unknown", "parameters_only"}:
        return [
            _recommended_action(
                "init_submission_evidence",
                label="Init Submission Evidence",
                mode="commit",
                source="release_submission_readiness",
                tool="init_submission_evidence",
                arguments=project_args,
                why="Create the real submission manifest and local evidence scaffold before release/App submission.",
            )
        ]
    if isinstance(manifest_check, dict) and manifest_check.get("status") == "needs_attention":
        return [
            _recommended_action(
                "release_submission_readiness",
                label="Release Submission Readiness",
                mode="read",
                source="release_submission_readiness",
                tool="get_release_submission_readiness",
                arguments=project_args,
                why="Fix submission manifest schema or unknown fields before collecting final evidence.",
            )
        ]
    if isinstance(evidence_check, dict) and evidence_check.get("status") == "needs_attention":
        entry_templates = list(evidence_check.get("fill_entry_templates") or [])
        return [
            _recommended_action(
                "fill_submission_evidence_files",
                label="Fill Submission Evidence",
                mode="commit",
                source="release_submission_readiness",
                tool="fill_submission_evidence_files",
                arguments={
                    **project_args,
                    "entries": [],
                },
                evidence_context={
                    "missing_keys": list(evidence_check.get("missing_keys") or []),
                    "missing_files": list(evidence_check.get("missing_files") or []),
                    "missing_files_by_key": list(evidence_check.get("missing_files_by_key") or []),
                    "placeholder_files": list(evidence_check.get("placeholder_files") or []),
                    "placeholder_files_by_key": list(evidence_check.get("placeholder_files_by_key") or []),
                    "incomplete_keys": list(evidence_check.get("incomplete_keys") or []),
                    "entry_templates": entry_templates,
                },
                why="Replace placeholder submission evidence and add missing files before marking release/App submission ready.",
            )
        ]
    if review_keys:
        return [
            _recommended_action(
                "mark_submission_evidence_ready_fields",
                label="Mark Submission Evidence Ready",
                mode="commit",
                source="release_submission_readiness",
                tool="mark_submission_evidence_ready_fields",
                arguments={
                    **project_args,
                    "keys": review_keys,
                    "review_confirmation": "human_reviewed",
                },
                evidence_context={
                    "keys": review_keys,
                    "ready_fields": _ready_fields_for_keys(progress, review_keys),
                    "refs_by_key": _refs_by_key(progress, review_keys),
                },
                why="All selected evidence files are present; review them and mark the corresponding ready fields true.",
            )
        ]
    return [
        _recommended_action(
            "release_submission_readiness",
            label="Release Submission Readiness",
            mode="read",
            source="release_submission_readiness",
            tool="get_release_submission_readiness",
            arguments=project_args,
            why="Review release/App submission readiness details and complete remaining materials.",
        )
    ]


def _console_status(readiness: dict[str, Any] | None, full_loop: dict[str, Any] | None) -> str:
    readiness_status = _status_value(readiness)
    if readiness_status == "blocked":
        return "blocked"
    if readiness_status in {"needs_attention", "unknown"}:
        return "needs_attention"
    if _status_value(full_loop) == "ready":
        return "full_loop_ready"
    return "ready_read_preview"


def _readiness_snapshot(readiness: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(readiness, dict):
        return {"status": "unknown", "ready": False}
    return {
        "status": _status_value(readiness),
        "ready": readiness.get("ready") is True,
        "primary_blocker": readiness.get("primary_blocker"),
        "safe_next_action": readiness.get("safe_next_action"),
    }


def _full_loop_snapshot(full_loop: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(full_loop, dict):
        return {"status": "unknown", "full_loop_ready": False}
    return {
        "status": _status_value(full_loop),
        "full_loop_ready": full_loop.get("full_loop_ready") is True,
        "effective_authority": full_loop.get("effective_authority"),
        "missing_controls": list(full_loop.get("missing_controls") or []),
    }


def _release_submission_snapshot(release_submission: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(release_submission, dict):
        return {"status": "unknown", "ready": False}
    return {
        "status": _status_value(release_submission),
        "ready": release_submission.get("ready") is True,
        "blocker_codes": list(release_submission.get("blocker_codes") or []),
        "needs_attention_codes": list(release_submission.get("needs_attention_codes") or []),
        "submission_materials": _release_submission_materials_snapshot(release_submission),
        "safe_next_action": release_submission.get("safe_next_action"),
    }


def _release_submission_materials_snapshot(release_submission: dict[str, Any]) -> dict[str, Any]:
    materials = release_submission.get("submission_materials")
    checks = release_submission.get("checks")
    evidence_check = checks.get("submission_evidence_references") if isinstance(checks, dict) else None
    if not isinstance(materials, dict):
        return {"source": "unknown", "effective_fields": []}
    return {
        "source": materials.get("source") or "unknown",
        "source_detail": materials.get("source_detail"),
        "effective_fields": list(materials.get("effective_fields") or []),
        "evidence_keys": list(materials.get("evidence_keys") or []),
        "evidence_status": evidence_check.get("status") if isinstance(evidence_check, dict) else "unknown",
        "missing_evidence_keys": list(evidence_check.get("missing_keys") or []) if isinstance(evidence_check, dict) else [],
        "missing_evidence_files": list(evidence_check.get("missing_files") or []) if isinstance(evidence_check, dict) else [],
        "placeholder_evidence_files": list(evidence_check.get("placeholder_files") or []) if isinstance(evidence_check, dict) else [],
        "incomplete_evidence_keys": list(evidence_check.get("incomplete_keys") or []) if isinstance(evidence_check, dict) else [],
        "evidence_entry_templates": list(release_submission.get("submission_evidence_entry_templates") or []),
        "evidence_progress": release_submission.get("submission_evidence_progress"),
        "ignored_manifest_fields": list(materials.get("ignored_manifest_fields") or []),
        "error": materials.get("error"),
    }


def _release_submission_evidence_bundle(
    *,
    project_args: dict[str, Any],
    release_submission: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(release_submission, dict):
        return {
            "ok": True,
            "source": "release_submission_evidence_bundle",
            "schema_version": "release_submission_evidence_bundle.v1",
            "read_only": True,
            "side_effects": False,
            "status": "unknown",
            "summary": "Release submission evidence is not loaded.",
            "manifest": {"status": "unknown", "available": False},
            "progress_summary": {"status": "unknown", "complete_count": 0, "total_count": 0, "counts": {}},
            "fill_plan": _release_submission_fill_plan(
                project_args=project_args,
                release_submission=None,
                progress=None,
                manifest_status="unknown",
            ),
            "authority_boundary": _submission_evidence_bundle_authority_boundary(),
        }

    materials = release_submission.get("submission_materials")
    if not isinstance(materials, dict):
        materials = {}
    checks = release_submission.get("checks")
    evidence_check = checks.get("submission_evidence_references") if isinstance(checks, dict) else None
    manifest_check = checks.get("submission_materials_manifest") if isinstance(checks, dict) else None
    progress = release_submission.get("submission_evidence_progress")
    manifest_source = str(materials.get("source") or "unknown")
    manifest_available = manifest_source not in {"unknown", "parameters_only"}
    manifest_status = str(manifest_check.get("status") or "unknown") if isinstance(manifest_check, dict) else "unknown"
    progress_summary = _release_submission_progress_summary(progress)
    fill_plan = _release_submission_fill_plan(
        project_args=project_args,
        release_submission=release_submission,
        progress=progress,
        manifest_status=manifest_status,
    )
    return {
        "ok": True,
        "source": "release_submission_evidence_bundle",
        "schema_version": "release_submission_evidence_bundle.v1",
        "read_only": True,
        "side_effects": False,
        "status": _status_value(release_submission),
        "ready": release_submission.get("ready") is True,
        "summary": _release_submission_evidence_bundle_summary(release_submission, progress_summary),
        "manifest": {
            "status": manifest_status,
            "source": manifest_source,
            "available": manifest_available,
            "default_path": "docs/chatgpt-app-submission-materials.json",
            "effective_fields": list(materials.get("effective_fields") or []),
            "ignored_manifest_fields": list(materials.get("ignored_manifest_fields") or []),
            "error": materials.get("error"),
        },
        "progress_summary": progress_summary,
        "gap_summary": {
            "blocker_codes": list(release_submission.get("blocker_codes") or []),
            "needs_attention_codes": list(release_submission.get("needs_attention_codes") or []),
            "missing_keys": list(evidence_check.get("missing_keys") or []) if isinstance(evidence_check, dict) else [],
            "missing_files": list(evidence_check.get("missing_files") or []) if isinstance(evidence_check, dict) else [],
            "placeholder_files": list(evidence_check.get("placeholder_files") or []) if isinstance(evidence_check, dict) else [],
            "incomplete_keys": list(evidence_check.get("incomplete_keys") or []) if isinstance(evidence_check, dict) else [],
        },
        "fill_plan": fill_plan,
        "authority_boundary": _submission_evidence_bundle_authority_boundary(),
    }


def _release_submission_progress_summary(progress: Any) -> dict[str, Any]:
    if not isinstance(progress, dict):
        return {"status": "unknown", "complete_count": 0, "total_count": 0, "counts": {}, "rows": []}
    rows = progress.get("rows")
    compact_rows: list[dict[str, Any]] = []
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            compact_rows.append(
                {
                    "key": row.get("key"),
                    "ready_field": row.get("ready_field"),
                    "status": row.get("status"),
                    "ready": row.get("ready") is True,
                    "refs": list(row.get("refs") or []) if isinstance(row.get("refs"), list) else [],
                    "default_path": row.get("default_path"),
                }
            )
    return {
        "status": progress.get("status") or "unknown",
        "complete_count": progress.get("complete_count") if isinstance(progress.get("complete_count"), int) else 0,
        "total_count": progress.get("total_count") if isinstance(progress.get("total_count"), int) else len(compact_rows),
        "counts": dict(progress.get("counts") or {}) if isinstance(progress.get("counts"), dict) else {},
        "rows": compact_rows,
    }


def _release_submission_fill_plan(
    *,
    project_args: dict[str, Any],
    release_submission: dict[str, Any] | None,
    progress: Any,
    manifest_status: str,
) -> dict[str, Any]:
    if not isinstance(release_submission, dict):
        return {
            "status": "needs_release_readiness",
            "next_tool": "get_release_submission_readiness",
            "next_arguments": project_args,
            "draft_entries": [],
            "human_review_required": True,
            "why": "Load release submission readiness before collecting evidence.",
        }
    materials = release_submission.get("submission_materials")
    source = materials.get("source") if isinstance(materials, dict) else "unknown"
    if source in {"unknown", "parameters_only"}:
        return {
            "status": "manifest_missing",
            "next_tool": "init_submission_evidence",
            "next_arguments": project_args,
            "draft_entries": [],
            "human_review_required": True,
            "why": "Create the real local submission manifest before filling evidence files.",
        }
    if manifest_status == "needs_attention":
        return {
            "status": "manifest_needs_attention",
            "next_tool": "get_release_submission_readiness",
            "next_arguments": project_args,
            "draft_entries": [],
            "human_review_required": True,
            "why": "Fix manifest schema or unknown fields before writing evidence files.",
        }
    if release_submission.get("ready") is True:
        return {
            "status": "ready",
            "next_tool": "get_release_submission_readiness",
            "next_arguments": project_args,
            "draft_entries": [],
            "human_review_required": False,
            "why": "Submission evidence is already marked ready by the local manifest and readiness checks.",
        }
    review_keys = _filled_not_marked_ready_keys(progress)
    if review_keys:
        return {
            "status": "evidence_ready_for_review",
            "next_tool": "mark_submission_evidence_ready_fields",
            "next_arguments": {
                **project_args,
                "keys": review_keys,
                "review_confirmation": "human_reviewed",
            },
            "draft_entries": [],
            "review_entries": _review_entries_for_keys(progress, review_keys),
            "human_review_required": True,
            "why": "Evidence files are present; human review is required before setting manifest ready fields true.",
        }
    draft_entries = _release_submission_draft_entries(release_submission, progress)
    return {
        "status": "evidence_needs_fill",
        "next_tool": "fill_submission_evidence_files",
        "next_arguments": {**project_args, "entries": []},
        "draft_entries": draft_entries,
        "human_review_required": True,
        "why": "Fill real operator-reviewed evidence text before marking the corresponding ready fields true.",
    }


def _release_submission_draft_entries(release_submission: dict[str, Any], progress: Any) -> list[dict[str, Any]]:
    templates_by_key = {
        str(item.get("key")): item
        for item in list(release_submission.get("submission_evidence_entry_templates") or [])
        if isinstance(item, dict) and item.get("key")
    }
    rows = progress.get("rows") if isinstance(progress, dict) else []
    entries: list[dict[str, Any]] = []
    if not isinstance(rows, list):
        return entries
    for row in rows:
        if not isinstance(row, dict) or row.get("status") == "ready":
            continue
        key = str(row.get("key") or "")
        if not key:
            continue
        template = row.get("template") if isinstance(row.get("template"), dict) else templates_by_key.get(key, {})
        default_path = str(row.get("default_path") or template.get("default_path") or "")
        default_filename = str(template.get("default_filename") or os.path.basename(default_path) or f"{key}.md")
        entries.append(
            {
                "key": key,
                "ready_field": row.get("ready_field"),
                "current_status": row.get("status"),
                "default_path": default_path,
                "filename": default_filename,
                "purpose": template.get("purpose") or template.get("content_prompt"),
                "required_sections": list(template.get("required_sections") or []),
                "copyable_entry_shape": {
                    "key": key,
                    "filename": default_filename,
                    "content": "<operator-confirmed evidence text>",
                },
            }
        )
    return entries


def _filled_not_marked_ready_keys(progress: Any) -> list[str]:
    if not isinstance(progress, dict):
        return []
    counts = progress.get("counts")
    if not isinstance(counts, dict):
        return []
    if any(_count_value(counts.get(key)) > 0 for key in ("needs_attention", "placeholder", "not_started")):
        return []
    rows = progress.get("rows")
    if not isinstance(rows, list):
        return []
    return [
        str(row.get("key"))
        for row in rows
        if isinstance(row, dict) and row.get("status") == "filled_not_marked_ready" and row.get("key")
    ]


def _count_value(value: Any) -> int:
    return value if isinstance(value, int) else 0


def _review_entries_for_keys(progress: Any, keys: list[str]) -> list[dict[str, Any]]:
    key_set = set(keys)
    rows = progress.get("rows") if isinstance(progress, dict) else []
    if not isinstance(rows, list):
        return []
    entries: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict) or str(row.get("key") or "") not in key_set:
            continue
        entries.append(
            {
                "key": row.get("key"),
                "ready_field": row.get("ready_field"),
                "refs": list(row.get("refs") or []) if isinstance(row.get("refs"), list) else [],
                "current_status": row.get("status"),
                "next_action": row.get("next_action"),
            }
        )
    return entries


def _ready_fields_for_keys(progress: Any, keys: list[str]) -> list[str]:
    return [
        str(item.get("ready_field"))
        for item in _review_entries_for_keys(progress, keys)
        if item.get("ready_field")
    ]


def _refs_by_key(progress: Any, keys: list[str]) -> list[dict[str, Any]]:
    return [
        {"key": item["key"], "refs": item["refs"]}
        for item in _review_entries_for_keys(progress, keys)
        if item.get("key")
    ]


def _release_submission_evidence_bundle_summary(
    release_submission: dict[str, Any],
    progress_summary: dict[str, Any],
) -> str:
    if release_submission.get("ready") is True:
        return "Release submission evidence is ready."
    total = progress_summary.get("total_count") or 0
    complete = progress_summary.get("complete_count") or 0
    return f"Release submission evidence needs attention: {complete}/{total} evidence items are ready."


def _normalized_selected_evidence_keys(selected_keys: list[str] | None) -> set[str]:
    if not isinstance(selected_keys, list):
        return set()
    return {str(item).strip() for item in selected_keys if isinstance(item, str) and str(item).strip()}


def _filter_draft_entries(draft_entries: list[Any], selected_keys: set[str]) -> list[dict[str, Any]]:
    entries = [entry for entry in draft_entries if isinstance(entry, dict)]
    if not selected_keys:
        return entries
    return [entry for entry in entries if str(entry.get("key") or "") in selected_keys]


def _filter_review_entries(review_entries: list[Any], selected_keys: set[str]) -> list[dict[str, Any]]:
    entries = [entry for entry in review_entries if isinstance(entry, dict)]
    if not selected_keys:
        return entries
    return [entry for entry in entries if str(entry.get("key") or "") in selected_keys]


def _submission_evidence_fill_preview_status(
    bundle: dict[str, Any],
    fill_plan: dict[str, Any],
    fill_entries: list[dict[str, Any]],
    review_entries: list[dict[str, Any]],
    selected_keys: set[str],
) -> str:
    fill_plan_status = str(fill_plan.get("status") or "unknown")
    if fill_plan_status == "ready":
        return "no_fill_needed"
    if fill_plan_status == "manifest_missing":
        return "manifest_missing"
    if fill_plan_status == "manifest_needs_attention":
        return "manifest_needs_attention"
    if fill_plan_status == "needs_release_readiness":
        return "needs_release_readiness"
    if fill_plan_status == "evidence_ready_for_review":
        if review_entries:
            return "review_ready"
        if selected_keys:
            return "selected_keys_not_available"
        return "no_preview_entries"
    if selected_keys and not fill_entries:
        return "selected_keys_not_available"
    if fill_entries:
        return "preview_ready"
    if bundle.get("ready") is True:
        return "no_fill_needed"
    return "no_preview_entries"


def _submission_evidence_fill_preview_summary(status: str, fill_entries: list[dict[str, Any]]) -> str:
    if status == "preview_ready":
        return f"Prepared a read-only fill payload preview with {len(fill_entries)} evidence entries."
    if status == "review_ready":
        return "Prepared a read-only ready-field marking payload for human-reviewed evidence."
    if status == "no_fill_needed":
        return "Submission evidence is already ready; no fill payload is needed."
    if status == "manifest_missing":
        return "Submission manifest is missing; initialize the evidence scaffold before filling files."
    if status == "manifest_needs_attention":
        return "Submission manifest needs attention before a fill payload can be prepared."
    if status == "selected_keys_not_available":
        return "No draft evidence entries matched the selected keys."
    return "No submission evidence fill payload is ready yet."


def _submission_evidence_preview_operator_instructions(status: str) -> list[str]:
    if status == "review_ready":
        return [
            "Review every referenced evidence file before running the mark-ready tool.",
            "Use review_confirmation=human_reviewed only after a human reviewer confirms the evidence is final.",
            "Run get_release_submission_readiness again after marking ready fields.",
        ]
    return [
        "Review every entry and replace <operator-confirmed evidence text> with real evidence before running the write tool.",
        "Keep mark_ready=false until a human reviewer confirms the referenced evidence is final.",
        "Run get_release_submission_readiness again after filling files.",
    ]


def _submission_evidence_bundle_authority_boundary() -> dict[str, bool]:
    return {
        "read_only": True,
        "side_effects": False,
        "does_not_write_files": True,
        "does_not_mark_ready_fields": True,
        "does_not_create_openai_app_draft": True,
        "does_not_submit_app_for_review": True,
        "does_not_publish_app": True,
        "does_not_read_tokens_or_cookies": True,
    }


def _remote_connector_status(readiness: dict[str, Any] | None) -> str:
    if not isinstance(readiness, dict):
        return "unknown"
    remote = readiness.get("remote_connector")
    if not isinstance(remote, dict):
        return "unknown"
    smoke = remote.get("connector_smoke")
    if not isinstance(smoke, dict):
        return "unknown"
    return str(smoke.get("status") or "unknown")


def _status_value(packet: dict[str, Any] | None) -> str:
    if not isinstance(packet, dict):
        return "unknown"
    return str(packet.get("status") or "unknown")


def _summary_for(status: str) -> str:
    if status == "full_loop_ready":
        return "Product console is ready and controlled full-loop controls are present."
    if status == "ready_read_preview":
        return "Product console is ready in public beta read/preview mode."
    if status == "blocked":
        return "Product console has a product-readiness blocker that should be handled first."
    return "Product console needs attention before a clean operator handoff."


def _authority_boundary() -> dict[str, bool]:
    return {
        "read_only": True,
        "side_effects": False,
        "does_not_start_executor": True,
        "does_not_run_validation": True,
        "does_not_commit": True,
        "does_not_push": True,
        "does_not_replace_stable_service": True,
        "does_not_release_or_deploy": True,
        "does_not_read_tokens_or_cookies": True,
        "does_not_read_provider_config": True,
    }


def _iso_now(now: datetime | None) -> str:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
