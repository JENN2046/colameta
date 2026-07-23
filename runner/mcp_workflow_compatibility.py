"""Compatibility dispatch for the legacy ``run_mcp_workflow`` surface.

This is deliberately a host-adapted service rather than another MCP server.
The transport class supplies routing, context-binding, result packaging, and
the small set of project-scoped capabilities it already owns.  The service
owns the legacy workflow dispatch, typed read façades, and compatibility result
shape so that those concerns no longer live in the HTTP/JSON-RPC composition
root.
"""

from __future__ import annotations

import copy
from re import Pattern
from typing import Any, Protocol

from runner.core_workflow_registry import SUPPORTED_CORE_WORKFLOWS, normalize_workflow_name
from runner.mcp_gate_review_workflow import (
    GATE_REVIEW_WORKFLOW,
    GateReviewWorkflowError,
    MCPGateReviewWorkflow,
)
from runner.mcp_current_facts import (
    CURRENT_FACTS_WORKFLOW,
    CurrentFactsWorkflowError,
    MCPCurrentFactsWorkflow,
)
from runner.mcp_result_artifacts import MCPResultArtifactStore
from runner.mcp_review_manifest import MCPReviewManifestWorkflow, ReviewManifestWorkflowError
from runner.mcp_workflow_migration import OPERATOR_BATCH_WORKFLOW, RESULT_ARTIFACT_WORKFLOW
from runner.review_manifest import REVIEW_MANIFEST_WORKFLOW


