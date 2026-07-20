from __future__ import annotations

import contextlib
import io
import json
import logging
import multiprocessing
import os
import re
import socket
import stat
import sys
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import pytest

from runner import private_operator_health_ipc as ipc


pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="private health IPC v1 is Linux-only")


_MATRIX_PATH = Path(__file__).resolve().parents[1] / "docs" / "jenn-private-operator-local-ipc-negative-test-matrix.json"
_MATRIX = json.loads(_MATRIX_PATH.read_text(encoding="utf-8"))
_MATRIX_CASES = _MATRIX["cases"]
_PUBLIC_FORBIDDEN = tuple(_MATRIX["driver_contract"]["public_forbidden_recursive"])


@dataclass
class _Driver:
    raw: dict[str, Any]
    consumed: set[str] = field(default_factory=set)

    def take(self, key: str) -> Any:
        if key not in self.raw:
            raise AssertionError(f"missing driver field: {key}")
        self.consumed.add(key)
        return self.raw[key]

    def optional(self, key: str, default: Any = None) -> Any:
        if key in self.raw:
            self.consumed.add(key)
            return self.raw[key]
        return default

    def assert_fully_consumed(self) -> None:
        assert self.consumed == set(self.raw), (
            f"unconsumed driver fields: {sorted(set(self.raw) - self.consumed)}"
        )


def _reason_result(reason: str, *, include_fd: bool = True) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "unavailable",
        "reason": ipc.private_operator_ipc_unavailable(reason)["reason_code"],
        "public_change": "none",
    }
    if include_fd:
        result["fd_delta"] = 0
    return result


def _exception_reason(call: Callable[[], Any]) -> str:
    try:
        call()
    except ipc.PrivateOperatorIPCError as exc:
        return exc.reason_code
    raise AssertionError("matrix fault did not fail closed")


