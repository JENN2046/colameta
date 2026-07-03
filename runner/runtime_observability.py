from __future__ import annotations

import os
import re
import hashlib
import sys
import importlib.metadata
from datetime import datetime, timezone
from typing import Any


PROCESS_START_TIME_ISO = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
LOADED_SOURCE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
LOADED_MODULE_FINGERPRINT_ALGORITHM = "sha256"

_ALL_POSSIBLY_STALE_SURFACES = (
    "MCP tool results",
    "Web Console handlers",
    "executor workflow code paths",
    "runtime observability",
)

_HEX_HEAD_RE = re.compile(r"^[0-9a-fA-F]{7,128}$")


def git_checkout_metadata(project_root: str | None) -> dict[str, Any]:
    root = os.path.abspath(os.path.expanduser(project_root or ""))
    result: dict[str, Any] = {
        "project_root": root if project_root else None,
        "branch": None,
        "head": None,
        "head_available": False,
        "git_dir_available": False,
        "head_source": "unavailable",
    }
    if not project_root or not os.path.isdir(root):
        result["head_source"] = "missing_project_root"
        return result

    git_dir = _resolve_git_dir(root)
    if not git_dir:
        result["head_source"] = "missing_git_dir"
        return result

    result["git_dir_available"] = True
    head_text = _read_text(os.path.join(git_dir, "HEAD"), max_chars=4096)
    if not head_text:
        result["head_source"] = "missing_head"
        return result

    head_line = head_text.splitlines()[0].strip()
    if head_line.startswith("ref:"):
        ref_name = head_line[4:].strip()
        result["branch"] = _branch_from_ref(ref_name)
        ref_head = _read_ref(git_dir, ref_name)
        if ref_head:
            result["head"] = ref_head
            result["head_available"] = True
            result["head_source"] = "git_ref"
        else:
            result["head_source"] = "missing_ref"
        return result

    if _looks_like_head(head_line):
        result["head"] = head_line
        result["head_available"] = True
        result["head_source"] = "detached_head"
    else:
        result["head_source"] = "invalid_head"
    return result


def get_runtime_version_status(
    project_root: str | None,
    *,
    loaded_runtime_head: str | None = None,
    loaded_runtime_branch: str | None = None,
    process_start_time_iso: str | None = None,
    loaded_module_fingerprints: dict[str, dict[str, Any]] | None = None,
    local_service: dict[str, Any] | None = None,
) -> dict[str, Any]:
    loaded_head = _clean_head(loaded_runtime_head if loaded_runtime_head is not None else LOADED_RUNTIME_HEAD)
    project = git_checkout_metadata(project_root)
    project_head = _clean_head(project.get("head"))
    restart_needed, reason = _restart_needed(loaded_head, project_head)
    module_verification = verify_loaded_module_sources(loaded_module_fingerprints)
    installed_package_verification = verify_installed_package_against_project(project_root)
    reload_awareness = _reload_awareness(
        loaded_head,
        project_head,
        module_verification,
        installed_package_verification,
    )

    status = {
        "ok": True,
        "source": "runtime_version_observability",
        "scope": "mcp:read",
        "read_only": True,
        "side_effects": False,
        "process_start_time_iso": process_start_time_iso or PROCESS_START_TIME_ISO,
        "loaded_runtime": {
            "source_root": LOADED_SOURCE_ROOT,
            "head": loaded_head,
            "head_available": bool(loaded_head),
            "branch": loaded_runtime_branch if loaded_runtime_branch is not None else LOADED_RUNTIME_BRANCH,
            "head_source": LOADED_RUNTIME_HEAD_SOURCE,
            "captured_at_process_start": True,
        },
        "loaded_runtime_head": loaded_head,
        "project_checkout": {
            "project_root": project.get("project_root"),
            "head": project_head,
            "head_available": bool(project_head),
            "branch": project.get("branch"),
            "git_dir_available": bool(project.get("git_dir_available")),
            "head_source": project.get("head_source"),
        },
        "project_checkout_head": project_head,
        "restart_needed": restart_needed,
        "restart_needed_state": "unknown" if restart_needed is None else ("needed" if restart_needed else "not_needed"),
        "restart_needed_reason": reason,
        "runtime_loaded_code_stale": reload_awareness["runtime_loaded_code_stale"],
        "reload_needed_for_verification": reload_awareness["reload_needed_for_verification"],
        "reload_awareness_reason": reload_awareness["reload_awareness_reason"],
        "loaded_module_source_changed": module_verification["loaded_module_source_changed"],
        "changed_loaded_modules": module_verification["changed_loaded_modules"],
        "possibly_stale_surfaces": reload_awareness["possibly_stale_surfaces"],
        "loaded_module_verification": module_verification,
        "installed_package_verification": installed_package_verification,
    }
    status["connector_runtime_health"] = get_connector_runtime_health_status(
        runtime_status=status,
        local_service=local_service,
    )
    return status


