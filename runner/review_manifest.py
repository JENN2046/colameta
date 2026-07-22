"""Read-only, manifest-bound source review primitives.

The normal source-review allowlist deliberately keeps the public MCP surface
narrow.  An independent review sometimes needs a different *finite* set of
inputs, however: a caller supplies the exact paths and hashes up front, then
receives short-lived resources for those exact immutable subjects.  This module
implements that contract without turning it into arbitrary project-file access.

Nothing here executes a command, writes a project file, or stores file content
on disk.  Manifest sessions are process-local and expire quickly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import errno
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import stat
import threading
from typing import Any, Callable

from runner.path_policy import RunnerPathPolicy
from runner.project_identity import build_project_identity
from runner.runner_paths import resolve_project_runner_path, resolve_project_runner_plan_path


REVIEW_MANIFEST_SCHEMA_VERSION = "colameta.review_manifest.v1"
REVIEW_MANIFEST_WORKFLOW = "review_manifest"
REVIEW_MANIFEST_WORKFLOW_INTENT = "independent_review"

REVIEW_MANIFEST_MAX_SUBJECTS = 64
REVIEW_MANIFEST_MAX_FILE_BYTES = 2_000_000
REVIEW_MANIFEST_MAX_TOTAL_BYTES = 16_000_000
REVIEW_MANIFEST_PAGE_CHARS = 12_000

_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_SENSITIVE_PATH_PARTS = frozenset(
    {
        "secrets",
        "credentials",
        "private",
        "tokens",
        "sessions",
        "localstate",
        ".localstate",
        "state-private",
        ".ssh",
    }
)
_HIGH_RISK_MANIFEST_PATH_PARTS = frozenset(
    {
        "config",
        "configs",
        "configuration",
        "deploy",
        "deployment",
        "infrastructure",
        "infra",
    }
)
_SENSITIVE_FILE_SUFFIXES = (
    ".pem",
    ".key",
    ".crt",
    ".p12",
    ".pfx",
    ".cookie",
    ".cookies",
    ".session",
    ".token",
    ".secret",
    ".credentials",
    ".sqlite",
    ".sqlite3",
    ".db",
    ".log",
)
_SAFE_TEXT_SUFFIXES = frozenset(
    {
        ".py",
        ".md",
        ".mdx",
        ".txt",
        ".rst",
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".ini",
        ".cfg",
        ".xml",
        ".html",
        ".css",
        ".js",
        ".ts",
        ".tsx",
        ".jsx",
        ".vue",
        ".svelte",
        ".astro",
        ".go",
        ".php",
        ".java",
        ".rs",
        ".rb",
        ".cs",
        ".kt",
        ".swift",
        ".sh",
        ".bash",
        ".zsh",
        ".fish",
        ".sql",
        ".graphql",
        ".gql",
        ".properties",
        ".gradle",
        ".conf",
    }
)
_SAFE_TEXT_BASENAMES = frozenset(
    {
        "AGENTS.md",
        "Dockerfile",
        "Makefile",
        "LICENSE",
        "NOTICE",
        "CODEOWNERS",
        ".gitignore",
        ".editorconfig",
    }
)


class ReviewManifestError(ValueError):
    """A bounded, safe-to-return manifest contract error."""

    def __init__(
        self,
        error_code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.details = details or {}


@dataclass(frozen=True)
class ReviewManifestSubject:
    path: str
    sha256: str
    byte_size: int
    char_count: int
    page_count: int


@dataclass(frozen=True)
class ReviewManifestInspection:
    manifest: dict[str, Any]
    context_binding: dict[str, Any]
    subjects: tuple[ReviewManifestSubject, ...]
    manifest_sha256: str


@dataclass(frozen=True)
class ReviewManifestHandle:
    review_manifest_id: str
    manifest_sha256: str
    subject_count: int
    created_at: str
    expires_at: str


@dataclass(frozen=True)
class ReviewManifestPage:
    review_manifest_id: str
    review_unit: str
    subject_index: int
    path: str
    sha256: str
    page: int
    page_count: int
    page_char_start: int
    page_char_end: int
    expires_at: str
    content: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "review_manifest_id": self.review_manifest_id,
            "review_unit": self.review_unit,
            "subject_index": self.subject_index,
            "path": self.path,
            "sha256": self.sha256,
            "page": self.page,
            "page_count": self.page_count,
            "page_char_start": self.page_char_start,
            "page_char_end": self.page_char_end,
            "expires_at": self.expires_at,
            "content": self.content,
        }


@dataclass(frozen=True)
class StoredReviewManifest:
    handle: ReviewManifestHandle
    project_root: str
    manifest: dict[str, Any]
    context_binding: dict[str, Any]
    subjects: tuple[ReviewManifestSubject, ...]
    expires_at: datetime


class ReviewManifestStore:
    """Short-lived, process-local bindings for independent review inputs."""

    def __init__(
        self,
        *,
        ttl_seconds: int = 900,
        max_items: int = 32,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self._ttl_seconds = max(1, int(ttl_seconds))
        self._max_items = max(1, int(max_items))
        self._now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self._items: dict[str, StoredReviewManifest] = {}
        self._lock = threading.RLock()

    def put(
        self,
        *,
        project_root: str,
        inspection: ReviewManifestInspection,
    ) -> ReviewManifestHandle:
        now = self._now()
        expires_at = now + timedelta(seconds=self._ttl_seconds)
        review_manifest_id = secrets.token_urlsafe(24)
        handle = ReviewManifestHandle(
            review_manifest_id=review_manifest_id,
            manifest_sha256=inspection.manifest_sha256,
            subject_count=len(inspection.subjects),
            created_at=now.isoformat(),
            expires_at=expires_at.isoformat(),
        )
        stored = StoredReviewManifest(
            handle=handle,
            project_root=os.path.realpath(os.path.abspath(project_root)),
            manifest=dict(inspection.manifest),
            context_binding=dict(inspection.context_binding),
            subjects=tuple(inspection.subjects),
            expires_at=expires_at,
        )
        with self._lock:
            self._purge_expired_locked(now)
            self._items[review_manifest_id] = stored
            self._trim_locked()
        return handle

    def get(self, review_manifest_id: str) -> StoredReviewManifest | None:
        if not isinstance(review_manifest_id, str) or not review_manifest_id:
            return None
        now = self._now()
        with self._lock:
            self._purge_expired_locked(now)
            return self._items.get(review_manifest_id)

    def _now(self) -> datetime:
        now = self._now_fn()
        if now.tzinfo is None:
            return now.replace(tzinfo=timezone.utc)
        return now.astimezone(timezone.utc)

    def _purge_expired_locked(self, now: datetime) -> None:
        for review_manifest_id in [
            item_id
            for item_id, stored in self._items.items()
            if stored.expires_at <= now
        ]:
            self._items.pop(review_manifest_id, None)

    def _trim_locked(self) -> None:
        overflow = len(self._items) - self._max_items
        if overflow <= 0:
            return
        oldest = sorted(
            self._items.values(),
            key=lambda stored: stored.handle.created_at,
        )[:overflow]
        for stored in oldest:
            self._items.pop(stored.handle.review_manifest_id, None)


def collect_review_context_binding(
    project_root: str,
    *,
    project_name: str | None = None,
) -> dict[str, Any]:
    """Return the non-sensitive facts which bind a review session to a checkout."""

    normalized_root = os.path.realpath(os.path.abspath(os.path.expanduser(project_root)))
    identity = build_project_identity(normalized_root)
    resolved_project_name = (
        project_name.strip()
        if isinstance(project_name, str) and project_name.strip()
        else str(identity.get("project_name") or "").strip()
    )
    plan_path = resolve_project_runner_plan_path(normalized_root)
    plan_digest = _sha256_regular_file(plan_path, max_bytes=REVIEW_MANIFEST_MAX_FILE_BYTES)
    plan_present = plan_digest is not None
    return {
        "project_name": resolved_project_name,
        "branch": identity.get("git_branch"),
        "head": identity.get("git_head"),
        "runner_plan": {
            "mode": "managed" if plan_present else "source-only",
            "plan_sha256": plan_digest,
        },
        # Only this one public state field is read through a bounded,
        # no-follow helper. Raw Runner state is never attached to the manifest
        # or MCP response.
        "current_version": _bounded_current_version(normalized_root) if plan_present else None,
    }


def inspect_review_manifest(
    value: Any,
    *,
    project_root: str,
    context_binding: dict[str, Any],
) -> ReviewManifestInspection:
    """Validate a manifest, its runtime binding, and every declared subject."""

    if not isinstance(value, dict):
        raise ReviewManifestError(
            "INVALID_REVIEW_MANIFEST",
            "review_manifest 必须是对象。",
        )

    manifest = _normalize_manifest(value)
    manifest_binding = {
        key: manifest[key]
        for key in (
            "project_name",
            "branch",
            "head",
            "runner_plan",
            "current_version",
        )
    }
    mismatches = context_binding_mismatches(manifest_binding, context_binding)
    if mismatches:
        raise ReviewManifestError(
            "CONTEXT_BINDING_MISMATCH",
            "review_manifest 与当前项目上下文不一致，已停止读取。",
            {"mismatches": mismatches},
        )

    root = os.path.realpath(os.path.abspath(os.path.expanduser(project_root)))
    subjects: list[ReviewManifestSubject] = []
    total_bytes = 0
    for item in manifest["subjects"]:
        path = item["path"]
        expected_sha256 = item["sha256"]
        raw, text = read_manifest_subject_file(root, path)
        actual_sha256 = hashlib.sha256(raw).hexdigest()
        if not secrets.compare_digest(actual_sha256, expected_sha256):
            raise ReviewManifestError(
                "REVIEW_MANIFEST_SUBJECT_HASH_MISMATCH",
                f"manifest subject 的 SHA-256 与当前文件不一致：{path}",
                {
                    "path": path,
                    "expected_sha256": expected_sha256,
                    "actual_sha256": actual_sha256,
                },
            )
        total_bytes += len(raw)
        if total_bytes > REVIEW_MANIFEST_MAX_TOTAL_BYTES:
            raise ReviewManifestError(
                "REVIEW_MANIFEST_TOTAL_SIZE_EXCEEDED",
                "review_manifest 声明的 subject 总大小超过只读审查上限。",
                {
                    "max_total_bytes": REVIEW_MANIFEST_MAX_TOTAL_BYTES,
                    "subject_count": len(subjects) + 1,
                },
            )
        char_count = len(text)
        subjects.append(
            ReviewManifestSubject(
                path=path,
                sha256=expected_sha256,
                byte_size=len(raw),
                char_count=char_count,
                page_count=max(1, (char_count + REVIEW_MANIFEST_PAGE_CHARS - 1) // REVIEW_MANIFEST_PAGE_CHARS),
            )
        )

    normalized_context = {
        **manifest_binding,
        "review_unit": manifest["review_unit"],
        "workflow_intent": manifest["workflow_intent"],
    }
    normalized_manifest = {
        "schema_version": manifest["schema_version"],
        **normalized_context,
        "subjects": [
            {"path": subject.path, "sha256": subject.sha256}
            for subject in subjects
        ],
        "acceptance_commands": manifest["acceptance_commands"],
    }
    manifest_sha256 = _canonical_sha256(normalized_manifest)
    return ReviewManifestInspection(
        manifest=normalized_manifest,
        context_binding=normalized_context,
        subjects=tuple(subjects),
        manifest_sha256=manifest_sha256,
    )


def context_binding_mismatches(
    expected: dict[str, Any],
    actual: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return public, non-sensitive mismatch details for runtime bindings."""

    mismatches: list[dict[str, Any]] = []
    for field in ("project_name", "branch", "head", "runner_plan", "current_version"):
        expected_value = expected.get(field)
        actual_value = actual.get(field)
        if expected_value != actual_value:
            mismatches.append(
                {
                    "field": field,
                    "expected": expected_value,
                    "actual": actual_value,
                }
            )
    return mismatches


