"""Isolated toolchain construction for candidate-bound validation runs.

The validation runner deliberately keeps this module small and explicit.  A
validation child process is given a newly constructed environment and, for
Python commands, a newly constructed virtual environment whose package is
built from the candidate checkout.  The parent process' import paths and
virtual-environment markers are never used as a source of Python code.
"""

from __future__ import annotations

from dataclasses import dataclass
from email.parser import BytesParser
from email.policy import compat32
import hashlib
import json
import os
import platform
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig
import tempfile
from typing import Any, Mapping, Sequence
import venv
from zipfile import BadZipFile, ZipFile


_ENVIRONMENT_BLOCKLIST = frozenset(
    {
        "PYTHONPATH",
        "PYTHONHOME",
        "VIRTUAL_ENV",
        "CONDA_PREFIX",
        "PIP_PREFIX",
        "PIP_TARGET",
        "PIP_USER",
        "PYTHONUSERBASE",
        "PYTHONSTARTUP",
        "PIP_CONFIG_FILE",
        "PIP_FIND_LINKS",
        "PIP_NO_INDEX",
        "PIP_INDEX_URL",
        "PIP_EXTRA_INDEX_URL",
        "PIP_TRUSTED_HOST",
        "PIP_CONSTRAINT",
        "PIP_REQUIREMENT",
    }
)
_SAFE_PARENT_ENVIRONMENT = frozenset(
    {
        "PATH",
        "PATHEXT",
        "HOME",
        "USERPROFILE",
        "HOMEDRIVE",
        "HOMEPATH",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "LANG",
        "LANGUAGE",
        "LC_ALL",
        "LC_CTYPE",
        "LC_MESSAGES",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "REQUESTS_CA_BUNDLE",
        "CURL_CA_BUNDLE",
    }
)
_CANDIDATE_PIP_WHEEL_ENV = "COLAMETA_CANDIDATE_PIP_WHEEL"
_VALIDATION_ASSET_DIR_ENV = "COLAMETA_VALIDATION_ASSET_DIR"
_CANDIDATE_PIP_WHEEL_FILENAME = "pip-26.2-py3-none-any.whl"
_CANDIDATE_PIP_WHEEL_SHA256 = (
    "931c303696af6fa3417112103b1cad26890e5a07eccb5b99783700e33f2b8aad"
)
_CANDIDATE_PIP_VERSION = "26.2"
_OFFICIAL_PYPI_INDEX_URL = "https://pypi.org/simple"
_VALIDATION_TOOL_REQUIREMENTS = (
    "pytest>=9.0.3,<10",
    "ruff>=0.8,<1",
    "setuptools>=68",
    "wheel>=0.43",
    "bandit[toml]>=1.7,<2",
    "pip-audit>=2.7,<3",
    "pytest-cov>=5,<7",
)
_VALIDATION_TOOL_INSTALL_TIMEOUT_SECONDS = 1200
_PACKAGE_MODULES = ("runner", "adapters", "schemas", "scripts")


class ValidationEnvironmentError(RuntimeError):
    """Raised when a candidate validation environment cannot be proven safe."""


@dataclass(frozen=True)
class ValidationEnvironment:
    """The child-process environment and its non-sensitive provenance facts."""

    candidate_root: Path
    cwd: Path
    env: dict[str, str]
    venv_dir: Path | None
    python_executable: Path | None
    summary: dict[str, Any]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _wheel_primary_metadata(path: Path) -> tuple[str, str, set[object], Any]:
    """Read the distribution metadata for one wheel, excluding vendored metadata."""

    try:
        from packaging.utils import parse_wheel_filename
    except ImportError as exc:
        raise ValidationEnvironmentError(
            "candidate wheel metadata is invalid"
        ) from exc
    try:
        filename_name, filename_version, _build, tags = parse_wheel_filename(
            path.name
        )
        with ZipFile(path) as archive:
            metadata_names = []
            for name in archive.namelist():
                if not name.endswith(".dist-info/METADATA"):
                    continue
                dist_dir = name.rsplit("/", 1)[-2].removesuffix(".dist-info")
                if dist_dir.rsplit("-", 1)[0].casefold().replace("_", "-") == (
                    str(filename_name).casefold().replace("_", "-")
                ):
                    metadata_names.append(name)
            if len(metadata_names) != 1:
                raise ValidationEnvironmentError(
                    "candidate wheel metadata is invalid"
                )
            metadata = BytesParser(policy=compat32).parsebytes(
                archive.read(metadata_names[0])
            )
    except (OSError, BadZipFile, KeyError, ValueError) as exc:
        raise ValidationEnvironmentError(
            "candidate wheel metadata is invalid"
        ) from exc
    return str(filename_name), str(filename_version), set(tags), metadata


def verify_bound_wheel_asset(
    path: Path,
    *,
    expected_filename: str,
    expected_sha256: str,
) -> dict[str, Any]:
    """Verify one locally supplied wheel before it enters a validation env."""

    candidate = Path(path).expanduser()
    if candidate.is_symlink():
        raise ValidationEnvironmentError("bound frozen wheel asset is unavailable")
    asset = _real_path(candidate)
    if (
        not asset.is_file()
        or asset.is_symlink()
        or asset.name != expected_filename
    ):
        raise ValidationEnvironmentError("bound frozen wheel asset is unavailable")
    measured_sha256 = _sha256_file(asset)
    if measured_sha256 != expected_sha256:
        raise ValidationEnvironmentError("bound frozen wheel asset digest mismatch")
    return {
        "filename": asset.name,
        "sha256": measured_sha256,
        "source_verified": True,
    }


