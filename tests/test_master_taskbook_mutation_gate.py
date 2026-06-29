from __future__ import annotations

import copy
from pathlib import Path
import unittest

from runner.master_taskbook_mutation_gate import (
    FAIL_CLOSED_RESULT_FAIL_CLOSED,
    FAIL_CLOSED_RESULT_PASS,
    FORBIDDEN_MUTATION_GATE_RESULT_FIELDS,
    GATE_RESULT_ALLOW_READ_ONLY,
    GATE_RESULT_BLOCK_UNAUTHORIZED_MUTATION,
    GATE_RESULT_KNOWN_UNKNOWN,
    GATE_RESULT_REQUIRE_COMMANDER_HARD_GATE,
    MUTATION_ATTEMPT_CLASS_COMMANDER_AUTHORIZED_CANDIDATE,
    MUTATION_ATTEMPT_CLASS_NO_MASTER_MUTATION,
    MUTATION_ATTEMPT_CLASS_READ_ONLY_MASTER_ACCESS,
    MUTATION_ATTEMPT_CLASS_UNAUTHORIZED_MASTER_MUTATION,
    MUTATION_ATTEMPT_CLASS_UNKNOWN_RISK,
    evaluate_master_mutation_gate,
)
from runner.master_taskbook_registry import sha256_file


SCOPE_SHA = "1" * 64


