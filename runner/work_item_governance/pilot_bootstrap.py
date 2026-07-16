from __future__ import annotations

import os
import json
import secrets
import socket
import sqlite3
import stat

# Git is resolved locally and invoked with a fixed, non-shell argv.
import subprocess  # nosec B404
import sys
from datetime import timedelta
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
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
    PILOT_SOURCE_BINDING_FIELDS,
    PILOT_TABLE_COUNT_QUERIES,
    PILOT_TOOLS,
    build_pilot_execution_context,
    build_pilot_ledger_state,
    canonical_path_digest,
    validate_pilot_preflight,
)
from runner.work_item_governance.pilot_snapshot import PilotConformanceLedgerSnapshot
from runner.work_item_governance.schema_loader import validate_governance_record
from runner.work_item_governance.source_binding import (
    SOURCE_ARTIFACT_EVIDENCE_DIGEST_META_KEY,
    SOURCE_CHECKOUT_PATH_META_KEY,
    SOURCE_WHEEL_PATH_META_KEY,
    seal_runtime_source_attestation,
    verify_runtime_source_artifacts,
)
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
    "pilot_authorization_facts",
    "pilot_authorization_claims",
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
        return PilotBootstrapPaths(
            **{field: Path(getattr(self, field)).expanduser().resolve() for field in self.__dataclass_fields__}
        )


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


def _canonical_relative_manifest_path(value: str) -> str:
    lexical = PurePosixPath(value)
    canonical = lexical.as_posix()
    if not lexical.parts or lexical.is_absolute() or ".." in lexical.parts or "\\" in value or canonical != value:
        raise WorkItemGovernanceError(
            "PILOT_PROJECT_SNAPSHOT_MISMATCH",
            "Path manifest entries must be canonical relative POSIX paths.",
        )
    return canonical


def _measure_path_manifests(
    project_root: Path,
    manifests: dict[str, Any],
) -> dict[str, str]:
    expected_keys = {"protected", "allowed_read", "allowed_write"}
    if set(manifests) != expected_keys:
        raise WorkItemGovernanceError(
            "PILOT_PROJECT_SNAPSHOT_MISMATCH",
            "Pilot project path manifests require exact protected/read/write keysets.",
        )
    measured: dict[str, str] = {}
    for kind in sorted(expected_keys):
        value = manifests[kind]
        if not isinstance(value, dict) or set(value) != {"paths"} or not isinstance(value["paths"], list):
            raise WorkItemGovernanceError(
                "PILOT_PROJECT_SNAPSHOT_MISMATCH",
                "Pilot project path manifests must contain one explicit paths list.",
            )
        normalized: list[Any] = []
        seen: set[str] = set()
        for item in value["paths"]:
            if kind == "protected":
                if not isinstance(item, dict) or set(item) != {"path", "sha256"}:
                    raise WorkItemGovernanceError(
                        "PILOT_PROJECT_SNAPSHOT_MISMATCH",
                        "Protected path entries require path and sha256.",
                    )
                relative = item["path"]
            else:
                if not isinstance(item, str):
                    raise WorkItemGovernanceError(
                        "PILOT_PROJECT_SNAPSHOT_MISMATCH",
                        "Allowed path entries must be relative strings.",
                    )
                relative = item
            if not isinstance(relative, str) or not relative or relative in seen:
                raise WorkItemGovernanceError(
                    "PILOT_PROJECT_SNAPSHOT_MISMATCH", "Path manifest entries must be unique."
                )
            relative = _canonical_relative_manifest_path(relative)
            candidate = project_root / relative
            try:
                candidate.resolve(strict=False).relative_to(project_root)
            except ValueError as exc:
                raise WorkItemGovernanceError(
                    "PILOT_PROJECT_SNAPSHOT_MISMATCH",
                    "Path manifest entry escapes the target project.",
                ) from exc
            if candidate.is_symlink():
                raise WorkItemGovernanceError(
                    "PILOT_PROJECT_SNAPSHOT_MISMATCH", "Path manifest symlinks are forbidden."
                )
            seen.add(relative)
            if kind == "protected":
                if not candidate.is_file() or sha256_file(candidate) != item["sha256"]:
                    raise WorkItemGovernanceError(
                        "PILOT_PROJECT_SNAPSHOT_MISMATCH",
                        "Protected path bytes differ from their exact manifest.",
                    )
                normalized.append({"path": relative, "sha256": item["sha256"]})
            else:
                normalized.append(relative)
        normalized.sort(key=lambda item: item["path"] if isinstance(item, dict) else item)
        measured[kind] = canonical_sha256({"paths": normalized})
    return measured


