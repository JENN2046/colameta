from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import subprocess
import tarfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from runner.runtime_observability import git_checkout_metadata
from runner.stable_promotion_readiness import DEFAULT_STABLE_RUNTIME_DIR
from scripts.remote_https_mcp_preflight import normalize_public_base_url, run_preflight
from urllib.parse import urlparse


DEFAULT_PUBLIC_BASE_URL = "https://colameta-mcp.skmt617.top"
DEFAULT_STATUS_PATH = "~/.local/state/colameta/ops/last-status.json"
DEFAULT_CONNECTOR_SMOKE_FRESH_HOURS = 24
DEFAULT_CLOUDFLARED_SERVICE = "cloudflared-colameta-mcp-prod.service"
DEFAULT_STABLE_SERVICE = "colameta-stable.service"
DEFAULT_BACKUP_DIR = "/home/jenn/tools/colameta-stable-backups"
LOCAL_HEALTH_PROBE_TIMEOUT_SECONDS = 2.0
DEFAULT_COMMAND_TIMEOUT_SECONDS = 10.0
REDACTED_PUBLIC_BASE_URL = "<redacted-public-base-url>"
REDACTED_CONNECTOR_SMOKE_VALUE = "<redacted-connector-smoke-value>"
REDACTED_STATUS_WRITTEN_PATH = "<redacted-status-written-path>"
EXPECTED_WEB_HEALTH_SERVICE = "colameta-web-console"
EXPECTED_MCP_HEALTH_SERVICE = "colameta-mcp"

BLOCKED = "blocked"
NEEDS_ATTENTION = "needs_attention"
READY = "ready"

SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_\-]{12,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9_]{12,}"),
    re.compile(r"(?i)\bAuthorization\s*:\s*Bearer\s+\S+"),
    re.compile(r"(?i)\bBearer\s+\S+"),
    re.compile(r"(?i)\bBearer\s+eyJ[A-Za-z0-9_\-]*(?:\.[A-Za-z0-9_\-]+){1,2}"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\b"),
    re.compile(r"(?i)\b(client_secret|access_token|refresh_token|id_token|cookie|password|private_key)\b"),
)
SENSITIVE_KEY_RE = re.compile(r"(?i)(secret|token|cookie|password|credential|private[_-]?key|authorization)")
CONNECTOR_SMOKE_STATUS_ALLOWLIST = frozenset(
    {
        "ready",
        "missing",
        "stale",
        "failed",
        "needs_attention",
        "blocked",
        "unavailable",
        "unknown",
    }
)


