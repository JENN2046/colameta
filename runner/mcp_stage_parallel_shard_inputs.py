from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from typing import Any

from runner.confirmation_store import ConfirmationStore
from runner.core_confirmation import confirmation_apply_guard, confirmation_fact_from_store
from runner.runner_paths import resolve_project_runner_rel_dir
from runner.stage_parallel_plan import build_stage_parallel_run_preview
from runner.stage_parallel_shard_input_overlay import ARTIFACT_KIND, overlay_paths
from runner.tool_result import apply_result, error_result, ok_result, preview_result, status_result


PREVIEW_TTL_SECONDS = 1800
PREVIEWS_RELATIVE_DIR = os.path.join("runtime", "stage-parallel-shard-input-previews")


class MCPStageParallelShardInputManager:
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
        plan = self._build_plan(params)
        validations = self._validate_plan(plan)
        operations = self._planned_operations(plan, validations)
        blockers = self._preview_blockers(plan, validations, operations)
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
                message="shard input preview 存在阻断项，未生成 preview_id。",
            )

        preview_id = self._generate_preview_id()
        created_at = self._now_iso()
        expires_at = self._expires_at()
        reason = params.get("reason")
        preview_record = {
            "preview_id": preview_id,
            "artifact_kind": "stage_parallel_shard_input_apply_preview",
            "action": "manage_stage_parallel_shard_inputs.apply",
            "tool": "manage_stage_parallel_shard_inputs",
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
                "tool": "manage_stage_parallel_shard_inputs",
                "action": "apply",
                "params": {"action": "apply", "preview_id": preview_id},
                "reason": "使用 preview_id 在每个隔离 worktree 内写入 shard runner input；不会创建 executor preview 或启动 executor。",
                "requires_confirmation": True,
            },
            next_actions=[
                {
                    "tool": "manage_stage_parallel_shard_inputs",
                    "action": "discard",
                    "params": {"action": "discard", "preview_id": preview_id},
                    "reason": "废弃此 shard input preview，不写入 shard runner input。",
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
        if preview.get("artifact_kind") != "stage_parallel_shard_input_apply_preview":
            return error_result("PREVIEW_KIND_MISMATCH", "preview_id 类型不是 stage parallel shard input apply。", preview_id=preview_id)

        blockers = self._validate_apply_state(preview)
        if blockers:
            return error_result(
                "APPLY_STATE_MISMATCH",
                "当前 worktree 状态与 preview 不一致，已阻断 apply。",
                preview_id=preview_id,
                blockers=blockers,
                authority_boundary=self._authority_boundary(preview_only=False),
            )

        materialized: list[dict[str, Any]] = []
        source_plan = self._load_source_plan()
        for operation in self._stored_operations(preview):
            files = self._build_shard_files(operation, source_plan=source_plan)
            try:
                self._write_overlay_files(files)
            except Exception as exc:
                return error_result(
                    "SHARD_INPUT_WRITE_FAILED",
                    f"写入 shard runner input 失败：{exc}",
                    preview_id=preview_id,
                    failed_operation=operation,
                    materialized_inputs=materialized,
                    authority_boundary=self._authority_boundary(preview_only=False),
                )
            materialized.append(
                {
                    "task_id": operation.get("task_id"),
                    "worktree_path": operation.get("worktree_path"),
                    "branch_name": operation.get("branch_name"),
                    "version": files["manifest"].get("version"),
                    "runner_input_source": "stage_parallel_shard_overlay",
                    "manifest_file": files["manifest"].get("manifest_file"),
                    "plan_file": files["manifest"].get("plan_file"),
                    "state_file": files["manifest"].get("state_file"),
                    "prompt_file": files["manifest"].get("prompt_file"),
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
            side_effect_scope="shard_runtime_input_files_only",
            project_root=self.project_root,
            stage_id=preview.get("stage_id"),
            parallel_group_id=preview.get("parallel_group_id"),
            materialized_count=len(materialized),
            materialized_inputs=materialized,
            message=f"已写入 {len(materialized)} 个 shard runner input；未创建 executor preview，未启动 executor。",
            authority_boundary=self._authority_boundary(preview_only=False),
            next_actions=[
                {
                    "tool": "manage_stage_parallel_executor_group",
                    "arguments": {"action": "preview", "stage_id": preview.get("stage_id")},
                    "reason": "使用 shard runner input 后预览 executor group；当前步骤未创建 executor preview。",
                    "requires_confirmation": True,
                },
                {
                    "tool": "get_stage_parallel_group_status",
                    "arguments": {"stage_id": preview.get("stage_id")},
                    "reason": "读取并行 group 状态。",
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
            message=f"已废弃 shard input preview_id={preview_id}；未写入 shard runner input。",
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
        validations: list[dict[str, Any]] = []
        shards = plan.get("run_shards") if isinstance(plan.get("run_shards"), list) else []
        for shard in shards:
            if not isinstance(shard, dict):
                continue
            isolation = shard.get("isolation") if isinstance(shard.get("isolation"), dict) else {}
            worktree_path = os.path.abspath(os.path.expanduser(str(isolation.get("worktree_path") or "")))
            branch_name = str(isolation.get("branch_name") or "")
            base_branch = str(isolation.get("base_branch") or plan.get("base_branch") or "main")
            state = self._collect_worktree_state(worktree_path, base_branch=base_branch)
            blockers = self._validation_blockers(state, branch_name, base_branch)
            validations.append(
                {
                    "task_id": shard.get("task_id"),
                    "title": shard.get("title"),
                    "worktree_path": worktree_path,
                    "branch_name": branch_name,
                    "base_branch": base_branch,
                    "expected_head": self._base_head(base_branch),
                    "worktree_state": state,
                    "validation_status": "valid" if blockers == [] else "blocked",
                    "blocking_reasons": blockers,
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
            blockers.append({"code": "NO_SHARD_INPUT_OPERATIONS", "message": "没有可写入的 shard runner input。"})
        return blockers

    def _planned_operations(self, plan: dict[str, Any], validations: list[dict[str, Any]]) -> list[dict[str, Any]]:
        operations: list[dict[str, Any]] = []
        for validation in validations:
            if validation.get("validation_status") != "valid":
                continue
            shard = validation.get("shard") if isinstance(validation.get("shard"), dict) else {}
            worktree_path = str(validation.get("worktree_path") or "")
            paths = overlay_paths(worktree_path)
            task_id = str(validation.get("task_id") or "parallel_task")
            version = f"stage_parallel_{task_id}"
            operations.append(
                {
                    "task_id": task_id,
                    "title": validation.get("title"),
                    "worktree_path": worktree_path,
                    "branch_name": validation.get("branch_name"),
                    "base_branch": validation.get("base_branch"),
                    "head": validation.get("worktree_state", {}).get("head")
                    if isinstance(validation.get("worktree_state"), dict)
                    else None,
                    "provider": plan.get("provider") or "codex",
                    "parallel_group_id": plan.get("parallel_group_id"),
                    "stage_id": plan.get("stage_id"),
                    "version": version,
                    "allowed_files": shard.get("allowed_files") if isinstance(shard.get("allowed_files"), list) else [],
                    "surfaces": shard.get("surfaces") if isinstance(shard.get("surfaces"), list) else [],
                    "risk_level": shard.get("risk_level"),
                    "overlay_paths": {
                        "manifest_file": paths["manifest_file"],
                        "plan_file": paths["plan_file"],
                        "state_file": paths["state_file"],
                        "prompt_file": paths["prompt_file"],
                        "runtime_dir": paths["runtime_dir"],
                        "logs_dir": paths["logs_dir"],
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
                    "code": "SHARD_INPUT_OPERATIONS_CHANGED",
                    "message": "当前 shard input operations 与 preview 时不一致。",
                }
            )
        return blockers

    def _build_shard_files(self, operation: dict[str, Any], *, source_plan: dict[str, Any]) -> dict[str, Any]:
        paths = operation.get("overlay_paths") if isinstance(operation.get("overlay_paths"), dict) else {}
        worktree_path = os.path.abspath(os.path.expanduser(str(operation.get("worktree_path") or "")))
        provider = str(operation.get("provider") or "codex")
        task_id = str(operation.get("task_id") or "parallel_task")
        title = str(operation.get("title") or task_id)
        version = str(operation.get("version") or f"stage_parallel_{task_id}")
        allowed_files = self._string_list(operation.get("allowed_files"))
        now = self._now_iso()
        prompt_file = str(paths.get("prompt_file") or overlay_paths(worktree_path)["prompt_file"])
        plan_file = str(paths.get("plan_file") or overlay_paths(worktree_path)["plan_file"])
        state_file = str(paths.get("state_file") or overlay_paths(worktree_path)["state_file"])
        runtime_dir = str(paths.get("runtime_dir") or overlay_paths(worktree_path)["runtime_dir"])
        logs_dir = str(paths.get("logs_dir") or overlay_paths(worktree_path)["logs_dir"])
        manifest_file = str(paths.get("manifest_file") or overlay_paths(worktree_path)["manifest_file"])
        prompt = self._build_prompt(operation, allowed_files=allowed_files)
        plan = self._build_overlay_plan(
            source_plan=source_plan,
            worktree_path=worktree_path,
            provider=provider,
            task_id=task_id,
            title=title,
            version=version,
            allowed_files=allowed_files,
            prompt_file=prompt_file,
            runtime_dir=runtime_dir,
            logs_dir=logs_dir,
            state_file=state_file,
        )
        state = {
            "project_name": plan["project_name"],
            "status": "READY",
            "current_version": version,
            "current_version_index": 0,
            "attempt": 1,
            "max_fix_attempts_per_version": plan.get("runner_policy", {}).get("max_fix_attempts_per_version", 3),
            "versions": [
                {
                    "version": version,
                    "name": title,
                    "status": "PROMPT_READY",
                    "attempt": 0,
                    "metadata": {
                        "stage_parallel_shard_input": True,
                        "stage_id": operation.get("stage_id"),
                        "parallel_group_id": operation.get("parallel_group_id"),
                        "task_id": task_id,
                    },
                }
            ],
            "started_at": now,
            "updated_at": now,
            "completed_at": None,
            "last_prompt_file": prompt_file,
            "last_generated_prompt_file": prompt_file,
            "last_audit_file": None,
            "last_log_file": None,
            "last_error": None,
        }
        manifest = {
            "artifact_kind": ARTIFACT_KIND,
            "schema_version": "stage_parallel_shard_input_overlay.v1",
            "created_at": now,
            "worktree_path": worktree_path,
            "stage_id": operation.get("stage_id"),
            "parallel_group_id": operation.get("parallel_group_id"),
            "task_id": task_id,
            "title": title,
            "branch_name": operation.get("branch_name"),
            "base_branch": operation.get("base_branch"),
            "head": operation.get("head"),
            "provider": provider,
            "version": version,
            "allowed_files": allowed_files,
            "manifest_file": manifest_file,
            "plan_file": plan_file,
            "state_file": state_file,
            "prompt_file": prompt_file,
            "runtime_dir": runtime_dir,
            "logs_dir": logs_dir,
        }
        return {
            "manifest_file": manifest_file,
            "plan_file": plan_file,
            "state_file": state_file,
            "prompt_file": prompt_file,
            "runtime_dir": runtime_dir,
            "logs_dir": logs_dir,
            "manifest": manifest,
            "plan": plan,
            "state": state,
            "prompt": prompt,
        }

    def _build_overlay_plan(
        self,
        *,
        source_plan: dict[str, Any],
        worktree_path: str,
        provider: str,
        task_id: str,
        title: str,
        version: str,
        allowed_files: list[str],
        prompt_file: str,
        runtime_dir: str,
        logs_dir: str,
        state_file: str,
    ) -> dict[str, Any]:
        source_project = source_plan.get("project_name") if isinstance(source_plan.get("project_name"), str) else "stage_parallel"
        model_execution = dict(source_plan.get("model_execution")) if isinstance(source_plan.get("model_execution"), dict) else {}
        model_execution["provider"] = provider
        runner_policy = dict(source_plan.get("runner_policy")) if isinstance(source_plan.get("runner_policy"), dict) else {}
        runner_policy.setdefault("auto_continue_on_pass", False)
        runner_policy.setdefault("max_fix_attempts_per_version", 3)
        runner_policy.setdefault("require_clean_worktree", True)
        runner_policy.setdefault("stop_on_acceptance_failure", True)
        runner_policy.setdefault("stop_on_scope_violation", True)
        return {
            "project_name": f"{source_project}:{task_id}",
            "plan_version": "stage_parallel_shard_inputs.v1",
            "project_root": worktree_path,
            "model_execution": model_execution,
            "runner_policy": runner_policy,
            "review_policy": {"enabled": False, "mode": "manual_gate", "after_versions": []},
            "commit_policy": {
                "enabled": False,
                "mode": "manual_gate",
                "after_acceptance_pass": True,
                "include_runner_runtime_files": False,
                "require_clean_scope": True,
                "require_confirm": True,
                "require_commit_before_continue": False,
            },
            "logs_dir": logs_dir,
            "runtime_dir": runtime_dir,
            "state_file": state_file,
            "rules_file": os.path.join(worktree_path, ".colameta", "rules.md"),
            "versions": [
                {
                    "version": version,
                    "name": title,
                    "description": f"Stage parallel shard input for {task_id}.",
                    "prompt_file": prompt_file,
                    "enabled": True,
                    "context_files": allowed_files,
                    "allowed_files": allowed_files,
                    "forbidden_files": [
                        ".github/workflows/**",
                        ".colameta/state.json",
                        ".colameta/runtime/**",
                        ".colameta/logs/**",
                        ".colameta/reports/**",
                        ".colameta/audits/**",
                        ".colameta/executor-sessions/**",
                        ".colameta/*.lock",
                        ".colameta/**/*.lock",
                    ],
                    "acceptance_commands": self._source_default_acceptance_commands(source_plan),
                    "manual_acceptance": [
                        "changed files stay within shard allowed_files",
                        "no commit/push/stable replacement/Delivery accepted/ReviewDecision/GateEvent",
                    ],
                    "out_of_scope": [
                        "stable replacement",
                        "push",
                        "merge to main",
                        "Delivery accepted",
                        "ReviewDecision",
                        "GateEvent",
                    ],
                    "execution": {"provider": provider},
                    "allow_no_changes": False,
                    "required_changed_files": [],
                }
            ],
        }

    def _build_prompt(self, operation: dict[str, Any], *, allowed_files: list[str]) -> str:
        allowed = "\n".join(f"- {item}" for item in allowed_files) if allowed_files else "- <none declared>"
        surfaces = ", ".join(self._string_list(operation.get("surfaces"))) or "unspecified"
        return f"""# Stage parallel shard task

Stage: {operation.get("stage_id") or ""}
Parallel group: {operation.get("parallel_group_id") or ""}
Task: {operation.get("task_id") or ""} - {operation.get("title") or ""}
Branch: {operation.get("branch_name") or ""}
Worktree: {operation.get("worktree_path") or ""}
Surfaces: {surfaces}

## Allowed files
{allowed}

## Work
Implement only this shard's task. Keep edits inside the allowed files above.

## Boundaries
- Do not commit, push, merge, tag, release, publish, or replace stable service.
- Do not write Delivery accepted, ReviewDecision, GateEvent, secrets, tokens, cookies, credentials, or browser login state.
- Do not edit auth, proxy, provider, or tunnel configuration.
- Do not restart tunnel-client or stable services.
- If the task needs a file outside allowed_files, stop and report the needed boundary change.

## Validation
Run the nearest relevant validation before reporting completion.
"""

    def _write_overlay_files(self, files: dict[str, Any]) -> None:
        for path_key in ("runtime_dir", "logs_dir"):
            os.makedirs(str(files[path_key]), exist_ok=True)
        self._write_text_atomic(str(files["prompt_file"]), str(files["prompt"]))
        self._write_json_atomic(str(files["plan_file"]), files["plan"])
        self._write_json_atomic(str(files["state_file"]), files["state"])
        self._write_json_atomic(str(files["manifest_file"]), files["manifest"])

    def _write_json_atomic(self, path: str, payload: dict[str, Any]) -> None:
        self._write_text_atomic(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")

    def _write_text_atomic(self, path: str, content: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.tmp-{os.getpid()}-{os.urandom(4).hex()}"
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(tmp, path)

    def _load_source_plan(self) -> dict[str, Any]:
        path = os.path.join(self.project_root, ".colameta", "plan.json")
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _source_default_acceptance_commands(self, source_plan: dict[str, Any]) -> list[dict[str, Any]]:
        commands = source_plan.get("default_acceptance_commands")
        if not isinstance(commands, list):
            return []
        result: list[dict[str, Any]] = []
        for item in commands:
            if not isinstance(item, dict):
                continue
            command = item.get("command")
            if not isinstance(command, str) or not command.strip():
                continue
            result.append(
                {
                    "command": command.strip(),
                    "timeout_seconds": self._int_or(item.get("timeout_seconds"), 600),
                    "continue_on_failure": bool(item.get("continue_on_failure", False)),
                }
            )
        return result

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
        blockers: list[dict[str, Any]] = []
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

    def _validation_blockers(self, state: dict[str, Any], branch_name: str, base_branch: str) -> list[dict[str, Any]]:
        blockers: list[dict[str, Any]] = []
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
        parts: list[str] = []
        for operation in operations:
            parts.append(
                "|".join(
                    [
                        str(operation.get("task_id") or ""),
                        str(operation.get("worktree_path") or ""),
                        str(operation.get("branch_name") or ""),
                        str(operation.get("head") or ""),
                        str(operation.get("provider") or ""),
                        str(operation.get("version") or ""),
                    ]
                )
            )
        return hashlib.sha256("\n".join(sorted(parts)).encode("utf-8")).hexdigest()

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
            "does_not_create_executor_preview": True,
            "does_not_start_background_worker": True,
            "does_not_merge_parallel_results": True,
            "does_not_commit": True,
            "does_not_push": True,
            "does_not_replace_stable_service": True,
            "does_not_write_delivery_accepted": True,
            "does_not_create_review_decision": True,
            "does_not_emit_gate_event": True,
            "does_not_create_branch_or_worktree": True,
            "writes_shard_runtime_input_only_on_apply": not preview_only,
        }

    def _string_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]

    def _int_or(self, value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _generate_preview_id(self) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        return f"stage_parallel_shard_inputs_{ts}_{os.urandom(4).hex()}"

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
