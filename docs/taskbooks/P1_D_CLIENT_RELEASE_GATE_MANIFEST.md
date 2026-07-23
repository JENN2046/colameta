# P1-D Client Experience And Release-Gate Manifest

```yaml
p1_d_client_release_gate:
  schema_version: colameta.p1_d_client_release_gate_manifest.v1
  document_type: implementation_binding_manifest
  status: implementation_ready
  created_at: 2026-07-24
  baseline_commit: 7e18f29
  public_commander_tool_count: 9
  public_tool_additions: forbidden
  external_configuration_authority: false
  stable_replacement_authority: false
  release_authority: false
```

## Purpose

P1-D makes the ChatGPT Commander and Local Codex experiences intentionally
different without splitting their authority semantics:

```text
ChatGPT Commander
  = exact nine tools, compact public projection, typed page continuations

Local Codex / loopback normal
  = advanced diagnostics, executor control, local migration and handoff context

Shared
  = canonical state, scopes, context binding, and authority boundaries
```

It also adds a fail-closed P1 release-decision packet. A local rehearsal can
prove the server-side contract but cannot claim that a live ChatGPT host,
connector, OAuth configuration, tunnel, or stable runtime has been accepted.

## Boundaries

- No tenth public Commander tool.
- No Connector, Auth0/OAuth, tunnel, DNS, App, stable-runtime, Git push, tag,
  publish, or release action.
- No caller-provided assertion may turn the P1 release decision ready.
- `resources/read` stays optional standards compatibility; ChatGPT's primary
  paged read paths are `review_manifest` and `read_result_artifact`.
- The local rehearsal uses only a temporary fixture and must leave it clean.

## Implementation Surface

| Path | Role |
| --- | --- |
| `runner/mcp_commander_public.py` | Frozen nine-tool partition metadata and safe artifact descriptor projection. |
| `runner/mcp_commander_app.py` | Advanced/local client-experience contract and Commander instructions. |
| `runner/chatgpt_development_acceptance.py` | Temporary-fixture contract rehearsal. |
| `scripts/chatgpt_development_acceptance.py` | Operator entry point for that rehearsal. |
| `runner/p1_release_gate.py` | Read-only fail-closed P1 release decision. |
| `runner/release_submission_readiness.py` | Exposes the distinct P1 decision without conflating it with submission materials. |

## Required Local Rehearsal Evidence

```text
tools/list
  -> exact COMMANDER_EXPOSED_TOOLS tuple (9)

current_facts preview
  -> apply without context_binding
  -> CONTEXT_BINDING_MISMATCH; no archive write

review_manifest inspect/read(all pages)/verify
  -> declared-subject SHA and expiry continuity

current_facts inspect/read_result_artifact(all pages)
  -> artifact ID, SHA-256, expiry and contiguous-page continuity

all reads
  -> typed tools only; no resources/read request
```

Run it with:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/chatgpt_development_acceptance.py --json
```

## Release Decision Contract

`p1_client_release_gate.status` must remain `blocked` until independently
verified evidence exists for all of the following:

1. full required local validation for the candidate commit;
2. fresh public endpoint runtime provenance;
3. fresh sanitized connector/OAuth reachability plus exact nine-tool discovery;
4. fresh current facts with no unresolved critical blocker;
5. a fresh live ChatGPT development-connector session covering the rehearsal
   scenarios; and
6. separately authorized exact stable-replacement target.

This implementation has no evidence-ingestion path for these claims. It is
therefore correct for the gate to stay fail-closed; this is not a release
failure and does not block local engineering work.

## Required Regression Coverage

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q \
  tests/test_chatgpt_development_acceptance.py \
  tests/test_mcp_current_facts.py \
  tests/test_mcp_commander_exposure_profile.py \
  tests/test_release_submission_readiness.py
```

The full shared-MCP validation ladder remains required before local commit.
