from __future__ import annotations

import fcntl
import json
import os
import sqlite3
import stat
from pathlib import Path
from typing import Any

from runner.work_item_governance.canonical import canonical_json, canonical_sha256
from runner.work_item_governance.activation import canonical_path_digest
from runner.work_item_governance.errors import WorkItemGovernanceError
from runner.work_item_governance.pilot_candidate import (
    load_validated_pilot_candidate_for_authorization,
)
from runner.work_item_governance.pilot import (
    PILOT_FROZEN_CONTRACT_DIGESTS,
    build_pilot_semantic_validation_receipt,
    validate_pilot_authority_chain,
    validate_pilot_authorization,
    validate_pilot_preflight,
    validate_pilot_scope_envelope,
)
from runner.work_item_governance.preview import isoformat_utc, utc_now
from runner.work_item_governance.repository import SQLiteWorkItemLedger


_CAPABILITY_FIELDS = (
    "_tombstone_json",
    "_candidate_validation_receipt_json",
    "_authorization_json",
    "_scope_envelope_json",
    "_execution_receipt_json",
    "_preflight_json",
    "_authentication_conformance_json",
    "_preflight_semantic_json",
    "_semantic_receipt_json",
)


class ConsumedPilotAuthorization:
    """Non-serializable authority produced only by one-shot consumption."""

    __slots__ = (
        "_tombstone_json",
        "_candidate_validation_receipt_json",
        "_authorization_json",
        "_scope_envelope_json",
        "_execution_receipt_json",
        "_preflight_json",
        "_authentication_conformance_json",
        "_preflight_semantic_json",
        "_semantic_receipt_json",
        "_ledger",
        "_authorization_digest",
        "_issued_record_json",
        "_tombstone_path",
    )

    def __new__(cls, *args: Any, **kwargs: Any) -> ConsumedPilotAuthorization:
        del args, kwargs
        raise TypeError("Consumed Pilot authority can only be minted by the decision consumer.")

    def __setattr__(self, _name: str, _value: Any) -> None:
        raise TypeError("Consumed Pilot authority is immutable.")

    def _copy(self, field: str) -> dict[str, Any]:
        value = getattr(self, field)
        record = json.loads(value)
        if not isinstance(record, dict):
            raise TypeError("Consumed Pilot authority contains an invalid internal snapshot.")
        return record

    @property
    def tombstone(self) -> dict[str, Any]:
        return self._copy("_tombstone_json")

    @property
    def authorization(self) -> dict[str, Any]:
        return self._copy("_authorization_json")

    @property
    def candidate_validation_receipt(self) -> dict[str, Any]:
        return self._copy("_candidate_validation_receipt_json")

    @property
    def scope_envelope(self) -> dict[str, Any]:
        return self._copy("_scope_envelope_json")

    @property
    def execution_receipt(self) -> dict[str, Any]:
        return self._copy("_execution_receipt_json")

    @property
    def preflight(self) -> dict[str, Any]:
        return self._copy("_preflight_json")

    @property
    def authentication_conformance(self) -> dict[str, Any]:
        return self._copy("_authentication_conformance_json")

    @property
    def preflight_semantic_receipt(self) -> dict[str, Any]:
        return self._copy("_preflight_semantic_json")

    @property
    def semantic_receipt(self) -> dict[str, Any]:
        return self._copy("_semantic_receipt_json")

    def __copy__(self) -> ConsumedPilotAuthorization:
        raise TypeError("Consumed Pilot authority cannot be copied.")

    def __deepcopy__(self, _memo: dict[int, Any]) -> ConsumedPilotAuthorization:
        raise TypeError("Consumed Pilot authority cannot be copied.")

    def __reduce__(self) -> Any:
        raise TypeError("Consumed Pilot authority cannot be serialized.")

    def __reduce_ex__(self, _protocol: int) -> Any:
        raise TypeError("Consumed Pilot authority cannot be serialized.")


_PERSISTENCE_CONTROLLER_FACTORY_SEAL = object()
_ISSUED_PERSISTENCE_CONTROLLERS: dict[int, tuple[object, str]] = {}


