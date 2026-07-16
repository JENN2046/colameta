from __future__ import annotations

import json
import os
import stat
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from runner.work_item_governance.activation import canonical_path_digest
from runner.work_item_governance.canonical import canonical_sha256, sha256_bytes
from runner.work_item_governance.errors import WorkItemGovernanceError
from runner.work_item_governance.pilot import (
    PILOT_SOURCE_BINDING_FIELDS,
    validate_execution_authorization_receipt,
    validate_pilot_authorization,
    validate_pilot_scope_envelope,
)
from runner.work_item_governance.source_binding import CORE_BASELINE_COMMIT


_RECORD_NAMES = frozenset(
    {
        "execution-authorization-receipt.json",
        "scope-envelope.json",
        "PILOT_AUTHORIZATION_TEMPLATE.json",
    }
)
_VALIDATION_RECEIPT_NAME = "PILOT_CANDIDATE_VALIDATION_RECEIPT.json"


@dataclass(frozen=True)
class PilotCandidatePaths:
    pilot_root: Path
    project_root: Path

    @classmethod
    def from_roots(
        cls,
        *,
        pilot_root: str | Path,
        project_root: str | Path,
    ) -> PilotCandidatePaths:
        return cls(
            pilot_root=Path(pilot_root).expanduser().resolve(),
            project_root=Path(project_root).expanduser().resolve(),
        )

    def path_digests(self) -> dict[str, str]:
        pilot = self.pilot_root
        project = self.project_root
        return {
            "backup_path_digest": canonical_path_digest(pilot / "backups/pre-activation-generation-1.sqlite3"),
            "cwd_path_digest": canonical_path_digest(project),
            "home_path_digest": canonical_path_digest(pilot / "home"),
            "ledger_path_digest": canonical_path_digest(project / ".colameta/ledger/work-items.sqlite3"),
            "pilot_root_path_digest": canonical_path_digest(pilot),
            "project_root_path_digest": canonical_path_digest(project),
            "registry_path_digest": canonical_path_digest(pilot / "xdg-config/colameta/project-registry.json"),
            "runtime_executable_path_digest": canonical_path_digest(pilot / "runtime/bin/python"),
            "settings_path_digest": canonical_path_digest(project / ".colameta/settings.json"),
            "token_file_path_digest": canonical_path_digest(pilot / "xdg-config/colameta/auth.json"),
            "xdg_cache_path_digest": canonical_path_digest(pilot / "xdg-cache"),
            "xdg_config_path_digest": canonical_path_digest(pilot / "xdg-config"),
            "xdg_data_path_digest": canonical_path_digest(pilot / "xdg-data"),
            "xdg_state_path_digest": canonical_path_digest(pilot / "xdg-state"),
        }


def _principal_for_authorization(principal: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "authenticated_by": principal["principal_authenticated_by"],
        "caller_auth_mode": principal["caller_auth_mode"],
        "combined_operator_reviewer_role_explicitly_authorized": principal[
            "combined_operator_reviewer_role_explicitly_authorized"
        ],
        "permissions": deepcopy(principal["permissions"]),
        "principal_id": principal["principal_id"],
        "principal_kind": principal["principal_kind"],
        "session_ref": principal["session_ref"],
    }


