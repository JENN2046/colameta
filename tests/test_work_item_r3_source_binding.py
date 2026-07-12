from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import warnings
import zipfile
from collections.abc import Callable
from pathlib import Path

import pytest

import runner.work_item_canary_runtime as canary_runtime
from runner.work_item_governance.activation import read_authoritative_token_file
from runner.work_item_governance.bootstrap import (
    PrivateTokenProvisioning,
    provision_private_bearer_token,
)
from runner.work_item_governance.errors import WorkItemGovernanceError
from runner.work_item_governance.source_binding import (
    _wheel_artifact_manifest,
    verify_runtime_source_artifacts,
)
from runtime_artifact_helpers import prepare_exact_runtime_artifacts


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def exact_wheel_artifacts(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    checkout, wheel, _binding = prepare_exact_runtime_artifacts(
        canary_root=tmp_path_factory.mktemp("exact-wheel"),
        repository_root=REPOSITORY_ROOT,
    )
    return checkout, wheel


def test_verifier_rejects_identical_modules_loaded_outside_exact_checkout(tmp_path: Path) -> None:
    checkout, wheel, _binding = prepare_exact_runtime_artifacts(
        canary_root=tmp_path,
        repository_root=REPOSITORY_ROOT,
    )

    with pytest.raises(WorkItemGovernanceError) as rejected:
        verify_runtime_source_artifacts(checkout_root=checkout, wheel_artifact=wheel)

    assert rejected.value.code == "RUNTIME_LOADED_CODE_OUTSIDE_CHECKOUT"


def test_verifier_requires_accepted_baseline_ancestry(tmp_path: Path) -> None:
    checkout, wheel, _binding = prepare_exact_runtime_artifacts(
        canary_root=tmp_path,
        repository_root=REPOSITORY_ROOT,
    )
    _run(checkout, "git", "checkout", "--orphan", "unrelated-history")
    _run(checkout, "git", "reset")
    _run(checkout, "git", "add", "runner", "adapters", "schemas", "scripts")
    _run(
        checkout,
        "git",
        "-c",
        "user.name=R3 Test",
        "-c",
        "user.email=r3@example.invalid",
        "commit",
        "-qm",
        "unrelated runtime",
    )
    script = r'''
import json, os
from runner.work_item_governance import activation as _activation
from runner.work_item_governance import bootstrap as _bootstrap
from runner.work_item_governance.errors import WorkItemGovernanceError
from runner.work_item_governance.source_binding import verify_runtime_source_artifacts
try:
 verify_runtime_source_artifacts(checkout_root=os.environ["CHECKOUT"],wheel_artifact=os.environ["WHEEL"])
except WorkItemGovernanceError as exc:
 code=exc.code
print(json.dumps({"code":code},sort_keys=True))
'''

    result = _run_checkout_python(checkout, wheel, script)

    assert result["code"] == "RUNTIME_SOURCE_BASELINE_INVALID"
def test_runtime_source_binding_is_measured_not_caller_asserted(tmp_path: Path) -> None:
    checkout, wheel, measured = prepare_exact_runtime_artifacts(
        canary_root=tmp_path,
        repository_root=REPOSITORY_ROOT,
    )
    assert measured["implementation_commit"] == _git(checkout, "rev-parse", "HEAD")
    assert measured["implementation_tree"] == _git(checkout, "rev-parse", "HEAD^{tree}")
    script = r'''
import json, os
from runner.work_item_governance import activation as _activation
from runner.work_item_governance import bootstrap as _bootstrap
from runner.work_item_governance.errors import WorkItemGovernanceError
from runner.work_item_governance.source_binding import verify_runtime_source_artifacts
measured=verify_runtime_source_artifacts(checkout_root=os.environ["CHECKOUT"],wheel_artifact=os.environ["WHEEL"])
try:
 verify_runtime_source_artifacts(checkout_root=os.environ["CHECKOUT"],wheel_artifact=os.environ["WHEEL"],expected_source_binding={"core_baseline_commit":"53d8939af22b019b2df2b555b85869ac39c5bba2","implementation_commit":"d"*40,"implementation_tree":"e"*40,"wheel_sha256":"f"*64})
except WorkItemGovernanceError as exc:
 code=exc.code
print(json.dumps({"code":code,"public":measured.public_evidence()},sort_keys=True))
'''
    result = _run_checkout_python(checkout, wheel, script)
    assert result["code"] == "RUNTIME_SOURCE_BINDING_MISMATCH"
    assert result["public"]["source_binding"] == measured
    assert result["public"]["baseline_is_ancestor"] is True
    assert result["public"]["loaded_modules_required_under_checkout"] is True
    assert result["public"]["verified"] is True


def test_runtime_source_verifier_scrubs_hostile_git_routing_environment(tmp_path: Path) -> None:
    checkout, wheel, measured = prepare_exact_runtime_artifacts(
        canary_root=tmp_path,
        repository_root=REPOSITORY_ROOT,
    )
    script = r'''
import json, os
from runner.work_item_governance import activation as _activation
from runner.work_item_governance import bootstrap as _bootstrap
from runner.work_item_governance.source_binding import verify_runtime_source_artifacts
result=verify_runtime_source_artifacts(checkout_root=os.environ["CHECKOUT"],wheel_artifact=os.environ["WHEEL"])
print(json.dumps({"binding":result.source_binding},sort_keys=True))
'''

    result = _run_checkout_python(
        checkout,
        wheel,
        script,
        extra_environment={
            "GIT_DIR": str(tmp_path / "attacker.git"),
            "GIT_WORK_TREE": str(tmp_path / "attacker-worktree"),
            "GIT_OBJECT_DIRECTORY": str(tmp_path / "attacker-objects"),
            "GIT_CONFIG_GLOBAL": str(tmp_path / "attacker-config"),
        },
    )

    assert result["binding"] == measured


@pytest.mark.parametrize(
    ("flag", "expected_code"),
    (
        ("--assume-unchanged", "RUNTIME_SOURCE_INDEX_FLAGS_FORBIDDEN"),
        ("--skip-worktree", "RUNTIME_SOURCE_INDEX_FLAGS_FORBIDDEN"),
    ),
)
def test_runtime_source_verifier_rejects_suppressed_index_paths(
    tmp_path: Path,
    flag: str,
    expected_code: str,
) -> None:
    checkout, wheel, _binding = prepare_exact_runtime_artifacts(
        canary_root=tmp_path,
        repository_root=REPOSITORY_ROOT,
    )
    _run(checkout, "git", "update-index", flag, "runner/work_item_governance/bootstrap.py")
    script = r'''
import json, os
from runner.work_item_governance import activation as _activation
from runner.work_item_governance import bootstrap as _bootstrap
from runner.work_item_governance.errors import WorkItemGovernanceError
from runner.work_item_governance.source_binding import verify_runtime_source_artifacts
try:
 verify_runtime_source_artifacts(checkout_root=os.environ["CHECKOUT"],wheel_artifact=os.environ["WHEEL"])
except WorkItemGovernanceError as exc:
 code=exc.code
print(json.dumps({"code":code},sort_keys=True))
'''

    result = _run_checkout_python(checkout, wheel, script)

    assert result["code"] == expected_code


@pytest.mark.parametrize(
    "relative_path",
    ("conftest.py", "pytest.py", "ruff.toml", ".ruff.toml"),
)
def test_runtime_source_verifier_rejects_ignored_top_level_overlay(
    tmp_path: Path,
    relative_path: str,
) -> None:
    checkout, wheel, _binding = prepare_exact_runtime_artifacts(
        canary_root=tmp_path,
        repository_root=REPOSITORY_ROOT,
    )
    exclude = checkout / ".git" / "info" / "exclude"
    exclude.write_text(
        exclude.read_text(encoding="utf-8") + f"\n/{relative_path}\n",
        encoding="utf-8",
    )
    (checkout / relative_path).write_text("pytest_plugins = []\n", encoding="utf-8")
    script = r'''
import json, os
from runner.work_item_governance import activation as _activation
from runner.work_item_governance import bootstrap as _bootstrap
from runner.work_item_governance.errors import WorkItemGovernanceError
from runner.work_item_governance.source_binding import verify_runtime_source_artifacts
try:
 verify_runtime_source_artifacts(checkout_root=os.environ["CHECKOUT"],wheel_artifact=os.environ["WHEEL"])
except WorkItemGovernanceError as exc:
 code=exc.code
print(json.dumps({"code":code},sort_keys=True))
'''

    result = _run_checkout_python(checkout, wheel, script)

    assert result["code"] == "RUNTIME_SOURCE_IGNORED_OVERLAY"


@pytest.mark.parametrize(
    "relative_path",
    (
        "runner/late_overlay.so",
        "runner/late_overlay.pyc",
        "runner/__pycache__/late_overlay.cpython-312.pyc",
    ),
)
def test_runtime_source_verifier_rejects_untracked_importable_overlay(
    tmp_path: Path,
    relative_path: str,
) -> None:
    checkout, wheel, _binding = prepare_exact_runtime_artifacts(
        canary_root=tmp_path,
        repository_root=REPOSITORY_ROOT,
    )
    target = checkout / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"unreviewed-importable-overlay")
    script = r'''
import json, os
from runner.work_item_governance import activation as _activation
from runner.work_item_governance import bootstrap as _bootstrap
from runner.work_item_governance.errors import WorkItemGovernanceError
from runner.work_item_governance.source_binding import verify_runtime_source_artifacts
try:
 verify_runtime_source_artifacts(checkout_root=os.environ["CHECKOUT"],wheel_artifact=os.environ["WHEEL"])
except WorkItemGovernanceError as exc:
 code=exc.code
print(json.dumps({"code":code},sort_keys=True))
'''

    result = _run_checkout_python(checkout, wheel, script)

    assert result["code"] == "RUNTIME_SOURCE_IGNORED_OVERLAY"


