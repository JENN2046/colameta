from __future__ import annotations

from typing import Any

from runner.taskbook_version_candidate_mapping import (
    MAPPING_READY,
    TaskbookVersionCandidateMappingError,
    assert_version_candidate_mapping_contract,
)


ADOPTION_PREVIEW_READY = "adoption_preview_ready"
ADOPTION_PREVIEW_BLOCKED_MAPPING_NOT_READY = "adoption_preview_blocked_mapping_not_ready"
ADOPTION_PREVIEW_BLOCKED_PLAN_SCOPE_CONFLICT = "adoption_preview_blocked_plan_scope_conflict"
ADOPTION_PREVIEW_BLOCKED_AUTHORITY_CONFUSION = "adoption_preview_blocked_authority_confusion"
VALID_ADOPTION_PREVIEW_STATUSES = frozenset(
    {
        ADOPTION_PREVIEW_READY,
        ADOPTION_PREVIEW_BLOCKED_MAPPING_NOT_READY,
        ADOPTION_PREVIEW_BLOCKED_PLAN_SCOPE_CONFLICT,
        ADOPTION_PREVIEW_BLOCKED_AUTHORITY_CONFUSION,
    }
)

REQUIRED_ADOPTION_PREVIEW_FIELDS = frozenset(
    {
        "adoption_preview_id",
        "adoption_preview_status",
        "source_taskbook_ref",
        "import_preview_ref",
        "mapping_ref",
        "target_plan_path",
        "candidate_plan_diff_summary",
        "candidate_allowed_files_delta",
        "candidate_forbidden_files_summary",
        "candidate_acceptance_commands_summary",
        "candidate_manual_acceptance_summary",
        "required_exact_hash_authorization",
        "commander_decision_request",
        "blockers",
        "risks",
        "authority_boundary",
    }
)

AUTHORITY_BOUNDARY_EXPECTATIONS = {
    "adoption_preview_result_is_authority": False,
    "adoption_preview_executes_adoption": False,
    "adoption_preview_mutates_plan": False,
    "adoption_preview_expands_allowed_files": False,
    "adoption_preview_authorizes_executor_dispatch": False,
    "adoption_preview_records_commander_confirmation": False,
    "adoption_preview_writes_delivery_state": False,
    "creates_review_decision": False,
    "emits_gate_event": False,
}
FORBIDDEN_ADOPTION_PREVIEW_CLAIM_KEYS = frozenset(
    {
        "adoption_executed",
        "plan_mutation_authorized",
        "allowed_files_expansion_authorized",
        "executor_dispatch_authorized",
        "delivery_state_accepted",
        "review_acceptance",
        "review_accepted",
        "commander_confirmation_recorded",
        "adoption_preview_result_is_authority",
        "adoption_preview_executes_adoption",
        "adoption_preview_mutates_plan",
        "adoption_preview_expands_allowed_files",
        "adoption_preview_authorizes_executor_dispatch",
        "adoption_preview_records_commander_confirmation",
        "adoption_preview_writes_delivery_state",
        "creates_review_decision",
        "emits_gate_event",
        "writes_delivery_state",
    }
)
DEFAULT_TARGET_REPOSITORY_PATH = "/home/jenn/src/colameta-dev"
DEFAULT_TARGET_PLAN_PATH = ".colameta/plan.json"


