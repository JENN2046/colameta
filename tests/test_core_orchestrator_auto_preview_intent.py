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
        ("Update the docs for a read-only inspection workflow.", "docs"),
        ("Edit code handling a read-only operation.", "small_project_patch"),
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
        "Inspect the current project state and report the next read-only action.",
        "Perform a read-only inspection of the current project.",
    ],
)
def test_read_only_directives_still_request_project_status(goal: str) -> None:
    classified = WorkflowOrchestrator._classify_goal(goal)

    assert classified["selected_workflow"] == "project_status"


@pytest.mark.parametrize(
    ("goal", "expected_workflow"),
    [
        ("Do not forget to update the docs.", "docs"),
        ("Do not overlook the plan update.", "plan"),
        ("Never forget to edit the requested file.", "small_project_patch"),
    ],
)
def test_positive_do_not_forget_idioms_retain_routing_evidence(
    goal: str,
    expected_workflow: str,
) -> None:
    classified = WorkflowOrchestrator._classify_goal(goal)

    assert classified["selected_workflow"] == expected_workflow


@pytest.mark.parametrize(
    ("goal", "expected_workflow"),
    [
        ("Do not write tests; update the plan instead.", "plan"),
        ("Do not mutate README; update the docs instead.", "docs"),
    ],
)
def test_selective_write_prohibition_does_not_become_a_global_veto(
    goal: str,
    expected_workflow: str,
) -> None:
    classified = WorkflowOrchestrator._classify_goal(goal)

    assert classified["selected_workflow"] == expected_workflow


@pytest.mark.parametrize(
    "goal",
    [
        "Update the docs, but do not change any files.",
        "Update the docs but do not modify files.",
        "Update the docs, but don't make changes.",
        "Update the docs; never make any changes to the working tree.",
    ],
)
def test_global_no_change_wording_vetoes_mutating_routes(goal: str) -> None:
    classified = WorkflowOrchestrator._classify_goal(goal)

    assert classified["selected_workflow"] == "project_status"


def test_global_no_change_wording_does_not_create_a_docs_preview() -> None:
    class RejectDocsManager:
        def handle(self, _action: str, _params: dict[str, object]) -> dict[str, object]:
            raise AssertionError("global no-change intent must not enter docs preview")

    result = WorkflowOrchestrator(
        "/tmp/project",
        analyze_state_fn=lambda _params: {
            "ok": True,
            "recommended_next_actions": [],
        },
        project_docs_manager=RejectDocsManager(),  # type: ignore[arg-type]
    )._workflow_auto_preview(
        {
            "goal": "Update the docs, but do not change any files.",
            "file": "docs/operations.md",
            "heading": "Operations",
            "new_content": "This content must never be previewed.",
        }
    )

    assert result.selected_workflow == "project_status"
    assert result.preview_ids == []
    assert result.requires_confirmation is False


@pytest.mark.parametrize(
    ("goal", "expected_workflow"),
    [
        ("Do not change tests; update the plan instead.", "plan"),
        ("Do not modify tests; update the docs instead.", "docs"),
        ("Do not make changes to tests; update the plan instead.", "plan"),
    ],
)
def test_object_scoped_no_change_wording_is_not_a_global_veto(
    goal: str,
    expected_workflow: str,
) -> None:
    classified = WorkflowOrchestrator._classify_goal(goal)

    assert classified["selected_workflow"] == expected_workflow


@pytest.mark.parametrize(
    "goal",
    [
        "Inspect the current state; no commit.",
        "Inspect the current state; no pushing.",
        "Inspect the current state; no stable replacement.",
        "Inspect the current state; no run executor.",
    ],
)
def test_no_action_shorthand_is_not_positive_routing_evidence(goal: str) -> None:
    classified = WorkflowOrchestrator._classify_goal(goal)

    assert classified["selected_workflow"] == "project_status"


def test_no_commit_shorthand_does_not_create_a_commit_preview() -> None:
    class RejectCommitManager:
        def handle(self, _action: str, _params: dict[str, object]) -> dict[str, object]:
            raise AssertionError("no-commit intent must not enter commit preview")

    result = WorkflowOrchestrator(
        "/tmp/project",
        analyze_state_fn=lambda _params: {
            "ok": True,
            "recommended_next_actions": [],
        },
        git_commit_manager=RejectCommitManager(),  # type: ignore[arg-type]
    )._workflow_auto_preview(
        {
            "goal": "Inspect the current state; no commit.",
            "message": "This message must never be previewed.",
        }
    )

    assert result.selected_workflow == "project_status"
    assert result.preview_ids == []
    assert result.requires_confirmation is False


