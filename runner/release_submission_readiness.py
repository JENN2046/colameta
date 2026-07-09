from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from runner.production_ops import DEFAULT_CONNECTOR_SMOKE_FRESH_HOURS, DEFAULT_PUBLIC_BASE_URL
from runner.product_readiness import build_product_readiness_packet


RELEASE_SUBMISSION_SOURCE = "release_submission_readiness"
RELEASE_SUBMISSION_VERSION = "release_submission_readiness.v1"
READY = "ready"
NEEDS_ATTENTION = "needs_attention"
BLOCKED = "blocked"

SUBMISSION_MATERIAL_TEXT_FIELDS = {
    "app_name",
    "app_description",
    "company_url",
    "privacy_policy_url",
}
SUBMISSION_MATERIAL_BOOL_FIELDS = {
    "logo_ready",
    "screenshots_ready",
    "test_prompts_ready",
    "test_responses_ready",
    "localization_ready",
    "mcp_tool_info_ready",
    "app_management_permissions_confirmed",
    "security_review_ready",
    "metadata_snapshot_reviewed",
    "submission_confirmations_ready",
}
SUBMISSION_MATERIAL_METADATA_FIELDS = {
    "schema_version",
    "evidence",
    "notes",
}
SUBMISSION_MATERIAL_FIELDS = (
    SUBMISSION_MATERIAL_TEXT_FIELDS | SUBMISSION_MATERIAL_BOOL_FIELDS | SUBMISSION_MATERIAL_METADATA_FIELDS
)

DOC_REFS = [
    {
        "id": "submit_app",
        "url": "https://developers.openai.com/apps-sdk/deploy/submission",
        "why": "Submission requires public MCP details, required form fields, screenshots, prompts/responses, and review flow.",
    },
    {
        "id": "submission_guidelines",
        "url": "https://developers.openai.com/apps-sdk/app-submission-guidelines",
        "why": "Apps must be complete, reliable, well-described, and thoroughly tested before submission.",
    },
    {
        "id": "testing",
        "url": "https://developers.openai.com/apps-sdk/deploy/testing",
        "why": "Tool handlers, ChatGPT developer mode, and mobile layouts should be tested before rollout.",
    },
    {
        "id": "security_privacy",
        "url": "https://developers.openai.com/apps-sdk/guides/security-privacy",
        "why": "Launch readiness should cover least privilege, explicit consent, redaction, confirmation, and operational monitoring.",
    },
]


