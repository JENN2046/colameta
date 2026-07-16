from __future__ import annotations

import base64
import csv
import hashlib
import io
import os
import re
import stat
import subprocess  # nosec B404
import sys
import zipfile
from dataclasses import dataclass, field
from email import policy
from email.parser import BytesParser
from pathlib import Path, PurePosixPath
from typing import Any, TYPE_CHECKING

from runner.work_item_governance.canonical import canonical_sha256, sha256_file
from runner.work_item_governance.errors import WorkItemGovernanceError

if TYPE_CHECKING:
    from runner.work_item_governance.repository import SQLiteWorkItemLedger


CORE_BASELINE_COMMIT = "53d8939af22b019b2df2b555b85869ac39c5bba2"
SOURCE_CHECKOUT_PATH_META_KEY = "authoritative_canary_source_checkout_path"
SOURCE_WHEEL_PATH_META_KEY = "authoritative_canary_wheel_artifact_path"
SOURCE_ARTIFACT_EVIDENCE_DIGEST_META_KEY = "authoritative_canary_source_artifact_evidence_digest"

_PACKAGE_ROOTS = ("runner", "adapters", "schemas", "scripts")
_SOURCE_SUFFIXES = (".py", ".json")
_BUILD_BINDING_FILES = ("pyproject.toml", "README.md")
_EXPECTED_PYPROJECT_SHA256 = "032627cfef03ae29d7dce5b6a36c89bff22157082e0813314becbac69a9180e7"
_EXPECTED_WHEEL_FILENAME = "colameta-0.1.2-py3-none-any.whl"
_EXPECTED_DIST_INFO = "colameta-0.1.2.dist-info"
_EXPECTED_ENTRY_POINTS = b"[console_scripts]\ncolameta = scripts.runner_cli:main\n"
_EXPECTED_TOP_LEVEL = b"adapters\nrunner\nschemas\nscripts\n"
_MAX_WHEEL_MEMBERS = 10_000
_MAX_WHEEL_MEMBER_BYTES = 4 * 1024 * 1024
_MAX_WHEEL_TOTAL_BYTES = 64 * 1024 * 1024
_MAX_WHEEL_COMPRESSION_RATIO = 200
_DIST_INFO_FILES = frozenset({"METADATA", "WHEEL", "entry_points.txt", "top_level.txt", "RECORD"})
_METADATA_HEADERS = {
    "metadata-version": ("2.4",),
    "name": ("colameta",),
    "version": ("0.1.2",),
    "summary": ("AI coding workflow harness connecting GPTs to local executors",),
    "license": ("禁止商业使用",),
    "project-url": ("Homepage, https://github.com/riccilnl/colameta",),
    "keywords": ("ai,coding,workflow,gpt,mcp",),
    "classifier": (
        "Development Status :: 3 - Alpha",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Programming Language :: Python :: 3.14",
    ),
    "requires-python": (">=3.10",),
    "description-content-type": ("text/markdown",),
    "requires-dist": (
        "jsonschema<5,>=4.23",
        "PyJWT[crypto]<3,>=2.8",
        'pytest<10,>=9.0.3; extra == "test"',
        'setuptools>=68; extra == "test"',
        'wheel>=0.43; extra == "test"',
        'bandit[toml]<2,>=1.7; extra == "quality"',
        'pip-audit<3,>=2.7; extra == "quality"',
        'pytest-cov<7,>=5; extra == "quality"',
        'ruff<1,>=0.8; extra == "quality"',
    ),
    "provides-extra": ("test", "quality"),
}
_CRITICAL_RUNTIME_FILES = frozenset(
    {
        "runner/mcp_server.py",
        "runner/work_item_canary_runtime.py",
        "runner/work_item_governance/activation.py",
        "runner/work_item_governance/bootstrap.py",
        "runner/work_item_governance/repository.py",
        "runner/work_item_governance/request_context.py",
        "runner/work_item_governance/service.py",
        "runner/work_item_governance/source_binding.py",
        "runner/work_item_governance/toolchain_binding.py",
    }
)
_RUNTIME_SOURCE_SEAL = object()
_TRUSTED_GIT_CANDIDATES = (Path("/usr/bin/git"), Path("/bin/git"))
_LOADER_AUTHORITY_PREFIXES = ("GIT_", "LD_", "DYLD_")
_LOADER_AUTHORITY_NAMES = frozenset(
    {
        "PYTHONHOME",
        "PYTHONUSERBASE",
        "PYTHONEXECUTABLE",
        "PYTHONCASEOK",
        "PYTHONPLATLIBDIR",
    }
)
_EXECUTION_OVERLAY_ROOTS = (*_PACKAGE_ROOTS, "tests")
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
_IGNORED_OVERLAY_CACHE_PARTS = frozenset(
    {".pytest_cache", ".mypy_cache", ".ruff_cache"}
)
_IGNORED_NON_EXECUTION_ROOTS = frozenset(
    {
        ".colameta",
        ".git",
        ".venv",
        "build",
        "dist",
        "docs",
        "colameta.egg-info",
    }
)
_IMPORTABLE_OVERLAY_SUFFIXES = (
    ".dll",
    ".dylib",
    ".pth",
    ".py",
    ".pyc",
    ".pyd",
    ".pyo",
    ".so",
)


