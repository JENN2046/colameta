from __future__ import annotations

from copy import deepcopy
from typing import Any

from runner.drift_evidence_schema import (
    AUTHORITY_BOUNDARY_EXPECTATIONS as DRIFT_EVIDENCE_AUTHORITY_BOUNDARY,
    DRIFT_EVIDENCE_SCHEMA_CHECK_PASSED,
    validate_drift_evidence_schema,
)
from runner.reviewer_alignment_questions import (
    ALIGNMENT_QUESTIONS_CHECK_PASSED,
    default_alignment_questions,
    validate_alignment_questions,
)
from runner.reviewer_drift_questions import (
    DRIFT_QUESTIONS_CHECK_PASSED,
    default_drift_questions,
    validate_drift_questions,
)


DRIFT_EVIDENCE_PACK_GENERATED = "drift_evidence_pack_generated"
DRIFT_EVIDENCE_PACK_FAILED_CLOSED = "drift_evidence_pack_failed_closed"
DRIFT_EVIDENCE_PACK_SCHEMA_VERSION = "drift_evidence_pack_builder.v1"
AUTHORITY_BOUNDARY_EXPECTATIONS = {
    "pack_builder_result_is_authority": False,
    "pack_builder_makes_semantic_drift_judgment": False,
    "pack_builder_answers_reviewer_questions": False,
    "pack_builder_creates_review_decision": False,
    "pack_builder_emits_gate_event": False,
    "pack_builder_writes_delivery_state": False,
    "pack_builder_mutates_plan": False,
    "pack_builder_rewrites_taskbook": False,
    "pack_builder_authorizes_executor_continuation": False,
    "pack_builder_commits_or_pushes": False,
}
FORBIDDEN_PACK_BUILDER_CLAIM_KEYS = frozenset(
    {
        "semantic_alignment_pass",
        "no_drift_confirmed",
        "review_decision_created",
        "review_decision_record_created",
        "gate_event_emitted",
        "delivery_state_accepted",
        "delivery_state_transitioned",
        "plan_mutated",
        "plan_mutation",
        "taskbook_rewritten",
        "taskbook_mutation_created",
        "master_goal_change",
        "master_goal_mutated",
        "executor_continuation_authorized",
        "commit_or_push",
        "stage_scope_expanded",
        "stage_scope_expansion",
        "plan_diff_created",
        "plan_patch_created",
        "apply_request_created",
        "commander_authorized_next_route",
        "pack_builder_result_is_authority",
        "pack_builder_makes_semantic_drift_judgment",
        "pack_builder_answers_reviewer_questions",
        "pack_builder_creates_review_decision",
        "pack_builder_emits_gate_event",
        "pack_builder_writes_delivery_state",
        "pack_builder_mutates_plan",
        "pack_builder_rewrites_taskbook",
        "pack_builder_authorizes_executor_continuation",
        "pack_builder_commits_or_pushes",
    }
)
FORBIDDEN_ACTIONABLE_OUTPUT_KEYS = frozenset(
    {
        "plan_diff",
        "plan_patch",
        "apply_request",
        "taskbook_mutation",
        "review_decision_record",
        "gate_event",
        "delivery_state_transition",
        "executor_continuation",
    }
)


