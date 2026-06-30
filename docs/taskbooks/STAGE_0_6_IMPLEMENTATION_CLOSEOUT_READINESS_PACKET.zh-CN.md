# Stage 0-6 实施收口就绪材料包中文 Companion

```yaml id="companion-binding"
companion_binding:
  language: zh-CN
  companion_type: full_chinese_reading_companion
  authority_status: non_authoritative_companion
  source_document: docs/taskbooks/STAGE_0_6_IMPLEMENTATION_CLOSEOUT_READINESS_PACKET.md
  source_sha256: 5f2717dbfede92a4a07d0ddb5cda6ddcbb049c99416cb2202eac0ef70f4aa4f4
```

## 这份文件是什么

`Implementation Closeout Readiness Packet` = 实施收口就绪材料包。中文意思是：本地
Stage 0-6 这条实现路线已经做到一个可收口点，这份材料把当前 HEAD、实现范围、证据、
测试结果、manifest hash 和 push 前边界收拢起来，供 Commander 判断是否进入 push。

这份中文 companion 不是英文源文件的权威替代，不授权 push、fetch、pull、executor run、
route transition、remote write、service restart、release / deploy、ReviewDecision、
GateEvent、review acceptance 或 Delivery State Gate transition。

## 指挥官快速阅读

```yaml id="commander-quick-read"
commander_quick_read:
  current_decision: decide_whether_to_prepare_final_non_force_push_authorization
  local_closeout_status: Stage 1-6 implementation evidence recorded and tests passed
  latest_validated_test_result: "505 tests passed via .venv/bin/python -m unittest discover -s tests"
  worktree_requirement_for_push: clean_at_final_authorization_time
  final_push_facts_required:
    - current_HEAD_observed_immediately_before_authorization
    - current_origin_main_local_tracking_ref_observed_immediately_before_authorization
    - current_ahead_behind_from_local_refs_observed_immediately_before_authorization
  generation_facts_are_not_final_push_facts: true
  still_missing_for_push_authority: explicit Commander confirmation
  must_not_do:
    - force_push
    - fetch_or_pull_without_separate_authorization
    - executor_run
    - route_transition
    - delivery_state_transition
```

中文解释：这份材料先帮助 Commander 判断“本地实施收口是否可信”，再决定是否生成
最终 push 授权。最终 push 授权不能直接复制 packet 生成时的 HEAD、ahead/behind 或
tracking ref，必须在授权前重新观察当前仓库状态。

## 当前 repo 现实

```yaml id="repo-reality"
repo_reality:
  project: ColaMeta
  workspace: /home/jenn/src/colameta-dev
  stable_service_runtime_path: /home/jenn/tools/colameta
  branch: main
  generation_head: 1219846e5ad2ddd800582d43d9dc450e7711d1ab
  generation_head_subject: "feat(taskbooks): add review decision adapter"
  generation_head_meaning: implementation_closeout_head_before_packet_storage
  generation_origin_main_tracking_ref: 018ff63b76872504407c537cd46e1e8a2ee5c22e
  generation_ahead_origin_main_from_local_refs: 81
  generation_behind_origin_main_from_local_refs: 0
  live_remote_status_not_validated: true
  worktree_status_at_generation: clean
```

中文解释：这里的 `generation_head` 是 packet 生成时、还没提交 packet 前的实现收口 HEAD。
packet 自己提交后，仓库 HEAD 会继续前进，所以真正 push 授权必须绑定最终确认时的当前
HEAD。这里的 ahead 81 / behind 0 也是生成材料时基于本地 tracking ref 的事实，不是最终
push 授权可直接复用的实时事实。这里没有做 `fetch`，所以不能证明远端此刻没有新变化。

## 范围

这份 closeout 覆盖的是：

- Stage 1：Master Taskbook Anchoring；
- Stage 2：Stage Taskbook Management；
- Stage 3：External Taskbook Import Protocol；
- Stage 4：Bounded Execution And Evidence；
- Stage 5：Reviewer Handoff Package；
- Stage 6：Review Feedback Intake。

Stage 0 是 baseline / reality clarity 阶段，所以本地实现路线从 Stage 1 / v1.1 开始。

## 关键规划锚点

