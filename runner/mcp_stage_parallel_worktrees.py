from __future__ import annotations

import hashlib
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from typing import Any

from runner.confirmation_store import ConfirmationStore
from runner.core_confirmation import confirmation_apply_guard, confirmation_fact_from_store
from runner.runner_paths import resolve_project_runner_rel_dir
from runner.stage_parallel_plan import build_stage_parallel_worktree_assignment_preview
from runner.tool_result import apply_result, error_result, ok_result, preview_result, status_result


PREVIEW_TTL_SECONDS = 1800
PREVIEWS_RELATIVE_DIR = os.path.join("runtime", "stage-parallel-worktree-previews")
_SAFE_BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]{1,120}$")


class MCPStageParallelWorktreeManager:
    def __init__(self, project_root: str):
        self.project_root = os.path.abspath(os.path.expanduser(project_root))
        preview_dir = os.path.join(resolve_project_runner_rel_dir(self.project_root), PREVIEWS_RELATIVE_DIR)
        self._store = ConfirmationStore(self.project_root, preview_dir, PREVIEW_TTL_SECONDS)

    def handle(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        if action == "preview":
            return self._preview(params)
        if action == "apply":
            return self._apply(params)
        if action == "status":
            return self._status(params)
        if action == "discard":
            return self._discard(params)
        return error_result("UNKNOWN_ACTION", "不支持的 action。支持：preview、apply、status、discard。")

    def _preview(self, params: dict[str, Any]) -> dict[str, Any]:
        assignment_preview = build_stage_parallel_worktree_assignment_preview(
            project_root=self.project_root,
            project_name=params.get("project_name") if isinstance(params.get("project_name"), str) else None,
            stage_id=params.get("stage_id") if isinstance(params.get("stage_id"), str) else None,
            task_intents=params.get("task_intents") if isinstance(params.get("task_intents"), list) else None,
            max_parallel_tasks=params.get("max_parallel_tasks") if isinstance(params.get("max_parallel_tasks"), int) else None,
            provider=params.get("provider") if isinstance(params.get("provider"), str) else None,
            base_branch=params.get("base_branch") if isinstance(params.get("base_branch"), str) else None,
        )
        base_branch = str(assignment_preview.get("base_branch") or "main")
        git_state = self._collect_git_state(base_branch)
        assignments = self._assignments(assignment_preview)
        blockers = self._preview_blockers(assignment_preview, git_state, assignments)
        operations = self._planned_operations(assignments)
        can_apply = bool(operations) and not blockers

        if not can_apply:
            return ok_result(
                "preview",
                status="blocked" if blockers else "empty",
                risk_level="blocked" if blockers else "none",
                can_apply=False,
                read_only=False,
                side_effects=False,
                side_effect_scope="none",
                project_root=self.project_root,
                assignment_preview=assignment_preview,
                git_state=git_state,
                planned_operations=operations,
                blockers=blockers,
                authority_boundary=self._authority_boundary(preview_only=True),
                message="worktree assignment preview 存在阻断项，未生成 preview_id。",
            )

        preview_id = self._generate_preview_id()
        created_at = self._now_iso()
        expires_at = self._expires_at()
        reason = params.get("reason")
        preview_record = {
            "preview_id": preview_id,
            "artifact_kind": "stage_parallel_worktree_apply_preview",
            "action": "manage_stage_parallel_worktrees.apply",
            "tool": "manage_stage_parallel_worktrees",
            "params": {"action": "apply", "preview_id": preview_id},
            "project_root": self.project_root,
            "stage_id": assignment_preview.get("stage_id"),
            "parallel_group_id": assignment_preview.get("parallel_group_id"),
            "base_branch": base_branch,
            "assignment_preview": assignment_preview,
            "git_state": git_state,
            "planned_operations": operations,
            "created_at": created_at,
            "expires_at": expires_at,
            "reason": reason.strip() if isinstance(reason, str) and reason.strip() else "",
            "requires_confirmation": True,
        }
        self._store.write(preview_id, preview_record)

        return preview_result(
            "preview",
            preview_id,
            status="preview_ready",
            risk_level="commit",
            can_apply=True,
            read_only=False,
            side_effects=True,
            side_effect_scope="preview_artifact_only",
            project_root=self.project_root,
            stage_id=assignment_preview.get("stage_id"),
            parallel_group_id=assignment_preview.get("parallel_group_id"),
            base_branch=base_branch,
            git_state=git_state,
            planned_operations=operations,
            created_at=created_at,
            expires_at=expires_at,
            authority_boundary=self._authority_boundary(preview_only=True),
            recommended_next_action={
                "tool": "manage_stage_parallel_worktrees",
                "action": "apply",
                "params": {"action": "apply", "preview_id": preview_id},
                "reason": "使用 preview_id 创建隔离 git worktrees；不会启动 executor。",
                "requires_confirmation": True,
            },
            next_actions=[
                {
                    "tool": "manage_stage_parallel_worktrees",
                    "action": "discard",
                    "params": {"action": "discard", "preview_id": preview_id},
                    "reason": "废弃此 worktree preview，不创建 worktree。",
                    "requires_confirmation": True,
                }
            ],
        )

    def _apply(self, params: dict[str, Any]) -> dict[str, Any]:
        preview_id = params.get("preview_id")
        if not isinstance(preview_id, str) or not preview_id.strip():
            return error_result("PREVIEW_ID_REQUIRED", "apply 需要 preview_id。请先调用 preview。")
        preview_id = preview_id.strip()

        guard = confirmation_apply_guard(self._store, preview_id, project_root=self.project_root)
        if not guard["ok"]:
            error_code = str(guard.get("error_code") or "PREVIEW_INVALID")
            if error_code == "PREVIEW_EXPIRED":
                self._store.delete(preview_id)
            return error_result(error_code, self._guard_message(error_code), preview_id=preview_id)
        preview = guard["payload"]
        if preview.get("artifact_kind") != "stage_parallel_worktree_apply_preview":
            return error_result("PREVIEW_KIND_MISMATCH", "preview_id 类型不是 stage parallel worktree apply。", preview_id=preview_id)

        validation = self._validate_apply_state(preview)
        if validation:
            return error_result(
                "APPLY_STATE_MISMATCH",
                "当前 Git/worktree 状态与 preview 不一致，已阻断 apply。",
                preview_id=preview_id,
                blockers=validation,
                authority_boundary=self._authority_boundary(preview_only=False),
            )

        created: list[dict[str, Any]] = []
        for operation in self._stored_operations(preview):
            branch_name = str(operation.get("branch_name") or "")
            worktree_path = str(operation.get("worktree_path") or "")
            base_branch = str(operation.get("base_branch") or preview.get("base_branch") or "main")
            os.makedirs(os.path.dirname(worktree_path), exist_ok=True)
            result = self._git(["worktree", "add", "-b", branch_name, worktree_path, base_branch], timeout=120)
            if result["code"] != 0:
                return error_result(
                    "GIT_WORKTREE_ADD_FAILED",
                    "git worktree add 执行失败。",
                    preview_id=preview_id,
                    failed_operation=operation,
                    created_worktrees=created,
                    stderr=result.get("stderr", "")[:4000],
                    authority_boundary=self._authority_boundary(preview_only=False),
                )
            created.append(
                {
                    "task_id": operation.get("task_id"),
                    "branch_name": branch_name,
                    "worktree_path": worktree_path,
                    "base_branch": base_branch,
                }
            )

        self._store.delete(preview_id)
        return apply_result(
            "apply",
            preview_id,
            status="succeeded",
            risk_level="commit",
            read_only=False,
            side_effects=True,
            side_effect_scope="git_worktree_creation_only",
            project_root=self.project_root,
            created_count=len(created),
            created_worktrees=created,
            message=f"已创建 {len(created)} 个隔离 git worktree；未启动 executor。",
            authority_boundary=self._authority_boundary(preview_only=False),
            next_actions=[
                {
                    "tool": "get_stage_parallel_executor_group_preview",
                    "arguments": {"stage_id": preview.get("stage_id")},
                    "reason": "读取下一步 executor preview group；此 apply 未启动 executor。",
                    "requires_confirmation": False,
                },
                {
                    "tool": "get_stage_parallel_group_status",
                    "arguments": {"stage_id": preview.get("stage_id")},
                    "reason": "跟踪并行 group 状态。",
                    "requires_confirmation": False,
                },
            ],
        )

    def _status(self, params: dict[str, Any]) -> dict[str, Any]:
        preview_id = params.get("preview_id")
        if not isinstance(preview_id, str) or not preview_id.strip():
            return error_result("PREVIEW_ID_REQUIRED", "status 需要 preview_id。")
        preview_id = preview_id.strip()
        preview = self._store.read(preview_id)
        if preview is None:
            return error_result("PREVIEW_NOT_FOUND", f"preview_id={preview_id} 不存在或已过期。")
        blockers = []
        if self._store.is_expired(preview):
            blockers.append({"code": "PREVIEW_EXPIRED", "message": "preview 已过期，请重新生成。"})
        else:
            blockers = self._validate_apply_state(preview)
        result = status_result(
            "status",
            preview_id,
            status="blocked" if blockers else "preview_ready",
            risk_level="blocked" if blockers else "commit",
            project_root=self.project_root,
            stage_id=preview.get("stage_id"),
            parallel_group_id=preview.get("parallel_group_id"),
            created_at=preview.get("created_at"),
            expires_at=preview.get("expires_at"),
            can_apply=not blockers,
            blockers=blockers,
            planned_operations=preview.get("planned_operations", []),
            authority_boundary=self._authority_boundary(preview_only=True),
        )
        fact = confirmation_fact_from_store(self._store, preview_id)
        if fact is not None:
            result["confirmation"] = fact.to_dict()
        return result

    def _discard(self, params: dict[str, Any]) -> dict[str, Any]:
        preview_id = params.get("preview_id")
        if not isinstance(preview_id, str) or not preview_id.strip():
            return error_result("PREVIEW_ID_REQUIRED", "discard 需要 preview_id。")
        preview_id = preview_id.strip()
        preview = self._store.read(preview_id)
        if preview is None:
            return error_result("PREVIEW_NOT_FOUND", f"preview_id={preview_id} 不存在或已过期。")
        if preview.get("project_root") != self.project_root:
            return error_result("PROJECT_MISMATCH", "preview 与当前项目不匹配。", preview_id=preview_id)
        self._store.delete(preview_id)
        return ok_result(
            "discard",
            preview_id=preview_id,
            status="succeeded",
            message=f"已废弃 worktree preview_id={preview_id}；未创建 worktree。",
        )

    def _preview_blockers(
        self,
        assignment_preview: dict[str, Any],
        git_state: dict[str, Any],
        assignments: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        blockers: list[dict[str, Any]] = []
        for source in (assignment_preview.get("blocking_reasons"), git_state.get("blockers")):
            if isinstance(source, list):
                blockers.extend(item for item in source if isinstance(item, dict))
        for assignment in assignments:
            branch_name = str(assignment.get("branch_name") or "")
            branch_blocker = self._branch_blocker(branch_name)
            if branch_blocker:
                blocker = dict(branch_blocker)
                blocker["task_id"] = assignment.get("task_id")
                blockers.append(blocker)
        return blockers

    def _validate_apply_state(self, preview: dict[str, Any]) -> list[dict[str, Any]]:
        blockers: list[dict[str, Any]] = []
        base_branch = str(preview.get("base_branch") or "main")
        current = self._collect_git_state(base_branch)
        if current.get("blockers"):
            blockers.extend(item for item in current.get("blockers", []) if isinstance(item, dict))
        expected_git = preview.get("git_state") if isinstance(preview.get("git_state"), dict) else {}
        for key, code in (
            ("head", "GIT_HEAD_CHANGED"),
            ("current_branch", "GIT_BRANCH_CHANGED"),
            ("status_hash", "GIT_STATUS_CHANGED"),
            ("base_branch_head", "BASE_BRANCH_HEAD_CHANGED"),
        ):
            if current.get(key) != expected_git.get(key):
                blockers.append(
                    {
                        "code": code,
                        "message": f"{key} 与 preview 时不一致。",
                        "expected": expected_git.get(key),
                        "actual": current.get(key),
                    }
                )
        for operation in self._stored_operations(preview):
            path = str(operation.get("worktree_path") or "")
            branch_name = str(operation.get("branch_name") or "")
            if not self._path_within_parallel_root(path):
                blockers.append({"code": "WORKTREE_PATH_OUTSIDE_PROJECT_RUNTIME", "worktree_path": path})
            if os.path.exists(path):
                blockers.append({"code": "WORKTREE_PATH_ALREADY_EXISTS", "worktree_path": path})
            branch_blocker = self._branch_blocker(branch_name)
            if branch_blocker:
                blockers.append({**branch_blocker, "branch_name": branch_name})
        return blockers

    def _collect_git_state(self, base_branch: str) -> dict[str, Any]:
        inside = self._git(["rev-parse", "--is-inside-work-tree"])
        if inside["code"] != 0 or inside["stdout"].strip().lower() != "true":
            return {"ok": False, "blockers": [{"code": "NOT_A_GIT_WORKTREE", "message": "项目不是 Git worktree。"}]}
        branch = self._git(["rev-parse", "--abbrev-ref", "HEAD"])
        head = self._git(["rev-parse", "HEAD"])
        base = self._git(["rev-parse", "--verify", base_branch])
        status = self._git(["status", "--short", "--untracked-files=all"])
        blockers: list[dict[str, Any]] = []
        if branch["code"] != 0:
            blockers.append({"code": "CURRENT_BRANCH_UNAVAILABLE", "message": "无法读取当前 branch。"})
        if head["code"] != 0:
            blockers.append({"code": "CURRENT_HEAD_UNAVAILABLE", "message": "无法读取当前 HEAD。"})
        if base["code"] != 0:
            blockers.append({"code": "BASE_BRANCH_UNAVAILABLE", "message": f"base_branch 不可用：{base_branch}"})
        status_lines = [line for line in status["stdout"].splitlines() if line.strip()]
        blocking_status = [line for line in status_lines if not self._is_ignored_runtime_status(line)]
        if blocking_status:
            blockers.append(
                {
                    "code": "WORKTREE_NOT_CLEAN",
                    "message": "创建并行 worktree 前需要干净的目标 checkout（忽略 .colameta/runtime 产物）。",
                    "status_short": blocking_status[:50],
                }
            )
        return {
            "ok": not blockers,
            "current_branch": branch["stdout"].strip() if branch["code"] == 0 else None,
            "head": head["stdout"].strip() if head["code"] == 0 else None,
            "base_branch": base_branch,
            "base_branch_head": base["stdout"].strip() if base["code"] == 0 else None,
            "status_short": blocking_status,
            "ignored_runtime_status_short": [line for line in status_lines if self._is_ignored_runtime_status(line)],
            "status_hash": self._status_hash(blocking_status),
            "blockers": blockers,
        }

    def _branch_blocker(self, branch_name: str) -> dict[str, Any] | None:
        if not branch_name or not _SAFE_BRANCH_RE.fullmatch(branch_name):
            return {"code": "INVALID_PARALLEL_BRANCH_NAME", "message": "branch name 不安全。"}
        check = self._git(["check-ref-format", "--branch", branch_name])
        if check["code"] != 0:
            return {"code": "INVALID_PARALLEL_BRANCH_NAME", "message": "git check-ref-format 未通过。"}
        exists = self._git(["show-ref", "--verify", "--quiet", f"refs/heads/{branch_name}"])
        if exists["code"] == 0:
            return {"code": "PARALLEL_BRANCH_ALREADY_EXISTS", "message": "目标 branch 已存在。"}
        return None

    def _planned_operations(self, assignments: list[dict[str, Any]]) -> list[dict[str, Any]]:
        operations: list[dict[str, Any]] = []
        for assignment in assignments:
            if assignment.get("assignment_status") != "assignable":
                continue
            operations.append(
                {
                    "task_id": assignment.get("task_id"),
                    "branch_name": assignment.get("branch_name"),
                    "worktree_path": assignment.get("worktree_path"),
                    "base_branch": assignment.get("base_branch") or "main",
                    "command_preview": "git worktree add -b <branch_name> <worktree_path> <base_branch>",
                }
            )
        return operations

    def _stored_operations(self, preview: dict[str, Any]) -> list[dict[str, Any]]:
        value = preview.get("planned_operations")
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, dict)]

    def _assignments(self, assignment_preview: dict[str, Any]) -> list[dict[str, Any]]:
        value = assignment_preview.get("worktree_assignments")
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, dict)]

    def _path_within_parallel_root(self, path: str) -> bool:
        parallel_root = os.path.join(self.project_root, ".colameta", "runtime", "parallel-worktrees")
        try:
            return os.path.commonpath([os.path.abspath(path), parallel_root]) == os.path.abspath(parallel_root)
        except ValueError:
            return False

    def _is_ignored_runtime_status(self, line: str) -> bool:
        path = line[3:].strip() if len(line) > 3 else line.strip()
        paths = [part.strip() for part in path.split(" -> ")]
        return bool(paths) and all(
            item == ".colameta/runtime"
            or item.startswith(".colameta/runtime/")
            for item in paths
        )

    def _status_hash(self, lines: list[str]) -> str:
        raw = "\n".join(lines)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _git(self, args: list[str], *, timeout: int = 30) -> dict[str, Any]:
        try:
            proc = subprocess.run(
                ["git", *args],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return {"code": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}
        except FileNotFoundError:
            return {"code": 127, "stdout": "", "stderr": "git 命令不可用"}
        except Exception as exc:
            return {"code": 1, "stdout": "", "stderr": str(exc)}

    def _authority_boundary(self, *, preview_only: bool) -> dict[str, bool]:
        return {
            "does_not_authorize_executor_run": True,
            "does_not_create_executor_preview": True,
            "does_not_start_background_worker": True,
            "does_not_merge_parallel_results": True,
            "does_not_commit": True,
            "does_not_push": True,
            "does_not_replace_stable_service": True,
            "does_not_write_delivery_accepted": True,
            "does_not_create_review_decision": True,
            "does_not_emit_gate_event": True,
            "does_not_create_branch_or_worktree": preview_only,
            "creates_branch_or_worktree_only_on_apply": not preview_only,
        }

    def _generate_preview_id(self) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        return f"stage_parallel_worktrees_{ts}_{os.urandom(4).hex()}"

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).astimezone().isoformat()

    def _expires_at(self) -> str:
        return (datetime.now(timezone.utc) + timedelta(seconds=PREVIEW_TTL_SECONDS)).astimezone().isoformat()

    def _guard_message(self, error_code: str) -> str:
        return {
            "PREVIEW_NOT_FOUND": "preview_id 不存在或已过期。请重新调用 preview。",
            "PROJECT_MISMATCH": "preview 与当前项目不匹配。",
            "PREVIEW_EXPIRED": "preview 已过期，请重新生成。",
        }.get(error_code, "preview 无效。")
