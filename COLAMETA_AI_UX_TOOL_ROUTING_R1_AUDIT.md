# ColaMeta AI UX / Tool Routing R1 — Reality Audit

Status: implementation audit complete

Audited tree: `3f64276a1f907d6a2490fac3c45ded779259b72f`

Scope: Agent-facing projection and routing only

## 1. Current tool inventory

`MCPPlanningBridgeServer` builds 123 registered tool definitions for the full
Owner catalog. Existing physical exposure profiles project that catalog as
follows:

| MCP exposure profile | Registered | Physically visible |
|---|---:|---:|
| `owner` | 123 | 123 |
| `legacy` | 123 | 103 |
| `maintainer` | 123 | 87 |
| `normal` | 123 | 85 |
| `commander` | 123 | 9 |
| `authoritative_canary` | 112 | 14 |

The Commander nine-tool surface is already enforced by `_PROFILE_ORDERS` and
`COMMANDER_EXPOSED_TOOLS`; R1 must not replace that registration mechanism.

## 2. Current domain map

The catalog contains these operational domains:

- orientation and routing: project registry, consumer/profile contracts,
  project analysis, Commander flow and app packets;
- bounded workflow: `run_mcp_workflow`, prompt/plan/docs/project-patch helpers;
- source and result reading: bounded file/source search, review manifest and
  result artifact readers;
- executor and validation: executor configuration/session/run/report tools and
  validation preview/run/status;
- Git and delivery: Git status/history/commit/remote operations, GitHub delivery,
  stable readiness and promotion evidence;
- stage parallel: plan, worktree, shard, executor-group, merge and closeout;
- Work Item Governance: work-item, attempt, review, blocker, receipt and outbox
  transitions;
- product/connector/release: Product Console, connector health, app submission
  and release evidence;
- compatibility primitives: retained direct getters and single-purpose preview
  operations.

The implementation lacks one runtime-consumable registry that assigns every
registered tool a domain, a canonical primary tool, a tier, profile guidance
and a side-effect level.

## 3. Duplicate intent and overlapping entrypoints

The highest selection-entropy clusters are:

- project orientation: `analyze_project_state`, project status workflows,
  direct Runner/plan/Git getters and Commander flow packets;
- Git: `manage_git`, `manage_git_commit`, `manage_git_history`,
  `manage_git_remote` and direct Git getters;
- executor: `manage_executor_workflow`, executor reports/activity/session
  getters and `run_mcp_workflow` executor workflows;
- planning/docs/patching: high-level workflow routes plus their precise manager
  tools and legacy preview functions;
- review/results: typed `review_manifest`/`read_result_artifact` plus retained
  compatibility workflow forms;
- stage parallel and Work Item Governance: state packets coexist with precise
  transition tools that should only be recommended at the matching phase.

R1 should reduce this entropy through navigation metadata, not tool deletion.

## 4. Existing routing, profile and continuation primitives

- `analyze_project_state` already builds one canonical fact snapshot and returns
  ordered `recommended_next_actions`.
- `get_agent_operator_flow_packet` already selects a role-aware
  `primary_next_action`, emits a strong read-only authority boundary and knows
  five accepted profiles.
- `auto_preview` already classifies intent and selects a bounded existing
  workflow while stopping at preview/apply/run/commit boundaries.
- `project_name` registry routing, `context_binding`, preview confirmation and
  scope gates already exist and remain authoritative.
- typed handles already include `preview_id`, `patch_id`, `run_id`,
  `workflow_id`, `review_manifest_id`, `artifact_id`, `gate_preview_id` and
  `batch_preview_id`.

The gap is a shared projection contract over these existing primitives.

## 5. Proposed classification

- `PRIMARY`: normal Agent entrypoints such as project registry, profile/flow
  packet, project analysis, bounded workflow, validation, canonical Git,
  review-manifest and result-artifact reads.
- `ADVANCED`: precise domain managers, executor governance, stage-parallel,
  Work Item Governance, delivery and stable-evidence operations.
