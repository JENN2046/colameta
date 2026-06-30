from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from runner.workflow_records import WorkflowRecordStore


class WorkflowRecordStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="colameta-workflow-records-")
        self.project_root = Path(self._tmp.name)
        self.store = WorkflowRecordStore(str(self.project_root))
        Path(self.store.workflows_dir).mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write_record(
        self,
        filename: str,
        *,
        workflow_id: str,
        workflow_name: str,
        created_at: str,
        status: str = "succeeded",
    ) -> None:
        payload = {
            "workflow_id": workflow_id,
            "workflow_name": workflow_name,
            "created_at": created_at,
            "updated_at": created_at,
            "finished_at": created_at,
            "status": status,
            "risk_level": "info",
            "tool_name": workflow_name,
            "stop_reason": "completed",
            "preview_ids": [],
            "changed_files": [],
            "steps": [],
        }
        (Path(self.store.workflows_dir) / filename).write_text(
            json.dumps(payload),
            encoding="utf-8",
        )

    def test_list_runs_sorts_by_created_at_desc_before_limit(self) -> None:
        self.write_record(
            "zzzz_old.json",
            workflow_id="old",
            workflow_name="run_mcp_workflow",
            created_at="2026-06-30T01:00:00Z",
        )
        self.write_record(
            "aaaa_new.json",
            workflow_id="new",
            workflow_name="run_mcp_workflow",
            created_at="2026-06-30T03:00:00Z",
        )
        self.write_record(
            "mmmm_middle.json",
            workflow_id="middle",
            workflow_name="run_mcp_workflow",
            created_at="2026-06-30T02:00:00Z",
        )

        result = self.store.list_runs(limit=2)

        assert result["ok"] is True
        assert [item["workflow_id"] for item in result["runs"]] == ["new", "middle"]

    def test_list_runs_filters_then_sorts_by_created_at_desc(self) -> None:
        self.write_record(
            "zzzz_old_match.json",
            workflow_id="old-match",
            workflow_name="manage_validation_run",
            created_at="2026-06-30T01:00:00Z",
        )
        self.write_record(
            "aaaa_other_newer.json",
            workflow_id="other-newer",
            workflow_name="run_mcp_workflow",
            created_at="2026-06-30T04:00:00Z",
        )
        self.write_record(
            "bbbb_new_match.json",
            workflow_id="new-match",
            workflow_name="manage_validation_run",
            created_at="2026-06-30T03:00:00Z",
        )

        result = self.store.list_runs(limit=1, workflow_name="manage_validation_run")

        assert result["ok"] is True
        assert [item["workflow_id"] for item in result["runs"]] == ["new-match"]


if __name__ == "__main__":
    unittest.main()
