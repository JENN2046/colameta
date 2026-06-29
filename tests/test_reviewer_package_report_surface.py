from __future__ import annotations

import unittest

from runner.reviewer_package_report_surface import (
    REPORT_SURFACE_CHECK_FAILED_CLOSED,
    REPORT_SURFACE_CHECK_PASSED,
    example_report_surface,
    validate_reviewer_package_report_surface,
)


class ReviewerPackageReportSurfaceTests(unittest.TestCase):
    def test_example_surface_passes_without_decision(self) -> None:
        result = validate_reviewer_package_report_surface(example_report_surface())

        assert result["report_surface_check_result"] == REPORT_SURFACE_CHECK_PASSED
        assert result["reviewer_decision_created"] is False
        assert result["delivery_state_accepted"] is False

    def test_missing_binding_summary_fails_closed(self) -> None:
        surface = example_report_surface()
        del surface["binding_summary"]

        result = validate_reviewer_package_report_surface(surface)

        assert result["report_surface_check_result"] == REPORT_SURFACE_CHECK_FAILED_CLOSED

    def test_hidden_needs_fix_fails_closed(self) -> None:
        surface = example_report_surface()
        surface["allowed_review_decisions"] = ["ACCEPT", "ABORT"]

        result = validate_reviewer_package_report_surface(surface)

        assert result["report_surface_check_result"] == REPORT_SURFACE_CHECK_FAILED_CLOSED

    def test_missing_non_authority_notice_fails_closed(self) -> None:
        surface = example_report_surface()
        surface["non_authority_notice"] = {}

        result = validate_reviewer_package_report_surface(surface)

        assert result["report_surface_check_result"] == REPORT_SURFACE_CHECK_FAILED_CLOSED

    def test_accept_recommendation_fails_closed(self) -> None:
        surface = example_report_surface()
        surface["highlighted_accept_as_recommended"] = True

        result = validate_reviewer_package_report_surface(surface)

        assert result["report_surface_check_result"] == REPORT_SURFACE_CHECK_FAILED_CLOSED

    def test_delivery_state_claim_fails_closed(self) -> None:
        surface = example_report_surface()
        surface["delivery_state_accepted"] = True

        result = validate_reviewer_package_report_surface(surface)

        assert result["report_surface_check_result"] == REPORT_SURFACE_CHECK_FAILED_CLOSED


if __name__ == "__main__":
    unittest.main()
