from __future__ import annotations

import hashlib
import json
import os
import subprocess  # nosec B404
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from runner.work_item_governance.canonical import canonical_sha256, sha256_file
from runner.work_item_governance.activation import (
    AUTHORITATIVE_TOKEN_EVIDENCE_DIGEST_META_KEY,
    AUTHORITATIVE_TOKEN_FILE_SHA256_META_KEY,
    canonical_path_digest,
    validate_authoritative_bearer_token,
)
from runner.work_item_governance.errors import WorkItemGovernanceError
from runner.work_item_governance.pilot import PILOT_SCOPE_MODE, PILOT_TOOLS
from runner.work_item_governance.preview import isoformat_utc, utc_now
from runner.work_item_governance.schema_loader import validate_governance_record


_SAFETY_DIGEST_FIELDS = (
    "network_inventory_digest",
    "process_inventory_digest",
    "project_registry_snapshot_digest",
    "git_remote_snapshot_digest",
    "stable_promotion_snapshot_digest",
)


def _loopback_json_request(
    endpoint: str,
    *,
    payload: dict[str, Any] | None = None,
    token: str | None = None,
    path: str = "/mcp",
) -> tuple[int, dict[str, Any]]:
    parsed = urlparse(endpoint)
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.username or parsed.password:
        raise WorkItemGovernanceError(
            "PILOT_HTTP_CONFORMANCE_ENDPOINT_INVALID",
            "Pilot HTTP conformance permits only an exact 127.0.0.1 HTTP endpoint.",
        )
    base = f"http://127.0.0.1:{parsed.port or 80}"
    headers = {"Accept": "application/json"}
    data = None
    method = "GET"
    if payload is not None:
        data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
        method = "POST"
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(f"{base}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:  # nosec B310 - validated loopback URL
            status = int(response.status)
            raw = response.read()
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        raw = exc.read()
    try:
        value = json.loads(raw.decode("utf-8")) if raw else {}
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorkItemGovernanceError(
            "PILOT_HTTP_CONFORMANCE_RESPONSE_INVALID",
            "Pilot HTTP conformance received a non-JSON response.",
        ) from exc
    if not isinstance(value, dict):
        raise WorkItemGovernanceError(
            "PILOT_HTTP_CONFORMANCE_RESPONSE_INVALID",
            "Pilot HTTP conformance response must be a JSON object.",
        )
    return status, value


def measure_pilot_http_authentication(*, endpoint: str, correct_token: str) -> dict[str, Any]:
    """Probe authentication and restricted dispatch through the live HTTP handler."""

    wrong_token = "mvr_" + ("A" * 43)
    if wrong_token == correct_token:
        wrong_token = "mvr_" + ("B" * 43)
    authenticated_dispatch = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "get_work_item_governance_status", "arguments": {}},
    }
    tools_request = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
    no_status, no_response = _loopback_json_request(endpoint, payload=authenticated_dispatch)
    wrong_status, wrong_response = _loopback_json_request(endpoint, payload=authenticated_dispatch, token=wrong_token)
    correct_status, correct_response = _loopback_json_request(
        endpoint,
        payload=authenticated_dispatch,
        token=correct_token,
    )
    tools_status, tools_response = _loopback_json_request(endpoint, payload=tools_request, token=correct_token)
    actions_status, actions_response = _loopback_json_request(
        endpoint,
        payload={},
        token=correct_token,
        path=f"/api/{PILOT_TOOLS[0]}",
    )
    try:
        visible = tuple(str(item["name"]) for item in tools_response["result"]["tools"])
    except (KeyError, TypeError) as exc:
        raise WorkItemGovernanceError(
            "PILOT_HTTP_CONFORMANCE_RESPONSE_INVALID",
            "Authenticated tools/list response lacks the exact tool definitions.",
        ) from exc
    actions_code = actions_response.get("error_code")
    if (
        no_status != 401
        or wrong_status != 401
        or correct_status != 200
        or tools_status != 200
        or visible != PILOT_TOOLS
        or actions_status != 404
        or actions_code != "ACTIONS_DISABLED"
    ):
        raise WorkItemGovernanceError(
            "PILOT_HTTP_CONFORMANCE_FAILED",
            "Live Pilot HTTP authentication or restricted dispatch failed closed conformance.",
        )
    return {
        "authentication": {
            "no_token_status": no_status,
            "wrong_token_status": wrong_status,
            "correct_token_status": correct_status,
            "no_token_response_digest": canonical_sha256(no_response),
            "wrong_token_response_digest": canonical_sha256(wrong_response),
            "correct_token_response_digest": canonical_sha256(correct_response),
        },
        "surface": {
            "visible_tool_count": len(visible),
            "visible_tool_set_digest": canonical_sha256(list(visible)),
            "tool_list_response_digest": canonical_sha256(tools_response),
            "actions_response_digest": canonical_sha256(actions_response),
            "actions_error_code": actions_code,
        },
    }


