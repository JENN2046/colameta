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
1. Run colameta doctor --json.
2. Read status / primary_blocker / safe_next_action.
3. If stable runtime evidence is the blocker, safe_next_action points to
   get_stable_replacement_cadence for read-only batch judgment.
4. If connector evidence is the blocker, run the external Apps connector smoke.
5. Use colameta ops-check --json only when you need lower-level evidence.
```

If Web GPT or a local agent has just connected to the stable MCP endpoint:

```text
1. list_registered_projects
2. get_agent_consumer_contract
3. get_service_entry_profile(profile_id="web_gpt_commander")
4. get_agent_operator_flow_packet(project_name="colameta-self-dev", profile_id="web_gpt_commander")
5. get_web_gpt_service_entrypoint
6. get_runtime_version_status(project_name="colameta-self-dev")
7. get_stable_replacement_cadence(project_name="colameta-self-dev")
8. get_apps_connector_smoke_packet(project_name="colameta-self-dev")
9. get_connector_runtime_health_status(project_name="colameta-self-dev")
```

If you want to start a controlled optimization round:

```text
1. run_mcp_workflow workflow=thin_governed_loop_preview input_mode=draft
2. For M0-M2 low-risk work, if result.codex_execution_packet.packet_status is ready, give result.codex_execution_packet.copy_paste_codex_prompt to local Codex.
3. Only when formal evidence preview is needed, inspect result.generated_input_bundle and feed back result.next_request_payload.
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

For a single service decision, use `readiness` from
`get_commander_app_manifest(project_name=...)` or `service_readiness_summary`
from Web `/api/v2/status`. It returns `ready`, `needs_attention`, or `blocked`
with safe next actions. It is read-only and does not authorize executor runs,
commits, pushes, stable replacement, ReviewDecision, GateEvent, or Delivery
accepted.

For a role-aware agent handoff, use
`get_agent_operator_flow_packet(project_name=..., profile_id=...)` before
choosing lower-level tools. It returns one `primary_next_action`, the gate level
for that action, `persona_safe_next_tool`, confirmation flags, and
`advanced_actions` for agents that need the full context. `advanced_actions`
are filtered by profile: Reviewer and Source Observer profiles see read and
evidence routes by default, not executor, commit, push, or stable promotion
entry points. The packet itself is read-only; it does not create preview
artifacts, start executors, merge, commit, push, or replace stable.

For ChatGPT Apps connector closeout, read `apps_connector_closeout` from the
same surfaces. It is a read-only smoke packet for:

```text
Apps connector reachable -> project list includes project_name -> connector closeout ready
```

It includes the exact `list_registered_projects` and
`get_connector_runtime_health_status` calls, plus a sanitized tunnel evidence
template. If the Apps connector returns `HTTP 401 token_expired`, reconnect the
Apps connector session. Do not read tokens, cookies, browser login state,
tunnel-client config, raw logs, or provider responses.

For a one-call ChatGPT Apps smoke handoff, call
`get_apps_connector_smoke_packet(project_name=...)`. It returns
`apps_connector_closeout`, the safe operator sequence, token-expired recovery
guidance, connector runtime health, and a stable replacement drift hint. The
stable hint may say that replacement is available, but it still requires Jenn's
exact `授权替换稳定服务到 <exact_commit_sha>` authorization.

If HTTP MCP `tools/list` shows `get_apps_connector_smoke_packet` but the current
ChatGPT Apps connector tool picker does not, treat it as Apps metadata cache
staleness. Open a new ChatGPT/Codex window or reconnect the ColaMeta Apps
connector, then call `list_registered_projects` again. Until the metadata
refresh exposes the new tool, use `get_connector_runtime_health_status` with the
same sanitized tunnel evidence as the read-only fallback. Do not read tokens,
cookies, browser login state, connector config, or raw logs.

`get_service_entry_profile` and `get_agent_operator_flow_packet` also return
`tool_surface_guidance`. If the current Apps tool surface has not exposed a
referenced tool, use `tool_search` with the exact ColaMeta tool name. If the
Apps surface still cannot expose it, call the stable HTTP MCP endpoint
`http://127.0.0.1:8766/mcp` with JSON-RPC `tools/call` and the
`copyable_tool_call.arguments` payload.

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

If you have the tunnel-client admin port and PID, `status` can explicitly include
sanitized tunnel evidence:

