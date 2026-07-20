from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import stat
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from runner import mcp_private_operator as private_operator_module
from runner.mcp_private_operator import (
    OPERATOR_PROFILE_JENN,
    OperatorBatchService,
    OperatorPermitStore,
    OperatorSettingsStore,
    evaluate_operator_principal,
    normalize_operator_operations,
    operator_authenticated_request_scope,
    validate_operator_ticket,
)
from runner.mcp_server import MCPPlanningBridgeServer
from runner.mcp_git_commit import MCPGitCommitManager
from runner.mcp_project_patch import MCPProjectPatchManager
from runner.planning_bridge import PlanningBridge
from runner.source_review_bridge import SourceReviewBridge
from scripts import runner_cli


def _auth(*, subject: str = "auth0|jenn", client: str = "https://chatgpt.example/cimd") -> dict:
    return {
        "mode": "external-oauth",
        "oauth_provider": SimpleNamespace(
            issuer="https://issuer.example/",
            audience="https://mcp.example/mcp",
            resource="https://mcp.example/mcp",
        ),
        "token": {
            "iss": "https://issuer.example/",
            "aud": "https://mcp.example/mcp",
            "sub": subject,
            "azp": client,
            "client_id": client,
            "scope": "mcp:read mcp:preview mcp:plan mcp:commit",
        },
    }


def _settings(tmp_path: Path) -> OperatorSettingsStore:
    store = OperatorSettingsStore(str(tmp_path / "config"))
    result = store.enable("auth0|jenn", "https://chatgpt.example/cimd")
    assert result["ok"] is True
    return store


def _validator(operation: dict) -> dict:
    preview_id = operation.get("preview_id") or operation.get("params", {}).get("preview_id")
    if preview_id == "missing_0000":
        return {"ok": False, "error_code": "OPERATOR_PREVIEW_NOT_FOUND"}
    return {"ok": True, "preview_digest": "a" * 64}


def _commit_operation(step_id: str, preview_id: str) -> dict:
    return {
        "step_id": step_id,
        "tool": "manage_git",
        "params": {"action": "commit_apply", "preview_id": preview_id},
    }


def _claim_ticket(store: OperatorPermitStore, batch_id: str) -> dict:
    expected_ticket = store.read(batch_id)
    assert isinstance(expected_ticket, dict)
    return store.claim(batch_id, expected_ticket=expected_ticket)


