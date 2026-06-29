from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from runner.stage_taskbook_validator import (
    FAIL_CLOSED_RESULT_PASS,
    VALIDATION_RESULT_PASSED,
    load_stage_taskbook_schema,
    validate_stage_taskbook,
)


DEFAULT_REGISTRY_REL_PATH = ".colameta/taskbooks/stage_taskbook_registry.json"
EXPECTED_SCHEMA_VERSION = "stage_taskbook_registry.v1"
EXPECTED_REGISTRY_RECORD_ID = "stage_taskbook.registry.current"
EXPECTED_PROJECT = "ColaMeta"
EXPECTED_RECORD_KEY = "stage_id"
EXPECTED_MASTER_TASKBOOK_REF = {
    "path": "PROJECT_MASTER_TASKBOOK.md",
    "raw_snapshot_sha256": "1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34",
    "review_status": "freeze_candidate_confirmed_for_exact_hash",
}
EXPECTED_SOURCE_VERSION_TASKBOOK_REF = {
    "path": "docs/taskbooks/versions/stage-02/VERSION_STAGE_02_V2_2_STAGE_TASKBOOK_REGISTRY_V1.md",
    "raw_snapshot_sha256": "d43c791d76df839b0fa361955dc6208af9cce24a7594d045feb4062892f69050",
    "version_id": "stage_02_v2_2_stage_taskbook_registry_v1",
}

REQUIRED_REGISTRY_FIELDS = (
    "schema_version",
    "registry_record_id",
    "project",
    "workspace",
    "record_key",
    "source_version_taskbook_ref",
    "observed_git_head",
    "observed_origin_main_local_tracking_ref",
    "ahead_behind_from_local_refs",
    "live_remote_status_not_validated",
    "authority_boundary",
    "mutation_boundary",
    "records",
    "created_at",
)
ALLOWED_REGISTRY_FIELDS = frozenset(REQUIRED_REGISTRY_FIELDS)

REQUIRED_STAGE_RECORD_FIELDS = (
    "stage_id",
    "stage_name",
    "stage_taskbook_path",
    "stage_taskbook_raw_snapshot_sha256",
    "master_taskbook_ref",
    "supports_project_goal",
    "validator_result",
    "gate_readiness_summary",
    "non_goals_summary",
    "authority_boundary",
    "source_version_taskbook_ref",
    "observed_git_head",
    "created_at",
)
ALLOWED_STAGE_RECORD_FIELDS = frozenset(REQUIRED_STAGE_RECORD_FIELDS)

REQUIRED_VALIDATOR_RESULT_FIELDS = (
    "validator_name",
    "validator_schema_version",
    "validator_result_consumed",
    "validation_result",
    "fail_closed_result",
    "stage_taskbook_path",
    "stage_taskbook_hash",
    "stage_id",
    "stage_name",
    "master_taskbook_ref",
    "supports_project_goal",
    "fail_closed_violations",
    "required_field_violations",
    "validator_result_is_authority",
    "creates_review_decision",
    "emits_gate_event",
    "writes_delivery_state",
)
ALLOWED_VALIDATOR_RESULT_FIELDS = frozenset(REQUIRED_VALIDATOR_RESULT_FIELDS)

REGISTRY_AUTHORITY_BOUNDARY_EXPECTATIONS = {
    "registry_is_execution_authority": False,
    "registry_is_delivery_state_authority": False,
    "registry_can_create_review_decision": False,
    "registry_can_emit_gate_event": False,
    "registry_can_override_delivery_state_gate": False,
    "registry_result_is_authority": False,
}

STAGE_AUTHORITY_BOUNDARY_EXPECTATIONS = {
    "registered_stage_is_accepted_delivery_state": False,
    "registered_stage_authorizes_execution": False,
    "registry_can_mutate_stage_taskbook": False,
    "registry_can_override_delivery_state_gate": False,
    "gate_readiness_is_delivery_state": False,
    "registry_result_is_authority": False,
}

MUTATION_BOUNDARY_EXPECTATIONS = {
    "stage_taskbook_mutation_allowed": False,
    "registry_can_mutate_stage_taskbook": False,
    "requires_separate_hash_specific_authorization": True,
}

