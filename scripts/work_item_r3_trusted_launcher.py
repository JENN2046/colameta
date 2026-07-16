from __future__ import annotations

"""Pre-import trust boundary for the R3 Closeout control program.

Execute this source file with ``python -I -S -B``.  It uses only the standard
library until the exact Git checkout and frozen virtual environment have been
measured.  Candidate modules and site-packages enter ``sys.path`` only after
that measurement succeeds.
"""

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess  # nosec B404 - exact root-owned /usr/bin/git below
import sys
from typing import Any


_EXPECTED_ENVIRONMENT_TREE_SHA256 = (
    "32663b4400cad650c4a1e7678795fb399e428330cf5d3e88b613269b59755d5d"
)
_SOURCE_ROOTS = frozenset({"runner", "adapters", "schemas", "scripts", "tests"})
_PROTECTED_PATHS = frozenset(
    {
        "AGENTS.md",
        "AGENTS - 副本.amd",
        "AGENTS - 副本.md:Zone.Identifier",
        "AGENTS.md:Zone.Identifier",
    }
)
_FORBIDDEN_STARTUP_PREFIXES = ("GIT_", "LD_", "DYLD_", "PYTHON")
_NON_EXECUTION_UNTRACKED_ROOTS = frozenset(
    {
        ".agents",
        ".codex",
        ".colameta",
        ".git",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "build",
        "colameta.egg-info",
        "dist",
        "docs",
    }
)
_PROTECTED_UNTRACKED = frozenset(
    {
        "AGENTS - 副本.amd",
        "AGENTS - 副本.md:Zone.Identifier",
        "AGENTS.md:Zone.Identifier",
    }
)
_IMPORT_OVERLAY_SUFFIXES = (
    ".py",
    ".pyc",
    ".pyo",
    ".so",
    ".pyd",
    ".dll",
    ".dylib",
    ".pth",
)
_EXECUTION_CONFIG_NAMES = frozenset(
    {
        ".coveragerc",
        ".pytest.ini",
        ".ruff.toml",
        "conftest.py",
        "pyproject.toml",
        "pytest.ini",
        "pytest.toml",
        "ruff.toml",
        "setup.cfg",
        "sitecustomize.py",
        "tox.ini",
        "usercustomize.py",
    }
)
_CAPABILITY_SEAL = object()
_LAUNCHER_RELATIVE_PATH = "scripts/work_item_r3_trusted_launcher.py"


class _TrustedBootstrapCapability:
    __slots__ = ("__record", "__seal", "__consumed")

    def __init__(self, record: dict[str, Any], *, _seal: object) -> None:
        if _seal is not _CAPABILITY_SEAL:
            raise TypeError("R3 bootstrap capabilities are launcher-owned.")
        self.__record = record
        self.__seal = _seal
        self.__consumed = False

    def consume(self) -> dict[str, Any]:
        if self.__seal is not _CAPABILITY_SEAL or self.__consumed:
            raise RuntimeError("R3 bootstrap capability is invalid or already consumed.")
        self.__consumed = True
        return json.loads(json.dumps(self.__record, sort_keys=True))


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _trusted_git_environment() -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(_FORBIDDEN_STARTUP_PREFIXES)
    }
    environment.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C",
        }
    )
    return environment


def _trusted_git() -> Path:
    candidate = Path("/usr/bin/git")
    resolved = candidate.resolve(strict=True)
    metadata = resolved.stat()
    if (
        resolved.parent.as_posix() not in {"/usr/bin", "/bin"}
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != 0
        or metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
        or not metadata.st_mode & stat.S_IXUSR
    ):
        raise RuntimeError("R3 bootstrap requires the trusted system Git executable.")
    return resolved


