# Commander public-evidence follow-up register after PR #188

This is the repository-local authority for the original non-P1 Commander
public-evidence findings raised during PR #188 and their final-head
disposition. The findings were initially outside the PR freeze scope; this
tracked copy records which were subsequently fixed in the source PR and which
future architecture work remains separate. GitHub Issues are disabled for
this repository; the original register and its amendment were posted in the
PR conversation, and this tracked copy makes the disposition auditable from
the repository.

## Register policy

~~~yaml
source_pr: 188
source_pr_head: 4a0dbb77349445765b13da60991484cc26a8538f
merged_main_head: fdc588d24a417a1357fe27bc98aa238f16add184
inventory_observed_date: 2026-08-03
unique_pr_review_threads_observed: 176
resolved_pr_review_threads_observed: 176
unresolved_pr_review_threads_observed: 0
active_follow_up_count: 0
fixed_in_source_pr_count: 25
stale_count: 0
duplicate_count: 1
superseded_count: 0
p1_count: 0
dedupe_key: GitHub review thread/comment database id
scope: non-P1 Commander public-evidence hardening after the Kubernetes Secret fix
reopen_policy: only a CI failure, a regression caused by the final PR fix, or a P1 may reopen PR #188
~~~

The current GitHub review-thread query returned 176 unique resolved threads.
The earlier PR register contained 23 unique links; its exact-head amendment
added one new link and repeated one existing link (`3691860435`, F-006). The
final-head audit below therefore contains 25 unique source entries, records the
one duplicate separately, and classifies every unique entry against `4a0dbb7`.
No entry remains active, stale, or superseded after the source/test audit; the
future architecture batch below is not an active PR-thread count.

All reproductions below are synthetic and must use redacted fixtures. No live
credential, provider response, cookie, token, or browser state is required.

## Final-head audited source threads

~~~yaml
- id: F-001
  source_pr: 188
  source_comment_or_thread: https://github.com/JENN2046/colameta/pull/188#discussion_r3688700380
  severity: P2
  status: fixed_in_source_pr
  component: result_artifact_manifest_uri_boundary
  summary: Preserve valid opaque resource URI validity when public text truncation cuts across a URI.
  synthetic_reproduction: true
  security_boundary: public Artifact/Manifest text projection and URI allowlist handling
  recommended_disposition: closed_by_final_head_fix; retain regression coverage
  allowed_reopen_condition: CI failure, regression caused by PR #188, or P1 only
  finding_present_at_final_head: false
  fix_commit: "866e6a2"
  regression_test_present: true
  classification_basis: "Final-head URI truncation preserves only a complete opaque URI or replaces a crossing URI; tests/test_commander_contract.py::test_public_text_redacts_an_opaque_uri_crossing_the_character_cutoff"

- id: F-002
  source_pr: 188
  source_comment_or_thread: https://github.com/JENN2046/colameta/pull/188#discussion_r3688775850
  severity: P2
  status: fixed_in_source_pr
  component: public_evidence_redaction_precedence
  summary: Redact a sensitive assignment before preserving a URI-shaped substring inside its value.
  synthetic_reproduction: true
  security_boundary: public text redaction must dominate URI preservation
  recommended_disposition: closed_by_final_head_fix; retain regression coverage
  allowed_reopen_condition: CI failure, regression caused by PR #188, or P1 only
  finding_present_at_final_head: false
  fix_commit: "0121993"
  regression_test_present: true
  classification_basis: "Final-head public projection redacts credential syntax spanning a preserved URI; tests/test_commander_contract.py::test_public_text_redacts_sensitive_values_that_are_valid_opaque_uris"

- id: F-003
  source_pr: 188
  source_comment_or_thread: https://github.com/JENN2046/colameta/pull/188#discussion_r3689172892
  severity: P2
  status: fixed_in_source_pr
  component: commander_documentation_error_inventory
  summary: Remove non-Commander error names from the Commander guide.
  synthetic_reproduction: not_applicable_documentation_only
  security_boundary: public documentation must describe only the exposed Commander contract
  recommended_disposition: closed_by_documentation_fix; retain documentation regression
  allowed_reopen_condition: CI failure, regression caused by PR #188, or P1 only
  finding_present_at_final_head: false
  fix_commit: "30ce078"
  regression_test_present: true
  classification_basis: "Final-head Usage common-error guidance exposes only PROJECT_CONTEXT_MISMATCH and INTERNAL_ERROR with nine-tool recovery; tests/test_commander_public_docs.py::test_usage_docs_keep_commander_error_recovery_on_the_public_surface"