def _verify_bound_wheel_directory(
    path: Path,
    *,
    expected_filename: str,
    expected_sha256: str,
    expected_distribution: str,
    expected_version: str,
) -> tuple[Path, dict[str, Any]]:
    """Verify the dedicated local wheel directory used for frozen installs.

    The wheel is deliberately installed by an exact distribution requirement
    resolved through ``--find-links``.  Passing the absolute wheel path to pip
    makes PEP 610 record the temporary asset directory in ``direct_url.json``;
    that would make an otherwise identical frozen environment path-sensitive.
    The directory is therefore constrained before pip is invoked: it must be
    a real directory, contain the bound wheel, and contain no second candidate
    for the bound distribution.
    """

    candidate = Path(path).expanduser()
    parent = candidate.parent
    if parent.is_symlink():
        raise ValidationEnvironmentError(
            "bound frozen wheel asset directory is unavailable"
        )
    wheel_dir = _real_path(parent)
    if not wheel_dir.is_dir() or wheel_dir.is_symlink():
        raise ValidationEnvironmentError(
            "bound frozen wheel asset directory is unavailable"
        )

    bound = verify_bound_wheel_asset(
        candidate,
        expected_filename=expected_filename,
        expected_sha256=expected_sha256,
    )
    try:
        from packaging.tags import sys_tags
        from packaging.utils import canonicalize_name
    except ImportError as exc:
        raise ValidationEnvironmentError(
            "bound frozen wheel metadata is unavailable"
        ) from exc

    expected_name = canonicalize_name(expected_distribution)
    matching_wheels: list[Path] = []
    for entry in sorted(wheel_dir.iterdir(), key=lambda item: item.name):
        if entry.suffix.lower() != ".whl":
            continue
        if entry.is_symlink() or not entry.is_file():
            raise ValidationEnvironmentError(
                "bound frozen wheel directory contains an unsafe wheel entry"
            )
        try:
            filename_name, filename_version, tags, metadata = _wheel_primary_metadata(
                entry
            )
        except ValidationEnvironmentError as exc:
            raise ValidationEnvironmentError(
                "bound frozen wheel directory contains invalid wheel metadata"
            ) from exc
        if canonicalize_name(filename_name) != expected_name:
            continue
        matching_wheels.append(entry)
        if (
            filename_version != expected_version
            or metadata.get("Name") is None
            or canonicalize_name(str(metadata.get("Name"))) != expected_name
            or metadata.get("Version") != expected_version
            or not set(tags).intersection(sys_tags())
        ):
            raise ValidationEnvironmentError(
                "bound frozen wheel metadata does not match the contract"
            )

    bound_path = _real_path(candidate)
    if len(matching_wheels) != 1 or matching_wheels[0] != bound_path:
        raise ValidationEnvironmentError(
            "bound frozen wheel candidate set is ambiguous"
        )
    return wheel_dir, {
        **bound,
        "distribution": expected_distribution,
        "version": expected_version,
        "wheel_directory_verified": True,
        "matching_wheel_count": len(matching_wheels),
    }


def verify_candidate_pip_wheel_asset(path: Path) -> dict[str, Any]:
    """Verify the exact offline pip bootstrap wheel and its wheel metadata."""

    summary = verify_bound_wheel_asset(
        path,
        expected_filename=_CANDIDATE_PIP_WHEEL_FILENAME,
        expected_sha256=_CANDIDATE_PIP_WHEEL_SHA256,
    )
    asset = _real_path(Path(path).expanduser())
    try:
        with ZipFile(asset) as archive:
            metadata_names = sorted(
                name
                for name in archive.namelist()
                if name.endswith(".dist-info/METADATA")
            )
            if len(metadata_names) != 1:
                raise ValidationEnvironmentError(
                    "candidate pip wheel metadata is ambiguous"
                )
            metadata = BytesParser(policy=compat32).parsebytes(
                archive.read(metadata_names[0])
            )
    except (OSError, BadZipFile, KeyError, ValueError) as exc:
        raise ValidationEnvironmentError(
            "candidate pip wheel metadata is unreadable"
        ) from exc

    requires_python = metadata.get("Requires-Python")
    if (
        metadata.get("Name") != "pip"
        or metadata.get("Version") != _CANDIDATE_PIP_VERSION
        or requires_python != ">=3.10"
        or sys.version_info < (3, 10)
    ):
        raise ValidationEnvironmentError(
            "candidate pip wheel metadata does not match the bound contract"
        )
    return {
        **summary,
        "distribution": "pip",
        "version": _CANDIDATE_PIP_VERSION,
        "requires_python": requires_python,
        "metadata_verified": True,
    }


def resolve_candidate_pip_asset(
    parent_environment: Mapping[str, str],
) -> dict[str, Any] | None:
    """Resolve an explicitly supplied, locally bound candidate pip wheel."""

    candidates: list[Path] = []
    explicit = parent_environment.get(_CANDIDATE_PIP_WHEEL_ENV)
    if explicit:
        candidates.append(Path(explicit).expanduser())
    asset_dir = parent_environment.get(_VALIDATION_ASSET_DIR_ENV)
    if asset_dir:
        candidates.append(
            Path(asset_dir).expanduser() / _CANDIDATE_PIP_WHEEL_FILENAME
        )
    seen: set[str] = set()
    for candidate in candidates:
        key = os.path.abspath(os.fspath(candidate))
        if key in seen:
            continue
        seen.add(key)
        try:
            verified = verify_candidate_pip_wheel_asset(candidate)
        except ValidationEnvironmentError:
            continue
        return {
            "path": _real_path(candidate),
            **verified,
            "asset_verified": True,
            "installed_offline": True,
            "network_used": False,
            "runtime_dependency": False,
        }
    if explicit:
        raise ValidationEnvironmentError("CANDIDATE_PIP_26_2_ASSET_UNAVAILABLE")
    return None


def download_candidate_pip_asset(
    *,
    python_executable: Path,
    work_root: Path,
    environment: Mapping[str, str],
) -> dict[str, Any]:
    """Download and verify the exact pip bootstrap wheel from official PyPI."""

    download_dir = _real_path(work_root) / "candidate-pip-download"
    if download_dir.exists() or download_dir.is_symlink():
        raise ValidationEnvironmentError("candidate pip download directory collision")
    download_dir.mkdir(parents=True, exist_ok=True)
    download_command = [
        str(python_executable),
        "-m",
        "pip",
        "download",
        "--disable-pip-version-check",
        "--no-input",
        "--no-cache-dir",
        "--only-binary",
        ":all:",
        "--no-deps",
        "--index-url",
        _OFFICIAL_PYPI_INDEX_URL,
        "--dest",
        str(download_dir),
        f"pip=={_CANDIDATE_PIP_VERSION}",
    ]
    _run_toolchain_command(
        download_command,
        cwd=_real_path(work_root),
        environment=environment,
        timeout_seconds=300,
        label="candidate pip bootstrap download",
    )
    wheels = sorted(download_dir.glob("*.whl"))
    if len(wheels) != 1 or wheels[0].name != _CANDIDATE_PIP_WHEEL_FILENAME:
        raise ValidationEnvironmentError("CANDIDATE_PIP_26_2_ASSET_UNAVAILABLE")
    verified = verify_candidate_pip_wheel_asset(wheels[0])
    return {
        "path": _real_path(wheels[0]),
        **verified,
        "asset_verified": True,
        "installed_offline": False,
        "network_used": True,
        "runtime_dependency": False,
        "_pip_command": download_command,
    }


