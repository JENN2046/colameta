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

    def test_status_collects_sanitized_tunnel_evidence_when_explicitly_requested(self) -> None:
        from scripts import runner_cli

        class FakeResponse:
            status = 200

            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
                return False

        stderr = io.StringIO()
        requested_urls: list[str] = []
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
            "discovered_from_process_table": False,
        }
        runtime_status = {
            "runtime_loaded_code_stale": False,
            "reload_needed_for_verification": False,
            "reload_awareness_reason": "installed_package_matches_project_checkout",
        }

        def fake_urlopen(url: str, timeout: float = 0) -> FakeResponse:
            requested_urls.append(url)
            return FakeResponse()

        with (
            contextlib.redirect_stderr(stderr),
            patch.object(runner_cli, "_read_service_metadata", return_value=metadata),
            patch.object(runner_cli, "_is_pid_running", return_value=True),
            patch.object(runner_cli, "_probe_service_health", return_value=("healthy", "healthy")),
            patch.object(runner_cli, "get_runtime_version_status", return_value=runtime_status),
            patch.object(runner_cli.urllib.request, "urlopen", side_effect=fake_urlopen),
        ):
            result = runner_cli._run_service_status(
                [
                    "status",
                    str(self.project),
                    "--tunnel-admin-port",
                    "8080",
                    "--tunnel-pid",
                    "4034",
                ]
            )

        output = stderr.getvalue()
        assert result == 0
        assert requested_urls == ["http://127.0.0.1:8080/healthz", "http://127.0.0.1:8080/readyz"]
        assert "external_connector=healthy" in output
        assert "closeout=connector_closeout_ready" in output
        assert "TUNNEL_CLIENT_HEALTHZ_READY" in output
        assert "TUNNEL_CONTROL_PLANE_READYZ_READY" in output
        assert "evidence=tunnel_admin_probe" in output
        assert "token" not in output.lower()
        assert "secret" not in output.lower()

    def test_status_tunnel_evidence_requires_port_and_pid_together(self) -> None:
        from scripts import runner_cli

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            result = runner_cli._run_service_status(
                ["status", str(self.project), "--with-tunnel-evidence", "--tunnel-admin-port", "8080"]
            )

        output = stderr.getvalue()
        assert result == 1
        assert "--tunnel-admin-port" in output
        assert "--tunnel-pid" in output

    def test_status_tunnel_evidence_rejects_non_loopback_admin_host(self) -> None:
        from scripts import runner_cli

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            result = runner_cli._run_service_status(
                [
                    "status",
                    str(self.project),
                    "--tunnel-admin-host",
                    "example.com",
                    "--tunnel-admin-port",
                    "8080",
                    "--tunnel-pid",
                    "4034",
                ]
            )

        output = stderr.getvalue()
        assert result == 1
        assert "loopback" in output
        assert "example.com" in output


if __name__ == "__main__":
    unittest.main()
