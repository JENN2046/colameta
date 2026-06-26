# Platform-Blocked Operator Handoff RFC

## 1. Status

Status: RFC, documentation-only.

This document defines the fallback protocol for cases where ChatGPT cannot invoke a ColaMeta preview-bound apply action because the platform-level tool safety layer blocks the tool call before ColaMeta can evaluate its own preview, binding, confirmation, and audit checks.

This RFC does not implement the handoff system. It does not add Web Console routes, MCP tools, executor behavior, Git manager behavior, shell fallbacks, or runtime state changes.

## 2. Purpose

The purpose is to preserve ColaMeta's preview/apply audit model when a platform blocks the direct tool call that would normally carry a preview-bound apply request into ColaMeta.

A platform-blocked tool call becomes an operator handoff boundary, not a bypass. The human operator may only use an approved, action-specific ColaMeta surface, and the closeout must verify the result through read-only tools before the agent claims success.

## 3. Problem

Some ColaMeta actions require a generated preview, a stable binding, a confirmation guard, and an audit trail before mutation. In normal operation, the agent submits the apply request to ColaMeta, and ColaMeta validates the preview id, project binding, worktree or state signatures, route/action binding, and guard policy before dispatch.

When the hosting platform blocks the tool call before it reaches ColaMeta, ColaMeta cannot evaluate those checks. Treating the block as permission to perform an unbound manual workaround would break auditability and could skip the exact safety checks the action depends on.

The fallback needs a common manifest and receipt protocol so the operator can perform only the intended action on an approved surface, while the agent records the handoff and verifies the outcome using read-only closeout.

## 4. Non-goals

This RFC does not:

- implement a Web Console handoff route;
- implement an MCP handoff tool;
- authorize shell fallback;
- authorize manual state edits;
- authorize unbound apply;
- authorize skipping preview generation;
- authorize skipping closeout verification;
- authorize force push, tag, release, pull apply, restore apply, or revert apply;
- weaken Web Console CSRF, origin/host, dangerous confirmation, preview binding, or audit requirements;
- replace post-run scope validation;
- change MCP Git commit, Git remote, or MCP server internals.

## 5. Relationship to Web Remote Git Mutation Prohibition

This RFC is compatible with the existing Web Console remote Git mutation prohibition.

Web remote Git remains a read-only status surface. The Web Console must not expose push, pull, fetch, preview, apply, confirm, run, execute, or equivalent remote Git mutation routes. This handoff protocol does not authorize Web remote Git mutation.

`push_apply`, `fetch_apply`, and `pull_apply` are excluded from the first Web/operator handoff MVP. Any future remote Git mutation surface would require a separate hard-gated plan and must not be inferred from this RFC.

## 6. Approved Operator Surfaces

Approved operator surfaces must be action-specific. A generic shell, generic file editor, generic state editor, generic HTTP client, or broad "run this command" instruction is not an approved surface.

For the first RFC MVP, candidate handoff actions may be performed only through a ColaMeta-owned surface that is explicitly bound to the same action class:

- `continue_next_version`: an action-specific ColaMeta control that advances the managed plan to the next version after preview/confirmation requirements are satisfied.
- `apply_preview`: an action-specific ColaMeta preview apply control that consumes one named preview id and validates the preview binding before mutation.
- `run_once`: an action-specific ColaMeta executor run control that preserves executor confirmation and run audit behavior.
- `manual_validation_apply`: an action-specific ColaMeta validation apply control that applies a named validation preview or decision.

`commit_apply` is not part of the first handoff MVP. Local Git commit behavior remains the existing guarded flow: `/api/commit-preview` creates runtime preview metadata, and `/api/commit-confirm` is the local Git history mutation boundary requiring dangerous confirmation and the existing MCPGitCommitManager preview/HEAD/diff/file-set guards.

## 7. Fallback Policy for Platform-Blocked Tool Calls

When a preview-bound apply call is blocked by the platform before ColaMeta can evaluate it:

1. The agent must stop the direct apply attempt and classify the situation as `platform_blocked_operator_handoff_required`.
2. The agent must not synthesize a shell command, local file edit, direct state mutation, or alternative unbound apply path.
3. The agent must produce an `OPERATOR_HANDOFF` manifest that names the exact action, preview binding, target project, expected guard context, operator surface, and required closeout checks.
4. The human operator may act only on the approved action-specific ColaMeta surface named by the manifest.
5. The operator must return an `OPERATOR_RECEIPT` that claims what was done, when, on which surface, and with which visible result.
6. The agent must treat the receipt as a claim, not proof.
7. The agent must verify the outcome through read-only tools or read-only ColaMeta status/report surfaces before closing the task.
8. If read-only verification is unavailable or inconsistent with the receipt, the closeout must remain blocked or inconclusive.

## 8. Common OPERATOR_HANDOFF Manifest Schema

