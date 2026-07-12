from __future__ import annotations

import os
import shutil
import subprocess  # nosec B404
import sys
import zipfile
from dataclasses import dataclass, field
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
    }
)
_RUNTIME_SOURCE_SEAL = object()


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
    commit = _git(checkout, "rev-parse", "--verify", "HEAD^{commit}").strip()
    tree = _git(checkout, "rev-parse", "--verify", "HEAD^{tree}").strip()
    try:
        _git(checkout, "cat-file", "-e", f"{CORE_BASELINE_COMMIT}^{{commit}}")
        _git(checkout, "merge-base", "--is-ancestor", CORE_BASELINE_COMMIT, commit)
    except WorkItemGovernanceError as exc:
        raise WorkItemGovernanceError(
            "RUNTIME_SOURCE_BASELINE_INVALID",
            "Exact checkout must contain the accepted core baseline and descend from it.",
        ) from exc
    dirty = _git(
        checkout,
        "status",
        "--porcelain=v1",
        "--untracked-files=no",
        "--",
        *_PACKAGE_ROOTS,
    )
    if dirty.strip():
        raise WorkItemGovernanceError(
            "RUNTIME_SOURCE_CHECKOUT_DIRTY",
            "Packaged runtime source differs from the exact Git object.",
            details={"changed_entry_count": len(dirty.splitlines())},
        )
    tracked_names = _git(
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
    wheel_manifest = _wheel_runtime_manifest(wheel)
    if set(wheel_manifest) != set(checkout_manifest) or wheel_manifest != checkout_manifest:
        raise WorkItemGovernanceError(
            "RUNTIME_WHEEL_SOURCE_MISMATCH",
            "Wheel package files do not exactly match the Git runtime source manifest.",
            details={
                "git_file_count": len(checkout_manifest),
                "wheel_file_count": len(wheel_manifest),
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
    file_manifest_digest = canonical_sha256(checkout_manifest)
    evidence = {
        "source_binding": binding,
        "checkout_path": checkout.as_posix(),
        "wheel_path": wheel.as_posix(),
        "file_manifest_digest": file_manifest_digest,
    }
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


def _git(checkout: Path, *arguments: str) -> str:
    git_executable = shutil.which("git")
    if git_executable is None:
        raise WorkItemGovernanceError(
            "RUNTIME_SOURCE_GIT_UNAVAILABLE",
            "Exact Git object verification requires the Git executable.",
        )
    environment = dict(os.environ)
    environment.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "LC_ALL": "C",
        }
    )
    try:
        completed = subprocess.run(  # nosec B603
            [git_executable, "-C", str(checkout), *arguments],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=20,
            env=environment,
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


def _wheel_runtime_manifest(wheel: Path) -> dict[str, str]:
    manifest: dict[str, str] = {}
    try:
        with zipfile.ZipFile(wheel) as archive:
            members = archive.infolist()
            if len(members) > 10_000 or sum(item.file_size for item in members) > 128 * 1024 * 1024:
                raise WorkItemGovernanceError(
                    "RUNTIME_WHEEL_INVALID",
                    "Wheel exceeds the Authoritative Canary inventory limits.",
                )
            for info in members:
                member_path = PurePosixPath(info.filename)
                name = member_path.as_posix()
                if member_path.is_absolute() or ".." in member_path.parts:
                    raise WorkItemGovernanceError(
                        "RUNTIME_WHEEL_INVALID",
                        "Wheel contains an unsafe member path.",
                    )
                if member_path.suffix in {".pth", ".so", ".dll", ".dylib", ".pyc", ".pyo"}:
                    raise WorkItemGovernanceError(
                        "RUNTIME_WHEEL_UNREVIEWED_EXECUTABLE",
                        "Wheel contains executable material outside the reviewed Python source manifest.",
                    )
                if member_path.suffix == ".py" and (
                    not member_path.parts or member_path.parts[0] not in _PACKAGE_ROOTS
                ):
                    raise WorkItemGovernanceError(
                        "RUNTIME_WHEEL_UNREVIEWED_EXECUTABLE",
                        "Wheel contains Python code outside the reviewed package roots.",
                    )
                if not _is_runtime_source_name(name):
                    continue
                if name in manifest or info.is_dir() or info.file_size > 4 * 1024 * 1024:
                    raise WorkItemGovernanceError(
                        "RUNTIME_WHEEL_INVALID",
                        "Wheel contains an invalid or duplicate runtime source member.",
                    )
                data = archive.read(info)
                import hashlib

                manifest[name] = hashlib.sha256(data).hexdigest()
    except (OSError, zipfile.BadZipFile) as exc:
        raise WorkItemGovernanceError(
            "RUNTIME_WHEEL_INVALID",
            "Runtime Wheel artifact is not a readable Wheel archive.",
        ) from exc
    return dict(sorted(manifest.items()))


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
