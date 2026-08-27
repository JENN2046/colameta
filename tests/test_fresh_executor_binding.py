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
import stat
import subprocess
import threading
from pathlib import Path

import pytest

from runner.fresh_executor_authority import (
    ADMISSION_FILENAME,
    EXECUTION_BINDING_FILENAME,
    FRESH_EXECUTOR_AUTHORITY_ALREADY_CONSUMED,
    FRESH_EXECUTOR_AUTHORITY_BINDING_CONFLICT,
    FRESH_EXECUTOR_AUTHORITY_BINDING_WRITE_FAILED,
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
    read_fresh_executor_authority,
    read_execution_binding,
    validate_and_create_execution_binding,
    _read_admission_verification,
    _read_execution_binding_verification,
    _validate_and_create_execution_binding_verification,
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


def _event_stream_contract() -> dict[str, object]:
    return {
        "identity": {"device": 1, "inode": 1},
        "size": 1,
        "raw_sha256": "0" * 64,
        "record_count": 1,
    }


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
        "event_stream": _event_stream_contract(),
    }


def _validate_bind_kwargs(head: str, admission_sha256: str) -> dict[str, object]:
    kwargs = _bind_kwargs(head, admission_sha256)
    admitted_head = kwargs.pop("admitted_head")
    provider = kwargs.pop("provider")
    kwargs.pop("admission_sha256")
    return {
        **kwargs,
        "expected_admission_sha256": admission_sha256,
        "expected_head": admitted_head,
        "expected_provider": provider,
        "expected_repository": "JENN2046/colameta",
        "expected_git_branch": "main",
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("unexpected", True),
        ("historical_session_inherited", 0),
        ("provider_invoked", 0),
        ("work_started", 0),
        ("created_at", 7),
        ("repository", ["JENN2046/colameta"]),
        ("git_branch", ["main"]),
    ],
)
def test_exact_admission_contract_rejected_by_all_production_reads(
    tmp_path: Path, field: str, value: object
) -> None:
    repo, head = _make_repo(tmp_path)
    authority_id, _admission_sha256 = _make_authority(repo, head)
    path = (
        Path(executor_authority_dir(str(repo))) / authority_id / ADMISSION_FILENAME
    )
    record = json.loads(path.read_text(encoding="utf-8"))
    record[field] = value
    path.write_text(json.dumps(record, sort_keys=True) + "\n", encoding="utf-8")
    path.chmod(0o600)
    mutated_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()

    internal = _read_admission_verification(str(repo), authority_id)
    inspected = inspect_fresh_executor_authority_for_execution(
        str(repo),
        authority_id,
        expected_admission_sha256=mutated_sha256,
        expected_head=head,
    )
    consumed = _validate_and_create_execution_binding_verification(
        str(repo),
        authority_id,
        **_validate_bind_kwargs(head, mutated_sha256),
    )

    assert read_fresh_executor_authority(str(repo), authority_id) is None
    assert internal.get("ok") is False
    assert internal.get("error_code") == FRESH_EXECUTOR_AUTHORITY_MALFORMED
    assert inspected.get("ok") is False
    assert inspected.get("error_code") == FRESH_EXECUTOR_AUTHORITY_MALFORMED
    assert consumed.get("ok") is False
    assert consumed.get("error_code") == FRESH_EXECUTOR_AUTHORITY_MALFORMED
    assert not _binding_path(repo, authority_id).exists()