class _PilotAuthorizationPersistenceController:
    """Short-lived, operation-scoped writer minted only after validation."""

    def __init__(self, *, ledger: SQLiteWorkItemLedger, table: str, _factory_seal: object) -> None:
        if _factory_seal is not _PERSISTENCE_CONTROLLER_FACTORY_SEAL or table not in {
            "pilot_authorization_facts",
            "pilot_authorization_claims",
        }:
            raise TypeError("Pilot authorization writers are internal one-operation capabilities.")
        self.ledger = ledger
        self.table = table
        _ISSUED_PERSISTENCE_CONTROLLERS[id(self)] = (self, table)
        try:
            self.__repository_control_binding = ledger._bind_activation_controller(self)
        except Exception:
            _ISSUED_PERSISTENCE_CONTROLLERS.pop(id(self), None)
            raise

    def insert(self, sql: str, parameters: tuple[Any, ...]) -> None:
        try:
            with self.ledger.write_transaction() as connection:
                session = self.ledger.authorize_activation_control_write(
                    connection,
                    controller=self,
                    controller_binding=self.__repository_control_binding,
                )
                try:
                    connection.execute(sql, parameters)
                finally:
                    self.ledger.finalize_activation_control_write(connection, session=session)
        finally:
            _ISSUED_PERSISTENCE_CONTROLLERS.pop(id(self), None)
            self.ledger._release_activation_controller(self, self.__repository_control_binding)


def _is_issued_pilot_authorization_persistence_controller(value: object) -> bool:
    return bool(
        type(value) is _PilotAuthorizationPersistenceController
        and _ISSUED_PERSISTENCE_CONTROLLERS.get(id(value)) == (value, value.table)
    )


def _pilot_authorization_persistence_controller_table(value: object) -> str | None:
    if not _is_issued_pilot_authorization_persistence_controller(value):
        return None
    return value.table


def _persist_authorization_fact(ledger: SQLiteWorkItemLedger, record: dict[str, Any]) -> None:
    controller = _PilotAuthorizationPersistenceController(
        ledger=ledger,
        table="pilot_authorization_facts",
        _factory_seal=_PERSISTENCE_CONTROLLER_FACTORY_SEAL,
    )
    controller.insert(
        "INSERT INTO pilot_authorization_facts("
        "authorization_digest,schema_version,tombstone_digest,tombstone_path_digest,"
        "payload_digest,issued_record_json,issued_at) VALUES(?,?,?,?,?,?,?)",
        (
            record["authorization_digest"],
            record["schema_version"],
            record["tombstone_digest"],
            record["tombstone_path_digest"],
            record["payload_digest"],
            canonical_json(record),
            record["issued_at"],
        ),
    )


def _persist_authorization_claim(
    ledger: SQLiteWorkItemLedger,
    *,
    authorization_digest: str,
    claim_digest: str,
    claimed_at: str,
) -> None:
    controller = _PilotAuthorizationPersistenceController(
        ledger=ledger,
        table="pilot_authorization_claims",
        _factory_seal=_PERSISTENCE_CONTROLLER_FACTORY_SEAL,
    )
    controller.insert(
        "INSERT INTO pilot_authorization_claims("
        "authorization_digest,schema_version,claim_digest,claimed_at) VALUES(?,?,?,?)",
        (
            authorization_digest,
            "wig_p3_pilot_authorization_claim.v1",
            claim_digest,
            claimed_at,
        ),
    )


def _open_directory_without_symlinks(path: Path) -> int:
    directory = Path(os.path.abspath(path.expanduser()))
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor: int | None = None
    try:
        descriptor = os.open(directory.anchor, flags)
        for component in directory.parts[1:]:
            next_descriptor = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except OSError as exc:
        if descriptor is not None:
            os.close(descriptor)
        raise WorkItemGovernanceError(
            "PILOT_AUTHORIZATION_PATH_INVALID",
            "Pilot authorization paths must not traverse symbolic links.",
        ) from exc


def _strict_json_object(raw: bytes) -> dict[str, Any]:
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


