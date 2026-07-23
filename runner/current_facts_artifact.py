"""Redacted, deterministic current-facts artifacts and their local archive.

This module deliberately starts from ``canonical_project_state`` rather than
opening Git, Runner, service, connector, report, or credential sources.  The
artifact is therefore a bounded observation product: it makes freshness and
authority explicit without becoming a new source of truth or an authorization
token.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import threading
from typing import Any, Callable


CURRENT_FACTS_ARTIFACT_SCHEMA_VERSION = "colameta.current_facts_artifact.v1"
CURRENT_FACTS_ARCHIVE_ROOT = ".colameta/reports/current-facts"
CURRENT_FACTS_PREVIEW_TTL_SECONDS = 900
CURRENT_FACTS_PREVIEW_MAX_ITEMS = 64

_SENSITIVE_KEY_PARTS = (
    "token",
    "secret",
    "password",
    "cookie",
    "credential",
    "authorization_header",
    "private_key",
    "raw_log",
    "log_content",
    "project_root",
    "filesystem_path",
)


class CurrentFactsArtifactError(ValueError):
    """A public-safe current-facts artifact failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class CurrentFactsArtifact:
    """One fully rendered, redacted current-facts snapshot."""

    payload: dict[str, Any]
    json_text: str
    markdown_text: str
    canonical_state_sha256: str
    canonical_state_semantic_sha256: str
    snapshot_json_sha256: str
    snapshot_markdown_sha256: str
    archive_stem: str

    @property
    def observed_at(self) -> str:
        return str(self.payload["observed_at"])

    def descriptor(self) -> dict[str, Any]:
        current_facts = self.payload.get("current_facts")
        conclusion = current_facts.get("current_conclusion") if isinstance(current_facts, dict) else {}
        freshness = current_facts.get("freshness") if isinstance(current_facts, dict) else {}
        return {
            "schema_version": CURRENT_FACTS_ARTIFACT_SCHEMA_VERSION,
            "observed_at": self.observed_at,
            "canonical_state_sha256": self.canonical_state_sha256,
            "canonical_state_semantic_sha256": self.canonical_state_semantic_sha256,
            "snapshot_json_sha256": self.snapshot_json_sha256,
            "snapshot_markdown_sha256": self.snapshot_markdown_sha256,
            "archive_root": CURRENT_FACTS_ARCHIVE_ROOT,
            "json_path": f"{CURRENT_FACTS_ARCHIVE_ROOT}/{self.archive_stem}.json",
            "markdown_path": f"{CURRENT_FACTS_ARCHIVE_ROOT}/{self.archive_stem}.md",
            "current_conclusion": _json_clone(conclusion if isinstance(conclusion, dict) else {}),
            "freshness": _json_clone(freshness if isinstance(freshness, dict) else {}),
            "authority": "observation_only",
        }


@dataclass(frozen=True)
class CurrentFactsPreview:
    """Opaque, process-local preview for one explicit archive write."""

    preview_id: str
    expires_at: str
    artifact: CurrentFactsArtifact

    def descriptor(self) -> dict[str, Any]:
        return {
            "preview_id": self.preview_id,
            "expires_at": self.expires_at,
            **self.artifact.descriptor(),
        }


@dataclass(frozen=True)
class _StoredPreview:
    preview: CurrentFactsPreview
    project_root: str
    expires_at: datetime


