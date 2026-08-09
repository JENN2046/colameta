from __future__ import annotations

import base64
import hashlib
import os
import re
import stat
import sys
import sysconfig
from importlib import metadata
from pathlib import Path, PurePosixPath
from typing import Any

from runner.work_item_governance.canonical import canonical_sha256, sha256_file
from runner.work_item_governance.errors import WorkItemGovernanceError


_EXPECTED_DISTRIBUTION_VERSIONS = {
    "bandit": "1.9.4",
    "cryptography": "50.0.0",
    "jsonschema": "4.26.0",
    "pip-audit": "2.10.1",
    "pytest": "9.1.1",
    "ruff": "0.15.20",
    "setuptools": "83.0.0",
}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REQUIRED_TOOL_WRAPPERS = ("bandit", "pip-audit", "pytest", "ruff")
_EXPECTED_BIN_ENTRIES = (
    "Activate.ps1",
    "activate",
    "activate.csh",
    "activate.fish",
    "bandit",
    "bandit-baseline",
    "bandit-config-generator",
    "colameta",
    "coverage",
    "coverage-3.12",
    "coverage3",
    "doesitcache",
    "idna",
    "jsonschema",
    "markdown-it",
    "normalizer",
    "pip",
    "pip-audit",
    "pip3",
    "pip3.12",
    "py.test",
    "pygmentize",
    "pytest",
    "python",
    "python3",
    "python3.12",
    "ruff",
    "wheel",
)
_EXPECTED_FROZEN_TOOLCHAIN_ASSETS = {
    "cryptography": {
        "distribution": "cryptography",
        "version": "50.0.0",
        "filename": "cryptography-50.0.0-cp39-abi3-manylinux_2_34_x86_64.whl",
        "size": 4762400,
        "sha256": "37fdb0d0111f1e2ff07139dfb79f1b49531f8e213c46f1163dd7642979b58c47",
    },
}
_EXPECTED_ENVIRONMENT_ROOT_SHA256 = (
    "1eb3b914080827525b75bb230b0f2cb41a692995892ba39a71085f70bd141c29"
)
_FROZEN_TOOLCHAIN_RECORD_SCHEMA_VERSION = "work_item_r3_closeout_toolchain_record.v2"
_FROZEN_TOOLCHAIN_RECORD_BYTECODE_POLICY = {
    "record_listed": "forbidden",
    "non_record_listed": "forbidden",
    "unknown_owner": "fail_closed",
}
_EXPECTED_FROZEN_TOOLCHAIN_RECORD_SHA256 = (
    "c9ba12106b90e31d3000f1de8f41f3587fc4fbbb56a712fdf44ee482ef6570af"
)


def load_verified_frozen_toolchain_record() -> dict[str, Any]:
    """Load the immutable contract without inspecting the active environment."""

    record = {
        "schema_version": _FROZEN_TOOLCHAIN_RECORD_SCHEMA_VERSION,
        "required_versions": dict(_EXPECTED_DISTRIBUTION_VERSIONS),
        "required_bin_entries": list(_EXPECTED_BIN_ENTRIES),
        "required_tool_wrappers": list(_REQUIRED_TOOL_WRAPPERS),
        "required_assets": {
            name: dict(asset)
            for name, asset in _EXPECTED_FROZEN_TOOLCHAIN_ASSETS.items()
        },
        "environment_root_sha256": _EXPECTED_ENVIRONMENT_ROOT_SHA256,
        "bytecode_policy": dict(_FROZEN_TOOLCHAIN_RECORD_BYTECODE_POLICY),
    }
    if (
        record["schema_version"] != _FROZEN_TOOLCHAIN_RECORD_SCHEMA_VERSION
        or not _SHA256_RE.fullmatch(str(record["environment_root_sha256"]))
        or not record["required_versions"]
        or not record["required_bin_entries"]
        or tuple(record["required_tool_wrappers"]) != _REQUIRED_TOOL_WRAPPERS
        or record["required_assets"] != _EXPECTED_FROZEN_TOOLCHAIN_ASSETS
        or record["bytecode_policy"] != _FROZEN_TOOLCHAIN_RECORD_BYTECODE_POLICY
    ):
        raise WorkItemGovernanceError(
            "CLOSEOUT_TOOLCHAIN_RECORD_INVALID",
            "The embedded frozen toolchain record failed schema validation.",
        )
    record_sha256 = canonical_sha256(record)
    if (
        _EXPECTED_FROZEN_TOOLCHAIN_RECORD_SHA256
        and record_sha256 != _EXPECTED_FROZEN_TOOLCHAIN_RECORD_SHA256
    ):
        raise WorkItemGovernanceError(
            "CLOSEOUT_TOOLCHAIN_RECORD_INVALID",
            "The embedded frozen toolchain record digest does not match.",
        )
    return {**record, "record_sha256": record_sha256}