class TaskbookImportAdoptionPreviewError(ValueError):
    def __init__(self, error_code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.details = details or {}


def render_taskbook_import_adoption_preview(
    version_candidate_mapping: dict[str, Any],
    *,
    mapping_hash: str,
    current_head: str,
    candidate_plan_diff_hash: str,
    candidate_allowed_files_delta_hash: str,
    target_repository_path: str = DEFAULT_TARGET_REPOSITORY_PATH,
    target_plan_path: str = DEFAULT_TARGET_PLAN_PATH,
) -> dict[str, Any]:
    authority_boundary = dict(AUTHORITY_BOUNDARY_EXPECTATIONS)
    blockers: list[dict[str, Any]] = []

    try:
        assert_version_candidate_mapping_contract(version_candidate_mapping)
    except TaskbookVersionCandidateMappingError as exc:
        preview = _adoption_preview_result(
            status=ADOPTION_PREVIEW_BLOCKED_AUTHORITY_CONFUSION,
            mapping=version_candidate_mapping if isinstance(version_candidate_mapping, dict) else {},
            mapping_hash=mapping_hash,
            current_head=current_head,
            candidate_plan_diff_hash=candidate_plan_diff_hash,
            candidate_allowed_files_delta_hash=candidate_allowed_files_delta_hash,
            target_repository_path=target_repository_path,
            target_plan_path=target_plan_path,
            blockers=[
                _blocker(
                    "mapping_authority_confusion",
                    "Version candidate mapping contract failed before adoption preview.",
                    {"mapping_error_code": exc.error_code, "mapping_error_details": exc.details},
                )
            ],
            authority_boundary=authority_boundary,
        )
        assert_taskbook_import_adoption_preview_contract(preview)
        return preview

    if version_candidate_mapping.get("mapping_status") != MAPPING_READY:
        blockers.append(
            _blocker(
                "mapping_not_ready",
                "Adoption preview requires mapping_ready Version candidate mapping.",
                {"mapping_status": version_candidate_mapping.get("mapping_status")},
            )
        )
        preview = _adoption_preview_result(
            status=ADOPTION_PREVIEW_BLOCKED_MAPPING_NOT_READY,
            mapping=version_candidate_mapping,
            mapping_hash=mapping_hash,
            current_head=current_head,
            candidate_plan_diff_hash=candidate_plan_diff_hash,
            candidate_allowed_files_delta_hash=candidate_allowed_files_delta_hash,
            target_repository_path=target_repository_path,
            target_plan_path=target_plan_path,
            blockers=blockers,
            authority_boundary=authority_boundary,
        )
        assert_taskbook_import_adoption_preview_contract(preview)
        return preview

    invalid_scope_fields = _invalid_scope_fields(
        mapping_hash=mapping_hash,
        current_head=current_head,
        candidate_plan_diff_hash=candidate_plan_diff_hash,
        candidate_allowed_files_delta_hash=candidate_allowed_files_delta_hash,
        target_repository_path=target_repository_path,
        target_plan_path=target_plan_path,
    )
    if invalid_scope_fields:
        blockers.append(
            _blocker(
                "required_exact_hash_authorization_inputs_invalid",
                "Adoption preview requires exact hashes, current head, repository path, and target plan path.",
                {"invalid_fields": invalid_scope_fields},
            )
        )

    status = ADOPTION_PREVIEW_BLOCKED_PLAN_SCOPE_CONFLICT if blockers else ADOPTION_PREVIEW_READY
    preview = _adoption_preview_result(
        status=status,
        mapping=version_candidate_mapping,
        mapping_hash=mapping_hash,
        current_head=current_head,
        candidate_plan_diff_hash=candidate_plan_diff_hash,
        candidate_allowed_files_delta_hash=candidate_allowed_files_delta_hash,
        target_repository_path=target_repository_path,
        target_plan_path=target_plan_path,
        blockers=blockers or _adoption_execution_blockers(version_candidate_mapping),
        authority_boundary=authority_boundary,
    )
    assert_taskbook_import_adoption_preview_contract(preview)
    return preview


def assert_taskbook_import_adoption_preview_contract(preview: dict[str, Any]) -> None:
    if not isinstance(preview, dict):
        raise TaskbookImportAdoptionPreviewError(
            "ADOPTION_PREVIEW_INVALID",
            "Taskbook import adoption preview must be an object.",
        )
    missing = sorted(REQUIRED_ADOPTION_PREVIEW_FIELDS - set(preview))
    if missing:
        raise TaskbookImportAdoptionPreviewError(
            "ADOPTION_PREVIEW_REQUIRED_FIELD_MISSING",
            "Taskbook import adoption preview is missing required fields.",
            details={"missing_fields": missing},
        )
    status = preview.get("adoption_preview_status")
    if status not in VALID_ADOPTION_PREVIEW_STATUSES:
        raise TaskbookImportAdoptionPreviewError(
            "ADOPTION_PREVIEW_STATUS_INVALID",
            "Taskbook import adoption preview has an unsupported status.",
            details={"adoption_preview_status": status, "valid_statuses": sorted(VALID_ADOPTION_PREVIEW_STATUSES)},
        )
    blockers = preview.get("blockers")
    if not isinstance(blockers, list) or not blockers:
        raise TaskbookImportAdoptionPreviewError(
            "ADOPTION_PREVIEW_BLOCKERS_REQUIRED",
            "Adoption preview must list blockers to actual adoption or the reason preview is blocked.",
            details={"blockers": blockers},
        )
    if preview.get("authority_boundary") != AUTHORITY_BOUNDARY_EXPECTATIONS:
        raise TaskbookImportAdoptionPreviewError(
            "FORBIDDEN_ADOPTION_PREVIEW_AUTHORITY_CLAIM",
            "Adoption preview authority boundary must remain false.",
            details={"expected": AUTHORITY_BOUNDARY_EXPECTATIONS, "actual": preview.get("authority_boundary")},
        )
    forbidden_claims = _forbidden_truthy_claims(preview, "adoption_preview")
    if forbidden_claims:
        raise TaskbookImportAdoptionPreviewError(
            "FORBIDDEN_ADOPTION_PREVIEW_RESULT_CLAIM",
            "Adoption preview contains forbidden authority claims.",
            details={"forbidden_claims": forbidden_claims},
        )
    request = preview.get("commander_decision_request")
    if not isinstance(request, dict) or request.get("decision_status") != "not_confirmed":
        raise TaskbookImportAdoptionPreviewError(
            "COMMANDER_DECISION_REQUEST_NOT_PENDING",
            "Commander decision request must remain not_confirmed.",
            details={"commander_decision_request": request},
        )
    if request.get("explicit_authorized_actions") != []:
        raise TaskbookImportAdoptionPreviewError(
            "COMMANDER_DECISION_REQUEST_AUTHORIZES_ACTIONS",
            "Adoption preview request must not authorize actions by itself.",
            details={"explicit_authorized_actions": request.get("explicit_authorized_actions")},
        )


def _adoption_preview_result(
    *,
    status: str,
    mapping: dict[str, Any],
    mapping_hash: str,
    current_head: str,
    candidate_plan_diff_hash: str,
    candidate_allowed_files_delta_hash: str,
    target_repository_path: str,
    target_plan_path: str,
    blockers: list[dict[str, Any]],
    authority_boundary: dict[str, bool],
) -> dict[str, Any]:
    source_ref = _dict_or_empty(mapping.get("source_taskbook_ref"))
    import_preview_ref = _dict_or_empty(mapping.get("import_preview_ref"))
    candidate_allowed_files = _dict_or_empty(mapping.get("candidate_allowed_files"))
    candidate_forbidden_files = _dict_or_empty(mapping.get("candidate_forbidden_files"))
    candidate_acceptance_commands = _dict_or_empty(mapping.get("candidate_acceptance_commands"))
    candidate_manual_acceptance = _dict_or_empty(mapping.get("candidate_manual_acceptance"))
    required_authorization = {
        "target_repository_path": target_repository_path,
        "current_head": current_head,
        "source_taskbook_hash": source_ref.get("external_taskbook_hash"),
        "import_preview_hash": import_preview_ref.get("import_preview_hash"),
        "mapping_hash": mapping_hash,
        "target_plan_path": target_plan_path,
        "candidate_plan_diff_hash": candidate_plan_diff_hash,
        "candidate_allowed_files_delta_hash": candidate_allowed_files_delta_hash,
    }
    return {
        "adoption_preview_id": _adoption_preview_id(mapping),
        "adoption_preview_status": status,
        "source_taskbook_ref": source_ref,
        "import_preview_ref": import_preview_ref,
        "mapping_ref": {
            "version_candidate_id": mapping.get("version_candidate_id"),
            "mapping_status": mapping.get("mapping_status"),
            "mapping_hash": mapping_hash,
        },
        "target_plan_path": target_plan_path,
        "candidate_plan_diff_summary": {
            "candidate_only": True,
            "target_plan_path": target_plan_path,
            "candidate_plan_diff_hash": candidate_plan_diff_hash,
            "plan_mutation_authorized": False,
            "plan_mutation_applied": False,
        },
        "candidate_allowed_files_delta": {
            "candidate_only": True,
            "candidate_allowed_files_delta_hash": candidate_allowed_files_delta_hash,
            "paths": _list_or_empty(candidate_allowed_files.get("paths")),
            "allowed_files_expansion_authorized": False,
        },
        "candidate_forbidden_files_summary": {
            "candidate_only": True,
            "paths": _list_or_empty(candidate_forbidden_files.get("paths")),
        },
        "candidate_acceptance_commands_summary": {
            "candidate_only": True,
            "commands": _list_or_empty(candidate_acceptance_commands.get("commands")),
            "authorized_to_run": False,
        },
        "candidate_manual_acceptance_summary": {
            "candidate_only": True,
            "manual_acceptance": _dict_or_empty(candidate_manual_acceptance.get("manual_acceptance")),
            "manual_acceptance_is_delivery_state_accepted": False,
        },
        "required_exact_hash_authorization": required_authorization,
        "commander_decision_request": _commander_decision_request(required_authorization),
        "blockers": blockers,
        "risks": _risks(status),
        "authority_boundary": authority_boundary,
        "adoption_executed": False,
        "plan_mutation_authorized": False,
        "allowed_files_expansion_authorized": False,
        "executor_dispatch_authorized": False,
        "delivery_state_accepted": False,
        "commander_confirmation_recorded": False,
    }


def _commander_decision_request(required_authorization: dict[str, Any]) -> dict[str, Any]:
    return {
        **required_authorization,
        "decision_status": "not_confirmed",
        "explicit_authorized_actions": [],
        "explicit_unauthorized_actions": [
            "implementation",
            "commit",
            "push",
            "fetch",
            "pull",
            "executor_dispatch",
            "route_transition",
            "remote_write",
            "delivery_state_accepted",
            "release_or_deploy",
        ],
        "invalidation_rule": "Any mismatch in repository path, current head, source hash, preview hash, mapping hash, target plan path, candidate plan diff hash, or allowed-files delta hash invalidates this request.",
        "must_authorize_separately": [
            "plan_mutation",
            "allowed_files_expansion",
            "commit",
            "executor_dispatch",
            "route_transition",
            "remote_write",
        ],
    }


def _adoption_execution_blockers(mapping: dict[str, Any]) -> list[dict[str, Any]]:
    decision_ids = [
        item.get("decision_id")
        for item in _list_or_empty(mapping.get("required_commander_decisions"))
        if isinstance(item, dict)
    ]
    return [
        _blocker(
            "adoption_execution_requires_separate_commander_confirmation",
            "Adoption preview is not adoption execution.",
            {"required_commander_decisions": decision_ids},
        )
    ]


def _risks(status: str) -> list[dict[str, str]]:
    return [
        {
            "risk_id": "authority_laundering",
            "risk": "A future caller could mistake the Commander decision request for Commander confirmation.",
            "mitigation": "decision_status remains not_confirmed and explicit_authorized_actions remains empty.",
        },
        {
            "risk_id": "candidate_delta_overread",
            "risk": "A future caller could mistake candidate plan diff or allowed_files delta for applied changes.",
            "mitigation": "candidate summaries are marked candidate_only and all authorization flags remain false.",
        },
        {
            "risk_id": "blocked_status",
            "risk": "Adoption cannot continue while preview status is blocked.",
            "mitigation": f"current adoption_preview_status is {status}.",
        },
    ]


def _invalid_scope_fields(
    *,
    mapping_hash: str,
    current_head: str,
    candidate_plan_diff_hash: str,
    candidate_allowed_files_delta_hash: str,
    target_repository_path: str,
    target_plan_path: str,
) -> list[str]:
    invalid = []
    if not _is_sha256(mapping_hash):
        invalid.append("mapping_hash")
    if not _is_git_sha(current_head):
        invalid.append("current_head")
    if not _is_sha256(candidate_plan_diff_hash):
        invalid.append("candidate_plan_diff_hash")
    if not _is_sha256(candidate_allowed_files_delta_hash):
        invalid.append("candidate_allowed_files_delta_hash")
    if target_repository_path != DEFAULT_TARGET_REPOSITORY_PATH:
        invalid.append("target_repository_path")
    if target_plan_path != DEFAULT_TARGET_PLAN_PATH:
        invalid.append("target_plan_path")
    return invalid


def _adoption_preview_id(mapping: dict[str, Any]) -> str:
    candidate_id = mapping.get("version_candidate_id")
    if isinstance(candidate_id, str) and candidate_id:
        return f"adoption_preview_{candidate_id}"
    return "adoption_preview_unknown"


def _blocker(code: str, message: str, details: dict[str, Any]) -> dict[str, Any]:
    return {"code": code, "message": message, "details": details}


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_or_empty(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _is_git_sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) in {7, 40} and all(char in "0123456789abcdef" for char in value)


def _forbidden_truthy_claims(value: Any, path: str = "adoption_preview") -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if str(key) in FORBIDDEN_ADOPTION_PREVIEW_CLAIM_KEYS and _truthy_claim(child):
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
