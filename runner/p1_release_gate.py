"""Fail-closed, receipt-evaluated release gate for the P1 ChatGPT contract.

The gate does not accept evidence as function arguments.  It evaluates only a
persisted, preview-bound local operator receipt and keeps stable replacement as
a separate hard authorization boundary.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from runner.p1_release_evidence import (
    P1_EVIDENCE_CHECK_IDS,
    P1_RELEASE_EVIDENCE_SOURCE,
    get_p1_release_evidence_status,
)


P1_CLIENT_RELEASE_GATE_SOURCE = "p1_client_release_gate"
P1_CLIENT_RELEASE_GATE_SCHEMA_VERSION = "colameta.p1_client_release_gate.v2"

P1_CLIENT_RELEASE_GATE_BLOCKER_CODES = (
    "FULL_LOCAL_VALIDATION_EVIDENCE_REQUIRED",
    "FRESH_RUNTIME_PROVENANCE_REQUIRED",
    "FRESH_CONNECTOR_OAUTH_EVIDENCE_REQUIRED",
    "FRESH_CURRENT_FACTS_REQUIRED",
    "LIVE_CHATGPT_DEVELOPMENT_ACCEPTANCE_REQUIRED",
    "EXPLICIT_STABLE_REPLACEMENT_AUTHORIZATION_REQUIRED",
)

_CHECK_SPECS = (
    (
        "full_local_validation",
        "FULL_LOCAL_VALIDATION_EVIDENCE_REQUIRED",
        "fresh complete local validation receipt for the candidate commit",
        "A local contract rehearsal is narrower than the required full validation ladder.",
    ),
    (
        "runtime_provenance",
        "FRESH_RUNTIME_PROVENANCE_REQUIRED",
        "fresh public endpoint runtime provenance bound to the candidate commit",
        "Unverified or reload-needed runtime facts cannot prove the endpoint is serving the candidate.",
    ),
    (
        "connector_oauth",
        "FRESH_CONNECTOR_OAUTH_EVIDENCE_REQUIRED",
        "fresh sanitized connector/OAuth reachability and exact nine-tool discovery evidence",
        "A local server cannot prove the configured ChatGPT connector currently reaches this endpoint.",
    ),
    (
        "current_facts",
        "FRESH_CURRENT_FACTS_REQUIRED",
        "fresh current-facts artifact with no unresolved critical blocker",
        "Historical receipts and local observations are not interchangeable with a fresh release fact set.",
    ),
    (
        "live_chatgpt_development_acceptance",
        "LIVE_CHATGPT_DEVELOPMENT_ACCEPTANCE_REQUIRED",
        "fresh ChatGPT development-connector session covering nine-tool discovery, context mismatch, manifest pages/hash verification, and typed artifact recovery",
        "The local rehearsal verifies server contracts but cannot observe the ChatGPT host surface.",
    ),
)


def _check(
    *,
    check_id: str,
    blocker_code: str,
    required_evidence: str,
    fallback_reason: str,
    evidence_check: dict[str, Any] | None,
) -> dict[str, Any]:
    observed_status = evidence_check.get("status") if isinstance(evidence_check, dict) else None
    passed = observed_status == "passed"
    status = "passed" if passed else "stale" if observed_status == "stale" else "blocked"
    result: dict[str, Any] = {
        "check_id": check_id,
        "status": status,
        "required_evidence": required_evidence,
        "reason": (
            str(evidence_check.get("reason"))
            if isinstance(evidence_check, dict) and isinstance(evidence_check.get("reason"), str)
            else fallback_reason
        ),
        "evidence_source": P1_RELEASE_EVIDENCE_SOURCE if isinstance(evidence_check, dict) else None,
        "evidence_observed_at": evidence_check.get("observed_at") if isinstance(evidence_check, dict) else None,
    }
    if not passed:
        result["blocker_code"] = blocker_code
        if observed_status in {"stale", "invalid"}:
            result["evidence_status"] = observed_status
    return result


def _stable_authorization_check() -> dict[str, str]:
    return {
        "check_id": "stable_replacement_authorization",
        "status": "blocked",
        "blocker_code": "EXPLICIT_STABLE_REPLACEMENT_AUTHORIZATION_REQUIRED",
        "required_evidence": "a separately authorized exact stable-replacement target commit",
        "reason": "No release packet, test result, or evidence receipt authorizes a stable replacement.",
    }


def _unavailable_evidence_status() -> dict[str, Any]:
    return {
        "ok": False,
        "status": "unavailable",
        "receipt_integrity_verified": False,
        "evidence_complete": False,
        "checks": {
            check_id: {"status": "blocked", "reason": "project_root_unavailable_for_receipt_evaluation"}
            for check_id in P1_EVIDENCE_CHECK_IDS
        },
    }


def build_p1_client_release_gate(
    project_root: str | None = None,
    *,
    candidate_head: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Evaluate persisted P1 evidence without accepting caller assertions.

    A complete, fresh evidence receipt can clear the first five blockers.  The
    final stable-replacement authorization blocker intentionally remains until
    Jenn supplies a separate exact authorization through the stable promotion
    path; this function never creates that authority.
    """

    evidence_status = (
        get_p1_release_evidence_status(project_root, candidate_head=candidate_head, now=now)
        if isinstance(project_root, str) and project_root.strip()
        else _unavailable_evidence_status()
    )
    evidence_checks = evidence_status.get("checks") if isinstance(evidence_status.get("checks"), dict) else {}
    checks = [
        _check(
            check_id=check_id,
            blocker_code=blocker_code,
            required_evidence=required_evidence,
            fallback_reason=fallback_reason,
            evidence_check=evidence_checks.get(check_id) if isinstance(evidence_checks.get(check_id), dict) else None,
        )
        for check_id, blocker_code, required_evidence, fallback_reason in _CHECK_SPECS
    ]
    checks.append(_stable_authorization_check())
    blocker_codes = [
        str(check["blocker_code"])
        for check in checks
        if check.get("status") != "passed" and isinstance(check.get("blocker_code"), str)
    ]
    external_evidence_complete = all(check.get("status") == "passed" for check in checks[:-1])
    candidate_release_status = (
        "evidence_ready_pending_stable_authorization"
        if external_evidence_complete
        else "evidence_incomplete_or_stale"
    )
    return {
        "ok": True,
        "source": P1_CLIENT_RELEASE_GATE_SOURCE,
        "schema_version": P1_CLIENT_RELEASE_GATE_SCHEMA_VERSION,
        "read_only": True,
        "side_effects": False,
        "status": "blocked",
        "ready": False,
        "decision_kind": "p1_client_release_decision",
        "candidate_release_status": candidate_release_status,
        "blocker_codes": blocker_codes,
        "checks": checks,
        "evidence_receipt": {
            "source": P1_RELEASE_EVIDENCE_SOURCE,
            "status": evidence_status.get("status"),
            "candidate_head": evidence_status.get("candidate_head"),
            "receipt_integrity_verified": evidence_status.get("receipt_integrity_verified") is True,
            "operator_attested_external_observations": (
                evidence_status.get("operator_attested_external_observations") is True
            ),
            "evidence_complete": evidence_status.get("evidence_complete") is True,
            "error_code": evidence_status.get("error_code"),
        },
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
            "accepted_source_kind": "operator_confirmed_sanitized_external_chatgpt_observation",
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
            "verification_ingestion_status": "implemented_preview_bound_operator_receipt",
            "external_evidence_label": "operator_attested_not_server_observed",
        },
        "authority_boundary": {
            "does_not_accept_unverified_caller_evidence": True,
            "does_not_start_executor": True,
            "does_not_commit_or_push": True,
            "does_not_replace_stable": True,
            "does_not_change_connector_or_oauth": True,
            "does_not_create_release_or_deployment": True,
        },
        "safe_next_action": (
            {
                "action": "obtain_explicit_stable_replacement_authorization",
                "requires_external_human_or_operator_action": True,
                "does_not_authorize_stable_replacement": True,
            }
            if external_evidence_complete
            else {
                "action": "collect_or_refresh_p1_release_evidence",
                "tool": "manage_p1_release_evidence",
                "requires_external_human_or_operator_action": True,
                "does_not_authorize_stable_replacement": True,
            }
        ),
    }
