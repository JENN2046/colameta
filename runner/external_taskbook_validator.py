from __future__ import annotations

from pathlib import Path
from typing import Any

from runner.external_taskbook_schema import (
    EXPECTED_SCHEMA_VERSION,
    REQUIRED_CLAIM_FIELDS,
    SCHEMA_CHECK_PASSED,
    load_external_taskbook_schema,
    preview_external_taskbook_claim_shape,
    sha256_file,
    validate_external_taskbook_schema_contract,
)


VALIDATION_PASSED = "validation_passed"
VALIDATION_FAILED_CLOSED = "validation_failed_closed"

EXPECTED_MASTER_TASKBOOK_REF = {
    "path": "PROJECT_MASTER_TASKBOOK.md",
    "raw_snapshot_sha256": "1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34",
    "review_status": "freeze_candidate_confirmed_for_exact_hash",
}
EXPECTED_STAGE_TASKBOOK_REF = {
    "path": "docs/taskbooks/stages/STAGE_03_EXTERNAL_TASKBOOK_IMPORT.md",
    "raw_snapshot_sha256": "c5402734ef6990687a6a03ec6b17769f598ff0319b350b6a2371144985ece7ff",
    "stage_id": "stage_03_external_taskbook_import",
}

AUTHORITY_BOUNDARY_EXPECTATIONS = {
    "validator_result_is_authority": False,
    "external_taskbook_is_trusted_fact": False,
    "external_taskbook_mutates_plan": False,
    "external_taskbook_authorizes_execution": False,
    "external_taskbook_expands_allowed_files": False,
    "manual_acceptance_means_delivery_state_accepted": False,
    "creates_review_decision": False,
    "emits_gate_event": False,
    "writes_delivery_state": False,
}
FORBIDDEN_RESULT_CLAIM_KEYS = frozenset(
    {
        "accepted",
        "delivery_state",
        "delivery_state_accepted",
        "review_acceptance",
        "review_accepted",
        "import_adopted",
        "execution_authorized",
        "executor_dispatch_authorized",
        "plan_mutation_authorized",
        "allowed_files_expansion_authorized",
        "validator_result_is_authority",
        "external_taskbook_is_trusted_fact",
        "external_taskbook_mutates_plan",
        "external_taskbook_authorizes_execution",
        "external_taskbook_expands_allowed_files",
        "manual_acceptance_means_delivery_state_accepted",
        "creates_review_decision",
        "emits_gate_event",
        "writes_delivery_state",
    }
)
FORBIDDEN_COMMAND_FRAGMENTS = (
    "git push",
    "git fetch",
    "git pull",
    "git reset --hard",
    "git clean -fd",
    "colameta serve",
    "executor",
    "route transition",
)
HARD_FORBIDDEN_ALLOWED_FILE_PREFIXES = (
    "/home/jenn/tools/colameta",
    ".git/",
    ".colameta/runtime/",
)
HARD_FORBIDDEN_ALLOWED_FILE_EXACT = {
    ".git",
    ".colameta/plan.json",
    ".colameta/state.json",
    "PROJECT_MASTER_TASKBOOK.md",
    "PROJECT_MASTER_TASKBOOK.zh-CN.md",
}