def test_no_action_shorthand_preserves_an_unrelated_positive_clause() -> None:
    classified = WorkflowOrchestrator._classify_goal(
        "No commit; update the docs instead."
    )

    assert classified["selected_workflow"] == "docs"


@pytest.mark.parametrize(
    ("goal", "expected_workflow"),
    [
        ("Do not write tests and update the plan instead.", "plan"),
        ("Do not mutate tests and update the docs instead.", "docs"),
    ],
)
def test_and_instead_positive_clause_survives_a_selective_prohibition(
    goal: str,
    expected_workflow: str,
) -> None:
    classified = WorkflowOrchestrator._classify_goal(goal)

    assert classified["selected_workflow"] == expected_workflow


@pytest.mark.parametrize(
    "action",
    [
        "sync",
        "append",
        "plan",
        "repair",
        "extend",
        "version",
        "commit",
        "stage",
        "patch",
        "edit",
        "resume",
        "exec",
        "execute",
    ],
)
def test_every_routable_action_verb_is_stripped_from_a_negated_clause(
    action: str,
) -> None:
    classified = WorkflowOrchestrator._classify_goal(
        f"Inspect current state; do not {action} changes."
    )

    assert classified["selected_workflow"] == "project_status"


def test_negated_stage_does_not_create_a_commit_preview() -> None:
    class RejectCommitManager:
        def handle(self, _action: str, _params: dict[str, object]) -> dict[str, object]:
            raise AssertionError("negated stage intent must not enter commit preview")

    result = WorkflowOrchestrator(
        "/tmp/project",
        analyze_state_fn=lambda _params: {
            "ok": True,
            "recommended_next_actions": [],
        },
        git_commit_manager=RejectCommitManager(),  # type: ignore[arg-type]
    )._workflow_auto_preview(
        {
            "goal": "Inspect current state; do not stage changes.",
            "message": "This message must never be previewed.",
        }
    )

    assert result.selected_workflow == "project_status"
    assert result.preview_ids == []
    assert result.requires_confirmation is False


@pytest.mark.parametrize(
    "goal",
    [
        "Do not keep this task read-only; update the docs.",
        "Do not perform a read-only inspection; update the docs.",
    ],
)
def test_negated_read_only_directive_does_not_veto_positive_work(goal: str) -> None:
    classified = WorkflowOrchestrator._classify_goal(goal)

    assert classified["selected_workflow"] == "docs"


@pytest.mark.parametrize(
    "goal",
    [
        "Inspect current state; do not run executor, stage any changes.",
        "Inspect current state; do not edit any files, patch any tests.",
        "Inspect current state; do not commit, push, or merge.",
        "Inspect current state; do not update any docs, commit any changes, or run executor.",
    ],
)
def test_comma_separated_prohibited_action_lists_remain_negated(goal: str) -> None:
    classified = WorkflowOrchestrator._classify_goal(goal)

    assert classified["selected_workflow"] == "project_status"


def test_comma_separated_prohibition_does_not_create_a_commit_preview() -> None:
    class RejectCommitManager:
        def handle(self, _action: str, _params: dict[str, object]) -> dict[str, object]:
            raise AssertionError("prohibited action list must not enter commit preview")

    result = WorkflowOrchestrator(
        "/tmp/project",
        analyze_state_fn=lambda _params: {
            "ok": True,
            "recommended_next_actions": [],
        },
        git_commit_manager=RejectCommitManager(),  # type: ignore[arg-type]
    )._workflow_auto_preview(
        {
            "goal": "Inspect current state; do not run executor, stage any changes.",
            "message": "This message must never be previewed.",
        }
    )

    assert result.selected_workflow == "project_status"
    assert result.preview_ids == []
    assert result.requires_confirmation is False


def test_positive_comma_clause_with_any_remains_routable() -> None:
    classified = WorkflowOrchestrator._classify_goal(
        "Do not run executor, update the plan with any required changes."
    )

    assert classified["selected_workflow"] == "plan"