def venv_bin_dir(venv_dir: Path) -> Path:
    """Return the platform-specific executable directory for a virtualenv."""

    return venv_dir / ("Scripts" if os.name == "nt" else "bin")


def venv_python(venv_dir: Path) -> Path:
    """Return the platform-specific Python executable for a virtualenv."""

    return venv_bin_dir(venv_dir) / ("python.exe" if os.name == "nt" else "python")


def create_validation_venv(path: Path) -> None:
    """Create a validation venv with one explicit cross-platform policy.

    POSIX validation checkouts may use interpreter symlinks, while Windows
    validation checkouts must use copied launchers.  Keeping this policy in one
    helper prevents the initial venv and the post-wheel rebuild from drifting.
    """

    venv.EnvBuilder(
        symlinks=(os.name != "nt"),
        with_pip=True,
        system_site_packages=False,
    ).create(path)


def venv_console_script(venv_dir: Path, name: str) -> Path | None:
    """Return the generated console script path, if it exists."""

    directory = venv_bin_dir(venv_dir)
    candidates = [directory / name]
    if os.name == "nt":
        candidates.extend((directory / f"{name}.exe", directory / f"{name}.cmd"))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _real_path(path: Path) -> Path:
    return Path(os.path.realpath(path))


def _is_within(path: Path, root: Path) -> bool:
    try:
        return os.path.commonpath([str(path), str(root)]) == str(root)
    except ValueError:
        return False


def _normalise_parent_environment(
    parent_environment: Mapping[str, str],
) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in parent_environment.items():
        if key in _ENVIRONMENT_BLOCKLIST:
            continue
        if key in _SAFE_PARENT_ENVIRONMENT or key.startswith("LC_"):
            result[key] = str(value)
    return result


def build_validation_subprocess_environment(
    *,
    candidate_root: Path,
    validation_venv: Path | None = None,
    venv_dir: Path | None = None,
    parent_environment: Mapping[str, str] | None = None,
    base_env: Mapping[str, str] | None = None,
    temp_root: Path | None = None,
    forbidden_roots: Sequence[Path] = (),
) -> dict[str, str]:
    """Build a scrubbed child environment without importing a source tree.

    ``base_env`` and ``venv_dir`` are accepted as readable aliases for the
    names used by older callers.  The function intentionally has no
    ``PYTHONPATH`` parameter: candidate source is selected by ``cwd`` and by
    the candidate-built distribution, never by an injected import path.
    """

    if validation_venv is not None and venv_dir is not None:
        raise ValueError("validation_venv and venv_dir are mutually exclusive")
    selected_venv = validation_venv or venv_dir
    parent = parent_environment or base_env or os.environ
    candidate = _real_path(candidate_root)
    forbidden = tuple(_real_path(path) for path in forbidden_roots)
    if not candidate.is_dir():
        raise ValidationEnvironmentError("candidate checkout is not a directory")
    if selected_venv is not None:
        selected_venv = _real_path(selected_venv)
        if not selected_venv.is_dir():
            raise ValidationEnvironmentError("validation virtualenv is not a directory")
        if any(_is_within(selected_venv, root) for root in forbidden):
            raise ValidationEnvironmentError("validation virtualenv escapes the isolated environment")

    environment = _normalise_parent_environment(parent)
    parent_path = environment.get("PATH", "")
    path_entries = []
    for item in parent_path.split(os.pathsep):
        if not item:
            continue
        real_item = _real_path(Path(item))
        if any(_is_within(real_item, root) for root in forbidden):
            continue
        path_entries.append(item)
    if selected_venv is not None:
        path_entries.insert(0, str(venv_bin_dir(selected_venv)))
    if not path_entries:
        path_entries.append(str(venv_bin_dir(selected_venv)) if selected_venv is not None else os.defpath)
    environment["PATH"] = os.pathsep.join(path_entries)

    if temp_root is not None:
        temp = _real_path(temp_root)
        home = temp / "home"
        scratch = temp / "tmp"
        home.mkdir(parents=True, exist_ok=True)
        scratch.mkdir(parents=True, exist_ok=True)
        environment["HOME"] = str(home)
        environment["TMPDIR"] = str(scratch)
        environment["TEMP"] = str(scratch)
        environment["TMP"] = str(scratch)
        if os.name == "nt":
            environment["USERPROFILE"] = str(home)
    elif "HOME" not in environment and os.name != "nt":
        environment["HOME"] = str(Path(tempfile.gettempdir()))

    if selected_venv is not None:
        environment["VIRTUAL_ENV"] = str(selected_venv)
    else:
        environment.pop("VIRTUAL_ENV", None)
    environment["PYTHONNOUSERSITE"] = "1"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    environment["PIP_NO_INPUT"] = "1"
    environment["PIP_NO_CACHE_DIR"] = "1"
    environment["GIT_TERMINAL_PROMPT"] = "0"
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    environment["PWD"] = str(candidate)
    for key in _ENVIRONMENT_BLOCKLIST - {"VIRTUAL_ENV"}:
        environment.pop(key, None)
    for key in (_CANDIDATE_PIP_WHEEL_ENV, _VALIDATION_ASSET_DIR_ENV):
        locator = parent.get(key)
        if locator:
            environment[key] = str(locator)
    return environment


def command_uses_python(command: Sequence[str]) -> bool:
    """Return whether an argv's executable is a Python interpreter."""

    if not command:
        return False
    name = Path(command[0]).name.lower()
    return name in {"python", "python3", "python.exe", "python3.exe"} or name.startswith("python3.")


def rewrite_command_for_validation_environment(
    command: Sequence[str],
    validation_venv: Path | None,
) -> list[str]:
    """Point Python argv at the validation venv while preserving declared argv."""

    rewritten = list(command)
    if validation_venv is not None and command_uses_python(rewritten):
        rewritten[0] = str(venv_python(validation_venv))
    return rewritten