def _private_evidence_file_clean(*, root: Path, candidate: Path, token_bytes: bytes) -> bool:
    """Read one governed evidence file without following or racing a symlink."""

    try:
        observed = os.lstat(candidate)
    except OSError:
        return False
    if (
        not stat.S_ISREG(observed.st_mode)
        or observed.st_uid != os.getuid()
        or stat.S_IMODE(observed.st_mode) & 0o077
        or observed.st_size > 16 * 1024 * 1024
    ):
        return False
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(candidate, flags)
    except OSError:
        return False
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or (before.st_dev, before.st_ino) != (observed.st_dev, observed.st_ino)
            or before.st_uid != os.getuid()
            or stat.S_IMODE(before.st_mode) & 0o077
            or before.st_size > 16 * 1024 * 1024
        ):
            return False
        payload = bytearray()
        while chunk := os.read(descriptor, 1024 * 1024):
            payload.extend(chunk)
        after = os.fstat(descriptor)
        stable_fields = ("st_dev", "st_ino", "st_mode", "st_uid", "st_size", "st_mtime_ns", "st_ctime_ns")
        if any(getattr(before, field) != getattr(after, field) for field in stable_fields):
            return False
        return token_bytes not in payload
    finally:
        os.close(descriptor)


def _token_absent_from_evidence_root(*, root: Path, excluded: set[Path], token_bytes: bytes) -> bool:
    """Scan one explicit private evidence boundary with stable no-follow reads."""

    try:
        root_observed = os.lstat(root)
    except OSError:
        return False
    if (
        not stat.S_ISDIR(root_observed.st_mode)
        or root_observed.st_uid != os.getuid()
        or stat.S_IMODE(root_observed.st_mode) & 0o077
    ):
        return False
    for current, directory_names, file_names in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        try:
            current_observed = os.lstat(current_path)
        except OSError:
            return False
        if (
            not stat.S_ISDIR(current_observed.st_mode)
            or current_observed.st_uid != os.getuid()
            or stat.S_IMODE(current_observed.st_mode) & 0o077
        ):
            return False
        for name in directory_names:
            candidate = current_path / name
            try:
                directory_observed = os.lstat(candidate)
            except OSError:
                return False
            if (
                not stat.S_ISDIR(directory_observed.st_mode)
                or directory_observed.st_uid != os.getuid()
                or stat.S_IMODE(directory_observed.st_mode) & 0o077
            ):
                return False
        for name in file_names:
            candidate = current_path / name
            if candidate in excluded:
                continue
            if not _private_evidence_file_clean(root=root, candidate=candidate, token_bytes=token_bytes):
                return False
    return True


def _token_absent_from_private_evidence(paths: PilotBootstrapPaths, token: str) -> dict[str, bool]:
    """Measure governed bundle and log roots without traversing runtime/build trees."""

    token_bytes = token.encode("utf-8")
    excluded = {paths.backup_path}
    bundle_roots = (paths.backup_path.parent, paths.xdg_data_home)
    log_roots = (paths.xdg_state_home,)
    return {
        "bundle": all(
            _token_absent_from_evidence_root(root=root, excluded=excluded, token_bytes=token_bytes)
            for root in bundle_roots
        ),
        "logs": all(
            _token_absent_from_evidence_root(root=root, excluded=excluded, token_bytes=token_bytes)
            for root in log_roots
        ),
    }


def _measure_restricted_surface(conformance: dict[str, Any]) -> dict[str, Any]:
    """Cross-bind the frozen core allowlist to independently produced transport evidence."""

    names = PILOT_TOOLS
    evidence = conformance["surface"]
    exact = (
        len(names) == len(set(names))
        and conformance["result"] == "PASS"
        and evidence["visible_tool_set_digest"] == canonical_sha256(list(names))
    )
    return {
        "exposure_profile": "authoritative_canary",
        "scope_mode": PILOT_SCOPE_MODE,
        "visible_tool_count": len(names),
        "visible_tool_set_digest": canonical_sha256(list(names)),
        "definitions_dispatch_exact_match": exact and evidence["definitions_dispatch_exact_match"],
        "resources_disabled_or_empty": exact and evidence["resources_disabled_or_empty"],
        "actions_disabled": exact and evidence["actions_disabled"],
        "hidden_tool_rejected": exact and evidence["hidden_tool_rejected"],
        "alternate_dispatch_rejected": exact and evidence["alternate_dispatch_rejected"],
        "prohibited_workers_running": (not exact) or evidence["prohibited_workers_running"],
    }


