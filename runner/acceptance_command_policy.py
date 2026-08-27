from __future__ import annotations

import os
import shlex
import stat
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator
from pathlib import Path


SHELL_META_PATTERNS = (
    "&&",
    "||",
    ";",
    "|",
    ">",
    "<",
    "`",
    "$(",
    "${",
    "\n",
    "\r",
)
_PYTHON_ALIASES = frozenset({"python", "python3"})
_FAIL_CLOSED_LAUNCHERS = frozenset(
    {
        "pytest",
        "tox",
        "nox",
        "ruff",
        "mypy",
        "pyright",
        "node",
        "npm",
        "npx",
        "pnpm",
        "yarn",
        "uv",
        "make",
        "go",
        "cargo",
    }
)
_PYTHON_ISOLATION_FLAGS = ("-I", "-P", "-s", "-E")
_GIT_ISOLATION_ARGS = (
    "-c",
    "core.fsmonitor=false",
    "-c",
    "core.hooksPath=/dev/null",
)
_INDEPENDENT_TRUSTED_OWNER_ID = 0
_DISALLOWED_TEMP_ROOTS = tuple(
    dict.fromkeys(
        os.path.realpath(path)
        for path in ("/tmp", tempfile.gettempdir())
        if os.path.isabs(path)
    )
)


class AcceptanceCommandPolicyError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True)
class TrustedPathIdentity:
    path: str
    device: int
    inode: int
    owner: int
    group: int
    mode: int
    size: int
    modified_ns: int
    kind: str


@dataclass(frozen=True)
class AcceptanceExecutionPlan:
    argv: tuple[str, ...]
    project_root: str
    executable: TrustedPathIdentity


@dataclass(frozen=True)
class OpenedAcceptanceExecutable:
    fd: int
    proc_path: str
    argv: tuple[str, ...]
    pass_fds: tuple[int, ...]


def _is_within(path: str, root: str) -> bool:
    try:
        return os.path.commonpath((path, root)) == root
    except ValueError:
        return False


def canonical_acceptance_project_root(project_root: str) -> str:
    if not isinstance(project_root, str) or not project_root.strip():
        raise AcceptanceCommandPolicyError(
            "ACCEPTANCE_PROJECT_ROOT_REQUIRED",
            "A canonical project root is required for acceptance execution.",
        )
    candidate = os.path.realpath(os.path.abspath(project_root))
    try:
        root_stat = os.stat(candidate)
    except OSError as exc:
        raise AcceptanceCommandPolicyError(
            "ACCEPTANCE_PROJECT_ROOT_INVALID",
            "The acceptance project root is unavailable.",
        ) from exc
    if not stat.S_ISDIR(root_stat.st_mode):
        raise AcceptanceCommandPolicyError(
            "ACCEPTANCE_PROJECT_ROOT_INVALID",
            "The acceptance project root is not a directory.",
        )
    return candidate


def _path_components(path: str) -> list[str]:
    path = os.path.abspath(path)
    parts = Path(path).parts
    current = parts[0]
    components = [current]
    for part in parts[1:]:
        current = os.path.join(current, part)
        components.append(current)
    return components


def _disallowed_location_code(path: str, project_root: str) -> str | None:
    if _is_within(path, project_root):
        return "ACCEPTANCE_RUNTIME_INTERPRETER_IN_PROJECT"
    if any(_is_within(path, root) for root in _DISALLOWED_TEMP_ROOTS):
        return "ACCEPTANCE_EXECUTABLE_IN_TEMP_ROOT"
    return None


