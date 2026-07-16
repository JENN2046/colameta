from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import runner.work_item_governance.pilot_candidate as candidate_module
import runner.work_item_governance.pilot as pilot_module
import runner.work_item_governance.pilot_authorization as authorization_module
from runner.work_item_governance.activation import canonical_path_digest
from runner.work_item_governance.canonical import canonical_sha256
from runner.work_item_governance.errors import WorkItemGovernanceError
from runner.work_item_governance.pilot_authorization import (
    PilotAuthorizationDecisionConsumer,
)
from runner.work_item_governance.pilot import (
    validate_pilot_conformance_authorization_source,
)
from runner.work_item_governance.pilot_candidate import (
    PilotCandidatePaths,
    derive_pilot_candidate_records,
    require_validated_pilot_candidate_for_authorization,
    serialize_pilot_candidate_records,
    validate_final_pilot_candidate_bytes,
    write_validated_pilot_candidate_records,
)


SHA = "a" * 64
CONFORMANCE_SHA = "9" * 64
SOURCE_BINDING = {
    "implementation_commit": "1" * 40,
    "implementation_tree": "2" * 40,
    "wheel_sha256": "3" * 64,
    "installed_inventory_sha256": "4" * 64,
}


def _records(tmp_path: Path) -> tuple[dict[str, object], ...]:
    project = tmp_path / "project"
    pilot = tmp_path / "pilot"
    paths = PilotCandidatePaths.from_roots(pilot_root=pilot, project_root=project)
    principal = {
        "principal_id": "candidate-operator",
        "principal_kind": "human",
        "session_ref": "candidate-session",
        "caller_auth_mode": "token",
        "principal_authenticated_by": "local_session",
        "permissions": ["work_item.accept"],
        "combined_operator_reviewer_role_explicitly_authorized": True,
    }
    execution = {
        "issuer": {"principal_id": "stale"},
        "scope": {
            "project_id": "stale",
            "project_snapshot_digest": SHA,
            "work_item_id": "stale",
            "allowed_read_path_manifest_digest": SHA,
            "allowed_write_path_manifest_digest": SHA,
            "protected_path_manifest_digest": SHA,
            "attempt_slot_schema_sha256": SHA,
            "executor_identity": "executor",
            "attempt_slots": [{"objective_digest": SHA}],
        },
    }
    scope = {
        "source_binding": {
            "implementation_commit": "stale",
            "implementation_tree": "stale",
            "wheel_sha256": SHA,
            "installed_inventory_sha256": SHA,
        },
        "target_project": {
            "project_id": "project-id",
            "project_root": "/stale",
            "project_root_path_digest": SHA,
            "project_snapshot_digest": "b" * 64,
            "allowed_read_path_manifest_digest": "c" * 64,
            "allowed_write_path_manifest_digest": "d" * 64,
            "protected_path_manifest_digest": "e" * 64,
        },
        "pilot_isolation": {"pilot_root": "/stale"},
        "principal_binding": {},
        "work_item_scope": {
            "objective_ref": "synthetic://candidate/objective",
            "objective_digest": SHA,
            "proposed_work_item_id": "wi_candidate",
        },
        "execution_scope": {
            "authorization_receipt_digest": SHA,
            "attempt_slot_schema_sha256": "f" * 64,
            "executor_identity": "executor",
        },
        "artifact_policy": {"allowed_root_path_digests": [SHA]},
        "window": {},
    }
    authorization = {
        "bindings": {},
        "principal": {},
        "target": {},
        "window": {},
        "source": {
            "implementation_commit": "stale",
            "implementation_tree": "stale",
            "wheel_sha256": SHA,
            "installed_inventory_sha256": SHA,
        },
    }
    derived = derive_pilot_candidate_records(
        principal_binding=principal,
        execution_authorization_receipt=execution,
        scope_envelope=scope,
        pilot_authorization=authorization,
        source_binding=SOURCE_BINDING,
        paths=paths,
        issued_at="2026-07-16T00:00:00Z",
        expires_at="2026-07-16T04:00:00Z",
        candidate_manifest_sha256="1" * 64,
        file_list_root_sha256="2" * 64,
        authentication_conformance_receipt_digest=CONFORMANCE_SHA,
    )
    return principal, execution, scope, authorization, paths, derived


