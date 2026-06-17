from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ExecutionStandardSection:
    section: str
    title: str
    purpose: str
    content: str
    checklist: tuple[str, ...]
    reject_patterns: tuple[str, ...] = ()
    examples: tuple[dict[str, Any], ...] = ()


PLAN_FORMAT = ExecutionStandardSection(
    section="plan_format",
    title="Runner plan.json 格式标准",
    purpose="Before generating or editing .colameta/plan.json, call this section first.",
    content=(
        "一、版本对象必填字段：\n"
        "- version：非空字符串，稳定版本号，例如 v1.40\n"
        "- name：非空字符串\n"
        "- description：非空字符串，说明本版本目标\n"
        "- prompt_file：非空字符串，指向 .colameta/prompts 下的 prompt 文件\n"
        "- enabled：布尔值\n"
        "- allowed_files：非空 list[str]，必须具体，不能用 **/* 作为默认\n"
        "- acceptance_commands：list[object]，每项必须是单条独立命令对象\n\n"
        "二、推荐字段：\n"
        "- forbidden_files\n"
        "- context_files\n"
        "- manual_acceptance\n"
        "- out_of_scope\n"
        "- execution.provider\n\n"
        "三、acceptance_commands 严格格式：\n"
        "每条必须是：\n"
        "{\n"
        '  "command": "python3 -m compileall -q .",\n'
        '  "timeout_seconds": 600,\n'
        '  "continue_on_failure": false\n'
        "}\n\n"
        "硬性规则：\n"
        "- command 必须是非空字符串\n"
        "- command 必须是一条独立命令\n"
        "- timeout_seconds 必须是正整数\n"
        "- continue_on_failure 必须是布尔值\n"
        "- cwd 可选，但如果出现必须是相对路径或受控路径\n"
        "- 不允许多行命令\n"
        "- 不允许 here-doc\n"
        "- 不允许跨命令变量\n"
        "- 不允许依赖上一条命令 export/cd/source 的状态\n"
        "- 不允许把多个逻辑命令塞进一条 command\n"
        "- 不允许 curl | sh\n"
        "- 不允许 rm -rf\n"
        "- 不允许 git reset / git clean / git merge / git rebase / git push\n"
        "- 不允许交互式命令\n"
        "- 不允许缺少 timeout_seconds\n"
        "- 不允许 timeout_seconds 为字符串\n"
        "- 不允许 continue_on_failure 缺失；必须显式 true/false"
    ),
    checklist=(
        "每个版本有明确 scope",
        "allowed_files 不为空且具体",
        "forbidden_files 包含不应触碰路径",
        "acceptance_commands 每条都是独立单行命令",
        "每条 acceptance command 都有 timeout_seconds 和 continue_on_failure",
        "out_of_scope 明确说明本版本不做什么",
        "execution.provider 只在需要覆盖默认执行器时设置",
        "如果是首次完整 plan，已参考 bootstrap_plan 并生成可下载 JSON 文件",
    ),
    reject_patterns=(
        "multiline_command",
        "here_doc",
        "cross_command_variable",
        "missing_timeout_seconds",
        "missing_continue_on_failure",
        "broad_allowed_files",
        "dangerous_git_command",
        "destructive_shell_command",
        "interactive_command",
    ),
    examples=(
        {
            "label": "坏例1：here-doc / 多行",
            "value": {
                "acceptance_commands": [
                    {
                        "command": "cat <<'EOF' > /tmp/test.py\nprint('x')\nEOF\npython3 /tmp/test.py",
                        "timeout_seconds": 60,
                        "continue_on_failure": False,
                    }
                ]
            },
        },
        {
            "label": "坏例2：跨命令变量",
            "value": {
                "acceptance_commands": [
                    {
                        "command": "TMP=/tmp/a",
                        "timeout_seconds": 60,
                        "continue_on_failure": False,
                    },
                    {
                        "command": "python3 $TMP/test.py",
                        "timeout_seconds": 60,
                        "continue_on_failure": False,
                    },
                ]
            },
        },
        {
            "label": "坏例3：缺少参数",
            "value": {
                "acceptance_commands": [{"command": "python3 -m compileall -q ."}]
            },
        },
        {
            "label": "好例：完整独立命令",
            "value": {
                "acceptance_commands": [
                    {
                        "command": "python3 -m compileall -q .",
                        "timeout_seconds": 600,
                        "continue_on_failure": False,
                    },
                ]
            },
        },
    ),
)

