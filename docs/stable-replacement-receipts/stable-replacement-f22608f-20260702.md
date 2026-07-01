# Stable Replacement Receipt - f22608f

Date: 2026-07-02

Status: `completed`

This receipt records the authorized stable service replacement to:

```text
f22608fa98d8a6f92070cd9b21dcdf4210bb57e3
```

It is evidence only. It does not create ReviewDecision, GateEvent, Delivery
State accepted, release, deploy, package publish, route transition, executor-run
authority, or further stable replacement authority.

## Authorization

Jenn authorized the exact replacement target:

```text
授权替换稳定服务到 f22608f。
```

## Candidate And CI

```yaml
candidate_commit: f22608fa98d8a6f92070cd9b21dcdf4210bb57e3
candidate_short: f22608f
origin_main_at_replacement: f22608fa98d8a6f92070cd9b21dcdf4210bb57e3
local_branch: main
local_status_after_push: clean
ci:
  name: CI
  status: completed
  conclusion: success
  run_id: 28530280291
  url: https://github.com/JENN2046/colameta/actions/runs/28530280291
```

## Backup

```yaml
backup_path: /home/jenn/tools/colameta-stable-backups/stable-before-f22608f-20260702T000019+0800.tar.gz
backup_sha256: b8ad9a838bca55494d69acd4aa4ffcdf9df3d4f668228e89335a9d1b90737aea
previous_stable_head: a3a1bbca2394b71fef1f8255c186b02a3d32eab3
```

## Replacement Actions

```yaml
stable_runtime_dir: /home/jenn/tools/colameta
stable_head_after_checkout: f22608fa98d8a6f92070cd9b21dcdf4210bb57e3
package_reinstall:
  command: /home/jenn/tools/colameta/.venv/bin/python -m pip install --no-deps --force-reinstall /home/jenn/tools/colameta
  result: success
  installed_distribution: colameta 0.1.2
service_restart:
  previous_pid: 2347941
  previous_pid_terminated_by_exact_term: true
  new_pid: 2372850
  command: "/home/jenn/tools/colameta/.venv/bin/python /home/jenn/tools/colameta/.venv/bin/colameta serve /home/jenn/src/colameta-dev --web-host 127.0.0.1 --web-port 8801 --mcp-host 127.0.0.1 --mcp-port 8766 --auth-mode none"
  detached: true
  start_method: setsid
  pythonpath_override_used: false
```

## Running Service Evidence

```yaml
running_service:
  pid: 2372850
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

## Web And MCP Smoke

```yaml
web:
  url: http://127.0.0.1:8801
  healthz: ok
  root_page: ok
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
    - get_runtime_version_status
    - get_connector_runtime_health_status
    - run_mcp_workflow
    - manage_executor_config
    - manage_executor_workflow
    - manage_project_docs
```

## Runtime Provenance

This block is a replacement-time snapshot captured after the stable service
restart and smoke checks.

```yaml
get_runtime_version_status:
  ok: true
  observed_scope: replacement_time_snapshot
  process_start_time_iso: 2026-07-01T16:00:51.599183Z
  project_checkout_head: f22608fa98d8a6f92070cd9b21dcdf4210bb57e3
  runtime_loaded_code_stale: false
  reload_needed_for_verification: false
  reload_awareness_reason: installed_package_matches_project_checkout
```

## Documentation Evidence

```yaml
stable_runtime_docs_present:
  docs/USAGE.zh-CN.md: true
  docs/ONBOARDING.zh-CN.md: true
  docs/DEVELOPMENT_HISTORY.zh-CN.md: true
  docs/agent-consumer-contract.zh-CN.md: true
  docs/web-gpt-service-entrypoint.zh-CN.md: true
stable_mcp_manage_project_docs:
  search_query: DEVELOPMENT_HISTORY
  result_visible: true
  first_result: docs/DEVELOPMENT_HISTORY.zh-CN.md
```

## Executor Profile Evidence

```yaml
manage_executor_config_inspect_inventory:
  provider: codex
  model: gpt-5.5
  reasoning_effort: xhigh
  settings_scope: user_settings_project
```

## Connector Caveat

```yaml
connector_runtime_health_without_external_evidence:
  local_service_status: healthy
  external_connector_status: unverified
  operator_closeout_status: local_runtime_ready_external_connector_unverified
```

The local Web/MCP runtime is healthy. External connector/tunnel closeout remains
unverified until approved sanitized tunnel-client and control-plane evidence is
provided through bounded status surfaces.

## Not Performed

```text
Delivery State accepted
ReviewDecision creation
GateEvent emission
route transition
release
deploy
package publish
executor run
provider/proxy/tunnel config mutation
secret/token/cookie/credential read
provider raw response copy
```

## Notes

At replacement time, the stable runtime directory, stable installed package, dev
checkout, and `origin/main` were all aligned to `f22608f`. Later receipt-only
commits may move the dev checkout and `origin/main` ahead without changing the
installed stable runtime. This replacement also makes the new development
history overview available from both the stable runtime directory and the running
stable MCP documentation surface.
