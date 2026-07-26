# P1 Convergence Execution Baseline

```yaml id="p1-convergence-execution-baseline-metadata"
p1_convergence_execution_baseline:
  schema_version: colameta.p1_convergence_execution_baseline.v2
  document_type: bounded_execution_plan
  status: p1_e_implementation_verified_fresh_development_acceptance_pending
  authority_status: planning_reference_only
  created_at: 2026-07-24
  revision: 9
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
  reconciliation:
    observed_at: 2026-07-25
    observed_implementation_head_before_reconciliation_edit: 05575ad90cd40f44819aed31dda185ec7aa5c1f8
    implementation_scope: p1_a_through_p1_e_local_convergence
    exact_candidate_validation_status: not_claimed_requires_clean_candidate_revalidation
    fresh_development_acceptance_status: pending
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

### Adopted P1-C0 integration binding

`docs/taskbooks/P1_C_STAGE_7_9_INTEGRATION_MANIFEST.md` is now the exact
implementation-binding manifest for this slice (baseline commit `eb35e8e`,
SHA-256 `bb16181ae45abedbf06ee4e68799a13e4adeb9c9142cf1b6063bd9d575e33519`).
It freezes the current Master/Stage 7/Stage 8/Stage 9 paths and hashes, limits
the public entry to `run_mcp_workflow workflow=stage_7_9_preview` with only
`inspect` and `preview` under `mcp:read`, and names a focused new domain owner
outside `mcp_server.py`. It requires an inspect-issued, rechecked journey
context; exact three-stage input objects; cross-stage pack-ID and taskbook-hash
continuity; a whitelist-only public projection; and named negative tests.

The canonical valid PLAN_ADJUST path is intentionally blocked at Stage 9 until
the human resolves Stage 8: `PLAN_ADJUST_BLOCKS_CONTINUE` is a correct safe
readiness conclusion, not an invitation to bypass the adjustment. The manifest
adds no public tool and grants no implementation authority to its taskbook
inputs.

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

### Adopted P1-C implementation closure

- `runner/mcp_stage_7_9_preview.py` is the focused composition owner. It calls
  the existing Stage 7 builder, Stage 8 preview, and Stage 9 readiness report;
  it does not duplicate their domain logic or add behavior to `mcp_server.py`.
- `run_mcp_workflow workflow=stage_7_9_preview` exposes only `inspect` and
  `preview` under `mcp:read`. Invalid side-effect phases intentionally reach
  the typed read-only handler and return
  `STAGE_7_9_PHASE_NOT_SUPPORTED`, not a misleading generic policy result.
- `inspect` returns an exact `stage_7_9_context`, including meaningful null
  values in source-only Runner facts. The public projection preserves that
  closed contract so an unchanged ChatGPT follow-up can be verified.
- `preview` verifies the frozen taskbook paths/hashes, all three bounded input
  objects, generated Stage 7-to-8 pack continuity, generated Stage 8-to-9
  preview continuity, and the false side-effect claims of every underlying
  Stage result. Its only successful PLAN_ADJUST conclusion is the blocked,
  human-decision-required Stage 9 state.
- The focused tests cover the valid route, public-result redaction, clean
  checkout behavior, missing/changed context, taskbook/input/hash mismatch,
  Stage 7/8/9 failure closure, and every declared side-effect phase.

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

### Adopted P1-D local implementation closure

- `runner/chatgpt_development_acceptance.py` now performs a temporary-fixture,
  in-process contract rehearsal of the exact nine-tool Commander surface. It
  proves the deliberate context-binding negative path, all-page hash-bound
  manifest review, all-page typed result-artifact recovery, clean-checkout
  behavior, and no `resources/read` dependency.
- The rehearsal is explicitly labelled `local_contract_rehearsal`; it never
  claims a live ChatGPT session, Connector/OAuth reachability, runtime
  provenance, stable replacement, or release authorization.
- Commander now preserves the complete safe artifact descriptor—including
  `expires_at`—on an initial current-facts packaged response as well as on its
  typed pages. This closes the first-page/continuation contract rather than
  requiring a client to guess an expiry.
- The advanced consumer contract now exposes the client-experience partition:
  the literal nine-tool Commander tuple and its typed reads versus the normal
  Local Codex advanced capability examples. No public tool was added.
- `p1_client_release_gate` is included in submission-readiness output but is a
  separately named release decision. It stays `blocked` until independently
  verified live evidence exists; a caller cannot promote it with a supplied
  assertion. `P1_D_CLIENT_RELEASE_GATE_MANIFEST.md` owns the exact local
  rehearsal and external-evidence boundary.

The local P1-D implementation gate is complete once the shared validation
ladder is green. The fresh live ChatGPT development-connector acceptance and
any stable-replacement decision remain intentionally external, separately
authorized follow-ups.

### P1-E controlled release-evidence closure

- `manage_p1_release_evidence` is a normal/loopback-only typed workflow. It
  accepts a closed, sanitized evidence shape through `preview -> apply`, binds
  all five P1 evidence groups to one exact candidate HEAD, and persists only a
  local ignored runtime receipt after explicit operator confirmation.
- `p1_client_release_gate` now evaluates the stored receipt rather than
  returning a static list of generic blockers. Each non-stable check is shown
  as passed, stale, or blocked. External ChatGPT/connector observations remain
  labelled operator-attested, never server-observed.
- The public Commander remains exactly nine tools. P1-E adds no public tool,
  does not alter Connector/Auth0/tunnel settings, and cannot replace stable.
- Even when the five evidence checks pass, the gate remains `blocked` with
  `EXPLICIT_STABLE_REPLACEMENT_AUTHORIZATION_REQUIRED` until Jenn separately
  authorizes an exact target through the stable-promotion boundary.

### 2026-07-25 governance reconciliation

The local implementation history observed immediately before this
documentation-only reconciliation reaches P1-E at
`05575ad90cd40f44819aed31dda185ec7aa5c1f8`. The implementation groups are:

- typed-read and runtime-convergence foundation: `25a9585` through `20ecb3b`;
- P1-A composition-root extraction: `4aef920` through `34a0382`;
- P1-B current-facts artifact workflow: `eb35e8e`;
- P1-C Stage 7--9 manifest and preview journey: `ddd2bea` through `7e18f29`;
- P1-D client release gate and continuity fix: `29b2bd4` through `5dd354a`;
  and
- P1-E release-evidence evaluation: `05575ad`.

This is an implementation-history reconciliation, not an exact-candidate
acceptance result. The documentation reconciliation commit is intentionally
outside the observed implementation HEAD, so the complete validation ladder
must be rerun on a clean exact candidate. Fresh public runtime provenance,
sanitized Connector/OAuth reachability, and a new ChatGPT development-
connector acceptance remain pending. No P0 closure, stable replacement,
external configuration, push, release, or deployment authority is created.

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