```yaml id="planning-anchors"
planning_anchors:
  pre_implementation_route_start_gate:
    path: docs/taskbooks/PRE_IMPLEMENTATION_ROUTE_START_GATE.md
    sha256: 871736b661e15cc0e85feb35f7294b2e7506673c74b3142afd9413a95ae93620
  master_taskbook:
    path: PROJECT_MASTER_TASKBOOK.md
    sha256: 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
  stage_0_6_stage_set_packet:
    path: docs/taskbooks/stages/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_0_6.md
    sha256: 94ea9101a120e0935e834533ed0315a6fe3e77e3d4ecb48db37fa6851e75b5ce
```

中文解释：这些是路线来源和上游计划锚点，不是新的执行授权。

## 实现产物 Manifest

```yaml id="implementation-artifact-manifests"
implementation_artifact_manifests:
  manifest_method: sha256_of_sorted_sha256sum_manifest_lines
  combined_stage_1_6_artifact_manifest:
    file_count: 138
    sha256: f8f38c816511b4efa6c8563952fed1cab11f495f4630ade03ea7e9c8c8bd0610
  stage_manifests:
    stage_01:
      file_count: 21
      sha256: f28fb587b0833742e461ba25c183eb8430e987084b33f9f9d15c51ec9d05efa6
    stage_02:
      file_count: 18
      sha256: 1f81e5630c82713fbf5ed5519989d301470618fcb8fa1076fbe9a00d7ee8cd4b
    stage_03:
      file_count: 21
      sha256: 02580220952da3ee1b27c6403de12e49eed4706762b5373b4de95bc74ff1ce07
    stage_04:
      file_count: 36
      sha256: 00380e463173b2a9fc1dbda4a6472043a45f6aecc63c6be0cab01fac9e8fcde0
    stage_05:
      file_count: 20
      sha256: 3ea7e9aca085df84ab800b617818d88d3d9f310d5bd8ef8392373e367d0a41bb
    stage_06:
      file_count: 22
      sha256: fbe60f4ce9297d98647bddd08d606f24955e9853b3852d72ff4d07b588d73e19
```

中文解释：这里不是把所有文件逐行塞进材料，而是把所有实现产物按排序后的 `sha256sum`
清单再 hash 成 manifest。这样既可复核，又不会让材料臃肿。复算命令必须在 WSL 仓库根目录
`/home/jenn/src/colameta-dev` 运行。这里的实现产物集合只包括 Stage 1-6 每个 slice 产出的
`.colameta/taskbooks` 合约、`runner/` helper、对应测试、英文证据报告和中文证据 companion；
不是把整个 `runner/` 或 `tests/` 目录全部扫进去。

```bash id="manifest-recompute-command"
# Run from /home/jenn/src/colameta-dev
.venv/bin/python - <<'PY'
from pathlib import Path
import hashlib
import subprocess

stages = {
    "stage_01": {
        "contracts": [".colameta/taskbooks/master_taskbook_registry.json"],
        "modules": "master_taskbook_registry master_taskbook_reader master_taskbook_validator master_taskbook_hash_binding master_taskbook_mutation_gate".split(),
    },
    "stage_02": {
        "contracts": [".colameta/taskbooks/stage_taskbook_schema.json", ".colameta/taskbooks/stage_taskbook_registry.json"],
        "modules": "stage_taskbook_validator stage_taskbook_registry stage_to_master_binding stage_taskbook_gate_readiness".split(),
    },
    "stage_03": {
        "contracts": [".colameta/taskbooks/external_taskbook_schema.json"],
        "modules": "external_taskbook_schema external_taskbook_validator taskbook_import_preview taskbook_version_candidate_mapping taskbook_import_adoption_preview".split(),
    },
    "stage_04": {
        "contracts": [],
        "modules": "execution_envelope executor_run_preview local_execution_receipt imported_execution_receipt executor_report execution_evidence_receipt validation_truth scope_evidence_pack audit_package_taskbook_binding".split(),
    },
    "stage_05": {
        "contracts": [],
        "modules": "reviewer_handoff_schema reviewer_handoff_generator reviewer_alignment_questions reviewer_drift_questions reviewer_package_report_surface".split(),
    },
    "stage_06": {
        "contracts": [],
        "modules": "review_feedback_schema review_feedback_validator review_feedback_preview review_feedback_classification commander_decision_request review_decision_adapter".split(),
    },
}

def manifest(files):
    lines = [subprocess.check_output(["sha256sum", f]).decode().strip()
             for f in sorted(dict.fromkeys(files))]
    payload = "\n".join(lines) + "\n"
    return len(lines), hashlib.sha256(payload.encode()).hexdigest()

combined = []
for stage_id, data in stages.items():
    stage_number = stage_id[-2:]
    files = list(data["contracts"])
    files += [f"runner/{module}.py" for module in data["modules"]]
    files += [f"tests/test_{module}.py" for module in data["modules"]]
    files += sorted(
        str(path)
        for path in Path(f"docs/taskbooks/versions/stage-{stage_number}/evidence").rglob("*")
        if path.is_file()
    )
    combined.extend(files)
    print(stage_id, *manifest(files))
print("combined", *manifest(combined))
PY
```