@pytest.mark.parametrize(
    "goal",
    [
        "Update the docs, but do not modify any files during this task.",
        "Update the docs, but do not change the project throughout this workflow.",
        "Update the docs, but no writes during this session.",
    ],
)
def test_qualified_global_no_write_directive_vetoes_mutating_routes(
    goal: str,
) -> None:
    classified = WorkflowOrchestrator._classify_goal(goal)

    assert classified["selected_workflow"] == "project_status"


@pytest.mark.parametrize(
    "goal",
    [
        "检查当前状态，不要同步文档。",
        "检查当前状态，不要追加文档。",
        "检查当前状态，不要修复版本。",
        "检查当前状态，不要扩展版本。",
        "检查当前状态，不要提交任何更改。",
        "只查看状态，不要修改代码。",
        "检查当前状态，不要执行任务。",
        "检查当前状态，不要更新文档。",
    ],
)
def test_chinese_negated_routing_actions_are_not_positive_evidence(
    goal: str,
) -> None:
    classified = WorkflowOrchestrator._classify_goal(goal)

    assert classified["selected_workflow"] == "project_status"


def test_chinese_commit_prohibition_does_not_create_a_commit_preview() -> None:
    class RejectCommitManager:
        def handle(self, _action: str, _params: dict[str, object]) -> dict[str, object]:
            raise AssertionError("Chinese commit veto must not enter commit preview")

    result = WorkflowOrchestrator(
        "/tmp/project",
        analyze_state_fn=lambda _params: {
            "ok": True,
            "recommended_next_actions": [],
        },
        git_commit_manager=RejectCommitManager(),  # type: ignore[arg-type]
    )._workflow_auto_preview(
        {
            "goal": "检查当前状态，不要提交任何更改。",
            "message": "此消息不得进入预览。",
        }
    )

    assert result.selected_workflow == "project_status"
    assert result.preview_ids == []
    assert result.requires_confirmation is False


@pytest.mark.parametrize(
    ("goal", "expected_workflow"),
    [
        ("Update the docs to explain when there are no writes.", "docs"),
        (
            "Edit code handling a state where there are no mutations.",
            "small_project_patch",
        ),
    ],
)
def test_no_write_subject_matter_is_not_a_global_veto(
    goal: str,
    expected_workflow: str,
) -> None:
    classified = WorkflowOrchestrator._classify_goal(goal)

    assert classified["selected_workflow"] == expected_workflow


@pytest.mark.parametrize(
    "goal",
    [
        "Inspect current state; no writes.",
        "Inspect current state, no mutations.",
        "Update the docs, but no writes during this task.",
        "Update the docs; no mutations throughout this workflow.",
    ],
)
def test_no_write_directive_clauses_remain_global_vetoes(goal: str) -> None:
    classified = WorkflowOrchestrator._classify_goal(goal)

    assert classified["selected_workflow"] == "project_status"


@pytest.mark.parametrize(
    "goal",
    [
        "Inspect current state; must not commit.",
        "Inspect current state; cannot commit.",
        "Inspect current state; can't commit.",
        "Inspect current state; cant stage changes.",
    ],
)
def test_modal_negative_routing_directives_are_not_positive_evidence(
    goal: str,
) -> None:
    classified = WorkflowOrchestrator._classify_goal(goal)

    assert classified["selected_workflow"] == "project_status"


def test_modal_commit_prohibition_does_not_create_a_commit_preview() -> None:
    class RejectCommitManager:
        def handle(self, _action: str, _params: dict[str, object]) -> dict[str, object]:
            raise AssertionError("modal commit veto must not enter commit preview")

    result = WorkflowOrchestrator(
        "/tmp/project",
        analyze_state_fn=lambda _params: {
            "ok": True,
            "recommended_next_actions": [],
        },
        git_commit_manager=RejectCommitManager(),  # type: ignore[arg-type]
    )._workflow_auto_preview(
        {
            "goal": "Inspect current state; must not commit.",
            "message": "This message must never be previewed.",
        }
    )

    assert result.selected_workflow == "project_status"
    assert result.preview_ids == []
    assert result.requires_confirmation is False


@pytest.mark.parametrize(
    "goal",
    [
        "更新文档，但不要修改任何文件。",
        "更新文档；不得更改项目。",
        "更新文档，不过不可写入代码。",
        "更新文档，但不要做任何更改。",
    ],
)
def test_chinese_global_no_write_directive_vetoes_mutating_routes(
    goal: str,
) -> None:
    classified = WorkflowOrchestrator._classify_goal(goal)

    assert classified["selected_workflow"] == "project_status"


