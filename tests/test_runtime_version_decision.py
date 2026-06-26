from __future__ import annotations

import unittest

from runner.runtime_version_decision import (
    FORBIDDEN_RUNTIME_VERSION_STATUS_ACTIONS,
    evaluate_runtime_version_status_decision,
)


REQUIRED_FORBIDDEN_ACTIONS = {
    "restart",
    "reload",
    "kill",
    "apply",
    "automatic_restart",
    "automatic_reload",
    "automatic_kill",
    "automatic_apply",
    "service_lifecycle_mutation",
    "state_mutation",
    "config_write",
    "git_fetch",
    "git_pull",
    "git_push",
    "git_tag",
    "git_release",
    "executor_workflow_mutation",
    "web_route_mutation",
}


class RuntimeVersionDecisionTests(unittest.TestCase):
    def test_not_needed_returns_normal_operation_without_notice_or_diagnostics(self) -> None:
        decision = evaluate_runtime_version_status_decision("not_needed")

        assert decision["decision_kind"] == "normal_operation"
        assert decision["operator_notice_required"] is False
        assert decision["diagnostics_required"] is False
        assert decision["restart_prompt_required"] is False
        assert "No restart prompt is needed" in decision["explanation"]

    def test_needed_returns_operator_handoff_notice_only(self) -> None:
        decision = evaluate_runtime_version_status_decision("needed")

        assert decision["decision_kind"] == "operator_handoff_notice"
        assert decision["operator_notice_required"] is True
        assert decision["diagnostics_required"] is False
        assert decision["automatic_action_authorized"] is False
        assert "operator handoff notice only" in decision["explanation"]
        assert "no automatic restart" in decision["explanation"]

    def test_unknown_returns_bounded_read_only_diagnostics(self) -> None:
        decision = evaluate_runtime_version_status_decision("unknown")

        assert decision["decision_kind"] == "bounded_read_only_diagnostics"
        assert decision["operator_notice_required"] is False
        assert decision["diagnostics_required"] is True
        assert decision["automatic_action_authorized"] is False
        assert "Unknown is not safe" in decision["explanation"]
        assert "does not authorize any automatic action" in decision["explanation"]

    def test_invalid_and_missing_input_fail_closed(self) -> None:
        for value in (None, "", "unexpected", True, {"restart_needed_state": "needed"}):
            with self.subTest(value=value):
                decision = evaluate_runtime_version_status_decision(value)
                assert decision["decision_kind"] == "bounded_read_only_diagnostics"
                assert decision["diagnostics_required"] is True
                assert decision["automatic_action_authorized"] is False

        missing_decision = evaluate_runtime_version_status_decision()
        assert missing_decision["decision_kind"] == "bounded_read_only_diagnostics"
        assert missing_decision["diagnostics_required"] is True

    def test_every_decision_includes_required_forbidden_actions(self) -> None:
        for state in ("not_needed", "needed", "unknown", "invalid"):
            with self.subTest(state=state):
                decision = evaluate_runtime_version_status_decision(state)
                forbidden_actions = decision.get("forbidden_actions")
                assert isinstance(forbidden_actions, list)
                assert REQUIRED_FORBIDDEN_ACTIONS <= set(forbidden_actions)

    def test_forbidden_actions_constant_includes_required_actions(self) -> None:
        assert REQUIRED_FORBIDDEN_ACTIONS <= set(FORBIDDEN_RUNTIME_VERSION_STATUS_ACTIONS)

    def test_evaluator_has_no_returned_state_side_effects(self) -> None:
        first = evaluate_runtime_version_status_decision("needed")
        first["forbidden_actions"].append("caller_mutation")

        second = evaluate_runtime_version_status_decision("needed")

        assert "caller_mutation" not in second["forbidden_actions"]
        assert "caller_mutation" not in FORBIDDEN_RUNTIME_VERSION_STATUS_ACTIONS

    def test_no_executable_restart_reload_kill_apply_callables_are_exposed(self) -> None:
        decision = evaluate_runtime_version_status_decision("needed")

        for key, value in decision.items():
            assert not callable(value), key

        for action_name in ("restart", "reload", "kill", "apply"):
            assert not callable(decision.get(action_name))


if __name__ == "__main__":
    unittest.main()
