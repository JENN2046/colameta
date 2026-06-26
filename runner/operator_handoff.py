from __future__ import annotations

import re
from typing import Any


SUPPORTED_HANDOFF_CANDIDATE_ACTIONS = frozenset({
    "continue_next_version",
    "apply_preview",
    "run_once",
    "manual_validation_apply",
})

GUARDED_ONLY_ACTIONS = frozenset({
    "commit_apply",
})

EXCLUDED_ACTIONS = frozenset({
    "push_apply",
    "fetch_apply",
    "pull_apply",
    "restore_file_apply",
    "revert_apply",
    "tag",
    "release",
    "force_push",
    "web_remote_git_mutation",
    "shell_fallback",
    "manual_state_edit",
    "unbound_apply",
})

CLOSEOUT_OUTCOMES = frozenset({
    "verified_success",
    "verified_noop",
    "blocked_platform",
    "blocked_no_operator_surface",
    "blocked_receipt_missing",
    "blocked_receipt_invalid",
    "blocked_verification_unavailable",
    "blocked_verification_mismatch",
    "blocked_excluded_action",
})

_ACTION_ALIASES = {
    "continue_next": "continue_next_version",
    "continue_version": "continue_next_version",
    "next_version": "continue_next_version",
    "commit_confirm": "commit_apply",
    "git_commit_confirm": "commit_apply",
    "git_commit_apply": "commit_apply",
    "push": "push_apply",
    "git_push": "push_apply",
    "git_push_apply": "push_apply",
    "git_remote_push": "push_apply",
    "git_remote_push_apply": "push_apply",
    "remote_git_push": "push_apply",
    "remote_git_push_apply": "push_apply",
    "web_git_push_apply": "push_apply",
    "fetch": "fetch_apply",
    "git_fetch": "fetch_apply",
    "git_fetch_apply": "fetch_apply",
    "git_remote_fetch": "fetch_apply",
    "git_remote_fetch_apply": "fetch_apply",
    "remote_git_fetch": "fetch_apply",
    "remote_git_fetch_apply": "fetch_apply",
    "web_git_fetch_apply": "fetch_apply",
    "pull": "pull_apply",
    "git_pull": "pull_apply",
    "git_pull_apply": "pull_apply",
    "git_remote_pull": "pull_apply",
    "git_remote_pull_apply": "pull_apply",
    "remote_git_pull": "pull_apply",
    "remote_git_pull_apply": "pull_apply",
    "web_git_pull_apply": "pull_apply",
    "force_push_apply": "force_push",
    "git_force_push": "force_push",
    "restore": "restore_file_apply",
    "restore_file": "restore_file_apply",
    "restore_apply": "restore_file_apply",
    "file_restore": "restore_file_apply",
    "revert": "revert_apply",
    "git_revert": "revert_apply",
    "tag_apply": "tag",
    "git_tag": "tag",
    "create_tag": "tag",
    "release_apply": "release",
    "publish_release": "release",
    "remote_git_mutation": "web_remote_git_mutation",
    "web_git_remote_mutation": "web_remote_git_mutation",
    "web_remote_git": "web_remote_git_mutation",
    "shell": "shell_fallback",
    "bash": "shell_fallback",
    "terminal": "shell_fallback",
    "generic_shell": "shell_fallback",
    "state_edit": "manual_state_edit",
    "state_editor": "manual_state_edit",
    "manual_state_editor": "manual_state_edit",
    "manual_state_mutation": "manual_state_edit",
    "unbound": "unbound_apply",
    "apply_without_preview": "unbound_apply",
}

_ACTION_SURFACE_TOKENS = {
    "continue_next_version": frozenset({"continue", "next", "version"}),
    "apply_preview": frozenset({"apply", "preview"}),
    "run_once": frozenset({"run", "once"}),
    "manual_validation_apply": frozenset({"manual", "validation", "apply"}),
}

_GENERIC_SURFACE_VALUES = frozenset({
    "shell",
    "terminal",
    "bash",
    "zsh",
    "sh",
    "powershell",
    "cmd",
    "generic_shell",
    "file_editor",
    "generic_file_editor",
    "state_editor",
    "generic_state_editor",
    "manual_state_editor",
    "http_client",
    "generic_http_client",
    "curl",
    "postman",
    "insomnia",
    "browser_devtools",
})

_TRUTHY_STRINGS = frozenset({"1", "true", "yes", "y", "on"})


def normalize_action_class(value: str) -> str:
    normalized = _normalize_identifier(value)
    return _ACTION_ALIASES.get(normalized, normalized)


def is_supported_candidate_action(action_class: str) -> bool:
    return normalize_action_class(action_class) in SUPPORTED_HANDOFF_CANDIDATE_ACTIONS


