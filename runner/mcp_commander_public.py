"""The compact, path-safe public projection for the nine-tool Commander app."""

from __future__ import annotations

import copy
import re
from typing import Any

from runner.canonical_project_state import CANONICAL_PROJECT_STATE_SCHEMA_VERSION
from runner.commander_contract import (
    COMMANDER_RESPONSE_SCHEMA_VERSION,
    build_commander_response,
    validate_commander_response,
)
from runner.commander_projections import CommanderProjectionService
from runner.mcp_gate_review_workflow import GATE_REVIEW_WORKFLOW
from runner.mcp_workflow_migration import RESULT_ARTIFACT_WORKFLOW
from runner.project_context_binding import BASE_CONTEXT_BINDING_FIELDS
from runner.review_manifest import REVIEW_MANIFEST_WORKFLOW


COMMANDER_EXPOSED_TOOLS = (
    "list_registered_projects",
    "get_apps_connector_smoke_packet",
    "render_commander_app",
    "analyze_project_state",
    "review_manifest",
    "read_result_artifact",
    "run_mcp_workflow",
    "manage_validation_run",
    "manage_git",
)
COMMANDER_CLIENT_EXPERIENCE_CONTRACT_VERSION = "commander_client_experience.v1"
# These are deliberately examples rather than a second catalog.  The normal
# loopback catalog remains the source of truth for Local Codex; this short list
# documents the capability families that must not leak into the nine-tool
# ChatGPT Commander surface.
COMMANDER_LOCAL_CODEX_ADVANCED_TOOL_EXAMPLES = (
    "get_agent_consumer_contract",
    "get_agent_operator_flow_packet",
    "manage_executor_config",
    "manage_executor_workflow",
    "manage_p1_release_evidence",
    "manage_files",
    "inspect_executor_activity",
    "manage_workflow_run",
)
COMMANDER_PUBLIC_RESULT_ARTIFACT_CONTRACT_FIELDS = (
    "artifact_id",
    "resource_uri",
    "page_uri_template",
    "page_count",
    "content_sha256",
    "expires_at",
)
COMMANDER_PUBLIC_RESPONSE_MINIMIZATION_VERSION = "commander_public_minimal.v1"
COMMANDER_PUBLIC_COMPACT_TOOLS = frozenset(
    {
        "list_registered_projects",
        "get_apps_connector_smoke_packet",
        "render_commander_app",
        "analyze_project_state",
    }
)
COMMANDER_PUBLIC_CONTEXT_BINDING_KEYS = frozenset(
    {
        "context_binding",
        # This is an inspect-issued, exact context contract for the read-only
        # Stage 7 -> 9 journey.  It has the same closed schema as the normal
        # confirmation binding, including meaningful ``null`` values for a
        # source-only runner plan/current version.  Treating it as an ordinary
        # nested object would drop those nulls during projection and make an
        # otherwise verbatim follow-up context impossible to validate.
        "stage_7_9_context",
    }
)
COMMANDER_PUBLIC_ALWAYS_OMIT_KEYS = frozenset(
    {
        "audit_id",
        "delegated_tool",
        "evidence_path",
        "evidence_paths",
        "evidence_refs",
        "event_id",
        "loaded_source_root",
        "log",
        "log_path",
        "logs",
        "operator_confirmation_ref",
        "pid",
        "ppid",
        "project_id",
        "project_identity",
        "project_root",
        "raw_log",
        "raw_logs",
        "record_id",
        "registry_path",
        "report_id",
        "request_id",
        "runtime_dir",
        "runtime_project_root",
        "session_ref",
        "session_id",
        "settings_path",
        "source_root",
        "stable_runtime_dir",
        "stderr",
        "stdout",
        "trace_id",
        "workflow_id",
        "workflow_record_warning",
        "workspace_root",
    }
)
COMMANDER_PUBLIC_COMPACT_OMIT_KEYS = frozenset(
    {
        "action_fingerprint",
        "action_id",
        "action_key",
        "accepted_commit",
        "accepted_commit_subject",
        "candidate_head",
        "changed_files",
        "commit",
        "commit_subject",
        "commits",
        "files",
        "head",
        "ignored_files",
        "item_id",
        "loaded_runtime_head",
        "recent_commits",
        "repo_overview",
        "reports",
        "runtime_files",
        "stable_head",
        "stable_replacement_hint",
        "unreconciled_direct_versions",
    }
)
COMMANDER_PUBLIC_OPAQUE_RESOURCE_URI_RE = re.compile(
    r"^colameta://(?:"
    r"result-artifact/[A-Za-z0-9_-]{16,128}(?:/pages/(?:[1-9][0-9]*|\{page\}))?"
    r"|review-manifest/[A-Za-z0-9_-]{16,128}"
    r"(?:/subjects/[1-9][0-9]*(?:/pages/(?:[1-9][0-9]*|\{page\}))?)?"
    r")$"
)
COMMANDER_PUBLIC_POSIX_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9:/])/(?!/)[^\s,;\]\[(){}<>\"']+"
)
COMMANDER_PUBLIC_FILE_URI_RE = re.compile(
    r"(?<![A-Za-z0-9])file:(?://(?:localhost)?/|/)[^\s,;\]\[(){}<>\"']+",
    re.IGNORECASE,
)
COMMANDER_PUBLIC_UNC_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9\\])\\\\[^\\\s,;\]\[(){}<>\"']+\\[^\s,;\]\[(){}<>\"']+"
)
COMMANDER_PUBLIC_WINDOWS_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:[A-Za-z]:\\)[^\s,;\]\[(){}<>\"']+",
    re.IGNORECASE,
)


