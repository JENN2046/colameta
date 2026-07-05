---
receipt_type: stable_aligned_apps_connector_smoke_receipt
receipt_id: stable_aligned_apps_connector_smoke_3b4dbbd_20260706
recorded_at_utc: 2026-07-05T17:00:21Z
project_name: colameta-self-dev
project_root: /home/jenn/src/colameta-dev
observed_dev_head: 3b4dbbda9ef8689b08e3f37e049798cdf5d97e38
observed_stable_head: 3b4dbbda9ef8689b08e3f37e049798cdf5d97e38
result: pass
---

# Stable-Aligned Apps Connector Smoke Receipt: 3b4dbbd

## Scope

This receipt records the sanitized closeout evidence after stable runtime was
aligned to `3b4dbbd` and `get_apps_connector_smoke_packet` was called with fresh
tunnel/client and control-plane evidence.

It does not include token values, cookies, client secrets, credential contents,
browser login state, tunnel config, proxy config, provider raw responses, raw
logs, or `.env` values.

## Observed Runtime State

```yaml
project_name: colameta-self-dev
observed_dev_head: 3b4dbbda9ef8689b08e3f37e049798cdf5d97e38
observed_stable_runtime_head: 3b4dbbda9ef8689b08e3f37e049798cdf5d97e38
readiness_status: stable_promotion_review_candidate
stable_promotion_review_candidate: true
runtime_loaded_code_stale: false
reload_needed_for_verification: false
stable_replacement_hint.status: stable_aligned
stable_replacement_not_required: true
```

## Sanitized Evidence Supplied

```yaml
tunnel_client:
  status: healthy
  reason_code: CLOUDFLARED_SYSTEMD_RUNNING
  evidence_source: "systemctl --user show cloudflared-colameta-mcp-prod.service ActiveState/SubState/MainPID; service active/running; no token/cookie/config/log read"
  last_observed_at: 2026-07-05T17:00:21Z

control_plane:
  status: healthy
  reason_code: CLOUDFLARE_TUNNEL_PUBLIC_PREFLIGHT_READY
  evidence_source: "remote_https_mcp_preflight https://colameta-mcp.skmt617.top ok=true failures=[]; external-oauth protected-resource route reachable"
  last_observed_at: 2026-07-05T17:00:21Z
```

## Apps Connector Smoke Result

```yaml
apps_connector_closeout.status: ready
connector_runtime_health.overall_status: healthy
operator_closeout.status: connector_closeout_ready
operator_closeout.decision: ready
evidence_gap_count: 0
external_connector.status: healthy
runtime.status: healthy
local_service.status: healthy
web.status: healthy
mcp.status: healthy
stable_replacement_hint.status: stable_aligned
```

## Safety Boundary

```yaml
read_tokens_or_cookies: false
read_client_secret: false
read_env_values: false
read_browser_login_state: false
read_tunnel_config: false
read_proxy_config: false
read_raw_provider_response: false
read_raw_logs: false
restart_tunnel_client: false
modify_proxy_or_auth_config: false
executor_run: false
route_transition: false
delivery_state_accepted: false
review_decision_created: false
gate_event_emitted: false
```

## Receipt Note

This receipt is a documentation artifact written after the observed smoke. If it
is committed, the dev branch HEAD will advance beyond the observed
`3b4dbbd`; that does not change the recorded smoke result for the observed
stable-aligned runtime.