def is_excluded_action(action_class: str) -> bool:
    return normalize_action_class(action_class) in EXCLUDED_ACTIONS


def is_guarded_only_action(action_class: str) -> bool:
    return normalize_action_class(action_class) in GUARDED_ONLY_ACTIONS


def validate_handoff_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    if not isinstance(manifest, dict):
        return _validation_result(
            ok=False,
            errors=[_error("INVALID_MANIFEST", "OPERATOR_HANDOFF manifest must be a dictionary.")],
        )

    if manifest.get("type") != "OPERATOR_HANDOFF":
        errors.append(_error("INVALID_MANIFEST_TYPE", "Manifest type must be OPERATOR_HANDOFF."))
    if str(manifest.get("schema_version") or "").strip() != "1.0":
        errors.append(_error("INVALID_SCHEMA_VERSION", "Manifest schema_version must be 1.0."))

    handoff_id = _require_non_empty_string(manifest, "handoff_id", errors)
    action_class = _manifest_action_class(manifest)
    _validate_action_class_for_manifest(action_class, errors)

    if _contains_truthy_key(manifest, "remote_git_mutation"):
        errors.append(_error("REMOTE_GIT_MUTATION_REJECTED", "remote_git_mutation=true is not allowed."))
    if _contains_truthy_key(manifest, "secrets_included"):
        errors.append(_error("SECRETS_INCLUDED_REJECTED", "secrets_included=true is not allowed."))

    if not isinstance(manifest.get("project_binding"), dict):
        errors.append(_error("MISSING_PROJECT_BINDING", "Manifest must include project_binding."))

    action_binding = manifest.get("action_binding")
    if not isinstance(action_binding, dict):
        errors.append(_error("MISSING_ACTION_BINDING", "Manifest must include action_binding."))
    elif action_class and normalize_action_class(str(action_binding.get("action_class") or "")) != action_class:
        errors.append(_error("ACTION_BINDING_MISMATCH", "action_binding.action_class must match the manifest action class."))

    operator_surface = manifest.get("operator_surface")
    _validate_operator_surface(operator_surface, action_class, errors, prefix="Manifest")

    if not _declares_read_only_closeout(manifest.get("required_closeout_checks")):
        errors.append(_error(
            "READ_ONLY_CLOSEOUT_REQUIRED",
            "Manifest must declare read-only closeout verification requirements.",
        ))

    if not str(manifest.get("reason") or "").strip():
        warnings.append(_warning("MISSING_REASON", "Manifest reason is empty."))

    return _validation_result(
        ok=not errors,
        errors=errors,
        warnings=warnings,
        action_class=action_class,
        handoff_id=handoff_id,
        read_only_closeout_declared=not any(error["code"] == "READ_ONLY_CLOSEOUT_REQUIRED" for error in errors),
    )


