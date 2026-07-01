from __future__ import annotations

from copy import deepcopy
from typing import Any


CONTROLLED_CONTINUE_READINESS_SCHEMA_VERSION = "controlled_continue_readiness.v1"
CONTROLLED_CONTINUE_ACTION = "controlled_continue_readiness_report"

READINESS_READY_TO_CONTINUE = "ready_to_continue"
READINESS_BLOCKED = "blocked"
READINESS_NOOP_BLOCKED = "noop_blocked"
VALID_READINESS_RESULTS = frozenset(
    {
        READINESS_READY_TO_CONTINUE,
        READINESS_BLOCKED,
        READINESS_NOOP_BLOCKED,
    }
)

ELIGIBLE_REVIEW_DECISION_VALUES = frozenset({"ACCEPT"})
RUNTIME_STATE_VALUES = frozenset({"PASSED", "COMPLETED", "VERSION_PASSED"})
PLAN_ADJUST_REVIEW_DECISION_VALUE = "PLAN_ADJUST"
PLAN_ADJUST_CLASSIFICATION = "plan_adjust_review_feedback"
PLAN_ADJUST_COMMANDER_ACTION = "ask_whether_to_prepare_plan_adjustment_draft"
ACCEPT_CLASSIFICATION = "accept_review_feedback"
ACCEPT_COMMANDER_ACTION = "ask_whether_to_request_delivery_state_gate_review"
COMMANDER_DECISION_REQUEST_AVAILABLE = "commander_decision_request_available"

STAGE_8_PLAN_ADJUSTMENT_PREVIEW_POINTER = {
    "stage_id": "stage_08_plan_adjustment_control",
    "module": "runner/plan_adjustment_preview.py",
    "report_status": "required_before_continue",
}

CONTINUE_GATE_READY_STATUSES = frozenset({"requested", "available", "ready", "approved", "granted"})
CONTINUE_GATE_TYPES = frozenset({"continue_gate", "controlled_continue_gate", "stage_09_continue_gate"})

FORBIDDEN_SIDE_EFFECT_KEYS = (
    "continue_next_version_service_call",
    "state_machine_continue_next_version_call",
    "manage_executor_workflow_call",
    "executor_preflight_call",
    "executor_run_call",
    "state_mutation",
    "plan_write",
    "state_write",
    "review_decision_creation",
    "gate_event_emission",
    "delivery_state_transition",
    "delivery_state_accepted_write",
    "git_commit",
    "git_push",
    "deploy",
    "package_publish",
    "mcp_web_integration",
)

FORBIDDEN_AUTHORITY_CLAIM_KEYS = frozenset(
    {
        "continue_next_version_called",
        "continue_next_version_service_called",
        "state_machine_continue_next_version_called",
        "manage_executor_workflow_called",
        "executor_preflight_called",
        "executor_run_called",
        "state_mutated",
        "plan_mutated",
        "state_written",
        "review_decision_created",
        "gate_event_emitted",
        "delivery_state_transitioned",
        "delivery_state_accepted",
        "commit_created",
        "pushed",
        "deployed",
        "package_published",
        "mcp_web_integrated",
    }
)

NON_AUTHORITY_NOTICE = {
    "report_is_read_only": True,
    "report_does_not_call_continue_next_version_service": True,
    "report_does_not_call_state_machine_continue_next_version": True,
    "report_does_not_call_manage_executor_workflow": True,
    "report_does_not_call_executor_preflight_or_run": True,
    "report_does_not_mutate_plan_or_state": True,
    "report_does_not_create_review_decision": True,
    "report_does_not_emit_gate_event": True,
    "report_does_not_write_delivery_state_accepted": True,
    "report_does_not_commit_push_deploy_or_publish": True,
    "report_does_not_add_mcp_or_web_integration": True,
    "runtime_passed_or_completed_is_runtime_fact_only": True,
    "runtime_passed_or_completed_is_not_review_decision_accept": True,
    "runtime_passed_or_completed_is_not_delivery_state_accepted": True,
    "plan_adjust_blocks_continue_until_stage_8_preview_is_resolved": True,
}

REQUIRED_REPORT_FIELDS = frozenset(
    {
        "schema_version",
        "action",
        "readiness_result",
        "can_continue",
        "blockers",
        "runner_state_summary",
        "current_version_summary",
        "next_version_summary",
        "plan_summary",
        "git_facts",
        "review_decision_refs",
        "continue_gate_refs",
        "taskbook_hash_refs",
        "plan_adjustment_status",
        "forbidden_side_effects",
        "non_authority_notice",
        "authority_boundary",
    }
)


