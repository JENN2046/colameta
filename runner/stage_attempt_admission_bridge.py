from __future__ import annotations

import os
import re
from typing import Any, Callable

from runner.confirmation_store import ConfirmationStore
from runner.core_confirmation import confirmation_apply_guard
from runner.work_item_governance.canonical import canonical_sha256
from runner.work_item_governance.errors import WorkItemGovernanceError
from runner.work_item_governance.ids import is_stable_id


GRANT_TTL_SECONDS = 900
GRANTS_RELATIVE_DIR = os.path.join(
    ".colameta", "runtime", "stage-attempt-admission-grants"
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class StageAttemptAdmissionGrantIssuer:
    """Transport one governance-signed preview behind an opaque handle.

    This object belongs to the authenticated composition root.  It does not
    mint authority: the nested Work Item governance preview is the authority.
    """

    def __init__(self, project_root: str, *, store: ConfirmationStore | None = None) -> None:
        self.project_root = os.path.abspath(os.path.expanduser(project_root))
        self._store = store

    def _grant_store(self) -> ConfirmationStore:
        if self._store is None:
            self._store = ConfirmationStore(
                self.project_root,
                GRANTS_RELATIVE_DIR,
                GRANT_TTL_SECONDS,
            )
        return self._store

    def store_signed_preview(self, preview_result: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(preview_result, dict) or preview_result.get("status") != "preview_ready":
            raise WorkItemGovernanceError(
                "STAGE_ATTEMPT_GRANT_PREVIEW_INVALID",
                "A successful governance Attempt preview is required.",
            )
        preview = preview_result.get("preview")
        if not isinstance(preview, dict):
            raise WorkItemGovernanceError(
                "STAGE_ATTEMPT_GRANT_PREVIEW_INVALID",
                "The governance Attempt preview is missing.",
            )
        grant_id = preview.get("preview_id")
        if not is_stable_id(grant_id, "preview"):
            raise WorkItemGovernanceError(
                "STAGE_ATTEMPT_GRANT_ID_INVALID",
                "The governance preview does not contain an opaque stable handle.",
            )
        signed = preview.get("command")
        if not isinstance(signed, dict):
            raise WorkItemGovernanceError(
                "STAGE_ATTEMPT_GRANT_PREVIEW_INVALID",
                "The governance preview does not contain a signed command.",
            )
        execution_context = _normalize_execution_context(signed.get("execution_context"))
        record = {
            "artifact_kind": "stage_attempt_admission_grant_transport.v1",
            "grant_id": grant_id,
            "project_root": self.project_root,
            "created_at": preview.get("issued_at"),
            "expires_at": preview.get("expires_at"),
            "nested_preview": preview,
            "nested_preview_sha256": canonical_sha256(preview),
            "execution_context_sha256": canonical_sha256(execution_context),
            "attempt_admission": None,
        }
        self._grant_store().write(grant_id, record)
        return {
            "status": "grant_ready",
            "grant_id": grant_id,
            "task_id": execution_context["task_id"],
            "target_authorized": True,
            "expires_at": preview.get("expires_at"),
            "work_item_written": False,
            "attempt_created": False,
            "provider_started": False,
        }

    def load_signed_preview_for_apply(
        self,
        grant_id: str,
        *,
        expected_execution_context: dict[str, Any],
    ) -> dict[str, Any]:
        record, preview, _context = _load_grant_record(
            self._grant_store(),
            self.project_root,
            grant_id,
            expected_execution_context,
        )
        admission = record.get("attempt_admission")
        if admission is not None and not isinstance(admission, dict):
            raise WorkItemGovernanceError(
                "STAGE_ATTEMPT_ADMISSION_RECORD_INVALID",
                "Attempt admission state is malformed.",
            )
        return preview

    def record_attempt_admission(
        self,
        grant_id: str,
        *,
        expected_execution_context: dict[str, Any],
        apply_result: dict[str, Any],
    ) -> dict[str, Any]:
        record, preview, context = _load_grant_record(
            self._grant_store(),
            self.project_root,
            grant_id,
            expected_execution_context,
        )
        attempt = apply_result.get("attempt")
        signed = preview.get("command")
        command = signed.get("attempt_command") if isinstance(signed, dict) else None
        if (
            not isinstance(attempt, dict)
            or not isinstance(command, dict)
            or attempt.get("work_item_id") != command.get("work_item_id")
            or attempt.get("task_version") != command.get("task_version")
            or not isinstance(attempt.get("attempt_id"), str)
        ):
            raise WorkItemGovernanceError(
                "STAGE_ATTEMPT_ADMISSION_RESULT_MISMATCH",
                "Canonical Attempt result does not match the signed grant target.",
            )
        admission = {
            "status": "attempt_admitted",
            "grant_id": grant_id,
            "task_id": context["task_id"],
            "work_item_id": attempt["work_item_id"],
            "task_version": attempt["task_version"],
            "attempt_id": attempt["attempt_id"],
            "source_event_key": attempt.get("source_event_key"),
            "preview_id": apply_result.get("preview_id"),
            "binding_sha256": canonical_sha256(
                {
                    "grant_id": grant_id,
                    "execution_context": context,
                    "work_item_id": attempt["work_item_id"],
                    "task_version": attempt["task_version"],
                    "attempt_id": attempt["attempt_id"],
                }
            ),
        }
        existing = record.get("attempt_admission")
        if existing is not None and existing != admission:
            raise WorkItemGovernanceError(
                "STAGE_ATTEMPT_ADMISSION_REPLAY_MISMATCH",
                "Attempt admission replay differs from the durable exact result.",
            )
        record["attempt_admission"] = admission
        self._grant_store().write(grant_id, record)
        return dict(admission)


class StageAttemptAdmissionBridge:
    """Read-only Stage-facing view of opaque Attempt admission state."""

    def __init__(
        self,
        project_root: str,
        *,
        inspect_signed_transport: Callable[
            [dict[str, Any], dict[str, Any]], dict[str, Any]
        ],
        resolve_attempt_artifacts: Callable[[str, int, str], dict[str, Any]],
        store: ConfirmationStore | None = None,
    ) -> None:
        self.project_root = os.path.abspath(os.path.expanduser(project_root))
        self._inspect_signed_transport = inspect_signed_transport
        self._resolve_attempt_artifacts = resolve_attempt_artifacts
        self._store = store

    def _grant_store(self) -> ConfirmationStore:
        if self._store is None:
            self._store = ConfirmationStore(
                self.project_root,
                GRANTS_RELATIVE_DIR,
                GRANT_TTL_SECONDS,
            )
        return self._store

    def inspect_task_grant(
        self,
        grant_id: str,
        *,
        expected_execution_context: dict[str, Any],
    ) -> dict[str, Any]:
        _record, preview, context = _load_grant_record(
            self._grant_store(), self.project_root, grant_id, expected_execution_context
        )
        inspected = self._inspect_signed_transport(preview, context)
        return {
            "status": "grant_valid",
            "grant_id": grant_id,
            "task_id": context["task_id"],
            "target_authorized": True,
            "work_item_id": inspected.get("work_item_id"),
            "task_version": inspected.get("task_version"),
            "attempt_created": False,
        }

    def inspect_task_attempt_admission(
        self,
        grant_id: str,
        *,
        expected_execution_context: dict[str, Any],
    ) -> dict[str, Any]:
        record, _preview, context = _load_grant_record(
            self._grant_store(), self.project_root, grant_id, expected_execution_context
        )
        self.inspect_task_grant(
            grant_id, expected_execution_context=expected_execution_context
        )
        admission = record.get("attempt_admission")
        if admission is None:
            return {
                "status": "governance_admission_required",
                "grant_id": grant_id,
                "task_id": context["task_id"],
                "attempt_created": False,
            }
        if not isinstance(admission, dict):
            raise WorkItemGovernanceError(
                "STAGE_ATTEMPT_ADMISSION_RECORD_INVALID",
                "Attempt admission state is malformed.",
            )
        expected_binding = canonical_sha256(
            {
                "grant_id": grant_id,
                "execution_context": context,
                "work_item_id": admission.get("work_item_id"),
                "task_version": admission.get("task_version"),
                "attempt_id": admission.get("attempt_id"),
            }
        )
        if (
            admission.get("status") != "attempt_admitted"
            or admission.get("grant_id") != grant_id
            or admission.get("task_id") != context["task_id"]
            or admission.get("binding_sha256") != expected_binding
        ):
            raise WorkItemGovernanceError(
                "STAGE_ATTEMPT_ADMISSION_RECORD_INVALID",
                "Attempt admission state does not match its exact task binding.",
            )
        return {
            "status": "attempt_admitted",
            "grant_id": grant_id,
            "task_id": context["task_id"],
            "attempt": {
                key: admission.get(key)
                for key in (
                    "work_item_id", "task_version", "attempt_id", "source_event_key"
                )
            },
        }

    def resolve_task_attempt_artifacts(
        self,
        grant_id: str,
        *,
        expected_execution_context: dict[str, Any],
        attempt_id: str,
    ) -> dict[str, Any]:
        """Resolve artifacts through one exact signed target, never a generic query."""

        admission = self.inspect_task_attempt_admission(
            grant_id, expected_execution_context=expected_execution_context
        )
        attempt = admission.get("attempt")
        if not isinstance(attempt, dict) or attempt.get("attempt_id") != attempt_id:
            raise WorkItemGovernanceError(
                "STAGE_ATTEMPT_ADMISSION_REQUIRED",
                "The exact Attempt has not been admitted by governance.",
            )
        result = self._resolve_attempt_artifacts(
            str(attempt.get("work_item_id") or ""),
            int(attempt.get("task_version") or 0),
            attempt_id,
        )
        if (
            not isinstance(result, dict)
            or result.get("ledger_backed") is not True
            or result.get("synthetic_empty") is not False
            or result.get("dispatch_eligible") is not True
            or result.get("attempt_id") != attempt_id
            or not isinstance(result.get("artifact_refs"), list)
        ):
            raise WorkItemGovernanceError(
                "STAGE_ATTEMPT_ARTIFACT_PROJECTION_INVALID",
                "The governance artifact resolver did not return an exact ledger projection.",
            )
        return {
            **result,
            "grant_id": grant_id,
            "task_id": admission["task_id"],
        }


def _load_grant_record(
    store: ConfirmationStore,
    project_root: str,
    grant_id: str,
    expected_execution_context: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
    if not is_stable_id(grant_id, "preview"):
        raise WorkItemGovernanceError(
            "STAGE_ATTEMPT_GRANT_ID_INVALID",
            "Attempt admission grant handle is invalid.",
        )
    guard = confirmation_apply_guard(
        store,
        grant_id,
        project_root=project_root,
    )
    if not guard.get("ok"):
        raise WorkItemGovernanceError(
            str(guard.get("error_code") or "STAGE_ATTEMPT_GRANT_INVALID"),
            "Attempt admission grant is missing, expired, or belongs to another project.",
        )
    record = guard.get("payload")
    if (
        not isinstance(record, dict)
        or record.get("artifact_kind") != "stage_attempt_admission_grant_transport.v1"
        or record.get("grant_id") != grant_id
    ):
        raise WorkItemGovernanceError(
            "STAGE_ATTEMPT_GRANT_TRANSPORT_MISMATCH",
            "Attempt admission transport record does not match its handle.",
        )
    preview = record.get("nested_preview")
    if (
        not isinstance(preview, dict)
        or preview.get("preview_id") != grant_id
        or record.get("nested_preview_sha256") != canonical_sha256(preview)
    ):
        raise WorkItemGovernanceError(
            "STAGE_ATTEMPT_GRANT_TRANSPORT_MISMATCH",
            "Nested governance preview does not match the transport record.",
        )
    signed = preview.get("command")
    if not isinstance(signed, dict):
        raise WorkItemGovernanceError(
            "STAGE_ATTEMPT_GRANT_PREVIEW_INVALID",
            "Nested governance preview is malformed.",
        )
    actual_context = _normalize_execution_context(signed.get("execution_context"))
    expected_context = _normalize_execution_context(expected_execution_context)
    if (
        actual_context != expected_context
        or record.get("execution_context_sha256") != canonical_sha256(actual_context)
    ):
        raise WorkItemGovernanceError(
            "STAGE_ATTEMPT_GRANT_CONTEXT_MISMATCH",
            "Attempt admission grant is bound to another Stage task context.",
        )
    return record, preview, actual_context


def _normalize_execution_context(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        raise WorkItemGovernanceError(
            "STAGE_ATTEMPT_EXECUTION_CONTEXT_INVALID",
            "Stage Attempt execution context must be an object.",
        )
    required = {
        "kind", "stage_id", "parallel_group_id", "task_id", "stage_preview_sha256",
        "base_head", "runner_plan_sha256",
    }
    if set(value) != required or value.get("kind") != "stage_parallel_task":
        raise WorkItemGovernanceError(
            "STAGE_ATTEMPT_EXECUTION_CONTEXT_INVALID",
            "Stage Attempt execution context fields are missing or unexpected.",
        )
    result: dict[str, str] = {"kind": "stage_parallel_task"}
    for field in ("stage_id", "parallel_group_id", "task_id"):
        item = value.get(field)
        if not isinstance(item, str) or not item.strip() or len(item.strip()) > 256:
            raise WorkItemGovernanceError(
                "STAGE_ATTEMPT_EXECUTION_CONTEXT_INVALID",
                f"{field} must be a bounded non-empty string.",
            )
        result[field] = item.strip()
    for field in ("stage_preview_sha256", "base_head", "runner_plan_sha256"):
        item = value.get(field)
        if not isinstance(item, str) or not _SHA256_RE.fullmatch(item):
            raise WorkItemGovernanceError(
                "STAGE_ATTEMPT_EXECUTION_CONTEXT_INVALID",
                f"{field} must be a lowercase SHA-256 value.",
            )
        result[field] = item
    return result
