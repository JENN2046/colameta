import json
import os
import re
from pathlib import Path
from typing import Any

from runner.current_version import load_current_version
from runner.evidence_builder import build_post_executor_patch_evidence
from runner.manual_acceptance import detect_manual_acceptance
from runner.markdown_sections import (
    append_section,
    find_section,
    normalize_section_body,
    parse_headings,
    replace_section_body,
)
from runner.mcp_project_patch import MCPProjectPatchManager
from runner.param_utils import bounded_int
from runner.source_review_bridge import SourceReviewBridge
from runner.tool_result import apply_result, error_result, ok_result, preview_result as build_preview_result

ALLOWED_DOC_DIRS = {"", "docs"}
ALLOWED_DOC_NAMES = {"README.md", "AGENTS.md"}
ALLOWED_DOC_PREFIXES = {"docs/"}
DENIED_DOC_PATTERNS = re.compile(
    r"(^|/)\.(git|env)|"
    r"(^|/)(runtime|logs|secrets|db|venv|node_modules|dist|build)(/|$)",
    re.IGNORECASE,
)

STALE_TERM_RULES: list[dict[str, Any]] = [
    {
        "id": "tui_primary_entry",
        "category": "tui_primary_entry",
        "severity": "warning",
        "patterns": [
            re.compile(r"(?i)TUI\s+(is\s+the\s+)?(primary|main|recommended)\s+(entry|interface|way)"),
            re.compile(r"(?i)(primary|main|recommended)\s+(entry|interface|way)\s+is\s+the\s+TUI"),
        ],
        "suggested_note": (
            "TUI has been retired. The current primary entry is Web Console + MCP + CLI fallback. "
            "Keep historical TUI descriptions as-is, but update main-entry claims."
        ),
    },
    {
        "id": "paste_plan_textarea",
        "category": "paste_plan_textarea",
        "severity": "warning",
        "patterns": [
            re.compile(r"(?i)paste\s+(your\s+)?plan\s+(json|text|content|in)"),
            re.compile(r"(?i)(large|big)\s+text(area|box)\s+(to\s+)?(paste|enter|input).*plan"),
        ],
        "suggested_note": (
            "Paste-plan UI is retired. Use manage_runner_plan / manage_plan_workflow / import-plan-file "
            "for plan onboarding."
        ),
    },
    {
        "id": "pi_default_executor",
        "category": "pi_default_executor",
        "severity": "info",
        "patterns": [
            re.compile(r"(?i)Pi\s+(is\s+the\s+)?(default|mainline|primary)\s+executor"),
            re.compile(r"(?i)(default|mainline|primary)\s+executor\s+is\s+Pi"),
        ],
        "suggested_note": (
            "Codex is now the default mainline executor. Pi remains supported as an alternative."
        ),
    },
    {
        "id": "apply_plan_patch_exposed",
        "category": "apply_plan_patch_exposed",
        "severity": "warning",
        "patterns": [
            re.compile(r"(?i)apply_plan_patch\s+(is|can be|can)\s+(called|used|exposed|invoked).*MCP"),
            re.compile(r"(?i)MCP.*apply_plan_patch"),
        ],
        "suggested_note": (
            "apply_plan_patch is intentionally NOT exposed over MCP. "
            "Plan apply uses the controlled preview/apply tool chain (manage_plan_version, manage_project_patch)."
        ),
    },
    {
        "id": "tui_active_maintenance",
        "category": "tui_active_maintenance",
        "severity": "info",
        "patterns": [
            re.compile(r"(?i)TUI\s+(is|remains|under)\s+(active\s+)?(maintenance|development|supported)"),
            re.compile(r"(?i)(actively|currently)\s+(maintain|develop|support).*TUI"),
        ],
        "suggested_note": (
            "TUI has been retired and is no longer maintained. "
            "Refer to Web Console + MCP + CLI as current entry points."
        ),
    },
]


class MCPProjectDocsError(Exception):
    def __init__(self, error_code: str, message: str):
        self.error_code = error_code
        self.message = message


