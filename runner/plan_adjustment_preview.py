from __future__ import annotations

from copy import deepcopy
from typing import Any


PLAN_ADJUSTMENT_PREVIEW_AVAILABLE = "plan_adjustment_preview_available"
PLAN_ADJUSTMENT_PREVIEW_FAILED_CLOSED = "plan_adjustment_preview_failed_closed"
PLAN_ADJUSTMENT_PREVIEW_SCHEMA_VERSION = "plan_adjustment_request_preview.v1"
PLAN_ADJUST_COMMANDER_ACTION = "ask_whether_to_prepare_plan_adjustment_draft"
PLAN_ADJUST_REVIEW_DECISION_VALUE = "PLAN_ADJUST"
PLAN_ADJUST_CLASSIFICATION = "plan_adjust_review_feedback"

FORBIDDEN_PLAN_ADJUSTMENT_CLAIM_KEYS = frozenset(
    {
        "apply_allowed",
        "plan_mutated",
        "master_goal_mutated",
        "reviewer_bypassed",
        "review_decision_created",
        "gate_event_emitted",
        "executor_continuation_authorized",
        "commit_or_push",
        "route_transitioned",
        "delivery_state_accepted",
    }
)
REQUIRED_PREVIEW_FIELDS = (
    "source_refs",
    "master_taskbook_ref",
    "master_taskbook_hash",
    "affected_stage_refs",
    "affected_version_refs",
    "proposed_change_summary",
    "proposed_diff_or_patch_preview",
    "continued_master_goal_service_explanation",
)
MASTER_TASKBOOK_PATHS = frozenset({"PROJECT_MASTER_TASKBOOK.md", "PROJECT_MASTER_TASKBOOK.zh-CN.md"})
MASTER_GOAL_MARKERS = frozenset(
    {
        "master_goal",
        "master-goal",
        "project_final_goal",
        "final_goal",
        "/master/goal",
        "/project/final_goal",
    }
)
NON_AUTHORITY_NOTICE = {
    "preview_does_not_apply_change": True,
    "preview_does_not_mutate_plan": True,
    "preview_does_not_mutate_master_goal": True,
    "preview_does_not_bypass_reviewer": True,
    "preview_does_not_create_review_decision": True,
    "preview_does_not_emit_gate_event": True,
    "preview_does_not_authorize_executor_continuation": True,
    "preview_does_not_commit_or_push": True,
    "preview_does_not_transition_route": True,
    "preview_does_not_accept_delivery_state": True,
}


