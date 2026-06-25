from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
import tempfile
import unittest
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "runner_cli.py"
HOST = "127.0.0.1"
STARTUP_TIMEOUT_SECONDS = 12.0
PORT_RELEASE_TIMEOUT_SECONDS = 5.0
TOKEN = "colameta-e02-test-token"


def free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((HOST, 0))
        return int(sock.getsockname()[1])


def is_port_bindable(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((HOST, port))
        except OSError:
            return False
    return True


def wait_until_port_released(port: int, timeout_seconds: float = PORT_RELEASE_TIMEOUT_SECONDS) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if is_port_bindable(port):
            return True
        time.sleep(0.05)
    return is_port_bindable(port)


def isolated_env(tmp_path: Path) -> dict[str, str]:
    home = tmp_path / "home"
    xdg_config = tmp_path / "xdg-config"
    home.mkdir(exist_ok=True)
    xdg_config.mkdir(exist_ok=True)
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(xdg_config),
            "PYTHONNOUSERSITE": "1",
            "PYTHONUNBUFFERED": "1",
            "NO_PROXY": "127.0.0.1,localhost",
            "no_proxy": "127.0.0.1,localhost",
        }
    )
    return env


def json_request(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    token: str | None = None,
    timeout: float = 2.0,
) -> tuple[int, dict[str, Any]]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Accept": "application/json"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return int(response.status), json.loads(raw)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        return int(exc.code), json.loads(raw)


def wait_for_json(url: str, service: "ServiceProcess", expected_service: str) -> dict[str, Any]:
    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if service.process.poll() is not None:
            raise AssertionError(f"service exited during startup\n{service.log_text()}")
        try:
            status, payload = json_request(url, timeout=0.5)
            if status == 200 and payload.get("service") == expected_service:
                return payload
        except Exception as exc:
            last_error = exc
        time.sleep(0.1)
    raise AssertionError(f"timed out waiting for {url}: {last_error}\n{service.log_text()}")


@dataclass
class ServiceProcess:
    process: subprocess.Popen[bytes]
    command: list[str]
    log_path: Path
    web_port: int | None
    mcp_port: int

    def log_text(self) -> str:
        if not self.log_path.exists():
            return "<service log missing>"
        return self.log_path.read_text(encoding="utf-8", errors="replace")[-6000:]

    def stop(self) -> None:
        if self.process.poll() is None:
            if os.name == "nt":
                self.process.terminate()
            else:
                os.killpg(self.process.pid, signal.SIGTERM)
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                if os.name == "nt":
                    self.process.kill()
                else:
                    os.killpg(self.process.pid, signal.SIGKILL)
                self.process.wait(timeout=5)

        ports = [self.mcp_port]
        if self.web_port is not None:
            ports.append(self.web_port)
        unreleased = [port for port in ports if not wait_until_port_released(port)]
        assert unreleased == [], f"ports not released: {unreleased}\n{self.log_text()}"


def start_service(
    tmp_path: Path,
    project: Path,
    mode: str,
    *,
    web_port: int | None,
    mcp_port: int,
) -> ServiceProcess:
    log_path = tmp_path / f"{mode}-service.log"
    command = [
        sys.executable,
        str(CLI),
        str(project),
        mode,
        "--mcp-host",
        HOST,
        "--mcp-port",
        str(mcp_port),
        "--auth-mode",
        "token",
        "--auth-token",
        TOKEN,
        "--public-base-url",
        f"http://{HOST}:{mcp_port}",
    ]
    if web_port is not None:
        command.extend(["--web-host", HOST, "--web-port", str(web_port)])

    assert "0.0.0.0" not in command
    log_handle = log_path.open("wb")
    try:
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            env=isolated_env(tmp_path),
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=(os.name != "nt"),
            close_fds=True,
        )
    finally:
        log_handle.close()
    return ServiceProcess(process=process, command=command, log_path=log_path, web_port=web_port, mcp_port=mcp_port)


def initialize_payload() -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}


def assert_token_auth_flow(service: ServiceProcess) -> None:
    url = f"http://{HOST}:{service.mcp_port}/mcp"

    status, payload = json_request(url, method="POST", payload=initialize_payload())
    assert status == 401
    assert payload["error_code"] == "UNAUTHORIZED"

    status, payload = json_request(url, method="POST", payload=initialize_payload(), token="wrong-token")
    assert status == 401
    assert payload["error_code"] == "UNAUTHORIZED"

    status, payload = json_request(url, method="POST", payload=initialize_payload(), token=TOKEN)
    assert status == 200
    assert payload["jsonrpc"] == "2.0"
    assert payload["result"]["serverInfo"]["name"] == "colameta-mcp"


class ServiceAuthBaselineTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="colameta-service-test-")
        self.tmp_path = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_managed_service_web_mcp_token_auth_and_port_cleanup(self) -> None:
        project = self.tmp_path / "managed-project"
        project.mkdir()
        web_port = free_tcp_port()
        mcp_port = free_tcp_port()
        service = start_service(self.tmp_path, project, "managed", web_port=web_port, mcp_port=mcp_port)

        try:
            web_health = wait_for_json(f"http://{HOST}:{web_port}/api/healthz", service, "colameta-web-console")
            assert web_health["ok"] is True

            mcp_health = wait_for_json(f"http://{HOST}:{mcp_port}/healthz", service, "colameta-mcp")
            assert mcp_health["ok"] is True
            assert mcp_health["auth_mode"] == "token"
            assert mcp_health["routing"] == "registry"

            assert (project / ".colameta" / "plan.json").is_file()
            assert_token_auth_flow(service)
        finally:
            service.stop()

        assert service.process.poll() is not None
        assert is_port_bindable(web_port)
        assert is_port_bindable(mcp_port)

    def test_source_only_service_mcp_token_auth_and_port_cleanup(self) -> None:
        project = self.tmp_path / "source-only-project"
        project.mkdir()
        mcp_port = free_tcp_port()
        service = start_service(self.tmp_path, project, "source-only", web_port=None, mcp_port=mcp_port)

        try:
            mcp_health = wait_for_json(f"http://{HOST}:{mcp_port}/healthz", service, "colameta-mcp")
            assert mcp_health["ok"] is True
            assert mcp_health["auth_mode"] == "token"
            assert mcp_health["project"] == str(project)
            assert not (project / ".colameta").exists()

            assert_token_auth_flow(service)
        finally:
            service.stop()

        assert service.process.poll() is not None
        assert is_port_bindable(mcp_port)
