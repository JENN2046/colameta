from __future__ import annotations

from typing import Any


DRIFT_EVIDENCE_SCHEMA_CHECK_PASSED = "drift_evidence_schema_check_passed"
DRIFT_EVIDENCE_SCHEMA_CHECK_FAILED_CLOSED = "drift_evidence_schema_check_failed_closed"
EXPECTED_DRIFT_EVIDENCE_SCHEMA_VERSION = "drift_evidence.v1"
REQUIRED_DRIFT_EVIDENCE_FIELDS = (
    "drift_evidence_pack_id",
    "master_taskbook_ref",
    "stage_taskbook_ref",
    "version_taskbook_ref",
    "execution_evidence_ref",
    "changed_files",
    "validation_truth",
    "scope_evidence",
    "forbidden_files_evidence",
    "out_of_scope_evidence",
    "master_goal_alignment_questions",
    "reviewer_drift_checklist",
    "plan_adjustment_trigger_conditions",
)
REQUIRED_OBJECT_REF_FIELDS = (
    "master_taskbook_ref",
    "stage_taskbook_ref",
    "version_taskbook_ref",
)
REQUIRED_EVIDENCE_FIELDS = (
    "execution_evidence_ref",
    "validation_truth",
    "scope_evidence",
    "forbidden_files_evidence",
    "out_of_scope_evidence",
)
REQUIRED_STRUCTURED_LIST_FIELDS = (
    "master_goal_alignment_questions",
    "reviewer_drift_checklist",
    "plan_adjustment_trigger_conditions",
)
FORBIDDEN_DRIFT_EVIDENCE_CLAIM_KEYS = frozenset(
    {
        "semantic_alignment_pass",
        "no_drift_confirmed",
        "review_decision_created",
        "gate_event_emitted",
        "delivery_state_accepted",
        "plan_mutated",
        "plan_mutation",
        "taskbook_rewritten",
        "master_goal_change",
        "master_goal_mutated",
        "executor_continuation_authorized",
        "commit_or_push",
        "stage_scope_expanded",
        "stage_scope_expansion",
    }
)
AUTHORITY_BOUNDARY_EXPECTATIONS = {
    "drift_evidence_result_is_authority": False,
    "semantic_alignment_pass": False,
    "no_drift_confirmed": False,
    "review_decision_created": False,
    "gate_event_emitted": False,
    "delivery_state_accepted": False,
    "plan_mutated": False,
    "taskbook_rewritten": False,
    "executor_continuation_authorized": False,
    "commit_or_push": False,
    "stage_scope_expanded": False,
}
ALIGNMENT_ANSWER_OPTIONS = ("YES", "NO", "UNCLEAR", "NOT_APPLICABLE")
DRIFT_ANSWER_OPTIONS = ("NO_DRIFT_VISIBLE", "DRIFT_VISIBLE", "UNCLEAR", "NOT_APPLICABLE")