def test_chinese_global_no_write_directive_does_not_create_a_docs_preview() -> None:
    class RejectDocsManager:
        def handle(self, _action: str, _params: dict[str, object]) -> dict[str, object]:
            raise AssertionError("Chinese no-write intent must not enter docs preview")

    result = WorkflowOrchestrator(
        "/tmp/project",
        analyze_state_fn=lambda _params: {
            "ok": True,
            "recommended_next_actions": [],
        },
        project_docs_manager=RejectDocsManager(),  # type: ignore[arg-type]
    )._workflow_auto_preview(
        {
            "goal": "更新文档，但不要修改任何文件。",
            "file": "docs/operations.md",
            "heading": "操作",
            "new_content": "不得进入预览。",
        }
    )

    assert result.selected_workflow == "project_status"
    assert result.preview_ids == []
    assert result.requires_confirmation is False


def test_chinese_no_write_subject_matter_is_not_a_global_veto() -> None:
    classified = WorkflowOrchestrator._classify_goal(
        "更新文档，说明不要修改任何文件的场景。"
    )

    assert classified["selected_workflow"] == "docs"


@pytest.mark.parametrize(
    "goal",
    [
        "Inspect status; don't make a commit.",
        "Inspect status; do not make the commit.",
        "Inspect status; must not make a commit.",
        "Inspect status; cannot make a commit.",
    ],
)
def test_auxiliary_commit_prohibitions_are_not_positive_evidence(goal: str) -> None:
    classified = WorkflowOrchestrator._classify_goal(goal)

    assert classified["selected_workflow"] == "project_status"


def test_auxiliary_commit_prohibition_does_not_create_a_commit_preview() -> None:
    class RejectCommitManager:
        def handle(self, _action: str, _params: dict[str, object]) -> dict[str, object]:
            raise AssertionError("auxiliary commit veto must not enter commit preview")

    result = WorkflowOrchestrator(
        "/tmp/project",
        analyze_state_fn=lambda _params: {
            "ok": True,
            "recommended_next_actions": [],
        },
        git_commit_manager=RejectCommitManager(),  # type: ignore[arg-type]
    )._workflow_auto_preview(
        {
            "goal": "Inspect status; don't make a commit.",
            "message": "This message must never be previewed.",
        }
    )

    assert result.selected_workflow == "project_status"
    assert result.preview_ids == []
    assert result.requires_confirmation is False


@pytest.mark.parametrize(
    "goal",
    [
        "Update the docs, but do not write to any files.",
        "Update the docs, but must not write into the project.",
    ],
)
def test_prepositional_global_no_write_directive_vetoes_mutating_routes(
    goal: str,
) -> None:
    classified = WorkflowOrchestrator._classify_goal(goal)

    assert classified["selected_workflow"] == "project_status"


@pytest.mark.parametrize(
    "goal",
    [
        "Update the docs, but do not write to any files.",
        "Update the docs without modifying any files.",
    ],
)
def test_global_no_write_does_not_create_a_docs_preview(goal: str) -> None:
    class RejectDocsManager:
        def handle(self, _action: str, _params: dict[str, object]) -> dict[str, object]:
            raise AssertionError("prepositional no-write intent must not enter docs preview")

    result = WorkflowOrchestrator(
        "/tmp/project",
        analyze_state_fn=lambda _params: {
            "ok": True,
            "recommended_next_actions": [],
        },
        project_docs_manager=RejectDocsManager(),  # type: ignore[arg-type]
    )._workflow_auto_preview(
        {
            "goal": goal,
            "file": "docs/operations.md",
            "heading": "Operations",
            "new_content": "This content must never be previewed.",
        }
    )

    assert result.selected_workflow == "project_status"
    assert result.preview_ids == []
    assert result.requires_confirmation is False


@pytest.mark.parametrize(
    ("goal", "expected_workflow"),
    [
        (
            "Update the docs to explain why dry runs do not write any files.",
            "docs",
        ),
        (
            "Edit code handling workflows that do not mutate the project.",
            "small_project_patch",
        ),
    ],
)
def test_embedded_write_predicates_are_not_global_directives(
    goal: str,
    expected_workflow: str,
) -> None:
    classified = WorkflowOrchestrator._classify_goal(goal)

    assert classified["selected_workflow"] == expected_workflow


