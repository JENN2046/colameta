# ColaMeta AI UX / Tool Routing R1 — Verification

Status: NARROW INTEGRATION-REVIEW REPAIR VALIDATED; FULL-SUITE BASELINE FAILURES PRESERVED

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

## Integration-review repair closure

The narrow repair closes the four P1 and two P2 findings without changing MCP
registration or authority gates:

- `auto_preview` reads the nested production result/canonical-state envelope;
  operation status remains separately visible as `operation_status`;
- Web Commander guidance recommends only tools in its physical nine-tool
  surface and starts at `analyze_project_state`;
- Connector-origin errors take precedence over embedded OAuth/scope markers
  and map conservatively to operator action on the production workflow route;
- all 123 current tools have one explicit exact-name domain assignment, with
  future unknown names fail-visible as `unclassified`;
- all 20 routing fixtures are materialized through
  `build_canonical_project_state`, and every `authority_expectation` is
  mechanically evaluated by the independent verifier;
- validation scope metadata contains only real MCP scopes, expressed by
  inspect/preview/run action rather than a synthetic combined scope.
- recovery uses a conservative `known retry, unknown stop` fallback: unknown
  ColaMeta application errors require operator action and are non-retryable;
  identical-call retry is possible only through an exact reviewed allowlist,
  which currently contains no entries.
- typed handles inside production next-action/result records take precedence
  over the generic `CoreOutput.preview_ids` envelope;
- same-source `refresh_project_state` fallbacks cannot become a primary action;
- seven exact commit-scoped legacy/governance commands are classified as
  `WRITE_OR_TRANSITION` rather than inferred as read-only from their names.
- `auto_preview` filters its projected primary action through the active
  profile's reachable tools, while established operator-flow packets retain
  their own route-specific contracts;
- `source_observer` guidance contains only read-only tools and never advertises
  the mixed read/write `manage_files` surface.
- ASCII routing keywords remain whole-token matched, while audited common
  inflections such as `editing`, `patching`, and `committing` retain their
  intended preview routes.
- a known registered `project_name` is carried into the canonical action's
  concrete arguments and `required_arguments`, so copying the action preserves
  service-mode routing;
- generic preview continuations derive their consuming action from the typed
  production next action (`commit`, `run_once`, `run_bounded`, and so on); a
  context-free preview advertises no invented action.

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

The fixture corpus contains 20 production-built canonical state/intent pairs covering project inspection,
source reading, small edit, docs, plan, executor preflight/ready/running/done,
validation pending/failed/passed, commit pending, context drift, preview expiry,
scope failure, review, stage parallel, blocked Work Item and Stable readiness.

Dedicated R1 tests after review hardening: `59 passed`.
The three previously affected operator-flow production regressions plus the R1
suite pass together: `62 passed`.

## Compatibility validation

- high-level routing/workflow set: `232 passed`;
- Commander/public-contract set: `1426 passed`;
- combined R1 plus related workflow/Commander regression after review
  hardening: `1671 passed`;
- functional MVP, thin loop, stage parallel, review manifest, validation,
  Stable and Work Item targeted set: `863 passed`, `29 subtests passed`;
- full suite after the profile-reachability repair: `4781 passed`, `22 failed`,
  `2 skipped`, `213 subtests passed`.

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