class CurrentFactsPreviewStore:
    """Bounded process-local previews for explicit runtime-archive writes."""

    def __init__(
        self,
        *,
        ttl_seconds: int = CURRENT_FACTS_PREVIEW_TTL_SECONDS,
        max_items: int = CURRENT_FACTS_PREVIEW_MAX_ITEMS,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self._ttl_seconds = max(1, int(ttl_seconds))
        self._max_items = max(1, int(max_items))
        self._now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self._items: dict[str, _StoredPreview] = {}
        self._lock = threading.RLock()

    def put(self, *, project_root: str, artifact: CurrentFactsArtifact) -> CurrentFactsPreview:
        now = self._now()
        expires_at = now + timedelta(seconds=self._ttl_seconds)
        preview = CurrentFactsPreview(
            preview_id=secrets.token_urlsafe(24),
            expires_at=expires_at.isoformat(),
            artifact=artifact,
        )
        stored = _StoredPreview(
            preview=preview,
            project_root=_normalized_project_root(project_root),
            expires_at=expires_at,
        )
        with self._lock:
            self._purge_expired_locked(now)
            self._items[preview.preview_id] = stored
            self._trim_locked()
        return preview

    def get(self, *, preview_id: str, project_root: str) -> CurrentFactsPreview | None:
        if not isinstance(preview_id, str) or not preview_id.strip():
            return None
        normalized_root = _normalized_project_root(project_root)
        now = self._now()
        with self._lock:
            self._purge_expired_locked(now)
            stored = self._items.get(preview_id.strip())
            if stored is None or stored.project_root != normalized_root:
                return None
            return stored.preview

    def _now(self) -> datetime:
        now = self._now_fn()
        if now.tzinfo is None:
            return now.replace(tzinfo=timezone.utc)
        return now.astimezone(timezone.utc)

    def _purge_expired_locked(self, now: datetime) -> None:
        for preview_id in [
            item_id
            for item_id, stored in self._items.items()
            if stored.expires_at <= now
        ]:
            self._items.pop(preview_id, None)

    def _trim_locked(self) -> None:
        overflow = len(self._items) - self._max_items
        if overflow <= 0:
            return
        oldest = sorted(
            self._items.values(),
            key=lambda stored: stored.preview.expires_at,
        )[:overflow]
        for stored in oldest:
            self._items.pop(stored.preview.preview_id, None)


_PROCESS_PREVIEW_STORE = CurrentFactsPreviewStore()


def process_current_facts_preview_store() -> CurrentFactsPreviewStore:
    """Return the bounded store shared by routed servers in one MCP process."""

    return _PROCESS_PREVIEW_STORE


def build_current_facts_artifact(canonical_state: dict[str, Any]) -> CurrentFactsArtifact:
    """Render a redacted JSON/Markdown pair from one canonical state object."""

    if not isinstance(canonical_state, dict):
        raise CurrentFactsArtifactError(
            "CURRENT_FACTS_CANONICAL_STATE_REQUIRED",
            "current-facts artifact 需要 canonical_project_state 对象。",
        )
    _reject_sensitive_keys(canonical_state)
    observed_at = _required_text(canonical_state.get("observed_at"), "observed_at")
    canonical_state_sha256 = _sha256_json(canonical_state)
    canonical_state_semantic_sha256 = _sha256_json(_canonical_semantic_identity(canonical_state))
    public_state = _public_current_facts_projection(canonical_state)
    payload = {
        "schema_version": CURRENT_FACTS_ARTIFACT_SCHEMA_VERSION,
        "document_type": "current_facts_snapshot",
        "observed_at": observed_at,
        "canonical_state_sha256": canonical_state_sha256,
        "canonical_state_semantic_sha256": canonical_state_semantic_sha256,
        "current_facts": public_state,
        "authority_boundary": {
            "snapshot_is_observation_only": True,
            "does_not_authorize": [
                "executor_run",
                "validation_run",
                "commit",
                "push",
                "stable_replacement",
                "delivery_acceptance",
            ],
            "historical_verification_is_not_current_observation": True,
        },
    }
    json_text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    snapshot_json_sha256 = _sha256_text(json_text)
    markdown_text = _render_markdown(payload, snapshot_json_sha256)
    snapshot_markdown_sha256 = _sha256_text(markdown_text)
    return CurrentFactsArtifact(
        payload=payload,
        json_text=json_text,
        markdown_text=markdown_text,
        canonical_state_sha256=canonical_state_sha256,
        canonical_state_semantic_sha256=canonical_state_semantic_sha256,
        snapshot_json_sha256=snapshot_json_sha256,
        snapshot_markdown_sha256=snapshot_markdown_sha256,
        archive_stem=_archive_stem(observed_at, canonical_state_sha256),
    )


def write_current_facts_archive(
    project_root: str,
    artifact: CurrentFactsArtifact,
) -> dict[str, Any]:
    """Write the exact rendered pair below the fixed ignored runtime root.

    The writer never accepts a caller-selected path, never overwrites a
    different artifact, and only reports repository-relative names.
    """

    archive_dir = _ensure_archive_directory(project_root, artifact.archive_stem)
    json_path = archive_dir / f"{artifact.archive_stem}.json"
    markdown_path = archive_dir / f"{artifact.archive_stem}.md"
    json_bytes = artifact.json_text.encode("utf-8")
    markdown_bytes = artifact.markdown_text.encode("utf-8")
    json_exists = json_path.exists()
    markdown_exists = markdown_path.exists()

    if json_exists or markdown_exists:
        if not (json_exists and markdown_exists):
            raise CurrentFactsArtifactError(
                "CURRENT_FACTS_ARCHIVE_CONFLICT",
                "current-facts archive 存在不完整同名快照，已停止覆盖。",
            )
        if _read_regular_bytes(json_path) != json_bytes or _read_regular_bytes(markdown_path) != markdown_bytes:
            raise CurrentFactsArtifactError(
                "CURRENT_FACTS_ARCHIVE_CONFLICT",
                "current-facts archive 已存在不同内容的同名快照，已停止覆盖。",
            )
        status = "already_present"
    else:
        created: list[Path] = []
        try:
            _write_new_file(json_path, json_bytes)
            created.append(json_path)
            _write_new_file(markdown_path, markdown_bytes)
            created.append(markdown_path)
        except (FileExistsError, OSError) as exc:
            for path in reversed(created):
                try:
                    path.unlink()
                except OSError:
                    pass
            raise CurrentFactsArtifactError(
                "CURRENT_FACTS_ARCHIVE_WRITE_FAILED",
                "current-facts archive 写入失败，未覆盖已有快照。",
            ) from exc
        status = "written"

    return {
        "status": status,
        "archive_root": CURRENT_FACTS_ARCHIVE_ROOT,
        "files": [
            {
                "path": f"{CURRENT_FACTS_ARCHIVE_ROOT}/{json_path.name}",
                "sha256": artifact.snapshot_json_sha256,
                "bytes": len(json_bytes),
            },
            {
                "path": f"{CURRENT_FACTS_ARCHIVE_ROOT}/{markdown_path.name}",
                "sha256": artifact.snapshot_markdown_sha256,
                "bytes": len(markdown_bytes),
            },
        ],
        "canonical_state_sha256": artifact.canonical_state_sha256,
        "canonical_state_semantic_sha256": artifact.canonical_state_semantic_sha256,
        "snapshot_json_sha256": artifact.snapshot_json_sha256,
        "snapshot_markdown_sha256": artifact.snapshot_markdown_sha256,
        "authority": "observation_only",
    }


def _public_current_facts_projection(canonical_state: dict[str, Any]) -> dict[str, Any]:
    current = _mapping(canonical_state.get("currently_observed"))
    return {
        "canonical_state_schema_version": _optional_text(canonical_state.get("schema_version")),
        "observed_at": _optional_text(canonical_state.get("observed_at")),
        "context_binding": _context_binding_projection(canonical_state.get("context_binding")),
        "historically_verified": {
            "latest_execution_report": _pick(
                _mapping(_mapping(canonical_state.get("historically_verified")).get("latest_execution_report")),
                ("status", "verified_at", "report_status", "version"),
            ),
        },
        "currently_observed": {
            "git": _pick(
                _mapping(current.get("git")),
                (
                    "status",
                    "branch",
                    "head",
                    "raw_working_tree",
                    "delivery_working_tree",
                    "ignored_runtime_file_count",
                    "reconciliation",
                ),
            ),
            "runner": _pick(
                _mapping(current.get("runner")),
                (
                    "status",
                    "mode",
                    "runner_status",
                    "current_version",
                    "current_version_status",
                    "next_version",
                    "pending_count",
                    "has_pending_versions",
                    "unreconciled_direct_version_count",
                ),
            ),
            "executor": _pick(
                _mapping(current.get("executor")),
                (
                    "status",
                    "has_session",
                    "continuation_available",
                    "risk_level",
                    "manual_confirmation_required",
                ),
            ),
            "runtime": _pick(
                _mapping(current.get("runtime")),
                ("status", "observed_at", "reason_code"),
            ),
            "connector": _pick(
                _mapping(current.get("connector")),
                ("status", "observed_at", "reason_code"),
            ),
        },
        "freshness": _pick(
            _mapping(canonical_state.get("freshness")),
            ("current_observation", "observed_at", "unobserved_sources", "partial_error_count"),
        ),
        "current_conclusion": _current_conclusion_projection(canonical_state.get("current_conclusion")),
        "warnings": _text_list(canonical_state.get("warnings")),
    }


def _context_binding_projection(value: Any) -> dict[str, Any]:
    binding = _mapping(value)
    result = _pick(binding, ("project_name", "branch", "head", "current_version"))
    runner_plan = _mapping(binding.get("runner_plan"))
    if runner_plan:
        result["runner_plan"] = _pick(runner_plan, ("mode", "plan_sha256"))
    return result


def _current_conclusion_projection(value: Any) -> dict[str, Any]:
    conclusion = _mapping(value)
    result = _pick(conclusion, ("status", "scope", "reasons", "authorization"))
    for key in ("project_checkout", "runtime_and_connector"):
        nested = _mapping(conclusion.get(key))
        if nested:
            result[key] = _pick(nested, ("status", "scope", "reasons"))
    return result


def _render_markdown(payload: dict[str, Any], snapshot_json_sha256: str) -> str:
    current = _mapping(payload.get("current_facts"))
    conclusion = _mapping(current.get("current_conclusion"))
    freshness = _mapping(current.get("freshness"))
    observed = _mapping(current.get("currently_observed"))
    historical = _mapping(current.get("historically_verified"))
    lines = [
        "# Current Facts Snapshot",
        "",
        f"- Schema: `{CURRENT_FACTS_ARTIFACT_SCHEMA_VERSION}`",
        f"- Observed at: `{payload.get('observed_at')}`",
        f"- Canonical state SHA-256: `{payload.get('canonical_state_sha256')}`",
        f"- Snapshot JSON SHA-256: `{snapshot_json_sha256}`",
        "- Authority: observation only; this snapshot grants no execution, validation, Git, stable-replacement, or delivery authority.",
        "",
        "## Current conclusion",
        "",
        f"- Status: `{conclusion.get('status')}`",
        f"- Scope: `{conclusion.get('scope')}`",
        f"- Reasons: `{', '.join(_text_list(conclusion.get('reasons'))) or 'none'}`",
        "",
        "## Freshness",
        "",
        f"- Current observation: `{freshness.get('current_observation')}`",
        f"- Unobserved sources: `{', '.join(_text_list(freshness.get('unobserved_sources'))) or 'none'}`",
        f"- Partial error count: `{freshness.get('partial_error_count')}`",
        "",
        "## Source observations",
        "",
        "| Source | Status | Observed at | Reason |",
        "| --- | --- | --- | --- |",
    ]
    for source in ("git", "runner", "executor", "runtime", "connector"):
        item = _mapping(observed.get(source))
        lines.append(
            "| "
            + source
            + " | "
            + _markdown_value(item.get("status"))
            + " | "
            + _markdown_value(item.get("observed_at"))
            + " | "
            + _markdown_value(item.get("reason_code"))
            + " |"
        )
    latest = _mapping(historical.get("latest_execution_report"))
    lines.extend(
        [
            "",
            "## Historical verification",
            "",
            f"- Latest execution report status: `{latest.get('status')}`",
            f"- Verified at: `{latest.get('verified_at')}`",
            f"- Version: `{latest.get('version')}`",
            "",
            "## Warnings",
            "",
        ]
    )
    warnings = _text_list(current.get("warnings"))
    if warnings:
        lines.extend(f"- `{warning}`" for warning in warnings)
    else:
        lines.append("- none")
    return "\n".join(lines) + "\n"


def _archive_stem(observed_at: str, canonical_state_sha256: str) -> str:
    timestamp = re.sub(r"[^0-9A-Za-z]+", "-", observed_at).strip("-") or "unknown-time"
    return f"current-facts-{timestamp}-{canonical_state_sha256[:16]}"


def _ensure_archive_directory(project_root: str, archive_stem: str) -> Path:
    root = Path(_normalized_project_root(project_root))
    if not root.is_dir():
        raise CurrentFactsArtifactError(
            "CURRENT_FACTS_PROJECT_ROOT_UNAVAILABLE",
            "current-facts archive 的项目根目录不可用。",
        )
    _require_ignored_archive_targets(root, archive_stem)
    current = root
    for part in (".colameta", "reports", "current-facts"):
        current = current / part
        if current.exists() and current.is_symlink():
            raise CurrentFactsArtifactError(
                "CURRENT_FACTS_ARCHIVE_PATH_UNSAFE",
                "current-facts archive 路径不能经过符号链接。",
            )
        current.mkdir(mode=0o700, exist_ok=True)
    try:
        current.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise CurrentFactsArtifactError(
            "CURRENT_FACTS_ARCHIVE_PATH_UNSAFE",
            "current-facts archive 必须位于项目的固定 runtime 目录。",
        ) from exc
    return current


def _require_ignored_archive_targets(project_root: Path, archive_stem: str) -> None:
    targets = [
        f"{CURRENT_FACTS_ARCHIVE_ROOT}/{archive_stem}.json",
        f"{CURRENT_FACTS_ARCHIVE_ROOT}/{archive_stem}.md",
    ]
    for target in targets:
        try:
            checked = subprocess.run(
                ["git", "-C", str(project_root), "check-ignore", "--quiet", "--no-index", target],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=2,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise CurrentFactsArtifactError(
                "CURRENT_FACTS_ARCHIVE_NOT_IGNORED",
                "current-facts archive 需要已验证的 Git ignore 规则；未写入。",
            ) from exc
        if checked.returncode != 0:
            raise CurrentFactsArtifactError(
                "CURRENT_FACTS_ARCHIVE_NOT_IGNORED",
                "current-facts archive 未被 Git ignore 规则覆盖；未写入以避免创建待提交文档。",
            )


def _read_regular_bytes(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise CurrentFactsArtifactError(
            "CURRENT_FACTS_ARCHIVE_PATH_UNSAFE",
            "current-facts archive 目标不是普通文件。",
        )
    try:
        return path.read_bytes()
    except OSError as exc:
        raise CurrentFactsArtifactError(
            "CURRENT_FACTS_ARCHIVE_WRITE_FAILED",
            "current-facts archive 无法读取已有快照以进行安全复核。",
        ) from exc


def _write_new_file(path: Path, content: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            os.unlink(path)
        except OSError:
            pass
        raise


def _reject_sensitive_keys(value: Any, *, path: tuple[str, ...] = ()) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key).strip().lower().replace("-", "_")
            if any(part in normalized for part in _SENSITIVE_KEY_PARTS):
                label = ".".join((*path, str(key))) or str(key)
                raise CurrentFactsArtifactError(
                    "CURRENT_FACTS_REDACTION_REQUIRED",
                    f"canonical state 包含不能进入 current-facts artifact 的敏感或路径字段：{label}。",
                )
            _reject_sensitive_keys(nested, path=(*path, str(key)))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_sensitive_keys(nested, path=(*path, str(index)))


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _pick(value: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {
        key: _json_clone(value[key])
        for key in keys
        if key in value
    }


def _text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _optional_text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _required_text(value: Any, field: str) -> str:
    text = _optional_text(value)
    if text is None:
        raise CurrentFactsArtifactError(
            "CURRENT_FACTS_CANONICAL_STATE_REQUIRED",
            f"canonical_project_state.{field} 必须是非空文本。",
        )
    return text


def _json_clone(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True))
    except (TypeError, ValueError) as exc:
        raise CurrentFactsArtifactError(
            "CURRENT_FACTS_CANONICAL_STATE_REQUIRED",
            "canonical_project_state 必须只包含 JSON 值。",
        ) from exc


def _sha256_json(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _canonical_semantic_identity(value: Any) -> Any:
    """Drop collection timestamps before comparing preview freshness snapshots.

    A new read necessarily has a new collection time.  That alone must not
    make an otherwise unchanged preview impossible to apply; changed source
    state, freshness status, reasons, or authority data still changes the
    semantic digest and fails closed.
    """

    if isinstance(value, dict):
        return {
            str(key): _canonical_semantic_identity(nested)
            for key, nested in value.items()
            if str(key) not in {"observed_at", "last_observed_at"}
        }
    if isinstance(value, list):
        return [_canonical_semantic_identity(item) for item in value]
    return value


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _markdown_value(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("|", "\\|").replace("\n", " ")


def _normalized_project_root(project_root: str) -> str:
    return os.path.realpath(os.path.abspath(os.path.expanduser(project_root)))
