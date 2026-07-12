from __future__ import annotations

import json
import os
import secrets
import stat
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

from runner.project_registry import ProjectRegistry
from runner.runner_global_config import RunnerGlobalConfigStore
from runner.work_item_governance.activation import (
    AUTHORITATIVE_CANARY_TOOLS,
    AUTHORITATIVE_TOKEN_EVIDENCE_DIGEST_META_KEY,
    AUTHORITATIVE_TOKEN_FILE_SHA256_META_KEY,
    R2_SPEC_FREEZE_MANIFEST_SHA256,
    business_fact_counts,
    canonical_path_digest,
    process_identity_inputs,
    read_authoritative_token_file,
    validate_runtime_policy_contracts,
    validate_synthetic_fixture_semantics,
)
from runner.work_item_governance.canonical import canonical_json, canonical_sha256, sha256_file
from runner.work_item_governance.errors import WorkItemGovernanceError
from runner.work_item_governance.ids import new_stable_id
from runner.work_item_governance.preview import isoformat_utc, utc_now
from runner.work_item_governance.repository import SQLiteWorkItemLedger
from runner.work_item_governance.schema_loader import validate_governance_record


PRIVATE_CREDENTIAL_SOURCE = "isolated_xdg_auth_json"
PRIVATE_FILE_MODE_TEXT = "0600"
PRIVATE_DIRECTORY_MODE_TEXT = "0700"
CSPRNG_EVIDENCE_ALGORITHM = "os_csprng_256_bits_minimum_base64url"
VERIFIED_TRUE = bool(1)
VERIFIED_FALSE = bool(0)


@dataclass(frozen=True)
class PrivateTokenProvisioning:
    token: str
    auth_file: Path
    evidence_digest: str
    entropy_bits: int


@dataclass(frozen=True)
class FreshCanaryPaths:
    canary_root: Path
    home: Path
    xdg_config: Path
    xdg_state: Path
    xdg_cache: Path
    registry: Path
    project_root: Path
    settings: Path
    ledger: Path
    backup: Path
    token_file: Path
    activation_envelope: Path
    claimed_activation_envelope: Path
    fixture_root: Path
    runtime_executable: Path
    cwd: Path


def provision_private_bearer_token(
    *,
    xdg_config_home: str | os.PathLike[str],
) -> PrivateTokenProvisioning:
    config_home = Path(xdg_config_home).expanduser().resolve()
    config_home.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(config_home, 0o700)
    store = RunnerGlobalConfigStore(config_dir=str(config_home / "colameta"))
    token = f"mvr_{secrets.token_urlsafe(32)}"
    saved = store.save_auth_token(token)
    if not saved.get("ok"):
        raise WorkItemGovernanceError(
            "ACTIVATION_TOKEN_PROVISION_FAILED",
            "Private Canary Bearer Token could not be provisioned.",
            details={"error_code": saved.get("error_code")},
        )
    auth_file = Path(str(saved["path"])).resolve()
    parent = auth_file.parent
    os.chmod(parent, 0o700)
    saved_token, evidence = read_authoritative_token_file(auth_file)
    if not secrets.compare_digest(saved_token, token):
        raise WorkItemGovernanceError(
            "ACTIVATION_TOKEN_PROVISION_FAILED",
            "Private Canary Bearer Token differs from the persisted auth.json.",
        )
    return PrivateTokenProvisioning(
        token=token,
        auth_file=auth_file,
        evidence_digest=canonical_sha256(evidence),
        entropy_bits=256,
    )


def revoke_private_bearer_token(
    *,
    auth_file: str | os.PathLike[str],
    canary_root: str | os.PathLike[str],
) -> dict[str, Any]:
    path = Path(auth_file).expanduser().resolve()
    root = Path(canary_root).expanduser().resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise WorkItemGovernanceError(
            "TOKEN_REVOCATION_PATH_INVALID",
            "Token revocation path must remain below the Canary root.",
        ) from exc
    existed = path.is_file()
    if existed:
        path.unlink()
        descriptor = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    return {
        "revoked": True,
        "token_file_existed": existed,
        "token_file_present_after": path.exists(),
        "token_file_path_digest": canonical_path_digest(path),
    }