def test_candidate_paths_use_production_canonical_path_digest(tmp_path: Path) -> None:
    paths = PilotCandidatePaths.from_roots(
        pilot_root=tmp_path / "pilot",
        project_root=tmp_path / "project",
    )
    digests = paths.path_digests()
    assert digests["pilot_root_path_digest"] == canonical_path_digest(paths.pilot_root)
    assert digests["project_root_path_digest"] == canonical_path_digest(paths.project_root)
    assert digests["project_root_path_digest"] != hashlib.sha256(
        str(paths.project_root).encode()
    ).hexdigest()


def test_generator_recomputes_all_mutable_cross_bindings(tmp_path: Path) -> None:
    _, _, _, _, paths, records = _records(tmp_path)
    execution = records["execution-authorization-receipt.json"]
    scope = records["scope-envelope.json"]
    authorization = records["PILOT_AUTHORIZATION_TEMPLATE.json"]
    objective_digest = canonical_sha256(scope["work_item_scope"]["objective_ref"])
    execution_digest = canonical_sha256(execution)
    scope_digest = canonical_sha256(scope)

    assert scope["target_project"]["project_root"] == str(paths.project_root)
    assert scope["target_project"]["project_root_path_digest"] == canonical_path_digest(
        paths.project_root
    )
    assert scope["pilot_isolation"]["pilot_root_path_digest"] == canonical_path_digest(
        paths.pilot_root
    )
    assert scope["work_item_scope"]["objective_digest"] == objective_digest
    assert execution["scope"]["attempt_slots"][0]["objective_digest"] == objective_digest
    assert scope["execution_scope"]["authorization_receipt_digest"] == execution_digest
    assert authorization["bindings"]["execution_authorization_receipt_digest"] == execution_digest
    assert (
        authorization["bindings"]["authentication_conformance_receipt_digest"]
        == CONFORMANCE_SHA
    )
    assert authorization["bindings"]["authorized_scope_digest"] == scope_digest
    assert authorization["bindings"]["scope_envelope_sha256"] == scope_digest
    assert {
        field: scope["source_binding"][field] for field in SOURCE_BINDING
    } == SOURCE_BINDING
    assert authorization["source"] == SOURCE_BINDING


def test_generator_requires_one_authoritative_source_binding(tmp_path: Path) -> None:
    principal, execution, scope, authorization, paths, _ = _records(tmp_path)
    with pytest.raises(WorkItemGovernanceError) as error:
        derive_pilot_candidate_records(
            principal_binding=principal,
            execution_authorization_receipt=execution,
            scope_envelope=scope,
            pilot_authorization=authorization,
            source_binding={**SOURCE_BINDING, "unreviewed_source": SHA},
            paths=paths,
            issued_at="2026-07-16T00:00:00Z",
            expires_at="2026-07-16T04:00:00Z",
            candidate_manifest_sha256="1" * 64,
            file_list_root_sha256="2" * 64,
            authentication_conformance_receipt_digest=CONFORMANCE_SHA,
        )
    assert error.value.code == "PILOT_CANDIDATE_SOURCE_BINDING_INVALID"


def test_conformance_source_must_match_authorization_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _, _, _, _, _, records = _records(tmp_path)
    authorization = records["PILOT_AUTHORIZATION_TEMPLATE.json"]
    scope = records["scope-envelope.json"]
    receipt = {"source_binding": dict(SOURCE_BINDING)}
    authorization["bindings"]["authentication_conformance_receipt_digest"] = (
        canonical_sha256(receipt)
    )
    monkeypatch.setattr(pilot_module, "validate_governance_record", lambda *args: None)

    validate_pilot_conformance_authorization_source(
        authorization,
        scope_envelope=scope,
        authentication_conformance_receipt=receipt,
    )
    receipt["source_binding"]["implementation_commit"] = "5" * 40
    with pytest.raises(WorkItemGovernanceError) as error:
        validate_pilot_conformance_authorization_source(
            authorization,
            scope_envelope=scope,
            authentication_conformance_receipt=receipt,
        )
    assert error.value.code == "PILOT_AUTHENTICATION_SOURCE_BINDING_MISMATCH"
    assert error.value.details["failed_bindings"] == [
        "conformance_receipt_digest",
        "conformance_to_authorization:implementation_commit",
        "conformance_to_scope:implementation_commit",
    ]


