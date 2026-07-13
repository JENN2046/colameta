from __future__ import annotations

import re
from typing import Final


CURRENT_LEDGER_SCHEMA_VERSION: Final = 6
LEDGER_RELATIVE_PATH: Final = ".colameta/ledger/work-items.sqlite3"
LEDGER_DATA_CLASSIFICATION: Final = "project_local_durable"

WORK_ITEM_STATES: Final = frozenset(
    {"proposed", "ready", "in_delivery", "submitted", "accepted", "cancelled"}
)
TERMINAL_WORK_ITEM_STATES: Final = frozenset({"accepted", "cancelled"})
WORK_ITEM_TRANSITIONS: Final = {
    "proposed": frozenset({"ready", "cancelled"}),
    "ready": frozenset({"in_delivery", "cancelled"}),
    "in_delivery": frozenset({"submitted", "cancelled"}),
    "submitted": frozenset({"in_delivery", "accepted", "cancelled"}),
    "accepted": frozenset(),
    "cancelled": frozenset(),
}

ORIGIN_KINDS: Final = frozenset(
    {"quick_chat", "project", "workbench", "slack", "linear", "manual", "imported"}
)
ARTIFACT_KINDS: Final = frozenset(
    {"report", "validation", "git_commit", "git_diff", "file", "test_report", "evidence_receipt", "other"}
)
DECISION_ACTIONS: Final = frozenset(
    {
        "approve",
        "approve_submission",
        "accept",
        "cancel",
        "reject",
        "request_changes",
        "submit",
    }
)

SCHEMA_VERSIONS: Final = {
    "work_item": "work_item.v1",
    "task_version": "task_version.v1",
    "execution_attempt": "execution_attempt.v1",
    "artifact_reference": "artifact_reference.v1",
    "decision_record": "decision_record.v1",
    "gate_event": "gate_event.v1",
    "delivery_receipt": "delivery_receipt.v1",
    "preview": "work_item_command_preview.v1",
    "execution_envelope": "execution_envelope.v2",
    "acceptance_manifest": "acceptance_evidence_manifest.v1",
}

ID_PREFIXES: Final = {
    "work_item": "wi",
    "attempt": "attempt",
    "artifact": "artifact",
    "decision": "decision",
    "gate_event": "gate",
    "delivery_receipt": "delivery",
    "audit_event": "audit",
    "outbox_event": "outbox",
    "inbox_event": "inbox",
    "blocker": "blocker",
    "blocker_event": "blocker_event",
    "attempt_event": "attempt_event",
    "acceptance_manifest": "acceptance_manifest",
    "preview": "preview",
    "activation_lease": "lease",
    "activation_lease_event": "lease_event",
    "activation_envelope": "envelope",
}

UUID7_TEXT_PATTERN: Final = (
    r"[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
)
SHA256_PATTERN: Final = re.compile(r"^[0-9a-f]{64}$")
STABLE_ID_PATTERN: Final = re.compile(
    rf"^(?:{'|'.join(re.escape(value) for value in ID_PREFIXES.values())})_{UUID7_TEXT_PATTERN}$"
)

MAX_JSON_BYTES: Final = 1_048_576
MAX_URI_LENGTH: Final = 8_192
MAX_TEXT_LENGTH: Final = 65_536
DEFAULT_PREVIEW_TTL_SECONDS: Final = 300
MAX_PREVIEW_TTL_SECONDS: Final = 900
DEFAULT_BUSY_TIMEOUT_MS: Final = 5_000

# These requirements are the sole transition-policy definition consumed by the
# application service.  Runner status is intentionally absent.
TRANSITION_REQUIREMENTS: Final = {
    ("proposed", "ready"): {
        "authority": "work_item.ready",
        "decision_actions": frozenset(),
        "evidence_required": False,
        "blockers_must_be_clear": False,
    },
    ("ready", "in_delivery"): {
        "authority": "work_item.start_delivery",
        "decision_actions": frozenset(),
        "evidence_required": False,
        "blockers_must_be_clear": True,
    },
    ("in_delivery", "submitted"): {
        "authority": "work_item.submit",
        "decision_actions": frozenset({"submit", "approve_submission", "approve"}),
        "evidence_required": True,
        "blockers_must_be_clear": True,
    },
    ("submitted", "accepted"): {
        "authority": "work_item.accept",
        "decision_actions": frozenset({"accept", "approve"}),
        "evidence_required": True,
        "blockers_must_be_clear": True,
    },
    ("submitted", "in_delivery"): {
        "authority": "work_item.return_for_revision",
        "decision_actions": frozenset({"request_changes", "reject"}),
        "evidence_required": False,
        "blockers_must_be_clear": False,
        "transition_result": "returned_for_revision",
    },
    ("proposed", "cancelled"): {
        "authority": "work_item.cancel",
        "decision_actions": frozenset({"cancel"}),
        "evidence_required": False,
        "blockers_must_be_clear": False,
    },
    ("ready", "cancelled"): {
        "authority": "work_item.cancel",
        "decision_actions": frozenset({"cancel"}),
        "evidence_required": False,
        "blockers_must_be_clear": False,
    },
    ("in_delivery", "cancelled"): {
        "authority": "work_item.cancel",
        "decision_actions": frozenset({"cancel"}),
        "evidence_required": False,
        "blockers_must_be_clear": False,
    },
    ("submitted", "cancelled"): {
        "authority": "work_item.cancel",
        "decision_actions": frozenset({"cancel"}),
        "evidence_required": False,
        "blockers_must_be_clear": False,
    },
}


def can_transition(current_state: str, target_state: str) -> bool:
    return target_state in WORK_ITEM_TRANSITIONS.get(current_state, frozenset())
