from __future__ import annotations

import pytest

from runner.core_orchestrator import WorkflowOrchestrator


@pytest.mark.parametrize("verb", ["choose", "select", "report", "return", "provide", "recommend"])
@pytest.mark.parametrize("template", [
    "Update the docs to {verb} a read-only action for reviewers.",
    "Update the docs to explain how to {verb} a read-only workflow.",
    "Update the docs to describe workflows that inspect state and {verb} a read-only action.",
])
def test_documentation_about_read_only_actions_can_preview(verb, template):
    class DocsStub:
        def __init__(self):
            self.calls = []

        def handle(self, action, params):
            self.calls.append(action)
            return {"ok": True, **({"preview_id": "docs-test"} if action.endswith("_preview") else {})}

    docs = DocsStub()
    result = WorkflowOrchestrator(
        "/tmp/project", project_docs_manager=docs,
    )._workflow_auto_preview({
        "goal": template.format(verb=verb), "file": "README.md",
        "heading": "Usage", "new_content": "Recommend a read-only action for reviewers.",
    })
    assert docs.calls == ["index", "update_section_preview"]
    assert result.selected_workflow == "docs_update"
    assert result.preview_ids == ["docs-test"]
    assert result.requires_confirmation is True


@pytest.mark.parametrize("goal", [
    "Update the docs to explain how to keep this task read-only.",
    "Update the docs to explain how to make this task read-only.",
    "Update the docs to explain how to treat this task read-only.",
    "Update the docs to explain how to perform a read-only inspection.",
    "Update the docs to explain how to conduct a read-only review.",
    "Update the docs to explain how to run a read-only check.",
])
def test_other_read_only_predicates_in_documentation_remain_subject_matter(goal):
    assert WorkflowOrchestrator._classify_goal(goal)["selected_workflow"] == "docs"


@pytest.mark.parametrize("goal", [
    "Update the docs. Recommend a read-only action for reviewers.",
    "Update the docs; select a read-only workflow.",
    "Update the docs and report the next read-only action.",
    "Update the docs, but return a read-only response.",
    "Update the docs\rProvide a read-only action.",
    "Update the docs. Could you recommend a read-only action?",
    "Update the docs. You should choose a read-only workflow.",
    "Update the docs to explain routing, and please recommend a read-only action.",
    "Update the docs to explain routing and you must recommend a read-only action.",
    "Update the docs and keep this task read-only.",
    "Update the docs. Please conduct a read-only review.",
    "Update the docs. We should perform a read-only inspection.",
    "Update the docs, but only perform a read-only inspection.",
    "Update the docs, but just conduct a read-only review.",
    "Update the docs; for this request please recommend a read-only action.",
    "Update the docs to explain routing and please recommend a read-only action.",
])
def test_independent_read_only_instructions_still_veto_document_preview(goal):
    class RejectDocs:
        def handle(self, _action, _params):
            raise AssertionError("a task read-only constraint must veto docs preview")

    result = WorkflowOrchestrator(
        "/tmp/project", project_docs_manager=RejectDocs(),
        analyze_state_fn=lambda _params: {"ok": True, "recommended_next_actions": []},
    )._workflow_auto_preview({
        "goal": goal, "file": "README.md", "heading": "Usage", "new_content": "Not authorized",
    })
    assert result.selected_workflow == "project_status"
    assert result.preview_ids == []
    assert result.next_actions == []
    assert result.requires_confirmation is False
