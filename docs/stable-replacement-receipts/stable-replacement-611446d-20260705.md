# Stable Replacement Receipt: 611446d

date: 2026-07-05
operator: Codex
authorized_by: Jenn
authorization: "授权替换稳定服务到 611446d5b633e423eb2dcc62d944a264ec7f5775"

## Target

```text
target_commit: 611446d5b633e423eb2dcc62d944a264ec7f5775
target_subject: Add role-aware agent flow packet
previous_stable_commit: 189bdeed6b9b1d060674032cb1e67f995cc9e282
dev_repo: /home/jenn/src/colameta-dev
stable_dir: /home/jenn/tools/colameta
stable_web: http://127.0.0.1:8801
stable_mcp: http://127.0.0.1:8766/mcp
auth_mode: none
```

## Preflight

```text
dev_HEAD: 611446d5b633e423eb2dcc62d944a264ec7f5775
origin_main: 611446d5b633e423eb2dcc62d944a264ec7f5775
ci_run: https://github.com/JENN2046/colameta/actions/runs/28734793784
ci_status: completed
ci_conclusion: success
stable_worktree_clean: true
```

Untracked prior receipt files were left uncommitted:

```text
docs/stable-replacement-receipts/stable-replacement-189bdee-20260703.md
docs/stable-replacement-receipts/stable-replacement-dd1b99f-20260703.md
```

## Backup

```text
backup_file: /home/jenn/tools/colameta-stable-backups/stable-before-611446d-20260705T164057+0800.tar.gz
backup_sha256: c49308cea1f742c5232c7db2476f8a481cc8afe83b1b57181557ace1902855c2
```

## Replacement

```text
stable_fetch: git -C /home/jenn/tools/colameta fetch origin
stable_checkout: git -C /home/jenn/tools/colameta checkout 611446d5b633e423eb2dcc62d944a264ec7f5775
package_reinstall: /home/jenn/tools/colameta/.venv/bin/python -m pip install --no-deps --force-reinstall /home/jenn/tools/colameta
service_unit: colameta-stable.service
service_pid: 1815304
service_log: /home/jenn/tools/colameta-stable-backups/stable-service-611446d-20260705T164210+0800.log
```

The first background launch attempt exited under the command runner. A direct
foreground launch verified the new code could serve Web/MCP, then the stable
service was started as a transient user systemd unit with the same
`colameta serve ... --auth-mode none` command.

## Verification

```text
web_healthz: ok
mcp_healthz: ok
mcp_initialize: ok
mcp_initialized_notification: 202_empty_body
mcp_tools_list_count: 44
has_get_agent_operator_flow_packet: true
has_get_apps_connector_smoke_packet: true
get_agent_operator_flow_packet:
  ok: true
  source: agent_operator_flow_packet
  primary_tool: run_mcp_workflow
  gate_level: read_only_workflow_packet
get_runtime_version_status:
  project_checkout_head: 611446d5b633e423eb2dcc62d944a264ec7f5775
  reload_needed_for_verification: false
  runtime_loaded_code_stale: false
colameta_status:
  PID: 1815304
  Web Console: healthy
  MCP Endpoint: healthy
  Stable cadence: stable_aligned
```

Web page smoke:

```text
/: contains "Web Commander 服务能力入口"
/api/v2/status: not validated without Web read token
reason: WEB_READ_AUTH_REQUIRED
boundary: web_read_token_not_read_or_extracted
```

Connector/App smoke:

```text
tunnel_client_health:
  command: tunnel-client health --port 8080 --pid 4034 --json
  healthz: ok
  readyz: ok
apps_connector_list_registered_projects:
  ok: true
  project_count: 5
  includes: colameta-self-dev
apps_connector_get_connector_runtime_health_status:
  overall_status: healthy
  runtime: healthy
  local_service: healthy
  external_connector: healthy
  operator_closeout: connector_closeout_ready
  decision: ready
  evidence_gap_count: 0
```

## Boundary

```text
did_not_read_tokens_or_cookies: true
did_not_read_tunnel_client_config: true
did_not_read_raw_tunnel_logs: true
did_not_modify_proxy_or_auth_config: true
did_not_restart_tunnel_client: true
did_not_write_delivery_accepted: true
did_not_create_review_decision: true
did_not_create_gate_event: true
```
