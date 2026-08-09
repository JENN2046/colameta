# P0 Canonical Baseline Reconciliation — 2026-08-03

~~~yaml
report_type: P0_CANONICAL_BASELINE_RECONCILIATION
project: colameta-self-dev
generated_at: 2026-08-03T11:33:32Z
decision: PASS_P0_RECONCILIATION_REPORT_CORRECTED
candidate_head: fdc588d24a417a1357fe27bc98aa238f16add184
candidate_branch: main
product_code_changed: false
tracked_write_scope:
  - docs/P0_CANONICAL_BASELINE_RECONCILIATION_2026-08-03.md
  - docs/COMMANDER_FOLLOWUP_REGISTER.md
push_performed: false
release_performed: false
stable_replacement_performed: false
executor_started: false
executor_resumed: false
~~~

## Executive Decision

P0-R1 report correction is complete: the current source identity is
main@fdc588d, final-head follow-up classifications are bound to source commits
and regression evidence, and historical Runner/Executor evidence is explicitly
separated from direct verification and canonical validation. The canonical
validation gate remains open because its isolated environment drifted; this
report does not convert that failure into a product failure or a pass.

The result is a factual reconciliation, not a claim that the external
connector is healthy or that the latest main has been promoted to the stable
service. Neither of those mutations was authorized.

## Before / After

| Surface | Before | After / authoritative disposition |
| --- | --- | --- |
| Git | Clean feature branch codex/commander-contract-v1-hotfix at 4a0dbb7; tree-equivalent to origin/main, but not main identity | Canonical baseline main@fdc588d24a417a1357fe27bc98aa238f16add184; origin/main equal; clean before report write; only the two allowed report files are now untracked |
| Runner | COMPLETED, current v1.18 / PASSED, 21 planned versions, v1.19 present, latest persisted report v1.15 | Same historical state retained; v1.19 disposition explicitly B: implementation is in main, canonical v1.19 Executor lineage is not proven |
| Executor | Codex session present, recorded HEAD 9448b4e…, current HEAD different; no safe continuation | Existing canonical session reset marked it inactive and retained the record for audit; no session file was deleted or hand-edited; continuation and new-start decisions remain fail-closed |
| Runtime | Runtime had to be checked against the feature-branch identity | Loaded source, checkout, and installed package now report main@fdc588d; stale/reload flags are false; local Web/MCP are healthy |
| Connector | Local Runtime healthy, external Tunnel/Control Plane freshness missing | Apps connector reachability is proved; tunnel client is healthy with SYSTEMD_SERVICE_RUNNING; Control Plane remains unverified with PUBLIC_BASE_URL_REJECTED; connector closeout is needs_attention/blocked |
| Stable replacement | Latest receipt was historical and did not describe current main | not_promoted; current stable runtime head is 861a401…, different from candidate fdc588d…; no promotion was attempted |
| PR #188 follow-ups | PR Conversation register existed outside the repository and had not been reconciled to final Head | Canonical tracked register is [COMMANDER_FOLLOWUP_REGISTER.md](COMMANDER_FOLLOWUP_REGISTER.md): 0 active, 25 fixed in source PR, 1 deduplicated amendment repeat, zero P1 |

## M0 — Frozen facts

### Git

~~~yaml
remote: origin -> git@github.com:JENN2046/colameta.git
before_branch: codex/commander-contract-v1-hotfix
before_head: 4a0dbb77349445765b13da60991484cc26a8538f
origin_main_after_read_only_fetch: fdc588d24a417a1357fe27bc98aa238f16add184
before_worktree_clean: true
before_tree_matches_origin_main: true
before_ahead_behind: "124 1"
after_branch: main
after_head: fdc588d24a417a1357fe27bc98aa238f16add184
after_origin_main: fdc588d24a417a1357fe27bc98aa238f16add184
clean_before_report_write: true
after_ahead_behind: "0 0"
candidate_tree: 5c977137bf43eeefff1e5c9e001a537a80337936
candidate_git_object_manifest_sha256: b2fe8133a89a29313eb9a73579eabc232a93be2b29925f3282b4a244b358eee0
~~~

The switch used git fetch origin main followed by a fast-forward-only local
update. No merge commit, rebase, reset, force push, or history rewrite was
used.

### Runner

~~~yaml
runner_status: COMPLETED
current_version: v1.18
current_version_status: PASSED
pending_count: 0
plan_version_count: 21
enabled_versions: v1.0..v1.19
plan_sha256: f1f2ee0986c01fcc04d0d85ec1bb8ea98f3a0e6191bccdc201ef807db7ff1b4b
v1_19_present: true
latest_persisted_executor_report:
  version: v1.15
  classification: historical_only
  version_status: PASSED
  executor_summary: PASSED_OR_IDLE