def _load_pyproject(candidate_root: Path) -> dict[str, Any] | None:
    pyproject = candidate_root / "pyproject.toml"
    if not pyproject.is_file():
        return None
    try:
        try:
            import tomllib
        except ModuleNotFoundError:
            import tomli as tomllib

        with pyproject.open("rb") as handle:
            payload = tomllib.load(handle)
    except (OSError, ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def _project_metadata(candidate_root: Path) -> tuple[str | None, list[str]]:
    payload = _load_pyproject(candidate_root)
    project = payload.get("project", {}) if payload is not None else {}
    if not isinstance(project, dict):
        return None, []
    name = project.get("name")
    scripts = project.get("scripts", {})
    script_names = [key for key in scripts if isinstance(key, str) and key.strip()] if isinstance(scripts, dict) else []
    return (name.strip() if isinstance(name, str) and name.strip() else None), script_names


def _project_is_installable(candidate_root: Path) -> bool:
    """Return whether the candidate exposes an explicit packaging surface.

    Static PEP 621 metadata is optional for local projects.  A setup.py,
    setup.cfg, or packaging table in pyproject.toml is enough to enter the
    existing governed wheel build/install path; a tool-only pyproject is not.
    """

    if any((candidate_root / filename).is_file() for filename in ("setup.py", "setup.cfg")):
        return True
    payload = _load_pyproject(candidate_root)
    if payload is None:
        return False
    return any(isinstance(payload.get(section), dict) for section in ("project", "build-system"))


def _run_toolchain_command(
    command: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    timeout_seconds: int,
    label: str,
) -> None:
    try:
        completed = subprocess.run(
            list(command),
            cwd=cwd,
            env=dict(environment),
            capture_output=True,
            text=True,
            check=False,
            shell=False,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValidationEnvironmentError(
            f"validation toolchain {label} failed"
        ) from exc
    if completed.returncode != 0:
        raise ValidationEnvironmentError(
            f"validation toolchain {label} returned a failure"
        )


def _clean_candidate_build_overlays(
    *,
    candidate_root: Path,
    environment: Mapping[str, str],
) -> None:
    """Remove bounded setuptools outputs without touching the validation venv.

    ``git clean`` cannot express the required safety boundary reliably for an
    ignored virtualenv: an exclude pattern can still allow the directory to be
    traversed and removed on some Git versions.  The build performed here has a
    small, known output surface, so clean only those paths and leave every other
    candidate-bound or runtime path untouched.
    """

    del environment  # The bounded cleanup intentionally does not invoke a child process.
    generated_paths = [candidate_root / "build", candidate_root / "dist"]
    generated_paths.extend(candidate_root.glob("*.egg-info"))
    for path in generated_paths:
        try:
            if path.is_symlink():
                raise ValidationEnvironmentError(
                    "candidate build overlay cleanup encountered a symlink"
                )
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()
        except ValidationEnvironmentError:
            raise
        except OSError as exc:
            raise ValidationEnvironmentError("candidate build overlay cleanup failed") from exc


def _remove_bytecode(root: Path) -> None:
    """Keep the fresh validation toolchain free of pre-import bytecode."""

    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in {".pyc", ".pyo"}:
            try:
                path.unlink()
            except OSError as exc:
                raise ValidationEnvironmentError("validation bytecode cleanup failed") from exc


def materialize_frozen_toolchain_environment(
    *,
    source_venv: Path,
    work_root: Path,
    frozen_asset: Path | None = None,
    frozen_asset_filename: str | None = None,
    frozen_asset_sha256: str | None = None,
    frozen_asset_distribution: str = "cryptography",
    frozen_asset_version: str = "50.0.0",
) -> tuple[Path, Path, dict[str, Any]]:
    """Copy local frozen-toolchain assets into a disposable bytecode-free venv."""

    source = _real_path(source_venv)
    work = _real_path(work_root)
    if not source.is_dir() or not (source / "pyvenv.cfg").is_file():
        raise ValidationEnvironmentError("frozen toolchain source is unavailable")
    if _is_within(work, source) or _is_within(source, work):
        raise ValidationEnvironmentError("frozen toolchain materialization roots overlap")
    work.mkdir(parents=True, exist_ok=True)
    project_root = work / "frozen-toolchain-project"
    venv_root = project_root / ".venv"
    if project_root.exists() or project_root.is_symlink():
        raise ValidationEnvironmentError("frozen toolchain materialization already exists")

    source_bytecode_count = sum(
        1
        for path in source.rglob("*")
        if path.is_file() and path.suffix.lower() in {".pyc", ".pyo"}
    )

    def ignore_bytecode(_directory: str, names: list[str]) -> set[str]:
        return {
            name
            for name in names
            if Path(name).suffix.lower() in {".pyc", ".pyo"}
        }

    try:
        shutil.copytree(
            source,
            venv_root,
            symlinks=True,
            ignore=ignore_bytecode,
        )
    except (OSError, shutil.Error) as exc:
        raise ValidationEnvironmentError(
            "frozen toolchain materialization failed"
        ) from exc

    asset_summary: dict[str, Any] | None = None
    if frozen_asset is not None:
        if not frozen_asset_filename or not frozen_asset_sha256:
            raise ValidationEnvironmentError("frozen wheel asset binding is incomplete")
        wheel_dir, asset_summary = _verify_bound_wheel_directory(
            frozen_asset,
            expected_filename=frozen_asset_filename,
            expected_sha256=frozen_asset_sha256,
            expected_distribution=frozen_asset_distribution,
            expected_version=frozen_asset_version,
        )
        environment = build_validation_subprocess_environment(
            candidate_root=project_root,
            validation_venv=venv_root,
            parent_environment=os.environ,
            temp_root=work,
        )
        environment["PIP_NO_INDEX"] = "1"
        environment["PIP_FIND_LINKS"] = str(wheel_dir)
        _run_toolchain_command(
            [
                str(venv_python(venv_root)),
                "-m",
                "pip",
                "install",
                "--no-index",
                "--find-links",
                str(wheel_dir),
                "--only-binary",
                ":all:",
                "--no-deps",
                "--force-reinstall",
                f"{frozen_asset_distribution}=={frozen_asset_version}",
            ],
            cwd=project_root,
            environment=environment,
            timeout_seconds=300,
            label="bound frozen wheel installation",
        )
        _remove_bytecode(venv_root)
        installed_version = subprocess.check_output(
            [
                str(venv_python(venv_root)),
                "-c",
                "import importlib.metadata, sys; print(importlib.metadata.version(sys.argv[1]))",
                frozen_asset_distribution,
            ],
            cwd=project_root,
            env=environment,
            text=True,
            shell=False,
        ).strip()
        if installed_version != frozen_asset_version:
            raise ValidationEnvironmentError("bound frozen wheel version mismatch")
        if installed_version != asset_summary["version"]:
            raise ValidationEnvironmentError("bound frozen wheel metadata mismatch")

    materialized_bytecode_count = sum(
        1
        for path in venv_root.rglob("*")
        if path.is_file() and path.suffix.lower() in {".pyc", ".pyo"}
    )
    if materialized_bytecode_count:
        raise ValidationEnvironmentError(
            "frozen toolchain materialization retained pre-import bytecode"
        )
    return project_root, venv_root, {
        "source_bytecode_count": source_bytecode_count,
        "materialized_bytecode_count": materialized_bytecode_count,
        "local_assets_only": True,
        "network_used": False,
        "frozen_asset": asset_summary,
    }


def materialize_trusted_source_venv(
    *,
    source_venv: Path,
    source_checkout: Path,
) -> dict[str, Any]:
    """Attach a disposable, bytecode-free venv to a clean source checkout.

    The trusted launcher contract measures ``<checkout>/.venv`` as part of
    its pre-import environment.  This helper copies the already selected
    frozen environment into a temporary clean checkout; it never writes to
    the source venv or to the serving checkout.
    """

    source = _real_path(source_venv)
    checkout = _real_path(source_checkout)
    if not source.is_dir() or not (source / "pyvenv.cfg").is_file():
        raise ValidationEnvironmentError("trusted source venv is unavailable")
    if not checkout.is_dir() or not (checkout / ".git").exists():
        raise ValidationEnvironmentError("trusted source checkout is unavailable")
    destination = checkout / ".venv"
    if destination.exists() or destination.is_symlink():
        raise ValidationEnvironmentError("trusted source venv destination already exists")
    if _is_within(source, checkout) or _is_within(destination, source):
        raise ValidationEnvironmentError("trusted source venv roots overlap")

    source_bytecode_count = sum(
        1
        for path in source.rglob("*")
        if path.is_file() and path.suffix.lower() in {".pyc", ".pyo"}
    )

    def ignore_bytecode(_directory: str, names: list[str]) -> set[str]:
        return {
            name
            for name in names
            if Path(name).suffix.lower() in {".pyc", ".pyo"}
        }

    try:
        shutil.copytree(
            source,
            destination,
            symlinks=True,
            ignore=ignore_bytecode,
        )
    except (OSError, shutil.Error) as exc:
        raise ValidationEnvironmentError(
            "trusted source venv materialization failed"
        ) from exc

    materialized_bytecode_count = sum(
        1
        for path in destination.rglob("*")
        if path.is_file() and path.suffix.lower() in {".pyc", ".pyo"}
    )
    if materialized_bytecode_count:
        raise ValidationEnvironmentError(
            "trusted source venv retained pre-import bytecode"
        )
    return {
        "source_bytecode_count": source_bytecode_count,
        "materialized_bytecode_count": materialized_bytecode_count,
        "local_assets_only": True,
        "network_used": False,
    }


def _verify_candidate_install(
    *,
    candidate_root: Path,
    validation_venv: Path,
    environment: Mapping[str, str],
    distribution_name: str | None,
    script_names: Sequence[str],
    forbidden_roots: Sequence[Path],
) -> dict[str, Any]:
    module_names = [
        name for name in _PACKAGE_MODULES if (candidate_root / name).is_dir()
    ]
    probe = r'''
import importlib
import importlib.metadata
import json
import os
import sys

candidate = os.path.realpath(sys.argv[1])
venv_root = os.path.realpath(sys.argv[2])
distribution_name = sys.argv[3]
module_names = json.loads(sys.argv[4])
script_names = json.loads(sys.argv[5])
forbidden_roots = [os.path.realpath(item) for item in json.loads(sys.argv[6])]

def within(path, root):
    try:
        return os.path.commonpath([os.path.realpath(path), root]) == root
    except ValueError:
        return False

def allowed_source(path):
    return within(path, candidate) or within(path, venv_root)

result = {
    "distribution_installed": False,
    "distribution_in_validation_venv": False,
    "distribution_metadata_in_validation_venv": False,
    "python_prefix_is_validation_venv": False,
    "modules_loaded": False,
    "modules_from_allowed_source": False,
    "forbidden_path_present": False,
    "console_scripts_generated": False,
}
try:
    result["python_prefix_is_validation_venv"] = within(sys.prefix, venv_root)
    distribution = importlib.metadata.distribution(distribution_name) if distribution_name else None
    if distribution is not None:
        result["distribution_installed"] = True
        result["distribution_in_validation_venv"] = within(distribution.locate_file(""), venv_root)
        result["distribution_metadata_in_validation_venv"] = within(
            getattr(distribution, "_path", ""),
            venv_root,
        )
    module_files = []
    for name in module_names:
        module = importlib.import_module(name)
        module_file = getattr(module, "__file__", None)
        if not isinstance(module_file, str):
            raise RuntimeError("module has no file")
        module_files.append(module_file)
    result["modules_loaded"] = len(module_files) == len(module_names)
    result["modules_from_allowed_source"] = all(allowed_source(item) for item in module_files)
    result["forbidden_path_present"] = any(
        within(item, root)
        for item in sys.path
        if item
        for root in forbidden_roots
    )
    script_dir = os.path.join(venv_root, "Scripts" if os.name == "nt" else "bin")
    script_paths = []
    for name in script_names:
        candidates = [os.path.join(script_dir, name)]
        if os.name == "nt":
            candidates.extend((os.path.join(script_dir, name + ".exe"), os.path.join(script_dir, name + ".cmd")))
        script_paths.append(any(os.path.isfile(item) for item in candidates))
    result["console_scripts_generated"] = bool(script_paths) and all(script_paths)
except Exception:
    pass

print(json.dumps(result, sort_keys=True))
'''
    command = [
        str(venv_python(validation_venv)),
        "-c",
        probe,
        str(candidate_root),
        str(validation_venv),
        distribution_name or "",
        json.dumps(module_names),
        json.dumps(list(script_names)),
        json.dumps([str(path) for path in forbidden_roots]),
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=candidate_root,
            env=dict(environment),
            capture_output=True,
            text=True,
            check=False,
            shell=False,
            timeout=60,
        )
        payload = json.loads(completed.stdout) if completed.returncode == 0 else {}
    except (OSError, subprocess.TimeoutExpired, ValueError, json.JSONDecodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    required = (
        (not distribution_name or payload.get("distribution_installed") is True)
        and (not distribution_name or payload.get("distribution_in_validation_venv") is True)
        and (not distribution_name or payload.get("distribution_metadata_in_validation_venv") is True)
        and payload.get("python_prefix_is_validation_venv") is True
        and payload.get("modules_loaded") is True
        and payload.get("modules_from_allowed_source") is True
        and payload.get("forbidden_path_present") is False
        and (not script_names or payload.get("console_scripts_generated") is True)
    )
    return {
        "candidate_package_expected": bool(distribution_name),
        "candidate_package_installed": payload.get("distribution_installed") is True if distribution_name else None,
        "distribution_in_validation_venv": payload.get("distribution_in_validation_venv"),
        "distribution_metadata_in_validation_venv": payload.get("distribution_metadata_in_validation_venv"),
        "python_prefix_is_validation_venv": payload.get("python_prefix_is_validation_venv"),
        "modules_loaded": payload.get("modules_loaded"),
        "modules_from_allowed_source": payload.get("modules_from_allowed_source"),
        "forbidden_path_present": payload.get("forbidden_path_present"),
        "candidate_module_provenance_verified": required,
        "console_script_verified": payload.get("console_scripts_generated") is True if script_names else None,
        "parent_import_path_leak": payload.get("forbidden_path_present") is True,
        "validation_environment_verified": required,
    }


def _read_distribution_version(
    python_executable: Path,
    *,
    environment: Mapping[str, str] | None,
    cwd: Path,
    distribution: str,
) -> str:
    """Read one installed distribution version without trusting command output."""

    try:
        completed = subprocess.run(
            [
                str(python_executable),
                "-c",
                "import importlib.metadata, sys; print(importlib.metadata.version(sys.argv[1]))",
                distribution,
            ],
            cwd=cwd,
            env=dict(environment) if environment is not None else None,
            capture_output=True,
            text=True,
            check=False,
            shell=False,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValidationEnvironmentError(
            "validation distribution version probe failed"
        ) from exc
    if completed.returncode != 0:
        raise ValidationEnvironmentError(
            "validation distribution version probe failed"
        )
    version = completed.stdout.strip()
    if not version:
        raise ValidationEnvironmentError(
            "validation distribution version probe was empty"
        )
    return version


def _canonical_json_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def canonical_installed_distribution_set(
    distributions: Sequence[Mapping[str, str]],
) -> tuple[dict[str, Any], str]:
    """Normalize one installed distribution set and return its canonical digest."""

    try:
        from packaging.utils import canonicalize_name
    except ImportError as exc:
        raise ValidationEnvironmentError(
            "candidate environment package-name authority is unavailable"
        ) from exc
    observed: dict[str, str] = {}
    for distribution in distributions:
        raw_name = distribution.get("canonical_name") or distribution.get("name")
        raw_version = distribution.get("version")
        if (
            not isinstance(raw_name, str)
            or not raw_name.strip()
            or not isinstance(raw_version, str)
            or not raw_version.strip()
        ):
            raise ValidationEnvironmentError(
                "candidate environment distribution identity is invalid"
            )
        name = canonicalize_name(raw_name.strip())
        version = raw_version.strip()
        previous = observed.get(name)
        if previous is not None and previous != version:
            raise ValidationEnvironmentError(
                "candidate environment contains conflicting distribution versions"
            )
        observed[name] = version
    payload = {
        "schema_version": "colameta.installed_distribution_set.v1",
        "distributions": [
            {"name": name, "version": observed[name]}
            for name in sorted(observed)
        ],
    }
    return payload, _canonical_json_sha256(payload)


def canonical_environment_identity(
    *,
    executable_sha256: str,
    python_implementation: str,
    python_version: str,
    python_cache_tag: str,
    package_set_sha256: str,
) -> tuple[dict[str, str], str]:
    """Return the closed identity for one materialized Candidate environment."""

    fields = {
        "executable_sha256": executable_sha256,
        "python_implementation": python_implementation,
        "python_version": python_version,
        "python_cache_tag": python_cache_tag,
        "package_set_sha256": package_set_sha256,
    }
    if any(
        not isinstance(value, str) or not value.strip()
        for value in fields.values()
    ):
        raise ValidationEnvironmentError(
            "candidate environment identity is incomplete"
        )
    return fields, _canonical_json_sha256(fields)


def _probe_installed_environment_identity(
    *,
    python_executable: Path,
    validation_venv: Path,
    candidate_root: Path,
    environment: Mapping[str, str],
) -> dict[str, Any]:
    """Measure Python and installed distributions using the target venv itself."""

    probe = r'''
import importlib.metadata
import json
import os
import platform
import sys

from packaging.utils import canonicalize_name

venv_root = os.path.realpath(sys.argv[1])

def within(path, root):
    try:
        return os.path.commonpath([os.path.realpath(path), root]) == root
    except (TypeError, ValueError):
        return False

distributions = []
for distribution in importlib.metadata.distributions():
    metadata_path = getattr(distribution, "_path", None)
    if metadata_path is None or not within(metadata_path, venv_root):
        raise RuntimeError("distribution metadata escaped validation venv")
    name = distribution.metadata.get("Name")
    version = distribution.version
    if not isinstance(name, str) or not name.strip() or not isinstance(version, str) or not version.strip():
        raise RuntimeError("distribution metadata identity is incomplete")
    distributions.append({
        "canonical_name": canonicalize_name(name),
        "version": version,
    })

print(json.dumps({
    "python": {
        "implementation": platform.python_implementation(),
        "version": platform.python_version(),
        "cache_tag": sys.implementation.cache_tag,
        "executable": sys.executable,
    },
    "packages": {"distributions": distributions},
}, sort_keys=True))
'''
    try:
        completed = subprocess.run(
            [str(python_executable), "-I", "-B", "-c", probe, str(validation_venv)],
            cwd=candidate_root,
            env=dict(environment),
            capture_output=True,
            text=True,
            check=False,
            shell=False,
            timeout=60,
        )
        payload = json.loads(completed.stdout) if completed.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationEnvironmentError(
            "candidate environment identity probe failed"
        ) from exc
    if not isinstance(payload, dict):
        raise ValidationEnvironmentError(
            "candidate environment identity probe failed"
        )
    python_payload = payload.get("python")
    packages_payload = payload.get("packages")
    if not isinstance(python_payload, dict) or not isinstance(packages_payload, dict):
        raise ValidationEnvironmentError(
            "candidate environment identity probe is incomplete"
        )
    executable = python_payload.get("executable")
    if (
        not isinstance(executable, str)
        or _real_path(Path(executable)) != _real_path(python_executable)
    ):
        raise ValidationEnvironmentError(
            "candidate environment executable identity mismatch"
        )
    distributions = packages_payload.get("distributions")
    if not isinstance(distributions, list) or not all(
        isinstance(item, dict) for item in distributions
    ):
        raise ValidationEnvironmentError(
            "candidate environment distribution set is invalid"
        )
    package_set, package_set_sha256 = canonical_installed_distribution_set(
        distributions
    )
    environment_identity, environment_identity_sha256 = canonical_environment_identity(
        executable_sha256=_sha256_file(python_executable),
        python_implementation=python_payload.get("implementation"),
        python_version=python_payload.get("version"),
        python_cache_tag=python_payload.get("cache_tag"),
        package_set_sha256=package_set_sha256,
    )
    return {
        **environment_identity,
        "package_set": package_set,
        "distribution_count": len(package_set["distributions"]),
        "environment_identity_sha256": environment_identity_sha256,
    }


def prepare_validation_environment(
    *,
    candidate_root: Path,
    work_root: Path,
    parent_environment: Mapping[str, str],
    forbidden_roots: Sequence[Path] = (),
    needs_python: bool,
    frozen_asset: Path | None = None,
    frozen_asset_filename: str | None = None,
    frozen_asset_sha256: str | None = None,
    frozen_asset_distribution: str = "cryptography",
    frozen_asset_version: str = "50.0.0",
) -> ValidationEnvironment:
    """Create a clean child environment and install the exact candidate wheel."""

    candidate = _real_path(candidate_root)
    work = _real_path(work_root)
    work.mkdir(parents=True, exist_ok=True)
    venv_dir: Path | None = None
    python_executable: Path | None = None
    initial_pip_version: str | None = None
    if needs_python:
        venv_dir = candidate / ".venv"
        if venv_dir.exists() or venv_dir.is_symlink():
            raise ValidationEnvironmentError("candidate validation overlay already exists")
        try:
            create_validation_venv(venv_dir)
        except (OSError, RuntimeError) as exc:
            raise ValidationEnvironmentError("validation virtualenv creation failed") from exc
        python_executable = venv_python(venv_dir)
        if not python_executable.is_file():
            raise ValidationEnvironmentError("validation Python executable was not created")

    environment = build_validation_subprocess_environment(
        candidate_root=candidate,
        validation_venv=venv_dir,
        parent_environment=parent_environment,
        temp_root=work,
        forbidden_roots=forbidden_roots,
    )
    distribution_name, script_names = _project_metadata(candidate)
    project_is_installable = _project_is_installable(candidate)
    candidate_distribution_name = distribution_name
    if needs_python and venv_dir is not None and python_executable is not None:
        wheelhouse = work / "wheelhouse"
        wheelhouse.mkdir(parents=True, exist_ok=True)
        builder_environment = build_validation_subprocess_environment(
            candidate_root=candidate,
            validation_venv=venv_dir,
            parent_environment=parent_environment,
            temp_root=work,
            forbidden_roots=forbidden_roots,
        )
        for command_environment in (environment, builder_environment):
            command_environment["PIP_CONFIG_FILE"] = os.devnull
            command_environment["PIP_INDEX_URL"] = _OFFICIAL_PYPI_INDEX_URL
            for key in (
                "PIP_EXTRA_INDEX_URL",
                "PIP_TRUSTED_HOST",
                "PIP_CONSTRAINT",
                "PIP_REQUIREMENT",
                "PIP_FIND_LINKS",
                "PIP_NO_INDEX",
            ):
                command_environment.pop(key, None)

        initial_pip_version = _read_distribution_version(
            python_executable,
            environment=environment,
            cwd=candidate,
            distribution="pip",
        )
        pip_commands: list[list[str]] = []

        def run_candidate_pip(
            arguments: Sequence[str],
            *,
            label: str,
            command_environment: Mapping[str, str],
            timeout_seconds: int = 300,
        ) -> None:
            command = [str(python_executable), "-m", "pip", *arguments]
            pip_commands.append(command)
            _run_toolchain_command(
                command,
                cwd=candidate,
                environment=command_environment,
                timeout_seconds=timeout_seconds,
                label=label,
            )

        candidate_pip_asset = resolve_candidate_pip_asset(parent_environment)
        if candidate_pip_asset is None:
            candidate_pip_asset = download_candidate_pip_asset(
                python_executable=python_executable,
                work_root=work,
                environment=environment,
            )
            download_command = candidate_pip_asset.pop("_pip_command", None)
            if isinstance(download_command, list):
                pip_commands.append(download_command)

        frozen_asset_summary: dict[str, Any] | None = None
        if frozen_asset is not None:
            if not frozen_asset_filename or not frozen_asset_sha256:
                raise ValidationEnvironmentError("frozen wheel asset binding is incomplete")
            frozen_asset_summary = verify_bound_wheel_asset(
                frozen_asset,
                expected_filename=frozen_asset_filename,
                expected_sha256=frozen_asset_sha256,
            )
        run_candidate_pip(
            [
                "install",
                "--index-url",
                _OFFICIAL_PYPI_INDEX_URL,
                "--no-index",
                "--no-deps",
                "--force-reinstall",
                "--no-cache-dir",
                str(candidate_pip_asset["path"]),
            ],
            label="candidate pip bootstrap upgrade",
            command_environment=environment,
        )
        selected_pip_version = _read_distribution_version(
            python_executable,
            environment=environment,
            cwd=candidate,
            distribution="pip",
        )
        if selected_pip_version != _CANDIDATE_PIP_VERSION:
            raise ValidationEnvironmentError(
                "candidate pip bootstrap version mismatch"
            )
        run_candidate_pip(
            [
                "install",
                "--index-url",
                _OFFICIAL_PYPI_INDEX_URL,
                "--no-input",
                "--no-cache-dir",
                *_VALIDATION_TOOL_REQUIREMENTS,
            ],
            label="candidate validation tool installation",
            command_environment=environment,
            timeout_seconds=_VALIDATION_TOOL_INSTALL_TIMEOUT_SECONDS,
        )
        candidate_wheel: Path | None = None
        if project_is_installable:
            run_candidate_pip(
                [
                    "wheel",
                    "--index-url",
                    _OFFICIAL_PYPI_INDEX_URL,
                    "--no-deps",
                    "--no-build-isolation",
                    "--no-cache-dir",
                    "--wheel-dir",
                    str(wheelhouse),
                    str(candidate),
                ],
                label="candidate wheel build",
                command_environment=builder_environment,
            )
            _clean_candidate_build_overlays(
                candidate_root=candidate,
                environment=builder_environment,
            )
            try:
                from packaging.utils import canonicalize_name
            except ImportError as exc:
                raise ValidationEnvironmentError(
                    "candidate wheel metadata is invalid"
                ) from exc
            candidate_wheels = []
            for path in wheelhouse.glob("*.whl"):
                wheel_name, _version, _tags, _metadata = _wheel_primary_metadata(path)
                if distribution_name is None or canonicalize_name(wheel_name) == canonicalize_name(distribution_name):
                    candidate_wheels.append(path)
            if len(candidate_wheels) != 1:
                raise ValidationEnvironmentError("candidate wheel build output is ambiguous")
            candidate_wheel = candidate_wheels[0]
            if candidate_distribution_name is None:
                candidate_distribution_name, _version, _tags, _metadata = _wheel_primary_metadata(
                    candidate_wheel
                )
            run_candidate_pip(
                [
                    "install",
                    "--index-url",
                    _OFFICIAL_PYPI_INDEX_URL,
                    "--no-input",
                    "--no-cache-dir",
                    "--force-reinstall",
                    str(candidate_wheel),
                ],
                label="candidate wheel installation",
                command_environment=environment,
            )
        if frozen_asset is not None:
            run_candidate_pip(
                [
                    "install",
                    "--index-url",
                    _OFFICIAL_PYPI_INDEX_URL,
                    "--no-index",
                    "--no-deps",
                    "--force-reinstall",
                    "--no-cache-dir",
                    str(frozen_asset),
                ],
                label="bound frozen cryptography installation",
                command_environment=environment,
            )
            installed_frozen_version = _read_distribution_version(
                python_executable,
                environment=environment,
                cwd=candidate,
                distribution=frozen_asset_distribution,
            )
            if installed_frozen_version != frozen_asset_version:
                raise ValidationEnvironmentError(
                    "bound frozen distribution version mismatch"
                )
        provenance = _verify_candidate_install(
            candidate_root=candidate,
            validation_venv=venv_dir,
            environment=environment,
            distribution_name=candidate_distribution_name,
            script_names=script_names,
            forbidden_roots=forbidden_roots,
        )
        if provenance.get("validation_environment_verified") is not True:
            raise ValidationEnvironmentError(
                "candidate validation environment provenance could not be verified"
            )
        _remove_bytecode(venv_dir)
        if frozen_asset_summary is not None:
            provenance["frozen_asset"] = {
                **frozen_asset_summary,
                "distribution": frozen_asset_distribution,
                "version": frozen_asset_version,
            }
        provenance["candidate_bootstrap"] = {
            "initial_pip_version": initial_pip_version,
            "selected_pip_version": selected_pip_version,
            "wheel_filename": candidate_pip_asset["filename"],
            "wheel_sha256": candidate_pip_asset["sha256"],
            "asset_verified": candidate_pip_asset["asset_verified"],
            "installed_offline": candidate_pip_asset["installed_offline"],
            "asset_source": (
                "local_bound"
                if candidate_pip_asset["installed_offline"]
                else "official_pypi"
            ),
            "network_used": candidate_pip_asset["network_used"],
            "runtime_dependency": candidate_pip_asset["runtime_dependency"],
        }
        provenance["candidate_pip_authority"] = {
            "sole_pip_executable": str(python_executable),
            "sole_pip_version": selected_pip_version,
            "bootstrap_pip_invocation_count": 1,
            "post_upgrade_parent_pip_invocation_count": 0,
            "pip_command_count": len(pip_commands),
            "all_commands_candidate_python": all(
                command[0] == str(python_executable) for command in pip_commands
            ),
            "all_online_index_urls_official": all(
                command[command.index("--index-url") + 1]
                == _OFFICIAL_PYPI_INDEX_URL
                for command in pip_commands
                if "--index-url" in command
            ),
            "extra_index_present": any(
                "--extra-index-url" in command for command in pip_commands
            ),
            "trusted_host_present": any(
                "--trusted-host" in command for command in pip_commands
            ),
            "build_isolation_disabled": any(
                "--no-build-isolation" in command for command in pip_commands
            ),
            "local_commands_no_index": all(
                "--no-index" in command for command in pip_commands
                if "--no-index" in command
            ),
            "network_used": any(
                "--index-url" in command and "--no-index" not in command
                for command in pip_commands
            ),
        }
        environment_identity = _probe_installed_environment_identity(
            python_executable=python_executable,
            validation_venv=venv_dir,
            candidate_root=candidate,
            environment=environment,
        )
        provenance.update(
            {
                "python_implementation": environment_identity[
                    "python_implementation"
                ],
                "python_version": environment_identity["python_version"],
                "python_cache_tag": environment_identity["python_cache_tag"],
                "package_set_sha256": environment_identity[
                    "package_set_sha256"
                ],
                "distribution_count": environment_identity[
                    "distribution_count"
                ],
                "environment_identity_sha256": environment_identity[
                    "environment_identity_sha256"
                ],
                "environment_identity": {
                    key: environment_identity[key]
                    for key in (
                        "executable_sha256",
                        "python_implementation",
                        "python_version",
                        "python_cache_tag",
                        "package_set_sha256",
                    )
                },
            }
        )
    else:
        provenance = {
            "candidate_package_expected": False,
            "candidate_package_installed": None,
            "distribution_in_validation_venv": None,
            "distribution_metadata_in_validation_venv": None,
            "python_prefix_is_validation_venv": None,
            "modules_loaded": None,
            "modules_from_allowed_source": None,
            "forbidden_path_present": False,
            "candidate_module_provenance_verified": None,
            "console_script_verified": None,
            "parent_import_path_leak": False,
            "validation_environment_verified": True,
        }

    blocked_keys_removed = all(
        key not in environment
        for key in _ENVIRONMENT_BLOCKLIST
        if key not in {
            "VIRTUAL_ENV",
            "PIP_CONFIG_FILE",
            "PIP_INDEX_URL",
        }
    )
    venv_path_first = (
        venv_dir is None
        or environment.get("PATH", "").split(os.pathsep)[0] == str(venv_bin_dir(venv_dir))
    )
    provenance.update(
        {
            "parent_pythonpath_removed": "PYTHONPATH" not in environment,
            "parent_pythonhome_removed": "PYTHONHOME" not in environment,
            "parent_virtualenv_rebuilt": venv_dir is None or environment.get("VIRTUAL_ENV") == str(venv_dir),
            "validation_venv_path_first": venv_path_first,
            "blocked_python_environment_keys_removed": blocked_keys_removed,
            "candidate_cwd_selected": environment.get("PWD") == str(candidate),
        }
    )
    return ValidationEnvironment(
        candidate_root=candidate,
        cwd=candidate,
        env=environment,
        venv_dir=venv_dir,
        python_executable=python_executable,
        summary=provenance,
    )