class ExternalTaskbookValidatorError(ValueError):
    def __init__(self, error_code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.details = details or {}


def validate_external_taskbook_claim(
    claim: dict[str, Any],
    *,
    project_root: str | Path | None = None,
    schema: dict[str, Any] | None = None,
    expected_master_taskbook_ref: dict[str, str] | None = None,
    expected_stage_taskbook_ref: dict[str, str] | None = None,
    expected_schema_version: str = EXPECTED_SCHEMA_VERSION,
) -> dict[str, Any]:
    root = Path(project_root or Path.cwd()).expanduser().resolve()
    expected_master_ref = expected_master_taskbook_ref or EXPECTED_MASTER_TASKBOOK_REF
    expected_stage_ref = expected_stage_taskbook_ref or EXPECTED_STAGE_TASKBOOK_REF
    schema = schema or load_external_taskbook_schema(root)
    schema_summary = validate_external_taskbook_schema_contract(schema)

    rejection_reasons: list[dict[str, Any]] = []
    rejected_fields: set[str] = set()
    known_conflicts: list[dict[str, Any]] = []
    schema_result = preview_external_taskbook_claim_shape(claim, schema=schema)
    rejected_fields.update(schema_result["rejected_fields"])
    rejection_reasons.extend(schema_result["rejection_reasons"])
    known_conflicts.extend(schema_result["known_conflicts"])

    recognized_fields = _recognized_fields(claim)
    if schema_summary["schema_version"] != expected_schema_version:
        rejection_reasons.append(
            _reason(
                "SCHEMA_VERSION_MISMATCH",
                "External Taskbook schema version does not match the expected validator schema version.",
                {"expected": expected_schema_version, "actual": schema_summary["schema_version"]},
            )
        )
        known_conflicts.append(
            _conflict("schema_version_mismatch", "schema_version", expected_schema_version, schema_summary["schema_version"])
        )

    if schema_result["schema_check_result"] == SCHEMA_CHECK_PASSED:
        _validate_authority_ref(
            claim["expected_hash_authority_ref"],
            rejected_fields=rejected_fields,
            rejection_reasons=rejection_reasons,
            known_conflicts=known_conflicts,
        )
        _validate_reference(
            claim["master_taskbook_ref"],
            expected_master_ref,
            "master_taskbook_ref",
            root=root,
            rejected_fields=rejected_fields,
            rejection_reasons=rejection_reasons,
            known_conflicts=known_conflicts,
        )
        _validate_reference(
            claim["stage_taskbook_ref"],
            expected_stage_ref,
            "stage_taskbook_ref",
            root=root,
            rejected_fields=rejected_fields,
            rejection_reasons=rejection_reasons,
            known_conflicts=known_conflicts,
        )
        _validate_file_claims(
            claim,
            rejected_fields=rejected_fields,
            rejection_reasons=rejection_reasons,
            known_conflicts=known_conflicts,
        )
        _validate_acceptance_commands(
            claim["acceptance_commands"],
            rejected_fields=rejected_fields,
            rejection_reasons=rejection_reasons,
            known_conflicts=known_conflicts,
        )
        _validate_goal_support(
            claim["supports_stage_and_master_goals"],
            rejected_fields=rejected_fields,
            rejection_reasons=rejection_reasons,
            known_conflicts=known_conflicts,
        )

    passed = not rejection_reasons
    result = {
        "validation_result": VALIDATION_PASSED if passed else VALIDATION_FAILED_CLOSED,
        "fail_closed_result": "pass" if passed else "fail_closed",
        "schema_check_result": schema_result["schema_check_result"],
        "schema_version": schema_summary["schema_version"],
        "recognized_fields": recognized_fields,
        "rejected_fields": sorted(rejected_fields),
        "rejection_reasons": rejection_reasons,
        "known_conflicts": known_conflicts,
        "normalized_claims_candidate": schema_result["normalized_claims"] if passed else {},
        "normalized_output_candidate": schema_result["normalized_output_candidate"] if passed else {},
        "version_candidate_mapping": schema_result["version_candidate_mapping"] if passed else {},
        "expected_master_taskbook_ref": expected_master_ref,
        "expected_stage_taskbook_ref": expected_stage_ref,
        "authority_boundary": dict(AUTHORITY_BOUNDARY_EXPECTATIONS),
        "validator_result_is_authority": False,
        "external_taskbook_is_trusted_fact": False,
        "external_taskbook_mutates_plan": False,
        "external_taskbook_authorizes_execution": False,
        "external_taskbook_expands_allowed_files": False,
        "manual_acceptance_means_delivery_state_accepted": False,
        "creates_review_decision": False,
        "emits_gate_event": False,
        "writes_delivery_state": False,
    }
    assert_external_taskbook_validation_result_contract(result)
    return result


def assert_external_taskbook_validation_result_contract(result: dict[str, Any]) -> None:
    if not isinstance(result, dict):
        raise ExternalTaskbookValidatorError("VALIDATION_RESULT_INVALID", "Validation result must be an object.")
    if result.get("validation_result") not in {VALIDATION_PASSED, VALIDATION_FAILED_CLOSED}:
        raise ExternalTaskbookValidatorError(
            "VALIDATION_RESULT_VALUE_INVALID",
            "External Taskbook validation result has an unsupported value.",
            details={"validation_result": result.get("validation_result")},
        )
    if result.get("validation_result") == VALIDATION_PASSED and result.get("rejection_reasons"):
        raise ExternalTaskbookValidatorError(
            "PASSED_WITH_REJECTION_REASONS",
            "Passed External Taskbook validation must not include rejection reasons.",
            details={"rejection_reasons": result.get("rejection_reasons")},
        )
    authority_boundary = result.get("authority_boundary")
    if authority_boundary != AUTHORITY_BOUNDARY_EXPECTATIONS:
        raise ExternalTaskbookValidatorError(
            "FORBIDDEN_VALIDATOR_AUTHORITY_CLAIM",
            "External Taskbook validator result authority boundary must remain false.",
            details={"expected": AUTHORITY_BOUNDARY_EXPECTATIONS, "actual": authority_boundary},
        )
    forbidden_claims = _forbidden_truthy_claims(result, "result")
    if forbidden_claims:
        raise ExternalTaskbookValidatorError(
            "FORBIDDEN_VALIDATOR_RESULT_CLAIM",
            "External Taskbook validator result contains forbidden authority claims.",
            details={"forbidden_claims": forbidden_claims},
        )


def _recognized_fields(claim: Any) -> list[str]:
    if not isinstance(claim, dict):
        return []
    return [field for field in REQUIRED_CLAIM_FIELDS if field in claim]


def _validate_authority_ref(
    authority_ref: dict[str, Any],
    *,
    rejected_fields: set[str],
    rejection_reasons: list[dict[str, Any]],
    known_conflicts: list[dict[str, Any]],
) -> None:
    authority_hash = authority_ref.get("authority_hash") or authority_ref.get("authority_sha256")
    if not _is_sha256(authority_hash):
        rejected_fields.add("expected_hash_authority_ref")
        rejection_reasons.append(
            _reason(
                "EXPECTED_HASH_AUTHORITY_HASH_INVALID",
                "expected_hash_authority_ref must include a valid authority_hash or authority_sha256.",
                {"field": "expected_hash_authority_ref"},
            )
        )
        known_conflicts.append(
            _conflict("expected_hash_authority_ref_invalid", "expected_hash_authority_ref", "sha256", authority_hash)
        )


def _validate_reference(
    actual_ref: dict[str, Any],
    expected_ref: dict[str, str],
    field: str,
    *,
    root: Path,
    rejected_fields: set[str],
    rejection_reasons: list[dict[str, Any]],
    known_conflicts: list[dict[str, Any]],
) -> None:
    for key, expected in expected_ref.items():
        actual = actual_ref.get(key)
        if actual != expected:
            rejected_fields.add(field)
            rejection_reasons.append(
                _reason(
                    "REFERENCE_MISMATCH",
                    f"{field}.{key} does not match the expected reference.",
                    {"field": field, "key": key, "expected": expected, "actual": actual},
                )
            )
            known_conflicts.append(_conflict("reference_mismatch", f"{field}.{key}", expected, actual))

    rel_path = actual_ref.get("path")
    if isinstance(rel_path, str):
        try:
            path = _resolve_project_relative_path(root, rel_path, f"{field}.path")
        except ExternalTaskbookValidatorError as exc:
            rejected_fields.add(field)
            rejection_reasons.append(_reason(exc.error_code, str(exc), exc.details))
            known_conflicts.append(_conflict("reference_path_invalid", f"{field}.path", "project_relative_file", rel_path))
            return
        if not path.is_file():
            rejected_fields.add(field)
            rejection_reasons.append(
                _reason("REFERENCE_FILE_MISSING", f"{field}.path does not point to an existing file.", {"path": rel_path})
            )
            return
        expected_hash = expected_ref.get("raw_snapshot_sha256")
        actual_hash = sha256_file(path)
        if expected_hash and actual_hash != expected_hash:
            rejected_fields.add(field)
            rejection_reasons.append(
                _reason(
                    "REFERENCE_ACTUAL_HASH_MISMATCH",
                    f"{field}.path actual file hash does not match the expected reference hash.",
                    {"field": field, "expected": expected_hash, "actual": actual_hash, "path": rel_path},
                )
            )
            known_conflicts.append(_conflict("reference_actual_hash_mismatch", field, expected_hash, actual_hash))


def _validate_file_claims(
    claim: dict[str, Any],
    *,
    rejected_fields: set[str],
    rejection_reasons: list[dict[str, Any]],
    known_conflicts: list[dict[str, Any]],
) -> None:
    allowed_files = claim["allowed_files"]
    forbidden_files = claim["forbidden_files"]
    allowed_set = set(allowed_files)
    forbidden_set = set(forbidden_files)
    overlap = sorted(allowed_set & forbidden_set)
    if overlap:
        rejected_fields.add("allowed_files")
        rejected_fields.add("forbidden_files")
        rejection_reasons.append(
            _reason(
                "ALLOWED_FORBIDDEN_FILES_OVERLAP",
                "External taskbook claim cannot place the same path in allowed_files and forbidden_files.",
                {"overlap": overlap},
            )
        )
        known_conflicts.append(_conflict("allowed_forbidden_files_overlap", "allowed_files", "disjoint", overlap))

    invalid_allowed = [_invalid_file_claim_reason(path, allow_glob=False) for path in allowed_files]
    invalid_allowed = [item for item in invalid_allowed if item is not None]
    if invalid_allowed:
        rejected_fields.add("allowed_files")
        rejection_reasons.append(
            _reason(
                "ALLOWED_FILES_INVALID",
                "allowed_files must be narrow project-relative paths and must not include hard-forbidden targets.",
                {"invalid_allowed_files": invalid_allowed},
            )
        )
        known_conflicts.extend(
            _conflict("allowed_file_boundary", f"allowed_files[{item['path']}]", "project_relative_allowed_path", item)
            for item in invalid_allowed
        )

    invalid_forbidden = [_invalid_forbidden_file_claim_reason(path) for path in forbidden_files]
    invalid_forbidden = [item for item in invalid_forbidden if item is not None]
    if invalid_forbidden:
        rejected_fields.add("forbidden_files")
        rejection_reasons.append(
            _reason(
                "FORBIDDEN_FILES_INVALID",
                "forbidden_files must remain project-relative or approved hard-boundary absolute prefixes.",
                {"invalid_forbidden_files": invalid_forbidden},
            )
        )


def _validate_acceptance_commands(
    commands: list[str],
    *,
    rejected_fields: set[str],
    rejection_reasons: list[dict[str, Any]],
    known_conflicts: list[dict[str, Any]],
) -> None:
    forbidden = []
    for command in commands:
        lowered = command.lower()
        for fragment in FORBIDDEN_COMMAND_FRAGMENTS:
            if fragment in lowered:
                forbidden.append({"command": command, "forbidden_fragment": fragment})
    if forbidden:
        rejected_fields.add("acceptance_commands")
        rejection_reasons.append(
            _reason(
                "ACCEPTANCE_COMMAND_FORBIDDEN",
                "acceptance_commands must not contain remote, executor, route, or destructive actions.",
                {"forbidden_commands": forbidden},
            )
        )
        known_conflicts.append(_conflict("acceptance_command_forbidden", "acceptance_commands", "local_validation", forbidden))


def _validate_goal_support(
    support: dict[str, Any],
    *,
    rejected_fields: set[str],
    rejection_reasons: list[dict[str, Any]],
    known_conflicts: list[dict[str, Any]],
) -> None:
    if support.get("supports_stage_goal") is not True or support.get("supports_master_goal") is not True:
        rejected_fields.add("supports_stage_and_master_goals")
        rejection_reasons.append(
            _reason(
                "GOAL_SUPPORT_INVALID",
                "supports_stage_and_master_goals must affirm both Stage and Master goal support.",
                {"actual": support},
            )
        )
        known_conflicts.append(
            _conflict("goal_support_invalid", "supports_stage_and_master_goals", "both_goals_supported", support)
        )
    if not str(support.get("rationale", "")).strip():
        rejected_fields.add("supports_stage_and_master_goals")
        rejection_reasons.append(
            _reason(
                "GOAL_SUPPORT_RATIONALE_MISSING",
                "supports_stage_and_master_goals must include a non-empty rationale.",
                {"actual": support},
            )
        )


def _invalid_file_claim_reason(path: str, *, allow_glob: bool) -> dict[str, str] | None:
    if not path.strip():
        return {"path": path, "reason": "empty_path"}
    if path.startswith("/home/jenn/tools/colameta"):
        return {"path": path, "reason": "stable_service_path_forbidden"}
    if path.startswith("/"):
        return {"path": path, "reason": "absolute_path_forbidden"}
    normalized = path.replace("\\", "/")
    if normalized in HARD_FORBIDDEN_ALLOWED_FILE_EXACT or normalized.startswith(HARD_FORBIDDEN_ALLOWED_FILE_PREFIXES):
        return {"path": path, "reason": "hard_forbidden_target"}
    if not allow_glob and "*" in normalized:
        return {"path": path, "reason": "glob_not_allowed_in_allowed_files"}
    if any(part == ".." for part in normalized.split("/")):
        return {"path": path, "reason": "parent_directory_forbidden"}
    lower = normalized.lower()
    if ".env" in lower or "secret" in lower or "credential" in lower:
        return {"path": path, "reason": "sensitive_path_forbidden"}
    return None


def _invalid_forbidden_file_claim_reason(path: str) -> dict[str, str] | None:
    if not path.strip():
        return {"path": path, "reason": "empty_path"}
    normalized = path.replace("\\", "/")
    if normalized.startswith("/home/jenn/tools/colameta"):
        return None
    if normalized.startswith("/"):
        return {"path": path, "reason": "absolute_path_forbidden"}
    if any(part == ".." for part in normalized.split("/")):
        return {"path": path, "reason": "parent_directory_forbidden"}
    return None


def _resolve_project_relative_path(root: Path, raw_path: str, field: str) -> Path:
    if not raw_path.strip():
        raise ExternalTaskbookValidatorError("REFERENCE_PATH_EMPTY", f"{field} must be non-empty.")
    path = Path(raw_path)
    if path.is_absolute():
        raise ExternalTaskbookValidatorError("REFERENCE_ABSOLUTE_PATH_FORBIDDEN", f"{field} must be project-relative.")
    resolved = (root / path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ExternalTaskbookValidatorError(
            "REFERENCE_PATH_OUTSIDE_PROJECT",
            f"{field} must stay inside the project root.",
            details={"field": field, "path": raw_path, "project_root": str(root)},
        ) from exc
    return resolved


def _reason(code: str, message: str, details: dict[str, Any]) -> dict[str, Any]:
    return {"code": code, "message": message, "details": details}


def _conflict(conflict_type: str, field: str, expected: Any, actual: Any) -> dict[str, Any]:
    return {"conflict_type": conflict_type, "field": field, "expected": expected, "actual": actual}


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _forbidden_truthy_claims(value: Any, path: str = "result") -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if str(key) in FORBIDDEN_RESULT_CLAIM_KEYS and _truthy_claim(child):
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
