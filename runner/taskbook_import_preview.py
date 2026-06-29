from __future__ import annotations

from typing import Any

from runner.external_taskbook_validator import (
    VALIDATION_PASSED,
    ExternalTaskbookValidatorError,
    assert_external_taskbook_validation_result_contract,
)


PREVIEW_READY = "preview_ready"
PREVIEW_BLOCKED_INVALID_VALIDATOR_RESULT = "preview_blocked_invalid_validator_result"
PREVIEW_BLOCKED_AUTHORITY_CONFUSION = "preview_blocked_authority_confusion"
PREVIEW_BLOCKED_MISSING_REQUIRED_CLAIM = "preview_blocked_missing_required_claim"
VALID_PREVIEW_STATUSES = frozenset(
    {
        PREVIEW_READY,
        PREVIEW_BLOCKED_INVALID_VALIDATOR_RESULT,
        PREVIEW_BLOCKED_AUTHORITY_CONFUSION,
        PREVIEW_BLOCKED_MISSING_REQUIRED_CLAIM,
    }
)

REQUIRED_PREVIEW_FIELDS = frozenset(
    {
        "preview_id",
        "preview_status",
        "source_claim_ref",
        "validator_result_ref",
        "recognized_claims_summary",
        "rejected_claims_summary",
        "proposed_version_candidate_identity",
        "proposed_scope_summary",
        "proposed_allowed_files_candidate_delta",
        "proposed_forbidden_files_summary",
        "proposed_acceptance_commands_summary",
        "proposed_manual_acceptance_summary",
        "required_commander_decisions",
        "blockers",
        "authority_boundary",
    }
)

AUTHORITY_BOUNDARY_EXPECTATIONS = {
    "preview_result_is_authority": False,
    "preview_authorizes_adoption": False,
    "preview_mutates_plan": False,
    "preview_expands_allowed_files": False,
    "preview_authorizes_executor_dispatch": False,
    "preview_writes_delivery_state": False,
    "creates_review_decision": False,
    "emits_gate_event": False,
}
FORBIDDEN_PREVIEW_CLAIM_KEYS = frozenset(
    {
        "adoption_authorized",
        "plan_mutation_authorized",
        "allowed_files_expansion_authorized",
        "executor_dispatch_authorized",
        "delivery_state_accepted",
        "review_acceptance",
        "review_accepted",
        "preview_result_is_authority",
        "preview_authorizes_adoption",
        "preview_mutates_plan",
        "preview_expands_allowed_files",
        "preview_authorizes_executor_dispatch",
        "preview_writes_delivery_state",
        "creates_review_decision",
        "emits_gate_event",
        "writes_delivery_state",
    }
)


