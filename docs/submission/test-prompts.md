# Test Prompts Evidence

These prompts mirror the five positive cases in
`chatgpt-app-submission.json`. Tool names below are the exact public Commander
tool names loaded at `b6c864c`.

## T001 — Project discovery

Prompt: List my registered ColaMeta projects.

Expected tool: `list_registered_projects`.

Expected behavior: return registered-project identity and availability facts so
the user can select a project safely, without changing project state.

## T002 — Connector smoke

Prompt: Check the Apps connector smoke status for `colameta-self-dev`.

Expected tool: `get_apps_connector_smoke_packet`.

Expected behavior: return sanitized connector reachability, runtime provenance,
evidence gaps, and closeout status without exposing credentials or raw logs.

## T003 — Commander and project analysis

Prompt: Open ColaMeta Commander for `colameta-self-dev` and summarize the
project's current state.

Expected tools: `render_commander_app`, then `analyze_project_state`.

Expected behavior: render the project-scoped Commander and summarize current
Git, Runner, plan, executor, and evidence facts with safe next actions.

## T004 — Stage 0–6 governed-loop preview

Prompt: Prepare a Stage 0–6 thin governed loop preview for
`colameta-self-dev`, but do not apply changes or run an executor.

Expected tool: `run_mcp_workflow` with
`workflow=thin_governed_loop_preview` and `phase=preview`.

Expected behavior: return read-only Stage 0–6 evidence, no changed files, and no
Delivery State, ReviewDecision, GateEvent, executor, commit, push, or stable
replacement action.

## T005 — Validation and Git readiness

Prompt: Preview current-version validation for `colameta-self-dev`, then show
Git commit readiness without committing or pushing.

Expected tools: `manage_validation_run`, then `manage_git`.

Expected behavior: return a bounded validation preview and Git readiness
evidence while stopping before validation execution, commit, or push.

## Review boundary

These cases must be rerun in both ChatGPT web and mobile before submission.
Repository and local-MCP checks do not substitute for that Dashboard reviewer
run.
