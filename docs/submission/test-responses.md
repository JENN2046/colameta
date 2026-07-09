# Test Responses Evidence

## prompt_id
T001

## observed_result
`list_registered_projects` returned `ok=true` with `project_count=1`; the first project name was `colameta-self-dev`.

## evidence_link_or_notes
Observed through a local MCPPlanningBridgeServer instance with a temporary registry containing only `/home/jenn/src/colameta-dev`. No token, cookie, raw log, provider response, or private registry file was read.

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
`get_release_submission_readiness` returned `ok=true`, `source=release_submission_readiness`, `read_only=true`, `ready=false`, `status=blocked`, and blocker codes `PRODUCT_READINESS_NOT_READY` and `PUBLIC_MCP_ENDPOINT_NOT_READY`. Evidence counts after this test evidence fill were `ready=0`, `filled_not_marked_ready=5`, `placeholder=5`, `not_started=0`.

## evidence_link_or_notes
The readiness packet preserves the public endpoint and product readiness blockers and keeps submission evidence unready until human review.

## review_status
Draft evidence only. This test should be rerun after stable/public endpoint readiness is restored.

## prompt_id
T005

## observed_result
`get_submission_evidence_auto_draft` returned `ok=true`, `source=submission_evidence_auto_draft`, `read_only=true`, `status=draft_ready`, `generated_keys=["mcp_tool_info"]`, and a copyable `fill_submission_evidence_files` tool call with `mark_ready=false`.

## evidence_link_or_notes
This proves the auto-draft path keeps generation separate from write and ready-state authority.

## review_status
Draft evidence only. Generated evidence must be reviewed and edited before any ready field is marked true.
