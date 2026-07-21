from __future__ import annotations

import copy
import unittest

from runner.validation_truth import (
    AUTHORITY_BOUNDARY_EXPECTATIONS,
    VALIDATION_TRUTH_CHECK_FAILED_CLOSED,
    VALIDATION_TRUTH_CHECK_PASSED,
    ValidationTruthError,
    assert_validation_truth_result_contract,
    evidence_record_sha256,
    validate_evidence_provenance,
    validate_validation_truth,
)


class ValidationTruthTests(unittest.TestCase):
    def validation_truth(self, execution_status: str = "passed") -> dict:
        return {
            "validation_truth_id": f"validation-truth-{execution_status}",
            "validation_command": ".venv/bin/python -m unittest tests.test_example",
            "command_source_ref": {"source": "version_taskbook.acceptance_commands"},
            "execution_status": execution_status,
            "exit_code": 0 if execution_status == "passed" else 1 if execution_status == "failed" else None,
            "output_summary": "Ran 1 test ... OK" if execution_status == "passed" else "",
            "evidence_ref": {"evidence_id": "example-evidence"},
            "failure_reason": "assertion failed" if execution_status == "failed" else "",
            "blocker_reason": "authorization missing" if execution_status in {"blocked", "not_run"} else "",
            "known_gaps": [{"gap_id": "not_checked"}] if execution_status == "unvalidated" else [],
            "authority_boundary": dict(AUTHORITY_BOUNDARY_EXPECTATIONS),
        }

    def attach_provenance(
        self,
        truth: dict,
        *,
        subject_path: str = "$",
        claimed_subject: str = "validation",
        claimed_completed: bool = True,
    ) -> None:
        truth["evidence_provenance"] = {
            "schema_version": "evidence_provenance.v1",
            "entries": [
                {
                    "subject_path": subject_path,
                    "evidence_kind": "observed",
                    "binding": {
                        "record_id": truth["validation_truth_id"],
                        "record_schema_version": "validation_truth.v1",
                        "subject_path": subject_path,
                        "content_sha256": evidence_record_sha256(truth),
                    },
                    "claimed_evidence_subject": claimed_subject,
                    "claimed_subject_requires_execution": True,
                    "claimed_subject_operation_completed": claimed_completed,
                    "claimed_execution_performed": True,
                    "claimed_eligible_for_acceptance": True,
                }
            ],
        }

    def test_passed_with_command_evidence_passes(self) -> None:
        result = validate_validation_truth(self.validation_truth("passed"))

        assert result["validation_truth_check_result"] == VALIDATION_TRUTH_CHECK_PASSED
        assert result["execution_status"] == "passed"
        assert result["truth_boundary"]["runtime_label_alone_as_truth"] is False
        assert result["delivery_state_accepted"] is False
        assert result["evidence_provenance"]["provenance_status"] == "legacy_unclassified"

    def test_observed_validation_provenance_is_validator_eligible(self) -> None:
        truth = self.validation_truth("passed")
        self.attach_provenance(truth)

        result = validate_validation_truth(truth)

        assert result["validation_truth_check_result"] == VALIDATION_TRUTH_CHECK_PASSED
        assert result["evidence_provenance"]["eligible_for_acceptance"] is True
        assert result["evidence_provenance"]["entries"][0]["evidence_subject"] == "validation"

    def test_non_string_evidence_kind_fails_closed_without_raising(self) -> None:
        for evidence_kind in ({"kind": "observed"}, ["observed"], 1, None):
            with self.subTest(evidence_kind=evidence_kind):
                truth = self.validation_truth("passed")
                self.attach_provenance(truth)
                truth["evidence_provenance"]["entries"][0]["evidence_kind"] = evidence_kind

                result = validate_validation_truth(truth)

                assert result["validation_truth_check_result"] == VALIDATION_TRUTH_CHECK_FAILED_CLOSED
                assert result["evidence_provenance"]["provenance_status"] == "failed_closed"
                assert result["evidence_provenance"]["eligible_for_acceptance"] is False
                assert "EVIDENCE_PROVENANCE_KIND_INVALID" in {
                    reason["code"] for reason in result["rejection_reasons"]
                }

    def test_versioned_provenance_must_cover_every_validator_owned_subject(self) -> None:
        observation = {"observation_id": "obs-coverage", "schema_version": "observation.v1"}
        observation["evidence_provenance"] = {
            "schema_version": "evidence_provenance.v1",
            "entries": [
                {
                    "subject_path": "$.first",
                    "evidence_kind": "observed",
                    "binding": {
                        "record_id": "obs-coverage",
                        "record_schema_version": "observation.v1",
                        "subject_path": "$.first",
                        "content_sha256": evidence_record_sha256(observation),
                    },
                }
            ],
        }

        result = validate_evidence_provenance(
            observation,
            record_id="obs-coverage",
            record_schema_version="observation.v1",
            subject_specs={
                "$.first": {
                    "evidence_subject": "read_only_observation",
                    "subject_operation_completed": True,
                },
                "$.second": {
                    "evidence_subject": "read_only_observation",
                    "subject_operation_completed": True,
                },
            },
            base_valid=True,
        )

        assert result["projection"]["provenance_status"] == "failed_closed"
        assert result["projection"]["eligible_for_acceptance"] is False
        coverage = next(
            reason
            for reason in result["rejection_reasons"]
            if reason["code"] == "EVIDENCE_PROVENANCE_SUBJECT_COVERAGE_INCOMPLETE"
        )
        assert coverage["details"]["missing_subject_paths"] == ["$.second"]

    def test_observed_read_only_subject_is_eligible_without_execution(self) -> None:
        observation = {"observation_id": "obs-1", "schema_version": "observation.v1"}
        observation["evidence_provenance"] = {
            "schema_version": "evidence_provenance.v1",
            "entries": [
                {
                    "subject_path": "$",
                    "evidence_kind": "observed",
                    "binding": {
                        "record_id": "obs-1",
                        "record_schema_version": "observation.v1",
                        "subject_path": "$",
                        "content_sha256": evidence_record_sha256(observation),
                    },
                    "claimed_evidence_subject": "read_only_observation",
                    "claimed_subject_requires_execution": False,
                    "claimed_subject_operation_completed": True,
                    "claimed_execution_performed": False,
                    "claimed_eligible_for_acceptance": True,
                }
            ],
        }

        result = validate_evidence_provenance(
            observation,
            record_id="obs-1",
            record_schema_version="observation.v1",
            subject_specs={
                "$": {
                    "evidence_subject": "read_only_observation",
                    "subject_operation_completed": True,
                }
            },
            base_valid=True,
        )

        assert result["rejection_reasons"] == []
        entry = result["projection"]["entries"][0]
        assert entry["subject_requires_execution"] is False
        assert entry["execution_performed"] is False
        assert entry["eligible_for_acceptance"] is True

    def test_non_observed_evidence_fails_closed_even_when_claims_are_truthful(self) -> None:
        for evidence_kind in ("draft", "simulated", "placeholder"):
            with self.subTest(evidence_kind=evidence_kind):
                observation = {
                    "observation_id": "obs-incomplete",
                    "schema_version": "observation.v1",
                }
                observation["evidence_provenance"] = {
                    "schema_version": "evidence_provenance.v1",
                    "entries": [
                        {
                            "subject_path": "$",
                            "evidence_kind": evidence_kind,
                            "binding": {
                                "record_id": "obs-incomplete",
                                "record_schema_version": "observation.v1",
                                "subject_path": "$",
                                "content_sha256": evidence_record_sha256(observation),
                            },
                            "claimed_evidence_subject": "read_only_observation",
                            "claimed_subject_requires_execution": False,
                            "claimed_subject_operation_completed": False,
                            "claimed_execution_performed": False,
                            "claimed_eligible_for_acceptance": False,
                        }
                    ],
                }

                result = validate_evidence_provenance(
                    observation,
                    record_id="obs-incomplete",
                    record_schema_version="observation.v1",
                    subject_specs={
                        "$": {
                            "evidence_subject": "read_only_observation",
                            "subject_operation_completed": False,
                        }
                    },
                    base_valid=True,
                )

                assert result["projection"]["provenance_status"] == "failed_closed"
                assert result["projection"]["eligible_for_acceptance"] is False
                assert "EVIDENCE_PROVENANCE_NON_OBSERVED_INELIGIBLE" in {
                    reason["code"] for reason in result["rejection_reasons"]
                }

    def test_validation_provenance_downgrade_path_and_completion_fail_closed(self) -> None:
        downgrade = self.validation_truth("passed")
        self.attach_provenance(downgrade, claimed_subject="read_only_observation")
        downgrade_result = validate_validation_truth(downgrade)

        path = self.validation_truth("passed")
        self.attach_provenance(path, subject_path="$.evidence_ref")
        path_result = validate_validation_truth(path)

        completion = self.validation_truth("passed")
        self.attach_provenance(completion, claimed_completed=False)
        completion_result = validate_validation_truth(completion)

        assert "EVIDENCE_PROVENANCE_SUBJECT_DOWNGRADE" in {
            item["code"] for item in downgrade_result["rejection_reasons"]
        }
        assert "EVIDENCE_PROVENANCE_PATH_MISMATCH" in {
            item["code"] for item in path_result["rejection_reasons"]
        }
        assert "EVIDENCE_PROVENANCE_COMPLETION_MISMATCH" in {
            item["code"] for item in completion_result["rejection_reasons"]
        }

    def test_noncanonical_provenance_content_fails_closed_instead_of_raising(self) -> None:
        observation = {
            "observation_id": "obs-1",
            "schema_version": "observation.v1",
            "noncanonical": {"set-value"},
            "evidence_provenance": {
                "schema_version": "evidence_provenance.v1",
                "entries": [
                    {
                        "subject_path": "$",
                        "evidence_kind": "observed",
                        "binding": {
                            "record_id": "obs-1",
                            "record_schema_version": "observation.v1",
                            "subject_path": "$",
                            "content_sha256": "0" * 64,
                        },
                    }
                ],
            },
        }

        result = validate_evidence_provenance(
            observation,
            record_id="obs-1",
            record_schema_version="observation.v1",
            subject_specs={
                "$": {
                    "evidence_subject": "read_only_observation",
                    "subject_operation_completed": True,
                }
            },
            base_valid=True,
        )

        assert result["projection"]["provenance_status"] == "failed_closed"
        assert "EVIDENCE_PROVENANCE_CONTENT_NOT_CANONICAL" in {
            item["code"] for item in result["rejection_reasons"]
        }

    def test_failed_with_failure_reason_passes_without_summarizing_passed(self) -> None:
        result = validate_validation_truth(self.validation_truth("failed"))

        assert result["validation_truth_check_result"] == VALIDATION_TRUTH_CHECK_PASSED
        assert result["execution_status"] == "failed"

    def test_blocked_with_blocker_reason_passes(self) -> None:
        result = validate_validation_truth(self.validation_truth("blocked"))

        assert result["validation_truth_check_result"] == VALIDATION_TRUTH_CHECK_PASSED
        assert result["execution_status"] == "blocked"

    def test_not_run_with_blocker_reason_passes(self) -> None:
        result = validate_validation_truth(self.validation_truth("not_run"))

        assert result["validation_truth_check_result"] == VALIDATION_TRUTH_CHECK_PASSED
        assert result["execution_status"] == "not_run"

    def test_unvalidated_with_known_gap_passes(self) -> None:
        result = validate_validation_truth(self.validation_truth("unvalidated"))

        assert result["validation_truth_check_result"] == VALIDATION_TRUTH_CHECK_PASSED
        assert result["execution_status"] == "unvalidated"

    def test_failed_summarized_as_passed_fails_closed(self) -> None:
        truth = self.validation_truth("failed")
        truth["summary_status"] = "passed"

        result = validate_validation_truth(truth)

        assert result["validation_truth_check_result"] == VALIDATION_TRUTH_CHECK_FAILED_CLOSED
        assert "FAILED_SUMMARIZED_AS_PASSED" in {item["code"] for item in result["rejection_reasons"]}

    def test_not_run_summarized_as_passed_fails_closed(self) -> None:
        truth = self.validation_truth("not_run")
        truth["summary_status"] = "passed"

        result = validate_validation_truth(truth)

        assert result["validation_truth_check_result"] == VALIDATION_TRUTH_CHECK_FAILED_CLOSED
        assert "NOT_RUN_SUMMARIZED_AS_PASSED" in {item["code"] for item in result["rejection_reasons"]}

    def test_passed_without_evidence_ref_fails_closed(self) -> None:
        truth = self.validation_truth("passed")
        truth["evidence_ref"] = {}

        result = validate_validation_truth(truth)

        assert result["validation_truth_check_result"] == VALIDATION_TRUTH_CHECK_FAILED_CLOSED
        assert "PASSED_WITHOUT_EVIDENCE_REF" in {item["code"] for item in result["rejection_reasons"]}

    def test_runtime_passed_label_alone_fails_closed(self) -> None:
        truth = self.validation_truth("passed")
        truth["runtime_label"] = "PASSED"
        truth["evidence_ref"] = {}
        truth["command_source_ref"] = {}

        result = validate_validation_truth(truth)

        assert result["validation_truth_check_result"] == VALIDATION_TRUTH_CHECK_FAILED_CLOSED
        assert "RUNTIME_LABEL_ALONE_AS_TRUTH" in {item["code"] for item in result["rejection_reasons"]}

    def test_delivery_state_claim_fails_closed(self) -> None:
        truth = self.validation_truth("passed")
        truth["delivery_state_accepted"] = True

        result = validate_validation_truth(truth)

        assert result["validation_truth_check_result"] == VALIDATION_TRUTH_CHECK_FAILED_CLOSED
        assert "FORBIDDEN_VALIDATION_TRUTH_AUTHORITY_CLAIM" in {item["code"] for item in result["rejection_reasons"]}

    def test_result_contract_rejects_delivery_state_accepted(self) -> None:
        result = validate_validation_truth(self.validation_truth("passed"))
        mutated = copy.deepcopy(result)
        mutated["delivery_state_accepted"] = True

        with self.assertRaises(ValidationTruthError) as raised:
            assert_validation_truth_result_contract(mutated)

        assert raised.exception.error_code == "FORBIDDEN_VALIDATION_TRUTH_RESULT_CLAIM"

    def test_non_object_truth_fails_closed(self) -> None:
        result = validate_validation_truth("not truth")  # type: ignore[arg-type]

        assert result["validation_truth_check_result"] == VALIDATION_TRUTH_CHECK_FAILED_CLOSED
        assert result["recognized_fields"] == []
        assert result["rejection_reasons"][0]["code"] == "VALIDATION_TRUTH_INVALID"


if __name__ == "__main__":
    unittest.main()
