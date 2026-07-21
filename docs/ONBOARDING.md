# ColaMeta Onboarding

[中文](ONBOARDING.zh-CN.md)

This guide is for operators or agents connecting a local project to ColaMeta
for the first time.

It covers the generic onboarding path. It does not authorize executor runs,
stable service replacement, release, deploy, ReviewDecision creation, GateEvent
emission, or Delivery State accepted.

For daily operation after onboarding, read the
[ColaMeta Operator Manual](USAGE.md).
Install or deploy ColaMeta first with
[Installation And Deployment](INSTALLATION_AND_DEPLOYMENT.md).

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
first. On the private App Commander surface, it should use the seven public
tools in this order:

```text
list_registered_projects
get_apps_connector_smoke_packet
render_commander_app
analyze_project_state
run_mcp_workflow only for the requested read/preview workflow
manage_validation_run only for bounded validation
manage_git only for reviewed Git operations
```

Consumer contracts, individual runtime/cadence tools, and other low-level
diagnostics are advanced loopback tools. They are not part of the seven-tool
private App contract.

Project-level tools require `project_name`. If the agent does not know the
project name, it must call `list_registered_projects` first.

The remaining role/profile packets in this section are **advanced loopback**
capabilities. After selecting a profile there, prefer
`get_agent_operator_flow_packet(project_name=..., profile_id=...)` as the
single role-aware navigation packet. It gives one `primary_next_action`, keeps
advanced context visible, and remains read-only. The packet also exposes
`persona_safe_next_tool`, `requires_confirmation_before_preview`,
`requires_confirmation_before_write_or_run`, `forbidden_workflows`, and
`tool_surface_guidance`. Reviewer and Source Observer profiles get narrower
advanced actions by default so they do not start from executor, commit, push, or
stable promotion routes.

If an advanced tool is not visible in the private App, do not bypass the
Commander profile. Use an explicitly approved local advanced client on
`http://127.0.0.1:8768/mcp`.

For the one-line private App decision, read the readiness embedded by
`render_commander_app` in the ChatGPT Apps panel's `Readiness` and `Next Step`
sections. On the advanced endpoint, the same signal is available from
`get_commander_app_manifest`; Web exposes `service_readiness_summary` at
`/api/v2/status`. It collapses runtime, local service, and connector closeout
into `ready`, `needs_attention`, or `blocked`; it is read-only and does not
authorize executor runs, commits, pushes, stable replacement, ReviewDecision,
or GateEvent.
For ChatGPT Apps connector handoff, also read `apps_connector_closeout`. It
packages the read-only smoke sequence. The private App uses
`get_apps_connector_smoke_packet`; the advanced endpoint may also use
`get_connector_runtime_health_status` with sanitized tunnel evidence. A
`token_expired` response is an Apps session reconnect task, not evidence that
the local Web/MCP service is broken.
If the server exposes `get_apps_connector_smoke_packet`, use it for the same
handoff in one read-only call. It also returns stable replacement drift as a
hint, not as replacement authorization.

Continuation-aware reads also return a public `continuation_snapshot`. Use its
`snapshot_id` to confirm that Commander, Analyze/Web, Thin-loop recovery, and
executor guidance came from the same capture; do not combine different IDs.
A new request normally has a new ID, and raw private session identity is not
part of the public snapshot.

Before enabling executor work, confirm that the host supports POSIX `flock` and
that the canonical project root is owned by the service user with no
group/world write bits (`mode & 0o022 == 0`). ColaMeta holds the operation lease
on the existing directory descriptor and creates no lock file. Treat
`PROJECT_OPERATION_BUSY` as “wait for the active operation and retry from a
fresh snapshot.” Treat `PROJECT_OPERATION_LEASE_UNAVAILABLE` as a deployment or
ownership/permission mismatch: keep dispatch stopped and fix the environment.
Never delete runtime/session state or loosen permissions to bypass either gate.

## 4. Minimal New-Project Smoke

After onboarding, the minimum smoke checklist is:

```text
Private App Commander:
project appears in list_registered_projects
get_apps_connector_smoke_packet returns read_only=true
render_commander_app embeds ready, needs_attention, or blocked
analyze_project_state returns project mode and recommended next step
source-only project is not treated as a managed workflow project
managed project can enter thin governed loop preview
gate_review_request inspect is read-only and either returns sanitized candidates or candidate_count=0

Optional loopback advanced smoke on http://127.0.0.1:8768/mcp:
selected profile is readable
get_runtime_version_status returns read_only=true
get_stable_replacement_cadence returns stable_replacement_not_required for ordinary dev/stable drift
get_connector_runtime_health_status returns read_only=true
service_readiness_summary/readiness returns ready, needs_attention, or blocked
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

PROJECT_OPERATION_BUSY
  Another process holds the project operation lease. Wait or poll the active
  run, then retry with a fresh snapshot/preview.

PROJECT_OPERATION_LEASE_UNAVAILABLE
  The host or project-root owner/mode does not satisfy the POSIX lease contract.
  Keep mutations stopped and correct the deployment.
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
Follow [Installation And Deployment](INSTALLATION_AND_DEPLOYMENT.md) for the
backup, exact checkout, wheel reinstall, restart, private App verification, and
rollback sequence.

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
2. get_apps_connector_smoke_packet(project_name="<project_name>")
3. render_commander_app(project_name="<project_name>")
4. analyze_project_state(project_name="<project_name>")
5. If Stage 0-6 asks for Gate review, call run_mcp_workflow with
   workflow=gate_review_request and phase=inspect first.

Do not run executors, write Delivery accepted, create ReviewDecision, emit
GateEvent, replace stable service, or mutate provider/proxy/tunnel/auth config
unless Jenn gives explicit current authorization.

For implementation, use run_mcp_workflow with
workflow=thin_governed_loop_preview and input_mode=draft, then work only within
allowed_files and validation_commands.
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