- id: F-004
  source_pr: 188
  source_comment_or_thread: https://github.com/JENN2046/colameta/pull/188#discussion_r3691249469
  severity: P2
  status: fixed_in_source_pr
  component: resource_uri_unicode_boundary
  summary: Accept a combining mark immediately before an opaque resource URI.
  synthetic_reproduction: true
  security_boundary: Artifact/Manifest URI boundary detection must not reject valid multilingual text
  recommended_disposition: closed_by_final_head_fix; retain regression coverage
  allowed_reopen_condition: CI failure, regression caused by PR #188, or P1 only
  finding_present_at_final_head: false
  fix_commit: "c1381d3"
  regression_test_present: true
  classification_basis: "Final-head URI boundary scanning accepts combining-mark prose, including exact Artifact/Manifest cases; tests/test_commander_contract.py::test_public_text_preserves_opaque_uris_adjacent_to_unicode_prose"

- id: F-005
  source_pr: 188
  source_comment_or_thread: https://github.com/JENN2046/colameta/pull/188#discussion_r3691604817
  severity: P2
  status: fixed_in_source_pr
  component: resource_uri_scheme_filter
  summary: Match disallowed ColaMeta schemes case-insensitively in exact evidence.
  synthetic_reproduction: true
  security_boundary: exact Artifact/Manifest evidence must fail closed for case variants
  recommended_disposition: closed_by_final_head_fix; retain regression coverage
  allowed_reopen_condition: CI failure, regression caused by PR #188, or P1 only
  finding_present_at_final_head: false
  fix_commit: "0e12ef1"
  regression_test_present: true
  classification_basis: "Final-head disallowed ColaMeta scheme matching is case-insensitive and covered by literal/escaped typed-evidence negatives; tests/test_mcp_review_manifest.py::test_commander_manifest_read_rejects_unsafe_uri_boundaries"

- id: F-006
  source_pr: 188
  source_comment_or_thread: https://github.com/JENN2046/colameta/pull/188#discussion_r3691860435
  severity: P2
  status: fixed_in_source_pr
  component: encoded_non_commander_tool_filter
  summary: Decode escaped field names before filtering non-Commander tool references.
  synthetic_reproduction: true
  security_boundary: exact Result Artifact/Review Manifest evidence must not expose hidden tools
  recommended_disposition: closed_by_final_head_fix; retain regression coverage
  allowed_reopen_condition: CI failure, regression caused by PR #188, or P1 only
  finding_present_at_final_head: false
  fix_commit: "d78722b"
  regression_test_present: true
  classification_basis: "Final-head bounded decoded-candidate scanning rejects encoded hidden tool references on public text and typed Artifact/Manifest paths; tests/test_commander_contract.py::test_public_text_redacts_encoded_noncommander_tools"

- id: F-007
  source_pr: 188
  source_comment_or_thread: https://github.com/JENN2046/colameta/pull/188#discussion_r3693705271
  severity: P2
  status: fixed_in_source_pr
  component: typed_evidence_before_page_slicing
  summary: Validate typed evidence before slicing a page when an allowlisted URI straddles the page boundary.
  synthetic_reproduction: true
  security_boundary: paged Artifact/Manifest evidence must not classify a split safe handle as unsafe or vice versa
  recommended_disposition: closed_by_final_head_fix; retain typed-evidence regression coverage
  allowed_reopen_condition: CI failure, regression caused by PR #188, or P1 only
  finding_present_at_final_head: false
  fix_commit: "6389564"
  regression_test_present: true
  classification_basis: "Final-head typed Artifact/Manifest reads preflight complete hash-bound content before page slicing; tests/test_mcp_result_artifacts.py::test_typed_result_artifact_validates_whole_payload_before_slicing_resource_uri"