BOOTSTRAP_PLAN = ExecutionStandardSection(
    section="bootstrap_plan",
    title="首次 Runner plan 生成与文件交付标准",
    purpose="Before generating an initial Runner plan for a new project, call this section after plan_format.",
    content=(
        "一、适用场景：\n"
        "- 新项目尚未有 .colameta/plan.json\n"
        "- ChatGPT 需要根据用户项目目标生成初始 Runner plan\n"
        "- 这是首次 plan 交付标准，不是版本增量 patch 标准\n\n"
        "二、推荐流程：\n"
        '1. ChatGPT 调用 get_runner_execution_standards(section="plan_format")\n'
        '2. ChatGPT 调用 get_runner_execution_standards(section="bootstrap_plan")\n'
        "3. ChatGPT 根据用户项目目标生成完整 plan JSON\n"
        "4. ChatGPT 将 plan JSON 作为可下载 .json 文件交付\n"
        "5. 用户下载文件到本地，例如 /tmp/runner-bootstrap-plan.json\n"
        "6. 用户在本地运行 Runner CLI 导入\n"
        "7. Runner 本地执行 lint/校验后再写入 .colameta/plan.json\n\n"
        "三、必须强调：\n"
        "- 不要让用户手动复制超长 JSON\n"
        "- 不要通过 MCP 直接写 .colameta/plan.json\n"
        "- 不要通过 shell 重定向远程写本地文件\n"
        "- 不要跳过 plan_format\n"
        "- 不要省略 prompt_file 与 prompt 内容的对应关系\n"
        "- 不要省略 acceptance_commands 的 timeout_seconds 和 continue_on_failure\n"
        "- 不要使用断行命令、here-doc、跨命令变量\n"
        "- 不要把执行器模型选择写成强假设；provider 可选，模型由用户在执行器里配置默认值\n\n"
        "四、下载文件交付要求：\n"
        "- 文件名建议：runner-bootstrap-plan.json\n"
        "- JSON 必须 UTF-8\n"
        "- JSON 必须可被本地 Runner CLI 读取\n"
        "- JSON 不应包含注释\n"
        "- JSON 顶层结构必须清晰\n"
        "- 如果当前 Runner 尚未实现 import-bootstrap-plan，ChatGPT 应说明这是 bootstrap plan 文件，需要用户保存后按当前可用导入命令或后续 bootstrap import 命令导入\n\n"
        "五、建议本地导入命令文案：\n"
        "如果 import-bootstrap-plan 已支持：\n"
        "./bin/colameta import-bootstrap-plan /path/to/project /path/to/runner-bootstrap-plan.json\n\n"
        "如果当前版本尚未支持 import-bootstrap-plan：\n"
        "请用户先保存文件，待本地 bootstrap import 能力可用后导入；不要通过 MCP 直接写入 plan.json。\n\n"
        "六、首次 plan 必须包含：\n"
        "- project/name 或项目说明\n"
        "- versions 列表\n"
        "- 每个 version 的 version/name/description/prompt_file/enabled/allowed_files/acceptance_commands\n"
        "- prompts 内容或 prompt_file 对应的生成策略\n"
        "- out_of_scope\n"
        "- manual_acceptance\n"
        "- context_files\n"
        "- execution.provider 可选"
    ),
    checklist=(
        "已先读取 plan_format",
        "输出为可下载 JSON 文件",
        "不要求用户复制长 JSON",
        "不通过 MCP 直接写 plan.json",
        "每个版本的 acceptance_commands 符合 plan_format",
        "每个版本有具体 allowed_files",
        "每个版本有 out_of_scope",
        "prompt_file 与 prompt 内容对应关系明确",
        "导入动作由用户本地 CLI 执行",
    ),
    reject_patterns=(
        "copy_large_json_manually",
        "mcp_direct_plan_write",
        "missing_plan_format_check",
        "missing_prompt_file_mapping",
        "missing_acceptance_command_fields",
        "multiline_acceptance_command",
        "here_doc",
        "cross_command_variable",
        "broad_allowed_files",
    ),
    examples=(
        {
            "label": "好例：可下载文件交付",
            "value": {
                "delivery": "downloadable_file",
                "filename": "runner-bootstrap-plan.json",
                "local_import": "./bin/colameta import-bootstrap-plan /path/to/project /tmp/runner-bootstrap-plan.json",
                "notes": "用户下载文件后在本地执行导入。",
            },
        },
        {
            "label": "坏例：仅聊天消息交付",
            "value": {
                "delivery": "chat_message_only",
                "problem": "要求用户手动复制超长 JSON，容易截断、错粘或污染格式。",
            },
        },
    ),
)

