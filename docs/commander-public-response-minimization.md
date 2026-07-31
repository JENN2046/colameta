# Commander Public Response Contract

## Contract boundary

The nine-tool `commander` exposure profile wraps every public tool result in
`commander_response.v1` before it is returned through MCP `tools/call`, the
legacy agent-call path, or the REST Actions adapter. The `normal`,
`maintainer`, `legacy`, and loopback advanced profiles retain their existing
full engineering responses.

The public Commander inventory is exactly:

- `list_registered_projects`;
- `get_apps_connector_smoke_packet`;
- `render_commander_app`;
- `analyze_project_state`;
- `review_manifest`;
- `read_result_artifact`;
- `run_mcp_workflow`;
- `manage_validation_run`; and
- `manage_git`.

## Envelope and nested response

The public envelope keeps `ok`, `tool`, and `data`. Commander clients must use
the nested `data` object as the workflow contract:

```json
{
  "ok": true,
  "tool": "analyze_project_state",
  "data": {
    "schema_version": "commander_response.v1",
    "outcome": "completed",
    "summary": "Current project state was read.",
    "journey_stage": "observe",
    "context_binding": {
      "project_name": "colameta",
      "branch": "codex/example",
      "head": "0123456789abcdef0123456789abcdef01234567",
      "runner_plan": {
        "mode": "managed",
        "plan_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
      },
      "current_version": "N1"
    },
    "facts": {},
    "evidence": null,
    "next_action": null,
    "confirmation": null,
    "error": null
  }
}
```

`data.outcome`, not the envelope's `ok` value or an internal status field, is
the authoritative state of the current Commander call. Its only values are:

- `completed`;
- `in_progress`;
- `confirmation_required`;
- `blocked`; and
- `failed`.

`completed` means only that the current call completed. It does not declare the
project, version, review, or delivery complete.

## Relationship rules

Every response has at most one `data.next_action`, and its tool must be one of
the nine public Commander tools.

- `confirmation_required` has both `data.confirmation` and the exact bound
  confirmation action in `data.next_action`.
- `blocked` and `failed` have `data.error`; when recovery is available,
  `data.error.recovery` equals `data.next_action`.
- `in_progress` uses a polling or status-read `data.next_action`.
- Other outcomes keep `data.confirmation` and `data.error` null.

`PROJECT_REQUIRED` and `PROJECT_NOT_REGISTERED` recover through
`list_registered_projects`; clients then retry the original call with one of
the returned public project names.

## Facts, context, confirmation, and evidence

`data.facts` contains bounded current facts. It is evidence, not authority.
Project-bound reads, previews, applies, manifests, and confirmations preserve
the existing binding in `data.context_binding`.

`data.confirmation` states the decision, impact, preview ID, and any relevant
risks or expiry. A preview or binding is not reusable outside its declared
operation.

Large or detailed public-safe results use:

```text
data.evidence.kind=result_artifact
data.evidence.artifact_id
data.evidence.resource_uri
data.evidence.page_uri_template
data.evidence.page_count
data.evidence.content_sha256
data.evidence.expires_at
```

ChatGPT follows the single `data.next_action` to `read_result_artifact`.
Resource-capable MCP clients may read the opaque ColaMeta URI through
`resources/read`. A public resource continuation is rebuilt from an exact
allowlist: `kind`, `tool`, `arguments.uri`, and an optional sanitized `reason`.
Sibling paths, credentials, IDs, or diagnostics are never copied.

## Public minimization

The projection removes local or diagnostic implementation details that are not
required for the user-facing workflow, including:

- registry and private project identifiers;
- absolute project, workspace, runtime, settings, evidence, and log paths;
- process, request, workflow, session, report, and executor identifiers;
- raw logs, stdout, stderr, exception stacks, tokens, credentials, and
  authorization data; and
- nested recommendations that name tools outside the nine-tool Commander
  profile.

Local paths embedded in otherwise useful text are replaced with `<project>` or
`<local-path>`, including POSIX paths, drive-letter paths, local `file:` URIs,
and UNC paths. Detailed public-safe content is retained through opaque Result
Artifacts rather than exposed as raw local files.

## Validation boundary

Contract, policy, integration, routing, Artifact, Manifest, and context-binding
tests cover all nine tools; the five outcomes; field relationships; single
next-action selection; opaque evidence; project-selection recovery; sensitive
key and path filtering; resource-reference sibling filtering; and
non-Commander compatibility.

A stable/public runtime must still be replaced at an explicitly authorized
exact commit before live connector or Dashboard review can treat this contract
as deployed.
