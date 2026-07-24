"""Bounded, operator-confirmed evidence for the P1 client release gate.

The P1 gate intentionally does not accept an arbitrary ``passed=True`` value
from a ChatGPT client.  Some of its inputs are intrinsically external to the
local server (for example what a ChatGPT development session displayed).  This
module records those observations only through a short-lived preview followed
by an explicit local operator confirmation.  The stored receipt is integrity
checked, candidate-bound, freshness-bounded, and deliberately *not* a stable
replacement authorization.

No raw transcript, URL, OAuth token, cookie, tunnel log, or provider response
is accepted or persisted here.  External observations remain labelled
``operator_attested`` rather than being misrepresented as server-observed
facts.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from runner._internal_utils import write_json_atomic
from runner.mcp_commander_public import COMMANDER_EXPOSED_TOOLS
from runner.runner_paths import resolve_project_runner_path


P1_RELEASE_EVIDENCE_SOURCE = "p1_release_evidence"
P1_RELEASE_EVIDENCE_SCHEMA_VERSION = "colameta.p1_release_evidence.v1"
P1_RELEASE_EVIDENCE_PREVIEW_SCHEMA_VERSION = "colameta.p1_release_evidence_preview.v1"
P1_RELEASE_EVIDENCE_RECEIPT_SCHEMA_VERSION = "colameta.p1_release_evidence_receipt.v1"
P1_RELEASE_EVIDENCE_PREVIEW_TTL_SECONDS = 1800
P1_RELEASE_EVIDENCE_MAX_AGE_SECONDS = 24 * 60 * 60
P1_RELEASE_EVIDENCE_MAX_RECEIPTS = 64
P1_RELEASE_EVIDENCE_PREVIEWS_DIR = os.path.join("runtime", "p1-release-evidence-previews")
P1_RELEASE_EVIDENCE_RECEIPTS_DIR = os.path.join("runtime", "p1-release-evidence")

P1_REQUIRED_LOCAL_VALIDATION_COMMANDS = (
    "pytest",
    "self_hosting_smoke",
    "compileall",
    "ruff",
    "git_diff_check",
)
P1_EVIDENCE_CHECK_IDS = (
    "full_local_validation",
    "runtime_provenance",
    "connector_oauth",
    "current_facts",
    "live_chatgpt_development_acceptance",
)

_COMMIT_RE = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_OPAQUE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
_PREVIEW_ID_RE = re.compile(r"^[A-Za-z0-9_-]{12,128}$")


class P1ReleaseEvidenceError(ValueError):
    """A controlled validation failure for release-evidence input."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


def p1_release_evidence_input_schema() -> dict[str, Any]:
    """Return the closed local-operator schema without exposing a public tool."""

    head = {"type": "string", "pattern": "^[0-9a-fA-F]{40,128}$"}
    sha256 = {"type": "string", "pattern": "^[0-9a-fA-F]{64}$"}
    observed_at = {"type": "string", "format": "date-time", "maxLength": 64}
    inventory = {
        "type": "array",
        "minItems": len(COMMANDER_EXPOSED_TOOLS),
        "maxItems": len(COMMANDER_EXPOSED_TOOLS),
        "items": {"type": "string", "maxLength": 128},
    }
    return {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["inspect", "status", "preview", "apply", "discard"],
                "description": "inspect/status 只读；preview 绑定 sanitized evidence；apply 需显式确认并仅写本地 runtime receipt；discard 丢弃 preview。",
            },
            "project_name": {
                "type": "string",
                "description": "服务模式下指定已登记 managed project_name。",
            },
            "candidate_head": {
                **head,
                "description": "精确候选 Git commit；preview 必填，status/inspect 可选。",
            },
            "preview_id": {
                "type": "string",
                "description": "apply/discard 必填；来自 preview。",
            },
            "confirm_release_evidence": {
                "type": "boolean",
                "description": "apply 必须为 true。它只确认受控 evidence receipt，不授权 stable replacement。",
            },
            "full_local_validation": {
                "type": "object",
                "properties": {
                    "observed_at": observed_at,
                    "candidate_head": head,
                    "commands": {
                        "type": "object",
                        "properties": {
                            name: {"type": "string", "const": "passed"}
                            for name in P1_REQUIRED_LOCAL_VALIDATION_COMMANDS
                        },
                        "required": list(P1_REQUIRED_LOCAL_VALIDATION_COMMANDS),
                        "additionalProperties": False,
                    },
                },
                "required": ["observed_at", "candidate_head", "commands"],
                "additionalProperties": False,
            },
            "runtime_provenance": {
                "type": "object",
                "properties": {
                    "observed_at": observed_at,
                    "candidate_head": head,
                    "loaded_runtime_head": head,
                    "runtime_project_checkout_head": head,
                    "runtime_loaded_code_stale": {"type": "boolean", "const": False},
                    "reload_needed_for_verification": {"type": "boolean", "const": False},
                    "installed_package_matches_project_checkout": {"type": "boolean", "const": True},
                },
                "required": [
                    "observed_at",
                    "candidate_head",
                    "loaded_runtime_head",
                    "runtime_project_checkout_head",
                    "runtime_loaded_code_stale",
                    "reload_needed_for_verification",
                    "installed_package_matches_project_checkout",
                ],
                "additionalProperties": False,
            },
            "connector_oauth": {
                "type": "object",
                "properties": {
                    "observed_at": observed_at,
                    "candidate_head": head,
                    "connector_reachable": {"type": "boolean", "const": True},
                    "oauth_authorized": {"type": "boolean", "const": True},
                    "visible_tool_inventory": inventory,
                },
                "required": [
                    "observed_at",
                    "candidate_head",
                    "connector_reachable",
                    "oauth_authorized",
                    "visible_tool_inventory",
                ],
                "additionalProperties": False,
            },
            "current_facts": {
                "type": "object",
                "properties": {
                    "observed_at": observed_at,
                    "candidate_head": head,
                    "artifact_id": {"type": "string", "pattern": "^[A-Za-z0-9_-]{16,128}$"},
                    "content_sha256": sha256,
                    "expires_at": observed_at,
                    "canonical_state_sha256": sha256,
                    "canonical_state_semantic_sha256": sha256,
                    "snapshot_json_sha256": sha256,
                    "freshness_current_observation": {"type": "boolean", "const": True},
                    "unresolved_critical_blocker_count": {"type": "integer", "minimum": 0, "maximum": 0},
                },
                "required": [
                    "observed_at",
                    "candidate_head",
                    "artifact_id",
                    "content_sha256",
                    "expires_at",
                    "canonical_state_sha256",
                    "canonical_state_semantic_sha256",
                    "snapshot_json_sha256",
                    "freshness_current_observation",
                    "unresolved_critical_blocker_count",
                ],
                "additionalProperties": False,
            },
            "live_chatgpt_development_acceptance": {
                "type": "object",
                "properties": {
                    "observed_at": observed_at,
                    "candidate_head": head,
                    "visible_tool_inventory": inventory,
                    "context_binding_mismatch_error_code": {"type": "string", "const": "CONTEXT_BINDING_MISMATCH"},
                    "review_manifest": {
                        "type": "object",
                        "properties": {
                            "manifest_sha256": sha256,
                            "expires_at": observed_at,
                            "subject_count": {"type": "integer", "minimum": 1, "maximum": 64},
                            "page_count": {"type": "integer", "minimum": 1, "maximum": 4096},
                            "all_subject_pages_read": {"type": "boolean", "const": True},
                            "page_ranges_contiguous": {"type": "boolean", "const": True},
                            "expiry_continuity": {"type": "boolean", "const": True},
                            "verify_context_binding": {"type": "string", "const": "matched"},
                            "verify_subject_hashes": {"type": "string", "const": "matched"},
                        },
                        "required": [
                            "manifest_sha256",
                            "expires_at",
                            "subject_count",
                            "page_count",
                            "all_subject_pages_read",
                            "page_ranges_contiguous",
                            "expiry_continuity",
                            "verify_context_binding",
                            "verify_subject_hashes",
                        ],
                        "additionalProperties": False,
                    },
                    "result_artifact": {
                        "type": "object",
                        "properties": {
                            "artifact_id": {"type": "string", "pattern": "^[A-Za-z0-9_-]{16,128}$"},
                            "content_sha256": sha256,
                            "expires_at": observed_at,
                            "page_count": {"type": "integer", "minimum": 1, "maximum": 4096},
                            "all_pages_read": {"type": "boolean", "const": True},
                            "page_ranges_contiguous": {"type": "boolean", "const": True},
                            "expiry_continuity": {"type": "boolean", "const": True},
                            "typed_read_tool": {"type": "string", "const": "read_result_artifact"},
                        },
                        "required": [
                            "artifact_id",
                            "content_sha256",
                            "expires_at",
                            "page_count",
                            "all_pages_read",
                            "page_ranges_contiguous",
                            "expiry_continuity",
                            "typed_read_tool",
                        ],
                        "additionalProperties": False,
                    },
                    "resources_read_used": {"type": "boolean", "const": False},
                    "all_calls_read_only": {"type": "boolean", "const": True},
                },
                "required": [
                    "observed_at",
                    "candidate_head",
                    "visible_tool_inventory",
                    "context_binding_mismatch_error_code",
                    "review_manifest",
                    "result_artifact",
                    "resources_read_used",
                    "all_calls_read_only",
                ],
                "additionalProperties": False,
            },
        },
        "required": ["action"],
        "additionalProperties": False,
    }


