from __future__ import annotations

import copy
from pathlib import Path
import unittest

from runner.master_taskbook_registry import sha256_file
from runner.stage_taskbook_validator import (
    FIELD_RESULT_KNOWN_UNKNOWN,
    FIELD_RESULT_MALFORMED,
    FIELD_RESULT_MISSING,
    FIELD_RESULT_PRESENT,
    FORBIDDEN_VALIDATOR_RESULT_FIELDS,
    VALIDATION_RESULT_FAILED_CLOSED,
    VALIDATION_RESULT_KNOWN_UNKNOWN,
    VALIDATION_RESULT_PASSED,
    extract_yaml_blocks,
    load_stage_taskbook_schema,
    validate_stage_taskbook,
)


MASTER_SHA = "1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34"
OTHER_SHA = "2" * 64


class StageTaskbookValidatorTests(unittest.TestCase):
    def schema(self) -> dict:
        return load_stage_taskbook_schema(Path(__file__).resolve().parents[1])

    def complete_content(self, master_hash: str = MASTER_SHA) -> str:
        return "\n".join(
            [
                "# Stage 9 Taskbook: Example",
                '```yaml id="stage-taskbook-summary"',
                "stage_taskbook:",
                "  stage_id: stage_09_example",
                "  stage_name: Example Stage",
                "  chinese_name: 示例阶段",
                "  status: discussion_draft",
                "  authority_status: planning_reference_only",
                "```",
                "## 1. Master Binding",
                '```yaml id="master-binding"',
                "master_binding:",
                "  master_taskbook_path: PROJECT_MASTER_TASKBOOK.md",
                "  master_taskbook_ref:",
                "    path: PROJECT_MASTER_TASKBOOK.md",
                f"    raw_snapshot_sha256: {master_hash}",
                "  supports_project_goal: true",
                "```",
                "## 2. Stage Purpose",
                "This stage defines bounded planning artifacts.",
                '```yaml id="entry-criteria"',
                "entry_criteria:",
                "  required:",
                "    - master reference exists",
                "```",
                '```yaml id="exit-criteria"',
                "exit_criteria:",
                "  required:",
                "    - validator exists",
                "```",
                '```yaml id="deliverables"',
                "deliverables:",
                "  minimum:",
                "    - validator",
                "```",
                "## Gate-Readiness Criteria",
                '```yaml id="gate-readiness-criteria"',
                "gate_readiness_criteria:",
                "  - Stage Taskbook must reference master_taskbook_ref.",
                "  - Stage Taskbook claims are distinct from accepted delivery state.",
                "```",
                '```yaml id="stage-readiness-contract"',
                "stage_readiness_contract:",
                "  minimum_readiness_claim: Stage Taskbooks express bounded stage claims.",
                "  required_evidence:",
                "    - stage objective",
                "  gate_question: Are stage claims distinct from accepted state?",
                "  explicit_non_goal: Not state authority or workflow platform.",
                "```",
                '```yaml id="minimum-evidence-package"',
                "minimum_evidence_package:",
                "  required_fields:",
                "    - stage_taskbook_path",
                "    - stage_taskbook_hash",
                "    - master_taskbook_ref",
                "    - supports_project_goal_summary",
                "    - non_goals",
                "    - gate_readiness_criteria",
                "    - validation_result",
                "```",
                '```yaml id="non-goals"',
                "non_goals:",
                "  - no stage execution",
                "  - no automatic acceptance",
                "```",
                "This stage has a state authority boundary, execution authorization boundary, and mutation boundary.",
            ]
        )

    def by_field(self, result: dict) -> dict[str, dict]:
        return {item["field"]: item for item in result["required_field_check_table"]}

    def test_complete_stage_taskbook_passes_without_authority_fields(self) -> None:
        result = validate_stage_taskbook(raw_content=self.complete_content(), schema=self.schema())

        assert result["validation_result"] == VALIDATION_RESULT_PASSED
        assert result["fail_closed_result"] == "pass"
        assert result["master_binding_check"]["result"] == FIELD_RESULT_PRESENT
        assert result["minimum_evidence_package_check"]["result"] == FIELD_RESULT_PRESENT
        assert not result["fail_closed_violations"]
        assert not (set(result) & FORBIDDEN_VALIDATOR_RESULT_FIELDS)
        assert result["validator_result_is_authority"] is False

    def test_extract_yaml_blocks_reports_ids(self) -> None:
        blocks = extract_yaml_blocks(self.complete_content())

        assert len(blocks) >= 7
        assert "master-binding" in {block["id"] for block in blocks}

    def test_missing_master_taskbook_ref_fails_closed(self) -> None:
        raw = self.complete_content().replace(
            "  master_taskbook_ref:\n"
            "    path: PROJECT_MASTER_TASKBOOK.md\n"
            f"    raw_snapshot_sha256: {MASTER_SHA}\n",
            "",
        )

        result = validate_stage_taskbook(raw_content=raw, schema=self.schema())

        assert result["validation_result"] == VALIDATION_RESULT_FAILED_CLOSED
        assert result["fail_closed_result"] == "fail_closed"
        assert "master_taskbook_ref" in result["fail_closed_violations"]

    def test_master_binding_hash_without_path_fails_closed(self) -> None:
        raw = self.complete_content().replace("  master_taskbook_path: PROJECT_MASTER_TASKBOOK.md\n", "")
        raw = raw.replace("    path: PROJECT_MASTER_TASKBOOK.md\n", "")

        result = validate_stage_taskbook(raw_content=raw, schema=self.schema())

        assert result["validation_result"] == VALIDATION_RESULT_FAILED_CLOSED
        assert result["master_binding_check"]["result"] == FIELD_RESULT_MALFORMED
        assert "master_taskbook_path_missing" in result["master_binding_check"]["failure_reason_or_none"]

    def test_master_hash_mismatch_fails_closed(self) -> None:
        result = validate_stage_taskbook(raw_content=self.complete_content(OTHER_SHA), schema=self.schema())

        assert result["validation_result"] == VALIDATION_RESULT_FAILED_CLOSED
        assert result["master_binding_check"]["result"] == FIELD_RESULT_MALFORMED
        assert "master_hash_mismatch" in result["master_binding_check"]["failure_reason_or_none"]

    def test_supports_project_goal_false_fails_closed(self) -> None:
        raw = self.complete_content().replace("  supports_project_goal: true", "  supports_project_goal: false")

        result = validate_stage_taskbook(raw_content=raw, schema=self.schema())

        assert result["validation_result"] == VALIDATION_RESULT_FAILED_CLOSED
        assert result["supports_project_goal_check"]["result"] == FIELD_RESULT_MALFORMED
        assert "supports_project_goal" in result["fail_closed_violations"]

    def test_missing_non_goals_fails_closed(self) -> None:
        raw = self.complete_content().replace(
            '```yaml id="non-goals"\nnon_goals:\n  - no stage execution\n  - no automatic acceptance\n```',
            "",
        )

        result = validate_stage_taskbook(raw_content=raw, schema=self.schema())

        assert result["validation_result"] == VALIDATION_RESULT_FAILED_CLOSED
        assert self.by_field(result)["non_goals"]["result"] == FIELD_RESULT_MISSING

    def test_non_goals_heading_without_body_fails_closed(self) -> None:
        raw = self.complete_content().replace(
            '```yaml id="non-goals"\nnon_goals:\n  - no stage execution\n  - no automatic acceptance\n```',
            "## Non-Goals",
        )

        result = validate_stage_taskbook(raw_content=raw, schema=self.schema())

        assert result["validation_result"] == VALIDATION_RESULT_FAILED_CLOSED
        assert self.by_field(result)["non_goals"]["result"] == FIELD_RESULT_MISSING
        assert self.by_field(result)["non_goals"]["failure_reason_or_none"] == "machine_checkable_field_missing"

    def test_missing_gate_readiness_fails_closed(self) -> None:
        raw = self.complete_content().replace(
            "## Gate-Readiness Criteria\n"
            '```yaml id="gate-readiness-criteria"\n'
            "gate_readiness_criteria:\n"
            "  - Stage Taskbook must reference master_taskbook_ref.\n"
            "  - Stage Taskbook claims are distinct from accepted delivery state.\n"
            "```",
            "",
        )

        result = validate_stage_taskbook(raw_content=raw, schema=self.schema())

        assert result["validation_result"] == VALIDATION_RESULT_FAILED_CLOSED
        assert self.by_field(result)["gate_readiness_criteria"]["result"] == FIELD_RESULT_MISSING

    def test_gate_readiness_heading_without_body_fails_closed(self) -> None:
        raw = self.complete_content().replace(
            "## Gate-Readiness Criteria\n"
            '```yaml id="gate-readiness-criteria"\n'
            "gate_readiness_criteria:\n"
            "  - Stage Taskbook must reference master_taskbook_ref.\n"
            "  - Stage Taskbook claims are distinct from accepted delivery state.\n"
            "```",
            "## Gate-Readiness Criteria",
        )

        result = validate_stage_taskbook(raw_content=raw, schema=self.schema())

        assert result["validation_result"] == VALIDATION_RESULT_FAILED_CLOSED
        assert self.by_field(result)["gate_readiness_criteria"]["result"] == FIELD_RESULT_MISSING
        assert (
            self.by_field(result)["gate_readiness_criteria"]["failure_reason_or_none"]
            == "machine_checkable_field_missing"
        )

    def test_missing_minimum_evidence_package_fails_closed(self) -> None:
        raw = self.complete_content().replace(
            '```yaml id="minimum-evidence-package"\n'
            "minimum_evidence_package:\n"
            "  required_fields:\n"
            "    - stage_taskbook_path\n"
            "    - stage_taskbook_hash\n"
            "    - master_taskbook_ref\n"
            "    - supports_project_goal_summary\n"
            "    - non_goals\n"
            "    - gate_readiness_criteria\n"
            "    - validation_result\n"
            "```",
            "",
        )

        result = validate_stage_taskbook(raw_content=raw, schema=self.schema())

        assert result["validation_result"] == VALIDATION_RESULT_FAILED_CLOSED
        assert result["minimum_evidence_package_check"]["result"] == FIELD_RESULT_MISSING

    def test_minimum_evidence_package_field_mentions_outside_section_do_not_pass(self) -> None:
        raw = self.complete_content().replace("    - validation_result\n", "")
        raw += "\nThis paragraph mentions validation_result outside the minimum evidence package.\n"

        result = validate_stage_taskbook(raw_content=raw, schema=self.schema())

        assert result["validation_result"] == VALIDATION_RESULT_FAILED_CLOSED
        assert result["minimum_evidence_package_check"]["result"] == FIELD_RESULT_MISSING
        assert result["minimum_evidence_package_check"]["missing_fields"] == ["validation_result"]

    def test_delivery_state_accepted_claim_fails_closed(self) -> None:
        raw = self.complete_content() + "\naccepted: true\n"

        result = validate_stage_taskbook(raw_content=raw, schema=self.schema())

        assert result["validation_result"] == VALIDATION_RESULT_FAILED_CLOSED
        assert result["fail_closed_negative_case_results"]["forbidden_claims"][0]["claim"] == "accepted"

    def test_schema_forbidden_delivery_state_accepted_phrase_fails_closed(self) -> None:
        raw = self.complete_content() + "\nThis draft says delivery_state accepted.\n"

        result = validate_stage_taskbook(raw_content=raw, schema=self.schema())

        assert result["validation_result"] == VALIDATION_RESULT_FAILED_CLOSED
        assert result["fail_closed_negative_case_results"]["forbidden_claims"][0]["claim"] == "delivery_state_accepted"

    def test_review_acceptance_true_claim_fails_closed(self) -> None:
        raw = self.complete_content() + "\nreview_acceptance: true\n"

        result = validate_stage_taskbook(raw_content=raw, schema=self.schema())

        assert result["validation_result"] == VALIDATION_RESULT_FAILED_CLOSED
        assert result["fail_closed_negative_case_results"]["forbidden_claims"][0]["claim"] == "review_acceptance"

    def test_execution_authority_claim_fails_closed(self) -> None:
        raw = self.complete_content() + "\nexecution_authority: granted\n"

        result = validate_stage_taskbook(raw_content=raw, schema=self.schema())

        assert result["validation_result"] == VALIDATION_RESULT_FAILED_CLOSED
        assert result["fail_closed_negative_case_results"]["forbidden_claims"][0]["claim"] == "execution_authority"

    def test_missing_raw_content_returns_known_unknown(self) -> None:
        result = validate_stage_taskbook(raw_content=None, stage_taskbook_path=None, schema=self.schema())

        assert result["validation_result"] == VALIDATION_RESULT_KNOWN_UNKNOWN
        assert result["fail_closed_result"] == "fail_closed"
        assert result["failure_reason_or_none"] == "stage_taskbook_path_missing"
        assert all(item["result"] == FIELD_RESULT_KNOWN_UNKNOWN for item in result["required_field_check_table"])

    def test_validator_does_not_mutate_schema_input(self) -> None:
        schema = self.schema()
        before = copy.deepcopy(schema)

        validate_stage_taskbook(raw_content=self.complete_content(), schema=schema)

        assert schema == before

    def test_current_stage_2_taskbook_validates_without_mutation(self) -> None:
        project = Path(__file__).resolve().parents[1]
        stage = project / "docs" / "taskbooks" / "stages" / "STAGE_02_STAGE_TASKBOOK_MANAGEMENT.md"
        master = project / "PROJECT_MASTER_TASKBOOK.md"
        stage_before = sha256_file(stage)
        master_before = sha256_file(master)

        result = validate_stage_taskbook(
            stage_taskbook_path=stage,
            schema=self.schema(),
            expected_master_taskbook_hash=MASTER_SHA,
            observed_git_head="0" * 40,
        )

        assert result["validation_result"] == VALIDATION_RESULT_PASSED
        assert result["stage_taskbook_hash"] == stage_before
        assert result["master_taskbook_ref"]["raw_snapshot_sha256"] == MASTER_SHA
        assert sha256_file(stage) == stage_before
        assert sha256_file(master) == master_before


if __name__ == "__main__":
    unittest.main()