- id: F-008
  source_pr: 188
  source_comment_or_thread: https://github.com/JENN2046/colameta/pull/188#discussion_r3697533284
  severity: P2
  status: fixed_in_source_pr
  component: oauth_form_decode_budget
  summary: Fail closed when an authorization-code form candidate exceeds the scan bound.
  synthetic_reproduction: true
  security_boundary: structured OAuth evidence must not bypass bounded candidate exhaustion
  recommended_disposition: closed_by_final_head_fix; defer only separate provider/decode architecture
  allowed_reopen_condition: CI failure, regression caused by PR #188, or P1 only
  finding_present_at_final_head: false
  fix_commit: "833bdee"
  regression_test_present: true
  classification_basis: "Final-head form candidate overflow fails closed instead of accepting an unscanned suffix; tests/test_commander_contract.py::test_public_text_fails_closed_for_oversized_url_candidates and typed Artifact/Manifest overflow fixtures"

- id: F-009
  source_pr: 188
  source_comment_or_thread: https://github.com/JENN2046/colameta/pull/188#discussion_r3697533288
  severity: P2
  status: fixed_in_source_pr
  component: xml_candidate_bound
  summary: Fail closed on an oversized sensitive XML header.
  synthetic_reproduction: true
  security_boundary: structured XML evidence must honor the bounded header scan
  recommended_disposition: closed_by_final_head_fix; retain bounded-structure regression coverage
  allowed_reopen_condition: CI failure, regression caused by PR #188, or P1 only
  finding_present_at_final_head: false
  fix_commit: "7564149"
  regression_test_present: true
  classification_basis: "Final-head bounded XML header inspection fails closed when a sensitive label appears beyond a complete tag header; tests/test_commander_contract.py::test_public_text_redacts_sensitive_xml_elements and exact Artifact/Manifest fixtures"

- id: F-010
  source_pr: 188
  source_comment_or_thread: https://github.com/JENN2046/colameta/pull/188#discussion_r3697533291
  severity: P2
  status: fixed_in_source_pr
  component: gcs_signed_url_predicate
  summary: Redact Google Cloud Storage V2 signed URLs with the required query fields.
  synthetic_reproduction: true
  security_boundary: provider-specific capability URLs in public evidence
  recommended_disposition: closed_by_final_head_fix; defer only provider-registry architecture
  allowed_reopen_condition: CI failure, regression caused by PR #188, or P1 only
  finding_present_at_final_head: false
  fix_commit: "7564149"
  regression_test_present: true
  classification_basis: "Final-head bounded GCS V2 signed-query detection requires all three non-empty fields and covers JSON/percent/nested forms; tests/test_commander_contract.py::test_public_text_redacts_gcs_v2_signed_queries"

- id: F-011
  source_pr: 188
  source_comment_or_thread: https://github.com/JENN2046/colameta/pull/188#discussion_r3699201877
  severity: P2
  status: fixed_in_source_pr
  component: xml_entity_decode_private_path
  summary: Decode XML entities before scanning for private filesystem paths.
  synthetic_reproduction: true
  security_boundary: exact Artifact/Manifest evidence must not expose encoded private paths
  recommended_disposition: closed_by_final_head_fix; retain decode-closure regression coverage
  allowed_reopen_condition: CI failure, regression caused by PR #188, or P1 only
  finding_present_at_final_head: false
  fix_commit: "d6594b6"
  regression_test_present: true
  classification_basis: "Final-head XML entity decode closure reaches private-path and XML credential scans; tests/test_commander_contract.py::test_public_text_redacts_sensitive_xml_elements plus typed Artifact/Manifest entity fixtures"

- id: F-012
  source_pr: 188
  source_comment_or_thread: https://github.com/JENN2046/colameta/pull/188#discussion_r3699201880
  severity: P2
  status: fixed_in_source_pr
  component: vault_token_predicate
  summary: Redact standalone HashiCorp Vault service tokens with the hvs. prefix.
  synthetic_reproduction: true
  security_boundary: provider-token material in public evidence
  recommended_disposition: closed_by_final_head_fix; defer only provider-registry architecture
  allowed_reopen_condition: CI failure, regression caused by PR #188, or P1 only
  finding_present_at_final_head: false
  fix_commit: "4de051c"
  regression_test_present: true
  classification_basis: "Final-head decoded-candidate scanning recognizes standalone hvs. Vault service tokens and their encoded forms; Contract, Artifact, and Manifest regressions are present"

