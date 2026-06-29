# 实施路线启动前总闸口材料中文 Companion

```yaml id="pre-implementation-route-start-gate-zh-cn-summary"
chinese_companion:
  source_document: docs/taskbooks/PRE_IMPLEMENTATION_ROUTE_START_GATE.md
  source_sha256: 871736b661e15cc0e85feb35f7294b2e7506673c74b3142afd9413a95ae93620
  translation_status: companion_draft
  authority_status: planning_reference_only
  translation_mode: full_semantic_chinese_mirror
```

`Pre-Implementation Route Start Gate Packet` = 实施路线启动前总闸口材料包。中文意思是：
它不是实现授权，而是在真正开工前，把“从哪里开始实现、第一刀做什么、能改哪些文件、
跑哪些验证、不能做什么、Commander 要确认什么”全部收拢成一份可审查材料。

本中文文件是英文源文件的中文 companion。它不替代英文源文件的 hash 权威，不授权
implementation、commit、push、executor run、route transition、remote write、
release / deploy 或 Delivery State Gate transition。

---

## 1. 这份材料包是什么

英文源文件声明：

```yaml
document_type: pre_implementation_route_start_gate_packet
schema_version: pre_implementation_route_start_gate.material_draft.v1
status: route_start_gate_material_draft
authority_status: commander_confirmation_prompt_draft_only
workspace: /home/jenn/src/colameta-dev
stable_service_runtime_path: /home/jenn/tools/colameta
material_generation_head: 25a70bd5578f140d2d6f591ee13aae5ddf56da28
ahead_origin_main_from_local_refs_at_material_generation: 47
worktree_status_at_material_generation: clean
implementation_authority: false
commit_authority: false
push_authority: false
executor_authority: false
route_transition_authority: false
```

中文解释：

- `route_start_gate_material_draft` = 路线启动总闸口材料草稿。
- `commander_confirmation_prompt_draft_only` = 这里只是准备给 Commander 确认的口令草稿。
- `implementation_authority: false` = 这份文件本身不授权实现。
- `stable_service_runtime_path` = 稳定服务运行目录，也就是 `/home/jenn/tools/colameta`，这次不允许改。
- `material_generation_head` = 生成这份材料时观察到的 HEAD，不等于材料提交后的当前 HEAD。

---

## 2. 总闸口前置条件

这份材料包要求以下事情已经完成：

- Master Taskbook 已经按精确 hash 进入 freeze candidate 审查状态；
- Stage 0-6 的 Stage 任务书集合已经完成 freeze candidate 确认；
- Stage 0-6 的 Version 任务书集合已经完成 freeze candidate 确认；
- Stage 0-6 全链路收口审查结果是 GO。

中文大白话：前面的大计划、阶段计划、版本计划都已经封到“可以准备实现路线”的程度。
但这还不是“可以直接实现”。真正开工还要 Commander 再确认一次精确口令。

---

## 3. Hash 绑定的输入

这份材料包绑定了这些关键输入：

| 名称 | 路径 | hash / 状态 |
| --- | --- | --- |
| Master Taskbook | `PROJECT_MASTER_TASKBOOK.md` | `1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34` |
| Master freeze packet | `FREEZE_CANDIDATE_REVIEW_PACKET.md` | `4199671538a07d3422ef510f1ad8718724b587e24cfa9014ccb6f2a1e0ef1236` |
| Stage 0-6 stage set packet | `docs/taskbooks/stages/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_0_6.md` | `94ea9101a120e0935e834533ed0315a6fe3e77e3d4ecb48db37fa6851e75b5ce` |
| Stage 1 / v1.1 taskbook | `docs/taskbooks/versions/stage-01/VERSION_STAGE_01_V1_1_MASTER_TASKBOOK_REGISTRY_V1.md` | `503af0ff7cdac71c55b9fa3d47a09d3fc484c851daffb244a52385ac0dd2b896` |
| Stage 1 version packet | `docs/taskbooks/versions/stage-01/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_01_VERSIONS.md` | `c4ef865c84ab634a7b3626cdc6924a4e51420a1d6d94bb274aeb9f13d354fce5` |
| Stage 6 version packet | `docs/taskbooks/versions/stage-06/FREEZE_CANDIDATE_REVIEW_PACKET_STAGE_06_VERSIONS.md` | `ffdb39ba91cdd1c016ec03030c0079731895f74e055b91fa50b0932db8cf0284` |

中文解释：这些 hash 是为了防止“材料准备时看的是 A 文件，真正开工时悄悄变成 B 文件”。
如果这些文件变了，就必须重新生成材料和确认口令。

---

## 4. Implementation Entry = 实施入口

英文源文件把实施入口定为：

```yaml
route_name: Stage 0-6 Thin Governed Loop Local Implementation Route
entry_stage: stage_01_master_taskbook_anchoring
entry_version: stage_01_v1_1_master_taskbook_registry_v1
route_start_mode: local_only
implementation_model: thin_governed_slice
```

中文解释：

- `Implementation Entry` = 实施入口，也就是第一步真正从哪个 Stage / Version 开始写代码。
- 这里选择 `Stage 1 / v1.1`，不是 Stage 0。
- 原因是 Stage 0 主要是基线和现实状态收束；第一刀真正可实现的治理能力，是 Stage 1 的
  `Master Taskbook Registry V1`。
- `local_only` = 只允许本地实现，不碰远端。
- `thin_governed_slice` = 薄治理切片，只做最小闭环，不做大平台。

---

## 5. First Implementation Slice = 首个实现切片

首个实现切片是：

