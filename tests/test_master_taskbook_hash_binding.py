from __future__ import annotations

import copy
from pathlib import Path
import unittest

from runner.master_taskbook_hash_binding import (
    CANONICALIZER_VERSION,
    CANONICAL_PAYLOAD_SCHEMA_VERSION,
    FAIL_CLOSED_RESULT_FAIL_CLOSED,
    FAIL_CLOSED_RESULT_PASS,
    FORBIDDEN_HASH_BINDING_RESULT_FIELDS,
    HASH_BINDING_RESULT_KNOWN_UNKNOWN,
    HASH_BINDING_RESULT_MATCH,
    HASH_BINDING_RESULT_MISMATCH,
    HASH_BINDING_RESULT_MISSING_INPUT,
    MasterTaskbookHashBindingError,
    bind_master_hashes,
    canonicalize_master_taskbook,
    parse_master_taskbook_yaml_blocks,
)
from runner.master_taskbook_reader import read_master_taskbook
from runner.master_taskbook_registry import load_master_taskbook_registry, sha256_file
from runner.master_taskbook_validator import validate_master_taskbook_required_fields


MASTER_SHA = "1" * 64
OTHER_SHA = "2" * 64
CANDIDATE_1_RAW_SHA256 = "40c6af59e10ae488c58230e5a29d1348824101485fae86daf9fff1d3d019d528"
CANDIDATE_1_CANONICAL_PAYLOAD_SHA256 = "77da1b70bb448dcd62e54965e7a3563c3d2935e0543c9e3b85c20572e6eb0fee"
CANDIDATE_1_FREEZE_CONTENT_HASH = "387dce1306628aaef5ab7d37a5a13f44489f0212466cc42527f2e54ab5465acb"
CANDIDATE_2_RAW_SHA256 = "b162e804899b6871c9291de68e62ad6c8541d9e71852ec6100ce437afada2a3b"
CANDIDATE_2_CANONICAL_PAYLOAD_SHA256 = "34e3c3b2fef13bb9e88a05fdbdadf2f4adcc971899289fc607ad93ac820e2015"
CANDIDATE_2_FREEZE_CONTENT_HASH = "ca744af4c012c48f32720375536e0a43d4edb8e56c5f1f005f28fdef90c42190"