class WorkflowCompatibilityError(ValueError):
    """A bounded compatibility error converted by the MCP transport layer."""

    def __init__(
        self,
        error_code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.details = details


class WorkflowCompatibilityHost(Protocol):
    """Narrow host capabilities required by compatibility dispatch."""

    mcp_exposure_profile: str
    _mcp_result_artifact_store: MCPResultArtifactStore

    def _mcp_result_artifact_uri(self, artifact_id: str, page: int | None = None) -> str: ...

    def _store_packaged_result_artifact(
        self,
        tool_name: str,
        structured_tool_result: dict[str, Any],
    ) -> dict[str, Any] | None: ...

    def _result_artifact_recommended_next_reads(
        self,
        artifact_fields: dict[str, Any],
    ) -> list[dict[str, Any]]: ...

    def _current_facts_analyze(self, params: dict[str, Any]) -> dict[str, Any]: ...

    def _result_artifact_compatibility_read_call(self, artifact_id: str, *, page: int) -> dict[str, Any]: ...

    def _operator_target_server(self, params: dict[str, Any]) -> Any: ...

    def _require_operation_context_binding(
        self,
        tool_name: str,
        params: dict[str, Any],
    ) -> dict[str, Any] | None: ...

    def _strip_operation_context_binding_params(self, params: dict[str, Any]) -> dict[str, Any]: ...

    def _strip_project_name_param(self, params: dict[str, Any]) -> dict[str, Any]: ...

    def _attach_operation_context_binding(
        self,
        result: dict[str, Any],
        *,
        tool_name: str,
        params: dict[str, Any],
        verified_binding: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    def _route_project_name_tool(
        self,
        tool_name: str,
        params: dict[str, Any],
        *,
        require_managed: bool,
    ) -> dict[str, Any]: ...

    def _tool_work_item_command(self, name: str, params: dict[str, Any]) -> dict[str, Any]: ...

    def _create_mcp_workflow_router(self) -> Any: ...

    def _normalize_recommended_actions_for_visible_tools(self, actions: list[Any]) -> list[Any]: ...

    def _record_workflow_if_needed(
        self,
        tool_name: str,
        action: str,
        params: dict[str, Any],
        result: dict[str, Any],
    ) -> str | None: ...


class MCPWorkflowCompatibilityService:
    """One authoritative implementation of legacy workflow compatibility."""

    def __init__(
        self,
        host: WorkflowCompatibilityHost,
        *,
        commander_exposure_profile: str,
        result_artifact_id_re: Pattern[str],
    ) -> None:
        self._host = host
        self._commander_exposure_profile = commander_exposure_profile
        self._result_artifact_id_re = result_artifact_id_re

    def handle_operator_batch(self, params: dict[str, Any]) -> dict[str, Any]:
        project_name = params.get("project_name")
        if not isinstance(project_name, str) or not project_name.strip():
            raise WorkflowCompatibilityError(
                "PROJECT_NAME_REQUIRED",
                "operator_batch 必须指定已登记 managed project_name。",
            )
        target = self._host._operator_target_server(params)
        return target._operator_batch_service().handle(project_name.strip(), params)

    def handle_review_manifest(self, params: dict[str, Any]) -> dict[str, Any]:
        try:
            return MCPReviewManifestWorkflow(self._host).handle(params)
        except ReviewManifestWorkflowError as exc:
            raise WorkflowCompatibilityError(exc.error_code, exc.message, exc.details) from exc

    @staticmethod
    def _typed_workflow_read_call_projection(
        value: Any,
        *,
        workflow: str,
        tool_name: str,
        drop_phase: bool,
    ) -> Any:
        """Project only this typed façade's continuation calls."""

        if isinstance(value, list):
            return [
                MCPWorkflowCompatibilityService._typed_workflow_read_call_projection(
                    item,
                    workflow=workflow,
                    tool_name=tool_name,
                    drop_phase=drop_phase,
                )
                for item in value
            ]
        if not isinstance(value, dict):
            return copy.deepcopy(value)
        projected = {
            key: MCPWorkflowCompatibilityService._typed_workflow_read_call_projection(
                nested,
                workflow=workflow,
                tool_name=tool_name,
                drop_phase=drop_phase,
            )
            for key, nested in value.items()
        }
        arguments = projected.get("arguments")
        if (
            projected.get("tool") == "run_mcp_workflow"
            and isinstance(arguments, dict)
            and arguments.get("workflow") == workflow
        ):
            typed_arguments = dict(arguments)
            typed_arguments.pop("workflow", None)
            if drop_phase:
                typed_arguments.pop("phase", None)
            projected["tool"] = tool_name
            projected["arguments"] = typed_arguments
            if projected.get("kind") == "mcp_tool_compatibility":
                projected["kind"] = "mcp_tool"
        return projected

    def handle_review_manifest_entry(self, params: dict[str, Any]) -> dict[str, Any]:
        """Typed, read-only façade for the manifest review state machine."""

        result = self.handle_review_manifest(params)
        return self._typed_workflow_read_call_projection(
            result,
            workflow=REVIEW_MANIFEST_WORKFLOW,
            tool_name="review_manifest",
            drop_phase=False,
        )

    @staticmethod
    def _result_artifact_authority_boundary() -> dict[str, bool]:
        return {
            "does_not_read_project_files": True,
            "does_not_authorize_executor_run": True,
            "does_not_authorize_validation_run": True,
            "does_not_authorize_commit_or_push": True,
            "does_not_authorize_review_decision": True,
            "does_not_authorize_delivery_acceptance": True,
        }

    def _result_artifact_read_packet(self, *, artifact_page: Any) -> dict[str, Any]:
        """Expose one exact stored artifact page through its bounded read surface."""

        artifact_id = str(artifact_page.artifact_id)
        page = int(artifact_page.page)
        page_count = int(artifact_page.page_count)
        resource_uri = self._host._mcp_result_artifact_uri(artifact_id)
        artifact_fields = {
            "artifact_id": artifact_id,
            "resource_uri": resource_uri,
            "page_uri_template": f"{resource_uri}/pages/{{page}}",
            "page_count": page_count,
            "content_sha256": str(artifact_page.content_sha256),
            "expires_at": str(artifact_page.expires_at),
        }
        read_call = self._host._result_artifact_compatibility_read_call(
            artifact_id,
            page=page,
        )
        recommended_next_reads: list[dict[str, Any]] = []
        if page < page_count:
            next_read_call = self._host._result_artifact_compatibility_read_call(
                artifact_id,
                page=page + 1,
            )
            recommended_next_reads.append(
                {
                    "kind": "mcp_tool",
                    **next_read_call,
                    "reason": "继续读取同一短期 artifact 的下一页；artifact_id、expires_at 与 content_sha256 保持不变。",
                }
            )
        return {
            "ok": True,
            "workflow": RESULT_ARTIFACT_WORKFLOW,
            "phase": "read",
            "schema_version": "colameta.result_artifact_read.v1",
            "read_only": True,
            "side_effects": False,
            **artifact_fields,
            "artifact_page": artifact_page.to_dict(),
            "read_call": read_call,
            "recommended_next_reads": recommended_next_reads,
            "artifact_contract": {
                "opaque_handle_required": True,
                "page_content_is_exact_stored_utf8_slice": True,
                "content_sha256_applies_to_concatenated_pages": True,
                "expiry_is_enforced": True,
                "standard_resource_read_remains_preferred": True,
                "compatibility_route_is_read_only": True,
            },
            "authority_boundary": self._result_artifact_authority_boundary(),
        }

    def handle_read_result_artifact(self, params: dict[str, Any]) -> dict[str, Any]:
        """Typed, read-only façade for one packaged-result continuation page."""

        phase_raw = params.get("phase")
        if phase_raw is not None:
            phase = phase_raw.strip().lower() if isinstance(phase_raw, str) else ""
            if phase != "read":
                raise WorkflowCompatibilityError(
                    "INVALID_RESULT_ARTIFACT_PHASE",
                    "read_result_artifact 固定执行 read；它不是通用 artifact、文件或证据读取入口。",
                )
        read_params = dict(params)
        read_params["phase"] = "read"
        result = self.handle_result_artifact(read_params)
        return self._typed_workflow_read_call_projection(
            result,
            workflow=RESULT_ARTIFACT_WORKFLOW,
            tool_name="read_result_artifact",
            drop_phase=True,
        )

    def handle_result_artifact(self, params: dict[str, Any]) -> dict[str, Any]:
        """Read a pre-issued packaged-result page without widening file access."""

        phase_raw = params.get("phase")
        phase = phase_raw.strip().lower() if isinstance(phase_raw, str) else ""
        if phase != "read":
            raise WorkflowCompatibilityError(
                "INVALID_RESULT_ARTIFACT_PHASE",
                "result_artifact 只支持 read；它不是通用 artifact、文件或证据读取入口。",
            )
        artifact_id_raw = params.get("artifact_id")
        if not isinstance(artifact_id_raw, str) or not artifact_id_raw.strip():
            raise WorkflowCompatibilityError(
                "RESULT_ARTIFACT_ID_REQUIRED",
                "result_artifact read 必须提供 packaged response 返回的 artifact_id。",
            )
        artifact_id = artifact_id_raw.strip()
        if self._result_artifact_id_re.fullmatch(artifact_id) is None:
            raise WorkflowCompatibilityError(
                "INVALID_RESULT_ARTIFACT_ID",
                "artifact_id 不是有效的短期 opaque result-artifact handle。",
            )
        page = params.get("artifact_page", 1)
        if isinstance(page, bool) or not isinstance(page, int) or page < 1:
            raise WorkflowCompatibilityError(
                "INVALID_RESULT_ARTIFACT_PAGE",
                "artifact_page 必须是正整数。",
            )
        artifact_page = self._host._mcp_result_artifact_store.read_page(artifact_id, page)
        if artifact_page is None:
            # Do not distinguish unknown, evicted, expired, or out-of-range
            # handles.  This prevents artifact enumeration just as
            # resources/read does.
            raise WorkflowCompatibilityError(
                "RESULT_ARTIFACT_NOT_FOUND_OR_EXPIRED",
                "结果 artifact 不存在、已过期或页码无效；请重新执行原始只读调用。",
            )
        return self._result_artifact_read_packet(artifact_page=artifact_page)

    def handle_gate_review(
        self,
        params: dict[str, Any],
        *,
        verified_binding: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Run the Gate adapter without adding a second authority layer."""

        if params.get("project_name") is not None:
            return self._host._route_project_name_tool(
                "run_mcp_workflow",
                params,
                require_managed=True,
            )
        clean = self._host._strip_operation_context_binding_params(
            self._host._strip_project_name_param(params),
        )
        try:
            result = MCPGateReviewWorkflow(self._host._tool_work_item_command).handle(clean)
        except GateReviewWorkflowError as exc:
            raise WorkflowCompatibilityError(exc.error_code, exc.message, exc.details) from exc
        return self._host._attach_operation_context_binding(
            result,
            tool_name="run_mcp_workflow",
            params=params,
            verified_binding=verified_binding,
        )

    def handle_current_facts(self, params: dict[str, Any]) -> dict[str, Any]:
        """Run the bounded current-facts read/archive state machine."""

        phase_raw = params.get("phase")
        phase = phase_raw.strip().lower() if isinstance(phase_raw, str) else "inspect"
        if params.get("project_name") is not None:
            return self._host._route_project_name_tool(
                "run_mcp_workflow",
                params,
                require_managed=phase == "apply",
            )
        verified_binding = self._host._require_operation_context_binding(
            "run_mcp_workflow",
            params,
        )
        clean = self._host._strip_operation_context_binding_params(params)
        try:
            result = MCPCurrentFactsWorkflow(self._host).handle(clean)
        except CurrentFactsWorkflowError as exc:
            raise WorkflowCompatibilityError(exc.error_code, exc.message) from exc
        # Do not create a generic workflow record here: the explicit archive
        # is the durable evidence surface, while inspect/preview must remain
        # observational and must not make a clean checkout appear dirty before
        # the caller can confirm the exact snapshot.
        return self._host._attach_operation_context_binding(
            result,
            tool_name="run_mcp_workflow",
            params=params,
            verified_binding=verified_binding,
        )

    def handle_run_mcp_workflow(self, params: dict[str, Any]) -> dict[str, Any]:
        """Dispatch the retained legacy workflow surface through one path."""

        workflow = normalize_workflow_name(params.get("workflow"))
        if workflow == RESULT_ARTIFACT_WORKFLOW:
            return self.handle_result_artifact(params)
        if workflow == REVIEW_MANIFEST_WORKFLOW:
            return self.handle_review_manifest(params)
        if workflow == CURRENT_FACTS_WORKFLOW:
            return self.handle_current_facts(params)
        if (
            workflow not in {OPERATOR_BATCH_WORKFLOW, GATE_REVIEW_WORKFLOW}
            and workflow not in SUPPORTED_CORE_WORKFLOWS
        ):
            raise WorkflowCompatibilityError("INVALID_WORKFLOW", f"未知 workflow：{workflow}")

        verified_binding = self._host._require_operation_context_binding(
            "run_mcp_workflow",
            params,
        )
        if workflow == OPERATOR_BATCH_WORKFLOW:
            result = self.handle_operator_batch(
                self._host._strip_operation_context_binding_params(params),
            )
            return self._host._attach_operation_context_binding(
                result,
                tool_name="run_mcp_workflow",
                params=params,
                verified_binding=verified_binding,
            )
        if workflow == GATE_REVIEW_WORKFLOW:
            return self.handle_gate_review(params, verified_binding=verified_binding)
        if params.get("project_name") is not None:
            return self._host._route_project_name_tool(
                "run_mcp_workflow",
                params,
                require_managed=True,
            )

        result = self._host._create_mcp_workflow_router().handle(
            workflow,
            self._host._strip_operation_context_binding_params(params),
        )
        if self._host.mcp_exposure_profile == self._commander_exposure_profile:
            next_actions = result.get("next_actions") if isinstance(result, dict) else None
            if isinstance(next_actions, list):
                result["next_actions"] = self._host._normalize_recommended_actions_for_visible_tools(
                    next_actions,
                )
        self._host._record_workflow_if_needed("run_mcp_workflow", workflow, params, result)
        return self._host._attach_operation_context_binding(
            result,
            tool_name="run_mcp_workflow",
            params=params,
            verified_binding=verified_binding,
        )
