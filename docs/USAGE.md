# ColaMeta Operator Manual

[中文](USAGE.zh-CN.md)

This is the main ColaMeta operator manual for Jenn, local Codex, Web GPT,
planner agents, reviewer agents, and other agents that use ColaMeta through
MCP.

It explains how to use ColaMeta day to day. It does not grant release
authority, stable service replacement authority, Delivery State accepted,
ReviewDecision creation, or GateEvent emission.

For onboarding a new local project into ColaMeta, read
[ColaMeta Onboarding](ONBOARDING.md) first.

## 0. Fast Path

If you only need to check whether ColaMeta is usable now:

```text
1. Run colameta status.
2. Confirm Web healthy and MCP healthy.
3. Call get_runtime_version_status.
4. Call get_connector_runtime_health_status.
```

If Web GPT or a local agent has just connected to the stable MCP endpoint:

```text
1. list_registered_projects
2. get_agent_consumer_contract
3. get_service_entry_profile(profile_id="web_gpt_commander")
4. get_web_gpt_service_entrypoint
5. get_runtime_version_status(project_name="colameta-self-dev")
6. get_connector_runtime_health_status(project_name="colameta-self-dev")
```

If you want to start a controlled optimization round:

```text
1. run_mcp_workflow workflow=thin_governed_loop_preview input_mode=draft
2. Inspect result.generated_input_bundle.
3. Feed back result.next_request_payload as-is.
4. Let local Codex implement only within allowed_files and validation_commands.
5. Review the diff before deciding commit, push, or stable replacement.
```

If you only need validation or regression evidence:

```text
1. manage_validation_run action=preview
2. manage_validation_run action=run preview_id=<preview_id>
3. manage_validation_run action=status run_id=<run_id>
4. Record the result as a receipt or feedback. Do not write Delivery accepted.
```

If connector or tunnel status is still unverified:

```text
1. Confirm local_service=healthy first.
2. Extract only sanitized evidence from approved status surfaces.
3. Feed the sanitized evidence into get_connector_runtime_health_status.
4. Write a closeout receipt only after operator_closeout.decision=ready.
```

If this manual and the stable service response do not match exactly:

```text
1. Check whether the dev repo is ahead of origin/main.
2. Check whether the stable service has been replaced to the commit containing
   this manual.
3. If the dev repo is newer than the stable service, trust the stable service
   response for current operations.
4. Do not replace the stable service just because docs are newer. Stable
   replacement requires Jenn's exact authorization.
```

## 1. Know Which Entry Point You Are Using

ColaMeta normally has three entry points:

```text
stable service
  The daily-use Web/MCP service.

dev test service
  A temporary service for verifying new dev repo behavior.

repo-local commands
  Commands run from the current shell while developing or maintaining ColaMeta.
```

Jenn's current local stable service:

```text
stable runtime dir: /home/jenn/tools/colameta
stable Web: http://127.0.0.1:8801
stable MCP: http://127.0.0.1:8766/mcp
managed project_name: colameta-self-dev
dev repo: /home/jenn/src/colameta-dev
```

Web GPT and external agents should prefer the stable MCP endpoint. Use a dev
test MCP endpoint only when you are explicitly validating new dev repo behavior.

Keep these three versions separate:

```text
dev repo HEAD
  The code and docs being edited, committed, and pushed.

stable service HEAD
  The code actually running from /home/jenn/tools/colameta.

origin/main
  The remote main branch that GitHub CI validates.
```

Daily use follows the stable service. Development and docs work happens in the
dev repo. The stable service moves only after push, CI success, and Jenn's exact
authorization:

```text
授权替换稳定服务到 <exact_commit_sha>
```

Check the service from a local shell:

```bash
/home/jenn/tools/colameta/.venv/bin/colameta status /home/jenn/src/colameta-dev
```

Read health like this:

```text
Web healthy + MCP healthy
  Local ColaMeta is usable.

runtime_loaded_code_stale=false
  The running code has been proven aligned with checkout/package.

reload_needed_for_verification=true
  Not always a failure. It often means the running stable service cannot prove
  it matches the current dev checkout. If the dev repo is ahead and stable has
  not been replaced, this is expected.

external_connector=unverified
  Local Web/MCP is usable, but tunnel-client/control-plane evidence has not
  been provided.

operator_closeout.decision=blocked
  Connector closeout cannot be closed yet. This does not mean local Web/MCP is
  broken.
```

## 2. First Reads After MCP Connects

After MCP connects, do read-only calibration first. Do not run an executor,
commit, push, or write project state before reading the service contract.

Recommended first reads:

```json
{"name": "list_registered_projects", "arguments": {}}
```

```json
{"name": "get_agent_consumer_contract", "arguments": {}}
```

```json
{
  "name": "get_service_entry_profile",
  "arguments": {"profile_id": "web_gpt_commander"}
}
```

```json
{
  "name": "get_web_gpt_service_entrypoint",
  "arguments": {}
}
```

Project-level tools require `project_name`:

```json
{
  "name": "render_commander_app",
  "arguments": {"project_name": "colameta-self-dev"}
}
```

`render_commander_app` is the ChatGPT Apps entry for the ColaMeta Commander
panel. It returns a read-only manifest plus widget metadata. For clients that
only need data, use:

```json
{
  "name": "get_commander_app_manifest",
  "arguments": {"project_name": "colameta-self-dev"}
}
```

Apps clients can discover and read the widget resource through
`resources/list` and `resources/read`. The widget only displays service facts,
profile-aware entries, connector health, preview-first routes, and explicit
authorization gates. It does not authorize executor runs, commits, pushes,
stable service replacement, ReviewDecision, GateEvent, or Delivery accepted.

```json
{
  "name": "get_runtime_version_status",
  "arguments": {"project_name": "colameta-self-dev"}
}
```

```json
{
  "name": "get_connector_runtime_health_status",
  "arguments": {"project_name": "colameta-self-dev"}
}
```

If you see `PROJECT_NAME_REQUIRED`, call `list_registered_projects`, choose the
returned `project_name`, and retry.

If you are calling HTTP MCP directly instead of using a GPT connector, wrap tool
calls in JSON-RPC:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "list_registered_projects",
    "arguments": {}
  }
}
```

Read structured results from:

```text
result.structuredContent.ok
result.structuredContent.data
```

`result.content[0].text` is a short display message for MCP clients. It is not
the primary structured payload.

Minimal Python example:

```bash
python3 - <<'PY'
import json
import urllib.request

payload = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
        "name": "list_registered_projects",
        "arguments": {},
    },
}
request = urllib.request.Request(
    "http://127.0.0.1:8766/mcp",
    data=json.dumps(payload).encode("utf-8"),
    headers={"Content-Type": "application/json"},
)
with urllib.request.urlopen(request, timeout=10) as response:
    body = json.load(response)

print(json.dumps(body["result"]["structuredContent"], indent=2))
PY
```

Minimal `curl` example:

```bash
curl -sS http://127.0.0.1:8766/mcp \
  -H 'Content-Type: application/json' \
  --data '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"list_registered_projects","arguments":{}}}'
```

Generic result reading:

```text
ok=true
  Read data, then check read_only, side_effects, and recommended_next_reads.

ok=false
  Read error_code, message, and details first. Do not guess parameters.

packaged=true
  The result was compressed into a manifest. Continue through
  recommended_next_reads.
```

Common errors:

```text
PROJECT_NAME_REQUIRED
  Call list_registered_projects, then retry with project_name.

PROJECT_ROOT_OVERRIDE_NOT_ALLOWED
  Service mode does not accept arbitrary project_root. Use registered
  project_name.

UNKNOWN_SERVICE_ENTRY_PROFILE
  Call get_agent_consumer_contract and choose a profile_id from
  service_entry_profiles.