def test_validate_and_bind_private_evidence_is_stable_and_not_public(
    tmp_path: Path,
) -> None:
    repo, head = _make_repo(tmp_path)
    authority_id, admission_sha256 = _make_authority(repo, head)

    internal = _validate_and_create_execution_binding_verification(
        str(repo),
        authority_id,
        **_validate_bind_kwargs(head, admission_sha256),
    )

    assert internal.get("ok") is True, internal
    evidence = internal["_internal_verification"]
    assert set(evidence) == {"admission", "binding"}
    for contract in evidence.values():
        assert set(contract) == {
            "identity",
            "metadata",
            "raw_sha256",
            "content_sha256",
        }
        assert "raw" not in contract

    second_authority_id, second_admission_sha256 = _make_authority(repo, head)
    public = validate_and_create_execution_binding(
        str(repo),
        second_authority_id,
        **_validate_bind_kwargs(head, second_admission_sha256),
    )
    assert public.get("ok") is True, public
    assert "_internal_verification" not in public
    assert "durable_contract" not in public
    public_json = json.dumps(public, sort_keys=True)
    assert second_authority_id not in public_json
    assert second_admission_sha256 not in public_json
    assert str(repo) not in public_json
    assert "event_stream" not in public_json
    assert "execution_binding_path" not in public_json

    replay = validate_and_create_execution_binding(
        str(repo),
        second_authority_id,
        **_validate_bind_kwargs(head, second_admission_sha256),
    )
    assert replay.get("ok") is False
    replay_json = json.dumps(replay, sort_keys=True)
    assert second_authority_id not in replay_json
    assert second_admission_sha256 not in replay_json
    assert str(repo) not in replay_json
    assert "event_stream" not in replay_json


def _replace_unsafe_record(path: Path, tmp_path: Path, hazard: str) -> None:
    raw = path.read_bytes()
    path.unlink()
    outside = tmp_path / f"outside-{path.name}"
    if hazard == "symlink":
        outside.write_bytes(raw)
        outside.chmod(0o600)
        path.symlink_to(outside)
    elif hazard == "fifo":
        os.mkfifo(path, 0o600)
    elif hazard == "hardlink":
        outside.write_bytes(raw)
        outside.chmod(0o600)
        os.link(outside, path)
    elif hazard == "mode":
        path.write_bytes(raw)
        path.chmod(0o644)
    elif hazard == "oversized":
        path.write_bytes(b"x" * (1024 * 1024 + 1))
        path.chmod(0o600)
    else:  # pragma: no cover - test helper guard
        raise AssertionError(hazard)


@pytest.mark.parametrize("hazard", ["symlink", "fifo", "hardlink", "mode", "oversized"])
def test_admission_hazards_rejected_by_read_inspect_and_consume(
    tmp_path: Path, hazard: str
) -> None:
    repo, head = _make_repo(tmp_path)
    authority_id, admission_sha256 = _make_authority(repo, head)
    path = (
        Path(executor_authority_dir(str(repo))) / authority_id / ADMISSION_FILENAME
    )
    _replace_unsafe_record(path, tmp_path, hazard)

    plain = read_fresh_executor_authority(str(repo), authority_id)
    inspected = inspect_fresh_executor_authority_for_execution(
        str(repo), authority_id, expected_admission_sha256=admission_sha256
    )
    consumed = validate_and_create_execution_binding(
        str(repo),
        authority_id,
        **_validate_bind_kwargs(head, admission_sha256),
    )

    assert plain is None
    assert inspected.get("ok") is False
    assert inspected.get("error_code") == FRESH_EXECUTOR_AUTHORITY_MALFORMED
    assert consumed.get("ok") is False
    assert consumed.get("error_code") == FRESH_EXECUTOR_AUTHORITY_MALFORMED
    assert not _binding_path(repo, authority_id).exists()


@pytest.mark.parametrize("hazard", ["symlink", "fifo", "hardlink", "mode", "oversized"])
def test_existing_binding_hazards_rejected_by_all_production_probes(
    tmp_path: Path, hazard: str
) -> None:
    repo, head = _make_repo(tmp_path)
    authority_id, admission_sha256 = _make_authority(repo, head)
    kwargs = _bind_kwargs(head, admission_sha256)
    assert create_execution_binding(str(repo), authority_id, **kwargs).get("ok") is True
    _replace_unsafe_record(_binding_path(repo, authority_id), tmp_path, hazard)

    inspected = inspect_fresh_executor_authority_for_execution(
        str(repo), authority_id, expected_admission_sha256=admission_sha256
    )
    direct = create_execution_binding(str(repo), authority_id, **kwargs)
    consumed = validate_and_create_execution_binding(
        str(repo),
        authority_id,
        **_validate_bind_kwargs(head, admission_sha256),
    )

    assert read_execution_binding(str(repo), authority_id) is None
    assert inspected.get("ok") is False
    assert inspected.get("error_code") == FRESH_EXECUTOR_AUTHORITY_MALFORMED
    assert direct.get("ok") is False
    assert direct.get("error_code") == FRESH_EXECUTOR_AUTHORITY_BINDING_CONFLICT
    assert consumed.get("ok") is False
    assert consumed.get("error_code") == FRESH_EXECUTOR_AUTHORITY_BINDING_CONFLICT


