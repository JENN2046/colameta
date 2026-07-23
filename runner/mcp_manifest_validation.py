"""MCP adapter for manifest-bound validation previews and runs.

The public server owns routing and transport errors.  This adapter owns the
cross-cutting bridge between an already-inspected review manifest and the
ordinary validation-run manager, keeping the larger MCP server focused on
surface assembly and generic dispatch.
"""

from __future__ import annotations

import os
from typing import Any, Protocol

from runner.mcp_validation_run import MCPValidationRunManager
from runner.project_context_binding import (
    PROJECT_CONTEXT_BINDING_SCHEMA_VERSION,
    ProjectContextBindingError,
    collect_project_context_binding,
    context_binding_sha256,
    require_operation_context_binding,
)
from runner.review_manifest import (
    ReviewManifestError,
    ReviewManifestStore,
    StoredReviewManifest,
    collect_review_context_binding,
    verify_stored_review_manifest,
)
from runner.review_manifest_validation import (
    build_review_manifest_validation_source,
    manifest_validation_contract_from_artifact,
)
from runner.workflow_engine import record_tool_call, should_record_tool


class ManifestValidationWorkflowError(ValueError):
    """A bounded manifest-validation error for the MCP transport to render."""

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


class ManifestValidationHost(Protocol):
    """Narrow host contract implemented by ``MCPPlanningBridgeServer``."""

    service_mode: bool
    _review_manifest_store: ReviewManifestStore

    def _resolve_read_only_project_context(
        self,
        params: dict[str, Any],
    ) -> tuple[str, dict[str, Any] | None]: ...

    def _project_name_for_context(
        self,
        project_root: str,
        project_record: dict[str, Any] | None,
        params: dict[str, Any],
    ) -> str: ...

    def _strip_operation_context_binding_params(
        self,
        params: dict[str, Any],
    ) -> dict[str, Any]: ...

    def _with_project_identity(
        self,
        result: dict[str, Any],
        project_root: str,
    ) -> dict[str, Any]: ...

    def _inject_operation_context_into_next_actions(
        self,
        result: dict[str, Any],
        *,
        binding: dict[str, Any],
        identity: tuple[str, str],
    ) -> None: ...

    def _inject_project_name_into_nested_actions(
        self,
        value: Any,
        project_name: str,
    ) -> None: ...