class MasterTaskbookMutationGateTests(unittest.TestCase):
    def test_unprotected_file_mutation_is_not_master_mutation(self) -> None:
        result = evaluate_master_mutation_gate(
            candidate_changes=[
                {
                    "path": "runner/master_taskbook_mutation_gate.py",
                    "action": "create",
                    "detected_from": "allowed_files",
                }
            ],
            observed_git_head="a" * 40,
        )

        assert result["mutation_attempt_class"] == MUTATION_ATTEMPT_CLASS_NO_MASTER_MUTATION
        assert result["gate_result"] == GATE_RESULT_ALLOW_READ_ONLY
        assert result["fail_closed_result"] == FAIL_CLOSED_RESULT_PASS
        assert result["blocked_attempt_or_none"] is None

    def test_read_only_master_access_is_allowed_as_evidence_only(self) -> None:
        result = evaluate_master_mutation_gate(
            candidate_changes=[
                {
                    "path": "PROJECT_MASTER_TASKBOOK.md",
                    "action": "sha256sum",
                    "detected_from": "preflight",
                }
            ],
        )

        assert result["mutation_attempt_class"] == MUTATION_ATTEMPT_CLASS_READ_ONLY_MASTER_ACCESS
        assert result["gate_result"] == GATE_RESULT_ALLOW_READ_ONLY
        assert result["fail_closed_result"] == FAIL_CLOSED_RESULT_PASS
        assert result["mutation_gate_result_is_authority"] is False
        assert result["canonical_receipt_generation"] == "deferred_not_generated"
        assert result["canonical_payload_hash_finalization"] == "deferred_not_finalized"
        assert not (set(result) & FORBIDDEN_MUTATION_GATE_RESULT_FIELDS)

    def test_master_taskbook_mutation_without_commander_gate_is_blocked(self) -> None:
        result = evaluate_master_mutation_gate(
            candidate_changes=[
                {
                    "path": "PROJECT_MASTER_TASKBOOK.md",
                    "action": "modify",
                    "detected_from": "git_diff_name_status",
                }
            ],
        )

        assert result["mutation_attempt_class"] == MUTATION_ATTEMPT_CLASS_UNAUTHORIZED_MASTER_MUTATION
        assert result["gate_result"] == GATE_RESULT_BLOCK_UNAUTHORIZED_MUTATION
        assert result["fail_closed_result"] == FAIL_CLOSED_RESULT_FAIL_CLOSED
        assert result["failure_reason_or_none"] == "protected_master_path_mutation_without_commander_hard_gate"
        assert result["blocked_attempt_or_none"] == {
            "protected_path": "PROJECT_MASTER_TASKBOOK.md",
            "attempted_action": "modify",
            "detected_from": "git_diff_name_status",
        }

    def test_chinese_master_companion_mutation_is_also_blocked(self) -> None:
        result = evaluate_master_mutation_gate(
            candidate_changes=[
                {
                    "path": "./PROJECT_MASTER_TASKBOOK.zh-CN.md",
                    "action": "delete",
                    "detected_from": "git_diff_name_status",
                }
            ],
        )

        assert result["mutation_attempt_class"] == MUTATION_ATTEMPT_CLASS_UNAUTHORIZED_MASTER_MUTATION
        assert result["gate_result"] == GATE_RESULT_BLOCK_UNAUTHORIZED_MUTATION
        assert result["blocked_attempt_or_none"]["protected_path"] == "PROJECT_MASTER_TASKBOOK.zh-CN.md"

    def test_absolute_project_path_is_normalized_and_blocked(self) -> None:
        result = evaluate_master_mutation_gate(
            candidate_changes=[
                {
                    "path": "/home/jenn/src/colameta-dev/PROJECT_MASTER_TASKBOOK.md",
                    "action": "write",
                    "detected_from": "absolute_path_check",
                }
            ],
        )

        assert result["mutation_attempt_class"] == MUTATION_ATTEMPT_CLASS_UNAUTHORIZED_MASTER_MUTATION
        assert result["gate_result"] == GATE_RESULT_BLOCK_UNAUTHORIZED_MUTATION
        assert result["blocked_attempt_or_none"]["protected_path"] == "PROJECT_MASTER_TASKBOOK.md"

    def test_traversal_style_project_path_is_normalized_and_blocked(self) -> None:
        result = evaluate_master_mutation_gate(
            candidate_changes=[
                {
                    "path": "docs/../PROJECT_MASTER_TASKBOOK.md",
                    "action": "modify",
                    "detected_from": "candidate_manifest",
                }
            ],
        )

        assert result["mutation_attempt_class"] == MUTATION_ATTEMPT_CLASS_UNAUTHORIZED_MASTER_MUTATION
        assert result["gate_result"] == GATE_RESULT_BLOCK_UNAUTHORIZED_MUTATION
        assert result["blocked_attempt_or_none"]["protected_path"] == "PROJECT_MASTER_TASKBOOK.md"

    def test_matching_commander_authorization_still_requires_hard_gate_not_acceptance(self) -> None:
        token = "AUTHORIZE_MASTER_MUTATION_FOR_EXACT_HASH_ONLY"
        result = evaluate_master_mutation_gate(
            candidate_changes=[
                {
                    "path": "PROJECT_MASTER_TASKBOOK.md",
                    "action": "modify",
                    "detected_from": "candidate_manifest",
                }
            ],
            commander_authorization={
                "authorization_status": "hash_specific_commander_hard_gate_authorized",
                "authorization_token": token,
                "authorization_scope_hash": SCOPE_SHA,
                "authorized_paths": ["PROJECT_MASTER_TASKBOOK.md"],
                "authorized_actions": ["modify"],
            },
        )

        assert result["mutation_attempt_class"] == MUTATION_ATTEMPT_CLASS_COMMANDER_AUTHORIZED_CANDIDATE
        assert result["gate_result"] == GATE_RESULT_REQUIRE_COMMANDER_HARD_GATE
        assert result["fail_closed_result"] == FAIL_CLOSED_RESULT_FAIL_CLOSED
        assert result["commander_hard_gate_requirement_check"]["authorization_scope_matches_candidate"] is True
        assert result["commander_hard_gate_requirement_check"]["gate_does_not_generate_commander_token"] is True
        assert result["commander_authorization_token_present"] is True
        assert "commander_authorization_token_or_none" not in result
        assert token not in repr(result)
        assert "accepted" not in result

    def test_source_version_ref_filters_forbidden_authority_fields(self) -> None:
        result = evaluate_master_mutation_gate(
            candidate_changes=[],
            source_version_taskbook_ref={
                "version": "v1.5",
                "sha256": "60732a6bef0d6add2382da353ad715ce88a35c0dbef33d451c1b1d128e12ed81",
                "accepted": "true",
                "canonical_payload_hash": "2" * 64,
            },
        )

        assert result["source_version_taskbook_ref"] == {
            "version": "v1.5",
            "sha256": "60732a6bef0d6add2382da353ad715ce88a35c0dbef33d451c1b1d128e12ed81",
        }

    def test_missing_candidate_changes_is_known_unknown_and_fails_closed(self) -> None:
        result = evaluate_master_mutation_gate(candidate_changes=None)

        assert result["mutation_attempt_class"] == MUTATION_ATTEMPT_CLASS_UNKNOWN_RISK
        assert result["gate_result"] == GATE_RESULT_KNOWN_UNKNOWN
        assert result["fail_closed_result"] == FAIL_CLOSED_RESULT_FAIL_CLOSED
        assert result["failure_reason_or_none"] == "candidate_changes_missing"

    def test_unclassifiable_change_is_known_unknown_and_fails_closed(self) -> None:
        result = evaluate_master_mutation_gate(
            candidate_changes=[
                {
                    "path": "PROJECT_MASTER_TASKBOOK.md",
                    "action": "touchish",
                    "detected_from": "ambiguous_tool",
                }
            ],
        )

        assert result["mutation_attempt_class"] == MUTATION_ATTEMPT_CLASS_UNKNOWN_RISK
        assert result["gate_result"] == GATE_RESULT_KNOWN_UNKNOWN
        assert result["unknown_change_inputs"][0]["attempted_action"] == "touchish"

    def test_does_not_mutate_inputs(self) -> None:
        candidate_changes = [
            {
                "path": "PROJECT_MASTER_TASKBOOK.md",
                "action": "read",
                "detected_from": "preflight",
            }
        ]
        commander_authorization = {
            "authorization_status": "hash_specific_commander_hard_gate_authorized",
            "authorization_token": "TOKEN",
            "authorization_scope_hash": SCOPE_SHA,
            "authorized_paths": ["PROJECT_MASTER_TASKBOOK.md"],
            "authorized_actions": ["modify"],
        }
        before = copy.deepcopy((candidate_changes, commander_authorization))

        evaluate_master_mutation_gate(
            candidate_changes=candidate_changes,
            commander_authorization=commander_authorization,
        )

        assert (candidate_changes, commander_authorization) == before

    def test_current_repo_master_and_hash_binding_files_are_unchanged_by_gate(self) -> None:
        project = Path(__file__).resolve().parents[1]
        master = project / "PROJECT_MASTER_TASKBOOK.md"
        hash_binding = project / "runner" / "master_taskbook_hash_binding.py"
        master_before = sha256_file(master)
        hash_binding_before = sha256_file(hash_binding)

        result = evaluate_master_mutation_gate(
            candidate_changes=[
                {
                    "path": "PROJECT_MASTER_TASKBOOK.md",
                    "action": "sha256sum",
                    "detected_from": "current_repo_smoke",
                },
                {
                    "path": "runner/master_taskbook_mutation_gate.py",
                    "action": "create",
                    "detected_from": "current_repo_smoke",
                },
            ],
            observed_git_head="0" * 40,
            source_version_taskbook_ref={
                "version": "v1.5",
                "sha256": "60732a6bef0d6add2382da353ad715ce88a35c0dbef33d451c1b1d128e12ed81",
            },
        )

        assert result["mutation_attempt_class"] == MUTATION_ATTEMPT_CLASS_READ_ONLY_MASTER_ACCESS
        assert result["gate_result"] == GATE_RESULT_ALLOW_READ_ONLY
        assert sha256_file(master) == master_before
        assert sha256_file(hash_binding) == hash_binding_before


if __name__ == "__main__":
    unittest.main()
