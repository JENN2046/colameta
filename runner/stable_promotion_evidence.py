from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from runner._internal_utils import write_json_atomic
from runner.runner_paths import resolve_project_runner_path


PREVIEW_TTL_SECONDS = 3600
PREVIEWS_DIR = os.path.join("runtime", "stable-promotion-evidence-previews")
RECEIPTS_DIR = os.path.join("runtime", "stable-promotion-evidence")
MANIFEST_VERSION = 2
MANIFEST_KIND = "git_commit_tracked_sha256_manifest"
RECEIPT_SCHEMA_VERSION = "stable_promotion_artifact_receipt.v1"
PREVIEW_SCHEMA_VERSION = "stable_promotion_artifact_preview.v1"
_OBJECT_ID_PATTERN = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
_PREVIEW_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def build_candidate_artifact_manifest(
    project_root: str,
    candidate_head: str | None,
    *,
    include_entries: bool = False,
) -> dict[str, Any]:
    """Hash tracked content from an exact Git commit, never from the worktree."""
    root = _normalize_project_root(project_root)
    resolved_head = _resolve_commit(root, candidate_head)
    if not resolved_head:
        return _manifest_unavailable("candidate_commit_unavailable")

    tree = _run_git(root, ["ls-tree", "-rz", "--full-tree", resolved_head])
    if not tree["ok"]:
        return _manifest_unavailable("git_ls_tree_failed")
    parsed_entries = _parse_ls_tree(tree.get("stdout_bytes", b""))
    if parsed_entries is None:
        return _manifest_unavailable("git_ls_tree_malformed")

    blob_ids = sorted({entry["object_id"] for entry in parsed_entries if entry["object_type"] == "blob"})
    blob_fingerprints = _read_git_blob_fingerprints(root, blob_ids)
    if blob_fingerprints is None:
        return _manifest_unavailable("git_cat_file_batch_failed")

    entries: list[dict[str, Any]] = []
    total_size_bytes = 0
    for tree_entry in parsed_entries:
        object_id = tree_entry["object_id"]
        object_type = tree_entry["object_type"]
        mode = tree_entry["mode"]
        if object_type == "blob":
            fingerprint = blob_fingerprints.get(object_id)
            if fingerprint is None:
                return _manifest_unavailable("git_blob_missing")
            file_type = "symlink" if mode == "120000" else "file"
            size_bytes = int(fingerprint["size_bytes"])
            sha256 = str(fingerprint["sha256"])
        elif object_type == "commit" and mode == "160000":
            content = f"gitlink:{object_id}".encode("ascii")
            file_type = "gitlink"
            size_bytes = len(content)
            sha256 = hashlib.sha256(content).hexdigest()
        else:
            return _manifest_unavailable("unsupported_git_tree_entry")
        total_size_bytes += size_bytes
        entries.append(
            {
                "path": tree_entry["path"],
                "path_encoding": tree_entry["path_encoding"],
                "mode": mode,
                "file_type": file_type,
                "git_object_id": object_id,
                "sha256": sha256,
                "size_bytes": size_bytes,
            }
        )

    entries.sort(key=lambda item: (str(item["path_encoding"]), str(item["path"])))
    manifest_payload = {
        "manifest_version": MANIFEST_VERSION,
        "manifest_kind": MANIFEST_KIND,
        "algorithm": "sha256",
        "source_kind": "git_object_database",
        "project_head": resolved_head,
        "file_count": len(entries),
        "total_size_bytes": total_size_bytes,
        "files": entries,
    }
    manifest_sha256 = _canonical_sha256(manifest_payload)
    path_list_sha256 = _canonical_sha256(
        [{"path": str(item["path"]), "path_encoding": str(item["path_encoding"])} for item in entries]
    )
    result: dict[str, Any] = {
        "available": True,
        "manifest_version": MANIFEST_VERSION,
        "manifest_kind": MANIFEST_KIND,
        "algorithm": "sha256",
        "source_kind": "git_object_database",
        "project_head": resolved_head,
        "file_count": len(entries),
        "total_size_bytes": total_size_bytes,
        "manifest_sha256": manifest_sha256,
        "tracked_path_list_sha256": path_list_sha256,
        "file_entries_omitted_from_response": not include_entries,
        "included_paths_preview": [
            str(item["path"])
            if item["path_encoding"] == "utf-8"
            else f"base64:{item['path']}"
            for item in entries[:20]
        ],
        "excluded_scope": "untracked_files_ignored_runtime_private_state_worktree_changes_git_directory_virtualenv_build_artifacts",
        "read_only": True,
        "side_effects": False,
        "worktree_content_used": False,
    }
    if include_entries:
        result["files"] = entries
    return result