def _track_os_descriptors(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[set[int], object, object]:
    real_open = os.open
    real_close = os.close
    live_fds: set[int] = set()

    def tracked_open(*args: object, **kwargs: object) -> int:
        fd = real_open(*args, **kwargs)
        live_fds.add(fd)
        return fd

    def tracked_close(fd: int) -> None:
        real_close(fd)
        live_fds.discard(fd)

    monkeypatch.setattr(os, "open", tracked_open)
    monkeypatch.setattr(os, "close", tracked_close)
    return live_fds, real_open, real_close


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def test_operator_settings_store_hashes_principal_and_uses_private_mode(tmp_path: Path) -> None:
    store = _settings(tmp_path)
    raw = Path(store.path).read_text(encoding="utf-8")
    assert "auth0|jenn" not in raw
    assert "chatgpt.example" not in raw
    data = json.loads(raw)
    assert data["oauth_operator_profile"] == OPERATOR_PROFILE_JENN
    if os.name == "posix":
        assert stat.S_IMODE(os.stat(store.path).st_mode) == 0o600
        assert stat.S_IMODE(os.stat(store.config_dir).st_mode) == 0o700
    assert store.status() == {
        "ok": True,
        "enabled": True,
        "profile": OPERATOR_PROFILE_JENN,
        "permit_ttl_seconds": 300,
        "batch_max_steps": 8,
    }
    disabled = store.disable()
    assert disabled["ok"] is True
    assert disabled["enabled"] is False
    assert "subject_fingerprint" not in json.loads(Path(store.path).read_text(encoding="utf-8"))


def test_private_quarantine_threshold_status_is_detached_and_sanitized() -> None:
    assert private_operator_module.private_operator_local_runtime_status() == {
        "quarantined_close_fd_count": 0,
        "quarantine_attention_threshold": 1,
        "quarantine_status": "clear",
        "local_alert_code": None,
    }
    sentinel_fd = 987_654_321
    try:
        with private_operator_module._ACTIVE_BATCHES_LOCK:
            private_operator_module._QUARANTINED_CLOSE_FDS.add(sentinel_fd)
        observed = private_operator_module.private_operator_local_runtime_status()
        assert observed == {
            "quarantined_close_fd_count": 1,
            "quarantine_attention_threshold": 1,
            "quarantine_status": "attention",
            "local_alert_code": "OPERATOR_FD_QUARANTINE_ATTENTION",
        }
        assert str(sentinel_fd) not in json.dumps(observed)
        observed["quarantined_close_fd_count"] = 999
        assert private_operator_module.private_operator_local_runtime_status()[
            "quarantined_close_fd_count"
        ] == 1
    finally:
        with private_operator_module._ACTIVE_BATCHES_LOCK:
            private_operator_module._QUARANTINED_CLOSE_FDS.discard(sentinel_fd)


def test_local_operator_config_status_surfaces_private_quarantine_alert_only_locally(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    sentinel_fd = 987_654_322

    class LocalStore:
        @staticmethod
        def status() -> dict:
            return {
                "ok": True,
                "enabled": True,
                "profile": OPERATOR_PROFILE_JENN,
                "permit_ttl_seconds": 300,
                "batch_max_steps": 8,
            }

    monkeypatch.setattr(runner_cli, "OperatorSettingsStore", LocalStore)
    monkeypatch.setattr(
        runner_cli,
        "query_private_operator_health",
        lambda project_path=None: {
            "observation_source": "service_private_ipc",
            "observation_status": "observed",
            "quarantined_close_fd_count": 1,
            "quarantine_attention_threshold": 1,
            "quarantine_status": "attention",
            "local_alert_code": "OPERATOR_FD_QUARANTINE_ATTENTION",
        },
    )
    try:
        with private_operator_module._ACTIVE_BATCHES_LOCK:
            private_operator_module._QUARANTINED_CLOSE_FDS.add(sentinel_fd)
        assert runner_cli._run_operator_config(["operator-config", "status"]) == 0
        rendered = capsys.readouterr().out
        payload = json.loads(rendered)
        assert payload["private_runtime"] == {
            "observation_source": "service_private_ipc",
            "observation_status": "observed",
            "quarantined_close_fd_count": 1,
            "quarantine_attention_threshold": 1,
            "quarantine_status": "attention",
            "local_alert_code": "OPERATOR_FD_QUARANTINE_ATTENTION",
        }
        assert str(sentinel_fd) not in rendered
    finally:
        with private_operator_module._ACTIVE_BATCHES_LOCK:
            private_operator_module._QUARANTINED_CLOSE_FDS.discard(sentinel_fd)


def test_private_quarantine_alert_is_absent_from_operator_mcp_results(tmp_path: Path) -> None:
    _settings_store, _permits, service = _matrix_service(tmp_path)
    sentinel_fd = 987_654_323
    try:
        with private_operator_module._ACTIVE_BATCHES_LOCK:
            private_operator_module._QUARANTINED_CLOSE_FDS.add(sentinel_fd)
        preview = _matrix_preview(
            service,
            [_commit_operation("commit", "preview_private_alert_omission")],
        )
        serialized = json.dumps(preview, sort_keys=True)
        assert "private_runtime" not in serialized
        assert "quarantine" not in serialized
        assert "OPERATOR_FD_QUARANTINE_ATTENTION" not in serialized
        assert str(sentinel_fd) not in serialized
    finally:
        with private_operator_module._ACTIVE_BATCHES_LOCK:
            private_operator_module._QUARANTINED_CLOSE_FDS.discard(sentinel_fd)


@pytest.mark.parametrize(
    ("quarantined_count", "expected_status"),
    [(0, "clear"), (1, "attention"), (2, "attention"), (5, "attention")],
)
def test_private_quarantine_threshold_handles_multiple_fds(
    quarantined_count: int,
    expected_status: str,
) -> None:
    sentinel_fds = {987_655_000 + index for index in range(quarantined_count)}
    try:
        with private_operator_module._ACTIVE_BATCHES_LOCK:
            assert private_operator_module._QUARANTINED_CLOSE_FDS == set()
            private_operator_module._QUARANTINED_CLOSE_FDS.update(sentinel_fds)
        observed = private_operator_module.private_operator_local_runtime_status()
        assert observed["quarantined_close_fd_count"] == quarantined_count
        assert observed["quarantine_attention_threshold"] == 1
        assert observed["quarantine_status"] == expected_status
        assert observed["local_alert_code"] == (
            None if quarantined_count == 0 else "OPERATOR_FD_QUARANTINE_ATTENTION"
        )
        for sentinel_fd in sentinel_fds:
            assert str(sentinel_fd) not in json.dumps(observed)
    finally:
        with private_operator_module._ACTIVE_BATCHES_LOCK:
            private_operator_module._QUARANTINED_CLOSE_FDS.difference_update(sentinel_fds)


def test_private_quarantine_gauge_resets_in_fresh_process() -> None:
    sentinel_fd = 987_655_100
    try:
        with private_operator_module._ACTIVE_BATCHES_LOCK:
            private_operator_module._QUARANTINED_CLOSE_FDS.add(sentinel_fd)
        assert private_operator_module.private_operator_local_runtime_status()[
            "quarantined_close_fd_count"
        ] == 1
        completed = subprocess.run(
            [
                sys.executable,
                "-B",
                "-c",
                (
                    "import json; "
                    "from runner.mcp_private_operator import private_operator_local_runtime_status; "
                    "print(json.dumps(private_operator_local_runtime_status(), sort_keys=True))"
                ),
            ],
            cwd=Path(__file__).resolve().parents[1],
            check=True,
            capture_output=True,
            text=True,
        )
        child_status = json.loads(completed.stdout)
        assert child_status == {
            "local_alert_code": None,
            "quarantine_attention_threshold": 1,
            "quarantine_status": "clear",
            "quarantined_close_fd_count": 0,
        }
        assert completed.stderr == ""
    finally:
        with private_operator_module._ACTIVE_BATCHES_LOCK:
            private_operator_module._QUARANTINED_CLOSE_FDS.discard(sentinel_fd)


def test_local_service_health_summary_includes_private_attention_without_fd_ids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    sentinel_fd = 987_655_200
    packet = {
        "runtime_status": {},
        "connector_runtime_health": {},
        "apps_connector_closeout": {},
        "apps_connector_smoke_packet": {},
        "stable_replacement_cadence": {},
    }
    monkeypatch.setattr(runner_cli, "_connector_runtime_health_packet", lambda **_kwargs: packet)
    monkeypatch.setattr(runner_cli, "_registered_project_name_for_path", lambda _path: "project")
    try:
        with private_operator_module._ACTIVE_BATCHES_LOCK:
            private_operator_module._QUARANTINED_CLOSE_FDS.add(sentinel_fd)
        payload = runner_cli._service_status_payload(
            project_path=str(tmp_path),
            metadata=None,
            state="stopped",
            web_state=None,
            mcp_state=None,
            log_path=None,
            private_operator_runtime={
                "observation_source": "service_private_ipc",
                "observation_status": "observed",
                "quarantined_close_fd_count": 1,
                "quarantine_attention_threshold": 1,
                "quarantine_status": "attention",
                "local_alert_code": "OPERATOR_FD_QUARANTINE_ATTENTION",
            },
        )
        assert payload["private_operator_runtime"] == {
            "observation_source": "service_private_ipc",
            "observation_status": "observed",
            "quarantined_close_fd_count": 1,
            "quarantine_attention_threshold": 1,
            "quarantine_status": "attention",
            "local_alert_code": "OPERATOR_FD_QUARANTINE_ATTENTION",
        }
        runner_cli._print_private_operator_runtime_summary(payload["private_operator_runtime"])
        rendered = capsys.readouterr().err
        assert "quarantine_status=attention" in rendered
        assert "quarantined_close_fd_count=1" in rendered
        assert "alert=OPERATOR_FD_QUARANTINE_ATTENTION" in rendered
        assert str(sentinel_fd) not in json.dumps(payload) + rendered
    finally:
        with private_operator_module._ACTIVE_BATCHES_LOCK:
            private_operator_module._QUARANTINED_CLOSE_FDS.discard(sentinel_fd)


def test_operator_principal_requires_subject_and_unambiguous_client(tmp_path: Path) -> None:
    settings = _settings(tmp_path).load()["settings"]
    assert evaluate_operator_principal(_auth(), settings).allowed is True
    assert evaluate_operator_principal(_auth(subject="other"), settings).error_code == "OPERATOR_PRINCIPAL_DENIED"
    missing = _auth()
    missing["token"].pop("azp")
    missing["token"].pop("client_id")
    assert evaluate_operator_principal(missing, settings).error_code == "OPERATOR_CLIENT_CLAIM_MISSING"
    ambiguous = _auth()
    ambiguous["token"]["client_id"] = "different"
    assert evaluate_operator_principal(ambiguous, settings).error_code == "OPERATOR_CLIENT_CLAIM_AMBIGUOUS"


def test_operator_operations_are_allowlisted_scope_aware_and_preview_bound() -> None:
    operations = [
        {
            "step_id": "plan",
            "tool": "run_mcp_workflow",
            "params": {"workflow": "plan_update", "phase": "apply", "patch_id": "preview_0001"},
        },
        _commit_operation("commit", "preview_0002"),
    ]
    result = normalize_operator_operations(operations, max_steps=8, preview_validator=_validator)
    assert result["ok"] is True
    assert result["required_scopes"] == ["mcp:commit", "mcp:plan"]

    nested = [{
        "step_id": "nested",
        "tool": "run_mcp_workflow",
        "params": {"workflow": "operator_batch", "phase": "execute", "preview_id": "preview_0003"},
    }]
    assert normalize_operator_operations(nested, max_steps=8, preview_validator=_validator)["error_code"] == "OPERATOR_OPERATION_DENIED"

    async_not_last = [
        {
            "step_id": "run",
            "tool": "run_mcp_workflow",
            "params": {"workflow": "prompt_to_plan", "phase": "run", "preview_id": "preview_0004"},
        },
        _commit_operation("commit", "preview_0005"),
    ]
    assert normalize_operator_operations(async_not_last, max_steps=8, preview_validator=_validator)["error_code"] == "OPERATOR_ASYNC_STEP_NOT_LAST"

    project_override = [_commit_operation("commit", "preview_0006")]
    project_override[0]["params"]["project_name"] = "other"
    assert normalize_operator_operations(project_override, max_steps=8, preview_validator=_validator)["error_code"] == "OPERATOR_PROJECT_OVERRIDE_DENIED"

    private_input = [_commit_operation("commit", "preview_0007")]
    private_input[0]["params"]["access_token"] = "never-store-this"
    assert normalize_operator_operations(private_input, max_steps=8, preview_validator=_validator)["error_code"] == "OPERATOR_PRIVATE_INPUT_DENIED"


def test_operator_batch_is_single_use_and_public_response_is_allowlisted(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    permits = OperatorPermitStore(str(tmp_path / "config"))
    dispatched: list[tuple[str, dict]] = []

    def dispatch(_capability: object, tool: str, params: dict) -> dict:
        dispatched.append((tool, params))
        return {"ok": True, "project_root": "/must/not/escape", "token": "must-not-escape"}

    service = OperatorBatchService(
        settings_store=settings,
        permit_store=permits,
        preview_validator=_validator,
        dispatch=dispatch,
    )
    preview_params = {
        "workflow": "operator_batch",
        "phase": "preview",
        "project_name": "colameta-self-dev",
        "operations": [_commit_operation("commit", "preview_1001")],
    }
    with operator_authenticated_request_scope(_auth()):
        preview = service.handle("colameta-self-dev", preview_params)
        assert preview["ok"] is True
        execute = service.handle("colameta-self-dev", {
            "workflow": "operator_batch",
            "phase": "execute",
            "project_name": "colameta-self-dev",
            "batch_preview_id": preview["batch_preview_id"],
            "manifest_digest": preview["manifest_digest"],
        })
        replay = service.handle("colameta-self-dev", {
            "workflow": "operator_batch",
            "phase": "execute",
            "project_name": "colameta-self-dev",
            "batch_preview_id": preview["batch_preview_id"],
            "manifest_digest": preview["manifest_digest"],
        })
    assert execute["state"] == "consumed"
    assert execute["steps"] == [{"step_id": "commit", "status": "succeeded"}]
    assert set(execute) == {"ok", "batch_preview_id", "manifest_digest", "state", "steps", "expires_at"}
    assert replay["error_code"] == "OPERATOR_TICKET_NOT_PENDING"
    assert len(dispatched) == 1
    assert "project_root" not in json.dumps(execute)
    assert "token" not in json.dumps(execute)


def test_operator_batch_stops_after_first_failure_without_rollback(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    permits = OperatorPermitStore(str(tmp_path / "config"))
    calls = 0

    def dispatch(_capability: object, _tool: str, _params: dict) -> dict:
        nonlocal calls
        calls += 1
        return {"ok": calls == 1, "error_code": "CONTROLLED_FAILURE"}

    service = OperatorBatchService(
        settings_store=settings,
        permit_store=permits,
        preview_validator=_validator,
        dispatch=dispatch,
    )
    with operator_authenticated_request_scope(_auth()):
        preview = service.handle("project", {
            "workflow": "operator_batch",
            "phase": "preview",
            "project_name": "project",
            "operations": [
                _commit_operation("one", "preview_2001"),
                _commit_operation("two", "preview_2002"),
                _commit_operation("three", "preview_2003"),
            ],
        })
        result = service.handle("project", {
            "workflow": "operator_batch",
            "phase": "execute",
            "project_name": "project",
            "batch_preview_id": preview["batch_preview_id"],
            "manifest_digest": preview["manifest_digest"],
        })
    assert result["state"] == "failed"
    assert [step["status"] for step in result["steps"]] == ["succeeded", "failed", "not_started"]
    assert calls == 2


def test_operator_permit_claim_is_atomic_under_concurrency(tmp_path: Path) -> None:
    _settings_store, store, service = _matrix_service(tmp_path)
    preview = _matrix_preview(service, [_commit_operation("commit", "preview_2301")])
    expected_ticket = store.read(preview["batch_preview_id"])
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(
            lambda _unused: store.claim(
                preview["batch_preview_id"],
                expected_ticket=expected_ticket,
            ),
            range(2),
        ))
    assert sum(result.get("ok") is True for result in results) == 1
    assert sum(result.get("error_code") in {"OPERATOR_TICKET_ALREADY_CLAIMED", "OPERATOR_TICKET_NOT_PENDING"} for result in results) == 1
    private_operator_module._release_batch(preview["batch_preview_id"])


def test_claim_revalidates_expected_manifest_after_lock_before_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _settings_store, permits, service = _matrix_service(tmp_path)
    preview = _matrix_preview(service, [_commit_operation("commit", "preview_2302")])
    expected_ticket = permits.read(preview["batch_preview_id"])
    altered_ticket = json.loads(json.dumps(expected_ticket))
    altered_ticket["operations"][0]["params"]["preview_id"] = "preview_replaced_2302"
    altered_ticket["operations"][0]["preview_id"] = "preview_replaced_2302"
    altered_ticket["operations"][0]["preview_digest"] = "b" * 64
    altered_ticket["manifest_digest"] = private_operator_module._manifest_digest(
        private_operator_module._ticket_manifest(altered_ticket)
    )
    assert validate_operator_ticket(altered_ticket)["ok"] is True
    dispatch_calls: list[str] = []
    service.dispatch = lambda _capability, _tool, _params: (
        dispatch_calls.append("dispatch") or {"ok": True}
    )
    real_read_locked = permits._read_ticket_from_root_fd
    reads = 0

    def replace_before_locked_read(root_fd: int, batch_id: str) -> dict | None:
        nonlocal reads
        reads += 1
        if reads == 3:
            assert permits.update(altered_ticket) is True
        return real_read_locked(root_fd, batch_id)

    monkeypatch.setattr(permits, "_read_ticket_from_root_fd", replace_before_locked_read)
    result = _matrix_execute(service, preview)

    assert result == {
        "ok": False,
        "error_code": "OPERATOR_TICKET_CHANGED",
        "message": "Operator request was denied.",
    }
    assert dispatch_calls == []
    assert permits.is_indeterminate(preview["batch_preview_id"]) is True


def test_claim_freezes_expected_ticket_before_first_permit_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _settings_store, permits, service = _matrix_service(tmp_path)
    preview = _matrix_preview(service, [_commit_operation("commit", "preview_2302a")])
    expected_ticket = permits.read(preview["batch_preview_id"])
    real_read = permits._read_ticket_from_root_fd
    mutated = False

    def mutate_caller_after_entry(root_fd: int, batch_id: str) -> dict | None:
        nonlocal mutated
        if not mutated:
            mutated = True
            expected_ticket["caller_mutation"] = True
        return real_read(root_fd, batch_id)

    monkeypatch.setattr(permits, "_read_ticket_from_root_fd", mutate_caller_after_entry)
    result = permits.claim(
        preview["batch_preview_id"],
        expected_ticket=expected_ticket,
    )

    assert result["ok"] is True
    assert "caller_mutation" not in result["ticket"]
    private_operator_module._release_batch(preview["batch_preview_id"])


@pytest.mark.skipif(os.name != "posix", reason="descriptor lifecycle assertion requires POSIX")
def test_claim_rejection_closes_pinned_root_descriptor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _settings_store, permits, service = _matrix_service(tmp_path)
    preview = _matrix_preview(service, [_commit_operation("commit", "preview_2302b")])
    expected_ticket = permits.read(preview["batch_preview_id"])
    altered_ticket = json.loads(json.dumps(expected_ticket))
    altered_ticket["created_at"] = (
        private_operator_module._parse_iso(altered_ticket["created_at"])
        - timedelta(seconds=1)
    ).isoformat()
    assert validate_operator_ticket(altered_ticket)["ok"] is True
    root_fd = os.open(permits.root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    monkeypatch.setattr(permits, "_open_root_dir_fd", lambda: root_fd)
    monkeypatch.setattr(
        permits,
        "_read_ticket_from_root_fd",
        lambda _root_fd, _batch_id: altered_ticket,
    )

    result = permits.claim(
        preview["batch_preview_id"],
        expected_ticket=expected_ticket,
    )

    assert result["error_code"] == "OPERATOR_TICKET_CHANGED"
    with pytest.raises(OSError):
        os.fstat(root_fd)


@pytest.mark.skipif(os.name != "posix", reason="dirfd race hardening requires POSIX")
def test_ticket_read_stays_bound_to_opened_root_dirfd_during_path_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _settings_store, permits, service = _matrix_service(tmp_path)
    preview = _matrix_preview(service, [_commit_operation("commit", "preview_2303")])
    expected = permits.read(preview["batch_preview_id"])
    root = Path(permits.root)
    relocated = root.with_name("operator-permits-original")
    ticket_name = permits._ticket_name(preview["batch_preview_id"])
    real_open = os.open
    swapped = False

    def swap_root_before_leaf_open(
        path: str,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        if path == ticket_name and dir_fd is not None and not swapped:
            swapped = True
            root.rename(relocated)
            root.mkdir(mode=0o700)
            forged = root / ticket_name
            forged.write_text(json.dumps({"forged": True}), encoding="utf-8")
            forged.chmod(0o600)
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", swap_root_before_leaf_open)
    observed = permits.read(preview["batch_preview_id"])

    assert swapped is True
    assert observed == expected
    assert observed.get("forged") is None


@pytest.mark.skipif(os.name != "posix", reason="dirfd race hardening requires POSIX")
def test_ticket_create_stays_bound_to_created_root_dirfd_during_path_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _settings_store, permits, service = _matrix_service(tmp_path)
    root = Path(permits.root)
    relocated = root.with_name("operator-permits-created-original")
    real_open_name_at = permits._open_name_at
    swapped = False

    def swap_before_ticket_create(
        root_fd: int,
        name: str,
        flags: int,
        mode: int = 0o600,
    ) -> int:
        nonlocal swapped
        if name.endswith(".json") and not swapped:
            swapped = True
            root.rename(relocated)
            root.mkdir(mode=0o700)
        return real_open_name_at(root_fd, name, flags, mode)

    monkeypatch.setattr(permits, "_open_name_at", swap_before_ticket_create)
    preview = _matrix_preview(service, [_commit_operation("commit", "preview_2303a")])

    assert swapped is True
    assert (relocated / permits._ticket_name(preview["batch_preview_id"])).is_file()
    assert list(root.iterdir()) == []


@pytest.mark.skipif(os.name != "posix", reason="dirfd race hardening requires POSIX")
def test_execute_updates_stay_on_claimed_root_after_post_lock_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _settings_store, permits, service = _matrix_service(tmp_path)
    preview = _matrix_preview(service, [_commit_operation("commit", "preview_2303b")])
    root = Path(permits.root)
    relocated = root.with_name("operator-permits-claimed-original")
    real_read = permits._read_ticket_from_root_fd
    reads = 0

    def swap_after_claim_lock(root_fd: int, batch_id: str) -> dict | None:
        nonlocal reads
        reads += 1
        if reads == 3:
            root.rename(relocated)
            root.mkdir(mode=0o700)
        return real_read(root_fd, batch_id)

    monkeypatch.setattr(permits, "_read_ticket_from_root_fd", swap_after_claim_lock)
    result = _matrix_execute(service, preview)
    durable = json.loads(
        (relocated / permits._ticket_name(preview["batch_preview_id"])).read_text(
            encoding="utf-8"
        )
    )

    assert reads >= 3
    assert result["state"] == "consumed"
    assert durable["state"] == "consumed"
    assert list(root.iterdir()) == []


@pytest.mark.skipif(os.name != "posix", reason="dirfd race hardening requires POSIX")
def test_poison_stays_on_claimed_root_after_post_lock_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _settings_store, permits, service = _matrix_service(
        tmp_path,
        dispatch=lambda _capability, _tool, _params: (_ for _ in ()).throw(
            RuntimeError("simulated executor failure")
        ),
    )
    preview = _matrix_preview(service, [_commit_operation("commit", "preview_2303c")])
    root = Path(permits.root)
    relocated = root.with_name("operator-permits-poison-original")
    real_read = permits._read_ticket_from_root_fd
    reads = 0

    def swap_after_claim_lock(root_fd: int, batch_id: str) -> dict | None:
        nonlocal reads
        reads += 1
        if reads == 3:
            root.rename(relocated)
            root.mkdir(mode=0o700)
        return real_read(root_fd, batch_id)

    monkeypatch.setattr(permits, "_read_ticket_from_root_fd", swap_after_claim_lock)
    result = _matrix_execute(service, preview)
    durable = json.loads(
        (relocated / permits._ticket_name(preview["batch_preview_id"])).read_text(
            encoding="utf-8"
        )
    )

    assert result["error_code"] == "OPERATOR_EXECUTION_INDETERMINATE"
    assert durable["state"] == "indeterminate"
    assert (relocated / permits._poison_name(preview["batch_preview_id"])).is_file()
    assert list(root.iterdir()) == []


def test_ticket_and_claim_leaf_symlinks_fail_closed(tmp_path: Path) -> None:
    _settings_store, permits, service = _matrix_service(tmp_path)
    preview = _matrix_preview(service, [_commit_operation("commit", "preview_2304")])
    batch_id = preview["batch_preview_id"]
    ticket_path = Path(permits._ticket_path(batch_id))
    backing_ticket = ticket_path.with_suffix(".backing")
    ticket_path.rename(backing_ticket)
    ticket_path.symlink_to(backing_ticket.name)

    assert permits.read(batch_id) is None

    ticket_path.unlink()
    backing_ticket.rename(ticket_path)
    claim_path = Path(permits._claim_path(batch_id))
    claim_path.symlink_to(ticket_path.name)
    assert permits.has_claim(batch_id) is False
    assert permits.claim_is_live(batch_id) is True


def test_operator_permit_root_with_broad_permissions_fails_closed(tmp_path: Path) -> None:
    permits = OperatorPermitStore(str(tmp_path / "config"))
    root = Path(permits.root)
    root.mkdir(parents=True, mode=0o700)
    root.chmod(0o755)

    with pytest.raises(OSError, match="unsafe operator permit root"):
        permits._ensure_root()

    if os.name == "posix":
        assert stat.S_IMODE(root.stat().st_mode) == 0o755


def test_operator_permit_access_rejects_symlink_ancestor(tmp_path: Path) -> None:
    _settings_store, permits, service = _matrix_service(tmp_path / "actual")
    preview = _matrix_preview(service, [_commit_operation("commit", "preview_2349")])
    alias = tmp_path / "alias"
    alias.symlink_to(tmp_path / "actual" / "config", target_is_directory=True)
    aliased_store = OperatorPermitStore(str(alias))

    assert aliased_store.read(preview["batch_preview_id"]) is None
    assert aliased_store.has_claim(preview["batch_preview_id"]) is False
    assert aliased_store.update(permits.read(preview["batch_preview_id"])) is False


def test_operator_permit_store_fails_closed_without_posix_dirfd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _settings_store, permits, service = _matrix_service(tmp_path)
    preview = _matrix_preview(service, [_commit_operation("commit", "preview_2349a")])
    ticket = permits.read(preview["batch_preview_id"])

    with monkeypatch.context() as scoped:
        scoped.setattr(private_operator_module.os, "name", "nt")
        read_result = permits.read(preview["batch_preview_id"])
        update_result = permits.update(ticket)
        poison_result = permits.mark_indeterminate(ticket)
        claim_result = permits.claim(
            preview["batch_preview_id"],
            expected_ticket=ticket,
        )
        with pytest.raises(OSError, match="dirfd operations are unsupported"):
            permits._ensure_root()

    assert read_result is None
    assert update_result is False
    assert poison_result is False
    assert claim_result["error_code"] == "OPERATOR_PERMIT_UNSAFE"


@pytest.mark.skipif(os.name != "posix", reason="descriptor lifecycle assertion requires POSIX")
def test_permit_operations_close_each_opened_descriptor_or_transfer_it_to_batch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _settings_store, permits, service = _matrix_service(tmp_path)
    real_open = os.open
    real_close = os.close
    live_fds: set[int] = set()

    def tracked_open(*args: object, **kwargs: object) -> int:
        fd = real_open(*args, **kwargs)
        live_fds.add(fd)
        return fd

    def tracked_close(fd: int) -> None:
        real_close(fd)
        live_fds.discard(fd)

    monkeypatch.setattr(os, "open", tracked_open)
    monkeypatch.setattr(os, "close", tracked_close)
    with monkeypatch.context() as scoped:
        scoped.setattr(
            permits,
            "_write_all",
            lambda _fd, _data: (_ for _ in ()).throw(OSError("simulated create failure")),
        )
        with pytest.raises(OSError, match="simulated create failure"):
            _matrix_preview(service, [_commit_operation("commit", "preview_2349b0")])
    assert live_fds == set()
    assert list(Path(permits.root).glob("*.json")) == []

    preview = _matrix_preview(service, [_commit_operation("commit", "preview_2349b")])
    assert live_fds == set()
    ticket = permits.read(preview["batch_preview_id"])
    assert live_fds == set()
    assert permits.update(ticket) is True
    assert live_fds == set()

    claimed = permits.claim(preview["batch_preview_id"], expected_ticket=ticket)
    assert claimed["ok"] is True
    with private_operator_module._ACTIVE_BATCHES_LOCK:
        transferred = {
            private_operator_module._ACTIVE_CLAIM_FDS[preview["batch_preview_id"]],
            private_operator_module._ACTIVE_ROOT_FDS[preview["batch_preview_id"]],
        }
    assert live_fds == transferred
    assert permits.mark_indeterminate(claimed["ticket"]) is True
    assert live_fds == transferred
    private_operator_module._release_batch(preview["batch_preview_id"])
    assert live_fds == set()


@pytest.mark.skipif(os.name != "posix", reason="descriptor lifecycle assertion requires POSIX")
def test_release_batch_attempts_root_close_when_claim_close_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _settings_store, permits, service = _matrix_service(tmp_path)
    preview = _matrix_preview(service, [_commit_operation("commit", "preview_2349b1")])
    result = _claim_ticket(permits, preview["batch_preview_id"])
    assert result["ok"] is True
    batch_id = preview["batch_preview_id"]
    with private_operator_module._ACTIVE_BATCHES_LOCK:
        claim_fd = private_operator_module._ACTIVE_CLAIM_FDS[batch_id]
        root_fd = private_operator_module._ACTIVE_ROOT_FDS[batch_id]
    real_close = os.close
    close_attempts: list[int] = []

    def fail_claim_close(fd: int) -> None:
        close_attempts.append(fd)
        if fd == claim_fd:
            raise OSError("simulated claim close failure")
        real_close(fd)

    with monkeypatch.context() as scoped:
        scoped.setattr(os, "close", fail_claim_close)
        private_operator_module._release_batch(batch_id)

    assert claim_fd in close_attempts
    assert root_fd in close_attempts
    with private_operator_module._ACTIVE_BATCHES_LOCK:
        assert claim_fd in private_operator_module._QUARANTINED_CLOSE_FDS
    with pytest.raises(OSError):
        os.fstat(root_fd)
    os.fstat(claim_fd)
    real_close(claim_fd)
    with private_operator_module._ACTIVE_BATCHES_LOCK:
        private_operator_module._QUARANTINED_CLOSE_FDS.discard(claim_fd)


@pytest.mark.skipif(os.name != "posix", reason="descriptor lifecycle assertion requires POSIX")
def test_service_claim_handoff_baseexception_releases_registered_descriptors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _settings_store, permits, service = _matrix_service(tmp_path)
    preview = _matrix_preview(service, [_commit_operation("commit", "preview_2349b2")])
    batch_id = preview["batch_preview_id"]
    real_open = os.open
    real_close = os.close
    live_fds: set[int] = set()

    def tracked_open(*args: object, **kwargs: object) -> int:
        fd = real_open(*args, **kwargs)
        live_fds.add(fd)
        return fd

    def tracked_close(fd: int) -> None:
        real_close(fd)
        live_fds.discard(fd)

    def interrupt_before_execution(_ticket: dict) -> dict:
        raise KeyboardInterrupt("simulated service handoff interruption")

    monkeypatch.setattr(os, "open", tracked_open)
    monkeypatch.setattr(os, "close", tracked_close)
    monkeypatch.setattr(service, "_execute_registered_claim", interrupt_before_execution)
    with pytest.raises(KeyboardInterrupt, match="handoff interruption"):
        _matrix_execute(service, preview)

    assert live_fds == set()
    with private_operator_module._ACTIVE_BATCHES_LOCK:
        assert batch_id not in private_operator_module._ACTIVE_BATCHES
        assert batch_id not in private_operator_module._ACTIVE_CLAIM_FDS
        assert batch_id not in private_operator_module._ACTIVE_ROOT_FDS


@pytest.mark.skipif(os.name != "posix", reason="descriptor lifecycle assertion requires POSIX")
def test_root_walk_baseexception_closes_current_directory_descriptor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _settings_store, permits, _service = _matrix_service(tmp_path)
    real_open = os.open
    opened_root_fd: int | None = None
    interrupted = False

    def interrupt_first_component(
        path: str,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal opened_root_fd, interrupted
        if dir_fd is not None and not interrupted:
            interrupted = True
            raise KeyboardInterrupt("simulated root walk interruption")
        fd = real_open(path, flags, mode, dir_fd=dir_fd)
        if path == os.path.sep and dir_fd is None:
            opened_root_fd = fd
        return fd

    monkeypatch.setattr(os, "open", interrupt_first_component)
    with pytest.raises(KeyboardInterrupt, match="root walk interruption"):
        permits._open_root_dir_fd()

    assert opened_root_fd is not None
    with pytest.raises(OSError):
        os.fstat(opened_root_fd)


@pytest.mark.parametrize(
    "fault",
    ["mkdir", "chmod", "stat", "final_open"],
)
@pytest.mark.skipif(os.name != "posix", reason="dirfd syscall injection requires POSIX")
def test_root_creation_syscall_failures_close_all_directory_descriptors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    _settings_store, permits, _service = _matrix_service(tmp_path)
    live_fds, _real_open, _real_close = _track_os_descriptors(monkeypatch)
    tracked_open = os.open
    real_mkdir = os.mkdir
    real_chmod = os.chmod
    real_stat = os.stat
    final_open_calls = 0

    if fault == "mkdir":
        monkeypatch.setattr(
            os,
            "mkdir",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("mkdir failed")),
        )
    elif fault == "chmod":
        def fail_final_chmod(*args: object, **kwargs: object) -> None:
            if args and args[0] == "operator-permits":
                raise OSError("chmod failed")
            real_chmod(*args, **kwargs)

        monkeypatch.setattr(os, "chmod", fail_final_chmod)
    elif fault == "stat":
        def fail_final_stat(*args: object, **kwargs: object) -> os.stat_result:
            if args and args[0] == "operator-permits":
                raise OSError("stat failed")
            return real_stat(*args, **kwargs)

        monkeypatch.setattr(os, "stat", fail_final_stat)
    else:
        def fail_second_final_open(*args: object, **kwargs: object) -> int:
            nonlocal final_open_calls
            if args and args[0] == "operator-permits":
                final_open_calls += 1
                if final_open_calls == 2:
                    raise OSError("final open failed")
            return tracked_open(*args, **kwargs)

        monkeypatch.setattr(os, "open", fail_second_final_open)

    with pytest.raises(OSError):
        permits._ensure_root_fd()

    assert live_fds == set()


@pytest.mark.parametrize(
    "fault",
    ["leaf_open", "fchmod", "write", "file_fsync", "root_fsync", "cleanup_unlink"],
)
@pytest.mark.skipif(os.name != "posix", reason="dirfd syscall injection requires POSIX")
def test_ticket_create_syscall_failure_matrix_is_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    _settings_store, permits, service = _matrix_service(tmp_path)
    permits._ensure_root()
    live_fds, _real_open, _real_close = _track_os_descriptors(monkeypatch)
    real_open_name = permits._open_name_at
    real_fchmod = os.fchmod
    real_fsync = os.fsync
    real_unlink = os.unlink

    if fault == "leaf_open":
        monkeypatch.setattr(
            permits,
            "_open_name_at",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("leaf open failed")),
        )
    elif fault == "fchmod":
        monkeypatch.setattr(
            os,
            "fchmod",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("fchmod failed")),
        )
    elif fault in {"write", "cleanup_unlink"}:
        monkeypatch.setattr(
            permits,
            "_write_all",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("write failed")),
        )
        if fault == "cleanup_unlink":
            monkeypatch.setattr(
                os,
                "unlink",
                lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("unlink failed")),
            )
    else:
        def fail_selected_fsync(fd: int) -> None:
            is_directory = stat.S_ISDIR(os.fstat(fd).st_mode)
            if (fault == "root_fsync" and is_directory) or (
                fault == "file_fsync" and not is_directory
            ):
                raise OSError(f"{fault} failed")
            real_fsync(fd)

        monkeypatch.setattr(os, "fsync", fail_selected_fsync)

    with pytest.raises(OSError):
        _matrix_preview(service, [_commit_operation("commit", f"preview_create_{fault}")])

    assert live_fds == set()
    tickets = list(Path(permits.root).glob("*.json"))
    assert len(tickets) == (1 if fault == "cleanup_unlink" else 0)
    monkeypatch.setattr(permits, "_open_name_at", real_open_name)
    monkeypatch.setattr(os, "fchmod", real_fchmod)
    monkeypatch.setattr(os, "fsync", real_fsync)
    monkeypatch.setattr(os, "unlink", real_unlink)


@pytest.mark.parametrize(
    "fault",
    ["temp_open", "fchmod", "write", "file_fsync", "rename", "root_fsync", "cleanup_unlink"],
)
@pytest.mark.skipif(os.name != "posix", reason="dirfd syscall injection requires POSIX")
def test_ticket_update_syscall_failure_matrix_is_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    _settings_store, permits, service = _matrix_service(tmp_path)
    preview = _matrix_preview(service, [_commit_operation("commit", f"preview_update_{fault}")])
    ticket = permits.read(preview["batch_preview_id"])
    live_fds, _real_open, _real_close = _track_os_descriptors(monkeypatch)
    real_open_name = permits._open_name_at
    real_fchmod = os.fchmod
    real_write_all = permits._write_all
    real_fsync = os.fsync
    real_rename = os.rename
    real_unlink = os.unlink

    if fault == "temp_open":
        def fail_temp_open(root_fd: int, name: str, flags: int, mode: int = 0o600) -> int:
            if name.startswith("."):
                raise OSError("temp open failed")
            return real_open_name(root_fd, name, flags, mode)

        monkeypatch.setattr(permits, "_open_name_at", fail_temp_open)
    elif fault == "fchmod":
        monkeypatch.setattr(
            os,
            "fchmod",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("fchmod failed")),
        )
    elif fault == "write":
        monkeypatch.setattr(
            permits,
            "_write_all",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("write failed")),
        )
    elif fault in {"rename", "cleanup_unlink"}:
        monkeypatch.setattr(
            os,
            "rename",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("rename failed")),
        )
        if fault == "cleanup_unlink":
            monkeypatch.setattr(
                os,
                "unlink",
                lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("unlink failed")),
            )
    else:
        def fail_selected_fsync(fd: int) -> None:
            is_directory = stat.S_ISDIR(os.fstat(fd).st_mode)
            if (fault == "root_fsync" and is_directory) or (
                fault == "file_fsync" and not is_directory
            ):
                raise OSError(f"{fault} failed")
            real_fsync(fd)

        monkeypatch.setattr(os, "fsync", fail_selected_fsync)

    assert permits.update(ticket) is False
    assert live_fds == set()
    temporary_files = list(Path(permits.root).glob(".*.tmp"))
    assert len(temporary_files) == (1 if fault == "cleanup_unlink" else 0)

    monkeypatch.setattr(permits, "_open_name_at", real_open_name)
    monkeypatch.setattr(os, "fchmod", real_fchmod)
    monkeypatch.setattr(permits, "_write_all", real_write_all)
    monkeypatch.setattr(os, "fsync", real_fsync)
    monkeypatch.setattr(os, "rename", real_rename)
    monkeypatch.setattr(os, "unlink", real_unlink)


