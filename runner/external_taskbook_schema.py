from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


DEFAULT_SCHEMA_REL_PATH = ".colameta/taskbooks/external_taskbook_schema.json"
EXPECTED_SCHEMA_VERSION = "external_taskbook_schema.v1"
EXPECTED_SCHEMA_ID = "external_taskbook.claim.schema.v1"
EXPECTED_CLAIM_KIND = "external_version_execution_taskbook_claim.v1"

REQUIRED_CLAIM_FIELDS = (
    "source",
    "provenance",
    "external_taskbook_hash",
    "expected_hash_authority_ref",
    "master_taskbook_ref",
    "stage_taskbook_ref",
    "allowed_files",
    "forbidden_files",
    "acceptance_commands",
    "manual_acceptance",
    "out_of_scope",
    "supports_stage_and_master_goals",
)
REJECTION_FIELDS = ("rejected_fields", "rejection_reasons", "known_conflicts")
NORMALIZED_OUTPUT_FIELDS = ("normalized_claims", "normalized_output_candidate", "version_candidate_mapping")
FORBIDDEN_AUTHORITY_CLAIMS = (
    "external_taskbook_is_trusted_fact",
    "external_taskbook_mutates_plan",
    "external_taskbook_authorizes_execution",
    "external_taskbook_expands_allowed_files",
    "manual_acceptance_means_delivery_state_accepted",
)
AUTHORITY_BOUNDARY_EXPECTATIONS = {
    "external_taskbook_expands_allowed_files": False,
    "external_taskbook_is_trusted_fact": False,
    "external_taskbook_mutates_plan": False,
    "external_taskbook_authorizes_execution": False,
    "manual_acceptance_means_delivery_state_accepted": False,
    "schema_result_is_authority": False,
    "creates_review_decision": False,
    "emits_gate_event": False,
    "writes_delivery_state": False,
}
EXPECTED_FIELD_TYPES = {
    "source": "object",
    "provenance": "object",
    "external_taskbook_hash": "sha256",
    "expected_hash_authority_ref": "object",
    "master_taskbook_ref": "object",
    "stage_taskbook_ref": "object",
    "allowed_files": "list",
    "forbidden_files": "list",
    "acceptance_commands": "list",
    "manual_acceptance": "object",
    "out_of_scope": "list",
    "supports_stage_and_master_goals": "object",
}
FORBIDDEN_RESULT_CLAIM_KEYS = frozenset(
    {
        "accepted",
        "delivery_state",
        "delivery_state_accepted",
        "review_acceptance",
        "review_accepted",
        "execution_authorized",
        "executor_authorization",
        "executor_dispatch_authorized",
        "route_transition_authorized",
        "plan_mutation_authorized",
        "allowed_files_expansion_authorized",
        "creates_review_decision",
        "emits_gate_event",
        "writes_delivery_state",
        *FORBIDDEN_AUTHORITY_CLAIMS,
    }
)

SCHEMA_CHECK_PASSED = "schema_check_passed"
SCHEMA_CHECK_FAILED_CLOSED = "schema_check_failed_closed"


