import json
import os
import re
import subprocess
from typing import Any


DEFAULT_SCAN_LIMIT = 20
MAX_SCAN_LIMIT = 100
VERSION_PATTERN = re.compile(r"\bv\d+(?:\.\d+){2,}\b", re.IGNORECASE)
MAX_LINEAGE_ENTRIES = 1200


def _normalize_version(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text[0] == "V":
        text = "v" + text[1:]
    return text


def _ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for raw in values:
        item = _normalize_version(raw)
        if not item or item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


def extract_versions_from_text(text: str) -> list[str]:
    if not isinstance(text, str) or not text.strip():
        return []
    found = VERSION_PATTERN.findall(text)
    return _ordered_unique(found)


class GitHistoryReconcileScanner:
    def __init__(self, project_root: str):
        self.project_root = os.path.abspath(os.path.expanduser(project_root))
        self.runner_dir = resolve_project_runner_dir(self.project_root)

    def scan_unreconciled_candidates(self, scan_limit: int | None = None) -> dict[str, Any]:
        bounded_limit = self._bounded_scan_limit(scan_limit)
        commits = self._read_recent_commits(bounded_limit)
        if isinstance(commits, dict):
            return commits

        lineage = self._collect_lineage_sets()
        candidates: list[dict[str, Any]] = []
        warnings: list[str] = []

        for item in commits:
            commit_hash = str(item.get("commit_hash") or "").strip()
            commit_hash_short = str(item.get("commit_hash_short") or "").strip()
            commit_message = str(item.get("commit_message") or "").strip()
            committed_at = item.get("committed_at")
            versions = extract_versions_from_text(commit_message)
            if not versions:
                continue

            version_states = {version: self._version_lineage_state(version, lineage) for version in versions}
            unmanaged_versions = [version for version in versions if not bool(version_states[version]["runner_managed"])]
            if not unmanaged_versions:
                continue

            ambiguous = len(versions) > 1
            selected_version = unmanaged_versions[0]
            selected_state = version_states[selected_version]
            candidate = self._build_candidate(
                version=selected_version,
                commit_hash=commit_hash,
                commit_hash_short=commit_hash_short,
                commit_message=commit_message,
                committed_at=committed_at,
                state=selected_state,
                ambiguous=ambiguous,
                detected_versions=versions,
                unmanaged_versions=unmanaged_versions,
            )
            if ambiguous:
                warnings.append(
                    f"commit {commit_hash_short or commit_hash[:8]} 的 message 含多个版本号：{', '.join(versions)}，需要人工确认。"
                )
            candidates.append(candidate)

        return {
            "ok": True,
            "action": "reconcile_git_history_preview",
            "scan_limit": bounded_limit,
            "scan_limit_max": MAX_SCAN_LIMIT,
            "scanned_commit_count": len(commits),
            "candidate_count": len(candidates),
            "candidates": candidates,
            "detection_basis": [
                "Git history commit message 版本号解析",
                "Runner plan/state/prompts/reports/audits lineage 比对",
            ],
            "lineage_summary": {
                "plan_version_count": len(lineage["plan_versions"]),
                "state_version_count": len(lineage["state_versions"]),
                "prompt_version_count": len(lineage["prompt_versions"]),
                "executor_report_version_count": len(lineage["report_versions"]),
                "audit_version_count": len(lineage["audit_versions"]),
            },
            "warnings": warnings[:20],
            "blockers": [],
            "preview_only": True,
            "recommended_next_action": {
                "tool": "run_mcp_workflow",
                "action": "manual_git_history_review_required",
                "params": {"workflow": "project_status", "phase": "inspect"},
            },
        }

    def inspect_commit_message(self, commit_hash: str, commit_message: str) -> dict[str, Any]:
        versions = extract_versions_from_text(commit_message)
        if not versions:
            return {
                "has_version_marker": False,
                "detected_versions": [],
                "ambiguous": False,
                "has_unreconciled_candidate": False,
            }

        lineage = self._collect_lineage_sets()
        states = {version: self._version_lineage_state(version, lineage) for version in versions}
        unmanaged_versions = [version for version in versions if not bool(states[version]["runner_managed"])]
        ambiguous = len(versions) > 1
        has_unreconciled = bool(unmanaged_versions)
        selected_version = unmanaged_versions[0] if unmanaged_versions else versions[0]
        selected_state = states[selected_version]
        commit_hash_short = str(commit_hash or "").strip()[:8]
        candidate = self._build_candidate(
            version=selected_version,
            commit_hash=commit_hash,
            commit_hash_short=commit_hash_short,
            commit_message=commit_message,
            committed_at=None,
            state=selected_state,
            ambiguous=ambiguous,
            detected_versions=versions,
            unmanaged_versions=unmanaged_versions,
        )
        return {
            "has_version_marker": True,
            "detected_versions": versions,
            "ambiguous": ambiguous,
            "has_unreconciled_candidate": has_unreconciled,
            "selected_candidate": candidate,
            "unmanaged_versions": unmanaged_versions,
        }

    def _build_candidate(
        self,
        *,
        version: str,
        commit_hash: str,
        commit_hash_short: str,
        commit_message: str,
        committed_at: Any,
        state: dict[str, Any],
        ambiguous: bool,
        detected_versions: list[str],
        unmanaged_versions: list[str],
    ) -> dict[str, Any]:
        candidate: dict[str, Any] = {
            "version": version,
            "commit_hash": commit_hash,
            "commit_hash_short": commit_hash_short,
            "commit_message": commit_message,
            "committed_at": committed_at if isinstance(committed_at, str) and committed_at.strip() else None,
            "source": "direct_git_commit",
            "runner_managed": bool(state.get("runner_managed")),
            "prompt_archived": bool(state.get("prompt_archived")),
            "executor_report_archived": bool(state.get("executor_report_archived")),
            "audit_archived": bool(state.get("audit_archived")),
            "note": "该版本由 Git 历史发现，未经过 Runner prompt_to_plan/run_once/report 链路。",
            "ambiguous": ambiguous,
        }
        if ambiguous:
            candidate["detected_versions"] = list(detected_versions)
            candidate["unmanaged_versions"] = list(unmanaged_versions)
        return candidate

    def _version_lineage_state(self, version: str, lineage: dict[str, set[str]]) -> dict[str, Any]:
        in_plan = version in lineage["plan_versions"]
        in_state = version in lineage["state_versions"]
        prompt_archived = version in lineage["prompt_versions"]
        report_archived = version in lineage["report_versions"]
        audit_archived = version in lineage["audit_versions"]
        return {
            "in_plan": in_plan,
            "in_state": in_state,
            "prompt_archived": prompt_archived,
            "executor_report_archived": report_archived,
            "audit_archived": audit_archived,
            "runner_managed": bool(in_plan or in_state or prompt_archived or report_archived or audit_archived),
        }

    def _collect_lineage_sets(self) -> dict[str, set[str]]:
        return {
            "plan_versions": self._load_plan_versions(),
            "state_versions": self._load_state_versions(),
            "prompt_versions": self._load_prompt_versions(),
            "report_versions": self._load_report_versions(),
            "audit_versions": self._load_audit_versions(),
        }

    def _load_plan_versions(self) -> set[str]:
        path = os.path.join(self.runner_dir, "plan.json")
        data = self._load_json_if_exists(path)
        if not isinstance(data, dict):
            return set()
        versions = data.get("versions")
        if not isinstance(versions, list):
            return set()
        result: set[str] = set()
        for item in versions:
            if not isinstance(item, dict):
                continue
            version = _normalize_version(str(item.get("version") or ""))
            if version:
                result.add(version)
        return result

    def _load_state_versions(self) -> set[str]:
        path = os.path.join(self.runner_dir, "state.json")
        data = self._load_json_if_exists(path)
        if not isinstance(data, dict):
            return set()
        result: set[str] = set()
        current_version = _normalize_version(str(data.get("current_version") or ""))
        if current_version:
            result.add(current_version)
        versions = data.get("versions")
        if not isinstance(versions, list):
            return result
        for item in versions:
            if not isinstance(item, dict):
                continue
            version = _normalize_version(str(item.get("version") or ""))
            if version:
                result.add(version)
        return result

    def _load_prompt_versions(self) -> set[str]:
        prompts_dir = os.path.join(self.runner_dir, "prompts")
        if not os.path.isdir(prompts_dir):
            return set()
        result: set[str] = set()
        try:
            for name in os.listdir(prompts_dir):
                match = VERSION_PATTERN.search(name)
                if match:
                    result.add(_normalize_version(match.group(0)))
        except Exception:
            return set()
        return result

    def _load_report_versions(self) -> set[str]:
        reports_root = os.path.join(self.runner_dir, "reports", "executor-runs")
        return self._collect_versions_from_tree(reports_root)

    def _load_audit_versions(self) -> set[str]:
        audits_root = os.path.join(self.runner_dir, "audits")
        return self._collect_versions_from_tree(audits_root)

    def _collect_versions_from_tree(self, root: str) -> set[str]:
        if not os.path.isdir(root):
            return set()
        result: set[str] = set()
        scanned = 0
        for base, dirs, files in os.walk(root):
            for name in list(dirs) + list(files):
                scanned += 1
                if scanned > MAX_LINEAGE_ENTRIES:
                    return result
                versions = extract_versions_from_text(name)
                for version in versions:
                    result.add(version)
                if len(result) >= MAX_LINEAGE_ENTRIES:
                    return result
            if scanned > MAX_LINEAGE_ENTRIES:
                return result
        return result

    def _read_recent_commits(self, scan_limit: int) -> list[dict[str, Any]] | dict[str, Any]:
        cmd = [
            "git",
            "log",
            f"--max-count={scan_limit}",
            "--pretty=format:%H%x1f%h%x1f%cI%x1f%s%x1e",
        ]
        try:
            proc = subprocess.run(
                cmd,
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except Exception as exc:
            return {
                "ok": False,
                "action": "reconcile_git_history_preview",
                "error_code": "GIT_LOG_EXEC_FAILED",
                "message": f"执行 git log 失败：{exc}",
                "blockers": ["git_log_failed"],
            }
        if proc.returncode != 0:
            stderr = (proc.stderr or "").strip()
            return {
                "ok": False,
                "action": "reconcile_git_history_preview",
                "error_code": "GIT_LOG_FAILED",
                "message": stderr[:500] if stderr else "git log 执行失败。",
                "blockers": ["git_log_failed"],
            }

        raw = proc.stdout or ""
        commits: list[dict[str, Any]] = []
        for chunk in raw.split("\x1e"):
            item = chunk.strip()
            if not item:
                continue
            parts = item.split("\x1f")
            if len(parts) < 4:
                continue
            commit_hash = str(parts[0]).strip()
            short_hash = str(parts[1]).strip()
            committed_at = str(parts[2]).strip()
            commit_message = str(parts[3]).strip()
            if not commit_hash:
                continue
            commits.append(
                {
                    "commit_hash": commit_hash,
                    "commit_hash_short": short_hash or commit_hash[:8],
                    "committed_at": committed_at or None,
                    "commit_message": commit_message,
                }
            )
        return commits

    def _load_json_if_exists(self, path: str) -> dict[str, Any] | None:
        if not os.path.isfile(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except Exception:
            return None

    def _bounded_scan_limit(self, scan_limit: int | None) -> int:
        if isinstance(scan_limit, bool):
            return DEFAULT_SCAN_LIMIT
        try:
            value = int(scan_limit) if scan_limit is not None else DEFAULT_SCAN_LIMIT
        except Exception:
            value = DEFAULT_SCAN_LIMIT
        if value < 1:
            value = DEFAULT_SCAN_LIMIT
        return min(value, MAX_SCAN_LIMIT)
from runner.runner_paths import resolve_project_runner_dir