@pytest.mark.parametrize(
    "fault",
    [
        "claim_open",
        "fchmod",
        "flock",
        "write",
        "claim_fsync",
        "root_fsync",
        "locked_read",
        "claimed_update",
    ],
)
@pytest.mark.skipif(
    os.name != "posix" or private_operator_module.fcntl is None,
    reason="claim syscall injection requires POSIX flock",
)
def test_claim_syscall_failure_matrix_releases_every_descriptor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    _settings_store, permits, service = _matrix_service(tmp_path)
    preview = _matrix_preview(service, [_commit_operation("commit", f"preview_claim_{fault}")])
    batch_id = preview["batch_preview_id"]
    expected_ticket = permits.read(batch_id)
    live_fds, _real_open, _real_close = _track_os_descriptors(monkeypatch)
    real_open_root = permits._open_root_dir_fd
    real_open_name = permits._open_name_at
    real_fchmod = os.fchmod
    real_flock = private_operator_module.fcntl.flock
    real_write_all = permits._write_all
    real_fsync = os.fsync
    real_read_ticket = permits._read_ticket_from_root_fd
    claim_fd: int | None = None
    root_fd: int | None = None
    root_fsync_failed = False
    reads = 0

    def capture_root() -> int:
        nonlocal root_fd
        root_fd = real_open_root()
        return root_fd

    def capture_or_fail_claim(
        opened_root_fd: int,
        name: str,
        flags: int,
        mode: int = 0o600,
    ) -> int:
        nonlocal claim_fd
        if name == permits._claim_name(batch_id):
            if fault == "claim_open":
                raise OSError("claim open failed")
            claim_fd = real_open_name(opened_root_fd, name, flags, mode)
            return claim_fd
        return real_open_name(opened_root_fd, name, flags, mode)

    def fail_claim_fchmod(fd: int, mode: int) -> None:
        if fault == "fchmod" and fd == claim_fd:
            raise OSError("claim fchmod failed")
        real_fchmod(fd, mode)

    def fail_claim_flock(fd: int, operation: int) -> None:
        if (
            fault == "flock"
            and fd == claim_fd
            and operation & private_operator_module.fcntl.LOCK_EX
        ):
            raise OSError("claim flock failed")
        real_flock(fd, operation)

    def fail_claim_write(fd: int, data: bytes) -> None:
        if fault == "write" and fd == claim_fd:
            raise OSError("claim write failed")
        real_write_all(fd, data)

    def fail_claim_fsync(fd: int) -> None:
        nonlocal root_fsync_failed
        if fault == "claim_fsync" and fd == claim_fd:
            raise OSError("claim fsync failed")
        if fault == "root_fsync" and fd == root_fd and not root_fsync_failed:
            root_fsync_failed = True
            raise OSError("root fsync failed")
        real_fsync(fd)

    def fail_locked_read(opened_root_fd: int, observed_batch_id: str) -> dict | None:
        nonlocal reads
        reads += 1
        if fault == "locked_read" and reads == 2:
            raise KeyboardInterrupt("locked read interrupted")
        return real_read_ticket(opened_root_fd, observed_batch_id)

    monkeypatch.setattr(permits, "_open_root_dir_fd", capture_root)
    monkeypatch.setattr(permits, "_open_name_at", capture_or_fail_claim)
    monkeypatch.setattr(os, "fchmod", fail_claim_fchmod)
    monkeypatch.setattr(private_operator_module.fcntl, "flock", fail_claim_flock)
    monkeypatch.setattr(permits, "_write_all", fail_claim_write)
    monkeypatch.setattr(os, "fsync", fail_claim_fsync)
    monkeypatch.setattr(permits, "_read_ticket_from_root_fd", fail_locked_read)
    if fault == "claimed_update":
        monkeypatch.setattr(permits, "_update_from_root_fd", lambda _fd, _ticket: False)

    if fault in {"claim_open", "claimed_update"}:
        result = permits.claim(batch_id, expected_ticket=expected_ticket)
        assert result["ok"] is False
    else:
        with pytest.raises((OSError, KeyboardInterrupt)):
            permits.claim(batch_id, expected_ticket=expected_ticket)

    assert live_fds == set()
    with private_operator_module._ACTIVE_BATCHES_LOCK:
        assert batch_id not in private_operator_module._ACTIVE_BATCHES
        assert batch_id not in private_operator_module._ACTIVE_CLAIM_FDS
        assert batch_id not in private_operator_module._ACTIVE_ROOT_FDS
        assert private_operator_module._QUARANTINED_CLOSE_FDS == set()