v1_19_runner_result:
  current_version: v1.18
  version_status: UNKNOWN
  canonical_execution_lineage: not_proven
state_or_plan_hand_edited: false
~~~

The Runner version-lineage gap and the plan path mismatch are separate facts.
Neither was repaired by changing `.colameta/state.json` or by copying a
report:

~~~yaml
runner_version_lineage_gap:
  plan_contains_v1_19: true
  runner_current_version: v1.18
  source_implementation_status: merged
  canonical_v1_19_executor_lineage: not_proven

plan_path_mismatch:
  affected_paths:
    - project_root
    - logs_dir
    - runtime_dir
    - state_file
  root_cause: "`.colameta/plan.json` stores repository-relative path identity values (`.`, `.colameta/logs`, `.colameta/runtime`, `.colameta/state.json`), while `MCPRunnerPlanManager._plan_path_mismatches()` compares those fields by exact string equality with current project-bound absolute paths."
  disposition: "record_as_path_representation_mismatch; keep version lineage separate; do not rewrite plan or state in this report correction"
~~~

## M2 — Runner v1.19 disposition: B

Disposition B is proven by both sides of the boundary:

- the v1.19 prompt remains a plan-only, prepared_not_authorized specification;
- bridge-version-result v1.19 has no commit or audit execution result and
  leaves Runner at v1.18;
- the implementation associated with the v1.19 work is nevertheless present
  in the current main history and tree, including
  runner/mcp_validation_run.py, runner/p1_release_evidence.py, and their
  tests/docs;
- the relevant implementation commits are ancestors of fdc588d, including
  05575ad, 6495c13, 84c1f8b, a18d2e2, 30e15dc, f9c3d45,
  0579b96, and f78bf70.

Therefore:

~~~yaml
source_implementation_status: merged
runner_execution_status: not_canonically_executed_or_not_proven
current_source_head: fdc588d24a417a1357fe27bc98aa238f16add184
historical_v1_18_state: retained_as_truth
v1_19_executor_report: not_created
~~~

The PR #188 exact-head and merge-commit CI results are separate evidence. They
do not become a v1.19 Executor report.

## M3 — Current main validation

### Candidate-bound manifest

The canonical Review Manifest bound 21 source/test subjects to the current
branch, head, and plan:

~~~yaml
review_manifest_subject_count: 21
review_manifest_sha256: 9f6e5f4084d80c88cb6b19495d1b69bcfbf6ce33b54313455fd214f4f6c7d3a9
validation_contract_sha256: 54b75ba4c3030e9544a0e405db0947ef8c2a8f606ca514d2891b823dba1803ac
command_specs_sha256: 990582a02bebc38db98947f8656b64577154bf2b7f2828aa33ead36f7ee94004
review_context:
  branch: main
  head: fdc588d24a417a1357fe27bc98aa238f16add184
  plan_sha256: f1f2ee0986c01fcc04d0d85ec1bb8ea98f3a0e6191bccdc201ef807db7ff1b4b
~~~

### Exact commands and results

The candidate checkout was clean and still at the bound HEAD when the direct
validation commands below ran:

~~~yaml
direct_exact_head_verification:
  status: passed
  head: fdc588d24a417a1357fe27bc98aa238f16add184
  commands:
    - argv: ".venv/bin/python -m compileall -q runner scripts adapters schemas tests"
      result: passed
    - argv: ".venv/bin/python scripts/self_hosting_smoke.py"
      result: passed
    - argv: ".venv/bin/python -m pytest -q tests/test_commander_contract.py tests/test_commander_workflow_policy.py tests/test_mcp_result_artifacts.py tests/test_mcp_review_manifest.py tests/test_mcp_operation_context_binding.py tests/test_mcp_current_facts.py tests/test_mcp_runtime_observability.py tests/test_executor_session_head_mismatch.py tests/test_continuation_snapshot.py tests/test_product_readiness.py"
      result: passed
      summary: "1932 passed, 78 subtests passed"
    - argv: ".venv/bin/python -m ruff check adapters runner schemas scripts tests"
      result: passed
    - argv: "git diff --check"
      result: passed
    - argv: "git status --short --branch"
      result: passed
      summary: "main...origin/main; no changed paths"
github_ci:
  status: passed
  exact_pr_head: 4a0dbb77349445765b13da60991484cc26a8538f
  exact_pr_head_run: 30789063326
  exact_main_head: fdc588d24a417a1357fe27bc98aa238f16add184
  exact_main_run: 30790183992
