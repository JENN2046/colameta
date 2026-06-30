from __future__ import annotations

import copy
import unittest

from runner.audit_package_taskbook_binding import build_audit_package_taskbook_binding
from runner.drift_evidence_pack_builder import (
    DRIFT_EVIDENCE_PACK_FAILED_CLOSED,
    DRIFT_EVIDENCE_PACK_GENERATED,
    DriftEvidencePackBuilderError,
    assert_drift_evidence_pack_builder_result_contract,
    build_drift_evidence_pack,
    drift_evidence_pack_builder_inventory,
)
from runner.drift_evidence_schema import DRIFT_EVIDENCE_SCHEMA_CHECK_PASSED
from runner.review_feedback_schema import example_review_feedback
from runner.reviewer_handoff_generator import generate_reviewer_handoff_package
from runner.scope_evidence_pack import build_scope_evidence_pack


class DriftEvidencePackBuilderTests(unittest.TestCase):
    def scope_pack(self) -> dict:
        return build_scope_evidence_pack(
            scope_pack_id="scope-pack-example",
            version_taskbook_ref={"version_id": "stage_07_v1_13_drift_evidence_pack_builder_v1"},
            execution_envelope_ref={"envelope_id": "execution-envelope-example"},
            allowed_files=["runner/**", "tests/**"],
            forbidden_files=["PROJECT_MASTER_TASKBOOK.md", ".colameta/plan.json"],
            observed_touched_files=["runner/drift_evidence_pack_builder.py", "tests/test_drift_evidence_pack_builder.py"],
            observed_mutations=[{"path": "runner/drift_evidence_pack_builder.py", "mutation_type": "created"}],
            generated_files=[],
            ignored_runtime_files=[],
            known_gaps=[{"gap_id": "manual_reviewer_still_required"}],
            remaining_risks=[{"risk_id": "reviewer_must_decide_drift"}],
        )

    def audit_package(self) -> dict:
        return build_audit_package_taskbook_binding(
            audit_package_id="audit-package-example",
            version_taskbook_ref={"version_id": "stage_07_v1_13_drift_evidence_pack_builder_v1"},
            master_taskbook_hash="1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34",
            stage_taskbook_hash="05e6114a666942c0641c635905c2295feaa62b98bd9e7b5166babd662e015a41",
            execution_envelope_ref={"envelope_id": "execution-envelope-example"},
            run_preview_ref={"run_preview_id": "run-preview-example"},
            execution_receipt_refs=[{"receipt_id": "local-receipt-example"}],
            executor_report_ref={"executor_report_id": "executor-report-example"},
            execution_evidence_receipt_ref={"evidence_receipt_id": "execution-evidence-receipt-example"},
            validation_truth_summary_ref={"validation_truth_summary_id": "validation-summary-example"},
            scope_evidence_pack_ref={"scope_pack_id": "scope-pack-example"},
            validation_truth_statuses=["passed"],
            scope_result="in_scope",
            known_gaps=[{"gap_id": "manual_reviewer_still_required"}],
            remaining_risks=[{"risk_id": "reviewer_must_decide_drift"}],
        )

    def handoff_package(self) -> dict:
        result = generate_reviewer_handoff_package(
            {
                "reviewer_handoff_schema_ref": {"version_id": "stage_05_v5_1_reviewer_handoff_schema_v1"},
                "handoff_package_id": "handoff-package-example",
                "master_taskbook_ref": {
                    "path": "PROJECT_MASTER_TASKBOOK.md",
                    "sha256": "1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34",
                },
                "stage_taskbook_ref": {"path": "docs/taskbooks/stages/STAGE_05_REVIEWER_HANDOFF_PACKAGE.md"},
                "version_taskbook_ref": {"version_id": "stage_07_v1_13_drift_evidence_pack_builder_v1"},
                "stage_4_audit_package_ref": {"audit_package_id": "audit-package-example"},
                "execution_receipt_refs": [{"receipt_id": "local-receipt-example"}],
                "claim_summary": {"summary": "Evidence is ready for reviewer inspection."},
                "changed_files": [
                    {"path": "runner/drift_evidence_pack_builder.py"},
                    {"path": "tests/test_drift_evidence_pack_builder.py"},
                ],
                "validation_truth": [{"command": "pytest", "execution_status": "passed"}],
                "scope_evidence": [{"scope_result": "in_scope", "scope_pack_id": "scope-pack-example"}],
                "known_risks": [{"risk_id": "reviewer_must_decide_drift"}],
                "known_gaps": [{"gap_id": "manual_reviewer_still_required"}],
                "reviewer_questions": [{"question_id": "accept_or_fix", "text": "Choose a review decision."}],
                "generated_at": "2026-07-01T00:00:00+08:00",
            }
        )
        return result["reviewer_handoff_package"]

    def inputs(self) -> dict:
        return {
            "drift_evidence_pack_id": "drift-evidence-pack-example",
            "master_taskbook_ref": {
                "path": "PROJECT_MASTER_TASKBOOK.md",
                "sha256": "1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34",
            },
            "stage_taskbook_ref": {
                "stage_id": "stage_07_drift_evidence_and_correction",
                "path": "docs/taskbooks/stages/STAGE_07_DRIFT_EVIDENCE_AND_CORRECTION.md",
            },
            "version_taskbook_ref": {"version": "v1.13", "name": "Stage 7 Drift Evidence Pack Builder V1"},
            "audit_package": self.audit_package(),
            "scope_evidence_pack": self.scope_pack(),
            "reviewer_handoff_package": self.handoff_package(),
            "review_feedback": example_review_feedback(review_decision_value="PLAN_ADJUST"),
        }

    def test_builder_composes_reviewer_ready_pack_without_drift_decision(self) -> None:
        result = build_drift_evidence_pack(self.inputs())

        assert result["pack_builder_status"] == DRIFT_EVIDENCE_PACK_GENERATED
        assert result["schema_validation_result"]["drift_evidence_schema_check_result"] == DRIFT_EVIDENCE_SCHEMA_CHECK_PASSED
        pack = result["drift_evidence_pack"]
        assert pack["executor_drift_evidence"]["section_id"] == "executor_drift_evidence"
        assert pack["task_drift_evidence"]["section_id"] == "task_drift_evidence"
        assert pack["stage_drift_evidence"]["section_id"] == "stage_drift_evidence"
        assert pack["known_gaps"][0]["gap_id"] == "manual_reviewer_still_required"
        assert pack["remaining_risks"][0]["risk_id"] == "reviewer_must_decide_drift"
        assert pack["semantic_alignment_pass"] is False
        assert pack["no_drift_confirmed"] is False
        assert pack["semantic_drift_judgment"] is None
        assert result["review_decision_created"] is False
        assert result["gate_event_emitted"] is False
        assert result["plan_mutated"] is False

    def test_reviewer_questions_are_unanswered_and_plan_adjust_is_preview_only(self) -> None:
        result = build_drift_evidence_pack(self.inputs())
        pack = result["drift_evidence_pack"]

        assert all("answer" not in item and "recommended_answer" not in item for item in pack["master_goal_alignment_questions"])
        assert all("answer" not in item and "recommended_answer" not in item for item in pack["reviewer_drift_checklist"])
        assert any(item["stage_8_preview_required"] is True for item in pack["plan_adjustment_trigger_conditions"])
        for condition in pack["plan_adjustment_trigger_conditions"]:
            assert "plan_diff" not in condition
            assert "plan_patch" not in condition
            assert "apply_request" not in condition
            assert "taskbook_mutation" not in condition
            assert condition["plan_diff_created"] is False
            assert condition["plan_patch_created"] is False
            assert condition["apply_request_created"] is False
            assert condition["taskbook_mutation_created"] is False

    def test_incomplete_evidence_fails_closed_with_blocker_codes(self) -> None:
        result = build_drift_evidence_pack(
            {
                "drift_evidence_pack_id": "incomplete-pack",
                "master_taskbook_ref": {"path": "PROJECT_MASTER_TASKBOOK.md"},
                "stage_taskbook_ref": {"path": "docs/taskbooks/stages/STAGE_07_DRIFT_EVIDENCE_AND_CORRECTION.md"},
                "version_taskbook_ref": {"version": "v1.13"},
            }
        )

        assert result["pack_builder_status"] == DRIFT_EVIDENCE_PACK_FAILED_CLOSED
        blocker_codes = {item["code"] for item in result["failures_and_blockers"]}
        assert "EXECUTION_EVIDENCE_REF_MISSING" in blocker_codes
        assert "CHANGED_FILES_MISSING" in blocker_codes
        assert "VALIDATION_TRUTH_MISSING" in blocker_codes
        assert "SCOPE_EVIDENCE_MISSING" in blocker_codes
        assert "DRIFT_EVIDENCE_SCHEMA_VALIDATION_FAILED" in blocker_codes
        assert result["no_drift_confirmed"] is False
        assert result["semantic_alignment_pass"] is False

    def test_prefilled_reviewer_answer_fails_closed(self) -> None:
        inputs = self.inputs()
        inputs["master_goal_alignment_questions"] = [
            {
                "question_id": "project_final_goal_support",
                "question_text": "Does this still support the project final goal?",
                "target_ref": {"target": "project_final_goal"},
                "evidence_refs": [{"evidence_id": "handoff-package-example"}],
                "reviewer_answer_options": ["YES", "NO", "UNCLEAR", "NOT_APPLICABLE"],
                "unanswered_state": "UNANSWERED",
                "answer": "YES",
            }
        ]

        result = build_drift_evidence_pack(inputs)

        assert result["pack_builder_status"] == DRIFT_EVIDENCE_PACK_FAILED_CLOSED
        assert "MASTER_GOAL_ALIGNMENT_QUESTIONS_INVALID" in {item["code"] for item in result["failures_and_blockers"]}
        assert result["review_decision_created"] is False

    def test_plan_adjust_actionable_output_fails_closed_without_echoing_patch(self) -> None:
        inputs = self.inputs()
        inputs["plan_adjustment_trigger_conditions"] = [
            {
                "trigger_condition_id": "bad_plan_adjust_trigger",
                "condition_text": "Bad trigger tries to carry a plan diff.",
                "plan_diff": {"ops": [{"op": "replace", "path": "/versions/0"}]},
            }
        ]

        result = build_drift_evidence_pack(inputs)

        assert result["pack_builder_status"] == DRIFT_EVIDENCE_PACK_FAILED_CLOSED
        assert "FORBIDDEN_PLAN_ADJUST_ACTIONABLE_OUTPUT" in {item["code"] for item in result["failures_and_blockers"]}
        for condition in result["drift_evidence_pack"]["plan_adjustment_trigger_conditions"]:
            assert "plan_diff" not in condition

    def test_builder_inventory_and_result_contract_preserve_authority_boundary(self) -> None:
        inventory = drift_evidence_pack_builder_inventory()
        assert inventory["uses_drift_evidence_schema_validation"] is True
        assert all(value is False for value in inventory["authority_boundary"].values())

        result = build_drift_evidence_pack(self.inputs())
        mutated = copy.deepcopy(result)
        mutated["review_decision_created"] = True

        with self.assertRaises(DriftEvidencePackBuilderError) as raised:
            assert_drift_evidence_pack_builder_result_contract(mutated)

        assert raised.exception.error_code == "FORBIDDEN_DRIFT_EVIDENCE_PACK_BUILDER_RESULT_CLAIM"


if __name__ == "__main__":
    unittest.main()
