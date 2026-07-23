"""Fail-closed release gate for the P1 ChatGPT client contract.

The gate intentionally separates a local protocol rehearsal from a live
ChatGPT development-connector acceptance.  A caller must not be able to turn a
release decision green merely by asserting that a test, tunnel, OAuth flow, or
stable replacement happened.  Until verified evidence has a dedicated,
authenticated ingestion path, this packet remains blocked by design.
"""

from __future__ import annotations

from typing import Any


P1_CLIENT_RELEASE_GATE_SOURCE = "p1_client_release_gate"
P1_CLIENT_RELEASE_GATE_SCHEMA_VERSION = "colameta.p1_client_release_gate.v1"

P1_CLIENT_RELEASE_GATE_BLOCKER_CODES = (
    "FULL_LOCAL_VALIDATION_EVIDENCE_REQUIRED",
    "FRESH_RUNTIME_PROVENANCE_REQUIRED",
    "FRESH_CONNECTOR_OAUTH_EVIDENCE_REQUIRED",
    "FRESH_CURRENT_FACTS_REQUIRED",
    "LIVE_CHATGPT_DEVELOPMENT_ACCEPTANCE_REQUIRED",
    "EXPLICIT_STABLE_REPLACEMENT_AUTHORIZATION_REQUIRED",
)


def _required_check(
    *,
    check_id: str,
    blocker_code: str,
    required_evidence: str,
    reason: str,
) -> dict[str, str]:
    return {
        "check_id": check_id,
        "status": "blocked",
        "blocker_code": blocker_code,
        "required_evidence": required_evidence,
        "reason": reason,
    }


def build_p1_client_release_gate() -> dict[str, Any]:
    """Return the P1 release decision boundary without accepting assertions.

    This is deliberately a read-only packet rather than an evidence upload API.
    It makes the currently missing verified evidence explicit and prevents a
    local test result from silently becoming a deployment or stable-promotion
    authorization.
    """

    checks = [
        _required_check(
            check_id="full_local_validation",
            blocker_code="FULL_LOCAL_VALIDATION_EVIDENCE_REQUIRED",
            required_evidence="fresh complete local validation receipt for the candidate commit",
            reason="A local contract rehearsal is narrower than the required full validation ladder.",
        ),
        _required_check(
            check_id="runtime_provenance",
            blocker_code="FRESH_RUNTIME_PROVENANCE_REQUIRED",
            required_evidence="fresh public endpoint runtime provenance bound to the candidate commit",
            reason="Unverified or reload-needed runtime facts cannot prove the endpoint is serving the candidate.",
        ),
        _required_check(
            check_id="connector_oauth",
            blocker_code="FRESH_CONNECTOR_OAUTH_EVIDENCE_REQUIRED",
            required_evidence="fresh sanitized connector/OAuth reachability and exact nine-tool discovery evidence",
            reason="A local server cannot prove the configured ChatGPT connector currently reaches this endpoint.",
        ),
        _required_check(
            check_id="current_facts",
            blocker_code="FRESH_CURRENT_FACTS_REQUIRED",
            required_evidence="fresh current-facts artifact with no unresolved critical blocker",
            reason="Historical receipts and local observations are not interchangeable with a fresh release fact set.",
        ),
        _required_check(
            check_id="live_chatgpt_development_acceptance",
            blocker_code="LIVE_CHATGPT_DEVELOPMENT_ACCEPTANCE_REQUIRED",
            required_evidence=(
                "fresh ChatGPT development-connector session covering nine-tool discovery, "
                "context mismatch, manifest pages/hash verification, and typed artifact recovery"
            ),
            reason="The local rehearsal verifies server contracts but cannot observe the ChatGPT host surface.",
        ),
        _required_check(
            check_id="stable_replacement_authorization",
            blocker_code="EXPLICIT_STABLE_REPLACEMENT_AUTHORIZATION_REQUIRED",
            required_evidence="a separately authorized exact stable-replacement target commit",
            reason="No release packet, test result, or caller assertion authorizes a stable replacement.",
        ),
    ]
    return {
        "ok": True,
        "source": P1_CLIENT_RELEASE_GATE_SOURCE,
        "schema_version": P1_CLIENT_RELEASE_GATE_SCHEMA_VERSION,
        "read_only": True,
        "side_effects": False,
        "status": "blocked",
        "ready": False,
        "decision_kind": "p1_client_release_decision",
        "candidate_release_status": "not_evaluated",
        "blocker_codes": list(P1_CLIENT_RELEASE_GATE_BLOCKER_CODES),
        "checks": checks,
        "local_contract_rehearsal": {
            "status": "not_accepted_as_live_evidence",
            "accepted_as": "developer preflight only",
            "not_accepted_as": [
                "live_chatgpt_acceptance",
                "connector_or_oauth_evidence",
                "runtime_provenance",
                "stable_replacement_authorization",
            ],
        },
        "live_evidence_contract": {
            "accepted_source_kind": "external_chatgpt_development_session",
            "required_fields": [
                "observed_at",
                "candidate_commit",
                "exact_visible_tool_inventory",
                "context_binding_mismatch_evidence",
                "review_manifest_hash_continuity_evidence",
                "typed_result_artifact_continuity_evidence",
                "no_resources_read_dependency_evidence",
            ],
            "caller_assertions_are_sufficient": False,
            "verification_ingestion_status": "not_implemented_fail_closed",
        },
        "authority_boundary": {
            "does_not_accept_unverified_caller_evidence": True,
            "does_not_start_executor": True,
            "does_not_commit_or_push": True,
            "does_not_replace_stable": True,
            "does_not_change_connector_or_oauth": True,
            "does_not_create_release_or_deployment": True,
        },
        "safe_next_action": {
            "action": "collect_fresh_verified_release_evidence",
            "requires_external_human_or_operator_action": True,
            "does_not_authorize_stable_replacement": True,
        },
    }
