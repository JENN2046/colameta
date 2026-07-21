# Commander Convergence Taskbook

```yaml id="commander-convergence-taskbook-metadata"
commander_convergence_taskbook:
  schema_version: commander_convergence_taskbook.v1
  document_type: product_and_engineering_taskbook
  status: reviewed_first_slice_scoped
  authority_status: planning_reference_only
  generated_at: 2026-07-21
  workspace: /home/jenn/src/colameta-dev
  branch_at_draft: main
  head_at_draft: 31a46757943de575d086002174c5a0e2059df17a
  implementation_authority: false
  commit_authority: false
  push_authority: false
  release_authority: false
  stable_replacement_authority: false
```

## 1. Executive Decision

ColaMeta's seven-tool private Commander surface has demonstrated a reliable
non-destructive governance boundary. The next product milestone is not an
eighth tool or a broader authority surface. It is a convergence pass that makes
the existing seven tools speak one decision language and present a smaller,
clearer operator view.

This taskbook freezes the public tool count at seven and defines one contract
gate plus six convergence work items:

1. CC-0 freezes the contradictory cases as red-to-green contract fixtures;
2. CC-1 creates one canonical executor-continuation decision;
3. CC-2 adds explicit observed/draft/simulated/placeholder evidence provenance;
4. CC-3 separates health and readiness axes rather than using one lossy status;
5. CC-4 keeps read-only inspection out of execution-packet flows;
6. CC-5 makes the Commander summary compact with diagnostics on demand; and
7. CC-6 applies one shared generated/cache-file exclusion policy.

This document is a planning draft. It does not authorize implementation,
executor dispatch, validation execution, commit, push, release, deployment,
stable replacement, service restart, ReviewDecision, GateEvent, or Delivery
State mutation.

## 2. User Evidence And Problem Statement

A real private-App session exercised all seven public tools without destructive
actions:

| Step | Tool | Observed outcome |
| --- | --- | --- |
| Project discovery | `list_registered_projects` | Registered projects were discoverable. |
| Project analysis | `analyze_project_state` | Git, plan, Runner, and executor facts were useful. |
| Commander | `render_commander_app` | The panel rendered, but the default information set was too broad. |
| Connector smoke | `get_apps_connector_smoke_packet` | Apps reachability was proved while external closeout evidence remained incomplete. |
| Governed workflow | `run_mcp_workflow` | A read-only thin-loop draft was produced, but a read-only intent was forced through an execution-oriented contract. |
| Validation | `manage_validation_run` | Three commands were frozen behind a confirmation-bound `preview_id`. |
| Git review | `manage_git` | Review context was sufficient, but cache files polluted the repository overview. |

No executor run, validation run, file mutation, ReviewDecision, GateEvent,
Delivery State mutation, commit, or push occurred. The validation flow stopped
correctly at `can_run=true` and `requires_confirmation=true`.

The central product finding is:

> Governance and mistake prevention are credible, but decision semantics and
> information architecture have not converged into a lightweight Commander.

The session report is user-provided first-hand product evidence. The following
current-source anchors independently support the identified implementation
risks; they do not reproduce the live ChatGPT session:

| Concern | Current source anchor |
| --- | --- |
| Continuation recommendation is derived in more than one place | `runner/executor_session.py` (`classify_executor_session_head_mismatch`, `get_continuation_decision`) and `runner/core_orchestrator.py` (`_thin_loop_executor_session_guidance`) |
| Draft objects can contain execution-like simulated values | `runner/core_orchestrator.py` (`_thin_loop_reset_draft_task_evidence`, `_thin_loop_apply_draft_seed`) |
| Connector closeout is collapsed into `ready` or `needs_attention` | `runner/runtime_observability.py` (`build_apps_connector_closeout_packet`) |
| Commander status and initial payload aggregate many domains | `runner/mcp_server.py` (Commander manifest construction) |
| Repository overview omits some cache exclusions used elsewhere | `runner/source_review_bridge.py`, `runner/file_policy_rules.py`, and `runner/work_item_governance/source_binding.py` |

## 3. Product Goal

After this convergence work, a project owner should be able to answer four
questions from the first Commander response without understanding internal
governance vocabulary:

1. Is the project healthy?
2. What exact item needs attention or blocks progress?
3. What is the recommended next action?
4. Will that action read, preview, run, write, commit, push, or change an external system?

The detailed governance objects remain available for diagnostics and audit, but
they must not dominate the default decision surface.

