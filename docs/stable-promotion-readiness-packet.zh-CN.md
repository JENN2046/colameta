# Stable Promotion Readiness Packet

状态：`readiness_draft`

本文记录当前 dev repo 是否适合晋升到稳定服务 `/home/jenn/tools/colameta`。它是只读晋升材料，不是部署授权。

## 当前候选

- 候选 repo：`/home/jenn/src/colameta-dev`
- 候选 HEAD：`1b2655a2e074a54616c971cff271caff54593603`
- 候选 short HEAD：`1b2655a`
- runtime 候选提交生成时本地领先：`origin/main +94`
- 当前 worktree：clean
- 当前 dev MCP：`http://127.0.0.1:8776/mcp`
- 当前 dev Web：`http://127.0.0.1:8811`

## 稳定服务现状

- 稳定服务目录：`/home/jenn/tools/colameta`
- 稳定 MCP：`http://127.0.0.1:8766/mcp`
- 稳定 Web：`http://127.0.0.1:8801`
- 稳定服务当前仍来自 `/home/jenn/tools/colameta`
- 稳定服务不是 dev repo 当前代码
- `/home/jenn/tools/colameta` 当前未确认 git 版本来源

## 当前结论

当前候选适合进入 `stable_promotion_review_candidate`，不适合直接晋升为正式稳定服务。

原因：

- dev 全量测试通过，但本地领先 94 个 commits，尚未形成可追溯 release artifact。
- 稳定服务运行目录不是 git repo，缺少明确的 artifact / commit 绑定。
- 稳定服务替换与 rollback 尚未演练。
- 网页端 GPT 需要使用服务，因此晋升前必须保证入口工具、项目路由、只读边界和证据回看稳定。

## 已满足条件

- dev repo worktree clean
- dev MCP endpoint ready
- 稳定服务未被改动
- 全量测试通过：`526 tests OK`
- 新增网页端 GPT 入口工具：`get_web_gpt_service_entrypoint`
- 入口工具在 `tools/list` 中可发现
- 入口工具 scope：`mcp:read`
- 薄治理闭环 `draft -> provided` 实测通过
- workflow run 列表按 `created_at` 新到旧排序，方便回看最近证据

## P0 晋升前必须完成

- 生成可追溯 artifact，并绑定 dev HEAD：`1b2655a2e074a54616c971cff271caff54593603`
- 记录 artifact sha256
- 明确稳定服务替换步骤
- 明确 rollback 步骤
- 在不修改稳定服务的前提下完成一次 dry-run 或 rehearsal
- Commander 明确授权 stable service replacement

## P1 建议完成

- 汇总 `origin/main..HEAD` 的 release notes
- 把治理文档、taskbook、runtime 能力和 UX 修复分组
- 记录网页端 GPT 使用路径验收结果
- 记录稳定服务启动命令、端口和 auth mode
- 确认稳定服务仍只绑定 loopback：`127.0.0.1`

## 禁止误解

本 packet 不授权：

- 替换 `/home/jenn/tools/colameta`
- push
- executor run
- route transition
- release / deploy
- 创建 ReviewDecision
- emit GateEvent
- 写 Delivery State accepted

## Commander 后续授权提示草案

```text
AUTHORIZE_STABLE_PROMOTION_REHEARSAL_FOR_EXACT_HEAD_ONLY

Target:
- Project: ColaMeta
- Dev repo: /home/jenn/src/colameta-dev
- Candidate HEAD: 1b2655a2e074a54616c971cff271caff54593603
- Stable runtime directory: /home/jenn/tools/colameta

Allowed:
- prepare stable promotion rehearsal plan
- compute candidate artifact manifest
- verify dev MCP tool discovery and web GPT entrypoint
- verify rollback plan text

Not allowed:
- replace stable service
- stop stable service
- modify /home/jenn/tools/colameta
- push
- executor run
- route transition
- release / deploy
```
