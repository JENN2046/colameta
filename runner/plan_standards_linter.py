import json
import os
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from runner.executor_registry import is_supported_execution_provider


@dataclass(frozen=True)
class PlanLintIssue:
    severity: str
    code: str
    message: str
    version: str | None = None
    field: str | None = None
    suggestion: str | None = None
    blocking: bool = True


def _issue(
    severity: str, code: str, message: str,
    version: str | None = None, field: str | None = None,
    suggestion: str | None = None, blocking: bool = True,
) -> PlanLintIssue:
    return PlanLintIssue(
        severity=severity, code=code, message=message,
        version=version, field=field, suggestion=suggestion, blocking=blocking,
    )


def _str_val(v: Any) -> str | None:
    return v.strip() if isinstance(v, str) and v.strip() else None


def _check_allowed_files(pattern: str, version_str: str, field_prefix: str) -> list[PlanLintIssue]:
    issues: list[PlanLintIssue] = []
    if not isinstance(pattern, str):
        issues.append(_issue("error", "NON_STRING_ALLOWED_FILE", "allowed_files 必须是非空字符串列表。", version=version_str, field=field_prefix, blocking=True))
        return issues
    cleaned = pattern.strip()
    if not cleaned:
        issues.append(_issue("error", "EMPTY_ALLOWED_FILE", "allowed_files 不能包含空字符串。", version=version_str, field=field_prefix, blocking=True))
        return issues
    if cleaned == "**/*":
        issues.append(_issue("error", "BROAD_ALLOWED_FILES", f"allowed_files 过于宽泛：{cleaned}，请更具体。", version=version_str, field=field_prefix, blocking=True))
    elif cleaned == "*":
        issues.append(_issue("warning", "BROAD_ALLOWED_FILES", f"allowed_files 过于宽泛：{cleaned}，建议更具体。", version=version_str, field=field_prefix, blocking=False))
    elif cleaned.startswith("/"):
        issues.append(_issue("error", "ABSOLUTE_ALLOWED_FILE", f"allowed_files 包含绝对路径：{cleaned}，请使用相对路径。", version=version_str, field=field_prefix, blocking=True))
    return issues


def _check_list_str(items: Any, label: str, version_str: str, field_prefix: str) -> list[PlanLintIssue]:
    issues: list[PlanLintIssue] = []
    if not isinstance(items, list):
        issues.append(_issue("error", "FIELD_NOT_LIST", f"{label} 必须是 list。", version=version_str, field=field_prefix, blocking=True))
        return issues
    for idx, item in enumerate(items):
        if not isinstance(item, str):
            issues.append(_issue("error", "FIELD_ITEM_NOT_STRING", f"{label}[{idx}] 必须是字符串。", version=version_str, field=f"{field_prefix}[{idx}]", blocking=True))
    return issues