def _toolchain_context(
    project_root: str | os.PathLike[str],
) -> tuple[Path, Path, Path]:
    project = Path(project_root).expanduser().resolve()
    venv = (project / ".venv").resolve()
    site_packages = Path(sysconfig.get_paths()["purelib"]).resolve()
    if (
        Path(sys.prefix).resolve() != venv
        or not site_packages.is_dir()
        or not _is_relative_to(site_packages, venv)
    ):
        raise WorkItemGovernanceError(
            "CLOSEOUT_TOOLCHAIN_ENVIRONMENT_INVALID",
            "Closeout verification must run from the project-local virtual environment.",
        )
    return project, venv, site_packages


def _path_key(path: Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _canonical_environment_path(path: Path, venv: Path) -> str:
    resolved = path.resolve()
    if _is_relative_to(resolved, venv):
        return resolved.relative_to(venv).as_posix()
    return resolved.as_posix()


def _bytecode_inventory(
    *,
    venv: Path,
    site_packages: Path,
    distributions: list[metadata.Distribution],
) -> dict[str, Any]:
    record_owners: dict[str, set[str]] = {}
    for distribution in distributions:
        name = _normalized_name(distribution.metadata.get("Name", ""))
        for package_path in distribution.files or ():
            lexical = Path(
                os.path.abspath(os.fspath(distribution.locate_file(package_path)))
            )
            if lexical.suffix.lower() not in {".pyc", ".pyo"}:
                continue
            if lexical.is_file() and not lexical.is_symlink():
                record_owners.setdefault(_path_key(lexical), set()).add(name)

    stdlib_roots = {
        Path(sysconfig.get_paths().get("stdlib", "")).resolve(),
        (venv / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}").resolve(),
    }
    counts = {
        "total_count": 0,
        "record_listed_count": 0,
        "non_record_listed_count": 0,
        "project_distribution_count": 0,
        "third_party_distribution_count": 0,
        "standard_library_count": 0,
        "unknown_owner_count": 0,
    }
    owner_names: set[str] = set()
    for path in venv.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".pyc", ".pyo"}:
            continue
        counts["total_count"] += 1
        owners = record_owners.get(_path_key(path))
        if owners:
            counts["record_listed_count"] += 1
            owner_names.update(owners)
            if "colameta" in owners:
                counts["project_distribution_count"] += 1
            else:
                counts["third_party_distribution_count"] += 1
            continue
        counts["non_record_listed_count"] += 1
        resolved = path.resolve()
        if (
            any(_is_relative_to(resolved, root) for root in stdlib_roots)
            and not _is_relative_to(resolved, site_packages)
        ):
            counts["standard_library_count"] += 1
        else:
            counts["unknown_owner_count"] += 1
    return {
        **counts,
        "record_owner_count": len(owner_names),
        "bytecode_policy_satisfied": counts["total_count"] == 0,
    }


def inspect_frozen_toolchain_environment(
    project_root: str | os.PathLike[str],
) -> dict[str, Any]:
    """Inspect a toolchain without confusing diagnostics with strict acceptance."""

    record = load_verified_frozen_toolchain_record()
    project, venv, site_packages = _toolchain_context(project_root)
    distributions = sorted(
        metadata.distributions(path=[site_packages.as_posix()]),
        key=lambda item: _normalized_name(item.metadata.get("Name", "")),
    )
    inventory = _bytecode_inventory(
        venv=venv,
        site_packages=site_packages,
        distributions=distributions,
    )
    strict_error_code = None
    measured: dict[str, Any] | None = None
    try:
        measured = _measure_closeout_toolchain(
            project,
            allow_preimport_bytecode=True,
        )
    except WorkItemGovernanceError as exc:
        strict_error_code = exc.code
    blocking_reasons: list[str] = []
    if inventory["record_listed_count"]:
        blocking_reasons.append("CLOSEOUT_TOOLCHAIN_PREIMPORT_BYTECODE")
    if inventory["unknown_owner_count"]:
        blocking_reasons.append("CLOSEOUT_TOOLCHAIN_UNOWNED_IMPORT_FILE")
    if strict_error_code and strict_error_code not in blocking_reasons:
        blocking_reasons.append(strict_error_code)
    environment_root = measured.get("environment_root_sha256") if measured else None
    environment_root_matches = environment_root == record["environment_root_sha256"]
    return {
        "status": "matched" if not blocking_reasons and environment_root_matches else "drifted",
        "record_sha256": record["record_sha256"],
        "record_hashes_verified": measured is not None
        and measured.get("record_hashes_verified") is True,
        "environment_root_sha256": environment_root,
        "environment_root_matches": environment_root_matches,
        "bytecode_inventory": inventory,
        "bytecode_policy_satisfied": inventory["bytecode_policy_satisfied"],
        "blocking_reasons": blocking_reasons,
        "strict_measure_error_code": strict_error_code,
    }


