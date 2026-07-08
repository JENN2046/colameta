# Connector / Remote Preflight Evidence: Tunnel Edge Fixed, Closeout Ready

## Summary

```yaml
date: 2026-07-09
observed_at_utc: 2026-07-08T21:15:34Z
project_head: ee462945061d7ed7a2c0a99ddc1a3cd701715016
stable_runtime_head: 4e139bbbe7126c571103819cfb531f12c2b40d1f
project_name: colameta-self-dev
public_base_url: https://colameta-mcp.skmt617.top
result: ready
closeout_ready: true
```

This receipt records the sanitized recovery evidence after the previous HTTP
530 preflight failure. It is evidence only. It does not authorize executor run,
route transition, delivery acceptance, release, package publish, or stable
replacement.

## Root Cause

The remote hostname DNS path had already been corrected to public Cloudflare
edge addresses, but Cloudflare still returned HTTP 530 / error 1033 because the
local `cloudflared` tunnel client was resolving Cloudflare tunnel edge hosts to
fake-IP addresses in `198.18.0.0/16`.

Sanitized cloudflared evidence before the fix:

```yaml
cloudflared_edge_resolution_before:
  region1.v2.argotunnel.com: 198.18.0.155
  region2.v2.argotunnel.com: 198.18.0.49
tunnel_symptom:
  cloudflare_http_status: 530
  cloudflare_error_code: 1033
  tunnel_client_error_class: edge_dial_timeout
```

The remote MCP origin was healthy locally throughout the failure:

```yaml
remote_origin:
  service: colameta-mcp-remote.service
  local_url: http://127.0.0.1:8767/healthz
  local_http_status: 200
  auth_mode: external-oauth
```

## DNS / Tunnel Edge Correction

DoH lookups pinned to public resolver IPs returned public Cloudflare tunnel
edge addresses:

```yaml
cloudflare_tunnel_edge_doh:
  srv_record: _v2-origintunneld._tcp.argotunnel.com
  targets:
    - region1.v2.argotunnel.com
    - region2.v2.argotunnel.com
  region1_public_answers:
    - 198.41.192.77
    - 198.41.192.107
    - 198.41.192.67
  region2_public_answers:
    - 198.41.200.53
    - 198.41.200.43
    - 198.41.200.13
```

A scoped `/etc/hosts` override was added for tunnel edge resolution:

```yaml
hosts_backup_before_edge_fix: /etc/hosts.colameta-backup-20260709T051325+0800
hosts_override:
  marker: "# BEGIN colameta cloudflared edge DNS override 2026-07-09"
  records:
    - "198.41.192.77 region1.v2.argotunnel.com"
    - "198.41.192.107 region1.v2.argotunnel.com"
    - "198.41.192.67 region1.v2.argotunnel.com"
    - "198.41.200.53 region2.v2.argotunnel.com"
    - "198.41.200.43 region2.v2.argotunnel.com"
    - "198.41.200.13 region2.v2.argotunnel.com"
```

The external OAuth issuer was also resolving to a fake-IP address locally:

```yaml
external_oauth_resolution_before:
  dev-2n3z8xing6eekyok.us.auth0.com: 198.18.0.75
external_oauth_public_answers:
  - 104.18.43.182
  - 172.64.144.74
```

A scoped `/etc/hosts` override was added for the Auth0 issuer:

```yaml
hosts_backup_before_auth0_fix: /etc/hosts.colameta-backup-20260709T051620+0800
hosts_override:
  marker: "# BEGIN colameta external oauth DNS override 2026-07-09"
  records:
    - "104.18.43.182 dev-2n3z8xing6eekyok.us.auth0.com"
    - "172.64.144.74 dev-2n3z8xing6eekyok.us.auth0.com"
```

No tunnel credentials, DNS provider credentials, proxy config values, tokens,
cookies, private browser state, provider auth, or raw provider responses were
read or recorded.

## Service Recovery

After applying the scoped DNS overrides, `cloudflared-colameta-mcp-prod.service`
was restarted and registered four public-edge tunnel connections.