@dataclass(frozen=True)
class _VerifiedWheelInventory:
    runtime_manifest: dict[str, str]
    member_manifest: dict[str, str]


@dataclass(frozen=True)
class _TrustedGit:
    executable: Path
    executable_sha256: str
    environment: dict[str, str]

    def run(self, checkout: Path, *arguments: str) -> str:
        try:
            completed = subprocess.run(  # nosec B603 -- root-owned measured system Git
                [
                    self.executable.as_posix(),
                    "--no-pager",
                    "--no-replace-objects",
                    "--literal-pathspecs",
                    "-c",
                    "core.fsmonitor=false",
                    "-c",
                    "core.untrackedCache=false",
                    "-C",
                    checkout.as_posix(),
                    *arguments,
                ],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=20,
                env=self.environment,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise WorkItemGovernanceError(
                "RUNTIME_SOURCE_GIT_UNAVAILABLE",
                "Exact Git object verification could not run.",
            ) from exc
        if completed.returncode != 0:
            raise WorkItemGovernanceError(
                "RUNTIME_SOURCE_GIT_INVALID",
                "Exact Git object verification failed.",
                details={"git_stderr": completed.stderr[-1000:]},
            )
        return completed.stdout

    def public_binding(self) -> dict[str, Any]:
        metadata = self.executable.stat()
        return {
            "resolved_path": self.executable.as_posix(),
            "sha256": self.executable_sha256,
            "owner_uid": metadata.st_uid,
            "mode": f"{stat.S_IMODE(metadata.st_mode):04o}",
            "root_owned": metadata.st_uid == 0,
            "group_or_other_writable": bool(metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH)),
        }


@dataclass(frozen=True)
class VerifiedRuntimeSourceBinding:
    """Process-local capability minted only after measuring real source artifacts."""

    source_binding: dict[str, str]
    checkout_root: Path
    wheel_artifact: Path
    evidence_digest: str
    file_manifest_digest: str
    _seal: object = field(repr=False, compare=False)

    def require_trusted(self) -> None:
        if self._seal is not _RUNTIME_SOURCE_SEAL:
            raise WorkItemGovernanceError(
                "RUNTIME_SOURCE_ATTESTATION_UNTRUSTED",
                "Runtime source binding was not minted by the artifact verifier.",
            )

    def public_evidence(self) -> dict[str, Any]:
        self.require_trusted()
        return {
            "schema_version": "work_item_runtime_source_attestation.v1",
            "source_binding": dict(self.source_binding),
            "file_manifest_digest": self.file_manifest_digest,
            "artifact_evidence_digest": self.evidence_digest,
            "checkout_path_digest": canonical_sha256(
                {"resolved_posix_path": self.checkout_root.as_posix()}
            ),
            "wheel_path_digest": canonical_sha256(
                {"resolved_posix_path": self.wheel_artifact.as_posix()}
            ),
            "baseline_object_present": True,
            "baseline_is_ancestor": True,
            "loaded_modules_required_under_checkout": True,
            "verified": True,
        }


