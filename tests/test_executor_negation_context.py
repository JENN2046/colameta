from __future__ import annotations

import pytest

from runner.core_orchestrator import WorkflowOrchestrator, _positive_routing_evidence
from runner.mcp_workflow_router import MCPWorkflowRouter


@pytest.mark.parametrize("negation", ["do not", "don't", "dont", "never"])
@pytest.mark.parametrize("template", [
    "Inspect workflows that {negation} run executor.",
    "Review modes which {negation} launch Codex.",
    "Inspect workflows that {negation} run executor and {negation} launch Codex.",
])
def test_described_executor_prohibition_is_inspection_evidence(negation, template):
    assert WorkflowOrchestrator._classify_goal(template.format(negation=negation))[
        "selected_workflow"
    ] == "executor"


@pytest.mark.parametrize("goal", [
    "Inspect executor behavior for workflows that do not run executor.",
    "Inspect workflows with no executor.",
    "Inspect workflows without executor.",
    "Inspect configurations without an executor.",
    "Inspect workflows that have no executor.",
    "Inspect modes where there is no executor.",
    "Inspect workflows that operate without running executor.",
    "Inspect workflows to explain how they operate without running executor.",
    "Inspect how workflows function without running executor.",
    "Inspect modes that work without launching Codex.",
    "Inspect workflows that run without executor.",
    "Inspect workflows that complete without running executor.",
    "Inspect configurations that were created without an executor.",
    "Inspect workflows which operate reliably without running executor.",
    "Inspect workflows where tasks run without executor.",
    "Inspect workflows that inspect state and do not run executor.",
    "Inspect how workflows do not run executor and do not launch Codex.",
])
def test_described_absent_executor_runs_only_read_only_preflight(tmp_path, goal):
    result = MCPWorkflowRouter(str(tmp_path), agent_profile_id="web_gpt_commander").handle(
        "auto_preview", {"goal": goal},
    )
    assert result["selected_workflow"] == "executor_preflight"
    assert result["changed_files"] == []
    assert result["preview_ids"] == []
    assert result["requires_confirmation"] is False
    assert {step["risk_level"] for step in result["steps"]} == {"info"}


@pytest.mark.parametrize("goal", [
    "Inspect state without running executor.",
    "Inspect state; no executor.",
    "Inspect state with no executor.",
    "Inspect state, but do not run executor.",
    "Inspect state and don't run executor.",
    "Inspect how executor works and do not run executor.",
    "Inspect why executor stops and don't launch Codex.",
    "Inspect how executor works and no executor.",
    "Inspect how executor works and without running executor.",
    "Inspect executor behavior to explain failures and do not run executor.",
    "Inspect executor behavior to describe failures and no executor.",
    "Never run executor; inspect state.",
    "Inspect workflows that do not run executor. Do not run executor.",
    "Inspect workflows with no executor; no executor.",
    "Inspect workflows that operate without running executor. Never run executor.",
    "Inspect workflows that don't run executor, but you must not run executor.",
    "Inspect workflows that never run executor\nDo not launch Codex.",
    "检查项目状态，不要运行执行器。",
    "检查项目状态，不启动 executor。",
])
def test_real_executor_constraints_still_prevent_preflight(goal):
    class RejectExecutor(WorkflowOrchestrator):
        def _auto_preview_executor(self, _params):
            raise AssertionError("an executor constraint must veto preflight")

    result = RejectExecutor(
        "/tmp/project",
        analyze_state_fn=lambda _params: {"ok": True, "recommended_next_actions": []},
    )._workflow_auto_preview({"goal": goal})
    assert result.selected_workflow == "project_status"
    assert result.preview_ids == []
    assert result.requires_confirmation is False


def test_described_executor_does_not_restore_trailing_mutation_evidence():
    positive, _, _ = _positive_routing_evidence(
        "Inspect workflows that do not run executor and edit README."
    )
    assert "executor" in positive
    assert "edit" not in positive


@pytest.mark.parametrize("goal", [
    "Inspect where executor is installed without running executor.",
    "Inspect how executor is configured without launching Codex.",
    "Inspect how executor works without running executor.",
    "Inspect workflows that run without executor during this inspection.",
    "Inspect workflows without executor for this task.",
    "Inspect workflows that run and you must inspect state without running executor.",
    "Inspect workflows that run but you must inspect state without running executor.",
    "For this task, inspect how executor is configured without running executor during this inspection.",
    "Inspect how executor is configured without running executor; only inspect its configuration.",
])
def test_query_subject_does_not_cancel_without_execution_constraint(goal):
    class RejectExecutor(WorkflowOrchestrator):
        def _auto_preview_executor(self, _params):
            raise AssertionError("inspection's without constraint must veto preflight")

    result = RejectExecutor(
        "/tmp/project",
        analyze_state_fn=lambda _params: {"ok": True, "recommended_next_actions": []},
    )._workflow_auto_preview({"goal": goal})
    assert result.selected_workflow == "project_status"
    assert result.preview_ids == []
    assert result.changed_files == []
    assert result.next_actions == []
    assert result.requires_confirmation is False
