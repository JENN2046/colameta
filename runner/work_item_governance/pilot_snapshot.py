from __future__ import annotations

import hashlib
import os
import shutil
import stat
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from runner.work_item_governance.activation import canonical_path_digest
from runner.work_item_governance.canonical import canonical_sha256, sha256_file
from runner.work_item_governance.errors import WorkItemGovernanceError
from runner.work_item_governance.repository import SQLiteWorkItemLedger


_SNAPSHOT_AUTHORITY = object()
_MAIN_NAME = "work-items.sqlite3"
_WAL_NAME = f"{_MAIN_NAME}-wal"
_SHM_NAME = f"{_MAIN_NAME}-shm"
_LOCK_NAME = "work-items.restore.lock"


def _private_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=False)
    measured = path.lstat()
    if (
        path.is_symlink()
        or not stat.S_ISDIR(measured.st_mode)
        or measured.st_uid != os.getuid()
        or stat.S_IMODE(measured.st_mode) != 0o700
    ):
        raise WorkItemGovernanceError(
            "PILOT_CONFORMANCE_SNAPSHOT_PATH_INVALID",
            "Pilot conformance snapshot directories must be private real directories.",
        )


def _stable_file_entry(path: Path) -> dict[str, Any]:
    before = path.lstat()
    if (
        path.is_symlink()
        or not stat.S_ISREG(before.st_mode)
        or before.st_uid != os.getuid()
        or before.st_nlink != 1
    ):
        raise WorkItemGovernanceError(
            "PILOT_CONFORMANCE_SOURCE_LEDGER_INVALID",
            "Protected Ledger files must be owned, single-link regular files.",
            details={"name": path.name},
        )
    digest = hashlib.sha256()
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    stable_fields = (
        "st_dev",
        "st_ino",
        "st_uid",
        "st_mode",
        "st_nlink",
        "st_size",
        "st_mtime_ns",
        "st_ctime_ns",
    )
    if any(getattr(before, field) != getattr(after, field) for field in stable_fields):
        raise WorkItemGovernanceError(
            "PILOT_CONFORMANCE_SOURCE_LEDGER_CHANGED",
            "Protected Ledger bytes or metadata changed while they were measured.",
            details={"name": path.name},
        )
    return {
        "name": path.name,
        "type": "file",
        "mode": f"{stat.S_IMODE(after.st_mode):04o}",
        "uid": after.st_uid,
        "device": after.st_dev,
        "inode": after.st_ino,
        "link_count": after.st_nlink,
        "size": after.st_size,
        "mtime_ns": after.st_mtime_ns,
        "ctime_ns": after.st_ctime_ns,
        "sha256": digest.hexdigest(),
    }


def _ledger_tree_manifest(ledger: SQLiteWorkItemLedger) -> dict[str, Any]:
    directory = ledger.path.parent
    measured = directory.lstat()
    if (
        directory.is_symlink()
        or not stat.S_ISDIR(measured.st_mode)
        or measured.st_uid != os.getuid()
    ):
        raise WorkItemGovernanceError(
            "PILOT_CONFORMANCE_SOURCE_LEDGER_INVALID",
            "Protected Ledger directory must be an owned real directory.",
        )
    entries: list[dict[str, Any]] = []
    for path in sorted(directory.iterdir(), key=lambda value: value.name):
        entries.append(_stable_file_entry(path))
    names = {entry["name"] for entry in entries}
    if _MAIN_NAME not in names or _LOCK_NAME not in names:
        raise WorkItemGovernanceError(
            "PILOT_CONFORMANCE_SOURCE_LEDGER_INVALID",
            "Protected Ledger snapshotting requires the database and preprovisioned maintenance lock.",
        )
    unexpected = names - {_MAIN_NAME, _WAL_NAME, _SHM_NAME, _LOCK_NAME}
    if unexpected:
        raise WorkItemGovernanceError(
            "PILOT_CONFORMANCE_SOURCE_LEDGER_INVALID",
            "Protected Ledger directory contains an unreviewed file set.",
            details={"unexpected_names": sorted(unexpected)},
        )
    return {
        "directory": {
            "mode": f"{stat.S_IMODE(measured.st_mode):04o}",
            "uid": measured.st_uid,
            "device": measured.st_dev,
            "inode": measured.st_ino,
            "mtime_ns": measured.st_mtime_ns,
            "ctime_ns": measured.st_ctime_ns,
        },
        "entries": entries,
    }


