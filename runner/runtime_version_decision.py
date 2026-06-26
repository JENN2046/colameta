from __future__ import annotations

from typing import Any


FORBIDDEN_RUNTIME_VERSION_STATUS_ACTIONS = (
    "restart",
    "reload",
    "kill",
    "apply",
    "automatic_restart",
    "automatic_reload",
    "automatic_kill",
    "automatic_apply",
    "service_lifecycle_mutation",
    "state_mutation",
    "config_write",
    "config_mutation",
    "git_fetch",
    "git_pull",
    "git_push",
    "git_tag",
    "git_release",
    "executor_workflow_mutation",
    "web_route_mutation",
)


def evaluate_runtime_version_status_decision(restart_needed_state: Any = None) -> dict[str, Any]:
    if restart_needed_state == "not_needed":
        return _decision(
            decision_kind="normal_operation",
            operator_notice_required=False,
            diagnostics_required=False,
            explanation="Runtime version status is current. No restart prompt is needed.",
        )

    if restart_needed_state == "needed":
        return _decision(
            decision_kind="operator_handoff_notice",
            operator_notice_required=True,
            diagnostics_required=False,
            explanation=(
                "Runtime version status indicates a possible stale process. "
                "This is an operator handoff notice only; no automatic restart, reload, kill, "
                "or apply action is authorized."
            ),
        )

    return _decision(
        decision_kind="bounded_read_only_diagnostics",
        operator_notice_required=False,
        diagnostics_required=True,
        explanation=(
            "Runtime version status is unknown or invalid. Unknown is not safe, does not mean current, "
            "and does not authorize any automatic action; only bounded read-only diagnostics are allowed."
        ),
    )


def _decision(
    *,
    decision_kind: str,
    operator_notice_required: bool,
    diagnostics_required: bool,
    explanation: str,
) -> dict[str, Any]:
    return {
        "decision_kind": decision_kind,
        "operator_notice_required": operator_notice_required,
        "diagnostics_required": diagnostics_required,
        "forbidden_actions": list(FORBIDDEN_RUNTIME_VERSION_STATUS_ACTIONS),
        "automatic_action_authorized": False,
        "restart_prompt_required": False,
        "explanation": explanation,
    }
