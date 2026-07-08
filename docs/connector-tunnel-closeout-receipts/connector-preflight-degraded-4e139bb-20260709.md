# Connector / Remote Preflight Evidence: 4e139bb Degraded

## Summary

```yaml
date: 2026-07-09
observed_at_utc: 2026-07-08T20:10:35Z
stable_runtime_head: 4e139bbbe7126c571103819cfb531f12c2b40d1f
stable_service_unit: colameta-stable.service
project_name: colameta-self-dev
public_base_url: https://colameta-mcp.skmt617.top
result: degraded
closeout_ready: false
```

This receipt records a fresh sanitized connector/preflight attempt after stable
replacement to `4e139bb`. It is evidence only. It does not authorize DNS,
tunnel, provider, Auth0, proxy, service, executor, Git, release, or deployment
mutation.

## Local Stable Evidence

```yaml
stable_service:
  status: healthy
  pid: 1673119
  web:
    url: http://127.0.0.1:8801
    state: healthy
  mcp:
    url: http://127.0.0.1:8766/mcp
    state: healthy
runtime:
  runtime_loaded_code_stale: false
  reload_needed_for_verification: false
  reload_awareness_reason: installed_package_matches_project_checkout
  installed_package_verification_status: match
```

## Current DNS / Proxy Environment

```yaml
proxy_env:
  observed_proxy_variables: []
  values_printed: false
dns_resolution:
  host: colameta-mcp.skmt617.top
  address: 198.18.0.218
  is_global: false
  is_private: true
  is_loopback: false
  is_link_local: false
  is_multicast: false
```

No proxy variable values, tunnel config, provider config, tokens, cookies, raw
logs, or raw provider responses were read.

## Tunnel Client Evidence

```yaml
tunnel_client:
  status: healthy
  reason_code: SYSTEMD_SERVICE_RUNNING
  evidence_source: "systemctl --user show cloudflared-colameta-mcp-prod.service ActiveState/SubState/MainPID; active/running; no config/log/token read"
  main_pid: 2099487
  active_state: active
  sub_state: running
  last_observed_at: 2026-07-08T20:09:34Z
```

## Remote HTTPS MCP Preflight

```yaml
command: /home/jenn/tools/colameta/.venv/bin/python /home/jenn/tools/colameta/scripts/remote_https_mcp_preflight.py https://colameta-mcp.skmt617.top
ok: false
failure: remote MCP public_base_url must not use localhost, loopback, private, link-local, multicast, local-only DNS, or otherwise non-public/non-unicast hosts.
ops_check:
  status: blocked
  remote_https_mcp_preflight:
    status: blocked
    reason_code: PUBLIC_BASE_URL_REJECTED
    redacted: true
  stable_runtime: ready
  stable_service: ready
  local_stable_health: ready
  cloudflared_service: ready
  backup_inventory: ready
  rollback_rehearsal: ready
  connector_smoke: needs_attention
  connector_smoke_reason: CONNECTOR_SMOKE_MISSING
```

The public endpoint guard rejected the current resolver result before network
preflight. This is the expected fail-closed behavior for non-public/non-unicast
address evidence.

## Connector Tool Evidence

Local ColaMeta read-only closeout with sanitized evidence:

```yaml
tool: get_connector_runtime_health_status
surface: local
overall_status: local_runtime_observed_external_connector_degraded
operator_closeout:
  status: external_connector_attention_needed
  decision: blocked
  evidence_gap_count: 0
external_connector:
  status: degraded
  tunnel_client:
    status: healthy
    reason_code: SYSTEMD_SERVICE_RUNNING
  control_plane:
    status: degraded
    reason_code: PUBLIC_BASE_URL_REJECTED
```

External ChatGPT ColaMeta MCP connector attempts:

```yaml
surface: ChatGPT ColaMeta MCP
get_connector_runtime_health_status:
  result: error
  error_class: mcp_internal_error
  code: -32603
get_apps_connector_smoke_packet:
  result: error
  error_class: mcp_internal_error
  code: -32603
```

The external connector did not produce a successful smoke packet in this run.
No token-expired detail, secret value, cookie, browser login state, raw tunnel
configuration, raw provider response, or raw log content was read or recorded.

## Decision

```yaml
operator_closeout_decision: blocked
ready_for_beta_gate: false
reason_codes:
  - PUBLIC_BASE_URL_REJECTED
  - CONNECTOR_SMOKE_MISSING
  - EXTERNAL_CONNECTOR_TOOL_INTERNAL_ERROR
safe_next_actions:
  - Fix or bypass the current DNS/proxy path so colameta-mcp.skmt617.top resolves to a public, globally routable address.
  - Rerun remote_https_mcp_preflight after DNS/proxy evidence is public.
  - Rerun ChatGPT Apps connector smoke after public preflight is ready.
not_authorized_actions:
  - read_tokens_or_cookies
  - read_tunnel_client_config
  - read_proxy_config_values
  - read_provider_auth
  - read_raw_logs
  - modify_dns_or_tunnel
  - restart_tunnel_client
  - route_transition
  - executor_run
  - delivery_state_acceptance
```

## Boundary

This receipt is a degraded-state evidence record. It does not close the external
connector, does not mark Beta Gate ready, and does not authorize any mutation.
