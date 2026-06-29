# 中文 Companion 文档清单

```yaml id="chinese-companion-index-summary"
chinese_companion_index:
  document_type: companion_index
  status: discussion_draft
  authority_status: planning_reference_only
  policy_ref: docs/taskbooks/CHINESE_COMPANION_POLICY.md
```

这份清单记录所有计划类文档的中文 companion 状态。

---

## 1. 顶层治理文档

| Source | 中文 Companion | 当前状态 | 备注 |
| --- | --- | --- | --- |
| `PROJECT_MASTER_TASKBOOK.md` | `PROJECT_MASTER_TASKBOOK.zh-CN.md` | `companion_draft` | Master 中文 companion 已生成，保留英文 hash 权威边界。 |
| `FREEZE_CANDIDATE_REVIEW_PACKET.md` | `FREEZE_CANDIDATE_REVIEW_PACKET.zh-CN.md` | `companion_draft` | Review packet 中文 companion 已生成，保留 packet 非授权边界。 |

---

## 2. Stage Taskbook 文档

| Source | 中文 Companion | 当前状态 | 备注 |
| --- | --- | --- | --- |
| `docs/taskbooks/stages/README.md` | `docs/taskbooks/stages/zh-CN/README.zh-CN.md` | `companion_draft` | Stage taskbook 索引中文 companion 已生成。 |
| `docs/taskbooks/stages/STAGE_00_BASELINE_CLOSEOUT.md` | `docs/taskbooks/stages/zh-CN/STAGE_00_BASELINE_CLOSEOUT.zh-CN.md` | `companion_draft` | Stage 0 中文 companion 已生成。 |
| `docs/taskbooks/stages/STAGE_01_MASTER_TASKBOOK_ANCHORING.md` | `docs/taskbooks/stages/zh-CN/STAGE_01_MASTER_TASKBOOK_ANCHORING.zh-CN.md` | `companion_draft` | Stage 1 中文 companion 已生成。 |
| `docs/taskbooks/stages/STAGE_02_STAGE_TASKBOOK_MANAGEMENT.md` | `docs/taskbooks/stages/zh-CN/STAGE_02_STAGE_TASKBOOK_MANAGEMENT.zh-CN.md` | `companion_draft` | Stage 2 中文 companion 已生成。 |
| `docs/taskbooks/stages/STAGE_03_EXTERNAL_TASKBOOK_IMPORT.md` | `docs/taskbooks/stages/zh-CN/STAGE_03_EXTERNAL_TASKBOOK_IMPORT.zh-CN.md` | `companion_draft` | Stage 3 中文 companion 已生成。 |
| `docs/taskbooks/stages/STAGE_04_BOUNDED_EXECUTION_AND_EVIDENCE.md` | `docs/taskbooks/stages/zh-CN/STAGE_04_BOUNDED_EXECUTION_AND_EVIDENCE.zh-CN.md` | `companion_draft` | Stage 4 中文 companion 已生成。 |
| `docs/taskbooks/stages/STAGE_05_REVIEWER_HANDOFF_PACKAGE.md` | `docs/taskbooks/stages/zh-CN/STAGE_05_REVIEWER_HANDOFF_PACKAGE.zh-CN.md` | `companion_draft` | Stage 5 中文 companion 已生成。 |
| `docs/taskbooks/stages/STAGE_06_REVIEW_FEEDBACK_INTAKE.md` | `docs/taskbooks/stages/zh-CN/STAGE_06_REVIEW_FEEDBACK_INTAKE.zh-CN.md` | `companion_draft` | Stage 6 中文 companion 已生成。 |

```yaml id="stage-companion-freeze-readiness-note"
stage_companion_freeze_readiness_note:
  status: companion_draft_retained
  freeze_readiness_effect: non_blocking_if_hash_matched_and_no_translation_conflict
  required_before_companion_reference_acceptance:
    - separate_companion_review
    - source_hash_match_check
    - translation_conflict_check
  non_authorization:
    - companion_draft_does_not_replace_english_source_authority
    - companion_draft_does_not_authorize_freeze
    - companion_draft_does_not_authorize_execution
```

中文解释：Stage 中文 companion 先保持 `companion_draft`。只要 source hash 匹配、
没有翻译冲突，它本身不阻塞 Stage freeze readiness 审查；但它也不会自动成为
同级权威副本。

