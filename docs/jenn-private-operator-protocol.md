# ColaMeta Commander / Jenn Private Operator Protocol

Status: implementation specification

## Purpose

ColaMeta has two remote operating tiers while retaining the public seven-tool
Commander surface.

1. `Commander` is the default. GPT may inspect and prepare previews with
   `mcp:read` and `mcp:preview`; execution remains local.
2. `jenn_private_operator` permits the one configured Jenn Auth0 principal to
   execute an explicitly previewed local batch after ChatGPT presents its write
   confirmation.

ChatGPT confirmation is a client-side user-control mechanism. ColaMeta does not
receive cryptographic proof of the click and must not report that it verified
the click. The server-side guarantee is narrower: the authenticated principal,
project, exact manifest, expiry, scopes, and one-time consumption are verified
before execution.

## Fixed safety boundary

The following remain unavailable to the private operator:

- push, pull/fetch apply, restore, revert, undo, reset, clean, merge, or rebase;
- release, tag, publish, deploy, stable replacement, or service lifecycle work;
- Runner or provider configuration changes;
- arbitrary shell commands, unbounded/bounded autonomous loops, nested operator
  batches, or an unlisted tool/action;
- operation against a project other than the registered managed
  `project_name` bound into the batch.

External callers may not invoke a write action directly. Operator execution is
available only through `run_mcp_workflow` with `workflow=operator_batch` and an
opaque, in-process dispatch capability.

## Public interface

The seven public tools and their names remain unchanged. Tool descriptors and
annotations are static and conservative; composite tools that can write remain
marked as write tools for both tiers.

### Preview

Call `run_mcp_workflow` with:

```json
{
  "workflow": "operator_batch",
  "phase": "preview",
  "project_name": "registered-managed-project",
  "operations": [
    {
      "step_id": "step-1",
      "tool": "manage_git",
      "params": {"action": "commit_apply", "preview_id": "existing-preview"}
    }
  ]
}
```

There must be 1 to the configured maximum number of operations (default 8,
hard range 1–16). Step IDs are unique. Every write operation references an
existing, project-matching underlying preview whose identity and content digest
match the requested operation. An underlying artifact that defines its own TTL
must also be unexpired. Legacy plan-patch artifacts have no intrinsic TTL, so
their unchanged digest is bound into the private `pending` execution ticket and
the ticket's five-minute default TTL supplies the execution window.

The public response contains only:

- `batch_preview_id`
- `manifest_digest`
- `required_scopes`
- sanitized `operations` containing step ID, tool, action/workflow, and phase
- `expires_at`
- `requires_confirmation: true`

The canonical versioned manifest covers project name, ordered normalized
operations, underlying preview identifiers and digests, required scopes, and
expiry. Execution never accepts replacement operations.

`plan_update/apply` consumes exactly the manifest-bound `patch_id` through the
single-patch apply path. It never invokes batch or auto-apply of other pending
plan patches.

### Execute

Call the same tool with only:

```json
{
  "workflow": "operator_batch",
  "phase": "execute",
  "project_name": "registered-managed-project",
  "batch_preview_id": "batch-id",
  "manifest_digest": "sha256-digest"
}
```

Before an atomic claim, the server verifies:

- the Operator profile is enabled;
- issuer, audience/resource, subject fingerprint, and client fingerprint;
- project, manifest digest, ticket state, and expiry;
- all required OAuth scopes;
- every referenced underlying preview is still valid.

Project, manifest digest, and ticket principal binding are verified before the
server interprets or returns any poison-marker state. A caller that does not
match the ticket receives only the corresponding fixed denial and no ticket
summary.

Operations run sequentially. The first failure stops the batch. Completed work
is retained, no rollback is attempted, and remaining steps are `not_started`.
An asynchronous executor or validation-run step must be last and completes as `started_async`.
Any validation or commit after it requires a new batch.

### Status

`phase=status` accepts `project_name` and `batch_preview_id`. Only the bound
principal may query it. The public result is allowlisted to batch ID, manifest
digest, state, step index/status, sanitized error code, and expiry. It never
returns operation parameters, prompts, commands, diffs, OAuth claims, provider
responses, local paths, or internal exceptions.

## Allowed operations and scopes

