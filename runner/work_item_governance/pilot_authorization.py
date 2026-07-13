from __future__ import annotations

import fcntl
import json
import os
import stat
from pathlib import Path
from typing import Any

from runner.work_item_governance.canonical import canonical_json, canonical_sha256
from runner.work_item_governance.errors import WorkItemGovernanceError
from runner.work_item_governance.pilot import validate_pilot_authorization


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
            validate_pilot_authorization(decision, scope_envelope=scope_envelope)
            digest = canonical_sha256(decision)
            if digest != expected_authorization_digest:
                raise WorkItemGovernanceError(
                    "PILOT_AUTHORIZATION_DIGEST_MISMATCH",
                    "Pilot authorization differs from the exact reviewed digest.",
                )
            tombstone = {
                "schema_version": "wig_p3_bounded_single_project_pilot_authorization_tombstone.v1",
                "gate_id": decision["gate_id"],
                "authorization_digest": digest,
                "scope_envelope_digest": canonical_sha256(scope_envelope),
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
            return tombstone
        finally:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)