class ExternalTaskbookSchemaError(ValueError):
    def __init__(self, error_code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.details = details or {}


def default_external_taskbook_schema_path(project_root: str | Path) -> Path:
    return Path(project_root).expanduser().resolve() / DEFAULT_SCHEMA_REL_PATH


def load_external_taskbook_schema(
    project_root: str | Path | None = None,
    schema_path: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(project_root or Path.cwd()).expanduser().resolve()
    path = _resolve_schema_path(root, schema_path)
    if not path.is_file():
        raise ExternalTaskbookSchemaError(
            "SCHEMA_FILE_MISSING",
            "External Taskbook schema file does not exist.",
            details={"schema_path": str(path)},
        )
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ExternalTaskbookSchemaError(
            "SCHEMA_JSON_INVALID",
            "External Taskbook schema JSON is invalid.",
            details={"schema_path": str(path), "line": exc.lineno, "column": exc.colno},
        ) from exc
    validate_external_taskbook_schema_contract(schema)
    return schema


def validate_external_taskbook_schema_contract(schema: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(schema, dict):
        raise ExternalTaskbookSchemaError("SCHEMA_INVALID", "External Taskbook schema must be a JSON object.")
    _require_exact(schema, "schema_version", EXPECTED_SCHEMA_VERSION)
    _require_exact(schema, "schema_id", EXPECTED_SCHEMA_ID)
    _require_exact(schema, "claim_kind", EXPECTED_CLAIM_KIND)
    _require_exact_list(schema, "required_fields", REQUIRED_CLAIM_FIELDS)
    _require_exact_list(schema, "rejection_fields", REJECTION_FIELDS)
    _require_exact_list(schema, "normalized_output_fields", NORMALIZED_OUTPUT_FIELDS)
    _require_exact_list(schema, "forbidden_authority_claims", FORBIDDEN_AUTHORITY_CLAIMS)
    _validate_authority_boundary(_required_dict(schema, "authority_boundary_expectations"))
    _validate_field_definitions(schema.get("field_definitions"))
    _reject_forbidden_truthy_claims(schema)
    return {
        "schema_contract_status": "valid",
        "schema_version": schema["schema_version"],
        "schema_id": schema["schema_id"],
        "claim_kind": schema["claim_kind"],
        "required_fields": list(REQUIRED_CLAIM_FIELDS),
        "forbidden_authority_claims": list(FORBIDDEN_AUTHORITY_CLAIMS),
        "schema_result_is_authority": False,
        "creates_review_decision": False,
        "emits_gate_event": False,
        "writes_delivery_state": False,
    }


def schema_contract_summary(project_root: str | Path, schema_path: str | Path | None = None) -> dict[str, Any]:
    root = Path(project_root).expanduser().resolve()
    path = _resolve_schema_path(root, schema_path)
    schema = load_external_taskbook_schema(root, path)
    return {
        "schema_path": path.relative_to(root).as_posix(),
        "schema_sha256": sha256_file(path),
        **validate_external_taskbook_schema_contract(schema),
    }


def preview_external_taskbook_claim_shape(
    claim: dict[str, Any],
    *,
    schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if schema is None:
        schema = load_external_taskbook_schema()
    validate_external_taskbook_schema_contract(schema)
    if not isinstance(claim, dict):
        return _claim_preview_result(
            check_result=SCHEMA_CHECK_FAILED_CLOSED,
            rejected_fields=[],
            rejection_reasons=[
                {
                    "code": "CLAIM_INVALID",
                    "message": "External taskbook claim must be a JSON object.",
                    "details": {"actual_type": type(claim).__name__},
                }
            ],
            known_conflicts=[],
        )

    rejected_fields: list[str] = []
    rejection_reasons: list[dict[str, Any]] = []
    known_conflicts: list[dict[str, Any]] = []

    missing = [field for field in REQUIRED_CLAIM_FIELDS if field not in claim]
    if missing:
        rejected_fields.extend(missing)
        rejection_reasons.append(
            {
                "code": "REQUIRED_FIELD_MISSING",
                "message": "External taskbook claim is missing required fields.",
                "details": {"missing_fields": missing},
            }
        )

    for field, expected_type in EXPECTED_FIELD_TYPES.items():
        if field in claim and not _matches_type(claim[field], expected_type):
            rejected_fields.append(field)
            rejection_reasons.append(
                {
                    "code": "FIELD_TYPE_INVALID",
                    "message": f"{field} does not match the schema type {expected_type}.",
                    "details": {"field": field, "expected_type": expected_type, "actual_value": claim[field]},
                }
            )

    authority_claims = _forbidden_claims(claim)
    if authority_claims:
        rejected_fields.extend(item["path"] for item in authority_claims)
        rejection_reasons.append(
            {
                "code": "FORBIDDEN_AUTHORITY_CLAIM",
                "message": "External taskbook claim contains forbidden authority claims.",
                "details": {"forbidden_claims": authority_claims},
            }
        )
        known_conflicts.extend(
            {"conflict_type": "authority_boundary", "path": item["path"], "claim": item["key"]}
            for item in authority_claims
        )

    has_expected_hash_authority = isinstance(claim.get("expected_hash_authority_ref"), dict) and bool(
        str(claim["expected_hash_authority_ref"].get("authority_document", "")).strip()
    )
    if "expected_hash_authority_ref" in claim and not has_expected_hash_authority:
        rejected_fields.append("expected_hash_authority_ref")
        rejection_reasons.append(
            {
                "code": "EXPECTED_HASH_AUTHORITY_REF_INVALID",
                "message": "expected_hash_authority_ref must name an authority document.",
                "details": {"field": "expected_hash_authority_ref"},
            }
        )

    result = SCHEMA_CHECK_FAILED_CLOSED if rejection_reasons else SCHEMA_CHECK_PASSED
    return _claim_preview_result(
        check_result=result,
        rejected_fields=sorted(set(rejected_fields)),
        rejection_reasons=rejection_reasons,
        known_conflicts=known_conflicts,
        normalized_claims=_normalized_claims(claim) if result == SCHEMA_CHECK_PASSED else {},
        normalized_output_candidate=_normalized_output_candidate(claim) if result == SCHEMA_CHECK_PASSED else {},
        version_candidate_mapping=_version_candidate_mapping(claim) if result == SCHEMA_CHECK_PASSED else {},
    )


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _claim_preview_result(
    *,
    check_result: str,
    rejected_fields: list[str],
    rejection_reasons: list[dict[str, Any]],
    known_conflicts: list[dict[str, Any]],
    normalized_claims: dict[str, Any] | None = None,
    normalized_output_candidate: dict[str, Any] | None = None,
    version_candidate_mapping: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = {
        "schema_check_result": check_result,
        "rejected_fields": rejected_fields,
        "rejection_reasons": rejection_reasons,
        "known_conflicts": known_conflicts,
        "normalized_claims": normalized_claims or {},
        "normalized_output_candidate": normalized_output_candidate or {},
        "version_candidate_mapping": version_candidate_mapping or {},
        "external_taskbook_is_trusted_fact": False,
        "external_taskbook_mutates_plan": False,
        "external_taskbook_authorizes_execution": False,
        "external_taskbook_expands_allowed_files": False,
        "manual_acceptance_means_delivery_state_accepted": False,
        "schema_result_is_authority": False,
        "creates_review_decision": False,
        "emits_gate_event": False,
        "writes_delivery_state": False,
    }
    _reject_forbidden_result_fields(result)
    return result


def _normalized_claims(claim: dict[str, Any]) -> dict[str, Any]:
    return {field: claim[field] for field in REQUIRED_CLAIM_FIELDS}


def _normalized_output_candidate(claim: dict[str, Any]) -> dict[str, Any]:
    return {
        "claim_kind": EXPECTED_CLAIM_KIND,
        "external_taskbook_hash": claim["external_taskbook_hash"],
        "source": claim["source"],
        "provenance": claim["provenance"],
    }


def _version_candidate_mapping(claim: dict[str, Any]) -> dict[str, Any]:
    return {
        "stage_taskbook_ref": claim["stage_taskbook_ref"],
        "master_taskbook_ref": claim["master_taskbook_ref"],
        "allowed_files": claim["allowed_files"],
        "forbidden_files": claim["forbidden_files"],
        "mapping_status": "schema_claim_shape_only_not_adopted",
    }


def _resolve_schema_path(root: Path, schema_path: str | Path | None) -> Path:
    raw_path = schema_path or DEFAULT_SCHEMA_REL_PATH
    candidate = Path(raw_path).expanduser()
    path = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    _ensure_inside_project(root, path, "schema_path")
    return path


def _ensure_inside_project(root: Path, path: Path, field: str) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ExternalTaskbookSchemaError(
            "PATH_OUTSIDE_PROJECT",
            f"{field} must stay inside the project root.",
            details={"field": field, "path": str(path), "project_root": str(root)},
        ) from exc


def _require_exact(record: dict[str, Any], field: str, expected: str) -> None:
    actual = record.get(field)
    if actual != expected:
        raise ExternalTaskbookSchemaError(
            "SCHEMA_FIELD_VALUE_UNSUPPORTED",
            f"{field} must be {expected!r}.",
            details={"field": field, "expected": expected, "actual": actual},
        )


def _require_exact_list(record: dict[str, Any], field: str, expected: tuple[str, ...]) -> None:
    actual = record.get(field)
    if actual != list(expected):
        raise ExternalTaskbookSchemaError(
            "SCHEMA_LIST_VALUE_UNSUPPORTED",
            f"{field} must match the expected ordered list.",
            details={"field": field, "expected": list(expected), "actual": actual},
        )


def _required_dict(record: dict[str, Any], field: str) -> dict[str, Any]:
    value = record.get(field)
    if not isinstance(value, dict):
        raise ExternalTaskbookSchemaError("SCHEMA_FIELD_INVALID", f"{field} must be an object.")
    return value


def _validate_authority_boundary(value: dict[str, Any]) -> None:
    unsupported = sorted(str(key) for key in value if key not in AUTHORITY_BOUNDARY_EXPECTATIONS)
    if unsupported:
        raise ExternalTaskbookSchemaError(
            "AUTHORITY_BOUNDARY_UNSUPPORTED_FIELD",
            "authority_boundary_expectations contains unsupported fields.",
            details={"unsupported_fields": unsupported},
        )
    for key, expected in AUTHORITY_BOUNDARY_EXPECTATIONS.items():
        if value.get(key) is not expected:
            raise ExternalTaskbookSchemaError(
                "FORBIDDEN_SCHEMA_AUTHORITY_CLAIM",
                "External Taskbook schema contains a forbidden authority claim.",
                details={"field": key, "expected": expected, "actual": value.get(key)},
            )


def _validate_field_definitions(value: Any) -> None:
    if not isinstance(value, list) or len(value) != len(REQUIRED_CLAIM_FIELDS):
        raise ExternalTaskbookSchemaError(
            "FIELD_DEFINITIONS_INVALID",
            "field_definitions must contain one definition for each required field.",
        )
    by_field = {}
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get("field"), str):
            raise ExternalTaskbookSchemaError("FIELD_DEFINITION_INVALID", "Each field definition must be an object.")
        by_field[item["field"]] = item
    if tuple(by_field) != REQUIRED_CLAIM_FIELDS:
        raise ExternalTaskbookSchemaError(
            "FIELD_DEFINITIONS_ORDER_INVALID",
            "field_definitions must match required_fields order.",
            details={"expected": list(REQUIRED_CLAIM_FIELDS), "actual": list(by_field)},
        )
    for field, expected_type in EXPECTED_FIELD_TYPES.items():
        definition = by_field[field]
        if definition.get("required") is not True or definition.get("type") != expected_type:
            raise ExternalTaskbookSchemaError(
                "FIELD_DEFINITION_VALUE_INVALID",
                "Field definition must preserve required=true and expected type.",
                details={"field": field, "expected_type": expected_type, "actual": definition},
            )


def _matches_type(value: Any, expected_type: str) -> bool:
    if expected_type == "object":
        return isinstance(value, dict) and bool(value)
    if expected_type == "list":
        return isinstance(value, list) and bool(value) and all(isinstance(item, str) and item.strip() for item in value)
    if expected_type == "sha256":
        return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)
    return False


def _reject_forbidden_truthy_claims(value: Any, path: str = "schema") -> None:
    claims = _forbidden_claims(value, path)
    if claims:
        raise ExternalTaskbookSchemaError(
            "FORBIDDEN_SCHEMA_AUTHORITY_CLAIM",
            "External Taskbook schema contains forbidden truthy authority claims.",
            details={"forbidden_claims": claims},
        )


def _forbidden_claims(value: Any, path: str = "claim") -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}"
            if key_text in FORBIDDEN_RESULT_CLAIM_KEYS and _truthy_claim(child):
                claims.append({"path": child_path, "key": key_text, "value": child})
            claims.extend(_forbidden_claims(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            claims.extend(_forbidden_claims(child, f"{path}[{index}]"))
    return claims


def _truthy_claim(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "accepted", "authorized", "allowed", "granted"}
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value != 0
    return False


def _reject_forbidden_result_fields(result: dict[str, Any]) -> None:
    truthy_claims = _forbidden_claims(result, "result")
    allowed_false_keys = set(FORBIDDEN_AUTHORITY_CLAIMS)
    unexpected = [item for item in truthy_claims if item["key"] not in allowed_false_keys]
    if unexpected:
        raise ExternalTaskbookSchemaError(
            "FORBIDDEN_SCHEMA_RESULT_FIELD",
            "Schema result contains forbidden authority fields.",
            details={"forbidden_claims": unexpected},
        )
