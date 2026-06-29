from __future__ import annotations

import copy
from pathlib import Path
import unittest

from runner.master_taskbook_hash_binding import (
    FAIL_CLOSED_RESULT_FAIL_CLOSED,
    FAIL_CLOSED_RESULT_PASS,
    FORBIDDEN_HASH_BINDING_RESULT_FIELDS,
    HASH_BINDING_RESULT_KNOWN_UNKNOWN,
    HASH_BINDING_RESULT_MATCH,
    HASH_BINDING_RESULT_MISMATCH,
    HASH_BINDING_RESULT_MISSING_INPUT,
    bind_master_hashes,
)
from runner.master_taskbook_reader import read_master_taskbook
from runner.master_taskbook_registry import load_master_taskbook_registry, sha256_file
from runner.master_taskbook_validator import validate_master_taskbook_required_fields


MASTER_SHA = "1" * 64
OTHER_SHA = "2" * 64


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


if __name__ == "__main__":
    unittest.main()