VERSION_PROMPT = ExecutionStandardSection(
    section="version_prompt",
    title="版本提示词生成标准",
    purpose="Before generating current-prompt.md or a version development task, call this section.",
    content=(
        "版本提示词必须包含：\n"
        "- 明确目标\n"
        "- 明确允许修改文件\n"
        "- 明确禁止修改文件\n"
        "- 明确 out_of_scope\n"
        "- 明确验收命令\n"
        "- 要求输出 changed files、验证结果、风险\n\n"
        "禁止行为：\n"
        "- 不得扩大 scope\n"
        "- 不得改未授权文件\n"
        "- 不得自行提交 git commit\n"
        "- 不得删除分支或 reset/clean"
    ),
    checklist=(
        "目标清晰可验证",
        "scope 边界明确",
        "验收命令与 plan.json 一致",
        "不允许的操作在提示词中被明确禁止",
    ),
    reject_patterns=(
        "no_scope_definition",
        "implicit_git_commit",
        "expanded_allowed_files",
        "destructive_git_command",
    ),
)

FIX_PROMPT = ExecutionStandardSection(
    section="fix_prompt",
    title="修复提示词生成标准",
    purpose="Before generating current-fix-prompt.md after acceptance failure, call this section.",
    content=(
        "修复提示词必须：\n"
        "- 只修当前版本失败\n"
        "- 引用失败命令和错误摘要\n"
        "- 不扩大需求\n"
        "- 不重写无关文件\n"
        "- 修复后说明重新运行哪些 acceptance_commands\n\n"
        "如果失败原因不明，先输出诊断，不要大改。"
    ),
    checklist=(
        "引用失败命令输出",
        "scope 不扩大",
        "修复后验证命令明确",
    ),
)

PLAN_PATCH = ExecutionStandardSection(
    section="plan_patch",
    title="Plan patch 预览标准",
    purpose="Before calling preview_insert_version or preview_update_version, call this section.",
    content=(
        "任何 plan patch 都必须先符合 plan_format 标准。\n"
        "execution.provider 可选，只能是 pi/codex/opencode。\n"
        "acceptance_commands 必须复用 plan_format 的单命令规则。\n"
        "update execution 时替换整个 execution，不做模糊 merge。\n\n"
        "禁止行为：\n"
        "- 不允许写入 apply_plan_patch\n"
        "- 不允许通过 patch 扩大执行权限"
    ),
    checklist=(
        "patch 符合 plan_format",
        "provider 合法",
        "acceptance_commands 单命令",
    ),
)

DIFF_REVIEW = ExecutionStandardSection(
    section="diff_review",
    title="Diff 审查标准",
    purpose="Before reviewing executor or model changes, call this section.",
    content=(
        "审查工作区改动时检查：\n"
        "- 是否越界\n"
        "- 是否新增 shell=True\n"
        "- 是否新增 git add .\n"
        "- 是否新增 reset/clean/merge/rebase/push\n"
        "- 是否重新暴露 apply_plan_patch\n"
        "- 是否改状态机\n"
        "- Web/MCP 显示是否一致\n"
        "- 文档是否同步\n"
        "- 是否引入未受控文件读取\n"
        "- 是否改变安全默认值"
    ),
    checklist=(
        "无 shell=True",
        "无 git add .",
        "无 apply_plan_patch 暴露",
        "无状态机改动",
        "文档已同步",
    ),
)

