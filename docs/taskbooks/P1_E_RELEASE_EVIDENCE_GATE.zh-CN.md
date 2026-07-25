# P1-E Release Evidence Gate 中文 Companion

```yaml
p1_e_release_evidence_gate_zh_cn:
  document_type: chinese_companion
  source_document_ref: docs/taskbooks/P1_E_RELEASE_EVIDENCE_GATE.md
  source_sha256: e72b2023973352d3405666bafc822d837cc2a644ae68b83360725af3b75f8ec5
  source_schema_version: colameta.p1_e_release_evidence_gate_manifest.v1
  source_status: implementation_verified_pending_fresh_development_acceptance
  translation_status: companion_draft
  authority_status: planning_reference_only
  source_authority_boundary: english_source_remains_authoritative
  created_at: 2026-07-24
  reconciled_at: 2026-07-25
  known_translation_gaps: []
```

## 目的

P1-D 已让九工具 ChatGPT 契约可观察、可重复。P1-E 补上证据处理缺口，但不会假装本地 MCP
服务器能够自行看见 ChatGPT 宿主会话。

```text
脱敏的观察事实
  -> preview 绑定的本地 operator receipt
  -> receipt 完整性 + candidate / freshness 复核
  -> P1 client release gate 逐项显示 passed、stale 或 blocked
  -> stable 仍需单独授权
```

外部观察在 receipt 中明确标记为 `operator_attested`，绝不伪装成服务器自行观察到的事实。

## 仅本地的 Intake Surface

`manage_p1_release_evidence` 只存在于 normal / loopback advanced MCP profile，刻意不进入
ChatGPT Commander 的九工具元组。

| Action | Scope | 作用 |
| --- | --- | --- |
| `inspect`、`status` | `mcp:read` | 复核最新的 exact-candidate receipt。 |
| `preview` | `mcp:preview` | 校验 closed evidence contract，并创建短时 runtime preview。 |
| `apply` | `mcp:commit` | 要求 `preview_id` 和 `confirm_release_evidence=true`；只写一份 ignored runtime receipt。 |
| `discard` | `mcp:preview` | 删除短时 preview。 |

intake 只接受结构化 evidence 字段。它拒绝 raw transcript、URL、tunnel log、OAuth token、cookie、
credential 和任意 metadata。

## 精确 Receipt 合同

每一项观察都绑定精确 candidate commit 与 `observed_at`。评估器会拒绝超过 24 小时的观察、未来时间、
candidate 不匹配、非标准九工具 inventory、缺少 continuity evidence 或 digest 被改动的 receipt。

必须有五组证据：

1. 完整本地验证：pytest、self-hosting smoke、compileall、Ruff、`git diff --check` 都被确认 passed；
2. runtime provenance：loaded runtime 与 checkout HEAD 都等于 candidate，且不存在 stale-code 或
   reload-needed；
3. connector/OAuth：可达、已授权，并暴露精确顺序的九工具元组；
4. current facts：有可分页 artifact descriptor，current observation 为真，且无未解决 critical blocker；
5. 真实 ChatGPT development 验收：精确 inventory、故意的 `CONTEXT_BINDING_MISMATCH`、manifest
   page/hash/expiry continuity、typed result-artifact page/SHA/expiry continuity、不使用
   `resources/read`，且所有调用只读。

## 明确不授予的权力

即使 P1 gate 能到达：

```text
candidate_release_status = evidence_ready_pending_stable_authorization
```

它的决策仍是：

```text
status = blocked
ready = false
blocker = EXPLICIT_STABLE_REPLACEMENT_AUTHORIZATION_REQUIRED
```

这个 receipt 不会授权 stable replacement、服务重启、Connector/OAuth 改动、executor run、validation
run、commit、push、release 或 deploy。

## 新鲜真实验收交接

当 candidate 仅部署到 development MCP 后，用新的 ChatGPT 会话对该 exact HEAD 做验收。只记录上面
closed contract 的字段，再使用本地 loopback 的 `preview -> apply` 持久化 receipt。最后读取
`get_release_submission_readiness` 或 P1 gate，确认剩下哪些 blocker。

五项 evidence 都通过后，下一步仍不是替换，而是向 Jenn 请求单独、精确的 stable-replacement 授权。

## 必须的回归覆盖

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q \
  tests/test_p1_release_evidence.py \
  tests/test_chatgpt_development_acceptance.py \
  tests/test_mcp_commander_exposure_profile.py \
  tests/test_release_submission_readiness.py
```

## 术语说明

| 术语 | 中文含义 |
| --- | --- |
| operator-attested | 由 operator 按闭合字段声明的外部观察，不是服务器自行观察。 |
| preview-bound receipt | 必须与短时 preview 和精确候选绑定后才能写入的本地回执。 |
| exact candidate | 所有证据共同绑定的精确 Git commit。 |
| freshness re-evaluation | 每次读取时重新判断观察时间、候选绑定和连续性是否仍有效。 |