def _read_private_regular_json_at(
    directory_fd: int, name: str
) -> tuple[dict[str, Any], tuple[int, int]]:
    try:
        path_info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except OSError as exc:
        raise WorkItemGovernanceError(
            "PILOT_AUTHORIZATION_FILE_INVALID",
            "Pilot authorization JSON is unreadable or invalid.",
        ) from exc
    if (
        stat.S_ISLNK(path_info.st_mode)
        or not stat.S_ISREG(path_info.st_mode)
        or path_info.st_uid != os.getuid()
        or path_info.st_nlink != 1
    ):
        raise WorkItemGovernanceError(
            "PILOT_AUTHORIZATION_FILE_UNTRUSTED",
            "Pilot authorization must be an owned, non-symlink regular file.",
        )
    if stat.S_IMODE(path_info.st_mode) & 0o077:
        raise WorkItemGovernanceError(
            "PILOT_AUTHORIZATION_FILE_MODE_INVALID",
            "Pilot authorization file must not grant group or world access.",
        )
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(name, flags, dir_fd=directory_fd)
        try:
            opened = os.fstat(descriptor)
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_dev != path_info.st_dev
                or opened.st_ino != path_info.st_ino
                or opened.st_uid != os.getuid()
                or opened.st_nlink != 1
                or stat.S_IMODE(opened.st_mode) & 0o077
            ):
                raise WorkItemGovernanceError(
                    "PILOT_AUTHORIZATION_FILE_UNTRUSTED",
                    "Pilot authorization changed while it was being opened.",
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
            "PILOT_AUTHORIZATION_FILE_INVALID",
            "Pilot authorization JSON is unreadable or invalid.",
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
            "PILOT_AUTHORIZATION_FILE_UNTRUSTED",
            "Pilot authorization changed while it was being read.",
        )
    raw = b"".join(chunks)
    if len(raw) != opened.st_size:
        raise WorkItemGovernanceError(
            "PILOT_AUTHORIZATION_FILE_UNTRUSTED",
            "Pilot authorization changed while it was being read.",
        )
    try:
        value = _strict_json_object(raw)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise WorkItemGovernanceError(
            "PILOT_AUTHORIZATION_FILE_INVALID",
            "Pilot authorization JSON is unreadable or invalid.",
        ) from exc
    return value, (opened.st_dev, opened.st_ino)


def _read_private_regular_json(path: Path) -> dict[str, Any]:
    directory_fd = _open_directory_without_symlinks(path.parent)
    try:
        value, _ = _read_private_regular_json_at(directory_fd, path.name)
        return value
    finally:
        os.close(directory_fd)