@pytest.mark.parametrize(
    "fault",
    ["poison_open", "fchmod", "write", "file_fsync", "root_fsync", "ticket_update"],
)
@pytest.mark.skipif(os.name != "posix", reason="poison syscall injection requires POSIX")
def test_poison_syscall_failure_matrix_preserves_fail_closed_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    _settings_store, permits, service = _matrix_service(tmp_path)
    preview = _matrix_preview(service, [_commit_operation("commit", f"preview_poison_{fault}")])
    batch_id = preview["batch_preview_id"]
    ticket = permits.read(batch_id)
    live_fds, _real_open, _real_close = _track_os_descriptors(monkeypatch)
    real_open_root = permits._open_root_dir_fd
    real_open_name = permits._open_name_at
    real_fchmod = os.fchmod
    real_write_all = permits._write_all
    real_fsync = os.fsync
    poison_fd: int | None = None
    fd_roles: dict[int, str] = {}
    root_fd: int | None = None
    root_fsync_failed = False

    def capture_root() -> int:
        nonlocal root_fd
        root_fd = real_open_root()
        return root_fd

    def capture_or_fail_poison(
        opened_root_fd: int,
        name: str,
        flags: int,
        mode: int = 0o600,
    ) -> int:
        nonlocal poison_fd
        if name == permits._poison_name(batch_id):
            if fault == "poison_open":
                raise OSError("poison open failed")
            poison_fd = real_open_name(opened_root_fd, name, flags, mode)
            fd_roles[poison_fd] = "poison"
            return poison_fd
        opened_fd = real_open_name(opened_root_fd, name, flags, mode)
        fd_roles[opened_fd] = "other"
        return opened_fd

    def fail_poison_fchmod(fd: int, mode: int) -> None:
        if fault == "fchmod" and fd_roles.get(fd) == "poison":
            raise OSError("poison fchmod failed")
        real_fchmod(fd, mode)

    def fail_poison_write(fd: int, data: bytes) -> None:
        if fault == "write" and fd_roles.get(fd) == "poison":
            raise OSError("poison write failed")
        real_write_all(fd, data)

    def fail_poison_fsync(fd: int) -> None:
        nonlocal root_fsync_failed
        if fault == "file_fsync" and fd_roles.get(fd) == "poison":
            raise OSError("poison file fsync failed")
        if fault == "root_fsync" and fd == root_fd and not root_fsync_failed:
            root_fsync_failed = True
            raise OSError("poison root fsync failed")
        real_fsync(fd)

    monkeypatch.setattr(permits, "_open_root_dir_fd", capture_root)
    monkeypatch.setattr(permits, "_open_name_at", capture_or_fail_poison)
    monkeypatch.setattr(os, "fchmod", fail_poison_fchmod)
    monkeypatch.setattr(permits, "_write_all", fail_poison_write)
    monkeypatch.setattr(os, "fsync", fail_poison_fsync)
    if fault == "ticket_update":
        monkeypatch.setattr(permits, "_update_from_root_fd", lambda _fd, _ticket: False)

    durable = permits.mark_indeterminate(ticket)

    assert durable is (fault == "ticket_update")
    assert live_fds == set()
    assert Path(permits._poison_path(batch_id)).exists() is (fault != "poison_open")
    persisted = permits.read(batch_id)
    assert persisted["state"] == ("pending" if fault == "ticket_update" else "indeterminate")


