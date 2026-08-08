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
_BINDING_RECEIPT_ENV = "COLAMETA_TRUSTED_LAUNCHER_BINDING_FILE"
_BINDING_RECEIPT_NAME = "trusted-launcher-binding.json"
_BINDING_SCHEMA = "colameta.trusted_launcher_binding.v1"
_HOST_FROZEN_LANE = "host_frozen"
_TRUSTED_FROZEN_ASSET = {
    "distribution": "cryptography",
    "version": "50.0.0",
    "filename": "cryptography-50.0.0-cp39-abi3-manylinux_2_34_x86_64.whl",
    "size": 4762400,
    "sha256": "37fdb0d0111f1e2ff07139dfb79f1b49531f8e213c46f1163dd7642979b58c47",
}
_TRUSTED_FROZEN_RECORD_SHA256 = (
    "c9ba12106b90e31d3000f1de8f41f3587fc4fbbb56a712fdf44ee482ef6570af"
)


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


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON value is forbidden: {value}")


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def _is_git_object_id(value: Any) -> bool:
    return isinstance(value, str) and len(value) in {40, 64} and all(
        character in "0123456789abcdef" for character in value
    )


def _is_contained(path: Path, root: Path) -> bool:
    try:
        return os.path.commonpath([str(path), str(root)]) == str(root)
    except ValueError:
        return False


