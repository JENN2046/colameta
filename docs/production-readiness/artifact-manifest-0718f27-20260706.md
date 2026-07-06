---
receipt_type: candidate_artifact_manifest_summary
receipt_id: candidate_artifact_manifest_0718f27_20260706
recorded_at_utc: 2026-07-05T16:43:40Z
project_name: colameta-self-dev
project_root: /home/jenn/src/colameta-dev
candidate_head: 0718f27bca6ee8f27f143e8af19aaef828c6f3db
candidate_short_head: 0718f27
source: get_stable_promotion_readiness
read_only: true
side_effects: false
---

# Candidate Artifact Manifest Summary: 0718f27

This receipt persists the read-only candidate artifact manifest summary returned
by `get_stable_promotion_readiness` after the worktree was made clean.

It is not a release artifact by itself, does not authorize stable replacement,
does not restart services, and does not include untracked files, ignored runtime
state, `.git`, `.venv`, build artifacts, secrets, cookies, tokens, browser state,
or private runtime state.

## Manifest Summary

```yaml
manifest_version: 1
manifest_kind: tracked_worktree_sha256_manifest
algorithm: sha256
project_head: 0718f27bca6ee8f27f143e8af19aaef828c6f3db
file_count: 533
total_size_bytes: 8132722
manifest_sha256: 17d551ca0993578dacb0dc1f8739e6173fd21c2382414402d6bb31550269843a
tracked_path_list_sha256: 76bcbc3bce2284ec50533b66418c8e69623ab57036d37afd12ea36cb175fb4eb
file_entries_omitted_from_mcp_response: true
excluded_scope: untracked_files_ignored_runtime_private_state_git_directory_virtualenv_build_artifacts
```

## Git State At Observation

```yaml
branch: codex/external-oauth-resource-server
worktree_clean: true
dirty_entry_count: 0
origin_main_head: 822adac33f5dc15582d29e5236ad45f08a66857e
ahead_of_origin_main: 6
behind_origin_main: 1
stable_runtime_head: 98da7e0bc74b394e6c48561c24b6ab464e55c764
```

## Readiness Result At Observation

```yaml
readiness_status: not_ready_for_stable_promotion_review
stable_promotion_review_candidate: false
stable_production_ready: false
remaining_local_blockers:
  - RUNTIME_RELOAD_NEEDED_FOR_VERIFICATION
```

`WORKTREE_NOT_CLEAN` was cleared before this manifest summary was captured. The
remaining blocker requires a service reload or equivalent runtime freshness proof
for the current checkout. This receipt does not perform that action.

## Safety Boundary

```yaml
read_tokens_or_cookies: false
read_env_values: false
read_tunnel_config: false
read_raw_logs: false
service_restart_performed: false
stable_replacement_performed: false
route_transition_performed: false
package_publish_performed: false
tag_push_performed: false
```