class MCPProjectDocsManager:
    def __init__(self, project_root: str, source_review: SourceReviewBridge):
        self.project_root = os.path.abspath(os.path.expanduser(project_root))
        self.source_review = source_review
        self._patch_manager: MCPProjectPatchManager | None = None

    @property
    def patch_manager(self) -> MCPProjectPatchManager:
        if self._patch_manager is None:
            self._patch_manager = MCPProjectPatchManager(self.project_root, self.source_review)
        return self._patch_manager

    def handle(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        if action == "index":
            return self._index(params)
        if action == "search":
            return self._search(params)
        if action == "read_section":
            return self._read_section(params)
        if action == "update_section_preview":
            return self._update_section_preview(params)
        if action == "append_section_preview":
            return self._append_section_preview(params)
        if action == "sync_docs_preview":
            return self._sync_docs_preview(params)
        if action == "apply":
            return self._apply(params)
        return error_result("UNKNOWN_ACTION", f"未知 action：{action}")

    # ----------------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------------
    def _docs_files(self, max_files: int = 50) -> list[str]:
        files: list[str] = []
        root = Path(self.project_root)

        candidates = [
            root / "README.md",
            root / "AGENTS.md",
        ]
        docs_dir = root / "docs"
        if docs_dir.is_dir():
            for f in sorted(docs_dir.iterdir()):
                if f.suffix == ".md" and f.is_file():
                    candidates.append(f)

        for abs_path in candidates:
            if not abs_path.is_file():
                continue
            rel = os.path.relpath(str(abs_path), self.project_root)
            if self._validate_doc_file(rel) and rel not in files:
                files.append(rel)
            if len(files) >= max_files:
                break

        return files

    def _validate_doc_file(self, file: str) -> bool:
        if not isinstance(file, str) or not file.strip():
            return False
        norm = file.strip()
        if norm.startswith("/") or norm.startswith(".."):
            return False
        if DENIED_DOC_PATTERNS.search(norm):
            return False
        if norm in ALLOWED_DOC_NAMES:
            return True
        for prefix in ALLOWED_DOC_PREFIXES:
            if norm.startswith(prefix) and norm.endswith(".md"):
                return True
        return False

    def _read_doc(self, file: str) -> str:
        if not self._validate_doc_file(file):
            raise MCPProjectDocsError("PATH_NOT_ALLOWED", f"不允许的文件路径：{file}")
        abs_path = Path(self.project_root) / file
        if not abs_path.is_file():
            raise MCPProjectDocsError("FILE_NOT_FOUND", f"文件不存在：{file}")
        try:
            return abs_path.read_text(encoding="utf-8")
        except Exception as e:
            raise MCPProjectDocsError("FILE_READ_ERROR", f"读取文件失败：{e}")

    def _parse_headings(self, content: str) -> list[dict[str, Any]]:
        return parse_headings(content)

    def _find_section(self, content: str, heading: str) -> dict[str, Any] | None:
        return find_section(content, heading)

    def _normalize_section_body(self, body: str) -> str:
        return normalize_section_body(body)

    def _replace_section_body(self, content: str, heading: str, new_body: str) -> str | dict:
        return replace_section_body(content, heading, new_body)

    def _append_section(self, content: str, section_heading: str, section_content: str, after_heading: str | None) -> str | dict:
        return append_section(content, section_heading, section_content, after_heading)

    def _scan_stale_terms(self, content: str, file: str) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        lines = content.splitlines()
        for rule in STALE_TERM_RULES:
            for pattern in rule["patterns"]:
                for i, line in enumerate(lines, start=1):
                    m = pattern.search(line)
                    if m:
                        start = max(0, m.start() - 20)
                        end = min(len(line), m.end() + 40)
                        snippet = line[start:end].strip()
                        findings.append({
                            "file": file,
                            "line": i,
                            "term": rule["id"],
                            "category": rule["category"],
                            "severity": rule["severity"],
                            "current_snippet": snippet[:200],
                            "suggested_note": rule["suggested_note"],
                        })
        return findings

    def _preview_exact_replace(self, file: str, old_text: str, new_text: str, reason: str | None) -> dict[str, Any]:
        patch_params: dict[str, Any] = {
            "file": file,
            "old_text": old_text,
            "new_text": new_text,
        }
        if reason:
            patch_params["reason"] = reason
        result = self.patch_manager.preview(patch_params)
        if not isinstance(result, dict):
            return {"ok": False, "error_code": "PATCH_PREVIEW_FAILED", "message": "patch preview 返回无效。"}
        return result

    # ----------------------------------------------------------------
    # Actions
    # ----------------------------------------------------------------
    def _index(self, params: dict[str, Any]) -> dict[str, Any]:
        max_files = bounded_int(params.get("max_files"), 50, 1, 100)
        max_chars = bounded_int(params.get("max_chars"), 12000, 1, 30000)

        files = self._docs_files(max_files)
        docs_list: list[dict[str, Any]] = []
        total_findings = 0
        findings_by_file: dict[str, int] = {}

        for f in files:
            try:
                content = self._read_doc(f)
            except MCPProjectDocsError:
                continue

            headings = self._parse_headings(content)
            title = headings[0]["heading"] if headings else Path(f).stem

            stale_findings = self._scan_stale_terms(content, f)
            if stale_findings:
                findings_by_file[f] = len(stale_findings)
                total_findings += len(stale_findings)

            docs_list.append({
                "file": f,
                "title": title,
                "heading_count": len(headings),
                "headings": headings[:max_chars // 100],
            })

            if len(docs_list) >= max_files:
                break

        return ok_result(
            "index",
            docs=docs_list,
            stale_term_summary={
                "total_findings": total_findings,
                "findings_by_file": findings_by_file,
            },
        )

    def _search(self, params: dict[str, Any]) -> dict[str, Any]:
        query = params.get("query")
        if not isinstance(query, str) or not query.strip():
            return error_result("INVALID_QUERY", "search 需要非空 query。")
        query = query.strip()

        max_files = bounded_int(params.get("max_files"), 50, 1, 100)
        files = self._docs_files(max_files)
        results: list[dict[str, Any]] = []

        for f in files:
            try:
                content = self._read_doc(f)
            except MCPProjectDocsError:
                continue

            headings = self._parse_headings(content)
            current_heading = ""

            for i, line in enumerate(content.splitlines(), start=1):
                for h in headings:
                    if h["line"] == i:
                        current_heading = h["heading"]
                        break

                if query.lower() in line.lower():
                    snippet = line.strip()[:300]
                    match_type = "heading" if any(h["line"] == i for h in headings) else "body"
                    results.append({
                        "file": f,
                        "heading": current_heading,
                        "line": i,
                        "match_type": match_type,
                        "snippet": snippet,
                    })

        return ok_result("search", query=query, results=results)

    def _read_section(self, params: dict[str, Any]) -> dict[str, Any]:
        file = params.get("file")
        if not isinstance(file, str) or not file.strip():
            return error_result("INVALID_FILE", "read_section 需要非空 file。")
        heading = params.get("heading")
        if not isinstance(heading, str) or not heading.strip():
            return error_result("INVALID_HEADING", "read_section 需要非空 heading。")
        max_chars = bounded_int(params.get("max_chars"), 12000, 1, 30000)

        file = file.strip()
        try:
            content = self._read_doc(file)
        except MCPProjectDocsError as e:
            return error_result(e.error_code, e.message)

        section = self._find_section(content, heading)
        if section is None:
            return error_result("SECTION_NOT_FOUND", f"文件 {file} 中未找到 heading「{heading}」。")
        if section.get("ambiguous"):
            return error_result("SECTION_AMBIGUOUS", f"heading「{heading}」匹配到 {section['matches']} 处，不唯一。")

        section_text = section["section_text"]
        truncated = False
        if len(section_text) > max_chars:
            section_text = section_text[:max_chars] + "\n... [truncated]"
            truncated = True

        return ok_result(
            "read_section",
            file=file,
            heading=section["heading"],
            level=section["level"],
            start_line=section["line"],
            end_line=section["end_line"],
            content=section_text,
            truncated=truncated,
        )

    def _update_section_preview(self, params: dict[str, Any]) -> dict[str, Any]:
        file = params.get("file")
        if not isinstance(file, str) or not file.strip():
            return error_result("INVALID_FILE", "update_section_preview 需要非空 file。")
        heading = params.get("heading")
        if not isinstance(heading, str) or not heading.strip():
            return error_result("INVALID_HEADING", "update_section_preview 需要非空 heading。")
        new_content = params.get("new_content")
        if not isinstance(new_content, str) or not new_content.strip():
            return error_result("INVALID_NEW_CONTENT", "update_section_preview 需要非空 new_content。")
        reason = params.get("reason")

        file = file.strip()
        heading = heading.strip()
        new_content = new_content.strip()

        if not self._validate_doc_file(file):
            return error_result("PATH_NOT_ALLOWED", f"不允许的文件路径：{file}")

        try:
            content = self._read_doc(file)
        except MCPProjectDocsError as e:
            return error_result(e.error_code, e.message)

        section = self._find_section(content, heading)
        if section is None:
            return error_result("SECTION_NOT_FOUND", f"文件 {file} 中未找到 heading「{heading}」。")
        if section.get("ambiguous"):
            return error_result("SECTION_AMBIGUOUS", f"heading「{heading}」匹配到 {section['matches']} 处，不唯一。")

        old_text = section["section_text"]
        body = self._normalize_section_body(new_content)
        lines = content.splitlines(keepends=True)
        heading_line = lines[section["line"] - 1]
        new_text = heading_line + body

        patch_preview = self._preview_exact_replace(file, old_text, new_text, reason)
        if not isinstance(patch_preview, dict) or not patch_preview.get("ok"):
            return patch_preview
        preview_id = str(patch_preview.get("preview_id") or "").strip()
        if preview_id:
            self._write_docs_preview_metadata(preview_id=preview_id, operation="update_section", file=file)

        return build_preview_result(
            "update_section_preview",
            str(patch_preview.get("preview_id")),
            underlying_action="manage_project_patch.preview",
            file=file,
            heading=heading,
            changed_files=patch_preview.get("changed_files", [file]),
            diff_hash=patch_preview.get("diff_hash"),
            diff_summary=patch_preview.get("diff_summary"),
            manual_review_required=True,
            recommended_next_action="manage_project_docs.apply",
        )

    def _append_section_preview(self, params: dict[str, Any]) -> dict[str, Any]:
        file = params.get("file")
        if not isinstance(file, str) or not file.strip():
            return error_result("INVALID_FILE", "append_section_preview 需要非空 file。")
        section_heading = params.get("section_heading")
        if not isinstance(section_heading, str) or not section_heading.strip():
            return error_result("INVALID_SECTION_HEADING", "append_section_preview 需要非空 section_heading。")
        section_content = params.get("section_content")
        if not isinstance(section_content, str) or not section_content.strip():
            return error_result("INVALID_SECTION_CONTENT", "append_section_preview 需要非空 section_content。")
        after_heading = params.get("after_heading")
        if after_heading is not None and not isinstance(after_heading, str):
            return error_result("INVALID_AFTER_HEADING", "after_heading 必须是字符串。")
        reason = params.get("reason")

        file = file.strip()
        section_heading = section_heading.strip()
        section_content = section_content.strip()

        if not self._validate_doc_file(file):
            return error_result("PATH_NOT_ALLOWED", f"不允许的文件路径：{file}")

        try:
            content = self._read_doc(file)
        except MCPProjectDocsError as e:
            if e.error_code == "FILE_NOT_FOUND":
                abs_path = Path(self.project_root) / file
                if abs_path.exists():
                    return error_result("FILE_NOT_FOUND", f"文件无法读取：{file}")
                creates_file = True
                file_exists_before = False
                new_content = f"# {section_heading}\n\n{section_content}\n"
                patch_preview = self._preview_exact_replace(file, "", new_content, reason)
                if not isinstance(patch_preview, dict) or not patch_preview.get("ok"):
                    return patch_preview
                preview_id = str(patch_preview.get("preview_id") or "").strip()
                if preview_id:
                    self._write_docs_preview_metadata(preview_id=preview_id, operation="create_file", file=file)
                return build_preview_result(
                    "append_section_preview",
                    str(patch_preview.get("preview_id")),
                    underlying_action="manage_project_patch.preview",
                    file=file,
                    section_heading=section_heading,
                    operation="create_file",
                    creates_file=creates_file,
                    file_exists_before=file_exists_before,
                    changed_files=patch_preview.get("changed_files", [file]),
                    diff_hash=patch_preview.get("diff_hash"),
                    diff_summary=patch_preview.get("diff_summary"),
                    manual_review_required=True,
                    recommended_next_action="manage_project_docs.apply",
                )
            return error_result(e.error_code, e.message)

        existing = self._find_section(content, section_heading)
        if existing is not None and not existing.get("ambiguous"):
            return error_result("SECTION_ALREADY_EXISTS", f"section「{section_heading}」已存在。建议使用 update_section_preview。")

        result = self._append_section(content, section_heading, section_content, after_heading)
        if isinstance(result, dict):
            return result

        new_content = result
        patch_preview = self._preview_exact_replace(file, content, new_content, reason)
        if not isinstance(patch_preview, dict) or not patch_preview.get("ok"):
            return patch_preview
        preview_id = str(patch_preview.get("preview_id") or "").strip()
        if preview_id:
            self._write_docs_preview_metadata(preview_id=preview_id, operation="append_section", file=file)

        return build_preview_result(
            "append_section_preview",
            str(patch_preview.get("preview_id")),
            underlying_action="manage_project_patch.preview",
            file=file,
            section_heading=section_heading,
            operation="append_section",
            creates_file=False,
            file_exists_before=True,
            changed_files=patch_preview.get("changed_files", [file]),
            diff_hash=patch_preview.get("diff_hash"),
            diff_summary=patch_preview.get("diff_summary"),
            manual_review_required=True,
            recommended_next_action="manage_project_docs.apply",
        )

    def _sync_docs_preview(self, params: dict[str, Any]) -> dict[str, Any]:
        max_files = bounded_int(params.get("max_files"), 50, 1, 100)
        reason = params.get("reason")

        files = self._docs_files(max_files)
        all_findings: list[dict[str, Any]] = []

        for f in files:
            try:
                content = self._read_doc(f)
            except MCPProjectDocsError:
                continue
            findings = self._scan_stale_terms(content, f)
            all_findings.extend(findings)

        if not all_findings:
            return ok_result(
                "sync_docs_preview",
                findings=[],
                preview_created=False,
                manual_review_required=True,
                recommended_next_action="review_findings",
            )

        max_patch_files = 5
        patch_files: list[str] = []
        patch_findings: list[dict[str, Any]] = []

        for finding in all_findings:
            f = finding["file"]
            if f not in patch_files:
                patch_files.append(f)
            patch_findings.append(finding)
            if len(patch_files) >= max_patch_files:
                break

        preview_id = None
        preview_created = False

        if patch_findings:
            try:
                combined_patch_text = self._build_sync_patch(patch_findings)
                if combined_patch_text:
                    patch_params: dict[str, Any] = {
                        "patch_text": combined_patch_text,
                    }
                    if reason:
                        patch_params["reason"] = reason
                    patch_result = self.patch_manager.preview(patch_params)
                    if isinstance(patch_result, dict) and patch_result.get("ok"):
                        preview_id = patch_result.get("preview_id")
                        preview_created = True
                        preview_id_text = str(preview_id or "").strip()
                        if preview_id_text:
                            first_file = patch_files[0] if patch_files else ""
                            self._write_docs_preview_metadata(preview_id=preview_id_text, operation="sync_docs", file=first_file)
            except Exception:
                pass

        if preview_created:
            return ok_result(
                "sync_docs_preview",
                findings=all_findings,
                preview_created=True,
                preview_id=preview_id,
                changed_files=list(dict.fromkeys(f["file"] for f in patch_findings)),
                diff_hash=None,
                manual_review_required=True,
                recommended_next_action="manage_project_docs.apply",
            )

        return ok_result(
            "sync_docs_preview",
            findings=all_findings,
            preview_created=False,
            manual_review_required=True,
            recommended_next_action="review_findings",
        )

    def _build_sync_patch(self, findings: list[dict[str, Any]]) -> str | None:
        patches: list[str] = []
        for finding in findings:
            f = finding["file"]
            try:
                content = self._read_doc(f)
            except MCPProjectDocsError:
                continue

            lines = content.splitlines(keepends=True)
            line_idx = finding["line"] - 1
            if line_idx < 0 or line_idx >= len(lines):
                continue

            old_line = lines[line_idx]
            note = finding["suggested_note"]
            inner_note = note.replace('"', "'")
            new_line = old_line.rstrip("\n\r") + f"  <!-- STALE: {inner_note[:120]} -->\n"
            lines[line_idx] = new_line

            new_content = "".join(lines)

            old_text = old_line
            new_text = new_line

            from difflib import unified_diff
            diff = list(unified_diff(
                [old_text], [new_text],
                fromfile=f"a/{f}",
                tofile=f"b/{f}",
            ))
            diff_text = "".join(diff)
            if diff_text:
                patches.append(diff_text)

        if not patches:
            return None

        return "\n".join(patches)

    def _docs_preview_metadata_path(self, preview_id: str) -> str:
        return resolve_project_runner_path(
            self.project_root, "runtime", "project-docs-previews", f"{preview_id}.json"
        )

    def _write_docs_preview_metadata(self, *, preview_id: str, operation: str, file: str) -> None:
        try:
            path = self._docs_preview_metadata_path(preview_id)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"preview_id": preview_id, "operation": operation, "file": file}, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
        except Exception:
            pass

    def _detect_docs_operation(self, preview_id: str) -> str:
        try:
            path = self._docs_preview_metadata_path(preview_id)
            if os.path.isfile(path):
                with open(path, "r", encoding="utf-8") as handle:
                    metadata = json.load(handle)
                if isinstance(metadata, dict):
                    operation = metadata.get("operation")
                    if isinstance(operation, str) and operation.strip():
                        return operation.strip()
        except Exception:
            pass
        return "apply"

    def _apply(self, params: dict[str, Any]) -> dict[str, Any]:
        preview_id = params.get("preview_id")
        if not isinstance(preview_id, str) or not preview_id.strip():
            return error_result("INVALID_PREVIEW_ID", "apply 需要非空 preview_id。")
        reason = params.get("reason")

        apply_params: dict[str, Any] = {
            "preview_id": preview_id.strip(),
        }
        if reason:
            apply_params["reason"] = reason

        result = self.patch_manager.apply(apply_params)
        if not isinstance(result, dict) or not result.get("ok"):
            return result

        version = load_current_version(self.project_root)
        now_ts = self.patch_manager._store.now_iso()
        operation = self._detect_docs_operation(preview_id)
        post_executor_patch_evidence = build_post_executor_patch_evidence(
            version=version,
            tool="manage_project_docs",
            preview_id=preview_id.strip(),
            files_changed=list(result.get("changed_files", [])),
            operation=operation,
            applied_at=now_ts,
            underlying_action="manage_project_patch.apply",
        )
        manual_acceptance = detect_manual_acceptance(reason)

        return apply_result(
            "apply",
            preview_id.strip(),
            underlying_action="manage_project_patch.apply",
            changed_files=result.get("changed_files", []),
            diff_hash=result.get("diff_hash"),
            diff_summary=result.get("diff_summary"),
            recommended_next_action="manage_git_commit.readiness",
            post_executor_patch_evidence=post_executor_patch_evidence,
            manual_acceptance_evidence=manual_acceptance,
        )
from runner.runner_paths import resolve_project_runner_path
