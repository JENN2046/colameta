import os
import platform
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from runner.runner_paths import PRIMARY_PROJECT_RUNNER_DIRNAME

@dataclass
class BootstrapResult:
    project_root: str
    created_files: list[str] = field(default_factory=list)
    skipped_files: list[str] = field(default_factory=list)
    overwritten_files: list[str] = field(default_factory=list)


@dataclass
class OpenBootstrapResult:
    project_root: str
    opened_files: list[str] = field(default_factory=list)
    manual_files: list[str] = field(default_factory=list)
    open_errors: list[str] = field(default_factory=list)
    is_macos: bool = False


@dataclass
class ValidationItem:
    name: str
    status: str
    message: str


@dataclass
class ValidateBootstrapResult:
    project_root: str
    ok: bool
    items: list[ValidationItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    parsed_versions: list[dict[str, Any]] = field(default_factory=list)


class BootstrapManager:
    RUNNER_DIR = PRIMARY_PROJECT_RUNNER_DIRNAME
    PLAN_FILE = f"{RUNNER_DIR}/plans/plan-bundle.yaml"
    BOOTSTRAP_FILES = [
        "README.md",
        "AGENTS.md",
        "docs/ARCHITECTURE.md",
        "docs/DEVELOPMENT_PLAN.md",
        f"{RUNNER_DIR}/plans/plan-bundle.yaml",
        f"{RUNNER_DIR}/bootstrap/CHATGPT_CONTEXT.md",
        f"{RUNNER_DIR}/bootstrap/BOOTSTRAP_CHECKLIST.md",
    ]

    def bootstrap(self, project_path: str, force: bool = False) -> BootstrapResult:
        project_root = os.path.abspath(os.path.expanduser(project_path))
        result = BootstrapResult(project_root=project_root)
        self._ensure_dirs(project_root)
        templates = self._templates(project_root)

        for rel_path, content in templates.items():
            abs_path = os.path.join(project_root, rel_path)
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            before_exists = os.path.exists(abs_path)
            if before_exists and not force:
                result.skipped_files.append(rel_path)
                continue
            with open(abs_path, "w", encoding="utf-8") as f:
                f.write(content.rstrip() + "\n")
            if force and before_exists:
                result.overwritten_files.append(rel_path)
            else:
                result.created_files.append(rel_path)
        return result

    def open_bootstrap(self, project_path: str) -> OpenBootstrapResult:
        project_root = os.path.abspath(os.path.expanduser(project_path))
        result = OpenBootstrapResult(project_root=project_root, is_macos=platform.system() == "Darwin")
        file_paths = [os.path.join(project_root, rel) for rel in self.BOOTSTRAP_FILES]
        existing_paths = [path for path in file_paths if os.path.exists(path)]

        if not result.is_macos:
            result.manual_files.extend(existing_paths)
            return result

        for abs_path in existing_paths:
            try:
                cmd = ["open", "-a", "TextEdit", abs_path]
                subprocess.run(cmd, capture_output=True, text=True, timeout=10, check=False)
                result.opened_files.append(abs_path)
            except Exception as e:
                result.open_errors.append(f"{abs_path}: {str(e)}")

        return result

    def validate_bootstrap(self, project_path: str) -> ValidateBootstrapResult:
        project_root = os.path.abspath(os.path.expanduser(project_path))
        result = ValidateBootstrapResult(project_root=project_root, ok=True)
        required_files = [
            "README.md",
            "AGENTS.md",
            "docs/ARCHITECTURE.md",
            "docs/DEVELOPMENT_PLAN.md",
            self.PLAN_FILE,
        ]

        for rel_path in required_files:
            abs_path = os.path.join(project_root, rel_path)
            if not os.path.exists(abs_path):
                result.items.append(ValidationItem(rel_path, "ERROR", "文件不存在"))
                result.errors.append(f"{rel_path} 不存在")
                continue
            if not self._is_nonempty(abs_path):
                result.items.append(ValidationItem(rel_path, "ERROR", "文件为空"))
                result.errors.append(f"{rel_path} 为空")
                continue
            result.items.append(ValidationItem(rel_path, "PASS", "文件存在且非空"))

        plan_path = os.path.join(project_root, self.PLAN_FILE)
        if os.path.exists(plan_path) and self._is_nonempty(plan_path):
            plan_text = Path(plan_path).read_text(encoding="utf-8", errors="replace")
            parsed = self._parse_plan_bundle_yaml_subset(plan_text)
            result.parsed_versions = parsed.get("versions", [])
            if not parsed.get("project_name"):
                result.errors.append("plan-bundle 缺少 project_name")
            if not parsed.get("plan_version"):
                result.errors.append("plan-bundle 缺少 plan_version")
            if not parsed.get("versions"):
                result.errors.append("plan-bundle 缺少 versions")
            for version in parsed.get("versions", []):
                name = version.get("version") or "unknown"
                if not version.get("version"):
                    result.errors.append("某个版本缺少 version")
                if not version.get("name"):
                    result.errors.append(f"{name} 缺少 name")
                if not version.get("allowed_files"):
                    result.errors.append(f"{name} 缺少 allowed_files")
                if not version.get("acceptance_commands"):
                    result.errors.append(f"{name} 缺少 acceptance_commands")
            risks = self._detect_acceptance_command_risks(parsed.get("versions", []))
            for risk in risks:
                result.errors.append(risk)

            if not result.errors:
                result.items.append(ValidationItem(self.PLAN_FILE, "PASS", "Plan Bundle 解析通过"))
            else:
                result.items.append(ValidationItem(self.PLAN_FILE, "ERROR", "Plan Bundle 存在结构或命令风险"))
        else:
            result.errors.append("plan-bundle.yaml 不存在或为空")

        result.ok = len(result.errors) == 0
        return result

    def render_validate_report(self, validation: ValidateBootstrapResult) -> str:
        lines = [
            f"项目：{validation.project_root}",
            "Bootstrap 校验结果：",
        ]
        for item in validation.items:
            prefix = "✅" if item.status == "PASS" else "❌"
            lines.append(f"{prefix} {item.name} - {item.message}")
        if validation.warnings:
            lines.append("")
            lines.append("警告：")
            for warning in validation.warnings:
                lines.append(f"- {warning}")
        if validation.errors:
            lines.append("")
            lines.append("错误：")
            for error in validation.errors:
                lines.append(f"- {error}")
        lines.append("")
        lines.append("结论：" + ("通过" if validation.ok else "失败"))
        return "\n".join(lines)

    def _ensure_dirs(self, project_root: str) -> None:
        os.makedirs(project_root, exist_ok=True)
        os.makedirs(os.path.join(project_root, "docs"), exist_ok=True)
        os.makedirs(os.path.join(project_root, self.RUNNER_DIR, "plans"), exist_ok=True)
        os.makedirs(os.path.join(project_root, self.RUNNER_DIR, "bootstrap"), exist_ok=True)

    def _is_nonempty(self, path: str) -> bool:
        try:
            return os.path.getsize(path) > 0
        except OSError:
            return False

    def _templates(self, project_root: str) -> dict[str, str]:
        project_name = os.path.basename(project_root.rstrip(os.sep)) or "new-project"
        now = datetime.now().strftime("%Y-%m-%d")
        return {
            "README.md": f"""# {project_name}

## 项目目标

- 在这里写清楚产品目标和第一阶段范围。

## 当前状态

- Bootstrap 草稿已生成，待补充内容。

## 最小使用方式

```bash
# 在这里写运行方式
```

## 开发状态

- [ ] 文档完善
- [ ] 计划可导入
- [ ] v0.1 可执行

## 版本计划链接

- [开发计划](docs/DEVELOPMENT_PLAN.md)
""",
            "AGENTS.md": """# AGENTS

## 角色

你是本项目的代码实现代理。

## 执行规则

- 修改前先输出文件计划。
- 只实现当前版本范围。
- 只修改 allowed_files 内文件。
- 完成后输出 changed files / command results / risks。

## 安全边界

- 当前版本未允许时，不调用真实外部服务。
- 当前版本未允许时，不修改业务生产配置。
- 当前版本未允许时，不提交 git。
""",
            "docs/ARCHITECTURE.md": f"""# 架构草稿（{project_name}）

## 系统目标

- 

## 模块划分

- 

## 数据流

- 

## 状态流

- 

## 技术边界

- 

## 待决策问题

- 
""",
            "docs/DEVELOPMENT_PLAN.md": """# 开发计划草稿

## v0.1

- 目标：
- 范围：
- allowed_files：
- acceptance_commands：

## v0.2

- 目标：
- 范围：
- allowed_files：
- acceptance_commands：

## v0.3

- 目标：
- 范围：
- allowed_files：
- acceptance_commands：

## v1.0

- 目标：
- 范围：
- allowed_files：
- acceptance_commands：
""",
            f"{self.RUNNER_DIR}/plans/plan-bundle.yaml": f"""project_name: "{project_name}"
plan_version: "0.1.0"
generated_at: "{now}"

review_policy:
  enabled: true
  mode: manual_gate
  after_versions:
    - "v0.1"

commit_policy:
  enabled: true
  mode: manual_gate
  after_acceptance_pass: true
  require_clean_scope: true
  include_runner_runtime_files: false
  require_confirm: true
  require_commit_before_continue: false

default_acceptance_commands:
  - command: "python3 -m compileall -q ."
    timeout_seconds: 600
    continue_on_failure: false

versions:
  - version: "v0.1"
    name: "项目骨架与最小入口"
    description: "建立最小可运行骨架，完成基础验收。"
    prompt_file: "v0.1.md"
    enabled: true
    context_files:
      - "README.md"
      - "docs/ARCHITECTURE.md"
      - "docs/DEVELOPMENT_PLAN.md"
    allowed_files:
      - "README.md"
      - "docs/**"
      - "src/**"
      - "tests/**"
      - "pyproject.toml"
    forbidden_files:
      - ".env*"
      - "secrets/**"
    acceptance_commands:
      - command: "python3 -m compileall -q ."
        timeout_seconds: 600
        continue_on_failure: false
      - command: ".venv/bin/python -m pytest tests -q"
        timeout_seconds: 900
        continue_on_failure: false
    manual_acceptance:
      - "CLI 可以正常启动"
    out_of_scope:
      - "不接入真实外部 API"
""",
            f"{self.RUNNER_DIR}/bootstrap/CHATGPT_CONTEXT.md": f"""# ChatGPT 上下文草稿

## 项目

- 项目名：{project_name}
- 目标路径：{project_root}

## 你希望 ChatGPT 输出的内容

1. README.md 草稿
2. AGENTS.md 草稿
3. docs/ARCHITECTURE.md 草稿
4. docs/DEVELOPMENT_PLAN.md 草稿
5. .colameta/plans/plan-bundle.yaml 草稿

## 约束

- ChatGPT 只输出文档内容，便于手工复制到本地文件。
- ChatGPT 输出应包含版本计划、allowed_files、acceptance_commands。
- ChatGPT 当前阶段不直接修改业务代码。
""",
            f"{self.RUNNER_DIR}/bootstrap/BOOTSTRAP_CHECKLIST.md": """# Bootstrap Checklist

- [ ] 与 ChatGPT 明确产品目标和范围
- [ ] 填写 README.md
- [ ] 填写 AGENTS.md
- [ ] 填写 docs/ARCHITECTURE.md
- [ ] 填写 docs/DEVELOPMENT_PLAN.md
- [ ] 填写 .colameta/plans/plan-bundle.yaml
- [ ] 运行 `colameta validate-bootstrap <project_path>`
- [ ] 通过后导入计划并启动 Runner
""",
        }

    def _parse_plan_bundle_yaml_subset(self, text: str) -> dict[str, Any]:
        data: dict[str, Any] = {
            "project_name": "",
            "plan_version": "",
            "versions": [],
        }
        lines = text.splitlines()
        current_version: dict[str, Any] | None = None
        in_versions = False
        in_allowed = False
        in_acceptance = False
        command_indent = -1
        block_capture = False
        block_lines: list[str] = []
        block_target: list[str] | None = None
        block_base_indent = 0

        for raw_line in lines:
            line = raw_line.rstrip("\n")
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            indent = len(line) - len(line.lstrip(" "))

            if block_capture:
                if indent <= block_base_indent:
                    if block_target is not None:
                        block_target.append("\n".join(block_lines).rstrip())
                    block_capture = False
                    block_lines = []
                    block_target = None
                    # 当前行继续按普通逻辑处理
                else:
                    block_lines.append(line[block_base_indent + 2:] if len(line) > block_base_indent + 2 else "")
                    continue

            if stripped.startswith("project_name:"):
                data["project_name"] = self._yaml_scalar(stripped.split(":", 1)[1].strip())
                continue
            if stripped.startswith("plan_version:"):
                data["plan_version"] = self._yaml_scalar(stripped.split(":", 1)[1].strip())
                continue
            if stripped == "versions:":
                in_versions = True
                continue
            if not in_versions:
                continue

            if re.match(r"^- version:\s*", stripped):
                value = stripped.split(":", 1)[1].strip()
                current_version = {
                    "version": self._yaml_scalar(value),
                    "name": "",
                    "allowed_files": [],
                    "acceptance_commands": [],
                }
                data["versions"].append(current_version)
                in_allowed = False
                in_acceptance = False
                command_indent = indent
                continue

            if current_version is None:
                continue

            if indent <= command_indent and stripped.startswith("- ") and not stripped.startswith("- command:"):
                in_allowed = False
                in_acceptance = False

            if stripped.startswith("name:"):
                current_version["name"] = self._yaml_scalar(stripped.split(":", 1)[1].strip())
                continue
            if stripped == "allowed_files:":
                in_allowed = True
                in_acceptance = False
                continue
            if stripped == "acceptance_commands:":
                in_acceptance = True
                in_allowed = False
                continue

            if in_allowed and stripped.startswith("- "):
                current_version["allowed_files"].append(self._yaml_scalar(stripped[2:].strip()))
                continue

            if in_acceptance and stripped.startswith("- command:"):
                command_value = stripped.split(":", 1)[1].strip()
                if command_value == "|":
                    block_capture = True
                    block_lines = []
                    block_target = current_version["acceptance_commands"]
                    block_base_indent = indent
                    continue
                current_version["acceptance_commands"].append(self._yaml_scalar(command_value))
                continue

        if block_capture and block_target is not None:
            block_target.append("\n".join(block_lines).rstrip())
        return data

    def _yaml_scalar(self, value: str) -> str:
        stripped = value.strip()
        if len(stripped) >= 2 and ((stripped[0] == '"' and stripped[-1] == '"') or (stripped[0] == "'" and stripped[-1] == "'")):
            return stripped[1:-1]
        return stripped

    def _detect_acceptance_command_risks(self, versions: list[dict[str, Any]]) -> list[str]:
        risks: list[str] = []
        risky_single_tokens = {"{", "}", "JSON", "PY", ")"}
        for version in versions:
            vname = version.get("version") or "unknown"
            commands = version.get("acceptance_commands") or []
            for idx, command in enumerate(commands, start=1):
                text = (command or "").strip()
                if text in risky_single_tokens:
                    risks.append(f"{vname} acceptance_commands[{idx}] 存在拆分风险：{text}")
                if "CHANGE_ID=$(python3 - <<'PY'" in text:
                    risks.append(f"{vname} acceptance_commands[{idx}] 包含跨命令变量块风险")
                if "<<'JSON'" in text and "JSON" not in text.split("<<'JSON'", 1)[1]:
                    risks.append(f"{vname} acceptance_commands[{idx}] 发现未闭合 JSON here-doc 风险")
                if "<<'PY'" in text and "PY" not in text.split("<<'PY'", 1)[1]:
                    risks.append(f"{vname} acceptance_commands[{idx}] 发现未闭合 PY here-doc 风险")
        return risks
