# Stage 0-6 冻结候选审查包草稿

```yaml id="stage-0-6-freeze-packet-zh-cn-summary"
chinese_companion:
  source_document: docs/taskbooks/stages/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_0_6.md
  source_sha256: 94ea9101a120e0935e834533ed0315a6fe3e77e3d4ecb48db37fa6851e75b5ce
  translation_status: companion_draft
  authority_status: planning_reference_only
stage_0_6_freeze_packet:
  status: hash_specific_freeze_candidate_confirmation_recorded
  generated_from_head: fd2f60a
  packet_storage_head: 0fc3fcc
  current_observed_head: 0fc3fcc
```

## 1. 这份文件是什么

这是一份中文 companion，也就是英文 Stage 0-6 freeze packet 确认记录的完整中文解释版。

`Freeze Candidate Review Packet` 中文可以理解为“冻结候选审查包”。它的作用是：
把一组准备进入冻结审查的文件、hash、范围、检查结论、不可证明事项、失效规则收在
一起，并记录 Commander 对这个精确 hash 集合的冻结候选审查状态确认。

它记录的是 `freeze_candidate` 审查状态确认，不是 accepted，不是执行授权，
不是 commit 授权，不是 push 授权，也不是 executor run 授权。

## 2. 当前绑定的现实

这份 Stage 0-6 packet 草稿基于本地提交：

```text
fd2f60a docs: align stage taskbooks for freeze readiness
```

这份 packet 草稿自身存放于本地提交：

```text
0fc3fcc docs: add stage freeze packet draft
```

当前观察到：

- 分支是 `main`；
- `origin/main` 是 `6bf9a85`；
- Stage manifest 生成时，本地比远端 ahead 1；
- packet 存放后，当前本地比远端 ahead 2；
- 这个 packet 记录了 Stage 0-6 的 hash-specific freeze_candidate 审查状态确认；
- 这个 packet 没有授权 push；
- 这个 packet 没有授权 executor；
- 这个 packet 没有把 Stage 0-6 变成 accepted。

## 3. 三个 hash 集合是什么意思

`source_authority_candidate` = 英文源文件权威候选集合。

中文意思是：真正准备作为 Stage 0-6 冻结审查来源的英文任务书集合。它包含
Stage 目录索引和 Stage 0 到 Stage 6 的英文任务书。

hash 是：

```text
9e7d52f98dbbb94f3143b8a1d104b6285cc305acee1204c3ca5a4dc915ae46b0
```

`chinese_companion_candidate` = 中文 companion 候选集合。

中文意思是：为了让 Commander 能完整中文阅读而准备的中文解释文件集合。它不替代
英文源文件权威。

hash 是：

```text
c669b2f73b34cb0efe7206ed6824f6a757dd908c741dce9566c669d4c9d62aed
```

`combined_candidate` = 英文源文件加中文 companion 的合并候选集合。

中文意思是：把英文源文件和中文 companion 放在一起时的整体清单 hash。

hash 是：

```text
1bc115edf7e74ede02543308fe4a42cebcbf120670315f4abfdc320793297f14
```

这些 hash 都是草稿审查用的 manifest hash。`manifest hash` 中文意思是：
先列出每个文件路径和每个文件自己的 sha256，再对这份清单做 sha256。

## 4. 当前审查结论

当前只读审查结论是：没有已知 P0。

这里的 `P0` 中文意思是：不修就不能进入冻结候选审查的阻塞问题。

已经检查过的重点包括：

- 每个 Stage 都有 `minimum_readiness_claim`，也就是“最小就绪声明”；
- 每个 Stage 都有 `required_evidence`，也就是“所需证据”；
- 每个 Stage 都有 `gate_question`，也就是“状态门问题”；
- 每个 Stage 都有 `explicit_non_goal`，也就是“明确不做什么”；
- 每个 Stage 都绑定了 `master_taskbook_ref`；
- 每个 Stage 都声明 `supports_project_goal=true`；
- Stage 3 已使用 `acceptance_commands` 和 `manual_acceptance`；
- Stage 5 没有再使用“推荐 ACCEPT”的表达；
- `created_from_head` 已解释为历史创建基线，不是当前冻结快照；
- 中文 companion 的 source hash 和英文源文件匹配；
- YAML 块可以解析；
- commit 前 `git diff --check` 通过。

## 5. 失效规则

这份 packet 草稿会在以下情况失效：

- Stage 英文源文件变化；
- Stage 中文 companion 文件变化；
- 生成基线 HEAD 变化；
- Master 绑定变化；
- hash policy 变化；
- canonicalization policy 变化；
- 审查发现新的 P0；
- Stage 范围变化；
- packet 自己的措辞变化并影响审查结论。

一旦失效，就要重新计算文件 hash、manifest hash，并重新做只读审查。

## 6. 允许的审查结果

这份 packet 确认记录后续最多允许导向这些结果：

- `FREEZE_CANDIDATE_CONFIRMATION_RECORDED_FOR_EXACT_HASH`
  = 这个精确 hash 的冻结候选确认已经记录；
- `RETURN_TO_DRAFT_FIXES`
  = 返回草稿修复；
- `INVALIDATED_BY_CONTENT_OR_HEAD_CHANGE`
  = 因内容或 HEAD 改变而失效；
- `BLOCKED_NEEDS_EXPLICIT_SCOPE_DECISION`
  = 范围问题需要 Commander 明确决定。

它禁止导向这些结果：

- Stage Taskbooks 已 accepted；
- delivery state 已 accepted；
- execution 已授权；
- push 已授权。

## 7. 不能证明什么

这份 packet 草稿不能证明：

- 未来 repo 状态还和当前一样；
- 远端 origin 会一直停在当前观察到的 commit；
- Commander 一定会确认冻结候选；
- 后续 Version 任务实现一定质量好；
- 未来 executor run 一定正确；
- 中文翻译没有任何可争议表达；
- 没有额外授权也能生成 canonical hash receipt。

## 8. 已使用的 Commander 确认口令

Commander 已经使用英文源文件里的
`CONFIRM_STAGE_0_6_FREEZE_CANDIDATE_FOR_HASH_ONLY` 口令确认这个精确 hash 集合。

这份中文 companion 只是解释确认记录，不增加额外授权。
