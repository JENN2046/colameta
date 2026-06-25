from __future__ import annotations

import contextlib
import io
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "runner_cli.py"


class RunnerCliStartupBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="colameta-e1a-test-")
        self.tmp_path = Path(self._tmp.name)
        self._old_env = {key: os.environ.get(key) for key in ("HOME", "XDG_CONFIG_HOME", "PYTHONNOUSERSITE")}
        os.environ["HOME"] = str(self.tmp_path / "home")
        os.environ["XDG_CONFIG_HOME"] = str(self.tmp_path / "xdg-config")
        os.environ["PYTHONNOUSERSITE"] = "1"
        Path(os.environ["HOME"]).mkdir(parents=True, exist_ok=True)
        Path(os.environ["XDG_CONFIG_HOME"]).mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        for key, value in self._old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._tmp.cleanup()

    def isolated_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env.update(
            {
                "HOME": str(self.tmp_path / "home"),
                "XDG_CONFIG_HOME": str(self.tmp_path / "xdg-config"),
                "PYTHONNOUSERSITE": "1",
                "PYTHONUNBUFFERED": "1",
                "NO_PROXY": "127.0.0.1,localhost",
                "no_proxy": "127.0.0.1,localhost",
            }
        )
        return env

    def create_managed_project(self, name: str) -> Path:
        project = self.tmp_path / name
        project.mkdir()
        from runner.mcp_runner_plan import ensure_minimal_runner_managed_project

        result = ensure_minimal_runner_managed_project(str(project))
        assert result.get("ok") is True
        return project

    def register_project(self, project: Path, *, last_selected: bool = False) -> None:
        from runner.project_registry import PROJECT_MODE_MANAGED, ProjectRegistry

        ProjectRegistry().register_project(
            str(project),
            project_name=project.name,
            project_mode=PROJECT_MODE_MANAGED,
            last_selected=last_selected,
        )

    def capture_background_start(self, args: list[str]) -> tuple[int, dict[str, object], str]:
        from scripts import runner_cli

        captured: dict[str, object] = {}
        original = runner_cli._run_service_start_from_command

        def fake_start(prepared: dict[str, object]) -> int:
            captured.update(prepared)
            return 0

        stderr = io.StringIO()
        runner_cli._run_service_start_from_command = fake_start
        try:
            with contextlib.redirect_stderr(stderr):
                rc = runner_cli._run_service_start(args)
        finally:
            runner_cli._run_service_start_from_command = original
        return rc, captured, stderr.getvalue()

    def test_start_without_path_uses_last_selected_managed_project(self) -> None:
        from scripts import runner_cli

        first = self.create_managed_project("first-managed")
        selected = self.create_managed_project("selected-managed")
        self.register_project(first)
        self.register_project(selected, last_selected=True)

        rc, prepared, stderr = self.capture_background_start(["start"])

        assert rc == 0, stderr
        assert prepared["project_path"] == str(selected)
        assert prepared["project_path"] != runner_cli._default_service_project_root()
        assert prepared["global_mode"] is False
        assert prepared["register_as_selected"] is True

    def test_start_without_path_uses_single_managed_project_without_selection(self) -> None:
        only = self.create_managed_project("only-managed")
        self.register_project(only)

        rc, prepared, stderr = self.capture_background_start(["start"])

        assert rc == 0, stderr
        assert prepared["project_path"] == str(only)

    def test_start_without_path_blocks_when_no_managed_project_exists(self) -> None:
        rc, prepared, stderr = self.capture_background_start(["start"])

        assert rc == 1
        assert prepared == {}
        assert "未找到可用的已登记 managed 项目" in stderr

    def test_start_without_path_blocks_when_managed_projects_are_ambiguous(self) -> None:
        self.register_project(self.create_managed_project("alpha"))
        self.register_project(self.create_managed_project("beta"))

        rc, prepared, stderr = self.capture_background_start(["start"])

        assert rc == 1
        assert prepared == {}
        assert "多个已登记 managed 项目" in stderr

    def test_explicit_start_project_path_is_preserved(self) -> None:
        project = self.create_managed_project("explicit-start")

        rc, prepared, stderr = self.capture_background_start(["start", str(project), "--no-mcp"])

        assert rc == 0, stderr
        assert prepared["project_path"] == str(project)
        assert prepared["serve_args"][1] == str(project)

    def test_default_start_hosts_are_loopback_and_external_web_requires_ack(self) -> None:
        from scripts import runner_cli

        project = self.create_managed_project("host-defaults")
        prepared = runner_cli._prepare_default_start(
            str(project),
            ["--public-base-url", "http://127.0.0.1:8765"],
        )
        assert prepared is not None
        assert prepared["web_host"] == "127.0.0.1"
        assert prepared["mcp_host"] == "127.0.0.1"

        blocked = runner_cli._prepare_default_start(
            str(project),
            [
                "--web-host",
                "0.0.0.0",
                "--mcp-host",
                "0.0.0.0",
                "--public-base-url",
                "http://127.0.0.1:8765",
            ],
        )
        assert blocked is None

        overridden = runner_cli._prepare_default_start(
            str(project),
            [
                "--web-host",
                "0.0.0.0",
                "--allow-external-web",
                "--mcp-host",
                "0.0.0.0",
                "--public-base-url",
                "http://127.0.0.1:8765",
            ],
        )
        assert overridden is not None
        assert overridden["web_host"] == "0.0.0.0"
        assert overridden["mcp_host"] == "0.0.0.0"
        assert "--allow-external-web" in overridden["serve_args"]

    def test_default_start_summary_separates_web_mcp_and_public_urls(self) -> None:
        from scripts import runner_cli_output

        stderr = io.StringIO()
        runner_cli_output.print_default_start_summary(
            project_path="/tmp/demo",
            web_host="127.0.0.1",
            web_port=8801,
            mcp_host="127.0.0.1",
            mcp_port=8802,
            public_base_url="https://public.example",
            public_base_url_source="cli",
            enable_web=True,
            enable_mcp=True,
            open_web=False,
            stderr=stderr,
        )

        output = stderr.getvalue()
        assert "Web Console: http://127.0.0.1:8801" in output
        assert "MCP Endpoint: http://127.0.0.1:8802/mcp" in output
        assert "Actions API: https://public.example/openapi.json" in output
        assert "Web Console: https://public.example" not in output

    def test_direct_web_command_prints_requested_web_url(self) -> None:
        from runner import web_console
        from scripts import runner_cli

        project = self.create_managed_project("direct-web")
        captured: dict[str, object] = {}
        original = web_console.WebConsoleServer

        class FakeWebConsoleServer:
            def __init__(self, project_path: str):
                captured["project_path"] = project_path

            def validate_project(self) -> None:
                captured["validated"] = True

            def serve_http(self, *, host: str, port: int, allow_external_web: bool = False) -> int:
                captured["host"] = host
                captured["port"] = port
                captured["allow_external_web"] = allow_external_web
                return 0

        web_console.WebConsoleServer = FakeWebConsoleServer
        stderr = io.StringIO()
        try:
            with contextlib.redirect_stderr(stderr):
                rc = runner_cli._run_web_console(["web", str(project), "--host", "127.0.0.2", "--port", "8898"])
        finally:
            web_console.WebConsoleServer = original

        assert rc == 0
        assert captured["project_path"] == str(project)
        assert captured["host"] == "127.0.0.2"
        assert captured["port"] == 8898
        assert captured["allow_external_web"] is False
        assert "MVP Runner Web Console: http://127.0.0.2:8898" in stderr.getvalue()

    def test_explicit_serve_project_path_and_url_reporting_are_preserved(self) -> None:
        project = self.create_managed_project("explicit-serve")
        web_port = free_tcp_port()
        mcp_port = free_tcp_port()
        log_path = self.tmp_path / "serve.log"
        command = [
            sys.executable,
            str(CLI),
            "serve",
            str(project),
            "--web-port",
            str(web_port),
            "--mcp-port",
            str(mcp_port),
            "--auth-mode",
            "none",
            "--public-base-url",
            "https://public.example",
        ]

        with log_path.open("wb") as log_handle:
            process = subprocess.Popen(
                command,
                cwd=ROOT,
                env=self.isolated_env(),
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                start_new_session=(os.name != "nt"),
                close_fds=True,
            )
        try:
            output = wait_for_log(log_path, "Ready. Press Ctrl-C to stop.", process)
            assert f"Project: {project}" in output
            assert f"Web Console: http://127.0.0.1:{web_port}" in output
            assert f"MCP Endpoint: http://127.0.0.1:{mcp_port}/mcp" in output
            assert "Actions API: https://public.example/openapi.json" in output
            assert "Web Console: https://public.example" not in output
        finally:
            stop_process(process)
            assert wait_until_port_released(web_port)
            assert wait_until_port_released(mcp_port)


def free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def is_port_bindable(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def wait_until_port_released(port: int, timeout_seconds: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if is_port_bindable(port):
            return True
        time.sleep(0.05)
    return is_port_bindable(port)


def wait_for_log(log_path: Path, expected: str, process: subprocess.Popen[bytes], timeout_seconds: float = 12.0) -> str:
    deadline = time.monotonic() + timeout_seconds
    last_text = ""
    while time.monotonic() < deadline:
        if log_path.exists():
            last_text = log_path.read_text(encoding="utf-8", errors="replace")
            if expected in last_text:
                return last_text
        if process.poll() is not None:
            raise AssertionError(f"serve exited before expected log line\n{last_text}")
        time.sleep(0.1)
    raise AssertionError(f"timed out waiting for {expected!r}\n{last_text}")


def stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        process.terminate()
    else:
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            process.kill()
        else:
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)
