from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from runner.external_taskbook_schema import (
    EXPECTED_CLAIM_KIND,
    REQUIRED_CLAIM_FIELDS,
    SCHEMA_CHECK_FAILED_CLOSED,
    SCHEMA_CHECK_PASSED,
    ExternalTaskbookSchemaError,
    load_external_taskbook_schema,
    preview_external_taskbook_claim_shape,
    schema_contract_summary,
    validate_external_taskbook_schema_contract,
)


class ExternalTaskbookSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Path(__file__).resolve().parents[1]
        self.schema = load_external_taskbook_schema(self.repo)

    def valid_claim(self) -> dict:
        return {
            "source": {
                "system": "commander_chat",
                "source_id": "external-taskbook-example",
                "received_at": "2026-06-30T00:00:00+08:00",
            },
            "provenance": {
                "provided_by": "Commander",
                "capture_method": "pasted_text",
                "provenance_note": "Local schema example only.",
            },
            "external_taskbook_hash": "a" * 64,
            "expected_hash_authority_ref": {
                "authority_document": "commander_confirmation_prompt",
                "authority_hash": "b" * 64,
            },
            "master_taskbook_ref": {
                "path": "PROJECT_MASTER_TASKBOOK.md",
                "raw_snapshot_sha256": "1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34",
                "review_status": "freeze_candidate_confirmed_for_exact_hash",
            },
            "stage_taskbook_ref": {
                "path": "docs/taskbooks/stages/STAGE_03_EXTERNAL_TASKBOOK_IMPORT.md",
                "raw_snapshot_sha256": "c5402734ef6990687a6a03ec6b17769f598ff0319b350b6a2371144985ece7ff",
                "stage_id": "stage_03_external_taskbook_import",
            },
            "allowed_files": [
                "runner/example.py",
                "tests/test_example.py",
            ],
            "forbidden_files": [
                "PROJECT_MASTER_TASKBOOK.md",
                ".colameta/plan.json",
            ],
            "acceptance_commands": [
                "python -m unittest tests.test_example",
            ],
            "manual_acceptance": {
                "required": True,
                "reviewer": "Commander",
                "acceptance_note": "Manual review required before adoption.",
            },
            "out_of_scope": [
                "plan mutation",
                "executor dispatch",
                "delivery state accepted",
            ],
            "supports_stage_and_master_goals": {
                "supports_stage_goal": True,
                "supports_master_goal": True,
                "rationale": "External taskbook remains a bounded claim until reviewed.",
            },
        }

    def test_real_schema_contract_loads(self) -> None:
        summary = schema_contract_summary(self.repo)

        assert summary["schema_contract_status"] == "valid"
        assert summary["schema_version"] == "external_taskbook_schema.v1"
        assert summary["claim_kind"] == EXPECTED_CLAIM_KIND
        assert summary["required_fields"] == list(REQUIRED_CLAIM_FIELDS)
        assert summary["schema_result_is_authority"] is False

    def test_valid_claim_shape_passes_as_evidence_only(self) -> None:
        result = preview_external_taskbook_claim_shape(self.valid_claim(), schema=self.schema)

        assert result["schema_check_result"] == SCHEMA_CHECK_PASSED
        assert result["rejected_fields"] == []
        assert result["known_conflicts"] == []
        assert result["normalized_output_candidate"]["claim_kind"] == EXPECTED_CLAIM_KIND
        assert result["version_candidate_mapping"]["mapping_status"] == "schema_claim_shape_only_not_adopted"
        assert result["external_taskbook_is_trusted_fact"] is False
        assert result["external_taskbook_mutates_plan"] is False
        assert result["external_taskbook_authorizes_execution"] is False
        assert result["external_taskbook_expands_allowed_files"] is False
        assert result["manual_acceptance_means_delivery_state_accepted"] is False
        assert result["creates_review_decision"] is False
        assert result["emits_gate_event"] is False
        assert result["writes_delivery_state"] is False

    def test_non_object_claim_fails_closed(self) -> None:
        result = preview_external_taskbook_claim_shape("not a claim", schema=self.schema)  # type: ignore[arg-type]

        assert result["schema_check_result"] == SCHEMA_CHECK_FAILED_CLOSED
        assert result["rejection_reasons"][0]["code"] == "CLAIM_INVALID"

    def test_missing_required_field_fails_closed(self) -> None:
        claim = self.valid_claim()
        del claim["expected_hash_authority_ref"]

        result = preview_external_taskbook_claim_shape(claim, schema=self.schema)

        assert result["schema_check_result"] == SCHEMA_CHECK_FAILED_CLOSED
        assert "expected_hash_authority_ref" in result["rejected_fields"]
        assert result["rejection_reasons"][0]["code"] == "REQUIRED_FIELD_MISSING"

    def test_invalid_hash_fails_closed(self) -> None:
        claim = self.valid_claim()
        claim["external_taskbook_hash"] = "not-a-sha"

        result = preview_external_taskbook_claim_shape(claim, schema=self.schema)

        assert result["schema_check_result"] == SCHEMA_CHECK_FAILED_CLOSED
        assert "external_taskbook_hash" in result["rejected_fields"]
        assert "FIELD_TYPE_INVALID" in {item["code"] for item in result["rejection_reasons"]}

    def test_empty_allowed_files_fails_closed(self) -> None:
        claim = self.valid_claim()
        claim["allowed_files"] = []

        result = preview_external_taskbook_claim_shape(claim, schema=self.schema)

        assert result["schema_check_result"] == SCHEMA_CHECK_FAILED_CLOSED
        assert "allowed_files" in result["rejected_fields"]

    def test_expected_hash_authority_ref_must_name_authority_document(self) -> None:
        claim = self.valid_claim()
        claim["expected_hash_authority_ref"] = {"authority_hash": "b" * 64}

        result = preview_external_taskbook_claim_shape(claim, schema=self.schema)

        assert result["schema_check_result"] == SCHEMA_CHECK_FAILED_CLOSED
        assert "expected_hash_authority_ref" in result["rejected_fields"]
        assert "EXPECTED_HASH_AUTHORITY_REF_INVALID" in {item["code"] for item in result["rejection_reasons"]}

    def test_forbidden_external_authority_claim_fails_closed(self) -> None:
        claim = self.valid_claim()
        claim["external_taskbook_authorizes_execution"] = True

        result = preview_external_taskbook_claim_shape(claim, schema=self.schema)

        assert result["schema_check_result"] == SCHEMA_CHECK_FAILED_CLOSED
        assert "FORBIDDEN_AUTHORITY_CLAIM" in {item["code"] for item in result["rejection_reasons"]}
        assert result["known_conflicts"][0]["conflict_type"] == "authority_boundary"

    def test_manual_acceptance_cannot_mean_delivery_state_accepted(self) -> None:
        claim = self.valid_claim()
        claim["manual_acceptance"]["manual_acceptance_means_delivery_state_accepted"] = True

        result = preview_external_taskbook_claim_shape(claim, schema=self.schema)

        assert result["schema_check_result"] == SCHEMA_CHECK_FAILED_CLOSED
        assert "manual_acceptance_means_delivery_state_accepted" in result["rejected_fields"][0]

    def test_schema_forbidden_authority_boundary_claim_is_rejected(self) -> None:
        schema = copy.deepcopy(self.schema)
        schema["authority_boundary_expectations"]["external_taskbook_mutates_plan"] = True

        with self.assertRaises(ExternalTaskbookSchemaError) as raised:
            validate_external_taskbook_schema_contract(schema)

        assert raised.exception.error_code == "FORBIDDEN_SCHEMA_AUTHORITY_CLAIM"

    def test_schema_required_fields_must_match_contract(self) -> None:
        schema = copy.deepcopy(self.schema)
        schema["required_fields"] = schema["required_fields"][:-1]

        with self.assertRaises(ExternalTaskbookSchemaError) as raised:
            validate_external_taskbook_schema_contract(schema)

        assert raised.exception.error_code == "SCHEMA_LIST_VALUE_UNSUPPORTED"

    def test_schema_field_definitions_must_match_required_fields_order(self) -> None:
        schema = copy.deepcopy(self.schema)
        schema["field_definitions"] = list(reversed(schema["field_definitions"]))

        with self.assertRaises(ExternalTaskbookSchemaError) as raised:
            validate_external_taskbook_schema_contract(schema)

        assert raised.exception.error_code == "FIELD_DEFINITIONS_ORDER_INVALID"

    def test_schema_path_must_stay_inside_project(self) -> None:
        with tempfile.TemporaryDirectory(prefix="colameta-external-schema-outside-") as tmp:
            outside = Path(tmp) / "external_taskbook_schema.json"
            outside.write_text(json.dumps(self.schema), encoding="utf-8")

            with self.assertRaises(ExternalTaskbookSchemaError) as raised:
                load_external_taskbook_schema(self.repo, outside)

        assert raised.exception.error_code == "PATH_OUTSIDE_PROJECT"


if __name__ == "__main__":
    unittest.main()
