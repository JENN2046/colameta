from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import runner.work_item_canary_runtime as canary_runtime
from runner.work_item_governance.activation import read_authoritative_token_file
from runner.work_item_governance.bootstrap import (
    PrivateTokenProvisioning,
    provision_private_bearer_token,
)
from runner.work_item_governance.errors import WorkItemGovernanceError
from runner.work_item_governance.source_binding import verify_runtime_source_artifacts
from runtime_artifact_helpers import prepare_exact_runtime_artifacts


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


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
