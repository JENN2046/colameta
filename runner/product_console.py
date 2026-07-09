from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from runner.full_loop_authority import build_full_loop_authority_status
from runner.product_readiness import build_product_readiness_packet
from runner.release_submission_readiness import build_release_submission_readiness


PRODUCT_CONSOLE_SOURCE = "product_console_map"
PRODUCT_CONSOLE_VERSION = "product_console.v1"
SUBMISSION_EVIDENCE_FILL_PREVIEW_SOURCE = "submission_evidence_fill_preview"
SUBMISSION_EVIDENCE_FILL_PREVIEW_VERSION = "submission_evidence_fill_preview.v1"


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
        "recommended_first_actions": _recommended_first_actions(
            project_name=project_name,
            status=status,
            readiness=readiness,
            release_submission=release,
        ),
        "readiness_snapshot": _readiness_snapshot(readiness),
        "full_loop_authority_snapshot": _full_loop_snapshot(full_loop),
        "release_submission_snapshot": _release_submission_snapshot(release),
        "release_submission_evidence_bundle": _release_submission_evidence_bundle(
            project_args={"project_name": project_name} if project_name else {},
            release_submission=release,
        ),
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
