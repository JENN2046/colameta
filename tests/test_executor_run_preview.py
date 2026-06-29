from __future__ import annotations

import copy
import unittest

from runner.execution_envelope import validate_execution_envelope
from runner.executor_run_preview import (
    PREVIEW_BLOCKED_AUTHORITY_CONFUSION,
    PREVIEW_BLOCKED_INVALID_ENVELOPE,
    PREVIEW_BLOCKED_MISSING_LOCAL_EXECUTION_AUTHORIZATION_REF,
    PREVIEW_READY,
    ExecutorRunPreviewError,
    assert_executor_run_preview_contract,
    render_executor_run_preview,
)

import tests.test_execution_envelope as envelope_fixture


class ExecutorRunPreviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = envelope_fixture.ExecutionEnvelopeTests()

    def local_execution_envelope(self) -> dict:
        envelope = self.fixture.valid_envelope("local_execution")
        envelope["local_execution_authorization_ref"] = {
            "authorization_id": "local-execution-auth-example",
            "authority_status": "hash_specific_authorized_elsewhere",
        }
        return envelope

    def test_valid_local_execution_envelope_renders_preview_without_dispatch(self) -> None:
        envelope = self.local_execution_envelope()
        validation = validate_execution_envelope(envelope)

        preview = render_executor_run_preview(envelope, validation)

        assert preview["preview_status"] == PREVIEW_READY
        assert preview["blockers"] == []
        assert preview["authority_mode"] == "local_execution"
        assert preview["required_local_execution_authorization_ref"]["authorization_id"] == "local-execution-auth-example"
        assert preview["proposed_commands"]["authorized_to_run"] is False
        assert preview["proposed_writable_paths"]["authorized_mutation"] is False
        assert preview["executor_run_authorized"] is False
        assert preview["dispatch_started"] is False
        assert preview["delivery_state_accepted"] is False

    def test_validation_only_envelope_blocks_run_preview_for_missing_local_auth(self) -> None:
        envelope = self.fixture.valid_envelope("validation_only")
        validation = validate_execution_envelope(envelope)

        preview = render_executor_run_preview(envelope, validation)

        assert preview["preview_status"] == PREVIEW_BLOCKED_MISSING_LOCAL_EXECUTION_AUTHORIZATION_REF
        assert preview["blockers"][0]["code"] == "local_execution_authorization_ref_missing"
        assert preview["executor_run_authorized"] is False

    def test_invalid_envelope_blocks_run_preview(self) -> None:
        envelope = self.fixture.valid_envelope()
        envelope["allowed_files"] = []
        validation = validate_execution_envelope(envelope)

        preview = render_executor_run_preview(envelope, validation)

        assert preview["preview_status"] == PREVIEW_BLOCKED_INVALID_ENVELOPE
        assert preview["blockers"][0]["code"] == "envelope_not_valid"

    def test_authority_confused_envelope_result_blocks_preview(self) -> None:
        envelope = self.local_execution_envelope()
        validation = validate_execution_envelope(envelope)
        validation["delivery_state_accepted"] = True

        preview = render_executor_run_preview(envelope, validation)

        assert preview["preview_status"] == PREVIEW_BLOCKED_AUTHORITY_CONFUSION
        assert preview["blockers"][0]["code"] == "envelope_result_authority_confusion"
        assert preview["dispatch_started"] is False

    def test_proposed_mutation_categories_are_candidate_only(self) -> None:
        envelope = self.local_execution_envelope()
        validation = validate_execution_envelope(envelope)

        preview = render_executor_run_preview(envelope, validation)

        assert preview["proposed_observed_mutation_categories"]["candidate_only"] is True
        assert preview["proposed_observed_mutation_categories"]["authorized_mutation"] is False
        assert preview["proposed_observed_mutation_categories"]["categories"] == ["runner_code", "tests"]

    def test_contract_rejects_executor_run_authorization(self) -> None:
        preview = render_executor_run_preview(self.local_execution_envelope(), validate_execution_envelope(self.local_execution_envelope()))
        mutated = copy.deepcopy(preview)
        mutated["executor_run_authorized"] = True

        with self.assertRaises(ExecutorRunPreviewError) as raised:
            assert_executor_run_preview_contract(mutated)

        assert raised.exception.error_code == "FORBIDDEN_RUN_PREVIEW_RESULT_CLAIM"

    def test_contract_rejects_dispatch_started(self) -> None:
        preview = render_executor_run_preview(self.local_execution_envelope(), validate_execution_envelope(self.local_execution_envelope()))
        mutated = copy.deepcopy(preview)
        mutated["dispatch_started"] = True

        with self.assertRaises(ExecutorRunPreviewError) as raised:
            assert_executor_run_preview_contract(mutated)

        assert raised.exception.error_code == "FORBIDDEN_RUN_PREVIEW_RESULT_CLAIM"

    def test_contract_rejects_delivery_state_authority_boundary(self) -> None:
        preview = render_executor_run_preview(self.local_execution_envelope(), validate_execution_envelope(self.local_execution_envelope()))
        mutated = copy.deepcopy(preview)
        mutated["authority_boundary"]["run_preview_writes_delivery_state"] = True

        with self.assertRaises(ExecutorRunPreviewError) as raised:
            assert_executor_run_preview_contract(mutated)

        assert raised.exception.error_code == "FORBIDDEN_RUN_PREVIEW_AUTHORITY_CLAIM"

    def test_ready_preview_cannot_include_blockers(self) -> None:
        preview = render_executor_run_preview(self.local_execution_envelope(), validate_execution_envelope(self.local_execution_envelope()))
        mutated = copy.deepcopy(preview)
        mutated["blockers"] = [{"code": "fake", "message": "fake", "details": {}}]

        with self.assertRaises(ExecutorRunPreviewError) as raised:
            assert_executor_run_preview_contract(mutated)

        assert raised.exception.error_code == "RUN_PREVIEW_READY_WITH_BLOCKERS"

    def test_blocked_preview_requires_blockers(self) -> None:
        envelope = self.fixture.valid_envelope("validation_only")
        validation = validate_execution_envelope(envelope)
        preview = render_executor_run_preview(envelope, validation)
        preview["blockers"] = []

        with self.assertRaises(ExecutorRunPreviewError) as raised:
            assert_executor_run_preview_contract(preview)

        assert raised.exception.error_code == "BLOCKED_RUN_PREVIEW_WITHOUT_BLOCKERS"


if __name__ == "__main__":
    unittest.main()
