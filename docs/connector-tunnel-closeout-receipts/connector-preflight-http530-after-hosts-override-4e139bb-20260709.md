# Connector / Remote Preflight Evidence: DNS Fixed, Cloudflare 530

## Summary

```yaml
date: 2026-07-09
observed_at_utc: 2026-07-08T20:27:48Z
stable_runtime_head: 4e139bbbe7126c571103819cfb531f12c2b40d1f
project_name: colameta-self-dev
public_base_url: https://colameta-mcp.skmt617.top
result: degraded
closeout_ready: false
```

This receipt records a second sanitized connector/preflight attempt after
correcting the local DNS path away from fake-IP responses. It is evidence only.
It does not authorize tunnel, DNS, provider, Auth0, proxy, service, executor,
Git, release, or deployment mutation.

## DNS / Proxy Path Correction

Before correction, the WSL resolver returned fake-IP responses in
`198.18.0.0/16`, including:

```yaml
colameta-mcp.skmt617.top: 198.18.0.218
cloudflare.com: 198.18.0.22
```

DoH queries pinned to public resolver IPs returned public Cloudflare A records:

```yaml
cloudflare_doh:
  resolver: cloudflare-dns.com via 1.1.1.1
  answers:
    - 104.21.42.91
    - 172.67.160.117
google_doh:
  resolver: dns.google via 8.8.8.8
  answers:
    - 172.67.160.117
    - 104.21.42.91
```

A scoped `/etc/hosts` override was added:

```yaml
hosts_backup: /etc/hosts.colameta-backup-20260709T042724+0800
hosts_override:
  marker: "# BEGIN colameta-mcp public DNS override 2026-07-09"
  records:
    - "104.21.42.91 colameta-mcp.skmt617.top"
    - "172.67.160.117 colameta-mcp.skmt617.top"
```

After correction, normal resolver APIs returned public/global addresses:

```yaml
resolved_addresses:
  - address: 104.21.42.91
    is_global: true
    is_private: false
    is_loopback: false
    is_link_local: false
    is_multicast: false
  - address: 172.67.160.117
    is_global: true
    is_private: false
    is_loopback: false
    is_link_local: false
    is_multicast: false
proxy_env:
  observed_proxy_variables: []
  values_printed: false
```

No proxy values, DNS provider credentials, tunnel config, provider config,
tokens, cookies, raw logs, or raw provider responses were read.

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
cloudflared_service:
  status: healthy
  reason_code: SYSTEMD_SERVICE_RUNNING
  main_pid: 2099487
  active_state: active
  sub_state: running
```

## Remote HTTPS MCP Preflight

After the DNS override, the preflight was no longer blocked by
`PUBLIC_BASE_URL_REJECTED`. It reached Cloudflare public edge addresses, but the
remote service returned HTTP 530 Cloudflare error metadata for all checked MCP
and OAuth endpoints.

```yaml
command: /home/jenn/tools/colameta/.venv/bin/python /home/jenn/tools/colameta/scripts/remote_https_mcp_preflight.py https://colameta-mcp.skmt617.top
network_check: run
ok: false
remote_http_statuses:
  healthz: 530
  mcp: 530
  protected_resource_metadata: 530
  authorization_server_metadata: 530
healthz_runtime:
  runtime_project_checkout_head: null
  runtime_loaded_code_stale: null
  reload_needed_for_verification: null
reason_code: REMOTE_PREFLIGHT_FAILED_HTTP_530
```

`ops-check` with `--expected-head 4e139bbbe7126c571103819cfb531f12c2b40d1f`
reported:

```yaml
overall_status: blocked
stable_runtime: ready
stable_service: ready
local_stable_health: ready
cloudflared_service: ready
backup_inventory: ready
rollback_rehearsal: ready
remote_https_mcp_preflight:
  status: blocked
  reason_code: REMOTE_PREFLIGHT_FAILED
connector_smoke:
  status: needs_attention
  reason_code: CONNECTOR_SMOKE_MISSING
secret_redaction:
  status: blocked
  reason_code: SECRET_LIKE_CONTENT_DETECTED
  finding_path: checks.remote_https_mcp_preflight.failures[10]
```

The secret-redaction finding came from preflight failure text that mentions
bearer-token support in metadata requirements. No secret value was printed or
recorded.

## Connector Tool Evidence

Local ColaMeta closeout with sanitized evidence:

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
    reason_code: REMOTE_PREFLIGHT_FAILED_HTTP_530
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

## Decision

```yaml
operator_closeout_decision: blocked
ready_for_beta_gate: false
ready_after_dns_fix: false
reason_codes:
  - REMOTE_PREFLIGHT_FAILED_HTTP_530
  - CONNECTOR_SMOKE_MISSING
  - EXTERNAL_CONNECTOR_TOOL_INTERNAL_ERROR
safe_next_actions:
  - Treat local stable runtime/Web/MCP as healthy.
  - Treat DNS/proxy fake-IP problem as locally corrected for this host override.
  - Investigate Cloudflare tunnel/control-plane health through approved sanitized status surfaces.
  - Do not mark connector closeout ready until remote preflight returns HTTP 200 readiness metadata and ChatGPT Apps connector smoke succeeds.
not_authorized_actions:
  - read_tokens_or_cookies
  - read_tunnel_client_config
  - read_proxy_config_values
  - read_provider_auth
  - read_raw_logs
  - modify_cloudflare_or_auth0_config
  - restart_tunnel_client
  - route_transition
  - executor_run
  - delivery_state_acceptance
```

## Boundary

This receipt records degraded-state evidence after a scoped local hosts
override. It does not close the external connector, does not mark Beta Gate
ready, and does not authorize any further mutation.
