from __future__ import annotations

import os
import secrets
import socket
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runner.work_item_governance.activation import (
    AUTHORITATIVE_TOKEN_EVIDENCE_DIGEST_META_KEY,
    AUTHORITATIVE_TOKEN_FILE_SHA256_META_KEY,
)
from runner.work_item_governance.canonical import canonical_json, canonical_sha256, sha256_file
from runner.work_item_governance.errors import WorkItemGovernanceError
from runner.work_item_governance.pilot import (
    PILOT_SCOPE_MODE,
    PILOT_TABLE_COUNT_QUERIES,
    PILOT_TOOLS,
    canonical_path_digest,
)
from runner.work_item_governance.repository import SQLiteWorkItemLedger


PILOT_ZERO_FACT_TABLES = (
    "work_items",
    "task_versions",
    "execution_attempts",
    "attempt_events",
    "artifact_refs",
    "decision_records",
    "gate_events",
    "acceptance_manifests",
    "activation_leases",
    "activation_lease_events",
    "pilot_activation_leases",
    "pilot_activation_lease_events",
    "external_associations",
    "delivery_receipts",
    "blocker_events",
    "audit_events",
    "outbox_events",
    "inbox_events",
)


@dataclass(frozen=True)
class PilotBootstrapPaths:
    pilot_root: Path
    project_root: Path
    home: Path
    xdg_config_home: Path
    xdg_state_home: Path
    xdg_cache_home: Path
    xdg_data_home: Path
    registry_path: Path
    token_file: Path
    backup_path: Path

    def resolved(self) -> PilotBootstrapPaths:
        return PilotBootstrapPaths(**{field: Path(getattr(self, field)).expanduser().resolve() for field in self.__dataclass_fields__})


def _assert_private_path(root: Path, path: Path, field: str) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise WorkItemGovernanceError(
            "PILOT_BOOTSTRAP_PATH_OUTSIDE_ROOT",
            "Every Pilot private path must remain under the isolated Pilot root.",
            details={"field": field, "path": str(path)},
        ) from exc
    cursor = path
    while cursor != root.parent:
        if cursor.is_symlink():
            raise WorkItemGovernanceError(
                "PILOT_BOOTSTRAP_SYMLINK_DENIED",
                "Pilot bootstrap rejects symlinks in its private path boundary.",
                details={"field": field, "path": str(cursor)},
            )
        if cursor == root:
            break
        cursor = cursor.parent


def validate_pilot_bootstrap_paths(paths: PilotBootstrapPaths) -> PilotBootstrapPaths:
    value = paths.resolved()
    root = value.pilot_root
    if root.is_symlink():
        raise WorkItemGovernanceError("PILOT_BOOTSTRAP_SYMLINK_DENIED", "Pilot root cannot be a symlink.")
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(root, 0o700)
    for field in value.__dataclass_fields__:
        if field == "pilot_root":
            continue
        _assert_private_path(root, getattr(value, field), field)
    return value


def _assert_port_available(port: int) -> None:
    if isinstance(port, bool) or not isinstance(port, int) or not 1024 <= port <= 65535:
        raise WorkItemGovernanceError("PILOT_PORT_INVALID", "Pilot port must be a non-privileged TCP port.")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError as exc:
            raise WorkItemGovernanceError("PILOT_PORT_UNAVAILABLE", "Pilot loopback port is unavailable.") from exc


