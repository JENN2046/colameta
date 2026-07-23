"""Immutable, manifest-bound validation-contract helpers.

An independent review manifest may declare validation commands, but that
declaration alone must never become execution authority. This module carries
the small, typed bridge between the short-lived review session and the normal
MCP validation manager:

* a source can only name one already-inspected manifest;
* the effective command specs are hashed together with the review binding;
* the resulting contract is safe to persist inside a normal validation preview;
* callers can recognise that a later run still needs a fresh manifest
  verification.

Command parsing and execution policy intentionally remain in
mcp_validation_run. These helpers only describe immutable data.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from typing import Any

from runner.review_manifest import StoredReviewManifest


REVIEW_MANIFEST_VALIDATION_SOURCE_SCHEMA_VERSION = (
    "colameta.review_manifest_validation_source.v1"
)
REVIEW_MANIFEST_VALIDATION_CONTRACT_SCHEMA_VERSION = (
    "colameta.review_manifest_validation_contract.v1"
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_HANDLE_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
_MAX_MANIFEST_COMMANDS = 32
_MIN_TIMEOUT_SECONDS = 10
_MAX_TIMEOUT_SECONDS = 900


def canonical_manifest_validation_sha256(value: object) -> str:
    """Return the SHA-256 of a canonical JSON validation-contract fragment."""

    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_review_manifest_validation_source(
    stored: StoredReviewManifest,
) -> dict[str, Any]:
    """Project one verified review session into the validation-parser input."""

    return {
        "schema_version": REVIEW_MANIFEST_VALIDATION_SOURCE_SCHEMA_VERSION,
        "review_manifest_id": stored.handle.review_manifest_id,
        "manifest_sha256": stored.handle.manifest_sha256,
        "review_unit": stored.context_binding["review_unit"],
        "workflow_intent": stored.context_binding["workflow_intent"],
        "review_context_binding": dict(stored.context_binding),
        "subjects": [
            {"path": subject.path, "sha256": subject.sha256}
            for subject in stored.subjects
        ],
        "acceptance_commands": list(stored.manifest.get("acceptance_commands") or []),
    }


def normalize_review_manifest_validation_source(value: Any) -> dict[str, Any] | None:
    """Validate a source passed across the review/validation module boundary.

    This function accepts only the source shape created above. It deliberately
    does not read files or trust a caller-provided project root; the MCP server
    owns those checks immediately before preview and run.
    """

    if not isinstance(value, dict):
        return None
    required = {
        "schema_version",
        "review_manifest_id",
        "manifest_sha256",
        "review_unit",
        "workflow_intent",
        "review_context_binding",
        "subjects",
        "acceptance_commands",
    }
    if set(value) != required:
        return None
    if value.get("schema_version") != REVIEW_MANIFEST_VALIDATION_SOURCE_SCHEMA_VERSION:
        return None
    review_manifest_id = value.get("review_manifest_id")
    manifest_sha256 = value.get("manifest_sha256")
    review_unit = value.get("review_unit")
    workflow_intent = value.get("workflow_intent")
    if not isinstance(review_manifest_id, str) or _HANDLE_RE.fullmatch(review_manifest_id) is None:
        return None
    if not isinstance(manifest_sha256, str) or _SHA256_RE.fullmatch(manifest_sha256.lower()) is None:
        return None
    if not isinstance(review_unit, str) or not review_unit.strip() or len(review_unit.strip()) > 160:
        return None
    if workflow_intent != "independent_review":
        return None

    review_context = value.get("review_context_binding")
    expected_context_keys = {
        "project_name",
        "branch",
        "head",
        "runner_plan",
        "current_version",
        "review_unit",
        "workflow_intent",
    }
    if not isinstance(review_context, dict) or set(review_context) != expected_context_keys:
        return None
    if (
        review_context.get("review_unit") != review_unit.strip()
        or review_context.get("workflow_intent") != workflow_intent
    ):
        return None
    runner_plan = review_context.get("runner_plan")
    if (
        not isinstance(runner_plan, dict)
        or set(runner_plan) != {"mode", "plan_sha256"}
        or runner_plan.get("mode") not in {"managed", "source-only"}
    ):
        return None
    plan_sha256 = runner_plan.get("plan_sha256")
    if plan_sha256 is not None and (
        not isinstance(plan_sha256, str)
        or _SHA256_RE.fullmatch(plan_sha256.lower()) is None
    ):
        return None

    subjects_value = value.get("subjects")
    if not isinstance(subjects_value, list) or not subjects_value or len(subjects_value) > 64:
        return None
    subjects: list[dict[str, str]] = []
    seen_paths: set[str] = set()
    for subject in subjects_value:
        if not isinstance(subject, dict) or set(subject) != {"path", "sha256"}:
            return None
        path = subject.get("path")
        sha256 = subject.get("sha256")
        if (
            not isinstance(path, str)
            or not path
            or path.startswith("/")
            or "\\" in path
            or ".." in path.split("/")
            or path in seen_paths
            or not isinstance(sha256, str)
            or _SHA256_RE.fullmatch(sha256.lower()) is None
        ):
            return None
        seen_paths.add(path)
        subjects.append({"path": path, "sha256": sha256.lower()})

    raw_commands = value.get("acceptance_commands")
    if not isinstance(raw_commands, list) or len(raw_commands) > _MAX_MANIFEST_COMMANDS:
        return None
    acceptance_commands: list[dict[str, Any]] = []
    for raw in raw_commands:
        if not isinstance(raw, dict) or "command" not in raw:
            return None
        if set(raw) - {"command", "timeout_seconds", "continue_on_failure"}:
            return None
        command = raw.get("command")
        if not isinstance(command, str) or not command.strip() or len(command.strip()) > 2000:
            return None
        item: dict[str, Any] = {"command": command.strip()}
        if "timeout_seconds" in raw:
            timeout_seconds = raw.get("timeout_seconds")
            if (
                isinstance(timeout_seconds, bool)
                or not isinstance(timeout_seconds, int)
                or not 1 <= timeout_seconds <= 3600
            ):
                return None
            item["timeout_seconds"] = timeout_seconds
        if "continue_on_failure" in raw:
            continue_on_failure = raw.get("continue_on_failure")
            if not isinstance(continue_on_failure, bool):
                return None
            item["continue_on_failure"] = continue_on_failure
        acceptance_commands.append(item)

    normalized_context = dict(review_context)
    normalized_context["runner_plan"] = {
        "mode": runner_plan["mode"],
        "plan_sha256": (
            plan_sha256.lower() if isinstance(plan_sha256, str) else None
        ),
    }
    return {
        "schema_version": REVIEW_MANIFEST_VALIDATION_SOURCE_SCHEMA_VERSION,
        "review_manifest_id": review_manifest_id,
        "manifest_sha256": manifest_sha256.lower(),
        "review_unit": review_unit.strip(),
        "workflow_intent": workflow_intent,
        "review_context_binding": normalized_context,
        "subjects": subjects,
        "acceptance_commands": acceptance_commands,
    }


def build_review_manifest_validation_contract(
    source: dict[str, Any],
    command_specs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Bind effective, parser-approved argv specs to one review manifest."""

    normalized_source = normalize_review_manifest_validation_source(source)
    if normalized_source is None:
        raise ValueError("invalid manifest validation source")
    if len(command_specs) > _MAX_MANIFEST_COMMANDS:
        raise ValueError("too many manifest validation command specs")
    normalized_specs: list[dict[str, Any]] = []
    for spec in command_specs:
        if not isinstance(spec, dict) or set(spec) != {
            "argv",
            "timeout_seconds",
            "continue_on_failure",
        }:
            raise ValueError("invalid manifest validation command spec")
        argv = spec.get("argv")
        timeout_seconds = spec.get("timeout_seconds")
        continue_on_failure = spec.get("continue_on_failure")
        if (
            not isinstance(argv, list)
            or not argv
            or not all(isinstance(part, str) and part for part in argv)
            or isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, int)
            or not _MIN_TIMEOUT_SECONDS <= timeout_seconds <= _MAX_TIMEOUT_SECONDS
            or not isinstance(continue_on_failure, bool)
        ):
            raise ValueError("invalid manifest validation command spec")
        normalized_specs.append(
            {
                "argv": list(argv),
                "timeout_seconds": timeout_seconds,
                "continue_on_failure": continue_on_failure,
            }
        )

    command_specs_sha256 = canonical_manifest_validation_sha256(normalized_specs)
    contract = {
        "schema_version": REVIEW_MANIFEST_VALIDATION_CONTRACT_SCHEMA_VERSION,
        "review_manifest_id": normalized_source["review_manifest_id"],
        "manifest_sha256": normalized_source["manifest_sha256"],
        "review_unit": normalized_source["review_unit"],
        "workflow_intent": normalized_source["workflow_intent"],
        "review_context_binding": normalized_source["review_context_binding"],
        "subjects": normalized_source["subjects"],
        "command_specs": normalized_specs,
        "command_specs_sha256": command_specs_sha256,
    }
    return {
        **contract,
        "contract_sha256": canonical_manifest_validation_sha256(contract),
    }