def test_authorization_consumer_cross_checks_conformance_source_before_consumption(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _, _, _, _, _, records = _records(tmp_path)
    for name in (
        "validate_execution_authorization_receipt",
        "validate_pilot_scope_envelope",
        "validate_pilot_authorization",
    ):
        monkeypatch.setattr(candidate_module, name, lambda *args, **kwargs: None)
    candidate_dir = tmp_path / "candidate"
    write_validated_pilot_candidate_records(candidate_dir, records)
    decision_path = tmp_path / "decision.json"
    decision_path.write_text(
        json.dumps(records["PILOT_AUTHORIZATION_TEMPLATE.json"]), encoding="utf-8"
    )
    decision_path.chmod(0o600)

    def reject_source(*args: object, **kwargs: object) -> None:
        raise WorkItemGovernanceError(
            "PILOT_AUTHENTICATION_SOURCE_BINDING_MISMATCH", "rejected"
        )

    monkeypatch.setattr(
        authorization_module,
        "validate_pilot_conformance_authorization_source",
        reject_source,
    )
    consumer = PilotAuthorizationDecisionConsumer(
        candidate_dir=candidate_dir,
        decision_path=decision_path,
        tombstone_path=tmp_path / "decision.tombstone.json",
        ledger=object(),  # type: ignore[arg-type]
    )
    with pytest.raises(WorkItemGovernanceError) as error:
        consumer.consume(
            scope_envelope=records["scope-envelope.json"],
            execution_authorization_receipt=records[
                "execution-authorization-receipt.json"
            ],
            preflight_receipt={},
            authentication_conformance_receipt={},
            preflight_semantic_validation_receipt={},
            expected_authorization_digest=canonical_sha256(
                records["PILOT_AUTHORIZATION_TEMPLATE.json"]
            ),
        )
    assert error.value.code == "PILOT_AUTHENTICATION_SOURCE_BINDING_MISMATCH"
    assert decision_path.is_file()
    assert not consumer.tombstone_path.exists()


def test_final_byte_validator_checks_exact_serialized_records(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _, _, _, _, _, records = _records(tmp_path)
    calls: list[str] = []
    monkeypatch.setattr(
        candidate_module,
        "validate_execution_authorization_receipt",
        lambda value: calls.append("execution") or value,
    )
    monkeypatch.setattr(
        candidate_module,
        "validate_pilot_scope_envelope",
        lambda value, **kwargs: calls.append("scope") or value,
    )
    monkeypatch.setattr(
        candidate_module,
        "validate_pilot_authorization",
        lambda value, **kwargs: calls.append("authorization") or value,
    )
    payloads = serialize_pilot_candidate_records(records)
    receipt = validate_final_pilot_candidate_bytes(payloads)
    assert calls == ["execution", "scope", "authorization"]
    assert receipt["execution_authorization"] == "PASS"
    assert receipt["authentication_conformance_receipt_digest"] == CONFORMANCE_SHA

    noncanonical = dict(payloads)
    value = json.loads(noncanonical["scope-envelope.json"])
    noncanonical["scope-envelope.json"] = json.dumps(value).encode()
    with pytest.raises(WorkItemGovernanceError) as error:
        validate_final_pilot_candidate_bytes(noncanonical)
    assert error.value.code == "PILOT_CANDIDATE_BYTES_NOT_CANONICAL"


def test_writer_validates_before_and_after_persisting_final_bytes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _, _, _, _, _, records = _records(tmp_path)
    calls: list[str] = []
    monkeypatch.setattr(
        candidate_module,
        "validate_execution_authorization_receipt",
        lambda value: calls.append("execution") or value,
    )
    monkeypatch.setattr(
        candidate_module,
        "validate_pilot_scope_envelope",
        lambda value, **kwargs: calls.append("scope") or value,
    )
    monkeypatch.setattr(
        candidate_module,
        "validate_pilot_authorization",
        lambda value, **kwargs: calls.append("authorization") or value,
    )
    output = tmp_path / "candidate"
    receipt = write_validated_pilot_candidate_records(output, records)
    assert receipt["validation"]["scope_envelope"] == "PASS"
    assert calls == [
        "execution",
        "scope",
        "authorization",
        "execution",
        "scope",
        "authorization",
    ]
    assert {path.name for path in output.iterdir()} == {
        "execution-authorization-receipt.json",
        "scope-envelope.json",
        "PILOT_AUTHORIZATION_TEMPLATE.json",
        "PILOT_CANDIDATE_VALIDATION_RECEIPT.json",
    }
    authorization_receipt = require_validated_pilot_candidate_for_authorization(output)
    assert authorization_receipt == receipt
    assert calls[-3:] == ["execution", "scope", "authorization"]


def test_writer_leaves_no_candidate_when_production_validation_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _, _, _, _, _, records = _records(tmp_path)
    monkeypatch.setattr(
        candidate_module,
        "validate_execution_authorization_receipt",
        lambda value: value,
    )

    def reject(*args: object, **kwargs: object) -> None:
        raise WorkItemGovernanceError("PILOT_SCOPE_DIGEST_MISMATCH", "rejected")

    monkeypatch.setattr(candidate_module, "validate_pilot_scope_envelope", reject)
    output = tmp_path / "candidate"
    with pytest.raises(WorkItemGovernanceError):
        write_validated_pilot_candidate_records(output, records)
    assert not output.exists()


def test_authorization_precheck_rejects_changed_final_bytes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _, _, _, _, _, records = _records(tmp_path)
    monkeypatch.setattr(
        candidate_module,
        "validate_execution_authorization_receipt",
        lambda value: value,
    )
    monkeypatch.setattr(
        candidate_module,
        "validate_pilot_scope_envelope",
        lambda value, **kwargs: value,
    )
    monkeypatch.setattr(
        candidate_module,
        "validate_pilot_authorization",
        lambda value, **kwargs: value,
    )
    output = tmp_path / "candidate"
    write_validated_pilot_candidate_records(output, records)
    scope = output / "scope-envelope.json"
    scope.write_bytes(scope.read_bytes() + b"\n")
    with pytest.raises(WorkItemGovernanceError) as error:
        require_validated_pilot_candidate_for_authorization(output)
    assert error.value.code == "PILOT_CANDIDATE_BYTES_NOT_CANONICAL"


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ("forged_receipt", "PILOT_CANDIDATE_VALIDATION_RECEIPT_MISMATCH"),
        ("tampered_bytes", "PILOT_CANDIDATE_BYTES_NOT_CANONICAL"),
        ("missing_receipt", "PILOT_CANDIDATE_AUTHORIZATION_FILE_SET_MISMATCH"),
        ("symlink_directory", "PILOT_CANDIDATE_OUTPUT_NOT_PRIVATE"),
        ("symlink_ancestor", "PILOT_CANDIDATE_OUTPUT_NOT_PRIVATE"),
        ("invalid_json", "PILOT_CANDIDATE_JSON_INVALID"),
        ("duplicate_json_key", "PILOT_CANDIDATE_JSON_INVALID"),
        ("symlink_file", "PILOT_CANDIDATE_AUTHORIZATION_FILE_INVALID"),
    ],
)
def test_unvalidated_candidate_cannot_enter_authorization_or_consumption(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mutation: str,
    expected_code: str,
) -> None:
    _, _, _, _, _, records = _records(tmp_path)
    monkeypatch.setattr(
        candidate_module,
        "validate_execution_authorization_receipt",
        lambda value: value,
    )
    monkeypatch.setattr(
        candidate_module,
        "validate_pilot_scope_envelope",
        lambda value, **kwargs: value,
    )
    monkeypatch.setattr(
        candidate_module,
        "validate_pilot_authorization",
        lambda value, **kwargs: value,
    )
    output = tmp_path / "candidate"
    write_validated_pilot_candidate_records(output, records)
    candidate_path = output
    receipt_path = output / "PILOT_CANDIDATE_VALIDATION_RECEIPT.json"
    if mutation == "forged_receipt":
        receipt_path.write_bytes(b'{"result":"PASS"}\n')
    elif mutation == "tampered_bytes":
        scope_path = output / "scope-envelope.json"
        scope_path.write_bytes(scope_path.read_bytes() + b"\n")
    elif mutation == "missing_receipt":
        receipt_path.unlink()
    elif mutation == "symlink_directory":
        candidate_path = tmp_path / "candidate-link"
        candidate_path.symlink_to(output, target_is_directory=True)
    elif mutation == "symlink_ancestor":
        linked_parent = tmp_path / "candidate-parent-link"
        linked_parent.symlink_to(tmp_path, target_is_directory=True)
        candidate_path = linked_parent / "candidate"
    elif mutation == "invalid_json":
        (output / "scope-envelope.json").write_bytes(b"{")
    elif mutation == "duplicate_json_key":
        (output / "scope-envelope.json").write_bytes(b'{"scope":1,"scope":2}\n')
    else:
        scope_path = output / "scope-envelope.json"
        external_scope = tmp_path / "external-scope.json"
        external_scope.write_bytes(scope_path.read_bytes())
        external_scope.chmod(0o600)
        scope_path.unlink()
        scope_path.symlink_to(external_scope)

    with pytest.raises(WorkItemGovernanceError) as signing_error:
        require_validated_pilot_candidate_for_authorization(candidate_path)
    assert signing_error.value.code == expected_code

    decision_path = tmp_path / "decision.json"
    tombstone_path = tmp_path / "decision.tombstone.json"
    decision_path.write_text(
        json.dumps(records["PILOT_AUTHORIZATION_TEMPLATE.json"]),
        encoding="utf-8",
    )
    decision_path.chmod(0o600)
    consumer = PilotAuthorizationDecisionConsumer(
        candidate_dir=candidate_path,
        decision_path=decision_path,
        tombstone_path=tombstone_path,
        ledger=object(),  # type: ignore[arg-type]
    )
    with pytest.raises(WorkItemGovernanceError) as consumption_error:
        consumer.consume(
            scope_envelope=records["scope-envelope.json"],
            execution_authorization_receipt=records[
                "execution-authorization-receipt.json"
            ],
            preflight_receipt={},
            authentication_conformance_receipt={},
            preflight_semantic_validation_receipt={},
            expected_authorization_digest=canonical_sha256(
                records["PILOT_AUTHORIZATION_TEMPLATE.json"]
            ),
        )
    assert consumption_error.value.code == expected_code
    assert decision_path.is_file()
    assert not tombstone_path.exists()
    assert not tombstone_path.with_suffix(".json.lock").exists()


