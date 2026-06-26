from __future__ import annotations

import contextlib
import io
import json
import os
import re
import socket
import secrets
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


HOST = "127.0.0.1"


def free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((HOST, 0))
        return int(sock.getsockname()[1])


def wait_until_port_released(port: int, timeout_seconds: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((HOST, port))
                return True
            except OSError:
                time.sleep(0.05)
    return False


def http_request(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    csrf_token: str | None = None,
    web_read_token: str | None = None,
    authorization: str | None = None,
    origin: str | None = None,
    host_header: str | None = None,
    content_type: str | None = "application/json",
    timeout: float = 2.0,
) -> tuple[int, str]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers: dict[str, str] = {"Accept": "application/json"}
    if payload is not None and content_type is not None:
        headers["Content-Type"] = content_type
    if csrf_token is not None:
        headers["X-ColaMeta-CSRF"] = csrf_token
    if web_read_token is not None:
        headers["X-ColaMeta-Read-Auth"] = web_read_token
    if authorization is not None:
        headers["Authorization"] = authorization
    if origin is not None:
        headers["Origin"] = origin
    if host_header is not None:
        headers["Host"] = host_header
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return int(response.status), response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read().decode("utf-8")


def json_request(url: str, **kwargs: Any) -> tuple[int, dict[str, Any]]:
    status, raw = http_request(url, **kwargs)
    return status, json.loads(raw)


class WebConsoleSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="colameta-web-security-test-")
        self.tmp_path = Path(self._tmp.name)
        self.project = self.tmp_path / "managed-project"
        self.project.mkdir()
        from runner.mcp_runner_plan import ensure_minimal_runner_managed_project

        result = ensure_minimal_runner_managed_project(str(self.project))
        assert result.get("ok") is True
        self.port = free_tcp_port()
        self.server = None
        self.thread: threading.Thread | None = None
        self.server_errors: list[BaseException] = []

    def tearDown(self) -> None:
        if self.server is not None:
            httpd = getattr(self.server, "_httpd", None)
            if httpd is not None:
                with contextlib.suppress(Exception):
                    httpd.shutdown()
        if self.thread is not None:
            self.thread.join(timeout=5)
        assert wait_until_port_released(self.port)
        self._tmp.cleanup()

    def start_web(
        self,
        *,
        host: str = HOST,
        allow_external_web: bool = False,
        web_read_token: str | None = None,
    ) -> None:
        from runner.web_console import WebConsoleServer

        self.server = WebConsoleServer(str(self.project))
        original_switch_executor = self.server._api_switch_executor

        def safe_switch_executor(body: dict[str, Any]) -> dict[str, Any]:
            provider = str((body or {}).get("provider") or "")
            return {"ok": True, "provider": provider}

        self.server._api_switch_executor = safe_switch_executor
        self.addCleanup(lambda: setattr(self.server, "_api_switch_executor", original_switch_executor))

        def run() -> None:
            try:
                self.server.serve_http(
                    host=host,
                    port=self.port,
                    allow_external_web=allow_external_web,
                    web_read_token=web_read_token,
                )
            except BaseException as exc:  # noqa: BLE001 - surfaced to the test thread
                self.server_errors.append(exc)

        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if self.server_errors:
                raise AssertionError(f"web server failed: {self.server_errors[0]}")
            try:
                status, payload = json_request(f"http://{HOST}:{self.port}/api/healthz")
                if status == 200 and payload.get("service") == "colameta-web-console":
                    return
            except Exception:
                time.sleep(0.05)
        raise AssertionError("timed out waiting for web console health")

    def csrf_token_from_page(self) -> str:
        status, body = http_request(f"http://{HOST}:{self.port}/")
        assert status == 200
        match = re.search(r'name="colameta-csrf-token" content="([^"]+)"', body)
        assert match is not None
        return match.group(1)

    def read_token_from_page(self) -> str:
        status, body = http_request(f"http://{HOST}:{self.port}/")
        assert status == 200
        match = re.search(r'name="colameta-web-read-auth" content="([^"]*)"', body)
        assert match is not None
        return match.group(1)

    def valid_origin(self) -> str:
        return f"http://{HOST}:{self.port}"

    def valid_host(self) -> str:
        return f"{HOST}:{self.port}"

    def dangerous_preview(self, route: str, payload: dict[str, Any]) -> str:
        csrf = self.csrf_token_from_page()
        status, preview = json_request(
            f"http://{HOST}:{self.port}/api/dangerous-action/preview",
            method="POST",
            payload={"route": route, "payload": payload},
            csrf_token=csrf,
            origin=self.valid_origin(),
            host_header=self.valid_host(),
        )
        assert status == 200
        assert preview["ok"] is True
        confirmation_id = preview.get("confirmation_id")
        assert isinstance(confirmation_id, str)
        assert confirmation_id
        return confirmation_id

    def create_registered_managed_project(self, name: str) -> Path:
        from runner.mcp_runner_plan import ensure_minimal_runner_managed_project

        project = self.tmp_path / name
        project.mkdir()
        result = ensure_minimal_runner_managed_project(str(project))
        assert result.get("ok") is True
        assert self.server is not None
        registered = self.server.project_registry.register_project(
            str(project),
            project_name=name,
            last_selected=False,
        )
        assert registered.get("ok") is True
        return project

    def test_health_and_ui_shell_remain_public_without_project_state(self) -> None:
        self.start_web()

        status, health = json_request(f"http://{HOST}:{self.port}/api/healthz")
        assert status == 200
        assert health["ok"] is True

        status, v2_health = json_request(f"http://{HOST}:{self.port}/api/v2/health")
        assert status == 200
        assert v2_health["ok"] is True

        status, body = http_request(f"http://{HOST}:{self.port}/")
        assert status == 200
        assert str(self.project) not in body
        assert ".colameta" not in body

    def test_sensitive_get_without_read_auth_is_rejected(self) -> None:
        self.start_web()

        status, payload = json_request(f"http://{HOST}:{self.port}/api/project-registry")
        assert status == 403
        assert payload["error_code"] == "WEB_READ_AUTH_REQUIRED"

    def test_sensitive_get_with_invalid_read_auth_is_rejected(self) -> None:
        self.start_web()

        status, payload = json_request(
            f"http://{HOST}:{self.port}/api/project-registry",
            web_read_token="invalid-read-auth-token",
        )
        assert status == 403
        assert payload["error_code"] == "WEB_READ_AUTH_INVALID"

    def test_sensitive_get_with_valid_web_read_auth_succeeds(self) -> None:
        self.start_web()
        read_token = self.read_token_from_page()

        status, registry = json_request(
            f"http://{HOST}:{self.port}/api/project-registry",
            web_read_token=read_token,
        )
        assert status == 200
        assert registry.get("ok") is True

    def test_high_sensitivity_read_routes_require_web_read_auth(self) -> None:
        self.start_web()
        read_token = self.read_token_from_page()

        status, payload = json_request(f"http://{HOST}:{self.port}/api/log-tail")
        assert status == 403
        assert payload["error_code"] == "WEB_READ_AUTH_REQUIRED"

        status, payload = json_request(f"http://{HOST}:{self.port}/api/v2/status")
        assert status == 403
        assert payload["error_code"] == "WEB_READ_AUTH_REQUIRED"

        status, payload = json_request(
            f"http://{HOST}:{self.port}/api/v2/status",
            authorization=f"Bearer {read_token}",
        )
        assert status == 200
        assert payload.get("ok") is True

    def test_missing_csrf_on_write_route_is_rejected(self) -> None:
        self.start_web()

        status, payload = json_request(
            f"http://{HOST}:{self.port}/api/switch-executor",
            method="POST",
            payload={"provider": "codex"},
            origin=self.valid_origin(),
            host_header=self.valid_host(),
        )

        assert status == 403
        assert payload["error_code"] == "WEB_CSRF_INVALID"

    def test_invalid_csrf_on_write_route_is_rejected(self) -> None:
        self.start_web()

        status, payload = json_request(
            f"http://{HOST}:{self.port}/api/switch-executor",
            method="POST",
            payload={"provider": "codex"},
            csrf_token="invalid-csrf-token",
            origin=self.valid_origin(),
            host_header=self.valid_host(),
        )

        assert status == 403
        assert payload["error_code"] == "WEB_CSRF_INVALID"

    def test_valid_csrf_origin_and_host_allow_safe_stubbed_write_route(self) -> None:
        self.start_web()
        csrf = self.csrf_token_from_page()
        payload_body = {"provider": "codex"}
        confirmation_id = self.dangerous_preview("/api/switch-executor", payload_body)

        status, payload = json_request(
            f"http://{HOST}:{self.port}/api/switch-executor",
            method="POST",
            payload={**payload_body, "confirmation_id": confirmation_id},
            csrf_token=csrf,
            origin=self.valid_origin(),
            host_header=self.valid_host(),
        )

        assert status == 200
        assert payload["ok"] is True
        assert payload["provider"] == "codex"
        receipt = payload.get("dangerous_action_receipt")
        assert receipt["confirmation_validated"] is True
        assert receipt["confirmation_id"] == "REDACTED"

    def test_valid_csrf_without_dangerous_confirmation_is_rejected(self) -> None:
        self.start_web()
        csrf = self.csrf_token_from_page()

        status, payload = json_request(
            f"http://{HOST}:{self.port}/api/switch-executor",
            method="POST",
            payload={"provider": "codex"},
            csrf_token=csrf,
            origin=self.valid_origin(),
            host_header=self.valid_host(),
        )

        assert status == 403
        assert payload["error_code"] == "DANGEROUS_CONFIRMATION_REQUIRED"

    def test_invalid_origin_is_rejected(self) -> None:
        self.start_web()
        csrf = self.csrf_token_from_page()

        status, payload = json_request(
            f"http://{HOST}:{self.port}/api/switch-executor",
            method="POST",
            payload={"provider": "codex"},
            csrf_token=csrf,
            origin="https://example.invalid",
            host_header=self.valid_host(),
        )

        assert status == 403
        assert payload["error_code"] == "WEB_ORIGIN_INVALID"

    def test_invalid_host_is_rejected(self) -> None:
        self.start_web()
        csrf = self.csrf_token_from_page()

        status, payload = json_request(
            f"http://{HOST}:{self.port}/api/switch-executor",
            method="POST",
            payload={"provider": "codex"},
            csrf_token=csrf,
            origin=self.valid_origin(),
            host_header="example.invalid",
        )

        assert status == 403
        assert payload["error_code"] == "WEB_HOST_INVALID"

    def test_wrong_content_type_is_rejected_for_json_write_route(self) -> None:
        self.start_web()
        csrf = self.csrf_token_from_page()

        status, payload = json_request(
            f"http://{HOST}:{self.port}/api/switch-executor",
            method="POST",
            payload={"provider": "codex"},
            csrf_token=csrf,
            origin=self.valid_origin(),
            host_header=self.valid_host(),
            content_type="text/plain",
        )

        assert status == 415
        assert payload["error_code"] == "WEB_CONTENT_TYPE_REQUIRED"

    def test_v2_registry_mutation_path_is_guarded_before_dispatch(self) -> None:
        self.start_web()
        csrf = self.csrf_token_from_page()
        other_project = self.create_registered_managed_project("other-project")

        status, payload = json_request(
            f"http://{HOST}:{self.port}/api/v2/action",
            method="POST",
            payload={
                "next_action": {
                    "action": "project_registry_unregister",
                    "params": {"project_root": str(other_project)},
                }
            },
            csrf_token=csrf,
            origin=self.valid_origin(),
            host_header=self.valid_host(),
        )

        assert status == 403
        assert payload["error_code"] == "DANGEROUS_CONFIRMATION_REQUIRED"
        registry = self.server.project_registry.list_projects()
        assert any(
            project.get("project_root") == str(other_project)
            for project in registry.get("projects", [])
        )

    def test_v2_registry_mutation_with_valid_confirmation_dispatches(self) -> None:
        self.start_web()
        csrf = self.csrf_token_from_page()
        other_project = self.create_registered_managed_project("dispatch-project")
        request_body = {
            "next_action": {
                "action": "project_registry_unregister",
                "params": {"project_root": str(other_project)},
            }
        }
        confirmation_id = self.dangerous_preview("/api/v2/action", request_body)

        status, payload = json_request(
            f"http://{HOST}:{self.port}/api/v2/action",
            method="POST",
            payload={**request_body, "confirmation_id": confirmation_id},
            csrf_token=csrf,
            origin=self.valid_origin(),
            host_header=self.valid_host(),
        )

        assert status == 200
        assert payload["ok"] is True
        assert payload["dangerous_action_receipt"]["confirmation_validated"] is True
        registry = self.server.project_registry.list_projects()
        assert all(
            project.get("project_root") != str(other_project)
            for project in registry.get("projects", [])
        )

    def test_switch_project_requires_correct_target_confirmation(self) -> None:
        self.start_web()
        csrf = self.csrf_token_from_page()
        other_project = self.create_registered_managed_project("switch-target")
        wrong_confirmation = self.dangerous_preview(
            "/api/switch-project",
            {"project_root": str(other_project)},
        )

        status, payload = json_request(
            f"http://{HOST}:{self.port}/api/switch-project",
            method="POST",
            payload={"project_root": str(self.project), "confirmation_id": wrong_confirmation},
            csrf_token=csrf,
            origin=self.valid_origin(),
            host_header=self.valid_host(),
        )

        assert status == 403
        assert payload["error_code"] == "DANGEROUS_CONFIRMATION_PAYLOAD_MISMATCH"

        request_body = {"project_root": str(other_project)}
        confirmation_id = self.dangerous_preview("/api/switch-project", request_body)
        status, payload = json_request(
            f"http://{HOST}:{self.port}/api/switch-project",
            method="POST",
            payload={**request_body, "confirmation_id": confirmation_id},
            csrf_token=csrf,
            origin=self.valid_origin(),
            host_header=self.valid_host(),
        )

        assert status == 200
        assert payload["ok"] is True
        assert self.server.project_root == str(other_project)

    def test_switch_executor_requires_correct_target_confirmation(self) -> None:
        self.start_web()
        csrf = self.csrf_token_from_page()
        wrong_confirmation = self.dangerous_preview("/api/switch-executor", {"provider": "codex"})

        status, payload = json_request(
            f"http://{HOST}:{self.port}/api/switch-executor",
            method="POST",
            payload={"provider": "opencode", "confirmation_id": wrong_confirmation},
            csrf_token=csrf,
            origin=self.valid_origin(),
            host_header=self.valid_host(),
        )

        assert status == 403
        assert payload["error_code"] == "DANGEROUS_CONFIRMATION_PAYLOAD_MISMATCH"

        request_body = {"provider": "codex"}
        confirmation_id = self.dangerous_preview("/api/switch-executor", request_body)
        status, payload = json_request(
            f"http://{HOST}:{self.port}/api/switch-executor",
            method="POST",
            payload={**request_body, "confirmation_id": confirmation_id},
            csrf_token=csrf,
            origin=self.valid_origin(),
            host_header=self.valid_host(),
        )

        assert status == 200
        assert payload["ok"] is True
        assert payload["dangerous_action_receipt"]["action_type"] == "switch_executor"

    def test_project_identity_apply_requires_correct_preview_binding(self) -> None:
        self.start_web()
        assert self.server is not None
        original_apply = self.server._api_project_identity_apply

        def safe_apply(body: dict[str, Any] | None) -> dict[str, Any]:
            return {"ok": True, "preview_id_seen": bool((body or {}).get("preview_id"))}

        self.server._api_project_identity_apply = safe_apply
        self.addCleanup(lambda: setattr(self.server, "_api_project_identity_apply", original_apply))
        csrf = self.csrf_token_from_page()
        wrong_confirmation = self.dangerous_preview(
            "/api/project-identity/apply",
            {"preview_id": "preview-a"},
        )

        status, payload = json_request(
            f"http://{HOST}:{self.port}/api/project-identity/apply",
            method="POST",
            payload={"preview_id": "preview-b", "confirmation_id": wrong_confirmation},
            csrf_token=csrf,
            origin=self.valid_origin(),
            host_header=self.valid_host(),
        )

        assert status == 403
        assert payload["error_code"] == "DANGEROUS_CONFIRMATION_PAYLOAD_MISMATCH"

        request_body = {"preview_id": "preview-a"}
        confirmation_id = self.dangerous_preview("/api/project-identity/apply", request_body)
        status, payload = json_request(
            f"http://{HOST}:{self.port}/api/project-identity/apply",
            method="POST",
            payload={**request_body, "confirmation_id": confirmation_id},
            csrf_token=csrf,
            origin=self.valid_origin(),
            host_header=self.valid_host(),
        )

        assert status == 200
        assert payload["ok"] is True
        assert payload["dangerous_action_receipt"]["action_type"] == "project_identity_apply"

    def test_loopback_default_and_external_web_acknowledgement(self) -> None:
        from runner.web_console import WebConsoleServer
        from scripts import runner_cli

        assert runner_cli.DEFAULT_WEB_HOST == "127.0.0.1"
        assert runner_cli._validate_external_web_bind("web", "127.0.0.1", False) is True
        assert runner_cli._validate_external_web_bind("web", "0.0.0.0", True) is True
        assert runner_cli._validate_external_web_read_auth("web", "127.0.0.1", None) is True
        assert runner_cli._validate_external_web_read_auth("web", "0.0.0.0", "configured-read-auth") is True
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            assert runner_cli._validate_external_web_bind("web", "0.0.0.0", False) is False
        assert "--allow-external-web" in stderr.getvalue()
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            assert runner_cli._validate_external_web_read_auth("web", "0.0.0.0", None) is False
        assert "--web-read-token" in stderr.getvalue()

        server = WebConsoleServer(str(self.project))
        with self.assertRaises(ValueError):
            server.serve_http(host="0.0.0.0", port=self.port)
        with self.assertRaises(ValueError):
            server.serve_http(host="0.0.0.0", port=self.port, allow_external_web=True)

    def test_external_bind_with_acknowledgement_and_read_auth_is_accepted(self) -> None:
        read_token = secrets.token_urlsafe(24)
        self.start_web(host="0.0.0.0", allow_external_web=True, web_read_token=read_token)

        status, body = http_request(f"http://{HOST}:{self.port}/")
        assert status == 200
        assert 'name="colameta-web-read-auth" content=""' in body

        status, payload = json_request(f"http://{HOST}:{self.port}/api/project-registry")
        assert status == 403
        assert payload["error_code"] == "WEB_READ_AUTH_REQUIRED"

        status, registry = json_request(
            f"http://{HOST}:{self.port}/api/project-registry",
            web_read_token=read_token,
        )
        assert status == 200
        assert registry.get("ok") is True