def manifest_validation_contract_from_artifact(value: Any) -> dict[str, Any] | None:
    """Return a verified contract from a validation-preview artifact, if any."""

    if not isinstance(value, dict):
        return None
    contract = value.get("manifest_validation")
    if not isinstance(contract, dict):
        return None
    expected_keys = {
        "schema_version",
        "review_manifest_id",
        "manifest_sha256",
        "review_unit",
        "workflow_intent",
        "review_context_binding",
        "subjects",
        "command_specs",
        "command_specs_sha256",
        "contract_sha256",
    }
    if set(contract) != expected_keys:
        return None
    if contract.get("schema_version") != REVIEW_MANIFEST_VALIDATION_CONTRACT_SCHEMA_VERSION:
        return None
    command_specs = contract.get("command_specs")
    try:
        base = {
            key: contract[key]
            for key in expected_keys
            if key != "contract_sha256"
        }
        expected_contract_sha256 = canonical_manifest_validation_sha256(base)
        expected_specs_sha256 = canonical_manifest_validation_sha256(command_specs)
    except (TypeError, ValueError):
        return None
    if (
        not isinstance(contract.get("contract_sha256"), str)
        or not isinstance(contract.get("command_specs_sha256"), str)
        or not hmac.compare_digest(contract["contract_sha256"], expected_contract_sha256)
        or not hmac.compare_digest(contract["command_specs_sha256"], expected_specs_sha256)
    ):
        return None
    source = {
        "schema_version": REVIEW_MANIFEST_VALIDATION_SOURCE_SCHEMA_VERSION,
        "review_manifest_id": contract.get("review_manifest_id"),
        "manifest_sha256": contract.get("manifest_sha256"),
        "review_unit": contract.get("review_unit"),
        "workflow_intent": contract.get("workflow_intent"),
        "review_context_binding": contract.get("review_context_binding"),
        "subjects": contract.get("subjects"),
        # Source parsing has already happened. An empty declaration is enough
        # for the structural source-binding check at this stage.
        "acceptance_commands": [],
    }
    normalized_source = normalize_review_manifest_validation_source(source)
    if normalized_source is None:
        return None
    try:
        rebuilt = build_review_manifest_validation_contract(
            normalized_source,
            command_specs if isinstance(command_specs, list) else [],
        )
    except (TypeError, ValueError):
        return None
    if not hmac.compare_digest(rebuilt["contract_sha256"], contract["contract_sha256"]):
        return None
    return dict(contract)
