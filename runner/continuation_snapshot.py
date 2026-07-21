from __future__ import annotations

import hashlib
import json
import os
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from runner.executor_session import (
    ExecutorSessionStore,
    add_continuation_compatibility_fields,
    build_canonical_continuation_decision,
)
from runner.planning_bridge import PlanningBridge
from runner.project_operation_lease import ProjectOperationLease
from runner.source_review_bridge import SourceReviewBridge


CONTINUATION_SNAPSHOT_SCHEMA_VERSION = "continuation_snapshot.v1"
_CURRENT_CONTINUATION_SNAPSHOT: ContextVar[Any] = ContextVar(
    "colameta_continuation_snapshot",
    default=None,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_provider(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    return normalized if normalized in {"pi", "codex", "opencode"} else None


def _digest(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _snapshot_id(project_root: str, observed_at: str, facts: dict[str, Any]) -> str:
    return "cs_" + _digest(
        {
            "project_root": project_root,
            "observed_at": observed_at,
            "capture_nonce": uuid.uuid4().hex,
            "facts": facts,
        }
    )[:32]


def _identity_binding(session_status: dict[str, Any]) -> tuple[str | None, str | None]:
    record = session_status.get("record") if isinstance(session_status, dict) else None
    record = record if isinstance(record, dict) else {}
    for kind, key in (
        ("conversation_id", "conversation_id"),
        ("session_id", "session_id"),
        ("session_file", "session_file"),
    ):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return kind, hashlib.sha256(value.strip().encode("utf-8")).hexdigest()
    return None, None


def _activity_evidence(project_root: str) -> dict[str, Any]:
    from runner.executor_read import handle_inspect_executor_activity

    result = handle_inspect_executor_activity(project_root, "latest_run_status", {})
    if not isinstance(result, dict):
        return {}
    live = result.get("live")
    if not isinstance(live, dict):
        stale = result.get("stale_orphan_claim")
        live = stale if isinstance(stale, dict) else None
    latest_claim_status = None
    if isinstance(live, dict):
        latest_claim_status = live.get("claim_status")
        claim = live.get("claim")
        if latest_claim_status is None and isinstance(claim, dict):
            latest_claim_status = claim.get("status")
    return {
        "latest_run_status": result.get("status"),
        "latest_claim_status": latest_claim_status,
        "live_run": live,
    }


@dataclass
class ContinuationSnapshot:
    project_root: str
    snapshot_id: str
    observed_at: str
    snapshot_status: str
    fact_bundle: dict[str, Any]
    session_status: dict[str, Any]
    continuation_preview: dict[str, Any]
    activity_evidence: dict[str, Any]
    operation_lock_observation: dict[str, Any]
    partial_errors: list[dict[str, str]] = field(default_factory=list)
    _projection_cache: dict[str, dict[str, Any]] = field(default_factory=dict, repr=False)

    def project(self, requested_provider: str | None = None) -> dict[str, Any]:
        provider = _clean_provider(requested_provider)
        selected = _clean_provider(self.fact_bundle.get("selected_provider"))
        effective_provider = provider or selected
        cache_key = effective_provider or ""
        cached = self._projection_cache.get(cache_key)
        if cached is not None:
            return cached

        facts = dict(self.fact_bundle)
        facts["requested_provider"] = effective_provider
        provider_policy_allows_resume = effective_provider in {"codex", "opencode"}
        for capability in (
            "provider_resume_supported",
            "resume_invocation_verified",
        ):
            if capability in facts:
                # A projection may narrow captured capability evidence for a
                # different provider, but it must never upgrade an explicit
                # false (or another non-true value) to true.
                facts[capability] = bool(
                    facts.get(capability) is True
                    and provider_policy_allows_resume
                )
            else:
                facts[capability] = provider_policy_allows_resume
        store = ExecutorSessionStore(self.project_root)
        decision = add_continuation_compatibility_fields(
            build_canonical_continuation_decision(facts),
            project_root=self.project_root,
            manifest_file=store.manifest_file,
            preview=self.continuation_preview,
        )
        try:
            invocation = store.get_resume_invocation_preview(
                requested_provider=effective_provider,
                fact_bundle=facts,
                continuation_decision=decision,
            )
        except Exception as exc:
            invocation = {
                "ok": False,
                "error_code": "CONTINUATION_INVOCATION_UNAVAILABLE",
                "message": type(exc).__name__,
                "canonical_continuation_decision": decision,
            }
        projection = {
            "schema_version": CONTINUATION_SNAPSHOT_SCHEMA_VERSION,
            "snapshot_id": self.snapshot_id,
            "observed_at": self.observed_at,
            "snapshot_status": self.snapshot_status,
            "requested_provider": effective_provider,
            "session_status": self.session_status,
            "continuation_preview": self.continuation_preview,
            "activity_evidence": self.activity_evidence,
            "operation_lock_observation": self.operation_lock_observation,
            "canonical_continuation_decision": decision,
            "resume_invocation_preview": invocation,
            "partial_errors": list(self.partial_errors),
        }
        self._projection_cache[cache_key] = projection
        return projection

    def public_view(self, requested_provider: str | None = None) -> dict[str, Any]:
        projection = self.project(requested_provider)
        identity_kind, identity_binding = _identity_binding(self.session_status)
        decision = projection["canonical_continuation_decision"]
        classification = decision.get("head_mismatch_classification")
        classification = classification if isinstance(classification, dict) else {}
        public_classification = {
            key: classification.get(key)
            for key in (
                "status",
                "severity",
                "blocks_auto_resume",
                "blocks_auto_start",
                "operation_running",
                "job_idle",
                "reason",
                "allowed_next_actions",
                "evidence",
            )
            if key in classification
        }
        public_decision = {
            key: decision.get(key)
            for key in (
                "ok",
                "schema_version",
                "decision",
                "classification",
                "recommended_action",
                "reason",
                "severity",
                "decision_source",
                "resume_allowed",
                "start_new_allowed",
                "continuation_available",
                "identity_present",
                "provider_matches",
                "provider_resume_supported",
                "resume_invocation_verified",
                "requested_provider",
                "selected_provider",
                "hard_blockers",
                "risk_warnings",
            )
            if key in decision
        }
        if public_classification:
            public_decision["head_mismatch_classification"] = public_classification
        return {
            "schema_version": CONTINUATION_SNAPSHOT_SCHEMA_VERSION,
            "snapshot_id": self.snapshot_id,
            "observed_at": self.observed_at,
            "snapshot_status": self.snapshot_status,
            "requested_provider": projection.get("requested_provider"),
            "identity_kind": identity_kind,
            "identity_binding_sha256": identity_binding,
            "operation_lock_observation": dict(self.operation_lock_observation),
            "canonical_continuation_decision": public_decision,
            "partial_errors": list(self.partial_errors),
        }


@contextmanager
def continuation_snapshot_scope(snapshot: ContinuationSnapshot):
    token = _CURRENT_CONTINUATION_SNAPSHOT.set(snapshot)
    try:
        yield snapshot
    finally:
        _CURRENT_CONTINUATION_SNAPSHOT.reset(token)


def current_continuation_snapshot(project_root: str) -> ContinuationSnapshot | None:
    snapshot = _CURRENT_CONTINUATION_SNAPSHOT.get()
    if not isinstance(snapshot, ContinuationSnapshot):
        return None
    root = os.path.realpath(os.path.abspath(os.path.expanduser(project_root)))
    return snapshot if snapshot.project_root == root else None


def get_or_collect_continuation_snapshot(
    project_root: str,
    requested_provider: str | None = None,
    **kwargs: Any,
) -> ContinuationSnapshot:
    current = current_continuation_snapshot(project_root)
    if current is not None:
        return current
    return collect_continuation_snapshot(
        project_root,
        requested_provider=requested_provider,
        **kwargs,
    )


def snapshot_from_fact_bundle(
    project_root: str,
    fact_bundle: dict[str, Any],
    *,
    snapshot_status: str = "captured",
) -> ContinuationSnapshot:
    root = os.path.realpath(os.path.abspath(os.path.expanduser(project_root)))
    facts = dict(fact_bundle) if isinstance(fact_bundle, dict) else {}
    session_status = facts.get("executor_session_status")
    session_status = session_status if isinstance(session_status, dict) else {}
    preview = facts.get("continuation_preview")
    preview = preview if isinstance(preview, dict) else {}
    observed_at = _now_iso()
    snapshot_id = _snapshot_id(root, observed_at, facts)
    return ContinuationSnapshot(
        project_root=root,
        snapshot_id=snapshot_id,
        observed_at=observed_at,
        snapshot_status=snapshot_status,
        fact_bundle=facts,
        session_status=session_status,
        continuation_preview=preview,
        activity_evidence={},
        operation_lock_observation={
            "state": "injected",
            "operation_running": facts.get("operation_running"),
            "job_status": facts.get("job_status"),
        },
    )


def collect_continuation_snapshot(
    project_root: str,
    requested_provider: str | None = None,
    *,
    held_operation_lease: ProjectOperationLease | None = None,
    session_store: ExecutorSessionStore | None = None,
    planning_bridge: PlanningBridge | None = None,
    source_review: SourceReviewBridge | None = None,
) -> ContinuationSnapshot:
    root = os.path.realpath(os.path.abspath(os.path.expanduser(project_root)))
    observed_at = _now_iso()
    lease = held_operation_lease
    owns_read_lease = False

    if lease is not None:
        if not lease.held or lease.canonical_project_root != root or lease.shared:
            return _unavailable_snapshot(
                root,
                requested_provider,
                observed_at,
                status="operation_lease_invalid",
                reason="held_operation_lease_invalid",
            )
        lock_observation = {
            "state": "owned_exclusive",
            "operation_running": False,
            "job_status": "idle",
        }
    else:
        lease = ProjectOperationLease(root, shared=True, operation_kind="snapshot", surface="continuation_snapshot")
        acquire = lease.acquire()
        if not acquire.held:
            if acquire.status == "busy":
                return _active_operation_snapshot(root, requested_provider, observed_at)
            return _unavailable_snapshot(
                root,
                requested_provider,
                observed_at,
                status="operation_lock_unavailable",
                reason="project_operation_lock_unavailable",
            )
        owns_read_lease = True
        lock_observation = {
            "state": "shared_snapshot_lock",
            "operation_running": False,
            "job_status": "idle",
        }

    partial_errors: list[dict[str, str]] = []
    continuation_evidence_failed = False
    try:
        store = session_store or ExecutorSessionStore(root)
        try:
            session_status = store.get_status()
            session_status = session_status if isinstance(session_status, dict) else {}
        except Exception as exc:
            session_status = {}
            partial_errors.append(_error("executor_session_status", exc))
            continuation_evidence_failed = True
        try:
            continuation_preview = store.get_continuation_preview(session_status)
            continuation_preview = continuation_preview if isinstance(continuation_preview, dict) else {}
        except Exception as exc:
            continuation_preview = {}
            partial_errors.append(_error("executor_continuation_preview", exc))
            continuation_evidence_failed = True

        try:
            activity = _activity_evidence(root)
        except Exception as exc:
            activity = {}
            partial_errors.append(_error("executor_activity", exc))
        try:
            runner_status = (planning_bridge or PlanningBridge()).get_runner_status(root)
            runner_status = runner_status if isinstance(runner_status, dict) else {}
        except Exception as exc:
            runner_status = {}
            partial_errors.append(_error("runner_status", exc))
        try:
            git_status = (source_review or SourceReviewBridge()).get_git_status(root)
            worktree_clean: bool | None = not bool(git_status.get("status_short"))
        except Exception as exc:
            worktree_clean = None
            partial_errors.append(_error("git_status", exc))

        record = session_status.get("record") if isinstance(session_status, dict) else None
        record = record if isinstance(record, dict) else {}
        selected_provider = (
            _clean_provider(continuation_preview.get("selected_provider"))
            or _clean_provider(record.get("provider"))
        )
        effective_provider = _clean_provider(requested_provider) or selected_provider
        identity_present = any(
            isinstance(record.get(key), str) and bool(record.get(key).strip())
            for key in ("conversation_id", "session_id", "session_file")
        )
        facts = {
            "executor_session_status": session_status,
            "continuation_preview": continuation_preview,
            "selected_provider": selected_provider,
            "requested_provider": effective_provider,
            "identity_present": identity_present,
            "provider_resume_supported": effective_provider in {"codex", "opencode"},
            "resume_invocation_verified": effective_provider in {"codex", "opencode"},
            "hard_blockers": list(continuation_preview.get("hard_blockers") or continuation_preview.get("blockers") or []),
            "risk_warnings": list(continuation_preview.get("risk_warnings") or []),
            "operation_running": False,
            "job_status": "idle",
            "latest_run_status": activity.get("latest_run_status"),
            "latest_claim_status": activity.get("latest_claim_status"),
            "live_run": activity.get("live_run"),
            "runner_status": runner_status.get("runner_status"),
            "current_version_status": runner_status.get("current_version_status"),
            "worktree_clean": worktree_clean,
        }
        if continuation_evidence_failed:
            facts["continuation_evidence_fail_closed"] = True
            facts["continuation_evidence_failure_reason"] = "continuation_snapshot_core_evidence_error"
        snapshot_id = _snapshot_id(root, observed_at, facts)
        return ContinuationSnapshot(
            project_root=root,
            snapshot_id=snapshot_id,
            observed_at=observed_at,
            snapshot_status=(
                "captured_fail_closed"
                if continuation_evidence_failed
                else ("captured_partial" if partial_errors else "captured")
            ),
            fact_bundle=facts,
            session_status=session_status,
            continuation_preview=continuation_preview,
            activity_evidence=activity,
            operation_lock_observation=lock_observation,
            partial_errors=partial_errors,
        )
    finally:
        if owns_read_lease:
            lease.release()


def _active_operation_snapshot(
    project_root: str,
    requested_provider: str | None,
    observed_at: str,
) -> ContinuationSnapshot:
    facts = {
        "executor_session_status": {},
        "requested_provider": _clean_provider(requested_provider),
        "selected_provider": None,
        "identity_present": False,
        "provider_resume_supported": False,
        "resume_invocation_verified": False,
        "hard_blockers": ["project_operation_lock_busy"],
        "risk_warnings": [],
        "operation_running": True,
        "job_status": "running",
        "latest_run_status": "running",
        "runner_status": None,
        "current_version_status": None,
        "worktree_clean": None,
    }
    return ContinuationSnapshot(
        project_root=project_root,
        snapshot_id=_snapshot_id(project_root, observed_at, facts),
        observed_at=observed_at,
        snapshot_status="operation_active",
        fact_bundle=facts,
        session_status={},
        continuation_preview={},
        activity_evidence={},
        operation_lock_observation={
            "state": "busy",
            "operation_running": True,
            "job_status": "running",
        },
    )


def _unavailable_snapshot(
    project_root: str,
    requested_provider: str | None,
    observed_at: str,
    *,
    status: str,
    reason: str,
) -> ContinuationSnapshot:
    facts = {
        "executor_session_status": {},
        "requested_provider": _clean_provider(requested_provider),
        "selected_provider": None,
        "identity_present": False,
        "provider_resume_supported": False,
        "resume_invocation_verified": False,
        "hard_blockers": [reason],
        "risk_warnings": [],
        "operation_running": None,
        "job_status": None,
        "latest_run_status": None,
        "runner_status": None,
        "current_version_status": None,
        "worktree_clean": None,
        "continuation_evidence_fail_closed": True,
        "continuation_evidence_failure_reason": reason,
    }
    return ContinuationSnapshot(
        project_root=project_root,
        snapshot_id=_snapshot_id(project_root, observed_at, facts),
        observed_at=observed_at,
        snapshot_status=status,
        fact_bundle=facts,
        session_status={},
        continuation_preview={},
        activity_evidence={},
        operation_lock_observation={
            "state": "unavailable",
            "operation_running": None,
            "job_status": None,
        },
        partial_errors=[{"name": "project_operation_lock", "error_code": "CONTEXT_ERROR", "message": reason}],
    )


def _error(name: str, exc: Exception) -> dict[str, str]:
    return {
        "name": name,
        "error_code": "CONTEXT_ERROR",
        "message": type(exc).__name__,
    }
