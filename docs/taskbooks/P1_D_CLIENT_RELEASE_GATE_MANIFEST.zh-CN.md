# P1-D 客户端体验与 Release Gate 清单

```yaml
p1_d_client_release_gate_zh_cn:
  document_type: chinese_companion
  source_document_ref: docs/taskbooks/P1_D_CLIENT_RELEASE_GATE_MANIFEST.md
  source_authority_boundary: english_source_remains_authoritative
  created_at: 2026-07-24
  translation_status: companion_draft
```

## 目的

P1-D 有意把两类客户端体验分开：

```text
ChatGPT Commander
  = 固定九工具、紧凑 public projection、typed 分页续读

Local Codex / loopback normal
  = 高级诊断、executor 控制、本地 migration 与 handoff context

共同部分
  = canonical state、scope、context binding、authority boundary
```

它还提供一份 fail-closed 的 P1 release-decision packet。本地演练只能证明 server-side
contract，不能声称 live ChatGPT host、connector、OAuth、tunnel 或 stable runtime 已被验收。

## 硬边界

- 不能增加第十个公开 Commander 工具。
- 不执行 Connector、Auth0/OAuth、tunnel、DNS、App、stable runtime、Git push、tag、publish 或 release。
- 调用方的自我声明不能把 P1 release decision 变成 ready。
- `resources/read` 保持可选标准兼容；ChatGPT 的主分页读取路线是 `review_manifest` 和
  `read_result_artifact`。
- 本地演练只能使用临时 fixture，结束后 checkout 必须保持干净。

## 本地演练

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/chatgpt_development_acceptance.py --json
```

它会验证精确九工具 inventory、故意的 `CONTEXT_BINDING_MISMATCH` 且不写 archive、
`review_manifest` 的全页 hash/expiry continuity、`read_result_artifact` 的全页 SHA/expiry
continuity，以及全过程不调用 `resources/read`。

## Release 决策

`p1_client_release_gate.status` 在以下独立验证证据全齐前必须始终是 `blocked`：完整候选 commit
本地验证、public endpoint runtime provenance、新鲜 connector/OAuth 与九工具 discovery、新鲜
current facts、真实 ChatGPT development-connector session 验收，以及另行授权的精确
stable-replacement target。

P1-E 为这些声明增加 closed、preview 绑定的本地 operator receipt。它会校验 candidate binding、
精确九工具 inventory、continuity flags、时间戳与 receipt digest，同时把外部 ChatGPT 和 Connector
观察明确标为 operator-attested，而不是服务器自行观察。receipt 不完整或不新鲜时 gate 仍会 fail-closed；
即使五组 evidence 都齐全，stable replacement 仍必须另行明确授权。详细 receipt contract 见
`P1_E_RELEASE_EVIDENCE_GATE.zh-CN.md`。
