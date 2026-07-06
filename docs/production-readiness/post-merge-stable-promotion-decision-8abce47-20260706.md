---
receipt_type: post_merge_stable_promotion_decision
receipt_id: post_merge_stable_promotion_decision_8abce47_20260706
recorded_at_utc: 2026-07-06T05:04:51Z
project_name: colameta-self-dev
project_root: /home/jenn/src/colameta-dev
main_head: 8abce47598d387783575500cb6327c5ff0e77bcd
main_short_head: 8abce47
stable_runtime_head: 3b4dbbda9ef8689b08e3f37e049798cdf5d97e38
stable_runtime_short_head: 3b4dbbd
decision: defer_stable_replacement
result: stable_promotion_ready_candidate
---

# Post-Merge Stable Promotion Decision: 8abce47

This receipt records the post-merge decision for whether to advance the stable
runtime from `3b4dbbd` to `8abce47` after PR #4 was merged.

It does not replace `/home/jenn/tools/colameta`, does not restart
`colameta-stable.service`, does not reinstall packages, does not publish a
package, does not push tags, and does not modify network, proxy, Auth0,
Cloudflare, tunnel, or systemd state.

## Decision

```yaml
decision: defer_stable_replacement
candidate_status: stable_promotion_ready_candidate
recommended_posture: optional_batch
stable_replacement_required_now: false
reason: latest main is validated, but the delta after the current stable head is small and not a live-runtime-critical fix
```

`8abce47` is acceptable as a future stable promotion candidate. The current
stable runtime should remain at `3b4dbbd` unless Jenn explicitly requests
strict main/stable alignment or a later runtime-impacting change needs stable
promotion.

## Observed State

```yaml
main_head: 8abce47598d387783575500cb6327c5ff0e77bcd
main_short_head: 8abce47
merged_pr: 4
merged_at_utc: 2026-07-06T04:39:52Z
stable_runtime_dir: /home/jenn/tools/colameta
stable_runtime_head: 3b4dbbda9ef8689b08e3f37e049798cdf5d97e38
stable_runtime_short_head: 3b4dbbd
stable_service_unit: colameta-stable.service
stable_service_state: active/running
stable_service_pid: 2278107
```

## Delta From Stable

Observed `3b4dbbd..8abce47`:

```yaml
changed_file_count: 3
changed_files:
  - docs/connector-tunnel-closeout-receipts/stable-aligned-apps-connector-smoke-3b4dbbd-20260706.md
  - scripts/self_hosting_smoke.py
  - tests/test_self_hosting_smoke.py
summary:
  - record stable-aligned Apps connector smoke receipt
  - harden self-hosting smoke TOML fallback
  - add targeted self-hosting smoke fallback tests
```

The merge commit `8abce47` itself has no content delta beyond the merged branch
tip; `9d369e2..8abce47` was observed as content-identical.

## Validation Evidence

```yaml
github_main_ci:
  workflow: CI
  run_id: 28768224828
  head_sha: 8abce47598d387783575500cb6327c5ff0e77bcd
  status: completed
  conclusion: success
  url: https://github.com/JENN2046/colameta/actions/runs/28768224828

local_targeted_tests:
  command: .venv/bin/python -m pytest tests/test_self_hosting_smoke.py -q
  result: pass
  summary: 2 passed

local_package_smoke:
  command: .venv/bin/python scripts/self_hosting_smoke.py
  result: pass

whitespace_check:
  command: git diff --check 3b4dbbd..8abce47
  result: pass
```

## Cadence Evidence

Read-only ColaMeta cadence evidence reported:

```yaml
status: dev_ahead_stable
stable_replacement_not_required: true
replacement_urgency: optional_batch
recommended_cadence: batch_when_ready
replacement_possible: true
replacement_available: false
```

This evidence does not authorize stable replacement.

## Safety Boundary

```yaml
stable_runtime_modified: false
stable_service_restarted: false
package_reinstalled: false
network_or_proxy_modified: false
auth_provider_modified: false
tunnel_state_modified: false
package_publish_performed: false
tag_push_performed: false
executor_run_performed: false
delivery_state_accepted: false
tokens_or_cookies_read: false
client_secret_read: false
env_values_read: false
tunnel_config_read: false
raw_logs_read: false
```

## Follow-Up Trigger

Promote stable to `8abce47` or a later main head only when one of these is true:

```yaml
promotion_triggers:
  - Jenn explicitly requests stable/main alignment
  - stable service needs a fix present only after 3b4dbbd
  - a runtime-impacting production-readiness change lands after 8abce47
  - external connector smoke must be refreshed against latest stable code
```