def test_claim_time_reverification_rejects_source_artifact_drift(tmp_path: Path) -> None:
    checkout, wheel, _binding = prepare_exact_runtime_artifacts(
        canary_root=tmp_path,
        repository_root=REPOSITORY_ROOT,
    )
    script = r'''
import json, os
from pathlib import Path
from runner.work_item_governance import activation as _activation
from runner.work_item_governance import bootstrap as _bootstrap
from runner.work_item_governance.errors import WorkItemGovernanceError
from runner.work_item_governance.preview import isoformat_utc, utc_now
from runner.work_item_governance.repository import SQLiteWorkItemLedger
from runner.work_item_governance.source_binding import reverify_runtime_source_binding,seal_runtime_source_attestation,verify_runtime_source_artifacts
checkout=Path(os.environ["CHECKOUT"]); project=Path(os.environ["PROJECT"]); project.mkdir()
attestation=verify_runtime_source_artifacts(checkout_root=checkout,wheel_artifact=os.environ["WHEEL"])
ledger=SQLiteWorkItemLedger(project); ledger.initialize()
with ledger.write_transaction() as connection:
 seal_runtime_source_attestation(connection,attestation,updated_at=isoformat_utc(utc_now()))
reverify_runtime_source_binding(ledger,expected_source_binding=attestation.source_binding)
target=checkout/"runner/work_item_governance/bootstrap.py"; target.write_bytes(target.read_bytes()+b"\n# drift\n")
try:
 reverify_runtime_source_binding(ledger,expected_source_binding=attestation.source_binding)
except WorkItemGovernanceError as exc:
 code=exc.code
print(json.dumps({"code":code},sort_keys=True))
'''
    result = _run_checkout_python(
        checkout,
        wheel,
        script,
        extra_environment={"PROJECT": str(tmp_path / "ledger-project")},
    )
    assert result["code"] == "RUNTIME_SOURCE_CHECKOUT_DIRTY"


