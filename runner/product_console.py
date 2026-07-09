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
        "recommended_first_actions": _recommended_first_actions(project_name=project_name, status=status),
        "readiness_snapshot": _readiness_snapshot(readiness),
        "full_loop_authority_snapshot": _full_loop_snapshot(full_loop),
        "release_submission_snapshot": _release_submission_snapshot(release),
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


def _recommended_first_actions(*, project_name: str | None, status: str) -> list[dict[str, Any]]:
    project_args = {"project_name": project_name} if project_name else {}
    if status == "blocked":
        return [
            {"tool": "get_product_readiness_status", "arguments": project_args},
            {"tool": "get_full_loop_authority_status", "arguments": project_args},
        ]
    return [
        {"tool": "get_product_readiness_status", "arguments": project_args},
        {"tool": "get_agent_operator_flow_packet", "arguments": project_args},
        {"tool": "get_full_loop_authority_status", "arguments": project_args},
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
        "safe_next_action": release_submission.get("safe_next_action"),
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
