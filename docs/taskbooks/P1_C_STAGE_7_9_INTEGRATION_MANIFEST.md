# P1-C0 Stage 7--9 Integration Manifest

```yaml id="p1-c-stage-7-9-integration-manifest-metadata"
p1_c_stage_7_9_integration_manifest:
  schema_version: colameta.p1_c_stage_7_9_integration_manifest.v1
  document_type: implementation_binding_manifest
  status: implementation_binding_active
  authority_status: implementation_scope_only
  created_at: 2026-07-24
  baseline_commit: eb35e8e17382624a1e2cdfd83c9b987578e0a359
  public_entry:
    tool: run_mcp_workflow
    workflow: stage_7_9_preview
    allowed_phases: [inspect, preview]
    required_scope: mcp:read
  forbidden_phases: [apply, apply_all, plan_apply, run, commit, execute]
  public_tool_count_change: false
  stable_replacement_authority: false
  connector_or_oauth_authority: false
```

## Purpose and boundary

This manifest binds the P1-C implementation of one read-only journey:

```text
Stage 7 bounded drift evidence
  -> Stage 8 PLAN_ADJUST preview
  -> Stage 9 controlled-continue readiness report
```

It converts no taskbook into implementation authority. The taskbooks below are
immutable planning inputs for this bounded slice. The slice may organize
evidence and name the next human decision; it may not declare semantic
alignment, apply a plan/taskbook mutation, start an executor, create a review
decision or GateEvent, alter delivery state, commit, push, replace stable, or
change Connector/OAuth configuration.

## Frozen inputs

The implementation must verify these exact references before composing a
preview. A mismatch fails closed and must not be silently refreshed or
normalized.

| Role | Path | SHA-256 |
| --- | --- | --- |
| Master governance input | `PROJECT_MASTER_TASKBOOK.md` | `1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34` |
| Stage 7 input | `docs/taskbooks/stages/STAGE_07_DRIFT_EVIDENCE_AND_CORRECTION.md` | `24cec5e48435254731cce4bb2e72c8810df3d041f57c142d5674d82a632cb142` |
| Stage 8 input | `docs/taskbooks/stages/STAGE_08_PLAN_ADJUSTMENT_CONTROL.md` | `60421ba765b238b9671f1f9baf878cf716c6e6e5cd05524bfa746610fd9a3755` |
| Stage 9 input | `docs/taskbooks/stages/STAGE_09_CONTROLLED_CONTINUE_AND_LONG_RUN_TRACE.md` | `5bfe6e4632748bd33f5a763963bc54b5e546bd3349ad536ec5b693522c7d696d` |

The compatibility surface must compose—not duplicate—the following existing
domain contracts at their frozen baseline contents:

| Contract | Path | SHA-256 |
| --- | --- | --- |
| Stage 7 schema | `runner/drift_evidence_schema.py` | `d956904c234d816fa55255464f2e4260db27fc56ffa066965bd2b03f442c716f` |
| Stage 7 builder | `runner/drift_evidence_pack_builder.py` | `f59870e70d4c728b1738ba32c60b0482e202b28778152046f85797ff050b1d48` |
| Stage 8 preview | `runner/plan_adjustment_preview.py` | `c56b3a24d301f07e173aa576e60b2cd5ddf74b8eb99b56c7310c030e9cbc5715` |
| Stage 9 report | `runner/controlled_continue_readiness.py` | `fd5bfc9f929be335d8607f4fa89f2bccd07dd00eb73b5dabf11884778c6e6f29` |

## Implementation allowlist

Only the following tracked files are in P1-C implementation scope. A new
focused module is mandatory; neither `mcp_server.py` nor a core orchestrator
may become a second owner of Stage 7--9 domain logic.

```text
runner/mcp_stage_7_9_preview.py
runner/mcp_workflow_compatibility.py
runner/mcp_tool_catalog.py
runner/mcp_workflow_policy.py
runner/mcp_workflow_migration.py
tests/test_mcp_stage_7_9_preview.py
tests/test_mcp_workflow_policy.py
tests/test_mcp_workflow_migration.py
tests/test_mcp_runtime_observability.py
tests/test_mcp_operation_context_binding.py
docs/USAGE.md
docs/USAGE.zh-CN.md
docs/taskbooks/P1_CONVERGENCE_EXECUTION_BASELINE.md
docs/taskbooks/P1_CONVERGENCE_EXECUTION_BASELINE.zh-CN.md
docs/taskbooks/P1_C_STAGE_7_9_INTEGRATION_MANIFEST.md
docs/taskbooks/P1_C_STAGE_7_9_INTEGRATION_MANIFEST.zh-CN.md
```

