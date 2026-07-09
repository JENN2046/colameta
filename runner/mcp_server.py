import json
import copy
import threading
import os
import re
import sys
import time
import hashlib
import urllib.request
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from runner.http_server_utils import ReusableThreadingHTTPServer
from runner.mcp_external_oauth import ExternalOAuthConfig, ExternalOAuthProvider
from runner.mcp_oauth import MCPOAuthProvider, default_server_oauth_store_file
from runner.planning_bridge import PlanningBridge, PlanningBridgeError
from runner.source_review_bridge import SourceReviewBridge, SourceReviewError
from runner.executor_inventory import load_executor_inventory
from runner.executor_run_reports import ExecutorRunReportStore
from runner.executor_session import ExecutorSessionStore
from runner.executor_status import polling_guidance_for_profile
from runner.project_identity import build_project_identity
from runner.project_registry import ProjectRegistry
from runner.execution_standards import get_execution_standards
from runner.plan_standards_linter import PlanStandardsLinter
from runner.mcp_git_commit import MCPGitCommitManager
from runner.mcp_git_remote import MCPGitRemoteManager
from runner.mcp_runner_plan import MCPRunnerPlanManager
from runner.mcp_decisions import MCPDecisionRecordsManager
from runner.mcp_project_memory import MCPProjectMemoryManager
from runner.mcp_todolist import MCPTodoListManager
from runner.mcp_project_patch import MCPProjectPatchManager
from runner.mcp_git_history import MCPGitHistoryManager
from runner.mcp_plan_workflow import MCPPlanWorkflowManager
from runner.mcp_project_docs import MCPProjectDocsManager
from runner.mcp_workflow_router import MCPWorkflowRouter
from runner.core_orchestrator import WorkflowOrchestrator
from runner.core_workflow_registry import SUPPORTED_CORE_WORKFLOWS, normalize_workflow_name, is_supported_core_workflow
from runner.mcp_executor_workflow import MCPExecutorWorkflowManager
from runner.mcp_executor_config import MCPExecutorConfigManager
from runner.mcp_validation_run import MCPValidationRunManager
from runner.executor_read import handle_inspect_executor_activity
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
from runner.product_readiness import (
    build_chatgpt_connection_packet,
    build_product_readiness_packet,
)
from runner.full_loop_authority import build_full_loop_authority_status
from runner.product_console import (
    build_submission_evidence_activity_result,
    build_product_console_map,
    build_submission_evidence_fill_preview,
    record_product_console_action_result,
)
from runner.release_submission_readiness import (
    build_release_submission_readiness,
    fill_submission_evidence_files,
    init_submission_evidence_scaffold,
    mark_submission_evidence_ready_fields,
)
from runner.stable_promotion_readiness import DEFAULT_STABLE_RUNTIME_DIR, get_stable_promotion_readiness
from runner.service_lifecycle_store import ServiceLifecycleStore
from runner.stage_parallel_plan import (
    build_stage_parallel_closeout_packet,
    build_stage_parallel_executor_group_preview,
    build_stage_parallel_group_status,
    build_stage_parallel_merge_preview,
    build_stage_parallel_plan_preview,
    build_stage_parallel_run_preview,
    build_stage_parallel_worktree_assignment_preview,
)
from runner.stage_parallel_executor_results import build_stage_parallel_executor_results_packet
from runner.stage_parallel_next_action import build_stage_parallel_next_action_packet
from runner.workflow_engine import should_record_tool, record_tool_call
from runner.workflow_records import WorkflowRecordStore
from runner.runner_paths import (
    is_project_runner_path,
    resolve_project_runner_dir,
    resolve_project_runner_path,
    resolve_project_runner_plan_path,
    resolve_project_runner_rel_dir,
)


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(minimum, value)


def _env_float(name: str, default: float, *, minimum: float = 0.1) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return max(minimum, value)


MCP_EXPOSURE_PROFILE_ENV = "MCP_EXPOSURE_PROFILE"
MCP_EXPOSURE_PROFILE_NORMAL = "normal"
MCP_EXPOSURE_PROFILE_MAINTAINER = "maintainer"
MCP_EXPOSURE_PROFILE_LEGACY = "legacy"
ACTIONS_API_PREFIX = "/api/"
ACTIONS_TARGET_RESPONSE_CHARS = 60000
ACTIONS_HARD_RESPONSE_CHARS = 75000
ACTIONS_HARD_REQUEST_CHARS = 90000
MCP_HARD_REQUEST_CHARS = ACTIONS_HARD_REQUEST_CHARS
MCP_REQUEST_TIMEOUT_SECONDS = _env_float("COLAMETA_MCP_REQUEST_TIMEOUT_SECONDS", 10.0, minimum=0.5)
MCP_GLOBAL_RATE_LIMIT_PER_MINUTE = _env_int("COLAMETA_MCP_GLOBAL_RATE_LIMIT_PER_MINUTE", 240)
MCP_GLOBAL_RATE_LIMIT_BURST = _env_int("COLAMETA_MCP_GLOBAL_RATE_LIMIT_BURST", 80)
MCP_CLIENT_RATE_LIMIT_PER_MINUTE = _env_int("COLAMETA_MCP_CLIENT_RATE_LIMIT_PER_MINUTE", 120)
MCP_CLIENT_RATE_LIMIT_BURST = _env_int("COLAMETA_MCP_CLIENT_RATE_LIMIT_BURST", 40)
MCP_CLIENT_RATE_LIMIT_BUCKETS = _env_int("COLAMETA_MCP_CLIENT_RATE_LIMIT_BUCKETS", 2048)
MCP_TARGET_TOOL_RESULT_CHARS = 60000
MCP_HARD_TOOL_RESULT_CHARS = 75000
REMOTE_EXTERNAL_OAUTH_POLICY = "remote_public"
COMMANDER_APP_WIDGET_URI = "ui://colameta/commander/v1.html"
COMMANDER_APP_WIDGET_MIME_TYPE = "text/html;profile=mcp-app"
COMMANDER_APP_MANIFEST_VERSION = "colameta_commander_app.v1"
COMMANDER_APP_TITLE = "ColaMeta Commander"
COMMANDER_APP_SERVER_INSTRUCTIONS = (
    "ColaMeta Commander is a read-only ChatGPT App surface for local ColaMeta service facts. "
    "Start with list_registered_projects, get_agent_consumer_contract, get_service_entry_profile, "
    "get_agent_operator_flow_packet, then render_commander_app with a registered project_name and profile_id. "
    "Treat manifest, runtime, connector, "
    "profile, and preview outputs as evidence only; they do not authorize executor run, commit, push, "
    "stable service replacement, ReviewDecision, GateEvent, or Delivery accepted."
)

REMOTE_EXTERNAL_OAUTH_DENIED_SCOPES: dict[str, str] = {
    "mcp:commit": "REMOTE_MCP_COMMIT_DENIED",
    "mcp:plan": "REMOTE_MCP_PLAN_DENIED",
}


NORMAL_EXPOSED_TOOLS = (
    "list_registered_projects",
    "get_agent_consumer_contract",
    "get_service_entry_profile",
    "get_agent_operator_flow_packet",
    "get_web_gpt_service_entrypoint",
    "get_product_readiness_status",
    "get_chatgpt_app_readiness",
    "get_full_loop_authority_status",
    "get_product_console_map",
    "get_release_submission_readiness",
    "get_submission_evidence_fill_preview",
    "get_submission_evidence_auto_draft",
    "init_submission_evidence",
    "fill_submission_evidence_files",
    "mark_submission_evidence_ready_fields",
    "record_product_console_action_result",
    "get_commander_app_manifest",
    "render_commander_app",
    "get_apps_connector_smoke_packet",
    "get_stable_replacement_cadence",
    "get_stable_promotion_readiness",
    "get_stage_parallel_plan_preview",
    "get_stage_parallel_run_preview",
    "get_stage_parallel_worktree_assignment_preview",
    "get_stage_parallel_next_action_packet",
    "get_stage_parallel_executor_group_preview",
    "get_stage_parallel_executor_results_packet",
    "get_stage_parallel_group_status",
    "get_stage_parallel_merge_preview",
    "get_stage_parallel_closeout_packet",
    "get_runtime_version_status",
    "get_connector_runtime_health_status",
    "analyze_project_state",
    "run_mcp_workflow",
    "manage_executor_config",
    "manage_executor_workflow",
    "manage_validation_run",
    "manage_stage_parallel_worktrees",
    "manage_stage_parallel_shard_inputs",
    "manage_stage_parallel_executor_group",
    "manage_stage_parallel_executor_runs",
    "manage_stage_parallel_merges",
    "manage_git",
    "manage_project_docs",
    "manage_prompt_file",
    "manage_workflow_run",
    "get_runner_execution_standards",
    "get_plan_standards_report",
    "manage_files",
    "manage_runner_plan",
    "manage_project_memory",
    "manage_plan_version",
    "list_executor_run_reports",
    "get_executor_run_report",
    "inspect_executor_activity",
)

MAINTAINER_EXTRA_TOOLS = (
    "get_project_identity",
    "get_runner_workbench_context",
)

LEGACY_EXTRA_TOOLS = (
    "get_runner_status",
    "get_plan_overview",
    "get_next_version_plan",
    "get_version_result",
    "get_project_doc_section",
    "get_plan_patch_status",
    "get_executor_session_status",
    "get_executor_continuation_preview",
    "get_executor_continuation_decision",
    "get_executor_resume_invocation_preview",
    "get_executor_inventory",
    "get_git_log",
    "get_repo_overview",
    "preview_insert_version",
    "preview_update_version",
    "manage_plan_workflow",
)

_PROFILE_ORDERS: dict[str, tuple[str, ...]] = {
    MCP_EXPOSURE_PROFILE_NORMAL: NORMAL_EXPOSED_TOOLS,
    MCP_EXPOSURE_PROFILE_MAINTAINER: NORMAL_EXPOSED_TOOLS + MAINTAINER_EXTRA_TOOLS,
    MCP_EXPOSURE_PROFILE_LEGACY: NORMAL_EXPOSED_TOOLS + MAINTAINER_EXTRA_TOOLS + LEGACY_EXTRA_TOOLS,
}


_SUPPORTED_MCP_WORKFLOWS = SUPPORTED_CORE_WORKFLOWS
_normalize_run_mcp_workflow_name = normalize_workflow_name


def _find_next_actions(result: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Extract next_actions list from a tool result dict, handling both flat and data-wrapped structures."""
    next_actions = result.get("next_actions")
    if isinstance(next_actions, list):
        return next_actions
    data = result.get("data")
    if isinstance(data, dict):
        next_actions = data.get("next_actions")
        if isinstance(next_actions, list):
            return next_actions
    return None


class _MCPRateLimiter:
    def __init__(
        self,
        *,
        global_per_minute: int,
        global_burst: int,
        client_per_minute: int,
        client_burst: int,
        max_client_buckets: int = MCP_CLIENT_RATE_LIMIT_BUCKETS,
    ) -> None:
        now = time.monotonic()
        self.global_per_minute = max(1, global_per_minute)
        self.global_burst = max(1, global_burst)
        self.client_per_minute = max(1, client_per_minute)
        self.client_burst = max(1, client_burst)
        self.max_client_buckets = max(1, max_client_buckets)
        self._global_bucket: dict[str, float] = {"tokens": float(self.global_burst), "updated_at": now}
        self._client_buckets: dict[str, dict[str, float]] = {}
        self._lock = threading.Lock()

    def check(self, client_id: str) -> dict[str, Any]:
        now = time.monotonic()
        with self._lock:
            self._refill(self._global_bucket, self.global_per_minute, self.global_burst, now)
            if self._global_bucket["tokens"] < 1.0:
                return self._denied("MCP_GLOBAL_RATE_LIMITED", self._global_bucket, self.global_per_minute)
            client_bucket = self._client_buckets.get(client_id)
            if client_bucket is None:
                self._prune_clients(now)
                if len(self._client_buckets) >= self.max_client_buckets:
                    return self._denied("MCP_CLIENT_BUCKET_LIMITED", self._global_bucket, self.global_per_minute)
                client_bucket = {"tokens": float(self.client_burst), "updated_at": now}
                self._client_buckets[client_id] = client_bucket
            self._refill(client_bucket, self.client_per_minute, self.client_burst, now)
            if client_bucket["tokens"] < 1.0:
                return self._denied("MCP_CLIENT_RATE_LIMITED", client_bucket, self.client_per_minute)
            self._global_bucket["tokens"] -= 1.0
            client_bucket["tokens"] -= 1.0
            return {"ok": True}

    def _refill(self, bucket: dict[str, float], per_minute: int, burst: int, now: float) -> None:
        elapsed = max(0.0, now - bucket["updated_at"])
        bucket["tokens"] = min(float(burst), bucket["tokens"] + elapsed * (float(per_minute) / 60.0))
        bucket["updated_at"] = now

    def _denied(self, reason_code: str, bucket: dict[str, float], per_minute: int) -> dict[str, Any]:
        missing = max(0.0, 1.0 - bucket["tokens"])
        seconds = missing / max(float(per_minute) / 60.0, 0.001)
        retry_after_seconds = max(1, min(60, int(seconds + 0.999)))
        return {
            "ok": False,
            "reason_code": reason_code,
            "retry_after_seconds": retry_after_seconds,
        }

    def _prune_clients(self, now: float) -> None:
        if len(self._client_buckets) < self.max_client_buckets:
            return
        stale_before = now - 300.0
        stale = [key for key, bucket in self._client_buckets.items() if bucket.get("updated_at", now) < stale_before]
        for key in stale[: max(1, self.max_client_buckets // 4)]:
            self._client_buckets.pop(key, None)


def _stage_parallel_preview_input_schema(*, include_executor_results: bool = False) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "project_name": {
            "type": "string",
            "description": "可选。按已登记 project_name 路由读取目标项目；服务模式下必须显式提供。",
        },
        "stage_id": {
            "type": "string",
            "description": "可选。要规划的阶段 ID；不传时使用 stage_parallel_automation。",
        },
        "provider": {
            "type": "string",
            "enum": ["codex", "opencode", "pi"],
            "description": "可选。未来 executor preview 的 provider 偏好。默认 codex。",
        },
        "base_branch": {
            "type": "string",
            "description": "可选。未来隔离 worktree 的基准分支名。默认 main。",
        },
        "max_parallel_tasks": {
            "type": "integer",
            "minimum": 1,
            "maximum": 8,
            "description": "可选。最多纳入多少个候选 task shard。默认 3，最大 8。",
        },
        "task_intents": {
            "type": "array",
            "description": "可选。候选任务意图；只用于只读并行编排预览。",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "task_id": {"type": "string"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "allowed_files": {"type": "array", "items": {"type": "string"}},
                    "surfaces": {"type": "array", "items": {"type": "string"}},
                    "risk_level": {
                        "type": "string",
                        "enum": ["none", "low", "moderate", "high", "blocked"],
                    },
                },
                "required": ["title"],
            },
        },
    }
    if include_executor_results:
        properties["executor_results"] = {
            "type": "array",
            "description": "可选。调用方提供的 sanitized executor result 摘要；不读取 raw logs。",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "task_id": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": ["planned", "running", "succeeded", "failed", "blocked", "unknown"],
                    },
                    "validation_status": {
                        "type": "string",
                        "enum": ["not_run", "running", "passed", "failed", "blocked", "unknown"],
                    },
                    "head": {"type": "string"},
                    "changed_files": {"type": "array", "items": {"type": "string"}},
                    "summary": {"type": "string"},
                },
                "required": ["task_id", "status"],
            },
        }
    return {
        "type": "object",
        "properties": properties,
        "required": [],
        "additionalProperties": False,
    }


def _manage_stage_parallel_worktrees_input_schema() -> dict[str, Any]:
    schema = _stage_parallel_preview_input_schema()
    properties = dict(schema["properties"])
    properties["action"] = {
        "type": "string",
        "enum": ["preview", "apply", "status", "discard"],
        "description": "preview 生成受控 worktree apply preview；apply 用 preview_id 创建 worktree；status/discard 读取或废弃 preview。",
    }
    properties["preview_id"] = {
        "type": "string",
        "description": "apply/status/discard 必填。来自 preview 的 preview_id。",
    }
    properties["reason"] = {
        "type": "string",
        "description": "preview 可选。记录创建并行 worktree preview 的原因。",
    }
    return {
        "type": "object",
        "properties": properties,
        "required": ["action"],
        "additionalProperties": False,
    }


def _manage_stage_parallel_executor_group_input_schema() -> dict[str, Any]:
    schema = _stage_parallel_preview_input_schema()
    properties = dict(schema["properties"])
    properties["action"] = {
        "type": "string",
        "enum": ["preview", "apply", "status", "discard"],
        "description": "preview 校验已创建 worktree 并生成 group preview；apply 用 preview_id 批量创建 executor run_once_preview artifacts。",
    }
    properties["preview_id"] = {
        "type": "string",
        "description": "apply/status/discard 必填。来自 preview 的 preview_id。",
    }
    properties["reason"] = {
        "type": "string",
        "description": "preview 可选。记录创建 executor preview group 的原因。",
    }
    return {
        "type": "object",
        "properties": properties,
        "required": ["action"],
        "additionalProperties": False,
    }


def _manage_stage_parallel_shard_inputs_input_schema() -> dict[str, Any]:
    schema = _stage_parallel_preview_input_schema()
    properties = dict(schema["properties"])
    properties["action"] = {
        "type": "string",
        "enum": ["preview", "apply", "status", "discard"],
        "description": "preview 校验已创建 worktree 并生成 shard input preview；apply 用 preview_id 写入每个 shard 的 runtime plan/state/prompt overlay。",
    }
    properties["preview_id"] = {
        "type": "string",
        "description": "apply/status/discard 必填。来自 preview 的 preview_id。",
    }
    properties["reason"] = {
        "type": "string",
        "description": "preview 可选。记录写入 shard runner input 的原因。",
    }
    return {
        "type": "object",
        "properties": properties,
        "required": ["action"],
        "additionalProperties": False,
    }


def _manage_stage_parallel_executor_runs_input_schema() -> dict[str, Any]:
    schema = _stage_parallel_preview_input_schema()
    properties = dict(schema["properties"])
    properties["action"] = {
        "type": "string",
        "enum": ["preview", "apply", "status", "discard"],
        "description": "preview 校验已创建 executor preview artifacts 并生成 run group preview；apply 用 preview_id 启动隔离 worktree executor runs。",
    }
    properties["preview_id"] = {
        "type": "string",
        "description": "apply/status/discard 必填。来自 preview 的 preview_id。",
    }
    properties["reason"] = {
        "type": "string",
        "description": "preview 可选。记录启动并行 executor run group 的原因。",
    }
    return {
        "type": "object",
        "properties": properties,
        "required": ["action"],
        "additionalProperties": False,
    }


def _manage_stage_parallel_merges_input_schema() -> dict[str, Any]:
    schema = _stage_parallel_preview_input_schema(include_executor_results=True)
    properties = dict(schema["properties"])
    properties["action"] = {
        "type": "string",
        "enum": ["preview", "apply", "status", "discard"],
        "description": "preview 生成受控 stage parallel merge apply preview；apply 用 preview_id 顺序执行本地 git merge。",
    }
    properties["preview_id"] = {
        "type": "string",
        "description": "apply/status/discard 必填。来自 preview 的 preview_id。",
    }
    properties["reason"] = {
        "type": "string",
        "description": "preview 可选。记录执行并行 merge gate 的原因。",
    }
    return {
        "type": "object",
        "properties": properties,
        "required": ["action"],
        "additionalProperties": False,
    }


PROJECT_NAME_REQUIRED_TOOLS = {
    "get_agent_operator_flow_packet",
    "get_product_readiness_status",
    "get_chatgpt_app_readiness",
    "get_full_loop_authority_status",
    "get_product_console_map",
    "get_release_submission_readiness",
    "get_submission_evidence_fill_preview",
    "get_submission_evidence_auto_draft",
    "init_submission_evidence",
    "fill_submission_evidence_files",
    "mark_submission_evidence_ready_fields",
    "record_product_console_action_result",
    "get_commander_app_manifest",
    "render_commander_app",
    "get_apps_connector_smoke_packet",
    "get_stable_replacement_cadence",
    "get_stable_promotion_readiness",
    "get_stage_parallel_plan_preview",
    "get_stage_parallel_run_preview",
    "get_stage_parallel_worktree_assignment_preview",
    "get_stage_parallel_next_action_packet",
    "get_stage_parallel_executor_group_preview",
    "get_stage_parallel_executor_results_packet",
    "get_stage_parallel_group_status",
    "get_stage_parallel_merge_preview",
    "get_stage_parallel_closeout_packet",
    "get_runtime_version_status",
    "get_connector_runtime_health_status",
    "get_plan_standards_report",
    "get_review_context",
    "manage_project_memory",
    "manage_git",
    "manage_git_commit",
    "manage_git_remote",
    "todo_read",
    "todo_add",
    "todo_update",
    "todo_delete",
    "decision_read",
    "decision_add",
    "decision_update",
    "decision_delete",
    "manage_plan_version",
    "manage_git_history",
    "manage_project_docs",
    "manage_prompt_file",
    "manage_files",
    "get_git_status",
    "get_git_diff",
    "list_executor_run_reports",
    "get_executor_run_report",
    "inspect_executor_activity",
    "analyze_project_state",
    "run_mcp_workflow",
    "manage_executor_config",
    "manage_executor_workflow",
    "manage_validation_run",
    "manage_stage_parallel_worktrees",
    "manage_stage_parallel_shard_inputs",
    "manage_stage_parallel_executor_group",
    "manage_stage_parallel_executor_runs",
    "manage_stage_parallel_merges",
    "manage_workflow_run",
    "list_workflow_runs",
    "get_workflow_run",
}


def _parse_prompt_front_matter(content: str) -> tuple[dict[str, Any], str | None]:
    if not content:
        return {}, None
    lines = content.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, content
    end_idx = -1
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx == -1:
        return {}, None
    raw = "\n".join(lines[1:end_idx])
    body = "\n".join(lines[end_idx + 1:])
    fm: dict[str, Any] = {}
    stack: list[tuple[str, Any, int]] = []
    for line in raw.split("\n"):
        stripped_line = line.lstrip()
        indent = len(line) - len(stripped_line)
        if not stripped_line or stripped_line.startswith("#"):
            continue
        list_match = re.match(r"^-\s+(.+)$", stripped_line)
        kv_match = re.match(r"^(\w[\w-]*):\s*(.*)$", stripped_line)
        if list_match:
            val = list_match.group(1).strip()
            while stack and stack[-1][2] >= indent:
                stack.pop()
            if stack:
                parent_key, parent_dict, _ = stack[-1]
                if not isinstance(parent_dict.get(parent_key), list):
                    parent_dict[parent_key] = []
                parent_dict[parent_key].append(val)
        elif kv_match:
            key = kv_match.group(1)
            raw_val = kv_match.group(2).strip()
            val: Any = raw_val
            val_lower = raw_val.lower()
            if val_lower in ("true", "yes"):
                val = True
            elif val_lower in ("false", "no"):
                val = False
            while stack and stack[-1][2] >= indent:
                stack.pop()
            target: dict[str, Any] = fm
            if stack:
                parent_key, parent_dict, _ = stack[-1]
                parent_val = parent_dict.get(parent_key)
                if isinstance(parent_val, dict):
                    target = parent_val
                else:
                    parent_dict[parent_key] = {}
                    target = parent_dict[parent_key]
            if raw_val == "":
                target[key] = {}
                stack.append((key, target, indent))
            else:
                target[key] = val
                stack.append((key, target, indent))
    return fm, body


@dataclass
class MCPToolDef:
    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    title: str | None = None
    annotations: dict[str, Any] | None = None
    meta: dict[str, Any] | None = None


VALID_MCP_SCOPES = frozenset({"mcp:read", "mcp:preview", "mcp:commit", "mcp:plan"})


@dataclass(frozen=True)
class MCPToolPolicy:
    name: str
    selector: str = "static"
    static_scope: str | None = None
    action_scopes: dict[str, str] | None = None
    default_scope: str | None = None
    side_effects: bool = False
    requires_confirmation: bool = False
    remote_public_allowed: bool = True

    def scope_for(self, params: dict[str, Any]) -> str | None:
        if self.selector == "static":
            return self.static_scope
        if self.selector == "action":
            action = _policy_string_param(params, "action")
            return (self.action_scopes or {}).get(action) or self.default_scope
        if self.selector == "manage_files":
            return _manage_files_policy_scope(params)
        if self.selector == "run_mcp_workflow":
            return _run_mcp_workflow_policy_scope(params)
        return None


def _policy_string_param(params: dict[str, Any], key: str) -> str:
    value = params.get(key)
    return value.strip().lower() if isinstance(value, str) else ""


def _static_policy(name: str, scope: str) -> MCPToolPolicy:
    return MCPToolPolicy(
        name=name,
        static_scope=scope,
        side_effects=scope not in {"mcp:read", "mcp:preview"},
        requires_confirmation=scope not in {"mcp:read"},
        remote_public_allowed=scope in {"mcp:read", "mcp:preview"},
    )


def _action_policy(name: str, action_scopes: dict[str, str], *, default_scope: str | None = None) -> MCPToolPolicy:
    return MCPToolPolicy(
        name=name,
        selector="action",
        action_scopes=action_scopes,
        default_scope=default_scope,
        side_effects=any(scope not in {"mcp:read", "mcp:preview"} for scope in action_scopes.values())
        or default_scope not in {None, "mcp:read", "mcp:preview"},
        requires_confirmation=any(scope != "mcp:read" for scope in action_scopes.values())
        or default_scope not in {None, "mcp:read"},
        remote_public_allowed=all(scope in {"mcp:read", "mcp:preview"} for scope in action_scopes.values())
        and default_scope in {None, "mcp:read", "mcp:preview"},
    )


def _manage_files_policy_scope(params: dict[str, Any]) -> str | None:
    action = _policy_string_param(params, "action")
    if action in {"search", "read"}:
        return "mcp:read"
    if action in {"create", "edit", "delete"}:
        phase = _policy_string_param(params, "phase")
        if phase == "status":
            return "mcp:read"
        if phase == "preview":
            return "mcp:preview"
        if phase == "apply":
            return "mcp:commit"
    return None


def _run_mcp_workflow_policy_scope(params: dict[str, Any]) -> str | None:
    workflow = _policy_string_param(params, "workflow")
    phase = _policy_string_param(params, "phase")
    docs_action = _policy_string_param(params, "docs_action")
    if workflow == "auto_preview":
        return "mcp:preview"
    if workflow == "project_status":
        return "mcp:read"
    if workflow == "source_onboarding":
        if phase in {"", "preview"}:
            return "mcp:preview"
        return None
    if workflow == "plan_update":
        if phase == "apply":
            return "mcp:commit"
        if phase in {"", "preview"}:
            return "mcp:preview"
        return None
    if workflow == "thin_governed_loop_preview":
        return "mcp:read"
    if workflow == "small_project_patch":
        if phase == "status":
            return "mcp:read"
        if phase == "preview":
            return "mcp:preview"
        if phase in {"apply", ""}:
            return "mcp:commit"
        return None
    if workflow == "docs_update":
        if docs_action in {"index", "search", "read_section"}:
            return "mcp:read" if phase in {"", "inspect"} else None
        if docs_action in {"update_section_preview", "append_section_preview", "sync_docs_preview"}:
            return "mcp:preview" if phase in {"", "preview"} else None
        if docs_action == "apply":
            return "mcp:commit"
        if phase in {"", "inspect"}:
            return "mcp:read"
        if phase == "preview":
            return "mcp:preview"
        if phase == "apply":
            return "mcp:commit"
        return None
    if workflow == "git_commit":
        if phase in {"inspect", "status"}:
            return "mcp:read"
        if phase == "preview":
            return "mcp:preview"
        if phase in {"apply", "commit", ""}:
            return "mcp:commit"
        return None
    if workflow in {"git_restore_file", "git_revert"}:
        if phase == "preview":
            return "mcp:preview"
        if phase in {"apply", ""}:
            return "mcp:commit"
        return None
    if workflow == "git_undo_version":
        if phase == "inspect":
            return "mcp:read"
        if phase == "preview":
            return "mcp:preview"
        if phase in {"apply", ""}:
            return "mcp:commit"
        return None
    if workflow == "agent_dispatch":
        if phase in {"inspect", "status"}:
            return "mcp:read"
        if phase in {"preview", "run_preview"}:
            return "mcp:preview"
        if phase in {"run", "apply", ""}:
            return "mcp:commit"
        return None
    if workflow == "prompt_to_plan":
        if phase in {"preview", "plan_preview", "run_preview"}:
            return "mcp:preview"
        if phase in {"apply", "plan_apply", "apply_all", "run"}:
            return "mcp:commit"
        return None
    return None


def _build_mcp_tool_policies() -> dict[str, MCPToolPolicy]:
    read_tools = {
        "list_registered_projects",
        "get_agent_consumer_contract",
        "get_service_entry_profile",
        "get_agent_operator_flow_packet",
        "get_web_gpt_service_entrypoint",
        "get_product_readiness_status",
        "get_chatgpt_app_readiness",
        "get_full_loop_authority_status",
        "get_product_console_map",
        "get_release_submission_readiness",
        "get_submission_evidence_fill_preview",
        "get_submission_evidence_auto_draft",
        "get_commander_app_manifest",
        "render_commander_app",
        "get_apps_connector_smoke_packet",
        "get_stable_replacement_cadence",
        "get_stable_promotion_readiness",
        "get_stage_parallel_plan_preview",
        "get_stage_parallel_run_preview",
        "get_stage_parallel_worktree_assignment_preview",
        "get_stage_parallel_next_action_packet",
        "get_stage_parallel_executor_group_preview",
        "get_stage_parallel_executor_results_packet",
        "get_stage_parallel_group_status",
        "get_stage_parallel_merge_preview",
        "get_stage_parallel_closeout_packet",
        "get_runtime_version_status",
        "get_connector_runtime_health_status",
        "get_runner_status",
        "get_version_result",
        "get_next_version_plan",
        "get_plan_overview",
        "get_review_context",
        "get_runner_workbench_context",
        "get_project_doc_section",
        "get_plan_patch_status",
        "get_repo_overview",
        "get_git_status",
        "get_git_log",
        "get_source_file",
        "search_source",
        "get_git_diff",
        "get_executor_inventory",
        "get_project_identity",
        "get_runner_execution_standards",
        "get_plan_standards_report",
        "get_executor_session_status",
        "get_executor_continuation_preview",
        "get_executor_continuation_decision",
        "get_executor_resume_invocation_preview",
        "manage_workflow_run",
        "todo_read",
        "decision_read",
        "list_executor_run_reports",
        "get_executor_run_report",
        "analyze_project_state",
        "inspect_executor_activity",
        "list_workflow_runs",
        "get_workflow_run",
    }
    policies = {name: _static_policy(name, "mcp:read") for name in read_tools}
    for name in ("preview_insert_version", "preview_update_version", "manage_plan_workflow"):
        policies[name] = _static_policy(name, "mcp:preview")
    for name in (
        "init_submission_evidence",
        "fill_submission_evidence_files",
        "mark_submission_evidence_ready_fields",
        "record_product_console_action_result",
        "todo_add",
        "todo_update",
        "todo_delete",
        "decision_add",
        "decision_update",
        "decision_delete",
    ):
        policies[name] = _static_policy(name, "mcp:commit")
    policies.update(
        {
            "manage_git": _action_policy(
                "manage_git",
                {
                    **dict.fromkeys(
                        (
                            "status",
                            "diff",
                            "review_context",
                            "commit_readiness",
                            "commit_message",
                            "push_status",
                            "pull_status",
                            "history_log",
                            "history_show",
                            "diff_commits",
                        ),
                        "mcp:read",
                    ),
                    **dict.fromkeys(
                        ("commit_preview", "push_preview", "pull_preview", "restore_file_preview", "revert_preview"),
                        "mcp:preview",
                    ),
                    **dict.fromkeys(
                        ("commit_apply", "push_apply", "pull_apply", "fetch_apply", "restore_file_apply", "revert_apply"),
                        "mcp:commit",
                    ),
                },
            ),
            "manage_git_commit": _action_policy(
                "manage_git_commit",
                {
                    "readiness": "mcp:read",
                    "suggest_commit_message": "mcp:read",
                    "preview": "mcp:preview",
                    "commit_workflow_preview": "mcp:preview",
                    "commit": "mcp:commit",
                    "apply": "mcp:commit",
                },
            ),
            "manage_git_remote": _action_policy(
                "manage_git_remote",
                {
                    "push_status": "mcp:read",
                    "pull_status": "mcp:read",
                    "push_preview": "mcp:preview",
                    "fetch_preview": "mcp:preview",
                    "pull_preview": "mcp:preview",
                    "push_apply": "mcp:commit",
                    "fetch_apply": "mcp:commit",
                    "pull_apply": "mcp:commit",
                },
            ),
            "manage_runner_plan": _action_policy(
                "manage_runner_plan",
                {"inspect": "mcp:read", "bootstrap_preview": "mcp:preview", "import_preview": "mcp:preview", "apply": "mcp:plan"},
            ),
            "manage_runner_record": _action_policy(
                "manage_runner_record",
                {"read": "mcp:read", "add": "mcp:commit", "update": "mcp:commit", "delete": "mcp:commit"},
            ),
            "manage_project_memory": _action_policy(
                "manage_project_memory",
                {"read": "mcp:read", "add": "mcp:commit", "update": "mcp:commit", "delete": "mcp:commit"},
            ),
            "manage_plan_version": _action_policy(
                "manage_plan_version",
                {
                    "inspect": "mcp:read",
                    "apply_preview_status": "mcp:read",
                    "insert_preview": "mcp:preview",
                    "update_preview": "mcp:preview",
                    "repair_preview": "mcp:preview",
                    "insert_from_prompt_file_preview": "mcp:preview",
                    "apply_preview": "mcp:commit",
                    "reload_plan": "mcp:commit",
                    "continue_next_version": "mcp:commit",
                },
            ),
            "manage_project_patch": _action_policy(
                "manage_project_patch",
                {"status": "mcp:read", "preview": "mcp:preview", "preview_delete": "mcp:preview", "apply": "mcp:commit"},
            ),
            "manage_git_history": _action_policy(
                "manage_git_history",
                {
                    "log": "mcp:read",
                    "show": "mcp:read",
                    "diff_commits": "mcp:read",
                    "reconcile_git_history_preview": "mcp:preview",
                    "restore_file_preview": "mcp:preview",
                    "revert_preview": "mcp:preview",
                    "restore_file_apply": "mcp:commit",
                    "revert_apply": "mcp:commit",
                },
            ),
            "manage_project_docs": _action_policy(
                "manage_project_docs",
                {
                    "index": "mcp:read",
                    "search": "mcp:read",
                    "read_section": "mcp:read",
                    "update_section_preview": "mcp:preview",
                    "append_section_preview": "mcp:preview",
                    "sync_docs_preview": "mcp:preview",
                    "apply": "mcp:commit",
                },
            ),
            "manage_prompt_file": _action_policy(
                "manage_prompt_file",
                {"status": "mcp:read", "preview": "mcp:preview", "discard": "mcp:preview", "apply": "mcp:commit"},
            ),
            "manage_executor_config": _action_policy(
                "manage_executor_config",
                {
                    "inspect_inventory": "mcp:read",
                    "probe_models_preview": "mcp:preview",
                    "set_default_profile_preview": "mcp:preview",
                    "probe_models_apply": "mcp:commit",
                    "set_default_profile_apply": "mcp:commit",
                },
            ),
            "manage_executor_workflow": _action_policy(
                "manage_executor_workflow",
                {
                    "preflight": "mcp:read",
                    "status": "mcp:read",
                    "get_audit_package": "mcp:read",
                    "run_once_preview": "mcp:preview",
                    "run_bounded_preview": "mcp:preview",
                    "recheck_report_preview": "mcp:preview",
                    "manual_fix_prompt_preview": "mcp:preview",
                    "manual_validation_preview": "mcp:preview",
                    "scope_mismatch_preview": "mcp:preview",
                    "state_lineage_reconciliation_preview": "mcp:preview",
                    "final_version_closeout_preview": "mcp:preview",
                    "reconcile_orphaned_claims_preview": "mcp:preview",
                    "run_once": "mcp:commit",
                    "run_bounded": "mcp:commit",
                    "refresh_audit_package": "mcp:commit",
                    "recheck_report_apply": "mcp:commit",
                    "manual_fix_prompt_apply": "mcp:commit",
                    "manual_validation_apply": "mcp:commit",
                    "scope_mismatch_apply": "mcp:commit",
                    "state_lineage_reconciliation_apply": "mcp:commit",
                    "final_version_closeout_apply": "mcp:commit",
                    "reconcile_orphaned_claims_apply": "mcp:commit",
                },
            ),
            "manage_validation_run": _action_policy(
                "manage_validation_run",
                {"inspect": "mcp:read", "status": "mcp:read", "preview": "mcp:preview", "run": "mcp:commit"},
            ),
        }
    )
    stage_action_scopes = {"status": "mcp:read", "preview": "mcp:preview", "discard": "mcp:preview", "apply": "mcp:commit"}
    for name in (
        "manage_stage_parallel_worktrees",
        "manage_stage_parallel_shard_inputs",
        "manage_stage_parallel_executor_group",
        "manage_stage_parallel_executor_runs",
        "manage_stage_parallel_merges",
    ):
        policies[name] = _action_policy(name, stage_action_scopes)
    policies["manage_files"] = MCPToolPolicy(name="manage_files", selector="manage_files", requires_confirmation=True)
    policies["run_mcp_workflow"] = MCPToolPolicy(
        name="run_mcp_workflow",
        selector="run_mcp_workflow",
        side_effects=True,
        requires_confirmation=True,
        remote_public_allowed=False,
    )
    return policies


MCP_TOOL_POLICIES = _build_mcp_tool_policies()


@dataclass
class MCPToolInputError(Exception):
    error_code: str
    message: str
    details: dict[str, Any] | None = None


class MCPPlanningBridgeServer:
    def __init__(self, project_path: str, *, service_mode: bool = False):
        self.project_root = os.path.abspath(os.path.expanduser(project_path))
        self.service_mode = service_mode
        self.project_registry = ProjectRegistry()
        self.mcp_exposure_profile = self._get_exposure_profile()
        self.bridge = PlanningBridge()
        self.source_review = SourceReviewBridge()
        if self.service_mode:
            self.project_identity = {"service": "colameta-mcp", "routing": "registry"}
            self.project_hint = "ColaMeta Service"
        else:
            self.project_identity = build_project_identity(self.project_root)
            self.project_hint = self.project_identity.get("mcp_display_hint", f"Project:{os.path.basename(self.project_root)}")
        common_output_schema = self._build_common_output_schema()
        commander_app_input_schema = self._commander_app_input_schema()
        full_loop_authority_input_schema = self._full_loop_authority_input_schema()
        release_submission_input_schema = self._release_submission_input_schema()
        submission_evidence_fill_preview_input_schema = self._submission_evidence_fill_preview_input_schema()
        submission_evidence_auto_draft_input_schema = self._submission_evidence_auto_draft_input_schema()
        init_submission_evidence_input_schema = self._init_submission_evidence_input_schema()
        fill_submission_evidence_input_schema = self._fill_submission_evidence_input_schema()
        mark_submission_evidence_ready_input_schema = self._mark_submission_evidence_ready_input_schema()
        product_console_action_result_input_schema = self._product_console_action_result_input_schema()
        self.tools = {
            "list_registered_projects": self._tool_list_registered_projects,
            "get_agent_consumer_contract": self._tool_get_agent_consumer_contract,
            "get_service_entry_profile": self._tool_get_service_entry_profile,
            "get_agent_operator_flow_packet": self._tool_get_agent_operator_flow_packet,
            "get_web_gpt_service_entrypoint": self._tool_get_web_gpt_service_entrypoint,
            "get_product_readiness_status": self._tool_get_product_readiness_status,
            "get_chatgpt_app_readiness": self._tool_get_chatgpt_app_readiness,
            "get_full_loop_authority_status": self._tool_get_full_loop_authority_status,
            "get_product_console_map": self._tool_get_product_console_map,
            "get_release_submission_readiness": self._tool_get_release_submission_readiness,
            "get_submission_evidence_fill_preview": self._tool_get_submission_evidence_fill_preview,
            "get_submission_evidence_auto_draft": self._tool_get_submission_evidence_auto_draft,
            "init_submission_evidence": self._tool_init_submission_evidence,
            "fill_submission_evidence_files": self._tool_fill_submission_evidence_files,
            "mark_submission_evidence_ready_fields": self._tool_mark_submission_evidence_ready_fields,
            "record_product_console_action_result": self._tool_record_product_console_action_result,
            "get_commander_app_manifest": self._tool_get_commander_app_manifest,
            "render_commander_app": self._tool_render_commander_app,
            "get_apps_connector_smoke_packet": self._tool_get_apps_connector_smoke_packet,
            "get_stable_replacement_cadence": self._tool_get_stable_replacement_cadence,
            "get_stable_promotion_readiness": self._tool_get_stable_promotion_readiness,
            "get_stage_parallel_plan_preview": self._tool_get_stage_parallel_plan_preview,
            "get_stage_parallel_run_preview": self._tool_get_stage_parallel_run_preview,
            "get_stage_parallel_worktree_assignment_preview": self._tool_get_stage_parallel_worktree_assignment_preview,
            "get_stage_parallel_next_action_packet": self._tool_get_stage_parallel_next_action_packet,
            "get_stage_parallel_executor_group_preview": self._tool_get_stage_parallel_executor_group_preview,
            "get_stage_parallel_executor_results_packet": self._tool_get_stage_parallel_executor_results_packet,
            "get_stage_parallel_group_status": self._tool_get_stage_parallel_group_status,
            "get_stage_parallel_merge_preview": self._tool_get_stage_parallel_merge_preview,
            "get_stage_parallel_closeout_packet": self._tool_get_stage_parallel_closeout_packet,
            "get_runtime_version_status": self._tool_get_runtime_version_status,
            "get_connector_runtime_health_status": self._tool_get_connector_runtime_health_status,
            "get_runner_status": self._tool_get_runner_status,
            "get_version_result": self._tool_get_version_result,
            "get_next_version_plan": self._tool_get_next_version_plan,
            "get_plan_overview": self._tool_get_plan_overview,
            "get_review_context": self._tool_get_review_context,
            "get_runner_workbench_context": self._tool_get_runner_workbench_context,
            "get_project_doc_section": self._tool_get_project_doc_section,
            "preview_insert_version": self._tool_preview_insert_version,
            "preview_update_version": self._tool_preview_update_version,
            "get_plan_patch_status": self._tool_get_plan_patch_status,
            "get_repo_overview": self._tool_get_repo_overview,
            "get_git_status": self._tool_get_git_status,
            "get_git_log": self._tool_get_git_log,
            "manage_files": self._tool_manage_files,
            "get_source_file": self._tool_get_source_file,
            "search_source": self._tool_search_source,
            "get_git_diff": self._tool_get_git_diff,
            "get_executor_inventory": self._tool_get_executor_inventory,
            "get_project_identity": self._tool_get_project_identity,
            "get_runner_execution_standards": self._tool_get_runner_execution_standards,
            "get_plan_standards_report": self._tool_get_plan_standards_report,
            "get_executor_session_status": self._tool_get_executor_session_status,
            "get_executor_continuation_preview": self._tool_get_executor_continuation_preview,
            "get_executor_continuation_decision": self._tool_get_executor_continuation_decision,
            "get_executor_resume_invocation_preview": self._tool_get_executor_resume_invocation_preview,
            "manage_git": self._tool_manage_git,
            "manage_git_commit": self._tool_manage_git_commit,
            "manage_git_remote": self._tool_manage_git_remote,
            "manage_runner_plan": self._tool_manage_runner_plan,
            "manage_runner_record": self._tool_manage_runner_record,
            "manage_project_memory": self._tool_manage_project_memory,
            "manage_workflow_run": self._tool_manage_workflow_run,
            "todo_read": self._tool_todo_read,
            "todo_add": self._tool_todo_add,
            "todo_update": self._tool_todo_update,
            "todo_delete": self._tool_todo_delete,
            "decision_read": self._tool_decision_read,
            "decision_add": self._tool_decision_add,
            "decision_update": self._tool_decision_update,
            "decision_delete": self._tool_decision_delete,
            "list_executor_run_reports": self._tool_list_executor_run_reports,
            "get_executor_run_report": self._tool_get_executor_run_report,
            "analyze_project_state": self._tool_analyze_project_state,
            "manage_plan_version": self._tool_manage_plan_version,
            "manage_project_patch": self._tool_manage_project_patch,
            "manage_git_history": self._tool_manage_git_history,
            "manage_plan_workflow": self._tool_manage_plan_workflow,
            "manage_project_docs": self._tool_manage_project_docs,
            "manage_prompt_file": self._tool_manage_prompt_file,
            "run_mcp_workflow": self._tool_run_mcp_workflow,
            "manage_executor_config": self._tool_manage_executor_config,
            "inspect_executor_activity": self._tool_inspect_executor_activity,
            "manage_executor_workflow": self._tool_manage_executor_workflow,
            "manage_validation_run": self._tool_manage_validation_run,
            "manage_stage_parallel_worktrees": self._tool_manage_stage_parallel_worktrees,
            "manage_stage_parallel_shard_inputs": self._tool_manage_stage_parallel_shard_inputs,
            "manage_stage_parallel_executor_group": self._tool_manage_stage_parallel_executor_group,
            "manage_stage_parallel_executor_runs": self._tool_manage_stage_parallel_executor_runs,
            "manage_stage_parallel_merges": self._tool_manage_stage_parallel_merges,
            "list_workflow_runs": self._tool_list_workflow_runs,
            "get_workflow_run": self._tool_get_workflow_run,
        }
        self.tool_defs = [
            MCPToolDef(
                name="list_registered_projects",
                description=f"[{self.project_hint}] 列出本地 registry 中已登记项目。只接受本地 allowlist 项目，不解析任意 project_root。",
                input_schema={
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
            ),
            MCPToolDef(
                name="get_agent_consumer_contract",
                description=(
                    f"[{self.project_hint}] 读取 Agent 消费者契约。"
                    "说明 MCP tool 成功/失败 envelope、project_name 路由规则、只读/副作用字段、packaged 大结果和权限边界。scope=mcp:read。"
                ),
                input_schema={
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
            ),
            MCPToolDef(
                name="get_service_entry_profile",
                description=(
                    f"[{self.project_hint}] 按 profile_id 读取服务入口画像。"
                    "用于网页 GPT、本地 Codex、Reviewer、Planner、Source Observer 等 agent 选择自己的最小进入路径。scope=mcp:read。"
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "profile_id": {
                            "type": "string",
                            "description": "可选。为空时返回默认 web_gpt_commander 和可选 profile 列表。",
                        }
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
            ),
            MCPToolDef(
                name="get_agent_operator_flow_packet",
                title="Get Agent Operator Flow Packet",
                description=(
                    f"[{self.project_hint}] 面向任意 agent profile 的只读操作流程 packet。"
                    "按 profile_id、task_mode 和当前项目事实给出一个 primary_next_action、简短原因、gate level 和 advanced context。"
                    "它不创建 preview artifact、不启动 executor、不 merge、不 commit、不 push、不替换 stable。scope=mcp:read。"
                ),
                input_schema=self._agent_operator_flow_input_schema(),
                output_schema=common_output_schema,
                annotations={
                    "readOnlyHint": True,
                    "destructiveHint": False,
                    "openWorldHint": False,
                    "idempotentHint": True,
                },
            ),
            MCPToolDef(
                name="get_web_gpt_service_entrypoint",
                description=(
                    f"[{self.project_hint}] 网页端 GPT 使用 ColaMeta 服务的只读入口卡片。"
                    "返回推荐首调用顺序、project_name 路由规则、薄治理闭环 draft/provided 用法、权限边界和稳定晋升注意事项。scope=mcp:read。"
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "project_name": {
                            "type": "string",
                            "description": "可选。若已知目标项目，可返回该项目的只读 identity 摘要；服务模式下仍不执行项目动作。",
                        }
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
            ),
            MCPToolDef(
                name="get_commander_app_manifest",
                title="Get Commander App Manifest",
                description=(
                    f"[{self.project_hint}] ChatGPT Apps 侧 ColaMeta Commander App 的只读 manifest。"
                    "汇总项目身份、runtime、connector health、profile-aware 入口、preview-first 工作流和授权闸门。"
                    "只接受 sanitized tunnel/control-plane evidence；不读取 token、cookie、配置或 raw logs。scope=mcp:read。"
                ),
                input_schema=commander_app_input_schema,
                output_schema=common_output_schema,
                annotations={
                    "readOnlyHint": True,
                    "destructiveHint": False,
                    "openWorldHint": False,
                    "idempotentHint": True,
                },
            ),
            MCPToolDef(
                name="get_product_readiness_status",
                title="Get Product Readiness Status",
                description=(
                    f"[{self.project_hint}] ColaMeta 作为公开 Beta 产品入口的只读 readiness packet。"
                    "聚合 ops-check、stable runtime、remote preflight、cloudflared 和 Apps connector smoke 状态，"
                    "输出 primary_blocker 和 safe_next_action；不重启服务、不修改 DNS/tunnel、不授权 executor run、commit、push 或 stable replacement。scope=mcp:read。"
                ),
                input_schema=commander_app_input_schema,
                output_schema=common_output_schema,
                annotations={
                    "readOnlyHint": True,
                    "destructiveHint": False,
                    "openWorldHint": False,
                    "idempotentHint": True,
                },
            ),
            MCPToolDef(
                name="get_chatgpt_app_readiness",
                title="Get ChatGPT App Readiness",
                description=(
                    f"[{self.project_hint}] ChatGPT App 连接前的只读产品 readiness 和推荐工具顺序。"
                    "返回 connector URL、recommended_sequence 和 readiness 摘要；只作为外部 connector closeout 证据，不授权写入或服务替换。scope=mcp:read。"
                ),
                input_schema=commander_app_input_schema,
                output_schema=common_output_schema,
                annotations={
                    "readOnlyHint": True,
                    "destructiveHint": False,
                    "openWorldHint": False,
                    "idempotentHint": True,
                },
            ),
            MCPToolDef(
                name="get_full_loop_authority_status",
                title="Get Full Loop Authority Status",
                description=(
                    f"[{self.project_hint}] Controlled Full Loop 的只读授权状态面。"
                    "默认 disabled/read-preview-only；即使显式请求完整闭环，也只验证 preview-confirm、operator confirmation ref "
                    "和 executor/validation/commit/push gate 是否齐备，不启动 executor、不跑验证、不 commit、不 push、不替换 stable。scope=mcp:read。"
                ),
                input_schema=full_loop_authority_input_schema,
                output_schema=common_output_schema,
                annotations={
                    "readOnlyHint": True,
                    "destructiveHint": False,
                    "openWorldHint": False,
                    "idempotentHint": True,
                },
            ),
            MCPToolDef(
                name="get_product_console_map",
                title="Get Product Console Map",
                description=(
                    f"[{self.project_hint}] ColaMeta 项目操作台的只读能力地图。"
                    "返回连接/readiness、计划审查、Controlled Full Loop、stable/release 的入口、工具、scope、状态和推荐首动作；"
                    "不启动 executor、不跑验证、不 commit、不 push、不替换 stable、不发布。scope=mcp:read。"
                ),
                input_schema=commander_app_input_schema,
                output_schema=common_output_schema,
                annotations={
                    "readOnlyHint": True,
                    "destructiveHint": False,
                    "openWorldHint": False,
                    "idempotentHint": True,
                },
            ),
            MCPToolDef(
                name="get_release_submission_readiness",
                title="Get Release Submission Readiness",
                description=(
                    f"[{self.project_hint}] ChatGPT App release/submission 的只读准备状态。"
                    "检查 public MCP/readiness、Apps connector smoke、提交表单材料、测试证据、权限声明、隐私安全和 metadata snapshot；"
                    "不创建 OpenAI app draft、不提交 review、不发布、不读取 token/cookie/provider config。scope=mcp:read。"
                ),
                input_schema=release_submission_input_schema,
                output_schema=common_output_schema,
                annotations={
                    "readOnlyHint": True,
                    "destructiveHint": False,
                    "openWorldHint": False,
                    "idempotentHint": True,
                },
            ),
            MCPToolDef(
                name="get_submission_evidence_fill_preview",
                title="Get Submission Evidence Fill Preview",
                description=(
                    f"[{self.project_hint}] 只读生成 ChatGPT App submission evidence 填写 payload 预览。"
                    "从当前 release/submission evidence bundle 生成 fill_submission_evidence_files 的 copyable arguments；"
                    "不写文件、不标 ready、不创建 OpenAI app draft、不提交 review、不发布。scope=mcp:read。"
                ),
                input_schema=submission_evidence_fill_preview_input_schema,
                output_schema=common_output_schema,
                annotations={
                    "readOnlyHint": True,
                    "destructiveHint": False,
                    "openWorldHint": False,
                    "idempotentHint": True,
                },
            ),
            MCPToolDef(
                name="get_submission_evidence_auto_draft",
                title="Get Submission Evidence Auto Draft",
                description=(
                    f"[{self.project_hint}] 只读生成可由当前 MCP/Commander 事实预填的 submission evidence 草稿。"
                    "覆盖 mcp_tool_info、security_review、metadata_snapshot；返回 fill_submission_evidence_files 的 copyable arguments；"
                    "不写文件、不标 ready、不创建 OpenAI app draft、不提交 review、不发布。scope=mcp:read。"
                ),
                input_schema=submission_evidence_auto_draft_input_schema,
                output_schema=common_output_schema,
                annotations={
                    "readOnlyHint": True,
                    "destructiveHint": False,
                    "openWorldHint": False,
                    "idempotentHint": True,
                },
            ),
            MCPToolDef(
                name="init_submission_evidence",
                title="Initialize Submission Evidence",
                description=(
                    f"[{self.project_hint}] 初始化 ChatGPT App release/submission 的本地 evidence scaffold。"
                    "创建 docs/chatgpt-app-submission-materials.json 和 docs/submission/*.todo.md 占位文件；"
                    "不覆盖已有文件、不提交 OpenAI review、不发布、不读取 token/cookie/provider config。scope=mcp:commit。"
                ),
                input_schema=init_submission_evidence_input_schema,
                output_schema=common_output_schema,
                annotations={
                    "readOnlyHint": False,
                    "destructiveHint": False,
                    "openWorldHint": False,
                    "idempotentHint": True,
                },
            ),
            MCPToolDef(
                name="fill_submission_evidence_files",
                title="Fill Submission Evidence Files",
                description=(
                    f"[{self.project_hint}] 写入操作者提供的 ChatGPT App submission evidence 文本。"
                    "仅创建 docs/submission/*.md，更新 docs/chatgpt-app-submission-materials.json 的 evidence 引用；"
                    "默认不标 ready，不覆盖已有真实文件，不读取 token/cookie/provider config。scope=mcp:commit。"
                ),
                input_schema=fill_submission_evidence_input_schema,
                output_schema=common_output_schema,
                annotations={
                    "readOnlyHint": False,
                    "destructiveHint": False,
                    "openWorldHint": False,
                    "idempotentHint": True,
                },
            ),
            MCPToolDef(
                name="mark_submission_evidence_ready_fields",
                title="Mark Submission Evidence Ready Fields",
                description=(
                    f"[{self.project_hint}] 在人工审查后标记 ChatGPT App submission evidence ready 字段。"
                    "只更新 docs/chatgpt-app-submission-materials.json 中已存在、非 .todo evidence 对应的 ready flag；"
                    "要求 review_confirmation=human_reviewed；不写 evidence 正文、不提交 OpenAI review、不发布。scope=mcp:commit。"
                ),
                input_schema=mark_submission_evidence_ready_input_schema,
                output_schema=common_output_schema,
                annotations={
                    "readOnlyHint": False,
                    "destructiveHint": False,
                    "openWorldHint": False,
                    "idempotentHint": True,
                },
            ),
            MCPToolDef(
                name="record_product_console_action_result",
                title="Record Product Console Action Result",
                description=(
                    f"[{self.project_hint}] 记录 Product Console 推荐动作的短结果摘要，供后续 console map 和 Commander 卡片读取。"
                    "只写 .colameta/runtime/product-console-action-results.json；不保存 raw tool output、不执行动作、"
                    "不提交 OpenAI review、不发布、不替换 stable。scope=mcp:commit。"
                ),
                input_schema=product_console_action_result_input_schema,
                output_schema=common_output_schema,
                annotations={
                    "readOnlyHint": False,
                    "destructiveHint": False,
                    "openWorldHint": False,
                    "idempotentHint": True,
                },
            ),
            MCPToolDef(
                name="render_commander_app",
                title="Render Commander App",
                description=(
                    f"[{self.project_hint}] 渲染 ChatGPT Apps iframe 版 ColaMeta Commander 面板。"
                    "返回 Commander manifest，并通过 MCP Apps resource URI 绑定 widget。"
                    "面板只展示事实、只读调用和 preview-first 入口；不授权 executor run、commit、push 或 stable replacement。scope=mcp:read。"
                ),
                input_schema=commander_app_input_schema,
                output_schema=common_output_schema,
                annotations={
                    "readOnlyHint": True,
                    "destructiveHint": False,
                    "openWorldHint": False,
                    "idempotentHint": True,
                },
                meta={
                    "ui": {
                        "resourceUri": COMMANDER_APP_WIDGET_URI,
                        "visibility": ["model", "app"],
                    },
                    "openai/outputTemplate": COMMANDER_APP_WIDGET_URI,
                    "openai/toolInvocation/invoking": "Opening ColaMeta Commander",
                    "openai/toolInvocation/invoked": "ColaMeta Commander ready",
                },
            ),
            MCPToolDef(
                name="get_apps_connector_smoke_packet",
                title="Get Apps Connector Smoke Packet",
                description=(
                    f"[{self.project_hint}] ChatGPT Apps connector 只读 smoke packet。"
                    "返回 list_registered_projects 检查、connector closeout 调用、token_expired 处理边界和稳定替换 drift 提示。"
                    "只接受 sanitized tunnel/control-plane evidence；不读取 token、cookie、browser login state、配置或 raw logs。scope=mcp:read。"
                ),
                input_schema=commander_app_input_schema,
                output_schema=common_output_schema,
                annotations={
                    "readOnlyHint": True,
                    "destructiveHint": False,
                    "openWorldHint": False,
                    "idempotentHint": True,
                },
            ),
            MCPToolDef(
                name="get_stable_replacement_cadence",
                title="Get Stable Replacement Cadence",
                description=(
                    f"[{self.project_hint}] 稳定服务替换节奏只读卡片。"
                    "当 dev HEAD 与 stable HEAD 不一致时，默认返回 dev_ahead_stable、"
                    "stable_replacement_not_required 和 batch_when_ready；"
                    "不把普通产品化 drift 升级成替换授权请求。scope=mcp:read。"
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "project_name": {
                            "type": "string",
                            "description": "可选。按已登记 project_name 路由读取目标项目的 stable replacement cadence；服务模式下必须显式提供。",
                        }
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
                annotations={
                    "readOnlyHint": True,
                    "destructiveHint": False,
                    "openWorldHint": False,
                    "idempotentHint": True,
                },
            ),
            MCPToolDef(
                name="get_stable_promotion_readiness",
                description=(
                    f"[{self.project_hint}] 稳定服务晋升只读预检卡片。"
                    "汇总运行中代码新鲜度、Git clean、MCP 入口能力、registry、稳定运行目录来源和晋升阻断项。"
                    "它只输出 evidence，不授权重启、替换稳定服务、push、executor run、route transition、release 或 deploy。scope=mcp:read。"
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "project_name": {
                            "type": "string",
                            "description": "可选。按已登记 project_name 路由读取目标项目稳定晋升预检；服务模式下必须显式提供。",
                        }
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
            ),
            MCPToolDef(
                name="get_stage_parallel_plan_preview",
                title="Get Stage Parallel Plan Preview",
                description=(
                    f"[{self.project_hint}] 阶段并行自动化只读规划卡片。"
                    "把 stage 或 task_intents 拆成候选 task_shards，标出 allowed_files overlap、surface、风险和下一步。"
                    "它不创建 executor preview、不启动 executor、不创建 branch/worktree、不 merge、不 commit、不 push、不替换 stable。scope=mcp:read。"
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "project_name": {
                            "type": "string",
                            "description": "可选。按已登记 project_name 路由读取目标项目；服务模式下必须显式提供。",
                        },
                        "stage_id": {
                            "type": "string",
                            "description": "可选。要规划的阶段 ID；不传时使用 stage_parallel_automation。",
                        },
                        "max_parallel_tasks": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 8,
                            "description": "可选。最多纳入多少个候选 task shard。默认 3，最大 8。",
                        },
                        "task_intents": {
                            "type": "array",
                            "description": "可选。候选任务意图；只用于只读拆分预览。",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "task_id": {"type": "string"},
                                    "title": {"type": "string"},
                                    "description": {"type": "string"},
                                    "allowed_files": {"type": "array", "items": {"type": "string"}},
                                    "surfaces": {"type": "array", "items": {"type": "string"}},
                                    "risk_level": {
                                        "type": "string",
                                        "enum": ["none", "low", "moderate", "high", "blocked"],
                                    },
                                },
                                "required": ["title"],
                            },
                        },
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
                annotations={
                    "readOnlyHint": True,
                    "destructiveHint": False,
                    "openWorldHint": False,
                    "idempotentHint": True,
                },
            ),
            MCPToolDef(
                name="get_stage_parallel_run_preview",
                title="Get Stage Parallel Run Preview",
                description=(
                    f"[{self.project_hint}] 阶段并行运行只读预览卡片。"
                    "基于 stage/task_intents 输出 parallel_group_id、每个 shard 的隔离 worktree/branch 建议和未来 executor preview request。"
                    "它不创建 executor preview、不启动 executor、不创建 branch/worktree、不 merge、不 commit、不 push、不替换 stable。scope=mcp:read。"
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "project_name": {
                            "type": "string",
                            "description": "可选。按已登记 project_name 路由读取目标项目；服务模式下必须显式提供。",
                        },
                        "stage_id": {
                            "type": "string",
                            "description": "可选。要规划的阶段 ID；不传时使用 stage_parallel_automation。",
                        },
                        "provider": {
                            "type": "string",
                            "enum": ["codex", "opencode", "pi"],
                            "description": "可选。未来 executor preview 的 provider 偏好。默认 codex。",
                        },
                        "base_branch": {
                            "type": "string",
                            "description": "可选。未来隔离 worktree 的基准分支名。默认 main。",
                        },
                        "max_parallel_tasks": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 8,
                            "description": "可选。最多纳入多少个候选 task shard。默认 3，最大 8。",
                        },
                        "task_intents": {
                            "type": "array",
                            "description": "可选。候选任务意图；只用于只读运行预览。",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "task_id": {"type": "string"},
                                    "title": {"type": "string"},
                                    "description": {"type": "string"},
                                    "allowed_files": {"type": "array", "items": {"type": "string"}},
                                    "surfaces": {"type": "array", "items": {"type": "string"}},
                                    "risk_level": {
                                        "type": "string",
                                        "enum": ["none", "low", "moderate", "high", "blocked"],
                                    },
                                },
                                "required": ["title"],
                            },
                        },
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
                annotations={
                    "readOnlyHint": True,
                    "destructiveHint": False,
                    "openWorldHint": False,
                    "idempotentHint": True,
                },
            ),
            MCPToolDef(
                name="get_stage_parallel_worktree_assignment_preview",
                title="Get Stage Parallel Worktree Assignment Preview",
                description=(
                    f"[{self.project_hint}] 阶段并行 worktree 分配只读预览卡片。"
                    "检查每个 shard 的 deterministic worktree path 和 branch name 是否可分配。"
                    "它不创建 branch/worktree、不创建 executor preview、不启动 executor、不 merge、不 commit、不 push、不替换 stable。scope=mcp:read。"
                ),
                input_schema=_stage_parallel_preview_input_schema(),
                output_schema=common_output_schema,
                annotations={
                    "readOnlyHint": True,
                    "destructiveHint": False,
                    "openWorldHint": False,
                    "idempotentHint": True,
                },
            ),
            MCPToolDef(
                name="get_stage_parallel_next_action_packet",
                title="Get Stage Parallel Next Action Packet",
                description=(
                    f"[{self.project_hint}] 阶段并行下一步只读 packet。"
                    "根据当前 worktree、shard input、executor preview、run claim/report metadata 给出唯一 recommended next tool。"
                    "它不创建 preview artifact、不写 shard input、不启动 executor、不 merge、不 commit、不 push、不替换 stable。scope=mcp:read。"
                ),
                input_schema=_stage_parallel_preview_input_schema(),
                output_schema=common_output_schema,
                annotations={
                    "readOnlyHint": True,
                    "destructiveHint": False,
                    "openWorldHint": False,
                    "idempotentHint": True,
                },
            ),
            MCPToolDef(
                name="get_stage_parallel_executor_group_preview",
                title="Get Stage Parallel Executor Group Preview",
                description=(
                    f"[{self.project_hint}] 阶段并行 executor group 只读预览卡片。"
                    "基于 worktree assignment 预览每个 shard 的未来 executor preview request。"
                    "它不创建 executor preview、不启动 executor、不创建 branch/worktree、不 merge、不 commit、不 push、不替换 stable。scope=mcp:read。"
                ),
                input_schema=_stage_parallel_preview_input_schema(),
                output_schema=common_output_schema,
                annotations={
                    "readOnlyHint": True,
                    "destructiveHint": False,
                    "openWorldHint": False,
                    "idempotentHint": True,
                },
            ),
            MCPToolDef(
                name="get_stage_parallel_executor_results_packet",
                title="Get Stage Parallel Executor Results Packet",
                description=(
                    f"[{self.project_hint}] 阶段并行 executor results 只读 packet。"
                    "扫描隔离 worktree 的 structured preview/claim/report metadata，生成 sanitized executor_results。"
                    "它不读 raw logs、不启动 executor、不 merge、不 commit、不 push、不替换 stable。scope=mcp:read。"
                ),
                input_schema=_stage_parallel_preview_input_schema(),
                output_schema=common_output_schema,
                annotations={
                    "readOnlyHint": True,
                    "destructiveHint": False,
                    "openWorldHint": False,
                    "idempotentHint": True,
                },
            ),
            MCPToolDef(
                name="get_stage_parallel_group_status",
                title="Get Stage Parallel Group Status",
                description=(
                    f"[{self.project_hint}] 阶段并行 group status 只读卡片。"
                    "汇总 planned 或调用方提供的 sanitized executor result 摘要，判断是否 merge_ready。"
                    "它不读取 raw logs、不启动 executor、不 merge、不 commit、不 push、不替换 stable。scope=mcp:read。"
                ),
                input_schema=_stage_parallel_preview_input_schema(include_executor_results=True),
                output_schema=common_output_schema,
                annotations={
                    "readOnlyHint": True,
                    "destructiveHint": False,
                    "openWorldHint": False,
                    "idempotentHint": True,
                },
            ),
            MCPToolDef(
                name="get_stage_parallel_merge_preview",
                title="Get Stage Parallel Merge Preview",
                description=(
                    f"[{self.project_hint}] 阶段并行 merge 只读预览卡片。"
                    "当所有 shard succeeded 且 validation passed 时，生成 merge order 和验证命令预览。"
                    "它不执行 merge、不 commit、不 push、不替换 stable。scope=mcp:read。"
                ),
                input_schema=_stage_parallel_preview_input_schema(include_executor_results=True),
                output_schema=common_output_schema,
                annotations={
                    "readOnlyHint": True,
                    "destructiveHint": False,
                    "openWorldHint": False,
                    "idempotentHint": True,
                },
            ),
            MCPToolDef(
                name="get_stage_parallel_closeout_packet",
                title="Get Stage Parallel Closeout Packet",
                description=(
                    f"[{self.project_hint}] 阶段并行 closeout 只读 packet。"
                    "汇总 worktree assignment、executor group、group status 和 merge preview 的人审材料。"
                    "它不写 Delivery accepted、不创建 ReviewDecision/GateEvent、不 merge、不 commit、不 push、不替换 stable。scope=mcp:read。"
                ),
                input_schema=_stage_parallel_preview_input_schema(include_executor_results=True),
                output_schema=common_output_schema,
                annotations={
                    "readOnlyHint": True,
                    "destructiveHint": False,
                    "openWorldHint": False,
                    "idempotentHint": True,
                },
            ),
            MCPToolDef(
                name="manage_stage_parallel_worktrees",
                title="Manage Stage Parallel Worktrees",
                description=(
                    f"[{self.project_hint}] 阶段并行隔离 git worktree 受控工具。"
                    "preview 会生成 preview_id 并校验 base HEAD、dirty state、worktree path 和 branch；"
                    "apply 只使用 preview_id 创建隔离 worktree。"
                    "它不启动 executor、不创建 executor preview、不 merge、不 commit、不 push、不替换 stable。"
                    "scope：status=mcp:read，preview/discard=mcp:preview，apply=mcp:commit。"
                ),
                input_schema=_manage_stage_parallel_worktrees_input_schema(),
                output_schema=common_output_schema,
                annotations={
                    "readOnlyHint": False,
                    "destructiveHint": False,
                    "openWorldHint": False,
                    "idempotentHint": False,
                },
            ),
            MCPToolDef(
                name="manage_stage_parallel_shard_inputs",
                title="Manage Stage Parallel Shard Inputs",
                description=(
                    f"[{self.project_hint}] 阶段并行 shard runner input 受控工具。"
                    "preview 会校验每个 isolated worktree 已存在、branch/head 匹配且干净；"
                    "apply 只在每个 worktree 的 .colameta/runtime 内写入 shard-specific plan/state/prompt overlay。"
                    "它不创建 executor preview、不启动 executor、不 merge、不 commit、不 push、不替换 stable。"
                    "scope：status=mcp:read，preview/discard=mcp:preview，apply=mcp:commit。"
                ),
                input_schema=_manage_stage_parallel_shard_inputs_input_schema(),
                output_schema=common_output_schema,
                annotations={
                    "readOnlyHint": False,
                    "destructiveHint": False,
                    "openWorldHint": False,
                    "idempotentHint": False,
                },
            ),
            MCPToolDef(
                name="manage_stage_parallel_executor_group",
                title="Manage Stage Parallel Executor Group",
                description=(
                    f"[{self.project_hint}] 阶段并行 executor preview group 受控工具。"
                    "preview 会校验每个 isolated worktree 已存在、branch/head 匹配且 executor preflight 可通过；"
                    "apply 只在每个 worktree 内创建 manage_executor_workflow run_once_preview artifact。"
                    "它不启动 executor、不 merge、不 commit、不 push、不替换 stable。"
                    "scope：status=mcp:read，preview/discard=mcp:preview，apply=mcp:commit。"
                ),
                input_schema=_manage_stage_parallel_executor_group_input_schema(),
                output_schema=common_output_schema,
                annotations={
                    "readOnlyHint": False,
                    "destructiveHint": False,
                    "openWorldHint": False,
                    "idempotentHint": False,
                },
            ),
            MCPToolDef(
                name="manage_stage_parallel_executor_runs",
                title="Manage Stage Parallel Executor Runs",
                description=(
                    f"[{self.project_hint}] 阶段并行 executor run group 受控工具。"
                    "preview 会校验每个 isolated worktree 已有未消费、未过期且匹配当前 branch/head/provider 的 run_once_preview；"
                    "apply 使用 preview_id 启动每个 worktree 内的 manage_executor_workflow run_once。"
                    "它不 merge、不 commit main、不 push、不替换 stable。"
                    "scope：status=mcp:read，preview/discard=mcp:preview，apply=mcp:commit。"
                ),
                input_schema=_manage_stage_parallel_executor_runs_input_schema(),
                output_schema=common_output_schema,
                annotations={
                    "readOnlyHint": False,
                    "destructiveHint": False,
                    "openWorldHint": False,
                    "idempotentHint": False,
                },
            ),
            MCPToolDef(
                name="manage_stage_parallel_merges",
                title="Manage Stage Parallel Merges",
                description=(
                    f"[{self.project_hint}] 阶段并行 merge 受控工具。"
                    "preview 会校验 sanitized executor_results、target branch/head、source branch/head 和 clean target worktree；"
                    "apply 使用 preview_id 顺序执行本地 git merge --no-ff。"
                    "它不 push、不替换 stable、不写 Delivery accepted、不创建 ReviewDecision/GateEvent。"
                    "scope：status=mcp:read，preview/discard=mcp:preview，apply=mcp:commit。"
                ),
                input_schema=_manage_stage_parallel_merges_input_schema(),
                output_schema=common_output_schema,
                annotations={
                    "readOnlyHint": False,
                    "destructiveHint": False,
                    "openWorldHint": False,
                    "idempotentHint": False,
                },
            ),
            MCPToolDef(
                name="get_project_identity",
                description=f"[{self.project_hint}] 读取当前 MCP 绑定项目的身份标识，可用于在多项目 MCP 间确认上下文。",
                input_schema={
                    "type": "object",
                    "properties": {
                        "project_name": {
                            "type": "string",
                            "description": "可选。按已登记 project_name 路由读取目标项目身份。",
                        }
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
            ),
            MCPToolDef(
                name="get_runtime_version_status",
                description=f"[{self.project_hint}] Read-only runtime/version metadata for the running ColaMeta process and current project checkout. Reports process start time, loaded runtime HEAD, current checkout HEAD, branch/project root, and whether restart/reload appears needed. This tool never restarts, reloads, kills, applies, fetches, pulls, pushes, tags, or releases.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "project_name": {
                            "type": "string",
                            "description": "可选。按已登记 project_name 路由读取目标项目 checkout HEAD；服务模式下必须显式提供。",
                        }
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
            ),
            MCPToolDef(
                name="get_connector_runtime_health_status",
                description=(
                    f"[{self.project_hint}] Read-only connector/runtime closeout card. "
                    "Combines runtime freshness, local Web/MCP service evidence, and optional sanitized tunnel_client/control_plane status. "
                    "It does not read tunnel/proxy/provider config, secrets, tokens, cookies, logs, private memory, or raw provider responses, "
                    "and it does not modify service/network state."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "project_name": {
                            "type": "string",
                            "description": "可选。按已登记 project_name 路由读取目标项目；服务模式下必须显式提供。",
                        },
                        "tunnel_client": {
                            "type": "object",
                            "description": "可选。调用方提供的 sanitized tunnel-client 状态，只采信 status/reason_code/evidence_source/last_observed_at。",
                            "properties": {
                                "status": {"type": "string"},
                                "reason_code": {"type": "string"},
                                "evidence_source": {"type": "string"},
                                "last_observed_at": {"type": "string"},
                            },
                            "additionalProperties": False,
                        },
                        "control_plane": {
                            "type": "object",
                            "description": "可选。调用方提供的 sanitized tunnel control-plane 状态，只采信 status/reason_code/evidence_source/last_observed_at。",
                            "properties": {
                                "status": {"type": "string"},
                                "reason_code": {"type": "string"},
                                "evidence_source": {"type": "string"},
                                "last_observed_at": {"type": "string"},
                            },
                            "additionalProperties": False,
                        },
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
            ),
            MCPToolDef(
                name="get_plan_standards_report",
                description="Read a structured lint report for the current Runner plan before generating or updating plan patches. If blocking_issue_count > 0, do not call preview_insert_version or preview_update_version except to fix those plan issues.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "project_name": {
                            "type": "string",
                            "description": "可选。按已登记 managed project_name 路由读取目标项目 plan 标准报告。",
                        },
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
            ),
            MCPToolDef(
                name="get_runner_execution_standards",
                description="Read Runner execution standards before generating initial plans, plan.json, plan patches, prompts, fix prompts, diff reviews, or low-cost executor instructions. Includes bootstrap_plan, strict plan_format, and acceptance_commands rules.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "section": {
                            "type": "string",
                            "description": "Optional section name (bootstrap_plan, plan_format, version_prompt, fix_prompt, plan_patch, diff_review, execution_branch, commit_review, low_cost_executor, executor_selection_strategy). Defaults to all.",
                        }
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
            ),
            MCPToolDef(
                name="get_runner_status",
                description=f"[{self.project_hint}] 读取 Runner 当前状态",
                input_schema={
                    "type": "object",
                    "properties": {
                        "project_name": {
                            "type": "string",
                            "description": "可选。按已登记 project_name 路由读取目标项目状态。",
                        }
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
            ),
            MCPToolDef(
                name="get_executor_session_status",
                description="Read the current project-scoped executor session manifest. This is read-only and does not resume, reset, or modify executor sessions.",
                input_schema={
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
            ),
            MCPToolDef(
                name="get_executor_continuation_preview",
                description="Read a read-only continuation preview for the current project executor session. This does not resume, reset, modify files, or call any executor.",
                input_schema={
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
            ),
            MCPToolDef(
                name="get_executor_continuation_decision",
                description="Read a read-only continuation decision for the requested executor provider. This does not resume, reset, modify files, or call any executor.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "provider": {
                            "type": "string",
                            "enum": ["pi", "codex", "opencode"],
                            "description": "Executor provider to evaluate continuation decision.",
                        }
                    },
                    "required": ["provider"],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
            ),
            MCPToolDef(
                name="get_executor_resume_invocation_preview",
                description="Read a read-only provider-specific resume invocation preview for the requested executor provider. This does not resume, reset, modify files, or call any executor.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "provider": {
                            "type": "string",
                            "enum": ["pi", "codex", "opencode"],
                            "description": "Executor provider to inspect invocation preview.",
                        }
                    },
                    "required": ["provider"],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
            ),
            MCPToolDef(
                name="get_review_context",
                description=f"[{self.project_hint}] Read a bundled review context for validating recent changes before telling the user whether a version can be committed. This is read-only and never stages, resets, cleans, or commits.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "max_diff_chars": {
                            "type": "integer",
                            "description": "Maximum characters for git diff. Defaults to 60000 and is capped at 120000.",
                        },
                        "include_log": {
                            "type": "boolean",
                            "description": "Whether to include recent git log. Defaults to true.",
                        },
                        "log_limit": {
                            "type": "integer",
                            "description": "Recent commit count when include_log is true. Defaults to 5 and is capped at 20.",
                        },
                        "include_repo_overview": {
                            "type": "boolean",
                            "description": "Whether to include repo overview/file tree. Defaults to false.",
                        },
                        "max_files": {
                            "type": "integer",
                            "description": "Maximum file entries for repo overview when included. Defaults to 200 and is capped at 500.",
                        },
                        "project_name": {
                            "type": "string",
                            "description": "可选。按已登记 managed project_name 路由读取目标项目 review context。",
                        },
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
            ),
            MCPToolDef(
                name="get_runner_workbench_context",
                description=f"[{self.project_hint}] Read a bundled workbench context for quickly understanding Runner status, plan state, executor continuation, and git status. Partial failures are returned per section.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "include_runner_state": {
                            "type": "boolean",
                            "description": "Whether to include runner status, current version result, next plan, and plan overview. Defaults to true.",
                        },
                        "include_executor": {
                            "type": "boolean",
                            "description": "Whether to include executor session and continuation preview. Defaults to true.",
                        },
                        "include_git_status": {
                            "type": "boolean",
                            "description": "Whether to include git status. Defaults to true.",
                        },
                        "provider": {
                            "type": "string",
                            "enum": ["pi", "codex", "opencode"],
                            "description": "Optional provider for continuation decision and resume invocation preview.",
                        },
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
            ),
            MCPToolDef(
                name="manage_git",
                description=(
                    f"[{self.project_hint}] 统一 Git 工具。"
                    "通过 action 路由到受控 Git 子操作。"
                    "支持 project_name 路由到已登记 managed 项目。"
                    "此工具不会执行任意 Git 命令，不会绕过 preview 审批。"
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": [
                                "status",
                                "diff",
                                "review_context",
                                "commit_readiness",
                                "commit_message",
                                "commit_preview",
                                "commit_apply",
                                "push_status",
                                "push_preview",
                                "push_apply",
                                "pull_status",
                                "pull_preview",
                                "pull_apply",
                                "history_log",
                                "history_show",
                                "diff_commits",
                                "restore_file_preview",
                                "restore_file_apply",
                                "revert_preview",
                                "revert_apply",
                            ],
                            "description": "Git domain action. Routes to existing Git capability.",
                        },
                        "project_name": {
                            "type": "string",
                            "description": "可选。按已登记 managed project_name 路由目标项目。",
                        },
                        "preview_id": {
                            "type": "string",
                            "description": "apply 类 action 必填。来自对应 preview 的 preview_id。",
                        },
                        "message": {
                            "type": "string",
                            "description": "commit_preview/commit_apply 的提交信息。",
                        },
                        "commit": {
                            "type": "string",
                            "description": "history_show/restore_file_preview/revert_preview 的 commit ref。",
                        },
                        "base": {
                            "type": "string",
                            "description": "diff_commits 的基础 commit。",
                        },
                        "head": {
                            "type": "string",
                            "description": "diff_commits 的目标 commit。",
                        },
                        "file": {
                            "type": "string",
                            "description": "restore_file_preview/diff_commits 的文件路径。",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "history_log 返回 commit 数量。默认 12，最大 50。",
                        },
                        "max_chars": {
                            "type": "integer",
                            "description": "diff/history_show/diff_commits/revert_preview 的 diff 字符限制。默认 40000，最大 80000。",
                        },
                        "include_diff_summary": {
                            "type": "boolean",
                            "description": "commit_readiness/commit_message 是否包含 diff 摘要。默认 true。",
                        },
                        "max_diff_chars": {
                            "type": "integer",
                            "description": "commit_readiness/commit_message 的 diff 字符限制。默认 40000，最大 80000。",
                        },
                        "style": {
                            "type": "string",
                            "enum": ["conventional", "runner_version", "concise"],
                            "description": "commit_message 可选。commit message 风格倾向。默认 runner_version。",
                        },
                        "scope_hint": {
                            "type": "string",
                            "description": "commit_message 可选。版本号或 scope 提示。",
                        },
                        "include_files": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "可选。commit_readiness/commit_message 指定的文件子集。",
                        },
                        "exclude_files": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "可选。commit_readiness/commit_message 排除的文件。",
                        },
                        "include_patch": {
                            "type": "boolean",
                            "description": "history_show 是否包含 patch。默认 true。",
                        },
                        "include_log": {
                            "type": "boolean",
                            "description": "review_context 是否包含 git log。默认 true。",
                        },
                        "log_limit": {
                            "type": "integer",
                            "description": "review_context 的 log 数量。默认 5，最大 20。",
                        },
                        "include_repo_overview": {
                            "type": "boolean",
                            "description": "review_context 是否包含 repo overview。默认 false。",
                        },
                        "max_files": {
                            "type": "integer",
                            "description": "review_context 的 repo overview 最大文件数。默认 200，最大 500。",
                        },
                        "reason": {
                            "type": "string",
                            "description": "可选。preview 类动作的理由说明。",
                        },
                        "scan_limit": {
                            "type": "integer",
                            "description": "reconcile_git_history_preview 可选。扫描最近 N 个 commit，默认 20，最大 100。",
                        },
                    },
                    "required": ["action"],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
            ),
            MCPToolDef(
                name="manage_git_commit",
                description=f"[{self.project_hint}] Manage a controlled git commit flow with readiness, suggest_commit_message, commit_workflow_preview, preview, and commit actions. 支持按已登记 managed project_name 路由目标项目。This tool never runs arbitrary shell, never exposes arbitrary git commands, and never stages all files at once.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["readiness", "suggest_commit_message", "commit_workflow_preview", "preview", "commit"],
                            "description": "Commit workflow action.",
                        },
                        "message": {
                            "type": "string",
                            "description": "Commit message for preview, commit_workflow_preview, or commit. Required for preview; optional for commit if matching preview message is stored.",
                        },
                        "preview_id": {
                            "type": "string",
                            "description": "Preview id returned by action=preview or commit_workflow_preview. Required for action=commit.",
                        },
                        "include_diff_summary": {
                            "type": "boolean",
                            "description": "Whether readiness/preview should include a bounded diff summary. Defaults to true.",
                        },
                        "max_diff_chars": {
                            "type": "integer",
                            "description": "Maximum diff characters to include in readiness/preview. Defaults to 40000 and is capped at 80000.",
                        },
                        "style": {
                            "type": "string",
                            "enum": ["conventional", "runner_version", "concise"],
                            "description": "suggest_commit_message 可选。commit message 风格倾向。默认 runner_version。",
                        },
                        "scope_hint": {
                            "type": "string",
                            "description": "suggest_commit_message 可选。版本号或 scope 提示，例如 v1.73。",
                        },
                        "include_files": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "可选，仅用于 readiness/suggest_commit_message/commit_workflow_preview/preview。指定要提交的文件子集。",
                        },
                        "exclude_files": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "可选，仅用于 readiness/suggest_commit_message/commit_workflow_preview/preview。用于从选择结果中排除文件。",
                        },
                        "project_name": {
                            "type": "string",
                            "description": "可选。按已登记 managed project_name 路由 readiness、suggest_commit_message、commit_workflow_preview、preview、commit。",
                        },
                    },
                    "required": ["action"],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
            ),
            MCPToolDef(
                name="manage_git_remote",
                description=f"[{self.project_hint}] 受控 Git remote 工具。支持 push、fetch preview/apply 与 fast-forward pull preview/apply。project_name 当前支持已登记 managed 项目的 push_status、push_preview、push_apply。",
                input_schema={
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": [
                                "push_status",
                                "push_preview",
                                "push_apply",
                                "fetch_preview",
                                "fetch_apply",
                                "pull_status",
                                "pull_preview",
                                "pull_apply",
                            ],
                            "description": "Git remote action.",
                        },
                        "preview_id": {
                            "type": "string",
                            "description": "apply 类 action 必填。来自对应 preview 的 preview_id。",
                        },
                        "reason": {
                            "type": "string",
                            "description": "可选。预览原因说明。",
                        },
                        "project_name": {
                            "type": "string",
                            "description": "可选。按已登记 managed project_name 路由 push_status、push_preview、push_apply。",
                        },
                    },
                    "required": ["action"],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
            ),
            MCPToolDef(
                name="manage_runner_plan",
                description=f"[{self.project_hint}] Manage controlled Runner plan onboarding for the bound source project with inspect, preview, and apply actions. bootstrap_preview project_name is the new plan name, not a registry routing key. This never writes arbitrary files and does not use paste-plan UI.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["inspect", "bootstrap_preview", "import_preview", "apply"],
                            "description": "Runner plan management action.",
                        },
                        "project_name": {
                            "type": "string",
                            "description": "bootstrap_preview 必填。新建 plan.json 的 project_name；仅用于命名当前绑定 source 项目，不按 registry 路由。",
                        },
                        "plan_json": {
                            "type": "string",
                            "description": "Full plan JSON string for import_preview. Intended for MCP/ChatGPT structured import, not Web paste UI.",
                        },
                        "preview_id": {
                            "type": "string",
                            "description": "Preview id returned by bootstrap_preview or import_preview. Required for apply.",
                        },
                        "allow_overwrite": {
                            "type": "boolean",
                            "description": "Whether apply can overwrite an existing .colameta/plan.json. Defaults to false.",
                        },
                    },
                    "required": ["action"],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
            ),
            MCPToolDef(
                name="manage_project_memory",
                description=f"[{self.project_hint}] 统一项目记忆工具。支持 record_type=memory|todo|decision 与 action=read|add|update|delete。memory 记录 GPTs 长期记忆，todo 记录后续事项，decision 记录已确认决策。支持 project_name 路由到已登记 managed 项目。",
                input_schema={
                    "type": "object",
                    "properties": {
                        "record_type": {
                            "type": "string",
                            "enum": ["memory", "todo", "decision"],
                            "description": "记忆类型。memory=GPTs 长期记忆；todo=后续事项；decision=已确认决策。",
                        },
                        "action": {
                            "type": "string",
                            "enum": ["read", "add", "update", "delete"],
                            "description": "记忆操作。",
                        },
                        "project_name": {
                            "type": "string",
                            "description": "可选。按已登记 managed project_name 路由到目标项目记忆。",
                        },
                        "id": {
                            "type": "string",
                            "description": "todo/decision update/delete 必填；memory 不使用。",
                        },
                        "include_done": {
                            "type": "boolean",
                            "default": False,
                            "description": "仅 todo read 有意义。是否包含 done 条目。",
                        },
                        "content": {
                            "type": "string",
                            "description": "todo add/update 的内容；memory add/update 的完整 Markdown 内容。",
                        },
                        "max_chars": {
                            "type": "integer",
                            "description": "仅 memory read 有意义。返回内容字符上限，默认 30000，最大 120000。",
                        },
                        "status": {
                            "type": "string",
                            "description": "todo 或 decision 的状态。具体允许值由底层记录类型校验。",
                        },
                        "title": {
                            "type": "string",
                            "description": "decision add/update 的标题。",
                        },
                        "decision": {
                            "type": "string",
                            "description": "decision add/update 的决策内容。",
                        },
                        "reason": {
                            "type": "string",
                            "description": "decision add/update 的原因。",
                        },
                        "related_versions": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "decision add/update 的相关版本列表。",
                        },
                    },
                    "required": ["record_type", "action"],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
            ),
            MCPToolDef(
                name="manage_runner_record",
                description=f"[{self.project_hint}] 统一项目记录工具。支持 record_type=todo|decision 与 action=read|add|update|delete，内部复用现有 todo/decision 实现与校验。支持 project_name 路由到已登记 managed 项目。",
                input_schema={
                    "type": "object",
                    "properties": {
                        "record_type": {
                            "type": "string",
                            "enum": ["todo", "decision"],
                            "description": "记录类型。",
                        },
                        "action": {
                            "type": "string",
                            "enum": ["read", "add", "update", "delete"],
                            "description": "记录操作。",
                        },
                        "project_name": {
                            "type": "string",
                            "description": "可选。按已登记 managed project_name 路由到目标项目记录。",
                        },
                        "id": {
                            "type": "string",
                            "description": "update/delete 必填；todo/decision 记录 id。",
                        },
                        "include_done": {
                            "type": "boolean",
                            "default": False,
                            "description": "仅 todo read 有意义。是否包含 done 条目。",
                        },
                        "content": {
                            "type": "string",
                            "description": "todo add/update 的内容。",
                        },
                        "status": {
                            "type": "string",
                            "description": "todo 或 decision 的状态。具体允许值由底层记录类型校验。",
                        },
                        "title": {
                            "type": "string",
                            "description": "decision add/update 的标题。",
                        },
                        "decision": {
                            "type": "string",
                            "description": "decision add/update 的决策内容。",
                        },
                        "reason": {
                            "type": "string",
                            "description": "decision add/update 的原因。",
                        },
                        "related_versions": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "decision add/update 的相关版本列表。",
                        },
                    },
                    "required": ["record_type", "action"],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
            ),
            MCPToolDef(
                name="manage_workflow_run",
                description=f"[{self.project_hint}] 统一 workflow run 查询工具。支持 action=list|get，内部复用现有 workflow record 列表与详情读取实现。支持 project_name 路由到已登记 managed 项目。scope=mcp:read。",
                input_schema={
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["list", "get"],
                            "description": "查询操作。",
                        },
                        "workflow_id": {
                            "type": "string",
                            "description": "action=get 必填；workflow_id。",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "action=list 可选。最大返回条数。默认 20，最大 100。",
                        },
                        "workflow_name": {
                            "type": "string",
                            "description": "action=list 可选。按 workflow_name 筛选。",
                        },
                        "status": {
                            "type": "string",
                            "description": "action=list 可选。按 status 筛选（running/succeeded/failed/partial/unsupported）。",
                        },
                        "project_name": {
                            "type": "string",
                            "description": "可选。按已登记 managed project_name 路由读取目标项目 workflow records。",
                        },
                    },
                    "required": ["action"],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
            ),
            MCPToolDef(
                name="todo_read",
                description=f"[{self.project_hint}] 读取 .colameta/todolist.json，可选只看 planned 项或包含 done 项。支持 project_name 路由到已登记 managed 项目。",
                input_schema={
                    "type": "object",
                    "properties": {
                        "include_done": {
                            "type": "boolean",
                            "default": False,
                            "description": "是否包含 done 条目。默认只返回 planned 条目。",
                        },
                        "project_name": {
                            "type": "string",
                            "description": "可选。按已登记 managed project_name 路由读取目标项目 todolist。",
                        },
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
            ),
            MCPToolDef(
                name="todo_add",
                description=f"[{self.project_hint}] 追加一条需求备忘录，可选指定 status。支持 project_name 路由到已登记 managed 项目。",
                input_schema={
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": "需求压缩描述。",
                        },
                        "status": {
                            "type": "string",
                            "enum": ["planned", "done"],
                            "description": "条目状态。默认 planned。",
                        },
                        "project_name": {
                            "type": "string",
                            "description": "可选。按已登记 managed project_name 路由写入目标项目 todolist。",
                        },
                    },
                    "required": ["content"],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
            ),
            MCPToolDef(
                name="todo_update",
                description=f"[{self.project_hint}] 按 id 更新一条需求备忘录内容或状态，保留原 id 和 created_at。支持 project_name 路由到已登记 managed 项目。",
                input_schema={
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": "todo id。",
                        },
                        "content": {
                            "type": "string",
                            "description": "更新后的需求压缩描述。",
                        },
                        "status": {
                            "type": "string",
                            "enum": ["planned", "done"],
                            "description": "更新后的条目状态。",
                        },
                        "project_name": {
                            "type": "string",
                            "description": "可选。按已登记 managed project_name 路由更新目标项目 todolist。",
                        },
                    },
                    "required": ["id"],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
            ),
            MCPToolDef(
                name="todo_delete",
                description=f"[{self.project_hint}] 按 id 删除一条需求备忘录。支持 project_name 路由到已登记 managed 项目。",
                input_schema={
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": "todo id。",
                        },
                        "project_name": {
                            "type": "string",
                            "description": "可选。按已登记 managed project_name 路由删除目标项目 todolist。",
                        },
                    },
                    "required": ["id"],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
            ),
            MCPToolDef(
                name="decision_read",
                description=f"[{self.project_hint}] 读取 .colameta/decisions.json，返回已记录的产品或架构决策。支持 project_name 路由到已登记 managed 项目。",
                input_schema={
                    "type": "object",
                    "properties": {
                        "project_name": {
                            "type": "string",
                            "description": "可选。按已登记 managed project_name 路由读取目标项目 decisions。",
                        },
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
            ),
            MCPToolDef(
                name="decision_add",
                description=f"[{self.project_hint}] 追加一条已接受的产品或架构决策记录。支持 project_name 路由到已登记 managed 项目。",
                input_schema={
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "决策标题。",
                        },
                        "decision": {
                            "type": "string",
                            "description": "决策内容。",
                        },
                        "reason": {
                            "type": "string",
                            "description": "决策原因。",
                        },
                        "related_versions": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "相关版本列表。",
                        },
                        "status": {
                            "type": "string",
                            "enum": ["active", "superseded", "rejected"],
                            "description": "决策状态。默认 active。",
                        },
                        "project_name": {
                            "type": "string",
                            "description": "可选。按已登记 managed project_name 路由写入目标项目 decisions。",
                        },
                    },
                    "required": ["title", "decision", "reason"],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
            ),
            MCPToolDef(
                name="decision_update",
                description=f"[{self.project_hint}] 按 id 更新决策记录内容、原因、相关版本或状态。支持 project_name 路由到已登记 managed 项目。",
                input_schema={
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": "decision id。",
                        },
                        "title": {
                            "type": "string",
                            "description": "更新后的决策标题。",
                        },
                        "decision": {
                            "type": "string",
                            "description": "更新后的决策内容。",
                        },
                        "reason": {
                            "type": "string",
                            "description": "更新后的决策原因。",
                        },
                        "related_versions": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "更新后的相关版本列表。",
                        },
                        "status": {
                            "type": "string",
                            "enum": ["active", "superseded", "rejected"],
                            "description": "更新后的决策状态。",
                        },
                        "project_name": {
                            "type": "string",
                            "description": "可选。按已登记 managed project_name 路由更新目标项目 decisions。",
                        },
                    },
                    "required": ["id"],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
            ),
            MCPToolDef(
                name="decision_delete",
                description=f"[{self.project_hint}] 按 id 删除一条决策记录。支持 project_name 路由到已登记 managed 项目。",
                input_schema={
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": "decision id。",
                        },
                        "project_name": {
                            "type": "string",
                            "description": "可选。按已登记 managed project_name 路由删除目标项目 decisions。",
                        },
                    },
                    "required": ["id"],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
            ),
            MCPToolDef(
                name="manage_plan_version",
                description=f"[{self.project_hint}] 结构化 Runner plan 版本管理工具。支持 inspect、insert/update/repair preview、insert_from_prompt_file_preview、apply_preview_status、apply_preview、reload_plan、continue_next_version。reload_plan/continue_next_version 会同步 state.json。project_name 支持已登记 managed 项目的 preview、status、apply_preview、reload_plan、continue_next_version 路由。",
                input_schema={
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["inspect", "insert_preview", "update_preview", "repair_preview", "apply_preview_status", "insert_from_prompt_file_preview", "apply_preview", "reload_plan", "continue_next_version"],
                            "description": "Plan version 管理操作。reload_plan 会重载 plan 并同步 state.json；continue_next_version 会在当前版本通过后推进到下一版本；apply_preview 受控应用 plan patch。",
                        },
                        "patch_id": {
                            "type": "string",
                            "description": "apply_preview_status 或 apply_preview 操作需要的 patch_id。",
                        },
                        "insert_after": {
                            "type": "string",
                            "description": "insert_preview 操作需要。在此版本后插入新版本。",
                        },
                        "version": {
                            "type": "string",
                            "description": "insert_preview（新版本号）或 update_preview（目标版本号）或 repair_preview（可选版本过滤）。",
                        },
                        "name": {
                            "type": "string",
                            "description": "insert_preview 必填。版本显示名称。",
                        },
                        "description": {
                            "type": "string",
                            "description": "insert_preview 必填。版本描述。",
                        },
                        "prompt": {
                            "type": "string",
                            "description": "insert_preview 必填。版本 prompt 内容。update_preview 可选更新 prompt。",
                        },
                        "allowed_files": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "insert_preview 必填。版本允许修改的文件模式列表。不能为空。",
                        },
                        "acceptance_commands": {
                            "type": "array",
                            "items": {
                                "oneOf": [
                                    {"type": "string"},
                                    {"type": "object",
                                     "properties": {
                                         "command": {"type": "string"},
                                         "timeout_seconds": {"type": "integer"},
                                         "continue_on_failure": {"type": "boolean"},
                                     },
                                     "required": ["command"],
                                     "additionalProperties": False,
                                    },
                                ],
                            },
                            "description": "insert_preview 必填。版本验收命令列表。可以是 string 或 object（command/timeout_seconds/continue_on_failure）。不允许空列表。",
                        },
                        "manual_acceptance": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "可选。手动验收检查项列表。",
                        },
                        "out_of_scope": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "可选。此版本不包含的范围说明列表。",
                        },
                        "context_files": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "可选。版本上下文文件模式列表。",
                        },
                        "forbidden_files": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "可选。版本禁止修改的文件模式列表。",
                        },
                        "allow_no_changes": {
                            "type": "boolean",
                            "description": "可选。read-only/audit 版本设置为 true 后，可在验收通过且无 allowed_files diff 时通过。默认 false 仍阻断无变更。",
                        },
                        "execution": {
                            "type": "object",
                            "description": "可选。版本执行器配置。provider 必须是 pi/codex/opencode。",
                            "properties": {
                                "provider": {
                                    "type": "string",
                                    "enum": ["pi", "codex", "opencode"],
                                    "description": "执行器 provider。",
                                },
                            },
                            "additionalProperties": True,
                        },
                        "prompt_file": {
                            "type": "string",
                            "description": "insert_preview 可选。覆盖默认 prompt 文件名。insert_from_prompt_file_preview 必填。prompt 文件相对路径，仅文件名，例如 v1.84.54.md。",
                        },
                        "repair_kinds": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": ["acceptance_command_shape", "invalid_provider", "missing_optional_safety_fields", "prompt_file_safety"],
                            },
                            "description": "repair_preview 可选。指定需要修复的种类；不传时自动检测所有可修复项。",
                        },
                        "dry_run": {
                            "type": "boolean",
                            "description": "repair_preview 可选。是否只做检查不生成 patch。默认 true。",
                        },
                        "project_name": {
                            "type": "string",
                            "description": "可选。按已登记 managed project_name 路由所有支持动作：insert_preview、update_preview、repair_preview、apply_preview_status、insert_from_prompt_file_preview、apply_preview、reload_plan、continue_next_version。",
                        },
                    },
                    "required": ["action"],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
            ),
            MCPToolDef(
                name="manage_project_patch",
                description=f"[{self.project_hint}] 通用小范围非文档文件的受控 patch 工具（源码、脚本、配置、测试数据）。README.md、AGENTS.md、docs/*.md 请优先使用 manage_project_docs。只有用户明确给出 exact old_text/new_text 或非文档通用 patch 时，才用本工具。scope：status=mcp:read，preview=mcp:preview，apply=mcp:commit。",
                input_schema={
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["preview", "apply", "status"],
                            "description": "Patch 操作。preview 预览改动（不写文件），apply 应用 preview（写文件），status 查询 preview 状态。",
                        },
                        "preview_id": {
                            "type": "string",
                            "description": "apply 或 status 操作需要的 preview_id。",
                        },
                        "file": {
                            "type": "string",
                            "description": "精确替换模式的相对文件路径。",
                        },
                        "old_text": {
                            "type": "string",
                            "description": "精确替换模式的旧文本。必须在文件中唯一。",
                        },
                        "new_text": {
                            "type": "string",
                            "description": "精确替换模式的新文本。可以为空字符串。",
                        },
                        "patch_text": {
                            "type": "string",
                            "description": "unified diff 模式的 patch 文本。",
                        },
                        "reason": {
                            "type": "string",
                            "description": "可选。patch 理由说明。",
                        },
                        "max_files": {
                            "type": "integer",
                            "description": "可选。最大文件数。默认 5，最大 5。",
                        },
                        "max_diff_chars": {
                            "type": "integer",
                            "description": "可选。最大 diff 字符数。默认 20000，最大 20000。",
                        },
                        "project_name": {
                            "type": "string",
                            "description": "可选。按已登记 managed project_name 路由所有操作。",
                        },
                    },
                    "required": ["action"],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
            ),
            MCPToolDef(
                name="manage_git_history",
                description=f"[{self.project_hint}] 受控 Git 历史管理工具。支持 log（查看历史）、show（查看 commit 详情）、diff_commits（对比 commit）、reconcile_git_history_preview（扫描 direct version 候选）、restore_file_preview（恢复文件预览）、restore_file_apply（恢复文件）、revert_preview（撤销预览）、revert_apply（受控撤销应用，必须使用 revert_preview 返回的 preview_id，不自动 commit，冲突时不自动解决）。不提供 reset/clean/push/merge/rebase。scope：log/show/diff_commits=mcp:read，reconcile_git_history_preview/restore_file_preview/revert_preview=mcp:preview，restore_file_apply/revert_apply=mcp:commit。",
                input_schema={
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["log", "show", "diff_commits", "reconcile_git_history_preview", "restore_file_preview", "restore_file_apply", "revert_preview", "revert_apply"],
                            "description": "Git history 操作。",
                        },
                        "commit": {
                            "type": "string",
                            "description": "show、restore_file_preview、revert_preview 使用的 commit ref。",
                        },
                        "base": {
                            "type": "string",
                            "description": "diff_commits 的基础 commit。",
                        },
                        "head": {
                            "type": "string",
                            "description": "diff_commits 的目标 commit。",
                        },
                        "file": {
                            "type": "string",
                            "description": "restore_file_preview 必填的相对文件路径；diff_commits 可选过滤文件。",
                        },
                        "preview_id": {
                            "type": "string",
                            "description": "restore_file_apply/revert_apply 使用的 preview_id。",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "log 返回 commit 数量。默认 12，最大 50。",
                        },
                        "max_chars": {
                            "type": "integer",
                            "description": "show/diff_commits/revert_preview 的 diff 字符限制。默认 40000，最大 80000。",
                        },
                        "include_patch": {
                            "type": "boolean",
                            "description": "show 是否包含 patch。默认 true。",
                        },
                        "reason": {
                            "type": "string",
                            "description": "可选。preview 类动作的理由说明。",
                        },
                        "scan_limit": {
                            "type": "integer",
                            "description": "reconcile_git_history_preview 可选。扫描最近 N 个 commit，默认 20，最大 100。",
                        },
                        "project_name": {
                            "type": "string",
                            "description": "可选。按已登记 managed project_name 路由所有操作。",
                        },
                    },
                    "required": ["action"],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
            ),
            MCPToolDef(
                name="manage_plan_workflow",
                description=f"[{self.project_hint}] [已弃用/legacy] 受控 Plan Workflow 自动化工具。此工具仅用于兼容旧流程，新流程请使用 manage_runner_plan（source-only 纳管）或 manage_plan_version（版本管理）。支持 source_onboarding_preview（从源码项目自动生成 onboarding 预览）、plan_repair_preview（lint 修复预览）、plan_extend_preview（扩展新版本预览）。project_name 当前仅支持已登记 managed 项目的 plan_repair_preview、plan_extend_preview。scope=mcp:preview。",
                input_schema={
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["source_onboarding_preview", "plan_repair_preview", "plan_extend_preview"],
                            "description": "Plan workflow action。",
                        },
                        "dry_run": {
                            "type": "boolean",
                            "description": "source_onboarding_preview 和 plan_repair_preview 支持 dry_run=true 只做分析不生成 patch。",
                        },
                        "max_files": {
                            "type": "integer",
                            "description": "source_onboarding_preview 可选。仓库文件树最大文件数。默认 300，最大 500。",
                        },
                        "version": {
                            "type": "string",
                            "description": "plan_repair_preview 可选版本过滤；plan_extend_preview 新版本号。",
                        },
                        "repair_kinds": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": ["acceptance_command_shape", "invalid_provider", "missing_optional_safety_fields", "prompt_file_safety"],
                            },
                            "description": "plan_repair_preview 可选。指定修复种类。",
                        },
                        "insert_after": {
                            "type": "string",
                            "description": "plan_extend_preview 可选。在此版本后插入。",
                        },
                        "name": {
                            "type": "string",
                            "description": "plan_extend_preview 可选。版本名称。",
                        },
                        "description": {
                            "type": "string",
                            "description": "plan_extend_preview 可选。版本描述。",
                        },
                        "prompt": {
                            "type": "string",
                            "description": "plan_extend_preview 可选。版本 prompt。不传则自动生成。",
                        },
                        "project_name": {
                            "type": "string",
                            "description": "source_onboarding_preview 单项目模式下可选，覆盖项目名称。不传则自动推断。project_name 路由模式下仅支持已登记 managed 项目的 plan_repair_preview、plan_extend_preview。",
                        },
                        "goal": {
                            "type": "string",
                            "description": "source_onboarding_preview 可选。覆盖项目目标。不传则自动推断。",
                        },
                        "first_version": {
                            "type": "string",
                            "description": "source_onboarding_preview 可选。首版本号。默认 v1.0。",
                        },
                        "first_version_name": {
                            "type": "string",
                            "description": "source_onboarding_preview 可选。首版本显示名称。默认 Adopt existing project into Runner。",
                        },
                        "target_version": {
                            "type": "string",
                            "description": "manage_plan_workflow 可选。目标版本号，用于 plan_repair_preview。",
                        },
                        "reason": {
                            "type": "string",
                            "description": "manage_plan_workflow 可选。操作理由说明，进入 workflow record。",
                        },
                    },
                    "required": ["action"],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
            ),
            MCPToolDef(
                name="manage_project_docs",
                description=f"[{self.project_hint}] 文档语义层工具。创建或修改 README.md、AGENTS.md、docs/*.md 时优先使用。支持 index、search、read_section、update_section_preview、append_section_preview（支持创建新文件）、sync_docs_preview、apply。底层复用 manage_project_patch。scope：index/search/read_section=mcp:read，preview 类=mcp:preview，apply=mcp:commit。",
                input_schema={
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["index", "search", "read_section", "update_section_preview", "append_section_preview", "sync_docs_preview", "apply"],
                            "description": "Docs management action。",
                        },
                        "project_name": {
                            "type": "string",
                            "description": "可选。按已登记 managed project_name 路由文档索引、读取、搜索、预览和 apply。",
                        },
                        "file": {
                            "type": "string",
                            "description": "read_section/update_section_preview/append_section_preview 使用的文件路径。只允许 README.md、AGENTS.md、docs/*.md。",
                        },
                        "heading": {
                            "type": "string",
                            "description": "read_section/update_section_preview 使用的 Markdown heading。",
                        },
                        "query": {
                            "type": "string",
                            "description": "search 使用的搜索关键词。",
                        },
                        "new_content": {
                            "type": "string",
                            "description": "update_section_preview 使用的 section body 新内容（不含 heading 行）。",
                        },
                        "section_heading": {
                            "type": "string",
                            "description": "append_section_preview 使用的新 section heading。",
                        },
                        "section_content": {
                            "type": "string",
                            "description": "append_section_preview 使用的新 section 内容。",
                        },
                        "after_heading": {
                            "type": "string",
                            "description": "append_section_preview 可选。指定在此 heading section 后追加。",
                        },
                        "stale_terms": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "sync_docs_preview 可选。自定义过时术语列表。",
                        },
                        "preview_id": {
                            "type": "string",
                            "description": "apply 使用的 preview_id。",
                        },
                        "max_chars": {
                            "type": "integer",
                            "description": "read/index/search 输出字符限制。默认 12000，最大 30000。",
                        },
                        "max_files": {
                            "type": "integer",
                            "description": "index/search/sync_docs_preview 最大文件数。默认 50，最大 100。",
                        },
                        "reason": {
                            "type": "string",
                            "description": "可选。操作理由，进入 workflow record 和底层 patch reason。",
                        },
                    },
                    "required": ["action"],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
            ),
            MCPToolDef(
                name="manage_prompt_file",
                description=(
                    f"[{self.project_hint}] 受控提示词文件保存工具。"
                    "支持 preview（预览）、apply（应用 preview 写入文件）、status（查询 preview 状态）、discard（废弃 preview artifact）。"
                    "文件写入 .colameta/prompts/{version}.md。"
                    "不运行执行器、不提交 Git、不修改 Runner plan。"
                    "project_name 支持已登记 managed 项目的 preview、apply、status、discard。"
                    "scope：status=mcp:read，preview=mcp:preview，discard=mcp:preview，apply=mcp:commit。"
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["preview", "apply", "status", "discard"],
                            "description": "Prompt file management action. discard 废弃 preview artifact，不写文件。",
                        },
                        "version": {
                            "type": "string",
                            "description": "preview 必填。版本号，用于生成文件名 .colameta/prompts/{version}.md。",
                        },
                        "content": {
                            "type": "string",
                            "description": "preview 必填。提示词正文。",
                        },
                        "preview_id": {
                            "type": "string",
                            "description": "apply/status/discard 必填。来自 preview 的 preview_id。",
                        },
                        "overwrite": {
                            "type": "boolean",
                            "description": "preview 可选。是否允许覆盖已有文件。默认 false。",
                        },
                        "reason": {
                            "type": "string",
                            "description": "preview 可选。操作理由。",
                        },
                        "max_preview_chars": {
                            "type": "integer",
                            "description": "preview 可选。content_preview 截断字符数。默认 200，最小 1，最大 5000。",
                        },
                        "allowed_files": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "preview 可选。自动写入 prompt front matter 的 allowed_files。",
                        },
                        "acceptance_commands": {
                            "type": "array",
                            "items": {
                                "oneOf": [
                                    {"type": "string"},
                                    {
                                        "type": "object",
                                        "properties": {
                                            "command": {"type": "string"},
                                            "timeout_seconds": {"type": "integer"},
                                            "continue_on_failure": {"type": "boolean"},
                                        },
                                        "required": ["command"],
                                        "additionalProperties": False,
                                    },
                                ],
                            },
                            "description": "preview 可选。自动写入 prompt front matter 的 acceptance_commands。",
                        },
                        "allow_no_changes": {
                            "type": "boolean",
                            "description": "preview 可选。自动写入 prompt front matter；read-only/audit 版本可在验收通过且无 allowed_files diff 时通过。",
                        },
                        "execution": {
                            "type": "object",
                            "properties": {
                                "provider": {
                                    "type": "string",
                                    "enum": ["pi", "codex", "opencode"],
                                    "description": "执行器 provider。",
                                },
                            },
                            "additionalProperties": False,
                            "description": "preview 可选。自动写入 prompt front matter 的 execution 配置。",
                        },
                        "project_name": {
                            "type": "string",
                            "description": "可选。按已登记 managed project_name 路由 prompt preview/apply/status/discard。",
                        },
                    },
                    "required": ["action"],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
            ),
            MCPToolDef(
                name="get_version_result",
                description="读取指定版本或当前版本结果",
                input_schema={
                    "type": "object",
                    "properties": {
                        "version": {
                            "type": "string",
                            "description": "Version to inspect. Omit this field to inspect the current version.",
                        }
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
            ),
            MCPToolDef(
                name="get_next_version_plan",
                description="读取下一版本计划",
                input_schema={
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
            ),
            MCPToolDef(
                name="get_plan_overview",
                description=f"[{self.project_hint}] 读取计划概览",
                input_schema={
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
            ),
            MCPToolDef(
                name="get_project_doc_section",
                description="读取项目白名单文档中指定 heading 的段落内容。",
                input_schema={
                    "type": "object",
                    "properties": {
                        "file": {
                            "type": "string",
                            "description": "Relative project document path, for example docs/Prompt.md.",
                        },
                        "heading": {
                            "type": "string",
                            "description": "Markdown heading or version label to extract, for example v1.1.",
                        },
                        "max_chars": {
                            "type": "integer",
                            "description": "Maximum characters to return. Defaults to 12000. Maximum 30000.",
                        },
                    },
                    "required": ["file", "heading"],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
            ),
            MCPToolDef(
                name="preview_insert_version",
                description="Preview insertion of a new version into the Runner plan. The spec_json string must be a JSON object with fields: insert_after, version, name, description, prompt, allowed_files, acceptance_commands, and optional manual_acceptance, out_of_scope, context_files. This only creates a pending patch and does not modify plan.json.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "spec_json": {
                            "type": "string",
                            "description": "JSON string for the version insertion spec. It must include insert_after, version, name, description, prompt, allowed_files, and acceptance_commands.",
                        }
                    },
                    "required": ["spec_json"],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
            ),
            MCPToolDef(
                name="preview_update_version",
                description="Preview update of an existing Runner version. The spec_json string must be a JSON object with version and at least one update field such as prompt, description, allowed_files, acceptance_commands, manual_acceptance, out_of_scope, context_files, or execution. This only creates a pending patch and does not modify plan.json.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "spec_json": {
                            "type": "string",
                            "description": "JSON string for the version update spec. It must include version and at least one update field such as prompt, description, allowed_files, acceptance_commands, manual_acceptance, out_of_scope, context_files, or execution.",
                        }
                    },
                    "required": ["spec_json"],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
            ),
            MCPToolDef(
                name="get_plan_patch_status",
                description="查询 patch 状态",
                input_schema={
                    "type": "object",
                    "properties": {"patch_id": {"type": "string"}},
                    "required": ["patch_id"],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
            ),
            MCPToolDef(
                name="get_repo_overview",
                description=f"[{self.project_hint}] 读取受控仓库概览，包括 git 状态、最近提交和安全过滤后的文件树。",
                input_schema={
                    "type": "object",
                    "properties": {
                        "project_name": {
                            "type": "string",
                            "description": "可选。按已登记 project_name 路由读取目标项目仓库概览。",
                        },
                        "max_depth": {
                            "type": "integer",
                            "description": "Maximum file tree depth. Defaults to 3.",
                        },
                        "max_files": {
                            "type": "integer",
                            "description": "Maximum number of file tree entries. Defaults to 300.",
                        },
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
            ),
            MCPToolDef(
                name="get_git_status",
                description=f"[{self.project_hint}] 读取 git status --short。",
                input_schema={
                    "type": "object",
                    "properties": {
                        "project_name": {
                            "type": "string",
                            "description": "可选。按已登记 project_name 路由读取目标项目 git 状态。",
                        }
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
            ),
            MCPToolDef(
                name="get_git_log",
                description="读取当前 MCP 绑定项目的最近提交记录，支持按 project_name 路由。",
                input_schema={
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "description": "Maximum commits to return. Defaults to 12 and is capped at 50.",
                        },
                        "project_name": {
                            "type": "string",
                            "description": "可选。按已登记 project_name 路由读取目标项目提交记录。",
                        },
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
            ),
            MCPToolDef(
                name="get_source_file",
                description="读取当前 MCP 绑定项目白名单源码文件的全文或指定行范围。",
                input_schema={
                    "type": "object",
                    "properties": {
                        "project_name": {
                            "type": "string",
                            "description": "可选。按已登记 project_name 路由读取目标项目源码文件。",
                        },
                        "file": {
                            "type": "string",
                            "description": "Relative source file path, for example runner/web_console.py.",
                        },
                        "max_chars": {
                            "type": "integer",
                            "description": "Maximum characters to return. Defaults to 30000 and is capped at 100000.",
                        },
                        "start_line": {
                            "type": "integer",
                            "description": "Optional 1-based start line.",
                        },
                        "end_line": {
                            "type": "integer",
                            "description": "Optional 1-based end line.",
                        },
                    },
                    "required": ["file"],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
            ),
            MCPToolDef(
                name="search_source",
                description="在当前 MCP 绑定项目的白名单源码文件中搜索关键词。",
                input_schema={
                    "type": "object",
                    "properties": {
                        "project_name": {
                            "type": "string",
                            "description": "可选。按已登记 project_name 路由搜索目标项目源码。",
                        },
                        "query": {
                            "type": "string",
                            "description": "Search query, 1 to 120 characters.",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum results to return. Defaults to 30 and is capped at 100.",
                        },
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
            ),
            MCPToolDef(
                name="manage_files",
                description=f"[{self.project_hint}] 统一项目文件搜索、读取与受控编辑工具。action=search 按关键词搜索白名单项目文件；action=read 读取指定文件内容；action=create/edit/delete 受控文件生命周期操作（委托 MCPProjectPatchManager），均需 phase=preview|apply|status。scope：search/read/status=mcp:read，preview=mcp:preview，apply=mcp:commit。",
                input_schema={
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["search", "read", "create", "edit", "delete"],
                            "description": "文件操作。search=搜索，read=读取，create=创建，edit=编辑，delete=删除。create/edit/delete 需要 phase=preview|apply|status。",
                        },
                        "phase": {
                            "type": "string",
                            "enum": ["preview", "apply", "status"],
                            "description": "action=create/edit/delete 必填。preview 预览改动（不写文件），apply 应用 preview（写文件），status 查询 preview 状态。",
                        },
                        "project_name": {
                            "type": "string",
                            "description": "可选。按已登记 project_name 路由到目标项目。",
                        },
                        "query": {
                            "type": "string",
                            "description": "action=search 必填。搜索关键词，1 到 120 字符。",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "action=search 可选。最大返回条数。默认 30，最大 100。",
                        },
                        "file": {
                            "type": "string",
                            "description": "action=read 或 action=create/edit/delete 必填。相对文件路径，例如 runner/web_console.py。",
                        },
                        "max_chars": {
                            "type": "integer",
                            "description": "action=read 可选。最大返回字符数。默认 30000，最大 100000。",
                        },
                        "start_line": {
                            "type": "integer",
                            "description": "action=read 可选。1-based 起始行号。",
                        },
                        "end_line": {
                            "type": "integer",
                            "description": "action=read 可选。1-based 结束行号。",
                        },
                        "old_text": {
                            "type": "string",
                            "description": "action=edit phase=preview 精确替换模式的旧文本。必须在文件中唯一。",
                        },
                        "new_text": {
                            "type": "string",
                            "description": "action=create/edit phase=preview 精确替换模式的新文本。create 时写入完整文件内容，edit 时替换 old_text。可以为空字符串。",
                        },
                        "patch_text": {
                            "type": "string",
                            "description": "action=edit phase=preview unified diff 模式的 patch 文本。",
                        },
                        "preview_id": {
                            "type": "string",
                            "description": "action=create/edit/delete phase=apply 或 phase=status 需要。来自 preview 操作返回的 preview_id。",
                        },
                        "reason": {
                            "type": "string",
                            "description": "action=create/edit/delete 可选。改动理由说明。",
                        },
                        "max_files": {
                            "type": "integer",
                            "description": "action=edit phase=preview 可选。最大文件数。默认 5，最大 5。",
                        },
                        "max_diff_chars": {
                            "type": "integer",
                            "description": "action=create/edit/delete phase=preview 可选。最大 diff 字符数。默认 20000，最大 20000。",
                        },
                    },
                    "required": ["action"],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
            ),
            MCPToolDef(
                name="get_git_diff",
                description=f"[{self.project_hint}] 读取 git diff，用于审查工作区改动。只返回白名单源码文件的 diff，过滤虚拟环境、本地运行态和敏感文件。",
                input_schema={
                    "type": "object",
                    "properties": {
                        "mode": {
                            "type": "string",
                            "enum": ["diff", "summary", "file", "files", "page"],
                            "description": "可选。diff=默认聚合，summary=只返回 diff map，file=单文件，files=指定文件集合，page=单文件分页。",
                        },
                        "file": {
                            "type": "string",
                            "description": "可选。file/page 模式读取单个白名单源码文件 diff。",
                        },
                        "include_files": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "可选。files 模式读取指定文件集合。",
                        },
                        "offset": {
                            "type": "integer",
                            "description": "可选。file/page 模式分页偏移量，默认 0。",
                        },
                        "max_chars": {
                            "type": "integer",
                            "description": "最大字符数。默认 60000，最大 120000。",
                        },
                        "cached": {
                            "type": "boolean",
                            "description": "是否使用 --cached 查看暂存区 diff。默认 false。",
                        },
                        "project_name": {
                            "type": "string",
                            "description": "可选。按已登记 project_name 路由读取目标项目 diff。多项目环境建议显式指定。",
                        },
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
            ),
            MCPToolDef(
                name="get_executor_inventory",
                description=f"[{self.project_hint}] 读取本地已保存的执行器 inventory，不触发探测，不执行任何命令。需要先通过 CLI probe-models 探测。",
                input_schema={
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
            ),
            MCPToolDef(
                name="list_executor_run_reports",
                description=f"[{self.project_hint}] 列出执行器完成报告。每次执行器执行完成后会自动保存结构化报告。支持按已登记 managed project_name 路由读取目标项目报告。只读，scope=mcp:read。",
                input_schema={
                    "type": "object",
                    "properties": {
                        "project_name": {
                            "type": "string",
                            "description": "可选。按已登记 managed project_name 路由读取目标项目报告列表。",
                        },
                        "version": {
                            "type": "string",
                            "description": "可选版本过滤。",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "最大返回数。默认 10，最大 50。",
                        },
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
            ),
            MCPToolDef(
                name="get_executor_run_report",
                description=f"[{self.project_hint}] 读取执行器完成报告的详细内容。支持按已登记 managed project_name 路由读取目标项目报告。只读，scope=mcp:read。",
                input_schema={
                    "type": "object",
                    "properties": {
                        "project_name": {
                            "type": "string",
                            "description": "可选。按已登记 managed project_name 路由读取目标项目报告详情。",
                        },
                        "version": {
                            "type": "string",
                            "description": "可选版本。简化 latest=true 时可不传。",
                        },
                        "report_id": {
                            "type": "string",
                            "description": "可选报告 ID，由 list_executor_run_reports 返回。",
                        },
                        "latest": {
                            "type": "boolean",
                            "description": "是否返回最新报告。默认 true。",
                        },
                        "include_markdown": {
                            "type": "boolean",
                            "description": "是否包含 markdown 内容。默认 true。",
                        },
                        "max_markdown_chars": {
                            "type": "integer",
                            "description": "最大 markdown 字符数。默认 30000，最大 60000。",
                        },
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
            ),
            MCPToolDef(
                name="inspect_executor_activity",
                description=f"[{self.project_hint}] 只读执行器状态/报告查询工具。支持 action：run_status（按 run_id 或 preview_id 查询运行状态）、latest_run_status（返回最近一次运行状态，没有记录时返回 found=false）、list_reports（列出执行器报告，支持 version 过滤和 limit）、get_report（读取指定 report 详情）、get_audit_summary（返回审计包只读摘要，不触发 recheck）。支持按已登记 managed project_name 路由读取目标项目。所有 action 都是只读不操作，scope=mcp:read。",
                input_schema={
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["run_status", "latest_run_status", "list_reports", "get_report", "get_audit_summary"],
                            "description": "只读查询 action。",
                        },
                        "project_name": {
                            "type": "string",
                            "description": "可选。按已登记 managed project_name 路由读取目标项目执行器状态或报告。",
                        },
                        "run_id": {
                            "type": "string",
                            "description": "run_status 可选。执行器运行 ID。",
                        },
                        "preview_id": {
                            "type": "string",
                            "description": "run_status 可选。preview ID。",
                        },
                        "version": {
                            "type": "string",
                            "description": "list_reports/get_report/get_audit_summary 可选。版本过滤。",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "list_reports 可选。最大返回数。默认 10，最大 50。",
                        },
                        "report_id": {
                            "type": "string",
                            "description": "get_report 可选。指定 report_id。",
                        },
                        "latest": {
                            "type": "boolean",
                            "description": "get_report 可选。是否返回最新报告。默认 true。",
                        },
                        "include_markdown": {
                            "type": "boolean",
                            "description": "get_report 可选。是否包含 markdown 内容。默认 true。",
                        },
                        "max_report_chars": {
                            "type": "integer",
                            "description": "get_report 可选。最大字符数。默认 30000，最大 60000。",
                        },
                        "section": {
                            "type": "string",
                            "enum": ["summary", "lineage", "scope", "report_excerpt"],
                            "description": "get_audit_summary 可选。审计包 section。默认 summary。",
                        },
                    },
                    "required": ["action"],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
            ),
            MCPToolDef(
                name="analyze_project_state",
                description=f"[{self.project_hint}] 只读项目状态分析工具。一次性返回项目身份、模式、Git、Runner、计划、执行器和报告的聚合状态，以及推荐下一步操作和阻断/警告。适合 ChatGPT 开始工作时先调用此工具全面了解项目状态，而不是手动串多个底层工具。scope=mcp:read。",
                input_schema={
                    "type": "object",
                    "properties": {
                        "project_name": {
                            "type": "string",
                            "description": "可选。按已登记 project_name 路由读取目标项目分析结果。",
                        },
                        "include_repo_overview": {
                            "type": "boolean",
                            "description": "是否包含仓库概览文件树。默认 false。",
                        },
                        "include_reports": {
                            "type": "boolean",
                            "description": "是否包含执行器运行报告列表。默认 true。",
                        },
                        "provider": {
                            "type": "string",
                            "enum": ["pi", "codex", "opencode"],
                            "description": "可选执行器 provider，用于评估 continuation 决策。",
                        },
                        "max_files": {
                            "type": "integer",
                            "description": "仓库概览文件树最大文件数。默认 200，最大 500。",
                        },
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
            ),
            MCPToolDef(
                name="run_mcp_workflow",
                description=(
                    f"[{self.project_hint}] Bounded Workflow Runner 统一入口。"
                    "减少工具选择压力，将常用流程收敛为一个高层入口。"
                    "auto_preview（v1.75）：自动分析 goal 并选择 bounded workflow，串联多个 read/preview 步骤，"
                    "在 apply/commit/executor-run 边界停止。推荐 ChatGPT 首选入口。"
                    "prompt_to_plan（v1.84.58）：串联 prompt 文件保存、plan insert preview、plan patch apply，"
                    "停在 executor preflight/run_once_preview 边界。"
                    "thin_governed_loop_preview：Stage 3-6 薄治理闭环只读预览，"
                    "可接收 external taskbook / execution envelope / local receipt / review feedback 对象，"
                    "draft 模式会直接返回 M0-M2 本地 Codex 可执行包 codex_execution_packet，"
                    "不产生执行、ReviewDecision、GateEvent 或 Delivery State 变更。"
                    "支持 workflow：auto_preview、project_status、source_onboarding、plan_update、"
                    "small_project_patch、docs_update、git_commit、git_restore_file、git_revert、git_undo_version、agent_dispatch、prompt_to_plan、thin_governed_loop_preview。"
                    "不执行 executor，不自动 commit，写入类默认停 preview。"
                    "commit 只确认已有受控预览(preview_id)，不执行任意 shell，不 git add .，不绕过 preview。"
                    "没有匹配的 stored preview_id 不能创建 commit。"
                    "git_revert 不自动 commit。"
                    "scope 按 workflow/phase 动态映射。"
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "workflow": {
                            "type": "string",
                            "enum": [
                                "auto_preview", "project_status", "source_onboarding",
                                "plan_update", "small_project_patch", "docs_update",
                                "git_commit", "git_restore_file", "git_revert", "git_undo_version",
                                "agent_dispatch", "prompt_to_plan", "thin_governed_loop_preview",
                            ],
                            "description": "要执行的工作流。auto_preview 是 v1.75 首选高层入口，自动分析 goal 并选择 bounded workflow。prompt_to_plan 是 v1.84.58 prompt 文件到 plan apply 链路入口。thin_governed_loop_preview 是 Stage 3-6 只读薄治理闭环预览。",
                        },
                        "phase": {
                            "type": "string",
                            "enum": ["inspect", "preview", "apply", "plan_preview", "plan_apply", "apply_all", "run_preview", "run", "commit", "status"],
                            "description": "工作流阶段。inspect/read/status 只读；preview/run_preview/plan_preview 只生成预览；apply/commit/run/plan_apply/apply_all 只确认受控预览ID，不执行任意 git 命令。prompt_to_plan 推荐主流程：preview → apply_all → run_preview → run。旧 phase apply/plan_preview/plan_apply 仍保留兼容。apply_all 一键完成 prompt 保存 + plan 登记。run_preview 生成执行器运行预览，不运行执行器。run 使用 run_preview 返回的 preview_id 执行一次执行器。",
                        },
                        "preview_id": {
                            "type": "string",
                            "description": "apply/commit/run 阶段必填。prompt_to_plan apply_all 使用 prompt preview_id（来自 prompt_to_plan preview）；prompt_to_plan run 使用 executor run_once_preview 返回的 preview_id。没有匹配的 stored preview 不执行任何写入或提交。不能用 preview_id 绕过安全检查。",
                        },
                        "patch_id": {
                            "type": "string",
                            "description": "agent_dispatch apply 可选，prompt_to_plan plan_apply 使用 patch_id。apply_all 内部生成并使用 patch_id，但用户不传 patch_id。",
                        },
                        "commit": {
                            "type": "string",
                            "description": "撤销目标 commit ref。git_undo_version preview 阶段必填，其他 workflow 可选。",
                        },
                        "file": {
                            "type": "string",
                            "description": "要恢复的文件路径。git_undo_version 可选，恢复单文件时使用。",
                        },
                        "reason": {
                            "type": "string",
                            "description": "操作理由，进入 workflow record。",
                        },
                        "max_chars": {
                            "type": "integer",
                            "description": "输出字符限制。",
                        },
                        "max_files": {
                            "type": "integer",
                            "description": "最大文件数。",
                        },
                        "include_diff_summary": {
                            "type": "boolean",
                            "description": "是否包含 diff 摘要。",
                        },
                        "max_diff_chars": {
                            "type": "integer",
                            "description": "最大 diff 字符数。",
                        },
                        "project_name": {
                            "type": "string",
                            "description": "可选。service mode 下项目级 workflow 必须传入已登记 managed project_name。project_status inspect、plan_update、prompt_to_plan、small_project_patch、thin_governed_loop_preview 支持按 project_name 路由。source-onboarding 仍将该字段用作 onboarding 项目名称。",
                        },
                        "goal": {
                            "type": "string",
                            "description": "source_onboarding 项目目标。",
                        },
                        "provider": {
                            "type": "string",
                            "enum": ["pi", "codex", "opencode"],
                            "description": "auto_preview 可选。执行器 provider，用于 executor preflight 和 continuation 决策。",
                        },
                        "first_version": {
                            "type": "string",
                            "description": "source_onboarding 首版本号。",
                        },
                        "first_version_name": {
                            "type": "string",
                            "description": "source_onboarding 首版本显示名称。",
                        },
                        "dry_run": {
                            "type": "boolean",
                            "description": "source_onboarding 是否 dry_run。",
                        },
                        "mode": {
                            "type": "string",
                            "enum": ["repair", "extend"],
                            "description": "plan_update 模式。",
                        },
                        "version": {
                            "type": "string",
                            "description": "plan_update 版本号。",
                        },
                        "target_version": {
                            "type": "string",
                            "description": "plan_update 目标版本号（repair）。",
                        },
                        "insert_after": {
                            "type": "string",
                            "description": "plan_update extend 插入位置。",
                        },
                        "name": {
                            "type": "string",
                            "description": "plan_update extend 版本名称。",
                        },
                        "description": {
                            "type": "string",
                            "description": "plan_update extend 版本描述。",
                        },
                        "prompt": {
                            "type": "string",
                            "description": "plan_update extend 版本 prompt。",
                        },
                        "user_request": {
                            "type": "string",
                            "description": "agent_dispatch preview 或 plan_update extend preview 的用户需求文本。",
                        },
                        "allowed_files": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "agent_dispatch preview 或 plan_update extend preview 的显式 allowed_files。",
                        },
                        "forbidden_files": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "agent_dispatch preview 或 plan_update extend preview 的显式 forbidden_files。",
                        },
                        "acceptance_commands": {
                            "type": "array",
                            "items": {
                                "oneOf": [
                                    {"type": "string"},
                                    {
                                        "type": "object",
                                        "properties": {
                                            "command": {"type": "string"},
                                            "timeout_seconds": {"type": "integer"},
                                            "continue_on_failure": {"type": "boolean"},
                                        },
                                        "required": ["command"],
                                        "additionalProperties": True,
                                    },
                                ],
                            },
                            "description": "agent_dispatch preview 或 plan_update extend preview 的显式 acceptance_commands。",
                        },
                        "manual_acceptance": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "agent_dispatch preview 或 plan_update extend preview 的显式 manual_acceptance。",
                        },
                        "out_of_scope": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "agent_dispatch preview 或 plan_update extend preview 的显式 out_of_scope。",
                        },
                        "context_files": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "agent_dispatch preview 或 plan_update extend preview 的显式 context_files。",
                        },
                        "repair_kinds": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "plan_update repair 指定修复类型。",
                        },
                        "file": {
                            "type": "string",
                            "description": "small_project_patch / git_restore_file 文件路径。",
                        },
                        "old_text": {
                            "type": "string",
                            "description": "small_project_patch 旧文本。",
                        },
                        "new_text": {
                            "type": "string",
                            "description": "small_project_patch 新文本。",
                        },
                        "patch_text": {
                            "type": "string",
                            "description": "small_project_patch unified diff 文本。",
                        },
                        "docs_action": {
                            "type": "string",
                            "enum": ["index", "search", "read_section", "update_section_preview", "append_section_preview", "sync_docs_preview", "apply"],
                            "description": "docs_update 动作。",
                        },
                        "heading": {
                            "type": "string",
                            "description": "docs_update 文档 heading。",
                        },
                        "query": {
                            "type": "string",
                            "description": "docs_update 搜索关键词。",
                        },
                        "section_heading": {
                            "type": "string",
                            "description": "docs_update 新 section heading。",
                        },
                        "new_content": {
                            "type": "string",
                            "description": "docs_update 更新后的 section 内容。",
                        },
                        "section_content": {
                            "type": "string",
                            "description": "docs_update 新 section 内容。",
                        },
                        "after_heading": {
                            "type": "string",
                            "description": "docs_update 指定追加位置。",
                        },
                        "stale_terms": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "docs_update 过时术语列表。",
                        },
                        "message": {
                            "type": "string",
                            "description": "git_commit commit message。",
                        },
                        "style": {
                            "type": "string",
                            "enum": ["conventional", "runner_version", "concise"],
                            "description": "git_commit commit message 风格。",
                        },
                        "scope_hint": {
                            "type": "string",
                            "description": "git_commit 版本号或 scope 提示。",
                        },
                        "commit": {
                            "type": "string",
                            "description": "git_restore_file / git_revert commit ref。",
                        },
                        "content": {
                            "type": "string",
                            "description": "prompt_to_plan preview 必填。prompt 文本内容。",
                        },
                        "overwrite": {
                            "type": "boolean",
                            "description": "prompt_to_plan preview 可选。是否覆盖已存在的 prompt 文件。默认 false。",
                        },
                        "prompt_file": {
                            "type": "string",
                            "description": "prompt_to_plan plan_preview 必填。prompt 文件名，例如 v1.84.58.md。只接受文件名，不接受路径。",
                        },
                        "input_mode": {
                            "type": "string",
                            "enum": ["example", "template", "draft", "provided"],
                            "description": "thin_governed_loop_preview 可选。example 使用内置样例；template 只返回真实输入契约和最小请求形状；draft 生成可编辑的四对象输入包但不执行闭环；provided 要求同时提供 external_taskbook_claim、execution_envelope、local_execution_receipt、review_feedback。",
                        },
                        "thin_loop_inputs": {
                            "type": "object",
                            "description": "thin_governed_loop_preview 可选。真实输入对象包；可包含 external_taskbook_claim、execution_envelope、local_execution_receipt、review_feedback、current_head；draft 模式也可在此携带 draft_seed。",
                            "additionalProperties": True,
                        },
                        "draft_seed": {
                            "type": "object",
                            "description": "thin_governed_loop_preview draft 模式可选。用少量上游字段生成四对象输入包和 Codex 可执行包，例如 goal/objective、task_tier、allowed_files、forbidden_files、context_files、validation_commands、allowed_commands、review_decision_value、reviewer_notes。",
                            "additionalProperties": True,
                        },
                        "external_taskbook_claim": {
                            "type": "object",
                            "description": "thin_governed_loop_preview provided 模式必填。外部任务书声明对象，作为 bounded claim 验证。",
                            "additionalProperties": True,
                        },
                        "execution_envelope": {
                            "type": "object",
                            "description": "thin_governed_loop_preview provided 模式必填。受控执行 envelope 对象。",
                            "additionalProperties": True,
                        },
                        "local_execution_receipt": {
                            "type": "object",
                            "description": "thin_governed_loop_preview provided 模式必填。本地执行 receipt 对象。",
                            "additionalProperties": True,
                        },
                        "review_feedback": {
                            "type": "object",
                            "description": "thin_governed_loop_preview provided 模式必填。审查反馈对象。",
                            "additionalProperties": True,
                        },
                        "current_head": {
                            "type": "string",
                            "description": "thin_governed_loop_preview 可选。用于 evidence preview 的 HEAD 绑定；不传时读取当前 checkout HEAD。",
                        },
                    },
                    "required": ["workflow"],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
            ),
            MCPToolDef(
                name="manage_executor_config",
                description=(
                    f"[{self.project_hint}] 受控执行器配置管理工具。支持 action："
                    "inspect_inventory（只读，返回安全的 inventory 摘要，不暴露 token/api_key/Bearer/secret）；"
                    "probe_models_preview（生成 preview_id，不探测执行器）；"
                    "probe_models_apply（基于 preview_id 执行受控探测，执行 probe_executor_inventory，"
                    "验证 project_root/expiry/provider 一致性）；"
                    "set_default_profile_preview / set_default_profile_apply（受控设置项目本地 executor profile）。"
                    "provider 可选，必须是 codex、opencode 或 pi；model/reasoning_effort 仅用于 profile 设置。"
                    "不执行任意 shell 命令，不写 token，不安装模型，不修改登录态。"
                    "scope：inspect_inventory=mcp:read，probe_models_preview/set_default_profile_preview=mcp:preview，"
                    "probe_models_apply/set_default_profile_apply=mcp:commit。"
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": [
                                "inspect_inventory",
                                "probe_models_preview",
                                "probe_models_apply",
                                "set_default_profile_preview",
                                "set_default_profile_apply",
                            ],
                            "description": "执行器配置管理 action。",
                        },
                        "provider": {
                            "type": "string",
                            "enum": ["codex", "opencode", "pi"],
                            "description": "可选。执行器 provider 过滤或 profile provider。不传时返回所有 provider。",
                        },
                        "model": {
                            "type": "string",
                            "description": "set_default_profile_preview 可选。项目本地 executor profile 的模型名，例如 opencode/deepseek-v4-flash-free。",
                        },
                        "reasoning_effort": {
                            "type": "string",
                            "description": "set_default_profile_preview 可选。项目本地 executor profile 的 reasoning effort。",
                        },
                        "preview_id": {
                            "type": "string",
                            "description": "probe_models_apply 或 set_default_profile_apply 必填。来自对应 preview 的 preview_id。",
                        },
                        "project_name": {
                            "type": "string",
                            "description": "可选。按已登记 managed project_name 路由项目本地 executor profile 和受控 preview/apply。",
                        },
                    },
                    "required": ["action"],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
            ),
            MCPToolDef(
                name="manage_executor_workflow",
                description=(
                    f"[{self.project_hint}] 受控执行器工作流工具。支持以下 action："
                    "preflight（只读预检，检查项目与执行器就绪状态）；"
                    "run_once_preview（生成 preview_id，不执行执行器）；"
                    "run_once（异步执行，需要来自 run_once_preview 的 preview_id。快速返回 started/running 状态，后台执行。完成后通过 status run_id 或 preview_id 轮询获取结果。不循环，不自动修复，不自动提交）；"
                    "run_bounded_preview（只做预检并生成 bounded loop preview，不执行执行器）；"
                    "run_bounded（基于 run_bounded_preview 的 preview_id 执行 bounded loop，受 max_iterations 限制）；"
                    "get_audit_package（读取执行审计包的轻量摘要与lineage）；"
                    "refresh_audit_package（按 version 生成新的版本审计包 refresh 快照）；"
                    "recheck_report_preview（只读重审旧 report 的 scope 结论，生成状态刷新 preview）；"
                    "recheck_report_apply（基于 recheck_report_preview 的 preview_id 刷新目标 version 的 state 状态）；"
                    "manual_fix_prompt_preview（为当前 blocked/failure 版本生成手动修复提示词准备 preview）；"
                    "manual_fix_prompt_apply（基于 manual_fix_prompt_preview 的 preview_id 写入 current-fix-prompt.md 并把当前版本置为 FIX_PROMPT_READY）；"
                    "manual_validation_preview（基于已通过的 manage_validation_run 记录生成手动验收通过 state 刷新 preview）；"
                    "manual_validation_apply（基于 manual_validation_preview 的 preview_id 登记手动/等价验收通过，不改 executor report）；"
                    "scope_mismatch_preview（只读输出授权范围与实际 changed_files 的通用差异诊断，生成 resolution preview，不改 state/report/audit/Git）；"
                    "scope_mismatch_apply（基于 scope_mismatch_preview 的 preview_id 执行受控 resolution 状态落盘，不改 report/Git）；"
                    "state_lineage_reconciliation_preview（基于人工受控完成证据生成 Runner state lineage 对账 preview）；"
                    "state_lineage_reconciliation_apply（基于 state_lineage_reconciliation_preview 的 preview_id 受控写入 state lineage 对账结果）；"
                    "final_version_closeout_preview（基于最后一个版本的人工 closeout 证据生成 Runner state 完成 preview）；"
                    "final_version_closeout_apply（基于 final_version_closeout_preview 的 preview_id 受控写入最后一个版本完成状态）；"
                    "reconcile_orphaned_claims_preview（只读扫描 RUNNING claim 并生成失联 claim reconcile preview，不改 runtime）；"
                    "reconcile_orphaned_claims_apply（基于 reconcile_orphaned_claims_preview 的 preview_id 受控终结仍失联的 RUNNING claim，不删除 claim，不杀进程）；"
                    "status（查看当前执行器会话状态）。"
                    "此工具遵循单项预览/应用审批模式。"
                    "project_root 可选，缺省使用 MCP 绑定项目，仅用于显式覆盖。"
                    "run_bounded 默认 max_iterations=1，最大 3；max_iterations>1 需要 trusted_mode=true。"
                    "不支持无限循环。allow_fix=false 时不执行 fix；allow_fix=true 只允许已有 FIX_PROMPT_READY。"
                    "allow_commit 不会执行 commit，只能停在 commit preview/next_action 边界。"
                    "run_once/run_bounded 不执行任意 git reset/clean/stash/merge/rebase/push，不创建或切换分支。"
                    "status 使用按 profile 分级的有界轮询契约：web_gpt_commander 默认短轮询，local_codex_commander 可更长时间跟进。支持 preview_id/run_id/profile_id 查询。"
                    "project_name 支持已登记 managed 项目的所有 action。"
                    "scope：preflight/status/get_audit_package=mcp:read，run_once_preview/run_bounded_preview/recheck_report_preview/manual_fix_prompt_preview/manual_validation_preview/scope_mismatch_preview/state_lineage_reconciliation_preview/final_version_closeout_preview/reconcile_orphaned_claims_preview=mcp:preview，run_once/run_bounded/refresh_audit_package/recheck_report_apply/manual_fix_prompt_apply/manual_validation_apply/scope_mismatch_apply/state_lineage_reconciliation_apply/final_version_closeout_apply/reconcile_orphaned_claims_apply=mcp:commit。"
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["preflight", "run_once_preview", "run_once", "run_bounded_preview", "run_bounded", "get_audit_package", "refresh_audit_package", "recheck_report_preview", "recheck_report_apply", "manual_fix_prompt_preview", "manual_fix_prompt_apply", "manual_validation_preview", "manual_validation_apply", "scope_mismatch_preview", "scope_mismatch_apply", "state_lineage_reconciliation_preview", "state_lineage_reconciliation_apply", "final_version_closeout_preview", "final_version_closeout_apply", "reconcile_orphaned_claims_preview", "reconcile_orphaned_claims_apply", "status"], "description": "执行器工作流操作。"},
                        "project_name": {"type": "string", "description": "可选。按已登记 managed project_name 路由 preflight、run_once_preview、run_once、status。"},
                        "project_root": {"type": "string", "description": "可选。项目根目录路径；不传时使用 MCP 绑定项目。"},
                        "provider": {"type": "string", "enum": ["pi", "codex", "opencode"], "description": "执行器 provider。默认 codex。"},
                        "model": {"type": "string", "description": "run_once_preview/run_once 可选。显式指定本次执行器模型；run_once 必须与对应 preview 中记录的 model 一致。"},
                        "execution_mode": {"type": "string", "enum": ["run", "fix"], "description": "执行模式。run 为正常执行，fix 仅当当前状态为 FIX_PROMPT_READY 时可用。默认 run。"},
                        "preview_id": {"type": "string", "description": "run_once/run_bounded/recheck_report_apply/manual_fix_prompt_apply/manual_validation_apply/scope_mismatch_apply/state_lineage_reconciliation_apply/final_version_closeout_apply/reconcile_orphaned_claims_apply 必填；status 可选。来自对应 preview 的 preview_id。"},
                        "manual_fix_prompt": {"type": "string", "description": "manual_fix_prompt_preview 必填。用户提供的手动修复提示词内容。"},
                        "validation_run_id": {"type": "string", "description": "manual_validation_preview 必填。来自 manage_validation_run run/status 的 validation run ID。"},
                        "resolution": {"type": "string", "enum": ["refresh_in_scope_state", "record_direct_manual_review", "abort_version"], "description": "scope_mismatch_apply 必填。resolution 选项。"},
                        "expected_head": {"type": "string", "description": "state_lineage_reconciliation_preview 必填。期望当前 Git HEAD。"},
                        "expected_branch": {"type": "string", "description": "state_lineage_reconciliation_preview 可选。期望当前分支。"},
                        "target_next_version": {"type": "string", "description": "state_lineage_reconciliation_preview 必填。对账后应成为当前可运行版本的 version。"},
                        "target_version": {"type": "string", "description": "final_version_closeout_preview 必填。要完成 closeout 的最后一个 plan version。"},
                        "accepted_commit": {"type": "string", "description": "final_version_closeout_preview 必填。最后一个版本对应的完整 commit hash。"},
                        "accepted_commit_subject": {"type": "string", "description": "final_version_closeout_preview 必填。accepted_commit 在本地 Git history 中的 subject。"},
                        "commit_files": {"type": "array", "items": {"type": "string"}, "description": "final_version_closeout_preview 可选。记录到版本 runtime 的 commit file 摘要。"},
                        "evidence_refs": {"type": "array", "items": {"type": "string"}, "description": "final_version_closeout_preview 可选。closeout evidence 引用；path:/file:/.colameta/ 开头的本地路径会校验存在。"},
                        "evidence_summary": {"type": "string", "description": "final_version_closeout_preview 可选。当 evidence_refs 不足时提供 closeout evidence 摘要。"},
                        "bindings": {
                            "type": "array",
                            "description": "state_lineage_reconciliation_preview 必填。版本对账绑定列表。",
                            "items": {
                                "type": "object",
                                "additionalProperties": True,
                                "properties": {
                                    "version": {"type": "string"},
                                    "target_status": {"type": "string"},
                                    "accepted_commit": {"type": "string"},
                                    "accepted_commit_subject": {"type": "string"},
                                    "commit_files": {"type": "array", "items": {"type": "string"}},
                                    "evidence_refs": {"type": "array", "items": {"type": "string"}},
                                    "evidence_summary": {"type": "string"},
                                    "reason": {"type": "string"},
                                },
                            },
                        },
                        "run_id": {"type": "string", "description": "status 可选。执行器运行 ID。"},
                        "profile_id": {"type": "string", "enum": ["web_gpt_commander", "local_codex_commander", "planner_agent", "reviewer_agent", "source_observer"], "description": "status/run_once 可选。用于选择 polling guidance。默认 web_gpt_commander；local_codex_commander 使用更长的本地有界轮询窗口。"},
                        "poll_attempt": {"type": "integer", "description": "status 可选。轮询次数。默认 1；最大建议由 polling_guidance.max_poll_attempts 按 profile 返回。"},
                        "max_diff_chars": {"type": "integer", "default": 40000, "minimum": 1, "maximum": 80000, "description": "run_once 可选。diff 输出字符限制。默认 40000，最大 80000。"},
                        "include_diff_summary": {"type": "boolean", "default": True, "description": "run_once 可选。是否返回 diff_summary。默认 true。"},
                        "include_report_markdown": {"type": "boolean", "default": False, "description": "run_once 可选。是否返回报告 markdown。默认 false。"},
                        "max_report_chars": {"type": "integer", "default": 30000, "minimum": 1, "maximum": 60000, "description": "run_once 可选。报告 markdown 最大字符数。默认 30000，最大 60000。"},
                        "executor_session_mode": {"type": "string", "enum": ["auto", "resume_existing", "start_new"], "default": "auto", "description": "run_once 可选。执行器会话模式：auto（默认）使用自动续接决策；resume_existing 要求续接现有会话；start_new 启动新会话。默认 auto。"},
                        "reason": {"type": "string", "description": "可选。执行理由说明。"},
                        "max_iterations": {"type": "integer", "default": 1, "minimum": 1, "maximum": 3, "description": "run_bounded 可选。循环轮数，默认 1，最小 1，最大 3。"},
                        "trusted_mode": {"type": "boolean", "default": False, "description": "run_bounded 可选。仅 trusted_mode=true 时允许 max_iterations>1。默认 false。"},
                        "stop_on_acceptance_failure": {"type": "boolean", "default": True, "description": "run_bounded 可选。是否在验收失败时停止。默认 true。"},
                        "stop_on_scope_violation": {"type": "boolean", "default": True, "description": "run_bounded 可选。是否在 scope violation 时停止。默认 true。"},
                        "stop_on_diff_too_large": {"type": "boolean", "default": True, "description": "run_bounded 可选。是否在 diff 超阈值时停止。默认 true。"},
                        "max_total_diff_chars": {"type": "integer", "default": 80000, "minimum": 1, "maximum": 200000, "description": "run_bounded 可选。总 diff 字符阈值，默认 80000，最大 200000。"},
                        "allow_fix": {"type": "boolean", "default": False, "description": "run_bounded 可选。默认 false；仅已有 FIX_PROMPT_READY 时允许 fix 轮。"},
                        "allow_commit": {"type": "boolean", "default": False, "description": "run_bounded 可选。默认 false；即使 true 也不会自动 commit。"},
                        "latest": {"type": "boolean", "default": True, "description": "get_audit_package 可选。默认 true。"},
                        "report_id": {"type": "string", "description": "get_audit_package/recheck_report_preview/scope_mismatch_preview 可选。指定 report_id。"},
                        "version": {"type": "string", "description": "get_audit_package/recheck_report_preview/manual_fix_prompt_preview/manual_validation_preview/scope_mismatch_preview/refresh_audit_package 可选。指定 version。"},
                        "section": {"type": "string", "enum": ["summary", "lineage", "validation", "scope", "report_excerpt"], "description": "get_audit_package 可选。默认 summary。"},
                        "include_markdown": {"type": "boolean", "default": False, "description": "get_audit_package 可选。section=report_excerpt 时是否返回 markdown 片段。"},
                        "max_chars": {"type": "integer", "default": 20000, "minimum": 1, "maximum": 60000, "description": "get_audit_package 可选。返回字符上限。"},
                    },
                    "required": ["action"],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
            ),
            MCPToolDef(
                name="manage_validation_run",
                description=(
                    f"[{self.project_hint}] 通用受控验证运行工具。"
                    "GPTs 只提供 scope/target_files；Runner 本地选择验证策略。"
                    "inspect/status 只读；preview 生成固定 argv，不运行命令；run 只执行 preview 固化命令，shell=False，输出脱敏截断。"
                    "scope：inspect/status=mcp:read，preview=mcp:preview，run=mcp:commit。"
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["inspect", "preview", "run", "status"],
                            "description": "验证动作。inspect/status 只读；preview 生成固定验证命令；run 使用 preview_id 执行一次。",
                        },
                        "scope": {
                            "type": "string",
                            "enum": ["changed_files", "target_files", "current_version", "full"],
                            "description": "验证范围。默认 changed_files；target_files 使用 target_files；current_version/full 优先运行当前版本 acceptance_commands。",
                        },
                        "target_files": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "可选目标文件列表。只接受项目内相对路径。",
                        },
                        "preview_id": {
                            "type": "string",
                            "description": "run 必填。来自 preview 的 preview_id。",
                        },
                        "run_id": {
                            "type": "string",
                            "description": "status 必填。验证运行 ID。",
                        },
                        "project_name": {
                            "type": "string",
                            "description": "可选。按已登记 managed project_name 路由所有操作。",
                        },
                    },
                    "required": ["action"],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
            ),
            MCPToolDef(
                name="list_workflow_runs",
                description=f"[{self.project_hint}] 列出 workflow run records。每次受控 MCP 操作（analyze_project_state、manage_plan_version insert/update/repair preview、manage_project_patch preview/apply、manage_git_history restore/preview/revert、manage_git_commit preview/commit、run_mcp_workflow、manage_executor_workflow）会自动生成 workflow record。返回摘要列表，不包含完整 steps。scope=mcp:read。",
                input_schema={
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "description": "最大返回条数。默认 20，最大 100。",
                        },
                        "workflow_name": {
                            "type": "string",
                            "description": "按 workflow_name 筛选。",
                        },
                        "status": {
                            "type": "string",
                            "description": "按 status 筛选（running/succeeded/failed/partial/unsupported）。",
                        },
                        "project_name": {
                            "type": "string",
                            "description": "可选。按已登记 managed project_name 路由读取目标项目 workflow records。",
                        },
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
            ),
            MCPToolDef(
                name="get_workflow_run",
                description=f"[{self.project_hint}] 查看单个 workflow run record 详情。返回完整 workflow record，包含 steps 数组。scope=mcp:read。",
                input_schema={
                    "type": "object",
                    "properties": {
                        "workflow_id": {
                            "type": "string",
                            "description": "workflow_id。",
                        },
                        "project_name": {
                            "type": "string",
                            "description": "可选。按已登记 managed project_name 路由读取目标项目 workflow record。",
                        },
                    },
                    "required": ["workflow_id"],
                    "additionalProperties": False,
                },
                output_schema=common_output_schema,
            ),
        ]

    def validate_project(self, mode: str | None = None) -> None:
        if not os.path.isdir(self.project_root):
            raise PlanningBridgeError(f"项目目录不存在：{self.project_root}")
        if mode == "source-only":
            return
        runner_dir = resolve_project_runner_dir(self.project_root)
        plan_file = os.path.join(runner_dir, "plan.json")
        state_file = os.path.join(runner_dir, "state.json")
        if mode == "managed":
            if not os.path.exists(plan_file):
                raise PlanningBridgeError(
                    "当前项目尚未纳入 Runner 管理；后续版本会支持 managed 自动最小纳管。当前可先使用 source-only 模式启动 MCP，或通过 manage_runner_plan 完成纳管。"
                )
            return
        if os.path.exists(plan_file) and os.path.exists(state_file):
            return
        git_dir = os.path.join(self.project_root, ".git")
        if os.path.isdir(git_dir):
            return
        raise PlanningBridgeError(f"缺少计划文件或 Git 仓库：{plan_file}")

    def serve_stdio(self) -> int:
        self._log(f"MCP Planning Bridge server started, project={self.project_root}")
        for raw_line in sys.stdin:
            line = raw_line.strip()
            if not line:
                continue
            response = self._handle_line_stdio(line)
            if response is None:
                continue
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()
        self._log("MCP Planning Bridge server stopped")
        return 0

    def serve_http(
        self,
        host: str = "127.0.0.1",
        port: int = 8765,
        auth_token: str | None = None,
        auth_mode: str | None = None,
        public_base_url: str | None = None,
        oauth_token_ttl_seconds: int = 3600,
        oauth_issuer: str | None = None,
        oauth_jwks_url: str | None = None,
        oauth_audience: str | None = None,
        oauth_scopes: str | list[str] | tuple[str, ...] | None = None,
        oauth_algorithms: str | list[str] | tuple[str, ...] | None = None,
        oauth_token_leeway_seconds: int = 60,
        debug_actions: bool = False,
    ) -> int:
        server = self
        _debug_counter = 0
        resolved_auth_mode = auth_mode or ("token" if auth_token else "none")
        if resolved_auth_mode not in {"none", "token", "oauth", "external-oauth"}:
            raise PlanningBridgeError(f"auth_mode 无效：{resolved_auth_mode}")
        if resolved_auth_mode == "token" and not auth_token:
            raise PlanningBridgeError("token auth mode requires auth_token.")
        normalized_public_base_url = public_base_url.rstrip("/") if public_base_url else None
        oauth_provider: MCPOAuthProvider | None = None
        external_oauth_provider: ExternalOAuthProvider | None = None
        if resolved_auth_mode == "oauth":
            if not normalized_public_base_url:
                raise PlanningBridgeError("oauth auth mode requires public_base_url.")
            oauth_provider = MCPOAuthProvider(
                self.project_root,
                normalized_public_base_url,
                token_ttl_seconds=oauth_token_ttl_seconds,
            )
        elif resolved_auth_mode == "external-oauth":
            if not normalized_public_base_url:
                raise PlanningBridgeError("external-oauth auth mode requires public_base_url.")
            if not isinstance(oauth_issuer, str) or not oauth_issuer.strip():
                raise PlanningBridgeError("external-oauth auth mode requires oauth_issuer.")
            if not isinstance(oauth_jwks_url, str) or not oauth_jwks_url.strip():
                raise PlanningBridgeError("external-oauth auth mode requires oauth_jwks_url.")
            external_oauth_provider = ExternalOAuthProvider(
                ExternalOAuthConfig(
                    public_base_url=normalized_public_base_url,
                    issuer=oauth_issuer,
                    jwks_url=oauth_jwks_url,
                    audience=oauth_audience,
                    scopes=oauth_scopes,  # type: ignore[arg-type]
                    algorithms=oauth_algorithms,  # type: ignore[arg-type]
                    token_leeway_seconds=oauth_token_leeway_seconds,
                )
            )
        resource_oauth_provider = external_oauth_provider or oauth_provider
        rate_limiter = _MCPRateLimiter(
            global_per_minute=MCP_GLOBAL_RATE_LIMIT_PER_MINUTE,
            global_burst=MCP_GLOBAL_RATE_LIMIT_BURST,
            client_per_minute=MCP_CLIENT_RATE_LIMIT_PER_MINUTE,
            client_burst=MCP_CLIENT_RATE_LIMIT_BURST,
        )

        def _debug_log(handler: BaseHTTPRequestHandler, status_code: int, response_payload: dict[str, Any] | None = None) -> None:
            if not debug_actions:
                return
            nonlocal _debug_counter
            _debug_counter += 1
            start = getattr(handler, "_debug_start", 0.0)
            duration_ms = int((time.time() - start) * 1000) if start else 0
            request_id = getattr(handler, "_debug_request_id", f"d{_debug_counter}")
            method = getattr(handler, "_debug_method", "?")
            path = getattr(handler, "_debug_path", "?")
            tool_name = getattr(handler, "_debug_tool_name", "")
            body_keys = getattr(handler, "_debug_body_keys", None)
            body_parse_error = getattr(handler, "_debug_body_parse_error", False)
            auth_header = handler.headers.get("Authorization", "")
            has_auth = bool(auth_header)
            if auth_header.startswith("Bearer "):
                auth_scheme = "Bearer"
                auth_len = len(auth_header) - 7
            elif auth_header.startswith("Basic "):
                auth_scheme = "Basic"
                auth_len = len(auth_header) - 6
            elif has_auth:
                auth_scheme = "Other"
                auth_len = 0
            else:
                auth_scheme = "Missing"
                auth_len = 0
            content_type = handler.headers.get("Content-Type", "") or "-"
            ua = handler.headers.get("User-Agent", "") or "-"
            ua_summary = ua[:60]
            if body_keys is None:
                body_keys_list: list[str] = []
            else:
                body_keys_list = body_keys
            body_keys_str = ",".join(body_keys_list) if body_keys_list else "-"
            response_ok: Any = None
            response_error_code: Any = None
            if response_payload:
                if "result" in response_payload:
                    r = response_payload.get("result", {})
                    if isinstance(r, dict):
                        response_ok = r.get("ok")
                        response_error_code = r.get("error_code")
                elif "error" in response_payload:
                    response_ok = False
                    err = response_payload.get("error", {})
                    if isinstance(err, dict):
                        response_error_code = err.get("data", {}).get("error_code", err.get("code"))
                else:
                    response_ok = response_payload.get("ok")
                    response_error_code = response_payload.get("error_code")
            parts = [
                "[actions-debug]",
                f"request_id={request_id}",
                f"method={method}",
                f"path={path}",
            ]
            if tool_name:
                parts.append(f"tool_name={tool_name}")
            parts.extend([
                f"status_code={status_code}",
                f"duration_ms={duration_ms}",
                f"auth_mode={resolved_auth_mode}",
                f"has_authorization={'true' if has_auth else 'false'}",
                f"authorization_scheme={auth_scheme}",
                f"authorization_length={auth_len}",
                f"content_type={content_type}",
                f"user_agent_summary={ua_summary}",
                f"body_keys={body_keys_str}",
            ])
            if body_parse_error:
                parts.append("body_parse_error=true")
            parts.append(f"response_ok={response_ok}" if response_ok is not None else "response_ok=-")
            parts.append(f"response_error_code={response_error_code}" if response_error_code is not None else "response_error_code=-")
            sys.stderr.write(" ".join(parts) + "\n")
            sys.stderr.flush()

        class MCPHTTPRequestHandler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:
                server._log(f"{self.address_string()} - {format % args}")

            def _request_id(self) -> str:
                request_id = getattr(self, "_debug_request_id", "")
                if not request_id:
                    request_id = os.urandom(8).hex()
                    self._debug_request_id = request_id
                return str(request_id)

            def _rate_limit_client_id(self, method: str, path: str) -> str:
                authorization = self.headers.get("Authorization", "")
                if authorization.startswith("Bearer "):
                    token = authorization[len("Bearer ") :].strip()
                    if token:
                        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
                        return f"bearer:{digest}"
                source_ip = "unknown"
                if isinstance(self.client_address, tuple) and self.client_address:
                    source_ip = str(self.client_address[0] or "unknown")
                if path == "/mcp":
                    path_bucket = "mcp"
                elif path in {
                    "/healthz",
                    "/.well-known/oauth-protected-resource",
                    "/.well-known/oauth-authorization-server",
                    "/authorize",
                    "/register",
                    "/token",
                    "/revoke",
                }:
                    path_bucket = path
                else:
                    path_bucket = "other"
                return f"anon:{source_ip}:{method}:{path_bucket}"

            def _prepare_request(self, method: str, path: str) -> bool:
                self._debug_start = time.time()
                self._debug_request_id = os.urandom(8).hex()
                self._debug_method = method
                self._debug_path = path
                self._request_body_too_large = False
                self._request_body_timed_out = False
                try:
                    self.connection.settimeout(MCP_REQUEST_TIMEOUT_SECONDS)
                except Exception:
                    pass
                client_id = self._rate_limit_client_id(method, path)
                limit_result = rate_limiter.check(client_id)
                if limit_result.get("ok") is True:
                    return True
                retry_after_seconds = int(limit_result.get("retry_after_seconds") or 1)
                self._send_json(
                    429,
                    {
                        "ok": False,
                        "error_code": "MCP_RATE_LIMITED",
                        "message": "请求过于频繁，请稍后重试。",
                        "reason_code": str(limit_result.get("reason_code") or "MCP_RATE_LIMITED"),
                        "retry_after_seconds": retry_after_seconds,
                    },
                    headers={"Retry-After": str(retry_after_seconds)},
                )
                return False

            def _payload_with_request_id(self, status_code: int, payload: dict[str, Any]) -> dict[str, Any]:
                should_attach = status_code >= 400 or payload.get("ok") is False
                if not should_attach:
                    return payload
                request_id = self._request_id()
                if isinstance(payload.get("error"), dict) and payload.get("jsonrpc") == "2.0":
                    cloned = dict(payload)
                    error = dict(cloned["error"])
                    data = error.get("data")
                    if not isinstance(data, dict):
                        data = {}
                    else:
                        data = dict(data)
                    data.setdefault("request_id", request_id)
                    error["data"] = data
                    cloned["error"] = error
                    return cloned
                cloned = dict(payload)
                cloned.setdefault("request_id", request_id)
                return cloned

            def _send_json(
                self,
                status_code: int,
                payload: dict[str, Any],
                headers: dict[str, str] | None = None,
            ) -> None:
                payload = self._payload_with_request_id(status_code, payload)
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status_code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("X-Request-Id", self._request_id())
                for key, value in (headers or {}).items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(body)
                _debug_log(self, status_code, payload)

            def _send_html(self, status_code: int, body_text: str) -> None:
                body = body_text.encode("utf-8")
                self.send_response(status_code)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("X-Request-Id", self._request_id())
                self.end_headers()
                self.wfile.write(body)

            def _send_redirect(self, location: str) -> None:
                self.send_response(302)
                self.send_header("Location", location)
                self.send_header("Content-Length", "0")
                self.send_header("X-Request-Id", self._request_id())
                self.end_headers()

            def _send_auth_error(self) -> None:
                headers: dict[str, str] = {}
                if resource_oauth_provider is not None:
                    headers["WWW-Authenticate"] = (
                        'Bearer resource_metadata="'
                        f'{resource_oauth_provider.protected_resource_metadata_url()}"'
                    )
                self._send_json(
                    401,
                    {
                        "ok": False,
                        "error_code": "UNAUTHORIZED",
                        "message": "Invalid or missing bearer token",
                    },
                    headers=headers,
                )

            def _send_request_too_large(self, *, jsonrpc: bool = False, tool_name: str = "") -> None:
                if jsonrpc:
                    self._send_json(
                        413,
                        {
                            "jsonrpc": "2.0",
                            "id": None,
                            "error": {
                                "code": -32000,
                                "message": "请求体过大，请拆分请求后重试。",
                                "data": {
                                    "error_code": "MCP_REQUEST_TOO_LARGE",
                                    "max_request_chars": MCP_HARD_REQUEST_CHARS,
                                },
                            },
                        },
                    )
                    return
                payload = {
                    "ok": False,
                    "error_code": "MCP_REQUEST_TOO_LARGE",
                    "message": "请求体过大，请拆分请求后重试。",
                    "max_request_chars": MCP_HARD_REQUEST_CHARS,
                }
                if tool_name:
                    payload["tool"] = tool_name
                self._send_json(413, payload)

            def _send_request_timeout(self, *, jsonrpc: bool = False, tool_name: str = "") -> None:
                if jsonrpc:
                    self._send_json(
                        408,
                        {
                            "jsonrpc": "2.0",
                            "id": None,
                            "error": {
                                "code": -32000,
                                "message": "读取请求体超时，请缩小请求或稍后重试。",
                                "data": {
                                    "error_code": "MCP_REQUEST_TIMEOUT",
                                    "timeout_seconds": MCP_REQUEST_TIMEOUT_SECONDS,
                                },
                            },
                        },
                    )
                    return
                payload = {
                    "ok": False,
                    "error_code": "MCP_REQUEST_TIMEOUT",
                    "message": "读取请求体超时，请缩小请求或稍后重试。",
                    "timeout_seconds": MCP_REQUEST_TIMEOUT_SECONDS,
                }
                if tool_name:
                    payload["tool"] = tool_name
                self._send_json(408, payload)

            def _body_too_large(self) -> bool:
                return bool(getattr(self, "_request_body_too_large", False))

            def _body_timed_out(self) -> bool:
                return bool(getattr(self, "_request_body_timed_out", False))

            def _auth_context(self) -> dict[str, Any] | None:
                if resolved_auth_mode == "none":
                    return {"mode": "none"}
                authorization = self.headers.get("Authorization", "")
                if resolved_auth_mode == "token":
                    if not authorization.startswith("Bearer "):
                        return None
                    token = authorization[len("Bearer ") :]
                    return {"mode": "token"} if token == auth_token else None
                if resolved_auth_mode == "oauth" and oauth_provider is not None:
                    if not authorization.startswith("Bearer "):
                        return None
                    token = authorization[len("Bearer ") :]
                    token_payload = oauth_provider.validate_token(token)
                    if token_payload is None:
                        return None
                    return {"mode": "oauth", "token": token_payload, "oauth_provider": oauth_provider}
                if resolved_auth_mode == "external-oauth" and external_oauth_provider is not None:
                    if not authorization.startswith("Bearer "):
                        return None
                    token = authorization[len("Bearer ") :]
                    token_payload = external_oauth_provider.validate_token(token)
                    if token_payload is None:
                        return None
                    return {
                        "mode": "external-oauth",
                        "token": token_payload,
                        "oauth_provider": external_oauth_provider,
                    }
                return None

            def _read_body(self) -> bytes | None:
                self._request_body_too_large = False
                self._request_body_timed_out = False
                length_value = self.headers.get("Content-Length", "0")
                try:
                    content_length = int(length_value)
                except ValueError:
                    content_length = 0
                if content_length <= 0:
                    return b""
                if content_length > MCP_HARD_REQUEST_CHARS:
                    self._request_body_too_large = True
                    return None
                try:
                    return self.rfile.read(content_length)
                except (TimeoutError, OSError):
                    self._request_body_timed_out = True
                    return None

            def _read_json_body(self) -> dict[str, Any] | None:
                raw = self._read_body()
                if raw is None:
                    return None
                if not raw:
                    return None
                try:
                    payload = json.loads(raw.decode("utf-8"))
                except Exception:
                    return None
                return payload if isinstance(payload, dict) else None

            def _read_params_body(self) -> dict[str, Any]:
                raw = self._read_body()
                if raw is None:
                    return {}
                if not raw:
                    return {}
                content_type = self.headers.get("Content-Type", "")
                if "application/json" in content_type:
                    try:
                        payload = json.loads(raw.decode("utf-8"))
                    except Exception:
                        return {}
                    return payload if isinstance(payload, dict) else {}
                try:
                    parsed = parse_qs(raw.decode("utf-8"), keep_blank_values=True)
                except Exception:
                    return {}
                return {key: values[-1] for key, values in parsed.items() if values}

            def _send_oauth_page_result(self, result: dict[str, Any]) -> None:
                kind = result.get("kind")
                if kind == "redirect":
                    self._send_redirect(str(result.get("location") or "/"))
                    return
                if kind == "html":
                    self._send_html(int(result.get("status") or 200), str(result.get("body") or ""))
                    return
                self._send_json(500, {"ok": False, "error_code": "OAUTH_RESPONSE_INVALID"})

            def _send_oauth_unavailable(self, message: str) -> None:
                if resolved_auth_mode == "external-oauth":
                    self._send_json(
                        404,
                        {
                            "ok": False,
                            "error_code": "EXTERNAL_AUTH_SERVER",
                            "message": message,
                        },
                    )
                    return
                self._send_json(404, {"ok": False, "error_code": "NOT_FOUND", "message": "OAuth 未启用。"})

            def do_GET(self) -> None:
                parsed_url = urlparse(self.path)
                path = parsed_url.path
                if not self._prepare_request("GET", path):
                    return
                if path == "/healthz":
                    try:
                        payload = {
                            "ok": True,
                            "service": "colameta-mcp",
                            "auth_mode": resolved_auth_mode,
                            **runtime_healthz_provenance(
                                server.project_root,
                                runtime_project_root=loaded_runtime_project_root(),
                            ),
                        }
                        if server.service_mode:
                            payload["routing"] = "registry"
                        else:
                            status = server.bridge.get_runner_status(server.project_root)
                            payload["project"] = server.project_root
                            payload["current_version"] = status.get("current_version")
                        self._send_json(200, payload)
                        return
                    except Exception:
                        self._send_json(
                            500,
                            {
                                "ok": False,
                                "error_code": "HEALTH_CHECK_FAILED",
                                "message": "health 检查失败。",
                            },
                        )
                        return
                if path == "/openapi.json":
                    payload = server._build_actions_openapi_schema(
                        public_base_url=normalized_public_base_url,
                        host=host,
                        port=port,
                    )
                    self._send_json(200, payload)
                    return
                if path == "/mcp":
                    payload = {
                        "ok": True,
                        "message": "MCP endpoint ready. Use POST /mcp with JSON-RPC 2.0.",
                        "auth_mode": resolved_auth_mode,
                    }
                    if resource_oauth_provider is not None:
                        payload["protected_resource_metadata"] = resource_oauth_provider.protected_resource_metadata_url()
                    self._send_json(200, payload)
                    return
                if path == "/.well-known/oauth-protected-resource":
                    if resource_oauth_provider is None:
                        self._send_json(404, {"ok": False, "error_code": "NOT_FOUND", "message": "OAuth 未启用。"})
                        return
                    self._send_json(200, resource_oauth_provider.protected_resource_metadata())
                    return
                if path == "/.well-known/oauth-authorization-server":
                    if oauth_provider is None:
                        self._send_oauth_unavailable(
                            "external-oauth 模式由外部 IdP 提供 authorization server metadata。"
                        )
                        return
                    self._send_json(200, oauth_provider.authorization_server_metadata())
                    return
                if path == "/authorize":
                    if oauth_provider is None:
                        self._send_oauth_unavailable("external-oauth 模式不在 ColaMeta 本机处理授权页面。")
                        return
                    self._send_oauth_page_result(
                        oauth_provider.authorize(parse_qs(parsed_url.query, keep_blank_values=True))
                    )
                    return
                self._send_json(
                    404,
                    {
                        "ok": False,
                        "error_code": "NOT_FOUND",
                        "message": "请求路径不存在。",
                    },
                )

            def do_POST(self) -> None:
                path = urlparse(self.path).path
                if not self._prepare_request("POST", path):
                    return
                if path == "/register":
                    if oauth_provider is None:
                        self._send_oauth_unavailable("external-oauth 模式不在 ColaMeta 本机注册 OAuth 客户端。")
                        return
                    payload = self._read_json_body()
                    if self._body_timed_out():
                        self._send_request_timeout()
                        return
                    if self._body_too_large():
                        self._send_request_too_large()
                        return
                    if payload is None:
                        self._send_json(400, {"error": "invalid_request", "error_description": "JSON body is required."})
                        return
                    status_code, response = oauth_provider.register_client(payload)
                    self._send_json(status_code, response)
                    return
                if path == "/token":
                    if oauth_provider is None:
                        self._send_oauth_unavailable("external-oauth 模式不在 ColaMeta 本机签发 token。")
                        return
                    params_body = self._read_params_body()
                    if self._body_timed_out():
                        self._send_request_timeout()
                        return
                    if self._body_too_large():
                        self._send_request_too_large()
                        return
                    status_code, response = oauth_provider.exchange_token(params_body)
                    self._send_json(status_code, response)
                    return
                if path == "/revoke":
                    if oauth_provider is None:
                        self._send_oauth_unavailable("external-oauth 模式不在 ColaMeta 本机撤销 token。")
                        return
                    params_body = self._read_params_body()
                    if self._body_timed_out():
                        self._send_request_timeout()
                        return
                    if self._body_too_large():
                        self._send_request_too_large()
                        return
                    status_code, response = oauth_provider.revoke_token(params_body)
                    self._send_json(status_code, response)
                    return
                tool_name = server._actions_tool_name_from_path(path)
                if tool_name is not None:
                    auth_context = self._auth_context()
                    if auth_context is None:
                        self._send_auth_error()
                        return
                    visible_tool_names = set(server._visible_tool_names())
                    if tool_name not in visible_tool_names:
                        self._send_json(
                            404,
                            {
                                "ok": False,
                                "error_code": "TOOL_NOT_FOUND",
                                "message": f"未知 tool：{tool_name}",
                            },
                        )
                        return
                    if debug_actions:
                        self._debug_tool_name = tool_name
                    raw = self._read_body()
                    if self._body_timed_out():
                        self._send_request_timeout(tool_name=tool_name)
                        return
                    if self._body_too_large():
                        self._send_request_too_large(tool_name=tool_name)
                        return
                    if raw is None:
                        self._send_request_too_large(tool_name=tool_name)
                        return
                    if server._is_actions_request_too_large(raw):
                        self._send_json(400, server._actions_request_too_large_payload(tool_name))
                        return
                    if not raw:
                        arguments: Any = {}
                    else:
                        try:
                            arguments = json.loads(raw.decode("utf-8"))
                        except Exception:
                            if debug_actions:
                                self._debug_body_keys = []
                                self._debug_body_parse_error = True
                            self._send_json(
                                400,
                                {
                                    "ok": False,
                                    "error_code": "INVALID_JSON",
                                    "message": "请求不是合法 JSON。",
                                },
                            )
                            return
                    if not isinstance(arguments, dict):
                        if debug_actions:
                            self._debug_body_keys = []
                            self._debug_body_parse_error = True
                        self._send_json(
                            400,
                            {
                                "ok": False,
                                "error_code": "INVALID_PARAMS",
                                "message": "tool 参数必须是 JSON 对象。",
                            },
                        )
                        return
                    if debug_actions and isinstance(arguments, dict):
                        self._debug_body_keys = list(arguments.keys())
                    tool_result = server._call_tool(tool_name, arguments, auth_context=auth_context)
                    response_payload = server._package_actions_rest_response(tool_name, arguments, tool_result)
                    self._send_json(200, response_payload)
                    return
                if path != "/mcp":
                    self._send_json(
                        404,
                        {
                            "ok": False,
                            "error_code": "NOT_FOUND",
                            "message": "请求路径不存在。",
                        },
                    )
                    return
                auth_context = self._auth_context()
                if auth_context is None:
                    self._send_auth_error()
                    return
                request = self._read_json_body()
                if self._body_timed_out():
                    self._send_request_timeout(jsonrpc=True)
                    return
                if self._body_too_large():
                    self._send_request_too_large(jsonrpc=True)
                    return
                if debug_actions:
                    if request is not None:
                        self._debug_body_keys = list(request.keys())
                        method_name = request.get("method", "")
                        if method_name in ("tools/call", "call_tool"):
                            rpc_params = request.get("params", {})
                            if isinstance(rpc_params, dict):
                                self._debug_tool_name = f"{method_name}/{rpc_params.get('name', '')}"
                            else:
                                self._debug_tool_name = method_name
                        else:
                            self._debug_tool_name = method_name
                    else:
                        self._debug_body_keys = []
                        self._debug_body_parse_error = True
                if request is None:
                    self._send_json(
                        400,
                        {
                            "jsonrpc": "2.0",
                            "id": None,
                            "error": {
                                "code": -32700,
                                "message": "请求不是合法 JSON。",
                                "data": {"error_code": "invalid_json"},
                            },
                        },
                    )
                    return
                response = server._handle_jsonrpc_request(request, auth_context=auth_context)
                if response is None:
                    self.send_response(202)
                    self.send_header("Content-Length", "0")
                    self.send_header("X-Request-Id", self._request_id())
                    self.end_headers()
                    return
                self._send_json(200, response)

        httpd = ReusableThreadingHTTPServer((host, port), MCPHTTPRequestHandler)
        self._httpd = httpd
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            self._log("MCP HTTP server interrupted")
        finally:
            httpd.shutdown()
            httpd.server_close()
            self._log("MCP HTTP server stopped")
        return 0

    def _handle_line_stdio(self, line: str) -> dict[str, Any] | None:
        try:
            request = json.loads(line)
        except Exception:
            return self._protocol_error(None, -32700, "invalid_json", "请求不是合法 JSON。")
        if not isinstance(request, dict):
            return self._protocol_error(None, -32600, "invalid_request", "请求必须是 JSON 对象。")
        return self._handle_jsonrpc_request(request)

    def _commander_widget_resource_meta(self) -> dict[str, Any]:
        return {
            "ui": {
                "prefersBorder": True,
                "csp": {
                    "connectDomains": [],
                    "resourceDomains": [],
                },
            },
            "openai/widgetDescription": (
                "ColaMeta Commander shows local service facts, connector health, "
                "profile-aware entries, preview-first workflow routes, and explicit authorization gates."
            ),
            "openai/widgetPrefersBorder": True,
            "openai/widgetCSP": {
                "connect_domains": [],
                "resource_domains": [],
            },
        }

    def _mcp_resources_list_result(self) -> dict[str, Any]:
        return {
            "resources": [
                {
                    "uri": COMMANDER_APP_WIDGET_URI,
                    "name": "colameta_commander",
                    "title": COMMANDER_APP_TITLE,
                    "description": "Read-only ColaMeta Commander panel for ChatGPT Apps.",
                    "mimeType": COMMANDER_APP_WIDGET_MIME_TYPE,
                    "_meta": self._commander_widget_resource_meta(),
                }
            ]
        }

    def _mcp_resource_read_result(self, uri: str) -> dict[str, Any]:
        return {
            "contents": [
                {
                    "uri": uri,
                    "mimeType": COMMANDER_APP_WIDGET_MIME_TYPE,
                    "text": self._commander_widget_html(),
                    "_meta": self._commander_widget_resource_meta(),
                }
            ]
        }

    def _commander_widget_html(self) -> str:
        return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    :root {
      color-scheme: light dark;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #f5f7f9;
      color: #1b1f23;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-width: 320px;
      background: #f5f7f9;
    }
    .shell {
      display: grid;
      gap: 14px;
      padding: 16px;
    }
    .top {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 12px;
      align-items: start;
    }
    h1 {
      margin: 0;
      font-size: 20px;
      line-height: 1.2;
      font-weight: 700;
      letter-spacing: 0;
    }
    .sub {
      margin-top: 4px;
      color: #5d6670;
      font-size: 13px;
      line-height: 1.35;
    }
    .badge {
      display: inline-flex;
      align-items: center;
      min-height: 28px;
      padding: 5px 9px;
      border: 1px solid #cfd8df;
      border-radius: 6px;
      background: #ffffff;
      font-size: 12px;
      font-weight: 650;
      white-space: nowrap;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 8px;
    }
    .tile {
      min-height: 74px;
      padding: 10px;
      border: 1px solid #d8e0e6;
      border-radius: 8px;
      background: #ffffff;
    }
    .label {
      color: #68727a;
      font-size: 11px;
      line-height: 1.2;
      text-transform: uppercase;
      letter-spacing: 0;
    }
    .value {
      margin-top: 7px;
      font-size: 15px;
      line-height: 1.25;
      font-weight: 650;
      overflow-wrap: anywhere;
    }
    .section {
      display: grid;
      gap: 8px;
    }
    .section h2 {
      margin: 0;
      font-size: 13px;
      line-height: 1.2;
      font-weight: 700;
      color: #333a40;
    }
    .readiness {
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
      gap: 8px;
    }
    .evidence-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
    }
    .evidence-card {
      min-height: 116px;
      padding: 10px;
      border: 1px solid #d8e0e6;
      border-radius: 8px;
      background: #ffffff;
      display: grid;
      gap: 7px;
    }
    .evidence-head {
      display: flex;
      justify-content: space-between;
      align-items: start;
      gap: 8px;
    }
    .evidence-title {
      font-size: 12px;
      line-height: 1.25;
      font-weight: 700;
      overflow-wrap: anywhere;
    }
    .evidence-path {
      color: #68727a;
      font-size: 11px;
      line-height: 1.25;
      overflow-wrap: anywhere;
    }
    .evidence-purpose {
      color: #334047;
      font-size: 12px;
      line-height: 1.35;
      overflow-wrap: anywhere;
    }
    .evidence-tags {
      display: flex;
      flex-wrap: wrap;
      gap: 5px;
    }
    .evidence-tag {
      display: inline-flex;
      align-items: center;
      min-height: 22px;
      padding: 3px 6px;
      border: 1px solid #d8e0e6;
      border-radius: 6px;
      color: #44515a;
      background: #f5f7f9;
      font-size: 11px;
      line-height: 1.2;
    }
    .evidence-copy {
      min-height: 28px;
      padding: 5px 8px;
      flex: 0 0 auto;
      font-size: 12px;
    }
    .note {
      min-height: 56px;
      padding: 10px;
      border: 1px solid #d8e0e6;
      border-radius: 8px;
      background: #ffffff;
      font-size: 12px;
      line-height: 1.35;
      color: #334047;
      overflow-wrap: anywhere;
    }
    .note strong {
      display: block;
      margin-bottom: 5px;
      font-size: 12px;
      line-height: 1.25;
      color: #243036;
    }
    .profiles {
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 8px;
    }
    .profile {
      min-height: 86px;
      padding: 9px;
      border: 1px solid #d8e0e6;
      border-radius: 8px;
      background: #ffffff;
    }
    .profile strong {
      display: block;
      font-size: 12px;
      line-height: 1.25;
      overflow-wrap: anywhere;
    }
    .profile span {
      display: block;
      margin-top: 6px;
      color: #68727a;
      font-size: 12px;
      line-height: 1.3;
    }
    .actions {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }
    .recommended-actions {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
    }
    .recommended-action {
      min-height: 112px;
      border: 1px solid #d8e0e6;
      border-radius: 8px;
      background: #ffffff;
      padding: 9px;
      display: grid;
      gap: 7px;
      align-content: start;
    }
    .recommended-action-head {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 8px;
    }
    .recommended-action-title {
      font-weight: 700;
      font-size: 12px;
      line-height: 1.25;
      overflow-wrap: anywhere;
    }
    .recommended-action-meta,
    .recommended-action-boundary {
      display: flex;
      flex-wrap: wrap;
      gap: 5px;
    }
    .action-chip {
      border: 1px solid #d8e0e6;
      border-radius: 999px;
      padding: 2px 7px;
      background: #f6f8f8;
      color: #4d5961;
      font-size: 11px;
      line-height: 1.3;
      overflow-wrap: anywhere;
    }
    .action-chip.commit {
      border-color: #dbc7a2;
      background: #fff8e8;
      color: #4d3d1f;
    }
    .action-chip.read {
      border-color: #b9d3cf;
      background: #eef8f6;
      color: #244f51;
    }
    .recommended-action-why {
      color: #68727a;
      font-size: 12px;
      line-height: 1.35;
      overflow-wrap: anywhere;
    }
    .action-run-status {
      color: #5d6670;
      font-size: 11px;
      line-height: 1.3;
      min-height: 15px;
      overflow-wrap: anywhere;
    }
    .action-refresh-queue {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 5px;
      min-height: 22px;
    }
    .action-refresh-label {
      color: #5d6670;
      font-size: 11px;
      line-height: 1.3;
    }
    .action-copy {
      min-height: 28px;
      padding: 4px 8px;
      font-size: 12px;
      flex: 0 0 auto;
    }
    .action-run,
    .action-refresh,
    .action-record {
      min-height: 28px;
      padding: 4px 8px;
      font-size: 12px;
      flex: 0 0 auto;
    }
    button {
      min-height: 34px;
      border: 1px solid #2f6f73;
      border-radius: 6px;
      padding: 7px 11px;
      background: #2f6f73;
      color: #ffffff;
      font: inherit;
      font-size: 13px;
      font-weight: 650;
      cursor: pointer;
    }
    button.secondary {
      background: #ffffff;
      color: #2f474a;
      border-color: #b9c7c4;
    }
    button:disabled {
      opacity: .55;
      cursor: default;
    }
    .boundary {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
    }
    .gate {
      min-height: 38px;
      border: 1px solid #dbc7a2;
      border-radius: 8px;
      background: #fff8e8;
      padding: 9px;
      font-size: 12px;
      line-height: 1.3;
      color: #4d3d1f;
    }
    .log {
      min-height: 34px;
      border-top: 1px solid #d8e0e6;
      padding-top: 9px;
      color: #5d6670;
      font-size: 12px;
      line-height: 1.35;
      overflow-wrap: anywhere;
    }
    @media (max-width: 760px) {
      .top { grid-template-columns: minmax(0, 1fr); }
      .grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .readiness { grid-template-columns: minmax(0, 1fr); }
      .recommended-actions { grid-template-columns: minmax(0, 1fr); }
      .evidence-grid { grid-template-columns: minmax(0, 1fr); }
      .profiles { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .boundary { grid-template-columns: minmax(0, 1fr); }
    }
  </style>
</head>
<body>
  <main class="shell">
    <header class="top">
      <div>
        <h1>ColaMeta Commander</h1>
        <div class="sub" id="subtitle">Awaiting service evidence</div>
      </div>
      <div class="badge" id="mode">read-only</div>
    </header>
    <section class="grid" aria-label="status">
      <div class="tile"><div class="label">Readiness</div><div class="value" id="readiness">-</div></div>
      <div class="tile"><div class="label">Project</div><div class="value" id="project">-</div></div>
      <div class="tile"><div class="label">Runtime</div><div class="value" id="runtime">-</div></div>
      <div class="tile"><div class="label">Local</div><div class="value" id="local">-</div></div>
      <div class="tile"><div class="label">External</div><div class="value" id="external">-</div></div>
      <div class="tile"><div class="label">Apps</div><div class="value" id="apps">-</div></div>
    </section>
    <section class="section">
      <h2>Next Step</h2>
      <div class="readiness">
        <div class="note"><strong>Flow persona</strong><span id="flow-persona">-</span></div>
        <div class="note"><strong>Primary blocker</strong><span id="primary-blocker">-</span></div>
        <div class="note"><strong>Safe next action</strong><span id="safe-next-action">-</span></div>
      </div>
    </section>
    <section class="section">
      <h2>Closeout</h2>
      <div class="readiness">
        <div class="note"><strong>Status</strong><span id="closeout-status">-</span></div>
        <div class="note"><strong>Gaps</strong><span id="closeout-gaps">-</span></div>
        <div class="note"><strong>Next</strong><span id="closeout-next">-</span></div>
      </div>
      <div class="recommended-actions" id="closeout-action-groups"></div>
    </section>
    <section class="section">
      <h2>Recommended Actions</h2>
      <div class="recommended-actions" id="recommended-actions"></div>
    </section>
    <section class="section">
      <h2>Profiles</h2>
      <div class="profiles" id="profiles"></div>
    </section>
    <section class="section">
      <h2>Apps Connector</h2>
      <div class="readiness">
        <div class="note"><strong>Project list</strong><span id="apps-project-list">-</span></div>
        <div class="note"><strong>Closeout</strong><span id="apps-closeout">-</span></div>
      </div>
    </section>
    <section class="section">
      <h2>Release Evidence</h2>
      <div class="readiness">
        <div class="note"><strong>Submission status</strong><span id="submission-status">-</span></div>
        <div class="note"><strong>Evidence blockers</strong><span id="submission-blockers">-</span></div>
      </div>
      <div class="note evidence-activity-wrap">
        <div class="evidence-head">
          <strong>Activity</strong>
          <div class="actions">
            <button class="evidence-copy secondary" id="submission-activity-copy" type="button">Copy</button>
            <button class="action-record secondary" id="submission-activity-record" type="button">Record</button>
          </div>
        </div>
        <span id="submission-activity">No evidence activity yet.</span>
        <div class="action-run-status" id="submission-activity-record-status"></div>
      </div>
      <div class="evidence-grid" id="submission-evidence"></div>
    </section>
    <section class="section">
      <h2>Reads</h2>
      <div class="actions">
        <button data-tool="get_commander_app_manifest">Manifest</button>
        <button class="secondary" data-tool="get_agent_operator_flow_packet">Flow</button>
        <button class="secondary" data-tool="get_product_console_map">Console</button>
        <button class="secondary" data-tool="get_release_submission_readiness">Submission</button>
        <button class="secondary" data-tool="get_submission_evidence_auto_draft">Auto Draft</button>
        <button class="secondary" data-tool="get_submission_evidence_fill_preview">Fill Preview</button>
        <button class="secondary" data-tool="get_apps_connector_smoke_packet">Apps</button>
        <button class="secondary" data-tool="get_stable_replacement_cadence">Cadence</button>
        <button class="secondary" data-tool="get_runtime_version_status">Runtime</button>
        <button class="secondary" data-tool="get_connector_runtime_health_status">Connector</button>
        <button class="secondary" data-tool="analyze_project_state">State</button>
      </div>
    </section>
    <section class="section">
      <h2>Gates</h2>
      <div class="boundary" id="boundary"></div>
    </section>
    <div class="log" id="log">No tool result received yet.</div>
  </main>
  <script>
    (function () {
      var manifest = null;
      var viewState = {};
      var seq = 1;
      var activeProjectName = "";
      var actionRunStatus = {};
      var pendingBridgeCalls = {};
      function byId(id) { return document.getElementById(id); }
      function text(id, value) { byId(id).textContent = value || "-"; }
      function normalize(payload) {
        if (!payload || typeof payload !== "object") return null;
        if (payload.data && payload.data.app_manifest_version) return payload.data;
        if (payload.structuredContent) return normalize(payload.structuredContent);
        if (payload.app_manifest_version) return payload;
        return payload.data && typeof payload.data === "object" ? payload.data : payload;
      }
      function hasOwn(obj, key) {
        return !!obj && Object.prototype.hasOwnProperty.call(obj, key);
      }
      function clearStaleEvidenceState(next) {
        if (!next || next.source !== "product_console_map") return;
        if (!hasOwn(next, "release_submission_evidence_bundle")) delete viewState.release_submission_evidence_bundle;
        if (!hasOwn(next, "release_submission_snapshot")) delete viewState.release_submission_snapshot;
        if (!hasOwn(next, "release_submission")) delete viewState.release_submission;
        if (!hasOwn(next, "release_submission_evidence")) delete viewState.release_submission_evidence;
        if (!hasOwn(next, "completion_surface")) delete viewState.completion_surface;
      }
      function clearStaleSubmissionFailureState(next) {
        if (!next || typeof next !== "object") return;
        var isSubmissionRefresh = [
          "release_submission_readiness",
          "submission_evidence_fill_preview",
          "product_console_map"
        ].indexOf(next.source) >= 0;
        if (!isSubmissionRefresh && next.ok !== true) return;
        if (!hasOwn(next, "safe_recovery_actions")) delete viewState.safe_recovery_actions;
        if (!hasOwn(next, "error_code")) delete viewState.error_code;
        if (!hasOwn(next, "ok")) delete viewState.ok;
      }
      function statusValue(obj, keys) {
        var cur = obj || {};
        for (var i = 0; i < keys.length; i += 1) {
          if (!cur || typeof cur !== "object") return "-";
          cur = cur[keys[i]];
        }
        return cur === undefined || cur === null || cur === "" ? "-" : String(cur);
      }
      function firstSafeAction(readiness) {
        var actions = readiness && Array.isArray(readiness.safe_next_actions) ? readiness.safe_next_actions : [];
        if (!actions.length) return "-";
        var first = actions[0] || {};
        return [first.label, first.tool, first.authority].filter(Boolean).join(" | ");
      }
      function flowAction(flow) {
        var action = flow && flow.primary_next_action;
        if (!action || typeof action !== "object") return "";
        return [action.label, action.tool, action.gate_level].filter(Boolean).join(" | ");
      }
      function blockerText(readiness) {
        var blocker = readiness && readiness.primary_blocker;
        if (!blocker || typeof blocker !== "object") return "none";
        return [blocker.component, blocker.reason_code, blocker.safe_evidence_needed].filter(Boolean).join(" | ");
      }
      function completionSurface(data) {
        if (!data || typeof data !== "object") return {};
        if (data.completion_surface && typeof data.completion_surface === "object") return data.completion_surface;
        if (data.product_console_map && data.product_console_map.completion_surface && typeof data.product_console_map.completion_surface === "object") {
          return data.product_console_map.completion_surface;
        }
        return {};
      }
      function completionGapText(completion) {
        var gaps = completion && Array.isArray(completion.gaps) ? completion.gaps : [];
        if (!gaps.length) return "none";
        return gaps.slice(0, 4).map(function (gap) {
          if (!gap || typeof gap !== "object") return String(gap);
          return [gap.component, gap.status, gap.code].filter(Boolean).join(" | ");
        }).join("\\n");
      }
      function completionNextText(completion) {
        var action = completion && completion.safe_next_action;
        if (!action || typeof action !== "object") return "-";
        return [action.action, action.tool || action.runbook, action.authority].filter(Boolean).join(" | ");
      }
      function completionActionText(action) {
        if (!action || typeof action !== "object") return "-";
        return [action.action || action.action_id, action.tool || action.runbook, action.authority || action.required_scope || action.mode].filter(Boolean).join(" | ");
      }
      function completionActionGroups(completion) {
        if (completion && Array.isArray(completion.action_groups) && completion.action_groups.length) {
          return completion.action_groups;
        }
        var action = completion && completion.safe_next_action;
        if (action && typeof action === "object") {
          return [{
            group_id: "next_action",
            label: "Next Action",
            status: completion.status || "unknown",
            gap_codes: completion.needs_attention_codes || completion.blocker_codes || [],
            primary_action: action,
            action_refs: [],
            empty_state: "Read Product Console to load closeout action groups."
          }];
        }
        return [];
      }
      function completionFollowupItems(completion) {
        var queue = completion && completion.followup_queue && typeof completion.followup_queue === "object"
          ? completion.followup_queue
          : {};
        if (Array.isArray(queue.items) && queue.items.length) return queue.items;
        if (queue.next_item && typeof queue.next_item === "object") return [queue.next_item];
        return [];
      }
      function closeoutFollowupAction(item) {
        var primary = item && item.primary_action && typeof item.primary_action === "object" ? Object.assign({}, item.primary_action) : {};
        if (!primary.action_id && item && item.item_id) primary.action_id = item.item_id;
        if (!primary.mode && item && item.required_scope === "mcp:read") primary.mode = "read";
        if (!primary.mode && item && item.required_scope === "mcp:preview") primary.mode = "preview";
        if (!primary.mode && item && item.required_scope === "mcp:commit") primary.mode = "commit";
        if (!primary.required_scope && item && item.required_scope) primary.required_scope = item.required_scope;
        return primary;
      }
      function closeoutFollowupKey(item, action) {
        return ["closeout", item && item.item_id, actionKey(action)].filter(Boolean).join("|");
      }
      function closeoutRefreshArgs(action) {
        var args = {};
        if (action && action.arguments && action.arguments.project_name) args.project_name = action.arguments.project_name;
        if (!args.project_name && activeProjectName) args.project_name = activeProjectName;
        return args;
      }
      function closeoutRecordArgs(action) {
        return action && action.arguments && typeof action.arguments === "object" ? Object.assign({}, action.arguments) : {};
      }
      function releaseSnapshot(data) {
        if (!data || typeof data !== "object") return {};
        if (data.source === "release_submission_readiness") return data;
        if (data.release_submission_snapshot && typeof data.release_submission_snapshot === "object") return data.release_submission_snapshot;
        if (data.release_submission && typeof data.release_submission === "object") return data.release_submission;
        return {};
      }
      function evidenceBundle(data) {
        if (!data || typeof data !== "object") return {};
        if (data.release_submission_evidence_bundle && typeof data.release_submission_evidence_bundle === "object") {
          return data.release_submission_evidence_bundle;
        }
        var apps = data.apps_connector_closeout || {};
        var releaseEvidence = apps.release_submission_evidence || data.release_submission_evidence || {};
        if (releaseEvidence && typeof releaseEvidence === "object") {
          return {
            status: releaseEvidence.status,
            ready: releaseEvidence.ready === true,
            progress_summary: releaseEvidence.evidence_progress,
            submission_evidence_activity: releaseEvidence.submission_evidence_activity,
            fill_plan: { status: releaseEvidence.ready === true ? "ready" : "read_release_submission_readiness", draft_entries: [] }
          };
        }
        return {};
      }
      function evidenceTemplates(data) {
        var snapshot = releaseSnapshot(data);
        if (Array.isArray(snapshot.submission_evidence_entry_templates)) return snapshot.submission_evidence_entry_templates;
        var materials = snapshot.submission_materials || {};
        if (Array.isArray(materials.evidence_entry_templates)) return materials.evidence_entry_templates;
        var actions = Array.isArray(data && data.recommended_first_actions) ? data.recommended_first_actions : [];
        for (var i = 0; i < actions.length; i += 1) {
          var ctx = actions[i] && actions[i].evidence_context;
          if (ctx && Array.isArray(ctx.entry_templates)) return ctx.entry_templates;
        }
        return [];
      }
      function evidenceProgress(data) {
        var bundle = evidenceBundle(data);
        if (bundle.progress_summary && typeof bundle.progress_summary === "object") {
          return bundle.progress_summary;
        }
        var snapshot = releaseSnapshot(data);
        if (snapshot.submission_evidence_progress && typeof snapshot.submission_evidence_progress === "object") {
          return snapshot.submission_evidence_progress;
        }
        var materials = snapshot.submission_materials || {};
        if (materials.evidence_progress && typeof materials.evidence_progress === "object") {
          return materials.evidence_progress;
        }
        return {};
      }
      function submissionPreview(data) {
        if (!data || typeof data !== "object") return {};
        return data.source === "submission_evidence_fill_preview" ? data : {};
      }
      function submissionPreviewCardModels(data) {
        var preview = submissionPreview(data);
        if (!preview.source) return [];
        var call = preview.copyable_tool_call || {};
        var args = call.arguments || {};
        if (call.tool === "fill_submission_evidence_files" && Array.isArray(args.entries)) {
          return args.entries.map(function (entry) {
            return {
              key: entry.key,
              title: entry.key,
              status: preview.status,
              default_filename: entry.filename,
              content_prompt: preview.summary,
              purpose: preview.summary,
              required_sections: preview.operator_instructions,
              copyable_entry_shape: entry,
              copy_payload: call,
              copy_message: "Copied evidence tool call."
            };
          });
        }
        if (call.tool === "mark_submission_evidence_ready_fields" && Array.isArray(args.keys)) {
          var bundle = preview.evidence_bundle || {};
          var fillPlan = bundle.fill_plan || {};
          var reviewEntries = Array.isArray(fillPlan.review_entries) ? fillPlan.review_entries : [];
          return args.keys.map(function (key) {
            var match = reviewEntries.find(function (entry) { return entry && String(entry.key) === String(key); }) || {};
            return {
              key: key,
              title: key,
              status: preview.status,
              default_path: Array.isArray(match.refs) ? match.refs.join(", ") : "",
              content_prompt: preview.summary,
              purpose: preview.summary,
              required_sections: ["human_reviewed"].concat(preview.operator_instructions || []),
              copyable_entry_shape: call,
              copy_payload: call,
              copy_message: "Copied evidence tool call."
            };
          });
        }
        return [];
      }
      function evidenceCardModels(data) {
        var previewCards = submissionPreviewCardModels(data);
        if (previewCards.length) return previewCards;
        var bundle = evidenceBundle(data);
        var fillPlan = bundle.fill_plan || {};
        if (Array.isArray(fillPlan.draft_entries) && fillPlan.draft_entries.length) {
          return fillPlan.draft_entries.map(function (entry) {
            return {
              key: entry.key,
              title: entry.key,
              status: entry.current_status || fillPlan.status,
              default_path: entry.default_path,
              default_filename: entry.filename,
              content_prompt: entry.purpose || fillPlan.why,
              purpose: entry.purpose || fillPlan.why,
              required_sections: entry.required_sections,
              copyable_entry_shape: entry.copyable_entry_shape
            };
          });
        }
        var progress = evidenceProgress(data);
        if (Array.isArray(progress.rows) && progress.rows.length) {
          return progress.rows.map(function (row) {
            var template = row.template || {};
            return {
              key: row.key,
              title: template.title || row.key,
              status: row.status,
              default_path: row.default_path || template.default_path,
              default_filename: template.default_filename,
              content_prompt: template.content_prompt || template.purpose,
              purpose: template.purpose,
              required_sections: template.required_sections,
              copyable_entry_shape: template.copyable_entry_shape
            };
          });
        }
        return evidenceTemplates(data);
      }
      function evidenceBlockers(data) {
        if (data && typeof data === "object" && data.ok === false) {
          var recoveryCount = Array.isArray(data.safe_recovery_actions) ? data.safe_recovery_actions.length : 0;
          return [
            "failed " + (data.error_code || data.status || "unknown"),
            recoveryCount ? "recovery actions " + recoveryCount : ""
          ].filter(Boolean).join(" | ");
        }
        var preview = submissionPreview(data);
        if (preview.source) {
          var call = preview.copyable_tool_call || {};
          var args = call.arguments || {};
          var entryCount = Array.isArray(args.entries) ? args.entries.length : 0;
          var keyCount = Array.isArray(args.keys) ? args.keys.length : 0;
          return [
            "preview " + (preview.status || "unknown"),
            call.tool ? "tool " + call.tool : "",
            entryCount ? "entries " + entryCount : "",
            keyCount ? "keys " + keyCount : ""
          ].filter(Boolean).join(" | ") || "none";
        }
        var bundle = evidenceBundle(data);
        var fillPlan = bundle.fill_plan || {};
        if (fillPlan.status && bundle.progress_summary && typeof bundle.progress_summary === "object") {
          var summary = bundle.progress_summary;
          var counts = summary.counts || {};
          return [
            "plan " + fillPlan.status,
            "ready " + (summary.complete_count || 0) + "/" + (summary.total_count || 0),
            "attention " + (counts.needs_attention || 0),
            "placeholder " + (counts.placeholder || 0)
          ].join(" | ");
        }
        var progress = evidenceProgress(data);
        if (progress.counts && typeof progress.counts === "object") {
          return [
            "ready " + (progress.complete_count || 0) + "/" + (progress.total_count || 0),
            "attention " + (progress.counts.needs_attention || 0),
            "placeholder " + (progress.counts.placeholder || 0)
          ].join(" | ");
        }
        var snapshot = releaseSnapshot(data);
        var materials = snapshot.submission_materials || {};
        var keys = Array.isArray(materials.incomplete_evidence_keys) ? materials.incomplete_evidence_keys : [];
        var placeholders = Array.isArray(materials.placeholder_evidence_files) ? materials.placeholder_evidence_files : [];
        var missing = Array.isArray(materials.missing_evidence_files) ? materials.missing_evidence_files : [];
        return keys.concat(placeholders).concat(missing).slice(0, 6).join(" | ") || "none";
      }
      function submissionPreviewRefreshes(data) {
        var preview = submissionPreview(data);
        var call = preview.copyable_tool_call || {};
        var contract = call.result_contract || {};
        return Array.isArray(contract.refresh_after) ? contract.refresh_after : [];
      }
      function submissionPreviewRefreshArgs(data, refresh) {
        var preview = submissionPreview(data);
        var call = preview.copyable_tool_call || {};
        var callArgs = call.arguments || {};
        var args = refresh && typeof refresh.arguments === "object" ? Object.assign({}, refresh.arguments) : {};
        var projectName = preview.project_name || callArgs.project_name || activeProjectName;
        if (projectName && !args.project_name) args.project_name = projectName;
        return args;
      }
      function submissionSafeRecoveryActions(data) {
        var actions = data && Array.isArray(data.safe_recovery_actions) ? data.safe_recovery_actions : [];
        return actions.filter(function (item) {
          if (!item || typeof item.tool !== "string" || !item.tool) return false;
          if (item.required_scope === "mcp:read") return true;
          return item.side_effects === false;
        });
      }
      function copyText(textValue, message) {
        if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
          navigator.clipboard.writeText(textValue).then(function () {
            text("log", message || "Copied.");
          }).catch(function () {
            text("log", "Copy failed; payload below:\\n" + textValue);
          });
          return;
        }
        text("log", "Copy unavailable; payload below:\\n" + textValue);
      }
      function renderEvidenceRefreshQueue(target, data) {
        var refreshes = submissionPreviewRefreshes(data);
        if (!refreshes.length) return;
        var queue = document.createElement("div");
        queue.className = "action-refresh-queue evidence-refresh-queue";
        var label = document.createElement("span");
        label.className = "action-refresh-label evidence-refresh-label";
        label.textContent = "Refresh after execution";
        queue.appendChild(label);
        refreshes.slice(0, 3).forEach(function (item, index) {
          if (!item || typeof item.tool !== "string" || !item.tool) return;
          var key = ["evidence-refresh", item.tool, index].join("|");
          var button = document.createElement("button");
          button.className = "action-refresh secondary evidence-refresh";
          button.type = "button";
          button.textContent = item.tool;
          button.title = item.why || "Refresh read surface after executing the copied tool call.";
          var status = document.createElement("span");
          status.className = "action-refresh-label evidence-refresh-label";
          renderRefreshStatus(status, key);
          button.addEventListener("click", async function () {
            rememberActionRunStatus(key, "pending", item.tool);
            renderRefreshStatus(status, key);
            var result = await callToolWithArgs(item.tool, submissionPreviewRefreshArgs(data, item), "evidence preview refresh", key);
            if (result && result.status) renderRefreshStatus(status, key);
          });
          queue.appendChild(button);
          queue.appendChild(status);
        });
        target.appendChild(queue);
      }
      function renderEvidenceRecoveryActions(target, data) {
        var actions = submissionSafeRecoveryActions(data);
        if (!actions.length) return;
        var queue = document.createElement("div");
        queue.className = "action-refresh-queue evidence-recovery-queue";
        var label = document.createElement("span");
        label.className = "action-refresh-label evidence-recovery-label";
        label.textContent = "Recovery actions";
        queue.appendChild(label);
        actions.slice(0, 3).forEach(function (item, index) {
          var key = ["evidence-recovery", item.tool, index].join("|");
          var button = document.createElement("button");
          button.className = "action-refresh secondary evidence-recovery";
          button.type = "button";
          button.textContent = item.tool;
          button.title = item.why || "Run safe read-only recovery action.";
          var status = document.createElement("span");
          status.className = "action-refresh-label evidence-recovery-label";
          renderRefreshStatus(status, key);
          button.addEventListener("click", async function () {
            rememberActionRunStatus(key, "pending", item.tool);
            renderRefreshStatus(status, key);
            var result = await callToolWithArgs(item.tool, item.arguments || {}, "evidence recovery", key);
            if (result && result.status) renderRefreshStatus(status, key);
          });
          queue.appendChild(button);
          queue.appendChild(status);
        });
        target.appendChild(queue);
      }
      function submissionActivityRows(data) {
        var rows = [];
        var actionState = data && typeof data.action_result_state === "object" ? data.action_result_state : {};
        var recordedActivity = actionState.submission_evidence_activity || {};
        var bundleActivity = evidenceBundle(data).submission_evidence_activity || {};
        if (recordedActivity && recordedActivity.available === true) {
          rows.push([
            "recorded",
            recordedActivity.status,
            recordedActivity.message,
            recordedActivity.observed_at
          ].filter(Boolean).join(" | "));
        } else if (bundleActivity && bundleActivity.available === true) {
          rows.push([
            "closeout",
            bundleActivity.status,
            bundleActivity.message,
            bundleActivity.observed_at
          ].filter(Boolean).join(" | "));
        }
        if (data && typeof data === "object" && data.ok === false) {
          rows.push([
            "result",
            data.status || "failed",
            data.error_code || "",
            data.message || ""
          ].filter(Boolean).join(" | "));
        }
        Object.keys(actionRunStatus).filter(function (key) {
          return key.indexOf("evidence-refresh|") === 0 || key.indexOf("evidence-recovery|") === 0;
        }).slice(-4).forEach(function (key) {
          var item = actionRunStatus[key] || {};
          rows.push([
            key.indexOf("evidence-recovery|") === 0 ? "recovery" : "refresh",
            item.status,
            item.message,
            item.at
          ].filter(Boolean).join(" | "));
        });
        return rows;
      }
      function renderEvidenceActivity(data) {
        var rows = submissionActivityRows(data);
        var target = byId("submission-activity");
        target.textContent = rows.length ? rows.join("\\n") : "No evidence activity yet.";
      }
      function submissionActivityCopyPayload(data) {
        return {
          source: "submission_evidence_activity_summary",
          schema_version: "submission_evidence_activity_summary.v1",
          project_name: activeProjectName || statusValue(data || {}, ["project_name"]),
          submission_status: byId("submission-status").textContent || "-",
          evidence_blockers: byId("submission-blockers").textContent || "none",
          rows: submissionActivityRows(data),
          authority_boundary: {
            read_only_summary: true,
            side_effects: false,
            does_not_write_files: true,
            does_not_mark_ready_fields: true,
            does_not_submit_app_for_review: true
          }
        };
      }
      function submissionActivityRecordStatus(rows) {
        if (!Array.isArray(rows) || !rows.length) return "blocked";
        return rows.some(function (row) { return String(row).indexOf("failed") >= 0; }) ? "failed" : "updated";
      }
      function submissionActivityRecordArgs(data) {
        var payload = submissionActivityCopyPayload(data);
        var rows = Array.isArray(payload.rows) ? payload.rows : [];
        var status = submissionActivityRecordStatus(rows);
        return {
          action_id: "submission_evidence_activity",
          tool: "submission_evidence_activity_summary",
          mode: "read",
          status: status,
          message: [
            "Submission evidence activity",
            payload.submission_status,
            payload.evidence_blockers,
            rows.slice(-2).join(" / ")
          ].filter(Boolean).join(" | "),
          result_ok: status === "updated"
        };
      }
      function submissionActivityRecordKey() {
        return "record|submission_evidence_activity|submission_evidence_activity_summary|read";
      }
      function renderSubmissionActivityRecordControl(data) {
        var button = byId("submission-activity-record");
        var statusNode = byId("submission-activity-record-status");
        if (!button || !statusNode) return;
        var rows = submissionActivityRows(data);
        var recordStatus = actionRunStatus[submissionActivityRecordKey()];
        button.disabled = !rows.length || !!(recordStatus && (recordStatus.status === "pending" || recordStatus.status === "recorded"));
        statusNode.textContent = recordStatus ? [recordStatus.status, recordStatus.message].filter(Boolean).join(" | ") : "";
      }
      function renderEvidence(data) {
        var snapshot = releaseSnapshot(data);
        var preview = submissionPreview(data);
        text("submission-status", preview.status || (data && data.ok === false ? "failed" : statusValue(snapshot, ["status"])));
        text("submission-blockers", evidenceBlockers(data));
        renderEvidenceActivity(data);
        renderSubmissionActivityRecordControl(data);
        var target = byId("submission-evidence");
        target.innerHTML = "";
        var cards = evidenceCardModels(data);
        renderEvidenceRecoveryActions(target, data);
        renderEvidenceRefreshQueue(target, data);
        if (!cards.length) {
          var empty = document.createElement("div");
          empty.className = "note";
          empty.textContent = "No evidence progress yet. Read Product Console or Release Submission readiness to refresh this panel.";
          target.appendChild(empty);
          return;
        }
        cards.slice(0, 10).forEach(function (template) {
          var card = document.createElement("div");
          card.className = "evidence-card";
          var head = document.createElement("div");
          head.className = "evidence-head";
          var titleWrap = document.createElement("div");
          var title = document.createElement("div");
          title.className = "evidence-title";
          title.textContent = [template.title || template.key || "Evidence", template.status].filter(Boolean).join(" | ");
          var path = document.createElement("div");
          path.className = "evidence-path";
          path.textContent = template.default_path || template.default_filename || "-";
          titleWrap.appendChild(title);
          titleWrap.appendChild(path);
          var copy = document.createElement("button");
          copy.className = "evidence-copy secondary";
          copy.type = "button";
          copy.textContent = "Copy";
          copy.addEventListener("click", function () {
            copyText(JSON.stringify(template.copy_payload || template.copyable_entry_shape || {
              key: template.key,
              filename: template.default_filename,
              content: "<operator-confirmed evidence text>"
            }, null, 2), template.copy_message || "Copied evidence entry shape.");
          });
          head.appendChild(titleWrap);
          head.appendChild(copy);
          var purpose = document.createElement("div");
          purpose.className = "evidence-purpose";
          purpose.textContent = template.content_prompt || template.purpose || "";
          var tags = document.createElement("div");
          tags.className = "evidence-tags";
          (Array.isArray(template.required_sections) ? template.required_sections : []).slice(0, 4).forEach(function (section) {
            var tag = document.createElement("span");
            tag.className = "evidence-tag";
            tag.textContent = String(section);
            tags.appendChild(tag);
          });
          card.appendChild(head);
          card.appendChild(purpose);
          card.appendChild(tags);
          target.appendChild(card);
        });
      }
      function renderCompletion(data) {
        var completion = completionSurface(data);
        var progress = completion.progress_state && typeof completion.progress_state === "object" ? completion.progress_state : {};
        text("closeout-status", [
          completion.status,
          progress.status ? "progress " + progress.status : "",
          completion.ready === true ? "ready" : "",
          completion.summary
        ].filter(Boolean).join(" | "));
        text("closeout-gaps", completionGapText(completion));
        text("closeout-next", completionNextText(completion));
        renderCompletionGroups(completion);
      }
      function renderCompletionGroups(completion) {
        var target = byId("closeout-action-groups");
        target.innerHTML = "";
        var groups = completionActionGroups(completion);
        if (!groups.length) {
          var empty = document.createElement("div");
          empty.className = "note closeout-group-empty";
          empty.textContent = "Read Product Console to load closeout action groups.";
          target.appendChild(empty);
          return;
        }
        groups.slice(0, 5).forEach(function (group) {
          if (!group || typeof group !== "object") return;
          var card = document.createElement("div");
          card.className = "recommended-action closeout-action-group";
          var title = document.createElement("div");
          title.className = "recommended-action-title closeout-group-title";
          title.textContent = [group.label || group.group_id || "Closeout", group.status].filter(Boolean).join(" | ");
          var meta = document.createElement("div");
          meta.className = "recommended-action-meta closeout-group-meta";
          appendChip(meta, group.component || group.group_id || "");
          var gaps = Array.isArray(group.gap_codes) ? group.gap_codes : [];
          appendChip(meta, gaps.length ? "gaps " + gaps.length : "no gaps", gaps.length ? "commit" : "read");
          var action = document.createElement("div");
          action.className = "recommended-action-why closeout-group-action";
          action.textContent = completionActionText(group.primary_action);
          var refs = document.createElement("div");
          refs.className = "recommended-action-boundary closeout-group-refs";
          (Array.isArray(group.action_refs) ? group.action_refs : []).slice(0, 3).forEach(function (ref) {
            appendChip(refs, completionActionText(ref));
          });
          if (!refs.textContent && group.empty_state) appendChip(refs, group.empty_state);
          card.appendChild(title);
          card.appendChild(meta);
          card.appendChild(action);
          card.appendChild(refs);
          renderCloseoutFollowupControls(card, completion, group);
          target.appendChild(card);
        });
      }
      function renderCloseoutFollowupControls(card, completion, group) {
        var items = completionFollowupItems(completion).filter(function (item) {
          return item && typeof item === "object" && (
            item.item_id === group.group_id ||
            item.component === group.component ||
            item.component === group.group_id
          );
        });
        if (!items.length) return;
        var item = items[0];
        var action = closeoutFollowupAction(item);
        var key = closeoutFollowupKey(item, action);
        var controls = document.createElement("div");
        controls.className = "action-refresh-queue closeout-followup-controls";
        var copy = document.createElement("button");
        copy.className = "action-copy secondary closeout-followup-copy";
        copy.type = "button";
        copy.textContent = "Copy";
        copy.addEventListener("click", function () {
          copyText(JSON.stringify({
            item_id: item.item_id,
            tool: action.tool,
            arguments: action.arguments || {},
            action: action.action,
            action_id: action.action_id,
            required_scope: item.required_scope || action.required_scope,
            gate_level: item.gate_level
          }, null, 2), "Copied closeout follow-up.");
        });
        controls.appendChild(copy);
        var canRun = item.required_scope === "mcp:read" && typeof action.tool === "string" && action.tool;
        var run = document.createElement("button");
        run.className = "action-run closeout-followup-run";
        run.type = "button";
        run.textContent = canRun ? "Run" : (item.required_scope === "mcp:commit" ? "Confirm required" : "Preview first");
        run.disabled = !canRun;
        var runStatus = document.createElement("span");
        runStatus.className = "action-run-status closeout-followup-status";
        renderActionRunStatus(runStatus, key, action);
        run.addEventListener("click", async function () {
          if (!canRun) return;
          rememberActionRunStatus(key, "pending", action.tool);
          renderActionRunStatus(runStatus, key, action);
          var result = await callToolWithArgs(action.tool, action.arguments || {}, "closeout follow-up", key);
          if (result && result.status) renderActionRunStatus(runStatus, key, action);
        });
        controls.appendChild(run);
        var recordStatusKey = recordKey(action);
        if (action.tool === "record_product_console_action_result") {
          var record = document.createElement("button");
          record.className = "action-record secondary closeout-followup-record";
          record.type = "button";
          record.textContent = "Record";
          record.title = "Record this closeout follow-up result";
          var recordStatus = document.createElement("span");
          recordStatus.className = "action-run-status closeout-followup-record-status";
          renderRefreshStatus(recordStatus, recordStatusKey);
          record.addEventListener("click", async function () {
            rememberActionRunStatus(recordStatusKey, "pending", "record_product_console_action_result");
            renderRefreshStatus(recordStatus, recordStatusKey);
            var recordResult = await callToolWithArgs("record_product_console_action_result", closeoutRecordArgs(action), "closeout follow-up record", recordStatusKey);
            renderRefreshStatus(recordStatus, recordStatusKey);
            if (recordActionResultSucceeded(recordResult)) {
              var refreshResult = await callToolWithArgs("get_product_console_map", closeoutRefreshArgs(action), "closeout follow-up refresh", "closeout-refresh|" + key);
              if (refreshResult && refreshResult.status) {
                rememberActionRunStatus(recordStatusKey, "recorded", "refresh current");
                renderRefreshStatus(recordStatus, recordStatusKey);
                render(viewState);
              }
            }
          });
          controls.appendChild(record);
          controls.appendChild(recordStatus);
        }
        var refresh = document.createElement("button");
        refresh.className = "action-refresh secondary closeout-followup-refresh";
        refresh.type = "button";
        refresh.textContent = "Refresh";
        var refreshStatusKey = "closeout-refresh|" + key;
        var refreshStatus = document.createElement("span");
        refreshStatus.className = "action-refresh-label closeout-followup-refresh-status";
        renderRefreshStatus(refreshStatus, refreshStatusKey);
        refresh.addEventListener("click", async function () {
          rememberActionRunStatus(refreshStatusKey, "pending", "get_product_console_map");
          renderRefreshStatus(refreshStatus, refreshStatusKey);
          var result = await callToolWithArgs("get_product_console_map", closeoutRefreshArgs(action), "closeout follow-up refresh", refreshStatusKey);
          if (result && result.status) renderRefreshStatus(refreshStatus, refreshStatusKey);
        });
        controls.appendChild(refresh);
        controls.appendChild(refreshStatus);
        controls.appendChild(runStatus);
        card.appendChild(controls);
      }
      function recommendedActions(data) {
        if (!data || typeof data !== "object") return [];
        if (Array.isArray(data.recommended_first_actions)) return data.recommended_first_actions;
        if (data.product_console_map && Array.isArray(data.product_console_map.recommended_first_actions)) {
          return data.product_console_map.recommended_first_actions;
        }
        return [];
      }
      function actionText(action) {
        if (!action || typeof action !== "object") return "-";
        return action.tool || action.runbook || action.action || action.action_id || "-";
      }
      function actionKey(action) {
        if (!action || typeof action !== "object") return "unknown";
        return [action.action_id, action.tool, action.runbook, action.mode].filter(Boolean).join("|") || actionText(action);
      }
      function rememberActionRunStatus(key, status, message) {
        if (!key) return;
        actionRunStatus[key] = {
          status: status || "unknown",
          message: message || "",
          at: new Date().toISOString()
        };
      }
      function errorSummary(err) {
        if (!err) return "unknown error";
        var message = err && err.message ? String(err.message) : String(err);
        return message.length > 120 ? message.slice(0, 117) + "..." : message;
      }
      function renderActionRunStatus(node, key, action) {
        var item = actionRunStatus[key] || (action && action.last_action_result);
        if (!item || item.status === "not_recorded") {
          node.textContent = "";
          return;
        }
        var observed = item.at || item.observed_at;
        node.textContent = ["Last run", item.status, item.message, observed].filter(Boolean).join(" | ");
      }
      function refreshKey(action, refresh, index) {
        return ["refresh", actionKey(action), refresh && refresh.tool, index].filter(Boolean).join("|");
      }
      function renderRefreshStatus(node, key) {
        var item = actionRunStatus[key];
        node.textContent = item ? [item.status, item.message].filter(Boolean).join(" | ") : "";
      }
      function recordKey(action) {
        return ["record", actionKey(action)].filter(Boolean).join("|");
      }
      function resultOkForRecord(status) {
        if (status === "updated") return true;
        if (status === "blocked" || status === "failed") return false;
        return undefined;
      }
      function recordActionResultSucceeded(result) {
        if (!result || typeof result !== "object") return false;
        return result.status === "updated" || result.status === "recorded" || result.result_status === "recorded";
      }
      function bridgeMessageId(message) {
        if (!message || typeof message !== "object") return "";
        if (message.id) return String(message.id);
        var params = message.params || {};
        if (params.id) return String(params.id);
        if (params.request_id) return String(params.request_id);
        if (params.requestId) return String(params.requestId);
        return "";
      }
      function resultFailed(data) {
        return data && typeof data === "object" && (data.ok === false || data.error || data.status === "failed");
      }
      function bridgeTimeoutMs() {
        var value = window.__colametaBridgeTimeoutMs;
        var parsed = value === undefined || value === null ? 30000 : Number(value);
        return Number.isFinite(parsed) && parsed > 0 ? parsed : 30000;
      }
      function clearBridgeTimeout(pending) {
        if (!pending || !pending.timeoutId) return;
        var clearFn = window.clearTimeout || (typeof clearTimeout === "function" ? clearTimeout : null);
        if (clearFn) clearFn(pending.timeoutId);
      }
      function markBridgeToolTimeout(id) {
        var pending = id && pendingBridgeCalls[id];
        if (!pending || !pending.statusKey) return;
        rememberActionRunStatus(pending.statusKey, "failed", pending.name + " via bridge timeout");
        delete pendingBridgeCalls[id];
        text("log", "Bridge request timed out for " + pending.name + ".");
        render(viewState);
      }
      function rememberBridgeToolResult(message, data) {
        var id = bridgeMessageId(message);
        var pending = id && pendingBridgeCalls[id];
        if (!pending || !pending.statusKey) return;
        clearBridgeTimeout(pending);
        var normalized = normalize(data) || {};
        var status = resultFailed(normalized) ? "failed" : "updated";
        var payloadStatus = normalized && normalized.status ? " | " + normalized.status : "";
        rememberActionRunStatus(pending.statusKey, status, pending.name + " via bridge" + payloadStatus);
        delete pendingBridgeCalls[id];
      }
      function renderRecordButton(button, statusNode, action, key) {
        var current = actionRunStatus[key];
        var recordStatus = actionRunStatus[recordKey(action)];
        var recorded = !!(recordStatus && recordStatus.status === "recorded");
        button.disabled = !current || current.status === "pending" || recorded;
        statusNode.textContent = recordStatus ? [recordStatus.status, recordStatus.message].filter(Boolean).join(" | ") : "";
      }
      function renderActionRefreshQueue(node, action) {
        node.innerHTML = "";
        var refreshes = action && Array.isArray(action.next_refresh_actions) ? action.next_refresh_actions : [];
        if (!refreshes.length) {
          return;
        }
        var label = document.createElement("span");
        label.className = "action-refresh-label";
        label.textContent = "Refresh";
        node.appendChild(label);
        refreshes.slice(0, 3).forEach(function (item, index) {
          if (!item || typeof item.tool !== "string" || !item.tool) return;
          var key = refreshKey(action, item, index);
          var button = document.createElement("button");
          button.className = "action-refresh secondary";
          button.type = "button";
          button.textContent = item.tool;
          button.title = item.why || "Refresh read surface";
          var status = document.createElement("span");
          status.className = "action-refresh-label";
          renderRefreshStatus(status, key);
          button.addEventListener("click", async function () {
            rememberActionRunStatus(key, "pending", item.tool);
            renderRefreshStatus(status, key);
            var result = await callToolWithArgs(item.tool, item.arguments || {}, "refresh queue", key);
            if (result && result.status) renderRefreshStatus(status, key);
          });
          node.appendChild(button);
          node.appendChild(status);
        });
      }
      function appendChip(parent, value, className) {
        if (value === undefined || value === null || value === "" || value === false) return;
        var chip = document.createElement("span");
        chip.className = ["action-chip", className || ""].filter(Boolean).join(" ");
        chip.textContent = String(value);
        parent.appendChild(chip);
      }
      function renderRecommendedActions(data) {
        var target = byId("recommended-actions");
        target.innerHTML = "";
        var actions = recommendedActions(data);
        if (!actions.length) {
          var empty = document.createElement("div");
          empty.className = "note";
          empty.textContent = "Read Product Console to load recommended action models.";
          target.appendChild(empty);
          return;
        }
        actions.slice(0, 6).forEach(function (action) {
          if (!action || typeof action !== "object") return;
          var key = actionKey(action);
          var card = document.createElement("div");
          card.className = "recommended-action";
          var head = document.createElement("div");
          head.className = "recommended-action-head";
          var title = document.createElement("div");
          title.className = "recommended-action-title";
          title.textContent = action.label || action.action_id || actionText(action);
          var copy = document.createElement("button");
          copy.className = "action-copy secondary";
          copy.type = "button";
          copy.textContent = "Copy";
          copy.addEventListener("click", function () {
            copyText(JSON.stringify({
              tool: action.tool,
              arguments: action.arguments || {},
              runbook: action.runbook,
              action_id: action.action_id,
              action_fingerprint: action.action_fingerprint,
              mode: action.mode,
              required_scope: action.required_scope,
              requires_explicit_confirmation: action.requires_explicit_confirmation === true
            }, null, 2), "Copied recommended action.");
          });
          head.appendChild(title);
          head.appendChild(copy);
          var run = document.createElement("button");
          run.className = "action-run";
          run.type = "button";
          var runnable = action.mode === "read" && typeof action.tool === "string" && action.tool;
          run.textContent = runnable ? "Run" : (action.mode === "commit" ? "Confirm outside" : "Preview first");
          run.disabled = !runnable;
          var runStatus = document.createElement("div");
          runStatus.className = "action-run-status";
          renderActionRunStatus(runStatus, key, action);
          var record = document.createElement("button");
          record.className = "action-record secondary";
          record.type = "button";
          record.textContent = "Record";
          record.title = "Record this action result summary";
          var recordStatus = document.createElement("div");
          recordStatus.className = "action-run-status";
          renderRecordButton(record, recordStatus, action, key);
          var refreshQueue = document.createElement("div");
          refreshQueue.className = "action-refresh-queue";
          renderActionRefreshQueue(refreshQueue, action);
          run.addEventListener("click", async function () {
            if (!runnable) return;
            rememberActionRunStatus(key, "pending", action.tool);
            renderActionRunStatus(runStatus, key, action);
            renderRecordButton(record, recordStatus, action, key);
            var result = await callToolWithArgs(action.tool, action.arguments || {}, "recommended action", key);
            if (result && result.status) {
              renderActionRunStatus(runStatus, key, action);
              renderRecordButton(record, recordStatus, action, key);
            }
          });
          record.addEventListener("click", async function () {
            var current = actionRunStatus[key];
            if (!current || current.status === "pending") return;
            var args = {
              action_id: action.action_id,
              tool: action.tool,
              mode: action.mode || "read",
              status: current.status,
              message: current.message || current.status,
              action_fingerprint: action.action_fingerprint
            };
            var resultOk = resultOkForRecord(current.status);
            if (resultOk !== undefined) args.result_ok = resultOk;
            var recKey = recordKey(action);
            rememberActionRunStatus(recKey, "pending", "record_product_console_action_result");
            renderRecordButton(record, recordStatus, action, key);
            var recordResult = await callToolWithArgs("record_product_console_action_result", args, "record action result", recKey);
            renderRecordButton(record, recordStatus, action, key);
            if (recordActionResultSucceeded(recordResult)) {
              var refreshResult = await callToolWithArgs("get_product_console_map", action.arguments || {}, "recorded result refresh", "record-refresh|" + key);
              if (refreshResult && refreshResult.status) {
                rememberActionRunStatus(recKey, "recorded", "refresh current");
                renderRecordButton(record, recordStatus, action, key);
                render(viewState);
              }
            }
          });
          head.appendChild(run);
          head.appendChild(record);
          var meta = document.createElement("div");
          meta.className = "recommended-action-meta";
          appendChip(meta, action.mode || "read", action.mode === "commit" ? "commit" : "read");
          appendChip(meta, action.status || "available");
          appendChip(meta, action.required_scope || "mcp:read");
          appendChip(meta, action.requires_explicit_confirmation === true ? "confirm" : "no confirm");
          appendChip(meta, action.side_effects === true ? "writes if invoked" : "read-only");
          appendChip(meta, actionText(action));
          var why = document.createElement("div");
          why.className = "recommended-action-why";
          why.textContent = action.why || "";
          var boundary = document.createElement("div");
          boundary.className = "recommended-action-boundary";
          var auth = action.authority_boundary || {};
          appendChip(boundary, auth.does_not_execute_now === true ? "does not execute now" : "");
          appendChip(boundary, auth.does_not_authorize_stable_replacement === true ? "no stable replacement" : "");
          appendChip(boundary, auth.does_not_submit_app_for_review === true ? "no app submission" : "");
          appendChip(boundary, auth.does_not_publish_app === true ? "no publish" : "");
          card.appendChild(head);
          card.appendChild(meta);
          card.appendChild(runStatus);
          card.appendChild(recordStatus);
          if (refreshQueue.textContent) card.appendChild(refreshQueue);
          if (why.textContent) card.appendChild(why);
          card.appendChild(boundary);
          target.appendChild(card);
        });
      }
      function profileCard(profile) {
        var node = document.createElement("div");
        node.className = "profile";
        var title = document.createElement("strong");
        title.textContent = profile.display_name || profile.profile_id || "Profile";
        var body = document.createElement("span");
        var guidance = profile.executor_status_polling_guidance || {};
        body.textContent = [
          profile.default_authority || "read_only",
          guidance.poll_interval_seconds ? guidance.poll_interval_seconds + "s" : "",
          guidance.max_poll_attempts ? "x " + guidance.max_poll_attempts : ""
        ].filter(Boolean).join(" | ");
        node.appendChild(title);
        node.appendChild(body);
        return node;
      }
      function render(payload) {
        var data = normalize(payload);
        if (!data || typeof data !== "object") return;
        if (data.app_manifest_version) manifest = data;
        clearStaleEvidenceState(data);
        clearStaleSubmissionFailureState(data);
        viewState = Object.assign({}, viewState, manifest || {}, data);
        var current = viewState;
        var projectName = current.project_name || statusValue(current, ["project_identity", "project", "project_name"]);
        activeProjectName = projectName && projectName !== "-" ? projectName : activeProjectName;
        var readiness = current.readiness || current.service_readiness_summary || {};
        var flow = current.agent_operator_flow || (current.source === "agent_operator_flow_packet" ? current : {});
        var flowProfile = current.agent_operator_flow_profile || {};
        var flowState = flow.current_state || {};
        var apps = current.apps_connector_closeout || {};
        text("subtitle", statusValue(current, ["app", "status_line"]) || "Service facts and authorization gates");
        text("readiness", statusValue(readiness, ["status"]));
        text("flow-persona", [
          flowProfile.display_name || flowProfile.profile_id || flow.profile_id,
          flowProfile.consumer_kind || flowState.consumer_kind,
          flowState.resolved_flow_mode
        ].filter(Boolean).join(" | "));
        text("primary-blocker", blockerText(readiness));
        text("safe-next-action", flowAction(flow) || firstSafeAction(readiness));
        text("project", projectName);
        text("runtime", statusValue(current, ["runtime", "reload_needed_for_verification"]) === "false" ? "current" : statusValue(current, ["runtime", "reload_awareness_reason"]));
        text("local", statusValue(current, ["connector", "local_service_status"]));
        text("external", statusValue(current, ["connector", "external_connector_status"]));
        text("apps", statusValue(apps, ["status"]));
        text("apps-project-list", [
          statusValue(apps, ["project_list_check", "tool"]),
          statusValue(apps, ["project_list_check", "expected_project_name"])
        ].filter(function (item) { return item && item !== "-"; }).join(" | "));
        text("apps-closeout", [
          statusValue(apps, ["connector_closeout_check", "current_operator_closeout"]),
          statusValue(apps, ["connector_closeout_check", "current_decision"])
        ].filter(function (item) { return item && item !== "-"; }).join(" | "));
        renderCompletion(current);
        renderRecommendedActions(current);
        renderEvidence(current);
        var profiles = byId("profiles");
        profiles.innerHTML = "";
        (current.profiles || current.service_entry_profiles || []).slice(0, 5).forEach(function (item) {
          profiles.appendChild(profileCard(item));
        });
        var boundary = byId("boundary");
        boundary.innerHTML = "";
        var list = Array.isArray(current.authority_boundary && current.authority_boundary.requires_explicit_commander_authorization_for)
          ? current.authority_boundary.requires_explicit_commander_authorization_for
          : ["executor run", "commit or push", "stable replacement"];
        list.slice(0, 6).forEach(function (item) {
          var node = document.createElement("div");
          node.className = "gate";
          node.textContent = String(item);
          boundary.appendChild(node);
        });
        text("log", "Last update: " + (current.updated_at || new Date().toISOString()));
        Array.prototype.forEach.call(document.querySelectorAll("button[data-tool]"), function (button) {
          button.disabled = !projectName;
        });
      }
      async function callToolWithArgs(name, args, sourceLabel, statusKey) {
        var callArgs = args && typeof args === "object" ? Object.assign({}, args) : {};
        if (!callArgs.project_name && activeProjectName) {
          callArgs.project_name = activeProjectName;
        }
        if (!name) {
          text("log", "Recommended action has no tool.");
          rememberActionRunStatus(statusKey, "blocked", "missing tool");
          return { status: "blocked", message: "missing tool" };
        }
        if (!callArgs.project_name) {
          text("log", "Project name unavailable.");
          rememberActionRunStatus(statusKey, "blocked", "missing project name");
          return { status: "blocked", message: "missing project name" };
        }
        if (window.openai && typeof window.openai.callTool === "function") {
          try {
            var next = await window.openai.callTool(name, callArgs);
            var normalized = null;
            var payload = null;
            if (next && next.structuredContent) {
              payload = next.structuredContent;
            } else if (next) {
              payload = next;
            }
            normalized = normalize(payload);
            var directStatus = resultFailed(normalized) ? "failed" : "updated";
            var payloadStatus = normalized && normalized.status ? " | " + normalized.status : "";
            rememberActionRunStatus(statusKey, directStatus, name + " via direct call" + payloadStatus);
            if (payload) render(payload);
            text("log", "Updated from " + (sourceLabel || name) + ".");
            return {
              status: directStatus,
              result_status: normalized && normalized.status,
              message: name + " via direct call" + payloadStatus
            };
          } catch (err) {
            var summary = errorSummary(err);
            rememberActionRunStatus(statusKey, "requested", "bridge fallback after direct failure: " + summary);
            text("log", "Direct call failed; using bridge for " + name + ": " + summary);
          }
        }
        var requestId = "colameta-commander-" + (seq++);
        pendingBridgeCalls[requestId] = { name: name, statusKey: statusKey, timeoutId: null };
        var timerFn = window.setTimeout || (typeof setTimeout === "function" ? setTimeout : null);
        if (timerFn) {
          pendingBridgeCalls[requestId].timeoutId = timerFn(function () {
            markBridgeToolTimeout(requestId);
          }, bridgeTimeoutMs());
        }
        window.parent.postMessage({
          jsonrpc: "2.0",
          id: requestId,
          method: "tools/call",
          params: { name: name, arguments: callArgs }
        }, "*");
        var requestedMessage = actionRunStatus[statusKey] && actionRunStatus[statusKey].message
          ? actionRunStatus[statusKey].message
          : name;
        rememberActionRunStatus(statusKey, "requested", requestedMessage);
        text("log", "Requested " + name + ".");
        return { status: "requested", message: requestedMessage };
      }
      async function callTool(name) {
        var projectName = activeProjectName || (manifest && manifest.project_name);
        if (!projectName) {
          text("log", "Project name unavailable.");
          return;
        }
        var args = { project_name: projectName };
        var flow = manifest && manifest.agent_operator_flow ? manifest.agent_operator_flow : {};
        var flowProfile = manifest && manifest.agent_operator_flow_profile ? manifest.agent_operator_flow_profile : {};
        var profileId = flowProfile.profile_id || flow.profile_id || statusValue(flow, ["current_state", "profile_id"]);
        if (profileId && profileId !== "-" && [
          "get_commander_app_manifest",
          "get_agent_operator_flow_packet",
          "render_commander_app"
        ].indexOf(name) >= 0) {
          args.profile_id = profileId;
        }
        callToolWithArgs(name, args, name);
      }
      window.addEventListener("openai:set_globals", function (event) {
        var globals = event.detail && event.detail.globals;
        render((globals && globals.toolOutput) || (window.openai && window.openai.toolOutput));
      }, { passive: true });
      window.addEventListener("message", function (event) {
        var message = event.data || {};
        if (message.method === "ui/notifications/tool-result") {
          var notificationResult = message.params && (message.params.structuredContent || message.params.result);
          rememberBridgeToolResult(message, notificationResult);
          render(notificationResult);
          return;
        }
        if (message.result && message.result.structuredContent) {
          rememberBridgeToolResult(message, message.result.structuredContent);
          render(message.result.structuredContent);
        }
      });
      Array.prototype.forEach.call(document.querySelectorAll("button[data-tool]"), function (button) {
        button.addEventListener("click", function () { callTool(button.getAttribute("data-tool")); });
      });
      var activityCopyButton = byId("submission-activity-copy");
      if (activityCopyButton) {
        activityCopyButton.addEventListener("click", function () {
          copyText(JSON.stringify(submissionActivityCopyPayload(viewState), null, 2), "Copied evidence activity summary.");
        });
      }
      var activityRecordButton = byId("submission-activity-record");
      if (activityRecordButton) {
        activityRecordButton.addEventListener("click", async function () {
          var key = submissionActivityRecordKey();
          var args = submissionActivityRecordArgs(viewState);
          if (!submissionActivityCopyPayload(viewState).rows.length) return;
          rememberActionRunStatus(key, "pending", "record_product_console_action_result");
          renderSubmissionActivityRecordControl(viewState);
          var result = await callToolWithArgs("record_product_console_action_result", args, "record evidence activity", key);
          renderSubmissionActivityRecordControl(viewState);
          if (recordActionResultSucceeded(result)) {
            var refreshResult = await callToolWithArgs("get_product_console_map", {}, "recorded evidence activity refresh", "record-refresh|submission_evidence_activity");
            if (refreshResult && refreshResult.status) {
              rememberActionRunStatus(key, "recorded", "refresh current");
              renderSubmissionActivityRecordControl(viewState);
            }
          }
        });
      }
      if (window.openai && window.openai.toolOutput) {
        render(window.openai.toolOutput);
      }
    }());
  </script>
</body>
</html>"""

    def _handle_jsonrpc_request(
        self,
        request: dict[str, Any],
        auth_context: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        req_id = request.get("id")
        method = request.get("method")
        params = request.get("params", {})
        if method is None:
            return self._protocol_error(req_id, -32600, "invalid_request", "请求缺少 method。")
        is_notification = "id" not in request
        if is_notification and isinstance(method, str) and method.startswith("notifications/"):
            return None

        try:
            if method == "initialize":
                return self._result(
                    req_id,
                    {
                        "protocolVersion": "2025-06-18",
                        "serverInfo": {"name": "colameta-mcp", "version": "1.0.0"},
                        "instructions": COMMANDER_APP_SERVER_INSTRUCTIONS,
                        "capabilities": {
                            "tools": {"listChanged": False},
                            "resources": {"subscribe": False, "listChanged": False},
                        },
                    },
                )
            if method == "notifications/initialized":
                return self._result(req_id, {"ok": True})
            if method in ("ping", "health"):
                return self._result(req_id, {"ok": True, "tool": method, "data": {"status": "ok"}})
            if method in ("list_tools", "tools/list"):
                return self._result(req_id, {"tools": self._tool_defs_payload()})
            if method in ("list_resources", "resources/list"):
                return self._result(req_id, self._mcp_resources_list_result())
            if method in ("read_resource", "resources/read"):
                if not isinstance(params, dict):
                    return self._protocol_error(req_id, -32602, "invalid_params", "params 必须是对象。")
                uri = params.get("uri")
                if not isinstance(uri, str) or not uri.strip():
                    return self._protocol_error(req_id, -32602, "invalid_resource_uri", "resources/read 需要 uri。")
                normalized_uri = uri.strip()
                if normalized_uri != COMMANDER_APP_WIDGET_URI:
                    return self._protocol_error(
                        req_id,
                        -32602,
                        "resource_not_found",
                        f"未知 resource uri：{normalized_uri}",
                    )
                return self._result(req_id, self._mcp_resource_read_result(normalized_uri))
            if method in ("call_tool", "tools/call"):
                if not isinstance(params, dict):
                    return self._result(req_id, self._tool_error("call_tool", "INVALID_PARAMS", "params 必须是对象。"))
                name = params.get("name")
                arguments = params.get("arguments", {})
                tool_result = self._call_tool(name, arguments, auth_context=auth_context)
                if method == "tools/call":
                    return self._result(req_id, self._as_mcp_call_result(tool_result, arguments))
                return self._result(req_id, tool_result)
            if method == "apply_plan_patch":
                return self._result(
                    req_id,
                    self._tool_error(
                        "apply_plan_patch",
                        "TOOL_NOT_EXPOSED",
                        "apply_plan_patch is intentionally not exposed over MCP. Runner applies pending patches locally via Web Console or CLI.",
                    ),
                )
            if method in self.tools:
                return self._result(req_id, self._call_tool(method, params, auth_context=auth_context))
            return self._protocol_error(req_id, -32601, "method_not_found", f"未知方法：{method}")
        except Exception as e:
            return self._result(
                req_id,
                self._tool_error("internal", "INTERNAL_ERROR", "服务器内部错误。", {"message": str(e)}),
            )

    def _tool_defs_payload(self) -> list[dict[str, Any]]:
        exposed_tool_defs = self._filter_tools_by_exposure_profile(self.tool_defs)
        payload: list[dict[str, Any]] = []
        for tool in exposed_tool_defs:
            item = {
                "name": tool.name,
                "description": tool.description,
                "inputSchema": tool.input_schema,
                "input_schema": tool.input_schema,
                "outputSchema": tool.output_schema,
            }
            if isinstance(tool.title, str) and tool.title.strip():
                item["title"] = tool.title
            if isinstance(tool.annotations, dict):
                item["annotations"] = copy.deepcopy(tool.annotations)
            if isinstance(tool.meta, dict):
                item["_meta"] = copy.deepcopy(tool.meta)
            payload.append(item)
        return payload

    def _snake_to_camel(self, name: str) -> str:
        parts = [part for part in name.strip().split("_") if part]
        if not parts:
            return ""
        head = parts[0].lower()
        tail = "".join(part[:1].upper() + part[1:] for part in parts[1:])
        return f"{head}{tail}"

    def _actions_operation_id(self, name: str) -> str:
        if name == "run_mcp_workflow":
            return "manageRunnerWorkflow"
        return self._snake_to_camel(name)

    def _actions_operation_summary(self, name: str) -> str:
        if name == "run_mcp_workflow":
            return "管理 Runner 工作流"
        return f"调用 {name}"

    def _truncate_description(self, text: Any, max_len: int = 280) -> str:
        if not isinstance(text, str):
            return ""
        trimmed = " ".join(text.split())
        if len(trimmed) <= max_len:
            return trimmed
        if max_len <= 3:
            return trimmed[:max_len]
        return f"{trimmed[: max_len - 3].rstrip()}..."

    def _actions_path_for_tool(self, name: str) -> str:
        return f"{ACTIONS_API_PREFIX}{name}"

    def _actions_tool_name_from_path(self, path: str) -> str | None:
        if not isinstance(path, str) or not path.startswith(ACTIONS_API_PREFIX):
            return None
        tool_name = path[len(ACTIONS_API_PREFIX):].strip("/")
        if not tool_name:
            return None
        return tool_name

    def _normalize_openapi_schema(self, schema: Any) -> Any:
        if isinstance(schema, dict):
            normalized: dict[str, Any] = {}
            for key, value in schema.items():
                if key == "properties":
                    if isinstance(value, dict):
                        normalized_properties: dict[str, Any] = {}
                        for prop_name, prop_schema in value.items():
                            normalized_properties[prop_name] = self._normalize_openapi_property_schema(prop_schema)
                        normalized[key] = normalized_properties
                    else:
                        normalized[key] = {}
                    continue
                if key == "description":
                    normalized[key] = self._truncate_description(value)
                else:
                    normalized[key] = self._normalize_openapi_schema(value)
            return normalized
        if isinstance(schema, list):
            return [self._normalize_openapi_schema(item) for item in schema]
        return schema

    def _normalize_openapi_property_schema(self, prop_schema: Any) -> dict[str, Any]:
        if isinstance(prop_schema, dict):
            normalized = self._normalize_openapi_schema(prop_schema)
            return normalized if isinstance(normalized, dict) else {"type": "string"}
        if isinstance(prop_schema, str):
            return {
                "type": "string",
                "description": self._truncate_description(prop_schema),
            }
        if isinstance(prop_schema, bool):
            if prop_schema:
                return {}
            return {"not": {}}
        if prop_schema is None:
            return {"type": "string", "description": ""}
        return {
            "type": "string",
            "description": self._truncate_description(str(prop_schema)),
        }

    def _actions_readonly_tools(self) -> set[str]:
        return {
            "get_agent_consumer_contract",
            "get_service_entry_profile",
            "get_agent_operator_flow_packet",
            "get_web_gpt_service_entrypoint",
            "get_commander_app_manifest",
            "render_commander_app",
            "get_stable_promotion_readiness",
            "get_runtime_version_status",
            "get_project_identity",
            "get_plan_standards_report",
            "get_runner_execution_standards",
            "get_runner_status",
            "get_executor_session_status",
            "get_executor_continuation_preview",
            "get_executor_continuation_decision",
            "get_executor_resume_invocation_preview",
            "get_review_context",
            "get_runner_workbench_context",
            "get_project_doc_section",
            "get_repo_overview",
            "get_git_status",
            "get_git_log",
            "get_source_file",
            "search_source",
            "get_git_diff",
            "get_executor_inventory",
            "list_executor_run_reports",
            "get_executor_run_report",
            "inspect_executor_activity",
            "analyze_project_state",
            "manage_workflow_run",
            "list_workflow_runs",
            "get_workflow_run",
            "todo_read",
            "decision_read",
        }

    def _is_actions_consequential_tool(self, tool_name: str) -> bool:
        return tool_name not in self._actions_readonly_tools()

    def _actions_manage_executor_allowed_actions(self) -> tuple[str, ...]:
        return (
            "preflight",
            "run_once_preview",
            "run_once",
            "get_audit_package",
            "refresh_audit_package",
            "recheck_report_preview",
            "recheck_report_apply",
            "manual_fix_prompt_preview",
            "manual_fix_prompt_apply",
            "manual_validation_preview",
            "manual_validation_apply",
            "scope_mismatch_preview",
            "scope_mismatch_apply",
            "state_lineage_reconciliation_preview",
            "state_lineage_reconciliation_apply",
            "final_version_closeout_preview",
            "final_version_closeout_apply",
            "reconcile_orphaned_claims_preview",
            "reconcile_orphaned_claims_apply",
            "status",
        )

    def _actions_openapi_tool_description(self, tool_name: str, description: str) -> str:
        if tool_name != "manage_executor_workflow":
            return self._truncate_description(description)
        return self._truncate_description(
            (
                "受控执行器工作流。GPT Actions 推荐链路：run_once_preview -> run_once -> status -> "
                "get_executor_run_report。支持旧报告重审链路：recheck_report_preview -> recheck_report_apply。"
                "支持手动修复提示词准备链路：manual_fix_prompt_preview -> manual_fix_prompt_apply。"
                "支持手动验收登记链路：manual_validation_preview -> manual_validation_apply。"
                "支持通用范围诊断链路：scope_mismatch_preview -> scope_mismatch_apply。"
                "支持 state lineage 对账链路：state_lineage_reconciliation_preview -> state_lineage_reconciliation_apply。"
                "支持最后一个版本 closeout 链路：final_version_closeout_preview -> final_version_closeout_apply。"
                "支持失联 claim 受控协调链路：reconcile_orphaned_claims_preview -> reconcile_orphaned_claims_apply。"
            )
        )

    def _actions_openapi_request_schema(self, tool_name: str, request_schema: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(request_schema, dict):
            return request_schema
        schema = copy.deepcopy(request_schema)
        props = schema.get("properties")
        if not isinstance(props, dict):
            return schema
        if tool_name in PROJECT_NAME_REQUIRED_TOOLS:
            project_schema = props.setdefault("project_name", {
                "type": "string",
                "description": "必填。服务模式下项目级工具必须显式提供已登记 project_name。",
            })
            if isinstance(project_schema, dict):
                project_schema["description"] = "必填。服务模式下项目级工具必须显式提供已登记 project_name。"
            required = schema.setdefault("required", [])
            if isinstance(required, list) and "project_name" not in required:
                required.append("project_name")
        if tool_name != "manage_executor_workflow":
            return schema
        action_schema = props.get("action")
        if isinstance(action_schema, dict):
            current_enum = action_schema.get("enum")
            allowed = list(self._actions_manage_executor_allowed_actions())
            if isinstance(current_enum, list):
                filtered = [item for item in current_enum if item in allowed]
                action_schema["enum"] = filtered or allowed
            else:
                action_schema["enum"] = allowed
            action_schema["description"] = (
                "执行器工作流操作。GPT Actions 暴露：preflight、run_once_preview、run_once、"
                "get_audit_package、refresh_audit_package、recheck_report_preview、recheck_report_apply、"
                "manual_fix_prompt_preview、manual_fix_prompt_apply、"
                "manual_validation_preview、manual_validation_apply、scope_mismatch_preview、scope_mismatch_apply、"
                "state_lineage_reconciliation_preview、state_lineage_reconciliation_apply、"
                "final_version_closeout_preview、final_version_closeout_apply、"
                "reconcile_orphaned_claims_preview、reconcile_orphaned_claims_apply、status。"
            )
        preview_schema = props.get("preview_id")
        if isinstance(preview_schema, dict):
            preview_schema["description"] = (
                "run_once/recheck_report_apply/manual_fix_prompt_apply/manual_validation_apply/scope_mismatch_apply/state_lineage_reconciliation_apply/final_version_closeout_apply/reconcile_orphaned_claims_apply 必填；status 可选。"
                "来自 run_once_preview、recheck_report_preview、manual_fix_prompt_preview、manual_validation_preview、scope_mismatch_preview、state_lineage_reconciliation_preview、final_version_closeout_preview 或 reconcile_orphaned_claims_preview 的 preview_id。"
            )
        for bounded_only_param in (
            "max_iterations",
            "trusted_mode",
            "stop_on_acceptance_failure",
            "stop_on_scope_violation",
            "stop_on_diff_too_large",
            "max_total_diff_chars",
            "allow_fix",
            "allow_commit",
        ):
            props.pop(bounded_only_param, None)
        return schema

    def _is_actions_bounded_next_action(self, item: dict[str, Any]) -> bool:
        candidates: list[str] = []
        direct = item.get("action")
        if isinstance(direct, str) and direct.strip():
            candidates.append(direct.strip().lower())
        for key in ("params", "arguments"):
            container = item.get(key)
            if isinstance(container, dict):
                action_val = container.get("action")
                if isinstance(action_val, str) and action_val.strip():
                    candidates.append(action_val.strip().lower())
        for candidate in candidates:
            if "run_bounded" in candidate:
                return True
        return False

    def _actions_run_once_preview_next_action(self, original: dict[str, Any]) -> dict[str, Any]:
        provider = "codex"
        for key in ("params", "arguments"):
            container = original.get(key)
            if isinstance(container, dict):
                provider_val = container.get("provider")
                if isinstance(provider_val, str) and provider_val.strip():
                    provider = provider_val.strip()
                    break
        return {
            "action": "manage_executor_workflow.run_once_preview",
            "label": "生成执行器运行预览",
            "reason": "GPT Actions 使用 run_once_preview -> run_once -> status -> get_executor_run_report 链路。",
            "tool": "manage_executor_workflow",
            "params": {"action": "run_once_preview", "provider": provider, "execution_mode": "run"},
            "risk_level": "preview",
            "requires_confirmation": True,
        }

    def _actions_sanitize_next_actions(self, items: list[Any]) -> list[Any]:
        sanitized: list[Any] = []
        seen_keys: set[str] = set()
        for item in items:
            if not isinstance(item, dict):
                sanitized.append(item)
                continue
            if self._is_actions_bounded_next_action(item):
                replacement = self._actions_run_once_preview_next_action(item)
                key = json.dumps(replacement, ensure_ascii=False, sort_keys=True)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                sanitized.append(replacement)
                continue
            sanitized.append(item)
        return sanitized

    def _actions_sanitize_tool_result(self, tool_result: Any) -> Any:
        if isinstance(tool_result, dict):
            result: dict[str, Any] = {}
            for key, value in tool_result.items():
                if key == "next_actions" and isinstance(value, list):
                    result[key] = self._actions_sanitize_next_actions(value)
                else:
                    result[key] = self._actions_sanitize_tool_result(value)
            return result
        if isinstance(tool_result, list):
            return [self._actions_sanitize_tool_result(item) for item in tool_result]
        return tool_result

    def _build_actions_openapi_schema(
        self,
        public_base_url: str | None,
        host: str,
        port: int,
    ) -> dict[str, Any]:
        server_url = public_base_url.rstrip("/") if isinstance(public_base_url, str) and public_base_url.strip() else f"http://{host}:{port}"
        visible_tool_defs = self._filter_tools_by_exposure_profile(self.tool_defs)
        common_output_schema = self._build_common_output_schema()
        normalized_output_schema = self._normalize_openapi_schema(common_output_schema)
        paths: dict[str, Any] = {}
        for tool in visible_tool_defs:
            path = self._actions_path_for_tool(tool.name)
            summary = self._actions_operation_summary(tool.name)
            description = self._actions_openapi_tool_description(tool.name, tool.description)
            request_schema = self._normalize_openapi_schema(tool.input_schema)
            request_schema = self._actions_openapi_request_schema(tool.name, request_schema)
            paths[path] = {
                "post": {
                    "operationId": self._actions_operation_id(tool.name),
                    "summary": self._truncate_description(summary, max_len=120),
                    "description": description,
                    "x-openai-isConsequential": self._is_actions_consequential_tool(tool.name),
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": request_schema,
                            }
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "OK",
                            "content": {
                                "application/json": {
                                    "schema": normalized_output_schema,
                                }
                            },
                        }
                    },
                    "security": [{"BearerAuth": []}],
                }
            }

        schema = {
            "openapi": "3.1.0",
            "info": {
                "title": "MVP Runner Actions API",
                "version": "1.0.0",
                "description": self._truncate_description(
                    "REST adapter for MVP Runner project status, source review, git review, docs, plan, executor and commit workflows."
                ),
            },
            "servers": [{"url": server_url}],
            "security": [{"BearerAuth": []}],
            "paths": paths,
            "components": {
                "securitySchemes": {
                    "BearerAuth": {
                        "type": "http",
                        "scheme": "bearer",
                    }
                },
                "schemas": {
                    "ToolResult": normalized_output_schema,
                },
            },
        }
        return self._normalize_openapi_schema(schema)

    def _get_exposure_profile(self) -> str:
        raw = os.getenv(MCP_EXPOSURE_PROFILE_ENV, MCP_EXPOSURE_PROFILE_NORMAL)
        if isinstance(raw, str):
            normalized = raw.strip().lower()
        else:
            normalized = MCP_EXPOSURE_PROFILE_NORMAL
        if normalized in _PROFILE_ORDERS:
            return normalized
        return MCP_EXPOSURE_PROFILE_NORMAL

    def _get_exposed_tool_names(self, profile: str | None = None) -> set[str]:
        profile_name = profile or self.mcp_exposure_profile
        tool_order = _PROFILE_ORDERS.get(profile_name, _PROFILE_ORDERS[MCP_EXPOSURE_PROFILE_NORMAL])
        return set(tool_order)

    def _filter_tools_by_exposure_profile(self, tools: list[MCPToolDef]) -> list[MCPToolDef]:
        allowed = self._get_exposed_tool_names(self.mcp_exposure_profile)
        return [tool for tool in tools if tool.name in allowed]

    def _visible_tool_names(self) -> list[str]:
        return [tool.name for tool in self._filter_tools_by_exposure_profile(self.tool_defs)]

    def _mcp_default_next_reads(self, tool_name: str) -> list[dict[str, Any]]:
        return self._actions_default_next_reads(tool_name)

    def _mcp_recommended_next_reads(
        self,
        tool_name: str,
        params: dict[str, Any],
        tool_result: dict[str, Any],
    ) -> list[dict[str, Any]]:
        return self._actions_recommended_next_reads(tool_name, params, tool_result)

    def _split_mcp_tool_result_meta(self, tool_result: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
        if not isinstance(tool_result, dict):
            return {"ok": False, "tool": "unknown_tool"}, None
        meta = tool_result.get("_meta")
        if not isinstance(meta, dict):
            return tool_result, None
        structured = dict(tool_result)
        structured.pop("_meta", None)
        return structured, copy.deepcopy(meta)

    def _attach_mcp_result_meta(self, result: dict[str, Any], meta: dict[str, Any] | None) -> dict[str, Any]:
        if isinstance(meta, dict):
            result["_meta"] = meta
        return result

    def _shape_mcp_call_result(
        self,
        tool_result: dict[str, Any],
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        structured_tool_result, mcp_meta = self._split_mcp_tool_result_meta(tool_result)
        safe_params = params if isinstance(params, dict) else {}
        is_error = not bool(structured_tool_result.get("ok"))
        tool_name = str(structured_tool_result.get("tool") or "unknown_tool")
        if self._json_char_count(structured_tool_result) <= MCP_TARGET_TOOL_RESULT_CHARS:
            if is_error:
                err_msg = str(structured_tool_result.get("message") or "unknown error")
                text_payload = f"{tool_name} failed: {err_msg}"
            else:
                text_payload = f"{tool_name} completed."
            return self._attach_mcp_result_meta(
                {
                    "content": [{"type": "text", "text": text_payload}],
                    "structuredContent": structured_tool_result,
                    "isError": is_error,
                },
                mcp_meta,
            )
        try:
            data = structured_tool_result.get("data")
            data_keys: list[str] = []
            if isinstance(data, dict):
                data_keys = [str(k) for k in list(data.keys())[:40]]
            omitted_fields = [f"data.{k}" for k in data_keys] if data_keys else ["data"]
            manifest_sc: dict[str, Any] = {
                "ok": bool(structured_tool_result.get("ok")),
                "tool": tool_name,
                "packaged": True,
                "package_mode": "manifest",
                "message": "结果内容较大，已返回摘要与续读建议。",
                "summary": {
                    "result_char_estimate": self._json_char_count(structured_tool_result),
                    "target_tool_result_chars": MCP_TARGET_TOOL_RESULT_CHARS,
                    "hard_tool_result_chars": MCP_HARD_TOOL_RESULT_CHARS,
                    "data_key_count": len(data.keys()) if isinstance(data, dict) else 0,
                    "data_keys": data_keys,
                    "original_error_code": structured_tool_result.get("error_code"),
                },
                "omitted_fields": omitted_fields,
                "recommended_next_reads": self._mcp_recommended_next_reads(tool_name, safe_params, structured_tool_result),
            }
            if not manifest_sc["ok"] and isinstance(structured_tool_result.get("error_code"), str):
                manifest_sc["error_code"] = structured_tool_result.get("error_code")
            manifest_text = json.dumps(manifest_sc, ensure_ascii=False)
            packaged_result = {
                "content": [{"type": "text", "text": manifest_text}],
                "structuredContent": manifest_sc,
                "isError": is_error,
            }
            if self._json_char_count(packaged_result) <= MCP_HARD_TOOL_RESULT_CHARS:
                return self._attach_mcp_result_meta(packaged_result, mcp_meta)

            reduced_sc = {
                "ok": bool(structured_tool_result.get("ok")),
                "tool": tool_name,
                "packaged": True,
                "package_mode": "manifest",
                "message": "结果内容较大，已返回最小续读提示。",
                "summary": {
                    "result_char_estimate": self._json_char_count(structured_tool_result),
                    "target_tool_result_chars": MCP_TARGET_TOOL_RESULT_CHARS,
                    "hard_tool_result_chars": MCP_HARD_TOOL_RESULT_CHARS,
                },
                "omitted_fields": ["data"],
                "recommended_next_reads": self._mcp_recommended_next_reads(tool_name, safe_params, structured_tool_result)[:2],
            }
            if not reduced_sc["ok"] and isinstance(structured_tool_result.get("error_code"), str):
                reduced_sc["error_code"] = structured_tool_result.get("error_code")
            reduced_text = json.dumps(reduced_sc, ensure_ascii=False)
            reduced_result = {
                "content": [{"type": "text", "text": reduced_text}],
                "structuredContent": reduced_sc,
                "isError": is_error,
            }
            if self._json_char_count(reduced_result) <= MCP_HARD_TOOL_RESULT_CHARS:
                return self._attach_mcp_result_meta(reduced_result, mcp_meta)
        except Exception:
            pass

        fallback_sc = {
            "ok": False,
            "tool": tool_name,
            "packaged": True,
            "error_code": "MCP_RESULT_SHAPING_FAILED",
            "message": "工具结果过大且摘要失败，请按续读建议分步读取。",
            "recommended_next_reads": self._mcp_default_next_reads(tool_name),
        }
        fallback_text = json.dumps(fallback_sc, ensure_ascii=False)
        return {
            "content": [{"type": "text", "text": fallback_text}],
            "structuredContent": fallback_sc,
            "isError": True,
        }

    def _as_mcp_call_result(
        self,
        tool_result: dict[str, Any],
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._shape_mcp_call_result(tool_result, params)

    @staticmethod
    def _sanitized_connector_evidence_schema(description: str) -> dict[str, Any]:
        return {
            "type": "object",
            "description": description,
            "properties": {
                "status": {"type": "string"},
                "reason_code": {"type": "string"},
                "evidence_source": {"type": "string"},
                "last_observed_at": {"type": "string"},
            },
            "additionalProperties": False,
        }

    def _commander_app_input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": "必填。服务模式下指定已登记 project_name。",
                },
                "profile_id": {
                    "type": "string",
                    "enum": [
                        "web_gpt_commander",
                        "local_codex_commander",
                        "planner_agent",
                        "reviewer_agent",
                        "source_observer",
                    ],
                    "description": "可选。指定 Commander 内嵌 agent flow 所属 persona；默认 web_gpt_commander。",
                },
                "tunnel_client": self._sanitized_connector_evidence_schema(
                    "可选。调用方提供的 sanitized tunnel-client 状态，只采信 status/reason_code/evidence_source/last_observed_at。"
                ),
                "control_plane": self._sanitized_connector_evidence_schema(
                    "可选。调用方提供的 sanitized tunnel control-plane 状态，只采信 status/reason_code/evidence_source/last_observed_at。"
                ),
            },
            "required": [],
            "additionalProperties": False,
        }

    def _full_loop_authority_input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": "必填。服务模式下指定已登记 project_name。",
                },
                "enable_full_loop": {
                    "type": "boolean",
                    "description": "可选。显式请求检查完整闭环控制项；默认 false。",
                },
                "confirmation_mode": {
                    "type": "string",
                    "enum": ["preview_confirm", "preview-confirm"],
                    "description": "可选。完整闭环必须使用 preview_confirm。",
                },
                "operator_confirmation_ref": {
                    "type": "string",
                    "description": "可选。外部确认引用；返回中只报告是否存在，不回显原文。",
                },
                "allow_executor_run": {"type": "boolean"},
                "allow_validation_run": {"type": "boolean"},
                "allow_local_commit": {"type": "boolean"},
                "allow_remote_push": {"type": "boolean"},
                "allow_stable_replacement": {"type": "boolean"},
            },
            "required": [],
            "additionalProperties": False,
        }

    def _release_submission_input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": "必填。服务模式下指定已登记 project_name。",
                },
                "app_name": {"type": "string"},
                "app_description": {"type": "string"},
                "company_url": {"type": "string"},
                "privacy_policy_url": {"type": "string"},
                "logo_ready": {"type": "boolean"},
                "screenshots_ready": {"type": "boolean"},
                "test_prompts_ready": {"type": "boolean"},
                "test_responses_ready": {"type": "boolean"},
                "localization_ready": {"type": "boolean"},
                "mcp_tool_info_ready": {"type": "boolean"},
                "app_management_permissions_confirmed": {"type": "boolean"},
                "security_review_ready": {"type": "boolean"},
                "metadata_snapshot_reviewed": {"type": "boolean"},
                "submission_confirmations_ready": {"type": "boolean"},
                "submission_materials": {
                    "type": "object",
                    "description": "可选。结构化 release/submission materials manifest；不会读取本机文件路径。",
                    "properties": {
                        "schema_version": {"type": "string"},
                        "app_name": {"type": "string"},
                        "app_description": {"type": "string"},
                        "company_url": {"type": "string"},
                        "privacy_policy_url": {"type": "string"},
                        "logo_ready": {"type": "boolean"},
                        "screenshots_ready": {"type": "boolean"},
                        "test_prompts_ready": {"type": "boolean"},
                        "test_responses_ready": {"type": "boolean"},
                        "localization_ready": {"type": "boolean"},
                        "mcp_tool_info_ready": {"type": "boolean"},
                        "app_management_permissions_confirmed": {"type": "boolean"},
                        "security_review_ready": {"type": "boolean"},
                        "metadata_snapshot_reviewed": {"type": "boolean"},
                        "submission_confirmations_ready": {"type": "boolean"},
                        "evidence": {"type": "object", "additionalProperties": True},
                        "notes": {"type": "string"},
                    },
                    "additionalProperties": True,
                },
            },
            "required": [],
            "additionalProperties": False,
        }

    def _submission_evidence_fill_preview_input_schema(self) -> dict[str, Any]:
        evidence_keys = [
            "logo",
            "screenshots",
            "test_prompts",
            "test_responses",
            "localization",
            "mcp_tool_info",
            "app_management_permissions",
            "security_review",
            "metadata_snapshot",
            "submission_confirmations",
        ]
        return {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": "必填。服务模式下指定已登记 project_name。",
                },
                "selected_keys": {
                    "type": "array",
                    "description": "可选。只为选中的 evidence key 生成 fill payload 预览；不写文件。",
                    "items": {"type": "string", "enum": evidence_keys},
                },
            },
            "required": [],
            "additionalProperties": False,
        }

    def _submission_evidence_auto_draft_input_schema(self) -> dict[str, Any]:
        auto_keys = ["mcp_tool_info", "security_review", "metadata_snapshot"]
        return {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": "必填。服务模式下指定已登记 project_name。",
                },
                "selected_keys": {
                    "type": "array",
                    "description": "可选。只为可自动预填的 evidence key 生成草稿；不写文件。",
                    "items": {"type": "string", "enum": auto_keys},
                },
            },
            "required": [],
            "additionalProperties": False,
        }

    def _init_submission_evidence_input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": "必填。服务模式下指定已登记 project_name。",
                },
                "app_name": {"type": "string"},
                "app_description": {"type": "string"},
                "company_url": {"type": "string"},
                "privacy_policy_url": {"type": "string"},
            },
            "required": [],
            "additionalProperties": False,
        }

    def _fill_submission_evidence_input_schema(self) -> dict[str, Any]:
        evidence_keys = [
            "logo",
            "screenshots",
            "test_prompts",
            "test_responses",
            "localization",
            "mcp_tool_info",
            "app_management_permissions",
            "security_review",
            "metadata_snapshot",
            "submission_confirmations",
        ]
        return {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": "必填。服务模式下指定已登记 project_name。",
                },
                "entries": {
                    "type": "array",
                    "description": "要写入的 evidence 条目。内容由操作者提供；文件会被限制在 docs/submission/*.md。",
                    "items": {
                        "type": "object",
                        "properties": {
                            "key": {"type": "string", "enum": evidence_keys},
                            "filename": {
                                "type": "string",
                                "description": "可选。文件名或 docs/submission/*.md 相对路径；不接受 .todo.md。",
                            },
                            "content": {"type": "string"},
                        },
                        "required": ["key", "content"],
                        "additionalProperties": False,
                    },
                },
                "mark_ready": {
                    "type": "boolean",
                    "description": "显式为 true 时，才把对应 manifest ready 字段标记为 true。",
                },
            },
            "required": ["entries"],
            "additionalProperties": False,
        }

    def _mark_submission_evidence_ready_input_schema(self) -> dict[str, Any]:
        evidence_keys = [
            "logo",
            "screenshots",
            "test_prompts",
            "test_responses",
            "localization",
            "mcp_tool_info",
            "app_management_permissions",
            "security_review",
            "metadata_snapshot",
            "submission_confirmations",
        ]
        return {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": "必填。服务模式下指定已登记 project_name。",
                },
                "keys": {
                    "type": "array",
                    "description": "已由人工审查、且 evidence 引用存在非 .todo 文件的 key。",
                    "items": {"type": "string", "enum": evidence_keys},
                    "minItems": 1,
                },
                "review_confirmation": {
                    "type": "string",
                    "description": "必须为 human_reviewed，表示操作者已人工确认这些 evidence 可标 ready。",
                    "enum": ["human_reviewed"],
                },
            },
            "required": ["keys", "review_confirmation"],
            "additionalProperties": False,
        }

    def _product_console_action_result_input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": "必填。服务模式下指定已登记 managed project_name。",
                },
                "action_id": {
                    "type": "string",
                    "description": "推荐动作的 action_id；用于把结果重新附着到 Product Console action card。",
                },
                "tool": {
                    "type": "string",
                    "description": "被调用的 MCP tool 名称。",
                },
                "mode": {
                    "type": "string",
                    "enum": ["read", "preview", "commit"],
                    "description": "动作模式；默认 read。",
                },
                "status": {
                    "type": "string",
                    "enum": ["pending", "updated", "requested", "blocked", "failed"],
                    "description": "最近一次动作结果状态。",
                },
                "message": {
                    "type": "string",
                    "description": "短操作摘要；服务端会 redaction 和截断，不应传 raw tool output。",
                },
                "result_ok": {
                    "type": "boolean",
                    "description": "可选。原始工具结果是否成功；不存储 raw result。",
                },
                "action_fingerprint": {
                    "type": "string",
                    "description": "可选。Product Console action_fingerprint；用于识别旧结果是否仍匹配当前动作参数和结果契约。",
                },
            },
            "required": ["status"],
            "additionalProperties": False,
        }

    def _agent_operator_flow_input_schema(self) -> dict[str, Any]:
        stage_schema = _stage_parallel_preview_input_schema()
        properties = {
            "project_name": {
                "type": "string",
                "description": "必填。服务模式下指定已登记 project_name。",
            },
            "profile_id": {
                "type": "string",
                "enum": [
                    "web_gpt_commander",
                    "local_codex_commander",
                    "planner_agent",
                    "reviewer_agent",
                    "source_observer",
                ],
                "description": "可选。调用方 agent profile；默认 web_gpt_commander。",
            },
            "task_mode": {
                "type": "string",
                "enum": [
                    "auto",
                    "ordinary_task",
                    "parallel_stage",
                    "planning",
                    "review",
                    "source_observation",
                    "connector_smoke",
                    "readiness",
                ],
                "description": "可选。希望 ColaMeta 压缩的使用流程；默认 auto。",
            },
            "task_brief": {
                "type": "string",
                "description": "可选。当前任务一句话摘要；用于生成 thin governed loop draft seed，不作为执行授权。",
            },
            "include_advanced_context": {
                "type": "boolean",
                "description": "可选。是否返回高级上下文摘要；默认 true。",
            },
            "tunnel_client": self._sanitized_connector_evidence_schema(
                "可选。调用方提供的 sanitized tunnel-client 状态，只采信 status/reason_code/evidence_source/last_observed_at。"
            ),
            "control_plane": self._sanitized_connector_evidence_schema(
                "可选。调用方提供的 sanitized tunnel control-plane 状态，只采信 status/reason_code/evidence_source/last_observed_at。"
            ),
        }
        for key in ("stage_id", "provider", "base_branch", "max_parallel_tasks", "task_intents"):
            properties[key] = stage_schema["properties"][key]
        return {
            "type": "object",
            "properties": properties,
            "required": [],
            "additionalProperties": False,
        }

    def _build_common_output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "ok": {
                    "type": "boolean",
                    "description": "Whether the tool call succeeded.",
                },
                "tool": {
                    "type": "string",
                    "description": "Tool name.",
                },
                "data": {
                    "type": "object",
                    "description": "Structured payload returned by the tool.",
                    "additionalProperties": True,
                },
                "error_code": {
                    "type": "string",
                    "description": "Machine-readable error code when ok is false.",
                },
                "message": {
                    "type": "string",
                    "description": "Human-readable message.",
                },
                "details": {
                    "type": "object",
                    "description": "Additional structured error details.",
                    "additionalProperties": True,
                },
                "packaged": {
                    "type": "boolean",
                    "description": "Whether a large response was replaced by a compact manifest.",
                },
                "package_mode": {
                    "type": "string",
                    "description": "Large-response packaging mode, for example manifest.",
                },
                "summary": {
                    "type": "object",
                    "description": "Summary for a packaged large response.",
                    "additionalProperties": True,
                },
                "omitted_fields": {
                    "type": "array",
                    "description": "Fields omitted from a packaged large response.",
                    "items": {"type": "string"},
                },
                "recommended_next_reads": {
                    "type": "array",
                    "description": "Suggested smaller follow-up reads when a large response is packaged.",
                    "items": {
                        "type": "object",
                        "additionalProperties": True,
                    },
                },
            },
            "required": ["ok", "tool"],
            "additionalProperties": False,
        }

    def _json_char_count(self, payload: Any) -> int:
        try:
            return len(json.dumps(payload, ensure_ascii=False))
        except Exception:
            return 10**9

    def _is_actions_request_too_large(self, raw: bytes) -> bool:
        if not raw:
            return False
        try:
            body_text = raw.decode("utf-8")
        except Exception:
            return len(raw) > ACTIONS_HARD_REQUEST_CHARS
        return len(body_text) > ACTIONS_HARD_REQUEST_CHARS

    def _actions_request_too_large_payload(self, tool_name: str) -> dict[str, Any]:
        return {
            "ok": False,
            "tool": tool_name,
            "error_code": "ACTION_REQUEST_TOO_LARGE",
            "message": "Actions 请求体过大，请拆分请求后重试。",
            "recommended_next_reads": [
                {
                    "tool": "manage_files",
                    "arguments": {"action": "edit", "phase": "preview"},
                    "reason": "将大 patch 拆成多个 preview 分批提交。",
                },
                {
                    "tool": "manage_executor_workflow",
                    "arguments": {"action": "preflight"},
                    "reason": "复杂改动优先使用受控执行器工作流。",
                },
            ],
        }

    def _actions_default_next_reads(self, tool_name: str) -> list[dict[str, Any]]:
        return [
            {
                "tool": "analyze_project_state",
                "arguments": {"include_repo_overview": False, "include_reports": False},
                "reason": "先读取项目摘要，再按需调用细粒度工具。",
            },
            {
                "tool": tool_name,
                "arguments": {},
                "reason": "缩小参数范围后重试当前工具。",
            },
        ]

    def _actions_recommended_next_reads(
        self,
        tool_name: str,
        params: dict[str, Any],
        tool_result: dict[str, Any],
    ) -> list[dict[str, Any]]:
        normalized_tool = str(tool_name or "").strip()
        if normalized_tool == "get_review_context":
            suggestions: list[dict[str, Any]] = [
                {
                    "tool": "manage_git",
                    "arguments": {"action": "diff", "mode": "summary"},
                    "reason": "先读取 diff 摘要再进入文件级审阅。",
                },
                {
                    "tool": "manage_git",
                    "arguments": {"action": "review_context", "include_repo_overview": False, "max_diff_chars": 20000},
                    "reason": "降低 diff 大小后读取上下文。",
                },
            ]
            data = tool_result.get("data")
            if isinstance(data, dict):
                changed_files = data.get("changed_files")
                if isinstance(changed_files, list):
                    first_file = next((x for x in changed_files if isinstance(x, str) and x.strip()), None)
                    if first_file:
                        suggestions.append(
                            {
                                "tool": "manage_git",
                                "arguments": {"action": "diff", "mode": "page", "file": first_file, "offset": 0, "max_chars": 30000},
                                "reason": "按文件分页续读 diff。",
                            }
                        )
            return suggestions
        if normalized_tool == "get_git_diff":
            suggestions = [
                {
                    "tool": "manage_git",
                    "arguments": {"action": "diff", "mode": "summary"},
                    "reason": "先读取变更文件摘要。",
                },
                {
                    "tool": "manage_git",
                    "arguments": {"action": "diff", "mode": "page", "offset": 0, "max_chars": 30000},
                    "reason": "分页读取单文件 diff。",
                },
            ]
            include_files = params.get("include_files")
            if isinstance(include_files, list):
                normalized_files = [x for x in include_files if isinstance(x, str) and x.strip()][:3]
                if normalized_files:
                    suggestions.append(
                        {
                            "tool": "manage_git",
                            "arguments": {"action": "diff", "mode": "files", "include_files": normalized_files, "max_chars": 30000},
                            "reason": "按文件子集续读 diff。",
                        }
                    )
            return suggestions
        if normalized_tool == "get_source_file":
            target_file = params.get("file") if isinstance(params.get("file"), str) else ""
            suggestions = []
            if target_file:
                suggestions.append(
                    {
                        "tool": "get_source_file",
                        "arguments": {"file": target_file, "start_line": 1, "end_line": 200, "max_chars": 20000},
                        "reason": "按行范围读取源码。",
                    }
                )
            suggestions.append(
                {
                    "tool": "search_source",
                    "arguments": {"query": "TODO", "max_results": 30},
                    "reason": "先定位关键片段再读取局部源码。",
                }
            )
            return suggestions
        if normalized_tool == "manage_files":
            action_name = params.get("action")
            if isinstance(action_name, str) and action_name.strip().lower() == "edit":
                return [
                    {
                        "tool": "manage_files",
                        "arguments": {"action": "edit", "phase": "preview", "max_diff_chars": 12000, "max_files": 3},
                        "reason": "拆小 patch 预览，分批确认。",
                    },
                    {
                        "tool": "manage_executor_workflow",
                        "arguments": {"action": "preflight"},
                        "reason": "复杂改动可转为执行器受控流程。",
                    },
                ]
            target_file = params.get("file") if isinstance(params.get("file"), str) else ""
            suggestions = []
            if target_file:
                suggestions.append(
                    {
                        "tool": "manage_files",
                        "arguments": {"action": "read", "file": target_file, "start_line": 1, "end_line": 200, "max_chars": 20000},
                        "reason": "按行范围读取源码。",
                    }
                )
            suggestions.append(
                {
                    "tool": "manage_files",
                    "arguments": {"action": "search", "query": "TODO", "max_results": 30},
                    "reason": "先定位关键片段再读取局部源码。",
                }
            )
            return suggestions
        if normalized_tool == "manage_git_commit":
            action = params.get("action")
            action_name = action.strip().lower() if isinstance(action, str) else ""
            if action_name in {"readiness", "preview", "commit_workflow_preview", "suggest_commit_message"}:
                return [
                    {
                        "tool": "manage_git",
                        "arguments": {"action": "commit_readiness", "include_diff_summary": False, "max_diff_chars": 20000},
                        "reason": "关闭大 diff 摘要并缩小字符上限。",
                    },
                    {
                        "tool": "manage_git",
                        "arguments": {"action": "diff", "mode": "summary"},
                        "reason": "使用 diff 摘要替代内嵌大 diff。",
                    },
                    {
                        "tool": "manage_git",
                        "arguments": {"action": "diff", "mode": "page", "offset": 0, "max_chars": 30000},
                        "reason": "按文件分页读取具体差异。",
                    },
                ]
        if normalized_tool == "manage_project_docs":
            action = params.get("action")
            action_name = action.strip().lower() if isinstance(action, str) else ""
            if action_name in {"read_section", "search", "index"}:
                return [
                    {
                        "tool": "manage_project_docs",
                        "arguments": {"action": action_name or "search", "max_chars": 8000, "max_files": 20},
                        "reason": "缩小文档读取范围与字符数。",
                    }
                ]
        if normalized_tool == "manage_git_history":
            action = params.get("action")
            action_name = action.strip().lower() if isinstance(action, str) else ""
            if action_name in {"show", "diff_commits", "revert_preview"}:
                action_map = {"show": "history_show"}
                mg_action = action_map.get(action_name, action_name)
                read_args: dict[str, Any] = {"action": mg_action, "max_chars": 20000}
                if action_name == "show":
                    read_args["include_patch"] = False
                for key in ("commit", "base", "head", "file"):
                    val = params.get(key)
                    if isinstance(val, str) and val.strip():
                        read_args[key] = val
                return [
                    {
                        "tool": "manage_git",
                        "arguments": read_args,
                        "reason": "使用较小 max_chars 或禁用 patch 续读。",
                    }
                ]
        if normalized_tool == "get_executor_run_report":
            args: dict[str, Any] = {"latest": True, "include_markdown": False}
            for key in ("version", "report_id"):
                val = params.get(key)
                if isinstance(val, str) and val.strip():
                    args[key] = val.strip()
            return [
                {
                    "tool": "get_executor_run_report",
                    "arguments": args,
                    "reason": "先读取结构化报告，按需再取 markdown。",
                },
                {
                    "tool": "get_executor_run_report",
                    "arguments": {**args, "include_markdown": True, "max_markdown_chars": 12000},
                    "reason": "缩小 markdown 字符数分步读取。",
                },
            ]
        if normalized_tool in {"manage_workflow_run", "list_workflow_runs"}:
            action_name = params.get("action")
            action_name = action_name.strip().lower() if isinstance(action_name, str) else "list"
            if action_name == "get":
                workflow_id = params.get("workflow_id")
                if isinstance(workflow_id, str) and workflow_id.strip():
                    return [
                        {
                            "tool": "manage_workflow_run",
                            "arguments": {"action": "get", "workflow_id": workflow_id.strip()},
                            "reason": "按单个 workflow_id 续读。",
                        }
                    ]
            return [
                {
                    "tool": "manage_workflow_run",
                    "arguments": {"action": "list", "limit": 20},
                    "reason": "缩小 workflow run 列表返回规模。",
                }
            ]
        if normalized_tool == "get_workflow_run":
            workflow_id = params.get("workflow_id")
            if isinstance(workflow_id, str) and workflow_id.strip():
                return [
                    {
                        "tool": "manage_workflow_run",
                        "arguments": {"action": "get", "workflow_id": workflow_id.strip()},
                        "reason": "按单个 workflow_id 续读。",
                    }
                ]
        return self._actions_default_next_reads(normalized_tool or "unknown_tool")

    def _package_actions_rest_response(
        self,
        tool_name: str,
        params: dict[str, Any],
        tool_result: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            sanitized_tool_result = self._actions_sanitize_tool_result(tool_result)
            response_chars = self._json_char_count(sanitized_tool_result)
            if response_chars <= ACTIONS_TARGET_RESPONSE_CHARS:
                return sanitized_tool_result
            ok_value = bool(sanitized_tool_result.get("ok"))
            data = sanitized_tool_result.get("data")
            data_keys: list[str] = []
            if isinstance(data, dict):
                data_keys = [str(k) for k in list(data.keys())[:40]]
            omitted_fields = [f"data.{k}" for k in data_keys] if data_keys else ["data"]
            summary: dict[str, Any] = {
                "response_char_estimate": response_chars,
                "target_response_chars": ACTIONS_TARGET_RESPONSE_CHARS,
                "hard_response_chars": ACTIONS_HARD_RESPONSE_CHARS,
                "data_key_count": len(data.keys()) if isinstance(data, dict) else 0,
                "data_keys": data_keys,
                "original_error_code": sanitized_tool_result.get("error_code"),
            }
            manifest: dict[str, Any] = {
                "ok": ok_value,
                "tool": tool_name,
                "packaged": True,
                "package_mode": "manifest",
                "message": "响应内容较大，已返回摘要与续读建议。",
                "summary": summary,
                "omitted_fields": omitted_fields,
                "recommended_next_reads": self._actions_recommended_next_reads(tool_name, params, sanitized_tool_result),
            }
            if not ok_value and isinstance(sanitized_tool_result.get("error_code"), str):
                manifest["error_code"] = sanitized_tool_result.get("error_code")
            if self._json_char_count(manifest) <= ACTIONS_HARD_RESPONSE_CHARS:
                return manifest
            reduced_manifest: dict[str, Any] = {
                "ok": ok_value,
                "tool": tool_name,
                "packaged": True,
                "package_mode": "manifest",
                "message": "响应内容较大，已返回最小续读提示。",
                "summary": {
                    "response_char_estimate": response_chars,
                    "target_response_chars": ACTIONS_TARGET_RESPONSE_CHARS,
                    "hard_response_chars": ACTIONS_HARD_RESPONSE_CHARS,
                },
                "omitted_fields": ["data"],
                "recommended_next_reads": self._actions_recommended_next_reads(tool_name, params, sanitized_tool_result)[:2],
            }
            if not ok_value and isinstance(sanitized_tool_result.get("error_code"), str):
                reduced_manifest["error_code"] = sanitized_tool_result.get("error_code")
            if self._json_char_count(reduced_manifest) <= ACTIONS_HARD_RESPONSE_CHARS:
                return reduced_manifest
            return {
                "ok": False,
                "tool": tool_name,
                "packaged": True,
                "error_code": "ACTION_RESPONSE_TOO_LARGE",
                "message": "响应体超过安全上限，请使用推荐的续读工具。",
                "recommended_next_reads": self._actions_default_next_reads(tool_name),
            }
        except Exception:
            return {
                "ok": False,
                "tool": tool_name,
                "error_code": "ACTION_RESPONSE_PACKAGING_FAILED",
                "message": "Actions 响应包装失败，请缩小请求范围后重试。",
                "recommended_next_reads": self._actions_default_next_reads(tool_name),
            }

    def project_name_required_guidance(
        self,
        tool_name: str,
        *,
        include_available_projects: bool = False,
    ) -> tuple[str, dict[str, Any]]:
        available_names: list[str] = []
        hint = "请先调用 list_registered_projects 查看可用项目，然后重试并传入 project_name。"
        if include_available_projects:
            try:
                projects = self.project_registry.list_projects().get("projects", [])
            except Exception:
                projects = []
            if isinstance(projects, list):
                for project in projects:
                    if not isinstance(project, dict):
                        continue
                    name = project.get("project_name")
                    if isinstance(name, str) and name.strip() and name.strip() not in available_names:
                        available_names.append(name.strip())
            if available_names:
                sample = ", ".join(available_names[:6])
                hint = f"已登记 project_name 示例：{sample}。如需完整列表，请先调用 list_registered_projects。"
        message = f"服务模式下项目级工具必须显式提供已登记 project_name，不能使用默认项目。{hint}"
        details = {
            "tool": tool_name,
            "required_param": "project_name",
            "next_action": "call list_registered_projects, then retry this tool with project_name",
        }
        if include_available_projects:
            details["available_project_names"] = available_names[:20]
        return message, details

    def _call_tool(
        self,
        name: Any,
        params: Any,
        auth_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(name, str) or not name:
            return self._tool_error("unknown", "INVALID_TOOL", "tool 名称无效。")
        if name == "apply_plan_patch":
            return self._tool_error(
                "apply_plan_patch",
                "TOOL_NOT_EXPOSED",
                "apply_plan_patch is intentionally not exposed over MCP. Runner applies pending patches locally via Web Console or CLI.",
            )
        tool = self.tools.get(name)
        if tool is None:
            return self._tool_error(name, "TOOL_NOT_FOUND", f"未知 tool：{name}")
        if params is None:
            params = {}
        if not isinstance(params, dict):
            return self._tool_error(name, "INVALID_PARAMS", "tool 参数必须是 JSON 对象。")
        if (self.service_mode or auth_context is not None) and name in PROJECT_NAME_REQUIRED_TOOLS:
            project_name = params.get("project_name")
            if not isinstance(project_name, str) or not project_name.strip():
                include_available_projects = self.service_mode and auth_context is None
                message, details = self.project_name_required_guidance(
                    name,
                    include_available_projects=include_available_projects,
                )
                return self._tool_error(
                    name,
                    "PROJECT_NAME_REQUIRED",
                    message,
                    details,
                )
        policy_error = self._tool_policy_error(name, params)
        if policy_error is not None:
            return policy_error
        scope_error = self._oauth_scope_error(name, params, auth_context)
        if scope_error is not None:
            return scope_error
        remote_policy_error = self._external_oauth_remote_policy_error(name, params, auth_context)
        if remote_policy_error is not None:
            return remote_policy_error
        relay_scope_error = self._cloud_relay_scope_error(name, params, auth_context)
        if relay_scope_error is not None:
            return relay_scope_error
        try:
            data = tool(params)
            result = {"ok": True, "tool": name, "data": data}
            if isinstance(data, dict) and isinstance(data.get("_meta"), dict):
                clean_data = dict(data)
                result["_meta"] = copy.deepcopy(clean_data.pop("_meta"))
                result["data"] = clean_data
            return result
        except MCPToolInputError as e:
            return self._tool_error(name, e.error_code, e.message, e.details)
        except PlanningBridgeError as e:
            return self._tool_error(name, "BRIDGE_ERROR", str(e))
        except SourceReviewError as e:
            return self._tool_error(name, "SOURCE_REVIEW_ERROR", str(e))
        except Exception as e:
            return self._tool_error(name, "TOOL_EXEC_ERROR", "工具执行失败。", {"message": str(e)})

    def call_tool_for_agent(
        self,
        name: str,
        arguments: dict[str, Any],
        auth_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._call_tool(name, arguments, auth_context=auth_context)

    def get_required_scope_for_tool(self, name: str, arguments: dict[str, Any]) -> str:
        return self._required_scope_for_tool(name, arguments)

    def _required_scope_for_tool(self, name: str, params: dict[str, Any]) -> str:
        return self._tool_policy_scope(name, params) or "mcp:unknown"

    def _tool_policy_scope(self, name: str, params: dict[str, Any]) -> str | None:
        policy = MCP_TOOL_POLICIES.get(name)
        if policy is None:
            return None
        scope = policy.scope_for(params)
        if scope not in VALID_MCP_SCOPES:
            return None
        return scope

    def _tool_policy_error(self, name: str, params: dict[str, Any]) -> dict[str, Any] | None:
        if self._tool_policy_scope(name, params) is not None:
            return None
        return self._tool_error(
            name,
            "TOOL_POLICY_DENIED",
            "Tool policy is missing or the requested action is not declared.",
            {
                "tool": name,
                "action": _policy_string_param(params, "action"),
                "phase": _policy_string_param(params, "phase"),
                "workflow": _policy_string_param(params, "workflow"),
                "policy": "mcp_tool_registry_fail_closed",
            },
        )

    def _oauth_scope_error(
        self,
        name: str,
        params: dict[str, Any],
        auth_context: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if not isinstance(auth_context, dict) or auth_context.get("mode") not in {"oauth", "external-oauth"}:
            return None
        oauth_provider = auth_context.get("oauth_provider")
        token_payload = auth_context.get("token")
        validate_scope = getattr(oauth_provider, "validate_scope", None)
        if not callable(validate_scope) or not isinstance(token_payload, dict):
            return self._tool_error(name, "UNAUTHORIZED", "OAuth token is invalid.")
        required_scope = self._required_scope_for_tool(name, params)
        if validate_scope(token_payload, required_scope):
            return None
        return self._tool_error(
            name,
            "INSUFFICIENT_SCOPE",
            "OAuth token scope is insufficient for this tool.",
        )

    def _external_oauth_remote_policy_error(
        self,
        name: str,
        params: dict[str, Any],
        auth_context: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if not isinstance(auth_context, dict) or auth_context.get("mode") != "external-oauth":
            return None
        required_scope = self._required_scope_for_tool(name, params)
        if required_scope in {"mcp:read", "mcp:preview"}:
            return None
        reason_code = REMOTE_EXTERNAL_OAUTH_DENIED_SCOPES.get(required_scope, "")
        if not reason_code:
            return None
        action = params.get("action")
        normalized_action = action.strip().lower() if isinstance(action, str) else ""
        return self._tool_error(
            name,
            "REMOTE_POLICY_DENIED",
            "external-oauth remote policy denied this tool action.",
            {
                "policy": REMOTE_EXTERNAL_OAUTH_POLICY,
                "tool": name,
                "action": normalized_action,
                "required_scope": required_scope,
                "reason_code": reason_code,
            },
        )

    def _cloud_relay_scope_error(
        self,
        name: str,
        params: dict[str, Any],
        auth_context: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if not isinstance(auth_context, dict) or auth_context.get("mode") != "cloud-relay":
            return None
        granted_scopes = auth_context.get("scopes", [])
        if not isinstance(granted_scopes, list):
            return self._tool_error(name, "UNAUTHORIZED", "cloud-relay scopes 无效。")
        required_scope = self._required_scope_for_tool(name, params)
        if required_scope in granted_scopes:
            return None
        return self._tool_error(
            name,
            "INSUFFICIENT_SCOPE",
            f"cloud-relay scope 不足，需要 {required_scope}，当前 scopes: {granted_scopes}",
        )

    def _project_identity(self) -> dict[str, Any]:
        return build_project_identity(self.project_root)

    def _project_identity_for_root(self, project_root: str) -> dict[str, Any]:
        return build_project_identity(project_root)

    def _resolve_registered_project_by_name(self, project_name: Any) -> dict[str, Any]:
        if not isinstance(project_name, str) or not project_name.strip():
            raise MCPToolInputError("INVALID_PROJECT_NAME", "project_name 必须是非空字符串。")
        result = self.project_registry.resolve_project_name(project_name.strip())
        if not result.get("ok"):
            raise MCPToolInputError(
                str(result.get("error_code") or "PROJECT_NOT_REGISTERED"),
                str(result.get("message") or "project_name 未登记。"),
                {"project_name": project_name.strip()},
            )
        project = result.get("project")
        if not isinstance(project, dict):
            raise MCPToolInputError("PROJECT_NOT_REGISTERED", "project_name 未登记。", {"project_name": project_name.strip()})
        return project

    def _resolve_managed_project_by_name(self, project_name: Any) -> dict[str, Any]:
        if not isinstance(project_name, str) or not project_name.strip():
            raise MCPToolInputError("INVALID_PROJECT_NAME", "project_name 必须是非空字符串。")
        result = self.project_registry.resolve_managed_project_name(project_name.strip())
        if not result.get("ok"):
            raise MCPToolInputError(
                str(result.get("error_code") or "PROJECT_MODE_UNSUPPORTED"),
                str(result.get("message") or "当前操作需要 managed 项目。"),
                {"project_name": project_name.strip()},
            )
        project = result.get("project")
        if not isinstance(project, dict):
            raise MCPToolInputError("PROJECT_NOT_REGISTERED", "project_name 未登记。", {"project_name": project_name.strip()})
        return project

    def _resolve_read_only_project_context(self, params: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
        project_name = params.get("project_name")
        if project_name is None:
            if self.service_mode:
                raise MCPToolInputError(
                    "PROJECT_NAME_REQUIRED",
                    "项目级调用必须显式提供 project_name；服务不会替 GPTs 选择项目。",
                )
            return self.project_root, None
        project = self._resolve_registered_project_by_name(project_name)
        return str(project.get("project_root") or self.project_root), project

    def _resolve_managed_project_context(self, params: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
        project_name = params.get("project_name")
        if project_name is None:
            if self.service_mode:
                raise MCPToolInputError(
                    "PROJECT_NAME_REQUIRED",
                    "项目级调用必须显式提供 project_name；服务不会替 GPTs 选择项目。",
                )
            return self.project_root, None
        project = self._resolve_managed_project_by_name(project_name)
        return str(project.get("project_root") or self.project_root), project

    def _strip_project_name_param(self, params: dict[str, Any]) -> dict[str, Any]:
        clean = dict(params)
        clean.pop("project_name", None)
        return clean

    def _route_project_name_tool(
        self,
        tool_name: str,
        params: dict[str, Any],
        *,
        require_managed: bool,
    ) -> dict[str, Any]:
        project_root_override = params.get("project_root")
        if isinstance(project_root_override, str) and project_root_override.strip():
            raise MCPToolInputError(
                "PROJECT_ROOT_OVERRIDE_NOT_ALLOWED",
                "project_name 路由不接受 project_root 覆盖。",
            )
        if require_managed:
            project_root, _ = self._resolve_managed_project_context(params)
        else:
            project_root, _ = self._resolve_read_only_project_context(params)
        routed_server = self.__class__(project_root)
        routed_tool = routed_server.tools.get(tool_name)
        if not callable(routed_tool):
            raise MCPToolInputError("TOOL_NOT_FOUND", f"未知 tool：{tool_name}")
        routed_params = self._strip_project_name_param(params)
        routed_params.pop("project_root", None)
        original_project_name = params.get("project_name")
        result = routed_tool(routed_params)
        if isinstance(result, dict) and isinstance(original_project_name, str) and original_project_name.strip():
            self._inject_project_name_into_routed_result(result, original_project_name.strip())
            next_actions = _find_next_actions(result)
            if next_actions is not None:
                for action in next_actions:
                    if isinstance(action, dict):
                        action_params = action.get("params")
                        if isinstance(action_params, dict) and "project_name" not in action_params:
                            action_params["project_name"] = original_project_name.strip()
        return result

    def _inject_project_name_into_routed_result(self, result: dict[str, Any], project_name: str) -> None:
        workflow = result.get("workflow")
        payload_result = result.get("result")
        if workflow != "thin_governed_loop_preview" or not isinstance(payload_result, dict):
            return

        for key in ("next_request_payload", "copy_paste_next_request"):
            payload = payload_result.get(key)
            if isinstance(payload, dict):
                payload["project_name"] = project_name

        bundle_summary = payload_result.get("generated_input_bundle_summary")
        if isinstance(bundle_summary, dict):
            next_shape = bundle_summary.get("next_request_shape")
            if isinstance(next_shape, dict):
                next_shape["project_name"] = project_name

    def _list_registered_projects_payload(self) -> dict[str, Any]:
        listed = self.project_registry.list_projects()
        projects = listed.get("projects")
        if not isinstance(projects, list):
            return listed
        enriched: list[dict[str, Any]] = []
        for item in projects:
            if not isinstance(item, dict):
                continue
            project = dict(item)
            root = str(project.get("project_root") or "")
            project["available"] = os.path.isdir(root)
            if root and os.path.isdir(root):
                project["runner_managed"] = self.project_registry.is_runner_managed_project(root)
            else:
                project["runner_managed"] = False
            enriched.append(project)
        listed["projects"] = enriched
        return listed

    def _with_project_identity(self, result: dict[str, Any], project_root: str | None = None, *, hint_project_name: bool = False) -> dict[str, Any]:
        if isinstance(result, dict) and result.get("ok"):
            result["project_identity"] = self._project_identity_for_root(project_root or self.project_root)
        return result

    def _tool_list_registered_projects(self, _: dict[str, Any]) -> dict[str, Any]:
        return self._list_registered_projects_payload()

    def _service_entry_profiles(self) -> list[dict[str, Any]]:
        def project_args(**extra: Any) -> dict[str, Any]:
            return {"project_name": "<registered project_name>", **extra}

        profiles = [
            {
                "profile_id": "web_gpt_commander",
                "display_name": "Web GPT Commander",
                "consumer_kind": "web_gpt",
                "default_authority": "read_only_evidence_until_commander_authorization",
                "first_reads": [
                    {"tool": "list_registered_projects", "arguments": {}},
                    {"tool": "get_agent_consumer_contract", "arguments": {}},
                    {"tool": "get_agent_operator_flow_packet", "arguments": project_args(profile_id="web_gpt_commander")},
                    {"tool": "get_web_gpt_service_entrypoint", "arguments": project_args()},
                    {"tool": "render_commander_app", "arguments": project_args()},
                    {"tool": "get_stable_replacement_cadence", "arguments": project_args()},
                    {"tool": "get_stable_promotion_readiness", "arguments": project_args()},
                    {"tool": "get_stage_parallel_plan_preview", "arguments": project_args()},
                    {"tool": "get_stage_parallel_run_preview", "arguments": project_args()},
                    {"tool": "get_stage_parallel_worktree_assignment_preview", "arguments": project_args()},
                    {"tool": "get_stage_parallel_next_action_packet", "arguments": project_args()},
                    {"tool": "manage_stage_parallel_shard_inputs", "arguments": {**project_args(), "action": "preview"}},
                    {"tool": "get_stage_parallel_executor_group_preview", "arguments": project_args()},
                    {"tool": "manage_stage_parallel_executor_runs", "arguments": {**project_args(), "action": "preview"}},
                    {"tool": "get_stage_parallel_executor_results_packet", "arguments": project_args()},
                    {"tool": "get_stage_parallel_group_status", "arguments": project_args()},
                    {"tool": "get_stage_parallel_merge_preview", "arguments": project_args()},
                    {"tool": "manage_stage_parallel_merges", "arguments": {**project_args(), "action": "preview"}},
                    {"tool": "get_stage_parallel_closeout_packet", "arguments": project_args()},
                    {"tool": "get_apps_connector_smoke_packet", "arguments": project_args()},
                    {"tool": "get_connector_runtime_health_status", "arguments": project_args()},
                    {"tool": "analyze_project_state", "arguments": project_args()},
                ],
                "primary_workflow": "thin_governed_loop_preview",
                "next_payload_rule": (
                    "Use draft first. For M0-M2 local work, require codex_execution_packet.packet_status=ready, then copy "
                    "codex_execution_packet.copy_paste_codex_prompt to local Codex; "
                    "send next_request_payload only when formal evidence preview is needed."
                ),
                "write_boundary": "Requires exact Commander authorization for write/run/push/stable promotion.",
            },
            {
                "profile_id": "local_codex_commander",
                "display_name": "Local Codex Commander",
                "consumer_kind": "local_codex",
                "default_authority": "local_repo_work_with_project_boundaries",
                "first_reads": [
                    {"tool": "list_registered_projects", "arguments": {}},
                    {"tool": "get_agent_consumer_contract", "arguments": {}},
                    {"tool": "get_agent_operator_flow_packet", "arguments": project_args(profile_id="local_codex_commander")},
                    {"tool": "analyze_project_state", "arguments": project_args()},
                    {"tool": "get_connector_runtime_health_status", "arguments": project_args()},
                    {"tool": "get_stage_parallel_group_status", "arguments": project_args()},
                    {"tool": "manage_workflow_run", "arguments": project_args(action="list", limit=10)},
                    {"tool": "list_executor_run_reports", "arguments": project_args(limit=10)},
                ],
                "primary_workflow": "thin_governed_loop_preview plus local code/test loop",
                "next_payload_rule": "Use MCP for routing/evidence; keep code edits inside the local repo boundary.",
                "write_boundary": "Local repo writes follow workspace rules; MCP read-only outputs do not authorize Delivery State changes.",
            },
            {
                "profile_id": "reviewer_agent",
                "display_name": "Reviewer Agent",
                "consumer_kind": "reviewer",
                "default_authority": "review_only",
                "first_reads": [
                    {"tool": "list_registered_projects", "arguments": {}},
                    {"tool": "get_agent_consumer_contract", "arguments": {}},
                    {"tool": "get_agent_operator_flow_packet", "arguments": project_args(profile_id="reviewer_agent")},
                    {"tool": "analyze_project_state", "arguments": project_args()},
                    {"tool": "manage_workflow_run", "arguments": project_args(action="list", limit=20)},
                    {"tool": "list_executor_run_reports", "arguments": project_args(limit=20)},
                ],
                "primary_workflow": "evidence_review",
                "next_payload_rule": "Report findings as review evidence only.",
                "write_boundary": "Does not create ReviewDecision, GateEvent, or accepted Delivery State.",
            },
            {
                "profile_id": "planner_agent",
                "display_name": "Planner Agent",
                "consumer_kind": "planner",
                "default_authority": "plan_preview_only",
                "first_reads": [
                    {"tool": "list_registered_projects", "arguments": {}},
                    {"tool": "get_agent_consumer_contract", "arguments": {}},
                    {"tool": "get_agent_operator_flow_packet", "arguments": project_args(profile_id="planner_agent")},
                    {"tool": "get_web_gpt_service_entrypoint", "arguments": project_args()},
                    {
                        "tool": "run_mcp_workflow",
                        "arguments": project_args(
                            workflow="thin_governed_loop_preview",
                            phase="preview",
                            input_mode="draft",
                        ),
                    },
                ],
                "primary_workflow": "thin_governed_loop_preview",
                "next_payload_rule": "Produce draft/provided input payloads; do not dispatch execution.",
                "write_boundary": "Planning preview is not executor authority or review acceptance.",
            },
            {
                "profile_id": "source_observer",
                "display_name": "Source Observer",
                "consumer_kind": "source_observer",
                "default_authority": "source_read_only",
                "first_reads": [
                    {"tool": "list_registered_projects", "arguments": {}},
                    {"tool": "get_agent_consumer_contract", "arguments": {}},
                    {"tool": "get_agent_operator_flow_packet", "arguments": project_args(profile_id="source_observer")},
                    {"tool": "analyze_project_state", "arguments": project_args()},
                    {"tool": "get_runtime_version_status", "arguments": project_args()},
                ],
                "primary_workflow": "source_observation",
                "next_payload_rule": "Use source facts for orientation; managed workflows may be unavailable for source-only projects.",
                "write_boundary": "No managed workflow adoption, execution, or state transition.",
            },
        ]
        for profile in profiles:
            profile_id = str(profile.get("profile_id") or "")
            profile["executor_status_polling_guidance"] = polling_guidance_for_profile(profile_id)
        return profiles

    def _select_service_entry_profile(self, params: dict[str, Any]) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
        profiles = self._service_entry_profiles()
        profile_by_id = {item["profile_id"]: item for item in profiles if isinstance(item.get("profile_id"), str)}
        raw_profile_id = params.get("profile_id")
        if raw_profile_id is None or raw_profile_id == "":
            profile_id = "web_gpt_commander"
        elif isinstance(raw_profile_id, str):
            profile_id = raw_profile_id.strip()
        else:
            raise MCPToolInputError(
                "INVALID_SERVICE_ENTRY_PROFILE",
                "profile_id 必须是字符串。",
                {"available_profile_ids": list(profile_by_id)},
            )
        if profile_id not in profile_by_id:
            raise MCPToolInputError(
                "UNKNOWN_SERVICE_ENTRY_PROFILE",
                "未知服务入口画像。",
                {"profile_id": profile_id, "available_profile_ids": list(profile_by_id)},
            )
        return profile_id, profile_by_id[profile_id], profiles

    def _tool_get_service_entry_profile(self, params: dict[str, Any]) -> dict[str, Any]:
        profile_id, selected, profiles = self._select_service_entry_profile(params)
        first_reads = selected.get("first_reads", [])
        return {
            "ok": True,
            "read_only": True,
            "side_effects": False,
            "profile_id": profile_id,
            "default_profile_id": "web_gpt_commander",
            "available_profile_ids": [item["profile_id"] for item in profiles],
            "selected_profile": selected,
            "recommended_next_reads": first_reads,
            "authority": selected.get("default_authority"),
            "write_boundary": selected.get("write_boundary"),
            "tool_surface_guidance": self._tool_surface_guidance_for_actions(first_reads),
        }

    def _tool_get_agent_operator_flow_packet(self, params: dict[str, Any]) -> dict[str, Any]:
        profile_id, selected_profile, profiles = self._select_service_entry_profile(params)
        project_root, project_record = self._resolve_read_only_project_context(params)
        project_name = self._project_name_for_context(project_root, project_record, params)
        project_args = {"project_name": project_name}
        tunnel_client = self._connector_external_evidence_param(params, "tunnel_client")
        control_plane = self._connector_external_evidence_param(params, "control_plane")
        local_service = self._connector_runtime_local_service_evidence(project_root)
        runtime_status = get_runtime_version_status(project_root, local_service=local_service)
        connector_health = get_connector_runtime_health_status(
            runtime_status=runtime_status,
            local_service=local_service,
            tunnel_client=tunnel_client,
            control_plane=control_plane,
        )
        readiness = build_service_readiness_summary(
            runtime_status=runtime_status,
            connector_health=connector_health,
            project_name=project_name,
        )
        apps_connector_closeout = build_apps_connector_closeout_packet(
            project_name=project_name,
            connector_health=connector_health,
        )
        product_console_map = build_product_console_map(
            project_root,
            project_name=project_name,
            readiness_packet=self._agent_flow_projected_product_readiness(readiness),
        )
        product_console_completion = (
            product_console_map.get("completion_surface")
            if isinstance(product_console_map.get("completion_surface"), dict)
            else {}
        )
        stable_cadence = self._stable_replacement_hint(project_root, runtime_status)
        requested_mode = self._normalize_agent_task_mode(params.get("task_mode"))
        task_brief = params.get("task_brief") if isinstance(params.get("task_brief"), str) else ""
        flow_mode = self._resolve_agent_flow_mode(
            requested_mode=requested_mode,
            consumer_kind=str(selected_profile.get("consumer_kind") or ""),
            task_brief=task_brief,
        )
        primary_next_action, embedded_packets = self._agent_flow_primary_next_action(
            params=params,
            project_args=project_args,
            project_root=project_root,
            project_name=project_name,
            profile_id=profile_id,
            consumer_kind=str(selected_profile.get("consumer_kind") or ""),
            flow_mode=flow_mode,
            task_brief=task_brief,
            readiness=readiness,
            apps_connector_closeout=apps_connector_closeout,
            product_console_completion=product_console_completion,
        )
        token_recovery = apps_connector_closeout.get("token_expired_recovery")
        if not isinstance(token_recovery, dict):
            token_recovery = {}
        include_advanced_context = params.get("include_advanced_context") is not False
        advanced_actions = self._agent_flow_advanced_actions(
            project_args=project_args,
            profile_id=profile_id,
            consumer_kind=str(selected_profile.get("consumer_kind") or ""),
            flow_mode=flow_mode,
            task_brief=task_brief,
        )
        forbidden_workflows = self._agent_flow_forbidden_workflows(
            profile_id=profile_id,
            consumer_kind=str(selected_profile.get("consumer_kind") or ""),
        )
        tool_surface_guidance = self._tool_surface_guidance_for_actions(
            [primary_next_action, *advanced_actions]
        )
        current_state = {
            "project_name": project_name,
            "profile_id": profile_id,
            "consumer_kind": selected_profile.get("consumer_kind"),
            "requested_task_mode": requested_mode,
            "resolved_flow_mode": flow_mode,
            "readiness": {
                "status": readiness.get("status"),
                "primary_blocker": readiness.get("primary_blocker"),
                "safe_next_actions": readiness.get("safe_next_actions"),
            },
            "runtime": {
                "project_checkout_head": runtime_status.get("project_checkout_head"),
                "loaded_runtime_head": runtime_status.get("loaded_runtime_head"),
                "runtime_loaded_code_stale": runtime_status.get("runtime_loaded_code_stale"),
                "reload_needed_for_verification": runtime_status.get("reload_needed_for_verification"),
                "reload_awareness_reason": runtime_status.get("reload_awareness_reason"),
            },
            "connector": {
                "overall_status": connector_health.get("overall_status"),
                "local_service_status": (
                    connector_health.get("local_service", {}).get("status")
                    if isinstance(connector_health.get("local_service"), dict)
                    else None
                ),
                "external_connector_status": (
                    connector_health.get("external_connector", {}).get("status")
                    if isinstance(connector_health.get("external_connector"), dict)
                    else None
                ),
                "operator_closeout": (
                    connector_health.get("operator_closeout", {}).get("status")
                    if isinstance(connector_health.get("operator_closeout"), dict)
                    else None
                ),
                "evidence_gap_count": (
                    connector_health.get("operator_closeout", {}).get("evidence_gap_count")
                    if isinstance(connector_health.get("operator_closeout"), dict)
                    else None
                ),
            },
            "apps_connector": {
                "status": apps_connector_closeout.get("status"),
                "next_action": apps_connector_closeout.get("next_action"),
                "token_expired_code": token_recovery.get("token_expired_code") or "token_expired",
            },
            "product_console": self._agent_flow_product_console_state(product_console_completion),
            "stable_cadence": {
                "relationship": stable_cadence.get("relationship"),
                "stable_replacement_not_required": stable_cadence.get("stable_replacement_not_required"),
                "recommended_cadence": stable_cadence.get("recommended_cadence"),
                "exact_authorization_required": stable_cadence.get("exact_authorization_required"),
                "dev_batch_summary": stable_cadence.get("dev_batch_summary"),
                "batch_review_summary": stable_cadence.get("batch_review_summary"),
            },
        }
        result: dict[str, Any] = {
            "ok": True,
            "source": "agent_operator_flow_packet",
            "scope": "mcp:read",
            "read_only": True,
            "side_effects": False,
            "flow_packet_version": "agent_operator_flow.v1",
            "project_name": project_name,
            "profile_id": profile_id,
            "selected_profile": selected_profile,
            "current_state": current_state,
            "primary_next_action": primary_next_action,
            "persona_safe_next_tool": primary_next_action.get("tool"),
            "requires_confirmation_before_preview": bool(
                primary_next_action.get("requires_confirmation_before_preview")
            ),
            "requires_confirmation_before_write_or_run": True,
            "forbidden_workflows": forbidden_workflows,
            "copyable_tool_call": primary_next_action.get("copyable_tool_call"),
            "advanced_actions": advanced_actions,
            "tool_surface_guidance": tool_surface_guidance,
            "flow_usage_rule": {
                "start_here": True,
                "execute_only_one_primary_action_then_reassess": True,
                "smart_agents_should_use_advanced_context_before_escalating": True,
                "do_not_infer_missing_authority_from_this_packet": True,
                "if_tool_not_visible_use_tool_search_or_http_mcp_fallback": True,
            },
            "authority_boundary": {
                "flow_packet_is_read_only": True,
                "does_not_create_preview_artifact": True,
                "does_not_start_executor": True,
                "does_not_merge": True,
                "does_not_commit": True,
                "does_not_push": True,
                "does_not_replace_stable": True,
                "does_not_write_delivery_accepted": True,
                "does_not_create_review_decision": True,
                "does_not_create_gate_event": True,
                "does_not_read_tokens_or_cookies": True,
                "does_not_read_tunnel_client_config": True,
                "does_not_read_raw_logs": True,
            },
        }
        if include_advanced_context:
            result["advanced_context"] = {
                "available_profile_ids": [item["profile_id"] for item in profiles],
                "profile_first_reads": selected_profile.get("first_reads", []),
                "embedded_read_only_packets": embedded_packets,
                "product_console_completion_surface": product_console_completion,
                "service_entry_profiles_version": "service_entry_profiles.v1",
                "project_identity": self._project_identity_for_root(project_root),
            }
            if isinstance(project_record, dict):
                result["advanced_context"]["project_record"] = project_record
        return result

    @staticmethod
    def _normalize_agent_task_mode(value: Any) -> str:
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {
                "auto",
                "ordinary_task",
                "parallel_stage",
                "planning",
                "review",
                "source_observation",
                "connector_smoke",
                "readiness",
            }:
                return normalized
        return "auto"

    @staticmethod
    def _resolve_agent_flow_mode(*, requested_mode: str, consumer_kind: str, task_brief: str) -> str:
        if requested_mode != "auto":
            return requested_mode
        if consumer_kind == "planner":
            return "planning"
        if consumer_kind == "reviewer":
            return "review"
        if consumer_kind == "source_observer":
            return "source_observation"
        if task_brief.strip():
            return "ordinary_task"
        return "readiness"

    def _agent_flow_primary_next_action(
        self,
        *,
        params: dict[str, Any],
        project_args: dict[str, Any],
        project_root: str,
        project_name: str,
        profile_id: str,
        consumer_kind: str,
        flow_mode: str,
        task_brief: str,
        readiness: dict[str, Any],
        apps_connector_closeout: dict[str, Any],
        product_console_completion: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        embedded_packets: dict[str, Any] = {}
        if flow_mode == "parallel_stage":
            stage_packet = build_stage_parallel_next_action_packet(**self._stage_parallel_builder_args(params))
            embedded_packets["stage_parallel_next_action_packet"] = stage_packet
            nested_call = stage_packet.get("copyable_tool_call") if isinstance(stage_packet.get("copyable_tool_call"), dict) else {}
            tool = str(nested_call.get("tool") or "get_stage_parallel_next_action_packet")
            arguments = nested_call.get("arguments") if isinstance(nested_call.get("arguments"), dict) else dict(project_args)
            next_action = stage_packet.get("next_action") if isinstance(stage_packet.get("next_action"), dict) else {}
            return self._agent_flow_action(
                action_id=f"parallel_stage_{stage_packet.get('phase') or 'next_action'}",
                label="Follow stage parallel next action",
                tool=tool,
                arguments=arguments,
                reason=str(next_action.get("reason") or "Use stage parallel state to choose the next safe gate."),
                expected_output="Next stage-parallel packet, preview artifact, executor result packet, or blocker evidence.",
                derived_from="get_stage_parallel_next_action_packet",
                requires_confirmation=bool(next_action.get("requires_confirmation")),
            ), embedded_packets

        if flow_mode == "connector_smoke":
            return self._agent_flow_action(
                action_id="apps_connector_smoke",
                label="Read Apps connector smoke packet",
                tool="get_apps_connector_smoke_packet",
                arguments=dict(project_args),
                reason="Connector closeout needs the Apps project-list and sanitized connector health handoff in one read-only packet.",
                expected_output="Apps connector reachability, project list check, connector closeout call, and token_expired recovery guidance.",
            ), embedded_packets

        if flow_mode == "review":
            return self._agent_flow_action(
                action_id="review_recent_evidence",
                label="Read recent workflow and executor evidence",
                tool="manage_workflow_run",
                arguments={**project_args, "action": "list", "limit": 20},
                reason="Reviewer agents should gather workflow evidence first and report findings without creating ReviewDecision or GateEvent.",
                expected_output="Recent controlled workflow records for review orientation.",
            ), embedded_packets

        if flow_mode == "source_observation":
            return self._agent_flow_action(
                action_id="inspect_project_state",
                label="Inspect project state",
                tool="analyze_project_state",
                arguments=dict(project_args),
                reason="Source observers need project facts and recommended reads before suggesting or changing anything.",
                expected_output="Project mode, Git state, Runner status, executor/report summary, and safe recommended reads.",
            ), embedded_packets

        if flow_mode in {"ordinary_task", "planning"}:
            draft_seed: dict[str, Any] = {
                "task_tier": "M0-M2",
            }
            if task_brief.strip():
                draft_seed["goal"] = task_brief.strip()
                draft_seed["objective"] = task_brief.strip()
            return self._agent_flow_action(
                action_id="thin_governed_loop_draft",
                label="Create thin governed loop draft packet",
                tool="run_mcp_workflow",
                arguments={
                    **project_args,
                    "workflow": "thin_governed_loop_preview",
                    "phase": "preview",
                    "input_mode": "draft",
                    "draft_seed": draft_seed,
                },
                reason=(
                    "Planner/Web GPT/Local Codex can use the returned codex_execution_packet for bounded local work; "
                    "this call itself is read-only evidence and does not dispatch execution."
                ),
                expected_output="codex_execution_packet plus allowed files, validation commands, and authority boundary.",
            ), embedded_packets

        readiness_status = str(readiness.get("status") or "")
        if readiness_status and readiness_status != "ready":
            safe_actions = readiness.get("safe_next_actions") if isinstance(readiness.get("safe_next_actions"), list) else []
            if safe_actions:
                first = safe_actions[0] if isinstance(safe_actions[0], dict) else {}
                tool = str(first.get("tool") or "get_commander_app_manifest")
                arguments = first.get("arguments") if isinstance(first.get("arguments"), dict) else dict(project_args)
                if tool in {"get_commander_app_manifest", "get_agent_operator_flow_packet", "render_commander_app"}:
                    arguments = {**arguments, "profile_id": profile_id}
                return self._agent_flow_action(
                    action_id="readiness_safe_next_action",
                    label=str(first.get("label") or "Follow readiness safe next action"),
                    tool=tool,
                    arguments=arguments,
                    reason=str(first.get("why") or first.get("reason") or "Readiness is not ready; follow the first safe read-only action."),
                    expected_output="Updated service readiness evidence or a clear blocker.",
                    derived_from="service_readiness_summary",
                ), embedded_packets
        if apps_connector_closeout.get("status") != "ready" and consumer_kind == "web_gpt":
            return self._agent_flow_action(
                action_id="apps_connector_smoke",
                label="Read Apps connector smoke packet",
                tool="get_apps_connector_smoke_packet",
                arguments=dict(project_args),
                reason="Web GPT should verify Apps connector reachability and connector closeout before coordinating external handoff.",
                expected_output="Apps connector project-list check and connector closeout packet.",
            ), embedded_packets
        product_console_next = self._agent_flow_product_console_next_action(
            project_args=project_args,
            profile_id=profile_id,
            product_console_completion=product_console_completion,
        )
        if product_console_next is not None:
            return product_console_next, embedded_packets
        return self._agent_flow_action(
            action_id="read_commander_manifest",
            label="Read Commander manifest",
            tool="get_commander_app_manifest",
            arguments={**project_args, "profile_id": profile_id},
            reason="No task-specific mode was selected; read the commander manifest for the current dashboard and safe next actions.",
            expected_output="Readiness, connector, runtime, profile entries, and preview-first workflow actions.",
        ), embedded_packets

    def _agent_flow_product_console_next_action(
        self,
        *,
        project_args: dict[str, Any],
        profile_id: str,
        product_console_completion: dict[str, Any],
    ) -> dict[str, Any] | None:
        if product_console_completion.get("ready") is True:
            return None
        queue = product_console_completion.get("followup_queue")
        if not isinstance(queue, dict):
            return None
        next_item = queue.get("next_item")
        if not isinstance(next_item, dict):
            return None
        primary = next_item.get("primary_action") if isinstance(next_item.get("primary_action"), dict) else {}
        tool = str(primary.get("tool") or next_item.get("primary_tool") or "get_product_console_map")
        arguments = primary.get("arguments") if isinstance(primary.get("arguments"), dict) else dict(project_args)
        if tool in {"get_commander_app_manifest", "get_agent_operator_flow_packet", "render_commander_app"}:
            arguments = {**arguments, "profile_id": profile_id}
        if tool == "get_product_console_map":
            arguments = {**project_args, **arguments}
        return self._agent_flow_action(
            action_id=f"product_console_closeout_{next_item.get('item_id') or 'followup'}",
            label=str(next_item.get("label") or "Follow Product Console closeout"),
            tool=tool,
            arguments=arguments,
            reason=str(primary.get("why") or next_item.get("empty_state") or "Product Console closeout still has follow-up items."),
            expected_output="Updated Product Console completion surface, recorded action result, or explicit closeout blocker.",
            derived_from="product_console_closeout_followup_queue",
        )

    @staticmethod
    def _agent_flow_projected_product_readiness(readiness: dict[str, Any]) -> dict[str, Any]:
        safe_actions = readiness.get("safe_next_actions") if isinstance(readiness.get("safe_next_actions"), list) else []
        safe_next_action = safe_actions[0] if safe_actions and isinstance(safe_actions[0], dict) else {}
        status = str(readiness.get("status") or "unknown")
        return {
            "ok": True,
            "source": "service_readiness_summary_projection",
            "read_only": True,
            "side_effects": False,
            "status": status,
            "ready": status == "ready",
            "primary_blocker": readiness.get("primary_blocker"),
            "safe_next_action": safe_next_action,
            "authority_boundary": {
                "projection_is_read_only": True,
                "does_not_run_ops_check": True,
                "does_not_run_remote_preflight": True,
            },
        }

    @staticmethod
    def _agent_flow_product_console_state(product_console_completion: dict[str, Any]) -> dict[str, Any]:
        queue = product_console_completion.get("followup_queue")
        if not isinstance(queue, dict):
            queue = {}
        next_item = queue.get("next_item")
        if not isinstance(next_item, dict):
            next_item = {}
        return {
            "completion_status": product_console_completion.get("status"),
            "ready": product_console_completion.get("ready"),
            "gap_count": product_console_completion.get("gap_count"),
            "blocker_codes": product_console_completion.get("blocker_codes"),
            "needs_attention_codes": product_console_completion.get("needs_attention_codes"),
            "followup_queue": {
                "source": queue.get("source"),
                "status": queue.get("status"),
                "total_count": queue.get("total_count"),
                "next_item_id": next_item.get("item_id"),
                "next_primary_tool": next_item.get("primary_tool"),
                "next_required_scope": next_item.get("required_scope"),
                "next_gate_level": next_item.get("gate_level"),
            },
        }

    def _agent_flow_action(
        self,
        *,
        action_id: str,
        label: str,
        tool: str,
        arguments: dict[str, Any],
        reason: str,
        expected_output: str,
        derived_from: str | None = None,
        requires_confirmation: bool = False,
    ) -> dict[str, Any]:
        scope = self._required_scope_for_tool(tool, arguments)
        gate_level = self._agent_flow_gate_level(tool=tool, arguments=arguments, scope=scope)
        requires_preview_confirmation = bool(requires_confirmation or scope == "mcp:preview")
        requires_write_or_run_confirmation = bool(scope != "mcp:read")
        return {
            "action_id": action_id,
            "label": label,
            "tool": tool,
            "arguments": arguments,
            "required_scope": scope,
            "gate_level": gate_level,
            "reason": reason,
            "expected_output": expected_output,
            "derived_from": derived_from,
            "requires_confirmation_before_preview": requires_preview_confirmation,
            "requires_confirmation_before_write_or_run": requires_write_or_run_confirmation,
            "requires_confirmation_before_execution": bool(
                requires_preview_confirmation or requires_write_or_run_confirmation
            ),
            "copyable_tool_call": {
                "tool": tool,
                "arguments": arguments,
            },
        }

    @staticmethod
    def _agent_flow_gate_level(*, tool: str, arguments: dict[str, Any], scope: str) -> str:
        if scope == "mcp:read":
            if tool == "run_mcp_workflow":
                return "read_only_workflow_packet"
            return "read_only"
        if scope == "mcp:preview":
            action = arguments.get("action") if isinstance(arguments, dict) else None
            if action == "preview":
                return "preview_artifact"
            return "preview_gate"
        if scope == "mcp:commit":
            return "explicit_apply_or_run_required"
        return scope

    def _agent_flow_advanced_actions(
        self,
        *,
        project_args: dict[str, Any],
        profile_id: str,
        consumer_kind: str,
        flow_mode: str,
        task_brief: str,
    ) -> list[dict[str, Any]]:
        draft_seed: dict[str, Any] = {"task_tier": "M0-M2"}
        if task_brief.strip():
            draft_seed["goal"] = task_brief.strip()
            draft_seed["objective"] = task_brief.strip()
        profile_contract = {
            "label": "Profile contract",
            "tool": "get_service_entry_profile",
            "arguments": {"profile_id": profile_id},
            "gate_level": "read_only",
        }
        project_state = {
            "label": "Project state",
            "tool": "analyze_project_state",
            "arguments": dict(project_args),
            "gate_level": "read_only",
        }
        runtime_status = {
            "label": "Runtime status",
            "tool": "get_runtime_version_status",
            "arguments": dict(project_args),
            "gate_level": "read_only",
        }
        thin_loop_draft = {
            "label": "Thin loop draft",
            "tool": "run_mcp_workflow",
            "arguments": {
                **project_args,
                "workflow": "thin_governed_loop_preview",
                "phase": "preview",
                "input_mode": "draft",
                "draft_seed": draft_seed,
            },
            "gate_level": "read_only_workflow_packet",
        }
        stage_parallel_next_action = {
            "label": "Stage parallel next action",
            "tool": "get_stage_parallel_next_action_packet",
            "arguments": dict(project_args),
            "gate_level": "read_only",
        }
        recent_workflow_records = {
            "label": "Recent workflow records",
            "tool": "manage_workflow_run",
            "arguments": {**project_args, "action": "list", "limit": 10},
            "gate_level": "read_only",
        }
        executor_reports = {
            "label": "Executor reports",
            "tool": "list_executor_run_reports",
            "arguments": {**project_args, "limit": 10},
            "gate_level": "read_only",
        }
        apps_connector_smoke = {
            "label": "Apps connector smoke",
            "tool": "get_apps_connector_smoke_packet",
            "arguments": dict(project_args),
            "gate_level": "read_only",
        }
        stable_cadence = {
            "label": "Stable cadence",
            "tool": "get_stable_replacement_cadence",
            "arguments": dict(project_args),
            "gate_level": "read_only",
        }

        if consumer_kind == "source_observer":
            return [profile_contract, project_state, runtime_status, apps_connector_smoke]
        if consumer_kind == "reviewer":
            return [profile_contract, project_state, recent_workflow_records, apps_connector_smoke]
        if consumer_kind == "planner":
            return [
                profile_contract,
                project_state,
                thin_loop_draft,
                stage_parallel_next_action,
                recent_workflow_records,
                apps_connector_smoke,
            ]
        if consumer_kind == "local_codex":
            return [
                profile_contract,
                project_state,
                thin_loop_draft,
                stage_parallel_next_action,
                recent_workflow_records,
                executor_reports,
                apps_connector_smoke,
            ]
        return [
            profile_contract,
            project_state,
            runtime_status,
            thin_loop_draft,
            stage_parallel_next_action,
            recent_workflow_records,
            executor_reports,
            apps_connector_smoke,
            stable_cadence,
        ]

    @staticmethod
    def _agent_flow_forbidden_workflows(*, profile_id: str, consumer_kind: str) -> list[str]:
        common = [
            "stable_replacement_without_exact_authorization",
            "delivery_accepted_write",
            "review_decision_write",
            "gate_event_write",
            "token_cookie_credential_access",
            "raw_tunnel_log_or_config_read",
        ]
        by_consumer = {
            "web_gpt": [
                "executor_run_without_current_authorization",
                "commit_or_push_without_current_authorization",
            ],
            "local_codex": [
                "executor_run_without_preview_or_current_authorization",
            ],
            "planner": [
                "executor_run",
                "commit_or_push",
            ],
            "reviewer": [
                "source_write",
                "executor_run",
                "commit_or_push",
                "stable_replacement",
            ],
            "source_observer": [
                "source_write",
                "managed_workflow_apply",
                "executor_run",
                "commit_or_push",
                "stable_replacement",
            ],
        }
        selected = by_consumer.get(consumer_kind, [])
        return [*selected, *common]

    def _tool_surface_guidance_for_actions(self, actions: list[dict[str, Any]]) -> dict[str, Any]:
        referenced_tools: list[str] = []
        for action in actions:
            if not isinstance(action, dict):
                continue
            tool_name = action.get("tool")
            if isinstance(tool_name, str) and tool_name:
                referenced_tools.append(tool_name)
            copyable_tool_call = action.get("copyable_tool_call")
            if isinstance(copyable_tool_call, dict):
                copyable_tool_name = copyable_tool_call.get("tool")
                if isinstance(copyable_tool_name, str) and copyable_tool_name:
                    referenced_tools.append(copyable_tool_name)
        referenced_tools = list(dict.fromkeys(referenced_tools))
        visible_tools = set(self._visible_tool_names())
        missing_from_current_mcp_exposure = [
            tool_name for tool_name in referenced_tools if tool_name not in visible_tools
        ]
        return {
            "referenced_tools": referenced_tools,
            "current_mcp_visible_tool_count": len(visible_tools),
            "missing_from_current_mcp_exposure": missing_from_current_mcp_exposure,
            "apps_tool_surface_may_lazy_load_tools": True,
            "if_tool_not_visible_in_current_apps_surface": (
                "Use tool_search with the exact ColaMeta tool name, or call the stable HTTP MCP endpoint "
                "with tools/call and the copyable_tool_call arguments."
            ),
            "tool_search_query_hint": " ".join(referenced_tools[:8]),
            "http_mcp_fallback": {
                "endpoint": "http://127.0.0.1:8766/mcp",
                "method": "tools/call",
                "arguments_source": "copyable_tool_call.arguments",
            },
        }

    def _tool_get_agent_consumer_contract(self, _: dict[str, Any]) -> dict[str, Any]:
        visible_tools = self._visible_tool_names()
        return {
            "ok": True,
            "read_only": True,
            "side_effects": False,
            "contract_version": "agent_consumer_contract.v1",
            "scope": "mcp:read",
            "service_mode": bool(self.service_mode),
            "mcp_exposure_profile": self.mcp_exposure_profile,
            "visible_tool_count": len(visible_tools),
            "outer_tool_result_envelope": {
                "success_required_fields": ["ok", "tool", "data"],
                "success_shape": {
                    "ok": True,
                    "tool": "<tool_name>",
                    "data": "<tool-specific payload>",
                },
                "error_required_fields": ["ok", "tool", "error_code", "message", "details"],
                "error_shape": {
                    "ok": False,
                    "tool": "<tool_name>",
                    "error_code": "<machine_readable_code>",
                    "message": "<human_readable_message>",
                    "details": "<structured object>",
                },
                "large_result_shape": {
                    "ok": "<original ok>",
                    "tool": "<tool_name>",
                    "packaged": True,
                    "package_mode": "manifest",
                    "summary": "<compact summary>",
                    "omitted_fields": ["data"],
                    "recommended_next_reads": "<follow-up reads>",
                },
            },
            "data_payload_recommendation": {
                "standard_success_fields": ["ok", "read_only", "side_effects"],
                "meaning": {
                    "ok": "Payload-level success flag when the payload can independently report success.",
                    "read_only": "True means the tool only read evidence or produced a preview.",
                    "side_effects": "False means the payload declares no state mutation.",
                },
                "compatibility_note": (
                    "Older payloads may omit payload-level ok/read_only/side_effects; "
                    "agents must first trust the outer envelope and then use payload fields when present."
                ),
            },
            "project_routing_contract": {
                "service_mode_project_tools_require_project_name": bool(self.service_mode),
                "do_not_send_project_root_when_project_name_is_used": True,
                "discover_projects_first": "list_registered_projects",
                "missing_project_name_error_code": "PROJECT_NAME_REQUIRED",
                "invalid_project_name_error_code": "INVALID_PROJECT_NAME",
                "project_root_override_error_code": "PROJECT_ROOT_OVERRIDE_NOT_ALLOWED",
                "source_only_managed_workflow_error_code": "PROJECT_MODE_UNSUPPORTED",
            },
            "chatgpt_apps_contract": {
                "app_name": COMMANDER_APP_TITLE,
                "archetype": "interactive-decoupled",
                "data_tool": "get_commander_app_manifest",
                "render_tool": "render_commander_app",
                "widget_resource_uri": COMMANDER_APP_WIDGET_URI,
                "resource_methods": ["resources/list", "resources/read"],
                "render_tool_meta": ["ui.resourceUri", "openai/outputTemplate"],
                "widget_only_meta_is_not_part_of_structured_content": True,
            },
            "authority_boundary": {
                "read_only_tools_do_not_authorize_executor_dispatch": True,
                "read_only_tools_do_not_create_review_decision": True,
                "read_only_tools_do_not_emit_gate_event": True,
                "read_only_tools_do_not_write_delivery_state": True,
                "stable_promotion_requires_external_commander_authorization": True,
            },
            "recommended_first_reads": [
                {"tool": "list_registered_projects", "why": "Discover allowed project_name values."},
                {"tool": "get_agent_consumer_contract", "why": "Load this consumer contract."},
                {"tool": "get_service_entry_profile", "why": "Select a consumer-specific entry profile."},
                {"tool": "get_agent_operator_flow_packet", "why": "Get one role-aware primary next action before choosing lower-level tools."},
                {"tool": "get_web_gpt_service_entrypoint", "why": "Read guided service entry flow."},
                {"tool": "render_commander_app", "why": "Open the ChatGPT Apps Commander panel with project_name."},
                {"tool": "get_commander_app_manifest", "why": "Read the same Commander App contract without rendering UI."},
                {"tool": "get_apps_connector_smoke_packet", "why": "Run the Apps connector project-list and connector-closeout smoke checklist."},
                {"tool": "get_stable_replacement_cadence", "why": "Read whether dev/stable drift should be batched instead of promoted immediately."},
                {"tool": "get_stable_promotion_readiness", "why": "Check runtime/project readiness with project_name."},
                {"tool": "get_stage_parallel_plan_preview", "why": "Preview stage-level parallel task sharding without starting executors."},
                {"tool": "get_stage_parallel_run_preview", "why": "Preview isolated parallel run orchestration without creating worktrees or executor previews."},
                {"tool": "get_stage_parallel_worktree_assignment_preview", "why": "Check deterministic worktree and branch assignments without creating them."},
                {"tool": "get_stage_parallel_next_action_packet", "why": "Read the current stage parallel state and get the single recommended next tool call."},
                {"tool": "manage_stage_parallel_shard_inputs", "why": "Preview shard-specific runner input materialization after isolated worktrees exist."},
                {"tool": "get_stage_parallel_executor_group_preview", "why": "Preview executor group requests without creating previews or starting runs."},
                {"tool": "manage_stage_parallel_executor_runs", "why": "Preview the executor run group after run_once_preview artifacts exist; apply starts isolated executor runs only."},
                {"tool": "get_stage_parallel_executor_results_packet", "why": "Read structured parallel executor claim/report summaries without raw logs."},
                {"tool": "get_stage_parallel_group_status", "why": "Read planned or provided shard result status before merge preview."},
                {"tool": "get_stage_parallel_merge_preview", "why": "Preview merge order and validation gates after shard results pass."},
                {"tool": "manage_stage_parallel_merges", "why": "Preview the controlled local merge gate; apply performs local git merge only."},
                {"tool": "get_stage_parallel_closeout_packet", "why": "Prepare the stage parallel closeout packet for human review."},
                {"tool": "get_connector_runtime_health_status", "why": "Check local/runtime/external connector closeout with project_name."},
                {"tool": "analyze_project_state", "why": "Inspect project facts with project_name."},
            ],
            "service_entry_profiles_version": "service_entry_profiles.v1",
            "service_entry_profiles": self._service_entry_profiles(),
            "thin_loop_consumer_rule": {
                "draft_mode": "Call run_mcp_workflow with input_mode=draft and draft_seed.",
                "m0_m2_direct_mode": "When result.codex_execution_packet.packet_status is ready, use result.codex_execution_packet.copy_paste_codex_prompt as the local Codex task packet; provided preview is optional.",
                "provided_mode": "Use result.next_request_payload only when formal thin-loop evidence preview is needed.",
                "authority": "thin_governed_loop_preview remains read-only preparation/evidence and does not authorize acceptance, executor dispatch, commit, or push.",
            },
        }

    def _tool_get_web_gpt_service_entrypoint(self, params: dict[str, Any]) -> dict[str, Any]:
        visible_names = self._visible_tool_names()
        project_identity: dict[str, Any] | None = None
        project_name = params.get("project_name")
        if project_name is not None:
            project_root, project_record = self._resolve_read_only_project_context(params)
            project_identity = self._project_identity_for_root(project_root)
            project_identity["project"] = project_record

        registered_projects = self._web_gpt_registered_project_summary()
        return {
            "ok": True,
            "read_only": True,
            "side_effects": False,
            "service_profile": {
                "service_name": "ColaMeta MCP",
                "mode": "service" if self.service_mode else "project",
                "mcp_exposure_profile": self.mcp_exposure_profile,
                "project_name_required_for_project_tools": bool(self.service_mode),
                "project_hint": self.project_hint,
                "visible_tool_count": len(visible_names),
            },
            "project_identity": project_identity,
            "registered_projects": registered_projects,
            "service_entry_profiles_version": "service_entry_profiles.v1",
            "service_entry_profiles": self._service_entry_profiles(),
            "entry_sequence": [
                {
                    "step": "discover_projects",
                    "tool": "list_registered_projects",
                    "arguments": {},
                    "why": "服务模式下先确认可用 project_name；不要猜项目目录。",
                },
                {
                    "step": "read_agent_consumer_contract",
                    "tool": "get_agent_consumer_contract",
                    "arguments": {},
                    "why": "确认统一 envelope、project_name 路由、只读边界和错误处理规则。",
                },
                {
                    "step": "select_service_entry_profile",
                    "tool": "get_service_entry_profile",
                    "arguments": {"profile_id": "web_gpt_commander"},
                    "why": "按当前消费者角色读取最小进入路径，不把其他 agent 的路径混进来。",
                },
                {
                    "step": "read_agent_operator_flow_packet",
                    "tool": "get_agent_operator_flow_packet",
                    "arguments": {"project_name": "<registered project_name>", "profile_id": "web_gpt_commander"},
                    "why": "先读取一个 role-aware primary_next_action，再决定是否进入底层高级工具链。",
                },
                {
                    "step": "render_commander_app",
                    "tool": "render_commander_app",
                    "arguments": {"project_name": "<registered project_name>", "profile_id": "web_gpt_commander"},
                    "why": "打开 ChatGPT Apps Commander 面板，统一展示服务事实、connector health、profiles 和授权闸门。",
                },
                {
                    "step": "inspect_stable_replacement_cadence",
                    "tool": "get_stable_replacement_cadence",
                    "arguments": {"project_name": "<registered project_name>"},
                    "why": "确认 dev ahead stable 是正常批次状态，不把普通 drift 当成稳定替换请求。",
                },
                {
                    "step": "inspect_stage_parallel_plan_preview",
                    "tool": "get_stage_parallel_plan_preview",
                    "arguments": {"project_name": "<registered project_name>"},
                    "why": "预览阶段级并行任务拆分和文件边界，不启动 executor。",
                },
                {
                    "step": "inspect_stage_parallel_run_preview",
                    "tool": "get_stage_parallel_run_preview",
                    "arguments": {"project_name": "<registered project_name>"},
                    "why": "预览隔离 worktree/branch 和未来 executor preview request，不创建执行器 preview。",
                },
                {
                    "step": "inspect_stage_parallel_worktree_assignment_preview",
                    "tool": "get_stage_parallel_worktree_assignment_preview",
                    "arguments": {"project_name": "<registered project_name>"},
                    "why": "检查每个 shard 的 worktree path 和 branch 是否可分配，但不创建。",
                },
                {
                    "step": "inspect_stage_parallel_next_action_packet",
                    "tool": "get_stage_parallel_next_action_packet",
                    "arguments": {"project_name": "<registered project_name>"},
                    "why": "读取当前并行阶段状态，获得唯一 recommended next tool call；这个 packet 不创建 preview artifact。",
                },
                {
                    "step": "preview_stage_parallel_shard_inputs",
                    "tool": "manage_stage_parallel_shard_inputs",
                    "arguments": {"project_name": "<registered project_name>", "action": "preview"},
                    "why": "隔离 worktree 已存在后，预览每个 shard 的 runner input materialization；apply 只写 runtime plan/state/prompt overlay。",
                },
                {
                    "step": "inspect_stage_parallel_executor_group_preview",
                    "tool": "get_stage_parallel_executor_group_preview",
                    "arguments": {"project_name": "<registered project_name>"},
                    "why": "预览 future executor preview group，不创建 preview，也不启动 executor。",
                },
                {
                    "step": "preview_stage_parallel_executor_runs",
                    "tool": "manage_stage_parallel_executor_runs",
                    "arguments": {"project_name": "<registered project_name>", "action": "preview"},
                    "why": "executor preview artifacts 已存在后，预览并行 executor run group；apply 才会启动隔离 worktree executor。",
                },
                {
                    "step": "inspect_stage_parallel_executor_results_packet",
                    "tool": "get_stage_parallel_executor_results_packet",
                    "arguments": {"project_name": "<registered project_name>"},
                    "why": "读取 structured executor claim/report 摘要，生成 sanitized executor_results；不读 raw logs。",
                },
                {
                    "step": "inspect_stage_parallel_group_status",
                    "tool": "get_stage_parallel_group_status",
                    "arguments": {"project_name": "<registered project_name>"},
                    "why": "读取 planned 或 sanitized executor result 状态，判断是否可进入 merge preview。",
                },
                {
                    "step": "inspect_stage_parallel_merge_preview",
                    "tool": "get_stage_parallel_merge_preview",
                    "arguments": {"project_name": "<registered project_name>"},
                    "why": "结果齐备后预览 merge order 和 validation gates，不执行 merge。",
                },
                {
                    "step": "preview_stage_parallel_merge_apply",
                    "tool": "manage_stage_parallel_merges",
                    "arguments": {"project_name": "<registered project_name>", "action": "preview"},
                    "why": "merge preview ready 后生成受控 merge apply preview；apply 才会执行本地 git merge。",
                },
                {
                    "step": "inspect_stage_parallel_closeout_packet",
                    "tool": "get_stage_parallel_closeout_packet",
                    "arguments": {"project_name": "<registered project_name>"},
                    "why": "生成人审 closeout packet；不写 Delivery accepted / ReviewDecision / GateEvent。",
                },
                {
                    "step": "inspect_stable_promotion_readiness",
                    "tool": "get_stable_promotion_readiness",
                    "arguments": {"project_name": "<registered project_name>"},
                    "why": "确认当前服务是否只是 dev 试用、可进入稳定晋升审查，还是仍有本地阻断。",
                },
                {
                    "step": "inspect_apps_connector_smoke",
                    "tool": "get_apps_connector_smoke_packet",
                    "arguments": {"project_name": "<registered project_name>"},
                    "why": "确认 Apps connector 可达、项目列表命中、connector closeout 调用形状和 token_expired 处理边界。",
                },
                {
                    "step": "inspect_connector_runtime_health",
                    "tool": "get_connector_runtime_health_status",
                    "arguments": {"project_name": "<registered project_name>"},
                    "why": "确认 local Web/MCP、runtime freshness、external connector/tunnel evidence 是否闭合。",
                },
                {
                    "step": "inspect_project_state",
                    "tool": "analyze_project_state",
                    "arguments": {"project_name": "<registered project_name>"},
                    "why": "开工前确认 Git、Runner、Executor、报告和阻断。",
                },
                {
                    "step": "inspect_recent_evidence",
                    "tool": "manage_workflow_run",
                    "arguments": {"action": "list", "project_name": "<registered project_name>", "limit": 10},
                    "why": "查看最近受控操作记录；列表按 created_at 新到旧排序。",
                },
            ],
            "recommended_flows": {
                "thin_governed_loop_input_draft": {
                    "tool": "run_mcp_workflow",
                    "draft_arguments": {
                        "workflow": "thin_governed_loop_preview",
                        "phase": "preview",
                        "project_name": "<registered project_name>",
                        "input_mode": "draft",
                        "draft_seed": {
                            "goal": "<natural-language objective>",
                            "task_tier": "M0-M2",
                            "allowed_files": ["<project-relative path>"],
                            "context_files": ["<optional context path>"],
                            "validation_commands": ["<validation command>"],
                            "review_decision_value": "NEEDS_FIX",
                            "reviewer_notes": "<optional reviewer note>",
                        },
                    },
                    "next_step": (
                        "For M0-M2 low-risk tasks, require result.codex_execution_packet.packet_status=ready, "
                        "then copy result.codex_execution_packet.copy_paste_codex_prompt to local Codex. "
                        "Use result.next_request_payload only when formal evidence preview is needed."
                    ),
                    "direct_codex_packet_field": "result.codex_execution_packet",
                    "provided_arguments": {
                        "workflow": "thin_governed_loop_preview",
                        "phase": "preview",
                        "project_name": "<same registered project_name>",
                        "input_mode": "provided",
                        "thin_loop_inputs": "<generated_input_bundle>",
                    },
                    "authority": "read_only_evidence_not_execution_or_acceptance_authority",
                },
                "validation": {
                    "tool": "manage_validation_run",
                    "preview_arguments": {
                        "action": "preview",
                        "scope": "target_files",
                        "project_name": "<registered project_name>",
                        "target_files": ["<project-relative path>"],
                    },
                    "run_arguments": {
                        "action": "run",
                        "project_name": "<same registered project_name>",
                        "preview_id": "<preview_id from preview>",
                    },
                    "status_arguments": {
                        "action": "status",
                        "project_name": "<same registered project_name>",
                        "run_id": "<run_id from run>",
                    },
                },
            },
            "safety_boundary": {
                "does_not_authorize_stable_promotion": True,
                "does_not_authorize_executor_run": True,
                "does_not_authorize_commit_or_push": True,
                "does_not_create_review_decision": True,
                "does_not_emit_gate_event": True,
                "does_not_write_delivery_state": True,
                "requires_explicit_commander_authorization_for": [
                    "stable service replacement",
                    "push",
                    "executor run",
                    "route transition",
                    "release/deploy",
                ],
            },
            "web_gpt_handoff_prompt": (
                "Start by calling list_registered_projects, get_agent_consumer_contract, "
                "get_service_entry_profile with profile_id=web_gpt_commander, get_agent_operator_flow_packet, then "
                "get_web_gpt_service_entrypoint, render_commander_app, get_stable_promotion_readiness, and "
                "analyze_project_state with the selected project_name. "
                "For thin governed loop work, "
                "use run_mcp_workflow input_mode=draft, then for M0-M2 local work require "
                "result.codex_execution_packet.packet_status=ready before copying "
                "result.codex_execution_packet.copy_paste_codex_prompt to local Codex. "
                "Use result.next_request_payload only when formal evidence preview is needed. "
                "Treat all outputs as evidence unless Commander explicitly authorizes a write, run, "
                "push, or stable promotion."
            ),
            "visible_tool_names": visible_names,
        }

    def _tool_get_commander_app_manifest(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._commander_app_manifest(params)

    def _tool_get_product_readiness_status(self, params: dict[str, Any]) -> dict[str, Any]:
        project_root, _ = self._resolve_read_only_project_context(params)
        return build_product_readiness_packet(project_root)

    def _tool_get_chatgpt_app_readiness(self, params: dict[str, Any]) -> dict[str, Any]:
        project_root, project_record = self._resolve_read_only_project_context(params)
        project_name = self._project_name_for_context(project_root, project_record, params)
        return build_chatgpt_connection_packet(project_root, project_name=project_name)

    def _tool_get_full_loop_authority_status(self, params: dict[str, Any]) -> dict[str, Any]:
        project_root, _ = self._resolve_read_only_project_context(params)
        return build_full_loop_authority_status(
            project_root,
            enable_full_loop=bool(params.get("enable_full_loop")),
            confirmation_mode=params.get("confirmation_mode") if isinstance(params.get("confirmation_mode"), str) else None,
            allow_executor_run=bool(params.get("allow_executor_run")),
            allow_validation_run=bool(params.get("allow_validation_run")),
            allow_local_commit=bool(params.get("allow_local_commit")),
            allow_remote_push=bool(params.get("allow_remote_push")),
            allow_stable_replacement=bool(params.get("allow_stable_replacement")),
            operator_confirmation_ref=(
                params.get("operator_confirmation_ref") if isinstance(params.get("operator_confirmation_ref"), str) else None
            ),
        )

    def _tool_get_product_console_map(self, params: dict[str, Any]) -> dict[str, Any]:
        project_root, project_record = self._resolve_read_only_project_context(params)
        project_name = self._project_name_for_context(project_root, project_record, params)
        return build_product_console_map(project_root, project_name=project_name)

    def _tool_record_product_console_action_result(self, params: dict[str, Any]) -> dict[str, Any]:
        if params.get("project_name") is not None:
            return self._route_project_name_tool("record_product_console_action_result", params, require_managed=True)
        status = params.get("status")
        if not isinstance(status, str) or not status.strip():
            raise MCPToolInputError("ACTION_RESULT_STATUS_REQUIRED", "status is required.")
        return record_product_console_action_result(
            self.project_root,
            action_id=params.get("action_id") if isinstance(params.get("action_id"), str) else None,
            tool=params.get("tool") if isinstance(params.get("tool"), str) else None,
            mode=params.get("mode") if isinstance(params.get("mode"), str) else None,
            status=status.strip(),
            message=params.get("message") if isinstance(params.get("message"), str) else None,
            result_ok=params.get("result_ok") if isinstance(params.get("result_ok"), bool) else None,
            action_fingerprint=params.get("action_fingerprint") if isinstance(params.get("action_fingerprint"), str) else None,
        )

    def _tool_get_submission_evidence_fill_preview(self, params: dict[str, Any]) -> dict[str, Any]:
        project_root, project_record = self._resolve_read_only_project_context(params)
        project_name = self._project_name_for_context(project_root, project_record, params)
        selected_keys = params.get("selected_keys")
        return build_submission_evidence_fill_preview(
            project_root,
            project_name=project_name,
            selected_keys=selected_keys if isinstance(selected_keys, list) else None,
        )

    def _tool_get_submission_evidence_auto_draft(self, params: dict[str, Any]) -> dict[str, Any]:
        project_root, project_record = self._resolve_read_only_project_context(params)
        project_name = self._project_name_for_context(project_root, project_record, params)
        selected_keys = self._selected_auto_submission_evidence_keys(params.get("selected_keys"))
        local_service = self._connector_runtime_local_service_evidence(project_root)
        runtime_status = get_runtime_version_status(project_root, local_service=local_service)
        connector_health = get_connector_runtime_health_status(
            runtime_status=runtime_status,
            local_service=local_service,
        )
        visible_tool_defs = self._filter_tools_by_exposure_profile(self.tool_defs)
        tool_scope_map = {
            tool.name: self._submission_evidence_scope_label(tool.name)
            for tool in visible_tool_defs
        }
        context = {
            "project_name": project_name,
            "project_root": project_root,
            "runtime_status": runtime_status,
            "connector_health": connector_health,
            "visible_tool_defs": visible_tool_defs,
            "tool_scope_map": tool_scope_map,
            "mcp_exposure_profile": self.mcp_exposure_profile,
            "service_mode": self.service_mode,
        }
        entries = [
            self._submission_evidence_auto_entry(key, context)
            for key in selected_keys
        ]
        entries = [entry for entry in entries if isinstance(entry, dict)]
        return {
            "ok": True,
            "source": "submission_evidence_auto_draft",
            "schema_version": "submission_evidence_auto_draft.v1",
            "read_only": True,
            "side_effects": False,
            "project_root": project_root,
            "project_name": project_name,
            "status": "draft_ready" if entries else "no_supported_keys",
            "selected_keys": selected_keys,
            "generated_keys": [entry["key"] for entry in entries],
            "unsupported_keys": [],
            "draft_entries": entries,
            "copyable_tool_call": {
                "tool": "fill_submission_evidence_files",
                "arguments": {
                    "project_name": project_name,
                    "entries": [entry["copyable_entry_shape"] for entry in entries],
                    "mark_ready": False,
                },
                "required_scope": "mcp:commit",
                "requires_explicit_operator_review": True,
            },
            "operator_instructions": [
                "Review and edit every generated evidence draft before writing files.",
                "Keep mark_ready=false until a human reviewer confirms the evidence is final.",
                "Run get_release_submission_readiness after filling files.",
            ],
            "authority_boundary": {
                "read_only": True,
                "side_effects": False,
                "does_not_write_files": True,
                "does_not_mark_ready_fields": True,
                "does_not_create_openai_app_draft": True,
                "does_not_submit_app_for_review": True,
                "does_not_publish_app": True,
                "does_not_read_tokens_or_cookies": True,
                "does_not_read_raw_logs": True,
            },
        }

    def _selected_auto_submission_evidence_keys(self, raw_selected: Any) -> list[str]:
        supported = ["mcp_tool_info", "security_review", "metadata_snapshot"]
        if not isinstance(raw_selected, list):
            return supported
        selected = [
            str(item).strip()
            for item in raw_selected
            if isinstance(item, str) and str(item).strip() in supported
        ]
        return selected or supported

    def _submission_evidence_auto_entry(self, key: str, context: dict[str, Any]) -> dict[str, Any] | None:
        filename_by_key = {
            "mcp_tool_info": "mcp-tool-info.md",
            "security_review": "security-review.md",
            "metadata_snapshot": "metadata-snapshot.md",
        }
        content_builders = {
            "mcp_tool_info": self._auto_mcp_tool_info_evidence,
            "security_review": self._auto_security_review_evidence,
            "metadata_snapshot": self._auto_metadata_snapshot_evidence,
        }
        builder = content_builders.get(key)
        if builder is None:
            return None
        filename = filename_by_key[key]
        content = builder(context)
        return {
            "key": key,
            "filename": filename,
            "content_length": len(content),
            "copyable_entry_shape": {
                "key": key,
                "filename": filename,
                "content": content,
            },
        }

    def _submission_evidence_scope_label(self, tool_name: str) -> str:
        scope = self._tool_policy_scope(tool_name, {})
        if isinstance(scope, str) and scope:
            return scope
        policy = MCP_TOOL_POLICIES.get(tool_name)
        if policy is None:
            return "policy-missing"
        if policy.selector in {"action", "manage_files", "run_mcp_workflow"}:
            return "action-dependent"
        return "policy-defined"

    def _auto_mcp_tool_info_evidence(self, context: dict[str, Any]) -> str:
        visible_tool_defs = context.get("visible_tool_defs") if isinstance(context.get("visible_tool_defs"), list) else []
        tool_scope_map = context.get("tool_scope_map") if isinstance(context.get("tool_scope_map"), dict) else {}
        lines = [
            "# MCP Tool Information Evidence",
            "",
            "## tool_inventory",
            f"Project name: {context.get('project_name') or '-'}",
            f"MCP exposure profile: {context.get('mcp_exposure_profile') or '-'}",
            f"Visible tool count: {len(visible_tool_defs)}",
            "",
            "| Tool | Scope | Title |",
            "|---|---|---|",
        ]
        for tool in visible_tool_defs:
            if not isinstance(tool, MCPToolDef):
                continue
            title = tool.title if isinstance(tool.title, str) and tool.title.strip() else "(untitled)"
            lines.append(f"| `{tool.name}` | `{tool_scope_map.get(tool.name, 'unknown')}` | {title} |")
        lines.extend(
            [
                "",
                "## scope_map",
                "Tools marked `mcp:read` are evidence-only reads. Tools marked `mcp:preview` prepare bounded previews. Tools marked `mcp:commit` require explicit operator authorization and are not invoked by this evidence draft. Tools marked `action-dependent` choose read, preview, or commit scope from their explicit action/workflow arguments.",
                "",
                "## side_effects",
                "This evidence draft is generated by a read-only MCP tool. It does not start executors, run validation, write files, commit, push, replace stable service, create OpenAI App drafts, submit review, publish, or read tokens/cookies/raw logs.",
                "",
                "## safety_boundaries",
                "Submission write actions remain separated behind `fill_submission_evidence_files` with `mcp:commit` scope. Ready fields remain false until a human reviewer confirms final evidence.",
            ]
        )
        return "\n".join(lines) + "\n"

    def _auto_security_review_evidence(self, context: dict[str, Any]) -> str:
        connector_health = context.get("connector_health") if isinstance(context.get("connector_health"), dict) else {}
        runtime_status = context.get("runtime_status") if isinstance(context.get("runtime_status"), dict) else {}
        return "\n".join(
            [
                "# Security And Privacy Review Evidence",
                "",
                "## least_privilege",
                "The Commander and release-evidence draft paths are read-only. Write tools remain separate and require `mcp:commit` scope. Remote/public MCP policy denies commit/plan scopes unless explicitly authorized by the configured service policy.",
                "",
                "## consent",
                "The generated submission evidence payload is a preview only. Operators must review and replace any draft text before calling `fill_submission_evidence_files`. The preview keeps `mark_ready=false` by default.",
                "",
                "## redaction",
                "This draft is built from sanitized service facts: tool names, scopes, runtime freshness, and connector summary statuses. It does not read token values, cookies, browser login state, provider config, raw logs, tunnel-client config, or proxy config.",
                "",
                "## monitoring",
                f"Runtime reload awareness: {runtime_status.get('reload_awareness_reason') or 'unknown'}",
                f"Reload needed for verification: {self._submission_evidence_value(runtime_status.get('reload_needed_for_verification'))}",
                f"Connector overall status: {connector_health.get('overall_status') or 'unknown'}",
                f"Operator closeout status: {((connector_health.get('operator_closeout') or {}) if isinstance(connector_health.get('operator_closeout'), dict) else {}).get('status') or 'unknown'}",
                "",
                "## review_status",
                "Human security/privacy review is still required before marking `security_review_ready=true`.",
            ]
        ) + "\n"

    def _auto_metadata_snapshot_evidence(self, context: dict[str, Any]) -> str:
        runtime_status = context.get("runtime_status") if isinstance(context.get("runtime_status"), dict) else {}
        connector_health = context.get("connector_health") if isinstance(context.get("connector_health"), dict) else {}
        local_service = connector_health.get("local_service") if isinstance(connector_health.get("local_service"), dict) else {}
        external_connector = connector_health.get("external_connector") if isinstance(connector_health.get("external_connector"), dict) else {}
        visible_tool_defs = context.get("visible_tool_defs") if isinstance(context.get("visible_tool_defs"), list) else []
        return "\n".join(
            [
                "# Metadata Snapshot Evidence",
                "",
                "## app_metadata",
                "App name: ColaMeta",
                "Description: Project console for local AI engineering workflows.",
                f"Project name: {context.get('project_name') or '-'}",
                f"Service mode: {self._submission_evidence_value(context.get('service_mode'))}",
                f"MCP exposure profile: {context.get('mcp_exposure_profile') or '-'}",
                "",
                "## urls",
                "Public MCP URL and privacy/company URLs must be confirmed by the human submitter before Dashboard submission.",
                "",
                "## assets",
                "Logo and screenshots are not generated by this auto draft and must be provided separately.",
                "",
                "## runtime_snapshot",
                f"Project checkout head: {runtime_status.get('project_checkout_head') or '-'}",
                f"Loaded runtime head: {runtime_status.get('loaded_runtime_head') or '-'}",
                f"Runtime stale: {self._submission_evidence_value(runtime_status.get('runtime_loaded_code_stale'))}",
                f"Reload needed for verification: {self._submission_evidence_value(runtime_status.get('reload_needed_for_verification'))}",
                "",
                "## connector_snapshot",
                f"Local service status: {local_service.get('status') or local_service.get('state') or 'unknown'}",
                f"External connector status: {external_connector.get('status') or 'unknown'}",
                f"Connector overall status: {connector_health.get('overall_status') or 'unknown'}",
                "",
                "## tool_metadata",
                f"Visible tool count: {len(visible_tool_defs)}",
                "Review the MCP tool information evidence for the full tool inventory and scope map.",
                "",
                "## reviewer",
                "Human reviewer must confirm final Dashboard metadata, URLs, logo, screenshots, and policy text before marking `metadata_snapshot_reviewed=true`.",
            ]
        ) + "\n"

    @staticmethod
    def _submission_evidence_value(value: Any) -> str:
        if value is True:
            return "true"
        if value is False:
            return "false"
        if value is None:
            return "unknown"
        return str(value)

    def _tool_get_release_submission_readiness(self, params: dict[str, Any]) -> dict[str, Any]:
        project_root, project_record = self._resolve_read_only_project_context(params)
        project_name = self._project_name_for_context(project_root, project_record, params)
        return build_release_submission_readiness(
            project_root,
            project_name=project_name,
            app_name=params.get("app_name") if isinstance(params.get("app_name"), str) else None,
            app_description=params.get("app_description") if isinstance(params.get("app_description"), str) else None,
            company_url=params.get("company_url") if isinstance(params.get("company_url"), str) else None,
            privacy_policy_url=params.get("privacy_policy_url") if isinstance(params.get("privacy_policy_url"), str) else None,
            logo_ready=bool(params.get("logo_ready")),
            screenshots_ready=bool(params.get("screenshots_ready")),
            test_prompts_ready=bool(params.get("test_prompts_ready")),
            test_responses_ready=bool(params.get("test_responses_ready")),
            localization_ready=bool(params.get("localization_ready")),
            mcp_tool_info_ready=bool(params.get("mcp_tool_info_ready")),
            app_management_permissions_confirmed=bool(params.get("app_management_permissions_confirmed")),
            security_review_ready=bool(params.get("security_review_ready")),
            metadata_snapshot_reviewed=bool(params.get("metadata_snapshot_reviewed")),
            submission_confirmations_ready=bool(params.get("submission_confirmations_ready")),
            submission_materials=params.get("submission_materials")
            if isinstance(params.get("submission_materials"), dict)
            else None,
        )

    def _tool_init_submission_evidence(self, params: dict[str, Any]) -> dict[str, Any]:
        if params.get("project_name") is not None:
            return self._route_project_name_tool("init_submission_evidence", params, require_managed=True)
        result = init_submission_evidence_scaffold(
            self.project_root,
            app_name=str(params.get("app_name") or "ColaMeta"),
            app_description=str(params.get("app_description") or "Project console for local AI engineering workflows."),
            company_url=str(params.get("company_url") or "https://example.com"),
            privacy_policy_url=str(params.get("privacy_policy_url") or "https://example.com/privacy"),
        )
        self._record_workflow_if_needed("init_submission_evidence", "apply", params, result)
        return result

    def _tool_fill_submission_evidence_files(self, params: dict[str, Any]) -> dict[str, Any]:
        if params.get("project_name") is not None:
            return self._route_project_name_tool("fill_submission_evidence_files", params, require_managed=True)
        entries = params.get("entries")
        result = fill_submission_evidence_files(
            self.project_root,
            entries=entries if isinstance(entries, list) else [],
            mark_ready=bool(params.get("mark_ready")),
        )
        self._record_workflow_if_needed("fill_submission_evidence_files", "apply", params, result)
        return result

    def _tool_mark_submission_evidence_ready_fields(self, params: dict[str, Any]) -> dict[str, Any]:
        if params.get("project_name") is not None:
            return self._route_project_name_tool("mark_submission_evidence_ready_fields", params, require_managed=True)
        keys = params.get("keys")
        result = mark_submission_evidence_ready_fields(
            self.project_root,
            keys=keys if isinstance(keys, list) else [],
            review_confirmation=str(params.get("review_confirmation") or ""),
        )
        self._record_workflow_if_needed("mark_submission_evidence_ready_fields", "apply", params, result)
        return result

    def _tool_render_commander_app(self, params: dict[str, Any]) -> dict[str, Any]:
        manifest = self._commander_app_manifest(params)
        manifest["_meta"] = {
            "ui": {
                "resourceUri": COMMANDER_APP_WIDGET_URI,
                "visibility": ["model", "app"],
            },
            "openai/outputTemplate": COMMANDER_APP_WIDGET_URI,
            "commander_app": {
                "manifest_version": COMMANDER_APP_MANIFEST_VERSION,
                "widget_resource_uri": COMMANDER_APP_WIDGET_URI,
                "project_name": manifest.get("project_name"),
                "profile_id": (
                    manifest.get("agent_operator_flow_profile", {}).get("profile_id")
                    if isinstance(manifest.get("agent_operator_flow_profile"), dict)
                    else None
                ),
            },
        }
        return manifest

    def _tool_get_apps_connector_smoke_packet(self, params: dict[str, Any]) -> dict[str, Any]:
        project_root, project_record = self._resolve_read_only_project_context(params)
        tunnel_client = self._connector_external_evidence_param(params, "tunnel_client")
        control_plane = self._connector_external_evidence_param(params, "control_plane")
        local_service = self._connector_runtime_local_service_evidence(project_root)
        runtime_status = get_runtime_version_status(project_root, local_service=local_service)
        connector_health = get_connector_runtime_health_status(
            runtime_status=runtime_status,
            local_service=local_service,
            tunnel_client=tunnel_client,
            control_plane=control_plane,
        )
        project_name = self._project_name_for_context(project_root, project_record, params)
        apps_connector_closeout = build_apps_connector_closeout_packet(
            project_name=project_name,
            connector_health=connector_health,
        )
        release_submission_evidence = self._apps_connector_release_submission_evidence(
            project_root=project_root,
            project_name=project_name,
            connector_health=connector_health,
            apps_connector_closeout=apps_connector_closeout,
        )
        apps_connector_closeout = {
            **apps_connector_closeout,
            "release_submission_evidence": release_submission_evidence,
        }
        return {
            "ok": True,
            "source": "apps_connector_smoke_packet",
            "scope": "mcp:read",
            "read_only": True,
            "side_effects": False,
            "project_name": project_name,
            "apps_connector_closeout": apps_connector_closeout,
            "release_submission_evidence": release_submission_evidence,
            "connector_runtime_health": connector_health,
            "runtime": {
                "project_checkout_head": runtime_status.get("project_checkout_head"),
                "loaded_runtime_head": runtime_status.get("loaded_runtime_head"),
                "runtime_loaded_code_stale": runtime_status.get("runtime_loaded_code_stale"),
                "reload_needed_for_verification": runtime_status.get("reload_needed_for_verification"),
                "reload_awareness_reason": runtime_status.get("reload_awareness_reason"),
            },
            "stable_replacement_hint": self._stable_replacement_hint(project_root, runtime_status),
            "operator_sequence": [
                apps_connector_closeout["project_list_check"],
                apps_connector_closeout["preferred_smoke_tool"],
                apps_connector_closeout["connector_closeout_check"],
            ],
            "token_expired_recovery": apps_connector_closeout["token_expired_recovery"],
            "metadata_refresh_guidance": apps_connector_closeout["metadata_refresh_guidance"],
            "authority_boundary": {
                "read_only": True,
                "does_not_read_tokens_or_cookies": True,
                "does_not_read_browser_login_state": True,
                "does_not_read_tunnel_client_config": True,
                "does_not_read_raw_logs": True,
                "does_not_restart_tunnel_client": True,
                "does_not_modify_proxy_or_auth_config": True,
                "does_not_authorize_executor_run": True,
                "does_not_authorize_commit_or_push": True,
                "does_not_authorize_stable_replacement": True,
            },
        }

    def _tool_get_stable_replacement_cadence(self, params: dict[str, Any]) -> dict[str, Any]:
        project_root, _ = self._resolve_read_only_project_context(params)
        local_service = self._connector_runtime_local_service_evidence(project_root)
        runtime_status = get_runtime_version_status(project_root, local_service=local_service)
        return self._stable_replacement_hint(project_root, runtime_status)

    def _commander_app_manifest(self, params: dict[str, Any]) -> dict[str, Any]:
        project_root, project_record = self._resolve_read_only_project_context(params)
        tunnel_client = self._connector_external_evidence_param(params, "tunnel_client")
        control_plane = self._connector_external_evidence_param(params, "control_plane")
        local_service = self._connector_runtime_local_service_evidence(project_root)
        runtime_status = get_runtime_version_status(project_root, local_service=local_service)
        connector_health = get_connector_runtime_health_status(
            runtime_status=runtime_status,
            local_service=local_service,
            tunnel_client=tunnel_client,
            control_plane=control_plane,
        )
        connector_summary = copy.deepcopy(connector_health)
        local_service_summary = connector_summary.get("local_service")
        external_connector_summary = connector_summary.get("external_connector")
        operator_closeout = connector_summary.get("operator_closeout")
        if isinstance(local_service_summary, dict):
            connector_summary["local_service_status"] = local_service_summary.get("status")
        if isinstance(external_connector_summary, dict):
            connector_summary["external_connector_status"] = external_connector_summary.get("status")
        if isinstance(operator_closeout, dict):
            connector_summary["operator_closeout_status"] = operator_closeout.get("status")

        project_identity = self._project_identity_for_root(project_root)
        if isinstance(project_record, dict):
            project_identity["project"] = project_record
        project_name = self._project_name_for_context(project_root, project_record, params)

        project_args = {"project_name": project_name}
        flow_profile_id, flow_profile, profiles = self._select_service_entry_profile(params)
        visible_names = self._visible_tool_names()
        readiness = build_service_readiness_summary(
            runtime_status=runtime_status,
            connector_health=connector_health,
            project_name=project_name,
        )
        apps_connector_closeout = build_apps_connector_closeout_packet(
            project_name=project_name,
            connector_health=connector_health,
        )
        release_submission_evidence = self._apps_connector_release_submission_evidence(
            project_root=project_root,
            project_name=project_name,
            connector_health=connector_health,
            apps_connector_closeout=apps_connector_closeout,
            compact_progress=True,
        )
        apps_connector_closeout = {
            **apps_connector_closeout,
            "release_submission_evidence": release_submission_evidence,
        }
        app_status = str(connector_summary.get("overall_status") or "unknown")
        readiness_status = str(readiness.get("status") or app_status)
        runtime_label = "runtime_current" if runtime_status.get("reload_needed_for_verification") is False else "runtime_needs_verification"
        runtime_summary = {
            "project_checkout_head": runtime_status.get("project_checkout_head"),
            "loaded_runtime_head": runtime_status.get("loaded_runtime_head"),
            "runtime_loaded_code_stale": runtime_status.get("runtime_loaded_code_stale"),
            "reload_needed_for_verification": runtime_status.get("reload_needed_for_verification"),
            "reload_awareness_reason": runtime_status.get("reload_awareness_reason"),
            "restart_needed_state": runtime_status.get("restart_needed_state"),
            "restart_needed_reason": runtime_status.get("restart_needed_reason"),
            "details_tool": "get_runtime_version_status",
            "details_arguments": project_args,
        }
        flow_args = {"profile_id": flow_profile_id, "include_advanced_context": False}
        if self.service_mode or params.get("project_name") is not None:
            flow_args.update(project_args)
        agent_operator_flow = self._tool_get_agent_operator_flow_packet(flow_args)
        flow_profile_summary = {
            "profile_id": flow_profile_id,
            "display_name": flow_profile.get("display_name"),
            "consumer_kind": flow_profile.get("consumer_kind"),
            "default_authority": flow_profile.get("default_authority"),
            "write_boundary": flow_profile.get("write_boundary"),
        }
        return {
            "ok": True,
            "read_only": True,
            "side_effects": False,
            "app_manifest_version": COMMANDER_APP_MANIFEST_VERSION,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "project_name": project_name,
            "app": {
                "name": COMMANDER_APP_TITLE,
                "status_line": f"{readiness_status} | {runtime_label}",
                "archetype": "interactive-decoupled",
                "widget_resource_uri": COMMANDER_APP_WIDGET_URI,
                "widget_mime_type": COMMANDER_APP_WIDGET_MIME_TYPE,
                "data_tool": "get_commander_app_manifest",
                "render_tool": "render_commander_app",
                "resource_methods": ["resources/list", "resources/read"],
                "embedded_flow_profile_id": flow_profile_id,
            },
            "service_profile": {
                "service_name": "ColaMeta MCP",
                "mode": "service" if self.service_mode else "project",
                "mcp_exposure_profile": self.mcp_exposure_profile,
                "project_name_required_for_project_tools": bool(self.service_mode),
                "project_hint": self.project_hint,
                "visible_tool_count": len(visible_names),
            },
            "project_identity": project_identity,
            "readiness": readiness,
            "agent_operator_flow_profile": flow_profile_summary,
            "agent_operator_flow": agent_operator_flow,
            "apps_connector_closeout": apps_connector_closeout,
            "runtime": runtime_summary,
            "connector": connector_summary,
            "registered_projects": self._web_gpt_registered_project_summary(),
            "profiles": profiles,
            "initial_reads": [
                {"tool": "list_registered_projects", "arguments": {}},
                {"tool": "get_agent_consumer_contract", "arguments": {}},
                {"tool": "get_service_entry_profile", "arguments": {"profile_id": flow_profile_id}},
                {"tool": "get_agent_operator_flow_packet", "arguments": {**project_args, "profile_id": flow_profile_id}},
                {"tool": "render_commander_app", "arguments": {**project_args, "profile_id": flow_profile_id}},
                {"tool": "get_stable_replacement_cadence", "arguments": project_args},
                {"tool": "get_stage_parallel_plan_preview", "arguments": project_args},
                {"tool": "get_stage_parallel_run_preview", "arguments": project_args},
                {"tool": "get_stage_parallel_worktree_assignment_preview", "arguments": project_args},
                {"tool": "get_stage_parallel_next_action_packet", "arguments": project_args},
                {"tool": "manage_stage_parallel_shard_inputs", "arguments": {**project_args, "action": "preview"}},
                {"tool": "get_stage_parallel_executor_group_preview", "arguments": project_args},
                {"tool": "manage_stage_parallel_executor_runs", "arguments": {**project_args, "action": "preview"}},
                {"tool": "get_stage_parallel_executor_results_packet", "arguments": project_args},
                {"tool": "get_stage_parallel_group_status", "arguments": project_args},
                {"tool": "get_stage_parallel_merge_preview", "arguments": project_args},
                {"tool": "manage_stage_parallel_merges", "arguments": {**project_args, "action": "preview"}},
                {"tool": "get_stage_parallel_closeout_packet", "arguments": project_args},
                {"tool": "get_apps_connector_smoke_packet", "arguments": project_args},
                {"tool": "get_submission_evidence_auto_draft", "arguments": project_args},
                {"tool": "get_submission_evidence_fill_preview", "arguments": project_args},
                {"tool": "get_connector_runtime_health_status", "arguments": project_args},
                {"tool": "analyze_project_state", "arguments": project_args},
            ],
            "commander_panel": {
                "primary_sections": [
                    "agent_operator_flow",
                    "service_readiness",
                    "apps_connector_closeout",
                    "release_submission_evidence",
                    "service_facts",
                    "runtime_freshness",
                    "connector_health",
                    "profile_aware_entries",
                    "preview_first_workflows",
                    "authorization_gates",
                ],
                "read_actions": [
                    {"tool": "get_commander_app_manifest", "arguments": {**project_args, "profile_id": flow_profile_id}},
                    {"tool": "get_agent_operator_flow_packet", "arguments": {**project_args, "profile_id": flow_profile_id}},
                    {"tool": "get_product_console_map", "arguments": project_args},
                    {"tool": "get_release_submission_readiness", "arguments": project_args},
                    {"tool": "get_submission_evidence_auto_draft", "arguments": project_args},
                    {"tool": "get_submission_evidence_fill_preview", "arguments": project_args},
                    {"tool": "get_apps_connector_smoke_packet", "arguments": project_args},
                    {"tool": "get_stable_replacement_cadence", "arguments": project_args},
                    {"tool": "get_stage_parallel_plan_preview", "arguments": project_args},
                    {"tool": "get_stage_parallel_run_preview", "arguments": project_args},
                    {"tool": "get_stage_parallel_worktree_assignment_preview", "arguments": project_args},
                    {"tool": "get_stage_parallel_next_action_packet", "arguments": project_args},
                    {"tool": "manage_stage_parallel_shard_inputs", "arguments": {**project_args, "action": "preview"}},
                    {"tool": "get_stage_parallel_executor_group_preview", "arguments": project_args},
                    {"tool": "manage_stage_parallel_executor_runs", "arguments": {**project_args, "action": "preview"}},
                    {"tool": "get_stage_parallel_executor_results_packet", "arguments": project_args},
                    {"tool": "get_stage_parallel_group_status", "arguments": project_args},
                    {"tool": "get_stage_parallel_merge_preview", "arguments": project_args},
                    {"tool": "manage_stage_parallel_merges", "arguments": {**project_args, "action": "preview"}},
                    {"tool": "get_stage_parallel_closeout_packet", "arguments": project_args},
                    {"tool": "get_runtime_version_status", "arguments": project_args},
                    {"tool": "get_connector_runtime_health_status", "arguments": project_args},
                    apps_connector_closeout["connector_closeout_check"],
                    {"tool": "analyze_project_state", "arguments": project_args},
                ],
                "preview_first_actions": [
                    {
                        "tool": "run_mcp_workflow",
                        "arguments": {
                            **project_args,
                            "workflow": "thin_governed_loop_preview",
                            "phase": "preview",
                            "input_mode": "draft",
                        },
                    },
                    {
                        "tool": "manage_validation_run",
                        "arguments": {
                            **project_args,
                            "action": "preview",
                            "scope": "target_files",
                        },
                    },
                    {
                        "tool": "manage_stage_parallel_worktrees",
                        "arguments": {
                            **project_args,
                            "action": "preview",
                            "stage_id": "stage_parallel_automation",
                        },
                    },
                    {
                        "tool": "manage_stage_parallel_executor_group",
                        "arguments": {
                            **project_args,
                            "action": "preview",
                            "stage_id": "stage_parallel_automation",
                        },
                    },
                    {
                        "tool": "manage_stage_parallel_executor_runs",
                        "arguments": {
                            **project_args,
                            "action": "preview",
                            "stage_id": "stage_parallel_automation",
                        },
                    },
                    {
                        "tool": "manage_stage_parallel_merges",
                        "arguments": {
                            **project_args,
                            "action": "preview",
                            "stage_id": "stage_parallel_automation",
                        },
                    },
                    {
                        "tool": "manage_executor_workflow",
                        "arguments": {
                            **project_args,
                            "action": "run_once_preview",
                            "provider": "codex",
                            "profile_id": "local_codex_commander",
                        },
                    },
                ],
            },
            "preview_first_workflows": {
                "thin_governed_loop": (
                    "draft -> local Codex codex_execution_packet for M0-M2; "
                    "provided next_request_payload only for formal evidence preview"
                ),
                "validation": "preview -> explicit authorization -> run -> status",
                "executor": "run_once_preview -> explicit authorization -> run_once -> status -> get_executor_run_report",
            },
            "authority_boundary": {
                "read_only_tools_do_not_authorize_executor_dispatch": True,
                "read_only_tools_do_not_create_review_decision": True,
                "read_only_tools_do_not_emit_gate_event": True,
                "read_only_tools_do_not_write_delivery_state": True,
                "does_not_authorize_stable_promotion": True,
                "does_not_authorize_executor_run": True,
                "does_not_authorize_commit_or_push": True,
                "requires_explicit_commander_authorization_for": [
                    "executor run",
                    "commit",
                    "push",
                    "stable service replacement",
                    "ReviewDecision",
                    "GateEvent",
                    "Delivery accepted",
                ],
            },
            "connector_recovery": {
                "healthy_path": [
                    "call list_registered_projects",
                    "call render_commander_app with project_name and profile_id",
                    "provide sanitized tunnel_client/control_plane evidence when available",
                    "if Apps connector returns token_expired, reconnect the Apps connector session",
                ],
                "apps_connector_closeout": self._apps_connector_recovery_closeout_summary(apps_connector_closeout),
                "accepted_external_evidence_fields": ["status", "reason_code", "evidence_source", "last_observed_at"],
                "forbidden_evidence": ["token", "cookie", "credential", "raw_log", "provider_raw_response", "browser_login_state"],
            },
            "docs_alignment": {
                "tools": "one-job read tools plus a render tool",
                "ui": "MCP Apps bridge iframe resource",
                "resource_uri": COMMANDER_APP_WIDGET_URI,
            },
            "visible_tool_names": visible_names,
        }

    def _web_gpt_registered_project_summary(self) -> list[dict[str, Any]]:
        try:
            projects = self.project_registry.list_projects().get("projects", [])
        except Exception:
            projects = []
        summary: list[dict[str, Any]] = []
        if not isinstance(projects, list):
            return summary
        for project in projects:
            if not isinstance(project, dict):
                continue
            name = project.get("project_name")
            root = project.get("project_root") or project.get("path")
            if not isinstance(name, str) or not name.strip():
                continue
            item = {
                "project_name": name.strip(),
                "project_root": root if isinstance(root, str) else "",
                "project_mode": project.get("project_mode"),
                "runner_managed": bool(project.get("runner_managed")),
                "last_selected": bool(project.get("last_selected")),
            }
            summary.append(item)
        return summary[:20]

    def _project_name_for_context(
        self,
        project_root: str,
        project_record: dict[str, Any] | None,
        params: dict[str, Any],
    ) -> str:
        if isinstance(project_record, dict) and isinstance(project_record.get("project_name"), str):
            project_name = str(project_record.get("project_name") or "").strip()
            if project_name:
                return project_name
        raw_project_name = params.get("project_name")
        if isinstance(raw_project_name, str) and raw_project_name.strip():
            return raw_project_name.strip()
        return os.path.basename(project_root.rstrip(os.sep)) or self.project_hint

    def _stable_replacement_hint(self, project_root: str, runtime_status: dict[str, Any]) -> dict[str, Any]:
        candidate_head = runtime_status.get("project_checkout_head")
        stable_metadata = git_checkout_metadata(DEFAULT_STABLE_RUNTIME_DIR)
        stable_head = stable_metadata.get("head")
        return build_stable_replacement_cadence(
            project_root=project_root,
            candidate_head=candidate_head if isinstance(candidate_head, str) else None,
            stable_runtime_dir=DEFAULT_STABLE_RUNTIME_DIR,
            stable_runtime_head=stable_head if isinstance(stable_head, str) else None,
        )

    def _apps_connector_release_submission_evidence(
        self,
        *,
        project_root: str,
        project_name: str,
        connector_health: dict[str, Any],
        apps_connector_closeout: dict[str, Any],
        compact_progress: bool = False,
    ) -> dict[str, Any]:
        connector_ready = apps_connector_closeout.get("status") == "ready"
        overall_status = str(connector_health.get("overall_status") or "unknown")
        ready = connector_ready and overall_status == "healthy"
        readiness_packet: dict[str, Any] = {
            "ready": ready,
            "status": "ready" if ready else "needs_attention",
            "public_base_url": None,
            "connector_url": None,
            "primary_blocker": None
            if ready
            else {
                "component": "apps_connector_closeout",
                "reason_code": "APPS_CONNECTOR_CLOSEOUT_NOT_READY",
                "status": apps_connector_closeout.get("status"),
                "overall_status": overall_status,
            },
            "ops_check": {
                "ops_check_ready": ready,
                "connector_smoke_ready": connector_ready,
                "beta_gate_ready": ready,
            },
        }
        release_submission = build_release_submission_readiness(
            project_root,
            project_name=project_name,
            readiness_packet=readiness_packet,
        )
        evidence_progress = release_submission.get("submission_evidence_progress")
        if compact_progress:
            evidence_progress = self._compact_submission_evidence_progress(evidence_progress)
        submission_activity = build_submission_evidence_activity_result(project_root)
        return {
            "ok": True,
            "source": "release_submission_evidence_closeout",
            "schema_version": "release_submission_evidence_closeout.v1",
            "tool": "get_release_submission_readiness",
            "arguments": {"project_name": project_name},
            "read_only": True,
            "side_effects": False,
            "status": release_submission.get("status"),
            "ready": release_submission.get("ready") is True,
            "evidence_progress": evidence_progress,
            "submission_evidence_activity": submission_activity,
            "safe_next_action": release_submission.get("safe_next_action"),
            "blocker_codes": release_submission.get("blocker_codes") or [],
            "needs_attention_codes": release_submission.get("needs_attention_codes") or [],
            "authority_boundary": {
                "read_only": True,
                "does_not_submit_app_for_review": True,
                "does_not_publish_app": True,
                "does_not_call_openai_dashboard_or_api": True,
                "does_not_read_tokens_or_cookies": True,
                "does_not_authorize_executor_run": True,
                "does_not_authorize_commit_or_push": True,
                "does_not_authorize_stable_replacement": True,
            },
        }

    def _apps_connector_recovery_closeout_summary(self, apps_connector_closeout: dict[str, Any]) -> dict[str, Any]:
        recovery_summary = dict(apps_connector_closeout)
        recovery_summary.pop("release_submission_evidence", None)
        return recovery_summary

    def _compact_submission_evidence_progress(self, progress: Any) -> dict[str, Any] | None:
        if not isinstance(progress, dict):
            return None
        rows = progress.get("rows")
        compact_rows: list[dict[str, Any]] = []
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                compact_rows.append(
                    {
                        "key": row.get("key"),
                        "ready_field": row.get("ready_field"),
                        "ready": row.get("ready") is True,
                        "status": row.get("status"),
                        "refs": row.get("refs") if isinstance(row.get("refs"), list) else [],
                        "default_path": row.get("default_path"),
                        "next_action": row.get("next_action") if isinstance(row.get("next_action"), dict) else None,
                    }
                )
        return {
            "source": progress.get("source"),
            "schema_version": progress.get("schema_version"),
            "status": progress.get("status"),
            "complete_count": progress.get("complete_count"),
            "total_count": progress.get("total_count"),
            "counts": progress.get("counts") if isinstance(progress.get("counts"), dict) else {},
            "rows": compact_rows,
            "manifest_available": progress.get("manifest_available"),
            "read_only": progress.get("read_only") is True,
            "side_effects": progress.get("side_effects") is True,
            "compact": True,
        }

    def _tool_get_stable_promotion_readiness(self, params: dict[str, Any]) -> dict[str, Any]:
        project_root, _ = self._resolve_read_only_project_context(params)
        return get_stable_promotion_readiness(
            project_root,
            visible_tool_names=self._visible_tool_names(),
            supported_workflows=list(_SUPPORTED_MCP_WORKFLOWS),
            service_mode=self.service_mode,
            mcp_exposure_profile=self.mcp_exposure_profile,
            registered_projects=self._web_gpt_registered_project_summary(),
        )

    def _tool_get_stage_parallel_plan_preview(self, params: dict[str, Any]) -> dict[str, Any]:
        project_root, project_record = self._resolve_read_only_project_context(params)
        project_name = self._project_name_for_context(project_root, project_record, params)
        return build_stage_parallel_plan_preview(
            project_root=project_root,
            project_name=project_name,
            stage_id=params.get("stage_id") if isinstance(params.get("stage_id"), str) else None,
            task_intents=params.get("task_intents") if isinstance(params.get("task_intents"), list) else None,
            max_parallel_tasks=params.get("max_parallel_tasks") if isinstance(params.get("max_parallel_tasks"), int) else None,
        )

    def _stage_parallel_builder_args(self, params: dict[str, Any]) -> dict[str, Any]:
        project_root, project_record = self._resolve_read_only_project_context(params)
        project_name = self._project_name_for_context(project_root, project_record, params)
        return {
            "project_root": project_root,
            "project_name": project_name,
            "stage_id": params.get("stage_id") if isinstance(params.get("stage_id"), str) else None,
            "task_intents": params.get("task_intents") if isinstance(params.get("task_intents"), list) else None,
            "max_parallel_tasks": params.get("max_parallel_tasks") if isinstance(params.get("max_parallel_tasks"), int) else None,
            "provider": params.get("provider") if isinstance(params.get("provider"), str) else None,
            "base_branch": params.get("base_branch") if isinstance(params.get("base_branch"), str) else None,
        }

    def _tool_get_stage_parallel_run_preview(self, params: dict[str, Any]) -> dict[str, Any]:
        return build_stage_parallel_run_preview(**self._stage_parallel_builder_args(params))

    def _tool_get_stage_parallel_worktree_assignment_preview(self, params: dict[str, Any]) -> dict[str, Any]:
        return build_stage_parallel_worktree_assignment_preview(**self._stage_parallel_builder_args(params))

    def _tool_get_stage_parallel_next_action_packet(self, params: dict[str, Any]) -> dict[str, Any]:
        return build_stage_parallel_next_action_packet(**self._stage_parallel_builder_args(params))

    def _tool_get_stage_parallel_executor_group_preview(self, params: dict[str, Any]) -> dict[str, Any]:
        return build_stage_parallel_executor_group_preview(**self._stage_parallel_builder_args(params))

    def _tool_get_stage_parallel_executor_results_packet(self, params: dict[str, Any]) -> dict[str, Any]:
        return build_stage_parallel_executor_results_packet(**self._stage_parallel_builder_args(params))

    def _tool_get_stage_parallel_group_status(self, params: dict[str, Any]) -> dict[str, Any]:
        args = self._stage_parallel_builder_args(params)
        args["executor_results"] = params.get("executor_results") if isinstance(params.get("executor_results"), list) else None
        return build_stage_parallel_group_status(**args)

    def _tool_get_stage_parallel_merge_preview(self, params: dict[str, Any]) -> dict[str, Any]:
        args = self._stage_parallel_builder_args(params)
        args["executor_results"] = params.get("executor_results") if isinstance(params.get("executor_results"), list) else None
        return build_stage_parallel_merge_preview(**args)

    def _tool_get_stage_parallel_closeout_packet(self, params: dict[str, Any]) -> dict[str, Any]:
        args = self._stage_parallel_builder_args(params)
        args["executor_results"] = params.get("executor_results") if isinstance(params.get("executor_results"), list) else None
        return build_stage_parallel_closeout_packet(**args)

    def _tool_get_project_identity(self, params: dict[str, Any]) -> dict[str, Any]:
        project_root, project_record = self._resolve_read_only_project_context(params)
        visible_names = self._visible_tool_names()
        return {
            "ok": True,
            "project_identity": self._project_identity_for_root(project_root),
            "mcp_exposure_profile": self.mcp_exposure_profile,
            "visible_tool_count": len(visible_names),
            "visible_tool_names": visible_names,
            "project": project_record,
        }

    def _tool_get_plan_standards_report(self, params: dict[str, Any]) -> dict[str, Any]:
        if params.get("project_name") is not None:
            return self._route_project_name_tool("get_plan_standards_report", params, require_managed=True)
        return PlanStandardsLinter().lint_project(self.project_root)

    def _tool_get_runner_execution_standards(self, params: dict[str, Any]) -> dict[str, Any]:
        section = params.get("section")
        if section is not None and not isinstance(section, str):
            raise MCPToolInputError("INVALID_SECTION", "section 必须是字符串。")
        return get_execution_standards(section=section)

    def _tool_get_runtime_version_status(self, params: dict[str, Any]) -> dict[str, Any]:
        project_root, _ = self._resolve_read_only_project_context(params)
        return get_runtime_version_status(
            project_root,
            local_service=self._connector_runtime_local_service_evidence(project_root),
        )

    def _tool_get_connector_runtime_health_status(self, params: dict[str, Any]) -> dict[str, Any]:
        project_root, _ = self._resolve_read_only_project_context(params)
        tunnel_client = self._connector_external_evidence_param(params, "tunnel_client")
        control_plane = self._connector_external_evidence_param(params, "control_plane")
        local_service = self._connector_runtime_local_service_evidence(project_root)
        return get_connector_runtime_health_status(
            runtime_status=get_runtime_version_status(project_root, local_service=local_service),
            local_service=local_service,
            tunnel_client=tunnel_client,
            control_plane=control_plane,
        )

    @staticmethod
    def _connector_external_evidence_param(params: dict[str, Any], key: str) -> dict[str, Any] | None:
        value = params.get(key)
        if value is None:
            return None
        if not isinstance(value, dict):
            raise MCPToolInputError("INVALID_CONNECTOR_EVIDENCE", f"{key} 必须是对象。")
        allowed = {"status", "reason_code", "evidence_source", "last_observed_at"}
        extra = [item for item in value if item not in allowed]
        if extra:
            raise MCPToolInputError(
                "UNSAFE_CONNECTOR_EVIDENCE",
                f"{key} 只能包含 sanitized evidence 字段。",
                {"field": key, "allowed_fields": sorted(allowed), "rejected_field_count": len(extra)},
            )
        return dict(value)

    def _connector_runtime_local_service_evidence(self, project_root: str) -> dict[str, Any] | None:
        parts = ServiceLifecycleStore.read_process_cmdline_parts(os.getpid()) or []
        for index, token in enumerate(parts):
            if token != "serve" or index + 1 >= len(parts):
                continue
            project_token = parts[index + 1]
            if not self._project_token_matches(project_token, project_root):
                continue
            args = parts[index + 2:]
            enable_web = "--no-web" not in args
            enable_mcp = "--no-mcp" not in args
            web_host = self._cmd_option_value(args, "--web-host", "127.0.0.1")
            web_port = self._cmd_option_int(args, "--web-port", 8799)
            mcp_host = self._cmd_option_value(args, "--mcp-host", "127.0.0.1")
            mcp_port = self._cmd_option_int(args, "--mcp-port", 8765)
            return {
                "state": "running",
                "health_source": "process_table",
                "pid": os.getpid(),
                "project_root": project_root,
                "metadata_project_matches": True,
                "discovered_from_process_table": True,
                "enable_web": enable_web,
                "web_state": (
                    "healthy"
                    if enable_web and self._local_http_healthz_ok(web_host, web_port, "colameta-web-console", "/api/healthz")
                    else ("disabled" if not enable_web else "starting")
                ),
                "web_url": f"http://{web_host}:{web_port}" if enable_web else None,
                "web_host": web_host,
                "web_port": web_port,
                "enable_mcp": enable_mcp,
                "mcp_state": "healthy" if enable_mcp else None,
                "mcp_url": f"http://{mcp_host}:{mcp_port}/mcp" if enable_mcp else None,
                "mcp_host": mcp_host,
                "mcp_port": mcp_port,
            }
        return None

    @staticmethod
    def _project_token_matches(value: str, project_root: str) -> bool:
        return os.path.realpath(os.path.abspath(os.path.expanduser(value))) == os.path.realpath(project_root)

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
            return int(MCPPlanningBridgeServer._cmd_option_value(args, name, str(default)))
        except ValueError:
            return default

    @staticmethod
    def _local_http_healthz_ok(host: Any, port: Any, expected_service: str, path: str = "/healthz") -> bool:
        host_text = str(host or "").strip()
        if host_text not in {"127.0.0.1", "localhost", "::1"}:
            return False
        path_text = str(path or "").strip() or "/healthz"
        if not path_text.startswith("/") or "?" in path_text or "#" in path_text:
            return False
        try:
            port_int = int(port)
        except (TypeError, ValueError):
            return False
        if port_int <= 0:
            return False
        try:
            with urllib.request.urlopen(f"http://{host_text}:{port_int}{path_text}", timeout=2) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception:
            return False
        return bool(isinstance(payload, dict) and payload.get("ok") is True and payload.get("service") == expected_service)

    def _tool_get_runner_status(self, params: dict[str, Any]) -> dict[str, Any]:
        project_root, project_record = self._resolve_read_only_project_context(params)
        if isinstance(project_record, dict) and project_record.get("project_mode") == "source-only":
            raise MCPToolInputError(
                "PROJECT_MODE_UNSUPPORTED",
                "source-only 项目请使用 analyze_project_state 或 run_mcp_workflow workflow=project_status phase=inspect。",
                {"project_name": project_record.get("project_name")},
            )
        return self._with_project_identity(self.bridge.get_runner_status(project_root), project_root)

    def _tool_get_executor_session_status(self, _: dict[str, Any]) -> dict[str, Any]:
        return self._with_project_identity(ExecutorSessionStore(self.project_root).get_status())

    def _tool_get_executor_continuation_preview(self, _: dict[str, Any]) -> dict[str, Any]:
        return self._with_project_identity(ExecutorSessionStore(self.project_root).get_continuation_preview())

    def _tool_get_executor_continuation_decision(self, params: dict[str, Any]) -> dict[str, Any]:
        provider = params.get("provider")
        if not isinstance(provider, str) or provider.strip().lower() not in {"pi", "codex", "opencode"}:
            raise MCPToolInputError("INVALID_PROVIDER", "provider 必须是 pi、codex 或 opencode。")
        return self._with_project_identity(
            ExecutorSessionStore(self.project_root).get_continuation_decision(
                requested_provider=provider.strip().lower()
            )
        )

    def _tool_get_executor_resume_invocation_preview(self, params: dict[str, Any]) -> dict[str, Any]:
        provider = params.get("provider")
        if not isinstance(provider, str) or provider.strip().lower() not in {"pi", "codex", "opencode"}:
            raise MCPToolInputError("INVALID_PROVIDER", "provider 必须是 pi、codex 或 opencode。")
        return self._with_project_identity(
            ExecutorSessionStore(self.project_root).get_resume_invocation_preview(
                requested_provider=provider.strip().lower()
            )
        )

    def _tool_get_review_context(self, params: dict[str, Any]) -> dict[str, Any]:
        if params.get("project_name") is not None:
            return self._route_project_name_tool("get_review_context", params, require_managed=True)
        max_diff_chars = self._bounded_int_param(params.get("max_diff_chars"), default=60000, minimum=1, maximum=120000)
        include_log = self._bool_param(params.get("include_log"), default=True)
        log_limit = self._bounded_int_param(params.get("log_limit"), default=5, minimum=1, maximum=20)
        include_repo_overview = self._bool_param(params.get("include_repo_overview"), default=False)
        max_files = self._bounded_int_param(params.get("max_files"), default=200, minimum=1, maximum=500)

        partial_errors: list[dict[str, str]] = []
        review_hints: list[str] = []
        data: dict[str, Any] = {
            "project_identity": self._project_identity(),
            "git_status": None,
            "git_diff": None,
            "git_log": None,
            "repo_overview": None,
            "changed_files": [],
            "untracked_files": [],
            "is_dirty": None,
            "has_untracked_runtime": False,
            "runtime_untracked_files": [],
            "review_hints": review_hints,
            "partial_errors": partial_errors,
        }

        git_status_item = self._collect_context_item("git_status", self._tool_get_git_status, {}, partial_errors)
        data["git_status"] = git_status_item["result"]

        git_diff_item = self._collect_context_item(
            "git_diff",
            self._tool_get_git_diff,
            {"max_chars": max_diff_chars},
            partial_errors,
        )
        data["git_diff"] = git_diff_item["result"]

        git_log_result: dict[str, Any] | None = None
        if include_log:
            git_log_item = self._collect_context_item(
                "git_log",
                self._tool_get_git_log,
                {"limit": log_limit},
                partial_errors,
            )
            git_log_result = git_log_item["result"]
        data["git_log"] = git_log_result

        repo_overview_result: dict[str, Any] | None = None
        if include_repo_overview:
            repo_overview_item = self._collect_context_item(
                "repo_overview",
                self._tool_get_repo_overview,
                {"max_files": max_files, "max_depth": 3},
                partial_errors,
            )
            repo_overview_result = repo_overview_item["result"]
        data["repo_overview"] = repo_overview_result

        changed_files: list[str] = []
        untracked_files: list[str] = []
        status_payload = data["git_status"]
        if isinstance(status_payload, dict) and status_payload.get("ok"):
            changed_files = [str(item) for item in status_payload.get("changed_files", []) if isinstance(item, str)]
            untracked_files = [str(item) for item in status_payload.get("untracked_files", []) if isinstance(item, str)]
        data["changed_files"] = changed_files
        data["untracked_files"] = untracked_files
        data["is_dirty"] = bool(changed_files or untracked_files)

        runtime_untracked = [item for item in untracked_files if is_project_runner_path(item)]
        data["runtime_untracked_files"] = runtime_untracked
        data["has_untracked_runtime"] = bool(runtime_untracked)

        if data["is_dirty"] is False:
            review_hints.append("working_tree_clean")
        if runtime_untracked and len(runtime_untracked) == len(untracked_files):
            review_hints.append("only_local_runner_runtime_untracked")
        if changed_files:
            review_hints.append("review_git_diff_before_commit")
        non_runtime_untracked = [item for item in untracked_files if item not in runtime_untracked]
        if non_runtime_untracked:
            review_hints.append("untracked_non_runtime_files_require_attention")
        diff_payload = data["git_diff"]
        data["diff_truncated"] = False
        data["diff_summary_available"] = False
        data["recommended_next_action"] = None
        if isinstance(diff_payload, dict) and diff_payload.get("ok") and diff_payload.get("truncated"):
            data["diff_truncated"] = True
            data["diff_summary_available"] = True
            data["recommended_next_action"] = 'manage_git diff(mode="summary")'
            review_hints.append("diff_truncated_review_specific_files")

        return data

    def _tool_get_runner_workbench_context(self, params: dict[str, Any]) -> dict[str, Any]:
        include_runner_state = self._bool_param(params.get("include_runner_state"), default=True)
        include_executor = self._bool_param(params.get("include_executor"), default=True)
        include_git_status = self._bool_param(params.get("include_git_status"), default=True)

        provider_raw = params.get("provider")
        provider: str | None = None
        if provider_raw is not None:
            if not isinstance(provider_raw, str) or provider_raw.strip().lower() not in {"pi", "codex", "opencode"}:
                raise MCPToolInputError("INVALID_PROVIDER", "provider 必须是 pi、codex 或 opencode。")
            provider = provider_raw.strip().lower()

        partial_errors: list[dict[str, str]] = []
        context: dict[str, Any] = {
            "project_identity": self._project_identity(),
            "runner_status": None,
            "current_version_result": None,
            "next_version_plan": None,
            "plan_overview": None,
            "executor_session_status": None,
            "executor_continuation_preview": None,
            "executor_continuation_decision": None,
            "executor_resume_invocation_preview": None,
            "git_status": None,
            "summary": {},
            "partial_errors": partial_errors,
        }

        item_states: dict[str, bool] = {}

        if include_runner_state:
            runner_status_item = self._collect_context_item(
                "runner_status",
                self._tool_get_runner_status,
                {},
                partial_errors,
            )
            context["runner_status"] = runner_status_item["result"]
            item_states["runner_status"] = runner_status_item["ok"]

            version_result_item = self._collect_context_item(
                "current_version_result",
                self._tool_get_version_result,
                {},
                partial_errors,
            )
            context["current_version_result"] = version_result_item["result"]
            item_states["current_version_result"] = version_result_item["ok"]

            next_plan_item = self._collect_context_item(
                "next_version_plan",
                self._tool_get_next_version_plan,
                {},
                partial_errors,
            )
            context["next_version_plan"] = next_plan_item["result"]
            item_states["next_version_plan"] = next_plan_item["ok"]

            plan_overview_item = self._collect_context_item(
                "plan_overview",
                self._tool_get_plan_overview,
                {},
                partial_errors,
            )
            context["plan_overview"] = plan_overview_item["result"]
            item_states["plan_overview"] = plan_overview_item["ok"]

        if include_executor:
            session_item = self._collect_context_item(
                "executor_session_status",
                self._tool_get_executor_session_status,
                {},
                partial_errors,
            )
            context["executor_session_status"] = session_item["result"]
            item_states["executor_session_status"] = session_item["ok"]

            continuation_item = self._collect_context_item(
                "executor_continuation_preview",
                self._tool_get_executor_continuation_preview,
                {},
                partial_errors,
            )
            context["executor_continuation_preview"] = continuation_item["result"]
            item_states["executor_continuation_preview"] = continuation_item["ok"]

            if provider is not None:
                decision_item = self._collect_context_item(
                    "executor_continuation_decision",
                    self._tool_get_executor_continuation_decision,
                    {"provider": provider},
                    partial_errors,
                )
                context["executor_continuation_decision"] = decision_item["result"]
                item_states["executor_continuation_decision"] = decision_item["ok"]

                invocation_item = self._collect_context_item(
                    "executor_resume_invocation_preview",
                    self._tool_get_executor_resume_invocation_preview,
                    {"provider": provider},
                    partial_errors,
                )
                context["executor_resume_invocation_preview"] = invocation_item["result"]
                item_states["executor_resume_invocation_preview"] = invocation_item["ok"]

        if include_git_status:
            git_status_item = self._collect_context_item(
                "git_status",
                self._tool_get_git_status,
                {},
                partial_errors,
            )
            context["git_status"] = git_status_item["result"]
            item_states["git_status"] = git_status_item["ok"]

        working_tree_clean: bool | None = None
        if isinstance(context["git_status"], dict) and context["git_status"].get("ok"):
            changed_files = context["git_status"].get("changed_files", [])
            untracked_files = context["git_status"].get("untracked_files", [])
            if isinstance(changed_files, list) and isinstance(untracked_files, list):
                working_tree_clean = len(changed_files) == 0 and len(untracked_files) == 0

        has_executor_session = False
        session_payload = context.get("executor_session_status")
        if isinstance(session_payload, dict):
            has_executor_session = bool(session_payload.get("active")) or isinstance(session_payload.get("record"), dict)

        recommended_next_reads: list[str] = []
        if working_tree_clean is False:
            recommended_next_reads.append("manage_git review_context")
        if include_runner_state and not item_states.get("runner_status", False):
            recommended_next_reads.extend(["get_repo_overview", "get_source_file"])
        if include_runner_state and item_states.get("plan_overview", False) and not item_states.get("next_version_plan", False):
            recommended_next_reads.append("get_next_version_plan")

        plan_path = resolve_project_runner_path(self.project_root, "plan.json")
        state_path = resolve_project_runner_path(self.project_root, "state.json")
        has_plan_file = os.path.isfile(plan_path)
        has_state_file = os.path.isfile(state_path)
        mode = self._build_state_mode(has_plan_file, has_state_file)

        blockers: list[str] = []
        warnings: list[str] = []
        if mode == "plan_without_state":
            blockers.append("state_missing")
        elif mode == "state_without_plan":
            blockers.append("plan_missing")
        elif mode == "invalid_or_partial":
            blockers.append("runner_state_invalid")
        if working_tree_clean is False:
            warnings.append("working_tree_dirty")

        recommended_workflows: list[str] = []
        if mode == "source_only":
            recommended_workflows.extend([
                "analyze_project_state",
                "manage_runner_plan.inspect",
                "manage_runner_plan.bootstrap_preview",
            ])
        else:
            recommended_workflows.append("analyze_project_state")
        if working_tree_clean is False:
            recommended_workflows.extend([
                "manage_git review_context",
                "manage_git commit_readiness",
            ])

        context["summary"] = {
            "has_runner_state": bool(item_states.get("runner_status", False)),
            "has_plan": bool(item_states.get("plan_overview", False)),
            "has_executor_session": has_executor_session,
            "working_tree_clean": working_tree_clean,
            "recommended_next_reads": recommended_next_reads,
            "mode": mode,
            "blockers": blockers,
            "warnings": warnings,
            "recommended_workflows": recommended_workflows,
        }
        return context

    def _tool_analyze_project_state(self, params: dict[str, Any]) -> dict[str, Any]:
        project_root, project_record = self._resolve_read_only_project_context(params)
        routed_params = self._strip_project_name_param(params)
        include_repo_overview = self._bool_param(params.get("include_repo_overview"), default=False)
        include_reports = self._bool_param(params.get("include_reports"), default=True)
        max_files = self._bounded_int_param(params.get("max_files"), default=200, minimum=1, maximum=500)

        provider_raw = params.get("provider")
        provider: str | None = None
        if provider_raw is not None:
            if not isinstance(provider_raw, str) or provider_raw.strip().lower() not in {"pi", "codex", "opencode"}:
                raise MCPToolInputError("INVALID_PROVIDER", "provider 必须是 pi、codex 或 opencode。")
            provider = provider_raw.strip().lower()

        orchestrator = WorkflowOrchestrator(
            project_root=project_root,
            source_review=self.source_review,
            planning_bridge=self.bridge,
        )
        fact_snapshot = orchestrator.build_fact_snapshot(provider=provider, include_reports=include_reports)

        core_output = orchestrator._build_analyze_core_output(fact_snapshot)

        repo_overview = None
        partial_errors = list(fact_snapshot.partial_errors)
        if include_repo_overview:
            repo_item = self._collect_context_item(
                "repo_overview", self._tool_get_repo_overview,
                {"max_files": max_files, "max_depth": 3, **({"project_name": project_record.get("project_name")} if isinstance(project_record, dict) else {})}, partial_errors,
            )
            repo_overview = repo_item["result"]

        legacy = {
            "ok": True,
            "read_only": True,
            "side_effects": False,
            "project_identity": fact_snapshot.project_identity,
            "mcp_exposure_profile": self.mcp_exposure_profile,
            "visible_tool_count": len(self._visible_tool_names()),
            "visible_tool_names": self._visible_tool_names(),
            "mode": fact_snapshot.mode,
            "risk_level": core_output.risk_level,
            "git": core_output.result.get("git") if isinstance(core_output.result, dict) else {},
            "runner": core_output.result.get("runner") if isinstance(core_output.result, dict) else {},
            "plan": core_output.result.get("plan") if isinstance(core_output.result, dict) else {},
            "executor": core_output.result.get("executor") if isinstance(core_output.result, dict) else {},
            "reports": core_output.result.get("reports") if isinstance(core_output.result, dict) else {},
            "summary": fact_snapshot.summary,
            "recommended_next_actions": self._normalize_recommended_actions_for_visible_tools(
                self._with_maintainer_review_recommendation(list(core_output.next_actions))
            ),
            "repo_overview": repo_overview,
            "blockers": list(core_output.blockers),
            "warnings": list(core_output.warnings),
            "unreconciled_direct_version_count": fact_snapshot.unreconciled_direct_version_count,
            "unreconciled_direct_versions": fact_snapshot.unreconciled_direct_versions,
            "partial_errors": partial_errors,
        }

        if project_record is None:
            self._record_workflow_if_needed("analyze_project_state", "analyze", routed_params, legacy)
        return legacy

    def _tool_inspect_executor_activity(self, params: dict[str, Any]) -> dict[str, Any]:
        action_raw = params.get("action", "")
        if not isinstance(action_raw, str) or not action_raw.strip():
            return {
                "ok": False,
                "error_code": "ACTION_REQUIRED",
                "message": "action 不能为空。支持：run_status、latest_run_status、list_reports、get_report、get_audit_summary。",
            }
        action = action_raw.strip().lower()
        if action not in ("run_status", "latest_run_status", "list_reports", "get_report", "get_audit_summary"):
            return {
                "ok": False,
                "error_code": "UNKNOWN_ACTION",
                "message": "不支持的 action。支持：run_status、latest_run_status、list_reports、get_report、get_audit_summary。",
            }
        if params.get("project_name") is not None:
            return self._route_project_name_tool("inspect_executor_activity", params, require_managed=True)
        return handle_inspect_executor_activity(self.project_root, action, params)

    def _build_state_mode(self, has_plan: bool, has_state: bool) -> str:
        if not has_plan and not has_state:
            return "source_only"
        if has_plan and has_state:
            return "runner_managed"
        if has_plan and not has_state:
            return "plan_without_state"
        if not has_plan and has_state:
            return "state_without_plan"
        return "invalid_or_partial"


    def _with_maintainer_review_recommendation(self, actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if self.mcp_exposure_profile != MCP_EXPOSURE_PROFILE_MAINTAINER:
            return actions
        if any(isinstance(item, dict) and item.get("tool") == "manage_git" and item.get("params", {}).get("action") == "review_context" for item in actions):
            return actions
        return [
            *actions,
            {
                "action": "review_context",
                "label": "读取审查上下文",
                "reason": "maintainer profile 保留 manage_git review_context 审查入口。",
                "tool": "manage_git",
                "params": {"action": "review_context"},
                "risk_level": "none",
                "requires_confirmation": False,
            },
        ]

    def _normalize_recommended_actions_for_visible_tools(
        self,
        actions: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        visible_names = set(self._visible_tool_names())
        normalized: list[dict[str, Any]] = []
        seen: set[str] = set()

        for action in actions:
            if not isinstance(action, dict):
                continue
            candidate = dict(action)
            tool = str(candidate.get("tool") or "")
            if tool not in visible_names:
                candidate = self._replace_hidden_recommended_action(candidate, visible_names)
            if not isinstance(candidate, dict):
                continue
            candidate_tool = str(candidate.get("tool") or "")
            if candidate_tool not in visible_names:
                if "analyze_project_state" not in visible_names:
                    continue
                candidate = self._fallback_analyze_action()
                candidate_tool = "analyze_project_state"
            key = self._recommended_action_key(candidate)
            if key in seen:
                continue
            seen.add(key)
            normalized.append(candidate)

        if not normalized and "analyze_project_state" in visible_names:
            normalized.append(self._fallback_analyze_action())
        return normalized

    def _replace_hidden_recommended_action(
        self,
        action: dict[str, Any],
        visible_names: set[str],
    ) -> dict[str, Any]:
        tool = str(action.get("tool") or "")
        if tool == "manage_runner_plan":
            if "run_mcp_workflow" in visible_names:
                return {
                    "action": "source_onboarding",
                    "label": "生成纳管预览",
                    "reason": "当前 profile 仅展示高层入口，使用 run_mcp_workflow source_onboarding preview。",
                    "tool": "run_mcp_workflow",
                    "params": {"workflow": "source_onboarding", "phase": "preview"},
                    "risk_level": "info",
                    "requires_confirmation": True,
                }
            return self._fallback_analyze_action()

        if tool in {"get_review_context", "get_git_status", "get_git_diff"}:
            if "manage_git" in visible_names:
                return {
                    "action": "status",
                    "label": "检查 Git 状态",
                    "reason": "当前 profile 仅展示高层入口，使用 manage_git status。",
                    "tool": "manage_git",
                    "params": {"action": "status"},
                    "risk_level": "info",
                    "requires_confirmation": False,
                }
            if "manage_git_commit" in visible_names:
                return {
                    "action": "commit_readiness",
                    "label": "检查提交准备状态",
                    "reason": "当前 profile 仅展示高层入口，使用 manage_git_commit readiness。",
                    "tool": "manage_git_commit",
                    "params": {"action": "readiness"},
                    "risk_level": "info",
                    "requires_confirmation": False,
                }
            if "run_mcp_workflow" in visible_names:
                return {
                    "action": "git_commit_inspect",
                    "label": "审查并提交改动",
                    "reason": "当前 profile 仅展示高层入口，使用 run_mcp_workflow git_commit inspect。",
                    "tool": "run_mcp_workflow",
                    "params": {"workflow": "git_commit", "phase": "inspect"},
                    "risk_level": "info",
                    "requires_confirmation": False,
                }
            return self._fallback_analyze_action()

        if tool in {"list_executor_run_reports", "get_executor_run_report", "get_executor_session_status"}:
            if "manage_executor_workflow" in visible_names:
                return {
                    "action": "executor_status",
                    "label": "查看执行器会话状态",
                    "reason": "当前 profile 仅展示高层入口，使用 manage_executor_workflow status。",
                    "tool": "manage_executor_workflow",
                    "params": {"action": "status"},
                    "risk_level": "info",
                    "requires_confirmation": False,
                }
            return self._fallback_analyze_action()

        if tool == "none":
            return self._fallback_analyze_action()

        return self._fallback_analyze_action()

    def _recommended_action_key(self, action: dict[str, Any]) -> str:
        tool = str(action.get("tool") or "")
        action_name = str(action.get("action") or "")
        params = action.get("params", {})
        try:
            params_key = json.dumps(params, ensure_ascii=False, sort_keys=True)
        except Exception:
            params_key = str(params)
        return f"{tool}|{action_name}|{params_key}"

    def _fallback_analyze_action(self) -> dict[str, Any]:
        return {
            "action": "refresh_project_state",
            "label": "刷新项目状态",
            "reason": "使用 analyze_project_state 获取当前可见范围内的下一步建议。",
            "tool": "analyze_project_state",
            "params": {},
            "risk_level": "none",
            "requires_confirmation": False,
        }

    def _append_context_error(self, name: str, message: str, partial_errors: list[dict[str, str]]) -> None:
        partial_errors.append({
            "name": name,
            "error_code": "CONTEXT_ERROR",
            "message": str(message),
        })

    def _tool_manage_plan_workflow(self, params: dict[str, Any]) -> dict[str, Any]:
        action_raw = params.get("action")
        action = action_raw.strip().lower() if isinstance(action_raw, str) else ""
        if action not in {"source_onboarding_preview", "plan_repair_preview", "plan_extend_preview"}:
            raise MCPToolInputError("INVALID_ACTION", "action 必须是 source_onboarding_preview、plan_repair_preview 或 plan_extend_preview。")

        if params.get("project_name") is not None:
            if action not in {"plan_repair_preview", "plan_extend_preview"}:
                raise MCPToolInputError(
                    "PROJECT_NAME_ROUTING_NOT_SUPPORTED",
                    "project_name 路由当前仅支持 manage_plan_workflow 的 managed preview：plan_repair_preview、plan_extend_preview。",
                )
            return self._route_project_name_tool("manage_plan_workflow", params, require_managed=True)

        manager = MCPPlanWorkflowManager(self.project_root, self.source_review)
        result = manager.handle(action, params)
        self._record_workflow_if_needed("manage_plan_workflow", action, params, result)
        if isinstance(result, dict):
            result["_legacy_warning"] = "manage_plan_workflow 已弃用。新流程请使用 manage_runner_plan（source-only 纳管）或 manage_plan_version（版本管理）。"
            result.setdefault("warnings", []).append("manage_plan_workflow 已弃用，请使用 manage_runner_plan 或 manage_plan_version。")
        return result

    def _tool_manage_project_docs(self, params: dict[str, Any]) -> dict[str, Any]:
        if params.get("project_name") is not None:
            return self._route_project_name_tool("manage_project_docs", params, require_managed=True)
        action_raw = params.get("action")
        action = action_raw.strip().lower() if isinstance(action_raw, str) else ""
        if action not in {"index", "search", "read_section", "update_section_preview", "append_section_preview", "sync_docs_preview", "apply"}:
            raise MCPToolInputError("INVALID_ACTION", "action 必须是 index、search、read_section、update_section_preview、append_section_preview、sync_docs_preview 或 apply。")

        manager = MCPProjectDocsManager(self.project_root, self.source_review)
        result = manager.handle(action, params)
        self._record_workflow_if_needed("manage_project_docs", action, params, result)
        return result

    def _tool_manage_prompt_file(self, params: dict[str, Any]) -> dict[str, Any]:
        from runner.mcp_prompt_file import MCPPromptFileManager
        action_raw = params.get("action")
        action = action_raw.strip().lower() if isinstance(action_raw, str) else ""
        if action not in {"preview", "apply", "status", "discard"}:
            raise MCPToolInputError("INVALID_ACTION", "action 必须是 preview、apply、status 或 discard。")

        if params.get("project_name") is not None:
            return self._route_project_name_tool("manage_prompt_file", params, require_managed=True)

        manager = MCPPromptFileManager(self.project_root)
        result = manager.handle(action, params)
        self._record_workflow_if_needed("manage_prompt_file", action, params, result)
        return result

    def _tool_manage_git(self, params: dict[str, Any]) -> dict[str, Any]:
        action_raw = params.get("action")
        action = action_raw.strip().lower() if isinstance(action_raw, str) else ""
        all_actions = {
            "status", "diff", "review_context",
            "commit_readiness", "commit_message", "commit_preview", "commit_apply",
            "push_status", "push_preview", "push_apply",
            "pull_status", "pull_preview", "pull_apply",
            "history_log", "history_show", "diff_commits",
            "restore_file_preview", "restore_file_apply",
            "revert_preview", "revert_apply",
        }
        if action not in all_actions:
            return {
                "ok": False,
                "error_code": "UNSUPPORTED_ACTION",
                "message": f"manage_git action '{action}' 暂无安全的路由目标，不自行创建新行为。",
                "action": action,
            }

        def _with_common_fields(result: dict[str, Any], delegated_tool: str) -> dict[str, Any]:
            if isinstance(result, dict):
                result["delegated_tool"] = delegated_tool
                result["action"] = action
            return result

        record_and_return = lambda result, tool: (self._record_workflow_if_needed("manage_git", action, params, result), _with_common_fields(result, tool))[1]

        # --- status: delegates to get_git_status ---
        if action == "status":
            status_params = {}
            if params.get("project_name") is not None:
                status_params["project_name"] = params["project_name"]
                return self._route_project_name_tool("manage_git", params, require_managed=True)
            result = self._tool_get_git_status(status_params)
            return record_and_return(result, "get_git_status")

        # --- diff: delegates to get_git_diff ---
        if action == "diff":
            diff_params: dict[str, Any] = {}
            for key in ("mode", "file", "include_files", "offset", "max_chars", "cached", "project_name"):
                if key in params:
                    diff_params[key] = params[key]
            if diff_params.get("project_name") is not None:
                return self._route_project_name_tool("manage_git", params, require_managed=True)
            result = self._tool_get_git_diff(diff_params)
            return record_and_return(result, "get_git_diff")

        # --- review_context: delegates to get_review_context ---
        if action == "review_context":
            ctx_params: dict[str, Any] = {}
            for key in ("max_diff_chars", "include_log", "log_limit", "include_repo_overview", "max_files", "project_name"):
                if key in params:
                    ctx_params[key] = params[key]
            if ctx_params.get("project_name") is not None:
                return self._route_project_name_tool("manage_git", params, require_managed=True)
            result = self._tool_get_review_context(ctx_params)
            return record_and_return(result, "get_review_context")

        # --- commit_readiness -> manage_git_commit readiness ---
        if action == "commit_readiness":
            delegate_params: dict[str, Any] = {"action": "readiness"}
            for key in ("include_diff_summary", "max_diff_chars", "include_files", "exclude_files", "project_name"):
                if key in params:
                    delegate_params[key] = params[key]
            result = self._delegate_manage_git_commit(delegate_params, record=False)
            return record_and_return(result, "manage_git_commit")

        # --- commit_message -> manage_git_commit suggest_commit_message ---
        if action == "commit_message":
            delegate_params = {"action": "suggest_commit_message"}
            for key in ("include_diff_summary", "max_diff_chars", "style", "scope_hint", "include_files", "exclude_files", "project_name"):
                if key in params:
                    delegate_params[key] = params[key]
            result = self._delegate_manage_git_commit(delegate_params, record=False)
            return record_and_return(result, "manage_git_commit")

        # --- commit_preview -> manage_git_commit preview ---
        if action == "commit_preview":
            message = params.get("message")
            if not isinstance(message, str) or not message.strip():
                raise MCPToolInputError("INVALID_MESSAGE", "commit_preview 需要非空 message。")
            delegate_params = {"action": "preview", "message": message.strip()}
            for key in ("include_diff_summary", "max_diff_chars", "include_files", "exclude_files", "project_name"):
                if key in params:
                    delegate_params[key] = params[key]
            result = self._delegate_manage_git_commit(delegate_params, record=False)
            return record_and_return(result, "manage_git_commit")

        # --- commit_apply -> manage_git_commit commit ---
        if action == "commit_apply":
            preview_id = params.get("preview_id")
            if not isinstance(preview_id, str) or not preview_id.strip():
                raise MCPToolInputError("INVALID_PREVIEW_ID", "commit_apply 需要非空 preview_id。")
            delegate_params = {"action": "commit", "preview_id": preview_id.strip()}
            msg = params.get("message")
            if isinstance(msg, str) and msg.strip():
                delegate_params["message"] = msg.strip()
            if params.get("project_name") is not None:
                delegate_params["project_name"] = params["project_name"]
            result = self._delegate_manage_git_commit(delegate_params, record=False)
            return record_and_return(result, "manage_git_commit")

        # --- push/pull actions -> manage_git_remote ---
        if action in ("push_status", "push_preview", "push_apply"):
            result = self._delegate_manage_git_remote(action, params, record=False)
            return record_and_return(result, "manage_git_remote")
        if action in ("pull_status", "pull_preview", "pull_apply"):
            result = self._delegate_manage_git_remote(action, params, record=False)
            return record_and_return(result, "manage_git_remote")

        # --- history actions -> manage_git_history ---
        if action in ("history_log", "history_show", "diff_commits",
                      "restore_file_preview", "restore_file_apply",
                      "revert_preview", "revert_apply"):
            mapped = {
                "history_log": "log",
                "history_show": "show",
                "diff_commits": "diff_commits",
                "restore_file_preview": "restore_file_preview",
                "restore_file_apply": "restore_file_apply",
                "revert_preview": "revert_preview",
                "revert_apply": "revert_apply",
            }
            history_action = mapped[action]
            history_params: dict[str, Any] = {"action": history_action}
            for key in ("commit", "base", "head", "file", "preview_id", "limit", "max_chars", "include_patch", "reason", "scan_limit", "project_name"):
                if key in params:
                    history_params[key] = params[key]
            if history_params.get("project_name") is not None:
                return self._route_project_name_tool("manage_git", params, require_managed=True)
            manager = MCPGitHistoryManager(self.project_root, self.source_review)
            result = manager.handle(history_action, history_params)
            return record_and_return(result, "manage_git_history")

        return {
            "ok": False,
            "error_code": "UNSUPPORTED_ACTION",
            "message": f"manage_git action '{action}' 暂无安全的路由目标，不自行创建新行为。",
            "action": action,
        }

    def _delegate_manage_git_commit(self, delegate_params: dict[str, Any], *, record: bool = True) -> dict[str, Any]:
        project_name = delegate_params.get("project_name")
        if project_name is not None:
            return self._route_project_name_tool("manage_git_commit", delegate_params, require_managed=True)
        action = delegate_params.get("action", "")
        manager = MCPGitCommitManager(self.project_root)

        if action == "readiness":
            result = manager.readiness(
                include_diff_summary=delegate_params.get("include_diff_summary", True),
                max_diff_chars=delegate_params.get("max_diff_chars", 40000),
                include_files=delegate_params.get("include_files"),
                exclude_files=delegate_params.get("exclude_files"),
            )
        elif action == "suggest_commit_message":
            result = manager.suggest_commit_message(
                include_diff_summary=delegate_params.get("include_diff_summary", True),
                max_diff_chars=delegate_params.get("max_diff_chars", 40000),
                style=delegate_params.get("style", "runner_version"),
                scope_hint=delegate_params.get("scope_hint"),
                include_files=delegate_params.get("include_files"),
                exclude_files=delegate_params.get("exclude_files"),
            )
        elif action == "preview":
            message = delegate_params.get("message", "")
            result = manager.preview(
                message=message.strip(),
                include_diff_summary=delegate_params.get("include_diff_summary", True),
                max_diff_chars=delegate_params.get("max_diff_chars", 40000),
                include_files=delegate_params.get("include_files"),
                exclude_files=delegate_params.get("exclude_files"),
            )
        elif action == "commit":
            result = manager.commit(
                preview_id=delegate_params.get("preview_id", "").strip(),
                message=delegate_params.get("message"),
            )
        else:
            return {"ok": False, "error_code": "INVALID_ACTION", "message": f"未知 manage_git_commit action：{action}"}

        if record:
            self._record_workflow_if_needed("manage_git_commit", action, delegate_params, result)
        return result

    def _delegate_manage_git_remote(self, action: str, params: dict[str, Any], *, record: bool = True) -> dict[str, Any]:
        if params.get("project_name") is not None:
            return self._route_project_name_tool("manage_git_remote", params, require_managed=True)
        manager = MCPGitRemoteManager(self.project_root)
        if action == "push_status":
            result = manager.push_status()
        elif action == "push_preview":
            reason = params.get("reason")
            reason_str = reason.strip() if isinstance(reason, str) else None
            result = manager.push_preview(reason=reason_str)
        elif action == "push_apply":
            preview_id = params.get("preview_id")
            if not isinstance(preview_id, str) or not preview_id.strip():
                return {"ok": False, "error_code": "INVALID_PREVIEW_ID", "message": "push_apply 需要非空 preview_id。"}
            result = manager.push_apply(preview_id.strip())
        elif action == "pull_status":
            result = manager.pull_status()
        elif action == "pull_preview":
            reason = params.get("reason")
            reason_str = reason.strip() if isinstance(reason, str) else None
            result = manager.pull_preview(reason=reason_str)
        elif action == "pull_apply":
            preview_id = params.get("preview_id")
            if not isinstance(preview_id, str) or not preview_id.strip():
                return {"ok": False, "error_code": "INVALID_PREVIEW_ID", "message": "pull_apply 需要非空 preview_id。"}
            result = manager.pull_apply(preview_id.strip())
        else:
            return {"ok": False, "error_code": "INVALID_ACTION", "message": f"未知 manage_git_remote action：{action}"}
        if record:
            self._record_workflow_if_needed("manage_git_remote", action, params, result)
        return result

    def _tool_manage_git_commit(self, params: dict[str, Any]) -> dict[str, Any]:
        action_raw = params.get("action")
        action = action_raw.strip().lower() if isinstance(action_raw, str) else ""
        if action not in {"readiness", "suggest_commit_message", "commit_workflow_preview", "preview", "commit"}:
            raise MCPToolInputError("INVALID_ACTION", "action 必须是 readiness、suggest_commit_message、commit_workflow_preview、preview 或 commit。")

        if params.get("project_name") is not None:
            return self._route_project_name_tool("manage_git_commit", params, require_managed=True)

        include_diff_summary = self._bool_param(params.get("include_diff_summary"), default=True)
        max_diff_chars = self._bounded_int_param(
            params.get("max_diff_chars"),
            default=40000,
            minimum=1,
            maximum=80000,
        )
        style = params.get("style")
        if not isinstance(style, str) or style not in {"conventional", "runner_version", "concise"}:
            style = "runner_version"
        scope_hint = params.get("scope_hint")
        if not isinstance(scope_hint, str) or not scope_hint.strip():
            scope_hint = None
        include_files = params.get("include_files")
        exclude_files = params.get("exclude_files")

        manager = MCPGitCommitManager(self.project_root)

        if action == "readiness":
            return manager.readiness(
                include_diff_summary=include_diff_summary,
                max_diff_chars=max_diff_chars,
                include_files=include_files,
                exclude_files=exclude_files,
            )

        if action == "suggest_commit_message":
            result = manager.suggest_commit_message(
                include_diff_summary=include_diff_summary,
                max_diff_chars=max_diff_chars,
                style=style,
                scope_hint=scope_hint,
                include_files=include_files,
                exclude_files=exclude_files,
            )
            self._record_workflow_if_needed("manage_git_commit", action, params, result)
            return result

        if action == "commit_workflow_preview":
            message = params.get("message")
            if message is not None:
                if not isinstance(message, str) or not message.strip():
                    raise MCPToolInputError("INVALID_MESSAGE", "message 必须是非空字符串。")
                if len(message.strip()) > 200:
                    raise MCPToolInputError("INVALID_MESSAGE", "message 长度不能超过 200。")
            result = manager.commit_workflow_preview(
                message=message.strip() if isinstance(message, str) else None,
                include_diff_summary=include_diff_summary,
                max_diff_chars=max_diff_chars,
                style=style,
                scope_hint=scope_hint,
                include_files=include_files,
                exclude_files=exclude_files,
            )
            self._record_workflow_if_needed("manage_git_commit", action, params, result)
            return result

        if action == "preview":
            message = params.get("message")
            if not isinstance(message, str) or not message.strip():
                raise MCPToolInputError("INVALID_MESSAGE", "preview 操作需要非空 message。")
            normalized_message = message.strip()
            if len(normalized_message) > 200:
                raise MCPToolInputError("INVALID_MESSAGE", "message 长度不能超过 200。")
            result = manager.preview(
                message=normalized_message,
                include_diff_summary=include_diff_summary,
                max_diff_chars=max_diff_chars,
                include_files=include_files,
                exclude_files=exclude_files,
            )
            self._record_workflow_if_needed("manage_git_commit", action, params, result)
            return result

        if include_files is not None or exclude_files is not None:
            raise MCPToolInputError(
                "INVALID_FILE_SELECTION",
                "commit 操作不接受 include_files 或 exclude_files，请使用 preview 中保存的文件集合。",
            )
        preview_id = params.get("preview_id")
        if not isinstance(preview_id, str) or not preview_id.strip():
            raise MCPToolInputError("INVALID_PREVIEW_ID", "commit 操作需要 preview_id。")
        message = params.get("message")
        if message is not None:
            if not isinstance(message, str) or not message.strip():
                raise MCPToolInputError("INVALID_MESSAGE", "message 必须是非空字符串。")
            normalized_message = message.strip()
            if len(normalized_message) > 200:
                raise MCPToolInputError("INVALID_MESSAGE", "message 长度不能超过 200。")
        else:
            normalized_message = None
        result = manager.commit(preview_id=preview_id.strip(), message=normalized_message)
        self._record_workflow_if_needed("manage_git_commit", action, params, result)
        return result

    def _tool_manage_git_remote(self, params: dict[str, Any]) -> dict[str, Any]:
        action_raw = params.get("action")
        action = action_raw.strip().lower() if isinstance(action_raw, str) else ""
        allowed_actions = {
            "push_status",
            "push_preview",
            "push_apply",
            "fetch_preview",
            "fetch_apply",
            "pull_status",
            "pull_preview",
            "pull_apply",
        }
        if action not in allowed_actions:
            raise MCPToolInputError("INVALID_ACTION", "action 必须是 manage_git_remote 支持的受控 action。")

        if params.get("project_name") is not None:
            if action not in {"push_status", "push_preview", "push_apply"}:
                raise MCPToolInputError(
                    "PROJECT_NAME_ROUTING_NOT_SUPPORTED",
                    "project_name 路由当前仅支持 manage_git_remote 的 push_status、push_preview、push_apply。",
                )
            return self._route_project_name_tool("manage_git_remote", params, require_managed=True)

        manager = MCPGitRemoteManager(self.project_root)
        if action == "push_status":
            result = manager.push_status()
            self._record_workflow_if_needed("manage_git_remote", action, params, result)
            return result
        if action == "push_preview":
            reason = params.get("reason")
            if reason is not None and (not isinstance(reason, str) or not reason.strip()):
                raise MCPToolInputError("INVALID_REASON", "reason 必须是非空字符串。")
            result = manager.push_preview(reason=reason.strip() if isinstance(reason, str) else None)
            self._record_workflow_if_needed("manage_git_remote", action, params, result)
            return result
        if action == "fetch_preview":
            reason = params.get("reason")
            if reason is not None and (not isinstance(reason, str) or not reason.strip()):
                raise MCPToolInputError("INVALID_REASON", "reason 必须是非空字符串。")
            result = manager.fetch_preview(reason=reason.strip() if isinstance(reason, str) else None)
            self._record_workflow_if_needed("manage_git_remote", action, params, result)
            return result
        if action == "pull_status":
            result = manager.pull_status()
            self._record_workflow_if_needed("manage_git_remote", action, params, result)
            return result
        if action == "pull_preview":
            reason = params.get("reason")
            if reason is not None and (not isinstance(reason, str) or not reason.strip()):
                raise MCPToolInputError("INVALID_REASON", "reason 必须是非空字符串。")
            result = manager.pull_preview(reason=reason.strip() if isinstance(reason, str) else None)
            self._record_workflow_if_needed("manage_git_remote", action, params, result)
            return result
        preview_id = params.get("preview_id")
        if not isinstance(preview_id, str) or not preview_id.strip():
            raise MCPToolInputError("INVALID_PREVIEW_ID", f"{action} 需要 preview_id。")
        if action == "push_apply":
            result = manager.push_apply(preview_id.strip())
        elif action == "fetch_apply":
            result = manager.fetch_apply(preview_id.strip())
        else:
            result = manager.pull_apply(preview_id.strip())
        self._record_workflow_if_needed("manage_git_remote", action, params, result)
        return result

    def _tool_manage_runner_plan(self, params: dict[str, Any]) -> dict[str, Any]:
        action_raw = params.get("action")
        action = action_raw.strip().lower() if isinstance(action_raw, str) else ""
        if action not in {"inspect", "bootstrap_preview", "import_preview", "apply"}:
            raise MCPToolInputError("INVALID_ACTION", "action 必须是 inspect、bootstrap_preview、import_preview 或 apply。")

        manager = MCPRunnerPlanManager(self.project_root)

        if action == "inspect":
            return manager.inspect()

        if action == "bootstrap_preview":
            project_name = params.get("project_name")
            if not isinstance(project_name, str) or not project_name.strip():
                raise MCPToolInputError("INVALID_PROJECT_NAME", "bootstrap_preview 需要非空 project_name。")
            return manager.bootstrap_preview(
                project_name=project_name.strip(),
            )

        if action == "import_preview":
            plan_json = params.get("plan_json")
            if not isinstance(plan_json, str) or not plan_json.strip():
                raise MCPToolInputError("INVALID_PLAN_JSON", "import_preview 需要非空 plan_json 字符串。")
            return manager.import_preview(plan_json=plan_json)

        preview_id = params.get("preview_id")
        if not isinstance(preview_id, str) or not preview_id.strip():
            raise MCPToolInputError("INVALID_PREVIEW_ID", "apply 操作需要 preview_id。")
        allow_overwrite = self._bool_param(params.get("allow_overwrite"), default=False)
        result = manager.apply(preview_id=preview_id.strip(), allow_overwrite=allow_overwrite)
        if isinstance(result, dict) and result.get("ok"):
            version_count = int(result.get("plan_summary", {}).get("version_count", 0))
            next_actions = [
                {
                    "tool": "run_mcp_workflow",
                    "action": "project_status.inspect",
                    "params": {"workflow": "project_status", "phase": "inspect"},
                    "reason": "先读取纳管后的统一项目状态与当前版本。",
                    "requires_confirmation": False,
                },
            ]
            if version_count <= 0:
                next_actions.append({
                    "tool": "manage_prompt_file",
                    "action": "manage_prompt_file.preview",
                    "params": {"action": "preview"},
                    "reason": "纳管完成（空版本）。先保存开发 prompt 文件，再通过 manage_plan_version insert_from_prompt_file_preview 插入第一个开发版本。",
                    "requires_confirmation": True,
                })
                next_actions.append({
                    "tool": "manage_plan_version",
                    "action": "insert_from_prompt_file_preview",
                    "params": {"action": "insert_from_prompt_file_preview"},
                    "reason": "从 prompt 文件插入第一个开发版本预览。",
                    "requires_confirmation": True,
                })
            else:
                next_actions.append({
                    "tool": "manage_executor_workflow",
                    "action": "run_once_preview",
                    "params": {"action": "run_once_preview", "provider": "codex", "execution_mode": "run"},
                    "reason": "生成当前版本的执行器运行预览。",
                    "requires_confirmation": True,
                })
                next_actions.append({
                    "tool": "manage_executor_workflow",
                    "action": "run_once",
                    "params": {
                        "action": "run_once",
                        "provider": "codex",
                        "execution_mode": "run",
                        "preview_id": "<from_run_once_preview.preview_id>",
                    },
                    "reason": "用 run_once_preview 返回的 preview_id 启动异步执行。",
                    "requires_confirmation": True,
                })
                next_actions.append({
                    "tool": "manage_executor_workflow",
                    "action": "status",
                    "params": {
                        "action": "status",
                        "preview_id": "<from_run_once_preview.preview_id>",
                    },
                    "reason": "run_once 返回 started/running 后，用 status 轮询终态。",
                    "requires_confirmation": False,
                })
                next_actions.append({
                    "tool": "get_executor_run_report",
                    "action": "latest_report",
                    "params": {"latest": True, "include_markdown": False},
                    "reason": "status 到 completed 后读取最新执行报告。",
                    "requires_confirmation": False,
                })
            result["next_actions"] = next_actions
            if version_count <= 0:
                result["next_action_hint"] = "纳管完成（空版本）。先保存 prompt 文件，再通过 manage_plan_version insert_from_prompt_file_preview 插入第一个开发版本。"
            else:
                result["next_action_hint"] = "按 run_once_preview -> run_once -> status -> get_executor_run_report 链路继续。"
        return result

    def _tool_todo_read(self, params: dict[str, Any]) -> dict[str, Any]:
        if params.get("project_name") is not None:
            return self._route_project_name_tool("todo_read", params, require_managed=True)
        manager = MCPTodoListManager(self.project_root)
        include_done = self._bool_param(params.get("include_done"), default=False)
        result = manager.read(include_done=include_done)
        if not self._bool_param(params.get("__skip_workflow_record"), default=False):
            self._record_workflow_if_needed("todo_read", "todo_read", params, result)
        return result

    def _tool_manage_runner_record(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._tool_manage_project_memory_impl("manage_runner_record", params)

    def _tool_manage_project_memory(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._tool_manage_project_memory_impl("manage_project_memory", params)

    def _tool_manage_project_memory_impl(self, workflow_tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
        raw_record_type = params.get("record_type")
        raw_action = params.get("action")
        if not isinstance(raw_record_type, str) or not raw_record_type.strip():
            raise MCPToolInputError("INVALID_RECORD_TYPE", "record_type 必须是 memory、todo 或 decision。")
        if not isinstance(raw_action, str) or not raw_action.strip():
            raise MCPToolInputError("INVALID_RECORD_ACTION", "action 必须是 read、add、update 或 delete。")
        if params.get("project_name") is not None:
            return self._route_project_name_tool(workflow_tool_name, params, require_managed=True)
        record_type = raw_record_type.strip().lower()
        action = raw_action.strip().lower()
        tool_name = self._runner_record_tool_name(record_type, action)
        delegate_params = self._runner_record_delegate_params(record_type, action, params)
        delegate_params["__skip_workflow_record"] = True
        if tool_name.startswith("memory_"):
            result = self._tool_manage_runner_record_memory_delegate(action, delegate_params)
        elif tool_name.startswith("todo_"):
            result = self._tool_manage_runner_record_todo_delegate(tool_name, delegate_params)
        else:
            result = self._tool_manage_runner_record_decision_delegate(tool_name, delegate_params)
        self._record_workflow_if_needed(workflow_tool_name, action, params, result)
        return result

    def _runner_record_tool_name(self, record_type: str, action: str) -> str:
        if record_type not in {"memory", "todo", "decision"}:
            raise MCPToolInputError("INVALID_RECORD_TYPE", "record_type 只能是 memory、todo 或 decision。")
        if action not in {"read", "add", "update", "delete"}:
            raise MCPToolInputError("INVALID_RECORD_ACTION", "action 只能是 read、add、update 或 delete。")
        return f"{record_type}_{action}"

    def _runner_record_delegate_params(self, record_type: str, action: str, params: dict[str, Any]) -> dict[str, Any]:
        allowed_keys_by_type = {
            "memory": {"project_name", "content", "max_chars"},
            "todo": {"project_name", "include_done", "id", "content", "status"},
            "decision": {"project_name", "id", "status", "title", "decision", "reason", "related_versions"},
        }
        delegate: dict[str, Any] = {}
        for key in allowed_keys_by_type[record_type]:
            if key in params:
                delegate[key] = params.get(key)
        if record_type in {"todo", "decision"} and action in {"update", "delete"}:
            if "id" not in delegate:
                raise MCPToolInputError("INVALID_ID", "update/delete 操作需要 id。")
        return delegate

    def _tool_manage_runner_record_memory_delegate(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        manager = MCPProjectMemoryManager(self.project_root)
        if action == "read":
            return manager.read(max_chars=params.get("max_chars"))
        if action == "add":
            return manager.add(params.get("content"))
        if action == "update":
            return manager.update(params.get("content"))
        return manager.delete()

    def _tool_manage_runner_record_todo_delegate(self, tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
        if tool_name == "todo_read":
            return self._tool_todo_read(params)
        if tool_name == "todo_add":
            return self._tool_todo_add(params)
        if tool_name == "todo_update":
            return self._tool_todo_update(params)
        return self._tool_todo_delete(params)

    def _tool_manage_runner_record_decision_delegate(self, tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
        if tool_name == "decision_read":
            return self._tool_decision_read(params)
        if tool_name == "decision_add":
            return self._tool_decision_add(params)
        if tool_name == "decision_update":
            return self._tool_decision_update(params)
        return self._tool_decision_delete(params)

    def _tool_manage_workflow_run(self, params: dict[str, Any]) -> dict[str, Any]:
        raw_action = params.get("action")
        if not isinstance(raw_action, str) or not raw_action.strip():
            raise MCPToolInputError("INVALID_WORKFLOW_ACTION", "action 必须是 list 或 get。")
        action = raw_action.strip().lower()
        if action == "list":
            return self._tool_list_workflow_runs(self._workflow_run_delegate_params(action, params))
        if action == "get":
            return self._tool_get_workflow_run(self._workflow_run_delegate_params(action, params))
        raise MCPToolInputError("INVALID_WORKFLOW_ACTION", "action 只能是 list 或 get。")

    def _workflow_run_delegate_params(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        allowed_keys_by_action = {
            "list": {"project_name", "limit", "workflow_name", "status"},
            "get": {"project_name", "workflow_id"},
        }
        delegate: dict[str, Any] = {}
        for key in allowed_keys_by_action[action]:
            if key in params:
                delegate[key] = params.get(key)
        if action == "get" and "workflow_id" not in delegate:
            raise MCPToolInputError("INVALID_WORKFLOW_ID", "action=get 需要 workflow_id。")
        return delegate

    def _tool_todo_add(self, params: dict[str, Any]) -> dict[str, Any]:
        if params.get("project_name") is not None:
            return self._route_project_name_tool("todo_add", params, require_managed=True)
        manager = MCPTodoListManager(self.project_root)
        result = manager.add(params.get("content"), params.get("status"))
        if not self._bool_param(params.get("__skip_workflow_record"), default=False):
            self._record_workflow_if_needed("todo_add", "todo_add", params, result)
        return result

    def _tool_todo_update(self, params: dict[str, Any]) -> dict[str, Any]:
        if params.get("project_name") is not None:
            return self._route_project_name_tool("todo_update", params, require_managed=True)
        manager = MCPTodoListManager(self.project_root)
        result = manager.update(
            params.get("id"),
            params.get("content") if "content" in params else None,
            params.get("status") if "status" in params else None,
        )
        if not self._bool_param(params.get("__skip_workflow_record"), default=False):
            self._record_workflow_if_needed("todo_update", "update", params, result)
        return result

    def _tool_todo_delete(self, params: dict[str, Any]) -> dict[str, Any]:
        if params.get("project_name") is not None:
            return self._route_project_name_tool("todo_delete", params, require_managed=True)
        manager = MCPTodoListManager(self.project_root)
        result = manager.delete(params.get("id"))
        if not self._bool_param(params.get("__skip_workflow_record"), default=False):
            self._record_workflow_if_needed("todo_delete", "todo_delete", params, result)
        return result

    def _tool_decision_read(self, params: dict[str, Any]) -> dict[str, Any]:
        if params.get("project_name") is not None:
            return self._route_project_name_tool("decision_read", params, require_managed=True)
        manager = MCPDecisionRecordsManager(self.project_root)
        result = manager.read()
        if not self._bool_param(params.get("__skip_workflow_record"), default=False):
            self._record_workflow_if_needed("decision_read", "decision_read", params, result)
        return result

    def _tool_decision_add(self, params: dict[str, Any]) -> dict[str, Any]:
        if params.get("project_name") is not None:
            return self._route_project_name_tool("decision_add", params, require_managed=True)
        manager = MCPDecisionRecordsManager(self.project_root)
        result = manager.add(
            params.get("title"),
            params.get("decision"),
            params.get("reason"),
            params.get("related_versions"),
            params.get("status"),
        )
        if not self._bool_param(params.get("__skip_workflow_record"), default=False):
            self._record_workflow_if_needed("decision_add", "decision_add", params, result)
        return result

    def _tool_decision_update(self, params: dict[str, Any]) -> dict[str, Any]:
        if params.get("project_name") is not None:
            return self._route_project_name_tool("decision_update", params, require_managed=True)
        manager = MCPDecisionRecordsManager(self.project_root)
        changes: dict[str, Any] = {}
        for key in ("title", "decision", "reason", "related_versions", "status"):
            if key in params:
                changes[key] = params.get(key)
        result = manager.update(params.get("id"), **changes)
        if not self._bool_param(params.get("__skip_workflow_record"), default=False):
            self._record_workflow_if_needed("decision_update", "decision_update", params, result)
        return result

    def _tool_decision_delete(self, params: dict[str, Any]) -> dict[str, Any]:
        if params.get("project_name") is not None:
            return self._route_project_name_tool("decision_delete", params, require_managed=True)
        manager = MCPDecisionRecordsManager(self.project_root)
        result = manager.delete(params.get("id"))
        if not self._bool_param(params.get("__skip_workflow_record"), default=False):
            self._record_workflow_if_needed("decision_delete", "decision_delete", params, result)
        return result

    def _tool_list_executor_run_reports(self, params: dict[str, Any]) -> dict[str, Any]:
        if params.get("project_name") is not None:
            return self._route_project_name_tool("list_executor_run_reports", params, require_managed=True)
        version_raw = params.get("version")
        version: str | None = None
        if version_raw is not None:
            if not isinstance(version_raw, str) or not version_raw.strip():
                raise MCPToolInputError("INVALID_VERSION", "version 必须是字符串。")
            version = version_raw.strip()
            from runner.executor_run_reports import _validate_version
            try:
                _validate_version(version)
            except ValueError as exc:
                raise MCPToolInputError("INVALID_VERSION", str(exc))

        limit = self._bounded_int_param(params.get("limit"), default=10, minimum=1, maximum=50)
        store = ExecutorRunReportStore(self.project_root)
        reports = store.list_reports(version=version, limit=limit)
        result = {
            "ok": True,
            "read_only": True,
            "side_effects": False,
            "reports": reports,
        }
        if not reports:
            result["message"] = "No executor run reports found."
        return result

    def _tool_get_executor_run_report(self, params: dict[str, Any]) -> dict[str, Any]:
        if params.get("project_name") is not None:
            return self._route_project_name_tool("get_executor_run_report", params, require_managed=True)
        version_raw = params.get("version")
        report_id_raw = params.get("report_id")
        latest = self._bool_param(params.get("latest"), default=True)
        include_markdown = self._bool_param(params.get("include_markdown"), default=True)
        max_md = self._bounded_int_param(params.get("max_markdown_chars"), default=30000, minimum=1, maximum=60000)

        version: str | None = None
        if version_raw is not None:
            if not isinstance(version_raw, str) or not version_raw.strip():
                raise MCPToolInputError("INVALID_VERSION", "version 必须是字符串。")
            version = version_raw.strip()
            from runner.executor_run_reports import _validate_version
            try:
                _validate_version(version)
            except ValueError as exc:
                raise MCPToolInputError("INVALID_VERSION", str(exc))

        report_id: str | None = None
        if report_id_raw is not None:
            if not isinstance(report_id_raw, str) or not report_id_raw.strip():
                raise MCPToolInputError("INVALID_REPORT_ID", "report_id 必须是字符串。")
            report_id = report_id_raw.strip()
            from runner.executor_run_reports import _validate_report_id
            try:
                _validate_report_id(report_id)
            except ValueError as exc:
                raise MCPToolInputError("INVALID_REPORT_ID", str(exc))

        store = ExecutorRunReportStore(self.project_root)
        result = store.get_report(
            version=version,
            report_id=report_id,
            latest=latest,
            include_markdown=include_markdown,
            max_markdown_chars=max_md,
        )
        if not result.get("ok"):
            return result
        return {"report": result.get("report", {}), "report_markdown": result.get("report_markdown"), "truncated": result.get("truncated", False)}

    def _collect_context_item(
        self,
        name: str,
        fn: Any,
        params: dict[str, Any],
        partial_errors: list[dict[str, str]],
    ) -> dict[str, Any]:
        try:
            result = fn(params)
            return {"ok": True, "result": result}
        except MCPToolInputError as exc:
            error = self._context_error(name, exc.error_code, exc.message)
        except PlanningBridgeError as exc:
            error = self._context_error(name, "BRIDGE_ERROR", str(exc))
        except SourceReviewError as exc:
            error = self._context_error(name, "SOURCE_REVIEW_ERROR", str(exc))
        except Exception as exc:
            error = self._context_error(name, "ITEM_EXEC_ERROR", str(exc))
        partial_errors.append({
            "name": name,
            "error_code": str(error.get("error_code") or "ITEM_EXEC_ERROR"),
            "message": str(error.get("message") or "context item failed"),
        })
        return {"ok": False, "result": error}

    def _context_error(self, name: str, error_code: str, message: str) -> dict[str, Any]:
        return {
            "ok": False,
            "name": name,
            "error_code": error_code,
            "message": message,
        }

    def _bool_param(self, value: Any, default: bool) -> bool:
        if isinstance(value, bool):
            return value
        return default

    def _bounded_int_param(self, value: Any, default: int, minimum: int, maximum: int) -> int:
        if isinstance(value, bool):
            return default
        try:
            parsed = int(value)
        except Exception:
            return default
        return max(minimum, min(parsed, maximum))

    def _tool_get_version_result(self, params: dict[str, Any]) -> dict[str, Any]:
        version = params.get("version")
        if version is not None and not isinstance(version, str):
            raise MCPToolInputError("INVALID_VERSION", "version 必须是字符串。")
        if isinstance(version, str) and not version.strip():
            version = None
        return self.bridge.get_version_result(self.project_root, version=version)

    def _tool_get_next_version_plan(self, _: dict[str, Any]) -> dict[str, Any]:
        return self.bridge.get_next_version_plan(self.project_root)

    def _tool_get_plan_overview(self, _: dict[str, Any]) -> dict[str, Any]:
        return self._with_project_identity(self.bridge.get_plan_overview(self.project_root))

    def _tool_get_project_doc_section(self, params: dict[str, Any]) -> dict[str, Any]:
        result = self.bridge.get_project_doc_section(self.project_root, params)
        if result.get("ok"):
            return result
        raise MCPToolInputError(
            str(result.get("error_code") or "DOC_SECTION_ERROR"),
            str(result.get("message") or "读取文档段落失败。"),
            {"available_headings": result.get("available_headings", [])},
        )

    def _tool_manage_plan_version(self, params: dict[str, Any]) -> dict[str, Any]:
        action_raw = params.get("action")
        action = action_raw.strip().lower() if isinstance(action_raw, str) else ""
        if action not in {"inspect", "insert_preview", "update_preview", "repair_preview", "apply_preview_status", "insert_from_prompt_file_preview", "apply_preview", "reload_plan", "continue_next_version"}:
            raise MCPToolInputError("INVALID_ACTION", "action 必须是 inspect、insert_preview、update_preview、repair_preview、apply_preview_status、insert_from_prompt_file_preview、apply_preview、reload_plan 或 continue_next_version。")

        if params.get("project_name") is not None:
            if action not in {"insert_preview", "update_preview", "repair_preview", "apply_preview_status", "insert_from_prompt_file_preview", "apply_preview", "reload_plan", "continue_next_version"}:
                raise MCPToolInputError(
                    "PROJECT_NAME_ROUTING_NOT_SUPPORTED",
                    "project_name 路由仅支持 manage_plan_version 的已登记 managed 项目动作：insert_preview、update_preview、repair_preview、apply_preview_status、insert_from_prompt_file_preview、apply_preview、reload_plan、continue_next_version。",
                )
            return self._route_project_name_tool("manage_plan_version", params, require_managed=True)

        plan_path = resolve_project_runner_plan_path(self.project_root)
        has_plan = os.path.isfile(plan_path)

        if action == "inspect":
            if not has_plan:
                return {
                    "ok": True, "action": "inspect",
                    "has_plan": False, "mode": "source_only",
                    "can_insert_preview": False, "can_update_preview": False,
                    "recommended_tool": "manage_runner_plan",
                    "recommended_action": "inspect",
                    "message": "当前项目是 source-only，尚未纳入 Runner 管理。请使用 manage_runner_plan 完成纳管。",
                }
            return self._plan_version_inspect_managed()

        if action == "apply_preview_status":
            patch_id = params.get("patch_id")
            if not isinstance(patch_id, str) or not patch_id.strip():
                raise MCPToolInputError("INVALID_PATCH_ID", "apply_preview_status 需要非空 patch_id。")
            try:
                return self.bridge.get_plan_patch_status(self.project_root, patch_id.strip())
            except PlanningBridgeError as exc:
                return {"ok": False, "action": "apply_preview_status", "error_code": "PATCH_NOT_FOUND", "message": str(exc)}

        if action == "reload_plan":
            result = self._handle_reload_plan()
            self._record_workflow_if_needed("manage_plan_version", action, params, result)
            return result

        if action == "continue_next_version":
            result = self._handle_continue_next_version()
            self._record_workflow_if_needed("manage_plan_version", action, params, result)
            return result

        if not has_plan:
            return {
                "ok": False, "error_code": "PLAN_MISSING", "action": action,
                "message": "当前项目缺少 .colameta/plan.json，无法执行 insert/update/repair preview。请先使用 manage_runner_plan 完成纳管。",
            }

        if action == "insert_preview":
            spec = self._build_insert_version_spec(params)
            result = self.bridge.preview_insert_version(self.project_root, spec)
            self._record_workflow_if_needed("manage_plan_version", action, params, result)
            return result

        if action == "update_preview":
            spec = self._build_update_version_spec(params)
            result = self.bridge.preview_update_version(self.project_root, spec)
            self._record_workflow_if_needed("manage_plan_version", action, params, result)
            return result

        if action == "repair_preview":
            result = self._plan_version_repair_preview(params)
            self._record_workflow_if_needed("manage_plan_version", action, params, result)
            return result

        if action == "insert_from_prompt_file_preview":
            result = self._handle_insert_from_prompt_file_preview(params)
            self._record_workflow_if_needed("manage_plan_version", action, params, result)
            return result

        if action == "apply_preview":
            result = self._handle_apply_preview(params)
            self._record_workflow_if_needed("manage_plan_version", action, params, result)
            return result

        return {"ok": False, "error_code": "UNEXPECTED", "action": action, "message": "未知操作。"}

    def _handle_reload_plan(self) -> dict[str, Any]:
        from runner.plan_reload_workflow import PlanReloadService

        result = PlanReloadService(self.project_root).reload_plan()
        if not isinstance(result, dict):
            return {
                "ok": False,
                "action": "reload_plan",
                "error_code": "RELOAD_PLAN_INVALID_RESULT",
                "message": "reload_plan 返回结构无效。",
            }
        result["action"] = "reload_plan"
        if result.get("ok") and result.get("current_version"):
            result["next_actions"] = [
                {
                    "tool": "manage_executor_workflow",
                    "action": "preflight",
                    "params": {"action": "preflight", "provider": "codex"},
                    "reason": "state 已同步到当前版本，下一步检查执行器 preflight。",
                    "requires_confirmation": False,
                }
            ]
        return result

    def _handle_continue_next_version(self) -> dict[str, Any]:
        from runner.continue_version_workflow import ContinueNextVersionService

        result = ContinueNextVersionService(self.project_root).continue_next_version()
        if not isinstance(result, dict):
            return {
                "ok": False,
                "action": "continue_next_version",
                "error_code": "CONTINUE_NEXT_VERSION_INVALID_RESULT",
                "message": "continue_next_version 返回结构无效。",
            }
        result["action"] = "continue_next_version"
        if result.get("ok") and result.get("runner_status") != "COMPLETED":
            result["next_actions"] = [
                {
                    "tool": "manage_executor_workflow",
                    "action": "preflight",
                    "params": {"action": "preflight", "provider": "codex"},
                    "reason": "已进入下一版本，下一步检查执行器 preflight。",
                    "requires_confirmation": False,
                }
            ]
        return result

    def _plan_version_inspect_managed(self) -> dict[str, Any]:
        plan_path = resolve_project_runner_path(self.project_root, "plan.json")
        state_path = resolve_project_runner_path(self.project_root, "state.json")
        result: dict[str, Any] = {
            "ok": True, "action": "inspect",
            "has_plan": True, "mode": "runner_managed",
            "has_state": os.path.isfile(state_path),
            "can_insert_preview": True, "can_update_preview": True,
        }
        try:
            from runner.mcp_runner_plan import MCPRunnerPlanManager
            inspect_result = MCPRunnerPlanManager(self.project_root).inspect()
            if isinstance(inspect_result, dict):
                result["plan_summary"] = inspect_result.get("plan_summary")
                result["lint_summary"] = (
                    inspect_result.get("plan_summary", {}).get("lint_status")
                    if isinstance(inspect_result.get("plan_summary"), dict) else None
                )
                result["blockers"] = list(inspect_result.get("blockers", []))
                result["warnings"] = list(inspect_result.get("warnings", []))
        except Exception:
            pass
        return result

    def _build_insert_version_spec(self, params: dict[str, Any]) -> dict[str, Any]:
        insert_after = params.get("insert_after")
        if not isinstance(insert_after, str) or not insert_after.strip():
            if self._plan_versions_empty():
                insert_after = "__first__"
            else:
                raise MCPToolInputError("INVALID_INSERT_AFTER", "insert_preview 需要非空 insert_after。")

        version = params.get("version")
        if not isinstance(version, str) or not version.strip():
            raise MCPToolInputError("INVALID_VERSION", "insert_preview 需要非空 version。")

        name = params.get("name")
        if not isinstance(name, str) or not name.strip():
            raise MCPToolInputError("INVALID_NAME", "insert_preview 需要非空 name。")

        description = params.get("description")
        if not isinstance(description, str) or not description.strip():
            raise MCPToolInputError("INVALID_DESCRIPTION", "insert_preview 需要非空 description。")

        prompt = params.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise MCPToolInputError("INVALID_PROMPT", "insert_preview 需要非空 prompt。")

        allowed_files = self._normalize_string_list(params.get("allowed_files"), "allowed_files")
        if not allowed_files:
            raise MCPToolInputError("INVALID_ALLOWED_FILES", "insert_preview 需要非空 allowed_files 列表。")

        acceptance_commands_val = params.get("acceptance_commands")
        if not isinstance(acceptance_commands_val, list) or not acceptance_commands_val:
            raise MCPToolInputError("INVALID_ACCEPTANCE_COMMANDS", "insert_preview 需要非空 acceptance_commands 列表。")
        acceptance_commands = self._normalize_acceptance_commands_param(acceptance_commands_val)

        spec: dict[str, Any] = {
            "insert_after": insert_after.strip(),
            "version": version.strip(),
            "name": name.strip(),
            "description": description.strip(),
            "prompt": prompt,
            "allowed_files": allowed_files,
            "acceptance_commands": acceptance_commands,
        }

        manual_acceptance = self._normalize_optional_string_list(params.get("manual_acceptance"), "manual_acceptance")
        if manual_acceptance is not None:
            spec["manual_acceptance"] = manual_acceptance

        out_of_scope = self._normalize_optional_string_list(params.get("out_of_scope"), "out_of_scope")
        if out_of_scope is not None:
            spec["out_of_scope"] = out_of_scope

        context_files = self._normalize_optional_string_list(params.get("context_files"), "context_files")
        if context_files is not None:
            spec["context_files"] = context_files

        forbidden_files = self._normalize_optional_string_list(params.get("forbidden_files"), "forbidden_files")
        if forbidden_files is not None:
            spec["forbidden_files"] = forbidden_files

        prompt_file = params.get("prompt_file")
        if isinstance(prompt_file, str) and prompt_file.strip():
            spec["prompt_file"] = prompt_file.strip()

        execution = params.get("execution")
        if execution is not None:
            spec["execution"] = self._extract_execution_profile(execution)

        if "allow_no_changes" in params and params.get("allow_no_changes") is not None:
            allow_no_changes = params.get("allow_no_changes")
            if not isinstance(allow_no_changes, bool):
                raise MCPToolInputError("INVALID_ALLOW_NO_CHANGES", "allow_no_changes 必须是布尔值。")
            spec["allow_no_changes"] = allow_no_changes

        return spec

    def _plan_versions_empty(self) -> bool:
        plan_path = resolve_project_runner_plan_path(self.project_root)
        try:
            with open(plan_path, "r", encoding="utf-8") as f:
                plan = json.load(f)
        except Exception:
            return False
        versions = plan.get("versions", []) if isinstance(plan, dict) else []
        return isinstance(versions, list) and len(versions) == 0

    def _build_update_version_spec(self, params: dict[str, Any]) -> dict[str, Any]:
        version = params.get("version")
        if not isinstance(version, str) or not version.strip():
            raise MCPToolInputError("INVALID_VERSION", "update_preview 需要非空 version。")

        spec: dict[str, Any] = {"version": version.strip()}
        update_fields = ["name", "description", "prompt"]
        has_update = False
        for field in update_fields:
            val = params.get(field)
            if val is not None:
                if not isinstance(val, str) or not val.strip():
                    raise MCPToolInputError(f"INVALID_{field.upper()}", f"{field} 必须是非空字符串。")
                spec[field] = val.strip()
                has_update = True

        allowed_raw = params.get("allowed_files")
        if allowed_raw is not None:
            allowed = self._normalize_string_list(allowed_raw, "allowed_files")
            if not allowed:
                raise MCPToolInputError("INVALID_ALLOWED_FILES", "allowed_files 不能为空。")
            spec["allowed_files"] = allowed
            has_update = True

        acceptance_raw = params.get("acceptance_commands")
        if acceptance_raw is not None:
            if not isinstance(acceptance_raw, list) or not acceptance_raw:
                raise MCPToolInputError("INVALID_ACCEPTANCE_COMMANDS", "acceptance_commands 不能为空。")
            spec["acceptance_commands"] = self._normalize_acceptance_commands_param(acceptance_raw)
            has_update = True

        for field in ("manual_acceptance", "out_of_scope", "context_files", "forbidden_files"):
            val = params.get(field)
            if val is not None:
                items = self._normalize_string_list(val, field)
                if items is not None:
                    spec[field] = items
                    has_update = True

        execution = params.get("execution")
        if execution is not None:
            spec["execution"] = self._extract_execution_profile(execution)
            has_update = True

        if "allow_no_changes" in params and params.get("allow_no_changes") is not None:
            allow_no_changes = params.get("allow_no_changes")
            if not isinstance(allow_no_changes, bool):
                raise MCPToolInputError("INVALID_ALLOW_NO_CHANGES", "allow_no_changes 必须是布尔值。")
            spec["allow_no_changes"] = allow_no_changes
            has_update = True

        if not has_update:
            raise MCPToolInputError("NO_UPDATE_FIELDS", "update_preview 至少需要一个可更新字段。")

        return spec

    def _normalize_acceptance_commands_param(self, commands: list[Any]) -> list[Any]:
        if not isinstance(commands, list) or not commands:
            raise MCPToolInputError("INVALID_ACCEPTANCE_COMMANDS", "acceptance_commands 必须是非空列表。")
        result: list[Any] = []
        for idx, item in enumerate(commands):
            if isinstance(item, str):
                if not item.strip():
                    raise MCPToolInputError("INVALID_ACCEPTANCE_COMMANDS", f"acceptance_commands[{idx}] 字符串命令不能为空。")
                result.append(item.strip())
            elif isinstance(item, dict):
                cmd_val = item.get("command")
                if not isinstance(cmd_val, str) or not cmd_val.strip():
                    raise MCPToolInputError("INVALID_ACCEPTANCE_COMMANDS", f"acceptance_commands[{idx}] 缺少非空 command。")
                command = cmd_val.strip()
                if "\n" in command or "\r" in command:
                    raise MCPToolInputError("INVALID_ACCEPTANCE_COMMANDS", f"acceptance_commands[{idx}] 不允许多行命令。")
                entry: dict[str, Any] = {"command": command}
                ts_raw = item.get("timeout_seconds")
                if ts_raw is not None:
                    if isinstance(ts_raw, bool) or not isinstance(ts_raw, int) or ts_raw <= 0:
                        raise MCPToolInputError("INVALID_ACCEPTANCE_COMMANDS", f"acceptance_commands[{idx}] timeout_seconds 必须是正整数。")
                    entry["timeout_seconds"] = ts_raw
                cf_raw = item.get("continue_on_failure")
                if cf_raw is not None:
                    if not isinstance(cf_raw, bool):
                        raise MCPToolInputError("INVALID_ACCEPTANCE_COMMANDS", f"acceptance_commands[{idx}] continue_on_failure 必须是布尔值。")
                    entry["continue_on_failure"] = cf_raw
                result.append(entry)
            else:
                raise MCPToolInputError("INVALID_ACCEPTANCE_COMMANDS", f"acceptance_commands[{idx}] 必须是字符串或对象。")
        return result

    def _extract_execution_profile(self, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise MCPToolInputError("INVALID_EXECUTION", "execution 必须是 JSON 对象。")
        allowed = {"provider", "model", "model_name", "pi_model", "codex_model", "opencode_model", "lane", "capability_level", "notes"}
        unknown = set(value.keys()) - allowed
        if unknown:
            raise MCPToolInputError("INVALID_EXECUTION", f"execution 包含不支持字段：{'、'.join(sorted(unknown))}")
        normalized: dict[str, Any] = {}
        for key in allowed:
            if key not in value:
                continue
            raw = value[key]
            if key == "provider":
                if not isinstance(raw, str) or not raw.strip():
                    raise MCPToolInputError("INVALID_EXECUTION", "execution.provider 必须是非空字符串。")
                provider_val = raw.strip().lower()
                if provider_val not in {"pi", "codex", "opencode"}:
                    raise MCPToolInputError("INVALID_EXECUTION", "execution.provider 必须是 pi、codex 或 opencode。")
                normalized[key] = provider_val
            else:
                if not isinstance(raw, str) or not raw.strip():
                    raise MCPToolInputError("INVALID_EXECUTION", f"execution.{key} 必须是非空字符串。")
                normalized[key] = raw.strip()
        return normalized

    def _normalize_optional_string_list(self, value: Any, field_name: str) -> list[str] | None:
        if value is None:
            return None
        return self._normalize_string_list(value, field_name)

    def _normalize_string_list(self, value: Any, field_name: str) -> list[str]:
        if not isinstance(value, list):
            raise MCPToolInputError(f"INVALID_{field_name.upper()}", f"{field_name} 必须是字符串列表。")
        result: list[str] = []
        for idx, item in enumerate(value):
            if not isinstance(item, str) or not item.strip():
                raise MCPToolInputError(f"INVALID_{field_name.upper()}", f"{field_name}[{idx}] 必须是非空字符串。")
            result.append(item.strip())
        return result

    def _plan_version_repair_preview(self, params: dict[str, Any]) -> dict[str, Any]:
        from runner.plan_standards_linter import PlanStandardsLinter
        lint_result = PlanStandardsLinter().lint_project(self.project_root)
        if not isinstance(lint_result, dict) or not lint_result.get("ok"):
            return {
                "ok": True, "action": "repair_preview",
                "can_preview": False,
                "message": "无法读取 plan lint 状态。请先检查 plan.json。",
                "suggested_next_action": "fix_plan_manually",
            }

        target_version = params.get("version")
        if isinstance(target_version, str):
            target_version = target_version.strip()
        else:
            target_version = None

        repair_kinds_raw = params.get("repair_kinds")
        allowed_kinds = {"acceptance_command_shape", "invalid_provider", "missing_optional_safety_fields", "prompt_file_safety"}
        repair_kinds: set[str] | None = None
        if isinstance(repair_kinds_raw, list) and repair_kinds_raw:
            kinds = set()
            for item in repair_kinds_raw:
                if isinstance(item, str) and item.strip() in allowed_kinds:
                    kinds.add(item.strip())
            if kinds:
                repair_kinds = kinds

        issues = lint_result.get("issues", [])
        repair_candidates: list[dict[str, Any]] = []
        blockers: list[str] = []
        warnings: list[str] = []

        for issue in issues:
            if not isinstance(issue, dict):
                continue
            if target_version:
                ver = issue.get("version")
                if ver is not None and str(ver) != target_version:
                    continue

            error_code = issue.get("error_code", "")
            field = issue.get("field", "")
            blocking = bool(issue.get("blocking", False))
            suggestion = issue.get("suggestion", "")

            if repair_kinds and error_code not in self._repair_issue_codes(repair_kinds):
                continue

            repair: dict[str, Any] = {"issue": error_code, "field": field, "blocking": blocking, "message": issue.get("message", "")}

            if error_code == "LEGACY_STRING_ACCEPTANCE_COMMAND" and (not repair_kinds or "acceptance_command_shape" in (repair_kinds or set())):
                repair["repair_action"] = "normalize_to_object"
                repair["repair_suggestion"] = "将字符串命令转为 {\"command\": \"...\", \"timeout_seconds\": 600, \"continue_on_failure\": false}"
                repair_candidates.append(repair)

            elif error_code == "MISSING_TIMEOUT_SECONDS" and (not repair_kinds or "acceptance_command_shape" in (repair_kinds or set())):
                repair["repair_action"] = "add_default_timeout"
                repair["repair_suggestion"] = "添加 timeout_seconds: 600"
                repair_candidates.append(repair)

            elif error_code == "MISSING_CONTINUE_ON_FAILURE" and (not repair_kinds or "acceptance_command_shape" in (repair_kinds or set())):
                repair["repair_action"] = "add_default_continue_on_failure"
                repair["repair_suggestion"] = "添加 continue_on_failure: false"
                repair_candidates.append(repair)

            elif error_code == "INVALID_EXECUTION_PROVIDER" and (not repair_kinds or "invalid_provider" in (repair_kinds or set())):
                repair["repair_action"] = "blocker_user_must_choose"
                repair["repair_suggestion"] = "需要用户从 pi、codex、opencode 中选择合法 provider。"
                repair_candidates.append(repair)

            elif error_code == "INVALID_MODEL_EXECUTION_PROVIDER" and (not repair_kinds or "invalid_provider" in (repair_kinds or set())):
                repair["repair_action"] = "blocker_user_must_choose"
                repair["repair_suggestion"] = "需要用户从 pi、codex、opencode 中选择合法 provider。"
                repair_candidates.append(repair)

            elif error_code in ("MISSING_OUT_OF_SCOPE", "MISSING_VERSION_DESCRIPTION") and (not repair_kinds or "missing_optional_safety_fields" in (repair_kinds or set())):
                repair["repair_action"] = "optional_recommendation"
                repair_candidates.append(repair)

            elif error_code == "PROMPT_FILE_PATH_UNSAFE" and (not repair_kinds or "prompt_file_safety" in (repair_kinds or set())):
                repair["repair_action"] = "blocker_manual_fix_required"
                repair_candidates.append(repair)
                if blocking:
                    blockers.append(f"prompt_file 路径不安全：{issue.get('message', '')}")

            if blocking and repair.get("repair_action") not in ("blocker_user_must_choose", "blocker_manual_fix_required"):
                blockers.append(f"{error_code}: {issue.get('message', '')}")

        can_preview = True
        has_blocker_repairs = any(
            r.get("repair_action") in ("blocker_user_must_choose", "blocker_manual_fix_required")
            for r in repair_candidates
        )
        has_actionable = any(
            r.get("repair_action") in ("normalize_to_object", "add_default_timeout", "add_default_continue_on_failure", "optional_recommendation")
            for r in repair_candidates
        )

        if not repair_candidates:
            can_preview = False
            return {
                "ok": True, "action": "repair_preview",
                "can_preview": False,
                "repair_candidates": [],
                "blockers": blockers,
                "warnings": warnings,
                "message": "未检测到可自动修复的问题。",
                "suggested_next_action": "no_repair_needed",
            }

        suggested_next_action = "review_repair_candidates"
        if has_blocker_repairs and not has_actionable:
            can_preview = False
            suggested_next_action = "manual_fix_required"

        return {
            "ok": True, "action": "repair_preview",
            "can_preview": can_preview,
            "repair_candidates": repair_candidates,
            "blockers": blockers,
            "warnings": warnings,
            "message": "" if can_preview else "存在需要人工修复的阻断问题。",
            "suggested_next_action": suggested_next_action,
        }

    def _repair_issue_codes(self, kinds: set[str]) -> set[str]:
        mapping: dict[str, set[str]] = {
            "acceptance_command_shape": {"LEGACY_STRING_ACCEPTANCE_COMMAND", "MISSING_TIMEOUT_SECONDS", "MISSING_CONTINUE_ON_FAILURE"},
            "invalid_provider": {"INVALID_EXECUTION_PROVIDER", "INVALID_MODEL_EXECUTION_PROVIDER"},
            "missing_optional_safety_fields": {"MISSING_OUT_OF_SCOPE", "MISSING_VERSION_DESCRIPTION"},
            "prompt_file_safety": {"PROMPT_FILE_PATH_UNSAFE"},
        }
        result: set[str] = set()
        for kind in kinds:
            codes = mapping.get(kind)
            if codes:
                result.update(codes)
        return result

    _VERSION_FILENAME_RE = re.compile(r"^[vV]\d[\d.]*\.md$")

    def _validate_prompt_file_safe(self, prompt_file: str) -> None:
        if not isinstance(prompt_file, str) or not prompt_file.strip():
            raise MCPToolInputError("PROMPT_FILE_REQUIRED", "prompt_file 不能为空。")
        if os.path.isabs(prompt_file):
            raise MCPToolInputError("INVALID_PROMPT_FILE", "prompt_file 不能是绝对路径。")
        if ".." in prompt_file.split("/"):
            raise MCPToolInputError("INVALID_PROMPT_FILE", "prompt_file 不能包含 ..。")
        if "\\" in prompt_file:
            raise MCPToolInputError("INVALID_PROMPT_FILE", "prompt_file 不能包含反斜杠。")
        if "/" in prompt_file:
            raise MCPToolInputError("INVALID_PROMPT_FILE", "prompt_file 不能包含多级路径，仅允许文件名。")
        if not prompt_file.endswith(".md"):
            raise MCPToolInputError("INVALID_PROMPT_FILE", "prompt_file 必须以 .md 结尾。")
        if not self._VERSION_FILENAME_RE.match(prompt_file):
            raise MCPToolInputError("INVALID_PROMPT_FILE", "prompt_file 必须是版本文件名，例如 v1.84.54.md。")

    def _version_from_prompt_filename(self, prompt_file: str) -> str:
        v = prompt_file[:-3]
        if not v:
            raise MCPToolInputError("INVALID_PROMPT_FILE", "prompt_file 版本号不能为空。")
        return v

    def _parse_version_tuple(self, version: str) -> tuple[int, ...] | None:
        parts = version.lstrip("vV").replace("-", ".").split(".")
        nums: list[int] = []
        for p in parts:
            try:
                nums.append(int(p))
            except ValueError:
                return None
        return tuple(nums)

    def _auto_derive_insert_after(self, version: str) -> str:
        plan_path = resolve_project_runner_plan_path(self.project_root)
        if not os.path.isfile(plan_path):
            return ""
        try:
            with open(plan_path, "r", encoding="utf-8") as f:
                plan = json.load(f)
        except Exception:
            return ""
        versions = plan.get("versions", [])
        if not versions:
            return "__first__"
        new_parsed = self._parse_version_tuple(version)
        if not new_parsed:
            return ""
        candidates: list[tuple[tuple[int, ...], str]] = []
        for v in versions:
            v_ver = v.get("version", "")
            v_parsed = self._parse_version_tuple(v_ver)
            if v_parsed and v_parsed < new_parsed:
                candidates.append((v_parsed, v_ver))
        if not candidates:
            return ""
        candidates.sort(key=lambda x: x[0])
        return candidates[-1][1]

    def _version_exists_in_plan(self, version: str) -> bool:
        plan_path = resolve_project_runner_plan_path(self.project_root)
        if not os.path.isfile(plan_path):
            return False
        try:
            with open(plan_path, "r", encoding="utf-8") as f:
                plan = json.load(f)
        except Exception:
            return False
        for v in plan.get("versions", []):
            if v.get("version") == version:
                return True
        return False

    def _handle_insert_from_prompt_file_preview(self, params: dict[str, Any]) -> dict[str, Any]:
        prompt_file = params.get("prompt_file")
        if not isinstance(prompt_file, str) or not prompt_file.strip():
            return {"ok": False, "error_code": "PROMPT_FILE_REQUIRED", "action": "insert_from_prompt_file_preview",
                    "message": "insert_from_prompt_file_preview 需要非空 prompt_file。"}
        prompt_file = prompt_file.strip()
        try:
            self._validate_prompt_file_safe(prompt_file)
        except MCPToolInputError as e:
            return {"ok": False, "error_code": e.error_code, "action": "insert_from_prompt_file_preview", "message": e.message}

        version = self._version_from_prompt_filename(prompt_file)
        version_param = params.get("version")
        if version_param is not None:
            if not isinstance(version_param, str) or not version_param.strip():
                return {"ok": False, "error_code": "INVALID_VERSION", "action": "insert_from_prompt_file_preview",
                        "message": "version 必须是非空字符串。"}
            if version_param.strip() != version:
                return {"ok": False, "error_code": "INVALID_VERSION", "action": "insert_from_prompt_file_preview",
                        "message": f"version 必须与 prompt_file 匹配：{version}"}

        prompts_dir = resolve_project_runner_path(self.project_root, "prompts")
        file_path = os.path.join(prompts_dir, prompt_file)
        real_prompts = os.path.realpath(prompts_dir)
        real_file = os.path.realpath(file_path)
        if not real_file.startswith(real_prompts + os.sep):
            return {"ok": False, "error_code": "PROMPT_FILE_UNSAFE", "action": "insert_from_prompt_file_preview",
                    "message": "prompt 文件路径不安全。"}
        if not os.path.isfile(real_file):
            return {"ok": False, "error_code": "PROMPT_FILE_NOT_FOUND", "action": "insert_from_prompt_file_preview",
                    "message": f"prompt 文件不存在：{resolve_project_runner_rel_dir(self.project_root)}/prompts/{prompt_file}"}

        try:
            with open(real_file, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            return {"ok": False, "error_code": "PROMPT_FILE_READ_ERROR", "action": "insert_from_prompt_file_preview",
                    "message": f"读取 prompt 文件失败：{resolve_project_runner_rel_dir(self.project_root)}/prompts/{prompt_file}"}

        if not content.strip():
            return {"ok": False, "error_code": "CONTENT_EMPTY", "action": "insert_from_prompt_file_preview",
                    "message": "prompt 文件内容为空。"}

        front_matter, body = _parse_prompt_front_matter(content)
        if body is None:
            return {"ok": False, "error_code": "FRONT_MATTER_INVALID", "action": "insert_from_prompt_file_preview",
                    "message": "prompt 文件 front matter 缺少结束分隔符 ---。"}

        if not body.strip():
            return {"ok": False, "error_code": "CONTENT_EMPTY", "action": "insert_from_prompt_file_preview",
                    "message": "prompt 正文为空。"}

        if self._version_exists_in_plan(version):
            return {"ok": False, "error_code": "VERSION_EXISTS", "action": "insert_from_prompt_file_preview",
                    "message": f"版本 {version} 已存在于 plan 中。"}

        merged_params: dict[str, Any] = {
            "version": version,
            "prompt": body,
            "prompt_file": prompt_file,
        }

        insert_after = params.get("insert_after")
        if insert_after is None:
            insert_after = self._auto_derive_insert_after(version)
            if not insert_after:
                return {"ok": False, "error_code": "INSERT_AFTER_NOT_FOUND", "action": "insert_from_prompt_file_preview",
                        "message": f"无法推导 insert_after：未找到小于 {version} 的版本。"}
        merged_params["insert_after"] = insert_after

        name_value = params.get("name")
        if not isinstance(name_value, str) or not name_value.strip():
            return {"ok": False, "error_code": "NAME_MISSING", "action": "insert_from_prompt_file_preview",
                    "message": "insert_from_prompt_file_preview 需要 GPTs 显式提供非空 name；不要从 prompt 文件或默认 Version vX 推导。"}
        merged_params["name"] = name_value.strip()

        description_value = params.get("description")
        if not isinstance(description_value, str) or not description_value.strip():
            return {"ok": False, "error_code": "DESCRIPTION_MISSING", "action": "insert_from_prompt_file_preview",
                    "message": "insert_from_prompt_file_preview 需要 GPTs 显式提供非空 description；不要从 prompt 文件或默认描述推导。"}
        merged_params["description"] = description_value.strip()

        allowed_files = params.get("allowed_files", front_matter.get("allowed_files"))
        if allowed_files is None:
            return {"ok": False, "error_code": "ALLOWED_FILES_MISSING", "action": "insert_from_prompt_file_preview",
                    "message": "insert_from_prompt_file_preview 需要 allowed_files 参数，或 prompt 文件 front matter 提供 allowed_files。"}
        merged_params["allowed_files"] = allowed_files

        acceptance_commands = params.get("acceptance_commands", front_matter.get("acceptance_commands"))
        if acceptance_commands is None:
            return {"ok": False, "error_code": "ACCEPTANCE_COMMANDS_MISSING", "action": "insert_from_prompt_file_preview",
                    "message": "insert_from_prompt_file_preview 需要 acceptance_commands 参数，或 prompt 文件 front matter 提供 acceptance_commands。"}
        merged_params["acceptance_commands"] = acceptance_commands

        for field in ("manual_acceptance", "out_of_scope", "context_files", "forbidden_files", "allow_no_changes"):
            if field in params:
                merged_params[field] = params.get(field)
            elif field in front_matter:
                merged_params[field] = front_matter.get(field)

        if "execution" in params:
            merged_params["execution"] = params.get("execution")
        elif "execution" in front_matter:
            execution = front_matter.get("execution")
            if execution is not None:
                if isinstance(execution, dict):
                    provider = execution.get("provider")
                    if provider is not None:
                        if not isinstance(provider, str) or not provider.strip():
                            return {"ok": False, "error_code": "INVALID_PROVIDER", "action": "insert_from_prompt_file_preview",
                                    "message": "执行器 provider 必须是非空字符串。"}
                        provider_str = provider.strip()
                        if provider_str not in ("pi", "codex", "opencode"):
                            return {"ok": False, "error_code": "INVALID_PROVIDER", "action": "insert_from_prompt_file_preview",
                                    "message": f"执行器 provider 必须是 pi、codex 或 opencode，收到：{provider_str}"}
                merged_params["execution"] = execution

        try:
            spec = self._build_insert_version_spec(merged_params)
        except MCPToolInputError as e:
            return {"ok": False, "error_code": e.error_code, "action": "insert_from_prompt_file_preview", "message": e.message}

        try:
            result = self.bridge.preview_insert_version(self.project_root, spec)
        except PlanningBridgeError as e:
            return {"ok": False, "error_code": "BRIDGE_ERROR", "action": "insert_from_prompt_file_preview",
                    "message": str(e)}

        if isinstance(result, dict) and result.get("ok"):
            result["source"] = "insert_from_prompt_file_preview"
            result["prompt_file"] = prompt_file
            result["version_from_filename"] = version
            if "recommended_next_action" not in result:
                result["recommended_next_action"] = {
                    "tool": "manage_plan_version",
                    "action": "apply_preview",
                    "params": {"action": "apply_preview", "patch_id": result.get("patch_id", "")},
                    "reason": "应用 plan patch，将新版本写入 plan.json 和 prompt 文件。",
                    "requires_confirmation": True,
                }
        return result

    def _handle_apply_preview(self, params: dict[str, Any]) -> dict[str, Any]:
        patch_id = params.get("patch_id")
        if not isinstance(patch_id, str) or not patch_id.strip():
            return {"ok": False, "action": "apply_preview", "error_code": "PATCH_ID_REQUIRED",
                    "message": "apply_preview 需要非空 patch_id。", "patch_id": ""}
        patch_id = patch_id.strip()

        try:
            result = self.bridge.apply_plan_patch(self.project_root, patch_id)
        except PlanningBridgeError as e:
            return {"ok": False, "action": "apply_preview", "error_code": "PATCH_NOT_FOUND",
                    "message": str(e), "patch_id": patch_id}

        if isinstance(result, dict) and result.get("ok"):
            result["action"] = "apply_preview"
            inserted = result.get("inserted_version")
            updated = result.get("updated_version")
            operation = result.get("operation", "")
            executor_provider = None
            if inserted or updated:
                plan_path = resolve_project_runner_plan_path(self.project_root)
                if os.path.isfile(plan_path):
                    try:
                        with open(plan_path, "r", encoding="utf-8") as f:
                            plan = json.load(f)
                        target_version = inserted or updated
                        for v in plan.get("versions", []):
                            if v.get("version") == target_version:
                                exec_cfg = v.get("execution", {})
                                if isinstance(exec_cfg, dict) and exec_cfg.get("provider"):
                                    executor_provider = exec_cfg["provider"]
                                break
                    except Exception:
                        pass
            if not executor_provider:
                executor_provider = "codex"
            result["next_actions"] = [
                {
                    "tool": "manage_executor_workflow",
                    "action": "preflight",
                    "params": {"action": "preflight", "provider": executor_provider},
                    "reason": f"检查 {executor_provider} 执行器可用性。",
                    "requires_confirmation": False,
                },
                {
                    "tool": "manage_plan_version",
                    "action": "inspect",
                    "params": {"action": "inspect"},
                    "reason": "查看应用 patch 后的 plan 状态。",
                    "requires_confirmation": False,
                },
            ]
        else:
            result["action"] = "apply_preview"
            if "patch_id" not in result:
                result["patch_id"] = patch_id
        return result

    def _tool_manage_project_patch(self, params: dict[str, Any]) -> dict[str, Any]:
        action_raw = params.get("action")
        action = action_raw.strip().lower() if isinstance(action_raw, str) else ""
        if action not in {"preview", "apply", "status", "preview_delete"}:
            raise MCPToolInputError("INVALID_ACTION", "action 必须是 preview、apply、status 或 preview_delete。")
        if params.get("project_name") is not None:
            return self._route_project_name_tool("manage_project_patch", params, require_managed=True)
        manager = MCPProjectPatchManager(self.project_root, self.source_review)
        if action == "preview":
            result = manager.preview(params)
            self._record_workflow_if_needed("manage_project_patch", action, params, result)
            return result
        if action == "preview_delete":
            result = manager.preview_delete(params)
            self._record_workflow_if_needed("manage_project_patch", "preview", params, result)
            return result
        if action == "apply":
            result = manager.apply(params)
            self._record_workflow_if_needed("manage_project_patch", action, params, result)
            return result
        return manager.status(params)

    def _tool_manage_git_history(self, params: dict[str, Any]) -> dict[str, Any]:
        action_raw = params.get("action")
        action = action_raw.strip().lower() if isinstance(action_raw, str) else ""
        if action not in {"log", "show", "diff_commits", "reconcile_git_history_preview", "restore_file_preview", "restore_file_apply", "revert_preview", "revert_apply"}:
            raise MCPToolInputError("INVALID_ACTION", "action 必须是 log、show、diff_commits、reconcile_git_history_preview、restore_file_preview、restore_file_apply、revert_preview 或 revert_apply。")
        if params.get("project_name") is not None:
            return self._route_project_name_tool("manage_git_history", params, require_managed=True)
        manager = MCPGitHistoryManager(self.project_root, self.source_review)
        result = manager.handle(action, params)
        self._record_workflow_if_needed("manage_git_history", action, params, result)
        return result

    def _tool_preview_insert_version(self, params: dict[str, Any]) -> dict[str, Any]:
        spec = self._parse_spec_json_or_legacy(params)
        return self.bridge.preview_insert_version(self.project_root, spec)

    def _tool_preview_update_version(self, params: dict[str, Any]) -> dict[str, Any]:
        spec = self._parse_spec_json_or_legacy(params)
        return self.bridge.preview_update_version(self.project_root, spec)

    def _tool_get_plan_patch_status(self, params: dict[str, Any]) -> dict[str, Any]:
        patch_id = params.get("patch_id")
        if not isinstance(patch_id, str) or not patch_id.strip():
            raise PlanningBridgeError("patch_id 参数不能为空。")
        return self.bridge.get_plan_patch_status(self.project_root, patch_id.strip())

    def _tool_get_repo_overview(self, params: dict[str, Any]) -> dict[str, Any]:
        project_root, _ = self._resolve_read_only_project_context(params)
        result = self.source_review.get_repo_overview(project_root, self._strip_project_name_param(params))
        return self._with_project_identity(result, project_root)

    def _tool_get_git_status(self, params: dict[str, Any]) -> dict[str, Any]:
        project_root, _ = self._resolve_read_only_project_context(params)
        hint = params.get("project_name") is None
        return self._with_project_identity(self.source_review.get_git_status(project_root), project_root, hint_project_name=hint)

    def _tool_get_git_log(self, params: dict[str, Any]) -> dict[str, Any]:
        project_root, project_record = self._resolve_read_only_project_context(params)
        result = self.source_review.get_git_log(project_root, self._strip_project_name_param(params))
        if isinstance(project_record, dict) and result.get("ok"):
            result["project_name"] = project_record.get("project_name")
        return result

    def _tool_manage_files(self, params: dict[str, Any]) -> dict[str, Any]:
        action = params.get("action", "")
        if not isinstance(action, str) or not action.strip():
            raise MCPToolInputError("INVALID_ACTION", "action 必须是 search、read、create、edit 或 delete。")
        action = action.strip().lower()
        if action == "search":
            search_params = dict(params)
            search_params.pop("action", None)
            result = self._tool_search_source(search_params)
            if isinstance(result, dict) and result.get("ok"):
                result["action"] = "search"
                result["delegated_tool"] = "search_source"
            return result
        elif action == "read":
            read_params = dict(params)
            read_params.pop("action", None)
            result = self._tool_get_source_file(read_params)
            if isinstance(result, dict) and result.get("ok"):
                result["action"] = "read"
                result["delegated_tool"] = "get_source_file"
            return result
        elif action in {"create", "edit", "delete"}:
            phase = params.get("phase")
            if not isinstance(phase, str) or not phase.strip():
                raise MCPToolInputError("INVALID_PHASE", f"{action} 操作需要 phase（preview、apply 或 status）。")
            phase = phase.strip().lower()
            if phase not in {"preview", "apply", "status"}:
                raise MCPToolInputError("INVALID_PHASE", "phase 必须是 preview、apply 或 status。")
            lifecycle_params = dict(params)
            lifecycle_params.pop("phase", None)
            if action == "create" and phase == "preview":
                if "patch_text" in lifecycle_params:
                    raise MCPToolInputError("INVALID_INPUT", "create preview 不支持 patch_text；请使用 file + new_text 创建新文件。")
                old_text = lifecycle_params.get("old_text", "")
                if old_text != "":
                    raise MCPToolInputError("INVALID_OLD_TEXT", "create preview 必须使用 old_text=\"\" 或省略 old_text；编辑已有文件请使用 action=edit。")
                lifecycle_params["action"] = "preview"
                lifecycle_params["old_text"] = ""
                lifecycle_params["allow_create"] = True
            elif action == "delete" and phase == "preview":
                lifecycle_params["action"] = "preview_delete"
                for key in ("old_text", "new_text", "patch_text", "max_files"):
                    lifecycle_params.pop(key, None)
            else:
                lifecycle_params["action"] = phase
                if action == "edit" and phase == "preview":
                    lifecycle_params["allow_create"] = False
                    lifecycle_params["require_existing_file"] = True
            result = self._tool_manage_project_patch(lifecycle_params)
            if isinstance(result, dict):
                result["action"] = action
                result["phase"] = phase
                result["delegated_tool"] = "manage_project_patch"
            return result
        else:
            raise MCPToolInputError("INVALID_ACTION", "action 必须是 search、read、create、edit 或 delete。")

    def _tool_get_source_file(self, params: dict[str, Any]) -> dict[str, Any]:
        project_root, _ = self._resolve_read_only_project_context(params)
        result = self.source_review.get_source_file(project_root, self._strip_project_name_param(params))
        if result.get("ok"):
            hint = params.get("project_name") is None
            return self._with_project_identity(result, project_root, hint_project_name=hint)
        raise MCPToolInputError(
            str(result.get("error_code") or "SOURCE_FILE_ERROR"),
            str(result.get("message") or "读取源码文件失败。"),
        )

    def _tool_search_source(self, params: dict[str, Any]) -> dict[str, Any]:
        project_root, _ = self._resolve_read_only_project_context(params)
        result = self.source_review.search_source(project_root, self._strip_project_name_param(params))
        if result.get("ok"):
            hint = params.get("project_name") is None
            return self._with_project_identity(result, project_root, hint_project_name=hint)
        raise MCPToolInputError(
            str(result.get("error_code") or "SOURCE_SEARCH_ERROR"),
            str(result.get("message") or "搜索源码失败。"),
        )

    def _tool_get_git_diff(self, params: dict[str, Any]) -> dict[str, Any]:
        project_root, _ = self._resolve_read_only_project_context(params)
        result = self.source_review.get_git_diff(project_root, self._strip_project_name_param(params))
        if result.get("ok"):
            hint = params.get("project_name") is None
            return self._with_project_identity(result, project_root, hint_project_name=hint)
        raise MCPToolInputError(
            str(result.get("error_code") or "GIT_DIFF_ERROR"),
            str(result.get("message") or "读取 git diff 失败。"),
        )

    def _tool_get_executor_inventory(self, params: dict[str, Any]) -> dict[str, Any]:
        result = load_executor_inventory(self.project_root)
        if result.get("ok"):
            return self._with_project_identity(result)
        raise MCPToolInputError(
            str(result.get("error_code") or "INVENTORY_ERROR"),
            str(result.get("message") or "读取执行器 inventory 失败。"),
        )

    def _tool_manage_executor_config(self, params: dict[str, Any]) -> dict[str, Any]:
        if params.get("project_name") is not None:
            return self._route_project_name_tool("manage_executor_config", params, require_managed=True)
        action_raw = params.get("action")
        action = action_raw.strip().lower() if isinstance(action_raw, str) else ""
        if action not in {
            "inspect_inventory",
            "probe_models_preview",
            "probe_models_apply",
            "set_default_profile_preview",
            "set_default_profile_apply",
        }:
            raise MCPToolInputError(
                "INVALID_ACTION",
                "action 必须是 inspect_inventory、probe_models_preview、probe_models_apply、set_default_profile_preview 或 set_default_profile_apply。",
            )
        manager = MCPExecutorConfigManager(self.project_root)
        result = manager.handle(action, params)
        self._record_workflow_if_needed("manage_executor_config", action, params, result)
        return result

    def _tool_manage_executor_workflow(self, params: dict[str, Any]) -> dict[str, Any]:
        if params.get("project_name") is not None:
            return self._route_project_name_tool("manage_executor_workflow", params, require_managed=True)

        action = params.get("action", "")
        project_path = params.get("project_root") or self.project_root
        provider = params.get("provider", "codex")
        model_raw = params.get("model")
        model = model_raw.strip() if isinstance(model_raw, str) else ""
        execution_mode = params.get("execution_mode", "run")
        preview_id = params.get("preview_id", "")
        max_diff_chars = self._bounded_int_param(params.get("max_diff_chars"), default=40000, minimum=1, maximum=80000)
        include_diff_summary = self._bool_param(params.get("include_diff_summary"), default=True)
        include_report_markdown = self._bool_param(params.get("include_report_markdown"), default=False)
        max_report_chars = self._bounded_int_param(params.get("max_report_chars"), default=30000, minimum=1, maximum=60000)
        reason_raw = params.get("reason")
        reason = reason_raw.strip() if isinstance(reason_raw, str) else ""
        executor_session_mode = params.get("executor_session_mode", "auto")
        max_iterations = self._bounded_int_param(params.get("max_iterations"), default=1, minimum=1, maximum=3)
        trusted_mode = self._bool_param(params.get("trusted_mode"), default=False)
        stop_on_acceptance_failure = self._bool_param(params.get("stop_on_acceptance_failure"), default=True)
        stop_on_scope_violation = self._bool_param(params.get("stop_on_scope_violation"), default=True)
        stop_on_diff_too_large = self._bool_param(params.get("stop_on_diff_too_large"), default=True)
        max_total_diff_chars = self._bounded_int_param(params.get("max_total_diff_chars"), default=80000, minimum=1, maximum=200000)
        allow_fix = self._bool_param(params.get("allow_fix"), default=False)
        allow_commit = self._bool_param(params.get("allow_commit"), default=False)
        run_id = params.get("run_id", "")
        poll_attempt_raw = params.get("poll_attempt")
        if poll_attempt_raw is not None:
            try:
                poll_attempt = int(poll_attempt_raw)
            except Exception:
                poll_attempt = 1
            if poll_attempt < 1:
                poll_attempt = 1
        else:
            poll_attempt = 1
        latest = self._bool_param(params.get("latest"), default=True)
        report_id = params.get("report_id", "")
        version = params.get("version", "")
        manual_fix_prompt_raw = params.get("manual_fix_prompt")
        manual_fix_prompt = manual_fix_prompt_raw.strip() if isinstance(manual_fix_prompt_raw, str) else ""
        validation_run_id = params.get("validation_run_id", "")
        section = params.get("section", "")
        include_markdown = self._bool_param(params.get("include_markdown"), default=False)
        max_chars = self._bounded_int_param(params.get("max_chars"), default=20000, minimum=1, maximum=60000)
        resolution = params.get("resolution", "")
        expected_head = params.get("expected_head", "")
        expected_branch = params.get("expected_branch", "")
        target_next_version = params.get("target_next_version", "")
        target_version = params.get("target_version", "")
        accepted_commit = params.get("accepted_commit", "")
        accepted_commit_subject = params.get("accepted_commit_subject", "")
        profile_id_raw = params.get("profile_id")
        profile_id = profile_id_raw.strip() if isinstance(profile_id_raw, str) else ""
        commit_files = params.get("commit_files") if isinstance(params.get("commit_files"), list) else []
        evidence_refs = params.get("evidence_refs") if isinstance(params.get("evidence_refs"), list) else []
        evidence_summary = params.get("evidence_summary", "")
        bindings = params.get("bindings") if isinstance(params.get("bindings"), list) else []
        if not isinstance(action, str) or not action.strip():
            return self._with_project_identity({
                "ok": False,
                "error_code": "ACTION_REQUIRED",
                "message": "action 不能为空。支持：preflight、run_once_preview、run_once、run_bounded_preview、run_bounded、get_audit_package、refresh_audit_package、recheck_report_preview、recheck_report_apply、manual_fix_prompt_preview、manual_fix_prompt_apply、manual_validation_preview、manual_validation_apply、scope_mismatch_preview、scope_mismatch_apply、state_lineage_reconciliation_preview、state_lineage_reconciliation_apply、final_version_closeout_preview、final_version_closeout_apply、status。",
            })
        manager = MCPExecutorWorkflowManager(project_path)
        workflow_params = {
            "provider": provider,
            "model": model,
            "execution_mode": execution_mode,
            "preview_id": preview_id,
            "max_diff_chars": max_diff_chars,
            "include_diff_summary": include_diff_summary,
            "include_report_markdown": include_report_markdown,
            "max_report_chars": max_report_chars,
            "reason": reason,
            "max_iterations": max_iterations,
            "trusted_mode": trusted_mode,
            "stop_on_acceptance_failure": stop_on_acceptance_failure,
            "stop_on_scope_violation": stop_on_scope_violation,
            "stop_on_diff_too_large": stop_on_diff_too_large,
            "max_total_diff_chars": max_total_diff_chars,
            "allow_fix": allow_fix,
            "allow_commit": allow_commit,
            "run_id": run_id,
            "poll_attempt": poll_attempt,
            "latest": latest,
            "report_id": report_id,
            "version": version,
            "manual_fix_prompt": manual_fix_prompt,
            "validation_run_id": validation_run_id,
            "section": section,
            "include_markdown": include_markdown,
            "max_chars": max_chars,
            "resolution": resolution,
            "expected_head": expected_head,
            "expected_branch": expected_branch,
            "target_next_version": target_next_version,
            "target_version": target_version,
            "accepted_commit": accepted_commit,
            "accepted_commit_subject": accepted_commit_subject,
            "profile_id": profile_id,
            "commit_files": commit_files,
            "evidence_refs": evidence_refs,
            "evidence_summary": evidence_summary,
            "bindings": bindings,
        }
        if action.strip().lower() == "run_once" or "executor_session_mode" in params:
            workflow_params["executor_session_mode"] = executor_session_mode
        result = manager.handle(action.strip().lower(), workflow_params)
        self._record_workflow_if_needed("manage_executor_workflow", action.strip().lower(), params, result)
        return self._with_project_identity(result)

    def _tool_manage_validation_run(self, params: dict[str, Any]) -> dict[str, Any]:
        action_raw = params.get("action")
        action = action_raw.strip().lower() if isinstance(action_raw, str) else ""
        if action not in {"inspect", "preview", "run", "status"}:
            raise MCPToolInputError(
                "INVALID_ACTION",
                "action 必须是 inspect、preview、run 或 status。",
            )
        if params.get("project_name") is not None:
            return self._route_project_name_tool("manage_validation_run", params, require_managed=True)
        manager = MCPValidationRunManager(self.project_root)
        result = manager.handle(action, params)
        self._record_workflow_if_needed("manage_validation_run", action, params, result)
        return self._with_project_identity(result)

    def _tool_manage_stage_parallel_worktrees(self, params: dict[str, Any]) -> dict[str, Any]:
        from runner.mcp_stage_parallel_worktrees import MCPStageParallelWorktreeManager

        action_raw = params.get("action")
        action = action_raw.strip().lower() if isinstance(action_raw, str) else ""
        if action not in {"preview", "apply", "status", "discard"}:
            raise MCPToolInputError(
                "INVALID_ACTION",
                "action 必须是 preview、apply、status 或 discard。",
            )
        if params.get("project_name") is not None:
            return self._route_project_name_tool("manage_stage_parallel_worktrees", params, require_managed=True)
        manager = MCPStageParallelWorktreeManager(self.project_root)
        result = manager.handle(action, params)
        self._record_workflow_if_needed("manage_stage_parallel_worktrees", action, params, result)
        return self._with_project_identity(result)

    def _tool_manage_stage_parallel_shard_inputs(self, params: dict[str, Any]) -> dict[str, Any]:
        from runner.mcp_stage_parallel_shard_inputs import MCPStageParallelShardInputManager

        action_raw = params.get("action")
        action = action_raw.strip().lower() if isinstance(action_raw, str) else ""
        if action not in {"preview", "apply", "status", "discard"}:
            raise MCPToolInputError(
                "INVALID_ACTION",
                "action 必须是 preview、apply、status 或 discard。",
            )
        if params.get("project_name") is not None:
            return self._route_project_name_tool("manage_stage_parallel_shard_inputs", params, require_managed=True)
        manager = MCPStageParallelShardInputManager(self.project_root)
        result = manager.handle(action, params)
        self._record_workflow_if_needed("manage_stage_parallel_shard_inputs", action, params, result)
        return self._with_project_identity(result)

    def _tool_manage_stage_parallel_executor_group(self, params: dict[str, Any]) -> dict[str, Any]:
        from runner.mcp_stage_parallel_executor_group import MCPStageParallelExecutorGroupManager

        action_raw = params.get("action")
        action = action_raw.strip().lower() if isinstance(action_raw, str) else ""
        if action not in {"preview", "apply", "status", "discard"}:
            raise MCPToolInputError(
                "INVALID_ACTION",
                "action 必须是 preview、apply、status 或 discard。",
            )
        if params.get("project_name") is not None:
            return self._route_project_name_tool("manage_stage_parallel_executor_group", params, require_managed=True)
        manager = MCPStageParallelExecutorGroupManager(self.project_root)
        result = manager.handle(action, params)
        self._record_workflow_if_needed("manage_stage_parallel_executor_group", action, params, result)
        return self._with_project_identity(result)

    def _tool_manage_stage_parallel_executor_runs(self, params: dict[str, Any]) -> dict[str, Any]:
        from runner.mcp_stage_parallel_executor_runs import MCPStageParallelExecutorRunGroupManager

        action_raw = params.get("action")
        action = action_raw.strip().lower() if isinstance(action_raw, str) else ""
        if action not in {"preview", "apply", "status", "discard"}:
            raise MCPToolInputError(
                "INVALID_ACTION",
                "action 必须是 preview、apply、status 或 discard。",
            )
        if params.get("project_name") is not None:
            return self._route_project_name_tool("manage_stage_parallel_executor_runs", params, require_managed=True)
        manager = MCPStageParallelExecutorRunGroupManager(self.project_root)
        result = manager.handle(action, params)
        self._record_workflow_if_needed("manage_stage_parallel_executor_runs", action, params, result)
        return self._with_project_identity(result)

    def _tool_manage_stage_parallel_merges(self, params: dict[str, Any]) -> dict[str, Any]:
        from runner.mcp_stage_parallel_merges import MCPStageParallelMergeManager

        action_raw = params.get("action")
        action = action_raw.strip().lower() if isinstance(action_raw, str) else ""
        if action not in {"preview", "apply", "status", "discard"}:
            raise MCPToolInputError(
                "INVALID_ACTION",
                "action 必须是 preview、apply、status 或 discard。",
            )
        if params.get("project_name") is not None:
            return self._route_project_name_tool("manage_stage_parallel_merges", params, require_managed=True)
        manager = MCPStageParallelMergeManager(self.project_root)
        result = manager.handle(action, params)
        self._record_workflow_if_needed("manage_stage_parallel_merges", action, params, result)
        return self._with_project_identity(result)

    def _create_mcp_workflow_router(self) -> MCPWorkflowRouter:
        return MCPWorkflowRouter(
            project_root=self.project_root,
            source_review=self.source_review,
            analyze_state_fn=self._tool_analyze_project_state,
            plan_workflow_manager=MCPPlanWorkflowManager(self.project_root, self.source_review),
            project_patch_manager=MCPProjectPatchManager(self.project_root, self.source_review),
            project_docs_manager=MCPProjectDocsManager(self.project_root, self.source_review),
            git_history_manager=MCPGitHistoryManager(self.project_root, self.source_review),
            git_commit_manager=MCPGitCommitManager(self.project_root),
        )

    def _tool_run_mcp_workflow(self, params: dict[str, Any]) -> dict[str, Any]:
        workflow = _normalize_run_mcp_workflow_name(params.get("workflow"))
        if workflow not in _SUPPORTED_MCP_WORKFLOWS:
            raise MCPToolInputError("INVALID_WORKFLOW", f"未知 workflow：{workflow}")
        project_name = params.get("project_name")
        if project_name is not None:
            return self._route_project_name_tool("run_mcp_workflow", params, require_managed=True)

        result = self._create_mcp_workflow_router().handle(workflow, params)
        self._record_workflow_if_needed("run_mcp_workflow", workflow, params, result)
        return result

    def _tool_list_workflow_runs(self, params: dict[str, Any]) -> dict[str, Any]:
        if params.get("project_name") is not None:
            return self._route_project_name_tool("list_workflow_runs", params, require_managed=True)
        limit = self._bounded_int_param(params.get("limit"), default=20, minimum=1, maximum=100)
        workflow_name_raw = params.get("workflow_name")
        workflow_name = workflow_name_raw.strip() if isinstance(workflow_name_raw, str) else None
        status_raw = params.get("status")
        status = status_raw.strip() if isinstance(status_raw, str) else None
        store = WorkflowRecordStore(self.project_root)
        return store.list_runs(limit=limit, workflow_name=workflow_name, status=status)

    def _tool_get_workflow_run(self, params: dict[str, Any]) -> dict[str, Any]:
        if params.get("project_name") is not None:
            return self._route_project_name_tool("get_workflow_run", params, require_managed=True)
        workflow_id = params.get("workflow_id")
        if not isinstance(workflow_id, str) or not workflow_id.strip():
            return {"ok": False, "error_code": "INVALID_WORKFLOW_ID", "message": "workflow_id 必须是非空字符串。"}
        store = WorkflowRecordStore(self.project_root)
        return store.get_run(workflow_id.strip())

    def _record_workflow_if_needed(self, tool_name: str, action: str, params: dict[str, Any], result: dict[str, Any]) -> str | None:
        if not should_record_tool(tool_name, action):
            return None
        if not isinstance(result, dict):
            return None
        ret = record_tool_call(self.project_root, tool_name, action, params, result)
        warning = ret.get("warning")
        if warning:
            existing = result.get("workflow_record_warning")
            if existing:
                result["workflow_record_warning"] = f"{existing}; {warning}"
            else:
                result["workflow_record_warning"] = warning
        wf_id = ret.get("workflow_id")
        if isinstance(wf_id, str) and wf_id.strip():
            result["workflow_id"] = wf_id.strip()
            return wf_id.strip()
        return None

    def _result(self, req_id: Any, result: dict[str, Any]) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    def _protocol_error(self, req_id: Any, code: int, error_code: str, message: str) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {
                "code": code,
                "message": message,
                "data": {"error_code": error_code},
            },
        }

    def _tool_error(self, tool: str, error_code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "ok": False,
            "tool": tool,
            "error_code": error_code,
            "message": message,
            "details": details or {},
        }

    def _parse_spec_json_or_legacy(self, params: dict[str, Any]) -> dict[str, Any]:
        spec: Any = None
        spec_json = params.get("spec_json")
        if isinstance(spec_json, str):
            try:
                spec = json.loads(spec_json)
            except Exception:
                raise MCPToolInputError(
                    "INVALID_SPEC_JSON",
                    "spec_json must be valid JSON",
                )
            if not isinstance(spec, dict):
                raise MCPToolInputError(
                    "INVALID_SPEC_JSON",
                    "spec_json must be valid JSON",
                )
            return spec
        if spec_json is not None:
            raise MCPToolInputError(
                "INVALID_SPEC_JSON",
                "spec_json must be a string",
            )
        legacy_spec = params.get("spec")
        if isinstance(legacy_spec, dict):
            spec = legacy_spec
        else:
            spec = params
        if not isinstance(spec, dict):
            raise MCPToolInputError(
                "INVALID_SPEC_JSON",
                "spec_json must be valid JSON",
            )
        return spec

    def _log(self, text: str) -> None:
        sys.stderr.write(text + "\n")
        sys.stderr.flush()
