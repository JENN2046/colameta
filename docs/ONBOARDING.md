# ColaMeta Onboarding

[中文](ONBOARDING.zh-CN.md)

This guide is for operators or agents connecting a local project to ColaMeta
for the first time.

It covers the generic onboarding path. It does not authorize executor runs,
stable service replacement, release, deploy, ReviewDecision creation, GateEvent
emission, or Delivery State accepted.

For daily operation after onboarding, read the
[ColaMeta Operator Manual](USAGE.md).

## 1. Choose An Onboarding Mode

ColaMeta has two common project modes:

```text
source-only
  Lightweight onboarding. Use it when you only need Web/MCP/agents to read
  source code, project facts, and basic evidence.

managed
  Controlled project delivery. Use it when ColaMeta should manage version
  planning, validation, receipts, review handoff, and Git closure.
```

Selection rule:

```text
Only observing a project
  Start with source-only.

Continuously advancing versions with allowed_files and validation_commands
  Use managed.

Not sure yet
  Start with source-only, then use controlled preview before moving to managed.
```

## 2. Register The Project

From a local shell:

```bash
colameta add /path/to/project source-only
```

or:

```bash
colameta add /path/to/project managed
```

After registration:

```bash
colameta status /path/to/project
```

If the service is running, confirm:

```text
Web Console: healthy
MCP Endpoint: healthy
```

If you are using Jenn's local stable service as the command entry:

```text
stable Web: http://127.0.0.1:8801
stable MCP: http://127.0.0.1:8766/mcp
```

## 3. First Agent Reads

After an agent connects to MCP, it should not run executors or write state
first. It should read:

```text
list_registered_projects
get_agent_consumer_contract
get_service_entry_profile
get_web_gpt_service_entrypoint
get_runtime_version_status
get_connector_runtime_health_status
```

Project-level tools require `project_name`. If the agent does not know the
project name, it must call `list_registered_projects` first.

For the one-line service decision, read `readiness` from
`get_commander_app_manifest` or `service_readiness_summary` from Web
`/api/v2/status`. It collapses runtime, local service, and connector closeout
into `ready`, `needs_attention`, or `blocked`; it is read-only and does not
authorize executor runs, commits, pushes, stable replacement, ReviewDecision, or
GateEvent.
The ChatGPT Apps panel renders the same signal in the `Readiness` and
`Next Step` sections.

## 4. Minimal New-Project Smoke

After onboarding, the minimum smoke checklist is:

```text
project appears in list_registered_projects
selected profile is readable
get_runtime_version_status returns read_only=true
get_connector_runtime_health_status returns read_only=true
service_readiness_summary/readiness returns ready, needs_attention, or blocked
analyze_project_state returns project mode and recommended next step
source-only project is not treated as a managed workflow project
managed project can enter thin governed loop preview
```

If smoke fails, read `error_code` first. Do not guess parameters.

Common errors:

```text
PROJECT_NAME_REQUIRED
  Missing project_name. Call list_registered_projects first.

PROJECT_NOT_REGISTERED
  The registry does not contain this project. Run colameta add first.

PROJECT_MODE_UNSUPPORTED
  A managed-only workflow was called for a source-only project.
```

## 5. Enter Controlled Optimization

For managed projects, start with `thin_governed_loop_preview`:

```json
{
  "name": "run_mcp_workflow",
  "arguments": {
    "workflow": "thin_governed_loop_preview",
    "phase": "preview",
    "project_name": "<project_name>",
    "input_mode": "draft",
    "draft_seed": {
      "goal": "Describe the bounded objective.",
      "allowed_files": ["docs/example.md"],
      "validation_commands": ["git diff --check"],
      "review_decision_value": "NEEDS_FIX",
      "reviewer_notes": "Keep this bounded."
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

For M0-M2 low-risk local work, give
`result.codex_execution_packet.copy_paste_codex_prompt` to local Codex only when
`packet_status` is `ready`. A ready packet contains the objective, allowed files,
context files, validation commands, closeout summary, and stale HEAD recovery
guidance. A blocked packet is missing required execution boundaries or has an
invalid tier; do not execute it.

Only when formal evidence preview is needed, inspect `result.generated_input_bundle`
and feed `result.next_request_payload` back into `run_mcp_workflow` as the provided
preview input.

Preview and the local Codex packet are still bounded evidence/task guidance. They
are not executor authorization, review acceptance, commit, push, or delivery state
accepted.

## 6. Run Validation

Use `manage_validation_run`. Do not let Web GPT invent shell commands.

```text
action=preview
action=run
action=status
```

`run` requires a `preview_id`. After validation passes, do not write Delivery
accepted directly. Record a receipt or review handoff first.

## 7. Connector And Tunnel Evidence

Local Web/MCP healthy only means the local ColaMeta service is usable.

External connector/tunnel closeout needs extra sanitized evidence:

```text
tunnel_client.status
tunnel_client.reason_code
tunnel_client.evidence_source
control_plane.status
control_plane.reason_code
control_plane.evidence_source
```

Only sanitized evidence is allowed. Do not read, paste, or commit:

```text
token
cookie
credential
provider raw response
tunnel-client config
proxy config
raw logs
browser login state
```

If ChatGPT Apps connector returns `HTTP 401 token_expired`, solve it through
connector reauthentication in the UI. Do not attempt to read or patch connector
tokens locally.

## 8. Git And Stable Service

Normal project work usually follows:

```text
local edit
local validation
commit
push
CI
review / receipt
```

Stable service replacement is not a normal step. It requires exact
authorization:

```text
授权替换稳定服务到 <exact_commit_sha>
```

Without that authorization, an agent may do preflight, receipts, previews, and
recommendations. It may not replace the stable runtime.

## 9. Agent Boundary

An agent may help with:

```text
reading project facts
generating preview
organizing evidence
editing bounded allowed_files
running local validation
preparing commit
writing receipt
```

An agent should not independently perform:

```text
force push
git tag
release / deploy / publish
stable replacement
executor run
route transition
ReviewDecision creation
GateEvent emission
Delivery State accepted
reading or exposing secrets
```

## 10. Copy-Paste Agent Instruction

When asking another agent to use ColaMeta for a project, you can say:

```text
Use ColaMeta as the project command entry.

First connect to the stable MCP endpoint:
http://127.0.0.1:8766/mcp

Do read-only calibration first:
1. list_registered_projects
2. get_agent_consumer_contract
3. get_service_entry_profile
4. get_runtime_version_status(project_name="<project_name>")
5. get_connector_runtime_health_status(project_name="<project_name>")

Do not run executors, write Delivery accepted, create ReviewDecision, emit
GateEvent, replace stable service, or mutate provider/proxy/tunnel/auth config
unless Jenn gives explicit current authorization.

For implementation, use run_mcp_workflow with
workflow=thin_governed_loop_preview and input_mode=draft, then work only within
allowed_files and validation_commands.

When polling executor status from local Codex, call manage_executor_workflow
with profile_id="local_codex_commander" and stop when terminal=true or
polling_exhausted=true.
```

For Jenn's current ColaMeta self-dev project, use:

```text
project_name="colameta-self-dev"
```

## 11. Successful Onboarding Criteria

A project is onboarded enough for ColaMeta command use when:

```text
project is visible in the registry
service entry contract is readable
profile can be selected
runtime health is readable
connector health is readable
project state is readable
next workflow preview can be generated
failures return clear error_code values
```

This means ColaMeta can act as a command entry for the project. It does not mean
the project has been delivered, released, deployed, stable-replaced, or marked
Delivery accepted.
