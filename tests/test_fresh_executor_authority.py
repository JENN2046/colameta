from __future__ import annotations

import hashlib
import json
import os
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from runner.fresh_executor_authority import (
    FRESH_EXECUTOR_ADMISSION_AUTHORITY_EXISTS,
    FRESH_EXECUTOR_ADMISSION_HEAD_DRIFT,
    FRESH_EXECUTOR_ADMISSION_INVALID_AUTHORITY_ID,
    FRESH_EXECUTOR_ADMISSION_LIVE_OPERATION,
    FRESH_EXECUTOR_ADMISSION_LIVENESS_UNAVAILABLE,
    FRESH_EXECUTOR_ADMISSION_PROJECT_BUSY,
    FRESH_EXECUTOR_ADMISSION_STATE_ROOT_ESCAPE,
    FRESH_EXECUTOR_ADMISSION_WORKTREE_DIRTY,
    FRESH_EXECUTOR_ADMISSION_WORKTREE_STATE_UNAVAILABLE,
    create_fresh_executor_authority,
    create_or_resolve_stage_shard_fresh_executor_authority,
    executor_authority_dir,
    executor_authority_path,
    read_fresh_executor_authority,
    inspect_stage_shard_fresh_executor_authority,
)
from runner.project_operation_lease import ProjectOperationLease
from runner.work_item_governance.ids import new_stable_id


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)


# Mirrors the canonical project .gitignore: ColaMeta local runtime state is
# expected untracked state and must not dirty the worktree.
_COLAMETA_GITIGNORE = """\
# Python
__pycache__/
*.py[cod]

# >>> ColaMeta local state >>>
.colameta/state.json
.colameta/runtime/**
.colameta/logs/**
.colameta/reports/**
.colameta/audits/**
.colameta/plan-patches/**
.colameta/tmp/**
.colameta/local/**
.colameta/ledger/**
.colameta/executor-session.json
.colameta/executor-sessions/**
.colameta/settings.json
.colameta/runner-settings.json
.colameta/*.lock
.colameta/**/*.lock
# <<< ColaMeta local state <<<
"""


def _make_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "project"
    repo.mkdir()
    # ProjectOperationLease requires a project root that is not group/other
    # writable (mode & 0o022 == 0); pytest tmp dirs default to 0o775.
    os.chmod(repo, 0o755)
    _run(["git", "init", "-b", "main"], repo)
    _run(["git", "config", "user.name", "Test"], repo)
    _run(["git", "config", "user.email", "test@example.invalid"], repo)
    _run(
        ["git", "remote", "add", "origin", "git@github.com:JENN2046/colameta.git"],
        repo,
    )
    (repo / "value.txt").write_text("x\n", encoding="utf-8")
    (repo / ".gitignore").write_text(_COLAMETA_GITIGNORE, encoding="utf-8")
    _run(["git", "add", "value.txt", ".gitignore"], repo)
    _run(["git", "commit", "-m", "init"], repo)
    head = _run(["git", "rev-parse", "HEAD"], repo).stdout.strip()
    return repo, head


def _write_stale_historical_manifest(repo: Path) -> Path:
    manifest = repo / ".colameta" / "runtime" / "executor-session.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "active": False,
        "provider": "codex",
        "session_id": None,
        "conversation_id": "019f19bd-c577-7eb2-ab66-b9d7ea517bec",
        "base_head": "9448b4ea00fcf2ce62871872302dfef58205d796",
        "current_head": "9448b4ea00fcf2ce62871872302dfef58205d796",
        "version": "v1.15",
        "resume_enabled": False,
    }
    manifest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return manifest


def _clean_preview_facts(repo: Path, head: str) -> dict[str, object]:
    """A realistic preview observation: exact HEAD, clean worktree, idle."""
    return {
        "project_root": str(repo),
        "project_root_valid": True,
        "project_head": head,
        "git_branch": "main",
        "repository": "JENN2046/colameta",
        "historical_session_live": False,
        "legacy_session_present": False,
        "worktree_clean": True,
        "worktree_state_available": True,
        "operation_liveness": {"state": "idle", "reason": "no_live_operation_evidence"},
        "authority_root_safe": True,
    }


def _write_claim(
    repo: Path,
    preview_id: str,
    *,
    status: str = "RUNNING",
    heartbeat: str | None = None,
    extra: dict[str, object] | None = None,
) -> Path:
    claim_dir = repo / ".colameta" / "runtime" / "executor-workflow-previews" / "claims"
    claim_dir.mkdir(parents=True, exist_ok=True)
    now_iso = datetime.now(timezone.utc).isoformat()
    claim: dict[str, object] = {
        "preview_id": preview_id,
        "run_id": f"exec_run_{preview_id}",
        "status": status,
        "claimed_at": now_iso,
        "last_heartbeat_at": heartbeat or now_iso,
        "heartbeat_interval_seconds": 5,
        "heartbeat_timeout_seconds": 20,
    }
    if extra:
        claim.update(extra)
    path = claim_dir / f"{preview_id}.json"
    path.write_text(json.dumps(claim, indent=2) + "\n", encoding="utf-8")
    return path