def test_verified_wheel_manifest_includes_all_metadata_and_record(
    exact_wheel_artifacts: tuple[Path, Path],
) -> None:
    checkout, wheel = exact_wheel_artifacts
    inventory = _wheel_artifact_manifest(
        wheel,
        checkout=checkout,
        expected_runtime_names=_runtime_names(checkout),
    )

    assert set(inventory.member_manifest) > set(inventory.runtime_manifest)
    assert {
        "colameta-0.1.2.dist-info/METADATA",
        "colameta-0.1.2.dist-info/WHEEL",
        "colameta-0.1.2.dist-info/entry_points.txt",
        "colameta-0.1.2.dist-info/top_level.txt",
        "colameta-0.1.2.dist-info/RECORD",
    }.issubset(inventory.member_manifest)


@pytest.mark.parametrize(
    ("member_name", "expected_code"),
    (
        ("colameta-0.1.2.data/scripts/colameta", "RUNTIME_WHEEL_UNREVIEWED_EXECUTABLE"),
        ("../runner/escape.py", "RUNTIME_WHEEL_INVALID"),
        ("runner\\escape.py", "RUNTIME_WHEEL_INVALID"),
        ("runner/extra.pth", "RUNTIME_WHEEL_UNREVIEWED_EXECUTABLE"),
        ("colameta-0.1.2.dist-info/unknown.json", "RUNTIME_WHEEL_INVALID"),
    ),
)
def test_wheel_rejects_unreviewed_or_unsafe_members(
    tmp_path: Path,
    exact_wheel_artifacts: tuple[Path, Path],
    member_name: str,
    expected_code: str,
) -> None:
    checkout, wheel = exact_wheel_artifacts
    tampered = tmp_path / wheel.name
    _rewrite_wheel(wheel, tampered, additions=((member_name, b"unreviewed"),))

    _assert_wheel_rejected(checkout, tampered, expected_code)