| Tool | Operation | Required scope |
|---|---|---|
| `run_mcp_workflow` | `plan_update/apply` | `mcp:plan` |
| `run_mcp_workflow` | `small_project_patch/apply` | `mcp:commit` |
| `run_mcp_workflow` | `docs_update/apply` | `mcp:commit` |
| `run_mcp_workflow` | `git_commit/commit` | `mcp:commit` |
| `run_mcp_workflow` | `agent_dispatch/apply` | `mcp:commit` |
| `run_mcp_workflow` | `prompt_to_plan/apply`, `plan_apply`, or `run` | `mcp:plan` or `mcp:commit` as normalized by phase |
| `manage_validation_run` | `run` | `mcp:commit` |
| `manage_git` | `commit_apply` | `mcp:commit` |

Every listed operation must consume its existing underlying preview. If an
existing handler cannot prove the preview binding, that operation fails closed
until the handler supplies the binding; the batch layer never synthesizes one.

`prompt_to_plan/apply_all` is intentionally excluded because it combines a
prompt write with creation and application of a new plan patch that did not
exist in the authorized manifest. Remote Operator execution must represent
those actions as separately previewed and digest-bound steps.

`required_scopes` is an ordered set. Status requires `mcp:read`; preview and
execute require the union for all operations. An insufficient-scope challenge
uses a space-separated OAuth `scope` value, for example
`mcp:plan mcp:commit`.

Scope discovery resolves the registered target project before validating the
manifest. If target resolution, ticket validation, or preview validation fails,
the scope gate fails closed to `mcp:plan` plus `mcp:commit`; it never downgrades
the request to `mcp:preview`. Execute scope discovery uses manifest scopes only
when the request's `manifest_digest` exactly matches the validated ticket. A
missing, malformed, mismatched, or concurrently replaced ticket therefore
requires both mutation scopes and cannot pass authorization using scopes from a
different manifest.

## Jenn principal policy

The profile is disabled by default. A principal matches only when all of the
following are true:

- the validated token issuer and audience/resource match server configuration;
- `sub` is present and its SHA-256 fingerprint matches the private config;
- client identity is `azp`, falling back to `client_id` only when `azp` is
  absent; differing simultaneous values are rejected;
- the client SHA-256 fingerprint matches the private config.

The specific bearer token is not bound into a ticket. Raw tokens, claims,
subject, and client identifiers are never persisted, logged, or returned.

Local commands:

```text
colameta operator-config status
colameta operator-config enable
colameta operator-config disable
```

`enable` is interactive and accepts no subject/client command-line arguments.
It hashes both inputs immediately and writes only fingerprints. `status`
reports enabled/profile/TTL/maximum steps. `disable` removes fingerprints and
restores Commander behavior.

Configuration defaults:

- `oauth_operator_profile=disabled`
- `oauth_operator_permit_ttl_seconds=300` (1–900)
- `oauth_operator_batch_max_steps=8` (1–16)

Private configuration and tickets are stored below ColaMeta's user config
directory. Directories are mode `0700` and files `0600` on POSIX. Symlinks,
wrong ownership, overly broad permissions, and path escape fail closed.
Existing permit directories with broader permissions are rejected without
silently changing their mode.

## Ticket state machine

```text
pending -> claimed -> consumed
                   -> failed
                   -> indeterminate
```

Claim is an atomic exclusive transition. Concurrent or sequential replay is
rejected. The executing process holds an exclusive lock on the claim marker;
another process treats the claim as live while that lock is held and reconciles
it as orphaned only after the owner releases the lock or exits. Step start and
terminal status are persisted around every dispatch. Ticket state, step-state
ordering, and claimed/completed timestamps are validated as one state machine,
not as independent enums. A process crash, persistence failure, or unknown
result after claim produces an `indeterminate` terminal state. A separate
private poison marker keeps that terminal decision durable when repeated ticket
writes fail, and such a ticket may never be replayed automatically.

The claim operation requires the previously validated ticket as an expected
binding. The store deep-copies and validates that expected ticket at claim
entry, so caller mutation during the claim cannot move the comparison target.
After the exclusive claim marker is created, locked, and durably
persisted, the store re-reads the ticket and compares batch ID, manifest digest,
project, subject/client fingerprints, state, steps, timestamps, and the full
canonical ticket. A mismatch fails closed,
creates an indeterminate decision, and performs no dispatch. Execution uses only
the operations from this lock-time ticket, never the earlier pre-claim object.