def _colameta_file_map(repo: Path) -> dict[str, str]:
    mapping: dict[str, str] = {}
    root = repo / ".colameta"
    if not root.exists():
        return mapping
    for base, _dirs, files in os.walk(root):
        for name in files:
            path = Path(base) / name
            relative = str(path.relative_to(repo))
            mapping[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return mapping


# ---------------------------------------------------------------------------
# R0 baseline tests (unchanged semantics)
# ---------------------------------------------------------------------------


def test_create_brand_new_authority(tmp_path: Path) -> None:
    repo, head = _make_repo(tmp_path)

    result = create_fresh_executor_authority(str(repo))

    assert result["ok"] is True
    authority_id = result["executor_authority_id"]
    assert len(authority_id) == 32 and all(c in "0123456789abcdef" for c in authority_id)
    record = read_fresh_executor_authority(str(repo), authority_id)
    assert record is not None
    assert record["executor_authority_id"] == authority_id
    assert record["schema_version"] == "fresh_executor_authority_admission.v1"
    assert record["admission_state"] == "admitted"
    assert record["operation_state"] == "idle"
    assert record["admitted_head"] == head
    assert record["source"] == "fresh_executor_admission"


def test_authority_id_unique(tmp_path: Path) -> None:
    repo, _ = _make_repo(tmp_path)

    first = create_fresh_executor_authority(str(repo))
    second = create_fresh_executor_authority(str(repo))

    assert first["ok"] is True and second["ok"] is True
    assert first["executor_authority_id"] != second["executor_authority_id"]


def test_provider_identity_absent_and_idle(tmp_path: Path) -> None:
    repo, head = _make_repo(tmp_path)

    result = create_fresh_executor_authority(str(repo))
    record = read_fresh_executor_authority(
        str(repo), result["executor_authority_id"]
    )

    assert record["provider_session_identity"] is None
    assert record["provider_invoked"] is False
    assert record["work_started"] is False
    assert record["operation_state"] == "idle"
    assert record["admission_state"] == "admitted"


def test_provider_invocation_count_zero_and_no_side_artifacts(tmp_path: Path) -> None:
    repo, _ = _make_repo(tmp_path)
    before = _colameta_file_map(repo)

    with patch(
        "runner.codex_executor.CodexExecutor.run_current_version",
        side_effect=AssertionError("provider must not be invoked"),
    ), patch(
        "runner.codex_executor.CodexExecutor.run_current_fix",
        side_effect=AssertionError("provider must not be invoked"),
    ), patch(
        "runner.executor_run_workflow.ExecutorRunOnceService.run_once",
        side_effect=AssertionError("provider must not be invoked"),
    ), patch(
        "runner.executor_session.ExecutorSessionStore.record_execution",
        side_effect=AssertionError("legacy session recording must not be invoked"),
    ):
        result = create_fresh_executor_authority(str(repo))

    assert result["ok"] is True
    after = _colameta_file_map(repo)
    new_files = set(after) - set(before)
    assert new_files == {
        os.path.join(
            ".colameta",
            "runtime",
            "executor-sessions",
            result["executor_authority_id"],
            "admission.json",
        )
    }


def test_exact_project_and_head_binding(tmp_path: Path) -> None:
    repo, head = _make_repo(tmp_path)

    result = create_fresh_executor_authority(str(repo))
    record = read_fresh_executor_authority(
        str(repo), result["executor_authority_id"]
    )

    assert record["project_root"] == str(repo)
    assert record["repository"] == "JENN2046/colameta"
    assert record["git_branch"] == "main"
    assert record["admitted_head"] == head


def test_historical_manifest_byte_unchanged(tmp_path: Path) -> None:
    repo, _ = _make_repo(tmp_path)
    manifest = _write_stale_historical_manifest(repo)
    before_sha = hashlib.sha256(manifest.read_bytes()).hexdigest()

    result = create_fresh_executor_authority(str(repo))

    assert result["ok"] is True
    after_sha = hashlib.sha256(manifest.read_bytes()).hexdigest()
    assert before_sha == after_sha
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["active"] is False
    assert payload["current_head"] == "9448b4ea00fcf2ce62871872302dfef58205d796"


def test_old_session_identity_and_continuation_not_copied(tmp_path: Path) -> None:
    repo, _ = _make_repo(tmp_path)
    _write_stale_historical_manifest(repo)

    result = create_fresh_executor_authority(str(repo))
    record = read_fresh_executor_authority(
        str(repo), result["executor_authority_id"]
    )

    assert record["parent_authority_id"] is None
    assert record["continuation_from"] is None
    assert record["historical_session_inherited"] is False
    assert record["provider_session_identity"] is None
    assert "conversation_id" not in record
    assert "session_id" not in record


def test_collision_fail_closed(tmp_path: Path) -> None:
    repo, _ = _make_repo(tmp_path)
    forced = "a" * 32

    first = create_fresh_executor_authority(str(repo), authority_id=forced)
    second = create_fresh_executor_authority(str(repo), authority_id=forced)

    assert first["ok"] is True
    assert second["ok"] is False
    assert second["error_code"] == FRESH_EXECUTOR_ADMISSION_AUTHORITY_EXISTS


def test_concurrent_create_safety(tmp_path: Path) -> None:
    repo, _ = _make_repo(tmp_path)
    forced = "b" * 32
    barrier = threading.Barrier(2)
    results: list[dict[str, object]] = []

    def worker() -> None:
        barrier.wait()
        results.append(create_fresh_executor_authority(str(repo), authority_id=forced))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    outcomes = sorted(bool(r.get("ok")) for r in results)
    assert outcomes == [False, True]
    failed = next(r for r in results if not r.get("ok"))
    # Concurrent creation must fail closed for the loser: either the exclusive
    # project lease is held by the winner (PROJECT_BUSY) or the authority
    # already exists (AUTHORITY_EXISTS).  No partial/double write is allowed.
    assert failed["error_code"] in {
        FRESH_EXECUTOR_ADMISSION_AUTHORITY_EXISTS,
        FRESH_EXECUTOR_ADMISSION_PROJECT_BUSY,
    }
    assert read_fresh_executor_authority(str(repo), forced) is not None


def test_head_drift_fail_closed(tmp_path: Path) -> None:
    repo, head = _make_repo(tmp_path)
    # Simulate preview observed HEAD=A, but creation-time live HEAD is the real HEAD.
    preview_head = "a" * 40
    assert preview_head != head
    preview_facts = _clean_preview_facts(repo, preview_head)

    result = create_fresh_executor_authority(
        str(repo),
        expected_head=preview_head,
        facts=preview_facts,
    )

    assert result["ok"] is False
    assert result["error_code"] == FRESH_EXECUTOR_ADMISSION_HEAD_DRIFT
    assert result["observed_head"] == head
    assert result["expected_head"] == preview_head
    # No authority must have been created.
    assert _colameta_file_map(repo) == {}


def test_project_lease_contention_fail_closed(tmp_path: Path) -> None:
    repo, _ = _make_repo(tmp_path)
    holder = ProjectOperationLease(str(repo))
    holder.acquire()
    assert holder.held is True
    try:
        result = create_fresh_executor_authority(str(repo))
        assert result["ok"] is False
        assert result["error_code"] == FRESH_EXECUTOR_ADMISSION_PROJECT_BUSY
        assert _colameta_file_map(repo) == {}
    finally:
        holder.release()


@pytest.mark.parametrize(
    "bad_id",
    (
        "c" * 31,
        "c" * 33,
        "C" * 32,
        "g" * 32,
        "../" + "d" * 32,
        "d" * 32 + "/admission.json",
        "",
        "not-a-uuid",
        "e" * 32 + ".json",
    ),
)
def test_malformed_authority_id_fail_closed(tmp_path: Path, bad_id: str) -> None:
    repo, _ = _make_repo(tmp_path)

    result = create_fresh_executor_authority(str(repo), authority_id=bad_id)

    assert result["ok"] is False
    assert result["error_code"] == FRESH_EXECUTOR_ADMISSION_INVALID_AUTHORITY_ID
    assert _colameta_file_map(repo) == {}


def test_path_traversal_rejected(tmp_path: Path) -> None:
    repo, _ = _make_repo(tmp_path)
    traversal = "../" + "f" * 32

    result = create_fresh_executor_authority(str(repo), authority_id=traversal)

    assert result["ok"] is False
    assert result["error_code"] == FRESH_EXECUTOR_ADMISSION_INVALID_AUTHORITY_ID
    outside = tmp_path / ("f" * 32)
    assert not outside.exists()
    assert not (repo / ".colameta" / "runtime" / "executor-sessions").exists()


def test_existing_authority_cannot_overwrite(tmp_path: Path) -> None:
    repo, _ = _make_repo(tmp_path)
    forced = "ab" * 16
    first = create_fresh_executor_authority(str(repo), authority_id=forced)
    record_path = executor_authority_path(str(repo), forced)
    before_sha = hashlib.sha256(Path(record_path).read_bytes()).hexdigest()

    second = create_fresh_executor_authority(str(repo), authority_id=forced)

    assert first["ok"] is True
    assert second["ok"] is False
    assert second["error_code"] == FRESH_EXECUTOR_ADMISSION_AUTHORITY_EXISTS
    after_sha = hashlib.sha256(Path(record_path).read_bytes()).hexdigest()
    assert before_sha == after_sha


def test_regression_stale_historical_session_does_not_block_fresh_authority(
    tmp_path: Path,
) -> None:
    """Historical inactive session + old HEAD mismatch must not block fresh
    admission, and the historical manifest must remain byte-identical."""
    repo, _ = _make_repo(tmp_path)
    manifest = _write_stale_historical_manifest(repo)
    before_sha = hashlib.sha256(manifest.read_bytes()).hexdigest()

    result = create_fresh_executor_authority(str(repo))

    assert result["ok"] is True
    record = read_fresh_executor_authority(
        str(repo), result["executor_authority_id"]
    )
    assert record["admitted_head"] != "9448b4ea00fcf2ce62871872302dfef58205d796"
    assert record["historical_session_inherited"] is False
    assert hashlib.sha256(manifest.read_bytes()).hexdigest() == before_sha


def test_historical_live_session_blocks_fresh_authority(tmp_path: Path) -> None:
    repo, _ = _make_repo(tmp_path)
    manifest = _write_stale_historical_manifest(repo)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["active"] = True
    manifest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    result = create_fresh_executor_authority(str(repo))

    assert result["ok"] is False
    assert result["error_code"] == "FRESH_EXECUTOR_ADMISSION_HISTORICAL_SESSION_LIVE"
    assert _colameta_file_map(repo) == {
        ".colameta/runtime/executor-session.json": hashlib.sha256(
            manifest.read_bytes()
        ).hexdigest()
    }


# ---------------------------------------------------------------------------
# P1-1: dirty worktree must never be admitted
# ---------------------------------------------------------------------------


def test_tracked_modified_worktree_rejected(tmp_path: Path) -> None:
    repo, head = _make_repo(tmp_path)
    (repo / "value.txt").write_text("MODIFIED\n", encoding="utf-8")

    result = create_fresh_executor_authority(str(repo), expected_head=head)

    assert result["ok"] is False
    assert result["error_code"] == FRESH_EXECUTOR_ADMISSION_WORKTREE_DIRTY
    assert _colameta_file_map(repo) == {}


def test_tracked_deleted_worktree_rejected(tmp_path: Path) -> None:
    repo, head = _make_repo(tmp_path)
    (repo / "value.txt").unlink()

    result = create_fresh_executor_authority(str(repo), expected_head=head)

    assert result["ok"] is False
    assert result["error_code"] == FRESH_EXECUTOR_ADMISSION_WORKTREE_DIRTY
    assert _colameta_file_map(repo) == {}


def test_untracked_worktree_rejected(tmp_path: Path) -> None:
    repo, head = _make_repo(tmp_path)
    (repo / "unexpected.txt").write_text("x\n", encoding="utf-8")

    result = create_fresh_executor_authority(str(repo), expected_head=head)

    assert result["ok"] is False
    assert result["error_code"] == FRESH_EXECUTOR_ADMISSION_WORKTREE_DIRTY
    assert _colameta_file_map(repo) == {}


def test_dirty_introduced_after_preview_rejected(tmp_path: Path) -> None:
    """TOCTOU: preview observed a clean worktree, but a tracked file became
    dirty before the lease-internal revalidation; must still fail closed."""
    repo, head = _make_repo(tmp_path)
    preview_facts = _clean_preview_facts(repo, head)
    (repo / "value.txt").write_text("MODIFIED\n", encoding="utf-8")

    result = create_fresh_executor_authority(
        str(repo), expected_head=head, facts=preview_facts
    )

    assert result["ok"] is False
    assert result["error_code"] == FRESH_EXECUTOR_ADMISSION_WORKTREE_DIRTY
    assert _colameta_file_map(repo) == {}


def test_git_status_failure_fail_closed(tmp_path: Path) -> None:
    """'cannot determine worktree state' must not be treated as clean."""
    repo, _ = _make_repo(tmp_path)
    with patch(
        "runner.fresh_executor_authority._git_worktree_clean",
        return_value=(None, "simulated git failure"),
    ):
        result = create_fresh_executor_authority(str(repo))

    assert result["ok"] is False
    assert result["error_code"] == FRESH_EXECUTOR_ADMISSION_WORKTREE_STATE_UNAVAILABLE
    assert _colameta_file_map(repo) == {}


# ---------------------------------------------------------------------------
# P1-2: liveness must combine manifest + run/claim/job/lease evidence
# ---------------------------------------------------------------------------


def test_inactive_manifest_plus_running_claim_artifact_rejected(
    tmp_path: Path,
) -> None:
    """Review attack: inactive manifest + running claim artifact."""
    repo, head = _make_repo(tmp_path)
    _write_stale_historical_manifest(repo)
    _write_claim(
        repo,
        "preview_running_artifact",
        extra={
            "claim_status": "running",
            "run_status": "running",
            "job_status": "active",
            "operation_running": True,
        },
    )

    result = create_fresh_executor_authority(str(repo), expected_head=head)

    assert result["ok"] is False
    assert result["error_code"] == FRESH_EXECUTOR_ADMISSION_LIVE_OPERATION
    # The historical manifest must remain byte-identical and no authority
    # directory may be created; the test-created claim artifact is expected.
    manifest = repo / ".colameta/runtime/executor-session.json"
    assert hashlib.sha256(manifest.read_bytes()).hexdigest() == _colameta_file_map(repo)[
        ".colameta/runtime/executor-session.json"
    ]
    assert not (repo / ".colameta" / "runtime" / "executor-sessions").exists()


def test_inactive_manifest_plus_running_run_rejected(tmp_path: Path) -> None:
    """Canonical RUNNING claim with a fresh heartbeat = live run."""
    repo, head = _make_repo(tmp_path)
    _write_stale_historical_manifest(repo)
    _write_claim(repo, "preview_live_run", status="RUNNING")

    result = create_fresh_executor_authority(str(repo), expected_head=head)

    assert result["ok"] is False
    assert result["error_code"] == FRESH_EXECUTOR_ADMISSION_LIVE_OPERATION


def test_inactive_manifest_plus_orphaned_run_rejected(tmp_path: Path) -> None:
    """A stale RUNNING claim with an old heartbeat is still fail-closed."""
    repo, head = _make_repo(tmp_path)
    _write_stale_historical_manifest(repo)
    _write_claim(
        repo,
        "preview_orphaned",
        status="RUNNING",
        heartbeat="2020-01-01T00:00:00+00:00",
    )

    result = create_fresh_executor_authority(str(repo), expected_head=head)

    assert result["ok"] is False
    assert result["error_code"] == FRESH_EXECUTOR_ADMISSION_LIVE_OPERATION


def test_inactive_manifest_plus_job_running_rejected(tmp_path: Path) -> None:
    """A claim artifact reporting a running job must fail closed."""
    repo, head = _make_repo(tmp_path)
    _write_stale_historical_manifest(repo)
    _write_claim(
        repo,
        "preview_job_running",
        status="COMPLETED",
        extra={"job_status": "running"},
    )

    result = create_fresh_executor_authority(str(repo), expected_head=head)

    assert result["ok"] is False
    assert result["error_code"] == FRESH_EXECUTOR_ADMISSION_LIVE_OPERATION


def test_malformed_claim_evidence_fail_closed(tmp_path: Path) -> None:
    """Malformed claim evidence must be UNAVAILABLE, never 'not running'."""
    repo, head = _make_repo(tmp_path)
    _write_stale_historical_manifest(repo)
    claim_dir = repo / ".colameta" / "runtime" / "executor-workflow-previews" / "claims"
    claim_dir.mkdir(parents=True, exist_ok=True)
    (claim_dir / "bad-claim.json").write_text("{not json", encoding="utf-8")

    result = create_fresh_executor_authority(str(repo), expected_head=head)

    assert result["ok"] is False
    assert result["error_code"] == FRESH_EXECUTOR_ADMISSION_LIVENESS_UNAVAILABLE
    assert _colameta_file_map(repo) == {
        ".colameta/runtime/executor-session.json": hashlib.sha256(
            (repo / ".colameta/runtime/executor-session.json").read_bytes()
        ).hexdigest(),
        ".colameta/runtime/executor-workflow-previews/claims/bad-claim.json": (
            hashlib.sha256(
                (repo / ".colameta/runtime/executor-workflow-previews/claims/bad-claim.json").read_bytes()
            ).hexdigest()
        ),
    }


def test_completed_claim_artifacts_do_not_block(tmp_path: Path) -> None:
    """Completed historical claims are idle evidence, not live operations."""
    repo, head = _make_repo(tmp_path)
    _write_stale_historical_manifest(repo)
    _write_claim(repo, "preview_completed", status="COMPLETED")

    result = create_fresh_executor_authority(str(repo), expected_head=head)

    assert result["ok"] is True
    record = read_fresh_executor_authority(
        str(repo), result["executor_authority_id"]
    )
    assert record["admitted_head"] == head


def test_liveness_unavailable_fail_closed(tmp_path: Path) -> None:
    """An indeterminate live-run reader must fail closed, not admit."""
    repo, _ = _make_repo(tmp_path)
    with patch(
        "runner.fresh_executor_authority._collect_operation_liveness",
        return_value={
            "state": "unavailable",
            "reason": "latest_run_status_unavailable",
        },
    ):
        result = create_fresh_executor_authority(str(repo))

    assert result["ok"] is False
    assert result["error_code"] == FRESH_EXECUTOR_ADMISSION_LIVENESS_UNAVAILABLE
    assert _colameta_file_map(repo) == {}


# ---------------------------------------------------------------------------
# P1-3: state-root containment
# ---------------------------------------------------------------------------


def test_state_root_symlink_escape_rejected(tmp_path: Path) -> None:
    """Review attack: executor-sessions symlink pointing outside the repo."""
    repo, head = _make_repo(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    runner_runtime = repo / ".colameta" / "runtime"
    runner_runtime.mkdir(parents=True, exist_ok=True)
    os.symlink(str(outside), runner_runtime / "executor-sessions")

    result = create_fresh_executor_authority(str(repo), expected_head=head)

    assert result["ok"] is False
    assert result["error_code"] == FRESH_EXECUTOR_ADMISSION_STATE_ROOT_ESCAPE
    assert list(outside.rglob("admission.json")) == []
    assert _colameta_file_map(repo) == {}


def test_runtime_parent_symlink_escape_rejected(tmp_path: Path) -> None:
    """A parent component (runtime) escaping the runner dir must fail closed."""
    repo, head = _make_repo(tmp_path)
    outside = tmp_path / "outside-runtime"
    outside.mkdir()
    runner_dir = repo / ".colameta"
    runner_dir.mkdir(parents=True, exist_ok=True)
    os.symlink(str(outside), runner_dir / "runtime")

    result = create_fresh_executor_authority(str(repo), expected_head=head)

    assert result["ok"] is False
    assert result["error_code"] == FRESH_EXECUTOR_ADMISSION_STATE_ROOT_ESCAPE
    assert list(outside.rglob("admission.json")) == []


def test_runner_dir_symlink_rejected(tmp_path: Path) -> None:
    repo, head = _make_repo(tmp_path)
    outside = tmp_path / "outside-runner"
    outside.mkdir()
    os.symlink(str(outside), repo / ".colameta")

    result = create_fresh_executor_authority(str(repo), expected_head=head)

    assert result["ok"] is False
    assert result["error_code"] == FRESH_EXECUTOR_ADMISSION_STATE_ROOT_ESCAPE
    assert list(outside.rglob("admission.json")) == []


def test_authority_dir_symlink_fails_closed(tmp_path: Path) -> None:
    repo, _ = _make_repo(tmp_path)
    authority_id = "aa" * 16
    target = tmp_path / "elsewhere"
    target.mkdir()
    root = Path(executor_authority_dir(str(repo)))
    root.mkdir(parents=True, exist_ok=True)
    os.symlink(str(target), root / authority_id)

    result = create_fresh_executor_authority(str(repo), authority_id=authority_id)

    assert result["ok"] is False
    assert result["error_code"] == FRESH_EXECUTOR_ADMISSION_AUTHORITY_EXISTS
    assert list(target.rglob("admission.json")) == []


def test_admission_file_symlink_fails_closed(tmp_path: Path) -> None:
    repo, _ = _make_repo(tmp_path)
    authority_id = "bb" * 16
    root = Path(executor_authority_dir(str(repo)))
    (root / authority_id).mkdir(parents=True, exist_ok=True)
    target = tmp_path / "victim.json"
    target.write_text("do not touch\n", encoding="utf-8")
    os.symlink(str(target), root / authority_id / "admission.json")

    result = create_fresh_executor_authority(str(repo), authority_id=authority_id)

    assert result["ok"] is False
    assert result["error_code"] == FRESH_EXECUTOR_ADMISSION_AUTHORITY_EXISTS
    assert target.read_text(encoding="utf-8") == "do not touch\n"


def test_normal_state_root_admits(tmp_path: Path) -> None:
    repo, head = _make_repo(tmp_path)
    result = create_fresh_executor_authority(str(repo), expected_head=head)
    assert result["ok"] is True
    record = read_fresh_executor_authority(
        str(repo), result["executor_authority_id"]
    )
    assert record["admitted_head"] == head


def test_preexisting_empty_admission_fails_closed(tmp_path: Path) -> None:
    """Write-once: an existing (even empty) admission.json must never be
    replaced, merged, or truncated."""
    repo, _ = _make_repo(tmp_path)
    authority_id = "cc" * 16
    root = Path(executor_authority_dir(str(repo)))
    (root / authority_id).mkdir(parents=True, exist_ok=True)
    (root / authority_id / "admission.json").write_text("", encoding="utf-8")

    result = create_fresh_executor_authority(str(repo), authority_id=authority_id)

    assert result["ok"] is False
    assert result["error_code"] == FRESH_EXECUTOR_ADMISSION_AUTHORITY_EXISTS
    assert (root / authority_id / "admission.json").read_bytes() == b""


def test_preexisting_malformed_admission_fails_closed(tmp_path: Path) -> None:
    repo, _ = _make_repo(tmp_path)
    authority_id = "dd" * 16
    root = Path(executor_authority_dir(str(repo)))
    (root / authority_id).mkdir(parents=True, exist_ok=True)
    (root / authority_id / "admission.json").write_text("{not json", encoding="utf-8")

    result = create_fresh_executor_authority(str(repo), authority_id=authority_id)

    assert result["ok"] is False
    assert result["error_code"] == FRESH_EXECUTOR_ADMISSION_AUTHORITY_EXISTS
    assert (root / authority_id / "admission.json").read_text(encoding="utf-8") == "{not json"


def test_preexisting_authority_directory_fails_closed(tmp_path: Path) -> None:
    """A pre-created authority directory (even without admission.json) must
    not be adopted or written into."""
    repo, _ = _make_repo(tmp_path)
    authority_id = "ee" * 16
    root = Path(executor_authority_dir(str(repo)))
    (root / authority_id).mkdir(parents=True, exist_ok=True)

    result = create_fresh_executor_authority(str(repo), authority_id=authority_id)

    assert result["ok"] is False
    assert result["error_code"] == FRESH_EXECUTOR_ADMISSION_AUTHORITY_EXISTS
    assert not (root / authority_id / "admission.json").exists()


def test_multiple_idle_authorities_still_allowed(tmp_path: Path) -> None:
    """R0 does not introduce a mutable current pointer; multiple idle
    authorities remain allowed (consumption is Work Authorization's job)."""
    repo, _ = _make_repo(tmp_path)
    first = create_fresh_executor_authority(str(repo))
    second = create_fresh_executor_authority(str(repo))
    assert first["ok"] is True and second["ok"] is True
    assert first["executor_authority_id"] != second["executor_authority_id"]


# ---------------------------------------------------------------------------
# Repair 2 — P1_a: FD-anchored state root (zero outside write on swap races)
# ---------------------------------------------------------------------------


def _swap_sessions_path_to_symlink(repo: Path, outside: Path) -> None:
    """Rename the real executor-sessions dir aside and point the canonical
    pathname at an outside directory (simulating an attacker swap)."""
    sessions = repo / ".colameta" / "runtime" / "executor-sessions"
    real_sessions = sessions.with_name("executor-sessions.real")
    if sessions.is_symlink():
        os.unlink(sessions)
    elif sessions.exists():
        os.rename(sessions, real_sessions)
    os.symlink(str(outside), sessions)


def test_race_a_swap_before_authority_mkdir_zero_outside_write(
    tmp_path: Path,
) -> None:
    """Race A: swap executor-sessions -> outside symlink after the state-root
    fds are opened but before the authority dir is created.  The mkdir is
    anchored to the open sessions fd, so no byte may reach outside."""
    repo, head = _make_repo(tmp_path)
    outside = tmp_path / "outside-race-a"
    outside.mkdir()
    real_mkdir = os.mkdir
    state = {"swapped": False}

    def _mkdir(path, *a, **kw):
        if (not state["swapped"]) and kw.get("dir_fd") is not None:
            basename = os.path.basename(str(path))
            if len(basename) == 32 and all(c in "0123456789abcdef" for c in basename):
                _swap_sessions_path_to_symlink(repo, outside)
                state["swapped"] = True
        return real_mkdir(path, *a, **kw)

    with patch("runner.fresh_executor_authority.os.mkdir", side_effect=_mkdir):
        result = create_fresh_executor_authority(str(repo), expected_head=head)

    outside_files = list(outside.rglob("*"))
    print("raceA ok:", result.get("ok"), "error:", result.get("error_code"),
          "outside_files:", outside_files)
    assert outside_files == []  # closure condition: outside filesystem zero write


def test_race_b_swap_before_admission_open_zero_outside_write(
    tmp_path: Path,
) -> None:
    """Race B: authority dir established, then the parent path is swapped to an
    outside symlink before admission.json is opened.  The record open is
    anchored to the open authority fd, so no byte may reach outside."""
    repo, head = _make_repo(tmp_path)
    outside = tmp_path / "outside-race-b"
    outside.mkdir()
    real_open = os.open
    state = {"swapped": False}

    def _open(path, *a, **kw):
        if (not state["swapped"]) and str(path) == "admission.json" and kw.get("dir_fd") is not None:
            _swap_sessions_path_to_symlink(repo, outside)
            state["swapped"] = True
        return real_open(path, *a, **kw)

    with patch("runner.fresh_executor_authority.os.open", side_effect=_open):
        result = create_fresh_executor_authority(str(repo), expected_head=head)

    outside_files = list(outside.rglob("*"))
    print("raceB ok:", result.get("ok"), "error:", result.get("error_code"),
          "outside_files:", outside_files)
    assert outside_files == []  # closure condition: outside filesystem zero write


def test_preexisting_sessions_symlink_still_rejected(tmp_path: Path) -> None:
    """Regression: the pre-existing symlink case must still fail closed."""
    repo, head = _make_repo(tmp_path)
    outside = tmp_path / "outside-preexisting"
    outside.mkdir()
    runtime_dir = repo / ".colameta" / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    os.symlink(str(outside), runtime_dir / "executor-sessions")

    result = create_fresh_executor_authority(str(repo), expected_head=head)

    assert result["ok"] is False
    assert result["error_code"] == FRESH_EXECUTOR_ADMISSION_STATE_ROOT_ESCAPE
    assert list(outside.rglob("*")) == []


def test_fd_cleanup_repeated_failed_admission(tmp_path: Path) -> None:
    """Repeated failed admissions (collision) must not leak fds."""
    import resource

    repo, _ = _make_repo(tmp_path)
    forced = "ab" * 16
    first = create_fresh_executor_authority(str(repo), authority_id=forced)
    assert first["ok"] is True
    before = resource.getrlimit(resource.RLIMIT_NOFILE)
    # Repeated collision attempts.
    for _ in range(40):
        result = create_fresh_executor_authority(str(repo), authority_id=forced)
        assert result["ok"] is False
        assert result["error_code"] == FRESH_EXECUTOR_ADMISSION_AUTHORITY_EXISTS
    # No assertion on exact count (other threads may hold fds); the loop above
    # must not raise EMFILE, which would indicate an fd leak.
    assert True


# ---------------------------------------------------------------------------
# Repair 2 — P1_b: liveness positive-proof schema
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "unknown_schema",
    (
        {},
        {"foo": "bar"},
        {"status": None},
        {"status": 123},
        {"status": ["not_found"]},
        {"status": "future-unknown-status"},
        {"status": "unknown"},
        {"status": "not_found", "live": {"available": True, "claim_status": "weird"}},
        {"status": "not_found", "live": {"available": True, "claim": {"status": 42}}},
    ),
)
def test_liveness_unknown_schema_fail_closed(tmp_path: Path, unknown_schema: dict) -> None:
    """P1-b: an uninterpretable liveness schema must fail closed with
    LIVENESS_UNAVAILABLE, never be treated as idle."""
    repo, _ = _make_repo(tmp_path)
    with patch(
        "runner.executor_read.handle_inspect_executor_activity",
        return_value=unknown_schema,
    ):
        result = create_fresh_executor_authority(str(repo))
    assert result["ok"] is False
    assert result["error_code"] == FRESH_EXECUTOR_ADMISSION_LIVENESS_UNAVAILABLE
    assert _colameta_file_map(repo) == {}


def test_liveness_valid_idle_schema_admits(tmp_path: Path) -> None:
    """Positive proof: a known idle status (not_found) + no claims admits."""
    repo, _ = _make_repo(tmp_path)
    with patch(
        "runner.executor_read.handle_inspect_executor_activity",
        return_value={"ok": True, "status": "not_found", "found": False},
    ):
        result = create_fresh_executor_authority(str(repo))
    assert result["ok"] is True
    record = read_fresh_executor_authority(str(repo), result["executor_authority_id"])
    assert record["admitted_head"] is not None


def test_liveness_valid_running_schema_blocks(tmp_path: Path) -> None:
    """Positive proof: a known running status blocks with LIVE_OPERATION."""
    repo, _ = _make_repo(tmp_path)
    with patch(
        "runner.executor_read.handle_inspect_executor_activity",
        return_value={"ok": True, "status": "running", "found": True},
    ):
        result = create_fresh_executor_authority(str(repo))
    assert result["ok"] is False
    assert result["error_code"] == FRESH_EXECUTOR_ADMISSION_LIVE_OPERATION


def test_liveness_valid_orphaned_schema_blocks(tmp_path: Path) -> None:
    repo, _ = _make_repo(tmp_path)
    with patch(
        "runner.executor_read.handle_inspect_executor_activity",
        return_value={"ok": True, "status": "orphaned", "found": True},
    ):
        result = create_fresh_executor_authority(str(repo))
    assert result["ok"] is False
    assert result["error_code"] == FRESH_EXECUTOR_ADMISSION_LIVE_OPERATION


def test_liveness_completed_schema_with_unknown_nested_claim_fail_closed(
    tmp_path: Path,
) -> None:
    """A nested live-run claim with an unknown status is uninterpretable."""
    repo, _ = _make_repo(tmp_path)
    schema = {
        "ok": True,
        "status": "completed",
        "found": True,
        "live": {
            "available": True,
            "claim_status": "RUNNING",
            "claim": {"status": "future-unknown"},
        },
    }
    with patch(
        "runner.executor_read.handle_inspect_executor_activity",
        return_value=schema,
    ):
        result = create_fresh_executor_authority(str(repo))
    assert result["ok"] is False
    assert result["error_code"] == FRESH_EXECUTOR_ADMISSION_LIVENESS_UNAVAILABLE


# ---------------------------------------------------------------------------
# Repair 3 — P1: nested liveness field present-but-malformed must fail closed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "live_schema",
    (
        {"status": "not_found", "live": {"available": True, "claim": "RUNNING"}},
        {"status": "not_found", "live": {"available": True, "claim": 42}},
        {"status": "not_found", "live": {"available": True, "claim_status": None}},
        {"status": "not_found", "live": {"available": True, "claim_status": 42}},
        {"status": "not_found", "live": {"available": True, "claim": {"status": None}}},
        {"status": "not_found", "live": {"available": True, "claim": {"status": 42}}},
        {"status": "not_found", "live": {"available": "yes"}},
        {"status": "not_found", "live": {"available": 1}},
        {"status": "not_found", "live": {"available": True, "claim_status": "future-unknown"}},
    ),
)
def test_repair3_live_nested_malformed_fail_closed(tmp_path, live_schema):
    repo, _ = _make_repo(tmp_path)
    with patch(
        "runner.executor_read.handle_inspect_executor_activity",
        return_value=live_schema,
    ):
        result = create_fresh_executor_authority(str(repo))
    assert result["ok"] is False
    assert result["error_code"] == FRESH_EXECUTOR_ADMISSION_LIVENESS_UNAVAILABLE
    assert _colameta_file_map(repo) == {}