The following remain expressly out of scope: `PROJECT_MASTER_TASKBOOK*`, the
three Stage taskbooks above, tracked `.colameta/` planning state, any ignored
runtime/log/session material, stable-replacement receipts, Git configuration,
release automation, Connector/tunnel/OAuth configuration, and every apply/run/
commit/push/deploy path.

## Public request contract

`inspect` returns the exact template and a fresh `stage_7_9_context`:

```yaml
stage_7_9_context:
  project_name: <resolved managed project name or local project identity>
  branch: <observed branch>
  head: <observed HEAD>
  runner_plan: { mode: <managed|source-only>, plan_sha256: <hash|null> }
  current_version: <string|null>
  review_unit: stage_07_to_stage_09_preview
  workflow_intent: stage_7_9_preview
```

`preview` must receive that object unchanged, plus all three input objects:

```yaml
stage_7_9_inputs:
  stage_7_drift_evidence_inputs: <object for build_drift_evidence_pack>
  stage_8_plan_adjustment_inputs: <object for build_plan_adjustment_preview>
  stage_9_continue_readiness_inputs: <object for build_controlled_continue_readiness_report>
```

The wrapper must establish these cross-stage invariants before its compact
public projection:

1. The request context still matches the current project identity and all four
   frozen taskbook references match both path and SHA-256.
2. Stage 7 succeeds only with a fully schema-valid, unanswered drift evidence
   pack. Its master and Stage 7 refs are the frozen refs above.
3. Stage 8 is supplied by an explicit `PLAN_ADJUST` Commander decision request,
   references the generated Stage 7 pack ID, and uses the frozen master and
   Stage 8 refs. It remains preview-only with `apply_allowed=false`.
4. Stage 9 receives the generated Stage 8 preview reference, the frozen master
   and Stage 9 refs, and an explicit plan/state/readiness input. In this
   PLAN_ADJUST journey, a `PLAN_ADJUST_BLOCKS_CONTINUE` result is the correct
   safe outcome—not a failure that can be bypassed—and identifies the Stage 8
   human decision as next.

The public result is a whitelist projection only: compact IDs, hash-match
booleans, status values, blocker codes, question/checklist counts, and the
next human decision. It must not echo arbitrary input objects, raw runtime
state, provider/session data, local absolute paths, full diffs, or credentials.

## Required negative matrix

Tests must exercise at least these named fail-closed outcomes:

| Case | Required blocker/error |
| --- | --- |
| Missing journey context | `STAGE_7_9_CONTEXT_REQUIRED` |
| Branch/HEAD/plan/version context changes | `STAGE_7_9_CONTEXT_MISMATCH` |
| Missing or wrong frozen taskbook path/hash | `STAGE_7_9_TASKBOOK_BINDING_MISMATCH` |
| Missing one stage input object | `STAGE_7_9_INPUTS_REQUIRED` |
| Invalid Stage 7 evidence | `STAGE_7_9_STAGE_7_FAILED_CLOSED` |
| Stage 8 source is not explicit PLAN_ADJUST | `STAGE_7_9_STAGE_8_FAILED_CLOSED` |
| Stage 8 drift-pack ID differs from Stage 7 | `STAGE_7_9_DRIFT_PACK_BINDING_MISMATCH` |
| Stage 9 lacks its required readiness material | `STAGE_7_9_STAGE_9_FAILED_CLOSED` |
| Any apply/run/commit/execute phase | `STAGE_7_9_PHASE_NOT_SUPPORTED` |

The valid fixture must prove that all side-effect fields are false and that the
Stage 9 report blocks continuation when Stage 8 PLAN_ADJUST remains unresolved.

## Acceptance commands

```text
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_mcp_stage_7_9_preview.py tests/test_drift_evidence_schema.py tests/test_drift_evidence_pack_builder.py tests/test_plan_adjustment_preview.py tests/test_controlled_continue_readiness.py tests/test_mcp_workflow_policy.py tests/test_mcp_workflow_migration.py tests/test_mcp_runtime_observability.py tests/test_mcp_operation_context_binding.py -q
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q
.venv/bin/python scripts/self_hosting_smoke.py
.venv/bin/python -m compileall runner tests
.venv/bin/ruff check runner tests
git diff --check
```

## Completion boundary

P1-C is complete only when this one public, read-only route has the valid and
negative fixture matrix above, no tenth public tool, no newly widened scope,
and a compact next-human-decision projection. It does not make Stage 7--9
execution, plan mutation, or stable deployment authorized.