## 阶段收口摘要

```yaml id="stage-closeout-summary"
stage_closeout_summary:
  stage_01: Master Taskbook registry / reader / validator / hash binding / mutation hard gate 已本地实现
  stage_02: Stage Taskbook schema / registry / Stage-to-Master binding / gate-readiness helper 已本地实现
  stage_03: External taskbook schema / validator / import preview / candidate mapping / adoption preview 已本地实现
  stage_04: Execution envelope / previews / receipts / validation truth / scope evidence / audit package binding 已本地实现
  stage_05: Reviewer handoff schema / generator / alignment questions / drift questions / report surface 已本地实现
  stage_06: Review feedback schema / validator / preview / CommanderDecisionRequest / adapter boundary 已本地实现
```

## 验证结果

```yaml id="validation-results"
validation_results:
  validation_command_context:
    default_working_directory: /home/jenn/src/colameta-dev
    shell_context: WSL/Linux repository root
    powershell_wrapper_if_needed: "wsl -d Ubuntu-24.04 --cd /home/jenn/src/colameta-dev -- bash -lc '<command>'"
  stage_05_package_review:
    result: passed
    tests_run: 38
  stage_06_package_review:
    result: passed
    tests_run: 49
  full_local_unittest_discovery:
    command: .venv/bin/python -m unittest discover -s tests
    result: passed
    tests_run: 505
  git_diff_check:
    result: passed
  chinese_evidence_source_hash_checks:
    result: passed
  forbidden_authority_effect_scans:
    result: passed
    scan_note: >
      应使用 key-level 的正向权限字段扫描。粗暴按 true 值 grep 可能误伤
      does_not_mean_delivery_state_accepted: true 这类否定边界字段。
```

中文解释：本地完整测试是 505 个测试全绿。`unittest discover` 必须带 `-s tests`，因为
裸 `unittest discover` 在 repo 根会发现 0 个测试。

## Reviewer 阅读路径

| 顺序 | 阅读对象 | 用途 |
| --- | --- | --- |
| 1 | `docs/taskbooks/STAGE_0_6_IMPLEMENTATION_CLOSEOUT_READINESS_PACKET.md` 和本中文 companion | 先看整条路线的收口状态、权限边界、测试结果和 push 决策状态。 |
| 2 | `docs/taskbooks/versions/stage-05/evidence/VERSION_STAGE_05_V5_5_REVIEWER_PACKAGE_REPORT_SURFACE_REPORT.md` 与 `docs/taskbooks/versions/stage-05/evidence/zh-CN/VERSION_STAGE_05_V5_5_REVIEWER_PACKAGE_REPORT_SURFACE_REPORT.zh-CN.md` | 看 Stage 5 最终给 reviewer 的 handoff surface。 |
| 3 | `docs/taskbooks/versions/stage-06/evidence/VERSION_STAGE_06_V6_1_REVIEW_FEEDBACK_SCHEMA_REPORT.md` 到 `VERSION_STAGE_06_V6_5_REVIEW_DECISION_ADAPTER_REPORT.md`，以及 `docs/taskbooks/versions/stage-06/evidence/zh-CN/` 下对应中文 companion | 看反馈接入链路如何从 reviewer 输入走到非权威 adapter 输出。 |
| 4 | `runner/reviewer_package_report_surface.py`、`runner/review_feedback_*.py`、`runner/commander_decision_request.py`、`runner/review_decision_adapter.py` | 看用户可见手感和 review feedback 机制。 |
| 5 | 本材料里的验证命令 | 在最终 push 授权前复跑最近一层信心检查。 |

