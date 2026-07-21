from __future__ import annotations

import errno
import os
import stat
from types import TracebackType
from typing import Any

try:
    import fcntl
except ImportError:  # pragma: no cover - this module deliberately fails closed off POSIX
    fcntl = None  # type: ignore[assignment]


# Retained as a compatibility label for receipts/tests.  The lease itself is
# held on the already-existing project-root directory descriptor so read-only
# snapshots never create a lock file or runtime directory.
LOCK_FILE_NAME = "project-operation.lock"
LEASE_ACQUIRED = "acquired"
LEASE_BUSY = "busy"
LEASE_UNAVAILABLE = "unavailable"
LEASE_RELEASED = "released"
LEASE_NEW = "new"

PROJECT_OPERATION_BUSY = "PROJECT_OPERATION_BUSY"
PROJECT_OPERATION_LEASE_UNAVAILABLE = "PROJECT_OPERATION_LEASE_UNAVAILABLE"


class ProjectOperationLeaseError(RuntimeError):
    """Raised when a lease used as a context manager cannot be acquired."""

    def __init__(self, status: str, error_code: str) -> None:
        super().__init__(error_code)
        self.status = status
        self.error_code = error_code


class ProjectOperationLease:
    """A non-blocking, project-scoped POSIX advisory lease.

    Exclusive leases protect project mutations. Shared leases allow concurrent
    snapshot readers while excluding mutations. The open file description is
    the authority: no PID, heartbeat, or sidecar state is used to infer
    ownership.
    """

    def __init__(
        self,
        project_root: str | os.PathLike[str],
        *,
        shared: bool = False,
        operation_kind: str = "project_operation",
        surface: str = "internal",
    ) -> None:
        self.shared = bool(shared)
        self.operation_kind = str(operation_kind or "project_operation")
        self.surface = str(surface or "internal")
        self.status = LEASE_NEW
        self.error_code = ""
        self._fd: int | None = None
        try:
            raw_root = os.fspath(project_root)
            if not raw_root:
                raise ValueError("project root is empty")
            self.canonical_project_root: str | None = os.path.realpath(
                os.path.abspath(os.path.expanduser(raw_root))
            )
        except (TypeError, ValueError, OSError):
            self.canonical_project_root = None
            self.status = LEASE_UNAVAILABLE
            self.error_code = PROJECT_OPERATION_LEASE_UNAVAILABLE

    @property
    def held(self) -> bool:
        return self.status == LEASE_ACQUIRED and self._fd is not None

    def __bool__(self) -> bool:
        return self.held

    def acquire(self) -> ProjectOperationLease:
        """Try to acquire immediately and return this status-bearing object."""

        if self.held:
            return self
        if self.canonical_project_root is None:
            return self._unavailable()
        if os.name != "posix" or fcntl is None:
            return self._unavailable()
        required_flags = ("O_DIRECTORY", "O_NOFOLLOW")
        if any(not hasattr(os, flag) for flag in required_flags):
            return self._unavailable()

        root_fd: int | None = None
        lock_held = False
        try:
            directory_flags = (
                os.O_RDONLY
                | os.O_DIRECTORY
                | os.O_NOFOLLOW
                | getattr(os, "O_CLOEXEC", 0)
            )
            root_fd = os.open(self.canonical_project_root, directory_flags)
            os.set_inheritable(root_fd, False)
            descriptor_stat = os.fstat(root_fd)
            if not stat.S_ISDIR(descriptor_stat.st_mode):
                return self._unavailable()
            if hasattr(os, "geteuid") and descriptor_stat.st_uid != os.geteuid():
                return self._unavailable()
            if stat.S_IMODE(descriptor_stat.st_mode) & 0o022:
                return self._unavailable()

            operation = fcntl.LOCK_SH if self.shared else fcntl.LOCK_EX
            try:
                fcntl.flock(root_fd, operation | fcntl.LOCK_NB)
                lock_held = True
            except OSError as exc:
                if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK):
                    os.close(root_fd)
                    root_fd = None
                    self.status = LEASE_BUSY
                    self.error_code = PROJECT_OPERATION_BUSY
                    return self
                raise

            self._fd = root_fd
            root_fd = None
            lock_held = False
            self.status = LEASE_ACQUIRED
            self.error_code = ""
            return self
        except (OSError, ValueError):
            if lock_held and root_fd is not None:
                try:
                    fcntl.flock(root_fd, fcntl.LOCK_UN)
                except OSError:
                    pass
            return self._unavailable()
        finally:
            if root_fd is not None:
                try:
                    os.close(root_fd)
                except OSError:
                    pass

    def _unavailable(self) -> ProjectOperationLease:
        self.status = LEASE_UNAVAILABLE
        self.error_code = PROJECT_OPERATION_LEASE_UNAVAILABLE
        self._fd = None
        return self

    def release(self) -> None:
        descriptor = self._fd
        self._fd = None
        if descriptor is None:
            return
        close_succeeded = False
        try:
            if fcntl is not None:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                except OSError:
                    pass
        finally:
            try:
                os.close(descriptor)
                close_succeeded = True
            except OSError:
                pass
            self.status = LEASE_RELEASED if close_succeeded else LEASE_UNAVAILABLE
            self.error_code = "" if close_succeeded else PROJECT_OPERATION_LEASE_UNAVAILABLE

    def public_status(self) -> dict[str, Any]:
        """Return a bounded projection that carries no project or owner data."""

        return {
            "status": self.status,
            "held": self.held,
            "shared": self.shared,
            "error_code": self.error_code or None,
        }

    def __enter__(self) -> ProjectOperationLease:
        self.acquire()
        if not self.held:
            raise ProjectOperationLeaseError(self.status, self.error_code)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.release()

    def __del__(self) -> None:
        try:
            self.release()
        except Exception:
            pass


def probe_project_operation_lease(project_root: str | os.PathLike[str]) -> dict[str, Any]:
    """Point-in-time public probe; callers must still acquire before writing."""

    lease = ProjectOperationLease(project_root, operation_kind="probe", surface="probe").acquire()
    if lease.held:
        lease.release()
        return {
            "status": "free",
            "held": False,
            "shared": False,
            "error_code": None,
        }
    return lease.public_status()