def _copy_readonly_source(source: Path, destination: Path) -> dict[str, Any]:
    before = _stable_file_entry(source)
    source_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    target_flags = (
        os.O_CREAT
        | os.O_EXCL
        | os.O_WRONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    source_fd = os.open(source, source_flags)
    target_fd = os.open(destination, target_flags, 0o600)
    try:
        while chunk := os.read(source_fd, 1024 * 1024):
            remaining = memoryview(chunk)
            while remaining:
                written = os.write(target_fd, remaining)
                remaining = remaining[written:]
        os.fsync(target_fd)
    finally:
        os.close(target_fd)
        os.close(source_fd)
    after = _stable_file_entry(source)
    if after != before or sha256_file(destination) != before["sha256"]:
        raise WorkItemGovernanceError(
            "PILOT_CONFORMANCE_SNAPSHOT_COPY_INVALID",
            "Snapshot input changed or copied bytes differ from the protected Ledger.",
            details={"name": source.name},
        )
    return {
        "name": source.name,
        "size": before["size"],
        "sha256": before["sha256"],
    }


@dataclass(frozen=True)
class PilotConformanceLedgerSnapshot:
    """Capability binding one isolated SQLite snapshot to one protected Ledger."""

    source_project_root: Path
    project_root: Path
    source_ledger_path_digest: str
    source_tree_manifest_digest: str
    snapshot_input_names: tuple[str, ...]
    snapshot_input_digest: str
    binding_digest: str
    _authority: object

    def require_bound_to(self, project_root: str | Path) -> None:
        source = Path(project_root).expanduser().resolve()
        if self._authority is not _SNAPSHOT_AUTHORITY or source != self.source_project_root:
            raise WorkItemGovernanceError(
                "PILOT_CONFORMANCE_SNAPSHOT_INVALID",
                "Pilot conformance requires the exact governed Ledger snapshot capability.",
            )
        expected_binding = canonical_sha256(
            {
                "source_project_root_path_digest": canonical_path_digest(self.source_project_root),
                "source_ledger_path_digest": self.source_ledger_path_digest,
                "source_tree_manifest_digest": self.source_tree_manifest_digest,
                "snapshot_project_root_path_digest": canonical_path_digest(self.project_root),
                "snapshot_input_digest": self.snapshot_input_digest,
            }
        )
        if self.binding_digest != expected_binding:
            raise WorkItemGovernanceError(
                "PILOT_CONFORMANCE_SNAPSHOT_INVALID",
                "Pilot conformance snapshot capability binding changed.",
            )
        if self.project_root == self.source_project_root or not self.project_root.is_dir():
            raise WorkItemGovernanceError(
                "PILOT_CONFORMANCE_SNAPSHOT_INVALID",
                "Pilot conformance snapshot must remain isolated from the protected project.",
            )
        snapshot_main = self.project_root / ".colameta/ledger" / _MAIN_NAME
        if not snapshot_main.is_file() or snapshot_main.is_symlink():
            raise WorkItemGovernanceError(
                "PILOT_CONFORMANCE_SNAPSHOT_INVALID",
                "Pilot conformance snapshot database is unavailable.",
            )
        snapshot_ledger = snapshot_main.parent
        current_inputs = []
        for name in self.snapshot_input_names:
            path = snapshot_ledger / name
            if not path.is_file() or path.is_symlink():
                raise WorkItemGovernanceError(
                    "PILOT_CONFORMANCE_SNAPSHOT_CHANGED",
                    "Pilot conformance snapshot input file set changed.",
                    details={"name": name},
                )
            measured = _stable_file_entry(path)
            current_inputs.append(
                {
                    "name": name,
                    "size": measured["size"],
                    "sha256": measured["sha256"],
                }
            )
        if canonical_sha256(current_inputs) != self.snapshot_input_digest:
            raise WorkItemGovernanceError(
                "PILOT_CONFORMANCE_SNAPSHOT_CHANGED",
                "Pilot conformance snapshot input bytes changed after governed copying.",
            )
        current = _ledger_tree_manifest(
            SQLiteWorkItemLedger(self.source_project_root, target_schema_version=7)
        )
        if canonical_sha256(current) != self.source_tree_manifest_digest:
            raise WorkItemGovernanceError(
                "PILOT_CONFORMANCE_SOURCE_LEDGER_CHANGED",
                "Protected Ledger bytes, file set, or metadata changed after snapshot creation.",
            )

    def public_evidence(self) -> dict[str, Any]:
        return {
            "schema_version": "wig_p3_pilot_conformance_ledger_snapshot.v1",
            "copy_method": "exclusive-maintenance-lock+O_RDONLY+O_NOFOLLOW+byte-copy",
            "source_sqlite_opened": False,
            "source_ledger_path_digest": self.source_ledger_path_digest,
            "source_tree_manifest_digest": self.source_tree_manifest_digest,
            "snapshot_input_digest": self.snapshot_input_digest,
            "snapshot_binding_digest": self.binding_digest,
        }


@contextmanager
def governed_pilot_conformance_ledger_snapshot(
    project_root: str | Path,
    *,
    snapshot_parent: str | Path,
) -> Iterator[PilotConformanceLedgerSnapshot]:
    """Copy a frozen protected Ledger into an isolated disposable SQLite project.

    No SQLite connection is ever given the source path. The source directory is
    measured before and after the entire context while an exclusive existing
    maintenance lock prevents repository-owned readers and writers. SQLite may
    materialize WAL coordination files only below the disposable snapshot root.
    """

    source_project = Path(project_root).expanduser().resolve()
    parent = Path(os.path.abspath(Path(snapshot_parent).expanduser()))
    if parent.resolve() != parent:
        raise WorkItemGovernanceError(
            "PILOT_CONFORMANCE_SNAPSHOT_PATH_INVALID",
            "Pilot conformance snapshot parent must not traverse symbolic links.",
        )
    parent_stat = parent.lstat()
    if (
        parent.is_symlink()
        or not stat.S_ISDIR(parent_stat.st_mode)
        or parent_stat.st_uid != os.getuid()
    ):
        raise WorkItemGovernanceError(
            "PILOT_CONFORMANCE_SNAPSHOT_PATH_INVALID",
            "Pilot conformance snapshot parent must be an owned real directory.",
        )
    ledger = SQLiteWorkItemLedger(source_project, target_schema_version=7)
    temporary = Path(tempfile.mkdtemp(prefix="colameta-pilot-ledger-snapshot-", dir=parent))
    os.chmod(temporary, 0o700)
    snapshot_project = temporary / "project"
    snapshot_colameta = snapshot_project / ".colameta"
    snapshot_ledger = snapshot_colameta / "ledger"
    try:
        _private_directory(snapshot_project)
        _private_directory(snapshot_colameta)
        _private_directory(snapshot_ledger)
        with ledger.frozen_storage_boundary():
            before = _ledger_tree_manifest(ledger)
            before_digest = canonical_sha256(before)
            copied = [_copy_readonly_source(ledger.path, snapshot_ledger / _MAIN_NAME)]
            source_wal = ledger.path.with_name(_WAL_NAME)
            if source_wal.is_file() and not source_wal.is_symlink():
                copied.append(_copy_readonly_source(source_wal, snapshot_ledger / _WAL_NAME))
            lock_fd = os.open(
                snapshot_ledger / _LOCK_NAME,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            os.close(lock_fd)
            snapshot_input_digest = canonical_sha256(copied)
            binding = {
                "source_project_root_path_digest": canonical_path_digest(source_project),
                "source_ledger_path_digest": canonical_path_digest(ledger.path),
                "source_tree_manifest_digest": before_digest,
                "snapshot_project_root_path_digest": canonical_path_digest(snapshot_project),
                "snapshot_input_digest": snapshot_input_digest,
            }
            snapshot = PilotConformanceLedgerSnapshot(
                source_project_root=source_project,
                project_root=snapshot_project,
                source_ledger_path_digest=binding["source_ledger_path_digest"],
                source_tree_manifest_digest=before_digest,
                snapshot_input_names=tuple(item["name"] for item in copied),
                snapshot_input_digest=snapshot_input_digest,
                binding_digest=canonical_sha256(binding),
                _authority=_SNAPSHOT_AUTHORITY,
            )
            after_copy = _ledger_tree_manifest(ledger)
            if after_copy != before:
                raise WorkItemGovernanceError(
                    "PILOT_CONFORMANCE_SOURCE_LEDGER_CHANGED",
                    "Protected Ledger changed while the isolated snapshot was copied.",
                )
            try:
                yield snapshot
                snapshot.require_bound_to(source_project)
            finally:
                after_use = _ledger_tree_manifest(ledger)
                if after_use != before:
                    raise WorkItemGovernanceError(
                        "PILOT_CONFORMANCE_SOURCE_LEDGER_CHANGED",
                        "Protected Ledger changed while the isolated snapshot was in use.",
                    )
    finally:
        if temporary.exists() and not temporary.is_symlink():
            shutil.rmtree(temporary)


__all__ = [
    "PilotConformanceLedgerSnapshot",
    "governed_pilot_conformance_ledger_snapshot",
]