def verify_runtime_source_artifacts(
    *,
    checkout_root: str | os.PathLike[str],
    wheel_artifact: str | os.PathLike[str],
    expected_source_binding: dict[str, str] | None = None,
) -> VerifiedRuntimeSourceBinding:
    """Measure Git objects, Wheel bytes and the Python files loaded by this process.

    Paths are selectors, not authority assertions.  All four public source-binding
    values are derived from local artifacts, and every package source file in the
    exact Git tree must have an identical Wheel member.  Every currently-loaded
    ColaMeta Python module is then compared to that exact file manifest.
    """

    checkout = Path(checkout_root).expanduser().resolve()
    wheel = Path(wheel_artifact).expanduser().resolve()
    if not checkout.is_dir() or not wheel.is_file() or wheel.suffix != ".whl":
        raise WorkItemGovernanceError(
            "RUNTIME_SOURCE_ARTIFACT_MISSING",
            "Runtime source verification requires an exact Git checkout and Wheel artifact.",
        )
    git = _trusted_git_for_checkout(checkout)
    commit = git.run(checkout, "rev-parse", "--verify", "HEAD^{commit}").strip()
    tree = git.run(checkout, "rev-parse", "--verify", "HEAD^{tree}").strip()
    try:
        git.run(checkout, "cat-file", "-e", f"{CORE_BASELINE_COMMIT}^{{commit}}")
        git.run(checkout, "merge-base", "--is-ancestor", CORE_BASELINE_COMMIT, commit)
    except WorkItemGovernanceError as exc:
        raise WorkItemGovernanceError(
            "RUNTIME_SOURCE_BASELINE_INVALID",
            "Exact checkout must contain the accepted core baseline and descend from it.",
        ) from exc
    checkout_state = _inspect_git_checkout(
        checkout,
        git=git,
        pathspecs=(*_PACKAGE_ROOTS, *_BUILD_BINDING_FILES),
    )
    if checkout_state["assume_unchanged_paths"] or checkout_state["skip_worktree_paths"]:
        raise WorkItemGovernanceError(
            "RUNTIME_SOURCE_INDEX_FLAGS_FORBIDDEN",
            "Runtime source paths may not suppress Git worktree verification.",
            details={
                "assume_unchanged_paths": checkout_state["assume_unchanged_paths"],
                "skip_worktree_paths": checkout_state["skip_worktree_paths"],
            },
        )
    if (
        checkout_state["ignored_execution_overlays"]
        or checkout_state["untracked_execution_overlays"]
    ):
        raise WorkItemGovernanceError(
            "RUNTIME_SOURCE_IGNORED_OVERLAY",
            "Untracked execution-relevant files are forbidden in the runtime checkout.",
            details={
                "ignored_paths": checkout_state["ignored_execution_overlays"],
                "untracked_paths": checkout_state["untracked_execution_overlays"],
            },
        )
    if checkout_state["object_mismatches"]:
        raise WorkItemGovernanceError(
            "RUNTIME_SOURCE_CHECKOUT_DIRTY",
            "Packaged runtime source differs from the exact Git object.",
            details={"changed_entries": checkout_state["object_mismatches"]},
        )
    dirty = git.run(
        checkout,
        "status",
        "--porcelain=v1",
        "--untracked-files=no",
        "--",
        *_PACKAGE_ROOTS,
        *_BUILD_BINDING_FILES,
    )
    if dirty.strip():
        raise WorkItemGovernanceError(
            "RUNTIME_SOURCE_CHECKOUT_DIRTY",
            "Packaged runtime source differs from the exact Git object.",
            details={"changed_entry_count": len(dirty.splitlines())},
        )
    tracked_names = git.run(
        checkout,
        "ls-tree",
        "-r",
        "--name-only",
        "HEAD",
        "--",
        *_PACKAGE_ROOTS,
    ).splitlines()
    expected_names = tuple(sorted(name for name in tracked_names if _is_runtime_source_name(name)))
    if not _CRITICAL_RUNTIME_FILES.issubset(expected_names):
        raise WorkItemGovernanceError(
            "RUNTIME_SOURCE_MANIFEST_INCOMPLETE",
            "Exact Git tree omits a required Authoritative Canary runtime file.",
        )
    filesystem_names = tuple(sorted(_filesystem_runtime_names(checkout)))
    if filesystem_names != expected_names:
        raise WorkItemGovernanceError(
            "RUNTIME_SOURCE_CHECKOUT_UNTRACKED",
            "Runtime checkout contains missing or untracked package source files.",
        )
    checkout_manifest = {name: sha256_file(checkout / name) for name in expected_names}
    if sha256_file(checkout / "pyproject.toml") != _EXPECTED_PYPROJECT_SHA256:
        raise WorkItemGovernanceError(
            "RUNTIME_BUILD_METADATA_POLICY_MISMATCH",
            "The exact Git build metadata differs from the reviewed Wheel metadata policy.",
        )
    wheel_inventory = _wheel_artifact_manifest(
        wheel,
        checkout=checkout,
        expected_runtime_names=expected_names,
    )
    if (
        set(wheel_inventory.runtime_manifest) != set(checkout_manifest)
        or wheel_inventory.runtime_manifest != checkout_manifest
    ):
        raise WorkItemGovernanceError(
            "RUNTIME_WHEEL_SOURCE_MISMATCH",
            "Wheel package files do not exactly match the Git runtime source manifest.",
            details={
                "git_file_count": len(checkout_manifest),
                "wheel_file_count": len(wheel_inventory.runtime_manifest),
            },
        )
    observed_loaded: dict[str, str] = {}
    for item in _loaded_colameta_files():
        path = _source_path(Path(item).expanduser().resolve())
        try:
            name = path.relative_to(checkout).as_posix()
        except ValueError as exc:
            raise WorkItemGovernanceError(
                "RUNTIME_LOADED_CODE_OUTSIDE_CHECKOUT",
                "Every loaded ColaMeta module must originate from the exact source checkout.",
                details={"loaded_path_digest": canonical_sha256({"resolved_posix_path": path.as_posix()})},
            ) from exc
        if not _is_runtime_source_name(name):
            raise WorkItemGovernanceError(
                "RUNTIME_LOADED_CODE_UNATTESTABLE",
                "A loaded ColaMeta module has no attestable source file.",
            )
        if name not in checkout_manifest or sha256_file(path) != checkout_manifest[name]:
            raise WorkItemGovernanceError(
                "RUNTIME_LOADED_CODE_MISMATCH",
                "Loaded ColaMeta code differs from the exact Git/Wheel artifact.",
                details={"module_file": name},
            )
        observed_loaded[name] = checkout_manifest[name]
    if not {
        "runner/work_item_governance/activation.py",
        "runner/work_item_governance/bootstrap.py",
        "runner/work_item_governance/source_binding.py",
    }.issubset(observed_loaded):
        raise WorkItemGovernanceError(
            "RUNTIME_LOADED_CODE_INCOMPLETE",
            "The source verifier could not attest its own loaded implementation modules.",
        )
    binding = {
        "core_baseline_commit": CORE_BASELINE_COMMIT,
        "implementation_commit": commit,
        "implementation_tree": tree,
        "wheel_sha256": sha256_file(wheel),
    }
    if expected_source_binding is not None and expected_source_binding != binding:
        raise WorkItemGovernanceError(
            "RUNTIME_SOURCE_BINDING_MISMATCH",
            "Caller-supplied source binding differs from measured runtime artifacts.",
            details={"measured_source_binding": binding},
        )
    file_manifest_digest = canonical_sha256(
        {
            "git_runtime_files": checkout_manifest,
            "git_build_inputs": {
                name: sha256_file(checkout / name) for name in _BUILD_BINDING_FILES
            },
            "wheel_members": wheel_inventory.member_manifest,
            "git_executable": git.public_binding(),
            "git_object_state_digest": checkout_state["manifest_digest"],
        }
    )
    evidence = {
        "source_binding": binding,
        "checkout_path": checkout.as_posix(),
        "wheel_path": wheel.as_posix(),
        "file_manifest_digest": file_manifest_digest,
        "git_executable": git.public_binding(),
        "git_object_state_digest": checkout_state["manifest_digest"],
    }
    if sha256_file(git.executable) != git.executable_sha256:
        raise WorkItemGovernanceError(
            "RUNTIME_SOURCE_GIT_CHANGED",
            "The trusted Git executable changed during runtime source verification.",
        )
    return VerifiedRuntimeSourceBinding(
        source_binding=binding,
        checkout_root=checkout,
        wheel_artifact=wheel,
        evidence_digest=canonical_sha256(evidence),
        file_manifest_digest=file_manifest_digest,
        _seal=_RUNTIME_SOURCE_SEAL,
    )


