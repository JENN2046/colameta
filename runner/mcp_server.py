import json
import copy
import threading
import os
import re
import secrets
import stat
import sys
import time
import hashlib
import hmac
import urllib.request
from collections import OrderedDict
from concurrent.futures import Future
from contextvars import ContextVar
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
from runner.continuation_snapshot import collect_continuation_snapshot
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
from runner.mcp_project_routing import (
    OPERATOR_TARGET_ISOLATED,
    TOOL_ROUTE_CONTINUATIONS,
    ProjectRouteContext,
    ProjectRouteServerFactory,
)
from runner.mcp_submission_evidence_revision import MCPSubmissionEvidenceRevisionManager
from runner.p1_release_evidence import P1ReleaseEvidenceManager
from runner.mcp_git_history import MCPGitHistoryManager
from runner.mcp_plan_workflow import MCPPlanWorkflowManager
from runner.mcp_project_docs import MCPProjectDocsManager
from runner.mcp_workflow_router import MCPWorkflowRouter
from runner.mcp_workflow_compatibility import (
    MCPWorkflowCompatibilityService,
    WorkflowCompatibilityError,
)
from runner.mcp_workflow_policy import (
    WORKFLOW_CONTEXT_MUTATION_PHASES,
    run_mcp_workflow_policy_scope,
)
from runner.mcp_gate_review_workflow import (
    GATE_REVIEW_WORKFLOW,
    GateReviewPreviewStore,
)
from runner.core_orchestrator import WorkflowOrchestrator
from runner.core_workflow_registry import SUPPORTED_CORE_WORKFLOWS, normalize_workflow_name, is_supported_core_workflow
from runner.mcp_executor_workflow import MCPExecutorWorkflowManager
from runner.mcp_executor_config import MCPExecutorConfigManager
from runner.mcp_manifest_validation import (
    MCPManifestValidationWorkflow,
    ManifestValidationWorkflowError,
)
from runner.mcp_review_manifest import (
    MCPReviewManifestResources,
    REVIEW_MANIFEST_URI_RE,
)
from runner.mcp_resources import (
    MCPResourcesService,
    RESULT_ARTIFACT_ID_RE,
    RESULT_ARTIFACT_RESOURCE_TEMPLATES,
    RESULT_ARTIFACT_URI_RE,
    RESULT_ARTIFACT_WORKFLOW,
    REVIEW_MANIFEST_RESOURCE_TEMPLATES,
)
from runner.mcp_tool_catalog import (
    MCPToolDef,
    _manage_stage_parallel_executor_group_input_schema,
    _manage_stage_parallel_executor_runs_input_schema,
    _manage_stage_parallel_merges_input_schema,
    _manage_stage_parallel_shard_inputs_input_schema,
    _manage_stage_parallel_worktrees_input_schema,
    _operation_context_binding_input_schema,
    _stage_parallel_preview_input_schema,
    apply_chatgpt_submission_tool_annotations,
    build_mcp_tool_definitions,
)
from runner.mcp_validation_run import MCPValidationRunManager
from runner.mcp_private_operator import (
    OPERATOR_DISPATCH_CAPABILITY,
    OperatorBatchService,
    OperatorPermitStore,
    OperatorSettingsStore,
    evaluate_operator_principal,
    operator_authenticated_request_scope,
)
from runner.mcp_result_artifacts import MCPResultArtifactStore, ResultArtifactHandle
from runner.current_facts_artifact import process_current_facts_preview_store
from runner.review_manifest import (
    REVIEW_MANIFEST_MAX_SUBJECTS,
    REVIEW_MANIFEST_WORKFLOW,
    ReviewManifestError,
    ReviewManifestHandle,
    ReviewManifestInspection,
    ReviewManifestStore,
    StoredReviewManifest,
    collect_review_context_binding,
    inspect_review_manifest,
    read_manifest_subject_file,
    read_stored_review_manifest_page,
    verify_stored_review_context,
    verify_stored_review_manifest,
)
from runner.project_context_binding import (
    PROJECT_CONTEXT_BINDING_SCHEMA_VERSION,
    ProjectContextBindingError,
    collect_project_context_binding,
    context_binding_sha256,
    require_operation_context_binding,
)
from runner.canonical_project_state import CANONICAL_PROJECT_STATE_SCHEMA_VERSION
from runner.operator_artifact_binding import canonical_artifact_digest
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
from runner.stable_promotion_evidence import MCPStablePromotionEvidenceManager
from runner.app_submission_work_items import AppSubmissionWorkItemCommands
from runner.commander_projections import CommanderProjectionService
from runner.commander_contract import (
    COMMANDER_RESPONSE_SCHEMA_VERSION,
    commander_public_error_code,
    commander_response_schema,
    validate_commander_response,
)
from runner.commander_widget import commander_widget_html
from runner.mcp_commander_app import (
    COMMANDER_APP_MANIFEST_VERSION,
    COMMANDER_APP_SERVER_INSTRUCTIONS,
    COMMANDER_APP_TITLE,
    COMMANDER_APP_WIDGET_MIME_TYPE,
    COMMANDER_APP_WIDGET_URI,
    MCPCommanderAppMixin,
)
from runner.mcp_commander_public import (
    COMMANDER_EXPOSED_TOOLS,
    COMMANDER_PUBLIC_RESPONSE_MINIMIZATION_VERSION as _COMMANDER_PUBLIC_RESPONSE_MINIMIZATION_VERSION,
    CommanderPublicProjector,
    commander_result_artifact_page_matches_binding,
)
from runner.stable_promotion_work_item import StablePromotionWorkItemReader
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
from runner.work_item_governance.errors import WorkItemGovernanceError
from runner.work_item_governance.request_context import (
    AuthenticatedTokenRequestProof,
    _AuthenticatedTokenListenerBoundary,
    _authenticated_token_listener_conformance_snapshot,
    _bind_authenticated_token_listener,
)
from runner.work_item_governance.activation import (
    ActivationLeaseControlPlane,
    process_tcp_listener_inventory,
    validate_authoritative_bearer_token,
    validate_runtime_policy_contracts,
)
from runner.work_item_governance.pilot import (
    PILOT_SCOPE_MODE,
    PILOT_TOOLS,
    PilotActivationControlPlane,
    measure_pilot_durable_token_binding,
    require_pilot_preflight_conformance_baseline,
)
from runner.work_item_governance.pilot_snapshot import PilotConformanceLedgerSnapshot
from runner.work_item_mcp_adapter import (
    AUTHORITATIVE_CANARY_MCP_TOOLS,
    WORK_ITEM_APPLY_TOOLS,
    WORK_ITEM_MCP_TOOLS,
    WORK_ITEM_PREVIEW_TOOLS,
    WORK_ITEM_READ_TOOLS,
    execute_work_item_mcp_command,
    work_item_mcp_tool_specs,
)
from runner.work_item_principal_adapter import (
    current_authenticated_token_request_proof,
    current_work_item_principal,
    principal_from_auth_context,
    work_item_authenticated_request_scope,
    work_item_principal_scope,
)
from runner.runner_paths import (
    is_project_runner_path,
    resolve_project_runner_dir,
    resolve_project_runner_path,
    resolve_project_runner_plan_path,
    resolve_project_runner_rel_dir,
)


MCPAuthContext = object | None


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
MCP_EXPOSURE_PROFILE_COMMANDER = "commander"
MCP_EXPOSURE_PROFILE_NORMAL = "normal"
MCP_EXPOSURE_PROFILE_MAINTAINER = "maintainer"
MCP_EXPOSURE_PROFILE_LEGACY = "legacy"
MCP_EXPOSURE_PROFILE_AUTHORITATIVE_CANARY = "authoritative_canary"
AUTHORITATIVE_CANARY_PRIVATE_CREDENTIAL_SOURCE = "isolated_xdg_auth_json"
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
MCP_MANAGE_FILES_READ_TARGET_CHARS = 24000
MCP_RESULT_ARTIFACT_TTL_SECONDS = _env_int(
    "COLAMETA_MCP_RESULT_ARTIFACT_TTL_SECONDS",
    900,
    minimum=60,
)
MCP_RESULT_ARTIFACT_PAGE_CHARS = 12000
MCP_RESULT_ARTIFACT_MAX_ITEMS = 64
COMMANDER_PUBLIC_RESULT_ARTIFACT_SAFETY_CACHE_MAX_ITEMS = (
    MCP_RESULT_ARTIFACT_MAX_ITEMS
)
COMMANDER_PUBLIC_ARTIFACT_SCAN_MAX_CHARS = 5_000_000
MCP_RESULT_ARTIFACT_WORKFLOW = RESULT_ARTIFACT_WORKFLOW
MCP_RESULT_ARTIFACT_ID_RE = RESULT_ARTIFACT_ID_RE
MCP_RESULT_ARTIFACT_URI_RE = RESULT_ARTIFACT_URI_RE
MCP_RESULT_ARTIFACT_RESOURCE_TEMPLATES = RESULT_ARTIFACT_RESOURCE_TEMPLATES
MCP_REVIEW_MANIFEST_TTL_SECONDS = _env_int(
    "COLAMETA_MCP_REVIEW_MANIFEST_TTL_SECONDS",
    900,
    minimum=60,
)
MCP_REVIEW_MANIFEST_MAX_ITEMS = 32
COMMANDER_PUBLIC_REVIEW_MANIFEST_SAFETY_CACHE_MAX_ITEMS = (
    MCP_REVIEW_MANIFEST_MAX_ITEMS * REVIEW_MANIFEST_MAX_SUBJECTS
)
MCP_REVIEW_MANIFEST_URI_RE = REVIEW_MANIFEST_URI_RE
MCP_REVIEW_MANIFEST_RESOURCE_TEMPLATES = REVIEW_MANIFEST_RESOURCE_TEMPLATES
COMMANDER_PUBLIC_RESPONSE_MINIMIZATION_VERSION = _COMMANDER_PUBLIC_RESPONSE_MINIMIZATION_VERSION
REMOTE_EXTERNAL_OAUTH_POLICY = "remote_public"
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
    "manage_submission_evidence_revision",
    "manage_p1_release_evidence",
    "init_submission_evidence",
    "fill_submission_evidence_files",
    "mark_submission_evidence_ready_fields",
    "record_product_console_action_result",
    "get_commander_app_manifest",
    "render_commander_app",
    "get_apps_connector_smoke_packet",
    "get_stable_replacement_cadence",
    "get_stable_promotion_readiness",
    "manage_stable_promotion_evidence",
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
    "review_manifest",
    "read_result_artifact",
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
) + WORK_ITEM_MCP_TOOLS

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
    MCP_EXPOSURE_PROFILE_COMMANDER: COMMANDER_EXPOSED_TOOLS,
    MCP_EXPOSURE_PROFILE_NORMAL: NORMAL_EXPOSED_TOOLS,
    MCP_EXPOSURE_PROFILE_MAINTAINER: NORMAL_EXPOSED_TOOLS + MAINTAINER_EXTRA_TOOLS,
    MCP_EXPOSURE_PROFILE_LEGACY: NORMAL_EXPOSED_TOOLS + MAINTAINER_EXTRA_TOOLS + LEGACY_EXTRA_TOOLS,
    MCP_EXPOSURE_PROFILE_AUTHORITATIVE_CANARY: AUTHORITATIVE_CANARY_MCP_TOOLS,
}


_SUPPORTED_MCP_WORKFLOWS = SUPPORTED_CORE_WORKFLOWS

_OPERATOR_BATCH_INTERNAL_DISPATCH: ContextVar[bool] = ContextVar(
    "operator_batch_internal_dispatch",
    default=False,
)
_CURRENT_FACTS_INTERNAL_ANALYZE: ContextVar[bool] = ContextVar(
    "current_facts_internal_analyze",
    default=False,
)
_COMMANDER_PUBLIC_REQUEST: ContextVar[bool] = ContextVar(
    "commander_public_request",
    default=False,
)
_normalize_run_mcp_workflow_name = normalize_workflow_name




def _find_action_list(result: dict[str, Any], key: str) -> list[dict[str, Any]] | None:
    actions = result.get(key)
    if isinstance(actions, list):
        return actions
    data = result.get("data")
    if isinstance(data, dict):
        actions = data.get(key)
        if isinstance(actions, list):
            return actions
    return None


def _find_action(result: dict[str, Any], key: str) -> dict[str, Any] | None:
    """Extract a singular action field from flat or data-wrapped tool results."""
    action = result.get(key)
    if isinstance(action, dict):
        return action
    data = result.get("data")
    if isinstance(data, dict):
        action = data.get(key)
        if isinstance(action, dict):
            return action
    return None


def _inject_project_name_into_action(action: dict[str, Any], project_name: str) -> None:
    for key in ("arguments", "params"):
        action_params = action.get(key)
        if isinstance(action_params, dict) and "project_name" not in action_params:
            action_params["project_name"] = project_name


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














