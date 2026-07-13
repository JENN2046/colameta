from __future__ import annotations

import fcntl
import json
import os
import stat
import threading
from pathlib import Path
from typing import Any

from runner.work_item_governance.canonical import canonical_json, canonical_sha256
from runner.work_item_governance.errors import WorkItemGovernanceError
from runner.work_item_governance.pilot import (
    PILOT_FROZEN_CONTRACT_DIGESTS,
    build_pilot_semantic_validation_receipt,
    validate_pilot_authority_chain,
    validate_pilot_authorization,
    validate_pilot_preflight,
    validate_pilot_scope_envelope,
)


_CAPABILITY_FIELDS = (
    "_tombstone_json",
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
        "_authorization_json",
        "_scope_envelope_json",
        "_execution_receipt_json",
        "_preflight_json",
        "_authentication_conformance_json",
        "_preflight_semantic_json",
        "_semantic_receipt_json",
        "_reader",
    )

    def __new__(cls, *args: Any, **kwargs: Any) -> ConsumedPilotAuthorization:
        del args, kwargs
        raise TypeError("Consumed Pilot authority can only be minted by the decision consumer.")

    def __setattr__(self, _name: str, _value: Any) -> None:
        raise TypeError("Consumed Pilot authority is immutable.")

    def _copy(self, field: str) -> dict[str, Any]:
        value = self._reader(self, field)
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


class PilotAuthorizationDecisionConsumer:
    """Consume one exact Pilot authorization before importing runtime code.

    The permanent Tombstone is the authority fact.  It is created by atomic
    rename while a cross-process lock is held, so a crash after consumption can
    never make the same authorization reusable.
    """

    def __init__(self, *, decision_path: Path, tombstone_path: Path) -> None:
        self.decision_path = decision_path.expanduser().resolve()
        self.tombstone_path = tombstone_path.expanduser().resolve()
        if self.decision_path == self.tombstone_path:
            raise WorkItemGovernanceError(
                "PILOT_AUTHORIZATION_PATH_INVALID",
                "Decision and Tombstone paths must differ.",
            )
        self.lock_path = self.tombstone_path.with_suffix(self.tombstone_path.suffix + ".lock")

    @staticmethod
    def _read_private_regular_json(path: Path) -> dict[str, Any]:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or path.is_symlink() or info.st_uid != os.getuid():
            raise WorkItemGovernanceError(
                "PILOT_AUTHORIZATION_FILE_UNTRUSTED",
                "Pilot authorization must be an owned, non-symlink regular file.",
            )
        if stat.S_IMODE(info.st_mode) & 0o077:
            raise WorkItemGovernanceError(
                "PILOT_AUTHORIZATION_FILE_MODE_INVALID",
                "Pilot authorization file must not grant group or world access.",
            )
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise WorkItemGovernanceError(
                "PILOT_AUTHORIZATION_FILE_INVALID",
                "Pilot authorization JSON is unreadable or invalid.",
            ) from exc
        if not isinstance(value, dict):
            raise WorkItemGovernanceError("PILOT_AUTHORIZATION_FILE_INVALID", "Pilot authorization must be an object.")
        return value

    def consume(
        self,
        *,
        scope_envelope: dict[str, Any],
        execution_authorization_receipt: dict[str, Any],
        preflight_receipt: dict[str, Any],
        authentication_conformance_receipt: dict[str, Any],
        preflight_semantic_validation_receipt: dict[str, Any],
        expected_authorization_digest: str,
    ) -> dict[str, Any]:
        self.tombstone_path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        os.chmod(self.tombstone_path.parent, 0o700)
        descriptor = os.open(self.lock_path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            if self.tombstone_path.exists():
                raise WorkItemGovernanceError(
                    "PILOT_AUTHORIZATION_ALREADY_CONSUMED",
                    "Pilot one-shot authorization already has a permanent Tombstone.",
                )
            if not self.decision_path.is_file():
                raise WorkItemGovernanceError(
                    "PILOT_AUTHORIZATION_DECISION_MISSING",
                    "Pilot one-shot authorization decision is missing.",
                )
            decision = self._read_private_regular_json(self.decision_path)
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
                "scope_envelope_digest": canonical_sha256(scope_envelope),
                "execution_authorization_receipt_digest": canonical_sha256(execution_authorization_receipt),
                "preflight_receipt_digest": canonical_sha256(preflight_receipt),
                "authentication_conformance_receipt_digest": canonical_sha256(authentication_conformance_receipt),
                "preflight_semantic_validation_receipt_digest": canonical_sha256(preflight_semantic_validation_receipt),
                "semantic_validation_receipt_digest": canonical_sha256(semantic_receipt),
                "decision": "CONSUMED",
                "retry_allowed": False,
            }
            temporary = self.tombstone_path.with_suffix(self.tombstone_path.suffix + ".tmp")
            flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
            temp_fd = os.open(temporary, flags, 0o600)
            try:
                os.write(temp_fd, canonical_json(tombstone).encode("utf-8"))
                os.fsync(temp_fd)
            finally:
                os.close(temp_fd)
            os.replace(temporary, self.tombstone_path)
            os.chmod(self.tombstone_path, 0o600)
            self.decision_path.unlink()
            directory_fd = os.open(self.tombstone_path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            return {
                "tombstone": tombstone,
                "authorization": decision,
                "scope_envelope": scope_envelope,
                "execution_receipt": execution_authorization_receipt,
                "preflight": preflight_receipt,
                "authentication_conformance": authentication_conformance_receipt,
                "preflight_semantic": preflight_semantic_validation_receipt,
                "semantic_receipt": semantic_receipt,
            }
        finally:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)