```yaml
cloudflared_service:
  status: healthy
  main_pid: 1925180
  registered_connections:
    - edge_ip: 198.41.192.77
      location: lax10
      protocol: quic
    - edge_ip: 198.41.200.13
      location: lax01
      protocol: quic
    - edge_ip: 198.41.192.67
      location: lax11
      protocol: quic
    - edge_ip: 198.41.200.53
      location: lax01
      protocol: quic
```

The remote MCP origin was restarted to clear stale loaded code from the prior
process.

```yaml
remote_origin:
  service: colameta-mcp-remote.service
  status: healthy
  main_pid: 1929965
  local_mcp_url: http://127.0.0.1:8767/mcp
  public_base_url: https://colameta-mcp.skmt617.top
  auth_mode: external-oauth
```

## Remote HTTPS MCP Preflight

```yaml
command: /home/jenn/tools/colameta/.venv/bin/python /home/jenn/tools/colameta/scripts/remote_https_mcp_preflight.py https://colameta-mcp.skmt617.top
network_check: run
ok: true
failures: []
responses:
  healthz: 200
  mcp: 200
  protected_resource_metadata: 200
  authorization_server_metadata: 404
healthz_runtime:
  loaded_runtime_head: ee462945061d7ed7a2c0a99ddc1a3cd701715016
  runtime_project_checkout_head: ee462945061d7ed7a2c0a99ddc1a3cd701715016
  runtime_loaded_code_stale: false
  reload_needed_for_verification: false
  installed_package_verification_status: match
```

The authorization-server metadata URL on the MCP service itself returned 404,
which is acceptable for this external OAuth mode because the protected-resource
metadata lists the external Auth0 issuer.

## ChatGPT Apps Connector Smoke

External ChatGPT ColaMeta MCP connector smoke succeeded with sanitized
tunnel/control-plane evidence.

```yaml
tool_surface: ChatGPT ColaMeta MCP
tool: get_apps_connector_smoke_packet
ok: true
apps_connector_closeout:
  status: ready
apps_connector_reachability:
  status: proved_by_successful_apps_tool_call
connector_closeout_check:
  current_operator_closeout: connector_closeout_ready
  current_decision: ready
  current_evidence_gap_count: 0
  local_service_status: healthy
  external_connector_status: healthy
connector_runtime_health:
  overall_status: healthy
  reason_codes:
    - RUNTIME_LOADED_CODE_CURRENT
    - LOCAL_SERVICE_HEALTHY
    - WEB_ENDPOINT_DISABLED
    - MCP_ENDPOINT_HEALTHY
    - CLOUDFLARED_REGISTERED_PUBLIC_EDGE_CONNECTIONS
    - REMOTE_PREFLIGHT_READY
runtime:
  project_checkout_head: ee462945061d7ed7a2c0a99ddc1a3cd701715016
  loaded_runtime_head: ee462945061d7ed7a2c0a99ddc1a3cd701715016
  runtime_loaded_code_stale: false
  reload_needed_for_verification: false
```

## Decision

```yaml
operator_closeout_decision: ready
external_connector_closeout: ready
ready_after_tunnel_edge_fix: true
stable_replacement_hint:
  status: dev_ahead_stable
  stable_replacement_not_required: true
reason_codes:
  - CLOUDFLARED_REGISTERED_PUBLIC_EDGE_CONNECTIONS
  - REMOTE_PREFLIGHT_READY
  - CONNECTOR_SMOKE_READY
  - RUNTIME_LOADED_CODE_CURRENT
safe_next_actions:
  - Use this as sanitized closeout evidence for the external connector.
  - Keep batching stable replacement separately unless explicitly requested.
  - Replace temporary hosts overrides with durable DNS/proxy policy when available.
not_authorized_actions:
  - read_tokens_or_cookies
  - read_browser_login_state
  - read_provider_auth
  - publish_package
  - push_tag
  - release
  - stable_replacement_without_explicit_authorization
```

## Boundary

This closeout used only sanitized service status, HTTP status, DNS classification,
and ChatGPT Apps connector read-only tool results. It did not read tunnel
credential files, token values, cookie values, raw browser state, raw provider
configuration, or private runtime memory.