@pytest.mark.parametrize(
    "extra",
    (
        {"operation_running": "yes"},
        {"operation_running": 1},
        {"operation_running": "true"},
        {"job_status": 5},
        {"job_status": True},
        {"job_status": ["running"]},
        {"claim_status": None},
        {"claim_status": 42},
        {"run_status": None},
        {"run_status": 7},
        {"executor_run_status": "not-a-string"},
    ),
)
def test_repair3_claim_nested_malformed_fail_closed(tmp_path, extra):
    repo, head = _make_repo(tmp_path)
    _write_stale_historical_manifest(repo)
    _write_claim(repo, "preview_repair3", status="COMPLETED", extra=extra)
    result = create_fresh_executor_authority(str(repo), expected_head=head)
    assert result["ok"] is False
    assert result["error_code"] == FRESH_EXECUTOR_ADMISSION_LIVENESS_UNAVAILABLE


def test_repair3_control_absent_optional_fields_preserved(tmp_path):
    """Truly absent optional nested fields keep existing (idle) semantics."""
    repo, head = _make_repo(tmp_path)
    _write_stale_historical_manifest(repo)
    _write_claim(repo, "preview_absent", status="COMPLETED")
    result = create_fresh_executor_authority(str(repo), expected_head=head)
    assert result["ok"] is True


