import os
from dataclasses import dataclass
from datetime import datetime

from adapters.codex_review_adapter import CodexReviewAdapter
from runner.workspace import ProjectWorkspace


@dataclass
class StageReviewResult:
    report_path: str
    log_path: str
    status: str
    short_summary: str
    reviewed_at: str


class StageReviewer:
    def __init__(self, workspace: ProjectWorkspace, adapter: CodexReviewAdapter | None = None):
        self.workspace = workspace
        self.adapter = adapter or CodexReviewAdapter()

    def run_review(self) -> StageReviewResult:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        reports_dir = os.path.join(self.workspace.runner_dir, "reports")
        os.makedirs(reports_dir, exist_ok=True)
        os.makedirs(self.workspace.logs_dir, exist_ok=True)

        report_path = os.path.join(reports_dir, f"stage-review-{timestamp}.md")
        summary_file = os.path.join(reports_dir, f"stage-review-{timestamp}.summary.md")
        log_path = os.path.join(self.workspace.logs_dir, f"stage-review-{timestamp}.log")

        prompt = self._build_review_prompt()
        self.adapter.execute_review(
            project_root=self.workspace.workspace_root,
            prompt=prompt,
            summary_file=summary_file,
            log_path=log_path,
        )

        summary = self._read_summary_file(summary_file)
        if not summary:
            summary = f"阶段审查已完成，但未返回可展示摘要。完整日志见：{log_path}"

        self._write_report(report_path, summary)

        short_summary = self._truncate_text(summary, 600)
        reviewed_at = datetime.now().astimezone().isoformat()
        return StageReviewResult(
            report_path=report_path,
            log_path=log_path,
            status="completed",
            short_summary=short_summary,
            reviewed_at=reviewed_at,
        )

    def _build_review_prompt(self) -> str:
        return """你是代码审查代理。只读审查，不要修改文件，不要运行修复命令，不要生成 patch。\n\n只读审查。不要编辑文件。不要运行会修改文件的命令。不要提交 git。\n\n审查目标：\n1. 找出阑尾代码、死代码、重复代码、无用模块、无用文件。\n2. 找出可以安全删除、合并、简化的内容。\n3. 找出性能优化点。\n4. 找出架构优化点。\n5. 找出状态机 / 执行流 / 人机交互的风险。\n6. 找出文档和实现不一致处。\n7. 区分“必须修”“建议优化”“可暂缓”。\n8. 不要硬造问题。没有问题就写“未发现明确问题”。\n\n输出格式必须是 Markdown：\n\n# 阶段审查报告\n\n## 结论\n- [一句话结论]\n\n## 必须修\n- [问题]\n  - 位置：\n  - 原因：\n  - 建议处理：\n\n## 建议优化\n- ...\n\n## 可暂缓\n- ...\n\n## 可删除 / 合并候选\n- ...\n\n## 性能优化候选\n- ...\n\n## 架构优化候选\n- ...\n\n## 文档一致性问题\n- ...\n\n## 不建议处理\n- ...\n"""

    def _read_summary_file(self, summary_file: str) -> str:
        try:
            if not os.path.exists(summary_file):
                return ""
            with open(summary_file, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception:
            return ""

    def _write_report(self, report_path: str, summary: str) -> None:
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(summary)
            if summary and not summary.endswith("\n"):
                f.write("\n")

    def _truncate_text(self, text: str, max_length: int) -> str:
        if len(text) <= max_length:
            return text
        return text[:max_length] + "\n...(已截断)"
