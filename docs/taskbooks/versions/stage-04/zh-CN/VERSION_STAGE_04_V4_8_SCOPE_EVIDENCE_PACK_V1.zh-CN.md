# Version 中文任务书：Stage 4 / v4.8 范围证据包 V1

```yaml id="version-stage-04-v4-8-zh-cn-summary"
chinese_companion:
  source_document: docs/taskbooks/versions/stage-04/VERSION_STAGE_04_V4_8_SCOPE_EVIDENCE_PACK_V1.md
  source_sha256: aef8eb8b4ba30ba640923f19045080166ecc31cf20a6f7213078d627241050e2
  translation_status: companion_draft
  authority_status: planning_reference_only
version_execution_taskbook:
  version_id: stage_04_v4_8_scope_evidence_pack_v1
  version: v4.8
  chinese_name: 范围证据包 V1
  status: discussion_draft
  execution_authorization_status: not_authorized
```

## 1. 这份任务书是什么

`Scope Evidence Pack V1` = 范围证据包 V1。

中文意思是：把 allowed_files、forbidden_files、实际 touched files、scope violation
和 known gaps 打包成范围证据，方便审查是否越界。

## 2. 父级绑定

- Master Taskbook hash：`1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34`
- Stage 4 Taskbook hash：`05e6114a666942c0641c635905c2295feaa62b98bd9e7b5166babd662e015a41`
- previous version v4.7 hash：`755b33635c24eb450162de4bad1e0c8e17c38cf8a4eb83887cda985cf6dea8e5`
- Stage 3 Version set confirmation hash：`8695cf9f9b29608011dfc4691fd12df5a4f21f879e025e999c8bba5ae929e313`

## 3. 范围证据最小合约

至少记录：

- allowed_files；
- forbidden_files；
- observed_touched_files；
- observed_mutations；
- generated_files；
- ignored_runtime_files；
- scope_violations；
- known_gaps；
- remaining_risks；
- authority_boundary。

允许的 scope result 只有：`in_scope`、`out_of_scope`、`unknown_needs_review`。

不能接受 out_of_scope 或 unknown 被包装成 in_scope，也不能把 scope pass 当成 review
acceptance。