The manifest is a structured request from the agent to the operator. It must be recorded in the conversation or audit context before any operator action.

```json
{
  "type": "OPERATOR_HANDOFF",
  "schema_version": "1.0",
  "handoff_id": "opaque-non-secret-id",
  "reason": "platform_blocked_tool_call",
  "blocked_tool_call": {
    "tool_name": "colameta.apply_preview",
    "action_class": "apply_preview",
    "blocked_before_colameta": true,
    "platform_block_summary": "platform safety layer blocked tool invocation"
  },
  "project_binding": {
    "project_root": "/path/to/project",
    "project_id": "optional-project-id",
    "worktree_head": "optional-head-or-state-hash",
    "runner_state_signature": "optional-state-signature",
    "plan_signature": "optional-plan-signature"
  },
  "action_binding": {
    "action_class": "apply_preview",
    "preview_id": "required-when-action-uses-preview",
    "preview_signature": "required-when-available",
    "route_or_tool": "expected-colameta-action-surface",
    "target_version": "optional-version",
    "target_files": ["optional", "file", "list"],
    "expected_mutation_scope": "short human-readable scope"
  },
  "operator_surface": {
    "surface_type": "web_console",
    "surface_name": "action-specific ColaMeta apply preview control",
    "approved": true,
    "remote_git_mutation": false
  },
  "required_operator_checks": [
    "confirm project identity",
    "confirm preview id",
    "confirm action class",
    "confirm target version or scope",
    "confirm no remote Git mutation"
  ],
  "required_closeout_checks": [
    "read-only status confirms expected state",
    "read-only report or audit entry references the preview/action",
    "no unexpected mutation scope is visible"
  ],
  "expires_at": "ISO-8601 timestamp or null",
  "notes": "no secrets; no confirmation ids; no bearer tokens"
}
```

Manifest rules:

- The manifest must not contain secrets, bearer tokens, session cookies, OAuth material, private keys, or full dangerous confirmation ids.
- If a preview id is itself sensitive in a future action class, the manifest must use a redacted id plus an out-of-band approved surface that displays the full value to the operator.
- The operator surface must be specific to the requested action class.
- `remote_git_mutation` must be `false` for the first Web/operator handoff MVP.
- Missing binding fields are allowed only when the action class does not produce them; missing fields must be called out in `notes` or closeout risk.

## 9. Action Binding Matrix

| Action class | MVP status | Required binding | Approved operator surface | Required read-only closeout |
| --- | --- | --- | --- | --- |
| `continue_next_version` | Candidate | project identity, current version, plan signature when available, runner state signature when available, expected next version | Action-specific ColaMeta continue-next-version control | Read current plan/status and verify version advanced exactly once to the expected version; verify report/audit status if available |
| `apply_preview` | Candidate | project identity, preview id, preview signature, target route/tool, expected mutation scope, state/plan/worktree signatures when available | Action-specific ColaMeta apply-preview control for the named preview | Read preview/apply status, project state, plan/report/audit surfaces; verify the named preview was consumed and scope matches |
| `run_once` | Candidate | project identity, executor mode, target version or task, runner state signature, plan signature, expected run scope | Action-specific ColaMeta run-once control that preserves executor confirmation | Read executor run status/report; verify run id, version, executor mode, and changed-file scope |
| `manual_validation_apply` | Candidate | project identity, validation preview or decision id, target version, validation signature when available | Action-specific ColaMeta manual-validation apply control | Read validation status/report and verify the expected decision was applied |
| `commit_apply` | Existing guarded behavior only | commit preview id, diff hash, commit file set, HEAD, project root, plan/state signatures when available | Existing `/api/commit-confirm` dangerous-confirmed local Git history boundary | Read-only Git/status/report checks confirm the commit result; no handoff MVP authorization |
| `push_apply` | Excluded | Not applicable | Not approved | Not applicable |
| `fetch_apply` | Excluded | Not applicable | Not approved | Not applicable |
| `pull_apply` | Excluded | Not applicable | Not approved | Not applicable |
| `restore_file_apply` | Excluded | Not applicable | Not approved | Not applicable |
| `revert_apply` | Excluded | Not applicable | Not approved | Not applicable |
| `tag` | Excluded | Not applicable | Not approved | Not applicable |
| `release` | Excluded | Not applicable | Not approved | Not applicable |

## 10. OPERATOR_RECEIPT Schema

The receipt is a structured claim from the operator after using the approved action-specific surface.

