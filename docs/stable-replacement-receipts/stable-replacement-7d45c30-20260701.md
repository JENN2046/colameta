# Stable Replacement Receipt - 7d45c30

Date: 2026-07-01

Status: `completed`

This receipt records the authorized stable service replacement to:

```text
7d45c3030125e75963c557a95120aebff6e55801
```

It is evidence only. It does not create ReviewDecision, GateEvent, Delivery
State accepted, release, deploy, package publish, route transition, or further
executor-run authority.

## Authorization

Jenn authorized the replacement after push and CI success:

```text
push、CI success、再授权替换稳定服务到包含 7d45c30 的 commit。
```

## Candidate And CI

```yaml
candidate_commit: 7d45c3030125e75963c557a95120aebff6e55801
candidate_short: 7d45c30
origin_main_at_replacement: 7d45c3030125e75963c557a95120aebff6e55801
local_branch: main
local_status_after_push: clean
ci:
  name: CI
  status: completed
  conclusion: success
  run_id: 28528230365
  url: https://github.com/JENN2046/colameta/actions/runs/28528230365
```

## Backup

```yaml
backup_path: /home/jenn/tools/colameta-stable-backups/stable-before-7d45c30-20260701T232129+0800.tar.gz
backup_sha256: b18ed461c20a3e5c4ba56e1472819ccc574e2a060c137e011840e2cb44254ab0
previous_stable_head: 814568f268551963c34c874443680d9deec68027
```

## Replacement Actions

```yaml
stable_runtime_dir: /home/jenn/tools/colameta
stable_head_after_checkout: 7d45c3030125e75963c557a95120aebff6e55801
package_reinstall:
  command: /home/jenn/tools/colameta/.venv/bin/python -m pip install --no-deps --force-reinstall /home/jenn/tools/colameta
  result: success
  installed_distribution: colameta 0.1.2
service_restart:
  previous_pid: 2320578
  previous_pid_terminated_by_exact_term: true
  new_pid: 2344364
  command: "/home/jenn/tools/colameta/.venv/bin/python /home/jenn/tools/colameta/.venv/bin/colameta serve /home/jenn/src/colameta-dev --web-host 127.0.0.1 --web-port 8801 --mcp-host 127.0.0.1 --mcp-port 8766 --auth-mode none"
  detached: true
  start_method: setsid
  pythonpath_override_used: false
```

Operational note: a local `colameta restart --help` inspection attempt invoked
the legacy restart path instead of printing help and briefly interrupted the old
stable service. The final stable replacement was recovered by terminating only
the exact old stable PID and starting the authorized target on the original
loopback ports.

## Running Service Evidence

```yaml
running_service:
  pid: 2344364
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
```

## Runtime Provenance

```yaml
get_runtime_version_status:
  ok: true
  process_start_time_iso: 2026-07-01T15:23:38.900244Z
  project_checkout_head: 7d45c3030125e75963c557a95120aebff6e55801
  runtime_loaded_code_stale: false
  reload_needed_for_verification: false
  reload_awareness_reason: installed_package_matches_project_checkout
```

## Executor Model Profile Evidence

The stable service sees the project executor profile through
`manage_executor_config inspect_inventory`:

```yaml
executor_profile:
  provider: codex
  model: gpt-5.5
  reasoning_effort: xhigh
  settings_scope: user_settings_project
  inventory_match: gpt-5.5 present
```

The installed stable package constructs the Codex command with both the model
and reasoning effort:

```yaml
stable_installed_package_command_preview:
  command_has_model: true
  command_has_reasoning_effort: true
  command_shape: "/usr/bin/codex exec --model gpt-5.5 -c model_reasoning_effort=\"xhigh\" --cd /home/jenn/src/colameta-dev --json --sandbox workspace-write --ask-for-approval never --output-last-message /tmp/summary.md -"
```

Before replacement, an explicitly authorized direct adapter smoke run was
performed in a temporary project. It exited 0, used the same model/reasoning
arguments, and produced no business diff in the temporary repo. No provider raw
response or log body is copied into this receipt.

## Connector Caveat

```yaml
connector_runtime_health_without_external_evidence:
  local_service_status: healthy
  external_connector_status: unverified
  operator_closeout_status: local_runtime_ready_external_connector_unverified
  evidence_gap_count: 2
  missing_evidence:
    - tunnel_client
    - tunnel_control_plane
```

The local Web/MCP runtime is healthy. External connector/tunnel closeout remains
unverified until sanitized tunnel-client and control-plane evidence is provided
through approved status surfaces.

## Not Performed

```text
Delivery State accepted
ReviewDecision creation
GateEvent emission
route transition
release
deploy
package publish
provider/proxy/tunnel config mutation
secret/token/cookie/credential read
provider raw response copy
```

## Notes

The stable runtime now serves the authorized candidate commit with the
`codex + gpt-5.5 + xhigh` executor profile visible and enforceable through the
stable installed package command path. This receipt is a post-replacement
documentation record and does not change runtime source files.