def test_wheel_rejects_duplicate_and_case_colliding_members(
    tmp_path: Path,
    exact_wheel_artifacts: tuple[Path, Path],
) -> None:
    checkout, wheel = exact_wheel_artifacts
    duplicate = tmp_path / "duplicate" / wheel.name
    _rewrite_wheel(
        wheel,
        duplicate,
        additions=(("colameta-0.1.2.dist-info/METADATA", b"duplicate"),),
    )
    _assert_wheel_rejected(checkout, duplicate, "RUNTIME_WHEEL_INVALID")

    collision = tmp_path / "collision" / wheel.name
    _rewrite_wheel(wheel, collision, additions=(("RUNNER/__init__.py", b"collision"),))
    _assert_wheel_rejected(checkout, collision, "RUNTIME_WHEEL_INVALID")


def test_wheel_rejects_encrypted_member_flag(
    tmp_path: Path,
    exact_wheel_artifacts: tuple[Path, Path],
) -> None:
    checkout, wheel = exact_wheel_artifacts
    tampered = tmp_path / wheel.name
    data = bytearray(wheel.read_bytes())
    offset = data.find(b"PK\x01\x02")
    assert offset >= 0
    flags = int.from_bytes(data[offset + 8 : offset + 10], "little") | 0x1
    data[offset + 8 : offset + 10] = flags.to_bytes(2, "little")
    tampered.write_bytes(data)

    _assert_wheel_rejected(checkout, tampered, "RUNTIME_WHEEL_INVALID")


def test_wheel_rejects_abnormal_member_size_or_compression_ratio(
    tmp_path: Path,
    exact_wheel_artifacts: tuple[Path, Path],
) -> None:
    checkout, wheel = exact_wheel_artifacts
    tampered = tmp_path / wheel.name
    _rewrite_wheel(
        wheel,
        tampered,
        additions=(("runner/oversized.json", b"0" * (4 * 1024 * 1024 + 1)),),
    )

    _assert_wheel_rejected(checkout, tampered, "RUNTIME_WHEEL_INVALID")


