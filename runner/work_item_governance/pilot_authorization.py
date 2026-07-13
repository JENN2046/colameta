from __future__ import annotations

import fcntl
import json
import os
import stat
import secrets
from pathlib import Path
from typing import Any

from runner.work_item_governance.canonical import canonical_json, canonical_sha256
from runner.work_item_governance.errors import WorkItemGovernanceError
from runner.work_item_governance.pilot import (
    PILOT_FROZEN_CONTRACT_DIGESTS,
    build_pilot_semantic_validation_receipt,
    validate_pilot_authorization,
    validate_pilot_preflight,
    validate_pilot_scope_envelope,
)


_CAPABILITY_SEAL = secrets.token_bytes(32)


class ConsumedPilotAuthorization:
    """Non-serializable authority produced only by one-shot consumption."""

    __slots__ = (
        "_tombstone_json",
        "_authorization_json",
        "_scope_envelope_json",
        "_execution_receipt_json",
        "_preflight_json",
        "_semantic_receipt_json",
        "_seal",
    )

    def __init__(
        self,
        *,
        tombstone: dict[str, Any],
        authorization: dict[str, Any],
        scope_envelope: dict[str, Any],
        execution_receipt: dict[str, Any],
        preflight: dict[str, Any],
        semantic_receipt: dict[str, Any],
        _seal: bytes,
    ) -> None:
        if not secrets.compare_digest(_seal, _CAPABILITY_SEAL):
            raise TypeError("Consumed Pilot authority can only be minted by the decision consumer.")
        self._tombstone_json = canonical_json(tombstone)
        self._authorization_json = canonical_json(authorization)
        self._scope_envelope_json = canonical_json(scope_envelope)
        self._execution_receipt_json = canonical_json(execution_receipt)
        self._preflight_json = canonical_json(preflight)
        self._semantic_receipt_json = canonical_json(semantic_receipt)
        self._seal = _seal

    @staticmethod
    def _copy(value: str) -> dict[str, Any]:
        record = json.loads(value)
        if not isinstance(record, dict):
            raise TypeError("Consumed Pilot authority contains an invalid internal snapshot.")
        return record

    @property
    def tombstone(self) -> dict[str, Any]:
        return self._copy(self._tombstone_json)

    @property
    def authorization(self) -> dict[str, Any]:
        return self._copy(self._authorization_json)

    @property
    def scope_envelope(self) -> dict[str, Any]:
        return self._copy(self._scope_envelope_json)

    @property
    def execution_receipt(self) -> dict[str, Any]:
        return self._copy(self._execution_receipt_json)

    @property
    def preflight(self) -> dict[str, Any]:
        return self._copy(self._preflight_json)

    @property
    def semantic_receipt(self) -> dict[str, Any]:
        return self._copy(self._semantic_receipt_json)

    def __copy__(self) -> ConsumedPilotAuthorization:
        raise TypeError("Consumed Pilot authority cannot be copied.")

    def __deepcopy__(self, _memo: dict[int, Any]) -> ConsumedPilotAuthorization:
        raise TypeError("Consumed Pilot authority cannot be copied.")

    def __reduce__(self) -> Any:
        raise TypeError("Consumed Pilot authority cannot be serialized.")

    def __reduce_ex__(self, _protocol: int) -> Any:
        raise TypeError("Consumed Pilot authority cannot be serialized.")


def require_consumed_pilot_authorization(value: Any) -> ConsumedPilotAuthorization:
    if (
        type(value) is not ConsumedPilotAuthorization
        or not isinstance(value._seal, bytes)
        or not secrets.compare_digest(value._seal, _CAPABILITY_SEAL)
    ):
        raise WorkItemGovernanceError(
            "PILOT_AUTHORIZATION_CAPABILITY_INVALID",
            "Pilot Lease preparation requires the exact consumed one-shot authority capability.",
        )
    return value


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
        expected_authorization_digest: str,
    ) -> ConsumedPilotAuthorization:
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
            validate_pilot_scope_envelope(
                scope_envelope,
                execution_authorization_receipt=execution_authorization_receipt,
            )
            validate_pilot_preflight(preflight_receipt)
            validate_pilot_authorization(decision, scope_envelope=scope_envelope)
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
            return ConsumedPilotAuthorization(
                tombstone=tombstone,
                authorization=decision,
                scope_envelope=scope_envelope,
                execution_receipt=execution_authorization_receipt,
                preflight=preflight_receipt,
                semantic_receipt=semantic_receipt,
                _seal=_CAPABILITY_SEAL,
            )
        finally:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)
