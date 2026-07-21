from __future__ import annotations

import json
import multiprocessing
import os
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from runner.project_operation_lease import (
    LEASE_ACQUIRED,
    LEASE_BUSY,
    LEASE_RELEASED,
    LEASE_UNAVAILABLE,
    PROJECT_OPERATION_BUSY,
    PROJECT_OPERATION_LEASE_UNAVAILABLE,
    ProjectOperationLease,
    ProjectOperationLeaseError,
    probe_project_operation_lease,
)
from runner.mcp_executor_workflow import MCPExecutorWorkflowManager
from runner.executor_run_workflow import ExecutorRunOnceService
from runner.web_console import WebConsoleServer


pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX flock lease")


def _try_lease(project_root: str, shared: bool, sender: Any) -> None:
    lease = ProjectOperationLease(project_root, shared=shared, surface="test-child").acquire()
    sender.send(lease.public_status())
    sender.close()
    lease.release()


def _hold_until_released(project_root: str, shared: bool, sender: Any, release_event: Any) -> None:
    lease = ProjectOperationLease(project_root, shared=shared, surface="test-child").acquire()
    sender.send(lease.public_status())
    sender.close()
    release_event.wait(10)
    lease.release()


def _hold_then_exit(project_root: str, sender: Any, exit_event: Any) -> None:
    lease = ProjectOperationLease(project_root, surface="test-crash").acquire()
    sender.send(lease.public_status())
    sender.close()
    exit_event.wait(10)
    os._exit(0)


def _child_status(ctx: Any, project_root: Path, *, shared: bool = False) -> dict[str, Any]:
    receiver, sender = ctx.Pipe(duplex=False)
    process = ctx.Process(target=_try_lease, args=(str(project_root), shared, sender))
    process.start()
    sender.close()
    status = receiver.recv()
    receiver.close()
    process.join(10)
    assert process.exitcode == 0
    return status


@pytest.fixture
def spawn_context() -> Any:
    return multiprocessing.get_context("spawn")


def test_same_canonical_project_is_exclusive_across_processes(tmp_path: Path, spawn_context: Any) -> None:
    project = tmp_path / "project"
    project.mkdir()
    alias = tmp_path / "project-alias"
    alias.symlink_to(project, target_is_directory=True)

    lease = ProjectOperationLease(project, operation_kind="mutate", surface="parent").acquire()
    try:
        assert lease.status == LEASE_ACQUIRED
        assert lease.held is True
        assert lease.canonical_project_root == os.path.realpath(project)
        assert _child_status(spawn_context, alias) == {
            "status": LEASE_BUSY,
            "held": False,
            "shared": False,
            "error_code": PROJECT_OPERATION_BUSY,
        }
    finally:
        lease.release()


def test_different_projects_can_be_held_in_parallel(tmp_path: Path, spawn_context: Any) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()

    first_lease = ProjectOperationLease(first).acquire()
    try:
        assert first_lease.held
        assert _child_status(spawn_context, second)["status"] == LEASE_ACQUIRED
    finally:
        first_lease.release()


def test_kernel_releases_lease_when_holder_process_exits(tmp_path: Path, spawn_context: Any) -> None:
    project = tmp_path / "project"
    project.mkdir()
    receiver, sender = spawn_context.Pipe(duplex=False)
    exit_event = spawn_context.Event()
    process = spawn_context.Process(target=_hold_then_exit, args=(str(project), sender, exit_event))
    process.start()
    sender.close()
    assert receiver.recv()["status"] == LEASE_ACQUIRED
    receiver.close()
    assert ProjectOperationLease(project).acquire().status == LEASE_BUSY

    exit_event.set()
    process.join(10)
    assert process.exitcode == 0
    recovered = ProjectOperationLease(project).acquire()
    try:
        assert recovered.status == LEASE_ACQUIRED
    finally:
        recovered.release()


