# Stage 4 中文任务书：有边界执行与证据

```yaml id="stage-04-zh-cn-summary"
chinese_companion:
  source_document: docs/taskbooks/stages/STAGE_04_BOUNDED_EXECUTION_AND_EVIDENCE.md
  source_sha256: a71d1a6cf00cfecd67421c3a6ade6327156547aec49cba169909e39d1bf153c4
  translation_status: companion_draft
  authority_status: planning_reference_only
stage:
  stage_id: stage_04_bounded_execution_and_evidence
  chinese_name: 有边界执行与证据
  status: discussion_draft
```

## 1. 阶段定位

Stage 4 把另行授权的版本任务候选，准备成有边界、机器可检查的
`ExecutionEnvelope`，并记录本地执行证据或外部执行回执。

它不是通用 executor dispatch 平台。

## 2. 关键概念

- `ExecutionEnvelope` = 执行信封。说明一次执行允许做什么、不能做什么、验证命令、
  可改文件和边界。
- `Receipt` = 回执。记录执行或验证实际发生了什么，不替它宣布通过。
- `authority_mode` = 权限模式。说明证据来自本地执行授权还是外部回执导入授权。

## 3. 进入条件

进入 Stage 4 需要：

- version taskbook 有有效 master_taskbook_ref；
- version taskbook 有有效 stage_taskbook_ref；
- 本地 dispatch 请求必须有 `local_execution_authorization_ref`；
- 外部 receipt adoption 请求必须有 `imported_receipt_authorization_ref`；
- allowed_files、forbidden_files 明确；
- validation commands 明确。

不需要 multi-provider dispatch、automatic repair、automatic review、automatic commit。

## 4. 退出条件

Stage 4 完成时需要：

- execution envelope 机器可检查；
- invalid envelope dispatch 前 fail closed；
- envelope schema、run preview、local execution receipt、imported receipt 是不同记录；
- execution/imported receipt report 绑定 version taskbook；
- report 记录 master_taskbook_hash 和 stage_taskbook_hash；
- receipt 区分 executed、imported、validated；
- validation failure 不能总结成 passed；
- scope violation 明确；
- envelope 存在本身不能授权 dispatch；
- executor 不能自动提升 delivery_state。

## 5. 版本方向

Stage 4 后续版本方向：

- Machine-checkable Execution Envelope V1；
- Taskbook-bound Executor Run Preview V1；
- Taskbook-bound Local Execution Receipt V1；
- Imported Execution Receipt V1；
- Taskbook-bound Executor Report V1；
- Execution Evidence Receipt V1；
- Validation Truth Integration V1；
- Scope Evidence Pack V1；
- Audit Package Taskbook Binding V1。

## 6. 状态门就绪条件

Stage 4 的关键 gate-readiness：

- envelope 不自动授权 dispatch；
- local dispatch 需要 local_execution_authorization_ref；
- imported receipt adoption 需要 imported_receipt_authorization_ref；
- 两种 authorization ref 不能互相替代；
- envelope 内 retry/fix/validation loop 只有在同一 Version Taskbook 和 envelope 明确
  授权时才可运行；
- retry/fix/validation loop 不能扩展 files、commands、network、secrets、
  destructive operations、timeout、route 或 delivery state。

## 7. 最小证据包

最小证据包需要：

- execution_envelope_ref；
- authority_mode；
- local_execution_authorization_ref；
- imported_receipt_authorization_ref；
- matching_authority_ref_for_authority_mode；
- version_taskbook_ref；
- master_taskbook_hash；
- stage_taskbook_hash；
- allowed_scope；
- observed_mutations；
- validation_command；
- validation_result；
- uncertainty_or_known_gaps。

不能把 executor self-acceptance、缺少命令证据的 validation summary、runtime PASSED
label 当作权威。

## 8. 非目标

Stage 4 不做通用 executor-dispatch platform、不要求 multi-provider dispatcher、
不做 router integration、不自动 repair、不自动 review、不跨版本自动 continue、
不自动 commit/push。
