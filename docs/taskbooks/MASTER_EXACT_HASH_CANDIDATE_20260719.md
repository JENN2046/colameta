# Master Exact-Hash Candidate — 2026-07-19

## Candidate

```yaml
candidate_kind: exact_hash_reaffirmation_without_master_mutation
repository_head: b6c864c4319ceaa0afc56f4bc2b2ae96998c5f29
target_path: PROJECT_MASTER_TASKBOOK.md
target_embedded_status: discussion_draft
current_raw_sha256: 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
candidate_raw_sha256: 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
candidate_diff: none
master_file_mutated: false
registry_mutated: false
canonical_receipt_mutated: false
```

The exact Master candidate is intentionally byte-for-byte identical to the
current registered Master. The current soak, stable/runtime provenance, Runner
lineage, and submission-candidate facts are volatile operational evidence. The
Master hash policy already excludes `master_taskbook.current_known_state`,
local status notes, and runtime status notes from the governance boundary.
Moving those facts into the Master would create hash churn without changing the
project doctrine.

## Existing Hash Set

The existing hash-specific review packet records:

```yaml
master_raw_snapshot_sha256: 1b2d787465eef52a177f4716ea7495704e03c390ce6f0e3d26ca16b360688e34
draft_freeze_content_hash_sha256: 495fcd55b637b6d9d8eb11695792ad47a6e1abd485d63172146e782f7efceee3
canonical_fields_manifest_sha256: 0a7dc3c33f5b9b2705fdadeab9a0052f74c403e7186e69acbdf4a3dbd9a48cb1
canonical_payload_json_sha256: 3c57b4b4922549cd7778d8f35cf6ff167740d5531d5b49468efd162e11e09510
review_status: freeze_candidate_confirmed_for_exact_hash
```

This preparation revalidated the raw file hash against the working tree and
confirmed that the tracked Master registry still binds the same raw SHA-256.
It does not regenerate or promote the canonical receipt, and it does not claim
that historical repository-state fields inside the older review packet are a
current runtime snapshot.

## External Reality References

These references support review but are not imported into the Master candidate:

```yaml
current_reality_snapshot:
  path: docs/taskbooks/CURRENT_REALITY_SNAPSHOT_20260719.md
  raw_sha256: eb8100f9cc84d392118c3097eff65338525de3a72524de8c067340fcc3a2c6cf
seven_tool_submission_candidate:
  path: chatgpt-app-submission.json
  source_commit: b6c864c4319ceaa0afc56f4bc2b2ae96998c5f29
  raw_sha256: 05877797d7d4115a909f64d024c2b933d089fed27b7a0791fec3412ff3e41296
stable_soak_receipt:
  path: docs/connector-tunnel-closeout-receipts/read-only-soak-ad170ce-20260719.md
  loaded_stable_target: ad170ced2bd576215bcda0ea1078dd6d6f41cf9f
stable_replacement_receipt:
  path: docs/stable-replacement-receipts/stable-replacement-b6c864c-20260719.md
  loaded_stable_target: b6c864c4319ceaa0afc56f4bc2b2ae96998c5f29
  raw_sha256: 2d2d0f0e53aa523c2bb177c19ad9ecede3c9940e09f3c5ed6a93b62a71f73213
```

## Authorization Boundary

This artifact prepares an exact review candidate only. It does not authorize a
Master mutation, registry rewrite, canonical re-freeze, implementation route,
commit, push, executor run, submission, release, stable replacement, or service
restart.

If a later governance change is actually proposed, it must supply a concrete
Master diff and a newly computed exact candidate hash. If `b6c864c` is to become
the stable runtime target, that separate operation requires a new explicit
authorization naming the full target commit.