class PilotAuthorizationDecisionConsumer:
    """Consume one exact Pilot authorization before importing runtime code.

    The append-only Ledger fact is authoritative and the permanent filesystem
    Tombstone is its required audit mirror. Both are bound and rechecked before
    the unique claim fact can be inserted.
    """

    def __init__(
        self,
        *,
        candidate_dir: Path,
        decision_path: Path,
        tombstone_path: Path,
        ledger: SQLiteWorkItemLedger,
    ) -> None:
        # Keep final path components unresolved so trust checks still see links.
        self.candidate_dir = Path(os.path.abspath(candidate_dir.expanduser()))
        self.decision_path = Path(os.path.abspath(decision_path.expanduser()))
        self.tombstone_path = Path(os.path.abspath(tombstone_path.expanduser()))
        self.ledger = ledger
        if self.decision_path == self.tombstone_path:
            raise WorkItemGovernanceError(
                "PILOT_AUTHORIZATION_PATH_INVALID",
                "Decision and Tombstone paths must differ.",
            )
        self.lock_path = self.tombstone_path.with_suffix(self.tombstone_path.suffix + ".lock")

    def consume(
        self,
        *,
        scope_envelope: dict[str, Any],
        execution_authorization_receipt: dict[str, Any],
        preflight_receipt: dict[str, Any],
        authentication_conformance_receipt: dict[str, Any],
        preflight_semantic_validation_receipt: dict[str, Any],
        expected_authorization_digest: str,
    ) -> ConsumedPilotAuthorization:
        candidate = load_validated_pilot_candidate_for_authorization(
            self.candidate_dir
        )
        candidate_records = candidate["records"]
        candidate_validation_receipt = candidate["validation_receipt"]
        supplied_scope = json.loads(canonical_json(scope_envelope))
        supplied_execution = json.loads(canonical_json(execution_authorization_receipt))
        input_mismatches: list[str] = []
        if canonical_json(supplied_execution) != canonical_json(
            candidate_records["execution-authorization-receipt.json"]
        ):
            input_mismatches.append("execution_authorization_receipt")
        if canonical_json(supplied_scope) != canonical_json(
            candidate_records["scope-envelope.json"]
        ):
            input_mismatches.append("scope_envelope")
        if input_mismatches:
            raise WorkItemGovernanceError(
                "PILOT_AUTHORIZATION_CANDIDATE_MISMATCH",
                "Pilot authorization inputs differ from the validated candidate.",
                details={"mismatched_records": input_mismatches},
            )
        # From this point onward consume only private JSON snapshots. In
        # particular, scope and execution come from the validated candidate,
        # never from caller-owned mutable dictionaries.
        scope_envelope = candidate_records["scope-envelope.json"]
        execution_authorization_receipt = candidate_records[
            "execution-authorization-receipt.json"
        ]
        preflight_receipt = json.loads(canonical_json(preflight_receipt))
        authentication_conformance_receipt = json.loads(
            canonical_json(authentication_conformance_receipt)
        )
        preflight_semantic_validation_receipt = json.loads(
            canonical_json(preflight_semantic_validation_receipt)
        )
        tombstone_directory_fd = _open_directory_without_symlinks(
            self.tombstone_path.parent
        )
        tombstone_directory_info = os.fstat(tombstone_directory_fd)
        if (
            tombstone_directory_info.st_uid != os.getuid()
            or stat.S_IMODE(tombstone_directory_info.st_mode) != 0o700
        ):
            os.close(tombstone_directory_fd)
            raise WorkItemGovernanceError(
                "PILOT_AUTHORIZATION_PATH_INVALID",
                "Pilot authorization Tombstone directory must be owned and mode-0700.",
            )
        try:
            decision_directory_fd = _open_directory_without_symlinks(
                self.decision_path.parent
            )
        except Exception:
            os.close(tombstone_directory_fd)
            raise
        lock_flags = (
            os.O_CREAT
            | os.O_RDWR
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        try:
            descriptor = os.open(
                self.lock_path.name,
                lock_flags,
                0o600,
                dir_fd=tombstone_directory_fd,
            )
        except Exception:
            os.close(decision_directory_fd)
            os.close(tombstone_directory_fd)
            raise
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            try:
                tombstone_info = os.stat(
                    self.tombstone_path.name,
                    dir_fd=tombstone_directory_fd,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                tombstone_info = None
            if tombstone_info is not None and stat.S_ISLNK(tombstone_info.st_mode):
                raise WorkItemGovernanceError(
                    "PILOT_AUTHORIZATION_PATH_INVALID",
                    "Pilot authorization Tombstone must not be a symbolic link.",
                )
            if tombstone_info is not None:
                raise WorkItemGovernanceError(
                    "PILOT_AUTHORIZATION_ALREADY_CONSUMED",
                    "Pilot one-shot authorization already has a permanent Tombstone.",
                )
            try:
                os.stat(
                    self.decision_path.name,
                    dir_fd=decision_directory_fd,
                    follow_symlinks=False,
                )
            except FileNotFoundError as exc:
                raise WorkItemGovernanceError(
                    "PILOT_AUTHORIZATION_DECISION_MISSING",
                    "Pilot one-shot authorization decision is missing.",
                ) from exc
            decision, decision_identity = _read_private_regular_json_at(
                decision_directory_fd, self.decision_path.name
            )
            if canonical_json(decision) != canonical_json(
                candidate_records["PILOT_AUTHORIZATION_TEMPLATE.json"]
            ):
                raise WorkItemGovernanceError(
                    "PILOT_AUTHORIZATION_CANDIDATE_MISMATCH",
                    "Pilot authorization decision differs from the validated candidate.",
                    details={"mismatched_records": ["pilot_authorization"]},
                )
            validate_pilot_authority_chain(
                decision,
                scope_envelope=scope_envelope,
                execution_authorization_receipt=execution_authorization_receipt,
                preflight_receipt=preflight_receipt,
                authentication_conformance_receipt=authentication_conformance_receipt,
                semantic_validation_receipt=preflight_semantic_validation_receipt,
            )
            digest = canonical_sha256(decision)
            if digest != expected_authorization_digest:
                raise WorkItemGovernanceError(
                    "PILOT_AUTHORIZATION_DIGEST_MISMATCH",
                    "Pilot authorization differs from the exact reviewed digest.",
                )
            semantic_receipt = build_pilot_semantic_validation_receipt(
                stage="decision_consumption",
                input_bindings={
                    "candidate_manifest_sha256": decision["bindings"]["candidate_manifest_sha256"],
                    "scope_envelope_digest": canonical_sha256(scope_envelope),
                    "storage_schema_contract_digest": PILOT_FROZEN_CONTRACT_DIGESTS["storage_schema_contract_digest"],
                    "fact_reconciliation_contract_digest": PILOT_FROZEN_CONTRACT_DIGESTS["fact_reconciliation_contract_digest"],
                    "authorization_digest": digest,
                    "project_snapshot_digest": scope_envelope["target_project"]["project_snapshot_digest"],
                    "runtime_binding_digest": canonical_sha256(preflight_receipt["execution_context"]),
                    "ledger_state_digest": canonical_sha256(preflight_receipt["ledger"]),
                },
            )
            tombstone = {
                "schema_version": "wig_p3_bounded_single_project_pilot_authorization_tombstone.v1",
                "gate_id": decision["gate_id"],
                "authorization_digest": digest,
                "candidate_validation_receipt_digest": canonical_sha256(
                    candidate_validation_receipt
                ),
                "scope_envelope_digest": canonical_sha256(scope_envelope),
                "execution_authorization_receipt_digest": canonical_sha256(execution_authorization_receipt),
                "preflight_receipt_digest": canonical_sha256(preflight_receipt),
                "authentication_conformance_receipt_digest": canonical_sha256(authentication_conformance_receipt),
                "preflight_semantic_validation_receipt_digest": canonical_sha256(preflight_semantic_validation_receipt),
                "semantic_validation_receipt_digest": canonical_sha256(semantic_receipt),
                "decision": "CONSUMED",
                "retry_allowed": False,
            }
            temporary_name = self.tombstone_path.name + ".tmp"
            flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
            temp_fd = os.open(
                temporary_name, flags, 0o600, dir_fd=tombstone_directory_fd
            )
            try:
                remaining = memoryview(canonical_json(tombstone).encode("utf-8"))
                while remaining:
                    written = os.write(temp_fd, remaining)
                    remaining = remaining[written:]
                os.fsync(temp_fd)
            finally:
                os.close(temp_fd)
            os.replace(
                temporary_name,
                self.tombstone_path.name,
                src_dir_fd=tombstone_directory_fd,
                dst_dir_fd=tombstone_directory_fd,
            )
            decision_after = os.stat(
                self.decision_path.name,
                dir_fd=decision_directory_fd,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISREG(decision_after.st_mode)
                or (decision_after.st_dev, decision_after.st_ino)
                != decision_identity
            ):
                raise WorkItemGovernanceError(
                    "PILOT_AUTHORIZATION_FILE_UNTRUSTED",
                    "Pilot authorization changed before one-shot consumption.",
                )
            os.unlink(self.decision_path.name, dir_fd=decision_directory_fd)
            os.fsync(tombstone_directory_fd)
            if decision_directory_fd != tombstone_directory_fd:
                os.fsync(decision_directory_fd)
            payload = {
                "tombstone": tombstone,
                "candidate_validation_receipt": candidate_validation_receipt,
                "authorization": decision,
                "scope_envelope": scope_envelope,
                "execution_receipt": execution_authorization_receipt,
                "preflight": preflight_receipt,
                "authentication_conformance": authentication_conformance_receipt,
                "preflight_semantic": preflight_semantic_validation_receipt,
                "semantic_receipt": semantic_receipt,
            }
            capability = object.__new__(ConsumedPilotAuthorization)
            snapshots = tuple(
                canonical_json(payload[field])
                for field in (
                    "tombstone",
                    "candidate_validation_receipt",
                    "authorization",
                    "scope_envelope",
                    "execution_receipt",
                    "preflight",
                    "authentication_conformance",
                    "preflight_semantic",
                    "semantic_receipt",
                )
            )
            tombstone_path_digest = canonical_path_digest(self.tombstone_path)
            issued_record = {
                "schema_version": "wig_p3_pilot_persisted_authority.v2",
                "authorization_digest": digest,
                "tombstone_digest": canonical_sha256(tombstone),
                "tombstone_path_digest": tombstone_path_digest,
                "payload_digest": canonical_sha256(list(snapshots)),
                "issued_at": isoformat_utc(utc_now()),
            }
            issued_record_json = canonical_json(issued_record)
            try:
                _persist_authorization_fact(self.ledger, issued_record)
            except sqlite3.IntegrityError as exc:
                raise WorkItemGovernanceError(
                    "PILOT_AUTHORIZATION_ALREADY_CONSUMED",
                    "Pilot authorization already has persisted issuance or consumption state.",
                ) from exc
            for field, snapshot in zip(_CAPABILITY_FIELDS, snapshots, strict=True):
                object.__setattr__(capability, field, snapshot)
            object.__setattr__(capability, "_ledger", self.ledger)
            object.__setattr__(capability, "_authorization_digest", digest)
            object.__setattr__(capability, "_issued_record_json", issued_record_json)
            object.__setattr__(capability, "_tombstone_path", self.tombstone_path)
            return capability
        finally:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)
                os.close(decision_directory_fd)
                os.close(tombstone_directory_fd)

def _verified_persisted_authority(
    value: Any,
) -> tuple[SQLiteWorkItemLedger, str, str]:
    if type(value) is not ConsumedPilotAuthorization:
        raise WorkItemGovernanceError(
            "PILOT_AUTHORIZATION_CAPABILITY_INVALID",
            "Pilot Lease preparation requires one exact persisted one-shot authority.",
        )
    try:
        snapshots = tuple(getattr(value, field) for field in _CAPABILITY_FIELDS)
        ledger = value._ledger
        authorization_digest_field = value._authorization_digest
        issued_record_json = value._issued_record_json
        tombstone_path = value._tombstone_path
        records = tuple(json.loads(snapshot) for snapshot in snapshots)
        issued_record = json.loads(issued_record_json)
    except (AttributeError, TypeError, json.JSONDecodeError) as exc:
        raise WorkItemGovernanceError(
            "PILOT_AUTHORIZATION_CAPABILITY_INVALID",
            "Persisted Pilot authority is incomplete or malformed.",
        ) from exc
    if (
        not isinstance(ledger, SQLiteWorkItemLedger)
        or not all(isinstance(record, dict) for record in records)
    ):
        raise WorkItemGovernanceError(
            "PILOT_AUTHORIZATION_CAPABILITY_INVALID",
            "Persisted Pilot authority has invalid runtime or snapshot types.",
        )
    (
        tombstone,
        candidate_validation_receipt,
        authorization,
        scope,
        execution,
        preflight,
        authentication,
        semantic,
        decision_semantic,
    ) = records
    authorization_digest = canonical_sha256(authorization)
    expected_tombstone_bindings = {
        "authorization_digest": authorization_digest,
        "candidate_validation_receipt_digest": canonical_sha256(
            candidate_validation_receipt
        ),
        "scope_envelope_digest": canonical_sha256(scope),
        "execution_authorization_receipt_digest": canonical_sha256(execution),
        "preflight_receipt_digest": canonical_sha256(preflight),
        "authentication_conformance_receipt_digest": canonical_sha256(authentication),
        "preflight_semantic_validation_receipt_digest": canonical_sha256(semantic),
        "semantic_validation_receipt_digest": canonical_sha256(decision_semantic),
    }
    expected_issued = {
        "schema_version": "wig_p3_pilot_persisted_authority.v2",
        "authorization_digest": authorization_digest,
        "tombstone_digest": canonical_sha256(tombstone),
        "tombstone_path_digest": canonical_path_digest(tombstone_path),
        "payload_digest": canonical_sha256(list(snapshots)),
        "issued_at": issued_record.get("issued_at") if isinstance(issued_record, dict) else None,
    }
    if (
        authorization_digest_field != authorization_digest
        or not isinstance(issued_record, dict)
        or issued_record != expected_issued
        or any(tombstone.get(field) != expected for field, expected in expected_tombstone_bindings.items())
        or tombstone.get("decision") != "CONSUMED"
        or tombstone.get("retry_allowed") is not False
    ):
        raise WorkItemGovernanceError(
            "PILOT_AUTHORIZATION_CAPABILITY_INVALID",
            "Persisted Pilot authority differs from its Tombstone or exact payload bindings.",
        )
    try:
        persisted_tombstone = _read_private_regular_json(tombstone_path)
    except (OSError, WorkItemGovernanceError) as exc:
        raise WorkItemGovernanceError(
            "PILOT_AUTHORIZATION_TOMBSTONE_INVALID",
            "The required permanent authorization Tombstone is absent or untrusted.",
        ) from exc
    if canonical_json(persisted_tombstone) != canonical_json(tombstone):
        raise WorkItemGovernanceError(
            "PILOT_AUTHORIZATION_TOMBSTONE_INVALID",
            "The permanent authorization Tombstone differs from the consumed authority.",
        )
    with ledger.read_connection() as connection:
        row = connection.execute(
            "SELECT * FROM pilot_authorization_facts WHERE authorization_digest=?",
            (authorization_digest,),
        ).fetchone()
        claimed = connection.execute(
            "SELECT 1 FROM pilot_authorization_claims WHERE authorization_digest=?",
            (authorization_digest,),
        ).fetchone()
    if (
        row is None
        or str(row["issued_record_json"]) != issued_record_json
        or str(row["tombstone_digest"]) != expected_issued["tombstone_digest"]
        or str(row["tombstone_path_digest"]) != expected_issued["tombstone_path_digest"]
        or str(row["payload_digest"]) != expected_issued["payload_digest"]
    ):
        raise WorkItemGovernanceError(
            "PILOT_AUTHORIZATION_CAPABILITY_INVALID",
            "Persisted Pilot authorization fact is absent or differs from its exact bindings.",
        )
    if claimed is not None:
        raise WorkItemGovernanceError(
            "PILOT_AUTHORIZATION_CAPABILITY_CONSUMED",
            "Persisted Pilot authority already has its unique claim fact.",
        )
    return ledger, authorization_digest, issued_record_json


def require_consumed_pilot_authorization(value: Any) -> ConsumedPilotAuthorization:
    _verified_persisted_authority(value)
    return value


def consume_pilot_authorization_capability(value: Any) -> ConsumedPilotAuthorization:
    """Atomically burn persisted one-shot authority before Lease validation."""

    ledger, authorization_digest, issued_record_json = _verified_persisted_authority(value)
    claimed_at = isoformat_utc(utc_now())
    claim_digest = canonical_sha256(
        {
            "authorization_digest": authorization_digest,
            "issued_record_digest": canonical_sha256(json.loads(issued_record_json)),
            "claimed_at": claimed_at,
        }
    )
    try:
        _persist_authorization_claim(
            ledger,
            authorization_digest=authorization_digest,
            claim_digest=claim_digest,
            claimed_at=claimed_at,
        )
    except sqlite3.IntegrityError as exc:
        raise WorkItemGovernanceError(
            "PILOT_AUTHORIZATION_CAPABILITY_CONSUMED",
            "Persisted Pilot authority has already been claimed by another Lease preparation attempt.",
        ) from exc
    return value
