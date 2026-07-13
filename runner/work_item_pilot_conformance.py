from __future__ import annotations

import hashlib
import os
import subprocess  # nosec B404
import threading
from pathlib import Path
from typing import Any

from runner.work_item_governance.canonical import canonical_sha256, sha256_file
from runner.work_item_governance.errors import WorkItemGovernanceError
from runner.work_item_governance.pilot import PILOT_SCOPE_MODE, PILOT_TOOLS


_SAFETY_DIGEST_FIELDS = (
    "network_inventory_digest",
    "process_inventory_digest",
    "project_registry_snapshot_digest",
    "git_remote_snapshot_digest",
    "stable_promotion_snapshot_digest",
)


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
        network_records.extend(f"{source.name}:{line.strip()}" for line in lines)
        for line in lines:
            columns = line.split()
            if len(columns) < 4 or columns[3] != "0A":
                continue
            address, hex_port = columns[1].split(":", 1)
            if int(hex_port, 16) != port:
                continue
            loopback = address in {"0100007F", "00000000000000000000000001000000"}
            public_listener = public_listener or not loopback

    process_records: list[dict[str, Any]] = []
    relay_or_tunnel = False
    for directory in sorted(Path("/proc").glob("[0-9]*"), key=lambda item: int(item.name)):
        try:
            command = (directory / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", errors="replace")
            executable = (directory / "exe").resolve().as_posix()
        except (OSError, PermissionError):
            continue
        process_records.append(
            {
                "pid": int(directory.name),
                "executable_digest": canonical_sha256(executable),
                "command_digest": canonical_sha256(command),
            }
        )
        lowered = command.lower()
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
        "process_inventory_digest": canonical_sha256(process_records),
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


__all__ = [
    "capture_pilot_safety_snapshot",
    "measure_pilot_safety_conformance",
    "measure_pilot_transport_surface",
]