def verify_stored_review_manifest(
    stored: StoredReviewManifest,
    *,
    current_context_binding: dict[str, Any],
) -> dict[str, Any]:
    """Re-check checkout binding and every subject hash without returning content."""

    verify_stored_review_context(
        stored,
        current_context_binding=current_context_binding,
    )

    verified: list[dict[str, Any]] = []
    for index, subject in enumerate(stored.subjects, start=1):
        raw, _text = read_manifest_subject_file(stored.project_root, subject.path)
        actual_sha256 = hashlib.sha256(raw).hexdigest()
        if not secrets.compare_digest(actual_sha256, subject.sha256):
            raise ReviewManifestError(
                "REVIEW_MANIFEST_SUBJECT_HASH_MISMATCH",
                f"manifest subject 的 SHA-256 与当前文件不一致：{subject.path}",
                {
                    "path": subject.path,
                    "expected_sha256": subject.sha256,
                    "actual_sha256": actual_sha256,
                },
            )
        verified.append(
            {
                "subject_index": index,
                "path": subject.path,
                "sha256": subject.sha256,
                "byte_size": subject.byte_size,
            }
        )
    return {
        "context_binding": "matched",
        "subject_hashes": "matched",
        "verified_subject_count": len(verified),
        "subjects": verified,
    }