ALLOWED_AHEAD_BEHIND_FIELDS = frozenset({"ahead", "behind", "source"})
ALLOWED_TRUE_AUTHORITY_KEYS = frozenset(
    {
        "live_remote_status_not_validated",
        "requires_separate_hash_specific_authorization",
        "validator_result_consumed",
    }
)
FORBIDDEN_AUTHORITY_KEY_MARKERS = (
    "authority",
    "authorized",
    "authorization",
    "accepted",
    "execution",
    "executor",
    "dispatch",
    "route_transition",
    "delivery_state",
    "review_acceptance",
    "can_mutate",
    "mutation_allowed",
    "can_override",
)
FORBIDDEN_FREE_TEXT_CLAIM_PATTERNS = (
    (
        "execution_authority",
        re.compile(
            r"\b(?:authori[sz]e[sd]?|allow(?:ed|s)?|grants?|granted|can|may)\s+"
            r"(?:to\s+)?(?:execute|execution)\b"
            r"|\bexecution\s+(?:authorized|authorization|authority|granted|allowed)\b"
            r"|\bexecutor\s+(?:authorized|authorization|authority|granted|allowed)\b"
        ),
    ),
    (
        "delivery_state_authority",
        re.compile(
            r"\bdelivery\s+state\s+(?:accepted|authorized|authority|granted|allowed)\b"
            r"|\baccepted\s+delivery\s+state\b"
            r"|\bwrites?\s+delivery\s+state\b"
        ),
    ),
    (
        "review_decision_or_gate_event",
        re.compile(
            r"\b(?:creates?|emits?|writes?|grants?|granted)\s+(?:a\s+)?"
            r"(?:review\s*decision|reviewdecision|gate\s*event|gateevent)\b"
        ),
    ),
    (
        "review_acceptance_authority",
        re.compile(
            r"\breview\s+acceptance\s+(?:granted|accepted|authorized|authority|allowed)\b"
            r"|\b(?:grants?|granted|authori[sz]e[sd]?|allow(?:ed|s)?)\s+review\s+acceptance\b"
        ),
    ),
)


