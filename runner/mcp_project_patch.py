import os
import re
import subprocess
from pathlib import Path
from typing import Any

from runner.core_confirmation import confirmation_apply_guard, confirmation_fact_from_store
from runner.preview_artifact import PreviewArtifact
from runner.current_version import load_current_version
from runner.diff_utils import diff_hash, synthetic_unified_diff, truncate_text
from runner.evidence_builder import build_post_executor_patch_evidence
from runner.file_signature import signatures_equal, text_signature
from runner.manual_acceptance import detect_manual_acceptance
from runner.param_utils import bounded_int
from runner.runner_paths import resolve_project_runner_rel_dir
from runner.source_review_bridge import SourceReviewBridge, SourceReviewError
from runner.tool_result import apply_result, error_result, preview_result, status_result


PREVIEW_TTL_SECONDS = 1800
MAX_FILES_DEFAULT = 5
MAX_FILES_CAP = 5
MAX_DIFF_CHARS_DEFAULT = 20000
MAX_DIFF_CHARS_CAP = 20000
PREVIEW_DIR_NAME = "project-patch-previews"
PREVIEW_RELATIVE_DIR = os.path.join("runtime", PREVIEW_DIR_NAME)


def _read_text_file(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _git_diff_for_files(project_root: str, files: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", "diff", "--", *files],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return result.stdout
    except Exception:
        pass
    return ""


def _git_diff_all(project_root: str) -> str:
    try:
        result = subprocess.run(
            ["git", "diff"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return result.stdout
    except Exception:
        pass
    return ""


class MCPProjectPatchManager:
    def __init__(self, project_root: str, source_review: SourceReviewBridge):
        self.project_root = os.path.abspath(os.path.expanduser(project_root))
        self.source_review = source_review
        preview_dir = os.path.join(resolve_project_runner_rel_dir(self.project_root), PREVIEW_RELATIVE_DIR)
        self._store = PreviewArtifact(self.project_root, preview_dir, PREVIEW_TTL_SECONDS)

    def preview(self, params: dict[str, Any]) -> dict[str, Any]:
        mode = self._detect_mode(params)
        if mode == "exact_replace":
            return self._preview_exact_replace(params)
        elif mode == "unified_diff":
            return self._preview_unified_diff(params)
        elif mode == "delete_file":
            return self._preview_delete(params)
        else:
            return error_result("INVALID_INPUT", "必须提供 (file + old_text + new_text) 用于精确替换，或 patch_text 用于 unified diff。")

    def preview_delete(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._preview_delete(params)

    def _detect_mode(self, params: dict[str, Any]) -> str | None:
        has_exact = (
            isinstance(params.get("file"), str)
            and isinstance(params.get("old_text"), str)
            and "new_text" in params
        )
        has_patch = isinstance(params.get("patch_text"), str)
        if has_exact and has_patch:
            return None
        if has_exact:
            return "exact_replace"
        if has_patch:
            return "unified_diff"
        return None

    def _preview_exact_replace(self, params: dict[str, Any]) -> dict[str, Any]:
        file_raw = params.get("file", "")
        old_text = params.get("old_text", "")
        new_text = params.get("new_text", "")
        reason = params.get("reason")
        max_diff_chars = bounded_int(
            params.get("max_diff_chars"), MAX_DIFF_CHARS_DEFAULT, 1, MAX_DIFF_CHARS_CAP
        )
        max_files = bounded_int(
            params.get("max_files"), MAX_FILES_DEFAULT, 1, MAX_FILES_CAP
        )
        allow_create = params.get("allow_create", True) is not False
        require_existing_file = params.get("require_existing_file", False) is True

        if not isinstance(file_raw, str) or not file_raw.strip():
            return error_result("INVALID_FILE", "file 必须是非空字符串。")
        if not isinstance(old_text, str):
            return error_result("INVALID_OLD_TEXT", "old_text 必须是字符串。")
        if "new_text" not in params or not isinstance(params["new_text"], str):
            return error_result("INVALID_NEW_TEXT", "new_text 必须是字符串。")

        rel_path = self._normalize_and_validate_path(file_raw)
        if isinstance(rel_path, dict):
            return rel_path

        abs_path = Path(self.project_root) / rel_path
        file_exists = abs_path.exists() and abs_path.is_file()
        if require_existing_file and not file_exists:
            return error_result("FILE_NOT_FOUND", f"文件不存在：{rel_path}")
        if not allow_create and not file_exists:
            return error_result("FILE_NOT_FOUND", f"文件不存在：{rel_path}")

        creates_file = False
        replaces_empty_file = False
        if old_text == "":
            if file_exists:
                try:
                    content = _read_text_file(abs_path)
                except Exception as e:
                    return error_result("FILE_READ_ERROR", f"读取文件失败：{e}")
                if content != "":
                    return error_result(
                        "AMBIGUOUS_EMPTY_OLD_TEXT",
                        f"文件 {rel_path} 已存在且非空。old_text=\"\" 只能用于创建新文件或写入已存在空文件。",
                    )
                replaces_empty_file = True
            else:
                creates_file = True
                content = ""
            if not new_text.strip():
                message = "创建文件时 new_text 不能为空。" if creates_file else "写入空文件时 new_text 不能为空。"
                return error_result("INVALID_NEW_TEXT", message)
            new_content = new_text
        else:
            if not file_exists:
                return error_result("FILE_NOT_FOUND", f"文件不存在：{rel_path}")
            try:
                content = _read_text_file(abs_path)
            except Exception as e:
                return error_result("FILE_READ_ERROR", f"读取文件失败：{e}")

            count = content.count(old_text)
            if count == 0:
                return error_result("OLD_TEXT_NOT_FOUND", f"old_text 在文件 {rel_path} 中不存在。")
            if count > 1:
                return error_result("OLD_TEXT_NOT_UNIQUE", f"old_text 在文件 {rel_path} 中出现 {count} 次，不唯一。")

            new_content = content.replace(old_text, new_text, 1)

        if len(old_text) > MAX_DIFF_CHARS_CAP * 2 or len(new_content) > 10_000_000:
            return error_result("CONTENT_TOO_LARGE", "文件内容过大。")

        sig = text_signature(content)

        predicted_diff = synthetic_unified_diff(rel_path, content, new_content)
        if len(predicted_diff) > max_diff_chars:
            return error_result("DIFF_TOO_LARGE", f"预计 diff 长度为 {len(predicted_diff)} 字符，超过限制 {max_diff_chars}。")

        preview_id = self._store.create_id()
        created_at = self._store.now_iso()
        expires_at = self._store.expires_at()

        exact_operation = "create_file" if creates_file else "replace_empty_file" if replaces_empty_file else "replace_text"
        preview_data: dict[str, Any] = {
            "preview_id": preview_id,
            "created_at": created_at,
            "expires_at": expires_at,
            "project_root": self.project_root,
            "mode": "exact_replace",
            "reason": reason if isinstance(reason, str) and reason.strip() else "",
            "files": [rel_path],
            "create_files": [rel_path] if creates_file else [],
            "base_signatures": {rel_path: sig},
            "exact_specs": [{"file": rel_path, "old_text": old_text, "new_text": new_text, "operation": exact_operation}],
            "predicted_diff": predicted_diff,
            "predicted_diff_hash": diff_hash(predicted_diff),
            "max_files": max_files,
            "max_diff_chars": max_diff_chars,
            "warnings": [],
        }
        self._write_preview(preview_id, preview_data)

        return preview_result(
            "preview",
            preview_id,
            mode="exact_replace",
            changed_files=[rel_path],
            diff_summary=truncate_text(predicted_diff, 2000),
            diff_hash=preview_data["predicted_diff_hash"],
            expires_at=expires_at,
            warnings=[],
            recommended_next_action="apply",
        )

    def _preview_unified_diff(self, params: dict[str, Any]) -> dict[str, Any]:
        patch_text = params.get("patch_text", "")
        reason = params.get("reason")
        max_diff_chars = bounded_int(
            params.get("max_diff_chars"), MAX_DIFF_CHARS_DEFAULT, 1, MAX_DIFF_CHARS_CAP
        )
        max_files = bounded_int(
            params.get("max_files"), MAX_FILES_DEFAULT, 1, MAX_FILES_CAP
        )

        if not isinstance(patch_text, str) or not patch_text.strip():
            return error_result("INVALID_PATCH_TEXT", "patch_text 必须是非空字符串。")

        if "\0" in patch_text:
            return error_result("BINARY_PATCH", "不支持 binary patch。")

        files = self._parse_unified_diff_files(patch_text)
        if not files:
            return error_result("NO_FILES_IN_PATCH", "patch_text 中未解析出任何文件。")

        if len(files) > max_files:
            return error_result("TOO_MANY_FILES", f"patch 涉及 {len(files)} 个文件，超过限制 {max_files}。")

        sections_by_file = self._sections_by_normalized_file(patch_text)
        validated_files: list[str] = []
        create_files: set[str] = set()
        for f in files:
            validated = self._normalize_and_validate_path(f)
            if isinstance(validated, dict):
                return validated
            if validated not in validated_files:
                validated_files.append(validated)
            abs_path = Path(self.project_root) / validated
            file_diff = sections_by_file.get(validated, "")
            is_create = self._is_unified_diff_create(file_diff)
            if is_create:
                if abs_path.exists():
                    return error_result("FILE_ALREADY_EXISTS", f"patch 标记为创建新文件，但 {validated} 已存在。")
                create_files.add(validated)
                continue
            if not abs_path.exists() or not abs_path.is_file():
                return error_result("FILE_NOT_FOUND", f"patch 中文件不存在：{validated}")
        files = validated_files

        if len(patch_text) > max_diff_chars:
            return error_result("DIFF_TOO_LARGE", f"patch_text 长度为 {len(patch_text)} 字符，超过限制 {max_diff_chars}。")

        base_signatures: dict[str, dict[str, Any]] = {}
        for f in files:
            abs_path = Path(self.project_root) / f
            if f in create_files:
                base_signatures[f] = text_signature("")
                continue
            try:
                content = _read_text_file(abs_path)
            except Exception as e:
                return error_result("FILE_READ_ERROR", f"读取 {f} 失败：{e}")
            base_signatures[f] = text_signature(content)

        preview_id = self._store.create_id()
        created_at = self._store.now_iso()
        expires_at = self._store.expires_at()

        preview_data: dict[str, Any] = {
            "preview_id": preview_id,
            "created_at": created_at,
            "expires_at": expires_at,
            "project_root": self.project_root,
            "mode": "unified_diff",
            "reason": reason if isinstance(reason, str) and reason.strip() else "",
            "files": files,
            "create_files": sorted(create_files),
            "base_signatures": base_signatures,
            "patch_text": patch_text,
            "predicted_diff": patch_text,
            "predicted_diff_hash": diff_hash(patch_text),
            "max_files": max_files,
            "max_diff_chars": max_diff_chars,
            "warnings": [],
        }
        self._write_preview(preview_id, preview_data)

        return preview_result(
            "preview",
            preview_id,
            mode="unified_diff",
            changed_files=files,
            diff_summary=truncate_text(patch_text, 2000),
            diff_hash=preview_data["predicted_diff_hash"],
            expires_at=expires_at,
            warnings=[],
            recommended_next_action="apply",
        )

    def _preview_delete(self, params: dict[str, Any]) -> dict[str, Any]:
        file_raw = params.get("file", "")
        reason = params.get("reason")
        max_diff_chars = bounded_int(
            params.get("max_diff_chars"), MAX_DIFF_CHARS_DEFAULT, 1, MAX_DIFF_CHARS_CAP
        )

        if not isinstance(file_raw, str) or not file_raw.strip():
            return error_result("INVALID_FILE", "file 必须是非空字符串。")

        rel_path = self._normalize_and_validate_path(file_raw)
        if isinstance(rel_path, dict):
            return rel_path

        abs_path = Path(self.project_root) / rel_path
        if not abs_path.exists():
            return error_result("FILE_NOT_FOUND", f"文件不存在：{rel_path}")
        if abs_path.is_dir():
            return error_result("IS_DIRECTORY", f"不支持删除目录：{rel_path}")

        try:
            content = _read_text_file(abs_path)
        except Exception as e:
            return error_result("FILE_READ_ERROR", f"读取文件失败：{e}")

        if len(content) > 10_000_000:
            return error_result("CONTENT_TOO_LARGE", "文件内容过大。")

        sig = text_signature(content)

        predicted_diff = synthetic_unified_diff(rel_path, content, "")
        if len(predicted_diff) > max_diff_chars:
            return error_result("DIFF_TOO_LARGE", f"预计 diff 长度为 {len(predicted_diff)} 字符，超过限制 {max_diff_chars}。")

        preview_id = self._store.create_id()
        created_at = self._store.now_iso()
        expires_at = self._store.expires_at()

        preview_data: dict[str, Any] = {
            "preview_id": preview_id,
            "created_at": created_at,
            "expires_at": expires_at,
            "project_root": self.project_root,
            "mode": "delete_file",
            "reason": reason if isinstance(reason, str) and reason.strip() else "",
            "files": [rel_path],
            "delete_files": [rel_path],
            "base_signatures": {rel_path: sig},
            "predicted_diff": predicted_diff,
            "predicted_diff_hash": diff_hash(predicted_diff),
            "max_files": 1,
            "max_diff_chars": max_diff_chars,
            "warnings": [],
        }
        self._write_preview(preview_id, preview_data)

        return preview_result(
            "preview",
            preview_id,
            mode="delete_file",
            changed_files=[rel_path],
            diff_summary=truncate_text(predicted_diff, 2000),
            diff_hash=preview_data["predicted_diff_hash"],
            expires_at=expires_at,
            warnings=[],
            recommended_next_action="apply",
        )

    def apply(self, params: dict[str, Any]) -> dict[str, Any]:
        raw_preview_id = params.get("preview_id")
        if not isinstance(raw_preview_id, str) or not raw_preview_id.strip():
            return error_result("INVALID_PREVIEW_ID", "apply 需要非空 preview_id。")
        preview_id = raw_preview_id.strip()

        guard = confirmation_apply_guard(self._store, preview_id, project_root=self.project_root)
        if not guard["ok"]:
            ec = guard["error_code"]
            if ec == "PREVIEW_NOT_FOUND":
                return error_result("PREVIEW_NOT_FOUND", f"preview 不存在：{preview_id}")
            if ec == "PROJECT_MISMATCH":
                return {"ok": False, "error_code": "PROJECT_MISMATCH", "message": "preview 与当前项目不匹配。"}
            if ec == "PREVIEW_EXPIRED":
                return {"ok": False, "error_code": "PREVIEW_EXPIRED", "message": "preview 已过期。"}
        preview_data = guard["payload"]

        mode = preview_data.get("mode", "")

        base_sigs = preview_data.get("base_signatures", {})
        create_file_set = set(preview_data.get("create_files", []))
        delete_file_set = set(preview_data.get("delete_files", []))
        if preview_data.get("mode") == "exact_replace":
            create_file_set.update(
                spec.get("file", "") for spec in preview_data.get("exact_specs", []) if spec.get("operation") == "create_file"
            )
        for file_path, sig in base_sigs.items():
            abs_path = Path(self.project_root) / file_path
            is_create = file_path in create_file_set
            if is_create:
                if abs_path.exists():
                    return error_result("FILE_ALREADY_EXISTS", f"preview 标记为创建新文件，但 {file_path} 已存在。")
                continue
            if not abs_path.exists() or not abs_path.is_file():
                return error_result("BASE_CHANGED", f"文件已不存在：{file_path}")
            try:
                current_content = _read_text_file(abs_path)
            except Exception:
                return error_result("FILE_READ_ERROR", f"无法读取文件：{file_path}")
            current_sig = text_signature(current_content)
            if not signatures_equal(current_sig, sig):
                return error_result("BASE_CHANGED", f"文件已变化：{file_path}")

        files = preview_data.get("files", [])

        if mode == "exact_replace":
            specs = preview_data.get("exact_specs", [])
            for spec in specs:
                file_path = spec.get("file", "")
                old_text = spec.get("old_text", "")
                new_text = spec.get("new_text", "")
                abs_path = Path(self.project_root) / file_path
                if old_text == "":
                    abs_path.parent.mkdir(parents=True, exist_ok=True)
                    abs_path.write_text(new_text, encoding="utf-8")
                else:
                    content = _read_text_file(abs_path)
                    new_content = content.replace(old_text, new_text, 1)
                    abs_path.write_text(new_content, encoding="utf-8")

        elif mode == "unified_diff":
            patch_text = preview_data.get("patch_text", "")
            result = self._apply_unified_diff_text(patch_text, files)
            if isinstance(result, dict):
                return result

        elif mode == "delete_file":
            for file_path in delete_file_set:
                abs_path = Path(self.project_root) / file_path
                if abs_path.exists():
                    abs_path.unlink()

        else:
            return error_result("UNKNOWN_MODE", f"未知 preview 模式：{mode}")

        diff_text = _git_diff_for_files(self.project_root, files)
        if not diff_text:
            diff_text = _git_diff_all(self.project_root)

        resulting_diff_hash = diff_hash(diff_text)
        diff_summary = truncate_text(diff_text, 2000)
        diff_omitted = not bool(diff_text)
        diff_truncated = len(diff_text) > len(diff_summary)
        file_signatures: dict[str, Any] = {}
        for file_path in files:
            abs_path = Path(self.project_root) / file_path
            if not abs_path.exists() or not abs_path.is_file():
                file_signatures[file_path] = {"exists": False}
                continue
            try:
                file_signatures[file_path] = {"exists": True, **text_signature(_read_text_file(abs_path))}
            except Exception:
                file_signatures[file_path] = {"exists": True, "readable": False}

        version = load_current_version(self.project_root)
        now_ts = self._store.now_iso()
        operation = self._preview_operation(preview_data, mode)
        post_executor_patch_evidence = build_post_executor_patch_evidence(
            version=version,
            tool="manage_project_patch",
            preview_id=preview_id,
            files_changed=list(files),
            operation=operation,
            applied_at=now_ts,
            file_signatures=file_signatures,
        )
        reason = params.get("reason")
        manual_acceptance = detect_manual_acceptance(reason)

        return apply_result(
            "apply",
            preview_id,
            changed_files=files,
            diff_summary=diff_summary,
            diff_hash=resulting_diff_hash,
            diff_omitted=diff_omitted,
            diff_truncated=diff_truncated,
            file_signatures=file_signatures,
            warnings=[],
            recommended_next_action="manage_git_commit.readiness",
            post_executor_patch_evidence=post_executor_patch_evidence,
            manual_acceptance_evidence=manual_acceptance,
        )

    def status(self, params: dict[str, Any]) -> dict[str, Any]:
        preview_id = params.get("preview_id")
        if not isinstance(preview_id, str) or not preview_id.strip():
            return error_result("INVALID_PREVIEW_ID", "status 需要非空 preview_id。")
        preview_id = preview_id.strip()

        preview_data = self._read_preview(preview_id)
        if preview_data is None:
            return error_result("PREVIEW_NOT_FOUND", f"preview 不存在：{preview_id}")

        expires_at = preview_data.get("expires_at", "")
        expired = self._store.is_expired(preview_data)

        result = status_result(
            "status",
            preview_id,
            exists=True,
            expired=expired,
            expires_at=expires_at,
            created_at=preview_data.get("created_at", ""),
            mode=preview_data.get("mode", ""),
            changed_files=preview_data.get("files", []),
            diff_hash=preview_data.get("predicted_diff_hash", ""),
            warnings=preview_data.get("warnings", []),
        )

        # Core confirmation enrichment (additive, preserves all existing fields)
        fact = confirmation_fact_from_store(self._store, preview_id)
        if fact is not None:
            result["confirmation"] = fact.to_dict()

        return result

    def _normalize_and_validate_path(self, raw_path: str) -> str | dict:
        try:
            self.source_review.validate_project_file_for_patch(self.project_root, raw_path)
            # Re-normalize to get the clean relative path
            normalized = self.source_review._normalize_repo_relative_path(raw_path)
            if normalized is None:
                return error_result("PATH_NOT_ALLOWED", "路径必须是项目内相对路径。")
            return normalized
        except SourceReviewError as e:
            return error_result("PATH_NOT_ALLOWED", str(e))

    def _preview_creates_file(self, preview_data: dict[str, Any]) -> bool:
        return self._preview_operation(preview_data, str(preview_data.get("mode", ""))) == "create_file"

    def _preview_operation(self, preview_data: dict[str, Any], fallback: str) -> str:
        if preview_data.get("create_files"):
            return "create_file"
        if preview_data.get("delete_files"):
            return "delete_file"
        if preview_data.get("mode") == "exact_replace":
            operations = [
                spec.get("operation") for spec in preview_data.get("exact_specs", [])
                if isinstance(spec, dict) and spec.get("operation")
            ]
            if len(set(operations)) == 1:
                return str(operations[0])
        return fallback

    _HUNK_HEADER_RE = re.compile(r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@")

    def _parse_unified_diff_files(self, patch_text: str) -> list[str]:
        files: list[str] = []
        previous_header = ""
        for line in patch_text.splitlines():
            if line.startswith("diff --git "):
                parts = line.split()
                if len(parts) >= 4:
                    b_path = self._clean_diff_path(parts[3])
                    if b_path and b_path not in files:
                        files.append(b_path)
                previous_header = ""
                continue
            if line.startswith("--- "):
                previous_header = line[4:].strip().split("\t", 1)[0]
                continue
            if line.startswith("+++ "):
                to_path = line[4:].strip().split("\t", 1)[0]
                path = self._clean_diff_path(to_path)
                if not path and previous_header and previous_header != "/dev/null":
                    path = self._clean_diff_path(previous_header)
                if path and path not in files:
                    files.append(path)
                previous_header = ""
        return files

    def _clean_diff_path(self, raw_path: str) -> str:
        path = raw_path.strip().strip('"')
        if not path or path == "/dev/null":
            return ""
        if path.startswith("a/") or path.startswith("b/"):
            path = path[2:]
        return path

    def _apply_unified_diff_text(self, patch_text: str, expected_files: list[str]) -> None | dict:
        sections = self._split_diff_by_file(patch_text)
        for file_path, file_diff in sections:
            if file_path not in expected_files:
                continue

            abs_path = Path(self.project_root) / file_path
            is_create = self._is_unified_diff_create(file_diff)
            if is_create:
                if abs_path.exists():
                    return error_result("FILE_ALREADY_EXISTS", f"patch 标记为创建新文件，但 {file_path} 已存在。")
                content = ""
            else:
                if not abs_path.exists():
                    return error_result("FILE_NOT_FOUND", f"apply 时文件不存在：{file_path}")

                try:
                    content = _read_text_file(abs_path)
                except Exception as e:
                    return error_result("FILE_READ_ERROR", f"读取 {file_path} 失败：{e}")

            new_content = self._apply_hunks_to_content(content, file_diff)
            if isinstance(new_content, dict):
                return new_content

            if is_create:
                abs_path.parent.mkdir(parents=True, exist_ok=True)
            abs_path.write_text(new_content, encoding="utf-8")

        return None

    def _sections_by_normalized_file(self, patch_text: str) -> dict[str, str]:
        return {file_path: file_diff for file_path, file_diff in self._split_diff_by_file(patch_text)}

    def _is_unified_diff_create(self, file_diff: str) -> bool:
        for line in file_diff.splitlines():
            if line.startswith("--- "):
                from_path = line[4:].strip().split("\t", 1)[0]
                return from_path == "/dev/null"
        return False

    def _split_diff_by_file(self, patch_text: str) -> list[tuple[str, str]]:
        sections: list[tuple[str, str]] = []
        current_file = ""
        current_lines: list[str] = []
        pending_lines: list[str] = []
        pending_from_path = ""

        def flush() -> None:
            nonlocal current_file, current_lines
            if current_file and current_lines:
                sections.append((current_file, "".join(current_lines)))
            current_file = ""
            current_lines = []

        for line in patch_text.splitlines(keepends=True):
            if line.startswith("diff --git "):
                flush()
                pending_lines = []
                pending_from_path = ""
                current_lines = [line]
                parts = line.split()
                current_file = self._clean_diff_path(parts[3]) if len(parts) >= 4 else ""
                continue
            if line.startswith("--- "):
                if current_file and current_lines:
                    current_lines.append(line)
                else:
                    pending_lines = [line]
                pending_from_path = line[4:].strip().split("\t", 1)[0]
                continue
            if line.startswith("+++ "):
                if current_file:
                    current_lines.append(line)
                else:
                    to_path = line[4:].strip().split("\t", 1)[0]
                    current_file = self._clean_diff_path(to_path)
                    if not current_file and pending_from_path != "/dev/null":
                        current_file = self._clean_diff_path(pending_from_path)
                    current_lines = [*pending_lines, line]
                    pending_lines = []
                    pending_from_path = ""
                continue
            if current_file:
                current_lines.append(line)
            elif pending_lines:
                pending_lines.append(line)

        flush()

        return sections

    def _apply_hunks_to_content(self, content: str, file_diff: str) -> str | dict:
        lines = content.splitlines(keepends=True)

        hunks = self._extract_hunks(file_diff)
        if not hunks:
            return content

        for hunk_header, hunk_body in hunks:
            match = self._HUNK_HEADER_RE.match(hunk_header)
            if not match:
                return error_result("INVALID_HUNK_HEADER", f"无法解析 hunk 头：{hunk_header.strip()}")

            old_start = int(match.group(1))
            old_count = int(match.group(2) or 1)
            new_start_text = match.group(3)
            new_count_text = match.group(4)

            new_lines: list[str] = []
            for hline in hunk_body:
                if hline.startswith("+") and not hline.startswith("+++"):
                    new_lines.append(hline[1:])
                elif hline.startswith(" ") or (hline.startswith("\t") and not hline.startswith("---")):
                    new_lines.append(hline[1:] if hline.startswith(" ") else hline)
                elif hline.startswith("-") and not hline.startswith("---"):
                    pass
                else:
                    new_lines.append(hline)

            old_idx = old_start - 1
            before = lines[:old_idx]
            after = lines[old_idx + old_count:]
            lines = before + new_lines + after

        return "".join(lines)

    def _extract_hunks(self, file_diff: str) -> list[tuple[str, list[str]]]:
        hunks: list[tuple[str, list[str]]] = []
        current_header = ""
        current_body: list[str] = []

        for line in file_diff.splitlines(keepends=True):
            if line.startswith("@@"):
                if current_header and current_body:
                    hunks.append((current_header, current_body))
                current_header = line
                current_body = []
            elif current_header:
                current_body.append(line)

        if current_header and current_body:
            hunks.append((current_header, current_body))

        return hunks

    def _write_preview(self, preview_id: str, data: dict[str, Any]) -> None:
        self._store.write(preview_id, data)

    def _read_preview(self, preview_id: str) -> dict[str, Any] | None:
        return self._store.read(preview_id)