class P1ReleaseEvidenceManager:
    """Create and persist exact-candidate P1 evidence receipts.

    The manager is only wired to the normal/loopback MCP profile.  Its apply
    step requires ``mcp:commit`` and an explicit boolean confirmation, but it
    writes only an ignored runtime receipt.  It cannot replace stable, push,
    run validation, or modify connector/OAuth configuration.
    """

    def __init__(
        self,
        project_root: str,
        *,
        now_fn: Callable[[], datetime] | None = None,
        preview_ttl_seconds: int = P1_RELEASE_EVIDENCE_PREVIEW_TTL_SECONDS,
    ) -> None:
        self.project_root = _normalize_project_root(project_root)
        self._now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self._preview_ttl_seconds = max(1, int(preview_ttl_seconds))

    def handle(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        normalized = action.strip().lower() if isinstance(action, str) else ""
        if normalized in {"inspect", "status"}:
            result = get_p1_release_evidence_status(
                self.project_root,
                candidate_head=_clean_optional_text(params.get("candidate_head")),
                now=self._now(),
            )
            return {"action": normalized, **result}
        if normalized == "preview":
            return self.preview(params)
        if normalized == "apply":
            return self.apply(params)
        if normalized == "discard":
            return self.discard(params)
        return _manager_error(
            normalized or "unknown",
            "UNKNOWN_ACTION",
            "action supports inspect, status, preview, apply, or discard.",
        )

    def preview(self, params: Mapping[str, Any]) -> dict[str, Any]:
        if not self._runtime_storage_is_safe():
            return _manager_error(
                "preview",
                "RUNTIME_STORAGE_UNSAFE",
                "P1 release-evidence storage resolves outside the project Runner runtime directory.",
            )
        candidate_head = _resolve_commit(self.project_root, _clean_optional_text(params.get("candidate_head")))
        if not candidate_head:
            return _manager_error(
                "preview",
                "CANDIDATE_COMMIT_UNAVAILABLE",
                "preview requires a resolvable exact candidate_head commit.",
            )
        if _resolve_commit(self.project_root, "HEAD") != candidate_head:
            return _manager_error(
                "preview",
                "CANDIDATE_NOT_CURRENT_HEAD",
                "Candidate commit is not the current project HEAD.",
                candidate_head=candidate_head,
            )
        try:
            observations = _normalize_observations(
                {check_id: params.get(check_id) for check_id in P1_EVIDENCE_CHECK_IDS},
                candidate_head,
            )
        except P1ReleaseEvidenceError as exc:
            return _manager_error("preview", exc.code, exc.message, **exc.details)
        evaluation = _evaluate_observations(observations, candidate_head, self._now())
        if evaluation["complete"] is not True:
            return _manager_error(
                "preview",
                "P1_RELEASE_EVIDENCE_NOT_FRESH_OR_COMPLETE",
                "All P1 evidence observations must be complete, candidate-bound, and fresh before preview.",
                checks=evaluation["checks"],
            )

        now = self._now()
        preview_id = f"p1e_{secrets.token_urlsafe(18)}"
        preview = {
            "schema_version": P1_RELEASE_EVIDENCE_PREVIEW_SCHEMA_VERSION,
            "artifact_kind": "p1_release_evidence_preview",
            "preview_id": preview_id,
            "project_root": self.project_root,
            "candidate_head": candidate_head,
            "created_at": _iso(now),
            "expires_at": _iso(now + timedelta(seconds=self._preview_ttl_seconds)),
            "observations": observations,
            "authority_boundary": _authority_boundary(),
        }
        preview["preview_digest"] = _canonical_sha256(preview)
        try:
            write_json_atomic(self._preview_path(preview_id), preview)
        except OSError:
            return _manager_error(
                "preview",
                "PREVIEW_WRITE_FAILED",
                "P1 release-evidence preview could not be persisted.",
            )
        return {
            "ok": True,
            "source": P1_RELEASE_EVIDENCE_SOURCE,
            "schema_version": P1_RELEASE_EVIDENCE_PREVIEW_SCHEMA_VERSION,
            "action": "preview",
            "status": "preview_ready",
            "read_only": False,
            "side_effects": True,
            "writes_preview_artifact_only": True,
            "preview_id": preview_id,
            "preview_digest": preview["preview_digest"],
            "candidate_head": candidate_head,
            "expires_at": preview["expires_at"],
            "evidence_summary": _evidence_summary(observations),
            "checks": evaluation["checks"],
            "confirmation": {
                "required": True,
                "action": "apply",
                "preview_id": preview_id,
                "candidate_head": candidate_head,
                "confirm_release_evidence": True,
                "required_scope": "mcp:commit",
            },
            "authority_boundary": _authority_boundary(),
        }

    def apply(self, params: Mapping[str, Any]) -> dict[str, Any]:
        preview_id = _valid_preview_id(params.get("preview_id"))
        if not preview_id:
            return _manager_error("apply", "PREVIEW_ID_INVALID", "apply requires a valid preview_id.")
        if params.get("confirm_release_evidence") is not True:
            return _manager_error(
                "apply",
                "P1_RELEASE_EVIDENCE_CONFIRMATION_REQUIRED",
                "apply requires confirm_release_evidence=true.",
            )
        if not self._runtime_storage_is_safe():
            return _manager_error(
                "apply",
                "RUNTIME_STORAGE_UNSAFE",
                "P1 release-evidence storage resolves outside the project Runner runtime directory.",
            )
        preview = self._read_preview(preview_id)
        if preview is None:
            return _manager_error("apply", "PREVIEW_NOT_FOUND", "P1 release-evidence preview was not found.")
        error = self._validate_preview(preview, preview_id)
        if error is not None:
            return error
        if _is_expired(preview.get("expires_at"), self._now()):
            return _manager_error("apply", "PREVIEW_EXPIRED", "P1 release-evidence preview has expired.")
        candidate_head = str(preview["candidate_head"])
        requested_candidate = _clean_optional_text(params.get("candidate_head"))
        if requested_candidate:
            resolved_requested = _resolve_commit(self.project_root, requested_candidate)
            if resolved_requested != candidate_head:
                return _manager_error(
                    "apply",
                    "PREVIEW_CANDIDATE_MISMATCH",
                    "Requested candidate_head does not match the preview-bound candidate.",
                    candidate_head=candidate_head,
                )
        if _resolve_commit(self.project_root, "HEAD") != candidate_head:
            return _manager_error(
                "apply",
                "CANDIDATE_NOT_CURRENT_HEAD",
                "Candidate commit changed after preview; create a new preview.",
                candidate_head=candidate_head,
            )
        raw_observations = preview.get("observations")
        try:
            observations = _normalize_observations(raw_observations, candidate_head)
        except P1ReleaseEvidenceError as exc:
            return _manager_error("apply", exc.code, exc.message, **exc.details)
        evaluation = _evaluate_observations(observations, candidate_head, self._now())
        if evaluation["complete"] is not True:
            return _manager_error(
                "apply",
                "P1_RELEASE_EVIDENCE_STALE_OR_CHANGED",
                "P1 evidence is no longer fresh or complete; create a new preview.",
                checks=evaluation["checks"],
            )

        now = self._now()
        receipt_id = f"p1_release_evidence_{candidate_head[:12]}_{now.strftime('%Y%m%dT%H%M%SZ')}_{secrets.token_urlsafe(6)}"
        receipt = {
            "schema_version": P1_RELEASE_EVIDENCE_RECEIPT_SCHEMA_VERSION,
            "receipt_id": receipt_id,
            "source": P1_RELEASE_EVIDENCE_SOURCE,
            "project_root": self.project_root,
            "candidate_head": candidate_head,
            "recorded_at": _iso(now),
            "preview_id": preview_id,
            "preview_digest": preview.get("preview_digest"),
            "operator_confirmation": {
                "confirmed": True,
                "confirmation_kind": "explicit_preview_apply",
                "external_observations": "operator_attested",
            },
            "observations": observations,
            "authority_boundary": _authority_boundary(),
        }
        receipt["receipt_digest"] = _receipt_digest(receipt)
        path = self._receipt_path(candidate_head, receipt_id)
        if not _is_safe_runtime_path(self.project_root, path):
            return _manager_error(
                "apply",
                "RUNTIME_STORAGE_UNSAFE",
                "P1 release-evidence receipt path is unsafe.",
            )
        try:
            created = _write_json_exclusive(path, receipt)
        except OSError:
            return _manager_error("apply", "RECEIPT_WRITE_FAILED", "P1 release-evidence receipt could not be persisted.")
        if not created:
            return _manager_error(
                "apply",
                "RECEIPT_ID_CONFLICT",
                "P1 release-evidence receipt ID already exists; preserve it and create a new preview.",
            )
        self._delete_preview(preview_id)
        evidence_status = get_p1_release_evidence_status(
            self.project_root,
            candidate_head=candidate_head,
            now=self._now(),
        )
        if evidence_status.get("receipt_integrity_verified") is not True:
            return _manager_error(
                "apply",
                "RECEIPT_VERIFICATION_FAILED",
                "Persisted P1 release-evidence receipt did not verify.",
            )
        return {
            "ok": True,
            "source": P1_RELEASE_EVIDENCE_SOURCE,
            "schema_version": P1_RELEASE_EVIDENCE_RECEIPT_SCHEMA_VERSION,
            "action": "apply",
            "status": "recorded",
            "read_only": False,
            "side_effects": True,
            "candidate_head": candidate_head,
            "receipt_id": receipt_id,
            "receipt_digest": receipt["receipt_digest"],
            "receipt_path": _relative_runtime_path(self.project_root, path),
            "evidence_status": evidence_status,
            "authority_boundary": _authority_boundary(),
        }

    def discard(self, params: Mapping[str, Any]) -> dict[str, Any]:
        preview_id = _valid_preview_id(params.get("preview_id"))
        if not preview_id:
            return _manager_error("discard", "PREVIEW_ID_INVALID", "discard requires a valid preview_id.")
        if not self._runtime_storage_is_safe():
            return _manager_error(
                "discard",
                "RUNTIME_STORAGE_UNSAFE",
                "P1 release-evidence storage resolves outside the project Runner runtime directory.",
            )
        existed = os.path.isfile(self._preview_path(preview_id))
        self._delete_preview(preview_id)
        return {
            "ok": True,
            "source": P1_RELEASE_EVIDENCE_SOURCE,
            "schema_version": P1_RELEASE_EVIDENCE_PREVIEW_SCHEMA_VERSION,
            "action": "discard",
            "status": "discarded" if existed else "not_found",
            "preview_id": preview_id,
            "authority_boundary": _authority_boundary(),
        }

    def _now(self) -> datetime:
        value = self._now_fn()
        return _normalize_datetime(value)

    def _preview_path(self, preview_id: str) -> str:
        return resolve_project_runner_path(
            self.project_root,
            P1_RELEASE_EVIDENCE_PREVIEWS_DIR,
            f"{preview_id}.json",
        )

    def _receipt_path(self, candidate_head: str, receipt_id: str) -> str:
        return resolve_project_runner_path(
            self.project_root,
            P1_RELEASE_EVIDENCE_RECEIPTS_DIR,
            candidate_head,
            f"{receipt_id}.json",
        )

    def _runtime_storage_is_safe(self) -> bool:
        probe = resolve_project_runner_path(
            self.project_root,
            P1_RELEASE_EVIDENCE_PREVIEWS_DIR,
            ".storage-probe.json",
        )
        return _is_safe_runtime_path(self.project_root, probe)

    def _read_preview(self, preview_id: str) -> dict[str, Any] | None:
        path = self._preview_path(preview_id)
        if not _is_safe_runtime_path(self.project_root, path):
            return None
        return _read_json_object(path)

    def _validate_preview(self, preview: Mapping[str, Any], preview_id: str) -> dict[str, Any] | None:
        if (
            preview.get("schema_version") != P1_RELEASE_EVIDENCE_PREVIEW_SCHEMA_VERSION
            or preview.get("artifact_kind") != "p1_release_evidence_preview"
            or preview.get("preview_id") != preview_id
            or preview.get("project_root") != self.project_root
            or not _is_commit(preview.get("candidate_head"))
        ):
            return _manager_error("apply", "PREVIEW_BINDING_MISMATCH", "P1 release-evidence preview binding is invalid.")
        expected = _canonical_sha256({key: value for key, value in preview.items() if key != "preview_digest"})
        if not secrets.compare_digest(str(preview.get("preview_digest") or ""), expected):
            return _manager_error("apply", "PREVIEW_DIGEST_MISMATCH", "P1 release-evidence preview digest is invalid.")
        return None

    def _delete_preview(self, preview_id: str) -> None:
        try:
            os.unlink(self._preview_path(preview_id))
        except FileNotFoundError:
            pass


def get_p1_release_evidence_status(
    project_root: str,
    *,
    candidate_head: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Read and re-evaluate the newest exact-candidate P1 evidence receipt."""

    root = _normalize_project_root(project_root)
    observed_now = _normalize_datetime(now or datetime.now(timezone.utc))
    candidate = _resolve_commit(root, candidate_head)
    if not candidate:
        return _status_error(
            "CANDIDATE_COMMIT_UNAVAILABLE",
            "Candidate commit could not be resolved for P1 release evidence.",
        )
    receipts_dir = resolve_project_runner_path(root, P1_RELEASE_EVIDENCE_RECEIPTS_DIR, candidate)
    if not _is_safe_runtime_path(root, receipts_dir):
        return _status_error(
            "RUNTIME_STORAGE_UNSAFE",
            "P1 release-evidence storage resolves outside the project Runner runtime directory.",
            candidate_head=candidate,
        )
    if not os.path.isdir(receipts_dir):
        return _missing_status(root, candidate)
    try:
        paths = [
            path
            for path in Path(receipts_dir).glob("*.json")
            if _is_safe_runtime_path(root, str(path))
        ]
    except OSError:
        return _status_error(
            "RECEIPT_DIRECTORY_UNREADABLE",
            "P1 release-evidence receipt directory could not be read.",
            candidate_head=candidate,
        )
    if not paths:
        return _missing_status(root, candidate)
    if len(paths) > P1_RELEASE_EVIDENCE_MAX_RECEIPTS:
        return _status_error(
            "RECEIPT_COUNT_EXCEEDED",
            "Too many P1 release-evidence receipts exist for one candidate.",
            candidate_head=candidate,
        )

    records: list[tuple[datetime, Path, dict[str, Any]]] = []
    for path in paths:
        receipt = _read_json_object(str(path))
        if receipt is None:
            return _status_error(
                "RECEIPT_UNREADABLE",
                "A P1 release-evidence receipt is unreadable.",
                candidate_head=candidate,
            )
        recorded_at = _parse_iso(receipt.get("recorded_at"))
        if recorded_at is None:
            return _status_error(
                "RECEIPT_INVALID",
                "A P1 release-evidence receipt has an invalid recorded_at value.",
                candidate_head=candidate,
            )
        records.append((recorded_at, path, receipt))
    _, path, receipt = max(records, key=lambda item: item[0])
    integrity_error = _validate_receipt(receipt, root, candidate)
    if integrity_error is not None:
        return _status_error(
            integrity_error["error_code"],
            integrity_error["message"],
            candidate_head=candidate,
        )
    try:
        observations = _normalize_observations(receipt.get("observations"), candidate)
    except P1ReleaseEvidenceError as exc:
        return _status_error(exc.code, exc.message, candidate_head=candidate)
    evaluation = _evaluate_observations(observations, candidate, observed_now)
    current_head = _resolve_commit(root, "HEAD")
    candidate_current = current_head == candidate
    checks = _apply_candidate_currentness(evaluation["checks"], candidate_current)
    complete = candidate_current and all(item["status"] == "passed" for item in checks.values())
    return {
        "ok": True,
        "source": P1_RELEASE_EVIDENCE_SOURCE,
        "schema_version": P1_RELEASE_EVIDENCE_RECEIPT_SCHEMA_VERSION,
        "read_only": True,
        "side_effects": False,
        "status": "verified_current" if complete else "verified_stale",
        "candidate_head": candidate,
        "receipt_integrity_verified": True,
        "operator_attested_external_observations": True,
        "evidence_complete": complete,
        "candidate_current": candidate_current,
        "current_head": current_head,
        "receipt_id": receipt.get("receipt_id"),
        "receipt_digest": receipt.get("receipt_digest"),
        "recorded_at": receipt.get("recorded_at"),
        "receipt_path": _relative_runtime_path(root, str(path)),
        "receipt_count": len(records),
        "evidence_summary": _evidence_summary(observations),
        "checks": checks,
        "authority_boundary": _authority_boundary(),
    }


def _normalize_observations(value: Any, candidate_head: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise P1ReleaseEvidenceError(
            "P1_RELEASE_EVIDENCE_OBSERVATIONS_REQUIRED",
            "P1 release evidence requires all five structured observations.",
        )
    _require_exact_keys(value, set(P1_EVIDENCE_CHECK_IDS), "observations")
    validation = _normalize_validation(value.get("full_local_validation"), candidate_head)
    runtime = _normalize_runtime(value.get("runtime_provenance"), candidate_head)
    connector = _normalize_connector(value.get("connector_oauth"), candidate_head)
    current_facts = _normalize_current_facts(value.get("current_facts"), candidate_head)
    live = _normalize_live_chatgpt(value.get("live_chatgpt_development_acceptance"), candidate_head)
    return {
        "full_local_validation": validation,
        "runtime_provenance": runtime,
        "connector_oauth": connector,
        "current_facts": current_facts,
        "live_chatgpt_development_acceptance": live,
    }


def _normalize_validation(value: Any, candidate_head: str) -> dict[str, Any]:
    mapping = _require_object(value, "full_local_validation")
    _require_exact_keys(mapping, {"observed_at", "candidate_head", "commands"}, "full_local_validation")
    commands = _require_object(mapping.get("commands"), "full_local_validation.commands")
    _require_exact_keys(commands, set(P1_REQUIRED_LOCAL_VALIDATION_COMMANDS), "full_local_validation.commands")
    for name in P1_REQUIRED_LOCAL_VALIDATION_COMMANDS:
        if commands.get(name) != "passed":
            raise P1ReleaseEvidenceError(
                "P1_LOCAL_VALIDATION_NOT_PASSED",
                "Every required local validation command must be recorded as passed.",
                command=name,
            )
    return {
        "observed_at": _normalize_observed_at(mapping.get("observed_at"), "full_local_validation.observed_at"),
        "candidate_head": _require_candidate(mapping.get("candidate_head"), candidate_head, "full_local_validation.candidate_head"),
        "commands": {name: "passed" for name in P1_REQUIRED_LOCAL_VALIDATION_COMMANDS},
    }


def _normalize_runtime(value: Any, candidate_head: str) -> dict[str, Any]:
    mapping = _require_object(value, "runtime_provenance")
    required = {
        "observed_at",
        "candidate_head",
        "loaded_runtime_head",
        "runtime_project_checkout_head",
        "runtime_loaded_code_stale",
        "reload_needed_for_verification",
        "installed_package_matches_project_checkout",
    }
    _require_exact_keys(mapping, required, "runtime_provenance")
    if (
        mapping.get("runtime_loaded_code_stale") is not False
        or mapping.get("reload_needed_for_verification") is not False
        or mapping.get("installed_package_matches_project_checkout") is not True
    ):
        raise P1ReleaseEvidenceError(
            "P1_RUNTIME_PROVENANCE_NOT_READY",
            "Runtime provenance must show no stale code, no reload need, and an installed package matching checkout.",
        )
    return {
        "observed_at": _normalize_observed_at(mapping.get("observed_at"), "runtime_provenance.observed_at"),
        "candidate_head": _require_candidate(mapping.get("candidate_head"), candidate_head, "runtime_provenance.candidate_head"),
        "loaded_runtime_head": _require_candidate(mapping.get("loaded_runtime_head"), candidate_head, "runtime_provenance.loaded_runtime_head"),
        "runtime_project_checkout_head": _require_candidate(
            mapping.get("runtime_project_checkout_head"),
            candidate_head,
            "runtime_provenance.runtime_project_checkout_head",
        ),
        "runtime_loaded_code_stale": False,
        "reload_needed_for_verification": False,
        "installed_package_matches_project_checkout": True,
    }


def _normalize_connector(value: Any, candidate_head: str) -> dict[str, Any]:
    mapping = _require_object(value, "connector_oauth")
    required = {"observed_at", "candidate_head", "connector_reachable", "oauth_authorized", "visible_tool_inventory"}
    _require_exact_keys(mapping, required, "connector_oauth")
    if mapping.get("connector_reachable") is not True or mapping.get("oauth_authorized") is not True:
        raise P1ReleaseEvidenceError(
            "P1_CONNECTOR_OAUTH_NOT_READY",
            "Connector/OAuth evidence must record connector_reachable=true and oauth_authorized=true.",
        )
    return {
        "observed_at": _normalize_observed_at(mapping.get("observed_at"), "connector_oauth.observed_at"),
        "candidate_head": _require_candidate(mapping.get("candidate_head"), candidate_head, "connector_oauth.candidate_head"),
        "connector_reachable": True,
        "oauth_authorized": True,
        "visible_tool_inventory": _require_commander_inventory(
            mapping.get("visible_tool_inventory"),
            "connector_oauth.visible_tool_inventory",
        ),
    }


def _normalize_current_facts(value: Any, candidate_head: str) -> dict[str, Any]:
    mapping = _require_object(value, "current_facts")
    required = {
        "observed_at",
        "candidate_head",
        "artifact_id",
        "content_sha256",
        "expires_at",
        "canonical_state_sha256",
        "canonical_state_semantic_sha256",
        "snapshot_json_sha256",
        "freshness_current_observation",
        "unresolved_critical_blocker_count",
    }
    _require_exact_keys(mapping, required, "current_facts")
    if mapping.get("freshness_current_observation") is not True or mapping.get("unresolved_critical_blocker_count") != 0:
        raise P1ReleaseEvidenceError(
            "P1_CURRENT_FACTS_NOT_READY",
            "Current-facts evidence must be a current observation with zero unresolved critical blockers.",
        )
    observed_at = _normalize_observed_at(mapping.get("observed_at"), "current_facts.observed_at")
    expires_at = _normalize_observed_at(mapping.get("expires_at"), "current_facts.expires_at")
    if _parse_iso(expires_at) <= _parse_iso(observed_at):
        raise P1ReleaseEvidenceError(
            "P1_CURRENT_FACTS_EXPIRY_INVALID",
            "Current-facts artifact expiry must be after its observation time.",
        )
    return {
        "observed_at": observed_at,
        "candidate_head": _require_candidate(mapping.get("candidate_head"), candidate_head, "current_facts.candidate_head"),
        "artifact_id": _require_opaque_id(mapping.get("artifact_id"), "current_facts.artifact_id"),
        "content_sha256": _require_sha256(mapping.get("content_sha256"), "current_facts.content_sha256"),
        "expires_at": expires_at,
        "canonical_state_sha256": _require_sha256(
            mapping.get("canonical_state_sha256"),
            "current_facts.canonical_state_sha256",
        ),
        "canonical_state_semantic_sha256": _require_sha256(
            mapping.get("canonical_state_semantic_sha256"),
            "current_facts.canonical_state_semantic_sha256",
        ),
        "snapshot_json_sha256": _require_sha256(
            mapping.get("snapshot_json_sha256"),
            "current_facts.snapshot_json_sha256",
        ),
        "freshness_current_observation": True,
        "unresolved_critical_blocker_count": 0,
    }


def _normalize_live_chatgpt(value: Any, candidate_head: str) -> dict[str, Any]:
    mapping = _require_object(value, "live_chatgpt_development_acceptance")
    required = {
        "observed_at",
        "candidate_head",
        "visible_tool_inventory",
        "context_binding_mismatch_error_code",
        "review_manifest",
        "result_artifact",
        "resources_read_used",
        "all_calls_read_only",
    }
    _require_exact_keys(mapping, required, "live_chatgpt_development_acceptance")
    if mapping.get("context_binding_mismatch_error_code") != "CONTEXT_BINDING_MISMATCH":
        raise P1ReleaseEvidenceError(
            "P1_CONTEXT_BINDING_NEGATIVE_MISSING",
            "Live ChatGPT evidence must record CONTEXT_BINDING_MISMATCH.",
        )
    if mapping.get("resources_read_used") is not False or mapping.get("all_calls_read_only") is not True:
        raise P1ReleaseEvidenceError(
            "P1_LIVE_CHATGPT_BOUNDARY_NOT_MET",
            "Live ChatGPT evidence must show no resources/read and only read-only calls.",
        )
    review = _normalize_live_manifest(mapping.get("review_manifest"))
    artifact = _normalize_live_artifact(mapping.get("result_artifact"))
    return {
        "observed_at": _normalize_observed_at(mapping.get("observed_at"), "live_chatgpt_development_acceptance.observed_at"),
        "candidate_head": _require_candidate(
            mapping.get("candidate_head"),
            candidate_head,
            "live_chatgpt_development_acceptance.candidate_head",
        ),
        "visible_tool_inventory": _require_commander_inventory(
            mapping.get("visible_tool_inventory"),
            "live_chatgpt_development_acceptance.visible_tool_inventory",
        ),
        "context_binding_mismatch_error_code": "CONTEXT_BINDING_MISMATCH",
        "review_manifest": review,
        "result_artifact": artifact,
        "resources_read_used": False,
        "all_calls_read_only": True,
    }


def _normalize_live_manifest(value: Any) -> dict[str, Any]:
    mapping = _require_object(value, "live_chatgpt_development_acceptance.review_manifest")
    required = {
        "manifest_sha256",
        "expires_at",
        "subject_count",
        "page_count",
        "all_subject_pages_read",
        "page_ranges_contiguous",
        "expiry_continuity",
        "verify_context_binding",
        "verify_subject_hashes",
    }
    _require_exact_keys(mapping, required, "live_chatgpt_development_acceptance.review_manifest")
    if (
        mapping.get("all_subject_pages_read") is not True
        or mapping.get("page_ranges_contiguous") is not True
        or mapping.get("expiry_continuity") is not True
        or mapping.get("verify_context_binding") != "matched"
        or mapping.get("verify_subject_hashes") != "matched"
    ):
        raise P1ReleaseEvidenceError(
            "P1_MANIFEST_CONTINUITY_NOT_MET",
            "Live review-manifest evidence must show complete pages plus matching context, hashes, and expiry continuity.",
        )
    return {
        "manifest_sha256": _require_sha256(
            mapping.get("manifest_sha256"),
            "live_chatgpt_development_acceptance.review_manifest.manifest_sha256",
        ),
        "expires_at": _normalize_observed_at(
            mapping.get("expires_at"),
            "live_chatgpt_development_acceptance.review_manifest.expires_at",
        ),
        "subject_count": _bounded_int(mapping.get("subject_count"), 1, 64, "review_manifest.subject_count"),
        "page_count": _bounded_int(mapping.get("page_count"), 1, 4096, "review_manifest.page_count"),
        "all_subject_pages_read": True,
        "page_ranges_contiguous": True,
        "expiry_continuity": True,
        "verify_context_binding": "matched",
        "verify_subject_hashes": "matched",
    }


def _normalize_live_artifact(value: Any) -> dict[str, Any]:
    mapping = _require_object(value, "live_chatgpt_development_acceptance.result_artifact")
    required = {
        "artifact_id",
        "content_sha256",
        "expires_at",
        "page_count",
        "all_pages_read",
        "page_ranges_contiguous",
        "expiry_continuity",
        "typed_read_tool",
    }
    _require_exact_keys(mapping, required, "live_chatgpt_development_acceptance.result_artifact")
    if (
        mapping.get("all_pages_read") is not True
        or mapping.get("page_ranges_contiguous") is not True
        or mapping.get("expiry_continuity") is not True
        or mapping.get("typed_read_tool") != "read_result_artifact"
    ):
        raise P1ReleaseEvidenceError(
            "P1_RESULT_ARTIFACT_CONTINUITY_NOT_MET",
            "Live result-artifact evidence must show complete typed pages with SHA/expiry continuity.",
        )
    return {
        "artifact_id": _require_opaque_id(
            mapping.get("artifact_id"),
            "live_chatgpt_development_acceptance.result_artifact.artifact_id",
        ),
        "content_sha256": _require_sha256(
            mapping.get("content_sha256"),
            "live_chatgpt_development_acceptance.result_artifact.content_sha256",
        ),
        "expires_at": _normalize_observed_at(
            mapping.get("expires_at"),
            "live_chatgpt_development_acceptance.result_artifact.expires_at",
        ),
        "page_count": _bounded_int(mapping.get("page_count"), 1, 4096, "result_artifact.page_count"),
        "all_pages_read": True,
        "page_ranges_contiguous": True,
        "expiry_continuity": True,
        "typed_read_tool": "read_result_artifact",
    }


def _evaluate_observations(
    observations: Mapping[str, Any],
    candidate_head: str,
    now: datetime,
) -> dict[str, Any]:
    checks: dict[str, dict[str, Any]] = {}
    for check_id in P1_EVIDENCE_CHECK_IDS:
        observation = observations.get(check_id)
        if not isinstance(observation, Mapping):
            checks[check_id] = {
                "status": "blocked",
                "reason": "structured_observation_missing",
            }
            continue
        observation_head = observation.get("candidate_head")
        observed_at = _parse_iso(observation.get("observed_at"))
        if observation_head != candidate_head:
            checks[check_id] = {
                "status": "blocked",
                "reason": "candidate_head_mismatch",
                "observed_at": observation.get("observed_at"),
            }
            continue
        freshness = _freshness_reason(observed_at, now)
        if freshness is not None:
            checks[check_id] = {
                "status": "stale",
                "reason": freshness,
                "observed_at": observation.get("observed_at"),
            }
            continue
        checks[check_id] = {
            "status": "passed",
            "reason": "operator_attested_observation_is_fresh_and_candidate_bound",
            "observed_at": observation.get("observed_at"),
            "evidence_kind": "operator_attested" if check_id != "full_local_validation" else "operator_confirmed_local_validation",
        }
    return {
        "checks": checks,
        "complete": all(item["status"] == "passed" for item in checks.values()),
    }


def _apply_candidate_currentness(
    checks: Mapping[str, Mapping[str, Any]],
    candidate_current: bool,
) -> dict[str, dict[str, Any]]:
    result = {key: dict(value) for key, value in checks.items()}
    if candidate_current:
        return result
    for value in result.values():
        if value.get("status") == "passed":
            value["status"] = "stale"
            value["reason"] = "candidate_head_is_no_longer_current"
    return result


def _evidence_summary(observations: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for check_id in P1_EVIDENCE_CHECK_IDS:
        observation = observations.get(check_id)
        if isinstance(observation, Mapping):
            result[check_id] = {
                "observed_at": observation.get("observed_at"),
                "source_kind": "operator_attested_external_observation"
                if check_id != "full_local_validation"
                else "operator_confirmed_local_validation",
            }
    return result


def _missing_status(root: str, candidate_head: str) -> dict[str, Any]:
    return {
        "ok": True,
        "source": P1_RELEASE_EVIDENCE_SOURCE,
        "schema_version": P1_RELEASE_EVIDENCE_RECEIPT_SCHEMA_VERSION,
        "read_only": True,
        "side_effects": False,
        "status": "missing",
        "candidate_head": candidate_head,
        "receipt_integrity_verified": False,
        "operator_attested_external_observations": False,
        "evidence_complete": False,
        "candidate_current": _resolve_commit(root, "HEAD") == candidate_head,
        "checks": {
            check_id: {"status": "blocked", "reason": "p1_release_evidence_receipt_missing"}
            for check_id in P1_EVIDENCE_CHECK_IDS
        },
        "safe_next_action": {
            "tool": "manage_p1_release_evidence",
            "arguments": {"action": "preview", "candidate_head": candidate_head},
            "required_scope": "mcp:preview",
        },
        "authority_boundary": _authority_boundary(),
    }


def _status_error(error_code: str, message: str, **details: Any) -> dict[str, Any]:
    return {
        "ok": False,
        "source": P1_RELEASE_EVIDENCE_SOURCE,
        "schema_version": P1_RELEASE_EVIDENCE_RECEIPT_SCHEMA_VERSION,
        "read_only": True,
        "side_effects": False,
        "status": "invalid",
        "receipt_integrity_verified": False,
        "evidence_complete": False,
        "error_code": error_code,
        "message": message,
        **details,
        "authority_boundary": _authority_boundary(),
    }


def _manager_error(action: str, error_code: str, message: str, **details: Any) -> dict[str, Any]:
    return {
        "ok": False,
        "source": P1_RELEASE_EVIDENCE_SOURCE,
        "schema_version": P1_RELEASE_EVIDENCE_SCHEMA_VERSION,
        "action": action,
        "read_only": action in {"inspect", "status"},
        "side_effects": False,
        "error_code": error_code,
        "message": message,
        **details,
        "authority_boundary": _authority_boundary(),
    }


def _validate_receipt(receipt: Mapping[str, Any], root: str, candidate_head: str) -> dict[str, str] | None:
    if (
        receipt.get("schema_version") != P1_RELEASE_EVIDENCE_RECEIPT_SCHEMA_VERSION
        or receipt.get("source") != P1_RELEASE_EVIDENCE_SOURCE
        or receipt.get("project_root") != root
        or receipt.get("candidate_head") != candidate_head
        or not isinstance(receipt.get("receipt_id"), str)
        or not isinstance(receipt.get("operator_confirmation"), Mapping)
        or receipt["operator_confirmation"].get("confirmed") is not True
    ):
        return {"error_code": "RECEIPT_INVALID", "message": "P1 release-evidence receipt binding is invalid."}
    expected = _receipt_digest(dict(receipt))
    if not secrets.compare_digest(str(receipt.get("receipt_digest") or ""), expected):
        return {"error_code": "RECEIPT_DIGEST_MISMATCH", "message": "P1 release-evidence receipt digest does not match."}
    return None


def _authority_boundary() -> dict[str, bool]:
    return {
        "external_observations_are_operator_attested": True,
        "does_not_accept_raw_transcripts": True,
        "does_not_read_tokens_or_cookies": True,
        "does_not_run_validation": True,
        "does_not_start_executor": True,
        "does_not_commit_or_push": True,
        "does_not_change_connector_or_oauth": True,
        "does_not_replace_stable": True,
        "does_not_authorize_stable_replacement": True,
        "does_not_create_release_or_deployment": True,
    }


def _require_object(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise P1ReleaseEvidenceError("P1_RELEASE_EVIDENCE_FIELD_INVALID", f"{label} must be an object.", field=label)
    return value


def _require_exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        raise P1ReleaseEvidenceError(
            "P1_RELEASE_EVIDENCE_SCHEMA_MISMATCH",
            f"{label} must contain exactly the documented fields.",
            field=label,
            missing=sorted(expected - actual),
            unexpected=sorted(actual - expected),
        )


def _require_candidate(value: Any, candidate_head: str, label: str) -> str:
    if not isinstance(value, str) or not _is_commit(value.lower()) or value.lower() != candidate_head:
        raise P1ReleaseEvidenceError(
            "P1_RELEASE_EVIDENCE_CANDIDATE_MISMATCH",
            f"{label} must equal the exact candidate_head.",
            field=label,
        )
    return candidate_head


def _require_commander_inventory(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise P1ReleaseEvidenceError("P1_COMMANDER_TOOL_INVENTORY_INVALID", f"{label} must be a tool-name list.", field=label)
    if tuple(value) != COMMANDER_EXPOSED_TOOLS:
        raise P1ReleaseEvidenceError(
            "P1_COMMANDER_TOOL_INVENTORY_MISMATCH",
            f"{label} must equal the exact ordered nine-tool Commander tuple.",
            field=label,
            expected_tool_count=len(COMMANDER_EXPOSED_TOOLS),
        )
    return list(COMMANDER_EXPOSED_TOOLS)


def _require_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value.lower()):
        raise P1ReleaseEvidenceError("P1_RELEASE_EVIDENCE_SHA256_INVALID", f"{label} must be a SHA-256 digest.", field=label)
    return value.lower()


def _require_opaque_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _OPAQUE_ID_RE.fullmatch(value):
        raise P1ReleaseEvidenceError("P1_RELEASE_EVIDENCE_ARTIFACT_ID_INVALID", f"{label} must be an opaque artifact ID.", field=label)
    return value


def _normalize_observed_at(value: Any, label: str) -> str:
    parsed = _parse_iso(value)
    if parsed is None:
        raise P1ReleaseEvidenceError("P1_RELEASE_EVIDENCE_TIME_INVALID", f"{label} must be an ISO-8601 timestamp.", field=label)
    return _iso(parsed)


def _bounded_int(value: Any, minimum: int, maximum: int, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise P1ReleaseEvidenceError(
            "P1_RELEASE_EVIDENCE_INTEGER_INVALID",
            f"{label} must be an integer between {minimum} and {maximum}.",
            field=label,
        )
    return value


def _freshness_reason(observed_at: datetime | None, now: datetime) -> str | None:
    if observed_at is None:
        return "observed_at_invalid"
    seconds = (now - observed_at).total_seconds()
    if seconds < -300:
        return "observation_from_future"
    if seconds > P1_RELEASE_EVIDENCE_MAX_AGE_SECONDS:
        return "observation_expired"
    return None


def _is_commit(value: Any) -> bool:
    return isinstance(value, str) and _COMMIT_RE.fullmatch(value.lower()) is not None


def _valid_preview_id(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized if _PREVIEW_ID_RE.fullmatch(normalized) else None


def _clean_optional_text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value or len(value) > 64:
        return None
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        return None
    return _normalize_datetime(parsed)


def _normalize_datetime(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _normalize_datetime(value).isoformat()


def _normalize_project_root(project_root: str) -> str:
    return os.path.realpath(os.path.abspath(os.path.expanduser(project_root)))


def _resolve_commit(project_root: str, value: str | None) -> str | None:
    ref = value.strip() if isinstance(value, str) and value.strip() else "HEAD"
    if ref not in {"HEAD", "origin/main"} and not _is_commit(ref):
        return None
    try:
        completed = subprocess.run(
            ["git", "-C", project_root, "rev-parse", "--verify", f"{ref}^{{commit}}"],
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    resolved = completed.stdout.decode("utf-8", errors="replace").strip().lower()
    return resolved if _is_commit(resolved) else None


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _receipt_digest(receipt: Mapping[str, Any]) -> str:
    return _canonical_sha256({key: value for key, value in receipt.items() if key != "receipt_digest"})


def _is_expired(value: Any, now: datetime) -> bool:
    expires_at = _parse_iso(value)
    return expires_at is None or expires_at <= now


def _is_safe_runtime_path(project_root: str, path: str) -> bool:
    root = _normalize_project_root(project_root)
    runtime_root = os.path.abspath(resolve_project_runner_path(root, "runtime"))
    candidate = os.path.abspath(path)
    try:
        within_runtime = os.path.commonpath([candidate, runtime_root]) == runtime_root
    except ValueError:
        return False
    return within_runtime and os.path.realpath(candidate) == candidate


def _relative_runtime_path(project_root: str, path: str) -> str:
    return os.path.relpath(path, _normalize_project_root(project_root)).replace(os.sep, "/")


def _read_json_object(path: str) -> dict[str, Any] | None:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _write_json_exclusive(path: str, payload: Mapping[str, Any]) -> bool:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    descriptor, temporary_path = tempfile.mkstemp(prefix=".tmp-p1-release-evidence-", suffix=".json", dir=directory)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary_path, path)
        except FileExistsError:
            return False
        return True
    finally:
        try:
            os.unlink(temporary_path)
        except FileNotFoundError:
            pass