def seal_runtime_source_attestation(
    connection: Any,
    attestation: VerifiedRuntimeSourceBinding,
    *,
    updated_at: str,
) -> None:
    attestation.require_trusted()
    values = (
        (SOURCE_CHECKOUT_PATH_META_KEY, attestation.checkout_root.as_posix()),
        (SOURCE_WHEEL_PATH_META_KEY, attestation.wheel_artifact.as_posix()),
        (SOURCE_ARTIFACT_EVIDENCE_DIGEST_META_KEY, attestation.evidence_digest),
    )
    for key, value in values:
        connection.execute(
            """
            INSERT INTO ledger_meta(key,value,updated_at) VALUES(?,?,?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at
            """,
            (key, value, updated_at),
        )


def reverify_runtime_source_binding(
    ledger: SQLiteWorkItemLedger,
    *,
    expected_source_binding: dict[str, str],
) -> VerifiedRuntimeSourceBinding:
    with ledger.read_connection() as connection:
        rows = connection.execute(
            "SELECT key,value FROM ledger_meta WHERE key IN (?,?,?)",
            (
                SOURCE_CHECKOUT_PATH_META_KEY,
                SOURCE_WHEEL_PATH_META_KEY,
                SOURCE_ARTIFACT_EVIDENCE_DIGEST_META_KEY,
            ),
        ).fetchall()
    metadata = {str(row["key"]): str(row["value"]) for row in rows}
    if set(metadata) != {
        SOURCE_CHECKOUT_PATH_META_KEY,
        SOURCE_WHEEL_PATH_META_KEY,
        SOURCE_ARTIFACT_EVIDENCE_DIGEST_META_KEY,
    }:
        raise WorkItemGovernanceError(
            "RUNTIME_SOURCE_ATTESTATION_MISSING",
            "Fresh Ledger has no complete runtime source artifact attestation.",
        )
    attestation = verify_runtime_source_artifacts(
        checkout_root=metadata[SOURCE_CHECKOUT_PATH_META_KEY],
        wheel_artifact=metadata[SOURCE_WHEEL_PATH_META_KEY],
        expected_source_binding=expected_source_binding,
    )
    if attestation.evidence_digest != metadata[SOURCE_ARTIFACT_EVIDENCE_DIGEST_META_KEY]:
        raise WorkItemGovernanceError(
            "RUNTIME_SOURCE_EVIDENCE_MISMATCH",
            "Runtime source artifacts differ from their preflight attestation.",
        )
    return attestation


def _authority_sanitized_environment(
    environment: dict[str, str] | None = None,
) -> tuple[dict[str, str], tuple[str, ...]]:
    sanitized = dict(os.environ if environment is None else environment)
    removed = tuple(
        sorted(
            key
            for key in sanitized
            if key in _LOADER_AUTHORITY_NAMES
            or key.startswith(_LOADER_AUTHORITY_PREFIXES)
        )
    )
    for key in removed:
        sanitized.pop(key, None)
    sanitized.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C",
        }
    )
    return sanitized, removed


