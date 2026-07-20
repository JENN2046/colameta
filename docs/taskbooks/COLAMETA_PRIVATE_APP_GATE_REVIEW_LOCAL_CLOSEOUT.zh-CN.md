# ColaMeta 私人 App Work Item Gate Review 本地验收 Closeout

```yaml id="private-app-gate-review-local-closeout"
private_app_gate_review_local_closeout:
  schema_version: colameta_private_app_gate_review_local_closeout.v1
  closeout_status: ready
  decision: ready_for_live_private_app_acceptance
  authority_status: exact_stable_replacement_completed
  generated_at_utc: 2026-07-20T19:16:15Z
  last_validated_at_utc: 2026-07-20T21:30:55Z
  workspace: /home/jenn/src/colameta-dev
  branch: codex/stable-replacement-238cfec-receipt
  base_head: 2dc78955ac284c88d56feee71fa5ebbb02c5d8f8
  worktree_mode: tracked_clean_with_preexisting_untracked_user_asset
  commit_authority: true
  push_authority: false
  publish_authority: false
  release_authority: false
  stable_replacement_authority: true
  stable_replacement_completed: true
  delivery_state_transition_recorded: false
```

## 结论

本地 closeout 已升为 `ready`。这个结论只覆盖当前脏工作区中的 ColaMeta 私人 app
Work Item Gate review 实现及其本地验收证据，不是 Git 交付、发布、stable replacement
或生产变更授权。

当前仓库未启用本地 Work Item governance ledger，`gate_review_request/inspect` 返回
`candidate_count=0`。因此这份 closeout 记录的是“实现与私人 app 验收 ready”，没有伪造
Work Item、ReviewDecision、GateEvent 或 Delivery State 迁移。

## 验收范围

- 继续保持 Commander 私人 app 恰好 7 个暴露工具；Gate review 复用
  `run_mcp_workflow`，不新增第 8 个工具。
- `gate_review_request` 复用现有 Work Item Gate 后端执行
  `inspect -> preview -> apply -> status`。
- service mode 下可以先发现脱敏 Work Item 候选，再生成带精确版本绑定的签名 preview。
- private external OAuth apply 只对配置匹配的 Operator subject/client、具备
  Work Item authority claims 和 `mcp:commit` 的调用方开放。
- 通用 external OAuth commit 仍保持拒绝。
- `transition_rejected` 和 `shadow_evaluated` 不再报告为成功推进。
- Gate binding ID 和最终 preview 响应受明确大小合约约束；超限请求明确失败，不返回被摘要或
  截断的签名 apply 调用。

## 验证证据

```yaml id="private-app-gate-review-validation-evidence"
validation_evidence:
  focused_gate_and_related_tests:
    result: pass
    summary: 54 passed
  bounded_payload_contract:
    result: pass
    binding_ids_per_field_max: 16
    binding_id_chars_max: 256
    copyable_apply_chars_max: 26000
    preview_workflow_chars_max: 56000
    boundary_apply_call_preserved_by_mcp_and_actions: true
    one_character_over_boundary_rejected: true
  commander_surface_readback:
    result: pass
    exposed_tool_count: 7
    exposed_tools:
      - list_registered_projects
      - get_apps_connector_smoke_packet
      - render_commander_app
      - analyze_project_state
      - run_mcp_workflow
      - manage_validation_run
      - manage_git
    gate_workflow_exposed_as_eighth_tool: false
    gate_review_entry: run_mcp_workflow
  live_private_app_connector_smoke:
    result: pass
    read_only: true
    side_effects: false
    observed_at_utc: 2026-07-20T21:21:34Z
    registered_project_visible: colameta-self-dev
    visible_tool_count: 7
    connector_runtime_aligned: true
    apps_connector_closeout_status: ready
    operator_closeout_status: connector_closeout_ready
    operator_decision: ready
    evidence_gap_count: 0
    evidence_basis: authorized Apps connector list_registered_projects and smoke_packet calls succeeded
    secrets_or_private_config_read: false
  live_gate_workflow_readback:
    result: pass
    read_only_call: gate_review_request/inspect
    status: succeeded
    read_only: true
    side_effects: false
    governance_enabled: false
    candidate_count: 0
    reason: exact stable runtime loaded the workflow; repository governance remains intentionally disabled
    stable_service_changed: true
    stable_target_commit: 2dc78955ac284c88d56feee71fa5ebbb02c5d8f8
  repository_gate_readback:
    result: pass
    read_only: true
    governance_enabled: false
    work_item_candidate_count: 0
    delivery_state_write_attempted: false
  loopback_service_mode_private_oauth_e2e:
    result: pass
    transport: 127.0.0.1 HTTP
    authentication: offline-generated RS256 token validated through JWKS
    negative_auth_check: missing Bearer returned HTTP 401
    positive_path: inspect -> select -> preview -> apply
    resulting_work_item_state: ready
  full_pytest:
    result: pass
    summary: 1837 passed, 2 skipped, 55 subtests passed
    duration_seconds: 284.25
    warnings: 3 pytest temporary-directory cleanup warnings
  self_hosting_smoke:
    result: pass
  frozen_toolchain:
    result: pass
    distribution_count: 50
    preimport_bytecode_count: 0
    exact_environment_root_verified: true
  ruff:
    result: pass
  git_diff_check:
    result: pass
```