- id: F-013
  source_pr: 188
  source_comment_or_thread: https://github.com/JENN2046/colameta/pull/188#discussion_r3699254293
  severity: P2
  status: fixed_in_source_pr
  component: cloudfront_signed_cookie_predicate
  summary: Redact CloudFront signed-cookie triples outside a Cookie header.
  synthetic_reproduction: true
  security_boundary: provider capability material in structured or bare public evidence
  recommended_disposition: closed_by_final_head_fix; defer only provider-registry architecture
  allowed_reopen_condition: CI failure, regression caused by PR #188, or P1 only
  finding_present_at_final_head: false
  fix_commit: "fe469a8"
  regression_test_present: true
  classification_basis: "Final-head structured and bare CloudFront signed-cookie triples are rejected without requiring a Cookie header; Contract, Artifact, and Manifest regressions are present"

- id: F-014
  source_pr: 188
  source_comment_or_thread: https://github.com/JENN2046/colameta/pull/188#discussion_r3699466722
  severity: P2
  status: fixed_in_source_pr
  component: structured_python_repr_credentials
  summary: Reject single-quoted structured credential mappings in Python repr form.
  synthetic_reproduction: true
  security_boundary: structured Artifact/Manifest projection and Python repr decoding
  recommended_disposition: closed_by_final_head_fix; defer only predicate-registry architecture
  allowed_reopen_condition: CI failure, regression caused by PR #188, or P1 only
  finding_present_at_final_head: false
  fix_commit: "f80abc4"
  regression_test_present: true
  classification_basis: "Final-head bounded Python-literal parsing rejects single-quoted device/OAuth and private-JWK mappings while retaining safe public mappings; tests/test_commander_contract.py::test_public_text_fails_closed_for_oversized_python_repr_credentials"

- id: F-015
  source_pr: 188
  source_comment_or_thread: https://github.com/JENN2046/colameta/pull/188#discussion_r3699529793
  severity: P2
  status: fixed_in_source_pr
  component: slack_webhook_predicate
  summary: Redact Slack incoming-webhook URLs.
  synthetic_reproduction: true
  security_boundary: provider capability URLs in public evidence
  recommended_disposition: closed_by_final_head_fix; defer only provider-registry architecture
  allowed_reopen_condition: CI failure, regression caused by PR #188, or P1 only
  finding_present_at_final_head: false
  fix_commit: "7cb4308"
  regression_test_present: true
  classification_basis: "Final-head Slack incoming-webhook URL detection covers canonical, gov, encoded, and structured forms; tests/test_commander_contract.py::test_public_text_redacts_standalone_provider_access_tokens"

- id: F-016
  source_pr: 188
  source_comment_or_thread: https://github.com/JENN2046/colameta/pull/188#discussion_r3699605902
  severity: P2
  status: fixed_in_source_pr
  component: telegram_bot_url_predicate
  summary: Redact Telegram bot tokens embedded in Bot API URLs.
  synthetic_reproduction: true
  security_boundary: provider capability URLs in public evidence
  recommended_disposition: closed_by_final_head_fix; defer only provider-registry architecture
  allowed_reopen_condition: CI failure, regression caused by PR #188, or P1 only
  finding_present_at_final_head: false
  fix_commit: "701ead9"
  regression_test_present: true
  classification_basis: "Final-head Telegram Bot API URL detection covers direct, file, encoded, and nested forms; tests/test_commander_contract.py::test_public_text_redacts_standalone_telegram_bot_tokens"

- id: F-017
  source_pr: 188
  source_comment_or_thread: https://github.com/JENN2046/colameta/pull/188#discussion_r3699605906
  severity: P2
  status: fixed_in_source_pr
  component: commander_documentation_tool_inventory
  summary: Update the Verify inventory to the complete nine-tool Commander surface.
  synthetic_reproduction: not_applicable_documentation_only
  security_boundary: public documentation must match the nine-tool exposure contract
  recommended_disposition: closed_by_documentation_fix; retain documentation regression
  allowed_reopen_condition: CI failure, regression caused by PR #188, or P1 only
  finding_present_at_final_head: false
  fix_commit: "701ead9"
  regression_test_present: true
  classification_basis: "Final-head private-beta Verify inventory lists the complete nine-tool surface; tests/test_commander_public_docs.py::test_current_commander_inventory_guides_list_all_nine_public_tools"