def _trusted_python_binding() -> dict[str, Any]:
    executable = Path(sys.executable).absolute()
    resolved = executable.resolve(strict=True)
    proc_executable = Path("/proc/self/exe").resolve(strict=True)
    metadata = resolved.stat()
    if (
        executable.as_posix() != "/usr/bin/python3.12"
        or resolved != proc_executable
        or resolved.parent.as_posix() not in {"/usr/bin", "/bin"}
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != 0
        or metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
        or not metadata.st_mode & stat.S_IXUSR
    ):
        raise RuntimeError(
            "R3 bootstrap requires exact root-owned /usr/bin/python3.12."
        )
    return {
        "requested_path": executable.as_posix(),
        "resolved_path": resolved.as_posix(),
        "proc_self_exe": proc_executable.as_posix(),
        "sha256": _sha256_file(resolved),
        "owner_uid": metadata.st_uid,
        "mode": f"{stat.S_IMODE(metadata.st_mode):04o}",
        "root_owned": True,
        "group_or_other_writable": False,
    }


def _git(root: Path, *arguments: str) -> bytes:
    completed = subprocess.run(
        [
            _trusted_git().as_posix(),
            "--no-pager",
            "--no-replace-objects",
            "--literal-pathspecs",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.untrackedCache=false",
            "-C",
            root.as_posix(),
            *arguments,
        ],
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_trusted_git_environment(),
        timeout=30,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "R3 bootstrap Git inspection failed: "
            + completed.stderr.decode("utf-8", errors="replace")[:300]
        )
    return completed.stdout


def _nul_records(payload: bytes) -> tuple[bytes, ...]:
    return tuple(item for item in payload.split(b"\0") if item)


def _git_blob(path: Path, *, algorithm: str) -> tuple[str, str]:
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode):
        data = os.readlink(path).encode("utf-8", errors="surrogateescape")
        mode = "120000"
    elif stat.S_ISREG(metadata.st_mode):
        data = path.read_bytes()
        mode = "100755" if metadata.st_mode & 0o111 else "100644"
    else:
        raise RuntimeError(f"R3 tracked source is not a regular file: {path}")
    digest = hashlib.new(algorithm)
    digest.update(f"blob {len(data)}\0".encode("ascii"))
    digest.update(data)
    return mode, digest.hexdigest()


