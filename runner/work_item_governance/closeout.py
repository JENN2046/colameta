from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import stat
import sys
import zipfile
from collections.abc import Collection
from datetime import timezone
from http import HTTPStatus
from pathlib import Path
from typing import Any

from runner.work_item_governance import bootstrap as _runtime_bootstrap
from runner.work_item_governance.activation import (
    AUTHORITATIVE_CANARY_TOOLS,
    ZERO_BUSINESS_TABLES,
    canonical_path_digest,
    listener_attestation_digest,
    request_context_binding_digest,
    validate_synthetic_fixture_semantics,
)
from runner.work_item_governance.canonical import canonical_sha256, sha256_file
from runner.work_item_governance.contracts import MAX_JSON_BYTES
from runner.work_item_governance.errors import WorkItemGovernanceError
from runner.work_item_governance.preview import parse_timestamp
from runner.work_item_governance.schema_loader import validate_governance_record
from runner.work_item_governance.source_binding import (
    _inspect_git_checkout,
    _trusted_git_for_checkout,
    verify_runtime_source_artifacts,
)
from runner.work_item_governance.toolchain_binding import measure_closeout_toolchain


REQUIRED_VERIFICATION_NAMES = (
    "schema_contract_validation",
    "focused_negative_tests",
    "concurrency_tests",
    "full_pytest",
    "ruff",
    "architecture_checks",
    "bandit_changed_scope",
    "pip_audit",
    "wheel_source_inventory",
    "runtime_isolation_smoke",
    "protected_assets_hash_check",
    "review_bundle_accessibility",
)

_SPECIAL_COMMAND_EVIDENCE = {
    "wheel_source_inventory": "evidence/commands/wheel-source-inventory-command.json",
    "runtime_isolation_smoke": "evidence/commands/runtime-isolation-smoke-command.json",
}
_PREIMPORT_LAUNCHER_RELATIVE_PATH = "scripts/work_item_r3_trusted_launcher.py"
_PREIMPORT_ENVIRONMENT_TREE_SHA256 = (
    "ac37b262291e178d8e877e1d54045161dfd6bd8e0be2e51b9b1c0324264de36c"
)
_PREIMPORT_ENVIRONMENT_ENTRY_COUNT = 2696

_SPEC_BINDING_PATHS = {
    "freeze_manifest_sha256": "docs/work-item-governance/r2-spec/FREEZE_MANIFEST.json",
    "tool_allowlist_sha256": (
        "schemas/work_item_governance/authoritative-canary-tool-allowlist.v1.json"
    ),
    "command_matrix_sha256": (
        "schemas/work_item_governance/work-item-write-command-matrix.v1.json"
    ),
    "write_path_inventory_sha256": (
        "docs/work-item-governance/r2-spec/write-path-inventory.v1.json"
    ),
    "activation_envelope_schema_sha256": (
        "schemas/work_item_governance/activation-envelope.v1.schema.json"
    ),
    "synthetic_fixture_schema_sha256": (
        "schemas/work_item_governance/synthetic-fixture-contract.v1.schema.json"
    ),
    "preflight_receipt_schema_sha256": (
        "schemas/work_item_governance/preflight-receipt.v1.schema.json"
    ),
    "lease_schema_sha256": "schemas/work_item_governance/activation-lease.v1.schema.json",
    "lease_event_schema_sha256": (
        "schemas/work_item_governance/activation-lease-event.v1.schema.json"
    ),
    "closeout_receipt_schema_sha256": (
        "schemas/work_item_governance/r2-closeout-receipt.v1.schema.json"
    ),
    "negative_test_matrix_sha256": (
        "docs/work-item-governance/r2-spec/negative-test-matrix.v1.json"
    ),
}

_CANARY_TEST_PREFIX = "tests/test_work_item_authoritative_canary.py::"
_RUNTIME_CONFORMANCE_TEST = (
    _CANARY_TEST_PREFIX
    + "test_loopback_conformance_requires_token_and_exposes_exact_surface"
)
_LEASE_CHECK_EVIDENCE_BINDINGS: dict[str, tuple[tuple[str, str], ...]] = {
    "lease_event_chain_verified": (
        ("focused_negative_tests", _CANARY_TEST_PREFIX + "test_exported_lease_event_chain_is_independently_recomputed"),
    ),
    "lease_event_semantics_verified": (
        ("focused_negative_tests", _CANARY_TEST_PREFIX + "test_transactional_lease_executes_revision_lifecycle_and_exact_replay"),
    ),
    "lease_event_state_version_sequence_verified": (
        ("focused_negative_tests", _CANARY_TEST_PREFIX + "test_exported_lease_event_chain_is_independently_recomputed"),
    ),
    "schema_valid": (
        ("focused_negative_tests", _CANARY_TEST_PREFIX + "test_schema_v5_and_frozen_runtime_policy_contracts"),
    ),
    "one_shot_pre_listener_claim_verified": (
        ("focused_negative_tests", _CANARY_TEST_PREFIX + "test_failed_single_use_envelope_claim_is_never_reusable"),
    ),
    "pre_listener_envelope_atomic_claim_verified": (
        ("focused_negative_tests", _CANARY_TEST_PREFIX + "test_failed_single_use_envelope_claim_is_never_reusable"),
    ),
    "post_bind_listener_attestation_verified": (
        ("runtime_isolation_smoke", _RUNTIME_CONFORMANCE_TEST),
    ),
    "valid_lease_principal_without_request_context_rejected": (
        ("focused_negative_tests", _CANARY_TEST_PREFIX + "test_active_lease_without_request_capability_rejects_without_mutation"),
    ),
    "request_context_exact_lease_binding_verified": (
        ("focused_negative_tests", _CANARY_TEST_PREFIX + "test_request_context_from_another_lease_freezes_before_domain_mutation"),
    ),
    "claimed_process_identity_verified": (
        ("focused_negative_tests", _CANARY_TEST_PREFIX + "test_fresh_bootstrap_preflight_runs_under_isolated_process"),
    ),
    "expected_and_claimed_process_identity_match_verified": (
        ("focused_negative_tests", _CANARY_TEST_PREFIX + "test_fresh_bootstrap_preflight_runs_under_isolated_process"),
    ),
    "failed_or_crashed_claim_not_reusable_verified": (
        ("focused_negative_tests", _CANARY_TEST_PREFIX + "test_failed_single_use_envelope_claim_is_never_reusable"),
    ),
    "synthetic_fixture_contract_verified": (
        ("focused_negative_tests", _CANARY_TEST_PREFIX + "test_synthetic_fixture_cross_field_semantics"),
    ),
    "synthetic_fixture_cross_field_semantics_verified": (
        ("focused_negative_tests", _CANARY_TEST_PREFIX + "test_synthetic_fixture_cross_field_semantics"),
    ),
    "fresh_preflight_binding_verified": (
        ("focused_negative_tests", _CANARY_TEST_PREFIX + "test_fresh_bootstrap_preflight_runs_under_isolated_process"),
    ),
    "path_containment_and_digest_recomputation_verified": (
        ("focused_negative_tests", _CANARY_TEST_PREFIX + "test_closeout_verification_requires_both_filesystem_roots"),
    ),
    "transactional_first_binding_verified": (
        ("focused_negative_tests", _CANARY_TEST_PREFIX + "test_concurrent_first_create_binds_only_one_work_item"),
    ),
    "complete_command_matrix_verified": (
        ("focused_negative_tests", _CANARY_TEST_PREFIX + "test_all_nine_denied_write_commands_fail_before_domain_mutation"),
    ),
    "nested_fact_quota_verified": (
        ("focused_negative_tests", _CANARY_TEST_PREFIX + "test_transactional_lease_executes_revision_lifecycle_and_exact_replay"),
    ),
    "actual_fact_reconciliation_verified": (
        ("focused_negative_tests", _CANARY_TEST_PREFIX + "test_transactional_lease_executes_revision_lifecycle_and_exact_replay"),
    ),
    "idempotent_replay_no_double_charge_verified": (
        ("focused_negative_tests", _CANARY_TEST_PREFIX + "test_concurrent_exact_create_replay_is_idempotent"),
    ),
    "idempotent_replay_no_lease_event_verified": (
        ("focused_negative_tests", _CANARY_TEST_PREFIX + "test_concurrent_exact_create_replay_is_idempotent"),
    ),
    "maximum_lease_events_verified": (
        ("focused_negative_tests", _CANARY_TEST_PREFIX + "test_transactional_lease_executes_revision_lifecycle_and_exact_replay"),
    ),
    "invalid_window_semantics_rejected_verified": (
        ("focused_negative_tests", _CANARY_TEST_PREFIX + "test_invalid_monotonic_deadline_freezes_authoritative_writes"),
    ),
    "monotonic_deadline_bound_verified": (
        ("focused_negative_tests", _CANARY_TEST_PREFIX + "test_invalid_monotonic_deadline_freezes_authoritative_writes"),
    ),
    "hard_expiry_without_watchdog_verified": (
        ("focused_negative_tests", _CANARY_TEST_PREFIX + "test_monotonic_deadline_expires_without_watchdog"),
    ),
    "process_restart_invalidates_lease_verified": (
        ("focused_negative_tests", _CANARY_TEST_PREFIX + "test_process_restart_cannot_reuse_active_lease"),
    ),
    "inactive_lease_removes_dispatch_authority_verified": (
        ("focused_negative_tests", _CANARY_TEST_PREFIX + "test_process_identity_mismatch_removes_attempt_dispatch_authority"),
    ),
    "background_side_effect_workers_absent_verified": (
        ("runtime_isolation_smoke", _RUNTIME_CONFORMANCE_TEST),
    ),
    "direct_python_bypass_rejected": (
        ("focused_negative_tests", _CANARY_TEST_PREFIX + "test_direct_canary_service_without_sealed_request_context_fails_closed"),
    ),
    "restore_during_window_rejected": (
        ("focused_negative_tests", _CANARY_TEST_PREFIX + "test_restore_is_not_an_authoritative_endpoint_write"),
    ),
}
_REQUIRED_FOCUSED_LEASE_TESTS = tuple(
    dict.fromkeys(
        target
        for bindings in _LEASE_CHECK_EVIDENCE_BINDINGS.values()
        for slot, target in bindings
        if slot == "focused_negative_tests"
    )
)

_EXPECTED_PYTEST_ARGUMENTS = {
    "schema_contract_validation": ["-q", "tests/test_work_item_governance_contracts.py"],
    "focused_negative_tests": [
        "-q",
        "tests/test_work_item_r3_auth.py",
        "tests/test_work_item_r3_source_binding.py",
        "tests/test_work_item_r3_write_boundary.py",
        "tests/test_work_item_r3_legacy_create_boundary.py",
        "tests/test_work_item_r3_closeout.py",
        "tests/test_work_item_r3_closeout_runner.py",
        "tests/test_work_item_r3_trusted_launcher.py",
        *_REQUIRED_FOCUSED_LEASE_TESTS,
    ],
    "concurrency_tests": [
        "-q",
        (
            "tests/test_work_item_authoritative_canary.py::"
            "test_concurrent_first_create_binds_only_one_work_item"
        ),
    ],
    "full_pytest": ["-q"],
    "architecture_checks": [
        "-q",
        "tests/test_work_item_governance_contracts.py",
        "tests/test_work_item_r3_write_boundary.py",
        "tests/test_work_item_r3_legacy_create_boundary.py",
        "-k",
        "architecture",
    ],
}

_MINIMUM_PYTEST_PASSED = {
    "schema_contract_validation": 20,
    "focused_negative_tests": 60,
    "concurrency_tests": 1,
    "full_pytest": 1100,
    "architecture_checks": 5,
    "runtime_isolation_smoke": 1,
}
_EXACT_PYTEST_PASSED = {
    "schema_contract_validation": 7,
    "focused_negative_tests": 175,
    "concurrency_tests": 1,
    "full_pytest": 1280,
    "architecture_checks": 13,
    "runtime_isolation_smoke": 1,
}

_BANDIT_CHANGED_SCOPE = (
    "runner/mcp_server.py",
    "runner/work_item_commands.py",
    "runner/work_item_canary_runtime.py",
    "runner/work_item_governance/activation.py",
    "runner/work_item_governance/architecture.py",
    "runner/work_item_governance/bootstrap.py",
    "runner/work_item_governance/closeout.py",
    "runner/work_item_governance/repository.py",
    "runner/work_item_governance/request_context.py",
    "runner/work_item_governance/service.py",
    "runner/work_item_governance/settings.py",
    "runner/work_item_governance/source_binding.py",
    "runner/work_item_governance/toolchain_binding.py",
    "runner/work_item_principal_adapter.py",
    "scripts/work_item_r3_closeout.py",
    "scripts/work_item_r3_trusted_launcher.py",
)

_REQUIRED_REVIEW_BUNDLE_FILES = (
    "evidence/candidate/colameta-0.1.2-py3-none-any.whl",
    "evidence/wheel-source-inventory.json",
    "evidence/runtime-isolation-evidence.json",
    "evidence/runtime-observations.json",
    "evidence/preflight-receipt.json",
    "evidence/claimed-activation-envelope.json",
    "evidence/synthetic-fixture.json",
    "evidence/pre-activation-backup-receipt.json",
    "evidence/ephemeral-ledger-closeout.json",
    "evidence/lease/activation-lease-snapshot.json",
    "evidence/lease/activation-lease-events.json",
    "evidence/lease/runtime-source-attestation.json",
    "evidence/runtime/revoked-token-rejected.ok",
    "evidence/commands/schema-contract-validation.json",
    "evidence/commands/focused-negative-tests.json",
    "evidence/commands/concurrency-tests.json",
    "evidence/commands/full-pytest.json",
    "evidence/commands/ruff.json",
    "evidence/commands/architecture-checks.json",
    "evidence/commands/bandit-changed-scope.json",
    "evidence/commands/pip-audit.json",
    "evidence/commands/protected-assets-hash-check.json",
    "evidence/commands/runtime-isolation-smoke-command.json",
    "evidence/commands/wheel-source-inventory-command.json",
)

# Accessibility is intentionally measured while the bundle is still being
# assembled.  The final verifier uses the larger exact set below, so a private
# pytest basetemp or an unreviewed addendum cannot be hidden behind a valid
# Manifest.  BUNDLE_MANIFEST.json attests every other member and is itself
# constrained by the exact on-disk set.
_FINAL_REVIEW_BUNDLE_FILES = (
    *_REQUIRED_REVIEW_BUNDLE_FILES,
    "evidence/commands/review-bundle-accessibility.json",
    "R3_CLOSEOUT_RECEIPT.json",
    "REVIEW.md",
    "BUNDLE_MANIFEST.json",
)

