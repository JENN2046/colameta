from __future__ import annotations

import json
from pathlib import Path

import pytest

from runner.core_orchestrator import WorkflowOrchestrator
from runner.mcp_workflow_router import MCPWorkflowRouter


LIVE_FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures" / "agent_routing_r1_live_acceptance.json")
    .read_text(encoding="utf-8")
)


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


def test_exact_live_negative_intent_never_starts_a_mutating_route() -> None:
    commit_calls: list[tuple[str, dict[str, object]]] = []

    class CommitManager:
        def handle(self, action: str, params: dict[str, object]) -> dict[str, object]:
            commit_calls.append((action, params))
            raise AssertionError("negative intent must not touch commit preview")

    result = WorkflowOrchestrator(
        "/tmp/project",
        analyze_state_fn=lambda _params: {
            "ok": True,
            "recommended_next_actions": [],
        },
        git_commit_manager=CommitManager(),
    )._workflow_auto_preview({"goal": LIVE_FIXTURES["negative_intent"]})

    assert result.selected_workflow == "project_status"
    assert result.preview_ids == []
    assert result.changed_files == []
    assert commit_calls == []


@pytest.mark.parametrize(
    "goal",
    [
        "do not commit",
        "don't commit",
        "do not push",
        "don't push",
        "do not run executor",
        "do not run",
        "do not merge",
        "do not replace Stable",
        "do not release",
        "without committing",
        "without pushing",
        "read only",
        "read-only",
        "inspect only",
        "no writes",
        "no mutation",
    ],
)
def test_prohibited_action_terms_are_not_positive_routing_evidence(goal: str) -> None:
    classified = WorkflowOrchestrator._classify_goal(
        f"Inspect the current project state; {goal}."
    )

    assert classified["selected_workflow"] == "project_status"


@pytest.mark.parametrize(
    ("goal", "expected_workflow"),
    [
        ("Do not run executor, update the plan.", "plan"),
        ("Don't commit, update the docs.", "docs"),
        ("Do not commit, edit the requested file.", "small_project_patch"),
        ("Do not run executor but update the plan.", "plan"),
        ("Don't commit; however update the docs.", "docs"),
        ("Do not commit yet edit the requested file.", "small_project_patch"),
    ],
)
def test_comma_delimited_positive_instruction_survives_a_negation(
    goal: str,
    expected_workflow: str,
) -> None:
    classified = WorkflowOrchestrator._classify_goal(goal)

    assert classified["selected_workflow"] == expected_workflow


@pytest.mark.parametrize(
    ("goal", "expected_workflow"),
    [
        ("Edit README to document read-only mode.", "docs"),
        ("Update the docs with a read-only configuration example.", "docs"),
        ("Edit source code to support read-only mode.", "small_project_patch"),
    ],
)
def test_read_only_subject_matter_is_not_a_global_routing_veto(
    goal: str,
    expected_workflow: str,
) -> None:
    classified = WorkflowOrchestrator._classify_goal(goal)

    assert classified["selected_workflow"] == expected_workflow


def test_read_only_executor_inspection_keeps_the_executor_preflight_route() -> None:
    classified = WorkflowOrchestrator._classify_goal(
        "Perform a read-only inspection of the executor."
    )

    assert classified["selected_workflow"] == "executor"


def test_read_only_executor_inspection_runs_only_the_bounded_preflight(
    tmp_path,
) -> None:
    result = MCPWorkflowRouter(
        str(tmp_path),
        agent_profile_id="web_gpt_commander",
    ).handle(
        "auto_preview",
        {"goal": "Perform a read-only inspection of the executor."},
    )

    assert result["selected_workflow"] == "executor_preflight"
    assert result["changed_files"] == []
    assert result["preview_ids"] == []
    assert result["requires_confirmation"] is False
    assert {step["risk_level"] for step in result["steps"]} == {"info"}


def test_executor_run_negation_still_overrides_read_only_executor_words() -> None:
    classified = WorkflowOrchestrator._classify_goal(
        "Inspect the executor read-only; do not run executor."
    )

    assert classified["selected_workflow"] == "project_status"


@pytest.mark.parametrize(
    ("goal", "expected_workflow"),
    [
        ("Do not run executor but update the plan.", "plan"),
        ("Don't commit; however, update the docs.", "docs"),
        ("Never launch Codex yet edit the requested file.", "small_project_patch"),
    ],
)
def test_contrast_delimited_positive_instruction_survives_a_negation(
    goal: str,
    expected_workflow: str,
) -> None:
    classified = WorkflowOrchestrator._classify_goal(goal)

    assert classified["selected_workflow"] == expected_workflow


@pytest.mark.parametrize(
    "goal",
    [
        "Edit README to document read-only mode.",
        "Update the docs with a read-only configuration example.",
    ],
)
def test_read_only_subject_matter_does_not_veto_docs_routing(goal: str) -> None:
    classified = WorkflowOrchestrator._classify_goal(goal)

    assert classified["selected_workflow"] == "docs"


@pytest.mark.parametrize(
    "goal",
    [
        "Inspect the current project state; read-only.",
        "Read only: inspect the current project state.",
        "Inspect the current project state and keep this task read-only.",
    ],
)
def test_read_only_directives_still_request_project_status(goal: str) -> None:
    classified = WorkflowOrchestrator._classify_goal(goal)

    assert classified["selected_workflow"] == "project_status"