class DriftEvidencePackBuilderError(ValueError):
    def __init__(self, error_code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.details = details or {}


def build_drift_evidence_pack(inputs: dict[str, Any] | None = None, **overrides: Any) -> dict[str, Any]:
    if inputs is not None and not isinstance(inputs, dict):
        pack: dict[str, Any] = {}
        schema_validation_result = validate_drift_evidence_schema(pack)
        result = _builder_result(
            pack=pack,
            schema_validation_result=schema_validation_result,
            alignment_questions_validation_result={},
            drift_questions_validation_result={},
            blockers=[_blocker("DRIFT_EVIDENCE_INPUTS_INVALID", "Builder inputs must be an object.", {})],
            known_conflicts=[],
        )
        assert_drift_evidence_pack_builder_result_contract(result)
        return result

    builder_inputs = deepcopy(inputs or {})
    builder_inputs.update(deepcopy(overrides))

    audit_package = _first_dict(
        builder_inputs.get("audit_package"),
        builder_inputs.get("stage_4_audit_package"),
        builder_inputs.get("audit_evidence"),
    )
    scope_evidence_pack = _first_dict(
        builder_inputs.get("scope_evidence_pack"),
        builder_inputs.get("scope_pack"),
        builder_inputs.get("scope_evidence_package"),
    )
    reviewer_handoff_package = _first_dict(
        builder_inputs.get("reviewer_handoff_package"),
        _nested_dict(builder_inputs.get("reviewer_handoff_result"), "reviewer_handoff_package"),
        _nested_dict(builder_inputs.get("handoff_result"), "reviewer_handoff_package"),
        builder_inputs.get("handoff_package"),
    )
    review_feedback = _first_dict(
        builder_inputs.get("review_feedback"),
        builder_inputs.get("review_evidence"),
        builder_inputs.get("stage_6_review_feedback"),
    )

    execution_evidence_ref = _first_evidence(
        builder_inputs.get("execution_evidence_ref"),
        audit_package.get("execution_evidence_receipt_ref"),
        audit_package.get("executor_report_ref"),
        reviewer_handoff_package.get("execution_receipt_refs"),
        review_feedback.get("execution_report_ref"),
    )
    changed_files = _first_list(
        builder_inputs.get("changed_files"),
        reviewer_handoff_package.get("changed_files"),
        _changed_files_from_scope(scope_evidence_pack),
    )
    validation_truth = _first_evidence(
        builder_inputs.get("validation_truth"),
        reviewer_handoff_package.get("validation_truth"),
        _validation_truth_from_audit_package(audit_package),
    )
    scope_evidence = _first_evidence(
        builder_inputs.get("scope_evidence"),
        reviewer_handoff_package.get("scope_evidence"),
        scope_evidence_pack,
    )
    forbidden_files_evidence = _first_evidence(
        builder_inputs.get("forbidden_files_evidence"),
        _forbidden_files_evidence_from_scope(scope_evidence_pack),
    )
    out_of_scope_evidence = _first_evidence(
        builder_inputs.get("out_of_scope_evidence"),
        _out_of_scope_evidence_from_scope(scope_evidence_pack),
    )
    known_gaps = _merge_structured_lists(
        builder_inputs.get("known_gaps"),
        audit_package.get("known_gaps"),
        scope_evidence_pack.get("known_gaps"),
        reviewer_handoff_package.get("known_gaps"),
    )
    remaining_risks = _merge_structured_lists(
        builder_inputs.get("remaining_risks"),
        audit_package.get("remaining_risks"),
        scope_evidence_pack.get("remaining_risks"),
        reviewer_handoff_package.get("known_risks"),
    )

    master_taskbook_ref = _first_dict(
        builder_inputs.get("master_taskbook_ref"),
        reviewer_handoff_package.get("master_taskbook_ref"),
        _hash_ref("PROJECT_MASTER_TASKBOOK.md", audit_package.get("master_taskbook_hash")),
        _hash_ref("PROJECT_MASTER_TASKBOOK.md", review_feedback.get("master_taskbook_hash")),
    )
    stage_taskbook_ref = _first_dict(
        builder_inputs.get("stage_taskbook_ref"),
        reviewer_handoff_package.get("stage_taskbook_ref"),
        _hash_ref("docs/taskbooks/stages/STAGE_07_DRIFT_EVIDENCE_AND_CORRECTION.md", audit_package.get("stage_taskbook_hash")),
        _hash_ref("docs/taskbooks/stages/STAGE_07_DRIFT_EVIDENCE_AND_CORRECTION.md", review_feedback.get("stage_taskbook_hash")),
    )
    version_taskbook_ref = _first_dict(
        builder_inputs.get("version_taskbook_ref"),
        reviewer_handoff_package.get("version_taskbook_ref"),
        audit_package.get("version_taskbook_ref"),
        review_feedback.get("version_taskbook_ref"),
    )

    evidence_refs = _source_evidence_refs(
        audit_package=audit_package,
        scope_evidence_pack=scope_evidence_pack,
        reviewer_handoff_package=reviewer_handoff_package,
        review_feedback=review_feedback,
        execution_evidence_ref=execution_evidence_ref,
    )
    target_refs = _target_refs(
        master_taskbook_ref=master_taskbook_ref,
        stage_taskbook_ref=stage_taskbook_ref,
        version_taskbook_ref=version_taskbook_ref,
        scope_evidence=scope_evidence,
        known_gaps=known_gaps,
        remaining_risks=remaining_risks,
    )

    master_goal_alignment_questions = _question_list_or_default(
        builder_inputs.get("master_goal_alignment_questions"),
        default_alignment_questions(target_refs, evidence_refs),
    )
    reviewer_drift_checklist = _question_list_or_default(
        builder_inputs.get("reviewer_drift_checklist"),
        default_drift_questions(evidence_refs),
    )
    plan_adjustment_trigger_conditions = _question_list_or_default(
        builder_inputs.get("plan_adjustment_trigger_conditions"),
        _default_plan_adjustment_trigger_conditions(review_feedback),
    )
    if _forbidden_actionable_outputs(
        {"plan_adjustment_trigger_conditions": plan_adjustment_trigger_conditions},
        "plan_adjustment_trigger_conditions_input",
    ):
        plan_adjustment_trigger_conditions = _default_plan_adjustment_trigger_conditions(review_feedback)

    pack = {
        "drift_evidence_pack_id": builder_inputs.get("drift_evidence_pack_id") or _default_pack_id(audit_package, reviewer_handoff_package),
        "drift_evidence_pack_schema_version": DRIFT_EVIDENCE_PACK_SCHEMA_VERSION,
        "master_taskbook_ref": master_taskbook_ref,
        "stage_taskbook_ref": stage_taskbook_ref,
        "version_taskbook_ref": version_taskbook_ref,
        "execution_evidence_ref": execution_evidence_ref,
        "changed_files": changed_files,
        "validation_truth": validation_truth,
        "scope_evidence": scope_evidence,
        "forbidden_files_evidence": forbidden_files_evidence,
        "out_of_scope_evidence": out_of_scope_evidence,
        "executor_drift_evidence": _executor_drift_evidence(
            execution_evidence_ref=execution_evidence_ref,
            changed_files=changed_files,
            validation_truth=validation_truth,
            forbidden_files_evidence=forbidden_files_evidence,
            out_of_scope_evidence=out_of_scope_evidence,
            audit_package=audit_package,
            evidence_refs=evidence_refs,
        ),
        "task_drift_evidence": _task_drift_evidence(
            version_taskbook_ref=version_taskbook_ref,
            scope_evidence=scope_evidence,
            changed_files=changed_files,
            known_gaps=known_gaps,
            remaining_risks=remaining_risks,
            review_feedback=review_feedback,
            evidence_refs=evidence_refs,
        ),
        "stage_drift_evidence": _stage_drift_evidence(
            master_taskbook_ref=master_taskbook_ref,
            stage_taskbook_ref=stage_taskbook_ref,
            audit_package=audit_package,
            reviewer_handoff_package=reviewer_handoff_package,
            review_feedback=review_feedback,
            evidence_refs=evidence_refs,
        ),
        "master_goal_alignment_questions": master_goal_alignment_questions,
        "reviewer_drift_checklist": reviewer_drift_checklist,
        "plan_adjustment_trigger_conditions": plan_adjustment_trigger_conditions,
        "source_evidence_refs": evidence_refs,
        "known_gaps": known_gaps,
        "remaining_risks": remaining_risks,
        "authority_boundary": dict(DRIFT_EVIDENCE_AUTHORITY_BOUNDARY),
        "semantic_alignment_pass": False,
        "no_drift_confirmed": False,
        "review_decision_created": False,
        "gate_event_emitted": False,
        "delivery_state_accepted": False,
        "plan_mutated": False,
        "taskbook_rewritten": False,
        "plan_diff_created": False,
        "plan_patch_created": False,
        "apply_request_created": False,
        "taskbook_mutation_created": False,
        "executor_continuation_authorized": False,
        "commit_or_push": False,
        "stage_scope_expanded": False,
        "semantic_drift_judgment": None,
    }

    alignment_questions_validation_result = validate_alignment_questions(master_goal_alignment_questions)
    drift_questions_validation_result = validate_drift_questions(reviewer_drift_checklist)
    schema_validation_result = validate_drift_evidence_schema(pack)
    blockers = _evidence_blockers(pack, builder_inputs)
    known_conflicts: list[dict[str, Any]] = []
    input_forbidden_claims = _forbidden_truthy_claims(builder_inputs, "builder_inputs")
    if input_forbidden_claims:
        blockers.append(
            _blocker(
                "FORBIDDEN_DRIFT_EVIDENCE_BUILDER_INPUT_CLAIM",
                "Builder inputs contain forbidden authority claims.",
                {"forbidden_claims": _safe_forbidden_claims(input_forbidden_claims)},
            )
        )
        known_conflicts.extend(
            {"conflict_type": "authority_boundary", "path": item["path"], "claim": item["key"]}
            for item in input_forbidden_claims
        )

    actionable_outputs = _forbidden_actionable_outputs(builder_inputs, "builder_inputs")
    if actionable_outputs:
        blockers.append(
            _blocker(
                "FORBIDDEN_PLAN_ADJUST_ACTIONABLE_OUTPUT",
                "Stage 7 drift evidence pack builder must not include plan diffs, patches, apply requests, or mutations.",
                {"forbidden_outputs": actionable_outputs},
            )
        )
        known_conflicts.extend(
            {"conflict_type": "forbidden_actionable_output", "path": item["path"], "key": item["key"]}
            for item in actionable_outputs
        )

    if alignment_questions_validation_result.get("alignment_questions_check_result") != ALIGNMENT_QUESTIONS_CHECK_PASSED:
        blockers.append(
            _blocker(
                "MASTER_GOAL_ALIGNMENT_QUESTIONS_INVALID",
                "Master goal alignment questions are not reviewer-ready.",
                {"rejection_reasons": alignment_questions_validation_result.get("rejection_reasons", [])},
            )
        )
    if drift_questions_validation_result.get("drift_questions_check_result") != DRIFT_QUESTIONS_CHECK_PASSED:
        blockers.append(
            _blocker(
                "REVIEWER_DRIFT_CHECKLIST_INVALID",
                "Reviewer drift checklist is not reviewer-ready.",
                {"rejection_reasons": drift_questions_validation_result.get("rejection_reasons", [])},
            )
        )
    if schema_validation_result.get("drift_evidence_schema_check_result") != DRIFT_EVIDENCE_SCHEMA_CHECK_PASSED:
        blockers.append(
            _blocker(
                "DRIFT_EVIDENCE_SCHEMA_VALIDATION_FAILED",
                "Generated drift evidence pack failed the v1.12 schema contract.",
                {
                    "rejected_fields": schema_validation_result.get("rejected_fields", []),
                    "rejection_reasons": schema_validation_result.get("rejection_reasons", []),
                },
            )
        )
        known_conflicts.extend(schema_validation_result.get("known_conflicts", []))

    result = _builder_result(
        pack=pack,
        schema_validation_result=schema_validation_result,
        alignment_questions_validation_result=alignment_questions_validation_result,
        drift_questions_validation_result=drift_questions_validation_result,
        blockers=blockers,
        known_conflicts=known_conflicts,
    )
    assert_drift_evidence_pack_builder_result_contract(result)
    return result


def assert_drift_evidence_pack_builder_result_contract(result: dict[str, Any]) -> None:
    if not isinstance(result, dict):
        raise DriftEvidencePackBuilderError("DRIFT_EVIDENCE_PACK_BUILDER_RESULT_INVALID", "Builder result must be an object.")
    status = result.get("pack_builder_status")
    if status not in {DRIFT_EVIDENCE_PACK_GENERATED, DRIFT_EVIDENCE_PACK_FAILED_CLOSED}:
        raise DriftEvidencePackBuilderError(
            "DRIFT_EVIDENCE_PACK_BUILDER_STATUS_INVALID",
            "Builder result status is unsupported.",
            details={"pack_builder_status": status},
        )
    blockers = _list_or_empty(result.get("failures_and_blockers"))
    if status == DRIFT_EVIDENCE_PACK_GENERATED and blockers:
        raise DriftEvidencePackBuilderError(
            "DRIFT_EVIDENCE_PACK_GENERATED_WITH_BLOCKERS",
            "Generated drift evidence pack result must not include blockers.",
            details={"blocker_codes": [item.get("code") for item in blockers if isinstance(item, dict)]},
        )
    if status == DRIFT_EVIDENCE_PACK_FAILED_CLOSED and not blockers:
        raise DriftEvidencePackBuilderError(
            "DRIFT_EVIDENCE_PACK_FAILED_WITHOUT_BLOCKERS",
            "Failed drift evidence pack result must include blocker codes.",
        )
    if result.get("authority_boundary") != AUTHORITY_BOUNDARY_EXPECTATIONS:
        raise DriftEvidencePackBuilderError(
            "FORBIDDEN_DRIFT_EVIDENCE_PACK_BUILDER_AUTHORITY_BOUNDARY",
            "Builder result authority boundary must remain false.",
            details={"expected": AUTHORITY_BOUNDARY_EXPECTATIONS, "actual": result.get("authority_boundary")},
        )
    forbidden_claims = _forbidden_truthy_claims(result, "builder_result")
    if forbidden_claims:
        raise DriftEvidencePackBuilderError(
            "FORBIDDEN_DRIFT_EVIDENCE_PACK_BUILDER_RESULT_CLAIM",
            "Builder result contains forbidden authority claims.",
            details={"forbidden_claims": _safe_forbidden_claims(forbidden_claims)},
        )
    actionable_outputs = _forbidden_actionable_outputs(result, "builder_result")
    if actionable_outputs:
        raise DriftEvidencePackBuilderError(
            "FORBIDDEN_DRIFT_EVIDENCE_PACK_BUILDER_ACTIONABLE_OUTPUT",
            "Builder result contains forbidden actionable outputs.",
            details={"forbidden_outputs": actionable_outputs},
        )


def drift_evidence_pack_builder_inventory() -> dict[str, Any]:
    return {
        "schema_version": DRIFT_EVIDENCE_PACK_SCHEMA_VERSION,
        "result_statuses": [DRIFT_EVIDENCE_PACK_GENERATED, DRIFT_EVIDENCE_PACK_FAILED_CLOSED],
        "authority_boundary": dict(AUTHORITY_BOUNDARY_EXPECTATIONS),
        "forbidden_actionable_outputs": sorted(FORBIDDEN_ACTIONABLE_OUTPUT_KEYS),
        "uses_drift_evidence_schema_validation": True,
        "creates_review_decision": False,
        "emits_gate_event": False,
        "mutates_plan": False,
        "continues_executor": False,
    }


def _builder_result(
    *,
    pack: dict[str, Any],
    schema_validation_result: dict[str, Any],
    alignment_questions_validation_result: dict[str, Any],
    drift_questions_validation_result: dict[str, Any],
    blockers: list[dict[str, Any]],
    known_conflicts: list[dict[str, Any]],
) -> dict[str, Any]:
    status = DRIFT_EVIDENCE_PACK_FAILED_CLOSED if blockers else DRIFT_EVIDENCE_PACK_GENERATED
    blocker_codes = [str(item.get("code")) for item in blockers if isinstance(item, dict) and item.get("code")]
    return {
        "pack_builder_status": status,
        "drift_evidence_pack_builder_status": status,
        "generation_status": status,
        "drift_evidence_pack": pack,
        "schema_validation_result": schema_validation_result,
        "alignment_questions_validation_result": alignment_questions_validation_result,
        "drift_questions_validation_result": drift_questions_validation_result,
        "missing_evidence_report": {
            "blocked_for_incomplete_evidence": bool(blockers),
            "blocker_codes": blocker_codes,
        },
        "failures_and_blockers": blockers,
        "known_conflicts": known_conflicts,
        "authority_boundary": dict(AUTHORITY_BOUNDARY_EXPECTATIONS),
        "semantic_alignment_pass": False,
        "no_drift_confirmed": False,
        "review_decision_created": False,
        "gate_event_emitted": False,
        "delivery_state_accepted": False,
        "plan_mutated": False,
        "taskbook_rewritten": False,
        "plan_diff_created": False,
        "plan_patch_created": False,
        "apply_request_created": False,
        "taskbook_mutation_created": False,
        "executor_continuation_authorized": False,
        "commit_or_push": False,
        "stage_scope_expanded": False,
        "semantic_drift_judgment": None,
    }


def _evidence_blockers(pack: dict[str, Any], builder_inputs: dict[str, Any]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    required_checks = (
        ("drift_evidence_pack_id", "DRIFT_EVIDENCE_PACK_ID_MISSING", _not_empty),
        ("master_taskbook_ref", "MASTER_TASKBOOK_REF_MISSING", _non_empty_dict),
        ("stage_taskbook_ref", "STAGE_TASKBOOK_REF_MISSING", _non_empty_dict),
        ("version_taskbook_ref", "VERSION_TASKBOOK_REF_MISSING", _non_empty_dict),
        ("execution_evidence_ref", "EXECUTION_EVIDENCE_REF_MISSING", _evidence_present),
        ("changed_files", "CHANGED_FILES_MISSING", _changed_files_present),
        ("validation_truth", "VALIDATION_TRUTH_MISSING", _evidence_present),
        ("scope_evidence", "SCOPE_EVIDENCE_MISSING", _evidence_present),
        ("forbidden_files_evidence", "FORBIDDEN_FILES_EVIDENCE_MISSING", _evidence_present),
        ("out_of_scope_evidence", "OUT_OF_SCOPE_EVIDENCE_MISSING", _evidence_present),
        ("master_goal_alignment_questions", "MASTER_GOAL_ALIGNMENT_QUESTIONS_MISSING", _structured_list),
        ("reviewer_drift_checklist", "REVIEWER_DRIFT_CHECKLIST_MISSING", _structured_list),
        ("plan_adjustment_trigger_conditions", "PLAN_ADJUSTMENT_TRIGGER_CONDITIONS_MISSING", _structured_list),
    )
    for field, code, predicate in required_checks:
        if not predicate(pack.get(field)):
            blockers.append(_blocker(code, f"{field} is required to build a drift evidence pack.", {"field": field}))

    for field in ("known_gaps", "remaining_risks"):
        if field in builder_inputs and not isinstance(builder_inputs.get(field), list):
            blockers.append(_blocker(f"{field.upper()}_INVALID", f"{field} must be a list when supplied.", {"field": field}))
    return blockers


def _executor_drift_evidence(
    *,
    execution_evidence_ref: Any,
    changed_files: list[Any],
    validation_truth: Any,
    forbidden_files_evidence: Any,
    out_of_scope_evidence: Any,
    audit_package: dict[str, Any],
    evidence_refs: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "section_id": "executor_drift_evidence",
        "purpose": "Expose executor-side drift evidence for reviewer judgment only.",
        "execution_evidence_ref": execution_evidence_ref,
        "executor_report_ref": _dict_or_none(audit_package.get("executor_report_ref")),
        "changed_files": changed_files,
        "validation_truth": validation_truth,
        "forbidden_files_evidence": forbidden_files_evidence,
        "out_of_scope_evidence": out_of_scope_evidence,
        "observed_evidence_refs": evidence_refs,
        "reviewer_answer": None,
        "semantic_drift_judgment": None,
    }


def _task_drift_evidence(
    *,
    version_taskbook_ref: dict[str, Any],
    scope_evidence: Any,
    changed_files: list[Any],
    known_gaps: list[dict[str, Any]],
    remaining_risks: list[dict[str, Any]],
    review_feedback: dict[str, Any],
    evidence_refs: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "section_id": "task_drift_evidence",
        "purpose": "Expose version-task drift evidence without deciding alignment.",
        "version_taskbook_ref": version_taskbook_ref,
        "scope_evidence": scope_evidence,
        "changed_files": changed_files,
        "known_gaps": known_gaps,
        "remaining_risks": remaining_risks,
        "review_feedback_ref": _review_feedback_ref(review_feedback),
        "review_feedback_decision_value": review_feedback.get("review_decision_value"),
        "task_completion_evidence": review_feedback.get("task_completion"),
        "scope_assessment_evidence": review_feedback.get("scope_assessment"),
        "observed_evidence_refs": evidence_refs,
        "reviewer_answer": None,
        "semantic_drift_judgment": None,
    }


def _stage_drift_evidence(
    *,
    master_taskbook_ref: dict[str, Any],
    stage_taskbook_ref: dict[str, Any],
    audit_package: dict[str, Any],
    reviewer_handoff_package: dict[str, Any],
    review_feedback: dict[str, Any],
    evidence_refs: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "section_id": "stage_drift_evidence",
        "purpose": "Expose stage-level drift evidence without stage completion or plan authority.",
        "master_taskbook_ref": master_taskbook_ref,
        "stage_taskbook_ref": stage_taskbook_ref,
        "master_taskbook_hash": audit_package.get("master_taskbook_hash") or review_feedback.get("master_taskbook_hash"),
        "stage_taskbook_hash": audit_package.get("stage_taskbook_hash") or review_feedback.get("stage_taskbook_hash"),
        "handoff_readiness": audit_package.get("handoff_readiness"),
        "handoff_package_ref": _handoff_ref(reviewer_handoff_package),
        "review_feedback_ref": _review_feedback_ref(review_feedback),
        "review_feedback_decision_value": review_feedback.get("review_decision_value"),
        "observed_evidence_refs": evidence_refs,
        "reviewer_answer": None,
        "stage_scope_expanded": False,
        "semantic_drift_judgment": None,
    }


def _default_plan_adjustment_trigger_conditions(review_feedback: dict[str, Any]) -> list[dict[str, Any]]:
    decision_value = review_feedback.get("review_decision_value")
    return [
        {
            "trigger_condition_id": "plan_adjust_if_reviewer_decision_is_plan_adjust",
            "condition_text": "If Reviewer decision is PLAN_ADJUST, route only to Stage 8 plan adjustment preview.",
            "source_review_decision_value": decision_value,
            "stage_8_preview_required": True,
            "forbidden_outputs": [
                "plan_diff",
                "plan_patch",
                "apply_request",
                "taskbook_mutation",
            ],
            "plan_diff_created": False,
            "plan_patch_created": False,
            "apply_request_created": False,
            "taskbook_mutation_created": False,
            "plan_mutated": False,
        },
        {
            "trigger_condition_id": "plan_adjust_if_reviewer_marks_drift_or_unclear_alignment",
            "condition_text": "If Reviewer records drift visible or unclear alignment, Stage 8 preview is required before any plan change.",
            "stage_8_preview_required": True,
            "forbidden_outputs": [
                "automatic_semantic_drift_judgment",
                "automatic_taskbook_rewrite",
                "stage_scope_expansion",
            ],
            "plan_diff_created": False,
            "plan_patch_created": False,
            "apply_request_created": False,
            "taskbook_mutation_created": False,
            "plan_mutated": False,
        },
    ]


def _source_evidence_refs(
    *,
    audit_package: dict[str, Any],
    scope_evidence_pack: dict[str, Any],
    reviewer_handoff_package: dict[str, Any],
    review_feedback: dict[str, Any],
    execution_evidence_ref: Any,
) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    if audit_package:
        refs.append({"source": "stage_4_audit_package", "evidence_id": audit_package.get("audit_package_id", "audit_package")})
    if scope_evidence_pack:
        refs.append({"source": "scope_evidence_pack", "evidence_id": scope_evidence_pack.get("scope_pack_id", "scope_evidence_pack")})
    if reviewer_handoff_package:
        refs.append({"source": "reviewer_handoff_package", "evidence_id": reviewer_handoff_package.get("handoff_package_id", "handoff_package")})
    if review_feedback:
        refs.append({"source": "review_feedback", "evidence_id": review_feedback.get("review_feedback_id", "review_feedback")})
    if _evidence_present(execution_evidence_ref):
        refs.append({"source": "execution_evidence_ref", "evidence_ref": execution_evidence_ref})
    return refs


def _target_refs(
    *,
    master_taskbook_ref: dict[str, Any],
    stage_taskbook_ref: dict[str, Any],
    version_taskbook_ref: dict[str, Any],
    scope_evidence: Any,
    known_gaps: list[dict[str, Any]],
    remaining_risks: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "project_final_goal_alignment": master_taskbook_ref,
        "stage_goal_alignment": stage_taskbook_ref,
        "version_task_goal_alignment": version_taskbook_ref,
        "scope_alignment": {"scope_evidence": scope_evidence},
        "evidence_alignment": {
            "master_taskbook_ref": master_taskbook_ref,
            "stage_taskbook_ref": stage_taskbook_ref,
            "version_taskbook_ref": version_taskbook_ref,
        },
        "risk_alignment": {"known_gaps": known_gaps, "remaining_risks": remaining_risks},
    }


def _validation_truth_from_audit_package(audit_package: dict[str, Any]) -> dict[str, Any]:
    if not audit_package:
        return {}
    result: dict[str, Any] = {}
    if _non_empty_dict(audit_package.get("validation_truth_summary_ref")):
        result["validation_truth_summary_ref"] = deepcopy(audit_package.get("validation_truth_summary_ref"))
    if isinstance(audit_package.get("validation_truth_statuses"), list):
        result["validation_truth_statuses"] = deepcopy(audit_package.get("validation_truth_statuses"))
    return result


def _forbidden_files_evidence_from_scope(scope_evidence_pack: dict[str, Any]) -> dict[str, Any]:
    if not scope_evidence_pack:
        return {}
    violations = _list_or_empty(scope_evidence_pack.get("scope_violations"))
    return {
        "source": "scope_evidence_pack",
        "scope_pack_ref": _scope_pack_ref(scope_evidence_pack),
        "forbidden_files": _list_or_empty(scope_evidence_pack.get("forbidden_files")),
        "forbidden_files_touched": [
            deepcopy(item)
            for item in violations
            if isinstance(item, dict) and item.get("violation_type") == "forbidden_file_touched"
        ],
    }


def _out_of_scope_evidence_from_scope(scope_evidence_pack: dict[str, Any]) -> dict[str, Any]:
    if not scope_evidence_pack:
        return {}
    violations = _list_or_empty(scope_evidence_pack.get("scope_violations"))
    return {
        "source": "scope_evidence_pack",
        "scope_pack_ref": _scope_pack_ref(scope_evidence_pack),
        "scope_result": scope_evidence_pack.get("scope_result"),
        "scope_violations": deepcopy(violations),
        "outside_allowed_files": [
            deepcopy(item)
            for item in violations
            if isinstance(item, dict) and item.get("violation_type") == "outside_allowed_files"
        ],
    }


def _changed_files_from_scope(scope_evidence_pack: dict[str, Any]) -> list[Any]:
    if not scope_evidence_pack:
        return []
    return _dedupe(
        _string_list(scope_evidence_pack.get("observed_touched_files"))
        + _string_list(scope_evidence_pack.get("generated_files"))
        + _mutation_paths(scope_evidence_pack.get("observed_mutations"))
    )


def _default_pack_id(audit_package: dict[str, Any], reviewer_handoff_package: dict[str, Any]) -> str:
    if reviewer_handoff_package.get("handoff_package_id"):
        return f"drift-evidence-{reviewer_handoff_package['handoff_package_id']}"
    if audit_package.get("audit_package_id"):
        return f"drift-evidence-{audit_package['audit_package_id']}"
    return "drift-evidence-pack"


def _scope_pack_ref(scope_evidence_pack: dict[str, Any]) -> dict[str, Any]:
    if not scope_evidence_pack:
        return {}
    return {"scope_pack_id": scope_evidence_pack.get("scope_pack_id")}


def _handoff_ref(reviewer_handoff_package: dict[str, Any]) -> dict[str, Any]:
    if not reviewer_handoff_package:
        return {}
    return {"handoff_package_id": reviewer_handoff_package.get("handoff_package_id")}


def _review_feedback_ref(review_feedback: dict[str, Any]) -> dict[str, Any]:
    if not review_feedback:
        return {}
    return {"review_feedback_id": review_feedback.get("review_feedback_id")}


def _hash_ref(path: str, hash_value: Any) -> dict[str, Any]:
    if not isinstance(hash_value, str) or not hash_value.strip():
        return {}
    return {"path": path, "sha256": hash_value}


def _first_dict(*values: Any) -> dict[str, Any]:
    for value in values:
        if _non_empty_dict(value):
            return deepcopy(value)
    return {}


def _first_list(*values: Any) -> list[Any]:
    for value in values:
        if isinstance(value, list) and value:
            return deepcopy(value)
    return []


def _first_evidence(*values: Any) -> Any:
    for value in values:
        if _evidence_present(value):
            return deepcopy(value)
    return {}


def _nested_dict(value: Any, key: str) -> dict[str, Any]:
    if isinstance(value, dict) and isinstance(value.get(key), dict):
        return value[key]
    return {}


def _question_list_or_default(value: Any, default: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(value, list) and value:
        return deepcopy(value)
    return deepcopy(default)


def _merge_structured_lists(*values: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, list):
            continue
        for item in value:
            if not isinstance(item, dict):
                continue
            copied = deepcopy(item)
            marker = repr(sorted(copied.items()))
            if marker in seen:
                continue
            seen.add(marker)
            result.append(copied)
    return result


def _non_empty_dict(value: Any) -> bool:
    return isinstance(value, dict) and bool(value)


def _structured_list(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(item, dict) and bool(item) for item in value)


def _evidence_present(value: Any) -> bool:
    return _non_empty_dict(value) or _structured_list(value)


def _changed_files_present(value: Any) -> bool:
    if not isinstance(value, list) or not value:
        return False
    return all((isinstance(item, str) and item.strip()) or (isinstance(item, dict) and item) for item in value)


def _not_empty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value)
    return True


def _empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict)):
        return len(value) == 0
    return False


