import os
from typing import Optional
from schemas.plan import BuildRunnerPlan, BuildVersion
from schemas.audit import BuildAuditReport

class PromptBuilder:
    def build_version_prompt(self, plan: BuildRunnerPlan, version: BuildVersion) -> str:
        prompt_content = self._read_file(version.prompt_file)
        
        os.makedirs(plan.runtime_dir, exist_ok=True)
        out_path = os.path.join(plan.runtime_dir, "current-prompt.md")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(prompt_content)
            
        return prompt_content

    def build_fix_prompt(self, plan: BuildRunnerPlan, version: BuildVersion, audit_markdown: str, manual_fix_prompt: str) -> str:
        allowed_files = "\n".join([f"- {f}" for f in version.allowed_files]) if version.allowed_files else "无"
        forbidden_files = "\n".join([f"- {f}" for f in version.forbidden_files]) if version.forbidden_files else "无"
        acceptance_cmds = "\n".join([f"- `{c.command}`" for c in version.acceptance_commands]) if version.acceptance_commands else "无"

        prompt = f"""# 当前版本修复任务
当前版本验收失败。

## 当前版本
{version.version} - {version.name}

## 失败审计
{audit_markdown}

## 用户提供的修复提示词
{manual_fix_prompt}

## 允许修改文件
{allowed_files}

## 禁止修改文件
{forbidden_files}

## 验收命令
{acceptance_cmds}

## 强制约束
- 只修复当前版本。
- 不要进入下一版本。
- 不要扩展 scope。
- 不要修改 allowed_files 之外的文件。
- 不要重构无关代码。
- 修复完成后运行验收命令。
"""

        os.makedirs(plan.runtime_dir, exist_ok=True)
        out_path = os.path.join(plan.runtime_dir, "current-fix-prompt.md")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(prompt)

        return prompt

    def _read_file(self, path: str, base_dir: str | None = None) -> str:
        try:
            if not path:
                return ""
            resolved_path = path
            if base_dir and not os.path.isabs(resolved_path):
                resolved_path = os.path.join(base_dir, resolved_path)
            if not os.path.exists(resolved_path):
                return ""
            with open(resolved_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            return ""
