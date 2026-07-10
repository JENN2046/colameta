from __future__ import annotations

import contextlib
import inspect
import io
import json
import os
import re
import socket
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from unittest.mock import patch


HOST = "127.0.0.1"


class WebRemoteGitMutationPolicyBaselineTests(unittest.TestCase):
    REPRESENTATIVE_PROHIBITED_REMOTE_GIT_PATHS = (
        "/api/git/push",
        "/api/git/push/apply",
        "/api/git-push-apply",
        "/api/git-remote/push",
        "/api/git-remote/push-apply",
        "/api/remote-git/push",
        "/api/remote-git/push-apply",
        "/api/remote-git/fetch-preview",
        "/api/remote-git/fetch-apply",
        "/api/remote-git/pull-preview",
        "/api/remote-git/pull-apply",
        "/api/push-apply",
        "/api/pull-apply",
        "/api/fetch-apply",
        "/api/git/pull-confirm",
        "/api/git/fetch-confirm",
        "/api/v2/git-remote/push/apply",
    )

    REPRESENTATIVE_PROHIBITED_REMOTE_GIT_ACTIONS = (
        "push_preview",
        "push_apply",
        "fetch_preview",
        "fetch_apply",
        "pull_preview",
        "pull_apply",
        "git_remote_push_apply",
        "remote-git.fetch-apply",
        "manage_git_remote",
    )

    def _web_console_source_and_routes(self) -> tuple[str, set[str]]:
        from runner import web_console

        source = inspect.getsource(web_console)
        route_literals = set(re.findall(r"""["'](/api/[^"']+)["']""", source))
        route_literals.update(web_console.SENSITIVE_WEB_GET_PATHS)
        route_literals.update(web_console.PROTECTED_WEB_POST_PATHS)
        route_literals.update(web_console.DANGEROUS_WEB_CONFIRMATION_ROUTES)
        return source, route_literals

    @staticmethod
    def _is_remote_git_mutation_route(route: str) -> bool:
        normalized = str(route or "").strip().lower().replace("_", "-")
        parts = {part for part in re.split(r"[^a-z0-9]+", normalized) if part}
        remote_context = bool({"git", "remote"} & parts) or normalized.startswith((
            "/api/push",
            "/api/pull",
            "/api/fetch",
        ))
        remote_operation = bool({"push", "pull", "fetch"} & parts)
        mutation_intent = bool({"apply", "preview", "confirm", "run", "start", "execute"} & parts)
        return remote_context and remote_operation and mutation_intent

    def test_remote_git_status_sanitizer_is_read_only_and_redacted(self) -> None:
        from runner.web_console import WebConsoleServer

        server = WebConsoleServer.__new__(WebConsoleServer)
        sanitized = server._sanitize_remote_git_status({
            "ok": True,
            "action": "push_status",
            "branch": "main",
            "remote_name": "origin",
            "remote_url_redacted": "https://token@example.invalid/org/repo.git",
            "can_push": True,
            "can_preview": True,
            "preview_id": "must-not-leak",
            "command_summary": "git push origin main",
            "pushed": True,
            "commits": [{"hash": "abcdef1234567890", "subject": "Bearer secret-token"}],
        })

        assert sanitized["ok"] is True
        assert sanitized["action"] == "push_status"
        assert sanitized["remote_url_redacted"] == "https://***@example.invalid/org/repo.git"
        assert sanitized["commits"][0]["short_hash"] == "abcdef123456"
        assert sanitized["commits"][0]["subject"] == "Bearer ***"
        for mutation_field in ("preview_id", "command_summary", "pushed", "preview_path"):
            assert mutation_field not in sanitized

    def test_commit_preview_and_confirm_web_git_boundaries_are_preserved(self) -> None:
        from runner import web_console

        assert "/api/commit-preview" in web_console.PROTECTED_WEB_POST_PATHS
        assert "/api/commit-preview" not in web_console.DANGEROUS_WEB_CONFIRMATION_ROUTES
        assert "/api/commit-confirm" in web_console.PROTECTED_WEB_POST_PATHS
        assert "/api/commit-confirm" in web_console.DANGEROUS_WEB_CONFIRMATION_ROUTES

    def test_web_route_tables_do_not_expose_remote_git_mutation_paths(self) -> None:
        _, routes = self._web_console_source_and_routes()

        for prohibited_path in self.REPRESENTATIVE_PROHIBITED_REMOTE_GIT_PATHS:
            assert prohibited_path not in routes
        offenders = sorted(route for route in routes if self._is_remote_git_mutation_route(route))
        assert offenders == []

    def test_web_console_does_not_call_remote_git_mutation_manager_methods(self) -> None:
        source, _ = self._web_console_source_and_routes()
        remote_manager_calls = set(re.findall(r"MCPGitRemoteManager\([^)]*\)\.([a-z_]+)\(", source))

        assert remote_manager_calls == {"push_status"}
        for forbidden_method in (
            "push_preview",
            "push_apply",
            "fetch_preview",
            "fetch_apply",
            "pull_status",
            "pull_preview",
            "pull_apply",
        ):
            assert f".{forbidden_method}(" not in source

    def test_web_v2_action_rejects_remote_git_mutation_actions(self) -> None:
        from runner.web_console import WebConsoleServer

        server = WebConsoleServer.__new__(WebConsoleServer)
        for action_name in self.REPRESENTATIVE_PROHIBITED_REMOTE_GIT_ACTIONS:
            result = server._api_v2_action({
                "next_action": {
                    "action": action_name,
                    "params": {"preview_id": "preview-do-not-use"},
                }
            })
            assert result["ok"] is False
            assert result["status"] == "blocked"
            assert result["action_outcome"]["error_code"] == "WEB_REMOTE_GIT_MUTATION_PROHIBITED"

    def test_dangerous_preview_policy_does_not_authorize_remote_git_mutation_actions(self) -> None:
        from runner.web_console import WebConsoleServer

        server = WebConsoleServer.__new__(WebConsoleServer)
        for action_name in self.REPRESENTATIVE_PROHIBITED_REMOTE_GIT_ACTIONS:
            assert server._dangerous_action_policy(
                "/api/v2/action",
                {"next_action": {"action": action_name, "params": {"preview_id": "preview-do-not-use"}}},
            ) is None
            assert server._dangerous_action_policy(
                "/api/jobs/start",
                {"operation": action_name},
            ) is None

    def test_project_registry_dangerous_preview_uses_operator_facing_chinese_copy(self) -> None:
        from runner.web_console import WebConsoleServer

        server = WebConsoleServer.__new__(WebConsoleServer)
        server.project_root = "/tmp/current-project"

        class StubRegistry:
            def list_projects(self) -> dict[str, Any]:
                return {
                    "projects": [
                        {
                            "project_id": "prj_other",
                            "project_name": "other-project",
                            "project_root": "/tmp/other-project",
                        }
                    ]
                }

        server.project_registry = StubRegistry()

        policy = server._dangerous_action_policy(
            "/api/v2/action",
            {
                "next_action": {
                    "action": "project_registry_unregister",
                    "params": {"project_root": "/tmp/other-project"},
                }
            },
        )

        assert policy is not None
        assert policy["display_summary"]["title"] == "移出项目登记"
        assert "other-project" in policy["display_summary"]["target"]
        assert "只移出登记" in policy["display_summary"]["target"]
        assert "不删除磁盘文件" in policy["display_summary"]["target"]


