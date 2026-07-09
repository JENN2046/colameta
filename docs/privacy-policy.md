# ColaMeta Privacy Policy

Effective date: 2026-07-10

This policy describes the data handling boundaries for the ColaMeta ChatGPT App
and MCP connector. ColaMeta is a project operation console for local AI
engineering workflows. It helps an authorized operator inspect project status,
runtime readiness, release evidence, and bounded workflow previews.

## Data Processed

ColaMeta may process the following information when an authorized operator uses
the app:

- project names and registered local project paths;
- Git metadata such as branch names, commit hashes, dirty/clean status, and
  changed file paths;
- read-only runtime, connector, and release-readiness status packets;
- MCP tool names, descriptions, scopes, and safety-boundary metadata;
- operator-provided prompts or parameters needed for the requested tool call;
- generated preview packets, evidence drafts, and validation summaries.

ColaMeta is designed not to read or disclose token values, cookies, browser
login state, raw provider responses, private keys, `.env` values, tunnel-client
configuration, proxy configuration, or raw logs as part of normal ChatGPT App
operation.

## Purpose Of Processing

ColaMeta uses the processed data to:

- answer operator requests about project and runtime state;
- show read-only Commander and Product Console views;
- prepare bounded previews before any write, executor run, commit, push, stable
  replacement, or submission-evidence update;
- produce sanitized readiness and evidence packets for human review;
- diagnose connector availability without exposing secret-bearing state.

ColaMeta does not sell personal data and is not designed for advertising,
profiling, or cross-context behavioral tracking.

## Human Authorization And Side Effects

Read-only tools only report evidence. Write or commit-scoped tools require
explicit operator authorization and remain separated from preview tools.
Submission evidence drafts are not final review approval, app submission,
publication, stable replacement, or delivery acceptance.

## Storage And Retention

ColaMeta may store local project artifacts such as plans, taskbooks, evidence
drafts, validation summaries, and readiness receipts inside the project
workspace. Retention is controlled by the repository owner and local operator.
Temporary runtime files, ignored local state, and generated previews should be
deleted when no longer needed for audit or debugging.

## Logs And Redaction

Operational logs and receipts should store only sanitized status, correlation
metadata, and bounded summaries. Secret-like values, bearer tokens, cookies,
authorization codes, provider raw responses, request bodies containing secrets,
and raw tunnel or proxy logs must not be written into submission evidence,
documentation, receipts, or ChatGPT App responses.

## Third-Party Processing

When used through ChatGPT, the user's interaction with ChatGPT and connected
apps is also subject to OpenAI's applicable terms and privacy documentation.
ColaMeta's MCP server may be exposed through an HTTPS tunnel or external OAuth
provider selected by the operator. Those services process network metadata
needed to connect ChatGPT to the MCP endpoint.

## User Controls And Deletion

The local operator can remove generated evidence, receipts, taskbooks, runtime
state, and registry entries from the project workspace. Requests to review,
correct, or delete retained ColaMeta project artifacts should be directed to the
repository owner or workspace operator responsible for the deployment.

## Security Practices

ColaMeta applies least-privilege tool scopes, preview-first workflows, explicit
confirmation boundaries, public-endpoint checks, runtime provenance checks, and
secret redaction rules. These controls reduce accidental disclosure but do not
replace human review before public submission or publication.

## Contact

For questions about this policy or the ColaMeta ChatGPT App deployment, contact
the repository owner for `github.com/JENN2046/colameta`.