class StageTaskbookRegistryError(ValueError):
    def __init__(self, error_code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.details = details or {}


def default_stage_taskbook_registry_path(project_root: str | Path) -> Path:
    return Path(project_root).expanduser().resolve() / DEFAULT_REGISTRY_REL_PATH


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_stage_taskbook_registry(
    project_root: str | Path,
    registry_path: str | Path | None = None,
    *,
    expected_master_taskbook_ref: dict[str, str] | None = None,
    expected_source_version_ref: dict[str, str] | None = None,
) -> dict[str, Any]:
    root = Path(project_root).expanduser().resolve()
    path = _resolve_registry_path(root, registry_path)
    if not path.is_file():
        raise StageTaskbookRegistryError(
            "REGISTRY_FILE_MISSING",
            "Stage Taskbook registry file does not exist.",
            details={"registry_path": str(path)},
        )

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StageTaskbookRegistryError(
            "REGISTRY_JSON_INVALID",
            "Stage Taskbook registry JSON is invalid.",
            details={"registry_path": str(path), "line": exc.lineno, "column": exc.colno},
        ) from exc

    return validate_stage_taskbook_registry(
        payload,
        project_root=root,
        registry_path=path,
        expected_master_taskbook_ref=expected_master_taskbook_ref,
        expected_source_version_ref=expected_source_version_ref,
    )


def validate_stage_taskbook_registry(
    registry: dict[str, Any],
    *,
    project_root: str | Path,
    registry_path: str | Path | None = None,
    expected_master_taskbook_ref: dict[str, str] | None = None,
    expected_source_version_ref: dict[str, str] | None = None,
) -> dict[str, Any]:
    if not isinstance(registry, dict):
        raise StageTaskbookRegistryError("REGISTRY_INVALID", "Stage Taskbook registry must be a JSON object.")

    _validate_required_and_allowed(
        value=registry,
        required=REQUIRED_REGISTRY_FIELDS,
        allowed=ALLOWED_REGISTRY_FIELDS,
        object_name="registry",
    )
    _reject_forbidden_authority_claims(registry)

    root = Path(project_root).expanduser().resolve()
    path = _resolve_registry_path(root, registry_path)
    workspace = _required_str(registry, "workspace")
    if Path(workspace).expanduser().resolve() != root:
        raise StageTaskbookRegistryError(
            "WORKSPACE_MISMATCH",
            "Stage Taskbook registry workspace does not match the current project root.",
            details={"workspace": workspace, "project_root": str(root)},
        )

    _require_exact_str(registry, "schema_version", EXPECTED_SCHEMA_VERSION)
    _require_exact_str(registry, "registry_record_id", EXPECTED_REGISTRY_RECORD_ID)
    _require_exact_str(registry, "project", EXPECTED_PROJECT)
    _require_exact_str(registry, "record_key", EXPECTED_RECORD_KEY)
    _required_sha_like(registry, "observed_git_head")
    _required_sha_like(registry, "observed_origin_main_local_tracking_ref")
    _validate_ahead_behind(_required_dict(registry, "ahead_behind_from_local_refs"))
    _validate_boolean_expectations(
        record=_required_dict(registry, "authority_boundary"),
        field="authority_boundary",
        expectations=REGISTRY_AUTHORITY_BOUNDARY_EXPECTATIONS,
    )
    _validate_boolean_expectations(
        record=_required_dict(registry, "mutation_boundary"),
        field="mutation_boundary",
        expectations=MUTATION_BOUNDARY_EXPECTATIONS,
    )
    if registry.get("live_remote_status_not_validated") is not True:
        raise StageTaskbookRegistryError(
            "REMOTE_STATUS_BOUNDARY_INVALID",
            "Registry must record that live remote status was not validated under this local-only slice.",
        )

    expected_master_ref = expected_master_taskbook_ref or EXPECTED_MASTER_TASKBOOK_REF
    expected_source_ref = expected_source_version_ref or EXPECTED_SOURCE_VERSION_TASKBOOK_REF
    _validate_source_ref(
        root=root,
        value=_required_dict(registry, "source_version_taskbook_ref"),
        field="source_version_taskbook_ref",
        expected=expected_source_ref,
    )

    records = _required_dict(registry, "records")
    if not records:
        raise StageTaskbookRegistryError("REGISTRY_RECORDS_EMPTY", "Stage Taskbook registry must contain records.")

    validated_records = {}
    for stage_id, record in records.items():
        if not isinstance(stage_id, str) or not stage_id:
            raise StageTaskbookRegistryError("STAGE_ID_INVALID", "Stage registry record key must be a non-empty string.")
        if not isinstance(record, dict):
            raise StageTaskbookRegistryError(
                "STAGE_RECORD_INVALID",
                "Stage registry record must be a JSON object.",
                details={"stage_id": stage_id},
            )
        validated_records[stage_id] = _validate_stage_record(
            root=root,
            stage_id=stage_id,
            record=record,
            expected_master_ref=expected_master_ref,
            expected_source_ref=expected_source_ref,
            observed_git_head=_required_str(registry, "observed_git_head"),
        )

    return {
        "ok": True,
        "registry_path": str(path),
        "project_root": str(root),
        "registry_record_id": registry["registry_record_id"],
        "record_count": len(validated_records),
        "stage_ids": sorted(validated_records),
        "records": validated_records,
        "stage_hashes_verified": True,
        "validator_results_verified": True,
        "registry_result_is_authority": False,
        "creates_review_decision": False,
        "emits_gate_event": False,
        "writes_delivery_state": False,
    }


def _validate_stage_record(
    *,
    root: Path,
    stage_id: str,
    record: dict[str, Any],
    expected_master_ref: dict[str, str],
    expected_source_ref: dict[str, str],
    observed_git_head: str,
) -> dict[str, Any]:
    _validate_required_and_allowed(
        value=record,
        required=REQUIRED_STAGE_RECORD_FIELDS,
        allowed=ALLOWED_STAGE_RECORD_FIELDS,
        object_name=f"records.{stage_id}",
    )
    if record["stage_id"] != stage_id:
        raise StageTaskbookRegistryError(
            "STAGE_ID_KEY_MISMATCH",
            "Stage registry record key must match record.stage_id.",
            details={"record_key": stage_id, "stage_id": record.get("stage_id")},
    )
    _required_str(record, "stage_name")
    stage_path = _resolve_project_relpath(root, _required_str(record, "stage_taskbook_path"), "stage_taskbook_path")
    expected_stage_hash = _required_sha256(record, "stage_taskbook_raw_snapshot_sha256")
    if not stage_path.is_file():
        raise StageTaskbookRegistryError(
            "STAGE_TASKBOOK_FILE_MISSING",
            "Stage Taskbook file declared by registry does not exist.",
            details={"stage_taskbook_path": str(stage_path)},
        )
    actual_hash = sha256_file(stage_path)
    if actual_hash != expected_stage_hash:
        raise StageTaskbookRegistryError(
            "STAGE_TASKBOOK_HASH_MISMATCH",
            "Stage Taskbook hash does not match registry binding.",
            details={"expected": expected_stage_hash, "actual": actual_hash},
        )

    _validate_master_taskbook_ref(
        root=root,
        value=_required_dict(record, "master_taskbook_ref"),
        field=f"records.{stage_id}.master_taskbook_ref",
        expected=expected_master_ref,
    )
    if record.get("supports_project_goal") is not True:
        raise StageTaskbookRegistryError(
            "SUPPORTS_PROJECT_GOAL_INVALID",
            "Stage registry record must preserve supports_project_goal: true.",
            details={"stage_id": stage_id, "supports_project_goal": record.get("supports_project_goal")},
        )
    _validate_source_ref(
        root=root,
        value=_required_dict(record, "source_version_taskbook_ref"),
        field=f"records.{stage_id}.source_version_taskbook_ref",
        expected=expected_source_ref,
    )
    _validate_boolean_expectations(
        record=_required_dict(record, "authority_boundary"),
        field=f"records.{stage_id}.authority_boundary",
        expectations=STAGE_AUTHORITY_BOUNDARY_EXPECTATIONS,
    )
    _validate_gate_readiness_summary(_required_dict(record, "gate_readiness_summary"), stage_id)
    _validate_non_goals_summary(record.get("non_goals_summary"), stage_id)
    _required_sha_like(record, "observed_git_head")
    _required_str(record, "created_at")

    validator_record = _validate_validator_result_record(
        _required_dict(record, "validator_result"),
        stage_id=stage_id,
        stage_path=stage_path,
        stage_path_rel=_required_str(record, "stage_taskbook_path"),
        expected_stage_hash=expected_stage_hash,
        expected_master_ref=expected_master_ref,
    )
    schema = load_stage_taskbook_schema(root)
    validator_result = validate_stage_taskbook(
        stage_taskbook_path=stage_path,
        schema=schema,
        expected_master_taskbook_hash=expected_master_ref["raw_snapshot_sha256"],
        observed_git_head=observed_git_head,
    )
    _compare_validator_result(
        expected=validator_record,
        actual=validator_result,
        stage_path=stage_path,
        stage_path_rel=_required_str(record, "stage_taskbook_path"),
    )

    return {
        "stage_id": stage_id,
        "stage_name": record["stage_name"],
        "stage_taskbook_path": str(stage_path),
        "stage_taskbook_hash": expected_stage_hash,
        "master_taskbook_ref": record["master_taskbook_ref"],
        "validator_result": validator_record,
        "gate_readiness_summary": record["gate_readiness_summary"],
        "non_goals_summary": record["non_goals_summary"],
        "validator_rerun_result": validator_result,
    }


def _validate_validator_result_record(
    record: dict[str, Any],
    *,
    stage_id: str,
    stage_path: Path,
    stage_path_rel: str,
    expected_stage_hash: str,
    expected_master_ref: dict[str, str],
) -> dict[str, Any]:
    _validate_required_and_allowed(
        value=record,
        required=REQUIRED_VALIDATOR_RESULT_FIELDS,
        allowed=ALLOWED_VALIDATOR_RESULT_FIELDS,
        object_name=f"records.{stage_id}.validator_result",
    )
    _require_exact_str(record, "validator_name", "runner.stage_taskbook_validator.validate_stage_taskbook")
    _require_exact_str(record, "validator_schema_version", "stage_taskbook_schema.v1")
    if record.get("validator_result_consumed") is not True:
        raise StageTaskbookRegistryError(
            "VALIDATOR_RESULT_NOT_CONSUMED",
            "Stage registry record must consume a v2.1 validator result.",
            details={"stage_id": stage_id},
        )
    _require_exact_str(record, "validation_result", VALIDATION_RESULT_PASSED)
    _require_exact_str(record, "fail_closed_result", FAIL_CLOSED_RESULT_PASS)
    _require_exact_str(record, "stage_taskbook_path", stage_path_rel)
    _require_exact_str(record, "stage_taskbook_hash", expected_stage_hash)
    _require_exact_str(record, "stage_id", stage_id)
    _required_str(record, "stage_name")
    _validate_exact_object(
        record=_required_dict(record, "master_taskbook_ref"),
        field=f"records.{stage_id}.validator_result.master_taskbook_ref",
        expected={
            "path": expected_master_ref["path"],
            "raw_snapshot_sha256": expected_master_ref["raw_snapshot_sha256"],
        },
    )
    if record.get("supports_project_goal") is not True:
        raise StageTaskbookRegistryError(
            "VALIDATOR_SUPPORTS_PROJECT_GOAL_INVALID",
            "Validator result must preserve supports_project_goal: true.",
            details={"stage_id": stage_id},
        )
    if record.get("fail_closed_violations") != []:
        raise StageTaskbookRegistryError(
            "VALIDATOR_FAIL_CLOSED_VIOLATIONS_PRESENT",
            "Stage registry cannot register a failed-closed validator result.",
            details={"stage_id": stage_id, "fail_closed_violations": record.get("fail_closed_violations")},
        )
    if record.get("required_field_violations") != []:
        raise StageTaskbookRegistryError(
            "VALIDATOR_REQUIRED_FIELD_VIOLATIONS_PRESENT",
            "Stage registry cannot register a validator result with required-field violations.",
            details={"stage_id": stage_id, "required_field_violations": record.get("required_field_violations")},
        )
    for key in ("validator_result_is_authority", "creates_review_decision", "emits_gate_event", "writes_delivery_state"):
        if record.get(key) is not False:
            raise StageTaskbookRegistryError(
                "VALIDATOR_AUTHORITY_BOUNDARY_INVALID",
                f"Validator result field {key} must be false.",
                details={"stage_id": stage_id, "field": key, "actual": record.get(key)},
            )
    if stage_path.name not in stage_path_rel:
        raise StageTaskbookRegistryError(
            "STAGE_TASKBOOK_PATH_INVALID",
            "Validator result stage_taskbook_path must refer to the registered Stage Taskbook path.",
            details={"stage_id": stage_id, "stage_taskbook_path": stage_path_rel},
        )
    return record


def _compare_validator_result(
    *,
    expected: dict[str, Any],
    actual: dict[str, Any],
    stage_path: Path,
    stage_path_rel: str,
) -> None:
    actual_path = Path(str(actual.get("stage_taskbook_path", ""))).resolve()
    if actual_path != stage_path.resolve():
        raise StageTaskbookRegistryError(
            "VALIDATOR_STAGE_PATH_MISMATCH",
            "Stored validator result does not match the current validator stage path.",
            details={"expected": str(stage_path), "actual": str(actual_path)},
        )
    comparisons = {
        "validation_result": actual.get("validation_result"),
        "fail_closed_result": actual.get("fail_closed_result"),
        "stage_taskbook_hash": actual.get("stage_taskbook_hash"),
        "stage_id": actual.get("stage_id"),
        "stage_name": actual.get("stage_name"),
        "supports_project_goal": actual.get("supports_project_goal"),
        "fail_closed_violations": actual.get("fail_closed_violations"),
        "required_field_violations": actual.get("required_field_violations"),
        "validator_result_is_authority": actual.get("validator_result_is_authority"),
        "creates_review_decision": actual.get("creates_review_decision"),
        "emits_gate_event": actual.get("emits_gate_event"),
        "writes_delivery_state": actual.get("writes_delivery_state"),
    }
    for key, actual_value in comparisons.items():
        if expected.get(key) != actual_value:
            raise StageTaskbookRegistryError(
                "VALIDATOR_RESULT_MISMATCH",
                "Stored validator result does not match the current v2.1 validator output.",
                details={"field": key, "expected": expected.get(key), "actual": actual_value},
            )
    if expected["stage_taskbook_path"] != stage_path_rel:
        raise StageTaskbookRegistryError(
            "VALIDATOR_RESULT_MISMATCH",
            "Stored validator stage path is not the registered project-relative path.",
            details={"field": "stage_taskbook_path", "expected": stage_path_rel, "actual": expected["stage_taskbook_path"]},
        )
    expected_master_ref = expected.get("master_taskbook_ref")
    actual_master_ref = actual.get("master_taskbook_ref")
    if expected_master_ref != actual_master_ref:
        raise StageTaskbookRegistryError(
            "VALIDATOR_RESULT_MISMATCH",
            "Stored validator Master binding does not match the current v2.1 validator output.",
            details={"field": "master_taskbook_ref", "expected": expected_master_ref, "actual": actual_master_ref},
        )


def _validate_gate_readiness_summary(value: dict[str, Any], stage_id: str) -> None:
    required = {
        "minimum_readiness_claim": str,
        "gate_question": str,
        "criteria_count": int,
        "delivery_state_accepted": bool,
        "gate_readiness_is_delivery_state": bool,
    }
    unsupported = sorted(str(key) for key in value if key not in required)
    if unsupported:
        raise StageTaskbookRegistryError(
            "GATE_READINESS_UNSUPPORTED_FIELD",
            "Gate-readiness summary contains unsupported fields.",
            details={"stage_id": stage_id, "unsupported_fields": unsupported},
        )
    missing = [key for key in required if key not in value]
    if missing:
        raise StageTaskbookRegistryError(
            "GATE_READINESS_REQUIRED_FIELD_MISSING",
            "Gate-readiness summary is missing required fields.",
            details={"stage_id": stage_id, "missing_fields": missing},
        )
    invalid_types = [
        key
        for key, expected_type in required.items()
        if not isinstance(value.get(key), expected_type)
    ]
    if invalid_types:
        raise StageTaskbookRegistryError(
            "GATE_READINESS_FIELD_INVALID",
            "Gate-readiness summary contains invalid field types.",
            details={"stage_id": stage_id, "invalid_fields": invalid_types},
        )
    if not value["minimum_readiness_claim"].strip() or not value["gate_question"].strip():
        raise StageTaskbookRegistryError(
            "GATE_READINESS_FIELD_EMPTY",
            "Gate-readiness summary text fields must be non-empty.",
            details={"stage_id": stage_id},
        )
    if not isinstance(value["criteria_count"], int) or value["criteria_count"] < 1:
        raise StageTaskbookRegistryError(
            "GATE_READINESS_CRITERIA_COUNT_INVALID",
            "Gate-readiness summary must record at least one criterion.",
            details={"stage_id": stage_id, "criteria_count": value.get("criteria_count")},
        )
    if value["delivery_state_accepted"] is not False or value["gate_readiness_is_delivery_state"] is not False:
        raise StageTaskbookRegistryError(
            "GATE_READINESS_AUTHORITY_BOUNDARY_INVALID",
            "Gate-readiness summary must not claim accepted delivery state.",
            details={"stage_id": stage_id},
        )


def _validate_non_goals_summary(value: Any, stage_id: str) -> None:
    if not isinstance(value, list) or not value:
        raise StageTaskbookRegistryError(
            "NON_GOALS_SUMMARY_INVALID",
            "Stage registry record must include a non-empty non_goals_summary list.",
            details={"stage_id": stage_id},
        )
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise StageTaskbookRegistryError(
            "NON_GOALS_SUMMARY_INVALID",
            "Stage registry non_goals_summary items must be non-empty strings.",
            details={"stage_id": stage_id},
        )


def _resolve_registry_path(root: Path, registry_path: str | Path | None) -> Path:
    if registry_path is None:
        path = default_stage_taskbook_registry_path(root).resolve()
    else:
        candidate = Path(registry_path).expanduser()
        path = candidate if candidate.is_absolute() else root / candidate
        path = path.resolve()
    _ensure_inside_project(root, path, "registry_path")
    return path


def _resolve_project_relpath(root: Path, raw_path: str, field: str) -> Path:
    if not raw_path.strip():
        raise StageTaskbookRegistryError("FIELD_EMPTY", f"{field} must be a non-empty path.")
    candidate = Path(raw_path)
    if candidate.is_absolute():
        raise StageTaskbookRegistryError("ABSOLUTE_PATH_FORBIDDEN", f"{field} must be project-relative.")
    resolved = (root / candidate).resolve()
    _ensure_inside_project(root, resolved, field)
    return resolved


def _ensure_inside_project(root: Path, path: Path, field: str) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise StageTaskbookRegistryError(
            "PATH_OUTSIDE_PROJECT",
            f"{field} must stay inside the project root.",
            details={"field": field, "path": str(path), "project_root": str(root)},
        ) from exc


def _validate_required_and_allowed(
    *,
    value: dict[str, Any],
    required: tuple[str, ...],
    allowed: frozenset[str],
    object_name: str,
) -> None:
    missing = [field for field in required if field not in value]
    if missing:
        raise StageTaskbookRegistryError(
            "REQUIRED_FIELD_MISSING",
            f"{object_name} is missing required fields.",
            details={"object": object_name, "missing_fields": missing},
        )
    unsupported = sorted(str(field) for field in value if field not in allowed)
    if unsupported:
        raise StageTaskbookRegistryError(
            "UNSUPPORTED_FIELD",
            f"{object_name} contains unsupported fields.",
            details={"object": object_name, "unsupported_fields": unsupported},
        )


def _required_str(record: dict[str, Any], field: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        raise StageTaskbookRegistryError("FIELD_INVALID", f"{field} must be a non-empty string.")
    return value.strip()


def _require_exact_str(record: dict[str, Any], field: str, expected: str) -> None:
    value = _required_str(record, field)
    if value != expected:
        raise StageTaskbookRegistryError(
            "FIELD_VALUE_UNSUPPORTED",
            f"{field} must be {expected!r}.",
            details={"field": field, "expected": expected, "actual": value},
        )


def _required_dict(record: dict[str, Any], field: str) -> dict[str, Any]:
    value = record.get(field)
    if not isinstance(value, dict):
        raise StageTaskbookRegistryError("FIELD_INVALID", f"{field} must be an object.")
    return value


def _required_sha256(record: dict[str, Any], field: str) -> str:
    value = _required_str(record, field)
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise StageTaskbookRegistryError("FIELD_INVALID", f"{field} must be a lowercase sha256 hex string.")
    return value


def _required_sha_like(record: dict[str, Any], field: str) -> str:
    value = _required_str(record, field)
    if len(value) < 7 or any(char not in "0123456789abcdef" for char in value):
        raise StageTaskbookRegistryError("FIELD_INVALID", f"{field} must be a lowercase git hash string.")
    return value


def _validate_boolean_expectations(
    *,
    record: dict[str, Any],
    field: str,
    expectations: dict[str, bool],
) -> None:
    unsupported = sorted(str(key) for key in record if key not in expectations)
    if unsupported:
        raise StageTaskbookRegistryError(
            "AUTHORITY_BOUNDARY_UNSUPPORTED_FIELD",
            f"{field} contains unsupported fields.",
            details={"field": field, "unsupported_fields": unsupported},
        )
    for key, expected in expectations.items():
        if record.get(key) is not expected:
            raise StageTaskbookRegistryError(
                "AUTHORITY_BOUNDARY_INVALID",
                f"{field}.{key} must be {expected!r}.",
                details={"field": field, "key": key, "expected": expected, "actual": record.get(key)},
            )


def _validate_ahead_behind(value: dict[str, Any]) -> None:
    unsupported = sorted(str(key) for key in value if key not in ALLOWED_AHEAD_BEHIND_FIELDS)
    if unsupported:
        raise StageTaskbookRegistryError(
            "AHEAD_BEHIND_UNSUPPORTED_FIELD",
            "ahead_behind_from_local_refs contains unsupported fields.",
            details={"unsupported_fields": unsupported},
        )
    for key in ("ahead", "behind"):
        if not isinstance(value.get(key), int) or value[key] < 0:
            raise StageTaskbookRegistryError(
                "AHEAD_BEHIND_INVALID",
                f"ahead_behind_from_local_refs.{key} must be a non-negative integer.",
            )


def _validate_source_ref(*, root: Path, value: dict[str, Any], field: str, expected: dict[str, str]) -> None:
    allowed_fields = frozenset({"path", "raw_snapshot_sha256", "version_id"})
    unsupported = sorted(str(key) for key in value if key not in allowed_fields)
    if unsupported:
        raise StageTaskbookRegistryError(
            "SOURCE_REF_UNSUPPORTED_FIELD",
            f"{field} contains unsupported fields.",
            details={"field": field, "unsupported_fields": unsupported},
        )
    _validate_exact_object(
        record=value,
        field=field,
        expected={
            "path": expected["path"],
            "raw_snapshot_sha256": expected["raw_snapshot_sha256"],
            "version_id": expected["version_id"],
        },
    )
    source_path = _resolve_project_relpath(root, value["path"], f"{field}.path")
    if not source_path.is_file():
        raise StageTaskbookRegistryError(
            "SOURCE_REF_FILE_MISSING",
            f"{field}.path does not exist.",
            details={"field": field, "path": str(source_path)},
        )
    actual_hash = sha256_file(source_path)
    if actual_hash != expected["raw_snapshot_sha256"]:
        raise StageTaskbookRegistryError(
            "SOURCE_REF_HASH_MISMATCH",
            f"{field}.raw_snapshot_sha256 does not match current file content.",
            details={"field": field, "path": str(source_path), "expected": expected["raw_snapshot_sha256"], "actual": actual_hash},
        )


def _validate_master_taskbook_ref(
    *,
    root: Path,
    value: dict[str, Any],
    field: str,
    expected: dict[str, str],
) -> None:
    allowed_fields = frozenset({"path", "raw_snapshot_sha256", "review_status"})
    unsupported = sorted(str(key) for key in value if key not in allowed_fields)
    if unsupported:
        raise StageTaskbookRegistryError(
            "MASTER_REF_UNSUPPORTED_FIELD",
            f"{field} contains unsupported fields.",
            details={"field": field, "unsupported_fields": unsupported},
        )
    _validate_exact_object(record=value, field=field, expected=expected)
    master_path = _resolve_project_relpath(root, value["path"], f"{field}.path")
    if not master_path.is_file():
        raise StageTaskbookRegistryError(
            "MASTER_TASKBOOK_FILE_MISSING",
            "Master Taskbook file declared by registry does not exist.",
            details={"field": field, "master_taskbook_path": str(master_path)},
        )
    actual_hash = sha256_file(master_path)
    if actual_hash != expected["raw_snapshot_sha256"]:
        raise StageTaskbookRegistryError(
            "MASTER_TASKBOOK_HASH_MISMATCH",
            "Master Taskbook hash does not match registry binding.",
            details={"field": field, "expected": expected["raw_snapshot_sha256"], "actual": actual_hash},
        )


def _validate_exact_object(*, record: dict[str, Any], field: str, expected: dict[str, str]) -> None:
    unsupported = sorted(str(key) for key in record if key not in expected)
    if unsupported:
        raise StageTaskbookRegistryError(
            "OBJECT_UNSUPPORTED_FIELD",
            f"{field} contains unsupported fields.",
            details={"field": field, "unsupported_fields": unsupported},
        )
    missing = [key for key in expected if key not in record]
    if missing:
        raise StageTaskbookRegistryError(
            "OBJECT_REQUIRED_FIELD_MISSING",
            f"{field} is missing required fields.",
            details={"field": field, "missing_fields": missing},
        )
    for key, expected_value in expected.items():
        actual = record.get(key)
        if actual != expected_value:
            raise StageTaskbookRegistryError(
                "OBJECT_FIELD_VALUE_UNSUPPORTED",
                f"{field}.{key} must be {expected_value!r}.",
                details={"field": field, "key": key, "expected": expected_value, "actual": actual},
            )


def _reject_forbidden_authority_claims(value: Any, path: str = "registry") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            clean_key = str(key).strip()
            lower_key = clean_key.lower()
            if _is_truthy_authority_claim(lower_key, child):
                raise StageTaskbookRegistryError(
                    "FORBIDDEN_AUTHORITY_CLAIM",
                    "Stage Taskbook registry contains a forbidden authority claim.",
                    details={"path": f"{path}.{clean_key}", "value": child},
                )
            _reject_forbidden_authority_claims(child, f"{path}.{clean_key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_forbidden_authority_claims(child, f"{path}[{index}]")
    elif isinstance(value, str):
        _reject_forbidden_text_claims(value, path)


def _is_truthy_authority_claim(key: str, value: Any) -> bool:
    if key in ALLOWED_TRUE_AUTHORITY_KEYS:
        return False
    if not any(marker in key for marker in FORBIDDEN_AUTHORITY_KEY_MARKERS):
        return False
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "allowed", "active", "accepted", "authorized"}
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value != 0
    return False


def _reject_forbidden_text_claims(value: str, path: str) -> None:
    lowered = re.sub(r"[_-]+", " ", value.strip().lower())
    normalized = " ".join(lowered.split())
    for claim, pattern in FORBIDDEN_FREE_TEXT_CLAIM_PATTERNS:
        if pattern.search(normalized):
            raise StageTaskbookRegistryError(
                "FORBIDDEN_TEXT_AUTHORITY_CLAIM",
                "Stage Taskbook registry contains a forbidden free-text authority claim.",
                details={"path": path, "claim": claim, "value": value},
            )