def test_same_inode_admission_mutation_never_admitted_or_consumed(
    tmp_path: Path,
) -> None:
    repo, head = _make_repo(tmp_path)
    authority_id, _admission_sha256 = _make_authority(repo, head)
    path = (
        Path(executor_authority_dir(str(repo))) / authority_id / ADMISSION_FILENAME
    )
    record = json.loads(path.read_text(encoding="utf-8"))
    record["created_at"] = "2" * 900_000
    path.write_text(json.dumps(record, sort_keys=True) + "\n", encoding="utf-8")
    path.chmod(0o600)
    expected_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    inode = path.stat().st_ino
    raw = path.read_bytes()
    offset = raw.index(head.encode("ascii"))
    stop = threading.Event()
    started = threading.Event()

    def mutate_same_inode() -> None:
        fd = os.open(path, os.O_WRONLY)
        try:
            started.set()
            replacement = b"1" if head[0] != "1" else b"2"
            while not stop.is_set():
                os.pwrite(fd, replacement, offset)
                replacement = b"2" if replacement == b"1" else b"1"
        finally:
            os.close(fd)

    thread = threading.Thread(target=mutate_same_inode)
    thread.start()
    started.wait(timeout=5)
    try:
        inspected = inspect_fresh_executor_authority_for_execution(
            str(repo),
            authority_id,
            expected_admission_sha256=expected_sha256,
            expected_head=head,
        )
        consumed = validate_and_create_execution_binding(
            str(repo),
            authority_id,
            **_validate_bind_kwargs(head, expected_sha256),
        )
    finally:
        stop.set()
        thread.join(timeout=5)

    assert path.stat().st_ino == inode
    assert inspected.get("ok") is False
    assert consumed.get("ok") is False
    assert not _binding_path(repo, authority_id).exists()


def test_foreign_owner_context_rejected_by_production_authority_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import runner.fresh_executor_authority as fea

    repo, head = _make_repo(tmp_path)
    authority_id, admission_sha256 = _make_authority(repo, head)
    actual_euid = os.geteuid()
    monkeypatch.setattr(fea.os, "geteuid", lambda: actual_euid + 1)

    inspected = inspect_fresh_executor_authority_for_execution(
        str(repo), authority_id, expected_admission_sha256=admission_sha256
    )
    consumed = validate_and_create_execution_binding(
        str(repo),
        authority_id,
        **_validate_bind_kwargs(head, admission_sha256),
    )

    assert read_fresh_executor_authority(str(repo), authority_id) is None
    assert inspected.get("ok") is False
    assert inspected.get("error_code") == FRESH_EXECUTOR_AUTHORITY_NOT_FOUND
    assert consumed.get("ok") is False
    assert consumed.get("error_code") == FRESH_EXECUTOR_AUTHORITY_NOT_FOUND
    assert not _binding_path(repo, authority_id).exists()


def test_project_root_symlink_rejected_by_all_production_authority_paths(
    tmp_path: Path,
) -> None:
    repo, head = _make_repo(tmp_path)
    authority_id, admission_sha256 = _make_authority(repo, head)
    linked_root = tmp_path / "linked-project"
    linked_root.symlink_to(repo, target_is_directory=True)

    inspected = inspect_fresh_executor_authority_for_execution(
        str(linked_root), authority_id, expected_admission_sha256=admission_sha256
    )
    consumed = validate_and_create_execution_binding(
        str(linked_root),
        authority_id,
        **_validate_bind_kwargs(head, admission_sha256),
    )

    assert read_fresh_executor_authority(str(linked_root), authority_id) is None
    assert read_execution_binding(str(linked_root), authority_id) is None
    assert inspected.get("ok") is False
    assert consumed.get("ok") is False
    assert not _binding_path(repo, authority_id).exists()


