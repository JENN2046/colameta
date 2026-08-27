from __future__ import annotations

import hashlib
import fcntl
import json
import multiprocessing
import os
import socket
import stat
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from runner.executor_events import (
    ExecutorEventIntegrityError,
    ExecutorEventStore,
    public_executor_projection,
)
from runner.executor_read import build_live_snapshot
from runner.executor_run_reports import ExecutorRunReportStore
from runner.executor_run_claims import ExecutorRunClaimStore
from runner.executor_run_workflow import (
    ExecutorRunOnceService,
    _public_executor_workflow_projection,
)
from runner.executor_session import ExecutorSessionStore
from runner.executor_status import read_executor_events_for_status
from runner.fresh_executor_authority import _read_execution_binding_verification
from runner.web_console_v2_assets import render_v2_index_page
from runner.work_item_governance.ids import new_stable_id


AUTHORITY_ID = "a" * 32
ADMISSION_SHA256 = "b" * 64


class _AuthorityEqualitySpoof:
    def __init__(self, expected: str) -> None:
        self.expected = expected

    def __eq__(self, other: object) -> bool:
        return other == self.expected

    def __str__(self) -> str:
        raise AssertionError("authority material must not be coerced")

    def strip(self) -> str:
        raise AssertionError("authority material must not be normalized")


class _AuthorityStringSubclass(str):
    pass


def _fail_selected_fsync(monkeypatch, module, surface: str) -> None:
    original_fsync = module.os.fsync

    def injected(fd: int) -> None:
        is_directory = stat.S_ISDIR(os.fstat(fd).st_mode)
        if (surface == "directory") == is_directory:
            raise OSError(f"injected {surface} fsync failure")
        original_fsync(fd)

    monkeypatch.setattr(module.os, "fsync", injected)


def _claim_store(project_root: Path) -> ExecutorRunClaimStore:
    return ExecutorRunClaimStore(
        str(project_root),
        ".colameta/runtime/executor-workflow-previews",
        "claims",
        heartbeat_interval_seconds=5,
        heartbeat_stale_multiplier=3,
        heartbeat_stale_min_seconds=20,
    )


def _authority_bound_claim_artifact() -> dict[str, object]:
    return {
        "artifact_kind": "run_once",
        "current_version": "v1",
        "current_head": "c" * 40,
        "created_at": "2026-08-26T00:00:00+00:00",
        "expires_at": "2026-08-26T00:15:00+00:00",
        "stage_executor_preview_request_sha256": "d" * 64,
        "fresh_execution_authority": {
            "executor_authority_id": AUTHORITY_ID,
            "admission_sha256": ADMISSION_SHA256,
            "admitted_head": "c" * 40,
            "provider": "codex",
            "executor_session_mode": "start_new",
        },
    }


def _append_process_batch(project_root: str, worker: int) -> None:
    store = ExecutorEventStore(project_root)
    for sequence in range(15):
        store.append("run-1", "heartbeat", {"worker": worker, "sequence": sequence})


def _context() -> dict[str, object]:
    return {
        "run_id": "run-1",
        "preview_id": "preview-1",
        "version": "v1",
        "provider": "codex",
        "execution_mode": "run",
        "work_item_id": new_stable_id("work_item"),
        "task_version": 1,
        "attempt_id": new_stable_id("attempt"),
        "artifact_refs": [],
        "executor_authority_id": AUTHORITY_ID,
        "admission_sha256": ADMISSION_SHA256,
    }


def _surface_context(
    context: dict[str, object],
    schema_version: str = "test_durable_lineage.v1",
) -> dict[str, object]:
    return {"schema_version": schema_version, **context}


