import json
import os
import re
import secrets
import subprocess
import tempfile
import threading
import uuid
import ipaddress
import hashlib
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from runner.http_server_utils import ReusableThreadingHTTPServer
from runner.planning_bridge import PlanningBridge, PlanningBridgeError
from runner.executor_registry import (
    DEFAULT_EXECUTION_PROVIDER,
    get_executor_provider_display,
    is_supported_execution_provider,
    normalize_execution_provider,
)
from runner.executor_inventory import get_executor_inventory_summary
from runner.project_identity import build_project_identity
from runner.product_console import build_product_console_map
from runner.execution_branch import ExecutionBranchController
from runner.mcp_executor_workflow import (
    CLAIM_HEARTBEAT_INTERVAL_SECONDS,
    CLAIM_HEARTBEAT_STALE_MULTIPLIER,
    CLAIM_HEARTBEAT_STALE_MIN_SECONDS,
    CLAIMS_DIR,
    PREVIEWS_DIR,
)
from runner.execution_profile import resolve_version_execution_provider, get_version_execution_summary
from runner.workspace import ProjectWorkspace
from runner.plan_loader import PlanLoader
from runner.state_store import StateStore
from runner.state_machine import RunnerStateMachine
from runner.executor_run_workflow import ExecutorRunOnceService
from runner.mcp_git_commit import MCPGitCommitManager
from runner.mcp_git_remote import MCPGitRemoteManager
from runner.mcp_decisions import MCPDecisionRecordsManager
from runner.mcp_project_memory import MCPProjectMemoryManager
from runner.mcp_todolist import MCPTodoListManager
from runner.acceptance_workflow import AcceptanceRerunService
from runner.checkpoint_review_workflow import CheckpointReviewService
from runner.plan_reload_workflow import PlanReloadService
from runner.continue_version_workflow import ContinueNextVersionService
from runner.plan_patch_workflow import PlanPatchAutoApplyService
from runner.project_registry import ProjectRegistry
from runner.runner_settings import RunnerSettingsStore
from runner.executor_session import (
    ExecutorSessionStore,
    classify_executor_session_head_mismatch,
    select_executor_identity_for_display,
)
from runner.runner_paths import resolve_project_runner_dir, resolve_project_runner_rel_dir
from runner.service_lifecycle_store import ServiceLifecycleStore
from runner.web_console_v2_assets import render_v2_index_page
from runner.core_orchestrator import WorkflowOrchestrator
from runner.core_output import CoreOutput
from runner.core_request import CoreRequest
from runner.dangerous_action_guard import DangerousActionGuard
from runner.web_console_presenter import (
    build_execution_display,
    build_executor_session_display,
    extract_model_display_from_plan_data,
)
from runner.executor_status import polling_guidance_for_profile
from runner.runtime_observability import (
    build_apps_connector_closeout_packet,
    build_service_readiness_summary,
    build_stable_replacement_cadence,
    get_connector_runtime_health_status,
    get_runtime_version_status,
    git_checkout_metadata,
    loaded_runtime_project_root,
    runtime_healthz_provenance,
)
from runner.stable_promotion_readiness import DEFAULT_STABLE_RUNTIME_DIR

WEB_CSRF_HEADER = "X-ColaMeta-CSRF"
WEB_READ_AUTH_HEADER = "X-ColaMeta-Read-Auth"
SENSITIVE_WEB_GET_PATHS = frozenset({
    "/api/status",
    "/api/v2/status",
    "/api/version-result",
    "/api/next-plan",
    "/api/plan-overview",
    "/api/log-tail",
    "/api/plan-patches",
    "/api/version-prompt",
    "/api/job-status",
    "/api/project-registry",
})
PROTECTED_WEB_POST_PATHS = frozenset({
    "/api/jobs/start",
    "/api/auto-apply-patches",
    "/api/run-current-version",
    "/api/fix-current-version",
    "/api/reload-plan",
    "/api/continue-next-version",
    "/api/rerun-acceptance",
    "/api/checkpoint-review",
    "/api/commit-preview",
    "/api/commit-confirm",
    "/api/switch-executor",
    "/api/switch-project",
    "/api/project-identity/preview",
    "/api/project-identity/apply",
    "/api/v2/action",
    "/api/dangerous-action/preview",
})

DANGEROUS_WEB_CONFIRMATION_ROUTES = frozenset({
    "/api/jobs/start",
    "/api/auto-apply-patches",
    "/api/run-current-version",
    "/api/fix-current-version",
    "/api/reload-plan",
    "/api/continue-next-version",
    "/api/rerun-acceptance",
    "/api/checkpoint-review",
    "/api/commit-confirm",
    "/api/switch-executor",
    "/api/switch-project",
    "/api/project-identity/apply",
    "/api/v2/action",
})

DANGEROUS_DIRECT_EXECUTOR_ROUTES = {
    "/api/run-current-version": ("executor_run_current_version", "run"),
    "/api/fix-current-version": ("executor_fix_current_version", "fix"),
}

DANGEROUS_JOB_EXECUTOR_OPERATIONS = {
    "run_current_version": ("executor_job_run_current_version", "run"),
    "fix_current_version": ("executor_job_fix_current_version", "fix"),
}

DANGEROUS_PLAN_STATE_ROUTES = {
    "/api/auto-apply-patches": {
        "action_type": "plan_patch_auto_apply",
        "operation": "auto_apply_patches",
        "risk_class": "plan_patch_action",
        "title": "Auto-apply pending plan patches",
    },
    "/api/reload-plan": {
        "action_type": "reload_plan",
        "operation": "reload_plan",
        "risk_class": "plan_state_transition",
        "title": "Reload plan",
    },
    "/api/continue-next-version": {
        "action_type": "continue_next_version",
        "operation": "continue_next_version",
        "risk_class": "plan_state_transition",
        "title": "Continue to next version",
    },
    "/api/rerun-acceptance": {
        "action_type": "rerun_acceptance",
        "operation": "rerun_acceptance",
        "risk_class": "acceptance_action",
        "title": "Rerun acceptance",
    },
    "/api/checkpoint-review": {
        "action_type": "checkpoint_review",
        "operation": "checkpoint_review",
        "risk_class": "checkpoint_review_action",
        "title": "Run checkpoint review",
    },
}

DANGEROUS_JOB_PLAN_STATE_OPERATIONS = {
    "rerun_acceptance": {
        "action_type": "job_rerun_acceptance",
        "risk_class": "acceptance_action",
        "title": "Start background rerun acceptance job",
    },
    "checkpoint_review": {
        "action_type": "job_checkpoint_review",
        "risk_class": "checkpoint_review_action",
        "title": "Start background checkpoint review job",
    },
}

DANGEROUS_REGISTRY_ACTIONS = frozenset({
    "project_registry_unregister",
    "project_registry_prune_unavailable",
    "project_registry_prune_temporary",
})

REMOTE_GIT_WEB_MUTATION_ACTIONS = frozenset({
    "manage_git_remote",
    "git_remote_push_preview",
    "git_remote_push_apply",
    "git_remote_fetch_preview",
    "git_remote_fetch_apply",
    "git_remote_pull_preview",
    "git_remote_pull_apply",
    "push_preview",
    "push_apply",
    "fetch_preview",
    "fetch_apply",
    "pull_preview",
    "pull_apply",
})


def _is_loopback_host(host: str | None) -> bool:
    value = (host or "").strip().lower().rstrip(".")
    if value == "localhost":
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def _parsed_header_host(value: str | None) -> tuple[str | None, int | None]:
    if not isinstance(value, str) or not value.strip():
        return None, None
    try:
        parsed = urlparse(f"//{value.strip()}")
        return parsed.hostname, parsed.port
    except ValueError:
        return None, None


def _parsed_url_host(value: str | None) -> tuple[str | None, int | None]:
    if not isinstance(value, str) or not value.strip():
        return None, None
    try:
        parsed = urlparse(value.strip())
        return parsed.hostname, parsed.port
    except ValueError:
        return None, None