canonical_validation:
  status: failed_environment_drift
  canonical_gate_closed: false
  product_failure_proven: false
  failed_result_artifacts_retained: true
  manifest_bound_runs:
    - result_sha256: 7e9fff5b8e93e6821c8a9ad8cfc84909ccc688dfbff04d99b5b6cef167c2e00c
      failed_command: scripts/self_hosting_smoke.py
    - result_sha256: 002702f7a099392ef02460fba911bfcc122ef4fd47bc4622c25dbf08b37fbbfb
      failed_command: scripts/self_hosting_smoke.py
  target_files_run:
    result_sha256: 0f8dcbc1452e7a571356bb911a819004c209896f4ed5635ea84425ea72dd8d61
    failed_command: targeted_pytest
  observed_causes:
    manifest_bound_smoke: isolated_runner_injected_PYTHONPATH_made_temporary_venv_treat_source_checkout_as_already_satisfied_and_no_console_script_was_created
    target_files_pytest: validation_service_inherited_runtime_environment_imported_a_different_module_view
~~~

The direct commands above are exact-head verification, not a canonical
Validation Result. The canonical manifest-bound artifacts are retained as
failed evidence; their causes are environment/toolchain drift, so no product
failure is proven and no validation-result JSON was hand-edited.

Local full pytest was not repeated because this task made no product-code
change. The exact main@fdc588d GitHub CI run completed successfully with all
six jobs green: Quality gates and Python 3.10, 3.11, 3.12, 3.13, and 3.14.
The exact PR head 4a0dbb7 CI run also completed successfully.

## M4 — Executor session closeout

Before closeout, the canonical facts were:

~~~yaml
session_present: true
provider: codex
recorded_branch: main
recorded_head: 9448b4ea00fcf2ce62871872302dfef58205d796
current_head: fdc588d24a417a1357fe27bc98aa238f16add184
branch_mismatch: false
head_mismatch: true
operation_running: false
job_status: idle
latest_claim_status: completed
latest_run_status: completed
~~~

No canonical retire/closeout API exists. The existing canonical
executor-session-reset lifecycle mechanism was used with a P0 reconciliation
reason. It marked the record inactive, added the closeout timestamp/reason,
and retained the original session record for audit. It did not delete the
session file, edit historical HEAD/provider values, resume a session, or start
an Executor.

~~~yaml
session_state: inactive_canonical_reset_retained_for_audit
continuation_available: false
resume_allowed: false
start_new_allowed: false
live_operation: false
post_closeout_classification: fail_closed_unknown_head_mismatch
~~~

The remaining fail-closed start decision is not treated as evidence that a new
Executor was needed or allowed. It is carried forward for Commander review.

## M5 — Runtime and Connector freshness

### Runtime

At the current observation (2026-08-03T10:54:39Z), the local runtime status
reported:

~~~yaml
local_service: healthy
mcp_endpoint: healthy
loaded_branch: main
loaded_head: fdc588d24a417a1357fe27bc98aa238f16add184
checkout_branch: main
checkout_head: fdc588d24a417a1357fe27bc98aa238f16add184
runtime_checkout_head: fdc588d24a417a1357fe27bc98aa238f16add184
installed_package_matches_project_checkout: true
runtime_loaded_code_stale: false
reload_needed: false
~~~

This proves current Runtime source alignment. It does not prove stable
replacement.

### Connector

The local canonical MCP surface successfully called
list_registered_projects; it returned ok=true, five registered projects,
and included colameta-self-dev. This is the current Apps/managed-connector
reachability fact. It is distinct from an external ChatGPT Apps smoke packet.

Fresh sanitized external observations were collected without reading config,
credentials, cookies, browser state, or raw logs:

~~~yaml
connector_observation_window: 2026-08-03T10:54:06Z..2026-08-03T10:54:39Z
apps_connector:
  reachability: proved
  evidence_source: local_canonical_mcp_list_registered_projects
tunnel_client:
  status: healthy
  reason_code: SYSTEMD_SERVICE_RUNNING
  evidence_source: sanitized_systemd_service_state
control_plane:
  status: unverified
  reason_code: PUBLIC_BASE_URL_REJECTED
  evidence_source: canonical_ops_check_remote_https_preflight
  interpretation: rejected_public_preflight_is_not_sufficient_to_claim_control_plane_health
connector_closeout:
  status: needs_attention
  decision: blocked
~~~

The current ops-check also reports CONNECTOR_SMOKE_MISSING. Apps/managed
connector reachability is therefore proved only by the approved local
canonical MCP surface; the external Apps smoke packet and Control Plane health
remain unverified. This is an evidence gap, not an assertion that the external
connector is down.
No tunnel restart, DNS/proxy change, OAuth action, or route transition was
performed.

## M6 — Stable replacement decision