def _read_regular_bytes(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("trusted launcher binding requires a regular file")
    flags = os.O_RDONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise RuntimeError("trusted launcher binding requires a regular file")
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = -1
            return handle.read()
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _load_binding_receipt(root: Path) -> dict[str, Any] | None:
    """Load and validate the preview-bound receipt, if this is a governed run."""

    raw_path = os.environ.get(_BINDING_RECEIPT_ENV)
    if not raw_path:
        return None
    path = Path(raw_path).expanduser()
    if not path.is_absolute() or path.is_symlink():
        raise RuntimeError("trusted launcher binding receipt path is unsafe")
    try:
        resolved_path = path.resolve(strict=True)
    except OSError as exc:
        raise RuntimeError("trusted launcher binding receipt is unavailable") from exc
    expected_parent = root.resolve().parent
    if (
        resolved_path.name != _BINDING_RECEIPT_NAME
        or resolved_path.parent != expected_parent
        or not _is_contained(resolved_path, expected_parent)
    ):
        raise RuntimeError("trusted launcher binding receipt path escaped its run")
    try:
        raw = _read_regular_bytes(resolved_path)
        receipt = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_reject_json_constant,
        )
    except (OSError, UnicodeDecodeError, ValueError, TypeError) as exc:
        raise RuntimeError("trusted launcher binding receipt is invalid") from exc
    if not isinstance(receipt, dict):
        raise RuntimeError("trusted launcher binding receipt is invalid")

    required_top_level = {
        "schema_version",
        "candidate",
        "toolchain",
        "launcher",
        "validation",
        "receipt_sha256",
    }
    if set(receipt) != required_top_level:
        raise RuntimeError("trusted launcher binding receipt schema is invalid")
    if receipt.get("schema_version") != _BINDING_SCHEMA:
        raise RuntimeError("trusted launcher binding receipt schema is invalid")
    receipt_digest = receipt.get("receipt_sha256")
    unsigned = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    if not _is_sha256(receipt_digest) or _canonical_sha256(unsigned) != receipt_digest:
        raise RuntimeError("trusted launcher binding receipt digest mismatch")

    candidate = receipt.get("candidate")
    toolchain = receipt.get("toolchain")
    launcher = receipt.get("launcher")
    validation = receipt.get("validation")
    if not all(isinstance(item, dict) for item in (candidate, toolchain, launcher, validation)):
        raise RuntimeError("trusted launcher binding receipt schema is invalid")
    assert isinstance(candidate, dict)
    assert isinstance(toolchain, dict)
    assert isinstance(launcher, dict)
    assert isinstance(validation, dict)
    if set(candidate) != {
        "head",
        "root",
        "worktree_delta_sha256",
        "source_binding_sha256",
        "source_binding_count",
        "source_binding_scope",
        "source_bindings",
    }:
        raise RuntimeError("trusted launcher candidate binding schema is invalid")
    if set(toolchain) != {
        "project_root",
        "environment_root",
        "environment_root_sha256",
        "frozen_record_sha256",
        "cryptography_version",
    } and set(toolchain) != {
        "project_root",
        "environment_root",
        "environment_root_sha256",
        "frozen_record_sha256",
        "cryptography_version",
        "frozen_asset",
    }:
        raise RuntimeError("trusted launcher toolchain binding schema is invalid")
    if set(launcher) != {"path", "sha256"}:
        raise RuntimeError("trusted launcher self binding schema is invalid")
    if set(validation) != {"preview_id", "command_specs_sha256", "lane"}:
        raise RuntimeError("trusted launcher validation binding schema is invalid")

    if not _is_git_object_id(candidate.get("head")):
        raise RuntimeError("trusted launcher candidate HEAD binding is invalid")
    candidate_root = Path(str(candidate.get("root"))).expanduser()
    if not candidate_root.is_absolute() or candidate_root.resolve() != root.resolve():
        raise RuntimeError("trusted launcher candidate root binding mismatch")
    bindings = candidate.get("source_bindings")
    if not isinstance(bindings, list):
        raise RuntimeError("trusted launcher source bindings are invalid")
    previous_path = None
    for binding in bindings:
        if not isinstance(binding, dict) or set(binding) != {"path", "present", "sha256"}:
            raise RuntimeError("trusted launcher source binding is invalid")
        relative = binding.get("path")
        if not isinstance(relative, str) or not relative or "\\" in relative:
            raise RuntimeError("trusted launcher source binding path is invalid")
        parts = tuple(relative.split("/"))
        if relative.startswith("/") or any(part in {"", ".", ".."} for part in parts):
            raise RuntimeError("trusted launcher source binding path escaped checkout")
        if previous_path is not None and relative <= previous_path:
            raise RuntimeError("trusted launcher source bindings are not canonical")
        previous_path = relative
        if not isinstance(binding.get("present"), bool):
            raise RuntimeError("trusted launcher source binding presence is invalid")
        if binding["present"]:
            if not _is_sha256(binding.get("sha256")):
                raise RuntimeError("trusted launcher source binding digest is invalid")
        elif binding.get("sha256") is not None:
            raise RuntimeError("deleted source binding must not have a digest")
    if (
        candidate.get("source_binding_scope") != "full_allowed_worktree_delta"
        or candidate.get("source_binding_count") != len(bindings)
        or not _is_sha256(candidate.get("source_binding_sha256"))
        or candidate.get("source_binding_sha256") != _canonical_sha256(bindings)
        or candidate.get("worktree_delta_sha256") != candidate.get("source_binding_sha256")
    ):
        raise RuntimeError("trusted launcher candidate digest binding mismatch")

    for key in ("project_root", "environment_root"):
        value = toolchain.get(key)
        path_value = Path(str(value)).expanduser()
        if not path_value.is_absolute() or path_value.is_symlink():
            raise RuntimeError("trusted launcher toolchain path binding is unsafe")
    toolchain_project = Path(str(toolchain["project_root"])).resolve(strict=True)
    toolchain_environment = Path(str(toolchain["environment_root"])).resolve(strict=True)
    if (
        toolchain_environment != toolchain_project / ".venv"
        or not toolchain_environment.is_dir()
        or not (toolchain_environment / "pyvenv.cfg").is_file()
        or not _is_sha256(toolchain.get("environment_root_sha256"))
        or not _is_sha256(toolchain.get("frozen_record_sha256"))
        or toolchain.get("cryptography_version") != "50.0.0"
    ):
        raise RuntimeError("trusted launcher toolchain binding is invalid")
    if launcher.get("path") != _LAUNCHER_RELATIVE_PATH or not _is_sha256(launcher.get("sha256")):
        raise RuntimeError("trusted launcher self binding is invalid")
    if (
        not isinstance(validation.get("preview_id"), str)
        or not validation["preview_id"]
        or not _is_sha256(validation.get("command_specs_sha256"))
        or validation.get("lane") != _HOST_FROZEN_LANE
    ):
        raise RuntimeError("trusted launcher validation binding is invalid")
    frozen_asset = toolchain.get("frozen_asset")
    if frozen_asset is not None:
        if not isinstance(frozen_asset, dict) or set(frozen_asset) != {
            "path",
            "distribution",
            "version",
            "filename",
            "size",
            "sha256",
        }:
            raise RuntimeError("trusted launcher frozen asset binding is invalid")
        if (
            not isinstance(frozen_asset.get("path"), str)
            or not frozen_asset["path"]
            or not isinstance(frozen_asset.get("size"), int)
            or isinstance(frozen_asset.get("size"), bool)
            or not _is_sha256(frozen_asset.get("sha256"))
            or not all(
                isinstance(frozen_asset.get(key), str) and frozen_asset[key]
                for key in ("distribution", "version", "filename")
            )
        ):
            raise RuntimeError("trusted launcher frozen asset binding is invalid")
    return receipt