@pytest.mark.parametrize(
    "goal",
    [
        "Update the docs without modifying any files.",
        "Update the docs without changing the project.",
        "Update the docs without making any changes.",
    ],
)
def test_without_global_write_directive_vetoes_mutating_routes(goal: str) -> None:
    classified = WorkflowOrchestrator._classify_goal(goal)

    assert classified["selected_workflow"] == "project_status"


def test_without_write_subject_matter_is_not_a_global_veto() -> None:
    classified = WorkflowOrchestrator._classify_goal(
        "Update the docs to explain how dry runs work without modifying any files."
    )

    assert classified["selected_workflow"] == "docs"


def test_filtered_status_goal_does_not_enter_source_onboarding() -> None:
    class RejectOnboardingOrchestrator(WorkflowOrchestrator):
        def _workflow_source_onboarding(
            self,
            _params: dict[str, object],
        ) -> dict[str, object]:
            raise AssertionError("filtered status goal must not enter source onboarding")

    result = RejectOnboardingOrchestrator(
        "/tmp/project",
        analyze_state_fn=lambda _params: {
            "ok": True,
            "plan": {"source_only": True},
            "recommended_next_actions": [],
        },
    )._workflow_auto_preview({"goal": "Inspect state; no commit."})

    assert result.selected_workflow == "project_status"
    assert result.preview_ids == []
    assert result.requires_confirmation is False


@pytest.mark.parametrize(
    "goal",
    [
        "Update the docs. Do not modify any files.",
        "Update the docs! Must not write to the project.",
        "Update the docs? No writes during this task.",
        "Update the docs.\nDo not change the working tree.",
        "更新文档。不要修改任何文件。",
        "更新文档。\n不得更改项目。",
    ],
)
def test_sentence_delimited_no_write_directive_vetoes_mutating_routes(
    goal: str,
) -> None:
    classified = WorkflowOrchestrator._classify_goal(goal)

    assert classified["selected_workflow"] == "project_status"


def test_sentence_delimited_no_write_does_not_create_a_docs_preview() -> None:
    class RejectDocsManager:
        def handle(self, _action: str, _params: dict[str, object]) -> dict[str, object]:
            raise AssertionError("sentence-delimited veto must not enter docs preview")

    result = WorkflowOrchestrator(
        "/tmp/project",
        analyze_state_fn=lambda _params: {
            "ok": True,
            "recommended_next_actions": [],
        },
        project_docs_manager=RejectDocsManager(),  # type: ignore[arg-type]
    )._workflow_auto_preview(
        {
            "goal": "Update the docs. Do not modify any files.",
            "file": "docs/operations.md",
            "heading": "Operations",
            "new_content": "This content must never be previewed.",
        }
    )

    assert result.selected_workflow == "project_status"
    assert result.preview_ids == []
    assert result.requires_confirmation is False


def test_sentence_delimited_subject_matter_is_not_a_global_veto() -> None:
    classified = WorkflowOrchestrator._classify_goal(
        "Update the docs. Explain why dry runs do not write any files."
    )

    assert classified["selected_workflow"] == "docs"


@pytest.mark.parametrize("contrast", ["but", "however", "yet"])
@pytest.mark.parametrize(
    "goal_template",
    [
        "Do not commit {contrast} update the docs, and edit the README.",
        "Do not commit, push {contrast} update the docs, and edit the README.",
        "Do not commit, push, or merge {contrast} update the docs, and edit the README.",
    ],
)
def test_prohibited_list_stops_before_positive_contrast(
    contrast: str, goal_template: str,
) -> None:
    classified = WorkflowOrchestrator._classify_goal(
        goal_template.format(contrast=contrast)
    )

    assert classified["selected_workflow"] == "docs"


@pytest.mark.parametrize("separator", [". ", "! ", "? ", "\n", ".\n", "\r\n"])
def test_standalone_read_only_sentence_never_enters_docs_preview(
    separator: str,
) -> None:
    class RejectDocsManager:
        def handle(self, _action: str, _params: dict[str, object]) -> dict[str, object]:
            raise AssertionError("standalone read-only directive must veto docs preview")

    goal = f"Update the docs{separator}Read-only."
    assert WorkflowOrchestrator._classify_goal(goal)["selected_workflow"] == "project_status"
    result = WorkflowOrchestrator(
        "/tmp/project",
        analyze_state_fn=lambda _params: {
            "ok": True,
            "plan": {"source_only": True},
            "recommended_next_actions": [],
        },
        project_docs_manager=RejectDocsManager(),  # type: ignore[arg-type]
    )._workflow_auto_preview(
        {
            "goal": goal,
            "file": "README.md",
            "heading": "Usage",
            "new_content": "This must not be previewed.",
        }
    )

    assert result.selected_workflow == "project_status"
    assert result.preview_ids == []
    assert result.requires_confirmation is False