def verify_stored_review_context(
    stored: StoredReviewManifest,
    *,
    current_context_binding: dict[str, Any],
) -> None:
    """Fail closed when a stored session no longer names this checkout."""

    expected_runtime_binding = {
        key: stored.context_binding[key]
        for key in ("project_name", "branch", "head", "runner_plan", "current_version")
    }
    mismatches = context_binding_mismatches(expected_runtime_binding, current_context_binding)
    if mismatches:
        raise ReviewManifestError(
            "CONTEXT_BINDING_MISMATCH",
            "审查会话建立后项目上下文已变化，已停止读取。",
            {"mismatches": mismatches},
        )


def read_stored_review_manifest_page(
    stored: StoredReviewManifest,
    *,
    subject_index: int,
    page: int,
) -> ReviewManifestPage:
    """Read one page only after re-verifying the exact subject hash."""

    if subject_index < 1 or subject_index > len(stored.subjects):
        raise ReviewManifestError(
            "REVIEW_MANIFEST_SUBJECT_NOT_FOUND",
            "review manifest subject 不存在。",
        )
    subject = stored.subjects[subject_index - 1]
    if page < 1 or page > subject.page_count:
        raise ReviewManifestError(
            "REVIEW_MANIFEST_PAGE_NOT_FOUND",
            "review manifest subject 页码无效。",
        )
    raw, text = read_manifest_subject_file(stored.project_root, subject.path)
    actual_sha256 = hashlib.sha256(raw).hexdigest()
    if not secrets.compare_digest(actual_sha256, subject.sha256):
        raise ReviewManifestError(
            "REVIEW_MANIFEST_SUBJECT_HASH_MISMATCH",
            f"manifest subject 的 SHA-256 与当前文件不一致：{subject.path}",
            {
                "path": subject.path,
                "expected_sha256": subject.sha256,
                "actual_sha256": actual_sha256,
            },
        )
    start = (page - 1) * REVIEW_MANIFEST_PAGE_CHARS
    end = min(start + REVIEW_MANIFEST_PAGE_CHARS, len(text))
    return ReviewManifestPage(
        review_manifest_id=stored.handle.review_manifest_id,
        review_unit=str(stored.context_binding["review_unit"]),
        subject_index=subject_index,
        path=subject.path,
        sha256=subject.sha256,
        page=page,
        page_count=subject.page_count,
        page_char_start=start,
        page_char_end=end,
        expires_at=stored.handle.expires_at,
        content=text[start:end],
    )