~~~yaml
stable_replacement:
  status: not_promoted
  latest_main_head: fdc588d24a417a1357fe27bc98aa238f16add184
  current_stable_head: 861a401cd8f27dfb657a6899775a225862f551ff
  stable_tree_equivalent_to_latest_main: false
  latest_receipt: docs/stable-replacement-receipts/stable-replacement-6c72507-20260726.md
  latest_receipt_promoted_head: 6c7250712cc2bc177e85bdbbcbbf4659556de815
  authorization_required_for_promotion: true
  action_taken: none
~~~

The historical 6c72507 receipt is not evidence that the current fdc588d has
been promoted. The current stable runtime observation is explicitly separate
from the development Runtime observation.

## M7 — PR #188 follow-up governance

The canonical register is [COMMANDER_FOLLOWUP_REGISTER.md](COMMANDER_FOLLOWUP_REGISTER.md).
Its final-head audit records all 25 deduplicated source entries as
fixed_in_source_pr, with 0 active follow-ups, 1 amendment duplicate, and 0
stale/superseded/P1 entries. The current GraphQL review-thread audit found 176
unique threads, all resolved. No follow-up code was changed in this task.

## Final Git state after report writes

~~~yaml
canonical_source_baseline:
  branch: main
  head: fdc588d24a417a1357fe27bc98aa238f16add184
  origin_main_aligned: true
  clean_before_report_write: true

current_worktree:
  clean: false
  allowed_untracked_files:
    - docs/P0_CANONICAL_BASELINE_RECONCILIATION_2026-08-03.md
    - docs/COMMANDER_FOLLOWUP_REGISTER.md
  unexpected_changes: false
~~~

## Authority hierarchy

The following hierarchy governs future statements about the baseline:

~~~text
GitHub main@fdc588d
    ↓
candidate-bound current validation
    ↓
Runner historical execution state
    ↓
Executor session state
    ↓
Runtime observation
    ↓
Connector external observation
~~~

- GitHub main establishes source identity and merge history. It cannot prove
  Runtime loading, Connector reachability, or stable promotion.
- Candidate-bound validation establishes what was checked against the source
  candidate. It cannot rewrite Runner history or create Executor lineage.
- Runner execution state describes its own version/report history. It cannot
  be substituted with PR CI or source presence.
- Executor state describes whether a resumable operation exists. A retained
  session record cannot be treated as a live operation.
- Runtime observation describes the currently loaded local code. Tree
  equivalence is not stable promotion.
- Connector observation describes only the external status surface and its
  freshness. Missing or rejected preflight evidence is not silently converted
  to healthy/unavailable without the corresponding observation.

## Remaining blockers and warnings

~~~yaml
blockers:
  - code: CANONICAL_VALIDATION_GATE_OPEN
    fact: canonical_validation.status is failed_environment_drift and canonical_gate_closed is false; no product failure is proven
    authorized_next_step: separately repair or re-scope the validation environment; not in this report correction
warnings:
  - code: CONNECTOR_CLOSEOUT_INCOMPLETE
    fact: Apps connector reachability is proved locally, tunnel client is healthy, Control Plane is unverified with PUBLIC_BASE_URL_REJECTED, and external Apps smoke is missing
    authorized_next_step: separate approved network/connector evidence collection
  - code: STABLE_REPLACEMENT_NOT_PROMOTED
    fact: current stable runtime head differs from latest main
    authorized_next_step: explicit Commander authorization for a separate stable replacement
  - code: RUNNER_V1_19_LINEAGE_NOT_PROVEN
    fact: source implementation is merged while Runner remains historically at v1.18
    authorized_next_step: do not fabricate a v1.19 execution report; plan a separate lineage reconciliation if desired
  - code: RUNNER_PLAN_PATH_MISMATCH_RECORDED
    fact: repository-relative plan path identity is compared with absolute current project paths by the Runner inspector
    authorized_next_step: keep this representation mismatch separate from version lineage; no plan/state edit is authorized here
  - code: CANONICAL_VALIDATION_HARNESS_ENVIRONMENT_DRIFT
    fact: manifest and target service runs produced failed artifacts for environment/toolchain reasons while exact direct candidate commands passed
    authorized_next_step: fix or separately scope the validation harness; not a product-code change in this P0 task
  - code: EXECUTOR_START_FAIL_CLOSED
    fact: no continuation or new Executor start is allowed by the current decision
    authorized_next_step: Commander review only; no start/resume was attempted
~~~

No source-tree drift, unauthorized tracked mutation, historical evidence
rewrite, false stable-promotion claim, secret exposure, push, commit, release,
or deployment was performed.

## Stop boundary

The repository is left at the requested review boundary:

~~~text
READY_FOR_COMMANDER_R1_REVIEW
~~~

No commit, push, PR update, next-version start, Executor start/resume, or
stable replacement follows this report.
