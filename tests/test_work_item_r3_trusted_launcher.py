from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import sysconfig

import pytest

from scripts import work_item_r3_trusted_launcher as launcher


def _venv_purelib(venv: Path) -> Path:
    if os.name == "nt":
        return venv / "Lib" / "site-packages"
    return Path(
        sysconfig.get_path(
            "purelib",
            vars={"base": str(venv), "platbase": str(venv)},
        )
    )


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
    site_packages = _venv_purelib(venv)
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
            sys.executable,
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


def _asset_bound_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    payload: bytes = b"trusted-wheel-bytes",
) -> tuple[Path, Path, dict[str, object]]:
    repository = _clean_checkout(tmp_path)
    launcher_path = repository / "scripts" / "work_item_r3_trusted_launcher.py"
    launcher_path.write_bytes(Path(launcher.__file__).read_bytes())
    subprocess.run(["git", "-C", repository, "add", "."], check=True)
    subprocess.run(["git", "-C", repository, "commit", "-qm", "launcher"], check=True)
    receipt_path = repository.parent / "trusted-launcher-binding.json"
    toolchain_project = tmp_path / "frozen-toolchain-project"
    environment = toolchain_project / ".venv"
    (environment / "bin").mkdir(parents=True, exist_ok=True)
    _venv_purelib(environment).mkdir(parents=True, exist_ok=True)
    (environment / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
    filename = "cryptography-test.whl"
    asset = tmp_path / "assets" / filename
    asset.parent.mkdir()
    asset.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    trusted_asset = {
        "distribution": "cryptography",
        "version": "50.0.0",
        "filename": filename,
        "size": len(payload),
        "sha256": digest,
    }
    monkeypatch.setattr(launcher, "_TRUSTED_FROZEN_ASSET", trusted_asset)
    monkeypatch.setattr(launcher, "_TRUSTED_FROZEN_RECORD_SHA256", "f" * 64)
    monkeypatch.setattr(
        launcher,
        "_EXPECTED_ENVIRONMENT_TREE_SHA256",
        launcher._measure_environment_tree(environment)["environment_tree_sha256"],
    )
    head = subprocess.run(
        ["git", "-C", repository, "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    bindings: list[dict[str, object]] = []
    receipt: dict[str, object] = {
        "schema_version": "colameta.trusted_launcher_binding.v1",
        "candidate": {
            "head": head,
            "root": repository.resolve().as_posix(),
            "worktree_delta_sha256": launcher._canonical_sha256(bindings),
            "source_binding_sha256": launcher._canonical_sha256(bindings),
            "source_binding_count": 0,
            "source_binding_scope": "full_allowed_worktree_delta",
            "source_bindings": bindings,
        },
        "toolchain": {
            "project_root": toolchain_project.resolve().as_posix(),
            "environment_root": environment.resolve().as_posix(),
            "environment_root_sha256": launcher._EXPECTED_ENVIRONMENT_TREE_SHA256,
            "frozen_record_sha256": "f" * 64,
            "cryptography_version": "50.0.0",
            "frozen_asset": {"path": asset.as_posix(), **trusted_asset},
        },
        "launcher": {"path": "scripts/work_item_r3_trusted_launcher.py", "sha256": hashlib.sha256(launcher_path.read_bytes()).hexdigest()},
        "validation": {"preview_id": "fixture", "command_specs_sha256": "c" * 64, "lane": "host_frozen"},
    }
    receipt["receipt_sha256"] = launcher._canonical_sha256(
        {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    )
    receipt_path.write_text(json.dumps(receipt, sort_keys=True), encoding="utf-8")
    return repository, receipt_path, receipt


def test_frozen_asset_measurement_is_trusted_and_preimport_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, _receipt_path, receipt = _asset_bound_receipt(tmp_path, monkeypatch)
    source = Path(launcher.__file__).read_text(encoding="utf-8")
    assert "runner.work_item_governance.toolchain_binding" not in source
    measured = launcher._verify_bound_frozen_asset(repository, receipt)
    assert measured["authority_source"] == "trusted_launcher_binding"
    assert measured["sha256"] == receipt["toolchain"]["frozen_asset"]["sha256"]


def test_candidate_expected_hash_spoof_cannot_authorize_wrong_asset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, receipt_path, receipt = _asset_bound_receipt(tmp_path, monkeypatch)
    asset = Path(receipt["toolchain"]["frozen_asset"]["path"])
    asset.write_bytes(b"tampered-wheel")
    with pytest.raises(RuntimeError, match="identity mismatch|size mismatch|hash mismatch"):
        launcher._verify_bound_frozen_asset(repository, receipt)
    # Changing only the receipt's expected hash cannot override the trusted
    # launcher identity; the receipt digest remains valid but is rejected.
    tampered = json.loads(receipt_path.read_text(encoding="utf-8"))
    tampered["toolchain"]["frozen_asset"]["sha256"] = "0" * 64
    tampered["receipt_sha256"] = launcher._canonical_sha256(
        {key: value for key, value in tampered.items() if key != "receipt_sha256"}
    )
    receipt_path.write_text(json.dumps(tampered, sort_keys=True), encoding="utf-8")
    with pytest.raises(RuntimeError, match="identity mismatch"):
        launcher._verify_bound_frozen_asset(repository, tampered)


def test_frozen_asset_symlink_and_path_escape_are_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, _receipt_path, receipt = _asset_bound_receipt(tmp_path, monkeypatch)
    asset = Path(receipt["toolchain"]["frozen_asset"]["path"])
    link = asset.with_name("asset-link.whl")
    link.symlink_to(asset)
    receipt["toolchain"]["frozen_asset"]["path"] = link.as_posix()
    with pytest.raises(RuntimeError, match="path is unsafe"):
        launcher._verify_bound_frozen_asset(repository, receipt)
    escaped = repository / receipt["toolchain"]["frozen_asset"]["filename"]
    escaped.write_bytes(asset.read_bytes())
    receipt["toolchain"]["frozen_asset"]["path"] = escaped.as_posix()
    with pytest.raises(RuntimeError, match="overlaps protected root"):
        launcher._verify_bound_frozen_asset(repository, receipt)