def read_manifest_subject_file(project_root: str, path: str) -> tuple[bytes, str]:
    """Safely load one declared subject without following symlinks."""

    normalized_path = normalize_manifest_subject_path(path)
    try:
        fd = _open_manifest_subject_fd(project_root, normalized_path)
        with os.fdopen(fd, "rb") as handle:
            opened = os.fstat(handle.fileno())
            if not stat.S_ISREG(opened.st_mode) or opened.st_size > REVIEW_MANIFEST_MAX_FILE_BYTES:
                raise ReviewManifestError(
                    "REVIEW_MANIFEST_SUBJECT_UNSAFE",
                    f"manifest subject 无法安全读取：{normalized_path}",
                    {"path": normalized_path},
                )
            raw = handle.read(REVIEW_MANIFEST_MAX_FILE_BYTES + 1)
    except ReviewManifestError:
        raise
    except OSError as exc:
        raise ReviewManifestError(
            "REVIEW_MANIFEST_SUBJECT_UNAVAILABLE",
            f"manifest subject 无法安全读取：{normalized_path}",
            {"path": normalized_path},
        ) from exc
    if len(raw) > REVIEW_MANIFEST_MAX_FILE_BYTES:
        raise ReviewManifestError(
            "REVIEW_MANIFEST_SUBJECT_TOO_LARGE",
            f"manifest subject 超过单文件只读审查上限：{normalized_path}",
            {
                "path": normalized_path,
                "max_file_bytes": REVIEW_MANIFEST_MAX_FILE_BYTES,
            },
        )
    if b"\0" in raw[:4096]:
        raise ReviewManifestError(
            "REVIEW_MANIFEST_SUBJECT_NOT_TEXT",
            f"manifest subject 不是 UTF-8 文本文件：{normalized_path}",
            {"path": normalized_path},
        )
    try:
        return raw, raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReviewManifestError(
            "REVIEW_MANIFEST_SUBJECT_NOT_TEXT",
            f"manifest subject 不是 UTF-8 文本文件：{normalized_path}",
            {"path": normalized_path},
        ) from exc