## 4. Non-Goals

- Do not add an eighth public Commander tool.
- Do not weaken preview IDs, confirmation gates, authority checks, private-auth
  checks, Work Item Gate rules, Git gates, or stable-replacement rules.
- Do not merge project health, local runtime health, Apps reachability, external
  connector closeout, validation readiness, and delivery readiness into one
  replacement boolean.
- Do not redesign the entire visual language or replace the existing widget
  technology in this convergence pass.
- Do not introduce a new workflow engine, state store, taskbook platform, or
  external service.
- Do not treat draft or simulated evidence as execution proof.
- Do not modify stable services, external connector configuration, OAuth,
  tunnel, DNS, or provider configuration under this taskbook alone.
- Do not publish, release, tag, or deploy under this taskbook alone.

## 5. Target Product Contract

### 5.1 Compact Commander summary

Every public Commander flow should have a small decision projection shaped like:

```json
{
  "project_health": "healthy",
  "primary_attention": {
    "domain": "external_connector_evidence",
    "status": "unverified",
    "blocks_current_task": false
  },
  "recommended_next_action": {
    "label": "Inspect project status",
    "tool": "analyze_project_state",
    "effect": "read"
  },
  "authority": {
    "state": "not_required_for_read",
    "authorized": true,
    "authorization_source": "read_only_tool_contract"
  },
  "details_available": true
}
```

Exact field names may change during implementation review, but the four operator
questions and non-lossy domain separation are acceptance requirements.

### 5.2 Effect vocabulary

All recommended actions exposed to the private App must use one user-visible
effect vocabulary:

```text
read | preview | run | write | commit | push | external_change
```

`requires_confirmation` remains a separate fact. A read-only action must never
be described using run/write language, and a preview must never be described as
completed execution.

Authority is also a mandatory first-class summary fact; it must not be hidden in
diagnostic details. `requires_confirmation` does not mean an action is already
authorized. When the current action-specific authority is absent, a mutation
effect (`run`, `write`, `commit`, `push`, or `external_change`) may recommend only
a read/preview step or an operator authorization handoff. It must not expose a
copyable mutation call as the immediately authorized next action.

### 5.3 Evidence provenance vocabulary

Objects that can be mistaken for execution or review evidence must carry:

```text
evidence_kind = observed | draft | simulated | placeholder
evidence_subject = execution | validation | review | hash_binding | read_only_observation
subject_requires_execution = true | false
subject_operation_completed = true | false
execution_performed = true | false
eligible_for_acceptance = true | false
```

Only observed evidence backed by a completed operation may set
`execution_performed=true`. Draft mode must not emit unqualified `executed`,
`passed`, or zero-exit-code claims that look like observed execution.

The fail-closed truth table is:

| `evidence_kind` | Subject rule | `execution_performed` | `eligible_for_acceptance` | Rule |
| --- | --- | --- | --- | --- |
| `draft` | Any subject | `false` | `false` | Always non-executed and non-acceptable. |
| `simulated` | Any subject | `false` | `false` | Expected/example results are never execution proof. |
| `placeholder` | Any subject | `false` | `false` | Missing or operator-fillable content is never acceptance evidence. |
| `observed` | Execution required but not completed | `false` | `false` | Cannot prove the required execution. |
| `observed` | Non-execution subject completed | `false` | `true` may be allowed | Only for a completed review, hash binding, or read-only observation when every applicable source, task/version, digest/binding, integrity, freshness, and authoritative-validator check passes. |
| `observed` | Execution completed, proof incomplete/conflicting | `true` | `false` | Completed execution remains ineligible when any applicable check is missing or conflicting. |
| `observed` | Execution completed, proof complete | `true` | `true` may be allowed | Allowed only when every required binding and existing authoritative validator passes; eligibility still does not mean accepted. |

`evidence_subject`, `subject_requires_execution`, and
`subject_operation_completed` are validator-derived facts, not trusted caller
claims. An incoming envelope may carry `claimed_*` values for comparison, but
the authoritative validator must derive the returned values from the bound
object/path, schema, and authoritative operation/binding record. The fixed v1
mapping is `execution` and `validation` -> requires execution; `review`,
`hash_binding`, and `read_only_observation` -> does not require execution.
Operation completion must come from bound evidence, not a request boolean. An
unknown subject, path/schema mismatch, subject downgrade, false non-execution
claim, or completion mismatch makes `eligible_for_acceptance=false` and fails
the acceptance-aware path closed.

