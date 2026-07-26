"""Bounded ``current_facts`` workflow over canonical project observations."""

from __future__ import annotations

from typing import Any, Protocol

from runner.current_facts_artifact import (
    CurrentFactsArtifact,
    CurrentFactsArtifactError,
    CurrentFactsPreviewStore,
    build_current_facts_artifact,
    write_current_facts_archive,
)


CURRENT_FACTS_WORKFLOW = "current_facts"


class CurrentFactsWorkflowError(ValueError):
    """A bounded error returned by the current-facts workflow."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message


class CurrentFactsWorkflowHost(Protocol):
    project_root: str
    _current_facts_preview_store: CurrentFactsPreviewStore

    def _current_facts_analyze(self, params: dict[str, Any]) -> dict[str, Any]: ...

    def _store_packaged_result_artifact(
        self,
        tool_name: str,
        structured_tool_result: dict[str, Any],
    ) -> dict[str, Any] | None: ...

    def _result_artifact_recommended_next_reads(
        self,
        artifact_fields: dict[str, Any],
    ) -> list[dict[str, Any]]: ...


class MCPCurrentFactsWorkflow:
    """Generate read artifacts and explicitly confirmed local archive pairs."""

    def __init__(self, host: CurrentFactsWorkflowHost) -> None:
        self._host = host

    def handle(self, params: dict[str, Any]) -> dict[str, Any]:
        phase = _phase(params.get("phase"))
        if phase == "inspect":
            return self._inspect(params)
        if phase == "preview":
            return self._preview(params)
        if phase == "apply":
            return self._apply(params)
        raise CurrentFactsWorkflowError(
            "CURRENT_FACTS_PHASE_NOT_SUPPORTED",
            "current_facts 只支持 inspect、preview 或 apply。",
        )

    def _inspect(self, params: dict[str, Any]) -> dict[str, Any]:
        artifact = self._build_artifact(params)
        return self._artifact_result(artifact, phase="inspect")

    def _preview(self, params: dict[str, Any]) -> dict[str, Any]:
        artifact = self._build_artifact(params)
        preview = self._host._current_facts_preview_store.put(
            project_root=self._host.project_root,
            artifact=artifact,
        )
        result = self._artifact_result(artifact, phase="preview")
        result.update(preview.descriptor())
        result.update(
            {
                "read_only": True,
                "side_effects": False,
                "requires_confirmation": True,
                "next_actions": [
                    {
                        "tool": "run_mcp_workflow",
                        "params": {
                            "workflow": CURRENT_FACTS_WORKFLOW,
                            "phase": "apply",
                            "preview_id": preview.preview_id,
                        },
                        "required_scope": "mcp:commit",
                        "requires_context_binding": True,
                        "reason": "显式确认后才把已绑定 current-facts 快照写入固定 runtime archive。",
                    }
                ],
                "authority_boundary": _authority_boundary(
                    read_only=True,
                    does_write_runtime_archive=False,
                ),
            }
        )
        return result

    def _apply(self, params: dict[str, Any]) -> dict[str, Any]:
        preview_id = params.get("preview_id")
        if not isinstance(preview_id, str) or not preview_id.strip():
            raise CurrentFactsWorkflowError(
                "CURRENT_FACTS_PREVIEW_ID_REQUIRED",
                "current_facts apply 必须提供 preview 返回的 preview_id。",
            )
        preview = self._host._current_facts_preview_store.get(
            preview_id=preview_id,
            project_root=self._host.project_root,
        )
        if preview is None:
            raise CurrentFactsWorkflowError(
                "CURRENT_FACTS_PREVIEW_NOT_FOUND_OR_EXPIRED",
                "current-facts preview 不存在、已过期或不属于当前项目；请重新 preview。",
            )
        current = self._build_artifact(params)
        if (
            current.canonical_state_semantic_sha256
            != preview.artifact.canonical_state_semantic_sha256
        ):
            raise CurrentFactsWorkflowError(
                "CURRENT_FACTS_PREVIEW_STALE",
                "current-facts 当前观察已变化；已停止写入，请重新 preview 并确认。",
            )
        try:
            archive = write_current_facts_archive(self._host.project_root, preview.artifact)
        except CurrentFactsArtifactError as exc:
            raise CurrentFactsWorkflowError(exc.code, exc.message) from exc

        result = self._artifact_result(preview.artifact, phase="apply")
        result.update(
            {
                "read_only": False,
                "side_effects": True,
                "requires_confirmation": False,
                "preview_id": preview.preview_id,
                "archive": archive,
                "current_observation_rechecked": True,
                "changed_files": [
                    item["path"]
                    for item in archive.get("files", [])
                    if isinstance(item, dict) and isinstance(item.get("path"), str)
                ],
                "authority_boundary": _authority_boundary(
                    read_only=False,
                    does_write_runtime_archive=True,
                ),
            }
        )
        return result

    def _build_artifact(self, params: dict[str, Any]) -> CurrentFactsArtifact:
        analyze_params: dict[str, Any] = {}
        provider = params.get("provider")
        if isinstance(provider, str) and provider.strip():
            analyze_params["provider"] = provider.strip()
        analysis = self._host._current_facts_analyze(analyze_params)
        canonical_state = analysis.get("canonical_state") if isinstance(analysis, dict) else None
        if not isinstance(analysis, dict) or analysis.get("ok") is not True or not isinstance(canonical_state, dict):
            raise CurrentFactsWorkflowError(
                "CURRENT_FACTS_UNAVAILABLE",
                "无法从当前项目状态分析获得 canonical_project_state。",
            )
        try:
            return build_current_facts_artifact(canonical_state)
        except CurrentFactsArtifactError as exc:
            raise CurrentFactsWorkflowError(exc.code, exc.message) from exc

    def _artifact_result(self, artifact: CurrentFactsArtifact, *, phase: str) -> dict[str, Any]:
        artifact_payload = {
            "ok": True,
            "tool": "run_mcp_workflow",
            "data": {
                "workflow": CURRENT_FACTS_WORKFLOW,
                "phase": phase,
                "current_facts": artifact.payload,
                "current_facts_markdown": artifact.markdown_text,
            },
        }
        result_artifact = self._host._store_packaged_result_artifact(
            "run_mcp_workflow",
            artifact_payload,
        )
        if result_artifact is None:
            raise CurrentFactsWorkflowError(
                "CURRENT_FACTS_RESULT_ARTIFACT_UNAVAILABLE",
                "current-facts 快照已生成，但无法建立可恢复的分页 result artifact。",
            )
        return {
            "ok": True,
            "workflow": CURRENT_FACTS_WORKFLOW,
            "phase": phase,
            "read_only": True,
            "side_effects": False,
            "current_facts": artifact.descriptor(),
            "result_artifact": result_artifact,
            **result_artifact,
            "recommended_next_reads": self._host._result_artifact_recommended_next_reads(
                result_artifact,
            ),
            "authority_boundary": _authority_boundary(
                read_only=True,
                does_write_runtime_archive=False,
            ),
        }


def _phase(value: Any) -> str:
    if value is None:
        return "inspect"
    return value.strip().lower() if isinstance(value, str) else ""


def _authority_boundary(
    *,
    read_only: bool,
    does_write_runtime_archive: bool,
) -> dict[str, bool]:
    return {
        "read_only": read_only,
        "side_effects": not read_only,
        "does_not_read_project_files": True,
        "does_not_read_tokens_or_cookies": True,
        "does_not_read_raw_runtime_state": True,
        "does_not_write_tracked_documentation": True,
        "does_write_fixed_runtime_archive": does_write_runtime_archive,
        "does_not_authorize_executor_run": True,
        "does_not_authorize_validation_run": True,
        "does_not_authorize_commit_or_push": True,
        "does_not_authorize_stable_replacement": True,
        "does_not_authorize_delivery_acceptance": True,
    }