def bootstrap_fresh_pilot_ledger(
    *,
    paths: PilotBootstrapPaths,
    port: int,
    token_file_sha256: str,
    token_evidence_digest: str,
) -> dict[str, Any]:
    """Create the fresh Schema v6 fact domain and its generation-bound backup.

    This routine never starts a listener, claims a Lease, or enables authoritative
    transitions.  It is therefore safe to use while preparing a later exact
    authorization candidate.
    """

    value = validate_pilot_bootstrap_paths(paths)
    _assert_port_available(port)
    if (value.project_root / ".colameta" / "ledger" / "work-items.sqlite3").exists():
        raise WorkItemGovernanceError("PILOT_LEDGER_NOT_FRESH", "Pilot bootstrap refuses an existing Ledger.")
    for directory in (
        value.project_root,
        value.home,
        value.xdg_config_home,
        value.xdg_state_home,
        value.xdg_cache_home,
        value.xdg_data_home,
        value.registry_path.parent,
        value.token_file.parent,
        value.backup_path.parent,
    ):
        directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        os.chmod(directory, 0o700)
    settings = value.project_root / ".colameta" / "settings.json"
    settings.parent.mkdir(mode=0o700, exist_ok=True)
    settings.write_text(
        canonical_json(
            {
                "work_item_governance": {
                    "shadow_ledger_enabled": True,
                    "gate_mode": "shadow",
                    "authoritative_canary": False,
                    "scope_mode": PILOT_SCOPE_MODE,
                }
            }
        ),
        encoding="utf-8",
    )
    os.chmod(settings, 0o600)
    legacy = SQLiteWorkItemLedger(value.project_root, target_schema_version=5)
    legacy.initialize()
    migration = legacy.migrate_to_v6()
    ledger = SQLiteWorkItemLedger(value.project_root, target_schema_version=6)
    with ledger.write_transaction() as connection:
        signing_key = secrets.token_hex(32)
        for key, item in (
            ("preview_signing_key", signing_key),
            (AUTHORITATIVE_TOKEN_FILE_SHA256_META_KEY, token_file_sha256),
            (AUTHORITATIVE_TOKEN_EVIDENCE_DIGEST_META_KEY, token_evidence_digest),
        ):
            connection.execute(
                "INSERT INTO ledger_meta(key,value,updated_at) VALUES(?,?,strftime('%Y-%m-%dT%H:%M:%fZ','now'))",
                (key, item),
            )
    with ledger.read_connection() as connection:
        zero = {
            table: int(connection.execute(PILOT_TABLE_COUNT_QUERIES[table]).fetchone()[0])
            for table in PILOT_ZERO_FACT_TABLES
        }
    if any(zero.values()):
        raise WorkItemGovernanceError("PILOT_ZERO_FACT_BASELINE_FAILED", "Fresh Pilot Ledger contains domain or Lease facts.")
    backup = ledger.backup_to(value.backup_path)
    backup_sha256 = sha256_file(value.backup_path)
    backup_record = {
        "api": "sqlite3.Connection.backup",
        "path_digest": canonical_path_digest(value.backup_path),
        "sha256": backup_sha256,
        "database_generation": backup["database_generation"],
        "schema_version": backup["schema_version"],
        "integrity_check": backup["integrity_check"],
        "foreign_key_violations": backup["foreign_key_violations"],
        "mode": format(stat.S_IMODE(value.backup_path.stat().st_mode), "04o"),
    }
    backup_record["receipt_digest"] = canonical_sha256(backup_record)
    return {
        "schema_version": "wig_p3_pilot_fresh_ledger_bootstrap.v1",
        "scope_mode": PILOT_SCOPE_MODE,
        "project_root": str(value.project_root),
        "ledger_path": str(ledger.path),
        "ledger_path_digest": canonical_path_digest(ledger.path),
        "storage_migration": migration,
        "storage_migration_receipt_digest": canonical_sha256(migration),
        "database_generation": ledger.database_generation(),
        "zero_fact_baseline": zero,
        "preview_signing_key_preprovisioned": True,
        "token_file_path_digest": canonical_path_digest(value.token_file),
        "token_file_sha256": token_file_sha256,
        "token_evidence_digest": token_evidence_digest,
        "surface": {
            "exposure_profile": "authoritative_canary",
            "scope_mode": PILOT_SCOPE_MODE,
            "visible_tool_count": len(PILOT_TOOLS),
            "visible_tool_set_digest": canonical_sha256(list(PILOT_TOOLS)),
        },
        "runtime": {
            "bind_address": "127.0.0.1",
            "port": port,
            "listener_before_activation": False,
            "port_available": True,
            "gate_mode": "shadow",
            "authoritative": False,
        },
        "backup": backup_record,
    }