def _open_manifest_subject_fd(project_root: str, normalized_path: str) -> int:
    """Open a literal relative path while rejecting every symlink component.

    ``Path.resolve`` plus a later open has a time-of-check/time-of-use gap.
    Walk from an opened project-root directory instead: each component is
    opened relative to the already-open parent and with ``O_NOFOLLOW``. The
    returned descriptor remains pinned to the exact regular-file inode that is
    subsequently hashed and returned to the reviewer.
    """

    required_open_flags = ("O_NOFOLLOW", "O_DIRECTORY", "O_NONBLOCK")
    if (
        any(not hasattr(os, flag) for flag in required_open_flags)
        or os.open not in os.supports_dir_fd
        or os.stat not in os.supports_dir_fd
        or os.stat not in os.supports_follow_symlinks
    ):
        raise ReviewManifestError(
            "REVIEW_MANIFEST_SUBJECT_UNAVAILABLE",
            "当前运行时不支持安全的无符号链接 subject 读取。",
            {"path": normalized_path},
        )
    root = os.path.realpath(os.path.abspath(os.path.expanduser(project_root)))
    directory_flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY
    directory_flags |= os.O_NONBLOCK
    try:
        current_fd = os.open(root, directory_flags)
    except OSError as exc:
        raise ReviewManifestError(
            "REVIEW_MANIFEST_SUBJECT_UNAVAILABLE",
            f"manifest subject 无法安全读取：{normalized_path}",
            {"path": normalized_path},
        ) from exc
    try:
        if not stat.S_ISDIR(os.fstat(current_fd).st_mode):
            raise ReviewManifestError(
                "REVIEW_MANIFEST_SUBJECT_UNSAFE",
                f"manifest project root 不是安全目录：{normalized_path}",
                {"path": normalized_path},
            )
        parts = PurePosixPath(normalized_path).parts
        for index, part in enumerate(parts):
            is_final = index == len(parts) - 1
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
            if not is_final:
                flags |= os.O_DIRECTORY
            try:
                preopened = os.stat(part, dir_fd=current_fd, follow_symlinks=False)
            except OSError as exc:
                raise ReviewManifestError(
                    "REVIEW_MANIFEST_SUBJECT_UNAVAILABLE",
                    f"manifest subject 无法安全读取：{normalized_path}",
                    {"path": normalized_path},
                ) from exc
            expected_type = stat.S_ISREG if is_final else stat.S_ISDIR
            if stat.S_ISLNK(preopened.st_mode) or not expected_type(preopened.st_mode):
                raise ReviewManifestError(
                    "REVIEW_MANIFEST_SUBJECT_UNSAFE",
                    f"manifest subject 不是可安全读取的常规文件：{normalized_path}",
                    {"path": normalized_path},
                )
            if is_final and preopened.st_size > REVIEW_MANIFEST_MAX_FILE_BYTES:
                raise ReviewManifestError(
                    "REVIEW_MANIFEST_SUBJECT_TOO_LARGE",
                    f"manifest subject 超过单文件只读审查上限：{normalized_path}",
                    {
                        "path": normalized_path,
                        "max_file_bytes": REVIEW_MANIFEST_MAX_FILE_BYTES,
                    },
                )
            try:
                next_fd = os.open(part, flags, dir_fd=current_fd)
            except OSError as exc:
                if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
                    raise ReviewManifestError(
                        "REVIEW_MANIFEST_SUBJECT_UNSAFE",
                        f"manifest subject 路径不能经过符号链接：{normalized_path}",
                        {"path": normalized_path},
                    ) from exc
                raise ReviewManifestError(
                    "REVIEW_MANIFEST_SUBJECT_UNAVAILABLE",
                    f"manifest subject 无法安全读取：{normalized_path}",
                    {"path": normalized_path},
                ) from exc
            os.close(current_fd)
            current_fd = next_fd
            mode = os.fstat(current_fd).st_mode
            if (not is_final and not stat.S_ISDIR(mode)) or (is_final and not stat.S_ISREG(mode)):
                raise ReviewManifestError(
                    "REVIEW_MANIFEST_SUBJECT_UNSAFE",
                    f"manifest subject 不是可安全读取的常规文件：{normalized_path}",
                    {"path": normalized_path},
                )
        return current_fd
    except Exception:
        os.close(current_fd)
        raise