class PlanAdjustmentPreviewError(ValueError):
    def __init__(self, error_code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.details = details or {}


def build_plan_adjustment_preview(inputs: dict[str, Any] | None = None, **overrides: Any) -> dict[str, Any]:
    if inputs is not None and not isinstance(inputs, dict):
        result = _failed_preview(
            [_reason("PLAN_ADJUSTMENT_INPUT_INVALID", "Plan adjustment preview inputs must be an object.", {})]
        )
        assert_plan_adjustment_preview_contract(result)
        return result

    builder_inputs = deepcopy(inputs or {})
    builder_inputs.update(deepcopy(overrides))

    forbidden_claims = _forbidden_truthy_claims(builder_inputs, "inputs")
    if forbidden_claims:
        result = _failed_preview(
            [
                _reason(
                    "FORBIDDEN_PLAN_ADJUSTMENT_AUTHORITY_CLAIM",
                    "Plan adjustment preview input contains forbidden authority claims.",
                    {"forbidden_claims": forbidden_claims},
                )
            ]
        )
        assert_plan_adjustment_preview_contract(result)
        return result

    source = _source_object(builder_inputs)
    orientation = _plan_adjust_orientation(source)
    source_refs = _source_refs(builder_inputs, source)
    master_taskbook_ref = _ref_or_empty(
        builder_inputs.get("master_taskbook_ref"),
        source.get("master_taskbook_ref"),
    )
    master_taskbook_hash = _first_non_empty(
        builder_inputs.get("master_taskbook_hash"),
        master_taskbook_ref.get("sha256"),
        master_taskbook_ref.get("raw_snapshot_sha256"),
        master_taskbook_ref.get("hash"),
        source.get("master_taskbook_hash"),
        source.get("master_taskbook_sha256"),
    )
    affected_stage_refs = _structured_list(
        builder_inputs.get("affected_stage_refs"),
        builder_inputs.get("affected_stage_taskbook_refs"),
        builder_inputs.get("stage_taskbook_refs"),
        builder_inputs.get("stage_taskbook_ref"),
        source.get("affected_stage_refs"),
        source.get("affected_stage_taskbook_refs"),
        source.get("stage_taskbook_ref"),
    )
    affected_version_refs = _structured_list(
        builder_inputs.get("affected_version_refs"),
        builder_inputs.get("affected_version_taskbook_refs"),
        builder_inputs.get("version_taskbook_refs"),
        builder_inputs.get("version_taskbook_ref"),
        source.get("affected_version_refs"),
        source.get("affected_version_taskbook_refs"),
        source.get("version_taskbook_ref"),
    )
    drift_evidence_ref = _optional_ref(builder_inputs.get("drift_evidence_ref"), source.get("drift_evidence_ref"))
    proposed_change_summary = _first_present(
        builder_inputs.get("proposed_change_summary"),
        source.get("proposed_change_summary"),
    )
    proposed_diff_or_patch_preview = _first_present(
        builder_inputs.get("proposed_diff_or_patch_preview"),
        builder_inputs.get("proposed_patch_preview"),
        builder_inputs.get("proposed_diff_preview"),
        source.get("proposed_diff_or_patch_preview"),
        source.get("proposed_patch_preview"),
        source.get("proposed_diff_preview"),
    )
    continued_master_goal_service_explanation = _first_present(
        builder_inputs.get("continued_master_goal_service_explanation"),
        source.get("continued_master_goal_service_explanation"),
    )

    errors = []
    if not orientation["is_plan_adjust_oriented"]:
        errors.append(
            _reason(
                "PLAN_ADJUST_SOURCE_REQUIRED",
                "Plan adjustment preview requires a PLAN_ADJUST-oriented source.",
                {"source_orientation": orientation},
            )
        )
    if orientation["conflicts"]:
        errors.append(
            _reason(
                "PLAN_ADJUST_SOURCE_CONFLICT",
                "Plan adjustment preview source contains conflicting non-PLAN_ADJUST indicators.",
                {"source_orientation": orientation},
            )
        )
    if source.get("request_status") and source.get("request_status") != "commander_decision_request_available":
        errors.append(
            _reason(
                "COMMANDER_DECISION_REQUEST_NOT_AVAILABLE",
                "CommanderDecisionRequest source must be available.",
                {"request_status": source.get("request_status")},
            )
        )

    required_values = {
        "source_refs": source_refs,
        "master_taskbook_ref": master_taskbook_ref,
        "master_taskbook_hash": master_taskbook_hash,
        "affected_stage_refs": affected_stage_refs,
        "affected_version_refs": affected_version_refs,
        "proposed_change_summary": proposed_change_summary,
        "proposed_diff_or_patch_preview": proposed_diff_or_patch_preview,
        "continued_master_goal_service_explanation": continued_master_goal_service_explanation,
    }
    missing = [field for field, value in required_values.items() if _is_empty(value)]
    if missing:
        errors.append(
            _reason(
                "PLAN_ADJUSTMENT_REQUIRED_FIELD_MISSING",
                "Plan adjustment preview is missing required binding or preview fields.",
                {"missing_fields": missing},
            )
        )

    if errors:
        result = _failed_preview(errors)
        assert_plan_adjustment_preview_contract(result)
        return result

    hard_gate_check = _commander_hard_gate_check(proposed_diff_or_patch_preview)
    preview = {
        "preview_status": PLAN_ADJUSTMENT_PREVIEW_AVAILABLE,
        "request_schema_version": PLAN_ADJUSTMENT_PREVIEW_SCHEMA_VERSION,
        "plan_adjustment_request_id": _request_id(source, source_refs),
        "source_orientation": orientation,
        "source_refs": source_refs,
        "master_taskbook_ref": deepcopy(master_taskbook_ref),
        "master_taskbook_hash": master_taskbook_hash,
        "affected_stage_refs": deepcopy(affected_stage_refs),
        "affected_version_refs": deepcopy(affected_version_refs),
        "drift_evidence_ref": deepcopy(drift_evidence_ref),
        "proposed_change_summary": deepcopy(proposed_change_summary),
        "proposed_diff_or_patch_preview": deepcopy(proposed_diff_or_patch_preview),
        "continued_master_goal_service_explanation": deepcopy(continued_master_goal_service_explanation),
        "commander_hard_gate_required": hard_gate_check["commander_hard_gate_required"],
        "commander_hard_gate_reasons": hard_gate_check["commander_hard_gate_reasons"],
        "apply_gate_status": {
            "apply_allowed": False,
            "apply_blocked_reason": "preview_only_requires_separate_commander_authorization_and_apply_route",
            "commander_hard_gate_required": hard_gate_check["commander_hard_gate_required"],
        },
        "forbidden_side_effects": _forbidden_side_effects_false(),
        "non_authority_notice": dict(NON_AUTHORITY_NOTICE),
        "validation_errors": [],
        "apply_allowed": False,
        "plan_mutated": False,
        "master_goal_mutated": False,
        "reviewer_bypassed": False,
        "review_decision_created": False,
        "gate_event_emitted": False,
        "executor_continuation_authorized": False,
        "commit_or_push": False,
        "route_transitioned": False,
        "delivery_state_accepted": False,
    }
    assert_plan_adjustment_preview_contract(preview)
    return preview


def assert_plan_adjustment_preview_contract(result: dict[str, Any]) -> None:
    if not isinstance(result, dict):
        raise PlanAdjustmentPreviewError("PLAN_ADJUSTMENT_PREVIEW_RESULT_INVALID", "Plan adjustment preview result must be an object.")
    if result.get("preview_status") not in {PLAN_ADJUSTMENT_PREVIEW_AVAILABLE, PLAN_ADJUSTMENT_PREVIEW_FAILED_CLOSED}:
        raise PlanAdjustmentPreviewError(
            "PLAN_ADJUSTMENT_PREVIEW_STATUS_INVALID",
            "Plan adjustment preview result contains an unsupported preview_status.",
            details={"preview_status": result.get("preview_status")},
        )

    forbidden = _forbidden_truthy_claims(result, "plan_adjustment_preview")
    if forbidden:
        raise PlanAdjustmentPreviewError(
            "FORBIDDEN_PLAN_ADJUSTMENT_PREVIEW_CLAIM",
            "Plan adjustment preview result contains forbidden authority claims.",
            details={"forbidden_claims": forbidden},
        )

    missing_notice = [key for key, expected in NON_AUTHORITY_NOTICE.items() if result.get("non_authority_notice", {}).get(key) != expected]
    if missing_notice:
        raise PlanAdjustmentPreviewError(
            "PLAN_ADJUSTMENT_PREVIEW_NOTICE_MISSING",
            "Plan adjustment preview result is missing non-authority notices.",
            details={"missing_notice": missing_notice},
        )

    if result.get("preview_status") == PLAN_ADJUSTMENT_PREVIEW_AVAILABLE:
        missing = [field for field in REQUIRED_PREVIEW_FIELDS if _is_empty(result.get(field))]
        if missing:
            raise PlanAdjustmentPreviewError(
                "PLAN_ADJUSTMENT_PREVIEW_FIELD_MISSING",
                "Available plan adjustment preview is missing required fields.",
                details={"missing_fields": missing},
            )
        if result.get("apply_allowed") is not False or result.get("apply_gate_status", {}).get("apply_allowed") is not False:
            raise PlanAdjustmentPreviewError(
                "PLAN_ADJUSTMENT_PREVIEW_APPLY_ALLOWED",
                "Plan adjustment preview must keep apply_allowed false.",
            )
        hard_gate_check = _commander_hard_gate_check(result.get("proposed_diff_or_patch_preview"))
        if hard_gate_check["commander_hard_gate_required"] and result.get("commander_hard_gate_required") is not True:
            raise PlanAdjustmentPreviewError(
                "PLAN_ADJUSTMENT_PREVIEW_MASTER_GATE_MISSING",
                "Preview touching a master taskbook or master-goal field must require Commander hard gate.",
                details=hard_gate_check,
            )


def plan_adjustment_preview_inventory() -> dict[str, Any]:
    return {
        "request_schema_version": PLAN_ADJUSTMENT_PREVIEW_SCHEMA_VERSION,
        "accepted_source_indicators": {
            "source_review_decision_value": PLAN_ADJUST_REVIEW_DECISION_VALUE,
            "normalized_review_decision_value": PLAN_ADJUST_REVIEW_DECISION_VALUE,
            "normalized_classification": PLAN_ADJUST_CLASSIFICATION,
            "requested_commander_action": PLAN_ADJUST_COMMANDER_ACTION,
        },
        "required_fields": list(REQUIRED_PREVIEW_FIELDS),
        "optional_fields": ["drift_evidence_ref"],
        "forbidden_claim_keys": sorted(FORBIDDEN_PLAN_ADJUSTMENT_CLAIM_KEYS),
        "preview_only_boundaries": {
            "apply_allowed": False,
            "plan_mutated": False,
            "master_goal_mutated": False,
            "reviewer_bypassed": False,
            "review_decision_created": False,
            "gate_event_emitted": False,
            "executor_continuation_authorized": False,
            "commit_or_push": False,
            "route_transitioned": False,
            "delivery_state_accepted": False,
        },
    }


def _source_object(inputs: dict[str, Any]) -> dict[str, Any]:
    return _first_dict(
        inputs.get("commander_decision_request"),
        inputs.get("source_commander_decision_request"),
        inputs.get("plan_adjust_source"),
        inputs.get("source"),
        inputs,
    )


def _plan_adjust_orientation(source: dict[str, Any]) -> dict[str, Any]:
    checks = []
    conflicts = []
    indicators = (
        ("requested_commander_action", PLAN_ADJUST_COMMANDER_ACTION),
        ("source_review_decision_value", PLAN_ADJUST_REVIEW_DECISION_VALUE),
        ("normalized_review_decision_value", PLAN_ADJUST_REVIEW_DECISION_VALUE),
        ("review_decision_value", PLAN_ADJUST_REVIEW_DECISION_VALUE),
        ("normalized_classification", PLAN_ADJUST_CLASSIFICATION),
    )
    for field, expected in indicators:
        value = source.get(field)
        if value in (None, "", []):
            continue
        matches = value == expected
        row = {"field": field, "value": value, "expected": expected, "matches_plan_adjust": matches}
        checks.append(row)
        if not matches:
            conflicts.append(row)
    return {
        "is_plan_adjust_oriented": bool(checks) and not conflicts,
        "checks": checks,
        "conflicts": conflicts,
    }


def _source_refs(inputs: dict[str, Any], source: dict[str, Any]) -> list[dict[str, Any]]:
    explicit_refs = _structured_list(
        inputs.get("source_refs"),
        inputs.get("source_ref"),
        source.get("source_refs"),
        source.get("source_ref"),
    )
    derived_refs = _structured_list(
        _id_ref("commander_decision_request_id", source.get("commander_decision_request_id")),
        source.get("source_review_feedback_ref"),
        source.get("reviewer_handoff_package_ref"),
        source.get("version_taskbook_ref"),
        source.get("execution_report_ref"),
        source.get("workspace_snapshot_ref"),
    )
    return _dedupe_refs([*explicit_refs, *derived_refs])


def _commander_hard_gate_check(proposed_diff_or_patch_preview: Any) -> dict[str, Any]:
    touches = _touched_master_gate_markers(proposed_diff_or_patch_preview, "proposed_diff_or_patch_preview")
    return {
        "commander_hard_gate_required": bool(touches),
        "commander_hard_gate_reasons": touches,
    }


def _touched_master_gate_markers(value: Any, path: str) -> list[dict[str, str]]:
    touches: list[dict[str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            key_text = str(key)
            marker = _master_goal_marker_or_none(key_text)
            if marker:
                touches.append({"path": child_path, "reason": "master_goal_field", "marker": marker})
            touches.extend(_touched_master_gate_markers(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            touches.extend(_touched_master_gate_markers(child, f"{path}[{index}]"))
    elif isinstance(value, str):
        for master_path in sorted(MASTER_TASKBOOK_PATHS):
            if master_path in value:
                touches.append({"path": path, "reason": "master_taskbook_path", "marker": master_path})
        marker = _master_goal_marker_or_none(value)
        if marker:
            touches.append({"path": path, "reason": "master_goal_field", "marker": marker})
    return _dedupe_touch_rows(touches)


def _master_goal_marker_or_none(value: str) -> str | None:
    normalized = value.strip().lower().replace(" ", "_")
    for marker in sorted(MASTER_GOAL_MARKERS):
        if marker in normalized:
            return marker
    return None


def _failed_preview(errors: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "preview_status": PLAN_ADJUSTMENT_PREVIEW_FAILED_CLOSED,
        "request_schema_version": PLAN_ADJUSTMENT_PREVIEW_SCHEMA_VERSION,
        "plan_adjustment_request_id": None,
        "validation_errors": errors,
        "forbidden_side_effects": _forbidden_side_effects_false(),
        "non_authority_notice": dict(NON_AUTHORITY_NOTICE),
        "apply_allowed": False,
        "plan_mutated": False,
        "master_goal_mutated": False,
        "reviewer_bypassed": False,
        "review_decision_created": False,
        "gate_event_emitted": False,
        "executor_continuation_authorized": False,
        "commit_or_push": False,
        "route_transitioned": False,
        "delivery_state_accepted": False,
    }


def _forbidden_side_effects_false() -> dict[str, bool]:
    return {key: False for key in sorted(FORBIDDEN_PLAN_ADJUSTMENT_CLAIM_KEYS)}


def _forbidden_truthy_claims(value: Any, path: str) -> list[dict[str, str]]:
    claims: list[dict[str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if str(key) in FORBIDDEN_PLAN_ADJUSTMENT_CLAIM_KEYS and _truthy_claim(child):
                claims.append({"path": child_path, "key": str(key)})
            claims.extend(_forbidden_truthy_claims(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            claims.extend(_forbidden_truthy_claims(child, f"{path}[{index}]"))
    return claims


def _truthy_claim(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {
            "true",
            "yes",
            "accepted",
            "created",
            "authorized",
            "executed",
            "applied",
            "mutated",
            "transitioned",
        }
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value != 0
    return False


def _request_id(source: dict[str, Any], source_refs: list[dict[str, Any]]) -> str:
    source_id = _first_non_empty(
        source.get("commander_decision_request_id"),
        source.get("review_feedback_id"),
        source.get("request_id"),
    )
    if source_id:
        return f"plan-adjust-preview-{source_id}"
    for ref in source_refs:
        for key in ("commander_decision_request_id", "review_feedback_id", "id"):
            if ref.get(key):
                return f"plan-adjust-preview-{ref[key]}"
    return "plan-adjust-preview-unidentified-source"


def _id_ref(key: str, value: Any) -> dict[str, Any]:
    if _is_empty(value):
        return {}
    return {key: value}


def _structured_list(*values: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for value in values:
        if _is_empty(value):
            continue
        if isinstance(value, dict):
            rows.append(deepcopy(value))
            continue
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict) and not _is_empty(item):
                    rows.append(deepcopy(item))
    return rows


def _optional_ref(*values: Any) -> dict[str, Any] | None:
    ref = _ref_or_empty(*values)
    return deepcopy(ref) if ref else None


def _ref_or_empty(*values: Any) -> dict[str, Any]:
    for value in values:
        if isinstance(value, dict) and not _is_empty(value):
            return deepcopy(value)
    return {}


def _first_dict(*values: Any) -> dict[str, Any]:
    for value in values:
        if isinstance(value, dict):
            return value
    return {}


def _first_present(*values: Any) -> Any:
    for value in values:
        if not _is_empty(value):
            return value
    return None


def _first_non_empty(*values: Any) -> Any:
    return _first_present(*values)


def _is_empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _reason(code: str, message: str, details: dict[str, Any]) -> dict[str, Any]:
    return {"code": code, "message": message, "details": details}


def _dedupe_refs(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    deduped = []
    for ref in refs:
        key = repr(sorted(ref.items()))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(ref)
    return deduped


def _dedupe_touch_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    seen = set()
    deduped = []
    for row in rows:
        key = (row["path"], row["reason"], row["marker"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped
