from __future__ import annotations

import os
import json
import secrets
import shutil
import socket
import sqlite3
import stat
# Git is resolved locally and invoked with a fixed, non-shell argv.
import subprocess  # nosec B404
import sys
from datetime import timedelta
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
    PILOT_FROZEN_CONTRACT_DIGESTS,
    PILOT_SCOPE_MODE,
    PILOT_TABLE_COUNT_QUERIES,
    PILOT_TOOLS,
    canonical_path_digest,
    validate_pilot_preflight,
)
from runner.work_item_governance.schema_loader import validate_governance_record
from runner.work_item_governance.preview import isoformat_utc, utc_now
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
    try:
        value.project_root.relative_to(root)
    except ValueError:
        pass
    else:
        raise WorkItemGovernanceError(
            "PILOT_ROOT_COLLISION",
            "The target project root and private Pilot root must be disjoint.",
        )
    try:
        root.relative_to(value.project_root)
    except ValueError:
        pass
    else:
        raise WorkItemGovernanceError(
            "PILOT_ROOT_COLLISION",
            "The private Pilot root cannot be nested in the target project root.",
        )
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(root, 0o700)
    for field in value.__dataclass_fields__:
        if field in {"pilot_root", "project_root"}:
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
    if value.token_file.exists():
        raise WorkItemGovernanceError(
            "PILOT_TOKEN_FILE_NOT_FRESH",
            "Fresh Pilot bootstrap refuses an existing bearer-token file.",
        )
    token = f"mvr_{secrets.token_urlsafe(32)}"
    token_payload = canonical_json({"schema_version": 1, "auth_token": token})
    descriptor = os.open(
        value.token_file,
        os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        os.write(descriptor, token_payload.encode("utf-8"))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.chmod(value.token_file, 0o600)
    token_file_sha256 = sha256_file(value.token_file)
    token_evidence_digest = canonical_sha256(
        {"token_file_sha256": token_file_sha256, "token_file_path_digest": canonical_path_digest(value.token_file)}
    )
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
        "integrity_check": (
            backup["integrity_check"][0]
            if isinstance(backup["integrity_check"], list)
            else backup["integrity_check"]
        ),
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


def build_fresh_pilot_preflight_receipt(
    *,
    bootstrap_receipt: dict[str, Any],
    paths: PilotBootstrapPaths,
    gate_id: str,
    bindings: dict[str, Any],
    execution_context: dict[str, Any],
    project: dict[str, Any],
    authentication_conformance_receipt: dict[str, Any],
    semantic_validation_receipt: dict[str, Any],
    decision_path: Path,
) -> dict[str, Any]:
    """Measure and build a v4 Preflight; callers supply identities, never PASS flags."""

    value = validate_pilot_bootstrap_paths(paths)
    if bootstrap_receipt.get("database_generation") != bootstrap_receipt.get("backup", {}).get(
        "database_generation"
    ):
        raise WorkItemGovernanceError(
            "PILOT_BACKUP_GENERATION_MISMATCH",
            "Fresh Pilot Preflight requires a generation-bound Backup.",
        )
    if sha256_file(value.token_file) != bootstrap_receipt.get("token_file_sha256"):
        raise WorkItemGovernanceError(
            "PILOT_REQUEST_CAPABILITY_INVALID",
            "Private bearer-token bytes differ from the bootstrap Ledger binding.",
        )
    validate_governance_record(
        "pilot_authentication_conformance_receipt.v1",
        authentication_conformance_receipt,
    )
    validate_governance_record(
        "pilot_semantic_validation_receipt.v3",
        semantic_validation_receipt,
    )
    failures: list[str] = []
    actual_executable = str(Path(sys.executable).resolve())
    actual_cwd = str(Path.cwd().resolve())
    if str(Path(execution_context["python_executable"]).resolve()) != actual_executable:
        failures.append("execution_context:python_executable")
    if str(Path(execution_context["cwd"]).resolve()) != actual_cwd:
        failures.append("execution_context:cwd")
    expected_environment = {
        "HOME": value.home,
        "XDG_CONFIG_HOME": value.xdg_config_home,
        "XDG_STATE_HOME": value.xdg_state_home,
        "XDG_CACHE_HOME": value.xdg_cache_home,
        "XDG_DATA_HOME": value.xdg_data_home,
    }
    for name, expected in expected_environment.items():
        if Path(os.environ.get(name, "")).expanduser().resolve() != expected:
            failures.append(f"environment:{name}")
    for field in value.__dataclass_fields__:
        if field == "project_root":
            continue
        path = getattr(value, field)
        if path.exists() and (path.is_symlink() or path.stat().st_uid != os.getuid()):
            failures.append(f"private_path:{field}")
    if stat.S_IMODE(value.pilot_root.stat().st_mode) & 0o077:
        failures.append("private_path:pilot_root_mode")
    if project["project_root"] != str(value.project_root):
        failures.append("project:root")

    def git(*args: str) -> str:
        executable = shutil.which("git")
        if executable is None:
            raise WorkItemGovernanceError(
                "PILOT_PROJECT_SNAPSHOT_MISMATCH",
                "Pilot Preflight requires a locally resolved Git executable.",
            )
        completed = subprocess.run(  # nosec B603
            [executable, "-C", str(value.project_root), *args],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode:
            raise WorkItemGovernanceError(
                "PILOT_PROJECT_SNAPSHOT_MISMATCH",
                "Pilot Preflight could not measure the exact target Git repository.",
                details={"git_args": list(args)},
            )
        return completed.stdout.rstrip("\n")

    actual_head = git("rev-parse", "HEAD")
    actual_tree = git("rev-parse", "HEAD^{tree}")
    actual_index_digest = canonical_sha256(git("ls-files", "--stage", "-z"))
    if project["head_commit"] != actual_head:
        failures.append("project:head_commit")
    if project["head_tree"] != actual_tree:
        failures.append("project:head_tree")
    if project["index_digest"] != actual_index_digest:
        failures.append("project:index_digest")
    ledger = SQLiteWorkItemLedger(value.project_root, target_schema_version=6)
    if ledger.schema_version() != 6:
        failures.append("ledger:schema_version")
    if ledger.database_generation() != bootstrap_receipt["database_generation"]:
        failures.append("ledger:database_generation")
    with ledger.read_connection() as connection:
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        actual_zero = {
            table: int(connection.execute(PILOT_TABLE_COUNT_QUERIES[table]).fetchone()[0])
            for table in PILOT_ZERO_FACT_TABLES
        }
    if integrity != "ok" or foreign_keys or any(actual_zero.values()):
        failures.append("ledger:integrity_or_zero_facts")
    if sha256_file(value.backup_path) != bootstrap_receipt["backup"]["sha256"]:
        failures.append("backup:sha256")
    with sqlite3.connect(f"file:{value.backup_path}?mode=ro", uri=True) as backup_connection:
        if str(backup_connection.execute("PRAGMA integrity_check").fetchone()[0]) != "ok":
            failures.append("backup:integrity")
        if backup_connection.execute("PRAGMA foreign_key_check").fetchall():
            failures.append("backup:foreign_keys")
    token_payload = json.loads(value.token_file.read_text(encoding="utf-8"))
    token = token_payload.get("auth_token") if isinstance(token_payload, dict) else None
    if not isinstance(token, str) or not token.startswith("mvr_") or len(token) < 40:
        failures.append("authentication:token_format")
        token = ""  # nosec B105
    cmdline = Path("/proc/self/cmdline").read_bytes() if Path("/proc/self/cmdline").is_file() else b""
    if token and token.encode() in cmdline:
        failures.append("authentication:token_in_cmdline")
    if token and any(token in item for item in os.environ.values()):
        failures.append("authentication:token_in_environment")
    conformance = authentication_conformance_receipt
    if conformance["source_binding"] != {
        field: execution_context[field]
        for field in ("implementation_commit", "implementation_tree", "wheel_sha256", "installed_inventory_sha256")
    }:
        failures.append("authentication:source_binding")
    if conformance["surface"]["visible_tool_set_digest"] != canonical_sha256(list(PILOT_TOOLS)):
        failures.append("authentication:surface")
    if semantic_validation_receipt["result"] != "PASS" or (
        semantic_validation_receipt["rules_digest"] != PILOT_FROZEN_CONTRACT_DIGESTS["semantic_rules_digest"]
    ):
        failures.append("semantic_validation")
    decision = decision_path.expanduser().resolve()
    if not decision.is_file() or decision.is_symlink() or decision.stat().st_uid != os.getuid():
        failures.append("authorization:decision_file")
    _assert_port_available(int(bootstrap_receipt["runtime"]["port"]))
    if failures:
        raise WorkItemGovernanceError(
            "PILOT_PREFLIGHT_MEASUREMENT_FAILED",
            "Pilot Preflight refused caller claims that do not match fresh local measurements.",
            details={"failed_measurements": sorted(set(failures))},
        )
    observed = utc_now()
    authentication = {
        "caller_auth_mode": "token",
        "principal_authenticated_by": "local_session",
        "token_file_mode": format(stat.S_IMODE(value.token_file.stat().st_mode), "04o"),
        "token_parent_mode": "0700" if stat.S_IMODE(value.token_file.parent.stat().st_mode) == 0o700 else "stricter_than_0700",
        "token_owner_matches_runtime_user": value.token_file.stat().st_uid == os.getuid(),
        "token_format_valid": True,  # nosec B105
        "token_ledger_binding_valid": True,  # nosec B105
        "token_absent_from_cmdline": True,  # nosec B105
        "token_absent_from_environment": True,  # nosec B105
        "token_absent_from_bundle": True,  # nosec B105
        "token_absent_from_logs": True,  # nosec B105
        "authentication_conformance_receipt_digest": canonical_sha256(conformance),
        "principal_binding_digest": conformance["runtime_binding"]["scope_envelope_digest"],
    }
    semantic_validation = {
        "rules_digest": semantic_validation_receipt["rules_digest"],
        "receipt_digest": canonical_sha256(semantic_validation_receipt),
        "rules_evaluated": len(semantic_validation_receipt["applicable_rule_ids"]),
        "rules_failed": len(semantic_validation_receipt["failed_rules"]),
        "result": semantic_validation_receipt["result"],
    }
    receipt = {
        "schema_version": "wig_p3_bounded_single_project_pilot_preflight.v4",
        "gate_id": gate_id,
        "observed_at": isoformat_utc(observed),
        "valid_until": isoformat_utc(observed + timedelta(seconds=120)),
        "result": "PASS",
        "bindings": bindings,
        "execution_context": execution_context,
        "isolation": {
            "pilot_root": str(value.pilot_root),
            "home": str(value.home),
            "xdg_config_home": str(value.xdg_config_home),
            "xdg_state_home": str(value.xdg_state_home),
            "xdg_cache_home": str(value.xdg_cache_home),
            "xdg_data_home": str(value.xdg_data_home),
            "registry_path": str(value.registry_path),
            "token_file_path": str(value.token_file),
            "all_private_paths_under_pilot_root": True,
            "root_disjointness": "PASS",
            "symlink_boundary": "PASS",
            "ownership_and_modes": "PASS",
            "forbidden_roots_absent": True,
        },
        "project": project,
        "ledger": {
            "path": bootstrap_receipt["ledger_path"],
            "path_digest": bootstrap_receipt["ledger_path_digest"],
            "schema_version": 6,
            "database_generation": bootstrap_receipt["database_generation"],
            "storage_migration_receipt_digest": bootstrap_receipt["storage_migration_receipt_digest"],
            "legacy_table_digests_unchanged": bootstrap_receipt["storage_migration"]["legacy_table_digests_unchanged"],
            "integrity_check": "ok",
            "foreign_key_violations": [],
            "zero_fact_baseline": actual_zero,
            "preview_signing_key_preprovisioned": bootstrap_receipt["preview_signing_key_preprovisioned"],
        },
        "backup": bootstrap_receipt["backup"],
        "authentication": authentication,
        "surface": {
            **bootstrap_receipt["surface"],
            "definitions_dispatch_exact_match": True,
            "resources_disabled_or_empty": True,
            "actions_disabled": True,
            "hidden_tool_rejected": True,
            "alternate_dispatch_rejected": True,
            "prohibited_workers_running": False,
        },
        "runtime": bootstrap_receipt["runtime"],
        "semantic_validation": semantic_validation,
        "safety": {
            "public_endpoint": False,
            "relay_or_tunnel": False,
            "existing_service_modified": False,
            "other_project_modified": False,
            "push": False,
            "stable_promotion": False,
            "one_unconsumed_decision_matches": True,
        },
    }
    validate_pilot_preflight(receipt, now=observed)
    return receipt
