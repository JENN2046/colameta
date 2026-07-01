from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class RunnerCliConnectorRuntimeHealthTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="colameta-runner-cli-health-")
        self.tmp_path = Path(self._tmp.name)
        self.project = self.tmp_path / "managed-project"
        self.project.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_connector_runtime_summary_reports_process_table_source_without_secrets(self) -> None:
        from scripts import runner_cli

        stderr = io.StringIO()
        metadata = {
            "pid": 12345,
            "project_root": str(self.project),
            "web_host": "127.0.0.1",
            "web_port": 8801,
            "mcp_host": "127.0.0.1",
            "mcp_port": 8766,
            "web_url": "http://127.0.0.1:8801",
            "mcp_url": "http://127.0.0.1:8766/mcp",
            "enable_web": True,
            "enable_mcp": True,
            "discovered_from_process_table": True,
        }
        runtime_status = {
            "runtime_loaded_code_stale": False,
            "reload_needed_for_verification": False,
            "reload_awareness_reason": "installed_package_matches_project_checkout",
        }

        with (
            contextlib.redirect_stderr(stderr),
            patch.object(runner_cli, "get_runtime_version_status", return_value=runtime_status),
        ):
            runner_cli._print_connector_runtime_health_summary(
                project_path=str(self.project),
                metadata=metadata,
                state="running",
                web_state="healthy",
                mcp_state="healthy",
            )

        output = stderr.getvalue()
        assert "Connector/runtime: local_service=healthy source=process_table external_connector=unverified" in output
        assert "closeout=local_runtime_ready_external_connector_unverified" in output
        assert "LOCAL_SERVICE_HEALTHY" in output
        assert "WEB_ENDPOINT_HEALTHY" in output
        assert "MCP_ENDPOINT_HEALTHY" in output
        assert "CONNECTOR_HEALTH_UNVERIFIED" in output
        assert "token" not in output.lower()
        assert "secret" not in output.lower()


if __name__ == "__main__":
    unittest.main()
