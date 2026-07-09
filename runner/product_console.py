from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from runner.full_loop_authority import build_full_loop_authority_status
from runner.product_readiness import build_product_readiness_packet
from runner.release_submission_readiness import build_release_submission_readiness


PRODUCT_CONSOLE_SOURCE = "product_console_map"
PRODUCT_CONSOLE_VERSION = "product_console.v1"


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
    release_submission: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    project_args = {"project_name": project_name} if project_name else {}
    release_actions = _release_submission_recommended_actions(project_args, release_submission)
    if status == "blocked":
        return release_actions + [
            {"tool": "get_product_readiness_status", "arguments": project_args},
            {"tool": "get_full_loop_authority_status", "arguments": project_args},
        ]
    return release_actions + [
        {"tool": "get_product_readiness_status", "arguments": project_args},
        {"tool": "get_agent_operator_flow_packet", "arguments": project_args},
        {"tool": "get_full_loop_authority_status", "arguments": project_args},
    ]


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
    if source in {"unknown", "parameters_only"}:
        return [
            {
                "tool": "init_submission_evidence",
                "arguments": project_args,
                "why": "Create the real submission manifest and local evidence scaffold before release/App submission.",
            }
        ]
    if isinstance(manifest_check, dict) and manifest_check.get("status") == "needs_attention":
        return [
            {
                "tool": "get_release_submission_readiness",
                "arguments": project_args,
                "why": "Fix submission manifest schema or unknown fields before collecting final evidence.",
            }
        ]
    if isinstance(evidence_check, dict) and evidence_check.get("status") == "needs_attention":
        entry_templates = list(evidence_check.get("fill_entry_templates") or [])
        return [
            {
                "tool": "fill_submission_evidence_files",
                "arguments": {
                    **project_args,
                    "entries": [],
                },
                "evidence_context": {
                    "missing_keys": list(evidence_check.get("missing_keys") or []),
                    "missing_files": list(evidence_check.get("missing_files") or []),
                    "missing_files_by_key": list(evidence_check.get("missing_files_by_key") or []),
                    "placeholder_files": list(evidence_check.get("placeholder_files") or []),
                    "placeholder_files_by_key": list(evidence_check.get("placeholder_files_by_key") or []),
                    "incomplete_keys": list(evidence_check.get("incomplete_keys") or []),
                    "entry_templates": entry_templates,
                },
                "why": "Replace placeholder submission evidence and add missing files before marking release/App submission ready.",
            }
        ]
    return [
        {
            "tool": "get_release_submission_readiness",
            "arguments": project_args,
            "why": "Review release/App submission readiness details and complete remaining materials.",
        }
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


def _release_submission_evidence_bundle_summary(
    release_submission: dict[str, Any],
    progress_summary: dict[str, Any],
) -> str:
    if release_submission.get("ready") is True:
        return "Release submission evidence is ready."
    total = progress_summary.get("total_count") or 0
    complete = progress_summary.get("complete_count") or 0
    return f"Release submission evidence needs attention: {complete}/{total} evidence items are ready."


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