```json
{
  "type": "OPERATOR_RECEIPT",
  "schema_version": "1.0",
  "handoff_id": "same-opaque-non-secret-id",
  "action_class": "apply_preview",
  "operator_surface": {
    "surface_type": "web_console",
    "surface_name": "action-specific ColaMeta apply preview control"
  },
  "operator_claim": {
    "performed": true,
    "performed_at": "ISO-8601 timestamp",
    "visible_result": "surface reported success",
    "preview_id_confirmed": "redacted-or-non-sensitive-preview-id",
    "target_confirmed": "short target summary",
    "remote_git_mutation": false
  },
  "operator_observations": [
    "short non-secret observation"
  ],
  "known_warnings": [
    "short non-secret warning or empty list"
  ],
  "secrets_included": false
}
```

Receipt rules:

- A receipt is a claim, not proof.
- The receipt must not contain secrets, bearer tokens, session cookies, OAuth material, private keys, or full dangerous confirmation ids.
- The receipt must not claim success for an action outside the manifest action class.
- The receipt must not broaden the mutation scope beyond the manifest.
- The receipt must explicitly state whether any remote Git mutation was involved; for the first MVP this value must be `false`.

## 11. Receipt Verification Rules

The agent must verify receipt claims before closeout:

1. Match `handoff_id`, `action_class`, and operator surface to the manifest.
2. Confirm the receipt does not contain secrets or forbidden identifiers.
3. Confirm the receipt does not describe an excluded action.
4. Use read-only tools or read-only ColaMeta status/report/audit surfaces to verify the claimed outcome.
5. Verify the resulting state matches the manifest's expected target and mutation scope.
6. Verify the same preview or action was not reused in a way that violates ColaMeta guard expectations.
7. Verify no Web remote Git mutation was performed or exposed.
8. If verification cannot be completed, close out as blocked or inconclusive instead of claiming success.

## 12. Closeout Outcome Taxonomy

- `verified_success`: Receipt claim matches the manifest and read-only closeout confirms the expected state.
- `verified_noop`: Receipt claim or read-only state shows no mutation occurred.
- `blocked_platform`: The platform blocked the direct tool call and no approved operator surface was used.
- `blocked_no_operator_surface`: No action-specific approved surface exists for the requested action.
- `blocked_receipt_missing`: Operator action may have occurred, but no receipt was provided.
- `blocked_receipt_invalid`: Receipt is malformed, mismatched, contains forbidden data, or claims an excluded action.
- `blocked_verification_unavailable`: Receipt exists, but read-only verification is unavailable.
- `blocked_verification_mismatch`: Read-only verification contradicts or fails to support the receipt.
- `blocked_excluded_action`: The requested action is outside the MVP or explicitly excluded.

## 13. MVP Scope

The first RFC MVP may cover only these candidate handoff actions:

- `continue_next_version`
- `apply_preview`
- `run_once`
- `manual_validation_apply`

The MVP requires:

- a common `OPERATOR_HANDOFF` manifest;
- a common `OPERATOR_RECEIPT` claim format;
- action-specific approved operator surfaces;
- read-only closeout verification;
- explicit exclusion of Web remote Git mutation;
- preservation of existing preview, binding, confirmation, and audit expectations.

## 14. Explicitly Excluded Actions

The first Web/operator handoff MVP excludes:

- `push_apply`
- `fetch_apply`
- `pull_apply`
- `restore_file_apply`
- `revert_apply`
- `tag`
- `release`
- force push
- Web remote Git mutation
- shell fallback
- manual runtime state edits
- unbound apply
- applying without a preview when the action class requires a preview
- applying without read-only closeout verification

`commit_apply` remains existing guarded behavior only through the current commit-confirm dangerous confirmation boundary. It is not authorized as a platform-blocked operator handoff action by this RFC.

## 15. Security Invariants

The handoff protocol must preserve these invariants:

1. Platform blocking creates a handoff boundary, not a bypass.
2. Preview-bound actions remain preview-bound.
3. Action binding must include the exact action class and target scope.
4. Operator surfaces must be action-specific.
5. Receipts are untrusted claims until verified.
6. Closeout must verify state through read-only tools or read-only ColaMeta status/report/audit surfaces.
7. The protocol must not authorize shell fallback or manual state edits.
8. The protocol must not authorize Web remote Git mutation.
9. The protocol must not leak secrets or full dangerous confirmation ids.
10. Excluded actions remain excluded even if an operator claims they were completed safely.
11. Missing or stale bindings require blocked or inconclusive closeout.
12. Existing Web and MCP guard boundaries remain authoritative for actions that reach ColaMeta directly.

## 16. Future Work

Future implementation work may define:

- a concrete handoff manifest emitter;
- a receipt parser and validator;
- action-specific Web UI affordances for approved MVP actions;
- read-only closeout helpers for each MVP action class;
- audit package integration for handoff manifests and receipts;
- stricter signature requirements for each action binding;
- operator identity and timestamp normalization;
- policy review for whether any additional action class should become eligible.

Future work must not infer approval for Web remote Git mutation, tag, release, force push, restore apply, revert apply, or shell fallback from this RFC.