def _trusted_system_git(
    environment: dict[str, str] | None = None,
) -> _TrustedGit:
    if not sys.platform.startswith("linux"):
        raise WorkItemGovernanceError(
            "RUNTIME_SOURCE_GIT_UNTRUSTED",
            "Authoritative source verification requires the reviewed Linux system Git boundary.",
        )
    sanitized, _removed = _authority_sanitized_environment(environment)
    for candidate in _TRUSTED_GIT_CANDIDATES:
        try:
            resolved = candidate.resolve(strict=True)
            metadata = resolved.stat()
        except OSError:
            continue
        if (
            resolved.parent.as_posix() not in {"/usr/bin", "/bin"}
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != 0
            or metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
            or not metadata.st_mode & stat.S_IXUSR
            or not _root_owned_nonwritable_path(resolved.parent)
        ):
            continue
        return _TrustedGit(
            executable=resolved,
            executable_sha256=sha256_file(resolved),
            environment=sanitized,
        )
    raise WorkItemGovernanceError(
        "RUNTIME_SOURCE_GIT_UNTRUSTED",
        "No root-owned, non-writable system Git executable is available.",
    )


def _root_owned_nonwritable_path(path: Path) -> bool:
    current = path
    while True:
        try:
            metadata = current.stat()
        except OSError:
            return False
        if metadata.st_uid != 0 or metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            return False
        if current == current.parent:
            return True
        current = current.parent


def _trusted_git_for_checkout(
    checkout: Path,
    *,
    environment: dict[str, str] | None = None,
) -> _TrustedGit:
    requested = checkout.expanduser().resolve()
    git = _trusted_system_git(environment)
    top_level = git.run(requested, "rev-parse", "--show-toplevel").strip()
    try:
        observed = Path(top_level).expanduser().resolve(strict=True)
    except OSError as exc:
        raise WorkItemGovernanceError(
            "RUNTIME_SOURCE_CHECKOUT_ROOT_MISMATCH",
            "Git returned an unavailable checkout root.",
        ) from exc
    if observed != requested or git.run(requested, "rev-parse", "--is-inside-work-tree").strip() != "true":
        raise WorkItemGovernanceError(
            "RUNTIME_SOURCE_CHECKOUT_ROOT_MISMATCH",
            "Git source inspection must bind the exact requested checkout root.",
            details={
                "requested_path_digest": canonical_sha256(
                    {"resolved_posix_path": requested.as_posix()}
                ),
                "observed_path_digest": canonical_sha256(
                    {"resolved_posix_path": observed.as_posix()}
                ),
            },
        )
    return git


