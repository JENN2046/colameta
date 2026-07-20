from __future__ import annotations

import contextlib
import errno
import hashlib
import json
import os
import re
import secrets
import select
import socket
import stat
import struct
import sys
import threading
from dataclasses import dataclass
from typing import Any, Callable, Iterator

try:
    import fcntl
except ImportError:  # pragma: no cover - exercised by the platform gate
    fcntl = None  # type: ignore[assignment]

from runner.mcp_private_operator import (
    OPERATOR_QUARANTINE_ALERT_CODE,
    OPERATOR_QUARANTINE_ATTENTION_THRESHOLD,
    _close_owned_fd,
    private_operator_local_runtime_status,
)
from runner.runner_paths import user_config_dir


IPC_PROTOCOL = "colameta.private_attention.v1"
REGISTRATION_SCHEMA_VERSION = "colameta.private_operator_health_registration.v1"
IPC_OBSERVATION_SOURCE = "service_private_ipc"
IPC_UNAVAILABLE_ALERT_CODE = "OPERATOR_PRIVATE_HEALTH_UNAVAILABLE"
IPC_MAX_PACKET_BYTES = 1024
IPC_MAX_REGISTRATIONS = 64
IPC_MAX_AGGREGATED_CLOSE_FDS = 65535 * IPC_MAX_REGISTRATIONS
IPC_TIMEOUT_SECONDS = 0.25
IPC_LISTEN_BACKLOG = 4
IPC_ROOT_DIRNAME = "private-operator-health"
IPC_LOCK_FILENAME = "registry.lock"
IPC_INSTANCE_RE = re.compile(r"^[0-9a-f]{32}$")
IPC_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
IPC_REGISTRATION_NAME_RE = re.compile(r"^service-([1-9][0-9]{0,9})\.json$")
IPC_REASON_CODES = frozenset(
    {
        "OPERATOR_PRIVATE_IPC_UNSUPPORTED",
        "OPERATOR_PRIVATE_PROCESS_IDENTITY_UNAVAILABLE",
        "OPERATOR_PRIVATE_PROCESS_IDENTITY_MISMATCH",
        "OPERATOR_PRIVATE_PROCESS_NOT_RUNNING",
        "OPERATOR_PRIVATE_SERVICE_AMBIGUOUS",
        "OPERATOR_PRIVATE_REGISTRATION_NOT_FOUND",
        "OPERATOR_PRIVATE_REGISTRY_SATURATED",
        "OPERATOR_PRIVATE_IPC_ROOT_UNSAFE",
        "OPERATOR_PRIVATE_IPC_ROOT_CHANGED",
        "OPERATOR_PRIVATE_IPC_REGISTRATION_UNSAFE",
        "OPERATOR_PRIVATE_IPC_REGISTRATION_INVALID",
        "OPERATOR_PRIVATE_IPC_REGISTRATION_CHANGED",
        "OPERATOR_PRIVATE_PROJECT_MISMATCH",
        "OPERATOR_PRIVATE_PEER_DENIED",
        "OPERATOR_PRIVATE_PROTOCOL_INVALID",
        "OPERATOR_PRIVATE_PROTOCOL_BINDING_MISMATCH",
        "OPERATOR_PRIVATE_GENERATION_LIVE",
        "OPERATOR_PRIVATE_IPC_UNAVAILABLE",
    }
)
_REGISTRATION_KEYS = frozenset(
    {
        "schema_version",
        "pid",
        "process_start_ticks",
        "instance_id",
        "project_fingerprint",
    }
)
_REQUEST_KEYS = frozenset(
    {"protocol", "operation", "instance_id", "project_fingerprint", "nonce"}
)
_RESPONSE_KEYS = frozenset(
    {
        "protocol",
        "operation",
        "instance_id",
        "project_fingerprint",
        "nonce",
        "quarantined_close_fd_count",
        "quarantine_attention_threshold",
        "quarantine_status",
        "local_alert_code",
    }
)
_DIR_OPEN_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)
_FILE_READ_FLAGS = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
_FILE_CREATE_FLAGS = (
    os.O_WRONLY
    | os.O_CREAT
    | os.O_EXCL
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)


class PrivateOperatorIPCError(Exception):
    def __init__(self, reason_code: str):
        super().__init__(reason_code)
        self.reason_code = reason_code if reason_code in IPC_REASON_CODES else "OPERATOR_PRIVATE_IPC_UNAVAILABLE"
        self.pending_registration: _FrozenRegistration | None = None


def private_operator_ipc_unavailable(reason_code: str) -> dict[str, Any]:
    safe_reason = reason_code if reason_code in IPC_REASON_CODES else "OPERATOR_PRIVATE_IPC_UNAVAILABLE"
    return {
        "observation_source": IPC_OBSERVATION_SOURCE,
        "observation_status": "unavailable",
        "quarantined_close_fd_count": None,
        "quarantine_attention_threshold": OPERATOR_QUARANTINE_ATTENTION_THRESHOLD,
        "quarantine_status": "unknown",
        "local_alert_code": IPC_UNAVAILABLE_ALERT_CODE,
        "reason_code": safe_reason,
    }


def _observed_projection(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "observation_source": IPC_OBSERVATION_SOURCE,
        "observation_status": "observed",
        "quarantined_close_fd_count": snapshot["quarantined_close_fd_count"],
        "quarantine_attention_threshold": snapshot["quarantine_attention_threshold"],
        "quarantine_status": snapshot["quarantine_status"],
        "local_alert_code": snapshot["local_alert_code"],
    }