def _trusted_path_identity(
    path: str,
    *,
    project_root: str,
    kind: str,
    executable: bool = False,
) -> TrustedPathIdentity:
    if not os.path.isabs(path) or os.path.normpath(path) != path:
        raise AcceptanceCommandPolicyError(
            "ACCEPTANCE_COMMAND_EXECUTABLE_PATH_NOT_TRUSTED",
            "Executable paths must be canonical absolute paths.",
        )
    location_code = _disallowed_location_code(path, project_root)
    if location_code:
        message = (
            "The runtime interpreter must be outside the target project."
            if location_code == "ACCEPTANCE_RUNTIME_INTERPRETER_IN_PROJECT"
            else "Acceptance executables cannot run from a temporary root."
        )
        raise AcceptanceCommandPolicyError(location_code, message)

    final_stat: os.stat_result | None = None
    for component in _path_components(path):
        try:
            component_stat = os.lstat(component)
        except OSError as exc:
            raise AcceptanceCommandPolicyError(
                "ACCEPTANCE_COMMAND_EXECUTABLE_NOT_AVAILABLE",
                "The trusted acceptance launcher is unavailable.",
            ) from exc
        if stat.S_ISLNK(component_stat.st_mode):
            raise AcceptanceCommandPolicyError(
                "ACCEPTANCE_COMMAND_EXECUTABLE_SYMLINK",
                "Symlink components are not allowed in trusted acceptance launchers.",
            )
        if component_stat.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise AcceptanceCommandPolicyError(
                "ACCEPTANCE_COMMAND_EXECUTABLE_MODE_NOT_TRUSTED",
                "The acceptance runtime or module chain is group/world writable.",
            )
        if component_stat.st_uid != _INDEPENDENT_TRUSTED_OWNER_ID:
            raise AcceptanceCommandPolicyError(
                "ACCEPTANCE_COMMAND_EXECUTABLE_OWNER_NOT_TRUSTED",
                "The acceptance runtime or module chain is not independently owned.",
            )
        final_stat = component_stat

    assert final_stat is not None
    expected_kind = (
        stat.S_ISDIR(final_stat.st_mode)
        if kind == "directory"
        else stat.S_ISREG(final_stat.st_mode)
    )
    if not expected_kind or (executable and not final_stat.st_mode & 0o111):
        raise AcceptanceCommandPolicyError(
            "ACCEPTANCE_COMMAND_EXECUTABLE_NOT_TRUSTED",
            "The trusted acceptance launcher has an invalid file type or mode.",
        )
    return TrustedPathIdentity(
        path=path,
        device=final_stat.st_dev,
        inode=final_stat.st_ino,
        owner=final_stat.st_uid,
        group=final_stat.st_gid,
        mode=final_stat.st_mode,
        size=final_stat.st_size,
        modified_ns=final_stat.st_mtime_ns,
        kind=kind,
    )


def _identity_matches(identity: TrustedPathIdentity, project_root: str) -> bool:
    try:
        current = _trusted_path_identity(
            identity.path,
            project_root=project_root,
            kind=identity.kind,
            executable=identity.kind == "executable",
        )
    except AcceptanceCommandPolicyError:
        return False
    return current == identity


def _trusted_system_directory(path: str) -> bool:
    if not os.path.isabs(path) or os.path.realpath(path) != path:
        return False
    try:
        path_stat = os.lstat(path)
    except OSError:
        return False
    return (
        stat.S_ISDIR(path_stat.st_mode)
        and path_stat.st_uid == _INDEPENDENT_TRUSTED_OWNER_ID
        and not path_stat.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
    )


_TRUSTED_SYSTEM_EXECUTABLE_DIRS = tuple(
    path
    for path in ("/usr/local/bin", "/usr/bin", "/bin")
    if _trusted_system_directory(path)
)
TRUSTED_ACCEPTANCE_PATH = os.pathsep.join(_TRUSTED_SYSTEM_EXECUTABLE_DIRS)


def _validate_python_grammar(args: list[str]) -> None:
    if args in (["--version"], ["-V"]):
        return
    if len(args) >= 2 and args[0] == "-m":
        raise AcceptanceCommandPolicyError(
            "ACCEPTANCE_COMMAND_PYTHON_MODULE_NOT_ALLOWED",
            "Python module execution is not approved for acceptance execution.",
        )
    raise AcceptanceCommandPolicyError(
        "ACCEPTANCE_COMMAND_PYTHON_GRAMMAR_NOT_ALLOWED",
        "Python arguments do not match an approved acceptance grammar.",
    )


def _validate_git_grammar(args: list[str]) -> None:
    if args == ["--version"]:
        return
    if args == ["diff", "--check"]:
        return
    if args in (
        ["status", "--short", "--branch"],
        ["status", "-sb"],
        ["status", "--porcelain=v1", "--untracked-files=all"],
    ):
        return
    raise AcceptanceCommandPolicyError(
        "ACCEPTANCE_COMMAND_GIT_GRAMMAR_NOT_ALLOWED",
        "Git arguments do not match an approved read-only acceptance grammar.",
    )


def _validate_launcher_grammar(argv: list[str], executable: str) -> None:
    if executable in _PYTHON_ALIASES or os.path.isabs(executable):
        _validate_python_grammar(argv[1:])
        return
    if executable == "git":
        _validate_git_grammar(argv[1:])
        return
    if executable in _FAIL_CLOSED_LAUNCHERS:
        raise AcceptanceCommandPolicyError(
            "ACCEPTANCE_COMMAND_TOOLCHAIN_UNPROVEN",
            "The launcher resolves an unpinned secondary toolchain and is not executable.",
        )
    raise AcceptanceCommandPolicyError(
        "ACCEPTANCE_COMMAND_EXECUTABLE_NOT_ALLOWED",
        "Executable is not allowed for acceptance commands.",
    )