def get_stable_promotion_evidence_status(
    project_root: str,
    *,
    candidate_head: str | None = None,
) -> dict[str, Any]:
    root = _normalize_project_root(project_root)
    resolved_head = _resolve_commit(root, candidate_head)
    if not resolved_head:
        return _status_error("CANDIDATE_COMMIT_UNAVAILABLE", "Candidate commit could not be resolved.")
    receipt_path = _receipt_path(root, resolved_head)
    if not _is_safe_runtime_artifact_path(root, receipt_path):
        return _status_error(
            "RUNTIME_STORAGE_UNSAFE",
            "Stable promotion evidence storage resolves outside the project Runner runtime directory.",
        )
    if not os.path.isfile(receipt_path):
        current = _git_snapshot(root).get("head") == resolved_head
        return {
            "ok": True,
            "source": "stable_promotion_artifact_evidence",
            "schema_version": RECEIPT_SCHEMA_VERSION,
            "read_only": True,
            "side_effects": False,
            "status": "missing",
            "verified": False,
            "current": current,
            "candidate_head": resolved_head,
            "receipt_path": _relative_runner_path(root, receipt_path),
            "safe_next_action": {
                "tool": "manage_stable_promotion_evidence",
                "arguments": {"action": "preview", "candidate_head": resolved_head},
                "required_scope": "mcp:preview",
            },
        }
    try:
        with open(receipt_path, "r", encoding="utf-8") as handle:
            receipt = json.load(handle)
    except Exception:
        return _status_error("RECEIPT_UNREADABLE", "Stable promotion artifact receipt is unreadable.")
    if not isinstance(receipt, dict) or receipt.get("schema_version") != RECEIPT_SCHEMA_VERSION:
        return _status_error("RECEIPT_INVALID", "Stable promotion artifact receipt has an invalid schema.")
    if receipt.get("project_root") != root or receipt.get("candidate_head") != resolved_head:
        return _status_error("RECEIPT_BINDING_MISMATCH", "Stable promotion artifact receipt binding is invalid.")
    expected_receipt_digest = _receipt_digest(receipt)
    if not secrets.compare_digest(str(receipt.get("receipt_digest") or ""), expected_receipt_digest):
        return _status_error("RECEIPT_DIGEST_MISMATCH", "Stable promotion artifact receipt digest does not match.")

    persisted_manifest = receipt.get("artifact_manifest")
    if not isinstance(persisted_manifest, dict) or not isinstance(persisted_manifest.get("files"), list):
        return _status_error("RECEIPT_MANIFEST_MISSING", "Stable promotion artifact receipt has no full manifest.")
    current_manifest = build_candidate_artifact_manifest(root, resolved_head, include_entries=True)
    if current_manifest.get("available") is not True:
        return _status_error("CANDIDATE_MANIFEST_UNAVAILABLE", "Candidate manifest could not be recomputed.")
    if persisted_manifest != current_manifest:
        return _status_error("RECEIPT_MANIFEST_MISMATCH", "Persisted manifest does not match the exact Git commit.")
    snapshot = _git_snapshot(root)
    current = snapshot.get("head") == resolved_head
    return {
        "ok": True,
        "source": "stable_promotion_artifact_evidence",
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "read_only": True,
        "side_effects": False,
        "status": "verified_current" if current else "verified_stale",
        "verified": True,
        "current": current,
        "candidate_head": resolved_head,
        "manifest": _manifest_summary(current_manifest),
        "recorded_at": receipt.get("recorded_at"),
        "receipt_id": receipt.get("receipt_id"),
        "receipt_digest": receipt.get("receipt_digest"),
        "receipt_path": _relative_runner_path(root, receipt_path),
        "authority_boundary": _authority_boundary(),
    }