def _aggregate_snapshots(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    if not snapshots:
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_REGISTRATION_NOT_FOUND")
    count = sum(snapshot["quarantined_close_fd_count"] for snapshot in snapshots)
    if count < 0 or count > IPC_MAX_AGGREGATED_CLOSE_FDS:
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_PROTOCOL_INVALID")
    return {
        "quarantined_close_fd_count": count,
        "quarantine_attention_threshold": OPERATOR_QUARANTINE_ATTENTION_THRESHOLD,
        "quarantine_status": "attention" if count else "clear",
        "local_alert_code": OPERATOR_QUARANTINE_ALERT_CODE if count else None,
    }


def _project_fingerprint(project_path: str) -> str:
    canonical = os.path.realpath(os.path.abspath(os.path.expanduser(project_path)))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _strict_json_object(raw: bytes) -> dict[str, Any]:
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_PROTOCOL_INVALID") from exc

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    try:
        value = json.loads(text, object_pairs_hook=reject_duplicates)
    except (json.JSONDecodeError, ValueError) as exc:
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_PROTOCOL_INVALID") from exc
    if not isinstance(value, dict):
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_PROTOCOL_INVALID")
    return value


def _platform_supported() -> bool:
    return bool(
        sys.platform == "linux"
        and hasattr(socket, "AF_UNIX")
        and hasattr(socket, "SOCK_SEQPACKET")
        and hasattr(socket, "SOCK_CLOEXEC")
        and hasattr(socket, "SO_PEERCRED")
        and hasattr(os, "pidfd_open")
        and hasattr(socket.socket, "recvmsg")
        and fcntl is not None
    )


def _safe_close_many(fds: list[int | None]) -> bool:
    ok = True
    for fd in fds:
        if isinstance(fd, int) and fd >= 0:
            ok = _close_owned_fd(fd) and ok
    return ok


def _close_socket(sock: socket.socket | None) -> bool:
    if sock is None:
        return True
    try:
        fd = sock.detach()
    except BaseException:
        return False
    return _close_owned_fd(fd)


def _validate_directory_info(info: os.stat_result, *, final: bool) -> None:
    if not stat.S_ISDIR(info.st_mode):
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_ROOT_UNSAFE")
    current_uid = os.geteuid()
    if info.st_uid not in {0, current_uid}:
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_ROOT_UNSAFE")
    mode = stat.S_IMODE(info.st_mode)
    if final:
        if info.st_uid != current_uid or mode != 0o700:
            raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_ROOT_UNSAFE")
        return
    writable = mode & 0o022
    sticky_root = info.st_uid == 0 and bool(mode & stat.S_ISVTX)
    if writable and not sticky_root:
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_ROOT_UNSAFE")


def _open_secure_root(root_path: str, *, create: bool = True) -> tuple[int, tuple[int, int]]:
    absolute = os.path.abspath(os.path.expanduser(root_path))
    components = [part for part in absolute.split(os.sep) if part]
    if not components:
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_ROOT_UNSAFE")
    current_fd: int | None = None
    trusted_base_index = max(len(components) - 3, 0)
    try:
        current_fd = os.open(os.sep, _DIR_OPEN_FLAGS)
        _validate_directory_info(os.fstat(current_fd), final=False)
        for index, component in enumerate(components):
            final = index == len(components) - 1
            allow_create = index > trusted_base_index
            next_fd: int | None = None
            try:
                next_fd = os.open(component, _DIR_OPEN_FLAGS, dir_fd=current_fd)
            except FileNotFoundError:
                if not create:
                    raise PrivateOperatorIPCError("OPERATOR_PRIVATE_REGISTRATION_NOT_FOUND")
                if not allow_create:
                    raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_ROOT_UNSAFE")
                try:
                    os.mkdir(component, mode=0o700, dir_fd=current_fd)
                    os.fsync(current_fd)
                except OSError as exc:
                    raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_UNAVAILABLE") from exc
                try:
                    created_info = os.stat(component, dir_fd=current_fd, follow_symlinks=False)
                    if not stat.S_ISDIR(created_info.st_mode) or created_info.st_uid != os.geteuid():
                        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_ROOT_CHANGED")
                    created_identity = (created_info.st_dev, created_info.st_ino)
                except PrivateOperatorIPCError:
                    raise
                except OSError as exc:
                    raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_UNAVAILABLE") from exc
                try:
                    next_fd = os.open(component, _DIR_OPEN_FLAGS, dir_fd=current_fd)
                except OSError as exc:
                    if next_fd is not None:
                        _close_owned_fd(next_fd)
                    raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_ROOT_CHANGED") from exc
                try:
                    opened_info = os.fstat(next_fd)
                    if (opened_info.st_dev, opened_info.st_ino) != created_identity:
                        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_ROOT_CHANGED")
                    os.fchmod(next_fd, 0o700)
                except BaseException:
                    closing_fd = next_fd
                    next_fd = None
                    _close_owned_fd(closing_fd)
                    raise
            try:
                info = os.fstat(next_fd)
                if index == trusted_base_index:
                    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o022:
                        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_ROOT_UNSAFE")
                _validate_directory_info(info, final=final or index >= len(components) - 2)
            except BaseException:
                _close_owned_fd(next_fd)
                raise
            closing_fd = current_fd
            current_fd = None
            if not _close_owned_fd(closing_fd):
                closing_next_fd = next_fd
                next_fd = None
                _close_owned_fd(closing_next_fd)
                raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_UNAVAILABLE")
            current_fd = next_fd
        info = os.fstat(current_fd)
        _validate_directory_info(info, final=True)
        return current_fd, (info.st_dev, info.st_ino)
    except PrivateOperatorIPCError:
        if current_fd is not None:
            _close_owned_fd(current_fd)
        raise
    except OSError as exc:
        if current_fd is not None:
            _close_owned_fd(current_fd)
        reason = (
            "OPERATOR_PRIVATE_IPC_ROOT_UNSAFE"
            if exc.errno in {errno.ELOOP, errno.ENOTDIR}
            else "OPERATOR_PRIVATE_IPC_UNAVAILABLE"
        )
        raise PrivateOperatorIPCError(reason) from exc
    except BaseException as exc:
        if current_fd is not None:
            _close_owned_fd(current_fd)
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_ROOT_UNSAFE") from exc


def _default_root_path() -> str:
    runtime_base = os.environ.get("XDG_RUNTIME_DIR", "").strip()
    if runtime_base:
        return os.path.join(os.path.abspath(os.path.expanduser(runtime_base)), "colameta", IPC_ROOT_DIRNAME)
    return os.path.join(user_config_dir(), "runtime", IPC_ROOT_DIRNAME)


def _assert_root_path_identity(root_path: str, expected: tuple[int, int]) -> None:
    current_fd: int | None = None
    try:
        current_fd, current = _open_secure_root(root_path, create=False)
        if current != expected:
            raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_ROOT_CHANGED")
    except PrivateOperatorIPCError as exc:
        if exc.reason_code == "OPERATOR_PRIVATE_IPC_ROOT_CHANGED":
            raise
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_ROOT_CHANGED") from exc
    finally:
        if current_fd is not None and not _close_owned_fd(current_fd):
            raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_UNAVAILABLE")


def _validate_private_regular(info: os.stat_result, *, max_size: int | None = None) -> None:
    if not stat.S_ISREG(info.st_mode):
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_REGISTRATION_UNSAFE")
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1:
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_REGISTRATION_UNSAFE")
    if max_size is not None and (info.st_size < 1 or info.st_size > max_size):
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_REGISTRATION_INVALID")


def _open_registry_lock(root_fd: int, *, create: bool = True) -> int:
    created = False
    try:
        if create:
            fd = os.open(IPC_LOCK_FILENAME, _FILE_CREATE_FLAGS, 0o600, dir_fd=root_fd)
            created = True
        else:
            fd = os.open(
                IPC_LOCK_FILENAME,
                os.O_RDWR | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
                dir_fd=root_fd,
            )
    except FileExistsError:
        try:
            fd = os.open(
                IPC_LOCK_FILENAME,
                os.O_RDWR | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
                dir_fd=root_fd,
            )
        except OSError as exc:
            raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_ROOT_UNSAFE") from exc
    except FileNotFoundError as exc:
        if not create:
            raise PrivateOperatorIPCError("OPERATOR_PRIVATE_REGISTRATION_NOT_FOUND") from exc
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_UNAVAILABLE") from exc
    except OSError as exc:
        reason = (
            "OPERATOR_PRIVATE_IPC_ROOT_UNSAFE"
            if exc.errno in {errno.ELOOP, errno.EISDIR}
            else "OPERATOR_PRIVATE_IPC_UNAVAILABLE"
        )
        raise PrivateOperatorIPCError(reason) from exc
    try:
        if created:
            os.fchmod(fd, 0o600)
            os.fsync(fd)
            os.fsync(root_fd)
        _validate_private_regular(os.fstat(fd), max_size=None)
        return fd
    except BaseException as exc:
        _close_owned_fd(fd)
        if isinstance(exc, PrivateOperatorIPCError):
            if exc.reason_code == "OPERATOR_PRIVATE_IPC_REGISTRATION_UNSAFE":
                raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_ROOT_UNSAFE") from exc
            raise
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_ROOT_UNSAFE") from exc


@contextlib.contextmanager
def _locked_registry(lock_fd: int) -> Iterator[None]:
    if fcntl is None:
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_UNSUPPORTED")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
    except BaseException as exc:
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_UNAVAILABLE") from exc
    try:
        yield
    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        except BaseException as exc:
            raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_UNAVAILABLE") from exc


def _read_all_fd(fd: int, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining > 0:
        chunk = os.read(fd, remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    value = b"".join(chunks)
    if len(value) != size:
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_REGISTRATION_INVALID")
    return value


@dataclass(frozen=True)
class PrivateOperatorIPCRegistration:
    pid: int
    process_start_ticks: int
    instance_id: str
    project_fingerprint: str

    @property
    def filename(self) -> str:
        return f"service-{self.pid}.json"

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": REGISTRATION_SCHEMA_VERSION,
            "pid": self.pid,
            "process_start_ticks": self.process_start_ticks,
            "instance_id": self.instance_id,
            "project_fingerprint": self.project_fingerprint,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "PrivateOperatorIPCRegistration":
        if frozenset(value) != _REGISTRATION_KEYS:
            raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_REGISTRATION_INVALID")
        if value.get("schema_version") != REGISTRATION_SCHEMA_VERSION:
            raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_REGISTRATION_INVALID")
        pid = value.get("pid")
        start_ticks = value.get("process_start_ticks")
        instance_id = value.get("instance_id")
        project = value.get("project_fingerprint")
        if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0 or pid > 2_147_483_647:
            raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_REGISTRATION_INVALID")
        if not isinstance(start_ticks, int) or isinstance(start_ticks, bool) or start_ticks <= 0:
            raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_REGISTRATION_INVALID")
        if not isinstance(instance_id, str) or IPC_INSTANCE_RE.fullmatch(instance_id) is None:
            raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_REGISTRATION_INVALID")
        if not isinstance(project, str) or IPC_DIGEST_RE.fullmatch(project) is None:
            raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_REGISTRATION_INVALID")
        return cls(pid, start_ticks, instance_id, project)


@dataclass(frozen=True)
class _FrozenRegistration:
    registration: PrivateOperatorIPCRegistration
    st_dev: int
    st_ino: int
    canonical: bytes


def _read_registration(root_fd: int, filename: str) -> _FrozenRegistration:
    match = IPC_REGISTRATION_NAME_RE.fullmatch(filename)
    if match is None:
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_REGISTRATION_UNSAFE")
    try:
        fd = os.open(filename, _FILE_READ_FLAGS, dir_fd=root_fd)
    except OSError as exc:
        reason = (
            "OPERATOR_PRIVATE_IPC_REGISTRATION_UNSAFE"
            if exc.errno in {errno.ELOOP, errno.EISDIR}
            else "OPERATOR_PRIVATE_IPC_UNAVAILABLE"
        )
        raise PrivateOperatorIPCError(reason) from exc
    close_ok = True
    try:
        before = os.fstat(fd)
        _validate_private_regular(before, max_size=2048)
        raw = _read_all_fd(fd, before.st_size)
        after = os.fstat(fd)
        if (before.st_dev, before.st_ino, before.st_size) != (after.st_dev, after.st_ino, after.st_size):
            raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_REGISTRATION_CHANGED")
        try:
            value = _strict_json_object(raw)
            registration = PrivateOperatorIPCRegistration.from_dict(value)
        except PrivateOperatorIPCError as exc:
            if exc.reason_code == "OPERATOR_PRIVATE_PROTOCOL_INVALID":
                raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_REGISTRATION_INVALID") from exc
            raise
        if registration.filename != filename or int(match.group(1)) != registration.pid:
            raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_REGISTRATION_INVALID")
        canonical = _canonical_json_bytes(registration.as_dict())
        if raw != canonical:
            raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_REGISTRATION_INVALID")
        return _FrozenRegistration(registration, before.st_dev, before.st_ino, canonical)
    except PrivateOperatorIPCError:
        raise
    except OSError as exc:
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_UNAVAILABLE") from exc
    finally:
        close_ok = _close_owned_fd(fd)
        if not close_ok:
            raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_UNAVAILABLE")


def _write_all(fd: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        written = os.write(fd, payload[offset:])
        if written <= 0:
            raise OSError("short write")
        offset += written


def _rollback_published_registration(
    root_fd: int,
    filename: str,
    expected_identity: tuple[int, int],
) -> bool:
    try:
        current = os.stat(filename, dir_fd=root_fd, follow_symlinks=False)
        if (current.st_dev, current.st_ino) != expected_identity:
            return False
        _validate_private_regular(current, max_size=2048)
        os.unlink(filename, dir_fd=root_fd)
        with contextlib.suppress(OSError):
            os.fsync(root_fd)
        return True
    except FileNotFoundError:
        return True
    except (OSError, PrivateOperatorIPCError):
        return False


def _publish_registration(root_fd: int, registration: PrivateOperatorIPCRegistration) -> _FrozenRegistration:
    payload = _canonical_json_bytes(registration.as_dict())
    temp_name = f".tmp-{registration.pid}-{secrets.token_hex(8)}"
    fd: int | None = None
    renamed = False
    completed = False
    published_identity: tuple[int, int] | None = None
    try:
        fd = os.open(temp_name, _FILE_CREATE_FLAGS, 0o600, dir_fd=root_fd)
        os.fchmod(fd, 0o600)
        _validate_private_regular(os.fstat(fd), max_size=None)
        _write_all(fd, payload)
        os.fsync(fd)
        published_info = os.fstat(fd)
        _validate_private_regular(published_info, max_size=2048)
        published_identity = (published_info.st_dev, published_info.st_ino)
        if not _close_owned_fd(fd):
            fd = None
            raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_UNAVAILABLE")
        fd = None
        os.rename(temp_name, registration.filename, src_dir_fd=root_fd, dst_dir_fd=root_fd)
        renamed = True
        os.fsync(root_fd)
        frozen = _read_registration(root_fd, registration.filename)
        if frozen.canonical != payload:
            raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_REGISTRATION_CHANGED")
        completed = True
        return frozen
    except PrivateOperatorIPCError:
        raise
    except BaseException as exc:
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_UNAVAILABLE") from exc
    finally:
        if fd is not None:
            _close_owned_fd(fd)
        if not renamed:
            with contextlib.suppress(OSError):
                os.unlink(temp_name, dir_fd=root_fd)
        elif not completed and published_identity is not None:
            rolled_back = _rollback_published_registration(
                root_fd,
                registration.filename,
                published_identity,
            )
            if not rolled_back:
                active_error = sys.exc_info()[1]
                if isinstance(active_error, PrivateOperatorIPCError):
                    active_error.pending_registration = _FrozenRegistration(
                        registration,
                        published_identity[0],
                        published_identity[1],
                        payload,
                    )


def _remove_expected_registration(root_fd: int, expected: _FrozenRegistration) -> None:
    current = _read_registration(root_fd, expected.registration.filename)
    if (
        current.st_dev != expected.st_dev
        or current.st_ino != expected.st_ino
        or current.canonical != expected.canonical
    ):
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_REGISTRATION_CHANGED")
    try:
        latest = _read_registration(root_fd, expected.registration.filename)
        if (
            latest.st_dev != expected.st_dev
            or latest.st_ino != expected.st_ino
            or latest.canonical != expected.canonical
        ):
            raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_REGISTRATION_CHANGED")
        os.unlink(expected.registration.filename, dir_fd=root_fd)
        os.fsync(root_fd)
    except PrivateOperatorIPCError:
        raise
    except FileNotFoundError as exc:
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_REGISTRATION_CHANGED") from exc
    except OSError as exc:
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_UNAVAILABLE") from exc


def _registration_names(root_fd: int) -> list[str]:
    try:
        names = os.listdir(root_fd)
    except OSError as exc:
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_UNAVAILABLE") from exc
    registrations: list[str] = []
    for name in names:
        if name == IPC_LOCK_FILENAME:
            continue
        if IPC_REGISTRATION_NAME_RE.fullmatch(name) is None:
            raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_REGISTRATION_UNSAFE")
        registrations.append(name)
    if len(registrations) > IPC_MAX_REGISTRATIONS:
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_REGISTRY_SATURATED")
    return sorted(registrations)


def _parse_proc_stat_start_ticks(raw: bytes) -> int:
    try:
        end_comm = raw.rindex(b")")
    except ValueError as exc:
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_PROCESS_IDENTITY_UNAVAILABLE") from exc
    fields = raw[end_comm + 1 :].strip().split()
    if len(fields) <= 19:
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_PROCESS_IDENTITY_UNAVAILABLE")
    try:
        start_ticks = int(fields[19])
    except (TypeError, ValueError) as exc:
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_PROCESS_IDENTITY_UNAVAILABLE") from exc
    if start_ticks <= 0:
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_PROCESS_IDENTITY_UNAVAILABLE")
    return start_ticks


def _process_start_ticks(pid: int) -> int:
    if pid <= 0:
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_PROCESS_IDENTITY_UNAVAILABLE")
    try:
        fd = os.open(f"/proc/{pid}/stat", os.O_RDONLY | os.O_CLOEXEC)
    except FileNotFoundError as exc:
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_PROCESS_NOT_RUNNING") from exc
    except OSError as exc:
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_PROCESS_IDENTITY_UNAVAILABLE") from exc
    try:
        chunks: list[bytes] = []
        total = 0
        while total <= 8192:
            chunk = os.read(fd, min(4096, 8193 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        if total > 8192:
            raise PrivateOperatorIPCError("OPERATOR_PRIVATE_PROCESS_IDENTITY_UNAVAILABLE")
        return _parse_proc_stat_start_ticks(b"".join(chunks))
    finally:
        if not _close_owned_fd(fd):
            raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_UNAVAILABLE")


def _open_pidfd(pid: int) -> int:
    if not _platform_supported():
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_UNSUPPORTED")
    try:
        return os.pidfd_open(pid, 0)
    except ProcessLookupError as exc:
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_PROCESS_NOT_RUNNING") from exc
    except OSError as exc:
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_PROCESS_IDENTITY_UNAVAILABLE") from exc


def _pidfd_alive(pidfd: int) -> bool:
    poller = select.poll()
    poller.register(pidfd, select.POLLIN | select.POLLHUP | select.POLLERR)
    return not bool(poller.poll(0))


def _registration_generation_live(registration: PrivateOperatorIPCRegistration) -> bool:
    pidfd: int | None = None
    try:
        try:
            pidfd = _open_pidfd(registration.pid)
        except PrivateOperatorIPCError as exc:
            if exc.reason_code == "OPERATOR_PRIVATE_PROCESS_NOT_RUNNING":
                return False
            raise
        if not _pidfd_alive(pidfd):
            return False
        try:
            return _process_start_ticks(registration.pid) == registration.process_start_ticks
        except PrivateOperatorIPCError as exc:
            if exc.reason_code == "OPERATOR_PRIVATE_PROCESS_NOT_RUNNING":
                return False
            raise
    finally:
        if pidfd is not None and not _close_owned_fd(pidfd):
            raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_UNAVAILABLE")


def _gc_stale_registrations(root_fd: int) -> list[_FrozenRegistration]:
    live: list[_FrozenRegistration] = []
    for filename in _registration_names(root_fd):
        frozen = _read_registration(root_fd, filename)
        if _registration_generation_live(frozen.registration):
            live.append(frozen)
            continue
        _remove_expected_registration(root_fd, frozen)
    return live


def _live_registrations_read_only(root_fd: int) -> list[_FrozenRegistration]:
    live: list[_FrozenRegistration] = []
    for filename in _registration_names(root_fd):
        frozen = _read_registration(root_fd, filename)
        if _registration_generation_live(frozen.registration):
            live.append(frozen)
    return live


def _peer_credentials(sock: socket.socket) -> tuple[int, int, int]:
    try:
        raw = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        pid, uid, gid = struct.unpack("3i", raw)
    except (OSError, struct.error) as exc:
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_PEER_DENIED") from exc
    if pid <= 0 or uid < 0 or gid < 0:
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_PEER_DENIED")
    return pid, uid, gid


def _validate_connected_peer(
    registration: PrivateOperatorIPCRegistration,
    *,
    peer_pid: int,
    peer_uid: int,
    expected_project_fingerprint: str | None,
) -> None:
    if peer_uid != os.geteuid():
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_PEER_DENIED")
    if peer_pid != registration.pid:
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_PROCESS_IDENTITY_MISMATCH")
    if _process_start_ticks(peer_pid) != registration.process_start_ticks:
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_PROCESS_IDENTITY_MISMATCH")
    if (
        expected_project_fingerprint is not None
        and expected_project_fingerprint != registration.project_fingerprint
    ):
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_PROJECT_MISMATCH")


def _abstract_address(instance_id: str) -> str:
    if IPC_INSTANCE_RE.fullmatch(instance_id) is None:
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_REGISTRATION_INVALID")
    return f"\0colameta.private-attention.v1.{os.geteuid()}.{instance_id}"


def _validate_snapshot(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_PROTOCOL_INVALID")
    expected = {
        "quarantined_close_fd_count",
        "quarantine_attention_threshold",
        "quarantine_status",
        "local_alert_code",
    }
    if set(value) != expected:
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_PROTOCOL_INVALID")
    count = value.get("quarantined_close_fd_count")
    threshold = value.get("quarantine_attention_threshold")
    status_value = value.get("quarantine_status")
    alert = value.get("local_alert_code")
    if not isinstance(count, int) or isinstance(count, bool) or not 0 <= count <= 65535:
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_PROTOCOL_INVALID")
    if threshold != OPERATOR_QUARANTINE_ATTENTION_THRESHOLD or isinstance(threshold, bool):
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_PROTOCOL_INVALID")
    expected_status = "attention" if count >= threshold else "clear"
    expected_alert = OPERATOR_QUARANTINE_ALERT_CODE if expected_status == "attention" else None
    if status_value != expected_status or alert != expected_alert:
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_PROTOCOL_INVALID")
    return {
        "quarantined_close_fd_count": count,
        "quarantine_attention_threshold": threshold,
        "quarantine_status": expected_status,
        "local_alert_code": expected_alert,
    }


def _validate_request(value: dict[str, Any], registration: PrivateOperatorIPCRegistration) -> dict[str, str]:
    if frozenset(value) != _REQUEST_KEYS:
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_PROTOCOL_INVALID")
    if value.get("protocol") != IPC_PROTOCOL or value.get("operation") != "read_attention":
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_PROTOCOL_INVALID")
    instance_id = value.get("instance_id")
    project = value.get("project_fingerprint")
    nonce = value.get("nonce")
    if not isinstance(instance_id, str) or IPC_INSTANCE_RE.fullmatch(instance_id) is None:
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_PROTOCOL_INVALID")
    if not isinstance(project, str) or IPC_DIGEST_RE.fullmatch(project) is None:
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_PROTOCOL_INVALID")
    if not isinstance(nonce, str) or IPC_INSTANCE_RE.fullmatch(nonce) is None:
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_PROTOCOL_INVALID")
    if instance_id != registration.instance_id or project != registration.project_fingerprint:
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_PROTOCOL_BINDING_MISMATCH")
    return {"instance_id": instance_id, "project_fingerprint": project, "nonce": nonce}


def _validate_response(
    value: dict[str, Any],
    registration: PrivateOperatorIPCRegistration,
    nonce: str,
) -> dict[str, Any]:
    if frozenset(value) != _RESPONSE_KEYS:
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_PROTOCOL_INVALID")
    if value.get("protocol") != IPC_PROTOCOL or value.get("operation") != "read_attention_result":
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_PROTOCOL_INVALID")
    if (
        value.get("instance_id") != registration.instance_id
        or value.get("project_fingerprint") != registration.project_fingerprint
        or value.get("nonce") != nonce
    ):
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_PROTOCOL_BINDING_MISMATCH")
    return _validate_snapshot(
        {
            "quarantined_close_fd_count": value.get("quarantined_close_fd_count"),
            "quarantine_attention_threshold": value.get("quarantine_attention_threshold"),
            "quarantine_status": value.get("quarantine_status"),
            "local_alert_code": value.get("local_alert_code"),
        }
    )


def _recv_one_packet(
    sock: socket.socket,
    *,
    empty_reason: str = "OPERATOR_PRIVATE_PROTOCOL_INVALID",
) -> bytes:
    try:
        payload, _ancillary, flags, _address = sock.recvmsg(IPC_MAX_PACKET_BYTES + 1)
    except (OSError, TimeoutError) as exc:
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_UNAVAILABLE") from exc
    if not payload:
        raise PrivateOperatorIPCError(empty_reason)
    if flags & getattr(socket, "MSG_TRUNC", 0) or len(payload) > IPC_MAX_PACKET_BYTES:
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_PROTOCOL_INVALID")
    try:
        readable, _writable, _exceptional = select.select([sock], [], [], 0)
    except (OSError, ValueError) as exc:
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_UNAVAILABLE") from exc
    extra = b""
    extra_flags = 0
    if readable:
        try:
            extra, _ancillary, extra_flags, _address = sock.recvmsg(
                1,
                0,
                getattr(socket, "MSG_PEEK", 0) | getattr(socket, "MSG_DONTWAIT", 0),
            )
        except BlockingIOError:
            extra = b""
            extra_flags = 0
        except OSError as exc:
            if exc.errno not in {errno.EAGAIN, errno.EWOULDBLOCK}:
                raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_UNAVAILABLE") from exc
    if extra or extra_flags & getattr(socket, "MSG_TRUNC", 0):
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_PROTOCOL_INVALID")
    return payload


def _send_one_packet(sock: socket.socket, value: dict[str, Any]) -> None:
    payload = _canonical_json_bytes(value)
    if len(payload) > IPC_MAX_PACKET_BYTES:
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_PROTOCOL_INVALID")
    try:
        sent = sock.send(payload)
    except (OSError, TimeoutError) as exc:
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_UNAVAILABLE") from exc
    if sent != len(payload):
        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_UNAVAILABLE")


class PrivateOperatorHealthIPCServer:
    def __init__(
        self,
        project_path: str,
        *,
        root_path: str | None = None,
        snapshot_supplier: Callable[[], dict[str, Any]] = private_operator_local_runtime_status,
    ):
        self.project_path = os.path.realpath(os.path.abspath(os.path.expanduser(project_path)))
        self.root_path = root_path or _default_root_path()
        self.snapshot_supplier = snapshot_supplier
        self._root_fd: int | None = None
        self._root_identity: tuple[int, int] | None = None
        self._lock_fd: int | None = None
        self._listener: socket.socket | None = None
        self._registration: _FrozenRegistration | None = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._startup_reason: str | None = None
        self._last_internal_reason: str | None = None

    @property
    def available(self) -> bool:
        return self._registration is not None and self._listener is not None

    @property
    def startup_reason(self) -> str | None:
        return self._startup_reason

    def start(self) -> bool:
        if not _platform_supported():
            self._startup_reason = "OPERATOR_PRIVATE_IPC_UNSUPPORTED"
            return False
        try:
            root_fd, root_identity = _open_secure_root(self.root_path)
            self._root_fd = root_fd
            self._root_identity = root_identity
            self._lock_fd = _open_registry_lock(root_fd)
            pid = os.getpid()
            registration = PrivateOperatorIPCRegistration(
                pid=pid,
                process_start_ticks=_process_start_ticks(pid),
                instance_id=secrets.token_hex(16),
                project_fingerprint=_project_fingerprint(self.project_path),
            )
            listener = socket.socket(
                socket.AF_UNIX,
                socket.SOCK_SEQPACKET | socket.SOCK_CLOEXEC,
            )
            listener.settimeout(IPC_TIMEOUT_SECONDS)
            listener.bind(_abstract_address(registration.instance_id))
            listener.listen(IPC_LISTEN_BACKLOG)
            self._listener = listener
            _assert_root_path_identity(self.root_path, root_identity)
            with _locked_registry(self._lock_fd):
                _assert_root_path_identity(self.root_path, root_identity)
                live_registrations = _gc_stale_registrations(root_fd)
                if any(item.registration.filename == registration.filename for item in live_registrations):
                    raise PrivateOperatorIPCError("OPERATOR_PRIVATE_GENERATION_LIVE")
                self._registration = _publish_registration(root_fd, registration)
            self._thread = threading.Thread(
                target=self._serve_loop,
                name="colameta-private-operator-health",
                daemon=True,
            )
            self._thread.start()
            return True
        except PrivateOperatorIPCError as exc:
            self._startup_reason = exc.reason_code
            if self._registration is None and exc.pending_registration is not None:
                self._registration = exc.pending_registration
        except BaseException:
            self._startup_reason = "OPERATOR_PRIVATE_IPC_UNAVAILABLE"
        self.close()
        return False

    def _serve_loop(self) -> None:
        while not self._stop_event.is_set():
            listener = self._listener
            if listener is None:
                return
            try:
                connection, _address = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            try:
                connection.settimeout(IPC_TIMEOUT_SECONDS)
                self._handle_connection(connection)
            except PrivateOperatorIPCError as exc:
                self._last_internal_reason = exc.reason_code
            except BaseException:
                self._last_internal_reason = "OPERATOR_PRIVATE_IPC_UNAVAILABLE"
            finally:
                _close_socket(connection)

    def _handle_connection(self, connection: socket.socket) -> None:
        registration = self._registration.registration if self._registration is not None else None
        if registration is None:
            return
        peer_pid, peer_uid, _peer_gid = _peer_credentials(connection)
        if peer_uid != os.geteuid() or peer_pid <= 0:
            raise PrivateOperatorIPCError("OPERATOR_PRIVATE_PEER_DENIED")
        request = _validate_request(_strict_json_object(_recv_one_packet(connection)), registration)
        snapshot = _validate_snapshot(self.snapshot_supplier())
        _send_one_packet(
            connection,
            {
                "protocol": IPC_PROTOCOL,
                "operation": "read_attention_result",
                "instance_id": registration.instance_id,
                "project_fingerprint": registration.project_fingerprint,
                "nonce": request["nonce"],
                **snapshot,
            },
        )

    def close(self) -> bool:
        self._stop_event.set()
        ok = _close_socket(self._listener)
        self._listener = None
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.0)
            ok = (not thread.is_alive()) and ok
        self._thread = None
        if self._root_fd is not None and self._lock_fd is not None and self._registration is not None:
            try:
                if self._root_identity is None:
                    raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_ROOT_CHANGED")
                with _locked_registry(self._lock_fd):
                    _assert_root_path_identity(self.root_path, self._root_identity)
                    _remove_expected_registration(self._root_fd, self._registration)
            except PrivateOperatorIPCError:
                ok = False
        self._registration = None
        if self._lock_fd is not None:
            ok = _close_owned_fd(self._lock_fd) and ok
        self._lock_fd = None
        if self._root_fd is not None:
            ok = _close_owned_fd(self._root_fd) and ok
        self._root_fd = None
        self._root_identity = None
        return ok

    def __enter__(self) -> "PrivateOperatorHealthIPCServer":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


class PrivateOperatorHealthIPCClient:
    def __init__(self, *, root_path: str | None = None):
        self.root_path = root_path or _default_root_path()

    def query(self, project_path: str | None = None) -> dict[str, Any]:
        if not _platform_supported():
            return private_operator_ipc_unavailable("OPERATOR_PRIVATE_IPC_UNSUPPORTED")
        root_fd: int | None = None
        lock_fd: int | None = None
        selected_registrations: list[tuple[_FrozenRegistration, int]] = []
        result: dict[str, Any] | None = None
        try:
            root_fd, root_identity = _open_secure_root(self.root_path, create=False)
            lock_fd = _open_registry_lock(root_fd, create=False)
            with _locked_registry(lock_fd):
                selected_registrations = self._select_registrations(root_fd, project_path)
            if not _close_owned_fd(lock_fd):
                lock_fd = None
                raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_UNAVAILABLE")
            lock_fd = None
            expected_project = (
                _project_fingerprint(project_path) if project_path is not None else None
            )
            snapshots = [
                self._query_registration(selected, pidfd, expected_project)
                for selected, pidfd in selected_registrations
            ]
            lock_fd = _open_registry_lock(root_fd, create=False)
            with _locked_registry(lock_fd):
                for selected, _pidfd in selected_registrations:
                    registration = selected.registration
                    current = _read_registration(root_fd, registration.filename)
                    if (
                        current.st_dev != selected.st_dev
                        or current.st_ino != selected.st_ino
                        or current.canonical != selected.canonical
                    ):
                        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_REGISTRATION_CHANGED")
                _assert_root_path_identity(self.root_path, root_identity)
            if not all(_pidfd_alive(pidfd) for _selected, pidfd in selected_registrations):
                raise PrivateOperatorIPCError("OPERATOR_PRIVATE_PROCESS_NOT_RUNNING")
            result = _observed_projection(_aggregate_snapshots(snapshots))
        except PrivateOperatorIPCError as exc:
            result = private_operator_ipc_unavailable(exc.reason_code)
        except BaseException:
            result = private_operator_ipc_unavailable("OPERATOR_PRIVATE_IPC_UNAVAILABLE")
        close_ok = _safe_close_many([pidfd for _selected, pidfd in selected_registrations])
        if lock_fd is not None:
            close_ok = _close_owned_fd(lock_fd) and close_ok
        if root_fd is not None:
            close_ok = _close_owned_fd(root_fd) and close_ok
        if not close_ok:
            return private_operator_ipc_unavailable("OPERATOR_PRIVATE_IPC_UNAVAILABLE")
        return result or private_operator_ipc_unavailable("OPERATOR_PRIVATE_IPC_UNAVAILABLE")

    def _query_registration(
        self,
        selected: _FrozenRegistration,
        pidfd: int,
        expected_project_fingerprint: str | None,
    ) -> dict[str, Any]:
        registration = selected.registration
        client_socket: socket.socket | None = None
        try:
            if not _pidfd_alive(pidfd):
                raise PrivateOperatorIPCError("OPERATOR_PRIVATE_PROCESS_NOT_RUNNING")
            client_socket = socket.socket(
                socket.AF_UNIX,
                socket.SOCK_SEQPACKET | socket.SOCK_CLOEXEC,
            )
            client_socket.settimeout(IPC_TIMEOUT_SECONDS)
            try:
                client_socket.connect(_abstract_address(registration.instance_id))
            except OSError as exc:
                raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_UNAVAILABLE") from exc
            peer_pid, peer_uid, _peer_gid = _peer_credentials(client_socket)
            _validate_connected_peer(
                registration,
                peer_pid=peer_pid,
                peer_uid=peer_uid,
                expected_project_fingerprint=expected_project_fingerprint,
            )
            if not _pidfd_alive(pidfd):
                raise PrivateOperatorIPCError("OPERATOR_PRIVATE_PROCESS_NOT_RUNNING")
            nonce = secrets.token_hex(16)
            _send_one_packet(
                client_socket,
                {
                    "protocol": IPC_PROTOCOL,
                    "operation": "read_attention",
                    "instance_id": registration.instance_id,
                    "project_fingerprint": registration.project_fingerprint,
                    "nonce": nonce,
                },
            )
            snapshot = _validate_response(
                _strict_json_object(
                    _recv_one_packet(
                        client_socket,
                        empty_reason="OPERATOR_PRIVATE_IPC_UNAVAILABLE",
                    )
                ),
                registration,
                nonce,
            )
            if not _pidfd_alive(pidfd):
                raise PrivateOperatorIPCError("OPERATOR_PRIVATE_PROCESS_NOT_RUNNING")
            return snapshot
        finally:
            if not _close_socket(client_socket):
                raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_UNAVAILABLE")

    def _select_registrations(
        self,
        root_fd: int,
        project_path: str | None,
    ) -> list[tuple[_FrozenRegistration, int]]:
        requested_project = _project_fingerprint(project_path) if project_path is not None else None
        candidates: list[tuple[_FrozenRegistration, int]] = []
        matching_registration_seen = False
        identity_failure: str | None = None
        try:
            for filename in _registration_names(root_fd):
                frozen = _read_registration(root_fd, filename)
                registration = frozen.registration
                if requested_project is not None and registration.project_fingerprint != requested_project:
                    continue
                matching_registration_seen = True
                try:
                    pidfd = _open_pidfd(registration.pid)
                except PrivateOperatorIPCError as exc:
                    if exc.reason_code == "OPERATOR_PRIVATE_PROCESS_NOT_RUNNING":
                        identity_failure = exc.reason_code
                        continue
                    raise
                try:
                    if not _pidfd_alive(pidfd):
                        if not _close_owned_fd(pidfd):
                            raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_UNAVAILABLE")
                        identity_failure = "OPERATOR_PRIVATE_PROCESS_NOT_RUNNING"
                        continue
                    if _process_start_ticks(registration.pid) != registration.process_start_ticks:
                        if not _close_owned_fd(pidfd):
                            raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_UNAVAILABLE")
                        identity_failure = "OPERATOR_PRIVATE_PROCESS_IDENTITY_MISMATCH"
                        continue
                except PrivateOperatorIPCError as exc:
                    if exc.reason_code == "OPERATOR_PRIVATE_IPC_UNAVAILABLE":
                        raise
                    if not _close_owned_fd(pidfd):
                        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_UNAVAILABLE") from exc
                    if exc.reason_code == "OPERATOR_PRIVATE_PROCESS_NOT_RUNNING":
                        identity_failure = exc.reason_code
                        continue
                    raise
                except BaseException as exc:
                    if not _close_owned_fd(pidfd):
                        raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_UNAVAILABLE") from exc
                    raise PrivateOperatorIPCError("OPERATOR_PRIVATE_PROCESS_IDENTITY_UNAVAILABLE") from exc
                candidates.append((frozen, pidfd))
            if not candidates:
                if matching_registration_seen and identity_failure is not None:
                    raise PrivateOperatorIPCError(identity_failure)
                raise PrivateOperatorIPCError("OPERATOR_PRIVATE_REGISTRATION_NOT_FOUND")
            if project_path is None and len(candidates) != 1:
                raise PrivateOperatorIPCError("OPERATOR_PRIVATE_SERVICE_AMBIGUOUS")
            selected = candidates
            candidates = []
            return selected
        finally:
            if candidates and not _safe_close_many([pidfd for _frozen, pidfd in candidates]):
                raise PrivateOperatorIPCError("OPERATOR_PRIVATE_IPC_UNAVAILABLE")


def query_private_operator_health(
    project_path: str | None = None,
    *,
    root_path: str | None = None,
) -> dict[str, Any]:
    return PrivateOperatorHealthIPCClient(root_path=root_path).query(project_path)


@contextlib.contextmanager
def private_operator_health_ipc_server(
    project_path: str,
    *,
    root_path: str | None = None,
    snapshot_supplier: Callable[[], dict[str, Any]] = private_operator_local_runtime_status,
) -> Iterator[PrivateOperatorHealthIPCServer]:
    server = PrivateOperatorHealthIPCServer(
        project_path,
        root_path=root_path,
        snapshot_supplier=snapshot_supplier,
    )
    server.start()
    try:
        yield server
    finally:
        server.close()
