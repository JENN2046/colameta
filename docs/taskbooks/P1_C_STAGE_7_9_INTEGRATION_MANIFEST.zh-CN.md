# P1-C0 Stage 7--9 集成 Manifest

```yaml id="p1-c-stage-7-9-integration-manifest-zh-cn-metadata"
p1_c_stage_7_9_integration_manifest_zh_cn:
  document_type: chinese_companion
  source_document_ref: docs/taskbooks/P1_C_STAGE_7_9_INTEGRATION_MANIFEST.md
  source_sha256: bb16181ae45abedbf06ee4e68799a13e4adeb9c9142cf1b6063bd9d575e33519
  source_schema_version: colameta.p1_c_stage_7_9_integration_manifest.v1
  translation_status: companion_draft
  authority_status: implementation_scope_only
  source_authority_boundary: english_source_remains_authoritative
  created_at: 2026-07-24
  known_translation_gaps: []
```

## 目标与边界

本 manifest 为 P1-C 绑定一条只读 journey：

```text
Stage 7 有界 drift evidence
  -> Stage 8 PLAN_ADJUST preview
  -> Stage 9 controlled-continue readiness report
```

它不会把任何 taskbook 变成 implementation authority。下面的 taskbook 是本切片不可变的 planning input。
这个切片只能组织 evidence、指出下一项人工决策；不能声明 semantic alignment、apply plan/taskbook mutation、
启动 executor、创建 ReviewDecision 或 GateEvent、改变 delivery state、commit、push、stable replacement，
也不能改变 Connector/OAuth configuration。

## 冻结输入

实现必须在组合 preview 前核对以下精确引用。任何不一致都必须 fail closed，不能静默刷新或归一化。

| 角色 | 路径 | SHA-256 |
| --- | --- | --- |
| Master governance input | `PROJECT_MASTER_TASKBOOK.md` | `1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34` |
| Stage 7 input | `docs/taskbooks/stages/STAGE_07_DRIFT_EVIDENCE_AND_CORRECTION.md` | `24cec5e48435254731cce4bb2e72c8810df3d041f57c142d5674d82a632cb142` |
| Stage 8 input | `docs/taskbooks/stages/STAGE_08_PLAN_ADJUSTMENT_CONTROL.md` | `60421ba765b238b9671f1f9baf878cf716c6e6e5cd05524bfa746610fd9a3755` |
| Stage 9 input | `docs/taskbooks/stages/STAGE_09_CONTROLLED_CONTINUE_AND_LONG_RUN_TRACE.md` | `5bfe6e4632748bd33f5a763963bc54b5e546bd3349ad536ec5b693522c7d696d` |

compatibility surface 必须组合而不是复制以下既有 domain contract 的冻结基线内容：

| Contract | 路径 | SHA-256 |
| --- | --- | --- |
| Stage 7 schema | `runner/drift_evidence_schema.py` | `d956904c234d816fa55255464f2e4260db27fc56ffa066965bd2b03f442c716f` |
| Stage 7 builder | `runner/drift_evidence_pack_builder.py` | `f59870e70d4c728b1738ba32c60b0482e202b28778152046f85797ff050b1d48` |
| Stage 8 preview | `runner/plan_adjustment_preview.py` | `c56b3a24d301f07e173aa576e60b2cd5ddf74b8eb99b56c7310c030e9cbc5715` |
| Stage 9 report | `runner/controlled_continue_readiness.py` | `fd5bfc9f929be335d8607f4fa89f2bccd07dd00eb73b5dabf11884778c6e6f29` |

## 实现 allowlist

P1-C 只能修改以下 tracked 文件。必须新建一个聚焦 module；`mcp_server.py` 和 core orchestrator 都不能成为
Stage 7--9 domain logic 的第二个 owner。

```text
runner/mcp_stage_7_9_preview.py
runner/mcp_workflow_compatibility.py
runner/mcp_tool_catalog.py
runner/mcp_workflow_policy.py
runner/mcp_workflow_migration.py
tests/test_mcp_stage_7_9_preview.py
tests/test_mcp_workflow_policy.py
tests/test_mcp_workflow_migration.py
tests/test_mcp_runtime_observability.py
tests/test_mcp_operation_context_binding.py
docs/USAGE.md
docs/USAGE.zh-CN.md
docs/taskbooks/P1_CONVERGENCE_EXECUTION_BASELINE.md
docs/taskbooks/P1_CONVERGENCE_EXECUTION_BASELINE.zh-CN.md
docs/taskbooks/P1_C_STAGE_7_9_INTEGRATION_MANIFEST.md
docs/taskbooks/P1_C_STAGE_7_9_INTEGRATION_MANIFEST.zh-CN.md
```