@pytest.mark.parametrize("mismatch", ["scope", "execution", "decision"])
def test_validated_candidate_must_match_every_authorization_input(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mismatch: str,
) -> None:
    _, _, _, _, _, records = _records(tmp_path)
    monkeypatch.setattr(
        candidate_module,
        "validate_execution_authorization_receipt",
        lambda value: value,
    )
    monkeypatch.setattr(
        candidate_module,
        "validate_pilot_scope_envelope",
        lambda value, **kwargs: value,
    )
    monkeypatch.setattr(
        candidate_module,
        "validate_pilot_authorization",
        lambda value, **kwargs: value,
    )
    candidate_dir = tmp_path / "candidate"
    write_validated_pilot_candidate_records(candidate_dir, records)
    scope = json.loads(json.dumps(records["scope-envelope.json"]))
    execution = json.loads(
        json.dumps(records["execution-authorization-receipt.json"])
    )
    decision = json.loads(json.dumps(records["PILOT_AUTHORIZATION_TEMPLATE.json"]))
    if mismatch == "scope":
        scope["target_project"]["project_id"] = "different-project"
    elif mismatch == "execution":
        execution["scope"]["project_id"] = "different-project"
    else:
        decision["gate_id"] = "different-gate"
    decision_path = tmp_path / "decision.json"
    decision_path.write_text(json.dumps(decision), encoding="utf-8")
    decision_path.chmod(0o600)
    tombstone_path = tmp_path / "decision.tombstone.json"
    consumer = PilotAuthorizationDecisionConsumer(
        candidate_dir=candidate_dir,
        decision_path=decision_path,
        tombstone_path=tombstone_path,
        ledger=object(),  # type: ignore[arg-type]
    )
    with pytest.raises(WorkItemGovernanceError) as error:
        consumer.consume(
            scope_envelope=scope,
            execution_authorization_receipt=execution,
            preflight_receipt={},
            authentication_conformance_receipt={},
            preflight_semantic_validation_receipt={},
            expected_authorization_digest=canonical_sha256(
                records["PILOT_AUTHORIZATION_TEMPLATE.json"]
            ),
        )
    assert error.value.code == "PILOT_AUTHORIZATION_CANDIDATE_MISMATCH"
    assert decision_path.exists()
    assert not tombstone_path.exists()


