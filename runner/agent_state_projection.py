from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from runner.agent_routing_registry import profile_guidance, tool_routing_metadata


AGENT_PROJECTION_SCHEMA_VERSION = "colameta.agent_state_projection.v1"

_HANDLE_SPECS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("review_manifest_id", "review_manifest", ("read", "verify")),
    ("artifact_id", "result_artifact", ("read",)),
    ("run_id", "executor_run", ("status", "read")),
    ("workflow_id", "workflow_run", ("status", "read")),
    ("gate_preview_id", "gate_preview", ("status", "apply")),
    ("batch_preview_id", "batch_preview", ("status", "execute")),
    ("patch_id", "plan_patch", ("status", "apply")),
    ("preview_id", "preview", ()),
)

_HARD_STOPS = (
    "No Agent projection field grants apply, executor, commit, push, merge, stable replacement, delivery, deploy, or release authority.",
    "The original typed handle, scope, context binding, preview and confirmation gates remain mandatory.",
)

# Retrying the identical call is safe only when an exact, reviewed error code
# proves the failure transient and the operation idempotent.  No current
# ColaMeta-owned error has that proof, so this allowlist intentionally starts
# empty; additions require a dedicated regression test.
_RETRY_SAME_CALL_ERROR_CODES: frozenset[str] = frozenset()


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _projection_sources(value: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Return bounded production envelopes from outermost to innermost."""

    sources: list[Mapping[str, Any]] = []
    queue: list[tuple[Mapping[str, Any], int]] = [(value, 0)]
    seen: set[int] = set()
    while queue:
        current, depth = queue.pop(0)
        identity = id(current)
        if identity in seen:
            continue
        seen.add(identity)
        sources.append(current)
        if depth >= 5:
            continue
        for key in (
            "result",
            "facts",
            "data",
            "current_state",
            "canonical_state",
            "canonical_project_state",
            "current_conclusion",
            "unified_status",
        ):
            nested = current.get(key)
            if isinstance(nested, Mapping):
                queue.append((nested, depth + 1))
    return sources


def _first_text(sources: list[Mapping[str, Any]], *keys: str) -> str | None:
    for source in sources:
        for key in keys:
            value = source.get(key)
            if isinstance(value, str) and value:
                return value
    return None


def _project_bound_action(
    action: Mapping[str, Any],
    project_name: str,
) -> dict[str, Any]:
    bound = dict(action)
    argument_field_found = False
    copyable_arguments: dict[str, Any] | None = None
    for field in ("arguments", "params", "required_arguments"):
        value = bound.get(field)
        if isinstance(value, Mapping):
            arguments = dict(value)
            arguments.setdefault("project_name", project_name)
            bound[field] = arguments
            if field in {"arguments", "params"}:
                argument_field_found = True
    copyable = bound.get("copyable_tool_call")
    if isinstance(copyable, Mapping):
        copyable_bound = dict(copyable)
        copyable_arguments = _as_dict(copyable_bound.get("arguments"))
        copyable_arguments.setdefault("project_name", project_name)
        copyable_bound["arguments"] = copyable_arguments
        bound["copyable_tool_call"] = copyable_bound
    if not argument_field_found:
        bound["arguments"] = copyable_arguments or {"project_name": project_name}
    return bound


def _bind_top_level_actions_to_project(
    response: dict[str, Any],
    project_name: str | None,
) -> None:
    if not project_name:
        return
    for key in ("primary_next_action", "recommended_next_action", "next_action", "safe_next_action"):
        action = response.get(key)
        if isinstance(action, Mapping):
            response[key] = _project_bound_action(action, project_name)
    for key in ("recommended_next_actions", "next_actions", "recommended_next_steps"):
        actions = response.get(key)
        if isinstance(actions, list):
            response[key] = [
                _project_bound_action(action, project_name)
                if isinstance(action, Mapping)
                else action
                for action in actions
            ]


def normalize_agent_action(
    action: Any,
    *,
    source_tool: str,
    project_name: str | None = None,
) -> dict[str, Any] | None:
    if not isinstance(action, Mapping):
        return None
    normalized = (
        _project_bound_action(action, project_name)
        if project_name
        else dict(action)
    )
    arguments = _as_dict(normalized.get("arguments"))
    if not arguments:
        arguments = _as_dict(normalized.get("params"))
    copyable = _as_dict(normalized.get("copyable_tool_call"))
    if not arguments:
        arguments = _as_dict(copyable.get("arguments"))
    tool = normalized.get("tool") or copyable.get("tool")
    if not isinstance(tool, str) or not tool:
        return None
    action_name = normalized.get("action")
    if not isinstance(action_name, str) or not action_name:
        for field in ("action", "phase", "workflow"):
            candidate = arguments.get(field)
            if isinstance(candidate, str) and candidate:
                action_name = candidate
                break
    normalized.setdefault("action", action_name if isinstance(action_name, str) else "inspect")
    normalized.setdefault("reason", "Follow the first bounded action selected from current project state.")
    required_arguments = _as_dict(normalized.get("required_arguments"))
    if not required_arguments:
        required_arguments = dict(arguments)
    elif project_name:
        required_arguments.setdefault("project_name", project_name)
    normalized["required_arguments"] = required_arguments
    normalized.setdefault("optional_arguments", {})
    normalized.setdefault("source_tool", source_tool)
    normalized.setdefault("routing", tool_routing_metadata(tool))
    normalized.setdefault("navigation_only", True)
    normalized.setdefault("does_not_grant_authority", True)
    return normalized


def _is_same_source_refresh(action: Mapping[str, Any], source_tool: str) -> bool:
    tool = action.get("tool")
    arguments = action.get("arguments")
    if not isinstance(arguments, Mapping):
        arguments = action.get("params")
    action_name = action.get("action")
    if not isinstance(action_name, str) and isinstance(arguments, Mapping):
        action_name = arguments.get("action")
    return tool == source_tool and action_name == "refresh_project_state"


def _profile_allowed_tools(profile_id: str | None) -> frozenset[str] | None:
    if profile_id is None:
        return None
    guidance = profile_guidance(profile_id)
    return frozenset(
        tool
        for key in ("primary_tools", "advanced_tools")
        for tool in guidance.get(key, [])
        if isinstance(tool, str) and tool
    )


def _action_reachable(
    action: Mapping[str, Any],
    allowed_tools: frozenset[str] | None,
) -> bool:
    return allowed_tools is None or action.get("tool") in allowed_tools


def _first_action(
    response: Mapping[str, Any],
    *,
    source_tool: str,
    allowed_tools: frozenset[str] | None,
) -> Any:
    for source in _projection_sources(response):
        direct = source.get("primary_next_action")
        if (
            isinstance(direct, Mapping)
            and not _is_same_source_refresh(direct, source_tool)
            and _action_reachable(direct, allowed_tools)
        ):
            return direct
        for key in ("recommended_next_actions", "next_actions", "recommended_next_steps"):
            actions = source.get(key)
            if isinstance(actions, list):
                for action in actions:
                    if (
                        isinstance(action, Mapping)
                        and isinstance(action.get("tool"), str)
                        and not _is_same_source_refresh(action, source_tool)
                        and _action_reachable(action, allowed_tools)
                    ):
                        return action
        for key in ("recommended_next_action", "next_action", "safe_next_action"):
            next_action = source.get(key)
            if (
                isinstance(next_action, Mapping)
                and isinstance(next_action.get("tool"), str)
                and not _is_same_source_refresh(next_action, source_tool)
                and _action_reachable(next_action, allowed_tools)
            ):
                return next_action
    return None


def select_primary_action_from_state(
    state: Mapping[str, Any],
    *,
    intent: str | None = None,
) -> dict[str, Any] | None:
    """Select one conservative navigation action from a recognized state.

    This function deliberately recognizes only states whose next read or
    preview is unambiguous.  It never selects an apply, run, commit-apply,
    push, merge, stable replacement, delivery, deploy, or release action.
    Unknown states return ``None`` instead of guessing.
    """

    sources = _projection_sources(state)
    run_id = _first_text(sources, "run_id")
    executor_run_status = _first_text(sources, "executor_run_status")
    if executor_run_status:
        status = f"EXECUTOR_{executor_run_status}".upper()
    else:
        status = ""
        for source in sources:
            candidate = (
                source.get("status")
                or source.get("state")
                or source.get("readiness_status")
            )
            if isinstance(candidate, str) and candidate:
                # An outer workflow's succeeded/failed status must not preempt
                # the canonical or nested project state it is carrying.
                if source is state and "result" in state and candidate.lower() in {
                    "succeeded", "failed", "completed"
                }:
                    continue
                status = candidate
                break
        status = status.strip().upper().replace("-", "_").replace(" ", "_")
    rules: dict[str, tuple[str, str, str, dict[str, Any]]] = {
        "EXECUTOR_PREFLIGHT": (
            "run_mcp_workflow",
            "auto_preview",
            "Executor work needs a bounded preview before any run authority can be evaluated.",
            {"workflow": "auto_preview"},
        ),
        "EXECUTOR_READY_TO_RUN": (
            "manage_executor_workflow",
            "preview",
            "Refresh the typed executor preview; this navigation result does not authorize the run.",
            {"action": "preview"},
        ),
        "EXECUTOR_RUNNING": (
            "manage_executor_workflow",
            "status",
            "An executor is already running; poll the same run instead of starting another.",
            {"action": "status", **({"run_id": run_id} if run_id else {})},
        ),
        "EXECUTOR_COMPLETED": (
            "manage_validation_run",
            "preview",
            "Executor work completed and acceptance validation is the next bounded gate.",
            {"action": "preview"},
        ),
        "EXECUTOR_COMPLETED_VALIDATION_PENDING": (
            "manage_validation_run",
            "preview",
            "Executor work completed and acceptance validation has not run.",
            {"action": "preview"},
        ),
        "VALIDATION_PENDING": (
            "manage_validation_run",
            "preview",
            "Validation has not run; create or refresh its bounded preview.",
            {"action": "preview"},
        ),
        "VALIDATION_FAILED": (
            "manage_validation_run",
            "inspect",
            "Inspect failed validation evidence before planning a repair.",
            {"action": "inspect"},
        ),
        "VALIDATION_PASSED": (
            "manage_git",
            "commit_preview",
            "Validation passed; the next bounded Git step is a commit preview, not commit apply.",
            {"action": "commit_preview"},
        ),
        "COMMIT_PENDING": (
            "manage_git",
            "commit_preview",
            "Changes are ready for Git review; create a dedicated commit preview.",
            {"action": "commit_preview"},
        ),
        "CONTEXT_CHANGED": (
            "analyze_project_state",
            "inspect",
            "Context changed after the prior projection; refresh canonical state.",
            {},
        ),
        "PREVIEW_EXPIRED": (
            "analyze_project_state",
            "inspect",
            "The prior preview expired; refresh state before creating a new typed preview.",
            {},
        ),
        "REVIEW_TASK": (
            "review_manifest",
            "inspect",
            "Review work should begin with immutable manifest evidence.",
            {"action": "inspect"},
        ),
        "PARALLEL_STAGE": (
            "get_stage_parallel_next_action_packet",
            "inspect",
            "Read the stage state machine before selecting the next shard or merge gate.",
            {},
        ),
        "BLOCKED_WORK_ITEM": (
            "get_work_item_governance_status",
            "inspect",
            "Read the governed blocker before proposing a transition.",
            {},
        ),
        "STABLE_PROMOTION_NOT_READY": (
            "get_stable_promotion_readiness",
            "inspect",
            "Stable promotion is not ready; inspect its evidence gate without mutating Stable.",
            {},
        ),
        "PROJECT_INSPECTION": (
            "analyze_project_state",
            "inspect",
            "Read canonical project facts before selecting a workflow.",
            {},
        ),
        "SOURCE_ONLY": (
            "run_mcp_workflow",
            "auto_preview",
            "The canonical checkout is source-only; request the existing bounded onboarding preview.",
            {"workflow": "auto_preview"},
        ),
        "READY_TO_EXECUTE": (
            "run_mcp_workflow",
            "auto_preview",
            "Canonical Runner state has pending work; route the bounded task through auto_preview.",
            {"workflow": "auto_preview"},
        ),
        "ACTION_REQUIRED": (
            "manage_git",
            "review_context",
            "Canonical state reports a dirty delivery worktree; inspect its bounded Git context first.",
            {"action": "review_context"},
        ),
        "FRESHNESS_REQUIRED": (
            "analyze_project_state",
            "inspect",
            "Current observations are incomplete or stale; refresh canonical project state.",
            {},
        ),
        "PARTIAL_OBSERVATION": (
            "analyze_project_state",
            "inspect",
            "Some canonical state sources are unavailable; refresh the read-only observation.",
            {},
        ),
        "BLOCKED": (
            "analyze_project_state",
            "inspect",
            "Canonical project state is blocked; inspect the reported blockers before any transition.",
            {},
        ),
        "WAITING_FOR_EXECUTOR_RESULTS": (
            "get_stage_parallel_executor_results_packet",
            "inspect",
            "The production stage packet reports running executors; read results instead of starting duplicates.",
            {},
        ),
        "READY_FOR_MERGE_PREVIEW": (
            "get_stage_parallel_merge_preview",
            "inspect",
            "The stage packet proves executor results are ready for the bounded merge preview.",
            {},
        ),
        "NOT_READY_FOR_STABLE_PROMOTION_REVIEW": (
            "get_stable_promotion_readiness",
            "inspect",
            "Stable promotion readiness reports local blockers; remain on its read-only evidence surface.",
            {},
        ),
    }
    rule = rules.get(status)
    if rule is None:
        return None
    tool, action, reason, required_arguments = rule
    if intent and tool == "run_mcp_workflow":
        required_arguments = {**required_arguments, "goal": intent}
    return {
        "tool": tool,
        "action": action,
        "reason": reason,
        "required_arguments": required_arguments,
        "optional_arguments": {},
    }


def _preview_handle_from_action(
    value: Mapping[str, Any],
) -> tuple[str, str, tuple[str, ...], str, str | None] | None:
    arguments = _as_dict(value.get("arguments"))
    if not arguments:
        arguments = _as_dict(value.get("params"))
    if not arguments:
        arguments = _as_dict(value.get("required_arguments"))
    if not arguments:
        arguments = _as_dict(_as_dict(value.get("copyable_tool_call")).get("arguments"))
    preview_id = arguments.get("preview_id") or value.get("preview_id")
    if not isinstance(preview_id, str) or not preview_id:
        return None
    tool = value.get("tool") or _as_dict(value.get("copyable_tool_call")).get("tool")
    action = (
        arguments.get("phase")
        if tool == "run_mcp_workflow"
        else arguments.get("action")
    )
    if not isinstance(action, str) or not action:
        action = arguments.get("action") or arguments.get("phase")
    actions = (action,) if isinstance(action, str) and action else ()
    expires_at = value.get("expires_at")
    return (
        "preview_id",
        "preview",
        actions,
        preview_id,
        expires_at if isinstance(expires_at, str) else None,
    )


def _walk_for_handle(value: Any, depth: int = 0) -> tuple[str, str, tuple[str, ...], str, str | None] | None:
    if depth > 5:
        return None
    if isinstance(value, (list, tuple)):
        for item in value:
            found = _walk_for_handle(item, depth + 1)
            if found is not None:
                return found
        return None
    if isinstance(value, Mapping):
        for field_name, kind, actions in _HANDLE_SPECS:
            if field_name == "preview_id":
                continue
            candidate = value.get(field_name)
            if isinstance(candidate, str) and candidate:
                expires_at = value.get("expires_at")
                return field_name, kind, actions, candidate, expires_at if isinstance(expires_at, str) else None
        action_handle = _preview_handle_from_action(value)
        if action_handle is not None:
            return action_handle
        for key in (
            "primary_next_action",
            "next_action",
            "next_actions",
            "recommended_next_actions",
            "arguments",
            "params",
            "confirmation",
            "result",
            "facts",
            "data",
        ):
            if key in value:
                found = _walk_for_handle(value[key], depth + 1)
                if found is not None:
                    return found
        preview_id = value.get("preview_id")
        if isinstance(preview_id, str) and preview_id:
            expires_at = value.get("expires_at")
            return (
                "preview_id",
                "preview",
                (),
                preview_id,
                expires_at if isinstance(expires_at, str) else None,
            )
        preview_ids = value.get("preview_ids")
        if isinstance(preview_ids, list) and len(preview_ids) == 1 and isinstance(preview_ids[0], str):
            return "preview_id", "preview", (), preview_ids[0], None
    return None


def typed_continuation_projection(response: Mapping[str, Any], *, source_tool: str) -> dict[str, Any] | None:
    found = _walk_for_handle(response)
    if found is None:
        return None
    field_name, kind, actions, identifier, expires_at = found
    continuation = {
        "kind": kind,
        "id": identifier,
        "field_name": field_name,
        "source_tool": source_tool,
        "allowed_next_actions": list(actions),
        "typed_handle_required_by_next_tool": True,
        "continuation_is_navigation_only": True,
        "does_not_grant_authority": True,
    }
    if expires_at is not None:
        continuation["expires_at"] = expires_at
    if not actions:
        continuation["why_no_allowed_next_action"] = (
            "The preview handle alone does not prove which workflow action may consume it."
        )
    return continuation


def infer_error_origin(error_code: str | None, explicit_origin: str | None = None) -> str:
    allowed = {
        "colameta_application",
        "colameta_workflow",
        "colameta_state_gate",
        "connector",
        "oauth",
        "transport",
        "host",
        "external_provider",
        "unknown",
    }
    if explicit_origin in allowed:
        return explicit_origin
    code = (error_code or "").upper()
    if "CONNECTOR" in code:
        return "connector"
    if any(marker in code for marker in ("OAUTH", "SCOPE", "AUTHORIZATION", "PRINCIPAL")):
        return "oauth"
    if "TRANSPORT" in code:
        return "transport"
    if "HOST" in code:
        return "host"
    if any(marker in code for marker in ("PREVIEW", "CONTEXT", "HEAD_CHANGED", "CONFIRMATION", "PREREQUISITE")):
        return "colameta_state_gate"
    if "WORKFLOW" in code or "TRANSITION" in code:
        return "colameta_workflow"
    return "colameta_application" if code else "unknown"


def recovery_projection(
    error_code: str | None,
    *,
    reason: str = "",
    error_origin: str | None = None,
) -> dict[str, Any] | None:
    if not error_code:
        return None
    code = error_code.upper()
    origin = infer_error_origin(code, error_origin)
    recovery_class = "operator_action_required"
    recommended_action = "Stop and inspect the unclassified ColaMeta error before choosing a recovery action."
    agent_should_stop = True
    retryable = False
    if code in _RETRY_SAME_CALL_ERROR_CODES:
        recovery_class = "retry_same_call"
        recommended_action = "Retry the same bounded call; this exact error is classified as transient and idempotent."
        agent_should_stop = False
        retryable = True
    elif any(marker in code for marker in ("PREVIEW_EXPIRED", "PREVIEW_NOT_FOUND", "PREVIEW_STALE")):
        recovery_class = "new_preview_required"
        recommended_action = "Create a new preview from current project state; do not reuse the old typed handle."
        agent_should_stop = False
        retryable = True
    elif any(marker in code for marker in ("CONTEXT_BINDING_MISMATCH", "HEAD_CHANGED", "PROJECT_CHANGED")):
        recovery_class = "context_changed"
        recommended_action = "Refresh canonical project state, then create a new context-bound preview."
        agent_should_stop = False
        retryable = True
    elif any(marker in code for marker in ("RUNNING", "IN_PROGRESS", "ALREADY_CLAIMED")):
        recovery_class = "wait_for_running_operation"
        recommended_action = "Poll the existing typed run or workflow handle; do not start a duplicate operation."
        agent_should_stop = False
        retryable = True
    elif origin in {"connector", "transport", "host", "external_provider", "unknown"}:
        recovery_class = "operator_action_required"
        recommended_action = "Inspect the external boundary; ColaMeta cannot prove an automatic recovery path."
        agent_should_stop = True
        retryable = True
    elif any(
        marker in code
        for marker in (
            "INSUFFICIENT_SCOPE",
            "SCOPE_REQUIRED",
            "SCOPE_MISMATCH",
            "SCOPE_VIOLATION",
            "AUTHORIZATION_REQUIRED",
        )
    ):
        recovery_class = "authorization_required"
        recommended_action = "Obtain the missing scope through the existing authorization flow, then retry."
        agent_should_stop = True
        retryable = True
    elif any(marker in code for marker in ("CONFIRMATION_REQUIRED", "CONFIRMATION_MISSING")):
        recovery_class = "operator_action_required"
        recommended_action = "Ask the operator to confirm the exact preview and context binding."
        agent_should_stop = True
        retryable = True
    elif "VALIDATION_FAILED" in code:
        recovery_class = "operator_action_required"
        recommended_action = "Inspect validation evidence, repair the failure, and create any required new preview."
        agent_should_stop = False
        retryable = True
    elif any(marker in code for marker in ("UNSUPPORTED", "NOT_SUPPORTED", "UNKNOWN_ACTION", "INVALID_WORKFLOW")):
        recovery_class = "unsupported_by_current_surface"
        recommended_action = "Use a documented supported action or escalate to an advanced tool without bypassing gates."
        agent_should_stop = False
        retryable = False
    elif code == "AUTHORITY_MISMATCH" or code.endswith("_HARD_STOP"):
        recovery_class = "hard_stop"
        recommended_action = "Stop and obtain new authoritative evidence or operator direction."
        agent_should_stop = True
        retryable = False
    elif "PREREQUISITE" in code or "NOT_READY" in code:
        recovery_class = "refresh_state_then_retry"
        recommended_action = "Refresh canonical state and satisfy the reported prerequisite before retrying."
        agent_should_stop = False
        retryable = True
    return {
        "recovery_class": recovery_class,
        "reason": reason or error_code,
        "recommended_action": recommended_action,
        "agent_should_stop": agent_should_stop,
        "retryable": retryable,
        "error_origin": origin,
        "recovery_is_navigation_only": True,
        "does_not_grant_authority": True,
    }


def authority_projection() -> dict[str, Any]:
    def scope(scope_name: str) -> dict[str, Any]:
        return {
            "status": "INDEPENDENT_SCOPE_AND_GATE_REQUIRED",
            "required_scope": scope_name,
            "granted_by_projection": False,
        }

    return {
        "read": scope("mcp:read"),
        "preview": scope("mcp:preview"),
        "execute": {
            "status": "TYPED_PREVIEW_CONTEXT_AND_CONFIRMATION_REQUIRED",
            "granted_by_projection": False,
        },
        "validate": {
            "status": "ACTION_DEPENDENT_SCOPE_AND_GATE_REQUIRED",
            "scope_by_action": {
                "inspect": "mcp:read",
                "preview": "mcp:preview",
                "run": "mcp:commit",
            },
            "granted_by_projection": False,
        },
        "commit": scope("mcp:commit"),
        "push": {
            "status": "DEDICATED_GIT_GATE_REQUIRED",
            "granted_by_projection": False,
        },
        "stable_replacement": {
            "status": "DEDICATED_STABLE_PROMOTION_GATE_REQUIRED",
            "granted_by_projection": False,
        },
        "projection_is_navigation_only": True,
        "projection_grants_no_authority": True,
    }


def _agent_state(
    response: Mapping[str, Any],
    *,
    project_name: str | None,
    goal: str | None,
    profile_id: str | None,
) -> dict[str, Any]:
    sources = _projection_sources(response)
    identity = next(
        (_as_dict(source.get("project_identity")) for source in sources if source.get("project_identity")),
        {},
    )
    canonical = next(
        (
            _as_dict(source.get("canonical_state") or source.get("canonical_project_state"))
            for source in sources
            if isinstance(source.get("canonical_state") or source.get("canonical_project_state"), Mapping)
        ),
        {},
    )
    canonical_context = _as_dict(canonical.get("context_binding"))
    canonical_observed = _as_dict(canonical.get("currently_observed"))
    canonical_runner = _as_dict(canonical_observed.get("runner"))
    conclusion = _as_dict(canonical.get("current_conclusion"))
    nested_result = _as_dict(response.get("result"))
    current_state = next(
        (_as_dict(source.get("current_state")) for source in sources if source.get("current_state")),
        {},
    )
    runner = next((_as_dict(source.get("runner")) for source in sources if source.get("runner")), {})
    plan = next((_as_dict(source.get("plan")) for source in sources if source.get("plan")), {})
    current_version = (
        canonical_context.get("current_version")
        or canonical_runner.get("current_version")
        or nested_result.get("current_version")
        or response.get("current_version")
        or current_state.get("current_version")
        or canonical.get("current_version")
        or runner.get("current_version")
        or plan.get("current_version")
    )
    current_phase = (
        nested_result.get("phase")
        or response.get("phase")
        or current_state.get("current_phase")
        or canonical.get("phase")
        or runner.get("phase")
        or plan.get("phase")
    )
    readiness = _as_dict(current_state.get("readiness"))
    status = (
        nested_result.get("status")
        or conclusion.get("status")
        or current_state.get("status")
        or readiness.get("status")
        or response.get("status")
        or response.get("mode")
        or "unknown"
    )
    agent_state = {
        "project": project_name or _first_text(sources, "project_name") or identity.get("project_name"),
        "goal": goal,
        "current_phase": current_phase,
        "current_version": current_version,
        "status": status,
        "profile_id": profile_id,
        "state_is_observation_not_authority": True,
    }
    operation_status = response.get("status")
    if isinstance(operation_status, str) and operation_status != status:
        agent_state["operation_status"] = operation_status
    return agent_state


def _blocked_next_actions(
    response: Mapping[str, Any],
    *,
    primary_action: Mapping[str, Any] | None,
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    blockers = _as_string_list(response.get("blockers"))
    if blockers:
        items.append(
            {
                "tool": primary_action.get("tool") if primary_action else "analyze_project_state",
                "action": primary_action.get("action") if primary_action else "inspect",
                "reason": "; ".join(blockers[:5]),
            }
        )
    if response.get("requires_confirmation") is True:
        items.append(
            {
                "tool": primary_action.get("tool") if primary_action else "run_mcp_workflow",
                "action": "apply_or_run",
                "reason": "The current preview still requires explicit operator confirmation and its original typed binding.",
            }
        )
    for tool, action, reason in (
        ("manage_git", "commit_apply", "A navigation response is not commit authority; a dedicated commit preview must pass."),
        ("manage_git", "push_apply", "Push remains behind its independent Git remote and confirmation gate."),
        (
            "manage_stable_promotion_evidence",
            "apply",
            "Stable replacement remains behind its dedicated evidence and authorization gate.",
        ),
    ):
        items.append({"tool": tool, "action": action, "reason": reason})
    return {
        "exhaustive": False,
        "items": items,
        "navigation_only": True,
        "does_not_define_an_allowlist": True,
    }


def add_agent_state_projection(
    response: Mapping[str, Any],
    *,
    source_tool: str,
    profile_id: str | None = None,
    project_name: str | None = None,
    goal: str | None = None,
    primary_action: Mapping[str, Any] | None = None,
    error_origin: str | None = None,
    enforce_profile_reachability: bool = False,
) -> dict[str, Any]:
    projected = dict(response)
    _bind_top_level_actions_to_project(projected, project_name)
    allowed_tools = (
        _profile_allowed_tools(profile_id) if enforce_profile_reachability else None
    )
    selected = (
        primary_action
        if isinstance(primary_action, Mapping)
        and _action_reachable(primary_action, allowed_tools)
        else None
    )
    if selected is None:
        selected = _first_action(
            projected,
            source_tool=source_tool,
            allowed_tools=allowed_tools,
        )
    if selected is None:
        selected = select_primary_action_from_state(projected, intent=goal)
    if isinstance(selected, Mapping) and not _action_reachable(selected, allowed_tools):
        selected = None
    normalized_action = normalize_agent_action(
        selected,
        source_tool=source_tool,
        project_name=project_name,
    )
    projected["agent_projection_schema_version"] = AGENT_PROJECTION_SCHEMA_VERSION
    projected["agent_state"] = _agent_state(
        projected,
        project_name=project_name,
        goal=goal,
        profile_id=profile_id,
    )
    projected.setdefault("completed", [])
    projected.setdefault("pending", [])
    projected.setdefault("blocked", _as_string_list(projected.get("blockers")))
    projected["authority"] = authority_projection()
    projected["primary_next_action"] = normalized_action
    if normalized_action is None:
        projected["why_no_unique_action"] = (
            "Current facts do not prove one unique safe next action; refresh state or provide a bounded goal."
        )
    projected["blocked_next_actions"] = _blocked_next_actions(
        projected,
        primary_action=normalized_action,
    )
    projected["continuation"] = typed_continuation_projection(projected, source_tool=source_tool)
    sources = _projection_sources(projected)
    error_code = _first_text(sources, "error_code")
    detected_origin = _first_text(sources, "error_origin")
    detected_message = _first_text(sources, "message", "reason") or ""
    if error_code and "error_code" not in projected:
        projected["error_code"] = error_code
    projected["error_origin"] = infer_error_origin(
        error_code,
        error_origin or detected_origin,
    ) if error_code else None
    projected["recovery"] = recovery_projection(
        error_code,
        reason=detected_message,
        error_origin=error_origin or detected_origin,
    )
    projected["hard_stops"] = list(_HARD_STOPS)
    projected["routing"] = {
        "source": tool_routing_metadata(source_tool),
        "profile": profile_guidance(profile_id),
        "selected_workflow": projected.get("selected_workflow"),
        "routing_metadata_is_navigation_only": True,
        "routing_metadata_grants_no_authority": True,
    }
    return projected