def test_binding_reader_exact_contract_and_safe_evidence(tmp_path: Path) -> None:
    repo, head = _make_repo(tmp_path)
    authority_id, admission_sha256 = _make_authority(repo, head)
    assert create_execution_binding(
        str(repo), authority_id, **_bind_kwargs(head, admission_sha256)
    ).get("ok") is True

    first = _read_execution_binding_verification(
        str(repo), authority_id, expected_run_id="exec_run_1"
    )
    second = _read_execution_binding_verification(
        str(repo), authority_id, expected_run_id="exec_run_1"
    )

    assert first["ok"] is True, first
    assert first["durable_contract"] == second["durable_contract"]
    assert set(first["durable_contract"]) == {
        "identity",
        "metadata",
        "raw_sha256",
        "content_sha256",
    }
    assert authority_id not in json.dumps(first["durable_contract"])
    assert admission_sha256 not in json.dumps(first["durable_contract"])
    raw_record = json.loads(_binding_path(repo, authority_id).read_text(encoding="utf-8"))
    assert raw_record["schema_version"] == "fresh_executor_execution_binding.v2"
    assert "_colameta_durable_identity" not in raw_record


@pytest.mark.parametrize("fsync_surface", ["file", "directory"])
def test_binding_creation_requires_file_and_directory_fsync(
    tmp_path: Path, monkeypatch, fsync_surface: str
) -> None:
    from runner import fresh_executor_authority as authority_module

    repo, head = _make_repo(tmp_path)
    authority_id, admission_sha256 = _make_authority(repo, head)
    original_fsync = authority_module.os.fsync

    def injected_fsync_failure(fd: int) -> None:
        is_directory = stat.S_ISDIR(os.fstat(fd).st_mode)
        if (fsync_surface == "directory") == is_directory:
            raise OSError(f"injected {fsync_surface} fsync failure")
        original_fsync(fd)

    monkeypatch.setattr(authority_module.os, "fsync", injected_fsync_failure)
    result = create_execution_binding(
        str(repo), authority_id, **_bind_kwargs(head, admission_sha256)
    )

    assert result["ok"] is False
    assert result["error_code"] == FRESH_EXECUTOR_AUTHORITY_BINDING_WRITE_FAILED


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_schema", "wrong_schema", "extra", "run", "truncated",
        "missing_event_stream", "bad_event_stream_identity", "bad_event_stream_digest",
    ],
)
def test_binding_reader_rejects_non_exact_contract(
    tmp_path: Path, mutation: str
) -> None:
    repo, head = _make_repo(tmp_path)
    authority_id, admission_sha256 = _make_authority(repo, head)
    assert create_execution_binding(
        str(repo), authority_id, **_bind_kwargs(head, admission_sha256)
    ).get("ok") is True
    path = _binding_path(repo, authority_id)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if mutation == "missing_schema":
        payload.pop("schema_version")
    elif mutation == "wrong_schema":
        payload["schema_version"] = "fresh_executor_execution_binding.v0"
    elif mutation == "extra":
        payload["unexpected"] = True
    elif mutation == "missing_event_stream":
        payload.pop("event_stream")
    elif mutation == "bad_event_stream_identity":
        payload["event_stream"]["identity"]["inode"] = True
    elif mutation == "bad_event_stream_digest":
        payload["event_stream"]["raw_sha256"] = "not-a-digest"
    path.write_text(
        '{"schema_version":"fresh_executor_execution_binding.v2"'
        if mutation == "truncated"
        else json.dumps(payload) + "\n",
        encoding="utf-8",
    )
    path.chmod(0o600)

    result = _read_execution_binding_verification(
        str(repo),
        authority_id,
        expected_run_id="different-run" if mutation == "run" else None,
    )

    assert result["ok"] is False
    assert result["error_code"] in {
        "BINDING_CONTRACT_FIELDS_INVALID",
        "BINDING_SCHEMA_VERSION_INVALID",
        "BINDING_RUN_ID_MISMATCH",
        "BINDING_JSON_INVALID",
        "BINDING_EVENT_STREAM_IDENTITY_INVALID",
        "BINDING_EVENT_STREAM_DIGEST_INVALID",
    }
    if mutation not in {"run"}:
        assert read_execution_binding(str(repo), authority_id) is None