中文证据 companion 里有些旧文件使用 `source_document`，有些证据报告 companion 使用
`source_report`。在本 closeout 审查里二者都是“源文件绑定键”，只要配套的 `source_sha256`
能匹配被引用源文件，就按同一类边界处理。

## Push 决策状态

```yaml id="push-readiness-decision-state"
push_readiness_decision_state:
  readiness_outcome: ready_for_commander_push_decision_review
  can_prepare_push_confirmation_prompt: true
  push_authorized_by_this_packet: false
  implementation_closeout_head_before_packet_storage: 1219846e5ad2ddd800582d43d9dc450e7711d1ab
  push_target_head_must_be_current_observed_head_at_authorization: true
  generation_origin_main_tracking_ref: 018ff63b76872504407c537cd46e1e8a2ee5c22e
  generation_ahead_behind_from_local_refs:
    behind: 0
    ahead: 81
  final_push_prompt_must_use_fresh_observation: true
  stale_generation_values_must_not_be_copied_into_final_push_prompt: true
  current_values_to_fill_at_final_authorization:
    current_head: "<CURRENT_OBSERVED_HEAD_AT_PUSH_AUTHORIZATION>"
    current_origin_main_tracking_ref: "<CURRENT_OBSERVED_ORIGIN_MAIN_LOCAL_REF_AT_PUSH_AUTHORIZATION>"
    current_ahead_behind_from_local_refs: "<CURRENT_OBSERVED_AHEAD_BEHIND_AT_PUSH_AUTHORIZATION>"
  live_remote_status_not_validated: true
```

中文解释：材料结论是“可以进入 Commander push 决策审查”，不是“已经可以 push”。如果
Commander 要求证明远端实时状态，需要单独授权 `fetch` 或等价远端检查。

## 禁止动作

这份材料不授权：

- push / fetch / pull；
- force push；
- history rewrite；
- tag / release / deploy / package publish；
- executor run；
- route transition；
- remote write；
- service restart；
- 修改 `/home/jenn/tools/colameta`；
- ReviewDecision creation；
- GateEvent emission；
- review acceptance；
- Delivery State Gate transition。

## Push Commander Prompt 草稿

```text id="commander-push-confirmation-prompt-draft"
AUTHORIZE_PUSH_STAGE_0_6_IMPLEMENTATION_CLOSEOUT_COMMITS_FOR_CURRENT_HEAD_ONLY

Target:
- Project: ColaMeta
- Workspace: /home/jenn/src/colameta-dev
- Branch: main
- Current HEAD:
  <CURRENT_OBSERVED_HEAD_AT_PUSH_AUTHORIZATION>
- Implementation closeout generation HEAD before packet storage:
  1219846e5ad2ddd800582d43d9dc450e7711d1ab
- Local origin/main tracking ref:
  <CURRENT_OBSERVED_ORIGIN_MAIN_LOCAL_REF_AT_PUSH_AUTHORIZATION>
- Local ahead/behind from local refs:
  <CURRENT_OBSERVED_AHEAD_BEHIND_AT_PUSH_AUTHORIZATION>

Allowed:
- verify current HEAD still equals the exact current observed HEAD supplied in the final Commander confirmation
- verify worktree is clean
- verify local origin/main tracking ref still equals the exact current observed ref supplied in the final Commander confirmation
- run git push origin main as a non-force push

Not allowed:
- force push
- fetch
- pull
- history rewrite
- tag
- release / deploy / package publish
- executor run
- route transition
- remote write other than the single non-force git push
- service restart
- modifying /home/jenn/tools/colameta
- review acceptance
- ReviewDecision creation
- GateEvent emission
- Delivery State Gate transition
```

中文解释：这是下一步可能使用的 push 授权口令草稿。只有你明确确认后才可执行。