以下内容明确不在范围内：`PROJECT_MASTER_TASKBOOK*`、上面三份 Stage taskbook、tracked `.colameta/`
planning state、任何 ignored runtime/log/session material、stable-replacement receipt、Git configuration、
release automation、Connector/tunnel/OAuth configuration，以及所有 apply/run/commit/push/deploy path。

## 公开请求契约

`inspect` 返回精确模板和一份新鲜的 `stage_7_9_context`：

```yaml
stage_7_9_context:
  project_name: <resolved managed project name or local project identity>
  branch: <observed branch>
  head: <observed HEAD>
  runner_plan: { mode: <managed|source-only>, plan_sha256: <hash|null> }
  current_version: <string|null>
  review_unit: stage_07_to_stage_09_preview
  workflow_intent: stage_7_9_preview
```

`preview` 必须原样收到这个对象，以及下面三个 input object：

```yaml
stage_7_9_inputs:
  stage_7_drift_evidence_inputs: <object for build_drift_evidence_pack>
  stage_8_plan_adjustment_inputs: <object for build_plan_adjustment_preview>
  stage_9_continue_readiness_inputs: <object for build_controlled_continue_readiness_report>
```

在生成 compact public projection 前，wrapper 必须核对以下 cross-stage invariant：

1. 请求 context 仍与当前 project identity 匹配，四个冻结 taskbook ref 的 path 与 SHA-256 全部匹配。
2. Stage 7 只在获得 schema-valid、未回答的 drift evidence pack 时成功；其中 master 和 Stage 7 ref 必须是上面的冻结 ref。
3. Stage 8 必须由显式 `PLAN_ADJUST` Commander decision request 驱动，引用生成的 Stage 7 pack ID，使用冻结的 master 与 Stage 8 ref，并保持 `apply_allowed=false`。
4. Stage 9 必须收到生成的 Stage 8 preview ref、冻结的 master 与 Stage 9 ref，以及明确的 plan/state/readiness input。在这个 PLAN_ADJUST journey 中，`PLAN_ADJUST_BLOCKS_CONTINUE` 是正确安全的结果，不能被绕过；它要指出 Stage 8 的人工决策。

public result 只能是 whitelist projection：compact ID、hash-match boolean、status、blocker code、question/checklist
count 和下一项人工决策。不能回显任意 input object、raw runtime state、provider/session data、local absolute
path、完整 diff 或 credential。

## 必测负向矩阵

| 情况 | 必须返回的 blocker/error |
| --- | --- |
| 缺少 journey context | `STAGE_7_9_CONTEXT_REQUIRED` |
| branch/HEAD/plan/version context 改变 | `STAGE_7_9_CONTEXT_MISMATCH` |
| 冻结 taskbook path/hash 缺失或错误 | `STAGE_7_9_TASKBOOK_BINDING_MISMATCH` |
| 缺少任一 stage input object | `STAGE_7_9_INPUTS_REQUIRED` |
| Stage 7 evidence 无效 | `STAGE_7_9_STAGE_7_FAILED_CLOSED` |
| Stage 8 source 不是显式 PLAN_ADJUST | `STAGE_7_9_STAGE_8_FAILED_CLOSED` |
| Stage 8 drift-pack ID 与 Stage 7 不同 | `STAGE_7_9_DRIFT_PACK_BINDING_MISMATCH` |
| Stage 9 缺少必要 readiness material | `STAGE_7_9_STAGE_9_FAILED_CLOSED` |
| 任意 apply/run/commit/execute phase | `STAGE_7_9_PHASE_NOT_SUPPORTED` |

valid fixture 必须证明所有 side-effect field 都是 false，并证明 Stage 8 PLAN_ADJUST 尚未解决时，Stage 9 会
阻断 continuation。

## 验收命令

```text
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_mcp_stage_7_9_preview.py tests/test_drift_evidence_schema.py tests/test_drift_evidence_pack_builder.py tests/test_plan_adjustment_preview.py tests/test_controlled_continue_readiness.py tests/test_mcp_workflow_policy.py tests/test_mcp_workflow_migration.py tests/test_mcp_runtime_observability.py tests/test_mcp_operation_context_binding.py -q
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q
.venv/bin/python scripts/self_hosting_smoke.py
.venv/bin/python -m compileall runner tests
.venv/bin/ruff check runner tests
git diff --check
```

## 完成边界

只有当这一条 public、read-only route 通过上面的 valid/negative fixture matrix，不增加第十个公开工具，
不扩大 scope，并且输出 compact next-human-decision projection 时，P1-C 才完成。它不授权 Stage 7--9
execution、plan mutation 或 stable deployment。
