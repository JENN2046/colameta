# P1 Convergence Execution Baseline

```yaml id="p1-convergence-execution-baseline-metadata"
p1_convergence_execution_baseline:
  schema_version: colameta.p1_convergence_execution_baseline.v2
  document_type: bounded_execution_plan
  status: execution_ready_after_batch_gate
  authority_status: planning_reference_only
  created_at: 2026-07-24
  revision: 5
  execution_style: decisive_batched_delivery
  baseline_branch: main
  baseline_head: 20ecb3b4f043f752f66ea5228accdcf64ceb1a98
  public_commander_contract:
    visible_tool_count: 9
    source_of_truth: runner.mcp_server.COMMANDER_EXPOSED_TOOLS
    supersedes:
      - commander_convergence_taskbook.v1.public_tool_count_freeze_only
  implementation_authority: false
  commit_authority: false
  push_authority: false
  stable_replacement_authority: false
  external_configuration_authority: false
```

## Decision

P1 is an aggressive convergence program, not a slow sequence of cosmetic
patches. The public Commander contract is exactly nine tools: the original
seven plus `review_manifest` and `read_result_artifact`. This v2 baseline
supersedes the prior seven-tool freeze **only** for that already implemented,
typed-read expansion. It does not authorize a tenth public tool during P1.

The program attacks four problems in order: the oversized MCP composition root,
the absence of one generated current-facts artifact, disconnected Stage 7--9
previews, and an overly similar ChatGPT/local-Codex experience. Compatibility,
not hesitation, is the reason legacy routes remain temporarily available.

## Non-Negotiable Operating Rules

1. Every batch ships a coherent vertical slice or does not ship. There are no
   long-lived half-extracted modules, duplicate authorities, or greenwashed
   compatibility shims.
2. `mcp_server.py` becomes transport, registry, policy, and compatibility
   composition only. Domain behavior belongs in `runner/mcp_*.py` modules.
3. The public nine-tool contract is frozen through P1. New capability first
   appears behind an existing typed tool, `run_mcp_workflow` compatibility, or
   the loopback advanced/local-Codex surface.
4. Runtime facts are generated snapshots, never silently rewritten history.
   Historical receipts, protected taskbooks, and stable-replacement evidence
   remain immutable inputs.
5. Stage 7--9 stay read/preview-only. Missing hash, context, authority, or
   observation evidence is a hard blocker, never a reason to guess.
6. A local pass is not a release. Stable replacement, Connector cutover, OAuth,
   tunnel, DNS, push, tag, publish, and public submission remain separate,
   explicit decisions.

## Baseline Already Earned

- context-bound mutation/confirmation checks across public workflow,
  validation, and Git surfaces;
- canonical historical/current/freshness state projection;
- explicit executor-negation routing and regression coverage;
- manifest-bound independent reading; and
- typed, read-only packaged-result continuation accepted in a real ChatGPT
  development-connector session without relying on `resources/read`.

These are foundations, not reasons to defer the remaining work.

## P1-A — Break The MCP Monolith And Narrow The Public Workflow

### Target

Reduce `runner/mcp_server.py` from its baseline of roughly 17.6k lines to at
most 9k lines. It owns only HTTP/JSON-RPC transport, authentication/policy
selection, tool registration, response-envelope composition, and explicit
legacy routing. It must not retain direct domain implementation for extracted
families.

### Required work

1. Produce `P1-A0`, a checked-in migration map that classifies every current
   `run_mcp_workflow.workflow` value as one of: public-typed, public
   compatibility, local-advanced, or retired-with-handoff. It names owner
   module, exact input/output contract, authority scope, and regression test.
2. Extract workflow registration/schema, response shaping, Commander projection,
   manifest/artifact reads, and workflow-family dispatch into focused
   `runner/mcp_*.py` modules. Existing extracted modules are reused rather than
   wrapped a second time.