_TOKEN_SECRET_PATTERN = re.compile(rb"mvr_[A-Za-z0-9_-]{43}")
_AUTH_TOKEN_FIELD_PATTERN = re.compile(rb'"auth_token"\s*:', re.IGNORECASE)
_MAX_SANITIZED_ARCHIVE_BYTES = 64 * 1024 * 1024
_MAX_SANITIZED_NON_ARCHIVE_BYTES = 8 * 1024 * 1024
_SQLITE_MAGIC = b"SQLite format 3\x00"
_ARCHIVE_MAGICS = (
    b"PK\x03\x04",  # zip member
    b"PK\x05\x06",  # empty zip
    b"PK\x07\x08",  # spanned zip
    b"\x1f\x8b",  # gzip
    b"BZh",  # bzip2
    b"\xfd7zXZ\x00",  # xz
    b"7z\xbc\xaf'\x1c",  # 7zip
    b"Rar!\x1a\x07",  # rar
    b"!<arch>\n",  # Unix ar
)

_EXPECTED_RUNTIME_OBSERVATION_KEYS = {
    "schema_version",
    "pass",
    "bind_address",
    "port",
    "process_pid",
    "listener",
    "authentication",
    "tool_names",
    "restricted_surface",
    "lifecycle",
    "safety",
    "existing_d1_canary_modified",
    "existing_service_modified",
    "authoritative_activation_outside_ephemeral_test",
    "secret_material_included",
}
_EXPECTED_RUNTIME_AUTHENTICATION = {
    "no_token_http_status": int(HTTPStatus.UNAUTHORIZED),
    "wrong_token_http_status": int(HTTPStatus.UNAUTHORIZED),
    "correct_token_http_status": int(HTTPStatus.OK),
    "revoked_token_http_status": int(HTTPStatus.UNAUTHORIZED),
    "replacement_token_http_status": int(HTTPStatus.OK),
    "token_file_present_after": False,
}
_EXPECTED_RUNTIME_LISTENER_FLAGS = {
    "public_endpoint_created": False,
    "relay_enabled": False,
    "tunnel_enabled": False,
    "proxy_enabled": False,
}
_EXPECTED_RUNTIME_RESTRICTED_SURFACE = {
    "definition_dispatch_exact_match": True,
    "hidden_jsonrpc_call_rejected": True,
    "direct_alias_rejected": True,
    "actions_disabled": True,
    "agent_dispatch_enforced": True,
}
_EXPECTED_RUNTIME_LIFECYCLE = {
    "accepted_state_observed": True,
    "guard_failure_observed": True,
    "lease_final_status": "closed",
    "shadow_recovery_verified": True,
}
_EXPECTED_RUNTIME_SAFETY = {
    "existing_canary_restarted": False,
    "a1_snapshot_refreshed": False,
    "authoritative_activation_performed": False,
    "isolated_conformance_harness_used": True,
    "deployed_canary_activation_performed": False,
    "existing_service_modified": False,
    "stable_runtime_modified": False,
    "real_work_item_used": False,
    "push_performed": False,
    "stable_promotion_performed": False,
}

# The closeout verifier attests the exact bootstrap and activation modules that
# make up the authoritative runtime.  Importing bootstrap here is intentional:
# an offline inventory/receipt process must measure the same critical module set
# as the live composition root instead of depending on unrelated import order.
assert _runtime_bootstrap is not None


def verify_r2_closeout_receipt(
    receipt: dict[str, Any],
    *,
    evidence_root: str | Path,
    project_root: str | Path,
) -> dict[str, Any]:
    """Fail closed on semantic PASS claims that JSON Schema alone cannot prove."""

    validate_governance_record("wig_p3_canary_a1_r2_closeout_receipt.v1", receipt)
    resolved_evidence_root = Path(evidence_root).expanduser().resolve()
    resolved_project_root = Path(project_root).expanduser().resolve()
    violations: list[str] = []
    try:
        expected_git = _trusted_git_for_checkout(resolved_project_root)
        expected_git_state = _inspect_git_checkout(
            resolved_project_root,
            git=expected_git,
            pathspecs=(),
            excluded_paths=frozenset(
                {
                    "AGENTS.md",
                    "AGENTS - 副本.amd",
                    "AGENTS - 副本.md:Zone.Identifier",
                    "AGENTS.md:Zone.Identifier",
                }
            ),
        )
        expected_toolchain = measure_closeout_toolchain(resolved_project_root)
    except Exception as exc:
        violations.append(f"closeout_provenance_preflight:{getattr(exc, 'code', type(exc).__name__)}")
        expected_git = None
        expected_git_state = None
        expected_toolchain = None
    verification = receipt["verification"]
    command_preimport_attestations: list[dict[str, Any]] = []
    if tuple(item["name"] for item in verification) != REQUIRED_VERIFICATION_NAMES:
        violations.append("verification_order_or_coverage")
    for item in verification:
        started = parse_timestamp(item["started_at"], f"{item['name']}.started_at")
        ended = parse_timestamp(item["ended_at"], f"{item['name']}.ended_at")
        if started > ended:
            violations.append(f"verification_time_order:{item['name']}")
        if item["exit_code"] != 0 or item["passed"] is not True:
            violations.append(f"verification_failed:{item['name']}")
        target = (resolved_evidence_root / item["evidence_ref"]).resolve()
        try:
            target.relative_to(resolved_evidence_root)
        except ValueError:
            violations.append(f"evidence_path_escape:{item['name']}")
        if not target.is_file():
            violations.append(f"evidence_missing:{item['name']}")
        elif sha256_file(target) != item["evidence_sha256"]:
            violations.append(f"evidence_digest_mismatch:{item['name']}")
        elif item["name"] not in _SPECIAL_COMMAND_EVIDENCE:
            attestation = _verify_command_evidence(
                item,
                target,
                receipt=receipt,
                project_root=resolved_project_root,
                expected_git_binding=(
                    expected_git.public_binding() if expected_git is not None else None
                ),
                expected_git_state=expected_git_state,
                expected_toolchain=expected_toolchain,
                violations=violations,
            )
            if attestation is not None:
                command_preimport_attestations.append(attestation)
        else:
            command_path = _evidence_path(
                resolved_evidence_root,
                _SPECIAL_COMMAND_EVIDENCE[item["name"]],
                f"{item['name']}_command",
                violations,
            )
            if command_path is not None:
                attestation = _verify_command_evidence(
                    item,
                    command_path,
                    receipt=receipt,
                    project_root=resolved_project_root,
                    expected_git_binding=(
                        expected_git.public_binding() if expected_git is not None else None
                    ),
                    expected_git_state=expected_git_state,
                    expected_toolchain=expected_toolchain,
                    violations=violations,
                )
                if attestation is not None:
                    command_preimport_attestations.append(attestation)
    if (
        len(command_preimport_attestations) != len(REQUIRED_VERIFICATION_NAMES)
        or any(
            item != command_preimport_attestations[0]
            for item in command_preimport_attestations[1:]
        )
    ):
        violations.append("command_preimport_attestation_set")
    window = receipt["verification_window"]
    started = parse_timestamp(window["started_at"], "verification_window.started_at")
    ended = parse_timestamp(window["ended_at"], "verification_window.ended_at")
    generated = parse_timestamp(receipt["generated_at"], "generated_at")
    if started > ended or ended > generated.astimezone(timezone.utc):
        violations.append("closeout_time_order")
    for item in verification:
        item_started = parse_timestamp(item["started_at"], f"{item['name']}.started_at")
        item_ended = parse_timestamp(item["ended_at"], f"{item['name']}.ended_at")
        if item_started < started or item_ended > ended:
            violations.append(f"verification_outside_window:{item['name']}")
    if receipt["activation_lease"]["final_status"] not in {
        "write_frozen",
        "expired",
        "closed",
        "revoked",
    }:
        violations.append("lease_not_inactive")
    result = receipt["result"]
    if result == "PASS" and (receipt["gaps"] or receipt["blockers"]):
        violations.append("pass_with_findings")
    if result == "PASS" and receipt["activation_lease"]["final_status"] != "closed":
        violations.append("pass_requires_closed_lease")
    if result == "PASS_WITH_GAPS" and (not receipt["gaps"] or receipt["blockers"]):
        violations.append("gaps_result_finding_mismatch")
    if result == "BLOCKED" and not receipt["blockers"]:
        violations.append("blocked_result_requires_blocker")
    finding_ids: set[str] = set()
    for category in ("gaps", "blockers"):
        for finding in receipt[category]:
            finding_id = str(finding["id"])
            if finding_id in finding_ids:
                violations.append(f"finding_duplicate_id:{finding_id}")
            finding_ids.add(finding_id)
            if (
                (category == "blockers" and finding["severity"] != "blocking")
                or (category == "gaps" and finding["severity"] == "blocking")
            ):
                violations.append(f"finding_severity:{finding_id}")
            finding_path = _evidence_path(
                resolved_evidence_root,
                str(finding["evidence_ref"]),
                f"finding:{finding_id}",
                violations,
            )
            if (
                finding_path is not None
                and sha256_file(finding_path) != finding["evidence_sha256"]
            ):
                violations.append(f"finding_evidence_digest:{finding_id}")
    _verify_spec_binding(receipt, resolved_project_root, violations)
    _verify_authentication_preflight_evidence(receipt, resolved_evidence_root, violations)
    _verify_fresh_ledger_and_runtime_evidence(
        receipt,
        resolved_evidence_root,
        violations,
    )
    _verify_activation_contract_exports(receipt, resolved_evidence_root, violations)
    _verify_exported_lease_evidence(receipt, resolved_evidence_root, violations)
    _verify_exact_source_and_runtime_evidence(
        receipt,
        resolved_evidence_root,
        resolved_project_root,
        violations,
    )
    _verify_candidate_worktree_clean(receipt, resolved_project_root, violations)
    _verify_bundle_manifest(resolved_evidence_root, violations)
    _verify_sanitized_evidence_bundle(
        resolved_evidence_root,
        violations,
        allowed_relative_paths=_FINAL_REVIEW_BUNDLE_FILES,
        exact_paths=True,
    )
    _verify_protected_assets(receipt, resolved_project_root, violations)
    if violations:
        raise WorkItemGovernanceError(
            "R2_CLOSEOUT_SEMANTICS_INVALID",
            "R2 Closeout Receipt cannot support its claimed result.",
            details={"violations": sorted(set(violations))},
        )
    return {
        "schema_valid": True,
        "semantic_valid": True,
        "result": result,
        "verification_count": len(verification),
    }


