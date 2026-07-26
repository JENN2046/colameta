from __future__ import annotations

import json

from runner.chatgpt_development_acceptance import (
    CHATGPT_DEVELOPMENT_CONTRACT_REHEARSAL_SCHEMA_VERSION,
    run_chatgpt_development_contract_rehearsal,
)
from runner.mcp_commander_public import COMMANDER_EXPOSED_TOOLS


def test_chatgpt_development_contract_rehearsal_covers_the_typed_public_paths() -> None:
    result = run_chatgpt_development_contract_rehearsal()

    assert result["ok"] is True
    assert result["schema_version"] == CHATGPT_DEVELOPMENT_CONTRACT_REHEARSAL_SCHEMA_VERSION
    assert result["acceptance_kind"] == "local_contract_rehearsal"
    assert result["live_chatgpt_session_observed"] is False
    assert result["release_eligible"] is False
    assert tuple(result["commander_tool_inventory"]["observed"]) == COMMANDER_EXPOSED_TOOLS
    assert result["context_binding_negative"] == {
        "error_code": "CONTEXT_BINDING_MISMATCH",
        "archive_written": False,
    }
    assert result["review_manifest"]["page_count"] > 1
    assert result["review_manifest"]["verify_context_binding"] == "matched"
    assert result["review_manifest"]["verify_subject_hashes"] == "matched"
    assert result["result_artifact"]["page_count"] > 1
    assert len(result["result_artifact"]["content_sha256"]) == 64
    assert result["resources_read"]["used"] is False
    assert result["fixture_checkout_clean_after_rehearsal"] is True
    assert result["p1_client_release_gate"]["status"] == "blocked"
    assert "LIVE_CHATGPT_DEVELOPMENT_ACCEPTANCE_REQUIRED" in result["p1_client_release_gate"]["blocker_codes"]


def test_chatgpt_development_contract_rehearsal_summary_is_json_serializable() -> None:
    result = run_chatgpt_development_contract_rehearsal()

    assert json.loads(json.dumps(result))["rehearsal_status"] == "passed"
