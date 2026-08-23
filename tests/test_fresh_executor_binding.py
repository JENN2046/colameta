"""Fresh executor authority -> execution binding (R0) tests.

Covers the authoritative FD-anchored admission read, the create-exclusive
execution-binding.json consumption primitive, the service-level fresh-authority
gates, the run_bounded fresh-start block, and the R0 crash-window semantics.
No provider is ever invoked in these tests.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

from runner.fresh_executor_authority import (
    ADMISSION_FILENAME,
    EXECUTION_BINDING_FILENAME,
    FRESH_EXECUTOR_AUTHORITY_ALREADY_CONSUMED,
    FRESH_EXECUTOR_AUTHORITY_BINDING_CONFLICT,
    FRESH_EXECUTOR_AUTHORITY_HEAD_MISMATCH,
    FRESH_EXECUTOR_AUTHORITY_MALFORMED,
    FRESH_EXECUTOR_AUTHORITY_NOT_FOUND,
    FRESH_EXECUTOR_AUTHORITY_PROVIDER_MISMATCH,
    FRESH_EXECUTOR_AUTHORITY_REQUIRED,
    FRESH_EXECUTOR_AUTHORITY_SESSION_MODE_MISMATCH,
    FRESH_EXECUTOR_AUTHORITY_STATE_INVALID,
    FRESH_EXECUTOR_AUTHORITY_WORK_TARGET_MISMATCH,
    FRESH_EXECUTOR_AUTHORITY_WORK_TARGET_REQUIRED,
    create_execution_binding,
    create_fresh_executor_authority,
    executor_authority_dir,
    inspect_fresh_executor_authority_for_execution,
    read_execution_binding,
)
from runner.executor_run_workflow import ExecutorRunOnceService
from runner.work_item_governance.ids import new_stable_id


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)


_COLAMETA_GITIGNORE = """\
__pycache__/
*.py[cod]
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
"""


def _make_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "project"
    repo.mkdir()
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


def _make_authority(repo: Path, head: str) -> tuple[str, str]:
    result = create_fresh_executor_authority(str(repo), expected_head=head)
    assert result.get("ok") is True, result
    authority_id = result["executor_authority_id"]
    admission_path = (
        Path(executor_authority_dir(str(repo))) / authority_id / ADMISSION_FILENAME
    )
    admission_sha256 = hashlib.sha256(admission_path.read_bytes()).hexdigest()
    return authority_id, admission_sha256


def _work_target() -> dict[str, object]:
    return {
        "work_item_id": new_stable_id("work_item"),
        "task_version": 1,
        "attempt_id": new_stable_id("attempt"),
        "artifact_refs": [],
    }


def _binding_path(repo: Path, authority_id: str) -> Path:
    return (
        Path(executor_authority_dir(str(repo)))
        / authority_id
        / EXECUTION_BINDING_FILENAME
    )


def _bind_kwargs(head: str, admission_sha256: str) -> dict[str, object]:
    return {
        "run_id": "exec_run_1",
        "preview_id": "exec_preview_1",
        "admitted_head": head,
        "provider": "codex",
        "executor_session_mode": "start_new",
        "work_target": _work_target(),
        "admission_sha256": admission_sha256,
        "repository": "JENN2046/colameta",
    }


# ---------------------------------------------------------------------------
# A. Authoritative FD-anchored read
# ---------------------------------------------------------------------------


def test_inspect_valid_authority_ok(tmp_path: Path) -> None:
    repo, head = _make_repo(tmp_path)
    authority_id, admission_sha256 = _make_authority(repo, head)

    result = inspect_fresh_executor_authority_for_execution(
        str(repo),
        authority_id,
        expected_admission_sha256=admission_sha256,
        expected_head=head,
        expected_provider="codex",
        expected_repository="JENN2046/colameta",
        expected_git_branch="main",
    )
    assert result.get("ok") is True
    assert result.get("unconsumed") is True
    assert result.get("admission_sha256") == admission_sha256
    assert result.get("record", {}).get("admission_state") == "admitted"


def test_inspect_missing_authority_not_found(tmp_path: Path) -> None:
    repo, _head = _make_repo(tmp_path)
    result = inspect_fresh_executor_authority_for_execution(str(repo), "0" * 32)
    assert result.get("ok") is False
    assert result.get("error_code") == FRESH_EXECUTOR_AUTHORITY_NOT_FOUND


def test_inspect_authority_dir_symlink_blocked(tmp_path: Path) -> None:
    repo, head = _make_repo(tmp_path)
    authority_id, admission_sha256 = _make_authority(repo, head)
    authority_dir = Path(executor_authority_dir(str(repo))) / authority_id
    outside = tmp_path / "outside"
    outside.mkdir()
    moved = tmp_path / "moved-authority"
    os.rename(authority_dir, moved)
    authority_dir.symlink_to(outside, target_is_directory=True)

    result = inspect_fresh_executor_authority_for_execution(
        str(repo),
        authority_id,
        expected_admission_sha256=admission_sha256,
        expected_head=head,
    )
    assert result.get("ok") is False
    assert result.get("error_code") == FRESH_EXECUTOR_AUTHORITY_MALFORMED


def test_inspect_admission_symlink_blocked(tmp_path: Path) -> None:
    repo, head = _make_repo(tmp_path)
    authority_id, admission_sha256 = _make_authority(repo, head)
    admission_path = (
        Path(executor_authority_dir(str(repo))) / authority_id / ADMISSION_FILENAME
    )
    backup = tmp_path / "admission-backup.json"
    os.rename(admission_path, backup)
    admission_path.symlink_to(backup)

    result = inspect_fresh_executor_authority_for_execution(
        str(repo),
        authority_id,
        expected_admission_sha256=admission_sha256,
        expected_head=head,
    )
    assert result.get("ok") is False
    assert result.get("error_code") == FRESH_EXECUTOR_AUTHORITY_MALFORMED


def test_inspect_admission_replaced_hash_mismatch(tmp_path: Path) -> None:
    repo, head = _make_repo(tmp_path)
    authority_id, admission_sha256 = _make_authority(repo, head)
    admission_path = (
        Path(executor_authority_dir(str(repo))) / authority_id / ADMISSION_FILENAME
    )
    record = json.loads(admission_path.read_text(encoding="utf-8"))
    record["admitted_head"] = "1" * 40
    admission_path.write_text(json.dumps(record) + "\n", encoding="utf-8")

    # expected hash is checked before schema: dedicated hash code wins
    result = inspect_fresh_executor_authority_for_execution(
        str(repo),
        authority_id,
        expected_admission_sha256=admission_sha256,
    )
    assert result.get("ok") is False
    assert result.get("error_code") == "FRESH_EXECUTOR_AUTHORITY_HASH_MISMATCH"

    # without expected hash, replaced content fails the schema/head check
    result2 = inspect_fresh_executor_authority_for_execution(
        str(repo), authority_id, expected_head=head
    )
    assert result2.get("ok") is False
    assert result2.get("error_code") == FRESH_EXECUTOR_AUTHORITY_HEAD_MISMATCH


def test_inspect_admission_truncated_malformed(tmp_path: Path) -> None:
    repo, head = _make_repo(tmp_path)
    authority_id, _admission_sha256 = _make_authority(repo, head)
    admission_path = (
        Path(executor_authority_dir(str(repo))) / authority_id / ADMISSION_FILENAME
    )
    admission_path.write_text(
        '{"schema_version": "fresh_executor_authority_ad', encoding="utf-8"
    )
    result = inspect_fresh_executor_authority_for_execution(
        str(repo), authority_id, expected_head=head
    )
    assert result.get("ok") is False
    assert result.get("error_code") == FRESH_EXECUTOR_AUTHORITY_MALFORMED


def test_inspect_malformed_json_malformed(tmp_path: Path) -> None:
    repo, head = _make_repo(tmp_path)
    authority_id, _admission_sha256 = _make_authority(repo, head)
    admission_path = (
        Path(executor_authority_dir(str(repo))) / authority_id / ADMISSION_FILENAME
    )
    admission_path.write_text("{not json", encoding="utf-8")
    result = inspect_fresh_executor_authority_for_execution(
        str(repo), authority_id, expected_head=head
    )
    assert result.get("ok") is False
    assert result.get("error_code") == FRESH_EXECUTOR_AUTHORITY_MALFORMED


def test_inspect_wrong_schema_malformed(tmp_path: Path) -> None:
    repo, head = _make_repo(tmp_path)
    authority_id, _admission_sha256 = _make_authority(repo, head)
    admission_path = (
        Path(executor_authority_dir(str(repo))) / authority_id / ADMISSION_FILENAME
    )
    record = json.loads(admission_path.read_text(encoding="utf-8"))
    record["schema_version"] = "fresh_executor_authority_admission.v2"
    admission_path.write_text(json.dumps(record) + "\n", encoding="utf-8")
    result = inspect_fresh_executor_authority_for_execution(
        str(repo), authority_id, expected_head=head
    )
    assert result.get("ok") is False
    assert result.get("error_code") == FRESH_EXECUTOR_AUTHORITY_MALFORMED


def test_inspect_head_mismatch(tmp_path: Path) -> None:
    repo, head = _make_repo(tmp_path)
    authority_id, _admission_sha256 = _make_authority(repo, head)
    result = inspect_fresh_executor_authority_for_execution(
        str(repo), authority_id, expected_head="2" * 40
    )
    assert result.get("ok") is False
    assert result.get("error_code") == FRESH_EXECUTOR_AUTHORITY_HEAD_MISMATCH


def test_inspect_provider_mismatch(tmp_path: Path) -> None:
    repo, head = _make_repo(tmp_path)
    authority_id, _admission_sha256 = _make_authority(repo, head)
    result = inspect_fresh_executor_authority_for_execution(
        str(repo),
        authority_id,
        expected_head=head,
        expected_provider="opencode",
    )
    assert result.get("ok") is False
    assert result.get("error_code") == FRESH_EXECUTOR_AUTHORITY_PROVIDER_MISMATCH


def test_inspect_unsafe_permissions_malformed(tmp_path: Path) -> None:
    repo, head = _make_repo(tmp_path)
    authority_id, _admission_sha256 = _make_authority(repo, head)
    admission_path = (
        Path(executor_authority_dir(str(repo))) / authority_id / ADMISSION_FILENAME
    )
    os.chmod(admission_path, 0o644)
    result = inspect_fresh_executor_authority_for_execution(
        str(repo), authority_id, expected_head=head
    )
    assert result.get("ok") is False
    assert result.get("error_code") == FRESH_EXECUTOR_AUTHORITY_MALFORMED


def test_inspect_mutated_state_invalid(tmp_path: Path) -> None:
    repo, head = _make_repo(tmp_path)
    authority_id, _admission_sha256 = _make_authority(repo, head)
    admission_path = (
        Path(executor_authority_dir(str(repo))) / authority_id / ADMISSION_FILENAME
    )
    record = json.loads(admission_path.read_text(encoding="utf-8"))
    record["admission_state"] = "consumed"
    admission_path.write_text(json.dumps(record) + "\n", encoding="utf-8")
    result = inspect_fresh_executor_authority_for_execution(
        str(repo), authority_id, expected_head=head
    )
    assert result.get("ok") is False
    assert result.get("error_code") == FRESH_EXECUTOR_AUTHORITY_STATE_INVALID


# ---------------------------------------------------------------------------
# B. execution-binding.json consumption
# ---------------------------------------------------------------------------


def test_first_bind_success(tmp_path: Path) -> None:
    repo, head = _make_repo(tmp_path)
    authority_id, admission_sha256 = _make_authority(repo, head)
    binding = create_execution_binding(
        str(repo), authority_id, **_bind_kwargs(head, admission_sha256)
    )
    assert binding.get("ok") is True, binding
    path = _binding_path(repo, authority_id)
    assert path.is_file()
    assert not path.is_symlink()
    assert (path.stat().st_mode & 0o777) == 0o600
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "fresh_executor_execution_binding.v1"
    assert payload["executor_authority_id"] == authority_id
    assert payload["run_id"] == "exec_run_1"
    assert payload["preview_id"] == "exec_preview_1"
    assert payload["work_item_id"] is not None
    assert payload["executor_session_mode"] == "start_new"
    # admission record remains immutable
    admission_path = (
        Path(executor_authority_dir(str(repo))) / authority_id / ADMISSION_FILENAME
    )
    assert hashlib.sha256(admission_path.read_bytes()).hexdigest() == admission_sha256


def test_second_same_bind_already_consumed(tmp_path: Path) -> None:
    repo, head = _make_repo(tmp_path)
    authority_id, admission_sha256 = _make_authority(repo, head)
    kwargs = _bind_kwargs(head, admission_sha256)
    assert (
        create_execution_binding(str(repo), authority_id, **kwargs).get("ok") is True
    )
    second = create_execution_binding(str(repo), authority_id, **kwargs)
    assert second.get("ok") is False
    assert second.get("error_code") == FRESH_EXECUTOR_AUTHORITY_ALREADY_CONSUMED


def test_second_different_run_binding_conflict(tmp_path: Path) -> None:
    repo, head = _make_repo(tmp_path)
    authority_id, admission_sha256 = _make_authority(repo, head)
    first_kwargs = _bind_kwargs(head, admission_sha256)
    assert (
        create_execution_binding(str(repo), authority_id, **first_kwargs).get("ok")
        is True
    )
    second_kwargs = dict(first_kwargs)
    second_kwargs["run_id"] = "exec_run_2"
    second_kwargs["preview_id"] = "exec_preview_2"
    second = create_execution_binding(str(repo), authority_id, **second_kwargs)
    assert second.get("ok") is False
    assert second.get("error_code") == FRESH_EXECUTOR_AUTHORITY_BINDING_CONFLICT


def test_binding_symlink_blocked(tmp_path: Path) -> None:
    repo, head = _make_repo(tmp_path)
    authority_id, admission_sha256 = _make_authority(repo, head)
    target = tmp_path / "outside-binding.json"
    target.write_text("{}", encoding="utf-8")
    _binding_path(repo, authority_id).symlink_to(target)
    result = create_execution_binding(
        str(repo), authority_id, **_bind_kwargs(head, admission_sha256)
    )
    assert result.get("ok") is False
    assert result.get("error_code") == FRESH_EXECUTOR_AUTHORITY_BINDING_CONFLICT


def test_partial_binding_fail_closed(tmp_path: Path) -> None:
    repo, head = _make_repo(tmp_path)
    authority_id, admission_sha256 = _make_authority(repo, head)
    _binding_path(repo, authority_id).write_text(
        '{"schema_version": "fresh_executor_exec', encoding="utf-8"
    )
    result = create_execution_binding(
        str(repo), authority_id, **_bind_kwargs(head, admission_sha256)
    )
    assert result.get("ok") is False
    assert result.get("error_code") == FRESH_EXECUTOR_AUTHORITY_BINDING_CONFLICT


def test_binding_requires_work_target(tmp_path: Path) -> None:
    repo, head = _make_repo(tmp_path)
    authority_id, admission_sha256 = _make_authority(repo, head)
    kwargs = _bind_kwargs(head, admission_sha256)
    kwargs["work_target"] = {}
    result = create_execution_binding(str(repo), authority_id, **kwargs)
    assert result.get("ok") is False
    assert result.get("error_code") == FRESH_EXECUTOR_AUTHORITY_WORK_TARGET_REQUIRED


def test_binding_requires_start_new_mode(tmp_path: Path) -> None:
    repo, head = _make_repo(tmp_path)
    authority_id, admission_sha256 = _make_authority(repo, head)
    kwargs = _bind_kwargs(head, admission_sha256)
    kwargs["executor_session_mode"] = "resume_existing"
    result = create_execution_binding(str(repo), authority_id, **kwargs)
    assert result.get("ok") is False
    assert result.get("error_code") == FRESH_EXECUTOR_AUTHORITY_SESSION_MODE_MISMATCH


def test_inspect_reports_consumed_after_bind(tmp_path: Path) -> None:
    repo, head = _make_repo(tmp_path)
    authority_id, admission_sha256 = _make_authority(repo, head)
    assert (
        create_execution_binding(
            str(repo), authority_id, **_bind_kwargs(head, admission_sha256)
        ).get("ok")
        is True
    )
    result = inspect_fresh_executor_authority_for_execution(
        str(repo),
        authority_id,
        expected_admission_sha256=admission_sha256,
        expected_head=head,
    )
    assert result.get("ok") is True
    assert result.get("unconsumed") is False
    assert result.get("execution_binding_present") is True
    assert read_execution_binding(str(repo), authority_id) is not None


# ---------------------------------------------------------------------------
# C. Service-level fresh-authority gates (provider never invoked)
# ---------------------------------------------------------------------------


def _service(repo: Path) -> ExecutorRunOnceService:
    return ExecutorRunOnceService(str(repo))


def test_dispatch_gate_start_new_without_authority_required(tmp_path: Path) -> None:
    repo, _head = _make_repo(tmp_path)
    service = _service(repo)
    error = service._fresh_authority_dispatch_gate(
        recommended_action="start_new",
        executor_session_mode="start_new",
        executor_authority_id="",
        admission_sha256="",
    )
    assert error == FRESH_EXECUTOR_AUTHORITY_REQUIRED


def test_dispatch_gate_authority_with_resume_mismatch(tmp_path: Path) -> None:
    repo, _head = _make_repo(tmp_path)
    service = _service(repo)
    error = service._fresh_authority_dispatch_gate(
        recommended_action="resume",
        executor_session_mode="resume_existing",
        executor_authority_id="0" * 32,
        admission_sha256="1" * 64,
    )
    assert error == FRESH_EXECUTOR_AUTHORITY_SESSION_MODE_MISMATCH


def test_dispatch_gate_resume_without_authority_allowed(tmp_path: Path) -> None:
    repo, _head = _make_repo(tmp_path)
    service = _service(repo)
    assert (
        service._fresh_authority_dispatch_gate(
            recommended_action="resume",
            executor_session_mode="resume_existing",
            executor_authority_id="",
            admission_sha256="",
        )
        is None
    )


def test_execution_gate_valid_creates_binding(tmp_path: Path) -> None:
    repo, head = _make_repo(tmp_path)
    authority_id, admission_sha256 = _make_authority(repo, head)
    service = _service(repo)
    target = _work_target()
    result = service._fresh_authority_execution_gate(
        provider="codex",
        executor_session_mode="start_new",
        executor_authority_id=authority_id,
        admission_sha256=admission_sha256,
        continuation_recommended_action="start_new",
        run_id="exec_run_1",
        preview_id="exec_preview_1",
        current_head=head,
        work_target=target,
        claimed_work_target=target,
    )
    assert result.get("ok") is True, result
    assert _binding_path(repo, authority_id).is_file()


def test_execution_gate_stale_authority_head_mismatch(tmp_path: Path) -> None:
    repo, head = _make_repo(tmp_path)
    authority_id, admission_sha256 = _make_authority(repo, head)
    service = _service(repo)
    target = _work_target()
    result = service._fresh_authority_execution_gate(
        provider="codex",
        executor_session_mode="start_new",
        executor_authority_id=authority_id,
        admission_sha256=admission_sha256,
        continuation_recommended_action="start_new",
        run_id="exec_run_1",
        preview_id="exec_preview_1",
        current_head="2" * 40,
        work_target=target,
        claimed_work_target=target,
    )
    assert result.get("ok") is False
    assert result.get("error_code") == FRESH_EXECUTOR_AUTHORITY_HEAD_MISMATCH
    assert not _binding_path(repo, authority_id).exists()


def test_execution_gate_without_work_target_blocked(tmp_path: Path) -> None:
    repo, head = _make_repo(tmp_path)
    authority_id, admission_sha256 = _make_authority(repo, head)
    service = _service(repo)
    result = service._fresh_authority_execution_gate(
        provider="codex",
        executor_session_mode="start_new",
        executor_authority_id=authority_id,
        admission_sha256=admission_sha256,
        continuation_recommended_action="start_new",
        run_id="exec_run_1",
        preview_id="exec_preview_1",
        current_head=head,
        work_target={},
        claimed_work_target=_work_target(),
    )
    assert result.get("ok") is False
    assert result.get("error_code") == FRESH_EXECUTOR_AUTHORITY_WORK_TARGET_REQUIRED
    assert not _binding_path(repo, authority_id).exists()


def test_execution_gate_resume_mode_mismatch(tmp_path: Path) -> None:
    repo, head = _make_repo(tmp_path)
    authority_id, admission_sha256 = _make_authority(repo, head)
    service = _service(repo)
    target = _work_target()
    result = service._fresh_authority_execution_gate(
        provider="codex",
        executor_session_mode="resume_existing",
        executor_authority_id=authority_id,
        admission_sha256=admission_sha256,
        continuation_recommended_action="resume",
        run_id="exec_run_1",
        preview_id="exec_preview_1",
        current_head=head,
        work_target=target,
        claimed_work_target=target,
    )
    assert result.get("ok") is False
    assert result.get("error_code") == FRESH_EXECUTOR_AUTHORITY_SESSION_MODE_MISMATCH


def test_execution_gate_consumed_blocks_replay(tmp_path: Path) -> None:
    repo, head = _make_repo(tmp_path)
    authority_id, admission_sha256 = _make_authority(repo, head)
    service = _service(repo)
    first_target = _work_target()
    first = service._fresh_authority_execution_gate(
        provider="codex",
        executor_session_mode="start_new",
        executor_authority_id=authority_id,
        admission_sha256=admission_sha256,
        continuation_recommended_action="start_new",
        run_id="exec_run_1",
        preview_id="exec_preview_1",
        current_head=head,
        work_target=first_target,
        claimed_work_target=first_target,
    )
    assert first.get("ok") is True
    # replay with a different run must be rejected
    replay_target = _work_target()
    replay = service._fresh_authority_execution_gate(
        provider="codex",
        executor_session_mode="start_new",
        executor_authority_id=authority_id,
        admission_sha256=admission_sha256,
        continuation_recommended_action="start_new",
        run_id="exec_run_2",
        preview_id="exec_preview_2",
        current_head=head,
        work_target=replay_target,
        claimed_work_target=replay_target,
    )
    assert replay.get("ok") is False
    assert replay.get("error_code") == FRESH_EXECUTOR_AUTHORITY_BINDING_CONFLICT
    # same run again is ALREADY_CONSUMED
    same_target = _work_target()
    same = service._fresh_authority_execution_gate(
        provider="codex",
        executor_session_mode="start_new",
        executor_authority_id=authority_id,
        admission_sha256=admission_sha256,
        continuation_recommended_action="start_new",
        run_id="exec_run_1",
        preview_id="exec_preview_1",
        current_head=head,
        work_target=same_target,
        claimed_work_target=same_target,
    )
    assert same.get("ok") is False
    assert same.get("error_code") == FRESH_EXECUTOR_AUTHORITY_ALREADY_CONSUMED


# ---------------------------------------------------------------------------
# D. Crash-window semantics (A/B/C)
# ---------------------------------------------------------------------------


def test_window_a_worker_failure_leaves_authority_unconsumed(tmp_path: Path) -> None:
    repo, head = _make_repo(tmp_path)
    authority_id, admission_sha256 = _make_authority(repo, head)
    # No binding exists (claim-created / thread-spawn-failure state).
    assert not _binding_path(repo, authority_id).exists()
    result = inspect_fresh_executor_authority_for_execution(
        str(repo),
        authority_id,
        expected_admission_sha256=admission_sha256,
        expected_head=head,
    )
    assert result.get("ok") is True
    assert result.get("unconsumed") is True
    # A fresh full-revalidation attempt may then bind successfully.
    assert (
        create_execution_binding(
            str(repo), authority_id, **_bind_kwargs(head, admission_sha256)
        ).get("ok")
        is True
    )


def test_window_b_crash_after_binding_consumes_forever(tmp_path: Path) -> None:
    repo, head = _make_repo(tmp_path)
    authority_id, admission_sha256 = _make_authority(repo, head)
    assert (
        create_execution_binding(
            str(repo), authority_id, **_bind_kwargs(head, admission_sha256)
        ).get("ok")
        is True
    )
    # provider never invoked in this window, but authority is consumed forever.
    replay = create_execution_binding(
        str(repo),
        authority_id,
        run_id="exec_run_9",
        preview_id="exec_preview_9",
        admitted_head=head,
        provider="codex",
        executor_session_mode="start_new",
        work_target=_work_target(),
        admission_sha256=admission_sha256,
        repository="JENN2046/colameta",
    )
    assert replay.get("ok") is False
    assert replay.get("error_code") == FRESH_EXECUTOR_AUTHORITY_BINDING_CONFLICT


def test_window_c_binding_blocks_provider_replay(tmp_path: Path) -> None:
    repo, head = _make_repo(tmp_path)
    authority_id, admission_sha256 = _make_authority(repo, head)
    service = _service(repo)
    first_target = _work_target()
    assert service._fresh_authority_execution_gate(
        provider="codex",
        executor_session_mode="start_new",
        executor_authority_id=authority_id,
        admission_sha256=admission_sha256,
        continuation_recommended_action="start_new",
        run_id="exec_run_1",
        preview_id="exec_preview_1",
        current_head=head,
        work_target=first_target,
        claimed_work_target=first_target,
    ).get("ok") is True
    # any later attempt (post-provider session/report failure) cannot re-run.
    replay_target = _work_target()
    replay = service._fresh_authority_execution_gate(
        provider="codex",
        executor_session_mode="start_new",
        executor_authority_id=authority_id,
        admission_sha256=admission_sha256,
        continuation_recommended_action="start_new",
        run_id="exec_run_1",
        preview_id="exec_preview_1",
        current_head=head,
        work_target=replay_target,
        claimed_work_target=replay_target,
    )
    assert replay.get("ok") is False
    assert replay.get("error_code") == FRESH_EXECUTOR_AUTHORITY_ALREADY_CONSUMED


# ---------------------------------------------------------------------------
# E. run_bounded fresh-start block + MCP preview gate
# ---------------------------------------------------------------------------


def test_bounded_blocked_result_carries_fresh_authority_error_code(
    tmp_path: Path,
) -> None:
    from runner.fresh_executor_authority import (
        FRESH_EXECUTOR_AUTHORITY_BOUNDED_UNSUPPORTED_R0,
    )
    from runner.mcp_executor_workflow import MCPExecutorWorkflowManager

    repo, _head = _make_repo(tmp_path)
    manager = MCPExecutorWorkflowManager(str(repo))
    result = manager._bounded_blocked_result(
        preview_id="p",
        provider="codex",
        max_iterations=1,
        trusted_mode=False,
        allow_fix=False,
        allow_commit=False,
        reason="fresh_authority_bounded_unsupported_r0",
        message="R0 fresh executor authority does not support run_bounded fresh start.",
        blocks=[
            {
                "code": FRESH_EXECUTOR_AUTHORITY_BOUNDED_UNSUPPORTED_R0,
                "message": "run_bounded fresh start unsupported in R0",
            }
        ],
        warnings=[],
        error_code=FRESH_EXECUTOR_AUTHORITY_BOUNDED_UNSUPPORTED_R0,
        classification="blocked_fresh_authority",
    )
    assert result["error_code"] == FRESH_EXECUTOR_AUTHORITY_BOUNDED_UNSUPPORTED_R0
    assert result["classification"] == "blocked_fresh_authority"
    assert result["stop_reason"] == "fresh_authority_bounded_unsupported_r0"
    assert result["blockers"] == [FRESH_EXECUTOR_AUTHORITY_BOUNDED_UNSUPPORTED_R0]


def test_preview_gate_requires_work_target(tmp_path: Path) -> None:
    from runner.mcp_executor_workflow import MCPExecutorWorkflowManager

    repo, head = _make_repo(tmp_path)
    authority_id, admission_sha256 = _make_authority(repo, head)
    manager = MCPExecutorWorkflowManager(str(repo))
    error = manager._fresh_authority_preview_gate(
        authority_id=authority_id,
        admission_sha256=admission_sha256,
        provider="codex",
        executor_session_mode="start_new",
        current_head=head,
        work_target={},
    )
    assert error == FRESH_EXECUTOR_AUTHORITY_WORK_TARGET_REQUIRED


def test_preview_gate_valid_authority_ok(tmp_path: Path) -> None:
    from runner.mcp_executor_workflow import MCPExecutorWorkflowManager

    repo, head = _make_repo(tmp_path)
    authority_id, admission_sha256 = _make_authority(repo, head)
    manager = MCPExecutorWorkflowManager(str(repo))
    error = manager._fresh_authority_preview_gate(
        authority_id=authority_id,
        admission_sha256=admission_sha256,
        provider="codex",
        executor_session_mode="start_new",
        current_head=head,
        work_target=_work_target(),
    )
    assert error is None


def test_preview_gate_consumed_authority_blocked(tmp_path: Path) -> None:
    from runner.mcp_executor_workflow import MCPExecutorWorkflowManager

    repo, head = _make_repo(tmp_path)
    authority_id, admission_sha256 = _make_authority(repo, head)
    assert (
        create_execution_binding(
            str(repo), authority_id, **_bind_kwargs(head, admission_sha256)
        ).get("ok")
        is True
    )
    manager = MCPExecutorWorkflowManager(str(repo))
    error = manager._fresh_authority_preview_gate(
        authority_id=authority_id,
        admission_sha256=admission_sha256,
        provider="codex",
        executor_session_mode="start_new",
        current_head=head,
        work_target=_work_target(),
    )
    assert error == FRESH_EXECUTOR_AUTHORITY_ALREADY_CONSUMED


# ---------------------------------------------------------------------------
# F. P1-1 repair: read->bind directory identity split is CLOSED
# ---------------------------------------------------------------------------


def test_validate_and_bind_single_fd_immune_to_pathname_swap(tmp_path: Path) -> None:
    """Deterministic reversal of the REREVIEW_1 split attack.

    The authority directory pathname is renamed away and a replacement
    directory is created at the original name immediately after the validated
    authority directory FD is opened.  Because admission validation AND the
    O_EXCL binding create use the SAME open authority directory object, the
    binding lands in the validated directory, never in the replacement.
    """
    import runner.fresh_executor_authority as fea

    repo, head = _make_repo(tmp_path)
    authority_id, admission_sha256 = _make_authority(repo, head)
    validated_dir = Path(fea.executor_authority_dir(str(repo))) / authority_id

    real_open = fea._open_existing_authority_dir
    state: dict[str, str] = {}

    def interposer(sessions_fd: int, authority_id: str):
        fd, err = real_open(sessions_fd, authority_id)
        if "swapped" not in state and fd >= 0:
            state["swapped"] = "yes"
            moved = Path(tmp_path) / "validated-dir-moved"
            os.rename(validated_dir, moved)
            os.mkdir(validated_dir)  # replacement dir occupies the old name
            state["moved"] = str(moved)
        return fd, err

    fea._open_existing_authority_dir = interposer
    try:
        result = fea.validate_and_create_execution_binding(
            str(repo),
            authority_id,
            expected_admission_sha256=admission_sha256,
            expected_head=head,
            expected_provider="codex",
            expected_repository="JENN2046/colameta",
            expected_git_branch="main",
            run_id="exec_run_1",
            preview_id="exec_preview_1",
            executor_session_mode="start_new",
            work_target=_work_target(),
            repository="JENN2046/colameta",
        )
    finally:
        fea._open_existing_authority_dir = real_open

    assert result.get("ok") is True, result
    moved = Path(state["moved"])
    assert (moved / EXECUTION_BINDING_FILENAME).is_file()      # validated object got the binding
    assert not (validated_dir / EXECUTION_BINDING_FILENAME).exists()  # replacement did NOT
    # admission in the validated object is still byte-identical
    assert hashlib.sha256((moved / ADMISSION_FILENAME).read_bytes()).hexdigest() == admission_sha256


def test_gate_validate_and_bind_single_fd_immune_to_sessions_swap(tmp_path: Path) -> None:
    """Same attack at the gate level: sessions/authority name swap cannot
    redirect the binding to a different object; provider gate still ok only
    because the binding landed on the validated object."""
    import runner.fresh_executor_authority as fea

    repo, head = _make_repo(tmp_path)
    authority_id, admission_sha256 = _make_authority(repo, head)
    validated_dir = Path(fea.executor_authority_dir(str(repo))) / authority_id

    real_open = fea._open_existing_authority_dir
    state: dict[str, str] = {}

    def interposer(sessions_fd: int, authority_id: str):
        fd, err = real_open(sessions_fd, authority_id)
        if "swapped" not in state and fd >= 0:
            state["swapped"] = "yes"
            moved = Path(tmp_path) / "validated-dir-moved"
            os.rename(validated_dir, moved)
            os.mkdir(validated_dir)
            state["moved"] = str(moved)
        return fd, err

    fea._open_existing_authority_dir = interposer
    try:
        service = _service(repo)
        target = _work_target()
        result = service._fresh_authority_execution_gate(
            provider="codex",
            executor_session_mode="start_new",
            executor_authority_id=authority_id,
            admission_sha256=admission_sha256,
            continuation_recommended_action="start_new",
            run_id="exec_run_1",
            preview_id="exec_preview_1",
            current_head=head,
            work_target=target,
            claimed_work_target=target,
        )
    finally:
        fea._open_existing_authority_dir = real_open

    assert result.get("ok") is True, result
    moved = Path(state["moved"])
    assert (moved / EXECUTION_BINDING_FILENAME).is_file()
    assert not (validated_dir / EXECUTION_BINDING_FILENAME).exists()


# ---------------------------------------------------------------------------
# G. P1-2 repair: preview/claim -> provider-before work-target exact chain
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mutate",
    [
        "work_item_id",
        "task_version",
        "attempt_id",
        "artifact_refs",
    ],
)
def test_work_target_substitution_blocked(tmp_path: Path, mutate: str) -> None:
    repo, head = _make_repo(tmp_path)
    authority_id, admission_sha256 = _make_authority(repo, head)
    service = _service(repo)
    claimed = _work_target()
    current = dict(claimed)
    if mutate == "work_item_id":
        current["work_item_id"] = new_stable_id("work_item")
    elif mutate == "task_version":
        current["task_version"] = current["task_version"] + 1
    elif mutate == "attempt_id":
        current["attempt_id"] = new_stable_id("attempt")
    elif mutate == "artifact_refs":
        current["artifact_refs"] = [new_stable_id("artifact")]
    # current target is itself complete + governed (valid stable ids) — still must block
    result = service._fresh_authority_execution_gate(
        provider="codex",
        executor_session_mode="start_new",
        executor_authority_id=authority_id,
        admission_sha256=admission_sha256,
        continuation_recommended_action="start_new",
        run_id="exec_run_1",
        preview_id="exec_preview_1",
        current_head=head,
        work_target=current,
        claimed_work_target=claimed,
    )
    assert result.get("ok") is False
    assert result.get("error_code") == FRESH_EXECUTOR_AUTHORITY_WORK_TARGET_MISMATCH
    assert not _binding_path(repo, authority_id).exists()  # no consumption on mismatch


def test_work_target_substitution_head_unchanged_blocked(tmp_path: Path) -> None:
    """HEAD stays the same; only the governed work target changes -> block."""
    repo, head = _make_repo(tmp_path)
    authority_id, admission_sha256 = _make_authority(repo, head)
    service = _service(repo)
    claimed = _work_target()
    current = dict(claimed)
    current["work_item_id"] = new_stable_id("work_item")
    result = service._fresh_authority_execution_gate(
        provider="codex",
        executor_session_mode="start_new",
        executor_authority_id=authority_id,
        admission_sha256=admission_sha256,
        continuation_recommended_action="start_new",
        run_id="exec_run_1",
        preview_id="exec_preview_1",
        current_head=head,  # same head
        work_target=current,
        claimed_work_target=claimed,
    )
    assert result.get("ok") is False
    assert result.get("error_code") == FRESH_EXECUTOR_AUTHORITY_WORK_TARGET_MISMATCH
    assert not _binding_path(repo, authority_id).exists()


def test_work_target_exact_same_continues(tmp_path: Path) -> None:
    repo, head = _make_repo(tmp_path)
    authority_id, admission_sha256 = _make_authority(repo, head)
    service = _service(repo)
    target = _work_target()
    result = service._fresh_authority_execution_gate(
        provider="codex",
        executor_session_mode="start_new",
        executor_authority_id=authority_id,
        admission_sha256=admission_sha256,
        continuation_recommended_action="start_new",
        run_id="exec_run_1",
        preview_id="exec_preview_1",
        current_head=head,
        work_target=target,
        claimed_work_target=target,
    )
    assert result.get("ok") is True, result
    assert _binding_path(repo, authority_id).is_file()


def test_gate_requires_frozen_claimed_work_target(tmp_path: Path) -> None:
    """Fresh start with authority but NO frozen claimed work target -> block."""
    repo, head = _make_repo(tmp_path)
    authority_id, admission_sha256 = _make_authority(repo, head)
    service = _service(repo)
    result = service._fresh_authority_execution_gate(
        provider="codex",
        executor_session_mode="start_new",
        executor_authority_id=authority_id,
        admission_sha256=admission_sha256,
        continuation_recommended_action="start_new",
        run_id="exec_run_1",
        preview_id="exec_preview_1",
        current_head=head,
        work_target=_work_target(),
        claimed_work_target=None,
    )
    assert result.get("ok") is False
    assert result.get("error_code") == FRESH_EXECUTOR_AUTHORITY_WORK_TARGET_MISMATCH
    assert not _binding_path(repo, authority_id).exists()


@pytest.mark.parametrize("provider", ["pi", "opencode"])
def test_non_codex_fresh_start_blocked(tmp_path: Path, provider: str) -> None:
    """R0 codex-only: pi/opencode fresh start with a codex authority is blocked."""
    repo, head = _make_repo(tmp_path)
    authority_id, admission_sha256 = _make_authority(repo, head)
    service = _service(repo)
    target = _work_target()
    result = service._fresh_authority_execution_gate(
        provider=provider,
        executor_session_mode="start_new",
        executor_authority_id=authority_id,
        admission_sha256=admission_sha256,
        continuation_recommended_action="start_new",
        run_id="exec_run_1",
        preview_id="exec_preview_1",
        current_head=head,
        work_target=target,
        claimed_work_target=target,
    )
    assert result.get("ok") is False
    assert result.get("error_code") == FRESH_EXECUTOR_AUTHORITY_PROVIDER_MISMATCH
    assert not _binding_path(repo, authority_id).exists()