Unknown kinds, missing provenance required by the new contract, and conflicting
provenance fail closed. Existing legacy provided-mode objects remain readable and
parseable for compatibility, but must report
`provenance_status=legacy_unclassified`, `eligible_for_acceptance=false`, and
cannot create a new acceptance, ReviewDecision, GateEvent, or Delivery State
mutation. A legacy object must be rebound through the versioned provenance
envelope and current validators before it can enter a new acceptance-aware path.

## 6. Work Items

### CC-0 — Contract Fixture Freeze

Priority: `P1 prerequisite`

Problem: the current contradictory recommendations and draft-evidence ambiguity
must be frozen once, using shared facts, before CC-1 and CC-2 change behavior.

Required outcome:

- Define deterministic fixtures that do not read ignored runtime/private state.
- Reuse each continuation fixture across session decision, Web/status,
  analyze-state, invocation-preview, and thin-loop assertions where applicable.
- Reuse each provenance fixture across draft generation and the authoritative
  receipt, validation-truth, and review-feedback validators where applicable.
- Record the pre-fix contradiction as the red phase inside the implementation
  work; no failing test may remain in the final worktree or closeout.
- Complete the same fixtures green after CC-1 and CC-2.

Mandatory fixtures:

| Fixture | Facts | Final required result |
| --- | --- | --- |
| `CONT-01` | Same HEAD, matching provider/identity, verified resume support, no blockers | `resume` may be recommended. |
| `CONT-02` | Completed idle historical session, current HEAD advanced, clean worktree | `start_new`; resume forbidden. |
| `CONT-03` | HEAD mismatch with a live/possibly live operation | `human_review`; resume and start both forbidden. |
| `CONT-04` | HEAD mismatch with incomplete operation/job/run/Runner/worktree facts | `inspect_evidence`; resume and start both forbidden. |
| `CONT-05` | No session, provider mismatch, identity missing, or resume unsupported | `start_new` with the exact reason; never pretend resume is available. |
| `PROV-01` | Draft seed contains allowed files and validation commands | Packet may be ready for future work, but receipt remains not-run and non-acceptable. |
| `PROV-02` | Draft contains default review/hash placeholders | Placeholders are labelled and non-acceptable. |
| `PROV-03` | Simulated or placeholder evidence is supplied to an acceptance-aware path | Fail closed; never accepted as observed evidence. |
| `PROV-04` | Completed, fully bound observed review/hash/read-only evidence | `execution_performed=false`; eligibility may be true, but acceptance is not implied. |
| `PROV-05` | Completed, fully bound observed execution/validation evidence | `execution_performed=true`; eligibility may be true, but acceptance is not implied. |
| `PROV-06` | Caller downgrades execution/validation to non-execution, changes subject/path, or claims unproved completion | Fail closed with `eligible_for_acceptance=false`. |

Red-to-green rule: the initial red result is implementation evidence only. The
slice cannot be closed, committed, or promoted while any required fixture or
existing regression test is failing.

### CC-1 — Canonical Executor Continuation Decision

Priority: `P1`

Problem: executor-session analysis already has a HEAD-mismatch classifier, but
different surfaces derive recommendations independently. The same stale session
can therefore produce both `resume` and `start_new` recommendations.

Required outcome:

- Define one pure canonical continuation-decision builder owned by
  `runner/executor_session.py` and consumed, not re-derived, by other surfaces.
- Accept one explicit fact bundle containing session/current HEAD,
  operation-running, job, latest run/claim, Runner/version, worktree, provider,
  identity, and resume-support facts.
- Make the HEAD-mismatch classifier and the fact bundle authoritative inputs.
- Include at least `classification`, `resume_allowed`, `start_new_allowed`,
  `recommended_action`, `reason`, `severity`, and `decision_source`.
- Make Web/status, `analyze_project_state`, thin-loop packets, executor invocation
  previews, and Commander summaries project the same canonical object rather
  than re-deriving a decision after different facts have been gathered.
- Preserve the stricter result if evidence is incomplete or an active operation
  may be running.

Canonical v1 values:

```text
classification = no_session | resume_eligible |
  completed_idle_stale_session | active_operation_head_mismatch |
  head_evidence_incomplete | provider_or_identity_mismatch | resume_unsupported
recommended_action = resume | start_new | inspect_evidence | human_review
```

