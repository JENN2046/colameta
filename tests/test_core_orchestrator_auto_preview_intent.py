from __future__ import annotations

import pytest

from runner.core_orchestrator import WorkflowOrchestrator


@pytest.mark.parametrize(
    "goal",
    [
        "Inspect the project state, but do not start executor.",
        "Review the current session without running Codex.",
        "Inspect the project state, but do not invoke an executor.",
        "Review the current session; don't run an executor.",
        "Inspect only, without starting an executor.",
        "只查看执行器状态，不要启动执行器。",
        "不运行 executor，只读检查当前项目。",
    ],
)
def test_auto_preview_treats_explicit_executor_negation_as_a_hard_route_veto(
    goal: str,
) -> None:
    classified = WorkflowOrchestrator._classify_goal(goal)

    assert classified["selected_workflow"] == "project_status"
    assert "explicitly forbids executor" in classified["reason"]


def test_auto_preview_preserves_a_specific_non_executor_workflow_under_negation() -> None:
    classified = WorkflowOrchestrator._classify_goal(
        "Update the docs, but do not start executor."
    )

    assert classified["selected_workflow"] == "docs"


def test_auto_preview_uses_read_only_project_status_when_executor_is_forbidden() -> None:
    calls: list[dict[str, object]] = []

    def analyze_state(params: dict[str, object]) -> dict[str, object]:
        calls.append(params)
        return {"ok": True, "recommended_next_actions": []}

    result = WorkflowOrchestrator(
        "/tmp/project",
        analyze_state_fn=analyze_state,
    )._workflow_auto_preview(
        {"goal": "Inspect current status; do not start executor."}
    )

    assert result.selected_workflow == "project_status"
    assert result.stop_reason == "goal_unclassified"
    assert len(calls) == 1
    assert result.steps == [
        {
            "name": "auto_preview",
            "tool": "analyze_project_state",
            "action": "analyze",
            "ok": True,
            "risk_level": "info",
            "preview_id": None,
            "changed_files": [],
            "blockers": [],
            "warnings": [],
        }
    ]