def source_binding_from_durable_attestation(
    source_artifact_attestation_bytes: bytes,
    *,
    durable_source_binding: Mapping[str, Any],
) -> dict[str, str]:
    """Project the Ledger-sealed attestation identity into candidate authority.

    Path identity is deliberately retained.  A byte-identical Wheel copied to a
    different path is a different durable source and cannot silently replace
    the attestation that was sealed into the Ledger.
    """

    try:
        attestation = _strict_json_bytes(source_artifact_attestation_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise WorkItemGovernanceError(
            "PILOT_CANDIDATE_SOURCE_ATTESTATION_INVALID",
            "Pilot candidate source attestation bytes are not strict JSON.",
        ) from exc
    source = attestation.get("source_binding")
    required_attestation_fields = {
        "schema_version",
        "source_binding",
        "file_manifest_digest",
        "artifact_evidence_digest",
        "checkout_path_digest",
        "wheel_path_digest",
        "baseline_object_present",
        "baseline_is_ancestor",
        "loaded_modules_required_under_checkout",
        "verified",
    }
    if (
        set(attestation) != required_attestation_fields
        or attestation.get("schema_version") != "work_item_runtime_source_attestation.v1"
        or not isinstance(source, Mapping)
        or set(source)
        != {
            "core_baseline_commit",
            "implementation_commit",
            "implementation_tree",
            "wheel_sha256",
        }
        or source.get("core_baseline_commit") != CORE_BASELINE_COMMIT
        or any(
            attestation.get(field) is not True
            for field in (
                "baseline_object_present",
                "baseline_is_ancestor",
                "loaded_modules_required_under_checkout",
                "verified",
            )
        )
    ):
        raise WorkItemGovernanceError(
            "PILOT_CANDIDATE_SOURCE_ATTESTATION_INVALID",
            "Pilot candidate generation requires a durable runtime source attestation.",
        )
    projected = {
        "implementation_commit": str(source["implementation_commit"]),
        "implementation_tree": str(source["implementation_tree"]),
        "wheel_sha256": str(source["wheel_sha256"]),
        "installed_inventory_sha256": str(attestation.get("file_manifest_digest", "")),
        "durable_artifact_evidence_digest": str(attestation.get("artifact_evidence_digest", "")),
        "durable_checkout_path_digest": str(attestation.get("checkout_path_digest", "")),
        "durable_wheel_path_digest": str(attestation.get("wheel_path_digest", "")),
    }
    if set(projected) != set(PILOT_SOURCE_BINDING_FIELDS) or any(
        len(projected[field]) != (40 if field.startswith("implementation_") else 64)
        for field in PILOT_SOURCE_BINDING_FIELDS
    ):
        raise WorkItemGovernanceError(
            "PILOT_CANDIDATE_SOURCE_ATTESTATION_INVALID",
            "Pilot source attestation has incomplete durable identity digests.",
        )
    expected = {field: str(durable_source_binding.get(field, "")) for field in PILOT_SOURCE_BINDING_FIELDS}
    if set(durable_source_binding) != set(PILOT_SOURCE_BINDING_FIELDS) or projected != expected:
        raise WorkItemGovernanceError(
            "PILOT_CANDIDATE_SOURCE_ATTESTATION_MISMATCH",
            "Pilot source attestation differs from the Ledger-sealed durable identity.",
            details={
                "failed_bindings": sorted(
                    field for field in PILOT_SOURCE_BINDING_FIELDS if projected.get(field) != expected.get(field)
                )
            },
        )
    return projected


def validate_pilot_candidate_manifest_source(
    candidate_manifest_bytes: bytes,
    *,
    source_artifact_attestation_bytes: bytes,
    durable_source_binding: Mapping[str, Any],
) -> str:
    """Bind exact manifest and attestation bytes to one durable source identity."""

    try:
        manifest = _strict_json_bytes(candidate_manifest_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise WorkItemGovernanceError(
            "PILOT_CANDIDATE_MANIFEST_SOURCE_INVALID",
            "Pilot candidate manifest bytes are not strict JSON.",
        ) from exc
    exact_source = manifest.get("exact_source")
    if not isinstance(exact_source, Mapping):
        raise WorkItemGovernanceError(
            "PILOT_CANDIDATE_MANIFEST_SOURCE_INVALID",
            "Pilot candidate manifest has no exact durable source binding.",
        )
    failed = [
        field
        for field in PILOT_SOURCE_BINDING_FIELDS
        if exact_source.get(field) != durable_source_binding.get(field)
    ]
    files = manifest.get("files")
    attestation_entries = (
        [
            item
            for item in files
            if isinstance(item, Mapping)
            and item.get("path") == "SOURCE_ARTIFACT_ATTESTATION.json"
        ]
        if isinstance(files, list)
        else []
    )
    expected_attestation_sha256 = sha256_bytes(source_artifact_attestation_bytes)
    if len(attestation_entries) != 1 or attestation_entries[0].get(
        "sha256"
    ) != expected_attestation_sha256:
        failed.append("SOURCE_ARTIFACT_ATTESTATION.json:sha256")
    if failed:
        raise WorkItemGovernanceError(
            "PILOT_CANDIDATE_MANIFEST_SOURCE_MISMATCH",
            "Pilot candidate manifest differs from its durable source identity.",
            details={"failed_bindings": sorted(failed)},
        )
    return sha256_bytes(candidate_manifest_bytes)


def derive_pilot_candidate_records(
    *,
    principal_binding: Mapping[str, Any],
    execution_authorization_receipt: Mapping[str, Any],
    scope_envelope: Mapping[str, Any],
    pilot_authorization: Mapping[str, Any],
    source_artifact_attestation_bytes: bytes,
    durable_source_binding: Mapping[str, Any],
    candidate_manifest_bytes: bytes,
    paths: PilotCandidatePaths,
    issued_at: str,
    expires_at: str,
    file_list_root_sha256: str,
    authentication_conformance_receipt_digest: str,
) -> dict[str, dict[str, Any]]:
    """Derive every mutable Pilot cross-binding from authoritative inputs.

    Callers provide semantic source records, never precomputed path or cross-record
    digests. The returned records are the only records that may be serialized into
    a preflight authorization candidate.
    """

    principal = deepcopy(dict(principal_binding))
    execution = deepcopy(dict(execution_authorization_receipt))
    scope = deepcopy(dict(scope_envelope))
    authorization = deepcopy(dict(pilot_authorization))
    authoritative_source = source_binding_from_durable_attestation(
        source_artifact_attestation_bytes,
        durable_source_binding=durable_source_binding,
    )
    candidate_manifest_sha256 = validate_pilot_candidate_manifest_source(
        candidate_manifest_bytes,
        source_artifact_attestation_bytes=source_artifact_attestation_bytes,
        durable_source_binding=authoritative_source,
    )
    window = {
        "issued_at": issued_at,
        "not_before": issued_at,
        "expires_at": expires_at,
        "maximum_preflight_age_seconds": 120,
        "maximum_runtime_seconds": 14400,
    }

    target = scope["target_project"]
    isolation = scope["pilot_isolation"]
    work_item = scope["work_item_scope"]
    execution_scope = scope["execution_scope"]
    digests = paths.path_digests()

    target["project_root"] = str(paths.project_root)
    target["project_root_path_digest"] = digests["project_root_path_digest"]
    isolation["pilot_root"] = str(paths.pilot_root)
    for field in (
        "backup_path_digest",
        "cwd_path_digest",
        "home_path_digest",
        "ledger_path_digest",
        "pilot_root_path_digest",
        "registry_path_digest",
        "runtime_executable_path_digest",
        "settings_path_digest",
        "token_file_path_digest",
        "xdg_cache_path_digest",
        "xdg_config_path_digest",
        "xdg_data_path_digest",
        "xdg_state_path_digest",
    ):
        isolation[field] = digests[field]
    scope["artifact_policy"]["allowed_root_path_digests"] = [digests["project_root_path_digest"]]
    scope["principal_binding"] = principal
    scope["source_binding"].update(authoritative_source)
    scope["window"] = deepcopy(window)

    objective_digest = canonical_sha256(work_item["objective_ref"])
    work_item["objective_digest"] = objective_digest
    execution.update(issued_at=issued_at, not_before=issued_at, expires_at=expires_at)
    execution["issuer"]["principal_id"] = principal["principal_id"]
    receipt_scope = execution["scope"]
    receipt_scope["project_id"] = target["project_id"]
    receipt_scope["project_snapshot_digest"] = target["project_snapshot_digest"]
    receipt_scope["work_item_id"] = work_item["proposed_work_item_id"]
    receipt_scope["allowed_read_path_manifest_digest"] = target["allowed_read_path_manifest_digest"]
    receipt_scope["allowed_write_path_manifest_digest"] = target["allowed_write_path_manifest_digest"]
    receipt_scope["protected_path_manifest_digest"] = target["protected_path_manifest_digest"]
    receipt_scope["attempt_slot_schema_sha256"] = execution_scope["attempt_slot_schema_sha256"]
    receipt_scope["executor_identity"] = execution_scope["executor_identity"]
    for slot in receipt_scope["attempt_slots"]:
        slot["objective_digest"] = objective_digest

    execution_digest = canonical_sha256(execution)
    execution_scope["authorization_receipt_digest"] = execution_digest
    scope_digest = canonical_sha256(scope)

    authorization["bindings"].update(
        candidate_manifest_sha256=candidate_manifest_sha256,
        file_list_root_sha256=file_list_root_sha256,
        execution_authorization_receipt_digest=execution_digest,
        authentication_conformance_receipt_digest=authentication_conformance_receipt_digest,
        project_snapshot_digest=target["project_snapshot_digest"],
        scope_envelope_sha256=scope_digest,
        authorized_scope_digest=scope_digest,
    )
    authorization["principal"] = _principal_for_authorization(principal)
    authorization["source"].update(authoritative_source)
    authorization["target"].update(
        project_id=target["project_id"],
        project_root_path_digest=digests["project_root_path_digest"],
        pilot_root_path_digest=digests["pilot_root_path_digest"],
    )
    authorization["window"] = deepcopy(window)

    return {
        "execution-authorization-receipt.json": execution,
        "scope-envelope.json": scope,
        "PILOT_AUTHORIZATION_TEMPLATE.json": authorization,
    }


def canonical_record_bytes(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def serialize_pilot_candidate_records(
    records: Mapping[str, Mapping[str, Any]],
) -> dict[str, bytes]:
    if set(records) != _RECORD_NAMES:
        raise WorkItemGovernanceError(
            "PILOT_CANDIDATE_RECORD_SET_MISMATCH",
            "Pilot candidate records require the exact final record set.",
        )
    return {name: canonical_record_bytes(records[name]) for name in sorted(records)}


def _strict_json_bytes(raw: bytes) -> dict[str, Any]:
    def pairs(value: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in value:
            if key in result:
                raise ValueError(f"duplicate key: {key}")
            result[key] = item
        return result

    value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs)
    if not isinstance(value, dict):
        raise ValueError("JSON object required")
    return value


def validate_final_pilot_candidate_bytes(
    payloads: Mapping[str, bytes],
) -> dict[str, str]:
    """Run production validators against the exact bytes offered for signing."""

    if set(payloads) != _RECORD_NAMES:
        raise WorkItemGovernanceError(
            "PILOT_CANDIDATE_RECORD_SET_MISMATCH",
            "Pilot candidate bytes require the exact final record set.",
        )
    try:
        records = {name: _strict_json_bytes(payloads[name]) for name in sorted(payloads)}
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise WorkItemGovernanceError(
            "PILOT_CANDIDATE_JSON_INVALID",
            "Pilot candidate records must contain strict UTF-8 JSON objects.",
        ) from exc
    for name, value in records.items():
        if payloads[name] != canonical_record_bytes(value):
            raise WorkItemGovernanceError(
                "PILOT_CANDIDATE_BYTES_NOT_CANONICAL",
                "Pilot candidate bytes changed after deterministic serialization.",
                details={"record": name},
            )

    execution = records["execution-authorization-receipt.json"]
    scope = records["scope-envelope.json"]
    authorization = records["PILOT_AUTHORIZATION_TEMPLATE.json"]
    validate_execution_authorization_receipt(execution)
    validate_pilot_scope_envelope(
        scope,
        execution_authorization_receipt=execution,
    )
    validate_pilot_authorization(authorization, scope_envelope=scope)
    return {
        "execution_authorization": "PASS",
        "scope_envelope": "PASS",
        "pilot_authorization": "PASS",
        "execution_authorization_receipt_digest": canonical_sha256(execution),
        "authentication_conformance_receipt_digest": authorization["bindings"][
            "authentication_conformance_receipt_digest"
        ],
        "scope_envelope_digest": canonical_sha256(scope),
        "final_byte_set_digest": canonical_sha256(
            [
                {
                    "name": name,
                    "sha256": sha256_bytes(payloads[name]),
                    "size": len(payloads[name]),
                }
                for name in sorted(payloads)
            ]
        ),
    }


def _candidate_validation_receipt(payloads: Mapping[str, bytes], validation: Mapping[str, str]) -> dict[str, Any]:
    return {
        "schema_version": "wig_p3_pilot_candidate_validation_receipt.v1",
        "result": "PASS",
        "production_validators": [
            "validate_execution_authorization_receipt",
            "validate_pilot_scope_envelope",
            "validate_pilot_authorization",
        ],
        "records": [
            {
                "name": name,
                "sha256": sha256_bytes(payloads[name]),
                "size": len(payloads[name]),
            }
            for name in sorted(payloads)
        ],
        "validation": dict(validation),
    }


def write_validated_pilot_candidate_records(
    output_dir: str | Path,
    records: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Persist exact candidate bytes only after production validation succeeds."""

    output = Path(output_dir).expanduser()
    if output.exists() or output.is_symlink():
        raise WorkItemGovernanceError(
            "PILOT_CANDIDATE_OUTPUT_NOT_FRESH",
            "Pilot candidate output must be a fresh path.",
        )
    payloads = serialize_pilot_candidate_records(records)
    receipt = validate_final_pilot_candidate_bytes(payloads)
    output.mkdir(mode=0o700, parents=False)
    if output.is_symlink() or stat.S_IMODE(output.stat().st_mode) != 0o700:
        raise WorkItemGovernanceError(
            "PILOT_CANDIDATE_OUTPUT_NOT_PRIVATE",
            "Pilot candidate output must be an owned mode-0700 directory.",
        )
    try:
        for name in sorted(payloads):
            target = output / name
            temporary = output / f".{name}.tmp"
            descriptor = os.open(
                temporary,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            try:
                os.write(descriptor, payloads[name])
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            os.replace(temporary, target)
        descriptor = os.open(output, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        persisted = {name: (output / name).read_bytes() for name in sorted(payloads)}
        if persisted != payloads:
            raise WorkItemGovernanceError(
                "PILOT_CANDIDATE_PERSISTED_BYTES_MISMATCH",
                "Persisted Pilot candidate bytes differ from validated bytes.",
            )
        final_receipt = validate_final_pilot_candidate_bytes(persisted)
        if final_receipt != receipt:
            raise WorkItemGovernanceError(
                "PILOT_CANDIDATE_VALIDATION_RECEIPT_MISMATCH",
                "Persisted Pilot candidate validation receipt changed.",
            )
        validation_receipt = _candidate_validation_receipt(persisted, final_receipt)
        receipt_path = output / _VALIDATION_RECEIPT_NAME
        receipt_bytes = canonical_record_bytes(validation_receipt)
        descriptor = os.open(
            receipt_path,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            os.write(descriptor, receipt_bytes)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        descriptor = os.open(output, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return validation_receipt
    except Exception:
        # Never leave a partially generated directory that could be signed.
        for child in output.iterdir():
            if child.is_file() and not child.is_symlink():
                child.unlink()
        output.rmdir()
        raise


def _read_private_candidate_file(directory_fd: int, name: str) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(name, flags, dir_fd=directory_fd)
        try:
            opened = os.fstat(descriptor)
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_uid != os.getuid()
                or stat.S_IMODE(opened.st_mode) != 0o600
                or opened.st_nlink != 1
            ):
                raise WorkItemGovernanceError(
                    "PILOT_CANDIDATE_AUTHORIZATION_FILE_INVALID",
                    "Pilot candidate authorization files must be private regular files.",
                    details={"record": name},
                )
            chunks: list[bytes] = []
            while chunk := os.read(descriptor, 1024 * 1024):
                chunks.append(chunk)
            finished = os.fstat(descriptor)
        finally:
            os.close(descriptor)
    except WorkItemGovernanceError:
        raise
    except OSError as exc:
        raise WorkItemGovernanceError(
            "PILOT_CANDIDATE_AUTHORIZATION_FILE_INVALID",
            "Pilot candidate authorization files must be private regular files.",
            details={"record": name},
        ) from exc
    stable_fields = (
        "st_dev",
        "st_ino",
        "st_uid",
        "st_mode",
        "st_nlink",
        "st_size",
        "st_mtime_ns",
        "st_ctime_ns",
    )
    if any(getattr(opened, field) != getattr(finished, field) for field in stable_fields):
        raise WorkItemGovernanceError(
            "PILOT_CANDIDATE_AUTHORIZATION_FILE_INVALID",
            "Pilot candidate authorization file changed while it was being read.",
            details={"record": name},
        )
    raw = b"".join(chunks)
    if len(raw) != opened.st_size:
        raise WorkItemGovernanceError(
            "PILOT_CANDIDATE_AUTHORIZATION_FILE_INVALID",
            "Pilot candidate authorization file changed while it was being read.",
            details={"record": name},
        )
    return raw


def _open_candidate_directory_without_symlinks(path: Path) -> int:
    candidate = Path(os.path.abspath(path.expanduser()))
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor: int | None = None
    try:
        descriptor = os.open(candidate.anchor, flags)
        for component in candidate.parts[1:]:
            next_descriptor = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except FileNotFoundError as exc:
        if descriptor is not None:
            os.close(descriptor)
        raise WorkItemGovernanceError(
            "PILOT_CANDIDATE_AUTHORIZATION_MISSING",
            "Pilot authorization requires a persisted validated candidate.",
        ) from exc
    except OSError as exc:
        if descriptor is not None:
            os.close(descriptor)
        raise WorkItemGovernanceError(
            "PILOT_CANDIDATE_OUTPUT_NOT_PRIVATE",
            "Pilot candidate paths must not traverse symbolic links.",
        ) from exc


def load_validated_pilot_candidate_for_authorization(
    candidate_dir: str | Path,
) -> dict[str, Any]:
    """Load exact candidate records only after a fresh fail-closed validation."""

    candidate = Path(os.path.abspath(Path(candidate_dir).expanduser()))
    directory_fd = _open_candidate_directory_without_symlinks(candidate)
    try:
        opened = os.fstat(directory_fd)
        if not stat.S_ISDIR(opened.st_mode) or opened.st_uid != os.getuid() or stat.S_IMODE(opened.st_mode) != 0o700:
            raise WorkItemGovernanceError(
                "PILOT_CANDIDATE_OUTPUT_NOT_PRIVATE",
                "Pilot candidate authorization requires a stable private candidate directory.",
            )
        expected_names = _RECORD_NAMES | {_VALIDATION_RECEIPT_NAME}
        if set(os.listdir(directory_fd)) != expected_names:
            raise WorkItemGovernanceError(
                "PILOT_CANDIDATE_AUTHORIZATION_FILE_SET_MISMATCH",
                "Pilot candidate authorization requires the exact validated file set.",
            )
        payloads = {name: _read_private_candidate_file(directory_fd, name) for name in sorted(_RECORD_NAMES)}
        receipt_bytes = _read_private_candidate_file(directory_fd, _VALIDATION_RECEIPT_NAME)
        finished = os.fstat(directory_fd)
        stable_directory_fields = (
            "st_dev",
            "st_ino",
            "st_uid",
            "st_mode",
            "st_nlink",
            "st_mtime_ns",
            "st_ctime_ns",
        )
        if set(os.listdir(directory_fd)) != expected_names or any(
            getattr(opened, field) != getattr(finished, field) for field in stable_directory_fields
        ):
            raise WorkItemGovernanceError(
                "PILOT_CANDIDATE_AUTHORIZATION_FILE_SET_MISMATCH",
                "Pilot candidate file set changed while it was being validated.",
            )
    finally:
        os.close(directory_fd)
    validation = validate_final_pilot_candidate_bytes(payloads)
    expected_receipt = _candidate_validation_receipt(payloads, validation)
    if receipt_bytes != canonical_record_bytes(expected_receipt):
        raise WorkItemGovernanceError(
            "PILOT_CANDIDATE_VALIDATION_RECEIPT_MISMATCH",
            "Pilot candidate validation receipt does not bind the final bytes.",
        )
    return {
        "records": {name: _strict_json_bytes(payloads[name]) for name in sorted(payloads)},
        "validation_receipt": expected_receipt,
    }


def require_validated_pilot_candidate_for_authorization(
    candidate_dir: str | Path,
) -> dict[str, Any]:
    """Fail closed unless persisted candidate bytes still match a fresh validation."""

    return load_validated_pilot_candidate_for_authorization(candidate_dir)["validation_receipt"]
