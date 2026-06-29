from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from runner.stage_taskbook_registry import (
    DEFAULT_REGISTRY_REL_PATH,
    EXPECTED_MASTER_TASKBOOK_REF,
    EXPECTED_SOURCE_VERSION_TASKBOOK_REF,
    StageTaskbookRegistryError,
    load_stage_taskbook_registry,
    sha256_file,
)


DEFAULT_STAGE_ID = "stage_02_stage_taskbook_management"
EXPECTED_PROJECT_FINAL_GOAL_REF = "master_taskbook.project_final_goal"
EXPECTED_MASTER_REVIEW_STATUS = "freeze_candidate_confirmed_for_exact_hash"

FORBIDDEN_STAGE_BINDING_PATTERNS = (
    (
        "stage_claims_master_mutation_authority",
        re.compile(
            r"\bstage\b.{0,80}\b(?:may|can|must|shall|is allowed to|is authorized to|authori[sz]es?)\b"
            r".{0,80}\b(?:mutate|modify|edit|rewrite|override|change)\b.{0,80}\bmaster\b"
            r"|\b(?:mutate|modify|edit|rewrite|override|change)\b.{0,80}\bmaster\s+taskbook\b"
            r"|\bmaster\s+mutation\s+(?:authority|authorized|allowed|granted)\b"
        ),
    ),
    (
        "stage_claims_project_final_goal_mutation",
        re.compile(
            r"\bproject[_\s-]+final[_\s-]+goal\b.{0,80}\b(?:mutat|modify|edit|rewrite|override|change)"
            r"|\b(?:mutat|modify|edit|rewrite|override|change)\b.{0,80}\bproject[_\s-]+final[_\s-]+goal\b"
        ),
    ),
    (
        "stage_claims_freeze_candidate_is_execution_authority",
        re.compile(
            r"\bfreeze[_\s-]+candidate\b.{0,100}\b(?:execution|executor|dispatch)\b.{0,40}"
            r"\b(?:authority|authorization|authorized|allowed|granted)\b"
            r"|\b(?:execution|executor|dispatch)\b.{0,100}\bfreeze[_\s-]+candidate\b.{0,40}"
            r"\b(?:authority|authorization|authorized|allowed|granted)\b"
        ),
    ),
    (
        "stage_claims_delivery_state_accepted",
        re.compile(
            r"\bdelivery[_\s-]+state\b.{0,80}\baccepted\b"
            r"|\baccepted[_\s-]+delivery[_\s-]+state\b"
        ),
    ),
)