- id: F-018
  source_pr: 188
  source_comment_or_thread: https://github.com/JENN2046/colameta/pull/188#discussion_r3699704231
  severity: P2
  status: fixed_in_source_pr
  component: commander_documentation_tool_count
  summary: Replace the remaining seven-tool statement in the implementation specification.
  synthetic_reproduction: not_applicable_documentation_only
  security_boundary: public documentation must not understate the exposed contract
  recommended_disposition: closed_by_documentation_fix; retain documentation regression
  allowed_reopen_condition: CI failure, regression caused by PR #188, or P1 only
  finding_present_at_final_head: false
  fix_commit: "67fd286"
  regression_test_present: true
  classification_basis: "Final-head operator protocol no longer contains the obsolete seven-tool statement; tests/test_commander_public_docs.py::test_current_commander_guides_do_not_restore_the_seven_tool_contract"

- id: F-019
  source_pr: 188
  source_comment_or_thread: https://github.com/JENN2046/colameta/pull/188#discussion_r3699859896
  severity: P2
  status: fixed_in_source_pr
  component: discord_webhook_predicate
  summary: Redact Discord incoming-webhook URLs.
  synthetic_reproduction: true
  security_boundary: provider capability URLs in public evidence
  recommended_disposition: closed_by_final_head_fix; defer only provider-registry architecture
  allowed_reopen_condition: CI failure, regression caused by PR #188, or P1 only
  finding_present_at_final_head: false
  fix_commit: "d5af28d"
  regression_test_present: true
  classification_basis: "Final-head Discord incoming-webhook URL detection covers canonical, canary/PTB, encoded, and structured forms; tests/test_commander_contract.py::test_public_text_redacts_standalone_provider_access_tokens"

- id: F-020
  source_pr: 188
  source_comment_or_thread: https://github.com/JENN2046/colameta/pull/188#discussion_r3699894958
  severity: P2
  status: fixed_in_source_pr
  component: structured_oauth_callback_predicate
  summary: Redact parsed OAuth callback code and state fields in mapping or JSON form.
  synthetic_reproduction: true
  security_boundary: structured OAuth evidence must remain sensitive after serialization
  recommended_disposition: closed_by_final_head_fix; defer only predicate-registry architecture
  allowed_reopen_condition: CI failure, regression caused by PR #188, or P1 only
  finding_present_at_final_head: false
  fix_commit: "a5d7d50"
  regression_test_present: true
  classification_basis: "Final-head same-object structured OAuth callback predicate covers JSON, Python repr, and nested serialization; tests/test_commander_contract.py::test_commander_response_omits_structured_oauth_callback"

- id: F-021
  source_pr: 188
  source_comment_or_thread: https://github.com/JENN2046/colameta/pull/188#discussion_r3699935988
  severity: P2
  status: fixed_in_source_pr
  component: stripe_webhook_secret_predicate
  summary: Redact standalone Stripe webhook signing secrets with the whsec_ prefix.
  synthetic_reproduction: true
  security_boundary: provider credential material in public evidence
  recommended_disposition: closed_by_final_head_fix; defer only provider-registry architecture
  allowed_reopen_condition: CI failure, regression caused by PR #188, or P1 only
  finding_present_at_final_head: false
  fix_commit: "7d6f00d"
  regression_test_present: true
  classification_basis: "Final-head bounded provider-token matching includes standalone whsec_ Stripe signing secrets and exact/encoded Artifact/Manifest fixtures"

