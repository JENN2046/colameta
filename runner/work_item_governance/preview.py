from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from runner.work_item_governance.canonical import canonical_json, canonical_sha256
from runner.work_item_governance.contracts import (
    DEFAULT_PREVIEW_TTL_SECONDS,
    MAX_PREVIEW_TTL_SECONDS,
    SCHEMA_VERSIONS,
)
from runner.work_item_governance.errors import WorkItemGovernanceError
from runner.work_item_governance.ids import new_stable_id
from runner.work_item_governance.repository import SQLiteWorkItemLedger


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def isoformat_utc(value: datetime) -> str:
    normalized = value.astimezone(timezone.utc)
    return normalized.isoformat(timespec="microseconds").replace("+00:00", "Z")


def parse_timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise WorkItemGovernanceError("PREVIEW_TIMESTAMP_INVALID", f"{field} must be an ISO timestamp.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise WorkItemGovernanceError("PREVIEW_TIMESTAMP_INVALID", f"{field} must be an ISO timestamp.") from exc
    if parsed.tzinfo is None:
        raise WorkItemGovernanceError("PREVIEW_TIMESTAMP_INVALID", f"{field} must include a timezone.")
    return parsed.astimezone(timezone.utc)


class PreviewCodec:
    def __init__(
        self,
        ledger: SQLiteWorkItemLedger,
        *,
        now: Callable[[], datetime] = utc_now,
    ) -> None:
        self.ledger = ledger
        self.now = now
        self.project_binding = canonical_sha256({"project_root": str(Path(ledger.project_root).resolve())})

    def issue(
        self,
        operation: str,
        command: dict[str, Any],
        *,
        ttl_seconds: int = DEFAULT_PREVIEW_TTL_SECONDS,
        generated_ids: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or not 1 <= ttl_seconds <= MAX_PREVIEW_TTL_SECONDS:
            raise WorkItemGovernanceError(
                "PREVIEW_TTL_INVALID",
                "Preview TTL is outside the allowed range.",
                details={"minimum": 1, "maximum": MAX_PREVIEW_TTL_SECONDS},
            )
        issued_at = self.now().astimezone(timezone.utc)
        payload = {
            "schema_version": SCHEMA_VERSIONS["preview"],
            "preview_id": new_stable_id("preview"),
            "operation": operation,
            "project_binding": self.project_binding,
            "issued_at": isoformat_utc(issued_at),
            "expires_at": isoformat_utc(issued_at + timedelta(seconds=ttl_seconds)),
            "ttl_seconds": ttl_seconds,
            "content_digest": canonical_sha256(command),
            "command": command,
            "generated_ids": dict(generated_ids or {}),
        }
        payload["signature"] = self._sign(payload)
        return payload

    def verify(self, preview: Any, *, expected_operation: str) -> dict[str, Any]:
        if not isinstance(preview, dict):
            raise WorkItemGovernanceError("PREVIEW_REQUIRED", "Apply requires the complete preview object.")
        required = {
            "schema_version",
            "preview_id",
            "operation",
            "project_binding",
            "issued_at",
            "expires_at",
            "ttl_seconds",
            "content_digest",
            "command",
            "generated_ids",
            "signature",
        }
        if set(preview) != required:
            raise WorkItemGovernanceError(
                "PREVIEW_SHAPE_INVALID",
                "Preview fields do not match the signed contract.",
                details={"missing": sorted(required - set(preview)), "extra": sorted(set(preview) - required)},
            )
        if preview.get("schema_version") != SCHEMA_VERSIONS["preview"]:
            raise WorkItemGovernanceError("PREVIEW_SCHEMA_UNSUPPORTED", "Preview schema version is unsupported.")
        if preview.get("operation") != expected_operation:
            raise WorkItemGovernanceError(
                "PREVIEW_OPERATION_MISMATCH",
                "Preview was issued for a different operation.",
                details={"expected": expected_operation, "actual": preview.get("operation")},
            )
        if preview.get("project_binding") != self.project_binding:
            raise WorkItemGovernanceError("PREVIEW_PROJECT_MISMATCH", "Preview belongs to a different project.")
        signature = preview.get("signature")
        if not isinstance(signature, str) or not hmac.compare_digest(signature, self._sign(preview)):
            raise WorkItemGovernanceError("PREVIEW_SIGNATURE_INVALID", "Preview signature is invalid.")
        command = preview.get("command")
        if not isinstance(command, dict) or preview.get("content_digest") != canonical_sha256(command):
            raise WorkItemGovernanceError("PREVIEW_CONTENT_MISMATCH", "Preview content digest does not match its command.")
        issued_at = parse_timestamp(preview.get("issued_at"), "issued_at")
        expires_at = parse_timestamp(preview.get("expires_at"), "expires_at")
        ttl = preview.get("ttl_seconds")
        if isinstance(ttl, bool) or not isinstance(ttl, int) or not 1 <= ttl <= MAX_PREVIEW_TTL_SECONDS:
            raise WorkItemGovernanceError("PREVIEW_TTL_INVALID", "Preview TTL is invalid.")
        if expires_at != issued_at + timedelta(seconds=ttl):
            raise WorkItemGovernanceError("PREVIEW_TTL_MISMATCH", "Preview expiration does not match its signed TTL.")
        if self.now().astimezone(timezone.utc) > expires_at:
            raise WorkItemGovernanceError("PREVIEW_EXPIRED", "Preview has expired.")
        return dict(preview)

    def _sign(self, preview: dict[str, Any]) -> str:
        unsigned = {key: value for key, value in preview.items() if key != "signature"}
        return hmac.new(
            self.ledger.get_or_create_signing_key(),
            canonical_json(unsigned).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
