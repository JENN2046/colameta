from __future__ import annotations

from typing import Any


ADAPTER_STATUS_ADAPTED = "review_decision_value_adapted"
ADAPTER_STATUS_FAILED_CLOSED = "review_decision_adapter_failed_closed"
ACCEPTED_NATIVE_VALUES = ("ACCEPT", "NEEDS_FIX", "PLAN_ADJUST", "ABORT")
LEGACY_ALIAS_VALUES = {"PASS": "ACCEPT"}
RUNTIME_STATE_VALUES = frozenset({"VERSION_PASSED", "PASSED", "COMPLETED", "BLOCKED", "FAILED_BLOCKED", "RUNNING_ACCEPTANCE"})
FORBIDDEN_EQUIVALENCE_KEYS = frozenset(
    {
        "PASS_equals_delivery_state_accepted",
        "ACCEPT_equals_delivery_state_accepted",
        "runtime_PASSED_equals_review_acceptance",
        "validation_passed_equals_review_acceptance",
    }
)
FORBIDDEN_ADAPTER_OUTPUT_KEYS = frozenset(
    {
        "review_decision_record",
        "review_decision_created",
        "gate_event",
        "gate_event_emitted",
        "delivery_state_transition",
        "delivery_state_transitioned",
        "runtime_state_transition",
        "runtime_state_transitioned",
        "commander_authorization",
        "commander_authorization_granted",
    }
)


class ReviewDecisionAdapterError(ValueError):
    def __init__(self, error_code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.details = details or {}


def adapt_review_decision_value(
    review_value: str,
    *,
    alias_policy_ref: str | None = None,
    forbidden_equivalence_claims: dict[str, Any] | None = None,
) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    normalized_value: str | None = None
    alias_used = False

    if review_value in ACCEPTED_NATIVE_VALUES:
        normalized_value = review_value
    elif review_value in LEGACY_ALIAS_VALUES:
        alias_used = True
        if alias_policy_ref:
            normalized_value = LEGACY_ALIAS_VALUES[review_value]
            warnings.append(
                _reason(
                    "LEGACY_ALIAS_USED",
                    "Legacy PASS alias was normalized by explicit policy ref.",
                    {"original_value": review_value, "normalized_value": normalized_value, "alias_policy_ref": alias_policy_ref},
                )
            )
        else:
            errors.append(_reason("PASS_ALIAS_POLICY_REF_MISSING", "PASS alias requires an explicit policy ref.", {}))
    elif review_value in RUNTIME_STATE_VALUES:
        errors.append(
            _reason(
                "RUNTIME_STATE_EQUIVALENCE_FORBIDDEN",
                "Runtime state values must not be adapted as review decisions.",
                {"runtime_state_value": review_value},
            )
        )
    else:
        errors.append(_reason("UNKNOWN_REVIEW_VALUE", "Review value is not a native value or policy-bound alias.", {"review_value": review_value}))

    equivalence_claims = forbidden_equivalence_claims or {}
    forbidden_equivalences = [key for key in FORBIDDEN_EQUIVALENCE_KEYS if equivalence_claims.get(key) is True]
    if forbidden_equivalences:
        errors.append(
            _reason(
                "FORBIDDEN_RUNTIME_OR_DELIVERY_STATE_EQUIVALENCE",
                "Adapter input claims a forbidden equivalence.",
                {"forbidden_equivalences": forbidden_equivalences},
            )
        )

    result = {
        "adapter_status": ADAPTER_STATUS_ADAPTED if not errors else ADAPTER_STATUS_FAILED_CLOSED,
        "original_value": review_value,
        "normalized_review_decision_value": normalized_value if not errors else None,
        "alias_policy_ref_when_used": alias_policy_ref if alias_used else None,
        "alias_disclosure": {
            "alias_used": alias_used,
            "original_value": review_value if alias_used else None,
            "normalized_value": normalized_value if alias_used and not errors else None,
            "must_surface_alias": alias_used,
            "does_not_mean_runtime_PASSED": True,
            "does_not_mean_delivery_state_accepted": True,
            "does_not_mean_validation_passed_as_review_acceptance": True,
        },
        "adapter_warnings": warnings,
        "adapter_errors": errors,
        "forbidden_meaning_check": {
            "runtime_PASSED_equals_review_acceptance": False,
            "validation_passed_equals_review_acceptance": False,
            "PASS_equals_delivery_state_accepted": False,
            "ACCEPT_equals_delivery_state_accepted": False,
        },
        "review_decision_created": False,
        "gate_event_emitted": False,
        "delivery_state_transitioned": False,
        "runtime_state_transitioned": False,
        "commander_authorization_granted": False,
    }
    assert_review_decision_adapter_contract(result)
    return result


def assert_review_decision_adapter_contract(result: dict[str, Any]) -> None:
    if not isinstance(result, dict):
        raise ReviewDecisionAdapterError("REVIEW_DECISION_ADAPTER_RESULT_INVALID", "Adapter result must be an object.")
    forbidden = _forbidden_truthy_outputs(result, "adapter")
    if forbidden:
        raise ReviewDecisionAdapterError(
            "FORBIDDEN_REVIEW_DECISION_ADAPTER_OUTPUT",
            "Adapter result contains forbidden authority output.",
            details={"forbidden_outputs": forbidden},
        )
    if result.get("adapter_status") == ADAPTER_STATUS_ADAPTED and result.get("normalized_review_decision_value") not in ACCEPTED_NATIVE_VALUES:
        raise ReviewDecisionAdapterError(
            "REVIEW_DECISION_ADAPTER_NORMALIZED_VALUE_INVALID",
            "Adapter normalized value must be in the native ReviewDecision value set.",
            details={"normalized_review_decision_value": result.get("normalized_review_decision_value")},
        )


def review_decision_adapter_inventory() -> dict[str, Any]:
    return {
        "accepted_native_values": list(ACCEPTED_NATIVE_VALUES),
        "legacy_alias_values": {
            "PASS": {
                "normalized_value": "ACCEPT",
                "requires_policy_ref": True,
                "must_surface_alias": True,
                "forbidden_meanings": [
                    "runtime_PASSED",
                    "delivery_state_accepted",
                    "validation_passed_as_review_acceptance",
                ],
            }
        },
        "runtime_state_values_rejected": sorted(RUNTIME_STATE_VALUES),
        "forbidden_outputs": sorted(FORBIDDEN_ADAPTER_OUTPUT_KEYS),
    }


def _reason(code: str, message: str, details: dict[str, Any]) -> dict[str, Any]:
    return {"code": code, "message": message, "details": details}


def _forbidden_truthy_outputs(value: Any, path: str) -> list[dict[str, str]]:
    claims: list[dict[str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if str(key) in FORBIDDEN_ADAPTER_OUTPUT_KEYS and _truthy_claim(child):
                claims.append({"path": child_path, "key": str(key)})
            claims.extend(_forbidden_truthy_outputs(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            claims.extend(_forbidden_truthy_outputs(child, f"{path}[{index}]"))
    return claims


def _truthy_claim(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "accepted", "created", "authorized", "transitioned"}
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value != 0
    return False