No surface may use `null`, a free-form synonym, or a second recommendation field
to override `recommended_action`. Conflict priority is fail-closed:

1. active or possibly active mismatch -> `human_review`;
2. incomplete comparison/operation evidence -> `inspect_evidence`;
3. completed stale session, no session, provider/identity mismatch, or unsupported
   resume -> `start_new` with the exact classification/reason;
4. only fully verified same-session facts -> `resume`.

Acceptance examples:

| Situation | Required decision |
| --- | --- |
| Same HEAD, matching provider and verified identity, no blockers | Resume may be recommended. |
| Completed idle historical session, current HEAD advanced, clean worktree | Start new; auto-resume is not allowed. |
| HEAD mismatch while an operation may be running | Block automatic resume and automatic start; require human review. |
| HEAD evidence incomplete | Do not guess; return an evidence blocker. |

### CC-2 — Evidence Provenance And Draft Truthfulness

Priority: `P1`

Problem: thin-loop draft generation can place simulated `executed`, `passed`,
and `exit_code=0` values inside an outer object that states no execution occurred.
The outer boundary is correct, but the nested semantics are easy to misread.

Required outcome:

- Add evidence provenance to execution receipts, validation results, review
  feedback drafts, hashes, and generated placeholders where ambiguity exists.
- Bind the contract to the current authoritative validators in
  `runner/local_execution_receipt.py`, `runner/validation_truth.py`, and
  `runner/review_feedback_schema.py`; presentation-only labels are insufficient.
- Derive subject, execution requirement, and completion from the bound
  object/path/schema and authoritative records; never trust caller flags.
- Draft input generation must keep execution and validation states explicitly
  not-run.
- If expected results are useful for examples, place them in a separately named
  `simulated_expectation` or schema-example section that is ineligible for
  acceptance.
- Default review placeholders such as `NEEDS_FIX` must be labelled as examples
  or omitted from observed summaries.
- Public projections must keep observed facts separate from draft artifacts.

For compatibility, the first slice uses a versioned transport-level sibling
`evidence_provenance` envelope rather than replacing existing v1 object fields or
changing scalar hash fields. Envelope entries identify the referenced object or
JSON field path, evidence subject, whether that subject requires execution,
subject-operation completion, evidence kind, execution fact, eligibility fact,
and verified binding state. A review hash remains a scalar SHA-256 value; its
provenance is a sibling entry, not a new hash-object shape. Existing legacy
provided-mode inputs without the envelope are labelled `legacy_unclassified`;
they remain read/parse compatible but cannot produce new acceptance or state
mutation until rebound and verified.

### CC-3 — Multi-Axis Health And Readiness

Priority: `P1`

Problem: `needs_attention` can be correct for connector closeout while looking
like a project or local-runtime failure when placed in the top status line.

Required outcome:

- Preserve separate status axes for:
  - project health;
  - local runtime health and freshness;
  - Apps tool-call reachability;
  - external connector/tunnel evidence;
  - current-task readiness; and
  - delivery/release readiness when relevant.
- A missing external closeout receipt must not silently downgrade project health.
- The top summary must name the affected domain and whether it blocks the
  current requested task.
- `ready`, `needs_attention`, and `blocked` may remain domain statuses, but a
  single scalar must not erase healthier component facts.

Required matrix tests include healthy project/runtime with unverified external
evidence, degraded local runtime, unreachable Apps calls, and a task-specific
blocker independent of connector closeout.

### CC-4 — Read-Only Intent Router

Priority: `P1`

Problem: ordinary users can express read-only analysis by sending empty
execution arrays or unsupported review values. The system safely refuses to run,
but only after generating a large execution-oriented draft.

Required outcome:

- Detect explicit inspect/status/review-only intent before thin-loop execution
  packet construction.
- Route that intent to the existing project-status or source-observation path.
- Do not generate execution receipts, Codex execution packets, allowed-file
  blockers, or validation-command blockers for a task that does not seek execution.
- When incompatible fields are supplied, return a short explanation and a
  copyable safe request shape.
- Keep execution intent strict: a runnable packet still requires bounded files,
  commands, validation, tier, and applicable authority gates.

### CC-5 — Compact-First Commander Information Architecture

Priority: `P2`

Problem: the default Commander result includes many useful but secondary
sections, which obscures the current decision.

Required outcome:

- Make the compact summary the default public/private-App projection.
- Keep the default surface focused on project health, primary attention,
  recommended next action, effect, and confirmation requirement.