EXECUTION_BRANCH = ExecutionStandardSection(
    section="execution_branch",
    title="执行安全分支标准",
    purpose="Before using low-cost or non-default executors, call this section.",
    content=(
        "标准流程：\n"
        "1. set-version-executor 设置版本执行器\n"
        "2. create-execution-branch 创建安全分支\n"
        "3. 在安全分支运行当前版本\n"
        "4. execution-branch-review 查看改动摘要\n"
        "5. 人工决定是否保留\n"
        "6. close-execution-branch 关闭记录\n\n"
        "坚决禁止：\n"
        "- Runner 不自动 checkout\n"
        "- Runner 不自动 merge\n"
        "- Runner 不自动 delete branch\n"
        "- Runner 不自动 reset/clean\n"
        "- Runner 不自动升级模型"
    ),
    checklist=(
        "非默认执行器前创建安全分支",
        "Runner 不自动操作 Git",
    ),
)

COMMIT_REVIEW = ExecutionStandardSection(
    section="commit_review",
    title="提交前审查标准",
    purpose="Before confirming a commit, call this section.",
    content=(
        "提交前必须确认：\n"
        "- compileall 通过\n"
        "- git diff --check 通过\n"
        "- forbidden patterns 检查\n"
        "- commit preview 通过\n"
        "- commit_content_signature 未过期\n"
        "- scope clean\n"
        "- acceptance passed"
    ),
    checklist=(
        "compileall 无错误",
        "diff 无 whitespace 错误",
        "无 shell=True",
        "无 git add .",
        "preview 未过期",
    ),
)

LOW_COST_EXECUTOR = ExecutionStandardSection(
    section="low_cost_executor",
    title="低成本执行器适用判断",
    purpose="Before deciding to use a low-cost model, call this section.",
    content=(
        "适合低成本执行：\n"
        "- 文档小改\n"
        "- UI 文案小改\n"
        "- 小范围 CLI 参数接线\n"
        "- 小型 adapter 接线\n"
        "- 已有模式复制\n\n"
        "不适合低成本执行：\n"
        "- 状态机重构\n"
        "- 安全边界设计\n"
        "- 大范围架构重构\n"
        "- OAuth\n"
        "- 复杂 Git 自动化\n"
        "- commit/apply 逻辑\n"
        "- 需要强推理的 bug\n\n"
        "规则：\n"
        "- 低模型执行应配合 execution branch\n"
        "- 失败后先 review summary，不直接让高模型清理混乱工作区\n"
        "- 不自动升级模型"
    ),
    checklist=(
        "任务适合低成本模型",
        "已创建安全分支",
        "失败后先 review 再评估",
    ),
)