def _verify_bound_frozen_asset(root: Path, receipt: dict[str, Any]) -> dict[str, Any]:
    """Verify the host-frozen wheel before any Candidate import is possible."""

    toolchain = receipt.get("toolchain")
    asset = toolchain.get("frozen_asset") if isinstance(toolchain, dict) else None
    if not isinstance(asset, dict):
        raise RuntimeError("trusted launcher frozen asset binding is unavailable")
    if (
        asset.get("distribution") != _TRUSTED_FROZEN_ASSET["distribution"]
        or asset.get("version") != _TRUSTED_FROZEN_ASSET["version"]
        or asset.get("filename") != _TRUSTED_FROZEN_ASSET["filename"]
        or asset.get("size") != _TRUSTED_FROZEN_ASSET["size"]
        or asset.get("sha256") != _TRUSTED_FROZEN_ASSET["sha256"]
        or toolchain.get("frozen_record_sha256") != _TRUSTED_FROZEN_RECORD_SHA256
    ):
        raise RuntimeError("trusted launcher frozen asset identity mismatch")
    path = Path(str(asset["path"])).expanduser()
    if not path.is_absolute() or path.is_symlink():
        raise RuntimeError("trusted launcher frozen asset path is unsafe")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise RuntimeError("trusted launcher frozen asset is unavailable") from exc
    project_root = Path(str(toolchain["project_root"])).expanduser().resolve(strict=True)
    environment_root = Path(str(toolchain["environment_root"])).expanduser().resolve(strict=True)
    for protected in (root.resolve(), project_root, environment_root):
        if _is_contained(resolved, protected) or _is_contained(protected, resolved):
            raise RuntimeError("trusted launcher frozen asset path overlaps protected root")
    if resolved.name != _TRUSTED_FROZEN_ASSET["filename"]:
        raise RuntimeError("trusted launcher frozen asset filename mismatch")
    metadata = resolved.stat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size != _TRUSTED_FROZEN_ASSET["size"]:
        raise RuntimeError("trusted launcher frozen asset size mismatch")
    measured = _sha256_file(resolved)
    if measured != _TRUSTED_FROZEN_ASSET["sha256"]:
        raise RuntimeError("trusted launcher frozen asset hash mismatch")
    environment = _measure_environment_tree(environment_root)
    if environment["environment_tree_sha256"] != toolchain.get("environment_root_sha256"):
        raise RuntimeError("trusted launcher frozen environment identity mismatch")
    return {
        "path": resolved.as_posix(),
        "filename": resolved.name,
        "size": metadata.st_size,
        "sha256": measured,
        "authority_source": "trusted_launcher_binding",
    }


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