class StageToMasterBindingError(ValueError):
    def __init__(self, error_code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.details = details or {}


def validate_stage_to_master_binding(
    project_root: str | Path,
    registry_path: str | Path | None = None,
    *,
    stage_id: str = DEFAULT_STAGE_ID,
    expected_master_taskbook_ref: dict[str, str] | None = None,
    expected_registry_source_ref: dict[str, str] | None = None,
) -> dict[str, Any]:
    root = Path(project_root).expanduser().resolve()
    expected_master_ref = expected_master_taskbook_ref or EXPECTED_MASTER_TASKBOOK_REF
    expected_source_ref = expected_registry_source_ref or EXPECTED_SOURCE_VERSION_TASKBOOK_REF

    try:
        registry_result = load_stage_taskbook_registry(
            root,
            registry_path,
            expected_master_taskbook_ref=expected_master_ref,
            expected_source_version_ref=expected_source_ref,
        )
    except StageTaskbookRegistryError as exc:
        raise StageToMasterBindingError(
            "REGISTRY_VALIDATION_FAILED",
            "Stage-to-Master binding requires a valid Stage Taskbook registry result.",
            details={"registry_error_code": exc.error_code, "registry_error_details": exc.details},
        ) from exc

    records = registry_result.get("records", {})
    record = records.get(stage_id)
    if not isinstance(record, dict):
        raise StageToMasterBindingError(
            "STAGE_REGISTRY_RECORD_MISSING",
            "Stage-to-Master binding requires a registry record for the requested stage.",
            details={"stage_id": stage_id, "available_stage_ids": sorted(records)},
        )

    master_ref = _required_dict(record, "master_taskbook_ref")
    _validate_master_ref(master_ref, expected_master_ref)
    master_path = _resolve_project_relpath(root, _required_str(master_ref, "path"), "master_taskbook_ref.path")
    master_actual_hash = sha256_file(master_path)
    if master_actual_hash != expected_master_ref["raw_snapshot_sha256"]:
        raise StageToMasterBindingError(
            "MASTER_HASH_MISMATCH",
            "Master Taskbook hash does not match the expected Stage-to-Master binding.",
            details={"expected": expected_master_ref["raw_snapshot_sha256"], "actual": master_actual_hash},
        )

    master_content = master_path.read_text(encoding="utf-8")
    if not _master_has_project_final_goal(master_content):
        raise StageToMasterBindingError(
            "MASTER_PROJECT_FINAL_GOAL_MISSING",
            "Master Taskbook must expose project_final_goal before Stage binding can pass.",
            details={"master_taskbook_path": _relpath(root, master_path)},
        )

    stage_path_raw = Path(_required_str(record, "stage_taskbook_path")).expanduser()
    stage_path = stage_path_raw.resolve() if stage_path_raw.is_absolute() else (root / stage_path_raw).resolve()
    _ensure_inside_project(root, stage_path, "stage_taskbook_path")
    if not stage_path.is_file():
        raise StageToMasterBindingError(
            "STAGE_TASKBOOK_FILE_MISSING",
            "Registered Stage Taskbook file does not exist.",
            details={"stage_taskbook_path": str(stage_path)},
        )
    stage_content = stage_path.read_text(encoding="utf-8")

    project_final_goal_ref = _first_exact_value(stage_content, ("project_final_goal_ref",))
    if project_final_goal_ref != EXPECTED_PROJECT_FINAL_GOAL_REF:
        raise StageToMasterBindingError(
            "PROJECT_FINAL_GOAL_REF_INVALID",
            "Stage Taskbook must preserve project_final_goal_ref as a Master reference.",
            details={"expected": EXPECTED_PROJECT_FINAL_GOAL_REF, "actual": project_final_goal_ref},
        )

    registry_supports_project_goal = record.get("supports_project_goal")
    if registry_supports_project_goal is None:
        validator_result = record.get("validator_result")
        if isinstance(validator_result, dict):
            registry_supports_project_goal = validator_result.get("supports_project_goal")
    if registry_supports_project_goal is not True:
        raise StageToMasterBindingError(
            "SUPPORTS_PROJECT_GOAL_INVALID",
            "Stage registry record must preserve supports_project_goal: true.",
            details={"stage_id": stage_id, "actual": registry_supports_project_goal},
        )

    stage_supports_project_goal = _first_exact_value(stage_content, ("supports_project_goal",))
    if _parse_yaml_bool(stage_supports_project_goal) is not True:
        raise StageToMasterBindingError(
            "STAGE_SUPPORTS_PROJECT_GOAL_INVALID",
            "Stage Taskbook must preserve supports_project_goal: true.",
            details={"stage_id": stage_id, "actual": stage_supports_project_goal},
        )

    support_rationale = _extract_stage_purpose(stage_content)
    if not support_rationale:
        raise StageToMasterBindingError(
            "SUPPORT_RATIONALE_MISSING",
            "Stage Taskbook must include a non-empty Stage Purpose support rationale.",
            details={"stage_id": stage_id},
        )

    forbidden_claims = _detect_forbidden_stage_binding_claims(stage_content)
    if forbidden_claims:
        raise StageToMasterBindingError(
            "FORBIDDEN_STAGE_BINDING_CLAIM",
            "Stage Taskbook contains a forbidden Stage-to-Master authority claim.",
            details={"stage_id": stage_id, "forbidden_claims": forbidden_claims},
        )

    registry_path_resolved = _resolve_registry_path(root, registry_path)
    source_stage_ref = {
        "path": _relpath(root, stage_path),
        "raw_snapshot_sha256": record["stage_taskbook_hash"],
        "stage_id": stage_id,
    }
    source_registry_ref = {
        "path": _relpath(root, registry_path_resolved),
        "raw_snapshot_sha256": sha256_file(registry_path_resolved),
        "registry_record_id": registry_result["registry_record_id"],
        "record_key": "stage_id",
        "stage_id": stage_id,
    }

    return {
        "binding_status": "bound",
        "validation_result": "passed",
        "fail_closed_result": "pass",
        "stage_id": stage_id,
        "master_taskbook_ref": {
            "path": master_ref["path"],
            "raw_snapshot_sha256": master_ref["raw_snapshot_sha256"],
            "review_status": master_ref["review_status"],
        },
        "master_hash_match_check": {
            "result": "passed",
            "expected_sha256": expected_master_ref["raw_snapshot_sha256"],
            "actual_sha256": master_actual_hash,
            "master_path": _relpath(root, master_path),
        },
        "project_final_goal_ref_preservation_check": {
            "result": "passed",
            "expected": EXPECTED_PROJECT_FINAL_GOAL_REF,
            "actual": project_final_goal_ref,
            "master_project_final_goal_present": True,
        },
        "freeze_candidate_boundary_check": {
            "result": "passed",
            "master_review_status": master_ref["review_status"],
            "treated_as_execution_authority": False,
        },
        "source_stage_taskbook_ref": source_stage_ref,
        "source_registry_record_ref": source_registry_ref,
        "supports_project_goal": True,
        "support_rationale": support_rationale,
        "registry_result_consumed": True,
        "registry_validator_results_verified": registry_result["validator_results_verified"],
        "negative_case_results": {
            "missing_master_taskbook_ref": "covered_by_registry_validator",
            "master_hash_mismatch": "covered_by_registry_or_binding_helper",
            "missing_project_final_goal_ref": "covered_by_binding_helper",
            "supports_project_goal_is_false_or_missing": "covered_by_binding_helper",
            "stage_claims_master_mutation_authority": "covered_by_binding_helper",
            "stage_claims_freeze_candidate_is_execution_authority": "covered_by_binding_helper",
            "stage_claims_delivery_state_accepted": "covered_by_registry_or_binding_helper",
        },
        "binding_result_is_authority": False,
        "creates_review_decision": False,
        "emits_gate_event": False,
        "writes_delivery_state": False,
        "mutates_master_taskbook": False,
        "mutates_project_final_goal": False,
        "authorizes_execution": False,
    }


def _resolve_registry_path(root: Path, registry_path: str | Path | None) -> Path:
    raw_path = registry_path or DEFAULT_REGISTRY_REL_PATH
    candidate = Path(raw_path).expanduser()
    resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    _ensure_inside_project(root, resolved, "registry_path")
    return resolved


def _resolve_project_relpath(root: Path, raw_path: str, field: str) -> Path:
    if not raw_path.strip():
        raise StageToMasterBindingError("FIELD_EMPTY", f"{field} must be a non-empty path.")
    candidate = Path(raw_path)
    if candidate.is_absolute():
        raise StageToMasterBindingError("ABSOLUTE_PATH_FORBIDDEN", f"{field} must be project-relative.")
    resolved = (root / candidate).resolve()
    _ensure_inside_project(root, resolved, field)
    return resolved


def _ensure_inside_project(root: Path, path: Path, field: str) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise StageToMasterBindingError(
            "PATH_OUTSIDE_PROJECT",
            f"{field} must stay inside the project root.",
            details={"field": field, "path": str(path), "project_root": str(root)},
        ) from exc


def _relpath(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root).as_posix()


def _required_dict(record: dict[str, Any], field: str) -> dict[str, Any]:
    value = record.get(field)
    if not isinstance(value, dict):
        raise StageToMasterBindingError("FIELD_INVALID", f"{field} must be an object.")
    return value


def _required_str(record: dict[str, Any], field: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        raise StageToMasterBindingError("FIELD_INVALID", f"{field} must be a non-empty string.")
    return value.strip()


def _validate_master_ref(actual: dict[str, Any], expected: dict[str, str]) -> None:
    allowed_fields = frozenset({"path", "raw_snapshot_sha256", "review_status"})
    unsupported = sorted(str(key) for key in actual if key not in allowed_fields)
    if unsupported:
        raise StageToMasterBindingError(
            "MASTER_REF_UNSUPPORTED_FIELD",
            "Master Taskbook reference contains unsupported fields.",
            details={"unsupported_fields": unsupported},
        )
    missing = [key for key in allowed_fields if key not in actual]
    if missing:
        raise StageToMasterBindingError(
            "MASTER_REF_REQUIRED_FIELD_MISSING",
            "Master Taskbook reference is missing required fields.",
            details={"missing_fields": missing},
        )
    for key, expected_value in expected.items():
        if actual.get(key) != expected_value:
            raise StageToMasterBindingError(
                "MASTER_REF_VALUE_MISMATCH",
                "Master Taskbook reference must match the expected binding.",
                details={"field": key, "expected": expected_value, "actual": actual.get(key)},
            )
    if actual.get("review_status") != EXPECTED_MASTER_REVIEW_STATUS:
        raise StageToMasterBindingError(
            "MASTER_REVIEW_STATUS_INVALID",
            "Master review status is not the expected freeze candidate confirmation boundary.",
            details={"expected": EXPECTED_MASTER_REVIEW_STATUS, "actual": actual.get("review_status")},
        )


def _master_has_project_final_goal(raw: str) -> bool:
    return _has_exact_field(raw, "project_final_goal")


def _has_exact_field(raw: str, key: str) -> bool:
    return re.search(rf"^\s*{re.escape(key)}\s*:\s*(?:.*?)\s*$", raw, re.MULTILINE) is not None


def _first_exact_value(raw: str, keys: tuple[str, ...]) -> str | None:
    key_pattern = "|".join(re.escape(key) for key in keys)
    pattern = re.compile(rf"^\s*(?:{key_pattern})\s*:\s*(.*?)\s*$", re.MULTILINE)
    match = pattern.search(raw)
    if not match:
        return None
    value = match.group(1).strip()
    if not value or value in {"|", ">"}:
        return None
    return value.strip("\"'")


def _parse_yaml_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    return None


def _extract_stage_purpose(raw: str) -> str:
    match = re.search(r"^##\s+2\.\s+Stage Purpose\s*$", raw, flags=re.MULTILINE)
    if not match:
        match = re.search(r"^##\s+Stage Purpose\s*$", raw, flags=re.MULTILINE)
    if not match:
        return ""
    next_heading = re.search(r"^##\s+", raw[match.end() :], flags=re.MULTILINE)
    section = raw[match.end() : match.end() + next_heading.start()] if next_heading else raw[match.end() :]
    lines = []
    for raw_line in section.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("```"):
            break
        lines.append(line)
    return " ".join(lines).strip()


def _detect_forbidden_stage_binding_claims(raw: str) -> list[dict[str, str]]:
    claims = []
    for line in raw.splitlines():
        normalized = _normalize_for_detection(line)
        if not normalized or _is_negated_boundary_line(normalized):
            continue
        for claim, pattern in FORBIDDEN_STAGE_BINDING_PATTERNS:
            match = pattern.search(normalized)
            if match:
                claims.append({"claim": claim, "matched_text": match.group(0)})
    return claims


def _normalize_for_detection(value: str) -> str:
    lowered = value.lower()
    lowered = lowered.replace("_", " ").replace("-", " ")
    return " ".join(lowered.split())


def _is_negated_boundary_line(value: str) -> bool:
    negation_markers = (
        "must not",
        "does not",
        "do not",
        "not ",
        "no ",
        "never ",
        "distinct from",
        "separate from",
        "without becoming",
        "is not",
    )
    return any(marker in value for marker in negation_markers)