def _inspect_git_checkout(
    checkout: Path,
    *,
    git: _TrustedGit,
    pathspecs: tuple[str, ...],
    excluded_paths: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    object_format = git.run(checkout, "rev-parse", "--show-object-format").strip()
    if object_format not in {"sha1", "sha256"}:
        raise WorkItemGovernanceError(
            "RUNTIME_SOURCE_GIT_INVALID",
            "Git repository uses an unsupported object format.",
        )
    head = _parse_tree_entries(
        git.run(checkout, "ls-tree", "-rz", "--full-tree", "HEAD", "--", *pathspecs)
    )
    index, index_shape_errors = _parse_index_entries(
        git.run(checkout, "ls-files", "--stage", "-z", "--", *pathspecs)
    )
    flags = _parse_index_flags(
        git.run(checkout, "ls-files", "-v", "-z", "--", *pathspecs)
    )
    ignored = tuple(
        sorted(
            name
            for name in _nul_items(
                git.run(
                    checkout,
                    "ls-files",
                    "--others",
                    "--ignored",
                    "--exclude-standard",
                    "-z",
                )
            )
            if _is_ignored_execution_overlay(name)
        )
    )
    untracked = tuple(
        sorted(
            name
            for name in _nul_items(
                git.run(
                    checkout,
                    "ls-files",
                    "--others",
                    "--exclude-standard",
                    "-z",
                )
            )
            if _is_ignored_execution_overlay(name)
        )
    )
    head = {name: value for name, value in head.items() if name not in excluded_paths}
    index = {name: value for name, value in index.items() if name not in excluded_paths}
    assume_unchanged = tuple(
        sorted(name for name, tag in flags.items() if name not in excluded_paths and tag.islower())
    )
    skip_worktree = tuple(
        sorted(name for name, tag in flags.items() if name not in excluded_paths and tag.upper() == "S")
    )
    mismatches = list(index_shape_errors)
    if set(head) != set(index):
        mismatches.extend(sorted(set(head) ^ set(index)))
    manifest: dict[str, dict[str, str]] = {}
    for name in sorted(set(head) & set(index)):
        head_mode, head_type, head_oid = head[name]
        index_mode, index_oid = index[name]
        path = checkout / name
        try:
            worktree_mode, worktree_oid = _worktree_git_object(path, algorithm=object_format)
        except (OSError, ValueError):
            mismatches.append(name)
            continue
        if (
            head_type != "blob"
            or head_mode != index_mode
            or head_oid != index_oid
            or head_mode != worktree_mode
            or head_oid != worktree_oid
        ):
            mismatches.append(name)
            continue
        manifest[name] = {"mode": head_mode, "blob_oid": head_oid}
    unique_mismatches = tuple(sorted(set(mismatches)))
    return {
        "object_format": object_format,
        "tracked_path_count": len(head),
        "manifest_digest": canonical_sha256(manifest),
        "object_mismatches": list(unique_mismatches),
        "assume_unchanged_paths": list(assume_unchanged),
        "skip_worktree_paths": list(skip_worktree),
        "ignored_execution_overlays": list(ignored),
        "untracked_execution_overlays": list(untracked),
    }


def _parse_tree_entries(text: str) -> dict[str, tuple[str, str, str]]:
    entries: dict[str, tuple[str, str, str]] = {}
    for record in _nul_items(text):
        metadata, separator, name = record.partition("\t")
        fields = metadata.split()
        if not separator or len(fields) != 3 or name in entries:
            raise WorkItemGovernanceError(
                "RUNTIME_SOURCE_GIT_INVALID",
                "Git tree inventory is malformed or ambiguous.",
            )
        entries[name] = (fields[0], fields[1], fields[2])
    return entries


def _parse_index_entries(text: str) -> tuple[dict[str, tuple[str, str]], tuple[str, ...]]:
    entries: dict[str, tuple[str, str]] = {}
    errors: list[str] = []
    for record in _nul_items(text):
        metadata, separator, name = record.partition("\t")
        fields = metadata.split()
        if not separator or len(fields) != 3 or fields[2] != "0" or name in entries:
            errors.append(name or "<malformed-index-entry>")
            continue
        entries[name] = (fields[0], fields[1])
    return entries, tuple(sorted(errors))


def _parse_index_flags(text: str) -> dict[str, str]:
    flags: dict[str, str] = {}
    for record in _nul_items(text):
        if len(record) < 3 or record[1] != " ":
            raise WorkItemGovernanceError(
                "RUNTIME_SOURCE_GIT_INVALID",
                "Git index flag inventory is malformed.",
            )
        flags[record[2:]] = record[0]
    return flags


def _nul_items(text: str) -> tuple[str, ...]:
    return tuple(item for item in text.split("\0") if item)


def _worktree_git_object(path: Path, *, algorithm: str) -> tuple[str, str]:
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode):
        data = os.readlink(path).encode("utf-8", errors="surrogateescape")
        mode = "120000"
    elif stat.S_ISREG(metadata.st_mode):
        data = path.read_bytes()
        mode = "100755" if metadata.st_mode & 0o111 else "100644"
    else:
        raise ValueError("tracked worktree entry is not a regular file or symlink")
    digest = hashlib.new(algorithm)
    digest.update(f"blob {len(data)}\0".encode("ascii"))
    digest.update(data)
    return mode, digest.hexdigest()


def _is_ignored_execution_overlay(name: str) -> bool:
    path = PurePosixPath(name)
    if path.parts and path.parts[0] in _IGNORED_NON_EXECUTION_ROOTS:
        return False
    if any(part in _IGNORED_OVERLAY_CACHE_PARTS for part in path.parts):
        return False
    if path.name in _EXECUTION_CONFIG_NAMES or path.name == "conftest.py":
        return True
    if path.name.lower().endswith(_IMPORTABLE_OVERLAY_SUFFIXES):
        return True
    return bool(path.parts and path.parts[0] in _EXECUTION_OVERLAY_ROOTS)


def _git(checkout: Path, *arguments: str) -> str:
    requested = checkout.expanduser().resolve()
    return _trusted_git_for_checkout(requested).run(requested, *arguments)


