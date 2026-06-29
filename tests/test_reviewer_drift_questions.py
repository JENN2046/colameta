from __future__ import annotations

import copy
import unittest

from runner.reviewer_drift_questions import (
    DRIFT_QUESTIONS_CHECK_FAILED_CLOSED,
    DRIFT_QUESTIONS_CHECK_PASSED,
    ReviewerDriftQuestionsError,
    assert_drift_questions_result_contract,
    default_drift_questions,
    validate_drift_questions,
)


class ReviewerDriftQuestionsTests(unittest.TestCase):
    def questions(self) -> list[dict]:
        return default_drift_questions([{"evidence_id": "handoff-package-example"}])

    def test_default_drift_questions_cover_required_groups(self) -> None:
        result = validate_drift_questions(self.questions())

        assert result["drift_questions_check_result"] == DRIFT_QUESTIONS_CHECK_PASSED
        assert "authority_drift" in result["drift_groups"]
        assert result["no_drift_confirmed"] is False

    def test_missing_authority_drift_fails_closed(self) -> None:
        result = validate_drift_questions([q for q in self.questions() if q["drift_type"] != "authority_drift"])

        assert result["drift_questions_check_result"] == DRIFT_QUESTIONS_CHECK_FAILED_CLOSED

    def test_missing_unclear_option_fails_closed(self) -> None:
        questions = self.questions()
        questions[0]["reviewer_answer_options"] = ["NO_DRIFT_VISIBLE", "DRIFT_VISIBLE", "NOT_APPLICABLE"]

        result = validate_drift_questions(questions)

        assert result["drift_questions_check_result"] == DRIFT_QUESTIONS_CHECK_FAILED_CLOSED

    def test_default_no_drift_answer_fails_closed(self) -> None:
        questions = self.questions()
        questions[0]["answer"] = "NO_DRIFT_VISIBLE"

        result = validate_drift_questions(questions)

        assert result["drift_questions_check_result"] == DRIFT_QUESTIONS_CHECK_FAILED_CLOSED

    def test_missing_evidence_refs_fails_closed(self) -> None:
        questions = self.questions()
        questions[0]["observed_evidence_refs"] = []

        result = validate_drift_questions(questions)

        assert result["drift_questions_check_result"] == DRIFT_QUESTIONS_CHECK_FAILED_CLOSED

    def test_result_contract_rejects_delivery_state_accepted(self) -> None:
        result = validate_drift_questions(self.questions())
        mutated = copy.deepcopy(result)
        mutated["delivery_state_accepted"] = True

        with self.assertRaises(ReviewerDriftQuestionsError):
            assert_drift_questions_result_contract(mutated)


if __name__ == "__main__":
    unittest.main()