def _install_consumer_owned_capability_boundary(
    consumer_class: type[PilotAuthorizationDecisionConsumer],
) -> tuple[
    type[PilotAuthorizationDecisionConsumer],
    Any,
    Any,
]:
    """Keep issuance and registry state reachable only through verified consume()."""

    lock = threading.RLock()
    registry: dict[int, dict[str, Any]] = {}
    verified_consume = consumer_class.consume

    def verified_record(value: Any) -> dict[str, Any]:
        if type(value) is not ConsumedPilotAuthorization:
            raise WorkItemGovernanceError(
                "PILOT_AUTHORIZATION_CAPABILITY_INVALID",
                "Pilot Lease preparation requires the exact consumed one-shot authority capability.",
            )
        record = registry.get(id(value))
        try:
            actual = tuple(getattr(value, field) for field in _CAPABILITY_FIELDS)
        except (AttributeError, TypeError) as exc:
            raise WorkItemGovernanceError(
                "PILOT_AUTHORIZATION_CAPABILITY_INVALID",
                "Pilot authority capability is incomplete or mutated.",
            ) from exc
        if record is None or record["capability"] is not value or actual != record["snapshots"]:
            raise WorkItemGovernanceError(
                "PILOT_AUTHORIZATION_CAPABILITY_INVALID",
                "Pilot authority capability was not issued by a verified Decision consumption or was mutated.",
            )
        return record

    def read_snapshot(value: Any, field: str) -> str:
        with lock:
            record = verified_record(value)
            return record["snapshots"][_CAPABILITY_FIELDS.index(field)]

    def consume_and_issue(self: Any, **kwargs: Any) -> ConsumedPilotAuthorization:
        payload = verified_consume(self, **kwargs)
        snapshots = tuple(
            canonical_json(payload[field])
            for field in (
                "tombstone",
                "authorization",
                "scope_envelope",
                "execution_receipt",
                "preflight",
                "authentication_conformance",
                "preflight_semantic",
                "semantic_receipt",
            )
        )
        capability = object.__new__(ConsumedPilotAuthorization)
        for field, snapshot in zip(_CAPABILITY_FIELDS, snapshots, strict=True):
            object.__setattr__(capability, field, snapshot)
        object.__setattr__(capability, "_reader", read_snapshot)
        with lock:
            registry[id(capability)] = {
                "capability": capability,
                "snapshots": snapshots,
                "state": "active",
            }
        return capability

    def require(value: Any) -> ConsumedPilotAuthorization:
        with lock:
            record = verified_record(value)
            if record["state"] != "active":
                raise WorkItemGovernanceError(
                    "PILOT_AUTHORIZATION_CAPABILITY_CONSUMED",
                    "Pilot authority capability has already been consumed by a Lease preparation attempt.",
                )
            return value

    def consume_once(value: Any) -> ConsumedPilotAuthorization:
        with lock:
            capability = require(value)
            registry[id(capability)]["state"] = "consumed"
            return capability

    consumer_class.consume = consume_and_issue  # type: ignore[method-assign]
    return consumer_class, require, consume_once


(
    PilotAuthorizationDecisionConsumer,
    require_consumed_pilot_authorization,
    consume_pilot_authorization_capability,
) = _install_consumer_owned_capability_boundary(PilotAuthorizationDecisionConsumer)
del _install_consumer_owned_capability_boundary
