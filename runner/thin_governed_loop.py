from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from runner.audit_package_taskbook_binding import (
    READY_FOR_REVIEWER_HANDOFF,
    build_audit_package_taskbook_binding,
)
from runner.execution_envelope import (
    ENVELOPE_CHECK_PASSED,
    EXPECTED_MASTER_TASKBOOK_REF as ENVELOPE_MASTER_REF,
    EXPECTED_STAGE_TASKBOOK_REF as ENVELOPE_STAGE_REF,
    EXPECTED_VERSION_TASKBOOK_REF as ENVELOPE_VERSION_REF,
    validate_execution_envelope,
)
from runner.execution_evidence_receipt import (
    EVIDENCE_RECEIPT_READY,
    build_execution_evidence_receipt,
)
from runner.executor_report import EXECUTOR_REPORT_READY, build_executor_report
from runner.executor_run_preview import PREVIEW_READY as RUN_PREVIEW_READY, render_executor_run_preview
from runner.external_taskbook_validator import (
    EXPECTED_MASTER_TASKBOOK_REF as EXTERNAL_MASTER_REF,
    EXPECTED_STAGE_TASKBOOK_REF as EXTERNAL_STAGE_REF,
    VALIDATION_PASSED,
    validate_external_taskbook_claim,
)
from runner.local_execution_receipt import RECEIPT_CHECK_PASSED, validate_local_execution_receipt
from runner.master_taskbook_registry import (
    MasterTaskbookRegistryError,
    load_master_taskbook_registry,
)
from runner.review_decision_adapter import ADAPTER_STATUS_ADAPTED, adapt_review_decision_value
from runner.review_feedback_classification import CLASSIFICATION_READY, classify_review_feedback
from runner.review_feedback_preview import PREVIEW_AVAILABLE as FEEDBACK_PREVIEW_AVAILABLE, build_review_feedback_preview
from runner.review_feedback_validator import VALID_FOR_PREVIEW, validate_review_feedback_for_preview
from runner.reviewer_handoff_generator import HANDOFF_PACKAGE_GENERATED, generate_reviewer_handoff_package
from runner.taskbook_import_adoption_preview import (
    ADOPTION_PREVIEW_READY,
    render_taskbook_import_adoption_preview,
)
from runner.taskbook_import_preview import PREVIEW_READY as IMPORT_PREVIEW_READY, render_taskbook_import_preview
from runner.taskbook_version_candidate_mapping import MAPPING_READY, map_preview_to_version_candidate
from runner.stage_taskbook_registry import (
    StageTaskbookRegistryError,
    load_stage_taskbook_registry,
)


THIN_LOOP_PASSED = "thin_governed_loop_passed"
THIN_LOOP_FAILED_CLOSED = "thin_governed_loop_failed_closed"
BASELINE_ANCHOR_READY = "baseline_anchor_ready"
MASTER_ANCHOR_VERIFIED = "master_anchor_verified"
STAGE_ANCHOR_VERIFIED = "stage_anchor_verified"
MASTER_TASKBOOK_HASH = "1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34"
STAGE_04_TASKBOOK_HASH = "05e6114a666942c0641c635905c2295feaa62b98bd9e7b5166babd662e015a41"
STAGE_06_TASKBOOK_HASH = "c83c979d447a4ec645d380b6c1dc206730d12d5d644c08582b3cfd04f3e0009d"

_STAGE_0_REQUIRED_ANCHORS = (
    "PROJECT_MASTER_TASKBOOK.md",
    ".colameta/taskbooks/master_taskbook_registry.json",
    ".colameta/taskbooks/stage_taskbook_registry.json",
)


