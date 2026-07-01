# Stable Replacement Receipt: 04c0f91

```yaml
receipt_type: stable_replacement_receipt
recorded_at: 2026-07-01T20:47:20+08:00
project: colameta-self-dev
dev_repo: /home/jenn/src/colameta-dev
stable_runtime_dir: /home/jenn/tools/colameta
target_commit: 04c0f916ed30e8f779f79b424f3bf33002065674
target_short_commit: 04c0f91
authorization: "Commander authorized stable replacement to exact commit 04c0f916ed30e8f779f79b424f3bf33002065674"
delivery_state_transition: not_performed
route_transition: not_performed
executor_run: not_performed
```

## Summary

Stable service replacement was completed for exact commit
`04c0f916ed30e8f779f79b424f3bf33002065674`.

This receipt records replacement evidence only. It does not mark Delivery State
accepted, does not create a ReviewDecision, does not emit a GateEvent, and does
not authorize any further service replacement or route transition.

## Source And CI Evidence

```yaml
source_evidence:
  dev_head: 04c0f916ed30e8f779f79b424f3bf33002065674
  origin_main: 04c0f916ed30e8f779f79b424f3bf33002065674
  local_branch: main
  local_status: clean
  commit_subject: "docs(connector): record tunnel closeout receipt"
  ci:
    workflow: CI
    run_id: 28518141095
    status: completed
    conclusion: success
    url: https://github.com/JENN2046/colameta/actions/runs/28518141095
```

## Replacement Evidence

```yaml
replacement_evidence:
  previous_stable_head: 380a9e3fef5c31eddaef93be488ef387707bc700
  new_stable_head: 04c0f916ed30e8f779f79b424f3bf33002065674
  stable_origin_main: 04c0f916ed30e8f779f79b424f3bf33002065674
  package_reinstalled: true
  installed_distribution: colameta 0.1.2
  backup:
    path: /home/jenn/tools/colameta-stable-backups/stable-before-04c0f91-20260701T204224+0800.tar.gz
    sha256: 83b56b465da76ad5cf7e0fc63741f236fa1a661656979cb82f68131f0228306c
```

## Running Service Evidence

```yaml
running_service:
  pid: 2289740
  project_root: /home/jenn/src/colameta-dev
  web:
    url: http://127.0.0.1:8801
    healthz_status: healthy
  mcp:
    url: http://127.0.0.1:8766/mcp
    healthz_status: healthy
    auth_mode: none
  bind_scope: loopback
  command_observed: "/home/jenn/tools/colameta/.venv/bin/python /home/jenn/tools/colameta/.venv/bin/colameta serve /home/jenn/src/colameta-dev --web-host 127.0.0.1 --web-port 8801 --mcp-host 127.0.0.1 --mcp-port 8766 --auth-mode none"
```

## Smoke Evidence

```yaml
smoke:
  web_root_page: ok
  web_page_embeds_csrf: true
  web_page_embeds_web_read_auth: true
  web_api_healthz: ok
  web_api_status_with_page_headers: ok
  web_api_version_result_with_page_headers: ok
  web_api_next_plan_with_page_headers: ok
  web_api_v2_health: ok
  mcp_healthz: ok
  mcp_initialize: ok
  mcp_tools_list: ok
  required_tools_present:
    - get_agent_consumer_contract
    - get_service_entry_profile
    - get_web_gpt_service_entrypoint
    - get_stable_promotion_readiness
    - get_runtime_version_status
    - get_connector_runtime_health_status
    - run_mcp_workflow
  service_entry_profiles_ok:
    - web_gpt_commander
    - local_codex_commander
    - planner_agent
    - reviewer_agent
    - source_observer
```

## Runtime Provenance Evidence

```yaml
runtime_provenance:
  project_checkout_head: 04c0f916ed30e8f779f79b424f3bf33002065674
  runtime_loaded_code_stale: false
  reload_needed_for_verification: false
  reload_awareness_reason: installed_package_matches_project_checkout
```

## Connector Runtime Health Evidence

```yaml
connector_runtime_health:
  tool_visible_on_stable_mcp: true
  read_only: true
  side_effects: false
  unsafe_extra_evidence_field_rejected: true
  unsafe_raw_value_echoed: false
  external_connector_status_without_evidence: unverified
  evidence_gap_components:
    - tunnel_client
    - tunnel_control_plane
```

## Remaining Caveats

```yaml
remaining_caveats:
  connector_runtime_local_service_probe:
    status: local_service_attention_needed
    observed_local_service_status: degraded
    contradictory_evidence:
      cli_status_local_service: healthy
      web_api_healthz: healthy
      mcp_healthz: healthy
      runtime_provenance: current
    suspected_cause: connector health tool probes Web health at /healthz instead of /api/healthz
    next_action: fix local_service probe path and redeploy after CI success and Commander authorization
  external_connector:
    status: unverified
    tunnel_client_status: unverified
    tunnel_control_plane_status: unverified
```

This receipt is intentionally not a connector/tunnel closeout-ready receipt.
External tunnel-client and control-plane evidence still require sanitized status
from approved status surfaces.
