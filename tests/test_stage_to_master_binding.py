from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from runner.stage_taskbook_registry import sha256_file
from runner.stage_taskbook_validator import load_stage_taskbook_schema, validate_stage_taskbook
from runner.stage_to_master_binding import (
    EXPECTED_PROJECT_FINAL_GOAL_REF,
    StageToMasterBindingError,
    validate_stage_to_master_binding,
)


class StageToMasterBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="colameta-stage-binding-")
        self.project = Path(self._tmp.name)
        self.registry_dir = self.project / ".colameta" / "taskbooks"
        self.registry_dir.mkdir(parents=True)
        self.master_path = self.project / "PROJECT_MASTER_TASKBOOK.md"
        self.master_path.write_text(
            "# Master Taskbook\n\nproject_final_goal: Build a goal-anchored AI delivery command layer.\n",
            encoding="utf-8",
        )
        self.master_sha = sha256_file(self.master_path)
        schema = load_stage_taskbook_schema(Path(__file__).resolve().parents[1])
        (self.registry_dir / "stage_taskbook_schema.json").write_text(
            json.dumps(schema, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        self.stage_path = self.project / "docs" / "taskbooks" / "stages" / "STAGE_02_STAGE_TASKBOOK_MANAGEMENT.md"
        self.stage_path.parent.mkdir(parents=True)
        self.stage_path.write_text(self.stage_taskbook_content(), encoding="utf-8")
        self.version_path = (
            self.project
            / "docs"
            / "taskbooks"
            / "versions"
            / "stage-02"
            / "VERSION_STAGE_02_V2_2_STAGE_TASKBOOK_REGISTRY_V1.md"
        )
        self.version_path.parent.mkdir(parents=True)
        self.version_path.write_text(
            "# Version v2.2\n\nversion_id: stage_02_v2_2_stage_taskbook_registry_v1\n",
            encoding="utf-8",
        )
        self.registry_path = self.registry_dir / "stage_taskbook_registry.json"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def expected_master_ref(self) -> dict[str, str]:
        return {
            "path": "PROJECT_MASTER_TASKBOOK.md",
            "raw_snapshot_sha256": self.master_sha,
            "review_status": "freeze_candidate_confirmed_for_exact_hash",
        }

    def expected_source_ref(self) -> dict[str, str]:
        return {
            "path": "docs/taskbooks/versions/stage-02/VERSION_STAGE_02_V2_2_STAGE_TASKBOOK_REGISTRY_V1.md",
            "raw_snapshot_sha256": sha256_file(self.version_path),
            "version_id": "stage_02_v2_2_stage_taskbook_registry_v1",
        }

    def stage_taskbook_content(self) -> str:
        return "\n".join(
            [
                "# Stage 2 Taskbook: Stage Taskbook Management",
                '```yaml id="stage-taskbook-summary"',
                "stage_taskbook:",
                "  stage_id: stage_02_stage_taskbook_management",
                "  stage_name: Stage Taskbook Management",
                "  chinese_name: 阶段任务书管理",
                "  status: discussion_draft",
                "  authority_status: planning_reference_only",
                "```",
                "## 1. Master Binding",
                '```yaml id="master-binding"',
                "master_binding:",
                "  master_taskbook_path: PROJECT_MASTER_TASKBOOK.md",
                "  master_taskbook_ref:",
                "    path: PROJECT_MASTER_TASKBOOK.md",
                f"    raw_snapshot_sha256: {self.master_sha}",
                "    review_status: freeze_candidate_confirmed_for_exact_hash",
                f"  project_final_goal_ref: {EXPECTED_PROJECT_FINAL_GOAL_REF}",
                "  supports_project_goal: true",
                "```",
                "## 2. Stage Purpose",
                "Stage 2 makes Stage Taskbooks first-class governed planning artifacts.",
                "It preserves Master goal binding while staying evidence-only.",
                '```yaml id="entry-criteria"',
                "entry_criteria:",
                "  required:",
                "    - master reference exists",
                "```",
                '```yaml id="exit-criteria"',
                "exit_criteria:",
                "  required:",
                "    - registry exists",
                "```",
                '```yaml id="deliverables"',
                "deliverables:",
                "  minimum:",
                "    - registry",
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

    def validator_result_record(self) -> dict:
        schema = load_stage_taskbook_schema(self.project)
        result = validate_stage_taskbook(
            stage_taskbook_path=self.stage_path,
            schema=schema,
            expected_master_taskbook_hash=self.master_sha,
            observed_git_head="e" * 40,
        )
        return {
            "validator_name": "runner.stage_taskbook_validator.validate_stage_taskbook",
            "validator_schema_version": "stage_taskbook_schema.v1",
            "validator_result_consumed": True,
            "validation_result": result["validation_result"],
            "fail_closed_result": result["fail_closed_result"],
            "stage_taskbook_path": "docs/taskbooks/stages/STAGE_02_STAGE_TASKBOOK_MANAGEMENT.md",
            "stage_taskbook_hash": result["stage_taskbook_hash"],
            "stage_id": result["stage_id"],
            "stage_name": result["stage_name"],
            "master_taskbook_ref": result["master_taskbook_ref"],
            "supports_project_goal": result["supports_project_goal"],
            "fail_closed_violations": result["fail_closed_violations"],
            "required_field_violations": result["required_field_violations"],
            "validator_result_is_authority": result["validator_result_is_authority"],
            "creates_review_decision": result["creates_review_decision"],
            "emits_gate_event": result["emits_gate_event"],
            "writes_delivery_state": result["writes_delivery_state"],
        }

    def valid_registry(self) -> dict:
        source_ref = self.expected_source_ref()
        return {
            "schema_version": "stage_taskbook_registry.v1",
            "registry_record_id": "stage_taskbook.registry.current",
            "project": "ColaMeta",
            "workspace": str(self.project.resolve()),
            "record_key": "stage_id",
            "source_version_taskbook_ref": source_ref,
            "observed_git_head": "e" * 40,
            "observed_origin_main_local_tracking_ref": "f" * 40,
            "ahead_behind_from_local_refs": {
                "ahead": 55,
                "behind": 0,
                "source": "git rev-list --left-right --count origin/main...HEAD",
            },
            "live_remote_status_not_validated": True,
            "authority_boundary": {
                "registry_is_execution_authority": False,
                "registry_is_delivery_state_authority": False,
                "registry_can_create_review_decision": False,
                "registry_can_emit_gate_event": False,
                "registry_can_override_delivery_state_gate": False,
                "registry_result_is_authority": False,
            },
            "mutation_boundary": {
                "stage_taskbook_mutation_allowed": False,
                "registry_can_mutate_stage_taskbook": False,
                "requires_separate_hash_specific_authorization": True,
            },
            "records": {
                "stage_02_stage_taskbook_management": {
                    "stage_id": "stage_02_stage_taskbook_management",
                    "stage_name": "Stage Taskbook Management",
                    "stage_taskbook_path": "docs/taskbooks/stages/STAGE_02_STAGE_TASKBOOK_MANAGEMENT.md",
                    "stage_taskbook_raw_snapshot_sha256": sha256_file(self.stage_path),
                    "master_taskbook_ref": self.expected_master_ref(),
                    "supports_project_goal": True,
                    "validator_result": self.validator_result_record(),
                    "gate_readiness_summary": {
                        "minimum_readiness_claim": "Stage Taskbooks express bounded stage claims.",
                        "gate_question": "Are stage claims distinct from accepted state?",
                        "criteria_count": 2,
                        "delivery_state_accepted": False,
                        "gate_readiness_is_delivery_state": False,
                    },
                    "non_goals_summary": [
                        "no stage execution",
                        "no automatic acceptance",
                    ],
                    "authority_boundary": {
                        "registered_stage_is_accepted_delivery_state": False,
                        "registered_stage_authorizes_execution": False,
                        "registry_can_mutate_stage_taskbook": False,
                        "registry_can_override_delivery_state_gate": False,
                        "gate_readiness_is_delivery_state": False,
                        "registry_result_is_authority": False,
                    },
                    "source_version_taskbook_ref": source_ref,
                    "observed_git_head": "e" * 40,
                    "created_at": "2026-06-30T03:10:00+08:00",
                }
            },
            "created_at": "2026-06-30T03:10:00+08:00",
        }

    def write_registry(self, record: dict | None = None) -> None:
        self.registry_path.write_text(json.dumps(record or self.valid_registry(), indent=2, sort_keys=True), encoding="utf-8")

    def binding_result(self) -> dict:
        return validate_stage_to_master_binding(
            self.project,
            self.registry_path,
            expected_master_taskbook_ref=self.expected_master_ref(),
            expected_registry_source_ref=self.expected_source_ref(),
        )

    def assert_binding_error(self, code: str) -> StageToMasterBindingError:
        with self.assertRaises(StageToMasterBindingError) as raised:
            self.binding_result()
        assert raised.exception.error_code == code
        return raised.exception

    def rewrite_stage(self, value: str) -> None:
        self.stage_path.write_text(value, encoding="utf-8")
        record = self.valid_registry()
        self.write_registry(record)

    def test_valid_binding_passes_and_is_evidence_only(self) -> None:
        self.write_registry()

        result = self.binding_result()

        assert result["binding_status"] == "bound"
        assert result["validation_result"] == "passed"
        assert result["master_hash_match_check"]["result"] == "passed"
        assert result["project_final_goal_ref_preservation_check"]["actual"] == EXPECTED_PROJECT_FINAL_GOAL_REF
        assert result["freeze_candidate_boundary_check"]["treated_as_execution_authority"] is False
        assert result["binding_result_is_authority"] is False
        assert result["creates_review_decision"] is False
        assert result["emits_gate_event"] is False
        assert result["writes_delivery_state"] is False
        assert result["mutates_master_taskbook"] is False
        assert result["mutates_project_final_goal"] is False
        assert result["authorizes_execution"] is False

    def test_real_repository_binding_passes(self) -> None:
        repo = Path(__file__).resolve().parents[1]

        result = validate_stage_to_master_binding(repo)

        assert result["binding_status"] == "bound"
        assert result["stage_id"] == "stage_02_stage_taskbook_management"
        assert result["source_stage_taskbook_ref"]["path"] == "docs/taskbooks/stages/STAGE_02_STAGE_TASKBOOK_MANAGEMENT.md"

    def test_missing_project_final_goal_ref_fails_closed(self) -> None:
        content = self.stage_taskbook_content().replace(
            f"  project_final_goal_ref: {EXPECTED_PROJECT_FINAL_GOAL_REF}\n",
            "",
        )
        self.rewrite_stage(content)

        self.assert_binding_error("PROJECT_FINAL_GOAL_REF_INVALID")

    def test_wrong_project_final_goal_ref_fails_closed(self) -> None:
        content = self.stage_taskbook_content().replace(
            EXPECTED_PROJECT_FINAL_GOAL_REF,
            "stage_taskbook.project_final_goal",
        )
        self.rewrite_stage(content)

        self.assert_binding_error("PROJECT_FINAL_GOAL_REF_INVALID")

    def test_supports_project_goal_false_fails_closed(self) -> None:
        content = self.stage_taskbook_content().replace("  supports_project_goal: true", "  supports_project_goal: false")
        self.rewrite_stage(content)

        self.assert_binding_error("REGISTRY_VALIDATION_FAILED")

    def test_missing_stage_purpose_rationale_fails_closed(self) -> None:
        content = self.stage_taskbook_content().replace(
            "Stage 2 makes Stage Taskbooks first-class governed planning artifacts.\n"
            "It preserves Master goal binding while staying evidence-only.\n",
            "",
        )
        self.rewrite_stage(content)

        self.assert_binding_error("SUPPORT_RATIONALE_MISSING")

    def test_missing_master_project_final_goal_fails_closed(self) -> None:
        self.master_path.write_text("# Master Taskbook\n\nnorth_star_goal: Missing canonical field.\n", encoding="utf-8")
        self.master_sha = sha256_file(self.master_path)
        self.stage_path.write_text(self.stage_taskbook_content(), encoding="utf-8")
        self.write_registry()

        self.assert_binding_error("MASTER_PROJECT_FINAL_GOAL_MISSING")

    def test_master_hash_mismatch_fails_closed(self) -> None:
        record = self.valid_registry()
        expected_master_ref = self.expected_master_ref()
        self.write_registry(record)
        self.master_path.write_text(
            "# Master Taskbook\n\nproject_final_goal: Changed after registry creation.\n",
            encoding="utf-8",
        )

        with self.assertRaises(StageToMasterBindingError) as raised:
            validate_stage_to_master_binding(
                self.project,
                self.registry_path,
                expected_master_taskbook_ref=expected_master_ref,
                expected_registry_source_ref=self.expected_source_ref(),
            )

        assert raised.exception.error_code == "REGISTRY_VALIDATION_FAILED"

    def test_missing_master_ref_fails_closed_via_registry(self) -> None:
        record = self.valid_registry()
        del record["records"]["stage_02_stage_taskbook_management"]["master_taskbook_ref"]
        self.write_registry(record)

        self.assert_binding_error("REGISTRY_VALIDATION_FAILED")

    def test_stage_claims_master_mutation_authority_fails_closed(self) -> None:
        content = self.stage_taskbook_content() + "\nStage may mutate the Master Taskbook.\n"
        self.rewrite_stage(content)

        error = self.assert_binding_error("FORBIDDEN_STAGE_BINDING_CLAIM")

        assert error.details["forbidden_claims"][0]["claim"] == "stage_claims_master_mutation_authority"

    def test_stage_claims_project_final_goal_mutation_fails_closed(self) -> None:
        content = self.stage_taskbook_content() + "\nStage may override project_final_goal.\n"
        self.rewrite_stage(content)

        error = self.assert_binding_error("FORBIDDEN_STAGE_BINDING_CLAIM")

        assert error.details["forbidden_claims"][0]["claim"] == "stage_claims_project_final_goal_mutation"

    def test_stage_claims_freeze_candidate_execution_authority_fails_closed(self) -> None:
        content = self.stage_taskbook_content() + "\nfreeze_candidate grants execution authority.\n"
        self.rewrite_stage(content)

        error = self.assert_binding_error("FORBIDDEN_STAGE_BINDING_CLAIM")

        assert error.details["forbidden_claims"][0]["claim"] == "stage_claims_freeze_candidate_is_execution_authority"

    def test_stage_claims_delivery_state_accepted_fails_closed(self) -> None:
        content = self.stage_taskbook_content() + "\ndelivery_state accepted.\n"
        self.rewrite_stage(content)

        error = self.assert_binding_error("REGISTRY_VALIDATION_FAILED")

        assert error.details["registry_error_code"] == "FIELD_VALUE_UNSUPPORTED"

    def test_registry_result_must_be_valid_before_binding(self) -> None:
        record = copy.deepcopy(self.valid_registry())
        record["records"]["stage_02_stage_taskbook_management"]["validator_result"]["validator_result_consumed"] = False
        self.write_registry(record)

        self.assert_binding_error("REGISTRY_VALIDATION_FAILED")


if __name__ == "__main__":
    unittest.main()
