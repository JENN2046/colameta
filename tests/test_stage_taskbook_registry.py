from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from runner.stage_taskbook_registry import (
    StageTaskbookRegistryError,
    load_stage_taskbook_registry,
    sha256_file,
)
from runner.stage_taskbook_validator import load_stage_taskbook_schema, validate_stage_taskbook


class StageTaskbookRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="colameta-stage-registry-")
        self.project = Path(self._tmp.name)
        self.registry_dir = self.project / ".colameta" / "taskbooks"
        self.registry_dir.mkdir(parents=True)
        self.master_path = self.project / "PROJECT_MASTER_TASKBOOK.md"
        self.master_path.write_text("# Master Taskbook\n\nproject_final_goal: test goal\n", encoding="utf-8")
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

    def expected_master_ref(self) -> dict[str, str]:
        return {
            "path": "PROJECT_MASTER_TASKBOOK.md",
            "raw_snapshot_sha256": self.master_sha,
            "review_status": "freeze_candidate_confirmed_for_exact_hash",
        }

    def tearDown(self) -> None:
        self._tmp.cleanup()

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

    def valid_record(self) -> dict:
        source_ref = self.expected_source_ref()
        stage_hash = sha256_file(self.stage_path)
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
                "ahead": 54,
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
                    "stage_taskbook_raw_snapshot_sha256": stage_hash,
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
                    "created_at": "2026-06-30T02:02:46+08:00",
                }
            },
            "created_at": "2026-06-30T02:02:46+08:00",
        }

    def write_registry(self, record: dict) -> None:
        self.registry_path.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")

    def assert_registry_error(self, record: dict, code: str) -> StageTaskbookRegistryError:
        self.write_registry(record)
        with self.assertRaises(StageTaskbookRegistryError) as raised:
            load_stage_taskbook_registry(
                self.project,
                self.registry_path,
                expected_master_taskbook_ref=self.expected_master_ref(),
                expected_source_version_ref=self.expected_source_ref(),
            )
        assert raised.exception.error_code == code
        return raised.exception

    def test_valid_registry_loads_and_consumes_validator_result(self) -> None:
        record = self.valid_record()
        self.write_registry(record)

        result = load_stage_taskbook_registry(
            self.project,
            self.registry_path,
            expected_master_taskbook_ref=self.expected_master_ref(),
            expected_source_version_ref=self.expected_source_ref(),
        )

        assert result["ok"] is True
        assert result["record_count"] == 1
        assert result["validator_results_verified"] is True
        assert result["registry_result_is_authority"] is False
        assert result["stage_ids"] == ["stage_02_stage_taskbook_management"]

    def test_missing_validator_result_fails_closed(self) -> None:
        record = self.valid_record()
        del record["records"]["stage_02_stage_taskbook_management"]["validator_result"]

        error = self.assert_registry_error(record, "REQUIRED_FIELD_MISSING")

        assert error.details["object"] == "records.stage_02_stage_taskbook_management"

    def test_validator_result_must_be_consumed(self) -> None:
        record = self.valid_record()
        record["records"]["stage_02_stage_taskbook_management"]["validator_result"]["validator_result_consumed"] = False

        self.assert_registry_error(record, "VALIDATOR_RESULT_NOT_CONSUMED")

    def test_failed_validator_result_fails_closed(self) -> None:
        record = self.valid_record()
        validator = record["records"]["stage_02_stage_taskbook_management"]["validator_result"]
        validator["validation_result"] = "failed_closed"
        validator["fail_closed_result"] = "fail_closed"
        validator["fail_closed_violations"] = ["non_goals"]

        self.assert_registry_error(record, "FIELD_VALUE_UNSUPPORTED")

    def test_validator_result_hash_mismatch_fails_closed(self) -> None:
        record = self.valid_record()
        record["records"]["stage_02_stage_taskbook_management"]["validator_result"]["stage_taskbook_hash"] = "0" * 64

        self.assert_registry_error(record, "FIELD_VALUE_UNSUPPORTED")

    def test_stage_hash_mismatch_fails_closed(self) -> None:
        record = self.valid_record()
        record["records"]["stage_02_stage_taskbook_management"]["stage_taskbook_raw_snapshot_sha256"] = "0" * 64

        self.assert_registry_error(record, "STAGE_TASKBOOK_HASH_MISMATCH")

    def test_missing_stage_file_fails_closed(self) -> None:
        record = self.valid_record()
        self.stage_path.unlink()

        self.assert_registry_error(record, "STAGE_TASKBOOK_FILE_MISSING")

    def test_stage_path_must_stay_inside_project(self) -> None:
        record = self.valid_record()
        record["records"]["stage_02_stage_taskbook_management"]["stage_taskbook_path"] = "../STAGE_02.md"

        self.assert_registry_error(record, "PATH_OUTSIDE_PROJECT")

    def test_master_taskbook_hash_mismatch_fails_closed(self) -> None:
        record = self.valid_record()
        record["records"]["stage_02_stage_taskbook_management"]["master_taskbook_ref"][
            "raw_snapshot_sha256"
        ] = "0" * 64

        error = self.assert_registry_error(record, "OBJECT_FIELD_VALUE_UNSUPPORTED")

        assert error.details["field"] == "records.stage_02_stage_taskbook_management.master_taskbook_ref"

    def test_master_taskbook_disk_hash_mismatch_fails_closed(self) -> None:
        record = self.valid_record()
        expected_master_ref = self.expected_master_ref()
        self.write_registry(record)
        self.master_path.write_text("# Changed Master\n", encoding="utf-8")

        with self.assertRaises(StageTaskbookRegistryError) as raised:
            load_stage_taskbook_registry(
                self.project,
                self.registry_path,
                expected_master_taskbook_ref=expected_master_ref,
                expected_source_version_ref=self.expected_source_ref(),
            )

        assert raised.exception.error_code == "MASTER_TASKBOOK_HASH_MISMATCH"

    def test_authority_claim_fails_closed(self) -> None:
        record = self.valid_record()
        record["records"]["stage_02_stage_taskbook_management"]["authority_boundary"][
            "registered_stage_authorizes_execution"
        ] = True

        error = self.assert_registry_error(record, "FORBIDDEN_AUTHORITY_CLAIM")

        assert "registered_stage_authorizes_execution" in error.details["path"]

    def test_registry_cannot_claim_delivery_state_authority(self) -> None:
        record = self.valid_record()
        record["authority_boundary"]["registry_is_delivery_state_authority"] = True

        error = self.assert_registry_error(record, "FORBIDDEN_AUTHORITY_CLAIM")

        assert "registry_is_delivery_state_authority" in error.details["path"]

    def test_source_version_ref_hash_mismatch_fails_closed(self) -> None:
        record = self.valid_record()
        expected_source_ref = self.expected_source_ref()
        self.write_registry(record)
        self.version_path.write_text("# changed\n", encoding="utf-8")

        with self.assertRaises(StageTaskbookRegistryError) as raised:
            load_stage_taskbook_registry(
                self.project,
                self.registry_path,
                expected_master_taskbook_ref=self.expected_master_ref(),
                expected_source_version_ref=expected_source_ref,
            )

        assert raised.exception.error_code == "SOURCE_REF_HASH_MISMATCH"

    def test_gate_readiness_text_authority_claim_fails_closed(self) -> None:
        claims = [
            "registry authorizes execution",
            "execution authorized",
            "allowed to execute",
            "creates a ReviewDecision",
            "emits a GateEvent",
            "registry is delivery state authority",
            "review acceptance granted",
        ]
        for claim in claims:
            with self.subTest(claim=claim):
                record = self.valid_record()
                record["records"]["stage_02_stage_taskbook_management"]["gate_readiness_summary"][
                    "minimum_readiness_claim"
                ] = claim

                self.assert_registry_error(record, "FORBIDDEN_TEXT_AUTHORITY_CLAIM")

    def test_non_goals_text_authority_claim_fails_closed(self) -> None:
        claims = [
            "registry writes delivery state",
            "registry writes delivery_state",
            "registry grants review acceptance authority",
            "execution authority granted",
        ]
        for claim in claims:
            with self.subTest(claim=claim):
                record = self.valid_record()
                record["records"]["stage_02_stage_taskbook_management"]["non_goals_summary"] = [claim]

                self.assert_registry_error(record, "FORBIDDEN_TEXT_AUTHORITY_CLAIM")

    def test_gate_readiness_invalid_text_type_fails_closed(self) -> None:
        record = self.valid_record()
        record["records"]["stage_02_stage_taskbook_management"]["gate_readiness_summary"][
            "minimum_readiness_claim"
        ] = True

        self.assert_registry_error(record, "GATE_READINESS_FIELD_INVALID")

    def test_stage_id_key_mismatch_fails_closed(self) -> None:
        record = self.valid_record()
        stage_record = record["records"].pop("stage_02_stage_taskbook_management")
        record["records"]["stage_99_wrong"] = stage_record

        self.assert_registry_error(record, "STAGE_ID_KEY_MISMATCH")

    def test_unknown_top_level_field_fails_closed(self) -> None:
        record = self.valid_record()
        record["delivery_state_accepted"] = True

        self.assert_registry_error(record, "UNSUPPORTED_FIELD")

    def test_default_registry_path_symlink_escape_fails_closed(self) -> None:
        outside = self.project.parent / f"{self.project.name}-outside-stage-registry.json"
        outside.write_text(json.dumps(self.valid_record()), encoding="utf-8")
        self.registry_path.symlink_to(outside)

        with self.assertRaises(StageTaskbookRegistryError) as raised:
            load_stage_taskbook_registry(
                self.project,
                expected_master_taskbook_ref=self.expected_master_ref(),
                expected_source_version_ref=self.expected_source_ref(),
            )

        assert raised.exception.error_code == "PATH_OUTSIDE_PROJECT"

    def test_validator_result_mismatch_after_stage_change_fails_closed(self) -> None:
        record = copy.deepcopy(self.valid_record())
        self.write_registry(record)
        self.stage_path.write_text(self.stage_taskbook_content().replace("Stage Taskbook Management", "Changed", 1), encoding="utf-8")

        with self.assertRaises(StageTaskbookRegistryError) as raised:
            load_stage_taskbook_registry(
                self.project,
                self.registry_path,
                expected_master_taskbook_ref=self.expected_master_ref(),
                expected_source_version_ref=self.expected_source_ref(),
            )

        assert raised.exception.error_code == "STAGE_TASKBOOK_HASH_MISMATCH"


if __name__ == "__main__":
    unittest.main()
