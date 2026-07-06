# Beta Gate Receipt Template

复制本模板时只填写脱敏证据。禁止粘贴 token、cookie、client secret、`.env`
值、provider raw response、raw log、browser login state、tunnel config 或
proxy/provider config。

```yaml
receipt_type: beta_gate_receipt
recorded_at_utc: <iso8601>
project_name: colameta-self-dev
candidate_head: <40-char-sha>
stable_runtime_head: <40-char-sha>
main_ci:
  run_id: <github-actions-run-id>
  status: completed
  conclusion: success
ops_check:
  status: ready
  ops_check_ready: true
  connector_smoke_ready: true
  beta_gate_ready: true
  reason_codes: []
remote_https_mcp_preflight:
  public_base_url: https://colameta-mcp.skmt617.top
  ok: true
  failures: []
chatgpt_connector_smoke:
  status: ready
  evidence_source: get_apps_connector_smoke_packet with sanitized tunnel/control-plane evidence
  last_observed_at: <iso8601>
backup:
  backup_file: /home/jenn/tools/colameta-stable-backups/stable-before-<short>-<timestamp>.tar.gz
  backup_sha256: <sha256>
rollback_rehearsal:
  status: ready
  target_commit_resolved: true
  archive_listable: true
  rehearsal_executed_restore: false
boundary:
  tokens_or_cookies_read: false
  env_values_read: false
  raw_logs_read: false
  provider_api_called: false
  stable_replacement_performed: false
  rollback_or_restore_performed: false
  release_or_deploy_performed: false
  tag_or_package_publish_performed: false
```

## 结论

```text
ops_check_ready: <true|false>
connector_smoke_ready: <true|false>
beta_gate_ready: <true|false>
status_label_change_authorized: false
```

本 receipt 不授权 Beta classifier 修改、stable replacement、release、deploy、
tag push、package publish、executor run、ReviewDecision、GateEvent 或 Delivery
accepted。
