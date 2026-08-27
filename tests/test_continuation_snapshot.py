from __future__ import annotations

import multiprocessing
import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from runner.continuation_snapshot import (
    _activity_evidence,
    collect_continuation_snapshot,
    snapshot_from_fact_bundle,
)
from runner.core_orchestrator import WorkflowOrchestrator
from runner.executor_run_claims import ExecutorRunClaimStore
from runner.executor_run_workflow import ExecutorRunOnceService
from runner.project_operation_lease import ProjectOperationLease
from runner.runner_paths import resolve_project_runner_rel_dir
from runner.web_console import WebConsoleServer


HEAD = "a" * 40
OTHER_HEAD = "b" * 40


def _hold_exclusive_lease(project_root: str, sender, release_event) -> None:
    lease = ProjectOperationLease(project_root, operation_kind="test", surface="child").acquire()
    sender.send(lease.public_status())
    sender.close()
    release_event.wait(10)
    lease.release()


def _facts(**overrides):
    status = {
        "ok": True,
        "active": True,
        "record": {
            "active": True,
            "provider": "codex",
            "current_head": HEAD,
            "base_head": HEAD,
            "conversation_id": "private-conversation-value",
            "resume_supported": True,
        },
        "current_head": HEAD,
        "matches_current_head": True,
    }
    facts = {
        "executor_session_status": status,
        "requested_provider": "codex",
        "selected_provider": "codex",
        "identity_present": True,
        "provider_resume_supported": True,
        "resume_invocation_verified": True,
        "operation_running": False,
        "job_status": "idle",
        "latest_run_status": "completed",
        "runner_status": "VERSION_PASSED",
        "current_version_status": "PASSED",
        "worktree_clean": True,
        "hard_blockers": [],
        "risk_warnings": [],
    }
    facts.update(overrides)
    return facts


class _NoSessionStore:
    def get_status(self):
        return {"ok": True, "active": False}

    def get_continuation_preview(self, status):
        return {"ok": True, "selected_provider": None, "hard_blockers": []}


class _PassingRunner:
    def get_runner_status(self, project_root):
        return {
            "runner_status": "VERSION_PASSED",
            "current_version_status": "PASSED",
        }


class _ReadyNotStartedRunner:
    def get_runner_status(self, project_root):
        return {
            "runner_status": "READY",
            "current_version_status": "NOT_STARTED",
        }


class _CleanGit:
    def get_git_status(self, project_root):
        return {"status_short": []}


def _write_running_claim(
    project_root: Path,
    *,
    preview_id: str,
    run_id: str,
    claimed_at: str,
) -> None:
    store = ExecutorRunClaimStore(
        str(project_root),
        os.path.join(
            resolve_project_runner_rel_dir(str(project_root)),
            "runtime",
            "executor-workflow-previews",
        ),
        "claims",
        5,
        3,
        20,
    )
    os.makedirs(store.claims_root, mode=0o700, exist_ok=True)
    for path in (
        project_root / resolve_project_runner_rel_dir(str(project_root)),
        Path(store.previews_root).parent,
        Path(store.previews_root),
        Path(store.claims_root),
    ):
        path.chmod(0o700)
    store.write_claim(
        preview_id,
        {
            "schema_version": "executor_run_claim.v1",
            "preview_id": preview_id,
            "run_id": run_id,
            "artifact_kind": "run_once",
            "project_root": str(project_root),
            "provider": "codex",
            "execution_mode": "run",
            "current_version": "v1",
            "current_head": HEAD,
            "status": "RUNNING",
            "claimed_at": claimed_at,
            "model": None,
            "model_source": None,
            "worker_pid": os.getpid(),
            "worker_started_at": claimed_at,
            "thread_started_at": claimed_at,
            "last_heartbeat_at": claimed_at,
            "heartbeat_interval_seconds": 5,
            "heartbeat_timeout_seconds": 20,
            "original_preview_created_at": claimed_at,
            "original_preview_expires_at": "2099-01-02T00:00:00+00:00",
        },
    )