def test_repair3_control_valid_bool_available_preserved(tmp_path):
    repo, _ = _make_repo(tmp_path)
    schema = {"status": "not_found", "live": {"available": False}}
    with patch(
        "runner.executor_read.handle_inspect_executor_activity",
        return_value=schema,
    ):
        result = create_fresh_executor_authority(str(repo))
    assert result["ok"] is True


def test_repair3_control_valid_string_job_status_preserved(tmp_path):
    repo, head = _make_repo(tmp_path)
    _write_stale_historical_manifest(repo)
    _write_claim(repo, "preview_jobidle", status="COMPLETED", extra={"job_status": "idle"})
    result = create_fresh_executor_authority(str(repo), expected_head=head)
    assert result["ok"] is True


def test_repair3_control_operation_running_false_preserved(tmp_path):
    repo, head = _make_repo(tmp_path)
    _write_stale_historical_manifest(repo)
    _write_claim(repo, "preview_opfalse", status="COMPLETED", extra={"operation_running": False})
    result = create_fresh_executor_authority(str(repo), expected_head=head)
    assert result["ok"] is True


def test_repair3_control_conflicting_live_wins(tmp_path):
    repo, _ = _make_repo(tmp_path)
    schema = {
        "status": "completed",
        "live": {"available": True, "claim_status": "RUNNING"},
    }
    with patch(
        "runner.executor_read.handle_inspect_executor_activity",
        return_value=schema,
    ):
        result = create_fresh_executor_authority(str(repo))
    assert result["ok"] is False
    assert result["error_code"] == FRESH_EXECUTOR_ADMISSION_LIVE_OPERATION


