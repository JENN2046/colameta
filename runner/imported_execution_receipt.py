from __future__ import annotations

import re
from typing import Any


IMPORTED_RECEIPT_CHECK_PASSED = "imported_receipt_check_passed"
IMPORTED_RECEIPT_CHECK_FAILED_CLOSED = "imported_receipt_check_failed_closed"
EXPECTED_IMPORTED_RECEIPT_KIND = "imported_execution_receipt"

REQUIRED_IMPORTED_RECEIPT_FIELDS = (
    "receipt_id",
    "receipt_kind",
    "imported_receipt_authorization_ref",
    "source_provenance",
    "source_receipt_hash",
    "version_taskbook_ref",
    "master_taskbook_hash",
    "stage_taskbook_hash",
    "claimed_execution_envelope_ref",
    "claimed_commands",
    "claimed_touched_files",
    "claimed_mutations",
    "claimed_validation_results",
    "confidence_level",
    "known_gaps",
    "adoption_blockers",
    "authority_boundary",
)
CLAIMED_LIST_FIELDS = (
    "claimed_commands",
    "claimed_touched_files",
    "claimed_mutations",
    "claimed_validation_results",
)
VALID_CONFIDENCE_LEVELS = frozenset({"high", "medium", "low", "unknown"})
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")

AUTHORITY_BOUNDARY_EXPECTATIONS = {
    "imported_receipt_result_is_authority": False,
    "imported_receipt_authorizes_local_dispatch": False,
    "imported_receipt_authorizes_local_execution": False,
    "imported_receipt_adopted_as_fact": False,
    "imported_receipt_self_accepts_review": False,
    "imported_receipt_writes_delivery_state": False,
    "imported_receipt_authorizes_plan_mutation": False,
    "imported_receipt_authorizes_commit": False,
    "imported_receipt_authorizes_push": False,
    "creates_review_decision": False,
    "emits_gate_event": False,
}
FORBIDDEN_IMPORTED_RECEIPT_CLAIM_KEYS = frozenset(
    {
        "local_execution_performed",
        "local_dispatch_authorized",
        "local_execution_authorized",
        "imported_receipt_adopted_as_fact",
        "imported_receipt_adopted",
        "adopted_as_fact",
        "review_accepted",
        "review_acceptance",
        "delivery_state_accepted",
        "plan_mutation_authorized",
        "commit_authorized",
        "push_authorized",
        "imported_receipt_result_is_authority",
        "imported_receipt_authorizes_local_dispatch",
        "imported_receipt_authorizes_local_execution",
        "imported_receipt_self_accepts_review",
        "imported_receipt_writes_delivery_state",
        "imported_receipt_authorizes_plan_mutation",
        "imported_receipt_authorizes_commit",
        "imported_receipt_authorizes_push",
        "creates_review_decision",
        "emits_gate_event",
        "writes_delivery_state",
    }
)