3. Make public `run_mcp_workflow` a compact compatibility/orchestration tool.
   New ChatGPT guidance uses typed tools first; legacy workflow values receive
   one bounded compatibility path or a copyable local-Codex handoff, never a
   hidden alternate implementation.
4. Keep the public nine tools exact. Git remains in `manage_git`, validation in
   `manage_validation_run`, independent review in `review_manifest`, and large
   result recovery in `read_result_artifact`.

### Exit gate

- `mcp_server.py` is at or below the 9k-line target;
- every migrated workflow has one authoritative implementation and one migration
  map entry;
- old/public-typed equivalence and denial paths are covered by targeted tests;
- public schemas, scopes, preview/apply binding, and context binding do not
  widen; and
- full pytest, self-hosting smoke, compileall for touched Python, Ruff, and
  `git diff --check` pass.

### Adopted P1-A composition boundary

- `runner/mcp_tool_catalog.py` owns declarative MCP input/output schemas, tool
  annotations, and the Stage-parallel/context-binding schema fragments.
- `runner/mcp_server.py` composes that catalog, adds the existing Work Item
  definitions, and applies frozen exposure-profile checks; it does not recreate
  catalog data.
- `runner/commander_widget.html` is packaged application data loaded through
  `runner/commander_widget.py`, while the existing `ui://colameta/commander/v1.html`
  URI and widget response bytes remain stable.
- `runner/mcp_commander_app.py` owns the Commander/ChatGPT product domain:
  manifests, readiness/product-console projections, submission-evidence views,
  and client-flow assembly. `MCPPlanningBridgeServer` inherits that domain while
  retaining transport, registry, policy, and explicit compatibility composition.
  The old server-module dependency-injection seam remains deliberate and tested
  so this ownership move does not change focused integration behavior.

This is an internal ownership split only. It does not change the nine public
tools, scopes, authorization boundaries, connector configuration, or release
authority.

## P1-B — Make Current Facts A Real Product Artifact

### Target

`canonical_project_state` is the only composition input for a current-facts
artifact. Source collectors still own Git, Runner, runtime, and connector
observation; the canonical projection does not impersonate those sources.

### Required work

1. Generate a redacted, versioned Markdown/JSON snapshot under
   `.colameta/reports/current-facts/`. Each snapshot records `observed_at`,
   per-source observation state, freshness conclusion, canonical-state digest,
   and the statement that it grants no authority.
2. Return the snapshot through an existing read-only typed result/artifact path;
   do not create a new public tool. A tracked-document update is available only
   as an explicit docs preview/apply flow and may never overwrite a historical
   receipt or protected taskbook.
3. Add deterministic fixture tests for fresh, stale, partial, not-observed, and
   conflicting Git/Runner/runtime/connector evidence. Test that no secret-like
   fields or ignored raw runtime content enter the projection.

### Exit gate

- identical fixture inputs produce byte-identical current-facts artifacts;
- every artifact has source observation timestamps, a canonical digest, and an
  explicit freshness/authority boundary;
- stale or missing external evidence yields `freshness_required` or `partial`,
  never a healthy/release conclusion; and
- artifact generation cannot write tracked documentation without a separately
  confirmed docs preview/apply action.

### Adopted P1-B current-facts boundary

- `runner/mcp_current_facts.py` owns the bounded `current_facts` state machine
  behind the existing `run_mcp_workflow` compatibility surface: `inspect`,
  `preview`, and context-bound `apply`. The nine public tools remain exact.
- `runner/current_facts_artifact.py` accepts only
  `canonical_project_state`, rejects secret/path-like keys, and renders one
  redacted JSON/Markdown pair with exact canonical, semantic, and snapshot
  SHA-256 fields. It never reads raw runtime state, project source, receipt, or
  taskbook content to construct the artifact.
- `inspect` and `preview` package the snapshot through the existing typed
  `read_result_artifact` recovery contract. Preview is process-local and
  short-lived; it makes no archive directory and does not dirty the checkout.