PROJECT_NAME_REQUIRED_TOOLS = {
    "get_agent_operator_flow_packet",
    "get_product_readiness_status",
    "get_chatgpt_app_readiness",
    "get_full_loop_authority_status",
    "get_product_console_map",
    "get_release_submission_readiness",
    "get_submission_evidence_fill_preview",
    "get_submission_evidence_auto_draft",
    "manage_submission_evidence_revision",
    "manage_p1_release_evidence",
    "init_submission_evidence",
    "fill_submission_evidence_files",
    "mark_submission_evidence_ready_fields",
    "record_product_console_action_result",
    "get_commander_app_manifest",
    "render_commander_app",
    "get_apps_connector_smoke_packet",
    "get_stable_replacement_cadence",
    "get_stable_promotion_readiness",
    "manage_stable_promotion_evidence",
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
    *WORK_ITEM_MCP_TOOLS,
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
            return run_mcp_workflow_policy_scope(params)
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
        "review_manifest",
        "read_result_artifact",
        "list_workflow_runs",
        "get_workflow_run",
    }
    policies = {name: _static_policy(name, "mcp:read") for name in read_tools}
    policies.update({name: _static_policy(name, "mcp:read") for name in WORK_ITEM_READ_TOOLS})
    policies.update({name: _static_policy(name, "mcp:preview") for name in WORK_ITEM_PREVIEW_TOOLS})
    policies.update({name: _static_policy(name, "mcp:commit") for name in WORK_ITEM_APPLY_TOOLS})
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
            "manage_stable_promotion_evidence": _action_policy(
                "manage_stable_promotion_evidence",
                {
                    "inspect": "mcp:read",
                    "status": "mcp:read",
                    "preview": "mcp:preview",
                    "discard": "mcp:preview",
                    "apply": "mcp:commit",
                },
            ),
        }
    )
    policies["manage_submission_evidence_revision"] = _action_policy(
        "manage_submission_evidence_revision",
        {
            "status": "mcp:read",
            "preview": "mcp:preview",
            "discard": "mcp:preview",
            "apply": "mcp:commit",
        },
    )
    policies["manage_p1_release_evidence"] = _action_policy(
        "manage_p1_release_evidence",
        {
            "inspect": "mcp:read",
            "status": "mcp:read",
            "preview": "mcp:preview",
            "discard": "mcp:preview",
            "apply": "mcp:commit",
        },
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


@dataclass(frozen=True)
class _CommanderResultArtifactPageBinding:
    artifact_id: str
    page: int
    page_count: int
    page_char_start: int
    page_char_end: int
    content_sha256: str
    expires_at: str
    page_content_sha256: str

    def as_projection_binding(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "page": self.page,
            "page_count": self.page_count,
            "page_char_start": self.page_char_start,
            "page_char_end": self.page_char_end,
            "content_sha256": self.content_sha256,
            "expires_at": self.expires_at,
            "page_content_sha256": self.page_content_sha256,
        }


@dataclass(frozen=True)
class _CommanderResultArtifactSafetyVerdict:
    safe: bool
    pages: tuple[_CommanderResultArtifactPageBinding, ...] = ()

    def page_binding(
        self,
        page: int,
    ) -> _CommanderResultArtifactPageBinding | None:
        if not self.safe or page < 1 or page > len(self.pages):
            return None
        binding = self.pages[page - 1]
        if binding.page != page:
            return None
        return binding


class MCPPlanningBridgeServer(MCPCommanderAppMixin):
    def __init__(
        self,
        project_path: str,
        *,
        service_mode: bool = False,
        exposure_profile: str | None = None,
        work_item_scope_mode: str | None = None,
    ):
        self.project_root = os.path.abspath(os.path.expanduser(project_path))
        self.service_mode = service_mode
        self.project_registry = ProjectRegistry()
        self.mcp_exposure_profile = self._get_exposure_profile(exposure_profile)
        self.work_item_scope_mode = work_item_scope_mode
        if work_item_scope_mode not in {None, PILOT_SCOPE_MODE}:
            raise PlanningBridgeError(f"Unsupported Work Item scope mode: {work_item_scope_mode}")
        if work_item_scope_mode == PILOT_SCOPE_MODE and self.mcp_exposure_profile != MCP_EXPOSURE_PROFILE_AUTHORITATIVE_CANARY:
            raise PlanningBridgeError("bounded Pilot scope requires the authoritative_canary exposure profile.")
        self._token_transport_proof_validator = None
        self._preflight_conformance_only = False
        self._preflight_conformance_ledger_snapshot_binding_digest: str | None = None
        self._mcp_result_artifact_store = MCPResultArtifactStore(
            ttl_seconds=MCP_RESULT_ARTIFACT_TTL_SECONDS,
            page_chars=MCP_RESULT_ARTIFACT_PAGE_CHARS,
            max_items=MCP_RESULT_ARTIFACT_MAX_ITEMS,
        )
        self._commander_public_result_artifact_safety_cache: OrderedDict[
            tuple[str, str], _CommanderResultArtifactSafetyVerdict
        ] = OrderedDict()
        self._commander_public_result_artifact_safety_inflight: dict[
            tuple[str, str], Future[_CommanderResultArtifactSafetyVerdict]
        ] = {}
        self._commander_public_result_artifact_safety_cache_lock = (
            threading.Lock()
        )
        self._gate_review_preview_store = GateReviewPreviewStore()
        self._current_facts_preview_store = process_current_facts_preview_store()
        self._review_manifest_store = ReviewManifestStore(
            ttl_seconds=MCP_REVIEW_MANIFEST_TTL_SECONDS,
            max_items=MCP_REVIEW_MANIFEST_MAX_ITEMS,
        )
        self._commander_public_review_manifest_safety_cache: OrderedDict[
            str, bool
        ] = OrderedDict()
        self._commander_public_review_manifest_safety_inflight: dict[
            str, Future[bool]
        ] = {}
        self._commander_public_review_manifest_safety_cache_lock = (
            threading.Lock()
        )
        self._project_route_server_factory = ProjectRouteServerFactory(self)
        self.bridge = PlanningBridge()
        self.source_review = SourceReviewBridge()
        if self.service_mode:
            self.project_identity = {"service": "colameta-mcp", "routing": "registry"}
            self.project_hint = "ColaMeta Service"
        else:
            self.project_identity = build_project_identity(self.project_root)
            self.project_hint = self.project_identity.get("mcp_display_hint", f"Project:{os.path.basename(self.project_root)}")
        common_output_schema = self._build_common_output_schema()
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
            "manage_submission_evidence_revision": self._tool_manage_submission_evidence_revision,
            "manage_p1_release_evidence": self._tool_manage_p1_release_evidence,
            "init_submission_evidence": self._tool_init_submission_evidence,
            "fill_submission_evidence_files": self._tool_fill_submission_evidence_files,
            "mark_submission_evidence_ready_fields": self._tool_mark_submission_evidence_ready_fields,
            "record_product_console_action_result": self._tool_record_product_console_action_result,
            "get_commander_app_manifest": self._tool_get_commander_app_manifest,
            "render_commander_app": self._tool_render_commander_app,
            "get_apps_connector_smoke_packet": self._tool_get_apps_connector_smoke_packet,
            "get_stable_replacement_cadence": self._tool_get_stable_replacement_cadence,
            "get_stable_promotion_readiness": self._tool_get_stable_promotion_readiness,
            "manage_stable_promotion_evidence": self._tool_manage_stable_promotion_evidence,
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
            "review_manifest": self._tool_review_manifest_entry,
            "read_result_artifact": self._tool_read_result_artifact,
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
        self.tools.update(
            {
                name: (lambda params, command_name=name: self._tool_work_item_command(command_name, params))
                for name in WORK_ITEM_MCP_TOOLS
            }
        )
        self.tool_defs = build_mcp_tool_definitions(
            self,
            common_output_schema,
            commander_widget_uri=COMMANDER_APP_WIDGET_URI,
        )
        self.tool_defs.extend(self._work_item_tool_definitions(common_output_schema))
        if self.mcp_exposure_profile == MCP_EXPOSURE_PROFILE_COMMANDER:
            commander_output_schema = self._build_commander_output_schema()
            for tool_def in self.tool_defs:
                if tool_def.name in COMMANDER_EXPOSED_TOOLS:
                    tool_def.output_schema = copy.deepcopy(commander_output_schema)
        apply_chatgpt_submission_tool_annotations(self.tool_defs)
        if self.mcp_exposure_profile == MCP_EXPOSURE_PROFILE_AUTHORITATIVE_CANARY:
            if self.work_item_scope_mode != PILOT_SCOPE_MODE:
                validate_runtime_policy_contracts()
            expected_tools = (
                PILOT_TOOLS
                if self.work_item_scope_mode == PILOT_SCOPE_MODE
                else AUTHORITATIVE_CANARY_MCP_TOOLS
            )
            actual = tuple(tool.name for tool in self._filter_tools_by_exposure_profile(self.tool_defs))
            if actual != expected_tools:
                raise PlanningBridgeError(
                    "authoritative_canary tool definition set differs from the frozen exact allowlist."
                )
            missing_dispatch_handlers = tuple(
                name for name in expected_tools if not callable(self.tools.get(name))
            )
            if missing_dispatch_handlers:
                raise PlanningBridgeError(
                    "authoritative_canary dispatch handlers differ from the frozen exact allowlist: "
                    + ", ".join(missing_dispatch_handlers)
                )

    def _work_item_tool_definitions(self, output_schema: dict[str, Any]) -> list[MCPToolDef]:
        return [
            MCPToolDef(output_schema=output_schema, **spec)
            for spec in work_item_mcp_tool_specs(
                self.project_hint,
                authoritative_canary=(
                    self.mcp_exposure_profile == MCP_EXPOSURE_PROFILE_AUTHORITATIVE_CANARY
                ),
                bounded_single_project_pilot=(self.work_item_scope_mode == PILOT_SCOPE_MODE),
            )
        ]

    def _tool_work_item_command(self, name: str, params: dict[str, Any]) -> dict[str, Any]:
        authoritative_canary = (
            self.mcp_exposure_profile == MCP_EXPOSURE_PROFILE_AUTHORITATIVE_CANARY
        )
        bounded_pilot = self.work_item_scope_mode == PILOT_SCOPE_MODE
        if authoritative_canary and params.get("project_name") is not None:
            raise MCPToolInputError(
                "ACTIVATION_PROJECT_ROUTING_DENIED",
                "The Authoritative Canary endpoint is bound to one exact project and forbids routing overrides.",
            )
        if params.get("project_name") is not None:
            return self._route_project_name_tool(
                name,
                params,
                require_managed=name not in WORK_ITEM_READ_TOOLS,
            )
        clean = self._strip_project_name_param(params)
        try:
            return execute_work_item_mcp_command(
                self.project_root,
                name,
                clean,
                principal_context=current_work_item_principal(),
                # The authoritative-canary exposure profile is the transport
                # boundary for both compositions.  A bounded Pilot must select
                # only the Pilot service/guard composition; passing both flags
                # is an explicit fail-closed conflict in the application
                # service and rejects every otherwise valid Pilot command.
                authoritative_canary=authoritative_canary and not bounded_pilot,
                bounded_single_project_pilot=bounded_pilot,
                authenticated_request_proof=current_authenticated_token_request_proof(),
            )
        except WorkItemGovernanceError as exc:
            raise MCPToolInputError(exc.code, str(exc), exc.details) from exc

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
        if self.mcp_exposure_profile == MCP_EXPOSURE_PROFILE_AUTHORITATIVE_CANARY:
            raise PlanningBridgeError(
                "authoritative_canary requires the Token-authenticated loopback HTTP transport."
            )
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

    def _pilot_http_conformance_snapshot(self) -> dict[str, Any]:
        if (
            self.mcp_exposure_profile != MCP_EXPOSURE_PROFILE_AUTHORITATIVE_CANARY
            or self.work_item_scope_mode != PILOT_SCOPE_MODE
            or not callable(self._token_transport_proof_validator)
            or getattr(self, "_httpd", None) is None
        ):
            raise PlanningBridgeError("Pilot conformance requires the exact active authenticated MCP listener.")
        snapshot = _authenticated_token_listener_conformance_snapshot(self)
        snapshot["preflight_conformance_only"] = bool(self._preflight_conformance_only)
        snapshot["ledger_snapshot_binding_digest"] = (
            self._preflight_conformance_ledger_snapshot_binding_digest
        )
        snapshot["server_binding_digest"] = hashlib.sha256(
            json.dumps(
                {
                    "project_root": self.project_root,
                    "scope_mode": self.work_item_scope_mode,
                    "exposure_profile": self.mcp_exposure_profile,
                    "preflight_conformance_only": bool(self._preflight_conformance_only),
                    "ledger_snapshot_binding_digest": (
                        self._preflight_conformance_ledger_snapshot_binding_digest
                    ),
                    "listener_instance_nonce": snapshot["listener_instance_nonce"],
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return snapshot

    def serve_http(
        self,
        host: str = "127.0.0.1",
        port: int = 8765,
        auth_token: str | None = None,
        auth_token_source: str | None = None,
        auth_token_file_sha256: str | None = None,
        auth_token_evidence_digest: str | None = None,
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
        activation_control_plane: ActivationLeaseControlPlane | PilotActivationControlPlane | None = None,
        activation_lease_id: str | None = None,
        activation_envelope_path: str | None = None,
        claimed_activation_envelope_path: str | None = None,
        preflight_conformance: bool = False,
        preflight_conformance_timeout_seconds: float = 120.0,
        preflight_conformance_ledger_snapshot: PilotConformanceLedgerSnapshot | None = None,
    ) -> int:
        server = self
        _debug_counter = 0
        resolved_auth_mode = auth_mode or ("token" if auth_token else "none")
        authoritative_canary = (
            self.mcp_exposure_profile == MCP_EXPOSURE_PROFILE_AUTHORITATIVE_CANARY
        )
        preflight_conformance_only = bool(preflight_conformance)
        if preflight_conformance_only and (
            not authoritative_canary or self.work_item_scope_mode != PILOT_SCOPE_MODE
        ):
            raise PlanningBridgeError(
                "preflight_conformance requires the exact bounded authoritative Pilot profile."
            )
        if preflight_conformance_only and (
            isinstance(preflight_conformance_timeout_seconds, bool)
            or not isinstance(preflight_conformance_timeout_seconds, (int, float))
            or not 0 < float(preflight_conformance_timeout_seconds) <= 120
        ):
            raise PlanningBridgeError(
                "preflight_conformance timeout must be greater than zero and at most 120 seconds."
            )
        if authoritative_canary:
            if host != "127.0.0.1":
                raise PlanningBridgeError("authoritative_canary must bind exactly 127.0.0.1.")
            if resolved_auth_mode != "token" or not auth_token:
                raise PlanningBridgeError("authoritative_canary requires private Bearer Token authentication.")
            if auth_token_source != AUTHORITATIVE_CANARY_PRIVATE_CREDENTIAL_SOURCE:
                raise PlanningBridgeError(
                    "authoritative_canary Token must be loaded from isolated 0600 XDG auth.json."
                )
            if not (
                isinstance(auth_token_file_sha256, str)
                and re.fullmatch(r"[0-9a-f]{64}", auth_token_file_sha256)
                and isinstance(auth_token_evidence_digest, str)
                and re.fullmatch(r"[0-9a-f]{64}", auth_token_evidence_digest)
            ):
                raise PlanningBridgeError(
                    "authoritative_canary requires exact Ledger-bound Token evidence digests."
                )
            try:
                validate_authoritative_bearer_token(auth_token)
            except WorkItemGovernanceError as exc:
                raise PlanningBridgeError(
                    "authoritative_canary token must match the exact bound 256-bit CSPRNG format."
                ) from exc
            if public_base_url is not None or debug_actions:
                raise PlanningBridgeError(
                    "authoritative_canary forbids public/actions configuration."
                )
            if preflight_conformance_only:
                if any(
                    value is not None
                    for value in (
                        activation_control_plane,
                        activation_lease_id,
                        activation_envelope_path,
                        claimed_activation_envelope_path,
                    )
                ):
                    raise PlanningBridgeError(
                        "preflight_conformance forbids Activation Lease inputs."
                    )
                if not isinstance(
                    preflight_conformance_ledger_snapshot,
                    PilotConformanceLedgerSnapshot,
                ):
                    raise PlanningBridgeError(
                        "preflight_conformance requires one governed isolated Ledger snapshot."
                    )
                try:
                    preflight_conformance_ledger_snapshot.require_bound_to(self.project_root)
                    snapshot_project_root = preflight_conformance_ledger_snapshot.project_root
                    require_pilot_preflight_conformance_baseline(snapshot_project_root)
                    durable_token_binding = measure_pilot_durable_token_binding(snapshot_project_root)
                    preflight_conformance_ledger_snapshot.require_bound_to(self.project_root)
                except WorkItemGovernanceError as exc:
                    raise PlanningBridgeError(
                        "preflight_conformance isolated Ledger snapshot validation failed."
                    ) from exc
                if durable_token_binding != {
                    "authoritative_canary_token_file_sha256": auth_token_file_sha256,
                    "authoritative_canary_token_evidence_digest": auth_token_evidence_digest,
                }:
                    raise PlanningBridgeError(
                        "preflight_conformance Token evidence differs from the durable Ledger binding."
                    )
            elif (
                activation_control_plane is None
                or not activation_lease_id
                or not activation_envelope_path
                or not claimed_activation_envelope_path
            ):
                raise PlanningBridgeError(
                    "authoritative_canary requires its one-shot Activation Lease control-plane claim."
                )
        if resolved_auth_mode not in {"none", "token", "oauth", "external-oauth"}:
            raise PlanningBridgeError(f"auth_mode 无效：{resolved_auth_mode}")
        if resolved_auth_mode == "token" and not auth_token:
            raise PlanningBridgeError("token auth mode requires auth_token.")
        if resolved_auth_mode == "token" and self._token_transport_proof_validator is not None:
            raise PlanningBridgeError("This MCP server already owns an active Token listener boundary.")
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
        listener_dispatch_context: ContextVar[object | None] = ContextVar(
            f"colameta_token_listener_{id(self)}_{id(object())}",
            default=None,
        )
        listener_proof_boundary: _AuthenticatedTokenListenerBoundary | None = None
        resolved_token_file_sha256 = auth_token_file_sha256 or hashlib.sha256(
            f"non-authoritative-token-file:{auth_token or ''}".encode("utf-8")
        ).hexdigest()
        resolved_token_evidence_digest = auth_token_evidence_digest or hashlib.sha256(
            f"non-authoritative-token-evidence:{auth_token or ''}".encode("utf-8")
        ).hexdigest()
        resolved_proof_lease_id = activation_lease_id or (
            "pilot-preflight-conformance"
            if preflight_conformance_only
            else "non-authoritative-token-listener"
        )

        def _validate_listener_token_proof(candidate: object) -> bool:
            if type(candidate) is not AuthenticatedTokenRequestProof:
                return False
            if listener_dispatch_context.get() is not candidate:
                return False
            proof = candidate
            if (
                proof.lease_id != resolved_proof_lease_id
                or proof.token_file_sha256 != resolved_token_file_sha256
                or proof.token_evidence_digest != resolved_token_evidence_digest
                or listener_proof_boundary is None
                or not listener_proof_boundary.is_active(proof)
            ):
                return False
            return proof.verify_signature(auth_token or "")

        def _mint_listener_token_proof() -> AuthenticatedTokenRequestProof:
            if listener_proof_boundary is None:
                raise PlanningBridgeError("Token listener proof boundary is unavailable.")
            return listener_proof_boundary.issue()

        def _activate_listener_token_proof(candidate: object) -> None:
            if type(candidate) is not AuthenticatedTokenRequestProof:
                return
            proof = candidate
            if (
                proof.lease_id == resolved_proof_lease_id
                and proof.token_file_sha256 == resolved_token_file_sha256
                and proof.token_evidence_digest == resolved_token_evidence_digest
                and proof.verify_signature(auth_token or "")
                and listener_proof_boundary is not None
            ):
                listener_proof_boundary.activate(proof)

        def _retire_listener_token_proof(candidate: object) -> None:
            if listener_proof_boundary is not None:
                listener_proof_boundary.retire(candidate)

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
                if (
                    authoritative_canary
                    and server.work_item_scope_mode == PILOT_SCOPE_MODE
                    and listener_proof_boundary is not None
                ):
                    listener_snapshot = server._pilot_http_conformance_snapshot()
                    self.send_header(
                        "X-ColaMeta-Listener-Instance",
                        str(listener_snapshot["listener_instance_nonce"]),
                    )
                    self.send_header(
                        "X-ColaMeta-Server-Binding",
                        str(listener_snapshot["server_binding_digest"]),
                    )
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

            def _auth_context(self) -> MCPAuthContext:
                if resolved_auth_mode == "none":
                    return {"mode": "none"}
                authorization = self.headers.get("Authorization", "")
                if resolved_auth_mode == "token":
                    if not authorization.startswith("Bearer "):
                        return None
                    token = authorization[len("Bearer ") :]
                    if not hmac.compare_digest(token, auth_token):
                        return None
                    return _mint_listener_token_proof()
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
                    if authoritative_canary:
                        self._send_json(
                            404,
                            {"ok": False, "error_code": "ACTIONS_DISABLED", "message": "Actions are disabled."},
                        )
                        return
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
                    if authoritative_canary:
                        self._send_json(
                            404,
                            {"ok": False, "error_code": "ACTIONS_DISABLED", "message": "Actions are disabled."},
                        )
                        return
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
                    _activate_listener_token_proof(auth_context)
                    dispatch_token = listener_dispatch_context.set(auth_context)
                    try:
                        tool_result = server._call_tool(
                            tool_name,
                            arguments,
                            auth_context=auth_context,
                        )
                    finally:
                        listener_dispatch_context.reset(dispatch_token)
                        _retire_listener_token_proof(auth_context)
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
                _activate_listener_token_proof(auth_context)
                dispatch_token = listener_dispatch_context.set(auth_context)
                try:
                    response = server._handle_jsonrpc_request(
                        request,
                        auth_context=auth_context,
                    )
                finally:
                    listener_dispatch_context.reset(dispatch_token)
                    _retire_listener_token_proof(auth_context)
                if response is None:
                    self.send_response(202)
                    self.send_header("Content-Length", "0")
                    self.send_header("X-Request-Id", self._request_id())
                    self.end_headers()
                    return
                self._send_json(200, response)

        claimed = False
        active = False
        if authoritative_canary and not preflight_conformance_only:
            if (
                activation_control_plane is None
                or activation_lease_id is None
                or activation_envelope_path is None
                or claimed_activation_envelope_path is None
            ):
                raise PlanningBridgeError(
                    "authoritative_canary Activation Lease claim inputs became unavailable."
                )
            activation_control_plane.claim_prepared_lease(
                lease_id=activation_lease_id,
                envelope_path=activation_envelope_path,
                claimed_envelope_path=claimed_activation_envelope_path,
            )
            claimed = True
        try:
            httpd = ReusableThreadingHTTPServer((host, port), MCPHTTPRequestHandler)
        except Exception:
            if claimed and activation_control_plane is not None and activation_lease_id is not None:
                activation_control_plane.revoke(
                    lease_id=activation_lease_id,
                    reason="listener_bind_failed_after_claim",
                )
            raise
        self._httpd = httpd
        self._preflight_conformance_only = preflight_conformance_only
        self._preflight_conformance_ledger_snapshot_binding_digest = (
            preflight_conformance_ledger_snapshot.binding_digest
            if preflight_conformance_only
            and isinstance(preflight_conformance_ledger_snapshot, PilotConformanceLedgerSnapshot)
            else None
        )
        if authoritative_canary and not preflight_conformance_only:
            if activation_control_plane is None or activation_lease_id is None:
                httpd.server_close()
                raise PlanningBridgeError(
                    "authoritative_canary listener attestation inputs became unavailable."
                )
            try:
                bound_port = int(httpd.server_address[1])
                activation_control_plane.attest_listener(
                    lease_id=activation_lease_id,
                    bind_address=host,
                    port=bound_port,
                    observed_listeners=process_tcp_listener_inventory(),
                )
                active = True
            except Exception:
                httpd.server_close()
                if claimed:
                    try:
                        activation_control_plane.revoke(
                            lease_id=activation_lease_id,
                            reason="listener_attestation_failed",
                        )
                    except WorkItemGovernanceError:
                        pass
                raise
        installed_token_validator = False
        preflight_timeout: threading.Timer | None = None
        try:
            if resolved_auth_mode == "token":
                listener_proof_boundary = _bind_authenticated_token_listener(
                    owner=self,
                    httpd=httpd,
                    auth_token=auth_token or "",
                    lease_id=resolved_proof_lease_id,
                    token_file_sha256=resolved_token_file_sha256,
                    token_evidence_digest=resolved_token_evidence_digest,
                )
                self._token_transport_proof_validator = _validate_listener_token_proof
                installed_token_validator = True
            if preflight_conformance_only:
                preflight_timeout = threading.Timer(
                    float(preflight_conformance_timeout_seconds),
                    httpd.shutdown,
                )
                preflight_timeout.name = "colameta-pilot-preflight-conformance-timeout"
                preflight_timeout.daemon = True
                preflight_timeout.start()
            httpd.serve_forever()
        except KeyboardInterrupt:
            self._log("MCP HTTP server interrupted")
        finally:
            if preflight_timeout is not None:
                preflight_timeout.cancel()
            httpd.shutdown()
            httpd.server_close()
            if listener_proof_boundary is not None:
                listener_proof_boundary.close()
            if (
                installed_token_validator
                and self._token_transport_proof_validator
                is _validate_listener_token_proof
            ):
                self._token_transport_proof_validator = None
            self._preflight_conformance_only = False
            self._preflight_conformance_ledger_snapshot_binding_digest = None
            if (
                authoritative_canary
                and not preflight_conformance_only
                and active
                and activation_control_plane is not None
                and activation_lease_id is not None
            ):
                try:
                    activation_control_plane.freeze(
                        lease_id=activation_lease_id,
                        reason="endpoint_stopped",
                    )
                except WorkItemGovernanceError:
                    pass
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


    def _mcp_resources_service(self) -> MCPResourcesService:
        """Compose read-only resource contracts over this server's local stores."""

        return MCPResourcesService(
            result_artifact_store=self._mcp_result_artifact_store,
            review_manifest_store=self._review_manifest_store,
            commander_widget_uri=COMMANDER_APP_WIDGET_URI,
            commander_app_title=COMMANDER_APP_TITLE,
            commander_widget_mime_type=COMMANDER_APP_WIDGET_MIME_TYPE,
            commander_widget_html_reader=self._commander_widget_html,
            commander_widget_meta_reader=self._commander_widget_resource_meta,
        )

    @staticmethod
    def _mcp_result_artifact_uri(artifact_id: str, page: int | None = None) -> str:
        return MCPResourcesService.result_artifact_uri(artifact_id, page)

    @staticmethod
    def _parse_mcp_result_artifact_uri(uri: str) -> tuple[str, int] | None:
        return MCPResourcesService.parse_result_artifact_uri(uri)

    def _store_packaged_result_artifact(
        self,
        tool_name: str,
        structured_tool_result: dict[str, Any],
    ) -> dict[str, Any] | None:
        if _COMMANDER_PUBLIC_REQUEST.get():
            public_payload = self._commander_public_projector().sanitize_for_artifact(
                structured_tool_result
            )
            if not isinstance(public_payload, dict):
                return None
            structured_tool_result = public_payload
        return self._mcp_resources_service().store_packaged_result_artifact(
            tool_name,
            structured_tool_result,
        )

    def _result_artifact_manifest_fields(
        self,
        handle: ResultArtifactHandle,
    ) -> dict[str, Any]:
        return self._mcp_resources_service().result_artifact_manifest_fields(handle)

    def _commander_public_result_artifact_preflight(
        self,
        artifact_id: str,
    ) -> _CommanderResultArtifactSafetyVerdict | None:
        """Check and bind the complete stored JSON payload before page reads."""

        first = self._mcp_result_artifact_store.read_page(artifact_id, 1)
        if first is None:
            return None
        cache_key = (artifact_id, first.content_sha256)
        owns_scan = False
        with self._commander_public_result_artifact_safety_cache_lock:
            cached = self._commander_public_result_artifact_safety_cache.get(
                cache_key
            )
            if cached is not None:
                self._commander_public_result_artifact_safety_cache.move_to_end(
                    cache_key
                )
                return cached
            flight = (
                self._commander_public_result_artifact_safety_inflight.get(
                    cache_key
                )
            )
            if flight is None:
                flight = Future()
                self._commander_public_result_artifact_safety_inflight[
                    cache_key
                ] = flight
                owns_scan = True
        if not owns_scan:
            return flight.result()

        def scan_complete_payload() -> _CommanderResultArtifactSafetyVerdict:
            pages: list[str] = []
            page_bindings: list[_CommanderResultArtifactPageBinding] = []
            total_chars = 0
            for page_number in range(1, first.page_count + 1):
                page = self._mcp_result_artifact_store.read_page(
                    artifact_id,
                    page_number,
                )
                if (
                    page is None
                    or page.artifact_id != artifact_id
                    or page.page != page_number
                    or page.content_sha256 != first.content_sha256
                    or page.page_count != first.page_count
                    or page.expires_at != first.expires_at
                    or page.page_char_start != total_chars
                    or page.page_char_end
                    != total_chars + len(page.content)
                ):
                    return _CommanderResultArtifactSafetyVerdict(False)
                page_bindings.append(
                    _CommanderResultArtifactPageBinding(
                        artifact_id=artifact_id,
                        page=page_number,
                        page_count=page.page_count,
                        page_char_start=page.page_char_start,
                        page_char_end=page.page_char_end,
                        content_sha256=page.content_sha256,
                        expires_at=page.expires_at,
                        page_content_sha256=hashlib.sha256(
                            page.content.encode("utf-8")
                        ).hexdigest(),
                    )
                )
                total_chars += len(page.content)
                if total_chars > COMMANDER_PUBLIC_ARTIFACT_SCAN_MAX_CHARS:
                    return _CommanderResultArtifactSafetyVerdict(False)
                pages.append(page.content)
            content = "".join(pages)
            if (
                hashlib.sha256(content.encode("utf-8")).hexdigest()
                != first.content_sha256
            ):
                return _CommanderResultArtifactSafetyVerdict(False)
            try:
                payload = json.loads(content)
            except (TypeError, ValueError):
                return _CommanderResultArtifactSafetyVerdict(False)
            if not isinstance(payload, dict):
                return _CommanderResultArtifactSafetyVerdict(False)
            return _CommanderResultArtifactSafetyVerdict(
                self._commander_public_result_artifact_payload_safety(
                    payload
                ),
                tuple(page_bindings),
            )

        try:
            verdict = scan_complete_payload()
        except BaseException as exc:
            with self._commander_public_result_artifact_safety_cache_lock:
                current = (
                    self._commander_public_result_artifact_safety_inflight.get(
                        cache_key
                    )
                )
                if current is flight:
                    del self._commander_public_result_artifact_safety_inflight[
                        cache_key
                    ]
            flight.set_exception(exc)
            raise

        with self._commander_public_result_artifact_safety_cache_lock:
            self._commander_public_result_artifact_safety_cache[
                cache_key
            ] = verdict
            self._commander_public_result_artifact_safety_cache.move_to_end(
                cache_key
            )
            while (
                len(
                    self._commander_public_result_artifact_safety_cache
                )
                > COMMANDER_PUBLIC_RESULT_ARTIFACT_SAFETY_CACHE_MAX_ITEMS
            ):
                self._commander_public_result_artifact_safety_cache.popitem(
                    last=False
                )
            current = (
                self._commander_public_result_artifact_safety_inflight.get(
                    cache_key
                )
            )
            if current is flight:
                del self._commander_public_result_artifact_safety_inflight[
                    cache_key
                ]
        flight.set_result(verdict)
        return verdict

    def _commander_public_result_artifact_safety(
        self,
        artifact_id: str,
    ) -> bool | None:
        verdict = self._commander_public_result_artifact_preflight(
            artifact_id
        )
        return None if verdict is None else verdict.safe

    def _commander_public_result_artifact_page_binding(
        self,
        artifact_id: str,
        page: int,
    ) -> dict[str, Any] | None:
        verdict = self._commander_public_result_artifact_preflight(
            artifact_id
        )
        if verdict is None:
            return None
        binding = verdict.page_binding(page)
        return (
            None
            if binding is None
            else binding.as_projection_binding()
        )

    def _commander_public_result_artifact_payload_safety(
        self,
        payload: dict[str, Any],
    ) -> bool:
        sanitized = self._commander_public_projector().sanitize_for_artifact(
            payload
        )
        return isinstance(sanitized, dict) and sanitized == payload

    def _commander_public_resource_read_safety(
        self,
        resource_result: dict[str, Any],
    ) -> bool:
        """Require an exact public projection for opaque evidence resources."""

        sanitized = self._commander_public_projector().sanitize_for_artifact(
            resource_result
        )
        return isinstance(sanitized, dict) and sanitized == resource_result

    @staticmethod
    def _commander_public_result_artifact_page_envelope_safety(
        resource_result: dict[str, Any],
        *,
        requested_uri: str,
        page_binding: dict[str, Any] | None,
    ) -> bool:
        if set(resource_result) != {"contents"}:
            return False
        contents = resource_result.get("contents")
        if not isinstance(contents, list) or len(contents) != 1:
            return False
        content_item = contents[0]
        if (
            not isinstance(content_item, dict)
            or set(content_item) != {"uri", "mimeType", "text"}
            or content_item.get("uri") != requested_uri
            or content_item.get("mimeType") != "application/json"
        ):
            return False
        serialized_page = content_item.get("text")
        if not isinstance(serialized_page, str):
            return False
        try:
            page = json.loads(serialized_page)
        except (TypeError, ValueError):
            return False
        return (
            isinstance(page, dict)
            and commander_result_artifact_page_matches_binding(
                page,
                page_binding,
            )
        )

    def _commander_public_review_manifest_content_safety(
        self,
        content: str,
    ) -> bool:
        whole_subject = {"content": content}
        sanitized_subject = (
            self._commander_public_projector().sanitize_for_artifact(
                whole_subject
            )
        )
        return (
            isinstance(sanitized_subject, dict)
            and sanitized_subject == whole_subject
        )

    def _commander_public_review_manifest_cached_safety(
        self,
        *,
        subject_sha256: str,
        content: str,
    ) -> bool:
        owns_scan = False
        with self._commander_public_review_manifest_safety_cache_lock:
            cached = self._commander_public_review_manifest_safety_cache.get(
                subject_sha256
            )
            if cached is not None:
                self._commander_public_review_manifest_safety_cache.move_to_end(
                    subject_sha256
                )
                return cached
            flight = (
                self._commander_public_review_manifest_safety_inflight.get(
                    subject_sha256
                )
            )
            if flight is None:
                flight = Future()
                self._commander_public_review_manifest_safety_inflight[
                    subject_sha256
                ] = flight
                owns_scan = True
        if not owns_scan:
            return flight.result()

        try:
            safe = self._commander_public_review_manifest_content_safety(
                content
            )
        except BaseException as exc:
            with self._commander_public_review_manifest_safety_cache_lock:
                current = (
                    self._commander_public_review_manifest_safety_inflight.get(
                        subject_sha256
                    )
                )
                if current is flight:
                    del (
                        self._commander_public_review_manifest_safety_inflight[
                            subject_sha256
                        ]
                    )
            flight.set_exception(exc)
            raise

        with self._commander_public_review_manifest_safety_cache_lock:
            self._commander_public_review_manifest_safety_cache[
                subject_sha256
            ] = safe
            self._commander_public_review_manifest_safety_cache.move_to_end(
                subject_sha256
            )
            while (
                len(self._commander_public_review_manifest_safety_cache)
                > COMMANDER_PUBLIC_REVIEW_MANIFEST_SAFETY_CACHE_MAX_ITEMS
            ):
                self._commander_public_review_manifest_safety_cache.popitem(
                    last=False
                )
            current = (
                self._commander_public_review_manifest_safety_inflight.get(
                    subject_sha256
                )
            )
            if current is flight:
                del self._commander_public_review_manifest_safety_inflight[
                    subject_sha256
                ]
        flight.set_result(safe)
        return safe

    def _commander_public_review_manifest_subject_safety(
        self,
        parsed_review_manifest: tuple[str, int | None, int | None],
    ) -> bool | None:
        """Verify and cache complete-subject safety before page slicing."""

        review_manifest_id, subject_index, _page = parsed_review_manifest
        if subject_index is None:
            return None
        stored = self._review_manifest_store.get(review_manifest_id)
        if stored is None:
            return None
        current_context = collect_review_context_binding(
            stored.project_root,
            project_name=str(stored.context_binding.get("project_name") or ""),
        )
        verify_stored_review_context(
            stored,
            current_context_binding=current_context,
        )
        if subject_index < 1 or subject_index > len(stored.subjects):
            return None
        subject = stored.subjects[subject_index - 1]
        raw, text = read_manifest_subject_file(stored.project_root, subject.path)
        actual_sha256 = hashlib.sha256(raw).hexdigest()
        if not secrets.compare_digest(actual_sha256, subject.sha256):
            raise ReviewManifestError(
                "REVIEW_MANIFEST_SUBJECT_HASH_MISMATCH",
                f"manifest subject 的 SHA-256 与当前文件不一致：{subject.path}",
                {
                    "path": subject.path,
                    "expected_sha256": subject.sha256,
                    "actual_sha256": actual_sha256,
                },
            )
        if len(text) > COMMANDER_PUBLIC_ARTIFACT_SCAN_MAX_CHARS:
            return False
        return self._commander_public_review_manifest_cached_safety(
            subject_sha256=subject.sha256,
            content=text,
        )

    def _commander_public_typed_evidence_safety(
        self,
        tool_name: str,
        params: dict[str, Any] | None,
    ) -> bool | None:
        """Preflight complete typed evidence before projecting an exact page."""

        if (
            self.mcp_exposure_profile != MCP_EXPOSURE_PROFILE_COMMANDER
            or not isinstance(params, dict)
        ):
            return None
        workflow = _policy_string_param(params, "workflow")
        phase = _policy_string_param(params, "phase")
        is_artifact_read = tool_name == "read_result_artifact" or (
            tool_name == "run_mcp_workflow"
            and workflow == MCP_RESULT_ARTIFACT_WORKFLOW
            and phase == "read"
        )
        if is_artifact_read:
            artifact_id = params.get("artifact_id")
            if (
                not isinstance(artifact_id, str)
                or MCP_RESULT_ARTIFACT_ID_RE.fullmatch(
                    artifact_id.strip()
                )
                is None
            ):
                return None
            return self._commander_public_result_artifact_safety(
                artifact_id.strip()
            )

        is_review_manifest_read = (
            (
                tool_name == "review_manifest"
                or (
                    tool_name == "run_mcp_workflow"
                    and workflow == REVIEW_MANIFEST_WORKFLOW
                )
            )
            and phase == "read"
        )
        if not is_review_manifest_read:
            return None
        review_manifest_id = params.get("review_manifest_id")
        subject_index = params.get("review_manifest_subject_index")
        page = params.get("review_manifest_page")
        if (
            not isinstance(review_manifest_id, str)
            or not review_manifest_id.strip()
            or isinstance(subject_index, bool)
            or not isinstance(subject_index, int)
            or subject_index < 1
            or (
                page is not None
                and (
                    isinstance(page, bool)
                    or not isinstance(page, int)
                    or page < 1
                )
            )
        ):
            return None
        parsed = self._parse_mcp_review_manifest_uri(
            self._mcp_review_manifest_uri(
                review_manifest_id.strip(),
                subject_index=subject_index,
                page=page,
            )
        )
        if parsed is None:
            return None
        return self._commander_public_review_manifest_subject_safety(
            parsed
        )

    def _commander_public_typed_result_artifact_page_binding(
        self,
        tool_name: str,
        params: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if (
            self.mcp_exposure_profile != MCP_EXPOSURE_PROFILE_COMMANDER
            or not isinstance(params, dict)
        ):
            return None
        workflow = _policy_string_param(params, "workflow")
        phase = _policy_string_param(params, "phase")
        is_artifact_read = tool_name == "read_result_artifact" or (
            tool_name == "run_mcp_workflow"
            and workflow == MCP_RESULT_ARTIFACT_WORKFLOW
            and phase == "read"
        )
        if not is_artifact_read:
            return None
        artifact_id = params.get("artifact_id")
        page = params.get("artifact_page", 1)
        if (
            not isinstance(artifact_id, str)
            or MCP_RESULT_ARTIFACT_ID_RE.fullmatch(
                artifact_id.strip()
            )
            is None
            or isinstance(page, bool)
            or not isinstance(page, int)
            or page < 1
        ):
            return None
        return self._commander_public_result_artifact_page_binding(
            artifact_id.strip(),
            page,
        )

    def _commander_public_review_manifest_page_envelope_safety(
        self,
        resource_result: dict[str, Any],
        parsed_review_manifest: tuple[str, int | None, int | None],
    ) -> bool:
        """Bind page metadata to its request without reinterpreting a slice."""

        (
            requested_manifest_id,
            requested_subject_index,
            requested_page,
        ) = parsed_review_manifest
        if requested_subject_index is None:
            return False
        expected_resource_uri = self._mcp_review_manifest_uri(
            requested_manifest_id,
            subject_index=requested_subject_index,
            page=requested_page,
        )

        candidate = copy.deepcopy(resource_result)
        contents = candidate.get("contents")
        if not isinstance(contents, list) or len(contents) != 1:
            return False
        content_item = contents[0]
        if not isinstance(content_item, dict):
            return False
        serialized_page = content_item.get("text")
        if not isinstance(serialized_page, str):
            return False
        try:
            page = json.loads(serialized_page)
        except (TypeError, ValueError):
            return False
        if not isinstance(page, dict) or not isinstance(page.get("content"), str):
            return False
        resource_uri = content_item.get("uri")
        if resource_uri != expected_resource_uri:
            return False
        parsed_resource = self._parse_mcp_review_manifest_uri(
            resource_uri
        )
        if parsed_resource != parsed_review_manifest:
            return False
        (
            resource_manifest_id,
            resource_subject_index,
            resource_page,
        ) = parsed_review_manifest
        expected_page_fields = {
            "review_manifest_id",
            "review_unit",
            "subject_index",
            "path",
            "sha256",
            "page",
            "page_count",
            "page_char_start",
            "page_char_end",
            "expires_at",
            "content",
        }
        if set(page) != expected_page_fields:
            return False
        if (
            page.get("review_manifest_id") != resource_manifest_id
            or page.get("subject_index") != resource_subject_index
            or page.get("page") != (resource_page or 1)
        ):
            return False
        expires_at = page.get("expires_at")
        if not isinstance(expires_at, str):
            return False
        try:
            parsed_expiry = datetime.fromisoformat(
                expires_at.replace("Z", "+00:00")
            )
        except ValueError:
            return False
        if parsed_expiry.tzinfo is None:
            return False
        page["content"] = ""
        # The resource page is a typed JSON envelope.  Validate its fields
        # structurally so allowlisted opaque ID fields are not reinterpreted
        # as free-text provider tokens merely because the envelope is
        # serialized into MCP ``text``.
        sanitized_page = (
            self._commander_public_projector().sanitize_for_artifact(page)
        )
        if not isinstance(sanitized_page, dict):
            return False
        # Restore the handle only after binding it to the parsed resource URI.
        sanitized_page["review_manifest_id"] = resource_manifest_id
        # Generic artifact projection intentionally omits timestamps.  This
        # typed envelope requires its validated expiry for continuation.
        sanitized_page["expires_at"] = expires_at
        if sanitized_page != page:
            return False
        content_item["text"] = ""
        return self._commander_public_resource_read_safety(candidate)

    def _commander_public_review_manifest_root_envelope_safety(
        self,
        resource_result: dict[str, Any],
        parsed_review_manifest: tuple[str, int | None, int | None],
    ) -> bool:
        """Bind a root summary's opaque handles to its requested resource."""

        review_manifest_id, subject_index, page = parsed_review_manifest
        if subject_index is not None or page is not None:
            return False
        expected_resource_uri = self._mcp_review_manifest_uri(
            review_manifest_id
        )
        candidate = copy.deepcopy(resource_result)
        contents = candidate.get("contents")
        if not isinstance(contents, list) or len(contents) != 1:
            return False
        content_item = contents[0]
        if not isinstance(content_item, dict):
            return False
        resource_uri = content_item.get("uri")
        serialized_summary = content_item.get("text")
        if (
            resource_uri != expected_resource_uri
            or not isinstance(serialized_summary, str)
        ):
            return False
        try:
            summary = json.loads(serialized_summary)
        except (TypeError, ValueError):
            return False
        if not isinstance(summary, dict):
            return False
        stored = self._review_manifest_store.get(review_manifest_id)
        if stored is None:
            return False
        expected_summary = self._review_manifest_resource_summary(stored)
        if summary != expected_summary:
            return False
        if (
            summary.get("review_manifest_id") != review_manifest_id
            or summary.get("manifest_resource_uri")
            != expected_resource_uri
        ):
            return False
        expires_at = summary.get("expires_at")
        if not isinstance(expires_at, str):
            return False
        try:
            parsed_expiry = datetime.fromisoformat(
                expires_at.replace("Z", "+00:00")
            )
        except ValueError:
            return False
        if parsed_expiry.tzinfo is None:
            return False

        # Mask only relation-bound standalone handle fields before applying
        # the generic credential scan.  URI fields remain exact and continue
        # through the ordinary opaque-resource allowlist.
        scan_summary = copy.deepcopy(summary)
        neutral_manifest_id = "opaque_review_manifest_handle_1234567890"
        scan_summary["review_manifest_id"] = neutral_manifest_id
        subjects = scan_summary.get("subjects")
        if not isinstance(subjects, list):
            return False
        for expected_subject_index, subject in enumerate(
            subjects,
            start=1,
        ):
            if not isinstance(subject, dict):
                return False
            subject_resource_uri = subject.get("resource_uri")
            parsed_subject_resource = (
                self._parse_mcp_review_manifest_uri(
                    subject_resource_uri
                )
                if isinstance(subject_resource_uri, str)
                else None
            )
            if parsed_subject_resource != (
                review_manifest_id,
                expected_subject_index,
                None,
            ):
                return False
            if subject.get("page_uri_template") != (
                f"{subject_resource_uri}/pages/{{page}}"
            ):
                return False
            read_call = subject.get("read_call")
            if (
                not isinstance(read_call, dict)
                or read_call.get("tool") != "run_mcp_workflow"
            ):
                return False
            arguments = read_call.get("arguments")
            if (
                not isinstance(arguments, dict)
                or arguments.get("workflow")
                != REVIEW_MANIFEST_WORKFLOW
                or arguments.get("phase") != "read"
                or arguments.get("review_manifest_id")
                != review_manifest_id
                or arguments.get("review_manifest_subject_index")
                != expected_subject_index
                or arguments.get("review_manifest_page") != 1
            ):
                return False
            arguments["review_manifest_id"] = neutral_manifest_id

        sanitized_summary = (
            self._commander_public_projector().sanitize_for_artifact(
                scan_summary
            )
        )
        if not isinstance(sanitized_summary, dict):
            return False
        # Generic artifact projection omits timestamps.  The root manifest
        # envelope requires its already validated continuation expiry.
        sanitized_summary["expires_at"] = expires_at
        if sanitized_summary != scan_summary:
            return False
        content_item["text"] = ""
        return self._commander_public_resource_read_safety(candidate)

    @staticmethod
    def _result_artifact_next_read(artifact_fields: dict[str, Any]) -> dict[str, Any]:
        return MCPResourcesService.result_artifact_next_read(artifact_fields)

    @staticmethod
    def _result_artifact_compatibility_read_call(
        artifact_id: str,
        *,
        page: int,
    ) -> dict[str, Any]:
        return MCPResourcesService.result_artifact_compatibility_read_call(
            artifact_id,
            page=page,
        )

    @staticmethod
    def _typed_result_artifact_read_call(
        artifact_id: str,
        *,
        page: int,
    ) -> dict[str, Any]:
        return MCPResourcesService.typed_result_artifact_read_call(artifact_id, page=page)

    @classmethod
    def _result_artifact_typed_next_read(
        cls,
        artifact_fields: dict[str, Any],
        *,
        page: int = 1,
    ) -> dict[str, Any]:
        return MCPResourcesService.result_artifact_typed_next_read(
            artifact_fields,
            page=page,
        )

    @classmethod
    def _result_artifact_compatibility_next_read(
        cls,
        artifact_fields: dict[str, Any],
        *,
        page: int = 1,
    ) -> dict[str, Any]:
        return MCPResourcesService.result_artifact_compatibility_next_read(
            artifact_fields,
            page=page,
        )

    def _result_artifact_recommended_next_reads(
        self,
        artifact_fields: dict[str, Any],
    ) -> list[dict[str, Any]]:
        return self._mcp_resources_service().result_artifact_recommended_next_reads(
            artifact_fields,
        )

    def _result_artifact_recovery_manifest(
        self,
        *,
        tool_name: str,
        ok: bool,
        artifact_fields: dict[str, Any],
        original_error_code: Any = None,
    ) -> dict[str, Any]:
        return self._mcp_resources_service().result_artifact_recovery_manifest(
            tool_name=tool_name,
            ok=ok,
            artifact_fields=artifact_fields,
            original_error_code=original_error_code,
        )

    @staticmethod
    def _result_artifact_unavailable_result(
        *,
        tool_name: str,
        error_code: str,
        message: str,
        recommended_next_reads: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return MCPResourcesService.result_artifact_unavailable_result(
            tool_name=tool_name,
            error_code=error_code,
            message=message,
            recommended_next_reads=recommended_next_reads,
        )

    @staticmethod
    def _mcp_result_artifact_resource_access_error(
        auth_context: MCPAuthContext,
    ) -> tuple[str, str] | None:
        return MCPResourcesService.result_artifact_resource_access_error(auth_context)

    def _review_manifest_resources(self) -> MCPReviewManifestResources:
        return self._mcp_resources_service().review_manifest_resources()

    @staticmethod
    def _mcp_review_manifest_uri(
        review_manifest_id: str,
        *,
        subject_index: int | None = None,
        page: int | None = None,
    ) -> str:
        return MCPResourcesService.review_manifest_uri(
            review_manifest_id,
            subject_index=subject_index,
            page=page,
        )

    @staticmethod
    def _parse_mcp_review_manifest_uri(
        uri: str,
    ) -> tuple[str, int | None, int | None] | None:
        return MCPResourcesService.parse_review_manifest_uri(uri)

    def _review_manifest_handle_fields(
        self,
        handle: ReviewManifestHandle,
    ) -> dict[str, Any]:
        return self._mcp_resources_service().review_manifest_handle_fields(handle)

    @staticmethod
    def _review_manifest_read_call(
        handle: ReviewManifestHandle,
        *,
        subject_index: int,
        page: int,
        project_name: str | None = None,
    ) -> dict[str, Any]:
        return MCPResourcesService.review_manifest_read_call(
            handle,
            subject_index=subject_index,
            page=page,
            project_name=project_name,
        )

    def _review_manifest_subject_descriptor(
        self,
        handle: ReviewManifestHandle,
        *,
        subject_index: int,
        path: str,
        sha256: str,
        byte_size: int,
        page_count: int,
        project_name: str | None = None,
    ) -> dict[str, Any]:
        return self._mcp_resources_service().review_manifest_subject_descriptor(
            handle,
            subject_index=subject_index,
            path=path,
            sha256=sha256,
            byte_size=byte_size,
            page_count=page_count,
            project_name=project_name,
        )

    @staticmethod
    def _mcp_read_scoped_resource_access_error(
        auth_context: MCPAuthContext,
        *,
        resource_label: str,
    ) -> tuple[str, str] | None:
        return MCPResourcesService.read_scoped_resource_access_error(
            auth_context,
            resource_label=resource_label,
        )

    def _review_manifest_resource_read_result(self, uri: str) -> dict[str, Any] | None:
        return self._mcp_resources_service().review_manifest_resource_read_result(uri)

    def _review_manifest_resource_summary(
        self,
        stored: StoredReviewManifest,
    ) -> dict[str, Any]:
        return self._mcp_resources_service().review_manifest_resource_summary(stored)

    @staticmethod
    def _review_manifest_authority_boundary() -> dict[str, bool]:
        return MCPResourcesService.review_manifest_authority_boundary()

    def _mcp_resources_list_result(self) -> dict[str, Any]:
        return self._mcp_resources_service().mcp_resources_list_result()

    @staticmethod
    def _mcp_resource_templates_list_result() -> dict[str, Any]:
        return MCPResourcesService.mcp_resource_templates_list_result()

    def _mcp_resource_read_result(self, uri: str) -> dict[str, Any] | None:
        return self._mcp_resources_service().mcp_resource_read_result(uri)


    def _handle_jsonrpc_request(
        self,
        request: dict[str, Any],
        auth_context: MCPAuthContext = None,
    ) -> dict[str, Any] | None:
        req_id = request.get("id")
        method = request.get("method")
        params = request.get("params", {})
        if method is None:
            return self._protocol_error(req_id, -32600, "invalid_request", "请求缺少 method。")
        is_notification = "id" not in request
        if is_notification and isinstance(method, str) and method.startswith("notifications/"):
            return None

        if (
            self.mcp_exposure_profile == MCP_EXPOSURE_PROFILE_AUTHORITATIVE_CANARY
            and method in {
                "list_tools",
                "call_tool",
                "list_resources",
                "list_resource_templates",
                "read_resource",
            }
        ):
            return self._protocol_error(
                req_id,
                -32601,
                "legacy_method_alias_disabled",
                "Only canonical MCP method names are enabled for authoritative_canary.",
            )

        try:
            if method == "initialize":
                authoritative_canary = (
                    self.mcp_exposure_profile == MCP_EXPOSURE_PROFILE_AUTHORITATIVE_CANARY
                )
                return self._result(
                    req_id,
                    {
                        "protocolVersion": "2025-06-18",
                        "serverInfo": {"name": "colameta-mcp", "version": "1.0.0"},
                        "instructions": (
                            "Isolated, Token-authenticated, Lease-scoped synthetic Work Item Canary."
                            if authoritative_canary
                            else COMMANDER_APP_SERVER_INSTRUCTIONS
                        ),
                        "capabilities": {
                            "tools": {"listChanged": False},
                            **(
                                {}
                                if authoritative_canary
                                else {"resources": {"subscribe": False, "listChanged": False}}
                            ),
                        },
                    },
                )
            if method == "notifications/initialized":
                return self._result(req_id, {"ok": True})
            if method in ("ping", "health"):
                return self._result(req_id, {"ok": True, "tool": method, "data": {"status": "ok"}})
            if method in ("list_tools", "tools/list"):
                return self._result(
                    req_id,
                    {"tools": self._tool_defs_payload(auth_context=auth_context)},
                )
            if method in ("list_resources", "resources/list"):
                if self.mcp_exposure_profile == MCP_EXPOSURE_PROFILE_AUTHORITATIVE_CANARY:
                    return self._result(req_id, {"resources": []})
                return self._result(req_id, self._mcp_resources_list_result())
            if method in ("list_resource_templates", "resources/templates/list"):
                if self.mcp_exposure_profile == MCP_EXPOSURE_PROFILE_AUTHORITATIVE_CANARY:
                    return self._result(req_id, {"resourceTemplates": []})
                return self._result(req_id, self._mcp_resource_templates_list_result())
            if method in ("read_resource", "resources/read"):
                if self.mcp_exposure_profile == MCP_EXPOSURE_PROFILE_AUTHORITATIVE_CANARY:
                    return self._protocol_error(
                        req_id,
                        -32601,
                        "resources_disabled",
                        "MCP Resources are disabled for authoritative_canary.",
                    )
                if not isinstance(params, dict):
                    return self._protocol_error(req_id, -32602, "invalid_params", "params 必须是对象。")
                uri = params.get("uri")
                if not isinstance(uri, str) or not uri.strip():
                    return self._protocol_error(req_id, -32602, "invalid_resource_uri", "resources/read 需要 uri。")
                normalized_uri = uri.strip()
                is_result_artifact = self._parse_mcp_result_artifact_uri(normalized_uri) is not None
                parsed_review_manifest = self._parse_mcp_review_manifest_uri(
                    normalized_uri
                )
                is_review_manifest = parsed_review_manifest is not None
                if (
                    normalized_uri != COMMANDER_APP_WIDGET_URI
                    and not is_result_artifact
                    and not is_review_manifest
                ):
                    return self._protocol_error(
                        req_id,
                        -32602,
                        "resource_not_found",
                        f"未知 resource uri：{normalized_uri}",
                    )
                parsed_artifact: tuple[str, int] | None = None
                result_artifact_page_binding: dict[str, Any] | None = None
                if is_result_artifact:
                    access_error = self._mcp_result_artifact_resource_access_error(auth_context)
                    if access_error is not None:
                        error_code, message = access_error
                        return self._protocol_error(req_id, -32602, error_code, message)
                    parsed_artifact = self._parse_mcp_result_artifact_uri(
                        normalized_uri
                    )
                    artifact_safety = (
                        self._commander_public_result_artifact_safety(
                            parsed_artifact[0]
                        )
                        if (
                            self.mcp_exposure_profile
                            == MCP_EXPOSURE_PROFILE_COMMANDER
                            and parsed_artifact is not None
                        )
                        else None
                    )
                    if (
                        artifact_safety is False
                    ):
                        return self._protocol_error(
                            req_id,
                            -32602,
                            "evidence_unavailable",
                            "结果证据未通过 Commander 公共安全校验，已拒绝读取。",
                        )
                    if (
                        artifact_safety is True
                        and parsed_artifact is not None
                    ):
                        result_artifact_page_binding = (
                            self._commander_public_result_artifact_page_binding(
                                parsed_artifact[0],
                                parsed_artifact[1],
                            )
                        )
                whole_subject_safety: bool | None = None
                if is_review_manifest:
                    access_error = self._mcp_read_scoped_resource_access_error(
                        auth_context,
                        resource_label="Review manifest resource",
                    )
                    if access_error is not None:
                        error_code, message = access_error
                        return self._protocol_error(req_id, -32602, error_code, message)
                    try:
                        if (
                            self.mcp_exposure_profile
                            == MCP_EXPOSURE_PROFILE_COMMANDER
                            and parsed_review_manifest is not None
                            and parsed_review_manifest[1] is not None
                        ):
                            whole_subject_safety = (
                                self._commander_public_review_manifest_subject_safety(
                                    parsed_review_manifest
                                )
                            )
                            if whole_subject_safety is False:
                                return self._protocol_error(
                                    req_id,
                                    -32602,
                                    "evidence_unavailable",
                                    "审查证据未通过 Commander 公共安全校验，已拒绝读取。",
                                )
                        resource_result = self._review_manifest_resource_read_result(normalized_uri)
                    except ReviewManifestError as exc:
                        error_code = exc.error_code
                        if (
                            self.mcp_exposure_profile
                            == MCP_EXPOSURE_PROFILE_COMMANDER
                        ):
                            error_code = (
                                commander_public_error_code(error_code)
                                or "INTERNAL_ERROR"
                            )
                        return self._protocol_error(
                            req_id,
                            -32602,
                            error_code,
                            exc.message,
                            exc.details,
                        )
                else:
                    resource_result = self._mcp_resource_read_result(normalized_uri)
                if resource_result is None:
                    return self._protocol_error(
                        req_id,
                        -32602,
                        (
                            "result_artifact_not_found_or_expired"
                            if is_result_artifact
                            else "review_manifest_not_found_or_expired"
                            if is_review_manifest
                            else "resource_not_found"
                        ),
                        (
                            "结果 artifact 不存在、已过期或页码无效。"
                            if is_result_artifact
                            else "审查 manifest 不存在、已过期或资源页码无效。"
                            if is_review_manifest
                            else f"未知 resource uri：{normalized_uri}"
                        ),
                    )
                if (
                    self.mcp_exposure_profile
                    == MCP_EXPOSURE_PROFILE_COMMANDER
                    and parsed_artifact is not None
                    and not self._commander_public_result_artifact_page_envelope_safety(
                        resource_result,
                        requested_uri=normalized_uri,
                        page_binding=result_artifact_page_binding,
                    )
                ):
                    return self._protocol_error(
                        req_id,
                        -32602,
                        "evidence_unavailable",
                        "结果证据页与已验证的存储页不一致，已拒绝读取。",
                    )
                if (
                    self.mcp_exposure_profile
                    == MCP_EXPOSURE_PROFILE_COMMANDER
                    and parsed_review_manifest is not None
                    and not (
                        (
                            self._commander_public_review_manifest_root_envelope_safety(
                                resource_result,
                                parsed_review_manifest,
                            )
                            if parsed_review_manifest[1] is None
                            else self._commander_public_review_manifest_page_envelope_safety(
                                resource_result,
                                parsed_review_manifest,
                            )
                            if whole_subject_safety is True
                            else self._commander_public_resource_read_safety(
                                resource_result
                            )
                        )
                    )
                ):
                    return self._protocol_error(
                        req_id,
                        -32602,
                        "evidence_unavailable",
                        "审查证据未通过 Commander 公共安全校验，已拒绝读取。",
                    )
                return self._result(req_id, resource_result)
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
                if self.mcp_exposure_profile == MCP_EXPOSURE_PROFILE_AUTHORITATIVE_CANARY:
                    return self._protocol_error(
                        req_id,
                        -32601,
                        "direct_tool_method_disabled",
                        "Direct named JSON-RPC tool methods are disabled; use tools/call.",
                    )
                return self._result(req_id, self._call_tool(method, params, auth_context=auth_context))
            return self._protocol_error(req_id, -32601, "method_not_found", f"未知方法：{method}")
        except Exception as e:
            return self._result(
                req_id,
                self._tool_error("internal", "INTERNAL_ERROR", "服务器内部错误。", {"message": str(e)}),
            )

    def _tool_oauth_scopes(
        self,
        tool_name: str,
        auth_context: MCPAuthContext,
    ) -> list[str]:
        if not isinstance(auth_context, dict):
            return []
        auth_mode = auth_context.get("mode")
        if auth_mode not in {"oauth", "external-oauth"}:
            return []
        policy = MCP_TOOL_POLICIES.get(tool_name)
        if policy is None:
            return []
        scopes: set[str] = set()
        if policy.static_scope is not None:
            scopes.add(policy.static_scope)
        if isinstance(policy.action_scopes, dict):
            scopes.update(policy.action_scopes.values())
        if policy.default_scope is not None:
            scopes.add(policy.default_scope)
        if policy.selector in {"manage_files", "run_mcp_workflow"}:
            scopes.update({"mcp:read", "mcp:preview", "mcp:plan", "mcp:commit"})
        if auth_mode == "external-oauth" and tool_name == "manage_git":
            scopes.discard("mcp:commit")
        scopes.intersection_update(VALID_MCP_SCOPES)
        oauth_provider = auth_context.get("oauth_provider")
        configured_scopes = getattr(oauth_provider, "scopes", None)
        if isinstance(configured_scopes, (list, tuple, set)):
            scopes.intersection_update(
                scope for scope in configured_scopes if isinstance(scope, str)
            )
        return sorted(scopes)

    def _tool_defs_payload(
        self,
        *,
        auth_context: MCPAuthContext = None,
    ) -> list[dict[str, Any]]:
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
            meta = copy.deepcopy(tool.meta) if isinstance(tool.meta, dict) else {}
            oauth_scopes = self._tool_oauth_scopes(tool.name, auth_context)
            if oauth_scopes:
                security_schemes = [{"type": "oauth2", "scopes": oauth_scopes}]
                item["securitySchemes"] = copy.deepcopy(security_schemes)
                meta["securitySchemes"] = copy.deepcopy(security_schemes)
            if meta:
                item["_meta"] = meta
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
            *WORK_ITEM_READ_TOOLS,
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

    def _get_exposure_profile(self, requested: str | None = None) -> str:
        raw = requested if requested is not None else os.getenv(
            MCP_EXPOSURE_PROFILE_ENV,
            MCP_EXPOSURE_PROFILE_NORMAL,
        )
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
        filtered = [tool for tool in tools if tool.name in allowed]
        if self.mcp_exposure_profile == MCP_EXPOSURE_PROFILE_COMMANDER:
            position = {name: index for index, name in enumerate(COMMANDER_EXPOSED_TOOLS)}
            filtered.sort(key=lambda tool: position[tool.name])
        return filtered



    def _commander_public_projector(self) -> CommanderPublicProjector:
        hidden_tool_names = {
            tool_name
            for profile_tools in _PROFILE_ORDERS.values()
            for tool_name in profile_tools
            if tool_name not in COMMANDER_EXPOSED_TOOLS
        }
        return CommanderPublicProjector(
            self.project_root,
            hidden_tool_names=hidden_tool_names,
        )

    def _commander_public_project_tool_result(
        self,
        tool_result: dict[str, Any],
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self.mcp_exposure_profile != MCP_EXPOSURE_PROFILE_COMMANDER:
            return tool_result
        projector = self._commander_public_projector()
        tool_name = str(tool_result.get("tool") or "unknown_tool")
        try:
            exact_evidence_safety = (
                self._commander_public_typed_evidence_safety(
                    tool_name,
                    params,
                )
            )
        except ReviewManifestError as exc:
            public_error_code = (
                commander_public_error_code(exc.error_code)
                or "INTERNAL_ERROR"
            )
            return projector.project_tool_result(
                self._tool_error(
                    tool_name,
                    public_error_code,
                    exc.message,
                ),
                params,
            )
        if exact_evidence_safety is False:
            return projector.project_tool_result(
                self._tool_error(
                    tool_name,
                    "EVIDENCE_UNAVAILABLE",
                    "完整证据未通过 Commander 公共安全校验，已拒绝读取。",
                ),
                params,
            )
        exact_evidence_prevalidated = exact_evidence_safety is True
        exact_result_artifact_page_binding = (
            self._commander_public_typed_result_artifact_page_binding(
                tool_name,
                params,
            )
            if exact_evidence_prevalidated
            else None
        )
        data = tool_result.get("data") if isinstance(tool_result, dict) else None
        if (
            isinstance(data, dict)
            and data.get("schema_version") == COMMANDER_RESPONSE_SCHEMA_VERSION
        ):
            return projector.project_tool_result(
                tool_result,
                params,
                exact_evidence_prevalidated=(
                    exact_evidence_prevalidated
                ),
                exact_result_artifact_page_binding=(
                    exact_result_artifact_page_binding
                ),
            )

        target_chars = (
            MCP_HARD_TOOL_RESULT_CHARS
            if tool_name == "render_commander_app"
            else MCP_TARGET_TOOL_RESULT_CHARS
        )
        if self._json_char_count(tool_result) <= target_chars:
            return projector.project_tool_result(
                tool_result,
                params,
                exact_evidence_prevalidated=(
                    exact_evidence_prevalidated
                ),
                exact_result_artifact_page_binding=(
                    exact_result_artifact_page_binding
                ),
            )

        safe_artifact_payload = projector.sanitize_for_artifact(tool_result)
        if not isinstance(safe_artifact_payload, dict):
            return projector.project_tool_result(
                {
                    "ok": False,
                    "tool": tool_name,
                    "error_code": "PUBLIC_PROJECTION_FAILED",
                    "message": "大结果无法建立安全的 Commander 公共证据。",
                },
                params,
                exact_evidence_prevalidated=(
                    exact_evidence_prevalidated
                ),
                exact_result_artifact_page_binding=(
                    exact_result_artifact_page_binding
                ),
            )
        artifact_fields = self._store_packaged_result_artifact(
            tool_name,
            safe_artifact_payload,
        )
        if artifact_fields is None:
            return projector.project_tool_result(
                {
                    "ok": False,
                    "tool": tool_name,
                    "error_code": "PUBLIC_PROJECTION_FAILED",
                    "message": "大结果无法建立可恢复的 Commander 公共证据。",
                },
                params,
                exact_evidence_prevalidated=(
                    exact_evidence_prevalidated
                ),
                exact_result_artifact_page_binding=(
                    exact_result_artifact_page_binding
                ),
            )

        projected = projector.project_tool_result(
            tool_result,
            params,
            exact_evidence_prevalidated=exact_evidence_prevalidated,
            exact_result_artifact_page_binding=(
                exact_result_artifact_page_binding
            ),
        )
        contract = projected.get("data") if isinstance(projected, dict) else None
        if not isinstance(contract, dict):
            return projector.project_tool_result(
                {
                    "ok": False,
                    "tool": tool_name,
                    "error_code": "PUBLIC_PROJECTION_FAILED",
                    "message": "大结果的 Commander 公共响应构建失败。",
                },
                params,
                exact_evidence_prevalidated=(
                    exact_evidence_prevalidated
                ),
                exact_result_artifact_page_binding=(
                    exact_result_artifact_page_binding
                ),
            )
        packaged_contract = copy.deepcopy(contract)
        packaged_contract["evidence"] = {
            "kind": "result_artifact",
            **artifact_fields,
        }
        facts = packaged_contract.get("facts")
        if not isinstance(facts, dict):
            facts = {}
        else:
            facts = {
                key: value
                for index, (key, value) in enumerate(facts.items())
                if index < 150
            }
        packaged_contract["facts"] = facts
        facts["result_packaged"] = True
        facts["result_char_estimate"] = self._json_char_count(tool_result)
        facts["artifact_projection"] = "public_sanitized_full_result"
        if packaged_contract.get("outcome") == "completed":
            packaged_contract["summary"] = (
                "当前调用已完成；完整公共安全结果已保存为短期分页证据。"
            )
            packaged_contract["next_action"] = {
                "tool": "read_result_artifact",
                "arguments": {
                    "artifact_id": artifact_fields["artifact_id"],
                    "artifact_page": 1,
                },
                "reason": "读取完整公共安全结果的第 1 页并核对内容哈希。",
            }
        try:
            validate_commander_response(
                packaged_contract,
                exact_evidence_prevalidated=(
                    exact_evidence_prevalidated
                ),
            )
        except Exception:
            return projector.project_tool_result(
                {
                    "ok": False,
                    "tool": tool_name,
                    "error_code": "PUBLIC_PROJECTION_FAILED",
                    "message": "大结果无法满足 Commander 公共响应契约。",
                },
                params,
                exact_evidence_prevalidated=(
                    exact_evidence_prevalidated
                ),
                exact_result_artifact_page_binding=(
                    exact_result_artifact_page_binding
                ),
            )
        packaged_result = copy.deepcopy(projected)
        packaged_result["data"] = packaged_contract
        return packaged_result
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
        tool_result = self._commander_public_project_tool_result(tool_result, params)
        structured_tool_result, mcp_meta = self._split_mcp_tool_result_meta(tool_result)
        safe_params = params if isinstance(params, dict) else {}
        is_error = not bool(structured_tool_result.get("ok"))
        tool_name = str(structured_tool_result.get("tool") or "unknown_tool")
        # The Commander widget consumes structuredContent directly. Keep its
        # manifest intact up to the existing hard response ceiling; generic
        # tools retain the lower packaging target.
        action_name = safe_params.get("action")
        is_manage_files_read = (
            tool_name == "manage_files"
            and isinstance(action_name, str)
            and action_name.strip().lower() == "read"
        )
        if tool_name == "render_commander_app":
            target_chars = MCP_HARD_TOOL_RESULT_CHARS
        elif is_manage_files_read:
            target_chars = MCP_MANAGE_FILES_READ_TARGET_CHARS
        else:
            target_chars = MCP_TARGET_TOOL_RESULT_CHARS
        if self._json_char_count(structured_tool_result) <= target_chars:
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
        artifact_fields: dict[str, Any] | None = None
        try:
            data = structured_tool_result.get("data")
            data_keys: list[str] = []
            if isinstance(data, dict):
                data_keys = [str(k) for k in list(data.keys())[:40]]
            omitted_fields = [f"data.{k}" for k in data_keys] if data_keys else ["data"]
            artifact_fields = self._store_packaged_result_artifact(
                tool_name,
                structured_tool_result,
            )
            if artifact_fields is None:
                unavailable_sc = self._result_artifact_unavailable_result(
                    tool_name=tool_name,
                    error_code="MCP_RESULT_ARTIFACT_UNAVAILABLE",
                    message=(
                        "工具结果超过返回上限，但无法建立可恢复分页 artifact；"
                        "原始结果未返回，请缩小请求范围后重试。"
                    ),
                    recommended_next_reads=self._mcp_default_next_reads(tool_name),
                )
                unavailable_text = json.dumps(unavailable_sc, ensure_ascii=False)
                return self._attach_mcp_result_meta(
                    {
                        "content": [{"type": "text", "text": unavailable_text}],
                        "structuredContent": unavailable_sc,
                        "isError": True,
                    },
                    mcp_meta,
                )
            recommended_next_reads = self._mcp_recommended_next_reads(
                tool_name,
                safe_params,
                structured_tool_result,
            )
            recommended_next_reads = [
                *self._result_artifact_recommended_next_reads(
                    artifact_fields,
                ),
                *recommended_next_reads,
            ]
            manifest_sc: dict[str, Any] = {
                "ok": bool(structured_tool_result.get("ok")),
                "tool": tool_name,
                "packaged": True,
                "package_mode": "manifest",
                "message": "结果内容较大，已返回摘要与续读建议。",
                "summary": {
                    "result_char_estimate": self._json_char_count(structured_tool_result),
                    "target_tool_result_chars": target_chars,
                    "hard_tool_result_chars": MCP_HARD_TOOL_RESULT_CHARS,
                    "data_key_count": len(data.keys()) if isinstance(data, dict) else 0,
                    "data_keys": data_keys,
                    "original_error_code": structured_tool_result.get("error_code"),
                },
                "omitted_fields": omitted_fields,
                "recommended_next_reads": recommended_next_reads,
            }
            manifest_sc.update(artifact_fields)
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
                    "target_tool_result_chars": target_chars,
                    "hard_tool_result_chars": MCP_HARD_TOOL_RESULT_CHARS,
                },
                "omitted_fields": ["data"],
                "recommended_next_reads": recommended_next_reads[:2],
            }
            reduced_sc.update(artifact_fields)
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

        if artifact_fields is not None:
            recovery_sc = self._result_artifact_recovery_manifest(
                tool_name=tool_name,
                ok=bool(structured_tool_result.get("ok")),
                artifact_fields=artifact_fields,
                original_error_code=structured_tool_result.get("error_code"),
            )
            recovery_text = json.dumps(recovery_sc, ensure_ascii=False)
            return self._attach_mcp_result_meta(
                {
                    "content": [{"type": "text", "text": recovery_text}],
                    "structuredContent": recovery_sc,
                    "isError": is_error,
                },
                mcp_meta,
            )

        fallback_sc = self._result_artifact_unavailable_result(
            tool_name=tool_name,
            error_code="MCP_RESULT_SHAPING_FAILED",
            message="工具结果超过返回上限且无法建立可恢复分页 artifact；请缩小请求范围后重试。",
            recommended_next_reads=self._mcp_default_next_reads(tool_name),
        )
        fallback_text = json.dumps(fallback_sc, ensure_ascii=False)
        return self._attach_mcp_result_meta(
            {
                "content": [{"type": "text", "text": fallback_text}],
                "structuredContent": fallback_sc,
                "isError": True,
            },
            mcp_meta,
        )

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
                "artifact_id": {
                    "type": "string",
                    "description": "Opaque short-lived ID for a packaged result continuation artifact.",
                },
                "resource_uri": {
                    "type": "string",
                    "description": "MCP resource URI for page 1 of a packaged result artifact.",
                },
                "page_uri_template": {
                    "type": "string",
                    "description": "MCP resource URI template for later artifact pages.",
                },
                "page_count": {
                    "type": "integer",
                    "description": "Number of readable pages in a packaged result artifact.",
                },
                "content_sha256": {
                    "type": "string",
                    "description": "SHA-256 of the complete artifact content.",
                },
                "expires_at": {
                    "type": "string",
                    "description": "Expiry timestamp for a packaged result artifact.",
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

    def _build_commander_output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "description": (
                "Commander 公共工具统一返回 envelope；data 严格符合 "
                "commander_response.v1。"
            ),
            "properties": {
                "ok": {
                    "type": "boolean",
                    "description": "Whether the public tool envelope was produced safely.",
                },
                "tool": {
                    "type": "string",
                    "enum": list(COMMANDER_EXPOSED_TOOLS),
                    "description": "Commander public tool name.",
                },
                "data": commander_response_schema(),
                "error_code": {
                    "type": "string",
                    "description": "Stable public error code when ok is false.",
                },
                "message": {
                    "type": "string",
                    "description": "Bounded public error message when ok is false.",
                },
            },
            "required": ["ok", "tool", "data"],
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
                read_arguments: dict[str, Any] = {
                    "action": "read",
                    "file": target_file,
                    "start_line": 1,
                    "end_line": 200,
                    "max_chars": 20000,
                }
                project_name = params.get("project_name")
                if isinstance(project_name, str) and project_name.strip():
                    read_arguments["project_name"] = project_name.strip()
                suggestions.append(
                    {
                        "tool": "manage_files",
                        "arguments": read_arguments,
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
        artifact_fields: dict[str, Any] | None = None
        ok_value = False
        original_error_code: Any = None
        try:
            tool_result = self._commander_public_project_tool_result(tool_result, params)
            sanitized_tool_result = self._actions_sanitize_tool_result(tool_result)
            response_chars = self._json_char_count(sanitized_tool_result)
            if response_chars <= ACTIONS_TARGET_RESPONSE_CHARS:
                return sanitized_tool_result
            ok_value = bool(sanitized_tool_result.get("ok"))
            original_error_code = sanitized_tool_result.get("error_code")
            data = sanitized_tool_result.get("data")
            data_keys: list[str] = []
            if isinstance(data, dict):
                data_keys = [str(k) for k in list(data.keys())[:40]]
            omitted_fields = [f"data.{k}" for k in data_keys] if data_keys else ["data"]
            artifact_fields = self._store_packaged_result_artifact(
                tool_name,
                sanitized_tool_result,
            )
            if artifact_fields is None:
                return self._result_artifact_unavailable_result(
                    tool_name=tool_name,
                    error_code="ACTION_RESULT_ARTIFACT_UNAVAILABLE",
                    message=(
                        "Actions 响应超过返回上限，但无法建立可恢复分页 artifact；"
                        "原始结果未返回，请缩小请求范围后重试。"
                    ),
                    recommended_next_reads=self._actions_default_next_reads(tool_name),
                )
            recommended_next_reads = self._actions_recommended_next_reads(
                tool_name,
                params,
                sanitized_tool_result,
            )
            recommended_next_reads = [
                *self._result_artifact_recommended_next_reads(
                    artifact_fields,
                ),
                *recommended_next_reads,
            ]
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
                "recommended_next_reads": recommended_next_reads,
            }
            manifest.update(artifact_fields)
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
                "recommended_next_reads": recommended_next_reads[:2],
            }
            reduced_manifest.update(artifact_fields)
            if not ok_value and isinstance(sanitized_tool_result.get("error_code"), str):
                reduced_manifest["error_code"] = sanitized_tool_result.get("error_code")
            if self._json_char_count(reduced_manifest) <= ACTIONS_HARD_RESPONSE_CHARS:
                return reduced_manifest
            return self._result_artifact_recovery_manifest(
                tool_name=tool_name,
                ok=ok_value,
                artifact_fields=artifact_fields,
                original_error_code=original_error_code,
            )
        except Exception:
            if artifact_fields is not None:
                return self._result_artifact_recovery_manifest(
                    tool_name=tool_name,
                    ok=ok_value,
                    artifact_fields=artifact_fields,
                    original_error_code=original_error_code,
                )
            return self._result_artifact_unavailable_result(
                tool_name=tool_name,
                error_code="ACTION_RESPONSE_PACKAGING_FAILED",
                message="Actions 响应包装失败，且未能建立可恢复分页 artifact；请缩小请求范围后重试。",
                recommended_next_reads=self._actions_default_next_reads(tool_name),
            )

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
        auth_context: MCPAuthContext = None,
    ) -> dict[str, Any]:
        if not isinstance(name, str) or not name:
            return self._tool_error("unknown", "INVALID_TOOL", "tool 名称无效。")
        if name == "apply_plan_patch":
            return self._tool_error(
                "apply_plan_patch",
                "TOOL_NOT_EXPOSED",
                "apply_plan_patch is intentionally not exposed over MCP. Runner applies pending patches locally via Web Console or CLI.",
            )
        if (
            self.mcp_exposure_profile
            in {
                MCP_EXPOSURE_PROFILE_COMMANDER,
                MCP_EXPOSURE_PROFILE_AUTHORITATIVE_CANARY,
            }
            and name not in self._get_exposed_tool_names(self.mcp_exposure_profile)
        ):
            return self._tool_error(
                name,
                "TOOL_NOT_EXPOSED",
                "The tool is denied by the active server exposure profile.",
            )
        if self._preflight_conformance_only:
            return self._tool_error(
                name,
                "PREFLIGHT_CONFORMANCE_TOOL_CALL_DENIED",
                "The preflight conformance listener exposes definitions for measurement but denies every tool call.",
            )
        listener_proof_validator = self._token_transport_proof_validator
        transport_authenticated = False
        if callable(listener_proof_validator) and auth_context is not None:
            try:
                transport_authenticated = bool(listener_proof_validator(auth_context))
            except Exception:
                transport_authenticated = False
        if (
            self.mcp_exposure_profile == MCP_EXPOSURE_PROFILE_AUTHORITATIVE_CANARY
            and not transport_authenticated
        ):
            return self._tool_error(
                name,
                "UNAUTHORIZED",
                "A Token-authenticated HTTP transport capability is required.",
            )
        tool = self.tools.get(name)
        if tool is None:
            return self._tool_error(name, "TOOL_NOT_FOUND", f"未知 tool：{name}")
        if params is None:
            params = {}
        if not isinstance(params, dict):
            return self._tool_error(name, "INVALID_PARAMS", "tool 参数必须是 JSON 对象。")
        is_unscoped_result_artifact_read = (
            name == "run_mcp_workflow"
            and _policy_string_param(params, "workflow") == MCP_RESULT_ARTIFACT_WORKFLOW
            and _policy_string_param(params, "phase") == "read"
        )
        if (
            self.mcp_exposure_profile != MCP_EXPOSURE_PROFILE_AUTHORITATIVE_CANARY
            and (self.service_mode or auth_context is not None)
            and name in PROJECT_NAME_REQUIRED_TOOLS
            and not is_unscoped_result_artifact_read
        ):
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
        remote_policy_error = self._external_oauth_remote_policy_error(name, params, auth_context)
        if remote_policy_error is not None:
            return remote_policy_error
        scope_error = self._oauth_scope_error(name, params, auth_context)
        if scope_error is not None:
            return scope_error
        relay_scope_error = self._cloud_relay_scope_error(name, params, auth_context)
        if relay_scope_error is not None:
            return relay_scope_error
        try:
            exact_evidence_safety = (
                self._commander_public_typed_evidence_safety(
                    name,
                    params,
                )
            )
        except ReviewManifestError as exc:
            return self._tool_error(
                name,
                commander_public_error_code(exc.error_code)
                or "INTERNAL_ERROR",
                exc.message,
            )
        if exact_evidence_safety is False:
            return self._tool_error(
                name,
                "EVIDENCE_UNAVAILABLE",
                "完整证据未通过 Commander 公共安全校验，已拒绝读取。",
            )
        operator_request = (
            name == "run_mcp_workflow"
            and _policy_string_param(params, "workflow") == "operator_batch"
        )
        commander_request_token = _COMMANDER_PUBLIC_REQUEST.set(
            _COMMANDER_PUBLIC_REQUEST.get()
            or self.mcp_exposure_profile == MCP_EXPOSURE_PROFILE_COMMANDER
        )
        try:
            with operator_authenticated_request_scope(auth_context), work_item_authenticated_request_scope(
                auth_context
            ), work_item_principal_scope(auth_context):
                data = tool(params)
            result = {"ok": True, "tool": name, "data": data}
            if isinstance(data, dict) and isinstance(data.get("_meta"), dict):
                clean_data = dict(data)
                result["_meta"] = copy.deepcopy(clean_data.pop("_meta"))
                result["data"] = clean_data
            return self._commander_public_project_tool_result(result, params)
        except MCPToolInputError as e:
            self._stop_authoritative_canary_if_inactive()
            if operator_request:
                return {"ok": False, "tool": name, "error_code": e.error_code, "message": "Operator request was denied."}
            return self._tool_error(name, e.error_code, e.message, e.details)
        except PlanningBridgeError as e:
            if operator_request:
                return {"ok": False, "tool": name, "error_code": "OPERATOR_REQUEST_FAILED", "message": "Operator request failed closed."}
            return self._tool_error(name, "BRIDGE_ERROR", str(e))
        except SourceReviewError as e:
            if operator_request:
                return {"ok": False, "tool": name, "error_code": "OPERATOR_REQUEST_FAILED", "message": "Operator request failed closed."}
            return self._tool_error(name, "SOURCE_REVIEW_ERROR", str(e))
        except Exception as e:
            self._stop_authoritative_canary_if_inactive()
            if operator_request:
                return {"ok": False, "tool": name, "error_code": "OPERATOR_REQUEST_FAILED", "message": "Operator request failed closed."}
            return self._tool_error(name, "TOOL_EXEC_ERROR", "工具执行失败。", {"message": str(e)})
        finally:
            _COMMANDER_PUBLIC_REQUEST.reset(commander_request_token)

    def _stop_authoritative_canary_if_inactive(self) -> None:
        if self.mcp_exposure_profile != MCP_EXPOSURE_PROFILE_AUTHORITATIVE_CANARY:
            return
        bounded_pilot = self.work_item_scope_mode == PILOT_SCOPE_MODE
        effective_active = False
        try:
            status = execute_work_item_mcp_command(
                self.project_root,
                "get_work_item_governance_status",
                {},
                principal_context=current_work_item_principal(),
                authoritative_canary=not bounded_pilot,
                bounded_single_project_pilot=bounded_pilot,
            )
            lease = status.get("activation_lease") if isinstance(status, dict) else None
            effective_active = bool(isinstance(lease, dict) and lease.get("effective_active") is True)
        except Exception:
            effective_active = False
        if effective_active:
            return
        httpd = getattr(self, "_httpd", None)
        if httpd is not None:
            threading.Thread(
                target=httpd.shutdown,
                name="colameta-authoritative-canary-stop",
                daemon=True,
            ).start()

    def call_tool_for_agent(
        self,
        name: str,
        arguments: dict[str, Any],
        auth_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        tool_result = self._call_tool(name, arguments, auth_context=auth_context)
        return self._commander_public_project_tool_result(tool_result, arguments)

    def get_required_scope_for_tool(self, name: str, arguments: dict[str, Any]) -> str:
        return self._required_scope_for_tool(name, arguments)

    def get_required_scopes_for_tool(self, name: str, arguments: dict[str, Any]) -> tuple[str, ...]:
        return self._required_scopes_for_tool(name, arguments)

    def _required_scope_for_tool(self, name: str, params: dict[str, Any]) -> str:
        scopes = self._required_scopes_for_tool(name, params)
        return scopes[0] if scopes else "mcp:unknown"

    def _required_scopes_for_tool(self, name: str, params: dict[str, Any]) -> tuple[str, ...]:
        if name == "run_mcp_workflow" and _policy_string_param(params, "workflow") == "operator_batch":
            try:
                service = self._operator_batch_service_for_params(params)
            except Exception:
                return ("mcp:commit", "mcp:plan")
            scopes = tuple(
                scope for scope in service.required_scopes(params)
                if scope in VALID_MCP_SCOPES
            )
            return tuple(dict.fromkeys(scopes))
        scope = self._tool_policy_scope(name, params)
        return (scope,) if scope is not None else ()

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
        auth_context: MCPAuthContext,
    ) -> dict[str, Any] | None:
        if not isinstance(auth_context, dict) or auth_context.get("mode") not in {"oauth", "external-oauth"}:
            return None
        oauth_provider = auth_context.get("oauth_provider")
        token_payload = auth_context.get("token")
        validate_scope = getattr(oauth_provider, "validate_scope", None)
        if not callable(validate_scope) or not isinstance(token_payload, dict):
            error = self._tool_error(name, "UNAUTHORIZED", "OAuth token is invalid.")
            return self._with_oauth_authenticate_challenge(
                error,
                oauth_provider=oauth_provider,
                error="invalid_token",
                error_description="The OAuth access token is invalid.",
            )
        required_scopes = self._required_scopes_for_tool(name, params)
        missing_scopes = [scope for scope in required_scopes if not validate_scope(token_payload, scope)]
        if not missing_scopes:
            return None
        required_scope = " ".join(missing_scopes)
        error = self._tool_error(
            name,
            "INSUFFICIENT_SCOPE",
            "OAuth token scope is insufficient for this tool.",
            {
                "required_scope": required_scope,
                "required_scopes": list(required_scopes),
                "missing_scopes": missing_scopes,
            },
        )
        return self._with_oauth_authenticate_challenge(
            error,
            oauth_provider=oauth_provider,
            required_scope=required_scope,
            error="insufficient_scope",
            error_description="The OAuth access token is missing the required scope.",
        )

    def _with_oauth_authenticate_challenge(
        self,
        tool_error: dict[str, Any],
        *,
        oauth_provider: object,
        error: str,
        error_description: str,
        required_scope: str | None = None,
    ) -> dict[str, Any]:
        metadata_url_builder = getattr(oauth_provider, "protected_resource_metadata_url", None)
        if not callable(metadata_url_builder):
            return tool_error
        metadata_url = metadata_url_builder()
        if not isinstance(metadata_url, str) or not metadata_url.startswith("https://"):
            return tool_error
        fields = [
            f'resource_metadata="{metadata_url}"',
            f'error="{error}"',
            f'error_description="{error_description}"',
        ]
        if isinstance(required_scope, str) and required_scope and all(
            scope in VALID_MCP_SCOPES for scope in required_scope.split()
        ):
            fields.insert(1, f'scope="{required_scope}"')
        enriched = dict(tool_error)
        enriched["_meta"] = {"mcp/www_authenticate": [f"Bearer {', '.join(fields)}"]}
        return enriched

    def _external_oauth_remote_policy_error(
        self,
        name: str,
        params: dict[str, Any],
        auth_context: MCPAuthContext,
    ) -> dict[str, Any] | None:
        if not isinstance(auth_context, dict) or auth_context.get("mode") != "external-oauth":
            return None
        if (
            name == "run_mcp_workflow"
            and _policy_string_param(params, "workflow") == GATE_REVIEW_WORKFLOW
            and _policy_string_param(params, "phase") == "apply"
        ):
            loaded = OperatorSettingsStore().load()
            if not loaded.get("ok"):
                return self._tool_error(
                    name,
                    str(loaded.get("error_code") or "OPERATOR_CONFIG_INVALID"),
                    "Private Gate review policy is unavailable.",
                )
            decision = evaluate_operator_principal(auth_context, loaded["settings"])
            if not decision.allowed:
                return self._tool_error(
                    name,
                    decision.error_code,
                    "Private Gate review policy denied this principal.",
                )
            principal = principal_from_auth_context(auth_context)
            if principal is None or not principal.trusted:
                return self._tool_error(
                    name,
                    "WORK_ITEM_PRIVATE_PRINCIPAL_REQUIRED",
                    "Private Gate review requires authenticated Work Item authority claims.",
                )
            return None
        if name == "run_mcp_workflow" and _policy_string_param(params, "workflow") == "operator_batch":
            loaded = OperatorSettingsStore().load()
            if not loaded.get("ok"):
                return self._tool_error(
                    name,
                    str(loaded.get("error_code") or "OPERATOR_CONFIG_INVALID"),
                    "Operator policy is unavailable.",
                )
            decision = evaluate_operator_principal(auth_context, loaded["settings"])
            if decision.allowed:
                return None
            return self._tool_error(
                name,
                decision.error_code,
                "Operator policy denied this principal.",
            )
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
        auth_context: MCPAuthContext,
    ) -> dict[str, Any] | None:
        if not isinstance(auth_context, dict) or auth_context.get("mode") != "cloud-relay":
            return None
        granted_scopes = auth_context.get("scopes", [])
        if not isinstance(granted_scopes, list):
            return self._tool_error(name, "UNAUTHORIZED", "cloud-relay scopes 无效。")
        required_scopes = self._required_scopes_for_tool(name, params)
        if all(scope in granted_scopes for scope in required_scopes):
            return None
        required_scope = " ".join(required_scopes)
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

    def _resolve_project_route_context(
        self,
        params: dict[str, Any],
        *,
        require_managed: bool,
    ) -> ProjectRouteContext:
        if require_managed:
            project_root, _ = self._resolve_managed_project_context(params)
        else:
            project_root, _ = self._resolve_read_only_project_context(params)
        raw_project_name = params.get("project_name")
        public_project_name = (
            raw_project_name.strip()
            if isinstance(raw_project_name, str)
            else None
        )
        return ProjectRouteContext(
            project_root=project_root,
            public_project_name=public_project_name,
            require_managed=require_managed,
        )

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
        context = self._resolve_project_route_context(
            params,
            require_managed=require_managed,
        )
        routed_server = self._project_route_server_factory.create(
            context,
            TOOL_ROUTE_CONTINUATIONS,
        )
        routed_tool = routed_server.tools.get(tool_name)
        if not callable(routed_tool):
            raise MCPToolInputError("TOOL_NOT_FOUND", f"未知 tool：{tool_name}")
        routed_params = self._strip_project_name_param(params)
        routed_params.pop("project_root", None)
        if context.public_project_name:
            # Keep the public registry identity available to the routed server
            # only for context revalidation.  It carries no authority and is
            # removed before any lower-level manager sees parameters.
            routed_params["__context_binding_project_name"] = (
                context.public_project_name
            )
        result = routed_tool(routed_params)
        if isinstance(result, dict) and context.public_project_name:
            self._inject_project_name_into_routed_result(
                result,
                context.public_project_name,
            )
            self._inject_project_name_into_nested_actions(
                result,
                context.public_project_name,
            )
        return result

    def _inject_project_name_into_nested_actions(self, value: Any, project_name: str) -> None:
        singular_action_keys = {
            "next_action",
            "safe_next_action",
            "recommended_next_action",
            "primary_next_action",
            "copyable_tool_call",
            "copyable_apply_call",
        }
        plural_action_keys = {
            "next_actions",
            "safe_next_actions",
            "recommended_next_steps",
            "recommended_next_actions",
        }
        if isinstance(value, dict):
            for key, nested in value.items():
                if key in singular_action_keys and isinstance(nested, dict):
                    _inject_project_name_into_action(nested, project_name)
                elif key in plural_action_keys and isinstance(nested, list):
                    for action in nested:
                        if isinstance(action, dict):
                            _inject_project_name_into_action(action, project_name)
                self._inject_project_name_into_nested_actions(nested, project_name)
        elif isinstance(value, list):
            for nested in value:
                self._inject_project_name_into_nested_actions(nested, project_name)

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
                "Submission creation remains separated behind `fill_submission_evidence_files` with `mcp:commit` scope. Replacing explicitly unfinished manifest-bound Markdown uses the digest-bound `manage_submission_evidence_revision` preview/apply flow and keeps its ready field false. Ready fields remain false until a human reviewer confirms final evidence.",
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


    def _tool_get_release_submission_readiness(self, params: dict[str, Any]) -> dict[str, Any]:
        project_root, project_record = self._resolve_read_only_project_context(params)
        project_name = self._project_name_for_context(project_root, project_record, params)
        result = build_release_submission_readiness(
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
        work_item_id = params.get("work_item_id")
        if isinstance(work_item_id, str) and work_item_id.strip():
            try:
                result["work_item_reference"] = AppSubmissionWorkItemCommands(
                    project_root
                ).reference_existing(work_item_id.strip())
            except WorkItemGovernanceError as exc:
                raise MCPToolInputError(exc.code, str(exc), exc.details) from exc
        result["work_item_command_boundary"] = {
            "create_path": ["preview_work_item_create", "apply_work_item_create"],
            "reference_path": "get_work_item",
            "direct_ledger_write": False,
            "automatic_work_item_creation": False,
        }
        return result






    def _tool_get_stable_replacement_cadence(self, params: dict[str, Any]) -> dict[str, Any]:
        project_root, _ = self._resolve_read_only_project_context(params)
        local_service = self._connector_runtime_local_service_evidence(project_root)
        runtime_status = self._runtime_version_status_for_project(project_root, local_service=local_service)
        return self._stable_replacement_hint(project_root, runtime_status)

    def _collect_continuation_snapshot_for_project(
        self,
        project_root: str,
        provider: str | None,
    ):
        supplier = getattr(self, "_continuation_snapshot_supplier", None)
        if callable(supplier):
            return supplier(project_root, provider)
        return collect_continuation_snapshot(
            project_root,
            requested_provider=provider,
            planning_bridge=self.bridge,
            source_review=self.source_review,
        )



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




    def _tool_get_stable_promotion_readiness(self, params: dict[str, Any]) -> dict[str, Any]:
        project_root, project_record = self._resolve_read_only_project_context(params)
        project_name = (
            self._project_name_for_context(project_root, project_record, params)
            if params.get("project_name") is not None
            else None
        )
        return self._build_stable_promotion_readiness_packet(
            project_root,
            project_name,
            work_item_id=params.get("work_item_id")
            if isinstance(params.get("work_item_id"), str)
            else None,
        )

    def _build_stable_promotion_readiness_packet(
        self,
        project_root: str,
        project_name: str | None,
        work_item_id: str | None = None,
    ) -> dict[str, Any]:
        result = get_stable_promotion_readiness(
            project_root,
            visible_tool_names=self._visible_tool_names(),
            supported_workflows=list(_SUPPORTED_MCP_WORKFLOWS),
            service_mode=self.service_mode,
            mcp_exposure_profile=self.mcp_exposure_profile,
            registered_projects=self._web_gpt_registered_project_summary(),
        )
        if project_name:
            recommended_next_steps = _find_action_list(result, "recommended_next_steps")
            if recommended_next_steps is not None:
                for action in recommended_next_steps:
                    if isinstance(action, dict):
                        _inject_project_name_into_action(action, project_name)
            for packet_key in ("promotion_artifact_evidence", "promotion_artifact_preview"):
                packet = result.get(packet_key)
                safe_next_action = packet.get("safe_next_action") if isinstance(packet, dict) else None
                if isinstance(safe_next_action, dict):
                    _inject_project_name_into_action(safe_next_action, project_name)
        if work_item_id:
            exact_commit = str(
                (result.get("project") or {}).get("head")
                or (result.get("git") or {}).get("head")
                or ""
            )
            try:
                result["work_item_acceptance_candidate"] = StablePromotionWorkItemReader(
                    project_root
                ).inspect_accepted_candidate(
                    work_item_id=work_item_id,
                    exact_commit=exact_commit,
                )
            except WorkItemGovernanceError as exc:
                raise MCPToolInputError(exc.code, str(exc), exc.details) from exc
        return result

    def _tool_manage_stable_promotion_evidence(self, params: dict[str, Any]) -> dict[str, Any]:
        action_raw = params.get("action")
        action = action_raw.strip().lower() if isinstance(action_raw, str) else ""
        if action not in {"inspect", "status", "preview", "apply", "discard"}:
            raise MCPToolInputError(
                "INVALID_ACTION",
                "action 必须是 inspect、status、preview、apply 或 discard。",
            )
        if params.get("project_name") is not None:
            return self._route_project_name_tool("manage_stable_promotion_evidence", params, require_managed=True)
        manager = MCPStablePromotionEvidenceManager(self.project_root)
        result = manager.handle(action, params)
        work_item_id = params.get("work_item_id")
        if isinstance(work_item_id, str) and work_item_id.strip():
            exact_commit = params.get("candidate_head")
            if not isinstance(exact_commit, str) or not exact_commit:
                exact_commit = str(git_checkout_metadata(self.project_root).get("head") or "")
            try:
                result["work_item_acceptance_candidate"] = StablePromotionWorkItemReader(
                    self.project_root
                ).inspect_accepted_candidate(
                    work_item_id=work_item_id.strip(),
                    exact_commit=exact_commit,
                )
            except WorkItemGovernanceError as exc:
                raise MCPToolInputError(exc.code, str(exc), exc.details) from exc
        self._record_workflow_if_needed("manage_stable_promotion_evidence", action, params, result)
        return self._with_project_identity(result)

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
        return self._runtime_version_status_for_project(
            project_root,
            local_service=self._connector_runtime_local_service_evidence(project_root),
        )

    def _runtime_version_status_for_project(
        self,
        project_root: str,
        *,
        local_service: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        runtime_project_root = loaded_runtime_project_root() or self.project_root
        status = get_runtime_version_status(
            project_root,
            runtime_project_root=runtime_project_root,
            local_service=local_service,
        )
        requested_project = git_checkout_metadata(project_root)
        status["runtime_project_root"] = runtime_project_root
        status["requested_project_checkout"] = requested_project
        status["requested_project_checkout_head"] = requested_project.get("head")
        return status

    def _tool_get_connector_runtime_health_status(self, params: dict[str, Any]) -> dict[str, Any]:
        project_root, _ = self._resolve_read_only_project_context(params)
        tunnel_client = self._connector_external_evidence_param(params, "tunnel_client")
        control_plane = self._connector_external_evidence_param(params, "control_plane")
        local_service = self._connector_runtime_local_service_evidence(project_root)
        return get_connector_runtime_health_status(
            runtime_status=self._runtime_version_status_for_project(project_root, local_service=local_service),
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
        snapshot = self._collect_continuation_snapshot_for_project(
            self.project_root,
            "codex",
        )
        result = dict(snapshot.session_status)
        result["continuation_snapshot"] = snapshot.public_view("codex")
        return self._with_project_identity(result)

    def _tool_get_executor_continuation_preview(self, _: dict[str, Any]) -> dict[str, Any]:
        snapshot = self._collect_continuation_snapshot_for_project(
            self.project_root,
            "codex",
        )
        result = dict(snapshot.continuation_preview)
        result["continuation_snapshot"] = snapshot.public_view("codex")
        return self._with_project_identity(result)

    def _tool_get_executor_continuation_decision(self, params: dict[str, Any]) -> dict[str, Any]:
        provider = params.get("provider")
        if not isinstance(provider, str) or provider.strip().lower() not in {"pi", "codex", "opencode"}:
            raise MCPToolInputError("INVALID_PROVIDER", "provider 必须是 pi、codex 或 opencode。")
        normalized_provider = provider.strip().lower()
        snapshot = self._collect_continuation_snapshot_for_project(
            self.project_root,
            normalized_provider,
        )
        result = dict(snapshot.project(normalized_provider)["canonical_continuation_decision"])
        result["continuation_snapshot"] = snapshot.public_view(normalized_provider)
        return self._with_project_identity(result)

    def _tool_get_executor_resume_invocation_preview(self, params: dict[str, Any]) -> dict[str, Any]:
        provider = params.get("provider")
        if not isinstance(provider, str) or provider.strip().lower() not in {"pi", "codex", "opencode"}:
            raise MCPToolInputError("INVALID_PROVIDER", "provider 必须是 pi、codex 或 opencode。")
        normalized_provider = provider.strip().lower()
        snapshot = self._collect_continuation_snapshot_for_project(
            self.project_root,
            normalized_provider,
        )
        result = dict(snapshot.project(normalized_provider)["resume_invocation_preview"])
        result["continuation_snapshot"] = snapshot.public_view(normalized_provider)
        return self._with_project_identity(result)

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

        continuation_snapshot = self._collect_continuation_snapshot_for_project(
            project_root,
            provider,
        )
        orchestrator = WorkflowOrchestrator(
            project_root=project_root,
            source_review=self.source_review,
            planning_bridge=self.bridge,
            continuation_snapshot=continuation_snapshot,
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
            "canonical_state": fact_snapshot.canonical_state,
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

        if project_record is None and not _CURRENT_FACTS_INTERNAL_ANALYZE.get():
            self._record_workflow_if_needed("analyze_project_state", "analyze", routed_params, legacy)
        return legacy

    def _current_facts_analyze(self, params: dict[str, Any]) -> dict[str, Any]:
        """Collect one canonical snapshot without creating a generic read record.

        ``current_facts`` has its own explicit preview/archive evidence flow.
        Recording the internal analysis would make the fact collection itself
        appear as a source-tree change before its confirmation can be checked.
        """
        token = _CURRENT_FACTS_INTERNAL_ANALYZE.set(True)
        try:
            return self._tool_analyze_project_state(params)
        finally:
            _CURRENT_FACTS_INTERNAL_ANALYZE.reset(token)

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

        if tool == "manage_git_commit" and "manage_git" in visible_names:
            params = action.get("params")
            clean_params = dict(params) if isinstance(params, dict) else {}
            action_name = str(clean_params.get("action") or "").strip().lower()
            git_action = {
                "readiness": "commit_readiness",
                "suggest_commit_message": "commit_message",
                "preview": "commit_preview",
                "commit_workflow_preview": "commit_preview",
                "commit": "commit_apply",
            }.get(action_name)
            if git_action:
                clean_params["action"] = git_action
                action["tool"] = "manage_git"
                action["params"] = clean_params
                return action
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

    @staticmethod
    def _operation_context_identity(
        tool_name: str,
        params: dict[str, Any],
    ) -> tuple[str, str] | None:
        """Return the server-owned intent/unit pair for one public operation."""

        if tool_name == "manage_validation_run":
            return ("validation_run", "operation:validation_run")

        if tool_name in {"manage_git", "manage_git_commit"}:
            action_raw = params.get("action")
            action = action_raw.strip().lower() if isinstance(action_raw, str) else ""
            if action in {
                "commit_readiness",
                "commit_message",
                "commit_preview",
                "commit_apply",
                "readiness",
                "suggest_commit_message",
                "commit_workflow_preview",
                "preview",
                "commit",
            }:
                intent = "git_commit"
            elif action in {"push_status", "push_preview", "push_apply"}:
                intent = "git_push"
            elif action in {"pull_status", "pull_preview", "pull_apply"}:
                intent = "git_pull"
            elif action in {"restore_file_preview", "restore_file_apply"}:
                intent = "git_restore_file"
            elif action in {"revert_preview", "revert_apply"}:
                intent = "git_revert"
            else:
                return None
            return (intent, f"operation:{intent}")

        if tool_name == "run_mcp_workflow":
            workflow = _normalize_run_mcp_workflow_name(params.get("workflow"))
            if workflow in {
                REVIEW_MANIFEST_WORKFLOW,
                MCP_RESULT_ARTIFACT_WORKFLOW,
                GATE_REVIEW_WORKFLOW,
            }:
                # The manifest has a caller-owned review_unit and its own
                # immutable read-session verifier. Result artifacts have a
                # pre-issued opaque read handle plus expiry/SHA contract. Gate
                # Review has its own stricter, signed Work Item Gate contract
                # (task/state/evidence binding plus explicit confirmation).
                # Do not overlay a generic Git/Runner binding on those
                # dedicated contracts.
                return None
            if not workflow:
                return None
            # These high-level workflow names are intentionally the same
            # operation identity used by the public Git tool.  A ChatGPT user
            # may preview through run_mcp_workflow and then confirm through
            # manage_git, so treating the wrappers as unrelated would make a
            # valid preview binding unusable.
            if workflow in {"git_commit", "git_restore_file", "git_revert"}:
                intent = workflow
            else:
                intent = f"workflow:{workflow}"
            return (intent, f"operation:{intent}")

        return None

    @staticmethod
    def _operation_context_required(tool_name: str, params: dict[str, Any]) -> bool:
        if _OPERATOR_BATCH_INTERNAL_DISPATCH.get():
            # The public operator_batch execute boundary has already verified
            # one project binding before its ticketed, capability-gated steps
            # are dispatched.  Requiring a caller-supplied second binding here
            # would make an immutable ticket impossible to execute.
            return False
        action_raw = params.get("action")
        action = action_raw.strip().lower() if isinstance(action_raw, str) else ""
        if tool_name == "manage_validation_run":
            return action == "run"
        if tool_name == "manage_git":
            return action in {
                "commit_apply",
                "push_apply",
                "pull_apply",
                "restore_file_apply",
                "revert_apply",
            }
        if tool_name == "manage_git_commit":
            return action == "commit"
        if tool_name == "run_mcp_workflow":
            workflow = _normalize_run_mcp_workflow_name(params.get("workflow"))
            if workflow in {
                REVIEW_MANIFEST_WORKFLOW,
                MCP_RESULT_ARTIFACT_WORKFLOW,
                GATE_REVIEW_WORKFLOW,
            }:
                return False
            phase_raw = params.get("phase")
            phase = phase_raw.strip().lower() if isinstance(phase_raw, str) else ""
            return phase in WORKFLOW_CONTEXT_MUTATION_PHASES.get(workflow, frozenset())
        return False

    @staticmethod
    def _operation_context_has_matching_confirmation(
        tool_name: str,
        params: dict[str, Any],
    ) -> bool:
        """Whether this operation identity has a later bound side effect.

        A preview itself does not require a binding as input, but the returned
        contract must make clear that its matching confirmation will.  Keeping
        that signal separate from ``_operation_context_required`` avoids
        telling ChatGPT that a read/preview call was itself a confirmation.
        """

        if MCPPlanningBridgeServer._operation_context_identity(tool_name, params) is None:
            return False
        if tool_name == "manage_validation_run":
            return True
        if tool_name in {"manage_git", "manage_git_commit"}:
            return True
        if tool_name == "run_mcp_workflow":
            workflow = _normalize_run_mcp_workflow_name(params.get("workflow"))
            return workflow in WORKFLOW_CONTEXT_MUTATION_PHASES
        return False

    @staticmethod
    def _context_binding_project_name(params: dict[str, Any]) -> str | None:
        for key in ("project_name", "__context_binding_project_name"):
            value = params.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    def _context_binding_project_root(self, params: dict[str, Any]) -> str:
        project_name = params.get("project_name")
        if isinstance(project_name, str) and project_name.strip():
            project_root, _ = self._resolve_managed_project_context(params)
            return project_root
        return self.project_root

    def _collect_operation_context_binding(
        self,
        tool_name: str,
        params: dict[str, Any],
    ) -> dict[str, Any] | None:
        identity = self._operation_context_identity(tool_name, params)
        if identity is None:
            return None
        workflow_intent, review_unit = identity
        return collect_project_context_binding(
            self._context_binding_project_root(params),
            project_name=self._context_binding_project_name(params),
            review_unit=review_unit,
            workflow_intent=workflow_intent,
        )

    def _require_operation_context_binding(
        self,
        tool_name: str,
        params: dict[str, Any],
    ) -> dict[str, Any] | None:
        if not self._operation_context_required(tool_name, params):
            return None
        identity = self._operation_context_identity(tool_name, params)
        if identity is None:
            return None
        workflow_intent, review_unit = identity
        try:
            return require_operation_context_binding(
                params.get("context_binding"),
                project_root=self._context_binding_project_root(params),
                project_name=self._context_binding_project_name(params),
                review_unit=review_unit,
                workflow_intent=workflow_intent,
            )
        except ProjectContextBindingError as exc:
            raise MCPToolInputError(exc.error_code, exc.message, exc.details) from exc

    @staticmethod
    def _strip_operation_context_binding_params(params: dict[str, Any]) -> dict[str, Any]:
        clean = dict(params)
        clean.pop("context_binding", None)
        clean.pop("__context_binding_project_name", None)
        return clean

    def _attach_operation_context_binding(
        self,
        result: dict[str, Any],
        *,
        tool_name: str,
        params: dict[str, Any],
        verified_binding: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(result, dict):
            return result
        self._attach_canonical_state_to_operation_status(result, params)
        binding = self._collect_operation_context_binding(tool_name, params)
        if binding is None:
            action_raw = params.get("action")
            action = (
                action_raw.strip().lower()
                if isinstance(action_raw, str)
                else ""
            )
            commander_routed_read = (
                self.mcp_exposure_profile == MCP_EXPOSURE_PROFILE_COMMANDER
                or isinstance(params.get("__context_binding_project_name"), str)
            )
            if (
                tool_name == "manage_git"
                and commander_routed_read
                and action
                in {
                    "diff",
                    "diff_commits",
                    "history_log",
                    "history_show",
                    "review_context",
                    "status",
                }
            ):
                # Read-only Git facts still bind to the observed project,
                # branch, HEAD, Runner plan and current version.  This base
                # binding is evidence only; it is not an operation authority
                # and does not add a confirmation gate.
                result["context_binding"] = collect_project_context_binding(
                    self._context_binding_project_root(params),
                    project_name=self._context_binding_project_name(params),
                )
                return result
            workflow = (
                _normalize_run_mcp_workflow_name(params.get("workflow"))
                if tool_name == "run_mcp_workflow"
                else ""
            )
            if workflow == GATE_REVIEW_WORKFLOW:
                # Gate Review keeps its signed Work Item preview as the sole
                # apply authority.  N1 still exposes the existing base
                # Context Binding as an observation so the public
                # confirmation is visibly tied to the routed project without
                # overlaying a second authorization gate.
                result["context_binding"] = collect_project_context_binding(
                    self.project_root,
                    project_name=self._context_binding_project_name(params),
                )
            return result
        identity = self._operation_context_identity(tool_name, params)
        if identity is None:
            return result
        result["context_binding"] = binding
        result["context_binding_contract"] = {
            "schema_version": PROJECT_CONTEXT_BINDING_SCHEMA_VERSION,
            "confirmation_required": self._operation_context_has_matching_confirmation(
                tool_name,
                params,
            ),
            "current_call_requires_context_binding": self._operation_context_required(
                tool_name,
                params,
            ),
            "workflow_intent": identity[0],
            "review_unit": identity[1],
            "context_binding_sha256": context_binding_sha256(binding),
        }
        if verified_binding is not None:
            result["context_binding_verification"] = {
                "status": "matched",
                "context_binding_sha256": context_binding_sha256(verified_binding),
            }
        self._inject_operation_context_into_next_actions(
            result,
            binding=binding,
            identity=identity,
        )
        return result

    def _attach_canonical_state_to_operation_status(
        self,
        result: dict[str, Any],
        params: dict[str, Any],
    ) -> None:
        """Point a legacy manager-local status at the canonical state model.

        Core workflows already receive this projection from
        ``WorkflowOrchestrator``.  The public Git facade can also surface a
        legacy manager ``unified_status`` directly, so refresh the same bounded
        fact snapshot there instead of letting that local status masquerade as
        global truth.  A failed supplementary observation never changes the
        result of the requested operation.
        """

        local_status = result.get("unified_status")
        if not isinstance(local_status, dict):
            return
        if isinstance(local_status.get("canonical_project_state"), dict):
            local_status.setdefault("status_scope", "operation_local")
            return
        provider_raw = params.get("provider")
        provider = (
            provider_raw.strip().lower()
            if isinstance(provider_raw, str)
            and provider_raw.strip().lower() in {"pi", "codex", "opencode"}
            else None
        )
        try:
            continuation_snapshot = self._collect_continuation_snapshot_for_project(
                self.project_root,
                provider,
            )
            snapshot = WorkflowOrchestrator(
                project_root=self.project_root,
                source_review=self.source_review,
                planning_bridge=self.bridge,
                continuation_snapshot=continuation_snapshot,
            ).build_fact_snapshot(provider=provider, include_reports=True)
        except Exception:
            # The manager-local status remains marked as local.  Callers can
            # make the explicit analyze_project_state read for a fresh retry.
            local_status["status_scope"] = "operation_local"
            local_status["canonical_project_state"] = {
                "schema_version": CANONICAL_PROJECT_STATE_SCHEMA_VERSION,
                "status": "unavailable",
                "reason_code": "canonical_snapshot_unavailable",
            }
            return
        canonical = snapshot.canonical_state
        local_status["status_scope"] = "operation_local"
        local_status["canonical_project_state"] = {
            "schema_version": canonical.get("schema_version"),
            "observed_at": canonical.get("observed_at"),
            "context_binding": canonical.get("context_binding"),
            "freshness": canonical.get("freshness"),
            "current_conclusion": canonical.get("current_conclusion"),
        }

    @staticmethod
    def _add_manage_git_confirmation_next_action(
        result: dict[str, Any],
        *,
        action: str,
    ) -> None:
        """Make a preview's public confirmation call explicit and copyable."""

        apply_action = {
            "commit_preview": "commit_apply",
            "push_preview": "push_apply",
            "pull_preview": "pull_apply",
            "restore_file_preview": "restore_file_apply",
            "revert_preview": "revert_apply",
        }.get(action)
        preview_id = result.get("preview_id") if isinstance(result, dict) else None
        if (
            not apply_action
            or result.get("ok") is not True
            or not isinstance(preview_id, str)
            or not preview_id.strip()
        ):
            return
        actions = result.get("next_actions")
        if not isinstance(actions, list):
            actions = []
            result["next_actions"] = actions
        if any(
            isinstance(item, dict)
            and item.get("tool") == "manage_git"
            and isinstance(item.get("params"), dict)
            and item["params"].get("action") == apply_action
            for item in actions
        ):
            return
        actions.append(
            {
                "tool": "manage_git",
                "params": {"action": apply_action, "preview_id": preview_id.strip()},
                "reason": "确认并执行已生成的受控 Git preview。",
                "requires_confirmation": True,
            }
        )

    def _inject_operation_context_into_next_actions(
        self,
        result: dict[str, Any],
        *,
        binding: dict[str, Any],
        identity: tuple[str, str],
    ) -> None:
        for key in ("next_actions", "recommended_next_actions"):
            actions = result.get(key)
            if not isinstance(actions, list):
                continue
            for next_action in actions:
                if not isinstance(next_action, dict):
                    continue
                tool = next_action.get("tool")
                if not isinstance(tool, str):
                    continue
                for params_key in ("params", "arguments"):
                    target_params = next_action.get(params_key)
                    if not isinstance(target_params, dict):
                        continue
                    target_identity = self._operation_context_identity(tool, target_params)
                    if (
                        target_identity == identity
                        and self._operation_context_required(tool, target_params)
                    ):
                        target_params.setdefault("context_binding", dict(binding))

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

        verified_binding = self._require_operation_context_binding("manage_git", params)

        def _with_common_fields(result: dict[str, Any], delegated_tool: str) -> dict[str, Any]:
            if isinstance(result, dict):
                result["delegated_tool"] = delegated_tool
                result["action"] = action
            return result

        def record_and_return(result: dict[str, Any], tool: str) -> dict[str, Any]:
            self._add_manage_git_confirmation_next_action(result, action=action)
            self._record_workflow_if_needed("manage_git", action, params, result)
            return self._attach_operation_context_binding(
                _with_common_fields(result, tool),
                tool_name="manage_git",
                params=params,
                verified_binding=verified_binding,
            )

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

        verified_binding = self._require_operation_context_binding("manage_git_commit", params)
        if params.get("project_name") is not None:
            return self._route_project_name_tool("manage_git_commit", params, require_managed=True)

        def finish(result: dict[str, Any]) -> dict[str, Any]:
            return self._attach_operation_context_binding(
                result,
                tool_name="manage_git_commit",
                params=params,
                verified_binding=verified_binding,
            )

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
            return finish(manager.readiness(
                include_diff_summary=include_diff_summary,
                max_diff_chars=max_diff_chars,
                include_files=include_files,
                exclude_files=exclude_files,
            ))

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
            return finish(result)

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
            return finish(result)

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
            return finish(result)

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
        return finish(result)

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
        review_manifest_id = params.get("review_manifest_id")
        manifest_workflow = MCPManifestValidationWorkflow(self)
        try:
            if action == "preview" and review_manifest_id is not None:
                return manifest_workflow.preview(params)
            if action == "run":
                manifest_result = manifest_workflow.try_run(params)
                if manifest_result is not None:
                    return manifest_result
            if action == "status":
                source_only_status = manifest_workflow.try_source_only_status(params)
                if source_only_status is not None:
                    return source_only_status
        except ManifestValidationWorkflowError as exc:
            raise MCPToolInputError(exc.error_code, exc.message, exc.details) from exc
        if review_manifest_id is not None:
            raise MCPToolInputError(
                "MANIFEST_VALIDATION_PREVIEW_REQUIRED",
                "review_manifest_id 仅可用于 manage_validation_run action=preview；请先生成受控 validation preview。",
            )
        verified_binding = self._require_operation_context_binding(
            "manage_validation_run",
            params,
        )
        if params.get("project_name") is not None:
            return self._route_project_name_tool("manage_validation_run", params, require_managed=True)
        manager = MCPValidationRunManager(self.project_root)
        result = manager.handle(
            action,
            self._strip_operation_context_binding_params(params),
        )
        self._record_workflow_if_needed("manage_validation_run", action, params, result)
        return self._attach_operation_context_binding(
            self._with_project_identity(result),
            tool_name="manage_validation_run",
            params=params,
            verified_binding=verified_binding,
        )

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

    def _operator_preview_validation(self, operation: dict[str, Any]) -> dict[str, Any]:
        preview_id = operation.get("preview_id")
        if not isinstance(preview_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,96}", preview_id):
            return {"ok": False, "error_code": "OPERATOR_PREVIEW_NOT_FOUND"}
        runner_dir = resolve_project_runner_dir(self.project_root)
        tool = operation.get("tool")
        action = operation.get("operation")
        phase = operation.get("phase")
        directory_names: tuple[tuple[str, ...], ...]
        artifact_profile: str
        if tool == "manage_git" or (tool == "run_mcp_workflow" and action == "git_commit"):
            directory_names = (("runtime", "commit-previews"),)
            artifact_profile = "commit"
        elif tool == "manage_validation_run":
            directory_names = (("runtime", "validation-run-previews"),)
            artifact_profile = "validation"
        elif tool == "run_mcp_workflow" and action in {"small_project_patch", "docs_update"}:
            directory_names = (("runtime", "project-patch-previews"),)
            artifact_profile = "project_patch"
        elif tool == "run_mcp_workflow" and action == "agent_dispatch" and phase == "run":
            directory_names = (("runtime", "executor-workflow-previews"),)
            artifact_profile = "executor"
        elif tool == "run_mcp_workflow" and action == "prompt_to_plan" and phase in {"apply", "apply_all"}:
            directory_names = (("runtime", "prompt-file-previews"),)
            artifact_profile = "prompt_file"
        elif tool == "run_mcp_workflow" and action == "prompt_to_plan" and phase == "run":
            directory_names = (("runtime", "executor-workflow-previews"),)
            artifact_profile = "executor"
        elif tool == "run_mcp_workflow" and action in {"plan_update", "agent_dispatch", "prompt_to_plan"}:
            directory_names = (("plan-patches",),)
            artifact_profile = "plan_patch"
        else:
            return {"ok": False, "error_code": "OPERATOR_OPERATION_DENIED"}
        candidate_dirs = tuple(os.path.join(runner_dir, *parts) for parts in directory_names)
        for directory in candidate_dirs:
            root = os.path.abspath(directory)
            if os.path.realpath(root) != root:
                return {"ok": False, "error_code": "OPERATOR_PREVIEW_UNSAFE"}
            path = os.path.join(root, f"{preview_id}.json")
            resolved_path = os.path.realpath(path)
            if not resolved_path.startswith(root + os.sep):
                continue
            try:
                info = os.lstat(path)
                if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                    continue
                flags = os.O_RDONLY
                if hasattr(os, "O_NOFOLLOW"):
                    flags |= os.O_NOFOLLOW
                fd = os.open(path, flags)
                with os.fdopen(fd, "rb") as handle:
                    opened = os.fstat(handle.fileno())
                    if not stat.S_ISREG(opened.st_mode):
                        return {"ok": False, "error_code": "OPERATOR_PREVIEW_UNSAFE"}
                    raw = handle.read(1_000_001)
                if len(raw) > 1_000_000:
                    return {"ok": False, "error_code": "OPERATOR_PREVIEW_INVALID"}
                payload = json.loads(raw.decode("utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict):
                continue
            project_root = payload.get("project_root")
            if not isinstance(project_root, str) or os.path.realpath(project_root) != os.path.realpath(self.project_root):
                return {"ok": False, "error_code": "OPERATOR_PROJECT_MISMATCH"}
            id_field = "patch_id" if artifact_profile == "plan_patch" else "preview_id"
            if payload.get(id_field) != preview_id:
                return {"ok": False, "error_code": "OPERATOR_PREVIEW_KIND_MISMATCH"}
            if artifact_profile == "commit" and payload.get("can_commit") is not True:
                return {"ok": False, "error_code": "OPERATOR_PREVIEW_BLOCKED"}
            if artifact_profile == "validation" and payload.get("artifact_kind") != "validation_run":
                return {"ok": False, "error_code": "OPERATOR_PREVIEW_KIND_MISMATCH"}
            if artifact_profile == "project_patch" and payload.get("mode") not in {
                "exact_replace", "unified_diff", "delete_file",
            }:
                return {"ok": False, "error_code": "OPERATOR_PREVIEW_KIND_MISMATCH"}
            if artifact_profile == "prompt_file" and payload.get("action") != "prompt_file_preview":
                return {"ok": False, "error_code": "OPERATOR_PREVIEW_KIND_MISMATCH"}
            if artifact_profile == "executor" and payload.get("artifact_kind") != "run_once":
                return {"ok": False, "error_code": "OPERATOR_PREVIEW_KIND_MISMATCH"}
            if artifact_profile == "plan_patch":
                if payload.get("operation") not in {"insert_version", "update_version"}:
                    return {"ok": False, "error_code": "OPERATOR_PREVIEW_KIND_MISMATCH"}
                if payload.get("status") in {"APPLIED", "FAILED", "STALE"}:
                    return {"ok": False, "error_code": "OPERATOR_PREVIEW_ALREADY_CONSUMED"}
            expires_at = payload.get("expires_at")
            if artifact_profile != "plan_patch" and (not isinstance(expires_at, str) or not expires_at):
                return {"ok": False, "error_code": "OPERATOR_PREVIEW_INVALID"}
            if isinstance(expires_at, str) and expires_at:
                try:
                    expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                except ValueError:
                    return {"ok": False, "error_code": "OPERATOR_PREVIEW_INVALID"}
                if expiry.tzinfo is None:
                    return {"ok": False, "error_code": "OPERATOR_PREVIEW_INVALID"}
                if datetime.now(timezone.utc) > expiry:
                    return {"ok": False, "error_code": "OPERATOR_PREVIEW_EXPIRED"}
            if payload.get("committed_at") or payload.get("applied_at") or payload.get("consumed_at"):
                return {"ok": False, "error_code": "OPERATOR_PREVIEW_ALREADY_CONSUMED"}
            return {
                "ok": True,
                "preview_digest": canonical_artifact_digest(payload),
            }
        return {"ok": False, "error_code": "OPERATOR_PREVIEW_NOT_FOUND"}

    def _operator_internal_dispatch(
        self,
        capability: object,
        tool_name: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        if capability is not OPERATOR_DISPATCH_CAPABILITY:
            return {"ok": False, "error_code": "OPERATOR_INTERNAL_CAPABILITY_DENIED"}
        if tool_name not in {"run_mcp_workflow", "manage_validation_run", "manage_git"}:
            return {"ok": False, "error_code": "OPERATOR_OPERATION_DENIED"}
        if (
            tool_name == "run_mcp_workflow"
            and params.get("workflow") == "plan_update"
            and params.get("phase") == "apply"
        ):
            patch_id = params.get("patch_id")
            if not isinstance(patch_id, str) or not patch_id.strip():
                return {"ok": False, "error_code": "OPERATOR_PREVIEW_NOT_FOUND"}
            try:
                result = self.bridge.apply_plan_patch(self.project_root, patch_id.strip())
            except Exception:
                return {"ok": False, "error_code": "OPERATOR_STEP_ERROR"}
            if not isinstance(result, dict):
                return {"ok": False, "error_code": "OPERATOR_STEP_ERROR"}
            self._record_workflow_if_needed("run_mcp_workflow", "plan_update", params, result)
            return result
        handler = self.tools.get(tool_name)
        if not callable(handler):
            return {"ok": False, "error_code": "OPERATOR_OPERATION_DENIED"}
        token = _OPERATOR_BATCH_INTERNAL_DISPATCH.set(True)
        try:
            result = handler(dict(params))
        finally:
            _OPERATOR_BATCH_INTERNAL_DISPATCH.reset(token)
        if isinstance(result, dict) and result.get("ok") is not True:
            nested = result.get("result")
            nested_code = nested.get("error_code") if isinstance(nested, dict) else None
            if nested_code == "OPERATOR_PREVIEW_CHANGED":
                return {"ok": False, "error_code": "OPERATOR_PREVIEW_CHANGED"}
        return result if isinstance(result, dict) else {"ok": False, "error_code": "OPERATOR_STEP_ERROR"}

    def _operator_batch_service(self) -> OperatorBatchService:
        return OperatorBatchService(
            settings_store=OperatorSettingsStore(),
            permit_store=OperatorPermitStore(),
            preview_validator=self._operator_preview_validation,
            dispatch=self._operator_internal_dispatch,
        )

    def _operator_target_server(self, params: dict[str, Any]) -> "MCPPlanningBridgeServer":
        context = self._resolve_project_route_context(
            params,
            require_managed=True,
        )
        if os.path.realpath(context.project_root) == os.path.realpath(self.project_root):
            return self
        return self._project_route_server_factory.create(
            context,
            OPERATOR_TARGET_ISOLATED,
        )

    def _operator_batch_service_for_params(self, params: dict[str, Any]) -> OperatorBatchService:
        return self._operator_target_server(params)._operator_batch_service()

    def _workflow_compatibility_service(self) -> MCPWorkflowCompatibilityService:
        """Construct the stateless legacy-workflow compatibility service."""

        return MCPWorkflowCompatibilityService(
            self,
            commander_exposure_profile=MCP_EXPOSURE_PROFILE_COMMANDER,
            result_artifact_id_re=MCP_RESULT_ARTIFACT_ID_RE,
        )

    def _workflow_compatibility_result(
        self,
        handler_name: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """Translate bounded compatibility errors at the MCP transport edge."""

        service = self._workflow_compatibility_service()
        handler = getattr(service, handler_name)
        try:
            return handler(params)
        except WorkflowCompatibilityError as exc:
            raise MCPToolInputError(exc.error_code, exc.message, exc.details) from exc

    def _tool_operator_batch(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._workflow_compatibility_result("handle_operator_batch", params)

    def _tool_review_manifest(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._workflow_compatibility_result("handle_review_manifest", params)

    def _tool_review_manifest_entry(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._workflow_compatibility_result("handle_review_manifest_entry", params)

    def _tool_read_result_artifact(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._workflow_compatibility_result("handle_read_result_artifact", params)

    def _tool_result_artifact(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._workflow_compatibility_result("handle_result_artifact", params)

    def _tool_run_mcp_workflow(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._workflow_compatibility_result("handle_run_mcp_workflow", params)

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

    def _protocol_error(
        self,
        req_id: Any,
        code: int,
        error_code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        data: dict[str, Any] = {"error_code": error_code}
        if details:
            data["details"] = details
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {
                "code": code,
                "message": message,
                "data": data,
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
