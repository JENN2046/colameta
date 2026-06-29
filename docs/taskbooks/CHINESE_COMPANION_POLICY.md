# 中文 Companion 文档策略

```yaml id="chinese-companion-policy-summary"
chinese_companion_policy:
  document_type: governance_policy
  status: discussion_draft
  authority_status: planning_reference_only
  policy_name: Chinese Companion Documentation Policy
  chinese_name: 中文伴随文档策略
```

`Chinese Companion` = 中文伴随文档。中文意思是：每一份英文计划文档、任务书、
审查包、版本任务书，都必须有一份全中文可读版本，供 Commander 和中文审查者
直接阅读。

---

## 1. 核心规则

```yaml id="core-rule"
core_rule:
  required: true
  statement: >
    ColaMeta 项目内所有计划类文档，无论大小，都必须拥有一份全中文版本。
  applies_to:
    - Project Master Taskbook
    - Freeze Candidate Review Packet
    - Stage Taskbook
    - Version Execution Taskbook
    - Prompt Taskbook
    - Plan manifest
    - Review packet
    - Governance policy document
```

中文解释：以后不能只有英文计划。只要它会指导路线、阶段、版本、审查、冻结、
执行边界或授权边界，就必须有中文 companion。

---

## 2. 命名规则

```yaml id="naming-rule"
naming_rule:
  markdown_companion_suffix: .zh-CN.md
  json_companion_suffix: .zh-CN.md
  examples:
    - source: PROJECT_MASTER_TASKBOOK.md
      companion: PROJECT_MASTER_TASKBOOK.zh-CN.md
    - source: FREEZE_CANDIDATE_REVIEW_PACKET.md
      companion: FREEZE_CANDIDATE_REVIEW_PACKET.zh-CN.md
    - source: docs/taskbooks/stages/STAGE_01_MASTER_TASKBOOK_ANCHORING.md
      companion: docs/taskbooks/stages/zh-CN/STAGE_01_MASTER_TASKBOOK_ANCHORING.zh-CN.md
    - source: .colameta/plan.json
      companion: .colameta/plan.zh-CN.md
```

中文解释：英文原文件不改名，中文版本用 `.zh-CN.md` 作为伴随文件。

---

## 3. 权威边界

```yaml id="authority-boundary"
authority_boundary:
  english_hash_bound_source:
    meaning: 已经被 hash 绑定或确认过的英文原文，不能因为中文翻译而被静默改写。
  chinese_companion:
    meaning: 中文 companion 是中文可读镜像，默认不替代原文的 hash 权威。
  conflict_rule:
    default: >
      如果英文 hash-bound 原件和中文 companion 冲突，必须停下并标记为 translation_conflict。
  promotion_rule:
    statement: >
      中文 companion 只有在单独通过 Commander 授权、hash 绑定和审查后，才可以成为同级权威副本。
```

中文解释：中文版本是必须有的，但不能偷偷改变已经确认过的英文 hash。翻译和
原文冲突时，不能靠猜，必须停下来修。

---

## 4. 中文版本最低要求

```yaml id="minimum-requirements"
minimum_requirements:
  required_sections:
    - source_document_ref
    - source_hash_if_known
    - translation_status
    - authority_boundary
    - full_chinese_body
    - technical_term_glossary
    - known_translation_gaps
  forbidden_shortcuts:
    - summary_only_when_full_version_is_required
    - mixed_english_without_chinese_explanation
    - omitting_authority_boundary
    - treating_translation_as_new_authorization
```

中文解释：不能只写摘要冒充中文版本。技术名词可以保留英文，但必须解释中文
意思。

---

## 5. 状态规则

```yaml id="status-rule"
status_rule:
  missing_companion: 中文 companion 缺失。
  companion_draft: 中文 companion 已存在，但还没有完成全文审查。
  companion_review_ready: 中文 companion 已可读，等待审查。
  companion_accepted_for_reference: 中文 companion 可作为中文参考版本。
  translation_conflict: 中文 companion 和原文存在冲突，必须修复。
```

中文解释：中文文档也有状态，不是写出来就自动算通过。

---

## 6. 冻结前要求

```yaml id="freeze-readiness-rule"
freeze_readiness_rule:
  stage_or_master_freeze_candidate:
    requires_chinese_companion: true
  version_execution_taskbook:
    requires_chinese_companion_before_execution: true
  review_packet:
    requires_chinese_companion_before_commander_confirmation: true
```

中文解释：以后 Master、Stage、Version、review packet 要进入关键确认前，都要
有中文 companion。否则 Commander 很容易被迫读英文技术文本，这不符合项目制度。

---

## 7. 当前迁移规则

```yaml id="migration-rule"
migration_rule:
  current_state: 英文计划文档已经存在，中文 companion 需要补齐。
  migration_mode: staged_translation
  allowed:
    - 先建立清单
    - 分批生成中文 companion
    - 每批做 hash 和冲突检查
  not_allowed:
    - 修改已确认 hash 的英文 Master 原件
    - 用摘要冒充完整中文版本
    - 把中文翻译当作新的执行授权
    - 因为缺中文 companion 而自动修改路线状态
```

中文解释：当前不会去改英文 Master 的内容，而是旁边补中文版本。