@pytest.mark.parametrize("separator", [". ", "\n"])
def test_read_only_subject_after_sentence_boundary_remains_routable(
    separator: str,
) -> None:
    classified = WorkflowOrchestrator._classify_goal(
        f"Update the docs{separator}Read-only mode needs a configuration example."
    )

    assert classified["selected_workflow"] == "docs"


@pytest.mark.parametrize("verb", ["edit", "patch", "update"])
@pytest.mark.parametrize(
    "prohibition",
    [
        ", but do not {verb} any files.",
        ". Must not {verb} the project during this task.",
        "\nDo not {verb} the working tree.",
    ],
)
def test_global_edit_patch_update_prohibition_blocks_docs_preview(
    verb: str, prohibition: str,
) -> None:
    class RejectDocsManager:
        def handle(self, _action: str, _params: dict[str, object]) -> dict[str, object]:
            raise AssertionError("global mutation veto must not enter docs preview")

    goal = "Update the docs" + prohibition.format(verb=verb)
    assert WorkflowOrchestrator._classify_goal(goal)["selected_workflow"] == "project_status"
    result = WorkflowOrchestrator(
        "/tmp/project",
        analyze_state_fn=lambda _params: {
            "ok": True,
            "recommended_next_actions": [
                {
                    "action": "docs_update.apply",
                    "requires_confirmation": True,
                    "risk_level": "write",
                },
            ],
        },
        project_docs_manager=RejectDocsManager(),  # type: ignore[arg-type]
    )._workflow_auto_preview(
        {
            "goal": goal,
            "file": "README.md",
            "heading": "Usage",
            "new_content": "This content must not be previewed.",
        }
    )

    assert result.selected_workflow == "project_status"
    assert result.preview_ids == []
    assert result.changed_files == []
    assert result.requires_confirmation is False
    assert result.next_actions == []


@pytest.mark.parametrize("verb", ["editing", "patching", "updating"])
def test_without_edit_patch_update_global_scope_vetoes_docs(verb: str) -> None:
    classified = WorkflowOrchestrator._classify_goal(
        f"Update the docs without {verb} any files."
    )

    assert classified["selected_workflow"] == "project_status"


@pytest.mark.parametrize("verb", ["edit", "patch", "update"])
@pytest.mark.parametrize(
    "goal_template",
    [
        "Update the docs, but do not {verb} tests.",
        "Update the docs, but do not {verb} the project configuration.",
        "Update the docs to explain why dry runs do not {verb} any files.",
    ],
)
def test_selective_edit_patch_update_prohibition_is_not_a_global_veto(
    verb: str, goal_template: str,
) -> None:
    classified = WorkflowOrchestrator._classify_goal(goal_template.format(verb=verb))

    assert classified["selected_workflow"] == "docs"


@pytest.mark.parametrize("verb", ["editing", "patching", "updating"])
def test_without_edit_patch_update_subject_matter_is_not_a_global_veto(
    verb: str,
) -> None:
    classified = WorkflowOrchestrator._classify_goal(
        f"Update the docs to explain how dry runs work without {verb} any files."
    )

    assert classified["selected_workflow"] == "docs"


