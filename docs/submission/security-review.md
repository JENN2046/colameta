# Security And Privacy Review Evidence

## Reviewed surface

The public Commander profile exposes seven tools at stable target
`b6c864c4319ceaa0afc56f4bc2b2ae96998c5f29`. Remote policy permits read and
preview scopes while denying commit and plan scopes. All seven tools declare the
three required annotations and an `outputSchema`.

## Confirmed strengths

- No public input schema asks for credentials, MFA codes, payment data,
  government identifiers, biometrics, or health data.
- Connector evidence inputs accept only sanitized status, reason, source, and
  observation-time fields.
- The Commander widget declares empty external connect and resource domains.
- Commit, push, validation execution, executor execution, and destructive Git
  actions remain separately gated.
- Public preflight and repeated connector smoke passed at the exact stable
  target with zero connector evidence gaps.

## Data-minimization finding and candidate resolution

Read-only response review found more local operational detail than a public app
reviewer is likely to need:

- `list_registered_projects` returns project identifiers, local project roots,
  and update/selection timestamps;
- `render_commander_app` can include project roots, stable paths, process IDs,
  recent commit identifiers/subjects, and evidence paths;
- `analyze_project_state` can include project roots and ignored-runtime file
  names.

No credential value was observed, and the privacy policy already discloses
project names and local project paths. Nevertheless, OpenAI's submission
guidance recommends returning only fields strictly necessary for the user
request and removing unnecessary internal identifiers, timestamps, telemetry,
and local implementation details rather than merely documenting them.

Exact source candidate
`fcfab88b5feed0cdf669905b085775c39f8ca621` implements
`commander_public_minimal.v1` at the Commander exposure boundary. It removes
unnecessary local paths, process IDs, record IDs, timestamps, raw logs, evidence
paths, compact-view commit/file diagnostics, and nested actions for tools outside
the seven-tool profile. It preserves project selection, health decisions,
safe-next-step facts, operational preview/run identifiers, Git-relative files,
and Git commit identifiers when those fields are required by the requested
tool's job.

The candidate does not move removed diagnostics into widget `_meta`. Unit tests
cover all seven tools, MCP and REST envelopes, path redaction, hidden-action
filtering, and normal-profile compatibility. It has not replaced stable target
`b6c864c4319ceaa0afc56f4bc2b2ae96998c5f29`; live connector and Dashboard
review must therefore continue to treat the original finding as deployed until
an explicitly authorized stable replacement is completed.

## Policies and URLs

- Privacy policy: `https://github.com/JENN2046/colameta/blob/main/docs/privacy-policy.md`
- Support: `https://github.com/JENN2046/colameta/blob/main/docs/support.md`
- Terms: `https://github.com/JENN2046/colameta/blob/main/docs/terms-of-use.md`

All three URLs returned HTTP 200 during review. The final Dashboard operator
must still confirm publisher identity, organization data residency, app
permissions, reviewer credentials, countries/regions, and the actual scanned
metadata snapshot.

## Review status

`security_review_ready` remains false. Annotation, CSP, credential-input,
runtime-health, and candidate source checks passed. The data-minimization fix
still requires exact-target stable deployment plus live ChatGPT web/mobile and
Dashboard review before public submission.

Official submission guidance reviewed:
`https://developers.openai.com/apps-sdk/deploy/submission/`.