class WebConsoleServer:
    def __init__(
        self,
        project_path: str,
        project_registry: ProjectRegistry | None = None,
        *,
        service_mode: bool = False,
    ):
        self.bridge = PlanningBridge()
        self.operation_lock = threading.Lock()
        self.operation_running = False
        self.operation_name = ""
        self.operation_started_at: str | None = None
        self.last_operation_result: dict[str, Any] | None = None
        self.job: dict[str, Any] = {"status": "idle"}
        self.pending_commit_preview: dict[str, Any] | None = None
        self.pending_run_preview: dict[str, Any] | None = None
        self.project_registry = project_registry or self._default_project_registry(project_path)
        self.service_mode = service_mode
        self.runner_settings_store = RunnerSettingsStore()
        self._set_project_root(project_path)
        self._settings_resolve_cache: dict[str, Any] = {}
        self._csrf_token = secrets.token_urlsafe(32)
        self._local_web_read_token = secrets.token_urlsafe(32)
        self.dangerous_action_guard = DangerousActionGuard()

    @classmethod
    def _default_project_registry(cls, project_path: str) -> ProjectRegistry:
        project_root = os.path.realpath(os.path.abspath(os.path.expanduser(project_path)))
        if cls._is_temporary_project_root(project_root):
            runtime_dir = os.path.join(resolve_project_runner_dir(project_root), "runtime")
            return ProjectRegistry(
                registry_path=os.path.join(runtime_dir, "project-registry.json"),
                user_settings_path=os.path.join(runtime_dir, "colameta-settings.json"),
            )
        return ProjectRegistry()

    @staticmethod
    def _is_temporary_project_root(project_root: str) -> bool:
        root = os.path.realpath(os.path.abspath(os.path.expanduser(project_root)))
        temp_root = os.path.realpath(tempfile.gettempdir())
        if root == temp_root or root.startswith(temp_root + os.sep):
            return True
        parts = set(root.split(os.sep))
        return "TemporaryItems" in parts or "Cleanup At Startup" in parts

    def _set_project_root(self, project_path: str) -> None:
        self.project_root = os.path.realpath(os.path.abspath(os.path.expanduser(project_path)))
        self.runner_dir = resolve_project_runner_dir(self.project_root)
        self.runner_rel_dir = resolve_project_runner_rel_dir(self.project_root)
        self.plan_file = os.path.join(self.runner_dir, "plan.json")
        self.state_file = os.path.join(self.runner_dir, "state.json")
        self.logs_dir = os.path.join(self.runner_dir, "logs")
        self.runtime_dir = os.path.join(self.runner_dir, "runtime")
        self.marker_file = os.path.join(self.runtime_dir, "plan-updated.marker")
        self.start_plan_mtime = self._safe_mtime(self.plan_file)
        self.start_marker_mtime = self._safe_mtime(self.marker_file)
        self.executor_session_store = ExecutorSessionStore(self.project_root)

    def _should_require_execution_branch(
        self,
        *,
        current_version: Any,
        resolved_provider: str,
        mainline_provider: str,
    ) -> bool:
        resolved = normalize_execution_provider(resolved_provider, default=DEFAULT_EXECUTION_PROVIDER)
        mainline = normalize_execution_provider(mainline_provider, default=DEFAULT_EXECUTION_PROVIDER)
        if resolved == "opencode":
            return True
        if resolved != mainline:
            return True
        if current_version is None or current_version.execution is None:
            return False
        override_provider = getattr(current_version.execution, "provider", None)
        if not isinstance(override_provider, str) or not override_provider.strip():
            return False
        normalized_override = normalize_execution_provider(override_provider, default=mainline)
        return normalized_override != mainline

    def validate_project(self, mode: str | None = None) -> None:
        if not os.path.isdir(self.project_root):
            raise PlanningBridgeError(f"项目目录不存在：{self.project_root}")
        if not os.path.isdir(self.runner_dir):
            raise PlanningBridgeError(f"缺少运行目录：{self.runner_dir}")
        if mode == "source-only":
            return
        if mode == "managed":
            if not os.path.exists(self.plan_file):
                raise PlanningBridgeError(
                    "当前项目尚未纳入 Runner 管理；后续版本会支持 managed 自动最小纳管。当前可先使用 source-only 模式启动 MCP，或通过 manage_runner_plan 完成纳管。"
                )
            return
        if not os.path.exists(self.plan_file):
            raise PlanningBridgeError(
                f"当前项目尚未纳入 Runner：缺少 {self.runner_rel_dir}/plan.json。\n"
                "请通过 MCP manage_runner_plan 创建受控 plan，\n"
                "或使用 CLI import-plan-file 作为高级 fallback。"
            )
        if not os.path.exists(self.state_file):
            raise PlanningBridgeError(f"缺少状态文件：{self.state_file}")

    def _now_iso(self) -> str:
        return datetime.now().astimezone().isoformat()

    def _operation_running_payload(self) -> dict[str, Any]:
        return {
            "ok": False,
            "error_code": "OPERATION_RUNNING",
            "message": f"当前有操作正在运行：{self.operation_name or 'unknown'}",
            "operation": {
                "name": self.operation_name or "unknown",
                "status": "running",
                "started_at": self.operation_started_at,
            },
        }

    def _operation_payload(self, operation_name: str, started_at: str | None, fn) -> dict[str, Any]:
        started_at = started_at or self._now_iso()
        try:
            result = fn()
            payload = {
                "ok": bool(result.get("ok", True)),
                "operation": operation_name,
                "status": "ok" if result.get("ok", True) else "failed",
                "started_at": started_at,
                "ended_at": self._now_iso(),
                "message": result.get("message", ""),
                "result": result,
                "error_code": result.get("error_code"),
            }
            self.last_operation_result = payload
            return payload
        except Exception as e:
            payload = {
                "ok": False,
                "operation": operation_name,
                "status": "failed",
                "started_at": started_at,
                "ended_at": self._now_iso(),
                "message": str(e),
                "result": {},
                "error_code": "OPERATION_FAILED",
            }
            self.last_operation_result = payload
            return payload

    def _run_operation(self, operation_name: str, fn) -> dict[str, Any]:
        with self.operation_lock:
            if self.operation_running:
                return self._operation_running_payload()
            if operation_name not in ("commit_preview", "commit_confirm"):
                self.pending_commit_preview = None
            if operation_name not in ("run_current_version_preview", "run_current_version_confirm"):
                self.pending_run_preview = None
            self.operation_running = True
            self.operation_name = operation_name
            self.operation_started_at = self._now_iso()
        started_at = self.operation_started_at
        try:
            return self._operation_payload(operation_name, started_at, fn)
        finally:
            with self.operation_lock:
                self.operation_running = False
                self.operation_name = ""
                self.operation_started_at = None

    def _load_runtime_context(self) -> tuple[ProjectWorkspace, Any, Any, StateStore, RunnerStateMachine]:
        workspace = ProjectWorkspace.from_project_path(self.project_root)
        workspace.ensure_directories()
        loader = PlanLoader()
        plan = loader.load_plan(workspace.plan_file)
        plan.project_root = workspace.workspace_root
        plan.logs_dir = workspace.logs_dir
        plan.runtime_dir = workspace.runtime_dir
        plan.state_file = workspace.state_file
        if not os.path.isabs(plan.rules_file):
            plan.rules_file = workspace.rules_file
        loader.validate_plan(plan)
        store = StateStore()
        state = store.load_state(workspace.state_file)
        machine = RunnerStateMachine(plan, state)
        return workspace, plan, state, store, machine

    def _to_rel(self, path: str | None) -> str:
        if not path:
            return "-"
        return self._to_project_relative(path)

    def serve_http(
        self,
        host: str = "127.0.0.1",
        port: int = 8787,
        *,
        allow_external_web: bool = False,
        web_read_token: str | None = None,
    ) -> int:
        external_web = not _is_loopback_host(host)
        configured_web_read_token = self._normalize_optional_secret(web_read_token)
        if external_web and not allow_external_web:
            raise ValueError("Web Console non-loopback bind requires --allow-external-web.")
        if external_web and configured_web_read_token is None:
            raise ValueError("Web Console non-loopback bind requires --web-read-token.")
        active_web_read_token = configured_web_read_token or self._local_web_read_token
        embed_web_read_token = not external_web
        server = self

        class WebConsoleHandler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:
                return

            def _send_json(self, payload: dict[str, Any], status_code: int = 200) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status_code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _send_html(self, html_text: str) -> None:
                body = html_text.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _read_json_body(self) -> dict[str, Any]:
                try:
                    length = int(self.headers.get("Content-Length", "0") or "0")
                    if length <= 0:
                        return {}
                    raw = self.rfile.read(length).decode("utf-8")
                    parsed = json.loads(raw)
                    return parsed if isinstance(parsed, dict) else {}
                except Exception:
                    return {}

            def _send_guard_result(self, result: dict[str, Any]) -> None:
                status_code = int(result.pop("_http_status", 403))
                self._send_json(result, status_code=status_code)

            def do_GET(self) -> None:
                parsed = urlparse(self.path)
                path = parsed.path
                if path == "/":
                    self._send_html(server._render_v2_index_html(active_web_read_token if embed_web_read_token else ""))
                    return
                if path == "/legacy/":
                    self._send_json(
                        {"ok": False, "error_code": "GONE", "message": "旧 Web Console 已移除，请使用 /。"},
                        status_code=410,
                    )
                    return
                if path == "/favicon.ico":
                    self.send_response(204)
                    self.end_headers()
                    return
                if path == "/api/healthz":
                    self._send_json(
                        {
                            "ok": True,
                            "service": "colameta-web-console",
                            **runtime_healthz_provenance(
                                server.project_root,
                                runtime_project_root=loaded_runtime_project_root(),
                            ),
                        }
                    )
                    return
                if path == "/api/v2/health":
                    self._send_json(server._api_v2_health())
                    return
                if path in SENSITIVE_WEB_GET_PATHS:
                    read_guard = server._validate_web_read_request(
                        headers=self.headers,
                        web_host=host,
                        web_port=port,
                        web_read_token=active_web_read_token,
                    )
                    if read_guard is not None:
                        self._send_guard_result(read_guard)
                        return
                if path == "/api/status":
                    self._send_json(server._api_status())
                    return
                if path == "/api/version-result":
                    self._send_json(server._api_version_result())
                    return
                if path == "/api/next-plan":
                    self._send_json(server._api_next_plan())
                    return
                if path == "/api/plan-overview":
                    self._send_json(server._api_plan_overview())
                    return
                if path == "/api/log-tail":
                    self._send_json(server._api_log_tail())
                    return
                if path == "/api/plan-patches":
                    self._send_json(server._api_plan_patches())
                    return
                if path == "/api/version-prompt":
                    version = parse_qs(urlparse(self.path).query, keep_blank_values=True).get("version", [None])[0]
                    self._send_json(server._api_version_prompt(version=version))
                    return
                if path == "/api/job-status":
                    self._send_json(server._api_job_status())
                    return
                if path == "/api/project-registry":
                    self._send_json(server._api_project_registry())
                    return
                if path == "/v2/":
                    self._send_html(server._render_v2_index_html(active_web_read_token if embed_web_read_token else ""))
                    return
                if path == "/api/v2/status":
                    self._send_json(server._api_v2_status())
                    return
                self._send_json({"ok": False, "message": "not_found"}, status_code=404)

            def do_POST(self) -> None:
                path = urlparse(self.path).path
                body: dict[str, Any] | None = None
                dangerous_receipt: dict[str, Any] | None = None
                if path in PROTECTED_WEB_POST_PATHS:
                    body = self._read_json_body()
                    write_guard = server._validate_web_write_request(
                        body,
                        headers=self.headers,
                        path=path,
                        web_host=host,
                        web_port=port,
                    )
                    if write_guard is not None:
                        self._send_guard_result(write_guard)
                        return
                    dangerous_guard, dangerous_receipt = server._validate_dangerous_action_request(
                        path,
                        body or {},
                    )
                    if dangerous_guard is not None:
                        self._send_guard_result(dangerous_guard)
                        return
                if path == "/api/dangerous-action/preview":
                    preview_payload = server._api_dangerous_action_preview(body or {})
                    status_code = int(preview_payload.pop("_http_status", 200))
                    self._send_json(preview_payload, status_code=status_code)
                    return
                if path == "/api/jobs/start":
                    self._send_json(server._with_dangerous_action_receipt(
                        server._api_start_job(body or {}),
                        dangerous_receipt,
                    ))
                    return
                if path == "/api/auto-apply-patches":
                    self._send_json(server._with_dangerous_action_receipt(
                        server._api_auto_apply_patches(),
                        dangerous_receipt,
                    ))
                    return
                if path == "/api/run-current-version":
                    self._send_json(server._with_dangerous_action_receipt(
                        server._api_run_current_version(),
                        dangerous_receipt,
                    ))
                    return
                if path == "/api/fix-current-version":
                    self._send_json(server._with_dangerous_action_receipt(
                        server._api_fix_current_version(),
                        dangerous_receipt,
                    ))
                    return
                if path == "/api/reload-plan":
                    self._send_json(server._with_dangerous_action_receipt(
                        server._api_reload_plan(),
                        dangerous_receipt,
                    ))
                    return
                if path == "/api/continue-next-version":
                    self._send_json(server._with_dangerous_action_receipt(
                        server._api_continue_next_version(),
                        dangerous_receipt,
                    ))
                    return
                if path == "/api/rerun-acceptance":
                    self._send_json(server._with_dangerous_action_receipt(
                        server._api_rerun_acceptance(),
                        dangerous_receipt,
                    ))
                    return
                if path == "/api/checkpoint-review":
                    self._send_json(server._with_dangerous_action_receipt(
                        server._api_checkpoint_review(),
                        dangerous_receipt,
                    ))
                    return
                if path == "/api/commit-preview":
                    self._send_json(server._api_commit_preview_with_project())
                    return
                if path == "/api/commit-confirm":
                    self._send_json(server._with_dangerous_action_receipt(
                        server._api_commit_confirm_with_project(),
                        dangerous_receipt,
                    ))
                    return
                if path == "/api/switch-executor":
                    self._send_json(server._with_dangerous_action_receipt(
                        server._api_switch_executor(body or {}),
                        dangerous_receipt,
                    ))
                    return
                if path == "/api/switch-project":
                    self._send_json(server._with_dangerous_action_receipt(
                        server._api_switch_project(body or {}),
                        dangerous_receipt,
                    ))
                    return
                if path == "/api/project-identity/preview":
                    self._send_json(server._api_project_identity_preview(body or {}))
                    return
                if path == "/api/project-identity/apply":
                    self._send_json(server._with_dangerous_action_receipt(
                        server._api_project_identity_apply(body or {}),
                        dangerous_receipt,
                    ))
                    return
                if path == "/api/v2/action":
                    self._send_json(server._with_dangerous_action_receipt(
                        server._api_v2_action(body or {}),
                        dangerous_receipt,
                    ))
                    return
                self._send_json({"ok": False, "message": "not_found"}, status_code=404)

        httpd = ReusableThreadingHTTPServer((host, port), WebConsoleHandler)
        self._httpd = httpd
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            httpd.shutdown()
            httpd.server_close()
        return 0

    def _validate_preview_request(self, body: dict[str, Any] | None) -> dict[str, Any] | None:
        payload = body or {}
        if payload.get("project_root") is not None:
            return {
                "ok": False,
                "error_code": "INVALID_PARAMS",
                "message": "project_root is not allowed.",
            }
        return None

    def _validate_commit_confirm_request(self, body: dict[str, Any] | None) -> dict[str, Any] | None:
        payload = body or {}
        if payload.get("project_root") is not None:
            return {
                "ok": False,
                "error_code": "INVALID_PARAMS",
                "message": "project_root is not allowed.",
            }
        return None

    def _guard_error(self, error_code: str, message: str, *, status_code: int = 403) -> dict[str, Any]:
        return {
            "ok": False,
            "error_code": error_code,
            "message": message,
            "_http_status": status_code,
        }

    @staticmethod
    def _normalize_optional_secret(value: str | None) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        return normalized or None

    def _validate_web_host_header(
        self,
        headers: Any,
        *,
        web_host: str,
        web_port: int,
        request_kind: str,
    ) -> dict[str, Any] | None:
        host_name, host_port = _parsed_header_host(headers.get("Host"))
        if host_name is None:
            return self._guard_error(
                "WEB_HOST_INVALID",
                f"Web Console {request_kind} request Host is invalid.",
            )
        if host_port is not None and web_port and host_port != web_port:
            return self._guard_error(
                "WEB_HOST_INVALID",
                f"Web Console {request_kind} request Host port is invalid.",
            )
        normalized_web_host = (web_host or "").strip().lower().rstrip(".")
        host_allowed = _is_loopback_host(host_name)
        if not host_allowed and normalized_web_host not in {"0.0.0.0", "::"}:
            host_allowed = host_name.strip().lower().rstrip(".") == normalized_web_host
        if not host_allowed:
            return self._guard_error(
                "WEB_HOST_INVALID",
                f"Web Console {request_kind} request Host is not allowed.",
            )
        return None

    def _validate_web_read_request(
        self,
        *,
        headers: Any | None = None,
        web_host: str = "127.0.0.1",
        web_port: int = 0,
        web_read_token: str = "",
    ) -> dict[str, Any] | None:
        if headers is None:
            return self._guard_error("WEB_READ_AUTH_REQUIRED", "Web Console read authentication is required.")
        host_guard = self._validate_web_host_header(
            headers,
            web_host=web_host,
            web_port=web_port,
            request_kind="read",
        )
        if host_guard is not None:
            return host_guard
        expected = self._normalize_optional_secret(web_read_token)
        if expected is None:
            return self._guard_error("WEB_READ_AUTH_REQUIRED", "Web Console read authentication is required.")
        presented = self._normalize_optional_secret(headers.get(WEB_READ_AUTH_HEADER))
        authorization = self._normalize_optional_secret(headers.get("Authorization"))
        if presented is None and authorization:
            parts = authorization.split(None, 1)
            if len(parts) == 2 and parts[0].lower() == "bearer":
                presented = self._normalize_optional_secret(parts[1])
        if presented is None:
            return self._guard_error("WEB_READ_AUTH_REQUIRED", "Web Console read authentication is required.")
        if not secrets.compare_digest(presented, expected):
            return self._guard_error("WEB_READ_AUTH_INVALID", "Web Console read authentication is invalid.")
        return None

    def _validate_web_write_request(
        self,
        body: dict[str, Any] | None,
        *,
        headers: Any | None = None,
        path: str = "",
        web_host: str = "127.0.0.1",
        web_port: int = 0,
    ) -> dict[str, Any] | None:
        if headers is not None:
            content_type = str(headers.get("Content-Type", "") or "").split(";", 1)[0].strip().lower()
            if content_type != "application/json":
                return self._guard_error(
                    "WEB_CONTENT_TYPE_REQUIRED",
                    "Web Console write requests require application/json.",
                    status_code=415,
                )

            host_guard = self._validate_web_host_header(
                headers,
                web_host=web_host,
                web_port=web_port,
                request_kind="write",
            )
            if host_guard is not None:
                return host_guard
            normalized_web_host = (web_host or "").strip().lower().rstrip(".")

            for header_name, error_code in (("Origin", "WEB_ORIGIN_INVALID"), ("Referer", "WEB_REFERER_INVALID")):
                value = headers.get(header_name)
                if not value:
                    continue
                origin_host, origin_port = _parsed_url_host(value)
                if origin_host is None:
                    return self._guard_error(error_code, f"Web Console write request {header_name} is invalid.")
                if origin_port is not None and web_port and origin_port != web_port:
                    return self._guard_error(error_code, f"Web Console write request {header_name} port is invalid.")
                origin_allowed = _is_loopback_host(origin_host)
                if not origin_allowed and normalized_web_host not in {"0.0.0.0", "::"}:
                    origin_allowed = origin_host.strip().lower().rstrip(".") == normalized_web_host
                if not origin_allowed:
                    return self._guard_error(error_code, f"Web Console write request {header_name} is not allowed.")

            csrf_value = str(headers.get(WEB_CSRF_HEADER, "") or "")
            if not csrf_value or not secrets.compare_digest(csrf_value, self._csrf_token):
                return self._guard_error("WEB_CSRF_INVALID", "Web Console write request CSRF token is invalid.")

        payload = body or {}
        if payload.get("project_root") is not None and path != "/api/switch-project":
            return {
                "ok": False,
                "error_code": "INVALID_PARAMS",
                "message": "project_root is not allowed.",
                "_http_status": 400,
            }
        return None

    def _api_dangerous_action_preview(self, body: dict[str, Any]) -> dict[str, Any]:
        route = body.get("route")
        payload = body.get("payload")
        if not isinstance(route, str) or not route.strip():
            return {
                "ok": False,
                "error_code": "DANGEROUS_PREVIEW_ROUTE_REQUIRED",
                "message": "Dangerous action preview requires a route.",
                "_http_status": 400,
            }
        if not isinstance(payload, dict):
            return {
                "ok": False,
                "error_code": "DANGEROUS_PREVIEW_PAYLOAD_REQUIRED",
                "message": "Dangerous action preview requires a JSON payload.",
                "_http_status": 400,
            }
        policy = self._dangerous_action_policy(route.strip(), payload)
        if policy is None:
            return {
                "ok": False,
                "error_code": "DANGEROUS_PREVIEW_UNSUPPORTED",
                "message": "Dangerous action preview is not available for this action.",
                "_http_status": 400,
            }
        context = self._dangerous_action_context()
        preview = self.dangerous_action_guard.create_preview(
            action_type=policy["action_type"],
            surface="web",
            route=route.strip(),
            risk_class=policy["risk_class"],
            project_root=context["project_root"],
            project_id=context["project_id"],
            project_name=context["project_name"],
            current_head=context["current_head"],
            state_signature=context["state_signature"],
            plan_signature=context["plan_signature"] if policy.get("guard_plan_signature") else None,
            patch_signature=self._dangerous_secondary_signature(policy, context),
            registry_signature=context["registry_signature"],
            payload=payload,
            target_summary=policy["target_summary"],
            display_summary=policy["display_summary"],
        )
        return self.dangerous_action_guard.preview_response(preview)

    def _validate_dangerous_action_request(
        self,
        route: str,
        body: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        policy = self._dangerous_action_policy(route, body)
        if policy is None:
            return None, None
        context = self._dangerous_action_context()
        result = self.dangerous_action_guard.confirm(
            confirmation_id=body.get("confirmation_id"),
            action_type=policy["action_type"],
            surface="web",
            route=route,
            project_root=context["project_root"],
            current_head=context["current_head"],
            state_signature=context["state_signature"],
            plan_signature=context["plan_signature"] if policy.get("guard_plan_signature") else None,
            patch_signature=self._dangerous_secondary_signature(policy, context),
            registry_signature=context["registry_signature"],
            payload=body,
        )
        if not result.get("ok"):
            error_code = str(result.get("error_code") or "DANGEROUS_CONFIRMATION_INVALID")
            message = str(result.get("message") or "Dangerous action confirmation is invalid.")
            if policy.get("guard_commit_preview_signature") and error_code == "DANGEROUS_CONFIRMATION_PATCH_MISMATCH":
                error_code = "DANGEROUS_CONFIRMATION_COMMIT_PREVIEW_MISMATCH"
                message = "Dangerous action confirmation commit preview mismatch."
            return self._guard_error(
                error_code,
                message,
            ), None
        receipt = result.get("receipt") if isinstance(result.get("receipt"), dict) else {}
        return None, receipt

    @staticmethod
    def _dangerous_secondary_signature(policy: dict[str, Any], context: dict[str, Any]) -> str | None:
        if policy.get("guard_commit_preview_signature"):
            return context["commit_preview_signature"]
        if policy.get("guard_patch_signature"):
            return context["patch_signature"]
        return None

    def _with_dangerous_action_receipt(
        self,
        payload: dict[str, Any],
        receipt: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if not receipt:
            return payload
        result = dict(payload)
        safe_receipt = dict(receipt)
        safe_receipt["execution_result"] = "ok" if bool(result.get("ok")) else "failed"
        if result.get("error_code"):
            safe_receipt["execution_error_code"] = result.get("error_code")
        result["dangerous_action_receipt"] = safe_receipt
        return result

    def _dangerous_action_policy(self, route: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        if route not in DANGEROUS_WEB_CONFIRMATION_ROUTES:
            return None
        direct_executor_policy = DANGEROUS_DIRECT_EXECUTOR_ROUTES.get(route)
        if direct_executor_policy is not None:
            action_type, executor_mode = direct_executor_policy
            return self._dangerous_executor_action_policy(
                action_type=action_type,
                route=route,
                executor_mode=executor_mode,
                operation=None,
                background_job=False,
            )
        plan_state_route_policy = DANGEROUS_PLAN_STATE_ROUTES.get(route)
        if plan_state_route_policy is not None:
            return self._dangerous_plan_state_action_policy(
                action_type=str(plan_state_route_policy["action_type"]),
                route=route,
                operation=str(plan_state_route_policy["operation"]),
                risk_class=str(plan_state_route_policy["risk_class"]),
                title=str(plan_state_route_policy["title"]),
                background_job=False,
            )
        if route == "/api/commit-confirm":
            return self._dangerous_git_commit_confirm_policy()
        if route == "/api/jobs/start":
            operation = str(payload.get("operation") or "").strip()
            job_executor_policy = DANGEROUS_JOB_EXECUTOR_OPERATIONS.get(operation)
            if job_executor_policy is not None:
                action_type, executor_mode = job_executor_policy
                return self._dangerous_executor_action_policy(
                    action_type=action_type,
                    route=route,
                    executor_mode=executor_mode,
                    operation=operation,
                    background_job=True,
                )
            job_plan_state_policy = DANGEROUS_JOB_PLAN_STATE_OPERATIONS.get(operation)
            if job_plan_state_policy is not None:
                return self._dangerous_plan_state_action_policy(
                    action_type=str(job_plan_state_policy["action_type"]),
                    route=route,
                    operation=operation,
                    risk_class=str(job_plan_state_policy["risk_class"]),
                    title=str(job_plan_state_policy["title"]),
                    background_job=True,
                )
            return None
        if route == "/api/switch-executor":
            provider = str(payload.get("provider") or "").strip().lower()
            return {
                "action_type": "switch_executor",
                "risk_class": "dangerous_write",
                "target_summary": {"provider": provider or "unknown"},
                "display_summary": {
                    "title": "Switch executor",
                    "target": provider or "unknown",
                },
            }
        if route == "/api/switch-project":
            target = self._dangerous_target_project_summary(payload)
            return {
                "action_type": "switch_project",
                "risk_class": "identity_or_registry_action",
                "target_summary": target,
                "display_summary": {
                    "title": "Switch project",
                    "target": target.get("project_name") or target.get("project_id") or target.get("project_root") or "unknown",
                },
            }
        if route == "/api/project-identity/apply":
            preview_id = str(payload.get("preview_id") or "").strip()
            return {
                "action_type": "project_identity_apply",
                "risk_class": "identity_or_registry_action",
                "target_summary": {
                    "preview_id_present": bool(preview_id),
                    "preview_id": "REDACTED" if preview_id else "",
                },
                "display_summary": {
                    "title": "Apply project identity migration",
                    "target": "project identity preview",
                },
            }
        if route == "/api/v2/action":
            next_action = payload.get("next_action")
            if not isinstance(next_action, dict):
                return None
            action_name = str(next_action.get("action") or "").strip().lower()
            if action_name not in DANGEROUS_REGISTRY_ACTIONS:
                return None
            params = next_action.get("params") if isinstance(next_action.get("params"), dict) else {}
            display_summary = self._registry_action_display_summary(action_name, params)
            return {
                "action_type": action_name,
                "risk_class": "identity_or_registry_action",
                "target_summary": {
                    "action": action_name,
                    "project": self._dangerous_target_project_summary(params),
                },
                "display_summary": display_summary,
            }
        return None

    def _registry_action_display_summary(self, action_name: str, params: dict[str, Any]) -> dict[str, str]:
        target = self._dangerous_target_project_summary(params)
        project_label = (
            target.get("project_name")
            or target.get("project_id")
            or target.get("project_root")
            or "目标项目"
        )
        project_root = target.get("project_root")
        if action_name == "project_registry_unregister":
            target_text = str(project_label)
            if project_root and project_root != project_label:
                target_text = f"{target_text} ｜ {project_root}"
            return {
                "title": "移出项目登记",
                "target": f"{target_text}（只移出登记，不删除磁盘文件）",
            }
        if action_name == "project_registry_prune_unavailable":
            return {
                "title": "清理不可用项目登记",
                "target": "不可用登记（保留当前项目，不删除磁盘文件）",
            }
        if action_name == "project_registry_prune_temporary":
            return {
                "title": "清理临时项目登记",
                "target": "临时登记（保留当前项目，不删除磁盘文件）",
            }
        return {
            "title": "项目登记操作",
            "target": str(action_name or "unknown"),
        }

    def _dangerous_executor_action_policy(
        self,
        *,
        action_type: str,
        route: str,
        executor_mode: str,
        operation: str | None,
        background_job: bool,
    ) -> dict[str, Any]:
        context = self._dangerous_executor_context(executor_mode)
        target_summary = {
            "executor_mode": executor_mode,
            "operation": operation or action_type,
            "background_job": background_job,
            "project_root": self.project_root,
            "current_head": context.get("current_head") or "",
            "current_version": context.get("current_version") or "",
            "current_version_index": context.get("current_version_index"),
            "plan_step": context.get("plan_step") or "",
            "runner_status": context.get("runner_status") or "",
            "allowed_working_directory": self.project_root,
            "expected_mutation_scope": [
                "project files allowed by the current plan",
                f"{self.runner_rel_dir}/runtime/**",
                f"{self.runner_rel_dir}/logs/**",
                f"{self.runner_rel_dir}/reports/**",
            ],
            "blocked_paths": [
                ".git/**",
                ".github/workflows/**",
                "remote repositories",
            ],
            "git_commit_allowed": False,
            "git_push_allowed": False,
            "external_network_allowed": False,
        }
        title = "Run current version" if executor_mode == "run" else "Fix current version"
        if background_job:
            title = f"Start background executor job: {title}"
        return {
            "action_type": action_type,
            "risk_class": "executor_action",
            "target_summary": target_summary,
            "display_summary": {
                "title": title,
                "target": context.get("current_version") or "current version",
                "executor_mode": executor_mode,
                "expected_writable_scope": "current project files allowed by plan plus ColaMeta runtime metadata",
                "post_checks": "executor acceptance workflow and post-run scope validation remain required",
                "rollback_guidance": "Review the executor report, inspect the resulting diff, and revert or repair project changes before any commit or push.",
            },
        }

    def _dangerous_git_commit_confirm_policy(self) -> dict[str, Any]:
        target_summary = self._dangerous_commit_preview_summary()
        return {
            "action_type": "git_commit_confirm",
            "risk_class": "git_local_history_action",
            "target_summary": target_summary,
            "display_summary": {
                "title": "Confirm local Git commit",
                "target": target_summary.get("version") or "current version",
                "rollback_guidance": "Inspect the new local commit and use normal Git history repair if the commit should be changed before any push.",
            },
            "guard_plan_signature": True,
            "guard_commit_preview_signature": True,
        }

    def _dangerous_commit_preview_summary(self) -> dict[str, Any]:
        preview = self.pending_commit_preview if isinstance(self.pending_commit_preview, dict) else {}
        files = preview.get("commit_files") if isinstance(preview.get("commit_files"), list) else []
        commit_files = sorted(str(item) for item in files if isinstance(item, str))
        preview_id = preview.get("preview_id") if isinstance(preview.get("preview_id"), str) else ""
        preview_project_root = preview.get("project_root")
        project_root = preview_project_root if isinstance(preview_project_root, str) and preview_project_root.strip() else self.project_root
        return {
            "operation": "commit_confirm",
            "preview_ready": bool(preview_id),
            "preview_id_present": bool(preview_id),
            "project_root": os.path.abspath(project_root),
            "version": preview.get("version") if isinstance(preview.get("version"), str) else "",
            "diff_hash": preview.get("diff_hash") if isinstance(preview.get("diff_hash"), str) else "",
            "commit_file_count": len(commit_files),
            "commit_files": commit_files,
            "git_commit_allowed": True,
            "git_push_allowed": False,
            "git_pull_allowed": False,
            "remote_mutation_allowed": False,
        }

    def _dangerous_plan_state_action_policy(
        self,
        *,
        action_type: str,
        route: str,
        operation: str,
        risk_class: str,
        title: str,
        background_job: bool,
    ) -> dict[str, Any]:
        target_summary = self._dangerous_plan_state_summary(
            operation=operation,
            background_job=background_job,
        )
        return {
            "action_type": action_type,
            "risk_class": risk_class,
            "target_summary": target_summary,
            "display_summary": {
                "title": title,
                "target": target_summary.get("current_version") or "managed plan",
                "rollback_guidance": "Review the plan and runner state diff, then restore or repair the specific ColaMeta plan/state files if needed.",
            },
            "guard_plan_signature": True,
            "guard_patch_signature": operation == "auto_apply_patches",
        }

    def _dangerous_plan_state_summary(self, *, operation: str, background_job: bool) -> dict[str, Any]:
        plan = self._read_json_file(self.plan_file) or {}
        state = self._read_json_file(self.state_file) or {}
        plan_versions = plan.get("versions") if isinstance(plan.get("versions"), list) else []
        current_version = state.get("current_version") if isinstance(state.get("current_version"), str) else ""
        current_version_index = state.get("current_version_index")
        current_item = self._dangerous_current_plan_item(plan_versions, current_version, current_version_index)
        summary: dict[str, Any] = {
            "operation": operation,
            "background_job": background_job,
            "project_root": self.project_root,
            "plan_file": self._to_project_relative(self.plan_file),
            "state_file": self._to_project_relative(self.state_file),
            "current_version": current_version,
            "current_version_index": current_version_index,
            "runner_status": state.get("status") if isinstance(state.get("status"), str) else "",
            "plan_version_count": len(plan_versions),
        }
        if operation == "auto_apply_patches":
            summary["plan_patch_inventory"] = self._dangerous_plan_patch_inventory()
            summary["max_auto_apply_batch_size"] = 5
        elif operation == "continue_next_version":
            summary["next_version"] = self._dangerous_next_enabled_version(plan_versions, current_version_index)
        elif operation == "rerun_acceptance":
            commands = current_item.get("acceptance_commands") if isinstance(current_item, dict) else None
            summary["acceptance_command_count"] = len(commands) if isinstance(commands, list) else 0
        elif operation == "checkpoint_review":
            review_policy = plan.get("review_policy") if isinstance(plan.get("review_policy"), dict) else {}
            after_versions = review_policy.get("after_versions") if isinstance(review_policy.get("after_versions"), list) else []
            summary["checkpoint_version_count"] = len(after_versions)
            summary["current_version_is_checkpoint"] = current_version in after_versions
        return summary

    @staticmethod
    def _dangerous_current_plan_item(
        plan_versions: list[Any],
        current_version: str,
        current_version_index: Any,
    ) -> dict[str, Any]:
        if isinstance(current_version_index, int) and 0 <= current_version_index < len(plan_versions):
            item = plan_versions[current_version_index]
            if isinstance(item, dict):
                return item
        if current_version:
            for item in plan_versions:
                if isinstance(item, dict) and item.get("version") == current_version:
                    return item
        return {}

    @staticmethod
    def _dangerous_next_enabled_version(plan_versions: list[Any], current_version_index: Any) -> str:
        start_index = current_version_index + 1 if isinstance(current_version_index, int) else 0
        for item in plan_versions[start_index:]:
            if not isinstance(item, dict):
                continue
            if item.get("enabled", True) is False:
                continue
            version = item.get("version")
            return version if isinstance(version, str) else ""
        return ""

    def _dangerous_plan_patch_inventory(self) -> dict[str, Any]:
        patch_dir = Path(self.runner_dir) / "plan-patches"
        if not patch_dir.is_dir():
            return {
                "patch_dir_present": False,
                "patch_json_count": 0,
                "pending_patch_count": 0,
                "read_error_count": 0,
            }
        patch_json_count = 0
        pending_patch_count = 0
        read_error_count = 0
        for patch_file in sorted(patch_dir.glob("*.json")):
            if not patch_file.is_file():
                continue
            patch_json_count += 1
            try:
                payload = json.loads(patch_file.read_text(encoding="utf-8"))
            except Exception:
                read_error_count += 1
                continue
            status = str(payload.get("status", "PENDING")).strip() or "PENDING"
            if status == "PENDING":
                pending_patch_count += 1
        return {
            "patch_dir_present": True,
            "patch_json_count": patch_json_count,
            "pending_patch_count": pending_patch_count,
            "read_error_count": read_error_count,
        }

    def _dangerous_executor_context(self, executor_mode: str) -> dict[str, Any]:
        state = self._read_json_file(self.state_file) or {}
        plan = self._read_json_file(self.plan_file) or {}
        current_version = state.get("current_version")
        current_version_index = state.get("current_version_index")
        runner_status = state.get("status")
        plan_versions = plan.get("versions") if isinstance(plan, dict) else None
        plan_step = None
        if isinstance(plan_versions, list) and isinstance(current_version_index, int):
            if 0 <= current_version_index < len(plan_versions):
                version_data = plan_versions[current_version_index]
                if isinstance(version_data, dict):
                    plan_step = version_data.get("name") or version_data.get("title") or version_data.get("version")
        return {
            "executor_mode": executor_mode,
            "current_head": self._dangerous_current_head(),
            "current_version": current_version if isinstance(current_version, str) else "",
            "current_version_index": current_version_index,
            "runner_status": runner_status if isinstance(runner_status, str) else "",
            "plan_step": plan_step if isinstance(plan_step, str) else "",
        }

    def _dangerous_target_project_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        project_id = payload.get("project_id") if isinstance(payload.get("project_id"), str) else None
        project_root = payload.get("project_root") if isinstance(payload.get("project_root"), str) else None
        normalized_root = None
        if project_root and project_root.strip():
            normalized_root = os.path.realpath(os.path.abspath(os.path.expanduser(project_root.strip())))
        project_name = None
        for project in self.project_registry.list_projects().get("projects", []):
            if not isinstance(project, dict):
                continue
            if project_id and project.get("project_id") == project_id:
                project_name = project.get("project_name") if isinstance(project.get("project_name"), str) else None
                normalized_root = project.get("project_root") if isinstance(project.get("project_root"), str) else normalized_root
                break
            if normalized_root and project.get("project_root") == normalized_root:
                project_id = project.get("project_id") if isinstance(project.get("project_id"), str) else project_id
                project_name = project.get("project_name") if isinstance(project.get("project_name"), str) else None
                break
        return {
            "project_id": project_id,
            "project_name": project_name,
            "project_root": normalized_root,
        }

    def _dangerous_action_context(self) -> dict[str, Any]:
        project = self.project_registry.get_project(self.project_root).get("project")
        if not isinstance(project, dict):
            project = {}
        return {
            "project_root": self.project_root,
            "project_id": project.get("project_id") if isinstance(project.get("project_id"), str) else None,
            "project_name": project.get("project_name") if isinstance(project.get("project_name"), str) else None,
            "current_head": self._dangerous_current_head(),
            "state_signature": self._dangerous_file_signature(self.state_file),
            "plan_signature": self._dangerous_file_signature(self.plan_file),
            "patch_signature": self._dangerous_plan_patch_signature(),
            "commit_preview_signature": self._dangerous_commit_preview_signature(),
            "registry_signature": self._dangerous_file_signature(self.project_registry.registry_path()),
        }

    def _dangerous_current_head(self) -> str | None:
        try:
            completed = subprocess.run(
                ["git", "-C", self.project_root, "rev-parse", "HEAD"],
                check=False,
                capture_output=True,
                text=True,
                timeout=2,
            )
        except Exception:
            return None
        if completed.returncode != 0:
            return None
        head = completed.stdout.strip()
        return head if head else None

    @staticmethod
    def _dangerous_file_signature(path: str | None) -> str | None:
        if not path:
            return None
        file_path = Path(path)
        if not file_path.is_file():
            return "missing"
        try:
            digest = hashlib.sha256(file_path.read_bytes()).hexdigest()
            stat = file_path.stat()
            return f"sha256:{digest}:size:{stat.st_size}"
        except Exception:
            return "unreadable"

    def _dangerous_plan_patch_signature(self) -> str:
        patch_dir = Path(self.runner_dir) / "plan-patches"
        if not patch_dir.exists():
            return "missing"
        if not patch_dir.is_dir():
            return "not-directory"
        entries: list[dict[str, Any]] = []
        for patch_file in sorted(patch_dir.glob("*.json")):
            if not patch_file.is_file():
                continue
            try:
                content = patch_file.read_bytes()
                stat = patch_file.stat()
                entries.append({
                    "name": patch_file.name,
                    "size": stat.st_size,
                    "sha256": hashlib.sha256(content).hexdigest(),
                })
            except Exception:
                entries.append({
                    "name": patch_file.name,
                    "error": "unreadable",
                })
        digest = hashlib.sha256(
            json.dumps(entries, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return f"dir-sha256:{digest}:files:{len(entries)}"

    def _dangerous_commit_preview_signature(self) -> str:
        preview = self.pending_commit_preview if isinstance(self.pending_commit_preview, dict) else {}
        preview_id = preview.get("preview_id") if isinstance(preview.get("preview_id"), str) else ""
        if not preview_id:
            return "missing"
        files = preview.get("commit_files") if isinstance(preview.get("commit_files"), list) else []
        commit_files = sorted(str(item) for item in files if isinstance(item, str))
        preview_project_root = preview.get("project_root")
        project_root = preview_project_root if isinstance(preview_project_root, str) and preview_project_root.strip() else self.project_root
        signature_payload = {
            "preview_id": preview_id,
            "diff_hash": preview.get("diff_hash") if isinstance(preview.get("diff_hash"), str) else "",
            "commit_files": commit_files,
            "version": preview.get("version") if isinstance(preview.get("version"), str) else "",
            "project_root": os.path.abspath(project_root),
        }
        digest = hashlib.sha256(
            json.dumps(signature_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return f"commit-preview-sha256:{digest}"

    def _validate_run_preview_request(self, body: dict[str, Any] | None) -> dict[str, Any] | None:
        payload = body or {}
        if payload.get("project_root") is not None:
            return {
                "ok": False,
                "error_code": "INVALID_PARAMS",
                "message": "project_root is not allowed.",
            }
        return None

    def _is_pending_run_preview_expired(self, preview: dict[str, Any]) -> bool:
        created_ts = preview.get("created_ts")
        try:
            created = float(created_ts)
        except (TypeError, ValueError):
            return True
        now_ts = datetime.now(timezone.utc).timestamp()
        return (now_ts - created) > 3600

    def _validate_run_confirm_request(self, body: dict[str, Any] | None) -> dict[str, Any] | None:
        payload = body or {}
        if payload.get("project_root") is not None:
            return {
                "ok": False,
                "error_code": "INVALID_PARAMS",
                "message": "project_root is not allowed.",
            }
        preview = self.pending_run_preview
        if not isinstance(preview, dict):
            return {
                "ok": False,
                "error_code": "RUN_PREVIEW_REQUIRED",
                "message": "请先为当前项目生成运行预览。",
            }
        if self._is_pending_run_preview_expired(preview):
            self.pending_run_preview = None
            return {
                "ok": False,
                "error_code": "PREVIEW_EXPIRED",
                "message": "运行预览已过期，请重新生成。",
            }
        return None

    def _connector_runtime_local_service_evidence(self) -> dict[str, Any]:
        metadata = self._current_process_service_metadata()
        if metadata is None:
            metadata = self._stored_service_metadata_if_current()
        if metadata is None:
            return {
                "state": "unknown",
                "health_source": "web_console_api_status",
                "project_root": self.project_root,
                "web": {"enabled": True, "state": "healthy"},
                "mcp": {"enabled": None, "state": "unknown"},
            }

        web_state, mcp_state = self._probe_service_endpoint_health(metadata)
        return {
            "state": "running",
            "health_source": "process_table" if metadata.get("discovered_from_process_table") else "metadata",
            "pid": metadata.get("pid"),
            "project_root": metadata.get("project_root") or self.project_root,
            "metadata_project_matches": self._service_metadata_matches_project(metadata),
            "discovered_from_process_table": metadata.get("discovered_from_process_table"),
            "enable_web": metadata.get("enable_web"),
            "web_state": web_state,
            "web_url": metadata.get("web_url"),
            "web_host": metadata.get("web_host"),
            "web_port": metadata.get("web_port"),
            "enable_mcp": metadata.get("enable_mcp"),
            "mcp_state": mcp_state,
            "mcp_url": metadata.get("mcp_url"),
            "mcp_host": metadata.get("mcp_host"),
            "mcp_port": metadata.get("mcp_port"),
        }

    def _current_process_service_metadata(self) -> dict[str, Any] | None:
        parts = ServiceLifecycleStore.read_process_cmdline_parts(os.getpid()) or []
        for index, token in enumerate(parts):
            if token != "serve" or index + 1 >= len(parts):
                continue
            project_token = parts[index + 1]
            if not self._project_token_matches(project_token):
                continue
            args = parts[index + 2:]
            enable_web = "--no-web" not in args
            enable_mcp = "--no-mcp" not in args
            web_host = self._cmd_option_value(args, "--web-host", "127.0.0.1")
            web_port = self._cmd_option_int(args, "--web-port", 8799)
            mcp_host = self._cmd_option_value(args, "--mcp-host", "127.0.0.1")
            mcp_port = self._cmd_option_int(args, "--mcp-port", 8765)
            return {
                "pid": os.getpid(),
                "project_root": self.project_root,
                "web_host": web_host,
                "web_port": web_port,
                "mcp_host": mcp_host,
                "mcp_port": mcp_port,
                "web_url": f"http://{web_host}:{web_port}" if enable_web else None,
                "mcp_url": f"http://{mcp_host}:{mcp_port}/mcp" if enable_mcp else None,
                "enable_web": enable_web,
                "enable_mcp": enable_mcp,
                "discovered_from_process_table": True,
            }
        return None

    def _stored_service_metadata_if_current(self) -> dict[str, Any] | None:
        metadata = ServiceLifecycleStore(self.project_root).read_metadata()
        if not isinstance(metadata, dict) or not self._service_metadata_matches_project(metadata):
            return None
        pid = metadata.get("pid")
        if not isinstance(pid, int) or not ServiceLifecycleStore.is_pid_running(pid):
            return None
        if ServiceLifecycleStore.pid_matches_metadata(pid, metadata) is False:
            return None
        payload = dict(metadata)
        payload.setdefault("discovered_from_process_table", False)
        return payload

    def _probe_service_endpoint_health(self, metadata: dict[str, Any]) -> tuple[str | None, str | None]:
        web_state = "healthy" if metadata.get("enable_web") else None
        mcp_state: str | None = None
        if metadata.get("enable_mcp"):
            mcp_state = (
                "healthy"
                if self._local_http_healthz_ok(metadata.get("mcp_host"), metadata.get("mcp_port"), "colameta-mcp")
                else "starting"
            )
        return web_state, mcp_state

    @staticmethod
    def _local_http_healthz_ok(host: Any, port: Any, expected_service: str) -> bool:
        host_text = str(host or "").strip()
        if not _is_loopback_host(host_text):
            return False
        try:
            port_int = int(port)
        except (TypeError, ValueError):
            return False
        if port_int <= 0:
            return False
        try:
            with urllib.request.urlopen(f"http://{host_text}:{port_int}/healthz", timeout=2) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception:
            return False
        return bool(isinstance(payload, dict) and payload.get("ok") is True and payload.get("service") == expected_service)

    def _service_metadata_matches_project(self, metadata: dict[str, Any]) -> bool:
        root = metadata.get("project_root")
        if not isinstance(root, str) or not root.strip():
            return False
        return os.path.realpath(os.path.abspath(os.path.expanduser(root))) == self.project_root

    def _project_token_matches(self, value: str) -> bool:
        return os.path.realpath(os.path.abspath(os.path.expanduser(value))) == self.project_root

    @staticmethod
    def _cmd_option_value(args: list[str], name: str, default: str) -> str:
        for index, token in enumerate(args):
            if token == name and index + 1 < len(args):
                return args[index + 1]
            if token.startswith(name + "="):
                return token.split("=", 1)[1]
        return default

    @staticmethod
    def _cmd_option_int(args: list[str], name: str, default: int) -> int:
        try:
            return int(WebConsoleServer._cmd_option_value(args, name, str(default)))
        except ValueError:
            return default

    def _api_status(self) -> dict[str, Any]:
        try:
            data = self.bridge.get_runner_status(self.project_root)
        except Exception as e:
            return {"ok": False, "message": str(e)}
        data["ok"] = True
        data["plan_reload_needed"] = self._is_plan_reload_needed()
        data["plan_file"] = self.plan_file
        data["mcp_hint"] = "MCP：只读 + 生成计划更新；应用由 Web Console 本地自动完成。"
        data["operation_running"] = self.operation_running
        data["operation_name"] = self.operation_name
        data["operation_started_at"] = self.operation_started_at
        data["last_operation_result"] = self.last_operation_result
        data["pending_commit_preview_ready"] = bool(
            self.pending_commit_preview
            and isinstance(self.pending_commit_preview.get("commit_files"), list)
            and len(self.pending_commit_preview.get("commit_files", [])) > 0
        )
        data["remote_git"] = self._api_remote_git_status()
        data["execution_display"] = self._api_execution_display()
        data["project_registry"] = self._api_project_registry()
        local_service = self._connector_runtime_local_service_evidence()
        data["connector_runtime_health"] = get_connector_runtime_health_status(
            runtime_status=get_runtime_version_status(self.project_root, local_service=local_service),
            local_service=local_service,
        )
        try:
            data["executor_session_status"] = self.executor_session_store.get_status()
        except Exception:
            data["executor_session_status"] = {
                "ok": False,
                "active": False,
                "message": "执行会话状态读取失败。",
            }
        try:
            data["executor_continuation_preview"] = self.executor_session_store.get_continuation_preview()
        except Exception:
            data["executor_continuation_preview"] = {
                "ok": False,
                "continuation_available": False,
                "message": "执行会话续接预览读取失败。",
            }
        current_provider = self._resolve_current_execution_provider(
            fallback_provider=data["execution_display"].get("provider", DEFAULT_EXECUTION_PROVIDER)
        )
        try:
            data["executor_continuation_decision"] = self.executor_session_store.get_continuation_decision(
                requested_provider=current_provider
            )
        except Exception:
            data["executor_continuation_decision"] = {
                "ok": False,
                "decision": "start_new_blocked",
                "continuation_available": False,
                "message": "执行会话续接决策读取失败。",
            }
        try:
            data["executor_resume_invocation_preview"] = self.executor_session_store.get_resume_invocation_preview(
                requested_provider=current_provider
            )
        except Exception:
            data["executor_resume_invocation_preview"] = {
                "ok": False,
                "resume_invocation_supported": False,
                "resume_invocation_verified": False,
                "resume_invocation_kind": "preview_unavailable",
                "command_preview": [],
                "message": "执行会话调用形态预览读取失败。",
            }
        self._apply_executor_session_head_mismatch_classification(data)
        data["executor_session_display"] = build_executor_session_display(
            executor_session_status=data.get("executor_session_status"),
            continuation_decision=data.get("executor_continuation_decision"),
            resume_invocation_preview=data.get("executor_resume_invocation_preview"),
            continuation_preview=data.get("executor_continuation_preview"),
        )
        data["executor_auto_resume_policy"] = {
            "policy": "auto_when_safe",
            "provider_scope": ["codex", "opencode"],
            "enabled_for_current_provider": current_provider in {"codex", "opencode"},
        }
        data["executor_inventory_summary"] = get_executor_inventory_summary(
            self.project_root,
            data["execution_display"].get("provider", DEFAULT_EXECUTION_PROVIDER),
        )
        data["project_identity"] = build_project_identity(self.project_root)
        try:
            branch_ctrl = ExecutionBranchController(self.project_root)
            data["execution_branch_status"] = branch_ctrl.get_status()
            review = branch_ctrl.get_review_summary()
            data["execution_branch_review"] = review
            _, plan, state, _, _ = self._load_runtime_context()
            settings_provider = data["execution_display"].get("provider", DEFAULT_EXECUTION_PROVIDER)
            cv = plan.versions[state.current_version_index] if state.current_version_index is not None and 0 <= state.current_version_index < len(plan.versions) else None
            resolved_provider = resolve_version_execution_provider(plan=plan, version=cv, fallback_provider=settings_provider)
            require_branch = self._should_require_execution_branch(
                current_version=cv,
                resolved_provider=resolved_provider,
                mainline_provider=settings_provider,
            )
            guard = branch_ctrl.validate_execution_ready(version=cv.version if cv else "", provider=resolved_provider, require_branch=require_branch)
            data["execution_branch_guard"] = guard
        except Exception:
            data["execution_branch_status"] = {"ok": False, "message": "读取执行安全分支状态失败。"}
            data["execution_branch_guard"] = {"required": False, "ok": False, "message": "读取执行安全分支状态失败。"}
            data["execution_branch_review"] = {"ok": False, "message": "读取执行安全分支审查摘要失败。"}
        try:
            _, plan, state, _, _ = self._load_runtime_context()
            current_version = plan.versions[state.current_version_index] if state.current_version_index is not None and 0 <= state.current_version_index < len(plan.versions) else None
            fallback_provider = data["execution_display"].get("provider", DEFAULT_EXECUTION_PROVIDER)
            settings = self.runner_settings_store.load_for_project(self.project_root, self.plan_file)
            data["version_execution_display"] = get_version_execution_summary(
                plan=plan, version=current_version, fallback_provider=fallback_provider, settings=settings,
            )
        except Exception:
            data["version_execution_display"] = None
        return data

    def _web_commander_runtime_summary(
        self,
        *,
        runtime_status: dict[str, Any],
        connector_health: dict[str, Any],
        local_service: dict[str, Any],
    ) -> dict[str, Any]:
        loaded_module_verification = runtime_status.get("loaded_module_verification")
        if not isinstance(loaded_module_verification, dict):
            loaded_module_verification = {}
        connector_closeout = connector_health.get("operator_closeout")
        if not isinstance(connector_closeout, dict):
            connector_closeout = {}
        local_health = connector_health.get("local_service")
        if not isinstance(local_health, dict):
            local_health = {}
        external_health = connector_health.get("external_connector")
        if not isinstance(external_health, dict):
            external_health = {}

        profile_ids = (
            "web_gpt_commander",
            "local_codex_commander",
            "planner_agent",
            "reviewer_agent",
            "source_observer",
        )
        profile_labels = {
            "web_gpt_commander": "Web GPT",
            "local_codex_commander": "Local Codex",
            "planner_agent": "Planner",
            "reviewer_agent": "Reviewer",
            "source_observer": "Source Observer",
        }
        profiles = [
            {
                "profile_id": profile_id,
                "display_name": profile_labels[profile_id],
                "polling_guidance": polling_guidance_for_profile(profile_id),
            }
            for profile_id in profile_ids
        ]

        project_identity = build_project_identity(self.project_root)
        project_name = str(project_identity.get("project_name") or "colameta-self-dev")
        readiness = build_service_readiness_summary(
            runtime_status=runtime_status,
            connector_health=connector_health,
            project_name=project_name,
        )
        apps_connector_closeout = build_apps_connector_closeout_packet(
            project_name=project_name,
            connector_health=connector_health,
        )
        stable_metadata = git_checkout_metadata(DEFAULT_STABLE_RUNTIME_DIR)
        stable_replacement_cadence = build_stable_replacement_cadence(
            project_root=self.project_root,
            candidate_head=runtime_status.get("project_checkout_head")
            if isinstance(runtime_status.get("project_checkout_head"), str)
            else None,
            stable_runtime_dir=DEFAULT_STABLE_RUNTIME_DIR,
            stable_runtime_head=stable_metadata.get("head") if isinstance(stable_metadata.get("head"), str) else None,
        )
        product_readiness_context = {
            "status": readiness.get("status"),
            "ready": readiness.get("status") == "ready",
            "primary_blocker": readiness.get("primary_blocker"),
            "safe_next_action": (readiness.get("safe_next_actions") or [{}])[0]
            if isinstance(readiness.get("safe_next_actions"), list)
            else None,
        }
        try:
            product_console_map = build_product_console_map(
                self.project_root,
                project_name=project_name,
                readiness_packet=product_readiness_context,
            )
        except Exception as exc:
            product_console_map = {
                "ok": False,
                "source": "product_console_map",
                "read_only": True,
                "side_effects": False,
                "status": "unknown",
                "error": str(exc),
                "completion_surface": {
                    "source": "product_console_completion_surface",
                    "schema_version": "product_console_completion_surface.v1",
                    "read_only": True,
                    "side_effects": False,
                    "status": "unknown",
                    "ready": False,
                    "summary": "Product Console completion surface is unavailable.",
                    "progress_state": {
                        "source": "product_console_closeout_progress_state",
                        "schema_version": "product_console_closeout_progress_state.v1",
                        "read_only": True,
                        "side_effects": False,
                        "status": "not_started",
                        "label": "Not Started",
                        "severity": "needs_attention",
                        "completion_status": "unknown",
                        "ready": False,
                        "message": "Product Console completion progress is unavailable.",
                        "next_step": "Re-read Product Console before choosing a closeout action.",
                        "operator_guidance": [
                            "Do not accept closeout while the Product Console map is unavailable.",
                            "Use get_product_console_map to refresh the read-only completion surface.",
                        ],
                        "recommended_action": {
                            "tool": "get_product_console_map",
                            "required_scope": "mcp:read",
                            "why": "Refresh the Product Console map to inspect closeout completion.",
                        },
                        "followup_count": 1,
                        "gap_count": 1,
                        "pending_refresh_count": 0,
                        "stale_result_count": 0,
                        "stored_result_count": 0,
                        "submission_evidence_activity_recorded": False,
                    },
                    "gap_count": 1,
                    "gaps": [
                        {
                            "code": "PRODUCT_CONSOLE_MAP_UNAVAILABLE",
                            "component": "product_console_map",
                            "severity": "needs_attention",
                            "status": "unknown",
                        }
                    ],
                    "safe_next_action": {
                        "action": "read_product_console_map",
                        "tool": "get_product_console_map",
                        "authority": "read_only",
                        "why": "Refresh the Product Console map to inspect closeout completion.",
                    },
                },
            }
        apps_smoke_call = apps_connector_closeout.get("preferred_smoke_tool")
        if not isinstance(apps_smoke_call, dict):
            apps_smoke_call = {
                "tool": "get_apps_connector_smoke_packet",
                "arguments": {"project_name": project_name},
            }
        copyable_mcp_calls = [
            {
                "label": "读取项目列表",
                "tool": "list_registered_projects",
                "arguments": {},
            },
            {
                "label": "Agent flow packet",
                "tool": "get_agent_operator_flow_packet",
                "arguments": {"project_name": project_name, "profile_id": "web_gpt_commander"},
            },
            {
                "label": "Apps smoke packet",
                "tool": str(apps_smoke_call.get("tool") or "get_apps_connector_smoke_packet"),
                "arguments": apps_smoke_call.get("arguments") if isinstance(apps_smoke_call.get("arguments"), dict) else {"project_name": project_name},
            },
            {
                "label": "Stable cadence",
                "tool": "get_stable_replacement_cadence",
                "arguments": {"project_name": project_name},
            },
            {
                "label": "Parallel plan preview",
                "tool": "get_stage_parallel_plan_preview",
                "arguments": {"project_name": project_name},
            },
            {
                "label": "Parallel run preview",
                "tool": "get_stage_parallel_run_preview",
                "arguments": {"project_name": project_name},
            },
            {
                "label": "Parallel worktree assignment",
                "tool": "get_stage_parallel_worktree_assignment_preview",
                "arguments": {"project_name": project_name},
            },
            {
                "label": "Parallel next action",
                "tool": "get_stage_parallel_next_action_packet",
                "arguments": {"project_name": project_name},
            },
            {
                "label": "Parallel worktree apply preview",
                "tool": "manage_stage_parallel_worktrees",
                "arguments": {
                    "project_name": project_name,
                    "action": "preview",
                    "stage_id": "stage_parallel_automation",
                },
            },
            {
                "label": "Parallel shard inputs preview",
                "tool": "manage_stage_parallel_shard_inputs",
                "arguments": {
                    "project_name": project_name,
                    "action": "preview",
                    "stage_id": "stage_parallel_automation",
                },
            },
            {
                "label": "Parallel executor group",
                "tool": "get_stage_parallel_executor_group_preview",
                "arguments": {"project_name": project_name},
            },
            {
                "label": "Parallel executor group apply preview",
                "tool": "manage_stage_parallel_executor_group",
                "arguments": {
                    "project_name": project_name,
                    "action": "preview",
                    "stage_id": "stage_parallel_automation",
                },
            },
            {
                "label": "Parallel executor runs apply preview",
                "tool": "manage_stage_parallel_executor_runs",
                "arguments": {
                    "project_name": project_name,
                    "action": "preview",
                    "stage_id": "stage_parallel_automation",
                },
            },
            {
                "label": "Parallel executor results packet",
                "tool": "get_stage_parallel_executor_results_packet",
                "arguments": {"project_name": project_name},
            },
            {
                "label": "Parallel group status",
                "tool": "get_stage_parallel_group_status",
                "arguments": {"project_name": project_name},
            },
            {
                "label": "Parallel merge preview",
                "tool": "get_stage_parallel_merge_preview",
                "arguments": {"project_name": project_name},
            },
            {
                "label": "Parallel merge apply preview",
                "tool": "manage_stage_parallel_merges",
                "arguments": {
                    "project_name": project_name,
                    "action": "preview",
                    "stage_id": "stage_parallel_automation",
                },
            },
            {
                "label": "Parallel closeout packet",
                "tool": "get_stage_parallel_closeout_packet",
                "arguments": {"project_name": project_name},
            },
            {
                "label": "读取 Web GPT 入口",
                "tool": "get_web_gpt_service_entrypoint",
                "arguments": {"project_name": project_name},
            },
            {
                "label": "打开 Commander App",
                "tool": "render_commander_app",
                "arguments": {"project_name": project_name, "profile_id": "web_gpt_commander"},
            },
            {
                "label": "读取 Commander manifest",
                "tool": "get_commander_app_manifest",
                "arguments": {"project_name": project_name, "profile_id": "web_gpt_commander"},
            },
            {
                "label": "读取 runtime 版本",
                "tool": "get_runtime_version_status",
                "arguments": {"project_name": project_name},
            },
            {
                "label": "读取 connector health",
                "tool": "get_connector_runtime_health_status",
                "arguments": {"project_name": project_name},
            },
            {
                "label": "Apps connector fallback",
                "tool": "get_connector_runtime_health_status",
                "arguments": apps_connector_closeout["connector_closeout_check"]["arguments"],
            },
            {
                "label": "Local Codex 执行器轮询",
                "tool": "manage_executor_workflow",
                "arguments": {
                    "action": "status",
                    "project_name": project_name,
                    "run_id": "<run_id>",
                    "profile_id": "local_codex_commander",
                    "poll_attempt": 1,
                },
            },
        ]

        return {
            "ok": True,
            "read_only": True,
            "side_effects": False,
            "project_name": project_name,
            "project_root": self.project_root,
            "readiness": readiness,
            "product_console_map": product_console_map,
            "product_console_completion": product_console_map.get("completion_surface")
            if isinstance(product_console_map.get("completion_surface"), dict)
            else {},
            "apps_connector_closeout": apps_connector_closeout,
            "apps_connector_tool_refresh": apps_connector_closeout.get("metadata_refresh_guidance"),
            "stable_replacement_cadence": stable_replacement_cadence,
            "service": {
                "pid": local_service.get("pid"),
                "health_source": local_service.get("health_source"),
                "web_url": local_service.get("web_url"),
                "web_state": local_service.get("web_state"),
                "mcp_url": local_service.get("mcp_url"),
                "mcp_state": local_service.get("mcp_state"),
            },
            "runtime": {
                "project_checkout_head": runtime_status.get("project_checkout_head"),
                "loaded_runtime_head": runtime_status.get("loaded_runtime_head"),
                "reload_needed_for_verification": runtime_status.get("reload_needed_for_verification"),
                "runtime_loaded_code_stale": runtime_status.get("runtime_loaded_code_stale"),
                "restart_needed_state": runtime_status.get("restart_needed_state"),
                "restart_needed_reason": runtime_status.get("restart_needed_reason"),
                "loaded_module_source_changed": runtime_status.get("loaded_module_source_changed"),
                "changed_module_count": loaded_module_verification.get("changed_module_count", 0),
                "unverified_module_count": loaded_module_verification.get("unverified_module_count", 0),
            },
            "connector": {
                "local_service_status": local_health.get("status"),
                "local_service_reason_code": local_health.get("reason_code"),
                "external_connector_status": external_health.get("status"),
                "external_connector_reason_code": external_health.get("reason_code"),
                "operator_closeout_status": connector_closeout.get("status"),
                "operator_closeout_decision": connector_closeout.get("decision"),
            },
            "profiles": profiles,
            "copyable_mcp_calls": copyable_mcp_calls,
            "authority_boundary": {
                "web_status_is_read_only": True,
                "does_not_authorize_executor_run": True,
                "does_not_authorize_commit_push_or_stable_replacement": True,
                "stable_replacement_requires_exact_commander_authorization": True,
            },
        }

    def _apply_executor_session_head_mismatch_classification(
        self,
        data: dict[str, Any],
        *,
        runner_status_data: dict[str, Any] | None = None,
        live_run: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        session_status = data.get("executor_session_status")
        if not isinstance(session_status, dict):
            try:
                session_status = self.executor_session_store.get_status()
                data["executor_session_status"] = session_status
            except Exception:
                session_status = {}

        existing = session_status.get("head_mismatch_classification") if isinstance(session_status, dict) else None
        if isinstance(existing, dict) and existing.get("status") == "none":
            classification = existing
        else:
            runner_data = runner_status_data if isinstance(runner_status_data, dict) else data
            if not (
                isinstance(runner_data, dict)
                and "runner_status" in runner_data
                and "current_version_status" in runner_data
            ):
                try:
                    runner_data = self.bridge.get_runner_status(self.project_root)
                except Exception:
                    runner_data = {}

            job_status = self._current_job_status_for_classification()
            latest_run_status, latest_claim_status, live_data = self._latest_run_evidence_for_classification(live_run)
            classification = classify_executor_session_head_mismatch(
                executor_session_status=session_status,
                operation_running=bool(self.operation_running),
                job_status=job_status,
                latest_run_status=latest_run_status,
                latest_claim_status=latest_claim_status,
                live_run=live_data,
                runner_status=str(runner_data.get("runner_status") or "") if isinstance(runner_data, dict) else None,
                current_version_status=(
                    str(runner_data.get("current_version_status") or "") if isinstance(runner_data, dict) else None
                ),
                worktree_clean=self._read_worktree_clean_for_status(),
            )

        if isinstance(session_status, dict):
            session_status["head_mismatch_classification"] = classification
        data["executor_session_head_mismatch"] = classification
        for key in (
            "executor_continuation_preview",
            "executor_continuation_decision",
            "executor_resume_invocation_preview",
        ):
            payload = data.get(key)
            if isinstance(payload, dict):
                payload["head_mismatch_classification"] = classification
        return classification

    def _current_job_status_for_classification(self) -> str | None:
        try:
            with self.operation_lock:
                job = dict(self.job) if isinstance(self.job, dict) else {}
        except Exception:
            job = {}
        status = job.get("status")
        return status if isinstance(status, str) and status.strip() else None

    def _latest_run_evidence_for_classification(
        self,
        live_run: dict[str, Any] | None = None,
    ) -> tuple[str | None, str | None, dict[str, Any] | None]:
        latest_run_status: str | None = None
        latest_claim_status: str | None = None
        live_data = live_run if isinstance(live_run, dict) else None
        try:
            from runner.executor_read import handle_inspect_executor_activity

            inspect_result = handle_inspect_executor_activity(
                self.project_root, "latest_run_status", {}
            )
            raw_status = inspect_result.get("status")
            if isinstance(raw_status, str) and raw_status.strip():
                latest_run_status = raw_status.strip()
            inspected_live = inspect_result.get("live")
            if isinstance(inspected_live, dict):
                live_data = inspected_live
            stale = inspect_result.get("stale_orphan_claim")
            if live_data is None and isinstance(stale, dict):
                live_data = stale
        except Exception:
            pass

        if isinstance(live_data, dict):
            claim_status = live_data.get("claim_status")
            if isinstance(claim_status, str) and claim_status.strip():
                latest_claim_status = claim_status.strip()
            claim = live_data.get("claim")
            if latest_claim_status is None and isinstance(claim, dict):
                claim_status = claim.get("status")
                if isinstance(claim_status, str) and claim_status.strip():
                    latest_claim_status = claim_status.strip()
            if latest_run_status is None:
                for key in ("status", "run_status", "executor_run_status"):
                    value = live_data.get(key)
                    if isinstance(value, str) and value.strip():
                        latest_run_status = value.strip()
                        break
        return latest_run_status, latest_claim_status, live_data

    def _read_worktree_clean_for_status(self) -> bool | None:
        try:
            completed = subprocess.run(
                ["git", "-C", self.project_root, "status", "--short"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except Exception:
            return None
        if completed.returncode != 0:
            return None
        return not bool(completed.stdout.strip())

    def _api_remote_git_status(self) -> dict[str, Any]:
        try:
            result = MCPGitRemoteManager(self.project_root).push_status()
        except Exception:
            return {
                "ok": False,
                "message": "无法读取远程 Git 状态。",
                "blockers": ["remote_git_status_unavailable"],
                "warnings": [],
                "commits": [],
            }
        return self._sanitize_remote_git_status(result)

    def _sanitize_remote_git_status(self, result: Any) -> dict[str, Any]:
        if not isinstance(result, dict):
            return {
                "ok": False,
                "message": "无法读取远程 Git 状态。",
                "blockers": ["remote_git_status_unavailable"],
                "warnings": [],
                "commits": [],
            }
        allowed_fields = {
            "ok",
            "action",
            "branch",
            "upstream",
            "remote_name",
            "remote_url_redacted",
            "head_short",
            "ahead",
            "behind",
            "working_tree_clean",
            "can_push",
            "can_preview",
            "blockers",
            "warnings",
            "message",
            "error_code",
        }
        sanitized = {key: self._redact_remote_git_display_value(result.get(key)) for key in allowed_fields if key in result}
        commits = []
        if isinstance(result.get("commits"), list):
            for item in result["commits"][:5]:
                if not isinstance(item, dict):
                    continue
                commits.append(
                    {
                        "short_hash": str(item.get("short_hash") or item.get("hash") or "")[:12],
                        "subject": str(self._redact_remote_git_display_value(item.get("subject") or ""))[:240],
                    }
                )
        sanitized["commits"] = commits
        sanitized.setdefault("blockers", [])
        sanitized.setdefault("warnings", [])
        return sanitized

    def _redact_remote_git_display_value(self, value: Any) -> Any:
        if isinstance(value, str):
            text = re.sub(r"(?i)([a-z][a-z0-9+.-]*://)[^/@\s]+@", r"\1***@", value)
            text = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+", "Bearer ***", text)
            return text
        if isinstance(value, list):
            return [self._redact_remote_git_display_value(item) for item in value]
        if isinstance(value, dict):
            return {str(k): self._redact_remote_git_display_value(v) for k, v in value.items()}
        return value

    @staticmethod
    def _is_web_remote_git_mutation_action(action_name: str) -> bool:
        normalized = re.sub(r"[^a-z0-9]+", "_", str(action_name or "").strip().lower()).strip("_")
        if normalized in REMOTE_GIT_WEB_MUTATION_ACTIONS:
            return True
        parts = {part for part in normalized.split("_") if part}
        remote_git_scope = bool({"git", "remote"} & parts) or normalized.startswith(("push_", "pull_", "fetch_"))
        remote_operation = bool({"push", "pull", "fetch"} & parts)
        mutation_intent = bool({"apply", "preview", "confirm", "run", "start", "execute"} & parts)
        return remote_git_scope and remote_operation and mutation_intent

    def _api_version_result(self) -> dict[str, Any]:
        try:
            data = self.bridge.get_version_result(self.project_root)
        except Exception as e:
            return {"ok": False, "message": str(e)}
        data["ok"] = True
        return data

    def _api_next_plan(self) -> dict[str, Any]:
        try:
            data = self.bridge.get_next_version_plan(self.project_root)
        except Exception as e:
            return {"ok": False, "message": str(e)}
        data["ok"] = True
        return data

    def _api_plan_overview(self) -> dict[str, Any]:
        try:
            data = self.bridge.get_plan_overview(self.project_root)
        except Exception as e:
            return {"ok": False, "message": str(e)}
        data["ok"] = True
        state_readable = True
        state_message = ""
        try:
            data["version_rows"] = self._build_version_rows(data.get("versions", []))
        except Exception as e:
            state_readable = False
            state_message = str(e)
            data["version_rows"] = self._build_version_rows_from_plan(data.get("versions", []))
        data["state_readable"] = state_readable
        data["state_message"] = state_message
        return data

    def _api_version_prompt(self, version: str | None = None) -> dict[str, Any]:
        if not version or not isinstance(version, str) or not version.strip():
            return {"ok": False, "error_code": "VERSION_REQUIRED", "message": "version 参数不能为空。"}
        version = version.strip()
        plan = self._read_json_file(self.plan_file)
        if not plan:
            return {"ok": False, "error_code": "PLAN_NOT_FOUND", "message": "plan.json 不存在。"}
        target_ver = None
        for v in plan.get("versions", []):
            if v.get("version") == version:
                target_ver = v
                break
        if target_ver is None:
            return {"ok": False, "error_code": "VERSION_NOT_FOUND", "message": f"版本 {version} 不存在于 plan 中。", "version": version}
        prompt_file_abs, resolve_error = self._resolve_prompt_file(target_ver.get("prompt_file"), version)
        if resolve_error == "PROMPT_NOT_FOUND":
            return {"ok": False, "error_code": "PROMPT_NOT_FOUND", "message": f"版本 {version} 的 prompt 文件不存在。", "version": version, "prompt_file": None}
        if resolve_error == "PROMPT_FILE_UNSAFE":
            return {"ok": False, "error_code": "PROMPT_FILE_UNSAFE", "message": "prompt 文件路径不安全。", "version": version}
        try:
            text = Path(prompt_file_abs).read_text(encoding="utf-8", errors="replace")
        except Exception:
            return {"ok": False, "error_code": "PROMPT_READ_ERROR", "message": "读取 prompt 文件失败。", "version": version}
        char_count = len(text)
        line_count = text.count("\n") + 1 if text else 0
        truncated = False
        max_chars = 50000
        if char_count > max_chars:
            text = text[:max_chars]
            truncated = True
            char_count = max_chars
        return {
            "ok": True,
            "version": version,
            "version_name": str(target_ver.get("name") or target_ver.get("description") or ""),
            "prompt_file": self._to_project_relative(prompt_file_abs),
            "content": text,
            "char_count": char_count,
            "line_count": line_count,
            "truncated": truncated,
            "report": self._version_prompt_report_payload(version),
        }

    def _version_prompt_report_payload(self, version: str) -> dict[str, Any]:
        try:
            from runner.executor_read import handle_inspect_executor_activity
            report_result = handle_inspect_executor_activity(
                self.project_root,
                "get_report",
                {
                    "version": version,
                    "latest": True,
                    "include_markdown": True,
                    "max_report_chars": 50000,
                },
            )
        except Exception as exc:
            return {
                "available": False,
                "error_code": "REPORT_READ_ERROR",
                "message": f"读取报告失败：{exc}",
            }
        if not report_result.get("ok"):
            return {
                "available": False,
                "error_code": str(report_result.get("error_code") or "REPORT_NOT_FOUND"),
                "message": str(report_result.get("message") or "该版本暂无执行器报告。"),
            }
        report = report_result.get("report") if isinstance(report_result.get("report"), dict) else {}
        markdown_file = str(report.get("markdown_file") or "")
        return {
            "available": True,
            "report_id": str(report.get("report_id") or ""),
            "status": str(report.get("status") or ""),
            "provider": str(report.get("provider") or ""),
            "report_file": self._to_project_relative(markdown_file) if markdown_file else "",
            "content": str(report_result.get("report_markdown") or ""),
            "truncated": bool(report_result.get("truncated", False)),
        }

    def _build_version_rows_from_plan(self, plan_versions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for plan_item in plan_versions:
            version_id = str(plan_item.get("version", ""))
            prompt_file_abs, resolve_error = self._resolve_prompt_file(plan_item.get("prompt_file"), version_id)
            prompt_excerpt = None
            prompt_missing = True
            display_path = None
            if prompt_file_abs is not None:
                prompt_excerpt = self._read_prompt_excerpt(prompt_file_abs)
                prompt_missing = False
                display_path = self._to_project_relative(prompt_file_abs)
            rows.append(
                {
                    "version": version_id,
                    "name": plan_item.get("name"),
                    "enabled": bool(plan_item.get("enabled", True)),
                    "is_current": False,
                    "runtime_status": None,
                    "attempt": 0,
                    "commit_hash": None,
                    "is_checkpoint": False,
                    "reviewed": False,
                    "prompt_file": display_path,
                    "prompt_excerpt": prompt_excerpt,
                    "prompt_missing": prompt_missing,
                }
            )
        return rows

    def _api_log_tail(self) -> dict[str, Any]:
        state = self._read_json_file(self.state_file)
        if not state:
            return {"ok": False, "message": "状态文件读取失败。"}
        raw_log_path = state.get("last_log_file")
        if not isinstance(raw_log_path, str) or not raw_log_path.strip():
            return {
                "ok": True,
                "log_path": None,
                "log_path_rel": None,
                "tail": "",
                "message": "暂无日志。",
            }
        log_path = os.path.abspath(raw_log_path.strip())
        logs_root = os.path.abspath(self.logs_dir)
        if not (log_path == logs_root or log_path.startswith(logs_root + os.sep)):
            return {
                "ok": False,
                "log_path": raw_log_path,
                "message": f"日志路径不在 {self.runner_rel_dir}/logs 目录内。",
            }
        if not os.path.exists(log_path):
            return {
                "ok": True,
                "log_path": log_path,
                "log_path_rel": self._to_project_relative(log_path),
                "tail": "",
                "message": "日志文件不存在。",
            }
        try:
            text = Path(log_path).read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return {
                "ok": False,
                "log_path": log_path,
                "log_path_rel": self._to_project_relative(log_path),
                "message": f"日志读取失败：{e}",
            }
        lines = text.splitlines()
        tail_lines = lines[-120:]
        tail_text = "\n".join(tail_lines)
        if len(tail_text) > 12000:
            tail_text = tail_text[-12000:]
        return {
            "ok": True,
            "log_path": log_path,
            "log_path_rel": self._to_project_relative(log_path),
            "tail": tail_text,
            "line_count": len(tail_lines),
            "char_count": len(tail_text),
            "message": "",
        }

    def _api_plan_patches(self) -> dict[str, Any]:
        try:
            data = self.bridge.list_plan_patches(self.project_root)
        except Exception as e:
            return {"ok": False, "message": str(e), "patches": []}
        data["ok"] = True
        return data

    def _api_auto_apply_patches(self) -> dict[str, Any]:
        if self.operation_running:
            return self._operation_running_payload()
        service = PlanPatchAutoApplyService(self.project_root)
        return service.auto_apply()

    def _job_operation_callable(self, operation: str):
        operations = {
            "run_current_version": lambda: self._api_execute_current_version("run", wrap=False),
            "fix_current_version": lambda: self._api_execute_current_version("fix", wrap=False),
            "rerun_acceptance": lambda: self._api_rerun_acceptance(wrap=False),
            "checkpoint_review": lambda: self._api_checkpoint_review(wrap=False),
            "commit_confirm": lambda: self._api_commit_confirm(wrap=False),
        }
        return operations.get(operation)

    def _api_start_job(self, payload: dict[str, Any]) -> dict[str, Any]:
        operation = str(payload.get("operation") or "").strip()
        fn = self._job_operation_callable(operation)
        if fn is None:
            return {
                "ok": False,
                "error_code": "INVALID_JOB_OPERATION",
                "message": "当前操作不可用。",
            }

        with self.operation_lock:
            if self.operation_running or self.job.get("status") == "running":
                return {
                    "ok": False,
                    "error_code": "JOB_ALREADY_RUNNING",
                    "message": "当前已有操作正在进行，请稍后再试。",
                }
            if operation not in ("commit_confirm",):
                self.pending_commit_preview = None
            job_id = uuid.uuid4().hex
            started_at = self._now_iso()
            self.operation_running = True
            self.operation_name = operation
            self.operation_started_at = started_at
            self.job = {
                "job_id": job_id,
                "operation": operation,
                "status": "running",
                "started_at": started_at,
                "ended_at": None,
                "message": "已开始处理。",
                "result": {},
                "error_code": "",
            }

        thread = threading.Thread(target=self._run_job_worker, args=(job_id, operation, fn), daemon=True)
        thread.start()
        return {
            "ok": True,
            "job_id": job_id,
            "operation": operation,
            "status": "running",
            "message": "已开始处理。",
        }

    def _run_job_worker(self, job_id: str, operation: str, fn) -> None:
        started_at = self.operation_started_at or self._now_iso()
        payload = self._operation_payload(operation, started_at, fn)
        status = "passed" if payload.get("ok") else "failed"
        with self.operation_lock:
            self.job = {
                "job_id": job_id,
                "operation": operation,
                "status": status,
                "started_at": payload.get("started_at"),
                "ended_at": payload.get("ended_at"),
                "message": payload.get("message", ""),
                "result": payload.get("result", {}),
                "error_code": payload.get("error_code") or "",
            }
            self.operation_running = False
            self.operation_name = ""
            self.operation_started_at = None

    def _api_job_status(self) -> dict[str, Any]:
        with self.operation_lock:
            job = dict(self.job) if self.job else {"status": "idle"}
        if not job:
            job = {"status": "idle"}
        return {"ok": True, "job": job}

    def _api_switch_executor(self, body: dict[str, Any]) -> dict[str, Any]:
        provider = (body or {}).get("provider", "").strip().lower()
        if not is_supported_execution_provider(provider):
            return {"ok": False, "message": f"不支持的执行器：{provider}"}
        try:
            from runner.runner_settings import RunnerSettings
            saved = self.runner_settings_store.save_settings_for_project(
                self.project_root,
                RunnerSettings(execution_provider=provider),
            )
            return {
                "ok": True,
                "provider": provider,
                "provider_display": get_executor_provider_display(provider),
                "settings_file": saved.get("settings_file"),
            }
        except Exception as e:
            return {"ok": False, "message": f"执行器切换失败：{e}"}

    def _load_execution_provider(self, workspace: ProjectWorkspace) -> str:
        settings = self.runner_settings_store.load_for_project(workspace.workspace_root, workspace.plan_file)
        if is_supported_execution_provider(settings.execution_provider):
            return settings.execution_provider
        return DEFAULT_EXECUTION_PROVIDER

    def _api_execution_display(self) -> dict[str, str]:
        try:
            workspace = ProjectWorkspace.from_project_path(self.project_root)
            provider = self._load_execution_provider(workspace)
        except Exception:
            provider = DEFAULT_EXECUTION_PROVIDER
        provider_display = get_executor_provider_display(provider)

        model_display = "默认模型"
        try:
            plan_data = self._read_json_file(self.plan_file) or {}
            model_display = extract_model_display_from_plan_data(plan_data)
        except Exception:
            model_display = "默认模型"

        return build_execution_display(
            provider=provider,
            provider_display=provider_display,
            model_display=model_display,
        )

    def _resolve_current_execution_provider(self, fallback_provider: str | None = None) -> str:
        fallback = normalize_execution_provider(
            fallback_provider or DEFAULT_EXECUTION_PROVIDER,
            default=DEFAULT_EXECUTION_PROVIDER,
        )
        try:
            workspace, plan, state, _, _ = self._load_runtime_context()
            current_version = (
                plan.versions[state.current_version_index]
                if state.current_version_index is not None and 0 <= state.current_version_index < len(plan.versions)
                else None
            )
            mainline = self._load_execution_provider(workspace)
            return resolve_version_execution_provider(
                plan=plan,
                version=current_version,
                fallback_provider=mainline,
            )
        except Exception:
            return fallback

    def _build_run_once_message(self, *, run_status: str, scope_status: str, execution_mode: str) -> str:
        mode = str(execution_mode or "run").strip().lower()
        run = str(run_status or "").strip().upper()
        scope = str(scope_status or "").strip().upper()
        is_fix = mode == "fix"
        if is_fix and run == "PASSED" and scope == "BLOCKED_BY_SCOPE_VIOLATION":
            return "当前版本修复完成，验收通过，改动范围校验失败。"
        if is_fix and run == "PASSED":
            return "当前版本修复完成，验收通过。"
        if is_fix:
            return "当前版本修复完成，验收未通过。"
        if run == "PASSED" and scope == "BLOCKED_BY_SCOPE_VIOLATION":
            return "当前版本运行完成，验收通过，改动范围校验失败。"
        if run == "PASSED":
            return "当前版本运行完成，验收通过。"
        return "当前版本运行完成，验收未通过。"

    def _api_execute_current_version(self, mode: str, wrap: bool = True) -> dict[str, Any]:
        def _do() -> dict[str, Any]:
            workspace, plan, state, _, _ = self._load_runtime_context()

            if not state.current_version:
                return {
                    "ok": False,
                    "error_code": "NO_CURRENT_VERSION",
                    "message": "当前没有可执行版本。",
                }

            if state.status == "VERSION_PASSED":
                return {
                    "ok": False,
                    "error_code": "VERSION_ALREADY_PASSED",
                    "message": "当前版本已通过。可按“进入下一版本”继续，或按“重新测试”复检。",
                }

            if state.status == "COMPLETED":
                return {
                    "ok": False,
                    "error_code": "ALL_COMPLETED",
                    "message": "所有版本已完成。",
                }

            if mode == "run" and state.status == "BLOCKED_BY_ACCEPTANCE_FAILURE":
                return {
                    "ok": False,
                    "error_code": "ACCEPTANCE_BLOCKED",
                    "message": "当前测试失败。请按“重新测试”重跑，或回到终端进入修复流程。",
                }

            if state.status == "BLOCKED_BY_MAX_FIX_ATTEMPTS":
                return {
                    "ok": False,
                    "error_code": "MAX_FIX_ATTEMPTS_REACHED",
                    "message": "当前版本已达到最大修复次数，流程已暂停。",
                }

            settings_provider = self._load_execution_provider(workspace)
            current_version = plan.versions[state.current_version_index] if state.current_version_index is not None and 0 <= state.current_version_index < len(plan.versions) else None
            provider = resolve_version_execution_provider(
                plan=plan, version=current_version, fallback_provider=settings_provider,
            )
            is_fix = mode == "fix" or state.status == "FIX_PROMPT_READY"

            if mode == "fix" and state.status != "FIX_PROMPT_READY":
                return {
                    "ok": False,
                    "error_code": "FIX_PROMPT_NOT_READY",
                    "message": "当前版本尚未进入修复执行阶段。请先在终端按 F 准备修复提示词。",
                }

            service = ExecutorRunOnceService(self.project_root)
            execution_mode = "fix" if is_fix else "run"
            run_ret = service.run_once(
                provider=provider,
                execution_mode=execution_mode,
                include_diff_summary=True,
                include_report_markdown=False,
                max_report_chars=30000,
                reason="web_console",
            )
            if not run_ret.get("ok"):
                return {
                    "ok": False,
                    "error_code": str(run_ret.get("error_code") or "EXECUTOR_FAILED"),
                    "message": str(run_ret.get("message") or "执行器运行失败。"),
                    "provider": provider,
                    "execution_mode": execution_mode,
                    "classification": run_ret.get("classification"),
                    "blocks": run_ret.get("blocks", []),
                    "warnings": run_ret.get("warnings", []),
                    "log_path": run_ret.get("log_path", ""),
                }

            run_status = str(run_ret.get("run_status") or "")
            scope_status = str(run_ret.get("scope_status") or "NOT_CHECKED")
            message = self._build_run_once_message(
                run_status=run_status,
                scope_status=scope_status,
                execution_mode=execution_mode,
            )
            lineage = {}
            report_summary = run_ret.get("report_summary", {})
            if isinstance(report_summary, dict) and isinstance(report_summary.get("execution_lineage"), dict):
                lineage = report_summary.get("execution_lineage", {})

            return {
                "ok": True,
                "message": message,
                "provider": provider,
                "execution_mode": execution_mode,
                "run_status": run_status,
                "runner_status": run_ret.get("runner_status"),
                "audit_file": run_ret.get("audit_file", ""),
                "scope_status": scope_status,
                "failed_command_indexes": run_ret.get("failed_command_indexes", []),
                "command_results": run_ret.get("command_results", []),
                "log_path": run_ret.get("log_path", ""),
                "summary_path": run_ret.get("summary_path", ""),
                "summary": "",
                "attempted_resume": bool(lineage.get("attempted_resume", False)),
                "used_resume": bool(lineage.get("used_resume", False)),
                "fallback_to_new_session": bool(lineage.get("fallback_to_new_session", False)),
                "resume_failed_reason": lineage.get("resume_failed_reason"),
                "command_shape": lineage.get("command_shape"),
                "version": run_ret.get("version") or state.current_version,
            }

        operation_name = "fix_current_version" if mode == "fix" else "run_current_version"
        if not wrap:
            return _do()
        return self._run_operation(operation_name, _do)

    def _api_run_current_version(self) -> dict[str, Any]:
        return self._api_execute_current_version("run")

    def _api_run_current_version_preview(self) -> dict[str, Any]:
        def _do() -> dict[str, Any]:
            preview_id = f"run-{uuid.uuid4().hex}"
            self.pending_run_preview = {
                "preview_id": preview_id,
                "created_at": self._now_iso(),
                "created_ts": datetime.now(timezone.utc).timestamp(),
            }
            return {
                "ok": True,
                "message": "运行预览已生成。",
                "preview_id": preview_id,
            }

        payload = self._run_operation("run_current_version_preview", _do)
        if isinstance(payload, dict):
            result = payload.get("result")
            if isinstance(result, dict):
                preview_id = result.get("preview_id")
                if preview_id:
                    payload["preview_id"] = preview_id
        return payload

    def _api_run_current_version_confirm_with_project(self) -> dict[str, Any]:
        return self._api_run_current_version()

    def _api_fix_current_version(self) -> dict[str, Any]:
        return self._api_execute_current_version("fix")

    def _api_reload_plan(self) -> dict[str, Any]:
        def _do() -> dict[str, Any]:
            service = PlanReloadService(self.project_root)
            result = service.reload_plan()
            if result.get("ok"):
                self.start_plan_mtime = self._safe_mtime(self.plan_file)
                self.start_marker_mtime = self._safe_mtime(self.marker_file)
            return result

        return self._run_operation("reload_plan", _do)

    def _api_continue_next_version(self) -> dict[str, Any]:
        def _do() -> dict[str, Any]:
            service = ContinueNextVersionService(self.project_root)
            result = service.continue_next_version()
            if result.get("ok"):
                self.start_plan_mtime = self._safe_mtime(self.plan_file)
                self.start_marker_mtime = self._safe_mtime(self.marker_file)
            return result

        return self._run_operation("continue_next_version", _do)

    def _api_rerun_acceptance(self, wrap: bool = True) -> dict[str, Any]:
        def _do() -> dict[str, Any]:
            service = AcceptanceRerunService(self.project_root)
            result = service.rerun_acceptance()
            return result

        if not wrap:
            return _do()
        return self._run_operation("rerun_acceptance", _do)

    def _api_checkpoint_review(self, wrap: bool = True) -> dict[str, Any]:
        def _do() -> dict[str, Any]:
            service = CheckpointReviewService(self.project_root)
            result = service.run_review()
            return result

        if not wrap:
            return _do()
        return self._run_operation("checkpoint_review", _do)

    def _api_commit_preview(self) -> dict[str, Any]:
        def _do() -> dict[str, Any]:
            _, plan, state, _, machine = self._load_runtime_context()

            if state.status != "VERSION_PASSED":
                self.pending_commit_preview = None
                return {
                    "ok": False,
                    "status": "error",
                    "error_code": "VERSION_NOT_PASSED",
                    "message": "当前版本未通过，不能提交。",
                }

            manager = MCPGitCommitManager(self.project_root)

            readiness = manager.readiness()
            if not readiness.get("ok"):
                self.pending_commit_preview = None
                return {
                    "ok": False,
                    "status": "error",
                    "error_code": str(readiness.get("error_code", "READINESS_FAILED")).upper(),
                    "message": readiness.get("message", "提交就绪检查失败。"),
                }

            commit_blockers: list[str] = readiness.get("commit_blockers", [])
            blocked_files: list[str] = readiness.get("blocked_files", [])
            excluded_files: list[str] = readiness.get("excluded_files", [])
            files_to_commit: list[str] = readiness.get("files_to_commit", [])

            if commit_blockers:
                self.pending_commit_preview = None
                result: dict[str, Any] = {
                    "ok": False,
                    "status": "blocked",
                    "error_code": "COMMIT_PREVIEW_BLOCKED",
                    "message": "提交被阻断。",
                    "commit_blockers": commit_blockers,
                    "commit_warnings": readiness.get("commit_warnings", []),
                    "blocked_files": sorted(blocked_files),
                    "excluded_files": sorted(excluded_files),
                    "files_to_commit": sorted(files_to_commit),
                }
                if blocked_files:
                    result["reason_if_blocked"] = "blocked_files_present"
                return result

            current_plan_version = (
                plan.versions[state.current_version_index]
                if state.current_version_index is not None
                and 0 <= state.current_version_index < len(plan.versions)
                else None
            )
            version_label = current_plan_version.version if current_plan_version else (state.current_version or "未知")
            version_name = current_plan_version.name if current_plan_version else ""
            commit_title = f"{version_label} {version_name}".strip()
            audit_rel = self._to_rel(machine.get_current_audit_file())
            commit_body = f"Runner accepted version: {version_label}\nAcceptance: passed\nAudit: {audit_rel}"
            commit_message = f"{commit_title}\n\n{commit_body}"

            preview_result = manager.preview(message=commit_message)
            if not preview_result.get("ok"):
                self.pending_commit_preview = None
                return {
                    "ok": False,
                    "status": "error",
                    "error_code": str(preview_result.get("error_code", "PREVIEW_FAILED")).upper(),
                    "message": preview_result.get("message", "提交预览生成失败。"),
                }

            preview_id = preview_result.get("preview_id")
            diff_hash = preview_result.get("diff_hash")
            final_files_to_commit = preview_result.get("files_to_commit", files_to_commit)
            final_excluded_files = preview_result.get("excluded_files", excluded_files)

            self.pending_commit_preview = {
                "preview_id": preview_id,
                "message": commit_title,
                "commit_files": sorted(final_files_to_commit),
                "excluded_files": sorted(final_excluded_files),
                "diff_hash": diff_hash,
                "version": state.current_version,
                "project_root": os.path.abspath(self.project_root),
            }

            return {
                "ok": True,
                "message": "提交预览已生成。",
                "status": "ready",
                "scope_status": "NOT_CHECKED",
                "commit_message": {
                    "title": commit_title,
                    "body": commit_body,
                },
                "commit_title": commit_title,
                "commit_body": commit_body,
                "version": state.current_version,
                "commit_files": sorted(final_files_to_commit),
                "excluded_files": sorted(final_excluded_files),
                "preview_id": preview_id,
                "diff_hash": diff_hash,
                "reason_if_blocked": "",
            }

        return self._run_operation("commit_preview", _do)

    def _api_commit_preview_with_project(self) -> dict[str, Any]:
        return self._api_commit_preview()

    def _api_commit_confirm(self, wrap: bool = True) -> dict[str, Any]:
        def _do() -> dict[str, Any]:
            _, plan, state, _, _ = self._load_runtime_context()

            if state.status != "VERSION_PASSED":
                self.pending_commit_preview = None
                return {
                    "ok": False,
                    "status": "failed",
                    "error_code": "VERSION_NOT_PASSED",
                    "message": "当前版本未通过，不能提交。",
                }

            preview = self.pending_commit_preview
            if not preview or not preview.get("preview_id"):
                self.pending_commit_preview = None
                return {
                    "ok": False,
                    "status": "failed",
                    "error_code": "COMMIT_PREVIEW_REQUIRED",
                    "message": "请先查看改动说明",
                }

            preview_id = str(preview.get("preview_id", "")).strip()
            manager = MCPGitCommitManager(self.project_root)
            commit_result = manager.commit(preview_id=preview_id)

            if not commit_result.get("ok"):
                self.pending_commit_preview = None
                error_code = str(commit_result.get("error_code", "COMMIT_FAILED"))
                return {
                    "ok": False,
                    "status": "failed",
                    "error_code": error_code,
                    "message": commit_result.get("message", "代码提交失败"),
                    "details": commit_result,
                }

            commit_hash = commit_result.get("commit_hash", "")
            commit_message = commit_result.get("message", "")
            committed_files = commit_result.get("committed_files", [])
            verify_clean = bool(commit_result.get("verify_clean", False))
            verify_summary = commit_result.get("verify_summary") if isinstance(commit_result.get("verify_summary"), dict) else {}
            remaining_uncommitted_files = commit_result.get("remaining_uncommitted_files", [])
            state_update = commit_result.get("commit_state_update") or {
                "ok": True,
                "skipped": True,
                "reason": "commit_state_update_unavailable",
            }

            self.pending_commit_preview = None

            return {
                "ok": True,
                "status": "committed",
                "message": str(verify_summary.get("one_line") or "代码提交完成"),
                "preview_id": commit_result.get("preview_id", preview_id),
                "commit_hash": commit_hash,
                "commit_hash_short": commit_result.get("commit_hash_short", str(commit_hash)[:8]),
                "commit_message": commit_message,
                "commit_files": committed_files,
                "committed_files": committed_files,
                "verify_clean": verify_clean,
                "clean_status": "clean" if verify_clean else "dirty",
                "verify_summary": verify_summary,
                "remaining_uncommitted_files": remaining_uncommitted_files,
                "commit_state_update": state_update,
            }

        if not wrap:
            return _do()
        return self._run_operation("commit_confirm", _do)

    def _api_commit_confirm_with_project(self) -> dict[str, Any]:
        return self._api_commit_confirm()

    def _is_plan_reload_needed(self) -> bool:
        current_plan_mtime = self._safe_mtime(self.plan_file)
        current_marker_mtime = self._safe_mtime(self.marker_file)
        if current_plan_mtime and self.start_plan_mtime and current_plan_mtime > self.start_plan_mtime:
            return True
        if current_marker_mtime and self.start_marker_mtime and current_marker_mtime > self.start_marker_mtime:
            return True
        if current_marker_mtime and not self.start_marker_mtime:
            return True
        return False

    def _safe_mtime(self, path: str) -> float | None:
        try:
            return os.path.getmtime(path)
        except Exception:
            return None

    def _settings_resolve_signature(self, provider: str) -> tuple[Any, ...]:
        candidate_paths = [
            self.plan_file,
            os.path.join(self.runner_dir, "runner-settings.json"),
            self.runner_settings_store.user_settings_path(),
        ]
        return tuple(
            [self.project_root, provider.strip().lower()]
            + [(path, self._safe_mtime(path)) for path in candidate_paths]
        )

    def _resolve_prompt_file(self, prompt_file: Any, version: str) -> tuple[str | None, str | None]:
        prompts_dir = os.path.join(self.runner_dir, "prompts")
        prompt_file_abs = None
        if prompt_file and isinstance(prompt_file, str) and prompt_file.strip():
            candidate = prompt_file if os.path.isabs(prompt_file) else os.path.join(self.project_root, prompt_file)
            if os.path.isfile(candidate):
                prompt_file_abs = candidate
        if not prompt_file_abs:
            fallback = os.path.join(prompts_dir, f"{version}.md")
            if os.path.isfile(fallback):
                prompt_file_abs = fallback
        if not prompt_file_abs:
            return None, "PROMPT_NOT_FOUND"
        real_prompts = os.path.realpath(prompts_dir)
        real_file = os.path.realpath(prompt_file_abs)
        if not real_file.startswith(real_prompts + os.sep):
            return None, "PROMPT_FILE_UNSAFE"
        return prompt_file_abs, None

    def _read_prompt_excerpt(self, prompt_path: str, max_lines: int = 10, max_chars: int = 300) -> str | None:
        try:
            text = Path(prompt_path).read_text(encoding="utf-8", errors="replace")
        except Exception:
            return None
        lines = text.splitlines()[:max_lines]
        excerpt = "\n".join(lines)
        if len(excerpt) > max_chars:
            excerpt = excerpt[:max_chars] + "…"
        return excerpt

    def _read_json_file(self, path: str) -> dict[str, Any] | None:
        try:
            return json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception:
            return None

    def _build_plan_version_list_for_v2(self) -> list[dict[str, Any]]:
        plan = self._read_json_file(self.plan_file) or {}
        state = self._read_json_file(self.state_file) or {}
        plan_versions = plan.get("versions", [])
        state_versions_map: dict[str, dict[str, Any]] = {}
        for item in state.get("versions", []):
            vid = item.get("version")
            if isinstance(vid, str):
                state_versions_map[vid] = item
        current_version = state.get("current_version")
        rows: list[dict[str, Any]] = []
        for pv in plan_versions:
            vid = str(pv.get("version", ""))
            sv = state_versions_map.get(vid, {})
            rows.append({
                "version": vid,
                "name": pv.get("name"),
                "description": pv.get("description"),
                "enabled": bool(pv.get("enabled", True)),
                "is_current": vid == current_version,
                "runtime_status": sv.get("status"),
            })
        return rows

    def _build_version_rows(self, plan_versions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        state = self._read_json_file(self.state_file) or {}
        review_state = self._read_json_file(os.path.join(self.runner_dir, "review-state.json")) or {}
        review_policy = self._read_json_file(self.plan_file) or {}
        checkpoint_versions = set((review_policy.get("review_policy") or {}).get("after_versions") or [])
        state_map: dict[str, dict[str, Any]] = {}
        for item in state.get("versions", []):
            version_id = item.get("version")
            if isinstance(version_id, str):
                state_map[version_id] = item

        current_version = state.get("current_version")
        reviewed_version = review_state.get("last_reviewed_version")
        has_review_file = bool(review_state.get("last_review_file"))
        rows: list[dict[str, Any]] = []
        for plan_item in plan_versions:
            version_id = str(plan_item.get("version", ""))
            runtime = state_map.get(version_id, {})
            is_checkpoint = version_id in checkpoint_versions
            reviewed = bool(is_checkpoint and reviewed_version == version_id and has_review_file)
            prompt_file_abs, resolve_error = self._resolve_prompt_file(plan_item.get("prompt_file"), version_id)
            prompt_excerpt = None
            prompt_missing = True
            display_path = None
            if prompt_file_abs is not None:
                prompt_excerpt = self._read_prompt_excerpt(prompt_file_abs)
                prompt_missing = False
                display_path = self._to_project_relative(prompt_file_abs)
            rows.append(
                {
                    "version": version_id,
                    "name": plan_item.get("name"),
                    "enabled": bool(plan_item.get("enabled", True)),
                    "is_current": version_id == current_version,
                    "runtime_status": runtime.get("status"),
                    "attempt": runtime.get("attempt"),
                    "commit_hash": runtime.get("commit_hash"),
                    "is_checkpoint": is_checkpoint,
                    "reviewed": reviewed,
                    "prompt_file": display_path,
                    "prompt_excerpt": prompt_excerpt,
                    "prompt_missing": prompt_missing,
                }
            )
        return rows

    def _to_project_relative(self, path: str) -> str:
        abs_path = os.path.abspath(path)
        root = os.path.abspath(self.project_root)
        if abs_path == root:
            return "."
        if abs_path.startswith(root + os.sep):
            return abs_path[len(root) + 1 :]
        return abs_path

    def _api_project_registry(self) -> dict[str, Any]:
        registry = self.project_registry.list_projects()
        for p in registry.get("projects", []):
            root = p.get("project_root", "")
            p["available"] = bool(root) and os.path.isdir(root) and self.project_registry.is_runner_managed_project(root)
            p["is_temp"] = bool(root) and self.project_registry.is_temp_path(root)
        return registry

    def _api_switch_project(self, body: dict[str, Any] | None) -> dict[str, Any]:
        payload = body or {}
        with self.operation_lock:
            if self.operation_running or self.job.get("status") == "running":
                return {
                    "ok": False,
                    "error_code": "OPERATION_RUNNING",
                    "message": "当前有操作正在运行，不能切换项目。",
                    "active_project_root": self.project_root,
                }

        selected = self.project_registry.select_project(
            project_id=payload.get("project_id") if isinstance(payload.get("project_id"), str) else None,
            project_root=payload.get("project_root") if isinstance(payload.get("project_root"), str) else None,
        )
        if not selected.get("ok"):
            selected["active_project_root"] = self.project_root
            return selected

        project = selected.get("project") if isinstance(selected.get("project"), dict) else {}
        new_root = project.get("project_root")
        if not isinstance(new_root, str) or not new_root.strip():
            return {
                "ok": False,
                "error_code": "PROJECT_SWITCH_FAILED",
                "message": "登记项目缺少 project_root。",
                "active_project_root": self.project_root,
            }

        previous_root = self.project_root
        try:
            self._set_project_root(new_root)
            self.pending_commit_preview = None
            self.pending_run_preview = None
            self.job = {"status": "idle"}
            return {
                "ok": True,
                "message": "项目已切换。",
                "previous_project_root": previous_root,
                "project": project,
                "registry_path": self.project_registry.registry_path(),
                "status": self._api_v2_status(),
            }
        except Exception as exc:
            self._set_project_root(previous_root)
            return {
                "ok": False,
                "error_code": "PROJECT_SWITCH_FAILED",
                "message": str(exc),
                "active_project_root": self.project_root,
            }

    def _api_project_identity_preview(self, body: dict[str, Any] | None) -> dict[str, Any]:
        payload = body or {}
        with self.operation_lock:
            if self.operation_running or self.job.get("status") == "running":
                return {
                    "ok": False,
                    "action": "project_identity_preview",
                    "blockers": ["当前有操作正在运行，不能编辑项目身份。"],
                }
        return self.project_registry.preview_project_identity_migration(
            project_id=payload.get("project_id") if isinstance(payload.get("project_id"), str) else None,
            current_project_root=self.project_root,
            new_project_name=str(payload.get("new_project_name") or ""),
            new_display_name=(
                payload.get("new_display_name")
                if isinstance(payload.get("new_display_name"), str)
                else None
            ),
            new_project_root=str(payload.get("new_project_root") or ""),
        )

    def _api_project_identity_apply(self, body: dict[str, Any] | None) -> dict[str, Any]:
        payload = body or {}
        preview_id = payload.get("preview_id")
        if not isinstance(preview_id, str) or not preview_id.strip():
            return {
                "ok": False,
                "action": "project_identity_apply",
                "error_code": "PREVIEW_ID_REQUIRED",
                "message": "apply 需要有效的 preview_id。",
            }
        with self.operation_lock:
            if self.operation_running or self.job.get("status") == "running":
                return {
                    "ok": False,
                    "action": "project_identity_apply",
                    "error_code": "OPERATION_RUNNING",
                    "message": "当前有操作正在运行，不能编辑项目身份。",
                }
        result = self.project_registry.apply_project_identity_migration(preview_id)
        if result.get("ok"):
            project = result.get("project")
            new_root = project.get("project_root") if isinstance(project, dict) else None
            if isinstance(new_root, str) and new_root.strip():
                self._set_project_root(new_root)
            result["project_registry"] = self._api_project_registry()
        return result

    # ---- Web v2 methods ----

    def _json_safe(self, obj: Any) -> Any:
        if isinstance(obj, dict):
            return {k: self._json_safe(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self._json_safe(v) for v in obj]
        if hasattr(obj, "__dataclass_fields__"):
            return {k: self._json_safe(getattr(obj, k)) for k in obj.__dataclass_fields__}
        if isinstance(obj, (str, int, float, bool)) or obj is None:
            return obj
        return str(obj)

    def _api_v2_live_run(self) -> dict[str, Any]:
        from runner.executor_read import handle_inspect_executor_activity
        session_status: dict[str, Any] | None = None
        try:
            session_status = self.executor_session_store.get_status()
        except Exception:
            session_status = None
        try:
            inspect_result = handle_inspect_executor_activity(
                self.project_root, "latest_run_status", {}
            )
            live_data = inspect_result.get("live")
            if isinstance(live_data, dict) and inspect_result.get("ok") and live_data.get("available"):
                self._enrich_live_run_progress_status(live_data)
                return self._with_executor_identity_display(
                    live_data,
                    session_status=session_status,
                )
            stale = inspect_result.get("stale_orphan_claim")
            stale_msg = inspect_result.get("message", "")
            if isinstance(stale, dict):
                return {
                    "available": False,
                    "stale_orphan_claim": stale,
                    "stale_orphan_message": stale_msg,
                }
            if not isinstance(live_data, dict):
                return {"available": False, "warning": "live field is not a dict"}
        except Exception:
            pass
        return {"available": False}

    def _enrich_live_run_progress_status(self, live_data: dict[str, Any]) -> None:
        try:
            from runner.executor_status import analyze_meaningful_progress
            events = live_data.get("events")
            progress = analyze_meaningful_progress(events if isinstance(events, list) else [])
            live_data["last_meaningful_progress"] = progress
            diagnostics = live_data.get("diagnostics")
            if not isinstance(diagnostics, list):
                diagnostics = []
            heartbeat = live_data.get("heartbeat")
            heartbeat_stale = bool(heartbeat.get("stale")) if isinstance(heartbeat, dict) else False
            claim_status = str(live_data.get("claim_status") or "").upper()
            if claim_status == "RUNNING" and not heartbeat_stale and progress.get("available") and progress.get("stale"):
                if "HEARTBEAT_ONLY_WITH_STALE_PROGRESS" not in diagnostics:
                    diagnostics.append("HEARTBEAT_ONLY_WITH_STALE_PROGRESS")
                live_data["provider_status"] = "stalled_without_provider_error"
                live_data["terminal_reason"] = "executor_stalled_without_provider_error"
                live_data["progress_stalled"] = True
            live_data["diagnostics"] = diagnostics
        except Exception:
            pass

    def _executor_model_for_display(
        self,
        *,
        provider: str,
        live_run: dict[str, Any],
        session_record: dict[str, Any],
    ) -> str:
        claim = live_run.get("claim") if isinstance(live_run.get("claim"), dict) else {}
        candidates = [
            live_run.get("executor_model"),
            live_run.get("model"),
            live_run.get("model_name"),
            claim.get("model"),
            claim.get("model_name"),
            session_record.get("model"),
            session_record.get("model_name"),
        ]
        for candidate in candidates:
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()

        cache_key = self._settings_resolve_signature(provider)
        resolved: Any = self._settings_resolve_cache.get(cache_key)
        if resolved is None:
            resolved = self.runner_settings_store.resolve_for_project(self.project_root, self.plan_file)
            self._settings_resolve_cache.clear()
            self._settings_resolve_cache[cache_key] = resolved
        profile = resolved.settings.executor_profile
        if profile and profile.model:
            profile_provider = (profile.provider or "").strip().lower()
            if not profile_provider or profile_provider == provider.strip().lower():
                return profile.model.strip()
        return ""

    def _with_executor_identity_display(
        self,
        live_run: dict[str, Any] | None,
        *,
        session_status: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        live = dict(live_run) if isinstance(live_run, dict) else {"available": False}
        if not live.get("available"):
            return live
        status = session_status if isinstance(session_status, dict) else {}
        record = status.get("record") if isinstance(status.get("record"), dict) else {}
        claim = live.get("claim") if isinstance(live.get("claim"), dict) else {}
        provider = (
            claim.get("provider")
            or live.get("provider")
            or record.get("provider")
            or ""
        )
        provider_text = str(provider or "")
        model_text = self._executor_model_for_display(
            provider=provider_text,
            live_run=live,
            session_record=record,
        )
        live["executor_model"] = model_text
        live["executor_display"] = f"{provider_text} + {model_text}" if provider_text and model_text else provider_text
        identity = select_executor_identity_for_display(
            run_identity=live,
            session_record=record,
            provider=provider_text,
            fallback_value=live.get("session_id_full"),
        )
        live["session_identity_present"] = bool(identity.get("identity_present") is True)
        live["session_identity_value"] = str(identity.get("identity_value") or "")
        live["session_identity_kind"] = str(identity.get("identity_kind") or "")
        live["session_identity_label"] = str(identity.get("identity_label") or "会话标识")
        live["session_identity_source"] = str(identity.get("identity_source") or "")
        if not isinstance(live.get("session_id_full"), str) or not str(live.get("session_id_full") or "").strip():
            live["session_id_full"] = live["session_identity_value"]
        return live

    def _api_v2_status(self) -> dict[str, Any]:
        orchestrator = WorkflowOrchestrator(self.project_root)
        core_output = orchestrator.handle("project_status", {"include_reports": True})
        result = self._json_safe(core_output)
        try:
            thin_loop_preview = orchestrator.handle(
                "thin_governed_loop_preview",
                {"phase": "preview", "input_mode": "example"},
            )
        except Exception as exc:
            thin_loop_preview = {
                "ok": False,
                "workflow": "thin_governed_loop_preview",
                "status": "failed",
                "risk_level": "info",
                "requires_confirmation": False,
                "blockers": [str(exc)],
                "warnings": [
                    "thin_governed_loop_preview is read-only evidence; it does not authorize executor dispatch, ReviewDecision, GateEvent, Delivery State transition, commit, or push."
                ],
                "result": {
                    "ok": False,
                    "read_only": True,
                    "side_effects": False,
                    "input_mode": "example",
                    "thin_loop": {
                        "thin_loop_status": "thin_governed_loop_failed_closed",
                        "blockers": [{"code": "thin_loop_preview_failed", "message": str(exc)}],
                    },
                    "forbidden_authority_outputs": {
                        "delivery_state_accepted": False,
                        "review_decision_created": False,
                        "gate_event_emitted": False,
                        "executor_dispatch_authorized": False,
                    },
                },
            }
        result["thin_governed_loop_preview"] = self._json_safe(thin_loop_preview)
        local_service = self._connector_runtime_local_service_evidence()
        runtime_status = get_runtime_version_status(self.project_root, local_service=local_service)
        connector_runtime_health = get_connector_runtime_health_status(
            runtime_status=runtime_status,
            local_service=local_service,
        )
        result["connector_runtime_health"] = self._json_safe(connector_runtime_health)
        web_commander_service = self._web_commander_runtime_summary(
            runtime_status=runtime_status,
            connector_health=connector_runtime_health,
            local_service=local_service,
        )
        result["runtime_version_summary"] = self._json_safe(web_commander_service["runtime"])
        result["web_commander_service"] = self._json_safe(web_commander_service)
        result["service_readiness_summary"] = self._json_safe(web_commander_service["readiness"])
        result["product_console_completion"] = self._json_safe(web_commander_service["product_console_completion"])
        result["apps_connector_closeout"] = self._json_safe(web_commander_service["apps_connector_closeout"])
        result["apps_connector_tool_refresh"] = self._json_safe(web_commander_service["apps_connector_tool_refresh"])
        result["stable_replacement_cadence"] = self._json_safe(web_commander_service["stable_replacement_cadence"])
        fs_pi = (result.get("fact_snapshot") or {}).get("project_identity")
        if isinstance(fs_pi, dict) and fs_pi.get("project_name"):
            result["project_identity"] = dict(fs_pi)
        else:
            result["project_identity"] = build_project_identity(self.project_root)
        registry_data = self._api_project_registry()
        registry_data["projects"] = [
            p for p in registry_data.get("projects", [])
            if p.get("project_mode") == "managed"
        ]
        registry_data["project_count"] = len(registry_data["projects"])
        result["project_registry"] = registry_data
        try:
            todo_result = MCPTodoListManager(self.project_root).read()
        except Exception as exc:
            todo_result = {
                "ok": False,
                "error_code": "TODO_READ_FAILED",
                "message": str(exc),
                "items": [],
                "item_count": 0,
                "total_item_count": 0,
                "planned_count": 0,
                "done_count": 0,
                "path": f"{self.runner_rel_dir}/todolist.json",
            }
        result["todolist"] = self._json_safe(todo_result)
        try:
            decision_result = MCPDecisionRecordsManager(self.project_root).read()
        except Exception as exc:
            decision_result = {
                "ok": False,
                "error_code": "DECISION_READ_FAILED",
                "message": str(exc),
                "decisions": [],
                "decision_count": 0,
                "path": f"{self.runner_rel_dir}/decisions.json",
            }
        result["decisions"] = self._json_safe(decision_result)
        try:
            memory_result = MCPProjectMemoryManager(self.project_root).read()
        except Exception as exc:
            memory_result = {
                "ok": False,
                "error_code": "MEMORY_READ_FAILED",
                "message": str(exc),
                "content": "",
                "content_chars": 0,
                "path": f"{self.runner_rel_dir}/memory.md",
            }
        result["memory"] = self._json_safe(memory_result)
        live_run = self._api_v2_live_run()
        result["live_run"] = live_run
        if not (isinstance(live_run, dict) and live_run.get("available") is True):
            self._enrich_latest_report_identity(result)
        self._apply_executor_session_head_mismatch_classification(result, live_run=live_run)
        result["executor_session_display"] = build_executor_session_display(
            executor_session_status=result.get("executor_session_status"),
            continuation_decision=result.get("executor_continuation_decision"),
            resume_invocation_preview=result.get("executor_resume_invocation_preview"),
            continuation_preview=result.get("executor_continuation_preview"),
        )
        try:
            result["plan_versions"] = self._build_plan_version_list_for_v2()
        except Exception:
            result["plan_versions"] = []
        result["operation_running"] = self.operation_running
        result["operation_name"] = self.operation_name
        result["operation_started_at"] = self.operation_started_at
        result["last_operation_result"] = self.last_operation_result
        return result

    def _enrich_latest_report_identity(self, result: dict[str, Any]) -> None:
        try:
            snapshot = result.get("fact_snapshot")
            if not isinstance(snapshot, dict):
                return
            lr_box = snapshot.get("latest_report")
            if not isinstance(lr_box, dict) or not lr_box.get("available"):
                return
            latest = lr_box.get("latest")
            if not isinstance(latest, dict):
                return
            report_id = str(latest.get("report_id") or "").strip()
            if not report_id:
                return
            from runner.executor_read import handle_inspect_executor_activity
            detail = handle_inspect_executor_activity(
                self.project_root,
                "get_report",
                {"report_id": report_id, "include_markdown": False},
            )
            if not detail.get("ok"):
                return
            report = detail.get("report")
            if not isinstance(report, dict):
                return
            lineage = report.get("execution_lineage")
            run_id = ""
            if isinstance(lineage, dict):
                run_id = str(lineage.get("run_id") or "")
                if not latest.get("run_id"):
                    latest["run_id"] = run_id
                if not latest.get("preview_id"):
                    latest["preview_id"] = str(lineage.get("preview_id") or "")
                if not latest.get("executor_model"):
                    latest["executor_model"] = str(lineage.get("model") or "")
                if not latest.get("session_id_full"):
                    latest["session_id_full"] = str(lineage.get("session_id_full") or "")
                if not latest.get("session_id_full"):
                    identity = self._latest_report_session_identity_from_current_session(
                        latest=latest,
                        lineage=lineage,
                    )
                    if identity.get("identity_present") is True:
                        latest["session_id_full"] = str(identity.get("identity_value") or "")
                        latest["session_identity_value"] = str(identity.get("identity_value") or "")
                        latest["session_identity_kind"] = str(identity.get("identity_kind") or "")
                        latest["session_identity_label"] = str(identity.get("identity_label") or "会话标识")
                        latest["session_identity_source"] = str(identity.get("identity_source") or "")
                if not latest.get("session_mode"):
                    used_resume = lineage.get("used_resume") is True
                    latest["session_mode"] = "resume" if used_resume else "new"
                    latest["session_mode_label"] = "续接" if used_resume else "新开"
            changed = report.get("changed_files")
            if isinstance(changed, list) and not latest.get("changed_files"):
                latest["changed_files"] = [str(f) for f in changed if isinstance(f, str)]
            events = report.get("events")
            if isinstance(events, list) and not isinstance(latest.get("events"), list):
                latest["events"] = events
        except Exception:
            pass

    def _latest_report_session_identity_from_current_session(
        self,
        *,
        latest: dict[str, Any],
        lineage: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            status = self.executor_session_store.get_status()
        except Exception:
            status = {}
        record = status.get("record") if isinstance(status, dict) and isinstance(status.get("record"), dict) else {}
        if not record:
            return {"identity_present": False}

        latest_provider = str(latest.get("provider") or "").strip()
        record_provider = str(record.get("provider") or "").strip()
        if latest_provider and record_provider and latest_provider != record_provider:
            return {"identity_present": False}

        latest_version = str(latest.get("version") or "").strip()
        record_version = str(record.get("version") or "").strip()
        if latest_version and record_version and latest_version != record_version:
            return {"identity_present": False}

        return select_executor_identity_for_display(
            run_identity={"report": {"execution_lineage": lineage}},
            session_record=record,
            provider=latest_provider or record_provider,
            fallback_value=str(latest.get("session_id_full") or ""),
        )

    def _build_registry_action_outcome(
        self,
        result: dict[str, Any],
        error_code: str | None = None,
    ) -> dict[str, Any]:
        if result.get("ok"):
            return {
                "ok": True,
                "source": "web_v2",
                "action": result.get("action", "project_registry"),
                "status": "succeeded",
                "risk_level": "info",
                "action_outcome": {
                    "code": "SUCCESS",
                    "message": result.get("message", ""),
                },
                "removed_count": result.get("removed_count", 0),
                "project_count": result.get("project_count", 0),
                "project_registry": self._api_project_registry(),
            }
        return {
            "ok": False,
            "source": "web_v2",
            "action": "project_registry",
            "status": "failed",
            "risk_level": "error",
            "action_outcome": {
                "code": "FAILED",
                "message": result.get("message", ""),
                "error_code": error_code or result.get("error_code", "REGISTRY_ACTION_FAILED"),
            },
            "project_registry": self._api_project_registry(),
        }

    def _handle_registry_action(self, action_name: str, next_action: dict[str, Any]) -> dict[str, Any] | None:
        if action_name == "project_registry_unregister":
            with self.operation_lock:
                if self.operation_running or self.job.get("status") == "running":
                    return self._build_registry_action_outcome(
                        {"ok": False, "message": "当前有操作正在运行，不能操作登记列表。", "error_code": "OPERATION_RUNNING"},
                    )
            params = next_action.get("params") or {}
            project_id = params.get("project_id") if isinstance(params.get("project_id"), str) else None
            project_root = params.get("project_root") if isinstance(params.get("project_root"), str) else None
            if project_root and os.path.realpath(project_root) == self.project_root:
                return self._build_registry_action_outcome(
                    {
                        "ok": False,
                        "message": "不能移除当前正在使用的项目。请先切换到其他项目后再操作。",
                        "error_code": "CANNOT_REMOVE_BOUND_PROJECT",
                    },
                )
            result = self.project_registry.unregister_project(
                project_id=project_id,
                project_root=project_root,
            )
            return self._build_registry_action_outcome(result)

        if action_name == "project_registry_prune_unavailable":
            result = self.project_registry.prune_unavailable_projects(preserve_project_root=self.project_root)
            return self._build_registry_action_outcome(result)

        if action_name == "project_registry_prune_temporary":
            result = self.project_registry.prune_temporary_projects(preserve_project_root=self.project_root)
            return self._build_registry_action_outcome(result)

        return None

    def _api_v2_action(self, body: dict[str, Any]) -> dict[str, Any]:
        next_action = body.get("next_action")
        if not isinstance(next_action, dict):
            return {
                "ok": False,
                "source": "web_v2",
                "action": "action",
                "status": "failed",
                "risk_level": "error",
                "action_outcome": {
                    "code": "FAILED",
                    "message": "请求缺少 next_action。",
                    "error_code": "MISSING_NEXT_ACTION",
                },
                "blockers": ["请求参数中未提供 next_action。"],
                "display_summary": {
                    "title": "请求错误",
                    "status_text": "failed",
                    "primary_message": "请求缺少 next_action，无法构造 CoreRequest。",
                    "next_step_text": "请刷新后重试。",
                    "detail_refs": [],
                },
            }

        action_name = (next_action.get("action") or "").lower()
        if self._is_web_remote_git_mutation_action(action_name):
            return self._json_safe(CoreOutput(
                ok=False,
                source="web_v2",
                action="action",
                status="blocked",
                risk_level="blocked",
                action_outcome={
                    "code": "FAILED",
                    "message": "Web Console remote Git mutation is prohibited; only read-only remote Git status is exposed.",
                    "error_code": "WEB_REMOTE_GIT_MUTATION_PROHIBITED",
                },
                blockers=["Web Console 不提供远程 Git push/pull/fetch apply 或 preview 路由。"],
                display_summary={
                    "title": "远程 Git 写入已拦截",
                    "status_text": "blocked",
                    "primary_message": "Web Console 仅展示只读 remote Git 状态，不执行远程 Git 变更。",
                    "next_step_text": "如需远程 Git 操作，请使用受控 MCP 流程和独立确认。",
                    "detail_refs": [],
                },
                audit={
                    "blocked_action": action_name,
                    "policy": "web_remote_git_mutation_prohibited",
                },
            ))
        registry_result = self._handle_registry_action(action_name, next_action)
        if registry_result is not None:
            return registry_result

        core_request = CoreRequest.from_web_action(
            next_action,
            client_context=body.get("client_context"),
            raw_payload=body,
        )

        if core_request.write_intent:
            target_action = (core_request.target_scope or {}).get("action", "unknown") if core_request.write_intent else "unknown"
            return self._json_safe(CoreOutput(
                ok=False,
                source="web_v2",
                action="action",
                status="blocked",
                risk_level="blocked",
                action_outcome={
                    "code": "FAILED",
                    "message": f"Web v2 第一版暂不支持写入型动作：{target_action}。",
                    "error_code": "WRITE_INTENT_BLOCKED",
                },
                blockers=[f"写入型动作 {target_action} 已被 Web v2 第一版安全拦截。请通过 MCP 或旧 Web 执行。"],
                display_summary={
                    "title": "写入已拦截",
                    "status_text": "blocked",
                    "primary_message": f"动作 {target_action} 是写入型操作，Web v2 第一版不做写入。",
                    "next_step_text": "请使用 MCP 客户端或旧 Web Console 执行此操作。",
                    "detail_refs": [],
                },
                audit={
                    "source": "web_v2",
                    "workflow": "action",
                    "phase": None,
                },
            ))

        orchestrator = WorkflowOrchestrator(self.project_root)
        core_output = orchestrator.handle_request(core_request)
        return self._json_safe(core_output)

    @staticmethod
    def _api_v2_health() -> dict[str, Any]:
        return {"ok": True, "version": "v2"}

    def _render_v2_index_html(self, web_read_token: str = "") -> str:
        return render_v2_index_page(csrf_token=self._csrf_token, web_read_token=web_read_token)