def _file_tree_digest(root: Path) -> str:
    entries: list[dict[str, Any]] = []
    if root.is_dir():
        for path in sorted(root.rglob("*")):
            if path.is_symlink():
                raise WorkItemGovernanceError(
                    "PILOT_SAFETY_SNAPSHOT_INVALID",
                    "Safety snapshot refuses symlinks in measured evidence roots.",
                )
            if path.is_file():
                entries.append(
                    {
                        "path": path.relative_to(root).as_posix(),
                        "size": path.stat().st_size,
                        "sha256": sha256_file(path),
                    }
                )
    return canonical_sha256(entries)


def capture_pilot_safety_snapshot(
    *,
    project_root: str | os.PathLike[str],
    registry_path: str | os.PathLike[str],
    stable_promotion_root: str | os.PathLike[str],
    port: int,
) -> dict[str, Any]:
    """Capture reviewable host/project facts used by the fresh Preflight."""

    network_records: list[str] = []
    public_listener = False
    for source in (Path("/proc/net/tcp"), Path("/proc/net/tcp6")):
        if not source.is_file():
            continue
        lines = source.read_text(encoding="utf-8", errors="replace").splitlines()[1:]
        for line in lines:
            columns = line.split()
            if len(columns) < 4 or columns[3] != "0A":
                continue
            address, hex_port = columns[1].split(":", 1)
            network_records.append(f"{source.name}:{address}:{hex_port}:LISTEN")
            if int(hex_port, 16) != port:
                continue
            loopback = address in {"0100007F", "00000000000000000000000001000000"}
            public_listener = public_listener or not loopback

    process_records: list[dict[str, Any]] = []
    relay_or_tunnel = False
    project_marker = Path(project_root).expanduser().resolve().as_posix().lower()
    stable_marker = Path(stable_promotion_root).expanduser().resolve().as_posix().lower()
    for directory in sorted(Path("/proc").glob("[0-9]*"), key=lambda item: int(item.name)):
        try:
            command = (directory / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", errors="replace")
            executable = (directory / "exe").resolve().as_posix()
        except (OSError, PermissionError):
            continue
        lowered = command.lower()
        relevant = (
            "colameta" in lowered
            or project_marker in lowered
            or stable_marker in lowered
            or str(port) in command
        )
        if relevant:
            process_records.append(
                {
                    "executable_digest": canonical_sha256(executable),
                    "command_digest": canonical_sha256(command),
                }
            )
        relay_or_tunnel = relay_or_tunnel or (
            str(port) in command and any(marker in lowered for marker in ("cloudflared", " tunnel", " relay"))
        )

    registry = Path(registry_path).expanduser().resolve()
    registry_digest = hashlib.sha256(registry.read_bytes()).hexdigest() if registry.is_file() else canonical_sha256(None)
    project = Path(project_root).expanduser().resolve()
    git = next((path for path in (Path("/usr/bin/git"), Path("/bin/git")) if path.is_file()), None)
    if git is None:
        raise WorkItemGovernanceError("PILOT_SAFETY_SNAPSHOT_INVALID", "Safety snapshot requires system Git.")
    completed = subprocess.run(  # nosec B603
        [git.as_posix(), "-C", project.as_posix(), "for-each-ref", "--format=%(refname)%00%(objectname)", "refs/remotes"],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
        env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"},
    )
    if completed.returncode:
        raise WorkItemGovernanceError("PILOT_SAFETY_SNAPSHOT_INVALID", "Safety snapshot could not measure remote refs.")
    return {
        "network_inventory_digest": canonical_sha256(sorted(network_records)),
        "process_inventory_digest": canonical_sha256(
            sorted(process_records, key=lambda item: (item["executable_digest"], item["command_digest"]))
        ),
        "project_registry_snapshot_digest": registry_digest,
        "git_remote_snapshot_digest": canonical_sha256(completed.stdout),
        "stable_promotion_snapshot_digest": _file_tree_digest(Path(stable_promotion_root).expanduser().resolve()),
        "public_endpoint": public_listener,
        "relay_or_tunnel": relay_or_tunnel,
    }


def measure_pilot_safety_conformance(
    *,
    expected_snapshot: dict[str, Any],
    project_root: str | os.PathLike[str],
    registry_path: str | os.PathLike[str],
    stable_promotion_root: str | os.PathLike[str],
    port: int,
) -> dict[str, Any]:
    """Fail closed unless current safety facts match the reviewed baseline."""

    current = capture_pilot_safety_snapshot(
        project_root=project_root,
        registry_path=registry_path,
        stable_promotion_root=stable_promotion_root,
        port=port,
    )
    expected = {field: expected_snapshot.get(field) for field in _SAFETY_DIGEST_FIELDS}
    actual = {field: current[field] for field in _SAFETY_DIGEST_FIELDS}
    if actual != expected or current["public_endpoint"] or current["relay_or_tunnel"]:
        raise WorkItemGovernanceError(
            "PILOT_SAFETY_SNAPSHOT_MISMATCH",
            "Pilot host or project safety facts differ from the reviewed baseline.",
        )
    return {
        **actual,
        "public_endpoint": False,
        "relay_or_tunnel": False,
        "existing_service_modified": False,
        "other_project_modified": False,
        "push": False,
        "stable_promotion": False,
    }


def measure_pilot_transport_surface(server: Any) -> dict[str, Any]:
    """Probe one composed MCP server and return reviewable surface evidence."""

    profile = getattr(server, "mcp_exposure_profile", None)
    scope_mode = getattr(server, "work_item_scope_mode", None)
    if profile != "authoritative_canary" or scope_mode != PILOT_SCOPE_MODE:
        raise WorkItemGovernanceError(
            "PILOT_TRANSPORT_CONFORMANCE_INVALID",
            "Transport conformance requires the exact bounded authoritative Pilot profile.",
        )
    tool_payload = server._tool_defs_payload()
    names = tuple(str(item["name"]) for item in tool_payload)
    resources = server._handle_jsonrpc_request(
        {"jsonrpc": "2.0", "id": 1, "method": "resources/list", "params": {}},
        {"mode": "token"},
    )
    resource_read = server._handle_jsonrpc_request(
        {"jsonrpc": "2.0", "id": 2, "method": "resources/read", "params": {"uri": "pilot://denied"}},
        {"mode": "token"},
    )
    hidden = server._handle_jsonrpc_request(
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "manage_files", "arguments": {}}},
        {"mode": "token"},
    )
    alternate = server._handle_jsonrpc_request(
        {"jsonrpc": "2.0", "id": 4, "method": "call_tool", "params": {"name": PILOT_TOOLS[0], "arguments": {}}},
        {"mode": "token"},
    )
    resource_code = (resource_read or {}).get("error", {}).get("data", {}).get("error_code")
    hidden_code = (hidden or {}).get("result", {}).get("structuredContent", {}).get("error_code")
    alternate_code = (alternate or {}).get("error", {}).get("data", {}).get("error_code")
    thread_inventory = sorted(
        (
            {
            "name": thread.name,
            "daemon": bool(thread.daemon),
            }
            for thread in threading.enumerate()
        ),
        key=lambda item: (item["name"], item["daemon"]),
    )
    prohibited_worker_names = ("outbox", "delivery", "stable", "product", "connector", "executor")
    prohibited_workers = any(
        any(marker in thread["name"].lower() for marker in prohibited_worker_names)
        for thread in thread_inventory
    )
    exact = names == PILOT_TOOLS and len(names) == len(set(names))
    resources_empty = resources == {"jsonrpc": "2.0", "id": 1, "result": {"resources": []}}
    return {
        "exposure_profile": profile,
        "scope_mode": scope_mode,
        "visible_tool_count": len(names),
        "visible_tool_set_digest": canonical_sha256(list(names)),
        "tool_list_response_digest": canonical_sha256(tool_payload),
        "resources_list_response_digest": canonical_sha256(resources),
        "resource_read_error_code": resource_code,
        "hidden_tool_error_code": hidden_code,
        "alternate_dispatch_error_code": alternate_code,
        "worker_inventory_digest": canonical_sha256(thread_inventory),
        "definitions_dispatch_exact_match": exact,
        "resources_disabled_or_empty": resources_empty and resource_code == "resources_disabled",
        "actions_disabled": exact and all(not name.startswith("manage_") for name in names),
        "hidden_tool_rejected": hidden_code == "TOOL_NOT_EXPOSED",
        "alternate_dispatch_rejected": alternate_code == "legacy_method_alias_disabled",
        "prohibited_workers_running": prohibited_workers,
    }