def acceptance_command_to_argv(
    command: str,
    *,
    project_root: str | None = None,
) -> list[str]:
    """Parse one shell-free command; execution performs stricter binding."""

    if not isinstance(command, str) or not command.strip():
        raise AcceptanceCommandPolicyError(
            "ACCEPTANCE_COMMAND_EMPTY",
            "Command must be a non-empty string.",
        )
    if any(pattern in command for pattern in SHELL_META_PATTERNS):
        raise AcceptanceCommandPolicyError(
            "ACCEPTANCE_COMMAND_SHELL_OPERATOR",
            "Shell operators are not allowed in acceptance commands.",
        )
    try:
        argv = shlex.split(command, posix=True)
    except ValueError as exc:
        raise AcceptanceCommandPolicyError(
            "ACCEPTANCE_COMMAND_PARSE_FAILED",
            "Acceptance command parsing failed.",
        ) from exc
    if not argv:
        raise AcceptanceCommandPolicyError(
            "ACCEPTANCE_COMMAND_EMPTY_ARGV",
            "Command must contain an executable.",
        )
    executable_token = argv[0]
    has_path_separator = os.sep in executable_token or bool(
        os.altsep and os.altsep in executable_token
    )
    if has_path_separator:
        runtime_candidates = _runtime_interpreter_candidates()
        runtime_token = os.path.realpath(os.path.abspath(executable_token))
        if not (
            os.path.isabs(executable_token)
            and os.path.realpath(executable_token) == executable_token
            and runtime_token in runtime_candidates
        ):
            raise AcceptanceCommandPolicyError(
                "ACCEPTANCE_COMMAND_EXECUTABLE_PATH_NOT_TRUSTED",
                "Executable paths are not trusted for acceptance commands.",
            )
        if project_root is not None:
            root = canonical_acceptance_project_root(project_root)
            location_code = _disallowed_location_code(runtime_token, root)
            if location_code:
                raise AcceptanceCommandPolicyError(
                    location_code,
                    "The runtime interpreter is not isolated from the target project.",
                )
        _validate_launcher_grammar(argv, executable_token)
        return argv

    _validate_launcher_grammar(argv, executable_token)
    return argv


def _runtime_interpreter_candidates() -> tuple[str, ...]:
    candidates: list[str] = []
    for value in (getattr(sys, "_base_executable", None), sys.executable):
        if not isinstance(value, str) or not value:
            continue
        candidate = os.path.realpath(os.path.abspath(value))
        if candidate not in candidates:
            candidates.append(candidate)
    return tuple(candidates)


def _runtime_interpreter_identity(
    project_root: str,
    *,
    requested_path: str | None = None,
) -> TrustedPathIdentity:
    candidates = (
        (os.path.realpath(os.path.abspath(requested_path)),)
        if requested_path is not None
        else _runtime_interpreter_candidates()
    )
    last_error: AcceptanceCommandPolicyError | None = None
    for runtime in candidates:
        try:
            return _trusted_path_identity(
                runtime,
                project_root=project_root,
                kind="executable",
                executable=True,
            )
        except AcceptanceCommandPolicyError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    raise AcceptanceCommandPolicyError(
        "ACCEPTANCE_RUNTIME_INTERPRETER_NOT_TRUSTED",
        "No independently trusted Python runtime is available.",
    )


def _resolve_system_executable(
    executable: str,
    project_root: str,
) -> TrustedPathIdentity:
    for directory in _TRUSTED_SYSTEM_EXECUTABLE_DIRS:
        candidate = os.path.join(directory, executable)
        if not os.path.lexists(candidate):
            continue
        try:
            return _trusted_path_identity(
                candidate,
                project_root=project_root,
                kind="executable",
                executable=True,
            )
        except AcceptanceCommandPolicyError:
            continue
    raise AcceptanceCommandPolicyError(
        "ACCEPTANCE_COMMAND_EXECUTABLE_NOT_AVAILABLE",
        "Allowed executable is unavailable in the trusted acceptance path.",
    )


def _git_execution_argv(executable: str, args: list[str]) -> list[str]:
    if args[:2] == ["diff", "--check"]:
        return [
            executable,
            *_GIT_ISOLATION_ARGS,
            "diff",
            "--no-ext-diff",
            "--no-textconv",
            "--check",
            *args[2:],
        ]
    return [executable, *_GIT_ISOLATION_ARGS, *args]


