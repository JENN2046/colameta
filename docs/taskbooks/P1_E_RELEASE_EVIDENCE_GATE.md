# P1-E Release Evidence Gate

```yaml
p1_e_release_evidence_gate:
  schema_version: colameta.p1_e_release_evidence_gate_manifest.v1
  document_type: implementation_binding_manifest
  status: implementation_verified_pending_fresh_development_acceptance
  created_at: 2026-07-24
  public_commander_tool_count: 9
  public_tool_additions: forbidden
  stable_replacement_authority: false
  release_authority: false
```

## Purpose

P1-D made the nine-tool ChatGPT contract observable and repeatable. P1-E
closes the remaining evidence-handling gap without pretending that a local MCP
server can independently see a ChatGPT host session.

```text
sanitized observed facts
  -> manifest-bound validation result
  -> preview-bound local operator receipt
  -> canonical integrity binding + candidate/freshness re-evaluation
  -> P1 client release gate shows each check as passed, stale, or blocked
  -> separate stable authorization remains required
```

The receipt labels the four external observation groups as
`operator_attested`. Full local validation is instead
`server_verified_validation_run`: the bounded local server re-reads a result
selected internally from `run_id`, verifies its terminal digest and existing
manifest contract, and derives its candidate and observation time.

## Local-Only Intake Surface

`manage_p1_release_evidence` exists only on the normal / loopback advanced
MCP profile. It is deliberately absent from the ChatGPT Commander tuple.

| Action | Scope | Effect |
| --- | --- | --- |
| `inspect`, `status` | `mcp:read` | Re-evaluate the newest exact-candidate receipt. |
| `preview` | `mcp:preview` | Validate the closed evidence contract and create a short-lived runtime preview. |
| `apply` | `mcp:commit` | Requires `preview_id` plus `confirm_release_evidence=true`; writes one ignored runtime receipt. |
| `discard` | `mcp:preview` | Removes a short-lived preview. |

The intake accepts only structural evidence fields. It rejects raw transcript
text, URLs, tunnel logs, OAuth tokens, cookies, credentials, and arbitrary
metadata.

## Exact Receipt Contract

Every observation is bound to the exact candidate commit and an `observed_at`
timestamp. The evaluator rejects observations older than 24 hours, future
observations, mismatched candidate heads, non-canonical nine-tool inventory,
missing continuity evidence, or altered receipt digests.

Required evidence groups are:

1. full local validation: one verified manifest-bound run whose fixed argv
   contract and ordered results cover pytest, self-hosting smoke, compileall,
   Ruff, and `git diff --check`; the run executes in a temporary detached
   worktree at the candidate commit and binds matching clean before/after Git
   object manifests, candidate tree, isolation, and cleanup state into the
   terminal result digest;
2. runtime provenance: loaded runtime and checkout head equal the candidate,
   with no stale-code or reload-needed flag;
3. connector/OAuth: reachable, authorized, and exposing the exact ordered
   nine-tool tuple;
4. current facts: a paged artifact descriptor with current observation and no
   unresolved critical blocker; and
5. live ChatGPT development acceptance: exact inventory, deliberate
   `CONTEXT_BINDING_MISMATCH`, manifest page/hash/expiry continuity, typed
   result-artifact page/SHA/expiry continuity, no `resources/read`, and only
   read-only calls.

## Explicit Non-Authority

The P1 gate may reach:

```text
candidate_release_status = evidence_ready_pending_stable_authorization
```

while its decision remains:

```text
status = blocked
ready = false
blocker = EXPLICIT_STABLE_REPLACEMENT_AUTHORIZATION_REQUIRED
```

Nothing in this receipt authorizes a stable replacement, service restart,
connector/OAuth change, executor run, validation run, commit, push, release,
or deployment.

## Canonical Integrity Binding And Trust Boundary

The candidate, existing `manifest_sha256`, existing `contract_sha256`, new
`validation_result_sha256`, and existing `receipt_digest` form a
**canonical integrity binding**. Each digest detects semantic divergence from
the retained expected hashes and preview/receipt bindings within the bounded
local server trust model.

SHA-256 is not a digital signature. SHA-256 is not remote attestation, and it
does not prove executor or operator identity. An unkeyed digest cannot resist a
malicious or privileged local writer that can rewrite both the persisted result
and its digest. Accordingly, `server_verified_validation_run` means verified
inside the bounded local server trust model; it is not cryptographically
authenticated execution provenance.

v1.19 adds no HMAC, digital signature, external attestation, or new trust authority.
The validation result must not be described as tamper-proof,
unforgeable, signed, remotely attested, or immutable.

The detached validation worktree prevents ordinary edits to the operator's
source checkout from changing the content under test. Its sanitized checkout
provenance is part of the terminal result's canonical integrity binding and is
re-verified for P1 eligibility. This isolation does not extend the trust model
to resist a malicious or privileged local writer that can rewrite both the
persisted result and its digest.

New P1 intake, preview, and receipt records use explicit v2 schemas. A v1
preview cannot apply. An integrity-valid v1 receipt remains read-only historical
evidence, reports at most `verified_stale`, and requires a fresh manifest-bound
validation run plus a new v2 receipt for recovery.

## Fresh Live Acceptance Handoff

After the candidate is deployed only to the development MCP, run a new
ChatGPT session against that exact HEAD. Record only the closed fields above,
then use local loopback `preview -> apply` to persist the receipt. Finally,
read `get_release_submission_readiness` or the P1 gate to verify which
blockers remain.

If the five evidence checks pass, the next action is not replacement. It is a
request for Jenn's separate, exact stable-replacement authorization.

## Required Regression Coverage

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q \
  tests/test_p1_release_evidence.py \
  tests/test_chatgpt_development_acceptance.py \
  tests/test_mcp_commander_exposure_profile.py \
  tests/test_release_submission_readiness.py
```