- `LEGACY_OR_INTERNAL`: compatibility getters, aliases and single-purpose
  primitives retained for old clients or precise internal use.

Classification is guidance only. It must not alter registration, scope,
visibility or execution authority.

## 6. Current Web GPT Commander inventory

The physically visible Commander tools are exactly:

1. `list_registered_projects`
2. `get_apps_connector_smoke_packet`
3. `render_commander_app`
4. `analyze_project_state`
5. `review_manifest`
6. `read_result_artifact`
7. `run_mcp_workflow`
8. `manage_validation_run`
9. `manage_git`

Logical profile guidance makes `analyze_project_state` the Commander first
entrypoint and recommends only members of this exact nine-tool surface.
`get_agent_operator_flow_packet` remains a high-level Owner/local entrypoint,
but is not advertised to a Commander that cannot physically call it.

## 7. Physical exposure feasibility

Status: **SUPPORTED AND ALREADY IMPLEMENTED**.

Evidence: `_PROFILE_ORDERS`, `_get_exposed_tool_names` and profile-specific
tool-list tests enforce static profile-aware exposure. Dynamic per-state
registration is neither needed nor authorized. R1 records
`PHYSICAL_PROFILE_TOOL_FILTERING_RETAINED`; no registration rewrite is planned.

## 8. Current error envelope

ColaMeta currently uses `ok`, `error_code`, `message`, optional `details`,
blockers/warnings and transport-level MCP error shaping. Some subsystems expose
ad-hoc `recovery`, `next_action` or continuation fields. There is no shared
machine-readable recovery classification across the three P0 entrypoints.

R1 will add a bounded projection for ColaMeta-owned errors and will label
uncertain external failures without claiming recovery certainty.

## 9. Continuation handles

Typed handles are security-relevant and remain unchanged. R1 will only project
`kind`, `field_name`, the same exact `id`, source tool, bounded allowed next
actions and an existing expiry when available. No generic continuation handle
will be accepted by an authority gate.

## 10. Required code changes

1. Add a runtime-consumable, exact-name routing registry covering all
   registered tools without substring classification.
2. Add a pure Agent projection module for state, authority guidance, one primary
   action, non-exhaustive blocked actions, typed continuation and recovery.
3. Additively project that contract from `analyze_project_state`,
   `get_agent_operator_flow_packet` and `auto_preview`.
4. Add fixtures constructed by the production canonical-state builder and an
   independent verifier that consumes serialized projection data rather than
   importing router implementation decisions.
5. Document the navigation/authority separation and profile guidance.

## 11. Compatibility risks

- Existing response keys may be compared by old clients: additions must be
  top-level additive and existing values must remain unchanged.
- Existing action shapes differ: normalization must preserve original fields.
- State may be partial: no unique primary action may be fabricated.
- Profile guidance must not become an allowlist or scope decision.
- Continuation metadata must never be accepted in place of the original typed
  parameter.

No Hard Stop was found. The projection can be implemented without deleting or
renaming a tool, changing authentication, weakening a gate, migrating persisted
state or replacing registration architecture.

## 12. Test plan

- inventory coverage and classification invariants for all 123 tools;
- five profile-guidance contracts;
- project inspection, source read, edit, docs, plan, executor, validation,
  commit, review, parallel, blocked Work Item and stable-readiness fixtures;
- preview expiry, context/HEAD mismatch, running operation, validation failure,
  scope failure, confirmation missing, unsupported transition and external
  connector recovery classification;
- navigation metadata cannot authorize apply/run/commit/push/stable mutation;
- cross-kind typed handle rejection remains unchanged;
- existing high-level workflow and Commander compatibility suites.

## 13. Narrow implementation sequence

1. shared routing registry;
2. pure projection/recovery/continuation helpers;
3. `analyze_project_state` projection;
4. operator-flow projection;
5. `auto_preview` projection;
6. fixtures and independent verifier;
7. targeted compatibility, full suite, lint, compile and smoke validation.
