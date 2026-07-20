# Runtime Version Status Decision Contract

For installation, stable replacement, post-restart verification, and rollback,
see [Installation And Deployment](INSTALLATION_AND_DEPLOYMENT.md). For package
and loaded-module provenance details, see
[Runtime Loaded-Code Verification](runtime-loaded-code-verification.md).

## Status

Status: v1.6 documentation and test contract.

This document defines how humans and Agents interpret the v1.5 read-only runtime/version observability result from `get_runtime_version_status`.

The v1.5 surface is read-only observability. It reports process start metadata, the runtime HEAD loaded by the running process, the current project checkout HEAD, and a `restart_needed_state` signal. It does not restart, reload, kill, apply, fetch, pull, push, tag, release, mutate service lifecycle state, mutate config, or run executor workflows.

## Purpose

The purpose of this contract is to make `restart_needed_state` actionable without turning it into automatic authority.

`restart_needed` and `restart_needed_state` are signals, not authorization. They can inform operator-facing wording and bounded read-only diagnostics, but they do not grant permission to mutate the running ColaMeta process, service manager state, project config, executor workflow state, or Git remote state.

## Decision Table

| `restart_needed_state` | Meaning | Required behavior | Allowed response | Forbidden behavior |
| --- | --- | --- | --- | --- |
| `not_needed` | The loaded runtime HEAD and project checkout HEAD are both known and match. | Do not prompt for restart. | Continue normal operation and, if useful, mention that runtime and checkout heads match. | Restart, reload, kill, service lifecycle mutation, config mutation, apply, executor workflow mutation, Git fetch, Git pull, Git push, tag, release. |
| `needed` | The loaded runtime HEAD and project checkout HEAD are both known and differ. | Surface an operator handoff notice only. | Explain that the running process may be stale and provide read-only evidence such as loaded HEAD, checkout HEAD, branch, and project root. | Automatic restart, reload, kill, apply, service lifecycle mutation, config mutation, executor workflow mutation, Git remote mutation, Git fetch, Git pull, Git push, tag, release. |
| `unknown` | The loaded runtime HEAD or project checkout HEAD is unavailable or undetermined. | Request or perform bounded read-only diagnostics only. | Explain which HEAD is unknown and why, using read-only evidence from the observability result. | Automatic restart, reload, kill, apply, treating unknown as safe, service lifecycle mutation, config mutation, executor workflow mutation, Git fetch, Git pull, Git push, tag, release. |

## State Rules

### `not_needed`

When `restart_needed_state == "not_needed"`, the Agent may continue normal operation.

Acceptable Agent wording:

- "The loaded runtime HEAD and project checkout HEAD match. No restart prompt is needed."
- "Runtime version status is current; continuing with the requested read-only check."

Forbidden Agent behavior:

- Restarting or reloading the service.
- Killing or replacing the running process.
- Writing config or service lifecycle state.
- Running Git fetch, pull, push, tag, or release.

### `needed`

When `restart_needed_state == "needed"`, the Agent must treat the result as an operator handoff notice only.

Acceptable Agent wording:

- "The running process may be stale: loaded runtime HEAD differs from the project checkout HEAD. This is an operator handoff notice only; no automatic restart is authorized."
- "Read-only evidence shows a runtime/checkout mismatch. An operator can decide whether to restart through an approved service lifecycle process."

Forbidden Agent behavior:

- Automatically restarting, reloading, or killing the process.
- Applying a restart preview or reload preview.
- Mutating service lifecycle state or config.
- Mutating executor workflow state.
- Running Git remote mutations, including fetch, pull, push, tag, or release.

### `unknown`

When `restart_needed_state == "unknown"`, the Agent must not treat the result as safe or current. The only allowed next step is bounded read-only diagnostics.

Acceptable Agent wording:

- "Runtime version status is unknown because the loaded runtime HEAD is unavailable. I can perform bounded read-only diagnostics."
- "Project checkout HEAD is unavailable, so no restart decision is authorized. I can report the missing metadata and stop."

Forbidden Agent behavior:

- Treating unknown as safe.
- Automatically restarting, reloading, killing, or applying changes.
- Mutating service lifecycle state, config, executor workflow state, or Git remote state.
- Running Git fetch, pull, push, tag, or release.

## Non-Authorization Rules

This contract does not authorize any automatic restart, reload, kill, or apply action.

This contract does not authorize any service lifecycle mutation.

This contract does not authorize any config mutation.

This contract does not authorize any executor workflow mutation.

This contract does not authorize any Git remote mutation. It specifically does not authorize Git fetch, pull, push, tag, or release.

This contract does not add Web Console business routes, MCP mutation tools, service manager integration, restart preview, restart apply, reload apply, notification behavior, background monitoring, or operator handoff execution surfaces.

## Closeout Rule

`get_runtime_version_status` remains a read-only observability surface. A status of `needed` can justify only an operator handoff notice. A status of `unknown` can justify only bounded read-only diagnostics. No state grants automatic action authority.
