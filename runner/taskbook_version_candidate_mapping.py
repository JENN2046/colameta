from __future__ import annotations

from typing import Any

from runner.taskbook_import_preview import (
    PREVIEW_READY,
    TaskbookImportPreviewError,
    assert_taskbook_import_preview_contract,
)


MAPPING_READY = "mapping_ready"
MAPPING_BLOCKED_PREVIEW_NOT_READY = "mapping_blocked_preview_not_ready"
MAPPING_BLOCKED_SCOPE_CONFLICT = "mapping_blocked_scope_conflict"
MAPPING_BLOCKED_AUTHORITY_CONFUSION = "mapping_blocked_authority_confusion"
VALID_MAPPING_STATUSES = frozenset(
    {
        MAPPING_READY,
        MAPPING_BLOCKED_PREVIEW_NOT_READY,
        MAPPING_BLOCKED_SCOPE_CONFLICT,
        MAPPING_BLOCKED_AUTHORITY_CONFUSION,
    }
)

REQUIRED_MAPPING_FIELDS = frozenset(
    {
        "version_candidate_id",
        "mapping_status",
        "source_taskbook_ref",
        "import_preview_ref",
        "candidate_parent_refs",
        "candidate_version_identity",
        "candidate_allowed_files",
        "candidate_forbidden_files",
        "candidate_acceptance_commands",
        "candidate_manual_acceptance",
        "candidate_evidence_requirements",
        "candidate_out_of_scope",
        "adoption_blockers",
        "required_commander_decisions",
        "authority_boundary",
    }
)

AUTHORITY_BOUNDARY_EXPECTATIONS = {
    "mapping_result_is_authority": False,
    "mapping_inserts_plan_item": False,
    "mapping_mutates_plan": False,
    "mapping_expands_allowed_files": False,
    "mapping_authorizes_executor_dispatch": False,
    "mapping_writes_delivery_state": False,
    "creates_review_decision": False,
    "emits_gate_event": False,
}
FORBIDDEN_MAPPING_CLAIM_KEYS = frozenset(
    {
        "plan_item_inserted",
        "plan_mutation_authorized",
        "allowed_files_expansion_authorized",
        "executor_dispatch_authorized",
        "delivery_state_accepted",
        "review_acceptance",
        "review_accepted",
        "mapping_result_is_authority",
        "mapping_inserts_plan_item",
        "mapping_mutates_plan",
        "mapping_expands_allowed_files",
        "mapping_authorizes_executor_dispatch",
        "mapping_writes_delivery_state",
        "creates_review_decision",
        "emits_gate_event",
        "writes_delivery_state",
        "authorized_delta",
        "authorized_to_run",
    }
)