def measure_closeout_toolchain(project_root: str | os.PathLike[str]) -> dict[str, Any]:
    """Perform the strict frozen-toolchain measurement."""

    return _measure_closeout_toolchain(project_root)


def _measure_closeout_toolchain(
    project_root: str | os.PathLike[str],
    *,
    allow_preimport_bytecode: bool = False,
) -> dict[str, Any]:
    """Measure the exact local verification environment and fail on drift.

    The R3 Closeout is intentionally a local exact-candidate review, not a claim
    that PyPI or the host OS is independently trusted.  Within that boundary we
    still bind every installed distribution file, executable wrapper and
    executable version used by the retained commands.  RECORD hashes are
    checked when present, and unowned importable files are rejected.
    """

    record = load_verified_frozen_toolchain_record()
    project, venv, site_packages = _toolchain_context(project_root)

    owned_paths: set[Path] = set()
    file_entries: dict[str, dict[str, Any]] = {}
    distributions: list[dict[str, Any]] = []
    for distribution in sorted(
        metadata.distributions(path=[site_packages.as_posix()]),
        key=lambda item: _normalized_name(item.metadata.get("Name", "")),
    ):
        name = _normalized_name(distribution.metadata.get("Name", ""))
        if not name:
            raise WorkItemGovernanceError(
                "CLOSEOUT_TOOLCHAIN_DISTRIBUTION_INVALID",
                "An installed distribution has no normalized name.",
            )
        version = str(distribution.version)
        distribution_entries: list[dict[str, Any]] = []
        for package_path in distribution.files or ():
            relative_text = str(package_path).replace("\\", "/")
            lexical = Path(
                os.path.abspath(os.fspath(distribution.locate_file(package_path)))
            )
            if (
                lexical.suffix.lower() in {".pyc", ".pyo"}
                and lexical.exists()
            ):
                if not allow_preimport_bytecode:
                    raise WorkItemGovernanceError(
                        "CLOSEOUT_TOOLCHAIN_PREIMPORT_BYTECODE",
                        "The exact verification environment must not contain pre-import bytecode.",
                        details={"distribution": name, "path": relative_text},
                    )
                continue
            if not lexical.exists() and "__pycache__" in PurePosixPath(relative_text).parts:
                continue
            resolved = lexical.resolve()
            if (
                lexical.is_symlink()
                or not resolved.is_file()
                or not _is_relative_to(resolved, venv)
            ):
                # Editable ColaMeta source is bound independently to Git+Wheel.
                if name == "colameta" and _is_relative_to(resolved, project):
                    continue
                raise WorkItemGovernanceError(
                    "CLOSEOUT_TOOLCHAIN_FILE_INVALID",
                    "An installed distribution references a missing or external file.",
                    details={"distribution": name, "path": relative_text},
                )
            actual_size = resolved.stat().st_size
            actual_sha256 = sha256_file(resolved)
            if package_path.size is not None and int(package_path.size) != actual_size:
                raise WorkItemGovernanceError(
                    "CLOSEOUT_TOOLCHAIN_RECORD_MISMATCH",
                    "An installed distribution file size differs from RECORD.",
                    details={"distribution": name, "path": relative_text},
                )
            if package_path.hash is not None:
                if package_path.hash.mode != "sha256":
                    raise WorkItemGovernanceError(
                        "CLOSEOUT_TOOLCHAIN_RECORD_MISMATCH",
                        "Closeout requires SHA-256 distribution RECORD entries.",
                        details={"distribution": name, "path": relative_text},
                    )
                measured = base64.urlsafe_b64encode(
                    bytes.fromhex(actual_sha256)
                ).rstrip(b"=").decode("ascii")
                if measured != package_path.hash.value:
                    raise WorkItemGovernanceError(
                        "CLOSEOUT_TOOLCHAIN_RECORD_MISMATCH",
                        "An installed distribution file differs from RECORD.",
                        details={"distribution": name, "path": relative_text},
                    )
            relative_venv = resolved.relative_to(venv).as_posix()
            owned_paths.add(lexical)
            entry = {
                "path": relative_venv,
                "size_bytes": actual_size,
                "sha256": actual_sha256,
            }
            file_entries[relative_venv] = entry
            distribution_entries.append(entry)
        distributions.append(
            {
                "name": name,
                "version": version,
                "file_count": len(distribution_entries),
                "file_root_sha256": _line_root(distribution_entries),
            }
        )

    measured_versions = {item["name"]: item["version"] for item in distributions}
    if any(
        measured_versions.get(name) != expected
        for name, expected in record["required_versions"].items()
    ):
        raise WorkItemGovernanceError(
            "CLOSEOUT_TOOLCHAIN_VERSION_MISMATCH",
            "The local verification tool versions differ from the frozen R3 environment.",
            details={
                "expected": record["required_versions"],
                "measured": {
                    name: measured_versions.get(name)
                    for name in record["required_versions"]
                },
            },
        )

    unowned = _unowned_site_package_entries(site_packages, owned_paths)
    if allow_preimport_bytecode:
        unowned = [
            path
            for path in unowned
            if Path(path).suffix.lower() not in {".pyc", ".pyo"}
        ]
    if unowned:
        raise WorkItemGovernanceError(
            "CLOSEOUT_TOOLCHAIN_UNOWNED_IMPORT_FILE",
            "The verification environment contains files not owned by a distribution RECORD.",
            details={"paths": unowned[:50], "count": len(unowned)},
        )

    wrappers: list[dict[str, Any]] = []
    for name in record["required_tool_wrappers"]:
        lexical = venv / "bin" / name
        resolved = lexical.resolve()
        if not lexical.is_file() or not resolved.is_file():
            raise WorkItemGovernanceError(
                "CLOSEOUT_TOOLCHAIN_EXECUTABLE_MISSING",
                "A required Closeout executable is unavailable.",
                details={"tool": name},
            )
        wrapper = {
            "name": name,
            "path": lexical.relative_to(venv).as_posix(),
            "resolved_path": _canonical_environment_path(lexical, venv),
            "mode": stat.S_IMODE(lexical.stat().st_mode),
            "size_bytes": lexical.stat().st_size,
            "sha256": sha256_file(lexical),
        }
        wrappers.append(wrapper)
        if lexical.absolute() not in owned_paths:
            raise WorkItemGovernanceError(
                "CLOSEOUT_TOOLCHAIN_EXECUTABLE_UNOWNED",
                "A required tool executable is not owned by its distribution RECORD.",
                details={"tool": name},
            )

    python_wrapper = venv / "bin" / "python"
    pyvenv = venv / "pyvenv.cfg"
    if not python_wrapper.exists() or not pyvenv.is_file():
        raise WorkItemGovernanceError(
            "CLOSEOUT_TOOLCHAIN_PYTHON_INVALID",
            "The project virtual environment has no complete Python binding.",
        )
    fixed_files = [
        {
            "path": "bin/python",
            "size_bytes": python_wrapper.stat().st_size,
            "sha256": sha256_file(python_wrapper),
            "symlink_target": os.readlink(python_wrapper) if python_wrapper.is_symlink() else None,
        },
        {
            "path": "pyvenv.cfg",
            "size_bytes": pyvenv.stat().st_size,
            "sha256": sha256_file(pyvenv),
            "symlink_target": None,
        },
    ]
    bin_inventory = _measure_bin_inventory(
        venv,
        expected_entries=record["required_bin_entries"],
    )
    environment_files = sorted(file_entries.values(), key=lambda item: item["path"])
    environment_root = canonical_sha256(
        {
            "bin_inventory": bin_inventory,
            "distributions": distributions,
            "environment_file_root_sha256": _line_root(environment_files),
            "fixed_files": fixed_files,
            "wrappers": wrappers,
        }
    )
    if environment_root != record["environment_root_sha256"]:
        raise WorkItemGovernanceError(
            "CLOSEOUT_TOOLCHAIN_ROOT_MISMATCH",
            "The local verification environment differs from the frozen R3 toolchain.",
            details={"measured_environment_root_sha256": environment_root},
        )
    return {
        "schema_version": "work_item_r3_closeout_toolchain.v1",
        "python_version": sys.version,
        "python_executable": Path(sys.executable).resolve().as_posix(),
        "python_executable_sha256": sha256_file(Path(sys.executable).resolve()),
        "virtual_environment": venv.as_posix(),
        "site_packages": site_packages.as_posix(),
        "distribution_count": len(distributions),
        "distributions": distributions,
        "distributions_sha256": canonical_sha256(distributions),
        "environment_file_count": len(environment_files),
        "environment_file_root_sha256": _line_root(environment_files),
        "environment_root_sha256": environment_root,
        "bin_inventory": bin_inventory,
        "bin_inventory_sha256": canonical_sha256(bin_inventory),
        "fixed_files": fixed_files,
        "required_versions": dict(record["required_versions"]),
        "wrappers": wrappers,
        "record_hashes_verified": True,
        "unowned_import_files": [],
        "frozen_toolchain_record_sha256": record["record_sha256"],
        "bytecode_policy_satisfied": not allow_preimport_bytecode,
    }


