from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from runner.master_taskbook_registry import (
    MasterTaskbookRegistryError,
    load_master_taskbook_registry,
    sha256_file,
)


class MasterTaskbookRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="colameta-master-registry-")
        self.project = Path(self._tmp.name)
        self.master = self.project / "PROJECT_MASTER_TASKBOOK.md"
        self.master.write_text("# Master\n\nproject_final_goal: keep the anchor stable\n", encoding="utf-8")
        self.stage_taskbook = self.project / "docs" / "taskbooks" / "stages" / "STAGE_01_MASTER_TASKBOOK_ANCHORING.md"
        self.stage_taskbook.parent.mkdir(parents=True)
        self.stage_taskbook.write_text("# Stage 1\n\nstage_id: stage_01_master_taskbook_anchoring\n", encoding="utf-8")
        self.version_taskbook = (
            self.project
            / "docs"
            / "taskbooks"
            / "versions"
            / "stage-01"
            / "VERSION_STAGE_01_V1_1_MASTER_TASKBOOK_REGISTRY_V1.md"
        )
        self.version_taskbook.parent.mkdir(parents=True)
        self.version_taskbook.write_text(
            "# Version v1.1\n\nversion_id: stage_01_v1_1_master_taskbook_registry_v1\n",
            encoding="utf-8",
        )
        self.registry_dir = self.project / ".colameta" / "taskbooks"
        self.registry_dir.mkdir(parents=True)
        self.registry_path = self.registry_dir / "master_taskbook_registry.json"

    def expected_source_refs(self) -> dict[str, dict[str, str]]:
        return {
            "source_stage_taskbook_ref": {
                "path": "docs/taskbooks/stages/STAGE_01_MASTER_TASKBOOK_ANCHORING.md",
                "raw_snapshot_sha256": sha256_file(self.stage_taskbook),
                "id_field": "stage_id",
                "id": "stage_01_master_taskbook_anchoring",
            },
            "source_version_taskbook_ref": {
                "path": "docs/taskbooks/versions/stage-01/VERSION_STAGE_01_V1_1_MASTER_TASKBOOK_REGISTRY_V1.md",
                "raw_snapshot_sha256": sha256_file(self.version_taskbook),
                "id_field": "version_id",
                "id": "stage_01_v1_1_master_taskbook_registry_v1",
            },
        }

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def valid_record(self) -> dict:
        return {
            "schema_version": "master_taskbook_registry.v1",
            "registry_record_id": "master_taskbook.current",
            "project": "ColaMeta",
            "workspace": str(self.project.resolve()),
            "master_taskbook_path": "PROJECT_MASTER_TASKBOOK.md",
            "master_raw_snapshot_sha256": sha256_file(self.master),
            "master_review_status": "freeze_candidate_confirmed_for_exact_hash",
            "master_authority_boundary": {
                "review_status_is_reference_only": True,
                "active_execution_authority": False,
                "executor_authority": False,
                "route_transition_authority": False,
                "delivery_state_authority": False,
                "review_acceptance_authority": False,
                "freeze_candidate_implies_accepted": False,
            },
            "project_final_goal_ref": {
                "source_document": "PROJECT_MASTER_TASKBOOK.md",
                "field_name": "project_final_goal",
                "authority_boundary": "hash_bound_reference_only",
            },
            "source_stage_taskbook_ref": {
                "path": "docs/taskbooks/stages/STAGE_01_MASTER_TASKBOOK_ANCHORING.md",
                "raw_snapshot_sha256": sha256_file(self.stage_taskbook),
                "stage_id": "stage_01_master_taskbook_anchoring",
            },
            "source_version_taskbook_ref": {
                "path": "docs/taskbooks/versions/stage-01/VERSION_STAGE_01_V1_1_MASTER_TASKBOOK_REGISTRY_V1.md",
                "raw_snapshot_sha256": sha256_file(self.version_taskbook),
                "version_id": "stage_01_v1_1_master_taskbook_registry_v1",
            },
            "observed_git_head": "c" * 40,
            "observed_origin_main_local_tracking_ref": "d" * 40,
            "ahead_behind_from_local_refs": {
                "ahead": 48,
                "behind": 0,
                "source": "git rev-list --left-right --count origin/main...HEAD",
            },
            "live_remote_status_not_validated": True,
            "mutation_boundary": {
                "master_taskbook_mutation_allowed": False,
                "registry_can_mutate_master": False,
                "requires_separate_hash_specific_authorization": True,
            },
            "forbidden_authority_claims": [
                "master_is_active_execution_authority",
                "master_is_accepted_delivery_state",
                "freeze_candidate_implies_executor_authority",
                "registry_record_can_mutate_master",
                "registry_record_can_override_delivery_state_gate",
            ],
            "created_at": "2026-06-29T00:00:00+08:00",
        }

    def write_record(self, record: dict) -> None:
        self.registry_path.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")

    def assert_registry_error(self, record: dict, code: str) -> MasterTaskbookRegistryError:
        self.write_record(record)
        with self.assertRaises(MasterTaskbookRegistryError) as raised:
            load_master_taskbook_registry(
                self.project,
                self.registry_path,
                expected_source_refs=self.expected_source_refs(),
            )
        assert raised.exception.error_code == code
        return raised.exception

    def test_valid_registry_loads_and_verifies_master_hash(self) -> None:
        record = self.valid_record()
        self.write_record(record)

        result = load_master_taskbook_registry(
            self.project,
            self.registry_path,
            expected_source_refs=self.expected_source_refs(),
        )

        assert result["ok"] is True
        assert result["master_hash_verified"] is True
        assert result["master_expected_sha256"] == sha256_file(self.master)
        assert result["master_actual_sha256"] == sha256_file(self.master)
        assert result["record"]["master_authority_boundary"]["active_execution_authority"] is False

    def test_missing_required_field_fails_closed(self) -> None:
        record = self.valid_record()
        del record["master_review_status"]

        error = self.assert_registry_error(record, "REQUIRED_FIELD_MISSING")

        assert error.details["missing_fields"] == ["master_review_status"]

    def test_master_hash_mismatch_fails_closed(self) -> None:
        record = self.valid_record()
        record["master_raw_snapshot_sha256"] = "0" * 64

        error = self.assert_registry_error(record, "MASTER_HASH_MISMATCH")

        assert error.details["expected"] == "0" * 64
        assert error.details["actual"] == sha256_file(self.master)

    def test_active_master_authority_claim_fails_closed(self) -> None:
        record = self.valid_record()
        record["master_authority_boundary"]["active_execution_authority"] = True

        error = self.assert_registry_error(record, "FORBIDDEN_AUTHORITY_CLAIM")

        assert error.details["path"] == "record.master_authority_boundary.active_execution_authority"

    def test_registry_cannot_claim_master_mutation_power(self) -> None:
        record = self.valid_record()
        record["mutation_boundary"]["registry_can_mutate_master"] = True

        error = self.assert_registry_error(record, "FORBIDDEN_AUTHORITY_CLAIM")

        assert error.details["path"] == "record.mutation_boundary.registry_can_mutate_master"

    def test_master_path_must_stay_inside_project(self) -> None:
        record = self.valid_record()
        record["master_taskbook_path"] = "../PROJECT_MASTER_TASKBOOK.md"

        self.assert_registry_error(record, "PATH_OUTSIDE_PROJECT")

    def test_invalid_live_remote_boundary_fails_closed(self) -> None:
        record = copy.deepcopy(self.valid_record())
        record["live_remote_status_not_validated"] = False

        self.assert_registry_error(record, "REMOTE_STATUS_BOUNDARY_INVALID")

    def test_wrong_schema_version_fails_closed(self) -> None:
        record = self.valid_record()
        record["schema_version"] = "master_taskbook_registry.v0"

        error = self.assert_registry_error(record, "FIELD_VALUE_UNSUPPORTED")

        assert error.details["field"] == "schema_version"

    def test_wrong_registry_record_id_fails_closed(self) -> None:
        record = self.valid_record()
        record["registry_record_id"] = "master_taskbook.other"

        error = self.assert_registry_error(record, "FIELD_VALUE_UNSUPPORTED")

        assert error.details["field"] == "registry_record_id"

    def test_project_final_goal_ref_must_match_exact_boundary(self) -> None:
        record = self.valid_record()
        record["project_final_goal_ref"]["authority_boundary"] = "active_authority"

        error = self.assert_registry_error(record, "OBJECT_FIELD_VALUE_UNSUPPORTED")

        assert error.details["field"] == "project_final_goal_ref"
        assert error.details["key"] == "authority_boundary"

    def test_extra_authority_claim_fails_closed(self) -> None:
        record = self.valid_record()
        record["master_authority_boundary"]["delivery_state_accepted"] = True

        error = self.assert_registry_error(record, "FORBIDDEN_AUTHORITY_CLAIM")

        assert error.details["path"] == "record.master_authority_boundary.delivery_state_accepted"

    def test_unknown_top_level_field_fails_closed(self) -> None:
        record = self.valid_record()
        record["delivery_state_accepted"] = True

        error = self.assert_registry_error(record, "UNSUPPORTED_REGISTRY_FIELD")

        assert error.details["unsupported_fields"] == ["delivery_state_accepted"]

    def test_source_ref_must_match_exact_path_hash_and_id(self) -> None:
        record = self.valid_record()
        record["source_stage_taskbook_ref"]["stage_id"] = "stage_99_wrong"

        error = self.assert_registry_error(record, "OBJECT_FIELD_VALUE_UNSUPPORTED")

        assert error.details["field"] == "source_stage_taskbook_ref"
        assert error.details["key"] == "stage_id"

    def test_source_ref_actual_file_hash_mismatch_fails_closed(self) -> None:
        record = self.valid_record()
        expected_source_refs = self.expected_source_refs()
        self.write_record(record)
        self.stage_taskbook.write_text("# Changed after registry creation\n", encoding="utf-8")

        with self.assertRaises(MasterTaskbookRegistryError) as raised:
            load_master_taskbook_registry(
                self.project,
                self.registry_path,
                expected_source_refs=expected_source_refs,
            )

        assert raised.exception.error_code == "SOURCE_REF_HASH_MISMATCH"

    def test_default_registry_path_symlink_escape_fails_closed(self) -> None:
        outside = self.project.parent / f"{self.project.name}-outside-registry.json"
        outside.write_text(json.dumps(self.valid_record()), encoding="utf-8")
        self.registry_path.symlink_to(outside)

        with self.assertRaises(MasterTaskbookRegistryError) as raised:
            load_master_taskbook_registry(
                self.project,
                expected_source_refs=self.expected_source_refs(),
            )

        assert raised.exception.error_code == "PATH_OUTSIDE_PROJECT"


if __name__ == "__main__":
    unittest.main()
