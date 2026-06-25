# Secret Allowlist Policy

## 1. Purpose

This policy reduces path/name-level false positives during secret hygiene reviews. It defines when source and test paths with secret-adjacent words may be treated as allowlist candidates during path-only triage.

- This policy does not prove repository contents are secret-free.
- This policy does not allow hardcoded secrets.
- This policy only defines when source/test paths with secret-adjacent words may be treated as allowlist candidates.

## 2. Scope

This policy applies to path/name-level triage for source code and tests.

It does not apply to:

- `.env`
- `.env.*`
- private keys
- certificates
- cookie jars
- session dumps
- database files
- local runtime state
- credential stores
- real tokens
- production secrets

## 3. Allowed Source/Test Filename Terms

These terms may appear in source or test filenames when the file is normal code or test code:

- `auth`: acceptable in source or test names for authentication flow logic, auth checks, auth adapters, or auth-related test coverage.
- `oauth`: acceptable in source or test names for OAuth protocol handling, OAuth flow orchestration, or OAuth-related test coverage.
- `token`: acceptable in source or test names for token accounting, parsing, redaction, budgeting, or tests that use placeholder token concepts.
- `session`: acceptable in source or test names for session lifecycle code, session orchestration, or tests that model session behavior without storing real session state.
- `config`: acceptable in source or test names for configuration schema, defaults, validation, loading logic, or tests using non-secret placeholders.
- `settings`: acceptable in source or test names for settings definitions, validation, defaults, UI or CLI settings behavior, or related tests.
- `env`: acceptable in source or test names for environment-variable handling, environment validation, or tests using placeholder environment names and values.

### Source Roles That May Trigger Detectors

The following source-code roles may legitimately contain secret-adjacent identifiers without embedding real secrets:

- environment variable lookup/name handling;
- config metadata and config key definitions;
- CLI option definitions;
- executor adapter configuration;
- OAuth/token/session handling code;
- session/cookie metadata handling;
- redaction and detector rule definitions;
- project snapshot or placeholder-handling logic.

## 4. Current Allowlist Candidates

### Current Path-Level Allowlist Candidates

- `runner/executor_session.py`
  - Trigger: `session` can indicate session state, cookies, or credential-bearing runtime data.
  - Source/test signal: `runner/` plus `.py` suggests normal Python source code for executor session behavior.
  - Future content-aware scan: verify it contains no real session dumps, cookies, tokens, or credential literals.

- `runner/mcp_executor_config.py`
  - Trigger: `config` can indicate credential-bearing configuration.
  - Source/test signal: `runner/` plus `.py` suggests normal Python source code for executor configuration behavior.
  - Future content-aware scan: verify defaults, examples, and comments use only non-secret placeholders.

- `runner/mcp_oauth.py`
  - Trigger: `oauth` is authentication-sensitive and may involve credential exchange.
  - Source/test signal: `runner/` plus `.py` suggests normal Python source code for OAuth behavior.
  - Future content-aware scan: verify it contains no client secrets, access tokens, refresh tokens, or private credentials.

- `runner/runner_global_config.py`
  - Trigger: `config` can indicate credential-bearing configuration.
  - Source/test signal: `runner/` plus `.py` suggests normal Python source code for global runner configuration behavior.
  - Future content-aware scan: verify no real configuration values embed secrets or local private paths.

- `runner/runner_settings.py`
  - Trigger: `settings` can indicate credential-bearing settings.
  - Source/test signal: `runner/` plus `.py` suggests normal Python source code for runner settings behavior.
  - Future content-aware scan: verify settings defaults do not include real credentials or secret-like values.

- `runner/token_usage.py`
  - Trigger: `token` can indicate secret tokens.
  - Source/test signal: `token_usage` plus `.py` suggests normal Python source code for token accounting or usage tracking.
  - Future content-aware scan: verify token references are usage/accounting concepts, not real API tokens or bearer values.

- `scripts/runner_cli_env.py`
  - Trigger: `env` can indicate environment-variable or secret handling.
  - Source/test signal: `scripts/` plus `.py` suggests normal Python source code for CLI environment handling.
  - Future content-aware scan: verify environment handling does not include hardcoded secrets or credential examples.

### Policy Refinement Candidate Paths

These source-role allowlist candidates are distinct from content-safe approval. They should remain visible in redacted scan reports unless a later tool-level suppression policy is separately reviewed and authorized.

- `adapters/codex_cli_adapter.py`
- `adapters/opencode_server_adapter.py`
- `runner/cloud_agent_client.py`
- `runner/cloud_pairing.py`
- `runner/codex_executor.py`
- `runner/executor_run_reports.py`
- `runner/executor_run_workflow.py`
- `runner/mcp_server.py`
- `runner/opencode_executor.py`
- `scripts/runner_cli.py`

## 5. Non-Allowlisted Patterns

The following must not be allowlisted by filename alone:

- `.env`
- `.env.*`
- `*.pem`
- `*.key`
- `*.p12`
- `*.pfx`
- `*.cookie`
- `*.cookies`
- `*.session`
- `*.token`
- `*.secret`
- `*.credentials`
- `*.sqlite`
- `*.sqlite3`
- `*.db`
- files or directories named `secrets/`, `credentials/`, `private/`, `tokens/`, `sessions/`, `localstate/`, `.localstate/`

## 6. Review Rules

1. Source/test files with secret-adjacent names may be allowlist candidates.
2. Allowlist candidate does not mean content-safe.
3. Content-aware scanning requires separate authorization.
4. Secret-like values must be redacted in reports.
5. Real credentials require immediate human handling.
6. Private runtime state should move to `state-private/`.
7. Public configuration examples should use `*.example`, `*.sample`, or `*.template`.
8. Allowlist status does not prove content-safe, and pattern scans may miss secrets.
9. Reports must redact values and snippets.
10. Real credentials or credible secret literals require human escalation before remediation claims.

### Classification Language

- `allowlist candidate`: a path or source role that can be normal code or test code by name and location, but is not automatically content-safe.
- `confirmed false positive`: a finding whose inspected context is clearly variable/key name handling, detector/redaction rule definition, placeholder mechanism, non-secret metadata, or code for reading secrets from the environment without embedding the value.
- `likely placeholder`: a finding whose inspected context is clearly non-real placeholder material.
- `policy allowlist refinement`: a finding whose path or source role is normal and should be documented in policy while future scans still apply redaction.
- `needs targeted human review`: a finding whose context is insufficient to decide safely without Jenn's review.
- `high-risk escalation`: a finding whose inspected context strongly suggests a real credential literal, token, key, cookie, private secret, or production credential.

### Non-Suppression Rule

Allowlist policy may classify findings, but must not silently suppress them. Findings must remain visible in redacted scan reports unless a later tool-level suppression policy is separately reviewed and authorized.

## 7. Current Evidence Binding

```text
Branch: main
HEAD: 9897fc42ef64cec386e16174ab3c85432a7dfde2
Path triage result: PASS_CURRENT_HEAD_PATH_TRIAGE_REPORT_READY
Policy plan result: PASS_CURRENT_HEAD_SECRET_POLICY_FIX_PLAN_READY
Content read: no
Redacted findings review result: PASS_REDACTED_FINDINGS_REVIEW_READY
Reviewed findings: 112
High-risk escalations: 0
Human review items: 0
Policy refinement findings: 92
```

## 8. Explicit Non-Claims

* This policy does not validate that the repository contains no secrets.
* This policy does not inspect file contents.
* This policy does not authorize content-aware scanning.
* This policy does not authorize file migration, templating, deletion, or secret rotation.