@pytest.mark.parametrize("replacement_type", ["symlink", "fifo", "hardlink", "mode"])
def test_binding_reader_rejects_symlink_and_fifo(
    tmp_path: Path, replacement_type: str
) -> None:
    repo, head = _make_repo(tmp_path)
    authority_id, admission_sha256 = _make_authority(repo, head)
    assert create_execution_binding(
        str(repo), authority_id, **_bind_kwargs(head, admission_sha256)
    ).get("ok") is True
    path = _binding_path(repo, authority_id)
    raw = path.read_bytes()
    if replacement_type == "symlink":
        path.unlink()
        outside = tmp_path / "outside-binding-read.json"
        outside.write_bytes(raw)
        outside.chmod(0o600)
        path.symlink_to(outside)
    elif replacement_type == "fifo":
        path.unlink()
        os.mkfifo(path, 0o600)
    elif replacement_type == "hardlink":
        outside = tmp_path / "outside-binding-read.json"
        outside.write_bytes(raw)
        outside.chmod(0o600)
        path.unlink()
        os.link(outside, path)
    else:
        path.chmod(0o644)

    result = _read_execution_binding_verification(str(repo), authority_id)

    assert result["ok"] is False
    assert result["error_code"] in {"BINDING_FILE_UNSAFE", "BINDING_FILE_UNSTABLE"}


def test_binding_reader_rejects_unsafe_authority_directory_mode(
    tmp_path: Path,
) -> None:
    repo, head = _make_repo(tmp_path)
    authority_id, admission_sha256 = _make_authority(repo, head)
    assert create_execution_binding(
        str(repo), authority_id, **_bind_kwargs(head, admission_sha256)
    ).get("ok") is True
    _binding_path(repo, authority_id).parent.chmod(0o777)

    result = _read_execution_binding_verification(str(repo), authority_id)

    assert result["ok"] is False
    assert result["error_code"] == FRESH_EXECUTOR_AUTHORITY_MALFORMED


def test_binding_reader_exposes_changed_identity_for_same_content_replacement(
    tmp_path: Path,
) -> None:
    repo, head = _make_repo(tmp_path)
    authority_id, admission_sha256 = _make_authority(repo, head)
    assert create_execution_binding(
        str(repo), authority_id, **_bind_kwargs(head, admission_sha256)
    ).get("ok") is True
    path = _binding_path(repo, authority_id)
    first = _read_execution_binding_verification(str(repo), authority_id)
    replacement = path.with_name("binding-replacement.json")
    replacement.write_bytes(path.read_bytes())
    replacement.chmod(0o600)
    os.replace(replacement, path)
    second = _read_execution_binding_verification(str(repo), authority_id)

    assert first["ok"] is True and second["ok"] is True
    assert first["durable_contract"]["raw_sha256"] == second["durable_contract"]["raw_sha256"]
    assert first["durable_contract"]["identity"] != second["durable_contract"]["identity"]


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
    assert payload["schema_version"] == "fresh_executor_execution_binding.v2"
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
        event_stream=_event_stream_contract(),
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
        event_stream=_event_stream_contract(),
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
        event_stream=_event_stream_contract(),
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
        event_stream=_event_stream_contract(),
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
        event_stream=_event_stream_contract(),
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
        event_stream=_event_stream_contract(),
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
        event_stream=_event_stream_contract(),
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
        event_stream=_event_stream_contract(),
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


