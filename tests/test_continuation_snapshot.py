from __future__ import annotations

import multiprocessing
import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from runner.continuation_snapshot import (
    collect_continuation_snapshot,
    snapshot_from_fact_bundle,
)
from runner.core_orchestrator import WorkflowOrchestrator
from runner.project_operation_lease import ProjectOperationLease
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
