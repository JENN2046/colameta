from __future__ import annotations

from typing import Any

from runner.execution_envelope import (
    ENVELOPE_CHECK_PASSED,
    ExecutionEnvelopeError,
    assert_execution_envelope_result_contract,
)


PREVIEW_READY = "preview_ready"
PREVIEW_BLOCKED_INVALID_ENVELOPE = "preview_blocked_invalid_envelope"
PREVIEW_BLOCKED_MISSING_LOCAL_EXECUTION_AUTHORIZATION_REF = "preview_blocked_missing_local_execution_authorization_ref"
PREVIEW_BLOCKED_AUTHORITY_CONFUSION = "preview_blocked_authority_confusion"
VALID_PREVIEW_STATUSES = frozenset(
    {
        PREVIEW_READY,
        PREVIEW_BLOCKED_INVALID_ENVELOPE,
        PREVIEW_BLOCKED_MISSING_LOCAL_EXECUTION_AUTHORIZATION_REF,
        PREVIEW_BLOCKED_AUTHORITY_CONFUSION,
    }
)

REQUIRED_RUN_PREVIEW_FIELDS = frozenset(
    {
        "run_preview_id",
        "preview_status",
        "execution_envelope_ref",
        "version_taskbook_ref",
        "authority_mode",
        "required_local_execution_authorization_ref",
        "proposed_commands",
        "proposed_writable_paths",
        "proposed_observed_mutation_categories",
        "validation_commands",
        "timeout_limits",
        "network_policy",
        "secrets_policy",
        "destructive_operation_policy",
        "stop_conditions",
        "authority_boundary",
    }
)

AUTHORITY_BOUNDARY_EXPECTATIONS = {
    "run_preview_result_is_authority": False,
    "run_preview_authorizes_executor_run": False,
    "run_preview_starts_dispatch": False,
    "run_preview_authorizes_code_changes": False,
    "run_preview_authorizes_commit": False,
    "run_preview_authorizes_push": False,
    "run_preview_writes_delivery_state": False,
    "creates_review_decision": False,
    "emits_gate_event": False,
}
FORBIDDEN_RUN_PREVIEW_CLAIM_KEYS = frozenset(
    {
        "executor_run_authorized",
        "dispatch_started",
        "code_changes_authorized",
        "commit_authorized",
        "push_authorized",
        "delivery_state_accepted",
        "review_acceptance",
        "review_accepted",
        "authorized_to_run",
        "authorized_mutation",
        "run_preview_result_is_authority",
        "run_preview_authorizes_executor_run",
        "run_preview_starts_dispatch",
        "run_preview_authorizes_code_changes",
        "run_preview_authorizes_commit",
        "run_preview_authorizes_push",
        "run_preview_writes_delivery_state",
        "creates_review_decision",
        "emits_gate_event",
        "writes_delivery_state",
    }
)


