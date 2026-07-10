from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from typing import Any

from runner.confirmation_store import ConfirmationStore
from runner.core_confirmation import confirmation_apply_guard
from runner.file_transaction import FileTransaction, FileTransactionError
from runner.release_submission_readiness import (
    DEFAULT_SUBMISSION_MATERIALS_REL_PATH,
    RELEASE_SUBMISSION_MATERIALS_MAX_BYTES,
    SUBMISSION_EVIDENCE_CONTENT_MAX_BYTES,
    SUBMISSION_EVIDENCE_ENTRY_TEMPLATE_DETAILS,
    SUBMISSION_EVIDENCE_READY_FIELD_BY_KEY,
    _coerce_evidence_refs,
    _normalize_evidence_ref,
    _normalize_submission_evidence_output_ref,
    _submission_evidence_unfinished_content_reason_codes,
)
from runner.tool_result import error_result


SUBMISSION_EVIDENCE_REVISION_SOURCE = "submission_evidence_revision"
SUBMISSION_EVIDENCE_REVISION_VERSION = "submission_evidence_revision.v1"
SUBMISSION_EVIDENCE_REVISION_PREVIEW_TTL_SECONDS = 1800
SUBMISSION_EVIDENCE_REVISION_PREVIEW_DIR = ".colameta/runtime/submission-evidence-revision-previews"


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


