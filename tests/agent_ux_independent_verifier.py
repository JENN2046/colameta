from __future__ import annotations

from collections.abc import Mapping
from typing import Any


_TYPED_FIELDS = {
    "review_manifest": "review_manifest_id",
    "result_artifact": "artifact_id",
    "executor_run": "run_id",
    "workflow_run": "workflow_id",
    "gate_preview": "gate_preview_id",
    "batch_preview": "batch_preview_id",
    "plan_patch": "patch_id",
    "preview": "preview_id",
}

_VALID_SCOPES = {"mcp:read", "mcp:preview", "mcp:plan", "mcp:commit"}


def verify_agent_projection(packet: Mapping[str, Any]) -> list[str]:
    """Independently check the public projection without importing its builder."""

    findings: list[str] = []
    primary = packet.get("primary_next_action")
    if primary is None:
        if not packet.get("why_no_unique_action"):
            findings.append("null primary action lacks why_no_unique_action")
    elif not isinstance(primary, Mapping):
        findings.append("primary_next_action is not an object or null")
    elif primary.get("does_not_grant_authority") is not True:
        findings.append("primary action is not explicitly navigation-only")

    blocked = packet.get("blocked_next_actions")
    if not isinstance(blocked, Mapping):
        findings.append("blocked_next_actions missing")
    elif blocked.get("exhaustive") is not False:
        findings.append("blocked_next_actions must be explicitly non-exhaustive")

    authority = packet.get("authority")
    if not isinstance(authority, Mapping):
        findings.append("authority projection missing")
    else:
        for name in ("read", "preview", "execute", "validate", "commit", "push", "stable_replacement"):
            scope = authority.get(name)
            if not isinstance(scope, Mapping) or scope.get("granted_by_projection") is not False:
                findings.append(f"projection appears to grant {name} authority")
                continue
            required_scope = scope.get("required_scope")
            if required_scope is not None and required_scope not in _VALID_SCOPES:
                findings.append(f"{name} contains a non-protocol scope")
            scope_by_action = scope.get("scope_by_action")
            if isinstance(scope_by_action, Mapping) and any(
                value not in _VALID_SCOPES for value in scope_by_action.values()
            ):
                findings.append(f"{name} contains a non-protocol action scope")

    continuation = packet.get("continuation")
    if continuation is not None:
        if not isinstance(continuation, Mapping):
            findings.append("continuation is not an object or null")
        else:
            expected_field = _TYPED_FIELDS.get(str(continuation.get("kind")))
            if expected_field is None or continuation.get("field_name") != expected_field:
                findings.append("continuation kind does not match its typed field")
            if "continuation_id" in continuation:
                findings.append("generic continuation_id is forbidden")
            if continuation.get("does_not_grant_authority") is not True:
                findings.append("continuation is not explicitly navigation-only")
            allowed_actions = continuation.get("allowed_next_actions")
            if not isinstance(allowed_actions, list) or any(
                not isinstance(action, str) or not action
                for action in allowed_actions
            ):
                findings.append("continuation allowed actions are malformed")
            if (
                continuation.get("kind") == "preview"
                and allowed_actions == []
                and not continuation.get("why_no_allowed_next_action")
            ):
                findings.append("context-free preview lacks a fail-closed explanation")
            if continuation.get("kind") == "workflow_run":
                if continuation.get("consumer_tool") != "manage_workflow_run":
                    findings.append("workflow continuation lacks its canonical consumer tool")
                if allowed_actions != ["get"]:
                    findings.append("workflow continuation advertises an invalid consumer action")
            if (
                continuation.get("kind") == "executor_run"
                and allowed_actions != ["status"]
            ):
                findings.append("executor continuation advertises an invalid consumer action")

    routing = packet.get("routing")
    if not isinstance(routing, Mapping) or routing.get("routing_metadata_grants_no_authority") is not True:
        findings.append("routing authority separation missing")
    return findings


def verify_authority_expectation(packet: Mapping[str, Any], expectation: str) -> list[str]:
    """Mechanically evaluate fixture authority expectations."""

    findings: list[str] = []
    authority = packet.get("authority")
    if not isinstance(authority, Mapping):
        return ["authority projection missing"]

    def denied(name: str) -> bool:
        value = authority.get(name)
        return isinstance(value, Mapping) and value.get("granted_by_projection") is False

    if not all(denied(name) for name in ("read", "preview", "execute", "validate", "commit", "push", "stable_replacement")):
        findings.append("projection widened at least one authority gate")

    primary = packet.get("primary_next_action")
    action = primary.get("action") if isinstance(primary, Mapping) else None
    recovery = packet.get("recovery")
    recovery_class = recovery.get("recovery_class") if isinstance(recovery, Mapping) else None

    checks = {
        "NO_AUTHORITY_FROM_PROJECTION": lambda: True,
        "PREVIEW_GATE_REMAINS_REQUIRED": lambda: denied("preview"),
        "EXECUTOR_AUTHORITY_NOT_GRANTED": lambda: denied("execute"),
        "NO_DUPLICATE_EXECUTOR_START": lambda: denied("execute") and action == "status",
        "VALIDATION_GATE_REMAINS_REQUIRED": lambda: denied("validate"),
        "COMMIT_AUTHORITY_NOT_GRANTED": lambda: denied("commit"),
        "COMMIT_PREVIEW_ONLY": lambda: denied("commit"),
        "NEW_PREVIEW_REQUIRED": lambda: denied("preview") and recovery_class in {"new_preview_required", "context_changed"},
        "SCOPE_NOT_WIDENED": lambda: recovery_class == "authorization_required",
        "REVIEW_ONLY": lambda: denied("execute") and denied("commit"),
        "STAGE_GATE_REMAINS_REQUIRED": lambda: denied("execute"),
        "TRANSITION_AUTHORITY_NOT_GRANTED": lambda: denied("execute"),
        "STABLE_AUTHORITY_NOT_GRANTED": lambda: denied("stable_replacement"),
    }
    check = checks.get(expectation)
    if check is None:
        findings.append(f"unknown authority expectation: {expectation}")
    elif not check():
        findings.append(f"authority expectation not met: {expectation}")
    return findings