def _measure_source_tree(root: Path) -> dict[str, Any]:
    observed_root = Path(
        _git(root, "rev-parse", "--show-toplevel").decode("utf-8").strip()
    ).resolve()
    if observed_root != root:
        raise RuntimeError("R3 bootstrap must run at the exact Git checkout root.")
    object_format = _git(root, "rev-parse", "--show-object-format").decode().strip()
    if object_format not in {"sha1", "sha256"}:
        raise RuntimeError("Unsupported Git object format.")

    tree: dict[str, tuple[str, str]] = {}
    for record in _nul_records(
        _git(root, "ls-tree", "-rz", "--full-tree", "HEAD", "--")
    ):
        metadata, separator, raw_name = record.partition(b"\t")
        fields = metadata.decode("ascii").split()
        if not separator or len(fields) != 3 or fields[1] != "blob":
            raise RuntimeError("Malformed R3 source tree inventory.")
        name = raw_name.decode("utf-8", errors="surrogateescape")
        if name in tree:
            raise RuntimeError("Duplicate R3 source tree entry.")
        if name not in _PROTECTED_PATHS:
            tree[name] = (fields[0], fields[2])

    index: dict[str, tuple[str, str]] = {}
    for record in _nul_records(
        _git(root, "ls-files", "--stage", "-z", "--")
    ):
        metadata, separator, raw_name = record.partition(b"\t")
        fields = metadata.decode("ascii").split()
        if not separator or len(fields) != 3 or fields[2] != "0":
            raise RuntimeError("Malformed or conflicted R3 source index.")
        name = raw_name.decode("utf-8", errors="surrogateescape")
        if name not in _PROTECTED_PATHS:
            index[name] = (fields[0], fields[1])
    if tree != index:
        raise RuntimeError("R3 source index differs from the exact HEAD tree.")

    flags = tuple(
        record
        for record in _nul_records(_git(root, "ls-files", "-v", "-z", "--"))
        if record[2:].decode("utf-8", errors="surrogateescape")
        not in _PROTECTED_PATHS
    )
    if any(
        len(record) < 3
        or record[1:2] != b" "
        or chr(record[0]).islower()
        or chr(record[0]).upper() == "S"
        for record in flags
    ):
        raise RuntimeError("R3 source index contains hidden path flags.")

    measured: dict[str, dict[str, str]] = {}
    for name, (expected_mode, expected_oid) in sorted(tree.items()):
        lowered = name.lower()
        if (
            expected_mode == "120000"
            or "__pycache__" in Path(name).parts
            or lowered.endswith(_IMPORT_OVERLAY_SUFFIXES[1:])
        ):
            raise RuntimeError(f"R3 tracked execution overlay is forbidden: {name}")
        mode, oid = _git_blob(root / name, algorithm=object_format)
        if mode != expected_mode or oid != expected_oid:
            raise RuntimeError(f"R3 source differs from HEAD: {name}")
        measured[name] = {"mode": mode, "blob_oid": oid}

    tracked = set(tree)
    overlays: list[str] = []
    for source_root in _SOURCE_ROOTS:
        base = root / source_root
        if not base.exists():
            raise RuntimeError(f"R3 source root is missing: {source_root}")
        for path in base.rglob("*"):
            if path.is_dir() and not path.is_symlink():
                continue
            relative = path.relative_to(root).as_posix()
            if relative not in tracked:
                overlays.append(relative)
    for name in ("sitecustomize.py", "usercustomize.py", "conftest.py"):
        candidate = root / name
        if candidate.exists() and name not in tracked:
            overlays.append(name)
    if overlays:
        raise RuntimeError(
            f"R3 source contains untracked execution overlays: {sorted(overlays)[:20]}"
        )

    ignored_and_untracked = set()
    for arguments in (
        ("ls-files", "--others", "--exclude-standard", "-z"),
        ("ls-files", "--others", "--ignored", "--exclude-standard", "-z"),
    ):
        ignored_and_untracked.update(
            item.decode("utf-8", errors="surrogateescape")
            for item in _nul_records(_git(root, *arguments))
        )
    root_overlays = []
    for name in sorted(ignored_and_untracked):
        if name in _PROTECTED_UNTRACKED:
            continue
        parts = Path(name).parts
        if not parts or parts[0] in _NON_EXECUTION_UNTRACKED_ROOTS:
            continue
        lowered = name.lower()
        if (
            parts[0] in _SOURCE_ROOTS
            or lowered.endswith(_IMPORT_OVERLAY_SUFFIXES)
            or Path(name).name in _EXECUTION_CONFIG_NAMES
        ):
            root_overlays.append(name)
    if root_overlays:
        raise RuntimeError(
            "R3 checkout contains an untracked import/startup overlay: "
            f"{root_overlays[:20]}"
        )

    launcher_entry = measured.get(_LAUNCHER_RELATIVE_PATH)
    if launcher_entry is None:
        raise RuntimeError("R3 trusted launcher is absent from the exact HEAD tree.")
    launcher_blob = _git(root, "show", f"HEAD:{_LAUNCHER_RELATIVE_PATH}")
    launcher_blob_sha256 = _sha256_bytes(launcher_blob)
    if launcher_blob_sha256 != _sha256_file(root / _LAUNCHER_RELATIVE_PATH):
        raise RuntimeError("R3 trusted launcher worktree bytes differ from its Git blob.")

    return {
        "commit": _git(root, "rev-parse", "HEAD").decode().strip(),
        "tree": _git(root, "rev-parse", "HEAD^{tree}").decode().strip(),
        "git_object_format": object_format,
        "tracked_path_count": len(measured),
        "tracked_manifest_sha256": _canonical_sha256(measured),
        "git_executable_sha256": _sha256_file(_trusted_git()),
        "launcher_blob_oid": launcher_entry["blob_oid"],
        "launcher_blob_sha256": launcher_blob_sha256,
    }


