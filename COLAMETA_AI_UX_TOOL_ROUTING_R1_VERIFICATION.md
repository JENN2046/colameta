# ColaMeta AI UX / Tool Routing R1 — Verification

Status: IMPLEMENTATION COMPLETE; FULL-SUITE BASELINE FAILURES PRESERVED

Implementation base: `3f64276a1f907d6a2490fac3c45ded779259b72f`

Branch: `codex/ai-ux-tool-routing-r1`

## Implemented contract

- one runtime-consumable registry classifies all 123 registered tools by
  domain, canonical primary tool, tier, profile and side-effect level;
- `analyze_project_state`, `get_agent_operator_flow_packet` and
  `run_mcp_workflow(auto_preview)` emit the additive
  `colameta.agent_state_projection.v1` projection;
- every projected primary action, continuation, recovery and routing record is
  explicitly navigation-only and non-authorizing;
- blocked actions are explicitly non-exhaustive;
- typed continuation fields remain distinct and no generic authority handle is
  introduced;
- recognized states use one conservative read/preview action; unknown states
  return no primary action and explain why;
- ASCII goal keywords are token-matched so substrings such as `pi` in
  `expired` cannot select the executor route.

## Independent Agent UX verification

The verifier in `tests/agent_ux_independent_verifier.py` imports no production
Router or projection builder. It inspects only the returned mapping and rejects:

- a non-null primary action that is not explicitly non-authorizing;
- null primary action without a reason;
- missing or exhaustive blocked-action metadata;
- any authority domain marked granted by projection;
- a continuation kind whose typed field does not match;
- any generic `continuation_id`;
- routing metadata without an explicit no-authority boundary.

The fixture corpus contains 20 state/intent pairs covering project inspection,
source reading, small edit, docs, plan, executor preflight/ready/running/done,
validation pending/failed/passed, commit pending, context drift, preview expiry,
scope failure, review, stage parallel, blocked Work Item and Stable readiness.

Dedicated R1 tests: `29 passed`.

## Compatibility validation

- primary Commander/project-routing/auto-preview set: `1570 passed`;
- functional MVP, workflow policy, thin loop, stage parallel, review manifest,
  validation, Stable and Work Item targeted set: `776 passed`, `1 failed`,
  `29 subtests passed`;
- full suite: `4761 passed`, `22 failed`, `2 skipped`, `213 subtests passed`.

All 22 full-suite failing nodes were replayed against an untouched detached
worktree at the implementation base. Every one reproduced there:

- 13 project-operation-lease/environment failures;
- 3 Web Console mutation tests blocked by the same lease condition;
- 2 frozen-toolchain tests missing the bound cryptography wheel environment;
- 2 pre-existing Work Item executor error-precedence mismatches;
- 1 production-ops file-mode/error-precedence mismatch;
- 1 canonical project conclusion mismatch in Git confirmation.

Therefore the R1 change introduces `0` new full-suite failure nodes. The full
suite is still truthfully classified as failed, not PASS.

## Static and packaging validation

- Python `compileall`: PASS;
- Ruff on all changed Python and test files: PASS;
- `scripts/self_hosting_smoke.py`: PASS, including isolated wheel build,
  install, imports, Commander widget and governance-schema negative check;
- `git diff --check`: PASS.

## Frozen boundaries

No tool was deleted or renamed. No public input field, OAuth behavior, Owner
principal policy, scope, preview gate, context binding, typed handle, MCP
registration architecture, Stable runtime, push, merge, deploy or release path
was changed. Commander retains its existing physical nine-tool surface.
