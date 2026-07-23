"""MCP workflow adapter for hash-bound independent review manifests.

The adapter owns the inspect/read/verify state machine while its host retains
resource URI construction and the public MCP transport.  Keeping those layers
separate makes the review contract easier to test without widening the public
tool surface.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Protocol

from runner.review_manifest import (
    REVIEW_MANIFEST_SCHEMA_VERSION,
    REVIEW_MANIFEST_WORKFLOW,
    REVIEW_MANIFEST_WORKFLOW_INTENT,
    ReviewManifestError,
    ReviewManifestHandle,
    ReviewManifestInspection,
    ReviewManifestStore,
    StoredReviewManifest,
    collect_review_context_binding,
    inspect_review_manifest,
    read_stored_review_manifest_page,
    verify_stored_review_context,
    verify_stored_review_manifest,
)


REVIEW_MANIFEST_URI_RE = re.compile(
    r"^colameta://review-manifest/(?P<review_manifest_id>[A-Za-z0-9_-]{16,128})"
    r"(?:/subjects/(?P<subject_index>[1-9][0-9]*)(?:/pages/(?P<page>[1-9][0-9]*))?)?$"
)


class ReviewManifestWorkflowError(ValueError):
    """A bounded review-manifest failure for the MCP transport to render."""

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


class MCPReviewManifestResources:
    """Own short-lived review-manifest URI and resource-page projections."""

    def __init__(self, store: ReviewManifestStore) -> None:
        self._store = store

    @staticmethod
    def uri(
        review_manifest_id: str,
        *,
        subject_index: int | None = None,
        page: int | None = None,
    ) -> str:
        base = f"colameta://review-manifest/{review_manifest_id}"
        if subject_index is None:
            return base
        subject_uri = f"{base}/subjects/{subject_index}"
        return subject_uri if page is None else f"{subject_uri}/pages/{page}"

    @staticmethod
    def parse_uri(uri: str) -> tuple[str, int | None, int | None] | None:
        matched = REVIEW_MANIFEST_URI_RE.fullmatch(uri)
        if matched is None:
            return None
        review_manifest_id = matched.group("review_manifest_id")
        subject_raw = matched.group("subject_index")
        page_raw = matched.group("page")
        try:
            subject_index = int(subject_raw) if subject_raw is not None else None
            page = int(page_raw) if page_raw is not None else None
        except ValueError:
            return None
        return review_manifest_id, subject_index, page

    def handle_fields(self, handle: ReviewManifestHandle) -> dict[str, Any]:
        return {
            "review_manifest_id": handle.review_manifest_id,
            "manifest_sha256": handle.manifest_sha256,
            "manifest_resource_uri": self.uri(handle.review_manifest_id),
            "expires_at": handle.expires_at,
        }

    @staticmethod
    def read_call(
        handle: ReviewManifestHandle,
        *,
        subject_index: int,
        page: int,
        project_name: str | None = None,
    ) -> dict[str, Any]:
        arguments: dict[str, Any] = {
            "workflow": REVIEW_MANIFEST_WORKFLOW,
            "phase": "read",
            "review_manifest_id": handle.review_manifest_id,
            "review_manifest_subject_index": subject_index,
            "review_manifest_page": page,
        }
        if isinstance(project_name, str) and project_name.strip():
            arguments["project_name"] = project_name.strip()
        return {
            "tool": "run_mcp_workflow",
            "arguments": arguments,
        }

    def subject_descriptor(
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
        resource_uri = self.uri(
            handle.review_manifest_id,
            subject_index=subject_index,
        )
        return {
            "subject_index": subject_index,
            "path": path,
            "sha256": sha256,
            "byte_size": byte_size,
            "page_count": page_count,
            "resource_uri": resource_uri,
            "page_uri_template": f"{resource_uri}/pages/{{page}}",
            "read_call": self.read_call(
                handle,
                subject_index=subject_index,
                page=1,
                project_name=project_name,
            ),
        }

    def read_resource(self, uri: str) -> dict[str, Any] | None:
        parsed = self.parse_uri(uri)
        if parsed is None:
            return None
        review_manifest_id, subject_index, page = parsed
        stored = self._store.get(review_manifest_id)
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
        if subject_index is None:
            return {
                "contents": [
                    {
                        "uri": uri,
                        "mimeType": "application/json",
                        "text": json.dumps(
                            self.resource_summary(stored),
                            ensure_ascii=False,
                        ),
                    }
                ]
            }
        subject_page = read_stored_review_manifest_page(
            stored,
            subject_index=subject_index,
            page=page or 1,
        )
        return {
            "contents": [
                {
                    "uri": uri,
                    "mimeType": "application/json",
                    "text": json.dumps(subject_page.to_dict(), ensure_ascii=False),
                }
            ]
        }

    def resource_summary(self, stored: StoredReviewManifest) -> dict[str, Any]:
        handle = stored.handle
        return {
            "schema_version": "colameta.review_manifest_resource.v1",
            **self.handle_fields(handle),
            "review_unit": stored.context_binding.get("review_unit"),
            "workflow_intent": stored.context_binding.get("workflow_intent"),
            "context_binding": dict(stored.context_binding),
            "acceptance_commands_preview": list(stored.manifest.get("acceptance_commands") or []),
            "subjects": [
                self.subject_descriptor(
                    handle,
                    subject_index=index,
                    path=subject.path,
                    sha256=subject.sha256,
                    byte_size=subject.byte_size,
                    page_count=subject.page_count,
                )
                for index, subject in enumerate(stored.subjects, start=1)
            ],
            "read_only": True,
            "side_effects": False,
            "authority_boundary": self.authority_boundary(),
        }

    @staticmethod
    def authority_boundary() -> dict[str, bool]:
        return {
            "does_not_authorize_executor_run": True,
            "does_not_authorize_validation_run": True,
            "does_not_authorize_commit_or_push": True,
            "does_not_authorize_review_decision": True,
            "does_not_authorize_delivery_acceptance": True,
            "does_not_read_unlisted_files": True,
        }


class ReviewManifestWorkflowHost(Protocol):
    """Narrow host contract implemented by ``MCPPlanningBridgeServer``."""

    service_mode: bool
    project_hint: str
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

    def _project_identity_for_root(self, project_root: str) -> dict[str, Any]: ...

    def _review_manifest_handle_fields(
        self,
        handle: ReviewManifestHandle,
    ) -> dict[str, Any]: ...

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
    ) -> dict[str, Any]: ...

    def _review_manifest_read_call(
        self,
        handle: ReviewManifestHandle,
        *,
        subject_index: int,
        page: int,
        project_name: str | None = None,
    ) -> dict[str, Any]: ...

    def _review_manifest_authority_boundary(self) -> dict[str, bool]: ...


class MCPReviewManifestWorkflow:
    """Run the strictly read-only review-manifest workflow lifecycle."""

    def __init__(self, host: ReviewManifestWorkflowHost) -> None:
        self._host = host

    def handle(self, params: dict[str, Any]) -> dict[str, Any]:
        phase_raw = params.get("phase", "inspect")
        phase = phase_raw.strip().lower() if isinstance(phase_raw, str) else ""
        if phase not in {"inspect", "read", "verify", "status"}:
            raise ReviewManifestWorkflowError(
                "INVALID_REVIEW_MANIFEST_PHASE",
                "review_manifest 只支持 inspect、read、verify 或 status。",
            )
        project_root, project_name, current_context = self._project_context(params)
        if phase == "inspect":
            if params.get("review_manifest") is None:
                return self._template(current_context)
            try:
                inspection = inspect_review_manifest(
                    params.get("review_manifest"),
                    project_root=project_root,
                    context_binding=current_context,
                )
            except ReviewManifestError as exc:
                raise ReviewManifestWorkflowError(
                    exc.error_code,
                    exc.message,
                    exc.details,
                ) from exc
            handle = self._host._review_manifest_store.put(
                project_root=project_root,
                inspection=inspection,
            )
            return self._packet(
                handle=handle,
                inspection=inspection,
                phase="inspect",
            )

        review_manifest_id = params.get("review_manifest_id")
        if not isinstance(review_manifest_id, str) or not review_manifest_id.strip():
            raise ReviewManifestWorkflowError(
                "REVIEW_MANIFEST_ID_REQUIRED",
                "review_manifest read/verify/status 必须提供 inspect 返回的 review_manifest_id。",
            )
        stored = self._host._review_manifest_store.get(review_manifest_id.strip())
        if stored is None:
            raise ReviewManifestWorkflowError(
                "REVIEW_MANIFEST_NOT_FOUND_OR_EXPIRED",
                "review manifest 不存在或已过期；请重新执行 inspect。",
            )
        if stored.project_root != project_root:
            raise ReviewManifestWorkflowError(
                "CONTEXT_BINDING_MISMATCH",
                "review manifest 不属于当前 project_name 路由的项目。",
                {
                    "mismatches": [
                        {
                            "field": "project_name",
                            "expected": stored.context_binding.get("project_name"),
                            "actual": project_name,
                        }
                    ]
                },
            )
        if phase == "read":
            return self._read(
                params=params,
                stored=stored,
                current_context=current_context,
            )
        try:
            verification = verify_stored_review_manifest(
                stored,
                current_context_binding=current_context,
            )
        except ReviewManifestError as exc:
            raise ReviewManifestWorkflowError(
                exc.error_code,
                exc.message,
                exc.details,
            ) from exc
        packet = self._packet(
            handle=stored.handle,
            inspection=stored,
            phase="verify" if phase == "verify" else "status",
        )
        packet["verification"] = verification
        return packet

    def _project_context(
        self,
        params: dict[str, Any],
    ) -> tuple[str, str, dict[str, Any]]:
        project_root, project_record = self._host._resolve_read_only_project_context(params)
        if isinstance(project_record, dict) or params.get("project_name") is not None:
            project_name = self._host._project_name_for_context(project_root, project_record, params)
        else:
            identity_name = self._host._project_identity_for_root(project_root).get("project_name")
            project_name = (
                identity_name.strip()
                if isinstance(identity_name, str) and identity_name.strip()
                else os.path.basename(project_root.rstrip(os.sep)) or self._host.project_hint
            )
        context_binding = collect_review_context_binding(
            project_root,
            project_name=project_name,
        )
        unavailable = [
            field
            for field in ("branch", "head")
            if not isinstance(context_binding.get(field), str)
            or not str(context_binding.get(field)).strip()
        ]
        if unavailable:
            raise ReviewManifestWorkflowError(
                "REVIEW_MANIFEST_CONTEXT_UNAVAILABLE",
                "review_manifest 需要可读取 branch 和 HEAD 的 Git checkout。",
                {"missing_context_fields": unavailable},
            )
        return (
            os.path.realpath(os.path.abspath(project_root)),
            project_name,
            context_binding,
        )

    def _packet(
        self,
        *,
        handle: ReviewManifestHandle,
        inspection: ReviewManifestInspection | StoredReviewManifest,
        phase: str,
    ) -> dict[str, Any]:
        manifest = inspection.manifest
        context_binding = inspection.context_binding
        compatibility_project_name = (
            str(context_binding.get("project_name") or "").strip()
            if self._host.service_mode
            else None
        )
        subject_descriptors = [
            self._host._review_manifest_subject_descriptor(
                handle,
                subject_index=index,
                path=subject.path,
                sha256=subject.sha256,
                byte_size=subject.byte_size,
                page_count=subject.page_count,
                project_name=compatibility_project_name,
            )
            for index, subject in enumerate(inspection.subjects, start=1)
        ]
        handle_fields = self._host._review_manifest_handle_fields(handle)
        manifest_resource_uri = handle_fields["manifest_resource_uri"]
        recommended_next_reads: list[dict[str, Any]] = [
            {
                "kind": "mcp_resource",
                "tool": "resources/read",
                "arguments": {"uri": manifest_resource_uri},
                "reason": "先续读审查 manifest，再仅按 subjects 中返回的 resource_uri 读取完整输入。",
            }
        ]
        if subject_descriptors:
            fallback = subject_descriptors[0].get("read_call")
            if isinstance(fallback, dict):
                recommended_next_reads.append(
                    {
                        "kind": "mcp_tool_compatibility",
                        **fallback,
                        "reason": "若宿主不支持动态 resources/read URI，使用同一 manifest 绑定下的第 1 个 subject 第 1 页读取调用。",
                    }
                )
        return {
            "ok": True,
            "workflow": REVIEW_MANIFEST_WORKFLOW,
            "phase": phase,
            "schema_version": "colameta.review_manifest_inspection.v1",
            "read_only": True,
            "side_effects": False,
            **handle_fields,
            "review_unit": context_binding["review_unit"],
            "workflow_intent": context_binding["workflow_intent"],
            "context_binding": dict(context_binding),
            "subject_count": len(subject_descriptors),
            "subjects": subject_descriptors,
            "acceptance_commands_preview": list(manifest.get("acceptance_commands") or []),
            "independent_review_packet": {
                "packet_kind": "manifest_bound_independent_review.v1",
                "review_unit": context_binding["review_unit"],
                "workflow_intent": context_binding["workflow_intent"],
                "manifest_sha256": handle.manifest_sha256,
                "manifest_resource_uri": manifest_resource_uri,
                "subject_count": len(subject_descriptors),
                "subject_read_contract": {
                    "only_manifest_subjects_are_readable": True,
                    "subject_hash_is_reverified_on_every_read": True,
                    "context_is_reverified_on_every_read": True,
                    "resources_are_process_local_and_short_lived": True,
                    "chatgpt_tool_read_fallback_is_hash_bound": True,
                },
                "validation_preview": {
                    "commands": list(manifest.get("acceptance_commands") or []),
                    "commands_executed": False,
                },
                "authority_boundary": self._host._review_manifest_authority_boundary(),
            },
            "recommended_next_reads": recommended_next_reads,
        }

    @staticmethod
    def _template(current_context: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "workflow": REVIEW_MANIFEST_WORKFLOW,
            "phase": "inspect",
            "status": "template_ready",
            "schema_version": "colameta.review_manifest_template.v1",
            "read_only": True,
            "side_effects": False,
            "context_binding": dict(current_context),
            "review_manifest_template": {
                "schema_version": REVIEW_MANIFEST_SCHEMA_VERSION,
                "review_unit": "<caller-defined review unit>",
                "workflow_intent": REVIEW_MANIFEST_WORKFLOW_INTENT,
                **dict(current_context),
                "subjects": [
                    {
                        "path": "<project-relative safe text path>",
                        "sha256": "<SHA-256 of exact current file bytes>",
                    }
                ],
                "acceptance_commands": [
                    {"command": "<declared command; preview only, not executed>"}
                ],
            },
            "required_next_input": [
                "review_manifest.review_unit",
                "review_manifest.subjects",
            ],
            "authority_boundary": {
                "does_not_read_files": True,
                "does_not_execute_acceptance_commands": True,
                "does_not_authorize_executor_run": True,
                "does_not_authorize_commit_or_push": True,
            },
        }

    def _read(
        self,
        *,
        params: dict[str, Any],
        stored: StoredReviewManifest,
        current_context: dict[str, Any],
    ) -> dict[str, Any]:
        subject_index = params.get("review_manifest_subject_index")
        if (
            isinstance(subject_index, bool)
            or not isinstance(subject_index, int)
            or subject_index < 1
        ):
            raise ReviewManifestWorkflowError(
                "REVIEW_MANIFEST_SUBJECT_INDEX_REQUIRED",
                "review_manifest read 必须提供 inspect 返回的正整数 review_manifest_subject_index。",
            )
        page = params.get("review_manifest_page", 1)
        if isinstance(page, bool) or not isinstance(page, int) or page < 1:
            raise ReviewManifestWorkflowError(
                "INVALID_REVIEW_MANIFEST_PAGE",
                "review_manifest read 的 review_manifest_page 必须是正整数。",
            )
        try:
            verify_stored_review_context(
                stored,
                current_context_binding=current_context,
            )
            subject_page = read_stored_review_manifest_page(
                stored,
                subject_index=subject_index,
                page=page,
            )
        except ReviewManifestError as exc:
            raise ReviewManifestWorkflowError(
                exc.error_code,
                exc.message,
                exc.details,
            ) from exc
        return self._read_packet(
            stored=stored,
            subject_index=subject_index,
            subject_page=subject_page,
        )

    def _read_packet(
        self,
        *,
        stored: StoredReviewManifest,
        subject_index: int,
        subject_page: Any,
    ) -> dict[str, Any]:
        page = int(subject_page.page)
        page_count = int(subject_page.page_count)
        compatibility_project_name = (
            str(stored.context_binding.get("project_name") or "").strip()
            if self._host.service_mode
            else None
        )
        read_call = self._host._review_manifest_read_call(
            stored.handle,
            subject_index=subject_index,
            page=page,
            project_name=compatibility_project_name,
        )
        recommended_next_reads: list[dict[str, Any]] = []
        if page < page_count:
            next_read_call = self._host._review_manifest_read_call(
                stored.handle,
                subject_index=subject_index,
                page=page + 1,
                project_name=compatibility_project_name,
            )
            recommended_next_reads.append(
                {
                    "kind": "mcp_tool",
                    **next_read_call,
                    "reason": "继续读取同一已绑定 subject 的下一页；上下文和 SHA-256 会再次复核。",
                }
            )
        return {
            "ok": True,
            "workflow": REVIEW_MANIFEST_WORKFLOW,
            "phase": "read",
            "schema_version": "colameta.review_manifest_read.v1",
            "read_only": True,
            "side_effects": False,
            **self._host._review_manifest_handle_fields(stored.handle),
            "review_unit": stored.context_binding["review_unit"],
            "workflow_intent": stored.context_binding["workflow_intent"],
            "context_binding": dict(stored.context_binding),
            "verification": {
                "context_binding": "matched",
                "subject_hash": "matched",
                "subject_index": subject_index,
            },
            "subject_page": subject_page.to_dict(),
            "read_call": read_call,
            "recommended_next_reads": recommended_next_reads,
            "authority_boundary": self._host._review_manifest_authority_boundary(),
        }
