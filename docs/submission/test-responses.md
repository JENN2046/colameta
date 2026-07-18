# Test Responses Evidence

## prompt_id
T001

## observed_result
The real ChatGPT Apps connector smoke returned `ok=true` with
`project_count=5`; the registered-project result included
`colameta-self-dev`.

## evidence_link_or_notes
Observed through the real connector surface against the stable/public baseline
`8639e83d6a7a572e1db1be26267aef7737313643`. No token, cookie, raw log,
provider secret, or private registry file is reproduced in this evidence.

## review_status
Draft evidence only. Human reviewer must rerun from the final ChatGPT Apps connector surface before marking `test_prompts_ready` or `test_responses_ready` true.

## prompt_id
T002

## observed_result
`get_commander_app_manifest` returned `ok=true`, `read_only=true`, `project_name=colameta-self-dev`, 23 initial reads, 24 read actions, and a `release_submission_evidence` Commander panel section.

## evidence_link_or_notes
This proves the Commander manifest exposes the release evidence workflow in the read-only app surface. It does not prove rendered visual screenshots or mobile layout quality.

## review_status
Draft evidence only. Human reviewer must verify the rendered ChatGPT Apps panel before marking screenshots or metadata ready.

## prompt_id
T003

## observed_result
`get_product_console_map` returned `ok=true`, `source=product_console_map`, `read_only=true`, `status=blocked`, and a release evidence summary with `complete_count=0` of `total_count=10`.

## evidence_link_or_notes
The Product Console correctly reports blocked state instead of overstating readiness while evidence remains unreviewed.

## review_status
Draft evidence only. Current blocked status is expected and must not be treated as release approval.

## prompt_id
T004

## observed_result
The earlier readiness response was `ready=false` and `status=blocked`. Since
that capture, expected-head-bound public MCP preflight and the real Apps
connector smoke both passed at baseline
`8639e83d6a7a572e1db1be26267aef7737313643`; connector evidence gaps were 0
and stable replacement status was `stable_aligned`.

## evidence_link_or_notes
The old `PUBLIC_MCP_ENDPOINT_NOT_READY` observation is superseded by the later
baseline preflight. Submission evidence remains unready because the generated
metadata, security review, screenshots, test responses, and Dashboard form have
not received final human approval.

## review_status
Draft evidence only. Rerun this tool from a fresh connector session after the
annotation candidate is committed and the stable/public runtime is refreshed;
do not mark readiness from the superseded response.

## prompt_id
T005

## observed_result
`get_submission_evidence_auto_draft` returned `ok=true`, `source=submission_evidence_auto_draft`, `read_only=true`, `status=draft_ready`, `generated_keys=["mcp_tool_info"]`, and a copyable `fill_submission_evidence_files` tool call with `mark_ready=false`.

## evidence_link_or_notes
This proves the auto-draft path keeps generation separate from write and ready-state authority.

## review_status
Draft evidence only. Generated evidence must be reviewed and edited before any ready field is marked true.