def _measure_environment_tree(venv: Path) -> dict[str, Any]:
    roots = (
        venv / "bin",
        venv / "lib" / "python3.12" / "site-packages",
        venv / "pyvenv.cfg",
    )
    entries: list[dict[str, Any]] = []
    for root in roots:
        candidates = root.rglob("*") if root.is_dir() else (root,)
        for path in candidates:
            metadata = path.lstat()
            if stat.S_ISDIR(metadata.st_mode) and not path.is_symlink():
                continue
            relative = path.relative_to(venv).as_posix()
            if path.is_symlink():
                entries.append(
                    {
                        "path": relative,
                        "kind": "symlink",
                        "mode": f"{stat.S_IMODE(metadata.st_mode):04o}",
                        "target": os.readlink(path),
                    }
                )
            elif stat.S_ISREG(metadata.st_mode):
                if path.suffix.lower() in {".pyc", ".pyo"}:
                    raise RuntimeError(
                        f"R3 toolchain contains pre-import bytecode: {relative}"
                    )
                entries.append(
                    {
                        "path": relative,
                        "kind": "regular",
                        "mode": f"{stat.S_IMODE(metadata.st_mode):04o}",
                        "size_bytes": metadata.st_size,
                        "sha256": _sha256_file(path),
                    }
                )
            else:
                raise RuntimeError(f"R3 toolchain contains a special entry: {relative}")
    entries.sort(key=lambda item: str(item["path"]).encode("utf-8"))
    return {
        "entry_count": len(entries),
        "environment_tree_sha256": _canonical_sha256(entries),
    }


def preimport_attestation(project_root: Path) -> dict[str, Any]:
    root = project_root.expanduser().resolve()
    forbidden_environment = sorted(
        key
        for key in os.environ
        if key.startswith(_FORBIDDEN_STARTUP_PREFIXES)
    )
    if forbidden_environment:
        raise RuntimeError(
            "R3 trusted launcher rejects inherited startup authority: "
            + ",".join(forbidden_environment)
        )
    if not (
        sys.flags.isolated
        and sys.flags.no_site
        and sys.flags.dont_write_bytecode
        and sys.flags.safe_path
    ):
        raise RuntimeError("R3 trusted launcher requires python -I -S -B.")
    venv = root / ".venv"
    python_binding = _trusted_python_binding()
    source = _measure_source_tree(root)
    environment = _measure_environment_tree(venv)
    if environment["environment_tree_sha256"] != _EXPECTED_ENVIRONMENT_TREE_SHA256:
        raise RuntimeError("R3 frozen verification environment differs before import.")
    record = {
        "schema_version": "work_item_r3_preimport_attestation.v1",
        "accepted": True,
        "project_root": root.as_posix(),
        "launcher_execution_source": "trusted_git_blob_stdin",
        "launcher_relative_path": _LAUNCHER_RELATIVE_PATH,
        "launcher_blob_oid": source["launcher_blob_oid"],
        "launcher_sha256": source["launcher_blob_sha256"],
        "python_executable": python_binding,
        "python_flags": {
            "isolated": True,
            "no_site": True,
            "dont_write_bytecode": True,
            "safe_path": True,
        },
        "startup_authority_environment": [],
        "source": source,
        "environment": environment,
    }
    record["attestation_sha256"] = _canonical_sha256(record)
    return record


def main() -> int:
    if sys.argv[0] != "-" or globals().get("__file__") != "<stdin>":
        raise RuntimeError(
            "R3 trusted launcher must be streamed from the exact Git blob over stdin."
        )
    if len(sys.argv) < 2:
        raise RuntimeError("R3 trusted launcher requires the exact checkout root argument.")
    project_root = Path(sys.argv.pop(1)).expanduser().resolve()
    attestation = preimport_attestation(project_root)
    venv = project_root / ".venv"
    site_packages = venv / "lib" / "python3.12" / "site-packages"
    sys.prefix = venv.as_posix()
    sys.exec_prefix = venv.as_posix()
    sys.path.insert(0, site_packages.as_posix())
    sys.path.insert(0, project_root.as_posix())

    import runpy

    capability = _TrustedBootstrapCapability(attestation, _seal=_CAPABILITY_SEAL)
    runpy.run_path(
        (project_root / "scripts" / "work_item_r3_closeout.py").as_posix(),
        run_name="__main__",
        init_globals={"_R3_TRUSTED_BOOTSTRAP_CAPABILITY": capability},
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(
            f"R3_TRUSTED_BOOTSTRAP_REJECTED: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        raise SystemExit(78) from exc
