"""Isolated toolchain construction for candidate-bound validation runs.

The validation runner deliberately keeps this module small and explicit.  A
validation child process is given a newly constructed environment and, for
Python commands, a newly constructed virtual environment whose package is
built from the candidate checkout.  The parent process' import paths and
virtual-environment markers are never used as a source of Python code.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Mapping, Sequence
import venv


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
_TOOL_REQUIREMENTS = (
    "pytest>=9.0.3,<10",
    "ruff>=0.8,<1",
    "setuptools>=68",
    "wheel>=0.43",
)
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


def _project_metadata(candidate_root: Path) -> tuple[str | None, list[str]]:
    pyproject = candidate_root / "pyproject.toml"
    if not pyproject.is_file():
        return None, []
    try:
        import tomllib

        with pyproject.open("rb") as handle:
            project = tomllib.load(handle).get("project", {})
    except (OSError, ValueError, TypeError):
        return None, []
    if not isinstance(project, dict):
        return None, []
    name = project.get("name")
    scripts = project.get("scripts", {})
    script_names = [key for key in scripts if isinstance(key, str) and key.strip()] if isinstance(scripts, dict) else []
    return (name.strip() if isinstance(name, str) and name.strip() else None), script_names


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
    """Remove only ignored build outputs created while making the candidate wheel."""

    try:
        completed = subprocess.run(
            ["git", "clean", "-fdX"],
            cwd=candidate_root,
            env=dict(environment),
            capture_output=True,
            text=True,
            check=False,
            shell=False,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValidationEnvironmentError("candidate build overlay cleanup failed") from exc
    if completed.returncode != 0:
        raise ValidationEnvironmentError("candidate build overlay cleanup returned a failure")


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


def prepare_validation_environment(
    *,
    candidate_root: Path,
    work_root: Path,
    parent_environment: Mapping[str, str],
    forbidden_roots: Sequence[Path] = (),
    needs_python: bool,
) -> ValidationEnvironment:
    """Create a clean child environment and install the exact candidate wheel."""

    candidate = _real_path(candidate_root)
    work = _real_path(work_root)
    work.mkdir(parents=True, exist_ok=True)
    venv_dir: Path | None = None
    python_executable: Path | None = None
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
    if needs_python and venv_dir is not None and python_executable is not None:
        wheelhouse = work / "wheelhouse"
        wheelhouse.mkdir(parents=True, exist_ok=True)
        environment["PIP_FIND_LINKS"] = str(wheelhouse)
        builder_environment = build_validation_subprocess_environment(
            candidate_root=candidate,
            parent_environment=parent_environment,
            temp_root=work,
            forbidden_roots=forbidden_roots,
        )
        builder_environment["PIP_FIND_LINKS"] = str(wheelhouse)
        builder = Path(sys.executable)
        if distribution_name:
            _run_toolchain_command(
                [
                    str(builder),
                    "-m",
                    "pip",
                    "wheel",
                    "--wheel-dir",
                    str(wheelhouse),
                    str(candidate),
                ],
                cwd=candidate,
                environment=builder_environment,
                timeout_seconds=300,
                label="candidate wheel build",
            )
            _clean_candidate_build_overlays(
                candidate_root=candidate,
                environment=builder_environment,
            )
            try:
                create_validation_venv(venv_dir)
            except (OSError, RuntimeError) as exc:
                raise ValidationEnvironmentError(
                    "validation virtualenv recreation failed"
                ) from exc
            python_executable = venv_python(venv_dir)
        _run_toolchain_command(
            [
                str(builder),
                "-m",
                "pip",
                "wheel",
                "--wheel-dir",
                str(wheelhouse),
                *_TOOL_REQUIREMENTS,
            ],
            cwd=candidate,
            environment=builder_environment,
            timeout_seconds=300,
            label="validation tool wheel build",
        )
        install_names = list(_TOOL_REQUIREMENTS[-4:])
        if distribution_name:
            install_names.insert(0, distribution_name)
        _run_toolchain_command(
            [
                str(python_executable),
                "-m",
                "pip",
                "install",
                "--no-index",
                "--find-links",
                str(wheelhouse),
                *install_names,
            ],
            cwd=candidate,
            environment=environment,
            timeout_seconds=300,
            label="candidate/tool installation",
        )
        provenance = _verify_candidate_install(
            candidate_root=candidate,
            validation_venv=venv_dir,
            environment=environment,
            distribution_name=distribution_name,
            script_names=script_names,
            forbidden_roots=forbidden_roots,
        )
        if provenance.get("validation_environment_verified") is not True:
            raise ValidationEnvironmentError(
                "candidate validation environment provenance could not be verified"
            )
        _remove_bytecode(venv_dir)
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
        if key not in {"VIRTUAL_ENV", "PIP_FIND_LINKS"}
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
