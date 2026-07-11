from __future__ import annotations

import json
from pathlib import Path

from runner.runner_data_layout import classify_runner_path, recommended_gitignore_rules
from runner.work_item_governance.architecture import check_work_item_architecture
from runner.work_item_governance.contracts import (
    TERMINAL_WORK_ITEM_STATES,
    TRANSITION_REQUIREMENTS,
    WORK_ITEM_TRANSITIONS,
    can_transition,
)
from runner.work_item_governance.ids import is_stable_id, new_stable_id, new_uuid7
from runner.work_item_governance.schema_loader import SCHEMA_FILES, load_all_governance_schemas


def test_uuidv7_identifiers_are_versioned_and_prefixed() -> None:
    value = new_uuid7(timestamp_ms=1_700_000_000_000, random_bytes=b"0123456789")
    assert value.version == 7
    assert value.variant == "specified in RFC 4122"
    for kind in ("work_item", "attempt", "artifact", "decision", "gate_event", "delivery_receipt"):
        assert is_stable_id(new_stable_id(kind), kind)


def test_schema_catalog_loads_and_local_refs_resolve() -> None:
    schemas = load_all_governance_schemas()
    assert set(schemas) == set(SCHEMA_FILES)
    schema_dir = Path(__file__).resolve().parents[1] / "schemas" / "work_item_governance"
    for schema in schemas.values():
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert isinstance(schema["$id"], str)
        encoded = json.dumps(schema)
        for filename in SCHEMA_FILES.values():
            if filename in encoded:
                assert (schema_dir / filename).is_file()


def test_lifecycle_matrix_is_closed_and_terminal_states_are_irreversible() -> None:
    assert can_transition("proposed", "ready")
    assert can_transition("submitted", "accepted")
    assert not can_transition("ready", "accepted")
    for state in TERMINAL_WORK_ITEM_STATES:
        assert WORK_ITEM_TRANSITIONS[state] == frozenset()
    assert set(TRANSITION_REQUIREMENTS) == {
        (source, target)
        for source, targets in WORK_ITEM_TRANSITIONS.items()
        for target in targets
    }


def test_ledger_path_is_project_local_durable_and_ignored() -> None:
    classification = classify_runner_path(".colameta/ledger/work-items.sqlite3")
    assert classification["category"] == "project_local_durable"
    assert classification["track_policy"] == "private"
    assert ".colameta/ledger/" in recommended_gitignore_rules()


def test_work_item_core_has_no_transport_product_ops_or_provider_dependency() -> None:
    project = Path(__file__).resolve().parents[1]
    result = check_work_item_architecture(project)
    assert result["ok"] is True, result["violations"]


def test_future_operations_module_is_covered_by_architecture_manifest(tmp_path: Path) -> None:
    runner_dir = tmp_path / "runner"
    core_dir = runner_dir / "work_item_governance"
    core_dir.mkdir(parents=True)
    (core_dir / "__init__.py").write_text("", encoding="utf-8")
    (runner_dir / "future_connector_operations.py").write_text(
        "from runner.work_item_governance.repository import SQLiteWorkItemLedger\n",
        encoding="utf-8",
    )
    result = check_work_item_architecture(tmp_path)
    assert result["ok"] is False
    assert result["checked_side_context_files"] == 1
    assert result["violations"] == [
        {
            "rule": "side_context_repository_dependency",
            "path": "runner/future_connector_operations.py",
            "import": "runner.work_item_governance.repository",
        },
    ]
