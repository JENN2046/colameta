import fcntl
import hashlib
import json
import logging
import os
import pwd
import re
import stat
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any

from runner.runner_paths import resolve_project_runner_path
from runner.sensitive_redaction import redact_sensitive_text
from runner.work_item_governance.references import optional_work_item_reference_rejections


EVENT_TYPES = frozenset({
    "run_claimed",
    "worker_started",
    "executor_preparing",
    "executor_blocked",
    "executor_dispatch_started",
    "executor_started",
    "executor_stdout",
    "executor_stderr",
    "executor_finished",
    "executor_failed",
    "executor_tool_event",
    "executor_command_started",
    "executor_command_finished",
    "git_diff_changed",
    "heartbeat",
    "validation_started",
    "validation_finished",
    "report_written",
    "run_completed",
    "run_failed",
    "run_orphaned",
})

_RUN_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,158}[A-Za-z0-9]|[A-Za-z0-9]")
_AUTHORITY_ID_RE = re.compile(r"[0-9a-f]{32}")
_ADMISSION_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_EVENTS_FILENAME = "events.jsonl"
_MAX_RECORD_BYTES = 1024 * 1024
_READ_CHUNK_BYTES = 128 * 1024
_MAX_DURABLE_FILE_BYTES = 16 * 1024 * 1024
_MAX_PROOF_RECORDS = 10_000
_RUN_LOCKS: dict[tuple[str, str], threading.RLock] = {}
_RUN_LOCKS_GUARD = threading.Lock()
_EVENT_BASE_FIELDS = frozenset({
    "schema_version", "run_id", "preview_id", "version", "provider",
    "execution_mode", "event_type", "phase", "level", "message",
    "timestamp", "data",
})
_EVENT_WORK_FIELDS = frozenset({
    "work_item_id", "task_version", "attempt_id", "artifact_refs",
})
_EVENT_AUTHORITY_FIELDS = frozenset({
    "executor_authority_id", "admission_sha256",
})
_EVENT_STRING_FIELDS = frozenset({
    "schema_version", "run_id", "preview_id", "version", "provider",
    "execution_mode", "event_type", "phase", "level", "message",
    "timestamp", "work_item_id", "attempt_id", "executor_authority_id",
    "admission_sha256",
})
_PRIVATE_LINEAGE_CANONICAL_KEYS = frozenset({
    "executor_authority_id",
    "admission_sha256",
})
_PRIVATE_LINEAGE_ALIAS_KEYS = frozenset({
    "authority_id",
    "authority_alias",
    "executor_authority",
    "fresh_executor_authority_id",
    "expected_executor_authority_id",
    "expected_admission_sha256",
    "admission_hash",
    "admission_digest",
    "admission_alias",
})


class ExecutorEventIntegrityError(RuntimeError):
    def __init__(self, error_code: str):
        self.error_code = error_code or "EVENT_INTEGRITY_FAILED"
        super().__init__(self.error_code)


def _trusted_directory_metadata(
    metadata: os.stat_result,
    *,
    exact_mode: int | None = None,
) -> None:
    """Enforce the explicit local trust model for durable path ancestors.

    Root- or current-user-owned directories are accepted. Group/other write
    access is rejected, except for a root-owned sticky world-writable transit
    directory such as ``/tmp``; every descendant is still opened and pinned
    independently with ``O_NOFOLLOW``.
    """
    mode = stat.S_IMODE(metadata.st_mode)
    sticky_root_transit = bool(
        metadata.st_uid == 0
        and mode & stat.S_ISVTX
        and mode & 0o002
    )
    exclusive_owner_group = bool(
        metadata.st_uid == os.geteuid()
        and metadata.st_gid == os.getegid()
        and not mode & 0o002
        and all(
            account.pw_uid == os.geteuid()
            for account in pwd.getpwall()
            if account.pw_gid == metadata.st_gid
        )
    )
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid not in {0, os.geteuid()}
        or metadata.st_nlink < 2
        or (
            mode & 0o022
            and not sticky_root_transit
            and not (mode & 0o020 and exclusive_owner_group)
        )
        or (exact_mode is not None and mode != exact_mode)
    ):
        raise OSError("durable path directory component is not trusted")


def _path_components(path: str) -> list[str]:
    absolute = os.path.abspath(os.path.expanduser(path))
    if absolute == os.path.sep:
        return []
    return [component for component in absolute.split(os.path.sep) if component]


def _open_pinned_directory_chain(path: str) -> list[dict[str, Any]]:
    """Open and pin every directory from filesystem root through ``path``."""
    absolute = os.path.abspath(os.path.expanduser(path))
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
    root_fd = os.open(os.path.sep, flags)
    chain: list[dict[str, Any]] = []
    try:
        root_metadata = os.fstat(root_fd)
        _trusted_directory_metadata(root_metadata)
        chain.append({
            "fd": root_fd,
            "name": None,
            "identity": root_metadata,
            "path": os.path.sep,
            "exact_mode": None,
        })
        root_fd = -1
        current_path = os.path.sep
        for component in _path_components(absolute):
            parent_fd = int(chain[-1]["fd"])
            before = os.stat(component, dir_fd=parent_fd, follow_symlinks=False)
            _trusted_directory_metadata(before)
            child_fd = os.open(component, flags, dir_fd=parent_fd)
            opened = os.fstat(child_fd)
            try:
                _trusted_directory_metadata(opened)
            except Exception:
                os.close(child_fd)
                raise
            if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
                os.close(child_fd)
                raise OSError("durable path directory changed identity")
            current_path = os.path.join(current_path, component)
            chain.append({
                "fd": child_fd,
                "name": component,
                "identity": opened,
                "path": current_path,
                "exact_mode": None,
            })
        return chain
    except Exception:
        _close_pinned_directory_chain(chain)
        if root_fd >= 0:
            os.close(root_fd)
        raise


def _assert_pinned_directory_chain(chain: list[dict[str, Any]]) -> None:
    if not chain:
        raise OSError("durable path directory chain is incomplete")
    for index, link in enumerate(chain):
        opened = os.fstat(int(link["fd"]))
        _trusted_directory_metadata(opened, exact_mode=link.get("exact_mode"))
        expected = link["identity"]
        if (opened.st_dev, opened.st_ino) != (expected.st_dev, expected.st_ino):
            raise OSError("durable path directory descriptor changed identity")
        if index == 0:
            current = os.stat(os.path.sep, follow_symlinks=False)
        else:
            current = os.stat(
                str(link["name"]),
                dir_fd=int(chain[index - 1]["fd"]),
                follow_symlinks=False,
            )
        _trusted_directory_metadata(current, exact_mode=link.get("exact_mode"))
        if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
            raise OSError("durable path canonical directory chain changed")


