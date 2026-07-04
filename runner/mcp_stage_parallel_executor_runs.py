from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from runner.confirmation_store import ConfirmationStore
from runner.core_confirmation import confirmation_apply_guard, confirmation_fact_from_store
from runner.mcp_executor_workflow import MCPExecutorWorkflowManager
from runner.mcp_stage_parallel_executor_group import MCPStageParallelExecutorGroupManager
from runner.runner_paths import resolve_project_runner_rel_dir
from runner.stage_parallel_plan import build_stage_parallel_run_preview
from runner.tool_result import apply_result, error_result, ok_result, preview_result, status_result


PREVIEW_TTL_SECONDS = 1800
PREVIEWS_RELATIVE_DIR = os.path.join("runtime", "stage-parallel-executor-run-previews")
EXECUTOR_PREVIEWS_RELATIVE_DIR = os.path.join(".colameta", "runtime", "executor-workflow-previews")
CLAIMS_DIR = "claims"


class MCPStageParallelExecutorRunGroupManager:
    def __init__(self, project_root: str):
        self.project_root = os.path.abspath(os.path.expanduser(project_root))
        preview_dir = os.path.join(resolve_project_runner_rel_dir(self.project_root), PREVIEWS_RELATIVE_DIR)
        self._store = ConfirmationStore(self.project_root, preview_dir, PREVIEW_TTL_SECONDS)
        self._executor_group = MCPStageParallelExecutorGroupManager(self.project_root)

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
        validations = self._executor_group._validate_plan(plan)
        operations, operation_blockers = self._planned_operations(plan, validations)
        blockers = self._preview_blockers(plan, validations, operations, operation_blockers)
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
                stage_id=plan.get("stage_id"),
                parallel_group_id=plan.get("parallel_group_id"),
                run_preview=plan,
                validations=validations,
                planned_operations=operations,
                blockers=blockers,
                authority_boundary=self._authority_boundary(preview_only=True),
                message="executor run group preview 存在阻断项，未生成 preview_id。",
            )

        preview_id = self._generate_preview_id()
        created_at = self._now_iso()
        expires_at = self._expires_at()
        reason = params.get("reason")
        preview_record = {
            "preview_id": preview_id,
            "artifact_kind": "stage_parallel_executor_run_group_apply_preview",
            "action": "manage_stage_parallel_executor_runs.apply",
            "tool": "manage_stage_parallel_executor_runs",
            "params": {"action": "apply", "preview_id": preview_id},
            "project_root": self.project_root,
            "stage_id": plan.get("stage_id"),
            "parallel_group_id": plan.get("parallel_group_id"),
            "provider": plan.get("provider"),
            "base_branch": plan.get("base_branch"),
            "run_preview": plan,
            "validations": validations,
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
            stage_id=plan.get("stage_id"),
            parallel_group_id=plan.get("parallel_group_id"),
            provider=plan.get("provider"),
            base_branch=plan.get("base_branch"),
            planned_operations=operations,
            created_at=created_at,
            expires_at=expires_at,
            authority_boundary=self._authority_boundary(preview_only=True),
            recommended_next_action={
                "tool": "manage_stage_parallel_executor_runs",
                "action": "apply",
                "params": {"action": "apply", "preview_id": preview_id},
                "reason": "使用 preview_id 启动每个隔离 worktree 的 executor run_once；不会 merge、commit main、push 或替换 stable。",
                "requires_confirmation": True,
            },
            next_actions=[
                {
                    "tool": "manage_stage_parallel_executor_runs",
                    "action": "discard",
                    "params": {"action": "discard", "preview_id": preview_id},
                    "reason": "废弃此 executor run group preview，不启动 executor。",
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
        if preview.get("artifact_kind") != "stage_parallel_executor_run_group_apply_preview":
            return error_result("PREVIEW_KIND_MISMATCH", "preview_id 类型不是 stage parallel executor run group apply。", preview_id=preview_id)

        blockers = self._validate_apply_state(preview)
        if blockers:
            return error_result(
                "APPLY_STATE_MISMATCH",
                "当前 worktree/executor preview 状态与 preview 不一致，已阻断 apply。",
                preview_id=preview_id,
                blockers=blockers,
                authority_boundary=self._authority_boundary(preview_only=False),
            )

        started: list[dict[str, Any]] = []
        reason = str(preview.get("reason") or f"stage parallel executor run group {preview_id}")
        for operation in self._stored_operations(preview):
            worktree_path = str(operation.get("worktree_path") or "")
            run_preview_id = str(operation.get("executor_preview_id") or "")
            result = MCPExecutorWorkflowManager(worktree_path).handle(
                "run_once",
                {
                    "preview_id": run_preview_id,
                    "provider": str(operation.get("provider") or preview.get("provider") or "codex"),
                    "execution_mode": str(operation.get("execution_mode") or "run"),
                    "executor_session_mode": "start_new",
                    "reason": reason,
                },
            )
            if not result.get("ok"):
                return error_result(
                    "EXECUTOR_RUN_START_FAILED",
                    "启动 executor run_once 失败；此前已启动的 shard 不会被回滚。",
                    preview_id=preview_id,
                    failed_operation=operation,
                    failed_result=result,
                    started_executor_runs=started,
                    authority_boundary=self._authority_boundary(preview_only=False),
                )
            started.append(
                {
                    "task_id": operation.get("task_id"),
                    "worktree_path": worktree_path,
                    "branch_name": operation.get("branch_name"),
                    "executor_preview_id": run_preview_id,
                    "run_id": result.get("run_id"),
                    "status": result.get("status"),
                    "preview_claim_status": result.get("preview_claim_status"),
                }
            )

        self._store.delete(preview_id)
        return apply_result(
            "apply",
            preview_id,
            status="started",
            risk_level="commit",
            read_only=False,
            side_effects=True,
            side_effect_scope="parallel_executor_runs_started_in_isolated_worktrees",
            project_root=self.project_root,
            stage_id=preview.get("stage_id"),
            parallel_group_id=preview.get("parallel_group_id"),
            started_count=len(started),
            started_executor_runs=started,
            message=f"已启动 {len(started)} 个隔离 worktree executor run；未 merge、未 commit main、未 push、未替换 stable。",
            authority_boundary=self._authority_boundary(preview_only=False),
            next_actions=[
                {
                    "tool": "get_stage_parallel_group_status",
                    "arguments": {"stage_id": preview.get("stage_id")},
                    "reason": "轮询 executor 完成后，用 sanitized executor result 摘要读取 group 状态。",
                    "requires_confirmation": False,
                },
                {
                    "tool": "inspect_executor_activity",
                    "arguments": {"project_name": "<project_name>"},
                    "reason": "检查 executor activity；不要读取 raw logs 或 token/cookie。",
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
            message=f"已废弃 executor run group preview_id={preview_id}；未启动 executor。",
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

    def _planned_operations(
        self,
        plan: dict[str, Any],
        validations: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        operations: list[dict[str, Any]] = []
        blockers: list[dict[str, Any]] = []
        for validation in validations:
            if validation.get("validation_status") != "valid":
                continue
            found = self._find_executor_preview(validation, provider=str(plan.get("provider") or "codex"))
            if found.get("ok"):
                artifact = found.get("artifact") if isinstance(found.get("artifact"), dict) else {}
                operations.append(
                    {
                        "task_id": validation.get("task_id"),
                        "title": validation.get("title"),
                        "worktree_path": validation.get("worktree_path"),
                        "branch_name": validation.get("branch_name"),
                        "head": validation.get("worktree_state", {}).get("head")
                        if isinstance(validation.get("worktree_state"), dict)
                        else None,
                        "provider": artifact.get("provider") or plan.get("provider") or "codex",
                        "execution_mode": artifact.get("execution_mode") or "run",
                        "executor_preview_id": artifact.get("preview_id"),
                        "executor_preview_created_at": artifact.get("created_at"),
                        "executor_preview_expires_at": artifact.get("expires_at"),
                        "executor_preview_summary": {
                            "current_version": artifact.get("current_version"),
                            "current_head": artifact.get("current_head"),
                            "current_branch": artifact.get("current_branch"),
                            "runner_status": artifact.get("runner_status"),
                        },
                        "run_request": {
                            "tool": "manage_executor_workflow",
                            "arguments": {
                                "action": "run_once",
                                "preview_id": artifact.get("preview_id"),
                                "provider": artifact.get("provider") or plan.get("provider") or "codex",
                                "execution_mode": artifact.get("execution_mode") or "run",
                                "executor_session_mode": "start_new",
                            },
                        },
                    }
                )
            else:
                blocker = {
                    "code": str(found.get("error_code") or "EXECUTOR_PREVIEW_NOT_FOUND"),
                    "message": str(found.get("message") or "未找到可启动的 executor preview artifact。"),
                    "task_id": validation.get("task_id"),
                    "worktree_path": validation.get("worktree_path"),
                }
                if found.get("candidate_count") is not None:
                    blocker["candidate_count"] = found.get("candidate_count")
                if found.get("candidate_blockers"):
                    blocker["candidate_blockers"] = found.get("candidate_blockers")
                blockers.append(blocker)
        return operations, blockers

    def _preview_blockers(
        self,
        plan: dict[str, Any],
        validations: list[dict[str, Any]],
        operations: list[dict[str, Any]],
        operation_blockers: list[dict[str, Any]],
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
        blockers.extend(operation_blockers)
        if not operations and not blockers:
            blockers.append({"code": "NO_EXECUTOR_RUN_OPERATIONS", "message": "没有可启动的 executor run。"})
        return blockers

    def _validate_apply_state(self, preview: dict[str, Any]) -> list[dict[str, Any]]:
        plan = preview.get("run_preview") if isinstance(preview.get("run_preview"), dict) else {}
        validations = self._executor_group._validate_plan(plan)
        current_ops, operation_blockers = self._planned_operations(plan, validations)
        blockers = self._preview_blockers(plan, validations, current_ops, operation_blockers)
        expected_ops = self._stored_operations(preview)
        if self._operations_signature(current_ops) != self._operations_signature(expected_ops):
            blockers.append(
                {
                    "code": "EXECUTOR_RUN_GROUP_OPERATIONS_CHANGED",
                    "message": "当前 executor run operations 与 preview 时不一致。",
                }
            )
        return blockers

    def _find_executor_preview(self, validation: dict[str, Any], *, provider: str) -> dict[str, Any]:
        worktree_path = str(validation.get("worktree_path") or "")
        preview_dir = os.path.join(worktree_path, EXECUTOR_PREVIEWS_RELATIVE_DIR)
        if not os.path.isdir(preview_dir):
            return {
                "ok": False,
                "error_code": "EXECUTOR_PREVIEW_NOT_FOUND",
                "message": "worktree 中尚未创建 executor preview artifact。",
                "candidate_count": 0,
            }
        candidates: list[dict[str, Any]] = []
        candidate_blockers: list[dict[str, Any]] = []
        for filename in sorted(os.listdir(preview_dir)):
            if not filename.endswith(".json"):
                continue
            path = os.path.join(preview_dir, filename)
            if not os.path.isfile(path):
                continue
            artifact = self._read_json(path)
            if not isinstance(artifact, dict):
                continue
            if str(artifact.get("artifact_kind") or "") != "run_once":
                continue
            preview_id = str(artifact.get("preview_id") or filename[:-5])
            blockers = self._executor_preview_blockers(artifact, validation, provider=provider, preview_dir=preview_dir)
            if blockers:
                candidate_blockers.append({"preview_id": preview_id, "blockers": blockers[:5]})
                continue
            candidates.append(artifact)
        if not candidates:
            code = "EXECUTOR_PREVIEW_NOT_FOUND"
            if candidate_blockers:
                codes = {
                    str(blocker.get("code") or "")
                    for item in candidate_blockers
                    for blocker in item.get("blockers", [])
                    if isinstance(blocker, dict)
                }
                if "EXECUTOR_PREVIEW_ALREADY_CLAIMED" in codes:
                    code = "EXECUTOR_PREVIEW_ALREADY_CLAIMED"
                elif "EXECUTOR_PREVIEW_EXPIRED" in codes:
                    code = "EXECUTOR_PREVIEW_EXPIRED"
            return {
                "ok": False,
                "error_code": code,
                "message": "没有未消费且匹配当前 worktree/head/provider 的 executor preview artifact。",
                "candidate_count": len(candidate_blockers),
                "candidate_blockers": candidate_blockers[:5],
            }
        candidates.sort(key=lambda item: (str(item.get("created_at") or ""), str(item.get("preview_id") or "")), reverse=True)
        return {"ok": True, "artifact": candidates[0], "candidate_count": len(candidates)}

    def _executor_preview_blockers(
        self,
        artifact: dict[str, Any],
        validation: dict[str, Any],
        *,
        provider: str,
        preview_dir: str,
    ) -> list[dict[str, Any]]:
        blockers: list[dict[str, Any]] = []
        worktree_path = str(validation.get("worktree_path") or "")
        state = validation.get("worktree_state") if isinstance(validation.get("worktree_state"), dict) else {}
        preview_id = str(artifact.get("preview_id") or "")
        expected_head = str(state.get("head") or "")
        expected_branch = str(validation.get("branch_name") or "")
        if os.path.abspath(str(artifact.get("project_root") or "")) != os.path.abspath(worktree_path):
            blockers.append({"code": "EXECUTOR_PREVIEW_PROJECT_MISMATCH"})
        if str(artifact.get("provider") or "") != provider:
            blockers.append({"code": "EXECUTOR_PREVIEW_PROVIDER_MISMATCH", "expected": provider, "actual": artifact.get("provider")})
        if str(artifact.get("execution_mode") or "run") != "run":
            blockers.append({"code": "EXECUTOR_PREVIEW_EXECUTION_MODE_MISMATCH", "actual": artifact.get("execution_mode")})
        if expected_head and str(artifact.get("current_head") or "") != expected_head:
            blockers.append({"code": "EXECUTOR_PREVIEW_HEAD_MISMATCH", "expected": expected_head, "actual": artifact.get("current_head")})
        if expected_branch and str(artifact.get("current_branch") or "") != expected_branch:
            blockers.append(
                {"code": "EXECUTOR_PREVIEW_BRANCH_MISMATCH", "expected": expected_branch, "actual": artifact.get("current_branch")}
            )
        if str(artifact.get("blocking_git_status_short") or "").strip():
            blockers.append({"code": "EXECUTOR_PREVIEW_BLOCKING_GIT_STATUS"})
        if self._is_artifact_expired(artifact):
            blockers.append({"code": "EXECUTOR_PREVIEW_EXPIRED"})
        if preview_id and os.path.exists(os.path.join(preview_dir, CLAIMS_DIR, f"{preview_id}.json")):
            blockers.append({"code": "EXECUTOR_PREVIEW_ALREADY_CLAIMED"})
        return blockers

    def _stored_operations(self, preview: dict[str, Any]) -> list[dict[str, Any]]:
        value = preview.get("planned_operations")
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, dict)]

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
                        str(operation.get("execution_mode") or ""),
                        str(operation.get("executor_preview_id") or ""),
                    ]
                )
            )
        return hashlib.sha256("\n".join(sorted(parts)).encode("utf-8")).hexdigest()

    def _read_json(self, path: str) -> dict[str, Any] | None:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    def _is_artifact_expired(self, artifact: dict[str, Any]) -> bool:
        raw = str(artifact.get("expires_at") or "").strip()
        if not raw:
            return True
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return True
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed <= datetime.now(timezone.utc)

    def _authority_boundary(self, *, preview_only: bool) -> dict[str, bool]:
        return {
            "does_not_create_executor_preview": True,
            "does_not_start_executor": preview_only,
            "starts_executor_runs_on_apply": not preview_only,
            "may_modify_isolated_worktrees_on_apply": not preview_only,
            "does_not_merge_parallel_results": True,
            "does_not_commit_to_main": True,
            "does_not_push": True,
            "does_not_replace_stable_service": True,
            "does_not_write_delivery_accepted": True,
            "does_not_create_review_decision": True,
            "does_not_emit_gate_event": True,
        }

    def _generate_preview_id(self) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        return f"stage_parallel_executor_run_group_{ts}_{os.urandom(4).hex()}"

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
