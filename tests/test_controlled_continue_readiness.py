from __future__ import annotations

import copy
import unittest

from runner.controlled_continue_readiness import (
    READINESS_BLOCKED,
    READINESS_NOOP_BLOCKED,
    READINESS_READY_TO_CONTINUE,
    ControlledContinueReadinessError,
    assert_controlled_continue_readiness_contract,
    build_controlled_continue_readiness_report,
    controlled_continue_readiness_inventory,
)


class ControlledContinueReadinessTests(unittest.TestCase):
    def plan(self) -> dict:
        return {
            "project_name": "colameta-self-dev",
            "plan_version": "test-plan",
            "versions": [
                {"version": "v1.1", "name": "Current", "enabled": True},
                {"version": "v1.2", "name": "Next", "enabled": True},
            ],
        }

    def state(self) -> dict:
        return {
            "project_name": "colameta-self-dev",
            "status": "VERSION_PASSED",
            "current_version": "v1.1",
            "current_version_index": 0,
            "updated_at": "2026-07-01T00:00:00+08:00",
            "versions": [
                {"version": "v1.1", "name": "Current", "status": "PASSED"},
                {"version": "v1.2", "name": "Next", "status": "NOT_STARTED"},
            ],
        }

    def required_refs(self) -> dict:
        return {
            "review_decision_ref": {
                "review_decision_id": "rd-1",
                "normalized_review_decision_value": "ACCEPT",
            },
            "continue_gate_ref": {
                "continue_gate_id": "cg-1",
                "gate_status": "requested",
                "gate_type": "controlled_continue_gate",
                "separate_from_review_decision": True,
                "target_next_version": "v1.2",
            },
            "taskbook_hash_refs": {
                "master_taskbook_ref": {
                    "path": "PROJECT_MASTER_TASKBOOK.md",
                    "expected_sha256": "m" * 64,
                    "actual_sha256": "m" * 64,
                },
                "stage_taskbook_ref": {
                    "path": "docs/taskbooks/stages/STAGE_09_CONTROLLED_CONTINUE_AND_LONG_RUN_TRACE.md",
                    "raw_snapshot_sha256": "s" * 64,
                },
                "version_taskbook_ref": {
                    "version": "v1.2",
                    "expected_sha256": "v" * 64,
                    "actual_sha256": "v" * 64,
                },
            },
            "git_facts": {
                "current_head": "a" * 40,
                "expected_head": "a" * 40,
                "current_branch": "main",
                "git_status_short": "",
            },
        }

    def ready_context(self, **overrides: object) -> dict:
        context = {
            "plan": self.plan(),
            "state": self.state(),
            "blocking_review_comments": [],
        }
        context.update(self.required_refs())
        context.update(overrides)
        return context

    @staticmethod
    def blocker_codes(result: dict) -> set[str]:
        return {item.get("code") for item in result.get("blockers", []) if isinstance(item, dict)}

    def test_ready_report_summarizes_gates_without_side_effects(self) -> None:
        context = self.ready_context()
        before = copy.deepcopy(context)

        result = build_controlled_continue_readiness_report(context)

        assert result["readiness_result"] == READINESS_READY_TO_CONTINUE
        assert result["can_continue"] is True
        assert result["next_version_summary"]["next_version"] == "v1.2"
        assert result["plan_summary"]["plan_version_count"] == 2
        assert result["git_facts"]["head_matches_expected"] is True
        assert result["review_decision_refs"]["eligible_basis"] == "review_decision_accept"
        assert result["continue_gate_refs"]["has_separate_gate"] is True
        assert result["taskbook_hash_refs"]["version_taskbook_ref"]["matches"] is True
        assert result["proposed_state"] is None
        assert result["files_would_be_written"] == []
        assert all(value is False for value in result["forbidden_side_effects"].values())
        assert result["authority_boundary"]["state_mutated"] is False
        assert context == before

    def test_commander_decision_request_can_satisfy_decision_ref_without_authority_effect(self) -> None:
        context = self.ready_context()
        context.pop("review_decision_ref")
        context["commander_decision_request_ref"] = {
            "commander_decision_request_id": "cdr-1",
            "request_status": "commander_decision_request_available",
            "source_review_decision_value": "ACCEPT",
            "normalized_classification": "accept_review_feedback",
            "requested_commander_action": "ask_whether_to_request_delivery_state_gate_review",
        }

        result = build_controlled_continue_readiness_report(context)

        assert result["can_continue"] is True
        assert result["review_decision_refs"]["eligible_basis"] == "commander_decision_request_accept_path"
        assert result["authority_boundary"]["review_decision_created"] is False
        assert result["authority_boundary"]["gate_event_emitted"] is False

    def test_no_next_version_returns_noop_blocked(self) -> None:
        plan = {
            "project_name": "colameta-self-dev",
            "plan_version": "test-plan",
            "versions": [{"version": "v1.1", "name": "Only", "enabled": True}],
        }
        state = {
            "project_name": "colameta-self-dev",
            "status": "COMPLETED",
            "current_version": "v1.1",
            "current_version_index": 0,
            "versions": [{"version": "v1.1", "name": "Only", "status": "PASSED"}],
        }

        result = build_controlled_continue_readiness_report({"plan": plan, "state": state})

        assert result["readiness_result"] == READINESS_NOOP_BLOCKED
        assert result["can_continue"] is False
        assert result["next_version_summary"]["has_next_enabled_version"] is False
        assert "NO_NEXT_ENABLED_VERSION" in self.blocker_codes(result)
        assert result["next_action"]["action"] == "noop_no_next_version"
        assert "no next enabled version" in result["message"]

    def test_runtime_passed_value_does_not_count_as_review_accept(self) -> None:
        context = self.ready_context(
            review_decision_ref={
                "review_decision_id": "rd-runtime",
                "normalized_review_decision_value": "PASSED",
            }
        )

        result = build_controlled_continue_readiness_report(context)

        assert result["readiness_result"] == READINESS_BLOCKED
        assert result["can_continue"] is False
        assert "RUNTIME_STATE_VALUE_IS_NOT_REVIEW_DECISION" in self.blocker_codes(result)
        assert "ELIGIBLE_REVIEW_DECISION_OR_COMMANDER_REQUEST_REQUIRED" in self.blocker_codes(result)
        assert result["review_decision_refs"]["runtime_facts_only"]["runtime_PASSED_equals_review_acceptance"] is False
        assert result["non_authority_notice"]["runtime_passed_or_completed_is_not_review_decision_accept"] is True

    def test_plan_adjust_blocks_and_points_to_stage_8_preview(self) -> None:
        context = self.ready_context(
            review_decision_ref={
                "review_decision_id": "rd-plan-adjust",
                "normalized_review_decision_value": "PLAN_ADJUST",
            },
            plan_adjustment_preview_ref={
                "preview_id": "stage8-preview-1",
                "preview_status": "plan_adjustment_preview_available",
            },
        )

        result = build_controlled_continue_readiness_report(context)

        assert result["can_continue"] is False
        assert "PLAN_ADJUST_BLOCKS_CONTINUE" in self.blocker_codes(result)
        assert result["plan_adjustment_status"]["stage_8_preview_ref"]["module"] == "runner/plan_adjustment_preview.py"
        assert result["next_action"]["action"] == "open_stage_8_plan_adjustment_preview"

    def test_missing_separate_continue_gate_blocks(self) -> None:
        context = self.ready_context()
        context.pop("continue_gate_ref")

        result = build_controlled_continue_readiness_report(context)

        assert result["can_continue"] is False
        assert "CONTINUE_GATE_REF_REQUIRED" in self.blocker_codes(result)

    def test_continue_gate_requires_explicit_next_version_target(self) -> None:
        context = self.ready_context()
        context["continue_gate_ref"].pop("target_next_version")

        result = build_controlled_continue_readiness_report(context)

        assert result["can_continue"] is False
        assert result["continue_gate_refs"]["target_next_version"] is None
        assert "CONTINUE_GATE_TARGET_REQUIRED" in self.blocker_codes(result)

    def test_continue_gate_next_version_alias_does_not_satisfy_explicit_target(self) -> None:
        context = self.ready_context()
        context["continue_gate_ref"].pop("target_next_version")
        context["continue_gate_ref"]["next_version"] = "v1.2"

        result = build_controlled_continue_readiness_report(context)

        assert result["can_continue"] is False
        assert result["continue_gate_refs"]["target_next_version"] is None
        assert result["continue_gate_refs"]["target_source"] is None
        assert "CONTINUE_GATE_TARGET_REQUIRED" in self.blocker_codes(result)

    def test_git_head_mismatch_and_dirty_worktree_block_continue(self) -> None:
        context = self.ready_context()
        context["git_facts"] = {
            "current_head": "b" * 40,
            "expected_head": "a" * 40,
            "current_branch": "main",
            "git_status_short": " M runner/controlled_continue_readiness.py",
        }

        result = build_controlled_continue_readiness_report(context)

        assert result["can_continue"] is False
        assert result["git_facts"]["head_matches_expected"] is False
        assert result["git_facts"]["dirty"] is True
        assert "GIT_HEAD_MISMATCH" in self.blocker_codes(result)
        assert "GIT_WORKTREE_DIRTY" in self.blocker_codes(result)

    def test_dirty_status_short_overrides_clean_dirty_flag(self) -> None:
        context = self.ready_context()
        context["git_facts"] = {
            "current_head": "a" * 40,
            "expected_head": "a" * 40,
            "current_branch": "main",
            "git_status_short": " M runner/controlled_continue_readiness.py",
            "dirty": False,
        }

        result = build_controlled_continue_readiness_report(context)

        assert result["can_continue"] is False
        assert result["git_facts"]["dirty"] is True
        assert result["git_facts"]["dirty_from_flag"] is False
        assert result["git_facts"]["dirty_flag_conflicts_with_status_short"] is True
        assert "GIT_WORKTREE_DIRTY" in self.blocker_codes(result)

    def test_missing_git_facts_blocks_continue(self) -> None:
        context = self.ready_context()
        context.pop("git_facts")

        result = build_controlled_continue_readiness_report(context)

        assert result["can_continue"] is False
        assert "GIT_FACTS_REQUIRED" in self.blocker_codes(result)

    def test_stale_current_version_index_resolves_by_version_and_blocks(self) -> None:
        context = self.ready_context()
        context["state"]["current_version_index"] = 99

        result = build_controlled_continue_readiness_report(context)

        assert result["can_continue"] is False
        assert result["next_version_summary"]["has_next_enabled_version"] is True
        assert result["next_version_summary"]["next_version"] == "v1.2"
        assert "CURRENT_VERSION_INDEX_OUT_OF_RANGE" in self.blocker_codes(result)
        assert "NO_NEXT_ENABLED_VERSION" not in self.blocker_codes(result)

    def test_bad_current_version_index_without_version_blocks_instead_of_noop(self) -> None:
        context = self.ready_context()
        context["state"].pop("current_version")
        context["state"]["current_version_index"] = 99

        result = build_controlled_continue_readiness_report(context)

        assert result["readiness_result"] == READINESS_BLOCKED
        assert result["can_continue"] is False
        assert "CURRENT_VERSION_INDEX_OUT_OF_RANGE" in self.blocker_codes(result)
        assert "NO_NEXT_ENABLED_VERSION" not in self.blocker_codes(result)

    def test_taskbook_hash_mismatch_blocks(self) -> None:
        context = self.ready_context()
        context["taskbook_hash_refs"]["master_taskbook_ref"]["actual_sha256"] = "0" * 64

        result = build_controlled_continue_readiness_report(context)

        assert result["can_continue"] is False
        assert "MASTER_TASKBOOK_HASH_MISMATCH" in self.blocker_codes(result)

    def test_blocking_review_comments_block_continue(self) -> None:
        context = self.ready_context(
            blocking_review_comments=[
                {"id": "comment-1", "status": "open", "blocking": True},
                {"id": "comment-2", "status": "resolved", "blocking": True},
            ]
        )

        result = build_controlled_continue_readiness_report(context)

        assert result["can_continue"] is False
        assert "BLOCKING_REVIEW_COMMENTS_PRESENT" in self.blocker_codes(result)
        assert result["review_comment_summary"]["blocking_review_comment_count"] == 1

    def test_contract_rejects_forbidden_effect_claims(self) -> None:
        result = build_controlled_continue_readiness_report(self.ready_context())
        mutated = copy.deepcopy(result)
        mutated["forbidden_side_effects"]["state_mutation"] = True

        with self.assertRaises(ControlledContinueReadinessError) as raised:
            assert_controlled_continue_readiness_contract(mutated)

        assert raised.exception.error_code == "CONTROLLED_CONTINUE_FORBIDDEN_SIDE_EFFECT_OBSERVED"

    def test_inventory_lists_required_gates_and_runtime_rejection(self) -> None:
        inventory = controlled_continue_readiness_inventory()

        assert "separate continue gate" in inventory["required_continue_inputs"]
        assert "PASSED" in inventory["runtime_state_values_rejected_as_review_decisions"]
        assert "continue_next_version_service_call" in inventory["forbidden_side_effects"]


if __name__ == "__main__":
    unittest.main()