```bash
/home/jenn/tools/colameta/.venv/bin/colameta status /home/jenn/src/colameta-dev --tunnel-admin-port 8080 --tunnel-pid 4034
```

This only probes loopback admin `/healthz` and `/readyz`. It does not read tokens,
cookies, tunnel-client config, proxy config, or raw logs.

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
  "arguments": {
    "project_name": "colameta-self-dev",
    "profile_id": "web_gpt_commander"
  }
}
```

`render_commander_app` is the ChatGPT Apps entry for the ColaMeta Commander
panel. It returns a read-only manifest plus widget metadata. Pass `profile_id`
to make the embedded flow persona explicit in the panel. For clients that only
need data, use:

```json
{
  "name": "get_commander_app_manifest",
  "arguments": {
    "project_name": "colameta-self-dev",
    "profile_id": "web_gpt_commander"
  }
}
```

Apps clients can discover and read the widget resource through
`resources/list` and `resources/read`. The widget only displays service facts,
profile-aware entries, connector health, preview-first routes, and explicit
authorization gates. It does not authorize executor runs, commits, pushes,
stable service replacement, ReviewDecision, GateEvent, or Delivery accepted.

For a compact product surface map, call `get_product_console_map` or
`colameta console-map --json`. The map is read-only: it groups the available
connect/readiness, plan/review, controlled full-loop, and stable/release entry
points without invoking them. When product readiness is `blocked` or
`needs_attention`, `recommended_first_actions` promotes the concrete
`safe_next_action` from the readiness packet, such as the read-only stable
cadence check, Apps connector smoke, or a bounded runbook; it does not treat
another generic readiness read as the main repair action. Its
`release_submission_evidence_bundle` field
summarizes the local ChatGPT App submission manifest, the 10-item evidence
progress table, remaining gaps, and the next safe tool. When evidence still
needs work, `fill_plan.draft_entries[]` contains copyable
`fill_submission_evidence_files.entries[]` shapes; the operator must replace
the placeholder content with real reviewed evidence before writing files or
marking ready fields. The bundle does not write files, mark ready fields, create
an OpenAI App draft, submit review, publish, or read tokens/cookies.
In the Commander widget, the Release Evidence panel prefers these bundle draft
entries after a `Console` read and falls back to release-readiness progress and
templates after a `Submission` read.
Use `get_submission_evidence_fill_preview` to review the generated
`fill_submission_evidence_files` payload before any write. The preview returns a
copyable tool call with `mark_ready=false` and placeholder evidence content; it
does not write files, mark ready fields, create an OpenAI App draft, submit
review, or publish. When every evidence file is already present but the
manifest ready fields are still false, the same preview returns
`copyable_tool_call.tool=mark_submission_evidence_ready_fields` with
`review_confirmation=human_reviewed`; run that commit-scoped tool only after a
human reviewer confirms the referenced evidence is final. The Commander widget
`Fill Preview` button calls this read-only preview.

For the same local workflow outside the connector, use the read-only CLI
preview first. It returns the same copyable next tool without writing files:

```bash
colameta submission-evidence-preview --project-name colameta-self-dev --json
```

After reviewing the referenced evidence files, use the CLI mark-ready command:

```bash
colameta mark-submission-evidence-ready \
  --keys logo,screenshots,test_prompts,test_responses,localization,mcp_tool_info,app_management_permissions,security_review,metadata_snapshot,submission_confirmations \
  --review-confirmation human_reviewed \
  --json
```

Use `get_submission_evidence_auto_draft` when you want read-only draft text for
submission evidence that can be derived from current MCP/Commander facts. It
currently supports `mcp_tool_info`, `security_review`, and `metadata_snapshot`.
The returned `copyable_tool_call` still targets `fill_submission_evidence_files`
with `mark_ready=false`; operators must review and edit the generated text
before writing files or marking ready fields. It does not create logo,
screenshot, permissions, policy, test prompt, test response, Dashboard review,
or publication evidence.

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
      "task_tier": "M0-M2",
      "allowed_files": ["runner/example.py", "tests/test_example.py"],
      "context_files": ["README.md"],
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
result.codex_execution_packet
result.codex_execution_packet.packet_status
result.codex_execution_packet.copy_paste_codex_prompt
```

For M0-M2 low-risk tasks, pass `copy_paste_codex_prompt` directly to local Codex
only when `result.codex_execution_packet.packet_status` is `ready`. The ready
packet already contains:

```text
task packet
allowed_files / forbidden_files
context_files
validation_commands
closeout summary template
executor_session_recovery
```

`allowed_files` and `validation_commands` are required for a ready direct packet.
If either is missing, or if `task_tier` is not one of the M0-M2 low-risk tiers,
the packet is returned as `blocked`; it does not inherit example files, commands,
or validation evidence.

For repo/docs/small fixes, this avoids the full
`insert_preview -> apply -> continue -> validation preview -> run -> closeout preview -> apply`
chain.

Only when formal evidence preview is needed, inspect `result.generated_input_bundle`
and feed `result.next_request_payload` back into `run_mcp_workflow`.

A thin governed loop preview is evidence. It is not executor-run authorization.
`codex_execution_packet` only gives local Codex a bounded task packet inside
Jenn/AGENTS rules; it does not authorize Delivery accepted, ReviewDecision,
GateEvent, commit, push, or stable replacement.

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

The smooth local closeout path is to let `colameta status` explicitly collect the
safe summary:

```bash
colameta status /home/jenn/src/colameta-dev --tunnel-admin-port <admin_port> --tunnel-pid <tunnel_client_pid>
```

The command only accepts a loopback admin host, probes `/healthz` and `/readyz`
read-only, and feeds `status/reason_code/evidence_source/last_observed_at` into
`get_connector_runtime_health_status`. Bare `colameta status` still fails closed
with `external_connector=unverified`.
The same status output also prints an `Apps connector:` handoff line with the
project list check, connector closeout state, and the safe Apps reconnect next
step. It does not print tokens, cookies, raw logs, or config.

For scripts or GPT handoff packets, add `--json`:

```bash
colameta status /home/jenn/src/colameta-dev --json --tunnel-admin-port <admin_port> --tunnel-pid <tunnel_client_pid>
```

The JSON output includes `connector_runtime_health` and
`apps_connector_closeout`, so callers do not need to parse terminal text.

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

Web Commander and `get_commander_app_manifest` also expose
`apps_connector_closeout`. Use it when the next operator is ChatGPT Apps: first
call `list_registered_projects`, then call `get_connector_runtime_health_status`
with sanitized tunnel evidence, and treat `token_expired` as an Apps session
reconnect task rather than a local ColaMeta service failure.
When available, `get_apps_connector_smoke_packet(project_name=...)` packages the
same handoff into one read-only call and adds a stable replacement drift hint.
Web Commander also surfaces an `Apps smoke packet` copy action. Prefer that
call; use the connector health call only as the metadata-refresh fallback.

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

Stable replacement cadence:

```text
small productization commit -> push + CI only
dev ahead of stable -> normal development state
stable_replacement_not_required -> continue the dev batch
batch_when_ready -> replace stable only after a coherent batch is ready
```

Do not ask Jenn for stable replacement just because `dev HEAD != stable HEAD`.
That drift should be reported as `dev_ahead_stable`, not as an urgent
replacement request. Ask for exact stable authorization only when one of these
is true:

```text
stable service is broken and the fix is in dev
Jenn explicitly wants the new feature in stable now
a security or correctness fix must reach stable
a productization batch is complete and Jenn chooses to promote it
```

Use `get_stable_replacement_cadence(project_name=...)` or Web
`/api/v2/status.stable_replacement_cadence` for this read-only judgment.
`colameta status --json` also returns the same cadence packet.
When dev is ahead of stable, the cadence packet includes `dev_batch_summary`
with the commit count since stable, recent commit subjects, `batch_size`, and
`promotion_posture`. This is evidence for later batch review, not a replacement
request.
It also includes `batch_review_summary`, which summarizes the batch theme,
affected surfaces (`MCP`, `Web`, `CLI`, `docs`, `tests`), risk level, and
`suggested_review_action`. `ready_for_human_review` means review the batch; it
does not authorize or request stable replacement.

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

## 9. Stage Parallel Plan Preview

Use `get_stage_parallel_plan_preview(project_name=...)` to preview future
stage-level parallel automation. The packet groups candidate task shards,
allowed file boundaries, affected surfaces, overlap risks, and a suggested next
action such as `ready_for_parallel_run_preview` or `refine_task_boundaries`.

This is read-only planning evidence. It does not create executor previews,
start executors, create branches or worktrees, merge results, commit, push, or
replace stable. The next productized step should still be a preview-first
surface such as `stage_parallel_run_preview`.