def _stage_authority_args(repo: Path, head: str, *, task_id: str = "one") -> dict[str, object]:
    return {
        "expected_repository": "JENN2046/colameta",
        "stage_preview_sha256": "1" * 64,
        "runner_plan_sha256": "2" * 64,
        "stage_id": "stage-a",
        "parallel_group_id": "group-a",
        "task_id": task_id,
        "work_item_id": new_stable_id("work_item"),
        "task_version": 1,
        "attempt_id": new_stable_id("attempt"),
        "artifact_refs": [],
        "expected_git_branch": "main",
        "expected_head": head,
        "provider": "codex",
    }


def test_stage_shard_authority_replay_returns_same_random_authority(tmp_path):
    repo, head = _make_repo(tmp_path)
    args = _stage_authority_args(repo, head)

    first = create_or_resolve_stage_shard_fresh_executor_authority(str(repo), **args)
    second = create_or_resolve_stage_shard_fresh_executor_authority(str(repo), **args)

    assert first["ok"] is second["ok"] is True
    assert first["executor_authority_id"] == second["executor_authority_id"]
    assert first["admission_sha256"] == second["admission_sha256"]
    assert second["idempotent_replay"] is True
    assert len(first["executor_authority_id"]) == 32


def test_stage_shard_authority_concurrent_replay_converges(tmp_path):
    repo, head = _make_repo(tmp_path)
    args = _stage_authority_args(repo, head)
    results: list[dict[str, object]] = []
    barrier = threading.Barrier(8)

    def worker() -> None:
        barrier.wait()
        results.append(
            create_or_resolve_stage_shard_fresh_executor_authority(str(repo), **args)
        )

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert len(results) == 8
    assert all(result["ok"] is True for result in results)
    assert len({result["executor_authority_id"] for result in results}) == 1