class TaskbookImportPreviewError(ValueError):
    def __init__(self, error_code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.details = details or {}


def render_taskbook_import_preview(
    validator_result: dict[str, Any],
    *,
    preview_id: str | None = None,
) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    authority_boundary = dict(AUTHORITY_BOUNDARY_EXPECTATIONS)
    normalized_claim = validator_result.get("normalized_claims_candidate") if isinstance(validator_result, dict) else None

    try:
        assert_external_taskbook_validation_result_contract(validator_result)
    except ExternalTaskbookValidatorError as exc:
        preview = _preview_result(
            preview_id=preview_id or "preview_blocked_authority_confusion",
            preview_status=PREVIEW_BLOCKED_AUTHORITY_CONFUSION,
            normalized_claim={},
            validator_result=validator_result if isinstance(validator_result, dict) else {},
            blockers=[
                _blocker(
                    "validator_result_authority_confusion",
                    "Validator result contract failed before import preview.",
                    {"validator_error_code": exc.error_code, "validator_error_details": exc.details},
                )
            ],
            authority_boundary=authority_boundary,
        )
        assert_taskbook_import_preview_contract(preview)
        return preview

    if validator_result.get("validation_result") != VALIDATION_PASSED:
        blockers.append(
            _blocker(
                "validator_result_not_passed",
                "Import preview requires a passed validator result.",
                {
                    "validation_result": validator_result.get("validation_result"),
                    "fail_closed_result": validator_result.get("fail_closed_result"),
                },
            )
        )
        preview = _preview_result(
            preview_id=preview_id or _preview_id_from_claim(normalized_claim, "blocked-invalid-validator"),
            preview_status=PREVIEW_BLOCKED_INVALID_VALIDATOR_RESULT,
            normalized_claim=normalized_claim if isinstance(normalized_claim, dict) else {},
            validator_result=validator_result,
            blockers=blockers,
            authority_boundary=authority_boundary,
        )
        assert_taskbook_import_preview_contract(preview)
        return preview

    if not isinstance(normalized_claim, dict) or not normalized_claim:
        blockers.append(
            _blocker(
                "normalized_claim_missing",
                "Import preview requires normalized_claims_candidate from the validator.",
                {"normalized_claims_candidate_type": type(normalized_claim).__name__},
            )
        )
        preview = _preview_result(
            preview_id=preview_id or "preview_blocked_missing_required_claim",
            preview_status=PREVIEW_BLOCKED_MISSING_REQUIRED_CLAIM,
            normalized_claim={},
            validator_result=validator_result,
            blockers=blockers,
            authority_boundary=authority_boundary,
        )
        assert_taskbook_import_preview_contract(preview)
        return preview

    preview = _preview_result(
        preview_id=preview_id or _preview_id_from_claim(normalized_claim, "preview"),
        preview_status=PREVIEW_READY,
        normalized_claim=normalized_claim,
        validator_result=validator_result,
        blockers=[],
        authority_boundary=authority_boundary,
    )
    assert_taskbook_import_preview_contract(preview)
    return preview


def assert_taskbook_import_preview_contract(preview: dict[str, Any]) -> None:
    if not isinstance(preview, dict):
        raise TaskbookImportPreviewError("PREVIEW_INVALID", "Taskbook import preview must be an object.")
    missing = sorted(REQUIRED_PREVIEW_FIELDS - set(preview))
    if missing:
        raise TaskbookImportPreviewError(
            "PREVIEW_REQUIRED_FIELD_MISSING",
            "Taskbook import preview is missing required fields.",
            details={"missing_fields": missing},
        )
    status = preview.get("preview_status")
    if status not in VALID_PREVIEW_STATUSES:
        raise TaskbookImportPreviewError(
            "PREVIEW_STATUS_INVALID",
            "Taskbook import preview has an unsupported preview_status.",
            details={"preview_status": status, "valid_statuses": sorted(VALID_PREVIEW_STATUSES)},
        )
    blockers = preview.get("blockers")
    if not isinstance(blockers, list):
        raise TaskbookImportPreviewError("PREVIEW_BLOCKERS_INVALID", "Taskbook import preview blockers must be a list.")
    if status == PREVIEW_READY and blockers:
        raise TaskbookImportPreviewError(
            "PREVIEW_READY_WITH_BLOCKERS",
            "preview_ready must not include blockers.",
            details={"blockers": blockers},
        )
    if status != PREVIEW_READY and not blockers:
        raise TaskbookImportPreviewError(
            "BLOCKED_PREVIEW_WITHOUT_BLOCKERS",
            "Blocked import preview must include at least one blocker.",
            details={"preview_status": status},
        )
    if preview.get("authority_boundary") != AUTHORITY_BOUNDARY_EXPECTATIONS:
        raise TaskbookImportPreviewError(
            "FORBIDDEN_PREVIEW_AUTHORITY_CLAIM",
            "Taskbook import preview authority boundary must remain false.",
            details={"expected": AUTHORITY_BOUNDARY_EXPECTATIONS, "actual": preview.get("authority_boundary")},
        )
    forbidden_claims = _forbidden_truthy_claims(preview, "preview")
    if forbidden_claims:
        raise TaskbookImportPreviewError(
            "FORBIDDEN_PREVIEW_RESULT_CLAIM",
            "Taskbook import preview contains forbidden authority claims.",
            details={"forbidden_claims": forbidden_claims},
        )
    delta = preview.get("proposed_allowed_files_candidate_delta")
    if not isinstance(delta, dict) or delta.get("authorized_delta") is not False or delta.get("candidate_only") is not True:
        raise TaskbookImportPreviewError(
            "ALLOWED_FILES_DELTA_NOT_CANDIDATE_ONLY",
            "Allowed-files delta must be candidate-only and unauthorized.",
            details={"proposed_allowed_files_candidate_delta": delta},
        )


def _preview_result(
    *,
    preview_id: str,
    preview_status: str,
    normalized_claim: dict[str, Any],
    validator_result: dict[str, Any],
    blockers: list[dict[str, Any]],
    authority_boundary: dict[str, bool],
) -> dict[str, Any]:
    source = _dict_or_empty(normalized_claim.get("source"))
    provenance = _dict_or_empty(normalized_claim.get("provenance"))
    allowed_files = _list_or_empty(normalized_claim.get("allowed_files"))
    forbidden_files = _list_or_empty(normalized_claim.get("forbidden_files"))
    acceptance_commands = _list_or_empty(normalized_claim.get("acceptance_commands"))
    manual_acceptance = _dict_or_empty(normalized_claim.get("manual_acceptance"))
    out_of_scope = _list_or_empty(normalized_claim.get("out_of_scope"))
    support = _dict_or_empty(normalized_claim.get("supports_stage_and_master_goals"))
    rejected_fields = _list_or_empty(validator_result.get("rejected_fields"))
    rejection_reasons = _list_or_empty(validator_result.get("rejection_reasons"))

    return {
        "preview_id": preview_id,
        "preview_status": preview_status,
        "source_claim_ref": {
            "external_taskbook_hash": normalized_claim.get("external_taskbook_hash"),
            "source_id": source.get("source_id"),
            "source_system": source.get("system"),
            "provenance_method": provenance.get("capture_method"),
        },
        "validator_result_ref": {
            "validation_result": validator_result.get("validation_result"),
            "fail_closed_result": validator_result.get("fail_closed_result"),
            "recognized_fields": _list_or_empty(validator_result.get("recognized_fields")),
            "rejected_fields": rejected_fields,
            "rejection_reasons_count": len(rejection_reasons),
        },
        "recognized_claims_summary": {
            "recognized_fields": _list_or_empty(validator_result.get("recognized_fields")),
            "recognized_fields_count": len(_list_or_empty(validator_result.get("recognized_fields"))),
        },
        "rejected_claims_summary": {
            "rejected_fields": rejected_fields,
            "rejection_reasons": rejection_reasons,
        },
        "proposed_version_candidate_identity": {
            "candidate_only": True,
            "authorized_for_mapping": False,
            "external_taskbook_hash": normalized_claim.get("external_taskbook_hash"),
            "source_id": source.get("source_id"),
            "proposed_version_id": source.get("proposed_version_id"),
            "identity_status": "candidate_identity_preview_only_not_mapped",
        },
        "proposed_scope_summary": {
            "candidate_only": True,
            "allowed_files_count": len(allowed_files),
            "forbidden_files_count": len(forbidden_files),
            "out_of_scope_count": len(out_of_scope),
            "supports_stage_goal": support.get("supports_stage_goal"),
            "supports_master_goal": support.get("supports_master_goal"),
        },
        "proposed_allowed_files_candidate_delta": {
            "candidate_only": True,
            "authorized_delta": False,
            "candidate_paths": allowed_files,
            "candidate_path_count": len(allowed_files),
        },
        "proposed_forbidden_files_summary": {
            "candidate_only": True,
            "paths": forbidden_files,
            "path_count": len(forbidden_files),
        },
        "proposed_acceptance_commands_summary": {
            "candidate_only": True,
            "authorized_to_run": False,
            "commands": acceptance_commands,
            "command_count": len(acceptance_commands),
        },
        "proposed_manual_acceptance_summary": {
            "candidate_only": True,
            "manual_acceptance_required": manual_acceptance.get("required"),
            "manual_acceptance_is_delivery_state_accepted": False,
            "reviewer": manual_acceptance.get("reviewer"),
        },
        "required_commander_decisions": _required_commander_decisions(preview_status),
        "blockers": blockers,
        "authority_boundary": authority_boundary,
        "adoption_authorized": False,
        "plan_mutation_authorized": False,
        "allowed_files_expansion_authorized": False,
        "executor_dispatch_authorized": False,
        "delivery_state_accepted": False,
    }


def _required_commander_decisions(preview_status: str) -> list[dict[str, str]]:
    if preview_status != PREVIEW_READY:
        return [
            {
                "decision_id": "resolve_preview_blocker",
                "decision_status": "required_before_any_import_path_continues",
            }
        ]
    return [
        {
            "decision_id": "decide_whether_to_consider_mapping",
            "decision_status": "required_before_v3_4_mapping_preview",
        },
        {
            "decision_id": "hash_specific_adoption_decision",
            "decision_status": "required_before_any_plan_mutation_or_allowed_files_expansion",
        },
        {
            "decision_id": "execution_authorization",
            "decision_status": "required_before_executor_dispatch_or_local_implementation",
        },
    ]


def _preview_id_from_claim(normalized_claim: Any, prefix: str) -> str:
    if isinstance(normalized_claim, dict):
        digest = str(normalized_claim.get("external_taskbook_hash", "unknown"))[:12]
        if digest and digest != "unknown":
            return f"{prefix}_{digest}"
    return f"{prefix}_unknown"


def _blocker(code: str, message: str, details: dict[str, Any]) -> dict[str, Any]:
    return {"code": code, "message": message, "details": details}


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_or_empty(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _forbidden_truthy_claims(value: Any, path: str = "preview") -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if str(key) in FORBIDDEN_PREVIEW_CLAIM_KEYS and _truthy_claim(child):
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
