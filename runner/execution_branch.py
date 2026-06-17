import os
import json
import re
from datetime import datetime
from pathlib import Path

from runner._internal_utils import run_git as _run_git_impl
from runner.executor_registry import is_supported_execution_provider
from runner.workspace import ProjectWorkspace

EXECUTION_BRANCH_FILE = "execution-branch.json"


class ExecutionBranchError(RuntimeError):
    pass


class ExecutionBranchController:
    def __init__(self, project_root: str):
        self.project_root = os.path.abspath(os.path.expanduser(project_root))
        self.workspace = ProjectWorkspace.from_project_path(self.project_root)
        self.manifest_path = os.path.join(self.workspace.runtime_dir, EXECUTION_BRANCH_FILE)

    def _run_git(self, args: list[str]) -> tuple[int, str, str]:
        return _run_git_impl(args, self.project_root)

    def _is_git_repo(self) -> bool:
        code, out, _ = self._run_git(["rev-parse", "--is-inside-work-tree"])
        return code == 0 and out.strip() == "true"

    def _current_branch(self) -> str:
        code, out, _ = self._run_git(["rev-parse", "--abbrev-ref", "HEAD"])
        if code != 0:
            raise ExecutionBranchError("无法读取当前分支。")
        branch = out.strip()
        if branch == "HEAD":
            raise ExecutionBranchError("当前处于 HEAD detached 状态，请在主分支操作。")
        return branch

    def _current_head(self) -> str:
        code, out, _ = self._run_git(["rev-parse", "HEAD"])
        if code != 0:
            raise ExecutionBranchError("无法读取 HEAD。")
        return out.strip()

    def _status_porcelain(self) -> str:
        code, out, _ = self._run_git(["status", "--porcelain"])
        if code != 0:
            raise ExecutionBranchError("无法读取工作区状态。")
        return out.strip()

    def _branch_exists(self, branch_name: str) -> bool:
        code, _, _ = self._run_git(["rev-parse", "--verify", "--quiet", f"refs/heads/{branch_name}"])
        return code == 0

    def _load_manifest(self) -> dict | None:
        if not os.path.isfile(self.manifest_path):
            return None
        try:
            return json.loads(Path(self.manifest_path).read_text(encoding="utf-8"))
        except Exception:
            return None

    def _safe_version(self, version: str) -> str:
        sanitized = re.sub(r"[^a-zA-Z0-9._-]", "-", version).strip("-")
        return sanitized or "version"

    def get_status(self) -> dict:
        if not self._is_git_repo():
            return {"ok": False, "message": "当前项目不是 Git 仓库。"}

        try:
            current_branch = self._current_branch()
            current_head = self._current_head()
            porcelain = self._status_porcelain()
            worktree_clean = len(porcelain) == 0
        except ExecutionBranchError as e:
            return {"ok": True, "active": False, "manifest_file": self.manifest_path,
                    "current_branch": None, "current_head": None, "worktree_clean": None,
                    "message": str(e)}

        manifest = self._load_manifest()
        if manifest is None:
            return {"ok": True, "active": False, "manifest_file": self.manifest_path,
                    "current_branch": current_branch, "current_head": current_head,
                    "worktree_clean": worktree_clean,
                    "message": "当前没有执行安全分支记录。"}

        branch_name = manifest.get("branch_name", "")
        on_execution_branch = current_branch == branch_name
        active = bool(manifest.get("active", False))

        return {"ok": True, "active": active, "manifest_file": self.manifest_path,
                "manifest": manifest, "current_branch": current_branch,
                "current_head": current_head, "on_execution_branch": on_execution_branch,
                "worktree_clean": worktree_clean}

    def validate_execution_ready(
        self,
        *,
        version: str,
        provider: str,
        require_branch: bool,
    ) -> dict:
        if not require_branch:
            return {"ok": True, "required": False, "message": "当前执行不要求安全分支。"}

        status = self.get_status()
        if not status.get("ok"):
            return {"ok": False, "required": True, "error_code": "EXECUTION_BRANCH_STATUS_ERROR",
                    "message": f"无法读取执行安全分支状态：{status.get('message', '未知错误')}"}

        if not status.get("active"):
            return {"ok": False, "required": True, "error_code": "EXECUTION_BRANCH_REQUIRED",
                    "message": "当前版本使用覆盖执行器，但未检测到执行安全分支。请先运行 create-execution-branch 创建安全分支，然后切换到该分支后再运行。"}

        manifest = status.get("manifest") or {}
        branch_name = manifest.get("branch_name", "")

        if not status.get("on_execution_branch"):
            return {"ok": False, "required": True, "error_code": "EXECUTION_BRANCH_NOT_CURRENT",
                    "message": f"执行安全分支 {branch_name} 已存在但当前不在该分支。请先切换到 {branch_name} 后再运行。"}

        expected_version = version.strip()
        manifest_version = (manifest.get("version") or "").strip()
        if manifest_version != expected_version:
            return {"ok": False, "required": True, "error_code": "EXECUTION_BRANCH_VERSION_MISMATCH",
                    "message": f"当前安全分支属于版本 {manifest_version}，不是当前版本 {expected_version}。请创建对应版本的安全分支。"}

        expected_provider = provider.strip().lower()
        manifest_provider = (manifest.get("provider") or "").strip().lower()
        if manifest_provider != expected_provider:
            return {"ok": False, "required": True, "error_code": "EXECUTION_BRANCH_PROVIDER_MISMATCH",
                    "message": f"当前安全分支执行器为 {manifest_provider}，但当前版本执行器为 {expected_provider}。请创建对应执行器的安全分支。"}

        manifest_project = manifest.get("project_root") or ""
        if manifest_project and os.path.abspath(manifest_project) != self.project_root:
            return {"ok": False, "required": True, "error_code": "EXECUTION_BRANCH_PROJECT_MISMATCH",
                    "message": "安全分支属于其他项目。"}

        return {
            "ok": True,
            "required": True,
            "status": "READY",
            "branch_name": branch_name,
            "version": manifest_version,
            "provider": manifest_provider,
            "message": "当前处于匹配的执行安全分支。",
        }

    def close_branch(
        self,
        *,
        status: str,
        note: str | None = None,
    ) -> dict:
        valid_statuses = ("passed", "failed", "abandoned")
        if status not in valid_statuses:
            return {"ok": False, "error_code": "INVALID_CLOSE_STATUS",
                    "message": f"不支持的关闭状态：{status}，仅支持 {', '.join(valid_statuses)}。"}

        manifest = self._load_manifest()
        if manifest is None:
            return {"ok": False, "error_code": "MANIFEST_NOT_FOUND",
                    "message": "未找到执行安全分支记录。"}
        if not manifest.get("active"):
            return {"ok": False, "error_code": "EXECUTION_BRANCH_NOT_ACTIVE",
                    "message": "当前执行安全分支记录不是 active 状态，无需关闭。"}

        try:
            current_branch = self._current_branch()
            current_head = self._current_head()
            porcelain = self._status_porcelain()
            worktree_clean = len(porcelain) == 0
        except ExecutionBranchError as e:
            return {"ok": False, "error_code": "GIT_STATUS_ERROR",
                    "message": f"读取当前 Git 状态失败：{e}"}

        branch_name = manifest.get("branch_name", "")
        on_execution_branch = current_branch == branch_name

        manifest["active"] = False
        manifest["closed"] = True
        manifest["closed_status"] = status
        manifest["closed_at"] = datetime.now().isoformat()
        manifest["closed_note"] = note
        manifest["closed_current_branch"] = current_branch
        manifest["closed_current_head"] = current_head
        manifest["closed_worktree_clean"] = worktree_clean
        manifest["closed_on_execution_branch"] = on_execution_branch

        try:
            with open(self.manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, ensure_ascii=False, indent=2)
                f.write("\n")
        except OSError as e:
            return {"ok": False, "error_code": "MANIFEST_WRITE_FAILED",
                    "message": f"写入 manifest 失败：{e}"}

        return {
            "ok": True,
            "status": "CLOSED",
            "closed_status": status,
            "branch_name": branch_name,
            "current_branch": current_branch,
            "on_execution_branch": on_execution_branch,
            "worktree_clean": worktree_clean,
            "manifest_file": self.manifest_path,
            "message": "执行安全分支记录已关闭。Runner 未合并、未删除分支。",
        }

    def get_review_summary(self) -> dict:
        if not self._is_git_repo():
            return {"ok": False, "error_code": "NOT_A_GIT_REPO", "message": "当前项目不是 Git 仓库。"}

        manifest = self._load_manifest()
        if manifest is None:
            return {"ok": False, "error_code": "MANIFEST_NOT_FOUND",
                    "message": "未找到执行安全分支记录。"}

        branch_name = manifest.get("branch_name", "")
        base_head = manifest.get("base_head", "")
        if not branch_name or not base_head:
            return {"ok": False, "error_code": "MANIFEST_INVALID",
                    "message": "执行安全分支记录缺少 branch_name 或 base_head。"}

        try:
            current_branch = self._current_branch()
            current_head = self._current_head()
            porcelain = self._status_porcelain()
            worktree_clean = len(porcelain) == 0
        except ExecutionBranchError as e:
            return {"ok": False, "error_code": "GIT_STATUS_ERROR",
                    "message": f"读取当前 Git 状态失败：{e}"}

        if current_branch != branch_name:
            return {"ok": False, "error_code": "EXECUTION_BRANCH_NOT_CURRENT",
                    "message": f"请先切换到执行安全分支 {branch_name} 后再查看审查摘要。"}

        try:
            name_status_code, name_status_out, ns_err = self._run_git(
                ["diff", "--name-status", base_head],
            )
            if name_status_code != 0:
                return {"ok": False, "error_code": "GIT_DIFF_FAILED",
                        "message": f"git diff --name-status 失败：{(ns_err or '').strip()[:300]}"}

            diff_stat_code, diff_stat_out, ds_err = self._run_git(
                ["diff", "--stat", base_head],
            )
            if diff_stat_code != 0:
                return {"ok": False, "error_code": "GIT_DIFF_FAILED",
                        "message": f"git diff --stat 失败：{(ds_err or '').strip()[:300]}"}

            untracked_code, untracked_out, ut_err = self._run_git(
                ["ls-files", "--others", "--exclude-standard"],
            )
        except Exception as e:
            return {"ok": False, "error_code": "GIT_STATUS_ERROR",
                    "message": f"读取 Git 状态失败：{e}"}

        changed_files: list[dict[str, str]] = []
        for line in name_status_out.splitlines():
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            status_char = parts[0].strip()
            if status_char.startswith("R"):
                if len(parts) >= 3:
                    changed_files.append({"status": status_char, "file": parts[2].strip(), "old_file": parts[1].strip()})
                else:
                    changed_files.append({"status": status_char, "file": parts[1].strip()})
            else:
                changed_files.append({"status": status_char, "file": parts[1].strip()})
            if len(changed_files) >= 300:
                break
        truncated = len(changed_files) >= 300

        diff_stat = diff_stat_out[:12000] if diff_stat_out else ""

        if untracked_code != 0:
            return {"ok": False, "error_code": "GIT_STATUS_ERROR",
                    "message": f"git ls-files --others 失败：{(ut_err or '').strip()[:300]}"}

        untracked_list: list[str] = []
        for line in untracked_out.splitlines():
            f = line.strip()
            if f:
                untracked_list.append(f)
                if len(untracked_list) >= 300:
                    break
        untracked_truncated = len(untracked_list) >= 300

        return {
            "ok": True,
            "manifest_file": self.manifest_path,
            "manifest": manifest,
            "version": manifest.get("version", ""),
            "provider": manifest.get("provider", ""),
            "branch_name": branch_name,
            "base_branch": manifest.get("base_branch", ""),
            "base_head": base_head,
            "current_branch": current_branch,
            "current_head": current_head,
            "on_execution_branch": True,
            "worktree_clean": worktree_clean,
            "changed_files": changed_files,
            "changed_file_count": len(changed_files),
            "truncated": truncated,
            "diff_stat": diff_stat,
            "untracked_files": untracked_list,
            "untracked_file_count": len(untracked_list),
            "untracked_truncated": untracked_truncated,
            "message": "已生成执行安全分支只读审查摘要。",
        }

    def create_branch(self, version: str, provider: str) -> dict:
        if not version or not version.strip():
            return {"ok": False, "error_code": "INVALID_VERSION", "message": "版本号不能为空。"}

        if not is_supported_execution_provider(provider):
            return {"ok": False, "error_code": "INVALID_PROVIDER",
                    "message": f"不支持的执行器：{provider}，仅支持 pi、codex、opencode。"}

        provider_key = provider.strip().lower()

        if not self._is_git_repo():
            return {"ok": False, "error_code": "NOT_A_GIT_REPO", "message": "当前项目不是 Git 仓库。"}

        try:
            base_branch = self._current_branch()
            base_head = self._current_head()
        except ExecutionBranchError as e:
            return {"ok": False, "error_code": "GIT_ERROR", "message": str(e)}

        porcelain = self._status_porcelain()
        if porcelain:
            return {"ok": False, "error_code": "DIRTY_WORKTREE",
                    "message": "Git 工作区不干净，请先提交或清理当前改动后再创建安全分支。"}

        existing_manifest = self._load_manifest()
        if existing_manifest is not None and existing_manifest.get("active"):
            existing_branch = existing_manifest.get("branch_name", "未知")
            return {"ok": False, "error_code": "ALREADY_ACTIVE",
                    "message": f"已有执行安全分支 {existing_branch} 处于 active 状态，请先处理后再创建新分支。"}

        safe_ver = self._safe_version(version.strip())
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        branch_name = f"runner/{safe_ver}-{provider_key}-{timestamp}"

        if self._branch_exists(branch_name):
            return {"ok": False, "error_code": "BRANCH_EXISTS",
                    "message": f"分支 {branch_name} 已存在，请重试。"}

        code, _, err = self._run_git(["checkout", "-b", branch_name])
        if code != 0:
            return {"ok": False, "error_code": "BRANCH_CREATE_FAILED",
                    "message": f"创建分支失败：{(err or '').strip()[:300]}"}

        os.makedirs(os.path.dirname(self.manifest_path), exist_ok=True)
        manifest = {
            "active": True,
            "created_at": datetime.now().isoformat(),
            "project_root": self.project_root,
            "version": version.strip(),
            "provider": provider_key,
            "branch_name": branch_name,
            "base_branch": base_branch,
            "base_head": base_head,
            "current_branch_at_create": base_branch,
            "notes": "Manual safety branch. Runner did not run executor, merge, reset, or delete branches.",
        }
        try:
            with open(self.manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, ensure_ascii=False, indent=2)
                f.write("\n")
        except OSError as e:
            return {"ok": False, "error_code": "MANIFEST_WRITE_FAILED",
                    "message": f"写入 manifest 失败：{e}"}

        return {
            "ok": True,
            "status": "CREATED",
            "version": version.strip(),
            "provider": provider_key,
            "branch_name": branch_name,
            "base_branch": base_branch,
            "base_head": base_head,
            "manifest_file": self.manifest_path,
            "message": "已创建执行安全分支，请在该分支运行当前版本。",
        }