def _close_pinned_directory_chain(chain: list[dict[str, Any]]) -> None:
    for link in reversed(chain):
        fd = int(link.get("fd", -1))
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass


def _stable_file_metadata(metadata: os.stat_result) -> tuple[int, ...]:
    """Return all mutation-relevant metadata except access time.

    Access time may legitimately change because of the read itself.  Identity,
    ownership, shape, size, mtime, and ctime must remain byte-for-byte stable.
    """
    return (
        metadata.st_mode,
        metadata.st_ino,
        metadata.st_dev,
        metadata.st_nlink,
        metadata.st_uid,
        metadata.st_gid,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _stat_identity(metadata: os.stat_result) -> dict[str, int]:
    return {"device": int(metadata.st_dev), "inode": int(metadata.st_ino)}


def _stat_metadata(metadata: os.stat_result) -> dict[str, int]:
    return {
        "device": int(metadata.st_dev),
        "inode": int(metadata.st_ino),
        "mode": int(metadata.st_mode),
        "uid": int(metadata.st_uid),
        "gid": int(metadata.st_gid),
        "nlink": int(metadata.st_nlink),
        "size": int(metadata.st_size),
        "mtime_ns": int(metadata.st_mtime_ns),
        "ctime_ns": int(metadata.st_ctime_ns),
    }


def _read_exact_regular_file_pass(file_fd: int, size: int) -> bytes:
    chunks: list[bytes] = []
    offset = 0
    while offset < size:
        chunk = os.pread(file_fd, min(_READ_CHUNK_BYTES, size - offset), offset)
        if not chunk:
            raise OSError("durable file truncated during bounded read")
        chunks.append(chunk)
        offset += len(chunk)
    if os.pread(file_fd, 1, size):
        raise OSError("durable file grew during bounded read")
    return b"".join(chunks)


def _read_stable_regular_fd(
    file_fd: int,
    opened: os.stat_result,
    *,
    max_bytes: int,
) -> bytes:
    """Prove one complete, bounded, repeatable snapshot of an open file."""
    initial_size = opened.st_size
    if initial_size < 0 or initial_size > max_bytes:
        raise OSError("durable file exceeds size limit")
    expected_metadata = _stable_file_metadata(opened)
    first = _read_exact_regular_file_pass(file_fd, initial_size)
    after_first = os.fstat(file_fd)
    ExecutorEventStore._assert_trusted_event_file(after_first)
    if _stable_file_metadata(after_first) != expected_metadata:
        raise OSError("durable file metadata changed during first read")
    second = _read_exact_regular_file_pass(file_fd, initial_size)
    after_second = os.fstat(file_fd)
    ExecutorEventStore._assert_trusted_event_file(after_second)
    if _stable_file_metadata(after_second) != expected_metadata or second != first:
        raise OSError("durable file snapshot was not repeatable")
    return first


def read_trusted_owned_regular_file(
    path: str,
    *,
    trusted_root: str,
    max_bytes: int = _MAX_DURABLE_FILE_BYTES,
) -> dict[str, Any]:
    """Read a regular file through a fully pinned, no-follow ancestor chain."""
    absolute = os.path.abspath(os.path.expanduser(path))
    root = os.path.abspath(os.path.expanduser(trusted_root))
    try:
        if os.path.commonpath((absolute, root)) != root:
            raise OSError("durable file is outside its trusted root")
    except ValueError as exc:
        raise OSError("durable file root mismatch") from exc
    parent = os.path.dirname(absolute)
    filename = os.path.basename(absolute)
    if not filename or filename in {".", ".."}:
        raise OSError("durable file name is invalid")
    chain = _open_pinned_directory_chain(parent)
    file_fd = -1
    try:
        parent_fd = int(chain[-1]["fd"])
        before = os.stat(filename, dir_fd=parent_fd, follow_symlinks=False)
        ExecutorEventStore._assert_trusted_event_file(before)
        file_fd = os.open(
            filename,
            os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=parent_fd,
        )
        opened = os.fstat(file_fd)
        ExecutorEventStore._assert_trusted_event_file(opened)
        if _stable_file_metadata(before) != _stable_file_metadata(opened):
            raise OSError("durable file changed identity after precheck")
        _assert_pinned_directory_chain(chain)
        raw = _read_stable_regular_fd(file_fd, opened, max_bytes=max_bytes)
        after = os.fstat(file_fd)
        current = os.stat(filename, dir_fd=parent_fd, follow_symlinks=False)
        ExecutorEventStore._assert_trusted_event_file(after)
        ExecutorEventStore._assert_trusted_event_file(current)
        expected_metadata = _stable_file_metadata(opened)
        if (
            _stable_file_metadata(after) != expected_metadata
            or _stable_file_metadata(current) != expected_metadata
        ):
            raise OSError("durable file changed during read")
        _assert_pinned_directory_chain(chain)
        raw_sha256 = hashlib.sha256(raw).hexdigest()
        return {
            "raw": raw,
            "identity": _stat_identity(opened),
            "metadata": _stat_metadata(opened),
            "size": opened.st_size,
            "raw_sha256": raw_sha256,
        }
    finally:
        if file_fd >= 0:
            os.close(file_fd)
        _close_pinned_directory_chain(chain)


def _collect_private_lineage_values(value: Any) -> set[str]:
    private_values: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            normalized_key = str(key).strip().lower()
            if (
                normalized_key
                in _PRIVATE_LINEAGE_CANONICAL_KEYS | _PRIVATE_LINEAGE_ALIAS_KEYS
                and isinstance(item, str)
                and item
            ):
                private_values.add(item)
            private_values.update(_collect_private_lineage_values(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            private_values.update(_collect_private_lineage_values(item))
    return private_values


def public_executor_projection(value: Any) -> Any:
    """Return a recursively safe public view of executor lineage data.

    Canonical pair fields, caller-supplied proof flags, and aliased copies of
    the exact private pair values are removed.  Projection is deliberately
    non-assertive: only a caller that has completed the durable multi-surface
    verifier may add a public proof result after projection.
    """
    private_values = _collect_private_lineage_values(value)

    def redact_private_values(text: str) -> str:
        redacted = text
        for private_value in sorted(private_values, key=len, reverse=True):
            if private_value:
                redacted = re.sub(
                    re.escape(private_value),
                    "[private-lineage-redacted]",
                    redacted,
                    flags=re.IGNORECASE,
                )
        return redacted

    def project(item: Any) -> Any:
        if isinstance(item, dict):
            projected: dict[str, Any] = {}
            for key, child in item.items():
                key_text = str(key)
                normalized_key = key_text.strip().lower()
                if normalized_key in {
                    *_PRIVATE_LINEAGE_CANONICAL_KEYS,
                    *_PRIVATE_LINEAGE_ALIAS_KEYS,
                    "fresh_authority_bound",
                    "fresh_authority_proof",
                    "event_stream",
                } or (
                    normalized_key.startswith("fresh_authority_")
                    and any(
                        marker in normalized_key
                        for marker in ("present", "proof", "verified", "bound", "digest")
                    )
                ):
                    continue
                public_key = redact_private_values(key_text)
                projected[public_key] = (
                    redact_private_values(child)
                    if isinstance(child, str)
                    else project(child)
                )
            return projected
        if isinstance(item, (list, tuple)):
            return [project(child) for child in item]
        if isinstance(item, str):
            return redact_private_values(item)
        return item

    return project(value)


def _redact_text(text: str) -> str:
    return redact_sensitive_text(text, replacement_token="***", preserve_token_prefix=False)


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, dict):
        return {k: _redact_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    return value


def redact_event_data(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        return data
    SENSITIVE_KEYS = frozenset({"prompt_body", "stdout", "stderr", "command", "env", "bearer_token", "api_key", "secret"})
    shallow = dict(data)
    for key, value in list(shallow.items()):
        if key in SENSITIVE_KEYS:
            shallow[key] = _redact_value(value)
        elif isinstance(value, dict):
            shallow[key] = _redact_value(_deep_key_aware_redact(value))
        elif isinstance(value, list):
            shallow[key] = _redact_value(value)
    if "stdout_tail" in shallow:
        shallow["stdout_tail"] = _redact_text(str(shallow["stdout_tail"]))[:2000]
    if "stderr_tail" in shallow:
        shallow["stderr_tail"] = _redact_text(str(shallow["stderr_tail"]))[:2000]
    return shallow


def _deep_key_aware_redact(data: dict[str, Any]) -> dict[str, Any]:
    SENSITIVE_KEYS = frozenset({"prompt_body", "stdout", "stderr", "command", "env", "bearer_token", "api_key", "secret"})
    result: dict[str, Any] = {}
    for key, value in data.items():
        if key in SENSITIVE_KEYS:
            result[key] = _redact_value(value)
        elif isinstance(value, dict):
            result[key] = _deep_key_aware_redact(value)
        elif isinstance(value, list):
            result[key] = [_deep_key_aware_redact(v) if isinstance(v, dict) else _redact_value(v) for v in value]
        else:
            result[key] = _redact_value(value)
    return result


class ExecutorEventStore:
    SCHEMA_VERSION = "1.1"

    def __init__(self, project_root: str):
        self.project_root = os.path.abspath(os.path.expanduser(project_root))

    def _runs_dir(self) -> str:
        return resolve_project_runner_path(self.project_root, "runtime", "executor-runs")

    def _events_file(self, run_id: str) -> str:
        return os.path.join(self._runs_dir(), run_id, "events.jsonl")

    def _run_lock(self, run_id: str) -> threading.RLock:
        key = (self.project_root, run_id)
        with _RUN_LOCKS_GUARD:
            return _RUN_LOCKS.setdefault(key, threading.RLock())

    @staticmethod
    def _valid_run_id(run_id: str) -> bool:
        return (
            isinstance(run_id, str)
            and run_id not in {".", ".."}
            and _RUN_ID_RE.fullmatch(run_id) is not None
        )

    @staticmethod
    def _assert_trusted_directory(metadata: os.stat_result, *, run_dir: bool = False) -> None:
        _trusted_directory_metadata(metadata, exact_mode=0o700 if run_dir else None)

    @classmethod
    def _open_child_directory(
        cls,
        parent_fd: int,
        name: str,
        *,
        create: bool,
        run_dir: bool = False,
    ) -> tuple[int, os.stat_result]:
        created = False
        try:
            metadata = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            if not create:
                raise
            try:
                os.mkdir(name, mode=0o700, dir_fd=parent_fd)
                created = True
            except FileExistsError:
                pass
            metadata = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if created and stat.S_IMODE(metadata.st_mode) != 0o700:
            raise OSError("new executor event directory mode is not private")
        cls._assert_trusted_directory(metadata, run_dir=run_dir)
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
        child_fd = os.open(name, flags, dir_fd=parent_fd)
        opened = os.fstat(child_fd)
        try:
            cls._assert_trusted_directory(opened, run_dir=run_dir)
        except Exception:
            os.close(child_fd)
            raise
        if (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino):
            os.close(child_fd)
            raise OSError("executor event directory component changed identity")
        return child_fd, opened

    def _open_run_dir(self, run_id: str, *, create: bool) -> list[dict[str, Any]]:
        if not self._valid_run_id(run_id):
            raise ValueError("invalid executor event run id")
        chain = _open_pinned_directory_chain(self.project_root)
        try:
            for component in (".colameta", "runtime", "executor-runs", run_id):
                parent_fd = int(chain[-1]["fd"])
                is_run_dir = component == run_id
                next_fd, metadata = self._open_child_directory(
                    parent_fd,
                    component,
                    create=create,
                    run_dir=is_run_dir,
                )
                chain.append({
                    "fd": next_fd,
                    "parent_fd": parent_fd,
                    "name": component,
                    "identity": metadata,
                    "run_dir": is_run_dir,
                    "exact_mode": 0o700 if is_run_dir else None,
                })
            self._assert_directory_chain(chain)
            return chain
        except Exception:
            self._close_directory_chain(chain)
            raise

    def _assert_directory_chain(self, chain: list[dict[str, Any]]) -> None:
        if len(chain) < 5:
            raise OSError("executor event directory chain is incomplete")
        _assert_pinned_directory_chain(chain)

    @staticmethod
    def _close_directory_chain(chain: list[dict[str, Any]]) -> None:
        _close_pinned_directory_chain(chain)

    @staticmethod
    def _precheck_regular_file(
        run_fd: int, filename: str, *, allow_missing: bool
    ) -> os.stat_result | None:
        try:
            metadata = os.stat(filename, dir_fd=run_fd, follow_symlinks=False)
        except FileNotFoundError:
            if allow_missing:
                return None
            raise
        ExecutorEventStore._assert_trusted_event_file(metadata)
        return metadata

    @staticmethod
    def _assert_trusted_event_file(metadata: os.stat_result) -> None:
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) & 0o077
        ):
            raise OSError("executor event path is not a trusted regular file")

    @classmethod
    def _assert_open_file_identity(
        cls,
        run_fd: int,
        event_fd: int,
        expected: os.stat_result | None,
    ) -> os.stat_result:
        opened = os.fstat(event_fd)
        cls._assert_trusted_event_file(opened)
        current = os.stat(_EVENTS_FILENAME, dir_fd=run_fd, follow_symlinks=False)
        cls._assert_trusted_event_file(current)
        opened_identity = (opened.st_dev, opened.st_ino)
        if (current.st_dev, current.st_ino) != opened_identity:
            raise OSError("executor event path identity changed")
        if expected is not None and (expected.st_dev, expected.st_ino) != opened_identity:
            raise OSError("executor event path changed after precheck")
        return opened

    @staticmethod
    def _bounded_flock(event_fd: int, operation: int) -> None:
        deadline = time.monotonic() + 5.0
        while True:
            try:
                fcntl.flock(event_fd, operation | fcntl.LOCK_NB)
                return
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("executor event lock unavailable")
                time.sleep(0.01)

    @staticmethod
    def _private_lineage(record: dict[str, Any], actual_run_id: str) -> dict[str, Any] | None:
        if record.get("schema_version") != ExecutorEventStore.SCHEMA_VERSION:
            return None
        if record.get("run_id") != actual_run_id or not ExecutorEventStore._valid_run_id(actual_run_id):
            return None
        preview_id = record.get("preview_id")
        authority_id = record.get("executor_authority_id")
        admission_sha256 = record.get("admission_sha256")
        if not isinstance(preview_id, str) or not preview_id.strip():
            return None
        if not isinstance(authority_id, str) or _AUTHORITY_ID_RE.fullmatch(authority_id) is None:
            return None
        if not isinstance(admission_sha256, str) or _ADMISSION_SHA256_RE.fullmatch(admission_sha256) is None:
            return None
        work_target = {field: record.get(field) for field in (
            "work_item_id", "task_version", "attempt_id", "artifact_refs"
        )}
        if any(field not in record for field in work_target):
            return None
        if optional_work_item_reference_rejections(work_target):
            return None
        return {
            "run_id": actual_run_id,
            "preview_id": preview_id,
            "executor_authority_id": authority_id,
            "admission_sha256": admission_sha256,
            **work_target,
        }

    @classmethod
    def _validate_proof_record(
        cls,
        record: dict[str, Any],
        *,
        actual_run_id: str,
        expected_context: dict[str, Any],
        expected_lineage: dict[str, Any],
        post_binding_seen: bool,
    ) -> tuple[str | None, bool]:
        """Validate one proof record against caller-supplied lineage.

        The only proof schemas are an explicitly bounded pre-binding prefix and
        the complete post-binding schema.  Prefix records must precede every
        bound record and can never carry or satisfy authority proof.
        """

        keys = frozenset(record)
        pre_binding_keys = _EVENT_BASE_FIELDS | _EVENT_WORK_FIELDS
        post_binding_keys = pre_binding_keys | _EVENT_AUTHORITY_FIELDS
        if keys == pre_binding_keys:
            if post_binding_seen:
                return "EVENT_PRE_BINDING_RECORD_AFTER_BINDING", False
            is_post_binding = False
        elif keys == post_binding_keys:
            is_post_binding = True
        else:
            return "EVENT_PROOF_FIELDS_INVALID", False
        for field in _EVENT_STRING_FIELDS & keys:
            if not isinstance(record.get(field), str):
                return "EVENT_PROOF_TYPES_INVALID", False
        task_version = record.get("task_version")
        if isinstance(task_version, bool) or not isinstance(task_version, int):
            return "EVENT_PROOF_TYPES_INVALID", False
        artifact_refs = record.get("artifact_refs")
        if not isinstance(artifact_refs, list) or not all(
            isinstance(item, str) for item in artifact_refs
        ):
            return "EVENT_PROOF_TYPES_INVALID", False
        if not isinstance(record.get("data"), dict):
            return "EVENT_PROOF_TYPES_INVALID", False
        if record.get("schema_version") != cls.SCHEMA_VERSION:
            return "EVENT_PROOF_SCHEMA_INVALID", False
        if record.get("run_id") != actual_run_id:
            return "EVENT_PROOF_RUN_ID_MISMATCH", False
        if record.get("event_type") not in EVENT_TYPES:
            return "EVENT_PROOF_EVENT_TYPE_INVALID", False
        for field in (
            "preview_id", "version", "provider", "execution_mode",
            "work_item_id", "task_version", "attempt_id", "artifact_refs",
        ):
            if record.get(field) != expected_context.get(field):
                return "EVENT_PROOF_LINEAGE_MISMATCH", False
        work_target = {
            field: record[field]
            for field in ("work_item_id", "task_version", "attempt_id", "artifact_refs")
        }
        if optional_work_item_reference_rejections(work_target):
            return "EVENT_PROOF_WORK_TARGET_INVALID", False
        if is_post_binding and cls._private_lineage(record, actual_run_id) != expected_lineage:
            return "EVENT_PROOF_LINEAGE_MISMATCH", False
        return None, is_post_binding

    @classmethod
    def _surface_private_lineage(
        cls, surface: dict[str, Any], actual_run_id: str
    ) -> dict[str, Any] | None:
        """Extract strict lineage without inventing schema or run identity."""
        if not isinstance(surface.get("schema_version"), str) or not str(
            surface.get("schema_version")
        ).strip():
            return None
        candidate = dict(surface)
        lineage = surface.get("execution_lineage")
        if isinstance(lineage, dict):
            candidate = {**surface, **lineage}
        record = surface.get("record")
        if isinstance(record, dict):
            candidate = {**surface, **record}
        if "run_id" not in candidate or candidate.get("run_id") != actual_run_id:
            return None
        if not cls._valid_run_id(actual_run_id):
            return None
        preview_id = candidate.get("preview_id")
        authority_id = candidate.get("executor_authority_id")
        admission_sha256 = candidate.get("admission_sha256")
        if not isinstance(preview_id, str) or not preview_id.strip():
            return None
        if not isinstance(authority_id, str) or _AUTHORITY_ID_RE.fullmatch(authority_id) is None:
            return None
        if not isinstance(admission_sha256, str) or _ADMISSION_SHA256_RE.fullmatch(admission_sha256) is None:
            return None
        work_target = {
            field: candidate.get(field)
            for field in ("work_item_id", "task_version", "attempt_id", "artifact_refs")
        }
        if any(field not in candidate for field in work_target):
            return None
        if optional_work_item_reference_rejections(work_target):
            return None
        return {
            "run_id": actual_run_id,
            "preview_id": preview_id,
            "executor_authority_id": authority_id,
            "admission_sha256": admission_sha256,
            **work_target,
        }

    @staticmethod
    def immutable_surface_contract(
        surface: dict[str, Any], *, mutable_fields: frozenset[str] = frozenset()
    ) -> dict[str, Any]:
        return {
            key: value
            for key, value in surface.items()
            if key not in mutable_fields
        }

    @staticmethod
    def contract_digest(contract: dict[str, Any]) -> str:
        return hashlib.sha256(
            json.dumps(
                contract,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _with_private_lineage(
        record: dict[str, Any], event_context: dict[str, Any], actual_run_id: str
    ) -> None:
        authority_id = event_context.get("executor_authority_id")
        admission_sha256 = event_context.get("admission_sha256")
        if not isinstance(authority_id, str) or not isinstance(admission_sha256, str):
            return
        authority_id = authority_id.strip().lower()
        admission_sha256 = admission_sha256.strip().lower()
        if (
            _AUTHORITY_ID_RE.fullmatch(authority_id) is None
            or _ADMISSION_SHA256_RE.fullmatch(admission_sha256) is None
        ):
            return
        candidate = {
            **record,
            "executor_authority_id": authority_id,
            "admission_sha256": admission_sha256,
        }
        if ExecutorEventStore._private_lineage(candidate, actual_run_id) is not None:
            record["executor_authority_id"] = authority_id
            record["admission_sha256"] = admission_sha256

    @staticmethod
    def _without_private_lineage(value: Any) -> Any:
        return public_executor_projection(value)

    @classmethod
    def _public_projection(
        cls, record: dict[str, Any], actual_run_id: str
    ) -> dict[str, Any]:
        projected = public_executor_projection(record)
        return projected if isinstance(projected, dict) else {}

    def append(
        self,
        run_id: str,
        event_type: str,
        data: dict[str, Any] | None = None,
        event_context: dict[str, Any] | None = None,
    ) -> None:
        if not self._valid_run_id(run_id):
            return
        if event_type not in EVENT_TYPES:
            raise ValueError("unknown executor event type")
        if data is None:
            data = {}
        redacted = redact_event_data(data)
        if event_context:
            record: dict[str, Any] = {
                "schema_version": self.SCHEMA_VERSION,
                "run_id": run_id,
                "preview_id": str(event_context.get("preview_id", "")),
                "version": str(event_context.get("version", "")),
                "provider": str(event_context.get("provider", "")),
                "execution_mode": str(event_context.get("execution_mode", "")),
                "event_type": event_type,
                "phase": str(event_context.get("phase", "")),
                "level": str(event_context.get("level", "info")),
                "message": str(event_context.get("message", "")),
                "timestamp": datetime.now(timezone.utc).astimezone().isoformat(),
                "data": redacted,
            }
            work_item_binding = {
                field: event_context.get(field)
                for field in ("work_item_id", "task_version", "attempt_id", "artifact_refs")
                if field in event_context
            }
            if work_item_binding and not optional_work_item_reference_rejections(work_item_binding):
                record.update(work_item_binding)
            self._with_private_lineage(record, event_context, run_id)
        else:
            record = {
                "schema_version": self.SCHEMA_VERSION,
                "run_id": run_id,
                "preview_id": "",
                "version": "",
                "provider": "",
                "execution_mode": "",
                "event_type": event_type,
                "phase": "",
                "level": "info",
                "message": "",
                "timestamp": datetime.now(timezone.utc).astimezone().isoformat(),
                "data": redacted,
            }
        encoded = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
        if len(encoded) > _MAX_RECORD_BYTES:
            logging.getLogger(__name__).error("Executor event record exceeds size limit")
            return
        chain: list[dict[str, Any]] = []
        event_fd = -1
        try:
            with self._run_lock(run_id):
                chain = self._open_run_dir(run_id, create=True)
                run_fd = int(chain[-1]["fd"])
                prechecked = self._precheck_regular_file(
                    run_fd, _EVENTS_FILENAME, allow_missing=True
                )
                open_flags = (
                    os.O_WRONLY
                    | os.O_APPEND
                    | os.O_CLOEXEC
                    | os.O_NOFOLLOW
                    | os.O_NONBLOCK
                )
                if prechecked is None:
                    open_flags |= os.O_CREAT | os.O_EXCL
                try:
                    event_fd = os.open(
                        _EVENTS_FILENAME,
                        open_flags,
                        0o600,
                        dir_fd=run_fd,
                    )
                except FileExistsError:
                    if prechecked is not None:
                        raise
                    prechecked = self._precheck_regular_file(
                        run_fd,
                        _EVENTS_FILENAME,
                        allow_missing=False,
                    )
                    event_fd = os.open(
                        _EVENTS_FILENAME,
                        open_flags & ~(os.O_CREAT | os.O_EXCL),
                        dir_fd=run_fd,
                    )
                self._assert_open_file_identity(run_fd, event_fd, prechecked)
                os.fchmod(event_fd, 0o600)
                self._bounded_flock(event_fd, fcntl.LOCK_EX)
                try:
                    self._assert_directory_chain(chain)
                    self._assert_open_file_identity(run_fd, event_fd, prechecked)
                    remaining = memoryview(encoded)
                    while remaining:
                        written = os.write(event_fd, remaining)
                        if written <= 0:
                            raise OSError("short executor event write")
                        remaining = remaining[written:]
                    os.fsync(event_fd)
                    self._assert_open_file_identity(run_fd, event_fd, prechecked)
                    self._assert_directory_chain(chain)
                finally:
                    fcntl.flock(event_fd, fcntl.LOCK_UN)
        except Exception:
            logging.getLogger(__name__).exception("Failed to write executor event")
        finally:
            if event_fd >= 0:
                os.close(event_fd)
            self._close_directory_chain(chain)

    def _read_records_streaming(
        self,
        run_id: str,
        *,
        limit: int,
        include_private_lineage: bool,
        durable_contract: bool = False,
        stream_origin_contract: bool = False,
        expected_prefix: dict[str, Any] | None = None,
        expected_lineage: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        chain: list[dict[str, Any]] = []
        event_fd = -1
        bounded_limit = max(1, min(int(limit), _MAX_PROOF_RECORDS))
        events: deque[dict[str, Any]] = deque(maxlen=bounded_limit)
        expected_prefix_size = int((expected_prefix or {}).get("size") or 0)
        snapshot: dict[str, Any] | None = None
        record_count = 0
        pre_binding_record_count = 0
        post_binding_record_count = 0
        post_binding_seen = False
        run_claimed_seen = False
        proof_expected: dict[str, Any] | None = None
        if durable_contract:
            if not isinstance(expected_lineage, dict):
                return {
                    "ok": False,
                    "error_code": "EXPECTED_PRIVATE_LINEAGE_INVALID",
                    "events": [],
                }
            expected_record = {"schema_version": self.SCHEMA_VERSION, **expected_lineage}
            proof_expected = self._private_lineage(expected_record, run_id)
            if proof_expected is None:
                return {
                    "ok": False,
                    "error_code": "EXPECTED_PRIVATE_LINEAGE_INVALID",
                    "events": [],
                }
            for field in ("preview_id", "version", "provider", "execution_mode"):
                if not isinstance(expected_lineage.get(field), str):
                    return {
                        "ok": False,
                        "error_code": "EXPECTED_PRIVATE_LINEAGE_INVALID",
                        "events": [],
                    }

        def consume(line: bytes) -> dict[str, Any] | None:
            nonlocal record_count, pre_binding_record_count
            nonlocal post_binding_record_count, post_binding_seen, run_claimed_seen
            if not line.strip():
                return None
            record_count += 1
            if record_count > _MAX_PROOF_RECORDS:
                return {"ok": False, "error_code": "EVENT_RECORD_LIMIT_EXCEEDED", "events": []}
            try:
                raw = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return {"ok": False, "error_code": "EVENT_INTERIOR_CORRUPTION", "events": []}
            if not isinstance(raw, dict):
                return {"ok": False, "error_code": "EVENT_INTERIOR_CORRUPTION", "events": []}
            if stream_origin_contract:
                if raw.get("schema_version") != self.SCHEMA_VERSION:
                    return {"ok": False, "error_code": "EVENT_ORIGIN_SCHEMA_INVALID", "events": []}
                if raw.get("run_id") != run_id:
                    return {"ok": False, "error_code": "EVENT_PROOF_RUN_ID_MISMATCH", "events": []}
                if raw.get("event_type") == "run_claimed":
                    run_claimed_seen = True
            raw_has_private_fields = any(
                field in raw
                for field in ("executor_authority_id", "admission_sha256")
            )
            if raw_has_private_fields and "schema_version" not in raw:
                return {"ok": False, "error_code": "EVENT_PRIVATE_LINEAGE_INVALID", "events": []}
            if durable_contract:
                if raw.get("schema_version") != self.SCHEMA_VERSION:
                    return {"ok": False, "error_code": "EVENT_PROOF_SCHEMA_INVALID", "events": []}
                if "run_id" not in raw:
                    return {"ok": False, "error_code": "EVENT_RUN_ID_MISSING", "events": []}
                if raw.get("run_id") != run_id:
                    return {"ok": False, "error_code": "EVENT_PROOF_RUN_ID_MISMATCH", "events": []}
                assert proof_expected is not None
                proof_error, is_post_binding = self._validate_proof_record(
                    raw,
                    actual_run_id=run_id,
                    expected_context=expected_lineage or {},
                    expected_lineage=proof_expected,
                    post_binding_seen=post_binding_seen,
                )
                if proof_error is not None:
                    return {"ok": False, "error_code": proof_error, "events": []}
                if is_post_binding:
                    post_binding_seen = True
                    post_binding_record_count += 1
                else:
                    pre_binding_record_count += 1
            if raw.get("schema_version") == self.SCHEMA_VERSION and "run_id" not in raw:
                return {"ok": False, "error_code": "EVENT_RUN_ID_MISSING", "events": []}
            normalized = raw if durable_contract else self._normalize_record(raw)
            has_private_fields = any(
                field in normalized
                for field in ("executor_authority_id", "admission_sha256")
            )
            if (
                normalized.get("schema_version") == self.SCHEMA_VERSION
                and has_private_fields
                and self._private_lineage(normalized, run_id) is None
            ):
                return {"ok": False, "error_code": "EVENT_PRIVATE_LINEAGE_INVALID", "events": []}
            events.append(
                normalized
                if include_private_lineage
                else self._public_projection(normalized, run_id)
            )
            return None

        try:
            with self._run_lock(run_id):
                chain = self._open_run_dir(run_id, create=False)
                run_fd = int(chain[-1]["fd"])
                prechecked = self._precheck_regular_file(
                    run_fd, _EVENTS_FILENAME, allow_missing=False
                )
                event_fd = os.open(
                    _EVENTS_FILENAME,
                    os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK,
                    dir_fd=run_fd,
                )
                self._assert_open_file_identity(run_fd, event_fd, prechecked)
                self._bounded_flock(event_fd, fcntl.LOCK_SH)
                try:
                    self._assert_directory_chain(chain)
                    opened_metadata = self._assert_open_file_identity(
                        run_fd, event_fd, prechecked
                    )
                    if prechecked is None or _stable_file_metadata(
                        prechecked
                    ) != _stable_file_metadata(opened_metadata):
                        raise ValueError("EVENT_DURABLE_METADATA_DRIFT")
                    opened_identity = _stat_identity(opened_metadata)
                    if expected_prefix is not None and expected_prefix.get(
                        "identity"
                    ) != opened_identity:
                        raise ValueError("EVENT_DURABLE_IDENTITY_DRIFT")
                    if opened_metadata.st_size > _MAX_DURABLE_FILE_BYTES:
                        raise ValueError("EVENT_FILE_TOO_LARGE")
                    raw = _read_stable_regular_fd(
                        event_fd,
                        opened_metadata,
                        max_bytes=_MAX_DURABLE_FILE_BYTES,
                    )
                    current = os.stat(
                        _EVENTS_FILENAME,
                        dir_fd=run_fd,
                        follow_symlinks=False,
                    )
                    self._assert_trusted_event_file(current)
                    if _stable_file_metadata(current) != _stable_file_metadata(
                        opened_metadata
                    ):
                        raise ValueError("EVENT_DURABLE_METADATA_DRIFT")
                    self._assert_directory_chain(chain)
                    raw_sha256 = hashlib.sha256(raw).hexdigest()
                    snapshot = {
                        "identity": opened_identity,
                        "metadata": _stat_metadata(opened_metadata),
                        "size": len(raw),
                        "raw_sha256": raw_sha256,
                    }
                finally:
                    fcntl.flock(event_fd, fcntl.LOCK_UN)
            if raw and not raw.endswith(b"\n"):
                return {
                    "ok": False,
                    "error_code": "EVENT_TORN_TAIL",
                    "torn_tail": True,
                    "events": [],
                }
            for line in raw.splitlines():
                if len(line) + 1 > _MAX_RECORD_BYTES:
                    raise ValueError("EVENT_RECORD_TOO_LARGE")
                failure = consume(line)
                if failure is not None:
                    return failure
            if durable_contract and post_binding_record_count == 0:
                return {
                    "ok": False,
                    "error_code": "EVENT_POST_BINDING_PROOF_MISSING",
                    "events": [],
                }
            if stream_origin_contract and not run_claimed_seen:
                return {
                    "ok": False,
                    "error_code": "EVENT_ORIGIN_RUN_CLAIMED_MISSING",
                    "events": [],
                }
            if expected_prefix is not None:
                if len(raw) < expected_prefix_size:
                    return {
                        "ok": False,
                        "error_code": "EVENT_HISTORY_TRUNCATED",
                        "events": [],
                    }
                prefix_sha256 = hashlib.sha256(raw[:expected_prefix_size]).hexdigest()
                expected_prefix_sha256 = str(expected_prefix.get("raw_sha256") or "")
                if prefix_sha256 != expected_prefix_sha256:
                    return {
                        "ok": False,
                        "error_code": "EVENT_HISTORY_TAMPERED",
                        "events": [],
                    }
            result = {
                "ok": True,
                "error_code": None,
                "torn_tail": False,
                "events": list(events),
            }
            if durable_contract:
                if snapshot is None:
                    raise ValueError("EVENT_DURABLE_SNAPSHOT_MISSING")
                contract_prefix_size = len(raw)
                result["durable_contract"] = {
                    **snapshot,
                    "content_sha256": self.contract_digest({"events": list(events)}),
                    "prefix_size": contract_prefix_size,
                    "prefix_sha256": hashlib.sha256(
                        raw[:contract_prefix_size]
                    ).hexdigest(),
                    "record_count": record_count,
                    "pre_binding_record_count": pre_binding_record_count,
                    "post_binding_record_count": post_binding_record_count,
                }
            if stream_origin_contract:
                if snapshot is None:
                    raise ValueError("EVENT_DURABLE_SNAPSHOT_MISSING")
                result["stream_origin_contract"] = {
                    "identity": snapshot["identity"],
                    "size": snapshot["size"],
                    "raw_sha256": snapshot["raw_sha256"],
                    "record_count": record_count,
                }
            return result
        finally:
            if event_fd >= 0:
                os.close(event_fd)
            self._close_directory_chain(chain)

    def read_with_integrity(
        self,
        run_id: str,
        limit: int = 100,
        *,
        include_private_lineage: bool = False,
    ) -> dict[str, Any]:
        if not self._valid_run_id(run_id):
            return {"ok": False, "error_code": "EVENT_RUN_ID_INVALID", "events": []}
        try:
            return self._read_records_streaming(
                run_id,
                limit=limit,
                include_private_lineage=include_private_lineage,
            )
        except ValueError as exc:
            code = str(exc)
            return {
                "ok": False,
                "error_code": code
                if code in {
                    "EVENT_RECORD_TOO_LARGE",
                    "EVENT_DURABLE_IDENTITY_DRIFT",
                    "EVENT_DURABLE_METADATA_DRIFT",
                    "EVENT_RECORD_LIMIT_EXCEEDED",
                    "EVENT_FILE_TOO_LARGE",
                }
                else "EVENT_STORE_UNAVAILABLE",
                "events": [],
            }
        except FileNotFoundError:
            return {"ok": False, "error_code": "EVENT_STORE_NOT_FOUND", "events": []}
        except Exception:
            return {"ok": False, "error_code": "EVENT_STORE_UNAVAILABLE", "events": []}

    def capture_durable_contract(
        self,
        run_id: str,
        *,
        expected_prefix: dict[str, Any] | None = None,
        expected_lineage: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self._valid_run_id(run_id):
            return {"ok": False, "error_code": "EVENT_RUN_ID_INVALID"}
        try:
            result = self._read_records_streaming(
                run_id,
                limit=1_000_000,
                include_private_lineage=True,
                durable_contract=True,
                expected_prefix=expected_prefix,
                expected_lineage=expected_lineage,
            )
        except ValueError as exc:
            code = str(exc)
            return {
                "ok": False,
                "error_code": code
                if code in {
                    "EVENT_RECORD_TOO_LARGE",
                    "EVENT_DURABLE_IDENTITY_DRIFT",
                    "EVENT_DURABLE_METADATA_DRIFT",
                    "EVENT_RECORD_LIMIT_EXCEEDED",
                    "EVENT_FILE_TOO_LARGE",
                }
                else "EVENT_STORE_UNAVAILABLE",
            }
        except FileNotFoundError:
            return {"ok": False, "error_code": "EVENT_STORE_NOT_FOUND"}
        except Exception:
            return {"ok": False, "error_code": "EVENT_STORE_UNAVAILABLE"}
        if not result.get("ok"):
            return {
                "ok": False,
                "error_code": str(result.get("error_code") or "EVENT_INTEGRITY_FAILED"),
            }
        return {
            "ok": True,
            "events": result.get("events", []),
            "durable_contract": result.get("durable_contract", {}),
        }

    def capture_stream_origin(self, run_id: str) -> dict[str, Any]:
        """Capture the durable pre-binding identity and exact history prefix."""

        if not self._valid_run_id(run_id):
            return {"ok": False, "error_code": "EVENT_RUN_ID_INVALID"}
        try:
            result = self._read_records_streaming(
                run_id,
                limit=1,
                include_private_lineage=True,
                stream_origin_contract=True,
            )
        except ValueError as exc:
            code = str(exc)
            return {
                "ok": False,
                "error_code": code
                if code in {
                    "EVENT_RECORD_TOO_LARGE",
                    "EVENT_DURABLE_IDENTITY_DRIFT",
                    "EVENT_DURABLE_METADATA_DRIFT",
                    "EVENT_RECORD_LIMIT_EXCEEDED",
                    "EVENT_FILE_TOO_LARGE",
                }
                else "EVENT_STORE_UNAVAILABLE",
            }
        except FileNotFoundError:
            return {"ok": False, "error_code": "EVENT_STORE_NOT_FOUND"}
        except Exception:
            return {"ok": False, "error_code": "EVENT_STORE_UNAVAILABLE"}
        if not result.get("ok"):
            return {
                "ok": False,
                "error_code": str(result.get("error_code") or "EVENT_INTEGRITY_FAILED"),
            }
        return {
            "ok": True,
            "stream_origin_contract": result.get("stream_origin_contract", {}),
        }

    def read(
        self,
        run_id: str,
        limit: int = 100,
        *,
        include_private_lineage: bool = False,
    ) -> list[dict[str, Any]]:
        result = self.read_with_integrity(
            run_id,
            limit,
            include_private_lineage=include_private_lineage,
        )
        if not result.get("ok"):
            error_code = str(result.get("error_code") or "EVENT_INTEGRITY_FAILED")
            if error_code in {"EVENT_STORE_NOT_FOUND", "EVENT_RUN_ID_INVALID"}:
                return []
            raise ExecutorEventIntegrityError(error_code)
        events = result.get("events")
        return events if isinstance(events, list) else []

    def verify_private_lineage(
        self,
        run_id: str,
        *,
        expected_event_context: dict[str, Any],
        event_type: str,
        claim_context: dict[str, Any] | None = None,
        report_context: dict[str, Any] | None = None,
        session_context: dict[str, Any] | None = None,
        binding_context: dict[str, Any] | None = None,
        required_surfaces: tuple[str, ...] = (),
        expected_prefix: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if expected_event_context.get("run_id") != run_id:
            return {
                "ok": False,
                "error_code": "EXPECTED_RUN_ID_MISSING_OR_MISMATCH",
                "safe_digest": "",
            }
        expected_record = {
            "schema_version": self.SCHEMA_VERSION,
            **expected_event_context,
        }
        expected = self._private_lineage(expected_record, run_id)
        if expected is None:
            return {"ok": False, "error_code": "EXPECTED_PRIVATE_LINEAGE_INVALID", "safe_digest": ""}
        contexts = {
            "binding": binding_context,
            "claim": claim_context,
            "report": report_context,
            "session": session_context,
        }
        for required in required_surfaces:
            if contexts.get(required) is None:
                return {
                    "ok": False,
                    "error_code": f"{required.upper()}_LINEAGE_MISSING",
                    "safe_digest": "",
                }
        for name, context in (
            ("binding", binding_context),
            ("claim", claim_context),
            ("report", report_context),
            ("session", session_context),
        ):
            if context is None:
                continue
            candidate = self._surface_private_lineage(context, run_id)
            if candidate != expected:
                return {"ok": False, "error_code": f"{name.upper()}_LINEAGE_MISMATCH", "safe_digest": ""}
        result = self.capture_durable_contract(
            run_id,
            expected_prefix=expected_prefix,
            expected_lineage=expected_event_context,
        )
        if not result.get("ok"):
            return {
                "ok": False,
                "error_code": str(
                    result.get("error_code") or "EVENT_INTEGRITY_FAILED"
                ),
                "safe_digest": "",
            }
        matching = [
            record for record in result.get("events", [])
            if isinstance(record, dict)
            and record.get("event_type") == event_type
            and self._private_lineage(record, run_id) == expected
        ]
        if not matching:
            return {"ok": False, "error_code": "PRIVATE_EVENT_LINEAGE_MISSING", "safe_digest": ""}
        digest_payload = {
            "schema": "executor-private-lineage-safe-digest.v1",
            "run_id": expected["run_id"],
            "preview_id": expected["preview_id"],
            "work_item_id": expected["work_item_id"],
            "task_version": expected["task_version"],
            "attempt_id": expected["attempt_id"],
            "artifact_refs": expected["artifact_refs"],
            "authority_pair_present": True,
        }
        safe_digest = hashlib.sha256(
            json.dumps(digest_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return {"ok": True, "error_code": None, "safe_digest": safe_digest}

    @staticmethod
    def _normalize_record(raw: dict[str, Any]) -> dict[str, Any]:
        if "schema_version" in raw:
            return raw
        ts = raw.get("ts", "")
        evt = raw.get("event", "")
        data_raw = raw.get("data", {})
        if not isinstance(data_raw, dict):
            data_raw = {}
        return {
            "schema_version": "0.9",
            "run_id": str(data_raw.get("run_id", "")),
            "preview_id": str(data_raw.get("preview_id", "")),
            "version": str(data_raw.get("version", "")),
            "provider": str(data_raw.get("provider", "")),
            "execution_mode": str(data_raw.get("execution_mode", "")),
            "event_type": str(evt),
            "phase": "",
            "level": "info",
            "message": "",
            "timestamp": str(ts),
            "data": data_raw,
        }

    def has_events(self, run_id: str) -> bool:
        if not self._valid_run_id(run_id):
            return False
        chain: list[dict[str, Any]] = []
        event_fd = -1
        try:
            chain = self._open_run_dir(run_id, create=False)
            run_fd = int(chain[-1]["fd"])
            prechecked = self._precheck_regular_file(
                run_fd, _EVENTS_FILENAME, allow_missing=False
            )
            event_fd = os.open(
                _EVENTS_FILENAME,
                os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK,
                dir_fd=run_fd,
            )
            self._assert_open_file_identity(run_fd, event_fd, prechecked)
            self._assert_directory_chain(chain)
            return True
        except Exception:
            return False
        finally:
            if event_fd >= 0:
                os.close(event_fd)
            self._close_directory_chain(chain)

    def run_dir(self, run_id: str) -> str:
        return os.path.join(self._runs_dir(), run_id)