def _dict_or_none(value: Any) -> dict[str, Any] | None:
    return deepcopy(value) if isinstance(value, dict) and value else None


def _list_or_empty(value: Any) -> list[Any]:
    return deepcopy(value) if isinstance(value, list) else []


def _string_list(value: Any) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _mutation_paths(value: Any) -> list[str]:
    paths: list[str] = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict) and isinstance(item.get("path"), str):
                paths.append(item["path"])
    return paths


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _blocker(code: str, message: str, details: dict[str, Any]) -> dict[str, Any]:
    return {"code": code, "message": message, "details": details, "blocking": True}


def _forbidden_truthy_claims(value: Any, path: str = "builder") -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if str(key) in FORBIDDEN_PACK_BUILDER_CLAIM_KEYS and _truthy_claim(child):
                claims.append({"path": child_path, "key": str(key)})
            claims.extend(_forbidden_truthy_claims(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            claims.extend(_forbidden_truthy_claims(child, f"{path}[{index}]"))
    return claims


def _forbidden_actionable_outputs(value: Any, path: str) -> list[dict[str, str]]:
    outputs: list[dict[str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if str(key) in FORBIDDEN_ACTIONABLE_OUTPUT_KEYS and not _empty(child):
                outputs.append({"path": child_path, "key": str(key)})
            outputs.extend(_forbidden_actionable_outputs(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            outputs.extend(_forbidden_actionable_outputs(child, f"{path}[{index}]"))
    return outputs


def _safe_forbidden_claims(claims: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [{"path": str(item["path"]), "key": str(item["key"])} for item in claims]


def _truthy_claim(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {
            "true",
            "yes",
            "accepted",
            "accept",
            "created",
            "authorized",
            "confirmed",
            "executed",
            "emitted",
            "mutated",
            "rewritten",
            "expanded",
            "pass",
            "passed",
        }
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value != 0
    return False
