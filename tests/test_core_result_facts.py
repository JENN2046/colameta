from __future__ import annotations

from runner.core_result_facts import normalize_next_actions, normalize_result_facts


def test_normalize_next_actions_preserves_single_top_level_next_action() -> None:
    next_action = {
        "action": "inspect_project",
        "tool": "analyze_project_state",
        "requires_confirmation": False,
    }

    assert normalize_next_actions({"next_action": next_action}) == [next_action]


def test_normalize_next_actions_uses_nested_single_next_action_as_fallback() -> None:
    next_action = {
        "action": "read_status",
        "tool": "run_mcp_workflow",
        "requires_confirmation": False,
    }

    assert normalize_next_actions({"result": {"next_action": next_action}}) == [
        next_action
    ]


def test_explicit_action_list_takes_precedence_over_single_next_action() -> None:
    listed = {"action": "listed", "tool": "analyze_project_state"}
    singular = {"action": "singular", "tool": "manage_git"}

    assert normalize_next_actions(
        {"next_actions": [listed], "next_action": singular}
    ) == [listed]


def test_read_only_single_next_action_does_not_create_confirmation() -> None:
    facts = normalize_result_facts(
        {
            "next_action": {
                "action": "inspect_project",
                "tool": "analyze_project_state",
                "requires_confirmation": False,
            }
        }
    )

    assert facts.requires_confirmation is False
    assert facts.confirmation is None
    assert facts.recommended_next_actions == [
        {
            "action": "inspect_project",
            "tool": "analyze_project_state",
            "requires_confirmation": False,
        }
    ]