def _policy_string_param(params: dict[str, Any], key: str) -> str:
    value = params.get(key)
    return value.strip().lower() if isinstance(value, str) else ""


class CommanderPublicProjector:
    """Produce the only ChatGPT-safe public projection of a tool result."""

    def __init__(self, project_root: str | None) -> None:
        self._project_root = project_root or ""

    def sanitize(self, value: Any, *, compact: bool) -> Any:
        if isinstance(value, dict):
            referenced_tool = value.get("tool")
            if (
                isinstance(referenced_tool, str)
                and referenced_tool
                and referenced_tool not in COMMANDER_EXPOSED_TOOLS
                and not self._is_resource_read_reference(value)
            ):
                return None
            sanitized: dict[str, Any] = {}
            for key, nested in value.items():
                clean_key = str(key)
                if (
                    clean_key in COMMANDER_PUBLIC_CONTEXT_BINDING_KEYS
                    and self._is_context_binding(nested)
                ):
                    sanitized[clean_key] = self._contract_sanitize(nested)
                    continue
                if (
                    clean_key in {"canonical_state", "canonical_project_state"}
                    and isinstance(nested, dict)
                    and nested.get("schema_version") == CANONICAL_PROJECT_STATE_SCHEMA_VERSION
                ):
                    sanitized[clean_key] = self._contract_sanitize(nested)
                    continue
                handled, contract_value = CommanderProjectionService.project_cc_s01_contract_value(
                    clean_key,
                    nested,
                )
                if handled:
                    sanitized[clean_key] = self._contract_sanitize(contract_value)
                    continue
                if self._omit_key(clean_key, nested, compact=compact):
                    continue
                clean_value = self.sanitize(nested, compact=compact)
                if clean_value is not None:
                    sanitized[clean_key] = clean_value
            return sanitized
        if isinstance(value, list):
            sanitized_items: list[Any] = []
            for item in value:
                clean_item = self.sanitize(item, compact=compact)
                if clean_item is not None:
                    sanitized_items.append(clean_item)
            return sanitized_items
        if isinstance(value, str):
            return self._public_string(value)
        return copy.deepcopy(value)

    def project_tool_result(
        self,
        tool_result: dict[str, Any],
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(tool_result, dict):
            return tool_result
        public_tool_result = copy.deepcopy(tool_result)
        tool_name = str(public_tool_result.get("tool") or "")
        raw_data = public_tool_result.get("data")
        if (
            tool_name in COMMANDER_EXPOSED_TOOLS
            and isinstance(raw_data, dict)
            and raw_data.get("schema_version") == COMMANDER_RESPONSE_SCHEMA_VERSION
        ):
            try:
                validate_commander_response(raw_data)
            except Exception:
                return self._wrap_commander_contract(
                    tool_name=tool_name,
                    projected_result={
                        "ok": False,
                        "tool": tool_name,
                        "error_code": "PUBLIC_PROJECTION_FAILED",
                        "message": "Commander 公共响应重复投影校验失败。",
                    },
                    params=params,
                )
            projected_contract: dict[str, Any] = {
                "ok": public_tool_result.get("ok") is True
                and raw_data["outcome"] != "failed",
                "tool": tool_name,
                "data": copy.deepcopy(raw_data),
            }
            meta = public_tool_result.get("_meta")
            if isinstance(meta, dict):
                projected_contract["_meta"] = copy.deepcopy(meta)
            if projected_contract["ok"] is False and isinstance(raw_data.get("error"), dict):
                projected_contract["error_code"] = raw_data["error"]["code"]
                projected_contract["message"] = raw_data["error"]["message"]
            return projected_contract
        is_review_manifest = (
            (
                tool_name == "review_manifest"
            )
            or (
                tool_name == "run_mcp_workflow"
                and isinstance(params, dict)
                and _policy_string_param(params, "workflow") == REVIEW_MANIFEST_WORKFLOW
            )
        )
        is_review_manifest_read = (
            is_review_manifest
            and isinstance(params, dict)
            and _policy_string_param(params, "phase") == "read"
        )
        # ``expires_at`` is intentionally omitted by the generic public
        # projection because most timestamps are local diagnostics.  A review
        # manifest expiry is different: it is a required, opaque continuation
        # contract shared by inspect, every subject page, and verify.  Preserve
        # only this typed workflow's value after ordinary sanitization.
        review_manifest_contract_expiry: str | None = None
        review_manifest_page_expiry: str | None = None
        if is_review_manifest and isinstance(raw_data, dict):
            raw_expiry = raw_data.get("expires_at")
            if isinstance(raw_expiry, str) and raw_expiry:
                review_manifest_contract_expiry = raw_expiry
        review_manifest_page_content: str | None = None
        if is_review_manifest_read:
            raw_page = raw_data.get("subject_page") if isinstance(raw_data, dict) else None
            raw_content = raw_page.get("content") if isinstance(raw_page, dict) else None
            if isinstance(raw_content, str):
                review_manifest_page_content = raw_content
            raw_page_expiry = raw_page.get("expires_at") if isinstance(raw_page, dict) else None
            if isinstance(raw_page_expiry, str) and raw_page_expiry:
                review_manifest_page_expiry = raw_page_expiry
        is_result_artifact_read = (
            tool_name == "read_result_artifact"
            or (
                tool_name == "run_mcp_workflow"
                and isinstance(params, dict)
                and _policy_string_param(params, "workflow") == RESULT_ARTIFACT_WORKFLOW
                and _policy_string_param(params, "phase") == "read"
            )
        )
        result_artifact_page: dict[str, Any] | None = None
        result_artifact_contract_fields: dict[str, Any] = {}
        result_artifact_descriptor: dict[str, Any] | None = None
        if isinstance(raw_data, dict):
            raw_descriptor = raw_data.get("result_artifact")
            if isinstance(raw_descriptor, dict):
                descriptor = {
                    field: copy.deepcopy(raw_descriptor[field])
                    for field in COMMANDER_PUBLIC_RESULT_ARTIFACT_CONTRACT_FIELDS
                    if field in raw_descriptor
                }
                if descriptor.get("artifact_id") and descriptor.get("content_sha256") and descriptor.get("expires_at"):
                    result_artifact_descriptor = descriptor
        if is_result_artifact_read and isinstance(raw_data, dict):
            raw_page = raw_data.get("artifact_page")
            if isinstance(raw_page, dict) and isinstance(raw_page.get("content"), str):
                result_artifact_page = copy.deepcopy(raw_page)
                for field in COMMANDER_PUBLIC_RESULT_ARTIFACT_CONTRACT_FIELDS:
                    if field in raw_data:
                        result_artifact_contract_fields[field] = copy.deepcopy(raw_data[field])
        if public_tool_result.get("ok") is False:
            is_review_manifest_mismatch = (
                (
                    tool_name == "review_manifest"
                    or (
                        tool_name == "run_mcp_workflow"
                        and isinstance(params, dict)
                        and _policy_string_param(params, "workflow") == REVIEW_MANIFEST_WORKFLOW
                    )
                )
                and public_tool_result.get("error_code") == "CONTEXT_BINDING_MISMATCH"
            )
            if not is_review_manifest_mismatch:
                public_tool_result.pop("details", None)
        if (
            tool_name == "run_mcp_workflow"
            and isinstance(params, dict)
            and _policy_string_param(params, "workflow") == "operator_batch"
        ):
            allowed_root_keys = {"ok", "tool", "error_code", "message"}
            projected = {
                key: copy.deepcopy(value)
                for key, value in public_tool_result.items()
                if key in allowed_root_keys
            }
            data = public_tool_result.get("data")
            if isinstance(data, dict):
                allowed_data_keys = {
                    "ok", "error_code", "message", "batch_preview_id",
                    "manifest_digest", "required_scopes", "operations",
                    "expires_at", "requires_confirmation", "state", "steps",
                    "context_binding", "context_binding_contract",
                    "context_binding_verification",
                }
                projected["data"] = {
                    key: copy.deepcopy(value)
                    for key, value in data.items()
                    if key in allowed_data_keys
                }
            return self._wrap_commander_contract(
                tool_name=tool_name,
                projected_result=projected,
                params=params,
            )
        if (
            tool_name == "run_mcp_workflow"
            and isinstance(params, dict)
            and _policy_string_param(params, "workflow") == GATE_REVIEW_WORKFLOW
        ):
            return self._wrap_commander_contract(
                tool_name=tool_name,
                projected_result=self._project_gate_review_result(public_tool_result),
                params=params,
            )
        if tool_name not in COMMANDER_EXPOSED_TOOLS:
            sanitized_root: dict[str, Any] = {}
            for key, value in public_tool_result.items():
                if self._omit_key(str(key), value, compact=False):
                    continue
                clean_value = self.sanitize(value, compact=False)
                if clean_value is not None:
                    sanitized_root[str(key)] = clean_value
            return sanitized_root

        projected = public_tool_result
        data = projected.get("data")
        if isinstance(data, dict):
            if tool_name == "list_registered_projects":
                projected["data"] = self._project_project_list(data)
            elif tool_name == "get_apps_connector_smoke_packet":
                projected["data"] = self._project_project_smoke(data)
            else:
                compact = tool_name in COMMANDER_PUBLIC_COMPACT_TOOLS
                clean_data = self.sanitize(data, compact=compact)
                if isinstance(clean_data, dict):
                    project_name = params.get("project_name") if isinstance(params, dict) else None
                    if (
                        isinstance(project_name, str)
                        and project_name.strip()
                        and "project_name" not in clean_data
                    ):
                        clean_data["project_name"] = project_name.strip()
                    projected["data"] = clean_data
        clean_result = self.sanitize(projected, compact=False)
        if review_manifest_page_content is not None and isinstance(clean_result, dict):
            clean_data = clean_result.get("data")
            if isinstance(clean_data, dict):
                if review_manifest_contract_expiry is not None:
                    clean_data["expires_at"] = review_manifest_contract_expiry
                clean_page = clean_data.get("subject_page")
                if isinstance(clean_page, dict):
                    clean_page["content"] = review_manifest_page_content
                    if review_manifest_page_expiry is not None:
                        clean_page["expires_at"] = review_manifest_page_expiry
        elif review_manifest_contract_expiry is not None and isinstance(clean_result, dict):
            clean_data = clean_result.get("data")
            if isinstance(clean_data, dict):
                clean_data["expires_at"] = review_manifest_contract_expiry
        if result_artifact_page is not None and isinstance(clean_result, dict):
            clean_data = clean_result.get("data")
            if isinstance(clean_data, dict):
                clean_data["artifact_page"] = result_artifact_page
                clean_data.update(result_artifact_contract_fields)
        if result_artifact_descriptor is not None and isinstance(clean_result, dict):
            clean_data = clean_result.get("data")
            if isinstance(clean_data, dict):
                clean_data["result_artifact"] = result_artifact_descriptor
                clean_data.update(result_artifact_descriptor)
        return self._wrap_commander_contract(
            tool_name=tool_name,
            projected_result=(
                clean_result if isinstance(clean_result, dict) else projected
            ),
            params=params,
        )

    @staticmethod
    def _wrap_commander_contract(
        *,
        tool_name: str,
        projected_result: dict[str, Any],
        params: dict[str, Any] | None,
    ) -> dict[str, Any]:
        response = build_commander_response(
            tool_name=tool_name,
            raw_result=projected_result,
            params=params,
        )
        validate_commander_response(response)
        result: dict[str, Any] = {
            "ok": projected_result.get("ok") is True
            and response["outcome"] != "failed",
            "tool": tool_name,
            "data": response,
        }
        meta = projected_result.get("_meta")
        if isinstance(meta, dict):
            result["_meta"] = copy.deepcopy(meta)
        if result["ok"] is False:
            error = response.get("error")
            if isinstance(error, dict):
                result["error_code"] = error["code"]
                result["message"] = error["message"]
        return result

    def _public_string(self, value: str) -> str:
        if COMMANDER_PUBLIC_OPAQUE_RESOURCE_URI_RE.fullmatch(value):
            return value
        redacted = value
        if self._project_root:
            redacted = redacted.replace(self._project_root, "<project>")
        redacted = COMMANDER_PUBLIC_FILE_URI_RE.sub("<local-path>", redacted)
        redacted = COMMANDER_PUBLIC_UNC_PATH_RE.sub("<local-path>", redacted)
        redacted = COMMANDER_PUBLIC_POSIX_PATH_RE.sub("<local-path>", redacted)
        return COMMANDER_PUBLIC_WINDOWS_PATH_RE.sub("<local-path>", redacted)

    @staticmethod
    def _value_has_absolute_path(value: Any) -> bool:
        if isinstance(value, str):
            return bool(
                value.startswith("/")
                or re.match(r"^[A-Za-z]:\\", value)
                or COMMANDER_PUBLIC_FILE_URI_RE.search(value)
                or COMMANDER_PUBLIC_UNC_PATH_RE.search(value)
                or COMMANDER_PUBLIC_POSIX_PATH_RE.search(value)
                or COMMANDER_PUBLIC_WINDOWS_PATH_RE.search(value)
            )
        if isinstance(value, list):
            return any(CommanderPublicProjector._value_has_absolute_path(item) for item in value)
        if isinstance(value, dict):
            return any(CommanderPublicProjector._value_has_absolute_path(item) for item in value.values())
        return False

    def _omit_key(self, key: str, value: Any, *, compact: bool) -> bool:
        normalized = key.strip().lower()
        if normalized in COMMANDER_PUBLIC_ALWAYS_OMIT_KEYS:
            return True
        if normalized.endswith(("_at", "_time")) or "timestamp" in normalized:
            return True
        if normalized in {"duration", "duration_ms", "elapsed", "elapsed_ms"}:
            return True
        if "latency" in normalized:
            return True
        if normalized.endswith(("_root", "_dir")):
            return True
        if normalized.endswith("_path"):
            return compact or self._value_has_absolute_path(value)
        if compact:
            if normalized in COMMANDER_PUBLIC_COMPACT_OMIT_KEYS:
                return True
            if normalized.endswith(("_head", "_commit", "_commit_subject", "_file", "_files")):
                return True
        return False

    @staticmethod
    def _is_resource_read_reference(value: dict[str, Any]) -> bool:
        if value.get("kind") != "mcp_resource" or value.get("tool") != "resources/read":
            return False
        arguments = value.get("arguments")
        if not isinstance(arguments, dict) or set(arguments) != {"uri"}:
            return False
        uri = arguments.get("uri")
        return isinstance(uri, str) and COMMANDER_PUBLIC_OPAQUE_RESOURCE_URI_RE.fullmatch(uri) is not None

    @staticmethod
    def _is_context_binding(value: Any) -> bool:
        if not isinstance(value, dict):
            return False
        if not all(field in value for field in BASE_CONTEXT_BINDING_FIELDS):
            return False
        allowed_fields = set(BASE_CONTEXT_BINDING_FIELDS) | {"review_unit", "workflow_intent"}
        if set(value) not in (set(BASE_CONTEXT_BINDING_FIELDS), allowed_fields):
            return False
        runner_plan = value.get("runner_plan")
        return isinstance(runner_plan, dict) and set(runner_plan) == {"mode", "plan_sha256"}

    def _contract_sanitize(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {str(key): self._contract_sanitize(nested) for key, nested in value.items()}
        if isinstance(value, list):
            return [self._contract_sanitize(item) for item in value]
        if isinstance(value, str):
            return self._public_string(value)
        return copy.deepcopy(value)

    @staticmethod
    def _project_project_list(data: dict[str, Any]) -> dict[str, Any]:
        projects = data.get("projects")
        projected: list[dict[str, Any]] = []
        if isinstance(projects, list):
            for item in projects:
                if not isinstance(item, dict):
                    continue
                project: dict[str, Any] = {}
                for key in (
                    "project_name",
                    "display_name",
                    "project_mode",
                    "available",
                    "runner_managed",
                ):
                    value = item.get(key)
                    if value is not None:
                        project[key] = copy.deepcopy(value)
                if project.get("project_name"):
                    projected.append(project)
        return {
            "ok": data.get("ok") is not False,
            "project_count": len(projected),
            "projects": projected,
        }

    def _project_project_smoke(self, data: dict[str, Any]) -> dict[str, Any]:
        projected = self.sanitize(data, compact=True)
        if not isinstance(projected, dict):
            return {}
        runtime = data.get("runtime")
        if isinstance(runtime, dict):
            stale = runtime.get("runtime_loaded_code_stale")
            reload_needed = runtime.get("reload_needed_for_verification")
            projected["runtime"] = {
                "runtime_aligned": stale is False and reload_needed is False,
                "runtime_loaded_code_stale": stale if isinstance(stale, bool) else None,
                "reload_needed_for_verification": (
                    reload_needed if isinstance(reload_needed, bool) else None
                ),
                "reload_awareness_reason": runtime.get("reload_awareness_reason"),
            }
        return projected

    def _project_gate_review_result(self, tool_result: dict[str, Any]) -> dict[str, Any]:
        projected = self.sanitize(tool_result, compact=False)
        return projected if isinstance(projected, dict) else tool_result