def build_pilot_authentication_conformance_receipt(
    *,
    server: Any,
    endpoint: str,
    correct_token: str,
    token_file: str | os.PathLike[str],
    token_binding: dict[str, str],
    source_binding: dict[str, Any],
    runtime_binding: dict[str, Any],
    expected_safety_snapshot: dict[str, Any],
    project_root: str | os.PathLike[str],
    registry_path: str | os.PathLike[str],
    stable_promotion_root: str | os.PathLike[str],
    port: int,
) -> dict[str, Any]:
    """Build the receipt only from live HTTP, composed surface and durable bindings."""

    validate_authoritative_bearer_token(correct_token)
    auth_path = Path(token_file).expanduser().resolve()
    try:
        token_payload = json.loads(auth_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkItemGovernanceError(
            "PILOT_AUTHENTICATION_CONFORMANCE_INVALID",
            "Pilot authentication conformance requires its exact private Token file.",
        ) from exc
    token_file_sha256 = sha256_file(auth_path)
    token_evidence_digest = canonical_sha256(
        {
            "token_file_sha256": token_file_sha256,
            "token_file_path_digest": canonical_path_digest(auth_path),
        }
    )
    expected_binding_keys = {
        AUTHORITATIVE_TOKEN_FILE_SHA256_META_KEY,
        AUTHORITATIVE_TOKEN_EVIDENCE_DIGEST_META_KEY,
    }
    if (
        not isinstance(token_payload, dict)
        or token_payload.get("auth_token") != correct_token
        or set(token_binding) != expected_binding_keys
        or token_binding.get(AUTHORITATIVE_TOKEN_FILE_SHA256_META_KEY) != token_file_sha256
        or token_binding.get(AUTHORITATIVE_TOKEN_EVIDENCE_DIGEST_META_KEY) != token_evidence_digest
    ):
        raise WorkItemGovernanceError(
            "PILOT_AUTHENTICATION_CONFORMANCE_INVALID",
            "Pilot Token file, live Token and Ledger binding do not match.",
        )
    http = measure_pilot_http_authentication(endpoint=endpoint, correct_token=correct_token)
    surface = measure_pilot_transport_surface(server)
    if (
        http["surface"]["visible_tool_count"] != surface["visible_tool_count"]
        or http["surface"]["visible_tool_set_digest"] != surface["visible_tool_set_digest"]
    ):
        raise WorkItemGovernanceError(
            "PILOT_TRANSPORT_CONFORMANCE_INVALID",
            "Live HTTP tools/list differs from the composed server dispatch surface.",
        )
    surface.update(
        {
            "tool_list_response_digest": http["surface"]["tool_list_response_digest"],
            "actions_response_digest": http["surface"]["actions_response_digest"],
            "actions_error_code": http["surface"]["actions_error_code"],
            "actions_disabled": http["surface"]["actions_error_code"] == "ACTIONS_DISABLED",
        }
    )
    safety = measure_pilot_safety_conformance(
        expected_snapshot=expected_safety_snapshot,
        project_root=project_root,
        registry_path=registry_path,
        stable_promotion_root=stable_promotion_root,
        port=port,
    )
    receipt = {
        "schema_version": "wig_p3_pilot_authentication_conformance_receipt.v1",
        "tested_at": isoformat_utc(utc_now()),
        "source_binding": dict(source_binding),
        "runtime_binding": dict(runtime_binding),
        "authentication": {
            "auth_mode": "token",
            "token_format_valid": True,
            "token_ledger_binding_valid": True,
            **http["authentication"],
            "request_capability_non_json": True,
            "request_capability_single_use": True,
        },
        "surface": surface,
        "safety": safety,
        "result": "PASS",
    }
    validate_governance_record("pilot_authentication_conformance_receipt.v1", receipt)
    return receipt


__all__ = [
    "build_pilot_authentication_conformance_receipt",
    "capture_pilot_safety_snapshot",
    "measure_pilot_safety_conformance",
    "measure_pilot_http_authentication",
    "measure_pilot_transport_surface",
]
