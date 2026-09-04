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