- Move stable cadence, submission readiness, domain projections, profile
  details, parallel-stage controls, fallback transport guidance, and authority
  diagnostics behind explicit detail reads or expandable sections. Only detailed
  authority diagnostics move behind details; the mandatory authority summary
  remains on the default surface.
- Preserve operational continuation identifiers such as `preview_id` and
  `run_id` when the user needs them for the next call.
- Define and test a bounded public payload budget without truncating copyable
  confirmation-bound requests.
- Continue to expose exactly seven public tools.

### CC-6 — Shared Repository Overview Exclusion Policy

Priority: `P2`

Problem: source review, execution overlay checks, and repository overview do not
consume one complete generated/cache exclusion set. Cache files can consume the
bounded file-tree quota.

Required outcome:

- Define one reusable generated/cache exclusion policy.
- Apply it to repository overview traversal and every other user-facing file
  inventory where the same semantics apply.
- At minimum cover `.ruff_cache`, `.pytest_cache`, `__pycache__`, `.mypy_cache`,
  virtual environments, build/dist output, egg-info, coverage output, and
  language/vendor caches already denied elsewhere.
- Keep security-sensitive deny rules distinct from low-value cache exclusions
  in diagnostics, while ensuring both are excluded from the default tree.
- Ensure excluded entries do not consume `max_files`.

## 7. Implementation Order And First Slice

```text
CC-0 contract fixtures
  -> CC-1 canonical continuation decision
  -> CC-2 evidence provenance
  -> CC-3 multi-axis status
  -> CC-4 read-only intent router
  -> CC-5 compact-first projection
  -> CC-6 shared exclusions and documentation closeout
```

CC-0 is an independently auditable red-to-green contract gate, not permission to
deliver failing tests. CC-1 through CC-3 are semantic foundations. CC-4 and CC-5
consume those foundations. CC-6 may be implemented independently after the
baseline fixtures exist.

### 7.1 First implementation slice — `CC-S01`

```yaml id="commander-convergence-first-slice"
first_implementation_slice:
  slice_id: CC-S01
  status: reviewed_scope_ready_for_authorization
  includes:
    - CC-0_contract_fixture_freeze
    - CC-1_canonical_executor_continuation_decision
    - CC-2_evidence_provenance_and_draft_truthfulness
  defers:
    - CC-3_multi_axis_health_and_readiness
    - CC-4_read_only_intent_router
    - CC-5_compact_first_commander_information_architecture
    - CC-6_shared_repository_overview_exclusion_policy
  implementation_authority: false
  validation_run_authority: false
  commit_authority: false
  push_authority: false
  stable_replacement_authority: false
```

Slice outcome:

- eliminate the contradictory resume/start-new recommendation at its shared
  decision source;
- make draft/simulated/placeholder evidence unambiguously non-executed and
  non-acceptable through authoritative validation semantics; and
- finish with all CC-0 fixtures and existing regressions green.

The slice explicitly does not change the top-level `needs_attention` model,
read-only intent routing, Commander information architecture, cache filtering,
tool count, stable runtime, connector configuration, or visual design. The only
Commander projection change permitted in this slice is the canonical-decision
and provenance/authority pass-through required to prove CC-1 and CC-2.

Expected primary implementation surface for the later exact implementation gate:

```text
runner/executor_session.py
runner/web_console.py
runner/core_orchestrator.py
runner/thin_governed_loop.py
runner/local_execution_receipt.py
runner/validation_truth.py
runner/review_feedback_schema.py
runner/mcp_server.py
runner/commander_projections.py
tests/test_executor_session_head_mismatch.py
tests/test_thin_governed_loop.py
tests/test_local_execution_receipt.py
tests/test_validation_truth.py
tests/test_review_feedback_schema.py
tests/test_mcp_runtime_observability.py
tests/test_mcp_commander_exposure_profile.py
```

This list is the reviewed candidate surface, not current write authorization. If
implementation proves that a persisted schema migration or any file outside this
candidate surface is required, stop and re-review/rebind the slice instead of
expanding it automatically.

Slice-specific validation gates:

