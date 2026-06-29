from __future__ import annotations

import copy
import unittest

from runner.scope_evidence_pack import (
    AUTHORITY_BOUNDARY_EXPECTATIONS,
    SCOPE_PACK_FAILED_CLOSED,
    SCOPE_PACK_READY,
    ScopeEvidencePackError,
    assert_scope_evidence_pack_contract,
    build_scope_evidence_pack,
)


class ScopeEvidencePackTests(unittest.TestCase):
    def build_pack(self, **overrides: object) -> dict:
        values = {
            "scope_pack_id": "scope-pack-example",
            "version_taskbook_ref": {"version_id": "stage_04_v4_8_scope_evidence_pack_v1"},
            "execution_envelope_ref": {"envelope_id": "execution-envelope-example"},
            "allowed_files": ["runner/**", "tests/**", "docs/taskbooks/versions/stage-04/evidence/**"],
            "forbidden_files": ["PROJECT_MASTER_TASKBOOK.md", ".colameta/plan.json", "/home/jenn/tools/colameta/**"],
            "observed_touched_files": ["runner/scope_evidence_pack.py", "tests/test_scope_evidence_pack.py"],
            "observed_mutations": [{"path": "runner/scope_evidence_pack.py", "mutation_type": "created"}],
            "generated_files": ["docs/taskbooks/versions/stage-04/evidence/VERSION_STAGE_04_V4_8_SCOPE_EVIDENCE_PACK_REPORT.md"],
            "ignored_runtime_files": [],
            "known_gaps": [],
            "remaining_risks": [{"risk_id": "review_required"}],
        }
        values.update(overrides)
        return build_scope_evidence_pack(**values)

    def test_in_scope_pack_is_ready_without_acceptance(self) -> None:
        pack = self.build_pack()

        assert pack["scope_pack_status"] == SCOPE_PACK_READY
        assert pack["scope_result"] == "in_scope"
        assert pack["scope_violations"] == []
        assert pack["review_accepted"] is False
        assert pack["delivery_state_accepted"] is False

    def test_forbidden_file_touched_is_truthful_out_of_scope(self) -> None:
        pack = self.build_pack(observed_touched_files=["PROJECT_MASTER_TASKBOOK.md"])

        assert pack["scope_pack_status"] == SCOPE_PACK_READY
        assert pack["scope_result"] == "out_of_scope"
        assert pack["scope_violations"][0]["violation_type"] == "forbidden_file_touched"

    def test_outside_allowed_generated_file_is_violation(self) -> None:
        pack = self.build_pack(generated_files=["tmp/generated.txt"])

        assert pack["scope_result"] == "out_of_scope"
        assert pack["scope_violations"][0]["violation_type"] == "outside_allowed_files"

    def test_unknown_with_known_gap_is_reviewable(self) -> None:
        pack = self.build_pack(
            observed_touched_files=[],
            observed_mutations=[],
            generated_files=[],
            known_gaps=[{"gap_id": "touched_files_unknown"}],
        )

        assert pack["scope_pack_status"] == SCOPE_PACK_READY
        assert pack["scope_result"] == "unknown_needs_review"

    def test_ignored_runtime_file_does_not_create_violation(self) -> None:
        pack = self.build_pack(
            observed_touched_files=[".colameta/state.json"],
            observed_mutations=[{"path": ".colameta/state.json", "mutation_type": "runtime_touch"}],
            generated_files=[],
            ignored_runtime_files=[".colameta/state.json"],
        )

        assert pack["scope_result"] == "in_scope"
        assert pack["scope_violations"] == []

    def test_out_of_scope_summarized_as_in_scope_fails_closed(self) -> None:
        pack = self.build_pack(observed_touched_files=["PROJECT_MASTER_TASKBOOK.md"], declared_scope_result="in_scope")

        assert pack["scope_pack_status"] == SCOPE_PACK_FAILED_CLOSED
        assert "OUT_OF_SCOPE_SUMMARIZED_AS_IN_SCOPE" in {item["code"] for item in pack["failures_and_blockers"]}

    def test_unknown_summarized_as_in_scope_fails_closed(self) -> None:
        pack = self.build_pack(
            observed_touched_files=[],
            observed_mutations=[],
            generated_files=[],
            known_gaps=[{"gap_id": "touched_files_unknown"}],
            declared_scope_result="in_scope",
        )

        assert pack["scope_pack_status"] == SCOPE_PACK_FAILED_CLOSED
        assert "UNKNOWN_SUMMARIZED_AS_IN_SCOPE" in {item["code"] for item in pack["failures_and_blockers"]}

    def test_missing_allowed_files_fails_closed(self) -> None:
        pack = self.build_pack(allowed_files=[])

        assert pack["scope_pack_status"] == SCOPE_PACK_FAILED_CLOSED
        assert "ALLOWED_FILES_MISSING" in {item["code"] for item in pack["failures_and_blockers"]}

    def test_scope_pass_implies_review_acceptance_claim_fails_closed(self) -> None:
        pack = self.build_pack(extra_claims={"scope_pass_implies_review_acceptance": True})

        assert pack["scope_pack_status"] == SCOPE_PACK_FAILED_CLOSED
        assert "FORBIDDEN_SCOPE_PACK_AUTHORITY_CLAIM" in {item["code"] for item in pack["failures_and_blockers"]}

    def test_result_contract_rejects_delivery_state_accepted(self) -> None:
        pack = self.build_pack()
        mutated = copy.deepcopy(pack)
        mutated["delivery_state_accepted"] = True

        with self.assertRaises(ScopeEvidencePackError) as raised:
            assert_scope_evidence_pack_contract(mutated)

        assert raised.exception.error_code == "FORBIDDEN_SCOPE_PACK_RESULT_CLAIM"


if __name__ == "__main__":
    unittest.main()