- `apply` re-observes semantic state before writing the exact previewed pair.
  A changed state returns `CURRENT_FACTS_PREVIEW_STALE`; absent Git-ignore
  coverage returns `CURRENT_FACTS_ARCHIVE_NOT_IGNORED`. The fixed archive is
  `.colameta/reports/current-facts/`, never a caller-selected or tracked docs
  path.
- Deterministic fixtures cover fresh, stale, partial, not-observed, and
  Git/Runner-conflict projections. The artifact remains observation-only even
  when a local archive write has been explicitly confirmed.

## P1-C — Turn Stage 7--9 Into One Fail-Closed Preview Journey

### P1-C0 implementation gate

Before code changes, create one exact Stage 7--9 integration manifest: allowed
files, current schema/hash bindings, input fixtures, public entry point, and
negative cases. The manifest must bind the work to the existing Stage taskbooks
without claiming that those taskbooks themselves grant implementation authority.

### Target

Use the existing read/preview capabilities to provide one bounded journey:

```text
Stage 7 drift evidence
  -> Stage 8 PLAN_ADJUST preview
  -> Stage 9 continue-readiness report
```

The public entry stays within the nine-tool contract, using the compact
`run_mcp_workflow` compatibility/orchestration surface where necessary. Rich
diagnostics remain local-Codex/advanced-only. No part of the journey may apply
a plan, continue a version, run an executor, create a ReviewDecision, mutate
Delivery State, commit, or push.

### Exit gate

- one fixture matrix proves valid and invalid Stage 7 -> 8 -> 9 handoffs;
- all context/hash/authority omissions return named fail-closed blockers;
- all side-effect paths are tested denied; and
- the public projection identifies the next human decision without leaking
  private runtime data or presenting a semantic drift verdict as fact.

## P1-D — Deliberately Different Client Experiences And A Hard Release Gate

### Client contract

ChatGPT receives the compact nine-tool Commander contract, typed read/preview
continuations, short next actions, and recoverable result handles. Local Codex
and the loopback advanced endpoint retain rich executor packets, deep diagnostics,
and migration handoffs. The two surfaces share canonical state, scope, context,
and authority semantics; they do not share oversized payloads by default.

### Development acceptance

Every changed public contract is accepted in a fresh ChatGPT development
connector session with:

1. exact nine-tool discovery;
2. deliberate `CONTEXT_BINDING_MISMATCH` negative coverage;
3. manifest inspect/read/verify and declared-subject hash continuity;
4. packaged-result artifact recovery across all pages with stable SHA/expiry;
   and
5. proof that ChatGPT does not depend on unavailable `resources/read` support.

### Hard release blockers

A release decision packet is `blocked` unless all of the following are true:

- full required local validation is green;
- the public endpoint's runtime provenance verifies the intended commit rather
  than reporting `unverified` or `reload_needed_for_verification`;
- fresh connector/OAuth reachability evidence and exact nine-tool discovery are
  present without exposing credentials;
- the current-facts artifact is fresh and has no unresolved critical blocker;
- the fresh ChatGPT acceptance above passes; and
- the decision packet names a separately authorized stable-replacement target.

Preparing this packet changes no service. Executing a stable replacement still
requires a new explicit instruction.

## Delivery Cadence

P1-A, P1-B, P1-C, and P1-D are sequential product gates, but work inside each
batch is driven to the exit gate without waiting for unrelated cleanup. Each
batch has an exact file list, acceptance commands, negative tests, docs update,
and one local commit only after the entire vertical slice is green. A discovered
scope expansion becomes a new bounded subtask, not hidden work inside the batch.

P1 is complete only when all four exit gates pass, the public nine-tool contract
is stable, legacy routing has either an explicit retained boundary or a tested
retirement path, and the P1-D decision packet is ready. That readiness never
equals stable replacement without a new explicit authorization.