@pytest.mark.parametrize("fault", ["unlock", "claim_close", "root_close"])
@pytest.mark.skipif(
    os.name != "posix" or private_operator_module.fcntl is None,
    reason="release syscall injection requires POSIX flock",
)
def test_release_syscall_failure_matrix_retains_private_quarantine_count(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    _settings_store, permits, service = _matrix_service(tmp_path)
    preview = _matrix_preview(service, [_commit_operation("commit", f"preview_release_{fault}")])
    batch_id = preview["batch_preview_id"]
    assert _claim_ticket(permits, batch_id)["ok"] is True
    with private_operator_module._ACTIVE_BATCHES_LOCK:
        claim_fd = private_operator_module._ACTIVE_CLAIM_FDS[batch_id]
        root_fd = private_operator_module._ACTIVE_ROOT_FDS[batch_id]
    real_flock = private_operator_module.fcntl.flock
    real_close = os.close
    quarantined_fd = claim_fd if fault == "claim_close" else root_fd

    def fail_unlock(fd: int, operation: int) -> None:
        if fault == "unlock" and operation & private_operator_module.fcntl.LOCK_UN:
            raise KeyboardInterrupt("unlock interrupted")
        real_flock(fd, operation)

    def fail_selected_close(fd: int) -> None:
        if fault in {"claim_close", "root_close"} and fd == quarantined_fd:
            raise OSError(f"{fault} failed")
        real_close(fd)

    with monkeypatch.context() as scoped:
        scoped.setattr(private_operator_module.fcntl, "flock", fail_unlock)
        scoped.setattr(os, "close", fail_selected_close)
        private_operator_module._release_batch(batch_id)

    counters = private_operator_module._private_operator_runtime_counters()
    assert counters == {
        "quarantined_close_fd_count": 0 if fault == "unlock" else 1,
    }
    counters["quarantined_close_fd_count"] = 999
    assert private_operator_module._private_operator_runtime_counters()[
        "quarantined_close_fd_count"
    ] == (0 if fault == "unlock" else 1)
    with private_operator_module._ACTIVE_BATCHES_LOCK:
        assert batch_id not in private_operator_module._ACTIVE_BATCHES
        assert batch_id not in private_operator_module._ACTIVE_CLAIM_FDS
        assert batch_id not in private_operator_module._ACTIVE_ROOT_FDS
    if fault != "unlock":
        os.fstat(quarantined_fd)
        real_close(quarantined_fd)
        with private_operator_module._ACTIVE_BATCHES_LOCK:
            private_operator_module._QUARANTINED_CLOSE_FDS.discard(quarantined_fd)
    assert private_operator_module._private_operator_runtime_counters() == {
        "quarantined_close_fd_count": 0,
    }


@pytest.mark.parametrize(
    "exit_edge",
    ["claim_exists", "claim_update_failure", "post_registration_exception"],
)
@pytest.mark.skipif(os.name != "posix", reason="descriptor lifecycle assertion requires POSIX")
def test_claim_exit_edges_release_every_owned_descriptor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    exit_edge: str,
) -> None:
    _settings_store, permits, service = _matrix_service(tmp_path)
    preview = _matrix_preview(service, [_commit_operation("commit", "preview_2349c")])
    batch_id = preview["batch_preview_id"]
    ticket = permits.read(batch_id)
    if exit_edge == "claim_exists":
        claim_path = Path(permits._claim_path(batch_id))
        claim_path.write_text("pid=1\n", encoding="ascii")
        claim_path.chmod(0o600)
    elif exit_edge == "claim_update_failure":
        monkeypatch.setattr(permits, "_update_from_root_fd", lambda _fd, _ticket: False)
    else:
        real_register = permits._register_active_claim

        def register_then_fail(batch: str, claim_fd: int, root_fd: int) -> None:
            real_register(batch, claim_fd, root_fd)
            raise RuntimeError("simulated post-registration failure")

        monkeypatch.setattr(permits, "_register_active_claim", register_then_fail)

    real_open = os.open
    real_close = os.close
    live_fds: set[int] = set()

    def tracked_open(*args: object, **kwargs: object) -> int:
        fd = real_open(*args, **kwargs)
        live_fds.add(fd)
        return fd

    def tracked_close(fd: int) -> None:
        real_close(fd)
        live_fds.discard(fd)

    monkeypatch.setattr(os, "open", tracked_open)
    monkeypatch.setattr(os, "close", tracked_close)
    if exit_edge == "post_registration_exception":
        with pytest.raises(RuntimeError, match="post-registration"):
            permits.claim(batch_id, expected_ticket=ticket)
    else:
        result = permits.claim(batch_id, expected_ticket=ticket)
        assert result["ok"] is False

    assert live_fds == set()
    with private_operator_module._ACTIVE_BATCHES_LOCK:
        assert batch_id not in private_operator_module._ACTIVE_BATCHES
        assert batch_id not in private_operator_module._ACTIVE_CLAIM_FDS
        assert batch_id not in private_operator_module._ACTIVE_ROOT_FDS


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode enforcement")
def test_new_ticket_and_claim_modes_ignore_restrictive_umask(tmp_path: Path) -> None:
    _settings_store, permits, service = _matrix_service(tmp_path)
    previous_umask = os.umask(0o777)
    try:
        preview = _matrix_preview(service, [_commit_operation("commit", "preview_2350")])
        claimed = _claim_ticket(permits, preview["batch_preview_id"])
    finally:
        os.umask(previous_umask)

    assert claimed["ok"] is True
    ticket_path = Path(permits._ticket_path(preview["batch_preview_id"]))
    claim_path = Path(permits._claim_path(preview["batch_preview_id"]))
    assert stat.S_IMODE(ticket_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(claim_path.stat().st_mode) == 0o600
    private_operator_module._release_batch(preview["batch_preview_id"])


@pytest.mark.skipif(os.name != "posix", reason="directory fsync requires POSIX")
def test_permit_ticket_claim_update_and_poison_fsync_parent_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _settings_store, permits, service = _matrix_service(tmp_path)
    directory_fsync_calls = 0
    real_fsync = os.fsync

    def observed_fsync(fd: int) -> None:
        nonlocal directory_fsync_calls
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            directory_fsync_calls += 1
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", observed_fsync)
    preview = _matrix_preview(service, [_commit_operation("commit", "preview_2350b")])
    after_ticket_create = directory_fsync_calls
    assert after_ticket_create >= 1

    claimed = _claim_ticket(permits, preview["batch_preview_id"])
    assert claimed["ok"] is True
    after_claim_and_ticket_update = directory_fsync_calls
    assert after_claim_and_ticket_update >= after_ticket_create + 2

    assert permits.mark_indeterminate(claimed["ticket"]) is True
    assert directory_fsync_calls >= after_claim_and_ticket_update + 2
    private_operator_module._release_batch(preview["batch_preview_id"])


@pytest.mark.skipif(os.name != "posix", reason="directory fsync requires POSIX")
def test_claim_ticket_directory_fsync_failure_fails_closed_with_poison(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _settings_store, permits, service = _matrix_service(tmp_path)
    preview = _matrix_preview(service, [_commit_operation("commit", "preview_2350c")])
    dispatch_calls: list[str] = []
    service.dispatch = lambda _capability, _tool, _params: (
        dispatch_calls.append("dispatch") or {"ok": True}
    )
    directory_fsync_calls = 0
    real_fsync = os.fsync

    def fail_claimed_ticket_directory_fsync(fd: int) -> None:
        nonlocal directory_fsync_calls
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            directory_fsync_calls += 1
        if directory_fsync_calls == 2 and stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("simulated directory fsync failure")
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", fail_claimed_ticket_directory_fsync)
    result = _matrix_execute(service, preview)

    assert result["error_code"] == "OPERATOR_EXECUTION_INDETERMINATE"
    assert dispatch_calls == []
    assert permits.is_indeterminate(preview["batch_preview_id"]) is True


@pytest.mark.skipif(os.name != "posix", reason="cross-process claim locking requires POSIX")
def test_live_cross_process_claim_is_not_reconciled_until_owner_exits(tmp_path: Path) -> None:
    _settings_store, permits, service = _matrix_service(tmp_path)
    preview = _matrix_preview(service, [_commit_operation("commit", "preview_2351")])
    context = multiprocessing.get_context("fork")
    ready = context.Queue()
    release = context.Event()

    def claim_worker() -> None:
        child_store = OperatorPermitStore(str(tmp_path / "config"))
        result = _claim_ticket(child_store, preview["batch_preview_id"])
        ready.put(result.get("ok") is True)
        release.wait(timeout=10)
        private_operator_module._release_batch(preview["batch_preview_id"])

    process = context.Process(target=claim_worker)
    process.start()
    try:
        assert ready.get(timeout=5) is True
        with operator_authenticated_request_scope(_auth()):
            live_status = service.handle("project", {
                "workflow": "operator_batch",
                "phase": "status",
                "project_name": "project",
                "batch_preview_id": preview["batch_preview_id"],
            })
        assert live_status["state"] == "claimed"
        assert "error_code" not in live_status
    finally:
        release.set()
        process.join(timeout=5)
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
    assert process.exitcode == 0

    with operator_authenticated_request_scope(_auth()):
        orphaned_status = service.handle("project", {
            "workflow": "operator_batch",
            "phase": "status",
            "project_name": "project",
            "batch_preview_id": preview["batch_preview_id"],
        })
    assert orphaned_status["state"] == "indeterminate"
    assert orphaned_status["error_code"] == "OPERATOR_EXECUTION_INDETERMINATE"


def test_claimed_ticket_without_claim_marker_becomes_indeterminate(tmp_path: Path) -> None:
    _settings_store, permits, service = _matrix_service(tmp_path)
    preview = _matrix_preview(service, [_commit_operation("commit", "preview_2352")])
    assert _claim_ticket(permits, preview["batch_preview_id"])["ok"] is True
    private_operator_module._release_batch(preview["batch_preview_id"])
    Path(permits._claim_path(preview["batch_preview_id"])).unlink()

    with operator_authenticated_request_scope(_auth()):
        status = service.handle("project", {
            "workflow": "operator_batch",
            "phase": "status",
            "project_name": "project",
            "batch_preview_id": preview["batch_preview_id"],
        })

    assert status["state"] == "indeterminate"
    assert status["error_code"] == "OPERATOR_EXECUTION_INDETERMINATE"


def test_handler_execution_releases_claim_lock_at_terminal_state(tmp_path: Path) -> None:
    _settings_store, permits, service = _matrix_service(tmp_path)
    preview = _matrix_preview(service, [_commit_operation("commit", "preview_2353")])

    with operator_authenticated_request_scope(_auth()):
        result = service.handle("project", {
            "workflow": "operator_batch",
            "phase": "execute",
            "project_name": "project",
            "batch_preview_id": preview["batch_preview_id"],
            "manifest_digest": preview["manifest_digest"],
        })

    assert result["state"] == "consumed"
    assert permits.has_claim(preview["batch_preview_id"]) is True
    assert permits.claim_is_live(preview["batch_preview_id"]) is False


def test_orphaned_claim_becomes_indeterminate_and_cannot_replay(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    permits = OperatorPermitStore(str(tmp_path / "config"))
    service = OperatorBatchService(
        settings_store=settings,
        permit_store=permits,
        preview_validator=_validator,
        dispatch=lambda _capability, _tool, _params: {"ok": True},
    )
    with operator_authenticated_request_scope(_auth()):
        preview = service.handle("project", {
            "workflow": "operator_batch",
            "phase": "preview",
            "project_name": "project",
            "operations": [_commit_operation("commit", "preview_2501")],
        })
        claim_path = Path(permits._claim_path(preview["batch_preview_id"]))
        fd = os.open(claim_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, b"claimed\n")
            os.fsync(fd)
        finally:
            os.close(fd)
        assert permits.read(preview["batch_preview_id"])["state"] == "pending"
        status = service.handle("project", {
            "workflow": "operator_batch",
            "phase": "status",
            "project_name": "project",
            "batch_preview_id": preview["batch_preview_id"],
        })
    assert status["state"] == "indeterminate"
    assert status["error_code"] == "OPERATOR_EXECUTION_INDETERMINATE"
    assert _claim_ticket(permits, preview["batch_preview_id"])["error_code"] == "OPERATOR_EXECUTION_INDETERMINATE"


def test_claim_write_failure_releases_activity_and_reconciles_indeterminate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(tmp_path)
    permits = OperatorPermitStore(str(tmp_path / "config"))
    service = OperatorBatchService(
        settings_store=settings,
        permit_store=permits,
        preview_validator=_validator,
        dispatch=lambda _capability, _tool, _params: {"ok": True},
    )
    preview = _matrix_preview(service, [_commit_operation("commit", "preview_2601")])

    with monkeypatch.context() as scoped:
        scoped.setattr(os, "write", lambda _fd, _data: (_ for _ in ()).throw(OSError("write failed")))
        with pytest.raises(OSError):
            _claim_ticket(permits, preview["batch_preview_id"])

    with operator_authenticated_request_scope(_auth()):
        status = service.handle("project", {
            "workflow": "operator_batch",
            "phase": "status",
            "project_name": "project",
            "batch_preview_id": preview["batch_preview_id"],
        })
    assert status["state"] == "indeterminate"
    assert status["error_code"] == "OPERATOR_EXECUTION_INDETERMINATE"


def test_orphan_reconciliation_happens_only_after_project_and_principal_binding(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    permits = OperatorPermitStore(str(tmp_path / "config"))
    service = OperatorBatchService(
        settings_store=settings,
        permit_store=permits,
        preview_validator=_validator,
        dispatch=lambda _capability, _tool, _params: {"ok": True},
    )
    preview = _matrix_preview(service, [_commit_operation("commit", "preview_2701")])
    claim_path = Path(permits._claim_path(preview["batch_preview_id"]))
    claim_path.write_text("claimed\n", encoding="utf-8")
    claim_path.chmod(0o600)

    response = _matrix_execute(service, preview, project="other")
    assert response["error_code"] == "OPERATOR_PROJECT_MISMATCH"
    assert permits.read(preview["batch_preview_id"])["state"] == "pending"


def test_poison_marker_is_interpreted_only_after_ticket_identity_binding(tmp_path: Path) -> None:
    settings, permits, service = _matrix_service(tmp_path)
    preview = _matrix_preview(service, [_commit_operation("commit", "preview_2702")])
    ticket = permits.read(preview["batch_preview_id"])
    assert permits.mark_indeterminate(ticket) is True

    wrong_project = _matrix_execute(service, preview, project="other")
    altered = dict(preview)
    altered["manifest_digest"] = "0" * 64
    wrong_digest = _matrix_execute(service, altered)

    assert settings.enable("auth0|rotated", "https://chatgpt.example/rotated")["ok"] is True
    with operator_authenticated_request_scope(
        _auth(subject="auth0|rotated", client="https://chatgpt.example/rotated")
    ):
        rotated_principal = service.handle("project", {
            "workflow": "operator_batch",
            "phase": "status",
            "project_name": "project",
            "batch_preview_id": preview["batch_preview_id"],
        })

    assert wrong_project == {
        "ok": False,
        "error_code": "OPERATOR_PROJECT_MISMATCH",
        "message": "Operator request was denied.",
    }
    assert wrong_digest == {
        "ok": False,
        "error_code": "OPERATOR_MANIFEST_MISMATCH",
        "message": "Operator request was denied.",
    }
    assert rotated_principal == {
        "ok": False,
        "error_code": "OPERATOR_PRINCIPAL_DENIED",
        "message": "Operator request was denied.",
    }


def test_server_reports_scope_union_and_plan_scope(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="commander")
    _settings_store, _permits, service = _matrix_service(tmp_path / "operator")
    monkeypatch.setattr(server, "_operator_batch_service_for_params", lambda _params: service)
    params = {
        "workflow": "operator_batch",
        "phase": "preview",
        "project_name": "project",
        "operations": [
            {
                "step_id": "plan",
                "tool": "run_mcp_workflow",
                "params": {"workflow": "plan_update", "phase": "apply", "patch_id": "preview_3001"},
            },
            _commit_operation("commit", "preview_3002"),
        ],
    }
    assert server.get_required_scopes_for_tool("run_mcp_workflow", params) == ("mcp:commit", "mcp:plan")
    assert server.get_required_scope_for_tool(
        "run_mcp_workflow", {"workflow": "plan_update", "phase": "apply"}
    ) == "mcp:plan"

    provider = SimpleNamespace(
        validate_scope=lambda _token, scope: scope == "mcp:plan",
        protected_resource_metadata_url=lambda: "https://mcp.example/.well-known/oauth-protected-resource",
    )
    error = server._oauth_scope_error(
        "run_mcp_workflow",
        params,
        {"mode": "external-oauth", "oauth_provider": provider, "token": {}},
    )
    assert error is not None
    assert error["details"]["required_scopes"] == ["mcp:commit", "mcp:plan"]
    assert error["details"]["missing_scopes"] == ["mcp:commit"]
    assert 'scope="mcp:commit"' in error["_meta"]["mcp/www_authenticate"][0]


def test_call_tool_preserves_exact_operator_public_projection(tmp_path: Path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="commander")
    expires_at = "2026-07-19T12:34:56Z"
    server.tools["run_mcp_workflow"] = lambda _params: {
        "ok": True,
        "batch_preview_id": "opb_12345678",
        "manifest_digest": "a" * 64,
        "required_scopes": ["mcp:commit"],
        "operations": [{
            "step_id": "commit",
            "tool": "manage_git",
            "operation": "commit_apply",
            "phase": "commit_apply",
        }],
        "expires_at": expires_at,
        "requires_confirmation": True,
        "project_name": "must-not-be-added",
        "project_root": "/must/not/escape",
    }

    result = server._call_tool("run_mcp_workflow", {
        "workflow": "operator_batch",
        "phase": "preview",
        "project_name": "project",
        "operations": [_commit_operation("commit", "preview_2801")],
    })

    assert result["data"]["expires_at"] == expires_at
    assert set(result["data"]) == {
        "ok", "batch_preview_id", "manifest_digest", "required_scopes",
        "operations", "expires_at", "requires_confirmation",
    }
    assert "project_name" not in result["data"]
    assert "project_root" not in result["data"]


def test_operator_cli_rejects_principal_values_on_command_line(capsys: pytest.CaptureFixture[str]) -> None:
    assert runner_cli._run_operator_config([
        "operator-config", "enable", "raw-subject", "raw-client"
    ]) == 1
    captured = capsys.readouterr()
    assert "raw-subject" not in captured.out + captured.err
    assert "raw-client" not in captured.out + captured.err


def test_operator_config_and_preview_paths_reject_symlinks(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir(mode=0o700)
    linked_config = tmp_path / "linked-config"
    linked_config.symlink_to(target, target_is_directory=True)
    store = OperatorSettingsStore(str(linked_config))
    assert store.enable("auth0|jenn", "client")["error_code"] == "OPERATOR_CONFIG_WRITE_FAILED"
    assert store.load()["error_code"] == "OPERATOR_CONFIG_UNSAFE"

    project = tmp_path / "project"
    preview_dir = project / ".colameta" / "runtime" / "commit-previews"
    preview_dir.mkdir(parents=True)
    preview_id = "preview_symlink_01"
    target_preview = preview_dir / "target.json"
    target_preview.write_text(json.dumps({
        "preview_id": preview_id,
        "project_root": str(project),
        "can_commit": True,
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
    }), encoding="utf-8")
    (preview_dir / f"{preview_id}.json").symlink_to(target_preview.name)
    server = MCPPlanningBridgeServer(str(project), exposure_profile="commander")
    result = server._operator_preview_validation({
        "tool": "manage_git",
        "operation": "commit_apply",
        "phase": "commit_apply",
        "preview_id": preview_id,
    })
    assert result["error_code"] == "OPERATOR_PREVIEW_NOT_FOUND"


def test_operator_preview_requires_exact_artifact_identity_kind_and_aware_expiry(tmp_path: Path) -> None:
    project = tmp_path / "project"
    preview_dir = project / ".colameta" / "runtime" / "validation-run-previews"
    preview_dir.mkdir(parents=True)
    preview_id = "validation_preview_01"
    path = preview_dir / f"{preview_id}.json"
    server = MCPPlanningBridgeServer(str(project), exposure_profile="commander")
    operation = {
        "tool": "manage_validation_run",
        "operation": "run",
        "phase": "run",
        "preview_id": preview_id,
    }

    base = {
        "preview_id": "different_preview",
        "artifact_kind": "validation_run",
        "project_root": str(project),
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
    }
    path.write_text(json.dumps(base), encoding="utf-8")
    assert server._operator_preview_validation(operation)["error_code"] == "OPERATOR_PREVIEW_KIND_MISMATCH"

    base["preview_id"] = preview_id
    base["artifact_kind"] = "wrong_kind"
    path.write_text(json.dumps(base), encoding="utf-8")
    assert server._operator_preview_validation(operation)["error_code"] == "OPERATOR_PREVIEW_KIND_MISMATCH"

    base["artifact_kind"] = "validation_run"
    base["expires_at"] = "2099-01-01T00:00:00"
    path.write_text(json.dumps(base), encoding="utf-8")
    assert server._operator_preview_validation(operation)["error_code"] == "OPERATOR_PREVIEW_INVALID"

    base["expires_at"] = ""
    path.write_text(json.dumps(base), encoding="utf-8")
    assert server._operator_preview_validation(operation)["error_code"] == "OPERATOR_PREVIEW_INVALID"


def test_operator_outer_error_response_does_not_expose_exception_details(tmp_path: Path) -> None:
    server = MCPPlanningBridgeServer(str(tmp_path), exposure_profile="commander")

    def fail(_params: dict) -> dict:
        raise RuntimeError("internal failure at /private/project/path")

    server.tools["run_mcp_workflow"] = fail
    result = server._call_tool("run_mcp_workflow", {
        "workflow": "operator_batch",
        "phase": "preview",
        "project_name": "project",
        "operations": [_commit_operation("commit", "preview_3901")],
    })
    assert result["error_code"] == "OPERATOR_REQUEST_FAILED"
    assert "details" not in result
    assert "/private/project/path" not in json.dumps(result)


def test_ticket_manifest_tamper_is_rejected_and_cannot_downgrade_scopes(tmp_path: Path) -> None:
    _settings_store, permits, service = _matrix_service(tmp_path)
    preview = _matrix_preview(service, [_commit_operation("commit", "preview_3951")])
    ticket = permits.read(preview["batch_preview_id"])
    assert validate_operator_ticket(ticket)["ok"] is True

    ticket["required_scopes"] = []
    ticket_path = Path(permits._ticket_path(preview["batch_preview_id"]))
    ticket_path.write_text(json.dumps(ticket), encoding="utf-8")
    ticket_path.chmod(0o600)

    assert service.required_scopes({
        "phase": "execute",
        "batch_preview_id": preview["batch_preview_id"],
    }) == ("mcp:commit", "mcp:plan")
    result = _matrix_execute(service, preview)
    assert result["error_code"] == "OPERATOR_TICKET_INVALID"


def test_ticket_operation_change_fails_canonical_manifest_recalculation(tmp_path: Path) -> None:
    _settings_store, permits, service = _matrix_service(tmp_path)
    preview = _matrix_preview(service, [_commit_operation("commit", "preview_3961")])
    ticket = permits.read(preview["batch_preview_id"])
    ticket["operations"][0]["preview_id"] = "preview_3962"
    ticket["operations"][0]["params"]["preview_id"] = "preview_3962"
    ticket_path = Path(permits._ticket_path(preview["batch_preview_id"]))
    ticket_path.write_text(json.dumps(ticket), encoding="utf-8")
    ticket_path.chmod(0o600)

    validation = validate_operator_ticket(permits.read(preview["batch_preview_id"]))
    assert validation["error_code"] == "OPERATOR_MANIFEST_MISMATCH"
    assert _matrix_execute(service, preview)["error_code"] == "OPERATOR_MANIFEST_MISMATCH"


def test_public_ticket_values_are_sanitized_even_for_malformed_private_state(tmp_path: Path) -> None:
    _settings_store, _permits, service = _matrix_service(tmp_path)
    result = service._public_ticket({
        "batch_preview_id": "../../private/path",
        "manifest_digest": "not-a-digest",
        "state": "token-value",
        "expires_at": "not-a-time",
        "steps": [{
            "step_id": "../../secret",
            "status": "internal/path",
            "error_code": "token=must-not-escape",
        }],
    }, "private/error=must-not-escape")
    serialized = json.dumps(result)
    assert "private/path" not in serialized
    assert "must-not-escape" not in serialized
    assert result["batch_preview_id"] is None
    assert result["manifest_digest"] is None
    assert result["state"] == "indeterminate"
    assert result["steps"] == [{"step_id": "step-1", "status": "indeterminate"}]
    assert result["expires_at"] is None
    assert result["error_code"] == "OPERATOR_REQUEST_FAILED"


def test_preview_validator_success_without_content_digest_fails_closed() -> None:
    result = normalize_operator_operations(
        [_commit_operation("commit", "preview_3971")],
        max_steps=8,
        preview_validator=lambda _operation: {"ok": True},
    )
    assert result["error_code"] == "OPERATOR_PREVIEW_DIGEST_INVALID"


def test_preview_scope_is_derived_only_after_real_manifest_validation(tmp_path: Path) -> None:
    _settings_store, _permits, service = _matrix_service(
        tmp_path,
        validator=lambda _operation: {"ok": True},
    )
    params = {
        "phase": "preview",
        "operations": [_commit_operation("commit", "preview_3981")],
    }

    assert service.required_scopes(params) == ("mcp:commit", "mcp:plan")


def test_operator_allowlist_conforms_to_real_git_commit_handler_phase(tmp_path: Path) -> None:
    assert set(private_operator_module._ALLOWED_OPERATIONS) == set(
        private_operator_module._OPERATION_PREVIEW_FIELDS
    )
    server = MCPPlanningBridgeServer(str(tmp_path / "project"), exposure_profile="commander")
    unsupported = server._tool_run_mcp_workflow({
        "workflow": "git_commit",
        "phase": "apply",
        "preview_id": "preview_6101",
    })
    supported = server._tool_run_mcp_workflow({
        "workflow": "git_commit",
        "phase": "commit",
        "preview_id": "preview_6101",
    })
    denied = normalize_operator_operations(
        [{
            "step_id": "commit",
            "tool": "run_mcp_workflow",
            "params": {
                "workflow": "git_commit",
                "phase": "apply",
                "preview_id": "preview_6101",
            },
        }],
        max_steps=8,
        preview_validator=_validator,
    )
    accepted = normalize_operator_operations(
        [{
            "step_id": "commit",
            "tool": "run_mcp_workflow",
            "params": {
                "workflow": "git_commit",
                "phase": "commit",
                "preview_id": "preview_6101",
            },
        }],
        max_steps=8,
        preview_validator=_validator,
    )

    assert unsupported["error_code"] == "PHASE_NOT_SUPPORTED"
    assert supported.get("error_code") != "PHASE_NOT_SUPPORTED"
    assert denied["error_code"] == "OPERATOR_OPERATION_DENIED"
    assert accepted["ok"] is True


def test_bound_artifact_is_checked_against_payload_consumed_by_real_handler(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    (project / "runner").mkdir(parents=True)
    target = project / "runner" / "target.py"
    target.write_text("original\n", encoding="utf-8")
    manager = MCPProjectPatchManager(str(project), SourceReviewBridge())
    patch_preview = manager.preview({
        "file": "runner/target.py",
        "old_text": "original\n",
        "new_text": "authorized\n",
    })
    assert patch_preview["ok"] is True, patch_preview
    preview_id = patch_preview["preview_id"]
    artifact_path = project / ".colameta" / "runtime" / "project-patch-previews" / f"{preview_id}.json"
    server = MCPPlanningBridgeServer(str(project), exposure_profile="commander")
    validations = 0

    def validate_then_replace(operation: dict) -> dict:
        nonlocal validations
        result = server._operator_preview_validation(operation)
        validations += 1
        if validations == 2 and result.get("ok") is True:
            payload = json.loads(artifact_path.read_text(encoding="utf-8"))
            payload["exact_specs"][0]["new_text"] = "unauthorized\n"
            artifact_path.write_text(json.dumps(payload), encoding="utf-8")
        return result

    settings = _settings(tmp_path / "operator")
    permits = OperatorPermitStore(str(tmp_path / "operator" / "config"))
    service = OperatorBatchService(
        settings_store=settings,
        permit_store=permits,
        preview_validator=validate_then_replace,
        dispatch=server._operator_internal_dispatch,
    )
    operation = {
        "step_id": "patch",
        "tool": "run_mcp_workflow",
        "params": {
            "workflow": "small_project_patch",
            "phase": "apply",
            "preview_id": preview_id,
        },
    }
    preview = _matrix_preview(service, [operation])
    result = _matrix_execute(service, preview)

    assert result["state"] == "failed"
    assert result["steps"] == [{
        "step_id": "patch",
        "status": "failed",
        "error_code": "OPERATOR_PREVIEW_CHANGED",
    }]
    assert target.read_text(encoding="utf-8") == "original\n"


def test_executor_consumer_rejects_artifact_replaced_after_operator_revalidation(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    preview_dir = project / ".colameta" / "runtime" / "executor-workflow-previews"
    preview_dir.mkdir(parents=True)
    preview_id = "preview_executor_binding_01"
    artifact_path = preview_dir / f"{preview_id}.json"
    artifact_path.write_text(json.dumps({
        "preview_id": preview_id,
        "artifact_kind": "run_once",
        "project_root": str(project),
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
        "provider": "codex",
    }), encoding="utf-8")
    server = MCPPlanningBridgeServer(str(project), exposure_profile="commander")
    validations = 0

    def validate_then_replace(operation: dict) -> dict:
        nonlocal validations
        result = server._operator_preview_validation(operation)
        validations += 1
        if validations == 2 and result.get("ok") is True:
            payload = json.loads(artifact_path.read_text(encoding="utf-8"))
            payload["provider"] = "unauthorized-provider"
            artifact_path.write_text(json.dumps(payload), encoding="utf-8")
        return result

    settings = _settings(tmp_path / "operator")
    permits = OperatorPermitStore(str(tmp_path / "operator" / "config"))
    service = OperatorBatchService(
        settings_store=settings,
        permit_store=permits,
        preview_validator=validate_then_replace,
        dispatch=server._operator_internal_dispatch,
    )
    operation = {
        "step_id": "executor",
        "tool": "run_mcp_workflow",
        "params": {
            "workflow": "prompt_to_plan",
            "phase": "run",
            "preview_id": preview_id,
        },
    }

    preview = _matrix_preview(service, [operation])
    result = _matrix_execute(service, preview)

    assert result["state"] == "failed"
    assert result["steps"] == [{
        "step_id": "executor",
        "status": "failed",
        "error_code": "OPERATOR_PREVIEW_CHANGED",
    }]
    assert not list((project / ".colameta").rglob("*.claim.json"))


def test_exact_plan_patch_dispatch_does_not_apply_second_pending_patch(tmp_path: Path) -> None:
    project = tmp_path / "project"
    runner_dir = project / ".colameta"
    runner_dir.mkdir(parents=True)
    (runner_dir / "plan.json").write_text(json.dumps({"versions": []}), encoding="utf-8")
    bridge = PlanningBridge()

    def spec(version: str) -> dict:
        return {
            "version": version,
            "name": version,
            "description": f"description {version}",
            "prompt": f"prompt {version}",
            "allowed_files": ["runner/**"],
            "acceptance_commands": ["python -m pytest -q"],
        }

    selected = bridge.preview_insert_version(str(project), spec("v1"))
    unselected = bridge.preview_insert_version(str(project), spec("v2"))
    server = MCPPlanningBridgeServer(str(project), exposure_profile="commander")
    settings = _settings(tmp_path / "operator")
    permits = OperatorPermitStore(str(tmp_path / "operator" / "config"))
    service = OperatorBatchService(
        settings_store=settings,
        permit_store=permits,
        preview_validator=server._operator_preview_validation,
        dispatch=server._operator_internal_dispatch,
    )
    operation = {
        "step_id": "plan",
        "tool": "run_mcp_workflow",
        "params": {
            "workflow": "plan_update",
            "phase": "apply",
            "patch_id": selected["patch_id"],
        },
    }
    preview = _matrix_preview(service, [operation])
    result = _matrix_execute(service, preview)

    plan = json.loads((runner_dir / "plan.json").read_text(encoding="utf-8"))
    selected_artifact = json.loads(
        (runner_dir / "plan-patches" / f"{selected['patch_id']}.json").read_text(encoding="utf-8")
    )
    unselected_artifact = json.loads(
        (runner_dir / "plan-patches" / f"{unselected['patch_id']}.json").read_text(encoding="utf-8")
    )
    assert result["state"] == "consumed"
    assert [item["version"] for item in plan["versions"]] == ["v1"]
    assert selected_artifact["status"] == "APPLIED"
    assert unselected_artifact.get("status", "PENDING") == "PENDING"


def test_validation_run_is_async_and_cannot_precede_commit() -> None:
    validation = {
        "step_id": "validation",
        "tool": "manage_validation_run",
        "params": {"action": "run", "preview_id": "preview_6201"},
    }
    single = normalize_operator_operations(
        [validation],
        max_steps=8,
        preview_validator=_validator,
    )
    combined = normalize_operator_operations(
        [validation, _commit_operation("commit", "preview_6202")],
        max_steps=8,
        preview_validator=_validator,
    )

    assert single["operations"][0]["async"] is True
    assert combined["error_code"] == "OPERATOR_ASYNC_STEP_NOT_LAST"


def test_real_commit_then_validation_handlers_produce_observable_side_effects(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    (project / "runner").mkdir(parents=True)
    tracked = project / "runner" / "tracked.py"
    tracked.write_text("initial\n", encoding="utf-8")
    _git(project, "init", "-q")
    _git(project, "config", "user.name", "ColaMeta Test")
    _git(project, "config", "user.email", "colameta@example.invalid")
    _git(project, "add", "runner/tracked.py")
    _git(project, "commit", "-q", "-m", "initial")
    tracked.write_text("changed\n", encoding="utf-8")

    commit_preview = MCPGitCommitManager(str(project)).preview(
        message="operator commit",
        include_files=["runner/tracked.py"],
    )
    assert commit_preview["ok"] is True, commit_preview
    validation_preview_id = "validation_6401"
    validation_marker = project / "validation-observed.txt"
    validation_dir = project / ".colameta" / "runtime" / "validation-run-previews"
    validation_dir.mkdir(parents=True, exist_ok=True)
    validation_artifact = {
        "preview_id": validation_preview_id,
        "artifact_kind": "validation_run",
        "project_root": str(project),
        "scope": "target_files",
        "target_files": ["runner/tracked.py"],
        "strategy": "operator-test",
        "validation_groups": [],
        "commands": [[
            "python3",
            "-c",
            "__import__('pathlib').Path('validation-observed.txt').write_text('passed', encoding='utf-8')",
        ]],
        "command_specs": [],
        "current_head": _git(project, "rev-parse", "HEAD"),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
        "blockers": [],
        "warnings": [],
    }
    (validation_dir / f"{validation_preview_id}.json").write_text(
        json.dumps(validation_artifact),
        encoding="utf-8",
    )
    server = MCPPlanningBridgeServer(str(project), exposure_profile="commander")
    settings = _settings(tmp_path / "operator")
    permits = OperatorPermitStore(str(tmp_path / "operator" / "config"))
    service = OperatorBatchService(
        settings_store=settings,
        permit_store=permits,
        preview_validator=server._operator_preview_validation,
        dispatch=server._operator_internal_dispatch,
    )
    operations = [
        _commit_operation("commit", commit_preview["preview_id"]),
        {
            "step_id": "validation",
            "tool": "manage_validation_run",
            "params": {"action": "run", "preview_id": validation_preview_id},
        },
    ]
    preview = _matrix_preview(service, operations)
    result = _matrix_execute(service, preview)

    deadline = time.monotonic() + 5
    while not validation_marker.exists() and time.monotonic() < deadline:
        time.sleep(0.02)

    assert result["state"] == "consumed"
    assert result["steps"] == [
        {"step_id": "commit", "status": "succeeded"},
        {"step_id": "validation", "status": "started_async"},
    ]
    assert _git(project, "log", "-1", "--pretty=%s") == "operator commit"
    assert tracked.read_text(encoding="utf-8") == "changed\n"
    assert validation_marker.read_text(encoding="utf-8") == "passed"
    run_files = list((project / ".colameta" / "runtime" / "validation-runs").glob("*.json"))
    assert run_files


def test_cross_project_scope_uses_target_project_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service_root = tmp_path / "service"
    target_root = tmp_path / "target"
    preview_dir = target_root / ".colameta" / "runtime" / "commit-previews"
    preview_dir.mkdir(parents=True)
    preview_id = "preview_cross_01"
    (preview_dir / f"{preview_id}.json").write_text(json.dumps({
        "preview_id": preview_id,
        "project_root": str(target_root),
        "can_commit": True,
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
    }), encoding="utf-8")
    server = MCPPlanningBridgeServer(str(service_root), exposure_profile="commander")
    target_server = MCPPlanningBridgeServer(str(target_root), exposure_profile="commander")
    settings, permits, target_service = _matrix_service(
        tmp_path / "operator",
        validator=target_server._operator_preview_validation,
    )
    assert settings.status()["ok"] is True
    assert permits.root
    monkeypatch.setattr(
        server,
        "_resolve_managed_project_context",
        lambda _params: (str(target_root), {"project_name": "target"}),
    )
    monkeypatch.setattr(
        MCPPlanningBridgeServer,
        "_operator_batch_service",
        lambda instance: target_service
        if Path(instance.project_root) == target_root
        else pytest.fail("scope validation used the service project instead of the target project"),
    )
    params = {
        "workflow": "operator_batch",
        "phase": "preview",
        "project_name": "target",
        "operations": [_commit_operation("commit", preview_id)],
    }

    assert server.get_required_scopes_for_tool("run_mcp_workflow", params) == ("mcp:commit",)


def test_cross_project_execute_uses_target_real_handler(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service_root = tmp_path / "service"
    target_root = tmp_path / "target"
    service_root.mkdir()
    (target_root / "runner").mkdir(parents=True)
    service_file = service_root / "target.txt"
    target_file = target_root / "runner" / "target.py"
    service_file.write_text("service\n", encoding="utf-8")
    target_file.write_text("target\n", encoding="utf-8")
    patch_preview = MCPProjectPatchManager(str(target_root), SourceReviewBridge()).preview({
        "file": "runner/target.py",
        "old_text": "target\n",
        "new_text": "target-updated\n",
    })
    assert patch_preview["ok"] is True, patch_preview
    target_server = MCPPlanningBridgeServer(str(target_root), exposure_profile="commander")
    settings = _settings(tmp_path / "operator")
    permits = OperatorPermitStore(str(tmp_path / "operator" / "config"))
    target_service = OperatorBatchService(
        settings_store=settings,
        permit_store=permits,
        preview_validator=target_server._operator_preview_validation,
        dispatch=target_server._operator_internal_dispatch,
    )
    server = MCPPlanningBridgeServer(str(service_root), exposure_profile="commander")
    monkeypatch.setattr(
        server,
        "_resolve_managed_project_context",
        lambda _params: (str(target_root), {"project_name": "target"}),
    )
    monkeypatch.setattr(
        MCPPlanningBridgeServer,
        "_operator_batch_service",
        lambda instance: target_service
        if Path(instance.project_root) == target_root
        else pytest.fail("execute used the service project instead of the target project"),
    )
    params = {
        "workflow": "operator_batch",
        "phase": "preview",
        "project_name": "target",
        "operations": [{
            "step_id": "patch",
            "tool": "run_mcp_workflow",
            "params": {
                "workflow": "small_project_patch",
                "phase": "apply",
                "preview_id": patch_preview["preview_id"],
            },
        }],
    }
    with operator_authenticated_request_scope(_auth()):
        preview = server._tool_operator_batch(params)
        result = server._tool_operator_batch({
            "workflow": "operator_batch",
            "phase": "execute",
            "project_name": "target",
            "batch_preview_id": preview["batch_preview_id"],
            "manifest_digest": preview["manifest_digest"],
        })

    assert result["state"] == "consumed"
    assert target_file.read_text(encoding="utf-8") == "target-updated\n"
    assert service_file.read_text(encoding="utf-8") == "service\n"


def test_failed_step_persistence_failure_becomes_indeterminate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _settings_store, permits, service = _matrix_service(
        tmp_path,
        dispatch=lambda _capability, _tool, _params: {
            "ok": False,
            "error_code": "CONTROLLED_FAILURE",
        },
    )
    preview = _matrix_preview(service, [_commit_operation("commit", "preview_6301")])
    original_update = permits.update

    def fail_failed_state(ticket: dict) -> bool:
        if ticket.get("state") == "failed":
            return False
        return original_update(ticket)

    monkeypatch.setattr(permits, "update", fail_failed_state)
    result = _matrix_execute(service, preview)
    durable = permits.read(preview["batch_preview_id"])

    assert result["error_code"] == "OPERATOR_EXECUTION_INDETERMINATE"
    assert result["state"] == "indeterminate"
    assert result["steps"] == [{"step_id": "commit", "status": "indeterminate"}]
    assert durable["state"] == "indeterminate"
    assert durable["steps"] == [{"step_id": "commit", "status": "indeterminate"}]


@pytest.mark.parametrize(
    ("state", "step_status", "claimed", "completed"),
    [
        ("pending", "succeeded", False, False),
        ("claimed", "pending", False, False),
        ("consumed", "pending", True, True),
        ("failed", "succeeded", True, True),
        ("indeterminate", "running", True, True),
    ],
)
def test_ticket_schema_rejects_inconsistent_state_machine_combinations(
    tmp_path: Path,
    state: str,
    step_status: str,
    claimed: bool,
    completed: bool,
) -> None:
    _settings_store, permits, service = _matrix_service(tmp_path)
    preview = _matrix_preview(service, [_commit_operation("commit", "preview_6351")])
    ticket = permits.read(preview["batch_preview_id"])
    ticket["state"] = state
    ticket["steps"][0]["status"] = step_status
    if claimed:
        ticket["claimed_at"] = private_operator_module._iso(private_operator_module._utc_now())
    if completed:
        ticket["completed_at"] = private_operator_module._iso(private_operator_module._utc_now())

    assert validate_operator_ticket(ticket)["error_code"] == "OPERATOR_TICKET_INVALID"


def test_preview_validator_error_code_is_filtered_from_public_response(tmp_path: Path) -> None:
    _settings_store, _permits, service = _matrix_service(
        tmp_path,
        validator=lambda _operation: {
            "ok": False,
            "error_code": "PRIVATE_/home/jenn/token",
        },
    )

    result = _matrix_preview(service, [_commit_operation("commit", "preview_6352")])

    assert result == {
        "ok": False,
        "error_code": "OPERATOR_REQUEST_FAILED",
        "message": "Operator request was denied.",
    }


def test_continuous_ticket_persistence_failure_uses_durable_poison_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _settings_store, permits, service = _matrix_service(tmp_path)
    preview = _matrix_preview(service, [_commit_operation("commit", "preview_6353")])
    monkeypatch.setattr(
        permits,
        "_update_from_root_fd",
        lambda _root_fd, _ticket: False,
    )

    first = _matrix_execute(service, preview)
    second = _matrix_execute(service, preview)
    with operator_authenticated_request_scope(_auth()):
        status = service.handle("project", {
            "workflow": "operator_batch",
            "phase": "status",
            "project_name": "project",
            "batch_preview_id": preview["batch_preview_id"],
        })

    assert first["error_code"] == "OPERATOR_EXECUTION_INDETERMINATE"
    assert second["error_code"] == "OPERATOR_EXECUTION_INDETERMINATE"
    assert status["state"] == "indeterminate"
    assert permits.is_indeterminate(preview["batch_preview_id"]) is True
    assert Path(permits._poison_path(preview["batch_preview_id"])).is_file()
    assert permits.read(preview["batch_preview_id"])["state"] == "pending"


@pytest.mark.parametrize("marker_kind", ["broad_mode", "symlink", "directory"])
def test_unsafe_indeterminate_marker_fails_closed_without_dispatch(
    tmp_path: Path,
    marker_kind: str,
) -> None:
    dispatch_calls: list[str] = []
    _settings_store, permits, service = _matrix_service(
        tmp_path,
        dispatch=lambda _capability, _tool, params: (
            dispatch_calls.append(str(params.get("preview_id"))) or {"ok": True}
        ),
    )
    preview = _matrix_preview(service, [_commit_operation("commit", "preview_6354")])
    marker = Path(permits._poison_path(preview["batch_preview_id"]))
    if marker_kind == "broad_mode":
        marker.write_text("unsafe", encoding="utf-8")
        marker.chmod(0o644)
    elif marker_kind == "symlink":
        target = tmp_path / "unsafe-marker-target"
        target.write_text("unsafe", encoding="utf-8")
        marker.symlink_to(target)
    else:
        marker.mkdir()

    result = _matrix_execute(service, preview)
    with operator_authenticated_request_scope(_auth()):
        status = service.handle("project", {
            "workflow": "operator_batch",
            "phase": "status",
            "project_name": "project",
            "batch_preview_id": preview["batch_preview_id"],
        })

    assert result["error_code"] == "OPERATOR_PERMIT_UNSAFE"
    assert status["error_code"] == "OPERATOR_PERMIT_UNSAFE"
    assert dispatch_calls == []
    assert permits.read(preview["batch_preview_id"])["state"] == "pending"


def test_prompt_to_plan_apply_all_is_not_an_operator_atomic_step() -> None:
    dispatch_calls: list[str] = []
    result = normalize_operator_operations(
        [{
            "step_id": "composite",
            "tool": "run_mcp_workflow",
            "params": {
                "workflow": "prompt_to_plan",
                "phase": "apply_all",
                "preview_id": "preview_6355",
            },
        }],
        max_steps=8,
        preview_validator=lambda operation: (
            dispatch_calls.append(str(operation.get("preview_id")))
            or {"ok": True, "preview_digest": "a" * 64}
        ),
    )

    assert result["error_code"] == "OPERATOR_OPERATION_DENIED"
    assert dispatch_calls == []


def test_ticket_schema_rejects_impossible_indeterminate_step_sequences(
    tmp_path: Path,
) -> None:
    _settings_store, permits, service = _matrix_service(tmp_path)
    preview = _matrix_preview(service, [
        _commit_operation("one", "preview_6356"),
        _commit_operation("two", "preview_6357"),
    ])
    base = permits.read(preview["batch_preview_id"])
    now = private_operator_module._iso(private_operator_module._utc_now())

    for statuses in (
        ("not_started", "succeeded"),
        ("started_async", "not_started"),
        ("indeterminate", "indeterminate"),
    ):
        ticket = json.loads(json.dumps(base))
        ticket["state"] = "indeterminate"
        ticket["claimed_at"] = now
        ticket["completed_at"] = now
        for step, status in zip(ticket["steps"], statuses, strict=True):
            step["status"] = status
        assert validate_operator_ticket(ticket)["error_code"] == "OPERATOR_TICKET_INVALID"


def test_ticket_schema_rejects_async_succeeded_instead_of_started_async(
    tmp_path: Path,
) -> None:
    _settings_store, permits, service = _matrix_service(tmp_path)
    preview = _matrix_preview(service, [{
        "step_id": "executor",
        "tool": "run_mcp_workflow",
        "params": {
            "workflow": "prompt_to_plan",
            "phase": "run",
            "preview_id": "preview_async_state_01",
        },
    }])
    ticket = permits.read(preview["batch_preview_id"])
    now = private_operator_module._iso(private_operator_module._utc_now())
    ticket["state"] = "consumed"
    ticket["claimed_at"] = now
    ticket["completed_at"] = now
    ticket["steps"][0]["status"] = "succeeded"

    assert validate_operator_ticket(ticket)["error_code"] == "OPERATOR_TICKET_INVALID"


_MATRIX_PATH = Path(__file__).parents[1] / "docs" / "jenn-private-operator-negative-test-matrix.json"
_MATRIX = json.loads(_MATRIX_PATH.read_text(encoding="utf-8"))["cases"]
_MATRIX_CASE_IDS = {case["case_id"] for case in _MATRIX}


@pytest.mark.parametrize("case", _MATRIX, ids=lambda case: case["case_id"])
def test_negative_matrix_row_executes_real_behavior(
    case: dict,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    required = {
        "case_id", "category", "preconditions", "request", "expected_error",
        "expected_ticket_state", "expected_step_states", "expected_side_effects",
        "public_response_allowlist",
    }
    assert set(case) == required
    if case["expected_error"] is not None:
        assert case["expected_error"].startswith(("OPERATOR_", "INSUFFICIENT_SCOPE", "REMOTE_POLICY_DENIED"))
    assert isinstance(case["public_response_allowlist"], list)
    assert case["category"] in {
        "principal", "scope", "manifest", "hard-stop", "preview-binding",
        "ticket", "replay", "execution", "bypass", "response",
    }
    observed = _execute_matrix_case(case, tmp_path, monkeypatch)
    assert observed["error"] == case["expected_error"]
    assert observed["ticket_state"] == case["expected_ticket_state"]
    assert observed["step_states"] == case["expected_step_states"]
    assert observed["side_effects"] == case["expected_side_effects"]
    implicit_envelope_keys = {"ok", "tool"}
    assert observed["public_keys"] - implicit_envelope_keys <= set(case["public_response_allowlist"])


def test_negative_matrix_has_no_unrouted_or_duplicate_case() -> None:
    assert len(_MATRIX) == len(_MATRIX_CASE_IDS)
    assert len(_MATRIX_CASE_IDS) == 35


def test_negative_matrix_request_payload_changes_executed_behavior(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    empty_batch = next(case for case in _MATRIX if case["case_id"] == "empty-batch")
    modified = json.loads(json.dumps(empty_batch))
    modified["request"] = {"phase": "preview", "operation_count": 1}

    observed = _execute_matrix_case(modified, tmp_path, monkeypatch)

    assert observed["error"] is None
    assert "batch_preview_id" in observed["public_keys"]


def _matrix_service(
    root: Path,
    *,
    enabled: bool = True,
    max_steps: int = 8,
    validator=_validator,
    dispatch=None,
) -> tuple[OperatorSettingsStore, OperatorPermitStore, OperatorBatchService]:
    settings = OperatorSettingsStore(str(root / "config"))
    if enabled:
        assert settings.enable(
            "auth0|jenn",
            "https://chatgpt.example/cimd",
            max_steps=max_steps,
        )["ok"] is True
    permits = OperatorPermitStore(str(root / "config"))
    service = OperatorBatchService(
        settings_store=settings,
        permit_store=permits,
        preview_validator=validator,
        dispatch=dispatch or (lambda _capability, _tool, _params: {"ok": True}),
    )
    return settings, permits, service


def _matrix_preview(
    service: OperatorBatchService,
    operations: list[dict],
    *,
    project: str = "project",
    phase: str = "preview",
) -> dict:
    with operator_authenticated_request_scope(_auth()):
        return service.handle(project, {
            "workflow": "operator_batch",
            "phase": phase,
            "project_name": project,
            "operations": operations,
        })


def _matrix_execute(
    service: OperatorBatchService,
    preview: dict,
    *,
    project: str = "project",
    phase: str = "execute",
    **extra: object,
) -> dict:
    params = {
        "workflow": "operator_batch",
        "phase": phase,
        "project_name": project,
        "batch_preview_id": preview["batch_preview_id"],
        "manifest_digest": preview["manifest_digest"],
        **extra,
    }
    with operator_authenticated_request_scope(_auth()):
        return service.handle(project, params)


def _observed(
    response: dict,
    *,
    ticket_state: str | None = None,
    step_states: list[str] | None = None,
    side_effects: str,
) -> dict:
    return {
        "error": response.get("error_code"),
        "ticket_state": ticket_state,
        "step_states": step_states or [],
        "side_effects": side_effects,
        "public_keys": set(response),
    }


def _matrix_filesystem_snapshot(root: Path) -> tuple[tuple[str, str, str], ...]:
    if not root.exists():
        return ()
    snapshot: list[tuple[str, str, str]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            snapshot.append((relative, "symlink", os.readlink(path)))
        elif path.is_file():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            snapshot.append((relative, "file", digest))
        elif path.is_dir():
            snapshot.append((relative, "dir", ""))
    return tuple(snapshot)


class _MatrixSideEffectObserver:
    def __init__(self, root: Path, dispatch_calls: list[str] | None = None):
        self.root = root
        self.dispatch_calls = dispatch_calls
        self.before_files = _matrix_filesystem_snapshot(root)
        self.before_dispatch_count = len(dispatch_calls) if dispatch_calls is not None else 0

    def classify(self) -> str:
        files_changed = _matrix_filesystem_snapshot(self.root) != self.before_files
        dispatch_changed = (
            self.dispatch_calls is not None
            and len(self.dispatch_calls) != self.before_dispatch_count
        )
        if not files_changed and not dispatch_changed:
            return "none"
        if files_changed and not dispatch_changed:
            return "filesystem_state_changed"
        if dispatch_changed and not files_changed:
            return "dispatch_observed"
        return "dispatch_and_filesystem_state_changed"


def _symbolic_matrix_operations(symbol: str) -> list[dict]:
    if symbol == "plan_update_apply":
        return [{
            "step_id": "plan",
            "tool": "run_mcp_workflow",
            "params": {"workflow": "plan_update", "phase": "apply", "patch_id": "preview_5101"},
        }]
    if symbol == "commit_apply":
        return [_commit_operation("commit", "preview_5102")]
    if symbol == "mixed_plan_commit":
        return _symbolic_matrix_operations("plan_update_apply") + _symbolic_matrix_operations("commit_apply")
    if symbol == "operator_batch":
        return [{
            "step_id": "nested",
            "tool": "run_mcp_workflow",
            "params": {"workflow": "operator_batch", "phase": "execute", "preview_id": "preview_5103"},
        }]
    if symbol == "unknown":
        return [{"step_id": "unknown", "tool": "manage_git", "params": {
            "action": "unknown", "preview_id": "preview_5104",
        }}]
    if symbol == "push_apply":
        return [{"step_id": "push", "tool": "manage_git", "params": {
            "action": "push_apply", "preview_id": "preview_5105",
        }}]
    if symbol == "restore_file_apply":
        return [{"step_id": "restore", "tool": "manage_git", "params": {
            "action": "restore_file_apply", "preview_id": "preview_5106",
        }}]
    if symbol == "stable_or_release":
        return [{"step_id": "release", "tool": "run_mcp_workflow", "params": {
            "workflow": "stable_replacement", "phase": "apply", "preview_id": "preview_5107",
        }}]
    raise AssertionError(f"unknown matrix operation symbol: {symbol}")


def _execute_matrix_case(
    case: dict,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict:
    category = case["category"]
    preconditions = case["preconditions"]
    request = case["request"]

    if category == "principal":
        enabled = preconditions.get("profile") != "disabled"
        _settings_store, _permits, service = _matrix_service(tmp_path, enabled=enabled)
        auth = _auth()
        if preconditions.get("subject") == "mismatch":
            auth["token"]["sub"] = "other"
        if preconditions.get("client") == "mismatch":
            auth["token"]["azp"] = auth["token"]["client_id"] = "other-client"
        if preconditions.get("client") == "missing":
            auth["token"].pop("azp")
            auth["token"].pop("client_id")
        if "azp" in preconditions:
            auth["token"]["azp"] = preconditions["azp"]
        if "client_id" in preconditions:
            auth["token"]["client_id"] = preconditions["client_id"]
        if preconditions.get("issuer") == "mismatch":
            auth["token"]["iss"] = "https://other-issuer.example/"
        if preconditions.get("audience") == "mismatch":
            auth["token"]["aud"] = "https://other-resource.example/mcp"
        observer = _MatrixSideEffectObserver(tmp_path)
        with operator_authenticated_request_scope(auth):
            response = service.handle("project", {
                "workflow": "operator_batch",
                "phase": request["phase"],
                "project_name": "project",
                "operations": [_commit_operation("commit", "preview_5201")],
            })
        return _observed(response, side_effects=observer.classify())

    if category == "scope":
        operations = _symbolic_matrix_operations(request["operation"])
        granted = set(preconditions["scopes"])
        _settings_store, _permits, service = _matrix_service(tmp_path)
        server = MCPPlanningBridgeServer(str(tmp_path / "project"), exposure_profile="commander")
        server._operator_batch_service_for_params = lambda _params: service
        provider = SimpleNamespace(
            validate_scope=lambda _token, scope: scope in granted,
            protected_resource_metadata_url=lambda: "https://mcp.example/.well-known/oauth-protected-resource",
        )
        observer = _MatrixSideEffectObserver(tmp_path)
        response = server._oauth_scope_error(
            "run_mcp_workflow",
            {"workflow": "operator_batch", "phase": request["phase"], "operations": operations},
            {"mode": "external-oauth", "oauth_provider": provider, "token": {}},
        )
        assert response is not None
        return _observed(response, side_effects=observer.classify())

    if category in {"manifest", "hard-stop"}:
        _settings_store, _permits, service = _matrix_service(
            tmp_path,
            max_steps=preconditions.get("max_steps", 8),
        )
        if "operations" in request:
            operations = request["operations"]
        elif "operation_count" in request:
            operations = [
                _commit_operation(f"step-{index}", f"preview_{5300 + index}")
                for index in range(request["operation_count"])
            ]
        elif "step_ids" in request:
            operations = [
                _commit_operation(step_id, f"preview_{5310 + index}")
                for index, step_id in enumerate(request["step_ids"])
            ]
        else:
            operations = _symbolic_matrix_operations(request["operation"])
        observer = _MatrixSideEffectObserver(tmp_path)
        response = _matrix_preview(service, operations, phase=request["phase"])
        return _observed(response, side_effects=observer.classify())

    if category == "preview-binding":
        project = tmp_path / "project"
        preview_dir = project / ".colameta" / "runtime" / "commit-previews"
        preview_dir.mkdir(parents=True)
        server = MCPPlanningBridgeServer(str(project), exposure_profile="commander")
        preview_id = "preview_binding_02"
        preview_condition = preconditions.get("preview")
        preview_project = preconditions.get("preview_project")
        if request.get("preview_id") != "missing":
            expires_delta = timedelta(seconds=-1) if preview_condition == "expired" else timedelta(minutes=5)
            payload = {
                "preview_id": preview_id,
                "project_root": str(tmp_path / "other") if preview_project == "other" else str(project),
                "can_commit": True,
                "expires_at": (datetime.now(timezone.utc) + expires_delta).isoformat(),
            }
            (preview_dir / f"{preview_id}.json").write_text(json.dumps(payload), encoding="utf-8")
        _settings_store, _permits, service = _matrix_service(
            tmp_path / "operator",
            validator=server._operator_preview_validation,
        )
        observer = _MatrixSideEffectObserver(tmp_path)
        response = _matrix_preview(
            service,
            [_commit_operation("binding", preview_id)],
            phase=request["phase"],
        )
        return _observed(response, side_effects=observer.classify())

    if category == "bypass":
        if request.get("tool") == "manage_git":
            assert preconditions.get("operator") == "matching"
            matching_auth = _auth()
            server = MCPPlanningBridgeServer(str(tmp_path / "project"), exposure_profile="commander")
            observer = _MatrixSideEffectObserver(tmp_path)
            response = server._external_oauth_remote_policy_error(
                request["tool"],
                {"action": request["action"], "preview_id": "preview_5401"},
                matching_auth,
            )
            assert response is not None
            return _observed(response, side_effects=observer.classify())
        _settings_store, _permits, service = _matrix_service(tmp_path)
        operation = _commit_operation("bypass", "preview_5402")
        if "nested_project_name" in request:
            operation["params"]["project_name"] = request["nested_project_name"]
        if "nested_key" in request:
            operation["params"][request["nested_key"]] = "must-not-persist"
        observer = _MatrixSideEffectObserver(tmp_path)
        response = _matrix_preview(service, [operation], phase=request["phase"])
        return _observed(response, side_effects=observer.classify())

    dispatch_calls: list[str] = []

    def dispatch(_capability: object, _tool: str, params: dict) -> dict:
        dispatch_calls.append(str(params.get("preview_id") or params.get("patch_id") or ""))
        if preconditions.get("fail_step") == len(dispatch_calls):
            return {"ok": False, "error_code": "CONTROLLED_FAILURE"}
        if preconditions.get("handler_private_field"):
            return {"ok": True, preconditions["handler_private_field"]: "/must/not/escape"}
        return {"ok": True}

    _settings_store, permits, service = _matrix_service(tmp_path, dispatch=dispatch)

    if category == "execution" and "operations" in request:
        operations = []
        for index, symbol in enumerate(request["operations"]):
            if symbol == "prompt_to_plan_run":
                operations.append({
                    "step_id": f"step-{index + 1}",
                    "tool": "run_mcp_workflow",
                    "params": {
                        "workflow": "prompt_to_plan",
                        "phase": "run",
                        "preview_id": f"preview_{5501 + index}",
                    },
                })
            elif symbol == "commit_apply":
                operations.append(_commit_operation(f"step-{index + 1}", f"preview_{5501 + index}"))
            elif symbol == "validation_run":
                operations.append({
                    "step_id": f"step-{index + 1}",
                    "tool": "manage_validation_run",
                    "params": {
                        "action": "run",
                        "preview_id": f"preview_{5501 + index}",
                    },
                })
            else:
                raise AssertionError(f"unknown execution operation symbol: {symbol}")
        observer = _MatrixSideEffectObserver(tmp_path, dispatch_calls)
        response = _matrix_preview(service, operations, phase=request["phase"])
        return _observed(response, side_effects=observer.classify())

    operation_count = 3 if preconditions.get("fail_step") else 1
    preview = _matrix_preview(service, [
        _commit_operation(f"step-{index + 1}", f"preview_{5600 + index}")
        for index in range(operation_count)
    ])
    batch_id = preview["batch_preview_id"]

    if category == "ticket":
        observer = _MatrixSideEffectObserver(tmp_path, dispatch_calls)
        if preconditions.get("ticket") == "expired":
            current = private_operator_module._utc_now()
            monkeypatch.setattr(private_operator_module, "_utc_now", lambda: current + timedelta(hours=1))
            response = _matrix_execute(service, preview, phase=request["phase"])
        elif preconditions.get("digest") == "mismatch":
            altered = dict(preview)
            altered["manifest_digest"] = "0" * 64
            response = _matrix_execute(service, altered, phase=request["phase"])
        elif preconditions.get("project") == "mismatch":
            response = _matrix_execute(service, preview, project="other", phase=request["phase"])
        elif request.get("extra") == "operations":
            response = _matrix_execute(service, preview, phase=request["phase"], operations=[])
        else:
            raise AssertionError(f"unrouted ticket matrix data: {case}")
        return _observed(
            response,
            ticket_state=permits.read(batch_id)["state"],
            side_effects=observer.classify(),
        )

    if category == "replay":
        if preconditions.get("ticket") == "consumed":
            assert _matrix_execute(service, preview, phase=request["phase"])["state"] == "consumed"
            calls_after_first_execute = list(dispatch_calls)
            observer = _MatrixSideEffectObserver(tmp_path, dispatch_calls)
            response = _matrix_execute(service, preview, phase=request["phase"])
            ticket = permits.read(batch_id)
            assert dispatch_calls == calls_after_first_execute
            return _observed(
                response,
                ticket_state=ticket["state"],
                step_states=[step["status"] for step in ticket["steps"]],
                side_effects=observer.classify(),
            )
        if preconditions.get("crash") == "after_claim":
            claim_path = Path(permits._claim_path(batch_id))
            fd = os.open(claim_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                os.write(fd, b"claimed\n")
                os.fsync(fd)
            finally:
                os.close(fd)
            response = _matrix_execute(service, preview, phase=request["phase"])
            ticket = permits.read(batch_id)
            assert dispatch_calls == []
            assert permits.is_indeterminate(batch_id) is True
            return _observed(
                response,
                ticket_state=ticket["state"],
                step_states=[step["status"] for step in ticket["steps"]],
                side_effects="unknown_no_replay",
            )
        if preconditions.get("attempts") == 2:
            started = threading.Event()
            release = threading.Event()

            def blocking_dispatch(_capability: object, _tool: str, params: dict) -> dict:
                dispatch_calls.append(str(params.get("preview_id") or ""))
                started.set()
                assert release.wait(timeout=5)
                return {"ok": True}

            service.dispatch = blocking_dispatch
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(lambda: _matrix_execute(service, preview, phase=request["phase"]))
                assert started.wait(timeout=5)
                response = _matrix_execute(service, preview, phase=request["phase"])
                ticket = permits.read(batch_id)
                observed = _observed(
                    response,
                    ticket_state=ticket["state"],
                    step_states=[step["status"] for step in ticket["steps"]],
                    side_effects="at_most_one_dispatch",
                )
                release.set()
                assert future.result(timeout=5)["state"] == "consumed"
            assert len(dispatch_calls) == 1
            return observed
        raise AssertionError(f"unrouted replay matrix data: {case}")

    if category == "execution":
        response = _matrix_execute(service, preview, phase=request["phase"])
        ticket = permits.read(batch_id)
        step_states = [step["status"] for step in ticket["steps"]]
        fail_step = int(preconditions["fail_step"])
        assert dispatch_calls == [f"preview_{5600 + index}" for index in range(fail_step)]
        assert step_states[:fail_step - 1] == ["succeeded"] * (fail_step - 1)
        assert step_states[fail_step - 1] == "failed"
        assert step_states[fail_step:] == ["not_started"] * (len(step_states) - fail_step)
        return _observed(
            response,
            ticket_state=ticket["state"],
            step_states=step_states,
            side_effects="first_step_retained_no_rollback",
        )

    if category == "response":
        response = _matrix_execute(service, preview, phase=request["phase"])
        assert preconditions["handler_private_field"] not in json.dumps(response)
        ticket = permits.read(batch_id)
        return _observed(
            response,
            ticket_state=ticket["state"],
            step_states=[step["status"] for step in ticket["steps"]],
            side_effects="private_field_filtered",
        )
    raise AssertionError(f"matrix data is not routed: {case}")