def get_connector_runtime_health_status(
    *,
    runtime_status: dict[str, Any] | None = None,
    local_service: dict[str, Any] | None = None,
    tunnel_client: dict[str, Any] | None = None,
    control_plane: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a read-only local-vs-external connector health card.

    The helper only summarizes evidence handed to it by safe status surfaces.
    It does not inspect tunnel-client config, proxy config, credentials, logs,
    provider state, or private memory.
    """
    runtime = _runtime_health_summary(runtime_status)
    service = _local_service_health_summary(local_service)
    tunnel_client = _sanitize_external_component_input(tunnel_client)
    control_plane = _sanitize_external_component_input(control_plane)
    tunnel = _external_component_summary(
        tunnel_client,
        component="tunnel_client",
        unknown_reason_code="CONNECTOR_HEALTH_UNVERIFIED",
    )
    plane = _external_component_summary(
        control_plane,
        component="tunnel_control_plane",
        unknown_reason_code="TUNNEL_CONTROL_PLANE_UNVERIFIED",
    )
    external_status = _external_connector_status(tunnel, plane)
    reason_codes = _unique_reason_codes(
        runtime.get("reason_codes"),
        service.get("reason_codes"),
        tunnel.get("reason_codes"),
        plane.get("reason_codes"),
    )
    evidence_gaps = _connector_evidence_gaps(runtime, service, tunnel, plane)

    return {
        "ok": True,
        "source": "connector_runtime_health_observability",
        "scope": "mcp:read",
        "read_only": True,
        "side_effects": False,
        "overall_status": _connector_overall_status(runtime, service, tunnel, plane),
        "reason_codes": reason_codes,
        "runtime": runtime,
        "local_service": service,
        "external_connector": {
            "status": external_status,
            "tunnel_client": tunnel,
            "control_plane": plane,
        },
        "evidence_gaps": evidence_gaps,
        "operator_closeout": _connector_operator_closeout(
            runtime,
            service,
            external_status=external_status,
            evidence_gaps=evidence_gaps,
        ),
        "safety_boundary": {
            "does_not_read_tunnel_client_config": True,
            "does_not_read_proxy_config": True,
            "does_not_read_provider_auth": True,
            "does_not_read_tokens_or_cookies": True,
            "does_not_read_private_memory": True,
            "does_not_probe_paid_provider_api": True,
            "does_not_modify_service_state": True,
            "does_not_modify_network_or_proxy_state": True,
        },
    }


def build_service_readiness_summary(
    *,
    runtime_status: dict[str, Any] | None = None,
    connector_health: dict[str, Any] | None = None,
    project_name: str | None = None,
) -> dict[str, Any]:
    """Collapse service facts into one read-only Commander-facing status."""
    connector = connector_health if isinstance(connector_health, dict) else {}
    runtime = connector.get("runtime")
    if not isinstance(runtime, dict):
        runtime = _runtime_health_summary(runtime_status)
    local_service = connector.get("local_service")
    if not isinstance(local_service, dict):
        local_service = {"status": "unverified", "reason_code": "LOCAL_SERVICE_HEALTH_UNVERIFIED"}
    external_connector = connector.get("external_connector")
    if not isinstance(external_connector, dict):
        external_connector = {"status": "unverified", "reason_code": "CONNECTOR_HEALTH_UNVERIFIED"}
    operator_closeout = connector.get("operator_closeout")
    if not isinstance(operator_closeout, dict):
        operator_closeout = {}

    status = _service_readiness_status(operator_closeout)
    reason_codes = _unique_reason_codes(
        runtime.get("reason_codes"),
        local_service.get("reason_codes"),
        external_connector.get("reason_codes"),
        connector.get("reason_codes"),
        operator_closeout.get("status"),
    )
    project_arg = _clean_status_text(project_name) or "<registered project_name>"
    safe_next_actions = _service_readiness_next_actions(
        status=status,
        operator_closeout=operator_closeout,
        project_name=project_arg,
    )

    return {
        "ok": True,
        "source": "service_readiness_summary",
        "scope": "mcp:read",
        "read_only": True,
        "side_effects": False,
        "status": status,
        "decision": status,
        "summary": _service_readiness_summary_text(status, operator_closeout),
        "reason_codes": reason_codes,
        "primary_blocker": _service_readiness_primary_blocker(status, operator_closeout),
        "components": {
            "local_service": {
                "status": local_service.get("status"),
                "reason_code": local_service.get("reason_code"),
            },
            "runtime": {
                "status": runtime.get("status"),
                "reason_code": runtime.get("reason_code"),
            },
            "external_connector": {
                "status": external_connector.get("status"),
                "reason_code": external_connector.get("reason_code"),
            },
            "operator_closeout": {
                "status": operator_closeout.get("status"),
                "decision": operator_closeout.get("decision"),
                "evidence_gap_count": operator_closeout.get("evidence_gap_count"),
            },
        },
        "safe_next_actions": safe_next_actions,
        "not_authorized_actions": [
            "read_tokens_or_cookies",
            "read_tunnel_client_config",
            "read_proxy_config",
            "read_provider_auth",
            "modify_network_or_proxy_state",
            "restart_or_replace_stable_service",
            "executor_run",
            "commit",
            "push",
            "delivery_state_acceptance",
            "review_decision",
            "gate_event",
        ],
    }


def build_apps_connector_closeout_packet(
    *,
    project_name: str | None = None,
    connector_health: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a read-only ChatGPT Apps connector closeout checklist.

    Local ColaMeta cannot prove ChatGPT's Apps session token by itself. The
    packet therefore describes the exact read-only Apps-side smoke sequence and
    collapses the local connector closeout that the sequence should verify.
    """
    connector = connector_health if isinstance(connector_health, dict) else {}
    operator_closeout = connector.get("operator_closeout")
    if not isinstance(operator_closeout, dict):
        operator_closeout = {}
    local_service = connector.get("local_service")
    if not isinstance(local_service, dict):
        local_service = {}
    external_connector = connector.get("external_connector")
    if not isinstance(external_connector, dict):
        external_connector = {}

    project_arg = _clean_status_text(project_name) or "<registered project_name>"
    closeout_status = _clean_status_text(operator_closeout.get("status")) or "unverified"
    closeout_decision = _clean_status_text(operator_closeout.get("decision")) or "blocked"
    evidence_gap_count_raw = operator_closeout.get("evidence_gap_count")
    evidence_gap_count = evidence_gap_count_raw if isinstance(evidence_gap_count_raw, int) else None
    connector_ready = closeout_status == "connector_closeout_ready" and closeout_decision == "ready"
    packet_status = "ready" if connector_ready else "needs_attention"

    sanitized_evidence_template = {
        "tunnel_client": {
            "status": "healthy",
            "reason_code": "TUNNEL_CLIENT_HEALTHZ_READY",
            "evidence_source": "tunnel-client health --port <admin_port> --pid <pid> --json healthz_ok",
            "last_observed_at": "<observed_at_iso8601>",
        },
        "control_plane": {
            "status": "healthy",
            "reason_code": "TUNNEL_CONTROL_PLANE_READYZ_READY",
            "evidence_source": "tunnel-client health --port <admin_port> --pid <pid> --json readyz_ok",
            "last_observed_at": "<observed_at_iso8601>",
        },
    }
    closeout_arguments: dict[str, Any] = {
        "project_name": project_arg,
        **sanitized_evidence_template,
    }
    preferred_smoke_tool = {
        "tool": "get_apps_connector_smoke_packet",
        "arguments": closeout_arguments,
        "fallback_tool": "get_connector_runtime_health_status",
        "fallback_arguments": closeout_arguments,
        "success_evidence": (
            "ok=true, apps_connector_closeout.status=ready, "
            "stable_replacement_hint.status=stable_aligned or stable_replacement_available."
        ),
    }
    metadata_refresh_guidance = {
        "status": "refresh_if_tool_missing",
        "expected_tool": "get_apps_connector_smoke_packet",
        "symptom": "Current ChatGPT Apps tool metadata does not list get_apps_connector_smoke_packet.",
        "safe_next_actions": [
            "Open a new ChatGPT/Codex window or reconnect the ColaMeta Apps connector.",
            "Call list_registered_projects to prove the connector session is live.",
            "Use get_connector_runtime_health_status as the fallback until metadata refresh exposes the smoke tool.",
        ],
        "not_authorized_actions": [
            "read_tokens_or_cookies",
            "read_browser_login_state",
            "modify_proxy_or_auth_config",
            "restart_tunnel_client",
        ],
    }

    return {
        "ok": True,
        "source": "apps_connector_closeout_packet",
        "scope": "mcp:read",
        "read_only": True,
        "side_effects": False,
        "status": packet_status,
        "summary": (
            "Apps connector smoke is ready to run; local connector closeout is ready."
            if connector_ready
            else "Apps connector smoke needs sanitized connector evidence before closeout."
        ),
        "project_name": project_arg,
        "preferred_smoke_tool": preferred_smoke_tool,
        "metadata_refresh_guidance": metadata_refresh_guidance,
        "apps_connector_reachability": {
            "status": "proved_by_successful_apps_tool_call",
            "local_service_can_verify_chatgpt_session": False,
            "success_evidence": "The Apps connector tool call returns ok=true instead of token_expired.",
            "token_expired_code": "token_expired",
        },
        "project_list_check": {
            "tool": "list_registered_projects",
            "arguments": {},
            "expected_project_name": project_arg,
            "success_evidence": "ok=true and the returned projects include the expected project_name.",
        },
        "connector_closeout_check": {
            "tool": "get_connector_runtime_health_status",
            "arguments": closeout_arguments,
            "expected_overall_status": "healthy",
            "expected_operator_closeout": "connector_closeout_ready",
            "expected_decision": "ready",
            "current_operator_closeout": closeout_status,
            "current_decision": closeout_decision,
            "current_evidence_gap_count": evidence_gap_count,
            "local_service_status": local_service.get("status"),
            "external_connector_status": external_connector.get("status"),
        },
        "smoke_sequence": [
            {
                "step_id": "apps_connector_reachable",
                "tool": "list_registered_projects",
                "arguments": {},
                "success_evidence": "Tool returns ok=true through the ChatGPT Apps connector.",
            },
            {
                "step_id": "project_list_ok",
                "tool": "list_registered_projects",
                "arguments": {},
                "success_evidence": f"Returned project list includes {project_arg}.",
            },
            {
                "step_id": "connector_closeout_ready",
                "tool": "get_connector_runtime_health_status",
                "arguments": closeout_arguments,
                "success_evidence": "overall_status=healthy, operator_closeout=connector_closeout_ready, evidence_gap_count=0.",
            },
        ],
        "next_action": {
            "action_id": "continue_with_requested_work" if connector_ready else "rerun_connector_closeout_with_sanitized_evidence",
            "label": (
                "Continue with the requested workflow."
                if connector_ready
                else "Run Apps connector closeout with sanitized tunnel/control-plane evidence."
            ),
            "authority": "read_only_or_preview_first",
        },
        "token_expired_recovery": {
            "status": "operator_handoff",
            "summary": "If Apps connector returns HTTP 401 token_expired, reconnect the ChatGPT Apps connector session.",
            "not_local_service_fix": True,
            "not_authorized_actions": [
                "read_tokens_or_cookies",
                "read_browser_login_state",
                "restart_tunnel_client",
                "modify_proxy_or_auth_config",
            ],
        },
        "sanitized_evidence_template": sanitized_evidence_template,
        "forbidden_evidence": [
            "token",
            "cookie",
            "credential",
            "raw_log",
            "provider_raw_response",
            "browser_login_state",
        ],
    }


def loaded_runner_module_fingerprints() -> dict[str, dict[str, Any]]:
    return {module_name: dict(evidence) for module_name, evidence in _LOADED_RUNNER_MODULE_FINGERPRINTS.items()}


def verify_loaded_module_sources(
    loaded_module_fingerprints: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    loaded_modules = _normalize_loaded_module_fingerprints(
        loaded_module_fingerprints if loaded_module_fingerprints is not None else _LOADED_RUNNER_MODULE_FINGERPRINTS
    )
    checked_modules: list[dict[str, Any]] = []
    changed_modules: list[dict[str, Any]] = []
    unverified_modules: list[dict[str, Any]] = []

    for module_name, loaded in sorted(loaded_modules.items()):
        source_path = _clean_source_path(loaded.get("source_path"))
        surfaces = _clean_surfaces(loaded.get("surfaces")) or _surfaces_for_module(module_name)
        current = _fingerprint_source_file(source_path) if source_path else _unavailable_fingerprint("missing_source_path")
        loaded_sha = _clean_sha256(loaded.get("sha256"))
        current_sha = _clean_sha256(current.get("sha256"))
        loaded_available = bool(loaded.get("fingerprint_available")) and bool(loaded_sha)
        current_available = bool(current.get("fingerprint_available")) and bool(current_sha)

        status = "verified"
        reason = "fingerprints_match"
        if not loaded_available:
            status = "unverified"
            reason = "missing_loaded_fingerprint"
        elif not current_available:
            status = "unverified"
            reason = "missing_current_source_fingerprint"
        elif loaded_sha != current_sha:
            status = "changed"
            reason = "sha256_mismatch"

        module_result = {
            "module_name": module_name,
            "source_path": source_path,
            "relative_path": loaded.get("relative_path"),
            "surfaces": surfaces,
            "verification_status": status,
            "verification_reason": reason,
            "loaded_sha256": loaded_sha,
            "current_sha256": current_sha,
            "loaded_size_bytes": loaded.get("size_bytes"),
            "current_size_bytes": current.get("size_bytes"),
            "loaded_mtime_ns": loaded.get("mtime_ns"),
            "current_mtime_ns": current.get("mtime_ns"),
            "captured_at_process_start": bool(loaded.get("captured_at_process_start")),
        }
        checked_modules.append(module_result)
        if status == "changed":
            changed_modules.append(module_result)
        elif status == "unverified":
            unverified_modules.append(module_result)

    if changed_modules:
        loaded_module_source_changed: bool | None = True
    elif unverified_modules or not loaded_modules:
        loaded_module_source_changed = None
    else:
        loaded_module_source_changed = False

    return {
        "source": "process_import_time_loaded_runner_module_fingerprints",
        "fingerprint_algorithm": LOADED_MODULE_FINGERPRINT_ALGORITHM,
        "captured_module_count": len(loaded_modules),
        "checked_module_count": len(checked_modules),
        "verified_module_count": len([item for item in checked_modules if item["verification_status"] == "verified"]),
        "changed_module_count": len(changed_modules),
        "unverified_module_count": len(unverified_modules),
        "module_fingerprint_verification_complete": bool(loaded_modules) and not unverified_modules,
        "loaded_module_source_changed": loaded_module_source_changed,
        "changed_loaded_modules": changed_modules,
        "unverified_loaded_modules": unverified_modules,
        "checked_loaded_modules": checked_modules,
        "worktree_cleanliness_claimed": False,
        "worktree_cleanliness_limitation": (
            "This check compares loaded runtime HEAD and import-time fingerprints for loaded runner modules only. "
            "It does not claim full Git worktree cleanliness."
        ),
    }


def _restart_needed(loaded_head: str | None, project_head: str | None) -> tuple[bool | None, str]:
    if not loaded_head:
        return None, "unknown_loaded_runtime_head"
    if not project_head:
        return None, "unknown_project_checkout_head"
    if loaded_head == project_head:
        return False, "heads_match"
    return True, "loaded_runtime_head_differs_from_project_checkout_head"


def _reload_awareness(
    loaded_head: str | None,
    project_head: str | None,
    module_verification: dict[str, Any],
    installed_package_verification: dict[str, Any] | None = None,
) -> dict[str, Any]:
    changed_modules = module_verification.get("changed_loaded_modules")
    unverified_modules = module_verification.get("unverified_loaded_modules")
    module_changed = module_verification.get("loaded_module_source_changed") is True
    module_verification_complete = module_verification.get("module_fingerprint_verification_complete") is True
    package_matches_project = (
        isinstance(installed_package_verification, dict)
        and installed_package_verification.get("matches_project_checkout") is True
    )

    if module_changed:
        reason = "loaded_module_source_changed"
        stale: bool | None = True
        reload_needed = True
        surfaces = _surfaces_from_modules(changed_modules)
    elif loaded_head and project_head and loaded_head != project_head:
        reason = "loaded_head_differs_from_project_head"
        stale = True
        reload_needed = True
        surfaces = list(_ALL_POSSIBLY_STALE_SURFACES)
    elif project_head and package_matches_project and module_verification_complete:
        reason = "installed_package_matches_project_checkout"
        stale = False
        reload_needed = False
        surfaces = []
    elif project_head and package_matches_project:
        reason = "loaded_module_fingerprint_unknown"
        stale = None
        reload_needed = True
        surfaces = _surfaces_from_modules(unverified_modules) or list(_ALL_POSSIBLY_STALE_SURFACES)
    elif not loaded_head or not project_head:
        reason = "unknown_runtime_or_checkout_head"
        stale = None
        reload_needed = True
        surfaces = list(_ALL_POSSIBLY_STALE_SURFACES)
    elif not module_verification.get("module_fingerprint_verification_complete"):
        reason = "loaded_module_fingerprint_unknown"
        stale = None
        reload_needed = True
        surfaces = _surfaces_from_modules(unverified_modules) or list(_ALL_POSSIBLY_STALE_SURFACES)
    else:
        reason = "loaded_code_verified_current"
        stale = False
        reload_needed = False
        surfaces = []

    return {
        "runtime_loaded_code_stale": stale,
        "reload_needed_for_verification": reload_needed,
        "reload_awareness_reason": reason,
        "possibly_stale_surfaces": surfaces,
    }


def _runtime_health_summary(runtime_status: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(runtime_status, dict):
        return {
            "status": "unverified",
            "reason_code": "RUNTIME_HEALTH_UNVERIFIED",
            "reason_codes": ["RUNTIME_HEALTH_UNVERIFIED"],
            "reload_needed_for_verification": None,
            "runtime_loaded_code_stale": None,
            "reload_awareness_reason": None,
        }

    stale = runtime_status.get("runtime_loaded_code_stale")
    reload_needed = runtime_status.get("reload_needed_for_verification")
    if stale is False and reload_needed is False:
        status = "healthy"
        reason_code = "RUNTIME_LOADED_CODE_CURRENT"
    elif stale is True:
        status = "stale"
        reason_code = "RUNTIME_LOADED_CODE_STALE"
    elif reload_needed is True:
        status = "unverified"
        reason_code = "RUNTIME_RELOAD_NEEDED_FOR_VERIFICATION"
    else:
        status = "unverified"
        reason_code = "RUNTIME_HEALTH_UNVERIFIED"

    loaded_runtime = runtime_status.get("loaded_runtime")
    project_checkout = runtime_status.get("project_checkout")
    return {
        "status": status,
        "reason_code": reason_code,
        "reason_codes": [reason_code],
        "reload_needed_for_verification": reload_needed if isinstance(reload_needed, bool) else None,
        "runtime_loaded_code_stale": stale if isinstance(stale, bool) else None,
        "reload_awareness_reason": _clean_status_text(runtime_status.get("reload_awareness_reason")),
        "loaded_source_root": (
            _clean_status_text(loaded_runtime.get("source_root")) if isinstance(loaded_runtime, dict) else None
        ),
        "project_root": (
            _clean_status_text(project_checkout.get("project_root")) if isinstance(project_checkout, dict) else None
        ),
    }


def _local_service_health_summary(local_service: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(local_service, dict):
        return {
            "status": "unverified",
            "reason_code": "LOCAL_SERVICE_HEALTH_UNVERIFIED",
            "reason_codes": ["LOCAL_SERVICE_HEALTH_UNVERIFIED"],
            "pid": None,
            "state": "unknown",
            "health_source": "unavailable",
            "discovered_from_process_table": None,
            "web": _endpoint_summary(None, "web"),
            "mcp": _endpoint_summary(None, "mcp"),
        }

    state = _clean_status_text(local_service.get("state")) or "unknown"
    source = _clean_status_text(local_service.get("health_source"))
    if source is None:
        source = "process_table" if local_service.get("discovered_from_process_table") is True else "metadata"
    web = _endpoint_summary(local_service, "web")
    mcp = _endpoint_summary(local_service, "mcp")

    if state == "stopped":
        status = "unavailable"
        reason_code = "LOCAL_SERVICE_UNAVAILABLE"
    elif state == "stale":
        status = "stale"
        reason_code = "LOCAL_SERVICE_STALE"
    elif state == "running" and _endpoint_ready(web) and _endpoint_ready(mcp):
        status = "healthy"
        reason_code = "LOCAL_SERVICE_HEALTHY"
    elif state == "running":
        status = "degraded"
        reason_code = "LOCAL_SERVICE_DEGRADED"
    else:
        status = "unverified"
        reason_code = "LOCAL_SERVICE_HEALTH_UNVERIFIED"

    reason_codes = [reason_code]
    for endpoint in (web, mcp):
        endpoint_code = endpoint.get("reason_code")
        if isinstance(endpoint_code, str):
            reason_codes.append(endpoint_code)

    return {
        "status": status,
        "reason_code": reason_code,
        "reason_codes": _unique_reason_codes(reason_codes),
        "pid": _clean_positive_int(local_service.get("pid")),
        "state": state,
        "health_source": source,
        "metadata_project_matches": (
            local_service.get("metadata_project_matches")
            if isinstance(local_service.get("metadata_project_matches"), bool)
            else None
        ),
        "discovered_from_process_table": (
            local_service.get("discovered_from_process_table")
            if isinstance(local_service.get("discovered_from_process_table"), bool)
            else None
        ),
        "project_root": _clean_status_text(local_service.get("project_root")),
        "web": web,
        "mcp": mcp,
    }


def _endpoint_summary(local_service: dict[str, Any] | None, endpoint: str) -> dict[str, Any]:
    nested = local_service.get(endpoint) if isinstance(local_service, dict) else None
    if isinstance(nested, dict):
        enabled_raw = nested.get("enabled")
        state_raw = nested.get("state")
        url_raw = nested.get("url")
        host_raw = nested.get("host")
        port_raw = nested.get("port")
    elif isinstance(local_service, dict):
        enabled_raw = local_service.get(f"enable_{endpoint}")
        state_raw = local_service.get(f"{endpoint}_state")
        url_raw = local_service.get(f"{endpoint}_url")
        host_raw = local_service.get(f"{endpoint}_host")
        port_raw = local_service.get(f"{endpoint}_port")
    else:
        enabled_raw = state_raw = url_raw = host_raw = port_raw = None

    enabled = enabled_raw if isinstance(enabled_raw, bool) else None
    state = _clean_status_text(state_raw) or ("disabled" if enabled is False else "unknown")
    if enabled is False:
        status = "disabled"
        reason_code = f"{endpoint.upper()}_ENDPOINT_DISABLED"
    elif state == "healthy":
        status = "healthy"
        reason_code = f"{endpoint.upper()}_ENDPOINT_HEALTHY"
    elif state in {"starting", "degraded", "unhealthy"}:
        status = "degraded"
        reason_code = f"{endpoint.upper()}_ENDPOINT_DEGRADED"
    else:
        status = "unverified"
        reason_code = f"{endpoint.upper()}_ENDPOINT_UNVERIFIED"

    return {
        "status": status,
        "reason_code": reason_code,
        "enabled": enabled,
        "state": state,
        "url": _clean_local_service_url(url_raw),
        "host": _clean_status_text(host_raw),
        "port": _clean_positive_int(port_raw),
    }


def _external_component_summary(
    component_status: dict[str, Any] | None,
    *,
    component: str,
    unknown_reason_code: str,
) -> dict[str, Any]:
    if not isinstance(component_status, dict):
        return {
            "component": component,
            "status": "unverified",
            "reason_code": unknown_reason_code,
            "reason_codes": [unknown_reason_code],
            "evidence_source": "not_collected",
        }

    raw_status = _clean_status_text(component_status.get("status")) or "unverified"
    if raw_status in {"healthy", "ready", "running", "ok"}:
        status = "healthy"
        reason_code = _clean_reason_code(component_status.get("reason_code")) or f"{component.upper()}_HEALTHY"
    elif raw_status in {"unavailable", "missing", "stopped"}:
        status = "unavailable"
        reason_code = _clean_reason_code(component_status.get("reason_code")) or f"{component.upper()}_UNAVAILABLE"
    elif raw_status in {"degraded", "failing", "failed"}:
        status = "degraded"
        reason_code = _clean_reason_code(component_status.get("reason_code")) or f"{component.upper()}_DEGRADED"
    else:
        status = "unverified"
        reason_code = _clean_reason_code(component_status.get("reason_code")) or unknown_reason_code

    return {
        "component": component,
        "status": status,
        "reason_code": reason_code,
        "reason_codes": [reason_code],
        "evidence_source": _clean_safe_evidence_text(component_status.get("evidence_source")) or "provided_status",
        "last_observed_at": _clean_safe_evidence_text(component_status.get("last_observed_at")),
    }


def _sanitize_external_component_input(component_status: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(component_status, dict):
        return None
    return {
        "status": _clean_status_text(component_status.get("status")),
        "reason_code": _clean_reason_code(component_status.get("reason_code")),
        "evidence_source": _clean_safe_evidence_text(component_status.get("evidence_source")),
        "last_observed_at": _clean_safe_evidence_text(component_status.get("last_observed_at")),
    }


def _connector_overall_status(
    runtime: dict[str, Any],
    service: dict[str, Any],
    tunnel: dict[str, Any],
    control_plane: dict[str, Any],
) -> str:
    local_status = service.get("status")
    runtime_status = runtime.get("status")
    external_status = _external_connector_status(tunnel, control_plane)
    if local_status == "healthy" and runtime_status == "healthy" and external_status == "healthy":
        return "healthy"
    if local_status in {"degraded", "stale", "unavailable"} or runtime_status in {"stale", "degraded"}:
        return "local_or_runtime_attention_needed"
    if external_status == "degraded":
        return "local_runtime_observed_external_connector_degraded"
    if external_status == "unverified":
        return "local_runtime_observed_external_connector_unverified"
    return "health_unverified"


def _external_connector_status(tunnel: dict[str, Any], control_plane: dict[str, Any]) -> str:
    statuses = {tunnel.get("status"), control_plane.get("status")}
    if "degraded" in statuses or "unavailable" in statuses:
        return "degraded"
    if statuses == {"healthy"}:
        return "healthy"
    return "unverified"


def _connector_evidence_gaps(
    runtime: dict[str, Any],
    service: dict[str, Any],
    tunnel: dict[str, Any],
    control_plane: dict[str, Any],
) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    if runtime.get("status") == "unverified":
        gaps.append(
            _evidence_gap(
                "runtime",
                runtime.get("reason_code"),
                "runtime loaded-code freshness from get_runtime_version_status",
            )
        )
    if service.get("status") == "unverified":
        gaps.append(
            _evidence_gap(
                "local_service",
                service.get("reason_code"),
                "local ColaMeta service metadata or process-table evidence",
            )
        )
    if tunnel.get("status") == "unverified":
        gaps.append(
            _evidence_gap(
                "tunnel_client",
                tunnel.get("reason_code"),
                "sanitized tunnel-client runtime status from an approved status surface, not config, logs, or tokens",
            )
        )
    if control_plane.get("status") == "unverified":
        gaps.append(
            _evidence_gap(
                "tunnel_control_plane",
                control_plane.get("reason_code"),
                "sanitized tunnel control-plane status from an approved status surface, not provider raw responses",
            )
        )
    return gaps


def _evidence_gap(component: str, reason_code: Any, safe_evidence_needed: str) -> dict[str, Any]:
    return {
        "component": component,
        "reason_code": _clean_status_text(reason_code) or "EVIDENCE_UNVERIFIED",
        "safe_evidence_needed": safe_evidence_needed,
    }


def _connector_operator_closeout(
    runtime: dict[str, Any],
    service: dict[str, Any],
    *,
    external_status: str,
    evidence_gaps: list[dict[str, Any]],
) -> dict[str, Any]:
    local_status = service.get("status")
    runtime_status = runtime.get("status")
    if local_status != "healthy":
        status = "local_service_attention_needed"
        decision = "blocked"
        summary = "Local ColaMeta Web/MCP evidence is not healthy enough for connector closeout."
    elif runtime_status == "stale":
        status = "runtime_attention_needed"
        decision = "blocked"
        summary = "Local service is healthy, but loaded runtime evidence is stale."
    elif external_status == "degraded":
        status = "external_connector_attention_needed"
        decision = "blocked"
        summary = "Local service is healthy, but external connector evidence is degraded or unavailable."
    elif runtime_status != "healthy":
        status = "local_service_ready_runtime_unverified"
        decision = "blocked"
        summary = "Local ColaMeta Web/MCP is healthy, but runtime freshness is not verified in this health card."
    elif external_status == "healthy":
        status = "connector_closeout_ready"
        decision = "ready"
        summary = "Local runtime, Web/MCP, and external connector evidence are healthy."
    else:
        status = "local_runtime_ready_external_connector_unverified"
        decision = "blocked"
        summary = "Local runtime and Web/MCP are healthy, but external connector/tunnel evidence is still unverified."

    return {
        "status": status,
        "decision": decision,
        "summary": summary,
        "evidence_gaps": list(evidence_gaps),
        "evidence_gap_count": len(evidence_gaps),
        "safe_next_actions": _connector_safe_next_actions(status),
        "not_authorized_actions": [
            "read_tunnel_client_config",
            "read_proxy_config",
            "read_provider_auth",
            "read_tokens_or_cookies",
            "probe_paid_provider_api",
            "modify_network_or_proxy_state",
            "restart_or_replace_stable_service",
            "route_transition",
            "executor_run",
            "delivery_state_acceptance",
        ],
    }


def _connector_safe_next_actions(closeout_status: str) -> list[str]:
    if closeout_status == "connector_closeout_ready":
        return ["Record connector closeout evidence if the Commander requests it."]
    if closeout_status == "local_service_attention_needed":
        return ["Inspect local ColaMeta Web/MCP status through existing read-only status surfaces."]
    if closeout_status in {"runtime_attention_needed", "local_service_ready_runtime_unverified"}:
        return ["Call get_runtime_version_status with project_name to collect loaded-code freshness evidence."]
    if closeout_status == "external_connector_attention_needed":
        return ["Use an approved external connector status surface and record sanitized degraded-state evidence."]
    return [
        "Use an approved external connector or tunnel status surface to provide sanitized health evidence.",
        "Keep external_connector unverified until tunnel-client and control-plane evidence are both present.",
    ]


def _service_readiness_status(operator_closeout: dict[str, Any]) -> str:
    closeout_status = operator_closeout.get("status")
    if operator_closeout.get("decision") == "ready":
        return "ready"
    if closeout_status == "local_service_attention_needed":
        return "blocked"
    if closeout_status in {
        "runtime_attention_needed",
        "local_service_ready_runtime_unverified",
        "external_connector_attention_needed",
        "local_runtime_ready_external_connector_unverified",
    }:
        return "needs_attention"
    return "blocked"


def _service_readiness_summary_text(status: str, operator_closeout: dict[str, Any]) -> str:
    if status == "ready":
        return "Local runtime, Web/MCP service, and external connector evidence are ready."
    summary = operator_closeout.get("summary")
    if isinstance(summary, str) and summary.strip():
        return summary.strip()
    if status == "needs_attention":
        return "Service is reachable, but readiness evidence still needs attention."
    return "Service readiness is blocked until required local service evidence is healthy."


def _service_readiness_primary_blocker(status: str, operator_closeout: dict[str, Any]) -> dict[str, Any] | None:
    if status == "ready":
        return None
    evidence_gaps = operator_closeout.get("evidence_gaps")
    first_gap = evidence_gaps[0] if isinstance(evidence_gaps, list) and evidence_gaps else None
    if isinstance(first_gap, dict):
        return {
            "component": first_gap.get("component"),
            "reason_code": first_gap.get("reason_code"),
            "safe_evidence_needed": first_gap.get("safe_evidence_needed"),
        }
    closeout_status = operator_closeout.get("status")
    return {
        "component": "operator_closeout",
        "reason_code": closeout_status or "SERVICE_READINESS_BLOCKED",
        "safe_evidence_needed": "Use read-only service status tools to collect the missing readiness evidence.",
    }


def _service_readiness_next_actions(
    *,
    status: str,
    operator_closeout: dict[str, Any],
    project_name: str,
) -> list[dict[str, Any]]:
    if status == "ready":
        return [
            {
                "action_id": "continue_with_requested_work",
                "label": "Continue with the requested low-risk or preview-first workflow.",
                "tool": "run_mcp_workflow",
                "arguments": {"project_name": project_name, "workflow": "thin_governed_loop_preview", "input_mode": "draft"},
                "authority": "preview_or_task_packet_only",
            }
        ]

    closeout_status = operator_closeout.get("status")
    if closeout_status in {"runtime_attention_needed", "local_service_ready_runtime_unverified"}:
        return [
            {
                "action_id": "read_runtime_version",
                "label": "Read runtime freshness evidence.",
                "tool": "get_runtime_version_status",
                "arguments": {"project_name": project_name},
                "authority": "read_only",
            }
        ]
    if closeout_status in {"external_connector_attention_needed", "local_runtime_ready_external_connector_unverified"}:
        return [
            {
                "action_id": "read_connector_health",
                "label": "Read connector health with sanitized tunnel/control-plane evidence when available.",
                "tool": "get_connector_runtime_health_status",
                "arguments": {"project_name": project_name},
                "authority": "read_only",
            }
        ]
    return [
        {
            "action_id": "read_service_entrypoint",
            "label": "Read the Web GPT service entrypoint and local service facts.",
            "tool": "get_web_gpt_service_entrypoint",
            "arguments": {"project_name": project_name},
            "authority": "read_only",
        },
        {
            "action_id": "read_connector_health",
            "label": "Read connector health without reading secrets or raw tunnel config.",
            "tool": "get_connector_runtime_health_status",
            "arguments": {"project_name": project_name},
            "authority": "read_only",
        },
    ]


def _endpoint_ready(endpoint: dict[str, Any]) -> bool:
    return endpoint.get("enabled") is False or endpoint.get("status") == "healthy"


def _unique_reason_codes(*groups: Any) -> list[str]:
    result: list[str] = []
    for group in groups:
        items = group if isinstance(group, list) else [group]
        for item in items:
            if not isinstance(item, str):
                continue
            candidate = item.strip().upper()
            if candidate and candidate not in result:
                result.append(candidate)
    return result


def _clean_positive_int(value: Any) -> int | None:
    try:
        candidate = int(value)
    except (TypeError, ValueError):
        return None
    return candidate if candidate > 0 else None


def _clean_status_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    return candidate or None


def _clean_reason_code(value: Any) -> str | None:
    candidate = _clean_status_text(value)
    if candidate is None:
        return None
    candidate = candidate.strip().upper()
    if not re.fullmatch(r"[A-Z0-9_]{2,80}", candidate):
        return None
    return candidate


def _clean_safe_evidence_text(value: Any) -> str | None:
    candidate = _clean_status_text(value)
    if candidate is None:
        return None
    if len(candidate) > 160:
        return None
    lowered = candidate.lower()
    sensitive_markers = (
        "bearer ",
        "authorization",
        "cookie",
        "token",
        "secret",
        "credential",
        "api_key",
        "apikey",
        "sk-",
        "key=",
        "auth=",
    )
    if any(marker in lowered for marker in sensitive_markers):
        return None
    return candidate


def _clean_local_service_url(value: Any) -> str | None:
    candidate = _clean_status_text(value)
    if candidate is None:
        return None
    candidate = candidate.split("?", 1)[0].split("#", 1)[0]
    lowered = candidate.lower()
    if "@" in candidate or any(token in lowered for token in ("token=", "key=", "secret=", "auth=")):
        return None
    if not lowered.startswith(("http://", "https://")):
        return None
    return candidate


def verify_installed_package_against_project(project_root: str | None) -> dict[str, Any]:
    project = git_checkout_metadata(project_root)
    project_root_clean = project.get("project_root") if isinstance(project.get("project_root"), str) else None
    base = {
        "source": "installed_package_project_checkout_comparison",
        "package_name": "colameta",
        "runtime_source_root": LOADED_SOURCE_ROOT,
        "project_root": project_root_clean,
        "project_head": _clean_head(project.get("head")),
        "read_only": True,
    }
    if not project_root_clean or not os.path.isdir(project_root_clean):
        return {
            **base,
            "verification_status": "unverified",
            "matches_project_checkout": None,
            "unavailable_reason": "missing_project_root",
        }

    try:
        distribution = importlib.metadata.distribution("colameta")
    except importlib.metadata.PackageNotFoundError:
        return {
            **base,
            "verification_status": "not_installed_package",
            "matches_project_checkout": None,
            "unavailable_reason": "distribution_not_found",
        }

    try:
        distribution_root = os.path.abspath(str(distribution.locate_file("")))
        root_common = os.path.commonpath([distribution_root, LOADED_SOURCE_ROOT])
    except (OSError, ValueError):
        distribution_root = ""
        root_common = ""
    if not distribution_root or root_common != distribution_root:
        return {
            **base,
            "package_version": _distribution_version(distribution),
            "distribution_root": distribution_root or None,
            "verification_status": "not_loaded_from_installed_package",
            "matches_project_checkout": None,
            "unavailable_reason": "loaded_source_root_outside_distribution",
        }

    files = list(distribution.files or [])
    runtime_relative_files = _runtime_distribution_source_files(files)
    if not runtime_relative_files:
        return {
            **base,
            "package_version": _distribution_version(distribution),
            "distribution_root": distribution_root,
            "verification_status": "unverified",
            "matches_project_checkout": None,
            "unavailable_reason": "no_runtime_distribution_files",
        }

    checked_count = 0
    matched_count = 0
    mismatched: list[dict[str, Any]] = []
    unverified: list[dict[str, Any]] = []
    installed_total_size = 0
    project_total_size = 0
    installed_digest = hashlib.sha256()
    project_digest = hashlib.sha256()

    for relative_path in runtime_relative_files:
        installed_path = os.path.join(distribution_root, relative_path)
        project_path = os.path.join(project_root_clean, relative_path)
        installed_fingerprint = _fingerprint_source_file(installed_path)
        project_fingerprint = _fingerprint_source_file(project_path)
        if not installed_fingerprint.get("fingerprint_available") or not project_fingerprint.get("fingerprint_available"):
            unverified.append(
                {
                    "path": relative_path,
                    "installed_available": bool(installed_fingerprint.get("fingerprint_available")),
                    "project_available": bool(project_fingerprint.get("fingerprint_available")),
                    "installed_unavailable_reason": installed_fingerprint.get("unavailable_reason"),
                    "project_unavailable_reason": project_fingerprint.get("unavailable_reason"),
                }
            )
            continue
        checked_count += 1
        installed_sha = _clean_sha256(installed_fingerprint.get("sha256"))
        project_sha = _clean_sha256(project_fingerprint.get("sha256"))
        installed_size = int(installed_fingerprint.get("size_bytes") or 0)
        project_size = int(project_fingerprint.get("size_bytes") or 0)
        installed_total_size += installed_size
        project_total_size += project_size
        installed_digest.update(relative_path.encode("utf-8") + b"\0" + str(installed_sha).encode("ascii") + b"\0")
        project_digest.update(relative_path.encode("utf-8") + b"\0" + str(project_sha).encode("ascii") + b"\0")
        if installed_sha == project_sha:
            matched_count += 1
        else:
            mismatched.append(
                {
                    "path": relative_path,
                    "installed_sha256": installed_sha,
                    "project_sha256": project_sha,
                    "installed_size_bytes": installed_size,
                    "project_size_bytes": project_size,
                }
            )

    if mismatched:
        verification_status = "mismatch"
        matches_project_checkout: bool | None = False
    elif unverified:
        verification_status = "unverified"
        matches_project_checkout = None
    else:
        verification_status = "match"
        matches_project_checkout = True

    return {
        **base,
        "package_version": _distribution_version(distribution),
        "distribution_root": distribution_root,
        "verification_status": verification_status,
        "matches_project_checkout": matches_project_checkout,
        "checked_file_count": checked_count,
        "matched_file_count": matched_count,
        "mismatched_file_count": len(mismatched),
        "unverified_file_count": len(unverified),
        "installed_total_size_bytes": installed_total_size,
        "project_total_size_bytes": project_total_size,
        "installed_runtime_files_sha256": installed_digest.hexdigest() if checked_count else None,
        "project_runtime_files_sha256": project_digest.hexdigest() if checked_count else None,
        "included_roots": ["adapters", "runner", "schemas", "scripts"],
        "mismatched_files": mismatched[:20],
        "unverified_files": unverified[:20],
        "truncated_mismatch_or_unverified_lists": len(mismatched) > 20 or len(unverified) > 20,
    }


def _capture_loaded_runner_module_fingerprints() -> dict[str, dict[str, Any]]:
    captured: dict[str, dict[str, Any]] = {}
    for module_name, module in sorted(list(sys.modules.items())):
        if module_name != "runner" and not module_name.startswith("runner."):
            continue
        source_path = _clean_source_path(getattr(module, "__file__", None))
        if not source_path or not _is_python_source(source_path) or not _is_within_loaded_source_root(source_path):
            continue
        fingerprint = _fingerprint_source_file(source_path)
        captured[module_name] = {
            "module_name": module_name,
            "source_path": source_path,
            "relative_path": _relative_to_loaded_root(source_path),
            "surfaces": _surfaces_for_module(module_name),
            "fingerprint_algorithm": LOADED_MODULE_FINGERPRINT_ALGORITHM,
            "fingerprint_available": bool(fingerprint.get("fingerprint_available")),
            "sha256": fingerprint.get("sha256"),
            "size_bytes": fingerprint.get("size_bytes"),
            "mtime_ns": fingerprint.get("mtime_ns"),
            "captured_at_process_start": True,
        }
    return captured


def _normalize_loaded_module_fingerprints(value: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, dict[str, Any]] = {}
    for raw_module_name, raw_evidence in value.items():
        if not isinstance(raw_module_name, str) or not isinstance(raw_evidence, dict):
            continue
        module_name = raw_module_name.strip()
        if module_name != "runner" and not module_name.startswith("runner."):
            continue
        evidence = dict(raw_evidence)
        evidence["surfaces"] = _clean_surfaces(evidence.get("surfaces")) or _surfaces_for_module(module_name)
        normalized[module_name] = evidence
    return normalized


def _fingerprint_source_file(path: str) -> dict[str, Any]:
    try:
        stat_result = os.stat(path)
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return {
            "fingerprint_available": True,
            "sha256": digest.hexdigest(),
            "size_bytes": stat_result.st_size,
            "mtime_ns": stat_result.st_mtime_ns,
        }
    except OSError as e:
        return _unavailable_fingerprint(e.__class__.__name__)


def _unavailable_fingerprint(reason: str) -> dict[str, Any]:
    return {
        "fingerprint_available": False,
        "sha256": None,
        "size_bytes": None,
        "mtime_ns": None,
        "unavailable_reason": reason,
    }


def _surfaces_for_module(module_name: str) -> list[str]:
    surfaces: set[str] = set()
    if module_name == "runner.runtime_observability":
        surfaces.update({"runtime observability", "MCP tool results"})
    if module_name == "runner.mcp_server" or module_name.startswith("runner.mcp_"):
        surfaces.add("MCP tool results")
    if module_name == "runner.web_console" or module_name.startswith("runner.web_console"):
        surfaces.add("Web Console handlers")
    if (
        module_name.startswith("runner.executor_")
        or module_name.startswith("runner.core_")
        or module_name in {
            "runner.workflow_engine",
            "runner.workflow_records",
            "runner.planning_bridge",
            "runner.plan_loader",
            "runner.state_machine",
            "runner.state_store",
        }
    ):
        surfaces.add("executor workflow code paths")
    if not surfaces:
        surfaces.add("runtime support code")
    return sorted(surfaces)


def _surfaces_from_modules(modules: Any) -> list[str]:
    surfaces: set[str] = set()
    if isinstance(modules, list):
        for module in modules:
            if not isinstance(module, dict):
                continue
            surfaces.update(_clean_surfaces(module.get("surfaces")))
    return sorted(surfaces)


def _clean_surfaces(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    cleaned: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        candidate = item.strip()
        if candidate and candidate not in cleaned:
            cleaned.append(candidate)
    return cleaned


def _distribution_version(distribution: importlib.metadata.Distribution) -> str | None:
    try:
        version = distribution.version
    except Exception:
        return None
    return version if isinstance(version, str) and version.strip() else None


def _runtime_distribution_source_files(files: list[Any]) -> list[str]:
    allowed_roots = {"adapters", "runner", "schemas", "scripts"}
    result: list[str] = []
    for file_ref in files:
        relative_path = str(file_ref).replace("\\", "/").strip("/")
        if not relative_path or relative_path in result:
            continue
        parts = relative_path.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            continue
        if not parts or parts[0] not in allowed_roots:
            continue
        if "__pycache__" in parts:
            continue
        if relative_path.endswith((".pyc", ".pyo")):
            continue
        result.append(relative_path)
    return sorted(result)


def _clean_source_path(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    raw_candidate = value.strip()
    if not raw_candidate:
        return None
    candidate = os.path.abspath(os.path.expanduser(raw_candidate))
    return candidate or None


def _clean_sha256(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip().lower()
    if re.match(r"^[0-9a-f]{64}$", candidate):
        return candidate
    return None


def _is_python_source(path: str) -> bool:
    return path.endswith(".py")


def _is_within_loaded_source_root(path: str) -> bool:
    try:
        common = os.path.commonpath([LOADED_SOURCE_ROOT, path])
    except ValueError:
        return False
    return common == LOADED_SOURCE_ROOT


def _relative_to_loaded_root(path: str) -> str:
    try:
        return os.path.relpath(path, LOADED_SOURCE_ROOT)
    except ValueError:
        return path


def _resolve_git_dir(project_root: str) -> str | None:
    dot_git = os.path.join(project_root, ".git")
    if os.path.isdir(dot_git):
        return dot_git
    if not os.path.isfile(dot_git):
        return None
    content = _read_text(dot_git, max_chars=4096)
    if not content:
        return None
    first_line = content.splitlines()[0].strip()
    if not first_line.lower().startswith("gitdir:"):
        return None
    gitdir = first_line.split(":", 1)[1].strip()
    if not gitdir:
        return None
    if not os.path.isabs(gitdir):
        gitdir = os.path.join(project_root, gitdir)
    gitdir = os.path.abspath(gitdir)
    return gitdir if os.path.isdir(gitdir) else None


def _read_ref(git_dir: str, ref_name: str) -> str | None:
    ref_path = os.path.join(git_dir, *ref_name.split("/"))
    ref_text = _read_text(ref_path, max_chars=4096)
    if ref_text:
        candidate = ref_text.splitlines()[0].strip()
        if _looks_like_head(candidate):
            return candidate
    return _read_packed_ref(git_dir, ref_name)


def _read_packed_ref(git_dir: str, ref_name: str) -> str | None:
    packed_refs = _read_text(os.path.join(git_dir, "packed-refs"), max_chars=1_000_000)
    if not packed_refs:
        return None
    for raw_line in packed_refs.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("^"):
            continue
        parts = line.split(" ", 1)
        if len(parts) != 2:
            continue
        candidate, packed_ref_name = parts[0].strip(), parts[1].strip()
        if packed_ref_name == ref_name and _looks_like_head(candidate):
            return candidate
    return None


def _branch_from_ref(ref_name: str) -> str | None:
    prefix = "refs/heads/"
    if ref_name.startswith(prefix):
        return ref_name[len(prefix):]
    return None


def _read_text(path: str, *, max_chars: int) -> str | None:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read(max_chars)
    except OSError:
        return None


def _looks_like_head(value: str) -> bool:
    return bool(_HEX_HEAD_RE.match(value))


def _clean_head(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not _looks_like_head(candidate):
        return None
    return candidate


_LOADED_RUNTIME_GIT_METADATA = git_checkout_metadata(LOADED_SOURCE_ROOT)
LOADED_RUNTIME_HEAD = _LOADED_RUNTIME_GIT_METADATA.get("head")
LOADED_RUNTIME_BRANCH = _LOADED_RUNTIME_GIT_METADATA.get("branch")
LOADED_RUNTIME_HEAD_SOURCE = _LOADED_RUNTIME_GIT_METADATA.get("head_source")
_LOADED_RUNNER_MODULE_FINGERPRINTS = _capture_loaded_runner_module_fingerprints()