def _wheel_artifact_manifest(
    wheel: Path,
    *,
    checkout: Path,
    expected_runtime_names: tuple[str, ...],
) -> _VerifiedWheelInventory:
    if wheel.name != _EXPECTED_WHEEL_FILENAME:
        raise WorkItemGovernanceError(
            "RUNTIME_WHEEL_INVALID",
            "Wheel filename does not match the reviewed distribution identity and compatibility tag.",
        )
    runtime_names = frozenset(expected_runtime_names)
    dist_info_names = frozenset(f"{_EXPECTED_DIST_INFO}/{name}" for name in _DIST_INFO_FILES)
    expected_names = runtime_names | dist_info_names
    member_bytes: dict[str, bytes] = {}
    try:
        with zipfile.ZipFile(wheel) as archive:
            members = archive.infolist()
            if archive.comment or len(members) > _MAX_WHEEL_MEMBERS:
                raise WorkItemGovernanceError(
                    "RUNTIME_WHEEL_INVALID",
                    "Wheel exceeds the Authoritative Canary inventory limits.",
                )
            total_size = 0
            normalized_names: set[str] = set()
            for info in members:
                name = _validated_wheel_member_name(info)
                normalized_name = name.casefold()
                if normalized_name in normalized_names:
                    raise WorkItemGovernanceError(
                        "RUNTIME_WHEEL_INVALID",
                        "Wheel contains duplicate or case-colliding member names.",
                    )
                normalized_names.add(normalized_name)
                total_size += info.file_size
                if (
                    info.file_size > _MAX_WHEEL_MEMBER_BYTES
                    or total_size > _MAX_WHEEL_TOTAL_BYTES
                    or (
                        info.file_size > 0
                        and info.file_size > max(info.compress_size, 1) * _MAX_WHEEL_COMPRESSION_RATIO
                    )
                ):
                    raise WorkItemGovernanceError(
                        "RUNTIME_WHEEL_INVALID",
                        "Wheel exceeds the Authoritative Canary inventory limits.",
                    )
                member_path = PurePosixPath(name)
                if any(part.endswith(".data") for part in member_path.parts):
                    raise WorkItemGovernanceError(
                        "RUNTIME_WHEEL_UNREVIEWED_EXECUTABLE",
                        "Wheel data installation schemes are forbidden for an Authoritative Canary.",
                    )
                if name not in expected_names:
                    code = (
                        "RUNTIME_WHEEL_UNREVIEWED_EXECUTABLE"
                        if member_path.suffix
                        in {".pth", ".so", ".dll", ".dylib", ".pyc", ".pyo", ".exe", ".sh"}
                        or member_path.suffix == ".py"
                        else "RUNTIME_WHEEL_INVALID"
                    )
                    raise WorkItemGovernanceError(
                        code,
                        "Wheel contains material outside the reviewed Git and metadata manifests.",
                    )
                member_bytes[name] = archive.read(info)
    except WorkItemGovernanceError:
        raise
    except (OSError, RuntimeError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise WorkItemGovernanceError(
            "RUNTIME_WHEEL_INVALID",
            "Runtime Wheel artifact is not a readable Wheel archive.",
        ) from exc
    if set(member_bytes) != expected_names:
        raise WorkItemGovernanceError(
            "RUNTIME_WHEEL_INVALID",
            "Wheel inventory does not exactly match the reviewed source and metadata manifests.",
            details={
                "expected_member_count": len(expected_names),
                "observed_member_count": len(member_bytes),
            },
        )
    _verify_wheel_record(member_bytes)
    _verify_wheel_metadata(member_bytes, checkout=checkout)
    member_manifest = {
        name: hashlib.sha256(data).hexdigest() for name, data in sorted(member_bytes.items())
    }
    return _VerifiedWheelInventory(
        runtime_manifest={name: member_manifest[name] for name in sorted(runtime_names)},
        member_manifest=member_manifest,
    )


def _validated_wheel_member_name(info: zipfile.ZipInfo) -> str:
    raw_name = info.filename
    try:
        raw_name.encode("ascii")
    except UnicodeEncodeError as exc:
        raise WorkItemGovernanceError(
            "RUNTIME_WHEEL_INVALID",
            "Wheel member paths must use the reviewed ASCII namespace.",
        ) from exc
    member_path = PurePosixPath(raw_name)
    name = member_path.as_posix()
    unix_mode = info.external_attr >> 16
    file_type = stat.S_IFMT(unix_mode)
    if (
        not raw_name
        or raw_name != name
        or raw_name.startswith(("/", "\\"))
        or "\\" in raw_name
        or ":" in raw_name
        or member_path.is_absolute()
        or not member_path.parts
        or any(part in {"", ".", ".."} for part in member_path.parts)
        or info.is_dir()
        or file_type not in {0, stat.S_IFREG}
        or info.flag_bits & 0x1
        or info.flag_bits & ~0x800
        or info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
        or info.extra
        or info.comment
    ):
        raise WorkItemGovernanceError(
            "RUNTIME_WHEEL_INVALID",
            "Wheel contains an unsafe or ambiguous member entry.",
        )
    return name


def _verify_wheel_record(member_bytes: dict[str, bytes]) -> None:
    record_name = f"{_EXPECTED_DIST_INFO}/RECORD"
    try:
        record_text = member_bytes[record_name].decode("utf-8")
        rows = tuple(csv.reader(io.StringIO(record_text, newline=""), strict=True))
    except (UnicodeDecodeError, csv.Error) as exc:
        raise WorkItemGovernanceError(
            "RUNTIME_WHEEL_RECORD_INVALID",
            "Wheel RECORD is not canonical UTF-8 CSV.",
        ) from exc
    observed: dict[str, tuple[str, str]] = {}
    for row in rows:
        if len(row) != 3 or row[0] in observed:
            raise WorkItemGovernanceError(
                "RUNTIME_WHEEL_RECORD_INVALID",
                "Wheel RECORD contains malformed or duplicate rows.",
            )
        observed[row[0]] = (row[1], row[2])
    if set(observed) != set(member_bytes) or observed.get(record_name) != ("", ""):
        raise WorkItemGovernanceError(
            "RUNTIME_WHEEL_RECORD_INVALID",
            "Wheel RECORD does not exactly enumerate the reviewed Wheel inventory.",
        )
    for name, data in member_bytes.items():
        if name == record_name:
            continue
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode("ascii")
        expected = (f"sha256={digest}", str(len(data)))
        if observed[name] != expected:
            raise WorkItemGovernanceError(
                "RUNTIME_WHEEL_RECORD_INVALID",
                "Wheel RECORD digest or size differs from the actual member bytes.",
                details={"member": name},
            )


def _verify_wheel_metadata(member_bytes: dict[str, bytes], *, checkout: Path) -> None:
    metadata = member_bytes[f"{_EXPECTED_DIST_INFO}/METADATA"]
    headers, body = _parse_mail_headers(metadata, kind="METADATA")
    if headers != _METADATA_HEADERS or body != (checkout / "README.md").read_bytes():
        raise WorkItemGovernanceError(
            "RUNTIME_WHEEL_METADATA_MISMATCH",
            "Wheel METADATA differs from the reviewed Git build metadata and README.",
        )
    wheel_headers, wheel_body = _parse_mail_headers(
        member_bytes[f"{_EXPECTED_DIST_INFO}/WHEEL"],
        kind="WHEEL",
    )
    generator = wheel_headers.pop("generator", ())
    if (
        wheel_headers
        != {
            "wheel-version": ("1.0",),
            "root-is-purelib": ("true",),
            "tag": ("py3-none-any",),
        }
        or len(generator) != 1
        or re.fullmatch(r"setuptools \([0-9]+(?:\.[0-9]+){1,3}\)", generator[0]) is None
        or wheel_body
    ):
        raise WorkItemGovernanceError(
            "RUNTIME_WHEEL_METADATA_MISMATCH",
            "Wheel compatibility metadata differs from the reviewed pure-Python policy.",
        )
    if (
        member_bytes[f"{_EXPECTED_DIST_INFO}/entry_points.txt"] != _EXPECTED_ENTRY_POINTS
        or member_bytes[f"{_EXPECTED_DIST_INFO}/top_level.txt"] != _EXPECTED_TOP_LEVEL
    ):
        raise WorkItemGovernanceError(
            "RUNTIME_WHEEL_METADATA_MISMATCH",
            "Wheel entry points or top-level packages differ from the reviewed runtime surface.",
        )


def _parse_mail_headers(data: bytes, *, kind: str) -> tuple[dict[str, tuple[str, ...]], bytes]:
    if b"\r" in data or b"\n\n" not in data:
        raise WorkItemGovernanceError(
            "RUNTIME_WHEEL_METADATA_MISMATCH",
            f"Wheel {kind} has a non-canonical header encoding.",
        )
    header_bytes, body = data.split(b"\n\n", 1)
    message = BytesParser(policy=policy.default).parsebytes(header_bytes + b"\n\n")
    if message.defects:
        raise WorkItemGovernanceError(
            "RUNTIME_WHEEL_METADATA_MISMATCH",
            f"Wheel {kind} contains malformed headers.",
        )
    header_names = {name.lower() for name in message.keys()}
    headers = {
        name: tuple(str(value) for value in message.get_all(name, failobj=[]))
        for name in sorted(header_names)
    }
    return headers, body


def _filesystem_runtime_names(checkout: Path) -> set[str]:
    names: set[str] = set()
    for root_name in _PACKAGE_ROOTS:
        root = checkout / root_name
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if path.is_symlink():
                raise WorkItemGovernanceError(
                    "RUNTIME_SOURCE_SYMLINK_FORBIDDEN",
                    "Runtime source manifest must not contain symbolic links.",
                )
            if path.is_file() and "__pycache__" not in path.parts:
                name = path.relative_to(checkout).as_posix()
                if _is_runtime_source_name(name):
                    names.add(name)
    return names


def _is_runtime_source_name(name: str) -> bool:
    path = PurePosixPath(name)
    if not path.parts or path.parts[0] not in _PACKAGE_ROOTS or ".." in path.parts:
        return False
    return path.suffix in _SOURCE_SUFFIXES or path.name == "py.typed"


def _loaded_colameta_files() -> tuple[str, ...]:
    files: set[str] = set()
    for name, module in tuple(sys.modules.items()):
        if not (name in _PACKAGE_ROOTS or name.startswith(tuple(f"{root}." for root in _PACKAGE_ROOTS))):
            continue
        module_file = getattr(module, "__file__", None)
        if isinstance(module_file, str):
            files.add(module_file)
    return tuple(sorted(files))


def _source_path(path: Path) -> Path:
    if path.suffix in {".pyc", ".pyo"}:
        candidate = path.parent.parent / f"{path.stem.split('.')[0]}.py"
        if candidate.is_file():
            return candidate.resolve()
    return path


__all__ = [
    "CORE_BASELINE_COMMIT",
    "VerifiedRuntimeSourceBinding",
    "reverify_runtime_source_binding",
    "seal_runtime_source_attestation",
    "verify_runtime_source_artifacts",
]