class WebConsoleV2ProductFollowupRenderingTests(unittest.TestCase):
    def test_product_followup_copy_payloads_preserve_action_binding(self) -> None:
        from runner.web_console_v2_assets import render_v2_index_page

        page = render_v2_index_page(csrf_token="csrf", web_read_token="read")

        assert 'action_key: item.action_key || primary.action_key || ""' in page
        assert 'action_fingerprint: item.action_fingerprint || primary.action_fingerprint || ""' in page
        assert 'action_id: item.action_id || primary.action_id || ""' in page
        assert "productFollowupRecordPayload" in page
        assert "const recordPayload = JSON.stringify(productFollowupRecordPayload(item, primary, scope), null, 2)" in page
        assert "复制 Product follow-up 结果记录模板：" in page
        assert "Copy follow-up" in page
        assert "Copy record" in page

    def test_submission_activity_record_copy_uses_underlying_action_arguments(self) -> None:
        if shutil.which("node") is None:
            self.skipTest("node is required for product follow-up payload behavior smoke")
        from runner.web_console_v2_assets import render_v2_index_page

        page = render_v2_index_page(csrf_token="csrf", web_read_token="read")
        function_source = page.split("function productFollowupRecordPayload", 1)[1].split(
            "function openProductFollowupInInbox", 1
        )[0]
        script = "function productFollowupRecordPayload" + function_source + r'''
const assert = require("assert");
function operatorInboxRecordPayload() { throw new Error("generic record wrapper must not be used"); }
const argumentsPayload = {
  action_id: "submission_evidence_activity",
  tool: "submission_evidence_activity_summary",
  mode: "read",
  status: "updated",
  message: "operator-confirmed evidence activity",
  result_ok: true,
};
const result = productFollowupRecordPayload({
  item_id: "submission_evidence_activity",
  component: "submission_evidence_activity",
  primary_tool: "record_product_console_action_result",
  required_scope: "mcp:commit",
}, {
  action: "record_submission_evidence_activity",
  tool: "record_product_console_action_result",
  arguments: argumentsPayload,
  required_scope: "mcp:commit",
}, "mcp:commit");
assert.deepStrictEqual(result.arguments, argumentsPayload);
assert.strictEqual(result.source_action_key, "submission_evidence_activity|submission_evidence_activity_summary|read");
assert.strictEqual(result.required_scope, "mcp:commit");
assert.strictEqual(result.gate_level, "explicit_operator_record_required");
const fingerprintBound = productFollowupRecordPayload({
  item_id: "release_submission",
  component: "release_submission",
  primary_tool: "record_product_console_action_result",
  required_scope: "mcp:commit",
  action_fingerprint: "bound-fingerprint",
}, {
  tool: "record_product_console_action_result",
  arguments: {
    action_id: "submission_evidence_activity",
    tool: "submission_evidence_activity_summary",
    mode: "read",
    status: "updated",
  },
}, "mcp:commit");
assert.strictEqual(fingerprintBound.arguments.action_fingerprint, "bound-fingerprint");
'''
        completed = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=False, timeout=15)
        assert completed.returncode == 0, completed.stdout + completed.stderr


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

    def install_safe_executor_stub(self) -> list[dict[str, Any]]:
        assert self.server is not None
        calls: list[dict[str, Any]] = []
        original_execute = self.server._api_execute_current_version

        def safe_execute(mode: str, wrap: bool = True) -> dict[str, Any]:
            calls.append({"mode": mode, "wrap": wrap})
            return {
                "ok": True,
                "message": "stubbed executor path accepted",
                "execution_mode": mode,
            }

        self.server._api_execute_current_version = safe_execute
        self.addCleanup(lambda: setattr(self.server, "_api_execute_current_version", original_execute))
        return calls

    def install_api_stub(self, method_name: str) -> list[dict[str, Any]]:
        assert self.server is not None
        calls: list[dict[str, Any]] = []
        original = getattr(self.server, method_name)

        def safe_stub(*args: Any, **kwargs: Any) -> dict[str, Any]:
            calls.append({"method": method_name, "args": args, "kwargs": kwargs})
            return {
                "ok": True,
                "message": "stubbed guarded operation",
                "method": method_name,
            }

        setattr(self.server, method_name, safe_stub)
        self.addCleanup(lambda: setattr(self.server, method_name, original))
        return calls

    def mutate_runner_state_signature(self) -> None:
        assert self.server is not None
        state_path = Path(self.server.state_file)
        data = json.loads(state_path.read_text(encoding="utf-8"))
        data["e2b_state_nonce"] = secrets.token_hex(8)
        state_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def mutate_runner_plan_signature(self) -> None:
        assert self.server is not None
        plan_path = Path(self.server.plan_file)
        data = json.loads(plan_path.read_text(encoding="utf-8"))
        data["e2c_plan_nonce"] = secrets.token_hex(8)
        plan_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def mutate_plan_patch_signature(self) -> None:
        assert self.server is not None
        patch_dir = Path(self.server.runner_dir) / "plan-patches"
        patch_dir.mkdir(parents=True, exist_ok=True)
        patch_path = patch_dir / "e2c-signature-test.json"
        patch_path.write_text(
            json.dumps(
                {
                    "patch_id": "e2c-signature-test",
                    "status": "PENDING",
                    "nonce": secrets.token_hex(8),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def mutate_commit_preview_signature(self) -> None:
        assert self.server is not None
        assert isinstance(self.server.pending_commit_preview, dict)
        self.server.pending_commit_preview["diff_hash"] = f"diff-{secrets.token_hex(8)}"

    def prepare_commit_confirm_state(self) -> None:
        assert self.server is not None
        state_path = Path(self.server.state_file)
        data = json.loads(state_path.read_text(encoding="utf-8"))
        data["status"] = "VERSION_PASSED"
        data["current_version"] = data.get("current_version") or "v1"
        data["current_version_index"] = 0
        state_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def prepare_pending_commit_preview(
        self,
        *,
        preview_id: str = "commit-preview-test",
        diff_hash: str = "diff-hash-test",
        commit_files: list[str] | None = None,
    ) -> None:
        assert self.server is not None
        self.server.pending_commit_preview = {
            "preview_id": preview_id,
            "message": "v1 test",
            "commit_files": sorted(commit_files or ["app.py", "tests/test_app.py"]),
            "excluded_files": [],
            "diff_hash": diff_hash,
            "version": "v1",
            "project_root": str(self.project),
        }

    def create_commit_confirmation(
        self,
        *,
        action_type: str = "git_commit_confirm",
        route: str = "/api/commit-confirm",
        current_head: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> str:
        assert self.server is not None
        context = self.server._dangerous_action_context()
        preview = self.server.dangerous_action_guard.create_preview(
            action_type=action_type,
            surface="web",
            route=route,
            risk_class="git_local_history_action",
            project_root=context["project_root"],
            project_id=context["project_id"],
            project_name=context["project_name"],
            current_head=current_head if current_head is not None else context["current_head"],
            state_signature=context["state_signature"],
            plan_signature=context["plan_signature"],
            patch_signature=context["commit_preview_signature"],
            registry_signature=context["registry_signature"],
            payload=payload or {},
            target_summary={"operation": "commit_confirm"},
            display_summary={"title": "Confirm local Git commit", "target": "current version"},
        )
        return preview.confirmation_id

    def install_commit_manager_stub(self) -> list[dict[str, Any]]:
        from runner import web_console

        calls: list[dict[str, Any]] = []
        original = web_console.MCPGitCommitManager

        class StubCommitManager:
            def __init__(self, project_root: str):
                self.project_root = project_root

            def commit(self, *, preview_id: str) -> dict[str, Any]:
                calls.append({"project_root": self.project_root, "preview_id": preview_id})
                return {
                    "ok": True,
                    "preview_id": preview_id,
                    "commit_hash": "abcdef1234567890",
                    "commit_hash_short": "abcdef12",
                    "message": "v1 test",
                    "committed_files": ["app.py", "tests/test_app.py"],
                    "verify_clean": True,
                    "verify_summary": {"one_line": "代码提交完成"},
                    "remaining_uncommitted_files": [],
                    "commit_state_update": {"ok": True},
                }

        web_console.MCPGitCommitManager = StubCommitManager
        self.addCleanup(lambda: setattr(web_console, "MCPGitCommitManager", original))
        return calls

    def create_manual_confirmation(
        self,
        *,
        action_type: str = "executor_run_current_version",
        route: str = "/api/run-current-version",
        project_root: str | None = None,
        current_head: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> str:
        assert self.server is not None
        context = self.server._dangerous_action_context()
        preview = self.server.dangerous_action_guard.create_preview(
            action_type=action_type,
            surface="web",
            route=route,
            risk_class="executor_action",
            project_root=project_root or context["project_root"],
            project_id=context["project_id"],
            project_name=context["project_name"],
            current_head=current_head if current_head is not None else context["current_head"],
            state_signature=context["state_signature"],
            registry_signature=context["registry_signature"],
            payload=payload or {},
            target_summary={"executor_mode": "run"},
            display_summary={"title": "Run current version", "target": "current version"},
        )
        return preview.confirmation_id

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
        assert "loaded_runtime_head" in health
        assert "runtime_project_checkout_head" in health
        assert "runtime_loaded_code_stale" in health
        assert "reload_needed_for_verification" in health
        assert "installed_package_matches_project_checkout" in health
        assert "installed_package_project_source_clean" in health
        assert "installed_package_source_cleanliness_status" in health

        status, v2_health = json_request(f"http://{HOST}:{self.port}/api/v2/health")
        assert status == 200
        assert v2_health["ok"] is True

        status, body = http_request(f"http://{HOST}:{self.port}/")
        assert status == 200
        assert str(self.project) not in body
        assert ".colameta" not in body

    def test_healthz_runtime_provenance_uses_loaded_runtime_root(self) -> None:
        runtime_root = str(self.tmp_path / "stable-runtime-root")
        calls: list[tuple[str | None, str | None]] = []

        def fake_runtime_healthz_provenance(project_root: str | None, *, runtime_project_root: str | None) -> dict[str, Any]:
            calls.append((project_root, runtime_project_root))
            return {
                "loaded_runtime_head": None,
                "runtime_project_checkout_head": "a" * 40,
                "runtime_loaded_code_stale": False,
                "reload_needed_for_verification": False,
                "installed_package_matches_project_checkout": True,
                "installed_package_project_source_clean": True,
                "installed_package_source_cleanliness_status": "clean",
            }

        with (
            patch("runner.web_console.loaded_runtime_project_root", return_value=runtime_root),
            patch("runner.web_console.runtime_healthz_provenance", side_effect=fake_runtime_healthz_provenance),
        ):
            self.start_web()
            status, health = json_request(f"http://{HOST}:{self.port}/api/healthz")

        assert status == 200
        assert health["runtime_project_checkout_head"] == "a" * 40
        assert calls
        assert all(call == (str(self.project), runtime_root) for call in calls)

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

        status, payload = json_request(
            f"http://{HOST}:{self.port}/api/status",
            web_read_token=read_token,
        )
        assert status == 200
        assert payload["connector_runtime_health"]["read_only"] is True
        assert payload["connector_runtime_health"]["local_service"]["web"]["reason_code"] == "WEB_ENDPOINT_HEALTHY"
        assert payload["connector_runtime_health"]["external_connector"]["status"] == "unverified"
        assert payload["connector_runtime_health"]["operator_closeout"]["decision"] == "blocked"
        assert "read_tokens_or_cookies" in payload["connector_runtime_health"]["operator_closeout"]["not_authorized_actions"]

    def test_connector_runtime_health_uses_current_serve_process_metadata(self) -> None:
        from runner.web_console import WebConsoleServer
        from runner.runtime_observability import get_connector_runtime_health_status

        server = WebConsoleServer(str(self.project))
        cmdline = [
            "/tmp/python",
            "/tmp/colameta",
            "serve",
            str(self.project),
            "--web-host",
            HOST,
            "--web-port",
            str(self.port),
            "--mcp-host",
            HOST,
            "--mcp-port",
            "8766",
        ]

        with (
            patch("runner.web_console.ServiceLifecycleStore.read_process_cmdline_parts", return_value=cmdline),
            patch.object(WebConsoleServer, "_local_http_healthz_ok", return_value=True),
        ):
            health = server._connector_runtime_local_service_evidence()

        assert health["state"] == "running"
        assert health["health_source"] == "process_table"
        assert health["discovered_from_process_table"] is True
        assert health["enable_web"] is True
        assert health["web_state"] == "healthy"
        assert health["enable_mcp"] is True
        assert health["mcp_state"] == "healthy"
        assert health["mcp_port"] == 8766

        summary = get_connector_runtime_health_status(local_service=health)
        assert summary["local_service"]["status"] == "healthy"
        assert summary["local_service"]["reason_code"] == "LOCAL_SERVICE_HEALTHY"
        assert summary["local_service"]["mcp"]["reason_code"] == "MCP_ENDPOINT_HEALTHY"
        assert summary["operator_closeout"]["status"] == "local_service_ready_runtime_unverified"

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

    def test_v2_status_exposes_web_commander_service_capabilities(self) -> None:
        self.start_web()
        read_token = self.read_token_from_page()
        cmdline = [
            "/tmp/python",
            "/tmp/colameta",
            "serve",
            str(self.project),
            "--web-host",
            HOST,
            "--web-port",
            str(self.port),
            "--mcp-host",
            HOST,
            "--mcp-port",
            "8766",
        ]

        with (
            patch("runner.web_console.ServiceLifecycleStore.read_process_cmdline_parts", return_value=cmdline),
            patch("runner.web_console.WebConsoleServer._local_http_healthz_ok", return_value=True),
        ):
            status, payload = json_request(
                f"http://{HOST}:{self.port}/api/v2/status",
                web_read_token=read_token,
            )

        assert status == 200
        service = payload["web_commander_service"]
        assert service["ok"] is True
        assert service["read_only"] is True
        assert service["side_effects"] is False
        assert service["authority_boundary"]["does_not_authorize_executor_run"] is True
        assert service["readiness"]["status"] in {"ready", "needs_attention", "blocked"}
        assert service["readiness"]["read_only"] is True
        assert service["readiness"]["safe_next_actions"]
        assert "executor_run" in service["readiness"]["not_authorized_actions"]
        assert payload["service_readiness_summary"]["status"] == service["readiness"]["status"]
        assert payload["service_readiness_summary"]["side_effects"] is False
        assert service["product_console_completion"]["source"] == "product_console_completion_surface"
        assert service["product_console_completion"]["read_only"] is True
        assert service["product_console_completion"]["side_effects"] is False
        assert service["product_console_completion"]["status"] in {"ready", "needs_attention", "blocked", "unknown"}
        assert service["product_console_completion"]["progress_state"]["source"] == "product_console_closeout_progress_state"
        assert service["product_console_completion"]["progress_state"]["read_only"] is True
        assert service["product_console_completion"]["progress_state"]["side_effects"] is False
        assert service["product_console_completion"]["progress_state"]["label"]
        assert service["product_console_completion"]["progress_state"]["severity"] in {"ready", "needs_attention"}
        assert service["product_console_completion"]["progress_state"]["next_step"]
        assert service["product_console_completion"]["progress_state"]["recommended_action"]["required_scope"] == "mcp:read"
        assert service["product_console_completion"]["progress_state"]["operator_guidance"]
        assert service["product_console_completion"]["progress_state"]["status"] in {
            "not_started",
            "recorded_needs_review",
            "refresh_pending",
            "stale_result",
            "closeout_ready",
        }
        assert payload["product_console_completion"]["status"] == service["product_console_completion"]["status"]
        overview = service["product_completion_overview"]
        assert overview["source"] == "product_completion_overview"
        assert overview["read_only"] is True
        assert overview["side_effects"] is False
        assert overview["status"] in {"ready", "needs_attention", "blocked"}
        assert overview["total_category_count"] >= overview["ready_category_count"]
        assert isinstance(overview["categories"], list)
        assert overview["categories"]
        assert {"category_id", "label", "status", "severity", "gap_codes", "next_step"} <= set(
            overview["categories"][0]
        )
        actionable_categories = [item for item in overview["categories"] if item.get("ready") is not True]
        if actionable_categories:
            assert actionable_categories[0]["primary_tool"]
            assert actionable_categories[0]["required_scope"] in {"mcp:read", "mcp:preview", "mcp:commit"}
            assert actionable_categories[0]["gate_level"]
        assert payload["product_completion_overview"]["status"] == overview["status"]
        trail = service["operator_session_trail"]
        assert trail["source"] == "product_console_operator_session_trail"
        assert trail["read_only"] is True
        assert trail["side_effects"] is False
        assert trail["status"] in {"not_started", "followup_pending", "refresh_pending", "recorded", "ready"}
        assert isinstance(trail["recent_events"], list)
        assert isinstance(trail["pending_refreshes"], list)
        assert isinstance(trail["recovery_actions"], list)
        assert trail["recovery_action_count"] == len(trail["recovery_actions"])
        assert payload["operator_session_trail"]["status"] == trail["status"]
        inbox = service["operator_inbox"]
        assert inbox["source"] == "web_commander_operator_inbox"
        assert inbox["read_only"] is True
        assert inbox["side_effects"] is False
        assert inbox["total_count"] == len(inbox["items"])
        assert inbox["read_only_count"] + inbox["gated_count"] == inbox["total_count"]
        inbox_sources = {item["source"] for item in inbox["items"]}
        assert {"product_console", "apps_connector", "stable_cadence"} <= inbox_sources
        assert all("tool" in item and "required_scope" in item and "gate_level" in item for item in inbox["items"])
        assert payload["operator_inbox"]["status"] == inbox["status"]
        from runner.web_console_v2_assets import render_v2_index_page

        page = render_v2_index_page(csrf_token="csrf", web_read_token="read")
        assert "Product categories" in page
        assert "completionCategoryText" in page
        assert "completionOverview.categories" in page
        assert "category.primary_tool" in page
        assert "renderProductCompletionOverview" in page
        assert "productCompletionBadgeClass" in page
        assert 'class="product-completion-overview" aria-label="Product completion overview"' in page
        assert "Product completion" in page
        assert "ready ${esc(ready)}/${esc(total)}" in page
        assert "第一缺口：" in page
        assert "primaryFollowupId" in page
        assert "Open first gap" in page
        assert "category.followup_item" in page
        assert "followupId" in page
        assert 'data-open-product-followup="${escAttr(followupId)}"' in page
        assert "只读概览；不执行提交、发布、stable replacement 或 app submission。" in page
        assert "Product follow-up queue" in page
        assert "renderProductFollowupQueue" in page
        assert "completion.followup_queue" in page
        assert 'class="product-followup-queue" aria-label="Product closeout follow-up queue"' in page
        assert "data-copy-operator-inbox" in page
        assert "data-open-product-followup" in page
        assert "openProductFollowupInInbox" in page
        assert "showRightTab(\"operator-inbox\")" in page
        assert "data-operator-inbox-followup-item-id" in page
        assert "target-highlight" in page
        assert "队列只读；Copy 不执行操作，Run 入口仍受 INBOX scope gate 控制。" in page
        assert "Open INBOX" in page
        assert "Copy follow-up" in page
        assert "item_id: followupItemId" in page
        assert "component: item.component" in page
        assert "action: primary.action" in page
        assert 'action_id: item.action_id || primary.action_id || ""' in page
        assert "required_scope: scope" in page
        assert "gate_level: gate" in page
        assert "Operator trail" in page
        assert "operatorTrailText" in page
        assert "recovery_action_count" in page
        assert "renderOperatorInboxRunImpact" in page
        assert 'class="operator-inbox-run-impact ${escAttr(state)}" role="status" aria-live="polite"' in page
        assert "刚才 INBOX Run：" in page
        assert "Product closeout 当前未报告 pending refresh。" in page
        assert "pending refresh，请优先运行或复制刷新项" in page
        assert "Product closeout 将在结果返回后刷新。" in page
        assert "Product closeout 未被推进，请查看 INBOX 项或复制调用手动处理。" in page
        assert "刷新已收口；Product closeout 当前为 current。" in page
        assert "renderCenterColumn(latestStatusData)" in page
        assert "openPendingRefreshInInbox" in page
        assert 'data-open-pending-refresh="true"' in page
        assert "Open refresh" in page
        assert 'data-operator-inbox-component="${escAttr(itemComponent)}"' in page
        assert "component: actionComponent || \"\"" in page
        assert "action.component || \"\"" in page
        assert "setOperatorInboxRunFeedback(actionKey, \"completed\", \"运行完成，状态已刷新。\", data, actionLabel, actionComponent)" in page
        assert "component === \"pending_refresh\"" in page
        assert '[data-operator-inbox-component="pending_refresh"]' in page
        assert "Operator inbox" in page
        assert "operatorInbox" in page
        assert 'data-tab-button="operator-inbox"' in page
        assert 'data-tab="operator-inbox"' in page
        assert "operatorInboxCountSummary" in page
        assert "operatorInboxNumericCount" in page
        assert "inboxBadgeClass" in page
        assert "tab-badge warn" in page
        assert "Operator inbox: " in page
        assert "activeRightTab" in page
        assert "normalizeRightTab" in page
        assert "rightTabActiveClass" in page
        assert "rightTabDisplayStyle" in page
        assert "rightTabAriaSelected" in page
        assert "rightTabAriaHidden" in page
        assert "rightTabCountBadge" in page
        assert "handleRightTabKeydown" in page
        assert "activeLeftTab" in page
        assert "normalizeLeftTab" in page
        assert "leftTabActiveClass" in page
        assert "leftTabAriaSelected" in page
        assert "leftTabAriaHidden" in page
        assert "handleLeftTabKeydown" in page
        assert "ArrowRight" in page
        assert "ArrowLeft" in page
        assert "Home" in page
        assert "End" in page
        assert "TODOLIST: " in page
        assert "DECISION: " in page
        assert 'role="tablist"' in page
        assert 'role="tab"' in page
        assert 'role="tabpanel"' in page
        assert 'role="dialog" aria-modal="true" aria-labelledby="project-management-modal-title" tabindex="-1"' in page
        assert 'role="dialog" aria-modal="true" aria-labelledby="issue-detail-modal-title" tabindex="-1"' in page
        assert 'role="dialog" aria-modal="true" aria-labelledby="todo-detail-modal-title" tabindex="-1"' in page
        assert 'role="dialog" aria-modal="true" aria-labelledby="version-prompt-modal-title" tabindex="-1"' in page
        assert 'aria-label="关闭项目登记管理"' in page
        assert "activeModalId" in page
        assert "modalReturnFocus" in page
        assert "MODAL_FOCUS_SELECTOR" in page
        assert "function modalFocusableElements" in page
        assert "function openModal" in page
        assert "function closeModal" in page
        assert "function closeActiveModal" in page
        assert "focusModal" in page
        assert "function trapModalFocus" in page
        assert "document.addEventListener(\"keydown\"" in page
        assert 'event.key === "Escape"' in page
        assert 'event.key !== "Tab"' in page
        assert "event.shiftKey && current === first" in page
        assert "!event.shiftKey && current === last" in page
        assert "!modal.contains(current)" in page
        assert "trapModalFocus(event)" in page
        assert "document.contains(returnFocus)" in page
        assert 'openModal("project-management-modal")' in page
        assert 'openModal("issue-detail-modal")' in page
        assert 'openModal("todo-detail-modal")' in page
        assert 'openModal("version-prompt-modal")' in page
        assert 'closeModal("project-management-modal", event)' in page
        assert 'id="loading" role="status" aria-live="polite"' in page
        assert 'id="error" role="alert" aria-live="assertive"' in page
        assert "#loading[aria-hidden=\"true\"]" in page
        assert 'id="project-select" aria-label="当前项目" aria-busy="false"' in page
        assert "projectSwitchInFlight" in page
        assert "setProjectSwitchBusy" in page
        assert "select.setAttribute(\"aria-disabled\"" in page
        assert "setGlobalLoading" in page
        assert "clearGlobalError" in page
        assert 'id="refresh-status" class="refresh-status" role="status" aria-live="polite"' in page
        assert 'id="refresh-btn" type="button" aria-busy="false" aria-disabled="false"' in page
        assert "refreshInFlight" in page
        assert "setRefreshButtonBusy" in page
        assert "刷新中..." in page
        assert "lastStatusRefreshText" in page
        assert "backgroundPollStatusText" in page
        assert "setRefreshStatus" in page
        assert "renderRefreshStatus" in page
        assert "projectManagementSyncStatusText" in page
        assert "项目登记数据：" in page
        assert 'class="modal-sync-status" role="status" aria-live="polite"' in page
        assert "renderProjectManagementModal(latestStatusData || {})" in page
        assert "registryActionInFlight" in page
        assert "setRegistryActionStatus" in page
        assert "registryActionTrail" in page
        assert "registryActionTrailFeedback" in page
        assert "REGISTRY_ACTION_TRAIL_LIMIT" in page
        assert "LOCAL_TRAIL_BOUNDARY_TEXT" in page
        assert "仅本会话显示；只保存操作摘要，不保存 payload 或 arguments。" in page
        assert 'class="local-trail-boundary"' in page
        assert 'class="local-trail-clear"' in page
        assert 'class="local-trail-feedback" role="status" aria-live="polite"' in page
        assert "清空本会话记录" in page
        assert "pushRegistryActionTrail" in page
        assert "clearRegistryActionTrail" in page
        assert "renderRegistryActionTrail" in page
        assert "最近项目管理操作" in page
        assert "暂无最近操作。" in page
        assert 'class="registry-action-trail"' in page
        assert "registryActionTrail.slice(0, REGISTRY_ACTION_TRAIL_LIMIT)" in page
        assert 'pushRegistryActionTrail("running", actionMeta, runningMessage)' in page
        assert 'pushRegistryActionTrail(failed ? "failed" : "completed", actionMeta, trailMessage)' in page
        assert 'onclick="clearRegistryActionTrail()"' in page
        assert "已清空本会话项目管理操作记录；未触发后端请求。" in page
        assert 'registryActionTrailFeedback = ""' in page
        assert "项目管理操作就绪。" in page
        assert "项目管理操作完成，状态已刷新。" in page
        assert 'id="registry-action-status"' in page
        assert 'class="registry-action-status ${escAttr(registryActionStatusState)}" role="status" aria-live="polite"' in page
        assert 'aria-busy="${registryBusyAria}" aria-disabled="${registryBusyAria}"' in page
        assert "if (registryActionInFlight) return" in page
        assert "最后刷新 " in page
        assert "后台轮询每 5 秒" in page
        assert "后台轮询正常，无变化" in page
        assert "后台轮询暂时失败，将重试" in page
        assert "正在刷新状态" in page
        assert "正在执行操作" in page
        assert "正在切换项目" in page
        assert "正在执行项目管理操作" in page
        assert 'aria-controls="right-panel-operator-inbox"' in page
        assert 'aria-labelledby="right-tab-operator-inbox"' in page
        assert 'aria-controls="left-panel-versionplan"' in page
        assert 'aria-labelledby="left-tab-versionplan"' in page
        assert "renderOperatorInboxPanel" in page
        assert "bindOperatorInboxActions" in page
        assert "operator-inbox-list" in page
        assert "data-copy-operator-inbox" in page
        assert "data-run-operator-inbox" in page
        assert "operatorInboxRunFeedback" in page
        assert "operatorInboxRunTrail" in page
        assert "operatorInboxRunTrailFeedback" in page
        assert "OPERATOR_INBOX_RUN_TRAIL_LIMIT" in page
        assert "LOCAL_TRAIL_BOUNDARY_TEXT" in page
        assert "operatorInboxRecordPayload" in page
        assert 'tool: "record_product_console_action_result"' in page
        assert "source_action_key" in page
        assert "source_item_id" in page
        assert "source_component" in page
        assert "explicit_operator_record_required" in page
        assert "Copy record" in page
        assert "复制 operator inbox 结果记录模板：" in page
        assert "recordPayload" in page
        assert "setOperatorInboxRunFeedback" in page
        assert "pushOperatorInboxRunTrail" in page
        assert "clearOperatorInboxRunTrail" in page
        assert "renderOperatorInboxRunTrail" in page
        assert "operatorInboxFeedbackFor" in page
        assert "operatorInboxSignature" in page
        assert "clearStaleOperatorInboxFeedback" in page
        assert 'operatorInboxRunFeedback.state === "running"' in page
        assert "operatorInboxRunFeedback.inboxSignature" in page
        assert "operatorInboxFeedbackTimestamp" in page
        assert "来自刚才的 Run 操作" in page
        assert "最近 Run" in page
        assert "暂无最近 Run。" in page
        assert 'class="operator-inbox-run-trail"' in page
        assert "operatorInboxRunTrail.slice(0, OPERATOR_INBOX_RUN_TRAIL_LIMIT)" in page
        assert "data-operator-inbox-action-label" in page
        assert "pushOperatorInboxRunTrail(actionKey, state, message, actionLabel)" in page
        assert 'onclick="clearOperatorInboxRunTrail()"' in page
        assert 'aria-disabled="${operatorInboxRunTrail.length ? "false" : "true"}"' in page
        assert "已清空本会话 operator inbox Run 记录；未触发后端请求。" in page
        assert 'operatorInboxRunTrailFeedback = ""' in page
        assert "operator-inbox-action-meta" in page
        assert "data-operator-inbox-action-key" in page
        assert "operator-inbox-action-status" in page
        assert "正在运行 operator inbox 项" in page
        assert "运行完成，状态已刷新。" in page
        assert 'aria-busy="${isRunning ? "true" : "false"}"' in page
        assert "复制 operator inbox 调用：" in page
        assert "运行只读 operator inbox 项：" in page
        assert "需要更高权限，不能在 Web Console 直接运行：" in page
        assert "复制 MCP 调用：" in page
        assert "复制 TODO ID " in page
        assert 'aria-disabled="${canRun && !isRunning ? "false" : "true"}"' in page
        assert "runAction(action" in page
        assert "REGISTRY_ACTION_META" in page
        assert "registryActionMeta" in page
        assert "registryActionButtonLabel" in page
        assert "移出项目登记" in page
        assert "清理不可用项目登记" in page
        assert "清理临时项目登记" in page
        assert "需要危险操作确认" in page
        assert "target: actionMeta.target" in page
        assert "reason: actionMeta.description" in page
        assert "setProjectIdentityControls" in page
        assert 'id="project-identity-preview"' in page
        assert 'role="status"' in page
        assert 'aria-live="polite"' in page
        assert 'aria-busy="false"' in page
        assert "预览中..." in page
        assert "应用中..." in page
        assert "正在生成迁移预览" in page
        assert "正在应用迁移" in page
        assert "草稿已修改，请重新预览迁移。" in page
        assert payload["apps_connector_closeout"]["read_only"] is True
        assert payload["apps_connector_closeout"]["preferred_smoke_tool"]["tool"] == "get_apps_connector_smoke_packet"
        assert payload["apps_connector_tool_refresh"]["expected_tool"] == "get_apps_connector_smoke_packet"
        assert payload["stable_replacement_cadence"]["read_only"] is True
        assert payload["stable_replacement_cadence"]["stable_replacement_not_required"] is True
        assert payload["stable_replacement_cadence"]["exact_authorization_required"] is False
        assert payload["stable_replacement_cadence"]["safety_boundary"]["does_not_request_stable_replacement"] is True
        assert "dev_batch_summary" in payload["stable_replacement_cadence"]
        assert payload["stable_replacement_cadence"]["dev_batch_summary"]["promotion_posture"] in {
            "continue_batching",
            "review_batch_when_ready",
        }
        assert "batch_review_summary" in payload["stable_replacement_cadence"]
        assert payload["stable_replacement_cadence"]["batch_review_summary"]["suggested_review_action"] in {
            "keep_batching",
            "ready_for_human_review",
        }
        assert service["stable_replacement_cadence"]["status"] == payload["stable_replacement_cadence"]["status"]
        assert payload["apps_connector_closeout"]["project_list_check"]["tool"] == "list_registered_projects"
        assert payload["apps_connector_closeout"]["connector_closeout_check"]["tool"] == "get_connector_runtime_health_status"
        assert service["connector"]["local_service_status"] == "healthy"
        assert service["connector"]["external_connector_status"] == "unverified"
        assert "project_checkout_head" in payload["runtime_version_summary"]
        assert "reload_needed_for_verification" in payload["runtime_version_summary"]
        assert payload["connector_runtime_health"]["read_only"] is True

        profiles = {item["profile_id"]: item for item in service["profiles"]}
        assert profiles["web_gpt_commander"]["polling_guidance"]["max_poll_attempts"] == 3
        assert profiles["local_codex_commander"]["polling_guidance"]["max_poll_attempts"] == 24

        calls = {item["tool"]: item for item in service["copyable_mcp_calls"]}
        calls_by_label = {item["label"]: item for item in service["copyable_mcp_calls"]}
        assert calls["get_apps_connector_smoke_packet"]["arguments"]["project_name"]
        assert calls["get_stable_replacement_cadence"]["arguments"]["project_name"]
        assert calls["get_stage_parallel_plan_preview"]["arguments"]["project_name"]
        assert calls["get_stage_parallel_run_preview"]["arguments"]["project_name"]
        assert calls["get_stage_parallel_worktree_assignment_preview"]["arguments"]["project_name"]
        assert calls["get_stage_parallel_next_action_packet"]["arguments"]["project_name"]
        assert calls["manage_stage_parallel_worktrees"]["arguments"]["project_name"]
        assert calls["manage_stage_parallel_worktrees"]["arguments"]["action"] == "preview"
        assert calls["manage_stage_parallel_shard_inputs"]["arguments"]["project_name"]
        assert calls["manage_stage_parallel_shard_inputs"]["arguments"]["action"] == "preview"
        assert calls["get_stage_parallel_executor_group_preview"]["arguments"]["project_name"]
        assert calls["manage_stage_parallel_executor_group"]["arguments"]["project_name"]
        assert calls["manage_stage_parallel_executor_group"]["arguments"]["action"] == "preview"
        assert calls["manage_stage_parallel_executor_runs"]["arguments"]["project_name"]
        assert calls["manage_stage_parallel_executor_runs"]["arguments"]["action"] == "preview"
        assert calls["get_stage_parallel_executor_results_packet"]["arguments"]["project_name"]
        assert calls["get_stage_parallel_group_status"]["arguments"]["project_name"]
        assert calls["get_stage_parallel_merge_preview"]["arguments"]["project_name"]
        assert calls["manage_stage_parallel_merges"]["arguments"]["project_name"]
        assert calls["manage_stage_parallel_merges"]["arguments"]["action"] == "preview"
        assert calls["get_stage_parallel_closeout_packet"]["arguments"]["project_name"]
        assert calls["render_commander_app"]["arguments"]["project_name"]
        assert calls["render_commander_app"]["arguments"]["profile_id"] == "web_gpt_commander"
        assert calls["get_commander_app_manifest"]["arguments"]["project_name"]
        assert calls["get_commander_app_manifest"]["arguments"]["profile_id"] == "web_gpt_commander"
        assert calls["get_connector_runtime_health_status"]["arguments"]["project_name"]
        assert calls_by_label["Apps smoke packet"]["tool"] == "get_apps_connector_smoke_packet"
        assert calls_by_label["Stable cadence"]["tool"] == "get_stable_replacement_cadence"
        assert calls_by_label["Parallel plan preview"]["tool"] == "get_stage_parallel_plan_preview"
        assert calls_by_label["Parallel run preview"]["tool"] == "get_stage_parallel_run_preview"
        assert calls_by_label["Parallel worktree assignment"]["tool"] == "get_stage_parallel_worktree_assignment_preview"
        assert calls_by_label["Parallel next action"]["tool"] == "get_stage_parallel_next_action_packet"
        assert calls_by_label["Parallel worktree apply preview"]["tool"] == "manage_stage_parallel_worktrees"
        assert calls_by_label["Parallel worktree apply preview"]["arguments"]["action"] == "preview"
        assert calls_by_label["Parallel shard inputs preview"]["tool"] == "manage_stage_parallel_shard_inputs"
        assert calls_by_label["Parallel shard inputs preview"]["arguments"]["action"] == "preview"
        assert calls_by_label["Parallel executor group"]["tool"] == "get_stage_parallel_executor_group_preview"
        assert calls_by_label["Parallel executor group apply preview"]["tool"] == "manage_stage_parallel_executor_group"
        assert calls_by_label["Parallel executor group apply preview"]["arguments"]["action"] == "preview"
        assert calls_by_label["Parallel executor runs apply preview"]["tool"] == "manage_stage_parallel_executor_runs"
        assert calls_by_label["Parallel executor runs apply preview"]["arguments"]["action"] == "preview"
        assert calls_by_label["Parallel executor results packet"]["tool"] == "get_stage_parallel_executor_results_packet"
        assert calls_by_label["Parallel group status"]["tool"] == "get_stage_parallel_group_status"
        assert calls_by_label["Parallel merge preview"]["tool"] == "get_stage_parallel_merge_preview"
        assert calls_by_label["Parallel merge apply preview"]["tool"] == "manage_stage_parallel_merges"
        assert calls_by_label["Parallel merge apply preview"]["arguments"]["action"] == "preview"
        assert calls_by_label["Parallel closeout packet"]["tool"] == "get_stage_parallel_closeout_packet"
        assert calls_by_label["Apps smoke packet"]["arguments"]["tunnel_client"]["reason_code"] == "TUNNEL_CLIENT_HEALTHZ_READY"
        assert calls_by_label["Apps connector fallback"]["arguments"]["tunnel_client"]["reason_code"] == "TUNNEL_CLIENT_HEALTHZ_READY"
        assert (
            calls_by_label["Apps connector fallback"]["arguments"]["control_plane"]["reason_code"]
            == "TUNNEL_CONTROL_PLANE_READYZ_READY"
        )
        assert calls["manage_executor_workflow"]["arguments"]["profile_id"] == "local_codex_commander"

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

    def test_executor_direct_routes_reject_missing_confirmation(self) -> None:
        self.start_web()
        calls = self.install_safe_executor_stub()
        csrf = self.csrf_token_from_page()

        for route in ("/api/run-current-version", "/api/fix-current-version"):
            status, payload = json_request(
                f"http://{HOST}:{self.port}{route}",
                method="POST",
                payload={},
                csrf_token=csrf,
                origin=self.valid_origin(),
                host_header=self.valid_host(),
            )
            assert status == 403
            assert payload["error_code"] == "DANGEROUS_CONFIRMATION_REQUIRED"

        assert calls == []

    def test_executor_jobs_start_run_fix_reject_missing_confirmation_before_job_state(self) -> None:
        self.start_web()
        calls = self.install_safe_executor_stub()
        csrf = self.csrf_token_from_page()

        for operation in ("run_current_version", "fix_current_version"):
            status, payload = json_request(
                f"http://{HOST}:{self.port}/api/jobs/start",
                method="POST",
                payload={"operation": operation},
                csrf_token=csrf,
                origin=self.valid_origin(),
                host_header=self.valid_host(),
            )
            assert status == 403
            assert payload["error_code"] == "DANGEROUS_CONFIRMATION_REQUIRED"
            assert self.server is not None
            assert self.server.operation_running is False
            assert self.server.job.get("status") == "idle"

        assert calls == []

    def test_executor_confirmation_rejects_wrong_action_and_route(self) -> None:
        self.start_web()
        csrf = self.csrf_token_from_page()
        wrong_action_confirmation = self.dangerous_preview("/api/fix-current-version", {})

        status, payload = json_request(
            f"http://{HOST}:{self.port}/api/run-current-version",
            method="POST",
            payload={"confirmation_id": wrong_action_confirmation},
            csrf_token=csrf,
            origin=self.valid_origin(),
            host_header=self.valid_host(),
        )
        assert status == 403
        assert payload["error_code"] == "DANGEROUS_CONFIRMATION_ACTION_MISMATCH"

        wrong_route_confirmation = self.create_manual_confirmation(route="/api/wrong-route")
        status, payload = json_request(
            f"http://{HOST}:{self.port}/api/run-current-version",
            method="POST",
            payload={"confirmation_id": wrong_route_confirmation},
            csrf_token=csrf,
            origin=self.valid_origin(),
            host_header=self.valid_host(),
        )
        assert status == 403
        assert payload["error_code"] == "DANGEROUS_CONFIRMATION_ROUTE_MISMATCH"

    def test_executor_confirmation_rejects_wrong_project_payload_and_stale_state(self) -> None:
        self.start_web()
        calls = self.install_safe_executor_stub()
        csrf = self.csrf_token_from_page()
        other_project = self.create_registered_managed_project("executor-other-project")
        wrong_project_confirmation = self.create_manual_confirmation(project_root=str(other_project))

        status, payload = json_request(
            f"http://{HOST}:{self.port}/api/run-current-version",
            method="POST",
            payload={"confirmation_id": wrong_project_confirmation},
            csrf_token=csrf,
            origin=self.valid_origin(),
            host_header=self.valid_host(),
        )
        assert status == 403
        assert payload["error_code"] == "DANGEROUS_CONFIRMATION_PROJECT_MISMATCH"

        request_body = {"operation": "run_current_version"}
        mismatched_confirmation = self.dangerous_preview("/api/jobs/start", request_body)
        status, payload = json_request(
            f"http://{HOST}:{self.port}/api/jobs/start",
            method="POST",
            payload={**request_body, "extra": "changed", "confirmation_id": mismatched_confirmation},
            csrf_token=csrf,
            origin=self.valid_origin(),
            host_header=self.valid_host(),
        )
        assert status == 403
        assert payload["error_code"] == "DANGEROUS_CONFIRMATION_PAYLOAD_MISMATCH"

        stale_head_confirmation = self.create_manual_confirmation(current_head="stale-head")
        status, payload = json_request(
            f"http://{HOST}:{self.port}/api/run-current-version",
            method="POST",
            payload={"confirmation_id": stale_head_confirmation},
            csrf_token=csrf,
            origin=self.valid_origin(),
            host_header=self.valid_host(),
        )
        assert status == 403
        assert payload["error_code"] == "DANGEROUS_CONFIRMATION_HEAD_MISMATCH"

        stale_confirmation = self.dangerous_preview("/api/run-current-version", {})
        self.mutate_runner_state_signature()
        status, payload = json_request(
            f"http://{HOST}:{self.port}/api/run-current-version",
            method="POST",
            payload={"confirmation_id": stale_confirmation},
            csrf_token=csrf,
            origin=self.valid_origin(),
            host_header=self.valid_host(),
        )
        assert status == 403
        assert payload["error_code"] == "DANGEROUS_CONFIRMATION_STATE_MISMATCH"
        assert calls == []

    def test_executor_confirmation_rejects_expired_and_reused_confirmation(self) -> None:
        self.start_web()
        calls = self.install_safe_executor_stub()
        csrf = self.csrf_token_from_page()
        assert self.server is not None
        self.server.dangerous_action_guard.ttl_seconds = -1
        expired_confirmation = self.dangerous_preview("/api/run-current-version", {})
        self.server.dangerous_action_guard.ttl_seconds = 300

        status, payload = json_request(
            f"http://{HOST}:{self.port}/api/run-current-version",
            method="POST",
            payload={"confirmation_id": expired_confirmation},
            csrf_token=csrf,
            origin=self.valid_origin(),
            host_header=self.valid_host(),
        )
        assert status == 403
        assert payload["error_code"] == "DANGEROUS_CONFIRMATION_EXPIRED"

        valid_confirmation = self.dangerous_preview("/api/run-current-version", {})
        status, payload = json_request(
            f"http://{HOST}:{self.port}/api/run-current-version",
            method="POST",
            payload={"confirmation_id": valid_confirmation},
            csrf_token=csrf,
            origin=self.valid_origin(),
            host_header=self.valid_host(),
        )
        assert status == 200
        assert payload["ok"] is True

        status, payload = json_request(
            f"http://{HOST}:{self.port}/api/run-current-version",
            method="POST",
            payload={"confirmation_id": valid_confirmation},
            csrf_token=csrf,
            origin=self.valid_origin(),
            host_header=self.valid_host(),
        )
        assert status == 403
        assert payload["error_code"] == "DANGEROUS_CONFIRMATION_REUSED"
        assert len(calls) == 1

    def test_executor_csrf_guard_runs_before_confirmation(self) -> None:
        self.start_web()
        calls = self.install_safe_executor_stub()

        status, payload = json_request(
            f"http://{HOST}:{self.port}/api/run-current-version",
            method="POST",
            payload={},
            origin=self.valid_origin(),
            host_header=self.valid_host(),
        )

        assert status == 403
        assert payload["error_code"] == "WEB_CSRF_INVALID"
        assert calls == []

    def test_executor_valid_confirmation_allows_safe_stub_and_redacted_receipt(self) -> None:
        self.start_web()
        calls = self.install_safe_executor_stub()
        csrf = self.csrf_token_from_page()
        confirmation_id = self.dangerous_preview("/api/run-current-version", {})

        status, payload = json_request(
            f"http://{HOST}:{self.port}/api/run-current-version",
            method="POST",
            payload={"confirmation_id": confirmation_id},
            csrf_token=csrf,
            origin=self.valid_origin(),
            host_header=self.valid_host(),
        )

        assert status == 200
        assert payload["ok"] is True
        assert calls == [{"mode": "run", "wrap": True}]
        receipt = payload["dangerous_action_receipt"]
        assert receipt["action_type"] == "executor_run_current_version"
        assert receipt["confirmation_validated"] is True
        assert receipt["confirmation_id"] == "REDACTED"
        assert receipt["target_summary"]["git_commit_allowed"] is False
        assert receipt["target_summary"]["git_push_allowed"] is False
        if confirmation_id in json.dumps(payload, ensure_ascii=False):
            raise AssertionError("full confirmation id leaked")

    def test_executor_jobs_start_valid_confirmation_allows_safe_stubbed_job(self) -> None:
        self.start_web()
        calls = self.install_safe_executor_stub()
        csrf = self.csrf_token_from_page()
        request_body = {"operation": "run_current_version"}
        confirmation_id = self.dangerous_preview("/api/jobs/start", request_body)

        status, payload = json_request(
            f"http://{HOST}:{self.port}/api/jobs/start",
            method="POST",
            payload={**request_body, "confirmation_id": confirmation_id},
            csrf_token=csrf,
            origin=self.valid_origin(),
            host_header=self.valid_host(),
        )

        assert status == 200
        assert payload["ok"] is True
        assert payload["dangerous_action_receipt"]["action_type"] == "executor_job_run_current_version"
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not calls:
            time.sleep(0.05)
        assert calls == [{"mode": "run", "wrap": False}]
        assert self.server is not None
        assert self.server.operation_running is False

    def test_commit_confirm_requires_dangerous_confirmation_before_dispatch(self) -> None:
        self.start_web()
        calls = self.install_api_stub("_api_commit_confirm_with_project")
        csrf = self.csrf_token_from_page()

        status, payload = json_request(
            f"http://{HOST}:{self.port}/api/commit-confirm",
            method="POST",
            payload={},
            csrf_token=csrf,
            origin=self.valid_origin(),
            host_header=self.valid_host(),
        )

        assert status == 403
        assert payload["error_code"] == "DANGEROUS_CONFIRMATION_REQUIRED"
        assert calls == []

    def test_commit_confirm_rejects_invalid_confirmations_before_dispatch(self) -> None:
        self.start_web()
        calls = self.install_api_stub("_api_commit_confirm_with_project")
        self.prepare_commit_confirm_state()
        self.prepare_pending_commit_preview()
        csrf = self.csrf_token_from_page()

        self.server.dangerous_action_guard.ttl_seconds = -1
        expired_confirmation = self.dangerous_preview("/api/commit-confirm", {})
        self.server.dangerous_action_guard.ttl_seconds = 300
        status, payload = json_request(
            f"http://{HOST}:{self.port}/api/commit-confirm",
            method="POST",
            payload={"confirmation_id": expired_confirmation},
            csrf_token=csrf,
            origin=self.valid_origin(),
            host_header=self.valid_host(),
        )
        assert status == 403
        assert payload["error_code"] == "DANGEROUS_CONFIRMATION_EXPIRED"

        valid_confirmation = self.dangerous_preview("/api/commit-confirm", {})
        status, payload = json_request(
            f"http://{HOST}:{self.port}/api/commit-confirm",
            method="POST",
            payload={"confirmation_id": valid_confirmation},
            csrf_token=csrf,
            origin=self.valid_origin(),
            host_header=self.valid_host(),
        )
        assert status == 200
        assert payload["ok"] is True
        assert len(calls) == 1
        status, payload = json_request(
            f"http://{HOST}:{self.port}/api/commit-confirm",
            method="POST",
            payload={"confirmation_id": valid_confirmation},
            csrf_token=csrf,
            origin=self.valid_origin(),
            host_header=self.valid_host(),
        )
        assert status == 403
        assert payload["error_code"] == "DANGEROUS_CONFIRMATION_REUSED"

        wrong_action_confirmation = self.dangerous_preview("/api/run-current-version", {})
        status, payload = json_request(
            f"http://{HOST}:{self.port}/api/commit-confirm",
            method="POST",
            payload={"confirmation_id": wrong_action_confirmation},
            csrf_token=csrf,
            origin=self.valid_origin(),
            host_header=self.valid_host(),
        )
        assert status == 403
        assert payload["error_code"] == "DANGEROUS_CONFIRMATION_ACTION_MISMATCH"

        wrong_route_confirmation = self.create_commit_confirmation(route="/api/wrong-route")
        status, payload = json_request(
            f"http://{HOST}:{self.port}/api/commit-confirm",
            method="POST",
            payload={"confirmation_id": wrong_route_confirmation},
            csrf_token=csrf,
            origin=self.valid_origin(),
            host_header=self.valid_host(),
        )
        assert status == 403
        assert payload["error_code"] == "DANGEROUS_CONFIRMATION_ROUTE_MISMATCH"

        wrong_payload_confirmation = self.dangerous_preview("/api/commit-confirm", {})
        status, payload = json_request(
            f"http://{HOST}:{self.port}/api/commit-confirm",
            method="POST",
            payload={"extra": "changed", "confirmation_id": wrong_payload_confirmation},
            csrf_token=csrf,
            origin=self.valid_origin(),
            host_header=self.valid_host(),
        )
        assert status == 403
        assert payload["error_code"] == "DANGEROUS_CONFIRMATION_PAYLOAD_MISMATCH"

        stale_head_confirmation = self.create_commit_confirmation(current_head="stale-head")
        status, payload = json_request(
            f"http://{HOST}:{self.port}/api/commit-confirm",
            method="POST",
            payload={"confirmation_id": stale_head_confirmation},
            csrf_token=csrf,
            origin=self.valid_origin(),
            host_header=self.valid_host(),
        )
        assert status == 403
        assert payload["error_code"] == "DANGEROUS_CONFIRMATION_HEAD_MISMATCH"

        stale_state_confirmation = self.dangerous_preview("/api/commit-confirm", {})
        self.mutate_runner_state_signature()
        status, payload = json_request(
            f"http://{HOST}:{self.port}/api/commit-confirm",
            method="POST",
            payload={"confirmation_id": stale_state_confirmation},
            csrf_token=csrf,
            origin=self.valid_origin(),
            host_header=self.valid_host(),
        )
        assert status == 403
        assert payload["error_code"] == "DANGEROUS_CONFIRMATION_STATE_MISMATCH"

        stale_plan_confirmation = self.dangerous_preview("/api/commit-confirm", {})
        self.mutate_runner_plan_signature()
        status, payload = json_request(
            f"http://{HOST}:{self.port}/api/commit-confirm",
            method="POST",
            payload={"confirmation_id": stale_plan_confirmation},
            csrf_token=csrf,
            origin=self.valid_origin(),
            host_header=self.valid_host(),
        )
        assert status == 403
        assert payload["error_code"] == "DANGEROUS_CONFIRMATION_PLAN_MISMATCH"

        stale_preview_confirmation = self.dangerous_preview("/api/commit-confirm", {})
        self.mutate_commit_preview_signature()
        status, payload = json_request(
            f"http://{HOST}:{self.port}/api/commit-confirm",
            method="POST",
            payload={"confirmation_id": stale_preview_confirmation},
            csrf_token=csrf,
            origin=self.valid_origin(),
            host_header=self.valid_host(),
        )
        assert status == 403
        assert payload["error_code"] == "DANGEROUS_CONFIRMATION_COMMIT_PREVIEW_MISMATCH"
        assert len(calls) == 1

    def test_commit_confirm_valid_confirmation_allows_stubbed_commit_and_redacted_receipt(self) -> None:
        self.start_web()
        self.prepare_commit_confirm_state()
        self.prepare_pending_commit_preview(preview_id="commit-preview-ok")
        commit_calls = self.install_commit_manager_stub()
        csrf = self.csrf_token_from_page()
        confirmation_id = self.dangerous_preview("/api/commit-confirm", {})

        status, payload = json_request(
            f"http://{HOST}:{self.port}/api/commit-confirm",
            method="POST",
            payload={"confirmation_id": confirmation_id},
            csrf_token=csrf,
            origin=self.valid_origin(),
            host_header=self.valid_host(),
        )

        assert status == 200
        assert payload["ok"] is True
        assert commit_calls == [{"project_root": os.path.realpath(str(self.project)), "preview_id": "commit-preview-ok"}]
        receipt = payload["dangerous_action_receipt"]
        assert receipt["action_type"] == "git_commit_confirm"
        assert receipt["risk_class"] == "git_local_history_action"
        assert receipt["confirmation_validated"] is True
        assert receipt["confirmation_id"] == "REDACTED"
        assert receipt["target_summary"]["git_commit_allowed"] is True
        assert receipt["target_summary"]["git_push_allowed"] is False
        assert receipt["target_summary"]["remote_mutation_allowed"] is False
        if confirmation_id in json.dumps(payload, ensure_ascii=False):
            raise AssertionError("full confirmation id leaked")

    def test_plan_patch_and_state_direct_routes_reject_missing_confirmation_before_dispatch(self) -> None:
        self.start_web()
        csrf = self.csrf_token_from_page()
        route_methods = [
            ("/api/auto-apply-patches", "_api_auto_apply_patches"),
            ("/api/reload-plan", "_api_reload_plan"),
            ("/api/continue-next-version", "_api_continue_next_version"),
            ("/api/rerun-acceptance", "_api_rerun_acceptance"),
            ("/api/checkpoint-review", "_api_checkpoint_review"),
        ]
        call_lists = [self.install_api_stub(method_name) for _, method_name in route_methods]

        for route, _ in route_methods:
            status, payload = json_request(
                f"http://{HOST}:{self.port}{route}",
                method="POST",
                payload={},
                csrf_token=csrf,
                origin=self.valid_origin(),
                host_header=self.valid_host(),
            )
            assert status == 403
            assert payload["error_code"] == "DANGEROUS_CONFIRMATION_REQUIRED"
            assert self.server is not None
            assert self.server.operation_running is False

        assert all(calls == [] for calls in call_lists)

    def test_plan_state_jobs_start_aliases_reject_missing_confirmation_before_job_state(self) -> None:
        self.start_web()
        rerun_calls = self.install_api_stub("_api_rerun_acceptance")
        checkpoint_calls = self.install_api_stub("_api_checkpoint_review")
        csrf = self.csrf_token_from_page()

        for operation in ("rerun_acceptance", "checkpoint_review"):
            status, payload = json_request(
                f"http://{HOST}:{self.port}/api/jobs/start",
                method="POST",
                payload={"operation": operation},
                csrf_token=csrf,
                origin=self.valid_origin(),
                host_header=self.valid_host(),
            )
            assert status == 403
            assert payload["error_code"] == "DANGEROUS_CONFIRMATION_REQUIRED"
            assert self.server is not None
            assert self.server.operation_running is False
            assert self.server.job.get("status") == "idle"

        assert rerun_calls == []
        assert checkpoint_calls == []

    def test_plan_patch_and_state_direct_routes_valid_confirmation_dispatches_with_redacted_receipt(self) -> None:
        self.start_web()
        csrf = self.csrf_token_from_page()
        route_methods = [
            ("/api/auto-apply-patches", "_api_auto_apply_patches", "plan_patch_auto_apply"),
            ("/api/reload-plan", "_api_reload_plan", "reload_plan"),
            ("/api/continue-next-version", "_api_continue_next_version", "continue_next_version"),
            ("/api/rerun-acceptance", "_api_rerun_acceptance", "rerun_acceptance"),
            ("/api/checkpoint-review", "_api_checkpoint_review", "checkpoint_review"),
        ]
        call_lists = [self.install_api_stub(method_name) for _, method_name, _ in route_methods]

        for index, (route, method_name, action_type) in enumerate(route_methods):
            confirmation_id = self.dangerous_preview(route, {})
            status, payload = json_request(
                f"http://{HOST}:{self.port}{route}",
                method="POST",
                payload={"confirmation_id": confirmation_id},
                csrf_token=csrf,
                origin=self.valid_origin(),
                host_header=self.valid_host(),
            )
            assert status == 200
            assert payload["ok"] is True
            assert payload["method"] == method_name
            receipt = payload["dangerous_action_receipt"]
            assert receipt["action_type"] == action_type
            assert receipt["confirmation_validated"] is True
            assert receipt["confirmation_id"] == "REDACTED"
            assert "executor_mode" not in receipt["target_summary"]
            if confirmation_id in json.dumps(payload, ensure_ascii=False):
                raise AssertionError("full confirmation id leaked")
            assert len(call_lists[index]) == 1

    def test_plan_state_jobs_start_aliases_valid_confirmation_allows_stubbed_jobs(self) -> None:
        self.start_web()
        rerun_calls = self.install_api_stub("_api_rerun_acceptance")
        checkpoint_calls = self.install_api_stub("_api_checkpoint_review")
        csrf = self.csrf_token_from_page()
        cases = [
            ("rerun_acceptance", "job_rerun_acceptance", rerun_calls),
            ("checkpoint_review", "job_checkpoint_review", checkpoint_calls),
        ]

        for operation, action_type, calls in cases:
            request_body = {"operation": operation}
            confirmation_id = self.dangerous_preview("/api/jobs/start", request_body)
            status, payload = json_request(
                f"http://{HOST}:{self.port}/api/jobs/start",
                method="POST",
                payload={**request_body, "confirmation_id": confirmation_id},
                csrf_token=csrf,
                origin=self.valid_origin(),
                host_header=self.valid_host(),
            )
            assert status == 200
            assert payload["ok"] is True
            assert payload["operation"] == operation
            assert payload["dangerous_action_receipt"]["action_type"] == action_type
            assert payload["dangerous_action_receipt"]["confirmation_id"] == "REDACTED"
            if confirmation_id in json.dumps(payload, ensure_ascii=False):
                raise AssertionError("full confirmation id leaked")
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and (not calls or self.server.operation_running):
                time.sleep(0.05)
            assert len(calls) == 1
            assert calls[0]["kwargs"] == {"wrap": False}
            assert self.server is not None
            assert self.server.operation_running is False

    def test_plan_patch_and_state_confirmation_rejects_stale_state_plan_and_patch(self) -> None:
        self.start_web()
        rerun_calls = self.install_api_stub("_api_rerun_acceptance")
        reload_calls = self.install_api_stub("_api_reload_plan")
        patch_calls = self.install_api_stub("_api_auto_apply_patches")
        csrf = self.csrf_token_from_page()

        stale_state_confirmation = self.dangerous_preview("/api/rerun-acceptance", {})
        self.mutate_runner_state_signature()
        status, payload = json_request(
            f"http://{HOST}:{self.port}/api/rerun-acceptance",
            method="POST",
            payload={"confirmation_id": stale_state_confirmation},
            csrf_token=csrf,
            origin=self.valid_origin(),
            host_header=self.valid_host(),
        )
        assert status == 403
        assert payload["error_code"] == "DANGEROUS_CONFIRMATION_STATE_MISMATCH"

        stale_plan_confirmation = self.dangerous_preview("/api/reload-plan", {})
        self.mutate_runner_plan_signature()
        status, payload = json_request(
            f"http://{HOST}:{self.port}/api/reload-plan",
            method="POST",
            payload={"confirmation_id": stale_plan_confirmation},
            csrf_token=csrf,
            origin=self.valid_origin(),
            host_header=self.valid_host(),
        )
        assert status == 403
        assert payload["error_code"] == "DANGEROUS_CONFIRMATION_PLAN_MISMATCH"

        stale_patch_confirmation = self.dangerous_preview("/api/auto-apply-patches", {})
        self.mutate_plan_patch_signature()
        status, payload = json_request(
            f"http://{HOST}:{self.port}/api/auto-apply-patches",
            method="POST",
            payload={"confirmation_id": stale_patch_confirmation},
            csrf_token=csrf,
            origin=self.valid_origin(),
            host_header=self.valid_host(),
        )
        assert status == 403
        assert payload["error_code"] == "DANGEROUS_CONFIRMATION_PATCH_MISMATCH"
        assert rerun_calls == []
        assert reload_calls == []
        assert patch_calls == []

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
