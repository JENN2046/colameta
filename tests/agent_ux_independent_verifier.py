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

    routing = packet.get("routing")
    if not isinstance(routing, Mapping) or routing.get("routing_metadata_grants_no_authority") is not True:
        findings.append("routing authority separation missing")
    return findings