```

## 3. Common Agent Profiles

Use `get_service_entry_profile` to select an operating profile:

```text
web_gpt_commander
  Web GPT command entry. Reads facts, generates payloads, and asks Jenn for
  authorization.

local_codex_commander
  Local Codex entry. Can edit code, validate, commit, and push within safe
  repo scope and local rules.

planner_agent
  Planning entry. Generates thin loop preview inputs and does not dispatch an
  executor.

reviewer_agent
  Review entry. Reads evidence and diffs, reports findings, and does not
  create ReviewDecision.

source_observer
  Source observation entry. Reads source/runtime facts and does not treat a
  source-only project as a managed workflow project.
```

## 4. Start A Controlled Optimization Preview

Ask ColaMeta to draft the input. Do not hand-build full `thin_loop_inputs` first.

```json
{
  "name": "run_mcp_workflow",
  "arguments": {
    "workflow": "thin_governed_loop_preview",
    "phase": "preview",
    "project_name": "colameta-self-dev",
    "input_mode": "draft",
    "draft_seed": {
      "goal": "Describe the bounded optimization objective.",
      "allowed_files": ["runner/example.py", "tests/test_example.py"],
      "validation_commands": [
        ".venv/bin/python -m pytest tests/test_example.py -q",
        "git diff --check"
      ],
      "review_decision_value": "NEEDS_FIX",
      "reviewer_notes": "Keep this bounded and do not mutate state."
    }
  }
}
```

Inspect:

```text
result.generated_input_bundle
result.next_request_payload
```

If the generated input is correct, send `result.next_request_payload` back into
`run_mcp_workflow` to enter provided preview.

A thin governed loop preview is evidence. It is not executor-run authorization.

## 5. Run Validation

Web GPT does not need to compose shell commands by itself. Use
`manage_validation_run`.

Preview:

```json
{
  "name": "manage_validation_run",
  "arguments": {
    "action": "preview",
    "scope": "target_files",
    "project_name": "colameta-self-dev",
    "target_files": ["runner/example.py", "tests/test_example.py"]
  }
}
```

Run after receiving `preview_id`:

```json
{
  "name": "manage_validation_run",
  "arguments": {
    "action": "run",
    "project_name": "colameta-self-dev",
    "preview_id": "<preview_id>"
  }
}
```

Poll status:

```json
{
  "name": "manage_validation_run",
  "arguments": {
    "action": "status",
    "project_name": "colameta-self-dev",
    "run_id": "<run_id>"
  }
}
```

Passing validation does not automatically mean Delivery accepted. Record the
result as a receipt or review handoff first.

## 6. Connector And Tunnel Closeout

Read baseline connector health:

```json
{
  "name": "get_connector_runtime_health_status",
  "arguments": {"project_name": "colameta-self-dev"}
}
```

Without external evidence, a normal result may be:

```text
local_service=healthy
external_connector=unverified
operator_closeout=local_runtime_ready_external_connector_unverified
decision=blocked
```

This means local ColaMeta is usable, but tunnel-client/control-plane evidence is
not closed.

Only feed approved, sanitized evidence back into ColaMeta. If the environment
has a tunnel-client admin port and PID, a local operator may run:

```bash
/home/jenn/tools/tunnel-client/bin/tunnel-client health --port <admin_port> --pid <tunnel_client_pid> --json
```

Extract only safe summary fields such as `ok`, `status`, and `reason_code`.
Do not paste raw responses, logs, config, keys, or provider output.

Sanitized evidence example:

```json
{
  "name": "get_connector_runtime_health_status",
  "arguments": {
    "project_name": "colameta-self-dev",
    "tunnel_client": {
      "status": "healthy",
      "reason_code": "TUNNEL_CLIENT_HEALTHZ_READY",
      "evidence_source": "tunnel-client health --port <admin_port> --pid <tunnel_client_pid> --json healthz_ok",
      "last_observed_at": "<observed_at_iso8601>"
    },
    "control_plane": {
      "status": "healthy",
      "reason_code": "TUNNEL_CONTROL_PLANE_READYZ_READY",
      "evidence_source": "tunnel-client health --port <admin_port> --pid <tunnel_client_pid> --json readyz_ok",
      "last_observed_at": "<observed_at_iso8601>"
    }
  }
}
```

Target closeout:

```text
external_connector=healthy
operator_closeout=connector_closeout_ready
decision=ready
evidence_gap_count=0
operator_closeout.evidence_gaps=[]
```

Never put these into evidence:

```text
raw token
cookie
credential
runtime key
provider raw response
tunnel-client raw config
proxy config
raw logs
browser login state
```

If a ChatGPT Apps connector returns `HTTP 401 token_expired`, that is connector
reauthentication work. It is not fixed by restarting the local ColaMeta service,
and an agent must not read or modify connector tokens/cookies.

## 7. Receipts

A receipt is evidence. It is not a state transition.

Good times to write a receipt:

```text
stable service replacement completed
Web/MCP smoke completed
runtime provenance verified
connector/tunnel closeout completed or clearly blocked
CI success needs traceable evidence
```

A receipt should record:

```text
commit
CI run
backup path and sha256
PID and ports
Web/MCP smoke
runtime provenance
connector closeout status
remaining caveats
not_performed boundary
```

A receipt must not claim:

```text
Delivery State accepted
ReviewDecision
GateEvent
route transition
executor run
release / deploy / package publish
```

## 8. Git And Stable Replacement

Normal code or docs work:

```text
1. Edit locally.
2. Run local validation.
3. Commit.
4. git push origin main.
5. Wait for CI success.
```

Stable service replacement is a hard boundary. It requires Jenn's exact
authorization:

```text
授权替换稳定服务到 <exact_commit_sha>
```

Stable replacement must include:

```text
preflight: HEAD / origin/main / CI success
backup: /home/jenn/tools/colameta-stable-backups/*.tar.gz + sha256
checkout stable dir to exact commit
pip reinstall stable package
restart stable Web/MCP
Web/MCP smoke
runtime provenance check
receipt
```

Do not treat CI success, read-only evidence, preview, or receipt as automatic
stable replacement authorization.

## 9. Local Codex HTTP MCP

For local Codex, the stable HTTP MCP endpoint can be registered as:

```bash
codex mcp add colameta-local --url http://127.0.0.1:8766/mcp
```

Inspect the local Codex MCP entry:

```bash
codex mcp get colameta-local
```

Expected shape:

```text
enabled: true
transport: streamable_http
url: http://127.0.0.1:8766/mcp
```

The HTTP MCP endpoint follows JSON-RPC notification semantics. A no-id
`notifications/initialized` request should not return a JSON-RPC response body:

```text
status: 202
body_bytes: 0
```

If a new Codex session reports `MCP startup failed`, `Transport channel closed`,
or `handshaking with MCP server failed`, test the HTTP MCP endpoint directly
before changing provider/auth config.

## 10. Executor Status Polling

Executor status polling is profile-aware. Read the selected service entry
profile first:

```json
{
  "name": "get_service_entry_profile",
  "arguments": {"profile_id": "local_codex_commander"}
}
```

The response includes `executor_status_polling_guidance`.

Default Web GPT behavior remains short and non-blocking:

```text
profile_id: web_gpt_commander
next_poll_after_seconds: 3
max_poll_attempts: 3
max_total_poll_seconds: 9
```

Local Codex can follow a bounded long-running executor task:

```text
profile_id: local_codex_commander
next_poll_after_seconds: 5
max_poll_attempts: 24
max_total_poll_seconds: 120
```

When polling from local Codex, pass the profile explicitly:

```json
{
  "name": "manage_executor_workflow",
  "arguments": {
    "action": "status",
    "project_name": "colameta-self-dev",
    "run_id": "<run_id>",
    "profile_id": "local_codex_commander",
    "poll_attempt": 1
  }
}
```

Stop polling when `terminal=true`, when `polling_exhausted=true`, or when the
status reports provider/auth/quota/network failure. If only heartbeat is still
up but `last_meaningful_progress.stale=true`, treat it as a possible stalled
executor run instead of continuing indefinitely.

## 11. Troubleshooting

### Manual smoke checklist

After changing docs or replacing the stable service, run this minimum smoke:

```text
colameta status shows running
Web /api/healthz OK
MCP /healthz OK
tools/list shows core entry tools
list_registered_projects shows colameta-self-dev
get_runtime_version_status(project_name) returns runtime provenance fields
get_connector_runtime_health_status(project_name) returns local_service,
  external_connector, and operator_closeout
run_mcp_workflow thin_governed_loop_preview input_mode=draft returns
  generated_input_bundle and next_request_payload
```

If these pass, the daily command entry is usable. The connector/tunnel may still
be `unverified`; that means external evidence is missing, not that local Web/MCP
is unusable.

### `PROJECT_NAME_REQUIRED`

Cause: a project-level tool was called without `project_name`.

Fix:

```text
Call list_registered_projects.
Choose project_name.
Retry the original tool.
```

### Web API 403

Cause: read APIs require headers embedded in the Web root page.

Fix:

```text
Open the Web root page first.
Read these meta values:
  colameta-csrf-token
  colameta-web-read-auth
Send API requests with:
  X-ColaMeta-CSRF
  X-ColaMeta-Read-Auth
```

Do not print or commit token/header values.

### `runtime_loaded_code_stale=true`

Cause: the running process loaded code that does not match checkout/package.

Fix:

```text
Read get_runtime_version_status.
Check reload_awareness_reason.
If stable replacement or restart is needed, get Jenn's exact authorization.
```

### `external_connector=unverified`

Cause: tunnel-client/control-plane sanitized evidence is missing.

Fix:

```text
Use an approved status surface, such as tunnel-client health.
Extract only ok/status/reason_code style summaries.
Feed them into get_connector_runtime_health_status.
Check operator_closeout.evidence_gaps.
Write a connector closeout receipt when ready.
```

### `UNSAFE_CONNECTOR_EVIDENCE`

Cause: external evidence included unsafe fields such as raw token, log, or
config.

Fix:

```text
Keep only:
  status
  reason_code
  evidence_source
  last_observed_at
```

### CI failure

Fix:

```text
gh run list --commit <sha>
gh run view <run_id> --log
Identify the failing job.
Fix locally.
Run local validation.
Push again.
```

Do not replace the stable service while CI is failing.

## 12. Minimum Safety Boundary

Without Jenn's explicit, current, scope-specific authorization, do not execute:

```text
stable service replacement
executor run
route transition
ReviewDecision creation
GateEvent emission
Delivery State accepted
git tag
force push
release / deploy / publish
database write
provider/auth/proxy config mutation
tunnel-client restart
```

Never read, print, copy, or commit:

```text
.env
tokens
cookies
credentials
runtime keys
provider raw responses
tunnel-client config/log raw content
private memory
browser login state
```

## 13. Current Delivery Fit

ColaMeta is suitable for:

```text
project registration
project fact reading
Web/MCP command entry
thin governed loop preview
controlled validation
review handoff
receipt/evidence archiving
local Git commit/push assistance
stable promotion evidence preparation
connector/tunnel closeout evidence judgment
```

ColaMeta should not be treated as:

```text
an unattended release system
an executor dispatch system that bypasses Commander authorization
an operations system that mutates provider/proxy/tunnel config automatically
a replacement for human acceptance and product judgment
```

The most reliable operating model is:

```text
ColaMeta handles evidence and controlled workflow.
GPT/Codex handles implementation and review.
Jenn handles direction, authorization, and final judgment.
```
