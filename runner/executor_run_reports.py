import json
import os
import re
import hashlib
import tempfile
import uuid
from datetime import datetime, timezone
from typing import Any

from runner._internal_utils import now_iso as _now_iso, run_git as _run_git_base
from runner.sensitive_redaction import redact_sensitive_text
from runner.runner_paths import primary_project_runner_relpath, resolve_project_runner_dir

REPORTS_SUBDIR = primary_project_runner_relpath("reports", "executor-runs")
AUDITS_SUBDIR = primary_project_runner_relpath("audits", "executor-runs")
VERSION_AUDITS_SUBDIR = primary_project_runner_relpath("audits", "versions")
SCHEMA_VERSION = "1.0"
AUDIT_SCHEMA_VERSION = "1.0"
VERSION_AUDIT_SCHEMA_VERSION = "1.0"
MAX_MARKDOWN_CHARS = 30000
MAX_COMMIT_MESSAGE_CHARS = 300
MAX_COMMITTED_FILES = 200
REPORT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")
VERSION_SAFE_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")
MAX_REPORT_ID_RETRIES = 5

def _redact_sensitive(text: str) -> str:
    return redact_sensitive_text(text, replacement_token="<redacted>", preserve_token_prefix=False)


def _bounded_markdown(text: str, max_chars: int = MAX_MARKDOWN_CHARS) -> tuple[str, bool]:
    redacted = _redact_sensitive(text or "")
    if len(redacted) <= max_chars:
        return redacted, False
    return redacted[:max_chars], True


def _full_redacted_markdown(text: str) -> str:
    return _redact_sensitive(text or "")


