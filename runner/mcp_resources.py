"""MCP resource and packaged-result contracts outside the transport server.

Resources are read-only projections.  They may expose a pre-issued opaque
result-artifact handle or a hash-bound review-manifest session, but they do not
grant project-file, executor, validation, Git, review-decision, or delivery
authority.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from runner.mcp_result_artifacts import MCPResultArtifactStore, ResultArtifactHandle
from runner.mcp_review_manifest import MCPReviewManifestResources
from runner.mcp_workflow_migration import RESULT_ARTIFACT_WORKFLOW
from runner.review_manifest import ReviewManifestHandle, ReviewManifestStore, StoredReviewManifest


RESULT_ARTIFACT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
RESULT_ARTIFACT_URI_RE = re.compile(
    r"^colameta://result-artifact/(?P<artifact_id>[A-Za-z0-9_-]{16,128})"
    r"(?:/pages/(?P<page>[1-9][0-9]*))?$"
)
RESULT_ARTIFACT_RESOURCE_TEMPLATES: tuple[dict[str, str], ...] = (
    {
        "name": "colameta_result_artifact",
        "title": "Paged packaged result",
        "description": (
            "Read page 1 of a short-lived packaged tool result. The opaque artifact "
            "ID must come from a packaged=true tool response; live artifacts are never "
            "listed."
        ),
        "uriTemplate": "colameta://result-artifact/{artifact_id}",
        "mimeType": "application/json",
    },
    {
        "name": "colameta_result_artifact_page",
        "title": "Paged packaged result page",
        "description": (
            "Read a later page of a short-lived packaged tool result. Use only the "
            "opaque artifact ID and page_uri_template returned by the originating response."
        ),
        "uriTemplate": "colameta://result-artifact/{artifact_id}/pages/{page}",
        "mimeType": "application/json",
    },
)
REVIEW_MANIFEST_RESOURCE_TEMPLATES: tuple[dict[str, str], ...] = (
    {
        "name": "colameta_review_manifest",
        "title": "Hash-bound review manifest",
        "description": (
            "Read the short-lived summary for a review_manifest session returned by "
            "run_mcp_workflow. The opaque ID must come from a successful inspect call."
        ),
        "uriTemplate": "colameta://review-manifest/{review_manifest_id}",
        "mimeType": "application/json",
    },
    {
        "name": "colameta_review_manifest_subject",
        "title": "Hash-bound review subject",
        "description": (
            "Read page 1 of one manifest-declared subject. The server rechecks the "
            "review context and subject SHA-256 before returning content."
        ),
        "uriTemplate": "colameta://review-manifest/{review_manifest_id}/subjects/{subject_index}",
        "mimeType": "application/json",
    },
    {
        "name": "colameta_review_manifest_subject_page",
        "title": "Hash-bound review subject page",
        "description": (
            "Read a later page of one manifest-declared subject. Only opaque IDs and "
            "page numbers returned by inspect are valid."
        ),
        "uriTemplate": (
            "colameta://review-manifest/{review_manifest_id}/subjects/{subject_index}"
            "/pages/{page}"
        ),
        "mimeType": "application/json",
    },
)


class MCPResourcesService:
    """Compose bounded resource reads over process-local stores."""

    def __init__(
        self,
        *,
        result_artifact_store: MCPResultArtifactStore,
        review_manifest_store: ReviewManifestStore,
        commander_widget_uri: str,
        commander_app_title: str,
        commander_widget_mime_type: str,
        commander_widget_html_reader: Callable[[], str],
        commander_widget_meta_reader: Callable[[], dict[str, Any]],
    ) -> None:
        self._result_artifact_store = result_artifact_store
        self._review_manifest_store = review_manifest_store
        self._commander_widget_uri = commander_widget_uri
        self._commander_app_title = commander_app_title
        self._commander_widget_mime_type = commander_widget_mime_type
        self._commander_widget_html_reader = commander_widget_html_reader
        self._commander_widget_meta_reader = commander_widget_meta_reader

    @staticmethod
    def result_artifact_uri(artifact_id: str, page: int | None = None) -> str:
        base = f"colameta://result-artifact/{artifact_id}"
        return base if page is None else f"{base}/pages/{page}"

    @staticmethod
    def parse_result_artifact_uri(uri: str) -> tuple[str, int] | None:
        matched = RESULT_ARTIFACT_URI_RE.fullmatch(uri)
        if matched is None:
            return None
        artifact_id = matched.group("artifact_id")
        page_raw = matched.group("page")
        try:
            page = int(page_raw) if page_raw is not None else 1
        except ValueError:
            return None
        return artifact_id, page

    def store_packaged_result_artifact(
        self,
        tool_name: str,
        structured_tool_result: dict[str, Any],
    ) -> dict[str, Any] | None:
        handle = self._result_artifact_store.put(
            tool=tool_name,
            payload=structured_tool_result,
        )
        if handle is None:
            return None
        return self.result_artifact_manifest_fields(handle)

    def result_artifact_manifest_fields(
        self,
        handle: ResultArtifactHandle,
    ) -> dict[str, Any]:
        resource_uri = self.result_artifact_uri(handle.artifact_id)
        return {
            "artifact_id": handle.artifact_id,
            "resource_uri": resource_uri,
            "page_uri_template": f"{resource_uri}/pages/{{page}}",
            "page_count": handle.page_count,
            "content_sha256": handle.content_sha256,
            "expires_at": handle.expires_at,
        }

    @staticmethod
    def result_artifact_next_read(artifact_fields: dict[str, Any]) -> dict[str, Any]:
        return {
            "kind": "mcp_resource",
            "tool": "resources/read",
            "arguments": {"uri": artifact_fields.get("resource_uri")},
            "reason": "可选的标准 MCP 资源续读：支持动态 resources/read 的客户端可读取第 1 页，再按 page_uri_template 续读。",
        }

    @staticmethod
    def result_artifact_compatibility_read_call(
        artifact_id: str,
        *,
        page: int,
    ) -> dict[str, Any]:
        return {
            "tool": "run_mcp_workflow",
            "arguments": {
                "workflow": RESULT_ARTIFACT_WORKFLOW,
                "phase": "read",
                "artifact_id": artifact_id,
                "artifact_page": page,
            },
        }

    @staticmethod
    def typed_result_artifact_read_call(
        artifact_id: str,
        *,
        page: int,
    ) -> dict[str, Any]:
        return {
            "tool": "read_result_artifact",
            "arguments": {
                "artifact_id": artifact_id,
                "artifact_page": page,
            },
        }

    @classmethod
    def result_artifact_typed_next_read(
        cls,
        artifact_fields: dict[str, Any],
        *,
        page: int = 1,
    ) -> dict[str, Any]:
        artifact_id = artifact_fields.get("artifact_id")
        if not isinstance(artifact_id, str) or not artifact_id:
            raise ValueError("artifact_fields must include artifact_id")
        return {
            "kind": "mcp_tool",
            **cls.typed_result_artifact_read_call(artifact_id, page=page),
            "reason": (
                "通过 ChatGPT 可调用的 read_result_artifact 读取同一短期 artifact 页；"
                "保留 artifact_id、页码、SHA-256 与 expiry 合同。"
            ),
        }

    @classmethod
    def result_artifact_compatibility_next_read(
        cls,
        artifact_fields: dict[str, Any],
        *,
        page: int = 1,
    ) -> dict[str, Any]:
        artifact_id = artifact_fields.get("artifact_id")
        if not isinstance(artifact_id, str) or not artifact_id:
            raise ValueError("artifact_fields must include artifact_id")
        return {
            "kind": "mcp_tool_compatibility",
            **cls.result_artifact_compatibility_read_call(artifact_id, page=page),
            "reason": "旧客户端兼容：通过 run_mcp_workflow 的 result_artifact read 读取同一短期 artifact 页。",
        }

    def result_artifact_recommended_next_reads(
        self,
        artifact_fields: dict[str, Any],
    ) -> list[dict[str, Any]]:
        return [
            self.result_artifact_typed_next_read(artifact_fields),
            self.result_artifact_next_read(artifact_fields),
            self.result_artifact_compatibility_next_read(artifact_fields),
        ]

    def result_artifact_recovery_manifest(
        self,
        *,
        tool_name: str,
        ok: bool,
        artifact_fields: dict[str, Any],
        original_error_code: Any = None,
    ) -> dict[str, Any]:
        manifest: dict[str, Any] = {
            "ok": ok,
            "tool": tool_name,
            "packaged": True,
            "package_mode": "artifact_continuation",
            "message": (
                "完整结果已保存为短期分页 artifact；请先通过 read_result_artifact "
                "读取各页并核对 content_sha256。支持动态 resources/read 的 MCP 客户端也可使用 resource_uri。"
            ),
            "omitted_fields": ["full_result"],
            "recommended_next_reads": self.result_artifact_recommended_next_reads(
                artifact_fields,
            ),
        }
        manifest.update(artifact_fields)
        if not ok and isinstance(original_error_code, str):
            manifest["error_code"] = original_error_code
        return manifest

    @staticmethod
    def result_artifact_unavailable_result(
        *,
        tool_name: str,
        error_code: str,
        message: str,
        recommended_next_reads: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "ok": False,
            "tool": tool_name,
            "packaged": False,
            "error_code": error_code,
            "message": message,
            "recommended_next_reads": recommended_next_reads,
        }

    @staticmethod
    def read_scoped_resource_access_error(
        auth_context: object | None,
        *,
        resource_label: str,
    ) -> tuple[str, str] | None:
        if not isinstance(auth_context, dict):
            return None
        auth_mode = auth_context.get("mode")
        if auth_mode == "cloud-relay":
            scopes = auth_context.get("scopes")
            if not isinstance(scopes, list) or "mcp:read" not in scopes:
                return "resource_access_denied", f"{resource_label} requires the mcp:read scope."
            return None
        if auth_mode not in {"oauth", "external-oauth"}:
            return None
        oauth_provider = auth_context.get("oauth_provider")
        token_payload = auth_context.get("token")
        validate_scope = getattr(oauth_provider, "validate_scope", None)
        if not callable(validate_scope) or not isinstance(token_payload, dict):
            return "resource_auth_invalid", f"{resource_label} requires a valid read-scoped OAuth token."
        try:
            allowed = bool(validate_scope(token_payload, "mcp:read"))
        except Exception:
            allowed = False
        if not allowed:
            return "resource_access_denied", f"{resource_label} requires the mcp:read scope."
        return None

    @classmethod
    def result_artifact_resource_access_error(
        cls,
        auth_context: object | None,
    ) -> tuple[str, str] | None:
        return cls.read_scoped_resource_access_error(
            auth_context,
            resource_label="Result artifact",
        )

    def review_manifest_resources(self) -> MCPReviewManifestResources:
        return MCPReviewManifestResources(self._review_manifest_store)

    @staticmethod
    def review_manifest_uri(
        review_manifest_id: str,
        *,
        subject_index: int | None = None,
        page: int | None = None,
    ) -> str:
        return MCPReviewManifestResources.uri(
            review_manifest_id,
            subject_index=subject_index,
            page=page,
        )

    @staticmethod
    def parse_review_manifest_uri(
        uri: str,
    ) -> tuple[str, int | None, int | None] | None:
        return MCPReviewManifestResources.parse_uri(uri)

    def review_manifest_handle_fields(self, handle: ReviewManifestHandle) -> dict[str, Any]:
        return self.review_manifest_resources().handle_fields(handle)

    @staticmethod
    def review_manifest_read_call(
        handle: ReviewManifestHandle,
        *,
        subject_index: int,
        page: int,
        project_name: str | None = None,
    ) -> dict[str, Any]:
        return MCPReviewManifestResources.read_call(
            handle,
            subject_index=subject_index,
            page=page,
            project_name=project_name,
        )

    def review_manifest_subject_descriptor(
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
        return self.review_manifest_resources().subject_descriptor(
            handle,
            subject_index=subject_index,
            path=path,
            sha256=sha256,
            byte_size=byte_size,
            page_count=page_count,
            project_name=project_name,
        )

    def review_manifest_resource_read_result(self, uri: str) -> dict[str, Any] | None:
        return self.review_manifest_resources().read_resource(uri)

    def review_manifest_resource_summary(
        self,
        stored: StoredReviewManifest,
    ) -> dict[str, Any]:
        return self.review_manifest_resources().resource_summary(stored)

    @staticmethod
    def review_manifest_authority_boundary() -> dict[str, bool]:
        return MCPReviewManifestResources.authority_boundary()

    def mcp_resources_list_result(self) -> dict[str, Any]:
        return {
            "resources": [
                {
                    "uri": self._commander_widget_uri,
                    "name": "colameta_commander",
                    "title": self._commander_app_title,
                    "description": "Read-only ColaMeta Commander panel for ChatGPT Apps.",
                    "mimeType": self._commander_widget_mime_type,
                    "_meta": self._commander_widget_meta_reader(),
                }
            ]
        }

    @staticmethod
    def mcp_resource_templates_list_result() -> dict[str, Any]:
        return {
            "resourceTemplates": [
                *[dict(item) for item in RESULT_ARTIFACT_RESOURCE_TEMPLATES],
                *[dict(item) for item in REVIEW_MANIFEST_RESOURCE_TEMPLATES],
            ]
        }

    def mcp_resource_read_result(self, uri: str) -> dict[str, Any] | None:
        if uri == self._commander_widget_uri:
            return {
                "contents": [
                    {
                        "uri": uri,
                        "mimeType": self._commander_widget_mime_type,
                        "text": self._commander_widget_html_reader(),
                        "_meta": self._commander_widget_meta_reader(),
                    }
                ]
            }

        parsed = self.parse_result_artifact_uri(uri)
        if parsed is None:
            return None
        artifact_id, page = parsed
        artifact_page = self._result_artifact_store.read_page(artifact_id, page)
        if artifact_page is None:
            return None
        return {
            "contents": [
                {
                    "uri": uri,
                    "mimeType": "application/json",
                    "text": json.dumps(artifact_page.to_dict(), ensure_ascii=False),
                }
            ]
        }