Use `get_stage_parallel_run_preview(project_name=...)` to preview the next
orchestration layer. It assigns a deterministic `parallel_group_id`, proposes an
isolated worktree and branch for each shard, and shows the future
`manage_executor_workflow action=run_once_preview` request shape. It still does
not create worktrees, create executor preview artifacts, start executor runs, or
merge results.

The local parallel orchestration packet chain is:

1. `get_stage_parallel_plan_preview`
2. `get_stage_parallel_run_preview`
3. `get_stage_parallel_worktree_assignment_preview`
4. `get_stage_parallel_next_action_packet`
5. `manage_stage_parallel_shard_inputs action=preview`
6. `get_stage_parallel_executor_group_preview`
7. `manage_stage_parallel_executor_runs action=preview`
8. `get_stage_parallel_executor_results_packet`
9. `get_stage_parallel_group_status`
10. `get_stage_parallel_merge_preview`
11. `manage_stage_parallel_merges action=preview`
12. `get_stage_parallel_closeout_packet`

These tools let ChatGPT/Jenn inspect the whole local parallel stage path before
any mutation. `group_status`, `merge_preview`, and `closeout_packet` may accept
sanitized executor result summaries, but they do not read raw logs and they do
not create worktrees, create executor previews, run executors, merge, commit,
push, write Delivery accepted, create ReviewDecision/GateEvent, or replace
stable.

The first controlled mutation gate is `manage_stage_parallel_worktrees`.
Use `action=preview` to create a short-lived preview artifact after validating
base HEAD, dirty state, branch names, and isolated worktree paths. Use
`action=apply` only with that `preview_id` to create the isolated git worktrees.
This apply step still does not create executor previews, start executors, merge,
commit, push, write Delivery accepted, create ReviewDecision/GateEvent, or
replace stable.

Use `get_stage_parallel_next_action_packet` whenever the current stage state is
unclear. It reads current worktree, shard input, executor preview, claim, and
report metadata, then returns one `copyable_tool_call` for the next safe step.
It does not create preview artifacts, write shard input, start executors, merge,
commit, push, write Delivery accepted, create ReviewDecision/GateEvent, or
replace stable.

After isolated worktrees exist, use `manage_stage_parallel_shard_inputs`.
`action=preview` validates that each worktree exists, is on the expected
branch/head, and is clean. `action=apply` writes a shard-specific runtime
`plan.json`, `state.json`, and prompt overlay under each worktree's
`.colameta/runtime/stage-parallel-shard-inputs/current/`. It does not change the
Git baseline, create executor previews, start executors, merge, commit, push,
write Delivery accepted, create ReviewDecision/GateEvent, or replace stable.

After shard inputs exist, use `manage_stage_parallel_executor_group`.
`action=preview` validates that each worktree exists, is on the expected
branch/head, is clean, and passes executor preflight using the shard input
overlay. `action=apply` then creates one `manage_executor_workflow
action=run_once_preview` artifact per worktree. It still does not start
executors, merge, commit, push, write Delivery accepted, create
ReviewDecision/GateEvent, or replace stable.

After those `run_once_preview` artifacts exist, use
`manage_stage_parallel_executor_runs`. `action=preview` validates that every
worktree has an unclaimed, unexpired preview artifact matching the current
branch/head/provider. `action=apply` starts one executor run per isolated
worktree with `executor_session_mode=start_new`. It still does not merge results
back to main, commit main, push, write Delivery accepted, create
ReviewDecision/GateEvent, or replace stable.

After executor runs are started or completed, use
`get_stage_parallel_executor_results_packet` to read structured preview,
claim, and report metadata from the isolated worktrees. It emits sanitized
`executor_results` for `get_stage_parallel_group_status` and merge preview. It
does not read raw logs, start executors, merge, commit, push, write Delivery
accepted, create ReviewDecision/GateEvent, or replace stable.

When merge preview is ready, use `manage_stage_parallel_merges`.
`action=preview` freezes the target branch/head, source branch heads, clean
target status, and merge sequence. `action=apply` uses that `preview_id` to run
local `git merge --no-ff --no-edit` sequentially. It can create local merge
commits, but it still does not push, write Delivery accepted, create
ReviewDecision/GateEvent, or replace stable.

## 10. Local Codex HTTP MCP

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

## 11. Executor Status Polling

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

## 12. Troubleshooting

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
  codex_execution_packet, generated_input_bundle, and next_request_payload
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