| Gate | Required proof |
| --- | --- |
| CC-0 red record | The pre-fix contradiction is demonstrably captured, but no intentionally failing test remains in the final tree. |
| CC-1 cross-surface consistency | `CONT-01` through `CONT-05` produce one canonical decision across session, Web/status, analyze, invocation, thin-loop, and Commander surfaces. |
| CC-1 fail-closed priority | Active/uncertain evidence cannot be weakened by cache preference, provider preference, or a later projection. |
| CC-2 provenance envelope | The sibling envelope is versioned, path-bound, does not change scalar hash shapes, and survives the Commander projection where applicable. |
| CC-2 acceptance negatives | Draft, simulated, placeholder, unknown, conflicting, stale, incompletely bound, subject-downgraded, path-mismatched, or completion-mismatched evidence always reports ineligible. |
| CC-2 non-execution positive | Fully validated completed review/hash/read-only evidence may be eligible with `execution_performed=false`; execution/validation subjects cannot use this branch. |
| CC-2 compatibility | Existing v1 objects remain read/parse compatible, are never silently relabelled provenance-verified, and cannot create new acceptance or state mutation until rebound. |
| Regression | Targeted modules, Commander seven-tool contract, compileall, full pytest, self-hosting smoke, and `git diff --check` pass. |

`CC-S01` is locally complete only when every gate above is green, the public tool
count remains seven, no CC-3 through CC-6 behavior has been smuggled into scope,
and a closeout records both new semantics and compatibility results. Local slice
completion still does not authorize commit, push, stable replacement, restart,
or live private-App mutation.

## 8. Expected Implementation Surface

The following paths are likely in scope, subject to a later exact implementation
authorization and source inspection:

```text
runner/executor_session.py
runner/web_console.py
runner/core_orchestrator.py
runner/thin_governed_loop.py
runner/local_execution_receipt.py
runner/validation_truth.py
runner/review_feedback_schema.py
runner/runtime_observability.py
runner/commander_projections.py
runner/mcp_server.py
runner/source_review_bridge.py
runner/file_policy_rules.py
tests/test_executor_session_head_mismatch.py
tests/test_thin_governed_loop.py
tests/test_local_execution_receipt.py
tests/test_validation_truth.py
tests/test_review_feedback_schema.py
tests/test_runtime_observability.py
tests/test_mcp_runtime_observability.py
tests/test_mcp_commander_exposure_profile.py
docs/commander-public-response-minimization.md
docs/web-gpt-service-entrypoint.zh-CN.md
docs/ONBOARDING.md
docs/ONBOARDING.zh-CN.md
```

This is an anticipated surface, not a write allowlist. The implementation gate
must bind an exact, reviewed file list before edits begin.

## 9. Validation Matrix

| Gate | Required proof |
| --- | --- |
| Continuation consistency | The same fixture produces the same recommendation and permissions across session, Web/status, analyze, thin-loop, invocation preview, and Commander. |
| Active mismatch safety | Active or uncertain HEAD mismatch never auto-resumes or auto-starts. |
| Draft truthfulness | Draft generation contains no observed execution/pass claims and cannot satisfy acceptance evidence. |
| Provenance schema authority | Receipt, validation-truth, and review-feedback validators enforce the truth table; projection labels alone cannot make evidence eligible. |
| Read-only routing | An explicit inspect/review-only task returns a project-status path without an execution packet. |
| Strict execution contract | Runnable packets still reject empty files, missing validation, invalid tiers, and insufficient authority. |
| Status separation | Healthy project/runtime plus missing external evidence remains visibly healthy in those domains and names the evidence gap separately. |
| Compact projection | Default Commander output answers the four operator questions, always preserves the mandatory authority summary, rejects unauthorized mutation as an immediate next call, and omits secondary diagnostic inventories. |
| Continuation tokens | Required `preview_id`, `run_id`, and confirmation-bound payloads survive minimization intact. |
| File-tree hygiene | Cache/generated paths are absent and do not consume `max_files`. |
| Seven-tool invariant | The private Commander profile exposes exactly the existing seven tools. |
| Private service/auth | Existing service-mode and private-auth positive and negative paths remain covered. |
| Regression | Targeted tests, compileall, full pytest, self-hosting smoke, and `git diff --check` pass. |

## 10. Definition Of Done

The convergence work is locally ready only when all of the following are true:

- CC-0 and all six convergence work items meet their acceptance criteria;
- no surface gives a conflicting continuation recommendation for the same facts;
- draft/simulated objects cannot be mistaken for observed execution evidence;
- top-level presentation identifies the affected status domain and task impact;
- explicit read-only tasks avoid execution-packet construction;
- the default Commander response is compact while required follow-up IDs and
  copyable requests remain intact;
