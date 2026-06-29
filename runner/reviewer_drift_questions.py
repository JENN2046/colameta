from __future__ import annotations

from typing import Any


DRIFT_QUESTIONS_CHECK_PASSED = "drift_questions_check_passed"
DRIFT_QUESTIONS_CHECK_FAILED_CLOSED = "drift_questions_check_failed_closed"
DRIFT_ANSWER_OPTIONS = ("NO_DRIFT_VISIBLE", "DRIFT_VISIBLE", "UNCLEAR", "NOT_APPLICABLE")
REQUIRED_DRIFT_GROUPS = ("project_goal_drift", "scope_drift", "authority_drift", "evidence_drift", "validation_drift", "risk_drift")
REQUIRED_DRIFT_FIELDS = (
    "drift_question_id",
    "drift_type",
    "question_text",
    "expected_reference",
    "observed_evidence_refs",
    "reviewer_answer_options",
    "unresolved_followup_prompt",
)
FORBIDDEN_DRIFT_CLAIM_KEYS = frozenset(
    {
        "generator_marks_no_drift_by_default",
        "generator_converts_drift_to_review_decision",
        "no_drift_confirmed",
        "review_decision_created",
        "delivery_state_transitioned",
        "delivery_state_accepted",
    }
)
AUTHORITY_BOUNDARY_EXPECTATIONS = {
    "drift_questions_result_is_authority": False,
    "drift_questions_default_no_drift": False,
    "drift_questions_create_review_decision": False,
    "drift_questions_emit_gate_event": False,
    "drift_questions_write_delivery_state": False,
}


class ReviewerDriftQuestionsError(ValueError):
    pass


def default_drift_questions(evidence_refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        _question("project_goal_drift", "Did the work move away from the project final goal?", evidence_refs),
        _question("scope_drift", "Were any changed files outside the declared allowed scope?", evidence_refs),
        _question("authority_drift", "Did any artifact claim commit push executor route review or state authority without authorization?", evidence_refs),
        _question("evidence_drift", "Do claims point to the evidence they depend on?", evidence_refs),
        _question("validation_drift", "Are failed or skipped validations visible?", evidence_refs),
        _question("risk_drift", "Are unresolved risks still visible to Reviewer?", evidence_refs),
    ]


def validate_drift_questions(questions: list[dict[str, Any]]) -> dict[str, Any]:
    rejection_reasons: list[dict[str, Any]] = []
    rejected_questions: list[dict[str, Any]] = []
    groups = {item.get("drift_type") for item in questions if isinstance(item, dict)}

    if not isinstance(questions, list) or not questions:
        rejection_reasons.append(_reason("DRIFT_QUESTION_LIST_MISSING", "Drift questions must be a non-empty list.", {}))
        groups = set()

    missing_groups = [group for group in REQUIRED_DRIFT_GROUPS if group not in groups]
    if missing_groups:
        rejection_reasons.append(_reason("DRIFT_GROUP_MISSING", "Required drift groups are missing.", {"missing_groups": missing_groups}))

    for index, question in enumerate(questions if isinstance(questions, list) else []):
        if not isinstance(question, dict):
            rejected_questions.append({"index": index, "reason": "not_object"})
            continue
        missing = [field for field in REQUIRED_DRIFT_FIELDS if field not in question]
        if missing:
            rejected_questions.append({"index": index, "reason": "missing_fields", "missing_fields": missing})
        if question.get("reviewer_answer_options") != list(DRIFT_ANSWER_OPTIONS):
            rejected_questions.append({"index": index, "reason": "answer_options_mismatch"})
        if not isinstance(question.get("observed_evidence_refs"), list) or not question.get("observed_evidence_refs"):
            rejected_questions.append({"index": index, "reason": "evidence_refs_missing"})
        if question.get("answer") == "NO_DRIFT_VISIBLE" or question.get("recommended_answer") == "NO_DRIFT_VISIBLE":
            rejected_questions.append({"index": index, "reason": "default_no_drift"})
        forbidden = _forbidden_truthy_claims(question, f"questions[{index}]")
        if forbidden:
            rejected_questions.append({"index": index, "reason": "forbidden_claim", "forbidden_claims": forbidden})

    if rejected_questions:
        rejection_reasons.append(_reason("DRIFT_QUESTION_CONTRACT_VIOLATION", "One or more drift questions violate the contract.", {"rejected_questions": rejected_questions}))

    result = {
        "drift_questions_check_result": DRIFT_QUESTIONS_CHECK_PASSED if not rejection_reasons else DRIFT_QUESTIONS_CHECK_FAILED_CLOSED,
        "validation_result": "passed" if not rejection_reasons else "failed_closed",
        "drift_groups": sorted(group for group in groups if isinstance(group, str)),
        "question_count": len(questions) if isinstance(questions, list) else 0,
        "rejection_reasons": rejection_reasons,
        "authority_boundary": dict(AUTHORITY_BOUNDARY_EXPECTATIONS),
        "no_drift_confirmed": False,
        "review_decision_created": False,
        "delivery_state_accepted": False,
    }
    assert_drift_questions_result_contract(result)
    return result


def assert_drift_questions_result_contract(result: dict[str, Any]) -> None:
    if result.get("authority_boundary") != AUTHORITY_BOUNDARY_EXPECTATIONS:
        raise ReviewerDriftQuestionsError("Drift question result boundary must remain false.")
    forbidden = _forbidden_truthy_claims(result, "drift_result")
    if forbidden:
        raise ReviewerDriftQuestionsError(f"Forbidden drift result claims: {forbidden}")


def _question(drift_type: str, text: str, evidence_refs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "drift_question_id": drift_type,
        "drift_type": drift_type,
        "question_text": text,
        "expected_reference": {"expected": drift_type},
        "observed_evidence_refs": evidence_refs,
        "reviewer_answer_options": list(DRIFT_ANSWER_OPTIONS),
        "unresolved_followup_prompt": "If unclear or drift is visible, describe the follow-up needed.",
    }


def _reason(code: str, message: str, details: dict[str, Any]) -> dict[str, Any]:
    return {"code": code, "message": message, "details": details}


def _forbidden_truthy_claims(value: Any, path: str) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if str(key) in FORBIDDEN_DRIFT_CLAIM_KEYS and _truthy_claim(child):
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
        return value.strip().lower() in {"true", "yes", "confirmed", "accepted", "created"}
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value != 0
    return False
