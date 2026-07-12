from __future__ import annotations

import json
from datetime import timezone
from pathlib import Path
from typing import Any

from runner.work_item_governance.canonical import canonical_sha256, sha256_file
from runner.work_item_governance.contracts import MAX_JSON_BYTES
from runner.work_item_governance.errors import WorkItemGovernanceError
from runner.work_item_governance.preview import parse_timestamp
from runner.work_item_governance.schema_loader import validate_governance_record


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
    verification = receipt["verification"]
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
    window = receipt["verification_window"]
    started = parse_timestamp(window["started_at"], "verification_window.started_at")
    ended = parse_timestamp(window["ended_at"], "verification_window.ended_at")
    generated = parse_timestamp(receipt["generated_at"], "generated_at")
    if started > ended or ended > generated.astimezone(timezone.utc):
        violations.append("closeout_time_order")
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
    if result == "PASS_WITH_GAPS" and receipt["blockers"]:
        violations.append("gaps_result_has_blockers")
    _verify_exported_lease_evidence(receipt, resolved_evidence_root, violations)
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
    digests: list[str] = []
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
        if sequence > 1 and event["status_before"] != prior_status:
            violations.append(f"lease_event_status:{sequence}")
        if event["lease_id"] != lease_receipt["lease_id"]:
            violations.append(f"lease_event_lease_binding:{sequence}")
        prior_digest = str(event["event_digest"])
        prior_status = str(event["status_after"])
        prior_version = int(event["state_version_after"])
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


def _verify_protected_assets(
    receipt: dict[str, Any],
    project_root: Path,
    violations: list[str],
) -> None:
    root = project_root.expanduser().resolve()
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

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f"duplicate JSON object key: {key}")
            value[key] = item
        return value

    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=reject_duplicates,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"non-finite JSON: {value}")),
    )


__all__ = ["REQUIRED_VERIFICATION_NAMES", "verify_r2_closeout_receipt"]