def verify_stage_0_2_governance_anchors(project_root: str | Path) -> dict[str, Any]:
    """Verify the repository, Master, and Stage registry anchors without writes."""
    root = Path(project_root).expanduser().resolve()
    missing = [relative for relative in _STAGE_0_REQUIRED_ANCHORS if not (root / relative).is_file()]
    blockers: list[dict[str, Any]] = []
    if not root.is_dir():
        blockers.append({"code": "stage_00_project_root_missing", "stage": "stage_00_baseline"})
    if missing:
        blockers.append(
            {
                "code": "stage_00_required_anchor_missing",
                "stage": "stage_00_baseline",
                "missing_relative_paths": missing,
            }
        )

    master_result: dict[str, Any] | None = None
    try:
        master_result = load_master_taskbook_registry(root)
    except MasterTaskbookRegistryError as exc:
        blockers.append(
            {
                "code": "stage_01_master_anchor_invalid",
                "stage": "stage_01_master_anchor",
                "anchor_error_code": exc.error_code,
            }
        )
    except OSError:
        blockers.append(
            {
                "code": "stage_01_master_anchor_unreadable",
                "stage": "stage_01_master_anchor",
            }
        )

    master_hash = str((master_result or {}).get("master_actual_sha256") or "")
    if master_result is not None and master_hash != MASTER_TASKBOOK_HASH:
        blockers.append(
            {
                "code": "stage_01_master_anchor_constant_mismatch",
                "stage": "stage_01_master_anchor",
                "expected_hash": MASTER_TASKBOOK_HASH,
                "actual_hash": master_hash,
            }
        )

    stage_result: dict[str, Any] | None = None
    try:
        stage_result = load_stage_taskbook_registry(root)
    except StageTaskbookRegistryError as exc:
        blockers.append(
            {
                "code": "stage_02_stage_anchor_invalid",
                "stage": "stage_02_stage_taskbook",
                "anchor_error_code": exc.error_code,
            }
        )
    except OSError:
        blockers.append(
            {
                "code": "stage_02_stage_anchor_unreadable",
                "stage": "stage_02_stage_taskbook",
            }
        )

    baseline_blocked = any(item.get("stage") == "stage_00_baseline" for item in blockers)
    master_blocked = any(item.get("stage") == "stage_01_master_anchor" for item in blockers)
    stage_blocked = any(item.get("stage") == "stage_02_stage_taskbook" for item in blockers)
    return {
        "anchor_status": THIN_LOOP_FAILED_CLOSED if blockers else THIN_LOOP_PASSED,
        "stage_results": {
            "stage_00_baseline": {
                "baseline_anchor": "blocked" if baseline_blocked else BASELINE_ANCHOR_READY,
                "required_anchor_files": list(_STAGE_0_REQUIRED_ANCHORS),
                "missing_anchor_files": missing,
            },
            "stage_01_master_anchor": {
                "master_registry": "blocked" if master_blocked else MASTER_ANCHOR_VERIFIED,
                "master_hash": master_hash or None,
                "master_review_status": (
                    ((master_result or {}).get("record") or {}).get("master_review_status")
                ),
            },
            "stage_02_stage_taskbook": {
                "stage_registry": "blocked" if stage_blocked else STAGE_ANCHOR_VERIFIED,
                "registered_stage_count": (stage_result or {}).get("record_count", 0),
                "registered_stage_ids": (stage_result or {}).get("stage_ids", []),
            },
        },
        "blockers": blockers,
        "read_only": True,
        "side_effects": False,
    }


