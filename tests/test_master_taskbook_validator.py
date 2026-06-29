from __future__ import annotations

import copy
from pathlib import Path
import unittest

from runner.master_taskbook_reader import read_master_taskbook
from runner.master_taskbook_registry import sha256_file
from runner.master_taskbook_validator import (
    FIELD_RESULT_EMPTY,
    FIELD_RESULT_KNOWN_UNKNOWN,
    FIELD_RESULT_MALFORMED,
    FIELD_RESULT_MISSING,
    FIELD_RESULT_PRESENT,
    FORBIDDEN_VALIDATOR_RESULT_FIELDS,
    VALIDATION_RESULT_FAILED_CLOSED,
    VALIDATION_RESULT_FAILED_REQUIRED_FIELDS,
    VALIDATION_RESULT_KNOWN_UNKNOWN,
    VALIDATION_RESULT_PASSED,
    validate_master_taskbook_required_fields,
)


class MasterTaskbookValidatorTests(unittest.TestCase):
    def reader_result(self, raw_content: str) -> dict:
        import hashlib

        return {
            "read_status": "read_ok",
            "raw_content": raw_content,
            "raw_content_sha256": hashlib.sha256(raw_content.encode("utf-8")).hexdigest(),
            "observed_git_head": "a" * 40,
            "registry_review_status_boundary": "freeze_candidate_confirmed_for_exact_hash",
            "failure_reason_or_none": None,
        }

    def complete_content(self) -> str:
        return "\n".join(
            [
                "project_final_goal:",
                "  goal: keep the project anchored",
                "mvp_stage_scope: Stage 0-6 Thin Governed Loop",
                "master_stage_taskbook_architecture: Master / Stage / Version",
                "authority_boundaries:",
                "  planning: Commander",
                "delivery_state_gate_boundary:",
                "  owner: Delivery State Gate",
                "review_decision_mapping_boundary: reviewers record review decisions first",
                "evidence_package_minimum: evidence not approval",
                "stage_0_6_thin_governed_loop: one thin governed loop",
                "forbidden_claims_or_boundary_law: no authority laundering",
                "versioning_policy:",
                "  project_final_goal_change: requires commander hard gate",
            ]
        )

    def check_by_field(self, result: dict) -> dict[str, dict]:
        return {item["field"]: item for item in result["required_field_check_table"]}

    def test_required_fields_present_passes_without_authority_fields(self) -> None:
        result = validate_master_taskbook_required_fields(self.reader_result(self.complete_content()))

        assert result["validation_result"] == VALIDATION_RESULT_PASSED
        assert result["fail_closed_result"] == "pass"
        assert not result["required_field_violations"]
        assert not (set(result) & FORBIDDEN_VALIDATOR_RESULT_FIELDS)
        assert all(item["result"] == FIELD_RESULT_PRESENT for item in result["required_field_check_table"])

    def test_missing_project_final_goal_fails_closed(self) -> None:
        raw_content = self.complete_content().replace("project_final_goal:\n  goal: keep the project anchored\n", "")

        result = validate_master_taskbook_required_fields(self.reader_result(raw_content))

        checks = self.check_by_field(result)
        assert result["validation_result"] == VALIDATION_RESULT_FAILED_CLOSED
        assert result["fail_closed_result"] == "fail_closed"
        assert checks["project_final_goal"]["result"] == FIELD_RESULT_MISSING
        assert "project_final_goal" in result["fail_closed_violations"]

    def test_empty_fail_closed_field_fails_closed(self) -> None:
        raw_content = self.complete_content().replace(
            "authority_boundaries:\n  planning: Commander\n",
            "authority_boundaries:\n",
        )

        result = validate_master_taskbook_required_fields(self.reader_result(raw_content))

        checks = self.check_by_field(result)
        assert result["validation_result"] == VALIDATION_RESULT_FAILED_CLOSED
        assert checks["authority_boundaries"]["result"] == FIELD_RESULT_EMPTY
        assert checks["authority_boundaries"]["failure_reason_or_none"] == "field_value_empty"

    def test_malformed_fail_closed_field_fails_closed(self) -> None:
        raw_content = self.complete_content().replace(
            "delivery_state_gate_boundary:\n  owner: Delivery State Gate\n",
            "delivery_state_gate_boundary: [\n",
        )

        result = validate_master_taskbook_required_fields(self.reader_result(raw_content))

        checks = self.check_by_field(result)
        assert result["validation_result"] == VALIDATION_RESULT_FAILED_CLOSED
        assert checks["delivery_state_gate_boundary"]["result"] == FIELD_RESULT_MALFORMED

    def test_missing_non_fail_closed_field_fails_required_fields_without_closing_fail_gate(self) -> None:
        raw_content = self.complete_content().replace(
            "versioning_policy:\n  project_final_goal_change: requires commander hard gate",
            "",
        )

        result = validate_master_taskbook_required_fields(self.reader_result(raw_content))

        checks = self.check_by_field(result)
        assert result["validation_result"] == VALIDATION_RESULT_FAILED_REQUIRED_FIELDS
        assert result["fail_closed_result"] == "pass"
        assert checks["versioning_policy"]["result"] == FIELD_RESULT_MISSING
        assert not result["fail_closed_violations"]

    def test_missing_reader_result_returns_known_unknown_without_rereading_master(self) -> None:
        result = validate_master_taskbook_required_fields(None)

        assert result["validation_result"] == VALIDATION_RESULT_KNOWN_UNKNOWN
        assert result["fail_closed_result"] == "fail_closed"
        assert result["failure_reason_or_none"] == "reader_result_missing"
        assert all(item["result"] == FIELD_RESULT_KNOWN_UNKNOWN for item in result["required_field_check_table"])

    def test_reader_result_hash_mismatch_returns_known_unknown(self) -> None:
        reader_result = self.reader_result(self.complete_content())
        reader_result["raw_content_sha256"] = "0" * 64

        result = validate_master_taskbook_required_fields(reader_result)

        assert result["validation_result"] == VALIDATION_RESULT_KNOWN_UNKNOWN
        assert result["failure_reason_or_none"] == "reader_result_hash_mismatch"
        assert result["reader_result_input"]["integrity_details"]["expected_raw_content_sha256"] == "0" * 64

    def test_current_master_reader_result_validates_required_fields_without_mutation(self) -> None:
        project = Path(__file__).resolve().parents[1]
        master = project / "PROJECT_MASTER_TASKBOOK.md"
        registry = project / ".colameta" / "taskbooks" / "master_taskbook_registry.json"
        master_before = sha256_file(master)
        registry_before = sha256_file(registry)

        reader_result = read_master_taskbook(project, observed_git_head="0" * 40)
        result = validate_master_taskbook_required_fields(reader_result)

        assert result["validation_result"] == VALIDATION_RESULT_PASSED
        assert result["reader_result_input"]["raw_content_sha256"] == master_before
        assert sha256_file(master) == master_before
        assert sha256_file(registry) == registry_before

    def test_validator_does_not_mutate_reader_result(self) -> None:
        reader_result = self.reader_result(self.complete_content())
        before = copy.deepcopy(reader_result)

        validate_master_taskbook_required_fields(reader_result)

        assert reader_result == before


if __name__ == "__main__":
    unittest.main()