class MCPSubmissionEvidenceRevisionManager:
    """Preview-bound replacement for manifest-owned submission evidence Markdown."""

    def __init__(self, project_root: str) -> None:
        self.project_root = os.path.abspath(os.path.expanduser(project_root))
        self._store = ConfirmationStore(
            self.project_root,
            SUBMISSION_EVIDENCE_REVISION_PREVIEW_DIR,
            SUBMISSION_EVIDENCE_REVISION_PREVIEW_TTL_SECONDS,
        )

    def handle(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        if action == "preview":
            return self._preview(params)
        if action == "apply":
            return self._apply(params)
        if action == "status":
            return self._status(params)
        if action == "discard":
            return self._discard(params)
        return error_result(
            "INVALID_ACTION",
            "action must be preview, apply, status, or discard.",
        )

    def _preview(self, params: dict[str, Any]) -> dict[str, Any]:
        key = str(params.get("key") or "").strip()
        ref = str(params.get("ref") or "").strip()
        content = params.get("content")
        if key not in SUBMISSION_EVIDENCE_READY_FIELD_BY_KEY:
            return self._error(
                "SUBMISSION_EVIDENCE_KEY_INVALID",
                "Choose a supported submission evidence key.",
                accepted_keys=sorted(SUBMISSION_EVIDENCE_READY_FIELD_BY_KEY),
            )
        if not ref:
            return self._error("SUBMISSION_EVIDENCE_REF_REQUIRED", "preview requires the manifest-bound evidence ref.")
        content_error = self._validate_proposed_content(key, content)
        if content_error is not None:
            return content_error

        target = self._load_target(key, ref, require_review_required=True)
        if target.get("ok") is not True:
            return target
        assert isinstance(content, str)
        proposed_content = content if content.endswith("\n") else content + "\n"
        current_content = str(target["current_content"])
        if current_content == proposed_content:
            return self._error(
                "SUBMISSION_EVIDENCE_REVISION_UNCHANGED",
                "Proposed evidence content is identical to the current file.",
                key=key,
                ref=target["ref"],
            )

        preview_id = self._store.create_id("evidence_revision_")
        created_at = self._store.now_iso()
        expires_at = self._store.expires_at()
        current_sha256 = _sha256_text(current_content)
        proposed_sha256 = _sha256_text(proposed_content)
        preview_record = {
            "artifact_kind": SUBMISSION_EVIDENCE_REVISION_SOURCE,
            "schema_version": SUBMISSION_EVIDENCE_REVISION_VERSION,
            "preview_id": preview_id,
            "created_at": created_at,
            "expires_at": expires_at,
            "project_root": self.project_root,
            "action": "preview",
            "tool": "manage_submission_evidence_revision",
            "key": key,
            "ref": target["ref"],
            "ready_field": target["ready_field"],
            "current_sha256": current_sha256,
            "current_size_bytes": len(current_content.encode("utf-8")),
            "manifest_sha256": target["manifest_sha256"],
            "proposed_sha256": proposed_sha256,
            "proposed_size_bytes": len(proposed_content.encode("utf-8")),
            "prior_reason_codes": target["reason_codes"],
            "required_sections": self._required_sections(key),
        }
        self._store.write(preview_id, preview_record)
        return {
            "ok": True,
            "source": SUBMISSION_EVIDENCE_REVISION_SOURCE,
            "schema_version": SUBMISSION_EVIDENCE_REVISION_VERSION,
            "action": "preview",
            "status": "preview_ready",
            "preview_id": preview_id,
            "project_root": self.project_root,
            "key": key,
            "ref": target["ref"],
            "ready_field": target["ready_field"],
            "current_sha256": current_sha256,
            "current_size_bytes": preview_record["current_size_bytes"],
            "proposed_sha256": proposed_sha256,
            "proposed_size_bytes": preview_record["proposed_size_bytes"],
            "prior_reason_codes": target["reason_codes"],
            "required_sections": preview_record["required_sections"],
            "content_included": False,
            "mark_ready": False,
            "expires_at": expires_at,
            "confirmation": {
                "required": True,
                "preview_id": preview_id,
                "action": "apply",
                "tool": "manage_submission_evidence_revision",
                "key": key,
                "ref": target["ref"],
                "proposed_sha256": proposed_sha256,
            },
            "copyable_apply_call": {
                "tool": "manage_submission_evidence_revision",
                "arguments": {
                    "action": "apply",
                    "preview_id": preview_id,
                    "content": "<resubmit the exact replacement Markdown used for preview>",
                },
                "required_scope": "mcp:commit",
            },
            "authority_boundary": self._authority_boundary(),
        }

    def _apply(self, params: dict[str, Any]) -> dict[str, Any]:
        preview_id = str(params.get("preview_id") or "").strip()
        if not preview_id:
            return self._error("INVALID_PREVIEW_ID", "apply requires a non-empty preview_id.")
        guard = confirmation_apply_guard(self._store, preview_id, project_root=self.project_root)
        if guard.get("ok") is not True:
            error_code = str(guard.get("error_code") or "PREVIEW_NOT_FOUND")
            messages = {
                "PREVIEW_NOT_FOUND": "Revision preview was not found or was already applied/discarded.",
                "PROJECT_MISMATCH": "Revision preview belongs to a different project.",
                "PREVIEW_EXPIRED": "Revision preview expired; create a new preview.",
            }
            return self._error(error_code, messages.get(error_code, "Revision preview is not usable."), preview_id=preview_id)
        record = guard.get("payload")
        if not isinstance(record, dict) or record.get("artifact_kind") != SUBMISSION_EVIDENCE_REVISION_SOURCE:
            return self._error("PREVIEW_KIND_MISMATCH", "preview_id does not identify a submission evidence revision.")

        key = str(record.get("key") or "")
        ref = str(record.get("ref") or "")
        if (
            key not in SUBMISSION_EVIDENCE_READY_FIELD_BY_KEY
            or not ref
            or record.get("tool") != "manage_submission_evidence_revision"
            or record.get("action") != "preview"
            or not _is_sha256(record.get("current_sha256"))
            or not _is_sha256(record.get("manifest_sha256"))
            or not _is_sha256(record.get("proposed_sha256"))
        ):
            return self._error("PREVIEW_CONTENT_INVALID", "Stored revision preview metadata is invalid.")
        proposed_content = params.get("content")
        content_error = self._validate_proposed_content(key, proposed_content)
        if content_error is not None:
            return content_error
        assert isinstance(proposed_content, str)
        proposed_content = proposed_content if proposed_content.endswith("\n") else proposed_content + "\n"
        if _sha256_text(proposed_content) != record.get("proposed_sha256"):
            return self._error(
                "SUBMISSION_EVIDENCE_PROPOSED_CONTENT_MISMATCH",
                "Replacement content does not match the content digest bound by preview.",
                preview_id=preview_id,
                proposed_sha256=record.get("proposed_sha256"),
                received_sha256=_sha256_text(proposed_content),
            )
        target = self._load_target(key, ref, require_review_required=True)
        if target.get("ok") is not True:
            return target
        if target.get("manifest_sha256") != record.get("manifest_sha256"):
            return self._error(
                "SUBMISSION_EVIDENCE_MANIFEST_CHANGED",
                "Submission materials changed after preview; create a new revision preview.",
                key=key,
                ref=ref,
            )
        current_content = str(target["current_content"])
        if _sha256_text(current_content) != record.get("current_sha256"):
            return self._error(
                "SUBMISSION_EVIDENCE_BASE_CHANGED",
                "Evidence file changed after preview; create a new revision preview.",
                key=key,
                ref=ref,
            )

        manifest = target["manifest"]
        ready_field = str(target["ready_field"])
        manifest[ready_field] = False
        manifest["notes"] = (
            f"Submission evidence {key} ({ref}) was revised through a preview-bound local transaction. "
            "Its ready field remains false until a human reviewer confirms the final content."
        )
        manifest_text = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
        transaction = FileTransaction(self.project_root, label="manage_submission_evidence_revision.apply")
        transaction.write_text(ref, proposed_content)
        transaction.write_text(DEFAULT_SUBMISSION_MATERIALS_REL_PATH, manifest_text)
        try:
            receipt = transaction.commit()
        except FileTransactionError as exc:
            return self._error(
                "SUBMISSION_EVIDENCE_REVISION_TRANSACTION_FAILED",
                str(exc),
                transaction_receipt=exc.receipt,
            )
        self._store.delete(preview_id)
        return {
            "ok": True,
            "source": SUBMISSION_EVIDENCE_REVISION_SOURCE,
            "schema_version": SUBMISSION_EVIDENCE_REVISION_VERSION,
            "action": "apply",
            "status": "applied",
            "preview_id": preview_id,
            "project_root": self.project_root,
            "key": key,
            "ref": ref,
            "ready_field": ready_field,
            "ready_field_value": False,
            "previous_sha256": record["current_sha256"],
            "applied_sha256": record["proposed_sha256"],
            "changed_files": [ref, DEFAULT_SUBMISSION_MATERIALS_REL_PATH],
            "content_included": False,
            "mark_ready": False,
            "transaction_receipt": receipt,
            "next_actions": [
                {
                    "tool": "get_release_submission_readiness",
                    "arguments": {},
                    "required_scope": "mcp:read",
                    "why": "Verify that the revised evidence no longer has an explicit unfinished-content blocker.",
                },
                {
                    "tool": "mark_submission_evidence_ready_fields",
                    "arguments": {"keys": [key], "review_confirmation": "human_reviewed"},
                    "required_scope": "mcp:commit",
                    "why": "Only after human review, mark this one evidence key ready.",
                },
            ],
            "authority_boundary": self._authority_boundary(),
        }

    def _status(self, params: dict[str, Any]) -> dict[str, Any]:
        preview_id = str(params.get("preview_id") or "").strip()
        if not preview_id:
            return self._error("INVALID_PREVIEW_ID", "status requires a non-empty preview_id.")
        record = self._store.read(preview_id)
        if not isinstance(record, dict) or record.get("artifact_kind") != SUBMISSION_EVIDENCE_REVISION_SOURCE:
            return self._error("PREVIEW_NOT_FOUND", "Revision preview was not found.", preview_id=preview_id)
        if record.get("project_root") != self.project_root:
            return self._error("PROJECT_MISMATCH", "Revision preview belongs to a different project.", preview_id=preview_id)
        return {
            "ok": True,
            "source": SUBMISSION_EVIDENCE_REVISION_SOURCE,
            "schema_version": SUBMISSION_EVIDENCE_REVISION_VERSION,
            "action": "status",
            "status": "expired" if self._store.is_expired(record) else "preview_ready",
            "preview_id": preview_id,
            "key": record.get("key"),
            "ref": record.get("ref"),
            "current_sha256": record.get("current_sha256"),
            "proposed_sha256": record.get("proposed_sha256"),
            "expires_at": record.get("expires_at"),
            "content_included": False,
            "mark_ready": False,
        }

    def _discard(self, params: dict[str, Any]) -> dict[str, Any]:
        preview_id = str(params.get("preview_id") or "").strip()
        if not preview_id:
            return self._error("INVALID_PREVIEW_ID", "discard requires a non-empty preview_id.")
        record = self._store.read(preview_id)
        if not isinstance(record, dict) or record.get("artifact_kind") != SUBMISSION_EVIDENCE_REVISION_SOURCE:
            return self._error("PREVIEW_NOT_FOUND", "Revision preview was not found.", preview_id=preview_id)
        if record.get("project_root") != self.project_root:
            return self._error("PROJECT_MISMATCH", "Revision preview belongs to a different project.", preview_id=preview_id)
        self._store.delete(preview_id)
        return {
            "ok": True,
            "source": SUBMISSION_EVIDENCE_REVISION_SOURCE,
            "schema_version": SUBMISSION_EVIDENCE_REVISION_VERSION,
            "action": "discard",
            "status": "discarded",
            "preview_id": preview_id,
            "key": record.get("key"),
            "ref": record.get("ref"),
            "content_included": False,
            "mark_ready": False,
        }

    def _load_target(self, key: str, ref: str, *, require_review_required: bool) -> dict[str, Any]:
        manifest_path = os.path.join(self.project_root, DEFAULT_SUBMISSION_MATERIALS_REL_PATH)
        expected_manifest_path = os.path.abspath(
            os.path.join(os.path.realpath(self.project_root), DEFAULT_SUBMISSION_MATERIALS_REL_PATH)
        )
        if os.path.realpath(manifest_path) != expected_manifest_path:
            return self._error(
                "SUBMISSION_EVIDENCE_MANIFEST_SYMLINK_NOT_ALLOWED",
                "Submission materials manifest must not be a symlink or use symlinked parent directories.",
            )
        manifest_snapshot = self._read_bound_file_bytes(
            DEFAULT_SUBMISSION_MATERIALS_REL_PATH,
            max_bytes=RELEASE_SUBMISSION_MATERIALS_MAX_BYTES,
            symlink_error="SUBMISSION_EVIDENCE_MANIFEST_SYMLINK_NOT_ALLOWED",
            read_error="SUBMISSION_MATERIALS_READ_FAILED",
        )
        if manifest_snapshot.get("ok") is not True:
            return manifest_snapshot
        manifest_bytes = manifest_snapshot["content_bytes"]
        try:
            manifest = json.loads(manifest_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            return self._error(
                "SUBMISSION_MATERIALS_JSON_INVALID",
                "Submission materials manifest is not valid UTF-8 JSON.",
                error_type=exc.__class__.__name__,
            )
        if not isinstance(manifest, dict):
            return self._error(
                "SUBMISSION_MATERIALS_SCHEMA_INVALID",
                "Submission materials manifest must be a JSON object.",
            )

        normalized = _normalize_submission_evidence_output_ref(self.project_root, ref)
        if normalized.get("ok") is not True:
            return self._error(
                str(normalized.get("error_code") or "SUBMISSION_EVIDENCE_REF_INVALID"),
                "Evidence ref is not an allowed docs/submission Markdown path.",
                key=key,
                ref=ref,
            )
        rel_path = str(normalized["rel_path"])
        evidence = manifest.get("evidence")
        manifest_refs = _coerce_evidence_refs(evidence.get(key)) if isinstance(evidence, dict) else []
        normalized_manifest_refs: list[str] = []
        for manifest_ref in manifest_refs:
            manifest_normalized = _normalize_evidence_ref(self.project_root, manifest_ref)
            if manifest_normalized.get("ok") is True:
                normalized_manifest_refs.append(str(manifest_normalized["rel_path"]))
        if rel_path not in normalized_manifest_refs:
            return self._error(
                "SUBMISSION_EVIDENCE_REF_NOT_BOUND_TO_KEY",
                "Evidence ref is not bound to the selected key in the submission materials manifest.",
                key=key,
                ref=rel_path,
                manifest_refs=normalized_manifest_refs,
            )
        evidence_snapshot = self._read_bound_file_bytes(
            rel_path,
            max_bytes=SUBMISSION_EVIDENCE_CONTENT_MAX_BYTES,
            symlink_error="SUBMISSION_EVIDENCE_SYMLINK_NOT_ALLOWED",
            read_error="SUBMISSION_EVIDENCE_FILE_UNREADABLE",
        )
        if evidence_snapshot.get("ok") is not True:
            return evidence_snapshot
        content_bytes = evidence_snapshot["content_bytes"]
        try:
            current_content = content_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            return self._error("SUBMISSION_EVIDENCE_FILE_UNREADABLE", "Evidence file is not valid UTF-8.", error_type=exc.__class__.__name__)
        reason_codes = _submission_evidence_unfinished_content_reason_codes(current_content)
        if require_review_required and not reason_codes:
            return self._error(
                "SUBMISSION_EVIDENCE_REVISION_NOT_REQUIRED",
                "This specialized revision path only accepts evidence currently blocked for unfinished content.",
                key=key,
                ref=rel_path,
                current_status="present",
            )
        return {
            "ok": True,
            "manifest": manifest,
            "manifest_sha256": _sha256_bytes(manifest_bytes),
            "ref": rel_path,
            "current_content": current_content,
            "reason_codes": reason_codes,
            "ready_field": SUBMISSION_EVIDENCE_READY_FIELD_BY_KEY[key],
        }

    def _read_bound_file_bytes(
        self,
        rel_path: str,
        *,
        max_bytes: int,
        symlink_error: str,
        read_error: str,
    ) -> dict[str, Any]:
        abs_path = os.path.abspath(os.path.join(self.project_root, rel_path))
        expected_real_path = os.path.abspath(os.path.join(os.path.realpath(self.project_root), rel_path))
        if os.path.realpath(abs_path) != expected_real_path:
            return self._error(symlink_error, "The bounded file path must not contain symlinks.", ref=rel_path)
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(abs_path, flags)
        except OSError as exc:
            return self._error(read_error, "Could not open the bounded file.", ref=rel_path, error_type=exc.__class__.__name__)
        try:
            opened_stat = os.fstat(fd)
            path_stat = os.stat(abs_path, follow_symlinks=False)
            same_file = (opened_stat.st_dev, opened_stat.st_ino) == (path_stat.st_dev, path_stat.st_ino)
            if (
                not stat.S_ISREG(opened_stat.st_mode)
                or not stat.S_ISREG(path_stat.st_mode)
                or not same_file
                or os.path.realpath(abs_path) != expected_real_path
            ):
                return self._error(symlink_error, "The bounded file path changed or resolves through a symlink.", ref=rel_path)
            chunks: list[bytes] = []
            remaining = max_bytes + 1
            while remaining > 0:
                chunk = os.read(fd, min(65536, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            content_bytes = b"".join(chunks)
        except OSError as exc:
            return self._error(read_error, "Could not read the bounded file.", ref=rel_path, error_type=exc.__class__.__name__)
        finally:
            os.close(fd)
        if len(content_bytes) > max_bytes:
            return self._error(
                "SUBMISSION_EVIDENCE_CONTENT_TOO_LARGE"
                if rel_path != DEFAULT_SUBMISSION_MATERIALS_REL_PATH
                else "SUBMISSION_MATERIALS_FILE_TOO_LARGE",
                "The bounded file exceeds the size limit.",
                ref=rel_path,
                max_bytes=max_bytes,
            )
        return {"ok": True, "content_bytes": content_bytes}

    def _validate_proposed_content(self, key: str, content: Any) -> dict[str, Any] | None:
        if not isinstance(content, str) or not content.strip():
            return self._error("SUBMISSION_EVIDENCE_CONTENT_REQUIRED", "Revision preview/apply requires non-empty replacement evidence content.")
        normalized_content = content if content.endswith("\n") else content + "\n"
        try:
            content_bytes = normalized_content.encode("utf-8")
        except UnicodeEncodeError as exc:
            return self._error(
                "SUBMISSION_EVIDENCE_CONTENT_INVALID",
                "Replacement evidence content must be valid UTF-8 text.",
                error_type=exc.__class__.__name__,
            )
        if len(content_bytes) > SUBMISSION_EVIDENCE_CONTENT_MAX_BYTES:
            return self._error(
                "SUBMISSION_EVIDENCE_CONTENT_TOO_LARGE",
                "Replacement evidence content exceeds the size limit.",
                max_bytes=SUBMISSION_EVIDENCE_CONTENT_MAX_BYTES,
                actual_bytes=len(content_bytes),
            )
        if "\x00" in content:
            return self._error("SUBMISSION_EVIDENCE_CONTENT_INVALID", "Replacement evidence content must be UTF-8 text without NUL bytes.")
        reason_codes = _submission_evidence_unfinished_content_reason_codes(content)
        if reason_codes:
            return self._error(
                "SUBMISSION_EVIDENCE_CONTENT_REVIEW_REQUIRED",
                "Replacement content still explicitly declares unfinished evidence.",
                reason_codes=reason_codes,
            )
        missing_sections = [
            section
            for section in self._required_sections(key)
            if re.search(rf"(?im)^#{{1,6}}\s+{re.escape(section)}\s*$", content) is None
        ]
        if missing_sections:
            return self._error(
                "SUBMISSION_EVIDENCE_REQUIRED_SECTIONS_MISSING",
                "Replacement evidence content is missing required Markdown sections.",
                key=key,
                missing_sections=missing_sections,
            )
        return None

    def _required_sections(self, key: str) -> list[str]:
        detail = SUBMISSION_EVIDENCE_ENTRY_TEMPLATE_DETAILS.get(key)
        return [str(item) for item in (detail or {}).get("required_sections", []) if isinstance(item, str)]

    def _error(self, error_code: str, message: str, **fields: Any) -> dict[str, Any]:
        return error_result(
            error_code,
            message,
            source=SUBMISSION_EVIDENCE_REVISION_SOURCE,
            schema_version=SUBMISSION_EVIDENCE_REVISION_VERSION,
            content_included=False,
            **fields,
        )

    def _authority_boundary(self) -> dict[str, Any]:
        return {
            "only_manifest_bound_submission_markdown": True,
            "preview_bound_apply": True,
            "ready_field_remains_false": True,
            "does_not_return_evidence_content": True,
            "does_not_submit_app_for_review": True,
            "does_not_publish_app": True,
        }