def normalize_manifest_subject_path(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReviewManifestError(
            "INVALID_REVIEW_MANIFEST_SUBJECT",
            "manifest subject.path 必须是非空项目内相对路径。",
        )
    path = value.strip().replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    pure = PurePosixPath(path)
    if (
        not path
        or pure.is_absolute()
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise ReviewManifestError(
            "INVALID_REVIEW_MANIFEST_SUBJECT",
            "manifest subject.path 必须是项目内相对路径，且不能包含 ..。",
        )
    normalized = str(pure)
    lower_name = pure.name.lower()
    if (
        any(part.lower() in _SENSITIVE_PATH_PARTS for part in pure.parts)
        or any(part.lower() in _HIGH_RISK_MANIFEST_PATH_PARTS for part in pure.parts)
        or lower_name == ".env"
        or lower_name.startswith(".env.")
        or lower_name.endswith(_SENSITIVE_FILE_SUFFIXES)
    ):
        raise ReviewManifestError(
            "REVIEW_MANIFEST_SUBJECT_DENIED",
            "manifest subject 命中敏感路径规则，已拒绝读取。",
            {"path": normalized},
        )
    policy = RunnerPathPolicy()
    if policy.is_denied_source_path(normalized):
        raise ReviewManifestError(
            "REVIEW_MANIFEST_SUBJECT_DENIED",
            "manifest subject 命中 Runner deny 规则，已拒绝读取。",
            {"path": normalized},
        )
    suffix = Path(pure.name).suffix.lower()
    if pure.name not in _SAFE_TEXT_BASENAMES and suffix not in _SAFE_TEXT_SUFFIXES:
        raise ReviewManifestError(
            "REVIEW_MANIFEST_SUBJECT_DENIED",
            "manifest subject 必须是明确允许的文本源码、文档或治理文件。",
            {"path": normalized},
        )
    return normalized


def _normalize_manifest(value: dict[str, Any]) -> dict[str, Any]:
    required = {
        "schema_version",
        "review_unit",
        "workflow_intent",
        "project_name",
        "branch",
        "head",
        "runner_plan",
        "current_version",
        "subjects",
    }
    missing = sorted(key for key in required if key not in value)
    if missing:
        raise ReviewManifestError(
            "CONTEXT_BINDING_MISMATCH",
            "review_manifest 缺少必需的上下文绑定字段。",
            {"missing_fields": missing},
        )
    unexpected = sorted(
        key
        for key in value
        if key not in required | {"acceptance_commands"}
    )
    if unexpected:
        raise ReviewManifestError(
            "INVALID_REVIEW_MANIFEST",
            "review_manifest 包含未声明字段。",
            {"unexpected_fields": unexpected},
        )
    schema_version = value.get("schema_version")
    if schema_version != REVIEW_MANIFEST_SCHEMA_VERSION:
        raise ReviewManifestError(
            "INVALID_REVIEW_MANIFEST",
            f"review_manifest.schema_version 必须是 {REVIEW_MANIFEST_SCHEMA_VERSION}。",
        )
    review_unit = _required_text(value.get("review_unit"), "review_unit", max_chars=160)
    workflow_intent = _required_text(value.get("workflow_intent"), "workflow_intent", max_chars=80)
    if workflow_intent != REVIEW_MANIFEST_WORKFLOW_INTENT:
        raise ReviewManifestError(
            "CONTEXT_BINDING_MISMATCH",
            "review_manifest.workflow_intent 必须绑定为 independent_review。",
            {
                "mismatches": [
                    {
                        "field": "workflow_intent",
                        "expected": REVIEW_MANIFEST_WORKFLOW_INTENT,
                        "actual": workflow_intent,
                    }
                ]
            },
        )
    project_name = _required_text(value.get("project_name"), "project_name", max_chars=128)
    branch = _required_text(value.get("branch"), "branch", max_chars=255)
    head = _required_text(value.get("head"), "head", max_chars=128)
    if not re.fullmatch(r"[0-9a-fA-F]{40,128}", head):
        raise ReviewManifestError(
            "INVALID_REVIEW_MANIFEST",
            "review_manifest.head 必须是完整 Git commit SHA。",
        )
    runner_plan = _normalize_runner_plan_binding(value.get("runner_plan"))
    current_version = value.get("current_version")
    if current_version is not None:
        current_version = _required_text(current_version, "current_version", max_chars=128)
    subjects_value = value.get("subjects")
    if not isinstance(subjects_value, list) or not subjects_value:
        raise ReviewManifestError(
            "INVALID_REVIEW_MANIFEST",
            "review_manifest.subjects 必须是非空数组。",
        )
    if len(subjects_value) > REVIEW_MANIFEST_MAX_SUBJECTS:
        raise ReviewManifestError(
            "INVALID_REVIEW_MANIFEST",
            "review_manifest.subjects 超过上限。",
            {"max_subjects": REVIEW_MANIFEST_MAX_SUBJECTS},
        )
    seen_paths: set[str] = set()
    subjects: list[dict[str, str]] = []
    for index, raw_subject in enumerate(subjects_value, start=1):
        if not isinstance(raw_subject, dict):
            raise ReviewManifestError(
                "INVALID_REVIEW_MANIFEST_SUBJECT",
                "review_manifest.subjects 的每一项必须是对象。",
                {"subject_index": index},
            )
        if set(raw_subject) != {"path", "sha256"}:
            raise ReviewManifestError(
                "INVALID_REVIEW_MANIFEST_SUBJECT",
                "review_manifest.subject 只允许 path 与 sha256。",
                {"subject_index": index},
            )
        path = normalize_manifest_subject_path(raw_subject.get("path"))
        if path in seen_paths:
            raise ReviewManifestError(
                "INVALID_REVIEW_MANIFEST_SUBJECT",
                "review_manifest.subjects 不允许重复 path。",
                {"path": path},
            )
        seen_paths.add(path)
        sha256 = raw_subject.get("sha256")
        if not isinstance(sha256, str) or not _SHA256_RE.fullmatch(sha256.strip()):
            raise ReviewManifestError(
                "INVALID_REVIEW_MANIFEST_SUBJECT",
                "review_manifest.subject.sha256 必须是 SHA-256 十六进制摘要。",
                {"subject_index": index, "path": path},
            )
        subjects.append({"path": path, "sha256": sha256.strip().lower()})
    return {
        "schema_version": REVIEW_MANIFEST_SCHEMA_VERSION,
        "review_unit": review_unit,
        "workflow_intent": workflow_intent,
        "project_name": project_name,
        "branch": branch,
        "head": head.lower(),
        "runner_plan": runner_plan,
        "current_version": current_version,
        "subjects": subjects,
        "acceptance_commands": _normalize_acceptance_commands(value.get("acceptance_commands")),
    }


def _normalize_runner_plan_binding(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"mode", "plan_sha256"}:
        raise ReviewManifestError(
            "CONTEXT_BINDING_MISMATCH",
            "review_manifest.runner_plan 必须精确包含 mode 与 plan_sha256。",
        )
    mode = value.get("mode")
    plan_sha256 = value.get("plan_sha256")
    if mode not in {"managed", "source-only"}:
        raise ReviewManifestError(
            "CONTEXT_BINDING_MISMATCH",
            "review_manifest.runner_plan.mode 必须是 managed 或 source-only。",
        )
    if plan_sha256 is None:
        if mode != "source-only":
            raise ReviewManifestError(
                "CONTEXT_BINDING_MISMATCH",
                "managed runner_plan 必须携带 plan_sha256。",
            )
        return {"mode": mode, "plan_sha256": None}
    if not isinstance(plan_sha256, str) or not _SHA256_RE.fullmatch(plan_sha256.strip()):
        raise ReviewManifestError(
            "CONTEXT_BINDING_MISMATCH",
            "runner_plan.plan_sha256 必须是 SHA-256 摘要或 source-only 的 null。",
        )
    return {"mode": mode, "plan_sha256": plan_sha256.strip().lower()}


def _normalize_acceptance_commands(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 32:
        raise ReviewManifestError(
            "INVALID_REVIEW_MANIFEST",
            "review_manifest.acceptance_commands 必须是最多 32 项的数组。",
        )
    normalized: list[dict[str, Any]] = []
    for index, raw_command in enumerate(value, start=1):
        if isinstance(raw_command, str):
            command = _required_text(raw_command, "acceptance_commands.command", max_chars=2000)
            normalized.append({"command": command})
            continue
        if not isinstance(raw_command, dict) or "command" not in raw_command:
            raise ReviewManifestError(
                "INVALID_REVIEW_MANIFEST",
                "acceptance_commands 项必须是 command 字符串或含 command 的对象。",
                {"command_index": index},
            )
        unexpected = set(raw_command) - {"command", "timeout_seconds", "continue_on_failure"}
        if unexpected:
            raise ReviewManifestError(
                "INVALID_REVIEW_MANIFEST",
                "acceptance_commands 项包含未声明字段。",
                {"command_index": index, "unexpected_fields": sorted(unexpected)},
            )
        command = _required_text(raw_command.get("command"), "acceptance_commands.command", max_chars=2000)
        item: dict[str, Any] = {"command": command}
        timeout_seconds = raw_command.get("timeout_seconds")
        if timeout_seconds is not None:
            if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int) or not (1 <= timeout_seconds <= 3600):
                raise ReviewManifestError(
                    "INVALID_REVIEW_MANIFEST",
                    "acceptance_commands.timeout_seconds 必须是 1..3600 的整数。",
                    {"command_index": index},
                )
            item["timeout_seconds"] = timeout_seconds
        continue_on_failure = raw_command.get("continue_on_failure")
        if continue_on_failure is not None:
            if not isinstance(continue_on_failure, bool):
                raise ReviewManifestError(
                    "INVALID_REVIEW_MANIFEST",
                    "acceptance_commands.continue_on_failure 必须是布尔值。",
                    {"command_index": index},
                )
            item["continue_on_failure"] = continue_on_failure
        normalized.append(item)
    return normalized


def _required_text(value: Any, field: str, *, max_chars: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > max_chars:
        raise ReviewManifestError(
            "CONTEXT_BINDING_MISMATCH",
            f"review_manifest.{field} 必须是非空且长度受限的字符串。",
            {"field": field},
        )
    text = value.strip()
    if any(ord(char) < 32 for char in text):
        raise ReviewManifestError(
            "INVALID_REVIEW_MANIFEST",
            f"review_manifest.{field} 不能包含控制字符。",
            {"field": field},
        )
    return text


def _canonical_sha256(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256_regular_file(path: str, *, max_bytes: int) -> str | None:
    try:
        info = os.lstat(path)
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_size > max_bytes:
            return None
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as handle:
            opened = os.fstat(handle.fileno())
            if not stat.S_ISREG(opened.st_mode) or opened.st_size > max_bytes:
                return None
            digest = hashlib.sha256()
            for chunk in iter(lambda: handle.read(64 * 1024), b""):
                digest.update(chunk)
            return digest.hexdigest()
    except OSError:
        return None


def _bounded_current_version(project_root: str) -> str | None:
    """Read only the public current-version field from bounded local state."""

    state_path = resolve_project_runner_path(project_root, "state.json")
    raw = _read_regular_file_bytes(state_path, max_bytes=512_000)
    if raw is None:
        return None
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    value = payload.get("current_version") if isinstance(payload, dict) else None
    return value.strip() if isinstance(value, str) and value.strip() else None


def _read_regular_file_bytes(path: str, *, max_bytes: int) -> bytes | None:
    try:
        info = os.lstat(path)
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_size > max_bytes:
            return None
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as handle:
            opened = os.fstat(handle.fileno())
            if not stat.S_ISREG(opened.st_mode) or opened.st_size > max_bytes:
                return None
            raw = handle.read(max_bytes + 1)
        return raw if len(raw) <= max_bytes else None
    except OSError:
        return None