def test_preview_gate_requires_exact_branch_not_colameta_prefix(tmp_path: Path) -> None:
    from runner.mcp_executor_workflow import MCPExecutorWorkflowManager

    repo, head = _make_repo(tmp_path)
    _run(["git", "checkout", "-b", "colameta/stage-a/one"], repo)
    authority_id, admission_sha256 = _make_authority(repo, head)
    manager = MCPExecutorWorkflowManager(str(repo))
    common = {
        "authority_id": authority_id,
        "admission_sha256": admission_sha256,
        "provider": "codex",
        "executor_session_mode": "start_new",
        "current_head": head,
        "work_target": _work_target(),
    }

    assert manager._fresh_authority_preview_gate(
        **common, expected_git_branch="colameta/stage-a/one"
    ) is None
    assert manager._fresh_authority_preview_gate(
        **common, expected_git_branch="colameta/stage-a/two"
    ) == FRESH_EXECUTOR_AUTHORITY_MALFORMED
    assert manager._fresh_authority_preview_gate(
        **common, expected_git_branch="main"
    ) == FRESH_EXECUTOR_AUTHORITY_MALFORMED


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


def test_preview_preclaim_gate_rejects_non_exact_admission(tmp_path: Path) -> None:
    from runner.mcp_executor_workflow import MCPExecutorWorkflowManager

    repo, head = _make_repo(tmp_path)
    authority_id, _admission_sha256 = _make_authority(repo, head)
    path = (
        Path(executor_authority_dir(str(repo))) / authority_id / ADMISSION_FILENAME
    )
    record = json.loads(path.read_text(encoding="utf-8"))
    record["unexpected"] = True
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")
    path.chmod(0o600)
    admission_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()

    error = MCPExecutorWorkflowManager(str(repo))._fresh_authority_preview_gate(
        authority_id=authority_id,
        admission_sha256=admission_sha256,
        provider="codex",
        executor_session_mode="start_new",
        current_head=head,
        work_target=_work_target(),
    )

    assert error == FRESH_EXECUTOR_AUTHORITY_MALFORMED


def test_preview_preclaim_gate_rejects_unsafe_existing_binding(tmp_path: Path) -> None:
    from runner.mcp_executor_workflow import MCPExecutorWorkflowManager

    repo, head = _make_repo(tmp_path)
    authority_id, admission_sha256 = _make_authority(repo, head)
    assert create_execution_binding(
        str(repo), authority_id, **_bind_kwargs(head, admission_sha256)
    ).get("ok") is True
    _replace_unsafe_record(_binding_path(repo, authority_id), tmp_path, "fifo")

    error = MCPExecutorWorkflowManager(str(repo))._fresh_authority_preview_gate(
        authority_id=authority_id,
        admission_sha256=admission_sha256,
        provider="codex",
        executor_session_mode="start_new",
        current_head=head,
        work_target=_work_target(),
    )

    assert error == FRESH_EXECUTOR_AUTHORITY_MALFORMED


# ---------------------------------------------------------------------------
# F. P1-1 repair: read->bind directory identity split is CLOSED
# ---------------------------------------------------------------------------


def test_validate_and_bind_rejects_authority_pathname_swap(tmp_path: Path) -> None:
    """Deterministic reversal of the REREVIEW_1 split attack.

    The authority directory pathname is renamed away and a replacement
    directory is created at the original name immediately after the authority
    directory FD is opened.  Full current-path revalidation must reject the
    detached object before admission validation or binding creation.
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
            event_stream=_event_stream_contract(),
        )
    finally:
        fea._open_existing_authority_dir = real_open

    assert result.get("ok") is False, result
    assert result.get("error_code") == FRESH_EXECUTOR_AUTHORITY_MALFORMED
    moved = Path(state["moved"])
    assert not (moved / EXECUTION_BINDING_FILENAME).exists()
    assert not (validated_dir / EXECUTION_BINDING_FILENAME).exists()
    assert hashlib.sha256((moved / ADMISSION_FILENAME).read_bytes()).hexdigest() == admission_sha256


def test_gate_validate_and_bind_rejects_authority_pathname_swap(tmp_path: Path) -> None:
    """The production provider gate rejects a replaced authority pathname."""
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
            event_stream=_event_stream_contract(),
        )
    finally:
        fea._open_existing_authority_dir = real_open

    assert result.get("ok") is False, result
    assert result.get("error_code") == FRESH_EXECUTOR_AUTHORITY_MALFORMED
    moved = Path(state["moved"])
    assert not (moved / EXECUTION_BINDING_FILENAME).exists()
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
        event_stream=_event_stream_contract(),
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