def _trusted_python_binding(
    binding_receipt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    executable = Path(sys.executable).absolute()
    resolved = executable.resolve(strict=True)
    proc_executable = Path("/proc/self/exe").resolve(strict=True)
    metadata = resolved.stat()
    if binding_receipt is None:
        executable_allowed = executable.as_posix() == "/usr/bin/python3.12"
    else:
        environment_root = Path(
            binding_receipt["toolchain"]["environment_root"]
        ).resolve(strict=True)
        expected_executable = environment_root / (
            "Scripts/python.exe" if os.name == "nt" else "bin/python"
        )
        executable_allowed = executable == expected_executable
    if (
        not executable_allowed
        or resolved != proc_executable
        or resolved.parent.as_posix() not in {"/usr/bin", "/bin"}
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != 0
        or metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
        or not metadata.st_mode & stat.S_IXUSR
    ):
        raise RuntimeError(
            "R3 bootstrap requires the governed frozen Python executable."
        )
    binding = {
        "requested_path": executable.as_posix(),
        "resolved_path": resolved.as_posix(),
        "proc_self_exe": proc_executable.as_posix(),
        "sha256": _sha256_file(resolved),
        "owner_uid": metadata.st_uid,
        "mode": f"{stat.S_IMODE(metadata.st_mode):04o}",
        "root_owned": True,
        "group_or_other_writable": False,
    }
    if binding_receipt is not None:
        binding["environment_root"] = binding_receipt["toolchain"][
            "environment_root"
        ]
    return binding


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


def _measure_source_tree(
    root: Path,
    *,
    binding_receipt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Measure HEAD plus one canonical candidate delta, or a clean HEAD."""

    root = root.resolve()
    receipt = binding_receipt or _load_binding_receipt(root)
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

    binding_map: dict[str, dict[str, Any]] = {}
    if receipt is not None:
        candidate = receipt["candidate"]
        binding_map = {
            binding["path"]: binding for binding in candidate["source_bindings"]
        }

    measured: dict[str, dict[str, str]] = {}
    for name, (expected_mode, expected_oid) in sorted(tree.items()):
        lowered = name.lower()
        if (
            expected_mode == "120000"
            or "__pycache__" in Path(name).parts
            or lowered.endswith(_IMPORT_OVERLAY_SUFFIXES[1:])
        ):
            raise RuntimeError(f"R3 tracked execution overlay is forbidden: {name}")
        target = root / name
        binding = binding_map.get(name)
        if not target.exists():
            if binding is not None and binding["present"] is False:
                continue
            raise RuntimeError(f"R3 source differs from HEAD: {name}")
        mode, oid = _git_blob(target, algorithm=object_format)
        if mode != expected_mode:
            raise RuntimeError(f"R3 source mode differs from HEAD: {name}")
        if oid != expected_oid:
            if (
                binding is None
                or binding["present"] is not True
                or _sha256_file(target) != binding["sha256"]
            ):
                raise RuntimeError(f"R3 source differs from HEAD: {name}")
        elif binding is not None and binding["present"] is False:
            raise RuntimeError(f"R3 deleted binding is still present: {name}")
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
    all_overlays = sorted(set(overlays) | set(root_overlays))
    expected_paths = set(binding_map)
    if receipt is None:
        if all_overlays:
            raise RuntimeError(
                f"R3 source contains untracked execution overlays: {all_overlays[:20]}"
            )
    elif set(all_overlays) - expected_paths:
        raise RuntimeError(
            "R3 candidate contains an unbound source overlay: "
            f"{sorted(set(all_overlays) - expected_paths)[:20]}"
        )

    if receipt is not None:
        changed_paths: set[str] = set()
        for arguments in (
            ("diff", "--name-only", "-z"),
            ("diff", "--cached", "--name-only", "-z"),
            ("ls-files", "--others", "--exclude-standard", "-z"),
        ):
            changed_paths.update(
                item.decode("utf-8", errors="surrogateescape")
                for item in _nul_records(_git(root, *arguments))
            )
        changed_paths.update(all_overlays)
        if changed_paths != expected_paths:
            raise RuntimeError("R3 candidate worktree delta differs from receipt.")
        for relative, binding in binding_map.items():
            target = root / relative
            resolved = target.resolve()
            if not _is_contained(resolved, root) or target.is_symlink():
                raise RuntimeError("R3 candidate binding escaped its checkout.")
            if binding["present"]:
                if not target.is_file() or _sha256_file(target) != binding["sha256"]:
                    raise RuntimeError(f"R3 candidate binding differs: {relative}")
            elif target.exists() or target.is_symlink():
                raise RuntimeError(f"R3 deleted candidate binding is present: {relative}")

    launcher_entry = measured.get(_LAUNCHER_RELATIVE_PATH)
    if launcher_entry is None:
        raise RuntimeError("R3 trusted launcher is absent from the exact HEAD tree.")
    launcher_blob = _git(root, "show", f"HEAD:{_LAUNCHER_RELATIVE_PATH}")
    launcher_blob_sha256 = _sha256_bytes(launcher_blob)
    current_launcher_sha256 = _sha256_file(root / _LAUNCHER_RELATIVE_PATH)
    if receipt is None:
        if launcher_blob_sha256 != current_launcher_sha256:
            raise RuntimeError("R3 trusted launcher worktree bytes differ from its Git blob.")
    elif current_launcher_sha256 != receipt["launcher"]["sha256"]:
        raise RuntimeError("R3 trusted launcher bytes differ from the governed receipt.")

    commit = _git(root, "rev-parse", "HEAD").decode().strip()
    tree_oid = _git(root, "rev-parse", "HEAD^{tree}").decode().strip()
    if receipt is not None and commit != receipt["candidate"]["head"]:
        raise RuntimeError("R3 candidate HEAD differs from the governed receipt.")
    result = {
        "commit": commit,
        "tree": tree_oid,
        "git_object_format": object_format,
        "tracked_path_count": len(measured),
        "tracked_manifest_sha256": _canonical_sha256(measured),
        "git_executable_sha256": _sha256_file(_trusted_git()),
        "launcher_blob_oid": launcher_entry["blob_oid"],
        "launcher_blob_sha256": launcher_blob_sha256,
    }
    if receipt is not None:
        result["candidate_binding"] = {
            "receipt_sha256": receipt["receipt_sha256"],
            "worktree_delta_sha256": receipt["candidate"]["worktree_delta_sha256"],
            "source_binding_sha256": receipt["candidate"]["source_binding_sha256"],
            "source_binding_count": receipt["candidate"]["source_binding_count"],
            "exact_match": True,
        }
    return result


def _measure_environment_tree(venv: Path) -> dict[str, Any]:
    site_packages = (
        venv / "Lib" / "site-packages"
        if os.name == "nt"
        else venv / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
    )
    roots = (
        venv / ("Scripts" if os.name == "nt" else "bin"),
        site_packages,
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
    binding_receipt = _load_binding_receipt(root)
    if (
        os.environ.get("COLAMETA_VALIDATION_LANE") == _HOST_FROZEN_LANE
        and binding_receipt is None
    ):
        raise RuntimeError("R3 host-frozen execution requires a governed binding receipt.")
    frozen_asset = None
    if binding_receipt is not None and (
        os.environ.get("COLAMETA_VALIDATION_LANE") == _HOST_FROZEN_LANE
    ):
        frozen_asset = _verify_bound_frozen_asset(root, binding_receipt)
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
    venv = (
        Path(binding_receipt["toolchain"]["environment_root"]).resolve()
        if binding_receipt is not None
        else root / ".venv"
    )
    python_binding = _trusted_python_binding(binding_receipt)
    source = _measure_source_tree(root, binding_receipt=binding_receipt)
    environment = _measure_environment_tree(venv)
    if (
        binding_receipt is None
        and environment["environment_tree_sha256"] != _EXPECTED_ENVIRONMENT_TREE_SHA256
    ):
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
    if binding_receipt is not None:
        record["trusted_launcher_binding"] = binding_receipt
    if frozen_asset is not None:
        record["frozen_asset"] = frozen_asset
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
    binding_receipt = attestation.get("trusted_launcher_binding")
    if binding_receipt is not None and not isinstance(binding_receipt, dict):
        raise RuntimeError("R3 trusted launcher binding attestation is invalid.")
    venv = (
        Path(binding_receipt["toolchain"]["environment_root"]).resolve()
        if isinstance(binding_receipt, dict)
        else project_root / ".venv"
    )
    site_packages = (
        venv / "Lib" / "site-packages"
        if os.name == "nt"
        else venv / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
    )
    sys.prefix = venv.as_posix()
    sys.exec_prefix = venv.as_posix()
    sys.path.insert(0, site_packages.as_posix())
    sys.path.insert(0, project_root.as_posix())

    if isinstance(binding_receipt, dict) and (
        os.environ.get("COLAMETA_VALIDATION_LANE") == _HOST_FROZEN_LANE
    ):
        # Re-measure immediately after the interpreter/site-packages boundary
        # is established.  This closes the post-binding mutation window while
        # keeping Candidate toolchain helpers out of the authority decision.
        _verify_bound_frozen_asset(project_root, binding_receipt)

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
