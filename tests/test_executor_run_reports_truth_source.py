from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from runner._internal_utils import write_json_atomic
from runner.executor_run_reports import ExecutorRunReportStore
from runner.mcp_executor_workflow import MCPExecutorWorkflowManager


COMMAND = "python3 -m unittest discover -s tests"


class ExecutorRunReportsTruthSourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="colameta-validation-truth-")
        self.project = Path(self._tmp.name) / "project"
        self.project.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _record_inconsistent_report(self, *, version: str = "v1.8") -> tuple[ExecutorRunReportStore, dict]:
        store = ExecutorRunReportStore(str(self.project))
        result = store.record_report(
            version=version,
            version_name="Validation hardening",
            provider="codex",
            execution_mode="run",
            status="FAILED",
            changed_files=["runner/executor_run_reports.py"],
            summary_validation_results=[f"PASSED: {COMMAND}"],
            summary_validation_command_records=[
                {
                    "command_index": 1,
                    "command": COMMAND,
                    "original_command": COMMAND,
                    "executed_command": COMMAND,
                    "status": "PASSED",
                    "exit_code": 1,
                    "stdout": "collected tests\n",
                    "stderr": "PermissionError: socket denied\n",
                }
            ],
            executor_report_text=f"Executor report: {COMMAND} failed with 38 socket PermissionError errors.",
        )
        assert result["ok"] is True, result
        return store, result

    def test_materialized_executor_and_version_audit_packages_preserve_failed_evidence(self) -> None:
        store, result = self._record_inconsistent_report(version="v1.8")

        run_package = store.get_materialized_audit_package(result["report_id"])["audit_package"]
        version_package = store.get_latest_materialized_version_audit_package("v1.8")["audit_package"]
        for package in (run_package, version_package):
            assert package["validation_status_summary"] == "inconsistent"
            assert package["validation_inconsistent"] is True
            assert package["validation_command_records"][0]["command"] == COMMAND
            assert package["validation_command_records"][0]["exit_code"] == 1
            assert "status_exit_code_mismatch" in package["validation_command_records"][0]["inconsistency_reason"]

        markdown = Path(result["markdown_file"]).read_text(encoding="utf-8")
        assert "exit_code=1" in markdown

    def test_get_audit_package_validation_payload_exposes_truth_fields(self) -> None:
        _, result = self._record_inconsistent_report(version="v1.8-get-audit")
        manager = MCPExecutorWorkflowManager(str(self.project))

        payload = manager.handle(
            "get_audit_package",
            {"report_id": result["report_id"], "section": "validation"},
        )

        assert payload["ok"] is True
        assert payload["summary"]["validation_status_summary"] == "inconsistent"
        assert payload["summary"]["validation_inconsistent"] is True
        validation = payload["validation"]
        assert validation["validation_inconsistent"] is True
        assert validation["validation_command_records"][0]["exit_code"] == 1
        assert validation["validation_command_records"][0]["command"] == COMMAND

    def test_validation_payload_rechecks_old_frozen_passed_audit_against_selected_report_markdown(self) -> None:
        store = ExecutorRunReportStore(str(self.project))
        report_id = "20260626T181106859609Z-codex-07d9ac99"
        version = "v1.7"
        report_dir = Path(store.reports_root) / version
        report_dir.mkdir(parents=True, exist_ok=True)
        report_file = report_dir / f"{report_id}.json"
        report_markdown_file = report_dir / f"{report_id}.md"
        version_audit_file = Path(store.version_audits_root) / f"{version}.audit.json"
        version_audit_file.parent.mkdir(parents=True, exist_ok=True)

        report = {
            "schema_version": "1.0",
            "report_id": report_id,
            "version": version,
            "version_name": "Runtime Version Status Decision Evaluator V1",
            "provider": "codex",
            "execution_mode": "run",
            "status": "completed",
            "json_file": str(report_file),
            "markdown_file": str(report_markdown_file),
            "changed_files": ["runner/runtime_version_decision.py"],
            "summary": {
                "validation_results": [f"PASSED: {COMMAND}"],
                "validation_status_summary": "passed",
                "validation_sample": [f"PASSED: {COMMAND}"],
            },
            "report_markdown": f"`{COMMAND}` failed with PermissionError and exit_code=1.",
        }
        version_audit = {
            "schema_version": "1.0",
            "audit_package_id": f"version_auditpkg_{version}",
            "package_type": "version",
            "package_role": "base_frozen",
            "version": version,
            "latest_report_id": report_id,
            "selected_report_id": report_id,
            "report_ids": [report_id],
            "status": "completed",
            "changed_files": ["runner/runtime_version_decision.py"],
            "validation_status_summary": "passed",
            "validation_sample": [f"PASSED: {COMMAND}"],
            "validation_command_count": 1,
            "validation_failed_command_count": 0,
            "evidence_paths": {
                "selected_report_json_file": str(report_file),
                "selected_report_markdown_file": str(report_markdown_file),
                "version_audit_file": str(version_audit_file),
            },
        }
        write_json_atomic(str(report_file), report)
        report_markdown_file.write_text(report["report_markdown"], encoding="utf-8")
        write_json_atomic(str(version_audit_file), version_audit)

        manager = MCPExecutorWorkflowManager(str(self.project))
        payload = manager.handle("get_audit_package", {"version": version, "section": "validation"})

        assert payload["ok"] is True
        assert payload["summary"]["validation_status_summary"] != "passed"
        assert payload["summary"]["validation_inconsistent"] is True
        validation = payload["validation"]
        assert validation["validation_status_summary"] != "passed"
        assert validation["validation_inconsistent"] is True
        assert validation["validation_command_records"][0]["command"] == COMMAND
        reasons = " ".join(validation["validation_inconsistency_reasons"])
        assert "report_text_failed_same_command" in reasons


if __name__ == "__main__":
    unittest.main()
