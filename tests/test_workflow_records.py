from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from runner.mcp_server import MCPPlanningBridgeServer
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

    def test_executor_record_boundary_redacts_pair_aliases_before_persist_and_retrieval(self) -> None:
        server = MCPPlanningBridgeServer(str(self.project_root))
        authority_id = "a" * 32
        admission_sha256 = "b" * 64
        params = {
            "action": "status",
            "executor_authority_id": authority_id,
            "admission_sha256": admission_sha256,
            "reason": f"copied={authority_id}",
            "nested": [
                {"authority_alias": authority_id, authority_id: "private key"},
                f"digest_alias={admission_sha256}",
            ],
            "fresh_authority_pair_present": True,
        }
        result = {
            "ok": False,
            "status": "blocked",
            "executor_authority_id": authority_id,
            "admission_sha256": admission_sha256,
            "error_message": f"pair={authority_id}:{admission_sha256}",
            "blockers": [{"nested": [authority_id, admission_sha256], admission_sha256: "private key"}],
            "warnings": [f"copied={admission_sha256}"],
            "fresh_authority_proof": True,
            "fresh_authority_proof_digest": admission_sha256,
        }

        workflow_id = server._record_workflow_if_needed(
            "manage_executor_workflow",
            "status",
            params,
            result,
        )

        assert isinstance(workflow_id, str)
        assert authority_id not in repr(result)
        assert admission_sha256 not in repr(result)
        assert "fresh_authority_proof" not in repr(result)
        raw_path = Path(self.store.workflows_dir) / f"{workflow_id}.json"
        raw_text = raw_path.read_text(encoding="utf-8")
        assert authority_id not in raw_text
        assert admission_sha256 not in raw_text
        assert "fresh_authority_pair_present" not in raw_text
        assert "fresh_authority_proof" not in raw_text

        response = server._handle_jsonrpc_request({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "call_tool",
            "params": {
                "name": "manage_workflow_run",
                "arguments": {"action": "get", "workflow_id": workflow_id},
            },
        })

        assert response is not None
        assert response["result"]["ok"] is True
        assert authority_id not in repr(response)
        assert admission_sha256 not in repr(response)
        assert "fresh_authority_pair_present" not in repr(response)
        assert "fresh_authority_proof" not in repr(response)

    def test_executor_record_uses_exact_success_projection_before_retrieval(self) -> None:
        server = MCPPlanningBridgeServer(str(self.project_root))
        authority_id = "c" * 32
        admission_sha256 = "d" * 64
        params = {"action": "status"}
        result = {
            "ok": True,
            "action": "status",
            "status": "succeeded",
            "risk_level": "info",
            "message": f"copied={authority_id}:{admission_sha256.upper()}",
            "Authority_Alias": authority_id,
            "EXPECTED_ADMISSION_SHA256": admission_sha256,
            "session_status": {
                "status": "ready",
                "AUTHORITY_ID": authority_id,
                "attacker_controlled_extra": {
                    "nested": admission_sha256,
                },
            },
            "project_identity": {"internal": authority_id},
            "attacker_controlled_extra": {
                "nested": [authority_id, admission_sha256],
            },
        }

        workflow_id = server._record_workflow_if_needed(
            "manage_executor_workflow",
            "status",
            params,
            result,
        )

        assert isinstance(workflow_id, str)
        assert result["session_status"] == {"status": "ready"}
        assert "attacker_controlled_extra" not in result
        assert "project_identity" not in result
        raw_path = Path(self.store.workflows_dir) / f"{workflow_id}.json"
        raw_text = raw_path.read_text(encoding="utf-8")
        assert authority_id not in raw_text
        assert admission_sha256 not in raw_text.lower()
        assert "attacker_controlled_extra" not in raw_text
        assert "project_identity" not in raw_text

        response = server._handle_jsonrpc_request({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "get_workflow_run",
                "arguments": {"workflow_id": workflow_id},
            },
        })

        assert response is not None
        serialized = repr(response)
        assert authority_id not in serialized
        assert admission_sha256 not in serialized.lower()
        assert "attacker_controlled_extra" not in serialized
        assert "project_identity" not in serialized


if __name__ == "__main__":
    unittest.main()