## 本地候选绑定

以下 SHA-256 绑定当前未提交候选内容；任何后续修改都会使本 closeout 需要重验。

```yaml id="private-app-gate-review-local-candidate-binding"
candidate_files:
  - path: runner/mcp_gate_review_workflow.py
    sha256: facab2529e9865708bb9949649444e3daf51998cb88615e14adb2657659f09ee
  - path: runner/mcp_server.py
    sha256: 3f65e0c69d58d6516c39fb274db2309a019739d9792845a87f91f75ba2e6d96a
  - path: runner/core_orchestrator.py
    sha256: 2c18adf4f4643ab618cd0290b1ede1b53001ac7ebf330f2adbb9775cfc06653c
  - path: tests/test_mcp_gate_review_workflow.py
    sha256: 603c1355a4e9ee844d2edd8705636671ad4c201ae65256591f365b43a9fa4b0d
  - path: tests/test_mcp_runtime_observability.py
    sha256: 59a9bd641ba643ed28491d88912dffd39572b64ebf8ba790bc3a4cc7d998dceb
  - path: docs/USAGE.md
    sha256: a4c2dda6215d0028ecd315fde68d4a2fd0338d764829598af402445539dec2d7
  - path: docs/USAGE.zh-CN.md
    sha256: 25047d1a2c1ce474dc265f6df257f05bf176930454588a50575cfcc6974dcee3
```

## 已知边界

- 超出有界 payload 合约的 Gate 请求会明确拒绝；这是安全边界，不会降级为残缺响应。
- 外部 IdP 没有用于本地测试；E2E 使用离线生成的测试密钥和真实 RS256/JWKS 验签，
  不读取或保存真实凭据。
- 真实私人 App 连接器本身已经完成只读 smoke，且返回
  `connector_closeout_ready / ready`；该结论证明连接器、认证、项目路由和当前稳定运行时可达。
- Jenn 后续精确授权 stable target
  `2dc78955ac284c88d56feee71fa5ebbb02c5d8f8` 及两项服务重启。受保护的
  `/home/jenn/tools/colameta` stable runtime 已替换到该提交；真实私人 App 的
  `gate_review_request/inspect` 已从 `TOOL_POLICY_DENIED` 变为只读成功。
- 当前仓库 governance 仍为 disabled，候选为 0；因此在线 smoke 没有伪造 Work Item，
  也没有执行 Delivery State、ReviewDecision 或 GateEvent 写入。完整 preview/apply 正向路径由
  service-mode/private-OAuth loopback E2E 覆盖。

## 本次交付边界

- 不 push。
- 不创建或推送 tag。
- 不发布、不部署。
- 只替换并重启精确授权的 stable target；不授权再次替换其他提交。
- 不修改 tunnel、DNS、provider 或认证配置。