class MCPStablePromotionEvidenceManager:
    def __init__(self, project_root: str):
        self.project_root = _normalize_project_root(project_root)
        self.previews_root = resolve_project_runner_path(self.project_root, PREVIEWS_DIR)

    def handle(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        normalized = action.strip().lower() if isinstance(action, str) else ""
        if normalized in {"inspect", "status"}:
            return self.status(params)
        if normalized == "preview":
            return self.preview(params)
        if normalized == "apply":
            return self.apply(params)
        if normalized == "discard":
            return self.discard(params)
        return {
            "ok": False,
            "action": normalized or "unknown",
            "error_code": "UNKNOWN_ACTION",
            "message": "action supports inspect, status, preview, apply, or discard.",
        }

    def status(self, params: dict[str, Any]) -> dict[str, Any]:
        return {
            "action": "status",
            **get_stable_promotion_evidence_status(
                self.project_root,
                candidate_head=_clean_optional_text(params.get("candidate_head")),
            ),
        }

    def preview(self, params: dict[str, Any]) -> dict[str, Any]:
        if not self._runtime_storage_is_safe():
            return _manager_error(
                "preview",
                "RUNTIME_STORAGE_UNSAFE",
                "Stable promotion evidence storage resolves outside the project Runner runtime directory.",
            )
        candidate_head = _resolve_commit(self.project_root, _clean_optional_text(params.get("candidate_head")))
        if not candidate_head:
            return _manager_error("preview", "CANDIDATE_COMMIT_UNAVAILABLE", "Candidate commit could not be resolved.")
        snapshot = _git_snapshot(self.project_root)
        manifest = build_candidate_artifact_manifest(self.project_root, candidate_head, include_entries=True)
        blockers = _apply_blockers(snapshot, candidate_head, manifest)
        now = _utc_now()
        preview_id = secrets.token_urlsafe(18)
        artifact = {
            "schema_version": PREVIEW_SCHEMA_VERSION,
            "artifact_kind": "stable_promotion_artifact_evidence_preview",
            "preview_id": preview_id,
            "project_root": self.project_root,
            "candidate_head": candidate_head,
            "git_snapshot": snapshot,
            "artifact_manifest": manifest,
            "blockers": blockers,
            "created_at": _iso(now),
            "expires_at": _iso(now + timedelta(seconds=PREVIEW_TTL_SECONDS)),
            "authority_boundary": _authority_boundary(),
        }
        artifact["preview_digest"] = _canonical_sha256(artifact)
        try:
            write_json_atomic(self._preview_path(preview_id), artifact)
        except OSError:
            return _manager_error(
                "preview", "PREVIEW_WRITE_FAILED", "Stable promotion evidence preview could not be persisted."
            )
        return {
            "ok": True,
            "source": "stable_promotion_artifact_evidence",
            "schema_version": PREVIEW_SCHEMA_VERSION,
            "action": "preview",
            "read_only": False,
            "side_effects": True,
            "writes_preview_artifact_only": True,
            "preview_id": preview_id,
            "preview_digest": artifact["preview_digest"],
            "candidate_head": candidate_head,
            "manifest": _manifest_summary(manifest),
            "preconditions": snapshot,
            "blockers": blockers,
            "can_apply": not blockers,
            "expires_at": artifact["expires_at"],
            "next_action": (
                {
                    "tool": "manage_stable_promotion_evidence",
                    "arguments": {"action": "apply", "preview_id": preview_id},
                    "required_scope": "mcp:commit",
                }
                if not blockers
                else None
            ),
            "authority_boundary": _authority_boundary(),
        }

    def apply(self, params: dict[str, Any]) -> dict[str, Any]:
        preview_id = _valid_preview_id(params.get("preview_id"))
        if not preview_id:
            return _manager_error("apply", "PREVIEW_ID_INVALID", "A valid preview_id is required.")
        if not self._runtime_storage_is_safe():
            return _manager_error(
                "apply",
                "RUNTIME_STORAGE_UNSAFE",
                "Stable promotion evidence storage resolves outside the project Runner runtime directory.",
            )
        artifact = self._read_preview(preview_id)
        if artifact is None:
            return _manager_error("apply", "PREVIEW_NOT_FOUND", "Stable promotion evidence preview was not found.")
        binding_error = self._validate_preview_artifact(artifact, preview_id)
        if binding_error:
            return binding_error
        if _is_expired(artifact.get("expires_at")):
            return _manager_error("apply", "PREVIEW_EXPIRED", "Stable promotion evidence preview has expired.")
        if artifact.get("blockers"):
            return _manager_error("apply", "PREVIEW_BLOCKED", "Stable promotion evidence preview has blockers.")

        candidate_head = str(artifact["candidate_head"])
        snapshot = _git_snapshot(self.project_root)
        manifest = build_candidate_artifact_manifest(self.project_root, candidate_head, include_entries=True)
        blockers = _apply_blockers(snapshot, candidate_head, manifest)
        if blockers:
            return {
                **_manager_error("apply", "PRECONDITION_CHANGED", "Stable promotion evidence preconditions changed."),
                "blockers": blockers,
            }
        preview_manifest = artifact.get("artifact_manifest")
        if not isinstance(preview_manifest, dict) or preview_manifest != manifest:
            return _manager_error("apply", "MANIFEST_CHANGED", "Exact candidate manifest differs from the preview.")

        receipt_path = _receipt_path(self.project_root, candidate_head)
        if not _is_safe_runtime_artifact_path(self.project_root, receipt_path):
            return _manager_error(
                "apply",
                "RUNTIME_STORAGE_UNSAFE",
                "Stable promotion evidence storage resolves outside the project Runner runtime directory.",
            )
        existing = get_stable_promotion_evidence_status(self.project_root, candidate_head=candidate_head)
        if existing.get("verified") is True:
            self._delete_preview(preview_id)
            return {
                "ok": True,
                "source": "stable_promotion_artifact_evidence",
                "schema_version": RECEIPT_SCHEMA_VERSION,
                "action": "apply",
                "status": "already_recorded",
                "already_recorded": True,
                "candidate_head": candidate_head,
                "evidence_status": existing,
                "authority_boundary": _authority_boundary(),
            }
        if os.path.isfile(receipt_path):
            return _manager_error(
                "apply",
                "RECEIPT_CONFLICT_INVALID",
                "An existing receipt for this candidate is invalid; preserve it for investigation instead of overwriting it.",
            )

        now = _utc_now()
        receipt_id = f"stable_promotion_artifact_{candidate_head[:12]}_{now.strftime('%Y%m%dT%H%M%SZ')}"
        receipt = {
            "schema_version": RECEIPT_SCHEMA_VERSION,
            "receipt_id": receipt_id,
            "source": "manage_stable_promotion_evidence",
            "project_root": self.project_root,
            "candidate_head": candidate_head,
            "recorded_at": _iso(now),
            "preview_id": preview_id,
            "preview_digest": artifact.get("preview_digest"),
            "git_snapshot": snapshot,
            "artifact_manifest": manifest,
            "authority_boundary": _authority_boundary(),
        }
        receipt["receipt_digest"] = _receipt_digest(receipt)
        try:
            created = _write_json_exclusive_atomic(receipt_path, receipt)
        except OSError:
            return _manager_error(
                "apply", "RECEIPT_WRITE_FAILED", "Stable promotion artifact receipt could not be persisted."
            )
        if not created:
            concurrent = get_stable_promotion_evidence_status(self.project_root, candidate_head=candidate_head)
            if concurrent.get("verified") is True:
                self._delete_preview(preview_id)
                return {
                    "ok": True,
                    "source": "stable_promotion_artifact_evidence",
                    "schema_version": RECEIPT_SCHEMA_VERSION,
                    "action": "apply",
                    "status": "already_recorded",
                    "already_recorded": True,
                    "candidate_head": candidate_head,
                    "evidence_status": concurrent,
                    "authority_boundary": _authority_boundary(),
                }
            return _manager_error(
                "apply",
                "RECEIPT_CONFLICT_INVALID",
                "A concurrent receipt for this candidate is invalid; preserve it for investigation.",
            )
        self._delete_preview(preview_id)
        verified = get_stable_promotion_evidence_status(self.project_root, candidate_head=candidate_head)
        if verified.get("verified") is not True:
            return _manager_error("apply", "RECEIPT_VERIFICATION_FAILED", "Persisted receipt did not verify.")
        return {
            "ok": True,
            "source": "stable_promotion_artifact_evidence",
            "schema_version": RECEIPT_SCHEMA_VERSION,
            "action": "apply",
            "status": "recorded",
            "already_recorded": False,
            "candidate_head": candidate_head,
            "receipt_id": receipt_id,
            "receipt_digest": receipt["receipt_digest"],
            "receipt_path": _relative_runner_path(self.project_root, receipt_path),
            "manifest": _manifest_summary(manifest),
            "evidence_status": verified,
            "authority_boundary": _authority_boundary(),
        }

    def discard(self, params: dict[str, Any]) -> dict[str, Any]:
        preview_id = _valid_preview_id(params.get("preview_id"))
        if not preview_id:
            return _manager_error("discard", "PREVIEW_ID_INVALID", "A valid preview_id is required.")
        if not self._runtime_storage_is_safe():
            return _manager_error(
                "discard",
                "RUNTIME_STORAGE_UNSAFE",
                "Stable promotion evidence storage resolves outside the project Runner runtime directory.",
            )
        existed = os.path.isfile(self._preview_path(preview_id))
        self._delete_preview(preview_id)
        return {
            "ok": True,
            "source": "stable_promotion_artifact_evidence",
            "action": "discard",
            "status": "discarded" if existed else "not_found",
            "preview_id": preview_id,
            "authority_boundary": _authority_boundary(),
        }

    def _validate_preview_artifact(self, artifact: dict[str, Any], preview_id: str) -> dict[str, Any] | None:
        if (
            artifact.get("schema_version") != PREVIEW_SCHEMA_VERSION
            or artifact.get("artifact_kind") != "stable_promotion_artifact_evidence_preview"
            or artifact.get("preview_id") != preview_id
            or artifact.get("project_root") != self.project_root
        ):
            return _manager_error("apply", "PREVIEW_BINDING_MISMATCH", "Stable promotion evidence preview binding is invalid.")
        expected = _canonical_sha256({key: value for key, value in artifact.items() if key != "preview_digest"})
        if not secrets.compare_digest(str(artifact.get("preview_digest") or ""), expected):
            return _manager_error("apply", "PREVIEW_DIGEST_MISMATCH", "Stable promotion evidence preview digest is invalid.")
        return None

    def _preview_path(self, preview_id: str) -> str:
        return str(Path(self.previews_root) / f"{preview_id}.json")

    def _runtime_storage_is_safe(self) -> bool:
        probe = str(Path(self.previews_root) / ".storage-probe.json")
        return _is_safe_runtime_artifact_path(self.project_root, probe)

    def _read_preview(self, preview_id: str) -> dict[str, Any] | None:
        try:
            with open(self._preview_path(preview_id), "r", encoding="utf-8") as handle:
                value = json.load(handle)
        except Exception:
            return None
        return value if isinstance(value, dict) else None

    def _delete_preview(self, preview_id: str) -> None:
        try:
            os.remove(self._preview_path(preview_id))
        except FileNotFoundError:
            pass


def _parse_ls_tree(raw: bytes) -> list[dict[str, str]] | None:
    entries: list[dict[str, str]] = []
    for record in (item for item in raw.split(b"\0") if item):
        try:
            metadata, raw_path = record.split(b"\t", 1)
            mode, object_type, object_id = metadata.decode("ascii").split(" ", 2)
        except (ValueError, UnicodeDecodeError):
            return None
        if not _OBJECT_ID_PATTERN.fullmatch(object_id):
            return None
        try:
            path = raw_path.decode("utf-8")
            path_encoding = "utf-8"
        except UnicodeDecodeError:
            path = base64.b64encode(raw_path).decode("ascii")
            path_encoding = "base64"
        entries.append(
            {
                "mode": mode,
                "object_type": object_type,
                "object_id": object_id,
                "path": path,
                "path_encoding": path_encoding,
            }
        )
    return entries


def _read_git_blob_fingerprints(project_root: str, object_ids: list[str]) -> dict[str, dict[str, Any]] | None:
    if not object_ids:
        return {}
    try:
        process = subprocess.Popen(
            ["git", "-C", project_root, "cat-file", "--batch"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return None
    if process.stdin is None or process.stdout is None:
        process.kill()
        return None
    fingerprints: dict[str, dict[str, Any]] = {}
    try:
        for expected_id in object_ids:
            process.stdin.write(f"{expected_id}\n".encode("ascii"))
            process.stdin.flush()
            header = process.stdout.readline()
            if not header.endswith(b"\n"):
                raise ValueError("missing cat-file header")
            actual_id, object_type, size_text = header[:-1].decode("ascii").split(" ", 2)
            size = int(size_text)
            if actual_id != expected_id or object_type != "blob" or size < 0:
                raise ValueError("unexpected cat-file object")
            digest = hashlib.sha256()
            remaining = size
            while remaining:
                chunk = process.stdout.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise ValueError("truncated cat-file blob")
                digest.update(chunk)
                remaining -= len(chunk)
            if process.stdout.read(1) != b"\n":
                raise ValueError("missing cat-file separator")
            fingerprints[expected_id] = {"sha256": digest.hexdigest(), "size_bytes": size}
        process.stdin.close()
        if process.wait(timeout=60) != 0:
            raise ValueError("cat-file failed")
    except (BrokenPipeError, OSError, subprocess.TimeoutExpired, UnicodeDecodeError, ValueError):
        process.kill()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        return None
    finally:
        process.stdout.close()
    return fingerprints


def _git_snapshot(project_root: str) -> dict[str, Any]:
    head = _resolve_commit(project_root, "HEAD")
    origin_main = _resolve_commit(project_root, "origin/main")
    status = _run_git(project_root, ["status", "--porcelain=v1", "-z", "--untracked-files=all"])
    dirty_count = count_promotion_relevant_porcelain_entries(status.get("stdout_bytes", b"")) if status["ok"] else None
    return {
        "head": head,
        "origin_main_head": origin_main,
        "origin_main_available": bool(origin_main),
        "worktree_clean": dirty_count == 0 if dirty_count is not None else None,
        "dirty_entry_count": dirty_count,
        "read_only": True,
    }


def count_promotion_relevant_porcelain_entries(raw: bytes) -> int:
    """Ignore only untracked Runner runtime evidence; preserve all source dirt."""
    count = 0
    for record in (item for item in raw.split(b"\0") if item):
        if len(record) >= 4 and record[:2] == b"??" and record[2:3] == b" ":
            path = record[3:].replace(b"\\", b"/")
            if path.startswith(b"./"):
                path = path[2:]
            if path.startswith(b".colameta/runtime/"):
                continue
        count += 1
    return count


def _apply_blockers(snapshot: dict[str, Any], candidate_head: str, manifest: dict[str, Any]) -> list[dict[str, str]]:
    blockers: list[dict[str, str]] = []
    if snapshot.get("head") != candidate_head:
        blockers.append(_blocker("CANDIDATE_NOT_CURRENT_HEAD", "Candidate commit is not the current project HEAD."))
    if snapshot.get("origin_main_available") is not True:
        blockers.append(_blocker("ORIGIN_MAIN_UNAVAILABLE", "origin/main could not be resolved."))
    elif snapshot.get("origin_main_head") != candidate_head:
        blockers.append(_blocker("CANDIDATE_NOT_ORIGIN_MAIN", "Candidate commit is not aligned with origin/main."))
    if snapshot.get("worktree_clean") is not True:
        blockers.append(_blocker("WORKTREE_NOT_CLEAN", "Worktree must be clean before persisting promotion evidence."))
    if manifest.get("available") is not True:
        blockers.append(_blocker("CANDIDATE_MANIFEST_UNAVAILABLE", "Exact candidate manifest could not be generated."))
    return blockers


def _resolve_commit(project_root: str, value: str | None) -> str | None:
    ref = value.strip() if isinstance(value, str) and value.strip() else "HEAD"
    if ref not in {"HEAD", "origin/main"} and not _OBJECT_ID_PATTERN.fullmatch(ref.lower()):
        return None
    result = _run_git(project_root, ["rev-parse", "--verify", f"{ref}^{{commit}}"])
    if not result["ok"]:
        return None
    resolved = str(result.get("stdout") or "").strip().lower()
    return resolved if _OBJECT_ID_PATTERN.fullmatch(resolved) else None


def _run_git(
    project_root: str,
    args: list[str],
    *,
    input_bytes: bytes | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            ["git", "-C", project_root, *args],
            input=input_bytes,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"ok": False, "stdout": "", "stdout_bytes": b""}
    return {
        "ok": completed.returncode == 0,
        "stdout": completed.stdout.decode("utf-8", errors="replace"),
        "stdout_bytes": completed.stdout,
    }


def _receipt_path(project_root: str, candidate_head: str) -> str:
    return resolve_project_runner_path(project_root, os.path.join(RECEIPTS_DIR, f"{candidate_head}.json"))


def _normalize_project_root(project_root: str) -> str:
    return os.path.realpath(os.path.abspath(os.path.expanduser(project_root)))


def _is_safe_runtime_artifact_path(project_root: str, path: str) -> bool:
    root = _normalize_project_root(project_root)
    runtime_root = os.path.abspath(resolve_project_runner_path(root, "runtime"))
    candidate = os.path.abspath(path)
    try:
        within_runtime = os.path.commonpath([candidate, runtime_root]) == runtime_root
    except ValueError:
        return False
    return within_runtime and os.path.realpath(candidate) == candidate


def _write_json_exclusive_atomic(path: str, payload: dict[str, Any]) -> bool:
    """Publish complete JSON once, without replacing a concurrent receipt."""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, temporary_path = tempfile.mkstemp(prefix=".tmp-stable-promotion-", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
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


def _receipt_digest(receipt: dict[str, Any]) -> str:
    return _canonical_sha256({key: value for key, value in receipt.items() if key != "receipt_digest"})


def _manifest_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    summary = {key: value for key, value in manifest.items() if key != "files"}
    if "files" in manifest:
        summary["file_entries_omitted_from_response"] = True
    return summary


def _manifest_unavailable(reason: str) -> dict[str, Any]:
    return {
        "available": False,
        "unavailable_reason": reason,
        "read_only": True,
        "side_effects": False,
        "worktree_content_used": False,
    }


def _status_error(error_code: str, message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "source": "stable_promotion_artifact_evidence",
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "read_only": True,
        "side_effects": False,
        "status": "invalid",
        "verified": False,
        "current": False,
        "error_code": error_code,
        "message": message,
    }


def _manager_error(action: str, error_code: str, message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "source": "stable_promotion_artifact_evidence",
        "action": action,
        "status": "failed",
        "error_code": error_code,
        "message": message,
        "authority_boundary": _authority_boundary(),
    }


def _authority_boundary() -> dict[str, bool]:
    return {
        "writes_runner_runtime_evidence_only": True,
        "does_not_read_worktree_file_content": True,
        "does_not_replace_stable_service": True,
        "does_not_restart_services": True,
        "does_not_modify_git": True,
        "does_not_push": True,
        "does_not_release_or_deploy": True,
        "does_not_read_tokens_or_cookies": True,
        "does_not_read_raw_logs": True,
    }


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _blocker(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def _clean_optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _valid_preview_id(value: Any) -> str | None:
    cleaned = _clean_optional_text(value)
    return cleaned if cleaned and _PREVIEW_ID_PATTERN.fullmatch(cleaned) else None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _is_expired(value: Any) -> bool:
    if not isinstance(value, str):
        return True
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return True
    return parsed <= _utc_now()


def _relative_runner_path(project_root: str, absolute_path: str) -> str:
    return os.path.relpath(absolute_path, project_root).replace(os.sep, "/")