def validate_operator_receipt(receipt: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    manifest_result = validate_handoff_manifest(manifest)
    manifest_action = str(manifest_result.get("action_class") or "")
    manifest_handoff_id = str(manifest_result.get("handoff_id") or "")
    if not manifest_result.get("ok"):
        errors.append(_error("INVALID_MANIFEST", "Receipt cannot be validated against an invalid handoff manifest."))

    if not isinstance(receipt, dict):
        return _validation_result(
            ok=False,
            errors=errors + [_error("INVALID_RECEIPT", "OPERATOR_RECEIPT must be a dictionary.")],
            receipt_is_claim=True,
            proof_verified=False,
        )

    if receipt.get("type") != "OPERATOR_RECEIPT":
        errors.append(_error("INVALID_RECEIPT_TYPE", "Receipt type must be OPERATOR_RECEIPT."))
    if str(receipt.get("schema_version") or "").strip() != "1.0":
        errors.append(_error("INVALID_SCHEMA_VERSION", "Receipt schema_version must be 1.0."))

    receipt_handoff_id = str(receipt.get("handoff_id") or "").strip()
    if not receipt_handoff_id:
        errors.append(_error("MISSING_HANDOFF_ID", "Receipt must include handoff_id."))
    elif manifest_handoff_id and receipt_handoff_id != manifest_handoff_id:
        errors.append(_error("HANDOFF_ID_MISMATCH", "Receipt handoff_id must match the manifest."))

    receipt_action = normalize_action_class(str(receipt.get("action_class") or ""))
    if not receipt_action:
        errors.append(_error("MISSING_ACTION_CLASS", "Receipt must include action_class."))
    elif is_excluded_action(receipt_action):
        errors.append(_error("EXCLUDED_ACTION", f"Action {receipt_action} is excluded from operator handoff."))
    elif is_guarded_only_action(receipt_action):
        errors.append(_error("GUARDED_ONLY_ACTION", f"Action {receipt_action} remains existing guarded behavior only."))
    elif manifest_action and receipt_action != manifest_action:
        errors.append(_error("ACTION_MISMATCH", "Receipt action_class must match the manifest."))

    if _contains_truthy_key(receipt, "remote_git_mutation"):
        errors.append(_error("REMOTE_GIT_MUTATION_REJECTED", "remote_git_mutation=true is not allowed."))
    if _contains_truthy_key(receipt, "secrets_included"):
        errors.append(_error("SECRETS_INCLUDED_REJECTED", "secrets_included=true is not allowed."))

    receipt_surface = receipt.get("operator_surface")
    _validate_operator_surface(receipt_surface, receipt_action or manifest_action, errors, prefix="Receipt")
    if isinstance(receipt_surface, dict) and isinstance(manifest.get("operator_surface"), dict):
        if _surface_fingerprint(receipt_surface) != _surface_fingerprint(manifest["operator_surface"]):
            errors.append(_error("OPERATOR_SURFACE_MISMATCH", "Receipt operator_surface must match the manifest."))

    closeout = _receipt_closeout(receipt)
    closeout_declared = _receipt_declares_read_only_closeout(receipt)
    closeout_outcome = _receipt_closeout_outcome(closeout, receipt)
    if not closeout_declared:
        errors.append(_error(
            "READ_ONLY_CLOSEOUT_REQUIRED",
            "Receipt must declare read-only closeout verification before success can be considered valid.",
        ))
    if closeout_outcome and closeout_outcome not in CLOSEOUT_OUTCOMES:
        errors.append(_error("INVALID_CLOSEOUT_OUTCOME", f"Unknown closeout outcome: {closeout_outcome}."))
    if not closeout_outcome:
        warnings.append(_warning("MISSING_CLOSEOUT_OUTCOME", "Receipt does not declare a closeout outcome."))

    return _validation_result(
        ok=not errors,
        errors=errors,
        warnings=warnings,
        action_class=receipt_action,
        handoff_id=receipt_handoff_id,
        receipt_is_claim=True,
        proof_verified=False,
        read_only_closeout_declared=closeout_declared,
        closeout_outcome=closeout_outcome,
        success_claim_valid=not errors and closeout_outcome == "verified_success" and closeout_declared,
    )


def _validate_action_class_for_manifest(action_class: str, errors: list[dict[str, str]]) -> None:
    if not action_class:
        errors.append(_error("MISSING_ACTION_CLASS", "Manifest must include action_class."))
        return
    if is_excluded_action(action_class):
        errors.append(_error("EXCLUDED_ACTION", f"Action {action_class} is excluded from operator handoff."))
        return
    if is_guarded_only_action(action_class):
        errors.append(_error("GUARDED_ONLY_ACTION", f"Action {action_class} remains existing guarded behavior only."))
        return
    if not is_supported_candidate_action(action_class):
        errors.append(_error("UNSUPPORTED_ACTION", f"Action {action_class} is not a supported handoff candidate."))


def _validate_operator_surface(
    surface: Any,
    action_class: str,
    errors: list[dict[str, str]],
    *,
    prefix: str,
) -> None:
    if not isinstance(surface, dict):
        errors.append(_error("MISSING_OPERATOR_SURFACE", f"{prefix} must include operator_surface."))
        return

    surface_type = str(surface.get("surface_type") or "").strip()
    surface_name = str(surface.get("surface_name") or "").strip()
    if not surface_type:
        errors.append(_error("MISSING_OPERATOR_SURFACE_TYPE", f"{prefix} operator_surface.surface_type is required."))
    if not surface_name:
        errors.append(_error("MISSING_OPERATOR_SURFACE_NAME", f"{prefix} operator_surface.surface_name is required."))

    if _contains_truthy_key(surface, "remote_git_mutation"):
        errors.append(_error("REMOTE_GIT_MUTATION_REJECTED", "operator_surface remote_git_mutation=true is not allowed."))
    if _is_generic_surface(surface):
        errors.append(_error("GENERIC_OPERATOR_SURFACE_REJECTED", "Operator surface must be action-specific, not generic."))
    if action_class and not _surface_matches_action(surface, action_class):
        errors.append(_error("ACTION_SPECIFIC_SURFACE_REQUIRED", "Operator surface must be specific to the action class."))

    if "approved" in surface and surface.get("approved") is not True:
        errors.append(_error("OPERATOR_SURFACE_NOT_APPROVED", "operator_surface.approved must not be false."))


def _manifest_action_class(manifest: dict[str, Any]) -> str:
    candidates = (
        manifest.get("action_class"),
        _nested_get(manifest, "action_binding", "action_class"),
        _nested_get(manifest, "blocked_tool_call", "action_class"),
    )
    for candidate in candidates:
        normalized = normalize_action_class(str(candidate or ""))
        if normalized:
            return normalized
    return ""


def _nested_get(source: dict[str, Any], *path: str) -> Any:
    value: Any = source
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _require_non_empty_string(source: dict[str, Any], key: str, errors: list[dict[str, str]]) -> str:
    value = str(source.get(key) or "").strip()
    if not value:
        errors.append(_error(f"MISSING_{key.upper()}", f"Manifest must include {key}."))
    return value


def _normalize_identifier(value: Any) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower())).strip("_")