class MCPManifestValidationWorkflow:
    """Bridge a review-manifest session into one validation-run lifecycle."""

    def __init__(self, host: ManifestValidationHost) -> None:
        self._host = host

    def preview(self, params: dict[str, Any]) -> dict[str, Any]:
        """Create one validation preview after a full manifest verification."""

        prohibited = [
            field
            for field in ("scope", "target_files", "preview_id", "run_id", "context_binding")
            if params.get(field) is not None
        ]
        if prohibited:
            raise ManifestValidationWorkflowError(
                "MANIFEST_VALIDATION_INPUT_COMBINATION_DENIED",
                "manifest-bound validation preview 只能使用 review_manifest_id，不能混入 scope、target_files 或其他 preview/run 输入。",
                {"prohibited_fields": prohibited},
            )
        stored = self._stored_review_manifest(params.get("review_manifest_id"), params)
        verification = self._verify_stored_manifest(stored)
        manager = MCPValidationRunManager(stored.project_root)
        result = manager.preview_manifest_bound(
            build_review_manifest_validation_source(stored),
        )
        result["manifest_verification"] = verification
        self._record_workflow(
            project_root=stored.project_root,
            action="preview",
            params=params,
            result=result,
        )
        return self._attach_operation_context(result, stored=stored)

    def try_run(self, params: dict[str, Any]) -> dict[str, Any] | None:
        """Run a manifest preview only after a second full verification."""

        preview_id = params.get("preview_id")
        if not isinstance(preview_id, str) or not preview_id.strip():
            return None
        project_root, _project_record = self._host._resolve_read_only_project_context(params)
        manager = MCPValidationRunManager(project_root)
        artifact = manager.read(preview_id.strip())
        if not isinstance(artifact, dict) or "manifest_validation" not in artifact:
            return None
        contract = manifest_validation_contract_from_artifact(artifact)
        if contract is None:
            raise ManifestValidationWorkflowError(
                "MANIFEST_VALIDATION_CONTRACT_INVALID",
                "manifest-bound validation preview 合同无效或已被改变，已停止执行。",
            )
        lookup_params = dict(params)
        lookup_params["review_manifest_id"] = contract["review_manifest_id"]
        stored = self._stored_review_manifest(
            contract["review_manifest_id"],
            lookup_params,
        )
        mismatches = self._contract_mismatches(contract, stored)
        if mismatches:
            raise ManifestValidationWorkflowError(
                "MANIFEST_VALIDATION_CONTRACT_MISMATCH",
                "validation preview 不再匹配其原始 review manifest，已停止执行。",
                {"mismatched_fields": mismatches},
            )
        project_name = str(stored.context_binding["project_name"])
        try:
            verified_binding = require_operation_context_binding(
                params.get("context_binding"),
                project_root=stored.project_root,
                project_name=project_name,
                review_unit="operation:validation_run",
                workflow_intent="validation_run",
            )
        except ProjectContextBindingError as exc:
            raise ManifestValidationWorkflowError(
                exc.error_code,
                exc.message,
                exc.details,
            ) from exc
        verification = self._verify_stored_manifest(stored)
        result = manager.run(self._host._strip_operation_context_binding_params(params))
        result["manifest_verification"] = verification
        self._record_workflow(
            project_root=stored.project_root,
            action="run",
            params=params,
            result=result,
        )
        return self._attach_operation_context(
            result,
            stored=stored,
            verified_binding=verified_binding,
        )

    def try_source_only_status(self, params: dict[str, Any]) -> dict[str, Any] | None:
        """Expose status for a manifest run in a registered source-only project."""

        if params.get("project_name") is None:
            return None
        project_root, project_record = self._host._resolve_read_only_project_context(params)
        if not isinstance(project_record, dict) or project_record.get("project_mode") != "source-only":
            return None
        project_name = self._host._project_name_for_context(project_root, project_record, params)
        manager = MCPValidationRunManager(project_root)
        result = manager.status(self._host._strip_operation_context_binding_params(params))
        self._record_workflow(
            project_root=project_root,
            action="status",
            params=params,
            result=result,
        )
        result = self._host._with_project_identity(result, project_root)
        result["project_name"] = project_name
        binding = collect_project_context_binding(
            project_root,
            project_name=project_name,
            review_unit="operation:validation_run",
            workflow_intent="validation_run",
        )
        result["context_binding"] = binding
        result["context_binding_contract"] = {
            "schema_version": PROJECT_CONTEXT_BINDING_SCHEMA_VERSION,
            "confirmation_required": True,
            "current_call_requires_context_binding": False,
            "workflow_intent": "validation_run",
            "review_unit": "operation:validation_run",
            "context_binding_sha256": context_binding_sha256(binding),
        }
        return result

    def _stored_review_manifest(
        self,
        review_manifest_id: Any,
        params: dict[str, Any],
    ) -> StoredReviewManifest:
        if not isinstance(review_manifest_id, str) or not review_manifest_id.strip():
            raise ManifestValidationWorkflowError(
                "REVIEW_MANIFEST_ID_REQUIRED",
                "manifest-bound validation preview 必须提供 inspect 返回的 review_manifest_id。",
            )
        stored = self._host._review_manifest_store.get(review_manifest_id.strip())
        if stored is None:
            raise ManifestValidationWorkflowError(
                "REVIEW_MANIFEST_NOT_FOUND_OR_EXPIRED",
                "review manifest 不存在或已过期；请重新执行 inspect。",
            )
        project_root, project_record = self._host._resolve_read_only_project_context(params)
        resolved_root = os.path.realpath(os.path.abspath(project_root))
        if stored.project_root != resolved_root:
            actual_name = self._host._project_name_for_context(project_root, project_record, params)
            raise ManifestValidationWorkflowError(
                "CONTEXT_BINDING_MISMATCH",
                "review manifest 不属于当前项目路由，已停止 manifest validation。",
                {
                    "mismatches": [{
                        "field": "project_name",
                        "expected": stored.context_binding.get("project_name"),
                        "actual": actual_name,
                    }]
                },
            )
        requested_name = params.get("project_name")
        stored_name = stored.context_binding.get("project_name")
        if (
            isinstance(requested_name, str)
            and requested_name.strip()
            and requested_name.strip() != stored_name
        ):
            raise ManifestValidationWorkflowError(
                "CONTEXT_BINDING_MISMATCH",
                "review manifest 的 project_name 与当前路由不一致。",
                {
                    "mismatches": [{
                        "field": "project_name",
                        "expected": stored_name,
                        "actual": requested_name.strip(),
                    }]
                },
            )
        return stored

    @staticmethod
    def _current_review_context(stored: StoredReviewManifest) -> dict[str, Any]:
        return collect_review_context_binding(
            stored.project_root,
            project_name=str(stored.context_binding["project_name"]),
        )

    def _verify_stored_manifest(self, stored: StoredReviewManifest) -> dict[str, Any]:
        try:
            return verify_stored_review_manifest(
                stored,
                current_context_binding=self._current_review_context(stored),
            )
        except ReviewManifestError as exc:
            raise ManifestValidationWorkflowError(
                exc.error_code,
                exc.message,
                exc.details,
            ) from exc

    @staticmethod
    def _contract_mismatches(
        contract: dict[str, Any],
        stored: StoredReviewManifest,
    ) -> list[str]:
        source = build_review_manifest_validation_source(stored)
        expected = {
            "review_manifest_id": source["review_manifest_id"],
            "manifest_sha256": source["manifest_sha256"],
            "review_unit": source["review_unit"],
            "workflow_intent": source["workflow_intent"],
            "review_context_binding": source["review_context_binding"],
            "subjects": source["subjects"],
        }
        return [
            field
            for field, value in expected.items()
            if contract.get(field) != value
        ]

    def _record_workflow(
        self,
        *,
        project_root: str,
        action: str,
        params: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        if not should_record_tool("manage_validation_run", action) or not isinstance(result, dict):
            return
        recorded = record_tool_call(
            project_root,
            "manage_validation_run",
            action,
            self._host._strip_operation_context_binding_params(params),
            result,
        )
        warning = recorded.get("warning")
        if isinstance(warning, str) and warning:
            result["workflow_record_warning"] = warning
        workflow_id = recorded.get("workflow_id")
        if isinstance(workflow_id, str) and workflow_id:
            result["workflow_id"] = workflow_id

    def _attach_operation_context(
        self,
        result: dict[str, Any],
        *,
        stored: StoredReviewManifest,
        verified_binding: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        project_name = str(stored.context_binding["project_name"])
        binding = collect_project_context_binding(
            stored.project_root,
            project_name=project_name,
            review_unit="operation:validation_run",
            workflow_intent="validation_run",
        )
        result = self._host._with_project_identity(result, stored.project_root)
        result["context_binding"] = binding
        result["context_binding_contract"] = {
            "schema_version": PROJECT_CONTEXT_BINDING_SCHEMA_VERSION,
            "confirmation_required": True,
            "current_call_requires_context_binding": verified_binding is not None,
            "workflow_intent": "validation_run",
            "review_unit": "operation:validation_run",
            "context_binding_sha256": context_binding_sha256(binding),
        }
        if verified_binding is not None:
            result["context_binding_verification"] = {
                "status": "matched",
                "context_binding_sha256": context_binding_sha256(verified_binding),
            }
        self._host._inject_operation_context_into_next_actions(
            result,
            binding=binding,
            identity=("validation_run", "operation:validation_run"),
        )
        if self._host.service_mode:
            result["project_name"] = project_name
            self._host._inject_project_name_into_nested_actions(result, project_name)
        return result