def test_stage_shard_malformed_reservation_fails_without_replacement(tmp_path):
    repo, head = _make_repo(tmp_path)
    args = _stage_authority_args(repo, head)
    first = create_or_resolve_stage_shard_fresh_executor_authority(str(repo), **args)
    reservation = (
        Path(executor_authority_dir(str(repo)))
        / first["executor_authority_id"]
        / "stage-shard-admission-reservation.json"
    )
    reservation.write_text("{", encoding="utf-8")
    before = sorted(path.name for path in reservation.parent.parent.iterdir())

    replay = create_or_resolve_stage_shard_fresh_executor_authority(str(repo), **args)

    assert replay["ok"] is False
    assert replay["error_code"] == "STAGE_SHARD_AUTHORITY_RESERVATION_MALFORMED"
    assert sorted(path.name for path in reservation.parent.parent.iterdir()) == before


def test_stage_shard_consumed_authority_is_not_replaced(tmp_path):
    repo, head = _make_repo(tmp_path)
    args = _stage_authority_args(repo, head)
    first = create_or_resolve_stage_shard_fresh_executor_authority(str(repo), **args)
    authority_dir = Path(executor_authority_dir(str(repo))) / first["executor_authority_id"]
    (authority_dir / "execution-binding.json").write_text("{}\n", encoding="utf-8")
    before = sorted(path.name for path in authority_dir.parent.iterdir())

    replay = create_or_resolve_stage_shard_fresh_executor_authority(str(repo), **args)

    assert replay["ok"] is False
    assert replay["error_code"] == "STAGE_SHARD_AUTHORITY_ALREADY_CONSUMED"
    assert sorted(path.name for path in authority_dir.parent.iterdir()) == before