def _token_set(value: str) -> set[str]:
    return {part for part in _normalize_identifier(value).split("_") if part}


def _surface_fingerprint(surface: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        _normalize_identifier(surface.get("surface_type")),
        _normalize_identifier(surface.get("surface_name")),
        _normalize_identifier(surface.get("surface_id")),
        normalize_action_class(str(surface.get("action_class") or "")),
    )


def _is_generic_surface(surface: dict[str, Any]) -> bool:
    values = [
        _normalize_identifier(surface.get("surface_type")),
        _normalize_identifier(surface.get("surface_name")),
        _normalize_identifier(surface.get("surface_id")),
    ]
    for value in values:
        if value in _GENERIC_SURFACE_VALUES:
            return True
        tokens = _token_set(value)
        if "generic" in tokens and ({"shell", "editor", "state", "file", "http", "client"} & tokens):
            return True
        if {"shell", "terminal", "bash", "zsh", "sh", "powershell", "cmd", "curl", "postman", "insomnia"} & tokens:
            return True
        if {"http", "client"}.issubset(tokens):
            return True
        if {"file", "editor"}.issubset(tokens):
            return True
        if {"state", "editor"}.issubset(tokens):
            return True
    return False


def _surface_matches_action(surface: dict[str, Any], action_class: str) -> bool:
    if normalize_action_class(str(surface.get("action_class") or "")) == action_class:
        return True
    joined = " ".join(
        str(surface.get(key) or "")
        for key in ("surface_id", "surface_name", "surface_type")
    )
    normalized_joined = _normalize_identifier(joined)
    if action_class in normalized_joined:
        return True
    tokens = _token_set(joined)
    required_tokens = _ACTION_SURFACE_TOKENS.get(action_class, frozenset())
    return bool(required_tokens) and required_tokens.issubset(tokens)


def _declares_read_only_closeout(value: Any) -> bool:
    if isinstance(value, list):
        return any(_value_mentions_read_only(item) for item in value)
    if isinstance(value, dict):
        return _truthy(value.get("read_only")) or _truthy(value.get("declared")) or any(
            _value_mentions_read_only(item) for item in value.values()
        )
    return _value_mentions_read_only(value)


def _receipt_closeout(receipt: dict[str, Any]) -> Any:
    for key in ("read_only_closeout", "closeout_verification", "closeout"):
        value = receipt.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _receipt_declares_read_only_closeout(receipt: dict[str, Any]) -> bool:
    if _truthy(receipt.get("read_only_closeout_declared")):
        return True
    closeout = _receipt_closeout(receipt)
    if not isinstance(closeout, dict):
        return False
    if _truthy(closeout.get("declared")) or _truthy(closeout.get("read_only")):
        return True
    if _truthy(closeout.get("verified_via_read_only_tools")):
        return True
    return any(_value_mentions_read_only(value) for value in closeout.values())


def _receipt_closeout_outcome(closeout: Any, receipt: dict[str, Any]) -> str:
    if isinstance(closeout, dict):
        outcome = closeout.get("outcome")
        if outcome:
            return normalize_action_class(str(outcome))
    return normalize_action_class(str(receipt.get("closeout_outcome") or ""))


def _contains_truthy_key(value: Any, key_name: str) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key) == key_name and _truthy(child):
                return True
            if _contains_truthy_key(child, key_name):
                return True
    elif isinstance(value, list):
        return any(_contains_truthy_key(child, key_name) for child in value)
    return False


def _value_mentions_read_only(value: Any) -> bool:
    if isinstance(value, (list, tuple, set)):
        return any(_value_mentions_read_only(item) for item in value)
    if isinstance(value, dict):
        return any(_value_mentions_read_only(item) for item in value.values())
    normalized = _normalize_identifier(value)
    return "read_only" in normalized or "readonly" in normalized


def _truthy(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, int) and not isinstance(value, bool):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in _TRUTHY_STRINGS
    return False


def _validation_result(
    *,
    ok: bool,
    errors: list[dict[str, str]],
    warnings: list[dict[str, str]] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    result = {
        "ok": ok,
        "status": "valid" if ok else "invalid",
        "errors": errors,
        "warnings": warnings or [],
    }
    if not ok and errors:
        result["error_code"] = errors[0]["code"]
    result.update(extra)
    return result


def _error(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def _warning(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}