def test_authorization_paths_reject_decision_and_tombstone_symlinks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _, _, _, _, _, records = _records(tmp_path)
    monkeypatch.setattr(
        candidate_module,
        "validate_execution_authorization_receipt",
        lambda value: value,
    )
    monkeypatch.setattr(
        candidate_module,
        "validate_pilot_scope_envelope",
        lambda value, **kwargs: value,
    )
    monkeypatch.setattr(
        candidate_module,
        "validate_pilot_authorization",
        lambda value, **kwargs: value,
    )
    candidate_dir = tmp_path / "candidate"
    write_validated_pilot_candidate_records(candidate_dir, records)
    decision_target = tmp_path / "decision-target.json"
    decision_target.write_text(
        json.dumps(records["PILOT_AUTHORIZATION_TEMPLATE.json"]), encoding="utf-8"
    )
    decision_target.chmod(0o600)
    decision_link = tmp_path / "decision.json"
    decision_link.symlink_to(decision_target)
    tombstone_path = tmp_path / "decision.tombstone.json"
    consumer = PilotAuthorizationDecisionConsumer(
        candidate_dir=candidate_dir,
        decision_path=decision_link,
        tombstone_path=tombstone_path,
        ledger=object(),  # type: ignore[arg-type]
    )
    with pytest.raises(WorkItemGovernanceError) as decision_error:
        consumer.consume(
            scope_envelope=records["scope-envelope.json"],
            execution_authorization_receipt=records[
                "execution-authorization-receipt.json"
            ],
            preflight_receipt={},
            authentication_conformance_receipt={},
            preflight_semantic_validation_receipt={},
            expected_authorization_digest=canonical_sha256(
                records["PILOT_AUTHORIZATION_TEMPLATE.json"]
            ),
        )
    assert decision_error.value.code == "PILOT_AUTHORIZATION_FILE_UNTRUSTED"
    assert decision_link.is_symlink()
    assert decision_target.is_file()
    assert not tombstone_path.exists()

    decision_link.unlink()
    authorization = records["PILOT_AUTHORIZATION_TEMPLATE.json"]
    duplicate_decision = "{" + ",".join(
        [
            '"bindings":{}',
            *(
                json.dumps(key) + ":" + json.dumps(value)
                for key, value in authorization.items()
            ),
        ]
    ) + "}"
    decision_link.write_text(duplicate_decision, encoding="utf-8")
    decision_link.chmod(0o600)
    with pytest.raises(WorkItemGovernanceError) as duplicate_error:
        consumer.consume(
            scope_envelope=records["scope-envelope.json"],
            execution_authorization_receipt=records[
                "execution-authorization-receipt.json"
            ],
            preflight_receipt={},
            authentication_conformance_receipt={},
            preflight_semantic_validation_receipt={},
            expected_authorization_digest=canonical_sha256(authorization),
        )
    assert duplicate_error.value.code == "PILOT_AUTHORIZATION_FILE_INVALID"

    decision_link.write_text(
        json.dumps(authorization), encoding="utf-8"
    )
    decision_link.chmod(0o600)
    tombstone_target = tmp_path / "tombstone-target.json"
    tombstone_target.write_text("sentinel", encoding="utf-8")
    tombstone_path.symlink_to(tombstone_target)
    with pytest.raises(WorkItemGovernanceError) as tombstone_error:
        consumer.consume(
            scope_envelope=records["scope-envelope.json"],
            execution_authorization_receipt=records[
                "execution-authorization-receipt.json"
            ],
            preflight_receipt={},
            authentication_conformance_receipt={},
            preflight_semantic_validation_receipt={},
            expected_authorization_digest=canonical_sha256(
                records["PILOT_AUTHORIZATION_TEMPLATE.json"]
            ),
        )
    assert tombstone_error.value.code == "PILOT_AUTHORIZATION_PATH_INVALID"
    assert decision_link.is_file()
    assert tombstone_path.is_symlink()
    assert tombstone_target.read_text(encoding="utf-8") == "sentinel"
