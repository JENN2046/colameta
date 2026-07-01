# Stable Replacement Receipt: 80d849b

```yaml
receipt_type: stable_replacement_receipt
recorded_at: 2026-07-01T19:42:46+08:00
project: colameta-self-dev
dev_repo: /home/jenn/src/colameta-dev
stable_runtime_dir: /home/jenn/tools/colameta
target_commit: 80d849b93ec7adb8b4e351060049e4a2174f0869
target_short_commit: 80d849b
authorization: "Commander authorized stable replacement to exact commit 80d849b93ec7adb8b4e351060049e4a2174f0869"
delivery_state_transition: not_performed
route_transition: not_performed
executor_run: not_performed
```

## Summary

Stable service replacement was completed for exact commit
`80d849b93ec7adb8b4e351060049e4a2174f0869`.

This receipt records replacement evidence only. It does not mark Delivery State
accepted, does not create a ReviewDecision, does not emit a GateEvent, and does
not authorize any further service replacement or route transition.

## Source And CI Evidence

```yaml
source_evidence:
  dev_head: 80d849b93ec7adb8b4e351060049e4a2174f0869
  origin_main: 80d849b93ec7adb8b4e351060049e4a2174f0869
  local_ahead_behind_origin_main: "0 0"
  commit_subject: "fix(ux): align health and draft goal handling"
  ci:
    workflow: CI
    run_id: 28494429048
    status: completed
    conclusion: success
    url: https://github.com/JENN2046/colameta/actions/runs/28494429048
```

## Replacement Evidence

```yaml
replacement_evidence:
  previous_stable_head: 8367a7d39cef0c70237625c4e50f0d6127cde3a6
  new_stable_head: 80d849b93ec7adb8b4e351060049e4a2174f0869
  stable_origin_main: 80d849b93ec7adb8b4e351060049e4a2174f0869
  package_reinstalled: true
  installed_distribution: colameta 0.1.2
  backup:
    path: /home/jenn/tools/colameta-stable-backups/stable-before-80d849b-20260701T132811+0800.tar.gz
    sha256: 6c1392b7a9e119bf1756f111d2b000b80a38bbfba6412cf2d89be61e43396eca
```

## Running Service Evidence

```yaml
running_service:
  pid: 2233650
  project_root: /home/jenn/src/colameta-dev
  web:
    url: http://127.0.0.1:8801
    status: healthy
  mcp:
    url: http://127.0.0.1:8766/mcp
    status: healthy
    auth_mode: none
  bind_scope: loopback
  log_path: /home/jenn/.config/colameta/runtime/service/service.log
  command_observed: "/home/jenn/tools/colameta/.venv/bin/python /home/jenn/tools/colameta/.venv/lib/python3.12/site-packages/scripts/runner_cli.py serve /home/jenn/src/colameta-dev --web-host 127.0.0.1 --web-port 8801 --mcp-host 127.0.0.1 --mcp-port 8766 --auth-mode none --service-child"
```

## Smoke Evidence

```yaml
smoke:
  web_healthz: ok
  web_root_page: ok
  web_api_status: ok
  web_api_version_result: ok
  mcp_healthz: ok
  mcp_initialize: ok
  mcp_tools_list: ok
  required_tools_present:
    - get_agent_consumer_contract
    - get_service_entry_profile
    - get_web_gpt_service_entrypoint
    - get_stable_promotion_readiness
    - get_runtime_version_status
    - run_mcp_workflow
```

## UX Fix Verification

```yaml
ux_fix_verification:
  web_status_connector_runtime_health_visible: true
  real_pid_port_health_visible:
    pid: 2233650
    web_port: 8801
    mcp_port: 8766
    health_source: process_table
    local_service_status: healthy
  draft_seed_goal:
    generated_input_bundle_contains_goal: true
    next_request_payload_contains_goal: true
```

## Runtime Provenance Evidence

```yaml
runtime_provenance:
  stable_promotion_readiness_status: stable_promotion_review_candidate
  stable_production_ready: false
  loaded_source_root: /home/jenn/tools/colameta/.venv/lib/python3.12/site-packages
  project_checkout_head: 80d849b93ec7adb8b4e351060049e4a2174f0869
  runtime_loaded_code_stale: false
  reload_needed_for_verification: false
  reload_awareness_reason: installed_package_matches_project_checkout
```

## Remaining Caveats

```yaml
remaining_caveats:
  external_connector_status: unverified
  tunnel_client_status: unverified
  tunnel_control_plane_status: unverified
  reason_codes:
    - RUNTIME_HEALTH_UNVERIFIED
    - LOCAL_SERVICE_HEALTHY
    - WEB_ENDPOINT_HEALTHY
    - MCP_ENDPOINT_HEALTHY
    - CONNECTOR_HEALTH_UNVERIFIED
    - TUNNEL_CONTROL_PLANE_UNVERIFIED
  stable_readiness_external_required_before_replacement:
    - PROMOTION_ARTIFACT_MANIFEST_NOT_PERSISTED
    - ROLLBACK_REHEARSAL_NOT_PROVEN
    - COMMANDER_STABLE_REPLACEMENT_AUTHORIZATION_ABSENT
```

The remaining connector/tunnel caveat is the recommended next optimization
preview topic: `stable connector/tunnel verification closeout`.

## Next Controlled Preview Evidence

```yaml
next_controlled_preview:
  service_used: stable_mcp
  mcp_url: http://127.0.0.1:8766/mcp
  tool: run_mcp_workflow
  workflow: thin_governed_loop_preview
  phase: preview
  project_name: colameta-self-dev
  input_mode: draft
  status: succeeded
  risk_level: info
  blockers: []
  thin_loop_status: thin_governed_loop_input_draft_ready
  current_head: 80d849b93ec7adb8b4e351060049e4a2174f0869
  preview_goal: "stable connector/tunnel verification closeout: improve safe read-only evidence and operator closeout for the remaining external_connector=tunnel/control-plane unverified state while local Web/MCP is healthy; do not read secrets or mutate network/provider/service state."
  draft_seed_applied:
    - allowed_files
    - forbidden_files
    - goal
    - reviewer_notes
  draft_seed_ignored: []
  draft_seed_unknown: []
  generated_input_bundle_sha256: d8ca52e99b5160641828c6e8b308aa05ff257149b17e47dab70456f96613da13
  next_request_payload_sha256: 80404dd8e77b1558f2195dcb72c928361b36bf1714cdaffefd8c7ce5795a2d16
  generated_bundle_contains_goal: true
  next_request_payload_contains_goal: true
  warning: "thin_governed_loop_preview is read-only evidence; it does not authorize executor dispatch, ReviewDecision, GateEvent, Delivery State transition, commit, or push."
```

Preview allowed files:

```yaml
allowed_files:
  - runner/runtime_observability.py
  - runner/web_console.py
  - scripts/runner_cli.py
  - runner/mcp_server.py
  - tests/test_mcp_runtime_observability.py
  - tests/test_web_console_security.py
  - tests/test_runner_cli.py
  - docs/connector-runtime-health-observability.md
```

Preview forbidden files:

```yaml
forbidden_files:
  - .env
  - .env.*
  - "**/.env"
  - /home/jenn/tools/tunnel-client/**
  - /home/jenn/tools/colameta/**
  - ~/.codex/**
  - ~/.config/tunnel-client/**
  - "**/*secret*"
  - "**/*token*"
  - "**/*credential*"
  - .colameta/state.json
  - .colameta/plan.json
  - .colameta/decisions.json
  - .colameta/memory.md
  - .colameta/todolist.json
```