```yaml
stage: Stage 1
version: v1.1
name: Master Taskbook Registry V1
chinese_name: 主任务书登记表 V1
```

它的目标是：

- 建一个最小 Master Taskbook registry，也就是“主任务书登记表”；
- 记录 `PROJECT_MASTER_TASKBOOK.md` 的路径、hash、审查状态边界、当前本地 git 状态；
- 明确 Master Taskbook 不能被 registry 偷偷改写；
- 写一个能加载和校验 registry 的小 helper；
- 写对应测试；
- 写执行证据报告和中文 companion。

它明确不做：

- 不改 `PROJECT_MASTER_TASKBOOK.md`；
- 不做完整 taskbook 平台；
- 不实现 Stage Taskbook 管理；
- 不实现外部任务书导入；
- 不调度 executor；
- 不声称 `delivery_state accepted`。

---

## 6. 授权边界

这份材料包本身授权：什么都不授权。

如果 Commander 以后确认精确口令，它只会授权：

- 在 allowed files 内做本地代码编辑；
- 在 allowed files 内做本地文档编辑；
- 运行材料包列出的验证命令；
- 生成本地证据报告。

它仍然不授权：

- commit；
- push；
- fetch / pull；
- executor run；
- route transition；
- remote write；
- service restart；
- release / deploy；
- 修改 `/home/jenn/tools/colameta`；
- 修改 `PROJECT_MASTER_TASKBOOK.md`；
- 修改 freeze confirmation packets；
- review acceptance；
- delivery state transition。

中文大白话：即使你以后确认这个口令，也只是允许“本地开工写这一小刀”，不是允许提交、
推送、跑执行器、改服务、切状态。

---

## 7. Allowed Files = 允许文件

未来精确授权后，可写文件只有：

```yaml
writable_after_commander_confirmation:
  - .colameta/taskbooks/master_taskbook_registry.json
  - runner/master_taskbook_registry.py
  - tests/test_master_taskbook_registry.py
  - docs/taskbooks/versions/stage-01/evidence/VERSION_STAGE_01_V1_1_MASTER_TASKBOOK_REGISTRY_REPORT.md
  - docs/taskbooks/versions/stage-01/evidence/zh-CN/VERSION_STAGE_01_V1_1_MASTER_TASKBOOK_REGISTRY_REPORT.zh-CN.md
```

中文解释：

- `.colameta/taskbooks/master_taskbook_registry.json` = 机器可读的主任务书登记记录。
- `runner/master_taskbook_registry.py` = 读取和校验登记表的小工具。
- `tests/test_master_taskbook_registry.py` = 对这个小工具的测试。
- evidence report = 证据报告，记录改了什么、跑了什么、没跑什么、风险是什么。

如果实现时发现还需要改别的文件，必须停下重新要边界，不能自动扩权。

---

## 8. Validation Commands = 验证命令

未来授权后候选验证命令包括：

```bash
git status --short --branch
git rev-parse HEAD
git rev-parse origin/main
git rev-list --left-right --count origin/main...HEAD
sha256sum PROJECT_MASTER_TASKBOOK.md docs/taskbooks/versions/stage-01/VERSION_STAGE_01_V1_1_MASTER_TASKBOOK_REGISTRY_V1.md
python -m compileall runner/master_taskbook_registry.py
python -m unittest tests.test_master_taskbook_registry
git diff --check
python -m unittest discover -s tests
```

中文解释：这些命令现在还没授权运行。它们只是写进材料包，等 Commander 确认后，
作为本地实现的验收路径。

---

## 9. Forbidden Actions = 禁止动作

这次总闸口明确禁止：

- fetch / pull / push；
- force push；
- remote write；
- executor run；
- route transition；
- service restart；
- release / deploy；
- 读写 credential / secret；
- 修改 `/home/jenn/tools/colameta`；
- 修改 `PROJECT_MASTER_TASKBOOK.md`；
- 修改 freeze confirmation packets；
- 自动扩大 allowed files；
- 声称 review acceptance；
- 声称 delivery state accepted；
- 靠实现本身关闭 P0。

中文解释：这是一道非常窄的门，只允许以后在本地实现 Stage 1 / v1.1，不允许把这个授权
扩成部署、远端同步、执行器运行或状态推进。

---

## 10. Commander Confirmation Prompt = 指挥官确认口令草稿

英文源文件准备的口令是：

```text
AUTHORIZE_STAGE_01_V1_1_LOCAL_IMPLEMENTATION_START_FOR_EXACT_GATE_ONLY
```

中文解释：这个口令的意思是“只授权当前精确 hash、当前精确边界下的 Stage 1 / v1.1
本地实现启动”。

但当前英文源文件里还有一个占位：

```text
<TO_BE_FILLED_AFTER_THIS_PACKET_IS_STORED>
<TO_BE_FILLED_AFTER_PACKET_STORAGE_AND_FINAL_REVIEW>
```

也就是说，这份 gate packet 先要被存入 Git，得到自己的精确 hash，并在存储后重新观察
当前 HEAD。之后才能生成最终 Commander prompt。没有这个最终 hash-specific prompt，
就不能开始实现。

---

## 11. 当前结论

```yaml
gate_outcome:
  current_packet_outcome: MATERIAL_DRAFT_READY_FOR_REVIEW
  may_enter_implementation_without_commander_confirmation: false
```

中文解释：材料草稿已经可以进入审查，但不能直接开工。下一步应该先审查这份材料包是否
存在 authority laundering、allowed files 太宽、验证命令不合理、或者 Commander prompt
边界不清的问题。
