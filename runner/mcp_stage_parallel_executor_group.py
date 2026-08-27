from __future__ import annotations

import hashlib
import os
import subprocess
from datetime import datetime, timedelta, timezone
from typing import Any

from runner.confirmation_store import ConfirmationStore
from runner.core_confirmation import confirmation_apply_guard, confirmation_fact_from_store
from runner.mcp_executor_workflow import MCPExecutorWorkflowManager
from runner.runner_paths import resolve_project_runner_rel_dir
from runner.stage_parallel_plan import build_stage_parallel_run_preview
from runner.stage_parallel_admission_lifecycle import (
    StageAdmissionLifecycleError,
    StageParallelAdmissionLifecycle,
)
from runner.tool_result import apply_result, error_result, ok_result, preview_result, status_result
from runner.work_item_governance.canonical import canonical_sha256


PREVIEW_TTL_SECONDS = 1800
PREVIEWS_RELATIVE_DIR = os.path.join("runtime", "stage-parallel-executor-group-previews")


class MCPStageParallelExecutorGroupManager:
    def __init__(self, project_root: str, *, attempt_bridge: Any | None = None):
        self.project_root = os.path.abspath(os.path.expanduser(project_root))
        preview_dir = os.path.join(resolve_project_runner_rel_dir(self.project_root), PREVIEWS_RELATIVE_DIR)
        self._store = ConfirmationStore(self.project_root, preview_dir, PREVIEW_TTL_SECONDS)
        self._lifecycle = (
            StageParallelAdmissionLifecycle(
                self.project_root,
                attempt_bridge=attempt_bridge,
                repository="JENN2046/colameta",
            )
            if attempt_bridge is not None
            else None
        )

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
        plan = self._build_plan(params)
        validations = self._validate_plan(plan)
        operations = self._planned_operations(plan, validations)
        blockers = self._preview_blockers(plan, validations, operations)
        can_apply = bool(operations) and not blockers

        task_authorizations = params.get("task_authorizations")
        if self._lifecycle is None:
            blockers.append(
                {
                    "code": "STAGE_ATTEMPT_GOVERNANCE_COMPOSITION_REQUIRED",
                    "message": "Stage lifecycle requires the authenticated narrow governance bridge.",
                }
            )
            can_apply = False

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
                parallel_group_id=plan.get("parallel_group_id"),
                run_preview=plan,
                validations=validations,
                planned_operations=operations,
                blockers=blockers,
                authority_boundary=self._authority_boundary(preview_only=True),
                message="executor group preview 存在阻断项，未生成 preview_id。",
            )

        preview_id = self._generate_preview_id()
        created_at = self._now_iso()
        expires_at = self._expires_at()
        reason = params.get("reason")
        preview_record = {
            "preview_id": preview_id,
            "artifact_kind": "stage_parallel_executor_group_apply_preview",
            "action": "manage_stage_parallel_executor_group.apply",
            "tool": "manage_stage_parallel_executor_group",
            "params": {"action": "apply", "preview_id": preview_id},
            "project_root": self.project_root,
            "stage_id": plan.get("stage_id"),
            "parallel_group_id": plan.get("parallel_group_id"),
            "provider": plan.get("provider"),
            "base_branch": plan.get("base_branch"),
            "run_preview": plan,
            "validations": validations,
            "planned_operations": operations,
            "lifecycle_spec": self._lifecycle_spec(plan, operations),
            "created_at": created_at,
            "expires_at": expires_at,
            "reason": reason.strip() if isinstance(reason, str) and reason.strip() else "",
            "requires_confirmation": True,
        }
        try:
            lifecycle = self._lifecycle.initialize(
                spec=preview_record["lifecycle_spec"],
                task_authorizations=task_authorizations,
            )
        except StageAdmissionLifecycleError as exc:
            return error_result(
                exc.code,
                str(exc),
                parallel_group_id=plan.get("parallel_group_id"),
                provider_started_count=0,
            )
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
            stage_id=plan.get("stage_id"),
            parallel_group_id=plan.get("parallel_group_id"),
            provider=plan.get("provider"),
            base_branch=plan.get("base_branch"),
            planned_operations=operations,
            created_at=created_at,
            expires_at=expires_at,
            authority_boundary=self._authority_boundary(preview_only=True),
            lifecycle=lifecycle,
            recommended_next_action={
                "tool": "manage_stage_parallel_executor_group",
                "action": "apply",
                "params": {"action": "apply", "preview_id": preview_id},
                "reason": "使用 preview_id 在每个隔离 worktree 内生成 executor run_once_preview；不会启动 executor。",
                "requires_confirmation": True,
            },
            next_actions=[
                {
                    "tool": "manage_stage_parallel_executor_group",
                    "action": "discard",
                    "params": {"action": "discard", "preview_id": preview_id},
                    "reason": "废弃此 executor group preview，不创建 executor preview artifacts。",
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
        if preview.get("artifact_kind") != "stage_parallel_executor_group_apply_preview":
            return error_result("PREVIEW_KIND_MISMATCH", "preview_id 类型不是 stage parallel executor group apply。", preview_id=preview_id)

        blockers = self._validate_apply_state(preview)
        if blockers:
            return error_result(
                "APPLY_STATE_MISMATCH",
                "当前 worktree/preflight 状态与 preview 不一致，已阻断 apply。",
                preview_id=preview_id,
                blockers=blockers,
                authority_boundary=self._authority_boundary(preview_only=False),
            )

        if self._lifecycle is None:
            return error_result(
                "STAGE_ATTEMPT_GOVERNANCE_COMPOSITION_REQUIRED",
                "Stage lifecycle requires the authenticated narrow governance bridge.",
                preview_id=preview_id,
            )
        try:
            lifecycle = self._lifecycle.advance(
                spec=preview["lifecycle_spec"],
                task_authorizations=params.get("task_authorizations"),
            )
        except StageAdmissionLifecycleError as exc:
            return error_result(
                exc.code,
                str(exc),
                preview_id=preview_id,
                provider_started_count=0,
                authority_boundary=self._authority_boundary(preview_only=False),
            )
        return apply_result(
            "apply",
            preview_id,
            status=lifecycle["status"],
            risk_level="preview",
            read_only=False,
            side_effects=True,
            side_effect_scope="stage_execution_preparation_only",
            project_root=self.project_root,
            stage_id=preview.get("stage_id"),
            parallel_group_id=preview.get("parallel_group_id"),
            lifecycle=lifecycle,
            provider_started_count=0,
            provider_start_authorized=False,
            message="Stage admission lifecycle advanced without starting an executor.",
            authority_boundary=self._authority_boundary(preview_only=False),
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
        lifecycle = None
        if not blockers and self._lifecycle is not None and isinstance(preview.get("lifecycle_spec"), dict):
            try:
                lifecycle = self._lifecycle.status(spec=preview["lifecycle_spec"])
            except StageAdmissionLifecycleError as exc:
                blockers.append({"code": exc.code, "message": str(exc)})
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
        if lifecycle is not None:
            result["lifecycle"] = lifecycle
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
            message=(
                f"已废弃 executor group preview_id={preview_id}；"
                "已持久化的 lifecycle recovery evidence、authority 与 executor preview 保留且未消费。"
            ),
        )

    def _build_plan(self, params: dict[str, Any]) -> dict[str, Any]:
        return build_stage_parallel_run_preview(
            project_root=self.project_root,
            project_name=params.get("project_name") if isinstance(params.get("project_name"), str) else None,
            stage_id=params.get("stage_id") if isinstance(params.get("stage_id"), str) else None,
            task_intents=params.get("task_intents") if isinstance(params.get("task_intents"), list) else None,
            max_parallel_tasks=params.get("max_parallel_tasks") if isinstance(params.get("max_parallel_tasks"), int) else None,
            provider=params.get("provider") if isinstance(params.get("provider"), str) else None,
            base_branch=params.get("base_branch") if isinstance(params.get("base_branch"), str) else None,
        )

    def _validate_plan(self, plan: dict[str, Any]) -> list[dict[str, Any]]:
        shards = plan.get("run_shards") if isinstance(plan.get("run_shards"), list) else []
        validations = []
        for shard in shards:
            if not isinstance(shard, dict):
                continue
            isolation = shard.get("isolation") if isinstance(shard.get("isolation"), dict) else {}
            worktree_path = os.path.abspath(os.path.expanduser(str(isolation.get("worktree_path") or "")))
            branch_name = str(isolation.get("branch_name") or "")
            base_branch = str(isolation.get("base_branch") or plan.get("base_branch") or "main")
            state = self._collect_worktree_state(worktree_path, base_branch=base_branch)
            preflight = {}
            if state.get("ok"):
                preflight = MCPExecutorWorkflowManager(worktree_path).handle(
                    "preflight",
                    {
                        "provider": str(plan.get("provider") or "codex"),
                        "execution_mode": "run",
                    },
                )
            validations.append(
                {
                    "task_id": shard.get("task_id"),
                    "title": shard.get("title"),
                    "worktree_path": worktree_path,
                    "branch_name": branch_name,
                    "base_branch": base_branch,
                    "expected_head": self._base_head(base_branch),
                    "worktree_state": state,
                    "executor_preflight": preflight,
                    "validation_status": "valid"
                    if self._validation_blockers(state, preflight, branch_name, base_branch) == []
                    else "blocked",
                    "blocking_reasons": self._validation_blockers(state, preflight, branch_name, base_branch),
                    "shard": shard,
                }
            )
        return validations

    def _preview_blockers(
        self,
        plan: dict[str, Any],
        validations: list[dict[str, Any]],
        operations: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        blockers: list[dict[str, Any]] = []
        run_blockers = plan.get("blocking_reasons")
        if isinstance(run_blockers, list):
            blockers.extend(item for item in run_blockers if isinstance(item, dict))
        for validation in validations:
            task_id = validation.get("task_id")
            for blocker in validation.get("blocking_reasons", []):
                if isinstance(blocker, dict):
                    blockers.append({**blocker, "task_id": task_id})
        if not operations and not blockers:
            blockers.append({"code": "NO_EXECUTOR_PREVIEW_OPERATIONS", "message": "没有可创建的 executor preview。"})
        return blockers

    def _planned_operations(self, plan: dict[str, Any], validations: list[dict[str, Any]]) -> list[dict[str, Any]]:
        operations = []
        for validation in validations:
            if validation.get("validation_status") != "valid":
                continue
            shard = validation.get("shard") if isinstance(validation.get("shard"), dict) else {}
            request = shard.get("executor_preview_request") if isinstance(shard.get("executor_preview_request"), dict) else {}
            request_args = request.get("arguments") if isinstance(request.get("arguments"), dict) else {}
            operations.append(
                {
                    "task_id": validation.get("task_id"),
                    "title": validation.get("title"),
                    "worktree_path": validation.get("worktree_path"),
                    "branch_name": validation.get("branch_name"),
                    "head": validation.get("worktree_state", {}).get("head")
                    if isinstance(validation.get("worktree_state"), dict)
                    else None,
                    "provider": plan.get("provider"),
                    "executor_preview_request": {
                        "tool": "manage_executor_workflow",
                        "arguments": {
                            **request_args,
                            "action": "run_once_preview",
                            "provider": plan.get("provider") or request_args.get("provider") or "codex",
                            "executor_session_mode": "start_new",
                            "execution_mode": "run",
                        },
                    },
                }
            )
        return operations

    def _validate_apply_state(self, preview: dict[str, Any]) -> list[dict[str, Any]]:
        plan = preview.get("run_preview") if isinstance(preview.get("run_preview"), dict) else {}
        validations = self._validate_plan(plan)
        current_ops = self._planned_operations(plan, validations)
        blockers = self._preview_blockers(plan, validations, current_ops)
        expected_ops = self._stored_operations(preview)
        if self._operations_signature(current_ops) != self._operations_signature(expected_ops):
            blockers.append(
                {
                    "code": "EXECUTOR_GROUP_OPERATIONS_CHANGED",
                    "message": "当前 executor preview operations 与 preview 时不一致。",
                }
            )
        return blockers

    def _collect_worktree_state(self, worktree_path: str, *, base_branch: str) -> dict[str, Any]:
        if not self._path_within_parallel_root(worktree_path):
            return {"ok": False, "blockers": [{"code": "WORKTREE_PATH_OUTSIDE_PROJECT_RUNTIME"}]}
        if not os.path.isdir(worktree_path):
            return {"ok": False, "blockers": [{"code": "WORKTREE_PATH_NOT_FOUND"}]}
        inside = self._git(["rev-parse", "--is-inside-work-tree"], cwd=worktree_path)
        if inside["code"] != 0 or inside["stdout"].strip().lower() != "true":
            return {"ok": False, "blockers": [{"code": "NOT_A_GIT_WORKTREE"}]}
        branch = self._git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=worktree_path)
        head = self._git(["rev-parse", "HEAD"], cwd=worktree_path)
        status = self._git(["status", "--short", "--untracked-files=all"], cwd=worktree_path)
        status_lines = [line for line in status["stdout"].splitlines() if line.strip()]
        blocking_status = [line for line in status_lines if not self._is_ignored_runtime_status(line)]
        blockers = []
        if branch["code"] != 0:
            blockers.append({"code": "WORKTREE_BRANCH_UNAVAILABLE"})
        if head["code"] != 0:
            blockers.append({"code": "WORKTREE_HEAD_UNAVAILABLE"})
        expected_head = self._base_head(base_branch)
        actual_head = head["stdout"].strip() if head["code"] == 0 else None
        if expected_head and actual_head and actual_head != expected_head:
            blockers.append(
                {
                    "code": "WORKTREE_HEAD_MISMATCH",
                    "expected": expected_head,
                    "actual": actual_head,
                }
            )
        if blocking_status:
            blockers.append({"code": "WORKTREE_NOT_CLEAN", "status_short": blocking_status[:50]})
        return {
            "ok": not blockers,
            "branch": branch["stdout"].strip() if branch["code"] == 0 else None,
            "head": actual_head,
            "expected_base_head": expected_head,
            "status_short": blocking_status,
            "ignored_runtime_status_short": [line for line in status_lines if self._is_ignored_runtime_status(line)],
            "status_hash": self._status_hash(blocking_status),
            "blockers": blockers,
        }

    def _validation_blockers(
        self,
        state: dict[str, Any],
        preflight: dict[str, Any],
        branch_name: str,
        base_branch: str,
    ) -> list[dict[str, Any]]:
        blockers = []
        for item in state.get("blockers", []):
            if isinstance(item, dict):
                blockers.append(item)
        if state.get("branch") != branch_name:
            blockers.append(
                {
                    "code": "WORKTREE_BRANCH_MISMATCH",
                    "expected": branch_name,
                    "actual": state.get("branch"),
                }
            )
        expected_head = self._base_head(base_branch)
        if expected_head and state.get("head") != expected_head:
            blockers.append(
                {
                    "code": "WORKTREE_BASE_HEAD_MISMATCH",
                    "expected": expected_head,
                    "actual": state.get("head"),
                }
            )
        if preflight and not preflight.get("ok"):
            blockers.append({"code": "EXECUTOR_PREFLIGHT_ERROR", "preflight": preflight})
        if preflight.get("preflight_blocked"):
            blockers.append(
                {
                    "code": "EXECUTOR_PREFLIGHT_BLOCKED",
                    "blocks": preflight.get("blocks", []),
                }
            )
        return blockers

    def _stored_operations(self, preview: dict[str, Any]) -> list[dict[str, Any]]:
        value = preview.get("planned_operations")
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, dict)]

    def _base_head(self, base_branch: str) -> str | None:
        result = self._git(["rev-parse", "--verify", base_branch], cwd=self.project_root)
        return result["stdout"].strip() if result["code"] == 0 else None

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

    def _operations_signature(self, operations: list[dict[str, Any]]) -> str:
        parts = []
        for operation in operations:
            parts.append(
                "|".join(
                    [
                        str(operation.get("task_id") or ""),
                        str(operation.get("worktree_path") or ""),
                        str(operation.get("branch_name") or ""),
                        str(operation.get("head") or ""),
                        str(operation.get("provider") or ""),
                    ]
                )
            )
        return hashlib.sha256("\n".join(sorted(parts)).encode("utf-8")).hexdigest()

    def _lifecycle_spec(
        self, plan: dict[str, Any], operations: list[dict[str, Any]]
    ) -> dict[str, Any]:
        task_order = [str(item.get("task_id") or "") for item in plan.get("run_shards", []) if isinstance(item, dict)]
        stage_preview_sha256 = canonical_sha256(plan.get("plan_preview", {}))
        runner_plan_sha256 = canonical_sha256(plan)
        base_head = self._base_head(str(plan.get("base_branch") or "main")) or ""
        tasks: dict[str, Any] = {}
        for operation in operations:
            task_id = str(operation.get("task_id") or "")
            tasks[task_id] = {
                "execution_context": {
                    "kind": "stage_parallel_task",
                    "stage_id": str(plan.get("stage_id") or ""),
                    "parallel_group_id": str(plan.get("parallel_group_id") or ""),
                    "task_id": task_id,
                    "stage_preview_sha256": stage_preview_sha256,
                    "base_head": canonical_sha256({"git_head": base_head}),
                    "runner_plan_sha256": runner_plan_sha256,
                },
                "shard": {
                    "project_root": operation.get("worktree_path"),
                    "branch": operation.get("branch_name"),
                    "head": operation.get("head"),
                    "provider": operation.get("provider") or "codex",
                },
            }
        return {
            "schema_version": "stage_parallel_admission_spec.v1",
            "project_root": self.project_root,
            "project_identity": canonical_sha256(
                {"project_root": self.project_root, "repository": "JENN2046/colameta"}
            ),
            "repository": "JENN2046/colameta",
            "stage_id": str(plan.get("stage_id") or ""),
            "parallel_group_id": str(plan.get("parallel_group_id") or ""),
            "stage_planning_preview_sha256": stage_preview_sha256,
            "runner_plan_sha256": runner_plan_sha256,
            "base_head": base_head,
            "task_order": task_order,
            "tasks": tasks,
        }

    def _status_hash(self, lines: list[str]) -> str:
        return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()

    def _git(self, args: list[str], *, cwd: str, timeout: int = 30) -> dict[str, Any]:
        try:
            proc = subprocess.run(
                ["git", *args],
                cwd=cwd,
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
            "does_not_start_executor": True,
            "does_not_merge_parallel_results": True,
            "does_not_commit": True,
            "does_not_push": True,
            "does_not_replace_stable_service": True,
            "does_not_write_delivery_accepted": True,
            "does_not_create_review_decision": True,
            "does_not_emit_gate_event": True,
            "does_not_create_executor_preview": preview_only,
            "creates_executor_preview_only_on_apply": not preview_only,
        }

    def _generate_preview_id(self) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        return f"stage_parallel_executor_group_{ts}_{os.urandom(4).hex()}"

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