EXECUTOR_SELECTION_STRATEGY = ExecutionStandardSection(
    section="executor_selection_strategy",
    title="执行器选择策略标准",
    purpose="Before writing plan versions, inserting patches, or generating version prompts, call this section to learn how to choose the right execution provider and model for each version.",
    content=(
        "一、前置要求——执行器可用性读取：\n"
        "在生成 plan、插入版本、更新版本提示词之前，ChatGPT 必须了解当前可用执行器和模型。\n\n"
        "1. 优先使用工具读取当前执行器 inventory 或 settings，例如 probe-models 结果中的可用 provider 和模型。\n"
        "2. 如果无法读取可用模型，使用已知 provider（codex、pi、opencode）和系统默认模型，并在 version.execution.notes 中\n"
        '   注明"不确定具体模型，按默认模型执行"。\n'
        "3. 不得凭空编造不可用 provider 或 model。\n"
        "4. 不得写入 schema 不支持的 provider 名称。\n"
        "5. provider 必须是 Runner 支持的执行器：codex、pi、opencode，除非项目已扩展 registry。\n"
        "6. 支持多版本的场景下，每个版本独立评估，不跨版本混合执行器依赖。\n\n"
        "二、风险分层与推荐填写方式：\n"
        "按任务风险、复杂度、文件范围、是否涉及核心链路，选择合适 provider/model。\n"
        "version.execution 是版本级显式选择，provider / model / pi_model / codex_model / opencode_model / capability_level / lane / notes\n"
        "都可按需使用。\n\n"
        "低风险任务：\n"
        "- docs-only、README/docs 文案、小范围 CSS/UI 文案\n"
        "- 测试断言文案、纯展示/无状态/低耦合修改\n"
        "- → 推荐：provider 优先低成本执行器（例如 pi，或 inventory 中最低成本可用 provider）\n"
        "- → capability_level: low\n"
        "- → lane: cheap-docs / cheap-ui / low-cost\n"
        "- → notes: 说明低风险、低成本执行原因\n"
        "- → 可指定 pi_model 或 model/model_name（如果可用模型已知）\n\n"
        "中风险任务：\n"
        "- 单模块源码修改、Web 前端轻量逻辑、单个薄 API\n"
        "- 非核心业务逻辑 bugfix、测试驱动的小范围修复\n"
        "- → 推荐：provider 使用 codex 或 inventory 中中等能力 provider\n"
        "- → capability_level: medium\n"
        "- → lane: standard-dev / deterministic\n"
        "- → notes: 说明风险中等、为什么不使用最低成本执行器\n\n"
        "高风险任务：\n"
        "- Runner 状态机、Git/commit workflow、MCP Action/权限边界\n"
        "- 执行器 workflow、plan patch/state/runtime 持久化\n"
        "- acceptance/recovery/transaction/consistency 关键链路、多文件一致性重构\n"
        "- → 推荐：provider 使用 codex 或 inventory 中高能力 provider\n"
        "- → capability_level: high\n"
        "- → lane: critical-runner / high-quality\n"
        "- → notes: 说明高风险，不为省 token 降级\n"
        "- → 可指定 codex_model 或 model/model_name（如果高能力模型已知）\n\n"
        "三、禁止行为：\n"
        "1. 不允许所有版本无脑使用 codex——必须按风险分配合适 provider。\n"
        "2. 不允许所有版本无脑使用最低成本执行器——高风险任务必须使用高能力 provider/model。\n"
        "3. 不允许为了节省 token 降低高风险任务能力。\n"
        "4. 不得凭空编造不可用 provider 或 model。\n"
        "5. 不得写入 schema 不支持的字段。\n"
        "6. 如果设置 execution.provider 或 model，必须在 notes 中说明选择原因。\n\n"
        "四、交叉引用：\n"
        "- 高风险或非默认执行器版本建议参考 execution_branch 标准，决定是否需要安全分支。\n"
        "- 低风险任务可参考 low_cost_executor 标准进一步确认是否适合低成本执行。\n\n"
        "五、schema 支持字段：\n"
        "执行器选择可用字段（VersionExecutionProfile）：\n"
        "- provider: Optional[str] — 执行器名称，取值 codex / pi / opencode\n"
        "- model: Optional[str] — 通用模型标识\n"
        "- model_name: Optional[str] — 模型名称\n"
        "- pi_model: Optional[str] — Pi 执行器指定模型\n"
        "- codex_model: Optional[str] — Codex 执行器指定模型\n"
        "- opencode_model: Optional[str] — OpenCode 执行器指定模型\n"
        "- capability_level: Optional[str] — 能力评级，取值 low / medium / high\n"
        "- lane: Optional[str] — 执行通道提示，取值由版本设计者自定\n"
        "- notes: Optional[str] — 选择原因说明，必读"
    ),
    checklist=(
        "已读取当前可用执行器 inventory 或 settings",
        "已按风险分层为当前版本选择合适 provider/model",
        "低风险任务优先考虑低成本 provider（如 pi）而非无脑 codex",
        "高风险任务未因节省 token 而降级",
        "版本未无脑全用 codex",
        "版本未无脑全用最低成本执行器",
        "notes 中说明了 provider/model 选择原因",
        "provider 属于支持的执行器（codex/pi/opencode）",
        "字段不超出 schema 支持范围",
        "多版本场景下各版本独立评估",
    ),
    reject_patterns=(
        "all_versions_codex",
        "all_versions_cheapest",
        "high_risk_downgraded_for_tokens",
        "fabricated_provider_or_model",
        "unsupported_schema_field",
        "missing_provider_notes",
        "cross_version_executor_dependency",
    ),
    examples=(
        {
            "label": "低风险 docs-only 示例",
            "value": {
                "version": "v0.1",
                "risk_level": "low",
                "execution": {
                    "provider": "pi",
                    "capability_level": "low",
                    "lane": "cheap-docs",
                    "notes": "docs-only change; low risk and suitable for lower-cost executor",
                },
            },
        },
        {
            "label": "低风险 UI/CSS 示例",
            "value": {
                "version": "v0.2",
                "risk_level": "low",
                "execution": {
                    "provider": "pi",
                    "capability_level": "low",
                    "lane": "cheap-ui",
                    "notes": "CSS-only Web UI adjustment; no state or backend changes",
                },
            },
        },
        {
            "label": "中风险 Web bugfix 示例",
            "value": {
                "version": "v0.3",
                "risk_level": "medium",
                "execution": {
                    "provider": "codex",
                    "capability_level": "medium",
                    "lane": "standard-dev",
                    "notes": "small Web JS/CSS bugfix with regression tests",
                },
            },
        },
        {
            "label": "高风险 Runner workflow 示例",
            "value": {
                "version": "v0.4",
                "risk_level": "high",
                "execution": {
                    "provider": "codex",
                    "capability_level": "high",
                    "lane": "critical-runner",
                    "notes": "touches Runner workflow or safety boundary; do not downgrade for token savings",
                },
            },
        },
        {
            "label": "低风险示例（含模型字段）",
            "value": {
                "version": "v0.5",
                "risk_level": "low",
                "execution": {
                    "provider": "pi",
                    "pi_model": "pi-1.5-fast",
                    "capability_level": "low",
                    "lane": "cheap-docs",
                    "notes": "known pi model available for docs update",
                },
            },
        },
        {
            "label": "高风险示例（含模型字段）",
            "value": {
                "version": "v0.6",
                "risk_level": "high",
                "execution": {
                    "provider": "codex",
                    "codex_model": "codex-sonnet",
                    "capability_level": "high",
                    "lane": "critical-runner",
                    "notes": "state machine change; high capability model required",
                },
            },
        },
    ),
)