def acceptance_command_to_execution_plan(
    command: str,
    *,
    project_root: str,
) -> AcceptanceExecutionPlan:
    """Bind a command to trusted paths and immutable pre-exec identities."""

    root = canonical_acceptance_project_root(project_root)
    argv = acceptance_command_to_argv(command, project_root=root)
    executable = argv[0]

    if os.path.isabs(executable) or executable in _PYTHON_ALIASES:
        interpreter = _runtime_interpreter_identity(
            root,
            requested_path=executable if os.path.isabs(executable) else None,
        )
        args = argv[1:]
        resolved_argv = [interpreter.path, *_PYTHON_ISOLATION_FLAGS, *args]
        return AcceptanceExecutionPlan(
            argv=tuple(resolved_argv),
            project_root=root,
            executable=interpreter,
        )

    system_identity = _resolve_system_executable(executable, root)
    return AcceptanceExecutionPlan(
        argv=tuple(_git_execution_argv(system_identity.path, argv[1:])),
        project_root=root,
        executable=system_identity,
    )


def verify_acceptance_execution_plan(plan: AcceptanceExecutionPlan) -> None:
    """Fail closed if any trusted launcher identity changed before exec."""

    if not _identity_matches(plan.executable, plan.project_root):
        raise AcceptanceCommandPolicyError(
            "ACCEPTANCE_COMMAND_EXECUTABLE_IDENTITY_CHANGED",
            "The trusted acceptance launcher changed before execution.",
        )


def _identity_matches_stat(
    identity: TrustedPathIdentity,
    current: os.stat_result,
) -> bool:
    return (
        identity.device == current.st_dev
        and identity.inode == current.st_ino
        and identity.owner == current.st_uid
        and identity.group == current.st_gid
        and identity.mode == current.st_mode
        and identity.size == current.st_size
        and identity.modified_ns == current.st_mtime_ns
    )


@contextmanager
def open_acceptance_executable(
    plan: AcceptanceExecutionPlan,
) -> Iterator[OpenedAcceptanceExecutable]:
    """Pin the verified executable and expose only its inherited proc-fd path."""

    proc_fd_root = "/proc/self/fd"
    if os.name != "posix" or not os.path.isdir(proc_fd_root):
        raise AcceptanceCommandPolicyError(
            "ACCEPTANCE_FD_EXECUTION_UNAVAILABLE",
            "Descriptor-bound acceptance execution is unavailable on this platform.",
        )
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    if not hasattr(os, "O_NOFOLLOW"):
        raise AcceptanceCommandPolicyError(
            "ACCEPTANCE_FD_EXECUTION_UNAVAILABLE",
            "Descriptor-bound acceptance execution requires no-follow open support.",
        )
    flags |= os.O_NOFOLLOW
    opened_fd: int | None = None
    try:
        try:
            opened_fd = os.open(plan.executable.path, flags)
        except OSError as exc:
            raise AcceptanceCommandPolicyError(
                "ACCEPTANCE_COMMAND_EXECUTABLE_OPEN_FAILED",
                "The trusted acceptance executable could not be pinned.",
            ) from exc
        if not _identity_matches_stat(plan.executable, os.fstat(opened_fd)):
            raise AcceptanceCommandPolicyError(
                "ACCEPTANCE_COMMAND_EXECUTABLE_IDENTITY_CHANGED",
                "The trusted acceptance executable changed before execution.",
            )

        yield OpenedAcceptanceExecutable(
            fd=opened_fd,
            proc_path=f"{proc_fd_root}/{opened_fd}",
            argv=plan.argv,
            pass_fds=(opened_fd,),
        )
    finally:
        if opened_fd is not None:
            os.close(opened_fd)


def acceptance_command_to_execution_argv(
    command: str,
    *,
    project_root: str,
) -> list[str]:
    """Compatibility projection for callers that only need resolved argv."""

    return list(
        acceptance_command_to_execution_plan(
            command,
            project_root=project_root,
        ).argv
    )


def trusted_acceptance_environment(
    env: dict[str, str] | None = None,
) -> dict[str, str]:
    """Return a fixed minimal environment; caller values are never inherited."""

    del env
    return {
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "NO_COLOR": "1",
        "PATH": TRUSTED_ACCEPTANCE_PATH,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_PAGER": "cat",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_COUNT": "2",
        "GIT_CONFIG_KEY_0": "core.fsmonitor",
        "GIT_CONFIG_VALUE_0": "false",
        "GIT_CONFIG_KEY_1": "core.hooksPath",
        "GIT_CONFIG_VALUE_1": os.devnull,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTHONSAFEPATH": "1",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
    }


def acceptance_command_rejection_code(
    command: str,
    *,
    project_root: str | None = None,
) -> str | None:
    try:
        if project_root is None:
            acceptance_command_to_argv(command)
        else:
            acceptance_command_to_execution_plan(
                command,
                project_root=project_root,
            )
    except AcceptanceCommandPolicyError as exc:
        return exc.code
    return None