class ImportedExecutionReceiptError(ValueError):
    def __init__(self, error_code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.details = details or {}


def validate_imported_execution_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    rejected_fields: set[str] = set()
    rejection_reasons: list[dict[str, Any]] = []
    known_conflicts: list[dict[str, Any]] = []

    if not isinstance(receipt, dict):
        return _imported_receipt_result(
            receipt={},
            rejected_fields=[],
            rejection_reasons=[
                _reason(
                    "IMPORTED_RECEIPT_INVALID",
                    "Imported execution receipt must be an object.",
                    {"actual_type": type(receipt).__name__},
                )
            ],
            known_conflicts=[],
        )

    missing = [field for field in REQUIRED_IMPORTED_RECEIPT_FIELDS if field not in receipt]
    if missing:
        rejected_fields.update(missing)
        rejection_reasons.append(
            _reason("REQUIRED_FIELD_MISSING", "Imported execution receipt is missing required fields.", {"missing_fields": missing})
        )

    if receipt.get("receipt_kind") != EXPECTED_IMPORTED_RECEIPT_KIND:
        rejected_fields.add("receipt_kind")
        rejection_reasons.append(
            _reason(
                "IMPORTED_RECEIPT_KIND_UNSUPPORTED",
                "Imported execution receipt kind is unsupported.",
                {"expected": EXPECTED_IMPORTED_RECEIPT_KIND, "actual": receipt.get("receipt_kind")},
            )
        )

    for field in ("imported_receipt_authorization_ref", "source_provenance", "version_taskbook_ref", "claimed_execution_envelope_ref"):
        if field in receipt and not _non_empty_dict(receipt.get(field)):
            rejected_fields.add(field)
            rejection_reasons.append(_reason("REFERENCE_FIELD_INVALID", f"{field} must be a non-empty object.", {"field": field}))

    for field in ("source_receipt_hash", "master_taskbook_hash", "stage_taskbook_hash"):
        if field in receipt and not _valid_sha256(receipt.get(field)):
            rejected_fields.add(field)
            rejection_reasons.append(_reason("SHA256_FIELD_INVALID", f"{field} must be a lowercase sha256 string.", {"field": field}))

    for field in CLAIMED_LIST_FIELDS:
        field_rejections = _claimed_list_rejections(receipt.get(field), field)
        if field_rejections:
            rejected_fields.add(field)
            rejection_reasons.extend(field_rejections)

    confidence_level = receipt.get("confidence_level")
    if confidence_level not in VALID_CONFIDENCE_LEVELS:
        rejected_fields.add("confidence_level")
        rejection_reasons.append(
            _reason(
                "CONFIDENCE_LEVEL_UNSUPPORTED",
                "Imported receipt confidence_level is unsupported.",
                {"actual": confidence_level, "valid_confidence_levels": sorted(VALID_CONFIDENCE_LEVELS)},
            )
        )

    for field in ("known_gaps", "adoption_blockers"):
        if field in receipt and not isinstance(receipt.get(field), list):
            rejected_fields.add(field)
            rejection_reasons.append(_reason("LIST_FIELD_INVALID", f"{field} must be a list.", {"field": field}))

    if isinstance(receipt.get("adoption_blockers"), list) and not receipt.get("adoption_blockers"):
        rejected_fields.add("adoption_blockers")
        rejection_reasons.append(
            _reason(
                "ADOPTION_BLOCKERS_REQUIRED",
                "Imported execution receipt must include at least one adoption blocker.",
                {"minimum_blocker": "separate_adoption_authority_required"},
            )
        )

    if "authority_boundary" in receipt and receipt.get("authority_boundary") != AUTHORITY_BOUNDARY_EXPECTATIONS:
        rejected_fields.add("authority_boundary")
        rejection_reasons.append(
            _reason(
                "FORBIDDEN_IMPORTED_RECEIPT_AUTHORITY_BOUNDARY",
                "Imported receipt authority boundary must remain false.",
                {
                    "expected": AUTHORITY_BOUNDARY_EXPECTATIONS,
                    "unexpected_truthy_keys": _truthy_authority_boundary_keys(receipt.get("authority_boundary")),
                },
            )
        )

    forbidden_claims = _forbidden_truthy_claims(receipt, "receipt")
    if forbidden_claims:
        rejected_fields.update(item["path"] for item in forbidden_claims)
        rejection_reasons.append(
            _reason(
                "FORBIDDEN_IMPORTED_RECEIPT_AUTHORITY_CLAIM",
                "Imported execution receipt contains forbidden authority claims.",
                {"forbidden_claims": forbidden_claims},
            )
        )
        known_conflicts.extend(
            {"conflict_type": "authority_boundary", "path": item["path"], "claim": item["key"]}
            for item in forbidden_claims
        )

    result = _imported_receipt_result(
        receipt=receipt,
        rejected_fields=sorted(rejected_fields),
        rejection_reasons=rejection_reasons,
        known_conflicts=known_conflicts,
    )
    assert_imported_execution_receipt_result_contract(result)
    return result


def assert_imported_execution_receipt_result_contract(result: dict[str, Any]) -> None:
    if not isinstance(result, dict):
        raise ImportedExecutionReceiptError("IMPORTED_RECEIPT_RESULT_INVALID", "Imported receipt result must be an object.")
    if result.get("authority_boundary") != AUTHORITY_BOUNDARY_EXPECTATIONS:
        raise ImportedExecutionReceiptError(
            "FORBIDDEN_IMPORTED_RECEIPT_RESULT_AUTHORITY_CLAIM",
            "Imported receipt result authority boundary must remain false.",
            details={"expected": AUTHORITY_BOUNDARY_EXPECTATIONS, "actual": result.get("authority_boundary")},
        )
    forbidden_claims = _forbidden_truthy_claims(result, "result")
    if forbidden_claims:
        raise ImportedExecutionReceiptError(
            "FORBIDDEN_IMPORTED_RECEIPT_RESULT_CLAIM",
            "Imported receipt result contains forbidden authority claims.",
            details={"forbidden_claims": forbidden_claims},
        )


def _imported_receipt_result(
    *,
    receipt: dict[str, Any],
    rejected_fields: list[str],
    rejection_reasons: list[dict[str, Any]],
    known_conflicts: list[dict[str, Any]],
) -> dict[str, Any]:
    passed = not rejection_reasons
    return {
        "imported_receipt_check_result": IMPORTED_RECEIPT_CHECK_PASSED if passed else IMPORTED_RECEIPT_CHECK_FAILED_CLOSED,
        "validation_result": "passed" if passed else "failed_closed",
        "recognized_fields": [field for field in REQUIRED_IMPORTED_RECEIPT_FIELDS if field in receipt],
        "rejected_fields": rejected_fields,
        "rejection_reasons": rejection_reasons,
        "known_conflicts": known_conflicts,
        "receipt_kind": receipt.get("receipt_kind"),
        "source_receipt_hash": receipt.get("source_receipt_hash"),
        "confidence_level": receipt.get("confidence_level"),
        "claim_distinction": {
            "imported_receipt_is_local_execution": False,
            "claimed_commands_are_verified_facts": False,
            "claimed_mutations_are_verified_facts": False,
            "validated_is_reviewed": False,
            "reviewed_is_accepted": False,
            "imported_receipt_self_accepts_delivery": False,
        },
        "authority_boundary": dict(AUTHORITY_BOUNDARY_EXPECTATIONS),
        "local_execution_performed": False,
        "local_dispatch_authorized": False,
        "local_execution_authorized": False,
        "imported_receipt_adopted_as_fact": False,
        "review_accepted": False,
        "delivery_state_accepted": False,
        "plan_mutation_authorized": False,
        "commit_authorized": False,
        "push_authorized": False,
        "creates_review_decision": False,
        "emits_gate_event": False,
        "writes_delivery_state": False,
    }


def _claimed_list_rejections(value: Any, field: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return [_reason("CLAIMED_LIST_INVALID", f"{field} must be a list.", {"field": field, "actual": value})]

    rejections = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            rejections.append(
                _reason("CLAIMED_ITEM_INVALID", f"{field} entries must be objects.", {"field": field, "index": index, "actual": item})
            )
            continue
        if item.get("claim_status") != "claimed":
            rejections.append(
                _reason(
                    "CLAIMED_ITEM_NOT_LABELED_AS_CLAIM",
                    f"{field} entries must be explicitly labeled as claimed.",
                    {"field": field, "index": index, "claim_status": item.get("claim_status")},
                )
            )
    return rejections


def _reason(code: str, message: str, details: dict[str, Any]) -> dict[str, Any]:
    return {"code": code, "message": message, "details": details}


def _non_empty_dict(value: Any) -> bool:
    return isinstance(value, dict) and bool(value)


def _valid_sha256(value: Any) -> bool:
    return isinstance(value, str) and bool(SHA256_PATTERN.fullmatch(value))


def _truthy_authority_boundary_keys(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return []
    return [str(key) for key, child in value.items() if key in AUTHORITY_BOUNDARY_EXPECTATIONS and _truthy_claim(child)]


def _forbidden_truthy_claims(value: Any, path: str = "receipt") -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if str(key) in FORBIDDEN_IMPORTED_RECEIPT_CLAIM_KEYS and _truthy_claim(child):
                claims.append({"path": child_path, "key": str(key), "value": child})
            claims.extend(_forbidden_truthy_claims(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            claims.extend(_forbidden_truthy_claims(child, f"{path}[{index}]"))
    return claims


def _truthy_claim(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "accepted", "authorized", "allowed", "granted", "adopted"}
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value != 0
    return False