- repository overview excludes low-value cache/generated files;
- the public tool count remains seven;
- targeted and full regression validation passes in the approved local
  environment; and
- user/operator documentation is updated to the final contract.

Local readiness does not imply stable-runtime readiness. Stable replacement and
live private-App revalidation require a separate exact-commit authorization.

## 11. Risks And Controls

| Risk | Control |
| --- | --- |
| Simplification weakens governance | Change projections and routing, not authority gates; retain negative-path tests. |
| One new aggregate hides component truth | Keep typed component statuses and task-impact facts. |
| Legacy consumers depend on large payloads | Limit compact-first behavior to the Commander projection; retain advanced/maintainer diagnostics unless separately reviewed. |
| Draft provenance breaks existing fixtures | Introduce versioned schema/projection changes and explicit compatibility tests. |
| Session consistency fix changes execution behavior | Test matching, stale-idle, active-mismatch, incomplete-evidence, and provider-mismatch cases before broad regression. |
| Payload minimization drops continuation IDs | Maintain an explicit operational-field allowlist and boundary tests. |
| Live App appears fixed before stable replacement | Report local and stable runtime status separately; require exact-commit replacement evidence. |

## 12. Delivery And Authority Boundary

This taskbook authorizes no implementation or delivery action. A later task may
separately authorize bounded local implementation and testing. Commit, push, PR,
merge, stable replacement, service restart, release, deployment, and live
private-App validation remain distinct authorization steps.

Current planning outcome:

```yaml id="commander-convergence-planning-outcome"
planning_outcome:
  taskbook_status: reviewed_first_slice_scoped
  recommended_next_gate: CC-S01_bounded_local_implementation_authorization_review
  may_implement_from_this_document_alone: false
  may_commit_from_this_document_alone: false
  may_replace_stable_from_this_document_alone: false
```

Independent taskbook review closeout:

```yaml id="commander-convergence-taskbook-review-closeout"
review_closeout:
  safety_and_authority_review: pass
  technical_implementability_review: pass
  usability_and_slice_clarity_review: pass
  remaining_blocker_high_medium_findings: 0
  first_slice: CC-S01
  first_slice_scope_confirmed:
    - CC-0
    - CC-1
    - CC-2
  implementation_authorized_by_review: false
```

## 13. Local Implementation Authorization, Review Remediation, And A2 Closeout

The taskbook itself remains non-authorizing. Jenn subsequently issued explicit
bounded-local authorization for `CC-S01`, `CC-S01-A1`, and `CC-S01-A2`. Those
instructions authorized implementation and local validation only; they did not
authorize commit, push, PR, merge, stable replacement, restart, publish, or
deployment.

`CC-S01-A2` added one provider-aware continuation snapshot per request and a
project-scoped POSIX shared/exclusive operation lease. Web v2, Analyze,
Thin-loop, Commander, agent dispatch, MCP executor status, run-once, bounded
execution, Codex, and OpenCode now consume the same captured continuation facts
instead of independently deriving continuation recommendations. The lease is
held on the existing canonical project-root directory descriptor, so read-only
snapshot collection creates no project files.

The first combined CC-S01/A1/A2 closeout review then found four defects that
invalidated the initial ready claim: provider projection could widen captured
resume-capability facts, the Chinese companion hash had drifted, a non-string
`evidence_kind` could raise instead of failing closed, and a versioned
provenance envelope could omit validator-owned subjects. The bounded local
remediation now preserves explicit false capability facts, rejects malformed
evidence kinds, requires complete provenance subject coverage, exercises
CONT-01 through CONT-05 across Session, Analyze, Thin-loop, Web, Invocation,
and Commander projections, and documents snapshot/lease operation for users
and operators. Final ordered validation and independent re-review have now
passed and are the evidence for the ready state below.

Local closeout evidence:

```yaml id="commander-convergence-cc-s01-a2-local-closeout"
cc_s01_a2_local_closeout:
  status: ready
  independent_reviews:
    technical: pass
    safety: pass
    usability_and_test_evidence: pass
  remaining_p0_p1_p2_findings: 0
  targeted_regression: 244_passed_84_subtests
  full_pytest: 1915_passed_2_skipped_139_subtests
  self_hosting_smoke: passed
  compileall: passed
  ruff_check: passed
  diff_check: passed
  final_project_and_venv_bytecode_count: 0
  commit_authorized: false
  push_authorized: false
  stable_replacement_authorized: false
```