def test_wheel_record_must_match_actual_member_digest_and_size(
    tmp_path: Path,
    exact_wheel_artifacts: tuple[Path, Path],
) -> None:
    checkout, wheel = exact_wheel_artifacts
    tampered = tmp_path / wheel.name
    _rewrite_wheel(
        wheel,
        tampered,
        replacements={"runner/__init__.py": b"# content changed without RECORD update\n"},
    )

    _assert_wheel_rejected(checkout, tampered, "RUNTIME_WHEEL_RECORD_INVALID")


@pytest.mark.parametrize(
    ("member_name", "replacement"),
    (
        (
            "colameta-0.1.2.dist-info/METADATA",
            lambda data: data.replace(b"Name: colameta\n", b"Name: colameta-evil\n", 1),
        ),
        (
            "colameta-0.1.2.dist-info/WHEEL",
            lambda data: data.replace(b"Tag: py3-none-any\n", b"Tag: cp311-cp311-linux_x86_64\n", 1),
        ),
        (
            "colameta-0.1.2.dist-info/entry_points.txt",
            lambda _data: b"[console_scripts]\ncolameta = runner.mcp_server:main\n",
        ),
    ),
)
def test_wheel_metadata_and_entry_points_remain_git_bound_even_with_rewritten_record(
    tmp_path: Path,
    exact_wheel_artifacts: tuple[Path, Path],
    member_name: str,
    replacement: Callable[[bytes], bytes],
) -> None:
    checkout, wheel = exact_wheel_artifacts
    with zipfile.ZipFile(wheel) as archive:
        original = archive.read(member_name)
    changed = replacement(original)
    assert isinstance(changed, bytes) and changed != original
    tampered = tmp_path / member_name.rsplit("/", 1)[-1] / wheel.name
    _rewrite_wheel(
        wheel,
        tampered,
        replacements={member_name: changed},
        rebuild_record=True,
    )

    _assert_wheel_rejected(checkout, tampered, "RUNTIME_WHEEL_METADATA_MISMATCH")


def test_static_token_material_cannot_claim_csprng_provisioning() -> None:
    deterministic = "mvr_" + base64.urlsafe_b64encode(bytes(range(32))).rstrip(b"=").decode("ascii")
    asserted = PrivateTokenProvisioning(
        token=deterministic,
        auth_file=Path("/tmp/not-authoritative-auth.json"),
        token_file_sha256="0" * 64,
        evidence_digest="1" * 64,
        entropy_bits=256,
        _seal=object(),
    )
    with pytest.raises(WorkItemGovernanceError) as rejected:
        asserted.require_trusted()
    assert rejected.value.code == "ACTIVATION_TOKEN_PROVENANCE_UNTRUSTED"


def test_token_file_reader_does_not_invent_csprng_provenance(tmp_path: Path) -> None:
    auth_file = tmp_path / "auth.json"
    token = "mvr_" + base64.urlsafe_b64encode(bytes(range(32))).rstrip(b"=").decode("ascii")
    auth_file.write_text(json.dumps({"auth_token": token}), encoding="utf-8")
    auth_file.chmod(0o600)

    _token, evidence = read_authoritative_token_file(auth_file)

    assert evidence["algorithm"] == "exact_auth_file_bytes_sha256"
    assert "csprng" not in json.dumps(evidence).lower()