def build_production_ops_packet(
    project_root: str,
    *,
    public_base_url: str = DEFAULT_PUBLIC_BASE_URL,
    expected_head: str | None = None,
    stable_runtime_dir: str = DEFAULT_STABLE_RUNTIME_DIR,
    stable_service_name: str = DEFAULT_STABLE_SERVICE,
    cloudflared_service_name: str = DEFAULT_CLOUDFLARED_SERVICE,
    backup_dir: str = DEFAULT_BACKUP_DIR,
    no_network: bool = False,
    connector_smoke: dict[str, Any] | None = None,
    connector_smoke_fresh_hours: int = DEFAULT_CONNECTOR_SMOKE_FRESH_HOURS,
    command_runner: Callable[[list[str]], subprocess.CompletedProcess[str]] | None = None,
    preflight_runner: Callable[..., dict[str, Any]] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    root = os.path.abspath(os.path.expanduser(project_root))
    observed_at = _iso_now(now)
    command_runner = command_runner or _run_command
    preflight_runner = preflight_runner or run_preflight
    candidate_head = _git_head(root, command_runner)
    target_head, expected_head_check = _expected_head_for_packet(expected_head, candidate_head)
    safe_public_base_url, public_base_url_check = _public_base_url_for_packet(public_base_url)

    checks: dict[str, dict[str, Any]] = {
        "candidate_head": _candidate_head_check(candidate_head, target_head),
        "origin_main": _origin_main_check(root, candidate_head, command_runner),
        "stable_runtime": _stable_runtime_check(stable_runtime_dir, target_head, command_runner),
        "stable_service": _systemd_service_check(stable_service_name, command_runner),
        "local_stable_health": _local_stable_health_check(command_runner, target_head),
        "remote_https_mcp_preflight": public_base_url_check
        or _remote_preflight_check(safe_public_base_url, no_network, preflight_runner),
        "cloudflared_service": _systemd_service_check(cloudflared_service_name, command_runner),
        "backup_inventory": _backup_inventory_check(backup_dir),
        "rollback_rehearsal": _rollback_rehearsal_check(root, backup_dir, target_head, command_runner),
        "connector_smoke": _connector_smoke_check(
            connector_smoke,
            fresh_hours=connector_smoke_fresh_hours,
            now=now,
        ),
    }
    if expected_head_check is not None:
        checks["expected_head"] = expected_head_check

    reason_codes: list[str] = []
    blocker_codes: list[str] = []
    needs_attention_codes: list[str] = []
    for check in checks.values():
        for code in check.get("reason_codes", []):
            if isinstance(code, str):
                reason_codes.append(code)
        if check.get("status") == BLOCKED:
            blocker_codes.extend(str(code) for code in check.get("reason_codes", []))
        elif check.get("status") == NEEDS_ATTENTION:
            needs_attention_codes.extend(str(code) for code in check.get("reason_codes", []))

    ops_check_ready = not blocker_codes and not needs_attention_codes_for_ops(checks)
    connector_smoke_ready = checks["connector_smoke"]["status"] == READY
    beta_gate_ready = ops_check_ready and connector_smoke_ready
    status = READY if beta_gate_ready else (BLOCKED if blocker_codes else NEEDS_ATTENTION)
    summary = _summary_for_status(status, ops_check_ready, connector_smoke_ready)

    packet: dict[str, Any] = {
        "ok": True,
        "source": "production_ops_beta_gate",
        "read_only": True,
        "side_effects": False,
        "project_root": root,
        "public_base_url": safe_public_base_url,
        "observed_at": observed_at,
        "status": status,
        "summary": summary,
        "ops_check_ready": ops_check_ready,
        "connector_smoke_ready": connector_smoke_ready,
        "beta_gate_ready": beta_gate_ready,
        "candidate_head": candidate_head,
        "expected_head": target_head,
        "stable_runtime_dir": os.path.abspath(os.path.expanduser(stable_runtime_dir)),
        "checks": checks,
        "reason_codes": sorted(set(reason_codes)),
        "blocker_codes": sorted(set(blocker_codes)),
        "needs_attention_codes": sorted(set(needs_attention_codes)),
        "not_authorized_actions": [
            "read_tokens_or_cookies",
            "read_env_values",
            "read_provider_config",
            "read_raw_logs",
            "provider_api_call",
            "modify_dns_or_tunnel",
            "restart_service",
            "stable_replacement",
            "rollback_or_restore",
            "release_or_deploy",
            "tag_push_or_package_publish",
            "create_github_issue_or_pr",
        ],
    }
    leak_check = _detect_sensitive_content(packet)
    if leak_check["status"] == BLOCKED:
        packet["status"] = BLOCKED
        packet["ops_check_ready"] = False
        packet["connector_smoke_ready"] = False
        packet["beta_gate_ready"] = False
        packet["checks"]["secret_redaction"] = leak_check
        packet["blocker_codes"] = sorted(set([*packet["blocker_codes"], "SECRET_LIKE_CONTENT_DETECTED"]))
        packet["reason_codes"] = sorted(set([*packet["reason_codes"], "SECRET_LIKE_CONTENT_DETECTED"]))
        packet["summary"] = "Production operations packet is blocked because secret-like content was detected."
    else:
        packet["checks"]["secret_redaction"] = leak_check
    return packet


def validate_status_write_path(path: str, *, project_root: str) -> str:
    resolved = os.path.abspath(os.path.expanduser(path))
    root = os.path.abspath(os.path.expanduser(project_root))
    if _is_relative_to(resolved, root):
        raise ValueError("--write-status refuses repository paths; use ~/.local/state/colameta/ops/last-status.json.")
    return resolved


def write_status_packet(path: str, packet: dict[str, Any], *, project_root: str, json_dumps: Callable[[object], str]) -> str:
    resolved = validate_status_write_path(path, project_root=project_root)
    parent = os.path.dirname(resolved)
    os.makedirs(parent, exist_ok=True)
    tmp = f"{resolved}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(json_dumps(packet))
        handle.write("\n")
    os.replace(tmp, resolved)
    return resolved


def redact_status_written_path(path: str) -> str:
    text = str(path)
    if _contains_sensitive_text(text):
        return REDACTED_STATUS_WRITTEN_PATH
    return text


def _expected_head_for_packet(
    expected_head: str | None,
    candidate_head: str | None,
) -> tuple[str | None, dict[str, Any] | None]:
    if expected_head is None:
        return candidate_head, None
    cleaned = _clean_head(expected_head)
    if cleaned:
        return cleaned, None
    return None, _check(
        BLOCKED,
        "EXPECTED_HEAD_INVALID",
        "Explicit expected head must be a full 40-character commit SHA.",
        expected_head_valid=False,
    )


def _candidate_head_check(candidate_head: str | None, expected_head: str | None) -> dict[str, Any]:
    if not candidate_head:
        return _check(BLOCKED, "CANDIDATE_HEAD_UNKNOWN", "Unable to resolve project Git HEAD.")
    return _check(
        READY,
        "CANDIDATE_HEAD_READY",
        "Project HEAD is known.",
        head=candidate_head,
        expected_stable_head=expected_head,
    )


def _origin_main_check(
    project_root: str,
    candidate_head: str | None,
    command_runner: Callable[[list[str]], subprocess.CompletedProcess[str]],
) -> dict[str, Any]:
    result = command_runner(["git", "-C", project_root, "rev-parse", "origin/main"])
    origin_head = _clean_head(result.stdout.strip()) if result.returncode == 0 else None
    if not origin_head:
        return _check(NEEDS_ATTENTION, "ORIGIN_MAIN_HEAD_UNKNOWN", "Unable to resolve origin/main.")
    if candidate_head and origin_head != candidate_head:
        return _check(
            NEEDS_ATTENTION,
            "ORIGIN_MAIN_NOT_ALIGNED",
            "Project HEAD is not aligned with origin/main.",
            origin_main_head=origin_head,
            candidate_head=candidate_head,
        )
    return _check(READY, "ORIGIN_MAIN_ALIGNED", "Project HEAD is aligned with origin/main.", origin_main_head=origin_head)


def _stable_runtime_check(
    stable_runtime_dir: str,
    expected_head: str | None,
    command_runner: Callable[[list[str]], subprocess.CompletedProcess[str]],
) -> dict[str, Any]:
    metadata = git_checkout_metadata(stable_runtime_dir)
    stable_head = metadata.get("head") if isinstance(metadata.get("head"), str) else _git_head(stable_runtime_dir, command_runner)
    if not stable_head:
        return _check(BLOCKED, "STABLE_RUNTIME_HEAD_UNKNOWN", "Stable runtime Git HEAD is unavailable.")
    if expected_head and stable_head != expected_head:
        return _check(BLOCKED, "STABLE_RUNTIME_HEAD_MISMATCH", "Stable runtime is not aligned to expected head.", head=stable_head)
    return _check(READY, "STABLE_RUNTIME_ALIGNED", "Stable runtime is aligned to expected head.", head=stable_head)


def _systemd_service_check(
    service_name: str,
    command_runner: Callable[[list[str]], subprocess.CompletedProcess[str]],
) -> dict[str, Any]:
    result = command_runner(
        ["systemctl", "--user", "show", service_name, "-p", "ActiveState", "-p", "SubState", "-p", "MainPID"]
    )
    properties = _parse_systemd_properties(result.stdout)
    pid = properties.get("MainPID")
    active = properties.get("ActiveState")
    sub = properties.get("SubState")
    if result.returncode != 0 or active != "active" or sub != "running":
        return _check(
            BLOCKED,
            "SYSTEMD_SERVICE_NOT_RUNNING",
            f"{service_name} is not active/running.",
            service_name=service_name,
            active_state=active,
            sub_state=sub,
            main_pid=pid,
        )
    return _check(
        READY,
        "SYSTEMD_SERVICE_RUNNING",
        f"{service_name} is active/running.",
        service_name=service_name,
        active_state=active,
        sub_state=sub,
        main_pid=pid,
    )


def _local_stable_health_check(
    command_runner: Callable[[list[str]], subprocess.CompletedProcess[str]],
    expected_head: str | None,
) -> dict[str, Any]:
    web = _curl_json_health("http://127.0.0.1:8801/api/healthz", command_runner)
    mcp = _curl_json_health("http://127.0.0.1:8766/healthz", command_runner)
    health_evidence = {
        "web_healthz_http_status": web.get("http_status"),
        "web_healthz_ok": web.get("ok"),
        "web_healthz_service": web.get("service"),
        "web_loaded_runtime_head": web.get("loaded_runtime_head"),
        "web_runtime_project_checkout_head": web.get("runtime_project_checkout_head"),
        "web_runtime_loaded_code_stale": web.get("runtime_loaded_code_stale"),
        "web_reload_needed_for_verification": web.get("reload_needed_for_verification"),
        "web_reload_awareness_reason": web.get("reload_awareness_reason"),
        "web_installed_package_matches_project_checkout": web.get("installed_package_matches_project_checkout"),
        "web_installed_package_verification_status": web.get("installed_package_verification_status"),
        "mcp_healthz_http_status": mcp.get("http_status"),
        "mcp_healthz_ok": mcp.get("ok"),
        "mcp_healthz_service": mcp.get("service"),
        "mcp_loaded_runtime_head": mcp.get("loaded_runtime_head"),
        "mcp_runtime_project_checkout_head": mcp.get("runtime_project_checkout_head"),
        "mcp_runtime_loaded_code_stale": mcp.get("runtime_loaded_code_stale"),
        "mcp_reload_needed_for_verification": mcp.get("reload_needed_for_verification"),
        "mcp_reload_awareness_reason": mcp.get("reload_awareness_reason"),
        "mcp_installed_package_matches_project_checkout": mcp.get("installed_package_matches_project_checkout"),
        "mcp_installed_package_verification_status": mcp.get("installed_package_verification_status"),
        "expected_head": expected_head,
    }
    if not _health_endpoint_ready(web, EXPECTED_WEB_HEALTH_SERVICE) or not _health_endpoint_ready(
        mcp, EXPECTED_MCP_HEALTH_SERVICE
    ):
        return _check(
            BLOCKED,
            "LOCAL_STABLE_HEALTH_FAILED",
            "Stable local Web or MCP health check failed.",
            **health_evidence,
        )
    web_verified = _health_runtime_matches_expected(web, expected_head)
    mcp_verified = _health_runtime_matches_expected(mcp, expected_head)
    if _health_runtime_mismatches_expected(web, expected_head) or _health_runtime_mismatches_expected(mcp, expected_head):
        return _check(
            BLOCKED,
            "LOCAL_STABLE_RUNTIME_HEAD_MISMATCH",
            "Stable local Web or MCP service is not serving the expected loaded runtime head.",
            **health_evidence,
        )
    if not expected_head or not web_verified or not mcp_verified:
        return _check(
            BLOCKED,
            "LOCAL_STABLE_RUNTIME_HEAD_UNVERIFIED",
            "Stable local Web and MCP health checks did not prove the running loaded runtime head.",
            **health_evidence,
        )
    return _check(
        READY,
        "LOCAL_STABLE_HEALTH_READY",
        "Stable local Web and MCP health checks passed.",
        **health_evidence,
    )


def _remote_preflight_check(
    public_base_url: str,
    no_network: bool,
    preflight_runner: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    if _is_loopback_http_url(public_base_url) and not no_network:
        return _check(
            NEEDS_ATTENTION,
            "REMOTE_PREFLIGHT_LOCAL_HTTP_NOT_REMOTE",
            "Loopback HTTP cannot satisfy the production remote HTTPS MCP preflight.",
            network_check="not_run",
            connector_url=f"{public_base_url.rstrip('/')}/mcp",
            failures=["loopback http is allowed only for offline shape checks"],
        )
    try:
        report = preflight_runner(public_base_url, allow_local_http=no_network, no_network=no_network)
    except Exception as exc:
        return _check(BLOCKED, "REMOTE_PREFLIGHT_ERROR", "Remote HTTPS MCP preflight raised an error.", error=str(exc))
    failures = report.get("failures") if isinstance(report, dict) else None
    if isinstance(report, dict) and report.get("ok") is True:
        if no_network:
            return _check(
                NEEDS_ATTENTION,
                "REMOTE_PREFLIGHT_NOT_RUN",
                "Remote HTTPS MCP preflight was not run; offline shape check does not satisfy Beta Gate.",
                network_check=report.get("network_check"),
                connector_url=report.get("connector_url"),
                failures=failures or [],
            )
        return _check(
            READY,
            "REMOTE_PREFLIGHT_READY",
            "Remote HTTPS MCP preflight passed.",
            network_check=report.get("network_check"),
            connector_url=report.get("connector_url"),
            failures=failures or [],
        )
    return _check(
        BLOCKED,
        "REMOTE_PREFLIGHT_FAILED",
        "Remote HTTPS MCP preflight failed.",
        network_check=report.get("network_check") if isinstance(report, dict) else None,
        failures=failures or [],
    )


def _backup_inventory_check(backup_dir: str) -> dict[str, Any]:
    latest = _latest_backup(backup_dir)
    if latest is None:
        return _check(NEEDS_ATTENTION, "STABLE_BACKUP_MISSING", "No stable backup archive was found.")
    sha = _sha256_file(latest)
    if not sha:
        return _check(NEEDS_ATTENTION, "STABLE_BACKUP_SHA256_UNAVAILABLE", "Stable backup sha256 could not be calculated.", backup_file=str(latest))
    try:
        with tarfile.open(latest, "r:gz") as archive:
            first_members = archive.getnames()[:5]
    except (tarfile.TarError, OSError):
        return _check(NEEDS_ATTENTION, "STABLE_BACKUP_ARCHIVE_UNREADABLE", "Stable backup archive could not be listed.", backup_file=str(latest), backup_sha256=sha)
    return _check(
        READY,
        "STABLE_BACKUP_READY",
        "Stable backup archive exists, has sha256, and can be listed.",
        backup_file=str(latest),
        backup_sha256=sha,
        sample_members=first_members,
    )


def _rollback_rehearsal_check(
    project_root: str,
    backup_dir: str,
    target_head: str | None,
    command_runner: Callable[[list[str]], subprocess.CompletedProcess[str]],
) -> dict[str, Any]:
    latest = _latest_backup(backup_dir)
    if latest is None:
        return _check(NEEDS_ATTENTION, "ROLLBACK_BACKUP_MISSING", "Rollback rehearsal needs a stable backup archive.")
    if not target_head:
        return _check(NEEDS_ATTENTION, "ROLLBACK_TARGET_COMMIT_UNRESOLVED", "Rollback target commit is unavailable.")
    result = command_runner(["git", "-C", project_root, "cat-file", "-e", f"{target_head}^{{commit}}"])
    if result.returncode != 0:
        return _check(NEEDS_ATTENTION, "ROLLBACK_TARGET_COMMIT_UNRESOLVED", "Rollback target commit cannot be resolved.", target_head=target_head)
    try:
        with tarfile.open(latest, "r:gz") as archive:
            archive.getmembers()[:1]
    except (tarfile.TarError, OSError):
        return _check(NEEDS_ATTENTION, "ROLLBACK_BACKUP_ARCHIVE_UNREADABLE", "Rollback rehearsal backup archive cannot be listed.", backup_file=str(latest))
    return _check(
        READY,
        "ROLLBACK_REHEARSAL_READY",
        "Rollback rehearsal evidence is available without modifying stable runtime.",
        backup_file=str(latest),
        target_head=target_head,
        rehearsal_executed_restore=False,
    )


def _connector_smoke_check(
    connector_smoke: dict[str, Any] | None,
    *,
    fresh_hours: int,
    now: datetime | None,
) -> dict[str, Any]:
    if not isinstance(connector_smoke, dict):
        return _check(NEEDS_ATTENTION, "CONNECTOR_SMOKE_MISSING", "Fresh ChatGPT connector smoke evidence was not provided.")
    status = connector_smoke.get("status") or connector_smoke.get("apps_connector_closeout_status")
    observed = connector_smoke.get("last_observed_at") or connector_smoke.get("observed_at")
    safe_status, status_redacted, status_allowlisted = _connector_smoke_status_for_packet(status)
    safe_observed, observed_redacted, observed_valid = _connector_smoke_observed_at_for_packet(observed)
    if status_redacted or observed_redacted:
        return _check(
            BLOCKED,
            "CONNECTOR_SMOKE_REJECTED",
            "Connector smoke evidence was rejected before status emission.",
            connector_status=safe_status,
            last_observed_at=safe_observed,
            redacted=True,
        )
    if safe_status != "ready":
        return _check(
            NEEDS_ATTENTION,
            "CONNECTOR_SMOKE_NOT_READY",
            "ChatGPT connector smoke evidence is not ready.",
            connector_status=safe_status,
            last_observed_at=safe_observed,
            connector_status_valid=status_allowlisted,
            observed_at_valid=observed_valid,
            redacted=safe_status == REDACTED_CONNECTOR_SMOKE_VALUE or safe_observed == REDACTED_CONNECTOR_SMOKE_VALUE,
        )
    if not observed_valid:
        return _check(
            NEEDS_ATTENTION,
            "CONNECTOR_SMOKE_STALE",
            "ChatGPT connector smoke evidence is stale.",
            connector_status=safe_status,
            last_observed_at=safe_observed,
            observed_at_valid=False,
            redacted=safe_observed == REDACTED_CONNECTOR_SMOKE_VALUE,
        )
    if not _is_fresh_iso8601(str(safe_observed or ""), fresh_hours=fresh_hours, now=now):
        return _check(NEEDS_ATTENTION, "CONNECTOR_SMOKE_STALE", "ChatGPT connector smoke evidence is stale.", connector_status=safe_status, last_observed_at=safe_observed)
    return _check(READY, "CONNECTOR_SMOKE_READY", "Fresh ChatGPT connector smoke evidence is ready.", connector_status=safe_status, last_observed_at=safe_observed)


def _redact_connector_smoke_field(value: Any) -> tuple[Any, bool]:
    if isinstance(value, str) and _contains_sensitive_text(value):
        return REDACTED_CONNECTOR_SMOKE_VALUE, True
    return value, False


def _connector_smoke_status_for_packet(value: Any) -> tuple[Any, bool, bool]:
    safe_value, redacted = _redact_connector_smoke_field(value)
    if redacted:
        return safe_value, True, False
    if not isinstance(value, str):
        return None, False, False
    normalized = value.strip().lower()
    if normalized in CONNECTOR_SMOKE_STATUS_ALLOWLIST:
        return normalized, False, True
    return REDACTED_CONNECTOR_SMOKE_VALUE, False, False


def _connector_smoke_observed_at_for_packet(value: Any) -> tuple[Any, bool, bool]:
    if value in (None, ""):
        return None, False, False
    safe_value, redacted = _redact_connector_smoke_field(value)
    if redacted:
        return safe_value, True, False
    if not isinstance(value, str) or _parse_iso8601(value) is None:
        return REDACTED_CONNECTOR_SMOKE_VALUE, False, False
    return value, False, True


def _public_base_url_for_packet(public_base_url: str) -> tuple[str, dict[str, Any] | None]:
    if not isinstance(public_base_url, str):
        return REDACTED_PUBLIC_BASE_URL, _check(
            BLOCKED,
            "PUBLIC_BASE_URL_REJECTED",
            "public_base_url was rejected before status emission.",
            error="public_base_url must be a string.",
            redacted=True,
        )
    try:
        normalized = normalize_public_base_url(public_base_url, allow_local_http=True)
    except ValueError as exc:
        return REDACTED_PUBLIC_BASE_URL, _check(
            BLOCKED,
            "PUBLIC_BASE_URL_REJECTED",
            "public_base_url was rejected before status emission.",
            error=str(exc),
            redacted=True,
        )
    if _contains_sensitive_text(normalized):
        return REDACTED_PUBLIC_BASE_URL, _check(
            BLOCKED,
            "PUBLIC_BASE_URL_REJECTED",
            "public_base_url was rejected before status emission.",
            error="public_base_url contains secret-like content.",
            redacted=True,
        )
    return normalized, None


def _contains_sensitive_text(value: str) -> bool:
    return any(pattern.search(value) for pattern in SECRET_PATTERNS)


def _is_loopback_http_url(value: str) -> bool:
    parsed = urlparse(value.strip())
    if parsed.scheme != "http":
        return False
    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _detect_sensitive_content(value: Any) -> dict[str, Any]:
    findings: list[str] = []

    def walk(item: Any, path: str) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                key_text = str(key)
                child_path = f"{path}.{key_text}" if path else key_text
                if SENSITIVE_KEY_RE.search(key_text) and child not in (None, "", [], {}):
                    findings.append(child_path)
                walk(child, child_path)
        elif isinstance(item, list):
            for index, child in enumerate(item):
                walk(child, f"{path}[{index}]")
        elif isinstance(item, str):
            for pattern in SECRET_PATTERNS:
                if pattern.search(item):
                    findings.append(path)
                    break

    walk(value, "")
    if findings:
        return _check(BLOCKED, "SECRET_LIKE_CONTENT_DETECTED", "Secret-like content was detected in the packet.", finding_paths=sorted(set(findings))[:10])
    return _check(READY, "NO_SECRET_LIKE_CONTENT_DETECTED", "No secret-like content was detected in the packet.")


def needs_attention_codes_for_ops(checks: dict[str, dict[str, Any]]) -> list[str]:
    codes: list[str] = []
    for name, check in checks.items():
        if name == "connector_smoke":
            continue
        if check.get("status") == NEEDS_ATTENTION:
            codes.extend(str(code) for code in check.get("reason_codes", []))
    return codes


def _check(status: str, reason_code: str, message: str, **extra: Any) -> dict[str, Any]:
    return {
        "status": status,
        "reason_code": reason_code,
        "reason_codes": [reason_code],
        "message": message,
        "evidence_source": extra.pop("evidence_source", "local_read_only_status"),
        **{key: value for key, value in extra.items() if value is not None},
    }


def _summary_for_status(status: str, ops_ready: bool, connector_ready: bool) -> str:
    if status == READY:
        return "Production operations Beta Gate evidence is ready."
    if not ops_ready:
        return "Production operations checks need attention before Beta Gate."
    if not connector_ready:
        return "Operations checks are ready, but fresh ChatGPT connector smoke evidence is missing or stale."
    return "Production operations Beta Gate is not ready."


def _git_head(path: str, command_runner: Callable[[list[str]], subprocess.CompletedProcess[str]]) -> str | None:
    result = command_runner(["git", "-C", os.path.abspath(os.path.expanduser(path)), "rev-parse", "HEAD"])
    if result.returncode != 0:
        return None
    return _clean_head(result.stdout.strip())


def _curl_json_health(url: str, command_runner: Callable[[list[str]], subprocess.CompletedProcess[str]]) -> dict[str, Any]:
    result = command_runner(
        [
            "curl",
            "-fsS",
            "--connect-timeout",
            "1",
            "--max-time",
            str(int(LOCAL_HEALTH_PROBE_TIMEOUT_SECONDS)),
            "-w",
            "\n%{http_code}",
            url,
        ]
    )
    if result.returncode != 0:
        return {"http_status": None, "ok": None, "service": None}
    body, separator, status_text = result.stdout.rpartition("\n")
    if not separator:
        return {"http_status": None, "ok": None, "service": None}
    status = status_text.strip() or None
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return {
        "http_status": status,
        "ok": payload.get("ok"),
        "service": payload.get("service") if isinstance(payload.get("service"), str) else None,
        "loaded_runtime_head": _clean_head(payload.get("loaded_runtime_head")),
        "runtime_project_checkout_head": _clean_head(
            payload.get("runtime_project_checkout_head") or payload.get("project_checkout_head")
        ),
        "runtime_loaded_code_stale": payload.get("runtime_loaded_code_stale")
        if isinstance(payload.get("runtime_loaded_code_stale"), bool)
        else None,
        "reload_needed_for_verification": payload.get("reload_needed_for_verification")
        if isinstance(payload.get("reload_needed_for_verification"), bool)
        else None,
        "reload_awareness_reason": payload.get("reload_awareness_reason")
        if isinstance(payload.get("reload_awareness_reason"), str)
        else None,
        "installed_package_matches_project_checkout": payload.get("installed_package_matches_project_checkout")
        if isinstance(payload.get("installed_package_matches_project_checkout"), bool)
        else None,
        "installed_package_verification_status": payload.get("installed_package_verification_status")
        if isinstance(payload.get("installed_package_verification_status"), str)
        else None,
    }


def _health_endpoint_ready(health: dict[str, Any], expected_service: str) -> bool:
    return health.get("http_status") == "200" and health.get("ok") is True and health.get("service") == expected_service


def _health_runtime_matches_expected(health: dict[str, Any], expected_head: str | None) -> bool:
    if not expected_head:
        return False
    if health.get("loaded_runtime_head") == expected_head:
        return True
    return (
        health.get("runtime_project_checkout_head") == expected_head
        and health.get("runtime_loaded_code_stale") is False
        and health.get("reload_needed_for_verification") is False
        and health.get("installed_package_matches_project_checkout") is True
        and health.get("installed_package_verification_status") == "match"
    )


def _health_runtime_mismatches_expected(health: dict[str, Any], expected_head: str | None) -> bool:
    loaded_head = health.get("loaded_runtime_head")
    return bool(expected_head and loaded_head and loaded_head != expected_head)


def _run_command(args: list[str]) -> subprocess.CompletedProcess[str]:
    timeout = LOCAL_HEALTH_PROBE_TIMEOUT_SECONDS + 1.0 if args[:1] == ["curl"] else DEFAULT_COMMAND_TIMEOUT_SECONDS
    try:
        return subprocess.run(args, check=False, text=True, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        if not stderr:
            stderr = f"command timed out after {timeout:g}s"
        return subprocess.CompletedProcess(args, 124, stdout=stdout, stderr=stderr)


def _latest_backup(backup_dir: str) -> Path | None:
    root = Path(os.path.abspath(os.path.expanduser(backup_dir)))
    if not root.is_dir():
        return None
    backups = [item for item in root.glob("stable-before-*.tar.gz") if item.is_file()]
    if not backups:
        return None
    return max(backups, key=lambda item: item.stat().st_mtime)


def _sha256_file(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def _is_fresh_iso8601(value: str, *, fresh_hours: int, now: datetime | None) -> bool:
    observed = _parse_iso8601(value)
    if observed is None:
        return False
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    if observed > reference:
        return False
    return reference - observed <= timedelta(hours=max(0, fresh_hours))


def _parse_iso8601(value: str) -> datetime | None:
    try:
        observed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    return observed


def _parse_systemd_properties(output: str) -> dict[str, str]:
    properties: dict[str, str] = {}
    for line in output.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key:
            properties[key] = value.strip()
    return properties


def _iso_now(now: datetime | None) -> str:
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    return reference.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _clean_head(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    if re.fullmatch(r"[0-9a-f]{40}", text):
        return text
    return None


def _is_relative_to(path: str, root: str) -> bool:
    try:
        common = os.path.commonpath([path, root])
    except ValueError:
        return False
    return common == root