class ControlledContinueReadinessError(ValueError):
    def __init__(self, error_code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.details = details or {}


def build_controlled_continue_readiness_report(
    inputs: dict[str, Any] | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    if inputs is not None and not isinstance(inputs, dict):
        result = _report_from_parts(
            blockers=[
                _blocker(
                    "CONTROLLED_CONTINUE_INPUT_INVALID",
                    "Controlled continue readiness inputs must be an object.",
                    {},
                )
            ],
            plan={},
            state={},
            data={},
        )
        assert_controlled_continue_readiness_contract(result)
        return result

    data = deepcopy(inputs or {})
    data.update(deepcopy(overrides))
    plan = data.get("plan") if isinstance(data.get("plan"), dict) else {}
    state = data.get("state") if isinstance(data.get("state"), dict) else {}
    blockers: list[dict[str, Any]] = []

    if not isinstance(data.get("plan"), dict):
        blockers.append(_blocker("PLAN_REQUIRED", "Readiness report requires a plan object.", {}))
    if not isinstance(data.get("state"), dict):
        blockers.append(_blocker("STATE_REQUIRED", "Readiness report requires a runner state object.", {}))

    result = _report_from_parts(blockers=blockers, plan=plan, state=state, data=data)
    assert_controlled_continue_readiness_contract(result)
    return result


def assert_controlled_continue_readiness_contract(result: dict[str, Any]) -> None:
    if not isinstance(result, dict):
        raise ControlledContinueReadinessError(
            "CONTROLLED_CONTINUE_READINESS_RESULT_INVALID",
            "Controlled continue readiness result must be an object.",
        )
    missing = sorted(REQUIRED_REPORT_FIELDS - set(result))
    if missing:
        raise ControlledContinueReadinessError(
            "CONTROLLED_CONTINUE_READINESS_FIELD_MISSING",
            "Controlled continue readiness result is missing required fields.",
            details={"missing_fields": missing},
        )
    if result.get("schema_version") != CONTROLLED_CONTINUE_READINESS_SCHEMA_VERSION:
        raise ControlledContinueReadinessError(
            "CONTROLLED_CONTINUE_READINESS_SCHEMA_INVALID",
            "Controlled continue readiness result uses an unsupported schema version.",
            details={"schema_version": result.get("schema_version")},
        )
    if result.get("action") != CONTROLLED_CONTINUE_ACTION:
        raise ControlledContinueReadinessError(
            "CONTROLLED_CONTINUE_READINESS_ACTION_INVALID",
            "Controlled continue readiness result uses an unsupported action.",
            details={"action": result.get("action")},
        )
    if result.get("readiness_result") not in VALID_READINESS_RESULTS:
        raise ControlledContinueReadinessError(
            "CONTROLLED_CONTINUE_READINESS_STATUS_INVALID",
            "Controlled continue readiness result has an unsupported readiness_result.",
            details={"readiness_result": result.get("readiness_result")},
        )
    if not isinstance(result.get("can_continue"), bool):
        raise ControlledContinueReadinessError(
            "CONTROLLED_CONTINUE_CAN_CONTINUE_INVALID",
            "can_continue must be a boolean.",
        )

    blockers = result.get("blockers")
    if not isinstance(blockers, list):
        raise ControlledContinueReadinessError(
            "CONTROLLED_CONTINUE_BLOCKERS_INVALID",
            "Controlled continue readiness blockers must be a list.",
        )
    if result.get("can_continue") and blockers:
        raise ControlledContinueReadinessError(
            "CONTROLLED_CONTINUE_READY_WITH_BLOCKERS",
            "can_continue true result must not include blockers.",
            details={"blockers": blockers},
        )
    if result.get("can_continue") and result.get("readiness_result") != READINESS_READY_TO_CONTINUE:
        raise ControlledContinueReadinessError(
            "CONTROLLED_CONTINUE_READY_STATUS_MISMATCH",
            "can_continue true requires ready_to_continue readiness_result.",
        )
    if result.get("can_continue") and not result.get("next_version_summary", {}).get("has_next_enabled_version"):
        raise ControlledContinueReadinessError(
            "CONTROLLED_CONTINUE_READY_WITHOUT_NEXT_VERSION",
            "can_continue true requires a next enabled version.",
        )

    missing_notice = [
        key
        for key, expected in NON_AUTHORITY_NOTICE.items()
        if result.get("non_authority_notice", {}).get(key) != expected
    ]
    if missing_notice:
        raise ControlledContinueReadinessError(
            "CONTROLLED_CONTINUE_NON_AUTHORITY_NOTICE_MISSING",
            "Controlled continue readiness result is missing non-authority notices.",
            details={"missing_notice": missing_notice},
        )

    forbidden_effects = result.get("forbidden_side_effects")
    if not isinstance(forbidden_effects, dict):
        raise ControlledContinueReadinessError(
            "CONTROLLED_CONTINUE_FORBIDDEN_SIDE_EFFECTS_INVALID",
            "forbidden_side_effects must be an object.",
        )
    observed_effects = [key for key in FORBIDDEN_SIDE_EFFECT_KEYS if forbidden_effects.get(key) is not False]
    if observed_effects:
        raise ControlledContinueReadinessError(
            "CONTROLLED_CONTINUE_FORBIDDEN_SIDE_EFFECT_OBSERVED",
            "Controlled continue readiness report must not record forbidden side effects.",
            details={"observed_effects": observed_effects},
        )

    forbidden_claims = _forbidden_truthy_claims(result, "controlled_continue_readiness")
    if forbidden_claims:
        raise ControlledContinueReadinessError(
            "CONTROLLED_CONTINUE_FORBIDDEN_AUTHORITY_CLAIM",
            "Controlled continue readiness result contains forbidden authority claims.",
            details={"forbidden_claims": forbidden_claims},
        )


def controlled_continue_readiness_inventory() -> dict[str, Any]:
    return {
        "schema_version": CONTROLLED_CONTINUE_READINESS_SCHEMA_VERSION,
        "eligible_review_decision_values": sorted(ELIGIBLE_REVIEW_DECISION_VALUES),
        "runtime_state_values_rejected_as_review_decisions": sorted(RUNTIME_STATE_VALUES),
        "required_continue_inputs": [
            "git facts with matching HEAD and clean worktree",
            "eligible ReviewDecision.ACCEPT or eligible CommanderDecisionRequest",
            "separate continue gate",
            "explicit continue gate target matching the next enabled version",
            "master taskbook hash ref",
            "stage taskbook hash ref",
            "version taskbook hash ref or next-version preview ref",
            "no blocking review comments",
            "next enabled version",
        ],
        "plan_adjust_pointer": dict(STAGE_8_PLAN_ADJUSTMENT_PREVIEW_POINTER),
        "forbidden_side_effects": list(FORBIDDEN_SIDE_EFFECT_KEYS),
        "readiness_results": sorted(VALID_READINESS_RESULTS),
    }


def _report_from_parts(
    *,
    blockers: list[dict[str, Any]],
    plan: dict[str, Any],
    state: dict[str, Any],
    data: dict[str, Any],
) -> dict[str, Any]:
    plan_versions = _dict_list(plan.get("versions"))
    state_versions = _dict_list(state.get("versions"))
    current_index_status = _current_index_status(state, plan_versions)
    current_index = current_index_status["resolved_index"]
    current_version = _clean_str(state.get("current_version"))
    if not current_version and current_index is not None:
        current_version = _version_value(_version_at(plan_versions, current_index))

    current_plan = _version_at(plan_versions, current_index)
    current_runtime = _runtime_for_current(state_versions, current_version, current_index)
    next_index, next_plan = _next_enabled_plan_version(plan_versions, current_index)
    next_runtime = _runtime_for_current(state_versions, _version_value(next_plan), next_index)
    has_next = next_plan is not None

    runner_summary = _runner_state_summary(state, state_versions, current_runtime)
    current_summary = _current_version_summary(current_version, current_index, current_plan, current_runtime)
    next_summary = _next_version_summary(next_index, next_plan, next_runtime)
    plan_summary = _plan_summary(plan, plan_versions, current_version)
    git_facts = _git_facts(data)
    review_refs = _review_decision_refs(data)
    continue_gate_refs = _continue_gate_refs(data, next_summary.get("next_version"))
    taskbook_refs = _taskbook_hash_refs(data)
    review_comments = _review_comment_summary(data, review_refs)
    plan_adjustment_status = _plan_adjustment_status(data, review_refs)

    if current_index is None and has_next:
        blockers.append(
            _blocker(
                "CURRENT_VERSION_INDEX_UNKNOWN",
                "Current version index is missing and the next enabled version cannot be checked safely.",
                {"current_version": current_version},
            )
        )

    if not has_next:
        blockers.append(
            _blocker(
                "NO_NEXT_ENABLED_VERSION",
                "There is no next enabled version to continue into.",
                {"current_version": current_version, "plan_version_count": len(plan_versions)},
            )
        )
    else:
        _add_current_index_blockers(blockers, current_index_status)
        _add_git_blockers(blockers, git_facts)
        _add_current_runtime_blockers(blockers, runner_summary, current_summary)
        _add_review_decision_blockers(blockers, review_refs)
        _add_continue_gate_blockers(blockers, continue_gate_refs, next_summary)
        _add_taskbook_hash_blockers(blockers, taskbook_refs)
        _add_review_comment_blockers(blockers, review_comments)

    if plan_adjustment_status["blocks_continue"]:
        blockers.append(
            _blocker(
                "PLAN_ADJUST_BLOCKS_CONTINUE",
                "PLAN_ADJUST is present or unresolved; continue is blocked until Stage 8 preview handling is resolved.",
                {
                    "stage_8_preview_ref": plan_adjustment_status["stage_8_preview_ref"],
                    "sources": plan_adjustment_status["sources"],
                    "plan_adjustment_preview_ref": plan_adjustment_status["plan_adjustment_preview_ref"],
                },
            )
        )

    readiness_result = _readiness_result(blockers, has_next)
    can_continue = readiness_result == READINESS_READY_TO_CONTINUE

    return {
        "schema_version": CONTROLLED_CONTINUE_READINESS_SCHEMA_VERSION,
        "action": CONTROLLED_CONTINUE_ACTION,
        "readiness_result": readiness_result,
        "can_continue": can_continue,
        "message": _message(readiness_result, blockers),
        "blockers": blockers,
        "runner_state_summary": runner_summary,
        "current_version_summary": current_summary,
        "next_version_summary": next_summary,
        "plan_summary": plan_summary,
        "current_version_index_status": current_index_status,
        "git_facts": git_facts,
        "review_decision_refs": review_refs,
        "continue_gate_refs": continue_gate_refs,
        "taskbook_hash_refs": taskbook_refs,
        "review_comment_summary": review_comments,
        "plan_adjustment_status": plan_adjustment_status,
        "next_action": _next_action(readiness_result, blockers, plan_adjustment_status),
        "forbidden_side_effects": _forbidden_side_effects_false(),
        "non_authority_notice": dict(NON_AUTHORITY_NOTICE),
        "authority_boundary": _authority_boundary(),
        "proposed_state": None,
        "files_would_be_written": [],
    }


def _add_current_index_blockers(blockers: list[dict[str, Any]], current_index_status: dict[str, Any]) -> None:
    issue_code = current_index_status.get("issue_code")
    if not issue_code:
        return
    blockers.append(
        _blocker(
            issue_code,
            "Current version index must be valid and match current_version before continue readiness can pass.",
            {"current_version_index_status": current_index_status},
        )
    )


def _add_git_blockers(blockers: list[dict[str, Any]], git_facts: dict[str, Any]) -> None:
    if not git_facts.get("provided"):
        blockers.append(
            _blocker(
                "GIT_FACTS_REQUIRED",
                "Continue readiness requires git facts for the current checkout.",
                {},
            )
        )
        return
    if not git_facts.get("current_head") or not git_facts.get("expected_head"):
        blockers.append(
            _blocker(
                "GIT_HEAD_REF_REQUIRED",
                "Continue readiness requires both current_head and expected_head.",
                {
                    "current_head": git_facts.get("current_head"),
                    "expected_head": git_facts.get("expected_head"),
                },
            )
        )
    if git_facts.get("head_matches_expected") is False:
        blockers.append(
            _blocker(
                "GIT_HEAD_MISMATCH",
                "Current HEAD does not match the expected continue baseline.",
                {
                    "current_head": git_facts.get("current_head"),
                    "expected_head": git_facts.get("expected_head"),
                },
            )
        )
    if git_facts.get("dirty") is True:
        blockers.append(
            _blocker(
                "GIT_WORKTREE_DIRTY",
                "Continue readiness requires a clean worktree.",
                {"status_short_lines": git_facts.get("status_short_lines", [])},
            )
        )


def _add_current_runtime_blockers(
    blockers: list[dict[str, Any]],
    runner_summary: dict[str, Any],
    current_summary: dict[str, Any],
) -> None:
    runner_status = runner_summary.get("runner_status")
    current_status = current_summary.get("current_version_runtime_status")
    if runner_status != "VERSION_PASSED" or current_status != "PASSED":
        blockers.append(
            _blocker(
                "CURRENT_VERSION_NOT_READY_FOR_CONTINUE",
                "Current runner runtime must be VERSION_PASSED with current version runtime PASSED before continue readiness can pass.",
                {"runner_status": runner_status, "current_version_runtime_status": current_status},
            )
        )


def _add_review_decision_blockers(blockers: list[dict[str, Any]], review_refs: dict[str, Any]) -> None:
    if review_refs.get("runtime_state_value_used_as_review_decision"):
        blockers.append(
            _blocker(
                "RUNTIME_STATE_VALUE_IS_NOT_REVIEW_DECISION",
                "Runtime PASSED/COMPLETED values are runtime facts only and cannot satisfy ReviewDecision.ACCEPT.",
                {
                    "observed_values": review_refs.get("runtime_state_values_observed", []),
                    "runtime_facts_only": review_refs.get("runtime_facts_only"),
                },
            )
        )
    if not review_refs.get("has_eligible_decision_or_request"):
        blockers.append(
            _blocker(
                "ELIGIBLE_REVIEW_DECISION_OR_COMMANDER_REQUEST_REQUIRED",
                "Continue readiness requires an explicit eligible ReviewDecision.ACCEPT or eligible CommanderDecisionRequest.",
                {
                    "review_decision_value": review_refs.get("review_decision_value"),
                    "commander_decision_request_value": review_refs.get("commander_decision_request_value"),
                },
            )
        )


def _add_continue_gate_blockers(
    blockers: list[dict[str, Any]],
    continue_gate_refs: dict[str, Any],
    next_summary: dict[str, Any],
) -> None:
    if not continue_gate_refs.get("present"):
        blockers.append(
            _blocker(
                "CONTINUE_GATE_REF_REQUIRED",
                "Continue readiness requires a separate continue gate ref.",
                {},
            )
        )
        return
    if not continue_gate_refs.get("has_separate_gate"):
        blockers.append(
            _blocker(
                "CONTINUE_GATE_MUST_BE_SEPARATE",
                "Continue gate must be separate from review decision evidence.",
                {"continue_gate_ref": continue_gate_refs.get("continue_gate_ref")},
            )
        )
    if not continue_gate_refs.get("status_is_eligible"):
        blockers.append(
            _blocker(
                "CONTINUE_GATE_STATUS_NOT_ELIGIBLE",
                "Continue gate status must be requested, available, ready, approved, or granted.",
                {"gate_status": continue_gate_refs.get("gate_status")},
            )
        )
    if continue_gate_refs.get("gate_type") and not continue_gate_refs.get("gate_type_is_continue_gate"):
        blockers.append(
            _blocker(
                "CONTINUE_GATE_TYPE_INVALID",
                "Continue gate ref must identify a continue gate.",
                {"gate_type": continue_gate_refs.get("gate_type")},
            )
        )
    target = continue_gate_refs.get("target_next_version")
    if not target:
        blockers.append(
            _blocker(
                "CONTINUE_GATE_TARGET_REQUIRED",
                "Continue gate ref must explicitly target the next enabled version.",
                {"next_version": next_summary.get("next_version")},
            )
        )
    if target and next_summary.get("next_version") and target != next_summary.get("next_version"):
        blockers.append(
            _blocker(
                "CONTINUE_GATE_TARGET_MISMATCH",
                "Continue gate target does not match the next enabled version.",
                {"gate_target": target, "next_version": next_summary.get("next_version")},
            )
        )


def _add_taskbook_hash_blockers(blockers: list[dict[str, Any]], taskbook_refs: dict[str, Any]) -> None:
    for field, code_prefix in (
        ("master_taskbook_ref", "MASTER_TASKBOOK"),
        ("stage_taskbook_ref", "STAGE_TASKBOOK"),
    ):
        ref = taskbook_refs.get(field, {})
        if not ref.get("provided"):
            blockers.append(
                _blocker(
                    f"{code_prefix}_HASH_REF_REQUIRED",
                    f"{field} with a known hash is required before continue readiness can pass.",
                    {},
                )
            )
        elif ref.get("mismatch"):
            blockers.append(
                _blocker(
                    f"{code_prefix}_HASH_MISMATCH",
                    f"{field} hash does not match expected hash.",
                    {"ref": ref},
                )
            )

    version_ref = taskbook_refs.get("version_taskbook_ref", {})
    preview_ref = taskbook_refs.get("next_version_preview_ref", {})
    version_or_preview_present = version_ref.get("provided") or preview_ref.get("provided")
    if not version_or_preview_present:
        blockers.append(
            _blocker(
                "VERSION_TASKBOOK_OR_PREVIEW_REF_REQUIRED",
                "Continue readiness requires a version taskbook hash ref or next-version preview ref.",
                {},
            )
        )
    if version_ref.get("mismatch"):
        blockers.append(
            _blocker(
                "VERSION_TASKBOOK_HASH_MISMATCH",
                "Version taskbook hash does not match expected hash.",
                {"ref": version_ref},
            )
        )
    if preview_ref.get("mismatch"):
        blockers.append(
            _blocker(
                "NEXT_VERSION_PREVIEW_REF_MISMATCH",
                "Next-version preview ref does not match expected hash.",
                {"ref": preview_ref},
            )
        )


def _add_review_comment_blockers(blockers: list[dict[str, Any]], review_comments: dict[str, Any]) -> None:
    if review_comments.get("blocking_review_comment_count", 0) > 0:
        blockers.append(
            _blocker(
                "BLOCKING_REVIEW_COMMENTS_PRESENT",
                "Continue readiness requires all blocking review comments to be resolved.",
                {"blocking_review_comments": review_comments.get("blocking_review_comments", [])},
            )
        )


def _runner_state_summary(
    state: dict[str, Any],
    state_versions: list[dict[str, Any]],
    current_runtime: dict[str, Any],
) -> dict[str, Any]:
    runner_status = _clean_str(state.get("status"))
    current_status = _clean_str(current_runtime.get("status"))
    return {
        "runner_status": runner_status,
        "current_version": _clean_str(state.get("current_version")),
        "current_version_index": state.get("current_version_index"),
        "state_version_count": len(state_versions),
        "current_version_runtime_status": current_status,
        "updated_at": state.get("updated_at"),
        "completed_at": state.get("completed_at"),
        "runtime_facts_only": {
            "runner_status": runner_status,
            "current_version_runtime_status": current_status,
            "runtime_status_is_not_review_decision_accept": True,
            "runtime_status_is_not_delivery_state_accepted": True,
        },
    }


def _current_version_summary(
    current_version: str,
    current_index: int | None,
    current_plan: dict[str, Any],
    current_runtime: dict[str, Any],
) -> dict[str, Any]:
    return {
        "current_version": current_version,
        "current_version_index": current_index,
        "current_version_name": _first_non_empty(current_plan.get("name"), current_runtime.get("name")),
        "current_version_enabled": _version_enabled(current_plan) if current_plan else None,
        "current_version_runtime_status": _clean_str(current_runtime.get("status")),
        "current_version_commit_hash": current_runtime.get("commit_hash"),
        "current_version_completed_at": current_runtime.get("completed_at"),
    }


def _next_version_summary(
    next_index: int | None,
    next_plan: dict[str, Any] | None,
    next_runtime: dict[str, Any],
) -> dict[str, Any]:
    has_next = next_plan is not None
    return {
        "has_next_enabled_version": has_next,
        "next_version": _version_value(next_plan),
        "next_version_index": next_index,
        "next_version_name": _clean_str(next_plan.get("name")) if isinstance(next_plan, dict) else None,
        "next_version_enabled": _version_enabled(next_plan) if isinstance(next_plan, dict) else False,
        "next_version_runtime_status": _clean_str(next_runtime.get("status")),
        "noop_reason": None if has_next else "no_next_enabled_version_to_continue_into",
    }


def _plan_summary(plan: dict[str, Any], plan_versions: list[dict[str, Any]], current_version: str) -> dict[str, Any]:
    enabled_versions = [version for version in plan_versions if _version_enabled(version)]
    return {
        "project_name": plan.get("project_name"),
        "plan_version": plan.get("plan_version"),
        "plan_version_count": len(plan_versions),
        "enabled_version_count": len(enabled_versions),
        "current_version_present": current_version in {_version_value(version) for version in plan_versions},
        "version_order": [_version_value(version) for version in plan_versions],
    }


def _git_facts(data: dict[str, Any]) -> dict[str, Any]:
    raw = data.get("git_facts") if isinstance(data.get("git_facts"), dict) else {}
    current_head = _first_non_empty(raw.get("current_head"), raw.get("head"), data.get("current_head"))
    expected_head = _first_non_empty(raw.get("expected_head"), data.get("expected_head"))
    branch = _first_non_empty(raw.get("current_branch"), raw.get("branch"), data.get("current_branch"))
    status_short = _first_non_empty(raw.get("git_status_short"), raw.get("status_short"), data.get("git_status_short"))
    status_lines = _status_lines(status_short)
    dirty_value = raw.get("dirty")
    dirty = dirty_value if isinstance(dirty_value, bool) else bool(status_lines)
    provided = bool(raw) or any([current_head, expected_head, branch, status_short])
    return {
        "provided": provided,
        "current_head": current_head or None,
        "expected_head": expected_head or None,
        "head_matches_expected": None if not (current_head and expected_head) else current_head == expected_head,
        "current_branch": branch or None,
        "dirty": dirty if provided else None,
        "status_short_lines": status_lines,
        "dirty_is_reported_as_fact_only": True,
    }


def _review_decision_refs(data: dict[str, Any]) -> dict[str, Any]:
    review_ref = _first_dict(
        data.get("review_decision_ref"),
        data.get("review_decision"),
        data.get("review_decision_record"),
    )
    commander_ref = _first_dict(
        data.get("commander_decision_request_ref"),
        data.get("commander_decision_request"),
    )

    review_value = _review_decision_value(review_ref)
    commander_value = _first_non_empty(
        commander_ref.get("normalized_review_decision_value"),
        commander_ref.get("source_review_decision_value"),
        commander_ref.get("review_decision_value"),
    )
    commander_classification = _clean_str(commander_ref.get("normalized_classification"))
    commander_action = _clean_str(commander_ref.get("requested_commander_action"))
    commander_status = _clean_str(commander_ref.get("request_status"))

    review_eligible = review_value in ELIGIBLE_REVIEW_DECISION_VALUES
    commander_eligible = (
        bool(commander_ref)
        and commander_status == COMMANDER_DECISION_REQUEST_AVAILABLE
        and (
            commander_value in ELIGIBLE_REVIEW_DECISION_VALUES
            or commander_classification == ACCEPT_CLASSIFICATION
            or commander_action == ACCEPT_COMMANDER_ACTION
        )
    )
    runtime_values = [
        value
        for value in (review_value, commander_value)
        if value in RUNTIME_STATE_VALUES
    ]
    return {
        "review_decision_ref": _compact_ref(review_ref),
        "commander_decision_request_ref": _compact_ref(commander_ref),
        "review_decision_value": review_value or None,
        "commander_decision_request_value": commander_value or None,
        "commander_decision_request_status": commander_status or None,
        "commander_decision_request_classification": commander_classification or None,
        "commander_decision_request_action": commander_action or None,
        "eligible_review_decision_present": review_eligible,
        "eligible_commander_decision_request_present": commander_eligible,
        "has_eligible_decision_or_request": review_eligible or commander_eligible,
        "eligible_basis": _eligible_basis(review_eligible, commander_eligible),
        "runtime_state_value_used_as_review_decision": bool(runtime_values),
        "runtime_state_values_observed": runtime_values,
        "runtime_facts_only": {
            "runtime_PASSED_equals_review_acceptance": False,
            "runtime_COMPLETED_equals_review_acceptance": False,
            "runtime_PASSED_or_COMPLETED_equals_delivery_state_accepted": False,
        },
    }


def _continue_gate_refs(data: dict[str, Any], next_version: Any) -> dict[str, Any]:
    ref = _first_dict(data.get("continue_gate_ref"), data.get("continue_gate"))
    gate_id = _first_non_empty(ref.get("continue_gate_id"), ref.get("gate_id"), ref.get("id"), ref.get("ref"))
    gate_status = _clean_str(_first_non_empty(ref.get("gate_status"), ref.get("status")))
    gate_type = _clean_str(_first_non_empty(ref.get("gate_type"), ref.get("type")))
    separate = ref.get("separate_from_review_decision")
    if separate is None:
        separate = ref.get("is_separate_continue_gate")
    target = _clean_str(_first_non_empty(ref.get("target_next_version"), ref.get("next_version")))
    present = bool(gate_id or ref)
    return {
        "present": present,
        "continue_gate_ref": _compact_ref(ref),
        "continue_gate_id": gate_id or None,
        "gate_status": gate_status or None,
        "status_is_eligible": gate_status in CONTINUE_GATE_READY_STATUSES,
        "gate_type": gate_type or None,
        "gate_type_is_continue_gate": not gate_type or gate_type in CONTINUE_GATE_TYPES,
        "has_separate_gate": separate is True,
        "target_next_version": target or None,
        "target_is_explicit": bool(target),
    }


def _taskbook_hash_refs(data: dict[str, Any]) -> dict[str, Any]:
    refs = data.get("taskbook_hash_refs") if isinstance(data.get("taskbook_hash_refs"), dict) else {}
    master_ref = _hash_ref_summary(
        _first_dict(refs.get("master_taskbook_ref"), refs.get("master"), data.get("master_taskbook_ref"))
    )
    stage_ref = _hash_ref_summary(
        _first_dict(refs.get("stage_taskbook_ref"), refs.get("stage"), data.get("stage_taskbook_ref"))
    )
    version_ref = _hash_ref_summary(
        _first_dict(
            refs.get("version_taskbook_ref"),
            refs.get("current_version_taskbook_ref"),
            refs.get("version"),
            data.get("version_taskbook_ref"),
        )
    )
    preview_ref = _hash_ref_summary(
        _first_dict(
            refs.get("next_version_preview_ref"),
            refs.get("preview_ref"),
            refs.get("next_version_preview"),
            data.get("next_version_preview_ref"),
        )
    )
    return {
        "master_taskbook_ref": master_ref,
        "stage_taskbook_ref": stage_ref,
        "version_taskbook_ref": version_ref,
        "next_version_preview_ref": preview_ref,
        "version_taskbook_or_preview_ref_present": version_ref["provided"] or preview_ref["provided"],
    }


def _review_comment_summary(data: dict[str, Any], review_refs: dict[str, Any]) -> dict[str, Any]:
    comments = _list_or_empty(data.get("blocking_review_comments"))
    review_ref = data.get("review_decision_ref") if isinstance(data.get("review_decision_ref"), dict) else {}
    comments.extend(_list_or_empty(review_ref.get("blocking_review_comments")))
    if data.get("has_blocking_review_comments") is True or review_ref.get("has_blocking_review_comments") is True:
        comments.append({"source": "has_blocking_review_comments", "blocking": True})
    if review_refs.get("review_decision_ref", {}).get("has_blocking_review_comments") is True:
        comments.append({"source": "review_decision_ref", "blocking": True})

    blocking = [comment for comment in comments if _comment_is_blocking(comment)]
    return {
        "blocking_review_comment_count": len(blocking),
        "blocking_review_comments": deepcopy(blocking),
        "no_blocking_review_comments": not blocking,
    }


def _plan_adjustment_status(data: dict[str, Any], review_refs: dict[str, Any]) -> dict[str, Any]:
    plan_adjustment_preview_ref = _first_dict(
        data.get("plan_adjustment_preview_ref"),
        data.get("stage_8_plan_adjustment_preview_ref"),
    )
    sources: list[dict[str, Any]] = []

    review_value = review_refs.get("review_decision_value")
    commander_value = review_refs.get("commander_decision_request_value")
    commander_classification = review_refs.get("commander_decision_request_classification")
    commander_action = review_refs.get("commander_decision_request_action")

    if review_value == PLAN_ADJUST_REVIEW_DECISION_VALUE:
        sources.append({"source": "review_decision_ref", "value": review_value})
    if commander_value == PLAN_ADJUST_REVIEW_DECISION_VALUE:
        sources.append({"source": "commander_decision_request_ref", "value": commander_value})
    if commander_classification == PLAN_ADJUST_CLASSIFICATION:
        sources.append({"source": "commander_decision_request_ref", "classification": commander_classification})
    if commander_action == PLAN_ADJUST_COMMANDER_ACTION:
        sources.append({"source": "commander_decision_request_ref", "requested_action": commander_action})

    explicit_unresolved = data.get("plan_adjust_unresolved") is True
    preview_resolution = _clean_str(
        _first_non_empty(
            plan_adjustment_preview_ref.get("resolution_status"),
            plan_adjustment_preview_ref.get("status"),
        )
    )
    preview_unresolved = bool(plan_adjustment_preview_ref) and preview_resolution not in {
        "resolved",
        "closed",
        "superseded",
        "not_required",
    }
    if explicit_unresolved:
        sources.append({"source": "plan_adjust_unresolved", "value": True})
    if preview_unresolved:
        sources.append({"source": "plan_adjustment_preview_ref", "resolution_status": preview_resolution or None})

    return {
        "plan_adjust_present": any(source.get("value") == PLAN_ADJUST_REVIEW_DECISION_VALUE for source in sources),
        "plan_adjust_unresolved": explicit_unresolved or preview_unresolved,
        "blocks_continue": bool(sources),
        "sources": sources,
        "stage_8_preview_ref": dict(STAGE_8_PLAN_ADJUSTMENT_PREVIEW_POINTER),
        "plan_adjustment_preview_ref": _compact_ref(plan_adjustment_preview_ref),
    }


def _hash_ref_summary(raw_ref: dict[str, Any]) -> dict[str, Any]:
    ref = deepcopy(raw_ref)
    expected_hash = _first_non_empty(
        ref.get("expected_sha256"),
        ref.get("expected_raw_snapshot_sha256"),
        ref.get("expected_hash"),
    )
    observed_hash = _first_non_empty(
        ref.get("actual_sha256"),
        ref.get("actual_raw_snapshot_sha256"),
        ref.get("actual_hash"),
        ref.get("raw_snapshot_sha256"),
        ref.get("sha256"),
        ref.get("hash"),
    )
    path = _clean_str(ref.get("path"))
    ref_id = _first_non_empty(ref.get("id"), ref.get("ref"), ref.get("preview_id"), ref.get("version"), ref.get("stage_id"))
    provided = bool(ref) and bool(observed_hash or expected_hash or path or ref_id)
    mismatch = bool(expected_hash and observed_hash and expected_hash != observed_hash)
    return {
        "provided": provided and bool(observed_hash or expected_hash),
        "path": path or None,
        "ref_id": ref_id or None,
        "expected_sha256": expected_hash or None,
        "observed_sha256": observed_hash or None,
        "hash_known": bool(observed_hash or expected_hash),
        "mismatch": mismatch,
        "matches": False if mismatch else bool(observed_hash or expected_hash),
        "comparison": "expected_vs_observed" if expected_hash and observed_hash else "single_hash_ref",
    }


def _current_index_status(state: dict[str, Any], plan_versions: list[dict[str, Any]]) -> dict[str, Any]:
    raw_index = state.get("current_version_index")
    current_version = _clean_str(state.get("current_version"))
    raw_index_is_int = isinstance(raw_index, int) and not isinstance(raw_index, bool)
    raw_index_in_range = raw_index_is_int and 0 <= raw_index < len(plan_versions)
    raw_index_version = _version_value(_version_at(plan_versions, raw_index)) if raw_index_in_range else ""
    resolved_index = None
    resolved_basis = None
    issue_code = None

    if raw_index_is_int and raw_index < 0:
        issue_code = "CURRENT_VERSION_INDEX_INVALID"
    elif raw_index_is_int and raw_index >= len(plan_versions):
        issue_code = "CURRENT_VERSION_INDEX_OUT_OF_RANGE"
    elif raw_index is not None and not raw_index_is_int:
        issue_code = "CURRENT_VERSION_INDEX_INVALID"

    if raw_index_in_range:
        if current_version and raw_index_version != current_version:
            issue_code = "CURRENT_VERSION_INDEX_VERSION_MISMATCH"
        else:
            resolved_index = raw_index
            resolved_basis = "current_version_index"

    if resolved_index is None and current_version:
        for index, version in enumerate(plan_versions):
            if _version_value(version) == current_version:
                resolved_index = index
                resolved_basis = "current_version"
                break

    return {
        "raw_current_version_index": raw_index,
        "current_version": current_version or None,
        "raw_index_is_valid_integer": raw_index_is_int and raw_index >= 0,
        "raw_index_in_range": raw_index_in_range,
        "raw_index_version": raw_index_version or None,
        "resolved_index": resolved_index,
        "resolved_basis": resolved_basis,
        "issue_code": issue_code,
    }


def _next_enabled_plan_version(
    plan_versions: list[dict[str, Any]],
    current_index: int | None,
) -> tuple[int | None, dict[str, Any] | None]:
    if current_index is None:
        return None, None
    for index in range(current_index + 1, len(plan_versions)):
        candidate = plan_versions[index]
        if _version_enabled(candidate):
            return index, candidate
    return None, None


def _runtime_for_current(
    state_versions: list[dict[str, Any]],
    version: str,
    index: int | None,
) -> dict[str, Any]:
    if index is not None and 0 <= index < len(state_versions):
        return deepcopy(state_versions[index])
    for runtime in state_versions:
        if _version_value(runtime) == version:
            return deepcopy(runtime)
    return {}


def _version_at(versions: list[dict[str, Any]], index: int | None) -> dict[str, Any]:
    if index is not None and 0 <= index < len(versions):
        return deepcopy(versions[index])
    return {}


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [deepcopy(item) for item in value if isinstance(item, dict)]


def _version_value(version: dict[str, Any] | None) -> str:
    if not isinstance(version, dict):
        return ""
    return _clean_str(_first_non_empty(version.get("version"), version.get("id"), version.get("name")))


def _version_enabled(version: dict[str, Any] | None) -> bool:
    if not isinstance(version, dict):
        return False
    return version.get("enabled") is not False


def _review_decision_value(ref: dict[str, Any]) -> str:
    return _clean_str(
        _first_non_empty(
            ref.get("normalized_review_decision_value"),
            ref.get("review_decision_value"),
            ref.get("decision"),
            ref.get("value"),
        )
    )


def _eligible_basis(review_eligible: bool, commander_eligible: bool) -> str | None:
    if review_eligible:
        return "review_decision_accept"
    if commander_eligible:
        return "commander_decision_request_accept_path"
    return None


def _first_dict(*values: Any) -> dict[str, Any]:
    for value in values:
        if isinstance(value, dict) and value:
            return deepcopy(value)
    return {}


def _compact_ref(ref: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(ref, dict) or not ref:
        return {}
    keys = (
        "id",
        "ref",
        "path",
        "version",
        "stage_id",
        "review_decision_id",
        "review_feedback_id",
        "commander_decision_request_id",
        "continue_gate_id",
        "gate_id",
        "preview_id",
        "request_status",
        "status",
        "gate_status",
        "normalized_review_decision_value",
        "review_decision_value",
        "source_review_decision_value",
        "normalized_classification",
        "requested_commander_action",
        "raw_snapshot_sha256",
        "sha256",
        "hash",
        "expected_sha256",
        "actual_sha256",
    )
    return {key: deepcopy(ref[key]) for key in keys if key in ref}


def _list_or_empty(value: Any) -> list[Any]:
    return deepcopy(value) if isinstance(value, list) else []


def _comment_is_blocking(comment: Any) -> bool:
    if not isinstance(comment, dict):
        return bool(comment)
    if comment.get("blocking") is False:
        return False
    status = _clean_str(comment.get("status")).lower()
    if status in {"resolved", "closed", "dismissed", "non_blocking"}:
        return False
    return True


def _readiness_result(blockers: list[dict[str, Any]], has_next: bool) -> str:
    if not blockers and has_next:
        return READINESS_READY_TO_CONTINUE
    codes = {str(blocker.get("code")) for blocker in blockers}
    if "NO_NEXT_ENABLED_VERSION" in codes:
        return READINESS_NOOP_BLOCKED
    return READINESS_BLOCKED


def _message(readiness_result: str, blockers: list[dict[str, Any]]) -> str:
    if readiness_result == READINESS_READY_TO_CONTINUE:
        return "Readiness checks passed; report only. No runner continuation was executed."
    if readiness_result == READINESS_NOOP_BLOCKED:
        return "Noop/blocked: there is no next enabled version to continue into."
    if blockers:
        return "Blocked: continue readiness is missing required evidence or gates."
    return "Blocked: continue readiness did not pass."


def _next_action(
    readiness_result: str,
    blockers: list[dict[str, Any]],
    plan_adjustment_status: dict[str, Any],
) -> dict[str, Any]:
    if plan_adjustment_status.get("blocks_continue"):
        return {
            "action": "open_stage_8_plan_adjustment_preview",
            "stage_8_preview_ref": plan_adjustment_status.get("stage_8_preview_ref"),
            "report_only": True,
        }
    if readiness_result == READINESS_READY_TO_CONTINUE:
        return {
            "action": "manual_controlled_continue_gate_review",
            "report_only": True,
            "runner_continued": False,
        }
    if readiness_result == READINESS_NOOP_BLOCKED:
        return {
            "action": "noop_no_next_version",
            "report_only": True,
            "runner_continued": False,
        }
    return {
        "action": "resolve_continue_readiness_blockers",
        "blocking_codes": [blocker.get("code") for blocker in blockers],
        "report_only": True,
        "runner_continued": False,
    }


def _authority_boundary() -> dict[str, bool]:
    return {
        "readiness_result_is_review_acceptance": False,
        "readiness_result_is_delivery_state_accepted": False,
        "readiness_result_authorizes_state_mutation": False,
        "readiness_result_authorizes_executor_run": False,
        "readiness_result_authorizes_commit_push_deploy": False,
        "review_decision_created": False,
        "gate_event_emitted": False,
        "delivery_state_transitioned": False,
        "state_mutated": False,
    }


def _forbidden_side_effects_false() -> dict[str, bool]:
    return {key: False for key in FORBIDDEN_SIDE_EFFECT_KEYS}


def _blocker(code: str, message: str, details: dict[str, Any]) -> dict[str, Any]:
    return {"code": code, "message": message, "details": details}


def _status_lines(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if not isinstance(value, str):
        return []
    return [line for line in value.splitlines() if line.strip()]


def _first_non_empty(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", []):
            return value
    return ""


def _clean_str(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _forbidden_truthy_claims(value: Any, path: str) -> list[dict[str, str]]:
    claims: list[dict[str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if str(key) in FORBIDDEN_AUTHORITY_CLAIM_KEYS and _truthy_claim(child):
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
            "mutated",
            "transitioned",
            "continued",
            "deployed",
            "pushed",
        }
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value != 0
    return False