@pytest.mark.parametrize(
    "goal",
    [
        "Update the docs, and do not modify any files.",
        "Update the docs and do not modify any files.",
        "Update the docs. Please do not modify any files.",
        "Update the docs, and please do not modify any files.",
        "Update the docs. Kindly do not edit any files.",
        "Please do not patch the project; update the docs.",
        "Update the docs, but do not modify any files or commit.",
        "Update the docs, but do not modify any files and commit.",
        "Update the docs, but do not modify any files nor commit.",
        "Update the docs, but do not modify any files or push or merge.",
        "Update the docs, but do not modify any files and do not commit.",
        "Update the docs, but do not modify any files and update the docs instead.",
        "Update the docs without modifying any files or committing.",
        "Update the docs without editing any files and pushing.",
        "Update the docs, and please no writes or mutations.",
        "Update the docs. Please do not write any files or commit.",
        "Update the docs to explain dry runs, and do not modify any files.",
        "Update the docs to explain dry runs. Please do not modify any files.",
        "Update docs when ready and do not modify any files.",
        "Update docs that need examples and do not modify any files.",
        "Update the docs.\nDo not modify any files\nDo not commit.",
        "Please do not write\nUpdate the docs.",
        "Update the docs, but no writes\nDo not commit.",
        "Update the docs. Inspect only.",
        "Update the docs! Inspect only.",
        "Update the docs? Inspect only.",
        "Update the docs\nInspect only.",
        "Update the docs\r\nInspect only.",
        "更新文档，并且不要修改任何文件。",
        "更新文档，并不要修改任何文件。",
        "更新文档并且不要修改任何文件。",
        "更新文档并不要修改任何文件。",
        "更新文档，并且不得更改项目。",
        "更新文档,并且不要修改任何文件。",
        "更新文档，说明预览行为，并且不要修改任何文件。",
        "更新文档说明预览行为，并且不要修改任何文件。",
        "更新文档中的说明并且不要修改任何文件。",
        "更新文档中的说明内容并且不要修改任何文件。",
        "更新文档中的解释并不要修改任何文件。",
        "更新说明文档并且不要修改任何文件。",
        "更新使用说明文档并且不要修改任何文件。",
        "更新文档介绍页并且不要修改任何文件。",
        *[
            f"更新文档{prefix}不要修改任何文件{newline}不要提交。"
            for prefix in ("，", "，并且", "并")
            for newline in ("\n", "\r\n", "\r")
        ],
    ],
)
def test_global_veto_clause_boundaries_block_preview_and_confirmation(goal: str) -> None:
    class RejectDocsManager:
        def handle(self, _action: str, _params: dict[str, object]) -> dict[str, object]:
            raise AssertionError("global veto must prevent document preview calls")

    assert WorkflowOrchestrator._classify_goal(goal)["selected_workflow"] == "project_status"
    result = WorkflowOrchestrator(
        "/tmp/project",
        analyze_state_fn=lambda _params: {
            "ok": True,
            "plan": {"source_only": True},
            "recommended_next_actions": [
                {"action": "docs_update.apply", "risk_level": "write", "requires_confirmation": True},
            ],
        },
        project_docs_manager=RejectDocsManager(),  # type: ignore[arg-type]
    )._workflow_auto_preview(
        {"goal": goal, "file": "README.md", "heading": "Usage", "new_content": "Not authorized"}
    )

    assert result.selected_workflow == "project_status"
    assert result.preview_ids == []
    assert result.changed_files == []
    assert result.next_actions == []
    assert result.requires_confirmation is False


@pytest.mark.parametrize(
    "goal",
    [
        "Update the docs to explain why dry runs inspect state and do not modify any files.",
        "Update the docs to describe workflows that inspect state and never edit any files.",
        "Update the docs to explain how dry runs inspect state and please do not modify any files.",
        "Update the docs to describe workflows that do not modify any files or commit.",
        "Update the docs to explain how dry runs work without modifying any files or committing.",
        "Do not modify tests or commit; update the docs instead.",
        "Do not modify any files under tests; update the docs instead.",
        "Update the docs, but do not modify the project configuration or commit.",
        "Update the docs, and please do not edit tests.",
        "Update the docs. Kindly do not patch README.",
        "Update the docs. Explain inspect only mode.",
        "Update the docs to describe inspect only mode.",
        "更新文档，并且不要修改项目配置。",
        "更新文档，并且不要修改任何测试文件。",
        "更新文档，说明预览检查状态并且不要修改任何文件。",
        "更新文档来解释预览检查状态并不要修改任何文件。",
        *[
            f"更新文档，并且不要修改任何测试文件{newline}不要提交。"
            for newline in ("\n", "\r\n", "\r")
        ],
    ],
)
def test_veto_clause_boundaries_preserve_selective_and_subject_matter_requests(goal: str) -> None:
    assert WorkflowOrchestrator._classify_goal(goal)["selected_workflow"] == "docs"


@pytest.mark.parametrize("verb", ["write", "mutate"])
@pytest.mark.parametrize("action", ["update", "patch"])
def test_coordinated_verbs_with_shared_selective_object_remain_routable(
    verb: str, action: str,
) -> None:
    goal = f"Do not {verb} or {action} tests; update the plan instead."
    assert WorkflowOrchestrator._classify_goal(goal)["selected_workflow"] == "plan"


