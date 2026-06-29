from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from runner.master_taskbook_reader import (
    FORBIDDEN_READER_RESULT_FIELDS,
    MasterTaskbookReaderError,
    read_master_taskbook,
)
from runner.master_taskbook_registry import sha256_file


class MasterTaskbookReaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="colameta-master-reader-")
        self.project = Path(self._tmp.name)
        self.master = self.project / "PROJECT_MASTER_TASKBOOK.md"
        self.master.write_bytes(b"# Master\r\n\r\ncustom_body: no semantic validation here\r\n")
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
        self.write_registry()

    def tearDown(self) -> None:
        self._tmp.cleanup()

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

    def registry_record(self) -> dict:
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
                "ahead": 49,
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

    def write_registry(self, record: dict | None = None) -> None:
        payload = record if record is not None else self.registry_record()
        self.registry_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def read(self) -> dict:
        return read_master_taskbook(
            self.project,
            registry_path=self.registry_path,
            observed_git_head="e" * 40,
            expected_source_refs=self.expected_source_refs(),
        )

    def test_reader_loads_registry_and_master_content_without_authority_fields(self) -> None:
        result = self.read()

        assert result["registry_record_id"] == "master_taskbook.current"
        assert result["master_taskbook_path"] == "PROJECT_MASTER_TASKBOOK.md"
        assert result["resolved_master_taskbook_path"] == str(self.master.resolve())
        assert result["path_within_repository"] is True
        assert result["raw_content_sha256"] == sha256_file(self.master)
        assert result["raw_content"] == self.master.read_bytes().decode("utf-8")
        assert "\r\n" in result["raw_content"]
        assert result["observed_file_size_bytes"] == len(self.master.read_bytes())
        assert result["observed_git_head"] == "e" * 40
        assert result["registry_review_status_boundary"] == "freeze_candidate_confirmed_for_exact_hash"
        assert result["read_status"] == "read_ok"
        assert result["failure_reason_or_none"] is None
        assert not (set(result) & FORBIDDEN_READER_RESULT_FIELDS)

    def test_reader_does_not_validate_project_final_goal_semantics(self) -> None:
        self.master.write_text("# Master\n\nthis file intentionally has no final goal field\n", encoding="utf-8")
        record = self.registry_record()
        self.write_registry(record)

        result = self.read()

        assert "project_final_goal" not in result["raw_content"]
        assert result["raw_content_sha256"] == sha256_file(self.master)

    def test_missing_registry_fails_closed_without_creating_it(self) -> None:
        self.registry_path.unlink()

        with self.assertRaises(MasterTaskbookReaderError) as raised:
            self.read()

        assert raised.exception.error_code == "REGISTRY_READ_FAILED"
        assert raised.exception.details["upstream_error_code"] == "REGISTRY_FILE_MISSING"
        assert not self.registry_path.exists()

    def test_master_path_escape_fails_closed(self) -> None:
        record = self.registry_record()
        record["master_taskbook_path"] = "../PROJECT_MASTER_TASKBOOK.md"
        self.write_registry(record)

        with self.assertRaises(MasterTaskbookReaderError) as raised:
            self.read()

        assert raised.exception.error_code == "REGISTRY_READ_FAILED"
        assert raised.exception.details["upstream_error_code"] == "PATH_OUTSIDE_PROJECT"

    def test_master_hash_mismatch_fails_closed(self) -> None:
        self.master.write_text("# Mutated after registry write\n", encoding="utf-8")

        with self.assertRaises(MasterTaskbookReaderError) as raised:
            self.read()

        assert raised.exception.error_code == "REGISTRY_READ_FAILED"
        assert raised.exception.details["upstream_error_code"] == "MASTER_HASH_MISMATCH"

    def test_reader_is_read_only_for_master_and_registry(self) -> None:
        master_before = sha256_file(self.master)
        registry_before = sha256_file(self.registry_path)

        self.read()

        assert sha256_file(self.master) == master_before
        assert sha256_file(self.registry_path) == registry_before


if __name__ == "__main__":
    unittest.main()