def example_stage_3_6_inputs() -> dict[str, Any]:
    """Return a deterministic in-memory example for the Stage 3-6 thin loop."""
    external_claim = {
        "source": {
            "system": "commander_chat",
            "source_id": "thin-governed-loop-example",
            "received_at": "2026-06-30T00:00:00+08:00",
        },
        "provenance": {
            "provided_by": "Commander",
            "capture_method": "pasted_text",
            "provenance_note": "Thin loop smoke example only.",
        },
        "external_taskbook_hash": "a" * 64,
        "expected_hash_authority_ref": {
            "authority_document": "commander_confirmation_prompt",
            "authority_hash": "b" * 64,
        },
        "master_taskbook_ref": dict(EXTERNAL_MASTER_REF),
        "stage_taskbook_ref": dict(EXTERNAL_STAGE_REF),
        "allowed_files": ["runner/example.py", "tests/test_example.py"],
        "forbidden_files": ["PROJECT_MASTER_TASKBOOK.md", ".colameta/plan.json", "**/.env"],
        "acceptance_commands": ["python -m unittest tests.test_example", "git diff --check"],
        "manual_acceptance": {
            "required": True,
            "reviewer": "Commander",
            "acceptance_note": "Manual review required before adoption.",
        },
        "out_of_scope": ["plan mutation", "executor dispatch", "delivery state accepted"],
        "supports_stage_and_master_goals": {
            "supports_stage_goal": True,
            "supports_master_goal": True,
            "rationale": "External taskbook remains a bounded claim until reviewed.",
        },
    }
    envelope = {
        "envelope_id": "thin-loop-execution-envelope",
        "envelope_schema_version": "execution_envelope.v1",
        "version_taskbook_ref": dict(ENVELOPE_VERSION_REF),
        "master_taskbook_ref": dict(ENVELOPE_MASTER_REF),
        "stage_taskbook_ref": dict(ENVELOPE_STAGE_REF),
        "authority_mode": "local_execution",
        "local_execution_authorization_ref": {
            "authorization_id": "thin-loop-local-execution-auth",
            "authority_status": "hash_specific_authorized_elsewhere",
        },
        "imported_receipt_authorization_ref": {},
        "allowed_files": ["runner/example.py", "tests/test_example.py"],
        "forbidden_files": ["PROJECT_MASTER_TASKBOOK.md", ".colameta/plan.json", "**/.env"],
        "allowed_commands": ["python -m unittest tests.test_example"],
        "validation_commands": ["python -m unittest tests.test_example", "git diff --check"],
        "timeout_limits": {"command_timeout_seconds": 120},
        "network_policy": {"network_allowed": False},
        "secrets_policy": {"read_secrets_allowed": False},
        "destructive_operation_policy": {"destructive_operations_allowed": False},
        "retry_policy": {"max_retries": 0},
        "stop_conditions": ["hash mismatch", "forbidden path touched"],
    }
    local_receipt = {
        "receipt_id": "thin-loop-local-receipt",
        "receipt_schema_version": "local_execution_receipt.v1",
        "receipt_kind": "local_execution_receipt",
        "local_execution_authorization_ref": {"authorization_id": "thin-loop-local-execution-auth"},
        "execution_envelope_ref": {"envelope_id": "thin-loop-execution-envelope"},
        "run_preview_ref": {"run_preview_id": "run_preview_thin-loop-execution-envelope"},
        "version_taskbook_ref": {"version_id": "stage_04_v4_3_taskbook_bound_local_execution_receipt_v1"},
        "master_taskbook_hash": MASTER_TASKBOOK_HASH,
        "stage_taskbook_hash": STAGE_04_TASKBOOK_HASH,
        "started_at": "2026-06-30T00:00:00+08:00",
        "completed_at": "2026-06-30T00:01:00+08:00",
        "execution_result": "executed",
        "command_attempts": [{"command": "python -m unittest tests.test_example", "exit_code": 0, "result": "passed"}],
        "touched_files": ["runner/example.py", "tests/test_example.py"],
        "observed_mutations": [{"path": "runner/example.py", "mutation_type": "modified"}],
        "validation_commands": ["python -m unittest tests.test_example", "git diff --check"],
        "validation_results": [
            {"command": "python -m unittest tests.test_example", "result": "passed"},
            {"command": "git diff --check", "result": "passed"},
        ],
        "validation_summary": "passed",
        "scope_check_result": "passed",
        "blocked_or_failed_reasons": [],
        "known_gaps": [],
        "remaining_risks": [{"risk_id": "review_required", "risk": "Reviewer has not accepted delivery."}],
    }
    review_feedback = {
        "review_feedback_id": "thin-loop-review-feedback",
        "review_feedback_schema_version": "review_feedback.v1",
        "reviewer_identity_or_source": {"source_type": "manual_reviewer", "display_name": "Reviewer"},
        "reviewer_authority_scope": {"scope": "review_feedback_only"},
        "reviewer_attestation": {"attested": True, "basis": "reviewed handoff package"},
        "reviewer_handoff_package_ref": {"handoff_package_id": "thin-loop-handoff-package"},
        "version_taskbook_ref": {"version_id": "stage_06_v6_1_review_feedback_schema_v1"},
        "execution_report_ref": {"executor_report_id": "thin-loop-executor-report"},
        "workspace_snapshot_ref": {"head": "thin-loop-head"},
        "master_taskbook_hash": MASTER_TASKBOOK_HASH,
        "stage_taskbook_hash": STAGE_06_TASKBOOK_HASH,
        "review_decision_value": "NEEDS_FIX",
        "pass_alias_policy_id_when_used": None,
        "charter_alignment": {"result": "aligned"},
        "task_completion": {"result": "partial"},
        "scope_assessment": {"result": "in_scope"},
        "reviewer_notes": "Thin loop feedback example.",
        "submitted_at": "2026-06-30T00:02:00+08:00",
    }
    return {
        "project_root": str(Path.cwd()),
        "current_head": "1a384e4c39749226b87b801182624cd6ad5074f0",
        "external_taskbook_claim": external_claim,
        "execution_envelope": envelope,
        "local_execution_receipt": local_receipt,
        "review_feedback": review_feedback,
    }