@pytest.mark.parametrize("modal", ["must not", "cannot", "can't", "cant"])
@pytest.mark.parametrize(
    "goal_template",
    [
        "Inspect executor behavior for workflows that {modal} run executor.",
        "Inspect workflows that {modal} run executor.",
        "Review executor modes which {modal} launch Codex.",
        "Inspect executor behavior where a workflow {modal} run executor.",
        "Inspect executor behavior to explain why you {modal} run executor.",
        "Inspect workflows that {modal} run executor and {modal} launch Codex.",
        "Inspect workflows that {modal} run executor but {modal} launch Codex.",
        "Inspect executor modes which inspect state and {modal} run executor.",
        "Inspect workflows that inspect state and {modal} run executor.",
        "Inspect executor behavior to explain why we {modal} run executor.",
        "Inspect why executor workflows {modal} run executor.",
    ],
)
def test_executor_modal_subject_matter_preserves_inspection(
    modal: str, goal_template: str,
) -> None:
    assert WorkflowOrchestrator._classify_goal(
        goal_template.format(modal=modal)
    )["selected_workflow"] == "executor"


@pytest.mark.parametrize("modal", ["must not", "cannot", "can't", "cant"])
@pytest.mark.parametrize(
    "goal_template",
    [
        "{modal} run executor. Inspect the project state.",
        "Please {modal} run executor. Inspect the project state.",
        "You {modal} run executor; inspect the project state.",
        "Inspect executor behavior, but you {modal} run executor.",
        "Inspect executor behavior and {modal} run executor.",
        "Inspect executor behavior that needs review and you {modal} run executor.",
        "For this task, we {modal} run executor.",
        "We {modal} run executor; inspect the project state.",
        "Inspect executor when ready and {modal} run executor.",
        "Inspect that executor and {modal} run executor.",
        "Inspect the behavior of that executor and {modal} run executor.",
        "Inspect executor behavior but {modal} run executor.",
        "For this task you {modal} run executor; inspect current state.",
        "During this review we {modal} run executor.",
        "You absolutely {modal} run executor; inspect current state.",
        "Inspect executor behavior and you absolutely {modal} run executor.",
    ],
)
def test_executor_modal_directives_still_veto_preflight(
    modal: str, goal_template: str,
) -> None:
    class RejectExecutorOrchestrator(WorkflowOrchestrator):
        def _auto_preview_executor(self, _params):
            raise AssertionError("explicit modal directive must veto executor preflight")

    goal = goal_template.format(modal=modal)
    result = RejectExecutorOrchestrator(
        "/tmp/project",
        analyze_state_fn=lambda _params: {"ok": True, "recommended_next_actions": []},
    )._workflow_auto_preview({"goal": goal})

    assert result.selected_workflow == "project_status"
    assert result.preview_ids == []
    assert result.requires_confirmation is False


@pytest.mark.parametrize(
    "goal",
    [
        "Inspect workflows that cannot run executor. You must not run executor.",
        "Inspect workflows that cannot run executor, but do not run executor.",
        "Inspect workflows that cannot run executor, and you cannot run executor.",
        "Inspect workflows that cannot run executor; kindly must not launch Codex.",
        "Inspect workflows that cannot run executor\nMust not run executor.",
        "Inspect workflows that cannot run executor but we must not run executor.",
        "Inspect workflows that cannot run executor, but must not run executor.",
        "Inspect workflows that cannot run executor and you absolutely must not run executor.",
    ],
)
def test_executor_subject_matter_does_not_hide_a_later_directive(goal: str) -> None:
    classified = WorkflowOrchestrator._classify_goal(goal)
    assert classified["selected_workflow"] == "project_status"
    assert "explicitly forbids executor" in classified["reason"]


@pytest.mark.parametrize("modal", ["must not", "cannot"])
def test_executor_modal_subject_matter_runs_only_read_only_preflight(tmp_path, modal: str) -> None:
    result = MCPWorkflowRouter(
        str(tmp_path), agent_profile_id="web_gpt_commander",
    ).handle("auto_preview", {"goal": f"Inspect workflows that {modal} run executor."})

    assert result["selected_workflow"] == "executor_preflight"
    assert result["changed_files"] == []
    assert result["preview_ids"] == []
    assert result["requires_confirmation"] is False
    assert {step["risk_level"] for step in result["steps"]} == {"info"}