class ExecutorRunPreviewError(ValueError):
    def __init__(self, error_code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.details = details or {}


def render_executor_run_preview(envelope: dict[str, Any], envelope_validation_result: dict[str, Any]) -> dict[str, Any]:
    try:
        assert_execution_envelope_result_contract(envelope_validation_result)
    except ExecutionEnvelopeError as exc:
        preview = _run_preview_result(
            envelope={},
            validation_result=envelope_validation_result if isinstance(envelope_validation_result, dict) else {},
            preview_status=PREVIEW_BLOCKED_AUTHORITY_CONFUSION,
            blockers=[
                _blocker(
                    "envelope_result_authority_confusion",
                    "ExecutionEnvelope validation result failed its authority-boundary contract.",
                    {"envelope_error_code": exc.error_code, "envelope_error_details": exc.details},
                )
            ],
        )
        assert_executor_run_preview_contract(preview)
        return preview

    if envelope_validation_result.get("envelope_check_result") != ENVELOPE_CHECK_PASSED:
        preview = _run_preview_result(
            envelope=envelope if isinstance(envelope, dict) else {},
            validation_result=envelope_validation_result,
            preview_status=PREVIEW_BLOCKED_INVALID_ENVELOPE,
            blockers=[
                _blocker(
                    "envelope_not_valid",
                    "Executor run preview requires a valid ExecutionEnvelope.",
                    {
                        "envelope_check_result": envelope_validation_result.get("envelope_check_result"),
                        "rejected_fields": envelope_validation_result.get("rejected_fields"),
                    },
                )
            ],
        )
        assert_executor_run_preview_contract(preview)
        return preview

    authority_mode = envelope.get("authority_mode")
    local_execution_authorization_ref = envelope.get("local_execution_authorization_ref")
    if authority_mode != "local_execution" or not isinstance(local_execution_authorization_ref, dict) or not local_execution_authorization_ref:
        preview = _run_preview_result(
            envelope=envelope,
            validation_result=envelope_validation_result,
            preview_status=PREVIEW_BLOCKED_MISSING_LOCAL_EXECUTION_AUTHORIZATION_REF,
            blockers=[
                _blocker(
                    "local_execution_authorization_ref_missing",
                    "Executor run preview requires local_execution mode with local_execution_authorization_ref before dispatch can be considered.",
                    {"authority_mode": authority_mode},
                )
            ],
        )
        assert_executor_run_preview_contract(preview)
        return preview

    preview = _run_preview_result(
        envelope=envelope,
        validation_result=envelope_validation_result,
        preview_status=PREVIEW_READY,
        blockers=[],
    )
    assert_executor_run_preview_contract(preview)
    return preview


def assert_executor_run_preview_contract(preview: dict[str, Any]) -> None:
    if not isinstance(preview, dict):
        raise ExecutorRunPreviewError("RUN_PREVIEW_INVALID", "Executor run preview must be an object.")
    missing = sorted(REQUIRED_RUN_PREVIEW_FIELDS - set(preview))
    if missing:
        raise ExecutorRunPreviewError(
            "RUN_PREVIEW_REQUIRED_FIELD_MISSING",
            "Executor run preview is missing required fields.",
            details={"missing_fields": missing},
        )
    status = preview.get("preview_status")
    if status not in VALID_PREVIEW_STATUSES:
        raise ExecutorRunPreviewError(
            "RUN_PREVIEW_STATUS_INVALID",
            "Executor run preview has an unsupported preview_status.",
            details={"preview_status": status, "valid_statuses": sorted(VALID_PREVIEW_STATUSES)},
        )
    blockers = preview.get("blockers")
    if not isinstance(blockers, list):
        raise ExecutorRunPreviewError("RUN_PREVIEW_BLOCKERS_INVALID", "Executor run preview blockers must be a list.")
    if status == PREVIEW_READY and blockers:
        raise ExecutorRunPreviewError(
            "RUN_PREVIEW_READY_WITH_BLOCKERS",
            "preview_ready must not include blockers.",
            details={"blockers": blockers},
        )
    if status != PREVIEW_READY and not blockers:
        raise ExecutorRunPreviewError(
            "BLOCKED_RUN_PREVIEW_WITHOUT_BLOCKERS",
            "Blocked run preview must include blockers.",
            details={"preview_status": status},
        )
    if preview.get("authority_boundary") != AUTHORITY_BOUNDARY_EXPECTATIONS:
        raise ExecutorRunPreviewError(
            "FORBIDDEN_RUN_PREVIEW_AUTHORITY_CLAIM",
            "Executor run preview authority boundary must remain false.",
            details={"expected": AUTHORITY_BOUNDARY_EXPECTATIONS, "actual": preview.get("authority_boundary")},
        )
    forbidden_claims = _forbidden_truthy_claims(preview, "run_preview")
    if forbidden_claims:
        raise ExecutorRunPreviewError(
            "FORBIDDEN_RUN_PREVIEW_RESULT_CLAIM",
            "Executor run preview contains forbidden authority claims.",
            details={"forbidden_claims": forbidden_claims},
        )


def _run_preview_result(
    *,
    envelope: dict[str, Any],
    validation_result: dict[str, Any],
    preview_status: str,
    blockers: list[dict[str, Any]],
) -> dict[str, Any]:
    authority_mode = envelope.get("authority_mode") or validation_result.get("authority_mode")
    allowed_files = _list_or_empty(envelope.get("allowed_files"))
    return {
        "run_preview_id": _run_preview_id(envelope),
        "preview_status": preview_status,
        "execution_envelope_ref": {
            "envelope_id": envelope.get("envelope_id"),
            "envelope_schema_version": envelope.get("envelope_schema_version"),
            "envelope_check_result": validation_result.get("envelope_check_result"),
        },
        "version_taskbook_ref": _dict_or_empty(envelope.get("version_taskbook_ref")),
        "authority_mode": authority_mode,
        "required_local_execution_authorization_ref": _dict_or_empty(envelope.get("local_execution_authorization_ref")),
        "proposed_commands": {
            "candidate_only": True,
            "authorized_to_run": False,
            "commands": _list_or_empty(envelope.get("allowed_commands")),
        },
        "proposed_writable_paths": {
            "candidate_only": True,
            "authorized_mutation": False,
            "paths": allowed_files,
        },
        "proposed_observed_mutation_categories": {
            "candidate_only": True,
            "authorized_mutation": False,
            "categories": _mutation_categories(allowed_files),
        },
        "validation_commands": {
            "candidate_only": True,
            "authorized_to_run": False,
            "commands": _list_or_empty(envelope.get("validation_commands")),
        },
        "timeout_limits": _dict_or_empty(envelope.get("timeout_limits")),
        "network_policy": _dict_or_empty(envelope.get("network_policy")),
        "secrets_policy": _dict_or_empty(envelope.get("secrets_policy")),
        "destructive_operation_policy": _dict_or_empty(envelope.get("destructive_operation_policy")),
        "stop_conditions": _list_or_empty(envelope.get("stop_conditions")),
        "blockers": blockers,
        "authority_boundary": dict(AUTHORITY_BOUNDARY_EXPECTATIONS),
        "executor_run_authorized": False,
        "dispatch_started": False,
        "code_changes_authorized": False,
        "commit_authorized": False,
        "push_authorized": False,
        "delivery_state_accepted": False,
    }


def _mutation_categories(paths: list[str]) -> list[str]:
    categories = set()
    for path in paths:
        if path.startswith("runner/"):
            categories.add("runner_code")
        elif path.startswith("tests/"):
            categories.add("tests")
        elif path.startswith("docs/"):
            categories.add("docs")
        else:
            categories.add("other_project_file")
    return sorted(categories)


def _run_preview_id(envelope: dict[str, Any]) -> str:
    envelope_id = envelope.get("envelope_id")
    if isinstance(envelope_id, str) and envelope_id:
        return f"run_preview_{envelope_id}"
    return "run_preview_unknown"


def _blocker(code: str, message: str, details: dict[str, Any]) -> dict[str, Any]:
    return {"code": code, "message": message, "details": details}


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_or_empty(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _forbidden_truthy_claims(value: Any, path: str = "run_preview") -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if str(key) in FORBIDDEN_RUN_PREVIEW_CLAIM_KEYS and _truthy_claim(child):
                claims.append({"path": child_path, "key": str(key), "value": child})
            claims.extend(_forbidden_truthy_claims(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            claims.extend(_forbidden_truthy_claims(child, f"{path}[{index}]"))
    return claims


def _truthy_claim(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "accepted", "authorized", "allowed", "granted"}
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value != 0
    return False