def bootstrap_fresh_pilot_ledger(
    *,
    paths: PilotBootstrapPaths,
    port: int,
    source_checkout: Path,
    wheel_artifact: Path,
) -> dict[str, Any]:
    """Create the fresh Schema v6 fact domain and its generation-bound backup.

    This routine never starts a listener, claims a Lease, or enables authoritative
    transitions.  It is therefore safe to use while preparing a later exact
    authorization candidate.
    """

    value = validate_pilot_bootstrap_paths(paths)
    _assert_port_available(port)
    source_attestation = verify_runtime_source_artifacts(
        checkout_root=source_checkout,
        wheel_artifact=wheel_artifact,
    )
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
    migration_v6 = legacy.migrate_to_v6()
    migration_v7 = SQLiteWorkItemLedger(value.project_root, target_schema_version=6).migrate_to_v7()
    migration = {
        "schema_version": "wig_p3_pilot_storage_migration_chain.v1",
        "from_schema_version": 5,
        "to_schema_version": 7,
        "transaction_mode": "TWO_EXPLICIT_BEGIN_IMMEDIATE_STEPS",
        "legacy_table_digests_unchanged": migration_v6["legacy_table_digests_unchanged"],
        "steps": [migration_v6, migration_v7],
    }
    ledger = SQLiteWorkItemLedger(value.project_root, target_schema_version=7)
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
        seal_runtime_source_attestation(
            connection,
            source_attestation,
            updated_at=isoformat_utc(utc_now()),
        )
    with ledger.read_connection() as connection:
        zero = {
            table: int(connection.execute(PILOT_TABLE_COUNT_QUERIES[table]).fetchone()[0])
            for table in PILOT_ZERO_FACT_TABLES
        }
    if any(zero.values()):
        raise WorkItemGovernanceError(
            "PILOT_ZERO_FACT_BASELINE_FAILED", "Fresh Pilot Ledger contains domain or Lease facts."
        )
    backup = ledger.backup_to(value.backup_path)
    backup_sha256 = sha256_file(value.backup_path)
    backup_record = {
        "api": "sqlite3.Connection.backup",
        "path_digest": canonical_path_digest(value.backup_path),
        "sha256": backup_sha256,
        "database_generation": backup["database_generation"],
        "schema_version": backup["schema_version"],
        "integrity_check": (
            backup["integrity_check"][0] if isinstance(backup["integrity_check"], list) else backup["integrity_check"]
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
        "source_binding": {
            **source_attestation.source_binding,
            "installed_inventory_sha256": source_attestation.file_manifest_digest,
            "durable_artifact_evidence_digest": source_attestation.evidence_digest,
            "durable_checkout_path_digest": source_attestation.public_evidence()["checkout_path_digest"],
            "durable_wheel_path_digest": source_attestation.public_evidence()["wheel_path_digest"],
        },
        "source_artifact_evidence_digest": source_attestation.evidence_digest,
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
    source_checkout: Path,
    wheel_artifact: Path,
    principal_binding: dict[str, Any],
    project_path_manifests: dict[str, Any],
    ledger_snapshot: PilotConformanceLedgerSnapshot,
) -> dict[str, Any]:
    """Measure and build a v4 Preflight; callers supply identities, never PASS flags."""

    value = validate_pilot_bootstrap_paths(paths)
    if bootstrap_receipt.get("database_generation") != bootstrap_receipt.get("backup", {}).get("database_generation"):
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
    if bindings.get("authentication_conformance_receipt_digest") != canonical_sha256(
        authentication_conformance_receipt
    ):
        failures.append("authentication:authorization_receipt_digest")
    ledger_snapshot.require_bound_to(value.project_root)
    source_attestation = verify_runtime_source_artifacts(
        checkout_root=source_checkout,
        wheel_artifact=wheel_artifact,
    )
    source_public_evidence = source_attestation.public_evidence()
    measured_context = build_pilot_execution_context(
        source_binding={
            "implementation_commit": source_attestation.source_binding["implementation_commit"],
            "implementation_tree": source_attestation.source_binding["implementation_tree"],
            "wheel_sha256": source_attestation.source_binding["wheel_sha256"],
            "installed_inventory_sha256": source_attestation.file_manifest_digest,
            "durable_artifact_evidence_digest": source_public_evidence["artifact_evidence_digest"],
            "durable_checkout_path_digest": source_public_evidence["checkout_path_digest"],
            "durable_wheel_path_digest": source_public_evidence["wheel_path_digest"],
        },
        python_executable=sys.executable,
        cwd=Path.cwd(),
    )
    if execution_context != measured_context:
        failures.append("execution_context:measured_runtime_artifacts")
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

    executable = next((item for item in (Path("/usr/bin/git"), Path("/bin/git")) if item.is_file()), None)
    if executable is None:
        raise WorkItemGovernanceError(
            "PILOT_PROJECT_SNAPSHOT_MISMATCH",
            "Pilot Preflight requires a root-owned system Git executable.",
        )
    git_environment = {
        "HOME": str(value.home),
        "PATH": "/usr/bin:/bin",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "LC_ALL": "C",
    }

    def git_process(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # nosec B603
            [
                executable.as_posix(),
                "--no-pager",
                "--no-replace-objects",
                "-c",
                "core.fsmonitor=false",
                "-c",
                "core.untrackedCache=false",
                "-C",
                str(value.project_root),
                *args,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
            env=git_environment,
        )

    def git(*args: str) -> str:
        completed = git_process(*args)
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
    tracked_changes_digest = canonical_sha256(git("diff", "--name-status", "-z", "HEAD"))
    untracked_changes_digest = canonical_sha256(git("ls-files", "--others", "--exclude-standard", "-z"))
    manifest_digests = _measure_path_manifests(value.project_root, project_path_manifests)
    ledger_relative = ".colameta/ledger/work-items.sqlite3"
    ledger_ignored = git_process("check-ignore", "--quiet", "--", ledger_relative).returncode == 0
    ledger_tracked = git_process("ls-files", "--error-unmatch", "--", ledger_relative).returncode == 0
    ledger_staged = bool(git("diff", "--cached", "--name-only", "--", ledger_relative))
    registry_payload = json.loads(value.registry_path.read_text(encoding="utf-8"))
    registry_projects = registry_payload.get("projects") if isinstance(registry_payload, dict) else None
    registry_valid = (
        isinstance(registry_projects, list)
        and len(registry_projects) == 1
        and isinstance(registry_projects[0], dict)
        and registry_projects[0].get("project_id") == project["project_id"]
        and Path(str(registry_projects[0].get("project_root", ""))).resolve() == value.project_root
    )
    if not registry_valid:
        failures.append("project:registry")
    snapshot_record = {
        "project_id": project["project_id"],
        "project_root_path_digest": canonical_path_digest(value.project_root),
        "head_commit": actual_head,
        "head_tree": actual_tree,
        "tracked_changes_digest": tracked_changes_digest,
        "untracked_changes_digest": untracked_changes_digest,
        "index_digest": actual_index_digest,
        "protected_assets_digest": manifest_digests["protected"],
        "protected_path_manifest_digest": manifest_digests["protected"],
        "allowed_read_path_manifest_digest": manifest_digests["allowed_read"],
        "allowed_write_path_manifest_digest": manifest_digests["allowed_write"],
    }
    measured_project = {
        "project_id": project["project_id"],
        "project_root": str(value.project_root),
        "registry_project_count": 1,
        "snapshot_digest": canonical_sha256(snapshot_record),
        "head_commit": actual_head,
        "head_tree": actual_tree,
        "index_digest": actual_index_digest,
        "protected_path_manifest_digest": manifest_digests["protected"],
        "allowed_read_path_manifest_digest": manifest_digests["allowed_read"],
        "allowed_write_path_manifest_digest": manifest_digests["allowed_write"],
        "ledger_git_ignored": ledger_ignored,
        "ledger_not_tracked": not ledger_tracked,
        "ledger_not_staged": not ledger_staged,
        "root_override_disabled": True,
    }
    if project != measured_project:
        failures.append("project:measured_snapshot")
    ledger_snapshot.require_bound_to(value.project_root)
    ledger = SQLiteWorkItemLedger(ledger_snapshot.project_root, target_schema_version=7)
    if ledger.schema_version() != 7:
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
        metadata_rows = connection.execute(
            "SELECT key,value FROM ledger_meta WHERE key IN (?,?,?,?,?)",
            (
                AUTHORITATIVE_TOKEN_FILE_SHA256_META_KEY,
                AUTHORITATIVE_TOKEN_EVIDENCE_DIGEST_META_KEY,
                SOURCE_CHECKOUT_PATH_META_KEY,
                SOURCE_WHEEL_PATH_META_KEY,
                SOURCE_ARTIFACT_EVIDENCE_DIGEST_META_KEY,
            ),
        ).fetchall()
    ledger_metadata = {str(row["key"]): str(row["value"]) for row in metadata_rows}
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
    token_format_valid = isinstance(token, str) and token.startswith("mvr_") and len(token) >= 40
    if not token_format_valid:
        failures.append("authentication:token_format")
        token = ""  # nosec B105
    cmdline = Path("/proc/self/cmdline").read_bytes() if Path("/proc/self/cmdline").is_file() else b""
    token_absent_from_cmdline = bool(token) and token.encode() not in cmdline
    token_absent_from_environment = bool(token) and all(token not in item for item in os.environ.values())
    if not token_absent_from_cmdline:
        failures.append("authentication:token_in_cmdline")
    if not token_absent_from_environment:
        failures.append("authentication:token_in_environment")
    token_mode = stat.S_IMODE(value.token_file.stat().st_mode)
    token_parent_mode = stat.S_IMODE(value.token_file.parent.stat().st_mode)
    token_owner_matches = value.token_file.stat().st_uid == os.getuid()
    if token_mode != 0o600 or token_parent_mode & 0o077 or not token_owner_matches:
        failures.append("authentication:token_permissions")
    token_file_sha256 = sha256_file(value.token_file)
    expected_token_evidence = canonical_sha256(
        {
            "token_file_sha256": token_file_sha256,
            "token_file_path_digest": canonical_path_digest(value.token_file),
        }
    )
    expected_source_metadata = {
        AUTHORITATIVE_TOKEN_FILE_SHA256_META_KEY: token_file_sha256,
        AUTHORITATIVE_TOKEN_EVIDENCE_DIGEST_META_KEY: expected_token_evidence,
        SOURCE_CHECKOUT_PATH_META_KEY: source_attestation.checkout_root.as_posix(),
        SOURCE_WHEEL_PATH_META_KEY: source_attestation.wheel_artifact.as_posix(),
        SOURCE_ARTIFACT_EVIDENCE_DIGEST_META_KEY: source_attestation.evidence_digest,
    }
    if ledger_metadata != expected_source_metadata:
        failures.append("ledger:token_or_source_artifact_binding")
    private_evidence = (
        _token_absent_from_private_evidence(value, token) if token else {"bundle": False, "logs": False}
    )
    if not all(private_evidence.values()):
        failures.append("authentication:token_in_private_evidence")
    conformance = authentication_conformance_receipt
    if conformance["source_binding"] != {field: execution_context[field] for field in PILOT_SOURCE_BINDING_FIELDS}:
        failures.append("authentication:source_binding")
    if conformance["surface"]["visible_tool_set_digest"] != canonical_sha256(list(PILOT_TOOLS)):
        failures.append("authentication:surface")
    ledger_state = build_pilot_ledger_state(
        path_digest=ledger_snapshot.source_ledger_path_digest,
        schema_version=ledger.schema_version(),
        database_generation=ledger.database_generation(),
        zero_fact_baseline=actual_zero,
        integrity_check=integrity,
        foreign_key_violations=foreign_keys,
        token_evidence_digest=expected_token_evidence,
        source_artifact_evidence_digest=source_attestation.evidence_digest,
    )
    expected_conformance_runtime = {
        "runtime_binding_digest": measured_context["runtime_binding_digest"],
        "scope_envelope_digest": bindings["scope_envelope_digest"],
        "ledger_state_digest": canonical_sha256(ledger_state),
        "token_file_path_digest": canonical_path_digest(value.token_file),
    }
    if conformance["runtime_binding"] != expected_conformance_runtime:
        failures.append("authentication:runtime_binding")
    if semantic_validation_receipt["result"] != "PASS" or (
        semantic_validation_receipt["rules_digest"] != PILOT_FROZEN_CONTRACT_DIGESTS["semantic_rules_digest"]
    ):
        failures.append("semantic_validation")
    expected_semantic_bindings = {
        "candidate_manifest_sha256": bindings["candidate_manifest_sha256"],
        "scope_envelope_digest": bindings["scope_envelope_digest"],
        "storage_schema_contract_digest": bindings["storage_schema_contract_digest"],
        "fact_reconciliation_contract_digest": bindings["fact_reconciliation_contract_digest"],
        "authorization_digest": bindings["authorization_digest"],
        "project_snapshot_digest": measured_project["snapshot_digest"],
        "runtime_binding_digest": measured_context["runtime_binding_digest"],
        "ledger_state_digest": canonical_sha256(ledger_state),
    }
    if semantic_validation_receipt["input_bindings"] != expected_semantic_bindings:
        failures.append("semantic_validation:input_bindings")
    decision = decision_path.expanduser().resolve()
    if (
        not decision.is_file()
        or decision.is_symlink()
        or decision.stat().st_uid != os.getuid()
        or stat.S_IMODE(decision.stat().st_mode) & 0o077
        or canonical_sha256(json.loads(decision.read_text(encoding="utf-8"))) != bindings["authorization_digest"]
    ):
        failures.append("authorization:decision_file")
    _assert_port_available(int(bootstrap_receipt["runtime"]["port"]))
    measured_surface = _measure_restricted_surface(conformance)
    expected_surface = {
        **bootstrap_receipt["surface"],
        "definitions_dispatch_exact_match": True,
        "resources_disabled_or_empty": True,
        "actions_disabled": True,
        "hidden_tool_rejected": True,
        "alternate_dispatch_rejected": True,
        "prohibited_workers_running": False,
    }
    conformance_surface_identity = {
        field: conformance["surface"][field]
        for field in ("exposure_profile", "scope_mode", "visible_tool_count", "visible_tool_set_digest")
    }
    if measured_surface != expected_surface or conformance_surface_identity != bootstrap_receipt["surface"]:
        failures.append("surface:measured_contract")
    if failures:
        raise WorkItemGovernanceError(
            "PILOT_PREFLIGHT_MEASUREMENT_FAILED",
            "Pilot Preflight refused caller claims that do not match fresh local measurements.",
            details={"failed_measurements": sorted(set(failures))},
        )
    ledger_snapshot.require_bound_to(value.project_root)
    observed = utc_now()
    decision_matches = (
        canonical_sha256(json.loads(decision.read_text(encoding="utf-8"))) == bindings["authorization_digest"]
    )
    authentication = {
        "caller_auth_mode": "token",
        "principal_authenticated_by": "local_session",
        "token_file_mode": format(token_mode, "04o"),
        "token_parent_mode": "0700" if token_parent_mode == 0o700 else "stricter_than_0700",
        "token_owner_matches_runtime_user": token_owner_matches,
        "token_format_valid": token_format_valid,  # nosec B105
        "token_ledger_binding_valid": ledger_metadata == expected_source_metadata,  # nosec B105
        "token_absent_from_cmdline": token_absent_from_cmdline,  # nosec B105
        "token_absent_from_environment": token_absent_from_environment,  # nosec B105
        "token_absent_from_bundle": private_evidence["bundle"],  # nosec B105
        "token_absent_from_logs": private_evidence["logs"],  # nosec B105
        "authentication_conformance_receipt_digest": canonical_sha256(conformance),
        "principal_binding_digest": canonical_sha256(principal_binding),
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
        "execution_context": measured_context,
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
        "project": measured_project,
        "ledger": {
            "path": bootstrap_receipt["ledger_path"],
            "path_digest": bootstrap_receipt["ledger_path_digest"],
            "schema_version": 7,
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
        "surface": measured_surface,
        "runtime": bootstrap_receipt["runtime"],
        "semantic_validation": semantic_validation,
        "safety": {
            "public_endpoint": conformance["safety"]["public_endpoint"],
            "relay_or_tunnel": conformance["safety"]["relay_or_tunnel"],
            "existing_service_modified": conformance["safety"]["existing_service_modified"],
            "other_project_modified": conformance["safety"]["other_project_modified"],
            "push": conformance["safety"]["push"],
            "stable_promotion": conformance["safety"]["stable_promotion"],
            "one_unconsumed_decision_matches": decision_matches,
        },
    }
    validate_pilot_preflight(receipt, now=observed)
    return receipt