class DriftEvidenceSchemaError(ValueError):
    def __init__(self, error_code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.details = details or {}


def validate_drift_evidence_schema(pack: dict[str, Any]) -> dict[str, Any]:
    rejected_fields: set[str] = set()
    rejection_reasons: list[dict[str, Any]] = []
    known_conflicts: list[dict[str, Any]] = []

    if not isinstance(pack, dict):
        return _schema_result(
            pack={},
            rejected_fields=[],
            rejection_reasons=[
                _reason(
                    "DRIFT_EVIDENCE_PACK_INVALID",
                    "DriftEvidencePack must be an object.",
                    {"actual_type": type(pack).__name__},
                )
            ],
            known_conflicts=[],
        )

    missing = [field for field in REQUIRED_DRIFT_EVIDENCE_FIELDS if field not in pack]
    if missing:
        rejected_fields.update(missing)
        rejection_reasons.append(
            _reason("REQUIRED_FIELD_MISSING", "DriftEvidencePack is missing required fields.", {"missing_fields": missing})
        )

    if "drift_evidence_pack_id" in pack and _empty(pack.get("drift_evidence_pack_id")):
        rejected_fields.add("drift_evidence_pack_id")
        rejection_reasons.append(
            _reason("REQUIRED_VALUE_EMPTY", "drift_evidence_pack_id must not be empty.", {"field": "drift_evidence_pack_id"})
        )

    for field in REQUIRED_OBJECT_REF_FIELDS:
        if field in pack and not _non_empty_dict(pack.get(field)):
            rejected_fields.add(field)
            rejection_reasons.append(
                _reason("REQUIRED_REF_MISSING", f"{field} must be a non-empty object.", {"field": field})
            )

    for field in REQUIRED_EVIDENCE_FIELDS:
        if field in pack and not _evidence_object_or_structured_list(pack.get(field)):
            rejected_fields.add(field)
            rejection_reasons.append(
                _reason(
                    "REQUIRED_EVIDENCE_MISSING",
                    f"{field} must be a non-empty object or non-empty structured list.",
                    {"field": field},
                )
            )

    if "changed_files" in pack and not _changed_files_present(pack.get("changed_files")):
        rejected_fields.add("changed_files")
        rejection_reasons.append(
            _reason(
                "CHANGED_FILES_MISSING",
                "changed_files must be a non-empty list of file paths or structured file records.",
                {"field": "changed_files"},
            )
        )

    for field in REQUIRED_STRUCTURED_LIST_FIELDS:
        if field in pack and not _non_empty_structured_list(pack.get(field)):
            rejected_fields.add(field)
            rejection_reasons.append(
                _reason("STRUCTURED_LIST_MISSING", f"{field} must be a non-empty structured list.", {"field": field})
            )

    question_rejections = _validate_master_goal_alignment_questions(pack.get("master_goal_alignment_questions"))
    if question_rejections:
        rejected_fields.add("master_goal_alignment_questions")
        rejection_reasons.append(
            _reason(
                "MASTER_GOAL_ALIGNMENT_QUESTIONS_INVALID",
                "Master goal alignment questions must remain explicit, evidence-bound, and unanswered.",
                {"rejected_questions": question_rejections},
            )
        )

    checklist_rejections = _validate_reviewer_drift_checklist(pack.get("reviewer_drift_checklist"))
    if checklist_rejections:
        rejected_fields.add("reviewer_drift_checklist")
        rejection_reasons.append(
            _reason(
                "REVIEWER_DRIFT_CHECKLIST_INVALID",
                "Reviewer drift checklist entries must remain explicit, evidence-bound, and unanswered.",
                {"rejected_items": checklist_rejections},
            )
        )

    trigger_rejections = _validate_plan_adjustment_trigger_conditions(pack.get("plan_adjustment_trigger_conditions"))
    if trigger_rejections:
        rejected_fields.add("plan_adjustment_trigger_conditions")
        rejection_reasons.append(
            _reason(
                "PLAN_ADJUSTMENT_TRIGGER_CONDITIONS_INVALID",
                "Plan adjustment trigger conditions must be explicit preview-only condition records.",
                {"rejected_conditions": trigger_rejections},
            )
        )

    forbidden_claims = _forbidden_truthy_claims(pack, "drift_evidence_pack")
    if forbidden_claims:
        rejected_fields.update(item["path"] for item in forbidden_claims)
        rejection_reasons.append(
            _reason(
                "FORBIDDEN_DRIFT_EVIDENCE_AUTHORITY_CLAIM",
                "DriftEvidencePack contains forbidden authority claims.",
                {"forbidden_claims": _safe_forbidden_claims(forbidden_claims)},
            )
        )
        known_conflicts.extend(
            {"conflict_type": "authority_boundary", "path": item["path"], "claim": item["key"]}
            for item in forbidden_claims
        )

    result = _schema_result(
        pack=pack,
        rejected_fields=sorted(rejected_fields),
        rejection_reasons=rejection_reasons,
        known_conflicts=known_conflicts,
    )
    assert_drift_evidence_schema_result_contract(result)
    return result


def assert_drift_evidence_schema_result_contract(result: dict[str, Any]) -> None:
    if not isinstance(result, dict):
        raise DriftEvidenceSchemaError("DRIFT_EVIDENCE_SCHEMA_RESULT_INVALID", "DriftEvidence schema result must be an object.")
    if result.get("authority_boundary") != AUTHORITY_BOUNDARY_EXPECTATIONS:
        raise DriftEvidenceSchemaError(
            "FORBIDDEN_DRIFT_EVIDENCE_SCHEMA_RESULT_AUTHORITY_CLAIM",
            "DriftEvidence schema result authority boundary must remain false.",
            details={"expected": AUTHORITY_BOUNDARY_EXPECTATIONS, "actual": result.get("authority_boundary")},
        )
    forbidden_claims = _forbidden_truthy_claims(result, "result")
    if forbidden_claims:
        raise DriftEvidenceSchemaError(
            "FORBIDDEN_DRIFT_EVIDENCE_SCHEMA_RESULT_CLAIM",
            "DriftEvidence schema result contains forbidden authority claims.",
            details={"forbidden_claims": _safe_forbidden_claims(forbidden_claims)},
        )


def drift_evidence_field_inventory() -> dict[str, Any]:
    return {
        "schema_version": EXPECTED_DRIFT_EVIDENCE_SCHEMA_VERSION,
        "required_fields": list(REQUIRED_DRIFT_EVIDENCE_FIELDS),
        "required_object_ref_fields": list(REQUIRED_OBJECT_REF_FIELDS),
        "required_evidence_fields": list(REQUIRED_EVIDENCE_FIELDS),
        "required_structured_list_fields": list(REQUIRED_STRUCTURED_LIST_FIELDS),
        "forbidden_authority_claim_keys": sorted(FORBIDDEN_DRIFT_EVIDENCE_CLAIM_KEYS),
        "authority_boundary": dict(AUTHORITY_BOUNDARY_EXPECTATIONS),
    }


def example_drift_evidence_pack() -> dict[str, Any]:
    evidence_refs = [{"evidence_id": "executor-report-example", "source": "executor_report"}]
    return {
        "drift_evidence_pack_id": "drift-evidence-example",
        "master_taskbook_ref": {
            "path": "PROJECT_MASTER_TASKBOOK.md",
            "sha256": "1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34",
        },
        "stage_taskbook_ref": {
            "stage_id": "stage_07_drift_evidence_and_correction",
            "path": "docs/taskbooks/stages/STAGE_07_DRIFT_EVIDENCE_AND_CORRECTION.md",
        },
        "version_taskbook_ref": {"version": "v1.12", "name": "Stage 7 Drift Evidence Schema V1"},
        "execution_evidence_ref": {"report_id": "executor-report-example", "status": "completed"},
        "changed_files": ["runner/drift_evidence_schema.py", "tests/test_drift_evidence_schema.py"],
        "validation_truth": {"truth_source": "structured_command_records", "status": "not_evaluated_by_schema"},
        "scope_evidence": {"allowed_files": ["runner/drift_evidence_schema.py", "tests/test_drift_evidence_schema.py"]},
        "forbidden_files_evidence": {"forbidden_files_touched": [], "source": "scope_check"},
        "out_of_scope_evidence": {"out_of_scope_files": [], "source": "scope_check"},
        "master_goal_alignment_questions": [
            {
                "question_id": "project_final_goal_alignment",
                "question_text": "Does the evidence support the project final goal rather than only local task completion?",
                "target_ref": {"target": "project_final_goal"},
                "evidence_refs": evidence_refs,
                "reviewer_answer_options": list(ALIGNMENT_ANSWER_OPTIONS),
                "unanswered_state": "UNANSWERED",
            }
        ],
        "reviewer_drift_checklist": [
            {
                "drift_question_id": "project_goal_drift",
                "drift_type": "project_goal_drift",
                "question_text": "Did the work move away from the project final goal?",
                "expected_reference": {"expected": "project_final_goal"},
                "observed_evidence_refs": evidence_refs,
                "reviewer_answer_options": list(DRIFT_ANSWER_OPTIONS),
                "unresolved_followup_prompt": "If unclear or drift is visible, describe the follow-up needed.",
            }
        ],
        "plan_adjustment_trigger_conditions": [
            {
                "trigger_condition_id": "plan_adjust_if_reviewer_finds_drift",
                "condition_text": "If Reviewer reports drift or unclear alignment, route only to Stage 8 plan adjustment preview.",
                "stage_8_preview_required": True,
            }
        ],
    }


def _schema_result(
    *,
    pack: dict[str, Any],
    rejected_fields: list[str],
    rejection_reasons: list[dict[str, Any]],
    known_conflicts: list[dict[str, Any]],
) -> dict[str, Any]:
    passed = not rejection_reasons
    return {
        "drift_evidence_schema_check_result": DRIFT_EVIDENCE_SCHEMA_CHECK_PASSED if passed else DRIFT_EVIDENCE_SCHEMA_CHECK_FAILED_CLOSED,
        "validation_result": "passed" if passed else "failed_closed",
        "schema_version": EXPECTED_DRIFT_EVIDENCE_SCHEMA_VERSION,
        "recognized_fields": [field for field in REQUIRED_DRIFT_EVIDENCE_FIELDS if field in pack],
        "rejected_fields": rejected_fields,
        "rejection_reasons": rejection_reasons,
        "known_conflicts": known_conflicts,
        "authority_boundary": dict(AUTHORITY_BOUNDARY_EXPECTATIONS),
        "semantic_alignment_pass": False,
        "no_drift_confirmed": False,
        "review_decision_created": False,
        "gate_event_emitted": False,
        "delivery_state_accepted": False,
        "plan_mutated": False,
        "taskbook_rewritten": False,
        "executor_continuation_authorized": False,
        "commit_or_push": False,
        "stage_scope_expanded": False,
        "semantic_drift_judgment": None,
    }


def _validate_master_goal_alignment_questions(value: Any) -> list[dict[str, Any]]:
    rejections: list[dict[str, Any]] = []
    if not isinstance(value, list):
        return rejections
    for index, question in enumerate(value):
        if not isinstance(question, dict):
            continue
        missing: list[str] = []
        if _empty(question.get("question_text")):
            missing.append("question_text")
        if not _ref_or_structured_list(question.get("target_ref")) and not _ref_or_structured_list(question.get("expected_reference")):
            missing.append("target_ref")
        if not _non_empty_structured_list(question.get("evidence_refs")) and not _non_empty_structured_list(question.get("observed_evidence_refs")):
            missing.append("evidence_refs")
        if missing:
            rejections.append({"index": index, "reason": "missing_fields", "missing_fields": missing})
        answer_options = question.get("reviewer_answer_options")
        if answer_options is not None and sorted(str(item) for item in answer_options) != sorted(ALIGNMENT_ANSWER_OPTIONS):
            rejections.append({"index": index, "reason": "answer_options_mismatch"})
        prefilled_answer = _prefilled_answer_field(question)
        if prefilled_answer:
            rejections.append({"index": index, "reason": "prefilled_reviewer_answer", "field": prefilled_answer})
    return rejections


def _validate_reviewer_drift_checklist(value: Any) -> list[dict[str, Any]]:
    rejections: list[dict[str, Any]] = []
    if not isinstance(value, list):
        return rejections
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            continue
        missing: list[str] = []
        if _empty(item.get("question_text")) and _empty(item.get("checklist_item_text")) and _empty(item.get("check_text")):
            missing.append("question_text")
        if not _ref_or_structured_list(item.get("expected_reference")) and _empty(item.get("drift_type")):
            missing.append("expected_reference")
        if not _non_empty_structured_list(item.get("observed_evidence_refs")) and not _non_empty_structured_list(item.get("evidence_refs")):
            missing.append("evidence_refs")
        if missing:
            rejections.append({"index": index, "reason": "missing_fields", "missing_fields": missing})
        answer_options = item.get("reviewer_answer_options")
        if answer_options is not None and sorted(str(option) for option in answer_options) != sorted(DRIFT_ANSWER_OPTIONS):
            rejections.append({"index": index, "reason": "answer_options_mismatch"})
        prefilled_answer = _prefilled_answer_field(item)
        if prefilled_answer:
            rejections.append({"index": index, "reason": "prefilled_reviewer_answer", "field": prefilled_answer})
    return rejections


def _validate_plan_adjustment_trigger_conditions(value: Any) -> list[dict[str, Any]]:
    rejections: list[dict[str, Any]] = []
    if not isinstance(value, list):
        return rejections
    for index, condition in enumerate(value):
        if not isinstance(condition, dict):
            continue
        if _empty(condition.get("trigger_condition_id")) and _empty(condition.get("condition_id")):
            rejections.append({"index": index, "reason": "missing_trigger_condition_id"})
        if _empty(condition.get("condition_text")) and _empty(condition.get("description")):
            rejections.append({"index": index, "reason": "missing_condition_text"})
    return rejections


def _reason(code: str, message: str, details: dict[str, Any]) -> dict[str, Any]:
    return {"code": code, "message": message, "details": details}


def _non_empty_dict(value: Any) -> bool:
    return isinstance(value, dict) and bool(value)


def _non_empty_structured_list(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(item, dict) and bool(item) for item in value)


def _ref_or_structured_list(value: Any) -> bool:
    return _non_empty_dict(value) or _non_empty_structured_list(value)


def _evidence_object_or_structured_list(value: Any) -> bool:
    return _ref_or_structured_list(value)


def _changed_files_present(value: Any) -> bool:
    if not isinstance(value, list) or not value:
        return False
    for item in value:
        if isinstance(item, str) and item.strip():
            continue
        if isinstance(item, dict) and item:
            continue
        return False
    return True


def _empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict, str)):
        return len(value) == 0
    return False


def _prefilled_answer_field(record: dict[str, Any]) -> str:
    for field in ("answer", "recommended_answer"):
        if field not in record:
            continue
        value = record.get(field)
        if _empty(value):
            continue
        if isinstance(value, str) and value.strip().upper() == "UNANSWERED":
            continue
        return field
    return ""


def _forbidden_truthy_claims(value: Any, path: str = "drift_evidence") -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if str(key) in FORBIDDEN_DRIFT_EVIDENCE_CLAIM_KEYS and _truthy_claim(child):
                claims.append({"path": child_path, "key": str(key)})
            claims.extend(_forbidden_truthy_claims(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            claims.extend(_forbidden_truthy_claims(child, f"{path}[{index}]"))
    return claims


def _truthy_claim(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {
            "true",
            "yes",
            "accepted",
            "accept",
            "created",
            "authorized",
            "confirmed",
            "executed",
            "emitted",
            "mutated",
            "rewritten",
            "expanded",
            "pass",
            "passed",
        }
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value != 0
    return False


def _safe_forbidden_claims(claims: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [{"path": str(item["path"]), "key": str(item["key"])} for item in claims]