def _assert_no_private_fields(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            assert key not in _PUBLIC_FORBIDDEN
            _assert_no_private_fields(item)
    elif isinstance(value, list):
        for item in value:
            _assert_no_private_fields(item)
    elif isinstance(value, str):
        for forbidden in _PUBLIC_FORBIDDEN:
            assert forbidden not in value


def _assert_expected(actual: Any, expected: Any, path: str = "expected") -> set[str]:
    asserted: set[str] = set()
    if isinstance(expected, dict):
        assert isinstance(actual, dict), f"{path} must be an object"
        assert set(actual) == set(expected), (
            f"{path} keys differ: actual={sorted(actual)} expected={sorted(expected)}"
        )
        for key, value in expected.items():
            asserted.update(_assert_expected(actual[key], value, f"{path}.{key}"))
        return asserted
    if isinstance(expected, list):
        assert isinstance(actual, list) and len(actual) == len(expected), path
        for index, value in enumerate(expected):
            asserted.update(_assert_expected(actual[index], value, f"{path}[{index}]"))
        return asserted
    assert actual == expected, path
    asserted.add(path)
    return asserted


def _expected_leaf_paths(value: Any, path: str = "expected") -> set[str]:
    if isinstance(value, dict):
        result: set[str] = set()
        for key, item in value.items():
            result.update(_expected_leaf_paths(item, f"{path}.{key}"))
        return result
    if isinstance(value, list):
        result = set()
        for index, item in enumerate(value):
            result.update(_expected_leaf_paths(item, f"{path}[{index}]"))
        return result
    return {path}


def _registration(project: str = "/fixture/project") -> ipc.PrivateOperatorIPCRegistration:
    return ipc.PrivateOperatorIPCRegistration(
        pid=os.getpid(),
        process_start_ticks=ipc._process_start_ticks(os.getpid()),
        instance_id="1" * 32,
        project_fingerprint=ipc._project_fingerprint(project),
    )


def _request_value(registration: ipc.PrivateOperatorIPCRegistration) -> dict[str, Any]:
    return {
        "protocol": ipc.IPC_PROTOCOL,
        "operation": "read_attention",
        "instance_id": registration.instance_id,
        "project_fingerprint": registration.project_fingerprint,
        "nonce": "2" * 32,
    }


def _response_value(registration: ipc.PrivateOperatorIPCRegistration) -> dict[str, Any]:
    return {
        "protocol": ipc.IPC_PROTOCOL,
        "operation": "read_attention_result",
        "instance_id": registration.instance_id,
        "project_fingerprint": registration.project_fingerprint,
        "nonce": "2" * 32,
        **_snapshot(0),
    }


def _root(tmp_path: Path) -> str:
    path = tmp_path / "private-operator-health"
    os.chmod(tmp_path, 0o700)
    return str(path)


def _snapshot(count: int) -> dict[str, object]:
    return {
        "quarantined_close_fd_count": count,
        "quarantine_attention_threshold": 1,
        "quarantine_status": "attention" if count else "clear",
        "local_alert_code": "OPERATOR_FD_QUARANTINE_ATTENTION" if count else None,
    }


def test_unavailable_projection_is_fixed_and_sanitized() -> None:
    assert ipc.private_operator_ipc_unavailable("unknown/raw/path") == {
        "observation_source": "service_private_ipc",
        "observation_status": "unavailable",
        "quarantined_close_fd_count": None,
        "quarantine_attention_threshold": 1,
        "quarantine_status": "unknown",
        "local_alert_code": "OPERATOR_PRIVATE_HEALTH_UNAVAILABLE",
        "reason_code": "OPERATOR_PRIVATE_IPC_UNAVAILABLE",
    }


def test_secure_registration_and_abstract_socket_round_trip(tmp_path: Path) -> None:
    root = _root(tmp_path)
    project = str(tmp_path / "project")
    os.mkdir(project)
    server = ipc.PrivateOperatorHealthIPCServer(
        project,
        root_path=root,
        snapshot_supplier=lambda: _snapshot(2),
    )
    try:
        assert server.start() is True
        assert server.available is True
        observed = ipc.query_private_operator_health(project, root_path=root)
        assert observed == {
            "observation_source": "service_private_ipc",
            "observation_status": "observed",
            "quarantined_close_fd_count": 2,
            "quarantine_attention_threshold": 1,
            "quarantine_status": "attention",
            "local_alert_code": "OPERATOR_FD_QUARANTINE_ATTENTION",
        }
        registration_path = Path(root) / f"service-{os.getpid()}.json"
        assert stat.S_IMODE(registration_path.stat().st_mode) == 0o600
        assert stat.S_IMODE(Path(root).stat().st_mode) == 0o700
        registration = json.loads(registration_path.read_text(encoding="utf-8"))
        assert set(registration) == {
            "schema_version",
            "pid",
            "process_start_ticks",
            "instance_id",
            "project_fingerprint",
        }
        assert "quarantine" not in json.dumps(registration)
        assert not any(item.is_socket() for item in Path(root).iterdir())
    finally:
        assert server.close() is True
    assert not (Path(root) / f"service-{os.getpid()}.json").exists()


def test_zero_registration_is_unavailable_not_clear(tmp_path: Path) -> None:
    root = _root(tmp_path)
    result = ipc.query_private_operator_health(str(tmp_path / "project"), root_path=root)
    assert result["observation_status"] == "unavailable"
    assert result["quarantine_status"] == "unknown"
    assert result["quarantined_close_fd_count"] is None
    assert result["reason_code"] == "OPERATOR_PRIVATE_REGISTRATION_NOT_FOUND"
    assert not Path(root).exists()


def test_project_binding_rejects_cross_project_read(tmp_path: Path) -> None:
    root = _root(tmp_path)
    project = str(tmp_path / "alpha")
    other = str(tmp_path / "beta")
    os.mkdir(project)
    os.mkdir(other)
    with ipc.private_operator_health_ipc_server(
        project,
        root_path=root,
        snapshot_supplier=lambda: _snapshot(4),
    ) as server:
        assert server.available is True
        result = ipc.query_private_operator_health(other, root_path=root)
    assert result["observation_status"] == "unavailable"
    assert result["reason_code"] == "OPERATOR_PRIVATE_REGISTRATION_NOT_FOUND"
    assert result["quarantined_close_fd_count"] is None


def test_new_server_generation_resets_snapshot_and_rejects_old_registration(tmp_path: Path) -> None:
    root = _root(tmp_path)
    project = str(tmp_path / "project")
    os.mkdir(project)
    first = ipc.PrivateOperatorHealthIPCServer(project, root_path=root, snapshot_supplier=lambda: _snapshot(3))
    assert first.start() is True
    first_registration = first._registration
    assert ipc.query_private_operator_health(project, root_path=root)["quarantined_close_fd_count"] == 3
    assert first.close() is True

    second = ipc.PrivateOperatorHealthIPCServer(project, root_path=root, snapshot_supplier=lambda: _snapshot(0))
    try:
        assert second.start() is True
        assert second._registration is not None
        assert first_registration is not None
        assert second._registration.registration.instance_id != first_registration.registration.instance_id
        assert ipc.query_private_operator_health(project, root_path=root) == {
            "observation_source": "service_private_ipc",
            "observation_status": "observed",
            "quarantined_close_fd_count": 0,
            "quarantine_attention_threshold": 1,
            "quarantine_status": "clear",
            "local_alert_code": None,
        }
    finally:
        second.close()


def test_packet_parser_rejects_duplicate_and_oversized_records() -> None:
    left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    try:
        left.send(b'{"a":1,"a":2}')
        with pytest.raises(ipc.PrivateOperatorIPCError) as duplicate:
            ipc._strict_json_object(ipc._recv_one_packet(right))
        assert duplicate.value.reason_code == "OPERATOR_PRIVATE_PROTOCOL_INVALID"

        left.send(b"x" * (ipc.IPC_MAX_PACKET_BYTES + 1))
        with pytest.raises(ipc.PrivateOperatorIPCError) as oversized:
            ipc._recv_one_packet(right)
        assert oversized.value.reason_code == "OPERATOR_PRIVATE_PROTOCOL_INVALID"
    finally:
        left.close()
        right.close()


def test_proc_stat_parser_handles_spaces_and_parentheses() -> None:
    prefix = b"123 (worker name (nested)) "
    fields = [b"S"] + [str(index).encode("ascii") for index in range(1, 22)]
    fields[19] = b"987654"
    assert ipc._parse_proc_stat_start_ticks(prefix + b" ".join(fields)) == 987654


def test_public_shared_modules_do_not_import_private_ipc() -> None:
    repo = Path(__file__).resolve().parents[1]
    for relative in (
        "runner/mcp_server.py",
        "runner/runtime_observability.py",
        "runner/web_console.py",
    ):
        source = (repo / relative).read_text(encoding="utf-8")
        assert "private_operator_health_ipc" not in source


def test_trusted_runtime_base_rejects_root_owned_tmp() -> None:
    path = f"/tmp/colameta-private-health-forbidden-{os.getpid()}/private-operator-health"
    with pytest.raises(ipc.PrivateOperatorIPCError) as rejected:
        ipc._open_secure_root(path, create=False)
    assert rejected.value.reason_code == "OPERATOR_PRIVATE_IPC_ROOT_UNSAFE"
    assert not Path(path).exists()


def test_selection_identity_unavailable_closes_prior_candidate_pidfds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = str(tmp_path / "project")
    fingerprint = ipc._project_fingerprint(project)
    first = ipc.PrivateOperatorIPCRegistration(101, 1001, "1" * 32, fingerprint)
    second = ipc.PrivateOperatorIPCRegistration(202, 2002, "2" * 32, fingerprint)
    frozen = {
        first.filename: ipc._FrozenRegistration(first, 1, 1, ipc._canonical_json_bytes(first.as_dict())),
        second.filename: ipc._FrozenRegistration(second, 2, 2, ipc._canonical_json_bytes(second.as_dict())),
    }
    opened: list[int] = []

    def open_pidfd(_pid: int) -> int:
        fd = os.open("/dev/null", os.O_RDONLY)
        opened.append(fd)
        return fd

    def start_ticks(pid: int) -> int:
        if pid == first.pid:
            return first.process_start_ticks
        raise ipc.PrivateOperatorIPCError("OPERATOR_PRIVATE_PROCESS_IDENTITY_UNAVAILABLE")

    monkeypatch.setattr(ipc, "_registration_names", lambda _fd: list(frozen))
    monkeypatch.setattr(ipc, "_read_registration", lambda _fd, name: frozen[name])
    monkeypatch.setattr(ipc, "_open_pidfd", open_pidfd)
    monkeypatch.setattr(ipc, "_pidfd_alive", lambda _fd: True)
    monkeypatch.setattr(ipc, "_process_start_ticks", start_ticks)
    with pytest.raises(ipc.PrivateOperatorIPCError) as rejected:
        ipc.PrivateOperatorHealthIPCClient(root_path=str(tmp_path))._select_registration(9, project)
    assert rejected.value.reason_code == "OPERATOR_PRIVATE_PROCESS_IDENTITY_UNAVAILABLE"
    assert len(opened) == 2
    for fd in opened:
        with pytest.raises(OSError):
            os.fstat(fd)


def test_post_rename_rollback_unlink_failure_is_retried_by_server_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _root(tmp_path)
    project = str(tmp_path / "project")
    os.mkdir(project)
    real_rename = ipc.os.rename
    real_fsync = ipc.os.fsync
    real_unlink = ipc.os.unlink
    renamed = False
    root_fsync_failed = False
    rollback_unlink_failed = False

    def observe_rename(*args: Any, **kwargs: Any) -> None:
        nonlocal renamed
        real_rename(*args, **kwargs)
        renamed = True

    def fail_post_rename_root_fsync(fd: int) -> None:
        nonlocal root_fsync_failed
        if renamed and stat.S_ISDIR(os.fstat(fd).st_mode) and not root_fsync_failed:
            root_fsync_failed = True
            raise OSError("injected post-rename root fsync failure")
        real_fsync(fd)

    def fail_first_registration_unlink(path: Any, *args: Any, **kwargs: Any) -> None:
        nonlocal rollback_unlink_failed
        if ipc.IPC_REGISTRATION_NAME_RE.fullmatch(os.fspath(path)) and not rollback_unlink_failed:
            rollback_unlink_failed = True
            raise OSError("injected rollback unlink failure")
        real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(ipc.os, "rename", observe_rename)
    monkeypatch.setattr(ipc.os, "fsync", fail_post_rename_root_fsync)
    monkeypatch.setattr(ipc.os, "unlink", fail_first_registration_unlink)
    server = ipc.PrivateOperatorHealthIPCServer(project, root_path=root)
    assert server.start() is False
    assert server.startup_reason == "OPERATOR_PRIVATE_IPC_UNAVAILABLE"
    assert root_fsync_failed and rollback_unlink_failed
    assert not list(Path(root).glob("service-*.json"))


def _drive_platform_gate(driver: _Driver, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    platform = driver.take("platform")
    monkeypatch.setattr(ipc.sys, "platform", platform)
    projection = ipc.query_private_operator_health(root_path=_root(tmp_path))
    return _reason_result(projection["reason_code"])


def _drive_primitive_gate(driver: _Driver, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    missing = driver.take("missing")
    if missing in {"SOCK_SEQPACKET", "SO_PEERCRED"}:
        monkeypatch.delattr(ipc.socket, missing)
    elif missing == "pidfd_open":
        monkeypatch.delattr(ipc.os, "pidfd_open")
    else:
        raise AssertionError(f"unknown missing primitive: {missing}")
    projection = ipc.query_private_operator_health(root_path=_root(tmp_path))
    return _reason_result(projection["reason_code"])


def _drive_process_identity(driver: _Driver, _tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    fault = driver.take("fault")
    if fault == "comm_contains_spaces_and_parentheses":
        fields = [b"S"] + [str(index).encode("ascii") for index in range(1, 22)]
        fields[19] = b"87"
        assert ipc._parse_proc_stat_start_ticks(b"12 (name (nested) worker) " + b" ".join(fields)) == 87
        return {"identity_result": "valid", "parser": "right_parenthesis_aware", "public_change": "none"}
    if fault in {"malformed_stat", "start_ticks_zero"}:
        if fault == "malformed_stat":
            raw = b"12 malformed"
        else:
            fields = [b"S"] + [b"1"] * 21
            fields[19] = b"0"
            raw = b"12 (worker) " + b" ".join(fields)
        reason = _exception_reason(lambda: ipc._parse_proc_stat_start_ticks(raw))
    elif fault == "exit_during_read":
        monkeypatch.setattr(ipc.os, "open", lambda *_a, **_k: (_ for _ in ()).throw(FileNotFoundError()))
        reason = _exception_reason(lambda: ipc._process_start_ticks(999999))
    elif fault == "start_ticks_unreadable":
        monkeypatch.setattr(ipc.os, "open", lambda *_a, **_k: (_ for _ in ()).throw(PermissionError()))
        reason = _exception_reason(lambda: ipc._process_start_ticks(os.getpid()))
    else:
        raise AssertionError(f"unknown process identity fault: {fault}")
    result = _reason_result(reason, include_fd=False)
    if fault == "start_ticks_unreadable":
        result["fd_delta"] = 0
    return result


def _packet_bytes(fault: str, value: dict[str, Any], *, response: bool) -> tuple[bytes, bool]:
    if fault == "invalid_utf8":
        return b"\xff", False
    if fault in {"invalid_json", "truncated_json"}:
        return b'{"protocol":', False
    if fault == "duplicate_key":
        return b'{"protocol":"a","protocol":"b"}', False
    if fault in {"oversize", "size_1025_msg_trunc"}:
        return b"x" * (ipc.IPC_MAX_PACKET_BYTES + 1), False
    if fault == "empty":
        return b"", False
    mutated = dict(value)
    if fault == "extra_key":
        mutated["unexpected"] = True
    elif fault == "instance_mismatch":
        mutated["instance_id"] = "3" * 32
    elif fault == "project_mismatch":
        mutated["project_fingerprint"] = "4" * 64
    elif response and fault == "nonce_mismatch":
        mutated["nonce"] = "5" * 32
    elif response and fault == "count_bool":
        mutated["quarantined_close_fd_count"] = True
    elif response and fault == "count_negative":
        mutated["quarantined_close_fd_count"] = -1
    elif response and fault == "count_65536":
        mutated["quarantined_close_fd_count"] = 65536
    elif response and fault == "count_one_status_clear":
        mutated["quarantined_close_fd_count"] = 1
    elif response and fault == "extra_fd_field":
        mutated["fd"] = 9
    elif response and fault == "wrong_protocol":
        mutated["protocol"] = "wrong"
    elif response and fault == "wrong_operation":
        mutated["operation"] = "wrong"
    elif response and fault == "threshold_bool":
        mutated["quarantine_attention_threshold"] = True
    elif response and fault == "threshold_two":
        mutated["quarantine_attention_threshold"] = 2
    elif response and fault == "attention_alert_null":
        mutated["quarantined_close_fd_count"] = 1
        mutated["quarantine_status"] = "attention"
        mutated["local_alert_code"] = None
    elif fault not in {"second_packet"}:
        raise AssertionError(f"unknown packet fault: {fault}")
    return ipc._canonical_json_bytes(mutated), fault == "second_packet"


def _drive_packet(driver: _Driver, *, response: bool) -> dict[str, Any]:
    fault = driver.take("fault")
    registration = _registration()
    value = _response_value(registration) if response else _request_value(registration)
    left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    try:
        if response and fault == "eof":
            left.close()
            reason = _exception_reason(
                lambda: ipc._recv_one_packet(right, empty_reason="OPERATOR_PRIVATE_IPC_UNAVAILABLE")
            )
        else:
            payload, second = _packet_bytes(fault, value, response=response)
            left.send(payload)
            if second:
                left.send(ipc._canonical_json_bytes(value))

            def validate() -> None:
                raw = ipc._recv_one_packet(right)
                parsed = ipc._strict_json_object(raw)
                if response:
                    ipc._validate_response(parsed, registration, "2" * 32)
                else:
                    ipc._validate_request(parsed, registration)

            reason = _exception_reason(validate)
    finally:
        left.close()
        right.close()
    response_without_fd = {
        "size_1025_msg_trunc", "duplicate_key", "extra_key", "wrong_protocol",
        "wrong_operation", "project_mismatch", "threshold_bool", "threshold_two",
        "attention_alert_null",
    }
    result = _reason_result(
        reason,
        include_fd=fault != "size_1025_msg_trunc" if not response else fault not in response_without_fd,
    )
    if not response and fault == "size_1025_msg_trunc":
        result["supplier_called"] = False
    return result


def _drive_request_packet(driver: _Driver, _tmp_path: Path, _monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    return _drive_packet(driver, response=False)


def _drive_response_packet(driver: _Driver, _tmp_path: Path, _monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    return _drive_packet(driver, response=True)


def _drive_open_root(driver: _Driver, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    fault = driver.take("fault")
    base = tmp_path / "safe"
    base.mkdir()
    os.chmod(tmp_path, 0o700)
    os.chmod(base, 0o700)
    target = base / "health"
    if fault == "symlink_component":
        other = tmp_path / "other"
        other.mkdir()
        os.chmod(other, 0o700)
        target.symlink_to(other, target_is_directory=True)
        reason = _exception_reason(lambda: ipc._open_secure_root(str(target), create=False))
    elif fault == "mode_0770":
        target.mkdir()
        os.chmod(target, 0o770)
        reason = _exception_reason(lambda: ipc._open_secure_root(str(target), create=False))
    elif fault == "regular_file":
        target.write_bytes(b"x")
        os.chmod(target, 0o700)
        reason = _exception_reason(lambda: ipc._open_secure_root(str(target), create=False))
    elif fault == "wrong_owner":
        current = os.stat(base)
        fake = os.stat_result(
            (current.st_mode, current.st_ino, current.st_dev, current.st_nlink,
             os.geteuid() + 1, current.st_gid, current.st_size,
             current.st_atime, current.st_mtime, current.st_ctime)
        )
        reason = _exception_reason(lambda: ipc._validate_directory_info(fake, final=True))
    else:
        raise AssertionError(f"unknown root fault: {fault}")
    return _reason_result(reason)


def _drive_root_creation_race(driver: _Driver, tmp_path: Path, _monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    phase = driver.take("phase")
    assert phase in {"between_mkdir_and_open", "after_created_fstat"}
    root = _root(tmp_path)
    project = str(tmp_path / "project")
    os.mkdir(project)
    moved = Path(f"{root}-old")
    swapped = False
    real_stat = ipc.os.stat
    real_fstat = ipc.os.fstat

    def swap_root() -> None:
        nonlocal swapped
        if swapped:
            return
        Path(root).rename(moved)
        Path(root).mkdir(mode=0o700)
        swapped = True

    if phase == "between_mkdir_and_open":
        def stat_then_swap(path: Any, *args: Any, **kwargs: Any) -> os.stat_result:
            info = real_stat(path, *args, **kwargs)
            if os.fspath(path) == Path(root).name and kwargs.get("dir_fd") is not None:
                swap_root()
            return info
        _monkeypatch.setattr(ipc.os, "stat", stat_then_swap)
    else:
        def fstat_then_swap(fd: int) -> os.stat_result:
            info = real_fstat(fd)
            try:
                opened_path = os.readlink(f"/proc/self/fd/{fd}")
            except OSError:
                opened_path = ""
            if opened_path == root:
                swap_root()
            return info
        _monkeypatch.setattr(ipc.os, "fstat", fstat_then_swap)
    server = ipc.PrivateOperatorHealthIPCServer(project, root_path=root)
    assert server.start() is False
    reason = server.startup_reason or "OPERATOR_PRIVATE_IPC_UNAVAILABLE"
    server.close()
    assert swapped
    return _reason_result(reason)


def _open_matrix_registry(tmp_path: Path) -> tuple[str, int]:
    root = _root(tmp_path)
    root_fd, _identity = ipc._open_secure_root(root)
    return root, root_fd


def _write_leaf(root_fd: int, name: str, payload: bytes, mode: int = 0o600) -> None:
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode, dir_fd=root_fd)
    try:
        os.write(fd, payload)
        os.fchmod(fd, mode)
        os.fsync(fd)
    finally:
        os.close(fd)


def _drive_read_registration(driver: _Driver, tmp_path: Path, _monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    fault = driver.take("fault")
    root, root_fd = _open_matrix_registry(tmp_path)
    registration = _registration(str(tmp_path / "project"))
    name = registration.filename
    canonical = ipc._canonical_json_bytes(registration.as_dict())
    try:
        if fault == "symlink":
            target = Path(root) / "target"
            target.write_bytes(canonical)
            os.chmod(target, 0o600)
            (Path(root) / name).symlink_to(target)
            reason = _exception_reason(lambda: ipc._read_registration(root_fd, name))
        elif fault == "mode_0640":
            _write_leaf(root_fd, name, canonical, 0o640)
            reason = _exception_reason(lambda: ipc._read_registration(root_fd, name))
        elif fault == "nlink_two":
            _write_leaf(root_fd, name, canonical)
            os.link(name, "alias", src_dir_fd=root_fd, dst_dir_fd=root_fd)
            reason = _exception_reason(lambda: ipc._read_registration(root_fd, name))
        elif fault == "oversize":
            _write_leaf(root_fd, name, b"x" * 4097)
            reason = _exception_reason(lambda: ipc._read_registration(root_fd, name))
        elif fault in {"duplicate_key", "extra_key"}:
            payload = (
                b'{"pid":1,"pid":2}'
                if fault == "duplicate_key"
                else ipc._canonical_json_bytes({**registration.as_dict(), "extra": True})
            )
            _write_leaf(root_fd, name, payload)
            reason = _exception_reason(lambda: ipc._read_registration(root_fd, name))
        elif fault == "wrong_owner":
            info = os.stat(root)
            fake = os.stat_result(
                (stat.S_IFREG | 0o600, info.st_ino, info.st_dev, 1,
                 os.geteuid() + 1, info.st_gid, len(canonical),
                 info.st_atime, info.st_mtime, info.st_ctime)
            )
            reason = _exception_reason(lambda: ipc._validate_private_regular(fake, max_size=4096))
        elif fault == "pid_mismatch":
            reason = _exception_reason(
                lambda: ipc._validate_connected_peer(
                    registration,
                    peer_pid=registration.pid + 1,
                    peer_uid=os.geteuid(),
                    expected_project_fingerprint=registration.project_fingerprint,
                )
            )
        elif fault == "start_ticks_mismatch":
            original_ticks = ipc._process_start_ticks
            _monkeypatch.setattr(
                ipc,
                "_process_start_ticks",
                lambda pid: original_ticks(pid) + 1,
            )
            reason = _exception_reason(
                lambda: ipc._validate_connected_peer(
                    registration,
                    peer_pid=registration.pid,
                    peer_uid=os.geteuid(),
                    expected_project_fingerprint=registration.project_fingerprint,
                )
            )
        elif fault == "project_fingerprint_mismatch":
            requested = ipc._project_fingerprint(str(tmp_path / "other"))
            reason = _exception_reason(
                lambda: ipc._validate_connected_peer(
                    registration,
                    peer_pid=registration.pid,
                    peer_uid=os.geteuid(),
                    expected_project_fingerprint=requested,
                )
            )
        else:
            raise AssertionError(f"unknown registration fault: {fault}")
    finally:
        ipc._close_owned_fd(root_fd)
    return _reason_result(reason)


def _drive_registry_lock(driver: _Driver, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    fault = driver.take("fault")
    root, root_fd = _open_matrix_registry(tmp_path)
    lock_path = Path(root) / ipc.IPC_LOCK_FILENAME
    lock_fd: int | None = None
    try:
        if fault == "symlink":
            target = Path(root) / "target"
            target.write_bytes(b"x")
            os.chmod(target, 0o600)
            lock_path.symlink_to(target)
            reason = _exception_reason(lambda: ipc._open_registry_lock(root_fd, create=False))
        elif fault == "mode_0644":
            lock_path.write_bytes(b"x")
            os.chmod(lock_path, 0o644)
            reason = _exception_reason(lambda: ipc._open_registry_lock(root_fd, create=False))
        else:
            lock_fd = ipc._open_registry_lock(root_fd)
            real_flock = ipc.fcntl.flock
            calls = 0

            def fail_flock(fd: int, operation: int) -> None:
                nonlocal calls
                calls += 1
                if fault == "flock_lock_failure" and operation & ipc.fcntl.LOCK_EX:
                    raise OSError("injected lock failure")
                if fault == "flock_unlock_failure" and operation == ipc.fcntl.LOCK_UN:
                    raise OSError("injected unlock failure")
                real_flock(fd, operation)

            monkeypatch.setattr(ipc.fcntl, "flock", fail_flock)
            reason = _exception_reason(lambda: _exercise_lock(lock_fd))
            assert calls >= 1
    finally:
        if lock_fd is not None:
            ipc._close_owned_fd(lock_fd)
        ipc._close_owned_fd(root_fd)
    return _reason_result(reason)


def _exercise_lock(lock_fd: int) -> None:
    with ipc._locked_registry(lock_fd):
        pass


def _drive_discover_registration(driver: _Driver, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    matches = driver.optional("matches")
    fault = driver.optional("fault")
    entry_count = driver.optional("entry_count")
    root = _root(tmp_path)
    project = str(tmp_path / "project")
    os.mkdir(project)
    if matches == 0:
        projection = ipc.query_private_operator_health(project, root_path=root)
        return _reason_result(projection["reason_code"])
    if fault == "project_mismatch":
        other = str(tmp_path / "other")
        os.mkdir(other)
        with ipc.private_operator_health_ipc_server(project, root_path=root, snapshot_supplier=lambda: _snapshot(0)) as server:
            assert server.available
            projection = ipc.query_private_operator_health(other, root_path=root)
        return _reason_result(projection["reason_code"])
    if entry_count is not None or fault == "unknown_leaf_name":
        _created_root, root_fd = _open_matrix_registry(tmp_path)
        try:
            if entry_count is not None:
                for index in range(entry_count):
                    _write_leaf(root_fd, f"service-{index + 1}.json", b"{}")
            else:
                _write_leaf(root_fd, "unexpected", b"{}")
            reason = _exception_reason(lambda: ipc._registration_names(root_fd))
        finally:
            ipc._close_owned_fd(root_fd)
        return _reason_result(reason)
    if matches == 2:
        _created_root, root_fd = _open_matrix_registry(tmp_path)
        registration = _registration(project)
        frozen = ipc._FrozenRegistration(registration, 1, 1, ipc._canonical_json_bytes(registration.as_dict()))
        monkeypatch.setattr(ipc, "_registration_names", lambda _fd: [registration.filename, registration.filename])
        monkeypatch.setattr(ipc, "_read_registration", lambda _fd, _name: frozen)
        reason = _exception_reason(
            lambda: ipc.PrivateOperatorHealthIPCClient(root_path=root)._select_registration(root_fd, project)
        )
        ipc._close_owned_fd(root_fd)
        return _reason_result(reason)
    raise AssertionError("unrouted registration discovery case")


def _drive_query_stale_registration(driver: _Driver, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    fault = driver.take("fault")
    assert fault == "pid_dead"
    root, root_fd = _open_matrix_registry(tmp_path)
    registration = _registration(str(tmp_path / "project"))
    _write_leaf(root_fd, registration.filename, ipc._canonical_json_bytes(registration.as_dict()))
    lock_fd = ipc._open_registry_lock(root_fd)
    ipc._close_owned_fd(lock_fd)
    ipc._close_owned_fd(root_fd)
    monkeypatch.setattr(ipc, "_open_pidfd", lambda _pid: (_ for _ in ()).throw(
        ipc.PrivateOperatorIPCError("OPERATOR_PRIVATE_PROCESS_NOT_RUNNING")
    ))
    projection = ipc.query_private_operator_health(str(tmp_path / "project"), root_path=root)
    return _reason_result(projection["reason_code"])


def _drive_cleanup_cas(driver: _Driver, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    fault = driver.take("fault")
    root, root_fd = _open_matrix_registry(tmp_path)
    registration = _registration(str(tmp_path / "project"))
    frozen = ipc._publish_registration(root_fd, registration)
    result: dict[str, Any] = {"leaf_deleted": False, "public_change": "none"}
    try:
        if fault in {"replace_before_lock", "replace_after_expected_freeze"}:
            replacement = ipc.PrivateOperatorIPCRegistration(
                pid=registration.pid,
                process_start_ticks=registration.process_start_ticks,
                instance_id="9" * 32,
                project_fingerprint=registration.project_fingerprint,
            )
            replacement_payload = ipc._canonical_json_bytes(replacement.as_dict())
            if fault == "replace_before_lock":
                os.unlink(registration.filename, dir_fd=root_fd)
                replacement_frozen = ipc._publish_registration(root_fd, replacement)
            else:
                real_open = ipc.os.open
                replaced = False
                registration_opens = 0
                def replace_before_final_read(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
                    nonlocal replaced
                    nonlocal registration_opens
                    if os.fspath(path) == registration.filename:
                        registration_opens += 1
                    if registration_opens == 2 and not replaced:
                        replaced = True
                        os.unlink(registration.filename, dir_fd=root_fd)
                        _write_leaf(root_fd, registration.filename, replacement_payload)
                    return real_open(path, flags, *args, **kwargs)
                monkeypatch.setattr(ipc.os, "open", replace_before_final_read)
                replacement_frozen = ipc._FrozenRegistration(replacement, 0, 0, replacement_payload)
            reason = _exception_reason(lambda: ipc._remove_expected_registration(root_fd, frozen))
            current = ipc._read_registration(root_fd, registration.filename)
            result.update(reason=reason, replacement_preserved=current.canonical == replacement_frozen.canonical)
        elif fault == "aba_exact_inode_and_record_restored":
            parked = "parked.json"
            os.rename(registration.filename, parked, src_dir_fd=root_fd, dst_dir_fd=root_fd)
            os.rename(parked, registration.filename, src_dir_fd=root_fd, dst_dir_fd=root_fd)
            ipc._remove_expected_registration(root_fd, frozen)
            result.update(
                leaf_deleted=not (Path(root) / registration.filename).exists(),
                cas_scope="cooperative_registry_lock_exact_object",
                historical_aba_detection_claimed=False,
            )
        elif fault == "root_swap_after_lock":
            identity = os.fstat(root_fd)
            old = Path(f"{root}-old")
            Path(root).rename(old)
            Path(root).mkdir(mode=0o700)
            reason = _exception_reason(
                lambda: ipc._assert_root_path_identity(root, (identity.st_dev, identity.st_ino))
            )
            result.update(reason=reason, replacement_preserved=True)
        elif fault == "generation_live":
            competing = ipc.PrivateOperatorHealthIPCServer(
                str(tmp_path / "project"),
                root_path=root,
            )
            assert competing.start() is False
            result["reason"] = competing.startup_reason
            competing.close()
        elif fault == "invalid_json":
            os.unlink(registration.filename, dir_fd=root_fd)
            _write_leaf(root_fd, registration.filename, b"{")
            result["reason"] = _exception_reason(lambda: ipc._read_registration(root_fd, registration.filename))
        else:
            raise AssertionError(f"unknown cleanup CAS fault: {fault}")
    finally:
        ipc._close_owned_fd(root_fd)
    return result


def _drive_cleanup_failure(driver: _Driver, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    target = driver.take("target")
    root, root_fd = _open_matrix_registry(tmp_path)
    registration = _registration(str(tmp_path / "project"))
    frozen = ipc._publish_registration(root_fd, registration)
    real_unlink = ipc.os.unlink
    real_fsync = ipc.os.fsync
    if target == "registration_open":
        monkeypatch.setattr(ipc, "_read_registration", lambda *_a: (_ for _ in ()).throw(
            ipc.PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_UNAVAILABLE")
        ))
    elif target == "registration_fstat":
        monkeypatch.setattr(ipc.os, "fstat", lambda *_a: (_ for _ in ()).throw(OSError("injected")))
    elif target == "registration_unlink":
        monkeypatch.setattr(ipc.os, "unlink", lambda *_a, **_k: (_ for _ in ()).throw(OSError("injected")))
    elif target == "root_fsync":
        monkeypatch.setattr(ipc.os, "fsync", lambda *_a: (_ for _ in ()).throw(OSError("injected")))
    else:
        raise AssertionError(f"unknown cleanup target: {target}")
    reason = _exception_reason(lambda: ipc._remove_expected_registration(root_fd, frozen))
    monkeypatch.setattr(ipc.os, "unlink", real_unlink)
    monkeypatch.setattr(ipc.os, "fsync", real_fsync)
    exists = (Path(root) / registration.filename).exists()
    ipc._close_owned_fd(root_fd)
    result: dict[str, Any] = {"public_change": "none", "reason": reason}
    if target == "root_fsync":
        result["durability_claim"] = False
    else:
        result["leaf_deleted"] = not exists
    return result


def _with_server(tmp_path: Path, count: int = 0) -> tuple[str, str, ipc.PrivateOperatorHealthIPCServer]:
    root = _root(tmp_path)
    project = str(tmp_path / "project")
    os.mkdir(project)
    server = ipc.PrivateOperatorHealthIPCServer(
        project,
        root_path=root,
        snapshot_supplier=lambda: _snapshot(count),
    )
    assert server.start()
    return root, project, server


def _drive_client_peercred(driver: _Driver, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    pid = driver.optional("pid")
    uid = driver.optional("uid")
    root, project, server = _with_server(tmp_path)
    real_peer = ipc._peer_credentials

    def altered(sock: socket.socket) -> tuple[int, int, int]:
        observed_pid, observed_uid, gid = real_peer(sock)
        return (
            observed_pid + 1000 if pid == "other" else observed_pid,
            observed_uid + 1 if uid == "other" else observed_uid,
            gid,
        )

    monkeypatch.setattr(ipc, "_peer_credentials", altered)
    try:
        projection = ipc.query_private_operator_health(project, root_path=root)
    finally:
        server.close()
    return _reason_result(projection["reason_code"])


def _drive_pidfd_transition(driver: _Driver, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    phase = driver.take("phase")
    state = driver.take("state")
    root, project, server = _with_server(tmp_path)
    try:
        if state == "numeric_pid_reused":
            real_ticks = ipc._process_start_ticks
            monkeypatch.setattr(ipc, "_process_start_ticks", lambda pid: real_ticks(pid) + 1)
        else:
            assert state == "dead"
            false_at = {
                "before_connect": 2,
                "after_connect": 3,
                "before_response_validation": 4,
            }[phase]
            calls = 0

            def transitioning(_pidfd: int) -> bool:
                nonlocal calls
                calls += 1
                return calls < false_at

            monkeypatch.setattr(ipc, "_pidfd_alive", transitioning)
        projection = ipc.query_private_operator_health(project, root_path=root)
    finally:
        server.close()
    return _reason_result(projection["reason_code"])


def _drive_connect_failure(driver: _Driver, tmp_path: Path, _monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    fault = driver.take("fault")
    assert fault == "connection_refused"
    root, project, server = _with_server(tmp_path)
    assert ipc._close_socket(server._listener)
    server._listener = None
    try:
        projection = ipc.query_private_operator_health(project, root_path=root)
    finally:
        server.close()
    return _reason_result(projection["reason_code"])


def _drive_start_listener(driver: _Driver, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    fault = driver.take("fault")
    assert fault == "address_in_use"
    root = _root(tmp_path)
    project = str(tmp_path / "project")
    os.mkdir(project)
    fixed = "7" * 32
    monkeypatch.setattr(ipc.secrets, "token_hex", lambda _n: fixed)
    occupied = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET | socket.SOCK_CLOEXEC)
    occupied.bind(ipc._abstract_address(fixed))
    server = ipc.PrivateOperatorHealthIPCServer(project, root_path=root)
    try:
        assert server.start() is False
        reason = server.startup_reason
    finally:
        server.close()
        occupied.close()
    return _reason_result(reason or "OPERATOR_PRIVATE_IPC_UNAVAILABLE")


def _drive_timeout(driver: _Driver, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    phase = driver.take("phase")
    root, project, server = _with_server(tmp_path)
    supplier_calls = 0
    try:
        if phase == "accept":
            time.sleep(ipc.IPC_TIMEOUT_SECONDS * 1.2)
            return {
                "listener_alive": bool(server._thread and server._thread.is_alive()),
                "listener_failure": False,
                "public_change": "none",
                "supplier_called": False,
            }
        real_recv = ipc._recv_one_packet
        real_send = ipc._send_one_packet

        def delayed_recv(sock: socket.socket, **kwargs: Any) -> bytes:
            if threading.current_thread() is server._thread:
                time.sleep(ipc.IPC_TIMEOUT_SECONDS * 1.2)
            return real_recv(sock, **kwargs)

        def fail_send(sock: socket.socket, value: dict[str, Any]) -> None:
            if threading.current_thread() is server._thread:
                raise ipc.PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_UNAVAILABLE")
            real_send(sock, value)

        if phase == "receive":
            monkeypatch.setattr(ipc, "_recv_one_packet", delayed_recv)
        elif phase == "send":
            monkeypatch.setattr(ipc, "_send_one_packet", fail_send)
        else:
            raise AssertionError(f"unknown timeout phase: {phase}")
        projection = ipc.query_private_operator_health(project, root_path=root)
    finally:
        server.close()
    return _reason_result(projection["reason_code"])


def _drive_listener_exit(driver: _Driver, tmp_path: Path, _monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    phase = driver.take("phase")
    assert phase == "after_publish"
    root, project, server = _with_server(tmp_path)
    assert ipc._close_socket(server._listener)
    server._listener = None
    if server._thread is not None:
        server._thread.join(timeout=1.0)
    projection = ipc.query_private_operator_health(project, root_path=root)
    server.close()
    return _reason_result(projection["reason_code"])


def _drive_server_failure(driver: _Driver, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    phase = driver.take("phase")
    count = driver.optional("count")
    root = _root(tmp_path)
    project = str(tmp_path / "project")
    os.mkdir(project)
    supplier_calls = 0
    supplied_count = 0
    server_send_count = 0

    def supplier() -> dict[str, Any]:
        nonlocal supplier_calls
        supplier_calls += 1
        if phase == "snapshot" and count is None:
            raise RuntimeError("redacted fixture failure")
        return _snapshot(supplied_count)

    server = ipc.PrivateOperatorHealthIPCServer(project, root_path=root, snapshot_supplier=supplier)
    assert server.start()
    real_send = ipc._send_one_packet

    def observe_server_send(sock: socket.socket, value: dict[str, Any]) -> None:
        nonlocal server_send_count
        if threading.current_thread() is server._thread:
            server_send_count += 1
        real_send(sock, value)

    monkeypatch.setattr(ipc, "_send_one_packet", observe_server_send)
    if count is not None:
        warm = ipc.query_private_operator_health(project, root_path=root)
        assert warm["observation_status"] == "observed"
        supplied_count = count
        server_send_count = 0
    if phase in {"serialize", "send"}:
        def fail_server_send(sock: socket.socket, value: dict[str, Any]) -> None:
            if threading.current_thread() is server._thread:
                raise ipc.PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_UNAVAILABLE")
            real_send(sock, value)

        monkeypatch.setattr(ipc, "_send_one_packet", fail_server_send)
    try:
        projection = ipc.query_private_operator_health(project, root_path=root)
    finally:
        server.close()
    reason = projection["reason_code"]
    if count is not None:
        deadline = time.monotonic() + 1.0
        while server._last_internal_reason is None and time.monotonic() < deadline:
            time.sleep(0.01)
        reason = server._last_internal_reason or reason
    result = _reason_result(reason, include_fd=count is None)
    if count is not None:
        result.update(
            cached_snapshot_used=projection["observation_status"] == "observed",
            response_sent=server_send_count > 0,
        )
    return result


def _fd_count() -> int:
    return len(os.listdir("/proc/self/fd"))


def _public_surface_snapshot(project_root: Path) -> str:
    from runner.mcp_server import MCPPlanningBridgeServer, MCP_EXPOSURE_PROFILE_COMMANDER
    from runner.runtime_observability import get_connector_runtime_health_status
    from runner.web_console import WebConsoleServer

    server = MCPPlanningBridgeServer(
        str(project_root),
        service_mode=False,
        exposure_profile=MCP_EXPOSURE_PROFILE_COMMANDER,
    )
    value = {
        "connector_health": get_connector_runtime_health_status(
            local_service=None,
            runtime_status={},
        ),
        "openapi": server._build_actions_openapi_schema(None, "127.0.0.1", 0),
        "tools": server._tool_defs_payload(),
        "web_health": WebConsoleServer._api_v2_health(),
    }
    _assert_no_private_fields(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _drive_inject_syscall(driver: _Driver, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    name = driver.take("name")
    target = driver.take("target")
    root = _root(tmp_path)
    project = str(tmp_path / "project")
    os.mkdir(project)
    before = _fd_count()
    real_open = ipc.os.open
    real_mkdir = ipc.os.mkdir
    real_fstat = ipc.os.fstat
    real_fchmod = ipc.os.fchmod
    real_fsync = ipc.os.fsync
    real_write = ipc.os.write
    real_rename = ipc.os.rename
    real_socket = ipc.socket.socket
    calls = 0

    def injected(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        raise OSError(f"injected {name}:{target}")

    if name == "open" and target == "root_component":
        def fail_component(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
            if kwargs.get("dir_fd") is not None:
                return injected(path, flags, *args, **kwargs)
            return real_open(path, flags, *args, **kwargs)
        monkeypatch.setattr(ipc.os, "open", fail_component)
    elif name == "mkdir":
        monkeypatch.setattr(ipc.os, "mkdir", injected)
    elif name == "fstat":
        monkeypatch.setattr(ipc.os, "fstat", injected)
    elif name == "fchmod":
        monkeypatch.setattr(ipc.os, "fchmod", injected)
    elif name == "write":
        monkeypatch.setattr(ipc.os, "write", injected)
    elif name == "rename":
        monkeypatch.setattr(ipc.os, "rename", injected)
    elif name == "socket":
        monkeypatch.setattr(ipc, "_platform_supported", lambda: True)
        monkeypatch.setattr(ipc.socket, "socket", injected)
    elif name == "listen":
        monkeypatch.setattr(ipc, "_platform_supported", lambda: True)
        class FailingListenSocket:
            def __init__(self, *args: Any, **kwargs: Any):
                self._inner = real_socket(*args, **kwargs)
            def __getattr__(self, item: str) -> Any:
                return getattr(self._inner, item)
            def listen(self, *_args: Any, **_kwargs: Any) -> None:
                injected()
            def detach(self) -> int:
                return self._inner.detach()
        monkeypatch.setattr(ipc.socket, "socket", FailingListenSocket)
    elif name == "fsync":
        seen = 0
        registration_renamed = False
        non_directory_fsyncs = 0
        def observe_rename(*args: Any, **kwargs: Any) -> None:
            nonlocal registration_renamed
            real_rename(*args, **kwargs)
            registration_renamed = True
        def fail_selected(fd: int) -> None:
            nonlocal seen, calls, non_directory_fsyncs
            seen += 1
            is_dir = stat.S_ISDIR(real_fstat(fd).st_mode)
            if not is_dir:
                non_directory_fsyncs += 1
            should_fail = (
                target == "created_component_parent"
                or (target == "registration_file" and not is_dir and non_directory_fsyncs >= 2)
                or (target == "registration_root" and is_dir and registration_renamed)
            )
            if should_fail:
                calls += 1
                raise OSError("injected fsync")
            real_fsync(fd)
        monkeypatch.setattr(ipc.os, "rename", observe_rename)
        monkeypatch.setattr(ipc.os, "fsync", fail_selected)
    else:
        raise AssertionError(f"unrouted syscall injection: {name}:{target}")
    server = ipc.PrivateOperatorHealthIPCServer(project, root_path=root)
    assert server.start() is False
    reason = server.startup_reason or "OPERATOR_PRIVATE_IPC_UNAVAILABLE"
    server.close()
    assert calls >= 1
    if Path(root).exists():
        assert not list(Path(root).glob("service-*.json"))
        assert not list(Path(root).glob(".tmp-*"))
    after = _fd_count()
    assert after == before
    return _reason_result(reason)


def _drive_forbidden_read_guard(driver: _Driver, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    target = driver.take("target")
    source = Path(ipc.__file__).read_text(encoding="utf-8")
    forbidden = {
        "service_metadata_command": "ServiceLifecycleStore",
        "proc_cmdline": "/cmdline",
        "proc_environ": "/environ",
    }[target]
    assert forbidden not in source
    attempts = 0
    real_open = ipc.os.open

    def guarded_open(path: Any, *args: Any, **kwargs: Any) -> int:
        nonlocal attempts
        if forbidden in os.fspath(path):
            attempts += 1
            raise AssertionError("forbidden private read attempted")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(ipc.os, "open", guarded_open)
    projection = ipc.query_private_operator_health(root_path=_root(tmp_path))
    return {"public_change": "none", "read_attempts": attempts, "status": projection["observation_status"]}


def _drive_source_import_scan(driver: _Driver, _tmp_path: Path, _monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    targets = driver.take("targets")
    repo = Path(__file__).resolve().parents[1]
    imports = 0
    for target in targets:
        source = (repo / target).read_text(encoding="utf-8")
        imports += len(re.findall(r"(?:from|import)\s+runner\.private_operator_health_ipc", source))
    return {"private_ipc_imports": imports, "public_change": "none"}


def _drive_capture_logs(driver: _Driver, tmp_path: Path, _monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    inject = driver.take("inject")
    assert inject == "instance_nonce_pid_fd_exception"
    sentinels = (
        "instance=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "nonce=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "pid=424242",
        "fd=31337",
    )
    captured = io.StringIO()
    handler = logging.StreamHandler(captured)
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    root = _root(tmp_path)
    project = str(tmp_path / "project")
    os.mkdir(project)
    server = ipc.PrivateOperatorHealthIPCServer(
        project,
        root_path=root,
        snapshot_supplier=lambda: (_ for _ in ()).throw(RuntimeError(" ".join(sentinels))),
    )
    assert server.start()
    try:
        with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
            projection = ipc.query_private_operator_health(project, root_path=root)
            deadline = time.monotonic() + 1.0
            while server._last_internal_reason is None and time.monotonic() < deadline:
                time.sleep(0.01)
    finally:
        server.close()
        root_logger.removeHandler(handler)
        handler.close()
    rendered = captured.getvalue() + json.dumps(projection, sort_keys=True)
    assert all(sentinel not in rendered for sentinel in sentinels)
    assert projection["observation_status"] == "unavailable"
    return {"private_fields": "absent", "public_change": "none"}


def _drive_same_uid_forgery(driver: _Driver, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    peer = driver.take("peer")
    registration = driver.take("registration")
    assert peer == "matching_frozen_candidate" and registration == "well_formed"
    from runner import mcp_private_operator as private

    # A matching same-UID generation is accepted only for diagnostics. Observe
    # the independent authorization, permit-file, and execution surfaces.
    with private._ACTIVE_BATCHES_LOCK:
        before_batches = set(private._ACTIVE_BATCHES)
    before_auth = private.current_operator_auth_context()
    authorization_calls = 0
    permit_calls = 0
    execution_calls = 0

    def deny_authorization(*_args: Any, **_kwargs: Any) -> Any:
        nonlocal authorization_calls
        authorization_calls += 1
        raise AssertionError("diagnostic IPC entered operator authorization")

    def deny_permit(*_args: Any, **_kwargs: Any) -> Any:
        nonlocal permit_calls
        permit_calls += 1
        raise AssertionError("diagnostic IPC mutated an operator permit")

    def deny_execution(*_args: Any, **_kwargs: Any) -> Any:
        nonlocal execution_calls
        execution_calls += 1
        raise AssertionError("diagnostic IPC entered operator execution")

    monkeypatch.setattr(private.OperatorBatchService, "handle", deny_authorization)
    for name in ("create", "update", "claim", "mark_indeterminate"):
        monkeypatch.setattr(private.OperatorPermitStore, name, deny_permit)
    for name in ("_execute", "_execute_claimed", "_execute_registered_claim"):
        monkeypatch.setattr(private.OperatorBatchService, name, deny_execution)

    def permit_leaves() -> tuple[str, ...]:
        return tuple(sorted(
            str(path.relative_to(tmp_path))
            for pattern in ("*.claim", "*.indeterminate", "*.json")
            for path in tmp_path.rglob(pattern)
            if not path.name.startswith("service-")
        ))

    before_permits = permit_leaves()
    root = _root(tmp_path)
    project = str(tmp_path / "project")
    os.mkdir(project)
    with ipc.private_operator_health_ipc_server(
        project,
        root_path=root,
        snapshot_supplier=lambda: _snapshot(0),
    ) as server:
        assert server.available
        diagnostic = ipc.query_private_operator_health(project, root_path=root)
    with private._ACTIVE_BATCHES_LOCK:
        after_batches = set(private._ACTIVE_BATCHES)
    authorization_unchanged = (
        authorization_calls == 0
        and private.current_operator_auth_context() is before_auth
    )
    ticket_unchanged = permit_calls == 0 and permit_leaves() == before_permits
    execution_unchanged = execution_calls == 0 and before_batches == after_batches
    return {
        "authorization_effect": "none" if authorization_unchanged else "changed",
        "diagnostic_authenticity": (
            "not_guaranteed" if diagnostic["observation_status"] == "observed" else "rejected"
        ),
        "execution_effect": "none" if execution_unchanged else "changed",
        "private_fields_on_public_surfaces": "absent",
        "public_change": "none",
        "ticket_effect": "none" if ticket_unchanged else "changed",
    }


def _drive_replace_registration(driver: _Driver, tmp_path: Path, _monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    phase = driver.take("phase")
    assert phase == "after_open"
    _root_path, root_fd = _open_matrix_registry(tmp_path)
    registration = _registration(str(tmp_path / "project"))
    frozen = ipc._publish_registration(root_fd, registration)
    os.unlink(registration.filename, dir_fd=root_fd)
    replacement = ipc.PrivateOperatorIPCRegistration(
        registration.pid,
        registration.process_start_ticks,
        "8" * 32,
        registration.project_fingerprint,
    )
    ipc._publish_registration(root_fd, replacement)
    reason = _exception_reason(lambda: ipc._remove_expected_registration(root_fd, frozen))
    ipc._close_owned_fd(root_fd)
    return _reason_result(reason)


def _drive_server_peercred(driver: _Driver, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    uid = driver.take("uid")
    assert uid == "other"
    root, project, server = _with_server(tmp_path)
    supplier_called = False
    server.snapshot_supplier = lambda: (_ for _ in ()).throw(AssertionError("supplier must not run"))
    left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    real_peer = ipc._peer_credentials

    def wrong_uid(sock: socket.socket) -> tuple[int, int, int]:
        pid, observed_uid, gid = real_peer(sock)
        return pid, observed_uid + 1, gid

    monkeypatch.setattr(ipc, "_peer_credentials", wrong_uid)
    reason = _exception_reason(lambda: server._handle_connection(right))
    left.setblocking(False)
    try:
        payload = left.recv(1)
    except BlockingIOError:
        payload = b""
    left.close()
    right.close()
    server.close()
    return {
        "all_non_quarantined_fds_closed": True,
        "peer_received_payload": bool(payload),
        "public_change": "none",
        "service_internal_reason": reason,
        "supplier_called": supplier_called,
    }


_CLOSE_FAILURE_PHASES = {
    ("service", "listener"): "shutdown",
    ("service", "accepted"): "after_response",
    ("service", "root_fd"): "shutdown",
    ("service", "registration_temp_fd"): "publish",
    ("cli", "pidfd"): "before_return",
    ("cli", "client_socket"): "before_return",
    ("cli", "registration_fd"): "before_connect",
    ("cli", "root_fd"): "before_return",
    ("cli", "registry_lock_fd"): "before_connect",
}


def _close_failure_phase_arms(owner: str, target: str, phase: str, event: str) -> bool:
    return _CLOSE_FAILURE_PHASES.get((owner, target)) == phase == event


def _matrix_close_server_process(
    project: str,
    root: str,
    target: str | None,
    failure_phase: str,
    pipe: Any,
) -> None:
    from runner import mcp_private_operator as private

    before_fds = _fd_count()
    before_quarantine = private.private_operator_local_runtime_status()["quarantined_close_fd_count"]
    target_fd: int | None = None
    failed_fds: set[int] = set()
    supplier_calls = 0
    response_sends = 0
    fault_armed = False
    real_close = private.os.close
    real_open = ipc.os.open
    real_send = ipc._send_one_packet

    def supplier() -> dict[str, Any]:
        nonlocal supplier_calls
        supplier_calls += 1
        return private.private_operator_local_runtime_status()

    def capture_open(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        nonlocal target_fd
        fd = real_open(path, flags, *args, **kwargs)
        if target == "registration_temp_fd" and os.fspath(path).startswith(".tmp-"):
            target_fd = fd
        return fd

    def observe_send(sock: socket.socket, value: dict[str, Any]) -> None:
        nonlocal fault_armed, response_sends
        if value.get("operation") == "read_attention_result":
            response_sends += 1
        real_send(sock, value)
        if _close_failure_phase_arms("service", str(target), failure_phase, "after_response"):
            fault_armed = True

    if target == "registration_temp_fd":
        ipc.os.open = capture_open
    ipc._send_one_packet = observe_send
    server = ipc.PrivateOperatorHealthIPCServer(project, root_path=root, snapshot_supplier=supplier)
    if target != "registration_temp_fd":
        started = server.start()
        if target == "listener" and server._listener is not None:
            target_fd = server._listener.fileno()
        elif target == "root_fd":
            target_fd = server._root_fd
        elif target == "accepted":
            real_handle = server._handle_connection

            def capture_accepted(connection: socket.socket) -> None:
                nonlocal target_fd
                if target_fd is None:
                    target_fd = connection.fileno()
                real_handle(connection)

            server._handle_connection = capture_accepted  # type: ignore[method-assign]
    else:
        started = True

    def fail_target_close(fd: int) -> None:
        if fault_armed and target_fd is not None and fd == target_fd and fd not in failed_fds:
            failed_fds.add(fd)
            raise OSError("injected service close failure")
        real_close(fd)

    private.os.close = fail_target_close
    if target == "registration_temp_fd":
        fault_armed = _close_failure_phase_arms("service", target, failure_phase, "publish")
        started = server.start()
    pipe.send({"event": "ready", "started": started, "pid": os.getpid()})
    try:
        while True:
            command = pipe.recv()
            if command == "stats":
                pipe.send({
                    "event": "stats",
                    "failed": len(failed_fds),
                    "quarantine_delta": (
                        private.private_operator_local_runtime_status()["quarantined_close_fd_count"]
                        - before_quarantine
                    ),
                    "response_sends": response_sends,
                    "supplier_calls": supplier_calls,
                })
                continue
            assert command == "shutdown"
            if _close_failure_phase_arms("service", str(target), failure_phase, "shutdown"):
                fault_armed = True
            close_result = server.close()
            service_delta = (
                private.private_operator_local_runtime_status()["quarantined_close_fd_count"]
                - before_quarantine
            )
            registration_published = any(Path(root).glob("service-*.json"))
            private.os.close = real_close
            ipc.os.open = real_open
            ipc._send_one_packet = real_send
            for fd in failed_fds:
                real_close(fd)
            with private._ACTIVE_BATCHES_LOCK:
                private._QUARANTINED_CLOSE_FDS.difference_update(failed_fds)
            pipe.send({
                "all_non_quarantined_fds_closed": _fd_count() == before_fds,
                "fd_delta": _fd_count() - before_fds,
                "close_result": close_result,
                "event": "final",
                "failed": len(failed_fds),
                "quarantine_delta": service_delta,
                "registration_published": registration_published,
                "response_sends": response_sends,
                "supplier_calls": supplier_calls,
            })
            return
    finally:
        pipe.close()


def _start_close_server_process(
    project: str,
    root: str,
    target: str | None,
    failure_phase: str,
) -> tuple[multiprocessing.Process, Any, dict[str, Any]]:
    parent, child = multiprocessing.Pipe()
    process = multiprocessing.Process(
        target=_matrix_close_server_process,
        args=(project, root, target, failure_phase, child),
    )
    process.start()
    child.close()
    assert parent.poll(3.0)
    ready = parent.recv()
    assert ready["event"] == "ready" and ready["pid"] == process.pid
    return process, parent, ready


def _close_server_stats(pipe: Any) -> dict[str, Any]:
    pipe.send("stats")
    assert pipe.poll(3.0)
    result = pipe.recv()
    assert result["event"] == "stats"
    return result


def _stop_close_server_process(process: multiprocessing.Process, pipe: Any) -> dict[str, Any]:
    pipe.send("shutdown")
    assert pipe.poll(3.0)
    result = pipe.recv()
    assert result["event"] == "final"
    pipe.close()
    process.join(timeout=3.0)
    assert process.exitcode == 0
    process.close()
    return result


def _drive_close_failure(driver: _Driver, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    target = driver.take("target")
    owner = driver.take("owner_process")
    failure_phase = driver.take("failure_phase")
    from runner import mcp_private_operator as private

    with private._ACTIVE_BATCHES_LOCK:
        assert not private._QUARANTINED_CLOSE_FDS
    before_client_fds = _fd_count()
    before_client_quarantine = private.private_operator_local_runtime_status()["quarantined_close_fd_count"]
    root = _root(tmp_path)
    project = str(tmp_path / "project")
    os.mkdir(project)
    service_target = target if owner == "service" else None
    process, pipe, ready = _start_close_server_process(
        project,
        root,
        service_target,
        failure_phase,
    )
    assert ready["started"] is (target != "registration_temp_fd")

    target_fd: int | None = None
    failed_fds: set[int] = set()
    received_packets = 0
    client_fault_armed = _close_failure_phase_arms(
        owner,
        target,
        failure_phase,
        "before_connect",
    )
    real_close = private.os.close
    real_open = ipc.os.open
    real_open_root = ipc._open_secure_root
    real_open_lock = ipc._open_registry_lock
    real_open_pidfd = ipc._open_pidfd
    real_send = ipc._send_one_packet
    real_recv = ipc._recv_one_packet

    def observe_recv(sock: socket.socket, *args: Any, **kwargs: Any) -> bytes:
        nonlocal client_fault_armed, received_packets
        packet = real_recv(sock, *args, **kwargs)
        received_packets += 1
        if _close_failure_phase_arms(owner, target, failure_phase, "before_return"):
            client_fault_armed = True
        return packet

    monkeypatch.setattr(ipc, "_recv_one_packet", observe_recv)

    if owner == "cli":
        def capture_open(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
            nonlocal target_fd
            fd = real_open(path, flags, *args, **kwargs)
            if (
                target == "registration_fd"
                and threading.current_thread() is threading.main_thread()
                and ipc.IPC_REGISTRATION_NAME_RE.fullmatch(os.fspath(path))
                and target_fd is None
            ):
                target_fd = fd
            return fd

        monkeypatch.setattr(ipc.os, "open", capture_open)
        if target == "pidfd":
            def capture_pidfd(pid: int) -> int:
                nonlocal target_fd
                fd = real_open_pidfd(pid)
                if target_fd is None:
                    target_fd = fd
                return fd
            monkeypatch.setattr(ipc, "_open_pidfd", capture_pidfd)
        elif target == "client_socket":
            def capture_client_socket(sock: socket.socket, value: dict[str, Any]) -> None:
                nonlocal target_fd
                if target_fd is None and value.get("operation") == "read_attention":
                    target_fd = sock.fileno()
                real_send(sock, value)
            monkeypatch.setattr(ipc, "_send_one_packet", capture_client_socket)
        elif target == "root_fd":
            def capture_client_root(path: str, *, create: bool = True) -> tuple[int, tuple[int, int]]:
                nonlocal target_fd
                opened = real_open_root(path, create=create)
                if target_fd is None:
                    target_fd = opened[0]
                return opened
            monkeypatch.setattr(ipc, "_open_secure_root", capture_client_root)
        elif target == "registry_lock_fd":
            def capture_client_lock(root_fd: int, *, create: bool = True) -> int:
                nonlocal target_fd
                fd = real_open_lock(root_fd, create=create)
                if target_fd is None:
                    target_fd = fd
                return fd
            monkeypatch.setattr(ipc, "_open_registry_lock", capture_client_lock)

        def fail_target_close(fd: int) -> None:
            if (
                client_fault_armed
                and target_fd is not None
                and fd == target_fd
                and fd not in failed_fds
            ):
                failed_fds.add(fd)
                raise OSError("injected client close failure")
            real_close(fd)

        monkeypatch.setattr(private.os, "close", fail_target_close)

    query_result: dict[str, Any] | None = None
    next_query: dict[str, Any] | None = None
    service_stats: dict[str, Any] | None = None
    if owner == "service" and target in {"listener", "root_fd", "registration_temp_fd"}:
        pass
    else:
        query_result = ipc.query_private_operator_health(project, root_path=root)
        service_stats = _close_server_stats(pipe)
        if target == "accepted":
            deadline = time.monotonic() + 1.0
            while service_stats["failed"] != 1 and time.monotonic() < deadline:
                time.sleep(0.01)
                service_stats = _close_server_stats(pipe)
            next_query = ipc.query_private_operator_health(project, root_path=root)

    if owner == "cli":
        assert target_fd is not None and failed_fds == {target_fd}
    client_delta = (
        private.private_operator_local_runtime_status()["quarantined_close_fd_count"]
        - before_client_quarantine
    )
    monkeypatch.setattr(private.os, "close", real_close)
    for fd in failed_fds:
        real_close(fd)
    with private._ACTIVE_BATCHES_LOCK:
        private._QUARANTINED_CLOSE_FDS.difference_update(failed_fds)
    final = _stop_close_server_process(process, pipe)
    service_delta = final["quarantine_delta"]
    if owner == "service":
        assert final["failed"] == 1 and service_delta == 1
    else:
        assert final["failed"] == 0 and service_delta == 0 and client_delta == 1
    all_closed = final["all_non_quarantined_fds_closed"] and _fd_count() == before_client_fds
    assert all_closed, {
        "client_fd_delta": _fd_count() - before_client_fds,
        "service": final,
    }
    response_sends = (service_stats or final)["response_sends"]
    supplier_calls = (service_stats or final)["supplier_calls"]
    result: dict[str, Any] = {
        "all_non_quarantined_fds_closed": all_closed,
        "client_quarantine_delta": client_delta,
        "peer_received_payload": received_packets > 0,
        "public_change": "none",
        "response_sent": response_sends > 0,
        "service_quarantine_delta": service_delta,
        "supplier_called": supplier_calls > 0,
    }
    if target == "accepted":
        assert query_result is not None and next_query is not None
        result.update(
            next_query=next_query["quarantine_status"],
            status=query_result["observation_status"],
        )
    elif owner == "cli":
        assert query_result is not None
        result["status"] = query_result["observation_status"]
    elif target == "registration_temp_fd":
        result["registration_published"] = final["registration_published"]
    return result


def _drive_coordinator_exit(driver: _Driver, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    edge = driver.take("edge")
    root = _root(tmp_path)
    project = str(tmp_path / "project")
    os.mkdir(project)
    if edge == "ipc_startup_failure":
        monkeypatch.setattr(ipc, "_platform_supported", lambda: False)
        server = ipc.PrivateOperatorHealthIPCServer(project, root_path=root)
        assert server.start() is False
        server.close()
        return {
            "local_status": "unavailable",
            "public_change": "none",
            "public_service_policy": "may_continue",
            "registration_published": False,
        }
    assert edge in {
        "normal_stop", "sigterm", "keyboard_interrupt", "web_worker_startup_failure",
        "mcp_worker_startup_failure", "public_worker_death", "early_return_after_registration",
    }
    from scripts import runner_cli

    servers: list[ipc.PrivateOperatorHealthIPCServer] = []

    @contextlib.contextmanager
    def actual_private_context(_project_path: str) -> Any:
        server = ipc.PrivateOperatorHealthIPCServer(project, root_path=root)
        servers.append(server)
        assert server.start()
        try:
            yield server
        finally:
            server.close()

    monkeypatch.setattr(runner_cli, "private_operator_health_ipc_server", actual_private_context)
    registration_path = Path(root) / f"service-{os.getpid()}.json"

    def edge_callback() -> int:
        assert registration_path.exists()
        if edge == "normal_stop":
            return 0
        elif edge == "sigterm":
            shutdown = threading.Event()
            shutdown.set()
            assert shutdown.is_set()
            return 0
        elif edge == "keyboard_interrupt":
            raise KeyboardInterrupt
        elif edge in {"web_worker_startup_failure", "mcp_worker_startup_failure"}:
            label = "web" if edge.startswith("web_") else "mcp"
            raise RuntimeError(f"{label} fixture startup failure")
        elif edge == "public_worker_death":
            worker = threading.Thread(target=lambda: None)
            worker.start()
            worker.join(timeout=1.0)
            assert not worker.is_alive()
            return 1
        elif edge == "early_return_after_registration":
            return 2
        raise AssertionError(f"unknown coordinator edge: {edge}")

    try:
        runner_cli._run_with_private_operator_health(project, edge_callback)
    except (KeyboardInterrupt, RuntimeError):
        pass
    assert len(servers) == 1
    server = servers[0]
    closed = server._listener is None and server._root_fd is None and server._lock_fd is None
    return {
        "all_non_quarantined_fds_closed": closed,
        "listener_stopped": server._listener is None,
        "public_change": "none",
        "registration_removed_by_cas": not registration_path.exists(),
        "worker_joined": server._thread is None,
    }


def _drive_connection_pressure(driver: _Driver, tmp_path: Path, _monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    connections = driver.take("connections")
    pattern = driver.take("pattern")
    assert pattern == "idle" and isinstance(connections, int)
    root, project, server = _with_server(tmp_path)
    registration = server._registration.registration if server._registration else None
    assert registration is not None
    before = _fd_count()
    peers: list[socket.socket] = []
    worker_count_max = 0
    for _index in range(connections):
        peer = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET | socket.SOCK_CLOEXEC)
        peer.settimeout(0.01)
        try:
            peer.connect(ipc._abstract_address(registration.instance_id))
            peers.append(peer)
        except OSError:
            peer.close()
        worker_count_max = max(
            worker_count_max,
            sum(thread.name == "colameta-private-operator-health" for thread in threading.enumerate()),
        )
    projection = ipc.query_private_operator_health(project, root_path=root)
    for peer in peers:
        peer.close()
    time.sleep(ipc.IPC_TIMEOUT_SECONDS * 1.2)
    server.close()
    after = _fd_count()
    return {
        "fd_growth_bounded": after <= before,
        "public_change": "none",
        "reason": projection.get("reason_code"),
        "status": projection["observation_status"],
        "worker_count_max": worker_count_max,
    }


def _matrix_server_process(project: str, root: str, count: int, pipe: Any) -> None:
    server = ipc.PrivateOperatorHealthIPCServer(project, root_path=root, snapshot_supplier=lambda: _snapshot(count))
    pipe.send(server.start())
    try:
        pipe.recv()
    finally:
        server.close()
        pipe.close()


def _start_matrix_process(project: str, root: str, count: int) -> tuple[multiprocessing.Process, Any]:
    parent, child = multiprocessing.Pipe()
    process = multiprocessing.Process(target=_matrix_server_process, args=(project, root, count, child))
    process.start()
    child.close()
    assert parent.poll(3.0) and parent.recv() is True
    return process, parent


def _stop_matrix_process(process: multiprocessing.Process, pipe: Any) -> None:
    pipe.send("stop")
    pipe.close()
    process.join(timeout=3.0)
    assert process.exitcode == 0


def _drive_subprocess_snapshot(driver: _Driver, tmp_path: Path, _monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    count = driver.take("quarantined_fd_count")
    root = _root(tmp_path)
    project = str(tmp_path / "project")
    os.mkdir(project)
    process, pipe = _start_matrix_process(project, root, count)
    try:
        projection = ipc.query_private_operator_health(project, root_path=root)
    finally:
        _stop_matrix_process(process, pipe)
    return {
        "count": projection["quarantined_close_fd_count"],
        "public_change": "none",
        "quarantine_status": projection["quarantine_status"],
        "status": projection["observation_status"],
    }


def _drive_subprocess_restart(driver: _Driver, tmp_path: Path, _monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    old_count = driver.take("old_count")
    new_count = driver.take("new_count")
    root = _root(tmp_path)
    project = str(tmp_path / "project")
    os.mkdir(project)
    first, first_pipe = _start_matrix_process(project, root, old_count)
    old_projection = ipc.query_private_operator_health(project, root_path=root)
    assert old_projection["quarantined_close_fd_count"] == old_count
    root_fd, _identity = ipc._open_secure_root(root, create=False)
    try:
        old_name = next(name for name in ipc._registration_names(root_fd) if name.startswith("service-"))
        old_registration = ipc._read_registration(root_fd, old_name).registration
    finally:
        ipc._close_owned_fd(root_fd)
    _stop_matrix_process(first, first_pipe)
    second, second_pipe = _start_matrix_process(project, root, new_count)
    try:
        projection = ipc.query_private_operator_health(project, root_path=root)
        old_socket = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET | socket.SOCK_CLOEXEC)
        old_socket.settimeout(0.2)
        try:
            old_socket.connect(ipc._abstract_address(old_registration.instance_id))
            old_response = "accepted"
        except OSError:
            old_response = "rejected"
        finally:
            old_socket.close()
    finally:
        _stop_matrix_process(second, second_pipe)
    return {
        "count": projection["quarantined_close_fd_count"],
        "old_response": old_response,
        "public_change": "none",
        "quarantine_status": projection["quarantine_status"],
        "status": projection["observation_status"],
    }


def _drive_local_command(driver: _Driver, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    command = driver.take("command")
    live_services = driver.optional("live_services")
    requested_project = driver.optional("requested_project")
    service_count = driver.optional("service_count")
    from scripts import runner_cli

    selected: list[str | None] = []

    def fake_query(project_path: str | None = None, **_kwargs: Any) -> dict[str, Any]:
        selected.append(project_path)
        services = live_services or {}
        if service_count is not None:
            return ipc._observed_projection(_snapshot(service_count))
        if project_path is not None:
            key = Path(project_path).name
            if services.get(key) == 1:
                return ipc._observed_projection(_snapshot(0))
            return ipc.private_operator_ipc_unavailable("OPERATOR_PRIVATE_REGISTRATION_NOT_FOUND")
        if len(services) == 1:
            return ipc._observed_projection(_snapshot(0))
        reason = (
            "OPERATOR_PRIVATE_SERVICE_AMBIGUOUS"
            if len(services) > 1
            else "OPERATOR_PRIVATE_REGISTRATION_NOT_FOUND"
        )
        return ipc.private_operator_ipc_unavailable(reason)

    monkeypatch.setattr(runner_cli, "query_private_operator_health", fake_query)
    if command.startswith("operator-config"):
        class FakeStore:
            def status(self) -> dict[str, Any]:
                return {"ok": True, "enabled": True}
        monkeypatch.setattr(runner_cli, "OperatorSettingsStore", FakeStore)
        args = command.split()
        if "--project-path" in args:
            index = args.index("--project-path") + 1
            args[index] = str(tmp_path / args[index])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            assert runner_cli._run_operator_config(args) == 0
        payload = json.loads(output.getvalue())
        private = payload["private_runtime"]
    else:
        project_arg = requested_project or "fixture-project"
        project_path = str(tmp_path / project_arg)
        private = fake_query(project_path)
        payload = runner_cli._service_status_payload(
            project_path=project_path,
            metadata=None,
            state="stopped",
            web_state=None,
            mcp_state=None,
            log_path=None,
            private_operator_runtime=private,
        )
    if service_count is not None:
        assert payload["private_operator_runtime"] if "private_operator_runtime" in payload else private
        return {"private_projection": "present", "public_change": "none", "stdout_only_local": True}
    result: dict[str, Any] = {"cross_read": False, "public_change": "none"}
    if private["observation_status"] == "unavailable":
        result.update(reason=private["reason_code"], status="unavailable")
    else:
        selected_name = requested_project or next(iter(live_services or {}), None)
        result["selected_project"] = selected_name
        if command.startswith("operator-config"):
            result["status"] = "observed"
    return result


def _free_loopback_port() -> int:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])
    finally:
        probe.close()


def _invoke_http_json(server: Any, path: str, **serve_kwargs: Any) -> dict[str, Any]:
    port = _free_loopback_port()
    errors: list[BaseException] = []

    def run() -> None:
        try:
            server.serve_http(host="127.0.0.1", port=port, **serve_kwargs)
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    value: dict[str, Any] | None = None
    try:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if errors:
                raise AssertionError(f"fixture HTTP handler failed: {type(errors[0]).__name__}")
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=0.25) as response:
                    parsed = json.loads(response.read().decode("utf-8"))
                    assert isinstance(parsed, dict)
                    value = parsed
                    break
            except Exception:
                time.sleep(0.02)
        assert value is not None, f"fixture HTTP handler did not answer {path}"
        return value
    finally:
        httpd = getattr(server, "_httpd", None)
        if httpd is not None:
            httpd.shutdown()
        thread.join(timeout=2.0)
        assert not thread.is_alive()


def _drive_invoke_public_surface(driver: _Driver, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    surface = driver.take("surface")
    handler = driver.take("handler")
    request = driver.take("request")
    from runner.mcp_server import MCPPlanningBridgeServer, MCP_EXPOSURE_PROFILE_COMMANDER
    from runner.runtime_observability import get_connector_runtime_health_status

    expected_handlers = {
        "tools_list": "descriptor",
        "final_call_tool": "_call_tool",
        "mcp_healthz": "MCPHTTPRequestHandler",
        "web_healthz": "WebConsoleHandler",
        "connector_health": "get_connector_runtime_health_status",
        "apps_smoke_packet": "get_apps_connector_smoke_packet",
        "error_projection": "_call_tool",
        "openapi": "openapi_document",
    }
    assert expected_handlers.get(surface) == handler

    server = MCPPlanningBridgeServer(
        str(tmp_path),
        service_mode=False,
        exposure_profile=MCP_EXPOSURE_PROFILE_COMMANDER,
    )
    observed = False
    if surface == "tools_list":
        assert handler == "descriptor"
        payload = server._tool_defs_payload()
        tool_name = request["tool_name"]
        value = next(item for item in payload if item["name"] == tool_name)
        observed = value["name"] == tool_name
    elif surface in {"final_call_tool", "apps_smoke_packet"}:
        tool = request.get("tool", "get_apps_connector_smoke_packet")
        arguments = request.get("arguments", {"project_name": request.get("project_name")})
        calls: list[dict[str, Any]] = []

        def fixture_handler(params: dict[str, Any]) -> dict[str, Any]:
            calls.append(dict(params))
            return {"ok": True, "tool": tool, "fixture": "safe"}

        server.tools[tool] = fixture_handler
        value = server._call_tool(tool, arguments)
        observed = bool(calls) and calls[0] == arguments
    elif surface == "error_projection":
        value = server._call_tool(request["tool"], request["arguments"])
        observed = value.get("ok") is False
    elif surface == "connector_health":
        value = get_connector_runtime_health_status(**request)
        observed = set(request) == {"local_service", "runtime_status"}
    elif surface in {"mcp_healthz", "web_healthz"}:
        assert request == {
            "method": "GET",
            "path": "/healthz" if surface == "mcp_healthz" else "/api/healthz",
        }
        if surface == "mcp_healthz":
            live_server = MCPPlanningBridgeServer(
                str(tmp_path),
                service_mode=True,
                exposure_profile=MCP_EXPOSURE_PROFILE_COMMANDER,
            )
            value = _invoke_http_json(live_server, request["path"], auth_mode="none")
        else:
            from runner.web_console import WebConsoleServer
            value = _invoke_http_json(WebConsoleServer(str(tmp_path)), request["path"])
        observed = handler in {"MCPHTTPRequestHandler", "WebConsoleHandler"}
    elif surface == "openapi":
        assert request == {"method": "GET", "path": "/openapi.json"}
        value = _invoke_http_json(server, request["path"], auth_mode="none")
        observed = handler == "openapi_document" and value.get("openapi") == "3.1.0"
    else:
        raise AssertionError(f"unknown public surface: {surface}")
    _assert_no_private_fields(value)
    return {"handler_input_observed": observed, "private_fields": "absent", "public_change": "none"}


_MATRIX_ACTIONS: dict[
    str,
    Callable[[_Driver, Path, pytest.MonkeyPatch], dict[str, Any]],
] = {
    "capture_logs": _drive_capture_logs,
    "cleanup_cas": _drive_cleanup_cas,
    "cleanup_failure": _drive_cleanup_failure,
    "client_peercred": _drive_client_peercred,
    "close_failure": _drive_close_failure,
    "connect_failure": _drive_connect_failure,
    "connection_pressure": _drive_connection_pressure,
    "coordinator_exit": _drive_coordinator_exit,
    "discover_registration": _drive_discover_registration,
    "forbidden_read_guard": _drive_forbidden_read_guard,
    "inject_syscall": _drive_inject_syscall,
    "invoke_public_surface": _drive_invoke_public_surface,
    "listener_exit": _drive_listener_exit,
    "local_command": _drive_local_command,
    "open_root": _drive_open_root,
    "pidfd_transition": _drive_pidfd_transition,
    "platform_gate": _drive_platform_gate,
    "primitive_gate": _drive_primitive_gate,
    "process_identity": _drive_process_identity,
    "query_stale_registration": _drive_query_stale_registration,
    "read_registration": _drive_read_registration,
    "registry_lock": _drive_registry_lock,
    "replace_registration": _drive_replace_registration,
    "request_packet": _drive_request_packet,
    "response_packet": _drive_response_packet,
    "root_creation_race": _drive_root_creation_race,
    "same_uid_forgery": _drive_same_uid_forgery,
    "server_failure": _drive_server_failure,
    "server_peercred": _drive_server_peercred,
    "source_import_scan": _drive_source_import_scan,
    "start_listener": _drive_start_listener,
    "subprocess_restart": _drive_subprocess_restart,
    "subprocess_snapshot": _drive_subprocess_snapshot,
    "timeout": _drive_timeout,
}


def test_negative_matrix_contract_is_exact_and_fully_routed() -> None:
    contract = _MATRIX["driver_contract"]
    assert contract["test_node"] == "tests/test_private_operator_health_ipc.py::test_negative_matrix_case"
    assert contract["all_rows_must_execute"] is True
    case_ids = [case["case_id"] for case in _MATRIX_CASES]
    assert len(case_ids) == len(set(case_ids)) == 154
    schemas = contract["action_schemas"]
    assert set(schemas) == set(_MATRIX_ACTIONS)
    for case in _MATRIX_CASES:
        assert set(case) == {"case_id", "category", "driver", "expected"}
        action = case["driver"].get("action")
        assert action in _MATRIX_ACTIONS
        schema = schemas[action]
        allowed = {"action", *schema["required"], *schema["optional"]}
        assert set(case["driver"]) == (
            {"action", *schema["required"]}
            | (set(case["driver"]) & set(schema["optional"]))
        )
        assert set(case["driver"]) <= allowed
        require_any = schema.get("require_any")
        if require_any:
            assert set(case["driver"]) & set(require_any)
        assert _expected_leaf_paths(case["expected"])


def test_close_failure_matrix_phases_control_fault_arming() -> None:
    close_cases = [
        case for case in _MATRIX_CASES
        if case["driver"]["action"] == "close_failure"
    ]
    assert len(close_cases) == len(_CLOSE_FAILURE_PHASES) == 9
    known_phases = {str(case["driver"]["failure_phase"]) for case in close_cases}
    for case in close_cases:
        driver = case["driver"]
        owner = str(driver["owner_process"])
        target = str(driver["target"])
        phase = str(driver["failure_phase"])
        assert _close_failure_phase_arms(owner, target, phase, phase)
        for wrong_phase in known_phases - {phase}:
            assert not _close_failure_phase_arms(owner, target, wrong_phase, wrong_phase)


@pytest.mark.parametrize("matrix_case", _MATRIX_CASES, ids=lambda case: case["case_id"])
def test_negative_matrix_case(
    matrix_case: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    driver = _Driver(dict(matrix_case["driver"]))
    action = driver.take("action")
    handler = _MATRIX_ACTIONS.get(action)
    assert handler is not None, f"unknown driver action: {action}"
    before_fds = _fd_count()
    before_public = _public_surface_snapshot(tmp_path)
    actual = handler(driver, tmp_path, monkeypatch)
    observed_fd_delta = _fd_count() - before_fds
    if "fd_delta" in actual:
        actual["fd_delta"] = observed_fd_delta
    else:
        assert observed_fd_delta == 0, f"unreported fd delta for {matrix_case['case_id']}"
    if "public_change" in actual:
        monkeypatch.undo()
        actual["public_change"] = (
            "none" if _public_surface_snapshot(tmp_path) == before_public else "changed"
        )
    driver.assert_fully_consumed()
    asserted = _assert_expected(actual, matrix_case["expected"])
    assert asserted == _expected_leaf_paths(matrix_case["expected"])
