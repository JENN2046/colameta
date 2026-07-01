# Stable Replacement Receipt: 5403363

```yaml
receipt_type: stable_replacement_receipt
recorded_at: 2026-07-01T21:02:34+08:00
project: colameta-self-dev
dev_repo: /home/jenn/src/colameta-dev
stable_runtime_dir: /home/jenn/tools/colameta
target_commit: 5403363e4ca62d896c7db1815c842bb3993a5923
target_short_commit: 5403363
authorization: "Commander authorized stable replacement to exact commit 5403363e4ca62d896c7db1815c842bb3993a5923"
delivery_state_transition: not_performed
route_transition: not_performed
executor_run: not_performed
```

## Summary

Stable service replacement was completed for exact commit
`5403363e4ca62d896c7db1815c842bb3993a5923`.

This receipt records replacement evidence only. It does not mark Delivery State
accepted, does not create a ReviewDecision, does not emit a GateEvent, and does
not authorize any further service replacement or route transition.

## Source And CI Evidence

```yaml
source_evidence:
  dev_head: 5403363e4ca62d896c7db1815c842bb3993a5923
  origin_main: 5403363e4ca62d896c7db1815c842bb3993a5923
  local_branch: main
  local_status: clean
  commit_subject: "fix(connector): probe web api healthz"
  ci:
    workflow: CI
    run_id: 28518821557
    status: completed
    conclusion: success
    url: https://github.com/JENN2046/colameta/actions/runs/28518821557
```

## Replacement Evidence

```yaml
replacement_evidence:
  previous_stable_head: 04c0f916ed30e8f779f79b424f3bf33002065674
  new_stable_head: 5403363e4ca62d896c7db1815c842bb3993a5923
  stable_origin_main: 5403363e4ca62d896c7db1815c842bb3993a5923
  package_reinstalled: true
  installed_distribution: colameta 0.1.2
  backup:
    path: /home/jenn/tools/colameta-stable-backups/stable-before-5403363-20260701T205602+0800.tar.gz
    sha256: e76c46ba8abcf1eea3a13c0d17e8de70b894f88f32a9dc67fa923473d500c148
```

## Running Service Evidence

```yaml
running_service:
  pid: 2299609
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
```

## Runtime And Connector Evidence

```yaml
runtime_provenance:
  project_checkout_head: 5403363e4ca62d896c7db1815c842bb3993a5923
  runtime_loaded_code_stale: false
  reload_needed_for_verification: false
  reload_awareness_reason: installed_package_matches_project_checkout
connector_runtime_health_without_external_evidence:
  local_service_status: healthy
  external_connector_status: unverified
  operator_closeout_status: local_runtime_ready_external_connector_unverified
  decision: blocked
  evidence_gap_components:
    - tunnel_client
    - tunnel_control_plane
connector_runtime_health_probe_fix:
  web_probe_path: /api/healthz
  local_service_status_after_fix: healthy
```

## Remaining Caveats

```yaml
remaining_caveats:
  external_connector_status_without_evidence: unverified
  tunnel_client_status_without_evidence: unverified
  tunnel_control_plane_status_without_evidence: unverified
  connector_closeout_update: docs/connector-tunnel-closeout-receipts/connector-tunnel-closeout-5403363-20260701.md
```

The replacement itself is complete. Connector/tunnel closeout depends on the
separate approved status evidence recorded in the connector closeout receipt.
