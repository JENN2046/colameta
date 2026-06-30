from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path


class RunnerCliServiceStatusDiscoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="colameta-status-discovery-")
        self.tmp_path = Path(self._tmp.name)
        self.project = self.tmp_path / "managed-project"
        self.project.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def stable_serve_cmdline(self) -> list[str]:
        return [
            "/home/jenn/tools/colameta/.venv/bin/python",
            ".venv/bin/colameta",
            "serve",
            str(self.project),
            "--web-host",
            "127.0.0.1",
            "--web-port",
            "8801",
            "--mcp-host",
            "127.0.0.1",
            "--mcp-port",
            "8766",
            "--auth-mode",
            "none",
        ]

    def test_direct_stable_serve_cmdline_builds_status_metadata_without_secrets(self) -> None:
        from scripts import runner_cli

        metadata = runner_cli._metadata_from_colameta_service_cmdline(
            pid=12345,
            project_path=str(self.project),
            cmdline_parts=self.stable_serve_cmdline(),
        )

        assert metadata is not None
        assert metadata["pid"] == 12345
        assert metadata["project_root"] == str(self.project)
        assert metadata["web_url"] == "http://127.0.0.1:8801"
        assert metadata["mcp_url"] == "http://127.0.0.1:8766/mcp"
        assert metadata["enable_web"] is True
        assert metadata["enable_mcp"] is True
        assert metadata["register_as_selected"] is True
        assert metadata["command_kind"] == "serve"
        assert "command" not in metadata
        assert "auth_token" not in metadata

    def test_direct_serve_discovery_requires_matching_project_path(self) -> None:
        from scripts import runner_cli

        other_project = self.tmp_path / "other-project"
        other_project.mkdir()

        metadata = runner_cli._metadata_from_colameta_service_cmdline(
            pid=12345,
            project_path=str(other_project),
            cmdline_parts=self.stable_serve_cmdline(),
        )

        assert metadata is None

    def test_discovery_prefers_registered_service_over_no_register_test_service(self) -> None:
        from scripts import runner_cli

        test_cmdline = [
            "python3",
            "scripts/runner_cli.py",
            "serve",
            str(self.project),
            "--web-port",
            "8802",
            "--mcp-port",
            "8767",
            "--no-register-selected",
        ]
        stable_cmdline = self.stable_serve_cmdline()
        originals = {
            "_iter_process_ids": runner_cli._iter_process_ids,
            "_is_pid_running": runner_cli._is_pid_running,
            "_read_process_cmdline_parts": runner_cli._read_process_cmdline_parts,
        }
        runner_cli._iter_process_ids = lambda: [1425587, 1685173]
        runner_cli._is_pid_running = lambda pid: pid in {1425587, 1685173}
        runner_cli._read_process_cmdline_parts = lambda pid: {
            1425587: test_cmdline,
            1685173: stable_cmdline,
        }.get(pid)
        try:
            metadata = runner_cli._discover_running_service_metadata(str(self.project))
        finally:
            for name, original in originals.items():
                setattr(runner_cli, name, original)

        assert metadata is not None
        assert metadata["pid"] == 1685173
        assert metadata["web_url"] == "http://127.0.0.1:8801"
        assert metadata["mcp_url"] == "http://127.0.0.1:8766/mcp"

    def test_status_falls_back_to_direct_serve_process_when_metadata_is_missing(self) -> None:
        from scripts import runner_cli

        originals = {
            "_read_service_metadata": runner_cli._read_service_metadata,
            "_iter_process_ids": runner_cli._iter_process_ids,
            "_is_pid_running": runner_cli._is_pid_running,
            "_read_process_cmdline_parts": runner_cli._read_process_cmdline_parts,
            "_is_runner_web_console": runner_cli._is_runner_web_console,
            "_is_runner_mcp_server": runner_cli._is_runner_mcp_server,
        }
        runner_cli._read_service_metadata = lambda project_path: None
        runner_cli._iter_process_ids = lambda: [12345]
        runner_cli._is_pid_running = lambda pid: pid == 12345
        runner_cli._read_process_cmdline_parts = (
            lambda pid: self.stable_serve_cmdline() if pid == 12345 else None
        )
        runner_cli._is_runner_web_console = lambda host, port, timeout=3: (host, port) == ("127.0.0.1", 8801)
        runner_cli._is_runner_mcp_server = lambda host, port, timeout=3: (host, port) == ("127.0.0.1", 8766)
        stderr = io.StringIO()
        try:
            with contextlib.redirect_stderr(stderr):
                rc = runner_cli._run_service_status(["status", str(self.project)])
        finally:
            for name, original in originals.items():
                setattr(runner_cli, name, original)

        assert rc == 0
        output = stderr.getvalue()
        assert f"Project: {self.project}" in output
        assert "Status: running" in output
        assert "PID: 12345" in output
        assert "Web Console: http://127.0.0.1:8801 (healthy)" in output
        assert "MCP Endpoint: http://127.0.0.1:8766/mcp (healthy)" in output
