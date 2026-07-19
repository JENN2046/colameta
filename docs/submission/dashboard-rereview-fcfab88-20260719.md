# Dashboard Re-Review Packet — fcfab88 — 2026-07-19

## Candidate binding

```yaml
candidate_exact_commit: fcfab88b5feed0cdf669905b085775c39f8ca621
candidate_change: commander_public_minimal.v1
current_stable_commit: b6c864c4319ceaa0afc56f4bc2b2ae96998c5f29
candidate_deployed: false
stable_replacement_authorized: false
service_restart_authorized: false
submission_artifact_sha256: 05877797d7d4115a909f64d024c2b933d089fed27b7a0791fec3412ff3e41296
tool_descriptor_changed: false
dashboard_draft_changed: false
submission_authorized: false
submission_ready: false
```

This packet binds the completed source implementation to an exact deployable
candidate. It does not replace stable, restart a service, create or update a
Dashboard draft, scan tools, upload an asset, configure OAuth, submit for
review, or publish.

## Change under review

The Commander exposure boundary now minimizes successful results for all seven
public tools before MCP `tools/call`, legacy agent-call, or REST Actions delivery.
The normal/maintainer/loopback responses retain their existing full engineering
payloads.

| Tool group | Public result after candidate deployment |
|---|---|
| `list_registered_projects` | Project name, display name, mode, availability, and Runner-managed state only. |
| Connector smoke | Health/closeout and stale/reload decisions; raw heads, PID/path/timestamp diagnostics removed; `runtime_aligned` added. |
| Commander and analysis | Broad readiness and safe-next-step facts retained; local roots, evidence paths, compact commit/file diagnostics, telemetry, and hidden-tool actions removed. |
| Workflow and validation | Necessary preview/run identifiers and relative changed files retained; record IDs, timestamps, absolute paths, raw logs, and hidden-tool actions removed. |
| Git | Requested Git job data, relative files, diffs, and necessary commit identifiers retained; unrelated workflow/audit metadata and absolute local paths removed. |

Removed data is dropped rather than copied into widget-only `_meta`.

## Source and validation evidence

- all seven tool annotations remain explicit and behavior-aligned;
- output schema coverage remains 7/7;
- Commander CSP remains limited to empty external connect/resource domains;
- exactly five positive and three negative submission tests remain in
  `chatgpt-app-submission.json`;
- focused response-minimization tests: 12 passed;
- related MCP/Commander/OAuth tests: 82 passed before the full run;
- full suite: 1503 passed, 2 skipped, 55 subtests passed;
- `compileall`: passed;
- self-hosting package/install/import/CLI smoke: passed; and
- `git diff --check`: passed before the candidate commit.

The first full-suite attempt ran concurrently with self-hosting installation and
created pre-import bytecode in the project virtual environment. The exact
toolchain test rejected that environment as designed. After removing only
recreatable `.pyc` files and rerunning serially with bytecode writes disabled,
the affected node and the complete suite passed.

## Submission artifact decision

The response projection changes live server results but does not change tool
names, titles, descriptions, input/output schemas, annotations, security schemes,
resource metadata/CSP, or MCP server instructions. The existing submission JSON
therefore remains source-consistent and keeps SHA-256
`05877797d7d4115a909f64d024c2b933d089fed27b7a0791fec3412ff3e41296`.

OpenAI's submission documentation distinguishes server-only result changes from
metadata-contract changes. Because ColaMeta has not completed final submission,
the operator should still run the final Dashboard `Scan Tools` and compare the
stored seven-tool snapshot after deployment.

## Required live re-review after separately authorized deployment

1. Replace stable with the exact candidate and restart the Private Beta service
   only after a new explicit target authorization.
2. Verify local, remote, and public health report the exact candidate, clean
   package/source match, and no stale/reload requirement.
3. Call `list_registered_projects` first, confirm `colameta-self-dev`, then run
   the same seven-tool smoke and inspect nested response keys without storing
   response values in repository evidence.
4. Confirm forbidden local diagnostics are absent and operational continuation
   identifiers/relative Git fields still work.
5. Refresh or reconnect the ChatGPT app so it loads the deployed behavior, then
   rerun all five positive tests in ChatGPT web and mobile.
6. In the authenticated Dashboard, confirm identity, global data residency,
   `api.apps.read`/`api.apps.write`, reviewer credentials, URLs, logo, listing,
   countries/regions, and the final scanned metadata snapshot.
7. Keep every readiness flag false until the corresponding human evidence is
   complete; do not select `Submit for review` without separate authorization.

## Remaining blockers

- candidate is not deployed and current stable remains b6;
- no authenticated Dashboard/browser session was available for this packet;
- Dashboard identity, permissions, data residency, reviewer credentials, and
  final Scan Tools snapshot are unverified;
- ChatGPT web/mobile positive tests have not run against the candidate; and
- current-version optional screenshots have not been captured.

Official sources reviewed:

- `https://developers.openai.com/apps-sdk/build/mcp-server/`;
- `https://developers.openai.com/apps-sdk/reference/`;
- `https://developers.openai.com/apps-sdk/deploy/submission/`; and
- `https://developers.openai.com/apps-sdk/app-submission-guidelines/`.
