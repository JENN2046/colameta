from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from adapters.executor_process_supervisor import ExecutorProcessSupervisor
from runner.executor_events import ExecutorEventStore
from runner.executor_run_claims import ExecutorRunClaimStore
from runner.executor_run_workflow import ExecutorRunOnceService
from runner.fresh_executor_authority import (
    _read_admission_verification,
    _validate_and_create_execution_binding_verification,
    create_fresh_executor_authority,
)
from runner.work_item_governance.ids import new_stable_id


def _bound_context() -> dict[str, object]:
    return {
        "run_id": "run-1",
        "preview_id": "preview-1",
        "provider": "codex",
        "work_item_id": new_stable_id("work_item"),
        "task_version": 1,
        "attempt_id": new_stable_id("attempt"),
        "artifact_refs": [],
        "executor_authority_id": "a" * 32,
        "admission_sha256": "b" * 64,
    }


def _prepare_durable_dispatch_lineage(
    project_root: Path,
    context: dict[str, object],
) -> dict[str, object]:
    project_root.chmod(0o755)
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(project_root)],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(project_root), "config", "user.email", "lineage@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(project_root), "config", "user.name", "Lineage Fixture"],
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(project_root),
            "remote",
            "add",
            "origin",
            "git@github.com:JENN2046/colameta.git",
        ],
        check=True,
    )
    (project_root / ".gitignore").write_text(
        ".colameta/runtime/**\n",
        encoding="utf-8",
    )
    (project_root / "fixture.txt").write_text("lineage fixture\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(project_root), "add", ".gitignore", "fixture.txt"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(project_root), "commit", "-qm", "lineage fixture"],
        check=True,
    )
    head = subprocess.run(
        ["git", "-C", str(project_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    authority = create_fresh_executor_authority(
        str(project_root),
        expected_head=head,
    )
    assert authority.get("ok") is True, authority
    authority_id = str(authority["executor_authority_id"])
    admission = _read_admission_verification(
        str(project_root),
        authority_id,
        expected_head=head,
        expected_provider="codex",
        expected_repository="JENN2046/colameta",
        expected_git_branch="main",
    )
    assert admission.get("ok") is True, admission
    admission_sha256 = str(admission["admission_sha256"])

    claims = ExecutorRunClaimStore(
        str(project_root),
        ".colameta/runtime/executor-workflow-previews",
        "claims",
        heartbeat_interval_seconds=5,
        heartbeat_stale_multiplier=3,
        heartbeat_stale_min_seconds=20,
    )
    claim = claims.acquire_claim(
        preview_id=str(context["preview_id"]),
        artifact={
            "artifact_kind": "run_once",
            "current_version": "v1",
            "current_head": head,
            "created_at": "2026-08-25T00:00:00+00:00",
            "expires_at": "2026-08-25T00:15:00+00:00",
            "work_item_id": context["work_item_id"],
            "task_version": context["task_version"],
            "attempt_id": context["attempt_id"],
            "artifact_refs": context["artifact_refs"],
        },
        provider="codex",
        execution_mode="run",
        executor_authority_id=authority_id,
        admission_sha256=admission_sha256,
    )
    assert claim.get("ok") is True, claim
    context.update(
        {
            "run_id": claim["run_id"],
            "version": "v1",
            "execution_mode": "run",
            "executor_authority_id": authority_id,
            "admission_sha256": admission_sha256,
        }
    )
    event_store = ExecutorEventStore(str(project_root))
    event_store.append(
        str(context["run_id"]),
        "run_claimed",
        {"run_id": context["run_id"], "preview_id": context["preview_id"]},
        {
            key: context[key]
            for key in (
                "run_id", "preview_id", "version", "provider", "execution_mode",
                "work_item_id", "task_version", "attempt_id", "artifact_refs",
            )
        },
    )
    stream_origin = event_store.capture_stream_origin(str(context["run_id"]))
    assert stream_origin.get("ok") is True, stream_origin
    binding = _validate_and_create_execution_binding_verification(
        str(project_root),
        authority_id,
        expected_admission_sha256=admission_sha256,
        expected_head=head,
        expected_provider="codex",
        expected_repository="JENN2046/colameta",
        expected_git_branch="main",
        run_id=str(context["run_id"]),
        preview_id=str(context["preview_id"]),
        executor_session_mode="start_new",
        work_target={
            "work_item_id": context["work_item_id"],
            "task_version": context["task_version"],
            "attempt_id": context["attempt_id"],
            "artifact_refs": context["artifact_refs"],
        },
        repository="JENN2046/colameta",
        event_stream=stream_origin["stream_origin_contract"],
    )
    assert binding.get("ok") is True, binding
    return binding


def test_executor_started_is_written_after_successful_process_spawn(tmp_path: Path) -> None:
    store = ExecutorEventStore(str(tmp_path))
    context = _bound_context()

    result = ExecutorProcessSupervisor().run_process(
        [sys.executable, "-c", "print('ok')"],
        cwd=str(tmp_path),
        event_store=store,
        run_id="run-1",
        event_context=context,
    )

    assert result.returncode == 0
    started = [
        event
        for event in store.read("run-1", include_private_lineage=True)
        if event["event_type"] == "executor_started"
    ]
    assert len(started) == 1
    assert started[0]["executor_authority_id"] == "a" * 32
    event_types = [
        event["event_type"]
        for event in store.read("run-1", include_private_lineage=True)
    ]
    assert "executor_finished" not in event_types
    assert "executor_failed" not in event_types


def test_nonzero_process_exit_defers_terminal_event_to_workflow(tmp_path: Path) -> None:
    store = ExecutorEventStore(str(tmp_path))

    result = ExecutorProcessSupervisor().run_process(
        [sys.executable, "-c", "raise SystemExit(7)"],
        cwd=str(tmp_path),
        event_store=store,
        run_id="run-1",
        event_context={"run_id": "run-1", "provider": "codex"},
    )

    assert result.returncode == 7
    event_types = [event["event_type"] for event in store.read("run-1")]
    assert event_types == ["executor_started"]


def test_failed_process_spawn_does_not_write_executor_started(tmp_path: Path) -> None:
    store = ExecutorEventStore(str(tmp_path))

    with pytest.raises(FileNotFoundError):
        ExecutorProcessSupervisor().run_process(
            [str(tmp_path / "missing-executable")],
            cwd=str(tmp_path),
            event_store=store,
            run_id="run-1",
            event_context={"run_id": "run-1", "provider": "codex"},
        )

    assert store.read("run-1", include_private_lineage=True) == []


def test_workflow_uses_dispatch_event_not_process_started(monkeypatch, tmp_path: Path) -> None:
    import runner.codex_executor as codex_executor_module

    class FakeCodexExecutor:
        def __init__(self, workspace, **kwargs) -> None:
            self.workspace = workspace

        def run_current_version(self, plan, state, **kwargs):
            return object()

    service = ExecutorRunOnceService(str(tmp_path))
    observed: list[str] = []
    monkeypatch.setattr(codex_executor_module, "CodexExecutor", FakeCodexExecutor)
    monkeypatch.setattr(
        service,
        "_maybe_write_event",
        lambda run_id, event_type, data=None, event_context=None: observed.append(event_type),
    )

    result = service._execute_provider(
        provider="codex",
        plan=object(),
        state=object(),
        workspace=object(),
        is_fix=False,
        execution_mode="run",
        head_before="a" * 40,
        run_id="run-1",
        event_context={"run_id": "run-1"},
    )

    assert result["ok"] is True
    assert observed == ["executor_dispatch_started"]


def test_production_provider_path_blocks_cross_append_stream_replacement(
    monkeypatch, tmp_path: Path
) -> None:
    import runner.codex_executor as codex_executor_module

    provider_called = False

    class FakeCodexExecutor:
        def __init__(self, workspace, **kwargs) -> None:
            self.workspace = workspace

        def run_current_version(self, plan, state, **kwargs):
            nonlocal provider_called
            provider_called = True
            return object()

    context = _bound_context()
    binding = _prepare_durable_dispatch_lineage(tmp_path, context)
    store = ExecutorEventStore(str(tmp_path))
    original_run_dir = Path(store.run_dir(str(context["run_id"])))
    displaced_run_dir = original_run_dir.with_name("displaced-original-run")
    original_run_dir.rename(displaced_run_dir)
    original_run_dir.mkdir(mode=0o700)
    monkeypatch.setattr(codex_executor_module, "CodexExecutor", FakeCodexExecutor)

    result = ExecutorRunOnceService(str(tmp_path))._execute_provider(
        provider="codex",
        plan=object(),
        state=object(),
        workspace=object(),
        is_fix=False,
        execution_mode="run",
        head_before="a" * 40,
        executor_session_mode="start_new",
        run_id=str(context["run_id"]),
        event_context=context,
        executor_authority_id=str(context["executor_authority_id"]),
        admission_sha256=str(context["admission_sha256"]),
        durable_lifecycle={
            "binding_creation": {
                "ok": True,
                "record": binding["binding"],
                "durable_contract": binding["_internal_verification"]["binding"],
            }
        },
    )

    assert result["ok"] is False
    assert result["error_code"] == "EVENT_DURABLE_IDENTITY_DRIFT"
    assert result["_provider_path_entered"] is False
    assert provider_called is False


def test_preflight_builds_and_verifies_full_acceptance_execution_plan(
    monkeypatch, tmp_path: Path
) -> None:
    import runner.executor_run_workflow as workflow_module

    runner_dir = tmp_path / ".colameta"
    runner_dir.mkdir()
    work_item_id = new_stable_id("work_item")
    attempt_id = new_stable_id("attempt")
    (runner_dir / "plan.json").write_text(
        json.dumps({
            "project_name": "demo",
            "project_root": str(tmp_path),
            "work_item_id": work_item_id,
            "task_version": 1,
            "attempt_id": attempt_id,
            "artifact_refs": [],
            "versions": [{
                "version": "v1",
                "name": "v1",
                "enabled": True,
                "acceptance_commands": [{"command": "git diff --check"}],
            }],
        }),
        encoding="utf-8",
    )
    (runner_dir / "state.json").write_text(
        json.dumps({
            "project_name": "demo",
            "status": "READY",
            "current_version": "v1",
            "current_version_index": 0,
            "attempt": 1,
            "versions": [{"version": "v1", "name": "v1", "status": "NOT_STARTED"}],
        }),
        encoding="utf-8",
    )
    pinned_plan = object()
    observed: list[object] = []
    monkeypatch.setattr(
        workflow_module,
        "acceptance_command_to_execution_plan",
        lambda command, *, project_root: observed.append((command, project_root))
        or pinned_plan,
    )
    monkeypatch.setattr(
        workflow_module,
        "verify_acceptance_execution_plan",
        lambda plan: observed.append(plan),
    )

    ExecutorRunOnceService(str(tmp_path)).preflight("codex")

    assert observed == [("git diff --check", str(tmp_path)), pinned_plan]


def test_bound_workflow_verifies_private_dispatch_lineage_before_provider(
    monkeypatch, tmp_path: Path
) -> None:
    import runner.codex_executor as codex_executor_module

    provider_called = False

    class FakeCodexExecutor:
        def __init__(self, workspace, **kwargs) -> None:
            self.workspace = workspace

        def run_current_version(self, plan, state, **kwargs):
            nonlocal provider_called
            provider_called = True
            return object()

    service = ExecutorRunOnceService(str(tmp_path))
    context = _bound_context()
    monkeypatch.setattr(codex_executor_module, "CodexExecutor", FakeCodexExecutor)
    binding = _prepare_durable_dispatch_lineage(tmp_path, context)
    binding_verification = binding["_internal_verification"]["binding"]
    durable_lifecycle = {
        "binding_creation": {
            "ok": True,
            "record": binding["binding"],
            "durable_contract": binding_verification,
        }
    }

    result = service._execute_provider(
        provider="codex",
        plan=object(),
        state=object(),
        workspace=object(),
        is_fix=False,
        execution_mode="run",
        head_before="a" * 40,
        executor_session_mode="start_new",
        run_id=str(context["run_id"]),
        event_context=context,
        executor_authority_id=str(context["executor_authority_id"]),
        admission_sha256=str(context["admission_sha256"]),
        durable_lifecycle=durable_lifecycle,
    )

    assert result["ok"] is True
    assert provider_called is True
    verification = service._event_store.verify_private_lineage(
        str(context["run_id"]),
        expected_event_context=context,
        event_type="executor_dispatch_started",
    )
    assert verification["ok"] is True


def test_bound_workflow_requires_durable_claim_and_binding_before_provider(
    monkeypatch, tmp_path: Path
) -> None:
    import runner.codex_executor as codex_executor_module

    provider_called = False

    class FakeCodexExecutor:
        def __init__(self, workspace, **kwargs) -> None:
            self.workspace = workspace

        def run_current_version(self, plan, state, **kwargs):
            nonlocal provider_called
            provider_called = True
            return object()

    service = ExecutorRunOnceService(str(tmp_path))
    context = _bound_context()
    monkeypatch.setattr(codex_executor_module, "CodexExecutor", FakeCodexExecutor)

    result = service._execute_provider(
        provider="codex",
        plan=object(),
        state=object(),
        workspace=object(),
        is_fix=False,
        execution_mode="run",
        head_before="a" * 40,
        run_id="run-1",
        event_context=context,
        executor_authority_id="a" * 32,
        admission_sha256="b" * 64,
    )

    assert result["ok"] is False
    assert result["error_code"] == "BINDING_LINEAGE_MISSING"
    assert provider_called is False


def test_bound_workflow_blocks_provider_when_dispatch_lineage_is_invalid(
    monkeypatch, tmp_path: Path
) -> None:
    import runner.codex_executor as codex_executor_module

    provider_called = False

    class FakeCodexExecutor:
        def __init__(self, workspace, **kwargs) -> None:
            self.workspace = workspace

        def run_current_version(self, plan, state, **kwargs):
            nonlocal provider_called
            provider_called = True
            return object()

    service = ExecutorRunOnceService(str(tmp_path))
    context = _bound_context()
    context.pop("artifact_refs")
    monkeypatch.setattr(codex_executor_module, "CodexExecutor", FakeCodexExecutor)

    result = service._execute_provider(
        provider="codex",
        plan=object(),
        state=object(),
        workspace=object(),
        is_fix=False,
        execution_mode="run",
        head_before="a" * 40,
        run_id="run-1",
        event_context=context,
        executor_authority_id="a" * 32,
        admission_sha256="b" * 64,
    )

    assert result["ok"] is False
    assert result["error_code"] == "EXPECTED_PRIVATE_LINEAGE_INVALID"
    assert provider_called is False
    assert [event["event_type"] for event in service._event_store.read("run-1")] == [
        "executor_dispatch_started"
    ]


def test_dispatch_failure_never_counts_as_actual_process_start(monkeypatch, tmp_path: Path) -> None:
    import runner.codex_executor as codex_executor_module

    class FailingCodexExecutor:
        def __init__(self, workspace, **kwargs) -> None:
            self.workspace = workspace

        def run_current_version(self, plan, state, **kwargs):
            raise FileNotFoundError("spawn failed")

    service = ExecutorRunOnceService(str(tmp_path))
    monkeypatch.setattr(codex_executor_module, "CodexExecutor", FailingCodexExecutor)

    result = service._execute_provider(
        provider="codex",
        plan=object(),
        state=object(),
        workspace=object(),
        is_fix=False,
        execution_mode="run",
        head_before="a" * 40,
        run_id="run-1",
        event_context={"run_id": "run-1"},
    )

    event_types = [event["event_type"] for event in service._event_store.read("run-1")]
    assert result["ok"] is False
    assert event_types.count("executor_dispatch_started") == 1
    assert event_types.count("executor_started") == 0


def test_pi_spawn_failure_does_not_emit_executor_started(monkeypatch, tmp_path: Path) -> None:
    import adapters.pi_rpc_adapter as pi_module

    observed: list[str] = []
    monkeypatch.setattr(pi_module.shutil, "which", lambda executable: "/usr/bin/pi")
    monkeypatch.setattr(
        pi_module.subprocess,
        "Popen",
        lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError("spawn failed")),
    )
    monkeypatch.setattr(
        pi_module.ExecutorEventStore,
        "append",
        lambda self, run_id, event_type, data=None, event_context=None: observed.append(event_type),
    )

    with pytest.raises(pi_module.PiRpcError, match="spawn failed"):
        pi_module.PiRpcAdapter().execute_prompt(
            project_root=str(tmp_path),
            logs_dir=str(tmp_path / "logs"),
            runner_dir=str(tmp_path / ".colameta"),
            version="v1",
            attempt=1,
            prompt="test",
            prompt_file="prompt.md",
            run_id="run-1",
            event_context={"run_id": "run-1"},
        )

    assert "executor_started" not in observed


def test_pi_emits_executor_started_only_after_popen_returns(monkeypatch, tmp_path: Path) -> None:
    import adapters.pi_rpc_adapter as pi_module

    observed: list[str] = []

    class FakeProcess:
        def __init__(self) -> None:
            self.stdin = io.StringIO()
            self.stdout = io.StringIO()
            self.stderr = io.StringIO()

    def fake_popen(*args, **kwargs):
        observed.append("popen_returned")
        return FakeProcess()

    adapter = pi_module.PiRpcAdapter()
    monkeypatch.setattr(pi_module.shutil, "which", lambda executable: "/usr/bin/pi")
    monkeypatch.setattr(pi_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        pi_module.ExecutorEventStore,
        "append",
        lambda self, run_id, event_type, data=None, event_context=None: observed.append(event_type),
    )
    monkeypatch.setattr(
        adapter,
        "_send_and_wait",
        lambda *args, **kwargs: (_ for _ in ()).throw(pi_module.PiRpcError("stop")),
    )
    monkeypatch.setattr(adapter, "_stop_process", lambda process: 1)
    monkeypatch.setattr(adapter, "_write_log", lambda **kwargs: None)

    with pytest.raises(pi_module.PiRpcError, match="stop"):
        adapter.execute_prompt(
            project_root=str(tmp_path),
            logs_dir=str(tmp_path / "logs"),
            runner_dir=str(tmp_path / ".colameta"),
            version="v1",
            attempt=1,
            prompt="test",
            prompt_file="prompt.md",
            run_id="run-1",
            event_context={"run_id": "run-1"},
        )

    assert observed[:2] == ["popen_returned", "executor_started"]
