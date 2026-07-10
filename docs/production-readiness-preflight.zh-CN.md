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
- `get_agent_consumer_contract` 是否可见
- `get_service_entry_profile` 是否可见
- `thin_governed_loop_preview` 是否可用
- 稳定运行目录 `/home/jenn/tools/colameta` 是否存在、是否有可证明 Git HEAD
- 从精确候选 Git commit object database 计算的 tracked-file artifact manifest 摘要与 `manifest_sha256`
- 当前候选 manifest receipt 是否已持久化并重新验证
- `local_blockers`
- `warnings`
- 稳定替换前仍需要的外部材料

## 结果怎么读

`readiness_status=stable_promotion_review_candidate` 的意思是：

当前运行候选可以进入稳定晋升审查，但还不是正式稳定生产服务。

它仍然需要：

- 把 `candidate_artifact_manifest` 摘要与 sha256 写入晋升材料
- 与精确候选 HEAD 绑定的 rollback / rehearsal 证明；现场证明满足时会显示为
  `rollback_rehearsal_binding.status=verified_current`
- Commander 对稳定服务替换的精确授权

`stable_production_ready` 当前必须保持 `false`，因为只读工具不能替代部署授权、发布物证明或 rollback receipt。

`rollback_rehearsal_evidence` 与 production ops 使用同一个只读检查来源。稳定晋级包还会通过
`rollback_rehearsal_binding` 复核 backup SHA-256、归档可读性、精确候选 HEAD 和
`rehearsal_executed_restore=false`。只有绑定为 `verified_current` 才能移除
`ROLLBACK_REHEARSAL_NOT_PROVEN`；该状态不表示执行过 restore。

## candidate_artifact_manifest

`candidate_artifact_manifest` 是服务现场计算的只读候选摘要：

- 只覆盖精确 `project_head` commit 中的 Git tracked files
- 从 Git object database 读取 blob 和 gitlink，不读取当前 worktree 文件内容
- worktree 的 tracked 修改、untracked 文件、ignored runtime state、`.git`、`.venv` 和 build artifacts 都不会污染该 commit manifest
- 返回 `manifest_sha256`、tracked path list hash、文件数量和总字节数
- 默认不把完整文件条目塞进 MCP 响应，避免输出臃肿

它能把候选版本推进到“可哈希绑定”的审查状态，但还不是已经持久化的 release artifact。
使用下面的 preview/apply 流程生成 runtime receipt：

```json
{
  "name": "manage_stable_promotion_evidence",
  "arguments": {
    "action": "preview",
    "project_name": "colameta-self-dev",
    "candidate_head": "<exact-head>"
  }
}
```

preview 只写短期 `.colameta/runtime` 预览，并要求 candidate 等于当前 `HEAD` 和
`origin/main`。`apply` 必须使用该 preview 的一次性 `preview_id`，重新计算
精确 commit manifest 并比对后，才写入完整 receipt。`status` 会再次从 Git object database
计算 manifest，验证 receipt digest、完整 file entries 和当前候选绑定。已有无效 receipt 不会被
静默覆盖。这个流程只准备晋升证据，不替换或重启 stable service，不修改 Git，不 push，也不
release/deploy。worktree 改动不会进入 manifest，也不会阻断这份 exact-commit receipt；响应中的
`worktree_isolation` 会明确记录 clean 状态、dirty 数量和隔离边界。但 worktree clean 仍是进入
`stable_promotion_review_candidate` 的独立门禁。正式稳定替换前仍要清掉该 blocker、完成
rehearsal / rollback 证明并取得精确 Commander 授权。

## local_blockers

`local_blockers` 是必须先清掉的本地阻断，例如：

- 当前运行服务无法证明加载了当前 checkout 代码
- worktree 不是 clean
- 缺少网页端 GPT 必需入口工具
- 缺少 Agent 消费者契约工具
- 缺少服务入口画像选择器
- 缺少 `thin_governed_loop_preview`
- 无法确认项目 HEAD

有 `local_blockers` 时，不应进入稳定晋升审查。

如果唯一 blocker 是 worktree 不 clean，仍可先按 `recommended_next_steps` 预览并记录精确
`origin/main` HEAD 的 artifact receipt。该动作只推进证据闭环，不会把候选标记为可晋升。

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
4. `manage_stable_promotion_evidence action=preview`
5. 显式确认后 `manage_stable_promotion_evidence action=apply`
6. `manage_stable_promotion_evidence action=status` 验证持久化 receipt
7. `analyze_project_state`
8. `manage_workflow_run action=list`
9. 只在 readiness 干净后准备 rehearsal
10. 只有 Commander 给出精确授权后，才考虑稳定服务替换

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