def _safe_version(version: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", version)


def _validate_version(version: str) -> None:
    if not isinstance(version, str) or not version.strip():
        raise ValueError("version must be a non-empty string")
    if not VERSION_SAFE_PATTERN.match(version):
        raise ValueError(f"version contains unsafe characters: {version!r}")
    if ".." in version:
        raise ValueError("version must not contain '..'")


def _validate_report_id(report_id: str) -> None:
    if not isinstance(report_id, str) or not report_id.strip():
        raise ValueError("report_id must be a non-empty string")
    if not REPORT_ID_PATTERN.fullmatch(report_id):
        raise ValueError(f"report_id contains unsafe characters: {report_id!r}")
    if ".." in report_id:
        raise ValueError("report_id must not contain '..'")
    if "/" in report_id or "\\" in report_id:
        raise ValueError("report_id must not contain path separators")
    if any(ord(c) < 0x20 or c == "\x7f" for c in report_id):
        raise ValueError("report_id must not contain control characters")


class ExecutorRunReportStore:
    def __init__(self, project_root: str, *, target: Any | None = None):
        self.project_root = os.path.abspath(os.path.expanduser(project_root))
        target_runner_dir = getattr(target, "runner_dir", None)
        if isinstance(target_runner_dir, str) and target_runner_dir.strip():
            self.runner_dir = os.path.abspath(os.path.expanduser(target_runner_dir))
        else:
            self.runner_dir = resolve_project_runner_dir(self.project_root)
        self.reports_root = os.path.join(self.runner_dir, "reports", "executor-runs")
        self.audits_root = os.path.join(self.runner_dir, "audits", "executor-runs")
        self.version_audits_root = os.path.join(self.runner_dir, "audits", "versions")

    def _is_under_reports_root(self, path: str) -> bool:
        root = os.path.realpath(self.reports_root)
        target = os.path.realpath(path)
        return target == root or target.startswith(root + os.sep)

    def _is_under_audits_root(self, path: str) -> bool:
        root = os.path.realpath(self.audits_root)
        target = os.path.realpath(path)
        return target == root or target.startswith(root + os.sep)

    def _is_under_version_audits_root(self, path: str) -> bool:
        root = os.path.realpath(self.version_audits_root)
        target = os.path.realpath(path)
        return target == root or target.startswith(root + os.sep)

    def record_report(
        self,
        *,
        version: str,
        version_name: str | None = None,
        provider: str,
        execution_mode: str,
        status: str,
        started_at: str | None = None,
        finished_at: str | None = None,
        commit_head_before: str | None = None,
        commit_head_after: str | None = None,
        changed_files: list[str] | None = None,
        log_file: str | None = None,
        audit_file: str | None = None,
        summary_changed_files: list[str] | None = None,
        summary_validation_results: list[str] | None = None,
        summary_risk_followups: list[str] | None = None,
        executor_report_text: str | None = None,
        execution_lineage: dict[str, Any] | None = None,
        completion_evidence: dict[str, Any] | None = None,
        token_usage: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        _validate_version(version)
        now = finished_at or _now_iso()
        version_dir = os.path.join(self.reports_root, _safe_version(version))

        full_report_md = _full_redacted_markdown(executor_report_text or "")
        report_md, truncated = _bounded_markdown(executor_report_text or "")
        has_executor_report = bool(full_report_md.strip())
        full_report_length = len(full_report_md)

        changed_files_list = sorted(set(str(f) for f in (changed_files or [])))

        try:
            os.makedirs(version_dir, exist_ok=True)
            for _ in range(MAX_REPORT_ID_RETRIES):
                report_id = self._generate_report_id(provider)
                _validate_report_id(report_id)
                json_file = os.path.join(version_dir, f"{report_id}.json")
                md_file = os.path.join(version_dir, f"{report_id}.md")
                report = {
                    "schema_version": SCHEMA_VERSION,
                    "project_root": self.project_root,
                    "version": version,
                    "version_name": version_name or "",
                    "provider": provider,
                    "execution_mode": execution_mode,
                    "status": status,
                    "started_at": started_at or now,
                    "finished_at": now,
                    "report_id": report_id,
                    "json_file": json_file,
                    "markdown_file": md_file,
                    "commit_head_before": commit_head_before or "",
                    "commit_head_after": commit_head_after or "",
                    "changed_files": changed_files_list,
                    "log_file": log_file or "",
                    "audit_file": audit_file or "",
                    "summary": {
                        "changed_files": sorted(set(str(f) for f in (summary_changed_files or []))),
                        "validation_results": [str(r) for r in (summary_validation_results or [])],
                        "risk_and_followups": [str(r) for r in (summary_risk_followups or [])],
                        "executor_report_available": has_executor_report,
                        "executor_report_full_length": full_report_length,
                        "executor_report_preview_length": len(report_md),
                        "executor_report_preview_truncated": truncated,
                    },
                    "execution_lineage": dict(execution_lineage or {}),
                    "completion_evidence": dict(completion_evidence or {}),
                    "token_usage": dict(token_usage) if isinstance(token_usage, dict) else None,
                    "report_markdown": report_md,
                    "report_markdown_full_length": full_report_length,
                    "report_markdown_full_available": has_executor_report,
                    "truncated": truncated,
                }
                if os.path.exists(json_file) or os.path.exists(md_file):
                    continue
                try:
                    self._write_json(json_file, report)
                    self._write_markdown(md_file, report, full_report_md)
                except FileExistsError:
                    try:
                        if os.path.isfile(json_file):
                            os.unlink(json_file)
                    except Exception:
                        pass
                    continue
                self._write_latest_pointer(self.reports_root, version, report_id, json_file, md_file)
                self._write_latest_pointer(version_dir, version, report_id, json_file, md_file)
                audit_package_result = {
                    "ok": False,
                    "status": "failed",
                    "error_code": "AUDIT_PACKAGE_WRITE_FAILED",
                    "message": "写入 executor audit package 失败。",
                }
                try:
                    audit_package_result = self._materialize_executor_run_audit_package(report)
                except Exception:
                    audit_package_result = {
                        "ok": False,
                        "status": "failed",
                        "error_code": "AUDIT_PACKAGE_WRITE_FAILED",
                        "message": "写入 executor audit package 失败。",
                    }
                version_audit_package_result = {
                    "ok": False,
                    "status": "failed",
                    "error_code": "VERSION_AUDIT_PACKAGE_WRITE_FAILED",
                    "message": "写入 version audit package 失败。",
                }
                try:
                    version_audit_package_result = self._materialize_version_audit_package(
                        report,
                        audit_package_result=audit_package_result,
                    )
                except Exception:
                    version_audit_package_result = {
                        "ok": False,
                        "status": "failed",
                        "error_code": "VERSION_AUDIT_PACKAGE_WRITE_FAILED",
                        "message": "写入 version audit package 失败。",
                    }
                return {
                    "ok": True,
                    "report_id": report_id,
                    "json_file": json_file,
                    "markdown_file": md_file,
                    "audit_package": audit_package_result,
                    "version_audit_package": version_audit_package_result,
                }
            return {"ok": False, "error_code": "REPORT_ID_CONFLICT", "message": "report_id 冲突，写入失败。"}
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning(
                f"Failed to write executor run report: {exc}"
            )
            return {"ok": False, "error_code": "REPORT_WRITE_FAILED", "message": "写入 executor report 失败。"}

    def list_reports(self, version: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 50))
        reports: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        reports_root = self.reports_root

        if not os.path.isdir(reports_root):
            return []

        if version:
            _validate_version(version)
            version_dir = os.path.join(reports_root, _safe_version(version))
            if not os.path.isdir(version_dir):
                return reports
            dirs_to_scan = [version_dir]
        else:
            dirs_to_scan = sorted(
                d.path for d in os.scandir(reports_root) if d.is_dir()
            )

        for version_dir in dirs_to_scan:
            try:
                entries = sorted(
                    (
                        e
                        for e in os.scandir(version_dir)
                        if e.name.endswith(".json") and e.is_file() and e.name != "latest.json"
                    ),
                    key=lambda e: e.name,
                    reverse=True,
                )
            except OSError:
                continue
            for entry in entries:
                try:
                    report = self._load_json(entry.path)
                    if not isinstance(report, dict):
                        continue
                    list_entry = self._list_entry(report)
                    sort_key = self._report_sort_key(report, entry.path)
                    reports.append((sort_key, list_entry))
                except Exception:
                    continue

        reports.sort(key=lambda item: item[0], reverse=True)
        return [entry for _, entry in reports[:limit]]

    def get_report(
        self,
        version: str | None = None,
        report_id: str | None = None,
        latest: bool = True,
        include_markdown: bool = True,
        max_markdown_chars: int = MAX_MARKDOWN_CHARS,
    ) -> dict[str, Any]:
        max_md = max(1, min(max_markdown_chars, 60000))

        target_path: str | None = None
        if report_id:
            _validate_report_id(report_id)
            if version:
                _validate_version(version)
                version_dir = os.path.join(self.reports_root, _safe_version(version))
                candidate = os.path.join(version_dir, f"{report_id}.json")
                if os.path.isfile(candidate) and self._is_under_reports_root(candidate):
                    target_path = candidate
            if target_path is None:
                target_path = self._find_report_by_id(report_id)

        if target_path is None and latest:
            latest_entries = self.list_reports(version=version, limit=1)
            if latest_entries:
                candidate = str(latest_entries[0].get("json_file", "") or "")
                if candidate and os.path.isfile(candidate) and self._is_under_reports_root(candidate):
                    target_path = os.path.realpath(candidate)
            if target_path is None:
                pointer_dir = self.reports_root
                if version:
                    pointer_dir = os.path.join(self.reports_root, _safe_version(version))
                target_path = self._read_latest_pointer(pointer_dir)

        if target_path is None:
            return {
                "ok": False,
                "error_code": "REPORT_NOT_FOUND",
                "message": "No executor run report found.",
            }

        return self._load_report_file(target_path, include_markdown=include_markdown, max_md=max_md)

    def get_materialized_audit_package(self, report_id: str) -> dict[str, Any]:
        _validate_report_id(report_id)
        audit_path = self._audit_package_json_path(report_id)
        if not os.path.isfile(audit_path):
            return {
                "ok": False,
                "error_code": "AUDIT_PACKAGE_NOT_FOUND",
                "message": "Audit package not found.",
            }
        if not self._is_under_audits_root(audit_path):
            return {
                "ok": False,
                "error_code": "ACCESS_DENIED",
                "message": "Audit package path is outside audits directory.",
            }
        data = self._load_json(audit_path)
        if not isinstance(data, dict):
            return {
                "ok": False,
                "error_code": "AUDIT_PACKAGE_LOAD_ERROR",
                "message": "Failed to parse audit package.",
            }
        return {"ok": True, "audit_package": data, "json_file": audit_path}

    def get_materialized_version_audit_package(self, version: str) -> dict[str, Any]:
        _validate_version(version)
        audit_path = self._version_audit_json_path(version)
        if not os.path.isfile(audit_path):
            return {
                "ok": False,
                "error_code": "AUDIT_PACKAGE_NOT_FOUND",
                "message": "Version audit package not found.",
            }
        if not self._is_under_version_audits_root(audit_path):
            return {
                "ok": False,
                "error_code": "ACCESS_DENIED",
                "message": "Version audit package path is outside audits directory.",
            }
        data = self._load_json(audit_path)
        if not isinstance(data, dict):
            return {
                "ok": False,
                "error_code": "AUDIT_PACKAGE_LOAD_ERROR",
                "message": "Failed to parse version audit package.",
            }
        return {"ok": True, "audit_package": data, "json_file": audit_path}

    def list_version_audit_packages(self, version: str) -> dict[str, Any]:
        _validate_version(version)
        base_file = self._version_audit_json_path(version)
        refresh_files = self._scan_version_refresh_files(version)
        latest_file = ""
        latest_source_kind = ""
        if refresh_files:
            latest_file = refresh_files[-1]
            latest_source_kind = "version_refresh"
        elif os.path.isfile(base_file):
            latest_file = base_file
            latest_source_kind = "version_materialized"
        return {
            "ok": True,
            "version": version,
            "base_package_file": base_file if os.path.isfile(base_file) else "",
            "refresh_package_files": refresh_files,
            "latest_package_file": latest_file,
            "latest_source_kind": latest_source_kind,
        }

    def get_latest_materialized_version_audit_package(self, version: str) -> dict[str, Any]:
        listing = self.list_version_audit_packages(version)
        latest_file = str(listing.get("latest_package_file", "") or "")
        if not latest_file:
            return {
                "ok": False,
                "error_code": "AUDIT_PACKAGE_NOT_FOUND",
                "message": "Version audit package not found.",
            }
        if not self._is_under_version_audits_root(latest_file):
            return {
                "ok": False,
                "error_code": "ACCESS_DENIED",
                "message": "Version audit package path is outside audits directory.",
            }
        data = self._load_json(latest_file)
        if not isinstance(data, dict):
            return {
                "ok": False,
                "error_code": "AUDIT_PACKAGE_LOAD_ERROR",
                "message": "Failed to parse version audit package.",
            }
        return {
            "ok": True,
            "audit_package": data,
            "json_file": latest_file,
            "source": str(listing.get("latest_source_kind", "") or ""),
            "base_package_file": str(listing.get("base_package_file", "") or ""),
            "refresh_package_files": self._str_list_any(listing.get("refresh_package_files")),
        }

    def refresh_version_audit_package(self, *, version: str, reason: str = "") -> dict[str, Any]:
        _validate_version(version)
        os.makedirs(self.version_audits_root, exist_ok=True)
        listing = self.list_version_audit_packages(version)
        snapshot = self._collect_version_audit_snapshot(version=version, preferred_report=None)
        if not snapshot.get("ok"):
            return {
                "ok": False,
                "error_code": str(snapshot.get("error_code") or "REPORT_NOT_FOUND"),
                "message": str(snapshot.get("message") or "未找到该版本 report。"),
            }
        refresh_id = self._generate_refresh_revision_id()
        refresh_file = self._version_refresh_audit_json_path(version, refresh_id)
        package = self._build_version_audit_package(
            snapshot=snapshot,
            package_role="refresh_revision",
            target_file=refresh_file,
            base_audit_package_file=str(listing.get("base_package_file", "") or ""),
            previous_refresh_files=self._str_list_any(listing.get("refresh_package_files"))[-50:],
            reason=reason,
        )
        try:
            self._write_json(refresh_file, package)
            return {
                "ok": True,
                "status": "created",
                "audit_package_id": package.get("audit_package_id", ""),
                "json_file": refresh_file,
                "source": "version_refresh",
            }
        except FileExistsError:
            return {
                "ok": False,
                "status": "failed",
                "error_code": "VERSION_AUDIT_REFRESH_CONFLICT",
                "message": "version audit refresh 文件冲突。",
            }
        except Exception:
            return {
                "ok": False,
                "status": "failed",
                "error_code": "VERSION_AUDIT_REFRESH_FAILED",
                "message": "写入 version audit refresh 失败。",
            }

    def _find_report_by_id(self, report_id: str) -> str | None:
        if not os.path.isdir(self.reports_root):
            return None
        for dpath, _, fnames in os.walk(self.reports_root):
            for fname in fnames:
                if fname == f"{report_id}.json":
                    candidate = os.path.join(dpath, fname)
                    if self._is_under_reports_root(candidate):
                        return candidate
        return None

    def _list_entry(self, report: dict[str, Any]) -> dict[str, Any]:
        lineage = report.get("execution_lineage")
        if isinstance(lineage, dict):
            executor_model = str(lineage.get("model") or "")
        else:
            executor_model = ""
        raw_token_usage = report.get("token_usage")
        return {
            "version": str(report.get("version", "")),
            "provider": str(report.get("provider", "")),
            "status": str(report.get("status", "")),
            "finished_at": str(report.get("finished_at", "")),
            "report_id": str(report.get("report_id", "")),
            "json_file": str(report.get("json_file", "")),
            "markdown_file": str(report.get("markdown_file", "")),
            "executor_model": executor_model,
            "token_usage": dict(raw_token_usage) if isinstance(raw_token_usage, dict) else None,
        }

    def _load_report_file(self, path: str, *, include_markdown: bool, max_md: int) -> dict[str, Any]:
        if not self._is_under_reports_root(path):
            return {"ok": False, "error_code": "ACCESS_DENIED", "message": "Report path is outside reports directory."}
        report = self._load_json(path)
        if not isinstance(report, dict):
            return {"ok": False, "error_code": "REPORT_LOAD_ERROR", "message": "Failed to parse report file."}
        result = {"ok": True, "report": {}}
        report_copy = dict(report)
        report_md = report_copy.pop("report_markdown", "")
        result["report"] = report_copy
        if include_markdown:
            md_text = str(report_md) if isinstance(report_md, str) else ""
            redacted = _redact_sensitive(md_text)
            if len(redacted) > max_md:
                redacted = redacted[:max_md]
                result["truncated"] = True
            else:
                result["truncated"] = bool(report.get("truncated", False))
            result["report_markdown"] = redacted
        return result

    def _write_json(self, path: str, data: dict[str, Any]) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        self._write_text_no_overwrite(path, payload)

    def _write_text_no_overwrite(self, path: str, content: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(content)
        except FileExistsError:
            raise
        except Exception:
            try:
                if os.path.isfile(path):
                    os.unlink(path)
            except Exception:
                pass
            raise

    def _write_markdown(self, path: str, report: dict[str, Any], report_md: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        content = (
            "# Executor Run Report\n\n"
            f"- Version: {report.get('version', '')}\n"
            f"- Version name: {report.get('version_name', '')}\n"
            f"- Provider: {report.get('provider', '')}\n"
            f"- Execution mode: {report.get('execution_mode', '')}\n"
            f"- Status: {report.get('status', '')}\n"
            f"- Started: {report.get('started_at', '')}\n"
            f"- Finished: {report.get('finished_at', '')}\n"
            f"- Duration: {report.get('duration_seconds', '')}\n"
            f"- HEAD before: {report.get('commit_head_before', '')}\n"
            f"- HEAD after: {report.get('commit_head_after', '')}\n"
            f"- Log: {report.get('log_file', '')}\n"
            f"- Audit: {report.get('audit_file', '')}\n"
            f"- Changed files ({len(report.get('changed_files', []))}):\n"
        )
        for cf in report.get("changed_files", []):
            content += f"  - {cf}\n"
        content += "\n## Executor final report\n\n"
        if report_md.strip():
            content += report_md + "\n"
        else:
            content += "No executor final report was captured. See log_file.\n"
        validation = report.get("summary", {}).get("validation_results", [])
        if validation:
            content += "\n## Validation\n\n"
            for val in validation:
                content += f"- {val}\n"
        risks = report.get("summary", {}).get("risk_and_followups", [])
        if risks:
            content += "\n## Risks and follow-ups\n\n"
            for risk in risks:
                content += f"- {risk}\n"
        self._write_text_no_overwrite(path, content)

    def _generate_report_id(self, provider: str) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        provider_token = re.sub(r"[^A-Za-z0-9_.-]", "_", str(provider or "unknown")).strip("._-") or "unknown"
        suffix = uuid.uuid4().hex[:8]
        return f"{ts}-{provider_token}-{suffix}"

    def _audit_package_json_path(self, report_id: str) -> str:
        _validate_report_id(report_id)
        return os.path.join(self.audits_root, f"{report_id}.audit.json")

    def _version_audit_json_path(self, version: str) -> str:
        _validate_version(version)
        return os.path.join(self.version_audits_root, f"{_safe_version(version)}.audit.json")

    def _version_refresh_audit_json_path(self, version: str, refresh_id: str) -> str:
        _validate_version(version)
        if not isinstance(refresh_id, str) or not refresh_id.strip():
            raise ValueError("refresh_id must be a non-empty string")
        rid = refresh_id.strip()
        if not REPORT_ID_PATTERN.fullmatch(rid) or ".." in rid or "/" in rid or "\\" in rid:
            raise ValueError("refresh_id contains unsafe characters")
        return os.path.join(self.version_audits_root, f"{_safe_version(version)}.refresh.{rid}.audit.json")

    def _scan_version_refresh_files(self, version: str) -> list[str]:
        _validate_version(version)
        if not os.path.isdir(self.version_audits_root):
            return []
        safe = _safe_version(version)
        prefix = f"{safe}.refresh."
        suffix = ".audit.json"
        files: list[str] = []
        try:
            for entry in os.scandir(self.version_audits_root):
                if not entry.is_file():
                    continue
                name = entry.name
                if not name.startswith(prefix) or not name.endswith(suffix):
                    continue
                full = os.path.join(self.version_audits_root, name)
                if self._is_under_version_audits_root(full):
                    files.append(full)
        except Exception:
            return []
        files.sort()
        return files

    def _generate_refresh_revision_id(self) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        suffix = uuid.uuid4().hex[:8]
        return f"{ts}-{suffix}"

    def _materialize_executor_run_audit_package(self, report: dict[str, Any]) -> dict[str, Any]:
        report_id = str(report.get("report_id", "") or "").strip()
        _validate_report_id(report_id)
        os.makedirs(self.audits_root, exist_ok=True)
        audit_json_file = self._audit_package_json_path(report_id)
        if os.path.exists(audit_json_file):
            return {
                "ok": True,
                "status": "existing",
                "audit_package_id": f"auditpkg_{report_id}",
                "json_file": audit_json_file,
            }

        execution_lineage = report.get("execution_lineage")
        lineage = execution_lineage if isinstance(execution_lineage, dict) else {}
        summary_obj = report.get("summary")
        summary = summary_obj if isinstance(summary_obj, dict) else {}
        validation_results = [str(x) for x in summary.get("validation_results", []) if isinstance(x, str)]
        changed_files = [str(x) for x in report.get("changed_files", []) if isinstance(x, str)]

        source_report_json_file = str(report.get("json_file", "") or "")
        source_report_markdown_file = str(report.get("markdown_file", "") or "")
        source_report_sha256 = self._sha256_file(source_report_json_file)

        package = {
            "schema_version": AUDIT_SCHEMA_VERSION,
            "audit_package_id": f"auditpkg_{report_id}",
            "package_type": "executor_run",
            "created_at": _now_iso(),
            "report_id": report_id,
            "version": str(report.get("version", "") or ""),
            "version_name": str(report.get("version_name", "") or ""),
            "provider": str(report.get("provider", "") or ""),
            "execution_mode": str(report.get("execution_mode", "") or ""),
            "status": str(report.get("status", "") or ""),
            "started_at": str(report.get("started_at", "") or ""),
            "finished_at": str(report.get("finished_at", "") or ""),
            "run_id": self._safe_short_str(lineage.get("run_id")),
            "preview_id": self._safe_short_str(lineage.get("preview_id")),
            "preview_claimed_at": self._safe_short_str(lineage.get("preview_claimed_at")),
            "preview_claim_status": self._safe_short_str(lineage.get("preview_claim_status")),
            "prompt_file": self._safe_short_str(lineage.get("prompt_file")),
            "prompt_sha256": self._safe_short_str(lineage.get("prompt_sha256")),
            "prompt_sha256_status": self._safe_short_str(lineage.get("prompt_sha256_status")),
            "provider_resume_supported": bool(lineage.get("provider_resume_supported") is True),
            "session_resume_available": bool(lineage.get("session_resume_available") is True),
            "resume_identity_present": bool(lineage.get("resume_identity_present") is True),
            "conversation_identity_present": bool(lineage.get("conversation_identity_present") is True),
            "actual_executor_resume_attempted": bool(lineage.get("actual_executor_resume_attempted") is True),
            "resume_blockers": self._str_list_any(lineage.get("resume_blockers"))[:20],
            "resume_warnings": self._str_list_any(lineage.get("resume_warnings"))[:20],
            "changed_files": changed_files,
            "changed_files_count": len(changed_files),
            "validation_status_summary": self._summarize_validation(validation_results),
            "scope_status_summary": self._summarize_scope(validation_results),
            "validation_sample": validation_results[:5],
            "evidence_paths": {
                "json_file": source_report_json_file,
                "markdown_file": source_report_markdown_file,
                "log_file": str(report.get("log_file", "") or ""),
                "audit_file": str(report.get("audit_file", "") or ""),
            },
            "source_report_sha256": source_report_sha256,
            "source_report_json_file": source_report_json_file,
            "source_report_markdown_file": source_report_markdown_file,
        }
        try:
            self._write_json(audit_json_file, package)
            return {
                "ok": True,
                "status": "created",
                "audit_package_id": package["audit_package_id"],
                "json_file": audit_json_file,
            }
        except FileExistsError:
            return {
                "ok": True,
                "status": "existing",
                "audit_package_id": package["audit_package_id"],
                "json_file": audit_json_file,
            }
        except Exception:
            return {
                "ok": False,
                "status": "failed",
                "error_code": "AUDIT_PACKAGE_WRITE_FAILED",
                "message": "写入 executor audit package 失败。",
            }

    def _materialize_version_audit_package(
        self,
        report: dict[str, Any],
        *,
        audit_package_result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        version = str(report.get("version", "") or "").strip()
        _validate_version(version)
        os.makedirs(self.version_audits_root, exist_ok=True)
        version_audit_json_file = self._version_audit_json_path(version)
        if os.path.exists(version_audit_json_file):
            return {
                "ok": True,
                "status": "existing",
                "audit_package_id": f"version_auditpkg_{_safe_version(version)}",
                "json_file": version_audit_json_file,
            }
        snapshot = self._collect_version_audit_snapshot(version=version, preferred_report=report)
        if not snapshot.get("ok"):
            return {
                "ok": False,
                "status": "failed",
                "error_code": "VERSION_AUDIT_PACKAGE_WRITE_FAILED",
                "message": "写入 version audit package 失败。",
            }
        if isinstance(audit_package_result, dict):
            apid = str(audit_package_result.get("audit_package_id", "") or "")
            afile = str(audit_package_result.get("json_file", "") or "")
            if apid and apid not in snapshot["executor_run_audit_package_ids"]:
                snapshot["executor_run_audit_package_ids"].append(apid)
            if afile and afile not in snapshot["executor_run_audit_package_files"]:
                snapshot["executor_run_audit_package_files"].append(afile)
        package = self._build_version_audit_package(
            snapshot=snapshot,
            package_role="base_frozen",
            target_file=version_audit_json_file,
            base_audit_package_file=version_audit_json_file,
            previous_refresh_files=[],
            reason="",
        )
        try:
            self._write_json(version_audit_json_file, package)
            return {
                "ok": True,
                "status": "created",
                "audit_package_id": package["audit_package_id"],
                "json_file": version_audit_json_file,
            }
        except FileExistsError:
            return {
                "ok": True,
                "status": "existing",
                "audit_package_id": package["audit_package_id"],
                "json_file": version_audit_json_file,
            }
        except Exception:
            return {
                "ok": False,
                "status": "failed",
                "error_code": "VERSION_AUDIT_PACKAGE_WRITE_FAILED",
                "message": "写入 version audit package 失败。",
            }

    def _collect_version_audit_snapshot(
        self,
        *,
        version: str,
        preferred_report: dict[str, Any] | None,
    ) -> dict[str, Any]:
        report_entries = self.list_reports(version=version, limit=50)
        report_ids = [str(entry.get("report_id", "") or "") for entry in report_entries if isinstance(entry, dict) and str(entry.get("report_id", "") or "")]
        preferred_id = ""
        if isinstance(preferred_report, dict):
            preferred_id = str(preferred_report.get("report_id", "") or "").strip()
            if preferred_id:
                try:
                    _validate_report_id(preferred_id)
                    if preferred_id not in report_ids:
                        report_ids.insert(0, preferred_id)
                except ValueError:
                    preferred_id = ""
        if not report_ids:
            return {"ok": False, "error_code": "REPORT_NOT_FOUND", "message": "未找到该版本 report。"}

        report_lookup: dict[str, dict[str, Any]] = {}
        for rid in report_ids:
            try:
                ret = self.get_report(version=version, report_id=rid, latest=False, include_markdown=False)
            except Exception:
                continue
            if isinstance(ret, dict) and ret.get("ok") and isinstance(ret.get("report"), dict):
                report_lookup[rid] = ret["report"]
        if not report_lookup:
            return {"ok": False, "error_code": "REPORT_NOT_FOUND", "message": "未找到可读取 report。"}

        latest_report_id = report_ids[0] if report_ids else next(iter(report_lookup.keys()))
        if latest_report_id not in report_lookup:
            latest_report_id = next(iter(report_lookup.keys()))
        selected_report_id = preferred_id if preferred_id in report_lookup else latest_report_id
        selected_report = report_lookup.get(selected_report_id, report_lookup[latest_report_id])
        selected_summary = selected_report.get("summary") if isinstance(selected_report.get("summary"), dict) else {}
        validation_results = [str(x) for x in selected_summary.get("validation_results", []) if isinstance(x, str)]
        changed_files = [str(x) for x in selected_report.get("changed_files", []) if isinstance(x, str)]
        lineage_raw = selected_report.get("execution_lineage")
        lineage = lineage_raw if isinstance(lineage_raw, dict) else {}
        existing_commit_meta = self._load_existing_version_commit_metadata(version)
        commit_meta = self._resolve_version_commit_metadata(
            version=version,
            selected_report=selected_report,
            changed_files=changed_files,
            existing=existing_commit_meta,
        )

        run_audit_ids: list[str] = []
        run_audit_files: list[str] = []
        for rid in report_ids:
            audit_path = self._audit_package_json_path(rid)
            if not os.path.isfile(audit_path):
                continue
            run_audit_files.append(audit_path)
            audit_data = self._load_json(audit_path)
            if isinstance(audit_data, dict):
                apid = str(audit_data.get("audit_package_id", "") or "")
                if apid and apid not in run_audit_ids:
                    run_audit_ids.append(apid)

        return {
            "ok": True,
            "version": version,
            "version_name": str(selected_report.get("version_name", "") or ""),
            "status": str(selected_report.get("status", "") or ""),
            "prompt_file": self._safe_short_str(lineage.get("prompt_file")),
            "prompt_sha256": self._safe_short_str(lineage.get("prompt_sha256")),
            "prompt_sha256_status": self._safe_short_str(lineage.get("prompt_sha256_status")),
            "provider_resume_supported": bool(lineage.get("provider_resume_supported") is True),
            "session_resume_available": bool(lineage.get("session_resume_available") is True),
            "resume_identity_present": bool(lineage.get("resume_identity_present") is True),
            "conversation_identity_present": bool(lineage.get("conversation_identity_present") is True),
            "resume_blockers": self._str_list_any(lineage.get("resume_blockers"))[:20],
            "resume_warnings": self._str_list_any(lineage.get("resume_warnings"))[:20],
            "latest_report_id": latest_report_id,
            "selected_report_id": selected_report_id,
            "report_ids": report_ids,
            "executor_run_audit_package_ids": run_audit_ids,
            "executor_run_audit_package_files": run_audit_files,
            "changed_files": changed_files,
            "changed_files_count": len(changed_files),
            "validation_status_summary": self._summarize_validation(validation_results),
            "scope_status_summary": self._summarize_scope(validation_results),
            "validation_sample": validation_results[:5],
            "commit_hash": str(commit_meta.get("commit_hash", "") or ""),
            "commit_hash_short": str(commit_meta.get("commit_hash_short", "") or ""),
            "commit_message": str(commit_meta.get("commit_message", "") or ""),
            "committed_files": self._str_list_any(commit_meta.get("committed_files"))[:MAX_COMMITTED_FILES],
            "committed_at": str(commit_meta.get("committed_at", "") or ""),
            "commit_head_before": str(commit_meta.get("commit_head_before", "") or ""),
            "commit_head_after": str(commit_meta.get("commit_head_after", "") or ""),
            "commit_metadata_status": str(commit_meta.get("commit_metadata_status", "unknown") or "unknown"),
            "selected_report_json_file": str(selected_report.get("json_file", "") or ""),
            "selected_report_markdown_file": str(selected_report.get("markdown_file", "") or ""),
            "source_report_ids": report_ids,
            "source_executor_audit_files": run_audit_files,
        }

    def _build_version_audit_package(
        self,
        *,
        snapshot: dict[str, Any],
        package_role: str,
        target_file: str,
        base_audit_package_file: str,
        previous_refresh_files: list[str],
        reason: str,
    ) -> dict[str, Any]:
        version = str(snapshot.get("version", "") or "")
        safe_version = _safe_version(version)
        base_id = f"version_auditpkg_{safe_version}"
        if package_role == "refresh_revision":
            refresh_tag = os.path.basename(target_file).split(".refresh.", 1)[-1].split(".audit.json", 1)[0]
            audit_package_id = f"{base_id}_refresh_{refresh_tag}"
        else:
            audit_package_id = base_id
        return {
            "schema_version": VERSION_AUDIT_SCHEMA_VERSION,
            "audit_package_id": audit_package_id,
            "package_type": "version",
            "package_role": package_role,
            "created_at": _now_iso(),
            "version": version,
            "version_name": str(snapshot.get("version_name", "") or ""),
            "status": str(snapshot.get("status", "") or ""),
            "prompt_file": str(snapshot.get("prompt_file", "") or ""),
            "prompt_sha256": str(snapshot.get("prompt_sha256", "") or ""),
            "prompt_sha256_status": str(snapshot.get("prompt_sha256_status", "") or ""),
            "provider_resume_supported": bool(snapshot.get("provider_resume_supported") is True),
            "session_resume_available": bool(snapshot.get("session_resume_available") is True),
            "resume_identity_present": bool(snapshot.get("resume_identity_present") is True),
            "conversation_identity_present": bool(snapshot.get("conversation_identity_present") is True),
            "resume_blockers": self._str_list_any(snapshot.get("resume_blockers"))[:20],
            "resume_warnings": self._str_list_any(snapshot.get("resume_warnings"))[:20],
            "latest_report_id": str(snapshot.get("latest_report_id", "") or ""),
            "selected_report_id": str(snapshot.get("selected_report_id", "") or ""),
            "report_ids": self._str_list_any(snapshot.get("report_ids")),
            "executor_run_audit_package_ids": self._str_list_any(snapshot.get("executor_run_audit_package_ids")),
            "executor_run_audit_package_files": self._str_list_any(snapshot.get("executor_run_audit_package_files")),
            "changed_files": self._str_list_any(snapshot.get("changed_files")),
            "changed_files_count": int(snapshot.get("changed_files_count", 0) or 0),
            "validation_status_summary": str(snapshot.get("validation_status_summary", "unknown") or "unknown"),
            "scope_status_summary": str(snapshot.get("scope_status_summary", "unknown") or "unknown"),
            "validation_sample": self._str_list_any(snapshot.get("validation_sample"))[:5],
            "commit_hash": str(snapshot.get("commit_hash", "") or ""),
            "commit_hash_short": str(snapshot.get("commit_hash_short", "") or ""),
            "commit_message": self._safe_short_str(snapshot.get("commit_message"), max_len=MAX_COMMIT_MESSAGE_CHARS),
            "committed_files": self._str_list_any(snapshot.get("committed_files"))[:MAX_COMMITTED_FILES],
            "committed_at": str(snapshot.get("committed_at", "") or ""),
            "commit_head_before": str(snapshot.get("commit_head_before", "") or ""),
            "commit_head_after": str(snapshot.get("commit_head_after", "") or ""),
            "commit_metadata_status": str(snapshot.get("commit_metadata_status", "unknown") or "unknown"),
            "evidence_paths": {
                "version_audit_file": target_file,
                "selected_report_json_file": str(snapshot.get("selected_report_json_file", "") or ""),
                "selected_report_markdown_file": str(snapshot.get("selected_report_markdown_file", "") or ""),
            },
            "source_report_ids": self._str_list_any(snapshot.get("source_report_ids")),
            "source_executor_audit_files": self._str_list_any(snapshot.get("source_executor_audit_files")),
            "base_audit_package_file": base_audit_package_file,
            "previous_refresh_files": previous_refresh_files[:50],
            "refresh_reason": self._safe_short_str(reason, max_len=200),
        }

    def _load_existing_version_commit_metadata(self, version: str) -> dict[str, Any]:
        try:
            latest_ret = self.get_latest_materialized_version_audit_package(version)
        except Exception:
            return {}
        if not latest_ret.get("ok"):
            return {}
        pkg = latest_ret.get("audit_package")
        if not isinstance(pkg, dict):
            return {}
        return {
            "commit_hash": self._safe_short_str(pkg.get("commit_hash"), max_len=80),
            "commit_hash_short": self._safe_short_str(pkg.get("commit_hash_short"), max_len=20),
            "commit_message": self._safe_short_str(pkg.get("commit_message"), max_len=MAX_COMMIT_MESSAGE_CHARS),
            "committed_at": self._safe_short_str(pkg.get("committed_at"), max_len=80),
            "committed_files": self._str_list_any(pkg.get("committed_files"))[:MAX_COMMITTED_FILES],
            "commit_head_before": self._safe_short_str(pkg.get("commit_head_before"), max_len=80),
            "commit_head_after": self._safe_short_str(pkg.get("commit_head_after"), max_len=80),
            "commit_metadata_status": self._safe_short_str(pkg.get("commit_metadata_status"), max_len=40) or "unknown",
        }

    def _resolve_version_commit_metadata(
        self,
        *,
        version: str,
        selected_report: dict[str, Any],
        changed_files: list[str],
        existing: dict[str, Any],
    ) -> dict[str, Any]:
        existing_data = existing if isinstance(existing, dict) else {}
        commit_hash = self._safe_short_str(existing_data.get("commit_hash"), max_len=80)
        commit_message = self._safe_short_str(existing_data.get("commit_message"), max_len=MAX_COMMIT_MESSAGE_CHARS)
        committed_at = self._safe_short_str(existing_data.get("committed_at"), max_len=80)
        committed_files = self._str_list_any(existing_data.get("committed_files"))[:MAX_COMMITTED_FILES]
        commit_head_before = self._safe_short_str(existing_data.get("commit_head_before"), max_len=80)
        commit_head_after = self._safe_short_str(existing_data.get("commit_head_after"), max_len=80)
        status = self._safe_short_str(existing_data.get("commit_metadata_status"), max_len=40) or "unknown"

        report_head_before = self._safe_short_str(selected_report.get("commit_head_before"), max_len=80)
        report_head_after = self._safe_short_str(selected_report.get("commit_head_after"), max_len=80)
        if report_head_before:
            commit_head_before = report_head_before
        if report_head_after:
            commit_head_after = report_head_after

        if report_head_after and status != "confirmed":
            commit_hash = report_head_after
            status = "confirmed"

        if not commit_hash:
            head_hash = self._read_git_head_commit_hash()
            if head_hash:
                commit_hash = head_hash
                commit_head_after = head_hash
                status = "candidate"

        if commit_hash:
            git_meta = self._read_git_commit_metadata(commit_hash)
            if git_meta.get("ok"):
                commit_message = self._safe_short_str(git_meta.get("commit_message"), max_len=MAX_COMMIT_MESSAGE_CHARS) or commit_message
                committed_at = self._safe_short_str(git_meta.get("committed_at"), max_len=80) or committed_at
                git_files = self._str_list_any(git_meta.get("committed_files"))
                if git_files:
                    committed_files = git_files[:MAX_COMMITTED_FILES]
            elif status not in {"confirmed", "candidate"}:
                status = "unknown"

        if not committed_files:
            committed_files = [str(x) for x in changed_files if isinstance(x, str)][:MAX_COMMITTED_FILES]

        if not commit_hash:
            status = "unavailable"

        commit_hash_short = ""
        if commit_hash:
            commit_hash_short = commit_hash[:12]

        return {
            "commit_hash": commit_hash,
            "commit_hash_short": commit_hash_short,
            "commit_message": commit_message,
            "committed_at": committed_at,
            "committed_files": committed_files,
            "commit_head_before": commit_head_before,
            "commit_head_after": commit_head_after,
            "commit_metadata_status": status,
        }

    def _read_git_head_commit_hash(self) -> str:
        ret = self._run_git_readonly(["rev-parse", "HEAD"])
        if ret.get("ok"):
            return self._safe_short_str(ret.get("stdout"), max_len=80)
        return ""

    def _read_git_commit_metadata(self, commit_hash: str) -> dict[str, Any]:
        safe_hash = self._safe_short_str(commit_hash, max_len=80)
        if not safe_hash:
            return {"ok": False}
        show_res = self._run_git_readonly(["show", "-s", "--format=%H%n%s%n%cI", safe_hash])
        if not show_res.get("ok"):
            return {"ok": False}
        lines = str(show_res.get("stdout", "") or "").splitlines()
        full_hash = lines[0].strip() if len(lines) >= 1 else ""
        commit_message = lines[1].strip() if len(lines) >= 2 else ""
        committed_at = lines[2].strip() if len(lines) >= 3 else ""
        files_res = self._run_git_readonly(["show", "--name-only", "--pretty=format:", safe_hash])
        committed_files: list[str] = []
        if files_res.get("ok"):
            committed_files = [line.strip() for line in str(files_res.get("stdout", "") or "").splitlines() if line.strip()]
        return {
            "ok": True,
            "commit_hash": self._safe_short_str(full_hash, max_len=80) or safe_hash,
            "commit_message": self._safe_short_str(commit_message, max_len=MAX_COMMIT_MESSAGE_CHARS),
            "committed_at": self._safe_short_str(committed_at, max_len=80),
            "committed_files": committed_files[:MAX_COMMITTED_FILES],
        }

    def _run_git_readonly(self, args: list[str], timeout_sec: int = 5) -> dict[str, Any]:
        rc, stdout, stderr = _run_git_base(args, self.project_root, timeout=timeout_sec)
        if rc != 0:
            return {"ok": False, "stdout": "", "stderr": (stderr or "")[:300]}
        return {"ok": True, "stdout": (stdout or "").strip(), "stderr": ""}

    def _str_list_any(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        out: list[str] = []
        for item in value:
            if isinstance(item, str) and item:
                out.append(item)
        return out

    def _sha256_file(self, path: str) -> str:
        if not path or not isinstance(path, str):
            return ""
        try:
            with open(path, "rb") as handle:
                h = hashlib.sha256()
                for chunk in iter(lambda: handle.read(65536), b""):
                    h.update(chunk)
                return h.hexdigest()
        except Exception:
            return ""

    def _safe_short_str(self, value: Any, max_len: int = 300) -> str:
        if not isinstance(value, str):
            return ""
        text = value.strip()
        if not text:
            return ""
        return text[:max_len]

    def _summarize_validation(self, results: list[str]) -> str:
        if not results:
            return "unknown"
        passed = 0
        failed = 0
        for item in results:
            upper = item.upper()
            if upper.startswith("PASSED:"):
                passed += 1
            elif upper.startswith("FAILED:"):
                failed += 1
        if failed > 0:
            return "failed"
        if passed > 0:
            return "passed"
        return "unknown"

    def _summarize_scope(self, results: list[str]) -> str:
        scope_lines = [item for item in results if item.startswith("Scope check:")]
        if not scope_lines:
            return "unknown"
        last = scope_lines[-1].split(":", 1)[-1].strip().upper()
        if last in {"PASSED", "NOT_CHECKED"}:
            return "ok"
        if last in {"FAILED", "BLOCKED", "VIOLATION"}:
            return "blocked"
        return last.lower() if last else "unknown"

    def _write_latest_pointer(self, directory: str, version: str, report_id: str, json_file: str, md_file: str) -> None:
        pointer = {
            "version": version,
            "report_id": report_id,
            "json_file": json_file,
            "markdown_file": md_file,
            "updated_at": _now_iso(),
        }
        pointer_path = os.path.join(directory, "latest.json")
        fd, tmp = tempfile.mkstemp(prefix=".latest-", suffix=".json", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(pointer, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            os.replace(tmp, pointer_path)
        except Exception:
            try:
                os.unlink(tmp)
            except Exception:
                pass

    def _read_latest_pointer(self, directory: str) -> str | None:
        pointer_path = os.path.join(directory, "latest.json")
        if not os.path.isfile(pointer_path):
            return None
        try:
            data = self._load_json(pointer_path)
            if not isinstance(data, dict):
                return None
            jf = data.get("json_file")
            if isinstance(jf, str) and os.path.isfile(jf) and self._is_under_reports_root(jf):
                return os.path.realpath(jf)
        except Exception:
            pass
        return None

    def _load_json(self, path: str) -> dict[str, Any] | None:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    def _report_sort_key(self, report: dict[str, Any], fallback_path: str) -> tuple[Any, ...]:
        finished_at_raw = str(report.get("finished_at", "") or "")
        finished_at_ts = self._parse_finished_at_timestamp(finished_at_raw)
        report_id = str(report.get("report_id", "") or "")
        json_file = str(report.get("json_file", "") or fallback_path)
        return (finished_at_ts, report_id, json_file)

    def _parse_finished_at_timestamp(self, finished_at: str) -> float:
        text = str(finished_at or "").strip()
        if not text:
            return 0.0
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(text).timestamp()
        except Exception:
            return 0.0
