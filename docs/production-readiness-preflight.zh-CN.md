# Production Readiness Preflight

状态：`dev_runtime_ready_for_readiness_trial`

本文说明 ColaMeta 服务如何在进入稳定服务替换前，先做只读生产级预检。它不是稳定部署授权，不授权替换 `/home/jenn/tools/colameta`，不授权 service restart、push、executor run、route transition、release 或 deploy。

## 首选工具

网页端 GPT 或本地操作者连接 MCP 后，可以调用：

```json
{
  "name": "get_stable_promotion_readiness",
  "arguments": {
    "project_name": "colameta-self-dev"
  }
}
```

这个工具只读，返回：

- 当前服务加载代码是否能证明和 checkout 一致
- 当前项目 Git HEAD、branch、worktree clean 状态
- 本地与 `origin/main` 的 ahead/behind 只读摘要
- 网页端 GPT 所需 MCP 入口工具是否可见
- `thin_governed_loop_preview` 是否可用
- 稳定运行目录 `/home/jenn/tools/colameta` 是否存在、是否有可证明 Git HEAD
- 候选 tracked-file artifact manifest 摘要与 `manifest_sha256`
- `local_blockers`
- `warnings`
- 稳定替换前仍需要的外部材料

## 结果怎么读

`readiness_status=stable_promotion_review_candidate` 的意思是：

当前运行候选可以进入稳定晋升审查，但还不是正式稳定生产服务。

它仍然需要：

- 把 `candidate_artifact_manifest` 摘要与 sha256 写入晋升材料
- rollback / rehearsal 证明
- Commander 对稳定服务替换的精确授权

`stable_production_ready` 当前必须保持 `false`，因为只读工具不能替代部署授权、发布物证明或 rollback receipt。

## candidate_artifact_manifest

`candidate_artifact_manifest` 是服务现场计算的只读候选摘要：

- 只覆盖 Git tracked files
- 不包含 `.git`、`.venv`、build artifacts、ignored runtime state、untracked files
- 返回 `manifest_sha256`、tracked path list hash、文件数量和总字节数
- 默认不把完整文件条目塞进 MCP 响应，避免输出臃肿

它能把候选版本推进到“可哈希绑定”的审查状态，但还不是已经持久化的 release artifact。正式稳定替换前，仍要把该摘要写入晋升材料，并完成 rehearsal / rollback 证明。

## local_blockers

`local_blockers` 是必须先清掉的本地阻断，例如：

- 当前运行服务无法证明加载了当前 checkout 代码
- worktree 不是 clean
- 缺少网页端 GPT 必需入口工具
- 缺少 `thin_governed_loop_preview`
- 无法确认项目 HEAD

有 `local_blockers` 时，不应进入稳定晋升审查。

## warnings

`warnings` 不一定阻断本地审查，但会降低生产确定性，例如：

- 本地 commits 尚未 push 到 `origin/main`
- 无法确认 `origin/main` 对比
- 稳定运行目录不是可证明 Git HEAD 的 checkout

这些 warning 需要在正式替换稳定服务前由 artifact manifest、release notes 或 rollback rehearsal 补足。

## 推荐路径

1. `get_web_gpt_service_entrypoint`
2. `list_registered_projects`
3. `get_stable_promotion_readiness`
4. `analyze_project_state`
5. `manage_workflow_run action=list`
6. 只在 readiness 干净后准备 artifact manifest 和 rehearsal
7. 只有 Commander 给出精确授权后，才考虑稳定服务替换

## 禁止误解

本工具不授权：

- 替换 `/home/jenn/tools/colameta`
- 停止或重启稳定服务
- push
- executor run
- route transition
- release / deploy
- 创建 ReviewDecision
- emit GateEvent
- 写 Delivery State accepted
