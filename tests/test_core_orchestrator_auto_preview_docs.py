from __future__ import annotations

from typing import Any

from runner.core_orchestrator import WorkflowOrchestrator


class _DocsManager:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def handle(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((action, params))
        if action == "index":
            return {"ok": True, "doc_index": []}
        if action == "append_section_preview":
            return {
                "ok": True,
                "preview_id": "docs-preview-1",
                "changed_files": ["docs/operations.md"],
            }
        raise AssertionError(f"unexpected action: {action}")


def test_auto_preview_passes_append_section_parameters_to_docs_workflow() -> None:
    docs = _DocsManager()
    orchestrator = WorkflowOrchestrator(
        "/tmp/project",
        project_docs_manager=docs,  # type: ignore[arg-type]
    )

    result = orchestrator._workflow_auto_preview(
        {
            "goal": "Append a docs section",
            "file": "docs/operations.md",
            "section_heading": "Connector smoke",
            "section_content": "Run the connector smoke.",
            "after_heading": "Verify",
            "reason": "Record the acceptance path.",
        }
    )

    assert result.status == "preview_ready"
    assert result.preview_ids == ["docs-preview-1"]
    assert result.changed_files == ["docs/operations.md"]
    assert docs.calls[1] == (
        "append_section_preview",
        {
            "file": "docs/operations.md",
            "section_heading": "Connector smoke",
            "section_content": "Run the connector smoke.",
            "after_heading": "Verify",
            "reason": "Record the acceptance path.",
        },
    )