def _managed_workspace(tmp_path: Path) -> Path:
    runner_dir = tmp_path / ".colameta"
    prompts_dir = runner_dir / "prompts"
    prompts_dir.mkdir(parents=True)
    runner_dir.chmod(0o755)
    (runner_dir / "plan.json").write_text(
        json.dumps(
            {
                "project_name": "demo",
                "project_root": str(tmp_path),
                "work_item_id": new_stable_id("work_item"),
                "task_version": 1,
                "attempt_id": new_stable_id("attempt"),
                "versions": [
                    {
                        "version": "v1",
                        "name": "Bound run",
                        "prompt_file": ".colameta/prompts/v1.md",
                        "enabled": True,
                        "allowed_files": ["runner/**"],
                        "acceptance_commands": [
                            {
                                "command": "git diff --check",
                                "timeout_seconds": 120,
                                "continue_on_failure": False,
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (runner_dir / "state.json").write_text(
        json.dumps(
            {
                "project_name": "demo",
                "status": "READY",
                "current_version": "v1",
                "current_version_index": 0,
                "attempt": 1,
                "versions": [
                    {
                        "version": "v1",
                        "name": "Bound run",
                        "status": "NOT_STARTED",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (prompts_dir / "v1.md").write_text("proof\n", encoding="utf-8")
    return tmp_path


def _secure_manual_run_dir(store: ExecutorEventStore, run_id: str = "run-1") -> Path:
    run_dir = Path(store.run_dir(run_id))
    run_dir.mkdir(parents=True)
    current = run_dir.parent
    while current != Path(store.project_root):
        current.chmod(0o755)
        current = current.parent
    run_dir.chmod(0o700)
    return run_dir


def _write_durable_binding_and_claim(
    project_root: Path, context: dict[str, object]
) -> tuple[Path, Path]:
    event_store = ExecutorEventStore(str(project_root))
    if not event_store.has_events(str(context["run_id"])):
        pre_binding_context = {
            key: value
            for key, value in context.items()
            if key not in {"executor_authority_id", "admission_sha256"}
        }
        event_store.append(
            str(context["run_id"]), "run_claimed", {}, pre_binding_context
        )
    stream_origin = event_store.capture_stream_origin(str(context["run_id"]))
    assert stream_origin.get("ok") is True, stream_origin
    authority_dir = (
        project_root
        / ".colameta"
        / "runtime"
        / "executor-sessions"
        / str(context["executor_authority_id"])
    )
    authority_dir.mkdir(parents=True, exist_ok=True)
    current = authority_dir
    while current != project_root:
        current.chmod(0o700)
        current = current.parent
    binding_path = authority_dir / "execution-binding.json"
    binding = {
        "schema_version": "fresh_executor_execution_binding.v2",
        "executor_authority_id": context["executor_authority_id"],
        "admission_sha256": context["admission_sha256"],
        "project_root": str(project_root),
        "repository": "JENN2046/colameta",
        "run_id": context["run_id"],
        "preview_id": context["preview_id"],
        "admitted_head": "c" * 40,
        "provider": context["provider"],
        "executor_session_mode": "start_new",
        "work_item_id": context["work_item_id"],
        "task_version": context["task_version"],
        "attempt_id": context["attempt_id"],
        "artifact_refs": context["artifact_refs"],
        "event_stream": stream_origin["stream_origin_contract"],
        "bound_at": "2026-08-25T00:00:00+00:00",
        "source": "fresh_executor_authority_execution_binding",
    }
    binding_path.write_text(
        json.dumps(binding) + "\n",
        encoding="utf-8",
    )
    binding_path.chmod(0o600)
    claims_dir = (
        project_root
        / ".colameta"
        / "runtime"
        / "executor-workflow-previews"
        / "claims"
    )
    claims_dir.mkdir(parents=True, exist_ok=True)
    current = claims_dir
    while current != project_root:
        current.chmod(0o700)
        current = current.parent
    claim_path = claims_dir / f"{context['preview_id']}.json"
    claim = {
        "schema_version": "executor_run_claim.v1",
        "preview_id": context["preview_id"],
        "run_id": context["run_id"],
        "artifact_kind": "run_once",
        "project_root": str(project_root),
        "provider": context["provider"],
        "execution_mode": context["execution_mode"],
        "current_version": context["version"],
        "current_head": "c" * 40,
        "claimed_at": "2026-08-25T00:00:00+00:00",
        "status": "RUNNING",
        "model": None,
        "model_source": None,
        "worker_pid": os.getpid(),
        "worker_started_at": "2026-08-25T00:00:00+00:00",
        "thread_started_at": "",
        "last_heartbeat_at": "2026-08-25T00:00:00+00:00",
        "heartbeat_interval_seconds": 5,
        "heartbeat_timeout_seconds": 20,
        "original_preview_created_at": "2026-08-25T00:00:00+00:00",
        "original_preview_expires_at": "2026-08-25T00:15:00+00:00",
        "executor_authority_id": context["executor_authority_id"],
        "admission_sha256": context["admission_sha256"],
        "work_item_id": context["work_item_id"],
        "task_version": context["task_version"],
        "attempt_id": context["attempt_id"],
        "artifact_refs": context["artifact_refs"],
    }
    claim_path.write_text(
        json.dumps(claim) + "\n",
        encoding="utf-8",
    )
    claim_path.chmod(0o600)
    return binding_path, claim_path


def _durable_binding_and_claim_paths(
    project_root: Path, context: dict[str, object]
) -> tuple[Path, Path]:
    binding_path = (
        project_root
        / ".colameta"
        / "runtime"
        / "executor-sessions"
        / str(context["executor_authority_id"])
        / "execution-binding.json"
    )
    claim_path = (
        project_root
        / ".colameta"
        / "runtime"
        / "executor-workflow-previews"
        / "claims"
        / f"{context['preview_id']}.json"
    )
    return binding_path, claim_path


def _prepare_post_verifier_surfaces(
    tmp_path: Path,
    *,
    finalize_lifecycle: bool = True,
) -> tuple[dict[str, object], ExecutorRunOnceService, str, dict[str, object]]:
    context = _context()
    store = ExecutorEventStore(str(tmp_path))
    pre_binding_context = {
        key: value
        for key, value in context.items()
        if key not in {"executor_authority_id", "admission_sha256"}
    }
    store.append("run-1", "run_claimed", {}, pre_binding_context)
    store.append("run-1", "executor_dispatch_started", {}, context)
    _write_durable_binding_and_claim(tmp_path, context)
    service = ExecutorRunOnceService(str(tmp_path))
    binding_verification = _read_execution_binding_verification(
        str(tmp_path), AUTHORITY_ID, expected_run_id="run-1"
    )
    assert binding_verification["ok"] is True, binding_verification
    pre_provider = service._capture_pre_provider_lineage(
        run_id="run-1",
        expected_context=context,
        binding_context=service._read_durable_binding_context(AUTHORITY_ID),
        claim_context=service._read_durable_claim_context("preview-1"),
    )
    assert pre_provider["ok"] is True, pre_provider
    store.append("run-1", "executor_finished", {}, context)

    sessions = ExecutorSessionStore(str(tmp_path))
    sessions.record_execution(
        provider="codex",
        version="v1",
        execution_mode="run",
        attempt=1,
        work_item_id=context["work_item_id"],
        task_version=context["task_version"],
        attempt_id=context["attempt_id"],
        artifact_refs=context["artifact_refs"],
        executor_authority_id=AUTHORITY_ID,
        admission_sha256=ADMISSION_SHA256,
    )
    assert sessions.bind_private_lineage(context)["ok"] is True
    report = ExecutorRunReportStore(str(tmp_path)).record_report(
        version="v1",
        provider="codex",
        execution_mode="run",
        status="completed",
        execution_lineage=dict(context),
        work_item_id=context["work_item_id"],
        task_version=context["task_version"],
        attempt_id=context["attempt_id"],
        artifact_refs=context["artifact_refs"],
    )
    assert report["ok"] is True
    if finalize_lifecycle:
        store.append(
            "run-1", "run_completed", {"report_id": report["report_id"]}, context
        )
        claims = _claim_store(tmp_path)
        claims.finalize_claim(
            preview_id="preview-1",
            run_id="run-1",
            final_status="COMPLETED",
            report_id=str(report["report_id"]),
        )
        finalized_claim = service._capture_verified_surface(
            name="CLAIM",
            verification=claims._read_claim_verification(
                "preview-1", expected_run_id="run-1"
            ),
            run_id="run-1",
            mutable_fields=frozenset(
                {
                    "status",
                    "worker_pid",
                    "worker_started_at",
                    "thread_started_at",
                    "last_heartbeat_at",
                    "heartbeat_interval_seconds",
                    "heartbeat_timeout_seconds",
                    "finished_at",
                    "report_id",
                    "error_code",
                    "error_message",
                    "exception_type",
                    "blockers",
                    "warnings",
                }
            ),
        )
        assert finalized_claim["ok"] is True, finalized_claim
        pre_provider["finalized_claim"] = finalized_claim
    return context, service, str(report["report_id"]), pre_provider


def _atomic_replace_json(path: Path, payload: dict[str, object]) -> None:
    replacement = path.with_name(f".{path.name}.replacement")
    replacement.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    replacement.chmod(0o600)
    os.replace(replacement, path)


def _install_synchronized_same_inode_mutation(
    monkeypatch,
    target: Path,
    *,
    truncate_regrow: bool,
) -> threading.Thread:
    original_pread = os.pread
    original = target.read_bytes()
    replacement = original.replace(b"codex", b"c0dex", 1)
    if replacement == original:
        replacement = original.replace(b"heartbeat", b"heartbeet", 1)
    assert replacement != original
    assert len(replacement) == len(original)
    boundary_reached = threading.Event()
    mutation_done = threading.Event()
    target_identity = (target.stat().st_dev, target.stat().st_ino)
    triggered = False

    def mutate() -> None:
        assert boundary_reached.wait(timeout=5)
        fd = os.open(target, os.O_WRONLY)
        try:
            if truncate_regrow:
                os.ftruncate(fd, 0)
            os.pwrite(fd, replacement, 0)
            os.ftruncate(fd, len(replacement))
            os.fsync(fd)
        finally:
            os.close(fd)
            mutation_done.set()

    worker = threading.Thread(target=mutate, daemon=True)
    worker.start()

    def synchronized_pread(fd: int, size: int, offset: int) -> bytes:
        nonlocal triggered
        data = original_pread(fd, size, offset)
        metadata = os.fstat(fd)
        if (
            not triggered
            and (metadata.st_dev, metadata.st_ino) == target_identity
            and size == 1
            and offset == len(original)
        ):
            triggered = True
            boundary_reached.set()
            assert mutation_done.wait(timeout=5)
        return data

    monkeypatch.setattr(os, "pread", synchronized_pread)
    return worker


def test_private_lineage_is_durable_but_default_read_is_public_safe(tmp_path: Path) -> None:
    store = ExecutorEventStore(str(tmp_path))
    context = _context()
    context["run_id"] = "forged-context-run"
    store.append(
        "run-1",
        "executor_started",
        {
            "provider": "codex",
            "nested": {
                "executor_authority_id": AUTHORITY_ID,
                "admission_sha256": ADMISSION_SHA256,
            },
        },
        context,
    )

    public = store.read("run-1")[-1]
    assert public["schema_version"] == "1.1"
    assert public["run_id"] == "run-1"
    assert "fresh_authority_bound" not in public
    assert "executor_authority_id" not in public
    assert "admission_sha256" not in public
    assert public["data"]["nested"] == {}

    private = store.read("run-1", include_private_lineage=True)[-1]
    assert private["executor_authority_id"] == AUTHORITY_ID
    assert private["admission_sha256"] == ADMISSION_SHA256
    assert private["artifact_refs"] == []

    events_file = Path(store.run_dir("run-1")) / "events.jsonl"
    assert stat.S_IMODE(events_file.stat().st_mode) == 0o600
    assert stat.S_IMODE(events_file.parent.stat().st_mode) == 0o700


def test_partial_or_malformed_private_lineage_is_omitted(tmp_path: Path) -> None:
    store = ExecutorEventStore(str(tmp_path))
    partial = _context()
    partial.pop("admission_sha256")
    malformed = _context()
    malformed["executor_authority_id"] = "not-an-authority"

    store.append("run-1", "heartbeat", {}, partial)
    store.append("run-1", "heartbeat", {}, malformed)

    for event in store.read("run-1", include_private_lineage=True):
        assert "executor_authority_id" not in event
        assert "admission_sha256" not in event


@pytest.mark.parametrize(
    "missing_field",
    ["work_item_id", "task_version", "attempt_id", "artifact_refs", "preview_id"],
)
def test_private_lineage_requires_complete_valid_t1_and_preview(
    tmp_path: Path, missing_field: str
) -> None:
    store = ExecutorEventStore(str(tmp_path))
    context = _context()
    context.pop(missing_field)

    store.append("run-1", "heartbeat", {}, context)

    private = store.read("run-1", include_private_lineage=True)[-1]
    public = store.read("run-1")[-1]
    assert "executor_authority_id" not in private
    assert "admission_sha256" not in private
    assert "fresh_authority_bound" not in public


def test_event_symlink_target_is_not_followed(tmp_path: Path) -> None:
    store = ExecutorEventStore(str(tmp_path))
    run_dir = _secure_manual_run_dir(store)
    target = tmp_path / "target.txt"
    target.write_text("unchanged\n", encoding="utf-8")
    (run_dir / "events.jsonl").symlink_to(target)

    store.append("run-1", "heartbeat", {}, {"run_id": "run-1"})

    assert target.read_text(encoding="utf-8") == "unchanged\n"
    with pytest.raises(ExecutorEventIntegrityError):
        store.read("run-1", include_private_lineage=True)


@pytest.mark.parametrize("operation", ["append", "read", "has_events"])
def test_fifo_event_target_is_rejected_without_blocking(
    tmp_path: Path, operation: str
) -> None:
    store = ExecutorEventStore(str(tmp_path))
    run_dir = _secure_manual_run_dir(store)
    os.mkfifo(run_dir / "events.jsonl")

    started = time.monotonic()
    if operation == "append":
        store.append("run-1", "heartbeat", {}, _context())
    elif operation == "read":
        with pytest.raises(ExecutorEventIntegrityError):
            store.read("run-1")
    else:
        assert store.has_events("run-1") is False

    assert time.monotonic() - started < 1.0


def test_socket_event_target_is_rejected_without_blocking(tmp_path: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="cm-event-", dir="/tmp") as project_root:
        store = ExecutorEventStore(project_root)
        run_dir = _secure_manual_run_dir(store)
        event_socket = socket.socket(socket.AF_UNIX)
        try:
            event_socket.bind(str(run_dir / "events.jsonl"))
            started = time.monotonic()
            store.append("run-1", "heartbeat", {}, _context())
            with pytest.raises(ExecutorEventIntegrityError):
                store.read("run-1")
            assert store.has_events("run-1") is False
            assert time.monotonic() - started < 1.0
        finally:
            event_socket.close()


@pytest.mark.parametrize("component", [".colameta", "runtime", "executor-runs"])
def test_intermediate_symlink_cannot_escape_project_root(
    tmp_path: Path, component: str
) -> None:
    external = tmp_path.parent / f"external-{tmp_path.name}-{component.strip('.')}"
    external.mkdir()
    current = tmp_path
    components = [".colameta", "runtime", "executor-runs"]
    for name in components:
        path = current / name
        if name == component:
            path.symlink_to(external, target_is_directory=True)
            break
        path.mkdir()
        current = path

    store = ExecutorEventStore(str(tmp_path))
    store.append("run-1", "heartbeat", {}, _context())

    assert not (external / "run-1").exists()
    with pytest.raises(ExecutorEventIntegrityError):
        store.read("run-1")
    assert store.has_events("run-1") is False


def test_run_directory_symlink_cannot_escape_event_root(tmp_path: Path) -> None:
    store = ExecutorEventStore(str(tmp_path))
    runs_dir = Path(store._runs_dir())
    runs_dir.mkdir(parents=True)
    external = tmp_path.parent / f"external-run-{tmp_path.name}"
    external.mkdir()
    (runs_dir / "run-1").symlink_to(external, target_is_directory=True)

    store.append("run-1", "heartbeat", {}, _context())

    assert not (external / "events.jsonl").exists()


def test_event_hardlink_target_cannot_modify_external_file(tmp_path: Path) -> None:
    store = ExecutorEventStore(str(tmp_path))
    run_dir = _secure_manual_run_dir(store)
    external = tmp_path / "external.txt"
    external.write_text("unchanged\n", encoding="utf-8")
    os.link(external, run_dir / "events.jsonl")

    store.append("run-1", "heartbeat", {}, _context())

    assert external.read_text(encoding="utf-8") == "unchanged\n"
    assert store.has_events("run-1") is False


def test_legacy_event_schemas_remain_readable(tmp_path: Path) -> None:
    store = ExecutorEventStore(str(tmp_path))
    run_dir = _secure_manual_run_dir(store)
    records = [
        {
            "schema_version": "1.0",
            "run_id": "run-1",
            "event_type": "heartbeat",
            "executor_authority_id": AUTHORITY_ID,
            "admission_sha256": ADMISSION_SHA256,
            "data": {},
        },
        {
            "ts": "2026-01-01T00:00:00Z",
            "event": "heartbeat",
            "data": {"run_id": "run-1"},
        },
    ]
    event_file = run_dir / "events.jsonl"
    event_file.write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )
    event_file.chmod(0o600)

    events = store.read("run-1")
    assert [event["schema_version"] for event in events] == ["1.0", "0.9"]
    assert "fresh_authority_bound" not in events[0]
    assert "executor_authority_id" not in events[0]


def test_legacy_event_cannot_enter_durable_proof_with_valid_terminal(
    tmp_path: Path,
) -> None:
    store = ExecutorEventStore(str(tmp_path))
    run_dir = _secure_manual_run_dir(store)
    event_file = run_dir / "events.jsonl"
    event_file.write_text(
        json.dumps({"ts": "2026-01-01T00:00:00Z", "event": "heartbeat", "data": {"run_id": "run-1"}})
        + "\n",
        encoding="utf-8",
    )
    event_file.chmod(0o600)
    store.append("run-1", "executor_finished", {}, _context())

    assert len(store.read("run-1")) == 2
    proof = store.capture_durable_contract("run-1", expected_lineage=_context())
    assert proof == {"ok": False, "error_code": "EVENT_PROOF_SCHEMA_INVALID"}


def test_invalid_run_id_cannot_escape_event_root(tmp_path: Path) -> None:
    store = ExecutorEventStore(str(tmp_path))
    store.append("../outside", "heartbeat", {}, {"run_id": "../outside"})
    assert not (tmp_path / "outside").exists()


@pytest.mark.parametrize("run_id", [".", "..", ".hidden", "hidden."])
def test_dot_component_run_ids_fail_closed_for_all_operations(
    tmp_path: Path, run_id: str
) -> None:
    store = ExecutorEventStore(str(tmp_path))
    store.append(run_id, "heartbeat", {})
    assert store.read_with_integrity(run_id)["error_code"] == "EVENT_RUN_ID_INVALID"
    assert store.read(run_id) == []
    assert store.has_events(run_id) is False


def test_public_projection_discards_forged_bound_flags(tmp_path: Path) -> None:
    forged = {
        "schema_version": "1.1",
        "run_id": "run-1",
        "preview_id": "preview-1",
        "fresh_authority_bound": True,
        "data": {"fresh_authority_bound": True},
    }
    projected = public_executor_projection(forged)
    assert "fresh_authority_bound" not in projected
    assert "fresh_authority_bound" not in projected["data"]


def test_public_projection_discards_private_event_stream_identity() -> None:
    projected = public_executor_projection(
        {
            "binding": {
                "event_stream": {
                    "identity": {"device": 7, "inode": 11},
                    "size": 23,
                    "raw_sha256": "0" * 64,
                    "record_count": 1,
                }
            }
        }
    )

    assert projected == {"binding": {}}


def test_event_inode_swap_between_precheck_and_open_fails_closed(
    tmp_path: Path, monkeypatch
) -> None:
    store = ExecutorEventStore(str(tmp_path))
    store.append("run-1", "heartbeat", {"sequence": 1})
    event_file = Path(store.run_dir("run-1")) / "events.jsonl"
    displaced = event_file.with_name("events.displaced")
    original = store._precheck_regular_file

    def swap_after_precheck(run_fd: int, filename: str, *, allow_missing: bool):
        metadata = original(run_fd, filename, allow_missing=allow_missing)
        event_file.rename(displaced)
        event_file.write_bytes(b"")
        return metadata

    monkeypatch.setattr(store, "_precheck_regular_file", swap_after_precheck)
    store.append("run-1", "heartbeat", {"sequence": 2})

    assert event_file.read_bytes() == b""
    assert b'"sequence": 2' not in displaced.read_bytes()


def test_production_pre_provider_proof_rejects_cross_append_run_dir_recreate(
    tmp_path: Path,
) -> None:
    context = _context()
    store = ExecutorEventStore(str(tmp_path))
    pre_binding_context = {
        key: value
        for key, value in context.items()
        if key not in {"executor_authority_id", "admission_sha256"}
    }
    store.append("run-1", "run_claimed", {}, pre_binding_context)
    _write_durable_binding_and_claim(tmp_path, context)

    original_run_dir = Path(store.run_dir("run-1"))
    displaced_run_dir = original_run_dir.with_name("run-1-original")
    original_run_dir.rename(displaced_run_dir)
    original_run_dir.mkdir(mode=0o700)
    store.append("run-1", "executor_dispatch_started", {}, context)

    service = ExecutorRunOnceService(str(tmp_path))
    result = service._capture_pre_provider_lineage(
        run_id="run-1",
        expected_context=context,
        binding_context=service._read_durable_binding_context(AUTHORITY_ID),
        claim_context=service._read_durable_claim_context("preview-1"),
    )

    assert result == {"ok": False, "error_code": "EVENT_DURABLE_IDENTITY_DRIFT"}
    assert b'"event_type": "run_claimed"' in (
        displaced_run_dir / "events.jsonl"
    ).read_bytes()
    assert b'"event_type": "executor_dispatch_started"' in (
        original_run_dir / "events.jsonl"
    ).read_bytes()


@pytest.mark.parametrize("component", ["run", "executor-runs"])
def test_directory_chain_rename_swap_fails_closed_without_writing_displaced_tree(
    tmp_path: Path, monkeypatch, component: str
) -> None:
    store = ExecutorEventStore(str(tmp_path))
    store.append("run-1", "heartbeat", {"sequence": 1})
    run_dir = Path(store.run_dir("run-1"))
    original_event = run_dir / "events.jsonl"
    original_bytes = original_event.read_bytes()
    original_flock = store._bounded_flock
    swapped = {"done": False}

    def swap_after_lock(event_fd: int, operation: int) -> None:
        original_flock(event_fd, operation)
        if swapped["done"]:
            return
        swapped["done"] = True
        if component == "run":
            displaced = tmp_path.parent / f"displaced-run-{tmp_path.name}"
            run_dir.rename(displaced)
            run_dir.mkdir(mode=0o700)
        else:
            runs_dir = run_dir.parent
            displaced = tmp_path.parent / f"displaced-runs-{tmp_path.name}"
            runs_dir.rename(displaced)
            replacement_run = runs_dir / "run-1"
            replacement_run.mkdir(parents=True, mode=0o700)

    monkeypatch.setattr(store, "_bounded_flock", swap_after_lock)
    store.append("run-1", "heartbeat", {"sequence": 2})

    displaced_event = (
        tmp_path.parent / f"displaced-run-{tmp_path.name}" / "events.jsonl"
        if component == "run"
        else tmp_path.parent
        / f"displaced-runs-{tmp_path.name}"
        / "run-1"
        / "events.jsonl"
    )
    assert displaced_event.read_bytes() == original_bytes
    replacement_event = Path(store.run_dir("run-1")) / "events.jsonl"
    assert not replacement_event.exists()


def test_forged_schema_1_1_lineage_fails_closed(tmp_path: Path) -> None:
    store = ExecutorEventStore(str(tmp_path))
    store.append("run-1", "executor_started", {}, _context())
    event_file = Path(store.run_dir("run-1")) / "events.jsonl"
    record = json.loads(event_file.read_text(encoding="utf-8"))
    record.pop("artifact_refs")
    event_file.write_text(json.dumps(record) + "\n", encoding="utf-8")

    integrity = store.read_with_integrity("run-1", include_private_lineage=True)
    assert integrity["ok"] is False
    assert integrity["error_code"] == "EVENT_PRIVATE_LINEAGE_INVALID"
    with pytest.raises(ExecutorEventIntegrityError) as exc_info:
        store.read("run-1")
    assert exc_info.value.error_code == "EVENT_PRIVATE_LINEAGE_INVALID"


def test_on_disk_run_id_must_match_actual_event_path(tmp_path: Path) -> None:
    store = ExecutorEventStore(str(tmp_path))
    store.append("run-1", "executor_started", {}, _context())
    event_file = Path(store.run_dir("run-1")) / "events.jsonl"
    record = json.loads(event_file.read_text(encoding="utf-8"))
    record["run_id"] = "run-2"
    event_file.write_text(json.dumps(record) + "\n", encoding="utf-8")

    integrity = store.read_with_integrity("run-1", include_private_lineage=True)
    assert integrity["error_code"] == "EVENT_PRIVATE_LINEAGE_INVALID"


def test_concurrent_thread_append_preserves_complete_json_records(tmp_path: Path) -> None:
    store = ExecutorEventStore(str(tmp_path))

    def append_batch(worker: int) -> None:
        for sequence in range(25):
            store.append("run-1", "heartbeat", {"worker": worker, "sequence": sequence})

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(append_batch, range(8)))

    result = store.read_with_integrity("run-1", limit=500)
    assert result["ok"] is True
    assert len(result["events"]) == 200
    assert {
        (event["data"]["worker"], event["data"]["sequence"])
        for event in result["events"]
    } == {(worker, sequence) for worker in range(8) for sequence in range(25)}


def test_concurrent_process_append_preserves_complete_json_records(tmp_path: Path) -> None:
    context = multiprocessing.get_context("fork")
    processes = [
        context.Process(target=_append_process_batch, args=(str(tmp_path), worker))
        for worker in range(4)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=10)
        assert process.exitcode == 0

    result = ExecutorEventStore(str(tmp_path)).read_with_integrity("run-1", limit=100)
    assert result["ok"] is True
    assert len(result["events"]) == 60


def test_short_writes_are_retried_until_record_is_complete(
    tmp_path: Path, monkeypatch
) -> None:
    original_write = os.write

    def short_write(fd: int, data) -> int:
        return original_write(fd, data[: max(1, len(data) // 3)])

    monkeypatch.setattr(os, "write", short_write)
    store = ExecutorEventStore(str(tmp_path))
    store.append("run-1", "heartbeat", {"payload": "x" * 4096})

    result = store.read_with_integrity("run-1")
    assert result["ok"] is True
    assert result["events"][0]["data"]["payload"] == "x" * 4096


def test_oversized_event_record_is_rejected_without_partial_write(tmp_path: Path) -> None:
    store = ExecutorEventStore(str(tmp_path))
    store.append("run-1", "heartbeat", {"payload": "x" * (2 * 1024 * 1024)})

    assert store.read("run-1") == []


def test_oversized_forged_record_is_rejected_by_streaming_reader(
    tmp_path: Path
) -> None:
    store = ExecutorEventStore(str(tmp_path))
    store.append("run-1", "heartbeat", {"sequence": 1})
    event_file = Path(store.run_dir("run-1")) / "events.jsonl"
    event_file.write_bytes(b'{"payload":"' + (b"x" * (1024 * 1024)) + b'"}\n')

    result = store.read_with_integrity("run-1")
    assert result["ok"] is False
    assert result["error_code"] == "EVENT_RECORD_TOO_LARGE"
    assert result["events"] == []


def test_event_proof_bounds_total_file_bytes(tmp_path: Path) -> None:
    store = ExecutorEventStore(str(tmp_path))
    run_dir = _secure_manual_run_dir(store)
    event_file = run_dir / "events.jsonl"
    event_file.write_bytes(b"x" * (16 * 1024 * 1024 + 1))
    event_file.chmod(0o600)

    result = store.capture_durable_contract("run-1", expected_lineage=_context())

    assert result == {"ok": False, "error_code": "EVENT_FILE_TOO_LARGE"}


def test_event_proof_bounds_total_record_count(tmp_path: Path) -> None:
    store = ExecutorEventStore(str(tmp_path))
    run_dir = _secure_manual_run_dir(store)
    event_file = run_dir / "events.jsonl"
    context = _context()
    store.append("run-1", "heartbeat", {}, context)
    record = json.loads(event_file.read_text(encoding="utf-8"))
    event_file.write_text(
        (json.dumps(record) + "\n") * 10_001,
        encoding="utf-8",
    )
    event_file.chmod(0o600)

    result = store.capture_durable_contract("run-1", expected_lineage=context)

    assert result == {"ok": False, "error_code": "EVENT_RECORD_LIMIT_EXCEEDED"}


@pytest.mark.parametrize("truncate_regrow", [False, True])
def test_event_proof_rejects_synchronized_same_inode_mutation(
    tmp_path: Path, monkeypatch, truncate_regrow: bool
) -> None:
    store = ExecutorEventStore(str(tmp_path))
    context = _context()
    store.append("run-1", "heartbeat", {"payload": "x" * 1024}, context)
    event_file = Path(store.run_dir("run-1")) / "events.jsonl"
    worker = _install_synchronized_same_inode_mutation(
        monkeypatch,
        event_file,
        truncate_regrow=truncate_regrow,
    )

    result = store.capture_durable_contract("run-1", expected_lineage=context)
    worker.join(timeout=5)

    assert worker.is_alive() is False
    assert result["ok"] is False
    assert result["error_code"] in {
        "EVENT_DURABLE_METADATA_DRIFT",
        "EVENT_STORE_UNAVAILABLE",
    }


def test_event_proof_exposes_bounded_raw_prefix_and_content_evidence(
    tmp_path: Path,
) -> None:
    store = ExecutorEventStore(str(tmp_path))
    context = _context()
    store.append("run-1", "executor_finished", {}, context)

    result = store.capture_durable_contract("run-1", expected_lineage=context)

    assert result["ok"] is True
    contract = result["durable_contract"]
    assert {
        "identity", "metadata", "size", "raw_sha256", "content_sha256",
        "prefix_size", "prefix_sha256", "record_count",
        "pre_binding_record_count", "post_binding_record_count",
    } == set(contract)
    assert contract["raw_sha256"] != contract["content_sha256"]
    assert contract["metadata"]["size"] == contract["size"]
    assert contract["record_count"] == 1


@pytest.mark.parametrize(
    ("mutation", "error_code"),
    [
        ("extra_field", "EVENT_PROOF_FIELDS_INVALID"),
        ("wrong_data_type", "EVENT_PROOF_TYPES_INVALID"),
        ("wrong_authority", "EVENT_PROOF_LINEAGE_MISMATCH"),
        ("wrong_work_item", "EVENT_PROOF_LINEAGE_MISMATCH"),
        ("missing_authority", "EVENT_POST_BINDING_PROOF_MISSING"),
    ],
)
def test_proof_parser_enforces_exact_schema_types_and_expected_lineage(
    tmp_path: Path, mutation: str, error_code: str
) -> None:
    context = _context()
    store = ExecutorEventStore(str(tmp_path))
    store.append("run-1", "executor_finished", {}, context)
    event_path = Path(store.run_dir("run-1")) / "events.jsonl"
    record = json.loads(event_path.read_text(encoding="utf-8"))
    if mutation == "extra_field":
        record["untrusted"] = True
    elif mutation == "wrong_data_type":
        record["data"] = []
    elif mutation == "wrong_authority":
        record["executor_authority_id"] = "c" * 32
    elif mutation == "wrong_work_item":
        record["work_item_id"] = new_stable_id("work_item")
    else:
        record.pop("executor_authority_id")
        record.pop("admission_sha256")
    event_path.write_text(json.dumps(record) + "\n", encoding="utf-8")
    event_path.chmod(0o600)

    result = store.capture_durable_contract(
        "run-1", expected_lineage=context
    )

    assert result == {"ok": False, "error_code": error_code}


def test_pre_binding_prefix_is_explicit_and_cannot_follow_or_replace_proof(
    tmp_path: Path,
) -> None:
    context = _context()
    pre_binding = {
        key: value
        for key, value in context.items()
        if key not in {"executor_authority_id", "admission_sha256"}
    }
    store = ExecutorEventStore(str(tmp_path))
    store.append("run-1", "executor_preparing", {}, pre_binding)

    prefix_only = store.capture_durable_contract(
        "run-1", expected_lineage=context
    )
    assert prefix_only == {
        "ok": False,
        "error_code": "EVENT_POST_BINDING_PROOF_MISSING",
    }

    store.append("run-1", "executor_dispatch_started", {}, context)
    admitted = store.capture_durable_contract(
        "run-1", expected_lineage=context
    )
    assert admitted["ok"] is True, admitted
    assert admitted["durable_contract"]["pre_binding_record_count"] == 1
    assert admitted["durable_contract"]["post_binding_record_count"] == 1

    store.append("run-1", "heartbeat", {}, pre_binding)
    rejected = store.capture_durable_contract(
        "run-1", expected_lineage=context
    )
    assert rejected == {
        "ok": False,
        "error_code": "EVENT_PRE_BINDING_RECORD_AFTER_BINDING",
    }


def test_final_torn_tail_is_reported_with_prior_records(tmp_path: Path) -> None:
    store = ExecutorEventStore(str(tmp_path))
    store.append("run-1", "heartbeat", {"sequence": 1})
    event_file = Path(store.run_dir("run-1")) / "events.jsonl"
    with event_file.open("ab") as stream:
        stream.write(b'{"schema_version":"1.1"')

    result = store.read_with_integrity("run-1")
    assert result["ok"] is False
    assert result["error_code"] == "EVENT_TORN_TAIL"
    assert result["torn_tail"] is True
    assert result["events"] == []


def test_parseable_unterminated_json_is_still_a_torn_tail(tmp_path: Path) -> None:
    store = ExecutorEventStore(str(tmp_path))
    store.append("run-1", "heartbeat", {"sequence": 1})
    event_file = Path(store.run_dir("run-1")) / "events.jsonl"
    payload = event_file.read_bytes().rstrip(b"\n")
    event_file.write_bytes(payload)

    result = store.read_with_integrity("run-1")
    assert result["ok"] is False
    assert result["error_code"] == "EVENT_TORN_TAIL"
    assert result["events"] == []


def test_interior_malformed_record_is_reported_and_fails_closed(tmp_path: Path) -> None:
    store = ExecutorEventStore(str(tmp_path))
    store.append("run-1", "heartbeat", {"sequence": 1})
    event_file = Path(store.run_dir("run-1")) / "events.jsonl"
    with event_file.open("ab") as stream:
        stream.write(b"{malformed}\n")
        stream.write(b'{"schema_version":"1.0","run_id":"run-1","event_type":"heartbeat","data":{}}\n')

    result = store.read_with_integrity("run-1")
    assert result["ok"] is False
    assert result["error_code"] == "EVENT_INTERIOR_CORRUPTION"
    assert result["events"] == []


def test_private_lineage_verifier_returns_only_safe_result_fields(tmp_path: Path) -> None:
    store = ExecutorEventStore(str(tmp_path))
    context = _context()
    store.append("run-1", "executor_dispatch_started", {}, context)

    result = store.verify_private_lineage(
        "run-1",
        expected_event_context=context,
        event_type="executor_dispatch_started",
        claim_context=_surface_context(context),
        report_context=_surface_context(context),
        session_context=_surface_context(context),
    )

    assert result["ok"] is True
    assert set(result) == {"ok", "error_code", "safe_digest"}
    assert len(result["safe_digest"]) == 64
    serialized = json.dumps(result)
    assert AUTHORITY_ID not in serialized
    assert ADMISSION_SHA256 not in serialized


def test_private_lineage_verifier_fails_closed_on_surface_mismatch(tmp_path: Path) -> None:
    store = ExecutorEventStore(str(tmp_path))
    context = _context()
    store.append("run-1", "executor_dispatch_started", {}, context)
    claim = _surface_context(context)
    claim["preview_id"] = "different-preview"

    result = store.verify_private_lineage(
        "run-1",
        expected_event_context=context,
        event_type="executor_dispatch_started",
        claim_context=claim,
    )

    assert result == {
        "ok": False,
        "error_code": "CLAIM_LINEAGE_MISMATCH",
        "safe_digest": "",
    }


def test_live_and_status_event_payloads_do_not_disclose_nested_pair(tmp_path: Path) -> None:
    store = ExecutorEventStore(str(tmp_path))
    store.append(
        "run-1",
        "heartbeat",
        {"nested": {"executor_authority_id": AUTHORITY_ID, "admission_sha256": ADMISSION_SHA256}},
        _context(),
    )

    status_events = read_executor_events_for_status(str(tmp_path), "run-1")
    live = build_live_snapshot(str(tmp_path), "run-1")
    for payload in (status_events, live["events"]):
        serialized = json.dumps(payload)
        assert AUTHORITY_ID not in serialized
        assert ADMISSION_SHA256 not in serialized
        assert "fresh_authority_bound" not in payload[0]


def test_real_report_event_excerpt_does_not_disclose_nested_pair(
    tmp_path: Path,
) -> None:
    import runner.executor_read as executor_read_module

    store = ExecutorEventStore(str(tmp_path))
    store.append(
        "run-1",
        "report_written",
        {"nested": {"executor_authority_id": AUTHORITY_ID, "admission_sha256": ADMISSION_SHA256}},
        _context(),
    )

    context = _context()
    report_result = ExecutorRunReportStore(str(tmp_path)).record_report(
        version="v1",
        provider="codex",
        execution_mode="run",
        status="completed",
        execution_lineage=dict(context),
        executor_report_text=f"authority={AUTHORITY_ID} admission={ADMISSION_SHA256}",
        work_item_id=context["work_item_id"],
        task_version=context["task_version"],
        attempt_id=context["attempt_id"],
        artifact_refs=context["artifact_refs"],
    )
    assert report_result["ok"] is True
    result = executor_read_module._get_report(str(tmp_path), {})

    serialized = json.dumps(result)
    assert AUTHORITY_ID not in serialized
    assert ADMISSION_SHA256 not in serialized
    assert "fresh_authority_bound" not in result["report"]
    assert "fresh_authority_bound" not in result["report"]["events"][0]


def test_real_session_public_status_does_not_disclose_private_pair(
    tmp_path: Path
) -> None:
    context = _context()
    sessions = ExecutorSessionStore(str(tmp_path))
    recorded = sessions.record_execution(
        provider="codex",
        version="v1",
        execution_mode="run",
        attempt=1,
        work_item_id=context["work_item_id"],
        task_version=context["task_version"],
        attempt_id=context["attempt_id"],
        artifact_refs=context["artifact_refs"],
        executor_authority_id=AUTHORITY_ID,
        admission_sha256=ADMISSION_SHA256,
    )
    assert sessions.bind_private_lineage(context)["ok"] is True
    public_status = sessions.get_status()
    private_status = sessions.get_status(include_private_lineage=True)

    assert AUTHORITY_ID not in json.dumps(recorded)
    assert AUTHORITY_ID not in json.dumps(public_status)
    assert ADMISSION_SHA256 not in json.dumps(public_status)
    assert "fresh_authority_bound" not in public_status["record"]
    assert private_status["record"]["executor_authority_id"] == AUTHORITY_ID


def test_public_report_and_session_shapes_drop_unknown_attacker_fields(
    tmp_path: Path,
) -> None:
    context = _context()
    report_store = ExecutorRunReportStore(str(tmp_path))
    recorded = report_store.record_report(
        version="v1",
        provider="codex",
        execution_mode="run",
        status="completed",
        execution_lineage=dict(context),
        work_item_id=context["work_item_id"],
        task_version=context["task_version"],
        attempt_id=context["attempt_id"],
        artifact_refs=context["artifact_refs"],
    )
    report_path = Path(str(recorded["json_file"]))
    report_payload = json.loads(report_path.read_text(encoding="utf-8"))
    report_payload["attacker_controlled_extra"] = {AUTHORITY_ID: ADMISSION_SHA256}
    report_payload["execution_lineage"]["attacker_lineage_extra"] = "must not survive"
    report_path.write_text(json.dumps(report_payload) + "\n", encoding="utf-8")
    report_path.chmod(0o600)

    report = report_store.get_report(report_id=str(recorded["report_id"]))

    assert report["ok"] is False
    assert report["error_code"] == "REPORT_CONTRACT_FIELDS_INVALID"
    assert AUTHORITY_ID not in repr(report)
    assert ADMISSION_SHA256 not in repr(report)
    assert report_store.read_durable_contract(
        report_id=str(recorded["report_id"]),
        expected_run_id="run-1",
    )["ok"] is False

    session_store = ExecutorSessionStore(str(tmp_path))
    session_store.record_execution(
        provider="codex",
        version="v1",
        execution_mode="run",
        attempt=1,
    )
    session_path = Path(session_store.manifest_file)
    session_payload = json.loads(session_path.read_text(encoding="utf-8"))
    session_payload["attacker_controlled_extra"] = {AUTHORITY_ID: ADMISSION_SHA256}
    session_path.write_text(json.dumps(session_payload) + "\n", encoding="utf-8")
    session_path.chmod(0o600)

    status = session_store.get_status()

    assert status["error_code"] == "MANIFEST_INVALID"
    assert AUTHORITY_ID not in repr(status)
    assert ADMISSION_SHA256 not in repr(status)
    assert session_store.read_durable_contract(expected_run_id="run-1")["ok"] is False


def test_workflow_projection_is_closed_and_redacts_key_value_aliases() -> None:
    response = {
        "ok": False,
        "status": "failed",
        "message": f"authority={AUTHORITY_ID} admission={ADMISSION_SHA256}",
        "durable_contract": {"metadata": {"size": 123}},
        "attacker_surface": {AUTHORITY_ID: ADMISSION_SHA256},
        "next_actions": [
            {
                "tool": "manage_executor_workflow",
                "action": "preflight",
                "params": {
                    "action": "preflight",
                    "provider": "codex",
                    "private_alias": ADMISSION_SHA256,
                },
                "reason": f"copied={AUTHORITY_ID}",
                "requires_confirmation": False,
                "unknown_action_field": {"metadata": "private"},
            }
        ],
    }

    projected = _public_executor_workflow_projection(
        response,
        executor_authority_id=AUTHORITY_ID,
        admission_sha256=ADMISSION_SHA256,
    )

    assert set(projected) == {"ok", "status", "message", "next_actions"}
    assert set(projected["next_actions"][0]) == {
        "tool", "action", "params", "reason", "requires_confirmation",
    }
    assert set(projected["next_actions"][0]["params"]) == {"action", "provider"}
    assert AUTHORITY_ID not in repr(projected)
    assert ADMISSION_SHA256 not in repr(projected)
    assert "durable_contract" not in projected


def test_shared_projection_redacts_case_insensitive_alias_only_values_on_all_surfaces() -> None:
    from runner.executor_run_reports import public_executor_report_projection
    from runner.executor_session import public_executor_session_projection
    from runner.executor_status import apply_claim_to_status
    from runner.web_console import public_executor_web_projection

    authority_id = "abcdef0123456789" * 2
    admission_sha256 = "abcdef0123456789" * 4
    alias_envelope = {
        "ExEcUtOr_AuThOrItY_Id": authority_id,
        "EXPECTED_ADMISSION_SHA256": admission_sha256,
    }
    transformed = f"pair={authority_id.upper()}:{admission_sha256.upper()}"

    report = public_executor_report_projection({
        **alias_envelope,
        "status": transformed,
        "execution_lineage": dict(alias_envelope),
    })
    session = public_executor_session_projection({
        **alias_envelope,
        "ok": False,
        "message": transformed,
        "record": {**alias_envelope, "source": transformed},
    })
    web = public_executor_web_projection({
        **alias_envelope,
        "ok": False,
        "message": transformed,
    })
    success = _public_executor_workflow_projection({
        **alias_envelope,
        "ok": True,
        "status": "completed",
        "message": transformed,
    })
    error = _public_executor_workflow_projection({
        **alias_envelope,
        "ok": False,
        "status": "failed",
        "message": transformed,
    })
    status: dict[str, object] = {}
    apply_claim_to_status(
        status,
        {
            **alias_envelope,
            "status": "FAILED",
            "error_message": transformed,
        },
        {},
    )

    for projected in (report, session, web, success, error, status):
        serialized = json.dumps(projected, ensure_ascii=False).lower()
        assert authority_id.lower() not in serialized
        assert admission_sha256.lower() not in serialized
        assert not any(
            key.lower() in {
                "executor_authority_id", "expected_admission_sha256"
            }
            for key in projected
        )


def test_event_append_rejects_unknown_type_and_blocked_event_has_defined_phase(
    tmp_path: Path,
) -> None:
    store = ExecutorEventStore(str(tmp_path))
    with pytest.raises(ValueError, match="unknown executor event type"):
        store.append("run-1", "attacker_defined_terminal", {})

    store.append(
        "run-1",
        "executor_blocked",
        {"error_code": "EXPECTED_BLOCK"},
        {**_context(), "phase": "authority_gate"},
    )
    events = store.read("run-1")
    assert events[-1]["event_type"] == "executor_blocked"
    assert events[-1]["phase"] == "authority_gate"


@pytest.mark.parametrize(
    "supplied_pair",
    [
        {},
        {"executor_authority_id": AUTHORITY_ID},
        {"admission_sha256": ADMISSION_SHA256},
        {
            "executor_authority_id": "e" * 32,
            "admission_sha256": ADMISSION_SHA256,
        },
        {
            "executor_authority_id": AUTHORITY_ID,
            "admission_sha256": "f" * 64,
        },
    ],
)
def test_authority_bound_claim_rejects_missing_partial_or_wrong_pair_without_side_effects(
    tmp_path: Path,
    supplied_pair: dict[str, object],
) -> None:
    store = _claim_store(tmp_path)

    result = store.acquire_claim(
        preview_id="preview-authority-bound",
        artifact=_authority_bound_claim_artifact(),
        provider="codex",
        execution_mode="run",
        **supplied_pair,
    )

    assert result == {"ok": False, "error_code": "PREVIEW_CLAIM_FAILED"}
    assert not Path(store.claims_root).exists()


@pytest.mark.parametrize(
    "supplied_pair",
    [
        {
            "executor_authority_id": _AuthorityEqualitySpoof(AUTHORITY_ID),
            "admission_sha256": _AuthorityEqualitySpoof(ADMISSION_SHA256),
        },
        {
            "executor_authority_id": _AuthorityStringSubclass(AUTHORITY_ID),
            "admission_sha256": _AuthorityStringSubclass(ADMISSION_SHA256),
        },
        {
            "executor_authority_id": AUTHORITY_ID.upper(),
            "admission_sha256": ADMISSION_SHA256,
        },
        {
            "executor_authority_id": AUTHORITY_ID,
            "admission_sha256": f" {ADMISSION_SHA256}",
        },
    ],
)
def test_authority_bound_claim_rejects_noncanonical_runtime_representations_before_mutation(
    tmp_path: Path,
    supplied_pair: dict[str, object],
) -> None:
    store = _claim_store(tmp_path)

    result = store.acquire_claim(
        preview_id="preview-noncanonical-authority",
        artifact=_authority_bound_claim_artifact(),
        provider="codex",
        execution_mode="run",
        **supplied_pair,
    )

    assert result == {"ok": False, "error_code": "PREVIEW_CLAIM_FAILED"}
    assert not Path(store.claims_root).exists()


@pytest.mark.parametrize(
    "malformed_binding",
    [
        None,
        {},
        {"executor_authority_id": AUTHORITY_ID},
        {"admission_sha256": ADMISSION_SHA256},
        {
            "executor_authority_id": "not-an-authority",
            "admission_sha256": ADMISSION_SHA256,
        },
        {
            "executor_authority_id": AUTHORITY_ID,
            "admission_sha256": "not-a-digest",
        },
        {
            "executor_authority_id": _AuthorityStringSubclass(AUTHORITY_ID),
            "admission_sha256": ADMISSION_SHA256,
        },
        {
            "executor_authority_id": AUTHORITY_ID.upper(),
            "admission_sha256": ADMISSION_SHA256,
        },
        {
            "executor_authority_id": AUTHORITY_ID,
            "admission_sha256": f"{ADMISSION_SHA256} ",
        },
    ],
)
def test_malformed_artifact_authority_binding_fails_before_claim_store_creation(
    tmp_path: Path,
    malformed_binding: object,
) -> None:
    store = _claim_store(tmp_path)
    artifact = _authority_bound_claim_artifact()
    artifact["fresh_execution_authority"] = malformed_binding

    result = store.acquire_claim(
        preview_id="preview-malformed-authority",
        artifact=artifact,
        provider="codex",
        execution_mode="run",
        executor_authority_id=AUTHORITY_ID,
        admission_sha256=ADMISSION_SHA256,
    )

    assert result == {"ok": False, "error_code": "PREVIEW_CLAIM_FAILED"}
    assert not Path(store.claims_root).exists()


def test_authority_bound_claim_accepts_and_persists_only_the_exact_pair(
    tmp_path: Path,
) -> None:
    store = _claim_store(tmp_path)

    result = store.acquire_claim(
        preview_id="preview-exact-authority",
        artifact=_authority_bound_claim_artifact(),
        provider="codex",
        execution_mode="run",
        executor_authority_id=AUTHORITY_ID,
        admission_sha256=ADMISSION_SHA256,
    )

    assert result["ok"] is True
    persisted = store.read_claim("preview-exact-authority")
    assert persisted is not None
    assert persisted["executor_authority_id"] == AUTHORITY_ID
    assert persisted["admission_sha256"] == ADMISSION_SHA256

    invalid_replacement = {
        **persisted,
        "executor_authority_id": _AuthorityStringSubclass(AUTHORITY_ID),
    }
    with pytest.raises(ValueError, match="CLAIM_AUTHORITY_CONTRACT_INVALID"):
        store.write_claim("preview-exact-authority", invalid_replacement)
    assert store.read_claim("preview-exact-authority") == persisted


def test_unbound_claim_without_authority_pair_keeps_legacy_semantics(
    tmp_path: Path,
) -> None:
    store = _claim_store(tmp_path)

    result = store.acquire_claim(
        preview_id="preview-unbound",
        artifact={
            "artifact_kind": "run_once",
            "current_version": "v1",
            "current_head": "c" * 40,
            "created_at": "2026-08-26T00:00:00+00:00",
            "expires_at": "2026-08-26T00:15:00+00:00",
        },
        provider="codex",
        execution_mode="run",
    )

    assert result["ok"] is True
    persisted = store.read_claim("preview-unbound")
    assert persisted is not None
    assert "executor_authority_id" not in persisted
    assert "admission_sha256" not in persisted


def test_unbound_claim_with_canonical_supplied_pair_preserves_existing_contract(
    tmp_path: Path,
) -> None:
    store = _claim_store(tmp_path)

    result = store.acquire_claim(
        preview_id="preview-unbound-with-pair",
        artifact={
            "artifact_kind": "run_once",
            "current_version": "v1",
            "current_head": "c" * 40,
            "created_at": "2026-08-26T00:00:00+00:00",
            "expires_at": "2026-08-26T00:15:00+00:00",
        },
        provider="codex",
        execution_mode="run",
        executor_authority_id=AUTHORITY_ID,
        admission_sha256=ADMISSION_SHA256,
    )

    assert result["ok"] is True
    persisted = store.read_claim("preview-unbound-with-pair")
    assert persisted is not None
    assert persisted["executor_authority_id"] == AUTHORITY_ID
    assert persisted["admission_sha256"] == ADMISSION_SHA256


@pytest.mark.parametrize("surface", ["file", "directory"])
def test_claim_creation_requires_file_and_directory_fsync(
    tmp_path: Path, monkeypatch, surface: str
) -> None:
    import runner.executor_run_claims as claim_module

    store = _claim_store(tmp_path)
    Path(store.claims_root).mkdir(parents=True)
    _fail_selected_fsync(monkeypatch, claim_module, surface)
    result = store.acquire_claim(
        preview_id="preview-1",
        artifact={"artifact_kind": "run_once", "current_version": "v1"},
        provider="codex",
        execution_mode="run",
    )
    assert result == {"ok": False, "error_code": "PREVIEW_CLAIM_FAILED"}


@pytest.mark.parametrize("surface", ["file", "directory"])
def test_claim_replacement_requires_file_and_directory_fsync(
    tmp_path: Path, monkeypatch, surface: str
) -> None:
    import runner.executor_run_claims as claim_module

    context = _context()
    _write_durable_binding_and_claim(tmp_path, context)
    store = _claim_store(tmp_path)
    claim = store.read_claim("preview-1")
    assert claim is not None
    claim["last_heartbeat_at"] = "2026-08-25T00:00:01+00:00"
    _fail_selected_fsync(monkeypatch, claim_module, surface)
    with pytest.raises(OSError, match=f"injected {surface} fsync failure"):
        store.write_claim("preview-1", claim)


@pytest.mark.parametrize("surface", ["file", "directory"])
def test_report_creation_requires_file_and_directory_fsync(
    tmp_path: Path, monkeypatch, surface: str
) -> None:
    import runner.executor_run_reports as report_module

    store = ExecutorRunReportStore(str(tmp_path))
    _fail_selected_fsync(monkeypatch, report_module, surface)
    result = store.record_report(
        version="v1",
        provider="codex",
        execution_mode="run",
        status="failed",
    )
    assert result["ok"] is False
    assert result["error_code"] == "REPORT_WRITE_FAILED"


@pytest.mark.parametrize("surface", ["file", "directory"])
def test_report_pointer_replacement_requires_file_and_directory_fsync(
    tmp_path: Path, monkeypatch, surface: str
) -> None:
    import runner.executor_run_reports as report_module

    store = ExecutorRunReportStore(str(tmp_path))
    recorded = store.record_report(
        version="v1",
        provider="codex",
        execution_mode="run",
        status="failed",
    )
    assert recorded["ok"] is True
    _fail_selected_fsync(monkeypatch, report_module, surface)
    with pytest.raises(OSError, match=f"injected {surface} fsync failure"):
        store._write_latest_pointer(
            store.reports_root,
            "v1",
            str(recorded["report_id"]),
            str(recorded["json_file"]),
            str(recorded["markdown_file"]),
        )


@pytest.mark.parametrize("surface", ["file", "directory"])
def test_session_replace_requires_file_and_directory_fsync(
    tmp_path: Path, monkeypatch, surface: str
) -> None:
    import runner.executor_session as session_module

    store = ExecutorSessionStore(str(tmp_path))
    _fail_selected_fsync(monkeypatch, session_module, surface)
    with pytest.raises(OSError, match=f"injected {surface} fsync failure"):
        store.record_execution(
            provider="codex",
            version="v1",
            execution_mode="run",
            attempt=1,
        )


@pytest.mark.parametrize("surface", ["claim", "report", "session"])
def test_durable_writers_require_successful_readback(
    tmp_path: Path, monkeypatch, surface: str
) -> None:
    if surface == "claim":
        context = _context()
        _write_durable_binding_and_claim(tmp_path, context)
        store = _claim_store(tmp_path)
        claim = store.read_claim("preview-1")
        assert claim is not None
        monkeypatch.setattr(
            store,
            "_read_claim_verification",
            lambda *args, **kwargs: {
                "ok": False,
                "error_code": "INJECTED_READBACK_FAILURE",
            },
        )
        with pytest.raises(OSError, match="readback verification"):
            store.write_claim("preview-1", claim)
    elif surface == "report":
        import runner.executor_run_reports as report_module

        monkeypatch.setattr(
            report_module,
            "read_trusted_owned_regular_file",
            lambda *args, **kwargs: {"raw": b"{}\n"},
        )
        result = ExecutorRunReportStore(str(tmp_path)).record_report(
            version="v1",
            provider="codex",
            execution_mode="run",
            status="failed",
        )
        assert result["ok"] is False
        assert result["error_code"] == "REPORT_WRITE_FAILED"
    else:
        import runner.executor_session as session_module

        monkeypatch.setattr(
            session_module,
            "read_trusted_owned_regular_file",
            lambda *args, **kwargs: {"raw": b"{}\n"},
        )
        with pytest.raises(OSError, match="readback verification"):
            ExecutorSessionStore(str(tmp_path)).record_execution(
                provider="codex",
                version="v1",
                execution_mode="run",
                attempt=1,
            )


@pytest.mark.parametrize("surface", ["report", "session"])
@pytest.mark.parametrize("truncate_regrow", [False, True])
def test_report_and_session_production_reads_reject_synchronized_same_inode_mutation(
    tmp_path: Path,
    monkeypatch,
    surface: str,
    truncate_regrow: bool,
) -> None:
    context = _context()
    if surface == "report":
        store = ExecutorRunReportStore(str(tmp_path))
        recorded = store.record_report(
            version="v1",
            provider="codex",
            execution_mode="run",
            status="completed",
            execution_lineage=dict(context),
            work_item_id=context["work_item_id"],
            task_version=context["task_version"],
            attempt_id=context["attempt_id"],
            artifact_refs=context["artifact_refs"],
        )
        assert recorded["ok"] is True
        target = Path(str(recorded["json_file"]))
        read = lambda: store.read_durable_contract(
            report_id=str(recorded["report_id"]),
            expected_run_id="run-1",
        )
    else:
        store = ExecutorSessionStore(str(tmp_path))
        store.record_execution(
            provider="codex",
            version="v1",
            execution_mode="run",
            attempt=1,
            work_item_id=context["work_item_id"],
            task_version=context["task_version"],
            attempt_id=context["attempt_id"],
            artifact_refs=context["artifact_refs"],
            executor_authority_id=AUTHORITY_ID,
            admission_sha256=ADMISSION_SHA256,
        )
        assert store.bind_private_lineage(context)["ok"] is True
        target = Path(store.manifest_file)
        read = lambda: store.read_durable_contract(expected_run_id="run-1")
    identity_before = (target.stat().st_dev, target.stat().st_ino)
    worker = _install_synchronized_same_inode_mutation(
        monkeypatch,
        target,
        truncate_regrow=truncate_regrow,
    )

    result = read()
    worker.join(timeout=5)

    assert worker.is_alive() is False
    assert (target.stat().st_dev, target.stat().st_ino) == identity_before
    assert result["ok"] is False


def test_report_and_session_contracts_carry_complete_distinct_durable_evidence(
    tmp_path: Path,
) -> None:
    _, _, report_id, _ = _prepare_post_verifier_surfaces(tmp_path)
    contracts = [
        ExecutorRunReportStore(str(tmp_path)).read_durable_contract(
            report_id=report_id,
            expected_run_id="run-1",
        ),
        ExecutorSessionStore(str(tmp_path)).read_durable_contract(
            expected_run_id="run-1"
        ),
    ]
    metadata_fields = {
        "device", "inode", "mode", "uid", "gid", "nlink", "size",
        "mtime_ns", "ctime_ns",
    }
    for result in contracts:
        assert result["ok"] is True, result
        contract = result["durable_contract"]
        assert set(contract) == {
            "identity", "metadata", "size", "raw_sha256",
            "content_sha256", "contract_sha256",
        }
        assert set(contract["metadata"]) == metadata_fields
        assert contract["identity"] == {
            "device": contract["metadata"]["device"],
            "inode": contract["metadata"]["inode"],
        }
        assert contract["size"] == contract["metadata"]["size"]
        assert contract["raw_sha256"] != contract["content_sha256"]


def test_post_persistence_verifier_reads_real_event_report_and_session(
    tmp_path: Path,
) -> None:
    context, service, report_id, pre_provider = _prepare_post_verifier_surfaces(
        tmp_path
    )
    verification = service._verify_post_persistence_lineage(
        run_id="run-1",
        report_id=report_id,
        expected_context=context,
        pre_provider_snapshot=pre_provider,
    )

    assert verification["ok"] is True
    assert set(verification) == {"ok", "error_code", "safe_digest"}
    assert AUTHORITY_ID not in json.dumps(verification)
    assert ADMISSION_SHA256 not in json.dumps(verification)


def test_claim_reader_requires_exact_v1_contract_and_returns_safe_evidence(
    tmp_path: Path,
) -> None:
    context = _context()
    _, claim_path = _write_durable_binding_and_claim(tmp_path, context)
    store = _claim_store(tmp_path)

    first = store._read_claim_verification("preview-1", expected_run_id="run-1")
    second = store._read_claim_verification("preview-1", expected_run_id="run-1")

    assert first["ok"] is True, first
    assert second["ok"] is True, second
    assert first["durable_contract"] == second["durable_contract"]
    assert set(first["durable_contract"]) == {
        "identity",
        "metadata",
        "size",
        "raw_sha256",
        "content_sha256",
    }
    assert AUTHORITY_ID not in json.dumps(first["durable_contract"])
    assert ADMISSION_SHA256 not in json.dumps(first["durable_contract"])
    payload = json.loads(claim_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "executor_run_claim.v1"
    assert "_colameta_durable_identity" not in payload
    assert "_colameta_durable_identity" not in store.read_claim("preview-1")

    payload["unexpected"] = True
    claim_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    claim_path.chmod(0o600)
    rejected = store._read_claim_verification("preview-1")
    assert rejected == {"ok": False, "error_code": "CLAIM_CONTRACT_FIELDS_INVALID"}


def test_claim_verified_read_uses_shared_lock_and_rejects_same_inode_race(
    tmp_path: Path, monkeypatch
) -> None:
    context = _context()
    _, claim_path = _write_durable_binding_and_claim(tmp_path, context)
    store = _claim_store(tmp_path)
    original_read = os.read
    original_lock = store._bounded_flock
    original_raw = claim_path.read_bytes()
    target_identity = (claim_path.stat().st_dev, claim_path.stat().st_ino)
    lock_operations: list[int] = []
    mutated = False

    def observed_lock(fd: int, operation: int) -> None:
        lock_operations.append(operation)
        original_lock(fd, operation)

    def mutate_at_first_eof(fd: int, size: int) -> bytes:
        nonlocal mutated
        data = original_read(fd, size)
        metadata = os.fstat(fd)
        if (
            not mutated
            and not data
            and size == 1
            and (metadata.st_dev, metadata.st_ino) == target_identity
        ):
            replacement = original_raw.replace(b'"codex"', b'"c0dex"', 1)
            assert len(replacement) == len(original_raw)
            writer = os.open(claim_path, os.O_WRONLY | os.O_NOFOLLOW)
            try:
                os.pwrite(writer, replacement, 0)
                os.fsync(writer)
            finally:
                os.close(writer)
            mutated = True
        return data

    monkeypatch.setattr(store, "_bounded_flock", observed_lock)
    monkeypatch.setattr(os, "read", mutate_at_first_eof)

    result = store._read_claim_verification(
        "preview-1", expected_run_id="run-1"
    )

    assert mutated is True
    assert lock_operations == [fcntl.LOCK_SH]
    assert result == {"ok": False, "error_code": "CLAIM_READ_UNSTABLE"}


@pytest.mark.parametrize(
    "mutation", ["missing_schema", "wrong_schema", "run_mismatch", "truncated"]
)
def test_claim_reader_rejects_schema_and_expected_run_mismatch(
    tmp_path: Path, mutation: str
) -> None:
    context = _context()
    _, claim_path = _write_durable_binding_and_claim(tmp_path, context)
    payload = json.loads(claim_path.read_text(encoding="utf-8"))
    if mutation == "missing_schema":
        payload.pop("schema_version")
    elif mutation == "wrong_schema":
        payload["schema_version"] = "executor_run_claim.v0"
    claim_path.write_text(
        '{"schema_version":"executor_run_claim.v1"'
        if mutation == "truncated"
        else json.dumps(payload) + "\n",
        encoding="utf-8",
    )
    claim_path.chmod(0o600)

    expected_run_id = "other-run" if mutation == "run_mismatch" else None
    result = _claim_store(tmp_path)._read_claim_verification(
        "preview-1", expected_run_id=expected_run_id
    )

    assert result["ok"] is False
    assert result["error_code"] in {
        "CLAIM_CONTRACT_INCOMPLETE",
        "CLAIM_SCHEMA_VERSION_INVALID",
        "CLAIM_RUN_ID_MISMATCH",
        "CLAIM_JSON_INVALID",
    }


@pytest.mark.parametrize("replacement_type", ["symlink", "fifo", "hardlink", "mode"])
def test_claim_reader_rejects_symlink_and_fifo(
    tmp_path: Path, replacement_type: str
) -> None:
    context = _context()
    _, claim_path = _write_durable_binding_and_claim(tmp_path, context)
    raw = claim_path.read_bytes()
    if replacement_type == "symlink":
        claim_path.unlink()
        outside = tmp_path / "outside-claim.json"
        outside.write_bytes(raw)
        outside.chmod(0o600)
        claim_path.symlink_to(outside)
    elif replacement_type == "fifo":
        claim_path.unlink()
        os.mkfifo(claim_path, 0o600)
    elif replacement_type == "hardlink":
        outside = tmp_path / "outside-claim.json"
        outside.write_bytes(raw)
        outside.chmod(0o600)
        claim_path.unlink()
        os.link(outside, claim_path)
    else:
        claim_path.chmod(0o644)

    result = _claim_store(tmp_path)._read_claim_verification("preview-1")

    assert result["ok"] is False
    assert result["error_code"] in {"CLAIM_FILE_UNSAFE", "CLAIM_READ_UNSTABLE"}


def test_claim_reader_rejects_unsafe_ancestor_mode(tmp_path: Path) -> None:
    context = _context()
    _, claim_path = _write_durable_binding_and_claim(tmp_path, context)
    claim_path.parent.chmod(0o777)

    result = _claim_store(tmp_path)._read_claim_verification("preview-1")

    assert result == {"ok": False, "error_code": "CLAIM_ANCESTOR_UNSAFE"}


def test_claim_replacement_changes_inode_and_raw_digest(
    tmp_path: Path,
) -> None:
    context = _context()
    _write_durable_binding_and_claim(tmp_path, context)
    store = _claim_store(tmp_path)
    first = store._read_claim_verification("preview-1", expected_run_id="run-1")

    assert store.refresh_heartbeat(preview_id="preview-1", run_id="run-1") is True
    second = store._read_claim_verification("preview-1", expected_run_id="run-1")

    assert first["ok"] is True and second["ok"] is True
    assert first["durable_contract"]["identity"] != second["durable_contract"]["identity"]
    assert first["durable_contract"]["raw_sha256"] != second["durable_contract"]["raw_sha256"]


@pytest.mark.parametrize("surface", ["claim", "binding"])
def test_post_verifier_rejects_same_content_inode_replacement(
    tmp_path: Path, surface: str
) -> None:
    context, service, report_id, pre_provider = _prepare_post_verifier_surfaces(
        tmp_path
    )
    binding_path, claim_path = _durable_binding_and_claim_paths(tmp_path, context)
    target = claim_path if surface == "claim" else binding_path
    _atomic_replace_json(target, json.loads(target.read_text(encoding="utf-8")))

    verification = service._verify_post_persistence_lineage(
        run_id="run-1",
        report_id=report_id,
        expected_context=context,
        pre_provider_snapshot=pre_provider,
    )

    assert verification["ok"] is False
    assert verification["error_code"] == f"{surface.upper()}_LIFECYCLE_DRIFT"


@pytest.mark.parametrize("surface", ["claim", "binding"])
def test_post_verifier_rejects_safe_ancestor_replacement(
    tmp_path: Path, surface: str
) -> None:
    context, service, report_id, pre_provider = _prepare_post_verifier_surfaces(
        tmp_path
    )
    binding_path, claim_path = _durable_binding_and_claim_paths(tmp_path, context)
    target = claim_path if surface == "claim" else binding_path
    ancestor = target.parent
    moved = tmp_path / f"moved-{surface}-ancestor"
    os.rename(ancestor, moved)
    ancestor.mkdir(mode=0o700)
    replacement = ancestor / target.name
    replacement.write_bytes((moved / target.name).read_bytes())
    replacement.chmod(0o600)

    verification = service._verify_post_persistence_lineage(
        run_id="run-1",
        report_id=report_id,
        expected_context=context,
        pre_provider_snapshot=pre_provider,
    )

    assert verification["ok"] is False
    assert verification["error_code"] == f"{surface.upper()}_LIFECYCLE_DRIFT"


@pytest.mark.parametrize("surface", ["claim", "binding"])
def test_post_persistence_verifier_rejects_same_lineage_contract_tamper(
    tmp_path: Path, surface: str
) -> None:
    context, service, report_id, pre_provider = _prepare_post_verifier_surfaces(
        tmp_path
    )
    binding_path, claim_path = _durable_binding_and_claim_paths(tmp_path, context)
    target = claim_path if surface == "claim" else binding_path
    replacement = json.loads(target.read_text(encoding="utf-8"))
    replacement["provider"] = "same-lineage-replacement"
    target.write_text(json.dumps(replacement) + "\n", encoding="utf-8")
    target.chmod(0o600)

    verification = service._verify_post_persistence_lineage(
        run_id="run-1",
        report_id=report_id,
        expected_context=context,
        pre_provider_snapshot=pre_provider,
    )

    assert verification["ok"] is False
    assert verification["error_code"] == (
        "BINDING_PROVIDER_INVALID"
        if surface == "binding"
        else "CLAIM_LIFECYCLE_DRIFT"
    )


@pytest.mark.parametrize("surface", ["claim", "binding"])
def test_post_verifier_rejects_raw_only_durable_rewrite(
    tmp_path: Path, surface: str
) -> None:
    context, service, report_id, pre_provider = _prepare_post_verifier_surfaces(
        tmp_path
    )
    binding_path, claim_path = _durable_binding_and_claim_paths(tmp_path, context)
    target = claim_path if surface == "claim" else binding_path
    payload = json.loads(target.read_text(encoding="utf-8"))
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=4) + "\n",
        encoding="utf-8",
    )
    target.chmod(0o600)

    verification = service._verify_post_persistence_lineage(
        run_id="run-1",
        report_id=report_id,
        expected_context=context,
        pre_provider_snapshot=pre_provider,
    )

    assert verification["ok"] is False
    assert verification["error_code"] == f"{surface.upper()}_LIFECYCLE_DRIFT"


def test_manager_finalizes_claim_after_terminal_event_before_final_proof(
    tmp_path: Path,
) -> None:
    from runner.mcp_executor_workflow import MCPExecutorWorkflowManager

    context, service, report_id, pre_provider = _prepare_post_verifier_surfaces(
        tmp_path,
        finalize_lifecycle=False,
    )
    claims = _claim_store(tmp_path)
    manager = object.__new__(MCPExecutorWorkflowManager)
    manager._claims = claims
    order: list[str] = []

    def refresh_claim(**kwargs):
        return claims.refresh_heartbeat(
            preview_id=kwargs["preview_id"],
            run_id=kwargs["run_id"],
            error_state=kwargs.get("error_state"),
        )

    def finalize_claim(**kwargs):
        claims.finalize_claim(**kwargs)
        order.append("claim_finalized")

    manager._refresh_claim_heartbeat = refresh_claim
    manager._delete_preview_artifact = lambda preview_id: order.append(
        "preview_deleted"
    )
    manager._finalize_preview_claim = finalize_claim

    binding_path, claim_path = _durable_binding_and_claim_paths(tmp_path, context)
    event_path = Path(service._event_store.run_dir("run-1")) / "events.jsonl"
    report_path = next(tmp_path.rglob(f"{report_id}.json"))
    session_path = Path(ExecutorSessionStore(str(tmp_path)).manifest_file)
    durable_paths = (
        binding_path,
        claim_path,
        event_path,
        report_path,
        session_path,
    )
    proof_snapshot: dict[str, tuple[int, int, str]] = {}

    def stable_snapshot() -> dict[str, tuple[int, int, str]]:
        return {
            str(path): (
                int(path.stat().st_dev),
                int(path.stat().st_ino),
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )
            for path in durable_paths
        }

    def service_run_once(**kwargs):
        service._event_store.append(
            "run-1",
            "run_completed",
            {"report_id": report_id},
            context,
        )
        order.append("terminal_event")
        verification = service._finalize_and_verify_fresh_lifecycle(
            run_id="run-1",
            report_id=report_id,
            expected_context=context,
            pre_provider_snapshot=pre_provider,
            finalizer=kwargs["_lifecycle_finalizer"],
            final_status="COMPLETED",
        )
        assert verification["ok"] is True, verification
        assert AUTHORITY_ID not in json.dumps(verification)
        assert ADMISSION_SHA256 not in json.dumps(verification)
        proof_snapshot.update(stable_snapshot())
        order.append("proof_attached")
        return {
            "ok": True,
            "latest_report_id": report_id,
            "fresh_authority_proof": {
                "verified": True,
                "safe_digest": verification["safe_digest"],
            },
        }

    manager._run_once_background_worker(
        provider="codex",
        execution_mode="run",
        include_diff_summary=False,
        include_report_markdown=False,
        max_report_chars=100,
        reason="ordering regression",
        run_id="run-1",
        preview_id="preview-1",
        preview_claimed_at="2026-08-25T00:00:00+00:00",
        preview_claim_status="RUNNING",
        run_once_callable=service_run_once,
        executor_authority_id=AUTHORITY_ID,
        admission_sha256=ADMISSION_SHA256,
        claimed_work_target={
            key: context[key]
            for key in ("work_item_id", "task_version", "attempt_id", "artifact_refs")
        },
    )

    assert order == [
        "terminal_event",
        "preview_deleted",
        "claim_finalized",
        "proof_attached",
    ]
    assert stable_snapshot() == proof_snapshot
    final_claim = claims.read_claim("preview-1")
    assert final_claim is not None
    assert final_claim["status"] == "COMPLETED"
    assert final_claim["report_id"] == report_id


@pytest.mark.parametrize("surface", ["report", "session"])
def test_post_verifier_rejects_real_second_read_replacement(
    tmp_path: Path, monkeypatch, surface: str
) -> None:
    context, service, report_id, pre_provider = _prepare_post_verifier_surfaces(
        tmp_path
    )
    if surface == "report":
        import runner.executor_run_reports as surface_module

        target = next(tmp_path.rglob(f"{report_id}.json"))
    else:
        import runner.executor_session as surface_module

        target = Path(ExecutorSessionStore(str(tmp_path)).manifest_file)
    original_reader = surface_module.read_trusted_owned_regular_file
    reads = 0

    def replace_after_real_read(path: str, **kwargs):
        nonlocal reads
        snapshot = original_reader(path, **kwargs)
        if Path(path) == target:
            reads += 1
            if reads == 1:
                replacement = json.loads(snapshot["raw"].decode("utf-8"))
                replacement["status" if surface == "report" else "source"] = (
                    "same-lineage-replacement"
                )
                _atomic_replace_json(target, replacement)
        return snapshot

    monkeypatch.setattr(
        surface_module,
        "read_trusted_owned_regular_file",
        replace_after_real_read,
    )
    verification = service._verify_post_persistence_lineage(
        run_id="run-1",
        report_id=report_id,
        expected_context=context,
        pre_provider_snapshot=pre_provider,
    )

    assert verification["ok"] is False
    assert verification["error_code"] == f"{surface.upper()}_SECOND_READ_DRIFT"


@pytest.mark.parametrize("surface", ["report", "session"])
def test_final_verifier_rejects_identical_byte_same_inode_rewrite_between_rounds(
    tmp_path: Path, monkeypatch, surface: str
) -> None:
    context, service, report_id, pre_provider = _prepare_post_verifier_surfaces(
        tmp_path
    )
    if surface == "report":
        import runner.executor_run_reports as surface_module

        target = next(tmp_path.rglob(f"{report_id}.json"))
    else:
        import runner.executor_session as surface_module

        target = Path(ExecutorSessionStore(str(tmp_path)).manifest_file)
    identity = (target.stat().st_dev, target.stat().st_ino)
    original_reader = surface_module.read_trusted_owned_regular_file
    reads = 0

    def rewrite_after_first_read(path: str, **kwargs):
        nonlocal reads
        snapshot = original_reader(path, **kwargs)
        if Path(path) == target:
            reads += 1
            if reads == 1:
                before = target.stat()
                writer = os.open(target, os.O_WRONLY | os.O_NOFOLLOW)
                try:
                    os.pwrite(writer, snapshot["raw"], 0)
                    os.ftruncate(writer, len(snapshot["raw"]))
                    os.fsync(writer)
                finally:
                    os.close(writer)
                os.utime(
                    target,
                    ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000),
                )
        return snapshot

    monkeypatch.setattr(
        surface_module,
        "read_trusted_owned_regular_file",
        rewrite_after_first_read,
    )
    verification = service._verify_post_persistence_lineage(
        run_id="run-1",
        report_id=report_id,
        expected_context=context,
        pre_provider_snapshot=pre_provider,
    )

    assert (target.stat().st_dev, target.stat().st_ino) == identity
    assert verification["ok"] is False
    assert verification["error_code"] == f"{surface.upper()}_SECOND_READ_DRIFT"


def test_post_verifier_rejects_real_event_second_read_replacement(
    tmp_path: Path, monkeypatch
) -> None:
    context, service, report_id, pre_provider = _prepare_post_verifier_surfaces(
        tmp_path
    )
    event_path = Path(service._event_store.run_dir("run-1")) / "events.jsonl"
    original_capture = service._event_store.capture_durable_contract
    reads = 0

    def replace_after_real_read(
        run_id: str, *, expected_prefix=None, expected_lineage=None
    ):
        nonlocal reads
        snapshot = original_capture(
            run_id,
            expected_prefix=expected_prefix,
            expected_lineage=expected_lineage,
        )
        reads += 1
        if reads == 1:
            replacement = event_path.with_name("events.replacement")
            replacement.write_bytes(event_path.read_bytes())
            replacement.chmod(0o600)
            os.replace(replacement, event_path)
        return snapshot

    monkeypatch.setattr(
        service._event_store,
        "capture_durable_contract",
        replace_after_real_read,
    )
    verification = service._verify_post_persistence_lineage(
        run_id="run-1",
        report_id=report_id,
        expected_context=context,
        pre_provider_snapshot=pre_provider,
    )

    assert verification["ok"] is False
    assert verification["error_code"] == "EVENT_DURABLE_IDENTITY_DRIFT"


def test_final_verifier_rejects_identical_event_rewrite_on_same_inode(
    tmp_path: Path, monkeypatch
) -> None:
    context, service, report_id, pre_provider = _prepare_post_verifier_surfaces(
        tmp_path
    )
    event_path = Path(service._event_store.run_dir("run-1")) / "events.jsonl"
    identity = (event_path.stat().st_dev, event_path.stat().st_ino)
    original_capture = service._event_store.capture_durable_contract
    reads = 0

    def rewrite_after_first_capture(
        run_id: str, *, expected_prefix=None, expected_lineage=None
    ):
        nonlocal reads
        snapshot = original_capture(
            run_id,
            expected_prefix=expected_prefix,
            expected_lineage=expected_lineage,
        )
        reads += 1
        if reads == 1:
            before = event_path.stat()
            raw = event_path.read_bytes()
            writer = os.open(event_path, os.O_WRONLY | os.O_NOFOLLOW)
            try:
                os.pwrite(writer, raw, 0)
                os.ftruncate(writer, len(raw))
                os.fsync(writer)
            finally:
                os.close(writer)
            os.utime(
                event_path,
                ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000),
            )
        return snapshot

    monkeypatch.setattr(
        service._event_store,
        "capture_durable_contract",
        rewrite_after_first_capture,
    )
    verification = service._verify_post_persistence_lineage(
        run_id="run-1",
        report_id=report_id,
        expected_context=context,
        pre_provider_snapshot=pre_provider,
    )

    assert (event_path.stat().st_dev, event_path.stat().st_ino) == identity
    assert verification["ok"] is False
    assert verification["error_code"] == "EVENT_SECOND_READ_DRIFT"


def test_post_verifier_rejects_event_history_tamper_with_same_inode(
    tmp_path: Path,
) -> None:
    context, service, report_id, pre_provider = _prepare_post_verifier_surfaces(
        tmp_path
    )
    event_path = Path(service._event_store.run_dir("run-1")) / "events.jsonl"
    records = [json.loads(line) for line in event_path.read_text(encoding="utf-8").splitlines()]
    records[0]["message"] = "same-lineage-history-tamper"
    event_path.write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )
    event_path.chmod(0o600)

    verification = service._verify_post_persistence_lineage(
        run_id="run-1",
        report_id=report_id,
        expected_context=context,
        pre_provider_snapshot=pre_provider,
    )

    assert verification["ok"] is False
    assert verification["error_code"] == "EVENT_HISTORY_TAMPERED"


@pytest.mark.parametrize(
    ("missing_field", "error_code"),
    [
        ("schema_version", "EVENT_PRIVATE_LINEAGE_INVALID"),
        ("run_id", "EVENT_RUN_ID_MISSING"),
    ],
)
def test_private_event_missing_schema_or_run_id_fails_closed(
    tmp_path: Path, missing_field: str, error_code: str
) -> None:
    store = ExecutorEventStore(str(tmp_path))
    store.append("run-1", "executor_finished", {}, _context())
    event_path = Path(store.run_dir("run-1")) / "events.jsonl"
    record = json.loads(event_path.read_text(encoding="utf-8"))
    record.pop(missing_field)
    event_path.write_text(json.dumps(record) + "\n", encoding="utf-8")
    event_path.chmod(0o600)

    result = store.capture_durable_contract("run-1", expected_lineage=_context())

    assert result["ok"] is False
    assert result["error_code"] == error_code


@pytest.mark.parametrize("missing_field", ["schema_version", "run_id"])
def test_claim_contract_missing_schema_or_run_id_is_never_synthesized(
    tmp_path: Path, missing_field: str
) -> None:
    service = ExecutorRunOnceService(str(tmp_path))
    claim = _surface_context(_context())
    claim.pop(missing_field)

    result = service._capture_parsed_surface(
        name="CLAIM",
        surface=claim,
        run_id="run-1",
    )

    assert result["ok"] is False
    assert result["error_code"] == f"CLAIM_{missing_field.removesuffix('_version').upper()}_MISSING"


@pytest.mark.parametrize("surface", ["report", "session"])
@pytest.mark.parametrize("missing_field", ["schema_version", "run_id"])
def test_report_and_session_missing_schema_or_run_id_fail_closed(
    tmp_path: Path, surface: str, missing_field: str
) -> None:
    _, _, report_id, _ = _prepare_post_verifier_surfaces(tmp_path)
    if surface == "report":
        store = ExecutorRunReportStore(str(tmp_path))
        target = next(tmp_path.rglob(f"{report_id}.json"))
        payload = json.loads(target.read_text(encoding="utf-8"))
        if missing_field == "run_id":
            payload["execution_lineage"].pop("run_id")
        else:
            payload.pop("schema_version")
        target.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        target.chmod(0o600)
        result = store.read_durable_contract(
            report_id=report_id,
            expected_run_id="run-1",
        )
    else:
        store = ExecutorSessionStore(str(tmp_path))
        target = Path(store.manifest_file)
        payload = json.loads(target.read_text(encoding="utf-8"))
        payload.pop(missing_field)
        target.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        target.chmod(0o600)
        result = store.read_durable_contract(expected_run_id="run-1")

    assert result["ok"] is False
    assert missing_field.removesuffix("_version").upper() in result["error_code"]


@pytest.mark.parametrize(
    ("surface", "mutation"),
    [
        ("report", "top_extra"),
        ("report", "top_type"),
        ("report", "summary_extra"),
        ("report", "summary_type"),
        ("report", "lineage_extra"),
        ("report", "lineage_type"),
        ("session", "top_extra"),
        ("session", "top_type"),
    ],
)
def test_report_and_session_durable_contracts_reject_extras_and_type_substitution(
    tmp_path: Path, surface: str, mutation: str
) -> None:
    _, _, report_id, _ = _prepare_post_verifier_surfaces(tmp_path)
    if surface == "report":
        store = ExecutorRunReportStore(str(tmp_path))
        target = next(tmp_path.rglob(f"{report_id}.json"))
        payload = json.loads(target.read_text(encoding="utf-8"))
        if mutation == "top_extra":
            payload["unknown"] = True
        elif mutation == "top_type":
            payload["truncated"] = 0
        elif mutation == "summary_extra":
            payload["summary"]["unknown"] = True
        elif mutation == "summary_type":
            payload["summary"]["validation_inconsistent"] = 0
        elif mutation == "lineage_extra":
            payload["execution_lineage"]["unknown"] = True
        else:
            payload["execution_lineage"]["attempted_resume"] = 0
        target.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        target.chmod(0o600)
        result = store.read_durable_contract(
            report_id=report_id,
            expected_run_id="run-1",
        )
    else:
        store = ExecutorSessionStore(str(tmp_path))
        target = Path(store.manifest_file)
        payload = json.loads(target.read_text(encoding="utf-8"))
        if mutation == "top_extra":
            payload["unknown"] = True
        else:
            payload["active"] = 1
        target.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        target.chmod(0o600)
        result = store.read_durable_contract(expected_run_id="run-1")

    assert result["ok"] is False


def test_report_rejects_unknown_lineage_before_persistence(tmp_path: Path) -> None:
    store = ExecutorRunReportStore(str(tmp_path))
    result = store.record_report(
        version="v1",
        provider="codex",
        execution_mode="run",
        status="failed",
        execution_lineage={"attacker_controlled": "unknown"},
    )
    assert result["ok"] is False
    assert result["error_code"] == "REPORT_LINEAGE_INVALID"
    assert not list(Path(store.reports_root).rglob("*.json"))


def test_session_bind_rejects_unknown_manifest_field_before_replace(
    tmp_path: Path,
) -> None:
    store = ExecutorSessionStore(str(tmp_path))
    store.record_execution(
        provider="codex",
        version="v1",
        execution_mode="run",
        attempt=1,
        work_item_id=_context()["work_item_id"],
        task_version=1,
        attempt_id=_context()["attempt_id"],
        artifact_refs=[],
        executor_authority_id=AUTHORITY_ID,
        admission_sha256=ADMISSION_SHA256,
    )
    target = Path(store.manifest_file)
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["attacker_controlled"] = "unknown"
    target.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    target.chmod(0o600)

    result = store.bind_private_lineage(_context())
    assert result["ok"] is False
    assert result["error_code"] == "SESSION_LINEAGE_MISSING"


@pytest.mark.parametrize("surface", ["report", "session"])
def test_report_and_session_reads_reject_symlink_and_hardlink_targets(
    tmp_path: Path, surface: str
) -> None:
    _, _, report_id, _ = _prepare_post_verifier_surfaces(tmp_path)
    if surface == "report":
        store = ExecutorRunReportStore(str(tmp_path))
        target = next(tmp_path.rglob(f"{report_id}.json"))
        read = lambda: store.read_durable_contract(
            report_id=report_id,
            expected_run_id="run-1",
        )
    else:
        store = ExecutorSessionStore(str(tmp_path))
        target = Path(store.manifest_file)
        read = lambda: store.read_durable_contract(expected_run_id="run-1")
    external = tmp_path / f"{surface}-external.json"
    external.write_bytes(target.read_bytes())
    external.chmod(0o600)
    target.unlink()
    target.symlink_to(external)
    assert read()["ok"] is False
    target.unlink()
    os.link(external, target)
    assert read()["ok"] is False


def test_full_ancestor_world_writable_component_blocks_event_io(tmp_path: Path) -> None:
    unsafe_parent = tmp_path / "unsafe-parent"
    project_root = unsafe_parent / "project"
    project_root.mkdir(parents=True)
    unsafe_parent.chmod(0o777)
    store = ExecutorEventStore(str(project_root))

    store.append("run-1", "heartbeat", {"sequence": 1})
    result = store.read_with_integrity("run-1")

    assert result["ok"] is False
    assert result["error_code"] == "EVENT_STORE_UNAVAILABLE"
    assert not (project_root / ".colameta").exists()


def test_mcp_status_projection_does_not_disclose_private_pair(
    tmp_path: Path, monkeypatch
) -> None:
    from runner.mcp_executor_workflow import MCPExecutorWorkflowManager

    store = ExecutorEventStore(str(tmp_path))
    store.append(
        "run-1",
        "executor_started",
        {"nested": {"executor_authority_id": AUTHORITY_ID, "admission_sha256": ADMISSION_SHA256}},
        _context(),
    )
    manager = object.__new__(MCPExecutorWorkflowManager)
    manager.project_root = str(tmp_path)
    monkeypatch.setattr(
        manager,
        "_evaluate_orphaned_claim",
        lambda claim: {"orphaned": False},
    )
    result: dict[str, object] = {}

    manager._apply_claim_to_status(
        result,
        {"run_id": "run-1", "preview_id": "preview-1", "status": "RUNNING"},
    )

    serialized = json.dumps(result)
    assert AUTHORITY_ID not in serialized
    assert ADMISSION_SHA256 not in serialized


def test_mcp_status_real_session_payload_does_not_disclose_private_pair(
    tmp_path: Path,
) -> None:
    from runner.mcp_executor_workflow import MCPExecutorWorkflowManager

    context = _context()
    sessions = ExecutorSessionStore(str(tmp_path))
    sessions.record_execution(
        provider="codex",
        version="v1",
        execution_mode="run",
        attempt=1,
        work_item_id=context["work_item_id"],
        task_version=context["task_version"],
        attempt_id=context["attempt_id"],
        artifact_refs=context["artifact_refs"],
        executor_authority_id=AUTHORITY_ID,
        admission_sha256=ADMISSION_SHA256,
    )
    assert sessions.bind_private_lineage(context)["ok"] is True

    result = MCPExecutorWorkflowManager(str(tmp_path))._status({})
    serialized = json.dumps(result)
    assert AUTHORITY_ID not in serialized
    assert ADMISSION_SHA256 not in serialized


def test_web_payload_projects_real_private_session_payload(tmp_path: Path) -> None:
    from runner.continuation_snapshot import ContinuationSnapshot
    from runner.web_console import WebConsoleServer

    context = _context()
    sessions = ExecutorSessionStore(str(tmp_path))
    sessions.record_execution(
        provider="codex",
        version="v1",
        execution_mode="run",
        attempt=1,
        work_item_id=context["work_item_id"],
        task_version=context["task_version"],
        attempt_id=context["attempt_id"],
        artifact_refs=context["artifact_refs"],
        executor_authority_id=AUTHORITY_ID,
        admission_sha256=ADMISSION_SHA256,
    )
    assert sessions.bind_private_lineage(context)["ok"] is True
    private_status = sessions.get_status(include_private_lineage=True)
    snapshot = ContinuationSnapshot(
        project_root=str(tmp_path),
        snapshot_id="snapshot-1",
        observed_at="2026-01-01T00:00:00Z",
        snapshot_status="ok",
        fact_bundle={"selected_provider": "codex"},
        session_status=private_status,
        continuation_preview={},
        activity_evidence={},
        operation_lock_observation={},
    )
    server = object.__new__(WebConsoleServer)
    server.project_root = str(tmp_path)
    payload: dict[str, object] = {}
    server._apply_executor_session_head_mismatch_classification(
        payload,
        requested_provider="codex",
        continuation_snapshot=snapshot,
    )

    serialized = json.dumps(payload)
    assert AUTHORITY_ID not in serialized
    assert ADMISSION_SHA256 not in serialized


def test_live_and_mcp_status_propagate_event_integrity_failure(
    tmp_path: Path, monkeypatch
) -> None:
    from runner.mcp_executor_workflow import MCPExecutorWorkflowManager

    store = ExecutorEventStore(str(tmp_path))
    store.append("run-1", "heartbeat", {"sequence": 1})
    event_file = Path(store.run_dir("run-1")) / "events.jsonl"
    with event_file.open("ab") as stream:
        stream.write(b"{}")

    live = build_live_snapshot(str(tmp_path), "run-1")
    assert live["ok"] is False
    assert live["status"] == "integrity_failed"
    assert live["error_code"] == "EVENT_TORN_TAIL"

    manager = object.__new__(MCPExecutorWorkflowManager)
    manager.project_root = str(tmp_path)
    monkeypatch.setattr(
        manager,
        "_evaluate_orphaned_claim",
        lambda claim: {"orphaned": False},
    )
    result: dict[str, object] = {}
    manager._apply_claim_to_status(
        result,
        {"run_id": "run-1", "preview_id": "preview-1", "status": "RUNNING"},
    )
    assert result["ok"] is False
    assert result["status"] == "integrity_failed"
    assert result["error_code"] == "EVENT_TORN_TAIL"


def test_mcp_public_schema_accepts_private_pair_only_as_strict_inputs(
    tmp_path: Path,
) -> None:
    from runner.mcp_server import MCPPlanningBridgeServer

    server = MCPPlanningBridgeServer(str(tmp_path), service_mode=False)
    tool = next(
        item for item in server.tool_defs if item.name == "manage_executor_workflow"
    )
    properties = tool.input_schema["properties"]

    assert properties["executor_authority_id"]["pattern"] == "^[0-9a-f]{32}$"
    assert properties["admission_sha256"]["pattern"] == "^[0-9a-f]{64}$"
    required_conditions = [
        {
            "if": {
                "properties": {
                    "action": {"const": "state_lineage_reconciliation_preview"}
                },
                "required": ["action"],
            },
            "then": {
                "required": ["expected_head", "target_next_version", "bindings"]
            },
        },
        {
            "if": {"required": ["executor_authority_id"]},
            "then": {"required": ["admission_sha256"]},
        },
        {
            "if": {"required": ["admission_sha256"]},
            "then": {"required": ["executor_authority_id"]},
        },
        {
            "if": {
                "anyOf": [
                    {"required": ["executor_authority_id"]},
                    {"required": ["admission_sha256"]},
                ]
            },
            "then": {
                "properties": {
                    "action": {"enum": ["run_once_preview", "run_once"]},
                    "executor_session_mode": {"const": "start_new"},
                },
                "required": ["executor_session_mode"],
            },
        },
        {
            "if": {
                "properties": {
                    "action": {"enum": ["run_once_preview", "run_once"]},
                    "executor_session_mode": {"const": "start_new"},
                },
                "required": ["action", "executor_session_mode"],
            },
            "then": {
                "required": ["executor_authority_id", "admission_sha256"]
            },
        },
    ]
    all_conditions = tool.input_schema["allOf"]
    for condition in required_conditions:
        assert condition in all_conditions
    assert "executor_authority_id" not in tool.output_schema.get("properties", {})
    assert "admission_sha256" not in tool.output_schema.get("properties", {})


@pytest.mark.parametrize("action", ["run_once_preview", "run_once"])
def test_real_mcp_server_route_preserves_exact_private_pair_without_output(
    tmp_path: Path, monkeypatch, action: str
) -> None:
    import runner.mcp_server as mcp_server_module

    captured: list[tuple[str, dict[str, object]]] = []

    class FakeManager:
        def __init__(self, project_root: str) -> None:
            self.project_root = project_root

        def handle(self, routed_action: str, params: dict[str, object]):
            captured.append((routed_action, dict(params)))
            return {
                "ok": True,
                "action": routed_action,
                "status": "preview_ready" if routed_action.endswith("preview") else "started",
                "preview_id": "preview-1",
            }

    monkeypatch.setattr(mcp_server_module, "MCPExecutorWorkflowManager", FakeManager)
    server = mcp_server_module.MCPPlanningBridgeServer(
        str(tmp_path), service_mode=False
    )
    params: dict[str, object] = {
        "action": action,
        "provider": "codex",
        "executor_session_mode": "start_new",
        "executor_authority_id": AUTHORITY_ID,
        "admission_sha256": ADMISSION_SHA256,
    }
    if action == "run_once":
        params["preview_id"] = "preview-1"

    result = server.call_tool_for_agent("manage_executor_workflow", params)

    assert result["ok"] is True
    assert captured[0][1]["executor_authority_id"] == AUTHORITY_ID
    assert captured[0][1]["admission_sha256"] == ADMISSION_SHA256
    assert AUTHORITY_ID not in json.dumps(result)
    assert ADMISSION_SHA256 not in json.dumps(result)


def test_real_mcp_route_delivers_exact_pair_to_fresh_authority_gate(
    tmp_path: Path, monkeypatch
) -> None:
    import runner.mcp_executor_workflow as workflow_module
    import runner.mcp_server as mcp_server_module

    captured: dict[str, object] = {}
    monkeypatch.setattr(
        workflow_module.ExecutorRunOnceService,
        "preflight",
        lambda self, **kwargs: {
            "preflight_blocked": False,
            "provider": "codex",
            "execution_mode": "run",
            "current_head": "c" * 40,
            "work_item_id": new_stable_id("work_item"),
            "task_version": 1,
            "attempt_id": new_stable_id("attempt"),
            "artifact_refs": [],
        },
    )

    def stop_at_gate(self, **kwargs):
        captured.update(kwargs)
        return "EXPECTED_GATE_STOP"

    monkeypatch.setattr(
        workflow_module.MCPExecutorWorkflowManager,
        "_fresh_authority_preview_gate",
        stop_at_gate,
    )
    server = mcp_server_module.MCPPlanningBridgeServer(
        str(tmp_path), service_mode=False
    )
    result = server.call_tool_for_agent(
        "manage_executor_workflow",
        {
            "action": "run_once_preview",
            "provider": "codex",
            "execution_mode": "run",
            "executor_session_mode": "start_new",
            "executor_authority_id": AUTHORITY_ID,
            "admission_sha256": ADMISSION_SHA256,
        },
    )

    public_data = result.get("data", result)
    assert isinstance(public_data, dict)
    assert public_data["ok"] is False
    assert public_data["error_code"] == "EXPECTED_GATE_STOP"
    assert captured["authority_id"] == AUTHORITY_ID
    assert captured["admission_sha256"] == ADMISSION_SHA256
    assert AUTHORITY_ID not in json.dumps(result)
    assert ADMISSION_SHA256 not in json.dumps(result)


@pytest.mark.parametrize(
    ("params", "error_code"),
    [
        (
            {
                "executor_session_mode": "start_new",
                "executor_authority_id": AUTHORITY_ID,
            },
            "FRESH_EXECUTOR_AUTHORITY_PAIR_REQUIRED",
        ),
        (
            {
                "executor_session_mode": "start_new",
                "executor_authority_id": f" {AUTHORITY_ID}",
                "admission_sha256": ADMISSION_SHA256,
            },
            "FRESH_EXECUTOR_AUTHORITY_FORMAT_INVALID",
        ),
        (
            {
                "executor_session_mode": "auto",
                "executor_authority_id": AUTHORITY_ID,
                "admission_sha256": ADMISSION_SHA256,
            },
            "FRESH_EXECUTOR_AUTHORITY_SESSION_MODE_MISMATCH",
        ),
    ],
)
def test_manager_rejects_invalid_private_pair_before_preflight(
    params: dict[str, object], error_code: str
) -> None:
    from runner.mcp_executor_workflow import MCPExecutorWorkflowManager

    manager = object.__new__(MCPExecutorWorkflowManager)
    result = manager._run_once_preview({"provider": "codex", **params})

    assert result["ok"] is False
    assert result["error_code"] == error_code
    assert AUTHORITY_ID not in json.dumps(result)
    assert ADMISSION_SHA256 not in json.dumps(result)


def test_web_executor_uses_governed_preview_claim_run_flow(
    tmp_path: Path, monkeypatch
) -> None:
    import runner.web_console as web_console_module

    calls: list[tuple[str, dict[str, object]]] = []

    class FakeManager:
        def __init__(self, project_root: str) -> None:
            self.project_root = project_root

        def handle(self, action: str, params: dict[str, object]):
            calls.append((action, dict(params)))
            if action == "run_once_preview":
                return {"ok": True, "preview_id": "preview-1", "status": "preview_ready"}
            return {
                "ok": True,
                "preview_id": "preview-1",
                "run_id": "run-1",
                "status": "started",
            }

    monkeypatch.setattr(web_console_module, "MCPExecutorWorkflowManager", FakeManager)
    monkeypatch.setattr(
        web_console_module,
        "resolve_version_execution_provider",
        lambda **kwargs: "codex",
    )
    server = object.__new__(web_console_module.WebConsoleServer)
    server.project_root = str(tmp_path)
    server._load_runtime_context = lambda: (
        SimpleNamespace(),
        SimpleNamespace(versions=[SimpleNamespace()]),
        SimpleNamespace(
            current_version="v1", current_version_index=0, status="READY"
        ),
        SimpleNamespace(),
        SimpleNamespace(),
    )
    server._load_execution_provider = lambda workspace: "codex"

    result = server._api_execute_current_version(
        "run",
        request_params={
            "executor_session_mode": "start_new",
            "executor_authority_id": AUTHORITY_ID,
            "admission_sha256": ADMISSION_SHA256,
        },
    )

    assert result["ok"] is True
    assert [action for action, _params in calls] == ["run_once_preview", "run_once"]
    assert calls[1][1]["preview_id"] == "preview-1"
    assert calls[1][1]["executor_authority_id"] == AUTHORITY_ID
    assert AUTHORITY_ID not in json.dumps(result)
    assert ADMISSION_SHA256 not in json.dumps(result)


def test_web_live_payload_preserves_integrity_failure(
    tmp_path: Path, monkeypatch
) -> None:
    import runner.executor_read as executor_read_module
    from runner.web_console import WebConsoleServer

    integrity_result = {
        "ok": False,
        "status": "integrity_failed",
        "terminal": True,
        "error_code": "EVENT_INTERIOR_CORRUPTION",
        "live": {
            "ok": False,
            "available": True,
            "status": "integrity_failed",
            "terminal": True,
            "error_code": "EVENT_INTERIOR_CORRUPTION",
            "events": [],
        },
    }
    monkeypatch.setattr(
        executor_read_module,
        "handle_inspect_executor_activity",
        lambda *args, **kwargs: integrity_result,
    )
    server = object.__new__(WebConsoleServer)
    server.project_root = str(tmp_path)

    payload = server._api_v2_live_run()
    assert payload == {
        "ok": False,
        "available": True,
        "status": "integrity_failed",
        "terminal": True,
        "error_code": "EVENT_INTERIOR_CORRUPTION",
        "events": [],
    }


def test_web_console_distinguishes_dispatch_from_actual_process_start() -> None:
    page = render_v2_index_page()
    assert 't === "executor_dispatch_started"' in page
    assert "正在调用" in page
    assert 't === "executor_started"' in page
    assert "已启动，正在执行任务" in page


def test_pre_binding_events_never_persist_requested_authority_pair(
    tmp_path: Path, monkeypatch
) -> None:
    project_root = _managed_workspace(tmp_path)
    service = ExecutorRunOnceService(str(project_root))
    monkeypatch.setattr(
        service,
        "preflight",
        lambda **kwargs: {
            "preflight_blocked": False,
            "current_head": "c" * 40,
            "preexisting_runner_files": [],
        },
    )
    monkeypatch.setattr(
        service,
        "_fresh_authority_execution_gate",
        lambda **kwargs: {"ok": False, "error_code": "EXPECTED_GATE_BLOCK"},
    )

    result = service._run_once_under_lease(
        provider="codex",
        run_id="run-1",
        preview_id="preview-1",
        executor_session_mode="start_new",
        executor_authority_id=AUTHORITY_ID,
        admission_sha256=ADMISSION_SHA256,
        continuation_recommended_action="start_new",
        claimed_work_target={},
    )

    assert result["ok"] is False
    events = service._event_store.read("run-1", include_private_lineage=True)
    assert events
    assert all("executor_authority_id" not in event for event in events)
    assert all("admission_sha256" not in event for event in events)


@pytest.mark.parametrize(
    ("error_code", "classification"),
    [
        ("EXECUTOR_FAILED", "executor_failed"),
        ("EXECUTOR_RESOURCE_EXHAUSTED", "executor_resource_exhausted"),
        ("EXECUTOR_INFRASTRUCTURE_FAILED", "executor_infrastructure_failed"),
    ],
)
def test_provider_entered_failures_persist_failed_report_before_terminal_events(
    tmp_path: Path,
    monkeypatch,
    error_code: str,
    classification: str,
) -> None:
    project_root = _managed_workspace(tmp_path)
    service = ExecutorRunOnceService(str(project_root))
    order: list[str] = []
    monkeypatch.setattr(
        service,
        "preflight",
        lambda **kwargs: {
            "preflight_blocked": False,
            "current_head": "c" * 40,
            "preexisting_runner_files": [],
        },
    )
    monkeypatch.setattr(
        service,
        "_fresh_authority_execution_gate",
        lambda **kwargs: {"ok": True},
    )
    monkeypatch.setattr(
        service,
        "_execute_provider",
        lambda **kwargs: {
            "ok": False,
            "status": "failed",
            "error_code": error_code,
            "message": "synthetic provider terminal failure",
            "classification": classification,
            "interruption_kind": "injected",
            "_provider_path_entered": True,
        },
    )
    original_record = service._record_executor_interruption_report
    original_event = service._maybe_write_event

    def record_then_mark(**kwargs):
        result = original_record(**kwargs)
        order.append("report")
        return result

    def event_then_mark(run_id, event_type, data=None, event_context=None):
        if event_type in {"executor_failed", "run_failed"}:
            order.append(event_type)
        return original_event(run_id, event_type, data, event_context)

    monkeypatch.setattr(service, "_record_executor_interruption_report", record_then_mark)
    monkeypatch.setattr(service, "_maybe_write_event", event_then_mark)

    result = service._run_once_under_lease(
        provider="codex",
        run_id="run-1",
        preview_id="preview-1",
    )

    assert result["ok"] is False
    assert result["latest_report_id"]
    assert order == ["report", "executor_failed", "run_failed"]
    report = ExecutorRunReportStore(str(project_root)).read_durable_contract(
        report_id=result["latest_report_id"],
        expected_run_id="run-1",
    )
    assert report["ok"] is False  # non-authority runs cannot assert private proof
    public_report = ExecutorRunReportStore(str(project_root)).get_report(
        report_id=result["latest_report_id"]
    )
    assert public_report["ok"] is True
    assert public_report["report"]["status"] == "failed"


def test_pre_provider_suppression_persists_failed_report_before_terminal_events(
    tmp_path: Path, monkeypatch
) -> None:
    project_root = _managed_workspace(tmp_path)
    service = ExecutorRunOnceService(str(project_root))
    order: list[str] = []
    monkeypatch.setattr(
        service,
        "preflight",
        lambda **kwargs: {
            "preflight_blocked": False,
            "current_head": "c" * 40,
            "preexisting_runner_files": [],
        },
    )
    monkeypatch.setattr(
        service,
        "_fresh_authority_execution_gate",
        lambda **kwargs: {
            "ok": True,
            "executor_authority_id": AUTHORITY_ID,
            "admission_sha256": ADMISSION_SHA256,
        },
    )
    monkeypatch.setattr(
        service,
        "_execute_provider",
        lambda **kwargs: {
            "ok": False,
            "status": "failed",
            "error_code": "EVENT_DURABLE_IDENTITY_DRIFT",
            "message": "event stream replaced before provider dispatch",
            "_provider_path_entered": False,
        },
    )
    original_record = service._record_executor_interruption_report
    original_event = service._maybe_write_event

    def record_then_mark(**kwargs):
        result = original_record(**kwargs)
        assert result.get("ok") is True, result
        order.append("report")
        return result

    def event_then_mark(run_id, event_type, data=None, event_context=None):
        if event_type in {"executor_failed", "run_failed"}:
            order.append(event_type)
        return original_event(run_id, event_type, data, event_context)

    monkeypatch.setattr(service, "_record_executor_interruption_report", record_then_mark)
    monkeypatch.setattr(service, "_maybe_write_event", event_then_mark)

    result = service._run_once_under_lease(
        provider="codex",
        run_id="run-1",
        preview_id="preview-1",
        executor_session_mode="start_new",
        executor_authority_id=AUTHORITY_ID,
        admission_sha256=ADMISSION_SHA256,
        continuation_recommended_action="start_new",
        claimed_work_target={},
    )

    assert result["ok"] is False
    assert result["error_code"] == "EVENT_DURABLE_IDENTITY_DRIFT"
    assert result["latest_report_id"]
    assert order == ["report", "executor_failed", "run_failed"]
    report = ExecutorRunReportStore(str(project_root)).get_report(
        report_id=result["latest_report_id"]
    )
    assert report["ok"] is True
    assert report["report"]["status"] == "failed"


def test_session_binding_failure_persists_failed_report_before_terminal_events(
    tmp_path: Path, monkeypatch
) -> None:
    project_root = _managed_workspace(tmp_path)
    service = ExecutorRunOnceService(str(project_root))
    order: list[str] = []
    monkeypatch.setattr(
        service,
        "preflight",
        lambda **kwargs: {
            "preflight_blocked": False,
            "current_head": "c" * 40,
            "preexisting_runner_files": [],
        },
    )
    monkeypatch.setattr(
        service,
        "_fresh_authority_execution_gate",
        lambda **kwargs: {
            "ok": True,
            "executor_authority_id": AUTHORITY_ID,
            "admission_sha256": ADMISSION_SHA256,
        },
    )
    monkeypatch.setattr(
        service,
        "_execute_provider",
        lambda **kwargs: {"ok": True, "_provider_path_entered": True},
    )
    monkeypatch.setattr(
        ExecutorSessionStore,
        "bind_private_lineage",
        lambda self, context: {
            "ok": False,
            "error_code": "SESSION_BINDING_INJECTED_FAILURE",
        },
    )
    original_record = service._record_executor_interruption_report
    original_event = service._maybe_write_event

    def record_then_mark(**kwargs):
        result = original_record(**kwargs)
        order.append("report")
        return result

    def event_then_mark(run_id, event_type, data=None, event_context=None):
        if event_type in {"executor_failed", "run_failed"}:
            order.append(event_type)
        return original_event(run_id, event_type, data, event_context)

    monkeypatch.setattr(service, "_record_executor_interruption_report", record_then_mark)
    monkeypatch.setattr(service, "_maybe_write_event", event_then_mark)

    result = service._run_once_under_lease(
        provider="codex",
        run_id="run-1",
        preview_id="preview-1",
        executor_session_mode="start_new",
        executor_authority_id=AUTHORITY_ID,
        admission_sha256=ADMISSION_SHA256,
        continuation_recommended_action="start_new",
        claimed_work_target={},
    )

    assert result["ok"] is False
    assert order[:3] == ["report", "executor_failed", "run_failed"]
    reports = ExecutorRunReportStore(str(project_root)).list_reports(limit=1)
    assert reports and reports[0]["status"] == "failed"


def test_successful_gate_adds_validated_pair_to_provider_context(
    tmp_path: Path, monkeypatch
) -> None:
    project_root = _managed_workspace(tmp_path)
    service = ExecutorRunOnceService(str(project_root))
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        service,
        "preflight",
        lambda **kwargs: {
            "preflight_blocked": False,
            "current_head": "c" * 40,
            "preexisting_runner_files": [],
        },
    )
    monkeypatch.setattr(
        service,
        "_fresh_authority_execution_gate",
        lambda **kwargs: {
            "ok": True,
            "executor_authority_id": AUTHORITY_ID,
            "admission_sha256": ADMISSION_SHA256,
        },
    )

    def capture_provider_context(**kwargs):
        captured.update(kwargs["event_context"])
        raise RuntimeError("stop after provider context capture")

    monkeypatch.setattr(service, "_execute_provider", capture_provider_context)

    with pytest.raises(RuntimeError, match="context capture"):
        service._run_once_under_lease(
            provider="codex",
            run_id="run-1",
            preview_id="preview-1",
            executor_session_mode="start_new",
            executor_authority_id=AUTHORITY_ID,
            admission_sha256=ADMISSION_SHA256,
            continuation_recommended_action="start_new",
            claimed_work_target={},
        )

    assert captured["executor_authority_id"] == AUTHORITY_ID
    assert captured["admission_sha256"] == ADMISSION_SHA256