def test_serve_failure_always_revokes_private_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "canary"
    for relative in ("home", "xdg-config", "xdg-state", "xdg-cache", "project"):
        path = root / relative
        path.mkdir(parents=True, mode=0o700)
        path.chmod(0o700)
    provisioning = provision_private_bearer_token(xdg_config_home=root / "xdg-config")
    for name, relative in (
        ("HOME", "home"),
        ("XDG_CONFIG_HOME", "xdg-config"),
        ("XDG_STATE_HOME", "xdg-state"),
        ("XDG_CACHE_HOME", "xdg-cache"),
    ):
        monkeypatch.setenv(name, str(root / relative))
    monkeypatch.setattr(canary_runtime, "local_principal_from_environment", lambda: None)

    with pytest.raises(WorkItemGovernanceError) as rejected:
        canary_runtime.serve_prepared_authoritative_canary(
            canary_root=root,
            project_root=root / "project",
            lease_id="activation_lease_missing",
            activation_envelope_path=root / "activation.json",
            claimed_activation_envelope_path=root / "claimed.json",
            port=48799,
        )

    assert rejected.value.code == "ACTIVATION_PRINCIPAL_CONFIGURATION_INVALID"
    assert not provisioning.auth_file.exists()


def _run_checkout_python(
    checkout: Path,
    wheel: Path,
    script: str,
    *,
    extra_environment: dict[str, str] | None = None,
) -> dict[str, object]:
    environment = {
        **os.environ,
        "PYTHONPATH": str(checkout),
        "PYTHONDONTWRITEBYTECODE": "1",
        "CHECKOUT": str(checkout),
        "WHEEL": str(wheel),
        **(extra_environment or {}),
    }
    completed = subprocess.run(  # noqa: S603 - isolated exact-checkout verifier
        [sys.executable, "-c", script],
        cwd=checkout,
        env=environment,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    result = json.loads(completed.stdout)
    assert isinstance(result, dict)
    return result


def _runtime_names(checkout: Path) -> tuple[str, ...]:
    return tuple(
        sorted(
            path.relative_to(checkout).as_posix()
            for root in ("runner", "adapters", "schemas", "scripts")
            for path in (checkout / root).rglob("*")
            if path.is_file()
            and "__pycache__" not in path.parts
            and (path.suffix in {".py", ".json"} or path.name == "py.typed")
        )
    )


def _assert_wheel_rejected(checkout: Path, wheel: Path, expected_code: str) -> None:
    with pytest.raises(WorkItemGovernanceError) as rejected:
        _wheel_artifact_manifest(
            wheel,
            checkout=checkout,
            expected_runtime_names=_runtime_names(checkout),
        )
    assert rejected.value.code == expected_code


def _rewrite_wheel(
    source: Path,
    destination: Path,
    *,
    replacements: dict[str, bytes] | None = None,
    additions: tuple[tuple[str, bytes], ...] = (),
    rebuild_record: bool = False,
) -> None:
    replacements = replacements or {}
    with zipfile.ZipFile(source) as archive:
        entries = [(info, replacements.get(info.filename, archive.read(info))) for info in archive.infolist()]
    if rebuild_record:
        record_name = "colameta-0.1.2.dist-info/RECORD"
        material = {info.filename: data for info, data in entries if info.filename != record_name}
        material.update(dict(additions))
        output = io.StringIO(newline="")
        writer = csv.writer(output, lineterminator="\n")
        for name, data in material.items():
            digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode("ascii")
            writer.writerow((name, f"sha256={digest}", str(len(data))))
        writer.writerow((record_name, "", ""))
        record_bytes = output.getvalue().encode("utf-8")
        entries = [
            (info, record_bytes if info.filename == record_name else data)
            for info, data in entries
        ]
    destination.parent.mkdir(parents=True, exist_ok=True)
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Duplicate name:", category=UserWarning)
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for info, data in entries:
                archive.writestr(info, data)
            for name, data in additions:
                archive.writestr(name, data)


def _git(checkout: Path, *arguments: str) -> str:
    return _run(checkout, "git", *arguments).strip()


def _run(cwd: Path, *command: str) -> str:
    completed = subprocess.run(  # noqa: S603 - test-only fixed argument vectors
        command,
        cwd=cwd,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return completed.stdout
