from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlparse

from runner.production_ops import (
    BLOCKED,
    DEFAULT_CONNECTOR_SMOKE_FRESH_HOURS,
    DEFAULT_PUBLIC_BASE_URL,
    NEEDS_ATTENTION,
    READY,
    build_production_ops_packet,
)
from runner.full_loop_authority import build_full_loop_authority_status
from runner.runtime_observability import build_stable_replacement_cadence


PRODUCT_PHASE_PUBLIC_BETA = "public_beta_mvp"
DEFAULT_VISIBLE_AUTHORITY = "read_preview_only"
COMMANDER_RENDER_TOOL = "render_commander_app"
READINESS_TOOL = "get_product_readiness_status"
CHATGPT_APP_READINESS_TOOL = "get_chatgpt_app_readiness"
APPS_SMOKE_TOOL = "get_apps_connector_smoke_packet"
STABLE_REPLACEMENT_CADENCE_TOOL = "get_stable_replacement_cadence"
STABLE_PROMOTION_READINESS_TOOL = "get_stable_promotion_readiness"
RUNTIME_VERSION_STATUS_TOOL = "get_runtime_version_status"
STABLE_DELIVERY_DECISION_VERSION = "stable_delivery_decision.v1"


def build_product_readiness_packet(
    project_root: str,
    *,
    project_name: str | None = None,
    public_base_url: str = DEFAULT_PUBLIC_BASE_URL,
    expected_head: str | None = None,
    no_network: bool = False,
    connector_smoke: dict[str, Any] | None = None,
    connector_smoke_fresh_hours: int = DEFAULT_CONNECTOR_SMOKE_FRESH_HOURS,
    command_runner: Callable[[list[str]], Any] | None = None,
    preflight_runner: Callable[..., dict[str, Any]] | None = None,
    now: datetime | None = None,
    ops_packet_builder: Callable[..., dict[str, Any]] | None = None,
    stable_cadence_builder: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a product-level, read-only readiness packet from ops evidence."""
    builder = ops_packet_builder or build_production_ops_packet
    ops_packet = builder(
        project_root,
        public_base_url=public_base_url,
        expected_head=expected_head,
        no_network=no_network,
        connector_smoke=connector_smoke,
        connector_smoke_fresh_hours=connector_smoke_fresh_hours,
        command_runner=command_runner,
        preflight_runner=preflight_runner,
        now=now,
    )
    full_loop_authority = build_full_loop_authority_status(project_root, now=now)
    checks = ops_packet.get("checks") if isinstance(ops_packet.get("checks"), dict) else {}
    stable_delivery_decision = _stable_delivery_decision(
        project_root=project_root,
        project_name=project_name,
        ops_packet=ops_packet,
        checks=checks,
        cadence_builder=stable_cadence_builder or build_stable_replacement_cadence,
    )
    primary_blocker = _primary_blocker(checks)
    status = _product_status(ops_packet)
    return {
        "ok": True,
        "source": "product_readiness",
        "read_only": True,
        "side_effects": False,
        "product_phase": PRODUCT_PHASE_PUBLIC_BETA,
        "default_authority": DEFAULT_VISIBLE_AUTHORITY,
        "project_root": ops_packet.get("project_root") or os.path.abspath(os.path.expanduser(project_root)),
        "project_name": project_name,
        "public_base_url": ops_packet.get("public_base_url") or public_base_url,
        "connector_url": _connector_url(str(ops_packet.get("public_base_url") or public_base_url)),
        "observed_at": ops_packet.get("observed_at") or _iso_now(now),
        "status": status,
        "ready": status == READY,
        "summary": _product_summary(status, ops_packet),
        "primary_blocker": primary_blocker,
        "safe_next_action": _safe_next_action(
            status,
            primary_blocker,
            stable_delivery_decision,
            project_args={"project_name": project_name} if project_name else {},
        ),
        "stable_delivery_decision": stable_delivery_decision,
        "chatgpt_app": {
            "status": status,
            "main_entry": COMMANDER_RENDER_TOOL,
            "readiness_tool": READINESS_TOOL,
            "chatgpt_app_readiness_tool": CHATGPT_APP_READINESS_TOOL,
            "smoke_tool": APPS_SMOKE_TOOL,
            "stable_replacement_cadence_tool": STABLE_REPLACEMENT_CADENCE_TOOL,
            "stable_promotion_readiness_tool": STABLE_PROMOTION_READINESS_TOOL,
            "default_visible_authority": ["read", "preview"],
            "write_tools_default": "blocked_until_local_config_and_explicit_confirmation",
            "full_loop_authority_tool": "get_full_loop_authority_status",
        },
        "full_loop_authority": full_loop_authority,
        "local_service": {
            "stable_runtime": _check_summary(checks.get("stable_runtime")),
            "stable_service": _check_summary(checks.get("stable_service")),
            "local_stable_health": _check_summary(checks.get("local_stable_health")),
        },
        "remote_connector": {
            "remote_https_mcp_preflight": _check_summary(checks.get("remote_https_mcp_preflight")),
            "cloudflared_service": _check_summary(checks.get("cloudflared_service")),
            "connector_smoke": _check_summary(checks.get("connector_smoke")),
        },
        "ops_check": {
            "status": ops_packet.get("status"),
            "ops_check_ready": ops_packet.get("ops_check_ready") is True,
            "connector_smoke_ready": ops_packet.get("connector_smoke_ready") is True,
            "beta_gate_ready": ops_packet.get("beta_gate_ready") is True,
            "reason_codes": list(ops_packet.get("reason_codes") or []),
            "blocker_codes": list(ops_packet.get("blocker_codes") or []),
            "needs_attention_codes": list(ops_packet.get("needs_attention_codes") or []),
        },
        "authority_boundary": _authority_boundary(),
        "not_authorized_actions": list(ops_packet.get("not_authorized_actions") or _not_authorized_actions()),
    }


def build_chatgpt_connection_packet(
    project_root: str,
    *,
    project_name: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    readiness = build_product_readiness_packet(project_root, project_name=project_name, **kwargs)
    project_args = {"project_name": project_name} if project_name else {}
    return {
        "ok": True,
        "source": "chatgpt_connection_readiness",
        "read_only": True,
        "side_effects": False,
        "connector_url": readiness["connector_url"],
        "project_root": readiness["project_root"],
        "project_name": project_name,
        "status": readiness["status"],
        "ready": readiness["ready"],
        "product_readiness": readiness,
        "recommended_sequence": [
            {"tool": "list_registered_projects", "arguments": {}},
            {"tool": "get_agent_consumer_contract", "arguments": {}},
            {"tool": READINESS_TOOL, "arguments": dict(project_args)},
            {"tool": COMMANDER_RENDER_TOOL, "arguments": dict(project_args)},
            {"tool": APPS_SMOKE_TOOL, "arguments": dict(project_args)},
        ],
        "operator_note": (
            "Use the connector URL in ChatGPT Apps, then run the recommended read-only sequence. "
            "This packet does not authorize executor run, commit, push, service restart, or stable replacement."
        ),
        "authority_boundary": _authority_boundary(),
    }


def build_apps_connector_smoke_handoff_packet(
    project_root: str,
    *,
    project_name: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    readiness = build_product_readiness_packet(project_root, project_name=project_name, **kwargs)
    project_args = {"project_name": project_name} if project_name else {}
    return {
        "ok": True,
        "source": "apps_connector_smoke_handoff",
        "read_only": True,
        "side_effects": False,
        "status": readiness["remote_connector"]["connector_smoke"]["status"],
        "product_status": readiness["status"],
        "connector_url": readiness["connector_url"],
        "project_root": readiness["project_root"],
        "project_name": project_name,
        "operator_sequence": [
            {"tool": "list_registered_projects", "arguments": {}},
            {"tool": APPS_SMOKE_TOOL, "arguments": dict(project_args)},
            {"tool": READINESS_TOOL, "arguments": dict(project_args)},
        ],
        "safe_next_action": {
            "action": "run_chatgpt_apps_connector_smoke",
            "tool": APPS_SMOKE_TOOL,
            "arguments": dict(project_args),
            "why": "Connector smoke evidence must be observed through the external ChatGPT Apps connector.",
        },
        "product_readiness": readiness,
        "authority_boundary": _authority_boundary(),
    }


def _primary_blocker(checks: dict[str, Any]) -> dict[str, Any] | None:
    priority = (
        "project_root",
        "expected_head",
        "candidate_head",
        "origin_main",
        "stable_runtime",
        "stable_service",
        "local_stable_health",
        "remote_https_mcp_preflight",
        "cloudflared_service",
        "connector_smoke",
        "secret_redaction",
    )
    for status in (BLOCKED, NEEDS_ATTENTION):
        for name in priority:
            check = checks.get(name)
            if isinstance(check, dict) and check.get("status") == status:
                return _blocker_summary(name, check)
        for name, check in checks.items():
            if isinstance(check, dict) and check.get("status") == status:
                return _blocker_summary(str(name), check)
    return None


def _blocker_summary(name: str, check: dict[str, Any]) -> dict[str, Any]:
    summary = _check_summary(check)
    summary["check"] = name
    return summary


def _check_summary(check: Any) -> dict[str, Any]:
    if not isinstance(check, dict):
        return {"status": "unknown", "reason_codes": []}
    summary = {
        "status": str(check.get("status") or "unknown"),
        "reason_codes": [str(code) for code in check.get("reason_codes", []) if isinstance(code, str)],
    }
    hint = check.get("operator_hint")
    if isinstance(hint, dict):
        summary["operator_hint"] = {
            key: hint[key]
            for key in ("action", "runbook", "summary")
            if isinstance(hint.get(key), str) and hint.get(key)
        }
    return summary


def _product_status(ops_packet: dict[str, Any]) -> str:
    status = ops_packet.get("status")
    if status in {READY, NEEDS_ATTENTION, BLOCKED}:
        return str(status)
    if ops_packet.get("beta_gate_ready") is True:
        return READY
    if ops_packet.get("blocker_codes"):
        return BLOCKED
    return NEEDS_ATTENTION


def _product_summary(status: str, ops_packet: dict[str, Any]) -> str:
    if status == READY:
        return "Public beta product readiness is ready for the ChatGPT App connector."
    if status == BLOCKED:
        return "Public beta product readiness is blocked; fix the primary blocker before connector closeout."
    if ops_packet.get("connector_smoke_ready") is not True:
        return "Public beta product readiness needs external ChatGPT Apps connector smoke evidence."
    return "Public beta product readiness needs operator attention before closeout."


def _safe_next_action(
    status: str,
    primary_blocker: dict[str, Any] | None,
    stable_delivery_decision: dict[str, Any],
    project_args: dict[str, Any],
) -> dict[str, Any]:
    if status == READY:
        return {
            "action": "continue_with_public_beta_workflow",
            "tool": COMMANDER_RENDER_TOOL,
            "arguments": dict(project_args),
            "why": "Readiness is green; open the Commander App entry surface.",
        }
    if primary_blocker and primary_blocker.get("check") == "connector_smoke":
        return {
            "action": "run_chatgpt_apps_connector_smoke",
            "tool": APPS_SMOKE_TOOL,
            "arguments": dict(project_args),
            "why": "External connector smoke is the remaining product closeout evidence.",
        }
    hint = primary_blocker.get("operator_hint") if isinstance(primary_blocker, dict) else None
    runbook = hint.get("runbook") if isinstance(hint, dict) else None
    if isinstance(runbook, str) and runbook:
        return {
            "action": "follow_runbook",
            "runbook": runbook,
            "why": "The primary blocker includes a bounded operator runbook.",
        }
    decision_action = stable_delivery_decision.get("safe_next_action")
    if (
        primary_blocker
        and primary_blocker.get("check")
        in {"stable_runtime", "local_stable_health", "remote_https_mcp_preflight"}
        and stable_delivery_decision.get("status")
        in {"promotion_review_required", "runtime_reload_review_required", "preflight_required"}
        and isinstance(decision_action, dict)
    ):
        action = dict(decision_action)
        action["arguments"] = {**project_args, **dict(action.get("arguments") or {})}
        return action
    if primary_blocker and primary_blocker.get("check") in {"stable_runtime", "local_stable_health"}:
        return {
            "action": "inspect_stable_replacement_cadence",
            "tool": STABLE_REPLACEMENT_CADENCE_TOOL,
            "arguments": dict(project_args),
            "why": (
                "Stable runtime evidence is blocking product readiness; inspect the read-only "
                "cadence packet before deciding whether any stable replacement should be requested."
            ),
        }
    return {
        "action": "inspect_product_readiness",
        "tool": READINESS_TOOL,
        "arguments": dict(project_args),
        "why": "Read the readiness packet and fix the primary blocker.",
    }


def _stable_delivery_decision(
    *,
    project_root: str,
    project_name: str | None,
    ops_packet: dict[str, Any],
    checks: dict[str, Any],
    cadence_builder: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    project_args = {"project_name": project_name} if project_name else {}
    candidate_head = _clean_head(ops_packet.get("candidate_head"))
    stable_check = checks.get("stable_runtime") if isinstance(checks.get("stable_runtime"), dict) else {}
    stable_runtime_head = _clean_head(stable_check.get("head"))
    cadence = cadence_builder(
        project_root=os.path.abspath(os.path.expanduser(project_root)),
        candidate_head=candidate_head,
        stable_runtime_dir=ops_packet.get("stable_runtime_dir"),
        stable_runtime_head=stable_runtime_head,
    )
    remote_check = (
        checks.get("remote_https_mcp_preflight")
        if isinstance(checks.get("remote_https_mcp_preflight"), dict)
        else {}
    )
    healthz_runtime = (
        remote_check.get("healthz_runtime")
        if isinstance(remote_check.get("healthz_runtime"), dict)
        else {}
    )
    public_loaded_head = _clean_head(healthz_runtime.get("loaded_runtime_head"))
    expected_public_head = _clean_head(remote_check.get("expected_runtime_head")) or candidate_head
    public_endpoint_stale = bool(
        expected_public_head and public_loaded_head and public_loaded_head != expected_public_head
    )
    public_endpoint_proven_current = bool(
        expected_public_head and public_loaded_head and public_loaded_head == expected_public_head
    ) or remote_check.get("status") == READY
    heads_differ = bool(
        candidate_head and stable_runtime_head and candidate_head != stable_runtime_head
    )
    cadence_deferred = (
        cadence.get("stable_replacement_not_required") is True
        and cadence.get("recommended_cadence") == "batch_when_ready"
    )

    if public_endpoint_stale and heads_differ:
        decision_status = "promotion_review_required"
        reason_codes = ["PUBLIC_ENDPOINT_SERVES_STALE_RUNTIME", "STABLE_DELIVERY_REVIEW_REQUIRED"]
        summary = (
            "The public MCP endpoint is serving a runtime other than the candidate; "
            "stable promotion review is required before public-beta delivery can be claimed."
        )
        safe_next_action = {
            "action": "inspect_stable_promotion_readiness",
            "tool": STABLE_PROMOTION_READINESS_TOOL,
            "arguments": dict(project_args),
            "why": (
                "Public runtime provenance is stale; inspect exact-head promotion evidence and local blockers "
                "before requesting any stable replacement authorization."
            ),
        }
    elif public_endpoint_stale:
        decision_status = "runtime_reload_review_required"
        reason_codes = ["PUBLIC_ENDPOINT_SERVES_STALE_RUNTIME", "PUBLIC_RUNTIME_RELOAD_REVIEW_REQUIRED"]
        summary = (
            "Stable checkout is aligned, but the public MCP endpoint is serving a different runtime; "
            "runtime reload evidence must be reviewed before delivery can be claimed."
        )
        safe_next_action = {
            "action": "inspect_runtime_version_status",
            "tool": RUNTIME_VERSION_STATUS_TOOL,
            "arguments": dict(project_args),
            "why": (
                "The checkout is aligned while the public process is stale; inspect runtime provenance before "
                "requesting any restart or reload."
            ),
        }
    elif heads_differ and cadence_deferred and public_endpoint_proven_current:
        decision_status = "deferred_batch"
        reason_codes = ["ORDINARY_DEV_STABLE_DRIFT_DEFERRED"]
        summary = "Development is ahead of stable, but no user-facing stale-runtime evidence requires promotion now."
        safe_next_action = {
            "action": "inspect_stable_replacement_cadence",
            "tool": STABLE_REPLACEMENT_CADENCE_TOOL,
            "arguments": dict(project_args),
            "why": "Continue the development batch until a promotion trigger is present.",
        }
    elif heads_differ:
        decision_status = "preflight_required"
        reason_codes = ["PUBLIC_ENDPOINT_RUNTIME_UNVERIFIED", "STABLE_DELIVERY_PROVENANCE_INCOMPLETE"]
        summary = (
            "Development is ahead of stable, but public endpoint runtime provenance is not verified; "
            "ordinary drift cannot be safely deferred yet."
        )
        operator_hint = remote_check.get("operator_hint") if isinstance(remote_check.get("operator_hint"), dict) else {}
        runbook = operator_hint.get("runbook") if isinstance(operator_hint.get("runbook"), str) else None
        safe_next_action = (
            {
                "action": "follow_public_endpoint_runbook",
                "runbook": runbook,
                "arguments": dict(project_args),
                "why": "Public endpoint provenance must be repaired or verified before stable drift is deferred.",
            }
            if runbook
            else {
                "action": "recheck_product_readiness",
                "tool": READINESS_TOOL,
                "arguments": dict(project_args),
                "why": "Recheck public endpoint provenance after the external runtime or network state changes.",
            }
        )
    elif candidate_head and stable_runtime_head and candidate_head == stable_runtime_head:
        decision_status = "aligned"
        reason_codes = ["STABLE_DELIVERY_ALIGNED"]
        summary = "Stable runtime is aligned with the candidate."
        safe_next_action = {
            "action": "continue_with_public_beta_workflow",
            "tool": COMMANDER_RENDER_TOOL,
            "arguments": dict(project_args),
            "why": "Stable runtime is aligned; continue with the remaining public-beta checks.",
        }
    else:
        decision_status = "preflight_required"
        reason_codes = ["STABLE_DELIVERY_PROVENANCE_INCOMPLETE"]
        summary = "Stable delivery provenance is incomplete; keep delivery blocked and inspect cadence evidence."
        safe_next_action = {
            "action": "inspect_stable_replacement_cadence",
            "tool": STABLE_REPLACEMENT_CADENCE_TOOL,
            "arguments": dict(project_args),
            "why": "Stable and candidate provenance must be known before a delivery decision.",
        }

    return {
        "source": "stable_delivery_decision",
        "schema_version": STABLE_DELIVERY_DECISION_VERSION,
        "read_only": True,
        "side_effects": False,
        "status": decision_status,
        "summary": summary,
        "candidate_head": candidate_head,
        "stable_runtime_head": stable_runtime_head,
        "public_endpoint_loaded_runtime_head": public_loaded_head,
        "public_endpoint_expected_runtime_head": expected_public_head,
        "public_endpoint_stale": public_endpoint_stale,
        "public_endpoint_proven_current": public_endpoint_proven_current,
        "candidate_differs_from_stable": heads_differ,
        "cadence_status": cadence.get("status"),
        "cadence_recommended": cadence.get("recommended_cadence"),
        "cadence_defers_ordinary_drift": cadence_deferred,
        "stable_promotion_review_required": decision_status == "promotion_review_required",
        "stable_replacement_authorized": False,
        "blocks_public_beta_delivery": decision_status
        in {"promotion_review_required", "runtime_reload_review_required", "preflight_required"},
        "reason_codes": reason_codes,
        "safe_next_action": safe_next_action,
        "authority_boundary": {
            "does_not_authorize_stable_replacement": True,
            "does_not_request_stable_replacement": True,
            "does_not_restart_services": True,
            "does_not_mutate_git": True,
            "does_not_release_or_deploy": True,
        },
    }


def _clean_head(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip().lower()
    return cleaned if len(cleaned) in {40, 64} and all(char in "0123456789abcdef" for char in cleaned) else None


def _connector_url(public_base_url: str) -> str:
    parsed = urlparse(public_base_url)
    if not parsed.scheme or not parsed.netloc:
        return public_base_url.rstrip("/") + "/mcp"
    path = parsed.path.rstrip("/")
    if path.endswith("/mcp"):
        return public_base_url.rstrip("/")
    return public_base_url.rstrip("/") + "/mcp"


def _authority_boundary() -> dict[str, bool]:
    return {
        "read_only": True,
        "side_effects": False,
        "does_not_read_tokens_or_cookies": True,
        "does_not_read_browser_login_state": True,
        "does_not_read_provider_config": True,
        "does_not_read_raw_logs": True,
        "does_not_modify_dns_or_tunnel": True,
        "does_not_restart_services": True,
        "does_not_authorize_executor_run": True,
        "does_not_authorize_commit_or_push": True,
        "does_not_authorize_stable_replacement": True,
        "does_not_release_or_deploy": True,
    }


def _not_authorized_actions() -> list[str]:
    return [
        "read_tokens_or_cookies",
        "read_env_values",
        "read_provider_config",
        "read_raw_logs",
        "modify_dns_or_tunnel",
        "restart_service",
        "executor_run",
        "commit_or_push",
        "stable_replacement",
        "release_or_deploy",
    ]


def _iso_now(now: datetime | None) -> str:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