- id: F-022
  source_pr: 188
  source_comment_or_thread: https://github.com/JENN2046/colameta/pull/188#discussion_r3699935989
  severity: P2
  status: fixed_in_source_pr
  component: valueless_assignment_template_boundary
  summary: Preserve valueless password-like assignment templates without treating them as credential values.
  synthetic_reproduction: true
  security_boundary: public text redaction must distinguish templates from populated assignments
  recommended_disposition: closed_by_final_head_fix; retain assignment-boundary regression coverage
  allowed_reopen_condition: CI failure, regression caused by PR #188, or P1 only
  finding_present_at_final_head: false
  fix_commit: "7d6f00d, 4caa8dd"
  regression_test_present: true
  classification_basis: "Final-head assignment scanning distinguishes empty/template values from populated values, including OAuth status context; tests/test_commander_contract.py::test_public_text_preserves_non_sensitive_key_prose"

- id: F-023
  source_pr: 188
  source_comment_or_thread: https://github.com/JENN2046/colameta/pull/188#discussion_r3699984030
  severity: P2
  status: fixed_in_source_pr
  component: punctuation_leading_assignment_value
  summary: Redact a credential assignment whose value begins with shell punctuation such as #.
  synthetic_reproduction: true
  security_boundary: public shell evidence must treat punctuation-leading assignment values as values
  recommended_disposition: closed_by_final_head_fix; retain assignment-boundary regression coverage
  allowed_reopen_condition: CI failure, regression caused by PR #188, or P1 only
  finding_present_at_final_head: false
  fix_commit: "4caa8dd"
  regression_test_present: true
  classification_basis: "Final-head assignment scanner treats # inside an assignment word as a non-empty value while preserving actual comments/templates; tests/test_commander_contract.py::test_public_text_fails_closed_for_multiword_sensitive_scalars"

- id: F-024
  source_pr: 188
  source_comment_or_thread: https://github.com/JENN2046/colameta/pull/188#discussion_r3701377878
  severity: P2
  status: fixed_in_source_pr
  component: onepassword_service_token_predicate
  summary: Redact standalone 1Password service-account tokens with the ops_ prefix.
  synthetic_reproduction: true
  security_boundary: provider-token material in public evidence
  recommended_disposition: closed_by_final_head_fix; defer only provider-registry architecture
  allowed_reopen_condition: CI failure, regression caused by PR #188, or P1 only
  finding_present_at_final_head: false
  fix_commit: "8b742f5"
  regression_test_present: true
  classification_basis: "Final-head decoded-candidate scanning recognizes standalone ops_ 1Password service tokens and exact/encoded Artifact/Manifest fixtures"
~~~

## Kubernetes Secret source thread (closed)

~~~yaml
- id: F-025
  source_pr: 188
  source_comment_or_thread: https://github.com/JENN2046/colameta/pull/188#discussion_r3701475706
  severity: P2
  status: fixed_in_source_pr
  component: kubernetes_secret_structured_credential_predicate
  summary: "Redact Kubernetes Secret payloads only when kind: Secret and data/stringData are non-empty mappings in the same object."
  synthetic_reproduction: true
  security_boundary: public Artifact/Manifest projection and exact evidence access
  recommended_disposition: closed by the final PR #188 fix; retain regression coverage on main
  allowed_reopen_condition: only a regression caused by the merged fix or a P1
  finding_present_at_final_head: false
  fix_commit: "4a0dbb7"
  regression_test_present: true
  classification_basis: "Final-head same-object exact kind: Secret predicate rejects non-empty data/stringData payloads across JSON/Python/encoded/nested forms and fails closed at depth/candidate exhaustion; Contract, Artifact, and Manifest regressions are present"
~~~

F-025 is shown separately only because its original thread was the final
freeze-head fix; it is included in the fixed count and has the same final-head
evidence fields as F-001–F-024. It is not classified as superseded. Resolved
review threads not represented by F-001–F-025 are closed under their existing
reply, stale, superseded, or already addressed by the merged PR. They are not
converted into untracked work. No P1 was found in the current 176-thread
review-thread query.

## Follow-up architecture boundary

The following are deliberately not implemented in PR #188 or this
reconciliation:

- a data-driven provider-token registry;
- a data-driven structured-credential predicate registry;
- decode-budget property or fuzz tests;

Those items belong to a separately planned follow-up batch. The documentation
items represented by F-003, F-017, and F-018 are already fixed in the source PR;
this register is a scope ledger, not an authorization to change product code.
