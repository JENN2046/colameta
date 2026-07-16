from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


RUNTIME_PACKAGE_ROOTS = ("runner", "adapters", "schemas", "scripts")


def prepare_exact_runtime_artifacts(
    *,
    canary_root: Path,
    repository_root: Path,
) -> tuple[Path, Path, dict[str, str]]:
    """Clone real history, commit current runtime bytes, and build a matching Wheel."""

    checkout = canary_root / "source"
    wheel = canary_root / "artifacts" / "colameta-0.0.0-py3-none-any.whl"
    wheel.parent.mkdir(parents=True)
    _run_artifact_command(
        canary_root,
        "git",
        "clone",
        "-q",
        "--no-hardlinks",
        str(repository_root),
        str(checkout),
    )
    for package in RUNTIME_PACKAGE_ROOTS:
        shutil.rmtree(checkout / package)
        shutil.copytree(
            repository_root / package,
            checkout / package,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
        )
    _run_artifact_command(checkout, "git", "add", *RUNTIME_PACKAGE_ROOTS)
    if _run_artifact_command(checkout, "git", "status", "--porcelain", *RUNTIME_PACKAGE_ROOTS).strip():
        _run_artifact_command(
            checkout,
            "git",
            "-c",
            "user.name=R3 Test",
            "-c",
            "user.email=r3@example.invalid",
            "commit",
            "-qm",
            "exact runtime",
        )
    _run_artifact_command(
        checkout,
        sys.executable,
        "-m",
        "pip",
        "wheel",
        "--no-deps",
        "--no-build-isolation",
        "--no-cache-dir",
        "--wheel-dir",
        str(wheel.parent),
        ".",
    )
    built_wheels = tuple(sorted(wheel.parent.glob("colameta-*.whl")))
    if len(built_wheels) != 1:
        raise AssertionError(f"expected one ColaMeta Wheel, found {len(built_wheels)}")
    wheel = built_wheels[0]
    verification_script = """
import json, os
from runner.work_item_governance import activation as _activation
from runner.work_item_governance import bootstrap as _bootstrap
from runner.work_item_governance.source_binding import verify_runtime_source_artifacts
attestation = verify_runtime_source_artifacts(
    checkout_root=os.environ["SOURCE_CHECKOUT"],
    wheel_artifact=os.environ["WHEEL_ARTIFACT"],
)
print(json.dumps(attestation.source_binding, sort_keys=True))
"""
    completed = subprocess.run(  # noqa: S603 - isolated exact-checkout verifier
        [sys.executable, "-c", verification_script],
        cwd=checkout,
        env={
            **os.environ,
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": str(checkout),
            "SOURCE_CHECKOUT": str(checkout),
            "WHEEL_ARTIFACT": str(wheel),
        },
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    source_binding = json.loads(completed.stdout)
    assert isinstance(source_binding, dict)
    return checkout, wheel, source_binding


def _run_artifact_command(cwd: Path, *command: str) -> str:
    completed = subprocess.run(  # noqa: S603 - test-only fixed commands
        command,
        cwd=cwd,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    return completed.stdout
