from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any


FULL_LOOP_SOURCE = "full_loop_authority_status"
FULL_LOOP_PHASE = "controlled_full_loop"
CONFIRMATION_MODE_PREVIEW_CONFIRM = "preview_confirm"
DISABLED = "disabled"
READY = "ready"
NEEDS_ATTENTION = "needs_attention"
BLOCKED = "blocked"

REQUIRED_GATES = (
    "executor_run",
    "validation_run",
    "local_commit",
    "remote_push",
)


def build_full_loop_authority_status(
    project_root: str,
    *,
    enable_full_loop: bool = False,
    confirmation_mode: str | None = None,
    allow_executor_run: bool = False,
    allow_validation_run: bool = False,
    allow_local_commit: bool = False,
    allow_remote_push: bool = False,
    allow_stable_replacement: bool = False,
    operator_confirmation_ref: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return a read-only status packet for the controlled full-loop boundary."""
    normalized_confirmation_mode = _normalize_confirmation_mode(confirmation_mode)
    requested_gates = {
        "executor_run": bool(allow_executor_run),
        "validation_run": bool(allow_validation_run),
        "local_commit": bool(allow_local_commit),
        "remote_push": bool(allow_remote_push),
    }
    missing_gates = [name for name in REQUIRED_GATES if not requested_gates[name]]
    confirmation_ready = normalized_confirmation_mode == CONFIRMATION_MODE_PREVIEW_CONFIRM
    confirmation_ref_ready = _has_confirmation_ref(operator_confirmation_ref)
    status = _status_for(
        enable_full_loop=enable_full_loop,
        confirmation_ready=confirmation_ready,
        confirmation_ref_ready=confirmation_ref_ready,
        missing_gates=missing_gates,
    )
    return {
        "ok": True,
        "source": FULL_LOOP_SOURCE,
        "read_only": True,
        "side_effects": False,
        "product_phase": FULL_LOOP_PHASE,
        "project_root": os.path.abspath(os.path.expanduser(project_root)),
        "observed_at": _iso_now(now),
        "status": status,
        "full_loop_ready": status == READY,
        "effective_authority": "controlled_full_loop" if status == READY else "read_preview_only",
        "summary": _summary_for(status),
        "requested_controls": {
            "enable_full_loop": bool(enable_full_loop),
            "confirmation_mode": normalized_confirmation_mode or "missing",
            "operator_confirmation_ref_present": confirmation_ref_ready,
            "allow_executor_run": bool(allow_executor_run),
            "allow_validation_run": bool(allow_validation_run),
            "allow_local_commit": bool(allow_local_commit),
            "allow_remote_push": bool(allow_remote_push),
            "allow_stable_replacement": bool(allow_stable_replacement),
        },
        "capability_gates": _capability_gates(
            requested_gates=requested_gates,
            enable_full_loop=enable_full_loop,
            confirmation_ready=confirmation_ready,
            confirmation_ref_ready=confirmation_ref_ready,
        ),
        "missing_controls": _missing_controls(
            enable_full_loop=enable_full_loop,
            confirmation_ready=confirmation_ready,
            confirmation_ref_ready=confirmation_ref_ready,
            missing_gates=missing_gates,
        ),
        "stable_replacement": {
            "status": BLOCKED,
            "requested": bool(allow_stable_replacement),
            "why": (
                "Stable replacement is never enabled by the generic full-loop authority status. "
                "It still requires a separate exact commit authorization and replacement receipt."
            ),
        },
        "safe_next_action": _safe_next_action(status),
        "authority_boundary": _authority_boundary(),
        "not_authorized_actions": _not_authorized_actions(status),
    }


def _status_for(
    *,
    enable_full_loop: bool,
    confirmation_ready: bool,
    confirmation_ref_ready: bool,
    missing_gates: list[str],
) -> str:
    if not enable_full_loop:
        return DISABLED
    if not confirmation_ready:
        return BLOCKED
    if not confirmation_ref_ready or missing_gates:
        return NEEDS_ATTENTION
    return READY


def _capability_gates(
    *,
    requested_gates: dict[str, bool],
    enable_full_loop: bool,
    confirmation_ready: bool,
    confirmation_ref_ready: bool,
) -> dict[str, dict[str, Any]]:
    gate_tools = {
        "executor_run": "manage_executor_workflow",
        "validation_run": "manage_validation_run",
        "local_commit": "manage_git_commit",
        "remote_push": "manage_git_remote",
    }
    gates: dict[str, dict[str, Any]] = {}
    for name in REQUIRED_GATES:
        requested = requested_gates[name]
        ready = bool(enable_full_loop and requested and confirmation_ready and confirmation_ref_ready)
        gates[name] = {
            "status": READY if ready else (DISABLED if not enable_full_loop else NEEDS_ATTENTION),
            "requested": requested,
            "required_scope": "mcp:commit",
            "tool": gate_tools[name],
            "requires_preview_confirm": True,
            "requires_operator_confirmation_ref": True,
        }
    return gates


def _missing_controls(
    *,
    enable_full_loop: bool,
    confirmation_ready: bool,
    confirmation_ref_ready: bool,
    missing_gates: list[str],
) -> list[str]:
    missing: list[str] = []
    if not enable_full_loop:
        missing.append("enable_full_loop")
    if not confirmation_ready:
        missing.append("confirmation_mode_preview_confirm")
    if not confirmation_ref_ready:
        missing.append("operator_confirmation_ref")
    missing.extend(missing_gates)
    return missing


def _safe_next_action(status: str) -> dict[str, Any]:
    if status == READY:
        return {
            "action": "use_preview_confirm_workflow",
            "why": "Full-loop authority controls are present; each write/run action still needs its own preview and confirmation.",
        }
    if status == DISABLED:
        return {
            "action": "stay_in_public_beta_read_preview",
            "why": "Full loop is disabled by default; continue using read-only and preview-first product surfaces.",
        }
    return {
        "action": "complete_full_loop_controls",
        "why": "The full-loop request is incomplete or missing preview-confirm controls.",
    }


def _authority_boundary() -> dict[str, bool]:
    return {
        "read_only_status_packet": True,
        "side_effects": False,
        "does_not_read_env_values": True,
        "does_not_read_tokens_or_cookies": True,
        "does_not_read_provider_config": True,
        "does_not_write_config": True,
        "does_not_start_executor": True,
        "does_not_run_validation": True,
        "does_not_commit": True,
        "does_not_push": True,
        "does_not_replace_stable_service": True,
        "does_not_release_or_deploy": True,
    }


def _not_authorized_actions(status: str) -> list[str]:
    if status == READY:
        return [
            "stable_replacement",
            "release_or_deploy",
            "skip_preview_confirm",
            "read_tokens_or_cookies",
        ]
    return [
        "executor_run",
        "validation_run",
        "commit_or_push",
        "stable_replacement",
        "release_or_deploy",
        "skip_preview_confirm",
        "read_tokens_or_cookies",
    ]


def _summary_for(status: str) -> str:
    if status == READY:
        return "Controlled full-loop authority controls are present; individual write/run actions still require preview-confirm."
    if status == BLOCKED:
        return "Controlled full-loop request is blocked because preview-confirm mode is missing or invalid."
    if status == NEEDS_ATTENTION:
        return "Controlled full-loop request needs all required gates and an operator confirmation reference."
    return "Controlled full-loop authority is disabled; ColaMeta remains in read/preview public beta mode."


def _normalize_confirmation_mode(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower().replace("-", "_")
    return normalized or None


def _has_confirmation_ref(value: str | None) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _iso_now(now: datetime | None) -> str:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
