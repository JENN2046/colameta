from __future__ import annotations

from typing import Any


REPORT_SURFACE_CHECK_PASSED = "reviewer_package_report_surface_check_passed"
REPORT_SURFACE_CHECK_FAILED_CLOSED = "reviewer_package_report_surface_check_failed_closed"
ALLOWED_REVIEW_DECISIONS = ("ACCEPT", "NEEDS_FIX", "PLAN_ADJUST", "ABORT")
REQUIRED_SECTIONS = (
    "package_identity",
    "binding_summary",
    "task_goal_summary",
    "claim_summary",
    "changed_files",
    "validation_truth",
    "scope_evidence",
    "alignment_questions",
    "drift_questions",
    "known_risks",
    "known_gaps",
    "allowed_review_decisions",
    "non_authority_notice",
)
REQUIRED_NOTICES = (
    "report_surface_is_not_review_decision",
    "report_surface_is_not_delivery_state_transition",
    "report_surface_is_not_commander_authorization",
    "report_surface_is_not_executor_authorization",
)
EMPTY_ALLOWED_SECTIONS = frozenset({"known_gaps"})
FORBIDDEN_SURFACE_CLAIM_KEYS = frozenset(
    {
        "highlighted_accept_as_recommended",
        "validation_pass_labelled_as_accepted",
        "reviewer_decision_created",
        "gate_event_emitted",
        "delivery_state_accepted",
        "review_accepted",
    }
)


def validate_reviewer_package_report_surface(surface: dict[str, Any]) -> dict[str, Any]:
    rejection_reasons: list[dict[str, Any]] = []
    if not isinstance(surface, dict):
        rejection_reasons.append(_reason("REPORT_SURFACE_INVALID", "Report surface must be an object.", {}))
        surface = {}

    missing_sections = [
        section
        for section in REQUIRED_SECTIONS
        if section not in surface or (section not in EMPTY_ALLOWED_SECTIONS and _empty(surface.get(section)))
    ]
    if missing_sections:
        rejection_reasons.append(_reason("REPORT_SURFACE_SECTION_MISSING", "Required report sections are missing.", {"missing_sections": missing_sections}))

    if surface.get("allowed_review_decisions") != list(ALLOWED_REVIEW_DECISIONS):
        rejection_reasons.append(_reason("DECISION_OPTIONS_NOT_VISIBLE_OR_EQUAL", "All review decisions must be visible and equal.", {}))

    notice = surface.get("non_authority_notice")
    missing_notices = [item for item in REQUIRED_NOTICES if not isinstance(notice, dict) or notice.get(item) is not True]
    if missing_notices:
        rejection_reasons.append(_reason("NON_AUTHORITY_NOTICE_MISSING", "Report surface is missing non-authority notices.", {"missing_notices": missing_notices}))

    forbidden = _forbidden_truthy_claims(surface, "surface")
    if forbidden:
        rejection_reasons.append(_reason("FORBIDDEN_REPORT_SURFACE_CLAIM", "Report surface contains forbidden authority claims.", {"forbidden_claims": forbidden}))

    return {
        "report_surface_check_result": REPORT_SURFACE_CHECK_PASSED if not rejection_reasons else REPORT_SURFACE_CHECK_FAILED_CLOSED,
        "validation_result": "passed" if not rejection_reasons else "failed_closed",
        "section_inventory": [section for section in REQUIRED_SECTIONS if section in surface],
        "rejection_reasons": rejection_reasons,
        "allowed_review_decisions": list(ALLOWED_REVIEW_DECISIONS),
        "reviewer_decision_created": False,
        "gate_event_emitted": False,
        "delivery_state_accepted": False,
    }


def example_report_surface() -> dict[str, Any]:
    return {
        "package_identity": {"handoff_package_id": "handoff-package-example"},
        "binding_summary": {"master_taskbook_ref": "PROJECT_MASTER_TASKBOOK.md"},
        "task_goal_summary": {"goal": "reviewer handoff"},
        "claim_summary": {"summary": "Evidence is presented for review."},
        "changed_files": [{"path": "runner/example.py"}],
        "validation_truth": [{"execution_status": "passed"}],
        "scope_evidence": [{"scope_result": "in_scope"}],
        "alignment_questions": [{"question_id": "project_final_goal_support"}],
        "drift_questions": [{"drift_question_id": "authority_drift"}],
        "known_risks": [{"risk_id": "review_required"}],
        "known_gaps": [],
        "allowed_review_decisions": list(ALLOWED_REVIEW_DECISIONS),
        "non_authority_notice": {key: True for key in REQUIRED_NOTICES},
    }


def _empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, (list, dict, str)):
        return len(value) == 0
    return False


def _reason(code: str, message: str, details: dict[str, Any]) -> dict[str, Any]:
    return {"code": code, "message": message, "details": details}


def _forbidden_truthy_claims(value: Any, path: str) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if str(key) in FORBIDDEN_SURFACE_CLAIM_KEYS and _truthy_claim(child):
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
        return value.strip().lower() in {"true", "yes", "accepted", "recommended", "created"}
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value != 0
    return False