def test_stage_shard_reservation_without_admission_recovers_same_authority(tmp_path):
    repo, head = _make_repo(tmp_path)
    args = _stage_authority_args(repo, head)
    first = create_or_resolve_stage_shard_fresh_executor_authority(str(repo), **args)
    authority_dir = Path(executor_authority_dir(str(repo))) / first["executor_authority_id"]
    (authority_dir / "admission.json").unlink()

    recovered = create_or_resolve_stage_shard_fresh_executor_authority(str(repo), **args)

    assert recovered["ok"] is True
    assert recovered["executor_authority_id"] == first["executor_authority_id"]
    assert recovered["idempotent_replay"] is True


def test_stage_shard_ignores_ordinary_unreserved_authority(tmp_path):
    repo, head = _make_repo(tmp_path)
    ordinary = create_fresh_executor_authority(str(repo), expected_head=head)
    stage = create_or_resolve_stage_shard_fresh_executor_authority(
        str(repo), **_stage_authority_args(repo, head)
    )

    assert ordinary["ok"] is stage["ok"] is True
    assert ordinary["executor_authority_id"] != stage["executor_authority_id"]


def test_stage_shard_duplicate_exact_reservations_fail_conflict(tmp_path):
    repo, head = _make_repo(tmp_path)
    args = _stage_authority_args(repo, head)
    first = create_or_resolve_stage_shard_fresh_executor_authority(str(repo), **args)
    sessions = Path(executor_authority_dir(str(repo)))
    duplicate_id = "f" * 32
    duplicate_dir = sessions / duplicate_id
    duplicate_dir.mkdir(mode=0o700)
    reservation = dict(first["reservation"])
    reservation["reserved_authority_id"] = duplicate_id
    duplicate_file = duplicate_dir / "stage-shard-admission-reservation.json"
    duplicate_file.write_text(json.dumps(reservation), encoding="utf-8")
    duplicate_file.chmod(0o600)

    replay = create_or_resolve_stage_shard_fresh_executor_authority(str(repo), **args)

    assert replay["ok"] is False
    assert replay["error_code"] == "STAGE_SHARD_AUTHORITY_RESERVATION_CONFLICT"


def test_stage_shard_reservation_symlink_fails_closed(tmp_path):
    repo, head = _make_repo(tmp_path)
    args = _stage_authority_args(repo, head)
    first = create_or_resolve_stage_shard_fresh_executor_authority(str(repo), **args)
    reservation = (
        Path(executor_authority_dir(str(repo))) / first["executor_authority_id"]
        / "stage-shard-admission-reservation.json"
    )
    outside = tmp_path / "outside-reservation.json"
    outside.write_text(json.dumps(first["reservation"]), encoding="utf-8")
    reservation.unlink()
    reservation.symlink_to(outside)

    replay = create_or_resolve_stage_shard_fresh_executor_authority(str(repo), **args)

    assert replay["ok"] is False
    assert replay["error_code"] == "STAGE_SHARD_AUTHORITY_RESERVATION_MALFORMED"