class TaskbookVersionCandidateMappingError(ValueError):
    def __init__(self, error_code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.details = details or {}


def map_preview_to_version_candidate(
    import_preview: dict[str, Any],
    *,
    import_preview_hash: str,
    normalized_claims_candidate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    authority_boundary = dict(AUTHORITY_BOUNDARY_EXPECTATIONS)

    try:
        assert_taskbook_import_preview_contract(import_preview)
    except TaskbookImportPreviewError as exc:
        mapping = _mapping_result(
            mapping_status=MAPPING_BLOCKED_AUTHORITY_CONFUSION,
            import_preview=import_preview if isinstance(import_preview, dict) else {},
            import_preview_hash=import_preview_hash,
            normalized_claims_candidate={},
            blockers=[
                _blocker(
                    "import_preview_authority_confusion",
                    "Import preview contract failed before Version candidate mapping.",
                    {"preview_error_code": exc.error_code, "preview_error_details": exc.details},
                )
            ],
            authority_boundary=authority_boundary,
        )
        assert_version_candidate_mapping_contract(mapping)
        return mapping

    if import_preview.get("preview_status") != PREVIEW_READY:
        blockers.append(
            _blocker(
                "import_preview_not_ready",
                "Version candidate mapping requires preview_ready import preview output.",
                {"preview_status": import_preview.get("preview_status")},
            )
        )
        mapping = _mapping_result(
            mapping_status=MAPPING_BLOCKED_PREVIEW_NOT_READY,
            import_preview=import_preview,
            import_preview_hash=import_preview_hash,
            normalized_claims_candidate=_dict_or_empty(normalized_claims_candidate),
            blockers=blockers,
            authority_boundary=authority_boundary,
        )
        assert_version_candidate_mapping_contract(mapping)
        return mapping

    if not _is_sha256(import_preview_hash):
        blockers.append(
            _blocker(
                "import_preview_hash_invalid",
                "Version candidate mapping requires the import preview hash.",
                {"import_preview_hash": import_preview_hash},
            )
        )

    claim = _dict_or_empty(normalized_claims_candidate)
    missing_claim_fields = [
        field
        for field in (
            "external_taskbook_hash",
            "master_taskbook_ref",
            "stage_taskbook_ref",
            "allowed_files",
            "forbidden_files",
            "acceptance_commands",
            "manual_acceptance",
            "out_of_scope",
        )
        if field not in claim
    ]
    if missing_claim_fields:
        blockers.append(
            _blocker(
                "normalized_claims_candidate_missing_required_fields",
                "Version candidate mapping requires normalized claims from the validator.",
                {"missing_fields": missing_claim_fields},
            )
        )

    mapping_status = MAPPING_BLOCKED_SCOPE_CONFLICT if blockers else MAPPING_READY
    mapping = _mapping_result(
        mapping_status=mapping_status,
        import_preview=import_preview,
        import_preview_hash=import_preview_hash,
        normalized_claims_candidate=claim,
        blockers=blockers,
        authority_boundary=authority_boundary,
    )
    assert_version_candidate_mapping_contract(mapping)
    return mapping


def assert_version_candidate_mapping_contract(mapping: dict[str, Any]) -> None:
    if not isinstance(mapping, dict):
        raise TaskbookVersionCandidateMappingError("MAPPING_INVALID", "Version candidate mapping must be an object.")
    missing = sorted(REQUIRED_MAPPING_FIELDS - set(mapping))
    if missing:
        raise TaskbookVersionCandidateMappingError(
            "MAPPING_REQUIRED_FIELD_MISSING",
            "Version candidate mapping is missing required fields.",
            details={"missing_fields": missing},
        )
    status = mapping.get("mapping_status")
    if status not in VALID_MAPPING_STATUSES:
        raise TaskbookVersionCandidateMappingError(
            "MAPPING_STATUS_INVALID",
            "Version candidate mapping has an unsupported mapping_status.",
            details={"mapping_status": status, "valid_statuses": sorted(VALID_MAPPING_STATUSES)},
        )
    blockers = mapping.get("adoption_blockers")
    if not isinstance(blockers, list):
        raise TaskbookVersionCandidateMappingError("ADOPTION_BLOCKERS_INVALID", "adoption_blockers must be a list.")
    if status == MAPPING_READY and not blockers:
        raise TaskbookVersionCandidateMappingError(
            "MAPPING_READY_WITHOUT_ADOPTION_BLOCKERS",
            "mapping_ready must still list adoption blockers and Commander decisions.",
        )
    if status != MAPPING_READY and not blockers:
        raise TaskbookVersionCandidateMappingError(
            "BLOCKED_MAPPING_WITHOUT_BLOCKERS",
            "Blocked Version candidate mapping must include blockers.",
            details={"mapping_status": status},
        )
    if mapping.get("authority_boundary") != AUTHORITY_BOUNDARY_EXPECTATIONS:
        raise TaskbookVersionCandidateMappingError(
            "FORBIDDEN_MAPPING_AUTHORITY_CLAIM",
            "Version candidate mapping authority boundary must remain false.",
            details={"expected": AUTHORITY_BOUNDARY_EXPECTATIONS, "actual": mapping.get("authority_boundary")},
        )
    forbidden_claims = _forbidden_truthy_claims(mapping, "mapping")
    if forbidden_claims:
        raise TaskbookVersionCandidateMappingError(
            "FORBIDDEN_MAPPING_RESULT_CLAIM",
            "Version candidate mapping contains forbidden authority claims.",
            details={"forbidden_claims": forbidden_claims},
        )
    if mapping["candidate_allowed_files"].get("candidate_only") is not True:
        raise TaskbookVersionCandidateMappingError(
            "CANDIDATE_ALLOWED_FILES_NOT_CANDIDATE_ONLY",
            "candidate_allowed_files must remain candidate-only.",
        )


def _mapping_result(
    *,
    mapping_status: str,
    import_preview: dict[str, Any],
    import_preview_hash: str,
    normalized_claims_candidate: dict[str, Any],
    blockers: list[dict[str, Any]],
    authority_boundary: dict[str, bool],
) -> dict[str, Any]:
    source_ref = _dict_or_empty(import_preview.get("source_claim_ref"))
    preview_identity = _dict_or_empty(import_preview.get("proposed_version_candidate_identity"))
    decisions = _list_or_empty(import_preview.get("required_commander_decisions"))
    external_hash = normalized_claims_candidate.get("external_taskbook_hash") or source_ref.get("external_taskbook_hash")
    candidate_id = _candidate_id(external_hash)
    adoption_blockers = _adoption_blockers(blockers, decisions)

    return {
        "version_candidate_id": candidate_id,
        "mapping_status": mapping_status,
        "source_taskbook_ref": {
            "external_taskbook_hash": external_hash,
            "source_id": source_ref.get("source_id"),
            "source_system": source_ref.get("source_system"),
            "mapping_source": "import_preview_and_normalized_claim_candidate",
        },
        "import_preview_ref": {
            "preview_id": import_preview.get("preview_id"),
            "preview_status": import_preview.get("preview_status"),
            "import_preview_hash": import_preview_hash,
        },
        "candidate_parent_refs": {
            "candidate_only": True,
            "master_taskbook_ref": _dict_or_empty(normalized_claims_candidate.get("master_taskbook_ref")),
            "stage_taskbook_ref": _dict_or_empty(normalized_claims_candidate.get("stage_taskbook_ref")),
        },
        "candidate_version_identity": {
            "candidate_only": True,
            "version_candidate_id": candidate_id,
            "source_preview_identity": preview_identity,
            "plan_item_inserted": False,
        },
        "candidate_allowed_files": {
            "candidate_only": True,
            "authorized_delta": False,
            "paths": _list_or_empty(normalized_claims_candidate.get("allowed_files")),
        },
        "candidate_forbidden_files": {
            "candidate_only": True,
            "paths": _list_or_empty(normalized_claims_candidate.get("forbidden_files")),
        },
        "candidate_acceptance_commands": {
            "candidate_only": True,
            "authorized_to_run": False,
            "commands": _list_or_empty(normalized_claims_candidate.get("acceptance_commands")),
        },
        "candidate_manual_acceptance": {
            "candidate_only": True,
            "manual_acceptance": _dict_or_empty(normalized_claims_candidate.get("manual_acceptance")),
            "manual_acceptance_is_delivery_state_accepted": False,
        },
        "candidate_evidence_requirements": {
            "candidate_only": True,
            "required_before_adoption": [
                "source_taskbook_hash",
                "import_preview_hash",
                "Commander hash-specific adoption decision",
                "separate implementation authorization before execution",
            ],
        },
        "candidate_out_of_scope": {
            "candidate_only": True,
            "items": _list_or_empty(normalized_claims_candidate.get("out_of_scope")),
        },
        "adoption_blockers": adoption_blockers,
        "required_commander_decisions": decisions,
        "authority_boundary": authority_boundary,
        "plan_item_inserted": False,
        "plan_mutation_authorized": False,
        "allowed_files_expansion_authorized": False,
        "executor_dispatch_authorized": False,
        "delivery_state_accepted": False,
    }


def _adoption_blockers(blockers: list[dict[str, Any]], decisions: list[Any]) -> list[dict[str, Any]]:
    if blockers:
        return blockers
    decision_ids = [item.get("decision_id") for item in decisions if isinstance(item, dict)]
    return [
        _blocker(
            "adoption_requires_separate_commander_decision",
            "Version candidate mapping is not import adoption.",
            {"required_commander_decisions": decision_ids},
        )
    ]


def _candidate_id(external_hash: Any) -> str:
    if isinstance(external_hash, str) and len(external_hash) >= 12:
        return f"version_candidate_{external_hash[:12]}"
    return "version_candidate_unknown"


def _blocker(code: str, message: str, details: dict[str, Any]) -> dict[str, Any]:
    return {"code": code, "message": message, "details": details}


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_or_empty(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _forbidden_truthy_claims(value: Any, path: str = "mapping") -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if str(key) in FORBIDDEN_MAPPING_CLAIM_KEYS and _truthy_claim(child):
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
