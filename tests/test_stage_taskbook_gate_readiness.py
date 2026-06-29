from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from runner.stage_taskbook_registry import sha256_file
from runner.stage_taskbook_gate_readiness import (
    READINESS_BLOCKED_NEEDS_REVIEW,
    READINESS_GATE_READY,
    READINESS_NOT_GATE_READY,
    StageTaskbookGateReadinessError,
    assert_gate_readiness_result_contract,
    assert_stage_taskbook_ref_consumable,
    evaluate_stage_taskbook_gate_readiness,
)

import tests.test_stage_to_master_binding as binding_fixture


class StageTaskbookGateReadinessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.binding = binding_fixture.StageToMasterBindingTests()
        self.binding.setUp()
        self.project = self.binding.project
        self.binding.write_registry()
        self.evidence_path = (
            self.project
            / "docs"
            / "taskbooks"
            / "versions"
            / "stage-02"
            / "evidence"
            / "VERSION_STAGE_02_V2_3_STAGE_TO_MASTER_BINDING_REPORT.md"
        )
        self.evidence_path.parent.mkdir(parents=True, exist_ok=True)
        self.evidence_path.write_text(
            "# Evidence Report: Stage 2 / v2.3\n\nbinding_status: bound\nvalidation_result: passed\n",
            encoding="utf-8",
        )
        self.evidence_sha = sha256_file(self.evidence_path)

    def tearDown(self) -> None:
        self.binding.tearDown()

    def result(self, **overrides: object) -> dict:
        options = {
            "registry_path": self.binding.registry_path,
            "expected_master_taskbook_ref": self.binding.expected_master_ref(),
            "expected_registry_source_ref": self.binding.expected_source_ref(),
            "evidence_package_path": self.evidence_path,
            "expected_evidence_package_sha256": self.evidence_sha,
        }
        options.update(overrides)
        registry_path = options.pop("registry_path")
        return evaluate_stage_taskbook_gate_readiness(self.project, registry_path, **options)

    def test_valid_gate_readiness_result_is_evidence_only(self) -> None:
        result = self.result()

        assert result["readiness_result"] == READINESS_GATE_READY
        assert result["blocking_reasons"] == []
        assert result["stage_taskbook_ref"]["stage_id"] == "stage_02_stage_taskbook_management"
        assert result["evidence_package_ref"]["exists"] is True
        assert result["authority_boundary"]["gate_ready_is_accepted_delivery_state"] is False
        assert result["authority_boundary"]["gate_ready_authorizes_execution"] is False
        assert result["authority_boundary"]["writes_delivery_state"] is False

    def test_real_repository_gate_readiness_passes(self) -> None:
        repo = Path(__file__).resolve().parents[1]

        result = evaluate_stage_taskbook_gate_readiness(repo)

        assert result["readiness_result"] == READINESS_GATE_READY
        assert result["stage_taskbook_ref"]["path"] == "docs/taskbooks/stages/STAGE_02_STAGE_TASKBOOK_MANAGEMENT.md"
        assert result["stage_taskbook_ref_consumption_rule"]["may_reference"] is True

    def test_gate_ready_stage_taskbook_ref_can_be_consumed(self) -> None:
        result = self.result()

        consumption = assert_stage_taskbook_ref_consumable(result, result["stage_taskbook_ref"])

        assert consumption["can_reference"] is True
        assert consumption["delivery_state_accepted"] is False
        assert consumption["execution_authorized"] is False

    def test_stage_taskbook_ref_hash_mismatch_is_not_gate_ready(self) -> None:
        provided_ref = {
            "path": "docs/taskbooks/stages/STAGE_02_STAGE_TASKBOOK_MANAGEMENT.md",
            "raw_snapshot_sha256": "0" * 64,
            "stage_id": "stage_02_stage_taskbook_management",
        }

        result = self.result(stage_taskbook_ref=provided_ref)

        assert result["readiness_result"] == READINESS_NOT_GATE_READY
        assert _blocking_codes(result) == {"stage_taskbook_ref_hash_mismatch"}

    def test_unregistered_stage_ref_is_not_gate_ready(self) -> None:
        result = self.result(stage_id="stage_99_missing")

        assert result["readiness_result"] == READINESS_NOT_GATE_READY
        assert "stage_taskbook_ref_is_unregistered" in _blocking_codes(result)
        assert "master_binding_failed_or_missing" in _blocking_codes(result)

    def test_missing_validator_result_is_not_gate_ready(self) -> None:
        record = self.binding.valid_registry()
        del record["records"]["stage_02_stage_taskbook_management"]["validator_result"]
        self.binding.write_registry(record)

        result = self.result()

        assert result["readiness_result"] == READINESS_NOT_GATE_READY
        assert "registry_record_missing_or_invalid" in _blocking_codes(result)
        assert "master_binding_failed_or_missing" in _blocking_codes(result)

    def test_failed_master_binding_is_not_gate_ready(self) -> None:
        content = self.binding.stage_taskbook_content().replace(
            "  project_final_goal_ref: master_taskbook.project_final_goal\n",
            "",
        )
        self.binding.rewrite_stage(content)

        result = self.result()

        assert result["readiness_result"] == READINESS_NOT_GATE_READY
        assert "master_binding_failed_or_missing" in _blocking_codes(result)

    def test_missing_evidence_package_without_known_unknown_is_not_gate_ready(self) -> None:
        missing = self.project / "docs" / "taskbooks" / "versions" / "stage-02" / "evidence" / "missing.md"

        result = self.result(evidence_package_path=missing)

        assert result["readiness_result"] == READINESS_NOT_GATE_READY
        assert _blocking_codes(result) == {"evidence_package_missing_without_known_unknown"}

    def test_missing_evidence_package_with_known_unknown_blocks_review(self) -> None:
        missing = self.project / "docs" / "taskbooks" / "versions" / "stage-02" / "evidence" / "missing.md"

        result = self.result(
            evidence_package_path=missing,
            evidence_package_known_unknown_reason="external packet not yet materialized",
        )

        assert result["readiness_result"] == READINESS_BLOCKED_NEEDS_REVIEW
        assert _blocking_codes(result) == {"evidence_package_known_unknown_documented"}
        assert result["known_unknowns"] == [
            {"field": "evidence_package_ref", "reason": "external packet not yet materialized"}
        ]

    def test_evidence_package_hash_mismatch_is_not_gate_ready(self) -> None:
        result = self.result(expected_evidence_package_sha256="0" * 64)

        assert result["readiness_result"] == READINESS_NOT_GATE_READY
        assert _blocking_codes(result) == {"evidence_package_hash_mismatch"}

    def test_forbidden_authority_boundary_claim_is_rejected(self) -> None:
        result = self.result()
        mutated = copy.deepcopy(result)
        mutated["authority_boundary"]["gate_ready_authorizes_execution"] = True

        with self.assertRaises(StageTaskbookGateReadinessError) as raised:
            assert_gate_readiness_result_contract(mutated)

        assert raised.exception.error_code == "FORBIDDEN_GATE_READY_AUTHORITY_CLAIM"

    def test_forbidden_top_level_result_claim_is_rejected(self) -> None:
        forbidden_claims = (
            ("delivery_state_accepted", True),
            ("review_acceptance", True),
            ("creates_review_decision", True),
            ("emits_gate_event", True),
            ("writes_delivery_state", True),
        )
        for key, value in forbidden_claims:
            with self.subTest(key=key):
                result = self.result()
                mutated = copy.deepcopy(result)
                mutated[key] = value

                with self.assertRaises(StageTaskbookGateReadinessError) as raised:
                    assert_gate_readiness_result_contract(mutated)

                assert raised.exception.error_code == "FORBIDDEN_GATE_READY_RESULT_CLAIM"

    def test_gate_ready_with_blocking_reasons_is_rejected(self) -> None:
        result = self.result()
        mutated = copy.deepcopy(result)
        mutated["blocking_reasons"] = [{"code": "fake", "message": "fake", "details": {}}]

        with self.assertRaises(StageTaskbookGateReadinessError) as raised:
            assert_gate_readiness_result_contract(mutated)

        assert raised.exception.error_code == "GATE_READY_WITH_BLOCKING_REASONS"

    def test_non_gate_ready_stage_ref_cannot_be_consumed(self) -> None:
        result = self.result(expected_evidence_package_sha256="0" * 64)

        with self.assertRaises(StageTaskbookGateReadinessError) as raised:
            assert_stage_taskbook_ref_consumable(result, result["stage_taskbook_ref"])

        assert raised.exception.error_code == "STAGE_TASKBOOK_REF_NOT_GATE_READY"

    def test_wrong_stage_ref_cannot_be_consumed(self) -> None:
        result = self.result()
        wrong_ref = dict(result["stage_taskbook_ref"])
        wrong_ref["raw_snapshot_sha256"] = "0" * 64

        with self.assertRaises(StageTaskbookGateReadinessError) as raised:
            assert_stage_taskbook_ref_consumable(result, wrong_ref)

        assert raised.exception.error_code == "STAGE_TASKBOOK_REF_MISMATCH"

    def test_evidence_path_outside_project_is_not_gate_ready(self) -> None:
        outside_dir = tempfile.TemporaryDirectory(prefix="colameta-stage-gate-outside-")
        self.addCleanup(outside_dir.cleanup)
        outside = Path(outside_dir.name) / "evidence.md"
        outside.write_text("# outside\n", encoding="utf-8")

        result = self.result(evidence_package_path=outside)

        assert result["readiness_result"] == READINESS_NOT_GATE_READY
        assert _blocking_codes(result) == {"evidence_package_path_outside_project"}


def _blocking_codes(result: dict) -> set[str]:
    return {str(item.get("code")) for item in result.get("blocking_reasons", [])}


if __name__ == "__main__":
    unittest.main()
