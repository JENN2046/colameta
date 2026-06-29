from __future__ import annotations

from typing import Any


ALIGNMENT_QUESTIONS_CHECK_PASSED = "alignment_questions_check_passed"
ALIGNMENT_QUESTIONS_CHECK_FAILED_CLOSED = "alignment_questions_check_failed_closed"
REVIEWER_ANSWER_OPTIONS = ("YES", "NO", "UNCLEAR", "NOT_APPLICABLE")
REQUIRED_QUESTION_GROUPS = (
    "project_final_goal_alignment",
    "stage_goal_alignment",
    "version_task_goal_alignment",
    "scope_alignment",
    "evidence_alignment",
    "risk_alignment",
)
REQUIRED_QUESTION_FIELDS = (
    "question_id",
    "question_text",
    "target_ref",
    "evidence_refs",
    "reviewer_answer_options",
    "unanswered_state",
)
FORBIDDEN_ALIGNMENT_CLAIM_KEYS = frozenset(
    {
        "prefilled_yes_answer",
        "accept_recommendation",
        "alignment_confirmed",
        "generator_scored_alignment_as_final",
        "reviewer_acceptance",
        "delivery_state_accepted",
        "review_accepted",
    }
)
AUTHORITY_BOUNDARY_EXPECTATIONS = {
    "alignment_questions_result_is_authority": False,
    "alignment_questions_answer_for_reviewer": False,
    "alignment_questions_recommend_accept": False,
    "alignment_questions_write_delivery_state": False,
    "creates_review_decision": False,
    "emits_gate_event": False,
}


class ReviewerAlignmentQuestionsError(ValueError):
    def __init__(self, error_code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.details = details or {}


def default_alignment_questions(target_refs: dict[str, Any], evidence_refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        _question("project_final_goal_alignment", "project_final_goal_support", "Does the evidence support the project final goal rather than only local task completion?", target_refs, evidence_refs),
        _question("project_final_goal_alignment", "project_final_goal_unchanged", "Did the work avoid changing the project final goal without Commander authorization?", target_refs, evidence_refs),
        _question("stage_goal_alignment", "stage_goal_support", "Does the evidence support the Stage 5 goal of reviewer handoff rather than review replacement?", target_refs, evidence_refs),
        _question("version_task_goal_alignment", "version_task_goal_support", "Does the package satisfy the exact Version task goal?", target_refs, evidence_refs),
        _question("scope_alignment", "scope_alignment_visible", "Were changed files and touched artifacts within declared scope?", target_refs, evidence_refs),
        _question("evidence_alignment", "evidence_ref_support", "Does each claim have a supporting evidence reference?", target_refs, evidence_refs),
        _question("risk_alignment", "risk_gap_visibility", "Are known risks and known gaps visible enough for review?", target_refs, evidence_refs),
    ]


def validate_alignment_questions(questions: list[dict[str, Any]]) -> dict[str, Any]:
    rejected_questions: list[dict[str, Any]] = []
    rejection_reasons: list[dict[str, Any]] = []
    groups = {item.get("question_group") for item in questions if isinstance(item, dict)}

    if not isinstance(questions, list) or not questions:
        rejection_reasons.append(_reason("QUESTION_LIST_MISSING", "Alignment questions must be a non-empty list.", {}))
        groups = set()

    missing_groups = [group for group in REQUIRED_QUESTION_GROUPS if group not in groups]
    if missing_groups:
        rejection_reasons.append(_reason("REQUIRED_GROUP_MISSING", "Alignment question groups are missing.", {"missing_groups": missing_groups}))

    for index, question in enumerate(questions if isinstance(questions, list) else []):
        if not isinstance(question, dict):
            rejected_questions.append({"index": index, "reason": "not_object"})
            continue
        missing_fields = [field for field in REQUIRED_QUESTION_FIELDS if field not in question]
        if missing_fields:
            rejected_questions.append({"index": index, "reason": "missing_fields", "missing_fields": missing_fields})
        if question.get("reviewer_answer_options") != list(REVIEWER_ANSWER_OPTIONS):
            rejected_questions.append({"index": index, "reason": "answer_options_mismatch"})
        if not isinstance(question.get("evidence_refs"), list) or not question.get("evidence_refs"):
            rejected_questions.append({"index": index, "reason": "evidence_refs_missing"})
        if question.get("answer") in {"YES", "ACCEPT"} or question.get("recommended_answer") in {"YES", "ACCEPT"}:
            rejected_questions.append({"index": index, "reason": "prefilled_or_recommended_acceptance"})
        forbidden_claims = _forbidden_truthy_claims(question, f"questions[{index}]")
        if forbidden_claims:
            rejected_questions.append({"index": index, "reason": "forbidden_claim", "forbidden_claims": _safe_forbidden_claims(forbidden_claims)})

    if rejected_questions:
        rejection_reasons.append(
            _reason("QUESTION_CONTRACT_VIOLATION", "One or more alignment questions violate the question contract.", {"rejected_questions": rejected_questions})
        )

    result = {
        "alignment_questions_check_result": ALIGNMENT_QUESTIONS_CHECK_PASSED if not rejection_reasons else ALIGNMENT_QUESTIONS_CHECK_FAILED_CLOSED,
        "validation_result": "passed" if not rejection_reasons else "failed_closed",
        "question_count": len(questions) if isinstance(questions, list) else 0,
        "question_groups": sorted(group for group in groups if isinstance(group, str)),
        "rejection_reasons": rejection_reasons,
        "authority_boundary": dict(AUTHORITY_BOUNDARY_EXPECTATIONS),
        "alignment_confirmed": False,
        "reviewer_acceptance": False,
        "delivery_state_accepted": False,
        "creates_review_decision": False,
        "emits_gate_event": False,
    }
    assert_alignment_questions_result_contract(result)
    return result


def assert_alignment_questions_result_contract(result: dict[str, Any]) -> None:
    if result.get("authority_boundary") != AUTHORITY_BOUNDARY_EXPECTATIONS:
        raise ReviewerAlignmentQuestionsError("FORBIDDEN_ALIGNMENT_RESULT_AUTHORITY_CLAIM", "Alignment result boundary must remain false.")
    forbidden_claims = _forbidden_truthy_claims(result, "alignment_result")
    if forbidden_claims:
        raise ReviewerAlignmentQuestionsError(
            "FORBIDDEN_ALIGNMENT_RESULT_CLAIM",
            "Alignment question result contains forbidden claims.",
            details={"forbidden_claims": _safe_forbidden_claims(forbidden_claims)},
        )


def _question(group: str, question_id: str, text: str, target_refs: dict[str, Any], evidence_refs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "question_group": group,
        "question_id": question_id,
        "question_text": text,
        "target_ref": target_refs.get(group, target_refs),
        "evidence_refs": evidence_refs,
        "reviewer_answer_options": list(REVIEWER_ANSWER_OPTIONS),
        "unanswered_state": "UNANSWERED",
    }


def _reason(code: str, message: str, details: dict[str, Any]) -> dict[str, Any]:
    return {"code": code, "message": message, "details": details}


def _forbidden_truthy_claims(value: Any, path: str = "questions") -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if str(key) in FORBIDDEN_ALIGNMENT_CLAIM_KEYS and _truthy_claim(child):
                claims.append({"path": child_path, "key": str(key)})
            claims.extend(_forbidden_truthy_claims(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            claims.extend(_forbidden_truthy_claims(child, f"{path}[{index}]"))
    return claims


def _safe_forbidden_claims(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"path": item.get("path"), "key": item.get("key")} for item in claims]


def _truthy_claim(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "accepted", "accept", "confirmed"}
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value != 0
    return False
