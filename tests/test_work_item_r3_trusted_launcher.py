from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

from scripts import work_item_r3_trusted_launcher as launcher


def _clean_checkout(root: Path) -> Path:
    repository = root / "checkout"
    repository.mkdir()
    for name in ("runner", "adapters", "schemas", "scripts", "tests"):
        package = repository / name
        package.mkdir()
        (package / "tracked.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repository / "pyproject.toml").write_text("[build-system]\n", encoding="utf-8")
    (repository / "README.md").write_text("fixture\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", repository], check=True)
    subprocess.run(
        ["git", "-C", repository, "config", "user.email", "r3@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", repository, "config", "user.name", "R3"],
        check=True,
    )
    subprocess.run(["git", "-C", repository, "add", "."], check=True)
    subprocess.run(
        ["git", "-C", repository, "commit", "-qm", "fixture"], check=True
    )
    return repository


@pytest.mark.parametrize(
    "relative",
    (
        "sqlite3.py",
        "sqlite3/__init__.py",
        "runner/__pycache__/__init__.cpython-312.pyc",
        "sitecustomize.py",
        "ruff.toml",
        ".ruff.toml",
    ),
)
def test_preimport_source_measure_rejects_self_deleting_import_overlays(
    tmp_path: Path,
    relative: str,
) -> None:
    repository = _clean_checkout(tmp_path)
    overlay = repository / relative
    overlay.parent.mkdir(parents=True, exist_ok=True)
    overlay.write_bytes(b"overlay")

    with pytest.raises(RuntimeError, match="overlay"):
        launcher._measure_source_tree(repository)


def test_preimport_source_measure_rejects_hidden_index_flags(tmp_path: Path) -> None:
    repository = _clean_checkout(tmp_path)
    subprocess.run(
        [
            "git",
            "-C",
            repository,
            "update-index",
            "--assume-unchanged",
            "runner/tracked.py",
        ],
        check=True,
    )

    with pytest.raises(RuntimeError, match="hidden path flags"):
        launcher._measure_source_tree(repository)


def test_preimport_environment_measure_rejects_bytecode_and_special_entries(
    tmp_path: Path,
) -> None:
    venv = tmp_path / ".venv"
    site_packages = venv / "lib" / "python3.12" / "site-packages"
    site_packages.mkdir(parents=True)
    (venv / "bin").mkdir()
    (venv / "pyvenv.cfg").write_text("home = /usr\n", encoding="utf-8")
    bytecode = site_packages / "__pycache__" / "payload.pyc"
    bytecode.parent.mkdir()
    bytecode.write_bytes(b"payload")

    with pytest.raises(RuntimeError, match="pre-import bytecode"):
        launcher._measure_environment_tree(venv)

    bytecode.unlink()
    bytecode.parent.rmdir()
    fifo = site_packages / "loader.pipe"
    os.mkfifo(fifo)
    with pytest.raises(RuntimeError, match="special entry"):
        launcher._measure_environment_tree(venv)


def test_worktree_launcher_path_is_never_a_trusted_entrypoint(tmp_path: Path) -> None:
    project = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [
            "/usr/bin/python3.12",
            "-I",
            "-S",
            "-B",
            "scripts/work_item_r3_trusted_launcher.py",
            project.as_posix(),
            "protected-assets-check",
        ],
        cwd=project,
        env={"HOME": tmp_path.as_posix(), "PATH": "/usr/bin:/bin", "LC_ALL": "C"},
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 78
    assert "must be streamed from the exact Git blob" in completed.stderr
