from __future__ import annotations

import copy
import unittest

from runner.reviewer_alignment_questions import (
    ALIGNMENT_QUESTIONS_CHECK_FAILED_CLOSED,
    ALIGNMENT_QUESTIONS_CHECK_PASSED,
    ReviewerAlignmentQuestionsError,
    assert_alignment_questions_result_contract,
    default_alignment_questions,
    validate_alignment_questions,
)


class ReviewerAlignmentQuestionsTests(unittest.TestCase):
    def questions(self) -> list[dict]:
        return default_alignment_questions(
            {"project_final_goal_alignment": {"target": "project_final_goal"}},
            [{"evidence_id": "handoff-package-example"}],
        )

    def test_default_questions_cover_required_groups_without_answers(self) -> None:
        result = validate_alignment_questions(self.questions())

        assert result["alignment_questions_check_result"] == ALIGNMENT_QUESTIONS_CHECK_PASSED
        assert "project_final_goal_alignment" in result["question_groups"]
        assert "risk_alignment" in result["question_groups"]
        assert result["alignment_confirmed"] is False
        assert result["delivery_state_accepted"] is False

    def test_missing_project_final_goal_question_fails_closed(self) -> None:
        questions = [q for q in self.questions() if q["question_group"] != "project_final_goal_alignment"]

        result = validate_alignment_questions(questions)

        assert result["alignment_questions_check_result"] == ALIGNMENT_QUESTIONS_CHECK_FAILED_CLOSED
        assert "REQUIRED_GROUP_MISSING" in {item["code"] for item in result["rejection_reasons"]}

    def test_missing_evidence_refs_fails_closed(self) -> None:
        questions = self.questions()
        questions[0]["evidence_refs"] = []

        result = validate_alignment_questions(questions)

        assert result["alignment_questions_check_result"] == ALIGNMENT_QUESTIONS_CHECK_FAILED_CLOSED

    def test_missing_unclear_option_fails_closed(self) -> None:
        questions = self.questions()
        questions[0]["reviewer_answer_options"] = ["YES", "NO", "NOT_APPLICABLE"]

        result = validate_alignment_questions(questions)

        assert result["alignment_questions_check_result"] == ALIGNMENT_QUESTIONS_CHECK_FAILED_CLOSED

    def test_prefilled_yes_fails_closed(self) -> None:
        questions = self.questions()
        questions[0]["answer"] = "YES"

        result = validate_alignment_questions(questions)

        assert result["alignment_questions_check_result"] == ALIGNMENT_QUESTIONS_CHECK_FAILED_CLOSED

    def test_accept_recommendation_fails_closed(self) -> None:
        questions = self.questions()
        questions[0]["accept_recommendation"] = True

        result = validate_alignment_questions(questions)

        assert result["alignment_questions_check_result"] == ALIGNMENT_QUESTIONS_CHECK_FAILED_CLOSED

    def test_result_contract_rejects_delivery_state_accepted(self) -> None:
        result = validate_alignment_questions(self.questions())
        mutated = copy.deepcopy(result)
        mutated["delivery_state_accepted"] = True

        with self.assertRaises(ReviewerAlignmentQuestionsError):
            assert_alignment_questions_result_contract(mutated)


if __name__ == "__main__":
    unittest.main()
