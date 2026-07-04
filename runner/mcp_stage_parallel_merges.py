from __future__ import annotations

import hashlib
import os
import subprocess
from datetime import datetime, timedelta, timezone
from typing import Any

from runner.confirmation_store import ConfirmationStore
from runner.core_confirmation import confirmation_apply_guard, confirmation_fact_from_store
from runner.runner_paths import resolve_project_runner_rel_dir
from runner.stage_parallel_executor_results import build_stage_parallel_executor_results_packet
from runner.stage_parallel_plan import build_stage_parallel_merge_preview
from runner.tool_result import apply_result, error_result, ok_result, preview_result, status_result


PREVIEW_TTL_SECONDS = 1800
PREVIEWS_RELATIVE_DIR = os.path.join("runtime", "stage-parallel-merge-previews")


class MCPStageParallelMergeManager:
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
        merge_preview, executor_results_source = self._build_merge_preview(params)
        target_branch = str(merge_preview.get("merge_plan", {}).get("target_branch") or params.get("base_branch") or "main")
        target_state = self._collect_target_state(target_branch)
        operations = self._planned_operations(merge_preview)
        blockers = self._preview_blockers(merge_preview, target_state, operations)
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
                stage_id=merge_preview.get("stage_id"),
                parallel_group_id=merge_preview.get("parallel_group_id"),
                executor_results_source=executor_results_source,
                merge_preview=merge_preview,
                target_state=target_state,
                planned_operations=operations,
                blockers=blockers,
                authority_boundary=self._authority_boundary(preview_only=True),
                message="stage parallel merge preview 存在阻断项，未生成 preview_id。",
            )

        preview_id = self._generate_preview_id()
        created_at = self._now_iso()
        expires_at = self._expires_at()
        reason = params.get("reason")
        preview_record = {
            "preview_id": preview_id,
            "artifact_kind": "stage_parallel_merge_apply_preview",
            "action": "manage_stage_parallel_merges.apply",
            "tool": "manage_stage_parallel_merges",
            "params": {"action": "apply", "preview_id": preview_id},
            "project_root": self.project_root,
            "stage_id": merge_preview.get("stage_id"),
            "parallel_group_id": merge_preview.get("parallel_group_id"),
            "target_branch": target_branch,
            "merge_preview": merge_preview,
            "executor_results_source": executor_results_source,
            "target_state": target_state,
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
            stage_id=merge_preview.get("stage_id"),
            parallel_group_id=merge_preview.get("parallel_group_id"),
            target_branch=target_branch,
            executor_results_source=executor_results_source,
            target_state=target_state,
            planned_operations=operations,
            created_at=created_at,
            expires_at=expires_at,
            authority_boundary=self._authority_boundary(preview_only=True),
            recommended_next_action={
                "tool": "manage_stage_parallel_merges",
                "action": "apply",
                "params": {"action": "apply", "preview_id": preview_id},
                "reason": "使用 preview_id 顺序执行本地 git merge；不会 push 或替换 stable。",
                "requires_confirmation": True,
            },
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
        if preview.get("artifact_kind") != "stage_parallel_merge_apply_preview":
            return error_result("PREVIEW_KIND_MISMATCH", "preview_id 类型不是 stage parallel merge apply。", preview_id=preview_id)

        blockers = self._validate_apply_state(preview)
        if blockers:
            return error_result(
                "APPLY_STATE_MISMATCH",
                "当前 Git/merge 状态与 preview 不一致，已阻断 apply。",
                preview_id=preview_id,
                blockers=blockers,
                authority_boundary=self._authority_boundary(preview_only=False),
            )

        merged: list[dict[str, Any]] = []
        for operation in self._stored_operations(preview):
            source_branch = str(operation.get("source_branch") or "")
            result = self._git(
                [
                    "-c",
                    "user.name=ColaMeta",
                    "-c",
                    "user.email=colameta@example.invalid",
                    "merge",
                    "--no-ff",
                    "--no-edit",
                    source_branch,
                ],
                timeout=180,
            )
            if result["code"] != 0:
                return error_result(
                    "GIT_MERGE_FAILED",
                    "git merge 执行失败；可能已留下冲突状态，需要人工处理。",
                    preview_id=preview_id,
                    failed_operation=operation,
                    merged_operations=merged,
                    git_output=self._short_git_output(result),
                    authority_boundary=self._authority_boundary(preview_only=False),
                )
            merged.append(
                {
                    "task_id": operation.get("task_id"),
                    "source_branch": source_branch,
                    "source_head": operation.get("source_head"),
                    "git_output": self._short_git_output(result),
                }
            )

        status_after = self._collect_target_state(str(preview.get("target_branch") or "main"))
        self._store.delete(preview_id)
        return apply_result(
            "apply",
            preview_id,
            status="succeeded",
            risk_level="commit",
            read_only=False,
            side_effects=True,
            side_effect_scope="local_git_merge_commits_only",
            project_root=self.project_root,
            stage_id=preview.get("stage_id"),
            parallel_group_id=preview.get("parallel_group_id"),
            target_branch=preview.get("target_branch"),
            merged_count=len(merged),
            merged_operations=merged,
            status_after=status_after,
            message=f"已顺序 merge {len(merged)} 个 parallel shard；未 push、未替换 stable。",
            authority_boundary=self._authority_boundary(preview_only=False),
            next_actions=[
                {
                    "tool": "get_stage_parallel_closeout_packet",
                    "arguments": {"executor_results": "<executor_results used for merge preview>"},
                    "reason": "生成只读 closeout packet；不写 Delivery accepted / ReviewDecision / GateEvent。",
                    "requires_confirmation": False,
                }
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
            target_branch=preview.get("target_branch"),
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
            message=f"已废弃 stage parallel merge preview_id={preview_id}；未执行 merge。",
        )

    def _build_merge_preview(self, params: dict[str, Any]) -> tuple[dict[str, Any], str]:
        executor_results = params.get("executor_results") if isinstance(params.get("executor_results"), list) else None
        source = "provided_executor_results"
        if executor_results is None:
            packet = build_stage_parallel_executor_results_packet(
                project_root=self.project_root,
                project_name=params.get("project_name") if isinstance(params.get("project_name"), str) else None,
                stage_id=params.get("stage_id") if isinstance(params.get("stage_id"), str) else None,
                task_intents=params.get("task_intents") if isinstance(params.get("task_intents"), list) else None,
                max_parallel_tasks=params.get("max_parallel_tasks") if isinstance(params.get("max_parallel_tasks"), int) else None,
                provider=params.get("provider") if isinstance(params.get("provider"), str) else None,
                base_branch=params.get("base_branch") if isinstance(params.get("base_branch"), str) else None,
            )
            executor_results = packet.get("executor_results") if isinstance(packet.get("executor_results"), list) else []
            source = "collected_executor_results_packet"
        return (
            build_stage_parallel_merge_preview(
                project_root=self.project_root,
                project_name=params.get("project_name") if isinstance(params.get("project_name"), str) else None,
                stage_id=params.get("stage_id") if isinstance(params.get("stage_id"), str) else None,
                task_intents=params.get("task_intents") if isinstance(params.get("task_intents"), list) else None,
                max_parallel_tasks=params.get("max_parallel_tasks") if isinstance(params.get("max_parallel_tasks"), int) else None,
                provider=params.get("provider") if isinstance(params.get("provider"), str) else None,
                base_branch=params.get("base_branch") if isinstance(params.get("base_branch"), str) else None,
                executor_results=executor_results,
            ),
            source,
        )

    def _preview_blockers(
        self,
        merge_preview: dict[str, Any],
        target_state: dict[str, Any],
        operations: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        blockers: list[dict[str, Any]] = []
        if merge_preview.get("status") != "preview_ready":
            merge_blockers = merge_preview.get("blocking_reasons")
            if isinstance(merge_blockers, list):
                blockers.extend(item for item in merge_blockers if isinstance(item, dict))
            if not blockers:
                blockers.append({"code": "MERGE_PREVIEW_NOT_READY"})
        blockers.extend(item for item in target_state.get("blockers", []) if isinstance(item, dict))
        if not operations and not blockers:
            blockers.append({"code": "NO_MERGE_OPERATIONS", "message": "没有可执行的 merge operation。"})
        for operation in operations:
            source_state = self._source_branch_state(operation)
            if source_state.get("blockers"):
                blockers.extend({**item, "task_id": operation.get("task_id")} for item in source_state.get("blockers", []))
        return blockers

    def _planned_operations(self, merge_preview: dict[str, Any]) -> list[dict[str, Any]]:
        sequence = merge_preview.get("merge_plan", {}).get("merge_sequence") if isinstance(merge_preview.get("merge_plan"), dict) else []
        operations = []
        if not isinstance(sequence, list):
            return operations
        for item in sequence:
            if not isinstance(item, dict):
                continue
            operations.append(
                {
                    "order": item.get("order"),
                    "task_id": item.get("task_id"),
                    "source_branch": item.get("source_branch"),
                    "source_worktree_path": item.get("source_worktree_path"),
                    "source_head": item.get("head"),
                    "changed_files": item.get("changed_files") if isinstance(item.get("changed_files"), list) else [],
                }
            )
        return operations

    def _validate_apply_state(self, preview: dict[str, Any]) -> list[dict[str, Any]]:
        target_state = self._collect_target_state(str(preview.get("target_branch") or "main"))
        blockers = []
        expected_state = preview.get("target_state") if isinstance(preview.get("target_state"), dict) else {}
        for key, code in (
            ("current_branch", "TARGET_BRANCH_CHANGED"),
            ("head", "TARGET_HEAD_CHANGED"),
            ("status_hash", "TARGET_STATUS_CHANGED"),
        ):
            if target_state.get(key) != expected_state.get(key):
                blockers.append({"code": code, "expected": expected_state.get(key), "actual": target_state.get(key)})
        blockers.extend(item for item in target_state.get("blockers", []) if isinstance(item, dict))
        expected_ops = self._stored_operations(preview)
        current_ops = []
        for operation in expected_ops:
            source_state = self._source_branch_state(operation)
            if source_state.get("blockers"):
                blockers.extend({**item, "task_id": operation.get("task_id")} for item in source_state.get("blockers", []))
            current_ops.append({**operation, "actual_source_head": source_state.get("head")})
            if source_state.get("head") != operation.get("source_head"):
                blockers.append(
                    {
                        "code": "SOURCE_BRANCH_HEAD_CHANGED",
                        "task_id": operation.get("task_id"),
                        "expected": operation.get("source_head"),
                        "actual": source_state.get("head"),
                    }
                )
        if self._operations_signature(expected_ops) != self._operations_signature(current_ops, actual_key="actual_source_head"):
            blockers.append({"code": "MERGE_OPERATIONS_CHANGED"})
        return blockers

    def _collect_target_state(self, target_branch: str) -> dict[str, Any]:
        inside = self._git(["rev-parse", "--is-inside-work-tree"])
        if inside["code"] != 0 or inside["stdout"].strip().lower() != "true":
            return {"ok": False, "blockers": [{"code": "NOT_A_GIT_WORKTREE"}]}
        branch = self._git(["rev-parse", "--abbrev-ref", "HEAD"])
        head = self._git(["rev-parse", "HEAD"])
        status = self._git(["status", "--short", "--untracked-files=all"])
        status_lines = [line for line in status["stdout"].splitlines() if line.strip()]
        blocking_status = [line for line in status_lines if not self._is_ignored_runtime_status(line)]
        blockers = []
        current_branch = branch["stdout"].strip() if branch["code"] == 0 else None
        if current_branch != target_branch:
            blockers.append({"code": "TARGET_BRANCH_MISMATCH", "expected": target_branch, "actual": current_branch})
        if head["code"] != 0:
            blockers.append({"code": "TARGET_HEAD_UNAVAILABLE"})
        if blocking_status:
            blockers.append({"code": "TARGET_WORKTREE_NOT_CLEAN", "status_short": blocking_status[:50]})
        return {
            "ok": not blockers,
            "current_branch": current_branch,
            "head": head["stdout"].strip() if head["code"] == 0 else None,
            "status_short": blocking_status,
            "ignored_runtime_status_short": [line for line in status_lines if self._is_ignored_runtime_status(line)],
            "status_hash": self._status_hash(blocking_status),
            "blockers": blockers,
        }

    def _source_branch_state(self, operation: dict[str, Any]) -> dict[str, Any]:
        branch = str(operation.get("source_branch") or "")
        if not branch:
            return {"ok": False, "blockers": [{"code": "SOURCE_BRANCH_MISSING"}]}
        head = self._git(["rev-parse", "--verify", branch])
        blockers = []
        if head["code"] != 0:
            blockers.append({"code": "SOURCE_BRANCH_UNAVAILABLE", "source_branch": branch})
        return {"ok": not blockers, "head": head["stdout"].strip() if head["code"] == 0 else None, "blockers": blockers}

    def _stored_operations(self, preview: dict[str, Any]) -> list[dict[str, Any]]:
        value = preview.get("planned_operations")
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, dict)]

    def _operations_signature(self, operations: list[dict[str, Any]], *, actual_key: str = "source_head") -> str:
        parts = []
        for operation in operations:
            parts.append(
                "|".join(
                    [
                        str(operation.get("order") or ""),
                        str(operation.get("task_id") or ""),
                        str(operation.get("source_branch") or ""),
                        str(operation.get(actual_key) or operation.get("source_head") or ""),
                    ]
                )
            )
        return hashlib.sha256("\n".join(sorted(parts)).encode("utf-8")).hexdigest()

    def _is_ignored_runtime_status(self, line: str) -> bool:
        path = line[3:].strip() if len(line) > 3 else line.strip()
        paths = [part.strip() for part in path.split(" -> ")]
        return bool(paths) and all(
            item == ".colameta/runtime"
            or item.startswith(".colameta/runtime/")
            for item in paths
        )

    def _status_hash(self, lines: list[str]) -> str:
        return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()

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

    def _short_git_output(self, result: dict[str, Any]) -> str:
        return (str(result.get("stdout") or "") + "\n" + str(result.get("stderr") or "")).strip()[:1000]

    def _authority_boundary(self, *, preview_only: bool) -> dict[str, bool]:
        return {
            "does_not_start_executor": True,
            "does_not_create_executor_preview": True,
            "does_not_create_branch_or_worktree": True,
            "does_not_merge_parallel_results": preview_only,
            "creates_local_merge_commits_on_apply": not preview_only,
            "does_not_push": True,
            "does_not_replace_stable_service": True,
            "does_not_write_delivery_accepted": True,
            "does_not_create_review_decision": True,
            "does_not_emit_gate_event": True,
        }

    def _generate_preview_id(self) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        return f"stage_parallel_merge_{ts}_{os.urandom(4).hex()}"

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