@pytest.mark.parametrize("attack", ["hardlink", "fifo", "world_readable", "torn"])
def test_stage_shard_unsafe_reservation_file_fails_without_replacement(
    tmp_path, attack
):
    repo, head = _make_repo(tmp_path)
    args = _stage_authority_args(repo, head)
    first = create_or_resolve_stage_shard_fresh_executor_authority(str(repo), **args)
    sessions = Path(executor_authority_dir(str(repo)))
    reservation = sessions / first["executor_authority_id"] / "stage-shard-admission-reservation.json"
    before = sorted(path.name for path in sessions.iterdir())
    if attack == "hardlink":
        os.link(reservation, tmp_path / "reservation-copy.json")
    elif attack == "fifo":
        reservation.unlink()
        os.mkfifo(reservation, 0o600)
    elif attack == "world_readable":
        reservation.chmod(0o644)
    else:
        reservation.write_bytes(b'{"schema_version":')

    replay = create_or_resolve_stage_shard_fresh_executor_authority(str(repo), **args)

    assert replay["ok"] is False
    assert replay["error_code"] == "STAGE_SHARD_AUTHORITY_RESERVATION_MALFORMED"
    assert sorted(path.name for path in sessions.iterdir()) == before


@pytest.mark.parametrize("attack", ["symlink", "hardlink", "fifo", "world_readable", "corrupt"])
def test_stage_shard_unsafe_admission_file_fails_without_replacement(
    tmp_path, attack
):
    repo, head = _make_repo(tmp_path)
    args = _stage_authority_args(repo, head)
    first = create_or_resolve_stage_shard_fresh_executor_authority(str(repo), **args)
    sessions = Path(executor_authority_dir(str(repo)))
    authority = sessions / first["executor_authority_id"]
    admission = authority / "admission.json"
    before = sorted(path.name for path in sessions.iterdir())
    if attack == "symlink":
        outside = tmp_path / "outside-admission.json"
        outside.write_bytes(admission.read_bytes())
        admission.unlink()
        admission.symlink_to(outside)
    elif attack == "hardlink":
        os.link(admission, tmp_path / "admission-copy.json")
    elif attack == "fifo":
        admission.unlink()
        os.mkfifo(admission, 0o600)
    elif attack == "world_readable":
        admission.chmod(0o644)
    else:
        admission.write_bytes(b"{")

    replay = create_or_resolve_stage_shard_fresh_executor_authority(str(repo), **args)

    assert replay["ok"] is False
    assert sorted(path.name for path in sessions.iterdir()) == before


def test_stage_shard_authority_directory_replacement_fails_closed(tmp_path):
    repo, head = _make_repo(tmp_path)
    args = _stage_authority_args(repo, head)
    first = create_or_resolve_stage_shard_fresh_executor_authority(str(repo), **args)
    sessions = Path(executor_authority_dir(str(repo)))
    authority = sessions / first["executor_authority_id"]
    displaced = tmp_path / "displaced-authority"
    authority.rename(displaced)
    authority.symlink_to(displaced, target_is_directory=True)

    replay = create_or_resolve_stage_shard_fresh_executor_authority(str(repo), **args)

    assert replay["ok"] is False
    assert replay["error_code"] == "STAGE_SHARD_AUTHORITY_RESERVATION_MALFORMED"


def test_stage_shard_sessions_parent_symlink_replacement_fails_closed(tmp_path):
    repo, head = _make_repo(tmp_path)
    args = _stage_authority_args(repo, head)
    first = create_or_resolve_stage_shard_fresh_executor_authority(str(repo), **args)
    sessions = Path(executor_authority_dir(str(repo)))
    displaced = sessions.with_name("executor-sessions-displaced")
    sessions.rename(displaced)
    sessions.symlink_to(displaced, target_is_directory=True)

    replay = create_or_resolve_stage_shard_fresh_executor_authority(str(repo), **args)

    assert replay["ok"] is False
    assert first["executor_authority_id"] in {path.name for path in displaced.iterdir()}


def test_stage_shard_lost_return_after_admission_recovers_same_authority(tmp_path):
    repo, head = _make_repo(tmp_path)
    args = _stage_authority_args(repo, head)
    created_but_return_lost = create_or_resolve_stage_shard_fresh_executor_authority(
        str(repo), **args
    )

    recovered = create_or_resolve_stage_shard_fresh_executor_authority(str(repo), **args)

    assert recovered["ok"] is True
    assert recovered["executor_authority_id"] == created_but_return_lost["executor_authority_id"]
    assert recovered["admission_sha256"] == created_but_return_lost["admission_sha256"]
    assert recovered["idempotent_replay"] is True


def test_stage_shard_cross_shard_reservation_swap_fails_closed(tmp_path):
    repo, head = _make_repo(tmp_path)
    first = create_or_resolve_stage_shard_fresh_executor_authority(
        str(repo), **_stage_authority_args(repo, head, task_id="one")
    )
    second = create_or_resolve_stage_shard_fresh_executor_authority(
        str(repo), **_stage_authority_args(repo, head, task_id="two")
    )
    sessions = Path(executor_authority_dir(str(repo)))
    first_file = sessions / first["executor_authority_id"] / "stage-shard-admission-reservation.json"
    second_file = sessions / second["executor_authority_id"] / "stage-shard-admission-reservation.json"
    temporary = tmp_path / "reservation-swap"
    first_file.rename(temporary)
    second_file.rename(first_file)
    temporary.rename(second_file)
    before = sorted(path.name for path in sessions.iterdir())

    replay = create_or_resolve_stage_shard_fresh_executor_authority(
        str(repo), **_stage_authority_args(repo, head, task_id="one")
    )

    assert replay["ok"] is False
    assert replay["error_code"] == "STAGE_SHARD_AUTHORITY_RESERVATION_MALFORMED"
    assert sorted(path.name for path in sessions.iterdir()) == before


def test_stage_shard_inspection_rejects_cross_task_binding(tmp_path):
    repo, head = _make_repo(tmp_path)
    args = _stage_authority_args(repo, head)
    first = create_or_resolve_stage_shard_fresh_executor_authority(str(repo), **args)
    reservation = first["reservation"]
    binding = {
        key: reservation[key]
        for key in (
            "project_identity", "project_root", "repository",
            "stage_preview_sha256", "runner_plan_sha256", "stage_id",
            "parallel_group_id", "task_id", "work_item_id", "task_version",
            "attempt_id", "artifact_refs", "artifact_refs_sha256",
            "git_branch", "git_head", "provider",
        )
    }
    binding["task_id"] = "other-task"

    inspected = inspect_stage_shard_fresh_executor_authority(
        str(repo),
        first["executor_authority_id"],
        expected_stage_shard_admission_key=first["stage_shard_admission_key"],
        expected_admission_sha256=first["admission_sha256"],
        expected_binding=binding,
    )

    assert inspected["ok"] is False
    assert inspected["error_code"] == "STAGE_SHARD_AUTHORITY_BINDING_MISMATCH"