class PlanStandardsLinter:
    def lint_project(self, project_root: str) -> dict[str, Any]:
        plan_file = resolve_project_runner_plan_path(project_root)
        return self.lint_plan_file(plan_file, project_root=project_root)

    def lint_plan_file(self, plan_file: str, project_root: str | None = None) -> dict[str, Any]:
        if not os.path.isfile(plan_file):
            return {"ok": False, "error_code": "PLAN_FILE_NOT_FOUND", "message": f"plan.json 不存在：{plan_file}",
                    "summary_for_chatgpt": "无法读取 plan.json，不能继续生成 plan patch。"}
        try:
            data = json.loads(open(plan_file, "r", encoding="utf-8").read())
        except json.JSONDecodeError as e:
            return {"ok": False, "error_code": "PLAN_JSON_INVALID", "message": f"plan.json 不是合法 JSON：{e}",
                    "summary_for_chatgpt": "无法读取 plan.json，不能继续生成 plan patch。"}
        except Exception as e:
            return {"ok": False, "error_code": "PLAN_READ_ERROR", "message": f"读取 plan.json 失败：{e}",
                    "summary_for_chatgpt": "无法读取 plan.json，不能继续生成 plan patch。"}
        if not isinstance(data, dict):
            return {"ok": False, "error_code": "PLAN_NOT_OBJECT", "message": "plan.json 根节点不是 JSON 对象。",
                    "summary_for_chatgpt": "无法读取 plan.json，不能继续生成 plan patch。"}
        return self.lint_plan_data(data, plan_file=plan_file, project_root=project_root)

    def lint_plan_data(self, data: dict[str, Any], *, plan_file: str | None = None, project_root: str | None = None) -> dict[str, Any]:
        issues: list[PlanLintIssue] = []

        if not _str_val(data.get("project_name")):
            issues.append(_issue("warning", "MISSING_PROJECT_NAME", "plan.json 缺少 project_name 或为空。", field="project_name", blocking=False))
        if not _str_val(data.get("plan_version")):
            issues.append(_issue("warning", "MISSING_PLAN_VERSION", "plan.json 缺少 plan_version 或为空。", field="plan_version", blocking=False))

        me = data.get("model_execution")
        if isinstance(me, dict):
            prov = _str_val(me.get("provider"))
            if prov and not is_supported_execution_provider(prov):
                issues.append(_issue("error", "INVALID_MODEL_EXECUTION_PROVIDER", f"model_execution.provider 不是支持的执行器：{prov}", field="model_execution.provider", blocking=True))

        default_commands = data.get("default_acceptance_commands")
        if default_commands is not None:
            issues.extend(self._lint_acceptance_commands(default_commands, version_str="(default)", field_prefix="default_acceptance_commands"))

        raw_versions = data.get("versions")
        if raw_versions is None or not isinstance(raw_versions, list):
            issues.append(_issue("error", "MISSING_VERSIONS", "plan.json 缺少 versions 字段或 versions 不是列表。", field="versions", blocking=True))
            return self._build_result(issues, plan_file=plan_file, project_root=project_root)
        if not raw_versions:
            issues.append(_issue("warning", "EMPTY_VERSIONS", "versions 为空列表。onboarding-only 场景可接受，后续通过 manage_plan_version 添加版本。", field="versions", blocking=False))

        seen_versions: set[str] = set()
        for v_idx, v in enumerate(raw_versions):
            v_prefix = f"versions[{v_idx}]"
            v_str = _str_val(v.get("version")) if isinstance(v, dict) else None
            vid = v_str or f"index {v_idx}"
            if v_str:
                if v_str in seen_versions:
                    issues.append(_issue("error", "DUPLICATE_VERSION", f"版本号 {v_str} 重复。", field=v_prefix, blocking=True))
                seen_versions.add(v_str)
            issues.extend(self._lint_single_version(v, v_idx, v_str))

        return self._build_result(issues, plan_file=plan_file, project_root=project_root)

    def _lint_single_version(self, v: Any, v_idx: int, v_str: str | None) -> list[PlanLintIssue]:
        issues: list[PlanLintIssue] = []
        v_prefix = f"versions[{v_idx}]"
        vid = v_str or v_prefix

        if not isinstance(v, dict):
            issues.append(_issue("error", "VERSION_NOT_OBJECT", f"版本 {vid} 不是 JSON 对象。", field=v_prefix, blocking=True))
            return issues

        if not _str_val(v.get("version")):
            issues.append(_issue("error", "MISSING_VERSION", f"版本缺失 version 字段。", version=vid, field=f"{v_prefix}.version", blocking=True))
        if not _str_val(v.get("name")):
            issues.append(_issue("error", "MISSING_VERSION_NAME", f"版本缺失 name 字段。", version=vid, field=f"{v_prefix}.name", blocking=True))
        if not _str_val(v.get("description")):
            issues.append(_issue("warning", "MISSING_VERSION_DESCRIPTION", f"版本缺失 description 字段或为空。", version=vid, field=f"{v_prefix}.description", blocking=False))
        if not _str_val(v.get("prompt_file")):
            issues.append(_issue("error", "MISSING_PROMPT_FILE", f"版本缺失 prompt_file 字段。", version=vid, field=f"{v_prefix}.prompt_file", blocking=True))

        enabled = v.get("enabled")
        if enabled is not None and not isinstance(enabled, bool):
            issues.append(_issue("warning", "INVALID_ENABLED", f"版本 enabled 不是布尔值。", version=vid, field=f"{v_prefix}.enabled", blocking=False))

        allowed = v.get("allowed_files")
        if not isinstance(allowed, list) or not allowed:
            issues.append(_issue("error", "MISSING_ALLOWED_FILES", f"版本 allowed_files 不存在或为空。", version=vid, field=f"{v_prefix}.allowed_files", blocking=True))
        elif isinstance(allowed, list):
            for af_idx, af in enumerate(allowed):
                issues.extend(_check_allowed_files(af, vid, f"{v_prefix}.allowed_files[{af_idx}]"))

        acc_commands = v.get("acceptance_commands")
        if acc_commands is not None:
            issues.extend(self._lint_acceptance_commands(acc_commands, version_str=vid, field_prefix=f"{v_prefix}.acceptance_commands"))
        elif enabled is not False:
            issues.append(_issue("error", "MISSING_ACCEPTANCE_COMMANDS", f"版本缺少 acceptance_commands。", version=vid, field=f"{v_prefix}.acceptance_commands", blocking=True))

        execution = v.get("execution")
        if execution is not None:
            if not isinstance(execution, dict):
                issues.append(_issue("error", "EXECUTION_NOT_OBJECT", f"版本 execution 不是 JSON 对象。", version=vid, field=f"{v_prefix}.execution", blocking=True))
            else:
                ex_prov = _str_val(execution.get("provider"))
                if ex_prov and not is_supported_execution_provider(ex_prov):
                    issues.append(_issue("error", "INVALID_EXECUTION_PROVIDER", f"版本 execution.provider 不是支持的执行器：{ex_prov}", version=vid, field=f"{v_prefix}.execution.provider", blocking=True))
                cap = _str_val(execution.get("capability_level"))
                if cap and cap not in ("L1", "L2", "L3", "L4", "UNKNOWN"):
                    issues.append(_issue("warning", "INVALID_CAPABILITY_LEVEL", f"版本 execution.capability_level 应为 L1/L2/L3/L4/UNKNOWN。", version=vid, field=f"{v_prefix}.execution.capability_level", blocking=False))

        oos = v.get("out_of_scope")
        if oos is not None and not (isinstance(oos, list) and len(oos) >= 0):
            issues.append(_issue("error", "OUT_OF_SCOPE_NOT_LIST", "out_of_scope 必须是 list。", version=vid, field=f"{v_prefix}.out_of_scope", blocking=True))
        elif oos is not None and isinstance(oos, list):
            issues.extend(_check_list_str(oos, "out_of_scope", vid, f"{v_prefix}.out_of_scope"))
        if oos is None or (isinstance(oos, list) and len(oos) == 0):
            issues.append(_issue("warning", "MISSING_OUT_OF_SCOPE", "out_of_scope 缺失或为空，建议明确此版本不做什么。", version=vid, field=f"{v_prefix}.out_of_scope", blocking=False))

        ff = v.get("forbidden_files")
        if ff is not None and not (isinstance(ff, list) and len(ff) >= 0):
            issues.append(_issue("error", "FORBIDDEN_FILES_NOT_LIST", "forbidden_files 必须是 list。", version=vid, field=f"{v_prefix}.forbidden_files", blocking=True))
        elif ff is not None and isinstance(ff, list):
            issues.extend(_check_list_str(ff, "forbidden_files", vid, f"{v_prefix}.forbidden_files"))

        for field_name, label in [("context_files", "context_files"), ("manual_acceptance", "manual_acceptance")]:
            field_val = v.get(field_name)
            if field_val is not None:
                if not isinstance(field_val, list):
                    issues.append(_issue("error", f"{field_name.upper()}_NOT_LIST", f"{label} 必须是 list。", version=vid, field=f"{v_prefix}.{field_name}", blocking=True))
                else:
                    issues.extend(_check_list_str(field_val, label, vid, f"{v_prefix}.{field_name}"))

        return issues

    def _lint_acceptance_commands(self, commands: Any, version_str: str, field_prefix: str) -> list[PlanLintIssue]:
        issues: list[PlanLintIssue] = []
        if not isinstance(commands, list):
            issues.append(_issue("error", "ACCEPTANCE_COMMANDS_NOT_LIST", "acceptance_commands 必须是 list。", version=version_str, field=field_prefix, blocking=True))
            return issues
        if not commands:
            issues.append(_issue("error", "EMPTY_ACCEPTANCE_COMMANDS", "acceptance_commands 为空列表。", version=version_str, field=field_prefix, blocking=True))
            return issues

        var_defs: list[str] = []
        for cmd_idx, cmd_item in enumerate(commands):
            c_prefix = f"{field_prefix}[{cmd_idx}]"
            if isinstance(cmd_item, str):
                issues.append(_issue("warning", "LEGACY_STRING_ACCEPTANCE_COMMAND", "acceptance command 为字符串格式，建议改为完整 dict 格式（command/timeout_seconds/continue_on_failure）。", version=version_str, field=c_prefix, blocking=False))
                command = cmd_item
            elif isinstance(cmd_item, dict):
                command = _str_val(cmd_item.get("command")) or ""
            else:
                issues.append(_issue("error", "INVALID_ACCEPTANCE_COMMAND", "acceptance command 必须是 dict 或字符串。", version=version_str, field=c_prefix, blocking=True))
                continue

            if not command:
                issues.append(_issue("error", "EMPTY_ACCEPTANCE_COMMAND", "command 为空。", version=version_str, field=f"{c_prefix}.command", blocking=True))
                continue

            if "\n" in command or "\r" in command:
                issues.append(_issue("error", "MULTILINE_ACCEPTANCE_COMMAND", "acceptance command 不允许包含换行。", version=version_str, field=f"{c_prefix}.command", suggestion="将多行脚本放入受控源码文件，再用单行命令调用。", blocking=True))

            if isinstance(cmd_item, dict):
                ts = cmd_item.get("timeout_seconds")
                if ts is None:
                    issues.append(_issue("error", "MISSING_TIMEOUT_SECONDS", "缺少 timeout_seconds。", version=version_str, field=f"{c_prefix}.timeout_seconds", blocking=True))
                elif not isinstance(ts, int) or ts <= 0:
                    issues.append(_issue("error", "INVALID_TIMEOUT_SECONDS", "timeout_seconds 必须是正整数。", version=version_str, field=f"{c_prefix}.timeout_seconds", blocking=True))

                cf = cmd_item.get("continue_on_failure")
                if cf is None:
                    issues.append(_issue("error", "MISSING_CONTINUE_ON_FAILURE", "缺少 continue_on_failure。", version=version_str, field=f"{c_prefix}.continue_on_failure", blocking=True))
                elif not isinstance(cf, bool):
                    issues.append(_issue("error", "INVALID_CONTINUE_ON_FAILURE", "continue_on_failure 必须是 true/false。", version=version_str, field=f"{c_prefix}.continue_on_failure", blocking=True))

                cwd_val = cmd_item.get("cwd")
                if cwd_val is not None:
                    if not isinstance(cwd_val, str) or not cwd_val.strip():
                        issues.append(_issue("error", "INVALID_CWD", "cwd 必须是非空字符串。", version=version_str, field=f"{c_prefix}.cwd", blocking=True))
                    else:
                        if cwd_val.startswith("/") or ".." in cwd_val.split("/"):
                            issues.append(_issue("error", "INVALID_CWD_PATH", "cwd 不能是绝对路径或包含 ..。", version=version_str, field=f"{c_prefix}.cwd", blocking=True))

            self._detect_dangerous_patterns(command, version_str, c_prefix, issues, var_defs)

        return issues

    def _detect_dangerous_patterns(self, cmd: str, version_str: str, field_prefix: str, issues: list[PlanLintIssue], var_defs: list[str]) -> None:
        cmd_lower = cmd.lower().strip()

        if "<<" in cmd:
            here_doc_markers = ["<<", "<<'EOF'", "<<EOF", "<<PY", "<<'PY'", "<<JSON", "<<'JSON'"]
            if any(m in cmd for m in here_doc_markers):
                issues.append(_issue("error", "HERE_DOC_ACCEPTANCE_COMMAND", "acceptance command 包含 here-doc。", version=version_str, field=field_prefix, suggestion="将脚本写入文件后使用单行命令调用。", blocking=True))

        risky_tokens = ("{", "}", "JSON", "PY", ")")
        if cmd in risky_tokens:
            issues.append(_issue("error", "RISKY_SINGLE_TOKEN", f"单独标记作为命令：{cmd}。", version=version_str, field=field_prefix, blocking=True))

        if "'JSON'" in cmd and "JSON" not in cmd.split("'JSON'", 1)[1]:
            issues.append(_issue("error", "UNCLOSED_JSON_HERE_DOC", "存在未闭合的 JSON here-doc。", version=version_str, field=field_prefix, blocking=True))
        if "'PY'" in cmd and "PY" not in cmd.split("'PY'", 1)[1]:
            issues.append(_issue("error", "UNCLOSED_PY_HERE_DOC", "存在未闭合的 PY here-doc。", version=version_str, field=field_prefix, blocking=True))
        if "CHANGE_ID=$(python3 - <<'PY'" in cmd:
            issues.append(_issue("error", "CROSS_COMMAND_CHANGE_ID", "包含跨命令变量块风险：CHANGE_ID=$(python3 - <<'PY'。", version=version_str, field=field_prefix, blocking=True))

        define_match = re.match(r"^\s*([A-Z_][A-Z0-9_]*)=", cmd)
        if define_match:
            var_defs.append(define_match.group(1))
        for defined in var_defs:
            if f"${defined}" in cmd and not cmd.startswith(f"{defined}="):
                issues.append(_issue("error", "CROSS_COMMAND_VARIABLE", f"依赖跨命令变量 ${defined}。各命令不能共享环境变量状态。", version=version_str, field=field_prefix, blocking=True))

        if "curl" in cmd_lower and "| sh" in cmd_lower:
            issues.append(_issue("error", "CURL_PIPE_SHELL", "curl | sh 不允许。", version=version_str, field=field_prefix, blocking=True))
        if "rm -rf" in cmd_lower:
            issues.append(_issue("error", "DESTRUCTIVE_SHELL_COMMAND", "rm -rf 不允许。", version=version_str, field=field_prefix, blocking=True))

        dangerous_git = ("git reset", "git clean", "git merge", "git rebase", "git push")
        if any(dg in cmd_lower for dg in dangerous_git):
            issues.append(_issue("error", "DANGEROUS_GIT_COMMAND", "acceptance command 不允许包含危险 git 操作（reset/clean/merge/rebase/push）。", version=version_str, field=field_prefix, blocking=True))

        interactive_markers = ("read -p", "input(", "npm init", "pnpm create", "create-react-app")
        for marker in interactive_markers:
            if marker in cmd_lower:
                issues.append(_issue("warning", "INTERACTIVE_COMMAND", f"命令可能交互式：{marker}。", version=version_str, field=field_prefix, blocking=False))
                break

        if ("&&" in cmd or ";" in cmd) and not (cmd.strip().startswith("#") or cmd.strip().startswith("//")):
            issues.append(_issue("warning", "MULTI_STEP_COMMAND", "命令包含多个步骤（&& 或 ;），建议保持单一验收动作。", version=version_str, field=field_prefix, blocking=False))

        if re.search(r'\b(export|source)\s', cmd):
            issues.append(_issue("warning", "EXPORT_SOURCE_COMMAND", "export/source 在当前进程有效，但每条 command 独立运行环境，无法传递给后续命令。", version=version_str, field=field_prefix, blocking=False))

    def _build_result(
        self,
        issues: list[PlanLintIssue],
        plan_file: str | None = None,
        project_root: str | None = None,
    ) -> dict[str, Any]:
        blocking = [i for i in issues if i.blocking]
        warnings = [i for i in issues if not i.blocking]
        status = "failed" if blocking else "passed"

        issue_dicts: list[dict[str, Any]] = []
        for i in issues:
            d: dict[str, Any] = {"severity": i.severity, "code": i.code, "message": i.message, "blocking": i.blocking}
            if i.version:
                d["version"] = i.version
            if i.field:
                d["field"] = i.field
            if i.suggestion:
                d["suggestion"] = i.suggestion
            issue_dicts.append(d)

        if status == "passed":
            summary = "plan.json 符合 Runner plan_format 标准；可以继续生成 plan patch。"
        else:
            top_lines = [f"- {i.version or ''} {i.field or ''}: {i.message}".strip() for i in blocking[:3]]
            top_text = "\n".join(top_lines)
            summary = (
                f"plan.json 存在 {len(blocking)} 个阻断问题、{len(warnings)} 个警告。"
                f"ChatGPT 应先修复这些 plan 标准问题；除非 patch 目标就是修复这些问题，否则不要调用 preview_insert_version / preview_update_version。\n"
                f"Top blocking issues:\n{top_text}"
            )

        result: dict[str, Any] = {
            "ok": True,
            "status": status,
            "issue_count": len(issues),
            "blocking_issue_count": len(blocking),
            "warning_count": len(warnings),
            "issues": issue_dicts,
            "summary_for_chatgpt": summary,
        }
        if plan_file is not None:
            result["plan_file"] = plan_file
        if project_root is not None:
            result["project_root"] = project_root
        return result
from runner.runner_paths import resolve_project_runner_plan_path