def test_one_snapshot_projects_same_decision_to_analyze_thin_loop_and_web(tmp_path: Path) -> None:
    snapshot = snapshot_from_fact_bundle(str(tmp_path), _facts())
    orchestrator = WorkflowOrchestrator(
        str(tmp_path),
        continuation_snapshot=snapshot,
    )

    analyze = orchestrator.build_fact_snapshot(provider="codex", include_reports=False)
    guidance = orchestrator._thin_loop_executor_session_guidance(
        provider="codex",
        continuation_snapshot=snapshot,
    )
    server = WebConsoleServer.__new__(WebConsoleServer)
    server.project_root = str(tmp_path)
    server._continuation_snapshot_supplier = lambda provider: snapshot
    web_data: dict = {}
    server._apply_executor_session_head_mismatch_classification(
        web_data,
        requested_provider="codex",
        continuation_snapshot=snapshot,
    )

    expected = snapshot.project("codex")["canonical_continuation_decision"]
    assert analyze._executor_raw["canonical_continuation_decision"] is expected
    assert guidance["canonical_continuation_decision"] is expected
    assert web_data["executor_continuation_decision"] is expected
    assert analyze._executor_raw["continuation_snapshot"]["snapshot_id"] == snapshot.snapshot_id
    assert guidance["continuation_snapshot"]["snapshot_id"] == snapshot.snapshot_id
    assert web_data["continuation_snapshot"]["snapshot_id"] == snapshot.snapshot_id

    public_text = str(snapshot.public_view("codex"))
    assert "private-conversation-value" not in public_text
    assert HEAD not in public_text
    assert snapshot.public_view("codex")["identity_binding_sha256"]


def test_exclusive_operation_makes_snapshot_fail_closed_without_fact_reads(tmp_path: Path) -> None:
    class ExplodingStore:
        def get_status(self):
            raise AssertionError("fact reader must not run while operation lock is busy")

    lease = ProjectOperationLease(
        str(tmp_path),
        operation_kind="test_operation",
        surface="test",
    ).acquire()
    assert lease.held
    try:
        snapshot = collect_continuation_snapshot(
            str(tmp_path),
            requested_provider="codex",
            session_store=ExplodingStore(),
        )
    finally:
        lease.release()

    decision = snapshot.project("codex")["canonical_continuation_decision"]
    assert snapshot.snapshot_status == "operation_active"
    assert snapshot.operation_lock_observation["state"] == "busy"
    assert decision["recommended_action"] == "human_review"
    assert decision["resume_allowed"] is False
    assert decision["start_new_allowed"] is False


@pytest.mark.skipif(os.name != "posix", reason="POSIX flock lease")
def test_cross_process_busy_snapshot_fails_closed_without_fact_reads(tmp_path: Path) -> None:
    class ExplodingStore:
        def get_status(self):
            raise AssertionError("fact reader must not run while child owns the lease")

    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    release_event = context.Event()
    process = context.Process(
        target=_hold_exclusive_lease,
        args=(str(tmp_path), sender, release_event),
    )
    process.start()
    sender.close()
    try:
        assert receiver.recv()["status"] == "acquired"
        snapshot = collect_continuation_snapshot(
            str(tmp_path),
            requested_provider="codex",
            session_store=ExplodingStore(),
        )
    finally:
        receiver.close()
        release_event.set()
        process.join(10)

    assert process.exitcode == 0
    decision = snapshot.project("codex")["canonical_continuation_decision"]
    assert snapshot.snapshot_status == "operation_active"
    assert decision["recommended_action"] == "human_review"
    assert decision["resume_allowed"] is False
    assert decision["start_new_allowed"] is False


def test_snapshot_lock_error_is_inspect_evidence(tmp_path: Path) -> None:
    tmp_path.chmod(0o777)

    snapshot = collect_continuation_snapshot(
        str(tmp_path),
        requested_provider="codex",
    )

    decision = snapshot.project("codex")["canonical_continuation_decision"]
    assert snapshot.snapshot_status == "operation_lock_unavailable"
    assert decision["recommended_action"] == "inspect_evidence"
    assert decision["resume_allowed"] is False
    assert decision["start_new_allowed"] is False