def test_shared_snapshot_readers_coexist_and_exclude_writer(tmp_path: Path, spawn_context: Any) -> None:
    project = tmp_path / "project"
    project.mkdir()
    reader = ProjectOperationLease(project, shared=True, operation_kind="snapshot").acquire()
    try:
        assert reader.held
        assert _child_status(spawn_context, project, shared=True)["status"] == LEASE_ACQUIRED
        assert _child_status(spawn_context, project, shared=False)["status"] == LEASE_BUSY
    finally:
        reader.release()

    writer = ProjectOperationLease(project).acquire()
    try:
        assert writer.held
        assert _child_status(spawn_context, project, shared=True)["status"] == LEASE_BUSY
    finally:
        writer.release()


def test_group_or_world_writable_project_root_fails_closed(tmp_path: Path) -> None:
    project = tmp_path / "unsafe-project"
    project.mkdir(mode=0o777)
    project.chmod(0o777)
    lease = ProjectOperationLease(project).acquire()
    assert lease.status == LEASE_UNAVAILABLE
    assert lease.held is False
    assert lease.error_code == PROJECT_OPERATION_LEASE_UNAVAILABLE


def test_directory_lease_is_noninheritable_side_effect_free_and_release_is_idempotent(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    before = list(project.iterdir())
    lease = ProjectOperationLease(project).acquire()
    assert lease.held
    assert lease._fd is not None
    assert os.get_inheritable(lease._fd) is False
    assert list(project.iterdir()) == before

    lease.release()
    lease.release()
    assert lease.status == LEASE_RELEASED
    assert lease.held is False


def test_context_manager_releases_and_busy_context_fails_closed(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    with ProjectOperationLease(project) as lease:
        assert lease.held
        with pytest.raises(ProjectOperationLeaseError) as error:
            with ProjectOperationLease(project):
                raise AssertionError("unreachable")
        assert error.value.status == LEASE_BUSY
        assert error.value.error_code == PROJECT_OPERATION_BUSY
    assert lease.status == LEASE_RELEASED


def test_public_probe_is_bounded_and_contains_no_private_identity(tmp_path: Path) -> None:
    project = tmp_path / "private-project-name"
    project.mkdir()
    lease = ProjectOperationLease(
        project,
        operation_kind="secret-operation-token",
        surface="private-surface-token",
    ).acquire()
    try:
        status = probe_project_operation_lease(project)
        assert status == {
            "status": LEASE_BUSY,
            "held": False,
            "shared": False,
            "error_code": PROJECT_OPERATION_BUSY,
        }
        serialized = json.dumps(status, sort_keys=True)
        for forbidden in (
            str(project),
            project.name,
            str(os.getpid()),
            "secret-operation-token",
            "private-surface-token",
            "project_root",
            "path",
            "pid",
            "token",
        ):
            assert forbidden not in serialized
    finally:
        lease.release()

    assert probe_project_operation_lease(project) == {
        "status": "free",
        "held": False,
        "shared": False,
        "error_code": None,
    }


def test_web_mutation_is_rejected_while_cross_process_lease_is_busy(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    held = ProjectOperationLease(project, operation_kind="external", surface="test").acquire()
    assert held.held

    server = WebConsoleServer.__new__(WebConsoleServer)
    server.project_root = str(project)
    server.operation_lock = threading.Lock()
    server.operation_running = False
    server.operation_name = ""
    server.operation_started_at = None
    server._active_project_operation_lease = None
    server.pending_commit_preview = None
    server.pending_run_preview = None
    called = False

    def mutate():
        nonlocal called
        called = True
        return {"ok": True}

    try:
        result = server._run_operation("test_mutation", mutate)
    finally:
        held.release()

    assert result["ok"] is False
    assert result["error_code"] == PROJECT_OPERATION_BUSY
    assert called is False


@pytest.mark.parametrize("action", ["run_once", "run_bounded"])
def test_mcp_operation_lease_releases_when_preflight_raises(
    tmp_path: Path,
    action: str,
) -> None:
    project = tmp_path / action
    project.mkdir()
    manager = MCPExecutorWorkflowManager.__new__(MCPExecutorWorkflowManager)
    manager.project_root = str(project)
    manager._service = SimpleNamespace(
        preflight=lambda **kwargs: (_ for _ in ()).throw(RuntimeError("preflight failed"))
    )
    manager._read_preview_claim_record = lambda preview_id: None
    manager._validate_preview_artifact = lambda *args, **kwargs: {"ok": True}
    manager._preview_guard_error = lambda *args, **kwargs: None

    if action == "run_once":
        manager._read_preview_artifact = lambda preview_id: {
            "artifact_kind": "run_once",
            "executor_session_continuation_facts": {"allowed_session_modes": ["auto"]},
        }
        invoke = lambda: manager._run_once(
            {"preview_id": "preview", "provider": "codex"}
        )
    else:
        manager._read_preview_artifact = lambda preview_id: {
            "artifact_kind": "run_bounded",
            "max_iterations": 1,
            "trusted_mode": False,
            "allow_fix": False,
            "allow_commit": False,
        }
        invoke = lambda: manager._run_bounded(
            {"preview_id": "preview", "provider": "codex"}
        )

    with pytest.raises(RuntimeError, match="preflight failed"):
        invoke()

    recovered = ProjectOperationLease(project).acquire()
    try:
        assert recovered.held
    finally:
        recovered.release()


def test_background_worker_heartbeat_start_failure_releases_lease_and_finalizes_claim(
    tmp_path: Path,
) -> None:
    project = tmp_path / "heartbeat"
    project.mkdir()
    lease = ProjectOperationLease(project).acquire()
    assert lease.held
    manager = MCPExecutorWorkflowManager.__new__(MCPExecutorWorkflowManager)
    finalized: list[dict[str, Any]] = []
    manager._refresh_claim_heartbeat = lambda **kwargs: None
    manager._delete_preview_artifact = lambda preview_id: None
    manager._finalize_preview_claim = lambda **kwargs: finalized.append(kwargs)

    class FailingHeartbeatThread:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            raise RuntimeError("heartbeat start failed")

    with patch("runner.mcp_executor_workflow.threading.Thread", FailingHeartbeatThread):
        manager._run_once_background_worker(
            provider="codex",
            execution_mode="run",
            include_diff_summary=False,
            include_report_markdown=False,
            max_report_chars=100,
            reason="test",
            run_id="run",
            preview_id="preview",
            operation_lease=lease,
        )

    assert lease.held is False
    assert finalized and finalized[0]["final_status"] == "FAILED"


def test_outer_background_worker_start_failure_deletes_preview_and_releases_lease(
    tmp_path: Path,
) -> None:
    project = tmp_path / "outer-worker"
    project.mkdir()
    lease = ProjectOperationLease(project).acquire()
    assert lease.held
    manager = MCPExecutorWorkflowManager.__new__(MCPExecutorWorkflowManager)
    manager._service = SimpleNamespace(run_once=lambda **kwargs: {"ok": True})
    manager._mark_claim_worker_started = lambda **kwargs: None
    deleted: list[str] = []
    finalized: list[dict[str, Any]] = []
    manager._delete_preview_artifact = lambda preview_id: deleted.append(preview_id)
    manager._finalize_preview_claim = lambda **kwargs: finalized.append(kwargs)

    class FailingOuterThread:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            raise RuntimeError("outer worker start failed")

    with (
        patch("runner.mcp_executor_workflow.threading.Thread", FailingOuterThread),
        pytest.raises(RuntimeError, match="outer worker start failed"),
    ):
        manager._start_run_once_background_worker(
            provider="codex",
            execution_mode="run",
            include_diff_summary=False,
            include_report_markdown=False,
            max_report_chars=100,
            reason="test",
            run_id="run",
            preview_id="preview",
            operation_lease=lease,
        )

    assert deleted == ["preview"]
    assert finalized and finalized[0]["final_status"] == "FAILED"
    assert finalized[0]["error_code"] == "BACKGROUND_WORKER_START_FAILED"
    assert lease.held is False
    recovered = ProjectOperationLease(project).acquire()
    try:
        assert recovered.held
    finally:
        recovered.release()


def test_cross_process_busy_blocks_mcp_claim_worker_and_executor_service(
    tmp_path: Path,
    spawn_context: Any,
) -> None:
    project = tmp_path / "busy-integration"
    project.mkdir()
    receiver, sender = spawn_context.Pipe(duplex=False)
    release_event = spawn_context.Event()
    process = spawn_context.Process(
        target=_hold_until_released,
        args=(str(project), False, sender, release_event),
    )
    process.start()
    sender.close()
    assert receiver.recv()["status"] == LEASE_ACQUIRED
    receiver.close()

    manager = MCPExecutorWorkflowManager.__new__(MCPExecutorWorkflowManager)
    manager.project_root = str(project)
    calls = {"preflight": 0, "claim": 0, "worker": 0}

    def forbidden(name: str):
        def call(*args, **kwargs):
            calls[name] += 1
            raise AssertionError(f"{name} must not be reached while lease is busy")

        return call

    manager._service = SimpleNamespace(preflight=forbidden("preflight"))
    manager._read_preview_claim_record = lambda preview_id: None
    manager._read_preview_artifact = lambda preview_id: {
        "artifact_kind": "run_once",
        "executor_session_continuation_facts": {"allowed_session_modes": ["auto"]},
    }
    manager._validate_preview_artifact = lambda *args, **kwargs: {"ok": True}
    manager._claim_preview_artifact = forbidden("claim")
    manager._start_run_once_background_worker = forbidden("worker")

    try:
        mcp_result = manager._run_once({"preview_id": "preview", "provider": "codex"})

        service = ExecutorRunOnceService.__new__(ExecutorRunOnceService)
        service.project_root = str(project)
        service._run_once_under_lease = forbidden("worker")
        service_result = service.run_once(provider="codex")
    finally:
        release_event.set()
        process.join(10)

    assert process.exitcode == 0
    assert mcp_result["error_code"] == PROJECT_OPERATION_BUSY
    assert service_result["error_code"] == PROJECT_OPERATION_BUSY
    assert calls == {"preflight": 0, "claim": 0, "worker": 0}


def test_bounded_exception_after_claim_finalizes_failed_and_releases_lease(
    tmp_path: Path,
) -> None:
    project = tmp_path / "bounded-claimed"
    project.mkdir()
    manager = MCPExecutorWorkflowManager.__new__(MCPExecutorWorkflowManager)
    manager.project_root = str(project)
    preflight_calls = 0

    def preflight(**kwargs):
        nonlocal preflight_calls
        preflight_calls += 1
        if preflight_calls == 1:
            return {
                "preflight_blocked": False,
                "blocking_git_status_short": [],
                "executor_inventory": {},
            }
        raise RuntimeError("iteration preflight failed")

    manager._service = SimpleNamespace(preflight=preflight)
    manager._read_preview_claim_record = lambda preview_id: None
    manager._read_preview_artifact = lambda preview_id: {
        "artifact_kind": "run_bounded",
        "max_iterations": 1,
        "trusted_mode": False,
        "allow_fix": False,
        "allow_commit": False,
    }
    manager._preview_guard_error = lambda *args, **kwargs: None
    manager._compare_bounded_artifact_with_preflight = lambda *args, **kwargs: {"ok": True}
    manager._provider_available = lambda inventory, provider: True
    manager._claim_preview_artifact = lambda **kwargs: {
        "ok": True,
        "run_id": "run-1",
        "claimed_at": "2026-07-21T00:00:00Z",
        "preview_claim_status": "RUNNING",
    }
    deleted: list[str] = []
    finalized: list[dict[str, Any]] = []
    manager._delete_preview_artifact = lambda preview_id: deleted.append(preview_id)
    manager._finalize_preview_claim = lambda **kwargs: finalized.append(kwargs)

    with pytest.raises(RuntimeError, match="iteration preflight failed"):
        manager._run_bounded({"preview_id": "preview", "provider": "codex"})

    assert deleted == ["preview"]
    assert finalized and finalized[0]["final_status"] == "FAILED"
    assert finalized[0]["error_code"] == "BOUNDED_WORKFLOW_CRASHED"
    recovered = ProjectOperationLease(project).acquire()
    try:
        assert recovered.held
    finally:
        recovered.release()
