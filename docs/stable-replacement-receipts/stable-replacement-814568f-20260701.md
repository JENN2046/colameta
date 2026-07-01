# Stable Replacement Receipt - 814568f

Date: 2026-07-01

Status: `completed`

This receipt records the authorized stable service replacement to:

```text
814568f268551963c34c874443680d9deec68027
```

It is evidence only. It does not create ReviewDecision, GateEvent, Delivery
State accepted, release, deploy, package publish, or executor run authority.

## Authorization

Jenn authorized the exact replacement target:

```text
授权替换稳定服务到 814568f268551963c34c874443680d9deec68027
```

## Candidate And CI

```yaml
candidate_commit: 814568f268551963c34c874443680d9deec68027
candidate_short: 814568f
origin_main_at_replacement: 814568f268551963c34c874443680d9deec68027
ci:
  name: CI
  status: completed
  conclusion: success
  run_id: 28524703981
  url: https://github.com/JENN2046/colameta/actions/runs/28524703981
```

## Backup

```yaml
backup_path: /home/jenn/tools/colameta-stable-backups/stable-before-814568f-20260701T222831+0800.tar.gz
backup_sha256: ea2f5c3a3749165731337798665f456db20d32c30dd5009ed0d2a387bcdeda75
previous_stable_head: 5403363e4ca62d896c7db1815c842bb3993a5923
```

## Replacement Actions

```yaml
stable_runtime_dir: /home/jenn/tools/colameta
stable_head_after_checkout: 814568f268551963c34c874443680d9deec68027
package_reinstall:
  command: python -m pip install --no-deps --force-reinstall /home/jenn/tools/colameta
  result: success
service_restart:
  previous_pid: 2299609
  new_pid: 2320578
  command: "/home/jenn/tools/colameta/.venv/bin/python /home/jenn/tools/colameta/.venv/bin/colameta serve /home/jenn/src/colameta-dev --web-host 127.0.0.1 --web-port 8801 --mcp-host 127.0.0.1 --mcp-port 8766 --auth-mode none"
  detached: true
  python_start_new_session: true
```

No `PYTHONPATH` override was used.

## Web And MCP Smoke

```yaml
web:
  url: http://127.0.0.1:8801
  healthz: ok
  page_ok: true
  csrf_meta_present: true
  web_read_auth_meta_present: true
  read_apis_with_page_headers:
    /api/status: ok
    /api/version-result: ok
    /api/next-plan: ok
    /api/v2/health: ok
mcp:
  url: http://127.0.0.1:8766/mcp
  healthz: ok
  initialize: ok
  tools_list: ok
  required_tools_visible:
    - list_registered_projects
    - get_agent_consumer_contract
    - get_service_entry_profile
    - get_web_gpt_service_entrypoint
    - get_runtime_version_status
    - get_connector_runtime_health_status
    - run_mcp_workflow
    - manage_validation_run
```

## Runtime Provenance

```yaml
get_runtime_version_status:
  ok: true
  runtime_loaded_code_stale: false
  reload_needed_for_verification: false
  reload_awareness_reason: installed_package_matches_project_checkout
  embedded_local_service: healthy
  embedded_closeout_without_external_evidence: local_runtime_ready_external_connector_unverified
```

## Connector Closeout

Sanitized external evidence was collected through:

```text
tunnel-client health --port 8080 --pid 4034 --json
```

Only safe summary fields were used:

```yaml
observed_at: 2026-07-01T14:32:38.148649Z
exit_code: 0
tunnel_client:
  status: healthy
  reason_code: TUNNEL_CLIENT_HEALTHZ_READY
  healthz_ok: true
  healthz_status: 200
control_plane:
  status: healthy
  reason_code: TUNNEL_CONTROL_PLANE_READYZ_READY
  readyz_ok: true
  readyz_status: 200
```

Stable MCP closeout with sanitized evidence:

```yaml
get_connector_runtime_health_status:
  ok: true
  local_service: healthy
  external_connector: healthy
  tunnel_client: healthy
  control_plane: healthy
  operator_closeout: connector_closeout_ready
  decision: ready
  evidence_gap_count: 0
```

No tunnel-client config, proxy config, runtime key, token, cookie, credential,
provider raw response, or log raw content was read or copied.

## Thin Preview Smoke

```yaml
run_mcp_workflow:
  workflow: thin_governed_loop_preview
  input_mode: draft
  ok: true
  read_only: true
  generated_input_bundle: present
  next_request_payload: present
  forbidden_authority_outputs:
    delivery_state_accepted: false
    review_decision_created: false
    gate_event_emitted: false
    executor_dispatch_authorized: false
```

## Not Performed

```text
executor run
route transition
ReviewDecision creation
GateEvent emission
Delivery State accepted
release
deploy
package publish
provider/proxy/tunnel config mutation
secret/token/cookie/credential read
```

## Notes

The stable runtime now serves the authorized candidate commit. This receipt is a
post-replacement documentation record and may be committed after the replacement
without changing runtime source files.