def test_idle_snapshot_is_stable_after_underlying_git_changes(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    captured = collect_continuation_snapshot(str(tmp_path), requested_provider="codex")
    before = captured.project("codex")

    (tmp_path / "later.txt").write_text("later", encoding="utf-8")
    after = captured.project("codex")

    assert before is after
    assert before["canonical_continuation_decision"] is after["canonical_continuation_decision"]
    assert captured.public_view("codex")["snapshot_id"] == captured.snapshot_id


def test_optional_runner_and_git_errors_do_not_hide_verified_no_session(tmp_path: Path) -> None:
    class NoSessionStore:
        def get_status(self):
            return {"ok": True}

        def get_continuation_preview(self, status):
            return {"ok": True, "selected_provider": None, "hard_blockers": []}

    class MissingRunner:
        def get_runner_status(self, project_root):
            raise RuntimeError("runner unavailable")

    class MissingGit:
        def get_git_status(self, project_root):
            raise RuntimeError("git unavailable")

    snapshot = collect_continuation_snapshot(
        str(tmp_path),
        requested_provider="codex",
        session_store=NoSessionStore(),
        planning_bridge=MissingRunner(),
        source_review=MissingGit(),
    )

    decision = snapshot.project("codex")["canonical_continuation_decision"]
    assert snapshot.snapshot_status == "captured_partial"
    assert {item["name"] for item in snapshot.partial_errors} == {"runner_status", "git_status"}
    assert decision["classification"] == "no_session"
    assert decision["recommended_action"] == "start_new"


def test_runtime_snapshot_excludes_current_run_claim(tmp_path: Path) -> None:
    _write_running_claim(
        tmp_path,
        preview_id="preview-self",
        run_id="run-self",
        claimed_at="2099-01-01T00:00:02+00:00",
    )

    snapshot = collect_continuation_snapshot(
        str(tmp_path),
        requested_provider="codex",
        current_run_id="run-self",
        session_store=_NoSessionStore(),
        planning_bridge=_PassingRunner(),
        source_review=_CleanGit(),
    )

    decision = snapshot.project("codex")["canonical_continuation_decision"]
    assert snapshot.activity_evidence["latest_run_status"] == "not_found"
    assert snapshot.activity_evidence["activity_record_found"] is False
    assert snapshot.activity_evidence["latest_claim_status"] is None
    assert snapshot.activity_evidence["live_run"] is None
    assert decision["classification"] == "no_session"
    assert decision["recommended_action"] == "start_new"
    assert decision["start_new_allowed"] is True


def test_runtime_snapshot_keeps_other_active_claim_fail_closed(tmp_path: Path) -> None:
    _write_running_claim(
        tmp_path,
        preview_id="preview-other",
        run_id="run-other",
        claimed_at="2099-01-01T00:00:01+00:00",
    )
    _write_running_claim(
        tmp_path,
        preview_id="preview-self",
        run_id="run-self",
        claimed_at="2099-01-01T00:00:02+00:00",
    )

    snapshot = collect_continuation_snapshot(
        str(tmp_path),
        requested_provider="codex",
        current_run_id="run-self",
        session_store=_NoSessionStore(),
        planning_bridge=_PassingRunner(),
        source_review=_CleanGit(),
    )

    decision = snapshot.project("codex")["canonical_continuation_decision"]
    assert snapshot.activity_evidence["latest_run_status"] == "running"
    assert snapshot.activity_evidence["latest_claim_status"] == "RUNNING"
    assert snapshot.activity_evidence["live_run"]["run_id"] == "run-other"
    assert decision["classification"] == "active_operation_head_mismatch"
    assert decision["recommended_action"] == "human_review"
    assert decision["start_new_allowed"] is False


def test_live_snapshot_inactive_stale_session_allows_only_start_new(tmp_path: Path) -> None:
    old_head = "c" * 40
    current_head = "d" * 40

    class InactiveStaleSessionStore:
        def get_status(self):
            return {
                "ok": True,
                "active": False,
                "current_head": current_head,
                "record": {
                    "active": False,
                    "provider": "codex",
                    "current_head": old_head,
                    "base_head": old_head,
                    "conversation_id": "historical-conversation",
                },
            }

        def get_continuation_preview(self, status):
            return {
                "ok": True,
                "selected_provider": "codex",
                "hard_blockers": ["session_manifest_inactive"],
            }

    snapshot = collect_continuation_snapshot(
        str(tmp_path),
        requested_provider="codex",
        session_store=InactiveStaleSessionStore(),
        planning_bridge=_ReadyNotStartedRunner(),
        source_review=_CleanGit(),
    )

    decision = snapshot.project("codex")["canonical_continuation_decision"]
    assert snapshot.snapshot_status == "captured"
    assert snapshot.activity_evidence["latest_run_status"] == "not_found"
    assert snapshot.activity_evidence["latest_claim_status"] is None
    assert decision["classification"] == "inactive_stale_session"
    assert decision["recommended_action"] == "start_new"
    assert decision["resume_allowed"] is False
    assert decision["start_new_allowed"] is True


def test_live_snapshot_terminal_available_run_allows_only_start_new(tmp_path: Path) -> None:
    old_head = "c" * 40
    current_head = "d" * 40

    class InactiveStaleSessionStore:
        def get_status(self):
            return {
                "ok": True,
                "active": False,
                "current_head": current_head,
                "record": {
                    "active": False,
                    "provider": "codex",
                    "current_head": old_head,
                    "base_head": old_head,
                    "conversation_id": "historical-conversation",
                },
            }

        def get_continuation_preview(self, status):
            return {
                "ok": True,
                "selected_provider": "codex",
                "hard_blockers": ["session_manifest_inactive"],
            }

    with patch(
        "runner.continuation_snapshot._activity_evidence",
        return_value={
            "latest_run_status": "completed",
            "activity_record_found": True,
            "latest_claim_status": "COMPLETED",
            "live_run": {
                "available": True,
                "claim_status": "COMPLETED",
            },
            "activity_evidence_complete": True,
        },
    ):
        snapshot = collect_continuation_snapshot(
            str(tmp_path),
            requested_provider="codex",
            session_store=InactiveStaleSessionStore(),
            planning_bridge=_ReadyNotStartedRunner(),
            source_review=_CleanGit(),
        )

    decision = snapshot.project("codex")["canonical_continuation_decision"]
    assert snapshot.snapshot_status == "captured"
    assert snapshot.activity_evidence["latest_run_status"] == "completed"
    assert snapshot.activity_evidence["activity_record_found"] is True
    assert snapshot.activity_evidence["live_run"]["available"] is True
    assert decision["classification"] == "inactive_stale_session"
    assert decision["recommended_action"] == "start_new"
    assert decision["resume_allowed"] is False
    assert decision["start_new_allowed"] is True
    assert decision["hard_blockers"] == []


def test_activity_collection_failure_blocks_inactive_stale_start_new(tmp_path: Path) -> None:
    old_head = "c" * 40
    current_head = "d" * 40

    class InactiveStaleSessionStore:
        def get_status(self):
            return {
                "ok": True,
                "active": False,
                "current_head": current_head,
                "record": {
                    "active": False,
                    "provider": "codex",
                    "current_head": old_head,
                    "base_head": old_head,
                    "conversation_id": "historical-conversation",
                },
            }

        def get_continuation_preview(self, status):
            return {
                "ok": True,
                "selected_provider": "codex",
                "hard_blockers": ["session_manifest_inactive"],
            }

    with patch(
        "runner.continuation_snapshot._activity_evidence",
        side_effect=RuntimeError("activity unavailable"),
    ):
        snapshot = collect_continuation_snapshot(
            str(tmp_path),
            requested_provider="codex",
            session_store=InactiveStaleSessionStore(),
            planning_bridge=_ReadyNotStartedRunner(),
            source_review=_CleanGit(),
        )

    decision = snapshot.project("codex")["canonical_continuation_decision"]
    assert snapshot.snapshot_status == "captured_fail_closed"
    assert {item["name"] for item in snapshot.partial_errors} == {"executor_activity"}
    assert decision["classification"] == "head_evidence_incomplete"
    assert decision["recommended_action"] == "inspect_evidence"
    assert decision["resume_allowed"] is False
    assert decision["start_new_allowed"] is False


def test_snapshot_malformed_blockers_fail_closed_without_character_splitting(tmp_path: Path) -> None:
    old_head = "c" * 40
    current_head = "d" * 40

    class MalformedPreviewStore:
        def get_status(self):
            return {
                "ok": True,
                "active": False,
                "current_head": current_head,
                "record": {
                    "active": False,
                    "provider": "codex",
                    "current_head": old_head,
                    "base_head": old_head,
                    "conversation_id": "historical-conversation",
                },
            }

        def get_continuation_preview(self, status):
            return {
                "ok": True,
                "selected_provider": "codex",
                "hard_blockers": "continuation_evidence_incomplete",
            }

    snapshot = collect_continuation_snapshot(
        str(tmp_path),
        requested_provider="codex",
        session_store=MalformedPreviewStore(),
        planning_bridge=_ReadyNotStartedRunner(),
        source_review=_CleanGit(),
    )

    decision = snapshot.project("codex")["canonical_continuation_decision"]
    assert snapshot.snapshot_status == "captured_fail_closed"
    assert snapshot.fact_bundle["hard_blockers"] == []
    assert decision["resume_allowed"] is False
    assert decision["start_new_allowed"] is False


def test_executor_service_passes_current_run_id_to_runtime_snapshot(tmp_path: Path) -> None:
    allowed_snapshot = snapshot_from_fact_bundle(
        str(tmp_path),
        _facts(executor_session_status={"ok": True, "active": False}),
    )
    observed: dict[str, object] = {}

    def collect(project_root, requested_provider=None, **kwargs):
        observed["project_root"] = project_root
        observed["requested_provider"] = requested_provider
        observed.update(kwargs)
        return allowed_snapshot

    service = ExecutorRunOnceService.__new__(ExecutorRunOnceService)
    service.project_root = str(tmp_path)
    service._run_once_under_lease = lambda **kwargs: {
        "ok": True,
        "status": "completed",
        "run_id": kwargs["run_id"],
    }

    with patch(
        "runner.continuation_snapshot.collect_continuation_snapshot",
        side_effect=collect,
    ):
        result = service.run_once(
            provider="codex",
            executor_session_mode="start_new",
            run_id="run-self",
            executor_authority_id="0" * 32,
            admission_sha256="1" * 64,
        )

    assert result["ok"] is True
    assert result["run_id"] == "run-self"
    assert observed["current_run_id"] == "run-self"
    assert observed["held_operation_lease"].held is False


def test_distinct_captures_have_distinct_snapshot_ids_for_identical_facts(tmp_path: Path) -> None:
    first = snapshot_from_fact_bundle(str(tmp_path), _facts())
    second = snapshot_from_fact_bundle(str(tmp_path), _facts())

    assert first.snapshot_id != second.snapshot_id


def test_analyze_and_thin_loop_each_collect_exactly_one_snapshot(tmp_path: Path) -> None:
    analyze_snapshot = snapshot_from_fact_bundle(str(tmp_path), _facts())
    analyze_calls: list[str | None] = []

    def collect_analyze(project_root, requested_provider=None, **kwargs):
        analyze_calls.append(requested_provider)
        return analyze_snapshot

    with patch("runner.core_orchestrator.collect_continuation_snapshot", side_effect=collect_analyze):
        analyze = WorkflowOrchestrator(str(tmp_path)).build_fact_snapshot(
            provider="codex",
            include_reports=False,
        )

    assert analyze_calls == ["codex"]
    assert analyze._executor_raw["continuation_snapshot"]["snapshot_id"] == analyze_snapshot.snapshot_id

    project_root = str(Path(__file__).resolve().parents[1])
    thin_snapshot = snapshot_from_fact_bundle(project_root, _facts())
    thin_calls: list[str | None] = []

    def collect_thin(project_root, requested_provider=None, **kwargs):
        thin_calls.append(requested_provider)
        return thin_snapshot

    with patch("runner.core_orchestrator.collect_continuation_snapshot", side_effect=collect_thin):
        thin = WorkflowOrchestrator(project_root).handle(
            "thin_governed_loop_preview",
            {
                "phase": "preview",
                "input_mode": "draft",
                "draft_seed": {
                    "goal": "Inspect one bounded docs update.",
                    "allowed_files": ["docs/example.md"],
                    "validation_commands": ["git diff --check"],
                },
            },
        )

    guidance = thin.result["codex_execution_packet"]["executor_session_recovery"]
    assert thin_calls == ["codex"]
    assert guidance["continuation_snapshot"]["snapshot_id"] == thin_snapshot.snapshot_id


def test_provider_projection_recomputes_resume_capability_fail_closed(tmp_path: Path) -> None:
    facts = _facts(
        selected_provider="pi",
        requested_provider="codex",
        executor_session_status={
            "ok": True,
            "active": True,
            "record": {
                "active": True,
                "provider": "pi",
                "current_head": HEAD,
                "session_id": "private-pi-session",
            },
            "current_head": HEAD,
        },
    )
    snapshot = snapshot_from_fact_bundle(str(tmp_path), facts)

    pi_decision = snapshot.project("pi")["canonical_continuation_decision"]

    assert pi_decision["provider_resume_supported"] is False
    assert pi_decision["resume_invocation_verified"] is False
    assert pi_decision["recommended_action"] == "start_new"
    assert pi_decision["resume_allowed"] is False


@pytest.mark.parametrize("provider", ["codex", "opencode"])
@pytest.mark.parametrize(
    "unsupported_capability",
    ["provider_resume_supported", "resume_invocation_verified"],
)
def test_provider_projection_never_upgrades_captured_false_capability(
    tmp_path: Path,
    provider: str,
    unsupported_capability: str,
) -> None:
    identity_key = "conversation_id" if provider == "codex" else "session_id"
    status = {
        "ok": True,
        "active": True,
        "record": {
            "active": True,
            "provider": provider,
            "current_head": HEAD,
            identity_key: "private-session-value",
        },
        "current_head": HEAD,
        "matches_current_head": True,
    }
    facts = _facts(
        executor_session_status=status,
        requested_provider=provider,
        selected_provider=provider,
        **{unsupported_capability: False},
    )

    decision = snapshot_from_fact_bundle(str(tmp_path), facts).project(provider)[
        "canonical_continuation_decision"
    ]

    assert decision[unsupported_capability] is False
    assert decision["classification"] == "resume_unsupported"
    assert decision["recommended_action"] == "start_new"
    assert decision["resume_allowed"] is False


def test_missing_capability_facts_are_derived_from_provider_policy(tmp_path: Path) -> None:
    facts = _facts()
    facts.pop("provider_resume_supported")
    facts.pop("resume_invocation_verified")

    decision = snapshot_from_fact_bundle(str(tmp_path), facts).project("codex")[
        "canonical_continuation_decision"
    ]

    assert decision["provider_resume_supported"] is True
    assert decision["resume_invocation_verified"] is True
    assert decision["classification"] == "resume_eligible"


@pytest.mark.parametrize(
    ("case", "fact_overrides", "classification", "action", "resume_allowed", "start_new_allowed"),
    [
        ("CONT-01", {}, "resume_eligible", "resume", True, False),
        (
            "CONT-02",
            {
                "executor_session_status": {
                    "ok": True,
                    "active": True,
                    "record": {
                        "active": True,
                        "provider": "codex",
                        "current_head": OTHER_HEAD,
                        "conversation_id": "private-session-value",
                    },
                    "current_head": HEAD,
                    "matches_current_head": False,
                }
            },
            "completed_idle_stale_session",
            "start_new",
            False,
            True,
        ),
        (
            "CONT-03",
            {"operation_running": True},
            "active_operation_head_mismatch",
            "human_review",
            False,
            False,
        ),
        (
            "CONT-04",
            {
                "executor_session_status": {
                    "ok": True,
                    "active": True,
                    "record": {
                        "active": True,
                        "provider": "codex",
                        "conversation_id": "private-session-value",
                    },
                }
            },
            "head_evidence_incomplete",
            "inspect_evidence",
            False,
            False,
        ),
        (
            "CONT-05/no-session",
            {"executor_session_status": {"ok": True, "active": False}},
            "no_session",
            "start_new",
            False,
            True,
        ),
        (
            "CONT-05/provider-mismatch",
            {"requested_provider": "opencode"},
            "provider_or_identity_mismatch",
            "start_new",
            False,
            True,
        ),
        (
            "CONT-05/identity-missing",
            {"identity_present": False},
            "provider_or_identity_mismatch",
            "start_new",
            False,
            True,
        ),
        (
            "CONT-05/resume-unsupported",
            {"provider_resume_supported": False},
            "resume_unsupported",
            "start_new",
            False,
            True,
        ),
    ],
    ids=lambda value: value if isinstance(value, str) and value.startswith("CONT-") else None,
)
def test_continuation_contract_matrix_at_snapshot_projection(
    tmp_path: Path,
    case: str,
    fact_overrides: dict,
    classification: str,
    action: str,
    resume_allowed: bool,
    start_new_allowed: bool,
) -> None:
    del case
    decision = snapshot_from_fact_bundle(
        str(tmp_path),
        _facts(**fact_overrides),
    ).project(fact_overrides.get("requested_provider"))[
        "canonical_continuation_decision"
    ]

    assert decision["classification"] == classification
    assert decision["recommended_action"] == action
    assert decision["resume_allowed"] is resume_allowed
    assert decision["start_new_allowed"] is start_new_allowed


def test_snapshot_collection_does_not_create_project_files(tmp_path: Path) -> None:
    before = list(tmp_path.iterdir())
    snapshot = collect_continuation_snapshot(str(tmp_path), requested_provider="codex")

    assert snapshot.snapshot_status in {"captured", "captured_partial", "captured_fail_closed"}
    assert list(tmp_path.iterdir()) == before


def test_inactive_stale_null_claim_without_absence_provenance_blocks_start_new(tmp_path: Path) -> None:
    facts = _facts(
        executor_session_status={"active": False, "record": {"active": False}},
        session_head=HEAD,
        current_head=OTHER_HEAD,
        latest_run_status="completed",
        latest_claim_status=None,
        live_run=None,
        activity_evidence_complete=True,
        activity_record_found=None,
        runner_status="READY",
        current_version_status="NOT_STARTED",
    )
    decision = snapshot_from_fact_bundle(str(tmp_path), facts).project("codex")[
        "canonical_continuation_decision"
    ]
    assert decision["start_new_allowed"] is False
    assert decision["resume_allowed"] is False


def test_inactive_stale_explicit_no_activity_provenance_allows_start_new(tmp_path: Path) -> None:
    facts = _facts(
        executor_session_status={"active": False, "record": {"active": False}},
        session_head=HEAD,
        current_head=OTHER_HEAD,
        latest_run_status="not_found",
        latest_claim_status=None,
        live_run=None,
        activity_evidence_complete=True,
        activity_record_found=False,
        runner_status="READY",
        current_version_status="NOT_STARTED",
    )
    decision = snapshot_from_fact_bundle(str(tmp_path), facts).project("codex")[
        "canonical_continuation_decision"
    ]
    assert decision["classification"] == "inactive_stale_session"
    assert decision["start_new_allowed"] is True
    assert decision["resume_allowed"] is False


def test_activity_found_provenance_matrix_fails_closed_on_malformed_shapes(tmp_path: Path) -> None:
    cases = [
        ({"ok": True, "status": "not_found", "found": False}, True),
        ({"ok": True, "status": "not_found", "found": True}, False),
        ({"ok": True, "status": "running", "found": False}, False),
        ({"ok": True, "status": None, "found": False}, False),
        ({"ok": True, "status": "not_found"}, False),
        ({"ok": True, "status": "not_found", "found": None}, False),
        ({"ok": True, "status": "not_found", "found": "false"}, False),
        ({"ok": True, "status": "not_found", "found": 0}, False),
        ({"ok": True, "status": "not_found", "found": []}, False),
        ({"ok": True, "status": "not_found", "found": {}}, False),
    ]
    for payload, expected_complete in cases:
        with patch("runner.executor_read.handle_inspect_executor_activity", return_value=payload):
            evidence = _activity_evidence(str(tmp_path))
        assert evidence.get("activity_evidence_complete") is expected_complete