class MasterTaskbookHashBindingTests(unittest.TestCase):
    def registry_input(self, master_hash: str = MASTER_SHA) -> dict:
        return {
            "master_expected_sha256": master_hash,
            "record": {
                "master_raw_snapshot_sha256": master_hash,
            },
        }

    def reader_result(self, master_hash: str = MASTER_SHA) -> dict:
        return {
            "read_status": "read_ok",
            "raw_content_sha256": master_hash,
            "observed_git_head": "a" * 40,
        }

    def validator_result(self, master_hash: str = MASTER_SHA) -> dict:
        return {
            "validation_result": "passed",
            "reader_result_input": {
                "raw_content_sha256": master_hash,
                "observed_git_head": "a" * 40,
            },
        }

    def bind(self, registry_hash: str = MASTER_SHA, reader_hash: str = MASTER_SHA, validator_hash: str = MASTER_SHA):
        return bind_master_hashes(
            registry_input=self.registry_input(registry_hash),
            reader_result=self.reader_result(reader_hash),
            validator_result=self.validator_result(validator_hash),
            observed_git_head="b" * 40,
            source_version_taskbook_refs=[
                {"version": "v1.1", "sha256": "3" * 64},
                {"version": "v1.2", "sha256": "4" * 64},
                {"version": "v1.3", "sha256": "5" * 64},
            ],
        )

    def test_matching_registry_reader_and_validator_hashes_pass(self) -> None:
        result = self.bind()

        assert result["hash_binding_result"] == HASH_BINDING_RESULT_MATCH
        assert result["fail_closed_result"] == FAIL_CLOSED_RESULT_PASS
        assert result["registry_master_raw_snapshot_sha256"] == MASTER_SHA
        assert result["reader_raw_content_sha256"] == MASTER_SHA
        assert result["validator_input_raw_content_sha256"] == MASTER_SHA
        assert result["canonical_receipt_generation"] == "deferred_not_generated"
        assert result["canonical_payload_hash_finalization"] == "deferred_not_finalized"
        assert result["binding_result_is_authority"] is False
        assert result["forbidden_authority_claims_present"] == []
        assert not (set(result) & FORBIDDEN_HASH_BINDING_RESULT_FIELDS)

    def test_hash_mismatch_fails_closed(self) -> None:
        result = self.bind(reader_hash=OTHER_SHA)

        assert result["hash_binding_result"] == HASH_BINDING_RESULT_MISMATCH
        assert result["fail_closed_result"] == FAIL_CLOSED_RESULT_FAIL_CLOSED
        assert result["failure_reason_or_none"] == "master_hash_inputs_do_not_match"
        assert not result["missing_inputs"]

    def test_missing_reader_hash_fails_closed_without_guessing(self) -> None:
        reader_result = self.reader_result()
        del reader_result["raw_content_sha256"]

        result = bind_master_hashes(
            registry_input=self.registry_input(),
            reader_result=reader_result,
            validator_result=self.validator_result(),
        )

        assert result["hash_binding_result"] == HASH_BINDING_RESULT_MISSING_INPUT
        assert result["fail_closed_result"] == FAIL_CLOSED_RESULT_FAIL_CLOSED
        assert result["missing_inputs"] == ["reader_raw_content_sha256"]
        assert result["reader_raw_content_sha256"] is None

    def test_invalid_hash_is_missing_input_and_fails_closed(self) -> None:
        result = self.bind(validator_hash="not-a-sha")

        assert result["hash_binding_result"] == HASH_BINDING_RESULT_MISSING_INPUT
        assert result["fail_closed_result"] == FAIL_CLOSED_RESULT_FAIL_CLOSED
        assert result["missing_inputs"] == ["validator_input_raw_content_sha256"]

    def test_known_unknown_validator_input_does_not_pass(self) -> None:
        validator_result = self.validator_result()
        validator_result["validation_result"] = "known_unknown"

        result = bind_master_hashes(
            registry_input=self.registry_input(),
            reader_result=self.reader_result(),
            validator_result=validator_result,
        )

        assert result["hash_binding_result"] == HASH_BINDING_RESULT_KNOWN_UNKNOWN
        assert result["fail_closed_result"] == FAIL_CLOSED_RESULT_FAIL_CLOSED
        assert result["known_unknown_inputs"] == ["validator_result"]

    def test_accepts_registry_record_shape(self) -> None:
        result = bind_master_hashes(
            registry_input={"record": {"master_raw_snapshot_sha256": MASTER_SHA}},
            reader_result=self.reader_result(),
            validator_result=self.validator_result(),
        )

        assert result["hash_binding_result"] == HASH_BINDING_RESULT_MATCH
        assert result["registry_master_raw_snapshot_sha256"] == MASTER_SHA

    def test_does_not_mutate_inputs(self) -> None:
        registry_input = self.registry_input()
        reader_result = self.reader_result()
        validator_result = self.validator_result()
        before = copy.deepcopy((registry_input, reader_result, validator_result))

        bind_master_hashes(
            registry_input=registry_input,
            reader_result=reader_result,
            validator_result=validator_result,
        )

        assert (registry_input, reader_result, validator_result) == before

    def test_current_master_registry_reader_validator_hashes_match_without_mutation(self) -> None:
        project = Path(__file__).resolve().parents[1]
        master = project / "PROJECT_MASTER_TASKBOOK.md"
        registry = project / ".colameta" / "taskbooks" / "master_taskbook_registry.json"
        master_before = sha256_file(master)
        registry_before = sha256_file(registry)

        registry_input = load_master_taskbook_registry(project)
        reader_result = read_master_taskbook(project, observed_git_head="0" * 40)
        validator_result = validate_master_taskbook_required_fields(reader_result)
        result = bind_master_hashes(
            registry_input=registry_input,
            reader_result=reader_result,
            validator_result=validator_result,
            observed_git_head="0" * 40,
        )

        assert result["hash_binding_result"] == HASH_BINDING_RESULT_MATCH
        assert result["fail_closed_result"] == FAIL_CLOSED_RESULT_PASS
        assert result["registry_master_raw_snapshot_sha256"] == master_before
        assert result["reader_raw_content_sha256"] == master_before
        assert result["validator_input_raw_content_sha256"] == master_before
        assert sha256_file(master) == master_before
        assert sha256_file(registry) == registry_before

    def test_historical_candidate_1_exact_hashes_remain_reproducible(self) -> None:
        project = Path(__file__).resolve().parents[1]
        candidate = project / "PROJECT_MASTER_TASKBOOK.v1.1-candidate.1.md"
        raw_bytes = candidate.read_bytes()
        raw = raw_bytes.decode("utf-8")

        first = canonicalize_master_taskbook(raw_bytes)
        second = canonicalize_master_taskbook(raw)
        crlf = canonicalize_master_taskbook(raw.replace("\n", "\r\n"))
        runtime_only = canonicalize_master_taskbook(
            raw.replace('    observed_at: "2026-06-28"', '    observed_at: "2099-01-01"', 1)
        )
        governance_change = canonicalize_master_taskbook(
            raw.replace("  version: v1.1-candidate.1", "  version: v1.1-candidate.2", 1)
        )

        assert first["canonicalization_status"] == "computed_evidence_only"
        assert first["raw_snapshot_sha256"] == sha256_file(candidate) == CANDIDATE_1_RAW_SHA256
        assert first["canonical_payload_sha256"] == CANDIDATE_1_CANONICAL_PAYLOAD_SHA256
        assert first["freeze_content_hash"] == CANDIDATE_1_FREEZE_CONTENT_HASH
        assert first["canonical_payload"]["source_document"] == "PROJECT_MASTER_TASKBOOK.v1.1-candidate.1.md"
        assert first["canonical_payload_field_count"] == 48
        assert first["yaml_library"] == "PyYAML"
        assert first["yaml_library_version"] == "6.0.3"
        assert first["canonical_json"] == second["canonical_json"]
        assert first["canonical_payload_sha256"] == second["canonical_payload_sha256"]
        assert first["freeze_content_hash"] == second["freeze_content_hash"]
        assert first["freeze_content_hash"] == crlf["freeze_content_hash"]
        assert first["raw_snapshot_sha256"] != crlf["raw_snapshot_sha256"]
        assert first["freeze_content_hash"] == runtime_only["freeze_content_hash"]
        assert first["raw_snapshot_sha256"] != runtime_only["raw_snapshot_sha256"]
        assert first["freeze_content_hash"] != governance_change["freeze_content_hash"]
        assert first["canonicalization_result_is_authority"] is False
        assert first["canonical_receipt_generated"] is False

    def test_candidate_2_exact_hashes_are_deterministic_and_non_authoritative(self) -> None:
        project = Path(__file__).resolve().parents[1]
        candidate = project / "PROJECT_MASTER_TASKBOOK.v1.1-candidate.2.md"
        raw_bytes = candidate.read_bytes()
        raw = raw_bytes.decode("utf-8")

        first = canonicalize_master_taskbook(raw_bytes)
        second = canonicalize_master_taskbook(raw)
        crlf = canonicalize_master_taskbook(raw.replace("\n", "\r\n"))
        runtime_only = canonicalize_master_taskbook(
            raw.replace('    observed_at: "2026-06-28"', '    observed_at: "2099-01-01"', 1)
        )

        assert first["raw_snapshot_sha256"] == sha256_file(candidate) == CANDIDATE_2_RAW_SHA256
        assert first["canonical_payload_sha256"] == CANDIDATE_2_CANONICAL_PAYLOAD_SHA256
        assert first["freeze_content_hash"] == CANDIDATE_2_FREEZE_CONTENT_HASH
        assert first["canonical_payload"]["source_document"] == "PROJECT_MASTER_TASKBOOK.v1.1-candidate.2.md"
        assert first["canonical_payload_field_count"] == 48
        assert first["canonical_json"] == second["canonical_json"]
        assert first["freeze_content_hash"] == second["freeze_content_hash"]
        assert first["freeze_content_hash"] == crlf["freeze_content_hash"]
        assert first["raw_snapshot_sha256"] != crlf["raw_snapshot_sha256"]
        assert first["freeze_content_hash"] == runtime_only["freeze_content_hash"]
        assert first["raw_snapshot_sha256"] != runtime_only["raw_snapshot_sha256"]
        assert first["canonicalization_result_is_authority"] is False
        assert first["canonical_receipt_generated"] is False

    def test_canonicalizer_fails_closed_on_missing_selector_and_duplicate_block_id(self) -> None:
        project = Path(__file__).resolve().parents[1]
        raw = (project / "PROJECT_MASTER_TASKBOOK.v1.1-candidate.2.md").read_text(encoding="utf-8")
        missing_selector = raw.replace(
            "    - master_taskbook.project_final_goal\n",
            "    - master_taskbook.missing_required_field\n",
            1,
        )

        with self.assertRaises(MasterTaskbookHashBindingError) as missing:
            canonicalize_master_taskbook(missing_selector)
        assert missing.exception.error_code == "CANONICAL_SELECTOR_PATH_MISSING"

        duplicate = raw + '\n```yaml id="hash-policy"\nhash_policy: {}\n```\n'
        with self.assertRaises(MasterTaskbookHashBindingError) as duplicated:
            canonicalize_master_taskbook(duplicate)
        assert duplicated.exception.error_code == "CANONICAL_YAML_BLOCK_ID_DUPLICATE"

        normalized_key_collision = raw.replace(
            "  canonical_payload_authority:\n",
            "  canonical_payload_authority:\n    collision: one\n    ' collision ': two\n",
            1,
        )
        with self.assertRaises(MasterTaskbookHashBindingError) as collision:
            canonicalize_master_taskbook(normalized_key_collision)
        assert collision.exception.error_code == "CANONICAL_MAPPING_KEY_COLLISION"

        with self.assertRaises(MasterTaskbookHashBindingError) as invalid_utf8:
            canonicalize_master_taskbook(b"\xff")
        assert invalid_utf8.exception.error_code == "CANONICAL_SOURCE_NOT_UTF8"

        parser_version_mismatch = raw.replace("      version: 6.0.3\n", "      version: 6.0.2\n", 1)
        with self.assertRaises(MasterTaskbookHashBindingError) as parser_version:
            canonicalize_master_taskbook(parser_version_mismatch)
        assert parser_version.exception.error_code == "CANONICALIZER_RUNTIME_DEPENDENCY_MISMATCH"

    def test_canonicalizer_fails_closed_on_every_declared_contract_surface(self) -> None:
        project = Path(__file__).resolve().parents[1]
        raw = (project / "PROJECT_MASTER_TASKBOOK.v1.1-candidate.2.md").read_text(encoding="utf-8")
        mutations = {
            "source_encoding": raw.replace("    source_encoding: utf-8\n", "    source_encoding: utf-16\n", 1),
            "payload_shape": raw.replace("      - field_values\n", "      - renamed_field_values\n", 1),
            "canonical_json": raw.replace("      ensure_ascii: false\n", "      ensure_ascii: true\n", 1),
            "evidence_boundary": raw.replace(
                "      generated_hashes_are_authority: false\n",
                "      generated_hashes_are_authority: true\n",
                1,
            ),
            "unexpected_contract_field": raw.replace(
                "    source_encoding: utf-8\n",
                "    source_encoding: utf-8\n    undeclared_contract_extension: true\n",
                1,
            ),
            "hash_policy_derived_view": raw.replace(
                "    canonical_json_trailing_newline: false\n",
                "    canonical_json_trailing_newline: true\n",
                1,
            ),
            "freeze_process_derived_view": raw.replace(
                "    field_values_key_rule: full_selector_string\n",
                "    field_values_key_rule: short_selector_alias\n",
                1,
            ),
        }

        for name, mutated in mutations.items():
            with self.subTest(name=name):
                with self.assertRaises(MasterTaskbookHashBindingError) as mismatch:
                    canonicalize_master_taskbook(mutated)
                assert mismatch.exception.error_code in {
                    "CANONICALIZER_CONTRACT_MISMATCH",
                    "CANONICALIZER_DERIVED_VIEW_MISMATCH",
                }

    def test_canonicalizer_requires_contract_views_to_be_hash_bound(self) -> None:
        project = Path(__file__).resolve().parents[1]
        raw = (project / "PROJECT_MASTER_TASKBOOK.v1.1-candidate.2.md").read_text(encoding="utf-8")
        unbound = raw.replace("    - hash_policy.canonicalization\n", "", 1)

        with self.assertRaises(MasterTaskbookHashBindingError) as missing_binding:
            canonicalize_master_taskbook(unbound)

        assert missing_binding.exception.error_code == "CANONICALIZER_CONTRACT_NOT_HASH_BOUND"
        assert missing_binding.exception.details["missing_selectors"] == ["hash_policy.canonicalization"]

    def test_canonicalizer_rejects_non_repo_relative_canonical_paths(self) -> None:
        project = Path(__file__).resolve().parents[1]
        raw = (project / "PROJECT_MASTER_TASKBOOK.v1.1-candidate.2.md").read_text(encoding="utf-8")
        canonical_path = "PROJECT_MASTER_TASKBOOK.v1.1-candidate.2.md"
        invalid_paths = (
            f"/tmp/{canonical_path}",
            f"C:/{canonical_path}",
            f"docs\\{canonical_path}",
            f"../{canonical_path}",
            f"./{canonical_path}",
            f"docs//{canonical_path}",
        )

        for invalid_path in invalid_paths:
            with self.subTest(invalid_path=invalid_path):
                mutated = raw.replace(
                    f"  canonical_path: {canonical_path}\n",
                    f"  canonical_path: {invalid_path}\n",
                    1,
                )
                with self.assertRaises(MasterTaskbookHashBindingError) as invalid:
                    canonicalize_master_taskbook(mutated)
                assert invalid.exception.error_code == "CANONICAL_SOURCE_PATH_NOT_REPO_RELATIVE"

    def test_candidate_p1_contract_fields_are_conditionally_required(self) -> None:
        project = Path(__file__).resolve().parents[1]
        raw = (project / "PROJECT_MASTER_TASKBOOK.v1.1-candidate.2.md").read_text(encoding="utf-8")
        blocks = parse_master_taskbook_yaml_blocks(raw)

        gate = blocks["gate-event-minimum-contract"]["gate_event_minimum_contract"]
        assert "from_state" not in gate["always_required_fields"]
        assert "to_state" not in gate["always_required_fields"]
        assert "transition_outcome" not in gate["always_required_fields"]
        assert gate["conditional_required_fields"]["transition_applied"]["required_fields"] == [
            "prior_state_version",
            "resulting_state_version",
            "from_state",
            "to_state",
            "transition_outcome",
        ]
        assert "from_state" in gate["conditional_required_fields"]["transition_rejected"]["forbidden_fields"]
        assert "transition_outcome" in gate["conditional_required_fields"]["transition_rejected"]["forbidden_fields"]
        assert "transition_outcome" in gate["conditional_required_fields"]["blocker_change"]["forbidden_fields"]
        assert "from_state" in gate["conditional_required_fields"]["correction_recorded"]["forbidden_fields"]
        event_types = set(gate["event_type_values"])
        branch_event_types = [
            event_type
            for branch in gate["conditional_required_fields"].values()
            for event_type in branch["event_types"]
        ]
        assert set(branch_event_types) == event_types
        assert len(branch_event_types) == len(set(branch_event_types))
        for branch in gate["conditional_required_fields"].values():
            assert not (set(branch["required_fields"]) & set(branch["forbidden_fields"]))
        for branch_name in (
            "transition_rejected",
            "blocker_change",
            "correction_recorded",
            "supersede_recorded",
        ):
            forbidden = set(gate["conditional_required_fields"][branch_name]["forbidden_fields"])
            assert {"from_state", "to_state", "transition_outcome"} <= forbidden

        review = blocks["review-decision-specific-fields"]["review_decision_specific_fields"]
        review_record = blocks["review-decision-record-minimum"]["review_decision_record"]
        accept_pending = review["ACCEPT"]["resulting_action_branches"]["gate_review_required"]
        accept_applied = review["ACCEPT"]["resulting_action_branches"]["state_transition_applied"]
        needs_fix_pending = review["NEEDS_FIX"]["resulting_action_branches"]["gate_review_required"]
        assert "transition_id" in accept_pending["forbidden_fields"]
        assert "resulting_gate_event_ref" in accept_pending["forbidden_fields"]
        assert "requested_transition_outcome" in accept_pending["required_fields"]
        assert "resulting_gate_event_ref" in accept_applied["required_fields"]
        assert "transition_id" in needs_fix_pending["forbidden_fields"]
        assert "resulting_action_id" in review_record["required_fields"]
        assert "no_action" not in review_record["resulting_action_values"]
        applied_transition_fields = {
            "gate_actor_id",
            "transition_id",
            "resulting_gate_event_ref",
            "from_state",
            "to_state",
            "transition_outcome",
        }
        for decision in ("ACCEPT", "NEEDS_FIX"):
            pending = review[decision]["resulting_action_branches"]["gate_review_required"]
            applied = review[decision]["resulting_action_branches"]["state_transition_applied"]
            assert applied_transition_fields <= set(pending["forbidden_fields"])
            assert applied_transition_fields <= set(applied["required_fields"])
            assert not (set(pending["required_fields"]) & set(pending["forbidden_fields"]))
            assert not (set(applied["required_fields"]) & set(applied["forbidden_fields"]))
        for decision in ("PLAN_ADJUST", "ABORT"):
            action_branches = review[decision]["resulting_action_branches"]
            assert set(action_branches) == {"commander_decision_requested"}
            commander_request = action_branches["commander_decision_requested"]
            assert commander_request["required_fields"] == ["requested_commander_decision_id"]
            assert commander_request["field_equality"] == {
                "resulting_action_id": "requested_commander_decision_id"
            }
            assert {
                *applied_transition_fields,
                "requested_from_state",
                "requested_to_state",
                "requested_transition_outcome",
            } <= set(commander_request["forbidden_fields"])
            assert not (set(commander_request["required_fields"]) & set(commander_request["forbidden_fields"]))


if __name__ == "__main__":
    unittest.main()