def _verify_exact_source_and_runtime_evidence(
    receipt: dict[str, Any],
    evidence_root: Path,
    project_root: Path,
    violations: list[str],
) -> None:
    verification = {item["name"]: item for item in receipt["verification"]}
    wheel_item = verification.get("wheel_source_inventory")
    runtime_item = verification.get("runtime_isolation_smoke")
    if not isinstance(wheel_item, dict) or not isinstance(runtime_item, dict):
        return

    wheel_result = wheel_item.get("result")
    measured_source = None
    if not isinstance(wheel_result, dict):
        violations.append("wheel_inventory_result_shape")
    else:
        inventory_path = _evidence_path(
            evidence_root,
            str(wheel_item["evidence_ref"]),
            "wheel_inventory",
            violations,
        )
        inventory: Any = None
        if inventory_path is not None:
            try:
                inventory = _load_strict_json(inventory_path)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
                violations.append("wheel_inventory_parse")
        expected_wheel_sha256 = receipt["source_binding"]["wheel_sha256"]
        if (
            not isinstance(inventory, dict)
            or inventory.get("wheel_sha256") != expected_wheel_sha256
            or wheel_result.get("wheel_sha256") != expected_wheel_sha256
        ):
            violations.append("wheel_inventory_source_binding")
        artifact_ref = wheel_result.get("wheel_artifact_ref")
        if not isinstance(artifact_ref, str) or not artifact_ref:
            violations.append("wheel_artifact_reference_missing")
        else:
            wheel_path = _evidence_path(
                evidence_root,
                artifact_ref,
                "wheel_artifact",
                violations,
            )
            if wheel_path is not None:
                if sha256_file(wheel_path) != expected_wheel_sha256:
                    violations.append("wheel_artifact_digest")
                expected_size = wheel_result.get("wheel_artifact_size_bytes")
                if (
                    isinstance(expected_size, bool)
                    or not isinstance(expected_size, int)
                    or expected_size != wheel_path.stat().st_size
                ):
                    violations.append("wheel_artifact_size")
                try:
                    measured_source = verify_runtime_source_artifacts(
                        checkout_root=project_root,
                        wheel_artifact=wheel_path,
                        expected_source_binding={
                            "core_baseline_commit": receipt["source_binding"]["core_baseline_commit"],
                            "implementation_commit": receipt["source_binding"]["implementation_commit"],
                            "implementation_tree": receipt["source_binding"]["implementation_tree"],
                            "wheel_sha256": receipt["source_binding"]["wheel_sha256"],
                        },
                    )
                except WorkItemGovernanceError:
                    violations.append("wheel_git_runtime_source_attestation")
                else:
                    if (
                        not isinstance(inventory, dict)
                        or inventory.get("source_binding") != measured_source.source_binding
                        or inventory.get("file_manifest_digest")
                        != measured_source.file_manifest_digest
                    ):
                        violations.append("wheel_inventory_manifest_binding")

    runtime_path = _evidence_path(
        evidence_root,
        str(runtime_item["evidence_ref"]),
        "runtime_isolation",
        violations,
    )
    runtime_evidence: Any = None
    if runtime_path is not None:
        try:
            runtime_evidence = _load_strict_json(runtime_path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            violations.append("runtime_evidence_parse")
    if not isinstance(runtime_evidence, dict):
        violations.append("runtime_evidence_shape")
    else:
        expected_source = {
            "core_baseline_commit": receipt["source_binding"]["core_baseline_commit"],
            "implementation_commit": receipt["source_binding"]["implementation_commit"],
            "implementation_tree": receipt["source_binding"]["implementation_tree"],
            "wheel_sha256": receipt["source_binding"]["wheel_sha256"],
        }
        if runtime_evidence.get("source") != expected_source:
            violations.append("runtime_evidence_source_binding")
        if (
            runtime_evidence.get("pass") is not True
            or runtime_evidence.get("bind_address") != receipt["runtime_isolation"]["bind_address"]
            or runtime_evidence.get("port") != receipt["runtime_isolation"]["port"]
            or runtime_evidence.get("listed_tools") != receipt["restricted_surface"]["listed_tool_count"]
        ):
            violations.append("runtime_evidence_binding")
        if runtime_evidence.get("tool_names") != list(AUTHORITATIVE_CANARY_TOOLS):
            violations.append("runtime_tool_inventory")
        command_evidence_ref = _SPECIAL_COMMAND_EVIDENCE["runtime_isolation_smoke"]
        command_evidence_path = _evidence_path(
            evidence_root,
            command_evidence_ref,
            "runtime_command_evidence",
            violations,
        )
        if (
            command_evidence_path is None
            or runtime_evidence.get("command_evidence_ref") != command_evidence_ref
            or runtime_evidence.get("command_evidence_sha256")
            != sha256_file(command_evidence_path)
        ):
            violations.append("runtime_command_evidence_binding")
        authentication = runtime_evidence.get("authentication")
        expected_authentication = dict(
            (
                ("no_token_http_status", int(HTTPStatus.UNAUTHORIZED)),
                ("wrong_token_http_status", int(HTTPStatus.UNAUTHORIZED)),
                ("correct_token_http_status", int(HTTPStatus.OK)),
                ("revoked_token_http_status", int(HTTPStatus.UNAUTHORIZED)),
                ("token_file_present_after", bool(0)),
            )
        )
        if not isinstance(authentication, dict) or authentication != expected_authentication:
            violations.append("runtime_authentication_evidence")
        source_attestation = runtime_evidence.get("source_attestation")
        if (
            measured_source is None
            or not isinstance(source_attestation, dict)
            or source_attestation.get("verified") is not True
            or source_attestation.get("source_binding") != measured_source.source_binding
            or source_attestation.get("file_manifest_digest")
            != measured_source.file_manifest_digest
        ):
            violations.append("runtime_source_attestation")

    snapshot_path = _evidence_path(
        evidence_root,
        receipt["activation_lease"]["lease_snapshot_export_relative_path"],
        "runtime_lease_snapshot",
        violations,
    )
    if snapshot_path is not None:
        try:
            snapshot = _load_strict_json(snapshot_path)
            runtime_started = parse_timestamp(runtime_item["started_at"], "runtime.started_at")
            runtime_ended = parse_timestamp(runtime_item["ended_at"], "runtime.ended_at")
            lease_created = parse_timestamp(snapshot["created_at"], "lease.created_at")
            lease_updated = parse_timestamp(snapshot["updated_at"], "lease.updated_at")
            if lease_created < runtime_started or lease_updated > runtime_ended:
                violations.append("runtime_lease_time_causality")
            runtime_binding = snapshot["runtime_binding"]
            runtime_lease = runtime_evidence.get("lease") if isinstance(runtime_evidence, dict) else None
            if not isinstance(runtime_lease, dict) or runtime_lease != {
                "lease_id": snapshot["lease_id"],
                "claimed_process_identity": runtime_binding["claimed_process_identity"],
                "listener_attestation_digest": runtime_binding["listener_attestation_digest"],
                "authenticated_request_context_binding_digest": runtime_binding[
                    "authenticated_request_context_binding_digest"
                ],
                "final_status": snapshot["status"],
                "final_state_version": snapshot["state_version"],
            }:
                violations.append("runtime_lease_binding")
            source_export = snapshot_path.parent / "runtime-source-attestation.json"
            if not source_export.is_file():
                violations.append("runtime_source_attestation_export_missing")
            else:
                exported_source = _load_strict_json(source_export)
                if (
                    measured_source is None
                    or exported_source.get("verified") is not True
                    or exported_source.get("source_binding") != measured_source.source_binding
                    or exported_source.get("file_manifest_digest")
                    != measured_source.file_manifest_digest
                    or not isinstance(runtime_evidence, dict)
                    or runtime_evidence.get("source_attestation") != exported_source
                ):
                    violations.append("runtime_source_attestation_export_binding")
        except (KeyError, OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError, WorkItemGovernanceError):
            violations.append("runtime_lease_time_parse")


def _verify_command_evidence(
    receipt_item: dict[str, Any],
    evidence_path: Path,
    *,
    receipt: dict[str, Any],
    project_root: Path,
    expected_git_binding: dict[str, Any] | None,
    expected_git_state: dict[str, Any] | None,
    expected_toolchain: dict[str, Any] | None,
    violations: list[str],
) -> dict[str, Any] | None:
    """Bind a verification slot to the retained completed-process record.

    This does not pretend that a local JSON file is an external attestation.  It
    does prevent a PASS receipt from pointing at arbitrary prose or replacing a
    real command with ``true`` while claiming pytest, Ruff or Bandit ran.
    """

    name = str(receipt_item["name"])
    try:
        evidence = _load_strict_json(evidence_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        violations.append(f"command_evidence_parse:{name}")
        return None
    if not isinstance(evidence, dict):
        violations.append(f"command_evidence_shape:{name}")
        return None
    argv = evidence.get("argv")
    if (
        evidence.get("schema_version") != "work_item_closeout_command_evidence.v2"
        or evidence.get("name") != name
        or not isinstance(argv, list)
        or not argv
        or any(not isinstance(value, str) or not value for value in argv)
        or evidence.get("cwd") != project_root.as_posix()
        or evidence.get("started_at") != receipt_item["started_at"]
        or evidence.get("ended_at") != receipt_item["ended_at"]
        or evidence.get("exit_code") != receipt_item["exit_code"]
        or evidence.get("process_exit_code") != 0
        or evidence.get("passed") != receipt_item["passed"]
        or isinstance(evidence.get("monotonic_duration_ns"), bool)
        or not isinstance(evidence.get("monotonic_duration_ns"), int)
        or evidence["monotonic_duration_ns"] < 0
        or not isinstance(evidence.get("wall_clock_rollback_clamped"), bool)
        or (
            evidence.get("wall_clock_rollback_clamped") is True
            and evidence.get("ended_at") != evidence.get("started_at")
        )
        or shlex.join(argv) != receipt_item["command"]
        or not isinstance(evidence.get("stdout"), str)
        or not isinstance(evidence.get("stderr"), str)
    ):
        violations.append(f"command_evidence_binding:{name}")
        return None
    expected_commit = receipt["source_binding"]["implementation_commit"]
    expected_tree = receipt["source_binding"]["implementation_tree"]
    preimport_attestation = evidence.get("preimport_attestation")
    if not _preimport_attestation_valid(
        preimport_attestation,
        project_root=project_root,
        expected_commit=expected_commit,
        expected_tree=expected_tree,
    ):
        violations.append(f"command_preimport_attestation:{name}")
        preimport_attestation = None
    protected_paths = sorted(
        str(item["path"])
        for item in receipt["protected_user_assets"]["assets"]
    )
    for phase in ("source_before", "source_after"):
        source_state = evidence.get(phase)
        if (
            not isinstance(source_state, dict)
            or source_state.get("repository_root") != project_root.as_posix()
            or source_state.get("requested_checkout_root") != project_root.as_posix()
            or source_state.get("commit") != expected_commit
            or source_state.get("tree") != expected_tree
            or source_state.get("candidate_clean") is not True
            or source_state.get("tracked_changes") != []
            or source_state.get("staged_changes") != []
            or source_state.get("untracked_changes") != []
            or source_state.get("allowed_protected_asset_changes") != protected_paths
            or source_state.get("assume_unchanged_paths") != []
            or source_state.get("skip_worktree_paths") != []
            or source_state.get("ignored_execution_overlays") != []
            or source_state.get("untracked_execution_overlays") != []
            or source_state.get("object_mismatches") != []
            or not isinstance(source_state.get("git_object_manifest_digest"), str)
            or source_state.get("git_object_manifest_digest")
            != (
                expected_git_state.get("manifest_digest")
                if isinstance(expected_git_state, dict)
                else None
            )
            or source_state.get("git_object_format")
            != (
                expected_git_state.get("object_format")
                if isinstance(expected_git_state, dict)
                else None
            )
            or source_state.get("git_executable") != expected_git_binding
            or source_state.get("inspection_errors") != []
        ):
            violations.append(f"command_source_binding:{name}:{phase}")
    if evidence.get("source_before") != evidence.get("source_after"):
        violations.append(f"command_source_changed:{name}")
    if evidence.get("source_binding_match") is not True:
        violations.append(f"command_source_match:{name}")
    environment_policy = evidence.get("environment_policy")
    expected_removed = {
        key
        for key in (
            "PYTEST_ADDOPTS",
            "PYTEST_PLUGINS",
            "PYTHONPATH",
            "PYTHONSTARTUP",
            "PYTHONINSPECT",
            "COVERAGE_PROCESS_START",
        )
    }
    expected_forced_values = {
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "PYTHONHASHSEED": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    expected_authority_prefixes = [
        "BANDIT_",
        "COVERAGE_",
        "COV_CORE_",
        "DISTUTILS_",
        "DYLD_",
        "GIT_",
        "LD_",
        "PIP_",
        "PYTEST_",
        "PYTHON",
        "RUFF_",
        "SETUPTOOLS_",
    ]
    is_trusted_launcher_child = (
        len(argv) >= 6
        and Path(argv[0]).absolute() == Path("/usr/bin/python3.12")
        and argv[1:5]
        == ["-I", "-S", "-B", "-"]
        and argv[5] == "."
    )
    if (
        not isinstance(environment_policy, dict)
        or set(environment_policy.get("removed_keys", {})) != expected_removed
        or any(
            not isinstance(value, bool)
            for value in environment_policy.get("removed_keys", {}).values()
        )
        or environment_policy.get("forced_values") != expected_forced_values
        or environment_policy.get("authority_prefixes") != expected_authority_prefixes
        or not isinstance(environment_policy.get("authority_removed_keys"), list)
        or any(
            not isinstance(value, str)
            for value in environment_policy.get("authority_removed_keys", [])
        )
        or environment_policy.get("executable_path")
        != f"{(project_root / '.venv' / 'bin').resolve().as_posix()}:{os.defpath}"
        or environment_policy.get("pip_config_file") != os.devnull
        or environment_policy.get("git_authority_environment_scrubbed") is not True
        or environment_policy.get("loader_authority_environment_scrubbed") is not True
        or environment_policy.get("trusted_launcher_child")
        is not is_trusted_launcher_child
        or environment_policy.get("trusted_launcher_removed_keys")
        != (
            [
                "GIT_CONFIG_GLOBAL",
                "GIT_CONFIG_NOSYSTEM",
                "GIT_NO_REPLACE_OBJECTS",
                "GIT_OPTIONAL_LOCKS",
                "GIT_TERMINAL_PROMPT",
                "PYTHONDONTWRITEBYTECODE",
                "PYTHONHASHSEED",
            ]
            if is_trusted_launcher_child
            else []
        )
    ):
        violations.append(f"command_environment_policy:{name}")
    if not _trusted_launcher_stdin_valid(
        evidence.get("trusted_launcher_stdin"),
        enabled=is_trusted_launcher_child,
        project_root=project_root,
        expected_commit=expected_commit,
        expected_tree=expected_tree,
    ):
        violations.append(f"command_trusted_launcher_stdin:{name}")
    toolchain = evidence.get("toolchain")
    if (
        not isinstance(toolchain, dict)
        or expected_toolchain is None
        or toolchain.get("before") != expected_toolchain
        or toolchain.get("after") != expected_toolchain
        or toolchain.get("error_before") is not None
        or toolchain.get("error_after") is not None
        or toolchain.get("unchanged") is not True
    ):
        violations.append(f"command_toolchain_binding:{name}")
    executable = evidence.get("executable")
    executable_launcher: Path | None = None
    resolved_executable: Path | None = None
    if isinstance(executable, dict) and isinstance(executable.get("launcher_path"), str):
        executable_launcher = Path(executable["launcher_path"]).absolute()
    if isinstance(executable, dict) and isinstance(executable.get("resolved_path"), str):
        resolved_executable = Path(executable["resolved_path"]).resolve()
    if (
        executable_launcher is None
        or resolved_executable is None
        or not executable_launcher.is_file()
        or not resolved_executable.is_file()
        or executable.get("requested") != argv[0]
        or executable.get("unchanged") is not True
        or executable.get("launcher_sha256") != sha256_file(executable_launcher)
        or executable.get("launcher_sha256_after")
        != executable.get("launcher_sha256")
        or executable.get("launcher_symlink_target_after")
        != executable.get("launcher_symlink_target")
        or executable.get("resolved_sha256") != sha256_file(resolved_executable)
        or executable.get("resolved_sha256_after")
        != executable.get("resolved_sha256")
        or executable_launcher.resolve() != resolved_executable
    ):
        violations.append(f"command_executable_binding:{name}")
    else:
        python_command = Path(argv[0]).name.startswith("python")
        if python_command:
            trusted_launcher_command = argv[1:5] == [
                "-I",
                "-S",
                "-B",
                "-",
            ] and len(argv) >= 6 and argv[5] == "."
            python_fixed = next(
                (
                    item
                    for item in (expected_toolchain or {}).get("fixed_files", [])
                    if item.get("path") == "bin/python"
                ),
                None,
            )
            if trusted_launcher_command:
                system_python = Path("/usr/bin/python3.12")
                if (
                    executable_launcher != system_python
                    or resolved_executable != system_python.resolve()
                    or executable.get("launcher_sha256")
                    != sha256_file(system_python.resolve())
                    or executable.get("launcher_symlink_target") is not None
                ):
                    violations.append(f"command_python_runtime:{name}")
            elif (
                executable_launcher
                != (project_root / ".venv" / "bin" / "python").absolute()
                or resolved_executable != Path(sys.executable).resolve()
                or not isinstance(python_fixed, dict)
                or python_fixed.get("sha256") != executable.get("launcher_sha256")
                or python_fixed.get("symlink_target")
                != executable.get("launcher_symlink_target")
            ):
                violations.append(f"command_python_runtime:{name}")
        else:
            expected_bin = (project_root / ".venv" / "bin").resolve()
            launcher_relative: str | None = None
            try:
                executable_launcher.relative_to(expected_bin)
                launcher_relative = executable_launcher.relative_to(
                    project_root / ".venv"
                ).as_posix()
            except ValueError:
                violations.append(f"command_tool_runtime:{name}")
            wrapper = next(
                (
                    item
                    for item in (expected_toolchain or {}).get("wrappers", [])
                    if item.get("name") == Path(argv[0]).name
                ),
                None,
            )
            if (
                not isinstance(wrapper, dict)
                or wrapper.get("path")
                != launcher_relative
                or wrapper.get("resolved_path") != resolved_executable.as_posix()
                or wrapper.get("sha256") != executable.get("launcher_sha256")
                or executable.get("launcher_symlink_target") is not None
            ):
                violations.append(f"command_toolchain_executable:{name}")
    if len(evidence["stdout"].encode("utf-8")) + len(evidence["stderr"].encode("utf-8")) > MAX_JSON_BYTES:
        violations.append(f"command_evidence_too_large:{name}")
    if not _command_matches_slot(name, argv):
        violations.append(f"command_contract:{name}")
    if not _command_output_matches_slot(
        name,
        stdout=evidence["stdout"],
        stderr=evidence["stderr"],
    ):
        violations.append(f"command_output_contract:{name}")
    return preimport_attestation


def _trusted_launcher_stdin_valid(
    binding: Any,
    *,
    enabled: bool,
    project_root: Path,
    expected_commit: str,
    expected_tree: str,
) -> bool:
    if not enabled:
        return binding is None
    try:
        git = _trusted_git_for_checkout(project_root)
        source = git.run(
            project_root,
            "show",
            f"HEAD:{_PREIMPORT_LAUNCHER_RELATIVE_PATH}",
        )
        expected = {
            "execution_source": "trusted_git_blob_stdin",
            "relative_path": _PREIMPORT_LAUNCHER_RELATIVE_PATH,
            "commit": expected_commit,
            "tree": expected_tree,
            "blob_oid": git.run(
                project_root,
                "rev-parse",
                f"HEAD:{_PREIMPORT_LAUNCHER_RELATIVE_PATH}",
            ).strip(),
            "sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        }
    except WorkItemGovernanceError:
        return False
    return binding == expected


def _preimport_attestation_valid(
    attestation: Any,
    *,
    project_root: Path,
    expected_commit: str,
    expected_tree: str,
) -> bool:
    if not isinstance(attestation, dict):
        return False
    bound = dict(attestation)
    digest = bound.pop("attestation_sha256", None)
    launcher = project_root / _PREIMPORT_LAUNCHER_RELATIVE_PATH
    system_python = Path("/usr/bin/python3.12")
    try:
        python_resolved = system_python.resolve(strict=True)
        python_metadata = python_resolved.stat()
        launcher_sha256 = sha256_file(launcher)
        python_sha256 = sha256_file(python_resolved)
        git_sha256 = sha256_file(Path("/usr/bin/git"))
        preimport_git = _trusted_git_for_checkout(project_root)
        preimport_source_state = _inspect_git_checkout(
            project_root,
            git=preimport_git,
            pathspecs=(),
            excluded_paths=frozenset(
                {
                    "AGENTS.md",
                    "AGENTS - 副本.amd",
                    "AGENTS - 副本.md:Zone.Identifier",
                    "AGENTS.md:Zone.Identifier",
                }
            ),
        )
        launcher_blob_oid = preimport_git.run(
            project_root,
            "rev-parse",
            f"HEAD:{_PREIMPORT_LAUNCHER_RELATIVE_PATH}",
        ).strip()
    except (OSError, WorkItemGovernanceError):
        return False
    source = attestation.get("source")
    environment = attestation.get("environment")
    expected_python = {
        "requested_path": system_python.as_posix(),
        "resolved_path": python_resolved.as_posix(),
        "proc_self_exe": python_resolved.as_posix(),
        "sha256": python_sha256,
        "owner_uid": 0,
        "mode": f"{stat.S_IMODE(python_metadata.st_mode):04o}",
        "root_owned": True,
        "group_or_other_writable": False,
    }
    return bool(
        attestation.get("schema_version")
        == "work_item_r3_preimport_attestation.v1"
        and attestation.get("accepted") is True
        and attestation.get("project_root") == project_root.as_posix()
        and attestation.get("launcher_relative_path")
        == _PREIMPORT_LAUNCHER_RELATIVE_PATH
        and attestation.get("launcher_execution_source")
        == "trusted_git_blob_stdin"
        and attestation.get("launcher_blob_oid") == launcher_blob_oid
        and attestation.get("launcher_sha256") == launcher_sha256
        and attestation.get("python_executable") == expected_python
        and stat.S_ISREG(python_metadata.st_mode)
        and python_metadata.st_uid == 0
        and not python_metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
        and bool(python_metadata.st_mode & stat.S_IXUSR)
        and attestation.get("python_flags")
        == {
            "isolated": True,
            "no_site": True,
            "dont_write_bytecode": True,
            "safe_path": True,
        }
        and attestation.get("startup_authority_environment") == []
        and isinstance(source, dict)
        and source.get("commit") == expected_commit
        and source.get("tree") == expected_tree
        and source.get("git_object_format")
        == preimport_source_state["object_format"]
        and source.get("tracked_path_count")
        == preimport_source_state["tracked_path_count"]
        and source.get("tracked_manifest_sha256")
        == preimport_source_state["manifest_digest"]
        and preimport_source_state["object_mismatches"] == []
        and preimport_source_state["assume_unchanged_paths"] == []
        and preimport_source_state["skip_worktree_paths"] == []
        and preimport_source_state["ignored_execution_overlays"] == []
        and preimport_source_state["untracked_execution_overlays"] == []
        and source.get("git_executable_sha256") == git_sha256
        and source.get("launcher_blob_oid") == launcher_blob_oid
        and source.get("launcher_blob_sha256") == launcher_sha256
        and environment
        == {
            "entry_count": _PREIMPORT_ENVIRONMENT_ENTRY_COUNT,
            "environment_tree_sha256": _PREIMPORT_ENVIRONMENT_TREE_SHA256,
        }
        and isinstance(digest, str)
        and digest == canonical_sha256(bound)
    )


def _command_matches_slot(name: str, argv: list[str]) -> bool:
    executable = Path(argv[0]).name
    modules = tuple(argv[1:3])
    arguments = argv[1:]
    is_python = executable.startswith("python")
    closeout_launcher_arguments = (
        argv[6:]
        if is_python
        and argv[1:5]
        == ["-I", "-S", "-B", "-"]
        and len(argv) >= 6
        and argv[5] == "."
        else None
    )
    is_pytest = executable == "pytest" or (is_python and modules == ("-m", "pytest"))
    pytest_arguments = arguments if executable == "pytest" else arguments[2:]
    if name in _EXPECTED_PYTEST_ARGUMENTS:
        return is_pytest and pytest_arguments == _EXPECTED_PYTEST_ARGUMENTS[name]
    if name == "ruff":
        return (executable == "ruff" and arguments == ["check", "."]) or (
            is_python and modules == ("-m", "ruff") and arguments[2:] == ["check", "."]
        )
    if name == "bandit_changed_scope":
        tool_arguments = arguments if executable == "bandit" else arguments[2:]
        return (
            executable == "bandit" or (is_python and modules == ("-m", "bandit"))
        ) and tool_arguments == ["-q", "-f", "json", "--exit-zero", *_BANDIT_CHANGED_SCOPE]
    if name == "pip_audit":
        return (executable == "pip-audit" and not arguments) or (
            is_python and arguments == ["-m", "pip_audit"]
        )
    if name == "wheel_source_inventory":
        return (
            closeout_launcher_arguments
            == [
                "wheel-inventory",
                "--checkout",
                ".",
                "--wheel",
                (
                    "docs/WIG-P3-CANARY-A1-R2-IMPLEMENTATION-R3-review/evidence/"
                    "candidate/colameta-0.1.2-py3-none-any.whl"
                ),
                "--output",
                (
                    "docs/WIG-P3-CANARY-A1-R2-IMPLEMENTATION-R3-review/evidence/"
                    "wheel-source-inventory.json"
                ),
            ]
        )
    if name == "runtime_isolation_smoke":
        return (
            is_pytest
            and pytest_arguments
            == [
                "-q",
                "tests/test_work_item_authoritative_canary.py::"
                "test_loopback_conformance_requires_token_and_exposes_exact_surface",
                "--basetemp=docs/WIG-P3-CANARY-A1-R2-IMPLEMENTATION-R3-review/"
                "evidence/runtime/pytest-runtime-exact",
            ]
        )
    if name == "protected_assets_hash_check":
        tool_arguments = closeout_launcher_arguments or []
        return (
            closeout_launcher_arguments is not None
            and tool_arguments[:1] == ["protected-assets-check"]
            and tool_arguments[1::2] == ["--expected"] * 4
            and len(tool_arguments[2::2]) == 4
        )
    if name == "review_bundle_accessibility":
        expected = [
            "bundle-access-check",
            "--bundle-root",
            "docs/WIG-P3-CANARY-A1-R2-IMPLEMENTATION-R3-review",
        ]
        for relative_path in _REQUIRED_REVIEW_BUNDLE_FILES:
            expected.extend(("--required", relative_path))
        return (
            closeout_launcher_arguments is not None
            and closeout_launcher_arguments == expected
        )
    return False


def _command_output_matches_slot(name: str, *, stdout: str, stderr: str) -> bool:
    combined = f"{stdout}\n{stderr}".lower()
    if name in {
        "schema_contract_validation",
        "focused_negative_tests",
        "concurrency_tests",
        "full_pytest",
        "architecture_checks",
    }:
        matches = [int(value) for value in re.findall(r"(?:^|\s)(\d+) passed", combined)]
        expected_exact = _EXACT_PYTEST_PASSED.get(name)
        return (
            bool(matches)
            and (
                max(matches) == expected_exact
                if expected_exact is not None
                else max(matches) >= _MINIMUM_PYTEST_PASSED[name]
            )
            and not any(marker in combined for marker in (" failed", " error", " errors"))
        )
    if name == "ruff":
        return stdout.strip().lower() == "all checks passed!" and not stderr.strip()
    if name == "bandit_changed_scope":
        try:
            payload = _loads_strict_json(stdout)
            totals = payload["metrics"]["_totals"]
        except (KeyError, TypeError, json.JSONDecodeError, ValueError):
            return False
        return (
            payload.get("errors") == []
            and isinstance(payload.get("results"), list)
            and totals.get("SEVERITY.HIGH") == 0
        )
    if name == "pip_audit":
        return combined.strip() == "no known vulnerabilities found"
    if name == "wheel_source_inventory":
        return not combined.strip()
    if name == "runtime_isolation_smoke":
        matches = [int(value) for value in re.findall(r"(?:^|\s)(\d+) passed", combined)]
        expected_exact = _EXACT_PYTEST_PASSED.get(name)
        return (
            bool(matches)
            and (
                max(matches) == expected_exact
                if expected_exact is not None
                else max(matches) >= _MINIMUM_PYTEST_PASSED[name]
            )
            and not any(marker in combined for marker in (" failed", " error", " errors"))
        )
    if name in {"protected_assets_hash_check", "review_bundle_accessibility"}:
        try:
            payload = _loads_strict_json(stdout)
        except (json.JSONDecodeError, TypeError, ValueError):
            return False
        return isinstance(payload, dict) and payload.get("pass") is True
    return False


def _verify_authentication_preflight_evidence(
    receipt: dict[str, Any],
    evidence_root: Path,
    violations: list[str],
) -> None:
    preflight_path = _evidence_path(
        evidence_root,
        "evidence/preflight-receipt.json",
        "preflight_receipt",
        violations,
    )
    if preflight_path is None:
        return
    try:
        preflight = _load_strict_json(preflight_path)
        validate_governance_record(
            "work_item_authoritative_canary_preflight_receipt.v1",
            preflight,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError, WorkItemGovernanceError):
        violations.append("preflight_receipt_parse_or_schema")
        return
    if canonical_sha256(preflight) != receipt["fresh_ledger"]["preflight_receipt_digest"]:
        violations.append("preflight_receipt_digest")
    authentication = preflight.get("authentication")
    closeout_authentication = receipt["authentication"]
    if not isinstance(authentication, dict) or {
        "auth_mode": authentication.get("auth_mode"),
        "token_source": authentication.get("token_source"),
        "token_generation_algorithm": authentication.get("token_generation_algorithm"),
        "token_entropy_bits": authentication.get("token_entropy_bits"),
        "token_generation_evidence_digest": authentication.get(
            "token_generation_evidence_digest"
        ),
        "auth_file_mode": authentication.get("token_file_mode"),
        "auth_parent_directories_mode": authentication.get("token_parent_mode"),
        "weak_token_configuration_rejected": authentication.get(
            "weak_token_configuration_rejected"
        ),
        "token_absent_from_public_surfaces": authentication.get(
            "token_absent_from_public_surfaces"
        ),
    } != {
        key: closeout_authentication[key]
        for key in (
            "auth_mode",
            "token_source",
            "token_generation_algorithm",
            "token_entropy_bits",
            "token_generation_evidence_digest",
            "auth_file_mode",
            "auth_parent_directories_mode",
            "weak_token_configuration_rejected",
            "token_absent_from_public_surfaces",
        )
    }:
        violations.append("preflight_authentication_binding")


def _verify_spec_binding(
    receipt: dict[str, Any],
    project_root: Path,
    violations: list[str],
) -> None:
    manifest_path = project_root / _SPEC_BINDING_PATHS["freeze_manifest_sha256"]
    try:
        manifest = _load_strict_json(manifest_path)
        package_binding = manifest["package_binding"]
        frozen_files = package_binding["files"]
        frozen_by_name = {Path(item["path"]).name: item for item in frozen_files}
    except (KeyError, OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        violations.append("spec_freeze_manifest_parse")
        return
    if (
        package_binding.get("file_count_excluding_manifest") != len(frozen_files)
        or package_binding.get("total_bytes_excluding_manifest")
        != sum(item["bytes"] for item in frozen_files)
        or package_binding.get("file_list_root_algorithm")
        != (
            "sha256(concatenated UTF-8 '<sha256>  <relative_path>\\n' lines "
            "sorted bytewise by relative_path)"
        )
        or package_binding.get("file_list_root_sha256")
        != hashlib.sha256(
            "".join(
                f"{item['sha256']}  {item['path']}\n"
                for item in sorted(frozen_files, key=lambda value: value["path"].encode("utf-8"))
            ).encode("utf-8")
        ).hexdigest()
        or package_binding.get("manifest_self_digest_included") is not False
    ):
        violations.append("spec_freeze_manifest_package_binding")
    for field, relative_path in _SPEC_BINDING_PATHS.items():
        target = (project_root / relative_path).resolve()
        try:
            target.relative_to(project_root)
        except ValueError:
            violations.append(f"spec_path_escape:{field}")
            continue
        if not target.is_file():
            violations.append(f"spec_file_missing:{field}")
            continue
        measured_sha256 = sha256_file(target)
        if receipt["spec_binding"][field] != measured_sha256:
            violations.append(f"spec_digest_mismatch:{field}")
        if field == "freeze_manifest_sha256":
            continue
        frozen = frozen_by_name.get(target.name)
        if (
            not isinstance(frozen, dict)
            or frozen.get("sha256") != measured_sha256
            or frozen.get("bytes") != target.stat().st_size
            or receipt["spec_binding"][field] != frozen.get("sha256")
        ):
            violations.append(f"spec_freeze_binding:{field}")


def _verify_fresh_ledger_and_runtime_evidence(
    receipt: dict[str, Any],
    evidence_root: Path,
    violations: list[str],
) -> None:
    preflight_path = _evidence_path(
        evidence_root,
        "evidence/preflight-receipt.json",
        "fresh_ledger_preflight",
        violations,
    )
    backup_path = _evidence_path(
        evidence_root,
        "evidence/pre-activation-backup-receipt.json",
        "fresh_ledger_backup",
        violations,
    )
    runtime_path = _evidence_path(
        evidence_root,
        "evidence/runtime-isolation-evidence.json",
        "fresh_ledger_runtime",
        violations,
    )
    snapshot_path = _evidence_path(
        evidence_root,
        receipt["activation_lease"]["lease_snapshot_export_relative_path"],
        "fresh_ledger_lease_snapshot",
        violations,
    )
    events_path = _evidence_path(
        evidence_root,
        receipt["activation_lease"]["lease_event_export_relative_path"],
        "fresh_ledger_lease_events",
        violations,
    )
    ledger_closeout_path = _evidence_path(
        evidence_root,
        "evidence/ephemeral-ledger-closeout.json",
        "fresh_ledger_closeout",
        violations,
    )
    fixture_path = _evidence_path(
        evidence_root,
        "evidence/synthetic-fixture.json",
        "fresh_ledger_fixture",
        violations,
    )
    if None in {
        preflight_path,
        backup_path,
        runtime_path,
        snapshot_path,
        events_path,
        ledger_closeout_path,
        fixture_path,
    }:
        return
    try:
        preflight = _load_strict_json(preflight_path)
        backup = _load_strict_json(backup_path)
        runtime = _load_strict_json(runtime_path)
        snapshot = _load_strict_json(snapshot_path)
        events = _load_strict_json(events_path)
        ledger_closeout = _load_strict_json(ledger_closeout_path)
        fixture = _load_strict_json(fixture_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        violations.append("fresh_ledger_evidence_parse")
        return
    _verify_runtime_observations_projection(
        runtime,
        evidence_root,
        preflight=preflight,
        snapshot=snapshot,
        violations=violations,
    )
    fresh = receipt["fresh_ledger"]
    preflight_fresh = preflight.get("fresh_ledger")
    preflight_backup = preflight.get("pre_activation_backup")
    if not isinstance(preflight_fresh, dict) or not isinstance(preflight_backup, dict):
        violations.append("fresh_ledger_evidence_shape")
        return
    expected_fresh = {
        "schema_version": preflight_fresh.get("schema_version"),
        "database_generation": preflight_fresh.get("database_generation"),
        "business_fact_counts_before": preflight_fresh.get("business_fact_counts"),
        "external_associations_before": preflight_fresh.get("external_associations"),
        "attempt_events_before": preflight_fresh.get("attempt_events"),
        "prior_activation_leases_for_authorization": preflight_fresh.get(
            "prior_activation_leases_for_authorization"
        ),
        "fresh_ledger_baseline_digest": preflight_fresh.get("baseline_digest"),
        "preflight_receipt_digest": canonical_sha256(preflight),
        "preflight_observed_at": preflight.get("observed_at"),
        "preflight_valid_until": preflight.get("valid_until"),
        "preview_signing_key_preprovisioned": preflight_fresh.get(
            "preview_signing_key_preprovisioned"
        ),
        "backup_receipt_digest": preflight_backup.get("receipt_digest"),
        "backup_sha256": preflight_backup.get("backup_sha256"),
        "integrity_check": preflight_fresh.get("integrity_check"),
        "foreign_key_violations": preflight_fresh.get("foreign_key_violations"),
    }
    for field, expected in expected_fresh.items():
        if fresh.get(field) != expected:
            violations.append(f"fresh_ledger_binding:{field}")
    try:
        observed = parse_timestamp(preflight["observed_at"], "preflight.observed_at")
        valid_until = parse_timestamp(preflight["valid_until"], "preflight.valid_until")
        claim_event = next(
            event
            for event in events
            if isinstance(event, dict) and event.get("event_type") == "process_claimed"
        )
        claimed = parse_timestamp(claim_event["created_at"], "process_claimed.created_at")
        measured_age = max(0.0, (claimed - observed).total_seconds())
        if abs(float(fresh["preflight_age_seconds_at_claim"]) - measured_age) > 0.001:
            violations.append("fresh_ledger_binding:preflight_age_seconds_at_claim")
        runtime_item = next(
            item for item in receipt["verification"] if item["name"] == "runtime_isolation_smoke"
        )
        command_started = parse_timestamp(runtime_item["started_at"], "runtime.started_at")
        command_ended = parse_timestamp(runtime_item["ended_at"], "runtime.ended_at")
        lease_updated = parse_timestamp(snapshot["updated_at"], "lease.updated_at")
        if (
            observed > claimed
            or claimed > valid_until
            or (valid_until - observed).total_seconds() > 120
            or observed < command_started
            or claimed > command_ended
            or lease_updated > command_ended
        ):
            violations.append("fresh_ledger_preflight_time_semantics")
    except (KeyError, StopIteration, TypeError, ValueError, WorkItemGovernanceError):
        violations.append("fresh_ledger_preflight_age")
    backup_core = {
        "api": backup.get("api"),
        "backup_sha256": backup.get("backup_sha256"),
        "database_generation": backup.get("database_generation"),
        "schema_version": backup.get("ledger_schema_version"),
        "integrity_check": (
            backup.get("integrity_check", [None])[0]
            if isinstance(backup.get("integrity_check"), list)
            else backup.get("integrity_check")
        ),
        "foreign_key_violations": backup.get("foreign_key_violations"),
        "mode": backup.get("mode"),
    }
    if canonical_sha256(backup_core) != fresh.get("backup_receipt_digest"):
        violations.append("fresh_ledger_backup_receipt_digest")
    if (
        backup.get("backup_bytes_in_sanitized_bundle") is not False
        or backup.get("backup_sha256") != fresh.get("backup_sha256")
        or backup.get("database_generation") != fresh.get("database_generation")
        or backup.get("ledger_schema_version") != fresh.get("schema_version")
        or backup.get("foreign_key_violations") != fresh.get("foreign_key_violations")
    ):
        violations.append("fresh_ledger_backup_binding")
    domain_totals = {
        key: 0
        for key in (
            "work_items",
            "task_versions",
            "runtime_attempts",
            "attempt_events",
            "artifacts",
            "decisions",
            "applied_gate_events",
            "rejected_gate_events",
            "audit_events",
            "outbox_events",
            "acceptance_manifests",
        )
    }
    for slot in fixture.get("command_slots", []):
        if not isinstance(slot, dict) or slot.get("expected_outcome") == "exact_idempotent_replay":
            continue
        delta = slot.get("expected_fact_delta")
        if not isinstance(delta, dict) or set(delta) != set(domain_totals):
            violations.append("fresh_ledger_fixture_fact_delta")
            continue
        for key, value in delta.items():
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                violations.append("fresh_ledger_fixture_fact_delta")
                continue
            domain_totals[key] += value
    expected_business_counts = {table: 0 for table in ZERO_BUSINESS_TABLES}
    expected_business_counts.update(
        {
            "work_items": domain_totals["work_items"],
            "task_versions": domain_totals["task_versions"],
            "execution_attempts": domain_totals["runtime_attempts"],
            "artifact_refs": domain_totals["artifacts"],
            "decision_records": domain_totals["decisions"],
            "gate_events": (
                domain_totals["applied_gate_events"]
                + domain_totals["rejected_gate_events"]
            ),
            "acceptance_manifests": domain_totals["acceptance_manifests"],
            "audit_events": domain_totals["audit_events"],
            "outbox_events": domain_totals["outbox_events"],
        }
    )
    expected_usage = {
        "new_work_items": domain_totals["work_items"],
        "task_versions": domain_totals["task_versions"],
        "runtime_attempts": domain_totals["runtime_attempts"],
        "artifacts": domain_totals["artifacts"],
        "decisions": domain_totals["decisions"],
        "applied_gate_events": domain_totals["applied_gate_events"],
        "rejected_gate_events": domain_totals["rejected_gate_events"],
        "gate_events_total": (
            domain_totals["applied_gate_events"]
            + domain_totals["rejected_gate_events"]
        ),
        "lease_events": len(events),
    }
    if (
        ledger_closeout.get("schema_version")
        != "work_item_r3_ephemeral_ledger_closeout.v1"
        or
        ledger_closeout.get("ledger_bytes_in_sanitized_bundle") is not False
        or ledger_closeout.get("integrity_check") != "ok"
        or ledger_closeout.get("foreign_key_violations") != []
        or ledger_closeout.get("business_fact_counts") != expected_business_counts
        or ledger_closeout.get("attempt_event_count") != domain_totals["attempt_events"]
        or ledger_closeout.get("external_association_count") != 0
        or ledger_closeout.get("database_generation")
        != preflight.get("fresh_ledger", {}).get("database_generation")
        or ledger_closeout.get("ledger_schema_version")
        != preflight.get("fresh_ledger", {}).get("schema_version")
        or ledger_closeout.get("activation_lease")
        != {
            "lease_id": snapshot.get("lease_id"),
            "status": snapshot.get("status"),
            "state_version": snapshot.get("state_version"),
            "usage": expected_usage,
        }
        or snapshot.get("usage") != expected_usage
    ):
        violations.append("fresh_ledger_closeout_binding")
    runtime_safety = runtime.get("safety")
    if not isinstance(runtime_safety, dict) or runtime_safety != receipt["safety"]:
        violations.append("runtime_safety_binding")
    if (
        runtime.get("existing_d1_canary_modified")
        != receipt["safety"]["existing_canary_restarted"]
        or runtime.get("existing_service_modified")
        != receipt["safety"]["existing_service_modified"]
        or runtime.get("authoritative_activation_outside_ephemeral_test")
        != receipt["safety"]["authoritative_activation_performed"]
    ):
        violations.append("runtime_safety_cross_binding")
    _verify_preflight_snapshot_binding(receipt, preflight, snapshot, violations)
    _verify_runtime_and_surface_receipt_bindings(receipt, preflight, runtime, snapshot, violations)


def _verify_runtime_observations_projection(
    runtime: dict[str, Any],
    evidence_root: Path,
    *,
    preflight: dict[str, Any],
    snapshot: dict[str, Any],
    violations: list[str],
) -> None:
    observations_ref = "evidence/runtime-observations.json"
    observations_path = _evidence_path(
        evidence_root,
        observations_ref,
        "runtime_observations",
        violations,
    )
    observations: Any = None
    if observations_path is not None:
        try:
            observations = _load_strict_json(observations_path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            violations.append("runtime_observations_parse")
    if (
        not isinstance(observations, dict)
        or set(observations) != _EXPECTED_RUNTIME_OBSERVATION_KEYS
        or observations.get("schema_version") != "work_item_r3_runtime_observations.v1"
        or observations.get("pass") is not True
        or observations.get("secret_material_included") is not False
        or observations.get("authentication") != _EXPECTED_RUNTIME_AUTHENTICATION
        or observations.get("tool_names") != list(AUTHORITATIVE_CANARY_TOOLS)
        or observations.get("restricted_surface")
        != _EXPECTED_RUNTIME_RESTRICTED_SURFACE
        or observations.get("lifecycle") != _EXPECTED_RUNTIME_LIFECYCLE
        or observations.get("safety") != _EXPECTED_RUNTIME_SAFETY
        or observations.get("existing_d1_canary_modified") is not False
        or observations.get("existing_service_modified") is not False
        or observations.get("authoritative_activation_outside_ephemeral_test")
        is not False
        or runtime.get("observations_ref") != observations_ref
        or observations_path is None
        or runtime.get("observations_sha256") != sha256_file(observations_path)
    ):
        violations.append("runtime_observations_binding")
        return
    preflight_runtime = preflight.get("runtime_isolation")
    process_identity = preflight.get("process_identity_inputs")
    snapshot_runtime = snapshot.get("runtime_binding")
    intended_port = (
        preflight_runtime.get("intended_port")
        if isinstance(preflight_runtime, dict)
        else None
    )
    expected_listener = {
        "inventory": [["127.0.0.1", intended_port]],
        "process_listener_count": 1,
        **_EXPECTED_RUNTIME_LISTENER_FLAGS,
    }
    process_pid = observations.get("process_pid")
    if (
        not isinstance(preflight_runtime, dict)
        or not isinstance(process_identity, dict)
        or not isinstance(snapshot_runtime, dict)
        or isinstance(process_pid, bool)
        or not isinstance(process_pid, int)
        or process_pid <= 0
        or process_pid != process_identity.get("pid")
        or intended_port != observations.get("port")
        or observations.get("bind_address") != "127.0.0.1"
        or observations.get("listener") != expected_listener
        or snapshot_runtime.get("claimed_process_identity")
        != process_identity.get("expected_process_identity")
    ):
        violations.append("runtime_observations_process_listener_binding")
    if (
        runtime.get("bind_address") != observations.get("bind_address")
        or runtime.get("port") != observations.get("port")
        or runtime.get("tool_names") != observations.get("tool_names")
        or runtime.get("listener") != observations.get("listener")
        or runtime.get("restricted_surface") != observations.get("restricted_surface")
        or runtime.get("safety") != observations.get("safety")
        or runtime.get("existing_d1_canary_modified")
        != observations.get("existing_d1_canary_modified")
        or runtime.get("existing_service_modified")
        != observations.get("existing_service_modified")
        or runtime.get("authoritative_activation_outside_ephemeral_test")
        != observations.get("authoritative_activation_outside_ephemeral_test")
        or runtime.get("authentication")
        != {
            key: observations.get("authentication", {}).get(key)
            for key in (
                "no_token_http_status",
                "wrong_token_http_status",
                "correct_token_http_status",
                "revoked_token_http_status",
                "token_file_present_after",
            )
        }
    ):
        violations.append("runtime_observations_projection")
    marker_path = _evidence_path(
        evidence_root,
        "evidence/runtime/revoked-token-rejected.ok",
        "revoked_token_marker",
        violations,
    )
    if marker_path is not None:
        try:
            marker = marker_path.read_bytes()
        except OSError:
            marker = b""
        if marker != b"true":
            violations.append("runtime_revoked_token_marker_content")


def _verify_preflight_snapshot_binding(
    receipt: dict[str, Any],
    preflight: dict[str, Any],
    snapshot: dict[str, Any],
    violations: list[str],
) -> None:
    runtime = snapshot.get("runtime_binding")
    snapshot_principal = snapshot.get("principal_binding")
    preflight_principal = preflight.get("principal_binding")
    preflight_runtime = preflight.get("runtime_isolation")
    if not all(
        isinstance(value, dict)
        for value in (runtime, snapshot_principal, preflight_principal, preflight_runtime)
    ):
        violations.append("preflight_snapshot_shape")
        return
    direct_bindings = {
        "authorization_id": (
            preflight.get("authorization_id"),
            snapshot.get("authorization_id"),
            receipt["activation_lease"]["authorization_id"],
        ),
        "authorization_digest": (
            preflight.get("authorization_digest"),
            snapshot.get("authorization_digest"),
            receipt["activation_lease"]["authorization_digest"],
        ),
        "lease_id": (
            preflight.get("activation_lease_id"),
            snapshot.get("lease_id"),
            receipt["activation_lease"]["lease_id"],
        ),
        "source_binding": (
            preflight.get("source_binding"),
            snapshot.get("source_binding"),
            {
                key: receipt["source_binding"][key]
                for key in (
                    "core_baseline_commit",
                    "implementation_commit",
                    "implementation_tree",
                    "wheel_sha256",
                )
            },
        ),
        "preflight_receipt_digest": (
            canonical_sha256(preflight),
            runtime.get("preflight_receipt_digest"),
            receipt["fresh_ledger"]["preflight_receipt_digest"],
        ),
        "backup_receipt_digest": (
            preflight.get("pre_activation_backup", {}).get("receipt_digest"),
            runtime.get("pre_activation_backup_receipt_digest"),
            receipt["fresh_ledger"]["backup_receipt_digest"],
        ),
        "backup_sha256": (
            preflight.get("pre_activation_backup", {}).get("backup_sha256"),
            runtime.get("pre_activation_backup_sha256"),
            receipt["fresh_ledger"]["backup_sha256"],
        ),
    }
    for field, values in direct_bindings.items():
        if values[0] != values[1] or values[1] != values[2]:
            violations.append(f"preflight_snapshot_binding:{field}")
    expected_principal = {
        "principal_id": preflight_principal.get("principal_id"),
        "principal_kind": preflight_principal.get("principal_kind"),
        "session_ref": preflight_principal.get("session_ref"),
        "caller_auth_mode": preflight.get("authentication", {}).get("auth_mode"),
        "principal_authenticated_by": preflight_principal.get("authenticated_by"),
        "permissions": preflight_principal.get("permissions"),
    }
    if snapshot_principal != expected_principal:
        violations.append("preflight_snapshot_binding:principal")
    path_bindings = {
        "canary_root_digest": "canary_root_path_digest",
        "home_path_digest": "home_path_digest",
        "xdg_config_path_digest": "xdg_config_path_digest",
        "xdg_state_path_digest": "xdg_state_path_digest",
        "xdg_cache_path_digest": "xdg_cache_path_digest",
        "registry_path_digest": "registry_path_digest",
        "project_root_digest": "project_root_digest",
        "runtime_executable_path_digest": "runtime_executable_path_digest",
        "cwd_path_digest": "cwd_path_digest",
        "settings_path_digest": "settings_path_digest",
        "ledger_path_digest": "ledger_path_digest",
        "backup_path_digest": "backup_path_digest",
        "activation_envelope_path_digest": "activation_envelope_path_digest",
        "claimed_activation_envelope_path_digest": (
            "claimed_activation_envelope_path_digest"
        ),
        "fixture_root_path_digest": "fixture_root_path_digest",
        "token_file_path_digest": "token_file_path_digest",
    }
    for runtime_field, preflight_field in path_bindings.items():
        source = (
            preflight.get("authentication", {})
            if preflight_field == "token_file_path_digest"
            else preflight_runtime
        )
        if runtime.get(runtime_field) != source.get(preflight_field):
            violations.append(f"preflight_snapshot_path_binding:{runtime_field}")
    scalar_bindings = {
        "database_generation": preflight.get("fresh_ledger", {}).get("database_generation"),
        "ledger_schema_version": preflight.get("fresh_ledger", {}).get("schema_version"),
        "fresh_ledger_baseline_digest": preflight.get("fresh_ledger", {}).get(
            "baseline_digest"
        ),
        "preflight_observed_at": preflight.get("observed_at"),
        "preflight_valid_until": preflight.get("valid_until"),
        "registry_project_count": preflight_runtime.get("registry_project_count"),
        "global_registry_fallback": False,
        "public_endpoint_created": preflight_runtime.get("public_endpoint_created"),
        "relay_enabled": preflight_runtime.get("relay_enabled"),
        "tunnel_enabled": preflight_runtime.get("tunnel_enabled"),
        "proxy_enabled": preflight_runtime.get("proxy_enabled"),
        "tool_allowlist_digest": preflight.get("restricted_surface", {}).get(
            "tool_allowlist_digest"
        ),
        "command_matrix_digest": preflight.get("restricted_surface", {}).get(
            "command_matrix_digest"
        ),
    }
    for field, expected in scalar_bindings.items():
        if runtime.get(field) != expected:
            violations.append(f"preflight_snapshot_binding:{field}")
    preflight_fresh = preflight.get("fresh_ledger", {})
    measured_baseline = canonical_sha256(
        {
            "business_fact_counts": preflight_fresh.get("business_fact_counts"),
            "external_associations": preflight_fresh.get("external_associations"),
            "attempt_events": preflight_fresh.get("attempt_events"),
            "prior_activation_leases_for_authorization": preflight_fresh.get(
                "prior_activation_leases_for_authorization"
            ),
        }
    )
    if (
        measured_baseline != preflight_fresh.get("baseline_digest")
        or measured_baseline != runtime.get("fresh_ledger_baseline_digest")
        or measured_baseline != receipt["fresh_ledger"]["fresh_ledger_baseline_digest"]
    ):
        violations.append("fresh_ledger_baseline_digest_recomputation")
    identity = preflight.get("process_identity_inputs")
    if not isinstance(identity, dict):
        violations.append("preflight_process_identity_shape")
    else:
        identity_payload = {
            key: identity.get(key)
            for key in (
                "pid",
                "process_start_ticks",
                "boot_id",
                "executable_sha256",
                "runtime_instance_nonce",
            )
        }
        measured_identity = canonical_sha256(identity_payload)
        if (
            identity.get("identity_algorithm")
            != (
                "sha256(canonical_json({pid,process_start_ticks,boot_id,"
                "executable_sha256,runtime_instance_nonce}))"
            )
            or measured_identity != identity.get("expected_process_identity")
            or measured_identity != runtime.get("expected_process_identity")
            or measured_identity != runtime.get("claimed_process_identity")
            or measured_identity != receipt["activation_lease"]["expected_process_identity"]
            or measured_identity != receipt["activation_lease"]["claimed_process_identity"]
        ):
            violations.append("preflight_process_identity_recomputation")
    _verify_preflight_path_recomputation(preflight, runtime, violations)


def _verify_preflight_path_recomputation(
    preflight: dict[str, Any],
    snapshot_runtime: dict[str, Any],
    violations: list[str],
) -> None:
    runtime = preflight["runtime_isolation"]
    root = Path(str(runtime["canary_root_resolved_path"])).expanduser().resolve()
    if canonical_path_digest(root) != runtime.get("canary_root_path_digest"):
        violations.append("preflight_path_digest:canary_root")
    path_fields = {
        "home": ("home_relative_path", "home_path_digest"),
        "xdg_config": ("xdg_config_relative_path", "xdg_config_path_digest"),
        "xdg_state": ("xdg_state_relative_path", "xdg_state_path_digest"),
        "xdg_cache": ("xdg_cache_relative_path", "xdg_cache_path_digest"),
        "registry": ("registry_relative_path", "registry_path_digest"),
        "project_root": ("project_root_relative_path", "project_root_digest"),
        "runtime_executable": (
            "runtime_executable_relative_path",
            "runtime_executable_path_digest",
        ),
        "cwd": ("cwd_relative_path", "cwd_path_digest"),
        "settings": ("settings_relative_path", "settings_path_digest"),
        "ledger": ("ledger_relative_path", "ledger_path_digest"),
        "backup": ("backup_relative_path", "backup_path_digest"),
        "activation_envelope": (
            "activation_envelope_relative_path",
            "activation_envelope_path_digest",
        ),
        "claimed_activation_envelope": (
            "claimed_activation_envelope_relative_path",
            "claimed_activation_envelope_path_digest",
        ),
        "fixture_root": ("fixture_root_relative_path", "fixture_root_path_digest"),
    }
    all_contained = True
    for label, (relative_field, digest_field) in path_fields.items():
        relative = Path(str(runtime.get(relative_field, "")))
        if relative.is_absolute() or ".." in relative.parts:
            all_contained = False
            violations.append(f"preflight_path_escape:{label}")
            continue
        resolved = (root / relative).resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            all_contained = False
            violations.append(f"preflight_path_escape:{label}")
            continue
        if canonical_path_digest(resolved) != runtime.get(digest_field):
            violations.append(f"preflight_path_digest:{label}")
    token_relative = Path(str(preflight["authentication"]["token_file_relative_path"]))
    token_path = (root / token_relative).resolve()
    try:
        token_path.relative_to(root)
    except ValueError:
        all_contained = False
        violations.append("preflight_path_escape:token_file")
    if canonical_path_digest(token_path) != preflight["authentication"].get(
        "token_file_path_digest"
    ):
        violations.append("preflight_path_digest:token_file")
    if runtime.get("all_paths_under_canary_root") is not all_contained:
        violations.append("preflight_path_containment_summary")
    snapshot_paths = {
        "canary_root_digest": runtime.get("canary_root_path_digest"),
        **{
            digest_field: runtime.get(digest_field)
            for _label, (_relative_field, digest_field) in path_fields.items()
        },
        "token_file_path_digest": preflight["authentication"].get("token_file_path_digest"),
    }
    snapshot_paths["canary_root_digest"] = runtime.get("canary_root_path_digest")
    for field, expected in snapshot_paths.items():
        if snapshot_runtime.get(field) != expected:
            violations.append(f"preflight_snapshot_path_recomputation:{field}")


def _verify_activation_contract_exports(
    receipt: dict[str, Any],
    evidence_root: Path,
    violations: list[str],
) -> None:
    envelope_path = _evidence_path(
        evidence_root,
        "evidence/claimed-activation-envelope.json",
        "claimed_activation_envelope",
        violations,
    )
    fixture_path = _evidence_path(
        evidence_root,
        "evidence/synthetic-fixture.json",
        "synthetic_fixture",
        violations,
    )
    if envelope_path is None or fixture_path is None:
        return
    try:
        envelope = _load_strict_json(envelope_path)
        fixture = _load_strict_json(fixture_path)
        validate_governance_record("work_item_activation_envelope.v1", envelope)
        validate_governance_record("work_item_synthetic_fixture_contract.v1", fixture)
        validate_synthetic_fixture_semantics(fixture)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError, WorkItemGovernanceError):
        violations.append("activation_contract_export_parse_or_semantics")
        return
    lease = receipt["activation_lease"]
    source = {
        key: receipt["source_binding"][key]
        for key in (
            "core_baseline_commit",
            "implementation_commit",
            "implementation_tree",
            "wheel_sha256",
        )
    }
    bindings = {
        "activation_envelope_digest": (
            canonical_sha256(envelope),
            lease["activation_envelope_digest"],
        ),
        "synthetic_fixture_contract_digest": (
            canonical_sha256(fixture),
            envelope.get("synthetic_fixture_contract_digest"),
            lease["synthetic_fixture_contract_digest"],
        ),
        "authorization_id": (
            fixture.get("authorization_id"),
            envelope.get("authorization_id"),
            lease["authorization_id"],
        ),
        "authorization_digest": (
            envelope.get("authorization_digest"),
            lease["authorization_digest"],
        ),
        "lease_id": (
            envelope.get("activation_lease_id"),
            lease["lease_id"],
        ),
        "spec_manifest_digest": (
            envelope.get("spec_manifest_digest"),
            receipt["spec_binding"]["freeze_manifest_sha256"],
        ),
        "preflight_receipt_digest": (
            envelope.get("preflight_receipt_digest"),
            receipt["fresh_ledger"]["preflight_receipt_digest"],
        ),
        "source_binding": (envelope.get("source_binding"), source),
        "fresh_ledger_baseline_digest": (
            envelope.get("fresh_ledger_baseline_digest"),
            receipt["fresh_ledger"]["fresh_ledger_baseline_digest"],
        ),
        "pre_activation_backup_receipt_digest": (
            envelope.get("pre_activation_backup_receipt_digest"),
            receipt["fresh_ledger"]["backup_receipt_digest"],
        ),
        "pre_activation_backup_sha256": (
            envelope.get("pre_activation_backup_sha256"),
            receipt["fresh_ledger"]["backup_sha256"],
        ),
        "tool_allowlist_digest": (
            envelope.get("tool_allowlist_digest"),
            receipt["spec_binding"]["tool_allowlist_sha256"],
        ),
        "command_matrix_digest": (
            envelope.get("command_matrix_digest"),
            receipt["spec_binding"]["command_matrix_sha256"],
        ),
    }
    for field, values in bindings.items():
        if any(value != values[0] for value in values[1:]):
            violations.append(f"activation_contract_binding:{field}")
    snapshot_path = _evidence_path(
        evidence_root,
        lease["lease_snapshot_export_relative_path"],
        "activation_contract_lease_snapshot",
        violations,
    )
    if snapshot_path is None:
        return
    try:
        snapshot = _load_strict_json(snapshot_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        violations.append("activation_contract_snapshot_parse")
        return
    runtime = snapshot.get("runtime_binding")
    principal = snapshot.get("principal_binding")
    scope = snapshot.get("scope")
    envelope_runtime = envelope.get("runtime_binding")
    envelope_principal = envelope.get("principal_binding")
    envelope_authentication = envelope.get("authentication")
    if not all(
        isinstance(value, dict)
        for value in (
            runtime,
            principal,
            scope,
            envelope_runtime,
            envelope_principal,
            envelope_authentication,
        )
    ):
        violations.append("activation_contract_nested_shape")
        return
    expected_scope = {
        "synthetic_fixture_contract_digest": canonical_sha256(fixture),
        "fixture_root_digest": fixture.get("fixture_root_path_digest"),
        "origin_kind": fixture.get("origin", {}).get("kind"),
        "objective_ref_prefix": fixture.get("objective_ref_prefix"),
        "authorized_create_command_digest": fixture.get("normalized_create", {}).get(
            "normalized_command_digest"
        ),
        "authorized_task_version_payload_digests": [
            item.get("normalized_payload_digest")
            for item in fixture.get("task_versions", [])
        ],
        "allowed_artifact_kinds": fixture.get("allowed_artifact_kinds"),
        "artifact_uri_scheme": fixture.get("artifact_uri_scheme"),
        "external_associations_allowed": fixture.get("external_associations_allowed"),
        "plan_version_refs_allowed": fixture.get("plan_version_refs_allowed"),
        "real_git_commit_artifacts_allowed": fixture.get(
            "real_git_commit_artifacts_allowed"
        ),
    }
    for field, expected in expected_scope.items():
        if scope.get(field) != expected:
            violations.append(f"activation_contract_fixture_scope_binding:{field}")
    origin_ref = fixture.get("origin", {}).get("ref")
    if (
        not isinstance(origin_ref, str)
        or not origin_ref.startswith(str(scope.get("allowed_origin_prefix") or ""))
    ):
        violations.append("activation_contract_fixture_scope_binding:allowed_origin_prefix")
    runtime_bindings = {
        "instance_id": "instance_id",
        "runtime_instance_nonce": "runtime_instance_nonce",
        "expected_process_identity": "expected_process_identity",
        "activation_envelope_path_digest": "activation_envelope_path_digest",
        "claimed_activation_envelope_path_digest": (
            "claimed_activation_envelope_path_digest"
        ),
        "project_name": "project_name",
        "project_root_digest": "project_root_digest",
        "bind_address": "bind_address",
        "port": "port",
    }
    for envelope_field, snapshot_field in runtime_bindings.items():
        if envelope_runtime.get(envelope_field) != runtime.get(snapshot_field):
            violations.append(f"activation_contract_runtime_binding:{envelope_field}")
    if envelope_runtime.get("canary_root_path_digest") != runtime.get("canary_root_digest"):
        violations.append("activation_contract_runtime_binding:canary_root_path_digest")
    expected_envelope_principal = {
        "principal_id": principal.get("principal_id"),
        "principal_kind": principal.get("principal_kind"),
        "session_ref": principal.get("session_ref"),
        "authenticated_by": principal.get("principal_authenticated_by"),
        "permissions": principal.get("permissions"),
    }
    if envelope_principal != expected_envelope_principal:
        violations.append("activation_contract_principal_binding")
    authentication_bindings = {
        "mode": receipt["authentication"]["auth_mode"],
        "token_source": receipt["authentication"]["token_source"],
        "token_file_path_digest": runtime.get("token_file_path_digest"),
        "token_generation_algorithm": receipt["authentication"][
            "token_generation_algorithm"
        ],
        "minimum_entropy_bits": 256,
        "request_context_mode": snapshot.get("policy", {}).get("request_context_mode"),
        "request_context_binding_algorithm": snapshot.get("policy", {}).get(
            "request_context_binding_algorithm"
        ),
        "bearer_token_embedded": False,
    }
    for field, expected in authentication_bindings.items():
        if envelope_authentication.get(field) != expected:
            violations.append(f"activation_contract_authentication_binding:{field}")
    if envelope.get("window") != snapshot.get("window"):
        violations.append("activation_contract_window_binding")
    if (
        envelope.get("created_at") != snapshot.get("created_at")
        or envelope.get("created_at") != envelope.get("window", {}).get("issued_at")
        or envelope.get("single_use") is not True
    ):
        violations.append("activation_contract_lifecycle_binding")
    try:
        window = envelope["window"]
        issued_at = parse_timestamp(window["issued_at"], "envelope.window.issued_at")
        not_before = parse_timestamp(window["not_before"], "envelope.window.not_before")
        expires_at = parse_timestamp(window["expires_at"], "envelope.window.expires_at")
        maximum_seconds = int(window["maximum_runtime_seconds"])
        if (
            issued_at > not_before
            or not_before >= expires_at
            or maximum_seconds <= 0
            or maximum_seconds > 1800
            or (expires_at - not_before).total_seconds() > maximum_seconds
        ):
            violations.append("activation_contract_window_semantics")
    except (KeyError, TypeError, ValueError, WorkItemGovernanceError):
        violations.append("activation_contract_window_parse")


def _verify_runtime_and_surface_receipt_bindings(
    receipt: dict[str, Any],
    preflight: dict[str, Any],
    runtime: dict[str, Any],
    snapshot: dict[str, Any],
    violations: list[str],
) -> None:
    isolation = receipt["runtime_isolation"]
    preflight_runtime = preflight.get("runtime_isolation")
    runtime_listener = runtime.get("listener")
    snapshot_runtime = snapshot.get("runtime_binding")
    snapshot_bootstrap = snapshot.get("bootstrap")
    if not all(
        isinstance(value, dict)
        for value in (preflight_runtime, runtime_listener, snapshot_runtime, snapshot_bootstrap)
    ):
        violations.append("runtime_isolation_evidence_shape")
        return
    expected_isolation = {
        "home_under_canary_root": preflight_runtime.get("all_paths_under_canary_root"),
        "xdg_config_under_canary_root": preflight_runtime.get("all_paths_under_canary_root"),
        "xdg_state_under_canary_root": preflight_runtime.get("all_paths_under_canary_root"),
        "xdg_cache_under_canary_root": preflight_runtime.get("all_paths_under_canary_root"),
        "registry_under_canary_root": preflight_runtime.get("all_paths_under_canary_root"),
        "runtime_executable_under_canary_root": preflight_runtime.get(
            "all_paths_under_canary_root"
        ),
        "cwd_under_canary_root": preflight_runtime.get("all_paths_under_canary_root"),
        "project_root_under_canary_root": preflight_runtime.get("all_paths_under_canary_root"),
        "settings_under_canary_root": preflight_runtime.get("all_paths_under_canary_root"),
        "ledger_under_canary_root": preflight_runtime.get("all_paths_under_canary_root"),
        "backup_under_canary_root": preflight_runtime.get("all_paths_under_canary_root"),
        "token_file_under_canary_root": preflight_runtime.get("all_paths_under_canary_root"),
        "fixture_root_under_canary_root": preflight_runtime.get("all_paths_under_canary_root"),
        "activation_envelope_under_canary_root": preflight_runtime.get(
            "all_paths_under_canary_root"
        ),
        "claimed_activation_envelope_under_canary_root": preflight_runtime.get(
            "all_paths_under_canary_root"
        ),
        "global_registry_not_selected": not bool(
            preflight_runtime.get("global_registry_selected")
        ),
        "global_registry_not_open": not bool(preflight_runtime.get("global_registry_open")),
        "registry_project_count": preflight_runtime.get("registry_project_count"),
        "bind_address": preflight_runtime.get("intended_bind_address"),
        "port": preflight_runtime.get("intended_port"),
        "preclaim_listener_count": preflight_runtime.get("preclaim_listener_count"),
        "postclaim_listener_count": runtime_listener.get("process_listener_count"),
        "listener_attestation_digest": snapshot_runtime.get("listener_attestation_digest"),
        "authenticated_request_context_binding_digest": snapshot_runtime.get(
            "authenticated_request_context_binding_digest"
        ),
        "request_dispatch_before_listener_attestation": snapshot_bootstrap.get(
            "request_dispatch_before_listener_attestation"
        ),
        "public_endpoint_created": runtime_listener.get("public_endpoint_created"),
        "relay_enabled": runtime_listener.get("relay_enabled"),
        "tunnel_enabled": runtime_listener.get("tunnel_enabled"),
        "proxy_enabled": runtime_listener.get("proxy_enabled"),
        "background_side_effect_workers_started": preflight_runtime.get(
            "background_side_effect_workers_started"
        ),
    }
    for field, expected in expected_isolation.items():
        if isolation.get(field) != expected:
            violations.append(f"runtime_isolation_binding:{field}")
    measured_listener_digest = listener_attestation_digest(
        claimed_process_identity=str(snapshot_runtime.get("claimed_process_identity")),
        bind_address=str(isolation["bind_address"]),
        port=int(isolation["port"]),
        process_listener_count=int(isolation["postclaim_listener_count"]),
        public_endpoint_created=bool(isolation["public_endpoint_created"]),
        relay_enabled=bool(isolation["relay_enabled"]),
        tunnel_enabled=bool(isolation["tunnel_enabled"]),
        proxy_enabled=bool(isolation["proxy_enabled"]),
    )
    principal = snapshot.get("principal_binding", {})
    measured_request_context_digest = request_context_binding_digest(
        lease_id=str(snapshot.get("lease_id")),
        authorization_digest=str(snapshot.get("authorization_digest")),
        claimed_process_identity=str(snapshot_runtime.get("claimed_process_identity")),
        runtime_instance_nonce=str(snapshot_runtime.get("runtime_instance_nonce")),
        listener_digest=measured_listener_digest,
        principal_id=str(principal.get("principal_id")),
        session_ref=str(principal.get("session_ref")),
    )
    if (
        measured_listener_digest != isolation["listener_attestation_digest"]
        or measured_listener_digest != snapshot_runtime.get("listener_attestation_digest")
        or measured_listener_digest
        != receipt["activation_lease"]["listener_attestation_digest"]
    ):
        violations.append("listener_attestation_digest_recomputation")
    if (
        measured_request_context_digest
        != isolation["authenticated_request_context_binding_digest"]
        or measured_request_context_digest
        != snapshot_runtime.get("authenticated_request_context_binding_digest")
        or measured_request_context_digest
        != receipt["activation_lease"]["authenticated_request_context_binding_digest"]
    ):
        violations.append("request_context_binding_digest_recomputation")
    tools = runtime.get("tool_names")
    surface_evidence = runtime.get("restricted_surface")
    surface = receipt["restricted_surface"]
    if not isinstance(tools, list) or not isinstance(surface_evidence, dict):
        violations.append("restricted_surface_evidence_shape")
        return
    expected_surface = {
        "profile": preflight.get("restricted_surface", {}).get("profile"),
        "listed_tool_count": len(tools),
        "listed_tools_sha256": canonical_sha256(tools),
        "definition_dispatch_exact_match": surface_evidence.get(
            "definition_dispatch_exact_match"
        ),
        "hidden_jsonrpc_call_rejected": surface_evidence.get(
            "hidden_jsonrpc_call_rejected"
        ),
        "direct_alias_rejected": surface_evidence.get("direct_alias_rejected"),
        "actions_disabled": surface_evidence.get("actions_disabled"),
        "agent_dispatch_enforced": surface_evidence.get("agent_dispatch_enforced"),
    }
    for field, expected in expected_surface.items():
        if surface.get(field) != expected:
            violations.append(f"restricted_surface_binding:{field}")


def _verify_exported_lease_evidence(
    receipt: dict[str, Any],
    evidence_root: Path,
    violations: list[str],
) -> None:
    root = evidence_root.expanduser().resolve()
    lease_receipt = receipt["activation_lease"]
    snapshot_path = _evidence_path(
        root,
        lease_receipt["lease_snapshot_export_relative_path"],
        "lease_snapshot",
        violations,
    )
    events_path = _evidence_path(
        root,
        lease_receipt["lease_event_export_relative_path"],
        "lease_events",
        violations,
    )
    if snapshot_path is None or events_path is None:
        return
    if sha256_file(snapshot_path) != lease_receipt["lease_snapshot_export_sha256"]:
        violations.append("lease_snapshot_export_digest")
    if sha256_file(events_path) != lease_receipt["lease_event_export_sha256"]:
        violations.append("lease_event_export_digest")
    try:
        snapshot = _load_strict_json(snapshot_path)
        events = _load_strict_json(events_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        violations.append(f"lease_evidence_parse:{type(exc).__name__}")
        return
    if not isinstance(snapshot, dict) or not isinstance(events, list):
        violations.append("lease_evidence_shape")
        return
    try:
        validate_governance_record("work_item_activation_lease.v1", snapshot)
    except WorkItemGovernanceError:
        violations.append("lease_snapshot_schema")
        return
    if canonical_sha256(snapshot) != lease_receipt["lease_snapshot_digest"]:
        violations.append("lease_snapshot_canonical_digest")
    expected_snapshot = {
        "lease_id": lease_receipt["lease_id"],
        "authorization_id": lease_receipt["authorization_id"],
        "authorization_digest": lease_receipt["authorization_digest"],
        "activation_envelope_digest": lease_receipt["activation_envelope_digest"],
        "status": lease_receipt["final_status"],
        "state_version": lease_receipt["final_state_version"],
        "spec_manifest_digest": receipt["spec_binding"]["freeze_manifest_sha256"],
        "lease_event_schema_digest": lease_receipt["lease_event_schema_digest"],
    }
    for field, expected in expected_snapshot.items():
        if snapshot.get(field) != expected:
            violations.append(f"lease_snapshot_binding:{field}")
    if snapshot.get("source_binding") != {
        "core_baseline_commit": receipt["source_binding"]["core_baseline_commit"],
        "implementation_commit": receipt["source_binding"]["implementation_commit"],
        "implementation_tree": receipt["source_binding"]["implementation_tree"],
        "wheel_sha256": receipt["source_binding"]["wheel_sha256"],
    }:
        violations.append("lease_snapshot_source_binding")
    runtime = snapshot.get("runtime_binding")
    scope = snapshot.get("scope")
    principal = snapshot.get("principal_binding")
    if not isinstance(runtime, dict) or not isinstance(scope, dict) or not isinstance(principal, dict):
        violations.append("lease_snapshot_nested_shape")
        return
    nested_bindings = {
        "claimed_envelope_path_digest": runtime.get("claimed_activation_envelope_path_digest"),
        "expected_process_identity": runtime.get("expected_process_identity"),
        "claimed_process_identity": runtime.get("claimed_process_identity"),
        "listener_attestation_digest": runtime.get("listener_attestation_digest"),
        "authenticated_request_context_binding_digest": runtime.get(
            "authenticated_request_context_binding_digest"
        ),
        "synthetic_fixture_contract_digest": scope.get("synthetic_fixture_contract_digest"),
        "principal_id": principal.get("principal_id"),
        "principal_kind": principal.get("principal_kind"),
        "session_ref": principal.get("session_ref"),
    }
    for field, actual in nested_bindings.items():
        if actual != lease_receipt[field]:
            violations.append(f"lease_snapshot_binding:{field}")
    if canonical_sha256(principal) != lease_receipt["principal_binding_digest"]:
        violations.append("principal_binding_digest")
    expected_root_digest = canonical_sha256({"resolved_posix_path": root.as_posix()})
    if lease_receipt["evidence_export_root_path_digest"] != expected_root_digest:
        violations.append("evidence_export_root_path_digest")
    if lease_receipt["lease_event_schema_digest"] != receipt["spec_binding"]["lease_event_schema_sha256"]:
        violations.append("lease_event_schema_digest")
    _verify_exported_event_chain(
        events=events,
        snapshot=snapshot,
        lease_receipt=lease_receipt,
        violations=violations,
    )


def _verify_exported_event_chain(
    *,
    events: list[Any],
    snapshot: dict[str, Any],
    lease_receipt: dict[str, Any],
    violations: list[str],
) -> None:
    if len(events) != lease_receipt["lease_event_count"] or not events:
        violations.append("lease_event_count")
        return
    prior_digest: str | None = None
    prior_status: str | None = None
    prior_version = 0
    prior_created_at = None
    digests: list[str] = []
    event_ids: set[str] = set()
    snapshot_created = parse_timestamp(snapshot["created_at"], "lease.created_at")
    snapshot_updated = parse_timestamp(snapshot["updated_at"], "lease.updated_at")
    snapshot_runtime = snapshot.get("runtime_binding", {})
    snapshot_principal = snapshot.get("principal_binding", {})
    snapshot_principal_digest = _event_principal_binding_digest(snapshot_principal)
    for sequence, event in enumerate(events, 1):
        if not isinstance(event, dict):
            violations.append(f"lease_event_shape:{sequence}")
            continue
        try:
            validate_governance_record("work_item_activation_lease_event.v1", event)
        except WorkItemGovernanceError:
            violations.append(f"lease_event_schema:{sequence}")
            continue
        unsigned = {key: value for key, value in event.items() if key != "event_digest"}
        if event["event_digest"] != canonical_sha256(unsigned):
            violations.append(f"lease_event_digest:{sequence}")
        if event["sequence"] != sequence or event["previous_event_digest"] != prior_digest:
            violations.append(f"lease_event_chain:{sequence}")
        if event["state_version_before"] != prior_version:
            violations.append(f"lease_event_state_version:{sequence}")
        if sequence == 1:
            if event["state_version_after"] != 0:
                violations.append(f"lease_event_state_version_delta:{sequence}")
        elif event["state_version_after"] != event["state_version_before"] + 1:
            violations.append(f"lease_event_state_version_delta:{sequence}")
        if sequence > 1 and event["status_before"] != prior_status:
            violations.append(f"lease_event_status:{sequence}")
        if event["lease_id"] != lease_receipt["lease_id"]:
            violations.append(f"lease_event_lease_binding:{sequence}")
        expected_process_identity = (
            None
            if sequence == 1
            else snapshot_runtime.get("claimed_process_identity")
        )
        expected_listener_digest = (
            None
            if sequence < 3
            else snapshot_runtime.get("listener_attestation_digest")
        )
        expected_request_context_digest = (
            None
            if sequence < 3
            else snapshot_runtime.get("authenticated_request_context_binding_digest")
        )
        if event.get("claimed_process_identity") != expected_process_identity:
            violations.append(f"lease_event_process_binding:{sequence}")
        if event.get("listener_attestation_digest") != expected_listener_digest:
            violations.append(f"lease_event_listener_binding:{sequence}")
        if (
            event.get("authenticated_request_context_binding_digest")
            != expected_request_context_digest
        ):
            violations.append(f"lease_event_request_context_binding:{sequence}")
        if (
            event.get("principal_binding_digest") is not None
            and event.get("principal_binding_digest") != snapshot_principal_digest
        ):
            violations.append(f"lease_event_principal_binding:{sequence}")
        event_id = str(event["lease_event_id"])
        if event_id in event_ids:
            violations.append(f"lease_event_duplicate_id:{sequence}")
        event_ids.add(event_id)
        prior_digest = str(event["event_digest"])
        prior_status = str(event["status_after"])
        prior_version = int(event["state_version_after"])
        try:
            created_at = parse_timestamp(event["created_at"], f"lease_event.created_at:{sequence}")
            if created_at < snapshot_created or created_at > snapshot_updated:
                violations.append(f"lease_event_time_bounds:{sequence}")
            if prior_created_at is not None and created_at < prior_created_at:
                violations.append(f"lease_event_time_order:{sequence}")
            prior_created_at = created_at
        except (KeyError, TypeError, ValueError, WorkItemGovernanceError):
            violations.append(f"lease_event_time_parse:{sequence}")
        digests.append(prior_digest)
    if canonical_sha256(digests) != lease_receipt["lease_event_root_sha256"]:
        violations.append("lease_event_root")
    if (
        prior_status != snapshot.get("status")
        or prior_version != snapshot.get("state_version")
        or prior_status != lease_receipt["final_status"]
        or prior_version != lease_receipt["final_state_version"]
        or snapshot.get("usage", {}).get("lease_events") != len(events)
    ):
        violations.append("lease_event_final_reconciliation")


def _event_principal_binding_digest(snapshot_principal: dict[str, Any]) -> str:
    """Project the Lease snapshot Principal into PrincipalContext.to_record()."""

    if not {"principal_authenticated_by", "permissions"}.issubset(snapshot_principal):
        # Older synthetic chains contain no command event Principal digest and
        # retain only the minimal snapshot identity. Their digest is never used
        # to authorize a non-null event binding.
        return canonical_sha256(snapshot_principal)
    return canonical_sha256(
        {
            "principal_id": snapshot_principal["principal_id"],
            "principal_kind": snapshot_principal["principal_kind"],
            "authenticated_by": snapshot_principal["principal_authenticated_by"],
            "granted_permissions": snapshot_principal["permissions"],
            "session_ref": snapshot_principal["session_ref"],
        }
    )
def _verify_protected_assets(
    receipt: dict[str, Any],
    project_root: Path,
    violations: list[str],
) -> None:
    root = project_root.expanduser().resolve()
    asset_paths = [str(item["path"]) for item in receipt["protected_user_assets"]["assets"]]
    for item in receipt["protected_user_assets"]["assets"]:
        target = (root / item["path"]).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            violations.append(f"protected_asset_path_escape:{item['path']}")
            continue
        if not target.is_file():
            violations.append(f"protected_asset_missing:{item['path']}")
        elif sha256_file(target) != item["sha256"]:
            violations.append(f"protected_asset_digest:{item['path']}")
    try:
        git = _trusted_git_for_checkout(root)
        staged = git.run(
            root,
            "diff",
            "--cached",
            "--name-only",
            "--",
            *asset_paths,
        )
        committed = git.run(
            root,
            "diff-tree",
            "--no-commit-id",
            "--name-only",
            "-r",
            "HEAD^",
            "HEAD",
            "--",
            *asset_paths,
        )
    except WorkItemGovernanceError:
        violations.append("protected_assets_git_measurement")
        return
    if staged.strip() or receipt["protected_user_assets"]["staged"]:
        violations.append("protected_assets_staged")
    if (
        committed.strip()
        or receipt["protected_user_assets"]["committed"]
    ):
        violations.append("protected_assets_committed")


def _verify_candidate_worktree_clean(
    receipt: dict[str, Any],
    project_root: Path,
    violations: list[str],
) -> None:
    protected = {
        str(item["path"])
        for item in receipt["protected_user_assets"]["assets"]
    }
    try:
        root = project_root.expanduser().resolve()
        git = _trusted_git_for_checkout(root)
        tracked = {
            item
            for item in git.run(root, "diff", "--name-only", "-z").split("\0")
            if item
        }
        staged = {
            item
            for item in git.run(root, "diff", "--cached", "--name-only", "-z").split("\0")
            if item
        }
        untracked = {
            item
            for item in git.run(
                root,
                "ls-files",
                "--others",
                "--exclude-standard",
                "-z",
            ).split("\0")
            if item
        }
        exact = _inspect_git_checkout(
            root,
            git=git,
            pathspecs=(),
            excluded_paths=frozenset(protected),
        )
    except WorkItemGovernanceError:
        violations.append("candidate_worktree_git_measurement")
        return
    changed = (tracked | staged | untracked) - protected
    exact_violation = any(
        exact[key]
        for key in (
            "object_mismatches",
            "assume_unchanged_paths",
            "skip_worktree_paths",
            "ignored_execution_overlays",
            "untracked_execution_overlays",
        )
    )
    if (
        changed
        or exact_violation
        or receipt["source_binding"]["tracked_source_clean"] is not True
    ):
        violations.append("candidate_worktree_not_clean")


def _verify_sanitized_evidence_bundle(
    evidence_root: Path,
    violations: list[str],
    *,
    allowed_relative_paths: Collection[str] | None = None,
    exact_paths: bool = False,
) -> None:
    expected_paths: set[str] | None = None
    if allowed_relative_paths is not None:
        expected_paths = set()
        for value in allowed_relative_paths:
            relative = Path(value)
            if relative.is_absolute() or not relative.parts or ".." in relative.parts:
                violations.append(f"sanitized_bundle_allowed_path_invalid:{value}")
                continue
            normalized = relative.as_posix()
            if normalized in expected_paths:
                violations.append(f"sanitized_bundle_allowed_path_duplicate:{normalized}")
            expected_paths.add(normalized)
    elif exact_paths:
        violations.append("sanitized_bundle_exact_paths_without_allowlist")
        return

    all_targets = sorted(evidence_root.rglob("*"))
    for target in all_targets:
        metadata = target.lstat()
        if stat.S_ISDIR(metadata.st_mode) and not target.is_symlink():
            continue
        if not stat.S_ISREG(metadata.st_mode):
            violations.append(
                "sanitized_bundle_special_entry:"
                f"{target.relative_to(evidence_root).as_posix()}"
            )
    actual_paths = {
        target.relative_to(evidence_root).as_posix()
        for target in all_targets
        if not target.is_dir() or target.is_symlink()
    }
    if exact_paths and actual_paths != expected_paths:
        violations.append("sanitized_bundle_path_set")
    if expected_paths is None:
        targets = all_targets
    else:
        targets = []
        for relative in sorted(expected_paths):
            target = evidence_root / relative
            if not target.is_file() or target.is_symlink():
                violations.append(f"sanitized_bundle_required_file:{relative}")
                continue
            targets.append(target)

    for target in targets:
        if target.is_symlink():
            violations.append("sanitized_bundle_symlink")
            continue
        if not target.is_file():
            continue
        name = target.name.lower()
        if (
            name == "auth.json"
            or name.endswith((".sqlite3", ".sqlite3-wal", ".sqlite3-shm"))
            or name.startswith(".build_")
        ):
            violations.append(f"sanitized_bundle_forbidden_file:{target.name}")
            continue
        if target.suffix == ".whl":
            _verify_sanitized_wheel(
                target,
                violations,
                label=target.relative_to(evidence_root).as_posix(),
            )
            continue
        size = target.stat().st_size
        if size > _MAX_SANITIZED_NON_ARCHIVE_BYTES:
            violations.append(
                "sanitized_bundle_non_archive_too_large:"
                f"{target.relative_to(evidence_root).as_posix()}"
            )
            continue
        payload = target.read_bytes()
        forbidden_kind = _forbidden_non_wheel_payload(payload)
        if forbidden_kind is not None:
            violations.append(
                "sanitized_bundle_forbidden_content:"
                f"{target.relative_to(evidence_root).as_posix()}:{forbidden_kind}"
            )
            continue
        _scan_sanitized_payload(
            payload,
            label=target.relative_to(evidence_root).as_posix(),
            parse_json=target.suffix.lower() == ".json",
            violations=violations,
        )


def _verify_bundle_manifest(evidence_root: Path, violations: list[str]) -> None:
    manifest_path = evidence_root / "BUNDLE_MANIFEST.json"
    if not manifest_path.is_file():
        violations.append("bundle_manifest_missing")
        return
    try:
        manifest = _load_strict_json(manifest_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        violations.append("bundle_manifest_parse")
        return
    all_targets = tuple(evidence_root.rglob("*"))
    actual_paths: set[str] = set()
    for path in all_targets:
        metadata = path.lstat()
        if stat.S_ISDIR(metadata.st_mode) and not path.is_symlink():
            continue
        actual_paths.add(path.relative_to(evidence_root).as_posix())
        if not stat.S_ISREG(metadata.st_mode):
            violations.append(
                "bundle_manifest_special_entry:"
                f"{path.relative_to(evidence_root).as_posix()}"
            )
    if actual_paths != set(_FINAL_REVIEW_BUNDLE_FILES):
        violations.append("bundle_manifest_path_set")
    files: list[dict[str, Any]] = []
    for path in sorted(
        item
        for item in all_targets
        if item.is_file() and not item.is_symlink()
    ):
        if path.resolve() == manifest_path.resolve():
            continue
        files.append(
            {
                "path": path.relative_to(evidence_root).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version")
        != "work_item_r3_closeout_bundle_manifest.v1"
        or manifest.get("files") != files
        or manifest.get("file_count") != len(files)
        or manifest.get("file_list_root_sha256") != canonical_sha256(files)
    ):
        violations.append("bundle_manifest_binding")


def _scan_sanitized_payload(
    payload: bytes,
    *,
    label: str,
    parse_json: bool,
    violations: list[str],
) -> None:
    if _TOKEN_SECRET_PATTERN.search(payload) or (
        parse_json and _AUTH_TOKEN_FIELD_PATTERN.search(payload)
    ):
        violations.append(f"sanitized_bundle_token_secret:{label}")
    if not parse_json:
        return
    try:
        decoded = _loads_strict_json(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        violations.append(f"sanitized_bundle_json_parse:{label}")
        return

    def scan(value: Any) -> bool:
        if isinstance(value, dict):
            return any(
                str(key).strip().lower() == "auth_token" or scan(item)
                for key, item in value.items()
            )
        if isinstance(value, list):
            return any(scan(item) for item in value)
        return isinstance(value, str) and bool(
            _TOKEN_SECRET_PATTERN.search(value.encode("utf-8"))
        )

    if scan(decoded):
        violations.append(f"sanitized_bundle_decoded_token_secret:{label}")


def _forbidden_non_wheel_payload(payload: bytes) -> str | None:
    if _SQLITE_MAGIC in payload:
        return "sqlite"
    if b"\x37\x7f\x06\x82" in payload or b"\x37\x7f\x06\x83" in payload:
        return "sqlite_wal"
    if b"\xd9\xd5\x05\xf9 \xa1c\xd7" in payload:
        return "sqlite_journal"
    for magic in _ARCHIVE_MAGICS:
        if magic in payload:
            return "archive"
    if len(payload) >= 263 and payload[257:263] in {b"ustar\x00", b"ustar "}:
        return "tar"
    return None


def _verify_sanitized_wheel(
    path: Path,
    violations: list[str],
    *,
    label: str | None = None,
) -> None:
    label = label or path.name
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            names = [item.filename for item in infos]
            if len(names) != len(set(names)):
                violations.append(f"sanitized_bundle_wheel_duplicate_member:{label}")
                return
            total_size = 0
            for info in infos:
                member = info.filename
                parts = Path(member).parts
                if (
                    info.flag_bits & 0x1
                    or member.startswith(("/", "\\"))
                    or not parts
                    or any(part in {"", ".", ".."} for part in parts)
                ):
                    violations.append(f"sanitized_bundle_wheel_unsafe_member:{label}")
                    return
                if info.is_dir():
                    continue
                total_size += info.file_size
                if total_size > _MAX_SANITIZED_ARCHIVE_BYTES:
                    violations.append(f"sanitized_bundle_wheel_too_large:{label}")
                    return
                payload = archive.read(info)
                _scan_sanitized_payload(
                    payload,
                    label=f"{label}!{member}",
                    parse_json=member.lower().endswith(".json"),
                    violations=violations,
                )
    except (OSError, zipfile.BadZipFile, RuntimeError, ValueError):
        violations.append(f"sanitized_bundle_wheel_parse:{label}")


def _evidence_path(
    root: Path,
    relative: str,
    label: str,
    violations: list[str],
) -> Path | None:
    target = (root / relative).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        violations.append(f"evidence_path_escape:{label}")
        return None
    if not target.is_file():
        violations.append(f"evidence_missing:{label}")
        return None
    return target


def _load_strict_json(path: Path) -> Any:
    if path.stat().st_size > MAX_JSON_BYTES:
        raise ValueError("JSON evidence exceeds the canonical size limit")

    return _loads_strict_json(path.read_text(encoding="utf-8"))


def _loads_strict_json(value: str) -> Any:
    if len(value.encode("utf-8")) > MAX_JSON_BYTES:
        raise ValueError("JSON evidence exceeds the canonical size limit")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON object key: {key}")
            result[key] = item
        return result

    return json.loads(
        value,
        object_pairs_hook=reject_duplicates,
        parse_constant=lambda constant: (_ for _ in ()).throw(
            ValueError(f"non-finite JSON: {constant}")
        ),
    )


__all__ = ["REQUIRED_VERIFICATION_NAMES", "verify_r2_closeout_receipt"]