On POSIX, ticket, claim, and poison reads first pin the private permit directory
with a directory descriptor. Leaf files are opened relative to that descriptor
with `O_NOFOLLOW`, then checked with `fstat` for regular-file type, owner, and
mode. The root descriptor is opened component by component from `/`, with
`O_DIRECTORY|O_NOFOLLOW` at every level, and the final descriptor is checked
with `fstat`. Path or leaf replacement cannot redirect a validated read to a
different ticket or claim file.

Root creation opens each existing ancestor relative to the preceding directory
descriptor. Only the final permit directory may be created; its identity is
checked before the descriptor becomes authoritative. Ticket creation uses that
same descriptor. Claim retains both the claim descriptor and the pinned root
descriptor until every execution exit releases the batch. All execution-time
ticket replacements and poison writes reuse the retained root descriptor, so a
post-lock rename or replacement of the configured root path cannot redirect a
state transition. The service execution callback runs inside `claim()` after
registration, so there is no successful-claim handoff window outside the
release guard. If descriptor close itself fails, its numeric ownership is
quarantined for the remaining process lifetime instead of being forgotten; all
permit descriptors are close-on-exec and the operating system closes any truly
live quarantined descriptor at process exit. If secure POSIX dirfd primitives
are unavailable, permit storage and execution fail closed; there is no pathname
fallback.

The process exposes a local read-only quarantine observation. It reports
`quarantined_close_fd_count`, a fixed attention threshold of `1`, a
`clear|attention` state, and the fixed local alert code
`OPERATOR_FD_QUARANTINE_ATTENTION` when the threshold is met. The observation
returns detached values and never descriptor numbers. `colameta operator-config
status` appends it under `private_runtime`; it is not persisted in Operator
configuration and is not included in MCP responses, public tickets, or logs.
The local `colameta status` health summary also includes the observation under
`private_operator_runtime` for JSON output and as a dedicated stderr summary
line for text output. This projection is assembled only in the local CLI; the
shared runtime-health builders and public MCP connector-health tool do not
import or receive the observation. Because the gauge is process-local, a fresh
process starts at zero; tests verify zero, threshold, and multiple-quarantine
states without persisting descriptor identities.

The CLI process's zero is not evidence about a different running service. The
permission-constrained cross-process design is specified in
`jenn-private-operator-local-ipc-design.md`; its executable negative-path
contract is `jenn-private-operator-local-ipc-negative-test-matrix.json`. Until
that design is implemented, the existing CLI projection remains process-local
only. The IPC design is Linux-only, diagnostic-only, fail-closed on identity or
transport uncertainty, and introduces no public MCP, HTTP, or Web surface.

On POSIX, ticket creation and replacement, claim creation, and poison creation
are persisted with both a file `fsync` and a permit-directory `fsync`. Ticket
replacement uses a private-mode temporary file, file `fsync`, atomic rename
within the pinned directory,
and directory `fsync`. A failure in any persistence barrier fails closed and
cannot be reported as a successful state transition.

Deterministic failure-injection tests cover the syscall boundaries for root
walk/create (`open`, `mkdir`, `chmod`, `stat`), ticket create/update (`open`,
`fchmod`, `write`, file/directory `fsync`, `rename`, cleanup `unlink`), claim
(`open`, `fchmod`, `flock`, `write`, claim/root `fsync`, locked read, claimed
update), poison (`open`, `fchmod`, `write`, file/root `fsync`, ticket update),
and release (`flock` unlock and each owned `close`). Every matrix row asserts
the resulting durable state, active ownership maps, quarantine count, and open
descriptor set as applicable.

Immediately around each real handler call, the operator binds the expected
preview ID and canonical artifact digest in an internal execution context. The
handler validates the payload it actually consumed against that binding. A
replacement between the pre-execution validation and the handler read therefore
fails with no authorized side effect instead of executing different content.

## Public response and logging rules

Operator responses use explicit field allowlists. They do not include local
paths, raw operation parameters, file bodies, diffs, prompts, commands, OAuth
claims, fingerprints, tokens, provider payloads, tracebacks, or internal error
messages. Every public error code is regex-filtered, including preview-validator
failures. Logs use only batch ID, manifest digest prefix, ordinal state, and
sanitized error code.

Commander applies a dedicated final projection to `operator_batch` results.
It preserves the allowlisted `expires_at` continuation field and does not add
the generic `project_name` field or any internal project identity.

## Delivery boundary

Implementation and tests do not edit Auth0 or ChatGPT, replace or restart a
stable service, publish, tag, push, or execute a real remote Operator batch.