def run_stage_3_6_thin_governed_loop(inputs: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run the Stage 3-6 evidence path without granting runtime authority."""
    values = inputs or example_stage_3_6_inputs()
    project_root = values.get("project_root") or Path.cwd()
    external_claim = _dict(values.get("external_taskbook_claim"))
    envelope = _dict(values.get("execution_envelope"))
    local_receipt = _dict(values.get("local_execution_receipt"))
    review_feedback = _dict(values.get("review_feedback"))

    external_validation = validate_external_taskbook_claim(external_claim, project_root=project_root)
    import_preview = render_taskbook_import_preview(external_validation)
    import_preview_hash = _stable_hash(import_preview)
    version_candidate_mapping = map_preview_to_version_candidate(
        import_preview,
        import_preview_hash=import_preview_hash,
        normalized_claims_candidate=external_validation.get("normalized_claims_candidate"),
    )
    adoption_preview = render_taskbook_import_adoption_preview(
        version_candidate_mapping,
        mapping_hash=_stable_hash(version_candidate_mapping),
        current_head=str(values.get("current_head") or "unknown"),
        candidate_plan_diff_hash="c" * 64,
        candidate_allowed_files_delta_hash="d" * 64,
    )

    envelope_validation = validate_execution_envelope(envelope)
    run_preview = render_executor_run_preview(envelope, envelope_validation)
    receipt_validation = validate_local_execution_receipt(local_receipt)
    executor_report = build_executor_report(
        executor_report_id="thin-loop-executor-report",
        version_taskbook_ref={"version_id": "stage_04_v4_5_taskbook_bound_executor_report_v1"},
        master_taskbook_hash=MASTER_TASKBOOK_HASH,
        stage_taskbook_hash=STAGE_04_TASKBOOK_HASH,
        receipt_records=[
            {
                "receipt_ref": {"receipt_id": local_receipt.get("receipt_id"), "receipt_kind": local_receipt.get("receipt_kind")},
                "authority_mode": "local_execution",
                "receipt": local_receipt,
                "receipt_validation_result": receipt_validation,
            }
        ],
    )
    evidence_receipt = build_execution_evidence_receipt(
        evidence_receipt_id="thin-loop-execution-evidence-receipt",
        version_taskbook_ref={"version_id": "stage_04_v4_6_execution_evidence_receipt_v1"},
        master_taskbook_hash=MASTER_TASKBOOK_HASH,
        stage_taskbook_hash=STAGE_04_TASKBOOK_HASH,
        executor_report_records=[
            {
                "executor_report_ref": {"executor_report_id": executor_report["executor_report_id"]},
                "executor_report": executor_report,
            }
        ],
        evidence_hashes={"executor_report": _stable_hash(executor_report), "local_receipt": _stable_hash(local_receipt)},
    )
    audit_package = build_audit_package_taskbook_binding(
        audit_package_id="thin-loop-audit-package",
        version_taskbook_ref={"version_id": "stage_04_v4_9_audit_package_taskbook_binding_v1"},
        master_taskbook_hash=MASTER_TASKBOOK_HASH,
        stage_taskbook_hash=STAGE_04_TASKBOOK_HASH,
        execution_envelope_ref={"envelope_id": envelope.get("envelope_id")},
        run_preview_ref={"run_preview_id": run_preview.get("run_preview_id")},
        execution_receipt_refs=[{"receipt_id": local_receipt.get("receipt_id")}],
        executor_report_ref={"executor_report_id": executor_report["executor_report_id"]},
        execution_evidence_receipt_ref={"evidence_receipt_id": evidence_receipt["evidence_receipt_id"]},
        validation_truth_summary_ref=evidence_receipt["validation_truth_summary_ref"],
        scope_evidence_pack_ref={"scope_pack_id": "thin-loop-scope-pack"},
        validation_truth_statuses=["passed"],
        scope_result="in_scope",
        known_gaps=evidence_receipt["known_gaps"],
        remaining_risks=evidence_receipt["remaining_risks"],
    )

    handoff = generate_reviewer_handoff_package(
        {
            "reviewer_handoff_schema_ref": {"version_id": "stage_05_v5_1_reviewer_handoff_schema_v1"},
            "handoff_package_id": "thin-loop-handoff-package",
            "master_taskbook_ref": {"path": "PROJECT_MASTER_TASKBOOK.md"},
            "stage_taskbook_ref": {"path": "docs/taskbooks/stages/STAGE_05_REVIEWER_HANDOFF_PACKAGE.md"},
            "version_taskbook_ref": {"version_id": "stage_05_v5_2_reviewer_handoff_generator_v1"},
            "stage_4_audit_package_ref": {"audit_package_id": audit_package["audit_package_id"]},
            "execution_receipt_refs": [{"receipt_id": local_receipt.get("receipt_id")}],
            "claim_summary": {"summary": "Thin loop evidence is ready for reviewer inspection."},
            "changed_files": executor_report["changed_files_summary"],
            "validation_truth": executor_report["validation_truth_summary"],
            "scope_evidence": executor_report["scope_check_summary"],
            "known_risks": audit_package["remaining_risks"],
            "known_gaps": audit_package["known_gaps"],
            "reviewer_questions": [{"question_id": "accept_or_fix", "text": "Choose a review decision."}],
            "generated_at": "2026-06-30T00:03:00+08:00",
        }
    )

    feedback_context = {
        "review_feedback_schema_ref": {"schema_version": "review_feedback.v1"},
        "expected_master_taskbook_hash": MASTER_TASKBOOK_HASH,
        "expected_stage_taskbook_hash": STAGE_06_TASKBOOK_HASH,
        "expected_version_taskbook_ref": {"version_id": "stage_06_v6_1_review_feedback_schema_v1"},
        "expected_reviewer_handoff_package_ref": {"handoff_package_id": "thin-loop-handoff-package"},
        "expected_workspace_snapshot_ref": {"head": "thin-loop-head"},
    }
    feedback_validation = validate_review_feedback_for_preview(review_feedback, feedback_context)
    feedback_preview = build_review_feedback_preview(review_feedback, feedback_validation)
    feedback_classification = classify_review_feedback(
        review_feedback,
        feedback_validation,
        feedback_preview,
        {"mapping_policy_id": "stage-06-v6-4-decision-mapping"},
    )
    decision_adapter = adapt_review_decision_value(str(review_feedback.get("review_decision_value") or "UNKNOWN"))

    stage_results = {
        "stage_03_import": {
            "external_validation": external_validation["validation_result"],
            "import_preview": import_preview["preview_status"],
            "version_candidate_mapping": version_candidate_mapping["mapping_status"],
            "adoption_preview": adoption_preview["adoption_preview_status"],
        },
        "stage_04_execution_evidence": {
            "execution_envelope": envelope_validation["envelope_check_result"],
            "run_preview": run_preview["preview_status"],
            "local_receipt": receipt_validation["receipt_check_result"],
            "executor_report": executor_report["report_status"],
            "evidence_receipt": evidence_receipt["evidence_receipt_status"],
            "audit_package_handoff_readiness": audit_package["handoff_readiness"],
        },
        "stage_05_reviewer_handoff": {
            "handoff_generation": handoff["generation_status"],
            "handoff_schema": handoff["schema_validation_result"].get("handoff_schema_check_result"),
        },
        "stage_06_feedback_intake": {
            "feedback_validation": feedback_validation["validation_status"],
            "feedback_preview": feedback_preview["preview_status"],
            "feedback_classification": feedback_classification["classification_status"],
            "review_decision_adapter": decision_adapter["adapter_status"],
            "requested_commander_action": feedback_classification["requested_commander_action"],
        },
    }
    blockers = _loop_blockers(stage_results)
    return {
        "thin_loop_status": THIN_LOOP_PASSED if not blockers else THIN_LOOP_FAILED_CLOSED,
        "thin_loop_path": [
            "external_taskbook_import",
            "execution_envelope",
            "local_execution_receipt",
            "reviewer_handoff_package",
            "review_feedback_intake",
        ],
        "stage_results": stage_results,
        "blockers": blockers,
        "authority_boundary": {
            "thin_loop_result_is_authority": False,
            "thin_loop_authorizes_executor_dispatch": False,
            "thin_loop_creates_review_decision": False,
            "thin_loop_emits_gate_event": False,
            "thin_loop_writes_delivery_state": False,
        },
        "handoff_package_ref": {"handoff_package_id": handoff["reviewer_handoff_package"].get("handoff_package_id")},
        "receipt_refs": evidence_receipt["execution_receipt_refs"],
        "requested_commander_action": feedback_classification["requested_commander_action"],
        "delivery_state_accepted": False,
        "review_decision_created": False,
        "gate_event_emitted": False,
        "executor_dispatch_authorized": False,
    }


def run_stage_0_6_thin_governed_loop(inputs: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run the complete Stage 0-6 proof while preserving preview-only authority."""
    values = inputs or example_stage_3_6_inputs()
    anchors = verify_stage_0_2_governance_anchors(values.get("project_root") or Path.cwd())
    downstream = run_stage_3_6_thin_governed_loop(values)
    blockers = [*anchors["blockers"], *downstream["blockers"]]
    stage_results = {
        **anchors["stage_results"],
        **downstream["stage_results"],
    }
    result = dict(downstream)
    result.update(
        {
            "thin_loop_status": THIN_LOOP_PASSED if not blockers else THIN_LOOP_FAILED_CLOSED,
            "thin_loop_path": [
                "repository_runtime_baseline",
                "master_taskbook_anchor",
                "stage_taskbook_registry",
                *downstream["thin_loop_path"],
            ],
            "stage_results": stage_results,
            "blockers": blockers,
            "governance_anchors": {
                "read_only": anchors["read_only"],
                "side_effects": anchors["side_effects"],
                "master_taskbook_hash": anchors["stage_results"]["stage_01_master_anchor"]["master_hash"],
                "registered_stage_ids": anchors["stage_results"]["stage_02_stage_taskbook"]["registered_stage_ids"],
            },
        }
    )
    return result


def _loop_blockers(stage_results: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    expected = {
        ("stage_03_import", "external_validation"): VALIDATION_PASSED,
        ("stage_03_import", "import_preview"): IMPORT_PREVIEW_READY,
        ("stage_03_import", "version_candidate_mapping"): MAPPING_READY,
        ("stage_03_import", "adoption_preview"): ADOPTION_PREVIEW_READY,
        ("stage_04_execution_evidence", "execution_envelope"): ENVELOPE_CHECK_PASSED,
        ("stage_04_execution_evidence", "run_preview"): RUN_PREVIEW_READY,
        ("stage_04_execution_evidence", "local_receipt"): RECEIPT_CHECK_PASSED,
        ("stage_04_execution_evidence", "executor_report"): EXECUTOR_REPORT_READY,
        ("stage_04_execution_evidence", "evidence_receipt"): EVIDENCE_RECEIPT_READY,
        ("stage_04_execution_evidence", "audit_package_handoff_readiness"): READY_FOR_REVIEWER_HANDOFF,
        ("stage_05_reviewer_handoff", "handoff_generation"): HANDOFF_PACKAGE_GENERATED,
        ("stage_06_feedback_intake", "feedback_validation"): VALID_FOR_PREVIEW,
        ("stage_06_feedback_intake", "feedback_preview"): FEEDBACK_PREVIEW_AVAILABLE,
        ("stage_06_feedback_intake", "feedback_classification"): CLASSIFICATION_READY,
        ("stage_06_feedback_intake", "review_decision_adapter"): ADAPTER_STATUS_ADAPTED,
    }
    blockers: list[dict[str, Any]] = []
    for (stage, field), expected_value in expected.items():
        actual_value = stage_results.get(stage, {}).get(field)
        if actual_value != expected_value:
            blockers.append(
                {
                    "code": "thin_loop_stage_result_mismatch",
                    "stage": stage,
                    "field": field,
                    "expected": expected_value,
                    "actual": actual_value,
                }
            )
    return blockers


def _stable_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