def build_release_submission_readiness(
    project_root: str,
    *,
    project_name: str | None = None,
    public_base_url: str = DEFAULT_PUBLIC_BASE_URL,
    no_network: bool = False,
    app_name: str | None = None,
    app_description: str | None = None,
    company_url: str | None = None,
    privacy_policy_url: str | None = None,
    logo_ready: bool = False,
    screenshots_ready: bool = False,
    test_prompts_ready: bool = False,
    test_responses_ready: bool = False,
    localization_ready: bool = False,
    mcp_tool_info_ready: bool = False,
    app_management_permissions_confirmed: bool = False,
    security_review_ready: bool = False,
    metadata_snapshot_reviewed: bool = False,
    submission_confirmations_ready: bool = False,
    submission_materials: Mapping[str, Any] | None = None,
    readiness_packet: dict[str, Any] | None = None,
    now: datetime | None = None,
    readiness_builder: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    readiness = readiness_packet if isinstance(readiness_packet, dict) else None
    if readiness is None:
        builder = readiness_builder or build_product_readiness_packet
        readiness = builder(
            project_root,
            public_base_url=public_base_url,
            no_network=no_network,
            connector_smoke_fresh_hours=DEFAULT_CONNECTOR_SMOKE_FRESH_HOURS,
            now=now,
        )
    materials = _merge_submission_materials(
        submission_materials,
        app_name=app_name,
        app_description=app_description,
        company_url=company_url,
        privacy_policy_url=privacy_policy_url,
        logo_ready=logo_ready,
        screenshots_ready=screenshots_ready,
        test_prompts_ready=test_prompts_ready,
        test_responses_ready=test_responses_ready,
        localization_ready=localization_ready,
        mcp_tool_info_ready=mcp_tool_info_ready,
        app_management_permissions_confirmed=app_management_permissions_confirmed,
        security_review_ready=security_review_ready,
        metadata_snapshot_reviewed=metadata_snapshot_reviewed,
        submission_confirmations_ready=submission_confirmations_ready,
    )
    materials_manifest = materials["manifest"]
    checks = _checks(
        readiness=readiness,
        app_name=materials["app_name"],
        app_description=materials["app_description"],
        company_url=materials["company_url"],
        privacy_policy_url=materials["privacy_policy_url"],
        logo_ready=materials["logo_ready"],
        screenshots_ready=materials["screenshots_ready"],
        test_prompts_ready=materials["test_prompts_ready"],
        test_responses_ready=materials["test_responses_ready"],
        localization_ready=materials["localization_ready"],
        mcp_tool_info_ready=materials["mcp_tool_info_ready"],
        app_management_permissions_confirmed=materials["app_management_permissions_confirmed"],
        security_review_ready=materials["security_review_ready"],
        metadata_snapshot_reviewed=materials["metadata_snapshot_reviewed"],
        submission_confirmations_ready=materials["submission_confirmations_ready"],
        submission_materials=materials_manifest,
    )
    blocker_codes, needs_attention_codes = _reason_codes(checks)
    status = BLOCKED if blocker_codes else NEEDS_ATTENTION if needs_attention_codes else READY
    return {
        "ok": True,
        "source": RELEASE_SUBMISSION_SOURCE,
        "schema_version": RELEASE_SUBMISSION_VERSION,
        "read_only": True,
        "side_effects": False,
        "project_root": os.path.abspath(os.path.expanduser(project_root)),
        "project_name": project_name,
        "public_base_url": readiness.get("public_base_url") or public_base_url,
        "connector_url": readiness.get("connector_url"),
        "observed_at": _iso_now(now),
        "status": status,
        "ready": status == READY,
        "summary": _summary_for(status),
        "checks": checks,
        "blocker_codes": blocker_codes,
        "needs_attention_codes": needs_attention_codes,
        "submission_materials": materials_manifest,
        "required_submission_materials": [
            "app_name",
            "logo",
            "description",
            "company_url",
            "privacy_policy_url",
            "mcp_server_details",
            "tool_information",
            "screenshots",
            "test_prompts_and_responses",
            "localization_information",
            "submission_confirmations",
        ],
        "doc_refs": DOC_REFS,
        "safe_next_action": _safe_next_action(status, blocker_codes, needs_attention_codes),
        "authority_boundary": _authority_boundary(),
        "not_authorized_actions": [
            "create_openai_app_draft",
            "submit_app_for_review",
            "publish_app",
            "call_openai_dashboard_or_api",
            "read_tokens_or_cookies",
            "read_provider_config",
            "release_or_deploy",
        ],
    }


def _checks(
    *,
    readiness: dict[str, Any],
    app_name: str | None,
    app_description: str | None,
    company_url: str | None,
    privacy_policy_url: str | None,
    logo_ready: bool,
    screenshots_ready: bool,
    test_prompts_ready: bool,
    test_responses_ready: bool,
    localization_ready: bool,
    mcp_tool_info_ready: bool,
    app_management_permissions_confirmed: bool,
    security_review_ready: bool,
    metadata_snapshot_reviewed: bool,
    submission_confirmations_ready: bool,
    submission_materials: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    ops_check = readiness.get("ops_check") if isinstance(readiness.get("ops_check"), dict) else {}
    return {
        "product_readiness": _status_check(
            READY if readiness.get("ready") is True else BLOCKED,
            "PRODUCT_READINESS_READY" if readiness.get("ready") is True else "PRODUCT_READINESS_NOT_READY",
            evidence={"status": readiness.get("status"), "primary_blocker": readiness.get("primary_blocker")},
        ),
        "public_mcp_endpoint": _status_check(
            READY if ops_check.get("ops_check_ready") is True else BLOCKED,
            "PUBLIC_MCP_ENDPOINT_READY"
            if ops_check.get("ops_check_ready") is True
            else "PUBLIC_MCP_ENDPOINT_NOT_READY",
        ),
        "apps_connector_smoke": _status_check(
            READY if ops_check.get("connector_smoke_ready") is True else NEEDS_ATTENTION,
            "APPS_CONNECTOR_SMOKE_READY"
            if ops_check.get("connector_smoke_ready") is True
            else "APPS_CONNECTOR_SMOKE_MISSING",
        ),
        "submission_form_assets": _materials_check(
            {
                "app_name": _has_text(app_name),
                "app_description": _has_text(app_description),
                "company_url": _is_https_url(company_url),
                "privacy_policy_url": _is_https_url(privacy_policy_url),
                "logo_ready": bool(logo_ready),
                "screenshots_ready": bool(screenshots_ready),
                "localization_ready": bool(localization_ready),
            }
        ),
        "mcp_tool_information": _status_check(
            READY if mcp_tool_info_ready else NEEDS_ATTENTION,
            "MCP_TOOL_INFORMATION_READY" if mcp_tool_info_ready else "MCP_TOOL_INFORMATION_MISSING",
        ),
        "testing_evidence": _materials_check(
            {
                "test_prompts_ready": bool(test_prompts_ready),
                "test_responses_ready": bool(test_responses_ready),
            }
        ),
        "security_privacy": _status_check(
            READY if security_review_ready and _is_https_url(privacy_policy_url) else NEEDS_ATTENTION,
            "SECURITY_PRIVACY_READY" if security_review_ready and _is_https_url(privacy_policy_url) else "SECURITY_PRIVACY_INCOMPLETE",
        ),
        "app_management_permissions": _status_check(
            READY if app_management_permissions_confirmed else NEEDS_ATTENTION,
            "APP_MANAGEMENT_PERMISSIONS_CONFIRMED"
            if app_management_permissions_confirmed
            else "APP_MANAGEMENT_PERMISSIONS_UNCONFIRMED",
        ),
        "metadata_snapshot": _status_check(
            READY if metadata_snapshot_reviewed else NEEDS_ATTENTION,
            "METADATA_SNAPSHOT_REVIEWED" if metadata_snapshot_reviewed else "METADATA_SNAPSHOT_NOT_REVIEWED",
        ),
        "submission_confirmations": _status_check(
            READY if submission_confirmations_ready else NEEDS_ATTENTION,
            "SUBMISSION_CONFIRMATIONS_READY" if submission_confirmations_ready else "SUBMISSION_CONFIRMATIONS_MISSING",
        ),
        "submission_materials_manifest": _manifest_check(submission_materials),
    }


def _materials_check(materials: dict[str, bool]) -> dict[str, Any]:
    missing = [name for name, present in materials.items() if not present]
    return {
        "status": READY if not missing else NEEDS_ATTENTION,
        "reason_codes": ["MATERIALS_READY"] if not missing else ["SUBMISSION_MATERIALS_MISSING"],
        "missing": missing,
        "present": [name for name, present in materials.items() if present],
    }


def _status_check(status: str, reason_code: str, *, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"status": status, "reason_codes": [reason_code]}
    if evidence is not None:
        payload["evidence"] = evidence
    return payload


def _manifest_check(submission_materials: dict[str, Any]) -> dict[str, Any]:
    ignored = submission_materials.get("ignored_manifest_fields")
    if isinstance(ignored, list) and ignored:
        return {
            "status": NEEDS_ATTENTION,
            "reason_codes": ["SUBMISSION_MATERIALS_MANIFEST_HAS_UNKNOWN_FIELDS"],
            "ignored_fields": ignored,
        }
    if submission_materials.get("source") == "parameters_only":
        return _status_check(
            READY,
            "SUBMISSION_MATERIALS_FROM_PARAMETERS",
            evidence={"source": "parameters_only"},
        )
    return _status_check(
        READY,
        "SUBMISSION_MATERIALS_MANIFEST_ACCEPTED",
        evidence={
            "schema_version": submission_materials.get("schema_version"),
            "manifest_fields": submission_materials.get("manifest_fields"),
        },
    )


def _merge_submission_materials(
    submission_materials: Mapping[str, Any] | None,
    *,
    app_name: str | None,
    app_description: str | None,
    company_url: str | None,
    privacy_policy_url: str | None,
    logo_ready: bool,
    screenshots_ready: bool,
    test_prompts_ready: bool,
    test_responses_ready: bool,
    localization_ready: bool,
    mcp_tool_info_ready: bool,
    app_management_permissions_confirmed: bool,
    security_review_ready: bool,
    metadata_snapshot_reviewed: bool,
    submission_confirmations_ready: bool,
) -> dict[str, Any]:
    manifest = submission_materials if isinstance(submission_materials, Mapping) else {}
    parameter_values = {
        "app_name": app_name,
        "app_description": app_description,
        "company_url": company_url,
        "privacy_policy_url": privacy_policy_url,
        "logo_ready": logo_ready,
        "screenshots_ready": screenshots_ready,
        "test_prompts_ready": test_prompts_ready,
        "test_responses_ready": test_responses_ready,
        "localization_ready": localization_ready,
        "mcp_tool_info_ready": mcp_tool_info_ready,
        "app_management_permissions_confirmed": app_management_permissions_confirmed,
        "security_review_ready": security_review_ready,
        "metadata_snapshot_reviewed": metadata_snapshot_reviewed,
        "submission_confirmations_ready": submission_confirmations_ready,
    }
    effective: dict[str, Any] = {}
    parameter_fields: list[str] = []

    for field in sorted(SUBMISSION_MATERIAL_TEXT_FIELDS):
        parameter_value = parameter_values[field]
        if _has_text(parameter_value if isinstance(parameter_value, str) else None):
            effective[field] = parameter_value
            parameter_fields.append(field)
        else:
            effective[field] = _text_from_manifest(manifest, field)

    for field in sorted(SUBMISSION_MATERIAL_BOOL_FIELDS):
        parameter_value = bool(parameter_values[field])
        if parameter_value:
            effective[field] = True
            parameter_fields.append(field)
        else:
            effective[field] = _bool_from_manifest(manifest, field)

    manifest_fields = sorted(str(key) for key in manifest if str(key) in SUBMISSION_MATERIAL_FIELDS)
    ignored_manifest_fields = sorted(str(key) for key in manifest if str(key) not in SUBMISSION_MATERIAL_FIELDS)
    effective_fields = sorted(
        field
        for field in sorted(SUBMISSION_MATERIAL_TEXT_FIELDS | SUBMISSION_MATERIAL_BOOL_FIELDS)
        if _material_field_present(field, effective.get(field))
    )
    manifest_summary = {
        "source": "manifest_and_parameters"
        if manifest and parameter_fields
        else "manifest"
        if manifest
        else "parameters_only",
        "schema_version": _text_from_manifest(manifest, "schema_version"),
        "manifest_fields": manifest_fields,
        "parameter_fields": sorted(parameter_fields),
        "effective_fields": effective_fields,
        "ignored_manifest_fields": ignored_manifest_fields,
    }
    effective["manifest"] = manifest_summary
    return effective


def _text_from_manifest(manifest: Mapping[str, Any], field: str) -> str | None:
    value = manifest.get(field)
    if isinstance(value, str) and value.strip():
        return value
    return None


def _bool_from_manifest(manifest: Mapping[str, Any], field: str) -> bool:
    return manifest.get(field) is True


def _material_field_present(field: str, value: Any) -> bool:
    if field in SUBMISSION_MATERIAL_TEXT_FIELDS:
        return _has_text(value if isinstance(value, str) else None)
    return value is True


def _reason_codes(checks: dict[str, dict[str, Any]]) -> tuple[list[str], list[str]]:
    blockers: list[str] = []
    needs_attention: list[str] = []
    for check in checks.values():
        codes = [str(code) for code in check.get("reason_codes", []) if isinstance(code, str)]
        if check.get("status") == BLOCKED:
            blockers.extend(codes)
        elif check.get("status") == NEEDS_ATTENTION:
            needs_attention.extend(codes)
    return sorted(set(blockers)), sorted(set(needs_attention))


def _safe_next_action(status: str, blocker_codes: list[str], needs_attention_codes: list[str]) -> dict[str, Any]:
    if status == READY:
        return {
            "action": "open_openai_dashboard_submission_form",
            "why": "Local readiness evidence is complete. Human operator still submits manually in the OpenAI dashboard.",
        }
    if blocker_codes:
        return {
            "action": "fix_product_readiness_before_submission",
            "tool": "get_product_readiness_status",
            "arguments": {},
            "why": "Submission should not start while product readiness or public MCP endpoint is blocked.",
        }
    return {
        "action": "complete_submission_materials",
        "missing_reason_codes": needs_attention_codes,
        "why": "Submission materials, testing evidence, permissions, or confirmations are incomplete.",
    }


def _summary_for(status: str) -> str:
    if status == READY:
        return "Release/App submission readiness evidence is complete; submit manually from the OpenAI dashboard."
    if status == BLOCKED:
        return "Release/App submission is blocked by product readiness or public endpoint evidence."
    return "Release/App submission needs operator-supplied materials, testing, permission, or confirmation evidence."


def _authority_boundary() -> dict[str, bool]:
    return {
        "read_only": True,
        "side_effects": False,
        "does_not_create_openai_app_draft": True,
        "does_not_submit_app_for_review": True,
        "does_not_publish_app": True,
        "does_not_call_openai_dashboard_or_api": True,
        "does_not_read_tokens_or_cookies": True,
        "does_not_read_provider_config": True,
        "does_not_release_or_deploy": True,
    }


def _has_text(value: str | None) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_https_url(value: str | None) -> bool:
    return isinstance(value, str) and value.strip().lower().startswith("https://")


def _iso_now(now: datetime | None) -> str:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