_SUPPORTED_SECTIONS: dict[str, ExecutionStandardSection] = {
    s.section: s
    for s in (
        PLAN_FORMAT,
        BOOTSTRAP_PLAN,
        VERSION_PROMPT,
        FIX_PROMPT,
        PLAN_PATCH,
        DIFF_REVIEW,
        EXECUTION_BRANCH,
        COMMIT_REVIEW,
        LOW_COST_EXECUTOR,
        EXECUTOR_SELECTION_STRATEGY,
    )
}

STANDARDS_VERSION = "v1"


def list_standard_sections() -> list[str]:
    return list(_SUPPORTED_SECTIONS.keys())


def _section_to_dict(section: ExecutionStandardSection) -> dict[str, Any]:
    return {
        "section": section.section,
        "title": section.title,
        "purpose": section.purpose,
        "content": section.content,
        "checklist": section.checklist,
        "reject_patterns": section.reject_patterns,
        "examples": section.examples,
    }


def get_execution_standards(section: str | None = None) -> dict[str, Any]:
    if not section:
        section = "all"
    normalized = str(section).strip().lower()
    if normalized == "all":
        sections = [_section_to_dict(s) for s in _SUPPORTED_SECTIONS.values()]
        return {
            "ok": True,
            "standards_version": STANDARDS_VERSION,
            "section": "all",
            "supported_sections": list_standard_sections(),
            "sections": sections,
        }

    sec = _SUPPORTED_SECTIONS.get(normalized)
    if sec is None:
        return {
            "ok": False,
            "error_code": "UNKNOWN_STANDARD_SECTION",
            "message": f"不支持的执行标准 section：{section}",
            "supported_sections": list_standard_sections(),
        }

    return {
        "ok": True,
        "standards_version": STANDARDS_VERSION,
        **_section_to_dict(sec),
    }