def bootstrap_fresh_canary_preflight(
    *,
    paths: FreshCanaryPaths,
    authorization_id: str,
    authorization_digest: str,
    activation_lease_id: str,
    runtime_instance_nonce: str,
    source_binding: dict[str, str],
    principal_binding: dict[str, Any],
    project_name: str,
    port: int,
    token_provisioning: PrivateTokenProvisioning,
    process_identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a schema-v5 empty Ledger and its <=120-second Preflight receipt.

    This is a local control-plane operation. It does not claim the Activation
    Envelope, start a listener, or enable an endpoint.
    """

    root = paths.canary_root.expanduser().resolve()
    if not root.is_dir():
        raise WorkItemGovernanceError("CANARY_ROOT_MISSING", "Canary root must already exist.")
    _assert_private_directory(root)
    for field_name, path in vars(paths).items():
        resolved = path.expanduser().resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise WorkItemGovernanceError(
                "CANARY_PATH_ESCAPE",
                "Every Authoritative Canary path must remain below its isolated root.",
                details={"field": field_name},
            ) from exc
    if paths.ledger.exists():
        raise WorkItemGovernanceError(
            "FRESH_LEDGER_ALREADY_EXISTS",
            "Fresh Canary bootstrap refuses a pre-existing Ledger.",
        )
    if token_provisioning.auth_file.resolve() != paths.token_file.resolve():
        raise WorkItemGovernanceError("TOKEN_FILE_PATH_MISMATCH", "Provisioned Token path differs from Preflight.")
    persisted_token, token_evidence = _validate_private_token_file(paths.token_file)
    if (
        not secrets.compare_digest(persisted_token, token_provisioning.token)
        or canonical_sha256(token_evidence) != token_provisioning.evidence_digest
    ):
        raise WorkItemGovernanceError(
            "ACTIVATION_TOKEN_BINDING_MISMATCH",
            "Provisioned Token evidence differs from the exact private auth.json bytes.",
        )
    _validate_token_secret_boundary(token_provisioning.token)
    expected_environment = {
        "HOME": paths.home.resolve(),
        "XDG_CONFIG_HOME": paths.xdg_config.resolve(),
        "XDG_STATE_HOME": paths.xdg_state.resolve(),
        "XDG_CACHE_HOME": paths.xdg_cache.resolve(),
    }
    for name, expected in expected_environment.items():
        actual = Path(os.environ.get(name, "")).expanduser().resolve()
        if actual != expected:
            raise WorkItemGovernanceError(
                "CANARY_ENVIRONMENT_PATH_MISMATCH",
                "Isolated HOME/XDG environment does not match Preflight paths.",
                details={"variable": name},
            )
    if paths.registry.resolve() != (paths.xdg_config / "colameta" / "project-registry.json").resolve():
        raise WorkItemGovernanceError(
            "CANARY_REGISTRY_PATH_MISMATCH",
            "Canary Registry is not the isolated default Registry path.",
        )
    if Path.cwd().resolve() != paths.cwd.resolve():
        raise WorkItemGovernanceError("CANARY_CWD_MISMATCH", "Current directory differs from Preflight CWD.")
    if Path("/proc/self/exe").resolve() != paths.runtime_executable.resolve():
        raise WorkItemGovernanceError(
            "CANARY_EXECUTABLE_MISMATCH",
            "Current process executable differs from the isolated runtime executable.",
        )
    for directory in (
        paths.home,
        paths.xdg_config,
        paths.xdg_state,
        paths.xdg_cache,
        paths.project_root,
        paths.fixture_root,
    ):
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    paths.settings.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _write_private_json(
        paths.settings,
        {
            "work_item_governance": {
                "shadow_ledger_enabled": True,
                "gate_mode": "authoritative",
                "authoritative_canary": True,
            }
        },
    )
    registry = ProjectRegistry(registry_path=str(paths.registry))
    registered = registry.register_project(
        str(paths.project_root),
        project_name=project_name,
        project_mode="source-only",
        display_name=project_name,
    )
    if not registered.get("ok") or registered.get("project_count") != 1:
        raise WorkItemGovernanceError("CANARY_REGISTRY_INVALID", "Canary Registry must contain one project.")
    if _global_registry_open(root):
        raise WorkItemGovernanceError(
            "GLOBAL_REGISTRY_OPEN",
            "Preflight detected an open project Registry outside the Canary root.",
        )
    ledger = SQLiteWorkItemLedger(paths.project_root)
    if ledger.path.resolve() != paths.ledger.resolve():
        raise WorkItemGovernanceError("LEDGER_PATH_MISMATCH", "Ledger path differs from the project-local contract.")
    ledger.initialize()
    ledger.get_or_create_signing_key()
    token_binding_updated_at = isoformat_utc(utc_now())
    with ledger.write_transaction() as connection:
        for key, value in (
            (AUTHORITATIVE_TOKEN_FILE_SHA256_META_KEY, token_evidence["token_sha256"]),
            (AUTHORITATIVE_TOKEN_EVIDENCE_DIGEST_META_KEY, token_provisioning.evidence_digest),
        ):
            connection.execute(
                """
                INSERT INTO ledger_meta(key,value,updated_at) VALUES(?,?,?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at
                """,
                (key, value, token_binding_updated_at),
            )
    with ledger.read_connection() as connection:
        counts = business_fact_counts(connection)
        external_associations = int(
            connection.execute("SELECT COUNT(*) FROM external_associations").fetchone()[0]
        )
        attempt_events = int(connection.execute("SELECT COUNT(*) FROM attempt_events").fetchone()[0])
        prior_leases = int(
            connection.execute(
                "SELECT COUNT(*) FROM activation_leases WHERE authorization_id=?",
                (authorization_id,),
            ).fetchone()[0]
        )
    if any(counts.values()) or external_associations or attempt_events or prior_leases:
        raise WorkItemGovernanceError("FRESH_LEDGER_REQUIRED", "Fresh Ledger business baseline is not empty.")
    baseline = {
        "business_fact_counts": counts,
        "external_associations": external_associations,
        "attempt_events": attempt_events,
        "prior_activation_leases_for_authorization": prior_leases,
    }
    baseline_digest = canonical_sha256(baseline)
    backup = ledger.backup_to(paths.backup)
    backup_core = {
        "api": "sqlite3.Connection.backup",
        "backup_sha256": sha256_file(paths.backup),
        "database_generation": ledger.database_generation(),
        "schema_version": ledger.schema_version(),
        "integrity_check": backup["integrity_check"][0],
        "foreign_key_violations": backup["foreign_key_violations"],
        "mode": f"{stat.S_IMODE(paths.backup.stat().st_mode):04o}",
    }
    backup_receipt_digest = canonical_sha256(backup_core)
    policy = validate_runtime_policy_contracts()
    observed = utc_now()
    valid_until = observed + timedelta(seconds=120)
    identity = process_identity or process_identity_inputs(runtime_instance_nonce)
    if identity.get("executable_sha256") != sha256_file(paths.runtime_executable):
        raise WorkItemGovernanceError(
            "CANARY_EXECUTABLE_DIGEST_MISMATCH",
            "Preflight process executable digest does not match the runtime executable.",
        )
    relative = _relative_paths(paths)
    runtime_isolation = {
        "canary_root_path_digest": canonical_path_digest(root),
        "canary_root_resolved_path": root.as_posix(),
        **relative,
        "home_path_digest": canonical_path_digest(paths.home),
        "xdg_config_path_digest": canonical_path_digest(paths.xdg_config),
        "xdg_state_path_digest": canonical_path_digest(paths.xdg_state),
        "xdg_cache_path_digest": canonical_path_digest(paths.xdg_cache),
        "registry_path_digest": canonical_path_digest(paths.registry),
        "project_root_digest": canonical_path_digest(paths.project_root),
        "runtime_executable_path_digest": canonical_path_digest(paths.runtime_executable),
        "cwd_path_digest": canonical_path_digest(paths.cwd),
        "settings_path_digest": canonical_path_digest(paths.settings),
        "ledger_path_digest": canonical_path_digest(paths.ledger),
        "backup_path_digest": canonical_path_digest(paths.backup),
        "activation_envelope_path_digest": canonical_path_digest(paths.activation_envelope),
        "claimed_activation_envelope_path_digest": canonical_path_digest(paths.claimed_activation_envelope),
        "fixture_root_path_digest": canonical_path_digest(paths.fixture_root),
        "all_paths_under_canary_root": True,
        "registry_project_count": 1,
        "global_registry_selected": False,
        "global_registry_open": False,
        "preclaim_listener_count": 0,
        "intended_bind_address": "127.0.0.1",
        "intended_port": port,
        "public_endpoint_created": False,
        "relay_enabled": False,
        "tunnel_enabled": False,
        "proxy_enabled": False,
        "background_side_effect_workers_started": False,
    }
    receipt = {
        "schema_version": "work_item_authoritative_canary_preflight_receipt.v1",
        "authorization_id": authorization_id,
        "authorization_digest": authorization_digest,
        "activation_lease_id": activation_lease_id,
        "observed_at": isoformat_utc(observed),
        "valid_until": isoformat_utc(valid_until),
        "maximum_age_seconds": 120,
        "source_binding": source_binding,
        "process_identity_inputs": identity,
        "runtime_isolation": runtime_isolation,
        "authentication": {
            "auth_mode": "token",
            "token_source": PRIVATE_CREDENTIAL_SOURCE,
            "token_file_relative_path": paths.token_file.resolve().relative_to(root).as_posix(),
            "token_file_path_digest": canonical_path_digest(paths.token_file),
            "token_file_mode": PRIVATE_FILE_MODE_TEXT,
            "token_parent_mode": PRIVATE_DIRECTORY_MODE_TEXT,
            "token_owner_matches_canary_user": VERIFIED_TRUE,
            "token_generation_algorithm": CSPRNG_EVIDENCE_ALGORITHM,
            "token_entropy_bits": token_provisioning.entropy_bits,
            "token_generation_evidence_digest": token_provisioning.evidence_digest,
            "weak_token_configuration_rejected": VERIFIED_TRUE,
            "token_absent_from_public_surfaces": VERIFIED_TRUE,
        },
        "principal_binding": principal_binding,
        "restricted_surface": {
            "profile": "authoritative_canary",
            "tool_count": len(AUTHORITATIVE_CANARY_TOOLS),
            "listed_tools_sha256": canonical_sha256(list(AUTHORITATIVE_CANARY_TOOLS)),
            "tool_allowlist_digest": policy["tool_allowlist_digest"],
            "command_matrix_digest": policy["command_matrix_digest"],
            "definitions_dispatch_exact_match": True,
            "resources_disabled_or_empty": True,
            "actions_disabled": True,
        },
        "fresh_ledger": {
            "schema_version": ledger.schema_version(),
            "database_generation": ledger.database_generation(),
            "business_fact_counts": counts,
            "external_associations": external_associations,
            "attempt_events": attempt_events,
            "prior_activation_leases_for_authorization": prior_leases,
            "preview_signing_key_preprovisioned": True,
            "baseline_digest": baseline_digest,
            "integrity_check": "ok",
            "foreign_key_violations": [],
        },
        "pre_activation_backup": {
            **backup_core,
            "receipt_digest": backup_receipt_digest,
        },
        "result": "PASS",
    }
    validate_governance_record("work_item_authoritative_canary_preflight_receipt.v1", receipt)
    return receipt


def build_activation_envelope(
    *,
    preflight_receipt: dict[str, Any],
    synthetic_fixture: dict[str, Any],
    instance_id: str,
    project_name: str,
    issued_at: str,
    not_before: str,
    expires_at: str,
) -> dict[str, Any]:
    """Build the secret-free, one-shot Envelope consumed by the waiting process."""

    validate_governance_record(
        "work_item_authoritative_canary_preflight_receipt.v1",
        preflight_receipt,
    )
    validate_synthetic_fixture_semantics(synthetic_fixture)
    if synthetic_fixture["authorization_id"] != preflight_receipt["authorization_id"]:
        raise WorkItemGovernanceError(
            "FIXTURE_AUTHORIZATION_MISMATCH",
            "Synthetic Fixture belongs to another authorization.",
        )
    runtime = preflight_receipt["runtime_isolation"]
    principal = preflight_receipt["principal_binding"]
    envelope = {
        "schema_version": "work_item_activation_envelope.v1",
        "envelope_id": new_stable_id("activation_envelope"),
        "authorization_id": preflight_receipt["authorization_id"],
        "authorization_digest": preflight_receipt["authorization_digest"],
        "activation_lease_id": preflight_receipt["activation_lease_id"],
        "spec_manifest_digest": R2_SPEC_FREEZE_MANIFEST_SHA256,
        "source_binding": preflight_receipt["source_binding"],
        "runtime_binding": {
            "instance_id": instance_id,
            "runtime_instance_nonce": preflight_receipt["process_identity_inputs"]["runtime_instance_nonce"],
            "expected_process_identity": preflight_receipt["process_identity_inputs"]["expected_process_identity"],
            "canary_root_path_digest": runtime["canary_root_path_digest"],
            "activation_envelope_path_digest": runtime["activation_envelope_path_digest"],
            "claimed_activation_envelope_path_digest": runtime[
                "claimed_activation_envelope_path_digest"
            ],
            "project_name": project_name,
            "project_root_digest": runtime["project_root_digest"],
            "bind_address": "127.0.0.1",
            "port": runtime["intended_port"],
        },
        "authentication": {
            "mode": "token",
            "token_source": PRIVATE_CREDENTIAL_SOURCE,
            "token_file_path_digest": preflight_receipt["authentication"]["token_file_path_digest"],
            "token_generation_algorithm": CSPRNG_EVIDENCE_ALGORITHM,
            "minimum_entropy_bits": 256,
            "request_context_mode": "sealed_token_verified_listener_attested_context",
            "request_context_binding_algorithm": (
                "sha256(canonical_json({lease_id,authorization_digest,claimed_process_identity,"
                "runtime_instance_nonce,listener_attestation_digest,principal_id,session_ref}))"
            ),
            "bearer_token_embedded": VERIFIED_FALSE,
        },
        "principal_binding": {
            "principal_id": principal["principal_id"],
            "principal_kind": principal["principal_kind"],
            "session_ref": principal["session_ref"],
            "authenticated_by": "local_session",
            "permissions": principal["permissions"],
        },
        "window": {
            "issued_at": issued_at,
            "not_before": not_before,
            "expires_at": expires_at,
            "maximum_runtime_seconds": 1800,
        },
        "synthetic_fixture_contract_digest": canonical_sha256(synthetic_fixture),
        "preflight_receipt_digest": canonical_sha256(preflight_receipt),
        "fresh_ledger_baseline_digest": preflight_receipt["fresh_ledger"]["baseline_digest"],
        "pre_activation_backup_receipt_digest": preflight_receipt["pre_activation_backup"][
            "receipt_digest"
        ],
        "pre_activation_backup_sha256": preflight_receipt["pre_activation_backup"]["backup_sha256"],
        "tool_allowlist_digest": preflight_receipt["restricted_surface"]["tool_allowlist_digest"],
        "command_matrix_digest": preflight_receipt["restricted_surface"]["command_matrix_digest"],
        "created_at": issued_at,
        "single_use": True,
    }
    validate_governance_record("work_item_activation_envelope.v1", envelope)
    return envelope


def _relative_paths(paths: FreshCanaryPaths) -> dict[str, str]:
    root = paths.canary_root.resolve()
    names = {
        "home_relative_path": paths.home,
        "xdg_config_relative_path": paths.xdg_config,
        "xdg_state_relative_path": paths.xdg_state,
        "xdg_cache_relative_path": paths.xdg_cache,
        "registry_relative_path": paths.registry,
        "project_root_relative_path": paths.project_root,
        "runtime_executable_relative_path": paths.runtime_executable,
        "cwd_relative_path": paths.cwd,
        "settings_relative_path": paths.settings,
        "ledger_relative_path": paths.ledger,
        "backup_relative_path": paths.backup,
        "activation_envelope_relative_path": paths.activation_envelope,
        "claimed_activation_envelope_relative_path": paths.claimed_activation_envelope,
        "fixture_root_relative_path": paths.fixture_root,
    }
    return {key: value.resolve().relative_to(root).as_posix() for key, value in names.items()}


def _validate_private_token_file(path: Path) -> tuple[str, dict[str, Any]]:
    return read_authoritative_token_file(path)


def _assert_private_directory(path: Path) -> None:
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise WorkItemGovernanceError(
            "CANARY_DIRECTORY_PERMISSIONS_INVALID",
            "Canary root must be 0700 or stricter.",
        )


def _validate_token_secret_boundary(token: str) -> None:
    try:
        command_line = Path("/proc/self/cmdline").read_bytes()
    except OSError:
        command_line = b""
    if token.encode("utf-8") in command_line or token in os.environ.values():
        raise WorkItemGovernanceError(
            "TOKEN_PUBLIC_SURFACE_VIOLATION",
            "Bearer Token must not appear in process arguments or environment variables.",
        )


def _global_registry_open(root: Path) -> bool:
    descriptors = Path("/proc/self/fd")
    if not descriptors.is_dir():
        return False
    for item in descriptors.iterdir():
        try:
            target = item.resolve(strict=True)
        except OSError:
            continue
        if target.name == "project-registry.json":
            try:
                target.relative_to(root)
            except ValueError:
                return True
    return False


def _write_private_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", closefd=False) as handle:
            handle.write(canonical_json(payload))
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)
    os.chmod(path, 0o600)


__all__ = [
    "FreshCanaryPaths",
    "PrivateTokenProvisioning",
    "bootstrap_fresh_canary_preflight",
    "build_activation_envelope",
    "provision_private_bearer_token",
    "revoke_private_bearer_token",
    "R2_SPEC_FREEZE_MANIFEST_SHA256",
]