---

## 3. Version / Prompt Taskbook 文档

| Source | 中文 Companion | 当前状态 | 备注 |
| --- | --- | --- | --- |
| `docs/taskbooks/versions/stage-00/VERSION_STAGE_00_V0_1_REPOSITORY_RUNTIME_REALITY_SNAPSHOT.md` | `docs/taskbooks/versions/stage-00/zh-CN/VERSION_STAGE_00_V0_1_REPOSITORY_RUNTIME_REALITY_SNAPSHOT.zh-CN.md` | `companion_draft` | Stage 0 / v0.1 中文 companion 已生成，尚未授权执行。 |
| `docs/taskbooks/versions/stage-00/VERSION_STAGE_00_V0_2_VALIDATION_TRUTH_SOURCE_REPORT.md` | `docs/taskbooks/versions/stage-00/zh-CN/VERSION_STAGE_00_V0_2_VALIDATION_TRUTH_SOURCE_REPORT.zh-CN.md` | `companion_draft` | Stage 0 / v0.2 中文 companion 已生成，尚未授权执行或跑测试。 |
| `docs/taskbooks/versions/stage-00/VERSION_STAGE_00_V0_3_RUNTIME_FRESHNESS_REPORT.md` | `docs/taskbooks/versions/stage-00/zh-CN/VERSION_STAGE_00_V0_3_RUNTIME_FRESHNESS_REPORT.zh-CN.md` | `companion_draft` | Stage 0 / v0.3 中文 companion 已生成，尚未授权执行、重启或 reload。 |
| `docs/taskbooks/versions/stage-00/VERSION_STAGE_00_V0_4_EXECUTOR_SESSION_HEAD_CLASSIFICATION_REPORT.md` | `docs/taskbooks/versions/stage-00/zh-CN/VERSION_STAGE_00_V0_4_EXECUTOR_SESSION_HEAD_CLASSIFICATION_REPORT.zh-CN.md` | `companion_draft` | Stage 0 / v0.4 中文 companion 已生成，尚未授权执行、session cleanup 或 executor dispatch。 |
| `docs/taskbooks/versions/stage-00/VERSION_STAGE_00_V0_5_LOCAL_REMOTE_BASELINE_REPORT.md` | `docs/taskbooks/versions/stage-00/zh-CN/VERSION_STAGE_00_V0_5_LOCAL_REMOTE_BASELINE_REPORT.zh-CN.md` | `companion_draft` | Stage 0 / v0.5 中文 companion 已生成，尚未授权 fetch、push 或 route transition。 |
| `docs/taskbooks/versions/stage-00/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_00_VERSIONS.md` | `docs/taskbooks/versions/stage-00/zh-CN/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_00_VERSIONS.zh-CN.md` | `companion_draft` | Stage 0 Version set freeze confirmation record 中文 companion 已生成，只记录精确 hash 的 freeze_candidate 审查状态，不授权执行、commit 或 push。 |
| `docs/taskbooks/versions/stage-01/VERSION_STAGE_01_V1_1_MASTER_TASKBOOK_REGISTRY_V1.md` | `docs/taskbooks/versions/stage-01/zh-CN/VERSION_STAGE_01_V1_1_MASTER_TASKBOOK_REGISTRY_V1.zh-CN.md` | `companion_draft` | Stage 1 / v1.1 中文 companion 已生成，尚未授权实现、registry mutation、executor、commit 或 push。 |
| `docs/taskbooks/versions/stage-01/VERSION_STAGE_01_V1_2_MASTER_TASKBOOK_READER_V1.md` | `docs/taskbooks/versions/stage-01/zh-CN/VERSION_STAGE_01_V1_2_MASTER_TASKBOOK_READER_V1.zh-CN.md` | `companion_draft` | Stage 1 / v1.2 中文 companion 已生成，尚未授权实现、reader helper、executor、commit 或 push。 |
| `docs/taskbooks/versions/stage-01/VERSION_STAGE_01_V1_3_MASTER_TASKBOOK_REQUIRED_FIELD_VALIDATOR_V1.md` | `docs/taskbooks/versions/stage-01/zh-CN/VERSION_STAGE_01_V1_3_MASTER_TASKBOOK_REQUIRED_FIELD_VALIDATOR_V1.zh-CN.md` | `companion_draft` | Stage 1 / v1.3 中文 companion 已生成，尚未授权实现、validator helper、executor、commit 或 push。 |
| `docs/taskbooks/versions/stage-01/VERSION_STAGE_01_V1_4_MASTER_HASH_BINDING_V1.md` | `docs/taskbooks/versions/stage-01/zh-CN/VERSION_STAGE_01_V1_4_MASTER_HASH_BINDING_V1.zh-CN.md` | `companion_draft` | Stage 1 / v1.4 中文 companion 已生成，尚未授权实现、hash-binding helper、canonical receipt、commit 或 push。 |
| `docs/taskbooks/versions/stage-01/VERSION_STAGE_01_V1_5_MASTER_MUTATION_HARD_GATE_V1.md` | `docs/taskbooks/versions/stage-01/zh-CN/VERSION_STAGE_01_V1_5_MASTER_MUTATION_HARD_GATE_V1.zh-CN.md` | `companion_draft` | Stage 1 / v1.5 中文 companion 已生成，尚未授权实现、mutation gate helper、Master mutation、commit 或 push。 |
| `docs/taskbooks/versions/stage-01/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_01_VERSIONS.md` | `docs/taskbooks/versions/stage-01/zh-CN/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_01_VERSIONS.zh-CN.md` | `companion_draft` | Stage 1 Version set freeze confirmation record 中文 companion 已生成，只记录精确 hash 的 freeze_candidate 审查状态，不授权实现、Master mutation、commit 或 push。 |
| `docs/taskbooks/versions/stage-02/VERSION_STAGE_02_V2_1_STAGE_TASKBOOK_SCHEMA_VALIDATOR_V1.md` | `docs/taskbooks/versions/stage-02/zh-CN/VERSION_STAGE_02_V2_1_STAGE_TASKBOOK_SCHEMA_VALIDATOR_V1.zh-CN.md` | `companion_draft` | Stage 2 / v2.1 中文 companion 已生成，尚未授权实现、schema/validator helper、executor、commit 或 push。 |
| `docs/taskbooks/versions/stage-02/VERSION_STAGE_02_V2_2_STAGE_TASKBOOK_REGISTRY_V1.md` | `docs/taskbooks/versions/stage-02/zh-CN/VERSION_STAGE_02_V2_2_STAGE_TASKBOOK_REGISTRY_V1.zh-CN.md` | `companion_draft` | Stage 2 / v2.2 中文 companion 已生成，尚未授权实现、registry mutation、executor、commit 或 push。 |
| `docs/taskbooks/versions/stage-02/VERSION_STAGE_02_V2_3_STAGE_TO_MASTER_BINDING_V1.md` | `docs/taskbooks/versions/stage-02/zh-CN/VERSION_STAGE_02_V2_3_STAGE_TO_MASTER_BINDING_V1.zh-CN.md` | `companion_draft` | Stage 2 / v2.3 中文 companion 已生成，尚未授权实现、Master mutation、project final goal mutation、executor、commit 或 push。 |
| `docs/taskbooks/versions/stage-02/VERSION_STAGE_02_V2_4_STAGE_TASKBOOK_GATE_READINESS_CONTRACT_V1.md` | `docs/taskbooks/versions/stage-02/zh-CN/VERSION_STAGE_02_V2_4_STAGE_TASKBOOK_GATE_READINESS_CONTRACT_V1.zh-CN.md` | `companion_draft` | Stage 2 / v2.4 中文 companion 已生成，尚未授权实现、gate-ready 状态推进、executor、commit 或 push。 |
| `docs/taskbooks/versions/stage-02/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_02_VERSIONS.md` | `docs/taskbooks/versions/stage-02/zh-CN/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_02_VERSIONS.zh-CN.md` | `companion_draft` | Stage 2 Version set freeze confirmation record 中文 companion 已生成，只记录精确 hash 的 freeze_candidate 审查状态，不授权实现、registry mutation、commit 或 push。 |
| `docs/taskbooks/versions/stage-03/VERSION_STAGE_03_V3_1_EXTERNAL_TASKBOOK_SCHEMA_V1.md` | `docs/taskbooks/versions/stage-03/zh-CN/VERSION_STAGE_03_V3_1_EXTERNAL_TASKBOOK_SCHEMA_V1.zh-CN.md` | `companion_draft` | Stage 3 / v3.1 中文 companion 已生成，尚未授权实现、external import、plan mutation、executor、commit 或 push。 |
| `docs/taskbooks/versions/stage-03/VERSION_STAGE_03_V3_2_EXTERNAL_TASKBOOK_VALIDATOR_V1.md` | `docs/taskbooks/versions/stage-03/zh-CN/VERSION_STAGE_03_V3_2_EXTERNAL_TASKBOOK_VALIDATOR_V1.zh-CN.md` | `companion_draft` | Stage 3 / v3.2 中文 companion 已生成，尚未授权实现、validator helper、import adoption、executor、commit 或 push。 |
| `docs/taskbooks/versions/stage-03/VERSION_STAGE_03_V3_3_TASKBOOK_IMPORT_PREVIEW_V1.md` | `docs/taskbooks/versions/stage-03/zh-CN/VERSION_STAGE_03_V3_3_TASKBOOK_IMPORT_PREVIEW_V1.zh-CN.md` | `companion_draft` | Stage 3 / v3.3 中文 companion 已生成，尚未授权实现、import preview execution、plan mutation、executor、commit 或 push。 |
| `docs/taskbooks/versions/stage-03/VERSION_STAGE_03_V3_4_TASKBOOK_TO_VERSION_CANDIDATE_MAPPING_V1.md` | `docs/taskbooks/versions/stage-03/zh-CN/VERSION_STAGE_03_V3_4_TASKBOOK_TO_VERSION_CANDIDATE_MAPPING_V1.zh-CN.md` | `companion_draft` | Stage 3 / v3.4 中文 companion 已生成，尚未授权实现、candidate mapping execution、plan insertion、executor、commit 或 push。 |
| `docs/taskbooks/versions/stage-03/VERSION_STAGE_03_V3_5_TASKBOOK_IMPORT_ADOPTION_PREVIEW_V1.md` | `docs/taskbooks/versions/stage-03/zh-CN/VERSION_STAGE_03_V3_5_TASKBOOK_IMPORT_ADOPTION_PREVIEW_V1.zh-CN.md` | `companion_draft` | Stage 3 / v3.5 中文 companion 已生成，尚未授权实现、import adoption、plan mutation、executor、commit 或 push。 |
| `docs/taskbooks/versions/stage-04/VERSION_STAGE_04_V4_1_MACHINE_CHECKABLE_EXECUTION_ENVELOPE_V1.md` | `docs/taskbooks/versions/stage-04/zh-CN/VERSION_STAGE_04_V4_1_MACHINE_CHECKABLE_EXECUTION_ENVELOPE_V1.zh-CN.md` | `companion_draft` | Stage 4 / v4.1 中文 companion 已生成，尚未授权实现、executor dispatch、commit 或 push。 |
| `docs/taskbooks/versions/stage-04/VERSION_STAGE_04_V4_2_TASKBOOK_BOUND_EXECUTOR_RUN_PREVIEW_V1.md` | `docs/taskbooks/versions/stage-04/zh-CN/VERSION_STAGE_04_V4_2_TASKBOOK_BOUND_EXECUTOR_RUN_PREVIEW_V1.zh-CN.md` | `companion_draft` | Stage 4 / v4.2 中文 companion 已生成，尚未授权实现、executor run、commit 或 push。 |
| `docs/taskbooks/versions/stage-04/VERSION_STAGE_04_V4_3_TASKBOOK_BOUND_LOCAL_EXECUTION_RECEIPT_V1.md` | `docs/taskbooks/versions/stage-04/zh-CN/VERSION_STAGE_04_V4_3_TASKBOOK_BOUND_LOCAL_EXECUTION_RECEIPT_V1.zh-CN.md` | `companion_draft` | Stage 4 / v4.3 中文 companion 已生成，尚未授权实现、local execution、review acceptance、commit 或 push。 |
| `docs/taskbooks/versions/stage-04/VERSION_STAGE_04_V4_4_IMPORTED_EXECUTION_RECEIPT_V1.md` | `docs/taskbooks/versions/stage-04/zh-CN/VERSION_STAGE_04_V4_4_IMPORTED_EXECUTION_RECEIPT_V1.zh-CN.md` | `companion_draft` | Stage 4 / v4.4 中文 companion 已生成，尚未授权实现、imported receipt adoption、commit 或 push。 |
| `docs/taskbooks/versions/stage-04/VERSION_STAGE_04_V4_5_TASKBOOK_BOUND_EXECUTOR_REPORT_V1.md` | `docs/taskbooks/versions/stage-04/zh-CN/VERSION_STAGE_04_V4_5_TASKBOOK_BOUND_EXECUTOR_REPORT_V1.zh-CN.md` | `companion_draft` | Stage 4 / v4.5 中文 companion 已生成，尚未授权实现、executor report generation、review acceptance、commit 或 push。 |
| `docs/taskbooks/versions/stage-04/VERSION_STAGE_04_V4_6_EXECUTION_EVIDENCE_RECEIPT_V1.md` | `docs/taskbooks/versions/stage-04/zh-CN/VERSION_STAGE_04_V4_6_EXECUTION_EVIDENCE_RECEIPT_V1.zh-CN.md` | `companion_draft` | Stage 4 / v4.6 中文 companion 已生成，尚未授权实现、evidence receipt generation、review acceptance、commit 或 push。 |
| `docs/taskbooks/versions/stage-04/VERSION_STAGE_04_V4_7_VALIDATION_TRUTH_INTEGRATION_V1.md` | `docs/taskbooks/versions/stage-04/zh-CN/VERSION_STAGE_04_V4_7_VALIDATION_TRUTH_INTEGRATION_V1.zh-CN.md` | `companion_draft` | Stage 4 / v4.7 中文 companion 已生成，尚未授权实现、validation execution、review acceptance、commit 或 push。 |
| `docs/taskbooks/versions/stage-04/VERSION_STAGE_04_V4_8_SCOPE_EVIDENCE_PACK_V1.md` | `docs/taskbooks/versions/stage-04/zh-CN/VERSION_STAGE_04_V4_8_SCOPE_EVIDENCE_PACK_V1.zh-CN.md` | `companion_draft` | Stage 4 / v4.8 中文 companion 已生成，尚未授权实现、scope judgment acceptance、commit 或 push。 |
| `docs/taskbooks/versions/stage-04/VERSION_STAGE_04_V4_9_AUDIT_PACKAGE_TASKBOOK_BINDING_V1.md` | `docs/taskbooks/versions/stage-04/zh-CN/VERSION_STAGE_04_V4_9_AUDIT_PACKAGE_TASKBOOK_BINDING_V1.zh-CN.md` | `companion_draft` | Stage 4 / v4.9 中文 companion 已生成，尚未授权实现、reviewer handoff completion、review acceptance、commit 或 push。 |
| `docs/taskbooks/versions/stage-05/VERSION_STAGE_05_V5_1_REVIEWER_HANDOFF_SCHEMA_V1.md` | `docs/taskbooks/versions/stage-05/zh-CN/VERSION_STAGE_05_V5_1_REVIEWER_HANDOFF_SCHEMA_V1.zh-CN.md` | `companion_draft` | Stage 5 / v5.1 中文 companion 已生成，尚未授权实现、review acceptance、commit 或 push。 |
| `docs/taskbooks/versions/stage-05/VERSION_STAGE_05_V5_2_REVIEWER_HANDOFF_GENERATOR_V1.md` | `docs/taskbooks/versions/stage-05/zh-CN/VERSION_STAGE_05_V5_2_REVIEWER_HANDOFF_GENERATOR_V1.zh-CN.md` | `companion_draft` | Stage 5 / v5.2 中文 companion 已生成，尚未授权实现、ReviewDecision creation、GateEvent emission、commit 或 push。 |
| `docs/taskbooks/versions/stage-05/VERSION_STAGE_05_V5_3_ALIGNMENT_QUESTIONS_V1.md` | `docs/taskbooks/versions/stage-05/zh-CN/VERSION_STAGE_05_V5_3_ALIGNMENT_QUESTIONS_V1.zh-CN.md` | `companion_draft` | Stage 5 / v5.3 中文 companion 已生成，尚未授权实现、alignment confirmed、review acceptance、commit 或 push。 |
| `docs/taskbooks/versions/stage-05/VERSION_STAGE_05_V5_4_DRIFT_QUESTION_PACK_V1.md` | `docs/taskbooks/versions/stage-05/zh-CN/VERSION_STAGE_05_V5_4_DRIFT_QUESTION_PACK_V1.zh-CN.md` | `companion_draft` | Stage 5 / v5.4 中文 companion 已生成，尚未授权实现、drift verdict automation、review acceptance、commit 或 push。 |
| `docs/taskbooks/versions/stage-05/VERSION_STAGE_05_V5_5_REVIEWER_PACKAGE_REPORT_SURFACE_V1.md` | `docs/taskbooks/versions/stage-05/zh-CN/VERSION_STAGE_05_V5_5_REVIEWER_PACKAGE_REPORT_SURFACE_V1.zh-CN.md` | `companion_draft` | Stage 5 / v5.5 中文 companion 已生成，尚未授权实现、ReviewDecision submission、GateEvent emission、commit 或 push。 |
| `.colameta/plan.json` | `.colameta/plan.zh-CN.md` | `companion_draft` | 机器计划 JSON 的中文可读镜像已生成。 |
| `.colameta/prompts/v1.0.md` | `.colameta/prompts/zh-CN/v1.0.zh-CN.md` | `companion_draft` | Version prompt 中文 companion 已生成。 |
| `.colameta/prompts/v1.1.md` | `.colameta/prompts/zh-CN/v1.1.zh-CN.md` | `companion_draft` | Version prompt 中文 companion 已生成。 |
| `.colameta/prompts/v1.2.md` | `.colameta/prompts/zh-CN/v1.2.zh-CN.md` | `companion_draft` | Version prompt 中文 companion 已生成。 |
| `.colameta/prompts/v1.3.md` | `.colameta/prompts/zh-CN/v1.3.zh-CN.md` | `companion_draft` | Version prompt 中文 companion 已生成。 |
| `.colameta/prompts/v1.4.md` | `.colameta/prompts/zh-CN/v1.4.zh-CN.md` | `companion_draft` | Version prompt 中文 companion 已生成。 |
| `.colameta/prompts/v1.5.md` | `.colameta/prompts/zh-CN/v1.5.zh-CN.md` | `companion_draft` | Version prompt 中文 companion 已生成。 |
| `.colameta/prompts/v1.6.md` | `.colameta/prompts/zh-CN/v1.6.zh-CN.md` | `companion_draft` | Version prompt 中文 companion 已生成。 |
| `.colameta/prompts/v1.6.1.md` | `.colameta/prompts/zh-CN/v1.6.1.zh-CN.md` | `companion_draft` | Version prompt 中文 companion 已生成。 |
| `.colameta/prompts/v1.7.md` | `.colameta/prompts/zh-CN/v1.7.zh-CN.md` | `companion_draft` | Version prompt 中文 companion 已生成。 |
| `.colameta/prompts/v1.8.md` | `.colameta/prompts/zh-CN/v1.8.zh-CN.md` | `companion_draft` | Version prompt 中文 companion 已生成。 |
| `.colameta/prompts/v1.9.md` | `.colameta/prompts/zh-CN/v1.9.zh-CN.md` | `companion_draft` | Version prompt 中文 companion 已生成。 |
| `.colameta/prompts/v1.10.md` | `.colameta/prompts/zh-CN/v1.10.zh-CN.md` | `companion_draft` | Version prompt 中文 companion 已生成。 |

---

## 4. 当前执行原则

```yaml id="current-execution-principle"
current_execution_principle:
  first_batch:
    - docs/taskbooks/CHINESE_COMPANION_POLICY.md
    - docs/taskbooks/CHINESE_COMPANION_INDEX.md
  completed_draft_batch:
    - PROJECT_MASTER_TASKBOOK.zh-CN.md
    - FREEZE_CANDIDATE_REVIEW_PACKET.zh-CN.md
    - docs/taskbooks/stages/zh-CN/*.zh-CN.md
    - .colameta/prompts/zh-CN/*.zh-CN.md
    - .colameta/plan.zh-CN.md
  later_batches: []
```

中文解释：先建立制度和清单，再按批次补全文中文 companion。不能把摘要当全文。