def _line_root(entries: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for entry in sorted(entries, key=lambda item: str(item["path"]).encode("utf-8")):
        digest.update(
            f"{entry['sha256']}  {entry['size_bytes']}  {entry['path']}\n".encode("utf-8")
        )
    return digest.hexdigest()


def _normalized_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def _unowned_site_package_entries(
    site_packages: Path,
    owned_paths: set[Path],
) -> list[str]:
    unowned: list[str] = []
    for path in site_packages.rglob("*"):
        relative = path.relative_to(site_packages).as_posix()
        if path.is_dir() and not path.is_symlink():
            continue
        if path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode):
            unowned.append(relative)
            continue
        if path.absolute() not in owned_paths:
            unowned.append(relative)
    return sorted(unowned)


def _measure_bin_inventory(
    venv: Path,
    *,
    expected_entries: list[str] | tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    bin_root = venv / "bin"
    entries = sorted(bin_root.iterdir(), key=lambda item: item.name.encode("utf-8"))
    expected = tuple(expected_entries or _EXPECTED_BIN_ENTRIES)
    if tuple(item.name for item in entries) != expected:
        raise WorkItemGovernanceError(
            "CLOSEOUT_TOOLCHAIN_BIN_INVENTORY_MISMATCH",
            "The virtualenv bin directory differs from the frozen exact inventory.",
            details={"measured_names": [item.name for item in entries]},
        )
    inventory: list[dict[str, Any]] = []
    for path in entries:
        metadata = path.lstat()
        if path.is_symlink():
            resolved = path.resolve()
            if not resolved.is_file():
                raise WorkItemGovernanceError(
                    "CLOSEOUT_TOOLCHAIN_BIN_ENTRY_INVALID",
                    "A virtualenv executable symlink has no regular target.",
                    details={"entry": path.name},
                )
            inventory.append(
                {
                    "name": path.name,
                    "kind": "symlink",
                    "mode": f"{stat.S_IMODE(metadata.st_mode):04o}",
                    "symlink_target": os.readlink(path),
                    "resolved_path": resolved.as_posix(),
                    "sha256": sha256_file(resolved),
                }
            )
        elif stat.S_ISREG(metadata.st_mode):
            inventory.append(
                {
                    "name": path.name,
                    "kind": "regular",
                    "mode": f"{stat.S_IMODE(metadata.st_mode):04o}",
                    "size_bytes": metadata.st_size,
                    "sha256": sha256_file(path),
                }
            )
        else:
            raise WorkItemGovernanceError(
                "CLOSEOUT_TOOLCHAIN_BIN_ENTRY_INVALID",
                "The virtualenv bin directory contains a directory or special entry.",
                details={"entry": path.name},
            )
    return inventory


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


__all__ = [
    "inspect_frozen_toolchain_environment",
    "load_verified_frozen_toolchain_record",
    "measure_closeout_toolchain",
]
